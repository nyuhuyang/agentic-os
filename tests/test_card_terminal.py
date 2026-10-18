"""Answering a session that stopped for review (dashboard UI plan, part C2): quick reply in
strict continuation, card locks, card-only terminals, the interactive-ended record, and the
"Waiting for you" heuristic. Stub processes and fake names only."""

import json
import sys
from pathlib import Path

import pytest

RUNNER = Path(__file__).resolve().parents[1] / "runner"
sys.path.insert(0, str(RUNNER))
sys.path.insert(0, str(RUNNER.parent))

import project_runs as pr  # noqa: E402
from test_reset_gen import ISSUE, SID, env, on_disk, write_log  # noqa: E402,F401  (env: fixture)
from test_runner_write_safety import statuses, stub_launches, tracker_state  # noqa: E402


@pytest.fixture
def harness(env, monkeypatch, tmp_path):
    app_mod, mod, client, log, events, tmp = env
    import projects as pj
    monkeypatch.setattr(app_mod, "_running_jobs", {})
    monkeypatch.setattr(app_mod, "_running_procs", {})
    monkeypatch.setattr(app_mod, "_SESSION_CLAIMS", {})  # stubbed launch helpers never release theirs
    monkeypatch.setattr(app_mod, "_INFLIGHT", app_mod._INFLIGHT)
    monkeypatch.setattr(pj, "CARD_LOCK_DIR", tmp_path / "card-locks")
    monkeypatch.setattr(pj, "WORKTREE_ROOT", tmp_path / "wt")
    return env


def records(log):
    return [json.loads(l) for l in log.read_text().splitlines()]


@pytest.mark.parametrize("text, expected", [
    ("Plan reviewed.\nShall I start the build?", "Plan reviewed."),
    ("Done. Please approve the plan to continue", "Done. Please approve the plan to continue"),
    ("Codex returned APPROVED.", None),  # statements, not requests (FB-02)
    ("Got your sign-off; build finished.", None),  # FB2-04
    ("All done. Let me know if you need anything else.", None),
    ("检查是否通过。", None),
    ("计划已审阅。\n要开始构建吗？", "计划已审阅。"),
    ("已完成，请确认是否合并", "已完成，请确认是否合并"),
    ("All tests pass. The branch is ready.", None),
    ("已完成全部修改。", None),
    ("", None),
])
def test_waiting_detection(text, expected):
    assert pr.waiting_question(text) == expected


def test_waiting_ignores_the_verify_tail(harness):
    app_mod, mod, client, log, events, tmp = harness
    out = "Done.\nShall I start the build?\n\n[verify tail]\n" + "\n".join(f"test {i} ok" for i in range(20))
    write_log(log, {"run_id": "v", "agent": "claude", "status": "review", "output": out})
    ev = client.get("/api/runs/v/events").get_json()
    assert ev["waiting"] == "Done." and ev["last_message"].endswith("Shall I start the build?")  # UI-09


def test_runner_root_dispatch_holds_the_card_through_the_run(harness, monkeypatch):
    app_mod, mod, client, log, events, tmp = harness
    import projects as pj
    seen = []
    monkeypatch.setattr(app_mod, "run_agent_process",
                        lambda rid, cmd, **kw: (seen.append(pj.card_busy(None, None, ISSUE)), ("ok", 1, 1, None, None, "", True))[1])
    monkeypatch.setattr(app_mod, "_run_grouped", lambda *a, **k: type("R", (), {"stdout": ""})())
    issue = {"id": ISSUE, "identifier": "LOC-1", "title": "t", "description": "", "labels": []}
    with pj.card_lock(ISSUE):  # an interactive terminal holds the card
        mod._dispatch_issue(issue, {"agent": {"backend": "claude"}}, app_mod.socketio)
    assert seen == []  # refused, nothing launched
    mod._dispatch_issue(issue, {"agent": {"backend": "claude"}}, app_mod.socketio)
    assert seen == [True] and not pj.card_busy(None, None, ISSUE)  # held during the run, released after (UI-02)


def test_review_runs_carry_waiting_and_the_last_message(harness):
    app_mod, mod, client, log, events, tmp = harness
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "output": "Ready.\nShall I merge?"},
              {"run_id": "b", "agent": "claude", "status": "error", "output": "Shall I?"})
    runs = {r["run_id"]: r for r in client.get("/api/runs?limit=10").get_json()}
    assert runs["a"]["waiting"] == "Ready." and runs["b"]["waiting"] is None
    ev = client.get("/api/runs/a/events").get_json()
    assert ev["last_message"].endswith("Shall I merge?") and ev["waiting"] == "Ready." and ev["card_key"] == ISSUE


def test_quick_reply_resumes_the_same_session(harness, monkeypatch):
    app_mod, mod, client, log, events, tmp = harness
    on_disk(app_mod, "claude", SID)
    monkeypatch.setattr(app_mod, "_process_table", lambda: {})
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID})
    from test_reset_gen import capture_launches
    cmds = capture_launches(app_mod, monkeypatch, result={"type": "result", "result": "done", "session_id": SID})
    r = client.post("/api/runs/a/retry", json={"reply": "go ahead", "strict": True})
    assert r.status_code == 200 and len(cmds) == 1  # a continuation must reply to count (R14-01)
    assert "--resume" in cmds[0] and SID in cmds[0] and any("go ahead" in a for a in cmds[0])
    assert statuses(log, r.get_json()["run_id"]) == ["review"]


def test_strict_continuation_never_falls_back(harness, monkeypatch):
    app_mod, mod, client, log, events, tmp = harness
    on_disk(app_mod, "claude", SID)
    monkeypatch.setattr(app_mod, "_process_table", lambda: {})
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID})
    procs = stub_launches(app_mod, monkeypatch, [{"rc": 1}])
    rid = client.post("/api/runs/a/retry", json={"reply": "x", "strict": True}).get_json()["run_id"]
    assert len(procs) == 1  # the failed resume is the attempt: no fresh session
    (rec,) = [r for r in records(log) if r["run_id"] == rid]  # one attempt, one record
    assert rec["status"] == "error" and SID in rec["error"]  # reported as a failed continuation (UI-06)
    # a card without a resumable session is refused before anything happens
    write_log(log, {"run_id": "c", "agent": "claude", "status": "todo", "linear_issue_id": "other"})
    before = log.read_text()
    assert client.post("/api/runs/c/retry", json={"reply": "x", "strict": True}).status_code == 409
    assert log.read_text() == before


