# P16 — 乐观 UI 更新：所有操作优先同步本地 state/task_state.json

**状态:** Active  
**优先级:** P1  
**开始:** 2026-05-14  
**负责人:** AgenticOS  

---

## 原则

所有用户操作遵循同一模式：

```
用户点击
  ↓
立即更新本地 state/task_state.json（文件写 + 内存缓存）
立即更新 UI（关闭弹窗 / 刷新面板）
  ↓（fire-and-forget，不 await）
异步同步到 Linear API
```

---

## 当前慢操作

| # | 操作 | 触发方式 | 当前行为 |
|---|------|---------|---------|
| 1 | Cancel | `cancelLinearIssue()` | PATCH 到 Linear API，等返回才关弹窗 |
| 2 | Cancel (card) | `cancelLinearIssueById()` | 同上 |
| 3 | Save to Linear | `saveLinearIssue()` | POST/PATCH 到 Linear API，等返回 |
| 4 | 状态变更 (dropdown) | `linear-edit-state` onChange | 发送 PATCH |
| 5 | Dispatch (▶) | `dispatchFromDetail()` | PATCH state + preferred_agent，等返回 |
| 6 | Approve (In Review → Done) | `approveLinearIssue()` | PATCH state，等返回 |
| 7 | Comment/Feedback 提交 | `submitReply()` | POST comment + PATCH 状态 |

---

## 执行计划

### Phase 1 — 后端本地同步路由

**文件：** `runner/modules/linear/__init__.py`

新增 `PATCH /api/linear/issues/local/<issue_id>` 路由，只写本地不调 Linear API：

```python
@self._route("/api/linear/issues/local/<issue_id>", methods=["PATCH"])
def _local_sync_handler(issue_id):
    data = request.get_json() or {}
    if issue_id in self.issues_cache:
        self.issues_cache[issue_id].update(data)
    local = self.get_local_tracker()
    if "state_name" in data:
        local.update_issue_state(issue_id, data["state_name"])
    if "preferred_agent" in data:
        local.set_issue_agent(issue_id, data["preferred_agent"])
    return jsonify({"ok": True})
```

**依赖：** `local_tracker.py` 需要 `set_issue_agent()` 方法。

**完成标准：**
- [ ] `PATCH /api/linear/issues/local/<id>` 实现
- [ ] 只写本地，不调 Linear API

---

### Phase 2 — 前端乐观更新

**文件：** `runner/templates/index.html`

逐操作改为乐观模式，共用函数：

**Cancel（✅ 已完成）**
- `cancelLinearIssue()`: 关弹窗 → 刷新面板 → fire-and-forget PATCH

**Save to Linear**
- `saveLinearIssue()`: 写本地 state → fire-and-forget PATCH

**状态变更**
- `linear-edit-state` onChange: 写本地 state → fire-and-forget PATCH

**Dispatch**
- `dispatchFromDetail()`: 本地写 state → fire-and-forget PATCH

**Approve**
- `approveLinearIssue()`: 本地写 state → fire-and-forget PATCH

**Comment/Feedback**
- `submitReply()`: 本地写 → fire-and-forget PATCH

**Card-level Cancel**
- `cancelLinearIssueById()`: 乐观更新

**完成标准：**
- [ ] 所有 7 个操作用户点击后 < 50ms 响应
- [ ] API 调用 fire-and-forget，不阻塞 UI

---

### Phase 3 — 验证

1. 点击 Cancel → 弹窗即时关闭
2. 修改状态/标题/评论 → UI 即时更新
3. 断开网络 → 本地操作仍然流畅
4. 恢复网络 → 轮询线程最终一致

---

## 非目标

- ❌ 不改 Linear API 全量轮询
- ❌ 不改 PTY/SSE/SSH
- ❌ 不改 dispatch 线程行为

---

## 风险

| 风险 | 缓解 |
|------|------|
| Linear API 失败后数据不一致 | 轮询线程最终修复 |
| 并发 fire-and-forget 排队 | 无副作用 |
| 本地写失败 | catch 静默 |


---

## 架构演化方向（2026-05-15 更新）

### 现状诊断

当前 Flask + Jinja2 模板 + 手写 JS 的架构在功能上够用，但 UI 迭代阻力越来越大：

| 症状 | 根因 | 后果 |
|---|---|---|
| 相同卡片/表格在不同页面重复写 | 无组件化 | 改一次样式要全文搜索替换 |
| API 响应的字段名拼错了不报错 | 无类型系统 | runtime 才炸，浪费时间 |
| 改一行 CSS 要手动刷新浏览器 | 无热重载 | 开发节奏被打断 |
| JS 逻辑散落在多个 `<script>` 标签里 | 模板与逻辑耦合 | 模块间依赖靠记忆 |
| 每次重启 Flask 才能看到 UI 变化 | 前端代码在后端进程中 | 改 UI 影响 API 服务 |

