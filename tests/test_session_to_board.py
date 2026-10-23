"""Sessions back on the board (docs/exec-plans/active/2026-10-16-session-to-board.md): Resume puts a
session's card in Todo, replies continue exactly that session in its own folder under the
project's policy, plus the badge, model, listing, Linear Project and trash changes.
Fixture stores under tmp_path; fake project names only."""

import contextlib
import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
import yaml

RUNNER = Path(__file__).resolve().parents[1] / "runner"
sys.path.insert(0, str(RUNNER))
sys.path.insert(0, str(RUNNER.parent))

from test_reset_gen import ISSUE, env, write_log  # noqa: E402,F401  (env: fixture)

SID = "c1"


def claude_session(root, sid, cwd, age=600, entrypoint="cli", title="hello there"):
    import projects as pj
    d = root / "claude" / pj._slug(cwd)
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{sid}.jsonl"
    f.write_text(json.dumps({"type": "user", "cwd": str(cwd), "entrypoint": entrypoint,
                             "message": {"role": "user", "content": title}}) + "\n")
    os.utime(f, (time.time() - age, time.time() - age))
    return f


@pytest.fixture
def stb(env, tmp_path, monkeypatch):
    app_mod, mod, client, log, events, tmp = env
    import projects as pj
    proj, conf = tmp_path / "proj", tmp_path / "conf"
    for p in (proj, conf):
        p.mkdir()
        subprocess.run(["git", "init", "-q", str(p)], check=True)
    reg = tmp_path / "projects.yaml"
    reg.write_text(yaml.safe_dump({"projects": {"demo": {"path": str(proj), "confidential": False},
                                                "secret": {"path": str(conf), "confidential": True}}}))
    monkeypatch.setattr(pj, "REGISTRY_PATH", reg)
    monkeypatch.setattr(pj, "CLAUDE_PROJECTS", tmp_path / "claude")
    monkeypatch.setattr(pj, "CODEX_DB", tmp_path / "state_5.sqlite")
    monkeypatch.setattr(pj, "WORKTREE_ROOT", tmp_path / "wt")
    monkeypatch.setattr(pj, "CARD_LOCK_DIR", tmp_path / "card-locks")
    monkeypatch.setattr(app_mod, "_running_jobs", {})
    monkeypatch.setattr(app_mod, "_running_procs", {})
    monkeypatch.setattr(app_mod, "_SESSION_CLAIMS", {})
    monkeypatch.setattr(app_mod, "_INFLIGHT", app_mod._INFLIGHT)
    monkeypatch.setattr(app_mod, "_records_unsafe", lambda: None)
    monkeypatch.setattr(app_mod, "_linear_dispatched", {})
    monkeypatch.setattr(app_mod, "_FINALIZING", set())  # other tests' stubbed workers never write records
    monkeypatch.setattr(app_mod, "_process_table", lambda: {})  # never the host's processes
    monkeypatch.setattr(app_mod, "_DSH_SESSIONS", tmp_path / "dsh" / "sessions")
    app_mod._RECORDS_CACHE.clear()
    claude_session(tmp_path, SID, proj)
    launches = []

    def fake_run(rid, cmd, **kw):
        launches.append({"rid": rid, "cmd": cmd, **kw})
        import project_runs
        project_runs.REPLIED.add(rid)  # what the stream reader notes for a real reply (R16-01)
        return "done", 10, 20, "claude-opus-5-5[1m]", SID, "", True
    monkeypatch.setattr(app_mod, "run_agent_process", fake_run)
    return app_mod, mod, client, log, tmp, proj, conf, launches


