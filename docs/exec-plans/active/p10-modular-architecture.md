# P10 — 模块化架构：可插拔模块系统

**状态:** Active  
**优先级:** P0  
**开始:** 2026-05-12  
**负责人:** AgenticOS

---

## 目标

将 AgenticOS 从单块架构改造为模块化系统。每个功能模块可以独立安装、加载或禁用，无需修改核心代码。缺失依赖（如 `LINEAR_API_KEY`、`OPENAI_API_KEY`、特定 model 后端）时系统优雅降级而非崩溃。

---

## 为什么现在做

- `runner/app.py` 已膨胀到 100K+ — 单文件，所有功能耦合在一起
- Linear 集成硬编码：没有 `LINEAR_API_KEY` 时轮询线程空转（浪费资源），没有备用方案
- Speech-to-Text 只支持 OpenAI Whisper：没有 `OPENAI_API_KEY` 就直接 400 错误
- Agent 后端（Claude/Codex/DeepSeek）虽然部分可独立存在，但没有统一的模块注册机制
- 无法只安装部分模块（比如只用 Claude 不用 Codex 和 DeepSeek，或反之）
- 前端渲染完全不知道后端有哪些能力可用 — 经常出现空面板
- **Symphony**（外部 Elixir 协调器）和 **Symphony/Elixir** 需要与 agentic-os 共享相同的 `agent.backend` 配置。当前两个系统各自独立实现 Agent 后端选择逻辑，容易不同步。Symphony 需要通过 agentic-os 的 API 发现可用后端
- **新的外部模块来源**（Maker 的设备控制、CIC、MCP 服务等）正在变得越来越多

---

## 设计原则

1. **按功能分拆，不分文件** — 每个功能是一个逻辑模块（Python 类），可以包含路由、SocketIO 事件、后台线程
2. **边加载边检测** — 模块注册时自动检测依赖（API key、环境变量、已安装包），不具备条件时标记为 `disabled` 并记录原因
3. **优雅降级** — 缺少 Linear → 用本地任务文件（`state/tasks.json`）。缺少 OpenAI STT → 只用浏览器 Web Speech API。缺少 DeepSeek key → Claude/Codex 仍然正常工作
4. **前端感知** — 每个模块向 `/api/capabilities` 报告自身可用性，前端动态隐藏/禁用对应 UI 元素
5. **零侵入核心** — `runner/core/` 保持最小依赖，不引用任何模块代码。模块通过注册 API 挂载

---

## 模块分类

```
agentic-os/
├── runner/
│   ├── app.py                    # 薄启动器 — 加载模块、启动 server
│   ├── core/
│   │   ├── __init__.py           # 核心基础设施
│   │   ├── module_registry.py    # [新] 模块注册表 — 注册/加载/列举/能力检测
│   │   └── features.py           # [新] 功能检测工具（env var、包、可执行文件）
│   ├── modules/
│   │   ├── __init__.py           # [新] 模块自动发现入口
│   │   ├── linear/
│   │   │   ├── __init__.py       # [新] Linear 集成模块
│   │   │   └── local_tracker.py  # [新] 本地任务跟踪（Linear 的降级替代）
│   │   ├── stt/
│   │   │   ├── __init__.py       # [新] 语音转文字模块
│   │   │   └── backends/         # [新] 各 STT 后端（OpenAI、浏览器、本地）
│   │   ├── backends/
│   │   │   ├── __init__.py       # [新] Agent 后端自动发现
│   │   │   ├── claude.py         # [新] Claude 后端模块
│   │   │   ├── codex.py          # [新] Codex 后端模块
│   │   │   └── deepseek.py       # [新] DeepSeek 后端模块
│   │   └── pty/
│   │       └── __init__.py       # [新] PTY 终端模块
│   ├── linear_client.py          # 保留 — 仅 Linear GraphQL 客户端
│   ├── deepseek_monitor.py       # 保留 — 已经是独立模块
│   ├── usage_reader.py           # 保留 — 已经是独立模块
│   └── run_skill.py              # 保留 — 已经是独立模块
```

---

## 执行顺序

```
Phase 1 (模块注册表) → Phase 2 (Linear 模块化) → Phase 3 (Agent 后端模块化 + Symphony 兼容)
→ Phase 4 (STT 模块化) → Phase 5 (前端动态渲染) → Phase 6 (拆分 app.py)
```

