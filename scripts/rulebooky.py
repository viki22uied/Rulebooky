#!/usr/bin/env python3
"""rulebooky CLI: install hooks, check health, manage the task card. Stdlib only.

  rulebooky.py install [--project DIR] [--python NAME]
  rulebooky.py doctor            check everything works; run this first when in doubt
  rulebooky.py uninstall [--purge]
  rulebooky.py lint | status | brief
  rulebooky.py task set --goal G [--method M] [--forbid REGEX]... [--min TOOL=N]... [--done-when D]
  rulebooky.py task add-req "text" | done N --evidence "..." | close [--force]
  rulebooky.py decide "text"
  rulebooky.py rule add ID --tier hard|process|soft --text T [--deny-bash RE|--deny-path RE|--block-new GLOB [--allow F]...|--min TOOL=N] [--replace]
  rulebooky.py rule remove ID | rule list
  rulebooky.py discover [--apply] | test ... | log ... | history [ID] | sync push|pull|ci
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

__version__ = "0.2.1"
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "hooks"))
import common as C  # noqa: E402

HOOKS = {
    "SessionStart": ("startup|resume|clear|compact|fork", "inject.py session"),
    "UserPromptSubmit": (None, "inject.py prompt"),
    "SubagentStart": (None, "inject.py subagent"),
    "PreToolUse": (".*", "guard.py"),
    "PostToolUse": (".*", "track.py"),
    "Stop": (None, "audit.py"),
}
MARK = "rulebooky/hooks/"
# Runtime files: per-machine, never committed, removed by `uninstall --purge`.
RUNTIME_FILES = ("state.json", "state.lock", "hook-errors.log", "hook-errors.log.1",
                 "actions.log", "actions.log.1", "rules-history.jsonl", "rules-history.jsonl.1")
TIERS = ("hard", "process", "soft")
HARD_CHECKS = ("deny_bash", "deny_path", "block_new_files")
VAGUE = ("best practice", "clean code", "properly", "appropriate", "as needed",
         "good ", "efficient", "high quality", "robust")

# Rule discovery patterns
DISCOVERY_PATTERNS = [
    (r"(?i)don['\u2019]?t\s+(create|make|add|write)\s+(new\s+)?(\.md|markdown)\s+files?",
     {"id": "no-md-sprawl", "tier": "hard", "text": "Never create new .md files. Rules live only in .claude/rulebooky/rules.json.",
      "check": {"type": "block_new_files", "glob": "*.md", "allow": ["README.md", "CHANGELOG.md"]}}),
    (r"(?i)don['\u2019]?t\s+(run|use|execute)\s+git\s+push\s+.*--force",
     {"id": "no-force-push", "tier": "hard", "text": "Never run git push --force or reset --hard without asking.",
      "check": {"type": "deny_bash", "pattern": "git\\s+push\\s+.*--force|git\\s+reset\\s+--hard"}}),
    (r"(?i)don['\u2019]?t\s+(touch|modify|edit|change)\s+([`\"']?)migrations?/\2",
     {"id": "no-migrations-touch", "tier": "hard", "text": "Never touch migrations/ directory.",
      "check": {"type": "deny_path", "pattern": "migrations/"}}),
    (r"(?i)(search|research|look up|find)\s+(thoroughly|deeply|extensively|at least\s+(\d+)\s+times?)",
     {"id": "min-search", "tier": "process", "text": "Search thoroughly before answering (at least 3 WebSearch calls).",
      "check": {"type": "min_calls", "tool": "WebSearch", "n": 3}}),
    (r"(?i)don['\u2019]?t\s+(commit|push)\s+(secrets?|passwords?|keys?|tokens?|api[_-]?keys?)",
     {"id": "no-secrets", "tier": "hard", "text": "Never commit secrets, passwords, keys, or tokens.",
      "check": {"type": "deny_bash", "pattern": "(password|secret|api[_-]?key|token)\\s*="}}),
    (r"(?i)don['\u2019]?t\s+(install|add)\s+(packages?|dependencies|deps)\s+without\s+(asking|approval)",
     {"id": "no-deps-without-ask", "tier": "hard", "text": "Never install dependencies without asking.",
      "check": {"type": "deny_bash", "pattern": "(npm|yarn|pnpm|pip|poetry|go get|cargo add)\\s+(install|add)"}}),
    (r"(?i)(answer|respond|reply)\s+(in|with)\s+(short|brief|concise)\s+(point[-\s]?form|bullets?)",
     {"id": "point-form", "tier": "soft", "text": "Answer in short point-form unless asked otherwise."}),
    (r"(?i)don['\u2019]?t\s+(create|make)\s+(new\s+)?files?\s+(unless|without)\s+(necessary|needed|asked)",
     {"id": "no-unnecessary-files", "tier": "soft", "text": "Don't create new files unless necessary or asked."}),
    (r"(?i)(follow|adhere to|comply with)\s+([`\"']?)([^`\"'\n]+)\2",
     {"id": "follow-spec", "tier": "process", "text": "Follow the specified document/spec exactly.",
      "check": {"type": "min_calls", "tool": "Read", "n": 1}}),
]

RULE_FILES = ["CLAUDE.md", ".cursorrules", "AGENTS.md", ".clauderc", "rules.md", "instructions.md", "CONTRIBUTING.md"]
SKIP_DIRS = {"node_modules", ".git", ".claude", "skills", ".venv", "venv", "__pycache__", "dist", "build",
             ".tox", ".mypy_cache", ".pytest_cache", "target", "vendor"}


class Fail(Exception):
    """A problem the user can fix; printed without a traceback."""


# ---------- helpers ----------

def working_python(name):
    try:
        r = subprocess.run([name, "-c", "import sys;print(sys.version_info[0])"],
                           capture_output=True, text=True, timeout=15)
        return r.returncode == 0 and r.stdout.strip() == "3"
    except Exception:
        return False


def pick_python(override=None):
    """First interpreter that really runs Python 3 (skips the Windows Store stub)."""
    if override:
        if not working_python(override):
            raise Fail("--python %r does not run Python 3" % override)
        return override
    for name in ("python3", "python"):
        if shutil.which(name) and working_python(name):
            return name
    exe = sys.executable
    return '"%s"' % exe if " " in exe else exe


def read_settings(path):
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise Fail("%s is not valid JSON (%s). Fix it by hand; rulebooky will not overwrite it." % (path, e))
    if not isinstance(data, dict) or not isinstance(data.get("hooks", {}), dict):
        raise Fail("%s has an unexpected shape (need an object with an optional 'hooks' object)." % path)
    for ev, entries in data.get("hooks", {}).items():
        if not isinstance(entries, list):
            raise Fail("%s: hooks.%s must be a list." % (path, ev))
    return data


def hook_command(py, script):
    """Shell command for settings.json. Only the path is quoted; the mode argument
    (session/prompt/subagent) must stay OUTSIDE the quotes or Python looks for a
    file literally named "inject.py prompt" and exits 2, which blocks every prompt."""
    name, _, arg = script.partition(" ")
    return '%s "$CLAUDE_PROJECT_DIR/.claude/rulebooky/hooks/%s"%s' % (py, name, " " + arg if arg else "")


def hook_shell():
    """argv prefix that runs a hook command the way Claude Code does (sh, or Git Bash on Windows)."""
    if os.name != "nt":
        return ["sh", "-c"]
    # Windows: Claude Code uses Git Bash. Never pick System32\bash.exe (the WSL launcher).
    cands = [os.environ.get("CLAUDE_CODE_GIT_BASH_PATH")]
    git = shutil.which("git")
    if git:
        root = Path(git).resolve().parent.parent  # ...\Git\cmd\git.exe -> ...\Git
        cands += [str(root / "bin" / "bash.exe"), str(root / "usr" / "bin" / "bash.exe")]
    cands += [r"C:\Program Files\Git\bin\bash.exe", shutil.which("bash")]
    for c in cands:
        if c and Path(c).is_file() and "system32" not in c.lower():
            return [c, "-c"]
    return None


HOOK_PROBES = {
    "SessionStart": ({"hook_event_name": "SessionStart", "source": "startup"}, (0,), "[RULEBOOKY]"),
    "UserPromptSubmit": ({"hook_event_name": "UserPromptSubmit", "prompt": "doctor probe"}, (0,), "[RULEBOOKY]"),
    "SubagentStart": ({"hook_event_name": "SubagentStart", "agent_type": "Explore"}, (0,), "additionalContext"),
    "PreToolUse": ({"hook_event_name": "PreToolUse", "tool_name": "Read", "tool_input": {"file_path": "x"}}, (0,), None),
    "PostToolUse": ({"hook_event_name": "PostToolUse"}, (0,), None),
    "Stop": ({"hook_event_name": "Stop", "stop_hook_active": False}, (0, 2), None),  # 2 = open task, fine
}


def hook_interpreter(command):
    """First word of a hook command; handles a quoted path with spaces (Windows)."""
    command = command.strip()
    if command.startswith('"'):
        return command[1:].split('"', 1)[0]
    return command.split(" ", 1)[0]


def ours(entry):
    if not isinstance(entry, dict):
        return False
    return any(isinstance(h, dict) and MARK in str(h.get("command", "")) for h in entry.get("hooks") or [])


def need_installed():
    if not C.rl_dir().exists():
        raise Fail("rulebooky is not installed in this project (%s). Run: install" % C.project_dir())


# ---------- commands ----------

def cmd_install(a):
    if sys.version_info < (3, 8):
        raise Fail("Python 3.8+ required (you have %d.%d)" % sys.version_info[:2])
    proj = Path(a.project).resolve()
    if not proj.is_dir():
        raise Fail("project directory not found: %s" % proj)
    settings_p = proj / ".claude" / "settings.json"
    settings = read_settings(settings_p)  # validates BEFORE we touch anything
    py = pick_python(a.python)
    dst = proj / ".claude" / "rulebooky"
    (dst / "hooks").mkdir(parents=True, exist_ok=True)
    for f in (HERE / "hooks").glob("*.py"):
        shutil.copy2(str(f), str(dst / "hooks" / f.name))
    shutil.copy2(str(HERE / "rulebooky.py"), str(dst / "rulebooky.py"))
    rules = dst / "rules.json"
    if not rules.exists():
        shutil.copy2(str(HERE.parent / "templates" / "rules.json"), str(rules))
    if settings_p.exists():
        bak = settings_p.with_name("settings.json.rulebooky.bak")
        if not bak.exists():
            shutil.copy2(str(settings_p), str(bak))
    hooks = settings.setdefault("hooks", {})
    for event, (matcher, script) in HOOKS.items():
        kept = [e for e in hooks.get(event, []) if not ours(e)]
        cmd = hook_command(py, script)
        entry = {"hooks": [{"type": "command", "command": cmd}]}
        if matcher:
            entry["matcher"] = matcher
        hooks[event] = kept + [entry]
    C.save_json(settings_p, settings)
    gi = proj / ".gitignore"
    cur = gi.read_text(encoding="utf-8") if gi.exists() else ""
    have = set(cur.splitlines())
    add = [l for l in (".claude/rulebooky/state.json", ".claude/rulebooky/state.lock",
                       ".claude/rulebooky/hook-errors.log*",
                       ".claude/rulebooky/actions.log*", ".claude/rulebooky/rules-history.jsonl*",
                       ".claude/rulebooky/*.tmp")
           if l not in have]
    if add:
        gi.write_text(cur + ("" if cur.endswith("\n") or not cur else "\n") + "\n".join(add) + "\n",
                      encoding="utf-8")
    print("Installed into %s (hooks use: %s)" % (dst, py))
    print("Next: edit %s, then run `python .claude/rulebooky/rulebooky.py doctor`. Restart Claude Code so hooks load." % rules)


def cmd_uninstall(a):
    proj = Path(a.project).resolve()
    settings_p = proj / ".claude" / "settings.json"
    settings = read_settings(settings_p)
    hooks = settings.get("hooks", {})
    for ev in list(hooks):
        hooks[ev] = [e for e in hooks[ev] if not ours(e)]
        if not hooks[ev]:
            del hooks[ev]
    if "hooks" in settings and not settings["hooks"]:
        del settings["hooks"]
    if settings_p.exists():
        C.save_json(settings_p, settings)
    dst = proj / ".claude" / "rulebooky"
    if a.purge and dst.exists():
        shutil.rmtree(str(dst / "hooks"), ignore_errors=True)
        for n in ("rulebooky.py",) + RUNTIME_FILES:
            if (dst / n).exists():
                (dst / n).unlink()
        for tmp in dst.glob("*.tmp"):
            tmp.unlink()
        print("Removed hooks and scripts. Kept %s (your rules)." % (dst / "rules.json"))
    else:
        print("Hooks removed from settings.json. Files left in place (use --purge to delete them).")
    print("Restart Claude Code.")


def cmd_doctor(a):
    bad = []

    def line(ok, msg, fatal=True):
        print(("ok    " if ok else ("FAIL  " if fatal else "warn  ")) + msg)
        if not ok and fatal:
            bad.append(msg)

    proj = C.project_dir()
    print("rulebooky %s, project %s" % (__version__, proj))
    line(sys.version_info >= (3, 8), "Python %d.%d (need 3.8+)" % sys.version_info[:2])
    scripts = ("common.py", "inject.py", "guard.py", "track.py", "audit.py")
    missing = [s for s in scripts if not (C.rl_dir() / "hooks" / s).exists()]
    line(not missing, "hook scripts present" + (" (missing: %s; run install)" % ", ".join(missing) if missing else ""))
    interp = None
    registered = []
    try:
        settings = read_settings(proj / ".claude" / "settings.json")
        hooks = settings.get("hooks", {})
        for ev in HOOKS:
            found = [h["command"] for e in hooks.get(ev, []) if ours(e) for h in e["hooks"]
                     if isinstance(h, dict) and MARK in str(h.get("command", ""))]
            line(bool(found), "%s hook registered" % ev + ("" if found else " (run install, then restart Claude Code)"))
            registered.extend((ev, f) for f in found)
            if found and not interp:
                interp = hook_interpreter(found[0])
        if interp:
            line(working_python(interp), "hook interpreter '%s' runs Python 3" % interp +
                 ("" if working_python(interp) else " (re-run install with --python NAME)"))
    except Fail as e:
        line(False, str(e))
    if not (C.rl_dir() / "rules.json").exists():
        line(False, "rules.json missing (run install)")
    elif cmd_lint(a) != 0:
        line(False, "rules.json has errors (see above)")
    else:
        line(True, "rules.json valid")
    err = C.rl_dir() / "hook-errors.log"
    if err.exists() and err.read_text(encoding="utf-8", errors="replace").strip():
        tail = err.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-3:]
        line(False, "hook-errors.log has entries: " + " | ".join(tail), fatal=False)
    # Run every registered command exactly as Claude Code will: through a shell,
    # with $CLAUDE_PROJECT_DIR set. This catches quoting and path bugs.
    shell = hook_shell()
    if shell is None:
        line(False, "bash not found; cannot run hook commands (Claude Code on Windows uses Git Bash)", fatal=False)
    elif registered:
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(proj))
        sp = C.state_path()
        saved = sp.read_bytes() if sp.exists() else None  # probes must not change the task card
        for ev, cmd in registered:
            event, codes, want = HOOK_PROBES[ev]
            try:
                r = subprocess.run(shell + [cmd], input=json.dumps(event), capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", env=env, cwd=str(proj), timeout=30)
                ok = r.returncode in codes and (want is None or want in r.stdout)
                why = "" if ok else " (exit %d: %s)" % (r.returncode, (r.stderr or r.stdout).strip()[:200])
            except Exception as e:
                ok, why = False, " (%s)" % e
            line(ok, "%s hook command runs" % ev + why)
        if saved is not None:
            sp.write_bytes(saved)
    print("\nAll good." if not bad else "\n%d problem(s). Fix the FAIL lines, then restart Claude Code." % len(bad))
    if bad:
        print("Run: python .claude/rulebooky/rulebooky.py doctor  (after fixes)")
    return 1 if bad else 0


def cmd_lint(a):
    rules = C.load_json(C.rules_path(), None)
    if rules is None:
        print("ERROR: no readable rules.json at %s (invalid JSON or missing)" % C.rules_path())
        return 1
    errs, warns, ids = [], [], set()
    if not isinstance(rules, dict):
        print("ERROR: rules.json must be a JSON object with a \"rules\" list")
        return 1
    rs = rules.get("rules", [])
    if not isinstance(rs, list):
        print("ERROR: \"rules\" must be a list")
        return 1
    bad_entries = [x for x in rs if not isinstance(x, dict)]
    if bad_entries:
        errs.append("%d entr%s in \"rules\" not an object" % (len(bad_entries), "y is" if len(bad_entries) == 1 else "ies are"))
    rs = [x for x in rs if isinstance(x, dict)]
    msb = rules.get("max_stop_blocks", 3)
    if not isinstance(msb, int) or isinstance(msb, bool) or msb < 0:
        errs.append("max_stop_blocks must be a whole number >= 0")
    for r in rs:
        rid = str(r.get("id") or "?")
        if rid == "?":
            errs.append("a rule is missing its id")
        if rid in ids:
            errs.append("duplicate id: " + rid)
        ids.add(rid)
        if r.get("tier") not in TIERS:
            errs.append("%s: tier must be one of %s" % (rid, TIERS))
        if not r.get("text"):
            errs.append("%s: missing text" % rid)
        elif not isinstance(r["text"], str):
            errs.append("%s: text must be a string" % rid)
        elif len(r["text"]) > 160:
            warns.append("%s: text over 160 chars, long rules get ignored" % rid)
        low = str(r.get("text", "")).lower()
        for v in VAGUE:
            if v in low:
                warns.append("%s: vague wording '%s', make it checkable" % (rid, v.strip()))
        c = r.get("check")
        if c is not None and not isinstance(c, dict):
            errs.append("%s: check must be an object" % rid)
            continue
        if r.get("tier") == "hard":
            if not c or c.get("type") not in HARD_CHECKS:
                errs.append("%s: hard rule needs check.type in %s (else make it soft)" % (rid, HARD_CHECKS))
            else:
                pat = c.get("pattern")
                if c["type"] in ("deny_bash", "deny_path"):
                    if not pat:
                        errs.append("%s: missing pattern" % rid)
                    else:
                        try:
                            re.compile(pat)
                        except re.error as e:
                            errs.append("%s: bad regex: %s" % (rid, e))
                if c["type"] == "block_new_files":
                    if not c.get("glob"):
                        errs.append("%s: block_new_files needs glob" % rid)
                    if not isinstance(c.get("allow", []), list):
                        errs.append("%s: allow must be a list of file names" % rid)
        if r.get("tier") == "process" and c:
            if (c.get("type") != "min_calls" or not c.get("tool") or isinstance(c.get("n"), bool)
                    or not str(c.get("n", "")).isdigit()):
                errs.append("%s: process check must be {type:min_calls, tool, n}" % rid)
    soft = sum(1 for r in rs if r.get("tier") == "soft")
    if soft > 10:
        warns.append("%d soft rules; keep <=10, extra ones dilute the rest" % soft)
    if len(rs) > 25:
        warns.append("%d rules total; cap is 25, prune" % len(rs))
    proj = C.project_dir()
    mds = [p for p in list((proj / ".claude").rglob("*.md")) + list(proj.glob("*.md"))
           if "node_modules" not in p.parts and ".git" not in p.parts and "skills" not in p.parts]
    if len(mds) > 6:
        warns.append("%d markdown files in project root/.claude; rules should live only in rules.json" % len(mds))
    for e in errs:
        print("ERROR: " + e)
    for w in warns:
        print("WARN:  " + w)
    print("%d rules (%d hard, %d process, %d soft)" % (
        len(rs), sum(r.get("tier") == "hard" for r in rs),
        sum(r.get("tier") == "process" for r in rs), soft))
    return 1 if errs else 0


# ---------- rule discovery ----------

def extract_rules_from_text(text, source):
    """Extract candidate rules from rule document text."""
    found = []
    for pattern, template in DISCOVERY_PATTERNS:
        matches = list(re.finditer(pattern, text))
        if matches:
            rule = dict(template)
            rule["_source"] = source
            rule["_matches"] = [m.group(0) for m in matches[:3]]
            found.append(rule)
    return found


def scan_rule_files(proj):
    """Scan project for common rule files and extract rules."""
    all_found = []
    wanted = set(RULE_FILES)
    paths = []
    for root, dirs, files in os.walk(str(proj)):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)  # prune: never walk node_modules etc.
        paths.extend(Path(root) / f for f in sorted(files) if f in wanted)
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            all_found.extend(extract_rules_from_text(text, str(path.relative_to(proj))))
        except Exception:
            pass
    return all_found


def deduplicate_rules(rules):
    """Merge rules with same id, keeping first."""
    seen = {}
    for r in rules:
        rid = r.get("id")
        if rid not in seen:
            seen[rid] = r
    return list(seen.values())


def cmd_discover(a):
    need_installed()
    proj = C.project_dir()

    print(f"Scanning {proj} for rule files...")
    found = scan_rule_files(proj)
    found = deduplicate_rules(found)

    if not found:
        print("No recognizable rules found in common rule files.")
        print("Checked:", ", ".join(RULE_FILES))
        return 0

    print(f"\nFound {len(found)} candidate rule(s):\n")

    rules_path = C.rules_path()
    existing = C.load_json(rules_path, {"rules": []})
    existing_ids = {r.get("id") for r in existing.get("rules", [])}

    to_add = []
    for r in found:
        rid = r.get("id")
        status = "EXISTS" if rid in existing_ids else "NEW"
        print(f"  [{status}] {rid} ({r.get('tier')}) - {r.get('text')}")
        if r.get("_matches"):
            for m in r["_matches"]:
                print(f"      matched: \"{m[:100]}\"")
        if status == "NEW":
            to_add.append(r)

    if not to_add:
        print("\nAll rules already exist in rules.json")
        return 0

    if a.apply:
        for r in to_add:
            clean = {k: v for k, v in r.items() if not k.startswith("_")}
            existing["rules"].append(clean)
        C.save_json(rules_path, existing)
        print(f"\nApplied {len(to_add)} new rule(s) to {rules_path}")
        print("Run: python .claude/rulebooky/rulebooky.py lint")
    else:
        print(f"\nRun with --apply to add {len(to_add)} new rule(s) to rules.json")
    return 0


# ---------- rule test sandbox ----------

def simulate_tool_call(tool_name, tool_input, rules, state):
    """Simulate guard.py check without blocking."""
    import guard  # hooks/ is on sys.path
    ev = {"tool_name": tool_name, "tool_input": tool_input if isinstance(tool_input, dict) else {}}
    return [msg for msg, _rid, _text in guard.check(ev, rules, state)]


def rules_from(data):
    """Accept one rule object, a list of rules, or a whole rules.json."""
    if isinstance(data, dict) and isinstance(data.get("rules"), list):
        return {"rules": data["rules"]}
    if isinstance(data, dict):
        return {"rules": [data]}
    if isinstance(data, list):
        return {"rules": data}
    raise Fail("rule data must be a rule object, a list of rules, or a rules.json object")


def cmd_test(a):
    need_installed()
    rules = C.load_rules()
    state = C.load_state()

    if a.rule_file:
        rule_data = C.load_json(a.rule_file, None)
        if rule_data is None:
            raise Fail(f"Cannot read rule file: {a.rule_file}")
        test_rules = rules_from(rule_data)
    elif a.rule_json:
        try:
            rule_data = json.loads(a.rule_json)
        except json.JSONDecodeError as e:
            raise Fail(f"Invalid JSON: {e}")
        test_rules = rules_from(rule_data)
    else:
        test_rules = rules

    if a.tool and a.input:
        try:
            tool_input = json.loads(a.input)
        except json.JSONDecodeError as e:
            raise Fail(f"Invalid input JSON: {e}")
        problems = simulate_tool_call(a.tool, tool_input, test_rules, state)
        if problems:
            print("BLOCKED:")
            for p in problems:
                print(f"  - {p}")
        else:
            print("ALLOWED: No rule violations")
    elif a.scenario:
        # Run multiple test cases from a scenario file
        scenario = C.load_json(a.scenario, None)
        if not isinstance(scenario, dict) or not isinstance(scenario.get("tests"), list):
            raise Fail("Scenario file must be a JSON object with a 'tests' array")
        mismatches = 0
        for i, test in enumerate(scenario["tests"], 1):
            if not isinstance(test, dict):
                raise Fail("test %d is not an object" % i)
            tool = test.get("tool")
            inp = test.get("input", {})
            expected = test.get("expected", "allowed")
            if expected not in ("allowed", "blocked"):
                raise Fail("test %d: expected must be 'allowed' or 'blocked' (got %r)" % (i, expected))
            problems = simulate_tool_call(tool, inp, test_rules, state)
            status = "blocked" if problems else "allowed"
            ok = status == expected
            mismatches += not ok
            print("Test %d: %s %s (expected %s) - %s" % (i, "PASS" if ok else "FAIL", status.upper(), expected, tool))
            for p in problems:
                print("    - " + p)
        print("\n%d/%d scenario test(s) matched" % (len(scenario["tests"]) - mismatches, len(scenario["tests"])))
        return 1 if mismatches else 0
    else:
        raise Fail("Provide --tool/--input or --scenario")
    return 0


# ---------- observability log ----------

def parse_since(since_str):
    """Parse '7d', '24h', '30m', '10s' into an epoch timestamp."""
    m = re.fullmatch(r"\s*(\d+)\s*([dhms])\s*", since_str or "")
    if not m:
        raise Fail("--since must look like 7d, 24h, 30m or 10s (got %r)" % since_str)
    val, unit = int(m.group(1)), m.group(2)
    mult = {"d": 86400, "h": 3600, "m": 60, "s": 1}
    return time.time() - val * mult[unit]


def cmd_log(a):
    need_installed()
    log_path = C.rl_dir() / "actions.log"
    if not log_path.exists():
        print("No actions.log found. Run some tasks first.")
        return 0

    since_ts = parse_since(a.since) if a.since else 0
    filter_type = a.type
    filter_tool = a.tool

    entries = []
    with open(str(log_path), encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if not isinstance(entry, dict):
                    continue
                if since_ts and entry.get("ts"):
                    try:
                        entry_ts = time.mktime(time.strptime(entry["ts"], "%Y-%m-%d %H:%M:%S"))
                        if entry_ts < since_ts:
                            continue
                    except Exception:
                        pass
                if filter_type and entry.get("type") != filter_type:
                    continue
                if filter_tool and entry.get("tool") != filter_tool:
                    continue
                entries.append(entry)
            except json.JSONDecodeError:
                pass

    if a.format == "json":
        print(json.dumps(entries, indent=2))
        return 0

    if not entries:
        print("No matching log entries.")
        return 0

    # Summary stats
    blocked = sum(1 for e in entries if e.get("result") == "blocked")
    allowed = sum(1 for e in entries if e.get("result") == "allowed")
    stop_blocks = sum(1 for e in entries if e.get("type") == "stop_block")

    print(f"Total: {len(entries)} | Blocked: {blocked} | Allowed: {allowed} | Stop blocks: {stop_blocks}")
    print()

    if a.format == "summary":
        # Group by rule
        by_rule = {}
        for e in entries:
            if e.get("type") == "blocked":
                rid = e.get("rule_id") or "unknown"
                by_rule[rid] = by_rule.get(rid, 0) + 1
        if by_rule:
            print("Blocks by rule:")
            for rid, count in sorted(by_rule.items(), key=lambda x: -x[1]):
                print(f"  {rid}: {count}")
        return 0

    # Default: table format
    for e in entries[-a.limit:] if a.limit > 0 else entries:
        ts = str(e.get("ts") or "")
        typ = str(e.get("type") or "")
        tool = str(e.get("tool") or "")
        rule = str(e.get("rule_id") or "")
        text = str(e.get("rule_text") or "")[:60]
        if typ == "blocked":
            print(f"{ts}  BLOCKED  {tool:12}  {rule:20}  {text}")
        elif typ == "stop_block":
            print(f"{ts}  STOP_BLOCK                    {rule:20}  {text}")
        elif typ == "subagent_inject":
            print(f"{ts}  SUBAGENT {tool:12}  rules + task card injected")
        else:
            print(f"{ts}  ALLOWED  {tool:12}")
    return 0


# ---------- rule history / blame ----------

def cmd_history(a):
    need_installed()
    hist_path = C.rl_dir() / "rules-history.jsonl"
    if not hist_path.exists():
        print("No rules-history.jsonl found.")
        return 0

    entries = []
    with open(hist_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

    if not entries:
        print("rules-history.jsonl is empty.")
        return 0

    def ids_of(e):
        return [i for i in (e.get("rule_ids") or []) if i]

    if a.rule_id:
        # Blame mode: show when the rule was added and removed
        present, found = False, False
        for e in entries:
            now = a.rule_id in ids_of(e)
            if now != present:
                print("%s  v%s  %s  %s" % (e.get("ts", "?"), e.get("version", 1),
                                           "added" if now else "removed", a.rule_id))
                found = True
            present = now
        if not found:
            print("Rule '%s' not found in history" % a.rule_id)
        return 0

    # Full history: each line shows what changed against the entry before it
    start = max(0, len(entries) - a.limit) if a.limit > 0 else 0
    for idx in range(start, len(entries)):
        e = entries[idx]
        cur = ids_of(e)
        if idx == 0:
            change_str = "init %d rules" % len(cur)
        else:
            prev = ids_of(entries[idx - 1])
            added = [i for i in cur if i not in prev]
            removed = [i for i in prev if i not in cur]
            changes = (["+" + ",".join(added)] if added else []) + (["-" + ",".join(removed)] if removed else [])
            change_str = " ".join(changes) if changes else "edited (same ids)"
        print("%s  v%s  %s rules  %s" % (e.get("ts", "?"), e.get("version", 1), e.get("rules_count", len(cur)), change_str))
    return 0


# ---------- team sync ----------

def gh(args, stdin=None):
    """Run the GitHub CLI; friendly error if it is missing."""
    try:
        return subprocess.run(["gh"] + args, input=stdin, capture_output=True, text=True, encoding="utf-8")
    except FileNotFoundError:
        raise Fail("GitHub CLI (gh) not installed. Install: https://cli.github.com, then run: gh auth login")


def fetch_remote_rules(gist_id):
    r = gh(["gist", "view", gist_id, "--raw", "--filename", "rules.json"])
    if r.returncode != 0:
        raise Fail("Cannot fetch gist %s: %s" % (gist_id, r.stderr.strip()))
    try:
        data = json.loads(r.stdout)
    except ValueError as e:
        raise Fail("gist %s does not hold valid rules.json JSON: %s" % (gist_id, e))
    if not isinstance(data, dict) or not isinstance(data.get("rules"), list):
        raise Fail("gist %s rules.json must be an object with a \"rules\" list" % gist_id)
    return data


def cmd_sync(a):
    need_installed()
    rules_path = C.rules_path()
    rules = C.load_json(rules_path, None)
    if not isinstance(rules, dict):
        raise Fail("No readable rules.json")
    gist_id = a.gist_id or rules.get("gist_id")

    if a.sub == "push":
        content = json.dumps(rules, indent=2, ensure_ascii=False)
        if gist_id:
            # Update the existing gist in place (never create duplicates).
            tmpdir = tempfile.mkdtemp(prefix="rulebooky-")
            try:
                tmp = Path(tmpdir) / "rules.json"
                tmp.write_text(content, encoding="utf-8")
                r = gh(["gist", "edit", gist_id, "--filename", "rules.json", str(tmp)])
            finally:
                shutil.rmtree(tmpdir, ignore_errors=True)
            if r.returncode != 0:
                raise Fail("gh gist edit failed: %s" % r.stderr.strip())
            print("Pushed to gist %s" % gist_id)
        else:
            desc = "rulebooky rules for %s" % C.project_dir().name
            r = gh(["gist", "create", "--desc", desc, "--filename", "rules.json", "-"], stdin=content)
            if r.returncode != 0:
                raise Fail("gh gist create failed: %s" % r.stderr.strip())
            url = r.stdout.strip()
            m = re.search(r"([0-9a-f]{20,})\s*$", url)
            if m:
                rules["gist_id"] = m.group(1)
                C.save_json(rules_path, rules)
                print("Saved gist_id %s in rules.json (commit it so your team can pull)." % m.group(1))
            print("Pushed to: %s" % url)
        return 0

    if not gist_id:
        if a.sub == "ci":
            print("No remote gist configured. Skipping CI check.")
            return 0
        raise Fail("No gist_id. Provide --gist-id or run push first.")
    remote = fetch_remote_rules(gist_id)

    if a.sub == "pull":
        remote.setdefault("gist_id", gist_id)
        C.save_json(rules_path, remote)
        print("Pulled rules from gist %s (%d rules)" % (gist_id, len(remote["rules"])))
        print("Run: python .claude/rulebooky/rulebooky.py lint")
        return 0

    # ci: exit 1 if local rules differ from remote (ignores version and gist_id)
    def by_id(data):
        return {r["id"]: r for r in data.get("rules", []) if isinstance(r, dict) and r.get("id")}
    local_ids, remote_ids = by_id(rules), by_id(remote)
    if local_ids.keys() != remote_ids.keys():
        print("RULES DIVERGED: Rule IDs differ")
        print("  Local only:  %s" % sorted(set(local_ids) - set(remote_ids)))
        print("  Remote only: %s" % sorted(set(remote_ids) - set(local_ids)))
        return 1
    for rid, local in local_ids.items():
        other = remote_ids[rid]
        if any(local.get(k) != other.get(k) for k in ("text", "tier", "check")):
            print("RULE DIVERGED: %s" % rid)
            print("  Local:  %s" % json.dumps({k: local.get(k) for k in ("tier", "text", "check")}, ensure_ascii=False))
            print("  Remote: %s" % json.dumps({k: other.get(k) for k in ("tier", "text", "check")}, ensure_ascii=False))
            return 1
    print("CI OK: rules.json matches remote")
    return 0


def cmd_rule(a):
    """Add/remove/list rules from the CLI. Claude Code treats .claude/ files as
    sensitive and refuses or prompts for direct Write/Edit, so this is how
    Claude changes rules.json."""
    need_installed()
    rp = C.rules_path()
    data = C.load_json(rp, None) if rp.exists() else {"version": 1, "max_stop_blocks": 3, "canary": "", "rules": []}
    if not isinstance(data, dict) or not isinstance(data.get("rules"), list):
        raise Fail("rules.json is not valid (run lint); refusing to overwrite it")
    rules = data["rules"]
    if a.sub == "list":
        for r in rules:
            if isinstance(r, dict):
                print("%-24s %-8s %s%s" % (r.get("id"), r.get("tier"), r.get("text"),
                                          "  check=" + json.dumps(r["check"]) if r.get("check") else ""))
        return 0
    if a.sub == "remove":
        keep = [r for r in rules if not (isinstance(r, dict) and r.get("id") == a.id)]
        if len(keep) == len(rules):
            raise Fail("No rule with id %r. Use `rule list`." % a.id)
        data["rules"] = keep
        C.save_json(rp, data)
        print("Removed rule %s." % a.id)
        return cmd_lint(a)
    # add
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", a.id):
        raise Fail("id must be a short slug like no-rm-rf (letters, digits, - _ .)")
    if not a.text.strip():
        raise Fail("--text is empty")
    checks = []
    for kind, pat in (("deny_bash", a.deny_bash), ("deny_path", a.deny_path)):
        if pat is not None:
            try:
                re.compile(pat)
            except re.error as e:
                raise Fail("--%s %r is not a valid regex: %s" % (kind.replace("_", "-"), pat, e))
            checks.append({"type": kind, "pattern": pat})
    if a.block_new is not None:
        checks.append({"type": "block_new_files", "glob": a.block_new, "allow": a.allow or []})
    elif a.allow:
        raise Fail("--allow only works with --block-new")
    if a.min is not None:
        tool, _, n = a.min.partition("=")
        if not tool.strip() or not n.strip().isdigit():
            raise Fail("--min must look like WebSearch=5 (got %r)" % a.min)
        checks.append({"type": "min_calls", "tool": tool.strip(), "n": int(n)})
    if len(checks) > 1:
        raise Fail("one check per rule; add several rules instead")
    check = checks[0] if checks else None
    if a.tier == "hard" and (not check or check["type"] not in HARD_CHECKS):
        raise Fail("a hard rule needs --deny-bash, --deny-path or --block-new (else use --tier soft)")
    if a.tier == "process" and check and check["type"] != "min_calls":
        raise Fail("a process rule takes only --min TOOL=N")
    if a.tier == "soft" and check:
        raise Fail("a soft rule has no check; use --tier hard or process")
    rule = {"id": a.id, "tier": a.tier, "text": a.text.strip()}
    if check:
        rule["check"] = check
    idx = [i for i, r in enumerate(rules) if isinstance(r, dict) and r.get("id") == a.id]
    if idx and not a.replace:
        raise Fail("rule %r already exists; pass --replace to overwrite it" % a.id)
    if idx:
        rules[idx[0]] = rule
    else:
        rules.append(rule)
    C.save_json(rp, data)
    print("%s rule %s." % ("Replaced" if idx else "Added", a.id))
    return cmd_lint(a)


def cmd_status(a):
    need_installed()
    print(C.render(C.load_rules(), C.load_state()))
    return 0


def cmd_task(a):
    need_installed()
    with C.state_lock():
        return _task(a)


def _task(a):
    st = C.load_state()
    t = st.get("task")
    if a.sub == "set":
        for pat in a.forbid or []:
            try:
                re.compile(pat)
            except re.error as e:
                raise Fail("--forbid %r is not a valid regex: %s" % (pat, e))
        mins = {}
        for m in a.min or []:
            tool, _, n = m.partition("=")
            tool, n = tool.strip(), n.strip()
            if not tool or not n.isdigit():
                raise Fail("--min must look like WebSearch=5 (got %r)" % m)
            mins[tool] = int(n)
        st["task"] = {"goal": a.goal, "method": a.method or "", "forbid": a.forbid or [],
                      "min_calls": mins, "done_when": a.done_when or "", "reqs": []}
        st["counters"], st["stop_blocks"] = {}, 0
    elif not t:
        raise Fail("No open task. Run: task set --goal ...")
    elif a.sub == "add-req":
        if not a.text.strip():
            raise Fail("Requirement text is empty.")
        t.setdefault("reqs", [])
        t["reqs"].append({"text": a.text, "done": False, "evidence": ""})
    elif a.sub == "done":
        t.setdefault("reqs", [])
        if not 1 <= a.n <= len(t["reqs"]):
            raise Fail("No requirement %d (task has %d). Use `status` to list them." % (a.n, len(t["reqs"])))
        if not a.evidence.strip():
            raise Fail("Evidence required (file:line, command output, URL).")
        t["reqs"][a.n - 1].update(done=True, evidence=a.evidence)
    elif a.sub == "close":
        left = C.open_reqs(t)
        if left and not a.force:
            raise Fail("Open requirements remain: %s. Use --force only if the user dropped them." %
                       [i for i, _ in left])
        st["task"], st["counters"], st["stop_blocks"] = None, {}, 0
    C.save_state(st)
    print(C.render(C.load_rules(), st))
    return 0


def cmd_decide(a):
    need_installed()
    with C.state_lock():
        return _decide(a)


def _decide(a):
    st = C.load_state()
    if not a.text.strip():
        raise Fail("Decision text is empty.")
    st["decisions"] = (st["decisions"] + [a.text])[-20:]
    C.save_state(st)
    print("Saved decision (%d kept)." % len(st["decisions"]))
    return 0


def main():
    C.setup_io()
    p = argparse.ArgumentParser(prog="rulebooky")
    p.add_argument("--version", action="version", version=__version__)
    sp = p.add_subparsers(dest="cmd", required=True)
    i = sp.add_parser("install"); i.add_argument("--project", default="."); i.add_argument("--python")
    i.set_defaults(f=cmd_install)
    u = sp.add_parser("uninstall"); u.add_argument("--project", default=".")
    u.add_argument("--purge", action="store_true"); u.set_defaults(f=cmd_uninstall)
    sp.add_parser("doctor").set_defaults(f=cmd_doctor)
    sp.add_parser("lint").set_defaults(f=cmd_lint)
    sp.add_parser("status").set_defaults(f=cmd_status)
    sp.add_parser("brief").set_defaults(f=cmd_status)
    d = sp.add_parser("decide"); d.add_argument("text"); d.set_defaults(f=cmd_decide)
    rl = sp.add_parser("rule", help="add/remove/list rules (use this, not direct edits of rules.json)")
    rls = rl.add_subparsers(dest="sub", required=True)
    ra = rls.add_parser("add"); ra.add_argument("id")
    ra.add_argument("--tier", choices=TIERS, required=True); ra.add_argument("--text", required=True)
    ra.add_argument("--deny-bash"); ra.add_argument("--deny-path"); ra.add_argument("--block-new", metavar="GLOB")
    ra.add_argument("--allow", action="append", metavar="FILENAME"); ra.add_argument("--min", metavar="TOOL=N")
    ra.add_argument("--replace", action="store_true")
    rr = rls.add_parser("remove"); rr.add_argument("id")
    rls.add_parser("list")
    rl.set_defaults(f=cmd_rule)
    disc = sp.add_parser("discover"); disc.add_argument("--apply", action="store_true"); disc.set_defaults(f=cmd_discover)
    test = sp.add_parser("test")
    test.add_argument("--rule-file"); test.add_argument("--rule-json")
    test.add_argument("--tool"); test.add_argument("--input")
    test.add_argument("--scenario")
    test.set_defaults(f=cmd_test)
    log = sp.add_parser("log")
    log.add_argument("--since", help="Time window: 7d, 24h, 30m")
    log.add_argument("--type", help="Filter by type: blocked, allowed, stop_block")
    log.add_argument("--tool", help="Filter by tool name")
    log.add_argument("--format", choices=["table", "json", "summary"], default="table")
    log.add_argument("--limit", type=int, default=50)
    log.set_defaults(f=cmd_log)
    hist = sp.add_parser("history")
    hist.add_argument("rule_id", nargs="?", help="Show history for specific rule (blame)")
    hist.add_argument("--limit", type=int, default=20)
    hist.set_defaults(f=cmd_history)
    sync = sp.add_parser("sync")
    sync_sub = sync.add_subparsers(dest="sub", required=True)
    sp_push = sync_sub.add_parser("push")
    sp_push.add_argument("--gist-id")
    sp_push.set_defaults(f=cmd_sync)
    sp_pull = sync_sub.add_parser("pull")
    sp_pull.add_argument("--gist-id")
    sp_pull.set_defaults(f=cmd_sync)
    sp_ci = sync_sub.add_parser("ci")
    sp_ci.add_argument("--gist-id")
    sp_ci.set_defaults(f=cmd_sync)
    t = sp.add_parser("task"); ts = t.add_subparsers(dest="sub", required=True)
    s = ts.add_parser("set"); s.add_argument("--goal", required=True); s.add_argument("--method")
    s.add_argument("--forbid", action="append"); s.add_argument("--min", action="append")
    s.add_argument("--done-when")
    ar = ts.add_parser("add-req"); ar.add_argument("text")
    dn = ts.add_parser("done"); dn.add_argument("n", type=int); dn.add_argument("--evidence", required=True)
    cl = ts.add_parser("close"); cl.add_argument("--force", action="store_true")
    t.set_defaults(f=cmd_task)
    a = p.parse_args()
    try:
        sys.exit(a.f(a) or 0)
    except Fail as e:
        print("rulebooky: %s" % e)
        sys.exit(1)
    except BrokenPipeError:  # output piped into `head` etc.
        try:
            sys.stdout = open(os.devnull, "w")
        except Exception:
            pass
        sys.exit(0)


if __name__ == "__main__":
    main()
