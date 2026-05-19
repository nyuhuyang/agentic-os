# AgenticOS — Product Vision

**作者:** yanghu  
**日期:** 2026-05-15  
**状态:** Living document

---

## 核心定位

**AgenticOS 是开发者的 agent 工作界面**，专注于编程任务的 dispatch、监控、和交互。

它不是通用 AI 助手，也不是团队项目管理工具。它是开发者在 agent 时代的主力编程界面。

---

## 生态架构

Linear 是整个生态的协调中心——团队所有工作的通用队列。不同类型的工作由不同的专业界面处理，各自双向同步 Linear。

```
Linear（团队操作系统 / 通用工作队列）
│
├── AgenticOS              ← 编程任务 / 开发者界面       [我们在做]
│   └── agent backends: Codex / Claude Code / DeepSeek
│
├── Claude co-worker       ← 非编程任务（文档、分析、沟通）[第三方]
│
├── [设计工具界面]         ← 设计、产品原型              [第三方/未来]
│
└── [数据/运营界面]        ← 数据分析、运营任务           [第三方/未来]
```

### 各角色使用什么

| 角色 | 主要界面 | Linear 角色 |
|---|---|---|
| 开发者 | AgenticOS Dashboard | 执行层，看自己负责的 issue |
| 技术 Lead | AgenticOS Dashboard | 监控 agent 运行，review 产出 |
| 产品经理 | Linear | 规划任务、定优先级、看进度 |
| 团队其他成员 | Linear / co-worker | 协同、评论、验收 |

---

## AgenticOS 的核心价值

1. **Agent dispatch** — 把 Linear issue 自动派发给最合适的 agent backend
2. **开发者控制界面** — 比 Linear 更细粒度：看 agent 输出、提 feedback、cancel/retry
3. **双向 Linear 同步** — 开发者在 Dashboard 操作，PM 在 Linear 看结果，不重复工作
4. **多 backend 支持** — Codex / Claude Code / DeepSeek，按任务类型配置

---

## 界面形态演进

### 现在（P17 + P18）

Web Dashboard：浏览器里的开发者工作界面。

```
浏览器 → AgenticOS Dashboard → REST API + SSE → AgenticOS Engine → Linear + Agent
```

### 未来：VS Code 插件

AgenticOS 作为 VS Code sidebar panel，开发者不离开编辑器：
- Sidebar 显示当前 Linear issue 列表
- 右键文件/选中代码 → dispatch 给 agent
- Agent 输出在 terminal panel 实时显示
- 与 Web Dashboard 共用同一套 `/api/v1/` 端点

这与 GitHub Copilot Workspace 方向一致，但开发者完全控制引擎和 backend。

### 未来：CLI

```bash
agentic dispatch AGE-123          # 派发 issue
agentic status                    # 查看运行中的 agent
agentic logs AGE-123              # 查看 agent 输出
```

---

## 设计原则

### Linear 是真相来源，不是 AgenticOS

- 所有 issue 状态最终写回 Linear
- AgenticOS 不维护独立的任务数据库
- Dashboard 是 Linear 状态的实时视图 + 操作层

### Agent 对开发者透明

- Dashboard 实时显示 agent 正在做什么（工具调用、token 消耗、当前 turn）
- 开发者随时可以 cancel、retry、提 feedback
- 不是"黑盒运行，结果见 PR"

### 开发者界面，不是 PM 界面

- Dashboard 不做看板排期、里程碑、甘特图
- 复杂的项目管理功能留给 Linear
- Dashboard 专注：issue → agent → 结果 → feedback 这条线

### API 层要干净

- `/api/v1/` 端点设计为可被多个客户端复用（Web / VS Code 插件 / CLI）
- 不做 UI 专用的 API 快捷方式

---

## 当前执行计划对应关系

| 计划 | 对应愿景层 |
|---|---|
| P17 — 引擎层（symphony-ts 吸收） | Agent dispatch + Linear 双向同步 |
| P18 — Dashboard | 开发者主力工作界面（Web 形态） |
| P15 — DeepSeek backend | 多 backend 支持扩展 |
| VS Code 插件 | 未规划，Phase 2 产品方向 |