def records(log):
    return [json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []


def to_board(client, key="demo", sid=SID, agent="claude"):
    import app as app_mod
    app_mod._RECORDS_CACHE.clear()  # same-second appends can keep (mtime, size) ambiguous in tests
    return client.post(f"/api/projects/{key}/sessions/{agent}/{sid}/to-board")


def tasks(tmp):
    return json.loads((tmp / "tasks.json").read_text())


# ── §2 to-board ──────────────────────────────────────────────────────────────

def test_to_board_without_a_card_creates_a_todo_issue_bound_to_the_session(stb):
    app_mod, mod, client, log, tmp, proj, conf, launches = stb
    r = to_board(client)
    assert r.status_code == 200 and r.get_json()["created"]
    issue_id = r.get_json()["issue_id"]
    issue = tasks(tmp)[issue_id]
    assert issue["state"] == "Todo" and issue["labels"] == ["project:demo"] and issue["title"] == "hello there"
    assert issue["preferred_agent"] == "claude"  # agent marker, as the "+" form (STB-040)
    (rec,) = [x for x in records(log) if x.get("linear_issue_id") == issue_id]
    assert rec["status"] == "todo" and rec["agent_session_id"] == SID and rec["source"] == "session"
    assert rec["resume_session"] == {"agent": "claude", "id": SID, "project_key": "demo", "gen": 0}
    assert rec["issue_identifier"] == issue["identifier"] and rec["to_board"]
    latest = client.get("/api/runs/latest-by-issue").get_json()[issue_id]
    assert latest["resume_ok"] and latest["resume_agent"] == "claude"
    detail = client.get(f"/api/runs/{rec['run_id']}").get_json()
    assert detail["resume_ok"] and detail["session_cwd"] == str(proj) and detail["in_use_elsewhere"] is None
    assert to_board(client).get_json()["issue_id"] == issue_id  # a second Resume finds that card


def test_to_board_on_a_found_card_moves_it_to_todo_and_keeps_its_history(stb):
    app_mod, mod, client, log, tmp, proj, conf, launches = stb
    write_log(log, {"run_id": "r0", "agent": "claude", "status": "review", "agent_session_id": SID},
              {"run_id": "r1", "agent": "claude", "status": "review", "agent_session_id": "other",
               "output": "earlier answer"},
              {"run_id": "r2", "agent": "claude", "status": "review", "agent_session_id": "other",
               "interactive_ended": True})
    r = to_board(client)
    assert r.status_code == 200 and r.get_json() == {"ok": True, "run_id": "r1", "issue_id": ISSUE, "created": False}
    assert tasks(tmp)[ISSUE]["state"] == "Todo"
    import reset_gen
    assert reset_gen.current(ISSUE) == 1
    rec = records(log)[-1]
    assert rec["run_id"] == "r1" and rec["status"] == "todo" and rec["output"] == "earlier answer"  # STB-016/035
    assert rec["agent_session_id"] == SID and rec["resume_session"]["gen"] == 1 and rec["to_board"]  # STB-046


def test_to_board_refuses_a_running_or_claimed_session_and_changes_nothing(stb):
    app_mod, mod, client, log, tmp, proj, conf, launches = stb
    write_log(log, {"run_id": "r0", "agent": "claude", "status": "review", "agent_session_id": SID})
    before = (log.read_text(), tasks(tmp))
    app_mod._SESSION_CLAIMS["x"] = ("claude", SID)
    assert to_board(client).status_code == 409
    app_mod._SESSION_CLAIMS.clear()
    app_mod._running_jobs["j"] = {"linear_issue_id": ISSUE, "state": "running", "agent": "claude"}
    assert to_board(client).status_code == 409  # the card has an in-flight run (STB-057)
    assert (log.read_text(), tasks(tmp)) == before


def test_to_board_refuses_sessions_outside_the_project_and_missing_dsh(stb):
    app_mod, mod, client, log, tmp, proj, conf, launches = stb
    claude_session(tmp, "far", tmp / "elsewhere")
    assert to_board(client, sid="far").status_code == 404
    assert to_board(client, agent="dsh").status_code == 404


def dsh_session(app_mod, sid, cwd, *, compressed=False, parent=None):
    project_dir = "--" + str(cwd).replace("/", "-").lstrip("-")[:251] + "--"
    directory = app_mod._DSH_SESSIONS / project_dir / sid
    directory.mkdir(parents=True)
    header = {"type": "session", "version": 4, "id": sid, "cwd": str(cwd),
              "createdAt": 1, "isSeeded": False, "delegationDepth": 0,
              **({"parentSession": parent} if parent else {})}
    events = [header, {"type": "user/message", "seq": 0, "time": 1,
                       "surfaceOp": "append", "data": {"role": "user", "id": "message-1",
                       "source": {"kind": "user"}, "content": [{"type": "text", "text": "first prompt"}]}},
              {"type": "session/title", "seq": 1, "time": 2,
               "data": {"title": "DeepSeek 原生标题", "messageSeqs": [], "source": {"kind": "user"}}}]
    lines = [(json.dumps(e, ensure_ascii=False) + "\n").encode() for e in events]
    # Real separately compressed frames: decoding just the first frame loses title/events.
    content = b"".join(app_mod._dsh_zstd(line) if compressed else line for line in lines)
    path = directory / ("session.v4.jsonl.zstd" if compressed else "session.v4.jsonl")
    path.write_bytes(content)
    os.utime(path, (time.time() - 600, time.time() - 600))
    return path


@pytest.mark.parametrize("compressed", [False, True])
def test_dsh_project_session_list_rename_resume_and_remove(stb, monkeypatch, compressed):
    app_mod, mod, client, log, tmp, proj, conf, launches = stb
    import projects as pj
    monkeypatch.setattr(app_mod, "_request_commit_pass", lambda jobs: None)
    monkeypatch.setattr(pj, "SESSION_TRASH", tmp / "trash")
    sid = "session-dsh-project"
    path = dsh_session(app_mod, sid, proj, compressed=compressed)
    dsh_session(app_mod, "session-outside", tmp / "proj-other")
    dsh_session(app_mod, "session-child", proj, parent=sid)
    base = f"/api/projects/demo/sessions/dsh/{sid}"
    listed = client.get("/api/projects").get_json()["projects"][0]["sessions"]
    row, = [s for s in listed if s["agent"] == "dsh"]
    assert row["id"] == sid and row["title"] == "DeepSeek 原生标题"
    assert sid in row["resume"] and "dsh" in row["resume"]
    before, mtime = path.read_bytes(), path.stat().st_mtime_ns
    assert client.post(base + "/rename", json={"title": "新名字"}).status_code == 200
    assert path.read_bytes().startswith(before) and path.stat().st_mtime_ns == mtime
    assert app_mod._find_session("dsh", sid)["native_title"] == "新名字"
    r = to_board(client, agent="dsh", sid=sid)
    assert r.status_code == 200, r.get_json()
    rid = r.get_json()["run_id"]
    intent = app_mod._valid_intent(app_mod._latest_record(rid))
    assert intent["agent"] == "dsh" and intent["id"] == sid
    reply = client.post(f"/api/runs/{rid}/retry", json={"reply": "continue exactly here"})
    assert reply.status_code == 200, reply.get_json()
    launch, = launches
    assert launch["cwd"] == str(proj) and launch["stream"] == "dsh"
    assert launch["cmd"][-4:] == ["--session-id", sid, "--", "continue exactly here"]
    assert app_mod._card_session(r.get_json()["issue_id"], "dsh")[0] == sid
    assert client.post(base + "/rename", json={"title": "card and native title"}).status_code == 200
    assert app_mod._find_session("dsh", sid)["native_title"] == "card and native title"
    assert client.post(base + "/remove").status_code == 200
    assert not path.exists() and app_mod._find_session("dsh", sid) is None
    assert list((tmp / "trash" / "dsh").rglob(path.name))
    assert client.post(base + "/to-board").status_code == 404


def test_dsh_session_writes_refuse_live_external_owner_and_store_escape(stb):
    import fcntl
    app_mod, mod, client, log, tmp, proj, conf, launches = stb
    sid = "session-native-lock"
    path = dsh_session(app_mod, sid, proj)
    base = f"/api/projects/demo/sessions/dsh/{sid}"
    before = path.read_bytes()
    with (path.parent / "session.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert client.post(base + "/rename", json={"title": "blocked"}).status_code == 409
        assert client.post(base + "/remove").status_code == 409
    assert path.read_bytes() == before
    app_mod._claim_session("dsh", sid, "claimed")
    assert client.post(base + "/rename", json={"title": "blocked"}).status_code == 409
    app_mod._release_session("claimed")
    assert to_board(client, key="secret", agent="dsh", sid=sid).status_code == 404
    escaped = path.parent.parent / "session-symlink"
    escaped.symlink_to(path.parent, target_is_directory=True)
    assert app_mod._find_session("dsh", "session-symlink") is None


def test_dsh_rename_short_write_rolls_back_and_preserves_torn_log(stb, monkeypatch):
    app_mod, mod, client, log, tmp, proj, conf, launches = stb
    sid = "session-rollback"
    path = dsh_session(app_mod, sid, proj)
    base = f"/api/projects/demo/sessions/dsh/{sid}"
    before, mtime = path.read_bytes(), path.stat().st_mtime_ns
    real_write = os.write
    with monkeypatch.context() as patch:
        patch.setattr(os, "write", lambda fd, data: real_write(fd, data[:5]))
        assert client.post(base + "/rename", json={"title": "must roll back"}).status_code == 500
    assert path.read_bytes() == before and path.stat().st_mtime_ns == mtime
    path.write_bytes(before + b'{"type":')
    os.utime(path, (time.time() - 600, time.time() - 600))
    assert client.post(base + "/rename", json={"title": "torn log"}).status_code == 400
    assert path.read_bytes() == before + b'{"type":'


def test_failed_move_restores_the_generation_and_appends_nothing(stb, monkeypatch):
    app_mod, mod, client, log, tmp, proj, conf, launches = stb
    write_log(log, {"run_id": "r0", "agent": "claude", "status": "review", "agent_session_id": SID})
    before = log.read_text()
    monkeypatch.setattr(mod, "move_to_todo", lambda iid: (_ for _ in ()).throw(RuntimeError("Linear refused")))
    r = to_board(client)
    import reset_gen
    assert r.status_code == 409 and "Linear refused" in r.get_json()["error"]
    assert reset_gen.current(ISSUE) == 0 and log.read_text() == before


def test_confidential_new_card_has_a_neutral_title_and_no_description(stb):
    app_mod, mod, client, log, tmp, proj, conf, launches = stb
    claude_session(tmp, "sess-conf-2", conf, title="secret plans")
    r = to_board(client, key="secret", sid="sess-conf-2")
    issue = tasks(tmp)[r.get_json()["issue_id"]]
    assert issue["title"] == "Session sess-con" and "secret plans" not in json.dumps(issue) and not issue["description"].strip("<!-> agent_backend:claude")


def test_two_concurrent_to_board_calls_make_one_card(stb):
    app_mod, mod, client, log, tmp, proj, conf, launches = stb
    import projects as pj
    with pj.session_lock("claude", SID):  # the first call holds it
        assert to_board(client).status_code == 409
    assert to_board(client).status_code == 200
    assert len([t for t in tasks(tmp).values() if t.get("labels")]) == 1


# ── §3 replies ───────────────────────────────────────────────────────────────

def _new_card(client, log):
    rid = to_board(client).get_json()["run_id"]
    return rid, [r for r in records(log) if r["run_id"] == rid][-1]["linear_issue_id"]


def test_reply_continues_the_same_session_in_its_folder_and_again_from_done(stb):
    app_mod, mod, client, log, tmp, proj, conf, launches = stb
    rid, issue_id = _new_card(client, log)
    r = client.post(f"/api/runs/{rid}/retry", json={"reply": "next step"})
    assert r.status_code == 200, r.get_json()
    (l,) = launches
    assert "--resume" in l["cmd"] and SID in l["cmd"] and "next step" in l["cmd"] and l["cwd"] == str(proj)
    assert "Original task" not in " ".join(l["cmd"])  # the reply only (§3.5)
    new = [x for x in records(log) if x["run_id"] == r.get_json()["run_id"]][-1]
    assert new["status"] == "review" and new["source"] == "session" and new["resume_session"]["id"] == SID
    assert new["model"] == "claude-opus-5-5[1m]" and new["token_cost_usd"] == round(30 / 1e6 * 20, 6)  # §8
    assert not app_mod._SESSION_CLAIMS and "project_key" not in str(app_mod._running_jobs)
    # marked Done, then replied again: the same session and folder again (SBR-001/008)
    assert client.patch(f"/api/runs/{new['run_id']}/status", json={"status": "success"}).status_code == 200
    r2 = client.post(f"/api/runs/{new['run_id']}/retry", json={"reply": "and more"})
    assert r2.status_code == 200 and len(launches) == 2 and launches[1]["cwd"] == str(proj)


def test_reply_rules_agent_empty_and_reset(stb):
    app_mod, mod, client, log, tmp, proj, conf, launches = stb
    rid, issue_id = _new_card(client, log)
    # a quick reply keeps its agent; a non-strict one switches (AGE-113, tests/test_switch_agent.py)
    assert client.post(f"/api/runs/{rid}/retry", json={"reply": "x", "agent": "codex", "strict": True}).status_code == 409
    assert client.post(f"/api/runs/{rid}/retry", json={"reply": " "}).status_code == 400
    # a drag back to Todo voids the intent: the next retry is today's path (Decision 11)
    client.patch(f"/api/linear/issues/local/{issue_id}", json={"state_name": "Todo"})
    assert app_mod._valid_intent([r for r in records(log) if r["run_id"] == rid][-1]) is None
    # the run-status reset drops the field as it copies the record (STB-004)
    client.patch(f"/api/runs/{rid}/status", json={"status": "todo"})
    assert "resume_session" not in records(log)[-1]
    assert launches == []


def test_reply_asks_when_the_session_is_in_use_elsewhere(stb):
    app_mod, mod, client, log, tmp, proj, conf, launches = stb
    rid, _ = _new_card(client, log)
    os.utime(next((tmp / "claude").rglob(f"{SID}.jsonl")), None)  # written just now, not by this card
    r = client.post(f"/api/runs/{rid}/retry", json={"reply": "x"})
    assert r.status_code == 409 and "2 minutes" in r.get_json()["in_use_elsewhere"] and launches == []
    assert client.post(f"/api/runs/{rid}/retry", json={"reply": "x", "confirm_in_use": True}).status_code == 200


def test_own_finished_run_is_not_elsewhere(stb):
    app_mod, mod, client, log, tmp, proj, conf, launches = stb
    target = {"agent": "claude", "id": SID, "path": next((tmp / "claude").rglob(f"{SID}.jsonl"))}
    os.utime(target["path"], None)
    assert app_mod.session_in_use(target, None, time.time()) is None  # written by our own run's end
    assert app_mod.session_in_use(target, None, None)
    import os as _os
    app_mod._process_table = lambda: {4242: (1, f"claude --resume {SID}"), 4243: (_os.getpid(), f"claude --resume {SID}"),
                                      4244: (1, f"x {SID}-other")}
    os.utime(target["path"], (time.time() - 600, time.time() - 600))
    assert "pid 4242" in app_mod.session_in_use(target, None, None)  # outside the runner tree; 4243 is ours
    app_mod._process_table = lambda: {4243: (_os.getpid(), f"claude --resume {SID}"), 4244: (1, f"x {SID}-other")}
    assert app_mod.session_in_use(target, None, None) is None  # own child, and no whole-id match
    app_mod._SESSION_CLAIMS["mine"] = ("claude", SID)
    os.utime(target["path"], (time.time() - 600, time.time() - 600))
    assert app_mod.session_in_use(target, "mine", None) is None  # own claim, by run id (STB-019)
    assert app_mod.session_in_use(target, "other", None)


def test_confidential_reply_is_sandboxed_or_refused_when_records_are_unsafe(stb, monkeypatch):
    app_mod, mod, client, log, tmp, proj, conf, launches = stb
    claude_session(tmp, "sess-conf-2", conf)
    rid = to_board(client, key="secret", sid="sess-conf-2").get_json()["run_id"]
    r = client.post(f"/api/runs/{rid}/retry", json={"reply": "x"})
    assert r.status_code == 200, r.get_json()
    assert "--settings" in launches[0]["cmd"]  # the confidential CLI (STB-011)
    rid2 = records(log)[-1]["run_id"]
    monkeypatch.setattr(app_mod, "_records_unsafe", lambda: "records outside")
    r = client.post(f"/api/runs/{rid2}/retry", json={"reply": "the secret reply"})
    assert r.status_code == 409 and len(launches) == 1  # refused before launch (STB-013)
    assert "the secret reply" not in log.read_text()


def test_ticket_session_in_its_worktree_goes_through_the_project_helper(stb, monkeypatch):
    app_mod, mod, client, log, tmp, proj, conf, launches = stb
    import projects as pj
    wt = pj.WORKTREE_ROOT / "demo" / "LOC-7"
    wt.mkdir(parents=True)
    claude_session(tmp, "w1", wt)
    write_log(log, {"run_id": "r0", "agent": "claude", "status": "review", "agent_session_id": "w1",
                    "project_key": "demo", "issue_identifier": "LOC-7"})
    app_mod._persist_binding([f"issue:{ISSUE}"], {"project_key": "demo", "issue_identifier": "LOC-7", "confidential": False})
    rid = to_board(client, sid="w1").get_json()["run_id"]
    seen = {}
    monkeypatch.setattr(app_mod, "_run_project_ticket", lambda **kw: seen.update(kw) or kw["ticket_hold"].close())
    assert client.post(f"/api/runs/{rid}/retry", json={"reply": "x"}).status_code == 200
    assert seen["ident"] == "LOC-7" and seen["resume_session"] == "w1" and seen["reuse_only"]
    assert seen["record_extra"]["resume_session"]["id"] == "w1" and launches == []


def test_cancel_of_a_session_reply_keeps_its_routing(stb, monkeypatch):
    app_mod, mod, client, log, tmp, proj, conf, launches = stb
    rid, _ = _new_card(client, log)
    seen = {}

    def cancelled_mid_run(run_id, cmd, **kw):
        seen["job"] = dict(app_mod._running_jobs[run_id])
        app_mod._cancel_generic(run_id, "Cancelled by user")
        return "partial", None, None, None, SID, "", False
    monkeypatch.setattr(app_mod, "run_agent_process", cancelled_mid_run)
    new = client.post(f"/api/runs/{rid}/retry", json={"reply": "x"}).get_json()["run_id"]
    assert "project_key" not in seen["job"]  # cancel/stall take the generic path (SBR-005)
    recs = [r for r in records(log) if r["run_id"] == new]
    assert [r["status"] for r in recs] == ["cancelled"]
    assert recs[0]["resume_session"]["id"] == SID and recs[0]["source"] == "session"
    assert app_mod._valid_intent(recs[0])  # the next reply routes through §3 again


def test_shutdown_cancels_generic_runs_with_their_record_and_refuses_launches(stb, monkeypatch):
    app_mod, mod, client, log, tmp, proj, conf, launches = stb
    monkeypatch.setattr(app_mod, "_SHUTTING_DOWN", threading.Event())
    monkeypatch.setattr(app_mod._projects, "stop_all", lambda: None)
    app_mod._running_jobs["g"] = {"run_id": "g", "skill": "_prompt", "started_at": "", "prompt": "p",
                                  "linear_issue_id": ISSUE, "record": {"agent": "claude", "task_id": "T"},
                                  "record_extra": {"resume_session": {"id": SID}, "source": "session"}}

    class Proc:
        pid = None
        def wait(self, timeout=None): return 0
        def kill(self): pass
    app_mod._running_procs["g"] = Proc()
    app_mod._stop_project_runs()
    (rec,) = [r for r in records(log) if r["run_id"] == "g"]
    assert rec["status"] == "cancelled" and rec["resume_session"] == {"id": SID} and not app_mod._running_jobs
    app_mod._running_jobs["h"] = {"run_id": "h"}
    killed = []
    monkeypatch.setattr(app_mod, "_kill_and_reap", killed.append)
    assert app_mod._register_proc("h", "proc") is False and killed == ["proc"]  # §3.7


def test_finalizing_runs_are_waited_for(stb, monkeypatch):
    app_mod, mod, client, log, tmp, proj, conf, launches = stb
    monkeypatch.setattr(app_mod, "_SHUTTING_DOWN", threading.Event())
    monkeypatch.setattr(app_mod._projects, "stop_all", lambda: None)
    app_mod._running_jobs["f"] = {"run_id": "f"}
    assert app_mod._end_job("f") and "f" in app_mod._FINALIZING
    app_mod._REAL_THREAD(target=lambda: (time.sleep(0.3), app_mod._write_run_log("_prompt", "review", "", 0.0, run_id="f")),
                         daemon=True).start()
    t0 = time.monotonic()
    app_mod._stop_project_runs()
    assert 0.2 < time.monotonic() - t0 < 5 and "f" not in app_mod._FINALIZING


# ── SBR-002/007 terminal folder ─────────────────────────────────────────────

def test_session_card_terminal_opens_in_the_session_folder(stb):
    app_mod, mod, client, log, tmp, proj, conf, launches = stb
    import projects as pj
    from runner.modules.pty import Terminal, _session_card_folder
    rid, issue_id = _new_card(client, log)
    rec = app_mod._latest_record(rid)
    t = Terminal(term_id="t1", kind="resume")
    project = _session_card_folder(t, pj.get_project("demo"), rec, {"agent": "claude", "session_id": SID})
    assert t.cwd == str(proj) and t.ticket is None and not project.confidential
    assert pj.card_busy("demo", rec["issue_identifier"], None)  # the card's ticket lock is held
    t.holds.close()
    client.patch(f"/api/linear/issues/local/{issue_id}", json={"state_name": "Todo"})  # reset (SBR-007)
    t2 = Terminal(term_id="t2", kind="resume")
    _session_card_folder(t2, pj.get_project("demo"), app_mod._latest_record(rid), {"agent": "claude", "session_id": SID})
    assert t2.cwd == str(proj)
    t2.holds.close()


# ── §7 badge ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("commits, dirty, verify, changed, expected", [
    ("", [], None, False, None),                    # question-only, no check: no badge
    ("", [], "fail", False, None),                  # question-only: verify does not run (AGE-117)
    ("", [], None, True, "main checkout changed"),
    ("abc", [], None, False, "no check"),           # changed files, no check: neutral
])
def test_badge_for_a_run_that_changed_nothing(monkeypatch, tmp_path, commits, dirty, verify, changed, expected):
    import project_runs as pr
    import projects as pj
    project = pj.Project(key="demo", path=tmp_path, verify="make test" if verify else "")
    monkeypatch.setattr(pr.projects, "uncommitted", lambda p, wt: list(dirty))
    monkeypatch.setattr(pr.projects, "_git", lambda wt, *a, **k: subprocess.CompletedProcess(a, 0, commits, ""))
    monkeypatch.setattr(pr.projects, "confine_for", lambda p, wt: None)
    monkeypatch.setattr(pr.projects, "load_binding", lambda p, i: {})
    monkeypatch.setattr(pr.projects, "committed_seeds", lambda p, wt, base: [])
    ran = []
    monkeypatch.setattr(pr.projects, "run_verify", lambda *a, **k: ran.append(1) or {"status": verify, "exit": 1, "duration_s": 0, "tail": ""})
    monkeypatch.setattr(pr, "closing_check", lambda p, e, b: {"main_checkout_changed": changed})
    binding = {"worktree": str(tmp_path), "issue_identifier": "LOC-1", "base_sha": "base"}
    result = pr.post_run(project, binding, "claude", "t", "fp", set(), start_sha="start")
    assert result.get("verify_badge") == expected
    assert bool(ran) == bool((commits or dirty) and verify) and ("verify" in result) == bool(ran)  # only a run that changed something


