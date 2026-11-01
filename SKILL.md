---
name: rulebooky
description: Make Claude Code actually follow the user's rules instead of just reading them. Use whenever the user sets rules, constraints or "do not" instructions; asks Claude to follow a document or spec; complains Claude forgets rules or context, ignores instructions, mixes up tasks, brute-forces, stops researching after one search, or creates too many .md files; or starts any multi-step task, research task, or subagent work. Compiles rules into one rules.json, enforces them with hooks (block, re-inject, audit before stopping), and tracks a task card that survives /clear and compaction. Use it even if the user does not say "rulebooky".
---

# rulebooky

Rules in markdown are advice. This skill turns them into enforcement: hooks block forbidden actions, re-inject the rules every turn and after /clear or compaction, and refuse to let you stop while the task is unfinished.

All state lives in two files. Never create other files for rules or notes.
- `.claude/rulebooky/rules.json`: the only rule store (committed)
- `.claude/rulebooky/state.json`: current task card, counters, decisions (not committed)

CLI: `python .claude/rulebooky/rulebooky.py <cmd>` (call it `RL` below).

## 1. First-time setup
1. Run `python <this-skill-dir>/scripts/rulebooky.py install` in the project root.
2. Collect the user's rules (they may paste messy docs, CLAUDE.md files, chat history). Merge everything into `rules.json` with `RL rule add` (below). Do not copy the source files. Do not edit `rules.json` with Write/Edit: Claude Code treats `.claude/` as sensitive and will refuse or prompt.
   - `RL rule add ID --tier hard --text "..." --deny-bash REGEX` (or `--deny-path REGEX`, or `--block-new GLOB [--allow NAME]...`)
   - `RL rule add ID --tier process --text "..." [--min TOOL=N]`
   - `RL rule add ID --tier soft --text "..."`
   - `RL rule list`, `RL rule remove ID`, `--replace` to change one. Each command validates and lints.
3. Classify each rule. Be strict about tiers:
   - **hard**: a tool call can be detected and blocked. Needs a `check` (see `references/rules-schema.md`). Examples: no new .md files, no force push, never touch `migrations/`.
   - **process**: a checkable step. Only `min_calls` (tool + count) is automatable, e.g. WebSearch at least 3. Other process rules are workflow text that point at the task card.
   - **soft**: style/behaviour that cannot be checked (tone, format). Max 10.
4. If a rule cannot be made hard, tell the user plainly it is advisory. Do not pretend it is enforced.
5. Keep rules short, imperative, testable. Max 25 total. Merge duplicates, drop vague ones ("follow best practices").
6. Check each hard rule blocks what it should and nothing else: `RL test --tool Bash --input '{"command": "..."}'`, or put several cases in a scenario file and run `RL test --scenario FILE` (exits 1 on a mismatch). A single plain `RL ...` call is never blocked for quoting a forbidden command in its text; chained commands are.
7. Run `RL doctor`, fix every FAIL line, then tell the user to restart Claude Code so hooks load. If anything misbehaves later, run `RL doctor` first. (The install step is needed because a skill alone cannot block anything; the hooks live in `.claude/settings.json` so they run in every session.)

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
Subagents do not inherit this conversation. The `SubagentStart` hook gives every subagent the rules and the task card, and hard rules also block the subagent's own tool calls. Still require each subagent to report evidence per requirement. On a Claude Code version without `SubagentStart` (`RL doctor` shows it), paste the output of `RL brief` at the top of the subagent prompt.

## 5. Changing rules
Change rules only with `RL rule add|remove` (it lints for you). When the user corrects you, turn the correction into one new checkable rule (hard if detectable), not a paragraph. Never write rules into new .md files.

## 6. More commands
- `RL discover` — scan CLAUDE.md, .cursorrules, AGENTS.md for rules. `--apply` adds them. Review what it adds; the patterns are heuristics.
- `RL test --scenario FILE` (or `--tool Bash --input '{"command":"..."}'`) — dry-run rules. Exits 1 if a case does not match `expected`. Use it after every rule change.
- `RL log [--since 7d] [--type blocked] [--format summary]` — enforcement history.
- `RL history [rule-id]` — rules.json change history; with an id, when it was added/removed.
- `RL sync push|pull|ci` — share rules via a GitHub Gist (needs `gh`). `ci` exits 1 if local != remote.

## Limits to state honestly
Hooks cannot judge quality or method. They enforce what a tool call, a count, or a checklist can show. Bash can bypass file-path rules, so add `deny_bash` patterns for the risky commands.
