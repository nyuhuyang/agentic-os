# P13 — DeepSeek Dispatch 清理：移除死代码、统一走 TUI CLI

**状态:** Active  
**优先级:** P1  
**开始:** 2026-05-13  
**负责人:** AgenticOS  

---

## 当前架构诊断

### 实际 dispatch 路径

```
Free-prompt / Retry
  ↓
app.py: agent == "deepseek" and _HAS_DEEPSEEK_AGENT and not shutil.which("deepseek")
  ↓  (CLI 已安装 → 条件为 False)
else: subprocess.Popen(_ai_command(agent, prompt))
  ↓
["deepseek", "exec", "--yolo", "--approval-policy", "auto", prompt]
  ↓
DeepSeek TUI agent ✅
```

### 死代码

| 文件/函数 | 行数 | 调用情况 | 状态 |
|-----------|------|----------|------|
| `runner/deepseek_agent.py` | 341 | `DeepSeekModule.dispatch()` 调用它，但该函数从未被触发 | ❌ 在线死代码 |
| `app.py` 中 `_HAS_DEEPSEEK_AGENT` 条件分支（L1141-1170） | ~30 | CLI 存在时永远不执行 | ❌ 死代码 |
| `app.py` 中 `_ds_dispatch()`（L449-453） | ~5 | 从未被调用（仅在被移除的死代码分支内调用） | ❌ 死代码 |
| `app.py` 中 `_execute_deepseek_commands()`（L1052-1056） | ~5 | 桥接到 `DeepSeekModule.execute_commands()`，但从未被调用 | ❌ 死代码 |
| `modules/backends/deepseek.py` `dispatch()` 内部的 `deepseek_agent` 调用 | ~15 | CLI 存在时从不走这条路径 | ❌ 死代码 |

### 因果关系

```
deepseek_agent.py
  └─ run_deepseek_agent()    ← 直接 API 集成，自有工具定义
      └─ DeepSeekAgent.run() ← tool-calling 循环 + httpx → api.deepseek.com

            ↑ 调用方          ↑ 何时触发
modules/backends/deepseek.py: 只当 CLI 不可用时
    DeepSeekModule.dispatch()  (目前 CLI 已安装 → 永不触发)

app.py 中 _ds_dispatch()     只当 CLI 不可用时
    桥接函数                  (目前 CLI 已安装 → 永不触发)

app.py 中 L1141-1170         只当 CLI 不可用时
    条件分支                  (目前 CLI 已安装 → 永不触发)
```

---

## 执行计划

### Phase 1 — 清理 `app.py` 的 DeepSeek 条件分支

**当前状态：** `app.py` L1141-1202 包含一个 `if/else` 条件：DeepSeek 走直接 API 还是所有 agent 走 CLI 子进程。

**改造目标：** DeepSeek 和其他 agent 一样统一走 CLI 子进程，消除条件分支。

**文件：** `runner/app.py`

**具体改动：**

1. **删除 `_HAS_DEEPSEEK_AGENT` 导入**（L71-76）
   - 从 `try/except ImportError` 块中移除 `deepseek_agent` 的导入
   - 删除 `_HAS_DEEPSEEK_AGENT` 和 `DeepSeekAgent` 变量
   - 注意：`_HAS_DEEPSEEK_MONITOR` 保留（monitoring 独立）

2. **删除 `_ds_dispatch()` 函数**（L446-453）
   - 桥接函数，不再需要

3. **删除 `_execute_deepseek_commands()` 函数**（L1047-1056）
   - 桥接函数，不再需要（实际从未被外部调用）

4. **简化 dispatch 条件**（L1141-1202）
   - 从：
     ```python
     if agent == "deepseek" and _HAS_DEEPSEEK_AGENT and not shutil.which("deepseek"):
         # DeepSeek API fallback
         ...
     else:
         # Claude / Codex / DeepSeek CLI — subprocess dispatch
         ...
     ```
   - 改为：所有 agent 统一走 CLI subprocess dispatch

5. **简化 retry dispatch 条件**（L1576-1610）
   - 同理，删除 DeepSeek API fallback 分支
   - 所有 agent 统一走 CLI subprocess

