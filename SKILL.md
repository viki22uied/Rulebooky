---
name: rulebooky
description: Make Claude Code actually follow the user's rules instead of just reading them. Use whenever the user sets rules, constraints or "do not" instructions; asks Claude to follow a document or spec; complains Claude forgets rules or context, ignores instructions, mixes up tasks, brute-forces, stops researching after one search, or creates too many .md files; or starts any multi-step task, research task, or subagent work. Compiles rules into one rules.json, enforces them with hooks (block, re-inject, audit before stopping), and tracks a task card that survives /clear and compaction. Use it even if the user does not say "rulebooky".
---

# rulebooky

Rules in markdown are advice. This skill turns them into enforcement: hooks block forbidden actions, re-inject the rules every turn and after /clear or compaction, and refuse to let you stop while the task is unfinished.

All state lives in two files. Never create other files for rules or notes.
- `.claude/rulebooky/rules.json`: the only rule store (committed)
- `.claude/rulebooky/state.json`: current task card, counters, decisions (not committed)

CLI: `python3 .claude/rulebooky/rulebooky.py <cmd>` (call it `RL` below).

## 1. First-time setup
1. Run `python3 <this-skill-dir>/scripts/rulebooky.py install` in the project root.
2. Collect the user's rules (they may paste messy docs, CLAUDE.md files, chat history). Merge everything into `rules.json`. Do not copy the source files.
3. Classify each rule. Be strict about tiers:
   - **hard**: a tool call can be detected and blocked. Needs a `check` (see `references/rules-schema.md`). Examples: no new .md files, no force push, never touch `migrations/`.
   - **process**: a checkable step. Only `min_calls` (tool + count) is automatable, e.g. WebSearch at least 3. Other process rules are workflow text that point at the task card.
   - **soft**: style/behaviour that cannot be checked (tone, format). Max 10.
4. If a rule cannot be made hard, tell the user plainly it is advisory. Do not pretend it is enforced.
5. Keep rules short, imperative, testable. Max 25 total. Merge duplicates, drop vague ones ("follow best practices").
6. Run `RL doctor`, fix every FAIL line, then tell the user to restart Claude Code so hooks load. If anything misbehaves later, run `RL doctor` first.

## 2. Every non-trivial task
1. Before doing anything else: `RL task set --goal "..." --method "..." [--forbid REGEX]... [--min WebSearch=N] [--done-when "..."]`.
   - `--forbid` takes a regex matched against Bash commands and file paths. Convert the user's "do not X" into one when X is detectable. If it is not (e.g. "don't brute force"), put it in `--method` and say it is unenforced.
   - `--min`: set it when the user asked for research depth (e.g. "search thoroughly" means `WebSearch=5` or more, one per sub-question).
2. If the user named a document/spec to follow: read it fully, then `RL task add-req "..."` once per concrete requirement. Quote its numbering where it has one.
3. Work. After each milestone: `RL decide "short decision"` for anything that must survive a reset.
4. Mark each requirement: `RL task done N --evidence "file:line / command output / URL"`. No evidence, not done.
5. When everything is done and verified: `RL task close`. Then summarise requirement by requirement with the evidence.
6. New, unrelated task from the user: close or replace the card. Never merge two tasks into one card.

## 3. When a hook blocks you
- A BLOCKED message is a rule, not a bug. Pick a different approach. Never retry the same action, rename to dodge a pattern, or route around it through Bash.
- A Stop block lists what is unmet. Do that work, then stop. If the user dropped it, tell them and use `RL task close --force`.

## 4. Subagents
Subagents do not inherit this conversation. Paste the output of `RL brief` at the top of every subagent prompt, and require them to report evidence per requirement.

## 5. Changing rules
Edit only `rules.json`, then `RL lint`. When the user corrects you, turn the correction into one new checkable rule (hard if detectable), not a paragraph. Never write rules into new .md files.

## Limits to state honestly
Hooks cannot judge quality or method. They enforce what a tool call, a count, or a checklist can show. Bash can bypass file-path rules, so add `deny_bash` patterns for the risky commands.
