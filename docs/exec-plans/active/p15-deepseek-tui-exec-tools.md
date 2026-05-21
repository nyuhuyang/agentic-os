# P15 — DeepSeek TUI exec agent integration

**状态:** Deferred  
**优先级:** P3  
**开始:** —  
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

**目标：** 先升级并适配 upstream DeepSeek TUI 的 `exec --auto --output-format stream-json`。只有最新版仍不能满足真实工具调用或机器可读事件时，才 fork。

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

1. 安装或构建 `deepseek >= 0.8.37`
   - 当前安装方式为 npm wrapper：`npm update -g deepseek`
   - 若 npm 版本滞后，备选：`cargo install deepseek-tui` 或从 GitHub release 下载 binary。
   - 不使用 fork，除非上游版本验证失败。

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

- [ ] 本地 `deepseek --version` 为支持 exec agent 的版本
- [ ] `deepseek exec --help` 暴露 `--auto` 和 `--output-format stream-json`
- [ ] `deepseek exec --auto ...` 实际产生 `tool_use` / `tool_result`
- [ ] shell/file 工具结果来自真实执行，不是模型模拟
- [ ] 输出末尾包含 `metadata` 和 `done`
- [ ] `--auto` sandbox/cwd 语义已验证并记录（与 `--yolo` 差异）

---

### Phase 1 — AgenticOS stream-json adapter

**目标：** 让 runner 把 `deepseek-tui` 当作结构化 CLI agent，而不是纯文本黑盒。

**改动范围：**

主要目标：`runner/modules/backends/deepseek.py`

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

### Phase 2 — Session / retry integration

**目标：** 利用 DeepSeek TUI 的 exec session 能力改善 retry 和 follow-up。

**具体改动：**

1. 首次运行保存 `metadata.session_id`
2. retry 时如果原 run 有 `deepseek_session_id`，优先使用：

```bash
deepseek exec --auto --output-format stream-json --resume <SESSION_ID> <feedback_prompt>
```

3. 如果 session resume 失败，降级为完整 prompt retry。

**完成标准：**

- [ ] 首次 run 保存 DeepSeek session id
- [ ] retry 可用 `--resume` 继续同一 DeepSeek exec session
- [ ] session resume 失败时有清晰错误或自动降级

---

### Phase 3 — Fork fallback（仅在 upstream 不足时执行）

**触发条件：**

- 最新上游 `exec --auto` 不能真实调用工具
- `stream-json` 缺少关键事件或 token/session metadata
- 上游行为无法通过配置或小补丁满足 AgenticOS

**决策截止：** Phase 0 验证结束后 1 周内决定是否进入 Phase 3。若届时上游 PR 无回应且问题未解决，视为触发。

**原则：**

- 不复制交互模式 tool loop。
- 复用上游 `run_exec_agent()` / `spawn_engine()` 路径。
- 尽量向上游提交 PR，减少长期 fork 维护。
- fork 保持 rebase，而不是 merge。

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
- 本机当前版本：v0.8.29
- 上游源码观察版本：v0.8.37
- 本机 binary：`/opt/homebrew/bin/deepseek`
- 关键源码：
  - `crates/cli/src/lib.rs`：dispatcher help / exec passthrough
  - `crates/tui/src/main.rs`：`ExecArgs`、`ExecOutputFormat`、`run_exec_agent()`
  - `crates/tui/src/core/engine.rs`：engine config / tool execution orchestration
  - `crates/protocol/src/lib.rs`：runtime event schema
