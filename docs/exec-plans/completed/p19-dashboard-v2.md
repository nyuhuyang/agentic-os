# P19 — Dashboard v2：React 18 + vibe-kanban 组件 + symphony-ts

**状态:** Active  
**优先级:** P1  
**依赖:** P17-fix（✅ 已完成，engine 稳定）

---

## 当前 ui/ 现状（起点）

P18 已搭出骨架，但还是 Preact + dnd-kit，不是 React 18 + vibe-kanban：

| 文件 | 状态 |
|---|---|
| `src/types/api.ts` | ⚠️ 类型与实际 engine JSON 不匹配（见下） |
| `src/api/client.ts` | ⚠️ 只有 `fetchState()`，缺 cancel/dispatch/comment/tokens |
| `src/hooks/useIssues.ts` | ⚠️ 5 秒轮询，未接 SSE invalidation |
| `src/hooks/useSSE.ts` | ✅ 基本可用 |
| `src/components/KanbanBoard.tsx` | ⚠️ 只渲染 running+retrying，全列结构未建 |
| `src/components/TaskCard.tsx` | ⚠️ 无 agent badge / turn / token bar / cancel 按钮 |
| `src/components/DetailPanel.tsx` | ⚠️ 空壳 |
| `package.json` | ❌ 仍是 Preact + dnd-kit，需切 React 18 + vibe-kanban 依赖 |

---

## 实际 Engine API（已验证，DeepSeek 直接对照写）

### `GET /api/v1/state`
```json
{
  "generated_at": "2026-05-16T01:03:54.054Z",
  "counts": { "running": 1, "retrying": 0 },
  "running": [
    {
      "issue_id": "737d699b-691d-494a-873c-8d3d671602f0",
      "issue_identifier": "AGE-87",
      "state": "In Progress",
      "session_id": "d0ec4ca6-0625-4a59-9421-dc6bd14cd9eb",
      "turn_count": 0,
      "last_event": null,
      "last_message": null,
      "started_at": "2026-05-16T01:03:54.229Z",
      "last_event_at": null,
      "tokens": { "input_tokens": 0, "output_tokens": 0, "total_tokens": 0 }
    }
  ],
  "retrying": [],
  "codex_totals": {
    "input_tokens": 7, "output_tokens": 368,
    "total_tokens": 375, "seconds_running": 17.272
  },
  "rate_limits": null
}
```

**注意**：`running[]` 每项是扁平对象（snake_case），不是嵌套 `issue + session`。现有 `types/api.ts` 的 `RunningIssue` 类型错误，需重写。

### `GET /api/v1/events` — SSE
每次 engine 状态变化推送，格式 `data: {...}\n\n`。前端 SSE → 触发重新 fetchState。

### `GET /api/v1/<issue-identifier>`
返回 `IssueDetailResponse`（running / retry_queued 状态才有数据，其他 404）。

### `POST /api/v1/refresh`
触发 engine 立即 poll Linear。Response: `{ queued, coalesced, requested_at, operations }`.

### `POST /api/v1/issues/:id/cancel`
Body: 空。Response: `{ ok: boolean, message: string }`.

### `POST /api/v1/issues/:id/dispatch`
Body: 空。Response: `{ ok: boolean }`.

### `POST /api/v1/issues/:id/comment`
Body: `{ "body": "comment text" }` (JSON)。Response: `{ ok: boolean, message: string }`.

### `GET /api/v1/tokens/5h` / `GET /api/v1/tokens/weekly`
```json
{
  "period": "5h",
  "since": "2026-05-15T20:04:22.586Z",
  "note": "In-memory only; data resets on engine restart.",
  "entries": [
    { "at": "iso", "issueIdentifier": "AGE-87",
      "inputTokens": 7, "outputTokens": 368, "totalTokens": 375 }
  ],
  "totals": { "inputTokens": 7, "outputTokens": 368, "totalTokens": 375 }
}
```

---

## 关键数据缺口

**`/api/v1/state` 只返回 running + retrying**，不包含 Todo / backlog / Done 的 issue。

全列看板需要解决这个问题。两个选项：