def test_verify_runs_when_the_run_committed(monkeypatch, tmp_path):
    import project_runs as pr
    import projects as pj
    project = pj.Project(key="demo", path=tmp_path, verify="make test")
    monkeypatch.setattr(pr.projects, "uncommitted", lambda p, wt: [])
    monkeypatch.setattr(pr.projects, "_git", lambda wt, *a, **k: subprocess.CompletedProcess(a, 0, "abc", ""))
    monkeypatch.setattr(pr.projects, "confine_for", lambda p, wt: None)
    monkeypatch.setattr(pr.projects, "load_binding", lambda p, i: {})
    monkeypatch.setattr(pr.projects, "committed_seeds", lambda p, wt, base: [])
    monkeypatch.setattr(pr.projects, "run_verify", lambda *a, **k: {"status": "fail", "exit": 1, "duration_s": 0, "tail": ""})
    monkeypatch.setattr(pr, "closing_check", lambda p, e, b: {"main_checkout_changed": False})
    binding = {"worktree": str(tmp_path), "issue_identifier": "LOC-1", "base_sha": "base"}
    result = pr.post_run(project, binding, "claude", "t", "fp", set(), start_sha="start")
    assert result["verify"]["status"] == "fail" and result["verify_badge"] == "fail"


# ── §8 model and cost ────────────────────────────────────────────────────────

