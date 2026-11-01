#!/usr/bin/env python3
"""PreToolUse: block hard-rule and task-card violations (exit 2 = block, stderr -> Claude)."""
import fnmatch
import importlib
import os
import re
import shlex
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import common lazily to catch import errors
_common_mod = None


WRITE_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")


def _C():
    """Get common module, loading it on first use."""
    global _common_mod
    if _common_mod is not None:
        return _common_mod
    try:
        _common_mod = importlib.import_module("common")
        return _common_mod
    except Exception as e:
        try:
            import time
            p = os.path.dirname(os.path.abspath(__file__))
            p = os.path.join(p, "..", "hook-errors.log")
            p = os.path.abspath(p)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "a", encoding="utf-8") as f:
                f.write("%s guard import: %r\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), e))
        except Exception:
            pass
        return None


def _call(name, *args, **kwargs):
    """Call a function from common module."""
    c = _C()
    if c is None:
        return None
    return getattr(c, name)(*args, **kwargs)


def _search(pattern, text, rid):
    """re.search that skips (and logs) a broken pattern instead of disabling every rule."""
    try:
        return re.search(pattern, text)
    except (re.error, TypeError) as e:
        _call("log_error", "guard: skipped rule %r, bad pattern %r: %s (run lint)" % (rid, pattern, e))
        return None


# CLI subcommands whose arguments are free text that often quotes forbidden words
# (evidence, rule text, test inputs). Not exempt: uninstall, rule remove/--replace.
_SAFE_CLI = {"task", "decide", "status", "brief", "lint", "test", "log", "history", "doctor", "discover"}


def is_own_cli_call(cmd):
    """True only for ONE plain call of the rulebooky CLI, e.g.
    python .claude/rulebooky/rulebooky.py task done 1 --evidence "removed rm -rf".
    Anything chained, piped, redirected or with command substitution is not exempt."""
    if not cmd or "`" in cmd or "$(" in cmd or "\n" in cmd or "\r" in cmd:
        return False
    try:
        lex = shlex.shlex(cmd, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        toks = list(lex)
    except ValueError:
        return False
    if len(toks) < 3 or any(t and all(ch in "();<>|&" for ch in t) for t in toks):
        return False
    exe = os.path.basename(toks[0].replace("\\", "/")).lower()
    if not re.fullmatch(r"(python[0-9.]*|py)(\.exe)?", exe):
        return False
    if not toks[1].replace("\\", "/").endswith(".claude/rulebooky/rulebooky.py"):
        return False
    sub = toks[2]
    if sub in _SAFE_CLI:
        return True
    if sub == "rule" and len(toks) > 3 and toks[3] in ("add", "list") and "--replace" not in toks:
        return True
    return False


def check(ev, rules, state):
    tool = ev.get("tool_name", "")
    inp = ev.get("tool_input")
    if not isinstance(inp, dict):
        inp = {}
    problems = []
    hard = [r for r in rules.get("rules", [])
            if isinstance(r, dict) and r.get("tier") == "hard" and isinstance(r.get("check"), dict)]
    forbid = (state.get("task") or {}).get("forbid") or []

    def hit(r, extra=""):
        problems.append(("rule '%s': %s%s" % (r.get("id"), r.get("text"), extra), r.get("id"), r.get("text")))

    if tool == "Bash":
        cmd = inp.get("command") or ""
        if not isinstance(cmd, str) or is_own_cli_call(cmd):
            cmd = ""
        for r in hard:
            c = r["check"]
            if c.get("type") == "deny_bash" and _search(c.get("pattern"), cmd, r.get("id")):
                hit(r)
        for pat in forbid:
            if _search(pat, cmd, "task-forbid"):
                problems.append(("task card forbids /%s/" % pat, "task-forbid", pat))

    if tool in WRITE_TOOLS:
        path = inp.get("file_path") or inp.get("notebook_path") or ""
        norm_path = path.replace("\\", "/")
        base = os.path.basename(norm_path)
        for r in hard:
            c = r["check"]
            if c.get("type") == "deny_path" and _search(c.get("pattern"), norm_path, r.get("id")):
                hit(r)
            if c.get("type") == "block_new_files" and tool == "Write" and c.get("glob"):
                allow = [str(a).lower() for a in (c.get("allow") or [])]
                if (fnmatch.fnmatch(base.lower(), str(c["glob"]).lower())
                        and base.lower() not in allow
                        and not os.path.exists(path)):
                    hit(r, " (new file: %s)" % base)
        for pat in forbid:
            if _search(pat, norm_path, "task-forbid"):
                problems.append(("task card forbids /%s/" % pat, "task-forbid", pat))
    return problems


def main():
    c = _C()
    if c is None:
        sys.exit(0)  # fail open
    c.setup_io()
    ev = c.read_event()
    tool = ev.get("tool_name", "")
    inp = ev.get("tool_input") or {}
    rules = c.load_rules()
    state = c.load_state()

    problems = check(ev, rules, state)
    if problems:
        for msg, rid, rtext in problems:
            _call("log_action", "blocked", tool, inp, "blocked", rid, rtext)
        sys.stderr.write("BLOCKED by rulebooky:\n- " + "\n- ".join(p[0] for p in problems) +
                         "\nChoose a different approach that respects these rules. "
                         "Do not retry the same action.\n")
        sys.exit(2)
    else:
        _call("log_action", "allowed", tool, inp, "allowed")
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        _call("log_error", "guard: %r" % e)
    sys.exit(0)