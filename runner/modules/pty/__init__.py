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
    agent: str | None = None       # resume tabs: the session they hold (rename/remove live check)
    session_id: str | None = None
    in_panel: bool = True          # shown in the bottom panel; card-only terminals are not (C2)
    card_key: str | None = None    # runner-root card lock held while open (C2)
    finalized: bool = False        # locks released and closure audited (once)
    closing: bool = False          # close_terminal owns the end: the reader leaves finalizing to it

    def info(self) -> dict:
        return {"term_id": self.term_id, "kind": self.kind, "project_key": self.project_key,
                "run_id": self.run_id, "cwd": self.cwd, "label": self.label, "alive": self.alive,
                "exit_code": self.exit_code, "cleanup_failed": self.cleanup_failed,
                "agent": self.agent, "session_id": self.session_id, "in_panel": self.in_panel,
                "card_key": self.card_key}


TERMINALS: dict[str, Terminal] = {}
_registry_lock = threading.Lock()


_finalize_lock = threading.Lock()


def _finalize(t: Terminal) -> bool:
    """Once per terminal, from close or a natural exit (UI3-03): release its locks (ticket, card,
    project) and audit a card session's end. The audit is admitted like any write, so under
    maintenance it is skipped with a warning instead of writing behind the gate (UI3-08)."""
    with _finalize_lock:
        if t.finalized:
            return False
        t.finalized = True
    t.holds.close()
    if t.kind == "resume" and t.run_id:
        from app import record_interactive_ended, _inflight_work, MaintenanceRefused
        try:
            with _inflight_work():
                record_interactive_ended(t.run_id, t.session_id)
        except MaintenanceRefused as exc:
            logger.warning("closure of %s not recorded: %s", t.term_id, exc)
        except Exception:
            logger.exception("closure audit for %s failed", t.term_id)
    return True


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
    if t.kind == "resume" and not t.closing:  # exited by itself: free its card before the next-state choice
        _finalize(t)
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
    # Who prompts is decided by who closed a live session, not by who won _finalize: killing the
    # shell also wakes the reader, which would otherwise finalize first (FB2-01).
    with _finalize_lock:
        prompt = t.alive and not t.finalized
        t.closing = True
    try:
        _kill_session(t)
    except Exception as exc:  # enumeration failed: keep the tab, flagged, so nothing is lost silently
        t.cleanup_failed = True
        logger.error("terminal %s cleanup failed: %s", term_id, exc)
        return {"error": f"cleanup failed: {exc}", **t.info()}
    _finalize(t)  # releases its locks; a card session's end is audited once, from any entry point
    with _registry_lock:
        TERMINALS.pop(term_id, None)
    # run_id only when this close ended a live session: an already-exited one was offered its choice (FB-05)
    return {"ok": True, "term_id": term_id, "run_id": t.run_id if t.kind == "resume" and prompt else None}


def close_all() -> None:
    for term_id in list(TERMINALS):
        with contextlib.suppress(Exception):
            close_terminal(term_id)


def _spawn(t: Terminal, argv: list[str], env: dict, cols: int, rows: int, socketio) -> None:
    pid, fd = pty.fork()
    if pid == 0:  # child: a new session (pty.fork), so it is its own session leader
        try:
            # Nothing of the runner leaks into the shell: without this the child inherits the
            # runner's listening socket on :8510, and a runner restart cannot bind it again while
            # any terminal (or a resumed agent in it) is still open.
            for fd_ in [int(n) for n in os.listdir("/dev/fd") if n.isdigit() and int(n) > 2]:
                try:  # only the descriptors that exist (SC_OPEN_MAX can be huge)
                    os.close(fd_)
                except OSError:
                    pass
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


