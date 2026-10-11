# Contributing to Rulebooky

Thank you for your help. This project is small by design. It uses Python
only. It uses no extra libraries. Small and tested changes are best.

## Rules

- Use Python 3.8 or newer. Use standard library only.
- Hooks must fail open. On error, write to `hook-errors.log`. Exit with 0.
  Never break the user session.
- Each behavior change needs a test in `tests/run_tests.py`.
- Keep rules short and testable. See `references/rules-schema.md`.

## Setup

Do these steps:

1. Copy the repo:
   ```bash
   git clone https://github.com/viki22uied/Rulebooky.git
   cd Rulebooky
   ```
2. Run the tests:
   ```bash
   python3 tests/run_tests.py
   ```

No install step is necessary. No virtualenv is necessary.

## How to make a change

1. Fork the repo. Make a branch:
   ```bash
   git checkout -b fix/short-name
   ```
2. Edit files in `scripts/`, `templates/`, `references/`, or docs.
3. Add a `check(...)` case in `tests/run_tests.py`. It must fail without
   your fix. It must pass with your fix.
4. Run the full suite:
   ```bash
   python3 tests/run_tests.py
   ```
   All tests must pass.
5. If you change rule parsing, check `lint` output in the suite.

## Commit and pull request rules

- Use one change per pull request. Keep diffs small.
- Use short subjects (70 characters or less). Use command form. Example:
  `Fix guard bypass for NotebookEdit paths`.
- In the request, describe the problem. Describe the fix. Show how you
  tested it. Paste the `N passed, 0 failed` line.
- State limits clearly. Do not claim that advice is enforced.

## How to report a bug

Open an issue. Include these items:

- Python version (`python3 --version`) and OS.
- Claude Code version and `/hooks` output.
- Smallest `rules.json` that shows the fault.
- Fake hook event JSON that shows the fault, if you have it.
- Lines from `.claude/rulebooky/hook-errors.log`. Remove private paths.
