"""AGE-147: DeepSeek dual-currency spend and the $20 monthly budget."""

import json
from datetime import datetime, timedelta, timezone

import dsh_cli
import usage_reader as u

KEY = "sk-age147-test"


def _monitor(monkeypatch, tmp_path):
    import deepseek_monitor as m
    monkeypatch.setattr(m, "_DEEPSEEK_DIR", tmp_path)
    monkeypatch.setattr(m, "_USAGE_PATH", tmp_path / "usage.json")
    monkeypatch.setattr(m, "_LOCK_PATH", tmp_path / "usage.json.lock")
    monkeypatch.setattr(m, "resolve_api_key", lambda: KEY)
    return m


def _poll(m, monkeypatch, now, raw):
    monkeypatch.setattr(m, "_now", lambda: now)
    if raw is None:
        monkeypatch.setattr(m, "fetch_balance", lambda key=None: {"error": "down"})
        return m.update_usage()
    usd = float(raw.get("USD", 0.0))
    cny = float(raw.get("CNY", 0.0))
    payload = {
        "raw_balances": dict(raw),
        "balance_cny": cny,
        "balance_usd": usd,
        "balance_total_usd": round(usd + cny / 7.2, 4),
        "balance_total_cny": round(cny + usd * 7.2, 4),
        "currency": "CNY" if "CNY" in raw else "USD",
    }
    monkeypatch.setattr(m, "fetch_balance", lambda key=None: dict(payload))
    return m.update_usage()


def _legacy(monkeypatch, m, body):
    body.setdefault("key_fp", dsh_cli.key_fp(KEY))
    m._USAGE_PATH.write_text(json.dumps(body), encoding="utf-8")


def test_dual_currency_spend_counts_both(monkeypatch, tmp_path):
    m = _monitor(monkeypatch, tmp_path)
    t0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
    _poll(m, monkeypatch, t0, {"CNY": 100.0, "USD": 20.0})
    _poll(m, monkeypatch, t0 + timedelta(minutes=1), {"CNY": 90.0, "USD": 20.0})
    r = _poll(m, monkeypatch, t0 + timedelta(minutes=2), {"CNY": 90.0, "USD": 15.0})

    assert r["_schema"] == 2
    assert r["window_5h_cost"] == round(10 / 7.2 + 5, 4)
    assert r["window_5h_cost_cny"] == 46.0
    assert r["total_cost_usd"] == round(10 / 7.2 + 5, 4)
    assert r["total_cost_cny"] == 46.0
    assert r["month_cost"] == round(10 / 7.2 + 5, 4)
    assert r["balance"]["balance_total_usd"] == round(15 + 90 / 7.2, 4)
    assert r["balance"]["balance_total_cny"] == round(90 + 15 * 7.2, 4)
    assert r["balance_total_usd"] == r["balance"]["balance_total_usd"]
    assert r["balance_total_cny"] == r["balance"]["balance_total_cny"]


def test_negative_currency_balance_is_clamped_for_totals():
    import deepseek_monitor as m
    total_usd, total_cny = m._balance_totals({"raw_balances": {"CNY": -0.05, "USD": 19.83}})
    assert total_usd == 19.83
    assert total_cny == round(19.83 * 7.2, 4)


def test_many_small_decreases_match_one_large():
    import deepseek_monitor as m
    base = datetime(2026, 10, 1, tzinfo=timezone.utc)
    samples = [{"ts": base.isoformat(), "balance_cny": 1000.0}]
    for i in range(1, 3601):
        samples.append({
            "ts": (base + timedelta(seconds=i)).isoformat(),
            "balance_cny": round(1000.0 - 0.01 * i, 2),
        })
    usd, cny = m._spend_since(samples, base)
    assert cny == 36.0
    assert usd == round(36 / 7.2, 4)


def test_cumulative_rounding_does_not_drift(monkeypatch, tmp_path):
    m = _monitor(monkeypatch, tmp_path)
    base = datetime(2026, 10, 1, tzinfo=timezone.utc)
    _poll(m, monkeypatch, base, {"CNY": 100.0})
    balance = 100.0
    for i in range(100):
        balance -= 0.01
        r = _poll(m, monkeypatch, base + timedelta(minutes=i + 1), {"CNY": round(balance, 2)})
    assert r["total_cost_cny"] == 1.0
    assert r["total_cost_usd"] == round(1.0 / 7.2, 4)