def test_observed_model_and_cost():
    import app as app_mod
    init = json.dumps({"type": "system", "subtype": "init", "model": "claude-opus-5-5[1m]", "session_id": "s"})
    result = json.dumps({"type": "result", "result": "ok", "model": None, "usage": {"input_tokens": 1, "output_tokens": 1},
                         "modelUsage": {"claude-opus-5-5[1m]": {}}})
    assert app_mod._parse_project_output("claude", [init, result], "", 0)[3] == "claude-opus-5-5[1m]"
    assert app_mod._parse_project_output("claude", [result], "", 0)[3] == "claude-opus-5-5[1m]"  # modelUsage
    assert app_mod._compute_token_cost(1_000_000, 0, "claude-opus-5-5[1m]") == 20.0
    assert app_mod._compute_token_cost(1_000_000, 0, "gpt-5.4-mini") == app_mod._DEFAULT_PRICE  # no prefix match
    # Codex counts cache hits inside input_tokens; only uncached input is kept (AGE-116)
    done = json.dumps({"type": "turn.completed",
                       "usage": {"input_tokens": 7_307_325, "cached_input_tokens": 7_073_920, "output_tokens": 52_783}})
    assert app_mod._parse_agent_output("codex", done)[1:3] == (233_405, 52_783)


# ── §9 board-launched sessions ───────────────────────────────────────────────

def test_board_launched_headless_sessions_are_listed_with_their_card(stb):
    app_mod, mod, client, log, tmp, proj, conf, launches = stb
    import projects as pj
    claude_session(tmp, "sdk1", proj, entrypoint="sdk-cli")
    claude_session(tmp, "sdk2", proj, entrypoint="sdk-cli")
    project = pj.get_project("demo")
    assert "sdk1" not in {r["id"] for r in pj.project_sessions(project)}
    rows = {r["id"]: r for r in pj.project_sessions(project, {("claude", "sdk1")}, {("claude", "sdk1"): "AGE-102"})}
    assert rows["sdk1"]["label"] == "AGE-102" and "sdk2" not in rows
    assert pj.session_target(project, "claude", "sdk1", board_ids={("claude", "sdk1")})["title"] == "hello there"
    with pytest.raises(pj.SessionNotFound):
        pj.session_target(project, "claude", "sdk2", board_ids={("claude", "sdk1")})
    write_log(log, {"run_id": "b", "agent": "claude", "agent_session_id": "sdk1", "issue_identifier": "AGE-9"})
    (demo,) = [p for p in client.get("/api/projects").get_json()["projects"] if p["key"] == "demo"]
    assert {s["id"]: s.get("label") for s in demo["sessions"]}["sdk1"] == "AGE-9"
    mod.issues_cache[ISSUE] = {"id": ISSUE, "identifier": "AGE-9", "title": "牛熊判断"}
    write_log(log, {"run_id": "c", "agent": "claude", "agent_session_id": "sdk1"})  # label from the card itself
    (demo,) = [p for p in client.get("/api/projects").get_json()["projects"] if p["key"] == "demo"]
    row = {s["id"]: s for s in demo["sessions"]}["sdk1"]
    assert row["label"] == "AGE-9" and row["card_title"] == "牛熊判断"


