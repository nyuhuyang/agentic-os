"""One task, one session, named by the card title (plan 2026-10-16-projects-vertical-session-titles).
Fixture session stores under tmp_path (conftest); fake names only."""

import contextlib
import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_reset_gen import ISSUE, SID, capture_launches, env, reset_route, resumed, write_log  # noqa: E402,F401

import projects as pj  # noqa: E402
import project_runs  # noqa: E402

USAGE = "You've hit your session limit · resets 10:50pm (America/New_York)"


@pytest.fixture
def cs(env, monkeypatch):
    app_mod, mod, client, log, events, tmp = env
    monkeypatch.setattr(app_mod, "_running_jobs", {})
    monkeypatch.setattr(app_mod, "_running_procs", {})
    monkeypatch.setattr(app_mod, "_SESSION_CLAIMS", {})
    monkeypatch.setattr(app_mod, "_LINEAR_TITLES", {})
    monkeypatch.setattr(app_mod, "_CLOSING_SESSIONS", {})
    monkeypatch.setattr(app_mod, "_process_table", lambda: {})  # no real ps: nothing open elsewhere
    return env


def transcript(cwd, sid=SID, age=600, title=None):
    d = pj.CLAUDE_PROJECTS / pj._slug(str(cwd))
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{sid}.jsonl"
    lines = [{"type": "user", "cwd": str(cwd), "entrypoint": "sdk-cli",
              "message": {"role": "user", "content": "You are working in a git worktree of project 'x'"}}]
    if title:
        lines.append({"type": "custom-title", "customTitle": title, "sessionId": sid})
    f.write_text("".join(json.dumps(x) + "\n" for x in lines))
    os.utime(f, (time.time() - age, time.time() - age))
    return f


def custom_titles(f):
    return [json.loads(l)["customTitle"] for l in f.read_text().splitlines() if '"custom-title"' in l]


def codex_store(root_cwd, tid, name=None, title="t", first="first"):
    pj.CODEX_DB.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(pj.CODEX_DB)
    db.execute("CREATE TABLE IF NOT EXISTS threads (id TEXT, cwd TEXT, name TEXT, title TEXT, first_user_message TEXT, "
               "updated_at INTEGER, tokens_used INTEGER, git_branch TEXT, source TEXT, archived INTEGER, "
               "archived_at INTEGER, rollout_path TEXT)")
    rollout = pj.CODEX_DB.parent / f"rollout-{tid}.jsonl"
    rollout.write_text("{}\n")
    os.utime(rollout, (time.time() - 600, time.time() - 600))
    db.execute("INSERT INTO threads VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
               (tid, str(root_cwd), name, title, first, 1, 0, "main", "exec", 0, None, str(rollout)))
    db.commit()
    db.close()


def thread_name(tid):
    db = sqlite3.connect(pj.CODEX_DB)
    try:
        return db.execute("SELECT name FROM threads WHERE id = ?", (tid,)).fetchone()[0]
    finally:
        db.close()


def records(log):
    return [json.loads(l) for l in log.read_text().splitlines()]


def tasks(tmp):
    return json.loads((tmp / "tasks.json").read_text())


class Proc:
    """A finished agent process: its stdout lines, its exit code, no pid (no group to wait for)."""
    def __init__(self, cmd, lines=(), rc=0, **kw):
        self.args, self.returncode = cmd, rc
        self.stdout = iter([(json.dumps(x) + "\n").encode() for x in lines])
        self.stderr = type("E", (), {"read": lambda s: b""})()
    def communicate(self, timeout=None): return b"", b""
    def wait(self, timeout=None): return self.returncode
    def poll(self): return self.returncode
    def kill(self): pass


def stub(app_mod, monkeypatch, lines=(), rc=0):
    procs = []

    def make(cmd, **kw):
        procs.append(Proc(cmd, lines, rc))
        return procs[-1]
    monkeypatch.setattr(app_mod.subprocess, "Popen", make)
    return procs


# ── units ──────────────────────────────────────────────────────────────────

def test_find_session_gives_cwd_and_the_native_name_only(tmp_path):
    transcript(tmp_path, "c1")
    t = pj.find_session("claude", "c1")
    assert t["cwd"] == str(tmp_path) and t["native_title"] is None and t["title"].startswith("You are working")
    transcript(tmp_path, "c2", title="Named")
    assert pj.find_session("claude", "c2")["native_title"] == "Named"
    codex_store(tmp_path, "x1", name=None, title="Card")
    t = pj.find_session("codex", "x1")
    assert t["title"] == "Card" and t["native_title"] is None  # threads.name, not the display chain (DP-30)
    assert pj.find_session("claude", "../etc") is None and pj.find_session("dsh", "c1") is None


def test_session_name_text_sanitizes():
    assert pj.session_name_text("  a\x07b \n c  ") == "a b c"
    assert len(pj.session_name_text("x" * 500)) == 200
    assert pj.session_name_text("\x00\x01") == "" and pj.session_name_text(None) == ""


def test_runner_note_renders_in_every_format():
    line = project_runs.note_line("new session: no session yet")
    for fmt in ("claude", "codex", "dsh", "text"):
        assert any("new session: no session yet" in x for x in project_runs.render_event(fmt, line))


def test_agent_error_of_claude_and_codex():
    claude = json.dumps({"type": "result", "is_error": True, "result": USAGE, "api_error": "usage_limit_reached"})
    assert project_runs.agent_error_of("claude", claude) == USAGE
    assert project_runs.agent_error_of("claude", json.dumps({"type": "result", "is_error": False, "result": "ok"})) is None
    failed = json.dumps({"type": "turn.failed", "error": {"message": "quota exhausted"}})
    assert project_runs.agent_error_of("codex", failed) == "quota exhausted"


def test_routing_call_leaves_no_session(cs):
    app_mod, *_ = cs
    assert "--no-session-persistence" in app_mod._ai_command("claude", "p", output_format="text", persist=False)
    cmd = app_mod._ai_command("codex", "p", persist=False)
    assert cmd[:3] == ["codex", "exec", "--ephemeral"]
    assert "--no-session-persistence" not in app_mod._ai_command("claude", "p")


