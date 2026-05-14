# P15 — Fork DeepSeek TUI：给 exec 模式注入 shell/file 工具

**状态:** Pending（长期计划，暂不执行）  
**优先级:** P2  
**开始:** —  
**负责人:** AgenticOS  

---

## 背景

当前 `deepseek exec --yolo --approval-policy auto <prompt>` 在非交互模式下**不提供 shell/file 工具**。Agent 只能返回文字，无法执行 `exec_shell`、`read_file` 等操作。

而交互式 TUI（我当前运行的模式）有完整的工具集：`exec_shell`、`read_file`、`write_file`、`edit_file`、`grep_files`、`list_dir`、`web_search`、`web_fetch`、`apply_patch` 等。

**目标：** Fork DeepSeek TUI，让 `deepseek exec` 命令在非交互模式下也注入工具定义 + tool-calling 循环。

---

## 当前架构

```
deepseek (v0.8.29)  —  Go binary
│
├─ 交互模式（默认）
│   ├─ 读取 AGENTS.md
│   ├─ 注入 TUI 系统提示词（含工具定义）
│   ├─ 运行 tool-calling 循环
│   ├─ 管理 MCP 服务器
│   └─ 会话 checkpoint 持久化
│
└─ exec 模式（子命令）
    ├─ 读取 [ARGS]... 作为 prompt
    ├─ 发送到 API
    ├─ 返回文字响应
    └─ ❌ 无工具定义
       ❌ 无 tool-calling 循环
       ❌ 无 AGENTS.md 上下文
```

---

## 执行计划

### Phase 1 — 调研 TUI 源码

**仓库：** https://github.com/Hmbown/DeepSeek-TUI

**需要回答的问题：**

1. **语言/框架：** TUI 用什么语言写的？从 binary size 和 npm wrapper 推测是 Go 或 Rust。
2. **工具定义在哪：** 交互模式的工具定义（exec_shell, read_file 等）声明在哪个文件？
3. **tool-calling 循环在哪：** 交互模式的 tool-calling 迭代循环在哪实现？
4. **exec 命令入口：** `exec` 子命令的入口在哪里？为什么跳过工具注入？
5. **AGENTS.md 加载：** AGENTS.md 是怎么加载并注入到 system prompt 的？
6. **MCP 服务器：** MCP server 的注册/调用入口在哪？

**完成标准：**
- [ ] 确定源码语言（Go / Rust / 其他）
- [ ] 找到工具定义位置（函数/文件）
- [ ] 找到 tool-calling 循环位置
- [ ] 找到 exec 命令入口
- [ ] 确定 AGENTS.md 加载流程

---

### Phase 2 — Fork + 最小可执行修改

**目标：** 让 `deepseek exec <prompt>` 也能运行工具。

**具体改动（预估）：**

1. **在 exec 命令入口，注入工具定义**
   - 复制交互模式的工具定义到 exec 流程
   - 确保 tools 数组随 `/chat/completions` 请求发送

2. **在 exec 命令入口，加入 tool-calling 循环**
   - 收到含 `tool_calls` 的响应后，执行工具
   - 将工具结果作为附加消息发回
   - 继续循环直到无 tool_calls 或超过最大轮次
   - 最终返回文字输出

3. **支持 AGENTS.md**
   - 在 exec 模式启动时读取 AGENTS.md
   - 注入到 system prompt 中（和交互模式一致）

**完成标准：**
- [ ] `deepseek exec "Run 'date'"` 实际执行 shell 命令
- [ ] `deepseek exec "Read foo.py"` 实际读取文件
- [ ] `deepseek exec "Edit foo.py replace X with Y"` 实际编辑文件
- [ ] `deepseek exec` 输出包含工具执行结果而非模拟
- [ ] `deepseek exec` 读取 AGENTS.md 并注入提示词

---

### Phase 3 — 集成到 AgenticOS

**目标：** 用 fork 版本替换现有 dispatch。

**具体改动：**

1. **安装 fork 版本**
   - `go install github.com/nyuhuyang/DeepSeek-TUI@exec-tools`

2. **验证 `_ai_cli` 调用方式**
   - 确认 `deepseek --yolo --approval-policy auto exec <prompt>` 在 fork 版本中正常工作

3. **更新 dispatch**
   - AgenticOS 中 `deepseek-tui` 选项现在可以正确跑代码 task
   - 保留 `deepseek`（API agent）作为轻量选项

4. **清理**
   - 更新 `AGENTS.md` 中的工具使用指引
   - 移除 `deepseek_agent.py` 的 DEPRECATED 注释或直接删除

**完成标准：**
- [ ] Fork 版本安装并在本地可用
- [ ] AgenticOS dispatch 用 fork 版本跑 task 成功
- [ ] `deepseek` 和 `deepseek-tui` 两个选项都有实际区别

---

## 关键限制

- Fork 必须保持与上游同步（rebase 而非 merge）
- MCP 服务器支持是加分项，不是 Phase 2 必须
- 不要破坏现有交互模式的功能
- 只修改 exec 命令的行为

---

## 参考

- TUI 仓库：https://github.com/Hmbown/DeepSeek-TUI
- 当前 v0.8.29
- npm wrapper：`npm install -g deepseek-tui`
- Go binary：`/opt/homebrew/bin/deepseek`
