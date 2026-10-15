"""Stall detection module — monitors and kills stalled runs.

Checks `_running_jobs` every 30 seconds; any job without progress
for > STALL_TIMEOUT_S (300s default) is killed and logged as "stalled".

Also auto-archives stale "sent" records older than 24h.
"""

from __future__ import annotations

import logging
import threading
import time

from runner.core.module_registry import AgenticModule, registry

logger = logging.getLogger(__name__)


def _ensure_imports():
    import app as _app
    return _app


class StallDetectionModule(AgenticModule):
    """Monitors and cleans up stalled runs."""

    name = "stall_detection"
    label = "Stall Detection"
    dependencies: list[str] = []
    required_env: list[str] = []

    def check_capabilities(self) -> dict:
        return {"available": True, "reason": ""}

    def start_background(self, app, socketio) -> list[threading.Thread]:
        return [threading.Thread(target=self._loop, args=(socketio,), daemon=True)]

    def _loop(self, socketio) -> None:
        _app = _ensure_imports()
        last_cleanup = 0.0

        while True:
            time.sleep(30)
            check_once(_app, socketio)

            if time.monotonic() - last_cleanup > 3600:
                last_cleanup = time.monotonic()
                _app._archive_stale_sent()


def check_once(_app, socketio) -> None:
    """Kill every job without progress for longer than STALL_TIMEOUT_S."""
    now = time.monotonic()
    for run_id, job in list(_app._running_jobs.items()):
        last = job.get("last_progress_at", now)
        if job.get("project_key"):
            # Project runs: only a silent agent phase stalls; post-run git/verify have
            # their own timeouts. The launch helper writes the record (I5-01/07).
            if job.get("phase") == "agent" and not job.get("cancelled") and now - last > _app.STALL_TIMEOUT_S:
                _app._signal_project_run(run_id, "stalled")
            continue
        if now - last > _app.STALL_TIMEOUT_S:
            skill = job.get("skill", "unknown")
            started_at = job.get("started_at", "")
            _app._running_jobs.pop(run_id, None)
            proc = _app._running_procs.pop(run_id, None)
            if proc:
                try:
                    proc.kill()
                except Exception:
                    pass
            _app._write_run_log(
                skill, "stalled", started_at, 0.0,
                prompt=job.get("prompt", ""), error="stalled",
                run_id=run_id,
                linear_issue_id=job.get("linear_issue_id"),
            )
            socketio.emit("run_state_change", {
                "run_id": run_id, "state": "stalled", "skill": skill,
            })


module = StallDetectionModule()
registry.register(module)