def test_older_linear_title_never_replaces_a_newer_one(cs):
    app_mod, *_ = cs
    app_mod._confirm_linear_title("i", "B", "2026-10-17T02:00:00Z")
    app_mod._confirm_linear_title("i", "A", "2026-10-17T01:00:00Z")  # a poll that fetched before the rename
    assert app_mod._LINEAR_TITLES["i"][0] == "B"


def test_owner_record_has_the_real_duration(cs):
    app_mod, mod, client, log, events, tmp = cs
    started = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
    job = {"run_id": "o", "skill": "_prompt", "started_at": started, "prompt": "p", "linear_issue_id": ISSUE,
           "record": {"agent": "claude", "task_id": "T"}}
    app_mod._write_owner_record("o", job, "cancelled", "Cancelled by user")
    assert records(log)[-1]["duration_s"] >= 29  # the card's own activity ends at the cancel (DP-27)


def test_issue_title_is_withheld_for_a_confidential_run_where_records_are_unsafe(cs, monkeypatch):
    app_mod, *_ = cs
    assert app_mod._issue_title_extra(ISSUE) == {"issue_title": "t"}
    monkeypatch.setattr(app_mod, "_records_unsafe", lambda: "outside the checkout")
    assert app_mod._issue_title_extra(ISSUE, None) == {} and app_mod._issue_title_extra(ISSUE, True) == {}


def test_quick_reply_is_gone():
    html = (Path(__file__).resolve().parents[1] / "runner" / "templates" / "index.html").read_text()
    assert "detail-term-reply" not in html and "_cardTermQuickReply" not in html


# ── one task, one session ─────────────────────────────────────────────────

def test_retry_after_reset_continues_the_card_session(cs, monkeypatch):
    app_mod, mod, client, log, events, tmp = cs
    f = transcript(app_mod.ROOT)
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID})
    reset_route(client)
    procs = stub(app_mod, monkeypatch, [{"type": "system", "subtype": "init", "session_id": SID},
                                        {"type": "result", "result": "done", "session_id": SID}])
    assert client.post("/api/runs/a/retry", json={"reply": "go on"}).status_code == 200
    assert len(procs) == 1 and "--resume" in procs[0].args and SID in procs[0].args
    rec = records(log)[-1]
    assert rec["status"] == "review" and rec["agent_session_id"] == SID and rec["issue_title"] == "t"
    assert custom_titles(f) == ["t"]  # the run's end named the session after the card


def test_failed_card_resume_is_an_error_with_the_agents_reason(cs, monkeypatch):
    app_mod, mod, client, log, events, tmp = cs
    transcript(app_mod.ROOT)
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID})
    reset_route(client)
    procs = stub(app_mod, monkeypatch, [{"type": "result", "is_error": True, "result": USAGE,
                                         "api_error": "usage_limit_reached", "session_id": SID}], rc=1)
    assert client.post("/api/runs/a/retry", json={"reply": "go on"}).status_code == 200
    assert len(procs) == 1  # no fresh fallback (DP-35)
    rec = records(log)[-1]
    assert rec["status"] == "error" and rec["error"] == USAGE  # D6


def test_retry_without_a_session_on_disk_starts_fresh_with_a_note(cs, monkeypatch):
    app_mod, mod, client, log, events, tmp = cs
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review"})
    procs = stub(app_mod, monkeypatch, [{"type": "result", "result": "done", "session_id": "new-1"}])
    assert client.post("/api/runs/a/retry", json={}).status_code == 200
    assert not resumed(procs[0].args)
    assert records(log)[-1]["session_note"] == "new session: no session yet"
    log_lines = app_mod._claude_stream_log_path(records(log)[-1]["run_id"]).read_text()
    assert "agenticos-note" in log_lines


def test_retry_for_a_card_that_is_gone_is_refused(cs, monkeypatch):
    app_mod, mod, client, log, events, tmp = cs
    import state_io
    state_io.write_json_atomic(tmp / "tasks.json", {})
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID})
    procs = stub(app_mod, monkeypatch)
    r = client.post("/api/runs/a/retry", json={"reply": "x"})
    assert r.status_code == 409 and "no longer exists" in r.get_json()["error"] and procs == []


def test_dispatch_continues_the_card_session_without_routing(cs, monkeypatch):
    app_mod, mod, client, log, events, tmp = cs
    transcript(app_mod.ROOT)
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID})
    reset_route(client)
    routed = []
    monkeypatch.setattr(app_mod, "_run_grouped", lambda cmd, *a, **k: routed.append(cmd))
    procs = stub(app_mod, monkeypatch, [{"type": "result", "result": "done", "session_id": SID}])
    issue = {"id": ISSUE, "identifier": "T-1", "title": "t", "description": ""}
    mod._dispatch_issue_counted(issue, {"agent": {"backend": "claude"}}, app_mod.socketio)
    assert routed == [] and len(procs) == 1 and "--resume" in procs[0].args and SID in procs[0].args
    assert records(log)[-1]["agent_session_id"] == SID and records(log)[-1]["status"] == "review"


def test_fresh_dispatch_routes_without_leaving_a_session(cs, monkeypatch):
    app_mod, mod, client, log, events, tmp = cs
    routed = []

    def route(cmd, *a, **k):
        routed.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "_prompt", "")
    monkeypatch.setattr(app_mod, "_run_grouped", route)
    procs = stub(app_mod, monkeypatch, [{"type": "result", "result": "done", "session_id": "s-new"}])
    issue = {"id": ISSUE, "identifier": "T-1", "title": "t", "description": ""}
    mod._dispatch_issue_counted(issue, {"agent": {"backend": "claude"}}, app_mod.socketio)
    assert "--no-session-persistence" in routed[0] and not resumed(procs[0].args)
    assert records(log)[-1]["session_note"] == "new session: no session yet"


