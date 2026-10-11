# Changelog

All big changes are listed here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Numbers follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

No changes yet.

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
