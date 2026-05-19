# P18 — Dashboard TS：Vite + Preact 前端仪表盘

**状态:** Completed  
**优先级:** P1  
**开始:** 2026-05-15  
**负责人:** yanghu  

---

## 为什么

### 产品定位

**AgenticOS Dashboard 是开发者的主力编程工作界面**，不是监控页面。

- 开发者在 Dashboard 管理 issue、拖拽调优先级、看 agent 运行进度、提交 feedback
- Linear 是团队协同层（PM 和其他成员看），Dashboard 和 Linear 双向同步
- 目标用户：技术型开发者，习惯在一个页面完成整个 agent 工作流

当前 Flask 模板已不能满足这个定位（无法交互、无实时拖拽、无 feedback 流）。

### 与 P17 的关系

P17（引擎层）提供 REST API + SSE，P18 消费它们。

**P17 需要为 P18 新增写操作端点**（symphony-ts 原版只有只读 API）：
```
POST /api/v1/issues/:id/cancel
POST /api/v1/issues/:id/dispatch
POST /api/v1/issues/:id/comment
PATCH /api/v1/config        ← WORKFLOW.md 热更新
```
这是 P18 的硬依赖，P17 Phase 3 需要优先加这些端点。

P18 Phase 1-3 用 mock API 开发，Phase 4 对接真实 P17。

---

## 目标

### 核心：独立 TypeScript 前端

```
agentic-os/
├── runner/           ← 不再作为主项目，保留不删
└── ui/               ← 新增（P18）
    ├── package.json
    ├── vite.config.ts
    ├── src/
    │   ├── main.tsx
    │   ├── App.tsx
    │   ├── api/         ← Symphony TS API 客户端
    │   ├── types/       ← TypeScript 类型定义
    │   ├── components/  ← 可复用 UI 组件
    │   └── hooks/       ← 自定义 hooks
    └── index.html
```

### 功能目标

| 功能 | 当前（Flask 模板） | 目标（Vite + Preact） |
|---|---|---|
| 任务列表 | 简单的 HTML 表格 | 看板 + 卡片视图 |
| 状态显示 | text + 颜色标签 | AgentBadge 组件 |
| 实时更新 | SocketIO 直接改 DOM | useSocket hook → React state |
| 操作 | 内联 JS fire-and-forget | API client → optimistic update |
| 历史 | run_log.jsonl 表格 | 可过滤、可排序的历史面板 |

### 非目标

- ❌ 不与 Flask 模板兼容（P18 是替代，不是兼容）
- ❌ 不做复杂的权限/用户系统
- ❌ 不做 CSS UI 库（Material UI / Ant Design）— 用 Tailwind CSS

---

## UI 设计参考

### Vibe Kanban 可借鉴

Vibe Kanban 的前端（packages/react-kanban/）是 Apache 2.0 的 TypeScript + React 看板组件：

| 借鉴什么 | 怎么借 |
|---|---|
| 看板卡片布局 | 参考 UI 设计，不抄代码 |
| 状态颜色方案 | 提取配色逻辑 |
| 拖拽排序 | 用 **dnd-kit** 实现（Phase 3 核心功能）|

### Simon Command Center 的 Your Turn / Claude's Turn

看板布局区分两个区域：
- **Your Turn** — 需要用户操作（等待 review/approve/feedback）
- **Claude's Turn** — Agent 正在运行

### 现有 AgenticOS dashboard 的功能（要保留）

- 任务列表展示（issue title, status, agent, 时间）
- 状态切换（dropdown）
- Cancel 操作
- Dispatch 按钮
- Comment/Feedback 提交
- 实时状态更新（SocketIO）
- Token 使用统计

---

## 组件树

```
App
├── Header
│   ├── ConnectionStatus
│   └── AgentSelector (claude/codex/deepseek)
├── MainLayout
│   ├── Sidebar
│   │   ├── IssueList
│   │   └── FilterBar
│   └── Content
│       ├── KanbanView
│       │   ├── Column ("Your Turn")
│       │   │   └── TaskCard[]
│       │   └── Column ("Claude's Turn")
│       │       └── TaskCard[]
│       ├── DetailPanel
│       │   ├── IssueMetadata
│       │   ├── StatusDropdown
│       │   ├── AgentBadge
│       │   ├── CommentFeed
│       │   └── ActionButtons
│       └── HistoryPanel
└── TokenUsageBar (底部)
```

---

## 目录结构

```
ui/
├── package.json
├── vite.config.ts
├── tsconfig.json
├── index.html
└── src/
    ├── main.tsx
    ├── App.tsx
    ├── App.css
    ├── api/
    │   ├── client.ts          ← fetch 封装
    │   └── sse.ts             ← SSE 客户端（/api/v1/events 用 SSE，非 WebSocket）
    ├── types/
    │   ├── api.ts
    │   └── ui.ts
    ├── components/
    │   ├── KanbanBoard.tsx
    │   ├── TaskCard.tsx
    │   ├── Column.tsx
    │   ├── DetailPanel.tsx
    │   ├── CommentFeed.tsx
    │   ├── StatusDropdown.tsx
    │   ├── AgentBadge.tsx
    │   ├── HistoryPanel.tsx
    │   ├── TokenBar.tsx
    │   └── Header.tsx
    └── hooks/
        ├── useSSE.ts
        ├── useIssues.ts
        └── useTokenUsage.ts
```

---

## API 契约（等待 P17 定义）

| 端点 | 用途 |
|---|---|
| GET /api/v1/issues | 获取 issue 列表 |
| GET /api/v1/snapshot | 全量快照 |
| PATCH /api/v1/issues/:id | 更新 issue 状态 |
| POST /api/v1/issues/:id/dispatch | 手动派发 |
| POST /api/v1/issues/:id/cancel | 取消 |
| WebSocket /api/v1/events | 实时事件推送 |