def test_strict_continuation_resumes_even_for_an_entrypoint_skill(harness, monkeypatch):
    app_mod, mod, client, log, events, tmp = harness
    monkeypatch.setattr(app_mod, "_load_registry", lambda agent: {"sk": {"schedule_eligible": True, "entrypoint": "x"}})
    write_log(log, {"run_id": "a", "skill": "sk", "agent": "claude", "status": "review", "agent_session_id": SID})
    procs = stub_launches(app_mod, monkeypatch, [{}])
    client.post("/api/runs/a/retry", json={"reply": "x", "strict": True})
    assert "--resume" in procs[0].args


@pytest.mark.parametrize("card", ["linear", "run"])
def test_interactive_lock_refuses_quick_reply_and_retry(harness, monkeypatch, card):
    app_mod, mod, client, log, events, tmp = harness
    import projects as pj
    if card == "linear":  # runner-root card with a tracker issue
        write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID})
        key = ISSUE
    else:  # dashboard /run card: no tracker id, the root task id is the key
        write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID,
                        "linear_issue_id": None, "task_id": "task-1"})
        key = "task-1"
    procs = stub_launches(app_mod, monkeypatch, [{}])
    before = (log.read_text(), tracker_state(tmp))
    with pj.card_lock(key):  # the card's interactive terminal is open
        for body in ({"reply": "x", "strict": True}, {}):
            r = client.post("/api/runs/a/retry", json=body)
            assert r.status_code == 409 and "busy" in r.get_json()["error"]
    assert procs == [] and (log.read_text(), tracker_state(tmp)) == before  # no attempt, no tracker change
    assert client.post("/api/runs/a/retry", json={}).status_code == 200  # free again


def test_card_key_spans_attempts_and_separates_tasks(harness, monkeypatch):
    app_mod, mod, client, log, events, tmp = harness
    import projects as pj
    write_log(log, {"run_id": "a1", "agent": "claude", "status": "review", "linear_issue_id": None, "task_id": "t-A"},
              {"run_id": "a2", "agent": "claude", "status": "review", "linear_issue_id": None, "task_id": "t-A",
               "attempt": 1, "parent_run_id": "a1"},
              {"run_id": "b1", "agent": "claude", "status": "review", "linear_issue_id": None, "task_id": "t-B"})
    stub_launches(app_mod, monkeypatch, [{}, {}])
    with pj.card_lock("t-A"):  # interactive tab opened on attempt 1
        assert client.post("/api/runs/a2/retry", json={}).status_code == 409  # attempt 2 is the same card
        assert client.post("/api/runs/b1/retry", json={}).status_code == 200  # an unrelated task


def test_project_card_lock_refuses_quick_reply(harness, monkeypatch):
    app_mod, mod, client, log, events, tmp = harness
    import projects as pj
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID,
                    "project_key": "demo", "issue_identifier": "T-1"})
    launched = []
    monkeypatch.setattr(app_mod, "_run_project_ticket", lambda **kw: launched.append(kw))
    before = (log.read_text(), tracker_state(tmp))
    with pj.ticket_lock("demo", "T-1"):
        assert client.post("/api/runs/a/retry", json={"reply": "x", "strict": True}).status_code == 409
    assert launched == [] and (log.read_text(), tracker_state(tmp)) == before
    assert client.post("/api/runs/a/retry", json={"reply": "x", "strict": True}).status_code == 200
    # SID is not in any session store here: a new session, said so (D3, R2)
    assert launched[0]["ticket_hold"] is not None and launched[0]["resume_session"] is None and launched[0]["note"]


def test_dispatch_is_refused_while_the_card_is_held(harness):
    app_mod, mod, client, log, events, tmp = harness
    import projects as pj
    with pj.card_lock(ISSUE):
        r = client.patch(f"/api/linear/issues/{ISSUE}", json={"state_name": "In Progress"})
        assert r.status_code == 409
    assert tracker_state(tmp) == "In Review"


def test_closing_a_card_session_records_it_once_from_any_entry_point(harness, monkeypatch):
    app_mod, mod, client, log, events, tmp = harness
    import runner.modules.pty as pty_mod
    monkeypatch.setattr(pty_mod, "TERMINALS", {})
    monkeypatch.setattr(pty_mod, "_spawn", lambda t, argv, env, cols, rows, sio: setattr(t, "pid", None))
    monkeypatch.setattr(pty_mod, "_kill_session", lambda t: None)
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID})
    info = pty_mod.open_terminal({"kind": "resume", "agent": "claude", "session_id": SID, "in_panel": False,
                                  "run_id": "a"}, None)
    out = pty_mod.close_terminal(info["term_id"])  # the panel's close and the card's End use this same path
    assert out["run_id"] == "a"
    ended = [r for r in records(log) if r.get("interactive_ended")]
    assert len(ended) == 1 and ended[0]["output"] == "interactive session ended"
    assert ended[0]["agent_session_id"] == SID and ended[0]["parent_run_id"] == "a"  # server-held id (UI2-06)
    assert ended[0]["prompt"] == "task"  # audit entry keeps the retry context (UI-08)
    shell = pty_mod.open_terminal({"kind": "shell"}, None)
    pty_mod.close_terminal(shell["term_id"])
    assert len([r for r in records(log) if r.get("interactive_ended")]) == 1  # shells never record


def test_projects_panel_resume_of_a_card_session_holds_the_card(harness, monkeypatch, tmp_path):
    app_mod, mod, client, log, events, tmp = harness
    import projects as pj
    import runner.modules.pty as pty_mod
    monkeypatch.setattr(pty_mod, "TERMINALS", {})
    monkeypatch.setattr(pty_mod, "_spawn", lambda t, argv, env, cols, rows, sio: setattr(t, "pid", 1))
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID})
    info = pty_mod.open_terminal({"kind": "resume", "agent": "claude", "session_id": SID}, None)  # no run_id
    assert info["card_key"] == ISSUE and pj.card_busy(None, None, ISSUE)  # UI2-01
    assert client.post("/api/runs/a/retry", json={"reply": "x", "strict": True}).status_code == 409
    for t in pty_mod.TERMINALS.values():
        t.holds.close()