def test_dispatch_refuses_a_session_open_elsewhere(cs, monkeypatch):
    app_mod, mod, client, log, events, tmp = cs
    transcript(app_mod.ROOT)
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID})
    monkeypatch.setattr(app_mod, "_process_table", lambda: {999999: (1, f"claude --resume {SID}")})
    monkeypatch.setattr(app_mod, "_run_grouped", lambda *a, **k: None)
    procs = stub(app_mod, monkeypatch)
    issue = {"id": ISSUE, "identifier": "T-1", "title": "t", "description": ""}
    mod._dispatch_issue_counted(issue, {"agent": {"backend": "claude"}}, app_mod.socketio)
    rec = records(log)[-1]
    assert procs == [] and rec["status"] == "error" and "session in use elsewhere" in rec["error"]
    assert app_mod._SESSION_CLAIMS == {}


# ── the card title as the session name ────────────────────────────────────

def test_title_edit_renames_idle_sessions_and_skips_a_live_one(cs):
    app_mod, mod, client, log, events, tmp = cs
    f = transcript(tmp / "elsewhere")
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID})
    assert client.patch(f"/api/linear/issues/local/{ISSUE}", json={"title": "New name"}).status_code == 200
    assert custom_titles(f) == ["New name"]
    app_mod._running_jobs["x"] = {"run_id": "x", "agent": "claude", "agent_session_id": SID}
    assert client.patch(f"/api/linear/issues/local/{ISSUE}", json={"title": "Newer"}).status_code == 200
    assert custom_titles(f) == ["New name"]  # live: renamed at its run's end instead


def test_sync_never_writes_the_preamble_without_a_confirmed_title(cs, monkeypatch):
    app_mod, mod, client, log, events, tmp = cs
    f = transcript(tmp / "elsewhere")
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID})
    monkeypatch.setattr(app_mod, "_confirmed_title", lambda iid: None)
    app_mod._sync_card_session_names(ISSUE)
    assert custom_titles(f) == []


def test_codex_name_is_written_even_when_its_display_title_matches(cs):
    app_mod, mod, client, log, events, tmp = cs
    codex_store(tmp, "x1", name=None, title="t")
    write_log(log, {"run_id": "a", "agent": "codex", "status": "review", "agent_session_id": "x1"})
    app_mod._sync_card_session_names(ISSUE)
    assert thread_name("x1") == "t"


def test_closing_marker_blocks_every_rename_until_the_group_is_gone(cs):
    app_mod, mod, client, log, events, tmp = cs
    f = transcript(tmp / "elsewhere")
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID})
    proc = subprocess.Popen(["/bin/sh", "-c", "sleep 30 & sleep 30"], start_new_session=True)
    time.sleep(0.5)  # both children started
    try:
        app_mod._mark_closing("claude", SID, proc.pid)
        os.kill(proc.pid, signal.SIGKILL)  # the leader is gone, its child still in the group
        proc.wait()
        app_mod._sync_card_session_names(ISSUE)
        assert custom_titles(f) == []  # a reaped leader is not enough (R6)
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)
    deadline = time.monotonic() + 5
    while app_mod._group_alive(proc.pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    app_mod._sync_card_session_names(ISSUE)
    assert custom_titles(f) == ["t"] and app_mod._CLOSING_SESSIONS == {}


def test_own_last_write_does_not_block_a_rename_right_after_a_run(cs):
    app_mod, mod, client, log, events, tmp = cs
    f = transcript(tmp / "elsewhere", age=0)  # written just now ...
    started = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID,
                    "started_at": started, "duration_s": 5})  # ... by this card's own last run (DP-26)
    app_mod._sync_card_session_names(ISSUE)
    assert custom_titles(f) == ["t"]


@pytest.fixture
def demo(cs, monkeypatch, tmp_path):
    proj = tmp_path / "demo"
    proj.mkdir()
    subprocess.run(["git", "init", "-q", str(proj)], check=True)
    reg = tmp_path / "projects.yaml"
    reg.write_text(yaml.safe_dump({"projects": {"demo": {"path": str(proj), "confidential": False}}}))
    monkeypatch.setattr(pj, "REGISTRY_PATH", reg)
    monkeypatch.setattr(pj, "WORKTREE_ROOT", tmp_path / "wt")
    return proj


def test_card_row_rename_renames_the_card_and_the_session(cs, demo):
    app_mod, mod, client, log, events, tmp = cs
    f = transcript(demo)
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID})
    r = client.post(f"/api/projects/demo/sessions/claude/{SID}/rename", json={"title": "Row name"})
    assert r.status_code == 200 and r.get_json()["card"] is True
    assert tasks(tmp)[ISSUE]["title"] == "Row name" and custom_titles(f) == ["Row name"]


def test_card_row_rename_validates_before_any_write(cs, demo):
    app_mod, mod, client, log, events, tmp = cs
    f = transcript(demo)
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID})
    r = client.post(f"/api/projects/demo/sessions/claude/{SID}/rename", json={"title": "bad\x07"})
    assert r.status_code == 400 and tasks(tmp)[ISSUE]["title"] == "t" and custom_titles(f) == []


def test_card_row_rename_with_a_failed_linear_update_changes_nothing(cs, demo, monkeypatch):
    app_mod, mod, client, log, events, tmp = cs
    f = transcript(demo)
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID})
    monkeypatch.setattr(mod, "set_card_title", lambda iid, title: (_ for _ in ()).throw(RuntimeError("Linear down")))
    r = client.post(f"/api/projects/demo/sessions/claude/{SID}/rename", json={"title": "Row name"})
    assert r.status_code == 502 and tasks(tmp)[ISSUE]["title"] == "t" and custom_titles(f) == []


def test_archived_cards_session_row_renames_only_the_session(cs, demo):
    app_mod, mod, client, log, events, tmp = cs
    import state_io
    f = transcript(demo)
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID})
    state_io.write_json_atomic(tmp / "tasks.json", {})  # the card is gone (DP-29)
    r = client.post(f"/api/projects/demo/sessions/claude/{SID}/rename", json={"title": "Own name"})
    assert r.status_code == 200 and "card" not in r.get_json() and custom_titles(f) == ["Own name"]


