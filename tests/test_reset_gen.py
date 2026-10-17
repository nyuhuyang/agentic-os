"""Decision 11 / DSH-30: a tracker reset starts the next retry fresh, and older runs never move the ticket."""

import json
import sys
import threading
import time
from pathlib import Path

import pytest

RUNNER = Path(__file__).resolve().parents[1] / "runner"
sys.path.insert(0, str(RUNNER))
sys.path.insert(0, str(RUNNER.parent))

ISSUE = "iss-1"
_MOD = None
SID = "session-old"


class SyncThread:
    def __init__(self, target, args=(), daemon=None, **_):
        self.target, self.args = target, args
    def start(self): self.target(*self.args)
    def join(self, timeout=None): pass
    def is_alive(self): return False


@pytest.fixture
def env(tmp_path, monkeypatch):
    import app as app_mod
    import reset_gen
    import runner.modules.linear as lin
    from runner.core.module_registry import registry

    monkeypatch.setattr(reset_gen, "GEN_PATH", tmp_path / "reset_generations.json")
    monkeypatch.setattr(lin, "STATE_DIR", tmp_path)
    import projects
    monkeypatch.setattr(projects, "CARD_LOCK_DIR", tmp_path / "card-locks")  # never the real home dir
    log = tmp_path / "run_log.jsonl"
    for name in ("RUN_LOG", "STATE_RUN_LOG"):
        monkeypatch.setattr(app_mod, name, log if name == "RUN_LOG" else tmp_path / "runs.jsonl")
    monkeypatch.setattr(app_mod, "RUN_PROGRESS_DIR", tmp_path)
    monkeypatch.setattr(app_mod, "STATE_TASK_STATE", tmp_path / "task_state.json")
    monkeypatch.setattr(app_mod, "JOB_STATE", tmp_path / "job_state.json")
    monkeypatch.setattr(app_mod, "OUTPUTS_DIR", tmp_path)
    monkeypatch.setattr(app_mod, "STATE_DIR", tmp_path)
    monkeypatch.setattr(app_mod, "_load_registry", lambda agent: {})
    monkeypatch.setattr(app_mod, "_registry_exec_env", lambda agent, reg: {})
    events = []
    monkeypatch.setattr(app_mod.socketio, "emit", lambda *a, **k: events.append(a))
    monkeypatch.setattr(app_mod.threading, "Thread", SyncThread)
    monkeypatch.setattr(lin.threading, "Thread", SyncThread)
    monkeypatch.setattr(lin, "_load_workflow_config", lambda: {"tracker": {"kind": "local"}})

    # Flask routes close over the instance that registered them, so every test shares one
    # instance and resets its state instead of creating a new one.
    global _MOD
    if _MOD is None:
        _MOD = lin.LinearModule()
        got, app_mod.app._got_first_request = app_mod.app._got_first_request, False
        _MOD._register_linear_routes(app_mod.app)
        app_mod.app._got_first_request = got
    mod = _MOD
    mod.issues_cache.clear(); mod.dispatched.clear(); mod._local_overrides.clear()
    mod._capability = {"available": True, "type": "local"}
    monkeypatch.setitem(registry._modules, "linear", mod)

    from runner.modules.linear.local_tracker import LocalTracker
    import state_io
    state_io.write_json_atomic(tmp_path / "tasks.json", {ISSUE: {"id": ISSUE, "state": "In Review", "title": "t"}})
    mod._local_tracker = LocalTracker(tmp_path)

    client = app_mod.app.test_client()
    client.environ_base["HTTP_X_AGENTICOS_TOKEN"] = app_mod.REQUEST_TOKEN
    return app_mod, mod, client, log, events, tmp_path


def write_log(log, *records):
    with log.open("a") as f:
        for r in records:
            f.write(json.dumps({"task_id": "T", "linear_issue_id": ISSUE, "skill": "_prompt",
                                "prompt": "task", **r}) + "\n")


