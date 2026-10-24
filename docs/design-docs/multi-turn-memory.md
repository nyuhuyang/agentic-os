# 多轮对话记忆：各家做法调研与 AgenticOS 建议（AGE-114）

**日期:** 2026-10-20 · **状态:** Step 0–2 已实现（2026-10-21，`docs/exec-plans/completed/2026-10-21-multi-turn-memory.md`）；Step 3 已实现（runner 启动的 Claude 读 CLAUDE.md + AGENTS.md，2026-10-21） · **相关:** AGE-113（`docs/exec-plans/completed/2026-10-20-switch-agent.md`）、P23（`docs/exec-plans/deferred/p23-shared-agent-context.md`）

## TL;DR

- 业界的记忆分三层：**会话内**（窗口满了就压缩）、**同一任务跨轮**（resume 原会话或 handoff 到新会话）、**跨任务长期**（指令文件 + agent 自写笔记）。
- 我们特殊在：runner 包的是厂商 CLI（claude / codex / dsh），**对话历史存放在各厂商的私有格式里**（Claude JSONL、Codex rollout + 加密压缩块、dsh zstd）。换 agent 时这部分历史无法迁移。能跨 agent 存活的只有两样：**runner 自己的 run 记录链**和**worktree 里的 git 状态**。
- 业界能“换模型不丢记忆”的系统（Aider、OpenHands、Letta）都是 **harness 自己持有对话**，而不是厂商持有。我们的对应物就是 `state/run_log.jsonl` 的 parent 链，目前只用了很小一部分。
- 现状有 3 个具体问题（第 4 节有证据）：
  - F1：同 agent 的普通卡片续接时，会把整段嵌套历史再发一遍。实测一条链嵌套 11 层，prompt 达 25 KB。
  - F2：session 卡片切换 agent 时，只带上一轮的内容加一个原始 transcript 路径；从 dsh 切出时连路径也没有。
  - F3：切换后，如果看板重新派发，可能 resume 旧 agent 的会话，丢掉新 agent 的轮次。
- 建议按 ponytail 原则分三步走，不做 runner 侧 LLM 摘要，不引入记忆服务器：
  1. 续接只发 reply。
  2. 用 run 链确定性地生成 handoff。
  3. 修正切换后的派发目标。
  
  长期记忆（P23）放到最后，先统一 AGENTS.md。

---

## 1. 问题拆分

| 层 | 问题 | 典型机制 |
|---|---|---|
| L1 会话内 | 单个会话超出上下文窗口 | compaction / 清理工具输出 / 子 agent 隔离 |
| L2 同任务跨轮 | 用户回复后，agent 如何知道前面聊了什么 | resume 同一会话；或新会话 + handoff prompt |
| L3 跨任务长期 | 项目规则、用户偏好、踩过的坑 | 指令文件（CLAUDE.md / AGENTS.md）、自写记忆（auto memory、Codex memories） |

**我们的特殊性主要在 L2：**
- 一张卡片的多轮对话中途可能换 agent，比如 Claude 额度用完换 Codex（AGE-113）。
- resume 只对同一厂商有效。
- L1 由各 CLI 自己负责，runner 不需要也不应该介入。

## 2. 各家做法