def test_linear_title_update_is_title_only():
    import linear_client
    sent = {}

    class Client(linear_client.LinearClient):
        def _graphql_strict(self, query, variables=None):
            sent.update(query=query, variables=variables)
            return {"issueUpdate": {"success": True, "issue": {"id": "i", "title": "N", "updatedAt": "u"}}}
    out = Client("k", "").update_title("i", "N")
    assert out == {"id": "i", "title": "N", "updated_at": "u"}
    assert "description" not in sent["query"] and "stateId" not in sent["query"]  # nothing cleared (DP-42)


def test_project_dispatch_continues_the_session_in_its_worktree(cs, demo, monkeypatch):
    app_mod, mod, client, log, events, tmp = cs
    wt = pj.worktree_path(pj.get_project("demo"), "T-1")
    wt.mkdir(parents=True)
    transcript(wt)
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID})
    seen = {}
    monkeypatch.setattr(app_mod, "_run_project_ticket", lambda **kw: seen.update(kw))
    issue = {"id": ISSUE, "identifier": "T-1", "title": "t", "description": "", "labels": ["project:demo"]}
    mod._dispatch_issue_counted(issue, {"agent": {"backend": "claude"}}, app_mod.socketio)
    assert seen["resume_session"] == SID and seen["timeout"] == app_mod.AI_SESSION_TIMEOUT_S and seen["note"] is None


def test_project_dispatch_with_the_session_elsewhere_starts_fresh_with_a_note(cs, demo, monkeypatch):
    app_mod, mod, client, log, events, tmp = cs
    transcript(demo)  # in the main checkout, not the ticket's worktree
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID})
    seen = {}
    monkeypatch.setattr(app_mod, "_run_project_ticket", lambda **kw: seen.update(kw))
    issue = {"id": ISSUE, "identifier": "T-1", "title": "t", "description": "", "labels": ["project:demo"]}
    mod._dispatch_issue_counted(issue, {"agent": {"backend": "claude"}}, app_mod.socketio)
    assert seen["resume_session"] is None and seen["note"] == "new session: the card's session is in a different folder"


def test_card_continuation_gets_the_session_timeout(cs, monkeypatch):
    app_mod, mod, client, log, events, tmp = cs
    transcript(app_mod.ROOT)
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID})
    seen = []
    monkeypatch.setattr(app_mod, "run_agent_process", lambda rid, cmd, **kw: (seen.append(kw.get("timeout")), ("ok", 0, 0, None, SID, "", True))[1])
    assert client.post("/api/runs/a/retry", json={"reply": "x"}).status_code == 200
    assert seen == [app_mod.AI_SESSION_TIMEOUT_S]  # D7: stall detector + 4 h, not the 30-minute cap


def test_project_run_note_survives_and_codex_error_is_kept(tmp_path):
    script = tmp_path / "agent.py"
    script.write_text("import json; print(json.dumps({'type': 'turn.failed', 'error': {'message': 'quota exhausted'}}))\n")
    log_path = tmp_path / "run_stream.jsonl"
    events = []
    project_runs.run_agent([sys.executable, str(script)], str(tmp_path), dict(os.environ), "pr1", "codex", 30,
                           lambda e, p: events.append(p), log_path=log_path, note="new session: no session yet")
    first = log_path.read_text().splitlines()[0]
    assert json.loads(first)["type"] == "agenticos-note"  # written after the log's "w" open (DP-39)
    assert any("new session" in p["line"] for p in events)
    assert project_runs.pop_agent_failure("pr1") == ("quota exhausted", True)  # DP-44; a failed turn even at exit 0 (R4-03)


# ── Codex build inspection 1 (R1–R6) ───────────────────────────────────────

def test_locked_session_gone_from_disk_starts_fresh_with_a_note(cs, monkeypatch):
    app_mod, mod, client, log, events, tmp = cs
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID})  # lock, no store entry
    procs = stub(app_mod, monkeypatch, [{"type": "result", "result": "done", "session_id": "s-new"}])
    assert client.post("/api/runs/a/retry", json={"reply": "x"}).status_code == 200
    assert len(procs) == 1 and not resumed(procs[0].args)  # no doomed resume, no fallback (R2)
    assert records(log)[-1]["session_note"] == "new session: the card's session was removed or archived"


def test_codex_thread_with_its_rollout_gone_is_not_resumable(tmp_path):
    codex_store(tmp_path, "x2")
    (pj.CODEX_DB.parent / "rollout-x2.jsonl").unlink()
    assert pj.find_session("codex", "x2") is None  # R6


def test_cancel_marks_the_session_closing_before_it_leaves_the_live_set(cs):
    app_mod, mod, client, log, events, tmp = cs
    proc = subprocess.Popen(["/bin/sh", "-c", "sleep 30"], start_new_session=True)
    try:
        app_mod._running_jobs["r"] = {"run_id": "r", "agent": "claude", "agent_session_id": SID}
        app_mod._running_procs["r"] = proc
        with app_mod._JOB_LOCK:
            app_mod._mark_job_closing("r")
        assert app_mod._CLOSING_SESSIONS == {("claude", SID): proc.pid}  # R3
    finally:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()


def test_retry_refused_when_the_card_was_reset_while_queued(cs, monkeypatch):
    app_mod, mod, client, log, events, tmp = cs
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review"})
    monkeypatch.setattr(app_mod, "_card_admitted", lambda iid, gen: False)
    procs = stub(app_mod, monkeypatch)
    r = client.post("/api/runs/a/retry", json={"reply": "x"})
    assert r.status_code == 409 and procs == [] and app_mod._SESSION_CLAIMS == {}  # R4


