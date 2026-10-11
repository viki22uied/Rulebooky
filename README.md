# Rulebooky — Make Claude Code Obey Your Rules

[![CI](https://github.com/viki22uied/Rulebooky/actions/workflows/ci.yml/badge.svg)](https://github.com/viki22uied/Rulebooky/actions/workflows/ci.yml)
[![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![No dependencies](https://img.shields.io/badge/deps-zero-brightgreen.svg)](scripts/rulebooky.py)

Claude Code reads your rules. rulebooky makes it obey them.

`CLAUDE.md` is only advice. Rules fade in long sessions. Rules are lost
after `/clear` and compaction. Claude creates extra `.md` files and forgets
them. rulebooky moves checks from the prompt into hooks.

> Search terms: claude-code, claude-skill, ai-coding-assistant,
> llm-rules-engine, prompt-adherence, git-hooks, task-tracking, subagents,
> developer-tools.

---

## Contents

- [1. Why rulebooky](#1-why-rulebooky)
- [2. How it works](#2-how-it-works)
- [3. Quickstart](#3-quickstart)
- [4. Daily use](#4-daily-use)
- [5. How to write rules](#5-how-to-write-rules)
- [6. Subagents](#6-subagents)
- [7. File layout](#7-file-layout)
- [8. Tests](#8-tests)
- [9. Troubleshooting](#9-troubleshooting)
- [10. Honest limits](#10-honest-limits)
- [11. Contribution and security](#11-contribution-and-security)
- [12. License](#12-license)

---

## 1. Why rulebooky

| Problem | Solution |
|---|---|
| Claude does what you forbade | The `PreToolUse` hook stops the command (exit 2) |
| Claude creates too many `.md` files | One `block_new_files` rule stops new files |
| Claude forgets rules after `/clear` | The `SessionStart` hook shows rules again each time |
| Claude ignores your document | The task card tracks each requirement with proof |
| Claude stops after one search | The `min_calls` check requires N searches |
| Subagents start with no context | The `brief` command gives them the task card |
| Claude mixes two tasks | One card holds one task only |

## 2. How it works

The system uses two files in your project:

- `.claude/rulebooky/rules.json` — the only rule store. Commit this file.
- `.claude/rulebooky/state.json` — the task card and counters. Do not commit
  this file. `.gitignore` already excludes it.

The skill (`SKILL.md`) tells Claude to read your rules and write them into
`rules.json`. Five small scripts (Python only, no libraries) enforce them:

| Event | Script | Function |
|---|---|---|
| `SessionStart`, `UserPromptSubmit` | `inject.py` | Show rules and task card |
| `PreToolUse` | `guard.py` | Stop violations (exit 2) |
| `PostToolUse` | `track.py` | Count tool calls |
| `Stop` | `audit.py` | Stop Claude if work is open |

In this guide, `RL` means `python3 .claude/rulebooky/rulebooky.py`.

## 3. Quickstart

You need Python 3.8 or newer. You need Claude Code with hook support. On
Windows, use `python` and not `python3`.

Do these steps:

1. Install the skill. Run one of these commands:
   ```bash
   git clone https://github.com/viki22uied/Rulebooky.git ~/.claude/skills/rulebooky
   ```
   Or, for one project only:
   ```bash
   git clone https://github.com/viki22uied/Rulebooky.git <your-project>/.claude/skills/rulebooky
   ```
2. Install the hooks into your project:
   ```bash
   cd your-project
   python3 ~/.claude/skills/rulebooky/scripts/rulebooky.py install
   python3 .claude/rulebooky/rulebooky.py lint
   ```
3. Restart Claude Code. Check `/hooks`. You must see five rulebooky entries.
4. Tell Claude: *Use rulebooky. Here are my rules: ...*

To update, run `git -C ~/.claude/skills/rulebooky pull`. Then run `install`
again in each project. The command is safe to run twice.

## 4. Daily use

Claude runs these commands. You can also run them by hand.

1. Open a task card before large work:
   ```bash
   python3 .claude/rulebooky/rulebooky.py task set \
     --goal "Port auth to the API in spec.pdf" \
     --method "follow spec sections in order" \
     --forbid "scrape\.py" --min WebSearch=5
   ```
2. Add one requirement for each item in your document:
   ```bash
   python3 .claude/rulebooky/rulebooky.py task add-req "Spec 3.2: tokens expire after 15 min"
   ```
3. Save each decision:
   ```bash
   python3 .claude/rulebooky/rulebooky.py decide "chose JWT per spec 3.1"
   ```
4. Close each requirement with proof (file and line, command result, or URL):
   ```bash
   python3 .claude/rulebooky/rulebooky.py task done 1 --evidence "auth/token.py:41"
   ```
5. Close the task when all work is done:
   ```bash
   python3 .claude/rulebooky/rulebooky.py task close
   ```

If a hook stops you, the `BLOCKED` message is a rule. It is not a bug. Use a
different method. Do not try the same action again. Do not change a file name
to avoid a rule. A `Stop` block shows open work. Do that work first. Use
`task close --force` only if the user cancelled the work.

## 5. How to write rules

Keep each rule short. Use clear commands. Use a maximum of 25 rules. Use a
maximum of 10 soft rules. Remove vague rules such as "follow best practices".

| Type | Meaning | Example |
|---|---|---|
| **hard** | The hook can stop it. It needs a `check`. | `Never run git push --force` |
| **process** | The hook can count it. It uses `min_calls`. | `Research needs 5 or more searches` |
| **soft** | No hook can check it. It is style only. | `Answer in short point form` |

For full syntax and examples, read
[`references/rules-schema.md`](references/rules-schema.md). For a start set,
see [`templates/rules.json`](templates/rules.json). After each change, run
`RL lint`. If a rule cannot be hard, keep it as advice. Do not claim it is
enforced.

## 6. Subagents

Subagents do not see this chat. Copy the output of `RL brief` into each
subagent prompt. Ask each subagent to give proof for each requirement. Note:
subagent tool calls may not increase parent counters. This is not verified.
Check counts in the parent session.

## 7. File layout

```text
SKILL.md                    orders that Claude obeys
scripts/rulebooky.py         CLI: install, lint, task, decide, brief
scripts/hooks/common.py     shared functions for paths and JSON
scripts/hooks/inject.py     shows context at start and each prompt
scripts/hooks/guard.py      stops violations before tool use
scripts/hooks/track.py      counts tool calls after tool use
scripts/hooks/audit.py      stops Claude if work is open
templates/rules.json        start rules
references/rules-schema.md  rule syntax and examples
tests/run_tests.py          full test suite
```

## 8. Tests

Run this command:

```bash
python3 tests/run_tests.py
```

The suite builds a test project. It sends fake hook events. It checks stops,
allow lists, forbid patterns, search counts, proof rules, install safety, and
fail-open faults. CI runs it on Python 3.8 through 3.12. CI runs it on
Ubuntu, macOS, and Windows. Result must be `23 passed, 0 failed`.

## 9. Troubleshooting

| Symptom | Action |
|---|---|
| Hooks do not run | Restart Claude Code. Run `/hooks`. Find five rulebooky entries. |
| `lint` shows errors | Read `references/rules-schema.md`. Fix tier and `check` type. |
| `audit` stops each time | Run `task done N --evidence "..."` for each item. Meet `min_calls`. |
| `python3` is not found (Windows) | Use `python` in all commands. Edit hook commands in settings. |
| Strange acts after hook change | Run `install` again. Restart Claude Code. Read `hook-errors.log`. |

## 10. Honest limits

- Hooks check tool calls, counts, and lists. They do not judge quality.
  They do not judge method. Such rules stay as advice.
- File rules can be avoided through Bash (example: `echo > x.md`). Add
  `deny_bash` patterns for such commands.
- The Stop hook has a limit (`max_stop_blocks`, default 3 per prompt). This
  stops a bad card from locking the session. You can change it.
- Proof is written by Claude. The hook checks that proof is present. It does
  not check that proof is true.
- Hooks fail open. If a script has an error, the session goes on. The error
  is written to `.claude/rulebooky/hook-errors.log`.
- Hook acts change with Claude Code versions. Check your version with
  `/hooks` and one real session.
- Subagent counters are not verified. Assume the parent does not count them.

## 11. Contribution and security

- Read [`CONTRIBUTING.md`](CONTRIBUTING.md) before you change code.
- Read [`SECURITY.md`](SECURITY.md) before you report a fault.
- Obey [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) in all talks.
- See [`CHANGELOG.md`](CHANGELOG.md) for release history.

## 12. License

MIT. See [LICENSE](LICENSE).