def test_streaming_is_progress_and_cancel_keeps_the_session(harness, monkeypatch):
    app_mod, mod, client, log, events, tmp = harness
    app_mod._running_jobs["r"] = {"run_id": "r", "skill": "_prompt", "started_at": "", "prompt": "p",
                                  "last_progress_at": 0.0, "agent": "claude", "record": {"agent": "claude"}}
    app_mod._publish_run_line("r", "claude", json.dumps({"type": "system", "session_id": "s-9"}))
    job = app_mod._running_jobs["r"]
    assert job["last_progress_at"] > 0 and job["agent_session_id"] == "s-9"  # UI2-03
    assert client.delete("/api/runs/r").status_code == 200
    assert records(log)[-1]["status"] == "cancelled" and records(log)[-1]["agent_session_id"] == "s-9"  # UI2-04


def test_card_terminals_stay_out_of_the_panel(harness, monkeypatch, tmp_path):
    app_mod, mod, client, log, events, tmp = harness
    import runner.modules.pty as pty_mod
    monkeypatch.setattr(pty_mod, "TERMINALS", {})
    monkeypatch.setattr(pty_mod, "_spawn", lambda t, argv, env, cols, rows, sio: setattr(t, "pid", 1))
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID})
    card = pty_mod.open_terminal({"kind": "resume", "agent": "claude", "session_id": SID, "in_panel": False,
                                  "run_id": "a", "card_key": "spoofed"}, None)  # the browser's key is ignored (UI-03)
    shell = pty_mod.open_terminal({"kind": "shell"}, None)
    assert card["in_panel"] is False and card["card_key"] == ISSUE and shell["in_panel"] is True
    import projects as pj
    assert pj.card_busy(None, None, ISSUE)  # the open session holds the card
    pty_mod.TERMINALS[card["term_id"]].in_panel = True  # what term_show does
    assert pty_mod.TERMINALS[card["term_id"]].info()["in_panel"] is True
    for t in pty_mod.TERMINALS.values():
        t.holds.close()
    assert not pj.card_busy(None, None, ISSUE)


def test_patch_reserves_the_card_and_the_dispatch_keeps_it(harness, monkeypatch):
    app_mod, mod, client, log, events, tmp = harness
    import projects as pj
    seen = []
    monkeypatch.setattr(app_mod, "run_agent_process",
                        lambda rid, cmd, **kw: (seen.append(pj.card_busy(None, None, ISSUE)), ("ok", 1, 1, None, None, "", True))[1])
    monkeypatch.setattr(app_mod, "_run_grouped", lambda *a, **k: type("R", (), {"stdout": ""})())
    monkeypatch.setattr(mod, "_socketio", app_mod.socketio)
    import state_io
    state_io.write_json_atomic(tmp / "tasks.json", {ISSUE: {"id": ISSUE, "identifier": "LOC-1", "state": "Todo",
                                                            "title": "t", "description": ""}})
    mod.issues_cache[ISSUE] = {"id": ISSUE, "identifier": "LOC-1", "title": "t", "description": "", "labels": [],
                               "state": "Todo"}
    assert client.patch(f"/api/linear/issues/{ISSUE}", json={"state_name": "In Progress"}).status_code == 200
    assert seen == [True] and not pj.card_busy(None, None, ISSUE)  # reserved by the route, held by the run (UI3-01)


def test_closure_audit_is_history_only(harness, monkeypatch):
    app_mod, mod, client, log, events, tmp = harness
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": "B"})
    task_state = json.loads(app_mod.STATE_TASK_STATE.read_text()) if app_mod.STATE_TASK_STATE.exists() else {}
    app_mod.record_interactive_ended("a", "A-older")
    after = json.loads(app_mod.STATE_TASK_STATE.read_text()) if app_mod.STATE_TASK_STATE.exists() else {}
    assert after == task_state  # no task/job state materialized (UI3-02)
    assert app_mod._get_task_agent_lock("T")["agent_session_id"] == "B"  # never the audit's session


def test_natural_exit_frees_the_card_and_records_once(harness, monkeypatch):
    app_mod, mod, client, log, events, tmp = harness
    import projects as pj
    import runner.modules.pty as pty_mod
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID})
    t = pty_mod.Terminal(term_id="t1", kind="resume", run_id="a", session_id=SID, agent="claude")
    t.holds.enter_context(pj.card_lock(ISSUE))
    sio = type("S", (), {"emit": lambda *a, **k: None})()
    pty_mod._reader(t, sio)  # fd None: the reader ends at once, as when the shell exits (UI3-03)
    assert not pj.card_busy(None, None, ISSUE)
    pty_mod.TERMINALS["t1"] = t
    assert pty_mod.close_terminal("t1")["run_id"] is None  # a later close does nothing more, no second prompt (FB-05)
    assert len([r for r in records(log) if r.get("interactive_ended")]) == 1


def test_closure_under_maintenance_writes_nothing(harness, monkeypatch):
    app_mod, mod, client, log, events, tmp = harness
    import projects as pj
    import runner.modules.pty as pty_mod
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID})
    before = log.read_text()
    t = pty_mod.Terminal(term_id="t2", kind="resume", run_id="a", session_id=SID, agent="claude")
    t.holds.enter_context(pj.card_lock(ISSUE))
    app_mod._MAINTENANCE.set()
    try:
        pty_mod._finalize(t)
    finally:
        app_mod._MAINTENANCE.clear()
    assert log.read_text() == before and not pj.card_busy(None, None, ISSUE)  # UI3-08: no write, lock freed


def test_entrypoint_retry_streams_plain_text(harness, monkeypatch):
    app_mod, mod, client, log, events, tmp = harness
    monkeypatch.setattr(app_mod, "_load_registry", lambda agent: {"sk": {"schedule_eligible": True, "entrypoint": "x"}})
    streams = []
    monkeypatch.setattr(app_mod, "run_agent_process", lambda rid, cmd, **kw: (streams.append(kw["stream"]), ("o", None, None, None, None, "", True))[1])
    write_log(log, {"run_id": "a", "skill": "sk", "agent": "claude", "status": "review"})
    client.post("/api/runs/a/retry", json={})
    assert streams == ["text"]  # run_skill.py output is plain lines for every agent (UI3-04)


def test_panel_close_prompts_even_when_the_reader_finalizes_first(harness, monkeypatch):
    app_mod, mod, client, log, events, tmp = harness
    import runner.modules.pty as pty_mod
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID})
    t = pty_mod.Terminal(term_id="t3", kind="resume", run_id="a", session_id=SID, agent="claude")
    monkeypatch.setitem(pty_mod.TERMINALS, "t3", t)
    sio = type("S", (), {"emit": lambda *a, **k: None})()
    # killing the shell wakes the reader, which ends while close_terminal is still waiting (FB2-01)
    monkeypatch.setattr(pty_mod, "_kill_session", lambda term: pty_mod._reader(term, sio))
    assert pty_mod.close_terminal("t3")["run_id"] == "a"
    assert len([r for r in records(log) if r.get("interactive_ended")]) == 1


