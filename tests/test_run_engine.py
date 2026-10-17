"""One process engine (C0) and the live/replayed run view (C) of the dashboard UI plan.
Fake agent CLIs only."""

import json
import sys
import textwrap
import time
from pathlib import Path

import pytest

RUNNER = Path(__file__).resolve().parents[1] / "runner"
sys.path.insert(0, str(RUNNER))
sys.path.insert(0, str(RUNNER.parent))

import project_runs as pr  # noqa: E402
from test_reset_gen import ISSUE, SID, env, write_log  # noqa: E402,F401  (env: fixture)

FAKE_CLI = textwrap.dedent('''
    import json, sys, time
    agent, mode = sys.argv[1], sys.argv[2]
    def out(ev): print(json.dumps(ev), flush=True)
    if agent == "claude":
        out({"type": "system", "subtype": "init", "session_id": "cs-1"})
        out({"type": "assistant", "message": {"content": [{"type": "text", "text": "working"},
             {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}]}})
        time.sleep(0.6)
        out({"type": "result", "result": "done", "session_id": "cs-1", "usage": {"input_tokens": 1, "output_tokens": 2}})
    elif agent == "codex":
        out({"type": "thread.started", "thread_id": "cx-1"})
        out({"type": "item.completed", "item": {"type": "agent_message", "text": "working"}})
        time.sleep(0.6)
        out({"type": "item.completed", "item": {"type": "agent_message", "text": "done"}})
        out({"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 2}})
    elif agent == "slowerr":  # complains on stderr, then hangs past the deadline
        print("warning: retrying upstream", file=sys.stderr, flush=True); time.sleep(30)
    elif agent == "interleaved":  # stdout, then a stderr warning, then more stdout
        out({"type": "assistant", "message": {"content": [{"type": "text", "text": "starting"}]}})
        time.sleep(0.3)
        print("temporary failure", file=sys.stderr, flush=True)
        time.sleep(0.3)
        out({"type": "assistant", "message": {"content": [{"type": "text", "text": "recovered"}]}})
    elif agent == "errquiet":  # only stderr activity for a while, stdout silent
        for _ in range(4):
            print("still working", file=sys.stderr, flush=True); time.sleep(0.3)
    elif agent == "failing":  # reports its failure on stderr only
        print("Error: not logged in", file=sys.stderr); sys.exit(1)
    elif agent == "noisy":  # a CLI that floods stderr before it closes stdout
        sys.stderr.write("w" * 300000); sys.stderr.flush()
        out({"type": "result", "result": "done", "session_id": "n-1"})
    else:
        print("plain line", flush=True)
    sys.exit(1 if mode == "fail" else 0)
''')


# ── renderer ─────────────────────────────────────────────────────────────────

def plain(lines):
    import re
    return [re.sub(r"\x1b\[[0-9;]*m", "", ln) for ln in lines]


