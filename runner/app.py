#!/usr/bin/env python3
"""AgenticOS web dashboard.

Usage:
    ../.venv/bin/python3 runner/app.py
    ../.venv/bin/python3 runner/app.py --port 8510
    ../.venv/bin/python3 runner/app.py --debug
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import subprocess
import sys
import time
import urllib.request
import uuid
import tomllib
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

import fcntl
import os
import pty
import select
import struct
import termios
import threading

from flask import Flask, Response, jsonify, render_template, request, stream_with_context
from flask_socketio import SocketIO, emit

_HERE = Path(__file__).resolve().parent              # runner/
_PROTO = _HERE.parent                                # agentic-os root
WORKSPACE_ROOT = _PROTO.parent.parent
CODEX_HOME = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
CODEX_CONFIG = CODEX_HOME / "config.toml"

# Load .env at proto root so $VAR references in WORKFLOW.md resolve without restarting
_DOTENV = _PROTO / ".env"
if _DOTENV.exists():
    for _line in _DOTENV.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

ROOT = _PROTO

sys.path.insert(0, str(_HERE))
from usage_reader import (
    compute_stats as _compute_usage,
    compute_windows as _compute_windows,
    load_codex_usage as _load_codex_usage,
    cross_check_stats_cache as _cross_check,
    _collect_jsonl_usage,
    _fmt as _fmt_tok_usage,
)

# Lazy import — deepseek_monitor may not be installed
try:
    import deepseek_monitor as _deepseek_monitor
    _HAS_DEEPSEEK_MONITOR = True
except ImportError:
    _deepseek_monitor = None  # type: ignore[assignment]
    _HAS_DEEPSEEK_MONITOR = False

# ── Module registry ────────────────────────────────────────────────────────
from runner.core.module_registry import registry as _module_registry
from runner.modules import discover_all as _discover_modules
_AVAILABLE_MODULES: list[str] = []

MASTER_REGISTRY_JSON = Path(os.environ.get("REGISTRY_JSON", str(WORKSPACE_ROOT / ".codex" / "registry.json")))
CLAUDE_REGISTRY_JSON = WORKSPACE_ROOT / ".claude" / "registry.json"
CLAUDE_REGISTRY_MD = WORKSPACE_ROOT / ".claude" / "registry.md"
OUTPUTS_DIR = _PROTO / "outputs"
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
RUN_LOG = OUTPUTS_DIR / "run_log.jsonl"
JOB_STATE = OUTPUTS_DIR / "job_state.json"

# Structured state directory — operational truth
STATE_DIR = _PROTO / "state"
STATE_DIR.mkdir(parents=True, exist_ok=True)
STATE_RUN_LOG = STATE_DIR / "runs.jsonl"
STATE_TASK_STATE = STATE_DIR / "task_state.json"
WIKI_LOG = ROOT / "wiki" / "log.md"
RUNNER = _HERE / "run_skill.py"
VAULT_PULSE_ROOTS = ("wiki", "raw", "outputs")

VENV_PYTHON = _PROTO / ".venv" / "bin" / "python3"

# In-memory running jobs: run_id -> {run_id, skill, started_at, prompt, last_progress_at}
_running_jobs: dict[str, dict] = {}
# Active subprocess handles for cancellation: run_id -> Popen
_running_procs: dict[str, "subprocess.Popen[bytes]"] = {}

STALL_TIMEOUT_S = 300
AI_RUN_TIMEOUT_S = int(os.environ.get("AI_RUN_TIMEOUT_S", "1800"))  # 30 min default

app = Flask(__name__, template_folder="templates")
socketio = SocketIO(app, cors_allowed_origins="*")

# ── PTY sessions ────────────────────────────────────────────────────────────
_pty_sessions: dict[str, int] = {}   # sid -> fd
_pty_input_buffers: dict[str, str] = {}
_pending_skill_handoffs: dict[str, dict[str, str]] = {}


def _pty_read_loop(sid: str, fd: int) -> None:
    while True:
        try:
            r, _, _ = select.select([fd], [], [], 0.1)
            if r:
                data = os.read(fd, 1024).decode("utf-8", errors="replace")
                socketio.emit("pty_output", {"data": data}, to=sid)
        except OSError:
            break
    _pty_sessions.pop(sid, None)


def _record_pending_handoff(sid: str, line: str) -> None:
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


def _track_pty_input(sid: str, text: str) -> None:
    buf = _pty_input_buffers.get(sid, "")
    for ch in text:
        if ch in ("\r", "\n"):
            _record_pending_handoff(sid, buf)
            buf = ""
        elif ch in ("\x7f", "\b"):
            buf = buf[:-1]
        elif ch == "\x1b":
            continue
        elif ch.isprintable() or ch == "\t":
            buf += ch
    _pty_input_buffers[sid] = buf


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
        os.chdir(str(ROOT))
        os.execvpe(shell, [shell], env)
    else:
        _pty_sessions[sid] = fd
        _pty_input_buffers[sid] = ""
        _set_winsize(fd, rows, cols)
        threading.Thread(target=_pty_read_loop, args=(sid, fd), daemon=True).start()


@socketio.on("pty_input")
def pty_input(data):
    fd = _pty_sessions.get(request.sid)
    if fd is not None:
        text = data["data"]
        _track_pty_input(request.sid, text)
        os.write(fd, text.encode())


@socketio.on("skill_selected")
def skill_selected(data):
    skill = (data or {}).get("skill", "").strip()
    phrase = (data or {}).get("phrase", "").strip()
    if not skill:
        return
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


def _set_winsize(fd: int, rows: int, cols: int) -> None:
    try:
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

def _python() -> str:
    return str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable


WORKFLOW_MD = _PROTO / "WORKFLOW.md"


def _read_registry_json(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        skills = payload.get("skills", {})
        return skills if isinstance(skills, dict) else {}
    except Exception:
        return {}


def _registry_md_text(registry: dict[str, dict]) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Skill Registry",
        "",
        f"Generated: {now} · {len(registry)} skills",
        "",
        "| Skill | Stack | Risk | Confirm? | Exec mode | Schedulable | Entrypoint |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for name, entry in sorted(registry.items()):
        sec = entry.get("security", {})
        schedulable = "yes" if entry.get("schedule_eligible") else "—"
        ep = f"`{entry['entrypoint']}`" if entry.get("entrypoint") else "—"
        confirm = "**yes**" if sec.get("confirmation_required") else "—"
        lines.append(
            f"| `{name}` | {entry.get('stack', 'uncategorized')} | {sec.get('risk_level', '?')} | {confirm} | {entry.get('execution_mode', 'local_only')} | {schedulable} | {ep} |"
        )

    lines += ["", "## Stack summary", "", "| Stack | Skills |", "| --- | --- |"]
    stacks: dict[str, list[str]] = {}
    for name, entry in registry.items():
        stacks.setdefault(entry.get("stack", "uncategorized"), []).append(name)
    for stack, skills in sorted(stacks.items()):
        lines.append(f"| {stack} | {', '.join(f'`{s}`' for s in sorted(skills))} |")

    lines += ["", "## Schedulable skills", ""]
    schedulable = {n: e for n, e in registry.items() if e.get("schedule_eligible")}
    if schedulable:
        for name, entry in sorted(schedulable.items()):
            ep = entry.get("entrypoint") or "no script (AI-only)"
            lines.append(f"- **`{name}`** ({entry.get('execution_mode', 'local_only')}) — {ep}")
    else:
        lines.append("No schedulable skills registered yet.")
    return "\n".join(lines) + "\n"


def _filter_registry_for_agent(agent: str | None) -> dict[str, dict]:
    agent = (agent or "").strip().lower()
    registry = _read_registry_json(MASTER_REGISTRY_JSON)
    if not agent:
        return registry
    return {
        name: entry
        for name, entry in registry.items()
        if agent in (entry.get("agents") or [])
    }


def _ensure_claude_registry() -> dict[str, dict]:
    registry = _filter_registry_for_agent("claude")
    CLAUDE_REGISTRY_JSON.parent.mkdir(parents=True, exist_ok=True)
    CLAUDE_REGISTRY_JSON.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "skill_count": len(registry),
                "skills": registry,
            },
            indent=2,
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )
    CLAUDE_REGISTRY_MD.write_text(_registry_md_text(registry), encoding="utf-8")
    return registry


def load_registry(agent: str | None = None) -> dict[str, dict]:
    agent = (agent or "").strip().lower()
    if agent == "claude":
        return _ensure_claude_registry()
    if agent == "codex":
        return _filter_registry_for_agent("codex")
    if agent == "deepseek":
        return _filter_registry_for_agent("deepseek")
    return _read_registry_json(MASTER_REGISTRY_JSON)


def _load_workflow_config() -> dict:
    if not WORKFLOW_MD.exists():
        return {}
    try:
        text = WORKFLOW_MD.read_text(encoding="utf-8")
        # Extract YAML front matter between --- delimiters
        if text.startswith("---"):
            end = text.find("---", 3)
            if end != -1:
                import yaml
                return yaml.safe_load(text[3:end]) or {}
    except Exception:
        pass
    return {}


def _save_workflow_config(cfg: dict) -> None:
    try:
        import yaml
        front = yaml.dump(cfg, default_flow_style=False, allow_unicode=True)
        WORKFLOW_MD.write_text(f"---\n{front}---\n", encoding="utf-8")
    except Exception:
        pass


def _archive_stale_sent() -> None:
    if not RUN_LOG.exists():
        return
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    lines = RUN_LOG.read_text(encoding="utf-8").splitlines()
    appended = []
    for line in lines:
        try:
            r = json.loads(line)
            if r.get("status") == "sent":
                started = datetime.fromisoformat(r["started_at"])
                if started.tzinfo is None:
                    started = started.replace(tzinfo=timezone.utc)
                if started < cutoff:
                    rid = r.get("run_id", "")
                    archived = {**r, "status": "archived", "prev_status": "sent"}
                    appended.append(json.dumps(archived))
                    if rid:
                        socketio.emit("run_state_change", {"run_id": rid, "state": "archived"})
        except Exception:
            continue
    if appended:
        with RUN_LOG.open("a", encoding="utf-8") as f:
            f.write("\n".join(appended) + "\n")


def _stall_detection_loop() -> None:
    last_cleanup = 0.0
    while True:
        time.sleep(30)
        now = time.monotonic()
        for run_id, job in list(_running_jobs.items()):
            last = job.get("last_progress_at", now)
            if now - last > STALL_TIMEOUT_S:
                skill = job.get("skill", "unknown")
                started_at = job.get("started_at", datetime.now(timezone.utc).isoformat())
                _running_jobs.pop(run_id, None)
                proc = _running_procs.pop(run_id, None)
                if proc:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                _write_run_log(skill, "stalled", started_at, 0.0,
                               prompt=job.get("prompt", ""), error="stalled", run_id=run_id,
                               linear_issue_id=job.get("linear_issue_id"))
                socketio.emit("run_state_change", {"run_id": run_id, "state": "stalled", "skill": skill})

        # Auto-archive stale sent records older than 24h (runs once per hour)
        if time.monotonic() - last_cleanup > 3600:
            last_cleanup = time.monotonic()
            _archive_stale_sent()


# Linear issue cache: issue_id -> normalized issue dict
_linear_issues_cache: dict[str, dict] = {}
# Track which In Progress issues have been dispatched: issue_id -> run_id
_linear_dispatched: dict[str, str] = {}
_linear_dispatches_warmed = False
# Issue IDs dismissed from board (archived locally, not changed in Linear)
_linear_dismissed: set[str] = set()
_DISMISSED_PATH = OUTPUTS_DIR / "dismissed_linear.json"

def _load_dismissed() -> None:
    if _DISMISSED_PATH.exists():
        try:
            _linear_dismissed.update(json.loads(_DISMISSED_PATH.read_text()))
        except Exception:
            pass

def _save_dismissed() -> None:
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    _DISMISSED_PATH.write_text(json.dumps(list(_linear_dismissed)))


def _latest_linear_runs(include_archived: bool = True) -> dict[str, dict]:
    """Return newest local run record per Linear issue."""
    if not RUN_LOG.exists():
        return {}
    latest: dict[str, dict] = {}
    for line in reversed(RUN_LOG.read_text(encoding="utf-8").splitlines()):
        try:
            r = json.loads(line)
        except Exception:
            continue
        issue_id = r.get("linear_issue_id")
        if not issue_id or issue_id in latest:
            continue
        if not include_archived and r.get("status") == "archived":
            continue
        if not r.get("run_id"):
            h = hashlib.md5(f"{r.get('started_at','')}{r.get('skill','')}".encode()).hexdigest()[:8]
            r["run_id"] = f"legacy-{h}"
        latest[issue_id] = r
    return latest


def _refresh_linear_dispatches_from_log() -> None:
    """Warm the duplicate-dispatch guard after server restarts.

    The in-memory guard must survive until the issue leaves In Progress again;
    otherwise a finished run can be redispatched immediately while Linear is
    still on the same issue state.
    """
    for issue_id, run in _latest_linear_runs(include_archived=True).items():
        run_id = run.get("run_id")
        if run_id and issue_id not in _linear_dispatched:
            _linear_dispatched[issue_id] = run_id


def _linear_issue_is_running(issue_id: str) -> bool:
    return any(
        job.get("linear_issue_id") == issue_id and job.get("state") == "running"
        for job in _running_jobs.values()
    )


def _linear_poll_states(tracker: dict) -> list[str]:
    active_states = list(tracker.get("active_states", ["Todo", "In Progress", "In Review"]))
    if "Backlog" not in active_states:
        active_states.insert(0, "Backlog")
    if "In Review" not in active_states:
        active_states.append("In Review")
    terminal_states = list(tracker.get("terminal_states", ["Done", "Canceled", "Duplicate"]))
    seen: set[str] = set()
    ordered: list[str] = []
    for state in active_states + terminal_states:
        # Linear is the source of truth for board contents. Poll all configured
        # states even if an older workflow file still marks some as "hidden".
        if state not in seen:
            seen.add(state)
            ordered.append(state)
    return ordered


def _linear_state_key(state: str | None) -> str:
    return re.sub(r"\s+", " ", (state or "").strip()).lower()


def _is_linear_in_progress(state: str | None) -> bool:
    return _linear_state_key(state) == "in progress"


def _resolve_linear_state_name(issue: dict | None, target_state_key: str) -> str | None:
    """Return the real Linear state name for a normalized target key."""
    if not issue:
        return None

    target_state_key = _linear_state_key(target_state_key)
    states = issue.get("team_states") or []
    for state in states:
        name = (state.get("name") or "").strip()
        if name and _linear_state_key(name) == target_state_key:
            return name

    current_state = (issue.get("state") or "").strip()
    if current_state and _linear_state_key(current_state) == target_state_key:
        return current_state

    return {
        "todo": "Todo",
        "in progress": "In Progress",
        "in review": "In Review",
        "done": "Done",
        "canceled": "Canceled",
        "duplicate": "Duplicate",
    }.get(target_state_key)


_ISSUE_AGENT_MARKER_RE = re.compile(r"<!--\s*agent_backend:\s*(claude|codex|aider|deepseek)\s*-->\s*", re.IGNORECASE)
_LINEAR_COMMENT_MUTATION = """
mutation AgenticOSCommentCreate($issueId: String!, $body: String!) {
  commentCreate(input: { issueId: $issueId, body: $body }) {
    success
    comment { id createdAt body }
  }
}
"""


def _extract_issue_agent(description: str | None) -> str | None:
    if not description:
        return None
    match = _ISSUE_AGENT_MARKER_RE.search(description)
    if not match:
        return None
    return (match.group(1) or "").lower() or None


def _strip_issue_metadata(description: str | None) -> str:
    if not description:
        return ""
    return _ISSUE_AGENT_MARKER_RE.sub("", description).strip()


def _compose_issue_description(description: str, preferred_agent: str | None) -> str:
    base = (description or "").strip()
    if preferred_agent in {"claude", "codex", "deepseek"}:
        marker = f"<!-- agent_backend: {preferred_agent} -->"
        return f"{base}\n\n{marker}" if base else marker
    return base


def _normalize_linear_issue(issue: dict) -> dict:
    normalized = dict(issue or {})
    raw_description = normalized.get("description", "") or ""
    normalized["preferred_agent"] = _extract_issue_agent(raw_description)
    normalized["description"] = _strip_issue_metadata(raw_description)
    return normalized


def _linear_api_key_from_cfg(tracker: dict) -> str:
    api_key = tracker.get("api_key", "")
    if api_key.startswith("$"):
        api_key = os.environ.get(api_key[1:], "")
    return api_key


def _extract_real_errors(stderr_s: str) -> str:
    """Filter verbose agent stderr (Codex session log) to only real error lines."""
    lines = []
    for line in stderr_s.splitlines():
        # Rust tracing format: "2026-05-09T...Z ERROR ..."
        if ' ERROR ' in line or ' WARN ' in line:
            lines.append(line)
        # Python/generic error formats
        elif line.startswith(('Error:', 'error:', 'Traceback', 'Exception:')):
            lines.append(line)
    return '\n'.join(lines)


def _linear_comment_body(*, title: str, prompt: str = "", output: str = "", error: str = "",
                         feedback: str = "", attachments: list[dict] | None = None) -> str:
    sections: list[str] = [f"**{title}**"]
    if feedback.strip():
        sections.append(feedback.strip())
    if prompt.strip():
        sections.append(f"**Prompt**\n```\n{prompt.strip()}\n```")
    if output.strip():
        sections.append(f"**Output**\n```\n{output.strip()}\n```")
    if error.strip():
        sections.append(f"**Error**\n```\n{error.strip()}\n```")
    attachment_lines = [
        f"- [{a.get('name') or a.get('filename') or 'attachment'}]({a.get('url', '')})"
        for a in (attachments or []) if a.get("url")
    ]
    if attachment_lines:
        sections.append("**Attachments**\n" + "\n".join(attachment_lines))
    return "\n\n".join(s for s in sections if s).strip()


def _issue_agent_comment_body(agent: str, previous_agent: str | None = None) -> str:
    if agent == "codex":
        label = "Codex"
    elif agent == "deepseek":
        label = "DeepSeek"
    else:
        label = "Claude"
    if previous_agent and previous_agent != agent:
        if previous_agent == "codex":
            previous_label = "Codex"
        elif previous_agent == "deepseek":
            previous_label = "DeepSeek"
        else:
            previous_label = "Claude"
        feedback = f"Model changed from `{previous_label}` to `{label}`. This task stays on `{label}` until it finishes."
    else:
        feedback = f"Model locked to `{label}` for this task. All follow-up runs stay on the same agent to preserve continuity."
    return _linear_comment_body(title="AgenticOS Model", feedback=feedback)


def _post_linear_comment(issue_id: str, body: str) -> bool:
    """Bridge to LinearModule.post_comment or LocalTracker."""
    linear_mod = _module_registry.get("linear")
    if linear_mod and linear_mod._capability.get("available"):
        return linear_mod.post_comment(issue_id, body)
    logger.debug("No tracker available, comment for %s not posted", issue_id)
    return False

# Rule: `In Progress` means the agent is actively running; `In Review` means the agent has finished and is waiting for human review.
# Board status → Linear state name mapping
_BOARD_TO_LINEAR: dict[str, str] = {
    "todo": "Todo",
    "running": "In Progress",
    "review": "In Review",
    "success": "Done",
    "cancelled": "Canceled",
    "duplicate": "Duplicate",
    "rework": "In Progress",  # no direct Linear equivalent
    "merging": "In Progress",
}


def _push_linear_state_async(issue_id: str, board_status: str) -> None:
    """Bridge to LinearModule.push_state."""
    linear_mod = _module_registry.get("linear")
    if linear_mod and linear_mod._capability.get("available"):
        linear_mod.push_state(issue_id, board_status)
    else:
        logger.debug("No tracker available, state %s for %s not pushed", board_status, issue_id)


def _locked_task_agent(original: dict, requested_agent: str | None = None) -> tuple[str | None, str | None]:
    """Return (locked_agent, error_message)."""
    locked_agent = (original.get("agent") or "").strip().lower() or None
    if original.get("linear_issue_id"):
        issue = _linear_issues_cache.get(original["linear_issue_id"]) or {}
        locked_agent = (issue.get("preferred_agent") or locked_agent or "").strip().lower() or None
    if locked_agent not in {"claude", "codex", "deepseek"}:
        locked_agent = None
    requested = (requested_agent or "").strip().lower()
    if requested and locked_agent and requested != locked_agent:
        return locked_agent, f"Task is locked to {locked_agent}. Continue on the same agent until completion."
    return locked_agent, None


def _linear_dispatch_issue(issue: dict, cfg: dict) -> None:
    """Select skill via Claude routing call and dispatch against a Linear issue."""
    issue_id = issue["id"]
    if issue_id in _linear_dispatched:
        return  # already dispatched

    agent_cfg = cfg.get("agent", {})
    backend = issue.get("preferred_agent") or agent_cfg.get("backend", "claude")
    registry = load_registry(backend)
    skill_list = "\n".join(
        f"- {name}: {entry.get('purpose', '')[:100]}"
        for name, entry in registry.items()
    )
    routing_prompt = (
        f"Given this issue, return only the skill name that best matches.\n\n"
        f"Issue: {issue['identifier']} — {issue['title']}\n"
        f"{(issue.get('description') or '')[:500]}\n\n"
        f"Available skills:\n{skill_list}\n\n"
        f"Return exactly one skill name, nothing else."
    )
    try:
        result = subprocess.run(
            _ai_command(backend, routing_prompt, output_format="text"),
            cwd=str(ROOT),
            capture_output=True, text=True, timeout=60,
        )
        selected_skill = _extract_skill_name(result.stdout or "", registry)
    except Exception:
        selected_skill = "_prompt"

    run_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc).isoformat()
    t0 = time.monotonic()
    prompt = f"{issue['identifier']}: {issue['title']}\n\n{_strip_issue_metadata(issue.get('description') or '')}"

    _linear_dispatched[issue_id] = run_id
    _running_jobs[run_id] = {
        "run_id": run_id, "skill": selected_skill, "started_at": started_at,
        "prompt": prompt, "state": "running", "last_progress_at": time.monotonic(),
        "linear_issue_id": issue_id,
        "agent": backend,
    }
    _push_linear_state_async(issue_id, "running")
    socketio.emit("run_state_change", {"run_id": run_id, "state": "running", "skill": selected_skill})

    entry = registry.get(selected_skill, {})
    if entry.get("schedule_eligible") and entry.get("entrypoint"):
        cmd = [_python(), str(RUNNER), selected_skill]
    else:
        cmd = _ai_command(backend, prompt, output_format="json")

    try:
        proc = subprocess.Popen(cmd, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        _running_procs[run_id] = proc
        stdout_b, stderr_b = proc.communicate(timeout=AI_RUN_TIMEOUT_S)
        dur = time.monotonic() - t0
        ok = proc.returncode == 0
        stdout_s = stdout_b.decode("utf-8", errors="replace").strip()
        stderr_s = stderr_b.decode("utf-8", errors="replace").strip()
        error_s = _extract_real_errors(stderr_s)
        output, input_tokens, output_tokens, parsed_model = _parse_agent_output(backend, stdout_s)
        if backend == "deepseek":
            output = _execute_deepseek_commands(output)
        _running_jobs.pop(run_id, None)
        _running_procs.pop(run_id, None)
        # Linear issue remains a single card; completed output is written back as a comment.
        final_state = "review"
        _write_run_log(
            selected_skill, final_state, started_at, dur,
            prompt=prompt, output=output, error=error_s, run_id=run_id,
            linear_issue_id=issue_id, selected_skill=selected_skill,
            input_tokens=input_tokens, output_tokens=output_tokens,
            agent=backend, model=parsed_model or _agent_model(backend, cfg),
            task_id=run_id,
        )
        _push_linear_state_async(issue_id, final_state)
        _post_linear_comment(
            issue_id,
            _linear_comment_body(
                title="AgenticOS Run",
                prompt=prompt,
                output=output,
                error=error_s,
            ),
        )
        socketio.emit("run_state_change", {"run_id": run_id, "state": final_state, "skill": selected_skill})
        socketio.emit("run_logged", {"skill": selected_skill, "run_id": run_id})
    except subprocess.TimeoutExpired:
        dur = time.monotonic() - t0
        proc = _running_procs.pop(run_id, None)
        if proc:
            proc.kill()
        _running_jobs.pop(run_id, None)
        msg = f"Timed out after {AI_RUN_TIMEOUT_S}s"
        _write_run_log(
            selected_skill, "timeout", started_at, dur, prompt=prompt, error=msg,
            run_id=run_id, linear_issue_id=issue_id, agent=backend,
        )
        _post_linear_comment(issue_id, _linear_comment_body(title="AgenticOS Run Timeout", prompt=prompt, error=msg))
        socketio.emit("run_state_change", {"run_id": run_id, "state": "timeout", "skill": selected_skill})
    except Exception as e:
        _running_procs.pop(run_id, None)
        _running_jobs.pop(run_id, None)
        _write_run_log(
            selected_skill, "error", started_at, 0.0, prompt=prompt, error=str(e),
            run_id=run_id, linear_issue_id=issue_id, agent=backend,
        )
        _post_linear_comment(
            issue_id,
            _linear_comment_body(title="AgenticOS Run Error", prompt=prompt, error=str(e)),
        )
        socketio.emit("run_state_change", {"run_id": run_id, "state": "error", "skill": selected_skill})


def _linear_polling_loop() -> None:
    from linear_client import LinearClient
    global _linear_dispatches_warmed
    while True:
        try:
            cfg = _load_workflow_config()
            tracker = cfg.get("tracker", {})
            if tracker.get("kind") != "linear":
                time.sleep(30)
                continue
            api_key = tracker.get("api_key", "")
            if api_key.startswith("$"):
                api_key = os.environ.get(api_key[1:], "")
            project_slug = tracker.get("project_slug", "")
            team_id = tracker.get("team_id", "")
            if not api_key:
                time.sleep(30)
                continue

            interval_ms = cfg.get("polling", {}).get("interval_ms", 5000)

            client = LinearClient(api_key, project_slug)
            issues = client.fetch_issues(_linear_poll_states(tracker), team_id=team_id or None)
            if not _linear_dispatches_warmed:
                _refresh_linear_dispatches_from_log()
                _linear_dispatches_warmed = True

            new_cache: dict[str, dict] = {}
            in_progress_ids: set[str] = set()
            for issue in issues:
                issue_id = issue["id"]
                new_cache[issue_id] = _normalize_linear_issue(issue)

                # Auto-dispatch In Progress issues
                if _is_linear_in_progress(issue.get("state")):
                    in_progress_ids.add(issue_id)
                    if issue_id not in _linear_dispatched and not _linear_issue_is_running(issue_id):
                        threading.Thread(
                            target=_linear_dispatch_issue,
                            args=(issue, cfg),
                            daemon=True,
                        ).start()

            for issue_id in list(_linear_dispatched):
                if issue_id not in in_progress_ids and not _linear_issue_is_running(issue_id):
                    _linear_dispatched.pop(issue_id, None)

            _linear_issues_cache.clear()
            _linear_issues_cache.update(new_cache)
            socketio.emit("linear_issues_updated", {"count": len(new_cache)})

        except Exception as e:
            logger.error("Linear polling error: %s", e)

        time.sleep(max(1, interval_ms / 1000))


def _load_task_state() -> dict:
    """Load task state from state/task_state.json (operational truth).

    Returns a dict keyed by skill name, each value is a dict with:
        - "runs": list of run records (each with full lifecycle data)
        - "status": latest status (derived from last run)
        - "last_run": ISO timestamp of last run
        - "duration_s": duration of last run
    """
    if not STATE_TASK_STATE.exists():
        return {}
    try:
        data = json.loads(STATE_TASK_STATE.read_text(encoding="utf-8"))
        # Migrate old format (flat status dict) to new format
        if data and not any("runs" in v for v in data.values()):
            # Old format: {"skill": {"status": ..., "last_run": ..., "duration_s": ...}}
            new_data = {}
            for skill, entry in data.items():
                new_data[skill] = {
                    "runs": [{
                        "run_id": None,
                        "skill": skill,
                        "status": entry.get("status", "unknown"),
                        "started_at": entry.get("last_run", ""),
                        "duration_s": entry.get("duration_s", 0.0),
                        "agent": None,
                        "model": None,
                        "input_tokens": None,
                        "output_tokens": None,
                        "selected_skill": skill,
                        "attempt": 0,
                        "parent_run_id": None,
                        "linear_issue_id": None,
                        "error": "",
                        "output": "",
                        "prompt": "",
                    }],
                    "status": entry.get("status", "unknown"),
                    "last_run": entry.get("last_run", ""),
                    "duration_s": entry.get("duration_s", 0.0),
                }
            # Write back migrated format
            STATE_TASK_STATE.write_text(json.dumps(new_data, indent=2), encoding="utf-8")
            return new_data
        return data
    except Exception:
        return {}


def _load_legacy_job_state() -> dict:
    """Load legacy job state from outputs/job_state.json (backward compat)."""
    if not JOB_STATE.exists():
        return {}
    try:
        return json.loads(JOB_STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_state() -> dict:
    """Load task state from operational truth (state/task_state.json), fall back to legacy."""
    state = _load_task_state()
    if state:
        return state
    return _load_legacy_job_state()


def _load_runs_from(path: Path, limit: int = 20, include_archived: bool = False) -> list[dict]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    seen: set[str] = set()
    records = []
    for line in reversed(lines):
        try:
            r = json.loads(line)
            if "run_id" not in r:
                h = hashlib.md5(f"{r.get('started_at','')}{r.get('skill','')}".encode()).hexdigest()[:8]
                r["run_id"] = f"legacy-{h}"
            r.setdefault("output_path", "")
            run_id = r["run_id"]
            if run_id in seen:
                continue  # dedup: latest append wins
            seen.add(run_id)
            if not include_archived and r.get("status") == "archived":
                continue  # mark seen for dedup, but exclude from normal results
            records.append(r)
        except Exception:
            continue
        if len(records) >= limit:
            break
    return records


def load_runs(limit: int = 20, include_archived: bool = False) -> list[dict]:
    """Load runs from operational truth (state/runs.jsonl), fall back to legacy."""
    runs = _load_runs_from(STATE_RUN_LOG, limit, include_archived)
    if runs:
        return runs
    return _load_runs_from(RUN_LOG, limit, include_archived)


def _shorten_pulse(text: str, limit: int = 96) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return "..." + text[-(limit - 3):]


def _load_log_pulse(limit: int) -> list[tuple[float, str]]:
    """Fallback activity from dated wiki log entries."""
    if not WIKI_LOG.exists():
        return []

    pattern = re.compile(r"^\s*-\s*(\d{4}-\d{2}-\d{2})(?:\s+(\d{2}:\d{2}))?\s+[—-]\s+(.*)$")
    entries: list[tuple[float, str]] = []
    for line in WIKI_LOG.read_text(encoding="utf-8").splitlines():
        match = pattern.match(line.strip())
        if not match:
            continue
        day, hhmm, body = match.groups()
        stamp = f"{day} {hhmm or '00:00'}"
        try:
            ts = datetime.strptime(stamp, "%Y-%m-%d %H:%M").timestamp()
        except ValueError:
            continue
        entries.append((ts, f"{stamp} - { _shorten_pulse(body) }"))

    return sorted(entries, reverse=True)[:limit]


def load_vault_pulse(limit: int = 8) -> list[str]:
    records: list[tuple[float, str]] = []
    for root_name in VAULT_PULSE_ROOTS:
        base = ROOT / root_name
        if not base.exists():
            continue
        for path in base.rglob("*.md"):
            if path == WIKI_LOG:
                continue
            if any(part.startswith(".") for part in path.relative_to(ROOT).parts):
                continue
            try:
                ts = path.stat().st_mtime
            except OSError:
                continue
            stamp = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
            rel = path.relative_to(ROOT).as_posix()
            records.append((ts, f"{stamp} - {_shorten_pulse(rel)}"))

    if records:
        return [item for _, item in sorted(records, reverse=True)[:limit]]
    return [item for _, item in _load_log_pulse(limit)]


def build_chart_data(runs: list[dict]) -> dict:
    now = datetime.now(timezone.utc).date()
    counts: dict = defaultdict(int)
    for run in runs:
        try:
            ts = run.get("started_at") or run.get("created_at") or ""
            day = datetime.fromisoformat(ts).date()
            counts[day] += 1
        except Exception:
            continue

    labels = []
    values = []
    for i in range(29, -1, -1):
        day = now - timedelta(days=i)
        labels.append(day.strftime("%b %d") if i % 5 == 0 else "")
        values.append(counts.get(day, 0))

    return {"labels": labels, "values": values}


def _fmt_dt(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso)
        diff = datetime.now(timezone.utc) - dt
        secs = int(diff.total_seconds())
        if secs < 60:
            return f"{secs}s ago"
        if secs < 3600:
            return f"{secs // 60}m ago"
        if secs < 86400:
            return f"{secs // 3600}h ago"
        return f"{secs // 86400}d ago"
    except Exception:
        return iso[:16]


def _fmt_dur(dur: float | None) -> str:
    if dur is None:
        return ""
    if dur < 1:
        return f"{int(dur * 1000)}ms"
    return f"{dur:.1f}s"


def _fmt_tok(n: int) -> str:
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)


def load_windows(agent: str = "claude") -> dict:
    try:
        w = _compute_windows(agent, RUN_LOG)
        # Format token counts for template
        def _fmt_win(d: dict) -> dict:
            tokens_fmt = _fmt_tok(d["tokens"])
            limit_fmt = _fmt_tok(d["limit"])
            display_line = d.get("display_line") or (
                f"{tokens_fmt} / {limit_fmt} · {d['sessions']} sessions"
            )
            return {
                **d,
                "tokens_fmt": tokens_fmt,
                "limit_fmt": limit_fmt,
                "remaining_pct": d.get("remaining_pct", 0),
                "display_line": display_line,
            }
        return {
            "agent":      w["agent"],
            "window_5h":  _fmt_win(w["window_5h"]),
            "window_7d":  _fmt_win(w["window_7d"]),
            "aux":        w["aux"],
            "quota_source": w.get("quota_source"),
            "plan_type": w.get("plan_type"),
            "limits_estimated": w.get("limits_estimated", True),
        }
    except Exception:
        return {}


def load_codex() -> dict:
    try:
        c = _load_codex_usage()
        if not c:
            return {}
        return {
            "tok_5h":   _fmt_tok(c["window_5h"]["tokens"]),
            "ses_5h":   c["window_5h"]["sessions"],
            "tok_7d":   _fmt_tok(c["window_7d"]["tokens"]),
            "ses_7d":   c["window_7d"]["sessions"],
            "tok_today": _fmt_tok(c["today"]["tokens"]),
            "ses_today": c["today"]["sessions"],
            "by_model": {m: _fmt_tok(t) for m, t in c["by_model"].items()},
        }
    except Exception:
        return {}


def load_cross_check() -> dict:
    try:
        data = _collect_jsonl_usage("2000-01-01")
        cc = _cross_check(data["total_messages"])
        if not cc:
            return {}
        last = cc["last_computed"]
        # Days since last stats-cache compute
        try:
            stale_days = (datetime.now(timezone.utc).date()
                          - datetime.fromisoformat(last).date()).days
        except Exception:
            stale_days = None
        return {
            "last_computed": last,
            "stale_days": stale_days,
            "cache_messages": cc["cache_messages"],
            "jsonl_messages": cc["jsonl_messages"],
        }
    except Exception:
        return {}


def load_usage() -> dict:
    try:
        s = _compute_usage(days=30)
        today = s["today"]
        total_in = today["input"] + today["cache_read"] + today["cache_creation"]
        cache_eff = round(today["cache_read"] / total_in * 100) if total_in > 0 else 0
        by_model = {
            m: _fmt_tok(v["input_tokens"] + v["output_tokens"] + v["cache_read"] + v["cache_creation"])
            for m, v in s["by_model"].items()
        }
        return {
            "today_tokens": _fmt_tok(today["tokens"]),
            "today_messages": today["messages"],
            "today_sessions": today["sessions"],
            "week_tokens": _fmt_tok(s["week"]["tokens"]),
            "week_messages": s["week"]["messages"],
            "cache_efficiency": cache_eff,
            "primary_model": s["primary_model"],
            "by_model": by_model,
        }
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------

def _write_run_log(skill: str, status: str, started_at: str, duration_s: float,
                   prompt: str = "", output: str = "", error: str = "",
                   run_id: str | None = None, output_path: str = "",
                   attempt: int = 0, parent_run_id: str | None = None,
                   linear_issue_id: str | None = None,
                   selected_skill: str | None = None,
                   input_tokens: int | None = None,
                   output_tokens: int | None = None,
                   agent: str | None = None,
                   model: str | None = None,
                   task_id: str | None = None) -> str:
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if run_id is None:
        run_id = str(uuid.uuid4())
    record: dict = {
        "run_id": run_id,
        "skill": skill,
        "status": status,
        "started_at": started_at,
        "duration_s": round(duration_s, 2),
        "prompt": prompt,
        "output": output,
        "error": error,
        "output_path": output_path,
        "attempt": attempt,
        "task_id": task_id or run_id,  # root task id; retry inherits from ancestor
    }
    if parent_run_id:
        record["parent_run_id"] = parent_run_id
    if linear_issue_id:
        record["linear_issue_id"] = linear_issue_id
    if selected_skill:
        record["selected_skill"] = selected_skill
    if input_tokens is not None:
        record["input_tokens"] = input_tokens
    if output_tokens is not None:
        record["output_tokens"] = output_tokens
    if agent:
        record["agent"] = agent
    if model:
        record["model"] = model

    # Write to both locations: state/ (operational truth) and outputs/ (backward compat)
    with STATE_RUN_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    with RUN_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")

    # Update task state in state/task_state.json (operational truth)
    state = _load_task_state()
    if skill not in state:
        state[skill] = {"runs": [], "status": "", "last_run": "", "duration_s": 0.0}
    # Append the new run record
    run_record = {
        "run_id": run_id,
        "skill": skill,
        "status": status,
        "started_at": started_at,
        "duration_s": record["duration_s"],
        "agent": agent,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "selected_skill": selected_skill or skill,
        "attempt": attempt,
        "parent_run_id": parent_run_id,
        "linear_issue_id": linear_issue_id,
        "error": error,
        "output": output,
        "prompt": prompt,
    }
    state[skill]["runs"].append(run_record)
    state[skill]["status"] = status
    state[skill]["last_run"] = started_at
    state[skill]["duration_s"] = record["duration_s"]
    STATE_TASK_STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")

    # Also update legacy job_state.json for backward compat
    legacy_state = _load_legacy_job_state()
    legacy_state[skill] = {"status": status, "last_run": started_at, "duration_s": record["duration_s"]}
    JOB_STATE.write_text(json.dumps(legacy_state, indent=2), encoding="utf-8")
    return run_id


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    cfg = _load_workflow_config()
    active_agent = cfg.get("agent", {}).get("backend", "claude")
    registry = load_registry(active_agent)
    state = load_state()
    all_runs = load_runs(100)

    # Linear issues are source of truth for stats — deduplicate by id, include dismissed
    seen_linear: dict[str, dict] = {}
    for issue in _linear_issues_cache.values():
        seen_linear[issue["id"]] = issue
    linear_for_stats = [
        {"started_at": i.get("created_at", ""), "skill": i.get("identifier", ""), "status": "success"}
        for i in seen_linear.values() if i.get("created_at")
    ]
    all_runs_with_linear = all_runs + linear_for_stats

    # Group skills by stack
    stacks: dict[str, list] = defaultdict(list)
    for name, entry in sorted(registry.items()):
        stacks[entry.get("stack", "other")].append(entry)

    # Stats
    error_runs = [
        r for r in all_runs
        if r.get("status") in ("failed", "error", "timeout", "stalled")
    ]
    stats = {
        "total": len(registry),
        "schedulable": sum(1 for e in registry.values() if e.get("schedule_eligible")),
        "ever_run": len(state),
        "errors": len(error_runs),
        "error_runs": [
            {
                "run_id": r.get("run_id"),
                "skill": r.get("skill", "unknown"),
                "status": r.get("status", "error"),
                "when": _fmt_dt(r.get("started_at")),
                "error": (r.get("error") or "")[:160],
            }
            for r in error_runs[:10]
        ],
        "total_runs": len(all_runs_with_linear),
    }

    # Recent runs for sidebar
    recent_runs = [
        {
            "skill": r["skill"],
            "status": r.get("status", "?"),
            "when": _fmt_dt(r.get("started_at")),
            "duration": _fmt_dur(r.get("duration_s")),
        }
        for r in all_runs[:15]
    ]

    chart_data = build_chart_data(all_runs_with_linear)
    vault_pulse = load_vault_pulse()
    usage = load_usage()
    codex = load_codex()
    cross_check = load_cross_check()
    windows_claude = load_windows("claude")
    windows_codex  = load_windows("codex")
    windows_deepseek = load_windows("deepseek")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Stack order
    stack_order = ["knowledge", "research", "admin", "trading", "publishing", "automation"]
    ordered_stacks = {k: stacks[k] for k in stack_order if k in stacks}
    for k in stacks:
        if k not in ordered_stacks:
            ordered_stacks[k] = stacks[k]

    return render_template(
        "index.html",
        stacks=ordered_stacks,
        stats=stats,
        recent_runs=recent_runs,
        chart_data=chart_data,
        vault_pulse=vault_pulse,
        usage=usage,
        codex=codex,
        cross_check=cross_check,
        windows_claude=windows_claude,
        windows_codex=windows_codex,
        windows_deepseek=windows_deepseek,
        registry=registry,
        now=now,
    )


BOARD_UPLOADS_DIR = _PROTO / "outputs" / "board_uploads"


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


UPLOADS_DIR = _PROTO / "outputs" / "uploads"


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
    return jsonify({"path": str(dest)})


def _ai_cli(agent: str) -> list[str]:
    """Return the CLI command prefix for the selected agent."""
    if agent == "codex":
        return ["codex", "exec", "--dangerously-bypass-approvals-and-sandbox"]
    if agent == "deepseek":
        return ["deepseek", "--model", "deepseek-v4-flash", "--yolo"]
    # default: claude
    claude_bin = _PROTO / ".venv" / "bin" / "claude"
    bin_str = str(claude_bin) if claude_bin.exists() else "claude"
    return [bin_str, "-p", "--permission-mode", "bypassPermissions"]


def _ai_command(agent: str, prompt: str, output_format: str = "json") -> list[str]:
    """Build a non-interactive agent command with agent-specific flags."""
    cli = _ai_cli(agent)
    if agent == "claude":
        return cli + [prompt, "--output-format", output_format]
    if agent == "deepseek":
        # Instruct DeepSeek to output shell commands in ```bash blocks
        # so the dashboard can post-process and execute them for real.
        _ds_suffix = (
            "\n\n"
            "Important: For each shell command you intend to run, "
            "wrap it in a ```bash code block (e.g. ```bash\ncommand\n```). "
            "Do NOT simulate execution output — just output the command blocks."
            " The dashboard will execute them and append real results."
        )
        return cli + ["--prompt", prompt + _ds_suffix]
    return cli + [prompt]


def _agent_model(agent: str, cfg: dict | None = None) -> str:
    """Return the model name for the given agent from config."""
    if cfg is None:
        cfg = _load_workflow_config()
    agent_cfg = cfg.get("agent", {})
    if agent == "claude":
        return agent_cfg.get("claude_model", "claude-sonnet-4-6")
    if agent == "codex":
        model = agent_cfg.get("codex_model")
        if model:
            return model
        try:
            if CODEX_CONFIG.exists():
                codex_cfg = tomllib.loads(CODEX_CONFIG.read_text(encoding="utf-8"))
                if isinstance(codex_cfg, dict):
                    configured = codex_cfg.get("model")
                    if isinstance(configured, str) and configured.strip():
                        return configured.strip()
        except Exception:
            pass
        return "gpt-5.4-mini"
    if agent == "deepseek":
        return agent_cfg.get("deepseek_model", "deepseek-v4-flash")
    return agent


def _parse_agent_output(agent: str, stdout_s: str) -> tuple[str, int | None, int | None, str | None]:
    if agent != "claude" or not stdout_s:
        return stdout_s, None, None, None
    try:
        parsed = json.loads(stdout_s)
        output = parsed.get("result") or parsed.get("content") or stdout_s
        usage = parsed.get("usage") or {}
        model = parsed.get("model")  # present in some Claude CLI versions
        return output, usage.get("input_tokens"), usage.get("output_tokens"), model
    except (json.JSONDecodeError, AttributeError):
        return stdout_s, None, None, None


def _execute_deepseek_commands(output: str, cwd: str | Path | None = None) -> str:
    if not output:
        return output
    PATTERN = re.compile(r"```(?:bash|shell)\n(.*?)```", re.DOTALL)
    cwd = cwd or ROOT
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


def _extract_skill_name(raw: str, registry: dict) -> str:
    normalized = (raw or "").strip().lower().replace(" ", "-")
    if normalized in registry:
        return normalized
    for line in (raw or "").splitlines():
        candidate = line.strip().lower().replace(" ", "-")
        if candidate in registry:
            return candidate
    for name in registry:
        if name in normalized:
            return name
    return list(registry.keys())[0] if registry else "_prompt"


@app.route("/run", methods=["POST"])
def run():
    data = request.get_json(silent=True) or {}
    skill  = data.get("skill")
    prompt = data.get("prompt", "").strip()
    agent  = data.get("agent", "claude")   # "claude" | "codex"

    if not prompt:
        return jsonify({"ok": False, "error": "No prompt provided."})

    # Guard: reject if skill doesn't support selected agent
    if skill:
        registry = load_registry(agent)
        entry = registry.get(skill, {})
        allowed_agents = entry.get("agents", ["claude"])
        if agent not in allowed_agents:
            return jsonify({"ok": False, "error": f"Skill '{skill}' does not support agent '{agent}'."})

        # If skill has an executable entrypoint, run via run_skill.py (agent-agnostic)
        if entry.get("schedule_eligible") and entry.get("entrypoint"):
            run_id = str(uuid.uuid4())
            started_at = datetime.now(timezone.utc).isoformat()
            t0 = time.monotonic()
            _running_jobs[run_id] = {"run_id": run_id, "skill": skill, "started_at": started_at, "prompt": prompt, "state": "running", "last_progress_at": time.monotonic()}
            socketio.emit("run_state_change", {"run_id": run_id, "state": "running", "skill": skill})
            try:
                proc = subprocess.Popen(
                    [_python(), str(RUNNER), skill],
                    cwd=str(ROOT),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                _running_procs[run_id] = proc
                stdout_b, stderr_b = proc.communicate(timeout=300)
                dur = time.monotonic() - t0
                ok = proc.returncode == 0
                output = stdout_b.decode("utf-8", errors="replace").strip()
                stderr_s = stderr_b.decode("utf-8", errors="replace").strip()
                _running_jobs.pop(run_id, None)
                _running_procs.pop(run_id, None)
                final_state = "success" if ok else "failed"
                _write_run_log(skill, final_state, started_at, dur,
                               prompt=prompt, output=output, error=stderr_s, run_id=run_id)
                socketio.emit("run_state_change", {"run_id": run_id, "state": final_state, "skill": skill})
                socketio.emit("run_logged", {"skill": skill, "run_id": run_id})
                return jsonify({
                    "ok": ok,
                    "run_id": run_id,
                    "output": output if ok else stderr_s,
                    "duration_s": round(dur, 2),
                    "skill": skill,
                    "message": f"{skill} completed" if ok else None,
                    "error": stderr_s[:200] if not ok else None,
                })
            except subprocess.TimeoutExpired:
                dur = time.monotonic() - t0
                _running_procs.get(run_id) and _running_procs[run_id].kill()
                _running_jobs.pop(run_id, None)
                _running_procs.pop(run_id, None)
                _write_run_log(skill, "timeout", started_at, dur, prompt=prompt, error="Timed out after 300s", run_id=run_id)
                socketio.emit("run_state_change", {"run_id": run_id, "state": "timeout", "skill": skill})
                return jsonify({"ok": False, "error": "Timed out after 300s."})
            except Exception as e:
                dur = time.monotonic() - t0
                _running_procs.pop(run_id, None)
                _running_jobs.pop(run_id, None)
                _write_run_log(skill, "error", started_at, dur, prompt=prompt, error=str(e), run_id=run_id)
                socketio.emit("run_state_change", {"run_id": run_id, "state": "error", "skill": skill})
                return jsonify({"ok": False, "error": str(e)})

    # AI-only skill or free prompt — dispatch to selected agent CLI
    skill_name = skill or "_prompt"
    run_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc).isoformat()
    t0 = time.monotonic()
    _running_jobs[run_id] = {"run_id": run_id, "skill": skill_name, "started_at": started_at, "prompt": prompt, "state": "running", "last_progress_at": time.monotonic()}
    socketio.emit("run_state_change", {"run_id": run_id, "state": "running", "skill": skill_name})
    try:
        proc = subprocess.Popen(
            _ai_command(agent, prompt, output_format="json"),
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        _running_procs[run_id] = proc
        stdout_b, stderr_b = proc.communicate(timeout=120)
        dur = time.monotonic() - t0
        ok = proc.returncode == 0
        stdout_s = stdout_b.decode("utf-8", errors="replace").strip()
        stderr_s = stderr_b.decode("utf-8", errors="replace").strip()

        output, input_tokens, output_tokens, parsed_model = _parse_agent_output(agent, stdout_s)
        if not output:
            output = stderr_s
        if agent == "deepseek":
            output = _execute_deepseek_commands(output)

        _running_jobs.pop(run_id, None)
        _running_procs.pop(run_id, None)
        final_state = "success" if ok else "failed"
        _write_run_log(skill_name, final_state, started_at, dur,
                       prompt=prompt, output=output, error="" if ok else stderr_s, run_id=run_id,
                       input_tokens=input_tokens, output_tokens=output_tokens, agent=agent,
                       model=parsed_model or _agent_model(agent),
                       task_id=run_id)
        socketio.emit("run_state_change", {"run_id": run_id, "state": final_state, "skill": skill_name})
        socketio.emit("run_logged", {"skill": skill_name, "run_id": run_id})
        return jsonify({
            "ok": ok,
            "run_id": run_id,
            "output": output,
            "duration_s": round(dur, 2),
            "skill": skill_name,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        })
    except FileNotFoundError:
        dur = time.monotonic() - t0
        _running_procs.pop(run_id, None)
        _running_jobs.pop(run_id, None)
        _write_run_log(skill_name, "error", started_at, dur, prompt=prompt, error=f"{agent} CLI not found", run_id=run_id)
        socketio.emit("run_state_change", {"run_id": run_id, "state": "error", "skill": skill_name})
        return jsonify({"ok": False, "error": f"{agent} CLI not found."})
    except subprocess.TimeoutExpired:
        dur = time.monotonic() - t0
        _running_procs.get(run_id) and _running_procs[run_id].kill()
        _running_procs.pop(run_id, None)
        _running_jobs.pop(run_id, None)
        _write_run_log(skill_name, "timeout", started_at, dur, prompt=prompt, error="Timed out after 120s", run_id=run_id)
        socketio.emit("run_state_change", {"run_id": run_id, "state": "timeout", "skill": skill_name})
        return jsonify({"ok": False, "error": "Timed out after 120s."})
    except Exception as e:
        dur = time.monotonic() - t0
        _running_procs.pop(run_id, None)
        _running_jobs.pop(run_id, None)
        _write_run_log(skill_name, "error", started_at, dur, prompt=prompt, error=str(e), run_id=run_id)
        socketio.emit("run_state_change", {"run_id": run_id, "state": "error", "skill": skill_name})
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/state")
def api_state():
    return jsonify({
        "state": load_state(),
        "recent_runs": load_runs(10),
    })


@app.route("/api/registry")
def api_registry():
    agent = (request.args.get("agent") or _load_workflow_config().get("agent", {}).get("backend", "claude")).strip().lower()
    return jsonify(load_registry(agent))


@app.route("/stream")
def stream():
    prompt  = request.args.get("prompt", "").strip()
    skill   = request.args.get("skill", "_prompt") or "_prompt"
    agent   = request.args.get("agent", "claude")

    def _sse(obj: dict) -> str:
        return f"data: {json.dumps(obj)}\n\n"

    def generate():
        if not prompt:
            yield _sse({"type": "error", "text": "No prompt."})
            return

        run_id = str(uuid.uuid4())
        started_at = datetime.now(timezone.utc).isoformat()
        t0 = time.monotonic()
        output_buf: list[str] = []

        _running_jobs[run_id] = {"run_id": run_id, "skill": skill, "started_at": started_at, "prompt": prompt, "state": "running", "last_progress_at": time.monotonic()}
        socketio.emit("run_state_change", {"run_id": run_id, "state": "running", "skill": skill})
        yield _sse({"type": "start", "run_id": run_id})

        # Schedule-eligible entrypoint path
        registry = load_registry(agent)
        entry = registry.get(skill, {})
        if entry.get("schedule_eligible") and entry.get("entrypoint"):
            cmd = [str(_python()), str(RUNNER), skill]
        else:
            cmd = _ai_command(agent, prompt, output_format="text")

        chunk_count = 0
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=0,
            )
            _running_procs[run_id] = proc
            while True:
                chunk = proc.stdout.read(64)
                if not chunk:
                    break
                text = chunk.decode("utf-8", errors="replace")
                output_buf.append(text)
                chunk_count += 1
                snippet = text.replace("\n", " ").strip()[-80:]
                if _running_jobs.get(run_id):
                    _running_jobs[run_id]["last_progress_at"] = time.monotonic()
                socketio.emit("run_progress", {"run_id": run_id, "snippet": snippet, "turn": chunk_count})
                yield _sse({"type": "output", "text": text})
            proc.wait()
            dur = time.monotonic() - t0
            ok = proc.returncode == 0
            _running_jobs.pop(run_id, None)
            _running_procs.pop(run_id, None)
            final_state = "success" if ok else "failed"
            _write_run_log(skill, final_state, started_at, dur,
                           prompt=prompt, output="".join(output_buf), run_id=run_id)
            socketio.emit("run_state_change", {"run_id": run_id, "state": final_state, "skill": skill})
            socketio.emit("run_logged", {"skill": skill, "run_id": run_id})
            yield _sse({"type": "done", "ok": ok, "run_id": run_id, "duration_s": round(dur, 2)})
        except Exception as e:
            dur = time.monotonic() - t0
            _running_procs.pop(run_id, None)
            _running_jobs.pop(run_id, None)
            _write_run_log(skill, "error", started_at, dur, prompt=prompt, error=str(e), run_id=run_id)
            socketio.emit("run_state_change", {"run_id": run_id, "state": "error", "skill": skill})
            yield _sse({"type": "error", "text": str(e)})

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/runs")
def api_runs():
    limit = int(request.args.get("limit", 30))
    state_filter = request.args.get("state", "")
    if state_filter == "running":
        return jsonify(list(_running_jobs.values()))
    if state_filter == "archived":
        runs = load_runs(200, include_archived=True)
        archived = [r for r in runs if r.get("status") == "archived"]
        # Add dismissed Linear virtual cards to trash
        for issue_id in list(_linear_dismissed):
            issue = _linear_issues_cache.get(issue_id)
            if issue:
                archived.append({
                    "run_id": f"linear-{issue_id}",
                    "skill": issue.get("identifier", ""),
                    "prompt": issue.get("title", ""),
                    "status": "archived",
                    "linear_issue_id": issue_id,
                    "_is_linear_issue": True,
                    "when": _fmt_dt(issue.get("created_at")),
                    "duration": "—",
                })
        return jsonify([{**r, "when": _fmt_dt(r.get("started_at")), "duration": _fmt_dur(r.get("duration_s"))} if not r.get("_is_linear_issue") else r for r in archived])
    runs = load_runs(limit)
    return jsonify([{
        **r,
        "when": _fmt_dt(r.get("started_at")),
        "duration": _fmt_dur(r.get("duration_s")),
    } for r in runs])


@app.route("/api/runs/<run_id>")
def api_run_detail(run_id: str):
    if not RUN_LOG.exists():
        return jsonify({"error": "not found"}), 404
    for line in reversed(RUN_LOG.read_text(encoding="utf-8").strip().splitlines()):
        try:
            r = json.loads(line)
            rid = r.get("run_id")
            if not rid:
                h = hashlib.md5(f"{r.get('started_at','')}{r.get('skill','')}".encode()).hexdigest()[:8]
                rid = f"legacy-{h}"
            if rid == run_id:
                r["run_id"] = rid
                r.setdefault("output_path", "")
                return jsonify(r)
        except Exception:
            continue
    return jsonify({"error": "not found"}), 404


@app.route("/api/runs/<run_id>/status", methods=["PATCH"])
def api_run_set_status(run_id: str):
    data = request.get_json(silent=True) or {}
    new_status = data.get("status", "").strip()
    allowed = {"success", "failed", "archived", "todo", "rework", "merging", "cancelled", "duplicate", "stalled", "queued", "review"}
    if new_status not in allowed:
        return jsonify({"error": f"status must be one of {allowed}"}), 400

    # Virtual Linear card — no run record; dismiss by tracking issue_id locally
    if run_id.startswith("linear-"):
        issue_id = run_id[7:]
        if new_status == "archived":
            _linear_dismissed.add(issue_id)
            _save_dismissed()
            socketio.emit("run_state_change", {"run_id": run_id, "state": "archived"})
        return jsonify({"ok": True, "run_id": run_id, "status": new_status})

    if not RUN_LOG.exists():
        return jsonify({"error": "not found"}), 404
    original = None
    for line in reversed(RUN_LOG.read_text(encoding="utf-8").strip().splitlines()):
        try:
            r = json.loads(line)
            rid = r.get("run_id")
            if not rid:
                h = hashlib.md5(f"{r.get('started_at','')}{r.get('skill','')}".encode()).hexdigest()[:8]
                rid = f"legacy-{h}"
            if rid == run_id:
                r["run_id"] = rid
                original = r
                break
        except Exception:
            continue
    if not original:
        return jsonify({"error": "not found"}), 404
    record = {**original, "status": new_status}
    if new_status == "archived":
        record["prev_status"] = original.get("status", "failed")
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    with RUN_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    socketio.emit("run_state_change", {"run_id": run_id, "state": new_status})

    # Push state to Linear if this run is linked to a Linear issue
    linear_issue_id = original.get("linear_issue_id")
    if linear_issue_id and new_status not in ("archived",):
        _push_linear_state_async(linear_issue_id, new_status)

    return jsonify({"ok": True, "run_id": run_id, "status": new_status})


@app.route("/api/runs/<run_id>/restore", methods=["POST"])
def api_run_restore(run_id: str):
    if run_id.startswith("linear-"):
        issue_id = run_id[7:]
        _linear_dismissed.discard(issue_id)
        _save_dismissed()
        socketio.emit("run_state_change", {"run_id": run_id, "state": "restored"})
        return jsonify({"ok": True, "run_id": run_id})
    if not RUN_LOG.exists():
        return jsonify({"error": "not found"}), 404
    for line in reversed(RUN_LOG.read_text(encoding="utf-8").strip().splitlines()):
        try:
            r = json.loads(line)
            rid = r.get("run_id")
            if not rid:
                h = hashlib.md5(f"{r.get('started_at','')}{r.get('skill','')}".encode()).hexdigest()[:8]
                rid = f"legacy-{h}"
            if rid == run_id and r.get("status") == "archived":
                prev_status = r.get("prev_status", "failed")
                record = {k: v for k, v in r.items() if k not in ("prev_status",)}
                record["status"] = prev_status
                OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
                with RUN_LOG.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(record) + "\n")
                socketio.emit("run_state_change", {"run_id": run_id, "state": prev_status})
                return jsonify({"ok": True, "run_id": run_id, "status": prev_status})
        except Exception:
            continue
    return jsonify({"error": "not found or not archived"}), 404


@app.route("/api/runs/<run_id>", methods=["DELETE"])
def api_run_cancel(run_id: str):
    proc = _running_procs.get(run_id)
    if proc is None:
        return jsonify({"error": "not running"}), 404
    try:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    except Exception:
        pass
    job = _running_jobs.pop(run_id, {})
    _running_procs.pop(run_id, None)
    started_at = job.get("started_at", datetime.now(timezone.utc).isoformat())
    skill = job.get("skill", "unknown")
    dur = time.monotonic() - (time.monotonic() - 0)  # best effort
    _write_run_log(skill, "cancelled", started_at, 0.0,
                   prompt=job.get("prompt", ""), error="Cancelled by user", run_id=run_id,
                   linear_issue_id=job.get("linear_issue_id"))
    socketio.emit("run_state_change", {"run_id": run_id, "state": "cancelled", "skill": skill})
    return jsonify({"ok": True, "run_id": run_id})


@app.route("/api/runs/<run_id>/retry", methods=["POST"])
def api_run_retry(run_id: str):
    if not RUN_LOG.exists():
        return jsonify({"error": "not found"}), 404
    original = None
    for line in reversed(RUN_LOG.read_text(encoding="utf-8").strip().splitlines()):
        try:
            r = json.loads(line)
            rid = r.get("run_id")
            if not rid:
                h = hashlib.md5(f"{r.get('started_at','')}{r.get('skill','')}".encode()).hexdigest()[:8]
                rid = f"legacy-{h}"
            if rid == run_id:
                original = r
                original["run_id"] = rid
                break
        except Exception:
            continue
    if not original:
        return jsonify({"error": "not found"}), 404

    skill = original.get("skill", "")
    original_prompt = original.get("prompt", "")
    prev_attempt = original.get("attempt", 0)
    linear_issue_id = original.get("linear_issue_id")
    # task_id chains back to root so all attempts share a common ancestry key
    task_id = original.get("task_id") or run_id

    # Build conversation context: include previous output + human feedback
    req_data = request.get_json(silent=True) or {}
    reply = (req_data.get("reply") or "").strip()
    attachments = req_data.get("attachments") or []
    prev_output = (original.get("output") or "").strip()
    attach_note = ""
    if attachments:
        names = ", ".join(a.get("name", a.get("filename", "")) for a in attachments)
        attach_note = f"\n\n[Attachments]: {names}"
    if reply and prev_output:
        prompt = (
            f"Original task:\n{original_prompt}\n\n"
            f"Previous attempt output:\n{prev_output}\n\n"
            f"[Human feedback]: {reply}{attach_note}\n\n"
            f"Please continue or revise based on the feedback above."
        )
    elif reply:
        prompt = f"[Human feedback]: {reply}{attach_note}\n\n{original_prompt}"
    elif attach_note:
        prompt = f"[Human feedback]:{attach_note}\n\n{original_prompt}"
    else:
        prompt = original_prompt

    # Guard: reject if already running
    if run_id in _running_procs or any(j.get("skill") == skill for j in _running_jobs.values()):
        pass  # allow retry of a different run_id even if same skill has another instance

    new_run_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc).isoformat()
    t0 = time.monotonic()

    cfg = _load_workflow_config()
    agent_override = (req_data.get("agent") or "").strip().lower()
    locked_agent, agent_error = _locked_task_agent(original, agent_override)
    if agent_error:
        return jsonify({"ok": False, "error": agent_error, "agent": locked_agent}), 400
    agent = locked_agent or agent_override or original.get("agent") or cfg.get("agent", {}).get("backend", "claude")
    registry = load_registry(agent)
    entry = registry.get(skill, {})

    if linear_issue_id:
        _linear_dispatched[linear_issue_id] = new_run_id
        _push_linear_state_async(linear_issue_id, "running")
        if reply or attachments:
            _post_linear_comment(
                linear_issue_id,
                _linear_comment_body(
                    title="Human Feedback",
                    feedback=reply,
                    attachments=attachments,
                ),
            )
    _running_jobs[new_run_id] = {
        "run_id": new_run_id, "skill": skill, "started_at": started_at,
        "prompt": prompt, "state": "running", "last_progress_at": time.monotonic(),
        "linear_issue_id": linear_issue_id,
        "agent": agent,
    }
    socketio.emit("run_state_change", {"run_id": new_run_id, "state": "running", "skill": skill})

    def _do_retry():
        try:
            if entry.get("schedule_eligible") and entry.get("entrypoint"):
                cmd = [_python(), str(RUNNER), skill]
            else:
                cmd = _ai_command(agent, prompt, output_format="json")
            proc = subprocess.Popen(cmd, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            _running_procs[new_run_id] = proc
            stdout_b, stderr_b = proc.communicate(timeout=AI_RUN_TIMEOUT_S)
            dur = time.monotonic() - t0
            ok = proc.returncode == 0
            stdout_s = stdout_b.decode("utf-8", errors="replace").strip()
            stderr_s = stderr_b.decode("utf-8", errors="replace").strip()
            output, input_tokens, output_tokens, parsed_model = _parse_agent_output(agent, stdout_s)
            error_s = _extract_real_errors(stderr_s)
            if not output:
                output = error_s or stderr_s
            if agent == "deepseek":
                output = _execute_deepseek_commands(output)
            _running_jobs.pop(new_run_id, None)
            _running_procs.pop(new_run_id, None)
            # Linear-linked runs stay on the original issue and write back output as a comment.
            final_state = "review" if linear_issue_id else ("success" if ok else "failed")
            _write_run_log(skill, final_state, started_at, dur,
                           prompt=prompt, output=output, error=error_s,
                           run_id=new_run_id, attempt=prev_attempt + 1, parent_run_id=run_id,
                           linear_issue_id=linear_issue_id,
                           input_tokens=input_tokens, output_tokens=output_tokens,
                           agent=agent, model=parsed_model or _agent_model(agent, cfg),
                           task_id=task_id)
            if linear_issue_id:
                _push_linear_state_async(linear_issue_id, final_state)
                _post_linear_comment(
                    linear_issue_id,
                    _linear_comment_body(
                        title="AgenticOS Retry",
                        prompt=prompt,
                        output=output,
                        error=error_s,
                    ),
                )
            socketio.emit("run_state_change", {"run_id": new_run_id, "state": final_state, "skill": skill})
            socketio.emit("run_logged", {"skill": skill, "run_id": new_run_id})
        except subprocess.TimeoutExpired:
            dur = time.monotonic() - t0
            proc = _running_procs.pop(new_run_id, None)
            if proc:
                proc.kill()
            _running_jobs.pop(new_run_id, None)
            msg = f"Timed out after {AI_RUN_TIMEOUT_S}s"
            _write_run_log(skill, "timeout", started_at, dur, prompt=prompt, error=msg,
                           run_id=new_run_id, attempt=prev_attempt + 1, parent_run_id=run_id,
                           linear_issue_id=linear_issue_id, agent=agent,
                           model=_agent_model(agent, cfg), task_id=task_id)
            if linear_issue_id:
                _post_linear_comment(linear_issue_id, _linear_comment_body(title="AgenticOS Retry Timeout", prompt=prompt, error=msg))
            socketio.emit("run_state_change", {"run_id": new_run_id, "state": "timeout", "skill": skill})
        except Exception as e:
            _running_procs.pop(new_run_id, None)
            _running_jobs.pop(new_run_id, None)
            _write_run_log(skill, "error", started_at, 0.0, prompt=prompt, error=str(e),
                           run_id=new_run_id, attempt=prev_attempt + 1, parent_run_id=run_id,
                           linear_issue_id=linear_issue_id, agent=agent,
                           model=_agent_model(agent, cfg), task_id=task_id)
            if linear_issue_id:
                _post_linear_comment(
                    linear_issue_id,
                    _linear_comment_body(title="AgenticOS Retry Error", prompt=prompt, error=str(e)),
                )
            socketio.emit("run_state_change", {"run_id": new_run_id, "state": "error", "skill": skill})

    threading.Thread(target=_do_retry, daemon=True).start()
    return jsonify({"ok": True, "run_id": new_run_id, "skill": skill, "attempt": prev_attempt + 1, "agent": agent})


@app.route("/api/runs/<run_id>/history")
def api_run_history(run_id: str):
    """Return full local history for a run, oldest→newest."""
    if not RUN_LOG.exists():
        return jsonify([])
    # Build lookup: run_id -> latest record
    lookup: dict[str, dict] = {}
    for line in RUN_LOG.read_text(encoding="utf-8").strip().splitlines():
        try:
            r = json.loads(line)
            rid = r.get("run_id")
            if not rid:
                h = hashlib.md5(f"{r.get('started_at','')}{r.get('skill','')}".encode()).hexdigest()[:8]
                rid = f"legacy-{h}"
            r["run_id"] = rid
            lookup[rid] = r
        except Exception:
            continue

    target = lookup.get(run_id)
    if target and target.get("linear_issue_id"):
        issue_id = target["linear_issue_id"]
        issue_runs = [
            r for r in lookup.values()
            if r.get("linear_issue_id") == issue_id
            and (r.get("status") != "archived" or r.get("run_id") == run_id)
        ]
        issue_runs.sort(key=lambda r: r.get("started_at", ""))
        return jsonify(issue_runs)

    # Walk parent_run_id chain back to root
    chain: list[dict] = []
    current_id: str | None = run_id
    visited: set[str] = set()
    while current_id and current_id not in visited:
        visited.add(current_id)
        r = lookup.get(current_id)
        if not r:
            break
        chain.append(r)
        current_id = r.get("parent_run_id")
    chain.reverse()  # oldest first
    return jsonify(chain)


@app.route("/api/runs/<run_id>/aggregate")
def api_aggregate_runtime(_run_id: str = ""):
    pass  # placeholder


@app.route("/api/config", methods=["GET"])
def api_config_get():
    cfg = _load_workflow_config()
    tracker = cfg.get("tracker", {})
    return jsonify({
        "agent_backend": cfg.get("agent", {}).get("backend", "claude"),
        "board_col_limit": cfg.get("board", {}).get("col_limit", 15),
        "linear_configured": bool(tracker.get("api_key") and tracker.get("project_slug")),
        "tracker_type": _module_registry.get("linear")._capability.get("type", "none") if _module_registry.get("linear") else "none",
        "linear_project_slug": tracker.get("project_slug", ""),
        "linear_team_id": tracker.get("team_id", ""),
    })


@app.route("/api/config", methods=["PATCH"])
def api_config_patch():
    data = request.get_json(silent=True) or {}
    cfg = _load_workflow_config()
    if "agent_backend" in data:
        cfg.setdefault("agent", {})["backend"] = data["agent_backend"]
    if "board_col_limit" in data:
        cfg.setdefault("board", {})["col_limit"] = int(data["board_col_limit"])
    if "linear_project_slug" in data:
        cfg.setdefault("tracker", {})["project_slug"] = data["linear_project_slug"]
        _linear_dispatched.clear()
        _linear_issues_cache.clear()
    if "linear_team_id" in data:
        cfg.setdefault("tracker", {})["team_id"] = data["linear_team_id"]
        _linear_dispatched.clear()
        _linear_issues_cache.clear()
    _save_workflow_config(cfg)
    return jsonify({"ok": True})


@app.route("/api/linear/teams")
def api_linear_teams():
    cfg = _load_workflow_config()
    tracker = cfg.get("tracker", {})
    api_key = tracker.get("api_key", "")
    if api_key.startswith("$"):
        api_key = os.environ.get(api_key[1:], "")
    if not api_key:
        return jsonify([])
    try:
        from linear_client import LinearClient
        client = LinearClient(api_key, tracker.get("project_slug", ""))
        return jsonify(client.fetch_teams())
    except Exception as e:
        logger.error("fetch_teams error: %s", e)
        return jsonify([])


# ── Module capabilities ─────────────────────────────────────────────────


@app.route("/api/capabilities")
def api_capabilities():
    """Return all module capabilities for frontend dynamic rendering."""
    return jsonify(_module_registry.get_capabilities())


# ── Runtime stats ──────────────────────────────────────────────────────────


@app.route("/api/runtime")
def api_runtime():
    total_s = 0.0
    if RUN_LOG.exists():
        for line in RUN_LOG.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
                total_s += r.get("duration_s", 0) or 0
            except Exception:
                pass
    # add elapsed for running jobs
    now = time.monotonic()
    for job in _running_jobs.values():
        try:
            started = datetime.fromisoformat(job["started_at"]).timestamp()
            total_s += time.time() - started
        except Exception:
            pass
    return jsonify({"total_s": round(total_s, 1)})


@app.route("/api/linear/issues")
def api_linear_issues():
    linear_mod = _module_registry.get("linear")
    if linear_mod and linear_mod._capability.get("available"):
        # Use module-level tracker (Linear or LocalTracker)
        cap = linear_mod._capability
        if cap.get("type") == "linear":
            # Linear mode: fetch live + merge cache
            cfg = _load_workflow_config()
            tracker = cfg.get("tracker", {})
            api_key = tracker.get("api_key", "")
            if api_key.startswith("$"):
                api_key = os.environ.get(api_key[1:], "")
            if api_key and tracker.get("kind") == "linear":
                try:
                    from linear_client import LinearClient
                    client = LinearClient(api_key, tracker.get("project_slug", ""))
                    team_id = tracker.get("team_id", "") or None
                    live_issues = client.fetch_issues(_linear_poll_states(tracker), team_id=team_id)
                    _linear_issues_cache.clear()
                    for issue in live_issues:
                        _linear_issues_cache[issue["id"]] = _normalize_linear_issue(issue)
                except Exception as e:
                    logger.warning("linear issues live refresh failed: %s", e)
            return jsonify(list(_linear_issues_cache.values()))
        else:
            # Local tracker mode
            tracker = linear_mod.get_local_tracker()
            cfg = _load_workflow_config()
            tcfg = cfg.get("tracker", {})
            states = _linear_poll_states(tcfg)
            issues = tracker.fetch_issues(states)
            return jsonify(issues)
    return jsonify([])


@app.route("/api/linear/issues", methods=["POST"])
def api_linear_create_issue():
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"error": "title required"}), 400
    description = (data.get("description") or "").strip()
    preferred_agent = (data.get("agent") or "").strip().lower()
    if preferred_agent not in {"claude", "codex", "deepseek"}:
        preferred_agent = None
    attachments = data.get("attachments") or []
    if attachments:
        attach_lines = "\n".join(
            "- [" + a.get("name", a.get("filename", "")) + "](" + a.get("url", "") + ")"
            for a in attachments
        )
        if description:
            description = description + "\n\n**Attachments:**\n" + attach_lines
        else:
            description = "**Attachments:**\n" + attach_lines
    description = _compose_issue_description(description, preferred_agent)
    team_id = (data.get("team_id") or "").strip()

    linear_mod = _module_registry.get("linear")
    cap = linear_mod._capability if linear_mod else {}
    is_local = cap.get("type") == "local" if cap else True

    if is_local:
        # Local tracker mode
        tracker = linear_mod.get_local_tracker()
        issue = tracker.create_issue(title, description, preferred_agent=preferred_agent)
        normalized = dict(issue)
        _linear_issues_cache[issue["id"]] = normalized
        socketio.emit("linear_issues_updated", {"count": len(_linear_issues_cache)})
        return jsonify({"ok": True, "issue": normalized})

    # Linear mode
    cfg = _load_workflow_config()
    tracker_cfg = cfg.get("tracker", {})
    api_key = tracker_cfg.get("api_key", "")
    if api_key.startswith("$"):
        api_key = os.environ.get(api_key[1:], "")
    if not team_id:
        team_id = tracker_cfg.get("team_id", "")

    if not api_key:
        return jsonify({"error": "Linear not configured"}), 503
    if not team_id:
        return jsonify({"error": "team_id required"}), 400

    try:
        from linear_client import LinearClient
        client = LinearClient(api_key, tracker_cfg.get("project_slug", ""))
        issue = client.create_issue(team_id, title, description, state_name="Todo")
        if not issue:
            return jsonify({"error": "Linear create failed"}), 500
        # Inject into cache immediately so board updates before next poll
        normalized = _normalize_linear_issue({
            "id": issue["id"],
            "identifier": issue.get("identifier", ""),
            "title": issue.get("title", ""),
            "description": description,
            "priority": 0,
            "state": (issue.get("state") or {}).get("name", "Todo"),
            "url": issue.get("url", ""),
            "assignee": "",
            "labels": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        _linear_issues_cache[issue["id"]] = normalized
        if normalized.get("preferred_agent"):
            _post_linear_comment(issue["id"], _issue_agent_comment_body(normalized["preferred_agent"]))
        socketio.emit("linear_issues_updated", {"count": len(_linear_issues_cache)})
        return jsonify({"ok": True, "issue": normalized})
    except Exception as e:
        logger.error("create_issue error: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/linear/projects")
def api_linear_projects():
    cfg = _load_workflow_config()
    tracker = cfg.get("tracker", {})
    api_key = tracker.get("api_key", "")
    if api_key.startswith("$"):
        api_key = os.environ.get(api_key[1:], "")
    if not api_key:
        return jsonify([])
    try:
        from linear_client import LinearClient
        client = LinearClient(api_key, tracker.get("project_slug", ""))
        return jsonify(client.fetch_projects())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/linear/issues/<issue_id>")
def api_linear_issue_detail(issue_id: str):
    cfg = _load_workflow_config()
    tracker = cfg.get("tracker", {})
    api_key = tracker.get("api_key", "")
    if api_key.startswith("$"):
        api_key = os.environ.get(api_key[1:], "")
    if not api_key:
        return jsonify({"error": "not configured"}), 400
    try:
        from linear_client import LinearClient
        client = LinearClient(api_key, tracker.get("project_slug", ""))
        issue = client.fetch_issue(issue_id)
        if not issue:
            return jsonify({"error": "not found"}), 404
        return jsonify(_normalize_linear_issue(issue))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/linear/issues/<issue_id>", methods=["PATCH"])
def api_linear_issue_update(issue_id: str):
    data = request.get_json(silent=True) or {}
    cfg = _load_workflow_config()
    tracker = cfg.get("tracker", {})
    api_key = tracker.get("api_key", "")
    if api_key.startswith("$"):
        api_key = os.environ.get(api_key[1:], "")
    if not api_key:
        return jsonify({"error": "not configured"}), 400
    try:
        from linear_client import LinearClient
        client = LinearClient(api_key, tracker.get("project_slug", ""))
        existing = client.fetch_issue(issue_id)
        if not existing:
            return jsonify({"error": "not found"}), 404
        existing_preferred_agent = (
            existing.get("preferred_agent")
            or _extract_issue_agent(existing.get("description", ""))
            or ""
        ).strip().lower()
        preferred_agent = (data.get("preferred_agent") or existing_preferred_agent or "").strip().lower()
        if preferred_agent not in {"claude", "codex", "deepseek"}:
            preferred_agent = None
        state_name = data.get("state_name")
        state_name = (state_name.strip() if isinstance(state_name, str) else state_name)
        description = data.get("description")
        if description is not None:
            description = _compose_issue_description(str(description), preferred_agent)
        elif "preferred_agent" in data:
            description = _compose_issue_description(
                _strip_issue_metadata(existing.get("description", "")),
                preferred_agent,
            )
        updated = client.update_issue(
            issue_id,
            title=data.get("title"),
            description=description,
            state_name=state_name,
        )
        if updated:
            # Refresh cache entry
            issue = client.fetch_issue(issue_id)
            if issue:
                normalized = _normalize_linear_issue(issue)
                _linear_issues_cache[issue_id] = normalized
                if (
                    "preferred_agent" in data
                    and normalized.get("preferred_agent")
                    and normalized.get("preferred_agent") != existing_preferred_agent
                ):
                    _post_linear_comment(
                        issue_id,
                        _issue_agent_comment_body(
                            normalized["preferred_agent"],
                            previous_agent=existing_preferred_agent or None,
                        ),
                    )
                if _is_linear_in_progress(normalized.get("state")) and not _linear_issue_is_running(issue_id):
                    _linear_dispatched.pop(issue_id, None)
                    threading.Thread(
                        target=_linear_dispatch_issue,
                        args=(normalized, cfg),
                        daemon=True,
                    ).start()
                return jsonify({"ok": True, "issue": normalized})
            return jsonify({"ok": True, "issue": updated})
        return jsonify({"ok": False, "error": "update failed"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/linear/issues/<issue_id>/comment", methods=["POST"])
def api_linear_issue_comment(issue_id: str):
    data = request.get_json(silent=True) or {}
    feedback = (data.get("feedback") or "").strip()
    prompt = (data.get("prompt") or "").strip()
    output = (data.get("output") or "").strip()
    error = (data.get("error") or "").strip()
    attachments = data.get("attachments") or []
    title = (data.get("title") or "AgenticOS Comment").strip()
    body = _linear_comment_body(
        title=title,
        feedback=feedback,
        prompt=prompt,
        output=output,
        error=error,
        attachments=attachments,
    )
    if not body:
        return jsonify({"ok": False, "error": "empty comment"}), 400
    if not _post_linear_comment(issue_id, body):
        return jsonify({"ok": False, "error": "comment sync failed"}), 500
    return jsonify({"ok": True})


@app.route("/api/linear/config")
def api_linear_config():
    cfg = _load_workflow_config()
    tracker = cfg.get("tracker", {})
    return jsonify({
        "kind": tracker.get("kind", ""),
        "project_slug": tracker.get("project_slug", ""),
        "active_states": tracker.get("active_states", []),
        "terminal_states": tracker.get("terminal_states", []),
        "configured": bool(tracker.get("api_key") and tracker.get("project_slug")),
    })


@app.route("/api/windows")
def api_windows():
    agent = request.args.get("agent", "claude")
    try:
        return jsonify(_compute_windows(agent, RUN_LOG))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/usage")
def api_usage():
    try:
        result: dict[str, Any] = {
            "claude": _compute_usage(days=30),
            "codex":  _load_codex_usage(),
        }
        if _HAS_DEEPSEEK_MONITOR:
            result["deepseek"] = _load_deepseek_usage_from_monitor()
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/deepseek/usage")
def api_deepseek_usage():
    """Return DeepSeek usage data from cached usage.json."""
    try:
        from usage_reader import load_deepseek_usage as _load_ds
        data = _load_ds()
        if not data:
            return jsonify({"ok": False, "error": "no usage data"}), 404
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/deepseek/refresh", methods=["POST"])
def api_deepseek_refresh():
    """Force refresh DeepSeek usage data (balance + checkpoint scan)."""
    if not _HAS_DEEPSEEK_MONITOR:
        return jsonify({"ok": False, "error": "deepseek_monitor not available"}), 400
    try:
        result = _deepseek_monitor.update_usage()
        return jsonify({"ok": True, "last_updated": result.get("last_updated", "")})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ── Speech-to-Text (OpenAI) ─────────────────────────────────────────────────


@app.route("/api/stt", methods=["POST"])
def api_stt():
    """Transcribe audio via OpenAI Audio API (whisper-1).

    Requires OPENAI_API_KEY in environment (.env or sourced bashrc).
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return jsonify({"error": "OPENAI_API_KEY not set in environment"}), 400

    if "audio" not in request.files:
        return jsonify({"error": "No audio file provided"}), 400

    audio_file = request.files["audio"]

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        transcript = client.audio.transcriptions.create(
            model="whisper-1",
            file=(audio_file.filename or "recording.webm", audio_file.read(), audio_file.content_type or "audio/webm"),
            response_format="text",
        )
        return jsonify({"text": transcript})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _load_deepseek_usage_from_monitor() -> dict[str, Any]:
    """Load DeepSeek usage via monitor's cached file."""
    from usage_reader import load_deepseek_usage as _load_ds
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