def test_project_dispatch_releases_its_claim_when_the_state_push_fails(cs, demo, monkeypatch):
    app_mod, mod, client, log, events, tmp = cs
    wt = pj.worktree_path(pj.get_project("demo"), "T-1")
    wt.mkdir(parents=True)
    transcript(wt)
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID})
    monkeypatch.setattr(mod, "push_state", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no thread")))
    issue = {"id": ISSUE, "identifier": "T-1", "title": "t", "description": "", "labels": ["project:demo"]}
    with pytest.raises(RuntimeError):
        mod._dispatch_issue_held(issue, {"agent": {"backend": "claude"}}, app_mod.socketio,
                                 contextlib.ExitStack(), False)
    assert app_mod._SESSION_CLAIMS == {} and ISSUE not in mod.dispatched  # R5


def test_refusal_record_of_a_confidential_project_withholds_the_title(cs, monkeypatch):
    app_mod, mod, client, log, events, tmp = cs
    monkeypatch.setattr(app_mod, "_records_unsafe", lambda: "outside the checkout")
    mod._refuse_resume({"id": ISSUE, "identifier": "T-1", "title": "Secret deal"}, "rr", "claude", 0, "busy",
                       binding={"project_key": "demo", "issue_identifier": "T-1", "confidential": True})
    rec = records(log)[-1]
    assert "Secret deal" not in json.dumps(rec) and rec["project_key"] == "demo" and rec["confidential"] is True  # R1


# ── Codex build inspection 2 (PVST-01..05) ─────────────────────────────────

def test_retry_without_a_reply_continues_a_main_checkout_session(cs, demo, monkeypatch):
    app_mod, mod, client, log, events, tmp = cs
    transcript(demo)
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID,
                    "project_key": "demo", "session_project": "demo"})
    reset_route(client)
    seen = []  # the agent launch only: the registry check still runs git (Popen) for real
    monkeypatch.setattr(app_mod, "run_agent_process",
                        lambda rid, cmd, **kw: (seen.append((cmd, kw.get("cwd"))), ("done", 0, 0, None, SID, "", True))[1])
    r = client.post("/api/runs/a/retry", json={"reply": ""})  # the board's Retry sends no reply (PVST-02)
    assert r.status_code == 200, r.get_json()
    assert len(seen) == 1 and "--resume" in seen[0][0] and SID in seen[0][0] and str(seen[0][1]) == str(demo)
    assert "resume_session" not in records(log)[-1]  # card-sourced: no persisted intent (DP-34)


def test_recorded_title_is_only_a_confirmed_one(cs, monkeypatch):
    app_mod, mod, client, log, events, tmp = cs
    monkeypatch.setattr(mod, "_capability", {"available": True, "type": "linear"})
    mod.issues_cache[ISSUE] = {"id": ISSUE, "title": "B unconfirmed"}  # a /local edit Linear never took
    app_mod._confirm_linear_title(ISSUE, "A", "2026-10-17T00:00:00Z")
    assert app_mod._issue_title_extra(ISSUE) == {"issue_title": "A"}  # PVST-03


# ── Codex build inspection 3 (PVST-R3-01..03) ──────────────────────────────

def test_retry_worker_refuses_a_card_reset_while_queued(cs, monkeypatch):
    app_mod, mod, client, log, events, tmp = cs
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review"})
    calls = []
    monkeypatch.setattr(app_mod, "_card_admitted", lambda iid, gen: (calls.append(1), len(calls) == 1)[1])  # route yes, worker no
    procs = stub(app_mod, monkeypatch)
    assert client.post("/api/runs/a/retry", json={"reply": "x"}).status_code == 200
    assert procs == [] and records(log)[-1]["status"] == "cancelled"  # R3-01: nothing launched


def test_dispatch_refuses_a_card_reset_during_routing(cs, monkeypatch):
    app_mod, mod, client, log, events, tmp = cs
    monkeypatch.setattr(app_mod, "_run_grouped", lambda cmd, *a, **k: subprocess.CompletedProcess(cmd, 0, "_prompt", ""))
    monkeypatch.setattr(app_mod, "_card_admitted", lambda iid, gen: False)
    procs = stub(app_mod, monkeypatch)
    issue = {"id": ISSUE, "identifier": "T-1", "title": "t", "description": ""}
    mod._dispatch_issue_counted(issue, {"agent": {"backend": "claude"}}, app_mod.socketio)
    assert procs == [] and records(log)[-1]["status"] == "cancelled" and ISSUE not in mod.dispatched


def test_board_label_uses_the_live_local_title_after_a_restart(cs):
    app_mod, mod, client, log, events, tmp = cs
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID,
                    "issue_identifier": "T-1", "issue_title": "A"})
    import state_io
    state_io.write_json_atomic(tmp / "tasks.json", {ISSUE: {"id": ISSUE, "state": "In Review", "title": "B"}})
    mod.issues_cache.clear()  # a restart in local mode: nothing cached yet
    assert app_mod._board_sessions()[1][("claude", SID)] == {"label": "T-1", "title": "B"}  # R3-02


def test_a_card_never_continues_another_cards_session(cs, monkeypatch):
    app_mod, mod, client, log, events, tmp = cs
    import state_io
    state_io.write_json_atomic(tmp / "tasks.json", {ISSUE: {"id": ISSUE, "state": "In Review", "title": "t"},
                                                    "iss-2": {"id": "iss-2", "state": "Todo", "title": "u"}})
    transcript(app_mod.ROOT)
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID})  # card A's
    write_log(log, {"run_id": "b", "agent": "claude", "status": "todo", "agent_session_id": SID,
                    "linear_issue_id": "iss-2", "task_id": "T2"})  # S bound to card B since
    assert app_mod._card_session(ISSUE, "claude") is None and app_mod._card_session("iss-2", "claude")[0] == SID
    reset_route(client)
    procs = stub(app_mod, monkeypatch, [{"type": "result", "result": "done", "session_id": "s-new"}])
    assert client.post("/api/runs/a/retry", json={"reply": "x"}).status_code == 200
    assert not resumed(procs[0].args)  # R3-03: card A starts a new session instead


# ── Codex build inspection 4 (PVST-R4-01..03) ──────────────────────────────

