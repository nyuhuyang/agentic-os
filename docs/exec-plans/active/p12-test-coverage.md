# P12 — 测试覆盖

**状态:** Active  
**优先级:** P2  
**开始:** 2026-05-12  
**负责人:** AgenticOS

---

## 目标

为 P10/P11 模块化改造后的核心组件建立单元测试，验证模块发现、能力检测、优雅降级、任务跟踪等关键路径，防止回归。

---

## 当前状态 (2026-05-12)

```
40 tests, 100% pass, 0.17s
```

### 已覆盖

| 组件 | 文件 | 测试数 | 覆盖场景 |
|------|------|--------|----------|
| 功能检测 | `tests/core/test_features.py` | 12 | `has_env`、`has_env_key`（含占位符/$VAR）、`has_package`、`has_executable`、`has_dir`、`check_all` |
| 模块注册表 | `tests/core/test_module_registry.py` | 12 | 注册/获取、能力检测通过/失败、禁用标记、`get_capabilities()` 结构、单例 |
| 后端模块 | `tests/modules/test_backend_modules.py` | 9 | Claude/Codex/DeepSeek 可用条件、不可用条件（缺目录、缺 CLI、缺API Key） |
| 本地任务跟踪 | `tests/modules/test_local_tracker.py` | 19 | CRUD、状态映射、评论、持久化、边界条件 |

### 未覆盖

| 组件 | 原因 | 计划 |
|------|------|------|
| `runner/core/registry_loader.py` | 依赖 app.py 路径常量 | 需 mock `sys.modules["app"]` |
| `runner/modules/stt/__init__.py` | 依赖 Flask | 需 Flask test client |
| `runner/modules/pty/__init__.py` | 依赖 Flask + SocketIO + PTY fd | 有状态组件 |
| `runner/modules/stall_detection/__init__.py` | 运行时组件（无限循环） | 可单独测试 `check_capabilities()` |
| app.py routes | Flask 应用 | 可选 pytest-flask |

---

## 执行计划

### Phase 1 — 核心基础设施测试 ✅（已完成）

`features.py` + `module_registry.py`

### Phase 2 — 模块能力检测测试 ✅（已完成）

各 AgenticModule 子类的 `check_capabilities()`

### Phase 3 — LocalTracker 完整 CRUD 测试 ✅（已完成）

LocalTracker 所有公开方法 + 边界条件 + 持久化

### Phase 4 — registry_loader 测试 🔲（可选）

需 mock `sys.modules["app"]` 或暴露测试接口

### Phase 5 — 模块集成测试 🔲（可选）

pytest-flask 启动最小 app 验证路由注册

---

## 关键文件

| 文件 | Phase | 行数 |
|------|-------|------|
| `tests/core/test_features.py` | 1 | 90 |
| `tests/core/test_module_registry.py` | 2 | 144 |
| `tests/modules/test_backend_modules.py` | 2 | 127 |
| `tests/modules/test_local_tracker.py` | 3 | 140 |

---

## 运行方式

```bash
.venv/bin/python3 -m pytest tests/ -v
```

## 约束

- 测试不依赖外部 API
- 不启动 Flask server
- mock 外部依赖（文件系统、环境变量、subprocess）
- `pytest` + `pytest-mock` 已安装在 `.venv`