# ---------------------------------------------------------------------------

def _migrate_legacy_state() -> None:
    """Copy existing data from outputs/ to state/ on first run."""
    # Migrate run log
    if RUN_LOG.exists() and not STATE_RUN_LOG.exists():
        try:
            data = RUN_LOG.read_text(encoding="utf-8")
            STATE_RUN_LOG.write_text(data, encoding="utf-8")
            print(f"Migrated run log: {RUN_LOG} → {STATE_RUN_LOG}")
        except Exception as e:
            print(f"Warning: run log migration failed: {e}")

    # Migrate job state
    if JOB_STATE.exists() and not STATE_TASK_STATE.exists():
        try:
            data = JOB_STATE.read_text(encoding="utf-8")
            STATE_TASK_STATE.write_text(data, encoding="utf-8")
            print(f"Migrated job state: {JOB_STATE} → {STATE_TASK_STATE}")
        except Exception as e:
            print(f"Warning: job state migration failed: {e}")

    # Ensure task_state.json uses the new structured format
    _load_task_state()


def _deepseek_polling_loop() -> None:
    """Periodically refresh DeepSeek usage data every 120s."""
    import time as _time
    if not _HAS_DEEPSEEK_MONITOR:
        return
    while True:
        try:
            _deepseek_monitor.update_usage()
        except Exception:
            logger.exception("deepseek poll failed")
        _time.sleep(120)


