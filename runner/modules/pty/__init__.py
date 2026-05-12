"""PTY 终端模块 — 伪终端会话管理 + 文件上传。

处理 WebSocket → PTY 桥接、技能注入、文件上传。
"""

from __future__ import annotations

import fcntl
import logging
import os
import pty
import select
import struct
import termios
import threading
from pathlib import Path

from flask import jsonify, request

from runner.core.module_registry import AgenticModule, registry

logger = logging.getLogger(__name__)

_HERE = Path(__file__).resolve().parent
_PROTO = _HERE.parent.parent

# Import shared paths from app.py (lazy, used inside functions)
ROOT: Path | None = None
_write_run_log = None


def _ensure_imports():
    """Lazy-import shared state from app.py to avoid circular imports."""
    global ROOT, _write_run_log
    if ROOT is None:
        from app import ROOT as _r, _write_run_log as _w
        ROOT = _r
        _write_run_log = _w


# ── Module-level state ─────────────────────────────────────────────────────

_pty_sessions: dict[str, int] = {}      # sid -> fd
_pty_input_buffers: dict[str, str] = {}
_pending_skill_handoffs: dict[str, dict[str, str]] = {}

BOARD_UPLOADS_DIR = _PROTO / "outputs" / "board_uploads"
UPLOADS_DIR = _PROTO / "outputs" / "uploads"


# ── Internal helpers ───────────────────────────────────────────────────────

def _set_winsize(fd: int, rows: int, cols: int) -> None:
    try:
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)
    except Exception:
        pass


def _pty_read_loop(sid: str, fd: int, socketio) -> None:
    while True:
        try:
            r, _, _ = select.select([fd], [], [], 0.1)
            if r:
                data = os.read(fd, 1024).decode("utf-8", errors="replace")
                socketio.emit("pty_output", {"data": data}, to=sid)
        except OSError:
            break
    _pty_sessions.pop(sid, None)


def _track_pty_input(sid: str, text: str) -> str | None:
    """Accumulate input buffer, return completed line on newline."""
    buf = _pty_input_buffers.get(sid, "")
    completed_line = None
    for ch in text:
        if ch in ("\r", "\n"):
            completed_line = buf
            buf = ""
        elif ch in ("\x7f", "\b"):
            buf = buf[:-1]
        elif ch == "\x1b":
            continue
        elif ch.isprintable() or ch == "\t":
            buf += ch
    _pty_input_buffers[sid] = buf
    return completed_line


def _record_pending_handoff(sid: str, line: str, socketio) -> None:
    import uuid
    from datetime import datetime, timezone
    _ensure_imports()
    if _write_run_log is None:
        return
    pending = _pending_skill_handoffs.pop(sid, None)
    if not pending:
        return
    command = line.strip()
    if not command:
        return
    started_at = datetime.now(timezone.utc).isoformat()
    run_id = pending.get("run_id") or str(uuid.uuid4())
    _write_run_log(
        pending["skill"],
        "sent",
        started_at,
        0.0,
        prompt=command,
        output="dispatched to terminal",
        run_id=run_id,
    )
    socketio.emit("run_logged", {"skill": pending["skill"], "run_id": run_id}, to=sid)


class PTYModule(AgenticModule):
    """PTY terminal and file upload module."""

    name = "pty"
    label = "PTY Terminal"
    dependencies: list[str] = []
    required_env: list[str] = []

    def check_capabilities(self) -> dict:
        return {"available": True, "reason": "", "terminal": True}

    def register_socketio(self, socketio) -> None:
        _ensure_imports()

        @socketio.on("pty_start")
        def pty_start(data):
            sid = request.sid
            shell = os.environ.get("SHELL", "/bin/bash")
            cols = data.get("cols", 120)
            rows = data.get("rows", 24)
            env = os.environ.copy()
            env["TERM"] = "xterm-256color"
            env["COLORTERM"] = "truecolor"
            pid, fd = pty.fork()
            if pid == 0:
                if ROOT:
                    os.chdir(str(ROOT))
                os.execvpe(shell, [shell], env)
            else:
                _pty_sessions[sid] = fd
                _pty_input_buffers[sid] = ""
                _set_winsize(fd, rows, cols)
                threading.Thread(target=_pty_read_loop, args=(sid, fd, socketio), daemon=True).start()

        @socketio.on("pty_input")
        def pty_input(data):
            fd = _pty_sessions.get(request.sid)
            if fd is not None:
                text = data["data"]
                completed = _track_pty_input(request.sid, text)
                if completed is not None:
                    _record_pending_handoff(request.sid, completed, socketio)
                os.write(fd, text.encode())

        @socketio.on("skill_selected")
        def skill_selected(data):
            skill = (data or {}).get("skill", "").strip()
            phrase = (data or {}).get("phrase", "").strip()
            if not skill:
                return
            import uuid
            run_id = str(uuid.uuid4())
            _pending_skill_handoffs[request.sid] = {"skill": skill, "phrase": phrase, "run_id": run_id}

        @socketio.on("pty_resize")
        def pty_resize(data):
            fd = _pty_sessions.get(request.sid)
            if fd is not None:
                _set_winsize(fd, data.get("rows", 24), data.get("cols", 120))

        @socketio.on("disconnect")
        def pty_disconnect():
            _pty_sessions.pop(request.sid, None)
            _pty_input_buffers.pop(request.sid, None)
            _pending_skill_handoffs.pop(request.sid, None)

    def register_routes(self, app) -> None:
        @app.route("/api/board/upload", methods=["POST"])
        def api_board_upload():
            if "file" not in request.files:
                return jsonify({"error": "no file"}), 400
            f = request.files["file"]
            if not f.filename:
                return jsonify({"error": "empty filename"}), 400
            from werkzeug.utils import secure_filename
            original_name = f.filename
            filename = secure_filename(original_name)
            BOARD_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
            dest = BOARD_UPLOADS_DIR / filename
            counter = 1
            while dest.exists():
                dest = BOARD_UPLOADS_DIR / f"{dest.stem}_{counter}{dest.suffix}"
                counter += 1
            f.save(str(dest))
            return jsonify({"name": original_name, "filename": dest.name, "url": f"/api/board/uploads/{dest.name}"})

        @app.route("/api/board/uploads/<path:filename>")
        def api_board_uploads_serve(filename):
            from werkzeug.utils import secure_filename
            from flask import send_from_directory
            safe = secure_filename(filename)
            return send_from_directory(str(BOARD_UPLOADS_DIR), safe)

        @app.route("/upload", methods=["POST"])
        def upload_file():
            if "file" not in request.files:
                return jsonify({"error": "no file"}), 400
            f = request.files["file"]
            if not f.filename:
                return jsonify({"error": "empty filename"}), 400
            from werkzeug.utils import secure_filename
            filename = secure_filename(f.filename)
            UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
            dest = UPLOADS_DIR / filename
            counter = 1
            while dest.exists():
                dest = UPLOADS_DIR / f"{dest.stem}_{counter}{dest.suffix}"
                counter += 1
            f.save(str(dest))
            return jsonify({"name": f.filename, "url": f"/api/uploads/{dest.name}"})


# ── Module registration ────────────────────────────────────────────────────

module = PTYModule()
registry.register(module)
