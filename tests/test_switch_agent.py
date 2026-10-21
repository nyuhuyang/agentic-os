"""AGE-113: a card can switch to another agent (e.g. when Claude's usage runs out). An explicit,
non-strict retry/reply with another agent starts a new session of that agent in the card's folder,
told the previous output, the reply and where the old conversation is; a quick reply never switches."""

import json
import os
import sqlite3
import sys
import time
from pathlib import Path

RUNNER = Path(__file__).resolve().parents[1] / "runner"
sys.path.insert(0, str(RUNNER))
sys.path.insert(0, str(RUNNER.parent))

from test_reset_gen import SID, capture_launches, env, on_disk, resumed, write_log  # noqa: E402,F401
from test_session_to_board import _new_card, records, stb  # noqa: E402,F401


def test_plain_card_switches_to_codex_with_the_previous_context(env, monkeypatch):
    app_mod, mod, client, log, events, _ = env
    monkeypatch.setattr(app_mod, "_process_table", lambda: {})
    on_disk(app_mod, "claude", SID)
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID,
                    "output": "claude's last answer"})
    cmds = capture_launches(app_mod, monkeypatch)
    r = client.post("/api/runs/a/retry", json={"agent": "codex", "reply": "keep going"})
    assert r.status_code == 200 and r.get_json()["agent"] == "codex"
    cmd = " ".join(cmds[0])
    assert cmds[0][0] == "codex" and not resumed(cmds[0]) and SID not in cmds[0]
    assert "claude's last answer" in cmd and "keep going" in cmd and "[Agent switch]" in cmd
    assert f"{SID}.jsonl" in cmd  # where the Claude conversation is


def test_quick_reply_never_switches(env, monkeypatch):
    app_mod, mod, client, log, events, _ = env
    monkeypatch.setattr(app_mod, "_process_table", lambda: {})
    on_disk(app_mod, "claude", SID)
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID})
    cmds = capture_launches(app_mod, monkeypatch)
    client.post("/api/runs/a/retry", json={"agent": "codex", "reply": "x", "strict": True})
    assert cmds and resumed(cmds[0]) and SID in cmds[0] and "codex" not in cmds[0][0]


def _codex_thread(tmp, sid, cwd):
    import projects as pj
    rollout = tmp / f"rollout-{sid}.jsonl"
    rollout.write_text("{}\n")
    os.utime(rollout, (time.time() - 600, time.time() - 600))
    db = sqlite3.connect(pj.CODEX_DB)
    db.execute("CREATE TABLE IF NOT EXISTS threads (id TEXT, cwd TEXT, name TEXT, title TEXT, first_user_message TEXT, "
               "updated_at INTEGER, tokens_used INTEGER, git_branch TEXT, source TEXT, archived INTEGER, "
               "archived_at INTEGER, rollout_path TEXT)")
    db.execute("INSERT INTO threads VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
               (sid, str(cwd), None, "t", "f", 1, 0, "main", "exec", 0, None, str(rollout)))
    db.commit()
    db.close()


def test_session_card_switches_in_its_folder_and_then_continues_the_new_session(stb, monkeypatch):
    app_mod, mod, client, log, tmp, proj, conf, launches = stb
    fake_run = app_mod.run_agent_process

    def run_codex(rid, cmd, **kw):
        out = fake_run(rid, cmd, **kw)
        return (*out[:4], "cx1", *out[5:])  # codex announces its new thread
    monkeypatch.setattr(app_mod, "run_agent_process", run_codex)
    rid, issue_id = _new_card(client, log)
    assert client.post(f"/api/runs/{rid}/retry", json={"reply": "x", "agent": "codex", "strict": True}).status_code == 409
    r = client.post(f"/api/runs/{rid}/retry", json={"reply": "over to you", "agent": "codex"})
    assert r.status_code == 200 and r.get_json()["agent"] == "codex", r.get_json()
    (l,) = launches
    cmd = " ".join(l["cmd"])
    assert l["cwd"] == str(proj) and "resume" not in l["cmd"] and "over to you" in cmd and "[Agent switch]" in cmd
    new = [x for x in records(log) if x["run_id"] == r.get_json()["run_id"]][-1]
    assert new["agent"] == "codex" and new["agent_session_id"] == "cx1" and "resume_session" not in new
    assert new["session_project"] == "demo"
    # the next plain reply continues the Codex session, in the same folder
    _codex_thread(tmp, "cx1", proj)
    app_mod._RECORDS_CACHE.clear()
    r2 = client.post(f"/api/runs/{new['run_id']}/retry", json={"reply": "and next"})
    assert r2.status_code == 200 and r2.get_json()["agent"] == "codex", r2.get_json()
    assert launches[1]["cwd"] == str(proj) and "resume" in launches[1]["cmd"] and "cx1" in launches[1]["cmd"]