def test_dispatch_queued_before_a_reset_never_runs(cs, monkeypatch):
    app_mod, mod, client, log, events, tmp = cs
    import reset_gen
    gen = reset_gen.current(ISSUE)
    reset_gen.bump(ISSUE)  # the user reset the card after the dispatch was asked for
    procs = stub(app_mod, monkeypatch)
    issue = {"id": ISSUE, "identifier": "T-1", "title": "t", "description": ""}
    mod._dispatch_issue_counted(issue, {"agent": {"backend": "claude"}}, app_mod.socketio, launch_gen=gen)
    assert procs == [] and not log.exists()  # R4-01: no launch, no record, no tracker change


def test_persisted_intent_for_a_session_another_card_owns_is_void(cs):
    app_mod, mod, client, log, events, tmp = cs
    import reset_gen, state_io
    state_io.write_json_atomic(tmp / "tasks.json", {ISSUE: {"id": ISSUE, "state": "Todo", "title": "t"},
                                                    "iss-2": {"id": "iss-2", "state": "Todo", "title": "u"}})
    intent = {"agent": "claude", "id": SID, "project_key": "demo", "gen": reset_gen.current(ISSUE)}
    write_log(log, {"run_id": "a", "agent": "claude", "status": "todo", "agent_session_id": SID, "resume_session": intent})
    rec_a = records(log)[-1]
    assert app_mod._valid_intent(rec_a) == intent
    write_log(log, {"run_id": "b", "agent": "claude", "status": "todo", "agent_session_id": SID,
                    "linear_issue_id": "iss-2", "task_id": "T2"})  # S bound to card B since
    assert app_mod._valid_intent(rec_a) is None  # R4-02


def test_continuation_with_a_failed_turn_at_exit_zero_is_an_error(cs, monkeypatch):
    app_mod, mod, client, log, events, tmp = cs
    transcript(app_mod.ROOT)
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID})
    stub(app_mod, monkeypatch, [{"type": "result", "is_error": True, "result": USAGE, "session_id": SID}], rc=0)
    assert client.post("/api/runs/a/retry", json={"reply": "x"}).status_code == 200
    rec = records(log)[-1]
    assert rec["status"] == "error" and rec["error"] == USAGE  # R4-03


# ── Codex build inspection 5 (PVST-R5-01) ──────────────────────────────────

def test_completion_with_a_surviving_descendant_blocks_renames_until_the_group_is_gone(cs):
    app_mod, mod, client, log, events, tmp = cs
    f = transcript(tmp / "elsewhere")
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID})
    proc = subprocess.Popen(["/bin/sh", "-c", "sleep 30 & sleep 30"], start_new_session=True)
    time.sleep(0.5)
    try:
        app_mod._running_jobs["r"] = {"run_id": "r", "agent": "claude", "agent_session_id": SID, "linear_issue_id": ISSUE}
        app_mod._running_procs["r"] = proc
        assert app_mod._end_job("r")  # normal completion retires the job ...
        app_mod._FINALIZING.discard("r")
        assert app_mod._CLOSING_SESSIONS.get(("claude", SID)) == proc.pid  # ... marker installed first (R5-01)
        app_mod._sync_card_session_names(ISSUE)  # e.g. a title edit right then
        assert custom_titles(f) == []
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
    deadline = time.monotonic() + 5
    while app_mod._group_alive(proc.pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    app_mod._sync_card_session_names(ISSUE)
    assert custom_titles(f) == ["t"]


def test_cancel_blocks_renames_while_its_group_exits(cs):
    app_mod, mod, client, log, events, tmp = cs
    f = transcript(tmp / "elsewhere")
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID})
    proc = subprocess.Popen(["/bin/sh", "-c", "trap '' TERM; sleep 30 & sleep 30"], start_new_session=True)
    time.sleep(0.5)
    try:
        app_mod._running_jobs["r"] = {"run_id": "r", "agent": "claude", "agent_session_id": SID, "linear_issue_id": ISSUE}
        app_mod._running_procs["r"] = proc
        with app_mod._JOB_LOCK:  # the cancel's first step: marker, then retirement (R3, R5-01)
            app_mod._mark_job_closing("r")
            app_mod._running_jobs.pop("r")
            app_mod._running_procs.pop("r")
        app_mod._sync_card_session_names(ISSUE)
        assert custom_titles(f) == []  # no window with neither the job nor the marker
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()


# ── Codex build inspection 6 (PVST-R6-01..02) ──────────────────────────────

def test_a_closing_session_cannot_be_claimed_or_resumed(cs):
    app_mod, mod, client, log, events, tmp = cs
    proc = subprocess.Popen(["/bin/sh", "-c", "sleep 30"], start_new_session=True)
    try:
        app_mod._CLOSING_SESSIONS[("claude", SID)] = proc.pid
        with pytest.raises(pj.SessionBusy):
            app_mod._claim_session("claude", SID, "r2")  # R6-01: no confirmation overrides it
        assert ("claude", SID) in app_mod._live_session_ids()
    finally:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
    deadline = time.monotonic() + 5
    while app_mod._group_alive(proc.pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    app_mod._claim_session("claude", SID, "r3")  # gone: claimable again
    assert app_mod._SESSION_CLAIMS["r3"] == ("claude", SID) and app_mod._CLOSING_SESSIONS == {}


def test_first_linear_confirmation_names_the_cards_session(cs, monkeypatch):
    app_mod, mod, client, log, events, tmp = cs
    monkeypatch.setattr(mod, "_capability", {"available": True, "type": "linear"})
    f = transcript(tmp / "elsewhere")
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID})
    app_mod._sync_card_session_names(ISSUE)
    assert custom_titles(f) == []  # no confirmed title yet: skipped (DP-46)
    mod.issues_cache[ISSUE] = {"id": ISSUE, "title": "Linear title"}
    app_mod._confirm_linear_title(ISSUE, "Linear title", "2026-10-17T03:00:00Z")  # the first poll after the run
    assert custom_titles(f) == ["Linear title"]  # R6-02


# ── Codex build inspection 7 (PVST-R7-01..02) ──────────────────────────────

