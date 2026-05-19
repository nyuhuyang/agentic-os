# Plans — AgenticOS Roadmap

> **Human-readable summary.** Authoritative source: `state/roadmap.json`. To regenerate `docs/`:
>
>     python3 scripts/render_roadmap_md.py

## ✅ Completed

- [x] **P1–P5**: Core board features — cancel, retry, stall detection, tokens, Linear sync
- [x] **P6**: Structured Operational Memory — `state/` JSON source of truth, `render_roadmap_md.py` fixed, Graphify integrated
- [x] **P7**: Aider / DeepSeek third backend — `runner/app.py` + UI 3-way toggle + telemetry + ADR
- [x] **P8**: Migrate Aider → DeepSeek TUI — installed, validated on real task, aider config retired
- [x] **P11**: Agent Dispatch DeepSeek — per-issue agent override in Job Board
- [x] **P12**: Test Coverage — runner core + linear_client smoke tests
- [x] **P13**: DeepSeek TUI Cleanup — config, prompts, MCP alignment
- [x] **P14**: Four-Agent Selection — Claude/Codex/DeepSeek/DeepSeek TUI parity
- [x] **P16**: Optimistic UI — instant feedback on dispatch/cancel/comment
- [x] **P17**: Fix Engine Stability — symphony-ts refactor + reliable task_shell dispatch
- [x] **P18**: Dashboard Skeleton — Preact + dnd-kit basic kanban
- [x] **P19**: Dashboard v2 — React 18 + vibe-kanban + 全列看板

## 🔄 Active

### P15 — DeepSeek TUI Exec Tools: stable agent shell dispatch

**Status:** active — symphony-ts engine refactor complete (P17). Agent dispatch via `task_shell_start`/`wait` stable. Next: end-to-end validation with deepseek backend.

→ [`docs/exec-plans/active/p15-deepseek-tui-exec-tools.md`](exec-plans/active/p15-deepseek-tui-exec-tools.md)

### P10 — Modular Architecture: 可插拔模块系统

**Status:** active — 核心拆分 + Agent/集成模块化 + 前端动态渲染 + 安装系统。Phase 1 待开始。

→ [`docs/exec-plans/active/p10-modular-architecture.md`](exec-plans/active/p10-modular-architecture.md)

### P6 — Structured Operational Memory

**Status:** active — `render_roadmap_md.py` bugs fixed. Remaining: initialState bootstrap, verify generated docs.

### P9 — DeepSeek Shell via MCP

**Status:** planned — 调研 DeepSeek TUI exec 模式下能否通过 MCP 获取真实 shell 工具。

→ [`docs/exec-plans/active/p9-deepseek-shell-via-mcp.md`](exec-plans/active/p9-deepseek-shell-via-mcp.md)

---

## 📋 Backlog

- **Reduce agent token waste** from repo-wide exploration
- **Controlled autonomy / layered permissions**
- **Lexical rich text** — full toolbar (Bold/Italic/Code/List)
- **Linear GraphQL proxy** — direct frontend-to-Linear fallback (Vite proxy configured)
- **Agent log** — wire real engine session data into DetailPanel
- **HistoryPanel** — date range picker + CSV export
