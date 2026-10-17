"""Runner write safety (docs/exec-plans/active/2026-10-15-runner-write-safety.md): atomic
registry cache, process-group timeouts, stoppable readers, and one owner per run end."""

import contextlib
import json
import os
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

RUNNER = Path(__file__).resolve().parents[1] / "runner"
sys.path.insert(0, str(RUNNER))
sys.path.insert(0, str(RUNNER.parent))

from test_reset_gen import ISSUE, SID, env, reset_route, write_log  # noqa: E402,F401  (env: fixture)

PIPE = subprocess.PIPE
READERS = ["_stream_text_run", "_stream_claude_run", "_stream_dsh_run"]
REAL_POPEN = subprocess.Popen


def gone(pid: int, within: float = 5.0) -> bool:
    deadline = time.monotonic() + within
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.05)
    return False


def kill_quietly(pid: int) -> None:
    with contextlib.suppress(OSError):
        os.kill(pid, signal.SIGKILL)


def spawn(script: str) -> subprocess.Popen:
    return REAL_POPEN(["/bin/sh", "-c", script], stdout=PIPE, stderr=PIPE, start_new_session=True)


@pytest.fixture
def app_mod(tmp_path, monkeypatch):
    import app
    monkeypatch.setattr(app, "RUN_PROGRESS_DIR", tmp_path)
    monkeypatch.setattr(app, "REGISTRY_CACHE_DIR", tmp_path / "registry-cache")
    return app


# ── BUILD-016: registry cache ────────────────────────────────────────────

def test_registry_cache_republish_keeps_a_held_handle_whole(app_mod):
    reg = {"s": {"agents": ["codex"]}}
    path = Path(app_mod._registry_exec_env("codex", reg)["REGISTRY_JSON"])
    with path.open(encoding="utf-8") as held:
        app_mod._registry_exec_env("codex", reg)  # same agent and skills: same path
        assert os.fstat(held.fileno()).st_ino != path.stat().st_ino  # replaced, never rewritten
        assert json.load(held)["skills"] == reg


# ── BUILD-014: timeouts end the group and the readers ────────────────────

@pytest.mark.parametrize("reader", READERS)
def test_timeout_kills_the_whole_group(app_mod, reader):
    proc = spawn("sleep 60 & echo $!; exec sleep 60")
    rid = f"group-{reader}"
    with pytest.raises(subprocess.TimeoutExpired):
        getattr(app_mod, reader)(proc, rid, timeout=1)
    assert proc.poll() is not None  # leader killed and reaped
    pid = int(app_mod._claude_stream_log_path(rid).read_text().split()[0])
    assert gone(pid), "the background descendant outlived the timeout"


ESCAPE = ("import subprocess, time; p = subprocess.Popen(['sleep', '60'], start_new_session=True); "
          "print(p.pid, flush=True); time.sleep(60)")


@pytest.mark.parametrize("reader", READERS)
def test_escaped_descendant_cannot_pin_the_readers(app_mod, monkeypatch, reader):
    threads = []
    real = app_mod._start_counted
    monkeypatch.setattr(app_mod, "_start_counted", lambda fn, *a, **k: threads.append(real(fn, *a, **k)) or threads[-1])
    before = app_mod._INFLIGHT
    proc = REAL_POPEN([sys.executable, "-c", ESCAPE], stdout=PIPE, stderr=PIPE, start_new_session=True)
    rid = f"escape-{reader}"
    t0 = time.monotonic()
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            getattr(app_mod, reader)(proc, rid, timeout=1)
        assert time.monotonic() - t0 < 10
        assert threads and not any(t.is_alive() for t in threads)
        assert app_mod._INFLIGHT == before  # every reader slot came back
    finally:
        words = app_mod._claude_stream_log_path(rid).read_text().split()
        if words:
            kill_quietly(int(words[0]))  # it escaped the group on purpose


@pytest.mark.parametrize("reader", READERS)
def test_early_stdout_eof_still_times_out(app_mod, reader):
    proc = spawn("exec >/dev/null; sleep 60")
    t0 = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        getattr(app_mod, reader)(proc, f"eof-{reader}", timeout=1)
    assert time.monotonic() - t0 < 10 and proc.poll() is not None  # WS-001


# ── Run lifecycle through the routes (synchronous threads, stub processes) ──

