# Active Tasks

## P10 — 模块化架构：可插拔模块系统
**Status:** active — Phase 1 done

核心模块注册表基础设施已就绪。接下来：Linear 模块化、Agent 后端模块化、STT 多后端、前端动态渲染、拆分 app.py。

### Phase 1 完成项
- `runner/core/module_registry.py` — ModuleRegistry + AgenticModule 基类
- `runner/core/features.py` — 功能检测工具（env var、包、可执行文件）
- `runner/modules/` — 五个模块目录（backends、linear、stt、pty + modules/__init__.py）
- `runner/app.py` — 集成 ModuleRegistry，添加 `/api/capabilities` 端点

详细计划见 `docs/exec-plans/active/p10-modular-architecture.md`

## Structured Operational Memory + Architecture Index
**Status:** active

render_roadmap_md.py bugs fixed; remaining: initialState bootstrap, verify generated docs.

## DeepSeek Shell Execution via MCP
**Status:** planned

Research: can deepseek exec mode get real shell tools via MCP? Blocked by option-2 workaround.
