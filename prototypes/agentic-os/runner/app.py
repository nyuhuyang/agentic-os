#!/usr/bin/env python3
"""AgenticOS web dashboard.

Usage:
    ../.venv/bin/python3 runner/app.py
    ../.venv/bin/python3 runner/app.py --port 8510
    KNOWLEDGE_BASE=/path/to/kb ../.venv/bin/python3 runner/app.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import fcntl
import os
import pty
import select
import struct
import termios
import threading

from flask import Flask, Response, jsonify, render_template, request, stream_with_context
from flask_socketio import SocketIO, emit

_HERE = Path(__file__).resolve().parent              # prototypes/agentic-os/runner/
_PROTO = _HERE.parent                                # prototypes/agentic-os/

# KNOWLEDGE_BASE env var overrides; default resolves relative to this file's location
_DEFAULT_KB = Path(os.environ.get(
    "KNOWLEDGE_BASE",
    str(_PROTO.parent.parent / "obsidian" / "knowledge_base")
)).resolve()

ROOT = _DEFAULT_KB                                   # knowledge_base/
sys.path.insert(0, str(_HERE))
from usage_reader import (
    compute_stats as _compute_usage,
    compute_windows as _compute_windows,
    load_codex_usage as _load_codex_usage,
    cross_check_stats_cache as _cross_check,
    _collect_jsonl_usage,
    _fmt as _fmt_tok_usage,
)
WORKSPACE_ROOT = ROOT.parent.parent                  # AI_Workspace/
REGISTRY_JSON = WORKSPACE_ROOT / ".codex" / "registry.json"
OUTPUTS_DIR = ROOT / "outputs"
RUN_LOG = OUTPUTS_DIR / "run_log.jsonl"
JOB_STATE = OUTPUTS_DIR / "job_state.json"
WIKI_LOG = ROOT / "wiki" / "log.md"
RUNNER = ROOT / ".codex" / "runner" / "run_skill.py"
VAULT_PULSE_ROOTS = ("wiki", "raw", "outputs")

VENV_PYTHON = ROOT / ".venv" / "bin" / "python3"

# In-memory running jobs: run_id -> {run_id, skill, started_at, prompt}
_running_jobs: dict[str, dict] = {}

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


def load_registry() -> dict:
    if not REGISTRY_JSON.exists():
        return {}
    return json.loads(REGISTRY_JSON.read_text(encoding="utf-8")).get("skills", {})


def load_state() -> dict:
    if not JOB_STATE.exists():
        return {}
    try:
        return json.loads(JOB_STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_runs(limit: int = 20) -> list[dict]:
    if not RUN_LOG.exists():
        return []
    lines = RUN_LOG.read_text(encoding="utf-8").strip().splitlines()
    records = []
    for line in reversed(lines):
        try:
            r = json.loads(line)
            if "run_id" not in r:
                h = hashlib.md5(f"{r.get('started_at','')}{r.get('skill','')}".encode()).hexdigest()[:8]
                r["run_id"] = f"legacy-{h}"
            r.setdefault("output_path", "")
            records.append(r)
        except Exception:
            continue
        if len(records) >= limit:
            break
    return records


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
            day = datetime.fromisoformat(run["started_at"]).date()
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
                   run_id: str | None = None, output_path: str = "") -> str:
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    if run_id is None:
        run_id = str(uuid.uuid4())
    record = {
        "run_id": run_id,
        "skill": skill,
        "status": status,
        "started_at": started_at,
        "duration_s": round(duration_s, 2),
        "prompt": prompt,
        "output": output,
        "error": error,
        "output_path": output_path,
    }
    with RUN_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")

    state = load_state()
    state[skill] = {"status": status, "last_run": started_at, "duration_s": record["duration_s"]}
    JOB_STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return run_id


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    registry = load_registry()
    state = load_state()
    all_runs = load_runs(100)

    # Group skills by stack
    stacks: dict[str, list] = defaultdict(list)
    for name, entry in sorted(registry.items()):
        stacks[entry.get("stack", "other")].append(entry)

    # Stats
    errors = sum(1 for s in state.values() if s.get("status") in ("failed", "error"))
    stats = {
        "total": len(registry),
        "schedulable": sum(1 for e in registry.values() if e.get("schedule_eligible")),
        "ever_run": len(state),
        "errors": errors,
        "total_runs": len(all_runs),
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

    chart_data = build_chart_data(all_runs)
    vault_pulse = load_vault_pulse()
    usage = load_usage()
    codex = load_codex()
    cross_check = load_cross_check()
    windows = load_windows("claude")
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
        windows=windows,
        registry=registry,
        now=now,
    )


UPLOADS_DIR = ROOT / "outputs" / "uploads"


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
        return ["codex", "exec"]
    # default: claude
    claude_bin = ROOT / ".venv" / "bin" / "claude"
    bin_str = str(claude_bin) if claude_bin.exists() else "claude"
    return [bin_str, "-p"]


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
        registry = load_registry()
        entry = registry.get(skill, {})
        allowed_agents = entry.get("agents", ["claude"])
        if agent not in allowed_agents:
            return jsonify({"ok": False, "error": f"Skill '{skill}' does not support agent '{agent}'."})

        # If skill has an executable entrypoint, run via run_skill.py (agent-agnostic)
        if entry.get("schedule_eligible") and entry.get("entrypoint"):
            run_id = str(uuid.uuid4())
            started_at = datetime.now(timezone.utc).isoformat()
            t0 = time.monotonic()
            _running_jobs[run_id] = {"run_id": run_id, "skill": skill, "started_at": started_at, "prompt": prompt, "state": "running"}
            socketio.emit("run_state_change", {"run_id": run_id, "state": "running", "skill": skill})
            try:
                result = subprocess.run(
                    [_python(), str(RUNNER), skill],
                    cwd=str(ROOT),
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
                dur = time.monotonic() - t0
                ok = result.returncode == 0
                output = (result.stdout or "").strip()
                _running_jobs.pop(run_id, None)
                final_state = "success" if ok else "failed"
                _write_run_log(skill, final_state, started_at, dur,
                               prompt=prompt, output=output, error=result.stderr, run_id=run_id)
                socketio.emit("run_state_change", {"run_id": run_id, "state": final_state, "skill": skill})
                socketio.emit("run_logged", {"skill": skill, "run_id": run_id})
                return jsonify({
                    "ok": ok,
                    "run_id": run_id,
                    "output": output if ok else result.stderr.strip(),
                    "duration_s": round(dur, 2),
                    "skill": skill,
                    "message": f"{skill} completed" if ok else None,
                    "error": result.stderr[:200] if not ok else None,
                })
            except subprocess.TimeoutExpired:
                dur = time.monotonic() - t0
                _running_jobs.pop(run_id, None)
                _write_run_log(skill, "timeout", started_at, dur, prompt=prompt, error="Timed out after 300s", run_id=run_id)
                socketio.emit("run_state_change", {"run_id": run_id, "state": "failed", "skill": skill})
                return jsonify({"ok": False, "error": "Timed out after 300s."})
            except Exception as e:
                dur = time.monotonic() - t0
                _running_jobs.pop(run_id, None)
                _write_run_log(skill, "error", started_at, dur, prompt=prompt, error=str(e), run_id=run_id)
                socketio.emit("run_state_change", {"run_id": run_id, "state": "failed", "skill": skill})
                return jsonify({"ok": False, "error": str(e)})

    # AI-only skill or free prompt — dispatch to selected agent CLI
    cli = _ai_cli(agent)
    extra = ["--output-format", "text"] if agent == "claude" else []
    skill_name = skill or "_prompt"
    run_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc).isoformat()
    t0 = time.monotonic()
    _running_jobs[run_id] = {"run_id": run_id, "skill": skill_name, "started_at": started_at, "prompt": prompt, "state": "running"}
    socketio.emit("run_state_change", {"run_id": run_id, "state": "running", "skill": skill_name})
    try:
        result = subprocess.run(
            cli + [prompt] + extra,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=120,
        )
        dur = time.monotonic() - t0
        ok = result.returncode == 0
        output = (result.stdout or result.stderr or "").strip()
        _running_jobs.pop(run_id, None)
        final_state = "success" if ok else "failed"
        _write_run_log(skill_name, final_state, started_at, dur,
                       prompt=prompt, output=output, error="" if ok else output, run_id=run_id)
        socketio.emit("run_state_change", {"run_id": run_id, "state": final_state, "skill": skill_name})
        socketio.emit("run_logged", {"skill": skill_name, "run_id": run_id})
        return jsonify({
            "ok": ok,
            "run_id": run_id,
            "output": output,
            "duration_s": round(dur, 2),
            "skill": skill_name,
        })
    except FileNotFoundError:
        dur = time.monotonic() - t0
        _running_jobs.pop(run_id, None)
        _write_run_log(skill_name, "error", started_at, dur, prompt=prompt, error=f"{agent} CLI not found", run_id=run_id)
        socketio.emit("run_state_change", {"run_id": run_id, "state": "failed", "skill": skill_name})
        return jsonify({"ok": False, "error": f"{agent} CLI not found."})
    except subprocess.TimeoutExpired:
        dur = time.monotonic() - t0
        _running_jobs.pop(run_id, None)
        _write_run_log(skill_name, "timeout", started_at, dur, prompt=prompt, error="Timed out after 120s", run_id=run_id)
        socketio.emit("run_state_change", {"run_id": run_id, "state": "failed", "skill": skill_name})
        return jsonify({"ok": False, "error": "Timed out after 120s."})
    except Exception as e:
        dur = time.monotonic() - t0
        _running_jobs.pop(run_id, None)
        _write_run_log(skill_name, "error", started_at, dur, prompt=prompt, error=str(e), run_id=run_id)
        socketio.emit("run_state_change", {"run_id": run_id, "state": "failed", "skill": skill_name})
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/state")
def api_state():
    return jsonify({
        "state": load_state(),
        "recent_runs": load_runs(10),
    })


@app.route("/api/registry")
def api_registry():
    return jsonify(load_registry())


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

        _running_jobs[run_id] = {"run_id": run_id, "skill": skill, "started_at": started_at, "prompt": prompt, "state": "running"}
        socketio.emit("run_state_change", {"run_id": run_id, "state": "running", "skill": skill})
        yield _sse({"type": "start", "run_id": run_id})

        # Schedule-eligible entrypoint path
        registry = load_registry()
        entry = registry.get(skill, {})
        if entry.get("schedule_eligible") and entry.get("entrypoint"):
            cmd = [str(_python()), str(RUNNER), skill]
        else:
            cli = _ai_cli(agent)
            extra = ["--output-format", "text"] if agent == "claude" else []
            cmd = cli + [prompt] + extra

        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=0,
            )
            while True:
                chunk = proc.stdout.read(64)
                if not chunk:
                    break
                text = chunk.decode("utf-8", errors="replace")
                output_buf.append(text)
                yield _sse({"type": "output", "text": text})
            proc.wait()
            dur = time.monotonic() - t0
            ok = proc.returncode == 0
            _running_jobs.pop(run_id, None)
            final_state = "success" if ok else "failed"
            _write_run_log(skill, final_state, started_at, dur,
                           prompt=prompt, output="".join(output_buf), run_id=run_id)
            socketio.emit("run_state_change", {"run_id": run_id, "state": final_state, "skill": skill})
            socketio.emit("run_logged", {"skill": skill, "run_id": run_id})
            yield _sse({"type": "done", "ok": ok, "run_id": run_id, "duration_s": round(dur, 2)})
        except Exception as e:
            dur = time.monotonic() - t0
            _running_jobs.pop(run_id, None)
            _write_run_log(skill, "error", started_at, dur, prompt=prompt, error=str(e), run_id=run_id)
            socketio.emit("run_state_change", {"run_id": run_id, "state": "failed", "skill": skill})
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


@app.route("/api/runs/<run_id>/retry", methods=["POST"])
def api_run_retry(run_id: str):
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
                return jsonify({"ok": True, "skill": r.get("skill", ""), "prompt": r.get("prompt", "")})
        except Exception:
            continue
    return jsonify({"error": "not found"}), 404


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
        return jsonify({
            "claude": _compute_usage(days=30),
            "codex":  _load_codex_usage(),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="AgenticOS web dashboard.")
    parser.add_argument("--port", type=int, default=8510)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    print(f"AgenticOS dashboard → http://{args.host}:{args.port}")
    socketio.run(app, host=args.host, port=args.port, debug=args.debug, allow_unsafe_werkzeug=True)


if __name__ == "__main__":
    main()