| 系统 | L1 会话内 | L2 跨轮 / 续接 | L3 长期 | 历史归谁 | 能换模型吗 |
|---|---|---|---|---|---|
| **Claude Code** | 自动 / 手动 `/compact`；压缩后从磁盘重读根 CLAUDE.md 和 auto memory，子目录 CLAUDE.md 要等再次触达才加载 | `--resume <id>` / `--continue`，transcript 存在 `~/.claude/projects/<cwd>/<id>.jsonl` | CLAUDE.md 多级 + `@import`；auto memory：同一仓库所有 worktree 共享，每次加载前 200 行或 25 KB；有 CLAUDE.md 时**默认不读 AGENTS.md** | 厂商 | 否 |
| **Codex CLI** | 自动压缩；OpenAI 模型走远端 `/responses/compact`，返回**不透明的加密块**；压缩时丢弃工具输出 | `codex resume` / `exec resume <id>`，rollout 存在 `~/.codex/sessions/` | AGENTS.md（全局 → git root → 子目录，可用 override）；Memories **默认关闭**：后台把空闲会话提炼到 `~/.codex/memories/`，官方要求把它当生成物，不要手改 | 厂商 | 否 |
| **Gemini CLI** | `/compress`：用结构化摘要替换历史 | `/chat save/resume <tag>` | GEMINI.md 分层；`save_memory` 工具把单条事实追加到 `~/.gemini/GEMINI.md` | 厂商 | 否 |
| **Amp** | **取消 compaction，改用 Handoff** | `/handoff <目标>`：分析当前线程，按新目标生成起始 prompt 和相关文件列表，作为**草稿**交给用户编辑 | AGENTS.md | 厂商 | 线程内 |
| **Cursor** | 内部摘要 | 新 chat 从零开始 | Rules（`.cursor/rules`、AGENTS.md）；自动 Memories 据报道已在 2.1 移除，只剩 Rules | 厂商 | 是（历史由编辑器持有） |
| **Aider** | 超过 `--max-chat-history-tokens` 后，用 weak model 摘要旧历史 | `.aider.chat.history.md` 明文保存，可用 `--restore-chat-history` 恢复 | 约定文件靠 `--read` 加载 | **harness** | **是** |
| **Cline Memory Bank** | — | 每次任务开始读取 `projectbrief / activeContext / progress` 等 markdown 文件 | 同左，文件在仓库里，人和 agent 都能编辑 | 仓库 | 是 |
| **OpenHands** | Condenser：把被遗忘的事件摘要成一条 summary event，可组成多级流水线 | 事件流由 harness 持久化 | microagents / repo 指令 | **harness** | **是** |
| **Letta (MemGPT)** | 溢出的旧消息驱逐到外存 | 常驻 memory blocks，agent 可自己改写 | archival memory，需要 agent 主动检索 | **harness** | **是** |
| **Anthropic 长任务 harness** | 每个会话从新窗口开始 | `claude-progress.txt` + **JSON 功能清单**（只许改 `passes` 字段）+ `init.sh` + git log；会话开始时先读这些再干活 | 同左 | 仓库 | 是 |
| **ESAA-Conversational**（arXiv 2606.23752） | — | 用 hook 把各 agent 的对话写进统一的 `activity.jsonl`；**确定性投影**出 `handoff.md / state.md / decisions.md / tasks.json`，新 agent 从 handoff 冷启动 | decisions 由 agent 显式记录 | **中立日志** | **是**（专为异构 agent 设计；只有定性证据） |

## 3. 共性模式与取舍

1. **手写指令文件（P1）**：每次都加载，最可靠。AGENTS.md 已经是事实上的跨厂商标准，Codex、Amp、Cursor 和新版 Claude Code 都会读。
2. **agent 自写笔记（P2）**：auto memory、`save_memory`、Codex memories、Cline memory bank、NOTES.md。所有厂商都声明这类内容“是上下文，不是规则”，硬性规则要写进 P1。
3. **压缩 / 摘要（P3）**：一定有损失。Anthropic 的建议是先清理工具输出（最轻的压缩），摘要时“先保召回再求精”。Amp 认为它助长冗长发散的线程，已经弃用。
4. **目标导向的 handoff（P4）**：按“下一步要干什么”抽取内容，而不是概括全部历史，并让人审稿。这比 P3 更适合切换场景。
5. **外部状态就是记忆（P5）**：git 历史、进度文件、结构化清单。Anthropic 发现 JSON 比 markdown 更不容易被模型乱改。
6. **harness 持有对话（P6）**：换模型不丢历史的**唯一**通用解。
   - 厂商 CLI 的 transcript 格式私有、会变；Codex 的压缩块甚至不可读；dsh 的是 zstd 压缩。
   - 让新 agent 去读旧 agent 的原始 JSONL（AGE-113 现在的做法）只能兜底：文件大、充满工具噪声、格式各异。

**对我们的启示：**
- L2 的切换问题本质上是 P6，加上 P4 的形状。
- runner 已经有中立日志：每轮的 `prompt / output / agent / agent_session_id / parent_run_id`。再加上 worktree 的 git 状态，相当于 ESAA 方案的简化版，不需要 hook，也不需要新存储。

## 4. 现状（代码与证据）

### 4.1 每一轮带了什么

| 场景 | 命令 | prompt | 代码 |
|---|---|---|---|
| 首轮派发 | 新会话 | `ID: 标题\n\n描述`，加项目规则前缀；**不含 Linear 评论** | `runner/modules/linear/__init__.py:922`、`runner/project_runs.py:104` |
| 普通卡片同 agent 续接 | `--resume` / `exec resume` / `--session-id` | `_handoff_prompt`：上一轮 prompt + 上一轮 output + 回复 | `runner/app.py:5337`、`runner/app.py:3473` |
| session 卡片同 agent 续接 | resume | **只发回复**（§3.5） | `runner/app.py:4424` |
| 切换 agent（两种卡片） | 新会话 | `_handoff_prompt` + `[Agent switch]` + 旧 transcript 路径 | `runner/app.py:5252`、`runner/app.py:5427`、`runner/app.py:4426` |

