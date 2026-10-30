#!/usr/bin/env python3
"""PostToolUse: count tool calls for the open task so Stop can verify process rules."""
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
                f.write("%s track import: %r\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), e))
        except Exception:
            pass
        return None


def _call(name, *args, **kwargs):
    c = _C()
    if c is None:
        return None
    return getattr(c, name)(*args, **kwargs)


def main():
    c = _C()
    if c is None:
        sys.exit(0)
    c.setup_io()
    ev = c.read_event()
    tool = ev.get("tool_name")
    if not tool:
        return
    state = c.load_state()
    if not state.get("task"):
        return
    state["counters"][tool] = state["counters"].get(tool, 0) + 1
    c.save_state(state)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        _call("log_error", "track: %r" % e)
    sys.exit(0)