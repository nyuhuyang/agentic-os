# AgenticOS 技术栈与语言选择（AGE-151）

**日期:** 2026-10-25 · **状态:** 现状说明 + 方向建议

## TL;DR

- **前端不是 PHP。** 浏览器端是原生 JavaScript；页面本身由 Python 的 Jinja2 模板在服务端渲染。没有 React/Vue，没有 npm 构建步骤。
- **后端是 Python。** Flask + Flask-SocketIO，负责 HTTP API、Socket.IO 实时事件、PTY 和 agent 子进程调度。
- **Rust 从来没有做过 AgenticOS 后端。** 仓库里出现过的 Rust 只有第三方 `deepseek-tui` CLI，它在 2026-10-14 被官方 `dsh` 取代。
- **前后端都用 JavaScript 技术上可行，但现在不值得做。** 真要改善前端，优先把前端拆成 TypeScript，不必重写 Python 后端。
- **PHP 依赖为零。** 仓库里没有 `.php` 文件、Composer 配置或 PHP 运行时要求，所以不存在“PHP 最近有问题”的迁移风险。

## 1. 当前实际架构

| 层 | 技术 | 位置 |
|---|---|---|
| Web 服务器 | Python 3.11+、Flask、Flask-SocketIO | `runner/app.py` |
| 页面模板 | Jinja2，服务端渲染 | `runner/templates/index.html` |
| 浏览器端 | HTML + CSS + 原生 JavaScript（ES2020+），无框架、无打包器 | 同上，约 6,200 行、320 KB |
| 第三方浏览器库 | Chart.js 4.4、xterm.js 5.5 + fit addon、Socket.IO client 4.7 | 从 jsDelivr CDN 引入 |
| 通信 | JSON REST + Socket.IO 实时事件 | `runner/app.py` |
| CLI | Python | `runner/run_skill.py`、`runner/usage_reader.py` |
| 本地状态 | JSON / JSONL，原子写入 + 文件锁 | `state/`、`outputs/` |
| Agent 执行 | 外部 CLI 子进程：`claude`、`codex`、`dsh` | `runner/app.py`、`runner/dsh_cli.py` |

补充几点容易混淆的地方：

1. **“前端是 JavaScript”不等于“前端是一个 JS 应用”。** 这里没有独立的 SPA、没有 `package.json`、没有 `ui/` 目录。HTML 由 Flask 渲染，项目自己的 CSS/JS 全部内联在模板里，改完重启 runner 就生效。
2. **页面确实加载 JavaScript 库，但它们是浏览器端的第三方资源。** Chart.js、xterm.js、Socket.IO 通过 CDN 引入，不属于 AgenticOS 的构建产物。
3. **`dsh` 本身是 npm 包，但这不意味着 AgenticOS 的后端是 Node。** 机器上装 Node 是为了运行这个 agent CLI；dashboard 和 runner 仍然是 Python。
4. **没有 SSE。** 运行事件走 Socket.IO；`/api/runs/<id>/events` 返回的是 JSON 快照，不是 `text/event-stream`。

## 2. 为什么现在是这个组合

这个项目的负载形状是“单机、单用户、I/O 密集”：

- 服务器主要做三件事：读写本地 JSON/JSONL、启动和监控外部 CLI、把事件推给浏览器。
- 真正耗时的是 agent 和模型 API，不是 Python 进程本身。
- PTY、`termios`、`fcntl`、`selectors`、`subprocess`、macOS `sandbox-exec`、launchd 这些底层操作，Python 标准库和现有代码已经覆盖得比较完整。
- 没有构建步骤意味着改一个模板不需要 npm install、不用处理 bundler 版本和前端依赖供应链；这对一个本地工具是实际优势。
- 现有 pytest 覆盖了大量进程、会话、worktree、沙箱和状态机细节。重写语言的主要成本不是“把语法翻译过去”，而是重新踩一遍这些边界条件。

单文件模板已经很大，这确实是可维护性问题；但它是**前端组织方式**的问题，不是“Python 不适合做后端”的证据。

## 3. Rust 在项目里的真实位置