def _session_card_folder(t, project, rec: dict, data: dict):
    """Where a session card's tab opens (SBR-002/007): the session's folder from session_target.
    The card's ticket lock is taken from its identifier (the lock file needs no binding), so the
    tab contends with reply and drag. Only a durable binding whose worktree is that folder takes
    the worktree path; otherwise the project's effective confidentiality applies. Returns the
    project as the tab's policy sees it."""
    import dataclasses
    import projects
    from app import _board_sessions, _durable_binding, _effective_project
    target = projects.session_target(project, str(data.get("agent")), str(data.get("session_id") or ""),
                                     board_ids=_board_sessions()[0])
    cwd = os.path.realpath(target["cwd"])
    idents = [i for i in (rec.get("issue_identifier"),) if i]
    durable = _durable_binding(rec.get("linear_issue_id"), rec.get("task_id")) or {}
    wid = durable.get("issue_identifier") if durable.get("project_key") == project.key else None
    in_worktree = bool(wid) and os.path.realpath(projects.worktree_path(project, wid)) == cwd
    if in_worktree and wid not in idents:
        idents.append(wid)
    for ident in idents:
        t.holds.enter_context(projects.ticket_lock(project.key, ident))
    if in_worktree:
        projects.load_binding(project, wid)
        project = _effective_project(project, wid)
        t.ticket = wid
    from app import session_confidential
    known = [rec["confidential"]] if "confidential" in rec else []
    # On both branches: the record and the session's history count too (SBI-001/008/013).
    if session_confidential(project, target["cwd"], rec.get("linear_issue_id"), rec.get("task_id"), *known,
                            sid=str(data.get("session_id") or "")) is not False:
        project = dataclasses.replace(project, confidential=True)
    t.cwd = target["cwd"]
    return project


def open_terminal(data: dict, socketio) -> dict:
    """term_open: shell (project main path, bound worktree, or runner root), resume, or run view."""
    _ensure_imports()
    import projects
    kind = (data or {}).get("kind") or "shell"
    cols, rows = int(data.get("cols") or 120), int(data.get("rows") or 24)
    t = Terminal(term_id=uuid.uuid4().hex[:12], kind=kind)
    t.in_panel = data.get("in_panel", True) is not False  # a card's terminal stays out of the panel (C2)
    if kind == "run":
        t.run_id = str(data.get("run_id") or "")
        t.project_key = data.get("project_key")
        t.label = f"{t.project_key or 'run'} · run · {t.run_id[:6]}"
        t.alive = True
        TERMINALS[t.term_id] = t
        return t.info()
    if live_count() >= MAX_TERMINALS:
        return {"error": f"terminal limit reached ({MAX_TERMINALS} live); close one first"}
    rec = None
    if kind == "resume":
        # A resume tied to a run (card Terminal tab, run tab, or a Projects-panel session that a run
        # recorded) is described by that run's record, never by the request: project, ticket and
        # agent come from the record, the session must be the run's, a conflicting project is
        # refused (UI8-01). So the project policy and the card's lock always apply.
        from app import card_run_for_session, _latest_record
        run_id = data.get("run_id") or card_run_for_session(str(data.get("agent")), str(data.get("session_id") or ""))
        if run_id:
            rec = _latest_record(str(run_id))
            if not rec:
                return {"error": f"unknown run {run_id}"}
            if not rec.get("agent_session_id") or rec["agent_session_id"] != str(data.get("session_id") or ""):
                return {"error": "that session does not belong to this run"}  # recorded and matching (REV-04, IR9-01)
            if rec.get("project_key") and data.get("project_key") not in (None, rec["project_key"]):
                return {"error": "this session belongs to another project's run"}
            sess = rec.get("resume_session") if isinstance(rec.get("resume_session"), dict) else None
            if sess is not None or rec.get("source") == "session":
                # A session card: the folder is the session's own, resolved server-side, never a
                # worktree binding read from inline fields, whatever the intent's validity (SBR-002/007).
                data = {**data, "run_id": str(run_id), "agent": rec.get("agent") or data.get("agent"),
                        "project_key": rec.get("project_key") or (sess or {}).get("project_key") or rec.get("session_project"),
                        "ticket": None, "session_card": True}
            else:
                data = {**data, "run_id": str(run_id), "agent": rec.get("agent") or data.get("agent"),
                        "project_key": rec.get("project_key"),
                        "ticket": rec.get("issue_identifier") if rec.get("project_key") else None}
    project = None
    key = data.get("project_key")
    admission = contextlib.ExitStack()  # held only until the tab is registered
    try:
        if key:
            # A project tab holds the project's shared lifecycle lock while open, so remove and
            # path/confidential/seed edits wait until it closes (REGUI-004).
            t.holds.enter_context(projects.project_lock(key))
            project = projects.get_project(key, projects.load_registry(errors={}))
            t.project_key = key
        ticket = data.get("ticket")
        if data.get("session_card") and project:
            project = _session_card_folder(t, project, rec, data)
        elif kind == "resume" and project and data.get("cwd") and not ticket:
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
        elif not (data.get("session_card") and project):  # a session card's folder is already set
            t.cwd = str(project.path if project else ROOT or _PROTO)
        if rec is not None:
            # The run's card: a runner-root card's session holds the card lock while open, so quick
            # reply, retry and dispatch of it are refused (C2, UI-03); a project card is held by its
            # ticket lock above (UI2-01, UI8-01).
            t.card_key = str(rec.get("linear_issue_id") or rec.get("task_id") or data["run_id"])
            t.run_id = str(data["run_id"])
            if not rec.get("project_key"):
                t.holds.enter_context(projects.card_lock(t.card_key))
        if project and project.confidential:
            from app import _records_unsafe
            problem = _records_unsafe()  # handoffs from this tab land in the run records (I6-04)
            if problem:
                raise projects.ProjectError(problem)
            t.confidential = True
        argv = [os.environ.get("SHELL", "/bin/zsh"), "-l"]
        if kind == "resume":
            t.agent, t.session_id = str(data.get("agent")), str(data.get("session_id"))
            # Admission under the session lock: a rename/remove holding it refuses this open,
            # and once registered below the tab is in the live set (A, R02).
            admission.enter_context(projects.session_lock(t.agent, t.session_id))
            from app import _live_session_ids
            if (t.agent, t.session_id) in _live_session_ids():  # a headless run (or another tab) is in it (UI14-01)
                raise projects.ProjectError("this session is running right now; open it when the run has ended")
            resume = interactive_resume_argv(str(data.get("agent")), str(data.get("session_id")), project)
            if not resume:
                t.holds.close()
                return {"error": "no eligible interactive resume for this session"}
            if data.get("cwd") and not data.get("session_card") and (not t.ticket or Path(os.path.realpath(
                    str(data["cwd"]))).is_relative_to(Path(os.path.realpath(t.cwd)))):
                t.cwd = str(data["cwd"])
            argv = [argv[0], "-l", "-c", shlex.join(resume) + f"; exec {shlex.quote(argv[0])} -l"]
        short = (t.ticket or Path(t.cwd).name)[:16]
        t.label = f"{key or 'runner'} · {kind} · {short}"
        _spawn(t, argv, _shell_env(project), cols, rows, socketio)
        TERMINALS[t.term_id] = t
    except Exception as exc:
        t.holds.close()
        return {"error": str(exc)}
    finally:
        admission.close()
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