def test_poll_confirmation_syncs_only_after_the_issue_is_published(cs, monkeypatch):
    app_mod, mod, client, log, events, tmp = cs
    import runner.modules.linear as lin
    monkeypatch.setattr(mod, "_capability", {"available": True, "type": "linear"})
    f = transcript(tmp / "elsewhere")
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID})
    mod.issues_cache.clear()  # a restart: the poll has not published anything yet
    pending: set = set()
    lin._note_linear_title({"id": ISSUE, "title": "From Linear", "updated_at": "2026-10-17T04:00:00Z"}, pending)
    assert pending == {ISSUE} and custom_titles(f) == []  # collected, not run against an empty cache
    mod.issues_cache[ISSUE] = {"id": ISSUE, "title": "From Linear"}  # the poll publishes
    lin._start_title_syncs(pending)
    assert custom_titles(f) == ["From Linear"]  # R7-01


def test_an_old_watcher_never_clears_a_newer_runs_marker(cs):
    app_mod, mod, client, log, events, tmp = cs
    newer = subprocess.Popen(["/bin/sh", "-c", "sleep 30"], start_new_session=True)
    try:
        app_mod._CLOSING_SESSIONS[("claude", SID)] = newer.pid  # run B's marker
        assert app_mod._clear_closing(("claude", SID), 999999) is False  # run A's watcher, A's token (R7-02)
        assert app_mod._CLOSING_SESSIONS[("claude", SID)] == newer.pid
    finally:
        os.killpg(newer.pid, signal.SIGKILL)
        newer.wait()


# ── Codex build inspection 8 (PVST-R8-01..02) ──────────────────────────────

def test_retry_start_failure_record_keeps_no_inherited_title(cs, demo, monkeypatch):
    app_mod, mod, client, log, events, tmp = cs
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "project_key": "demo",
                    "issue_identifier": "T-1", "confidential": True, "issue_title": "Secret deal",
                    "source": "session", "session_project": "demo"})
    monkeypatch.setattr(app_mod, "_records_unsafe", lambda: "outside the checkout")
    monkeypatch.setattr(app_mod, "_push_linear_state_async", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no thread")))
    r = client.post("/api/runs/a/retry", json={"reply": "x"})
    assert r.status_code == 500
    rec = records(log)[-1]
    assert rec["status"] == "error" and "Secret deal" not in json.dumps(rec)  # R8-01
    assert rec["project_key"] == "demo" and rec["issue_identifier"] == "T-1"


def test_retry_of_a_session_card_without_a_worktree_starts_fresh(cs, demo, monkeypatch):
    app_mod, mod, client, log, events, tmp = cs
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "project_key": "demo",
                    "issue_identifier": "T-1", "source": "session", "session_project": "demo"})  # session gone
    seen = {}
    monkeypatch.setattr(app_mod, "_run_project_ticket", lambda **kw: seen.update(kw))
    assert client.post("/api/runs/a/retry", json={"reply": "x"}).status_code == 200
    assert seen["reuse_only"] is False and seen["resume_session"] is None and seen["note"]  # R8-02


# ── Codex build inspection 9 (PVST-R9-01..03) ──────────────────────────────

def test_card_row_rename_with_an_empty_cache_keeps_the_card_metadata(cs, demo):
    app_mod, mod, client, log, events, tmp = cs
    import state_io
    state_io.write_json_atomic(tmp / "tasks.json", {ISSUE: {"id": ISSUE, "identifier": "LOC-7", "state": "In Review",
                                                            "title": "t", "labels": ["x"]}})
    transcript(demo)
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID})
    mod.issues_cache.clear()  # a restart in local mode
    assert client.post(f"/api/projects/demo/sessions/claude/{SID}/rename", json={"title": "New"}).status_code == 200
    cached = mod.issues_cache[ISSUE]
    assert cached["identifier"] == "LOC-7" and cached["state"] == "In Review" and cached["labels"] == ["x"]  # R9-02
    assert app_mod._board_sessions()[1][("claude", SID)] == {"label": "LOC-7", "title": "New"}


def test_retry_transient_intent_keeps_the_generation_the_request_read(cs, demo, monkeypatch):
    app_mod, mod, client, log, events, tmp = cs
    import reset_gen
    transcript(demo)
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID,
                    "project_key": "demo", "session_project": "demo"})
    real_find = pj.find_session

    def find_then_reset(agent, sid):  # the card is reset while the route resolves the session
        out = real_find(agent, sid)
        reset_gen.bump(ISSUE)
        return out
    monkeypatch.setattr(pj, "find_session", find_then_reset)
    launched = []
    monkeypatch.setattr(app_mod, "run_agent_process", lambda *a, **k: launched.append(1))
    r = client.post("/api/runs/a/retry", json={"reply": "x"})
    assert r.status_code == 409 and launched == []  # R9-01


# ── Codex build inspection 10 (PVST-R10-01) ────────────────────────────────

def test_a_deleted_cards_session_shows_its_own_name(cs, demo):
    app_mod, mod, client, log, events, tmp = cs
    import state_io
    f = transcript(demo)
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID,
                    "issue_identifier": "T-1", "issue_title": "Old card"})
    assert app_mod._board_sessions()[1][("claude", SID)]["label"] == "T-1"
    state_io.write_json_atomic(tmp / "tasks.json", {})  # emptied from the trash
    assert ("claude", SID) not in app_mod._board_sessions()[1]  # R10-01: no stale card title
    assert client.post(f"/api/projects/demo/sessions/claude/{SID}/rename", json={"title": "Mine"}).status_code == 200
    rows = {r["id"]: r for r in pj.project_sessions(pj.get_project("demo"), *app_mod._board_sessions())}
    assert rows[SID]["title"] == "Mine" and "card_title" not in rows[SID]


# ── Codex build inspection 11 (PVST-R11-01) ────────────────────────────────