| 方案 | 优点 | 缺点 |
|---|---|---|
| **A. 前端直接调 Linear GraphQL** | 完整数据 | 需要把 LINEAR_API_KEY 暴露给前端（通过 vite proxy 转发） |
| **B. engine 加 `/api/v1/issues/all` 端点** | 前端无需 key | 需要改 symphony-ts（P17-fix 追加任务） |

**建议 A**（短期）：Vite dev proxy 把 `/linear-api` 转发到 `https://api.linear.app/graphql`，key 通过 `VITE_LINEAR_API_KEY` 环境变量注入。生产环境由 engine 代理。

---

## 技术栈（目标）

| 项目 | 当前 | 目标 |
|---|---|---|
| 框架 | Preact | **React 18** |
| 拖拽 | dnd-kit | **@hello-pangea/dnd**（vibe-kanban 已有）|
| 数据请求 | 手写轮询 | **TanStack React Query** |
| 富文本输入 | 无 | **Lexical**（vibe-kanban 已有）|
| UI 原语 | 无 | **Radix UI**（Dialog、DropdownMenu、Tooltip）|
| 组件库 | 手写 | **vibe-kanban `packages/ui/`** 组件 |

### vibe-kanban 接入方式

```bash
# 在 ui/ 目录
pnpm link ../../vibe-kanban/packages/ui
```

或直接复制需要的组件到 `ui/src/components/vibe/`（避免 link 的路径问题，推荐）。

vibe-kanban 路径：`prototypes/vibe-kanban/packages/ui/src/components/`

直接复用的组件：
- `KanbanProvider` / `KanbanBoard` / `KanbanCard` / `KanbanCards` / `KanbanHeader`
- `RunningDots`
- `IssueCommentsSection` / `CommentCard`
- Radix UI: `Dialog`（确认框）、`DropdownMenu`（状态切换）、`Tooltip`

---

## 设计语言（继承 Flask 版）

覆盖 vibe-kanban HSL CSS 变量：

```css
:root {
  --background: 0 0% 5%;        /* #0d0d0d */
  --card: 0 0% 8.6%;            /* #161616 */
  --border: 0 0% 16.5%;         /* #2a2a2a */
  --foreground: 0 0% 83%;       /* #d4d4d4 */
  --muted-foreground: 0 0% 40%; /* #666 */
  --accent: 19 77% 57%;         /* #e8723a */
}
```

字体：`'SF Mono', 'Fira Code', monospace`  
Agent badge 颜色：`claude=#e8a87c` / `codex=#6fb5d4` / `deepseek=#7ec8a0`

---

## 看板结构

```
backlog → todo → running → review → rework → merging → done
                  (pulse)                            ↓
                                          cancelled / duplicate
                                          → Trash Panel（折叠）
```

列头颜色点：
- `running`: yellow pulse + RunningDots 动画
- `review`: red
- `done`: green

数据来源：
- `running` / `retrying` 列 → `/api/v1/state`（实时）
- 其他列 → Linear GraphQL 直查（方案 A）或 `/api/v1/issues/all`（方案 B）

---

## 卡片设计（扩展 KanbanCardContent）

```
┌──────────────────────────────────────────┐
│ AGE-87  [claude] ●●●  turn 0/6     [✕]  │
│ 测试new task                              │
│ 17s  375 tokens  ████░░░░░             │
└──────────────────────────────────────────┘
```

字段来自 `/api/v1/state` running 项：
- `issue_identifier` → 左上 ID
- `session_id != null` → 显示 RunningDots + 黄色左色带
- `turn_count` → turn 进度（分母从 WORKFLOW.md `max_turns`，默认 6）
- `tokens.total_tokens` → token bar
- `started_at` → elapsed 计时（前端自算）
- Cancel 按钮（仅 running 状态） → `POST /api/v1/issues/:id/cancel`

---

## 正确的类型定义

重写 `src/types/api.ts`（对照实际 engine JSON，全部 snake_case）：