Symphony/Elixir 兼容性作为 Phase 3 的子任务（3a/3b/3c）与 Agent 后端模块化同时推进，不单独设为阶段。

每一阶段都是可独立交付的增量 — 完成后立即合并，不等待后续阶段。

---

## Phase 1 — 模块注册表核心

**核心功能:** 注册、加载、列举模块，能力检测，优雅降级

### ModuleRegistry 接口

```python
class AgenticModule(ABC):
    """所有模块的基类。"""
    name: str                      # 唯一模块名，如 "linear"
    label: str                     # 显示标签，如 "Linear Issues"
    dependencies: list[str]        # 依赖的 Python 包名
    required_env: list[str]        # 必要的环境变量名
    requires: list[str]            # 依赖的其他模块名

    def check_capabilities(self) -> dict:
        """检测该模块是否可以加载。
        返回 {"available": True/False, "reason": "..."}
        """

    def register_routes(self, app: Flask):
        """注册 Flask 路由蓝图。"""

    def register_socketio(self, socketio: SocketIO):
        """注册 SocketIO 事件。"""

    def start_background(self, app: Flask, socketio: SocketIO):
        """启动后台线程（如有）。返回 daemon thread 列表。"""

class ModuleRegistry:
    modules: dict[str, AgenticModule]
    capability_cache: dict[str, dict]

    def register(self, module: AgenticModule): ...
    def load_all(self) -> list[str]:        # 返回已加载模块名列表
    def is_available(self, name: str) -> bool: ...
    def get_capabilities(self) -> dict:     # 用于 /api/capabilities
    def discover(self, path: str | None = None):  # 自动发现 module 目录
```

### Feature Detection 工具

```python
def has_env(name: str) -> bool: ...
def has_package(name: str) -> bool: ...
def has_executable(name: str) -> bool: ...
def has_api_key(env_var: str) -> bool: ...
```

### 完成标准

- [ ] `ModuleRegistry` 能注册和列举模块
- [ ] 每个模块独立调用 `check_capabilities()` 检测可用性
- [ ] `/api/capabilities` 返回所有模块状态
- [ ] 缺少依赖时模块标记为 `disabled`，系统仍然正常启动

---

## Phase 2 — Linear → 可插拔模块 + 本地任务跟踪

**改造:** 将 Linear 集成从 `app.py` 中提取为独立模块，提供本地任务跟踪作为降级方案

### LinearModule (`runner/modules/linear/__init__.py`)
- 将 `_linear_polling_loop`、`_linear_dispatch_issue`、`_push_linear_state_async`、`_post_linear_comment` 全部移入模块
- 注册路由 `/api/issues`、`/api/issues/<id>`、`/api/issues/<id>/update`、`/api/projects`、`/api/teams`
- 模块检测：`LINEAR_API_KEY` 环境变量 + `tracker.kind == "linear"` workflow config

### LocalTracker (`runner/modules/linear/local_tracker.py`)
- 无 `LINEAR_API_KEY` 时自动启用
- 所有任务数据存到 `state/tasks.json`（结构化 JSON，同 Linear 的 `_normalize_linear_issue` 格式）
- 支持：创建、更新状态、列举、删除
- 无后台轮询（不需要 — 没有外部变更）

### 前端变化
- 顶部显示 "Linear" 或 "Local Tasks" 标签
- Linear 特有 UI（board view、拖拽）在 Local 模式下隐藏
- Job Board 在两种模式下都能正常工作

### 完成标准

- [ ] 无 `LINEAR_API_KEY` 时 Linear 模块标记为 `disabled`
- [ ] 无 Linear 时本地任务跟踪自动启用
- [ ] 前端 board 在两种模式下正常运行
- [ ] 有 Linear 时功能和现在完全一致（回归测试）

---

## Phase 3 — Agent 后端模块化

**改造:** 每个 Agent 后端为独立模块，可单独安装/加载

### ClaudeModule
- 检测：`~/.claude/` 存在 + `claude` 命令可用
- 提供：dispatch、usage reading、rate limit 显示
- 路由：原 Claude 相关 `/api/*` 路由