def _forward_input(t: Terminal, text: str, socketio, refused: str | None = None) -> None:
    completed = _track_input(t, text)
    if completed is not None and refused is not None:
        if t.pending_handoff:  # a handoff under maintenance: neither recorded nor sent
            t.pending_handoff, t.input_buffer = None, ""
            socketio.emit("term_output", {"term_id": t.term_id, "data": f"\r\n[{refused}]\r\n"},
                          to=_room(t.term_id))
            return
    elif completed is not None:
        _record_pending_handoff(t, completed, socketio)
    with contextlib.suppress(OSError):
        os.write(t.fd, text.encode())


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
            if any(c in text for c in "\r\n"):
                # Only a completed line can record a handoff, so every newline is admitted first;
                # refused, it may still be forwarded but never records (BUILD-011, no race with
                # a concurrent skill_selected).
                from app import _inflight_work, MaintenanceRefused
                try:
                    with _inflight_work():
                        _forward_input(t, text, socketio)
                except MaintenanceRefused as exc:
                    _forward_input(t, text, socketio, refused=str(exc))
                return
            _forward_input(t, text, socketio)

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

        @socketio.on("term_show")
        def term_show(data):
            """'Show in panel': from now on a reload/reconnect attaches it to the panel (C2)."""
            t = TERMINALS.get((data or {}).get("term_id"))
            if t is None:
                return {"error": "unknown terminal"}
            t.in_panel = True
            return t.info()

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