def test_a_refused_project_retry_releases_its_session_claim(harness, monkeypatch):
    app_mod, mod, client, log, events, tmp = harness
    app_mod._SESSION_CLAIMS["r9"] = ("claude", SID)
    app_mod._MAINTENANCE.set()
    try:
        app_mod._run_project_ticket(project_key="demo", ident="T-1", agent="claude", prompt="p", title="t",
                                    run_id="r9", linear_issue_id=None, task_id="r9", launch_gen=0)
    finally:
        app_mod._MAINTENANCE.clear()
    assert "r9" not in app_mod._SESSION_CLAIMS  # FB2-02


def test_fallback_session_replaces_the_failed_resume(harness):
    app_mod, mod, client, log, events, tmp = harness
    app_mod._running_jobs["f"] = {"run_id": "f", "agent": "claude"}
    app_mod._publish_run_line("f", "claude", json.dumps({"type": "system", "session_id": "A"}))
    app_mod._publish_run_line("f", "claude", json.dumps({"type": "system", "session_id": "B"}))
    assert app_mod._running_jobs["f"]["agent_session_id"] == "B"  # FB2-03


def test_timeout_record_keeps_the_announced_session(harness, monkeypatch):
    app_mod, mod, client, log, events, tmp = harness
    import subprocess

    def engine(rid, cmd, **kw):
        app_mod._publish_run_line(rid, "claude", json.dumps({"type": "system", "session_id": "live-1"}))
        raise subprocess.TimeoutExpired(cmd, 1)
    monkeypatch.setattr(app_mod, "run_agent_process", engine)
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review"})
    rid = client.post("/api/runs/a/retry", json={}).get_json()["run_id"]
    (rec,) = [r for r in records(log) if r["run_id"] == rid]
    assert rec["status"] == "timeout" and rec["agent_session_id"] == "live-1"  # REV-02


def test_resume_must_match_the_runs_session(harness, monkeypatch):
    app_mod, mod, client, log, events, tmp = harness
    import runner.modules.pty as pty_mod
    monkeypatch.setattr(pty_mod, "TERMINALS", {})
    monkeypatch.setattr(pty_mod, "_spawn", lambda t, argv, env, cols, rows, sio: setattr(t, "pid", 1))
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID})
    out = pty_mod.open_terminal({"kind": "resume", "agent": "claude", "session_id": "other", "run_id": "a"}, None)
    assert "does not belong" in out["error"] and not pty_mod.TERMINALS  # REV-04


def test_run_bound_resume_takes_project_and_ticket_from_the_record(harness, monkeypatch):
    app_mod, mod, client, log, events, tmp = harness
    import runner.modules.pty as pty_mod
    monkeypatch.setattr(pty_mod, "TERMINALS", {})
    monkeypatch.setattr(pty_mod, "_spawn", lambda t, argv, env, cols, rows, sio: setattr(t, "pid", 1))
    write_log(log, {"run_id": "p", "agent": "claude", "status": "review", "agent_session_id": SID,
                    "project_key": "secret-proj", "issue_identifier": "T-1"})
    # the request leaves the project out: the record's project still applies (here: not registered → refused)
    out = pty_mod.open_terminal({"kind": "resume", "agent": "claude", "session_id": SID, "run_id": "p"}, None)
    assert "error" in out and "secret-proj" in out["error"] and not pty_mod.TERMINALS  # UI8-01
    out = pty_mod.open_terminal({"kind": "resume", "agent": "claude", "session_id": SID, "run_id": "p",
                                 "project_key": "other"}, None)
    assert "another project" in out["error"]


def test_history_of_a_running_attempt_includes_its_chain(harness):
    app_mod, mod, client, log, events, tmp = harness
    write_log(log, {"run_id": "r1", "agent": "claude", "status": "review", "linear_issue_id": None, "task_id": "t-R"})
    app_mod._running_jobs["r2"] = {"run_id": "r2", "started_at": "z", "prompt": "p", "agent": "claude",
                                   "record": {"parent_run_id": "r1", "task_id": "t-R", "attempt": 1}}
    chain = client.get("/api/runs/r2/history").get_json()
    assert [r["run_id"] for r in chain] == ["r1", "r2"] and chain[-1]["status"] == "running"  # UI8-05


def test_explicit_run_without_a_recorded_session_cannot_resume(harness, monkeypatch):
    app_mod, mod, client, log, events, tmp = harness
    import runner.modules.pty as pty_mod
    monkeypatch.setattr(pty_mod, "TERMINALS", {})
    monkeypatch.setattr(pty_mod, "_spawn", lambda t, argv, env, cols, rows, sio: setattr(t, "pid", 1))
    write_log(log, {"run_id": "e", "agent": "claude", "status": "review"})  # an entrypoint run: no session
    out = pty_mod.open_terminal({"kind": "resume", "agent": "claude", "session_id": "someone-elses", "run_id": "e"}, None)
    assert "does not belong" in out["error"] and not pty_mod.TERMINALS  # IR9-01


def test_strict_reply_to_an_older_attempt_is_refused(harness, monkeypatch):
    app_mod, mod, client, log, events, tmp = harness
    write_log(log, {"run_id": "a1", "agent": "claude", "status": "review", "agent_session_id": "S1"},
              {"run_id": "a2", "agent": "claude", "status": "review", "agent_session_id": "S2",
               "attempt": 1, "parent_run_id": "a1"})
    procs = stub_launches(app_mod, monkeypatch, [{}])
    before = log.read_text()
    r = client.post("/api/runs/a1/retry", json={"reply": "x", "strict": True})
    assert r.status_code == 409 and "latest" in r.get_json()["error"] and procs == []  # UI11-02
    assert log.read_text() == before


def test_history_of_an_older_dashboard_attempt_shows_the_later_ones(harness):
    app_mod, mod, client, log, events, tmp = harness
    write_log(log, {"run_id": "A", "agent": "claude", "status": "review", "linear_issue_id": None, "task_id": "A",
                    "started_at": "1"},
              {"run_id": "B", "agent": "claude", "status": "review", "linear_issue_id": None, "task_id": "A",
               "parent_run_id": "A", "attempt": 1, "started_at": "2"})
    assert [r["run_id"] for r in client.get("/api/runs/A/history").get_json()] == ["A", "B"]  # UI12-02


