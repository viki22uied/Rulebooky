"""Shared helpers for rulebooky hooks and CLI. Stdlib only."""
import contextlib
import json
import os
import sys
import time
from pathlib import Path


def project_dir():
    """Installed scripts locate the project from their own path, so cwd never matters."""
    here = Path(__file__).resolve()
    if len(here.parents) > 3 and here.parents[1].name == "rulebooky" and here.parents[2].name == ".claude":
        return here.parents[3]
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())


def setup_io():
    """Force UTF-8 so non-ASCII rule text cannot crash hooks on Windows/cp1252 consoles."""
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def rl_dir():
    return project_dir() / ".claude" / "rulebooky"


def rules_path():
    return rl_dir() / "rules.json"


def state_path():
    return rl_dir() / "state.json"


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path, data):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name("%s.%d.tmp" % (p.name, os.getpid()))  # unique: parallel hooks never share a tmp file
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    for attempt in range(20):
        try:
            os.replace(str(tmp), str(p))
            break
        except PermissionError:  # Windows: target briefly open by another reader
            if attempt == 19:
                raise
            time.sleep(0.02)
    # Auto-log rules.json changes
    if p.name == "rules.json":
        log_rules_change(data)


LOG_MAX_BYTES = 1000000  # rotate logs at ~1 MB so they never grow without bound


def _append_log(path, line):
    """Append one line to a log file, rotating it to <name>.1 when it gets large."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        if p.exists() and p.stat().st_size > LOG_MAX_BYTES:
            os.replace(str(p), str(p) + ".1")
    except Exception:
        pass
    with open(str(p), "a", encoding="utf-8") as f:
        f.write(line + "\n")


def log_rules_change(new_rules):
    """Append rules change to history log."""
    try:
        rs = [r for r in new_rules.get("rules", []) if isinstance(r, dict)]
        entry = {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "rules_count": len(rs),
            "rule_ids": [r.get("id") for r in rs],
            "version": new_rules.get("version", 1)
        }
        _append_log(rl_dir() / "rules-history.jsonl", json.dumps(entry, ensure_ascii=False))
    except Exception:
        pass


def read_event():
    try:
        ev = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return {}
    if not isinstance(ev, dict):
        return {}
    if not isinstance(ev.get("tool_input"), dict):
        ev["tool_input"] = {}
    return ev


def load_rules():
    """Rules file, normalised so one malformed entry can never crash a hook."""
    r = load_json(rules_path(), {})
    if not isinstance(r, dict):
        r = {}
    rs = r.get("rules")
    r["rules"] = [x for x in rs if isinstance(x, dict)] if isinstance(rs, list) else []
    return r


def load_state():
    s = load_json(state_path(), {})
    if not isinstance(s, dict):
        s = {}
    if not isinstance(s.get("task"), dict):
        s["task"] = None
    if not isinstance(s.get("counters"), dict):
        s["counters"] = {}
    if not isinstance(s.get("stop_blocks"), int):
        s["stop_blocks"] = 0
    if not isinstance(s.get("decisions"), list):
        s["decisions"] = []
    return s


def save_state(state):
    save_json(state_path(), state)


@contextlib.contextmanager
def state_lock(timeout=5.0):
    """Exclusive lock around a read-modify-write of state.json.

    Claude Code runs parallel tool calls, so PostToolUse hooks race; without
    this, counters lose increments. If the lock cannot be taken in time we
    carry on unlocked: a hook must never hang the session.
    """
    lock = None
    got = False
    try:
        p = rl_dir() / "state.lock"
        p.parent.mkdir(parents=True, exist_ok=True)
        lock = open(str(p), "a+")
        deadline = time.time() + timeout
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                got = True
                break
            except (OSError, IOError):
                if time.time() > deadline:
                    log_error("state lock timeout; continuing unlocked")
                    break
                time.sleep(0.005)
    except Exception as e:
        log_error("state lock unavailable: %r" % e)
    try:
        yield
    finally:
        if lock is not None:
            try:
                if got:
                    if os.name == "nt":
                        import msvcrt
                        lock.seek(0)
                        msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            finally:
                lock.close()


def log_error(msg):
    try:
        _append_log(rl_dir() / "hook-errors.log", "%s %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass


def summarize_input(tool_input, limit=200):
    """Keep only short, identifying fields. Never log file contents (they can hold secrets)."""
    if not isinstance(tool_input, dict):
        return {}
    out = {}
    for k in ("command", "file_path", "notebook_path", "path", "pattern", "url", "query",
              "subagent_type", "description"):
        v = tool_input.get(k)
        if isinstance(v, str) and v:
            out[k] = v if len(v) <= limit else v[:limit] + "...(%d chars)" % len(v)
    return out


def log_action(event_type, tool_name, tool_input, result, rule_id=None, rule_text=None):
    """Log rule enforcement actions for observability."""
    try:
        entry = {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "type": event_type,
            "tool": tool_name,
            "input": summarize_input(tool_input),
            "result": result,
            "rule_id": rule_id,
            "rule_text": rule_text,
            "task_goal": (load_state().get("task") or {}).get("goal", "") if event_type in ("blocked", "allowed") else ""
        }
        _append_log(rl_dir() / "actions.log", json.dumps(entry, ensure_ascii=False))
    except Exception:
        pass


def min_calls_required(rules, state):
    """Merge default min_calls from process rules with the task card's own."""
    need = {}
    for r in rules.get("rules", []):
        c = r.get("check")
        if r.get("tier") != "process" or not isinstance(c, dict) or c.get("type") != "min_calls":
            continue
        try:
            need[str(c["tool"])] = max(need.get(str(c["tool"]), 0), int(c["n"]))
        except Exception:
            log_error("skipped invalid min_calls rule %r (run lint)" % r.get("id"))
    task = state.get("task") or {}
    mins = task.get("min_calls")
    for tool, n in (mins.items() if isinstance(mins, dict) else ()):
        try:
            need[tool] = max(need.get(tool, 0), int(n))
        except Exception:
            pass
    return need


