"""DeepSeek 后端模块 — dsh (DeepSeek Harness) 能力检测 + 用量监控。

检测: dsh 可执行文件 (>= dsh_cli.DSH_MIN_VERSION) + Node >= 22 + API key
提供: 能力上报 backend="dsh"（派发在 app.py），balance/usage 监控，后台轮询
模块名与监控身份保持 "deepseek"。
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import threading
import time
from typing import Any

from runner.core.module_registry import AgenticModule, registry
from runner import dsh_cli

logger = logging.getLogger(__name__)

_NODE_MIN_MAJOR = 22


def _node_major() -> int | None:
    node = shutil.which("node")
    if not node:
        return None
    try:
        out = subprocess.check_output([node, "--version"], text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.match(r"v?(\d+)", out.strip())
    return int(m.group(1)) if m else None


class DeepSeekModule(AgenticModule):
    """DeepSeek via the official dsh CLI; this module only checks it and monitors spend."""

    name = "deepseek"
    label = "DeepSeek"

    def __init__(self) -> None:
        super().__init__()
        self._socketio = None

    def check_capabilities(self) -> dict:
        dsh_bin = dsh_cli.resolve_bin()
        if not dsh_bin:
            return {"available": False, "reason": "dsh not installed (npm i -g @deepseek-ai/dsh)"}
        major = _node_major()
        if major is None or major < _NODE_MIN_MAJOR:
            return {"available": False, "reason": f"dsh needs Node >= {_NODE_MIN_MAJOR} (found {major})"}
        try:
            version = dsh_cli.check_version(dsh_bin)
        except RuntimeError as exc:
            return {"available": False, "reason": str(exc)}
        if not dsh_cli.resolve_api_key():
            return {"available": False, "reason": "DEEPSEEK_API_KEY not set (env or ~/.deepseek/config.toml)"}
        return {"available": True, "reason": "", "backend": "dsh", "version": version}

    # ── Background polling ───────────────────────────────────────────────

    def start_background(self, app, socketio) -> list[threading.Thread]:
        self._socketio = socketio
        return [threading.Thread(target=self._polling_loop, daemon=True)]

    def _polling_loop(self) -> None:
        try:
            import deepseek_monitor as _ds_mon
        except ImportError:
            return
        while True:
            try:
                _ds_mon.update_usage()
            except Exception:
                logger.exception("deepseek poll failed")
            time.sleep(120)

    def load_usage(self) -> dict[str, Any]:
        """Load DeepSeek usage from monitor's cached file."""
        try:
            from usage_reader import load_deepseek_usage as _load_ds
        except ImportError:
            return {"available": False}
        data = _load_ds()
        if not data:
            return {"available": False}
        bal = data.get("balance", {})
        return {
            "available": True,
            "balance_cny": bal.get("balance_cny", 0),
            "balance_usd": bal.get("balance_usd", 0),
            "total_cost_usd": data.get("total_cost_usd", 0),
            "total_cost_cny": data.get("total_cost_cny", 0),
            "stale": bool(data.get("stale")),
        }


module = DeepSeekModule()
registry.register(module)