def test_resume_of_a_session_a_headless_run_is_in_is_refused(harness, monkeypatch):
    app_mod, mod, client, log, events, tmp = harness
    import runner.modules.pty as pty_mod
    monkeypatch.setattr(pty_mod, "TERMINALS", {})
    monkeypatch.setattr(pty_mod, "_spawn", lambda t, argv, env, cols, rows, sio: setattr(t, "pid", 1))
    app_mod._running_jobs["live"] = {"run_id": "live", "agent": "codex", "agent_session_id": "cx-live"}
    out = pty_mod.open_terminal({"kind": "resume", "agent": "codex", "session_id": "cx-live"}, None)
    assert "running right now" in out["error"] and not pty_mod.TERMINALS  # UI14-01


def test_issue_history_includes_a_running_attempt(harness):
    app_mod, mod, client, log, events, tmp = harness
    write_log(log, {"run_id": "A", "agent": "claude", "status": "review", "started_at": "1"})
    app_mod._running_jobs["B"] = {"run_id": "B", "started_at": "2", "linear_issue_id": ISSUE, "agent": "claude",
                                  "record": {"parent_run_id": "A", "task_id": "T", "attempt": 1}}
    for ref in (f"linear-{ISSUE}", "A"):  # the virtual card and an older attempt both see B (UI15-02)
        assert [r["run_id"] for r in client.get(f"/api/runs/{ref}/history").get_json()] == ["A", "B"]


def test_latest_run_per_issue_beyond_the_recent_window(harness):
    app_mod, mod, client, log, events, tmp = harness
    write_log(log, {"run_id": "old", "agent": "claude", "status": "review", "agent_session_id": SID})
    write_log(log, *({"run_id": f"n{i}", "agent": "claude", "status": "review", "linear_issue_id": f"other-{i}"} for i in range(90)))
    app_mod._runs_cache.clear()
    assert ISSUE not in {r.get("linear_issue_id") for r in client.get("/api/runs?limit=80").get_json()}
    latest = client.get("/api/runs/latest-by-issue").get_json()
    assert latest[ISSUE]["run_id"] == "old" and latest[ISSUE]["agent_session_id"] == SID  # REV23-01


def test_timed_out_linear_dispatch_stays_resumable(harness, monkeypatch):
    app_mod, mod, client, log, events, tmp = harness
    import subprocess

    def engine(rid, cmd, **kw):
        app_mod._publish_run_line(rid, "claude", json.dumps({"type": "system", "session_id": "lin-sess"}))
        raise subprocess.TimeoutExpired(cmd, 1)
    real_engine = app_mod.run_agent_process
    monkeypatch.setattr(app_mod, "run_agent_process", engine)
    monkeypatch.setattr(app_mod, "_run_grouped", lambda *a, **k: type("R", (), {"stdout": ""})())
    mod._dispatch_issue({"id": ISSUE, "identifier": "LOC-1", "title": "t", "description": "", "labels": []},
                        {"agent": {"backend": "claude"}}, app_mod.socketio)
    rec = records(log)[-1]
    assert rec["status"] == "timeout" and rec["task_id"] == rec["run_id"]  # FB5-01
    assert app_mod._get_task_agent_lock(rec["task_id"])["agent_session_id"] == "lin-sess"
    monkeypatch.setattr(app_mod, "run_agent_process", real_engine)
    on_disk(app_mod, "claude", "lin-sess")
    monkeypatch.setattr(app_mod, "_process_table", lambda: {})
    procs = stub_launches(app_mod, monkeypatch, [{}])
    assert client.post(f"/api/runs/{rec['run_id']}/retry", json={"reply": "go", "strict": True}).status_code == 200
    assert "--resume" in procs[0].args and "lin-sess" in procs[0].args


def test_older_review_card_keeps_its_waiting_badge(harness):
    app_mod, mod, client, log, events, tmp = harness
    write_log(log, {"run_id": "old", "agent": "claude", "status": "review", "output": "Plan ready.\nShall I build it?"})
    latest = client.get("/api/runs/latest-by-issue").get_json()
    assert latest[ISSUE]["waiting"] == "Plan ready."  # REV31-02


# ── Ending a card's interactive session (plan 2026-10-17-card-interactive-session-close) ──

def _live_term(pty_mod, monkeypatch, term_id="live1", **kw):
    t = pty_mod.Terminal(term_id=term_id, kind="resume", pid=1, alive=True, **kw)
    monkeypatch.setitem(pty_mod.TERMINALS, term_id, t)
    return t


def test_card_bound_resume_ends_with_its_agent_and_unbound_keeps_a_shell(harness, monkeypatch):
    app_mod, mod, client, log, events, tmp = harness
    import runner.modules.pty as pty_mod
    monkeypatch.setattr(pty_mod, "TERMINALS", {})
    argvs = []
    monkeypatch.setattr(pty_mod, "_spawn", lambda t, argv, env, cols, rows, sio: (argvs.append(argv), setattr(t, "pid", None)))
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID})
    bound = pty_mod.open_terminal({"kind": "resume", "agent": "claude", "session_id": SID, "in_panel": False,
                                   "run_id": "a"}, None)
    assert "error" not in bound
    assert argvs[-1][-1] == f"claude --resume {SID}"  # no "; exec $SHELL -l": the card unlocks on /exit (AC1)
    unbound = pty_mod.open_terminal({"kind": "resume", "agent": "claude", "session_id": "not-a-card"}, None)
    assert "error" not in unbound and "; exec " in argvs[-1][-1]


def test_card_terminal_matches_card_ticket_or_session_and_only_live_ones(harness, monkeypatch):
    import runner.modules.pty as pty_mod
    monkeypatch.setattr(pty_mod, "TERMINALS", {})
    _live_term(pty_mod, monkeypatch, "c", card_key="K1")
    _live_term(pty_mod, monkeypatch, "t", project_key="demo", ticket="T-1")
    _live_term(pty_mod, monkeypatch, "s", agent="claude", session_id="S1")
    dead = _live_term(pty_mod, monkeypatch, "d", card_key="K2")
    dead.alive = False
    assert pty_mod.card_terminal(card_key="K1") == "c"
    assert pty_mod.card_terminal(project_key="demo", ticket="T-1") == "t"
    assert pty_mod.card_terminal(agent="claude", session_id="S1") == "s"
    assert pty_mod.card_terminal(card_key="K2") is None and pty_mod.card_terminal(card_key="nope") is None
    assert pty_mod.card_interactive({"error": "x"}, card_key="nope") == {"error": "x"}  # unchanged when nothing holds it