### 4.2 问题

**F1：普通卡片续接时重复发送嵌套历史，token 消耗是 O(n²)。**
- `_handoff_prompt` 把上一轮的 `prompt` 原样放进 `Original task:`。上一轮的 prompt 本身又包含更早的轮次，于是逐层嵌套。
- 这个 prompt 随后发给一个**已经拥有这些历史**的 resume 会话。
- 实测 `state/run_log.jsonl`：一条链共 15 轮（14 轮 Claude，最后一轮切到 Codex），prompt 从 148 字符涨到 25 875 字符，`Original task:` 嵌套 11 层；另一条链 11 轮，涨到 18 KB。
- 副作用：普通卡片切换时，这个嵌套 prompt **意外**携带了全部轮次的 output。session 卡片只发回复，所以切换时只剩最后一轮。

**F2：session 卡片的切换 handoff 很薄。**
- 这条路径下 `original.prompt` 只是上一条回复，所以 handoff 实际只有“上一条回复 + 上一轮 output + 新回复 + 一个 JSONL 路径”。
- `session_file()` 对 dsh 返回 None（`runner/projects.py:1757`）。从 dsh 切出时，新 agent 拿不到任何更早的上下文，而 runner 自己的 `outputs/logs/<run_id>_stream.jsonl` 明明可读。
- 如果链上切换过多次（A→B→C），只给最后一个会话的路径，A 的路径丢失。
- handoff 没有提示新 agent 去看 `git log` / `git diff`。但 worktree 里的提交才是最可靠的“做过什么”（runner 会自动提交遗留改动，见 `ee36fd5`）。

**F3：切换后，看板重新派发可能回到旧会话。**
- 切换不会更新卡片的 `preferred_agent`。
- 重新派发时，按 `preferred_agent` 加 `_resumable_card_session(issue, backend)` 选会话（`runner/modules/linear/__init__.py:871-900`），会跨 generation 找该 agent 最新的会话。
- 因此，Claude → 切 Codex 聊几轮 → 看板再派发，可能 resume 那个旧 Claude 会话，Codex 的轮次就丢了。
- 这是读代码推断的结论，没有测试覆盖，需要先写测试确认。

**F4：L3 各 agent 看到的规则不一致。**
- Claude Code 在存在 CLAUDE.md 时**默认不读 AGENTS.md**；Codex 只读 AGENTS.md。
- 本仓库这两个文件内容完全不同：CLAUDE.md 是工作区契约，AGENTS.md 是仓库地图和 token 规则。所以 Claude 看不到 AGENTS.md 里的规则，Codex 也看不到 CLAUDE.md 里的。
- auto memory 只有 Claude 能看到；Codex memories 默认关闭；dsh 只拿到 SKILL.md。这正是 P23 描述的问题。

**F5（小）：回复没有单独存字段。**
- run 记录里只有拼好的 `prompt`，回复嵌在里面。要从 run 链重建对话，必须新增 `reply` 字段。旧记录只能尽力解析。

## 5. 建议

按“先删后加、先确定性后 LLM”的顺序排列，每一步都能单独发布。

### Step 0：续接只发回复（修 F1）
- 普通卡片的同 agent resume 和 session 卡片保持一致，只发 `reply + attachments`。`_handoff_prompt` 只在**新会话**时使用（首次换 agent，或 resume 失败后的 fallback）。
- 预期收益：长对话每轮少发几 KB 到几十 KB，CLI 压缩时也不会再被重复内容稀释。
- 风险：resume 失败回退到新会话时（`runner/app.py:5631` 复用同一个 `prompt`）必须改用 handoff prompt，不能只发 reply。

### Step 1：从 run 链确定性地生成 handoff（修 F2、F5）
- run 记录新增 `reply` 字段。
- 新增 `_card_history(run)`：沿 `parent_run_id` 回溯，组装成扁平结构。
  ```text
  Task: <根 prompt>
  Turn 1 (claude): human: … / agent: <output>
  Turn 2 (codex):  human: … / agent: <output>
  …
  Transcripts: <每个出现过的会话的路径；dsh 用 outputs/logs/<run_id>_stream.jsonl>
  Code state: this worktree's branch holds all prior commits; run `git log --oneline main..HEAD` and `git status` first.
  ```
- 预算：最近 K 轮（例如 3 轮）全文，更早的轮次每轮截断到 N 字符（例如 1 500）；总量超过上限（例如 30 KB）时，只保留根任务和最近几轮。
  - `ponytail:` 截断是朴素的启发式，它的上限是会丢掉中间轮次的细节。升级路径：超出预算时再调用一次 LLM 生成 Amp 式“目标导向 handoff”。在此之前**不做**。
