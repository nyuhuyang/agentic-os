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
            time.sleep(30)  # outside the reservation
            last_cleanup = run_pass(_app, socketio, last_cleanup)


def run_pass(_app, socketio, last_cleanup: float) -> float:
    """One stall/cleanup pass. It writes run records, so it is counted and skipped under
    maintenance (BUILD-012). Returns the new last-cleanup time."""
    try:
        with _app._inflight_work():
            check_once(_app, socketio)
            if time.monotonic() - last_cleanup > 3600:
                last_cleanup = time.monotonic()
                _app._archive_stale_sent()
    except _app.MaintenanceRefused:
        pass
    return last_cleanup


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
            try:
                _stall(_app, socketio, run_id, job)
            except Exception:  # one bad run never stops the watchdog (RWS-003)
                logger.exception("stall handling failed for %s", run_id)


def _stall(_app, socketio, run_id: str, job: dict) -> None:
    # Ending the run = taking both entries under the lock; then the stall pass owns its
    # record and tracker push, and the worker touches neither (WS-004/006/007).
    with _app._JOB_LOCK:
        _app._mark_job_closing(run_id)  # before it leaves the live set (R3)
        if _app._running_jobs.pop(run_id, None) is None:
            return  # the worker or a cancel ended it meanwhile
        proc = _app._running_procs.pop(run_id, None)
        _app._RETIRING[run_id] = job  # still counted as activity until it is stopped and recorded (CM-014)
    try:
        if proc:
            _app._kill_group(proc)
        _app._write_owner_record(run_id, job, "stalled", "stalled", proc=proc)
    finally:
        _app._RETIRING.pop(run_id, None)
    socketio.emit("run_state_change", {"run_id": run_id, "state": "stalled", "skill": job.get("skill", "unknown")})
    issue_id = job.get("linear_issue_id")
    linear_mod = _app._module_registry.get("linear")
    if issue_id and "launch_gen" in job and linear_mod:
        # The displaced worker's own guarded completion: a reset since launch or a
        # Done/Canceled issue stays as it is (WS-013).
        linear_mod._mark_issue_review(issue_id, gen=job["launch_gen"])

module = StallDetectionModule()
registry.register(module)