def capture_launches(app_mod, monkeypatch, on_launch=None, result=None):
    """Stub process launch: record the command; optionally run a callback mid-run."""
    cmds = []

    class Proc:
        def __init__(self, cmd, **kw):
            cmds.append(cmd)
            if on_launch:
                on_launch()
            out = json.dumps(result) if result else ""
            self.stdout = iter([out.encode()]) if result else iter([])
            self.stderr = type("E", (), {"read": lambda s: b""})()
            self.returncode = 0
            self.args = cmd
        def communicate(self, timeout=None):
            return (json.dumps(result).encode() if result else b"", b"")
        def wait(self, timeout=None): return 0
        def poll(self): return 0
        def kill(self): pass

    monkeypatch.setattr(app_mod.subprocess, "Popen", Proc)
    return cmds


def reset_route(client):
    r = client.patch(f"/api/linear/issues/local/{ISSUE}", json={"state_name": "Todo"})
    assert r.status_code == 200


def resumed(cmd):
    return any(flag in cmd for flag in ("--resume", "--session-id")) or (len(cmd) > 3 and "resume" in cmd[:4])


@pytest.mark.parametrize("agent", ["claude", "codex", "dsh"])
def test_tracker_reset_route_then_retry_starts_fresh(env, monkeypatch, agent):
    app_mod, mod, client, log, events, _ = env
    write_log(log, {"run_id": "a", "agent": agent, "status": "review", "agent_session_id": SID})
    assert app_mod._get_task_agent_lock("T")["agent_session_id"] == SID  # before: would resume
    reset_route(client)
    cmds = capture_launches(app_mod, monkeypatch)
    client.post("/api/runs/a/retry", json={})
    assert cmds and not resumed(cmds[0]) and SID not in cmds[0]


def test_agent_change_honored_after_reset(env, monkeypatch):
    app_mod, mod, client, log, events, _ = env
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID})
    reset_route(client)
    cmds = capture_launches(app_mod, monkeypatch)
    r = client.post("/api/runs/a/retry", json={"agent": "codex"})
    assert r.get_json()["agent"] == "codex" and cmds[0][0] == "codex"


def test_old_run_completing_after_reset_neither_resumes_nor_moves_ticket(env, monkeypatch):
    app_mod, mod, client, log, events, tmp = env
    write_log(log, {"run_id": "a", "agent": "codex", "status": "review", "agent_session_id": SID})
    real_log = app_mod._write_run_log
    # The retry launches under the current generation; mid-run the user drags the ticket to Todo.
    capture_launches(app_mod, monkeypatch, on_launch=lambda: reset_route(client),
                     result={"type": "thread.started", "thread_id": "session-new"})
    monkeypatch.setattr(app_mod, "_write_run_log", real_log)
    events.clear()
    client.post("/api/runs/a/retry", json={})
    tasks = json.loads((tmp / "tasks.json").read_text())
    assert tasks[ISSUE]["state"] == "Todo"  # the old run's completion did not push In Review
    assert not [e for e in events if e[0] == "run_state_change" and e[1].get("state") == "review"]
    # ... and its session id is never resumed
    assert app_mod._get_task_agent_lock("T") is None
    cmds = capture_launches(app_mod, monkeypatch)
    client.post("/api/runs/a/retry", json={})
    assert not resumed(cmds[0]) and "session-new" not in cmds[0]


def test_restored_pre_reset_run_is_not_resumed(env, monkeypatch):
    app_mod, mod, client, log, events, _ = env
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID})
    reset_route(client)
    write_log(log, {"run_id": "a", "agent": "claude", "status": "archived", "prev_status": "review",
                    "agent_session_id": SID})
    assert client.post("/api/runs/a/restore").status_code == 200
    cmds = capture_launches(app_mod, monkeypatch)
    client.post("/api/runs/a/retry", json={})
    assert not resumed(cmds[0])


