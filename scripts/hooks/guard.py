#!/usr/bin/env python3
"""PreToolUse: block hard-rule and task-card violations (exit 2 = block, stderr -> Claude)."""
import fnmatch
import os
import re
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *  # noqa

WRITE_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")


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
                problems.append("rule '%s': %s" % (r["id"], r["text"]))
        for pat in forbid:
            if re.search(pat, cmd):
                problems.append("task card forbids /%s/" % pat)

    if tool in WRITE_TOOLS:
        path = inp.get("file_path") or inp.get("notebook_path") or ""
        base = os.path.basename(path)
        for r in hard:
            c = r["check"]
            if c["type"] == "deny_path" and re.search(c["pattern"], path):
                problems.append("rule '%s': %s" % (r["id"], r["text"]))
            if (c["type"] == "block_new_files" and tool == "Write"
                    and fnmatch.fnmatch(base, c["glob"])
                    and base not in c.get("allow", [])
                    and not os.path.exists(path)):
                problems.append("rule '%s': %s (new file: %s)" % (r["id"], r["text"], base))
        for pat in forbid:
            if re.search(pat, path):
                problems.append("task card forbids /%s/" % pat)
    return problems


def main():
    ev = read_event()
    problems = check(ev, load_rules(), load_state())
    if problems:
        sys.stderr.write("BLOCKED by rulebooky:\n- " + "\n- ".join(problems) +
                         "\nChoose a different approach that respects these rules. "
                         "Do not retry the same action.\n")
        sys.exit(2)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        log_error("guard: %r" % e)
    sys.exit(0)
