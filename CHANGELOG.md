# Changelog

All big changes are listed here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Numbers follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

No changes yet.

## [0.2.1] - 2026-11-01

### Fixed

- **Every prompt was blocked.** `install` wrote the hook command as
  `python3 "…/inject.py prompt"`, with the mode argument inside the quotes,
  so Python looked for a file named `inject.py prompt` and exited 2. In
  Claude Code, that blocked every `UserPromptSubmit` and broke `SessionStart`.
  Re-run `install` to fix existing projects.
- Subagent propagation never worked: `guard.py` called an undefined
  `render()` (a `NameError`, silently logged), and a PreToolUse hook cannot
  change tool input by editing it in memory anyway. Replaced by a
  `SubagentStart` hook that returns the rules and task card as
  `additionalContext`. Claude Code calls the subagent tool `Agent` now, not
  `Task`.
- One bad rule (bad regex, missing `type`, non-numeric `n`, non-object
  entry) made the hook crash and fail open, so *every* rule was off. Bad rules
  are now skipped one by one and logged in `hook-errors.log`.
- Parallel tool calls lost `min_calls` counts (6 of 50 parallel PostToolUse
  calls were recorded). State updates now take a cross-platform file lock,
  and temp files are unique per process.
- `log --since` crashed (`time` was not imported). A bad `--since` value now
  gives a friendly error.
- `test --scenario` crashed on a bad regex and always exited 0. It now exits
  1 on a mismatch and prints the rule messages, not Python tuples.
- `history` showed wrong diffs (`list.index` on equal entries). Blame now
  shows when a rule was added and removed.
- `sync push` made a new gist on every push. It now updates the gist in
  `gist_id`. `sync pull` checks the remote JSON before writing it.
- `lint` crashed on a `rules.json` that is not an object, or on a
  `"rules"` value that is not a list.
- `doctor` could not read a quoted interpreter path with spaces (Windows).
- `*.md` block was case-sensitive on Linux/macOS: `NOTES.MD` slipped through.
- `discover` walked all of `node_modules` before filtering, and missed
  curly apostrophes (`don’t`).
- `actions.log` stored full tool input, including the content of every file
  written (secrets risk, unbounded growth). It now keeps only the command
  or path, truncated, and rotates at about 1 MB.
- `uninstall --purge` left `actions.log`, `rules-history.jsonl` and temp
  files behind. `install` now gitignores all runtime files.
- The Stop message told users to run `python3`; it now says `python`.
- README.md had UTF-16 junk appended (`# C I trigger`) from a Windows echo.

### Added

- `rule add|remove|list` commands. Claude Code treats `.claude/` files as
  sensitive, so in a real session Claude's Write/Edit of `rules.json` was
  refused (headless) or prompted every time. SKILL.md now uses the CLI.

### Changed

- A single plain call of the rulebooky CLI is no longer blocked by
  `deny_bash`/`--forbid` for quoting a forbidden command in its arguments.
  Found in a real session: Claude could not record `task done --evidence`
  because the evidence named `migrations/`. Chained commands, `uninstall`
  and `rule remove` are still checked.
- `doctor` runs every registered hook command through a shell (`sh`, or Git
  Bash on Windows) with `$CLAUDE_PROJECT_DIR` set, as Claude Code does.
- `SessionStart` matcher also covers `fork`.
- CI: Python 3.9 is no longer available on `ubuntu-latest` (Ubuntu 26.04),
  which failed every run since 0.2.0. The matrix is now 3.10–3.14 on all
  three OSes, plus 3.9 on macOS. CI also runs `tests/stress_test.py`, uses
  `actions/checkout@v5` and `actions/setup-python@v6` (Node 24), allows manual
  re-runs (`workflow_dispatch`), and the `gate` job now fails instead of
  being skipped when tests fail.

## [0.2.0] - 2026-10-31

### Added

- `discover` command: scan CLAUDE.md, .cursorrules, AGENTS.md and other rule files. Suggest checkable rules with tier and check config. `--apply` writes to rules.json.
- `test` command: dry-run rules against sample inputs. `--scenario` runs multiple test cases from a JSON file. Shows pass/fail per case.
- `log` command: view blocked/allowed actions, stop blocks. Filters: `--since 7d`, `--type blocked`, `--tool Bash`. Formats: table, json, summary.
- `history` command: audit trail of every rules.json change. `history <rule-id>` shows blame for one rule.
- `sync` command: push/pull rules to GitHub Gist via `gh` CLI. `sync ci` validates rules.json matches remote (exit 1 if diverged).
- Subagent auto-propagation: Task tool calls automatically receive rules + task card. No manual `RL brief` copy needed.
- Observability: all blocks, allows, stop blocks logged to `.claude/rulebooky/actions.log` (JSONL).
- Cross-platform: `python` used everywhere (not `python3`). Windows users no longer need `--python python`.

### Changed

- `doctor` output now says "Run: python .claude/rulebooky/rulebooky.py doctor" after fixes.
- README: all examples use `python` (cross-platform). Added sections for discover, test, log, history, sync.
- Version bump to 0.2.0.

## [0.1.1] - 2026-10-11

### Added

- `doctor` command: checks Python, hooks, settings, rules, and scripts.
  Run it first when in doubt.
- `uninstall` command: removes hooks from settings. Keeps `rules.json`.
  `--purge` also deletes scripts and state.
- `install --python NAME`: forces one Python 3 command for hooks.
- Settings backup at `.claude/settings.json.rulebooky.bak` on install.

### Fixed

- Install refuses bad `settings.json` and changes nothing. No half install.
- Install finds a Python 3 that truly runs (skips dead stubs).
- CLI works from project subfolders with no env var.
- Friendly errors (no tracebacks) for bad regex, bad `--min`, bad task
  numbers, and commands run before install.
- UTF-8 forced on all IO. Unicode rules cannot crash hooks on Windows.
- `SKILL.md` setup now ends with `RL doctor`, not `RL lint`.

## [0.1.0] - 2026-10-11

Earlier versions of this file listed this release as 1.0.0. The releases
after it are 0.1.1 and 0.2.0, so it is renumbered 0.1.0 to keep the order.

### Added

- First public release of the Rulebooky Claude Code skill.
- `SKILL.md` workflow: write user rules into `rules.json`, enforce with
  hooks, track one task card with proof.
- `scripts/rulebooky.py` CLI: `install`, `lint`, `task`, `decide`, `brief`.
- Hooks: `inject.py`, `guard.py`, `track.py`, `audit.py`, `common.py`.
- `templates/rules.json` start rules and `references/rules-schema.md` guide.
- `tests/run_tests.py` suite (23 checks, no libraries).
- Repo files: MIT license, security policy, conduct code, guide, CI,
  `.gitignore` for runtime state.