@pytest.fixture
def harness(env, monkeypatch):
    app_mod, mod, client, log, events, tmp = env
    monkeypatch.setattr(app_mod, "_running_jobs", {})
    monkeypatch.setattr(app_mod, "_running_procs", {})
    # Tests here send a cancel/reset request from inside another request; nested test-client
    # requests share flask.g, so the gate releases one slot for two. Real requests never nest:
    # restore the count afterwards so later tests start clean.
    monkeypatch.setattr(app_mod, "_INFLIGHT", app_mod._INFLIGHT)
    return env


def stub_launches(app_mod, monkeypatch, plan):
    """Popen stand-in without a pid; plan[i] shapes launch i: rc, on_launch(proc), on_read(proc)."""
    procs = []

    class Proc:
        def __init__(self, cmd, **kw):
            spec = plan[len(procs)] if len(procs) < len(plan) else {}
            procs.append(self)
            self.args, self.kw, self.killed = cmd, kw, False
            self.returncode = spec.get("rc", 0)
            self.stderr = type("E", (), {"read": lambda s: b""})()
            on_read = spec.get("on_read")

            def out():
                if on_read:
                    on_read(self)
                return
                yield
            self.stdout = out()
            if spec.get("on_launch"):
                spec["on_launch"](self)

        def communicate(self, timeout=None):
            for _ in self.stdout:
                pass
            return b"", b""

        def wait(self, timeout=None): return self.returncode
        def poll(self): return self.returncode
        def kill(self): self.killed = True

    monkeypatch.setattr(app_mod.subprocess, "Popen", Proc)
    return procs


def statuses(log, rid):
    return [r["status"] for r in map(json.loads, log.read_text().splitlines()) if r.get("run_id") == rid]


def latest_job(app_mod):
    return list(app_mod._running_jobs)[-1]


def tracker_state(tmp):
    return json.loads((tmp / "tasks.json").read_text())[ISSUE]["state"]


def canceller(app_mod, client, seen):
    def cancel(_proc):
        seen["rid"] = latest_job(app_mod)
        seen["code"] = client.delete(f"/api/runs/{seen['rid']}").status_code
    return cancel


def test_cancel_before_registration_kills_the_new_process(harness, monkeypatch):
    app_mod, mod, client, log, events, tmp = harness
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review"})
    seen = {}
    procs = stub_launches(app_mod, monkeypatch, [{"on_launch": canceller(app_mod, client, seen)}])
    client.post("/api/runs/a/retry", json={})
    assert seen["code"] == 200 and len(procs) == 1 and procs[0].killed  # WS-004 handshake
    assert statuses(log, seen["rid"])[-1] == "cancelled"
    assert seen["rid"] not in app_mod._running_procs


def test_cancel_before_fallback_registration_kills_the_fallback(harness, monkeypatch):
    app_mod, mod, client, log, events, tmp = harness
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID,
                    "linear_issue_id": None})  # a /run card: its resume keeps the fresh fallback (D3 covers tracker cards)
    seen = {}
    procs = stub_launches(app_mod, monkeypatch, [{"rc": 1}, {"on_launch": canceller(app_mod, client, seen)}])
    client.post("/api/runs/a/retry", json={})
    assert len(procs) == 2 and procs[1].killed and seen["code"] == 200
    assert statuses(log, seen["rid"])[-1] == "cancelled"


def test_cancelled_resumed_retry_starts_no_fallback(harness, monkeypatch):
    app_mod, mod, client, log, events, tmp = harness
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID})
    seen = {}
    procs = stub_launches(app_mod, monkeypatch, [{"rc": 1, "on_read": canceller(app_mod, client, seen)}])
    client.post("/api/runs/a/retry", json={})
    assert len(procs) == 1 and procs[0].killed  # the failed resume did not fall back (WS-004)
    assert statuses(log, seen["rid"])[-1] == "cancelled"


def test_cancelled_run_appends_nothing_after_cancelled(harness, monkeypatch):
    app_mod, mod, client, log, events, tmp = harness
    seen = {}
    stub_launches(app_mod, monkeypatch, [{"on_read": canceller(app_mod, client, seen)}])
    r = client.post("/run", json={"prompt": "hi", "agent": "claude"})
    assert r.get_json()["error"] == "cancelled"
    assert statuses(log, seen["rid"])[-1] == "cancelled"


def test_cancel_after_the_worker_ended_the_run_is_refused(harness, monkeypatch):
    app_mod, mod, client, log, events, tmp = harness
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review"})
    stub_launches(app_mod, monkeypatch, [{}])
    real, seen = app_mod._write_run_log, {}

    def write(skill, status, *a, **k):
        if status == "review" and "code" not in seen:  # after _end_job, before the record (WS-006)
            seen["code"] = client.delete(f"/api/runs/{k['run_id']}").status_code
            seen["rid"] = k["run_id"]
        return real(skill, status, *a, **k)
    monkeypatch.setattr(app_mod, "_write_run_log", write)
    client.post("/api/runs/a/retry", json={})
    assert seen["code"] == 404
    assert statuses(log, seen["rid"]) == ["review"]


