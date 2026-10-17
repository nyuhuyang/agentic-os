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


def test_reset_card_shows_available_full_resets_and_expiry():
    """AGE-104: the third Claude card lists limit-reset grants like Codex's reset card."""
    block = {"eligible": True, "grants": [
        {"id": "g1", "label": "Full reset", "resets_total": 2, "resets_left": 1,
         "ends_at": "2099-10-30T12:00:00Z", "usable_now": False},
        {"id": "old", "label": "Full reset", "resets_total": 1, "resets_left": 1,
         "ends_at": "2000-01-01T00:00:00Z"},  # expired: ignored
    ]}
    card = app._claude_reset_card(block)
    assert card["title"] == "Full reset"
    assert (card["value"], card["value_suffix"], card["pct"]) == (1, " available", 50)
    assert card["reset"].startswith("Expires Oct ")
    assert card["display_line"].startswith("1 of 2 left · expires Oct ")

    empty = app._claude_reset_card({"eligible": False, "ineligible_reason": "no_grant"})
    assert (empty["value"], empty["display_line"]) == (0, "No reset available (no_grant)")
    assert app._claude_reset_card(None)["display_line"] == "No reset available"


def test_official_windows_put_the_reset_card_third(clock, monkeypatch):
    usage = {**USAGE, "cedar_ember": {"eligible": True, "grants": [
        {"id": "g1", "label": "Full reset", "resets_total": 1, "resets_left": 1, "ends_at": "2099-10-30T12:00:00Z"}]}}
    monkeypatch.setattr(app, "_fetch_claude_oauth_usage", lambda: usage)
    aux = app._load_claude_official_windows()["aux"]
    assert (aux["title"], aux["value"]) == ("Full reset", 1)
