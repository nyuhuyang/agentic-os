"""AGE-114: a card's memory across turns and agents. A resumed session gets the reply only; a new
session (a switch, a dispatch after one) gets the card's history from the run chain, whichever
agent ran each turn, within a budget; a dispatch never resumes a session another agent has
since moved past."""

import json
import sys
from pathlib import Path

RUNNER = Path(__file__).resolve().parents[1] / "runner"
sys.path.insert(0, str(RUNNER))
sys.path.insert(0, str(RUNNER.parent))

from test_reset_gen import ISSUE, SID, capture_launches, env, on_disk, resumed, write_log  # noqa: E402,F401


def _records(log):
    return [json.loads(line) for line in log.read_text().splitlines()]


def test_resume_sends_the_reply_only_and_records_it(env, monkeypatch):
    app_mod, mod, client, log, events, _ = env
    monkeypatch.setattr(app_mod, "_process_table", lambda: {})
    on_disk(app_mod, "claude", SID)
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID, "output": "first answer"},
              {"run_id": "b", "parent_run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID,
               "prompt": "do x", "reply": "do x", "output": "second answer"})
    cmds = capture_launches(app_mod, monkeypatch)
    r = client.post("/api/runs/b/retry", json={"reply": "and y"})
    assert r.status_code == 200, r.get_json()
    cmd = " ".join(cmds[0])
    assert resumed(cmds[0]) and SID in cmds[0] and "and y" in cmd
    assert "Original task" not in cmd and "first answer" not in cmd and "second answer" not in cmd
    new = [x for x in _records(log) if x["run_id"] == r.get_json()["run_id"]][-1]
    assert new["reply"] == "and y" and new["prompt"] == "and y"


def test_switch_hands_over_every_turn_and_every_transcript(env, monkeypatch):
    app_mod, mod, client, log, events, tmp = env
    monkeypatch.setattr(app_mod, "_process_table", lambda: {})
    on_disk(app_mod, "claude", SID)
    (tmp / "c_stream.jsonl").write_text("{}\n")  # dsh's readable transcript: the runner's stream log
    legacy = ("Original task:\ntask\n\nPrevious attempt output:\nA1\n\n[Human feedback]: R2\n\n"
              "Please continue or revise based on the feedback above.")
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID, "output": "A1"},
              {"run_id": "b", "parent_run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID,
               "prompt": legacy, "output": "A2"},  # written before records kept the reply
              {"run_id": "c", "parent_run_id": "b", "agent": "dsh", "status": "review", "agent_session_id": "d1",
               "prompt": "R3", "reply": "R3", "output": "A3"})
    cmds = capture_launches(app_mod, monkeypatch)
    r = client.post("/api/runs/c/retry", json={"agent": "codex", "reply": "R4"})
    assert r.status_code == 200 and r.get_json()["agent"] == "codex", r.get_json()
    assert cmds[0][0] == "codex" and not resumed(cmds[0])
    prompt = cmds[0][-1]
    order = ["Original task:\ntask", "Turn 1 (claude)", "A1", "Human: R2", "A2", "Turn 3 (dsh)", "Human: R3", "A3",
             "[Human feedback]: R4", "[Agent switch]: this task was being worked on by dsh"]
    assert [prompt.index(s) for s in order] == sorted(prompt.index(s) for s in order), prompt
    assert prompt.count("Original task") == 1  # flat, not nested
    assert f"claude: {app_mod._projects.session_file('claude', SID)}" in prompt
    assert f"dsh: {tmp / 'c_stream.jsonl'}" in prompt and "git status" in prompt


def test_handoff_budget_cuts_then_drops_the_oldest_turns(env, monkeypatch):
    app_mod, mod, client, log, events, _ = env
    monkeypatch.setattr(app_mod, "_HANDOFF_MAX", 20_000)
    rows, parent = [], None
    for i in range(6):
        rows.append({"run_id": f"r{i}", "agent": "claude", "status": "review", "prompt": f"reply {i}",
                     "reply": f"reply {i}", "output": f"<{i}>" + "x" * 3000,
                     **({"parent_run_id": parent} if parent else {})})
        parent = f"r{i}"
    rows[0]["prompt"] = "task"
    write_log(log, *rows)
    p = app_mod._handoff_prompt(app_mod._all_records()[-1], "go", [])
    assert "<5>" + "x" * 3000 in p and "<3>" + "x" * 3000 in p  # the last three turns whole
    assert "<2>" + "x" * 1497 + " … [1503 more characters cut]" in p  # older ones cut
    monkeypatch.setattr(app_mod, "_HANDOFF_MAX", 9_500)
    p = app_mod._handoff_prompt(app_mod._all_records()[-1], "go", [])
    assert "<0>" not in p and "<3>" in p and "earlier turns omitted" in p and p.startswith("Original task:\ntask")


def test_dispatch_never_resumes_a_session_another_agent_moved_past(env, monkeypatch):
    app_mod, mod, client, log, events, _ = env
    on_disk(app_mod, "claude", SID)
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID, "output": "A1"})
    assert app_mod._resumable_card_session(ISSUE, "claude", None) == (SID, None)
    write_log(log, {"run_id": "b", "parent_run_id": "a", "agent": "codex", "status": "review",
                    "agent_session_id": "cx1", "prompt": "over to you", "reply": "over to you", "output": "B1"})
    app_mod._RECORDS_CACHE.clear()
    assert app_mod._resumable_card_session(ISSUE, "claude", None) == (None, "the card's latest session belongs to codex")
    latest = app_mod._latest_card_session_record(ISSUE)
    p = app_mod._handoff_prompt(latest, "", [], "codex", task="ISS-1: t")
    assert p.startswith("Original task:\nISS-1: t") and "A1" in p and "Human: over to you" in p and "B1" in p
    assert "this task was being worked on by codex" in p and "Please continue the task." in p


def test_a_failed_resume_falls_back_to_a_new_session_with_the_history(env, monkeypatch):
    app_mod, mod, client, log, events, _ = env
    monkeypatch.setattr(app_mod, "_process_table", lambda: {})
    write_log(log, {"run_id": "a", "linear_issue_id": None, "agent": "claude", "status": "review",
                    "agent_session_id": SID, "output": "A1"})
    cmds = []

    def engine(rid, cmd, **kw):
        cmds.append(cmd)
        return ("", None, None, None, None, "", len(cmds) > 1)  # the resume fails, the new session works
    monkeypatch.setattr(app_mod, "run_agent_process", engine)
    r = client.post("/api/runs/a/retry", json={"reply": "go on"})
    assert r.status_code == 200, r.get_json()
    assert resumed(cmds[0]) and "A1" not in " ".join(cmds[0])
    assert not resumed(cmds[1]) and "A1" in " ".join(cmds[1]) and "go on" in " ".join(cmds[1])
