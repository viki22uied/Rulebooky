#!/usr/bin/env python3
"""rulebooky CLI: install hooks, lint rules, manage the task card. Stdlib only.

  rulebooky.py install [--project DIR]
  rulebooky.py lint
  rulebooky.py status | brief
  rulebooky.py task set --goal G [--method M] [--forbid REGEX]... [--min TOOL=N]... [--done-when D]
  rulebooky.py task add-req "text" | done N --evidence "..." | close [--force]
  rulebooky.py decide "text"
"""
import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "hooks"))
import common as C  # noqa: E402

HOOKS = {
    "SessionStart": ("startup|resume|clear|compact", "inject.py session"),
    "UserPromptSubmit": (None, "inject.py prompt"),
    "PreToolUse": (".*", "guard.py"),
    "PostToolUse": (".*", "track.py"),
    "Stop": (None, "audit.py"),
}
MARK = "rulebooky/hooks/"
TIERS = ("hard", "process", "soft")
HARD_CHECKS = ("deny_bash", "deny_path", "block_new_files")
VAGUE = ("best practice", "clean code", "properly", "appropriate", "as needed",
         "good ", "efficient", "high quality", "robust")


def cmd_install(a):
    proj = Path(a.project).resolve()
    dst = proj / ".claude" / "rulebooky"
    (dst / "hooks").mkdir(parents=True, exist_ok=True)
    for f in (HERE / "hooks").glob("*.py"):
        shutil.copy2(str(f), str(dst / "hooks" / f.name))
    shutil.copy2(str(HERE / "rulebooky.py"), str(dst / "rulebooky.py"))
    rules = dst / "rules.json"
    if not rules.exists():
        shutil.copy2(str(HERE.parent / "templates" / "rules.json"), str(rules))
    settings_p = proj / ".claude" / "settings.json"
    settings = C.load_json(settings_p, {})
    hooks = settings.setdefault("hooks", {})
    for event, (matcher, script) in HOOKS.items():
        kept = [e for e in hooks.get(event, [])
                if not any(MARK in h.get("command", "") for h in e.get("hooks", []))]
        cmd = 'python3 "$CLAUDE_PROJECT_DIR/.claude/rulebooky/hooks/%s"' % script
        entry = {"hooks": [{"type": "command", "command": cmd}]}
        if matcher:
            entry["matcher"] = matcher
        hooks[event] = kept + [entry]
    C.save_json(settings_p, settings)
    gi = proj / ".gitignore"
    line = ".claude/rulebooky/state.json"
    cur = gi.read_text(encoding="utf-8") if gi.exists() else ""
    if line not in cur:
        gi.write_text(cur + ("" if cur.endswith("\n") or not cur else "\n") +
                      line + "\n.claude/rulebooky/hook-errors.log\n", encoding="utf-8")
    print("Installed into %s\nEdit %s, then run: python3 .claude/rulebooky/rulebooky.py lint" % (dst, rules))
    print("Restart Claude Code (or /hooks to review) so the new hooks load.")


