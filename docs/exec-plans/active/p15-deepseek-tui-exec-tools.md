# P15 — DeepSeek TUI exec agent integration

**状态:** Phase 0 完成；Phase 1+2 待实现 (2026-05-21)  
**优先级:** P3  
**开始:** 2026-05-20  
**负责人:** yanghu  

---

## 背景

AgenticOS 需要 `deepseek-tui` 像 Claude Code / Codex 一样作为可观测的 CLI agent：能真实调用 shell/file/MCP 工具，能输出机器可读事件，能记录 token/model/session，并能被 UI 展示进度。

当前本机安装的 `deepseek` 是 v0.8.29。这个版本的 `deepseek exec --help` 只暴露 `[ARGS]...`，AgenticOS 现在也只是用黑盒 subprocess 调用：

```bash
deepseek --yolo --approval-policy auto exec <prompt>
```

这导致 runner 只能拿到最终 stdout/stderr，无法稳定解析工具调用、token、模型、session 或进度。

上游 DeepSeek TUI 当前源码已经发展到 v0.8.37，并且 `exec` 已经支持 agentic backend integration：

```bash
deepseek exec --auto --output-format stream-json "fix this bug"
deepseek exec --resume <SESSION_ID> "follow up"
```

源码中 `crates/tui/src/main.rs` 的 `run_exec_agent()` 已经走 TUI engine，构造 `EngineConfig`，注入 `mcp_config_path`、`skills_dir`、`instructions`、project context、shell allow，并输出 `tool_use`、`tool_result`、`metadata`、`done` 等 NDJSON 事件。

**目标：** 直接在本地 source 上改。DeepSeek-TUI v0.8.39 已下载至 `prototypes/DeepSeek-TUI/`，这是主要改动源。先验证 `exec --auto --output-format stream-json` 是否满足需求；不足时在此 source 上直接 patch 并 build。

### 与其他 plan 的关系

symphony-ts（P17）已废弃。P15 主要改动范围：`runner/modules/backends/deepseek.py`（Python runner）。

---

## 当前判断

```
本机 deepseek v0.8.29
└─ exec 模式
   ├─ help 面只显示 [ARGS]...
   ├─ AgenticOS 当前按纯文本 subprocess 处理
   └─ 对 runner 来说不可观测：无结构化 tool events / usage / session

上游 DeepSeek TUI v0.8.37
└─ exec 模式
   ├─ --auto：启用 agentic mode + tool access
   ├─ --output-format stream-json：输出 NDJSON 事件
   ├─ --json：输出 summary JSON
   ├─ --resume / --session-id / --continue：支持非交互续跑
   ├─ run_exec_agent() 复用 TUI engine
   └─ metadata 包含 model / input_tokens / output_tokens / session_id / status
```

---

## 执行计划

### Phase 0 — 升级验证（不 fork）

**目标：** 先确认新版 DeepSeek TUI 是否已经解决 P15 原始问题。

**步骤：**

1. 构建本地 source
   - Source：`prototypes/DeepSeek-TUI/`（v0.8.39）
   - Build：`cd prototypes/DeepSeek-TUI && cargo build --release`
   - Binary：`target/release/deepseek`；可软链至 `/opt/homebrew/bin/deepseek` 替换旧版
   - npm wrapper 已过时（v0.8.29），不再依赖。

2. 验证 CLI surface

```bash
deepseek --version
deepseek exec --help
```

`exec --help` 应出现：

```text
--auto
--json
--resume
--session-id
--continue
--output-format <FORMAT>
stream-json
```

3. 验证真实工具调用

```bash
deepseek exec --auto --output-format stream-json "Run date and report the result."
deepseek exec --auto --output-format stream-json "Read runner/app.py and summarize _ai_cli."
```

4. 验证 `--auto` sandbox 语义

```bash
deepseek exec --auto --output-format stream-json "Write a file /tmp/p15-test.txt with content 'ok'"
```

确认：工具调用限制在 cwd / project context；不写入 `/tmp` 或系统目录之外。与旧 `--yolo --approval-policy auto` 行为对比记录。

**完成标准：**

- [x] 本地 `deepseek --version` 为支持 exec agent 的版本
- [x] `deepseek exec --help` 暴露 `--auto` 和 `--output-format stream-json`
- [x] `deepseek exec --auto ...` 实际产生 `tool_use` / `tool_result`
- [x] shell/file 工具结果来自真实执行，不是模型模拟
- [x] 输出末尾包含 `metadata` 和 `done`
- [x] `--auto` sandbox/cwd 语义已验证并记录（与 `--yolo` 差异）