@pytest.mark.parametrize("card", ["linear", "run"])
def test_retry_refusal_names_the_holding_terminal_only_when_one_holds_it(harness, monkeypatch, card):
    app_mod, mod, client, log, events, tmp = harness
    import projects as pj
    import runner.modules.pty as pty_mod
    monkeypatch.setattr(pty_mod, "TERMINALS", {})
    if card == "linear":
        write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID})
        key = ISSUE
    else:
        write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID,
                        "linear_issue_id": None, "task_id": "task-1"})
        key = "task-1"
    stub_launches(app_mod, monkeypatch, [{}])
    with pj.card_lock(key):  # held by a running attempt: no terminal to offer (AC2, last sentence)
        body = client.post("/api/runs/a/retry", json={}).get_json()
        assert "code" not in body and "term_id" not in body
        _live_term(pty_mod, monkeypatch, card_key=key)  # now the card's interactive terminal holds it
        r = client.post("/api/runs/a/retry", json={"reply": "x", "strict": True})
        assert r.status_code == 409 and r.get_json()["code"] == "card_interactive" and r.get_json()["term_id"] == "live1"


def test_tracker_and_local_patch_refusals_name_the_holding_terminal(harness, monkeypatch):
    app_mod, mod, client, log, events, tmp = harness
    import projects as pj
    import runner.modules.pty as pty_mod
    monkeypatch.setattr(pty_mod, "TERMINALS", {})
    with pj.card_lock(ISSUE):
        _live_term(pty_mod, monkeypatch, card_key=ISSUE)
        for url in (f"/api/linear/issues/local/{ISSUE}", f"/api/linear/issues/{ISSUE}"):
            r = client.patch(url, json={"state_name": "In Progress"})
            assert r.status_code == 409, url
            assert r.get_json()["code"] == "card_interactive" and r.get_json()["term_id"] == "live1", url
    assert tracker_state(tmp) == "In Review"  # the refused local write wrote nothing


def test_failed_close_then_exit_frees_the_card_once(harness, monkeypatch):
    app_mod, mod, client, log, events, tmp = harness
    import projects as pj
    import runner.modules.pty as pty_mod
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID})
    t = pty_mod.Terminal(term_id="f1", kind="resume", run_id="a", session_id=SID, agent="claude", pid=1)
    t.holds.enter_context(pj.card_lock(ISSUE))
    monkeypatch.setitem(pty_mod.TERMINALS, "f1", t)
    def boom(term):
        raise RuntimeError("ps failed")
    monkeypatch.setattr(pty_mod, "_kill_session", boom)
    out = pty_mod.close_terminal("f1")
    assert out["error"].startswith("cleanup failed") and pj.card_busy(None, None, ISSUE)  # still running: still held
    sio = type("S", (), {"emit": lambda *a, **k: None})()
    pty_mod._reader(t, sio)  # then the agent exits on its own, but its session still cannot be enumerated:
    assert t.cleanup_failed and pj.card_busy(None, None, ISSUE)  # leftovers unproven gone: still held (ICS-25/27)
    assert not pty_mod._finalize_lock.locked()
    monkeypatch.setattr(pty_mod, "_kill_session", lambda term: None)  # enumeration works again
    assert pty_mod.close_terminal("f1").get("ok")  # End session retried
    assert not pj.card_busy(None, None, ISSUE)
    assert len([r for r in records(log) if r.get("interactive_ended")]) == 1
    assert not pty_mod._finalize_lock.locked()


def test_exit_during_a_failed_close_frees_the_card_once_without_deadlock(harness, monkeypatch):
    import threading
    app_mod, mod, client, log, events, tmp = harness
    import projects as pj
    import runner.modules.pty as pty_mod
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID})
    t = pty_mod.Terminal(term_id="f2", kind="resume", run_id="a", session_id=SID, agent="claude", pid=1)
    t.holds.enter_context(pj.card_lock(ISSUE))
    monkeypatch.setitem(pty_mod.TERMINALS, "f2", t)
    sio = type("S", (), {"emit": lambda *a, **k: None})()
    def exits_then_fails(term):
        pty_mod._reader(term, sio)  # the reader ends while closing: it leaves finalizing to close
        raise RuntimeError("ps failed")
    monkeypatch.setattr(pty_mod, "_kill_session", exits_then_fails)
    result = {}
    th = threading.Thread(target=lambda: result.update(pty_mod.close_terminal("f2")), daemon=True)
    th.start()
    th.join(5)
    assert not th.is_alive(), "close_terminal deadlocked"
    assert result["error"].startswith("cleanup failed") and not pty_mod._finalize_lock.locked()
    # the agent is gone but its session's leftovers are unverified: ownership stays, visibly (ICS-29)
    assert pj.card_busy(None, None, ISSUE) and pty_mod.card_terminal(agent="claude", session_id=SID) == "f2"
    monkeypatch.setattr(pty_mod, "_kill_session", lambda term: None)  # End session retried, cleanup works
    assert pty_mod.close_terminal("f2").get("ok")
    assert not pj.card_busy(None, None, ISSUE)
    assert len([r for r in records(log) if r.get("interactive_ended")]) == 1