def test_reset_then_fresh_launch_failing_before_session_then_retry_still_fresh(env, monkeypatch):
    app_mod, mod, client, log, events, _ = env
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID})
    reset_route(client)
    import reset_gen
    write_log(log, {"run_id": "b", "agent": "claude", "status": "error", "reset_gen": reset_gen.current(ISSUE)})
    cmds = capture_launches(app_mod, monkeypatch)
    client.post("/api/runs/b/retry", json={})
    assert not resumed(cmds[0])


def test_in_flight_push_racing_a_reset_loses(env, monkeypatch):
    app_mod, mod, client, log, events, tmp = env
    import reset_gen
    gen = reset_gen.current(ISSUE)
    entered, release = threading.Event(), threading.Event()
    real_push = mod.get_local_tracker().push_state

    def slow_push(issue_id, status):
        entered.set()
        release.wait(5)  # the network call is slow; the reset arrives meanwhile
        real_push(issue_id, status)

    monkeypatch.setattr(mod.get_local_tracker(), "push_state", slow_push)
    import runner.modules.linear as lin
    monkeypatch.setattr(lin.threading, "Thread", threading.Thread)
    mod.push_state(ISSUE, "review", gen=gen)  # an old run's completion push, now in flight
    assert entered.wait(5)
    reset_thread = threading.Thread(target=reset_route, args=(client,))
    reset_thread.start()
    time.sleep(0.3)
    release.set()
    reset_thread.join(10)
    tasks = json.loads((tmp / "tasks.json").read_text())
    assert tasks[ISSUE]["state"] == "Todo"  # the reset was applied last
    # a push that starts after the reset is dropped outright
    mod.push_state(ISSUE, "review", gen=gen)
    time.sleep(0.3)
    assert json.loads((tmp / "tasks.json").read_text())[ISSUE]["state"] == "Todo"


class FakeLinearClient:
    calls: list = []

    def __init__(self, *a, **k): pass
    def ensure_label(self, team, name): return f"label-{name}"
    def create_issue(self, team, title, desc, label_ids=None): return {"id": "real-1", "title": title, "description": desc}
    def fetch_issue(self, i): return {"id": i, "title": "t", "description": "", "state": "Todo"}
    def update_issue(self, i, **kw): self.calls.append(("update", kw))
    def update_issue_state(self, i, s): self.calls.append(("state", s))


def test_background_linear_create_swaps_placeholder(env, monkeypatch):
    """I5-05: the placeholder swap goes through the locked raw transaction."""
    import types
    import runner.modules.linear as lin
    app_mod, mod, client, log, events, tmp = env
    monkeypatch.setitem(sys.modules, "linear_client", types.SimpleNamespace(LinearClient=FakeLinearClient))
    monkeypatch.setattr(lin, "_linear_api_key_from_cfg", lambda tc: "k")
    monkeypatch.setattr(lin, "_post_linear_comment_raw", lambda *a: True)
    monkeypatch.setattr(lin, "record_id_alias", lambda *a: None)
    mod._capability = {"available": True, "type": "linear"}
    local_id = client.post("/api/linear/issues", json={"title": "new", "team_id": "team"}).get_json()["issue"]["id"]
    tasks = json.loads((tmp / "tasks.json").read_text())
    assert "real-1" in tasks and local_id not in tasks and ISSUE in tasks
    assert "real-1" in mod.issues_cache and local_id not in mod.issues_cache


def test_state_sync_queued_before_reset_is_dropped(env, monkeypatch):
    """I5-06: a state change queued under an older generation never lands after a reset."""
    import types
    import reset_gen
    app_mod, mod, client, *_ = env
    monkeypatch.setitem(sys.modules, "linear_client", types.SimpleNamespace(LinearClient=FakeLinearClient))
    FakeLinearClient.calls = []
    gen = reset_gen.current(ISSUE)
    reset_gen.bump(ISSUE)
    mod._linear_sync_patch(ISSUE, {"state_name": "In Progress", "title": "x"}, {"tracker": {"api_key": "k"}}, None, gen)
    assert [c[0] for c in FakeLinearClient.calls] == ["update"]
    mod._linear_sync_patch(ISSUE, {"state_name": "Todo"}, {"tracker": {"api_key": "k"}}, None, reset_gen.current(ISSUE))
    assert FakeLinearClient.calls[-1] == ("state", "Todo")


