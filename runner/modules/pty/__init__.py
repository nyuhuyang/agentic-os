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

try:  # runner/ is on sys.path when the dashboard imports it as `app`
    import claude_account
except ImportError:  # imported as a package (tests, tooling)
    from runner import claude_account

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
    reader_done: bool = False      # the reader saw the PTY end (set and read under _finalize_lock)
    # one cleanup at a time; reentrant so a close holds it across its cleanup *and* its outcome (ICS-40/46)
    end_lock: threading.RLock = field(default_factory=threading.RLock)
    superseding: int = 0           # closes for a user action in progress or done (ICS-37/40/45)
    cleaned: bool = False          # its session's processes were proven gone (set under end_lock, ICS-48)

    @property
    def superseded(self) -> bool:  # ended for a user action: viewers drop its next-state choice
        return self.superseding > 0

    def info(self) -> dict:
        return {"term_id": self.term_id, "kind": self.kind, "project_key": self.project_key,
                "run_id": self.run_id, "cwd": self.cwd, "label": self.label, "alive": self.alive,
                "exit_code": self.exit_code, "cleanup_failed": self.cleanup_failed,
                "agent": self.agent, "session_id": self.session_id, "in_panel": self.in_panel,
                "card_key": self.card_key}


TERMINALS: dict[str, Terminal] = {}


def interactive_agents_in(checkout) -> list[str]:
    """Agent (resume) tabs working inside `checkout` whose processes are not proven gone: a manual
    merge waits for them (CM-024). Path-based, so every registration of the folder counts."""
    root = Path(os.path.realpath(str(checkout)))
    out = []
    for t in list(TERMINALS.values()):
        if t.kind != "resume" or (not t.alive and t.cleaned):
            continue
        with contextlib.suppress(Exception):
            if Path(os.path.realpath(t.cwd)).is_relative_to(root):
                out.append(t.term_id)
    return out
_SOCKETIO = None  # set at registration; close_terminal announces the ends it owns
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
        from app import record_interactive_ended, _inflight_work, MaintenanceRefused, _after_card_run, _latest_record
        try:
            with _inflight_work():
                record_interactive_ended(t.run_id, t.session_id)
                # admitted like the audit: the card's session is named once the terminal's group
                # is gone (DP-11); under maintenance neither runs (PVST-04)
                with contextlib.suppress(Exception):
                    issue_id = (_latest_record(t.run_id) or {}).get("linear_issue_id")
                    _after_card_run(t.term_id, issue_id, t.agent, t.session_id, t.pid, kind="term")
        except MaintenanceRefused as exc:
            logger.warning("closure of %s not recorded: %s", t.term_id, exc)
        except Exception:
            logger.exception("closure audit for %s failed", t.term_id)
    return True


def _room(term_id: str) -> str:
    return f"term:{term_id}"


def card_terminal(card_key=None, project_key=None, ticket=None, agent=None, session_id=None) -> str | None:
    """The live dashboard terminal holding a card, by its card key, its (project, ticket), or its
    session; None when nothing in the dashboard holds it (a headless run or an outside process).
    A refusal carries this id so the user can end that session and continue."""
    for t in list(TERMINALS.values()):
        if t.finalized or not ((t.alive or t.cleanup_failed) and t.pid):  # a failed cleanup still holds its card
            continue
        if (card_key and t.card_key == str(card_key)) \
                or (project_key and ticket and (t.project_key, t.ticket) == (project_key, ticket)) \
                or (agent and session_id and (t.agent, t.session_id) == (agent, session_id)):
            return t.term_id
    return None


def card_interactive(body: dict, **keys) -> dict:
    """`body` plus `code`/`term_id` when a live dashboard terminal holds the card, else unchanged."""
    term_id = card_terminal(**keys)
    return {**body, "code": "card_interactive", "term_id": term_id} if term_id else body


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


def _agent_exited(t: Terminal) -> bool:
    """A card session's agent process has exited (reaped here, exit code kept)."""
    with contextlib.suppress(ChildProcessError, OSError):
        pid, status = os.waitpid(t.pid, os.WNOHANG)
        if pid:
            t.exit_code = os.waitstatus_to_exitcode(status)
            return True
    return False


def _drain(t: Terminal, socketio, budget: float = 0.3) -> None:
    """Forward what is already in the PTY (bounded), e.g. an exiting agent's final output."""
    deadline = time.monotonic() + budget
    while time.monotonic() < deadline:
        try:
            r, _, _ = select.select([t.fd], [], [], 0.05)
            if not r:
                return
            data = os.read(t.fd, 4096)
        except (OSError, TypeError, ValueError):
            return
        if not data:
            return
        with t.lock:
            _append_scrollback(t, data)
            socketio.emit("term_output", {"term_id": t.term_id, "data": data.decode("utf-8", "replace")},
                          to=_room(t.term_id))


