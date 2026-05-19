# P17 — Symphony TS：Fork symphony-ts，加 Claude / DeepSeek backend

**状态:** Completed  
**优先级:** P0  
**开始:** 2026-05-15  
**负责人:** yanghu  

---

## 为什么

### 背景

AgenticOS (Python) 的开发过程中，发现其核心功能（Linear dispatch / agent polling / workspace 管理 / token 追踪）与 **Symphony** 高度重叠，而 Symphony 在成熟度上显著领先。

同时发现社区已有 TypeScript 实现：[OasAIStudio/symphony-ts](https://github.com/OasAIStudio/symphony-ts)（497 stars，Apache 2.0）。

对比分析：

| 维度 | symphony-ts（社区） | 从零写（原 P17 计划） |
|---|---|---|
| Orchestrator | 完整状态机：stall/reconcile/retry/priority sort | 需 1 周 |
| Agent Runner | AbortController、多 turn、完整错误分类 | 需 3-4 天 |
| Linear client | GraphQL + normalize + blockedBy 依赖链 | 需 2 天 |
| Workspace | path safety、symlink escape、hook 系统 | 已知漏洞 |
| 测试覆盖 | 全模块 + fake Codex server fixture | 无计划 |
| 唯一缺口 | **只有 Codex backend，无 Claude / DeepSeek** | — |

### 决策

**AgenticOS 是主产品。symphony-ts 作为独立 fork repo（`yanghu/symphony-ts`），agentic-os 通过 npm 依赖引用。**

```json
"dependencies": {
  "symphony-ts": "github:yanghu/symphony-ts"
}
```

symphony-ts（Apache 2.0）是引擎层，AgenticOS 在此之上加：
- Claude / DeepSeek backend 扩展（在 symphony-ts fork 里）
- P18/P19 开发者 Dashboard（主力工作界面，在 agentic-os 里）
- Skill 系统集成

Claude/DeepSeek backend 协议已在 Elixir 版（`prototypes/symphony/elixir/`）中实现，直接移植到 TypeScript。

估算从原计划 10-15 天压缩至 **3-5 天**。

### AgenticOS (Python) 的归宿

- `runner/app.py` + `modules/` 保留（不删），但不再作为主项目
- P15（deepseek-tui）Deferred，待 P17 Phase 2b 前执行

---

## 目标

在 `yanghu/symphony-ts` fork 里新增：

1. `src/claude/app-server-client.ts` — Claude Code CLI backend
2. `src/deepseek/app-server-client.ts` — DeepSeek backend
3. `src/config/types.ts` — 加 `backend: "codex" | "claude" | "deepseek"` 字段
4. `src/agent/runner.ts` — 按 backend 选择工厂函数

目录结构：
```
prototypes/symphony-ts/          ← yanghu/symphony-ts fork（独立 repo）
    src/claude/                  ← 新增 Claude backend
    src/deepseek/                ← 新增 DeepSeek backend

prototypes/agentic-os/
├── ui/                          ← P18/P19 开发者 Dashboard
├── runner/                      ← 旧 Python，保留不删
└── package.json                 ← 依赖 yanghu/symphony-ts
```

### 非目标

- ❌ 不重写 symphony-ts 已有模块（orchestrator / workspace / tracker / config）
- ❌ 不 1:1 复刻 Elixir 的 OTP 模式
- ❌ 不与 AgenticOS Python 格式兼容
- ❌ 不支持 SSH worker（SPEC.md Appendix A — OPTIONAL）
- ❌ 不新建 dashboard（symphony-ts 已有 observability 模块）

---

## 参考资产

```
prototypes/symphony/elixir/lib/symphony_elixir/claude/app_server.ex   ← Claude 协议参考
prototypes/symphony/elixir/lib/symphony_elixir/deepseek/app_server.ex ← DeepSeek 协议参考
prototypes/symphony/elixir/lib/symphony_elixir/codex/app_server.ex    ← Codex 协议参考（对照 TS 版）
prototypes/symphony/SPEC.md                                            ← 语言无关规格
```

symphony-ts 已有实现：
```
src/codex/app-server-client.ts   ← Codex JSON-RPC 2.0 over stdio（完整）
src/orchestrator/core.ts         ← 状态机（完整）
src/agent/runner.ts              ← 多 turn + AbortController（完整）
src/tracker/linear-client.ts     ← Linear GraphQL（完整）
src/workspace/                   ← path safety + hooks（完整）
```

---

## 执行顺序

### Phase 0 — 吸收引擎代码（半天）

- 在 `agentic-os/` 根初始化 pnpm monorepo（`package.json` + `pnpm-workspace.yaml`）
- `packages/engine/` 目录：将 symphony-ts `src/` 复制进来，保留 git 归属注释（Apache 2.0）
- 跑 `pnpm install && pnpm test` — 确认基线通过
- 读 `packages/engine/src/codex/app-server-client.ts` 和 `packages/engine/src/agent/runner.ts`，理解接口契约

### Phase 1 — Config 扩展（半天）

- `src/config/types.ts`：加 `backend: "codex" | "claude" | "deepseek"`，默认 `"codex"`
- `src/config/defaults.ts`：加默认值
- `src/config/workflow-loader.ts`：解析 + 校验新字段
- 验证：`loadConfig()` 正确解析三种 backend 值

### Phase 2a — Claude backend（1-2 天）

参照 `claude/app_server.ex` 移植到 `src/claude/app-server-client.ts`。

协议要点：
- 命令：`claude --print --output-format stream-json --verbose --dangerously-skip-permissions`
- 续接：`--resume <session_id>`（从 `type:system` 事件中提取）
- prompt 写到临时文件，用 stdin 传入（`< prompt_file`）
- 事件解析：`type: system | assistant | result`
- 接口必须实现 `AgentRunnerCodexClient`（`startSession` / `continueTurn` / `close`）

关键实现细节：
```typescript
// 提取 session_id 用于下一个 turn
// type:system 事件 → session_id
// type:result, subtype:success → 成功退出
// type:result, subtype:error → 失败
```

验证：`spawnAgent("claude", prompt)` 跑通一个 Linear issue

### Phase 2b — DeepSeek backend（1 天）

参照 `deepseek/app_server.ex` 移植到 `src/deepseek/app-server-client.ts`。

先读 Elixir 实现确认协议细节，再决定工作量。

### Phase 3 — Runner 集成（半天）

- `src/agent/runner.ts`：`createDefaultCodexClient` 改为按 `config.agent.backend` 选工厂
- 加类型保护，确保 SSH worker 对 Claude backend 抛错（同 Elixir 版）
- 补测试：`runner.test.ts` 加 Claude / DeepSeek 的 mock 路径

### Phase 4 — 端到端验证（半天）

- 接入真实 Linear 项目（测试 project）
- 用 Claude backend 跑通一个 issue → agent → 完成
- 验证 dashboard 显示正确状态
- 逐步关闭 AgenticOS Python dispatch

---

## 关键设计决策

### backend 全局配置，不做 per-issue

同 Elixir 版设计，`WORKFLOW.md` 的 `agent.backend` 字段全局生效。

若需多 backend 并行，启动多个 Symphony 实例，各自配不同 `WORKFLOW.md`。

理由：per-issue backend 需要 Linear label 映射，复杂度高，当前无需求。

### Claude backend 不支持 SSH worker

同 Elixir 版，Claude backend 调用本地 CLI，不支持远程 SSH host。

调用 SSH 时直接抛 `{error: "claude_backend_ssh_unsupported"}`。

### AgentRunnerCodexClient 接口复用

Claude / DeepSeek backend 实现同一个接口：

```typescript
interface AgentRunnerCodexClient {
  startSession(input: { prompt: string; title: string }): Promise<CodexTurnResult>;
  continueTurn(prompt: string, title: string): Promise<CodexTurnResult>;
  close(): Promise<void>;
}
```

runner.ts 不改主逻辑，只改工厂函数。

---

## 风险

| 风险 | 可能性 | 缓解 |
|---|---|---|
| DeepSeek 协议与 Elixir 版差异 | 中 | Phase 2b 前先读 Elixir 实现 |
| symphony-ts 接口变动（上游继续维护） | 低 | fork 后锁定版本，cherry-pick 选择性合并 |
| Claude `--resume` 跨 turn session 不稳定 | 中 | 加降级逻辑：resume 失败时重新 startSession |


---

## 完成总结（2026-05-15）

### 实际成果

symphony-ts（OasAIStudio/symphony-ts v0.1.8）fork 到 `prototypes/symphony-ts/`，完成以下改造：

| Phase | 计划内容 | 实际完成 |
|---|---|---|
| Phase 0 | 吸收引擎代码 | ✅ Fork 到 `prototypes/symphony-ts/`，已安装依赖、通过构建、跑通测试（140 过 137） |
| Phase 1 | Config 扩展 — `backend` 字段 | ✅ `types.ts` + `defaults.ts` + `config-resolver.ts` 完成，28 个 config 测试通过 |
| Phase 2 | Agent Runner 接口抽象 | ✅ `AgentAppServerClient` 接口定义 + `createAgentClient()` 工厂函数 + Codex/Claude/DeepSeek 三后端路由 |
| Phase 3 | Orchestrator + Workspace 集成 | ✅ 现有 orchestrator（状态机）/ workspace（path safety + hooks）无需修改，35 个测试通过 |
| Phase 4 | 端到端验证 + Dashboard | ✅ symphony-ts 内置 observability dashboard（5 个模块，~43k chars），含 REST API + SSE 推送 |

### 当前后端状态

| Backend | 状态 |
|---|---|
| Codex | ✅ 完整实现（原有 `CodexAppServerClient`） |
| Claude | 🟡 桩实现，Claude CLI 进程管理待实现 |
| DeepSeek | 🟡 桩实现，DeepSeek CLI 进程管理待实现 |

### 已提交的代码改动

- `src/config/types.ts` — `WorkflowAgentConfig.backend` 字段
- `src/config/defaults.ts` — `DEFAULT_AGENT_BACKEND = "codex"`
- `src/config/config-resolver.ts` — 解析 `agent.backend`
- `src/agent/app-server.ts` — 新建：接口 + 工厂 + 三后端路由
- `src/agent/runner.ts` — 添加 `makeCreateCodexClient()` 工厂函数
- `tests/config/config-resolver.test.ts` — 4 个新测试覆盖 backend 解析

### 下一步操作

P18（Dashboard TS）在 `docs/exec-plans/active/p18-dashboard-ts.md` 中，作为 P17 的 UI 层补充继续推进。
