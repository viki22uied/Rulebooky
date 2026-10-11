# Changelog

All big changes are listed here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Numbers follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

No changes yet.

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
