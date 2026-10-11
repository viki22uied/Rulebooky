#!/usr/bin/env python3
"""PostToolUse: count tool calls for the open task so Stop can verify process rules."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *  # noqa


def main():
    ev = read_event()
    tool = ev.get("tool_name")
    if not tool:
        return
    state = load_state()
    if not state.get("task"):
        return
    state["counters"][tool] = state["counters"].get(tool, 0) + 1
    save_state(state)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log_error("track: %r" % e)
    sys.exit(0)