def test_card_session_ends_when_its_agent_exits_despite_a_process_holding_the_pty(harness, monkeypatch):
    """The agent exits but a background child keeps the PTY open (no EOF): the card is still freed,
    the closure audited once, and the leftover child ended (AC1, ICS-22)."""
    import os
    import time
    app_mod, mod, client, log, events, tmp = harness
    import projects as pj
    import runner.modules.pty as pty_mod
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID})
    t = pty_mod.Terminal(term_id="bg1", kind="resume", run_id="a", session_id=SID, agent="claude", cwd=str(tmp))
    t.holds.enter_context(pj.card_lock(ISSUE))
    exits = []
    sio = type("S", (), {"emit": lambda self, ev, data, **k: exits.append(ev) if ev == "term_exit" else None})()
    pidfile = tmp / "bg.pid"
    pty_mod._spawn(t, ["/bin/sh", "-c", f"sleep 30 & echo $! > {pidfile}; exit 0"], dict(os.environ), 80, 24, sio)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and ("term_exit" not in exits or pj.card_busy(None, None, ISSUE)):
        time.sleep(0.1)
    assert "term_exit" in exits and not t.alive and t.exit_code == 0
    assert not pj.card_busy(None, None, ISSUE)
    assert len([r for r in records(log) if r.get("interactive_ended")]) == 1
    bg = int(pidfile.read_text())
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.kill(bg, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        os.kill(bg, 9)
        raise AssertionError("the leftover background process outlived its agent")


def test_card_session_ends_when_its_agent_exits_despite_a_chatty_leftover(harness, monkeypatch):
    """A leftover keeps writing to the PTY every 100 ms: the agent's exit is still seen (ICS-24)."""
    import os
    import time
    app_mod, mod, client, log, events, tmp = harness
    import projects as pj
    import runner.modules.pty as pty_mod
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID})
    t = pty_mod.Terminal(term_id="bg2", kind="resume", run_id="a", session_id=SID, agent="claude", cwd=str(tmp))
    t.holds.enter_context(pj.card_lock(ISSUE))
    exits = []
    sio = type("S", (), {"emit": lambda self, ev, data, **k: exits.append(ev) if ev == "term_exit" else None})()
    pty_mod._spawn(t, ["/bin/sh", "-c", "(while :; do echo tick; sleep 0.1; done) & exit 0"], dict(os.environ), 80, 24, sio)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and "term_exit" not in exits:
        time.sleep(0.1)
    assert "term_exit" in exits and not pj.card_busy(None, None, ISSUE)


def test_failed_leftover_cleanup_keeps_the_card_held_until_end_session(harness, monkeypatch):
    """Leftovers that cannot be ended keep the terminal live and the card held; End session retries
    the cleanup and then frees it (ICS-25)."""
    import os
    import time
    app_mod, mod, client, log, events, tmp = harness
    import projects as pj
    import runner.modules.pty as pty_mod
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID})
    t = pty_mod.Terminal(term_id="bg3", kind="resume", run_id="a", session_id=SID, agent="claude", cwd=str(tmp))
    t.holds.enter_context(pj.card_lock(ISSUE))
    monkeypatch.setitem(pty_mod.TERMINALS, "bg3", t)
    real_kill = pty_mod._kill_session
    def failing(term):
        raise RuntimeError("ps failed")
    monkeypatch.setattr(pty_mod, "_kill_session", failing)
    sio = type("S", (), {"emit": lambda *a, **k: None})()
    pty_mod._spawn(t, ["/bin/sh", "-c", "sleep 30 & exit 0"], dict(os.environ), 80, 24, sio)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not t.cleanup_failed:
        time.sleep(0.1)
    assert t.cleanup_failed and t.alive and pj.card_busy(None, None, ISSUE)
    monkeypatch.setattr(pty_mod, "_kill_session", real_kill)
    out = pty_mod.close_terminal("bg3")
    assert out.get("ok") and not pj.card_busy(None, None, ISSUE)
    assert len([r for r in records(log) if r.get("interactive_ended")]) == 1


def test_eof_never_proves_a_card_sessions_leftovers_are_gone(harness, monkeypatch):
    """The agent exits leaving a HUP-ignoring worker with redirected stdio: the PTY reaches EOF at
    once, yet the worker is still ended before the card is freed (ICS-27)."""
    import os
    import time
    app_mod, mod, client, log, events, tmp = harness
    import projects as pj
    import runner.modules.pty as pty_mod
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID})
    t = pty_mod.Terminal(term_id="bg4", kind="resume", run_id="a", session_id=SID, agent="claude", cwd=str(tmp))
    t.holds.enter_context(pj.card_lock(ISSUE))
    exits = []
    sio = type("S", (), {"emit": lambda self, ev, data, **k: exits.append(ev) if ev == "term_exit" else None})()
    pidfile = tmp / "worker.pid"
    script = f"(trap '' HUP; exec sleep 30) </dev/null >/dev/null 2>&1 & echo $! > {pidfile}; exit 0"
    pty_mod._spawn(t, ["/bin/sh", "-c", script], dict(os.environ), 80, 24, sio)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and "term_exit" not in exits:
        time.sleep(0.05)
    assert "term_exit" in exits and not pj.card_busy(None, None, ISSUE)
    worker = int(pidfile.read_text())
    try:
        os.kill(worker, 0)
    except ProcessLookupError:
        pass
    else:
        os.kill(worker, 9)
        raise AssertionError("the worker outlived its card session")


def test_a_reader_ending_during_a_close_leaves_the_end_to_the_close(harness, monkeypatch):
    """The reader ends while a close is in progress and that close then fails: the terminal is not
    marked dead or finalized by anyone — it stays live, held and matched — and a retried close
    ends it once (ICS-31/32/33)."""
    app_mod, mod, client, log, events, tmp = harness
    import projects as pj
    import runner.modules.pty as pty_mod
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID})
    t = pty_mod.Terminal(term_id="r1", kind="resume", run_id="a", session_id=SID, agent="claude", pid=1)
    t.holds.enter_context(pj.card_lock(ISSUE))
    monkeypatch.setitem(pty_mod.TERMINALS, "r1", t)
    sio = type("S", (), {"emit": lambda *a, **k: None})()
    t.closing = True                    # a close has begun ...
    pty_mod._reader(t, sio)             # ... the reader ends meanwhile and steps aside
    assert t.alive and not t.finalized and pj.card_busy(None, None, ISSUE)
    monkeypatch.setattr(pty_mod, "_kill_session", lambda term: (_ for _ in ()).throw(RuntimeError("ps failed")))
    t.closing = False
    assert pty_mod.close_terminal("r1")["error"].startswith("cleanup failed")
    assert t.alive and pj.card_busy(None, None, ISSUE) and pty_mod.card_terminal(card_key=None, agent="claude", session_id=SID) == "r1"
    assert ("claude", SID) in app_mod._live_session_ids()  # session actions and renames stay blocked
    monkeypatch.setattr(pty_mod, "_kill_session", lambda term: setattr(term, "alive", False))
    assert pty_mod.close_terminal("r1").get("ok") and not pj.card_busy(None, None, ISSUE)
    assert len([r for r in records(log) if r.get("interactive_ended")]) == 1