def test_codex_exec_threads_only_when_the_board_ran_them(stb):
    app_mod, mod, client, log, tmp, proj, conf, launches = stb
    import projects as pj
    db = sqlite3.connect(pj.CODEX_DB)
    db.execute("CREATE TABLE threads (id TEXT, cwd TEXT, name TEXT, title TEXT, first_user_message TEXT, "
               "updated_at INTEGER, tokens_used INTEGER, git_branch TEXT, source TEXT, archived INTEGER, rollout_path TEXT)")
    db.executemany("INSERT INTO threads VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                   [("e1", str(proj), None, "t", "f", 1, 0, "main", "exec", 0, None),
                    ("e2", str(proj), None, "t", "f", 1, 0, "main", "exec", 0, None)])
    db.commit()
    db.close()
    ids = {r["id"] for r in pj.codex_sessions(pj.get_project("demo"), {("codex", "e1")})}
    assert ids == {"e1"}


# ── §10 Linear Projects ──────────────────────────────────────────────────────

class FakeLinear:
    def __init__(self):
        self.calls = []
    def find_project(self, name, team_id):
        self.calls.append(("find", name))
        return None
    def create_project(self, name, team_id):
        self.calls.append(("create", name))
        return f"p-{name}"
    def find_project_by_slug(self, slug):
        self.calls.append(("slug", slug))
        return "p-default"


def test_linear_project_mapping(stb):
    import runner.modules.linear as lin
    client = FakeLinear()
    assert lin.linear_project_id(client, "team", "demo", "slug") == "p-demo"
    assert lin.linear_project_id(client, "team", "demo", "slug") == "p-demo"  # cached
    assert client.calls == [("find", "demo"), ("create", "demo")]
    assert lin.linear_project_id(client, "team", "secret", "slug") == "p-default"  # no Project for confidential
    assert lin.linear_project_id(client, "team", None, "slug") == "p-default"
    assert lin.linear_project_id(client, "team", None, "") is None
    assert ("create", "secret") not in client.calls


# ── §11 trash, SBR-004 identifiers ───────────────────────────────────────────

def test_empty_trash_local_removes_only_canceled_and_numbers_are_not_reused(stb):
    app_mod, mod, client, log, tmp, proj, conf, launches = stb
    local = mod.get_local_tracker()
    a = local.create_issue("a", state_name="Canceled")
    b = local.create_issue("b")
    assert [i["id"] for i in client.get("/api/linear/trash").get_json()] == [a["id"]]
    r = client.post("/api/linear/trash/empty").get_json()
    assert r == {"ok": True, "archived": 1, "failed": {}}
    assert a["id"] not in tasks(tmp) and b["id"] in tasks(tmp) and ISSUE in tasks(tmp)
    import runner.modules.linear as lin
    assert a["id"] in lin.archived_ids()
    local.delete_issue(b["id"])
    assert local.create_issue("c")["identifier"] == "LOC-3"  # never LOC-1/LOC-2 again (SBR-004)


def test_identifier_floor_starts_above_run_log_and_worktrees(stb):
    app_mod, mod, client, log, tmp, proj, conf, launches = stb
    import projects as pj
    (pj.WORKTREE_ROOT / "demo" / "LOC-4").mkdir(parents=True)
    write_log(log, {"run_id": "x", "issue_identifier": "LOC-9"})
    assert mod.get_local_tracker().create_issue("n")["identifier"] == "LOC-10"


def test_empty_trash_linear_archives_and_reports_failures(stb, monkeypatch):
    app_mod, mod, client, log, tmp, proj, conf, launches = stb

    class Archiver:
        def archive_issue(self, iid):
            if iid == "bad":
                raise RuntimeError("rate limited")
    monkeypatch.setattr(mod, "_linear_client", lambda: (Archiver(), {}))
    mod._capability = {"available": True, "type": "linear"}
    mod.issues_cache.update({"good": {"id": "good", "identifier": "AGE-1", "state": "Canceled"},
                             "bad": {"id": "bad", "identifier": "AGE-2", "state": "Canceled"},
                             "live": {"id": "live", "identifier": "AGE-3", "state": "Todo"}})
    r = client.post("/api/linear/trash/empty").get_json()
    assert r["archived"] == 1 and r["failed"] == {"AGE-2": "rate limited"}
    assert set(mod.issues_cache) == {"bad", "live"}


# ── further plan checks ──────────────────────────────────────────────────────

def test_intent_survives_the_cards_own_tab_and_a_failed_reply_is_an_error(stb, monkeypatch):
    app_mod, mod, client, log, tmp, proj, conf, launches = stb
    rid, issue_id = _new_card(client, log)
    app_mod.record_interactive_ended(rid, SID)  # opening and closing the card's tab (STB-065)
    assert app_mod._valid_intent(app_mod._latest_record(rid))
    assert app_mod.session_in_use({"agent": "claude", "id": SID, "path": next((tmp / "claude").rglob(f"{SID}.jsonl"))},
                                  None, app_mod._own_activity_end(issue_id)) is None  # own audit (STB-037)
    monkeypatch.setattr(app_mod, "run_agent_process", lambda rid_, cmd, **kw: (launches.append(cmd), ("", 0, 0, None, None, "boom", False))[1])
    new = client.post(f"/api/runs/{rid}/retry", json={"reply": "x"}).get_json()["run_id"]  # no "strict" in the body
    rec = [r for r in records(log) if r["run_id"] == new][-1]
    assert len(launches) == 1 and rec["status"] == "error" and rec["issue_identifier"]  # strict, no fallback (STB-060/061)


def test_session_moved_away_starts_a_fresh_session_and_leaks_no_claim(stb, monkeypatch):
    """Since the 2026-10-16 plan (D3, R12-01): a session card whose session was removed starts a
    new session, saying why, instead of refusing the reply."""
    app_mod, mod, client, log, tmp, proj, conf, launches = stb
    rid, _ = _new_card(client, log)
    next((tmp / "claude").rglob(f"{SID}.jsonl")).unlink()
    seen = {}
    monkeypatch.setattr(app_mod, "_run_project_ticket", lambda **kw: seen.update(kw))
    assert client.post(f"/api/runs/{rid}/retry", json={"reply": "x"}).status_code == 200
    assert seen["resume_session"] is None and "removed or archived" in seen["note"]
    assert not app_mod._SESSION_CLAIMS and launches == []


def test_reply_holds_the_card_and_project_locks_and_posts_no_text_for_confidential(stb, monkeypatch):
    app_mod, mod, client, log, tmp, proj, conf, launches = stb
    import projects as pj
    claude_session(tmp, "sess-conf-3", conf)
    rid = to_board(client, key="secret", sid="sess-conf-3").get_json()["run_id"]
    rec = app_mod._latest_record(rid)
    seen = {}

    def probe(run_id, cmd, **kw):
        seen["ticket"] = pj.card_busy("secret", rec["issue_identifier"], None)
        try:
            with pj.project_lock("secret", exclusive=True, blocking=False):
                seen["project"] = False
        except pj.ProjectBusy:
            seen["project"] = True
        return "secret output", 1, 1, None, "sess-conf-3", "", True
    monkeypatch.setattr(app_mod, "run_agent_process", probe)
    r = client.post(f"/api/runs/{rid}/retry", json={"reply": "the private reply"})
    assert r.status_code == 200, r.get_json()
    assert seen == {"ticket": True, "project": True}  # STB-051/054
    comments = json.dumps(tasks(tmp)[rec["linear_issue_id"]].get("comment_log", []))
    assert "the private reply" not in comments and "secret output" not in comments  # STB-052


def test_main_checkout_session_of_a_bound_ticket_takes_the_generic_path(stb, monkeypatch):
    app_mod, mod, client, log, tmp, proj, conf, launches = stb
    import projects as pj
    (pj.WORKTREE_ROOT / "demo" / "LOC-7").mkdir(parents=True)
    write_log(log, {"run_id": "r0", "agent": "claude", "status": "review", "agent_session_id": SID,
                    "project_key": "demo", "issue_identifier": "LOC-7"})
    app_mod._persist_binding([f"issue:{ISSUE}"], {"project_key": "demo", "issue_identifier": "LOC-7", "confidential": False})
    rid = to_board(client).get_json()["run_id"]
    monkeypatch.setattr(app_mod, "_run_project_ticket", lambda **kw: pytest.fail("worktree route taken"))
    assert client.post(f"/api/runs/{rid}/retry", json={"reply": "x"}).status_code == 200
    assert launches[0]["cwd"] == str(proj)  # the session's own folder (STB-001/007)


