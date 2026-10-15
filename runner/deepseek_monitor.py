#!/usr/bin/env python3
"""DeepSeek API usage monitor — balance and spend windows from balance changes.

Reads:   DeepSeek /user/balance (key: env DEEPSEEK_API_KEY first, else ~/.deepseek/config.toml)
Writes:  ~/.deepseek/usage.json (runner-owned cache; the only file this runner writes there)

Spend is account-level: window cost is the sum of balance decreases inside the window; top-ups
(increases) are ignored. Token and session counts are unknown here (null): per-run tokens live
in the run records. dsh writes no usage checkpoint.

Usage:
    python3 runner/deepseek_monitor.py --update   # refresh and print
    python3 runner/deepseek_monitor.py --json     # just print current usage
    python3 runner/deepseek_monitor.py --balance  # just print balance
"""

from __future__ import annotations

import fcntl
import json
import math
import os
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from dsh_cli import key_fp, resolve_api_key

_DEEPSEEK_DIR = Path.home() / ".deepseek"
_USAGE_PATH = _DEEPSEEK_DIR / "usage.json"
_LOCK_PATH = _DEEPSEEK_DIR / "usage.json.lock"
_CNY_PER_USD = 7.2
_WINDOWS_H = {"5h": 5, "7d": 168, "30d": 720}
_RETENTION = timedelta(hours=max(_WINDOWS_H.values()))  # longest displayed window


def _now() -> datetime:
    return datetime.now(timezone.utc)


def parse_iso_ms(ts: str) -> datetime | None:
    """Parse ISO 8601 timestamp with optional fractional seconds/microseconds."""
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ── Balance API ──────────────────────────────────────────────────────────

def _finite(value: Any) -> float:
    """float() that rejects NaN/Infinity (which float() happily parses from strings)."""
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"non-finite balance {value!r}")
    return number


def fetch_balance(api_key: str | None = None) -> dict[str, Any]:
    """Call DeepSeek /user/balance. Returns {"error": ...} unless a finite balance came back.

    Accounting currency is CNY. A USD-only account is normalized at _CNY_PER_USD, and
    "currency" records which one was reported so a currency switch resets the history.
    """
    api_key = api_key or resolve_api_key()
    if not api_key:
        return {"error": "no API key found"}
    req = urllib.request.Request(
        "https://api.deepseek.com/user/balance",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        result: dict[str, Any] = {"is_available": data.get("is_available", False)}
        for info in data.get("balance_infos", []):
            if info.get("currency") == "CNY":
                result["balance_cny"] = _finite(info["total_balance"])
            elif info.get("currency") == "USD":
                result["balance_usd"] = _finite(info["total_balance"])
    except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        return {"error": str(exc)}
    if "balance_cny" in result:
        result["currency"] = "CNY"
    elif "balance_usd" in result:
        result["currency"] = "USD"
        result["balance_cny"] = round(result["balance_usd"] * _CNY_PER_USD, 4)
    else:
        return {"error": "balance response has no CNY or USD balance"}
    result.setdefault("balance_usd", 0.0)
    return result


# ── Persistence ──────────────────────────────────────────────────────────

def _load_usage_history() -> dict[str, Any]:
    try:
        data = json.loads(_USAGE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_usage_history(data: dict[str, Any]) -> None:
    """Publish through a unique temp file in the same dir, then an atomic rename."""
    _DEEPSEEK_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".usage.", suffix=".tmp", dir=_DEEPSEEK_DIR)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str, allow_nan=False)
        os.replace(tmp, _USAGE_PATH)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


# ── Spend from balance samples ───────────────────────────────────────────

