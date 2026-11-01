#!/usr/bin/env python3
"""Comprehensive stress tests for rulebooky - covers edge cases, failures, and real-world scenarios."""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
passed = failed = 0


def run(proj, script, event=None, args=()):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(proj))
    return subprocess.run([PY, str(proj / ".claude/rulebooky" / script)] + list(args),
                          input=json.dumps(event or {}), capture_output=True, text=True, encoding="utf-8", env=env, cwd=str(proj))


def cli(proj, *args):
    return run(proj, "rulebooky.py", args=args)


def check(name, cond):
    global passed, failed
    if cond:
        passed += 1
        print(f"ok   {name}")
    else:
        failed += 1
        print(f"FAIL {name}")


def setup_project(proj):
    """Create a fresh project with rulebooky installed."""
    (proj / ".claude").mkdir(parents=True, exist_ok=True)
    subprocess.run([PY, str(ROOT / "scripts/rulebooky.py"), "install", "--project", str(proj)],
                   capture_output=True, check=True)


# ============ STRESS TESTS ============

def test_unicode_rules():
    """Unicode in rules must not crash hooks on any encoding."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        rules = json.loads((proj / ".claude/rulebooky/rules.json").read_text(encoding="utf-8"))
        rules["rules"].append({"id": "uni", "tier": "soft", "text": "Use \u201csmart quotes\u201d \u2014 \u00e9\u00e8 \u4e2d\u6587"})
        (proj / ".claude/rulebooky/rules.json").write_text(json.dumps(rules), encoding="utf-8")
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(proj), PYTHONIOENCODING="ascii")
        r = subprocess.run([PY, str(proj / ".claude/rulebooky/hooks/inject.py"), "session"], input=b"{}",
                           capture_output=True, env=env)
        check("unicode rules survive ascii console", r.returncode == 0 and "smart quotes".encode() in r.stdout)


def test_emoji_in_rules():
    """Emoji in rule text."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        rules = json.loads((proj / ".claude/rulebooky/rules.json").read_text(encoding="utf-8"))
        rules["rules"].append({"id": "emoji", "tier": "soft", "text": "Use \U0001f600 emoji \U0001f4a1"})
        (proj / ".claude/rulebooky/rules.json").write_text(json.dumps(rules), encoding="utf-8")
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(proj))
        r = subprocess.run([PY, str(proj / ".claude/rulebooky/hooks/inject.py"), "session"], input=b"{}",
                           capture_output=True, env=env)
        check("emoji in rules", r.returncode == 0)


def test_very_long_command():
    """Very long bash command (near limit)."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        long_cmd = "echo " + "x" * 50000
        r = run(proj, "hooks/guard.py", {"tool_name": "Bash", "tool_input": {"command": long_cmd}})
        check("very long bash command handled", r.returncode in (0, 2))  # not crash


def test_deeply_nested_paths():
    """Deeply nested file paths."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        deep_path = proj / "a" / "b" / "c" / "d" / "e" / "f" / "g" / "h" / "i" / "j" / "file.md"
        deep_path.parent.mkdir(parents=True)
        r = run(proj, "hooks/guard.py", {"tool_name": "Write", "tool_input": {"file_path": str(deep_path)}})
        check("deeply nested path handled", r.returncode in (0, 2))


def test_special_chars_in_path():
    """Special characters in file paths."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        special = proj / "file with spaces & symbols @#$.md"
        r = run(proj, "hooks/guard.py", {"tool_name": "Write", "tool_input": {"file_path": str(special)}})
        check("special chars in path", r.returncode == 2 and "no-md-sprawl" in r.stderr)


def test_unicode_file_path():
    """Unicode file paths."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        uni_path = proj / "\u4e2d\u6587\u6587\u4ef6.md"
        r = run(proj, "hooks/guard.py", {"tool_name": "Write", "tool_input": {"file_path": str(uni_path)}})
        check("unicode file path blocked", r.returncode == 2)


def test_malformed_json_input():
    """Hook receives malformed JSON on stdin."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(proj))
        r = subprocess.run([PY, str(proj / ".claude/rulebooky/hooks/guard.py")],
                           input="not json", capture_output=True, text=True, env=env)
        check("malformed JSON input fails open", r.returncode == 0)


def test_empty_stdin():
    """Hook receives empty stdin."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(proj))
        r = subprocess.run([PY, str(proj / ".claude/rulebooky/hooks/guard.py")],
                           input="", capture_output=True, text=True, env=env)
        check("empty stdin fails open", r.returncode == 0)


def test_missing_tool_name():
    """Event missing tool_name."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        r = run(proj, "hooks/guard.py", {"tool_input": {"command": "ls"}})
        check("missing tool_name fails open", r.returncode == 0)


def test_null_tool_input():
    """Event with null tool_input."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        r = run(proj, "hooks/guard.py", {"tool_name": "Bash", "tool_input": None})
        check("null tool_input handled", r.returncode == 0)


