# Next Steps

> Last updated: 2026-05-20 · Context: P20 Dashboard fixes are the current active implementation track

## Immediate (Active Work)

### P20 — Dashboard Fixes & Token Panel Redesign
Finish the dashboard follow-through work: verify nullable Linear timestamps, run `pnpm build`, complete run-history wiring from Flask, and visually check the card/header changes.
→ [`docs/exec-plans/active/p20-dashboard.md`](exec-plans/active/p20-dashboard.md)

## Deferred

### P15 — DeepSeek TUI Exec Tools
Plan remains in `docs/exec-plans/active/`, but its own status is `Deferred`. Do not treat it as the next implementation target until it is explicitly reactivated.
→ [`docs/exec-plans/active/p15-deepseek-tui-exec-tools.md`](exec-plans/active/p15-deepseek-tui-exec-tools.md)

## Recently Completed

- **P10 — Modular Architecture** → [`docs/exec-plans/completed/p10-modular-architecture.md`](exec-plans/completed/p10-modular-architecture.md)
- **P6 — Structured Operational Memory** → [`docs/exec-plans/completed/p6-structured-operational-memory.md`](exec-plans/completed/p6-structured-operational-memory.md)
- **P9 — DeepSeek Shell via MCP** → [`docs/exec-plans/completed/p9-deepseek-shell-via-mcp.md`](exec-plans/completed/p9-deepseek-shell-via-mcp.md)
- **P19 — Dashboard v2** → [`docs/exec-plans/completed/p19-dashboard-v2.md`](exec-plans/completed/p19-dashboard-v2.md)

## Ready to Pick Up (Backlog)

| Priority | Item | Notes |
|---|---|---|
| P1 | **Agent log — wire real engine session data** | Connect DetailPanel AgentLog to the engine session/run history source. |
| P2 | **Lexical toolbar** | RichEditor has basic setup. Add Bold/Italic/Code/List toolbar buttons. |
| P3 | **HistoryPanel — date range** | Add date range picker and CSV export. |
| P4 | **STT — OpenAI transcribe backend** | Current STT uses browser Web Speech API. Add OpenAI transcription backend support when capability plumbing is ready. |
| P5 | **Controlled autonomy** | Layered permissions per agent/operation. |

## Source Drift To Resolve

- `state/roadmap.json`, `docs/PLANS.md`, and `docs/generated/ACTIVE_TASKS.md` still describe older active work. Regenerate or update them after deciding whether P20 should become the roadmap source of truth.