---

### Phase 1 — AgenticOS stream-json adapter

**目标：** 让 runner 把 `deepseek-tui` 当作结构化 CLI agent，而不是纯文本黑盒。

**改动范围：**

主要目标：`runner/modules/backends/deepseek.py`

> **已知 Bug（顺带修）：** `runner/app.py` `_ai_cli("claude")`（line ~1459）缺少 `--verbose` flag。
> `--output-format stream-json` 在 Claude CLI 中必须搭配 `--verbose` 才能输出事件流，否则报错：
> `Error: When using --print, --output-format=stream-json requires --verbose`
> 修复：在 `_ai_cli` 返回值中加入 `"--verbose"`。

**具体改动：**

0. 运行时版本检测

dispatch 入口检查版本，不满足直接 fail fast：

```python
result = subprocess.run(["deepseek", "--version"], capture_output=True, text=True)
# 期望输出含 "v0.8.3x" 或更高；低于 0.8.37 → raise RuntimeError with upgrade hint
```

错误信息应包含 `npm update -g deepseek` 升级指令。

1. 更新 `deepseek-tui` 命令

当前：

```bash
deepseek --yolo --approval-policy auto exec <prompt>
```

目标：

```bash
deepseek exec --auto --output-format stream-json <prompt>
```

是否保留顶层 `--yolo` 需要用新版实际行为验证；不要同时假设旧版 flags 和新版 `--auto` 语义完全等价。

2. 解析 NDJSON 事件

需要支持的事件：

```text
content
tool_use
tool_result
session_capture
metadata
done
error
```

3. 写入 run log — 映射至 P22 telemetry schema

`_write_run_log()` 字段映射（`runner/app.py:1245`）：

| DeepSeek `metadata` 字段 | `_write_run_log` 参数 |
|---|---|
| `model` | `model` |
| `input_tokens` | `input_tokens` |
| `output_tokens` | `output_tokens` |
| `session_id` | 写入 run log `extra` 或单独字段 |
| `status` | 映射至 `status`（success / error / timeout） |

`agent` 固定写 `"deepseek-tui"`（区分 API agent `"deepseek"`）。

4. Timeout 对齐

streaming subprocess 超时使用 `AI_RUN_TIMEOUT_S`（`runner/app.py:144`，默认 1800s）。超时时 status 写 `"timeout"`，与其他 agent 一致。

5. UI 进度

- `tool_use` -> `run_progress`：显示工具名和参数摘要
- `tool_result` -> `run_progress`：显示工具完成状态
- `content` -> 累积最终 output
- `error` -> 写入 run error

**完成标准：**

- [ ] dispatch 入口有版本检测，< 0.8.37 fail fast with upgrade hint
- [ ] `deepseek-tui` run log 记录 `agent=deepseek-tui`
- [ ] run log 记录 `model`、`input_tokens`、`output_tokens`（映射 P22 schema）
- [ ] run log 记录 `session_id`
- [ ] streaming subprocess 超时使用 `AI_RUN_TIMEOUT_S`，status 写 `"timeout"`
- [ ] UI 能看到工具开始/完成进度
- [ ] 最终 output 不混入原始 NDJSON 噪音
- [ ] `deepseek` API agent 和 `deepseek-tui` CLI agent 仍有明确区别

---

### Phase 2 — Session lock + resume（三个 agent 全部）

**目标：** task 在 `in_progress` / `in_review` 期间，强制同一 agent 续接会话。只有打回 `todo` 时才允许换 agent。

#### 2a — Session ID 提取（每个 agent 的来源）

| Agent | Session ID 来源 | Resume 命令 |
|---|---|---|
| `claude` | 任意 event 的 `session_id` 字段 | `claude -p --resume <session_id> ...` |
| `codex` | `thread.started` event 的 `thread_id` | `codex exec resume <thread_id> <prompt>` |
| `deepseek-tui` | `metadata` event 的 `session_id` | `deepseek exec --auto --resume <session_id> <prompt>` |

首次 run 完成后，将 session id 写入 run log（需在 `_write_run_log` 加 `agent_session_id` 字段）。