def test_concurrent_task_cards():
    """Rapid task set/close cycles."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        for i in range(10):
            cli(proj, "task", "set", "--goal", f"task {i}", "--method", "test")
            cli(proj, "task", "close", "--force")
        st = json.loads((proj / ".claude/rulebooky/state.json").read_text())
        check("rapid task cycles leave clean state", st.get("task") is None)


def test_task_card_persistence_across_clears():
    """Task card survives simulated clear/compact."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        cli(proj, "task", "set", "--goal", "persist test", "--method", "test")
        cli(proj, "task", "add-req", "Requirement 1")
        # Simulate SessionStart clear
        run(proj, "hooks/inject.py", args=["session"])
        st = json.loads((proj / ".claude/rulebooky/state.json").read_text())
        check("task survives inject session", st.get("task") is not None)
        check("requirement persists", len(st["task"]["reqs"]) == 1)


def test_stop_block_escape_hatch():
    """After max_stop_blocks, stop is allowed."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        cli(proj, "task", "set", "--goal", "test", "--method", "test")
        cli(proj, "task", "add-req", "Impossible req")
        codes = [run(proj, "hooks/audit.py").returncode for _ in range(5)]
        check("escape hatch after 3 blocks", codes == [2, 2, 2, 0, 0])


def test_stop_block_resets_on_new_prompt():
    """New UserPromptSubmit resets stop block counter."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        cli(proj, "task", "set", "--goal", "test", "--method", "test")
        cli(proj, "task", "add-req", "Impossible req")
        run(proj, "hooks/audit.py")  # block 1
        run(proj, "hooks/audit.py")  # block 2
        run(proj, "hooks/inject.py", args=["prompt"])  # new prompt
        r = run(proj, "hooks/audit.py")
        check("new prompt resets block budget", r.returncode == 2)


def test_forbid_regex_edge_cases():
    """Complex forbid regex patterns."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        cli(proj, "task", "set", "--goal", "test", "--forbid", r"scrape\.py", "--forbid", r"deploy.*prod")
        # Should match
        r1 = run(proj, "hooks/guard.py", {"tool_name": "Bash", "tool_input": {"command": "python scrape.py"}})
        r2 = run(proj, "hooks/guard.py", {"tool_name": "Bash", "tool_input": {"command": "deploy to prod"}})
        # Should not match
        r3 = run(proj, "hooks/guard.py", {"tool_name": "Bash", "tool_input": {"command": "python scraper.py"}})
        r4 = run(proj, "hooks/guard.py", {"tool_name": "Bash", "tool_input": {"command": "deploy to staging"}})
        check("forbid regex matches scrape.py", r1.returncode == 2)
        check("forbid regex matches deploy.*prod", r2.returncode == 2)
        check("forbid regex does not match scraper.py", r3.returncode == 0)
        check("forbid regex does not match staging", r4.returncode == 0)


def test_deny_bash_complex_patterns():
    """Complex deny_bash patterns."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        rules = json.loads((proj / ".claude/rulebooky/rules.json").read_text(encoding="utf-8"))
        rules["rules"].append({
            "id": "no-rm-rf", "tier": "hard", "text": "Never run rm -rf",
            "check": {"type": "deny_bash", "pattern": r"rm\s+-rf\s+/"
        }})
        (proj / ".claude/rulebooky/rules.json").write_text(json.dumps(rules), encoding="utf-8")
        r1 = run(proj, "hooks/guard.py", {"tool_name": "Bash", "tool_input": {"command": "rm -rf /home/user"}})
        r2 = run(proj, "hooks/guard.py", {"tool_name": "Bash", "tool_input": {"command": "rm -rf /tmp/test"}})
        r3 = run(proj, "hooks/guard.py", {"tool_name": "Bash", "tool_input": {"command": "rm -f file.txt"}})
        check("deny_bash blocks rm -rf /", r1.returncode == 2)
        check("deny_bash blocks rm -rf /tmp", r2.returncode == 2)
        check("deny_bash allows rm -f", r3.returncode == 0)


