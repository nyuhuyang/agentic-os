"""Antigravity quota parsing and background cache tests (no Flask import)."""

import concurrent.futures
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runner"))
import usage_reader as u


SAMPLE = (
    "Gemini Models\tWeekly Limit Remaining\t84%\t2026-09-30T11:59:45Z\n"
    "Claude and GPT models\tWeekly Limit Remaining\t100%\t2026-09-30T12:21:05Z\n"
)


@pytest.fixture(autouse=True)
def reset_agy_cache():
    with u._agy_lock:
        u._agy_groups = {}
        u._agy_attempt_at = 0.0
        u._agy_error = None
        u._agy_refreshing = False
    yield
    assert not u._agy_refreshing
    with u._agy_lock:
        u._agy_groups = {}
        u._agy_attempt_at = 0.0
        u._agy_error = None
        u._agy_refreshing = False


def _wait_for_refresh():
    deadline = time.monotonic() + 2
    while u._agy_refreshing and time.monotonic() < deadline:
        threading.Event().wait(0.01)
    assert not u._agy_refreshing


def _due_again():
    with u._agy_lock:
        u._agy_attempt_at = time.monotonic() - u._AGY_CACHE_TTL_S


def test_parse_real_output():
    groups = u.parse_agy_usage(SAMPLE)
    assert groups["gemini"] == {
        "remaining_pct": 84,
        "resets_at": datetime(2026, 9, 30, 11, 59, 45, tzinfo=timezone.utc),
    }
    assert groups["claude_gpt"]["remaining_pct"] == 100
    assert groups["claude_gpt"]["resets_at"].tzinfo is not None


def test_parse_skips_malformed_and_unknown_lines():
    text = "bad\nUnknown\tWeekly Limit Remaining\t15%\tbad\n" + SAMPLE
    assert u.parse_agy_usage(text) == u.parse_agy_usage(SAMPLE)
    assert u.parse_agy_usage("Gemini Models\tWeekly\tnope\t2026-09-30T11:59:45Z") == {}
    assert u.parse_agy_usage("") == {}


def test_parse_bad_timestamp_keeps_clamped_percentage():
    groups = u.parse_agy_usage(
        "gEmInI Models\tWeekly Limit Remaining\t110%\tbad\n"
        "CLAUDE and GPT models\tWeekly Limit Remaining\t-3%\tbad\n"
    )
    assert groups == {
        "gemini": {"remaining_pct": 100, "resets_at": None},
        "claude_gpt": {"remaining_pct": 0, "resets_at": None},
    }


def test_cold_cache_returns_immediately_while_fetch_blocks():
    entered = threading.Event()
    release = threading.Event()

    def fetch():
        entered.set()
        assert release.wait(2)
        return u.parse_agy_usage(SAMPLE), None

    try:
        start = time.monotonic()
        assert u.load_agy_usage(fetch) == ({}, None)
        assert time.monotonic() - start < 0.5
        assert entered.wait(1)
    finally:
        release.set()
        _wait_for_refresh()
    groups, error = u.load_agy_usage(fetch)
    assert error is None
    assert set(groups) == {"gemini", "claude_gpt"}
    groups["gemini"]["remaining_pct"] = 0
    assert u.load_agy_usage(fetch)[0]["gemini"]["remaining_pct"] == 84


def test_concurrent_loads_start_only_one_fetch():
    entered = threading.Event()
    release = threading.Event()
    calls = []

    def fetch():
        calls.append(1)
        entered.set()
        assert release.wait(2)
        return u.parse_agy_usage(SAMPLE), None

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            results = list(pool.map(lambda _: u.load_agy_usage(fetch), range(10)))
        assert entered.wait(1)
        assert results == [({}, None)] * 10
        assert len(calls) == 1
    finally:
        release.set()
        _wait_for_refresh()


def test_failed_fetch_keeps_previous_groups():
    u.load_agy_usage(lambda: (u.parse_agy_usage(SAMPLE), None))
    _wait_for_refresh()
    _due_again()
    u.load_agy_usage(lambda: ({}, "exit_1"))
    _wait_for_refresh()
    groups, error = u.load_agy_usage()
    assert set(groups) == {"gemini", "claude_gpt"}
    assert error == "exit_1"


def test_partial_fetch_keeps_missing_group_and_reports_it():
    u.load_agy_usage(lambda: (u.parse_agy_usage(SAMPLE), None))
    _wait_for_refresh()
    previous = u.load_agy_usage()[0]["claude_gpt"]
    _due_again()
    u.load_agy_usage(lambda: ({"gemini": {"remaining_pct": 70, "resets_at": None}}, None))
    _wait_for_refresh()
    groups, error = u.load_agy_usage()
    assert groups["gemini"]["remaining_pct"] == 70
    assert groups["claude_gpt"] == previous
    assert error == "partial_claude_gpt"


def test_one_group_from_cold_cache_reports_missing_group():
    u.load_agy_usage(lambda: ({"claude_gpt": {"remaining_pct": 99, "resets_at": None}}, None))
    _wait_for_refresh()
    assert u.load_agy_usage()[1] == "partial_gemini"


def test_raising_fetch_clears_refresh_flag():
    def fetch():
        raise RuntimeError("CLI output must never be logged")

    u.load_agy_usage(fetch)
    _wait_for_refresh()
    assert u.load_agy_usage()[1] == "error"


def test_fetch_missing_binary(monkeypatch, tmp_path):
    monkeypatch.setattr(u.shutil, "which", lambda _: None)
    monkeypatch.setattr(u.Path, "home", lambda: tmp_path)
    assert u.fetch_agy_usage() == ({}, "not_installed")


@pytest.mark.parametrize("failure, expected", [
    (subprocess.TimeoutExpired("agy", 15), "timeout"),
    (None, "exit_1"),
])
def test_fetch_error_mappings(monkeypatch, tmp_path, failure, expected, caplog):
    binary = tmp_path / "agy"
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)
    monkeypatch.setattr(u.shutil, "which", lambda _: str(binary))

    def fake_run(*args, **kwargs):
        assert args[0] == [str(binary), "--log-file", "/dev/null", "-p", "/usage"]
        assert kwargs["stdin"] == subprocess.DEVNULL
        assert kwargs["capture_output"] is True
        assert kwargs["errors"] == "replace"
        if failure:
            raise failure
        return subprocess.CompletedProcess(args[0], 1, "SECRET CLI OUTPUT", "SECRET STDERR")

    monkeypatch.setattr(u.subprocess, "run", fake_run)
    assert u.fetch_agy_usage() == ({}, expected)
    assert "SECRET" not in caplog.text


def test_card_state_staleness():
    now = datetime.now(timezone.utc)
    fresh = {"fetched_at": now - timedelta(minutes=1), "resets_at": now + timedelta(days=1)}
    assert u.agy_card_state(fresh, now)[0] == "fresh"
    assert u.agy_card_state({**fresh, "resets_at": now - timedelta(seconds=1)}, now)[0] == "stale"
    assert u.agy_card_state({**fresh, "fetched_at": now - timedelta(minutes=16)}, now)[0] == "stale"
    assert u.agy_card_state({**fresh, "resets_at": None}, now)[0] == "fresh"
    assert u.agy_card_state(None, now)[0] == "missing"
