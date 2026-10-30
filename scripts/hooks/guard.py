#!/usr/bin/env python3
"""PreToolUse: block hard-rule and task-card violations (exit 2 = block, stderr -> Claude)."""
import fnmatch
import importlib
import os
import re
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


def check(ev, rules, state):
    tool = ev.get("tool_name", "")
    inp = ev.get("tool_input") or {}
    problems = []
    hard = [r for r in rules["rules"] if r.get("tier") == "hard" and r.get("check")]
    forbid = (state.get("task") or {}).get("forbid", [])

    if tool == "Bash":
        cmd = inp.get("command", "")
        for r in hard:
            c = r["check"]
            if c["type"] == "deny_bash" and re.search(c["pattern"], cmd):
                problems.append(("rule '%s': %s" % (r["id"], r["text"]), r["id"], r["text"]))
        for pat in forbid:
            if re.search(pat, cmd):
                problems.append(("task card forbids /%s/" % pat, "task-forbid", pat))

    if tool in WRITE_TOOLS:
        path = inp.get("file_path") or inp.get("notebook_path") or ""
        norm_path = path.replace("\\", "/")
        base = os.path.basename(path)
        for r in hard:
            c = r["check"]
            if c["type"] == "deny_path" and re.search(c["pattern"], norm_path):
                problems.append(("rule '%s': %s" % (r["id"], r["text"]), r["id"], r["text"]))
            if (c["type"] == "block_new_files" and tool == "Write"
                    and fnmatch.fnmatch(base, c["glob"])
                    and base.lower() not in [a.lower() for a in c.get("allow", [])]
                    and not os.path.exists(path)):
                problems.append(("rule '%s': %s (new file: %s)" % (r["id"], r["text"], base), r["id"], r["text"]))
        for pat in forbid:
            if re.search(pat, norm_path):
                problems.append(("task card forbids /%s/" % pat, "task-forbid", pat))
    return problems


def inject_subagent_brief(ev, rules, state):
    """Inject RL brief into Task tool calls for subagent propagation."""
    if ev.get("tool_name") != "Task":
        return ev
    inp = ev.get("tool_input") or {}
    prompt = inp.get("prompt", "")
    if not prompt:
        return ev
    if "[RULEBOOKY]" in prompt:
        return ev
    brief = render(rules, state)
    if not brief.strip():
        return ev
    inp["prompt"] = brief + "\n\n---\n\n" + prompt
    ev["tool_input"] = inp
    _call("log_action", "subagent_inject", "Task", {"subagent_type": inp.get("subagent_type", "")}, "injected")
    return ev


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

    ev = inject_subagent_brief(ev, rules, state)
    tool = ev.get("tool_name", "")
    inp = ev.get("tool_input") or {}

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