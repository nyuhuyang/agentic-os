# P11 — Agent 后端统一 Dispatch + DeepSeek 全功能集成

**状态:** Active  
**优先级:** P1  
**开始:** 2026-05-12  
**负责人:** AgenticOS

---

## 目标

在 P10 模块化基础上，完成两件事：

1. **DeepSeek 全功能集成** — DeepSeekModule 已能检测 API Key，但实际 dispatch 仍走 `app.py` 中的 `_deepseek_agent_dispatch()`。需要让 DeepSeek 像 Claude/Codex 一样，dispatch、token 统计、错误处理完全通过模块系统。

2. **Symphony 共享配置协议** — `/api/capabilities` 已返回 `backends` 列表，但 Elixir 端的 Symphony 协调器尚未消费这个 API。需要定义并实现 agentic-os ↔ Symphony 之间的配置共享契约。

---

## 为什么现在做

| 问题 | 说明 |
|------|------|
| DeepSeek dispatch 仍在 app.py | `_deepseek_agent_dispatch()` 和 `_execute_deepseek_commands()` 是硬编码在 app.py 的专有路径 |
| DeepSeek 运行时无能力上报 | 没有 `start_background()`，`deepseek_polling_loop` 仍在 app.py 硬编码启动 |
| Symphony 使用独立 Agent 逻辑 | Elixir 端自己决定用哪个 backend，不通过 agentic-os 的能力检测 |
| 跨系统配置不一致 | 在 dashboard 切换 agent 后，Symphony 不知道；反过来也一样 |

---

## 执行计划

### Phase 1 — DeepSeek dispatch 集成

**当前状态：** `DeepSeekModule` 只有 `check_capabilities()`。`_deepseek_agent_dispatch()`（app.py L1003-L1029）和 `_deepseek_polling_loop`（L1866-L1878）仍然是 app.py 中的独立函数。

**改造：**

1. **DeepSeekModule 添加 dispatch 接口**
   - `dispatch(self, prompt: str, timeout: int = 1800) -> dict` — 通过 DeepSeek agent 运行 prompt
   - `check_balance(self) -> dict` — 从 deepseek_monitor 返回当前余额/用量

2. **迁移 dispatch 逻辑**
   - `_execute_deepseek_commands()` → `DeepSeekModule.execute_commands()`
   - `_deepseek_agent_dispatch()` → `DeepSeekModule.dispatch()`
   - app.py 保留桥接函数，调用 `_module_registry.get("deepseek").dispatch()`
   - 类似现有的 `_push_linear_state_async` 桥接模式

3. **迁移后台轮询**
   - `_deepseek_polling_loop()` → `DeepSeekModule.start_background()`
   - 从 app.py `main()` 中删除 `if _HAS_DEEPSEEK_MONITOR: threading.Thread(target=_deepseek_polling_loop, daemon=True).start()`

**完成标准：**
- [ ] `_execute_deepseek_commands()` → `DeepSeekModule.execute_commands()`
- [ ] `_deepseek_agent_dispatch()` → `DeepSeekModule.dispatch()`
- [ ] `_deepseek_polling_loop` → `DeepSeekModule.start_background()`
- [ ] app.py 中 DeepSeek 专用函数清零
- [ ] 所有 agent dispatch 通过模块桥接

### Phase 2 — Symphony 共享配置协议

**当前状态：** `GET /api/capabilities` 返回 `backends` 列表。但无 Elixir 消费端，无热同步机制。

**API 扩展：**
1. `GET /api/capabilities` — 已存在（P10）
2. `GET /api/config` — 已存在，返回 `agent_backend`
3. `PATCH /api/config` — 已存在（切换 agent 时触发）
4. **新增** `PATCH /api/config` 触发 `socketio.emit("config_changed", {agent_backend: "new_value"})`
5. **新增** `/api/capabilities` 增加 `selected` 字段（当前激活的 backend）

**Symphony 端适配（不在此 repo 范围内，仅定义协议）：**
1. 启动时 GET `/api/capabilities` → 获取可用后端列表
2. 订阅 `config_changed` WebSocket 事件
3. dispatch 通过 `POST /run` 而非直接 CLI

**完成标准：**
- [ ] `PATCH /api/config` 触发 `socketio.emit("config_changed", ...)`
- [ ] `/api/capabilities` 增加 `selected` 字段
- [ ] workflow config 修改后 socketio 推送

### Phase 3 — 消除 app.py 中的硬编码 agent 启动

**当前状态：** `main()` 中最后一个 agent 专用硬编码：
```python
if _HAS_DEEPSEEK_MONITOR:
    threading.Thread(target=_deepseek_polling_loop, daemon=True).start()
```

**改造：**
- `_deepseek_polling_loop` 移入 `DeepSeekModule`
- 删除 app.py `main()` 中的条件线程启动
- 所有 agent 后台线程通过 `ModuleRegistry.init_background()` 管理

**完成标准：**
- [ ] app.py `main()` 中无任何 agent 专用硬编码线程
- [ ] DeepSeek 启动通过 `ModuleRegistry.init_background()`

---

## 关键文件

| 文件 | Phase | 变更 |
|------|-------|------|
| `runner/modules/backends/deepseek.py` | 1, 3 | 扩展 dispatch / execute_commands / start_background |
| `runner/app.py` | 1, 3 | 删除 DeepSeek 专用函数 + 硬编码线程 |
| `runner/core/module_registry.py` | 2 | get_capabilities 增加 `selected` 字段 |
| `runner/app.py` | 2 | PATCH /api/config 触发 config_changed |

---

## 约束

- 不修改 `usage_reader.py`、`run_skill.py`、`linear_client.py`
- DeepSeek dispatch bridge 模式与 Linear 一致
- Symphony 端适配不在本 repo 范围内

---

## 风险

| 风险 | 缓解 |
|------|------|
| DeepSeek dispatch 逻辑复杂，提取后易 break | 桥接函数渐进迁移，先 bridge 后 delete |
| PATCH /api/config 推事件增加 Socket 流量 | 只推送变化字段 |