class StopLoop(BaseException):
    pass


def test_poll_snapshot_never_overwrites_a_reset_made_during_the_fetch(env, monkeypatch):
    """I6-11: a reset landing while the poller fetches keeps its Todo state."""
    import types
    import reset_gen
    import runner.modules.linear as lin
    app_mod, mod, client, *_ = env

    class PollClient(FakeLinearClient):
        def fetch_issues(self, states, team_id=None):
            with reset_gen.issue_lock(ISSUE):  # what the reset route does, mid-fetch
                reset_gen.bump(ISSUE)
                mod.issues_cache[ISSUE] = {"id": ISSUE, "state": "Todo", "title": "t"}
            return [{"id": ISSUE, "state": "In Progress", "title": "t", "description": ""}]

    def stop(_):
        raise StopLoop
    monkeypatch.setitem(sys.modules, "linear_client", types.SimpleNamespace(LinearClient=PollClient))
    monkeypatch.setattr(lin, "_load_workflow_config", lambda: {"tracker": {"kind": "linear", "api_key": "k", "team_id": "team"}})
    monkeypatch.setattr(lin, "time", types.SimpleNamespace(sleep=stop, monotonic=time.monotonic, time=time.time))
    mod.dispatches_warmed = True
    with pytest.raises(StopLoop):
        mod._polling_loop(app_mod.socketio)
    assert mod.issues_cache[ISSUE]["state"] == "Todo"


def test_poll_keeps_a_terminal_ticket_reset_during_the_fetch(env, monkeypatch):
    """I7-04: a cached Done ticket reset to Todo mid-fetch is not restored as Done."""
    import types
    import reset_gen
    import runner.modules.linear as lin
    app_mod, mod, client, *_ = env
    mod.issues_cache[ISSUE] = {"id": ISSUE, "state": "Done", "title": "t", "team_id": "team"}

    class PollClient(FakeLinearClient):
        def fetch_issues(self, states, team_id=None):
            with reset_gen.issue_lock(ISSUE):
                reset_gen.bump(ISSUE)
                mod.issues_cache[ISSUE] = {"id": ISSUE, "state": "Todo", "title": "t", "team_id": "team"}
            return []  # Done is not an active state: the fetch does not include it

    def stop(_):
        raise StopLoop
    monkeypatch.setitem(sys.modules, "linear_client", types.SimpleNamespace(LinearClient=PollClient))
    monkeypatch.setattr(lin, "_load_workflow_config", lambda: {"tracker": {"kind": "linear", "api_key": "k", "team_id": "team"}})
    monkeypatch.setattr(lin, "time", types.SimpleNamespace(sleep=stop, monotonic=time.monotonic, time=time.time))
    mod.dispatches_warmed = True
    with pytest.raises(StopLoop):
        mod._polling_loop(app_mod.socketio)
    assert mod.issues_cache[ISSUE]["state"] == "Todo"
    assert mod._issues_by_team["team"][ISSUE]["state"] == "Todo"  # team board too (I8-07)


def test_agent_sync_never_doubles_the_marker(env, monkeypatch):
    """AGE-104: starting a card without a description edit keeps Linear's text and one agent marker."""
    import types
    app_mod, mod, client, *_ = env

    class MarkedClient(FakeLinearClient):
        def fetch_issue(self, i):
            return {"id": i, "title": "t", "description": "keep me\n\n<!-- agent_backend: claude -->", "state": "Todo"}

    monkeypatch.setitem(sys.modules, "linear_client", types.SimpleNamespace(LinearClient=MarkedClient))
    MarkedClient.calls = []
    mod._linear_sync_patch_locked(ISSUE, {"state_name": "In Progress"}, {"tracker": {"api_key": "k"}}, "claude")
    assert MarkedClient.calls[0] == ("update", {"description": "keep me\n\n<!-- agent_backend: claude -->"})