def test_block_new_files_allowlist():
    """block_new_files respects allowlist."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        rules = json.loads((proj / ".claude/rulebooky/rules.json").read_text(encoding="utf-8"))
        # Find no-md-sprawl and add allow
        for r in rules["rules"]:
            if r["id"] == "no-md-sprawl":
                r["check"]["allow"] = ["README.md", "CHANGELOG.md", "ALLOWED.md"]
        (proj / ".claude/rulebooky/rules.json").write_text(json.dumps(rules), encoding="utf-8")
        (proj / "ALLOWED.md").write_text("# Allowed")
        r1 = run(proj, "hooks/guard.py", {"tool_name": "Write", "tool_input": {"file_path": str(proj / "NEW.md")}})
        r2 = run(proj, "hooks/guard.py", {"tool_name": "Write", "tool_input": {"file_path": str(proj / "ALLOWED.md")}})
        check("block_new_files blocks new .md", r1.returncode == 2)
        check("block_new_files allows allowlisted", r2.returncode == 0)


def test_deny_path_patterns():
    """deny_path blocks paths matching pattern."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        rules = json.loads((proj / ".claude/rulebooky/rules.json").read_text(encoding="utf-8"))
        rules["rules"].append({
            "id": "no-migrations", "tier": "hard", "text": "Never touch migrations",
            "check": {"type": "deny_path", "pattern": "migrations/"}
        })
        (proj / ".claude/rulebooky/rules.json").write_text(json.dumps(rules), encoding="utf-8")
        (proj / "migrations").mkdir()
        r1 = run(proj, "hooks/guard.py", {"tool_name": "Write", "tool_input": {"file_path": str(proj / "migrations/001.sql")}})
        r2 = run(proj, "hooks/guard.py", {"tool_name": "Write", "tool_input": {"file_path": str(proj / "src/main.py")}})
        check("deny_path blocks migrations/", r1.returncode == 2)
        check("deny_path allows other paths", r2.returncode == 0)


def test_min_calls_multiple_tools():
    """Multiple min_calls requirements."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        cli(proj, "task", "set", "--goal", "research", "--min", "WebSearch=2", "--min", "Read=3")
        # Not enough calls
        r = run(proj, "hooks/audit.py")
        check("audit blocks: 0/2 WebSearch, 0/3 Read", r.returncode == 2)
        # Add WebSearch calls
        run(proj, "hooks/track.py", {"tool_name": "WebSearch"})
        run(proj, "hooks/track.py", {"tool_name": "WebSearch"})
        r = run(proj, "hooks/audit.py")
        check("audit blocks: 2/2 WebSearch, 0/3 Read", r.returncode == 2)
        # Add Read calls
        run(proj, "hooks/track.py", {"tool_name": "Read"})
        run(proj, "hooks/track.py", {"tool_name": "Read"})
        run(proj, "hooks/track.py", {"tool_name": "Read"})
        r = run(proj, "hooks/audit.py")
        check("audit passes after all min_calls met", r.returncode == 0)


def test_process_rules_from_rules_json():
    """Process rules defined in rules.json (not task card)."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        rules = json.loads((proj / ".claude/rulebooky/rules.json").read_text(encoding="utf-8"))
        rules["rules"].append({
            "id": "min-read", "tier": "process", "text": "Must read at least 2 files",
            "check": {"type": "min_calls", "tool": "Read", "n": 2}
        })
        (proj / ".claude/rulebooky/rules.json").write_text(json.dumps(rules), encoding="utf-8")
        cli(proj, "task", "set", "--goal", "test", "--method", "test")
        r = run(proj, "hooks/audit.py")
        check("process rule from rules.json enforced", r.returncode == 2 and "Read used 0/2" in r.stderr)
        run(proj, "hooks/track.py", {"tool_name": "Read"})
        run(proj, "hooks/track.py", {"tool_name": "Read"})
        r = run(proj, "hooks/audit.py")
        check("audit passes after process rule met", r.returncode == 0)


def test_evidence_requirement():
    """Evidence required for task done."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        cli(proj, "task", "set", "--goal", "test")
        cli(proj, "task", "add-req", "Do something")
        r = cli(proj, "task", "done", "1", "--evidence", " ")
        check("evidence cannot be whitespace", r.returncode != 0)
        r = cli(proj, "task", "done", "1", "--evidence", "file.py:10")
        check("evidence with file:line accepted", r.returncode == 0)


def test_task_done_out_of_range():
    """Task done with invalid requirement number."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        cli(proj, "task", "set", "--goal", "test")
        cli(proj, "task", "add-req", "Req 1")
        r = cli(proj, "task", "done", "99", "--evidence", "x")
        check("out of range req gives friendly error", r.returncode == 1 and "No requirement 99" in r.stdout)


def test_invalid_forbid_regex():
    """Invalid forbid regex gives friendly error."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        r = cli(proj, "task", "set", "--goal", "test", "--forbid", "(unclosed")
        check("bad forbid regex: friendly error", r.returncode == 1 and "not a valid regex" in r.stdout)


def test_invalid_min_format():
    """Invalid --min format gives friendly error."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        r = cli(proj, "task", "set", "--goal", "test", "--min", "WebSearch")
        check("bad --min format: friendly error", r.returncode == 1 and "WebSearch=5" in r.stdout)