def test_a_failed_record_write_keeps_the_worker_owner(harness, monkeypatch):
    app_mod, mod, client, log, events, tmp = harness
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review"})
    stub_launches(app_mod, monkeypatch, [{}])
    real, seen = app_mod._write_run_log, {}

    def write(skill, status, *a, **k):
        if status == "review" and "rid" not in seen:
            seen["rid"] = k["run_id"]
            raise OSError("disk full, once")
        return real(skill, status, *a, **k)
    monkeypatch.setattr(app_mod, "_write_run_log", write)
    client.post("/api/runs/a/retry", json={})
    assert statuses(log, seen["rid"]) == ["error"]  # WS-009: not mistaken for a cancel


def staller(app_mod, monkeypatch, before=None):
    from runner.modules.stall_detection import check_once

    def stall(_proc):
        if before:
            before()
        monkeypatch.setattr(app_mod, "STALL_TIMEOUT_S", -1)
        check_once(app_mod, app_mod.socketio)
    return stall


def test_stall_owns_the_run_and_moves_the_ticket(harness, monkeypatch):
    app_mod, mod, client, log, events, tmp = harness
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review"})
    seen = {}

    def before():
        seen["rid"] = latest_job(app_mod)
        seen["state"] = tracker_state(tmp)
        mod.dispatched[ISSUE] = seen["rid"]
    stub_launches(app_mod, monkeypatch, [{"on_read": staller(app_mod, monkeypatch, before)}])
    client.post("/api/runs/a/retry", json={})
    assert seen["state"] != "In Review"
    assert statuses(log, seen["rid"])[-1] == "stalled"  # the worker wrote no review after it
    assert tracker_state(tmp) == "In Review" and ISSUE not in mod.dispatched  # WS-007


@pytest.mark.parametrize("move, expected", [("Todo", "Todo"), ("Done", "Done")])
def test_stall_keeps_a_ticket_reset_or_closed_during_the_run(harness, monkeypatch, move, expected):
    app_mod, mod, client, log, events, tmp = harness
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review"})

    def before():
        assert client.patch(f"/api/linear/issues/local/{ISSUE}", json={"state_name": move}).status_code == 200
    stub_launches(app_mod, monkeypatch, [{"on_read": staller(app_mod, monkeypatch, before)}])
    client.post("/api/runs/a/retry", json={})
    assert tracker_state(tmp) == expected  # WS-013


def test_a_late_worker_leaves_the_next_run_alone(harness, monkeypatch):
    app_mod, mod, client, log, events, tmp = harness
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review"})
    seen = {}
    cancel = canceller(app_mod, client, seen)

    def cancel_then_start_b(proc):
        cancel(proc)
        mod.push_state(ISSUE, "running")  # retry B takes the issue
        mod.dispatched[ISSUE] = "B"
    stub_launches(app_mod, monkeypatch, [{"on_read": cancel_then_start_b}])
    client.post("/api/runs/a/retry", json={})
    assert tracker_state(tmp) == "In Progress" and mod.dispatched[ISSUE] == "B"


# ── Real process groups through the routes ───────────────────────────────

def group_script(pidfile: Path) -> str:
    return f"sleep 60 & echo $! > {shlex.quote(str(pidfile))}; exec sleep 60"


def test_non_streaming_retry_timeout_kills_the_group(harness, monkeypatch):
    app_mod, mod, client, log, events, tmp = harness
    pidfile = tmp / "bg.pid"
    monkeypatch.setattr(subprocess, "Popen", lambda cmd, **kw: REAL_POPEN(["/bin/sh", "-c", group_script(pidfile)], **kw))
    monkeypatch.setattr(app_mod, "AI_RUN_TIMEOUT_S", 1)
    write_log(log, {"run_id": "a", "agent": "codex", "status": "review"})
    client.post("/api/runs/a/retry", json={})
    assert gone(int(pidfile.read_text()))
    rid = [r for r in map(json.loads, log.read_text().splitlines()) if r.get("parent_run_id") == "a"][-1]["run_id"]
    assert statuses(log, rid)[-1] == "timeout"