def open_reqs(task):
    reqs = (task or {}).get("reqs") or []
    return [(i + 1, r) for i, r in enumerate(reqs) if isinstance(r, dict) and not r.get("done")]


def render(rules, state):
    """Compact context block injected on SessionStart and every prompt."""
    rs = rules.get("rules", [])
    out = ["[RULEBOOKY] Binding rules for this project. Hooks block hard-rule violations "
           "and stop you from finishing while process rules/requirements are unmet."]
    for label, tier in (("HARD (blocked by hooks)", "hard"),
                        ("PROCESS (checked before you may stop)", "process"),
                        ("SOFT", "soft")):
        items = [r for r in rs if r.get("tier") == tier]
        if items:
            out.append(label + ":")
            out.extend("- " + str(r.get("text", "")) for r in items)
    task = state.get("task")
    if task:
        out.append("CURRENT TASK CARD (do not drift from it):")
        out.append("- Goal: " + str(task.get("goal", "")))
        if task.get("method"):
            out.append("- Method (required): " + task["method"])
        for pat in task.get("forbid") or []:
            out.append("- FORBIDDEN (blocked): /%s/" % pat)
        need = min_calls_required(rules, state)
        for tool, n in need.items():
            have = state["counters"].get(tool, 0)
            out.append("- %s calls: %d/%d required" % (tool, have, n))
        for i, r in enumerate([x for x in task.get("reqs") or [] if isinstance(x, dict)], 1):
            out.append("- [%s] Req %d: %s" % ("x" if r.get("done") else " ", i, r.get("text", "")))
        if task.get("done_when"):
            out.append("- Done when: " + task["done_when"])
    if state.get("decisions"):
        out.append("DECISIONS SO FAR:")
        out.extend("- " + str(d) for d in state["decisions"][-5:])
    if rules.get("canary"):
        out.append("CANARY: begin every reply with: " + str(rules["canary"]))
    return "\n".join(out)
