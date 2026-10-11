#!/usr/bin/env python3
"""End-to-end tests: install into a temp project, feed fake hook events, check exit codes."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
passed = failed = 0


def run(proj, script, event=None, args=()):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(proj))
    return subprocess.run([PY, str(proj / ".claude/rulebooky" / script)] + list(args),
                          input=json.dumps(event or {}), capture_output=True, text=True, env=env, cwd=str(proj))


def cli(proj, *args):
    return run(proj, "rulebooky.py", args=args)


def check(name, cond):
    global passed, failed
    if cond:
        passed += 1
        print("ok   " + name)
    else:
        failed += 1
        print("FAIL " + name)


with tempfile.TemporaryDirectory() as d:
    proj = Path(d)
    (proj / ".claude").mkdir()
    (proj / ".claude/settings.json").write_text(json.dumps(
        {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo mine"}]}]}, "model": "x"}))
    for _ in range(2):  # twice => idempotent
        subprocess.run([PY, str(ROOT / "scripts/rulebooky.py"), "install", "--project", str(proj)],
                       capture_output=True, check=True)
    s = json.loads((proj / ".claude/settings.json").read_text())
    check("install keeps user's own hook", any("echo mine" in h["command"] for e in s["hooks"]["Stop"] for h in e["hooks"]))
    check("install idempotent (1 rulebooky Stop hook)",
          sum("rulebooky/hooks" in h["command"] for e in s["hooks"]["Stop"] for h in e["hooks"]) == 1)
    check("install keeps unrelated settings", s.get("model") == "x")
    check("all 5 events registered", all(k in s["hooks"] for k in
          ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop")))
    check("lint passes on template", cli(proj, "lint").returncode == 0)

    # guard
    r = run(proj, "hooks/guard.py", {"tool_name": "Write", "tool_input": {"file_path": str(proj / "NOTES.md")}})
    check("guard blocks new .md", r.returncode == 2 and "no-md-sprawl" in r.stderr)
    r = run(proj, "hooks/guard.py", {"tool_name": "Write", "tool_input": {"file_path": str(proj / "README.md")}})
    check("guard allows allowlisted README.md", r.returncode == 0)
    r = run(proj, "hooks/guard.py", {"tool_name": "Write", "tool_input": {"file_path": str(proj / "a.py")}})
    check("guard allows .py", r.returncode == 0)
    r = run(proj, "hooks/guard.py", {"tool_name": "Bash", "tool_input": {"command": "git push origin main --force"}})
    check("guard blocks force push", r.returncode == 2)
    r = run(proj, "hooks/guard.py", {"tool_name": "Bash", "tool_input": {"command": "ls"}})
    check("guard allows ls", r.returncode == 0)

    # task card forbid
    cli(proj, "task", "set", "--goal", "research X", "--forbid", "scrape\\.py", "--min", "WebSearch=3")
    r = run(proj, "hooks/guard.py", {"tool_name": "Bash", "tool_input": {"command": "python scrape.py"}})
    check("guard enforces task-card forbid", r.returncode == 2)

    # audit: min calls
    r = run(proj, "hooks/audit.py")
    check("audit blocks: 0/3 searches", r.returncode == 2 and "WebSearch used 0/3" in r.stderr)
    for _ in range(3):
        run(proj, "hooks/track.py", {"tool_name": "WebSearch"})
    check("audit passes after 3 searches", run(proj, "hooks/audit.py").returncode == 0)

    # audit: requirements need evidence
    cli(proj, "task", "add-req", "Use the API from the doc")
    check("audit blocks open requirement", run(proj, "hooks/audit.py").returncode == 2)
    check("done without evidence refused", cli(proj, "task", "done", "1", "--evidence", " ").returncode != 0)
    cli(proj, "task", "done", "1", "--evidence", "src/api.py:12")
    st = json.loads((proj / ".claude/rulebooky/state.json").read_text())
    check("audit passes when reqs done", run(proj, "hooks/audit.py").returncode == 0)

    # escape hatch
    cli(proj, "task", "add-req", "impossible thing")
    codes = [run(proj, "hooks/audit.py").returncode for _ in range(5)]
    check("stop blocked 3x then released", codes == [2, 2, 2, 0, 0])
    run(proj, "hooks/inject.py", args=["prompt"])
    check("new prompt resets block budget", run(proj, "hooks/audit.py").returncode == 2)

    # inject
    out = run(proj, "hooks/inject.py", args=["session"]).stdout
    check("inject shows rules + task card", "HARD" in out and "CURRENT TASK CARD" in out and "impossible thing" in out)
    check("close refuses with open reqs", cli(proj, "task", "close").returncode == 1)
    cli(proj, "task", "close", "--force")
    check("no task => audit passes", run(proj, "hooks/audit.py").returncode == 0)

    # fail-open on corrupt rules
    (proj / ".claude/rulebooky/rules.json").write_text("{not json")
    check("corrupt rules => hooks fail open", run(proj, "hooks/guard.py",
          {"tool_name": "Bash", "tool_input": {"command": "ls"}}).returncode == 0)
    check("lint flags corrupt rules", cli(proj, "lint").returncode == 1)

print("\n%d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