def test_linear_dispatch_timeout_kills_the_group(harness, monkeypatch):
    app_mod, mod, client, log, events, tmp = harness
    pidfile = tmp / "bg.pid"
    monkeypatch.setattr(app_mod, "_run_grouped", lambda *a, **k: (_ for _ in ()).throw(OSError("no router")))
    monkeypatch.setattr(subprocess, "Popen", lambda cmd, **kw: REAL_POPEN(["/bin/sh", "-c", group_script(pidfile)], **kw))
    monkeypatch.setattr(app_mod, "AI_RUN_TIMEOUT_S", 1)
    issue = {"id": ISSUE, "identifier": "T-1", "title": "t", "description": ""}
    mod._dispatch_issue_counted(issue, {"agent": {"backend": "codex"}}, app_mod.socketio)
    assert gone(int(pidfile.read_text()))
    assert [r["status"] for r in map(json.loads, log.read_text().splitlines())][-1] == "timeout"


TERM_IGNORER = "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"


def test_cancel_kills_a_term_ignoring_descendant(harness):
    app_mod, mod, client, log, events, tmp = harness
    proc = spawn(f"{shlex.quote(sys.executable)} -c {shlex.quote(TERM_IGNORER)} & echo $!; sleep 60")
    pid = int(proc.stdout.readline())
    app_mod._running_jobs["c"] = {"run_id": "c", "skill": "_prompt", "started_at": "", "prompt": "p"}
    app_mod._running_procs["c"] = proc
    try:
        assert client.delete("/api/runs/c").status_code == 200
        assert proc.poll() is not None
        assert gone(pid), "a SIGTERM-ignoring descendant survived the cancel (WS-002)"
    finally:
        kill_quietly(pid)
        with contextlib.suppress(OSError):
            os.killpg(proc.pid, signal.SIGKILL)


# ── Inspection 1 (RWS-001..004) ──────────────────────────────────────────

def test_linear_running_push_cannot_follow_a_cancel(harness, monkeypatch):
    app_mod, mod, client, log, events, tmp = harness
    seen = {}
    real_push = mod.push_state

    def push(issue_id, status, gen=None):
        if status == "running" and app_mod._running_jobs:  # the old order: job already cancellable
            canceller(app_mod, client, seen)(None)
        return real_push(issue_id, status, gen=gen)
    monkeypatch.setattr(mod, "push_state", push)
    monkeypatch.setattr(app_mod, "_run_grouped", lambda *a, **k: (_ for _ in ()).throw(OSError("no router")))
    stub_launches(app_mod, monkeypatch, [{"on_launch": canceller(app_mod, client, seen)}])
    mod._dispatch_issue_counted({"id": ISSUE, "identifier": "T-1", "title": "t", "description": ""},
                                {"agent": {"backend": "codex"}}, app_mod.socketio)
    assert seen["code"] == 200 and statuses(log, seen["rid"])[-1] == "cancelled"
    assert tracker_state(tmp) == "In Review"  # RWS-001: not left In Progress with no agent


def records(log, rid):
    return [r for r in map(json.loads, log.read_text().splitlines()) if r.get("run_id") == rid]


@pytest.mark.parametrize("ender", ["cancel", "stall"])
def test_cancel_and_stall_records_keep_the_launch_metadata(harness, monkeypatch, ender):
    app_mod, mod, client, log, events, tmp = harness
    write_log(log, {"run_id": "a", "agent": "codex", "status": "review"})
    seen = {}
    end = canceller(app_mod, client, seen) if ender == "cancel" else \
        staller(app_mod, monkeypatch, lambda: seen.update(rid=latest_job(app_mod)))
    stub_launches(app_mod, monkeypatch, [{"on_read": end}])
    client.post("/api/runs/a/retry", json={})
    rec = records(log, seen["rid"])[-1]
    assert rec["status"] == ("cancelled" if ender == "cancel" else "stalled")
    assert (rec["agent"], rec["task_id"], rec["parent_run_id"], rec["attempt"]) == ("codex", "T", "a", 1)  # RWS-002


@pytest.mark.parametrize("ender, status", [("cancel", "cancelled"), ("stall", "stalled")])
def test_a_failed_owner_record_write_is_retried(harness, monkeypatch, ender, status):
    app_mod, mod, client, log, events, tmp = harness
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review"})
    real, seen = app_mod._write_run_log, {}

    def write(skill, st, *a, **k):
        if st == status and "failed" not in seen:
            seen["failed"] = True
            raise OSError("disk full, once")
        return real(skill, st, *a, **k)
    monkeypatch.setattr(app_mod, "_write_run_log", write)
    end = canceller(app_mod, client, seen) if ender == "cancel" else \
        staller(app_mod, monkeypatch, lambda: seen.update(rid=latest_job(app_mod)))
    stub_launches(app_mod, monkeypatch, [{"on_read": end}])
    client.post("/api/runs/a/retry", json={})
    assert seen["failed"] and statuses(log, seen["rid"]) == [status]  # RWS-003


