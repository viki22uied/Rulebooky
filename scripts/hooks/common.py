"""Shared helpers for rulebooky hooks and CLI. Stdlib only."""
import json
import os
import sys
import time
from pathlib import Path


def project_dir():
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())


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
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(str(tmp), str(p))


def read_event():
    try:
        return json.loads(sys.stdin.read() or "{}")
    except Exception:
        return {}


def load_rules():
    r = load_json(rules_path(), {})
    r.setdefault("rules", [])
    return r


def load_state():
    s = load_json(state_path(), {})
    s.setdefault("task", None)
    s.setdefault("counters", {})
    s.setdefault("stop_blocks", 0)
    s.setdefault("decisions", [])
    return s


def save_state(state):
    save_json(state_path(), state)


def log_error(msg):
    try:
        p = rl_dir() / "hook-errors.log"
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(str(p), "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass


def min_calls_required(rules, state):
    """Merge default min_calls from process rules with the task card's own."""
    need = {}
    for r in rules.get("rules", []):
        c = r.get("check") or {}
        if r.get("tier") == "process" and c.get("type") == "min_calls":
            need[c["tool"]] = max(need.get(c["tool"], 0), int(c["n"]))
    task = state.get("task") or {}
    for tool, n in (task.get("min_calls") or {}).items():
        need[tool] = max(need.get(tool, 0), int(n))
    return need


def open_reqs(task):
    return [(i + 1, r) for i, r in enumerate((task or {}).get("reqs", [])) if not r.get("done")]


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
            out.extend("- " + r["text"] for r in items)
    task = state.get("task")
    if task:
        out.append("CURRENT TASK CARD (do not drift from it):")
        out.append("- Goal: " + task.get("goal", ""))
        if task.get("method"):
            out.append("- Method (required): " + task["method"])
        for pat in task.get("forbid", []):
            out.append("- FORBIDDEN (blocked): /%s/" % pat)
        need = min_calls_required(rules, state)
        for tool, n in need.items():
            have = state["counters"].get(tool, 0)
            out.append("- %s calls: %d/%d required" % (tool, have, n))
        for i, r in enumerate(task.get("reqs", []), 1):
            out.append("- [%s] Req %d: %s" % ("x" if r.get("done") else " ", i, r["text"]))
        if task.get("done_when"):
            out.append("- Done when: " + task["done_when"])
    if state.get("decisions"):
        out.append("DECISIONS SO FAR:")
        out.extend("- " + d for d in state["decisions"][-5:])
    if rules.get("canary"):
        out.append("CANARY: begin every reply with: " + rules["canary"])
    return "\n".join(out)
