"""AgenticOS 功能模块入口。

模块目录结构:
    runner/modules/
        backends/      — Agent 后端（Claude/Codex/DeepSeek）
        linear/        — Linear 集成 + 本地任务跟踪
        stt/           — 语音转文字（多后端）
        pty/           — PTY 终端模块（未来单独拆分）

每个模块包在 __init__.py 中显式注册到全局 ModuleRegistry。
"""

from runner.core.module_registry import registry


def discover_all() -> list[str]:
    """导入所有模块包，触发显式注册。

    模块在各自的 __init__.py 中调用 registry.register() 进行注册。
    discover_all() 遍历并导入它们，然后执行能力检测。

    返回本次调用中新注册的模块名列表。
    """
    before = set(registry.modules.keys())

    # 按顺序导入各模块（依赖顺序：先 backends 后 features）
    import runner.modules.backends  # noqa: F401  — registers claude/codex/deepseek
    import runner.modules.linear    # noqa: F401  — registers linear

    after = set(registry.modules.keys())
    return list(after - before)
