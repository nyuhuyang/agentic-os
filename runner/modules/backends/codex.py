"""Codex 后端模块 — Codex CLI 集成。

检测: codex CLI 可用 + ~/.codex/ 目录存在
提供: codex exec dispatch, SQLite-based usage reading
"""

from __future__ import annotations

import logging
from pathlib import Path

from runner.core.module_registry import AgenticModule
from runner.core.features import has_executable, has_dir

logger = logging.getLogger(__name__)

CODEX_DIR = Path.home() / ".codex"


class CodexModule(AgenticModule):
    """Codex CLI backend module."""

    name = "codex"
    label = "Codex CLI"
    dependencies: list[str] = []
    required_env: list[str] = []

    def check_capabilities(self) -> dict:
        """Detect if Codex is available."""
        if not has_dir(CODEX_DIR):
            return {
                "available": False,
                "reason": "~/.codex/ directory not found",
            }
        if not has_executable("codex"):
            return {
                "available": False,
                "reason": "codex CLI not found in PATH",
            }
        return {
            "available": True,
            "reason": "",
            "backend": "codex",
            "models": [],
            "default_model": "gpt-5.4-mini",
        }

    @property
    def default_model(self) -> str:
        try:
            from app import _load_workflow_config
            cfg = _load_workflow_config()
            model = (cfg.get("agent") or {}).get("codex_model", "")
            if model:
                return model
            # Fallback: read from Codex config
            config_path = CODEX_DIR / "config.toml"
            if config_path.exists():
                import tomllib
                codex_cfg = tomllib.loads(config_path.read_text(encoding="utf-8"))
                if isinstance(codex_cfg, dict):
                    configured = codex_cfg.get("model")
                    if isinstance(configured, str) and configured.strip():
                        return configured.strip()
        except Exception:
            pass
        return "gpt-5.4-mini"


# ── Module registration ────────────────────────────────────────────────────

module = CodexModule()
