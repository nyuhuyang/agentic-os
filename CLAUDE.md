# AI Workspace — Operating Contract

This is the top-level contract for `/AI_Workspace`. It governs the workspace as an **Agentic OS**: a four-layer system where Claude Code is the execution engine and Obsidian is the persistent memory layer.

## Architecture

```text
┌─────────────────────────────────────────────────────┐
│  Layer 4 · Interface    terminal → dashboard (TBD)  │
├─────────────────────────────────────────────────────┤
│  Layer 3 · Operations   runner · scheduler ·        │
│                         telemetry · permissions     │
├─────────────────────────────────────────────────────┤
│  Layer 2 · Capability   skills · scripts ·          │
│                         external connectors         │
├─────────────────────────────────────────────────────┤
│  Layer 1 · Memory       raw/ · wiki/ · outputs/     │
│                         (obsidian/knowledge_base/)  │
└─────────────────────────────────────────────────────┘
```

**Do not build the Interface layer before the Operations layer is stable.**

## Workspace Map

| Directory | Purpose |
| --- | --- |
| `obsidian/knowledge_base/` | Primary memory layer — see its own `CLAUDE.md` |
| `obsidian/knowledge_base/.codex/skills/` | Skill library (Capability layer) |
| `obsidian/knowledge_base/outputs/` | Persisted run artifacts and todo lists |
| `experiments/` | Throwaway explorations — nothing here is canonical |
| `prototypes/` | In-progress builds not yet promoted to tools |
| `tools/` | Promoted, stable utilities |
| `scripts/` | One-off scripts and automation helpers |
| `shared_libs/` | Shared Python/JS modules across projects |
| `scratch/` | Truly ephemeral — safe to delete anytime |

## Skill Stacks

Skills are organized by business domain. Each stack owns its skills, raw inputs, and wiki outputs.

| Stack | Domain | Status |
| --- | --- | --- |
| `research` | YouTube pipeline, NotebookLM, Firecrawl | active |
| `knowledge` | llm-wiki-ingest/query/lint/reflect/merge | active |
| `trading` | Market research, strategy codification | planned |
| `admin` | File org, scheduling, logging | planned |
| `publishing` | Content synthesis, output routing | planned |
| `automation` | Cron/launchd, remote workers, telemetry | planned |

Skill home: `obsidian/knowledge_base/.codex/skills/`

Each skill must have a `skill.yaml` manifest. Schema: `purpose`, `trigger`, `inputs`, `outputs`, `dependencies`, `failure_modes`, `evaluation`, `schedule_eligibility`, `execution_env` (`local_only` | `remote_ok` | `hybrid`).

## Core Rules

- `raw/` is human-owned and immutable (exception: single-tag `clippings` cleanup).
- `wiki/` is agent-maintained. Write in English. Trace every abstraction back to a source.
- Non-trivial outputs → `wiki/syntheses/` or `outputs/`. Never leave them only in chat.
- New skills require a `skill.yaml` manifest before use in production.
- Local automation = needs local files or local CLI. Remote automation = cloud-native, always-on.
- Terminal is primary interface for power users. Dashboard (when built) wraps only stable, high-value flows.

## Build Roadmap

Priority order from Gap Analysis (2026-04-23):

1. Skill registry — machine-readable index of all skills
2. Job runner — local queue + run logs + state + retry + cron/launchd
3. `local_only` / `remote_ok` / `hybrid` backfill across all skills
4. Telemetry — start/end time, success/failure, output path, quality score
5. Lightweight dashboard — core skills, recent runs, one-click triggers
6. Security gates — read/write separation, approval for destructive actions
7. Remote worker — if local runner proves the value first

Skill registry: `.codex/registry.json` / `.codex/registry.md` (generated; rebuild with `build_registry.py`)

Tracking: `obsidian/knowledge_base/outputs/chase-ai-agentic-os-gap-analysis-2026-04-23-todo.md`

## Sub-system Contracts

- Knowledge base (wiki ops): `obsidian/knowledge_base/CLAUDE.md`
- Skill creation standard: `obsidian/knowledge_base/.codex/skills/skill-creator/SKILL.md`

## Meta

This file governs workspace-level structure and principles. Operational procedures belong in skills. Sub-system rules belong in sub-system `CLAUDE.md` files. Only expand this file for rules that truly span the whole workspace.
