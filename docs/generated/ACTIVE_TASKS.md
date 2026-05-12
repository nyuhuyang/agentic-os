# Active Tasks

## P11 — Agent 后端统一 Dispatch + DeepSeek 全功能集成
**Status:** active

在 P10 模块化基础上，完成 DeepSeek 后端全功能集成（dispatch/polling 移入模块）和 Symphony 共享配置协议（config_changed WebSocket 事件）。

### Phase 1 — DeepSeek dispatch 集成
- [ ] _execute_deepseek_commands() → DeepSeekModule.execute_commands()
- [ ] _deepseek_agent_dispatch() → DeepSeekModule.dispatch()
- [ ] _deepseek_polling_loop → DeepSeekModule.start_background()

### Phase 2 — Symphony 共享配置协议
- [ ] PATCH /api/config 触发 config_changed WS 事件
- [ ] /api/capabilities 增加 selected 字段

### Phase 3 — 消除 app.py 硬编码 agent 启动
- [ ] 删除 main() 中 _HAS_DEEPSEEK_MONITOR 条件线程

详细计划见 `docs/exec-plans/active/p11-agent-dispatch-deepseek.md`

## P12 — 测试覆盖
**Status:** planned

为已模块化的组件添加单元测试，验证模块发现、能力检测、优雅降级逻辑。

## DeepSeek Shell Execution via MCP
**Status:** planned

Research: can deepseek exec mode get real shell tools via MCP? Blocked by option-2 workaround.
