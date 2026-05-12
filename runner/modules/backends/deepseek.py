"""DeepSeek 后端模块 — 直接 API 集成 + 工具调用循环 + 用量监控。

检测: DEEPSEEK_API_KEY 环境变量存在
提供: deepseek_agent dispatch, balance/usage 监控, 后台轮询
"""

from __future__ import annotations

import logging
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from runner.core.module_registry import AgenticModule, registry
from runner.core.features import has_env_key

logger = logging.getLogger(__name__)


class DeepSeekModule(AgenticModule):
    """DeepSeek V4 agent backend module."""

    name = "deepseek"
    label = "DeepSeek V4"
    dependencies = ["httpx"]
    required_env = ["DEEPSEEK_API_KEY"]

    def __init__(self) -> None:
        super().__init__()
        self._socketio = None

    def check_capabilities(self) -> dict:
        if not has_env_key("DEEPSEEK_API_KEY"):
            return {"available": False, "reason": "DEEPSEEK_API_KEY not set"}
        try:
            import httpx  # noqa: F401
        except ImportError:
            return {"available": False, "reason": "httpx package not installed"}
        return {
            "available": True, "reason": "", "backend": "deepseek",
            "models": ["deepseek-v4-flash", "deepseek-v4-pro"],
            "default_model": "deepseek-v4-flash",
        }

    # ── Background polling (Phase 3) ─────────────────────────────────────

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

    # ── Dispatch (Phase 1) ───────────────────────────────────────────────

    def dispatch(self, prompt: str, run_id: str,
                 socket_room: str | None = None) -> dict:
        """Run DeepSeek agent with tools. Returns result dict."""
        logger.info("[deepseek_agent] dispatching run_id=%s", run_id)
        try:
            from deepseek_agent import run_deepseek_agent as _run
        except ImportError:
            return {"ok": False, "error": "deepseek_agent not available"}

        import app as _app
        buf: list[str] = []

        def _on_chunk(text: str) -> None:
            buf.append(text)
            if socket_room and self._socketio:
                self._socketio.emit("run_output", {"run_id": run_id, "text": text}, room=socket_room)

        result = _run(prompt, workspace=str(_app.ROOT), stream_callback=_on_chunk)
        output = "".join(buf)
        if result.get("ok") and not output:
            output = result.get("output", "")
        result["output"] = output
        return result

    def execute_commands(self, output: str, cwd: str | Path | None = None) -> str:
        """Execute ```bash/shell blocks in DeepSeek output."""
        if not output:
            return output
        import app as _app
        PATTERN = re.compile(r"```(?:bash|shell)\n(.*?)```", re.DOTALL)
        cwd = cwd or _app.ROOT
        blocks: list[tuple[int, int, str]] = []
        for m in PATTERN.finditer(output):
            cmd = m.group(1).strip()
            if not cmd:
                continue
            try:
                proc = subprocess.run(cmd, shell=True, cwd=str(cwd),
                                      capture_output=True, text=True, timeout=30)
                parts: list[str] = []
                if proc.stdout.strip():
                    parts.append(proc.stdout.strip())
                if proc.stderr.strip():
                    parts.append(f"stderr: {proc.stderr.strip()}")
                parts.append(f"exit code: {proc.returncode}")
                real_output = "\n".join(parts)
            except subprocess.TimeoutExpired:
                real_output = "timed out after 30s"
            except Exception as e:
                real_output = f"error: {e}"
            orig_block = m.group(0)
            new_block = f"{orig_block}\n\n**Real execution result:**\n```\n{real_output}\n```"
            blocks.append((m.start(), m.end(), new_block))
        for start, end, replacement in reversed(blocks):
            output = output[:start] + replacement + output[end:]
        return output

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
            "today_tokens": data.get("today", {}).get("tokens", 0),
            "by_model": data.get("by_model", {}),
            "session_count": data.get("session_count", 0),
        }


module = DeepSeekModule()
registry.register(module)
