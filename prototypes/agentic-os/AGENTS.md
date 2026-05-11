# AgenticOS

> Single-host web dashboard and CLI job runner for AI skill executions and token budget monitoring.

## Critical Token Budget Rule

For small bug-fix tasks, do not read project-level documents by default.

Forbidden unless explicitly requested:

- `SPEC.md`
- `TODO.md`
- `ARCHITECTURE.md`
- `CONTEXT.md`
- `README.md`
- `docs/**`
- `outputs/**`
- historical logs
- long markdown files

Small bug-fix workflow:

1. Read only the user's task.
2. Search only the most likely implementation files.
3. Open only narrow line ranges around matched symbols.
4. Make the smallest relevant patch.
5. Validate with targeted checks.

For Job Board UI tasks, default scope is:

- `runner/templates/index.html`
- `runner/app.py`
- `runner/linear_client.py` only if Linear API behavior is involved

Do not read `SPEC.md` or `TODO.md` for UI polish, button, column, count, modal, card, or recycle-bin tasks unless the user explicitly asks for spec or roadmap work.

## Quick Start

```bash
# Web dashboard (port 8510)
.venv/bin/python3 runner/app.py

# CLI job runner
.venv/bin/python3 runner/run_skill.py --list
.venv/bin/python3 runner/run_skill.py <skill>
.venv/bin/python3 runner/run_skill.py <skill> --dry-run

# Token usage stats
.venv/bin/python3 runner/usage_reader.py --days 7
```

## Repository Map

```
agentic-os/
├── runner/
│   ├── app.py              # Flask + SocketIO web dashboard
│   ├── dashboard.py        # Rich TUI (read-only CLI view)
│   ├── run_skill.py        # CLI job runner (locking, logging, retry)
│   ├── usage_reader.py     # Token usage aggregator (Claude JSONL + Codex SQLite)
│   └── templates/
│       └── index.html      # Jinja2 template — all CSS/JS inline
├── outputs/
│   ├── run_log.jsonl       # Append-only run history
│   ├── job_state.json      # Last-known state per skill (atomic rewrite)
│   └── uploads/            # PTY file drop target
├── SPEC.md                 # Full FR/NFR/AC spec (source of truth)
├── TODO.md                 # Prioritized backlog (P0–P4)
├── CLAUDE.md               # Agent operating contract
└── docs/
    ├── design-docs/        # Design decisions and core beliefs
    ├── exec-plans/
    │   ├── active/         # Work in progress
    │   └── completed/      # Archived plans
    ├── references/         # LLM-readable reference materials
    └── PLANS.md            # Roadmap and prioritized backlog
```

## Architecture

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for the full component map, data flow, and storage invariants.

Key invariants (never violate without human confirmation):

- `run_log.jsonl` is **append-only**. Never mutate lines. Last record per `run_id` wins.
- `job_state.json` is **atomically rewritten** on every run completion.
- Only skills with `schedule_eligible: true` + `entrypoint` can run via `run_skill.py`.
- Server binds to `127.0.0.1` by default (NFR-01). Never expose externally without `--host`.

## Docs Index

| Path | Purpose |
|------|---------|
| `SPEC.md` | Authoritative FR/NFR/AC spec — check here before implementing |
| `TODO.md` | P0–P4 backlog with acceptance criteria |
| `docs/design-docs/` | Design decisions |
| `docs/exec-plans/active/` | Current work in progress |
| `docs/exec-plans/completed/` | Archived plans |
| `docs/references/` | Run log format, registry schema, data sources |
| `docs/PLANS.md` | Roadmap summary |

## Conventions

- No packages, no build step — all source is flat files in `runner/`.
- Run status closed set: `running`, `success`, `failed`, `error`, `timeout`, `sent`, `archived`.
- Skill dispatch routing: schedule-eligible → `run_skill.py`; AI-only → `claude -p` or `codex exec`.
- `outputs/` is created on first run if absent; never pre-create in code.
- Filenames uploaded via PTY drag-drop must go through `werkzeug.secure_filename` (NFR-08).
- Skill registry is read-only from the dashboard. Rebuild with `build_registry.py` externally.

## Agent Workflow

1. Read this file first.
2. Check `docs/exec-plans/active/` for current task context.
3. Read `SPEC.md` before touching any FR/NFR/AC — it is the source of truth.
4. Check `TODO.md` for the active P0 item before starting new work.
5. No test suite yet — manually verify against AC in SPEC.md before declaring done.
6. Escalate to human for anything in the section below.

## Escalation — Do Not Proceed Without Human Confirmation

- Changing the run status closed set (breaks log compatibility)
- Mutating or truncating `run_log.jsonl` in place
- Binding the server to `0.0.0.0` or any non-localhost address
- Adding auth, multi-user, or remote-worker scope (explicitly out of scope)
- Deleting files, branches, or outputs
- Pushing to main/master directly