def cmd_lint(a):
    rules = C.load_json(C.rules_path(), None)
    if rules is None:
        print("ERROR: no readable rules.json at %s" % C.rules_path())
        return 1
    errs, warns, ids = [], [], set()
    rs = rules.get("rules", [])
    for r in rs:
        rid = r.get("id", "?")
        if rid in ids:
            errs.append("duplicate id: " + rid)
        ids.add(rid)
        if r.get("tier") not in TIERS:
            errs.append("%s: tier must be one of %s" % (rid, TIERS))
        if not r.get("text"):
            errs.append("%s: missing text" % rid)
        elif len(r["text"]) > 160:
            warns.append("%s: text over 160 chars, long rules get ignored" % rid)
        low = r.get("text", "").lower()
        for v in VAGUE:
            if v in low:
                warns.append("%s: vague wording '%s', make it checkable" % (rid, v.strip()))
        c = r.get("check")
        if r.get("tier") == "hard":
            if not c or c.get("type") not in HARD_CHECKS:
                errs.append("%s: hard rule needs check.type in %s (else make it soft)" % (rid, HARD_CHECKS))
            else:
                pat = c.get("pattern")
                if c["type"] in ("deny_bash", "deny_path"):
                    try:
                        re.compile(pat or "")
                    except re.error as e:
                        errs.append("%s: bad regex: %s" % (rid, e))
                    if not pat:
                        errs.append("%s: missing pattern" % rid)
                if c["type"] == "block_new_files" and not c.get("glob"):
                    errs.append("%s: block_new_files needs glob" % rid)
        if r.get("tier") == "process" and c:
            if c.get("type") != "min_calls" or not c.get("tool") or not str(c.get("n", "")).isdigit():
                errs.append("%s: process check must be {type:min_calls, tool, n}" % rid)
    soft = sum(1 for r in rs if r.get("tier") == "soft")
    if soft > 10:
        warns.append("%d soft rules; keep <=10, extra ones dilute the rest" % soft)
    if len(rs) > 25:
        warns.append("%d rules total; cap is 25, prune" % len(rs))
    # markdown sprawl check
    proj = C.project_dir()
    mds = [p for p in list((proj / ".claude").rglob("*.md")) + list(proj.glob("*.md"))
           if "node_modules" not in p.parts and ".git" not in p.parts
           and "skills" not in p.parts]
    if len(mds) > 6:
        warns.append("%d markdown files in project root/.claude; rules should live only in rules.json" % len(mds))
    for e in errs:
        print("ERROR: " + e)
    for w in warns:
        print("WARN:  " + w)
    print("%d rules (%d hard, %d process, %d soft)" % (
        len(rs), sum(r.get("tier") == "hard" for r in rs),
        sum(r.get("tier") == "process" for r in rs), soft))
    return 1 if errs else 0


def cmd_status(a):
    print(C.render(C.load_rules(), C.load_state()))
    return 0


def cmd_task(a):
    st = C.load_state()
    t = st.get("task")
    if a.sub == "set":
        for pat in a.forbid or []:
            re.compile(pat)  # fail early on bad regex
        mins = {}
        for m in a.min or []:
            tool, n = m.split("=")
            mins[tool] = int(n)
        st["task"] = {"goal": a.goal, "method": a.method or "", "forbid": a.forbid or [],
                      "min_calls": mins, "done_when": a.done_when or "", "reqs": []}
        st["counters"], st["stop_blocks"] = {}, 0
    elif not t:
        print("No open task. Run: task set --goal ...")
        return 1
    elif a.sub == "add-req":
        t["reqs"].append({"text": a.text, "done": False, "evidence": ""})
    elif a.sub == "done":
        if not a.evidence.strip():
            print("Evidence required (file:line, command output, URL).")
            return 1
        t["reqs"][a.n - 1].update(done=True, evidence=a.evidence)
    elif a.sub == "close":
        left = C.open_reqs(t)
        if left and not a.force:
            print("Open requirements remain: %s. Use --force only if the user dropped them." %
                  [i for i, _ in left])
            return 1
        st["task"], st["counters"], st["stop_blocks"] = None, {}, 0
    C.save_state(st)
    print(C.render(C.load_rules(), st))
    return 0


def cmd_decide(a):
    st = C.load_state()
    st["decisions"] = (st["decisions"] + [a.text])[-20:]
    C.save_state(st)
    return 0


def main():
    p = argparse.ArgumentParser(prog="rulebooky")
    sp = p.add_subparsers(dest="cmd", required=True)
    i = sp.add_parser("install"); i.add_argument("--project", default="."); i.set_defaults(f=cmd_install)
    sp.add_parser("lint").set_defaults(f=cmd_lint)
    sp.add_parser("status").set_defaults(f=cmd_status)
    sp.add_parser("brief").set_defaults(f=cmd_status)
    d = sp.add_parser("decide"); d.add_argument("text"); d.set_defaults(f=cmd_decide)
    t = sp.add_parser("task"); ts = t.add_subparsers(dest="sub", required=True)
    s = ts.add_parser("set"); s.add_argument("--goal", required=True); s.add_argument("--method")
    s.add_argument("--forbid", action="append"); s.add_argument("--min", action="append")
    s.add_argument("--done-when")
    ar = ts.add_parser("add-req"); ar.add_argument("text")
    dn = ts.add_parser("done"); dn.add_argument("n", type=int); dn.add_argument("--evidence", required=True)
    cl = ts.add_parser("close"); cl.add_argument("--force", action="store_true")
    t.set_defaults(f=cmd_task)
    a = p.parse_args()
    sys.exit(a.f(a) or 0)


if __name__ == "__main__":
    main()
