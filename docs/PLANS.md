# Plans — AgenticOS Roadmap

> **Human-readable summary.** Authoritative source: `state/roadmap.json`. To regenerate `docs/`:
>
>     python3 scripts/render_roadmap_md.py

## ✅ Completed

- [x] **P1–P5**: Core board features — cancel, retry, stall detection, tokens, Linear sync
- [x] **P6**: Structured Operational Memory — `state/` JSON source of truth, `render_roadmap_md.py` fixed, Graphify integrated
- [x] **P7**: Aider / DeepSeek third backend — `runner/app.py` + UI 3-way toggle + telemetry + ADR
- [x] **P8**: Migrate Aider → DeepSeek TUI — installed, validated on real task, aider config retired

## 🔄 Active

### P10 — Modular Architecture: 可插拔模块系统

**Goal:** 将当前单体架构拆分为独立、可插拔的模块。Agent 后端、集成（Linear、STT）、前端组件均可按需安装/启用，缺少依赖时优雅降级。

**5 个阶段：**
1. **Core 拆分** — `config.py`、`registry.py`、`state.py`、`pty.py`
2. **Agent 模块化** — `agents/claude.py`、`agents/codex.py`、`agents/aider.py` + 注册表
3. **集成模块化** — `integrations/linear.py`、`integrations/stt.py` + fallback 链
4. **前端模块化** — 模板拆分 + 基于 `config.modules` 动态渲染
5. **安装系统** — `scripts/setup.py` + `agentic-os.toml`

**Status:** Phase 1 待开始

→ [`docs/exec-plans/active/p10-modular-architecture.md`](exec-plans/active/p10-modular-architecture.md)

### P6 — Structured Operational Memory

**Status:** active — 基础架构已完成，`render_roadmap_md.py` bugs 已修复

### P9 — Research: DeepSeek Shell via MCP

**Status:** planned — 调研 DeepSeek TUI exec 模式下能否通过 MCP 获取真实 shell 工具

→ [`docs/exec-plans/active/p9-deepseek-shell-via-mcp.md`](exec-plans/active/p9-deepseek-shell-via-mcp.md)

---

## 📋 Backlog

- **Reduce agent token waste** from repo-wide exploration
- **Controlled autonomy / layered permissions**