- 当前 `runner/` 没有 Rust 代码，也没有 Cargo 依赖。
- 仓库里出现过的 Rust 是第三方 DeepSeek TUI（`deepseek-tui`）。它曾经作为一个 agent backend 被调用，2026-10-14 被官方 `dsh` 替换；历史 session id 只做只读别名，不会再传给新后端。
- P18/P19 等旧计划里参考过 Vibe Kanban（Rust 后端 + TypeScript 前端），但只是借鉴看板 UI，不是引入它的后端。
- Rust 适合的场景是：单二进制分发、目标机器没有 Python、极高的并发或 CPU 密集处理。当前项目是 localhost 上的单用户 dashboard，这三点都不成立。
- 如果将来真的需要 Rust，更合理的是写一个小 sidecar（例如进程/PTY 监管或打包层），而不是把 Flask、状态文件、会话解析和测试体系整体重写。

## 4. “前后端都用 JavaScript”可行吗？

可行。把 Flask 换成 Node（Express/Fastify），Socket.IO 本来就有 Node 服务端，PTY 可以用 `node-pty`，SQLite 可以用 `better-sqlite3`，文件锁和原子写也有对应库。但“能写”不等于“现在值得写”。

| 方案 | 改动范围 | 主要收益 | 主要风险 | 建议 |
|---|---|---|---|---|
| A. 保持 Python + Jinja/原生 JS | 无 | 稳定、零构建、现有测试继续有效 | 单文件继续变大 | **现在采用** |
| B. Python API + 独立 TypeScript 前端 | 只重写浏览器端 | UI 组件化、类型检查、开发体验 | 多一个构建步骤和联调层 | **UI 变复杂后再做** |
| C. Node/TypeScript 全栈 | 前后端都重写 | 一种语言、共享类型 | 重写全部后端语义，风险最高 | 不建议 |
| D. Rust 重写后端 | 全部重写 | 性能、单二进制 | 成本远高于收益 | 不建议 |

方案 C 真正要迁移的东西比看起来多：

- 40 多个路由和它们的错误语义；
- Socket.IO 的连接鉴权、房间、PTY 输出转发；
- `claude` / `codex` / `dsh` 的 argv、环境变量、超时和退出码处理；
- Claude JSONL、Codex SQLite、dsh 压缩会话的读取；
- 项目注册表、worktree、commit/merge、verify harness；
- `fcntl` 锁、原子 JSON 写入、临时文件清理；
- macOS 沙箱 profile、launchd 集成；
- 一整套 pytest 回归用例。

Node 有对应能力，但每一样都需要重新验证。对一个本地单用户工具，这些工作不会带来用户可感知的速度提升。

## 5. 建议的演进路径

**短期（现在）：保持方案 A。**

- 新增功能继续用 Flask + 模板。
- 如果 `index.html` 成为瓶颈，先做低风险的组织调整：把内联 JS 按功能拆成静态 ES module 文件，仍然由 Flask 直接托管，不引入打包器。
- 不要为了“技术栈统一”而重写后端。

**中期（UI 明显变复杂时）：采用方案 B。**

- 保留 Python API、Socket.IO 协议和全部后端测试。
- 新建独立 `ui/`，用 Vite + TypeScript（React 或 Preact 均可），先迁移看板/详情页，旧页面保留为 fallback。
- 用绞杀者模式（strangler）逐屏替换，不做 big-bang 重写。
- 这时“前后端同语言”的收益才真正出现：前端类型可以和后端 JSON 契约对齐。

**只有在出现明确需求时才考虑 C 或 D：**

- 需要把 AgenticOS 作为单二进制分发给没有 Python 的机器：优先考虑打包 Python 或写 Rust sidecar，而不是重写全部业务。
- 需要多用户、远程 worker、真正的并发调度：这是产品形态变化，应该先改架构，不是先换语言。
- 团队里只有 JS 工程师，且 UI 迭代速度成为主要瓶颈：方案 B 足够，仍然不需要换后端。

## 6. 结论

AgenticOS 现在是 **Python 后端 + Jinja2 服务端页面 + 原生 JavaScript**，不是 PHP，也不是 Rust 后端。这个组合和它“单机、单用户、调度本地 agent”的定位是匹配的。

“前后端都用 JavaScript”是一个可选的重构方向，不是能力缺口。最合理的路线是保留 Python 后端，等前端复杂度真的上来后，再把浏览器端独立成 TypeScript 应用；全栈 JS 或 Rust 重写都不应该作为当前的技术目标。
