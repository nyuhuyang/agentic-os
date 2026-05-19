# P14 — 四 Agent 选择：Claude / Codex / DeepSeek / DeepSeek TUI

**状态:** Active  
**优先级:** P1  
**开始:** 2026-05-13  
**负责人:** AgenticOS  

---

## 目标

Dashboard 上可选 4 个 agent，dispatch 路径不同：

| Agent | 值 | Dispatch 方式 |
|-------|-----|-------------|
| Claude | `claude` | `claude -p <prompt>` 子进程 |
| Codex | `codex` | `codex exec <prompt>` 子进程 |
| DeepSeek | `deepseek` | `run_deepseek_agent()` 直接 API |
| DS TUI | `deepseek-tui` | `deepseek exec --yolo --approval-policy auto <prompt>` CLI |

---

## 工作范围

### 已完成的修改

**`runner/app.py`：**
- 恢复 `from deepseek_agent import run_deepseek_agent` import
- `_ai_cli()` 将 `deepseek` 分支改为 `deepseek-tui`
- Free-prompt dispatch: `if agent == "deepseek"` → 直接 API；`else` → 子进程
- Retry dispatch: 同上
- `_preferred_task_agent()` 白名单加入 `deepseek-tui`
- retry 路由 agent 白名单加入 `deepseek-tui`

**`runner/templates/index.html` - 可见按钮：**
- Skill panel: 增加「DS TUI」按钮
- New issue modal: 增加「DS TUI」按钮
- Detail modal dispatch/retry: 增加「DS TUI」按钮
- Job card retry: 增加「↺ DS TUI」按钮
- `setAgent()`: toggle `agent-deepseek-tui` 元素
- `setNewIssueAgent()`: 支持 `deepseek-tui`
- `setDetailIssueAgent()`: 支持 `deepseek-tui`
- `_updateDetailRetryLock()`: 增加 `detail-retry-deepseek-tui`
- `dispatchFromDetail()`: 删除 aider 遗留兼容

### 剩余的改动

**`runner/templates/index.html` - 后台 JS 数组/函数：**

| # | 位置 | 当前内容 | 需改为 |
|---|------|---------|--------|
| 1 | `_availableBackends`（~L1086） | `['claude', 'codex', 'deepseek']` | 加 `'deepseek-tui'` |
| 2 | `_updateAgentVisibility()`（~L1088） | 遍历 3 个 | 加 `'deepseek-tui'` |
| 3 | `_normalizeAgent()`（~L82574） | 仅 3 个 | 加 `'deepseek-tui'` |
| 4 | `hasAssignedAgent`（~L86246） | 仅 3 个 | 加 `'deepseek-tui'` |
| 5 | `clearIssuePreferredAgent()`（~L91556） | 含 `aider` 兼容 | 更新列表 |
| 6 | `triggerLinearIssueWithAgent()`（~L92475） | 含 `aider` 兼容 | 加 `'deepseek-tui'` |
| 7 | `updateWindows()`（~L58139） | 仅 3 个 | 加 `'deepseek-tui'` |

---

## 执行顺序

### Phase 1 — 后台 JS 数组更新

更新所有只循环 3 个 agent 的 JS 数组，加入 `'deepseek-tui'`。

**文件：** `runner/templates/index.html`

**完成标准：**
- [ ] `_availableBackends` 含 `deepseek-tui`
- [ ] `_updateAgentVisibility` 遍历 4 个 agent
- [ ] `_normalizeAgent` 接受 `deepseek-tui`
- [ ] `hasAssignedAgent` 检查包含 `deepseek-tui`
- [ ] `clearIssuePreferredAgent` 使用正常 agent 列表
- [ ] `triggerLinearIssueWithAgent` 含 `deepseek-tui`

### Phase 2 — 验证

1. `python3 -m py_compile runner/app.py`
2. 重启 dashboard
3. 检查 4 个 agent 按钮都在 UI 中可见
4. DeepSeek（API）→ 调 `run_deepseek_agent`
5. DS TUI（CLI）→ 调 `deepseek exec`

**完成标准：**
- [ ] Python 语法通过
- [ ] UI 4 按钮均可见
- [ ] 两条 dispatch 路径分别正确

---

## 非目标

- ❌ 不改后端 dispatch 逻辑
- ❌ 不删 `deepseek_agent.py`
- ❌ 不改 `deepseek_monitor.py`
