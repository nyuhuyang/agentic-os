# P17-fix — Engine 稳定性 + Tracker 改造

**状态:** Active  
**优先级:** P0  
**开始:** 2026-05-15  
**依赖:** symphony-ts fork（已有 config + backend 修改）

---

## 目标

让 symphony-ts engine 能稳定运行并正确找到用户 Linear 上的 issue。

## 任务

### 1. 修崩溃（P0）

Engine 找到 AGE-90 后，dispatch 阶段崩溃。排查方法：

- 捕获 stderr：启动 engine 时把 stderr 输出到文件
- 判断崩溃点：workspace 创建 / agent spawn / 状态机转换
- 根据根因修复（可能是 codex 协议版本不匹配、workspace path 异常等）

### 2. Tracker 按 team 过滤（P1）

当前 GraphQL 查询：`project.slugId` → 只找到 project 内的 issue  
改为：`team.id` → 找到 AGE 团队所有 issue  

改 `src/tracker/linear-queries.ts`：
```graphql
# 原来
filter: { project: { slugId: { eq: $projectSlug } } }

# 改为
filter: { team: { id: { eq: $teamId } } }
```

WORKFLOW.md 配置字段同步修改。

### 3. 写操作 API（P2）

为 Dashboard 操作按钮提供端点：

| 端点 | 方法 | 用途 |
|---|---|---|
| `/api/v1/issues/:id/cancel` | POST | 停止 agent |
| `/api/v1/issues/:id/dispatch` | POST | 手动派发 |
| `/api/v1/issues/:id/comment` | POST | 提交 feedback |

### 4. Token 统计 API

当前 engine 只返回当前 session 的 token。需要加：
- `/api/v1/tokens/5h` — 最近 5 小时 token 使用量
- `/api/v1/tokens/weekly` — 最近 7 天 token 使用量

数据来源：engine 内部 `codex_totals` + 持久化到 JSONL。

---

## 参考文件

symphony-ts 作为独立 repo（`prototypes/symphony-ts`），agentic-os 通过 npm 依赖引用：

```
prototypes/symphony-ts/src/tracker/linear-queries.ts       ← 改 GraphQL 查询
prototypes/symphony-ts/src/config/types.ts                 ← 改配置字段
prototypes/symphony-ts/src/observability/dashboard-http.ts ← 加 API 端点
```

## 已完成

### Tracker 按 team 过滤（已验证已完成）

检查后发现代码早已实现，无需修改：
- `src/tracker/linear-queries.ts` — 两个 query 均已用 `team: { id: { eq: $teamId } }`
- `src/config/types.ts` — `WorkflowTrackerConfig.teamId` 已有
- `src/config/config-resolver.ts` — 已读 `tracker.team_id` → `teamId`
- `WORKFLOW.md` — 已配置 `team_id: 76114694-9541-434c-8600-762735c3bd88` 和 `backend: claude`

### Claude backend bug fix（2026-05-15）

`src/agent/claude-app-server.ts`：
- **bug 1**：`startSession` 把 `input.title`（issue 标题字符串）赋给 `this.workspace`，覆盖了 `setOptions` 设置的 cwd → 删除该行
- **bug 2**：命令缺 `--output-format stream-json --verbose` → JSON 解析失败，`session_id` 永远无法捕获 → `--resume` 跨 turn 续接失效 → 已加两个 flag
- **bug 3**：`emit` 调用没有传 `sessionId` 字段 → orchestrator 的 running state 中 `session_id` 永远为 null → 每条 emit（notification / turn_completed / turn_failed）均加 `sessionId: capturedSessionId ?? undefined`
- **bug 4**：spawn 调用使用旧的 temp file + bash -lc 方式，改为直接 `spawn("claude", args)` + `child.stdin.write(prompt)` → 更简洁，无临时文件
- **bug 5**：遗留了未用的 `fs`/`path`/`os` import → 已清理

`src/config/types.ts`：
- `backend: string` 改为 `backend?: string` → 修复 5 个已有测试 type error（`WorkflowAgentConfig` 对象字面量缺该字段）

**构建注意**：build 脚本用 `tsconfig.build.json`，不是 `tsconfig.json`（后者仅做 typecheck）：
```bash
./node_modules/.bin/tsc -p tsconfig.build.json
```

---

### 写操作 API + Token 统计（2026-05-15）

新增端点（在 `src/observability/dashboard-server.ts` 路由层，`src/orchestrator/runtime-host.ts` 实现层）：

| 端点 | 状态 |
|---|---|
| `POST /api/v1/issues/:id/cancel` | ✅ 中止 worker AbortController，reason: `user_cancel` |
| `POST /api/v1/issues/:id/dispatch` | ✅ 触发 `requestRefresh`，engine 下次 poll 自动 dispatch |
| `POST /api/v1/issues/:id/comment` | ✅ Linear GraphQL `commentCreate` mutation（需 issue 在 running/retry 状态） |
| `GET /api/v1/tokens/5h` | ✅ 内存累加，跨 turn 聚合（重启清零，已在响应中注明） |
| `GET /api/v1/tokens/weekly` | ✅ 同上，7 天窗口 |

其他改动：
- `src/orchestrator/core.ts`：`StopReason` 加 `"user_cancel"`
- `src/tracker/tracker.ts`：`IssueTracker` 加可选 `createComment?(issueId, body)`
- `src/tracker/linear-client.ts`：实现 `createComment`（`commentCreate` mutation）
- `src/observability/dashboard-http.ts`：加 `readRequestBodyAsJson` helper

---

### 启动脚本（2026-05-15）

`agentic-os/start.sh`：
- 加载 `.env`，同时启动 symphony-ts engine（port 4321）和 `ui/` 前端 dev server（port 5173）
- `trap 'kill 0' EXIT` — Ctrl+C 同时停两个进程
- 使用方式：`./start.sh`（在 agentic-os 目录）

---

### 端到端验证结果（2026-05-16）

真实运行 AGE-87（"测试new task"，Todo → In Progress）：
- engine 启动 → Linear 团队 filter → 找到 AGE-87
- Claude spawn → session_id `d0ec4ca6-0625-4a59-9421-dc6bd14cd9eb` 正确捕获
- turn 完成：input_tokens=7，output_tokens=368，total_tokens=375
- `/api/v1/state` 返回 running=1，turn 后 running=0，codex_totals 正确
- `/api/v1/tokens/5h` 返回带 issueIdentifier 的 entry 列表

---

## 完成标准

- [x] 找到 AGE 团队的所有 Todo/In Progress issue（team filter 已到位）
- [x] Claude backend 能正确 spawn、捕获 session_id、跨 turn resume
- [x] `POST /api/v1/issues/:id/cancel` 可用
- [x] `POST /api/v1/issues/:id/dispatch` 可用
- [x] `POST /api/v1/issues/:id/comment` 可用
- [x] `GET /api/v1/tokens/5h` 返回 token 统计数据
- [x] `/api/v1/state` 返回正确 running 列表（AGE-87 验证通过）
- [x] `./start.sh` 一键启动前后端
- [x] engine 连续运行 30 分钟内不崩溃（已验证通过）
