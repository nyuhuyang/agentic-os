"""Official Claude usage: a failed fetch keeps the last good reading and backs off (AGE-104)."""

import pytest

import app


USAGE = {"five_hour": {"utilization": 40, "resets_at": "2099-01-01T00:00:00Z"},
         "seven_day": {"utilization": 60, "resets_at": "2099-01-01T00:00:00Z"}}


@pytest.fixture
def clock(monkeypatch):
    t = [1000.0]
    monkeypatch.setattr(app.time, "monotonic", lambda: t[0])
    monkeypatch.setattr(app, "_claude_usage_cache", (0.0, None))
    monkeypatch.setattr(app, "_claude_usage_retry_at", 0.0)
    return t


def test_failed_fetch_keeps_last_reading_and_backs_off(clock, monkeypatch):
    replies = [USAGE, {}, {}]
    calls = []
    monkeypatch.setattr(app, "_fetch_claude_oauth_usage", lambda: calls.append(1) or replies.pop(0))

    assert app._load_claude_oauth_usage() == (USAGE, 0.0)
    clock[0] += 60                       # cache expired, fetch 429s
    assert app._load_claude_oauth_usage() == (USAGE, 60.0)
    clock[0] += 30                       # inside the retry wait: no new request
    assert app._load_claude_oauth_usage() == (USAGE, 90.0)
    assert len(calls) == 2

    windows = app._load_claude_official_windows()
    assert windows["quota_source"] == "official-claude-api"
    assert windows["window_7d"]["used_pct"] == 60
    assert windows["snapshot_age_seconds"] == 90
    assert windows["window_7d"]["display_line"].endswith(" ago")

    clock[0] += app._CLAUDE_USAGE_MAX_AGE_S  # past retry wait and max age, fetch fails again
    assert app._load_claude_oauth_usage() == ({}, 0.0)
    assert len(calls) == 3