def test_label_comes_from_the_owning_card_even_after_an_old_record_is_archived(cs):
    app_mod, mod, client, log, events, tmp = cs
    import state_io
    state_io.write_json_atomic(tmp / "tasks.json", {ISSUE: {"id": ISSUE, "identifier": "A-1", "state": "Done", "title": "a"},
                                                    "iss-2": {"id": "iss-2", "identifier": "B-1", "state": "Todo", "title": "b"}})
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID, "issue_identifier": "A-1"})
    write_log(log, {"run_id": "b", "agent": "claude", "status": "todo", "agent_session_id": SID,
                    "linear_issue_id": "iss-2", "task_id": "T2", "issue_identifier": "B-1"})  # S now B's
    write_log(log, {"run_id": "a", "agent": "claude", "status": "archived", "agent_session_id": SID,
                    "issue_identifier": "A-1"})  # A's old run archived afterwards
    assert app_mod._board_sessions()[1][("claude", SID)]["label"] == "B-1"  # R11-01


# ── Codex build inspection 12 (PVST-R12-01) ────────────────────────────────

@pytest.mark.parametrize("gone", ["claude-removed", "codex-archived", "codex-no-rollout"])
def test_persisted_intent_for_a_removed_session_starts_fresh(cs, demo, monkeypatch, gone):
    app_mod, mod, client, log, events, tmp = cs
    import reset_gen
    agent = "claude" if gone.startswith("claude") else "codex"
    if gone == "codex-archived":
        codex_store(demo, SID)
        db = sqlite3.connect(pj.CODEX_DB)
        db.execute("UPDATE threads SET archived = 1 WHERE id = ?", (SID,))
        db.commit()
        db.close()
    elif gone == "codex-no-rollout":
        codex_store(demo, SID)
        (pj.CODEX_DB.parent / f"rollout-{SID}.jsonl").unlink()
    intent = {"agent": agent, "id": SID, "project_key": "demo", "gen": reset_gen.current(ISSUE)}
    write_log(log, {"run_id": "a", "agent": agent, "status": "todo", "agent_session_id": SID, "resume_session": intent,
                    "project_key": "demo", "issue_identifier": "T-1", "source": "session", "session_project": "demo"})
    seen = {}
    monkeypatch.setattr(app_mod, "_run_project_ticket", lambda **kw: seen.update(kw))
    r = client.post("/api/runs/a/retry", json={"reply": "x"})
    assert r.status_code == 200, r.get_json()
    assert seen["resume_session"] is None and "removed or archived" in seen["note"]  # R12-01


# ── Codex build inspection 13 (PVST-R13-01) ────────────────────────────────

def test_status_change_copy_withholds_a_confidential_title(cs, monkeypatch):
    app_mod, mod, client, log, events, tmp = cs
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "project_key": "demo",
                    "issue_identifier": "T-1", "confidential": True, "issue_title": "Secret deal"})
    monkeypatch.setattr(app_mod, "_records_unsafe", lambda: "state/ moved outside the checkout")
    assert client.patch("/api/runs/a/status", json={"status": "archived"}).status_code == 200
    copied = records(log)[-1]
    assert copied["status"] == "archived" and "issue_title" not in copied  # R13-01
    assert app_mod._sanitize_record({"issue_title": "x", "linear_issue_id": ISSUE}) == {"issue_title": "x", "linear_issue_id": ISSUE}


# ── Codex build inspection 14 (PVST-R14-01) ────────────────────────────────

def test_has_reply_ignores_protocol_fallback():
    import app as app_mod
    assert not app_mod._has_reply(json.dumps({"type": "system", "subtype": "init", "session_id": "s"}))
    assert not app_mod._has_reply('{"type":"thread.started","thread_id":"t"}\n{"type":"turn.completed"}')
    assert not app_mod._has_reply("") and app_mod._has_reply("Done: added the button.")


@pytest.mark.parametrize("lines", [[{"type": "system", "subtype": "init", "session_id": SID}],
                                   [{"type": "result", "result": "", "session_id": SID}]])
def test_resumed_dispatch_with_no_reply_is_an_error(cs, monkeypatch, lines):
    app_mod, mod, client, log, events, tmp = cs
    transcript(app_mod.ROOT)
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID})
    monkeypatch.setattr(app_mod, "_run_grouped", lambda *a, **k: None)
    procs = stub(app_mod, monkeypatch, lines, rc=0)
    issue = {"id": ISSUE, "identifier": "T-1", "title": "t", "description": ""}
    mod._dispatch_issue_counted(issue, {"agent": {"backend": "claude"}}, app_mod.socketio)
    assert len(procs) == 1 and records(log)[-1]["status"] == "error"  # R14-01


# ── DeepSeek build inspection 1 (DSI-01..02) ───────────────────────────────

def test_project_resume_with_no_reply_is_an_error(cs, demo, monkeypatch):
    app_mod, mod, client, log, events, tmp = cs
    subprocess.run(["git", "-C", str(demo), "-c", "user.name=t", "-c", "user.email=t@example.com",
                    "commit", "-q", "--allow-empty", "-m", "init"], check=True)  # a worktree needs a HEAD
    monkeypatch.setattr(project_runs, "run_agent", lambda *a, **k: ([json.dumps({"type": "system", "subtype": "init",
                                                                                "session_id": SID})], "", 0, False))
    monkeypatch.setattr(app_mod, "_project_cmd", lambda *a: ["true"])
    monkeypatch.setattr(project_runs, "post_run", lambda *a, **k: {})
    out = app_mod._run_project_ticket(project_key="demo", ident="T-1", agent="claude", prompt="p", title="t",
                                      run_id="pr", linear_issue_id=ISSUE, task_id="pr", launch_gen=0,
                                      resume_session=SID)
    assert out["status"] == "error" and "no reply" in out["error"]  # DSI-01


def test_a_dropped_queued_retry_still_names_the_session(cs, monkeypatch):
    app_mod, mod, client, log, events, tmp = cs
    f = transcript(app_mod.ROOT)
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID})
    calls = []
    monkeypatch.setattr(app_mod, "_card_admitted", lambda iid, gen: (calls.append(1), len(calls) == 1)[1])  # dropped at the worker
    stub(app_mod, monkeypatch)
    assert client.post("/api/runs/a/retry", json={"reply": "x"}).status_code == 200
    assert records(log)[-1]["status"] == "cancelled" and custom_titles(f) == ["t"]  # DSI-02
