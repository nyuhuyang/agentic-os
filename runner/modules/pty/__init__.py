"""PTY terminal module — server-owned terminal tabs (plan Decision 10) + file uploads.

Terminals belong to the server, not to a browser socket: a reload or a hidden panel only
detaches, and the process keeps running until its tab is closed. Each terminal has one
lock shared by its reader and by attach, so a reattaching client gets every byte exactly
once (snapshot first, then live output). Closing kills every process group in the
shell's session, not only the shell's own.
"""

from __future__ import annotations

import contextlib
import fcntl
import logging
import os
import pty
import select
import shlex
import signal
import struct
import subprocess
import termios
import threading
import time
import uuid
from dataclasses import dataclass, field
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


BOARD_UPLOADS_DIR = _PROTO / "outputs" / "board_uploads"
UPLOADS_DIR = _PROTO / "outputs" / "uploads"
SCROLLBACK_BYTES = 256 * 1024
MAX_TERMINALS = int(os.environ.get("AGENTIC_OS_MAX_TERMINALS", "8"))


# ── Terminal registry ──────────────────────────────────────────────────────

@dataclass
class Terminal:
    term_id: str
    kind: str                      # shell | resume | run
    cwd: str = ""
    project_key: str | None = None
    run_id: str | None = None
    ticket: str | None = None      # bound worktree ticket (holds its lock while open)
    label: str = ""
    pid: int | None = None
    fd: int | None = None
    alive: bool = True
    exit_code: int | None = None
    cleanup_failed: bool = False
    created_at: float = field(default_factory=time.time)
    scrollback: bytearray = field(default_factory=bytearray)
    lock: threading.Lock = field(default_factory=threading.Lock)
    holds: contextlib.ExitStack = field(default_factory=contextlib.ExitStack)
    input_buffer: str = ""
    pending_handoff: dict | None = None
    confidential: bool = False

    def info(self) -> dict:
        return {"term_id": self.term_id, "kind": self.kind, "project_key": self.project_key,
                "run_id": self.run_id, "cwd": self.cwd, "label": self.label, "alive": self.alive,
                "exit_code": self.exit_code, "cleanup_failed": self.cleanup_failed}


TERMINALS: dict[str, Terminal] = {}
_registry_lock = threading.Lock()


def _room(term_id: str) -> str:
    return f"term:{term_id}"


def live_count() -> int:
    return sum(1 for t in TERMINALS.values() if t.pid is not None and t.alive)


def main_path_tab_open(project_key: str) -> bool:
    """A user shell sits on this project's main checkout (Decision 10, interactive_tab_open)."""
    try:
        import projects
        path = str(projects.get_project(project_key, projects.load_registry(errors={})).path)
    except Exception:
        return False
    return any(t.alive and t.pid and t.kind == "shell" and t.project_key == project_key and t.cwd == path
               for t in TERMINALS.values())


# ── Internal helpers ───────────────────────────────────────────────────────

def _set_winsize(fd: int, rows: int, cols: int) -> None:
    try:
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    except Exception:
        pass


def _append_scrollback(t: Terminal, data: bytes) -> None:
    t.scrollback += data
    if len(t.scrollback) > SCROLLBACK_BYTES:
        del t.scrollback[: len(t.scrollback) - SCROLLBACK_BYTES]


def _reader(t: Terminal, socketio) -> None:
    """Read the PTY; append + emit under the terminal lock so attach sees each byte once."""
    while True:
        try:
            r, _, _ = select.select([t.fd], [], [], 0.2)
            if not r:
                if t.fd is None:
                    break
                continue
            data = os.read(t.fd, 4096)
        except (OSError, TypeError, ValueError):
            break
        if not data:
            break
        with t.lock:
            _append_scrollback(t, data)
            socketio.emit("term_output", {"term_id": t.term_id, "data": data.decode("utf-8", "replace")},
                          to=_room(t.term_id))
    with t.lock:
        t.alive = False
        if t.pid:
            with contextlib.suppress(ChildProcessError, OSError):
                pid, status = os.waitpid(t.pid, os.WNOHANG)
                if pid:
                    t.exit_code = os.waitstatus_to_exitcode(status)
    socketio.emit("term_exit", {"term_id": t.term_id, "exit_code": t.exit_code}, to=_room(t.term_id))


