# AgenticOS

> Single-host web dashboard and CLI job runner for AI skill executions and token budget monitoring.

## Critical Token Budget Rule

Bug-fix scope: `runner/templates/index.html`, `runner/app.py`, `runner/linear_client.py` (Linear API only). Do **not** read `SPEC.md`, `ARCHITECTURE.md`, `CONTEXT.md`, `README.md`, `docs/**` unless explicitly requested. Workflow: read task → grep implementation files → open narrow line ranges → smallest patch → validate.

## Quick Start

```bash
.venv/bin/python3 runner/app.py                          # dashboard (port 8510)
.venv/bin/python3 runner/run_skill.py <skill> [--dry-run]  # CLI runner
.venv/bin/python3 runner/usage_reader.py --days 7        # token stats
launchctl kickstart -k gui/$(id -u)/com.agenticos.runner # restart managed dashboard
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
│   ├── agent_ids.py        # Canonical agent ids (claude, codex, dsh) + legacy aliases
│   ├── dsh_cli.py          # DeepSeek Harness (dsh) CLI: binary, version gate, key, NDJSON events
│   ├── deepseek_monitor.py # DeepSeek balance/spend monitor
│   ├── projects.py         # Project registry, per-ticket worktrees + seeds, verify harness, session readers (CLI: list|worktree|verify|cleanup)
│   ├── project_runs.py     # Project-bound dispatch: sandboxed argv, comment gate, run-event ring, post-run checks
│   ├── reset_gen.py        # Per-issue reset generation + per-issue tracker lock (DSH-30)
│   ├── state_io.py         # Locked JSON read-modify-write for shared state files
│   ├── core/               # Registry and feature flags
│   ├── modules/            # Modular backends and integrations (pty/ = server-owned terminal tabs)
│   ├── outputs/            # Runner logs and uploads
│   ├── scripts/            # Runner-internal utilities
│   └── templates/
│       └── index.html      # Jinja2 dashboard — all CSS/JS inline, no build step
├── outputs/                # Runtime state (created on first run)
├── state/                  # Operational JSON/JSONL truth — do not edit manually
├── projects.yaml           # Real project registry — gitignored (schema: projects.example.yaml)
├── scripts/                # Utility scripts (roadmap render, state sync, migration, etc.)
├── docs/
│   ├── generated/          # Auto-generated — do not edit manually
│   ├── design-docs/        # Design decisions and core beliefs
│   ├── adr/                # Architecture decision records
│   ├── exec-plans/
│   │   ├── active/         # Work in progress
│   │   └── completed/      # Archived plans
│   ├── references/         # LLM-readable reference materials
│   ├── context-maintenance.md  # Cross-session continuity — WIP, decisions, next action
│   └── PLANS.md            # Roadmap and prioritized backlog
├── SPEC.md                 # Authoritative FR/NFR/AC spec
├── WORKFLOW.md             # Development workflow
├── CLAUDE.md               # Agent operating contract
└── graphify-out/           # Architecture knowledge graph (read-only)
```

## Architecture

→ [`ARCHITECTURE.md`](ARCHITECTURE.md) — component map, data flow, storage invariants

- Flask + SocketIO dispatches agents; `usage_reader.py` aggregates budgets; rebuild the dashboard-read-only registry externally
- Linear polling + dispatch are built in (`runner/modules/linear/`); no Symphony or `symphony-ts` dependency. The dashboard is `runner/templates/index.html` only
- A ticket labelled `project:<key>` runs in `~/.agentic-os/worktrees/<key>/<id>` on `agent/<id>`; confidential projects run sandboxed and get template-only tracker comments. Every browser request carries the per-process `X-AgenticOS-Token` (plan `2026-10-13-multi-project-dispatch`)

## Docs Index

| Path | Purpose |
|------|---------|
| `SPEC.md` | Authoritative FR/NFR/AC — check before implementing any feature |
| `docs/design-docs/` | Design decisions and core beliefs |
| `docs/adr/` | Architecture decision records |
| `state/roadmap.json` | Authoritative roadmap — edit this, not the generated files |
| `docs/exec-plans/active/` | Full exec plans for active work |
| `docs/exec-plans/completed/` | Archived plans |
| `docs/references/` | Run log format, registry schema, data sources |
| `docs/PLANS.md` | Roadmap summary |
| `docs/context-maintenance.md` | Cross-session continuity — WIP, decisions, next action |

## Conventions

- No external build step — source in `runner/`; submodules in `runner/core/` and `runner/modules/`
- Run status closed set: `running`, `success`, `failed`, `error`, `timeout`, `sent`, `archived`
- Only skills with `schedule_eligible: true` + non-empty `entrypoint` can run via `run_skill.py`
- `outputs/` created on first run; never pre-create in code
- PTY uploads must pass through `werkzeug.secure_filename` (NFR-08)
- Server binds `127.0.0.1` only — never expose externally without `--host`

## Definition of Done

- [ ] `.venv/bin/python3 -m py_compile runner/*.py` and affected behavior checks pass
- [ ] `docs/context-maintenance.md` records validation and next action

## Agent Workflow

1. Read this file first.
2. Read `docs/context-maintenance.md` and `docs/generated/ACTIVE_TASKS.md`; open the relevant active plan.
3. Read `SPEC.md` before touching any FR/NFR/AC — it is the source of truth.
4. Read only task-relevant files, then run Definition of Done checks; there is no formal test suite.
5. Escalate to human for anything below.

## Graphify Usage

- Read `graphify-out/GRAPH_REPORT.md` before architecture questions
- Cross-module queries: use `graphify query/path/explain` — not grep
- After modifying code: run `graphify update .` (AST-only, no API cost)
- CLI: `pip install graphifyy` (double y); command is `graphify`; `/graphify` is the Claude Code skill

## CodeGraph

- Symbol/caller/blast-radius lookups: `codegraph_explore` MCP tool (or `codegraph explore "<symbols>"`) before grep/Read
- A fresh ticket worktree gets a snapshot of the main checkout's index automatically (`_copy_codegraph`); no `.codegraph/` = skip CodeGraph

## DeepSeek Delegation

Delegate reviews, metric analysis, strategy comparisons, second opinions, and docs synthesis with `runner/scripts/ask_deepseek.py`.
Key: env or `~/.deepseek/config.toml`. Only the direct-API mode works: `--agentic` needs the removed Rust `deepseek` CLI.

Dashboard agents are `claude`, `codex` and `dsh` (labelled "DeepSeek", runs `dsh --profile headless --json`). Old ids `deepseek`, `deepseek-tui` and `aider` are aliased to `dsh` on read; stored records are never rewritten. `dsh` is rejected for confidential projects (its sandbox leaves shell network open).
Do not delegate visual/chart/browser/clipboard tasks.

## Escalation — Do Not Proceed Without Human Confirmation

- Changing the run status closed set (breaks log compatibility)
- Mutating or truncating `run_log.jsonl` in place
- Binding server to `0.0.0.0` or any non-localhost address
- Adding auth, multi-user, or remote-worker scope (explicitly out of scope)
- Deleting files, branches, or outputs
- Pushing to main/master directly
- Schema or API contract changes
- Dependency major-version upgrades
