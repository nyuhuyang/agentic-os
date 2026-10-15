"""Plan 4b: shared JSON state survives concurrent writers from several processes."""

import json
import multiprocessing as mp
import sys
from pathlib import Path

RUNNER = Path(__file__).resolve().parents[1] / "runner"
sys.path.insert(0, str(RUNNER))
sys.path.insert(0, str(RUNNER.parent))

import state_io  # noqa: E402


def _bump_many(path: str, prefix: str, n: int) -> None:
    sys.path.insert(0, str(RUNNER))
    import state_io as s
    for i in range(n):
        with s.json_transaction(Path(path)) as data:
            data[f"{prefix}-{i}"] = i


def test_two_processes_lose_no_record(tmp_path):
    path = tmp_path / "task_state.json"
    procs = [mp.Process(target=_bump_many, args=(str(path), p, 60)) for p in ("a", "b")]
    for p in procs:
        p.start()
    for p in procs:
        p.join(30)
    data = json.loads(path.read_text())  # valid JSON
    assert len(data) == 120
    assert not list(tmp_path.glob(".task_state.json.*.tmp"))  # no stray temp files


def _tracker_updates(state_dir: str, issue_id: str, n: int, comment: bool) -> None:
    sys.path.insert(0, str(RUNNER))
    sys.path.insert(0, str(RUNNER.parent))
    from runner.modules.linear.local_tracker import LocalTracker
    t = LocalTracker(Path(state_dir))
    for i in range(n):
        if comment:
            t.post_comment(issue_id, f"comment {i}")
        else:
            t.update_issue(issue_id, description=f"desc {i}")


def _seed(state_dir: Path, ids: list[str]) -> None:
    state_io.write_json_atomic(state_dir / "tasks.json", {i: {"id": i, "state": "Todo"} for i in ids})


def test_local_tracker_updates_to_different_tickets_both_survive(tmp_path):
    _seed(tmp_path, ["one", "two"])
    procs = [mp.Process(target=_tracker_updates, args=(str(tmp_path), i, 40, False)) for i in ("one", "two")]
    for p in procs:
        p.start()
    for p in procs:
        p.join(30)
    tasks = json.loads((tmp_path / "tasks.json").read_text())
    assert tasks["one"]["description"] == "desc 39" and tasks["two"]["description"] == "desc 39"


def test_comment_and_state_change_on_same_ticket_both_survive(tmp_path):
    _seed(tmp_path, ["one"])
    procs = [mp.Process(target=_tracker_updates, args=(str(tmp_path), "one", 40, flag)) for flag in (True, False)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(30)
    issue = json.loads((tmp_path / "tasks.json").read_text())["one"]
    assert len(issue["comment_log"]) == 40 and issue["description"] == "desc 39"


def _run_skill_updates(job_state: str, n: int) -> None:
    sys.path.insert(0, str(RUNNER))
    import run_skill
    run_skill.JOB_STATE = Path(job_state)
    for i in range(n):
        run_skill._update_state(f"skill-{i}", {"started_at": "t", "status": "success"})


def test_run_skill_and_dashboard_writers_share_the_lock(tmp_path):
    job = tmp_path / "job_state.json"
    procs = [mp.Process(target=_run_skill_updates, args=(str(job), 40)),
             mp.Process(target=_bump_many, args=(str(job), "dash", 40))]
    for p in procs:
        p.start()
    for p in procs:
        p.join(30)
    data = json.loads(job.read_text())
    assert sum(k.startswith("skill-") for k in data) == 40 and sum(k.startswith("dash-") for k in data) == 40