**完成标准：**
- [ ] `app.py` 中无 `_HAS_DEEPSEEK_AGENT` 引用
- [ ] `app.py` 中无 `_ds_dispatch()` 函数
- [ ] `app.py` 中无 `_execute_deepseek_commands()` 函数
- [ ] 只有一条 dispatch 路径：`_ai_command(agent, prompt)` → `subprocess.Popen`
- [ ] 只有一条 retry dispatch 路径：`_ai_command(agent, prompt)` → `subprocess.Popen`

---

### Phase 2 — 重写 `DeepSeekModule.dispatch()` 使用 CLI

**当前状态：** `modules/backends/deepseek.py` `dispatch()` 调用 `deepseek_agent.run_deepseek_agent()`。Phase 1 删除 `_ds_dispatch()` 后，模块系统中的 `dispatch()` 方法仍需正常运行。

**改造目标：** `DeepSeekModule.dispatch()` 改用 `deepseek exec` 子进程。

**文件：** `runner/modules/backends/deepseek.py`

**具体改动：**

1. **重写 `dispatch()` 方法**
   - 改为使用 `subprocess.Popen(["deepseek", "exec", "--yolo", "--approval-policy", "auto", prompt])`
   - 输出解析与 `_parse_agent_output` 一致
   - 返回 `ok`, `output`, `duration_s`, `input_tokens`, `output_tokens`, `model`

2. **确认 `execute_commands()` 方法**
   - 解析 output 中的 ```bash/shell 代码块
   - 无需大改

**完成标准：**
- [ ] `DeepSeekModule.dispatch()` 使用 `deepseek exec` CLI
- [ ] 返回 dict 包含预期字段

---

### Phase 3 — 标记 `runner/deepseek_agent.py` 弃用

**当前状态：** 341 行的直接 API 集成，Phase 1+2 后不再有代码调用它。

**方案：** 保留文件但添加头部注释标记为"弃用/参考"。

**文件：** `runner/deepseek_agent.py`

**具体改动：**
1. 文件头部添加注释：
   ```
   # DEPRECATED — kept as reference for direct DeepSeek API integration.
   # Dispatch now uses `deepseek exec` CLI (DeepSeek TUI).
   # See modules/backends/deepseek.py for the active dispatch path.
   ```

**完成标准：**
- [ ] `deepseek_agent.py` 头部有 DEPRECATED 注释

---

### Phase 4 — 验证集成

**验证内容：**

1. **语法检查：**
   ```bash
   python3 -m py_compile runner/app.py
   python3 -m py_compile runner/modules/backends/deepseek.py
   ```

2. **启动 dashboard 无报错：**
   ```bash
   .venv/bin/python3 runner/app.py --debug
   ```
   确认启动日志无 ImportError

3. **Free-prompt dispatch：**
   - 在 dashboard 输入框选择 DeepSeek agent
   - 提交简单 prompt
   - 确认任务执行成功，状态流转正常

4. **Retry dispatch：**
   - 从已有任务点 Retry
   - 确认 agent 为 deepseek 时正常执行

**完成标准：**
- [ ] Phase 1-3 语法检查通过
- [ ] Dashboard 启动无报错
- [ ] Free-prompt + Retry 正常执行

---

## 非目标

- ❌ 不删除 `runner/deepseek_monitor.py`（监控独立）
- ❌ 不修改 `usage_reader.py`、`run_skill.py`、`linear_client.py`
- ❌ 不修改前端模板
- ❌ 不涉及 Symphony 配置协议

---

## 风险

| 风险 | 缓解 |
|------|------|
| `deepseek exec` 不返回 JSON，token 计数为零 | 设 None，不影响功能 |
| CLI 突然不可用时（卸载）报 FileNotFoundError | 与 claude/codex 一致，已有处理 |
| 删错 import 影响其他功能 | 仅删 `deepseek_agent` 相关，保留 `_HAS_DEEPSEEK_MONITOR` |

---

## 文件改动清单

| 文件 | Phase | 改动类型 |
|------|-------|---------|
| `runner/app.py` | 1 | 删除 import + 3 个函数 + 2 个条件分支 |
| `runner/modules/backends/deepseek.py` | 2 | 重写 `dispatch()` |
| `runner/deepseek_agent.py` | 3 | 添加 DEPRECATED 注释 |

---

## 引用

- P11: `docs/exec-plans/active/p11-agent-dispatch-deepseek.md`
- P8: `docs/exec-plans/completed/p8-deepseek-tui-migration.md`
