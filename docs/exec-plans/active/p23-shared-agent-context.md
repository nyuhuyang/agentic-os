# P23 — Shared agent context injection

**状态:** Deferred — 待调研  
**优先级:** P3  
**开始:** —  
**负责人:** yanghu  

---

## 背景

AgenticOS 运行三个 agent（claude / codex / deepseek-tui），但项目记忆只有 Claude 能看到：

- Claude Code 自动加载 `~/.claude/projects/.../memory/MEMORY.md`
- Codex 有 `~/.codex/memories/`，但 runner 不写入
- DeepSeek TUI 只收到 SKILL.md 注入

**结果：** Codex 和 DeepSeek 不知道 P15 进展、已知 bug、agent lock 规则等项目上下文。每次跑都是"第一天上班"。

Runner 已有 SKILL.md prompt 注入模式（`_ai_command()`），但没有扩展到 shared memory。

---

## 待调研问题

在设计之前需要先搞清楚：

1. **Codex `~/.codex/memories/` 机制**  
   - 写入格式是什么？runner 能否直接写入？  
   - Codex exec 是否自动加载这个目录？  

2. **DeepSeek TUI `instructions` / `skills_dir` 注入**  
   - `EngineConfig` 的 `instructions` 字段支持多长的上下文？  
   - 有没有类似 memories 的持久机制，还是只能靠 prompt prepend？  

3. **Claude MEMORY.md 的 token 成本**  
   - 每次 `-p` 调用会把整个 MEMORY.md 加进 context 吗？  
   - 如果 shared context 变大，对三个 agent 的 token 成本影响多少？  

4. **内容分层**  
   - 哪些上下文应该每次都注入（always-on）？  
   - 哪些只在特定 skill 或 task 类型时注入（on-demand）？  

---

## 初步方向（调研后确认）

### 方案 A — Prompt prepend（最简单）

Runner 维护 `knowledge_base/outputs/agent_shared_context.md`，每次构建 prompt 时 prepend 给所有 agent：

```python
# _ai_command() 里
shared_ctx = _load_shared_context()
full_prompt = f"{shared_ctx}\n\n{full_prompt}" if shared_ctx else full_prompt
```

优点：三个 agent 完全统一，无需适配各自格式。  
缺点：每次 run 都多消耗 token；内容变大后代价高。

### 方案 B — 各 agent 原生 memories

- Claude：继续用 `~/.claude/projects/.../memory/`（已有）
- Codex：runner 写入 `~/.codex/memories/`（需调研格式）
- DeepSeek：写入 `instructions` 文件（需调研 EngineConfig）

优点：各 agent 用原生机制，可能有 caching 优化。  
缺点：三套维护成本；内容容易漂移不一致。

### 方案 C — 分层注入

- **Always-on 短摘要**（< 500 tokens）：项目状态、关键规则，prompt prepend 给所有 agent
- **On-demand 详细上下文**：skill 级别，按需注入

---

## 执行计划（调研后填充）

_待调研结果后补充。_

---

## 风险

- shared context 变大 → token 成本线性增长，需要压缩机制
- 各 agent 对 context 格式理解不同（Claude 更擅长 markdown 结构）
- runner 写 `~/.codex/memories/` 可能被 Codex 版本升级破坏

---

## 参考

- P22 Phase 1+2+2b：runner 已注入 knowledge_base memory substrate（`runner/app.py`）
- P15 Phase 1：`_ai_command()` 的 SKILL.md 注入模式，可扩展
- Claude memory 位置：`~/.claude/projects/-Users-yanghu-Documents-AI-Workspace-prototypes-agentic-os/memory/`
- Codex memories 位置：`~/.codex/memories/`