def test_one_failing_stall_does_not_stop_the_watchdog(harness, monkeypatch):
    app_mod, mod, client, log, events, tmp = harness
    from runner.modules.stall_detection import check_once
    for rid in ("x", "y"):
        app_mod._running_jobs[rid] = {"run_id": rid, "skill": "_prompt", "started_at": "", "prompt": "p",
                                      "last_progress_at": 0.0}
    real = app_mod._write_owner_record

    def owner(run_id, *a, **k):
        if run_id == "x":
            raise RuntimeError("boom")
        return real(run_id, *a, **k)
    monkeypatch.setattr(app_mod, "_write_owner_record", owner)
    monkeypatch.setattr(app_mod, "STALL_TIMEOUT_S", -1)
    check_once(app_mod, app_mod.socketio)  # must not raise (RWS-003)
    assert statuses(log, "y") == ["stalled"]


@pytest.mark.parametrize("reader, fail_at", [("_stream_text_run", 1), ("_stream_claude_run", 1),
                                             ("_stream_dsh_run", 1), ("_stream_dsh_run", 2)])
def test_a_reader_that_cannot_start_ends_the_run(app_mod, monkeypatch, reader, fail_at):
    started, real = [], app_mod._start_counted

    def start(fn, *a, **k):
        if len(started) + 1 == fail_at:
            raise RuntimeError("no thread")
        started.append(real(fn, *a, **k))
        return started[-1]
    monkeypatch.setattr(app_mod, "_start_counted", start)
    before = app_mod._INFLIGHT
    proc = spawn("sleep 60")
    with pytest.raises(RuntimeError):
        getattr(app_mod, reader)(proc, f"nostart-{reader}-{fail_at}", timeout=30)
    assert proc.poll() is not None  # RWS-004: the child does not outlive the failed start
    assert not any(t.is_alive() for t in started) and app_mod._INFLIGHT == before


# ── Inspection 2 (RWS-005..008) ──────────────────────────────────────────

def test_cancel_between_attempts_still_ends_the_first_group(harness, monkeypatch):
    app_mod, mod, client, log, events, tmp = harness
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID,
                    "linear_issue_id": None})  # a /run card: its resume keeps the fresh fallback (D3 covers tracker cards)
    seen = {}
    procs = stub_launches(app_mod, monkeypatch, [{"rc": 1}])

    class Jobs(dict):  # cancel exactly at the fallback decision, after attempt 1 returned
        def __contains__(self, rid):
            if procs and procs[0].returncode == 1 and "code" not in seen and dict.__contains__(self, rid) \
                    and procs[0].stdout.gi_frame is None:
                seen["rid"] = rid
                seen["code"] = client.delete(f"/api/runs/{rid}").status_code
            return dict.__contains__(self, rid)
    monkeypatch.setattr(app_mod, "_running_jobs", Jobs())
    client.post("/api/runs/a/retry", json={})
    assert seen["code"] == 200 and len(procs) == 1
    assert procs[0].killed, "the cancel lost the first attempt's group (RWS-005)"
    assert statuses(log, seen["rid"])[-1] == "cancelled"


def test_a_failed_timeout_record_write_is_retried(harness, monkeypatch):
    app_mod, mod, client, log, events, tmp = harness
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review"})
    real, seen = app_mod._write_run_log, {}

    def write(skill, st, *a, **k):
        if st == "timeout" and "failed" not in seen:
            seen["failed"], seen["rid"] = True, k["run_id"]
            raise OSError("disk full, once")
        return real(skill, st, *a, **k)
    monkeypatch.setattr(app_mod, "_write_run_log", write)

    def time_out(proc):  # the leader outlives the deadline
        proc.wait = lambda timeout=None: (_ for _ in ()).throw(subprocess.TimeoutExpired("agent", 1))
    stub_launches(app_mod, monkeypatch, [{"on_read": time_out}])
    client.post("/api/runs/a/retry", json={})
    assert seen["failed"] and statuses(log, seen["rid"]) == ["timeout"]  # RWS-006
    assert tracker_state(tmp) == "In Review"  # _finish still ran


