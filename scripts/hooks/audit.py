#!/usr/bin/env python3
"""Stop: refuse to let Claude finish while an open task has unmet checks (exit 2)."""
import importlib
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_common_mod = None


def _C():
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
                f.write("%s audit import: %r\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), e))
        except Exception:
            pass
        return None


def _call(name, *args, **kwargs):
    c = _C()
    if c is None:
        return None
    return getattr(c, name)(*args, **kwargs)


def problems_for(rules, state):
    task = state.get("task")
    if not task:
        return []
    probs = []
    # Use _call to get min_calls_required from common
    need = _call("min_calls_required", rules, state) or {}
    for tool, n in need.items():
        have = state["counters"].get(tool, 0)
        if have < n:
            probs.append("%s used %d/%d times (required for this task)" % (tool, have, n))
    open_reqs_result = _call("open_reqs", task) or []
    for i, r in open_reqs_result:
        probs.append("Requirement %d not done with evidence: %s" % (i, r.get("text", "")))
    return probs


def main():
    c = _C()
    if c is None:
        sys.exit(0)
    c.setup_io()
    c.read_event()
    rules = c.load_rules()
    try:
        limit = int(rules.get("max_stop_blocks", 3))
    except (TypeError, ValueError):
        limit = 3
    with c.state_lock():
        state = c.load_state()
        probs = problems_for(rules, state)
        if not probs:
            if state.get("stop_blocks"):
                state["stop_blocks"] = 0
                c.save_state(state)
            return
        if state.get("stop_blocks", 0) >= limit:
            released = True
        else:
            released = False
            state["stop_blocks"] = state.get("stop_blocks", 0) + 1
            c.save_state(state)
    if released:
        _call("log_action", "stop_block", "Stop", {}, "escape_hatch", "max_stop_blocks",
              "Allowed after %d blocks: %s" % (limit, "; ".join(probs)))
        sys.stderr.write("rulebooky: stop allowed after %d blocks, UNMET: %s\n" % (limit, "; ".join(probs)))
        return
    _call("log_action", "stop_block", "Stop", {}, "blocked", "audit", "; ".join(probs))
    sys.stderr.write("Do not finish yet. Unmet:\n- " + "\n- ".join(probs) +
                     "\nDo the work, then mark requirements with: "
                     "python .claude/rulebooky/rulebooky.py task done N --evidence \"...\" "
                     "(or close the task if the user dropped it).\n")
    sys.exit(2)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        _call("log_error", "audit: %r" % e)
    sys.exit(0)