def test_finalized_terminal_never_holds_and_superseded_close_says_so(harness, monkeypatch):
    """A terminal finalized after a failed-then-successful cleanup no longer matches as the card's
    holder (ICS-35); a close made for an action announces itself as superseded to every viewer (ICS-37)."""
    app_mod, mod, client, log, events, tmp = harness
    import projects as pj
    import runner.modules.pty as pty_mod
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID})
    t = pty_mod.Terminal(term_id="s1", kind="resume", run_id="a", session_id=SID, agent="claude", pid=1, card_key=ISSUE)
    t.holds.enter_context(pj.card_lock(ISSUE))
    monkeypatch.setitem(pty_mod.TERMINALS, "s1", t)
    monkeypatch.setattr(pty_mod, "_kill_session", lambda term: (_ for _ in ()).throw(RuntimeError("ps failed")))
    assert pty_mod.close_terminal("s1")["error"].startswith("cleanup failed") and t.cleanup_failed
    monkeypatch.setattr(pty_mod, "_kill_session", lambda term: setattr(term, "alive", False))
    sio = type("S", (), {"emit": lambda *a, **k: None})()
    pty_mod._reader(t, sio)  # the agent then exits and the reader's own cleanup succeeds
    assert t.finalized and not t.cleanup_failed and pty_mod.card_terminal(card_key=ISSUE) is None
    emitted = []
    monkeypatch.setattr(pty_mod, "_SOCKETIO", type("S", (), {"emit": lambda self, ev, data, **k: emitted.append((ev, data))})())
    t2 = pty_mod.Terminal(term_id="s2", kind="shell", pid=None)
    monkeypatch.setitem(pty_mod.TERMINALS, "s2", t2)
    pty_mod.close_terminal("s2", superseded=True)
    assert ("term_exit", {"term_id": "s2", "exit_code": None, "superseded": True}) in emitted


def test_a_gone_terminal_says_how_it_ended_and_cleanups_never_overlap(harness, monkeypatch):
    """A close that finds the terminal gone gets its end record (superseded or not), so a viewer that
    missed the exit offers no obsolete choice (ICS-41); two cleanups of one terminal run one at a time
    and close its descriptor once (ICS-40)."""
    import threading
    import time
    app_mod, mod, client, log, events, tmp = harness
    import runner.modules.pty as pty_mod
    monkeypatch.setattr(pty_mod, "ENDED", {})
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID})
    t = pty_mod.Terminal(term_id="e1", kind="resume", run_id="a", session_id=SID, agent="claude", pid=None)
    monkeypatch.setitem(pty_mod.TERMINALS, "e1", t)
    assert pty_mod.close_terminal("e1", superseded=True).get("ok")
    assert pty_mod.close_terminal("e1") == {"error": "unknown terminal", "ended": {"run_id": "a", "superseded": True}}
    assert pty_mod.close_terminal("never") == {"error": "unknown terminal"}
    # serialized cleanup: the second caller waits for the first and finds the descriptor already closed
    inside, overlaps = [], []
    def slow(term):
        overlaps.append(len(inside)); inside.append(1); time.sleep(0.2); inside.pop()
    monkeypatch.setattr(pty_mod, "_kill_session_locked", slow)
    t2 = pty_mod.Terminal(term_id="e2", kind="shell", pid=None)
    ths = [threading.Thread(target=pty_mod._kill_session, args=(t2,)) for _ in range(2)]
    [th.start() for th in ths]; [th.join(2) for th in ths]
    assert overlaps == [0, 0]


def test_a_failed_superseding_close_withdraws_its_intent(harness, monkeypatch):
    """An action's close fails: the session is not marked superseded, so its later natural end still
    offers the choice; a successful one says superseded in its acknowledgement (ICS-43/44)."""
    app_mod, mod, client, log, events, tmp = harness
    import runner.modules.pty as pty_mod
    t = pty_mod.Terminal(term_id="w1", kind="shell", pid=None)
    monkeypatch.setitem(pty_mod.TERMINALS, "w1", t)
    monkeypatch.setattr(pty_mod, "_kill_session", lambda term: (_ for _ in ()).throw(RuntimeError("ps failed")))
    assert pty_mod.close_terminal("w1", superseded=True)["error"].startswith("cleanup failed")
    assert t.superseded is False
    monkeypatch.setattr(pty_mod, "_kill_session", lambda term: setattr(term, "alive", False))
    assert pty_mod.close_terminal("w1", superseded=True)["superseded"] is True


def test_overlapping_superseding_closes_keep_the_successful_ones_intent(harness, monkeypatch):
    """Two action closes overlap; the first fails, the second succeeds: the end is superseded in the
    acknowledgement, the exit event and the end record (ICS-45)."""
    app_mod, mod, client, log, events, tmp = harness
    import runner.modules.pty as pty_mod
    monkeypatch.setattr(pty_mod, "ENDED", {})
    emitted = []
    monkeypatch.setattr(pty_mod, "_SOCKETIO", type("S", (), {"emit": lambda self, ev, data, **k: emitted.append((ev, data))})())
    t = pty_mod.Terminal(term_id="o1", kind="shell", pid=None)
    monkeypatch.setitem(pty_mod.TERMINALS, "o1", t)
    t.superseding += 1  # request B registered its intent and waits for the cleanup lock
    monkeypatch.setattr(pty_mod, "_kill_session", lambda term: (_ for _ in ()).throw(RuntimeError("ps failed")))
    assert pty_mod.close_terminal("o1", superseded=True)["error"].startswith("cleanup failed")  # request A fails
    assert t.superseded  # A withdrew only its own intent; B's stands
    monkeypatch.setattr(pty_mod, "_kill_session", lambda term: setattr(term, "alive", False))
    ack = pty_mod.close_terminal("o1")  # B's cleanup now runs and succeeds (its intent is already counted)
    assert ack["superseded"] is True and pty_mod.ENDED["o1"]["superseded"] is True
    assert any(ev == "term_exit" and d["superseded"] is True for ev, d in emitted)


def test_a_waiting_close_reuses_the_readers_confirmed_cleanup(harness, monkeypatch):
    """The reader's cleanup succeeded first; a superseding close waiting on it does not repeat (and so
    cannot fail) the cleanup: it succeeds and the end is announced superseded once (ICS-48)."""
    app_mod, mod, client, log, events, tmp = harness
    import runner.modules.pty as pty_mod
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID})
    t = pty_mod.Terminal(term_id="c1", kind="resume", run_id="a", session_id=SID, agent="claude", pid=None)
    monkeypatch.setitem(pty_mod.TERMINALS, "c1", t)
    t.cleaned = True  # as left by the reader's successful cleanup
    monkeypatch.setattr(pty_mod, "_kill_session", lambda term: (_ for _ in ()).throw(RuntimeError("ps failed")))
    ack = pty_mod.close_terminal("c1", superseded=True)
    assert ack.get("ok") and ack["superseded"] is True