def _session_pgids(sid: int) -> set[int]:
    """Process groups of every process in session `sid`. macOS pgrep has no -s and ps
    reports sess as 0, so ps lists pid/pgid and os.getsid() picks the session's members.
    Raises on enumeration failure (the caller marks the close as failed)."""
    out = subprocess.run(["ps", "-A", "-o", "pid=,pgid="], capture_output=True, text=True, timeout=10, check=True)
    groups = set()
    for line in out.stdout.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        pid, pgid = int(parts[0]), int(parts[1])
        try:
            if os.getsid(pid) == sid:
                groups.add(pgid)
        except (ProcessLookupError, PermissionError):
            continue  # vanished during the scan
    return groups


def _kill_session(t: Terminal) -> None:
    """SIGHUP, then SIGTERM, then SIGKILL every group in the shell's session; reap; close."""
    if t.pid is not None:
        for sig, grace in ((signal.SIGHUP, 0.5), (signal.SIGTERM, 2.0), (signal.SIGKILL, 0.5)):
            groups = _session_pgids(t.pid)  # pty.fork made the shell a session leader: sid == pid
            if not groups:
                break
            for pgid in groups:
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.killpg(pgid, sig)
            deadline = time.monotonic() + grace
            while time.monotonic() < deadline and _session_pgids(t.pid):
                time.sleep(0.05)
        with contextlib.suppress(ChildProcessError, OSError):
            os.waitpid(t.pid, 0)
    if t.fd is not None:
        with contextlib.suppress(OSError):
            os.close(t.fd)
        t.fd = None
    t.alive = False


def close_terminal(term_id: str) -> dict:
    t = TERMINALS.get(term_id)
    if t is None:
        return {"error": "unknown terminal"}
    try:
        _kill_session(t)
    except Exception as exc:  # enumeration failed: keep the tab, flagged, so nothing is lost silently
        t.cleanup_failed = True
        logger.error("terminal %s cleanup failed: %s", term_id, exc)
        return {"error": f"cleanup failed: {exc}", **t.info()}
    t.holds.close()  # releases a bound-worktree ticket lock
    with _registry_lock:
        TERMINALS.pop(term_id, None)
    return {"ok": True, "term_id": term_id}


def close_all() -> None:
    for term_id in list(TERMINALS):
        with contextlib.suppress(Exception):
            close_terminal(term_id)


def _spawn(t: Terminal, argv: list[str], env: dict, cols: int, rows: int, socketio) -> None:
    pid, fd = pty.fork()
    if pid == 0:  # child: a new session (pty.fork), so it is its own session leader
        try:
            os.chdir(t.cwd)
            os.execvpe(argv[0], argv, env)
        finally:
            os._exit(127)
    t.pid, t.fd = pid, fd
    _set_winsize(fd, rows, cols)
    threading.Thread(target=_reader, args=(t, socketio), daemon=True).start()


def _shell_env(project=None) -> dict:
    env = os.environ.copy()
    env["TERM"] = "xterm-256color"
    env["COLORTERM"] = "truecolor"
    for k, v in (project.env.items() if project else []):
        env[k] = f"{v}{os.pathsep}{env.get('PATH', '')}" if k == "PATH" else v
    return env


def interactive_resume_argv(agent: str, session_id: str, project) -> list[str] | None:
    """Resume command for an interactive tab, through the same policy as headless dispatch
    (Decision 10 / MPD-26). None = no eligible interactive form (button hidden)."""
    import project_runs
    if agent == "dsh":
        return None  # dsh has no interactive TUI
    if project is None:  # runner-root session: no project policy applies
        return ["claude", "--resume", session_id] if agent == "claude" else ["codex", "resume", session_id]
    try:
        cli = project_runs.agent_cli(agent, project, "claude", lambda: [])
    except project_runs.ProjectRunError:
        return None
    if agent == "claude":  # headless prefix minus -p/--verbose/--permission-prompts
        drop = {"-p", "--verbose"}
        out, skip = [], False
        for i, a in enumerate(cli):
            if skip:
                skip = False
                continue
            if a == "--permission-prompts":
                skip = True
                continue
            if a not in drop:
                out.append(a)
        return out + ["--resume", session_id]
    # codex: interactive `codex resume` with the same pinned sandbox and approval policy
    flags = [a for a in cli[2:] if a != "--json"]
    return ["codex", "resume", session_id, *flags]


