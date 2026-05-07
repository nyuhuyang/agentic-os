# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`agentic-os` is the runner/dashboard prototype for AI Workspace. It wraps skill execution with logging, state tracking, and a web UI. It is **not** the knowledge base — it reads from it.

The knowledge base lives at `../../obsidian/knowledge_base/` (override with `KNOWLEDGE_BASE` env var). The skill registry is at `AI_Workspace/.codex/registry.json`.

## Commands

```bash
# Start web dashboard (default port 8510)
.venv/bin/python3 runner/app.py
.venv/bin/python3 runner/app.py --port 8510 --debug
KNOWLEDGE_BASE=/path/to/kb .venv/bin/python3 runner/app.py

# Terminal dashboard (Rich TUI)
# Must be run from knowledge_base root
.venv/bin/python3 .codex/runner/dashboard.py
.venv/bin/python3 .codex/runner/dashboard.py --watch        # auto-refresh
.venv/bin/python3 .codex/runner/dashboard.py --skill <name> # detail view

# Run a schedulable skill (from knowledge_base root)
.venv/bin/python3 .codex/runner/run_skill.py <skill>
.venv/bin/python3 .codex/runner/run_skill.py --list
.venv/bin/python3 .codex/runner/run_skill.py --status
.venv/bin/python3 .codex/runner/run_skill.py <skill> --dry-run
.venv/bin/python3 .codex/runner/run_skill.py <skill> --headless  # cron/launchd

# Usage stats
.venv/bin/python3 runner/usage_reader.py --days 7
.venv/bin/python3 runner/usage_reader.py --json
```

## Architecture

All source is in `runner/`. No packages, no build step.

| File | Role |
|------|------|
| `app.py` | Flask + SocketIO web dashboard. Single process. |
| `dashboard.py` | Rich TUI — read-only CLI view of same data. |
| `run_skill.py` | CLI job runner. Wraps skill entrypoints with locking, logging, retry. |
| `usage_reader.py` | Token usage aggregator for Claude (JSONL) and Codex (SQLite). |
| `templates/index.html` | Jinja2 template — all CSS/JS inline, no build tooling. |

### Data flow

`app.py` routes:
- `GET /` — renders dashboard from registry + run log
- `POST /run` — dispatches skill; two paths:
  1. `schedule_eligible` + `entrypoint` → runs via `run_skill.py`
  2. AI-only skill or free prompt → spawns `claude -p` or `codex exec`
- `GET /stream` — SSE streaming variant of `/run`
- `PATCH /api/runs/<id>/status` — archive/restore runs (append to JSONL)

SocketIO events: `run_state_change`, `run_logged`, `pty_output`/`pty_input` (embedded xterm.js terminal).

### Run log

`outputs/run_log.jsonl` is **append-only**. Deduplication by `run_id` — the latest record for a given `run_id` wins. Status updates (archive, restore) append new records rather than mutating old ones. `outputs/job_state.json` stores the last-known state per skill and is atomically rewritten on each run.

### Usage data sources

- **Claude**: `~/.claude/projects/**/*.jsonl` — scanned on every request
- **Codex**: `~/.codex/state_5.sqlite` — `threads` table
- **Live rate limits** (Claude): `AI_Workspace/.claude/rate-limits-live.json` — written by a statusline hook; used if captured within last 12h
- **Live rate limits** (Codex): `~/.codex/sessions/**/*.jsonl` — scanned for `token_count` events
- **Budget overrides**: `~/.claude/budget.json` — per-agent `window_5h`, `window_7d`, `daily_runs_max`, `weekly_reset`

### Skill eligibility

Only skills with `schedule_eligible: true` and an `entrypoint` in the registry can be run via `run_skill.py`. Skills without an entrypoint are AI-only (dispatched to `claude -p`). The `agents` field in the registry controls which agent (claude/codex) a skill supports.