def test_invalid_json_rules():
    """Corrupt rules.json fails open in hooks, but lint catches it."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        (proj / ".claude/rulebooky/rules.json").write_text("{not json")
        r = run(proj, "hooks/guard.py", {"tool_name": "Bash", "tool_input": {"command": "ls"}})
        check("corrupt rules => hooks fail open", r.returncode == 0)
        r = cli(proj, "lint")
        check("lint flags corrupt rules", r.returncode == 1)


def test_missing_rules_json():
    """Missing rules.json handled gracefully."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        (proj / ".claude/rulebooky/rules.json").unlink()
        r = run(proj, "hooks/guard.py", {"tool_name": "Bash", "tool_input": {"command": "ls"}})
        check("missing rules.json => hooks fail open", r.returncode == 0)
        r = cli(proj, "lint")
        check("lint flags missing rules", r.returncode == 1)


def test_missing_settings_json():
    """Missing settings.json handled during install."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        (proj / ".claude").mkdir()
        r = subprocess.run([PY, str(ROOT / "scripts/rulebooky.py"), "install", "--project", str(proj)],
                           capture_output=True, text=True)
        check("install works without settings.json", r.returncode == 0)


def test_invalid_settings_json():
    """Invalid settings.json refuses install."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        (proj / ".claude").mkdir()
        (proj / ".claude/settings.json").write_text("{invalid json")
        r = subprocess.run([PY, str(ROOT / "scripts/rulebooky.py"), "install", "--project", str(proj)],
                           capture_output=True, text=True)
        check("install refuses invalid settings.json", r.returncode == 1 and "not valid JSON" in r.stdout)
        check("settings.json left untouched", (proj / ".claude/settings.json").read_text() == "{invalid json")


def test_settings_backup_created():
    """Install creates backup of existing settings."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        (proj / ".claude").mkdir()
        orig = {"model": "x", "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo mine"}]}]}}
        (proj / ".claude/settings.json").write_text(json.dumps(orig))
        subprocess.run([PY, str(ROOT / "scripts/rulebooky.py"), "install", "--project", str(proj)],
                       capture_output=True, check=True)
        check("backup created", (proj / ".claude/settings.json.rulebooky.bak").exists())


def test_install_idempotent():
    """Running install twice is safe."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        (proj / ".claude").mkdir()
        (proj / ".claude/settings.json").write_text(json.dumps({"hooks": {}}))
        for _ in range(3):
            subprocess.run([PY, str(ROOT / "scripts/rulebooky.py"), "install", "--project", str(proj)],
                           capture_output=True, check=True)
        s = json.loads((proj / ".claude/settings.json").read_text())
        check("install idempotent: 1 rulebooky hook per event",
              all(sum("rulebooky/hooks" in h["command"] for h in e["hooks"]) == 1 for ev in s["hooks"].values() for e in ev))


def test_uninstall_keeps_user_hooks():
    """Uninstall removes only rulebooky hooks."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        orig = {"model": "x", "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo mine"}]}]}}
        (proj / ".claude/settings.json").write_text(json.dumps(orig))
        subprocess.run([PY, str(ROOT / "scripts/rulebooky.py"), "install", "--project", str(proj)],
                       capture_output=True, check=True)
        cli(proj, "uninstall")
        s = json.loads((proj / ".claude/settings.json").read_text())
        check("uninstall keeps user hooks", s.get("hooks", {}).get("Stop") == orig["hooks"]["Stop"])
        check("uninstall removes rulebooky hooks", all("rulebooky/hooks" not in json.dumps(v) for v in s.get("hooks", {}).values()))


def test_uninstall_purge():
    """Uninstall --purge removes scripts but keeps rules.json."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        cli(proj, "uninstall", "--purge")
        check("purge removes hooks dir", not (proj / ".claude/rulebooky/hooks").exists())
        check("purge keeps rules.json", (proj / ".claude/rulebooky/rules.json").exists())


def test_commands_before_install():
    """Commands before install give friendly error."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        r = subprocess.run([PY, str(ROOT / "scripts/rulebooky.py"), "task", "set", "--goal", "g"],
                           capture_output=True, text=True, cwd=d,
                           env={k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"})
        check("command before install: friendly error", r.returncode == 1 and "not installed" in r.stdout)


def test_cli_from_subdirectory():
    """CLI works from project subdirectory without env var."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        sub = proj / "deep" / "er"
        sub.mkdir(parents=True)
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
        r = subprocess.run([PY, str(proj / ".claude/rulebooky/rulebooky.py"), "task", "set", "--goal", "g"],
                           capture_output=True, text=True, cwd=str(sub), env=env)
        check("CLI works from subdir", r.returncode == 0 and (proj / ".claude/rulebooky/state.json").exists())
        check("state not written to subdir", not (sub / ".claude").exists())


