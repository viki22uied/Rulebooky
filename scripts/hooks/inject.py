#!/usr/bin/env python3
"""SessionStart / UserPromptSubmit: re-inject rules + task card as context (stdout, exit 0)."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *  # noqa


def main():
    setup_io()
    mode = sys.argv[1] if len(sys.argv) > 1 else "prompt"
    read_event()
    rules, state = load_rules(), load_state()
    if mode == "prompt" and state.get("stop_blocks"):
        state["stop_blocks"] = 0  # fresh turn, fresh block budget
        save_state(state)
    print(render(rules, state))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # fail open: never break the session
        log_error("inject: %r" % e)
    sys.exit(0)
