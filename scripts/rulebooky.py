#!/usr/bin/env python3
"""rulebooky CLI: install hooks, check health, manage the task card. Stdlib only.

  rulebooky.py install [--project DIR] [--python NAME]
  rulebooky.py doctor            check everything works; run this first when in doubt
  rulebooky.py uninstall [--purge]
  rulebooky.py lint | status | brief
  rulebooky.py task set --goal G [--method M] [--forbid REGEX]... [--min TOOL=N]... [--done-when D]
  rulebooky.py task add-req "text" | done N --evidence "..." | close [--force]
  rulebooky.py decide "text"
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

__version__ = "0.1.1"
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "hooks"))
import common as C  # noqa: E402

HOOKS = {
    "SessionStart": ("startup|resume|clear|compact", "inject.py session"),
    "UserPromptSubmit": (None, "inject.py prompt"),
    "PreToolUse": (".*", "guard.py"),
    "PostToolUse": (".*", "track.py"),
    "Stop": (None, "audit.py"),
}
MARK = "rulebooky/hooks/"
TIERS = ("hard", "process", "soft")
HARD_CHECKS = ("deny_bash", "deny_path", "block_new_files")
VAGUE = ("best practice", "clean code", "properly", "appropriate", "as needed",
         "good ", "efficient", "high quality", "robust")


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


def ours(entry):
    return any(MARK in h.get("command", "") for h in entry.get("hooks", []))


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
        cmd = '%s "$CLAUDE_PROJECT_DIR/.claude/rulebooky/hooks/%s"' % (py, script)
        entry = {"hooks": [{"type": "command", "command": cmd}]}
        if matcher:
            entry["matcher"] = matcher
        hooks[event] = kept + [entry]
    C.save_json(settings_p, settings)
    gi = proj / ".gitignore"
    cur = gi.read_text(encoding="utf-8") if gi.exists() else ""
    add = [l for l in (".claude/rulebooky/state.json", ".claude/rulebooky/hook-errors.log") if l not in cur]
    if add:
        gi.write_text(cur + ("" if cur.endswith("\n") or not cur else "\n") + "\n".join(add) + "\n",
                      encoding="utf-8")
    print("Installed into %s (hooks use: %s)" % (dst, py))
    print("Next: edit %s, then run `doctor`. Restart Claude Code so hooks load." % rules)


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
        for n in ("rulebooky.py", "state.json", "hook-errors.log"):
            (dst / n).unlink() if (dst / n).exists() else None
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
    try:
        settings = read_settings(proj / ".claude" / "settings.json")
        hooks = settings.get("hooks", {})
        for ev in HOOKS:
            found = [h["command"] for e in hooks.get(ev, []) if ours(e) for h in e["hooks"]]
            line(bool(found), "%s hook registered" % ev + ("" if found else " (run install, then restart Claude Code)"))
            if found and not interp:
                interp = found[0].split(" ")[0].strip('"')
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
    py = interp if interp and working_python(interp) else sys.executable
    guard = C.rl_dir() / "hooks" / "guard.py"
    if guard.exists():
        r = subprocess.run([py, str(guard)], input=json.dumps({"tool_name": "Bash", "tool_input": {"command": "echo hi"}}),
                           capture_output=True, text=True)
        line(r.returncode == 0, "guard.py runs and allows a harmless command")
        r = subprocess.run([py, str(C.rl_dir() / "hooks" / "inject.py"), "session"], input="{}",
                           capture_output=True, text=True, encoding="utf-8")
        line(r.returncode == 0 and "[RULEBOOKY]" in r.stdout, "inject.py prints the rules")
    print("\nAll good." if not bad else "\n%d problem(s). Fix the FAIL lines, then restart Claude Code." % len(bad))
    return 1 if bad else 0


def cmd_lint(a):
    rules = C.load_json(C.rules_path(), None)
    if rules is None:
        print("ERROR: no readable rules.json at %s (invalid JSON or missing)" % C.rules_path())
        return 1
    errs, warns, ids = [], [], set()
    rs = rules.get("rules", [])
    for r in rs:
        rid = r.get("id", "?")
        if rid in ids:
            errs.append("duplicate id: " + rid)
        ids.add(rid)
        if r.get("tier") not in TIERS:
            errs.append("%s: tier must be one of %s" % (rid, TIERS))
        if not r.get("text"):
            errs.append("%s: missing text" % rid)
        elif len(r["text"]) > 160:
            warns.append("%s: text over 160 chars, long rules get ignored" % rid)
        low = r.get("text", "").lower()
        for v in VAGUE:
            if v in low:
                warns.append("%s: vague wording '%s', make it checkable" % (rid, v.strip()))
        c = r.get("check")
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
                if c["type"] == "block_new_files" and not c.get("glob"):
                    errs.append("%s: block_new_files needs glob" % rid)
        if r.get("tier") == "process" and c:
            if c.get("type") != "min_calls" or not c.get("tool") or not str(c.get("n", "")).isdigit():
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


def cmd_status(a):
    need_installed()
    print(C.render(C.load_rules(), C.load_state()))
    return 0


def cmd_task(a):
    need_installed()
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
            if not tool or not n.isdigit():
                raise Fail("--min must look like WebSearch=5 (got %r)" % m)
            mins[tool] = int(n)
        st["task"] = {"goal": a.goal, "method": a.method or "", "forbid": a.forbid or [],
                      "min_calls": mins, "done_when": a.done_when or "", "reqs": []}
        st["counters"], st["stop_blocks"] = {}, 0
    elif not t:
        raise Fail("No open task. Run: task set --goal ...")
    elif a.sub == "add-req":
        t["reqs"].append({"text": a.text, "done": False, "evidence": ""})
    elif a.sub == "done":
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
    st = C.load_state()
    st["decisions"] = (st["decisions"] + [a.text])[-20:]
    C.save_state(st)
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


if __name__ == "__main__":
    main()