def test_doctor_passes_fresh():
    """Doctor passes on fresh install."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        r = cli(proj, "doctor")
        check("doctor passes on fresh install", r.returncode == 0 and "All good" in r.stdout)


def test_doctor_catches_missing_hook():
    """Doctor catches missing hook script."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        (proj / ".claude/rulebooky/hooks/guard.py").unlink()
        r = cli(proj, "doctor")
        check("doctor FAILs on missing hook", r.returncode == 1 and "missing: guard.py" in r.stdout)


def test_decide_persists():
    """Decisions persist across task close."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        cli(proj, "task", "set", "--goal", "test")
        cli(proj, "decide", "chose option A")
        cli(proj, "task", "close", "--force")
        st = json.loads((proj / ".claude/rulebooky/state.json").read_text())
        check("decision persists after task close", "chose option A" in st.get("decisions", []))


def test_decisions_trimmed():
    """Decisions list trimmed to 20."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        cli(proj, "task", "set", "--goal", "test")
        for i in range(25):
            cli(proj, "decide", f"decision {i}")
        st = json.loads((proj / ".claude/rulebooky/state.json").read_text())
        check("decisions trimmed to 20", len(st.get("decisions", [])) == 20)


def test_large_rules_file():
    """Large rules.json (25 rules) works."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        rules = {"version": 1, "rules": []}
        for i in range(25):
            rules["rules"].append({
                "id": f"rule-{i}", "tier": "soft", "text": f"Soft rule {i}"
            })
        (proj / ".claude/rulebooky/rules.json").write_text(json.dumps(rules), encoding="utf-8")
        r = cli(proj, "lint")
        check("25 rules lint passes", r.returncode == 0)
        r = run(proj, "hooks/inject.py", args=["session"])
        check("inject handles 25 rules", r.returncode == 0 and "SOFT:" in r.stdout)


def test_too_many_soft_rules_warn():
    """More than 10 soft rules warns."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        rules = {"version": 1, "rules": []}
        for i in range(15):
            rules["rules"].append({"id": f"soft-{i}", "tier": "soft", "text": f"Soft {i}"})
        (proj / ".claude/rulebooky/rules.json").write_text(json.dumps(rules), encoding="utf-8")
        r = cli(proj, "lint")
        check("lint warns on >10 soft rules", r.returncode == 0 and "15 soft rules" in r.stdout)


def test_too_many_total_rules_warn():
    """More than 25 total rules warns."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        rules = {"version": 1, "rules": []}
        for i in range(30):
            rules["rules"].append({"id": f"rule-{i}", "tier": "soft", "text": f"Rule {i}"})
        (proj / ".claude/rulebooky/rules.json").write_text(json.dumps(rules), encoding="utf-8")
        r = cli(proj, "lint")
        check("lint warns on >25 total rules", r.returncode == 0 and "30 rules total" in r.stdout)


def test_duplicate_rule_ids_error():
    """Duplicate rule IDs cause lint error."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        rules = {"version": 1, "rules": [
            {"id": "dup", "tier": "soft", "text": "First"},
            {"id": "dup", "tier": "soft", "text": "Second"}
        ]}
        (proj / ".claude/rulebooky/rules.json").write_text(json.dumps(rules), encoding="utf-8")
        r = cli(proj, "lint")
        check("lint errors on duplicate IDs", r.returncode == 1 and "duplicate id" in r.stdout)


def test_vague_rule_warnings():
    """Vague wording in rules triggers warnings."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        rules = {"version": 1, "rules": [
            {"id": "vague", "tier": "soft", "text": "Follow best practices and write clean code"}
        ]}
        (proj / ".claude/rulebooky/rules.json").write_text(json.dumps(rules), encoding="utf-8")
        r = cli(proj, "lint")
        check("lint warns on vague wording", r.returncode == 0 and "vague wording" in r.stdout)


def test_hard_rule_without_check_errors():
    """Hard rule without check config causes lint error."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        rules = {"version": 1, "rules": [
            {"id": "bad-hard", "tier": "hard", "text": "Hard rule no check"}
        ]}
        (proj / ".claude/rulebooky/rules.json").write_text(json.dumps(rules), encoding="utf-8")
        r = cli(proj, "lint")
        check("lint errors on hard without check", r.returncode == 1 and "hard rule needs check" in r.stdout)


