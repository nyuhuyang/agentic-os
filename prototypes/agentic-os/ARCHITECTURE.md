# AgenticOS Architecture

Single-host web dashboard and CLI job runner for AI skill executions and token budget monitoring.

## Component Map

```
runner/
├── app.py            # Flask + SocketIO server — HTTP API, SSE stream, PTY, agent dispatch
├── run_skill.py      # CLI job runner — locking, logging, retry, schedule-eligible skills
├── usage_reader.py   # Token usage aggregator — Claude JSONL + Codex SQLite → budget windows
├── dashboard.py      # Rich TUI — read-only CLI view of run state
└── templates/
    └── index.html    # Jinja2 dashboard — all CSS/JS inline, no build step

outputs/              # Runtime state (created on first run)
├── run_log.jsonl     # Append-only run history — never mutate; last record per run_id wins
├── job_state.json    # Last-known state per skill — atomically rewritten each completion
└── uploads/          # PTY drag-drop file staging
```

## Data Flow

```
Skill Registry (registry.json)
        │
        ▼
Dashboard (index.html)         ← agent selection, budget display
        │
  click skill card
        │
        ├─ schedule-eligible skill ─→ run_skill.py ─→ run_log.jsonl + job_state.json
        │
        └─ AI-only skill ──────────→ claude -p / codex exec ─→ run_log.jsonl
```

## Storage Invariants

| File | Rule |
|------|------|
| `run_log.jsonl` | Append-only. Never mutate or truncate lines. Last record per `run_id` wins. |
| `job_state.json` | Atomically rewritten (write-then-rename) on every run completion. |
| `outputs/` | Created on first run if absent. Never pre-create in code. |

## Agent Backends

Two agents: `claude` and `codex`. Active agent is user-selected in the dashboard.

| Agent | Dispatch | Token tracking |
|-------|----------|---------------|
| `claude` | `claude -p <prompt>` | JSONL session logs in `~/.claude/` |
| `codex` | `codex exec <prompt>` | SQLite DB in Codex data dir |

`usage_reader.py` reads both sources to compute budget windows (5-hour rolling, 7-day rolling).

## Security Constraints (NFR)

- Server binds `127.0.0.1` only. Never expose externally without explicit `--host`.
- PTY file uploads must go through `werkzeug.secure_filename`.
- No auth, no multi-user, no remote-worker scope — all explicitly out of scope.

## Key Invariants for Agents

- Run status closed set: `running`, `success`, `failed`, `error`, `timeout`, `sent`, `archived`. Never extend without human confirmation.
- Skills are dispatched, never authored or edited through the dashboard. Registry is read-only from here; rebuild externally with `build_registry.py`.
- Only skills with `schedule_eligible: true` AND a non-empty `entrypoint` can run via `run_skill.py`.
- `POST /run` rejects dispatch if selected agent not in skill's `agents` field.
