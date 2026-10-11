# Security Policy

## Supported versions

| Version | Support |
| ------- | ------- |
| 1.x (latest `main`) | Yes |

Security fixes go to latest `main` only. Old copies have no support.

## Scope

Rulebooky runs locally only. It is a Claude Code skill. It runs Python hook
scripts in your own project. It has these properties:

- It makes no network calls.
- It collects no data.
- It needs no keys and no tokens.
- It reads and writes `.claude/rulebooky/` only.

## How to report a fault

Do not open a public issue for security faults. Do these steps:

1. Open a [private security advisory](../../security/advisories/new).
   Or contact the maintainer through their GitHub profile.
2. Give the file and commit. Give steps to repeat the fault. Describe the
   effect (example: hook bypass, command run, path error).
3. Wait for a reply within 72 hours.

## Response process

1. We repeat the fault. We assess the severity.
2. We fix it on a private branch. We add a test in `tests/run_tests.py`.
3. We publish the fix. We add a `CHANGELOG.md` entry. For high severity,
   we publish a GitHub Security Advisory.

## Safe use notes

- Hooks run with your user rights. Read `scripts/hooks/*.py` and
  `scripts/rulebooky.py` before install. Code is short (circa 500 lines).
- Do not install with `sudo` or as Administrator.
- `deny_bash` and `deny_path` patterns are aids. They are not a sandbox.
  A skilled local prompt can avoid them. See README honest limits.
- Do not commit `state.json` and `hook-errors.log`. `.gitignore` already
  excludes them.