def test_to_board_contends_with_a_drag_on_the_same_lock(stb):
    app_mod, mod, client, log, tmp, proj, conf, launches = stb
    from runner.modules.linear import reserve_card
    write_log(log, {"run_id": "r0", "agent": "claude", "status": "review", "agent_session_id": SID})
    with reserve_card(tasks(tmp)[ISSUE], ISSUE):  # a dispatch holds the card (STB-071)
        r = to_board(client)
    assert r.status_code == 409 and tasks(tmp)[ISSUE]["state"] == "In Review"


def test_linear_error_on_create_is_a_409_and_creates_nothing(stb, monkeypatch):
    app_mod, mod, client, log, tmp, proj, conf, launches = stb
    from linear_client import LinearError
    monkeypatch.setattr(mod, "create_session_issue", lambda *a: (_ for _ in ()).throw(LinearError("rate limit")))
    before = log.read_text() if log.exists() else ""
    r = to_board(client)
    assert r.status_code == 409 and "rate limit" in r.get_json()["error"]
    assert (log.read_text() if log.exists() else "") == before


class FakeLinearCreate(FakeLinear):
    def __init__(self, labels=True):
        super().__init__()
        self.labels = labels
    def ensure_label(self, team_id, name):
        self.calls.append(("label", name))
        return "lab-1" if self.labels else None
    def create_issue(self, team_id, title, desc, label_ids=None, project_id=None):
        self.calls.append(("create_issue", title, desc, tuple(label_ids or ()), project_id))
        return {"id": "lin-1", "identifier": "AGE-500", "title": title, "description": desc, "state": "Todo",
                "labels": ["project:demo"], "team_id": "team", "project_id": project_id}
    def set_issue_project(self, issue_id, project_id):
        self.calls.append(("set_project", issue_id, project_id))


def test_linear_session_issue_is_synchronous_with_label_marker_and_project(stb, monkeypatch):
    app_mod, mod, client, log, tmp, proj, conf, launches = stb
    import runner.modules.linear as lin
    fake = FakeLinearCreate()
    monkeypatch.setattr(lin, "_load_workflow_config", lambda: {"tracker": {"kind": "linear", "team_id": "team", "project_slug": "slug"}})
    monkeypatch.setattr(mod, "_linear_client", lambda: (fake, {"team_id": "team", "project_slug": "slug"}))
    mod._capability = {"available": True, "type": "linear"}
    r = to_board(client)
    assert r.status_code == 200 and r.get_json()["issue_id"] == "lin-1"
    (create,) = [c for c in fake.calls if c[0] == "create_issue"]
    assert create[3] == ("lab-1",) and create[4] == "p-demo" and "agent_backend: claude" in create[2]
    assert "lin-1" in mod.issues_cache and records(log)[-1]["issue_identifier"] == "AGE-500"
    fake_bad = FakeLinearCreate(labels=False)  # an unresolvable label creates nothing (STB-041)
    monkeypatch.setattr(mod, "_linear_client", lambda: (fake_bad, {}))
    claude_session(tmp, "c2", proj)
    assert to_board(client, sid="c2").status_code == 409 and not [c for c in fake_bad.calls if c[0] == "create_issue"]


def test_linear_session_issue_with_all_teams_uses_the_viewers_only_team(stb, monkeypatch):
    app_mod, mod, client, log, tmp, proj, conf, launches = stb
    import runner.modules.linear as lin
    fake = FakeLinearCreate()
    fake.fetch_teams = lambda: [{"id": "age", "key": "AGE", "name": "Agenticos"}]
    teams = []
    fake.ensure_label = lambda team_id, name: teams.append(team_id) or "lab-1"
    create = fake.create_issue
    fake.create_issue = lambda team_id, *a, **k: teams.append(team_id) or create(team_id, *a, **k)
    monkeypatch.setattr(lin, "_load_workflow_config", lambda: {"tracker": {"kind": "linear", "team_id": ""}})
    monkeypatch.setattr(mod, "_linear_client", lambda: (fake, {"team_id": "", "project_slug": "slug"}))
    mod._capability = {"available": True, "type": "linear"}
    r = to_board(client)
    assert r.status_code == 200 and teams == ["age", "age"]  # label + create; "All Teams" no longer blocks (AGE-122)
    assert [c for c in fake.calls if c[0] == "create_issue"]


def test_dispatch_moves_a_project_ticket_without_a_linear_project(stb, monkeypatch):
    app_mod, mod, client, log, tmp, proj, conf, launches = stb
    fake = FakeLinearCreate()
    monkeypatch.setattr(mod, "_linear_client", lambda: (fake, {"team_id": "team", "project_slug": "slug"}))
    mod._capability = {"available": True, "type": "linear"}
    mod._ensure_linear_project({"id": "i1", "team_id": "team", "project_id": ""}, "demo")
    mod._ensure_linear_project({"id": "i2", "team_id": "team", "project_id": "p-x"}, "demo")  # has one: untouched
    mod._ensure_linear_project({"id": "i3", "team_id": "team", "project_id": ""}, "secret")  # confidential: default
    assert [c for c in fake.calls if c[0] == "set_project"] == [("set_project", "i1", "p-demo"), ("set_project", "i3", "p-default")]


def test_archived_issues_stay_out_after_a_restart(stb):
    app_mod, mod, client, log, tmp, proj, conf, launches = stb
    import runner.modules.linear as lin
    lin._add_archived_ids(["gone"])
    with mod.get_local_tracker().raw_transaction() as raw:
        raw["gone"] = {"id": "gone", "state": "Canceled", "title": "old"}
    mod.issues_cache.clear()
    mod._capability = {"available": True, "type": "linear"}
    mod.start_background(app_mod.app, app_mod.socketio)  # the restart pre-fill (STB-029)
    assert "gone" not in mod.issues_cache and ISSUE in mod.issues_cache
    write_log(log, {"run_id": "r0", "agent": "claude", "status": "review", "agent_session_id": SID, "linear_issue_id": "gone"})
    assert app_mod._session_card("claude", SID) is None  # an archived card is "no card" (§2.3)


# ── build inspection 1 (SBI-001..007) ───────────────────────────────────────

def test_session_in_a_confidential_worktree_stays_confidential_without_its_card(stb):
    app_mod, mod, client, log, tmp, proj, conf, launches = stb
    import projects as pj
    wt = pj.WORKTREE_ROOT / "demo" / "LOC-8"
    wt.mkdir(parents=True)
    (pj.WORKTREE_ROOT / "demo" / ".meta").mkdir(parents=True, exist_ok=True)
    (pj.WORKTREE_ROOT / "demo" / ".meta" / "LOC-8.json").write_text(json.dumps({"confidential": True}))
    claude_session(tmp, "wt-secret-1", wt, title="sidecar secret")
    r = to_board(client, sid="wt-secret-1")
    issue = tasks(tmp)[r.get_json()["issue_id"]]
    assert issue["title"].startswith("Session ") and "sidecar secret" not in json.dumps(issue)  # SBI-001
    assert client.post(f"/api/runs/{r.get_json()['run_id']}/retry", json={"reply": "x"}).status_code == 200
    assert "--settings" in launches[-1]["cmd"]  # sandboxed although the registry says public


def test_found_card_record_marks_the_session_card(stb):
    app_mod, mod, client, log, tmp, proj, conf, launches = stb
    write_log(log, {"run_id": "r0", "agent": "claude", "status": "review", "agent_session_id": SID, "source": "linear"})
    to_board(client)
    rec = records(log)[-1]
    assert rec["source"] == "session" and rec["confidential"] is False  # SBI-003


def test_empty_trash_skips_a_card_moved_meanwhile_and_blocks_late_pushes(stb, monkeypatch):
    app_mod, mod, client, log, tmp, proj, conf, launches = stb
    local = mod.get_local_tracker()
    a = local.create_issue("a", state_name="Canceled")
    b = local.create_issue("b", state_name="Canceled")
    snapshot = mod.canceled_issues()
    local.update_issue_state(b["id"], "Todo")  # a Resume moved it after the snapshot
    monkeypatch.setattr(mod, "canceled_issues", lambda: snapshot)
    done, failed = mod.empty_trash()
    assert done == [a["id"]] and b["id"] in tasks(tmp)  # SBI-004
    mod.push_state(a["id"], "review")  # a run still finishing (SBI-005)
    assert a["id"] not in mod.issues_cache and a["id"] not in tasks(tmp)


