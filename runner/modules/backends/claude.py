"""Claude 后端模块 — Claude Code CLI 集成。

检测: claude CLI 可用 + ~/.claude/ 目录存在
提供: claude -p dispatch, JSONL-based usage reading
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

from runner.core.module_registry import AgenticModule
from runner.core.features import has_executable, has_dir

logger = logging.getLogger(__name__)

CLAUDE_DIR = Path.home() / ".claude"


class ClaudeModule(AgenticModule):
    """Claude Code CLI backend module."""

    name = "claude"
    label = "Claude Code"
    dependencies: list[str] = []
    required_env: list[str] = []

    def check_capabilities(self) -> dict:
        """Detect if Claude is available."""
        if not has_dir(CLAUDE_DIR):
            return {
                "available": False,
                "reason": f"~/.claude/ directory not found",
            }
        # Check for claude CLI — try project venv first, then PATH
        claude_bin = Path(__file__).resolve().parents[3] / ".venv" / "bin" / "claude"
        if not claude_bin.exists() and not has_executable("claude"):
            return {
                "available": False,
                "reason": "claude CLI not found in PATH or .venv",
            }
        return {
            "available": True,
            "reason": "",
            "backend": "claude",
            "models": [
                "claude-sonnet-4-6",
                "claude-opus-4-7",
                "claude-haiku-4-5-20251001",
            ],
            "default_model": "claude-sonnet-4-6",
        }

    @property
    def default_model(self) -> str:
        try:
            from app import _load_workflow_config
            cfg = _load_workflow_config()
            return (cfg.get("agent") or {}).get("claude_model", "claude-sonnet-4-6")
        except Exception:
            return "claude-sonnet-4-6"

    @property
    def cli_path(self) -> str:
        """Return the path to the claude CLI binary."""
        claude_bin = Path(__file__).resolve().parents[3] / ".venv" / "bin" / "claude"
        if claude_bin.exists():
            return str(claude_bin)
        return "claude"


# ── Module registration ────────────────────────────────────────────────────

module = ClaudeModule()
