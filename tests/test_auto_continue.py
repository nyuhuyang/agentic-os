"""AGE-115: a run stopped by a Claude usage limit continues its own session once the limit resets."""

import json
import sys
import time
from pathlib import Path

RUNNER = Path(__file__).resolve().parents[1] / "runner"
sys.path.insert(0, str(RUNNER))
sys.path.insert(0, str(RUNNER.parent))

from test_reset_gen import ISSUE, SID, capture_launches, env, on_disk, resumed, write_log  # noqa: E402,F401

RESET = int(time.time()) + 3600
REJECTED = json.dumps({"type": "rate_limit_event", "session_id": SID, "rate_limit_info": {
    "status": "rejected", "resetsAt": RESET, "rateLimitType": "five_hour", "overageStatus": "rejected"}})


def test_limit_reset_is_read_only_from_a_rejected_claude_event():
    import project_runs as pr
    assert pr.limit_reset_of("claude", REJECTED) == RESET
    assert pr.limit_reset_of("claude", REJECTED.replace('"rejected", "resetsAt"', '"allowed_warning", "resetsAt"')) is None
    assert pr.limit_reset_of("codex", REJECTED) is None


def test_limited_run_is_scheduled_then_continues_its_session(env, monkeypatch):
    app_mod, mod, client, log, events, tmp = env
    monkeypatch.setattr(app_mod, "_process_table", lambda: {})
    armed = []
    monkeypatch.setattr(app_mod, "_arm_auto_continue", lambda rid, at: armed.append((rid, at)))
    on_disk(app_mod, "claude", SID)
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "agent_session_id": SID})
    app_mod.project_runs.note_agent_error("b", "claude", REJECTED)
    app_mod._write_run_log("_prompt", "error", "2026-10-21T00:00:00+00:00", 1.0, prompt="task",
                           error="You've hit your limit", run_id="b", parent_run_id="a", attempt=1,
                           linear_issue_id=ISSUE, agent="claude", task_id="T", agent_session_id=SID,
                           reset_generation=0)
    at = RESET + app_mod.AUTO_CONTINUE_GRACE_S
    assert armed == [("b", at)]
    assert json.loads(log.read_text().splitlines()[-1])["auto_continue_at"].startswith("2026-")
    assert app_mod.read_json(app_mod._auto_continue_path()) == {"b": at}

    cmds = capture_launches(app_mod, monkeypatch)
    app_mod._auto_continue("b")
    assert cmds and resumed(cmds[0]) and SID in cmds[0] and app_mod.AUTO_CONTINUE_REPLY in " ".join(cmds[0])
    assert app_mod.read_json(app_mod._auto_continue_path()) == {}

    # a cancelled run is the user's stop: never continued
    app_mod.project_runs.note_agent_error("c", "claude", REJECTED)
    app_mod._write_run_log("_prompt", "cancelled", "2026-10-21T00:00:00+00:00", 1.0, run_id="c",
                           linear_issue_id=ISSUE, agent="claude", task_id="T", agent_session_id=SID)
    assert armed == [("b", at)] and "c" not in app_mod.project_runs.LIMIT_RESETS


CODEX_LIMIT = json.dumps({"type": "turn.failed", "error": {"message":
    "You've hit your usage limit. Upgrade to Pro (https://chatgpt.com/explore/pro) or try again at 3:15 PM."}})


def test_codex_reset_is_read_from_its_try_again_at_message():
    from datetime import datetime
    import project_runs as pr
    now = datetime(2026, 10, 21, 9, 0)
    assert pr.codex_reset_of("You've hit your usage limit. … or try again at 3:15 PM.", now) \
        == datetime(2026, 10, 21, 15, 15).timestamp()
    assert pr.codex_reset_of("You've hit your usage limit. … or try again at Oct 22nd, 2026 9:05 AM.", now) \
        == datetime(2026, 10, 22, 9, 5).timestamp()
    assert pr.codex_reset_of("You've hit your usage limit. … or try again later.", now) is None
    assert pr.limit_reset_of("codex", CODEX_LIMIT) is not None


def test_limited_codex_run_continues_its_thread(env, monkeypatch):
    app_mod, mod, client, log, events, tmp = env
    monkeypatch.setattr(app_mod, "_process_table", lambda: {})
    armed = []
    monkeypatch.setattr(app_mod, "_arm_auto_continue", lambda rid, at: armed.append((rid, at)))
    on_disk(app_mod, "codex", SID)
    write_log(log, {"run_id": "a", "agent": "codex", "status": "review", "agent_session_id": SID})
    app_mod.project_runs.note_agent_error("b", "codex", CODEX_LIMIT)
    app_mod._write_run_log("_prompt", "error", "2026-10-21T00:00:00+00:00", 1.0, prompt="task",
                           error="You've hit your usage limit", run_id="b", parent_run_id="a", attempt=1,
                           linear_issue_id=ISSUE, agent="codex", task_id="T", agent_session_id=SID,
                           reset_generation=0)
    assert [rid for rid, _ in armed] == ["b"]
    assert armed[0][1] >= time.time() + app_mod.AUTO_CONTINUE_GRACE_S - 5  # never in the past: no hot loop
    cmds = capture_launches(app_mod, monkeypatch)
    app_mod._auto_continue("b")
    assert cmds and cmds[0][0] == "codex" and resumed(cmds[0]) and SID in cmds[0]
