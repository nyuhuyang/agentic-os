# Active Tasks

## P11 — 共享配置协议：Symphony/Elixir 兼容
**Status:** planned

让 Symphony（外部 Elixir/Phoenix LiveView 协调器）通过 agentic-os 的 `/api/capabilities` 接口动态发现可用 Agent 后端，并通过 `POST /run` 统一 dispatch。

### 关键交付
- `/api/capabilities` 的 `backends` 列表可供 Symphony 动态读取
- WORKFLOW.md 中的 `agent.backend` 修改后，Symphony 能感知到变化
- Symphony 通过 agentic-os `POST /run` dispatch，不直接调用 agent CLI
- Symphony 展示不可用的 Agent 后端时显示禁用状态（同前端 dashboard）

### 状态
- `/api/capabilities` 已返回 `backends` 列表 ✅（P10 已交付）
- WORKFLOW.md `agent.backend` 热同步 — 待定
- Symphony dispatch 适配 — 待定

详细计划见 `docs/exec-plans/active/p11-shared-config-protocol.md`

## P12 — 测试覆盖
**Status:** planned

为已模块化的组件添加单元测试，验证模块发现、能力检测、优雅降级逻辑。

## DeepSeek Shell Execution via MCP
**Status:** planned

Research: can deepseek exec mode get real shell tools via MCP? Blocked by option-2 workaround.