### CodexModule
- 检测：`~/.codex/` 存在 + `codex` 命令可用
- 提供：dispatch、usage reading
- 同 Claude

### DeepSeekModule
- 检测：`DEEPSEEK_API_KEY` 存在
- 提供：dispatch、usage monitoring、balance 显示
- 路由：DeepSeek 特有路由（balance、usage）

### 统一 UsageReader 接口
- `ClaudeUsageReader`、`CodexUsageReader`、`DeepSeekUsageReader`
- 都遵循 `read(days: int) -> dict` 签名
- 前端 `/api/windows?agent=<name>` 自动选择正确的 reader

### 完成标准

- [ ] 三个 Agent 后端都是独立模块
- [ ] 只在一个模块可用时，dashboard 不会显示其他 module 的空面板
- [ ] `/api/windows` 自动映射到已加载的 agent 模块
- [ ] 切换 agent 时只显示该 agent 的数据

---

## Phase 4 — STT 多后端故障转移

**改造:** Speech-to-Text 从 OpenAI-only 迁为多后端模块

### STT Backends
1. **Browser Web Speech API** — 免费、不需要 API key、浏览器原生（已在前端代码中）
2. **OpenAI Whisper** — 需要 `OPENAI_API_KEY`
3. **WhisperCPP（未来）** — 需要本地 whisper 模型文件，离线可用

### 降级链
- 选择 "浏览器 STT" → 直接调用 Web Speech API（无需后端）
- 选择 "OpenAI" → 检测 `OPENAI_API_KEY`
  - 有 → 调用 `/api/stt`
  - 无 → 提示 "未配置 OpenAI API key，请先设置 OPENAI_API_KEY"
- （未来）选择 "本地 Whisper" → 检测 whisper-cpp 可执行文件

### 完成标准

- [ ] STT 模块在后端注册，检测 `OPENAI_API_KEY`
- [ ] 无 key 时前端 STT 选择下拉不显示 "OpenAI" 选项（或显示并 disable）
- [ ] 浏览器 STT 始终可用（不需要后端）
- [ ] `POST /api/stt` 在无 key 时返回 400 带可读错误信息

---

## Phase 5 — 前端动态渲染

**改造:** 前端根据 `/api/capabilities` 动态显示/隐藏 UI 元素

### /api/capabilities 返回格式
```json
{
  "backends": ["claude", "deepseek"],
  "linear": {"available": true, "type": "linear", "project": "AgenticOS"},
  "stt": {"available": true, "backends": ["browser", "openai"]},
  "pty": {"available": true}
}
```

### 前端变化
- Agent 切换只显示可用的 backend
- Linear board 标题显示 "Linear" / "Local Tasks" / "N/A"
- STT 选择下拉只显示可用后端
- 不可用的功能区域显示紧凑提示（"Configure XYZ in .env to enable"）

### 完成标准

- [ ] 前端在启动时 fetch `/api/capabilities`
- [ ] 所有动态 UI 元素根据 capabilities 显示/隐藏
- [ ] 没有 JavaScript 错误因为缺失的 API 端点

---

## Phase 6 — 拆分 `app.py`

**改造:** 将 `app.py` 从 100K+ 单文件拆分为模块化结构

### 迁移策略

**Phase 6a — 提取路由和 API handler 到模块**
- Linear 路由 → `runner/modules/linear/`
- Agent dispatch 路由 → `runner/modules/backends/`
- STT 路由 → `runner/modules/stt/`
- PTY 路由 → `runner/modules/pty/`

**Phase 6b — 提取后台循环**
- `_stall_detection_loop` → 保留在 app.py（核心功能）
- `_linear_polling_loop` → `runner/modules/linear/`
- `_deepseek_polling_loop` → `runner/modules/backends/deepseek.py`

**Phase 6c — app.py 变为薄启动器**
- 只做：参数解析 → 环境初始化 → 加载模块 → 启动 SocketIO

### 完成标准

- [ ] `app.py` 减少到 500 行以内
- [ ] 所有功能正常工作（回归测试）
- [ ] 新模块可以在 `runner/modules/` 下编写并通过注册表自动发现

---

## Symphony / Elixir 兼容性

### 背景

