# rules.json schema

```json
{
  "version": 1,
  "max_stop_blocks": 3,
  "canary": "",
  "rules": [ { "id": "...", "tier": "hard|process|soft", "text": "...", "check": { } } ]
}
```

- `max_stop_blocks`: how many times per user prompt the Stop hook may refuse to let Claude finish before releasing it (escape hatch).
- `canary`: optional string. If set, Claude must begin every reply with it. When replies stop starting with it, your rules have stopped landing.
- `id`: unique slug. `text`: one short imperative sentence (under 160 chars). Shown to Claude every turn.

## Hard checks (PreToolUse, blocked with exit code 2)

| type | fields | blocks when |
|---|---|---|
| `deny_bash` | `pattern` (regex) | the Bash command matches |
| `deny_path` | `pattern` (regex) | Write/Edit/MultiEdit/NotebookEdit targets a matching path |
| `block_new_files` | `glob`, `allow` (file names) | Write creates a NEW file whose name matches `glob` and is not in `allow` |

## Process checks (Stop hook)

| type | fields | meaning |
|---|---|---|
| `min_calls` | `tool`, `n` | while a task is open, `tool` (e.g. `WebSearch`) must have been called at least `n` times since `task set` |

Task cards add their own `--min` and `--forbid` on top of these.

## Examples

```json
{"id":"no-prod-db","tier":"hard","text":"Never run commands against the production database.",
 "check":{"type":"deny_bash","pattern":"psql .*prod|DATABASE_URL=.*prod"}}
{"id":"keep-migrations","tier":"hard","text":"Never edit existing migrations.",
 "check":{"type":"deny_path","pattern":"(^|/)migrations/"}}
{"id":"research-depth","tier":"process","text":"Research tasks need at least 5 web searches.",
 "check":{"type":"min_calls","tool":"WebSearch","n":5}}
```