def test_seed_committed_by_this_run_is_red_even_when_nothing_else_changed(monkeypatch, tmp_path):
    import project_runs as pr
    import projects as pj
    project = pj.Project(key="demo", path=tmp_path, verify="make test")
    monkeypatch.setattr(pr.projects, "uncommitted", lambda p, wt: [])
    monkeypatch.setattr(pr.projects, "_git", lambda wt, *a, **k: subprocess.CompletedProcess(a, 0, "", ""))
    monkeypatch.setattr(pr.projects, "confine_for", lambda p, wt: None)
    monkeypatch.setattr(pr.projects, "load_binding", lambda p, i: {})
    monkeypatch.setattr(pr.projects, "run_verify", lambda *a, **k: {"status": "pass", "exit": 0, "duration_s": 0, "tail": ""})
    monkeypatch.setattr(pr, "closing_check", lambda p, e, b: {"main_checkout_changed": False})
    binding = {"worktree": str(tmp_path), "issue_identifier": "LOC-1", "base_sha": "base"}
    monkeypatch.setattr(pr.projects, "committed_seeds", lambda p, wt, base: [".env"] if base == "start" else [])
    assert pr.post_run(project, binding, "claude", "t", "fp", set(), start_sha="start")["verify_badge"] == "seed committed"
    monkeypatch.setattr(pr.projects, "committed_seeds", lambda p, wt, base: [".env"] if base == "base" else [])
    out = pr.post_run(project, binding, "claude", "t", "fp", set(), start_sha="start")
    assert "verify_badge" not in out and out["seed_committed"] == [".env"]  # an older seed: history only (SBI-006)


def test_reply_refused_when_the_card_was_reset_during_admission(stb, monkeypatch):
    app_mod, mod, client, log, tmp, proj, conf, launches = stb
    rid, issue_id = _new_card(client, log)
    import reset_gen

    def reset_meanwhile(*a):
        reset_gen.bump(issue_id)  # another tab resets the card while this reply is admitted
        return None
    monkeypatch.setattr(app_mod, "session_in_use", reset_meanwhile)
    r = client.post(f"/api/runs/{rid}/retry", json={"reply": "x"})
    assert r.status_code == 409 and "reset" in r.get_json()["error"] and launches == []  # SBI-007
    assert not app_mod._SESSION_CLAIMS


# ── build inspection 2 (SBI-008..012) ───────────────────────────────────────

def test_confidential_history_of_a_session_survives_its_archived_card(stb):
    app_mod, mod, client, log, tmp, proj, conf, launches = stb
    write_log(log, {"run_id": "old", "agent": "claude", "status": "review", "agent_session_id": SID,
                    "linear_issue_id": "archived-card", "confidential": True})  # its card is gone
    r = to_board(client)
    issue = tasks(tmp)[r.get_json()["issue_id"]]
    assert issue["title"].startswith("Session ") and "hello there" not in json.dumps(issue)  # SBI-008
    assert client.post(f"/api/runs/{r.get_json()['run_id']}/retry", json={"reply": "x"}).status_code == 200
    assert "--settings" in launches[-1]["cmd"]


def test_reply_reads_policy_under_the_project_lock(stb, monkeypatch):
    app_mod, mod, client, log, tmp, proj, conf, launches = stb
    rid, _ = _new_card(client, log)
    order, real_lock, real_get = [], app_mod._projects.project_lock, app_mod._projects.get_project

    @contextlib.contextmanager
    def lock(key, *a, **k):
        order.append("lock")
        with real_lock(key, *a, **k):
            yield
    monkeypatch.setattr(app_mod._projects, "project_lock", lock)
    monkeypatch.setattr(app_mod._projects, "get_project", lambda *a, **k: (order.append("policy"), real_get(*a, **k))[1])
    assert client.post(f"/api/runs/{rid}/retry", json={"reply": "x"}).status_code == 200
    assert order[:2] == ["lock", "policy"] and order.count("lock") == 1  # one hold, handed to the worker (SBI-009)


def test_session_card_records_keep_their_project_and_session(stb, monkeypatch):
    app_mod, mod, client, log, tmp, proj, conf, launches = stb
    import projects as pj
    rid, _ = _new_card(client, log)
    assert app_mod._latest_record(rid)["session_project"] == "demo"  # SBI-010
    wt = pj.WORKTREE_ROOT / "demo" / "LOC-7"
    wt.mkdir(parents=True)
    claude_session(tmp, "w2", wt)
    write_log(log, {"run_id": "r0", "agent": "claude", "status": "review", "agent_session_id": "w2",
                    "project_key": "demo", "issue_identifier": "LOC-7"})
    app_mod._persist_binding([f"issue:{ISSUE}"], {"project_key": "demo", "issue_identifier": "LOC-7", "confidential": False})
    rid2 = to_board(client, sid="w2").get_json()["run_id"]
    new = client.post(f"/api/runs/{rid2}/retry", json={"reply": "x"}).get_json()["run_id"]  # the real helper fails early
    rec = [r for r in records(log) if r["run_id"] == new][-1]
    assert rec["status"] == "error" and rec["agent_session_id"] == "w2"  # kept without an observed id (SBI-011)


def test_tombstoned_cache_entries_never_reach_the_board(stb, monkeypatch):
    app_mod, mod, client, log, tmp, proj, conf, launches = stb
    import runner.modules.linear as lin
    lin._add_archived_ids(["gone"])
    mod._capability = {"available": True, "type": "linear"}
    mod.issues_cache["gone"] = {"state": "In Review"}  # an incomplete value with no id (SBI-012)
    mod.issues_cache["live"] = {"id": "live", "state": "Todo"}
    assert [i.get("id") for i in client.get("/api/linear/issues").get_json()] == ["live"]
    mod.push_state("gone", "review")
    assert mod.issues_cache["gone"] == {"state": "In Review"}  # untouched: no push for an archived card


# ── build inspection 3 (SBI-013..015) ───────────────────────────────────────

def test_worktree_terminal_keeps_the_records_confidential_flag(stb):
    app_mod, mod, client, log, tmp, proj, conf, launches = stb
    import projects as pj
    from runner.modules.pty import Terminal, _session_card_folder
    wt = pj.WORKTREE_ROOT / "demo" / "LOC-7"
    wt.mkdir(parents=True)
    claude_session(tmp, "w3", wt)
    app_mod._persist_binding([f"issue:{ISSUE}"], {"project_key": "demo", "issue_identifier": "LOC-7", "confidential": False})
    rec = {"linear_issue_id": ISSUE, "task_id": "T", "issue_identifier": "LOC-7", "confidential": True,
           "resume_session": {"project_key": "demo"}}
    t = Terminal(term_id="t3", kind="resume")
    original = pj.load_binding
    pj.load_binding = lambda p, i: {}
    try:
        project = _session_card_folder(t, pj.get_project("demo"), rec, {"agent": "claude", "session_id": "w3"})
    finally:
        pj.load_binding = original
        t.holds.close()
    assert t.ticket == "LOC-7" and project.confidential  # the worktree branch keeps the record's flag (SBI-013)


def test_to_board_reads_policy_under_the_project_lock(stb, monkeypatch):
    app_mod, mod, client, log, tmp, proj, conf, launches = stb
    order, real_lock, real_get = [], app_mod._projects.project_lock, app_mod._projects.get_project

    @contextlib.contextmanager
    def lock(key, *a, **k):
        order.append("lock")
        with real_lock(key, *a, **k):
            yield
        order.append("unlock")
    monkeypatch.setattr(app_mod._projects, "project_lock", lock)
    monkeypatch.setattr(app_mod._projects, "get_project", lambda *a, **k: (order.append("policy"), real_get(*a, **k))[1])
    monkeypatch.setattr(mod, "create_session_issue", (lambda real: lambda *a: (order.append("create"), real(*a))[1])(mod.create_session_issue))
    assert to_board(client).status_code == 200
    assert order[:2] == ["lock", "policy"] and order.index("create") < order.index("unlock")  # SBI-014


