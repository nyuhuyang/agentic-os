"""AgenticOS 功能模块入口。

模块目录结构:
    runner/modules/
        backends/      — Agent 后端（Claude/Codex/DeepSeek）
        linear/        — Linear 集成 + 本地任务跟踪
        stt/           — 语音转文字（多后端）
        pty/           — PTY 终端模块（未来单独拆分）

每个模块包定义自己的 `AgenticModule` 子类，被发现后自动注册。
"""

from pathlib import Path

from runner.core.module_registry import registry

_MODULES_DIR = Path(__file__).resolve().parent


def discover_all() -> list[str]:
    """扫描 runner/modules/ 目录，自动发现并注册所有模块。

    返回新发现的模块名列表。
    """
    return registry.discover(paths=[_MODULES_DIR])
