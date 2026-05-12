"""Agent 后端模块 — 可插拔的 AI 代码代理。

支持的后端:
- claude    (需要 ~/.claude/ 目录 + claude CLI)
- deepseek  (需要 DEEPSEEK_API_KEY 环境变量)
- codex     (需要 ~/.codex/ 存在 + codex CLI)

每个后端是一个独立的 `AgenticModule` 子类，注册到全局 ModuleRegistry。
"""

from runner.core.module_registry import registry

# Import triggers registration via module-level `module` variable
from runner.modules.backends.claude import module as _claude_mod
from runner.modules.backends.codex import module as _codex_mod
from runner.modules.backends.deepseek import module as _deepseek_mod

registry.register(_claude_mod)
registry.register(_codex_mod)
registry.register(_deepseek_mod)
