"""DeepSeek 后端模块 — 直接 API 集成 + 工具调用循环。

检测: DEEPSEEK_API_KEY 环境变量存在
提供: deepseek_agent dispatch, balance/usage 监控
"""

from __future__ import annotations

import logging
import os

from runner.core.module_registry import AgenticModule
from runner.core.features import has_env_key

logger = logging.getLogger(__name__)


class DeepSeekModule(AgenticModule):
    """DeepSeek V4 agent backend module."""

    name = "deepseek"
    label = "DeepSeek V4"
    dependencies = ["httpx"]
    required_env = ["DEEPSEEK_API_KEY"]

    def check_capabilities(self) -> dict:
        """Detect if DeepSeek is available."""
        if not has_env_key("DEEPSEEK_API_KEY"):
            return {
                "available": False,
                "reason": "DEEPSEEK_API_KEY not set in environment or .env",
            }
        try:
            import httpx  # noqa: F401
        except ImportError:
            return {
                "available": False,
                "reason": "httpx package not installed",
            }
        return {
            "available": True,
            "reason": "",
            "backend": "deepseek",
            "models": ["deepseek-v4-flash", "deepseek-v4-pro"],
            "default_model": "deepseek-v4-flash",
        }

    @property
    def default_model(self) -> str:
        """Return the default model from WORKFLOW.md config or fallback."""
        try:
            from app import _load_workflow_config
            cfg = _load_workflow_config()
            return (cfg.get("agent") or {}).get("deepseek_model", "deepseek-v4-flash")
        except Exception:
            return "deepseek-v4-flash"


# ── Module registration ────────────────────────────────────────────────────

module = DeepSeekModule()
