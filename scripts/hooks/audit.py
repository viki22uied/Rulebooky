#!/usr/bin/env python3
"""Stop: refuse to let Claude finish while an open task has unmet checks (exit 2)."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *  # noqa


def problems_for(rules, state):
    task = state.get("task")
    if not task:
        return []
    probs = []
    for tool, n in min_calls_required(rules, state).items():
        have = state["counters"].get(tool, 0)
        if have < n:
            probs.append("%s used %d/%d times (required for this task)" % (tool, have, n))
    for i, r in open_reqs(task):
        probs.append("Requirement %d not done with evidence: %s" % (i, r["text"]))
    return probs


def main():
    read_event()
    rules, state = load_rules(), load_state()
    probs = problems_for(rules, state)
    if not probs:
        if state.get("stop_blocks"):
            state["stop_blocks"] = 0
            save_state(state)
        return
    limit = int(rules.get("max_stop_blocks", 3))
    if state.get("stop_blocks", 0) >= limit:
        # escape hatch so a bad task card cannot trap the session forever
        sys.stderr.write("rulebooky: stop allowed after %d blocks, UNMET: %s\n" % (limit, "; ".join(probs)))
        return
    state["stop_blocks"] = state.get("stop_blocks", 0) + 1
    save_state(state)
    sys.stderr.write("Do not finish yet. Unmet:\n- " + "\n- ".join(probs) +
                     "\nDo the work, then mark requirements with: "
                     "python3 .claude/rulebooky/rulebooky.py task done N --evidence \"...\" "
                     "(or close the task if the user dropped it).\n")
    sys.exit(2)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        log_error("audit: %r" % e)
    sys.exit(0)
