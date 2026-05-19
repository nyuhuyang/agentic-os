# AgenticOS

> Single-host web dashboard and CLI job runner for AI skill executions and token budget monitoring.

## Critical Token Budget Rule

Bug-fix scope: `runner/templates/index.html`, `runner/app.py`, `runner/linear_client.py` (Linear API only). Do **not** read `SPEC.md`, `ARCHITECTURE.md`, `CONTEXT.md`, `README.md`, `docs/**` unless explicitly requested. Workflow: read task → grep implementation files → open narrow line ranges → smallest patch → validate.

## Quick Start

```bash
.venv/bin/python3 runner/app.py                          # dashboard (port 8510)
.venv/bin/python3 runner/run_skill.py <skill> [--dry-run]  # CLI runner
.venv/bin/python3 runner/usage_reader.py --days 7        # token stats
```

## Repository Map

```
agentic-os/
├── runner/
│   ├── app.py              # Flask + SocketIO server — HTTP API, SSE, PTY, agent dispatch
│   ├── run_skill.py        # CLI job runner — locking, logging, retry
│   ├── usage_reader.py     # Token usage aggregator (Claude JSONL + Codex SQLite)
│   ├── dashboard.py        # Rich TUI — read-only CLI view
│   ├── linear_client.py    # Linear API client
│   ├── deepseek_agent.py   # DeepSeek agent dispatcher
│   ├── deepseek_monitor.py # DeepSeek process monitor
│   ├── core/               # Module registry, feature flags
│   ├── modules/            # Linear and other connectors
│   └── templates/
│       └── index.html      # Jinja2 dashboard — all CSS/JS inline, no build step
├── outputs/                # Runtime state (created on first run)
│   ├── run_log.jsonl       # Append-only run history
│   ├── job_state.json      # Last-known state per skill (atomic rewrite)
│   └── uploads/            # PTY file drop target
├── state/                  # Operational source of truth (JSON/JSONL — do not edit manually)
│   ├── roadmap.json        # Structured roadmap — edit here, then run render_roadmap_md.py
│   ├── task_state.json     # Per-run task state (written by app.py)
│   └── events.jsonl        # Append-only event log
├── scripts/
│   └── render_roadmap_md.py  # Generates docs/generated/ + docs/exec-plans/ROADMAP.md
├── docs/
│   ├── generated/          # Auto-generated — do not edit manually
│   │   ├── ACTIVE_TASKS.md
│   │   └── COMPLETED.md
│   ├── design-docs/        # Design decisions and core beliefs
│   ├── exec-plans/
│   │   ├── active/         # Work in progress
│   │   └── completed/      # Archived plans
│   ├── references/         # LLM-readable reference materials
│   └── PLANS.md            # Roadmap and prioritized backlog
├── SPEC.md                 # Authoritative FR/NFR/AC spec
├── WORKFLOW.md             # Development workflow
├── CLAUDE.md               # Agent operating contract
└── graphify-out/           # Architecture knowledge graph (read-only)
```

## Architecture

→ [`ARCHITECTURE.md`](ARCHITECTURE.md) — component map, data flow, storage invariants

- Flask + SocketIO server dispatches skills to `claude -p` or `codex exec` based on agent selection
- `usage_reader.py` aggregates Claude JSONL + Codex SQLite → 5-hour and 7-day rolling budget windows
- Skill registry (`registry.json`) is read-only from dashboard; rebuild externally with `build_registry.py`

## Docs Index

| Path | Purpose |
|------|---------|
| `SPEC.md` | Authoritative FR/NFR/AC — check before implementing any feature |
| `docs/design-docs/` | Design decisions and core beliefs |
| `state/roadmap.json` | Authoritative roadmap — edit this, not the generated files |
| `docs/generated/ACTIVE_TASKS.md` | Quick summary of active work (generated) |
| `docs/exec-plans/active/` | Full exec plans for active work |
| `docs/exec-plans/completed/` | Archived plans |
| `docs/references/` | Run log format, registry schema, data sources |
| `docs/PLANS.md` | Roadmap summary |

## Conventions

- No external build step — source in `runner/`; submodules in `runner/core/` and `runner/modules/`
- Run status closed set: `running`, `success`, `failed`, `error`, `timeout`, `sent`, `archived`
- Only skills with `schedule_eligible: true` + non-empty `entrypoint` can run via `run_skill.py`
- `outputs/` created on first run; never pre-create in code
- PTY uploads must pass through `werkzeug.secure_filename` (NFR-08)
- Server binds `127.0.0.1` only — never expose externally without `--host`

## Agent Workflow

1. Read this file first.
2. Read `docs/generated/ACTIVE_TASKS.md`; open relevant `docs/exec-plans/active/` plan for detail.
3. Read `SPEC.md` before touching any FR/NFR/AC — it is the source of truth.
4. No test suite — verify against AC in `SPEC.md` before declaring done.
5. Only read files directly relevant to task; no repo-wide scans. Historical plans in `docs/exec-plans/completed/` — do not read unless required.
6. Escalate to human for anything below.

## Graphify Usage

Knowledge graph lives at `graphify-out/`. Read it before answering architecture questions.

- Before architecture questions: read `graphify-out/GRAPH_REPORT.md` for god nodes and community structure
- Cross-module queries: use `graphify query/path/explain` — not grep
- After modifying code: run `graphify update .` (AST-only, no API cost)
- CLI: `pip install graphifyy` (double y); command is `graphify`; `/graphify` is the Claude Code skill

## Escalation — Do Not Proceed Without Human Confirmation

- Changing the run status closed set (breaks log compatibility)
- Mutating or truncating `run_log.jsonl` in place
- Binding server to `0.0.0.0` or any non-localhost address
- Adding auth, multi-user, or remote-worker scope (explicitly out of scope)
- Deleting files, branches, or outputs
- Pushing to main/master directly
- Schema or API contract changes
- Dependency major-version upgrades