**根因：Flask 干了不属于它的活。** Flask 负责 API、SocketIO、调度——这些是它的强项。但它还负责渲染复杂 UI，这不是模板引擎擅长的。

P16 的乐观更新在现有架构下是对的（低成本、高收益）。长期看，瓶颈在前端工具链，不在后端。

### 目标架构

```
┌─ 浏览器 ─────────────────────────────────┐
│  TypeScript 前端 (Vite + Preact)         │
│  ┌─────────────────────────────────┐     │
│  │ 看板视图  │ 详情面板 │ 配置页   │     │
│  │ TaskCard  │ StateDropdown       │     │
│  │ KanbanBoard│ CommentFeed        │     │
│  └──────────┴──────────────────────┘     │
│          ↕ fetch / WebSocket             │
├─ localhost:8510 ─────────────────────────┤
│  Flask (Python)                          │
│  ┌─────────────────────────────────┐     │
│  │ REST API  │ SocketIO │ 调度器   │     │
│  │ runner/    │ state/   │ modules/│     │
│  └──────────┴──────────────────────┘     │
│         ↕ subprocess                     │
│  claude -p  /  codex exec               │
└──────────────────────────────────────────┘
```

**关键原则：Flask 后端不做任何修改。** 你现在的 `app.py`、`run_skill.py`、`modules/` 全部保持原样。前端通过 HTTP + WebSocket 与它通信。

### 目录结构

```
agentic-os/
├── runner/                      ← 不动
│   ├── app.py                   ← 不变
│   ├── templates/index.html     ← 逐步替换，最终删除
│   └── modules/                 ← 不变
├── ui/                          ← 新增
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── index.html               ← Vite 入口，替换 templates/index.html
│   └── src/
│       ├── main.tsx             ← 应用入口
│       ├── App.tsx              ← 路由/布局
│       ├── api/
│       │   ├── client.ts        ← fetch 封装（调 Flask API）
│       │   └── socket.ts        ← SocketIO 客户端
│       ├── types/
│       │   └── api.ts           ← API 响应类型定义
│       ├── components/
│       │   ├── KanbanBoard.tsx  ← 看板（参考 Vibe Kanban react-kanban）
│       │   ├── TaskCard.tsx     ← 任务卡片
│       │   ├── StateDropdown.tsx← 状态选择器
│       │   ├── DetailPanel.tsx  ← 详情侧面板
│       │   ├── CommentFeed.tsx  ← 评论/反馈流
│       │   └── AgentBadge.tsx   ← agent 状态指示器
│       └── hooks/
│           ├── useSocket.ts     ← SocketIO hook
│           └── useTasks.ts      ← 任务数据管理
```

### 迁移策略：按页面逐个替换，不搞大爆炸

```
第一阶段：看板视图
  └─ index.html 中的看板/任务列表 → ui/src/components/KanbanBoard.tsx
     保留其他模板页面不动

第二阶段：详情面板
  └─ 详情弹窗 → ui/src/components/DetailPanel.tsx + CommentFeed.tsx

第三阶段：配置页
  └─ 配置表单 → 独立页面

第四阶段：删除旧模板
  └─ runner/templates/index.html 下线
```

每个阶段可以独立开发和上线，不需要一次完成。

### 开发工作流

```bash
# 终端 1：Flask 后端（不变）
cd agentic-os
.venv/bin/python3 runner/app.py

# 终端 2：前端开发服务器
cd agentic-os/ui
npm install
npm run dev  # Vite 热重载, 默认 5173 端口
```

**跨域处理**：Vite dev server 代理 Flask API：

```typescript
// ui/vite.config.ts
import { defineConfig } from 'vite'
export default defineConfig({
  server: {
    proxy: {
      '/api': 'http://localhost:8510',
      '/socket.io': { target: 'http://localhost:8510', ws: true }
    }
  }
})
```

**部署时**：`npm run build` → `dist/` 复制到 `runner/` 下，Flask 托管。

### 状态管理

当前状态管理的模式不需要大改：

```
现有模式：
  Jinja2 模板 + 全局 JS 变量
  SocketIO 监听 → 直接修改 DOM

新模式：
  React state (useState/useReducer)
  SocketIO listener → dispatch reducer action
  /api/... 端点 → 更新 state
  UI 自动响应 state 变化
```

