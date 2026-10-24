"""AGE-128: the Activity chart splits each day's conversations into work, AgenticOS and other."""

from datetime import datetime, timedelta

import app


def _at(days_ago: int) -> str:
    return (datetime.now().astimezone() - timedelta(days=days_ago)).replace(hour=12).isoformat()


def _bucket(run: dict, keys=frozenset()) -> str:
    data = app.build_chart_data([{"started_at": _at(0), **run}], keys)
    (name,) = [n for n in ("agentic", "work", "other") if data[n][-1] == 1]
    return name


def test_agentic_os_and_unbound_prompts_are_agentic():
    assert _bucket({"skill": "_prompt", "project_key": "agentic-os"}) == "agentic"
    assert _bucket({"skill": "_prompt", "project_key": "Agentic-OS"}) == "agentic"
    assert _bucket({"skill": "_prompt", "session_project": "agentic-os"}) == "agentic"
    assert _bucket({"skill": "_prompt"}) == "agentic"
    assert _bucket({"skill": "_prompt", "project_key": "agentic-os", "confidential": True},
                   frozenset({"agentic-os"})) == "agentic"


def test_confidential_runs_are_work():
    assert _bucket({"skill": "_prompt", "project_key": "client-x", "confidential": True}) == "work"
    assert _bucket({"skill": "_prompt", "project_key": "Client-Y"}, frozenset({"client-y"})) == "work"


def test_everything_else_is_other():
    assert _bucket({"skill": "_prompt", "project_key": "hobby", "confidential": False}) == "other"
    assert _bucket({"skill": "yt-pipeline"}) == "other"


def test_days_sum_to_runs_and_out_of_window_or_bad_timestamps_drop():
    runs = [
        {"skill": "_prompt", "project_key": "agentic-os", "started_at": _at(2)},
        {"skill": "_prompt", "project_key": "client-x", "confidential": True, "started_at": _at(2)},
        {"skill": "_prompt", "project_key": "hobby", "started_at": _at(2)},
        {"skill": "_prompt", "project_key": "hobby", "started_at": _at(0)},
        {"skill": "_prompt", "project_key": "hobby", "started_at": _at(30)},  # one day past the window
        {"skill": "_prompt", "project_key": "hobby", "started_at": "not a date"},
        {"skill": "_prompt", "project_key": "hobby"},
    ]
    data = app.build_chart_data(runs)
    assert set(data) == {"labels", "agentic", "work", "other"}
    assert all(len(v) == 30 for v in data.values())
    per_day = [a + w + o for a, w, o in zip(data["agentic"], data["work"], data["other"])]
    assert per_day[-3] == 3 and per_day[-1] == 1 and sum(per_day) == 4


def test_confidential_keys_survive_a_broken_registry(monkeypatch):
    def broken(**_):
        raise app._projects.ProjectError("unreadable")
    monkeypatch.setattr(app._projects, "load_registry", broken)
    assert app._confidential_keys() == frozenset()