def test_month_boundary_uses_sample_timestamp(monkeypatch, tmp_path):
    m = _monitor(monkeypatch, tmp_path)
    base = datetime(2026, 9, 30, 23, 50, tzinfo=timezone.utc)
    _poll(m, monkeypatch, base, {"CNY": 100.0})
    _poll(m, monkeypatch, base + timedelta(minutes=5), {"CNY": 90.0})       # September spend
    r = _poll(m, monkeypatch, datetime(2026, 10, 1, 0, 5, tzinfo=timezone.utc),
              {"CNY": 80.0})                                                # October spend

    assert r["month_cost"] == round(10 / 7.2, 4)
    assert r["month_cost_cny"] == 10.0
    assert r["window_30d_cost"] == round(20 / 7.2, 4)


def test_legacy_cny_total_migrates_to_usd(monkeypatch, tmp_path):
    m = _monitor(monkeypatch, tmp_path)
    now = datetime(2026, 10, 10, 12, tzinfo=timezone.utc)
    _legacy(monkeypatch, m, {
        "balance": {"currency": "CNY", "balance_cny": 100.0, "balance_usd": 0.0},
        "_total_cost_cny": 36.0,
        "_balance_snapshots": [
            {"ts": (now - timedelta(hours=1)).isoformat(), "balance_cny": 100.0},
        ],
    })
    r = _poll(m, monkeypatch, now, {"CNY": 90.0})

    assert r["total_cost_usd"] == round(36 / 7.2 + 10 / 7.2, 4)
    assert r["total_cost_cny"] == 46.0
    assert r["_schema"] == 2


def test_legacy_usd_only_migrates_once(monkeypatch, tmp_path):
    m = _monitor(monkeypatch, tmp_path)
    now = datetime(2026, 10, 1, tzinfo=timezone.utc)
    _legacy(monkeypatch, m, {
        "balance": {"currency": "USD", "balance_usd": 20.0, "balance_cny": 144.0},
        "_total_cost_cny": 0.0,
        "_balance_snapshots": [
            {"ts": "2026-10-01T00:00:00+00:00", "balance_cny": 144.0},
        ],
    })
    first = _poll(m, monkeypatch, now + timedelta(minutes=1), {"USD": 20.0, "CNY": 0.67})
    assert first["_schema"] == 2
    assert first["month_cost"] == 0.0 and first["total_cost_usd"] == 0.0
    assert first["_balance_snapshots"][0]["balance_usd"] == 20.0
    assert "balance_cny" not in first["_balance_snapshots"][0]
    assert first["_balance_snapshots"][-1]["balance_cny"] == 0.67

    second = _poll(m, monkeypatch, now + timedelta(minutes=2), {"USD": 20.0})
    assert second["month_cost"] == 0.0
    assert "balance_cny" not in second["_balance_snapshots"][0]
    assert second["_balance_snapshots"][-1].get("balance_cny") is None


def test_failed_first_refresh_still_migrates_usd_only(monkeypatch, tmp_path):
    m = _monitor(monkeypatch, tmp_path)
    now = datetime(2026, 10, 1, tzinfo=timezone.utc)
    _legacy(monkeypatch, m, {
        "balance": {"currency": "USD", "balance_usd": 20.0, "balance_cny": 144.0},
        "_total_cost_cny": 0.0,
        "_balance_snapshots": [
            {"ts": "2026-10-01T00:00:00+00:00", "balance_cny": 144.0},
        ],
    })
    failed = _poll(m, monkeypatch, now + timedelta(minutes=1), None)
    assert failed["stale"] is True
    assert failed["_schema"] == 2
    assert failed["_balance_snapshots"][0]["balance_usd"] == 20.0
    assert "balance_cny" not in failed["_balance_snapshots"][0]

    recovered = _poll(m, monkeypatch, now + timedelta(minutes=2), {"USD": 20.0, "CNY": 0.67})
    assert recovered["month_cost"] == 0.0
    assert recovered["total_cost_usd"] == 0.0