**不需要引入 Redux 或 Zustand。** 你的场景（一个 dashboard 显示任务列表和状态）用 React 内置的 state 管理就够了。引入额外状态管理库会增加复杂度，收益极低。

```typescript
// hooks/useTasks.ts — 核心数据流
function useTasks() {
  const [tasks, setTasks] = useState<Task[]>([])
  const [connected, setConnected] = useState(false)

  useEffect(() => {
    // 初始化：拉取全量数据
    fetch('/api/tasks').then(r => r.json()).then(setTasks)
    // 连接 SocketIO 监听增量更新
    const socket = io()
    socket.on('task_update', (delta) => {
      setTasks(prev => applyDelta(prev, delta))
    })
    socket.on('connect', () => setConnected(true))
    return () => { socket.disconnect() }
  }, [])

  return { tasks, connected }
}
```

### 可参考的 Vibe Kanban 前端组件

Vibe Kanban 是 Rust 后端 + TypeScript 前端（Apache 2.0），前端部分可以直接借鉴：

| Vibe Kanban 组件 | 能否复用 | 需要改什么 |
|---|---|---|
| `packages/react-kanban/` (看板) | ✅ 参考 UI 布局和拖拽逻辑 | API 端改成调 Flask 端点 |
| `packages/common/` (共享类型) | ⚠️ 参考类型定义模式 | 数据结构不同 |
| Rust 后端 | ❌ 不需要 | 你的场景 Python 足够 |

注意：Vibe Kanban 的后端 API 围绕 git worktree 和 MCP 设计，和你的 runner 场景不同。**不要试图直接对接它的 Rust 后端。**

### Simon Scrapes Command Center 的可借鉴设计

Simon Scrapes 视频提出的几个设计模式值得参考：

1. **Your Turn / Claude's Turn 看板布局** — 取代传统的线性 kanban，反映 AI 协作的迭代本质
2. **业务层抽象** — dashboard 展示业务目标（"建立获客系统"），而不是底层会话状态
3. **任务分级** — Quick Task / Campaign / Deep Build 三级分类

这些是 UI 设计模式，不依赖语言或框架，可以直接在 React 组件里实现。

### Flask 在架构中的最终定位

迁移完成后，Flask 仍然是核心组件，只是职责更清晰：

```
API 接口层        ← Flask 路由（/api/...）
实时推送          ← Flask-SocketIO
技能调度          ← Flask 调 subprocess
文件处理          ← werkzeug.secure_filename
静态文件托管       ← Flask 跑完后托管 dist/
```

**Flask 不做的事：**
- ❌ 不再渲染 HTML 模板
- ❌ 不再处理前端状态
- ❌ 不再拼装 UI 片段

### 为什么不用全栈 TypeScript (Next.js)

全栈 TypeScript（Node/Next.js 替代 Flask）技术上可行，但对你来说**收益为零**：

| 要换的内容 | 工作量 | 获得什么 |
|---|---|---|
| Flask → Node | 2000+ 行 Python 重写 | 几乎无（过程式编排不需要类型系统优势） |
| subprocess 调用 | 全重写 | 无（Python subprocess 已经很成熟） |
| JSONL/SQLite 读写 | 全重写 | 无（Python 生态在这两个领域更好） |
| SocketIO 集成 | 全重写 | 少于 Flask（python-socketio 最成熟） |

**只换前端，不动后端** 的路径成本最低、风险最小、收益最快。

### 为什么不用 Rust

Rust 在 Vibe Kanban 的选择是有道理的（单二进制分发 + 大量并发 worktree），但你的场景不同：

- 用户只有你自己，不需要分发
- 不需要同时管理 N 个 git workspace
- Python subprocess 的并发能力足够支撑你的场景

**Rust 是解决你没有的问题。**

### 最佳时间线

| 阶段 | 内容 | 估算 | 依赖 |
|---|---|---|---|
| P16（当前） | Flask 模板内乐观更新 | 1-2 天 | 无 |
| 同时 | 初始化 ui/ 目录 + Vite + Preact | 2 小时 | 无 |
| Phase 1 | 看板视图 TypeScript 原型 | 2-3 天 | P16 完成 |
| Phase 2 | 详情面板 + SocketIO 集成 | 2-3 天 | Phase 1 |
| Phase 3 | 配置页迁移 | 1-2 天 | Phase 2 |
| Phase 4 | 旧模板下线 | 0.5 天 | Phase 1-3 |

中间任何时候可以暂停——新的 TypeScript 前端和老的 Flask 模板可以共存，通过 URL 路径或 query 参数切换。