def test_linear_start_failure_finishes_the_run(harness, monkeypatch):
    app_mod, mod, client, log, events, tmp = harness
    real_push = mod.push_state

    def push(issue_id, status, gen=None):
        if status == "running":
            raise RuntimeError("can't start thread")
        return real_push(issue_id, status, gen=gen)
    monkeypatch.setattr(mod, "push_state", push)
    monkeypatch.setattr(app_mod, "_run_grouped", lambda *a, **k: (_ for _ in ()).throw(OSError("no router")))
    procs = stub_launches(app_mod, monkeypatch, [{}])
    mod._dispatch_issue_counted({"id": ISSUE, "identifier": "T-1", "title": "t", "description": ""},
                                {"agent": {"backend": "codex"}}, app_mod.socketio)
    assert not procs and ISSUE not in mod.dispatched and not app_mod._running_jobs  # RWS-007
    last = [json.loads(l) for l in log.read_text().splitlines()][-1]
    assert (last["linear_issue_id"], last["status"]) == (ISSUE, "error")


@pytest.mark.parametrize("route", ["retry", "run"])
def test_a_setup_failure_after_launch_kills_the_agent(harness, monkeypatch, route):
    app_mod, mod, client, log, events, tmp = harness
    blocker = tmp / "not-a-dir"
    blocker.write_text("")
    monkeypatch.setattr(app_mod, "RUN_PROGRESS_DIR", blocker / "progress")  # mkdir fails after Popen
    launched = []
    monkeypatch.setattr(subprocess, "Popen", lambda cmd, **kw: launched.append(REAL_POPEN(["sleep", "60"], **kw)) or launched[-1])
    if route == "retry":
        write_log(log, {"run_id": "a", "agent": "claude", "status": "review"})
        client.post("/api/runs/a/retry", json={})
    else:
        client.post("/run", json={"prompt": "hi", "agent": "claude"})
    # returncode, not poll(): poll() would reap the child itself and hide a missing wait (RWS-010)
    assert launched and all(p.returncode is not None for p in launched)  # RWS-008


# ── Inspection 3 (RWS-009..010) ──────────────────────────────────────────

def test_buffered_lines_stop_with_the_reader(app_mod):
    import threading
    r, w = os.pipe()
    # ~1.8 KB: below any pipe capacity, so the write never blocks (RWS-012), and still one chunk
    # of many lines. A real pipe: epoll cannot watch regular files (RWS-019).
    os.write(w, b"".join(b"line %d\n" % i for i in range(200)))
    os.close(w)
    stop = threading.Event()
    with os.fdopen(r, "rb") as pipe:
        lines = app_mod._iter_pipe_lines(pipe, stop)
        assert next(lines) == b"line 0\n"
        stop.set()
        assert list(lines) == []  # RWS-009: the rest of the chunk is dropped, not drained


# ── Inspection 4 (RWS-011) ───────────────────────────────────────────────

def test_a_fallback_setup_failure_ends_the_first_attempts_group(harness, monkeypatch):
    app_mod, mod, client, log, events, tmp = harness
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID,
                    "linear_issue_id": None})  # a /run card: its resume keeps the fresh fallback (D3 covers tracker cards)
    procs = stub_launches(app_mod, monkeypatch, [{"rc": 1}])
    real_cmd = app_mod._ai_command

    def cmd(*a, **k):  # the fallback command cannot be built (e.g. SKILL.md unreadable)
        if procs:
            raise OSError("cannot read SKILL.md")
        return real_cmd(*a, **k)
    monkeypatch.setattr(app_mod, "_ai_command", cmd)
    client.post("/api/runs/a/retry", json={})
    assert len(procs) == 1 and procs[0].killed  # RWS-011
    rid = [r for r in map(json.loads, log.read_text().splitlines()) if r.get("parent_run_id") == "a"][-1]["run_id"]
    assert statuses(log, rid) == ["error"]


# ── Inspection 5 (RWS-013) ───────────────────────────────────────────────

@pytest.mark.parametrize("route", ["retry", "linear"])
@pytest.mark.parametrize("failure", ["timeout", "error"])
def test_a_failed_closing_comment_still_completes_the_ticket(harness, monkeypatch, route, failure):
    app_mod, mod, client, log, events, tmp = harness

    def fail(_proc):
        raise subprocess.TimeoutExpired("agent", 1) if failure == "timeout" else RuntimeError("agent crashed")
    stub_launches(app_mod, monkeypatch, [{"on_read": fail}])
    broken = {"n": 0}

    def comment(*a, **k):
        broken["n"] += 1
        raise OSError("tasks.json not writable, once")
    if route == "retry":
        monkeypatch.setattr(app_mod, "_post_linear_comment", comment)
        write_log(log, {"run_id": "a", "agent": "codex", "status": "review"})
        client.post("/api/runs/a/retry", json={})
    else:
        monkeypatch.setattr(mod, "post_comment", comment)
        monkeypatch.setattr(app_mod, "_run_grouped", lambda *a, **k: (_ for _ in ()).throw(OSError("no router")))
        mod._dispatch_issue_counted({"id": ISSUE, "identifier": "T-1", "title": "t", "description": ""},
                                    {"agent": {"backend": "codex"}}, app_mod.socketio)
    assert broken["n"] == 1
    assert tracker_state(tmp) == "In Review"  # RWS-013: completion ran despite the comment
    assert [json.loads(l)["status"] for l in log.read_text().splitlines()][-1] == failure