def _reader(t: Terminal, socketio) -> None:
    """Read the PTY; append + emit under the terminal lock so attach sees each byte once."""
    # A card's session ends with its agent even if a leftover background process keeps the PTY
    # open (no EOF): its card must not stay held by a process nobody sees (AC1, ICS-22).
    card_bound = t.kind == "resume" and bool(t.run_id) and t.pid is not None
    agent_gone, next_check = False, 0.0
    while True:
        try:
            r, _, _ = select.select([t.fd], [], [], 0.2)
            # checked on a schedule, busy PTY or not: a chatty leftover cannot hide the exit (ICS-24)
            if card_bound and not t.closing and time.monotonic() >= next_check:
                next_check = time.monotonic() + 0.5
                if _agent_exited(t):
                    agent_gone = True
                    _drain(t, socketio)  # the agent's last words still reach the view
                    break
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
    # Who ends the terminal is decided once, here, under the lock close_terminal takes: while a close
    # is in progress it owns the end entirely — on success it marks it dead, finalizes and says so;
    # on a failed cleanup the terminal stays live, held and retryable. A reader that yields never takes
    # the end back later; a reader that owns it finalizes only after its own cleanup (ICS-31..34).
    with _finalize_lock:
        t.reader_done = True
        own = not t.closing
    if not own:
        return
    if card_bound:
        # However the PTY ended (agent exit seen, EOF or EIO), a card session's leftovers in its
        # session go with it, as on End session; EOF alone never proves they are gone (ICS-27).
        if not agent_gone:
            _agent_exited(t)  # keep its exit code before the cleanup reaps it
        try:
            with t.end_lock:  # a close waiting on it reuses this result instead of repeating it (ICS-48)
                _kill_session(t)
                t.cleaned = True
            t.cleanup_failed = False  # proven gone now, whatever an earlier attempt said (ICS-35)
        except Exception as exc:
            # Not proven gone: the terminal stays live, flagged, holding its card, so End session can
            # retry the cleanup; nothing else may start in that checkout meanwhile (ICS-25).
            t.cleanup_failed = True
            logger.error("terminal %s: leftover processes after the agent exited, cleanup failed: %s", t.term_id, exc)
            with contextlib.suppress(Exception):
                socketio.emit("term_output", {"term_id": t.term_id, "data": "\r\n[agent exited; leftover processes could "
                              "not be ended — use End session to retry]\r\n"}, to=_room(t.term_id))
            return
    from app import _JOB_LOCK, _mark_closing
    # The closing marker first, then the terminal stops counting as live, at the boundary the
    # rename check snapshots under (R10-02). ponytail: the shell's own group stands for the
    # terminal's session; a child that moved to another group outlives the check.
    with _JOB_LOCK:
        if t.kind == "resume" and t.session_id:
            _mark_closing(t.agent, t.session_id, t.pid)
        t.alive = False
    with t.lock:
        if t.pid:
            with contextlib.suppress(ChildProcessError, OSError):
                pid, status = os.waitpid(t.pid, os.WNOHANG)
                if pid:
                    t.exit_code = os.waitstatus_to_exitcode(status)
    if t.kind == "resume":  # exited by itself: free its card before the next-state choice
        _finalize(t)
    # read after the cleanup: a close for an action that arrived meanwhile has marked it superseded
    _remember_end(t)
    socketio.emit("term_exit", {"term_id": t.term_id, "exit_code": t.exit_code, "superseded": t.superseded},
                  to=_room(t.term_id))


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
    """SIGHUP, then SIGTERM, then SIGKILL every group in the shell's session; reap; close.
    Serialized per terminal: a reader's and a close's cleanup never overlap, and the descriptor is
    closed once (ICS-40)."""
    with t.end_lock:
        _kill_session_locked(t)


def _kill_session_locked(t: Terminal) -> None:
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


# Recently ended terminals (bounded): a close that finds one gone says how it ended, so a viewer that
# missed the exit event never offers a choice its end made obsolete (ICS-41).
ENDED: dict[str, dict] = {}
_ENDED_MAX = 200


def _remember_end(t: Terminal) -> None:
    ENDED[t.term_id] = {"run_id": t.run_id if t.kind == "resume" else None, "superseded": t.superseded}
    while len(ENDED) > _ENDED_MAX:
        ENDED.pop(next(iter(ENDED)))