- 只有切换 agent 时才用它，替代当前的嵌套 prompt。

### Step 2：切换即改主（修 F3）
- 切换成功后，把卡片的“当前会话”统一为新 agent 的会话：要么更新 `preferred_agent`，要么让重新派发按“卡片最新会话（不分 agent）”来选。
- 先写一个复现测试：Claude → 切 Codex → 看板再派发，断言 resume 的是 Codex 会话。

### Step 3：统一长期记忆（F4 / P23），优先级低
- 最小步：让每个 agent 都能看到同一份规则。
  - 本仓库：把 AGENTS.md 里的通用规则 `@import` 进 CLAUDE.md，或在用户 settings 里设 `claude-md-and-agents-md`。
  - 对 dsh：确认它读不读 AGENTS.md；不读就由 runner prepend（P23 方案 A 的最小版本）。
- 跨 agent 的“学到的东西”：暂缓。
  - Claude auto memory 继续只给 Claude 用。
  - **不**写 `~/.codex/memories/`：官方把它定义为生成物，升级就可能失效。
  - 需要时再加一个仓库内的共享笔记文件（Cline / Anthropic 式），并由 AGENTS.md 引用。

### 明确不做
- runner 侧 LLM 摘要 / 压缩：有损失，要多一次模型调用，而各 CLI 已经在 L1 做了压缩。
- 向量库 / 记忆服务器（mem0、agentmemory、ai-memory）：单机单用户场景过重。
- 把旧 transcript 内联进 prompt：太大、噪声多，保留路径让 agent 按需读取即可。

## 6. 需要用户决定

- [x] Step 0–2：已按默认预算实现并 /verify（用户回复 "continue"，2026-10-21）。
- [x] handoff 预算：采用默认 3 / 1 500 / 30 000 字符（`runner/app.py` `_HANDOFF_*`），可再调。
- [x] Step 3：用户选“改 Claude 的设置让它两个都读”。runner 启动的每个 Claude（headless、项目、交互终端）都带 `--settings '{"pluginConfigs":{"cc-plugin-agents-md@builtin":{"options":{"instructionFiles":"claude-md-and-agents-md"}}}}'`（`runner/project_runs.py` `CLAUDE_SETTINGS`）。实测 Claude Code 2.1.305：带此参数能看到 AGENTS.md 的 “Critical Token Budget Rule”，不带看不到。
  - 例外：机密项目的 Claude 用 `--setting-sources user --strict-mcp-config`（AGE-129，原为 `""`），不加载项目的 CLAUDE.md 和 AGENTS.md，维持原样。
  - runner 之外手动开的 Claude Code 不受影响；要全局生效，需在 `~/.claude/settings.json` 里加同样的 `pluginConfigs`，或在 `/config` 里把 Project instructions 设为 `claude-md-and-agents-md`。

## 来源

- Anthropic: [Effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)
- Anthropic: [Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- Claude Code: [How Claude remembers your project](https://code.claude.com/docs/en/memory)
- Codex: [Memories](https://learn.chatgpt.com/docs/customization/memories?surface=app)
- Codex 压缩细节（第三方）: [Codex CLI context compaction](https://codex.danielvaughan.com/2026/04/16/codex-cli-context-compaction-tuning-long-sessions/)、[How memory works in Codex CLI](https://mem0.ai/blog/how-memory-works-in-codex-cli)
- Gemini CLI: [Memory tool (save_memory)](https://geminicli.com/docs/tools/memory)、[Gemini CLI memory deep dive](https://mer.vin/2025/12/gemini-cli-memory-deep-dive/)
- Amp: [Handoff (No More Compaction)](https://ampcode.com/news/handoff)
- Aider: [Options reference](https://aider.chat/docs/config/options.html)
- Cline: [Memory Bank](https://docs.cline.bot/prompting/cline-memory-bank)
- Cursor（第三方，Memories 移除的说法未经官方证实）: [cursor memory](https://blog.memoryplugin.com/cursor-memory/)、[Rules](https://docs.cursor.com/context/rules)
- OpenHands: [Condenser](https://docs.openhands.dev/sdk/arch/condenser.md)
- Letta: [Agent memory](https://docs.letta.com/guides/agents/memory)
- [ESAA-Conversational（arXiv 2606.23752）](https://arxiv.org/pdf/2606.23752)
- 跨厂商记忆服务器（未验证）: [ai-memory](https://github.com/akitaonrails/ai-memory)、[agentmemory](https://github.com/rohitg00/agentmemory)