def test_cny_history_survives_later_usd_only(monkeypatch, tmp_path):
    m = _monitor(monkeypatch, tmp_path)
    now = datetime(2026, 10, 10, 12, tzinfo=timezone.utc)
    _legacy(monkeypatch, m, {
        "_schema": 2,
        "balance": {"currency": "CNY", "balance_cny": 100.0, "balance_usd": 0.0},
        "_total_cost_cny": 0.0,
        "_total_cost_usd": 0.0,
        "_balance_snapshots": [
            {"ts": (now - timedelta(hours=1)).isoformat(), "balance_cny": 100.0},
        ],
    })
    first = _poll(m, monkeypatch, now, {"CNY": 90.0, "USD": 20.0})
    assert first["month_cost"] == round(10 / 7.2, 4)
    month = first["month_cost"]
    _poll(m, monkeypatch, now + timedelta(minutes=1), {"USD": 20.0})
    third = _poll(m, monkeypatch, now + timedelta(minutes=2), {"USD": 20.0})

    assert third["month_cost"] == month
    assert third["_balance_snapshots"][0]["balance_cny"] == 100.0
    assert third["_balance_snapshots"][1]["balance_cny"] == 90.0
    assert "balance_usd" in third["_balance_snapshots"][1]


def _usage():
    return {
        "_schema": 2,
        "balance": {
            "currency": "CNY",
            "balance_cny": 0.67,
            "balance_usd": 20.0,
            "balance_total_usd": 20.09,
            "balance_total_cny": 144.67,
        },
        "balance_total_usd": 20.09,
        "balance_total_cny": 144.67,
        "month_cost": 6.0,
        "month_cost_cny": 43.2,
        "month_resets_at": int(datetime(2026, 11, 1, tzinfo=timezone.utc).timestamp()),
        "window_5h_cost": 0.09,
        "window_5h_cost_cny": 0.65,
        "window_7d_cost": 3.47,
        "window_7d_cost_cny": 24.98,
        "window_30d_cost": 6.0,
        "window_30d_cost_cny": 43.2,
        "total_cost_usd": 6.0,
        "total_cost_cny": 43.2,
        "stale": False,
    }


def test_reader_builds_three_cards_against_20_usd(monkeypatch, tmp_path):
    monkeypatch.setattr(u, "load_deepseek_usage", _usage)
    monkeypatch.setattr(u, "BUDGET_CONFIG_PATH", tmp_path / "missing-budget.json")
    w = u.compute_windows("deepseek")

    assert w["month_cap_usd"] == 20.0
    month = w["window_5h"]
    assert month["title"] == "Monthly Budget"
    assert month["pct"] == 30 and month["remaining_pct"] == 70
    assert "$6.00 / $20.00" in month["display_line"]
    assert "¥43.20" in month["display_line"]

    balance = w["window_7d"]
    assert balance["title"] == "Balance"
    assert balance["value"] == "$20.09"
    assert "$20.00 USD" in balance["display_line"]
    assert "¥0.67 CNY" in balance["display_line"]

    recent = w["aux"]
    assert recent["title"] == "Recent Spend"
    assert recent["value"] == "$6.00"
    assert "(5h)" in recent["display_line"]
    assert "¥43.20" in recent["display_line"]
    assert "account-level" in recent["display_line"]
    assert "all uses" in recent["sub_line"]


def test_reader_stale_notice_is_in_the_display_line(monkeypatch, tmp_path):
    stale = _usage()
    stale["stale"] = True
    monkeypatch.setattr(u, "load_deepseek_usage", lambda: stale)
    monkeypatch.setattr(u, "BUDGET_CONFIG_PATH", tmp_path / "missing-budget.json")
    w = u.compute_windows("deepseek")
    assert "stale" in w["aux"]["display_line"]
    assert "stale" in w["window_5h"]["display_line"]


