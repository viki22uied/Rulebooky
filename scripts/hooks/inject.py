#!/usr/bin/env python3
"""SessionStart / UserPromptSubmit: re-inject rules + task card as context (stdout, exit 0)."""
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
                f.write("%s inject import: %r\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), e))
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
    mode = sys.argv[1] if len(sys.argv) > 1 else "prompt"
    c.read_event()
    rules, state = c.load_rules(), c.load_state()
    # Always save state to recover from corruption
    c.save_state(state)
    if mode == "prompt" and state.get("stop_blocks"):
        state["stop_blocks"] = 0
        c.save_state(state)
    print(c.render(rules, state))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        _call("log_error", "inject: %r" % e)
    sys.exit(0)