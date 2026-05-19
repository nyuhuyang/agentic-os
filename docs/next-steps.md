# Next Steps

> Last updated: 2026-05-16 · Context: P19 Dashboard v2 just completed

## Immediate (Active Work)

### P15 — DeepSeek TUI Exec Tools
End-to-end validation with deepseek backend. symphony-ts engine already refactored (P17), dispatch via `task_shell_start`/`wait` is stable.
→ [`docs/exec-plans/active/p15-deepseek-tui-exec-tools.md`](exec-plans/active/p15-deepseek-tui-exec-tools.md)

### P10 — Modular Architecture
Split monolith into pluggable modules. Phase 1: Core split (`config.py`, `registry.py`, `state.py`, `pty.py`).
→ [`docs/exec-plans/active/p10-modular-architecture.md`](exec-plans/active/p10-modular-architecture.md)

## Ready to Pick Up (Backlog)

| Priority | Item | Notes |
|---|---|---|
| P1 | **Agent log — wire real data** | DetailPanel AgentLog tab shows "No log entries yet". Connect to engine session log endpoint via `/api/v1/<issue-identifier>`. |
| P2 | **Lexical toolbar** | RichEditor has basic setup. Add Bold/Italic/Code/List toolbar buttons using Lexical `$createParagraphNode`/`FORMAT_TEXT_COMMAND`. |
| P3 | **HistoryPanel — date range** | Add date range picker + export to CSV. Backend filter parameter needed for `/api/linear/issues`. |
| P4 | **STT — OpenAI transcribe backend** | Current STT uses browser Web Speech API (good for Chinese). Add OpenAI whisper backend support from engine capabilities. |
| P5 | **Full drag-drop state sync** | Drag to Done → `PATCH /api/linear/issues/<id>` works. Extend to all column transitions. |

## Upcoming (Not Yet Scoped)

- **Reduce agent token waste** — avoid repo-wide file scanning on small tasks
- **Controlled autonomy** — layered permissions per agent/operation
- **Dashboard v3** — if P19 proves React 18 is the right path, double down: add GraphQL subscription, agent timeline, diff viewer
