# Changelog

All big changes are listed here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Numbers follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

No changes yet.

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

## [1.0.0] - 2026-10-11

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