```typescript
// 对应 /api/v1/state running[] 每项
export interface RunningEntry {
  issue_id: string
  issue_identifier: string
  state: string
  session_id: string | null
  turn_count: number
  last_event: string | null
  last_message: string | null
  started_at: string
  last_event_at: string | null
  tokens: { input_tokens: number; output_tokens: number; total_tokens: number }
}

export interface EngineState {
  generated_at: string
  counts: { running: number; retrying: number }
  running: RunningEntry[]
  retrying: RunningEntry[]
  codex_totals: {
    input_tokens: number; output_tokens: number
    total_tokens: number; seconds_running: number
  }
  rate_limits: Record<string, unknown> | null
}

export interface TokenUsageEntry {
  at: string
  issueIdentifier: string
  inputTokens: number; outputTokens: number; totalTokens: number
}

export interface TokenUsageResponse {
  period: '5h' | 'weekly'
  since: string
  note: string
  entries: TokenUsageEntry[]
  totals: { inputTokens: number; outputTokens: number; totalTokens: number }
}

// Linear issue（用于全列看板，Linear 直查）
export interface LinearIssue {
  id: string
  identifier: string
  title: string
  url: string
  state: { name: string }
  priority: number | null
  labels: { nodes: { name: string }[] }
}
```

---

## 完整 API Client

`src/api/client.ts` 需暴露所有端点：

```typescript
fetchState(): Promise<EngineState>
fetchIssueDetail(identifier: string): Promise<IssueDetailResponse | null>
postRefresh(): Promise<RefreshResponse>
cancelIssue(identifier: string): Promise<{ ok: boolean; message: string }>
dispatchIssue(identifier: string): Promise<{ ok: boolean }>
commentOnIssue(identifier: string, body: string): Promise<{ ok: boolean; message: string }>
fetchTokenUsage(period: '5h' | 'weekly'): Promise<TokenUsageResponse>
```

Vite proxy 配置（`vite.config.ts`）：
```typescript
server: {
  proxy: {
    '/api': 'http://127.0.0.1:4321',          // engine
    '/linear-api': {                           // Linear GraphQL proxy（方案A）
      target: 'https://api.linear.app/graphql',
      rewrite: (path) => path.replace(/^\/linear-api/, ''),
      changeOrigin: true,
    }
  }
}
```

---

## 目录结构（目标）

```
ui/src/
├── components/
│   ├── KanbanBoard.tsx       ← KanbanProvider + 全列，复用 vibe-kanban
│   ├── AgentKanbanCard.tsx   ← KanbanCardContent 扩展（agent 字段）
│   ├── TrashPanel.tsx        ← cancelled 折叠
│   ├── DetailPanel.tsx       ← slide-in，含 agent 日志 + comments
│   ├── AgentLog.tsx          ← 参考 ChatAssistantMessage / ChatToolSummary
│   ├── CommentFeed.tsx       ← IssueCommentsSection + Lexical + 麦克风 STT
│   ├── TokenPanel.tsx        ← 5h / weekly token 统计
│   ├── ConfirmDialog.tsx     ← Radix Dialog（拖到 Done 确认）
│   └── Header.tsx
├── hooks/
│   ├── useSSE.ts             ← EventSource → queryClient.invalidateQueries
│   ├── useIssues.ts          ← TanStack Query，fetchState
│   ├── useLinearIssues.ts    ← TanStack Query，Linear GraphQL（全列数据）
│   └── useTokenUsage.ts
├── api/
│   └── client.ts
└── types/
    └── api.ts
```

---

## 执行顺序

### Phase 1 — 类型修复 + API client 完善（半天）

- [ ] 重写 `src/types/api.ts`（snake_case，对照实际 engine JSON）
- [ ] 补全 `src/api/client.ts`（cancel / dispatch / comment / tokens / refresh）
- [ ] `useIssues.ts`：SSE 事件触发 refetch，减少轮询频率（30s → SSE 驱动）
- [ ] 验证：engine 跑 AGE-87，dashboard running 卡片正确显示 session_id / turn_count / tokens

### Phase 2 — 框架切换（半天）