def open_terminal(data: dict, socketio) -> dict:
    """term_open: shell (project main path, bound worktree, or runner root), resume, or run view."""
    _ensure_imports()
    import projects
    kind = (data or {}).get("kind") or "shell"
    cols, rows = int(data.get("cols") or 120), int(data.get("rows") or 24)
    t = Terminal(term_id=uuid.uuid4().hex[:12], kind=kind)
    if kind == "run":
        t.run_id = str(data.get("run_id") or "")
        t.project_key = data.get("project_key")
        t.label = f"{t.project_key or 'run'} · run · {t.run_id[:6]}"
        t.alive = True
        TERMINALS[t.term_id] = t
        return t.info()
    if live_count() >= MAX_TERMINALS:
        return {"error": f"terminal limit reached ({MAX_TERMINALS} live); close one first"}
    project = None
    key = data.get("project_key")
    try:
        if key:
            project = projects.get_project(key, projects.load_registry(errors={}))
            t.project_key = key
        ticket = data.get("ticket")
        if kind == "resume" and project and data.get("cwd") and not ticket:
            # The server, not the browser, decides whether a session sits in an owned worktree:
            # if so the tab takes that ticket's lock like any worktree tab (I5-08).
            cwd = Path(os.path.realpath(str(data["cwd"])))
            owned = Path(os.path.realpath(projects.WORKTREE_ROOT / project.key))
            if cwd.is_relative_to(owned) and cwd != owned:
                ticket = cwd.relative_to(owned).parts[0]
            elif not cwd.is_relative_to(project.path.resolve()):
                raise projects.ProjectError(f"session folder {cwd} is outside project {project.key}")
        if ticket and project:
            # A tab in a bound worktree owns the ticket while open (MPD-27).
            from app import _effective_project
            t.holds.enter_context(projects.ticket_lock(project.key, ticket))
            projects.load_binding(project, ticket)
            project = _effective_project(project, ticket)  # sticky per ticket (I6-02, I8-01)
            t.ticket, t.cwd = ticket, str(projects.worktree_path(project, ticket))
        else:
            t.cwd = str(project.path if project else ROOT or _PROTO)
        if project and project.confidential:
            from app import _records_unsafe
            problem = _records_unsafe()  # handoffs from this tab land in the run records (I6-04)
            if problem:
                raise projects.ProjectError(problem)
            t.confidential = True
        argv = [os.environ.get("SHELL", "/bin/zsh"), "-l"]
        if kind == "resume":
            resume = interactive_resume_argv(str(data.get("agent")), str(data.get("session_id")), project)
            if not resume:
                t.holds.close()
                return {"error": "no eligible interactive resume for this session"}
            if data.get("cwd") and (not t.ticket or Path(os.path.realpath(str(data["cwd"]))).is_relative_to(
                    Path(os.path.realpath(t.cwd)))):
                t.cwd = str(data["cwd"])
            argv = [argv[0], "-l", "-c", shlex.join(resume) + f"; exec {shlex.quote(argv[0])} -l"]
        short = (t.ticket or Path(t.cwd).name)[:16]
        t.label = f"{key or 'runner'} · {kind} · {short}"
        _spawn(t, argv, _shell_env(project), cols, rows, socketio)
    except Exception as exc:
        t.holds.close()
        return {"error": str(exc)}
    TERMINALS[t.term_id] = t
    return t.info()


def attach(t: Terminal, sid: str, socketio, join_room) -> None:
    """Join the live room and send the scrollback under the reader's lock: every byte
    arrives exactly once, either in the snapshot or live after it (MPD-30)."""
    with t.lock:
        join_room(_room(t.term_id), sid=sid)
        socketio.emit("term_output", {"term_id": t.term_id, "data": t.scrollback.decode("utf-8", "replace"),
                                      "replay": True}, to=sid)


