"""AgenticOS 核心基础设施模块。

提供可复用的配置、注册表、状态管理和 PTY 基础设施。
每个子模块独立可用，无跨模块循环依赖。
"""

from runner.core.features import (
    check_all,
    has_dir,
    has_env,
    has_env_key,
    has_executable,
    has_file,
    has_package,
)
from runner.core.module_registry import AgenticModule, ModuleRegistry, registry

__all__ = [
    "AgenticModule",
    "ModuleRegistry",
    "registry",
    # feature detection
    "check_all",
    "has_dir",
    "has_env",
    "has_env_key",
    "has_executable",
    "has_file",
    "has_package",
]