Symphony 是一个外部的 Elixir/Phoenix LiveView 协调器，位于 `../symphony/`。它与 agentic-os 共享：
1. **WORKFLOW.md** — 相同的 YAML front matter 格式（`agent.backend`、`tracker.kind`、`polling.interval_ms`）
2. **Agent 后端选择** — 需要根据配置和实际可用性选择 dispatch 到哪个后端
3. **任务状态同步** — agentic-os 的 running/success/failed 状态需要同步回 Symphony

当前问题：Symphony 和 agentic-os 各自独立实现 Agent 选择逻辑。WORKFLOW.md 格式虽然相同，但：
- Symphony 不知道 agentic-os 上哪些后端真正可用（有 API key、有 CLI）
- agentic-os 不知道 Symphony 何时完成了 dispatch
- `symphony/aider_deep.py` 受限于 P8 阻塞状态，尚未适配 DeepSeek CLI

### 共享配置协议

```
WORKFLOW.md
┌─────────────────────┐
│ agent:              │  ← 两个系统都读这个文件
│   backend: claude   │
│ polling: ...        │
│ tracker: ...        │
└─────────┬───────────┘
          │
          ▼
┌─────────────────┐   /api/capabilities   ┌──────────────────┐
│ agentic-os      │◄──────────────────────►│   Symphony       │
│ (Python/Flask)  │                        │ (Elixir/LiveView)│
│                 │  GET /api/backends     │                  │
│ 后端能力检测     │  ──→ ["claude", "ds"] │   Agent 选择 UI  │
│ 动态路由注册     │  ←── 平台可用后端      │   dispatch 路由   │
└─────────────────┘                        └──────────────────┘
```

### 适配方案

**Phase 3a — 后端能力 API**
在 Phase 3 完成后，`/api/capabilities` 返回可用后端列表。Symphony 可在启动时或定期调用此端点，动态决定哪些 Agent 按钮可点击。

**Phase 3b — agent.backend 热同步**
当用户在 agentic-os dashboard 切换 Agent 后端时，通过 WebSocket 或者 `/api/config` PATCH 同步更新 `WORKFLOW.md` 中的 `agent.backend`。Symphony 通过文件 watch 或定时重读获取最新配置。

**Phase 3c — Symphony dispatch 适配**
Symphony 不再直接调用 `claude -p` / `codex exec`，而是通过 agentic-os 的 `POST /run` 端点 dispatch。这样：
- agentic-os 负责 Agent 选择、技能匹配、run_id 生成、状态记录
- Symphony 只负责任务编排（poll Linear → create issue → set in progress → wait for result）
- dispatch 调用链：Symphony → agentic-os POST /run → agent CLI

### 完成标准（跨所有 phase）

- [ ] `/api/capabilities` 返回的 `backends` 列表可供 Symphony 动态读取
- [ ] WORKFLOW.md 中的 `agent.backend` 修改后，Symphony 能感知到变化
- [ ] Symphony 通过 agentic-os 的 `POST /run` dispatch，不直接调用 agent CLI
- [ ] Symphony 展示不可用的 Agent 后端时显示禁用状态（同前端 dashboard）

---

## 关键约束

- 不要改动 `usage_reader.py` 和 `run_skill.py` 等已经独立的文件，除非必要
- 每个模块必须能独立 `pytest`（无跨模块循环导入）
- `runner/core/` 不能引用任何 `runner/modules/` 中的代码
- Linear 的本地降级方案必须和 Linear API 的返回格式完全一致（`_normalize_linear_issue` 输出）
- 前端向后兼容：现有用户不会因为升级看到空白页
- 所有模块名、路由前缀、SocketIO 事件名保持命名空间一致

---

## 风险

| 风险 | 缓解 |
|------|------|
| `app.py` 内 Linear 引用散布各处，提取时遗漏 | 先用 grep 列出所有 `linear_` 引用，再做提取 |
| 模块间循环导入 | `ModuleRegistry` 纯注册不导入模块体；模块在 `load_all()` 时才导入 |
| 前端 JS 在能力不足时崩溃 | 所有动态元素加空值保护（`|| {}`、`?.` 安全链） |
| Phase 6 拆 `app.py` PR 过大难以审查 | 每个子 phase 一个 PR，控制在 200 行变更以内 |