def test_observed_model_reaches_cancel_and_timeout_records(stb):
    app_mod, mod, client, log, tmp, proj, conf, launches = stb
    app_mod._OBSERVED_MODELS["m1"] = "claude-opus-5-5[1m]"
    app_mod._write_owner_record("m1", {"skill": "_prompt", "record": {"agent": "claude", "model": "claude-sonnet-4-6"}},
                                "cancelled", "Cancelled by user")
    assert records(log)[-1]["model"] == "claude-opus-5-5[1m]" and "m1" not in app_mod._OBSERVED_MODELS  # SBI-015


# ── DeepSeek build inspection (third-party; SBI-016..017) ───────────────────

def test_poll_keeps_a_card_created_during_its_fetch(stb, monkeypatch):
    app_mod, mod, client, log, tmp, proj, conf, launches = stb
    import types
    import runner.modules.linear as lin
    monkeypatch.setattr(lin, "_load_workflow_config",
                        lambda: {"tracker": {"kind": "linear", "api_key": "k", "team_id": "team"}, "polling": {"interval_ms": 1000}})

    class Client:
        def __init__(self, *a): pass
        def fetch_teams(self): return []
        def fetch_issues(self, states, team_id=None):
            # a Resume creates its card while this fetch is in flight
            mod.issues_cache["new"] = {"id": "new", "team_id": "team", "state": "Todo"}
            mod._fresh_ids["new"] = time.monotonic()
            return [{"id": "old", "identifier": "AGE-1", "state": "Todo", "labels": [], "team_id": "team"}]

    class Stop(Exception):
        pass
    monkeypatch.setitem(sys.modules, "linear_client", types.SimpleNamespace(LinearClient=Client))
    monkeypatch.setattr(lin.time, "sleep", lambda s: (_ for _ in ()).throw(Stop()))
    mod._capability = {"available": True, "type": "linear"}
    mod.issues_cache["before"] = {"id": "before", "team_id": "team", "state": "Todo"}  # created before the poll began
    mod._fresh_ids["before"] = time.monotonic() - 10
    mod.issues_cache["local-ph"] = {"id": "local-ph", "team_id": "team", "state": "Todo"}  # "+" placeholder, sync pending
    mod._fresh_ids["local-ph"] = time.monotonic()
    with pytest.raises(Stop):
        mod._polling_loop(app_mod.socketio)  # one iteration
    assert {"new", "old", "before", "local-ph"} <= set(mod.issues_cache)  # SBI-016/018
    assert "old" not in mod._fresh_ids and "before" in mod._fresh_ids


def test_tracker_patches_refuse_an_emptied_card(stb):
    app_mod, mod, client, log, tmp, proj, conf, launches = stb
    import runner.modules.linear as lin
    lin._add_archived_ids([ISSUE])
    assert client.patch(f"/api/linear/issues/local/{ISSUE}", json={"title": "x"}).status_code == 404
    assert client.patch(f"/api/linear/issues/{ISSUE}", json={"state_name": "Todo"}).status_code == 404
    import reset_gen
    assert reset_gen.current(ISSUE) == 0 and ISSUE not in mod.issues_cache  # SBI-017: nothing written back


def test_empty_trash_survives_an_id_less_cache_entry(stb, monkeypatch):
    app_mod, mod, client, log, tmp, proj, conf, launches = stb

    class Archiver:
        def archive_issue(self, iid): pass
    monkeypatch.setattr(mod, "_linear_client", lambda: (Archiver(), {}))
    mod._capability = {"available": True, "type": "linear"}
    mod.issues_cache["x1"] = {"state": "Canceled"}  # an older writer stored no id
    mod.push_state("x2", "cancelled")
    assert mod.issues_cache["x2"]["id"] == "x2"  # push_state never writes an id-less entry (SBI-019)
    r = client.post("/api/linear/trash/empty").get_json()
    assert r["archived"] == 2 and r["failed"] == {}


def test_to_board_of_an_older_session_names_the_terminal_holding_its_card(stb, monkeypatch):
    """Resume of session A while session B of the same card holds its live interactive terminal:
    the refusal names B's terminal; a headless run keeps the plain refusal (plan 2026-10-17, R6)."""
    app_mod, mod, client, log, tmp, proj, conf, launches = stb
    import runner.modules.linear as linear_mod
    import runner.modules.pty as pty_mod
    write_log(log, {"run_id": "r0", "agent": "claude", "status": "review", "agent_session_id": SID},
              {"run_id": "r1", "agent": "claude", "status": "review", "agent_session_id": "other"})
    before = (log.read_text(), tasks(tmp))
    monkeypatch.setattr(pty_mod, "TERMINALS", {})
    monkeypatch.setattr(linear_mod, "card_locked", lambda issue, issue_id: True)  # B's terminal holds the card
    monkeypatch.setitem(pty_mod.TERMINALS, "tB", pty_mod.Terminal(term_id="tB", kind="resume", pid=1, alive=True,
                                                                  card_key=ISSUE, agent="claude", session_id="other"))
    r = to_board(client)  # session A = SID
    assert r.status_code == 409 and r.get_json() == {"error": "still running", "code": "card_interactive", "term_id": "tB"}
    pty_mod.TERMINALS.clear()
    app_mod._running_jobs["j"] = {"linear_issue_id": ISSUE, "state": "running", "agent": "claude"}
    assert to_board(client).get_json() == {"error": "still running"}  # headless: unchanged
    assert (log.read_text(), tasks(tmp)) == before


# ── AGE-127: confidential sessions get local-only tasks while Linear is the tracker ──

@pytest.fixture
def stb_linear(stb, monkeypatch):
    app_mod, mod, client, log, tmp, proj, conf, launches = stb
    import linear_client
    import runner.modules.linear as lin
    calls = []

    class NoLinear:
        def __call__(self, *a, **k):
            return self

        def __getattr__(self, name):
            return lambda *a, **k: calls.append((name, a, k))

    monkeypatch.setattr(linear_client, "LinearClient", NoLinear())
    monkeypatch.setattr(lin, "_post_linear_comment_raw", lambda *a: calls.append(("comment_raw", a)) or True)
    monkeypatch.setenv("LINEAR_API_KEY", "dummy")
    monkeypatch.setattr(lin, "_load_workflow_config", lambda: {"tracker": {
        "kind": "linear", "api_key": "$LINEAR_API_KEY", "project_slug": "slug", "team_id": "team-a"}})
    monkeypatch.setattr(mod, "_capability", {"available": True, "type": "linear"})
    return stb, calls


def test_sidecar_confidential_session_gets_a_local_only_task_in_linear_mode(stb_linear):
    (app_mod, mod, client, log, tmp, proj, conf, launches), calls = stb_linear
    import projects as pj
    wt = pj.WORKTREE_ROOT / "demo" / "LOC-8"
    wt.mkdir(parents=True)
    (pj.WORKTREE_ROOT / "demo" / ".meta").mkdir(parents=True, exist_ok=True)
    (pj.WORKTREE_ROOT / "demo" / ".meta" / "LOC-8.json").write_text(json.dumps({"confidential": True}))
    claude_session(tmp, "wt-secret-2", wt, title="sidecar secret")
    r = to_board(client, sid="wt-secret-2")
    assert r.status_code == 200, r.get_json()
    assert tasks(tmp)[r.get_json()["issue_id"]]["local_only"] is True and calls == []


def test_history_confidential_session_gets_a_local_only_task_in_linear_mode(stb_linear):
    (app_mod, mod, client, log, tmp, proj, conf, launches), calls = stb_linear
    write_log(log, {"run_id": "old", "agent": "claude", "status": "review", "agent_session_id": SID,
                    "linear_issue_id": "archived-card", "confidential": True})
    r = to_board(client)
    assert r.status_code == 200, r.get_json()
    assert tasks(tmp)[r.get_json()["issue_id"]]["local_only"] is True and calls == []


def test_public_session_still_goes_to_linear(stb_linear):
    (app_mod, mod, client, log, tmp, proj, conf, launches), calls = stb_linear
    to_board(client)
    assert any(c[0] == "ensure_label" for c in calls)  # the public path is unchanged