def _init_modules() -> None:
    """Initialize the module registry: discover, check capabilities, register routes."""
    global _AVAILABLE_MODULES
    from runner.core.module_registry import registry as _mod_reg
    from runner.modules import discover_all

    # Discover modules in runner/modules/
    discovered = discover_all()
    if discovered:
        logger.info("Discovered modules: %s", ", ".join(discovered))

    # Check capabilities for all registered modules
    _AVAILABLE_MODULES = _mod_reg.load_all()
    if _AVAILABLE_MODULES:
        logger.info("Available modules: %s", ", ".join(_AVAILABLE_MODULES))

    # Register routes (app is already created at this point)
    _mod_reg.init_routes(app)
    _mod_reg.init_socketio(socketio)


def main() -> None:
    parser = argparse.ArgumentParser(description="AgenticOS web dashboard.")
    parser.add_argument("--port", type=int, default=8510)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    print(f"AgenticOS dashboard → http://{args.host}:{args.port}")
    _migrate_legacy_state()
    _load_dismissed()
    _init_modules()
    threading.Thread(target=_stall_detection_loop, daemon=True).start()
    if _module_registry.is_available("linear"):
        threading.Thread(target=_linear_polling_loop, daemon=True).start()
    if _HAS_DEEPSEEK_MONITOR:
        threading.Thread(target=_deepseek_polling_loop, daemon=True).start()
    socketio.run(app, host=args.host, port=args.port, debug=args.debug, allow_unsafe_werkzeug=True)


if __name__ == "__main__":
    main()