#### 2b — Agent 锁定规则（runner state machine）

```
task status: todo        → agent 可以自由选择
task status: in_progress → agent 锁定为首次 run 使用的 agent；retry 必须用 --resume
task status: in_review   → agent 锁定；follow-up feedback 必须用 --resume
task status: todo        ← 打回时解锁 agent，允许换 agent 重新开始（不用 --resume）
```

实现要点：
- run log 的 `task_id` 已存在，用它关联同一 task 的多次 run
- 首次 run 写入 `agent` + `agent_session_id` 到 run log
- retry / follow-up 时查找同 `task_id` 最近一次 run，读取 `agent` 和 `agent_session_id`
- 若 task status 为 `in_progress` 或 `in_review`，强制使用已锁定 agent + `--resume`
- 若 session resume 失败（agent 报错），降级为同 agent 全量 prompt retry（不换 agent）
- 只有 UI 显式将 task 打回 `todo` 时，清空 agent 锁定

#### 2c — Resume 失败降级策略

```
resume 失败
  └─ 同 agent 全量 prompt retry（不换 agent，不带 --resume）
       └─ 仍失败 → 状态留 in_progress，提示用户打回 todo 换 agent
```

**完成标准：**

- [ ] `_write_run_log` 新增 `agent_session_id` 字段
- [ ] claude: `system` event 提取 `session_id` 写入 run log
- [ ] codex: `thread.started` event 提取 `thread_id` 写入 run log
- [ ] deepseek-tui: `metadata` event 提取 `session_id` 写入 run log
- [ ] task 在 `in_progress` / `in_review` 时，runner 拒绝切换 agent
- [ ] retry 自动带 `--resume <agent_session_id>`
- [ ] resume 失败时降级为同 agent 全量 retry，不自动换 agent
- [ ] task 打回 `todo` 时 agent 锁定解除

---

### Phase 3 — Fork fallback（仅在 upstream 不足时执行）

**触发条件：**

- 最新上游 `exec --auto` 不能真实调用工具
- `stream-json` 缺少关键事件或 token/session metadata
- 上游行为无法通过配置或小补丁满足 AgenticOS

**决策截止：** Phase 0 验证结束后 1 周内决定是否进入 Phase 3。

**原则：**

- Source 在 `prototypes/DeepSeek-TUI/`，直接改，不需要 fork 流程。
- 不复制交互模式 tool loop。
- 复用 `run_exec_agent()` / `spawn_engine()` 路径。
- 如有价值可向上游提 PR，但不是必须。

**可能改动：**

- 补齐 exec NDJSON event schema
- 补齐 metadata 字段
- 暴露更稳定的 `--auto` / `--output-format stream-json` help
- 为 backend integration 添加回归测试

**完成标准：**

- [ ] fork 只包含 upstream 不接受或尚未发布的最小 patch
- [ ] `deepseek exec --auto --output-format stream-json` 通过 AgenticOS smoke
- [ ] 有上游同步策略

---

## 风险与注意事项

- `--auto` / `--yolo` 语义需要验证是否等价：Elixir 版用 `--yolo --approval-policy never`，新版用 `--auto`，不要假设完全等价。
- `--auto` / `--yolo` 会自动批准工具调用，必须确认 sandbox 和 cwd 语义。
- 不要把 API agent `deepseek` 和 CLI agent `deepseek-tui` 混为一条路径。
- 不要依赖纯文本 stdout 格式；只依赖 JSON/NDJSON 事件。
- 版本检测必须清晰，否则 v0.8.29 会继续表现为黑盒。
- MCP 支持是增强项，不是 Phase 1 的必要条件。
- 不能改变 run status closed set。

---

## 参考

- TUI 仓库：https://github.com/Hmbown/DeepSeek-TUI
- 本地 source：`prototypes/DeepSeek-TUI/`（v0.8.39）
- npm wrapper（已废弃）：v0.8.29
- 构建后 binary：`prototypes/DeepSeek-TUI/target/release/deepseek`
- 关键源码：
  - `crates/cli/src/lib.rs`：dispatcher help / exec passthrough
  - `crates/tui/src/main.rs`：`ExecArgs`、`ExecOutputFormat`、`run_exec_agent()`
  - `crates/tui/src/core/engine.rs`：engine config / tool execution orchestration
  - `crates/protocol/src/lib.rs`：runtime event schema