def _track_input(t: Terminal, text: str) -> str | None:
    """Accumulate input; return the completed line on newline."""
    buf, completed = t.input_buffer, None
    for ch in text:
        if ch in ("\r", "\n"):
            completed, buf = buf, ""
        elif ch in ("\x7f", "\b"):
            buf = buf[:-1]
        elif ch == "\x1b":
            continue
        elif ch.isprintable() or ch == "\t":
            buf += ch
    t.input_buffer = buf
    return completed


def _record_pending_handoff(t: Terminal, line: str, socketio) -> None:
    """Skill handoff typed into a tab: logged with the tab's project (MPD-34). Run records are
    runner-local (Decision 4a), so the command itself needs no extra redaction there."""
    _ensure_imports()
    pending, t.pending_handoff = t.pending_handoff, None
    command = line.strip()
    if not pending or not command or _write_run_log is None:
        return
    from datetime import datetime, timezone
    import projects
    from app import _records_unsafe
    confidential = t.confidential
    if t.project_key and not confidential:  # the registry may have changed since the tab opened
        try:
            confidential = projects.get_project(t.project_key, projects.load_registry(errors={})).confidential
        except projects.ProjectError:
            confidential = True
    if confidential and _records_unsafe():
        command = "[withheld: run-record location not allowed for confidential projects]"  # I6-04
    run_id = pending.get("run_id") or str(uuid.uuid4())
    _write_run_log(pending["skill"], "sent", datetime.now(timezone.utc).isoformat(), 0.0,
                   prompt=command, output="dispatched to terminal", run_id=run_id,
                   extra={"project_key": t.project_key, "term_id": t.term_id} if t.project_key else None)
    socketio.emit("run_logged", {"skill": pending["skill"], "run_id": run_id}, to=_room(t.term_id))


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
        from flask_socketio import join_room

        @socketio.on("term_list")
        def term_list(_data=None):
            return [t.info() for t in TERMINALS.values()]

        @socketio.on("term_open")
        def term_open(data):
            return open_terminal(data or {}, socketio)

        @socketio.on("term_attach")
        def term_attach(data):
            t = TERMINALS.get((data or {}).get("term_id"))
            if t is None:
                return {"error": "unknown terminal"}
            attach(t, request.sid, socketio, join_room)
            return t.info()

        @socketio.on("term_input")
        def term_input(data):
            t = TERMINALS.get((data or {}).get("term_id"))
            if t is None or t.fd is None or not t.alive:
                return
            text = data.get("data") or ""
            completed = _track_input(t, text)
            if completed is not None:
                _record_pending_handoff(t, completed, socketio)
            with contextlib.suppress(OSError):
                os.write(t.fd, text.encode())

        @socketio.on("skill_selected")
        def skill_selected(data):
            t = TERMINALS.get((data or {}).get("term_id"))
            skill = (data or {}).get("skill", "").strip()
            if t is not None and skill:
                t.pending_handoff = {"skill": skill, "phrase": (data or {}).get("phrase", "").strip(),
                                     "run_id": str(uuid.uuid4())}

        @socketio.on("term_resize")
        def term_resize(data):
            t = TERMINALS.get((data or {}).get("term_id"))
            if t is not None and t.fd is not None:
                _set_winsize(t.fd, int(data.get("rows", 24)), int(data.get("cols", 120)))

        @socketio.on("term_close")
        def term_close(data):
            return close_terminal((data or {}).get("term_id"))

        # A browser disconnect only detaches (Socket.IO drops the sid from its rooms).

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
            return jsonify({
                "name": original_name,
                "filename": dest.name,
                "url": f"/api/board/uploads/{dest.name}",
                "path": str(dest.resolve()),
            })

        @app.route("/api/board/uploads/<path:filename>")
        def api_board_uploads_serve(filename):
            from werkzeug.utils import secure_filename
            from flask import send_from_directory
            safe = secure_filename(filename)
            resp = send_from_directory(str(BOARD_UPLOADS_DIR), safe)
            # Exempt from the request token, so an uploaded file must never run as the
            # dashboard (sandbox) or be embeddable by another origin (CORP).
            resp.headers["Content-Security-Policy"] = "sandbox; frame-ancestors 'none'"
            resp.headers["X-Content-Type-Options"] = "nosniff"
            resp.headers["Cross-Origin-Resource-Policy"] = "same-origin"
            return resp

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