# ── Inspection 6 (RWS-014) ───────────────────────────────────────────────

def test_a_failed_feedback_comment_does_not_abort_the_retry(harness, monkeypatch):
    app_mod, mod, client, log, events, tmp = harness
    write_log(log, {"run_id": "a", "agent": "codex", "status": "review"})
    procs = stub_launches(app_mod, monkeypatch, [{}])
    broken = {"n": 0}

    def comment(*a, **k):
        broken["n"] += 1
        if broken["n"] == 1:
            raise OSError("tasks.json not writable, once")
    monkeypatch.setattr(app_mod, "_post_linear_comment", comment)
    r = client.post("/api/runs/a/retry", json={"reply": "please also add tests"})
    assert r.status_code == 200 and len(procs) == 1  # RWS-014: the run still launched
    assert tracker_state(tmp) == "In Review"


# ── Inspection 7 (RWS-015..016) ──────────────────────────────────────────

def test_a_failed_running_push_finishes_the_retry(harness, monkeypatch):
    app_mod, mod, client, log, events, tmp = harness
    write_log(log, {"run_id": "a", "agent": "codex", "status": "review"})
    procs = stub_launches(app_mod, monkeypatch, [{}])
    real_push = mod.push_state

    def push(issue_id, status, gen=None):
        if status == "running":
            raise RuntimeError("can't start thread")
        return real_push(issue_id, status, gen=gen)
    monkeypatch.setattr(mod, "push_state", push)
    r = client.post("/api/runs/a/retry", json={})
    assert r.status_code == 500 and not procs and not app_mod._running_jobs  # RWS-015
    assert ISSUE not in app_mod._linear_dispatched and tracker_state(tmp) == "In Review"
    rid = r.get_json()["run_id"]
    rec = records(log, rid)[-1]
    assert (rec["status"], rec["parent_run_id"], rec["attempt"]) == ("error", "a", 1)


def test_a_routing_timeout_kills_its_group(app_mod, tmp_path):
    pidfile = tmp_path / "bg.pid"
    with pytest.raises(subprocess.TimeoutExpired):
        app_mod._run_grouped(["/bin/sh", "-c", group_script(pidfile)], 1, text=True)
    assert gone(int(pidfile.read_text()))  # RWS-016


def test_linear_routing_goes_through_the_grouped_runner(harness, monkeypatch):
    app_mod, mod, client, log, events, tmp = harness
    calls = []
    monkeypatch.setattr(app_mod, "_run_grouped", lambda cmd, timeout, **kw: calls.append(timeout) or
                        subprocess.CompletedProcess(cmd, 0, "_prompt", ""))
    stub_launches(app_mod, monkeypatch, [{}])
    mod._dispatch_issue_counted({"id": ISSUE, "identifier": "T-1", "title": "t", "description": ""},
                                {"agent": {"backend": "codex"}}, app_mod.socketio)
    assert calls == [60]


# ── Inspection 8 (RWS-017..018) ──────────────────────────────────────────

def failing_worker_start(app_mod, monkeypatch, name, before=None):
    real = app_mod._start_counted

    def start(fn, *a, **k):
        if getattr(fn, "__name__", "") == name:
            if before:
                before()
            raise RuntimeError("can't start thread")
        return real(fn, *a, **k)
    monkeypatch.setattr(app_mod, "_start_counted", start)


def test_a_worker_start_failure_after_a_cancel_keeps_the_cancel(harness, monkeypatch):
    app_mod, mod, client, log, events, tmp = harness
    write_log(log, {"run_id": "a", "agent": "codex", "status": "review"})
    seen = {}
    failing_worker_start(app_mod, monkeypatch, "_do_retry", lambda: canceller(app_mod, client, seen)(None))
    r = client.post("/api/runs/a/retry", json={})
    assert seen["code"] == 200 and r.status_code == 409
    assert statuses(log, seen["rid"]) == ["cancelled"]  # RWS-018: no error appended after it