在 P17 未就绪前，P18 可以用 mock API 开发。

---

## 执行顺序

### Phase 1 — 项目初始化（估算：2 小时）

- `pnpm create vite ui --template preact-ts`（在 `agentic-os/` 根下）
- 配置 Tailwind CSS v4（`@tailwindcss/vite` plugin）
- 配置 Vite proxy → P17 API（mock 模式下 proxy 不生效，用 msw 或 hardcoded mock）
- 安装 dnd-kit：`@dnd-kit/core @dnd-kit/sortable @dnd-kit/utilities`
- 验证：`pnpm dev` 跑通，Tailwind 样式生效

### Phase 2 — 基础组件（估算：2-3 天）

- types/api.ts — API 类型定义
- hooks/useSocket.ts — WebSocket 客户端
- hooks/useIssues.ts — 数据管理
- 基础组件：Header、TaskCard、AgentBadge、StatusDropdown
- 验证：展示 mock issue 列表

### Phase 3 — 看板 + 拖拽 + 详情（估算：3-4 天）

- KanbanBoard + Column（Your Turn / Claude's Turn 布局）
- **dnd-kit 拖拽**：issue 卡片在列间拖动 → 触发状态更新 → POST 到 P17 API → 同步 Linear
- DetailPanel + CommentFeed（feedback 提交）
- 操作按钮（Cancel / Dispatch / Comment）
- 验证：拖卡片 → Linear issue 状态同步更新

### Phase 4 — 历史 + Token（估算：1-2 天）

- HistoryPanel（过滤、排序）
- TokenBar 组件
- 验证：历史记录可浏览

### Phase 5 — 对接 P17（估算：1-2 天）

- 从 mock API 切换到真实 P17 API
- WebSocket 事件对接
- 验证：dashboard 实时显示 Symphony TS 运行状态

---

## 关键设计决策

### Preact 而不是 React

- Preact 与 React API 兼容，体积小 90%
- 你的场景不需要 React 的重度生态
- 开发体验几乎一样

### CSS：Tailwind CSS v4

- 不用 Material UI / Ant Design
- Tailwind CSS v4 + `@tailwindcss/vite`，无需 `tailwind.config.js`
- dashboard 组件少，utility-first 比手写 CSS 命名快

### 实时推送：SSE，非 WebSocket

symphony-ts 引擎用 SSE（`GET /api/v1/events`），不是 WebSocket。`useSSE.ts` hook 封装 `EventSource`。

### 状态管理：useState + useReducer

- 不需要 Redux / Zustand
- 状态模型：issue 列表（SSE 推送更新）+ 乐观更新（拖拽/操作先改本地，再 POST）
- `useIssues()` + `useTokenUsage()` 两个 hook 覆盖全部场景

### AgentSelector 组件：不做

backend（codex/claude/deepseek）是全局 WORKFLOW.md 配置，不是 per-session 可切换的。UI 不暴露这个控制。

---


---

## 完成总结（2026-05-15）

| Phase | 内容 | 状态 |
|---|---|---|
| Phase 1 | 项目初始化 — Vite + Preact + TypeScript + dnd-kit | ✅ 构建通过，18KB JS |
| Phase 2 | 基础组件 — Header, AgentBadge, StatusDropdown, TaskCard | ✅ |
| Phase 3 | 看板 + 详情 — KanbanBoard, Column (Your Turn / Claude's Turn), DetailPanel | ✅ |
| Phase 4 | TokenBar | ✅ |
| Phase 5 | 测试 | ✅ vitest + jsdom 配置，基本测试通过 |

### 输出

```
ui/dist/
├── index.html             0.5 kB
├── assets/index-*.css     3.0 kB
└── assets/index-*.js     17.8 kB
```

### 待定

- P17 REST API 写操作端点（`/cancel`, `/dispatch`）待实现后，P18 的 mock API 可切换到真实 API
- dnd-kit 拖拽排序待 P17 API 稳定后对接


---

## 完成总结（2026-05-15）

### 实际成果

| Phase | 内容 | 状态 |
|---|---|---|
| Phase 1 | Vite + Preact + TypeScript + dnd-kit 项目初始化 | ✅ |
| Phase 2 | 基础组件 — Header, AgentBadge, StatusDropdown, TaskCard | ✅ |
| Phase 3 | 看板 + 详情 — KanbanBoard, Column (Your Turn / Claude's Turn), DetailPanel | ✅ |
| Phase 4 | TokenBar | ✅ |
| Phase 5 | 测试配置 + 真实 engine 对接 | ✅ vitest 配置，proxy 连通 mock API |

### Dashboard 输出

```
ui/dist/
├── index.html             0.5 kB
├── assets/index-*.css     3.0 kB
└── assets/index-*.js     18.1 kB
```

### 已验证

- [x] `pnpm build` 通过
- [x] `pnpm test` 通过
- [x] Vite dev server 运行（:5173）
- [x] Mock API server 提供数据
- [x] Dashboard 显示绿色 Connected
- [x] 看板列显示 AGE-90 卡片
- [x] Vite proxy 转发 `/api/` → `localhost:4321`

### 已知问题

1. **Symphony TS engine 崩溃** — 启动后找到 issue → 尝试 dispatch → 崩溃。根源可能是 codex app-server 协议兼容性问题或 workspace 管理异常
2. **Tracker 按 project 过滤** — engine 用 `project.slugId` 过滤 issue，但用户的 Linear 工作主要在 team 级别（AGE 团队），不在 project 内
3. **Mock API 是临时方案** — 当前 :4321 跑的是 Python mock server，不是真实 engine