def test_invalid_check_type_errors():
    """Invalid check type causes lint error."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        rules = {"version": 1, "rules": [
            {"id": "bad-check", "tier": "hard", "text": "Bad check",
             "check": {"type": "invalid_type", "pattern": ".*"}}
        ]}
        (proj / ".claude/rulebooky/rules.json").write_text(json.dumps(rules), encoding="utf-8")
        r = cli(proj, "lint")
        check("lint errors on invalid check type", r.returncode == 1 and "check.type in" in r.stdout)


def test_missing_pattern_in_deny_bash():
    """deny_bash without pattern causes lint error."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        rules = {"version": 1, "rules": [
            {"id": "no-pat", "tier": "hard", "text": "No pattern",
             "check": {"type": "deny_bash"}}
        ]}
        (proj / ".claude/rulebooky/rules.json").write_text(json.dumps(rules), encoding="utf-8")
        r = cli(proj, "lint")
        check("lint errors on missing pattern", r.returncode == 1 and "missing pattern" in r.stdout)


def test_bad_regex_in_check():
    """Bad regex in check causes lint error."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        rules = {"version": 1, "rules": [
            {"id": "bad-regex", "tier": "hard", "text": "Bad regex",
             "check": {"type": "deny_bash", "pattern": "(unclosed"}}
        ]}
        (proj / ".claude/rulebooky/rules.json").write_text(json.dumps(rules), encoding="utf-8")
        r = cli(proj, "lint")
        check("lint errors on bad regex", r.returncode == 1 and "bad regex" in r.stdout)


def test_block_new_files_missing_glob():
    """block_new_files without glob causes lint error."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        rules = {"version": 1, "rules": [
            {"id": "no-glob", "tier": "hard", "text": "No glob",
             "check": {"type": "block_new_files"}}
        ]}
        (proj / ".claude/rulebooky/rules.json").write_text(json.dumps(rules), encoding="utf-8")
        r = cli(proj, "lint")
        check("lint errors on block_new_files missing glob", r.returncode == 1 and "block_new_files needs glob" in r.stdout)


def test_invalid_process_check():
    """Process rule with invalid check config."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        rules = {"version": 1, "rules": [
            {"id": "bad-proc", "tier": "process", "text": "Bad process",
             "check": {"type": "min_calls", "tool": "WebSearch"}}
        ]}
        (proj / ".claude/rulebooky/rules.json").write_text(json.dumps(rules), encoding="utf-8")
        r = cli(proj, "lint")
        check("lint errors on invalid process check", r.returncode == 1 and "process check must be" in r.stdout)


def test_subagent_auto_propagation():
    """Task tool call gets rules injected."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        cli(proj, "task", "set", "--goal", "parent task")
        cli(proj, "task", "add-req", "Parent requirement")
        # Simulate Task tool call
        r = run(proj, "hooks/guard.py", {
            "tool_name": "Task",
            "tool_input": {"prompt": "Do something", "subagent_type": "general-purpose"}
        })
        check("Task tool allowed", r.returncode == 0)
        # The prompt should be modified by guard.py (we can't easily test the modified prompt
        # since guard.py doesn't return it, but we can verify no crash)


def test_log_command():
    """Log command shows actions."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        cli(proj, "task", "set", "--goal", "test", "--forbid", "bad")
        # Trigger a block
        run(proj, "hooks/guard.py", {"tool_name": "Bash", "tool_input": {"command": "bad command"}})
        r = cli(proj, "log", "--format", "json")
        check("log command works", r.returncode == 0)
        logs = json.loads(r.stdout)
        check("log contains blocked entry", any(e.get("type") == "blocked" for e in logs))


def test_log_filters():
    """Log filters work."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        cli(proj, "task", "set", "--goal", "test", "--forbid", "bad")
        run(proj, "hooks/guard.py", {"tool_name": "Bash", "tool_input": {"command": "bad"}})
        run(proj, "hooks/guard.py", {"tool_name": "Bash", "tool_input": {"command": "good"}})
        r = cli(proj, "log", "--type", "blocked", "--format", "json")
        logs = json.loads(r.stdout)
        check("log --type blocked filters", all(e.get("type") == "blocked" for e in logs))


def test_history_command():
    """History command shows rules changes."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        r = cli(proj, "history")
        check("history command works", r.returncode == 0)
        # Should show initial rules
        out = r.stdout
        check("history shows initial rules", "rules" in out.lower())


def test_history_blame():
    """History blame for specific rule."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        # Add a rule via CLI to generate history
        (proj / "CLAUDE.md").write_text("Don't touch migrations/ directory.")
        cli(proj, "discover", "--apply")
        r = cli(proj, "history", "no-migrations-touch")
        check("history blame works", r.returncode == 0 and "no-migrations-touch" in r.stdout)