def test_reader_usd_only_raw_hides_synthesized_cny(monkeypatch, tmp_path):
    usage = _usage()
    usage["balance"] = {
        "currency": "USD",
        "balance_usd": 20.0,
        "balance_cny": 144.0,
        "raw_balances": {"USD": 20.0},
        "balance_total_usd": 20.0,
        "balance_total_cny": 144.0,
    }
    usage["balance_total_usd"] = 20.0
    usage["balance_total_cny"] = 144.0
    monkeypatch.setattr(u, "load_deepseek_usage", lambda: usage)
    monkeypatch.setattr(u, "BUDGET_CONFIG_PATH", tmp_path / "missing-budget.json")
    w = u.compute_windows("deepseek")
    line = w["window_7d"]["display_line"]
    assert "$20.00 USD" in line
    assert "CNY" not in line


def test_api_wrapper_reconstructs_legacy_balance_totals(monkeypatch):
    import app as app_mod

    monkeypatch.setattr(u, "load_deepseek_usage", lambda: {
        "balance": {"currency": "CNY", "balance_cny": 72.0, "balance_usd": 0.0},
    })
    out = app_mod._ds_load_usage()
    assert out["balance_total_usd"] == 10.0
    assert out["balance_total_cny"] == 72.0

    monkeypatch.setattr(u, "load_deepseek_usage", lambda: {
        "balance": {"currency": "USD", "balance_usd": 20.0, "balance_cny": 144.0},
    })
    out = app_mod._ds_load_usage()
    assert out["balance_total_usd"] == 20.0
    assert out["balance_total_cny"] == 144.0


def test_reader_falls_back_for_old_cache_without_double_counting(monkeypatch, tmp_path):
    old = {
        "balance": {"currency": "USD", "balance_usd": 20.0, "balance_cny": 144.0},
        "window_30d_cost": 4.0,
        "window_30d_cost_cny": 28.8,
        "window_5h_cost": 0.0,
        "window_5h_cost_cny": 0.0,
        "window_7d_cost": 4.0,
        "window_7d_cost_cny": 28.8,
    }
    monkeypatch.setattr(u, "load_deepseek_usage", lambda: old)
    monkeypatch.setattr(u, "BUDGET_CONFIG_PATH", tmp_path / "missing-budget.json")
    w = u.compute_windows("deepseek")

    assert w["month_cost"] == 4.0
    assert w["balance_total_usd"] == 20.0
    assert w["balance_total_cny"] == 144.0
    assert w["window_5h"]["reset"] == "30d"
    assert "CNY" not in w["window_7d"]["display_line"]


def test_file_backed_loader_keeps_month_fields_and_wins(monkeypatch, tmp_path):
    path = tmp_path / "usage.json"
    body = _usage()
    body["window_30d_cost"] = 9.0
    body["window_30d_cost_cny"] = 64.8
    path.write_text(json.dumps(body), encoding="utf-8")
    monkeypatch.setattr(u, "DEEPSEEK_USAGE_PATH", path)
    monkeypatch.setattr(u, "BUDGET_CONFIG_PATH", tmp_path / "missing-budget.json")

    loaded = u.load_deepseek_usage()
    assert loaded["month_cost"] == 6.0
    assert loaded["month_cost_cny"] == 43.2
    assert loaded["balance_total_usd"] == 20.09
    assert loaded["month_resets_at"] == _usage()["month_resets_at"]

    w = u.compute_windows("deepseek")
    assert w["month_cost"] == 6.0  # month wins over the rolling 30-day value (9.0)


def test_dashboard_renders_three_deepseek_cards(monkeypatch, tmp_path):
    import app as app_mod

    monkeypatch.setattr(u, "load_deepseek_usage", _usage)
    monkeypatch.setattr(u, "BUDGET_CONFIG_PATH", tmp_path / "missing-budget.json")
    windows = app_mod.load_windows("deepseek")
    monkeypatch.setattr(app_mod, "load_windows", lambda agent="claude": windows if agent == "deepseek" else {})

    html = app_mod.app.test_client().get("/").text
    assert "Monthly Budget" in html
    assert "$6.00 / $20.00" in html
    assert "Balance" in html
    assert "$20.09" in html
    assert "Recent Spend" in html