def _retain(samples: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    """Keep samples inside the longest window plus the newest earlier one as the baseline."""
    cutoff = now - _RETENTION
    older = [s for s in samples if (parse_iso_ms(s.get("ts", "")) or now) < cutoff]
    return older[-1:] + [s for s in samples if s not in older]


def _spend_since(samples: list[dict[str, Any]], since: datetime) -> float:
    """Sum of balance decreases observed at samples timestamped at or after since."""
    total = 0.0
    for prev, cur in zip(samples, samples[1:]):
        ts = parse_iso_ms(cur.get("ts", ""))
        drop = prev["balance_cny"] - cur["balance_cny"]
        if ts and ts >= since and drop > 0:
            total += drop
    return round(total, 4)


def _finite_or_zero(value: Any) -> float:
    try:
        return _finite(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _valid_samples(raw: Any) -> list[dict[str, Any]]:
    """Cached samples with a timestamp and a finite balance; anything else is dropped."""
    out = []
    for s in raw if isinstance(raw, list) else []:
        try:
            if isinstance(s, dict) and parse_iso_ms(s["ts"]):
                out.append({"ts": s["ts"], "balance_cny": _finite(s["balance_cny"])})
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _cny_usd(cny: float) -> float:
    return round(cny / _CNY_PER_USD, 4)


def _update_locked(now: datetime) -> dict[str, Any]:
    prev = _load_usage_history()
    api_key = resolve_api_key()  # resolved once: the same key feeds the fingerprint and the fetch
    current_fp = key_fp(api_key) if api_key else prev.get("key_fp")
    if api_key and prev.get("key_fp") != current_fp:
        prev = {}  # a known different account: never diff balances across accounts
    samples = _valid_samples(prev.get("_balance_snapshots"))
    total_cost_cny = _finite_or_zero(prev.get("_total_cost_cny"))
    balance = fetch_balance(api_key) if api_key else {"error": "no API key found"}
    stale, last_error = False, None
    if "error" in balance:
        stale, last_error = True, balance["error"]
        balance = dict(prev.get("balance") or {})  # keep the last valid baseline
    else:
        if prev.get("balance", {}).get("currency") not in (None, balance.get("currency")):
            samples, total_cost_cny = [], 0.0  # currency switch: deltas across currencies are meaningless
        bal = balance["balance_cny"]
        if not samples or samples[-1]["balance_cny"] != bal:
            if samples and bal < samples[-1]["balance_cny"]:
                total_cost_cny = round(total_cost_cny + samples[-1]["balance_cny"] - bal, 4)
            samples.append({"ts": now.isoformat(), "balance_cny": bal})
    samples = _retain(samples, now)

    window = {name: _spend_since(samples, now - timedelta(hours=h)) for name, h in _WINDOWS_H.items()}
    today_cny = _spend_since(samples, now.replace(hour=0, minute=0, second=0, microsecond=0))
    unknown = {"tokens": None, "sessions": None}
    return {
        "window_5h": dict(unknown),
        "window_7d": dict(unknown),
        "today": {**unknown, "cost": _cny_usd(today_cny), "cost_cny": today_cny},
        "by_model": {},
        "balance": balance,
        "stale": stale,
        "last_error": last_error,
        "total_cost_usd": _cny_usd(total_cost_cny),
        "total_cost_cny": total_cost_cny,
        **{f"window_{n}_cost": _cny_usd(c) for n, c in window.items()},
        **{f"window_{n}_cost_cny": c for n, c in window.items()},
        "spend_scope": "account (includes ask_deepseek.py and any other use of this key)",
        "last_updated": now.isoformat(),
        "key_fp": current_fp,
        "_balance_snapshots": samples,
        "_total_cost_cny": total_cost_cny,
    }


def update_usage() -> dict[str, Any]:
    """One fetch → read history → append → write cycle under an exclusive file lock.

    Fetching inside the lock guarantees no older observation overwrites a newer one across
    background polling, POST /api/deepseek/refresh and the --update CLI.
    """
    _DEEPSEEK_DIR.mkdir(parents=True, exist_ok=True)
    with open(_LOCK_PATH, "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            result = _update_locked(_now())
            _save_usage_history(result)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
    return result


# ── CLI ──────────────────────────────────────────────────────────────────

def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="DeepSeek usage monitor.")
    parser.add_argument("--update", action="store_true", help="Refresh usage data and save")
    parser.add_argument("--json", action="store_true", help="Print usage data as JSON")
    parser.add_argument("--balance", action="store_true", help="Print balance only")
    args = parser.parse_args()

    if args.update:
        result = update_usage()
        if args.json:
            print(json.dumps(result, indent=2, default=str))
            return 0
        bal = result.get("balance", {})
        print(f"DeepSeek usage — {result['last_updated'][:19]}{'  (STALE: ' + str(result['last_error']) + ')' if result['stale'] else ''}")
        print(f" Balance: ¥{bal.get('balance_cny', '?')} / ${bal.get('balance_usd', '?')}")
        print(f" Spend:   ¥{result['window_5h_cost_cny']} (5h) · ¥{result['window_7d_cost_cny']} (7d) · "
              f"¥{result['window_30d_cost_cny']} (30d) · ¥{result['total_cost_cny']} tracked total")
        print(f" Scope:   {result['spend_scope']}; tokens n/a")
        return 0

    if args.balance:
        bal = fetch_balance()
        if args.json:
            print(json.dumps(bal, indent=2, default=str))
            return 0
        if bal.get("error"):
            print(f"Balance check failed: {bal['error']}", file=sys.stderr)
            return 1
        print(f"Balance: ${bal.get('balance_usd', 0)} / ¥{bal.get('balance_cny', 0)}")
        print(f"Available: {bal.get('is_available', False)}")
        return 0

    if args.json:
        print(json.dumps(_load_usage_history(), indent=2, default=str))
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