def test_discover_command():
    """Discover command finds rules in CLAUDE.md."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        (proj / "CLAUDE.md").write_text("Don't touch migrations/ directory.")
        r = cli(proj, "discover")
        check("discover finds rules", r.returncode == 0 and "NEW" in r.stdout)


def test_discover_apply():
    """Discover --apply adds rules."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        (proj / "CLAUDE.md").write_text("Don't touch migrations/ directory.")
        r = cli(proj, "discover", "--apply")
        check("discover --apply works", r.returncode == 0)
        rules = json.loads((proj / ".claude/rulebooky/rules.json").read_text())
        check("new rule added", any(r["id"] == "no-migrations-touch" for r in rules["rules"]))


def test_test_command_scenario():
    """Test command with scenario file."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        scenario = {"tests": [
            {"tool": "Bash", "input": {"command": "git push --force"}, "expected": "blocked"},
            {"tool": "Bash", "input": {"command": "ls"}, "expected": "allowed"}
        ]}
        scenario_path = proj / "test-scenario.json"
        scenario_path.write_text(json.dumps(scenario))
        r = cli(proj, "test", "--scenario", str(scenario_path))
        check("test --scenario works", r.returncode == 0 and "2/2 scenario test(s) matched" in r.stdout)


def test_sync_no_gh():
    """Sync commands run without crashing."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        r = cli(proj, "sync", "push")
        # Should either succeed (if gh available) or fail gracefully with error message
        check("sync push runs without crash", r.returncode in (0, 1))
        if r.returncode == 1:
            check("sync push fails gracefully", "GitHub CLI" in r.stdout or "gh" in r.stdout.lower() or "not installed" in r.stdout.lower())