def test_a_confidential_project_retry_start_failure_withholds_the_feedback(harness, monkeypatch):
    app_mod, mod, client, log, events, tmp = harness
    write_log(log, {"run_id": "a", "agent": "codex", "status": "review"})
    binding = {"project_key": "demo", "issue_identifier": "T-1", "confidential": True}
    monkeypatch.setattr(app_mod, "_durable_binding", lambda *a, **k: dict(binding))
    monkeypatch.setattr(app_mod, "_ticket_confidential", lambda *a: True)
    monkeypatch.setattr(app_mod, "_records_unsafe", lambda: "run log outside the checkout")
    monkeypatch.setattr(app_mod, "_post_linear_comment", lambda *a, **k: None)
    failing_worker_start(app_mod, monkeypatch, "_run_project_ticket")
    r = client.post("/api/runs/a/retry", json={"reply": "SECRET-FEEDBACK-42"})
    assert r.status_code == 500
    assert "SECRET-FEEDBACK-42" not in log.read_text()  # RWS-017
    rec = records(log, r.get_json()["run_id"])[-1]
    assert rec["status"] == "error" and rec["project_key"] == "demo" and rec["prompt"].startswith("[withheld")


# ── Inspection 9 (RWS-019) ───────────────────────────────────────────────

def test_a_pipe_above_fd_setsize_is_still_read(app_mod):
    import resource
    import threading
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    want = 1500
    if soft <= want:
        if hard != resource.RLIM_INFINITY and hard <= want:
            pytest.skip("open-file hard limit too low for a descriptor above FD_SETSIZE")
        resource.setrlimit(resource.RLIMIT_NOFILE, (want + 100, hard))
    r, w = os.pipe()
    high = os.dup2(r, want)
    os.close(r)
    try:
        os.write(w, b"hi\n")
        os.close(w)
        with os.fdopen(high, "rb") as pipe:
            assert list(app_mod._iter_pipe_lines(pipe, threading.Event())) == [b"hi\n"]  # RWS-019
    finally:
        resource.setrlimit(resource.RLIMIT_NOFILE, (soft, hard))


@pytest.mark.parametrize("reader", READERS)
def test_a_failing_reader_ends_the_run_with_its_error(app_mod, monkeypatch, reader):
    def broken(pipe, stop):
        raise RuntimeError("reader crashed")
        yield  # pragma: no cover
    monkeypatch.setattr(app_mod, "_iter_pipe_lines", broken)
    proc = spawn("sleep 60")
    with pytest.raises(RuntimeError, match="reader crashed"):
        getattr(app_mod, reader)(proc, f"crash-{reader}", timeout=30)
    assert proc.returncode is not None  # killed and reaped by the controller (RWS-019)


# ── Inspection 10 (RWS-020..021) ─────────────────────────────────────────

def test_a_project_retry_start_failure_withholds_even_on_a_stale_public_snapshot(harness, monkeypatch):
    app_mod, mod, client, log, events, tmp = harness
    write_log(log, {"run_id": "a", "agent": "codex", "status": "review"})
    binding = {"project_key": "demo", "issue_identifier": "T-1", "confidential": False}  # promoted since
    monkeypatch.setattr(app_mod, "_durable_binding", lambda *a, **k: dict(binding))
    monkeypatch.setattr(app_mod, "_ticket_confidential", lambda *a: False)
    monkeypatch.setattr(app_mod, "_records_unsafe", lambda: "run log outside the checkout")
    monkeypatch.setattr(app_mod, "_post_linear_comment", lambda *a, **k: None)
    failing_worker_start(app_mod, monkeypatch, "_run_project_ticket")
    r = client.post("/api/runs/a/retry", json={"reply": "SECRET-FEEDBACK-43"})
    assert r.status_code == 500 and "SECRET-FEEDBACK-43" not in log.read_text()  # RWS-020


def test_a_failed_record_write_still_ends_the_attempts_group(harness, monkeypatch):
    app_mod, mod, client, log, events, tmp = harness
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review"})
    procs = stub_launches(app_mod, monkeypatch, [{}])
    real, seen = app_mod._write_run_log, {}

    def write(skill, status, *a, **k):
        if status == "review" and "failed" not in seen:
            seen["failed"] = True
            procs[0].killed = False  # only a kill after this point counts
            raise OSError("disk full, once")
        return real(skill, status, *a, **k)
    monkeypatch.setattr(app_mod, "_write_run_log", write)
    client.post("/api/runs/a/retry", json={})
    assert seen["failed"] and procs[0].killed  # RWS-021: leftovers of the attempt end too