- [ ] `package.json`：Preact → React 18，换 @hello-pangea/dnd，加 @tanstack/react-query / @radix-ui/* / lexical / @phosphor-icons/react
- [ ] 复制 vibe-kanban 组件到 `ui/src/components/vibe/`
- [ ] CSS 变量覆盖：vibe-kanban → AgenticOS 深色主题
- [ ] 字体覆盖：SF Mono / Fira Code
- [ ] 验证：`pnpm dev` 跑通，深色主题生效

### Phase 3 — 全列看板（2-3 天）

- [ ] 决策并实现全列数据源（方案 A proxy / 方案 B engine endpoint）
- [ ] `KanbanProvider` + 全列结构（backlog → done + Trash Panel）
- [ ] `AgentKanbanCard`：badge + RunningDots + turn + token bar + Cancel
- [ ] 运行时左侧黄色色带（`session_id != null`）
- [ ] `KanbanFilterBar` 接入
- [ ] 拖拽：drop → POST state mutation（Linear 或 engine）
- [ ] 拖到 Done → Radix Dialog 确认框
- [ ] 验证：mock 数据下全列渲染 + 拖拽可用

### Phase 4 — SSE 实时更新（1 天）

- [ ] SSE → `queryClient.invalidateQueries(['state'])`
- [ ] running 列 RunningDots 激活、色带出现、Cancel 常驻
- [ ] 验证：engine 跑 issue 时卡片实时变化

### Phase 5 — 详情面板（2-3 天）

- [ ] slide-in 右侧 DetailPanel（Radix Dialog 或自定义 drawer）
- [ ] agent 日志：参考 `ChatAssistantMessage` / `ChatToolSummary` 渲染
- [ ] CommentFeed：`IssueCommentsSection` + Lexical 富文本输入
- [ ] **麦克风按钮（STT）**：录音 → 转文字填入 Lexical（复用 `runner/modules/stt/`）
- [ ] Dispatch / Cancel 按钮
- [ ] 验证：点卡片 → 详情 → 语音输入 feedback → 提交

### Phase 6 — Token 面板（1 天）

- [ ] TokenPanel：`/api/v1/tokens/5h` + `/api/v1/tokens/weekly`
- [ ] engine restart 丢失数据提示（`note` 字段已有，前端展示）
- [ ] 进度条 + backend read-only badge（不可切换）

### Phase 7 — 历史记录（1 天）

- [ ] HistoryPanel：已完成 issue 列表（Linear 直查 Done 状态）
- [ ] 按日期 / agent / 状态过滤

---

## Agent Badge 交互（per-issue dispatch）

**设计**：badge 不是全局切换，是 per-issue dispatch trigger。

| issue 状态 | badge 行为 |
|---|---|
| backlog / todo（未运行） | 点击 → dropdown 选 agent → 确认 → dispatch |
| running | 只读显示当前 agent，不可点击 |
| done / cancelled | 显示跑过的 agent，不可点击 |

**Badge dropdown 选项**：`claude` / `codex` / `deepseek`（三选一）

**Dispatch 流程**：
1. 用户点 badge → Radix DropdownMenu 弹出（claude / codex / deepseek）
2. 选定 agent → `POST /api/v1/issues/:id/dispatch` body `{ "agent": "claude" }`
3. Engine 用该 agent override 全局 backend，立即 spawn 这个 issue
4. SSE 推送 → 卡片移到 running 列 + badge 锁定显示选定 agent

**需要 symphony-ts 配合（小改，加入 P17-fix 追加任务）**：

`POST /api/v1/issues/:id/dispatch` 加 body 支持：
```json
{ "agent": "claude" }   // claude | codex | deepseek | null（null 用全局 config）
```

engine 拿到 `agent` 字段后，为这次 dispatch 临时 override `config.agent.backend`，只影响这一个 issue 的这次运行。

**badge 颜色**：
- `claude` → `#e8a87c`（橙）
- `codex` → `#6fb5d4`（蓝）
- `deepseek` → `#7ec8a0`（绿）
- 未选 → `#666`（灰，点击可选）

---

## 非目标

- ❌ 不重新设计视觉风格（继承 Flask 版深色主题）
- ❌ 不做权限 / 多用户
- ❌ 不做 timeline / 甘特图
- ❌ 不完整移植 vibe-kanban（只取需要的部分）