def close_terminal(term_id: str, superseded: bool = False) -> dict:
    """End a terminal. `superseded`: ended for an action the user is taking (retry, move…), so every
    viewer's next-state choice for it is obsolete (ICS-37)."""
    t = TERMINALS.get(term_id)
    if t is None:
        return {"error": "unknown terminal", **({"ended": ENDED[term_id]} if term_id in ENDED else {})}
    if superseded:  # per request, before any cleanup: whoever finishes it announces it superseded
        with _finalize_lock:
            t.superseding += 1
    # Who prompts is decided by who closed a live session, not by who won _finalize: killing the
    # shell also wakes the reader, which would otherwise finalize first (FB2-01).
    with _finalize_lock:
        prompt = t.alive and not t.finalized
        t.closing = True
    # The cleanup and its outcome (a failed request withdrawing its intent) happen under the terminal's
    # end lock, so a concurrent close waiting on it publishes only after that outcome (ICS-46).
    with t.end_lock:
        try:
            if not t.cleaned:  # already proven gone (the reader's cleanup): reuse it, do not repeat (ICS-48)
                _kill_session(t)
                t.cleaned = True
            t.cleanup_failed = False
        except Exception as exc:  # enumeration failed: keep the tab, flagged, so nothing is lost silently
            t.cleanup_failed = True
            logger.error("terminal %s cleanup failed: %s", term_id, exc)
            # Not proven gone: ownership stays (locks held, terminal registered, flagged and still matched
            # by card_terminal), so End session can retry; a reader that has not ended yet takes the end
            # over again, and finalizes only after its own cleanup succeeds (ICS-29).
            with _finalize_lock:
                t.closing = False
                if superseded:  # this request did not end it: only its own intent is withdrawn (ICS-43/45)
                    t.superseding -= 1
            return {"error": f"cleanup failed: {exc}", **t.info()}
    _finalize(t)  # releases its locks; a card session's end is audited once, from any entry point
    with _registry_lock:
        TERMINALS.pop(term_id, None)
    _remember_end(t)
    if _SOCKETIO is not None:  # other viewers of it learn it ended (the reader leaves that to the close)
        with contextlib.suppress(Exception):
            _SOCKETIO.emit("term_exit", {"term_id": term_id, "exit_code": t.exit_code, "superseded": t.superseded},
                           to=_room(term_id))
    # run_id only when this close ended a live session: an already-exited one was offered its choice (FB-05)
    return {"ok": True, "term_id": term_id, "run_id": t.run_id if t.kind == "resume" and prompt else None,
            "superseded": t.superseded}  # ended for someone's action: no viewer offers its choice (ICS-44)


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
    claude_account.activate_env(env)  # AGE-125: after project.env, a tab uses the active account
    return env


def interactive_resume_argv(agent: str, session_id: str, project) -> list[str] | None:
    """Resume command for an interactive tab, through the same policy as headless dispatch
    (Decision 10 / MPD-26). None = no eligible interactive form (button hidden)."""
    import project_runs
    if agent == "dsh":
        return None  # dsh has no interactive TUI
    if project is None:  # runner-root session: no project policy applies
        return (["claude", *project_runs.CLAUDE_SETTINGS, "--resume", session_id] if agent == "claude"
                else ["codex", "resume", session_id])
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
            # A card's session ends with its agent, so the card's lock goes with it (no shell is
            # left holding it); an unbound resume keeps a shell in its folder afterwards.
            tail = "" if rec is not None else f"; exec {shlex.quote(argv[0])} -l"
            # AGE-129: after the login profile has set PATH, so the sandboxed `codex` stays first
            import project_runs
            path = (f"PATH={shlex.quote(str(project_runs.SANDBOXED_BIN))}:\"$PATH\" "
                    if t.agent == "claude" and project and project.confidential else "")
            argv = [argv[0], "-l", "-c", path + shlex.join(resume) + tail]
        short = (t.ticket or Path(t.cwd).name)[:16]
        t.label = f"{key or 'runner'} · {kind} · {short}"
        # An agent tab starts and registers under its checkout's merge gate: never between a manual
        # merge's activity check and its merge (CM-024). Lock order: card/ticket -> gate.
        from app import _checkout_gate
        # gated by the folder it actually runs in, not by the key it was opened under (CM-028)
        gate = _checkout_gate(t.cwd) if kind == "resume" else contextlib.nullcontext()
        with gate:
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
                   extra={"project_key": t.project_key, "term_id": t.term_id,
                          "confidential": bool(confidential)} if t.project_key else None)
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
        global _SOCKETIO
        _ensure_imports()
        _SOCKETIO = socketio
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
            return close_terminal((data or {}).get("term_id"), superseded=bool((data or {}).get("superseded")))

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