def test_renderer_turns_each_format_into_terminal_lines():
    r = pr.render_event
    claude_asst = json.dumps({"type": "assistant", "message": {"content": [
        {"type": "text", "text": "hi"}, {"type": "tool_use", "name": "Read", "input": {"file_path": "a"}}]}})
    assert plain(r("claude", claude_asst)) == ["hi", '[tool] Read {"file_path": "a"}']
    assert r("claude", claude_asst)[1].startswith("\x1b[36m")  # tool calls cyan
    tool_res = json.dumps({"type": "user", "message": {"content": [{"type": "tool_result", "content": "x" * 500}]}})
    out = r("claude", tool_res)
    assert out[0].startswith("\x1b[2m") and len(plain(out)[0]) < 220  # dim and truncated
    err_res = json.dumps({"type": "user", "message": {"content": [{"type": "tool_result", "is_error": True, "content": "boom"}]}})
    assert r("claude", err_res)[0].startswith("\x1b[31m")
    assert plain(r("claude", json.dumps({"type": "result", "is_error": True}))) == ["[result] error: error"]
    assert plain(r("claude", json.dumps({"type": "result", "is_error": True, "result": "API overloaded"}))) \
        == ["[result] error: API overloaded"]
    failed = r("codex", json.dumps({"type": "turn.failed", "error": {"message": "context window exceeded"}}))
    assert plain(failed) == ["[result] error: context window exceeded"] and failed[0].startswith("\x1b[31m")  # REV30-01
    cmd = {"type": "command_execution", "command": "ls", "aggregated_output": "a b", "exit_code": 0}
    assert plain(r("codex", json.dumps({"type": "item.started", "item": cmd}))) == ["[tool] shell ls"]  # while it runs
    assert plain(r("codex", json.dumps({"type": "item.completed", "item": cmd}))) == ["  ↳ a b"]  # no duplicate call line
    assert r("codex", json.dumps({"type": "item.completed", "item": {**cmd, "exit_code": 2}}))[0].startswith("\x1b[31m")
    assert plain(r("dsh", json.dumps({"type": "tool_result", "status": "ok", "result": "found 3"}))) == ["  ↳ [ok] found 3"]
    long = plain(r("claude", json.dumps({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Write", "input": {"content": "x" * 1000}}]}})))[0]
    assert long.endswith("…") and len(long) < 400  # visible truncation
    assert plain(r("codex", json.dumps({"type": "error", "message": "bad"}))) == ["[error] bad"]
    assert plain(r("dsh", json.dumps({"type": "tool_call", "tool": "grep", "input": {}}))) == ["[tool] grep {}"]
    assert r("dsh", json.dumps({"type": "final", "text": "fin"})) == ["fin"]
    err = r("dsh", json.dumps({"type": "error", "message": "session/writer-held"}))
    assert plain(err) == ["[error] session/writer-held"] and err[0].startswith("\x1b[31m")  # UI2-09
    assert r("text", "plain") == ["plain"] and r("text", "  ") == []
    assert r("claude", "not json") == []
    assert pr.session_id_of("codex", json.dumps({"type": "thread.started", "thread_id": "t"})) == "t"
    assert pr.session_id_of("claude", json.dumps({"type": "system", "session_id": "s"})) == "s"


# ── engine through the real launch paths ─────────────────────────────────────

@pytest.fixture
def eng(env, monkeypatch, tmp_path):
    app_mod, mod, client, log, events, tmp = env
    monkeypatch.setattr(app_mod, "_running_jobs", {})
    monkeypatch.setattr(app_mod, "_running_procs", {})
    monkeypatch.setattr(app_mod, "_INFLIGHT", app_mod._INFLIGHT)
    fake = tmp_path / "fake_cli.py"
    fake.write_text(FAKE_CLI)
    mode = {"m": "ok"}

    def cmd(agent, prompt, output_format="json", skill_name=None, registry=None):
        return [sys.executable, str(fake), agent if output_format != "text" else "text", mode["m"]]
    monkeypatch.setattr(app_mod, "_ai_command", cmd)
    monkeypatch.setattr(app_mod, "_build_resume_cmd", lambda agent, sid, prompt: [sys.executable, str(fake), agent, "fail"])
    calls = []
    real = app_mod.run_agent_process

    def spy(run_id, command, **kw):
        calls.append((run_id, kw["stream"]))
        return real(run_id, command, **kw)
    monkeypatch.setattr(app_mod, "run_agent_process", spy)
    stamped = []
    monkeypatch.setattr(app_mod.socketio, "emit", lambda *a, **k: (events.append(a), stamped.append((time.monotonic(), a))))
    pr.RUN_EVENTS.clear()
    return app_mod, mod, client, log, events, tmp, calls, stamped, mode


def records(log):
    return [json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []


def terminal_records(log, rid):
    return [r for r in records(log) if r.get("run_id") == rid]


def live_before_exit(stamped, rid):
    """True when the first run_event for rid came well before the run finished."""
    evs = [t for t, a in stamped if a[0] == "run_event" and a[1]["run_id"] == rid]
    done = [t for t, a in stamped if a[0] == "run_logged" and a[1]["run_id"] == rid]
    return bool(evs and done and evs[0] < done[0] - 0.4)


@pytest.mark.parametrize("agent, sid", [("claude", "cs-1"), ("codex", "cx-1")])
def test_linear_dispatch_streams_live_and_records_the_session(eng, agent, sid):
    app_mod, mod, client, log, events, tmp, calls, stamped, mode = eng
    issue = {"id": ISSUE, "identifier": "LOC-1", "title": "t", "description": "", "labels": []}
    mod._dispatch_issue(issue, {"agent": {"backend": agent}}, app_mod.socketio)
    (rid, stream), = calls
    assert stream == agent and live_before_exit(stamped, rid)
    (rec,) = terminal_records(log, rid)
    assert rec["agent_session_id"] == sid and rec["status"] == "review"
    ev = client.get(f"/api/runs/{rid}/events").get_json()
    assert ev["resume_eligible"] and "working" in plain(ev["lines"])


def test_codex_retry_streams_before_exit(eng):
    app_mod, mod, client, log, events, tmp, calls, stamped, mode = eng
    write_log(log, {"run_id": "a", "agent": "codex", "status": "review"})
    assert client.post("/api/runs/a/retry", json={}).status_code == 200
    (rid, stream), = calls
    assert stream == "codex" and live_before_exit(stamped, rid)
    assert terminal_records(log, rid)[-1]["agent_session_id"] == "cx-1"


def test_every_non_project_launch_goes_through_the_engine_with_one_record(eng, monkeypatch, tmp_path):
    app_mod, mod, client, log, events, tmp, calls, stamped, mode = eng
    # /run agent path
    assert client.post("/run", json={"prompt": "p", "agent": "claude"}).get_json()["ok"]
    # /run entrypoint path
    monkeypatch.setattr(app_mod, "_load_registry", lambda agent: {"sk": {"agents": ["claude"], "schedule_eligible": True,
                                                                        "entrypoint": "x"}})
    monkeypatch.setattr(app_mod, "RUNNER", tmp_path / "fake_cli.py")
    monkeypatch.setattr(app_mod, "_python_path", lambda: sys.executable)
    client.post("/run", json={"prompt": "p", "agent": "claude", "skill": "sk"})
    monkeypatch.setattr(app_mod, "_load_registry", lambda agent: {})
    # retry: a failed resume then the fallback = one run, two processes, one record
    write_log(log, {"run_id": "b", "agent": "claude", "status": "review", "agent_session_id": SID,
                    "linear_issue_id": None})  # a /run card: its resume keeps the fresh fallback (D3 covers tracker cards)
    client.post("/api/runs/b/retry", json={})
    # Linear dispatch
    mod._dispatch_issue({"id": ISSUE, "identifier": "LOC-1", "title": "t", "description": "", "labels": []},
                        {"agent": {"backend": "claude"}}, app_mod.socketio)
    streams = [s for _, s in calls]
    assert streams == ["claude", "text", "claude", "claude", "claude"]
    retry_rid = calls[2][0]
    assert calls[3][0] == retry_rid  # the fallback stays the same run
    for rid in dict.fromkeys(r for r, _ in calls):
        assert len(terminal_records(log, rid)) == 1  # exactly one terminal record per run


def test_replay_after_the_ring_is_gone(eng):
    app_mod, mod, client, log, events, tmp, calls, stamped, mode = eng
    assert client.post("/run", json={"prompt": "p", "agent": "claude"}).get_json()["ok"]
    rid = calls[0][0]
    live = client.get(f"/api/runs/{rid}/events").get_json()["lines"]
    pr.RUN_EVENTS.clear()  # a runner restart
    replay = client.get(f"/api/runs/{rid}/events").get_json()
    assert replay["lines"] == live and "working" in plain(replay["lines"])
    log_path = app_mod._claude_stream_log_path(rid)
    assert json.loads(log_path.read_text().splitlines()[0])["type"] == "system"  # raw contract unchanged
    assert json.loads(app_mod._stream_meta_path(rid).read_text()) == {"format": "claude"}


def test_stderr_flood_does_not_stall_the_reader(eng, tmp_path):
    app_mod, *_ = eng
    app_mod._running_jobs["noisy"] = {"run_id": "noisy"}
    out, *_rest, err, ok = app_mod.run_agent_process(
        "noisy", [sys.executable, str(tmp_path / "fake_cli.py"), "noisy", "ok"], stream="claude", timeout=20)
    assert out == "done" and ok and len(err) == 300000  # both pipes drained together (UI-04)


def test_fallback_keeps_the_failed_attempts_log_and_seq_cursor(eng):
    app_mod, mod, client, log, events, tmp, calls, stamped, mode = eng
    write_log(log, {"run_id": "b", "agent": "claude", "status": "review", "agent_session_id": SID,
                    "linear_issue_id": None})  # a /run card: its resume keeps the fresh fallback (D3 covers tracker cards)
    client.post("/api/runs/b/retry", json={})
    rid = calls[0][0]
    live = client.get(f"/api/runs/{rid}/events").get_json()
    assert live["cursor"] == len(live["lines"]) == pr.RUN_EVENTS[rid].total  # snapshot cursor (UI-13)
    seqs = [a[1]["seq"] for t, a in stamped if a[0] == "run_event" and a[1]["run_id"] == rid]
    assert seqs == list(range(1, len(seqs) + 1))
    pr.RUN_EVENTS.clear()
    replay = client.get(f"/api/runs/{rid}/events").get_json()["lines"]
    assert replay == live["lines"] and plain(replay).count("working") == 2  # resume + fallback both kept (UI-10)


def test_ring_count_is_bounded(monkeypatch):
    monkeypatch.setattr(pr, "RUN_EVENTS", {})
    monkeypatch.setattr(pr, "MAX_RINGS", 3)
    for i in range(5):
        pr.ring_for(f"r{i}").append("x")
    assert list(pr.RUN_EVENTS) == ["r2", "r3", "r4"]


# ── the project path keeps its own launcher, gains the durable log ───────────

from test_project_dispatch import SENTINEL, helper, proj  # noqa: E402,F401  (fixtures)


def test_project_run_replays_after_restart_without_the_engine(helper, monkeypatch):
    app_mod, run, records_, state, events, comments, pushes, repo, write_registry = helper
    used = []
    monkeypatch.setattr(app_mod, "run_agent_process", lambda *a, **k: used.append(a))
    state["mode"] = "stream"
    run(run_id="run-replay")
    assert used == []  # project path: projects.spawn / project_runs.run_agent, not the engine
    live = pr.RUN_EVENTS["run-replay"].snapshot()
    pr.RUN_EVENTS.clear()
    replay = app_mod.app.test_client().get("/api/runs/run-replay/events",
                                           headers={"X-AgenticOS-Token": app_mod.REQUEST_TOKEN}).get_json()
    assert replay["lines"] == live and "s0" in replay["lines"]
    assert app_mod._claude_stream_log_path("run-replay").parent == app_mod.RUN_PROGRESS_DIR


def test_confidential_project_log_only_where_records_may_go(helper, monkeypatch):
    app_mod, run, records_, state, events, comments, pushes, repo, write_registry = helper
    import projects as pj
    write_registry(confidential=True)
    monkeypatch.setattr(pj, "record_location_problem", lambda paths, checkout: "records outside")
    run(run_id="run-conf")
    assert not app_mod._claude_stream_log_path("run-conf").exists()  # refused: no log anywhere


def test_stderr_reaches_the_live_view_and_replay(eng, tmp_path):
    app_mod, *_ = eng
    app_mod._running_jobs["fail"] = {"run_id": "fail"}
    out, *_rest, err, ok = app_mod.run_agent_process(
        "fail", [sys.executable, str(tmp_path / "fake_cli.py"), "failing", "ok"], stream="claude", timeout=20)
    assert not ok and "not logged in" in err
    live = pr.RUN_EVENTS["fail"].snapshot()
    assert plain(live) == ["[stderr] Error: not logged in"]  # REV-03
    app_mod._running_jobs.pop("fail")
    pr.RUN_EVENTS.clear()
    assert app_mod._replay_lines("fail", "claude") == live


def test_stderr_survives_a_timeout_and_a_later_attempt(eng, tmp_path):
    app_mod, *_ = eng
    import subprocess as sp
    app_mod._running_jobs["st"] = {"run_id": "st"}
    with pytest.raises(sp.TimeoutExpired):
        app_mod.run_agent_process("st", [sys.executable, str(tmp_path / "fake_cli.py"), "slowerr", "ok"],
                                  stream="claude", timeout=2)
    assert "[stderr] warning: retrying upstream" in plain(pr.RUN_EVENTS["st"].snapshot())  # live (UI8-03)
    app_mod.run_agent_process("st", [sys.executable, str(tmp_path / "fake_cli.py"), "claude", "ok"], stream="claude", timeout=20)
    meta = json.loads(app_mod._stream_meta_path("st").read_text())
    assert [e["line"] for e in meta["stderr_tail"]] == ["warning: retrying upstream"] and meta["format"] == "claude"  # kept (UI8-04)
    app_mod._running_jobs.pop("st")
    pr.RUN_EVENTS.clear()
    assert "[stderr] warning: retrying upstream" in plain(app_mod._replay_lines("st", "claude"))


def test_project_reader_streams_stderr_while_running(tmp_path):
    script = tmp_path / "agent.py"
    script.write_text(textwrap.dedent('''
        import sys, time
        print("warn: slow upstream", file=sys.stderr, flush=True)
        time.sleep(1.0)
        print("done", flush=True)
    '''))
    got = []
    t0 = time.monotonic()
    import os
    pr.run_agent([sys.executable, str(script)], str(tmp_path), dict(os.environ), "run-se", "dsh", 20,
                 lambda ev, data: None, on_stderr=lambda raw: got.append((time.monotonic() - t0, raw)))
    end = time.monotonic() - t0
    assert got and got[0][1].startswith(b"warn: slow upstream") and got[0][0] < end - 0.5  # IR9-02


def test_dsh_session_announcement_is_recognised():
    assert pr.session_id_of("dsh", json.dumps({"type": "session", "sessionId": "d-1"})) == "d-1"  # UI10-01


def test_codex_messages_stay_apart_and_live_rings_survive_eviction(monkeypatch):
    import app as app_mod
    out, *_ = app_mod._parse_agent_output("codex", "\n".join(json.dumps(
        {"type": "item.completed", "item": {"type": "agent_message", "text": t}}) for t in ("Shall I go?", "Done.")))
    assert out == "Shall I go?\n\nDone."  # messages stay apart (IR19-03)
    monkeypatch.setattr(pr, "RUN_EVENTS", {})
    monkeypatch.setattr(pr, "MAX_RINGS", 2)
    monkeypatch.setattr(pr, "is_active", lambda rid: rid == "long")
    pr.ring_for("long").append("x")
    for i in range(4):
        pr.ring_for(f"r{i}")
    assert "long" in pr.RUN_EVENTS and pr.RUN_EVENTS["long"].total == 1  # IR19-04


def test_codex_last_message_comes_from_the_stream_log(eng):
    app_mod, *_ = eng
    log = app_mod._claude_stream_log_path("cx-last")
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("\n".join(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": t}})
                             for t in ("Shall I start?", "Done.\n\nAll green.")) + "\n")
    rec = {"run_id": "cx-last", "agent": "codex", "status": "review", "output": "Shall I start?\n\nDone.\n\nAll green."}
    assert app_mod._assistant_text(rec) == "Done.\n\nAll green."  # the real last message, paragraphs kept (R20-03)
    assert pr.waiting_question(app_mod._assistant_text(rec)) is None


def test_replay_keeps_stdout_and_stderr_in_their_live_order(eng, tmp_path):
    app_mod, *_ = eng
    app_mod._running_jobs["il"] = {"run_id": "il"}
    app_mod.run_agent_process("il", [sys.executable, str(tmp_path / "fake_cli.py"), "interleaved", "ok"], stream="claude", timeout=20)
    live = plain(pr.RUN_EVENTS["il"].snapshot())
    assert live == ["starting", "[stderr] temporary failure", "recovered"]
    app_mod._running_jobs.pop("il")
    pr.RUN_EVENTS.clear()
    assert plain(app_mod._replay_lines("il", "claude")) == live  # FINAL-02


def test_stderr_activity_is_progress(eng, tmp_path):
    app_mod, *_ = eng
    app_mod._running_jobs["eq"] = {"run_id": "eq", "last_progress_at": 0.0}
    app_mod.run_agent_process("eq", [sys.executable, str(tmp_path / "fake_cli.py"), "errquiet", "ok"], stream="claude", timeout=20)
    assert app_mod._running_jobs["eq"]["last_progress_at"] > 0  # the stall pass sees it working (FINAL-01)


def test_stderr_without_newlines_is_progress(eng):
    app_mod, *_ = eng
    app_mod._running_jobs["cr"] = {"run_id": "cr", "last_progress_at": 0.0}
    app_mod._StderrSink("cr").feed(b"\rdownloading 12%")  # no newline yet
    assert app_mod._running_jobs["cr"]["last_progress_at"] > 0  # UI27-01
    app_mod._running_jobs["cr"]["last_progress_at"] = 0.0
    app_mod._StderrSink("cr").feed(b"\r")  # a bare progress repaint
    assert app_mod._running_jobs["cr"]["last_progress_at"] > 0  # DS-01


def test_stderr_cannot_slip_between_a_stdout_write_and_its_publication(eng, tmp_path):
    app_mod, *_ = eng
    rid = "ord"
    app_mod._running_jobs[rid] = {"run_id": rid}
    sink = app_mod._StderrSink(rid)
    real_publish = app_mod._publish_run_line
    state = {}

    def publish(run_id, fmt, line):  # the stdout line is flushed; now stderr tries to cut in
        t = app_mod._REAL_THREAD(target=lambda: sink._line("E"))  # the fixture fakes threading.Thread
        t.start()
        t.join(timeout=0.3)
        state["blocked"] = t.is_alive()
        real_publish(run_id, fmt, line)
        state["t"] = t
    app_mod._publish_run_line = publish
    try:
        log = app_mod._claude_stream_log_path(rid)
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as sf:
            app_mod._persist_and_publish(rid, "text", sf, "A")
    finally:
        app_mod._publish_run_line = real_publish
    state["t"].join(timeout=5)
    sink.close()
    live = plain(pr.RUN_EVENTS[rid].snapshot())
    assert state["blocked"] and live == ["A", "[stderr] E"]  # UI27-02
    app_mod._running_jobs.pop(rid)
    pr.RUN_EVENTS.clear()
    assert plain(app_mod._replay_lines(rid, "text")) == live


def test_renderer_covers_every_codex_tool_item():
    r = lambda ev: plain(pr.render_event("codex", json.dumps(ev)))
    mcp = {"type": "mcp_tool_call", "server": "docs", "tool": "search", "arguments": {"q": "x"}, "status": "in_progress"}
    assert r({"type": "item.started", "item": mcp}) == ['[tool] mcp docs.search {"q": "x"}']
    assert r({"type": "item.completed", "item": {**mcp, "status": "completed", "result": {"content": [{"text": "3 hits"}]}}}) == ["  ↳ 3 hits"]
    failed = pr.render_event("codex", json.dumps({"type": "item.completed", "item": {**mcp, "status": "failed", "error": {"message": "denied"}}}))
    assert plain(failed) == ["  ↳ failed: denied"] and failed[0].startswith("\x1b[31m")
    fc = {"type": "file_change", "changes": [{"path": "a.py", "kind": "update"}], "status": "completed"}
    assert r({"type": "item.started", "item": fc}) == ["[tool] edit update a.py"]
    assert r({"type": "item.completed", "item": fc}) == ["  ↳ edit update a.py (completed)"]
    assert r({"type": "item.started", "item": {"type": "web_search", "query": "codex events"}}) == ["[tool] web_search codex events"]
    assert r({"type": "item.completed", "item": {"type": "error", "message": "stream lost"}}) == ["[error] stream lost"]  # UI28-01


def test_codex_tool_results_from_every_payload_field():
    r = lambda ev: pr.render_event("codex", json.dumps(ev))
    mcp = {"type": "mcp_tool_call", "server": "s", "tool": "t", "status": "completed",
           "result": {"content": [], "structured_content": {"rows": 2}}}
    assert plain(r({"type": "item.completed", "item": mcp})) == ['  ↳ {"rows": 2}']
    web = {"type": "web_search", "query": "q", "results": [{"title": "Codex docs"}]}
    assert "Codex docs" in plain(r({"type": "item.completed", "item": web}))[0]
    collab = {"type": "collab_tool_call", "tool": "wait", "status": "completed",
              "agents_states": {"a1": {"status": "completed", "message": "ok"}, "a2": {"status": "errored", "error": "boom"}}}
    out = r({"type": "item.completed", "item": collab})
    assert plain(out) == ["  ↳ failed: boom"] and out[0].startswith("\x1b[31m")  # REVIEW-01
    collab_ok = {**collab, "agents_states": {"a1": {"status": "completed", "message": "all green"}}}
    assert plain(r({"type": "item.completed", "item": collab_ok})) == ["  ↳ all green"]


def test_failed_codex_turn_reason_survives_replay(eng):
    app_mod, *_ = eng
    log = app_mod._claude_stream_log_path("tf")
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(json.dumps({"type": "turn.failed", "error": {"message": "context window exceeded"}}) + "\n")
    app_mod._stream_meta_path("tf").write_text(json.dumps({"format": "codex"}))
    assert plain(app_mod._replay_lines("tf", "codex")) == ["[result] error: context window exceeded"]