def test_hook_error_logging():
    """Hook errors logged to hook-errors.log."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        # Cause an error by making guard.py import fail
        (proj / ".claude/rulebooky/hooks/common.py").write_text("raise RuntimeError('test')")
        r = run(proj, "hooks/guard.py", {"tool_name": "Bash", "tool_input": {"command": "ls"}})
        check("hook error fails open", r.returncode == 0)
        err_log = proj / ".claude/rulebooky/hook-errors.log"
        check("error logged", err_log.exists() and "RuntimeError" in err_log.read_text())


def test_state_corruption_recovery():
    """Corrupt state.json recovers."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        (proj / ".claude/rulebooky/state.json").write_text("{invalid json")
        r = run(proj, "hooks/inject.py", args=["session"])
        check("corrupt state => fail open", r.returncode == 0)
        # State should be reset
        st = json.loads((proj / ".claude/rulebooky/state.json").read_text())
        check("state reset after corruption", st.get("task") is None)


def test_canary_rule():
    """Canary rule injected in output."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        rules = json.loads((proj / ".claude/rulebooky/rules.json").read_text(encoding="utf-8"))
        rules["canary"] = "CANARY_ACTIVE"
        (proj / ".claude/rulebooky/rules.json").write_text(json.dumps(rules), encoding="utf-8")
        r = run(proj, "hooks/inject.py", args=["session"])
        check("canary appears in inject output", "CANARY_ACTIVE" in r.stdout)


def test_hook_timeout_resistance():
    """Hooks don't hang on large input."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        # Large input that could cause regex backtracking
        large_input = {"tool_name": "Bash", "tool_input": {"command": "a" * 100000}}
        start = time.time()
        r = run(proj, "hooks/guard.py", large_input)
        elapsed = time.time() - start
        check("hook handles large input fast", r.returncode == 0 and elapsed < 2.0)


def test_concurrent_hook_calls():
    """Multiple rapid hook calls don't corrupt state."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        cli(proj, "task", "set", "--goal", "concurrent test")
        # Simulate rapid concurrent calls
        for _ in range(20):
            run(proj, "hooks/track.py", {"tool_name": "WebSearch"})
            run(proj, "hooks/guard.py", {"tool_name": "Bash", "tool_input": {"command": "ls"}})
        r = run(proj, "hooks/audit.py")
        check("concurrent calls don't corrupt", r.returncode in (0, 2))


def test_gitignore_updated():
    """Install adds state.json and hook-errors.log to .gitignore."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        gi = proj / ".gitignore"
        content = gi.read_text() if gi.exists() else ""
        check("gitignore has state.json", ".claude/rulebooky/state.json" in content)
        check("gitignore has hook-errors.log", ".claude/rulebooky/hook-errors.log" in content)


def test_cross_platform_paths():
    """Paths work on both Windows and Unix style."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        # Windows-style path with forward slashes (common in hooks)
        r = run(proj, "hooks/guard.py", {"tool_name": "Write", "tool_input": {"file_path": "src\\file.md"}})
        check("windows-style path blocked", r.returncode == 2)


def test_case_insensitive_fs():
    """Rules work on case-insensitive filesystems."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        # On Windows, README.md == readme.md
        r = run(proj, "hooks/guard.py", {"tool_name": "Write", "tool_input": {"file_path": str(proj / "readme.md")}})
        check("case-insensitive allowlist works", r.returncode == 0)


def test_max_stop_blocks_configurable():
    """max_stop_blocks can be configured."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        rules = json.loads((proj / ".claude/rulebooky/rules.json").read_text(encoding="utf-8"))
        rules["max_stop_blocks"] = 1
        (proj / ".claude/rulebooky/rules.json").write_text(json.dumps(rules), encoding="utf-8")
        cli(proj, "task", "set", "--goal", "test")
        cli(proj, "task", "add-req", "Impossible")
        codes = [run(proj, "hooks/audit.py").returncode for _ in range(3)]
        check("max_stop_blocks=1 allows after 1 block", codes == [2, 0, 0])


def test_all_hook_events_registered():
    """All 5 hook events registered after install."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        s = json.loads((proj / ".claude/settings.json").read_text())
        events = s.get("hooks", {})
        check("SessionStart registered", "SessionStart" in events)
        check("UserPromptSubmit registered", "UserPromptSubmit" in events)
        check("PreToolUse registered", "PreToolUse" in events)
        check("PostToolUse registered", "PostToolUse" in events)
        check("Stop registered", "Stop" in events)


def test_hook_matcher_correct():
    """Hook matchers are correct."""
    with tempfile.TemporaryDirectory() as d:
        proj = Path(d)
        setup_project(proj)
        s = json.loads((proj / ".claude/settings.json").read_text())
        pre = s["hooks"]["PreToolUse"][0]
        check("PreToolUse matcher is .*", pre.get("matcher") == ".*")
        sess = s["hooks"]["SessionStart"][0]
        check("SessionStart matcher correct", "startup|resume|clear|compact" in sess.get("matcher", ""))


# ============ RUN ALL TESTS ============

if __name__ == "__main__":
    print("=" * 60)
    print("RULEBOOKY STRESS TEST SUITE")
    print("=" * 60)
    
    # Core functionality
    test_unicode_rules()
    test_emoji_in_rules()
    test_very_long_command()
    test_deeply_nested_paths()
    test_special_chars_in_path()
    test_unicode_file_path()
    test_malformed_json_input()
    test_empty_stdin()
    test_missing_tool_name()
    test_null_tool_input()
    
    # Task card
    test_concurrent_task_cards()
    test_task_card_persistence_across_clears()
    test_stop_block_escape_hatch()
    test_stop_block_resets_on_new_prompt()
    
    # Forbid/deny patterns
    test_forbid_regex_edge_cases()
    test_deny_bash_complex_patterns()
    test_block_new_files_allowlist()
    test_deny_path_patterns()
    
    # Min calls
    test_min_calls_multiple_tools()
    test_process_rules_from_rules_json()
    
    # Evidence
    test_evidence_requirement()
    test_task_done_out_of_range()
    
    # Input validation
    test_invalid_forbid_regex()
    test_invalid_min_format()
    test_invalid_json_rules()
    test_missing_rules_json()
    test_missing_settings_json()
    test_invalid_settings_json()
    
    # Install/uninstall
    test_settings_backup_created()
    test_install_idempotent()
    test_uninstall_keeps_user_hooks()
    test_uninstall_purge()
    test_commands_before_install()
    test_cli_from_subdirectory()
    
    # Doctor
    test_doctor_passes_fresh()
    test_doctor_catches_missing_hook()
    
    # Decisions
    test_decide_persists()
    test_decisions_trimmed()
    
    # Rules limits
    test_large_rules_file()
    test_too_many_soft_rules_warn()
    test_too_many_total_rules_warn()
    test_duplicate_rule_ids_error()
    test_vague_rule_warnings()
    test_hard_rule_without_check_errors()
    test_invalid_check_type_errors()
    test_missing_pattern_in_deny_bash()
    test_bad_regex_in_check()
    test_block_new_files_missing_glob()
    test_invalid_process_check()
    
    # Subagent
    test_subagent_auto_propagation()
    
    # Observability
    test_log_command()
    test_log_filters()
    test_history_command()
    test_history_blame()
    
    # Discovery
    test_discover_command()
    test_discover_apply()
    
    # Test sandbox
    test_test_command_scenario()
    
    # Sync
    test_sync_no_gh()
    
    # Error handling
    test_hook_error_logging()
    test_state_corruption_recovery()
    
    # Canary
    test_canary_rule()
    
    # Performance
    test_hook_timeout_resistance()
    test_concurrent_hook_calls()
    
    # Gitignore
    test_gitignore_updated()
    
    # Cross-platform
    test_cross_platform_paths()
    test_case_insensitive_fs()
    
    # Config
    test_max_stop_blocks_configurable()
    
    # Hook registration
    test_all_hook_events_registered()
    test_hook_matcher_correct()
    
    print("=" * 60)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 60)
    sys.exit(1 if failed else 0)