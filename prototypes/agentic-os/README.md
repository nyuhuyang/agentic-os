# AgenticOS

> Single-host web dashboard and CLI job runner for AI skill executions and token budget monitoring.

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

## What It Does

AgenticOS wraps Claude Code and Codex in a lightweight operational layer:

- **Dashboard** — Flask + SocketIO web UI showing active runs, token budget windows (5-hour and 7-day rolling), and skill status
- **Job runner** — CLI dispatcher with file locking, structured logging, and retry for schedule-eligible skills
- **Token monitor** — Aggregates Claude JSONL session logs and Codex SQLite into unified budget views
- **Skill registry** — Machine-readable index of all available AI skills with metadata (schedule eligibility, agent compatibility, entrypoints)

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
├── ARCHITECTURE.md         # Component map, data flow, storage invariants
└── docs/
    ├── design-docs/        # Design decisions and core beliefs
    ├── exec-plans/         # Harness Engineering-style execution plans
    └── references/         # LLM-readable reference materials
```

## Agent Backends

Two backends, user-selectable from the dashboard:

| Agent | Dispatch | Token source |
|-------|----------|-------------|
| `claude` | `claude -p <prompt>` | JSONL session logs in `~/.claude/` |
| `codex` | `codex exec <prompt>` | SQLite DB in Codex data dir |

## Symphony Integration

For issue-driven agentic workflows, this project pairs with a modified fork of OpenAI's Symphony orchestrator that supports both Codex and Claude Code as agent backends:

**[nyuhuyang/symphony](https://github.com/nyuhuyang/symphony)** — adds `agent.backend: claude | codex` hot-swap to Symphony, wired through the LiveView dashboard toggle. Switch backends at runtime by editing `WORKFLOW.md` or clicking the dashboard button — no restart required.

## Inspiration and Prior Art

This project was built on ideas from three sources:

- **[Chase AI — "Claude Code Agentic OS = UNSTOPPABLE"](https://www.youtube.com/watch?v=pfPi04pIfaw&t=82s)** — the original framing of Claude Code as an operating system layer for agentic workflows. Directly inspired the architecture of this project.

- **[OpenAI — Open-source Codex Orchestration: Symphony](https://openai.com/index/open-source-codex-orchestration-symphony/)** — production-grade issue-driven orchestration pattern: poll Linear, isolate per-issue workspaces, run coding agents. The execution model AgenticOS extends.

- **[Harness Engineering](https://openai.com/index/harness-engineering/)** — operational discipline for running coding agents at scale: exec plans as repo artifacts, structured logging, skill registries, run state persistence. The planning and logging conventions in `docs/exec-plans/` and `outputs/` follow this methodology directly.
