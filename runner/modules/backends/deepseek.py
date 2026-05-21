"""DeepSeek 后端模块 — 直接 API 集成 + 工具调用循环 + 用量监控。

检测: DEEPSEEK_API_KEY 环境变量存在
提供: deepseek_agent dispatch, balance/usage 监控, 后台轮询
"""

from __future__ import annotations

import logging
import os
import re
import shutil
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
        """Run DeepSeek TUI CLI (deepseek exec). Returns result dict."""
        logger.info("[deepseek] dispatching run_id=%s via deepseek exec", run_id)

        # Resolve deepseek binary
        ds_bin = shutil.which("deepseek")
        if not ds_bin:
            for _p in ("/opt/homebrew/bin/deepseek", "/usr/local/bin/deepseek"):
                if Path(_p).exists():
                    ds_bin = _p
                    break
        if not ds_bin:
            return {"ok": False, "error": "deepseek CLI not found"}

        cmd = [ds_bin, "exec", "--auto", "--output-format", "stream-json", prompt]

        import app as _app
        import json as _json
        timeout_s = int(os.environ.get("AI_RUN_TIMEOUT_S", "1800"))
        t0 = time.monotonic()
        proc = None
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(_app.ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            content_parts: list[str] = []
            meta: dict = {}
            session_id: str | None = None
            deadline = t0 + timeout_s

            for raw in proc.stdout:  # type: ignore[union-attr]
                if time.monotonic() > deadline:
                    proc.kill()
                    raise subprocess.TimeoutExpired(cmd, timeout_s)
                line = raw.decode("utf-8", errors="replace").rstrip("\n")
                if not line:
                    continue
                try:
                    ev = _json.loads(line)
                    ev_type = ev.get("type", "")
                    if ev_type == "content":
                        content_parts.append(ev.get("content", ""))
                    elif ev_type == "metadata":
                        meta.update(ev.get("meta", {}))
                    elif ev_type == "session_capture":
                        session_id = ev.get("content")
                    elif ev_type == "tool_use" and socket_room and self._socketio:
                        self._socketio.emit("run_progress", {
                            "run_id": run_id,
                            "snippet": f"[tool] {ev.get('name', 'tool')}",
                        }, room=socket_room)
                except Exception:
                    pass

            proc.wait()
            stderr_s = (proc.stderr.read() or b"").decode("utf-8", errors="replace").strip()  # type: ignore[union-attr]
            dur = round(time.monotonic() - t0, 2)
            ok = proc.returncode == 0
            output = "".join(content_parts)
            error_s = stderr_s if not ok else ""
            if socket_room and self._socketio:
                self._socketio.emit("run_output", {"run_id": run_id, "text": output}, room=socket_room)
            return {
                "ok": ok,
                "output": output or error_s,
                "duration_s": dur,
                "input_tokens": meta.get("input_tokens"),
                "output_tokens": meta.get("output_tokens"),
                "model": meta.get("model", "deepseek-v4-flash"),
                "session_id": session_id or meta.get("session_id"),
                "error": error_s or None,
            }
        except subprocess.TimeoutExpired:
            if proc:
                proc.kill()
            return {"ok": False, "error": f"DeepSeek exec timed out after {timeout_s}s", "duration_s": round(time.monotonic() - t0, 2)}
        except Exception as e:
            return {"ok": False, "error": str(e), "duration_s": round(time.monotonic() - t0, 2)}

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
