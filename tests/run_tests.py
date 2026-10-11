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
MARK = "rulebooky/hooks/"
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


# ---- hardening: things real users hit ----
def install(proj, *extra):
    return subprocess.run([PY, str(ROOT / "scripts/rulebooky.py"), "install", "--project", str(proj)] + list(extra),
                          capture_output=True, text=True)


with tempfile.TemporaryDirectory() as d:
    proj = Path(d)
    (proj / ".claude").mkdir()
    bad = '{ "hooks": { // comment makes this invalid JSON\n }'
    (proj / ".claude/settings.json").write_text(bad)
    r = install(proj)
    check("install refuses invalid settings.json", r.returncode == 1 and "not valid JSON" in r.stdout)
    check("invalid settings.json left untouched", (proj / ".claude/settings.json").read_text() == bad)
    check("no half-installed files on refusal", not (proj / ".claude/rulebooky").exists())
    check("no traceback on refusal", "Traceback" not in r.stderr)

with tempfile.TemporaryDirectory() as d:
    proj = Path(d)
    (proj / ".claude").mkdir()
    orig = {"model": "x", "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo mine"}]}]}}
    (proj / ".claude/settings.json").write_text(json.dumps(orig))
    install(proj)
    check("install makes a settings backup", (proj / ".claude/settings.json.rulebooky.bak").exists())
    r = cli(proj, "doctor")
    check("doctor passes on fresh install", r.returncode == 0 and "All good" in r.stdout)
    sub = proj / "deep" / "er"
    sub.mkdir(parents=True)
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
    r = subprocess.run([PY, str(proj / ".claude/rulebooky/rulebooky.py"), "task", "set", "--goal", "g"],
                       capture_output=True, text=True, cwd=str(sub), env=env)
    check("CLI works from a subdirectory without env var", r.returncode == 0 and (proj / ".claude/rulebooky/state.json").exists())
    check("state not written to the subdirectory", not (sub / ".claude").exists())
    r = cli(proj, "task", "done", "9", "--evidence", "x")
    check("task done out of range: friendly error", r.returncode == 1 and "No requirement 9" in r.stdout and "Traceback" not in r.stderr)
    r = cli(proj, "task", "set", "--goal", "g", "--forbid", "(unclosed")
    check("bad forbid regex: friendly error", r.returncode == 1 and "not a valid regex" in r.stdout and "Traceback" not in r.stderr)
    r = cli(proj, "task", "set", "--goal", "g", "--min", "WebSearch")
    check("bad --min: friendly error", r.returncode == 1 and "WebSearch=5" in r.stdout)

    # unicode rule text must survive a non-UTF-8 console
    rules = json.loads((proj / ".claude/rulebooky/rules.json").read_text(encoding="utf-8"))
    rules["rules"].append({"id": "uni", "tier": "soft", "text": "Use \u201csmart quotes\u201d \u2014 \u00e9\u00e8 \u4e2d\u6587"})
    (proj / ".claude/rulebooky/rules.json").write_text(json.dumps(rules), encoding="utf-8")
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(proj), PYTHONIOENCODING="ascii")
    r = subprocess.run([PY, str(proj / ".claude/rulebooky/hooks/inject.py"), "session"], input=b"{}",
                       capture_output=True, env=env)
    check("inject survives ascii console with unicode rules", r.returncode == 0 and "smart quotes".encode() in r.stdout)

    # doctor catches breakage
    (proj / ".claude/rulebooky/hooks/guard.py").unlink()
    r = cli(proj, "doctor")
    check("doctor FAILs on missing hook script", r.returncode == 1 and "missing: guard.py" in r.stdout)
    install(proj)

    # uninstall keeps the user's own hook and settings
    r = cli(proj, "uninstall")
    s = json.loads((proj / ".claude/settings.json").read_text())
    check("uninstall removes only rulebooky hooks", s.get("hooks", {}).get("Stop") == orig["hooks"]["Stop"]
          and all(MARK not in json.dumps(v) for v in s.get("hooks", {}).values()) and s["model"] == "x")
    check("uninstall keeps rules.json by default", (proj / ".claude/rulebooky/rules.json").exists())
    cli(proj, "uninstall", "--purge")
    check("purge removes scripts but keeps rules.json", not (proj / ".claude/rulebooky/hooks").exists()
          and (proj / ".claude/rulebooky/rules.json").exists())

with tempfile.TemporaryDirectory() as d:
    r = subprocess.run([PY, str(ROOT / "scripts/rulebooky.py"), "task", "set", "--goal", "g"],
                       capture_output=True, text=True, cwd=d, env={k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"})
    check("commands before install: friendly message", r.returncode == 1 and "not installed" in r.stdout and "Traceback" not in r.stderr)

print("\n%d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)
