#!/usr/bin/env python3
"""DeepSeek API usage monitor — balance and spend windows from balance changes.

Reads:   DeepSeek /user/balance (key: env DEEPSEEK_API_KEY first, else ~/.deepseek/config.toml)
Writes:  ~/.deepseek/usage.json (runner-owned cache; the only file this runner writes there)

Spend is account-level: window cost is the sum of balance decreases inside the window; top-ups
(increases) are ignored. The API can report a CNY balance and a USD balance at the same time;
each currency is tracked independently and both are normalized to USD for the monthly budget.
Token and session counts are unknown here (null): per-run tokens live in the run records. dsh
writes no usage checkpoint.

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
_RETENTION = timedelta(days=31)  # one full calendar month, plus the 30-day window
_SCHEMA = 2  # 2 = snapshots carry raw per-currency balances


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

    The API can report both CNY and USD. `raw_balances` keeps only the reported currencies;
    `balance_cny`/`balance_usd` stay for old consumers. A USD-only account keeps the legacy
    synthesized `balance_cny`; a missing USD balance is 0.0.
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
        result: dict[str, Any] = {
            "is_available": data.get("is_available", False),
            "raw_balances": {},
        }
        for info in data.get("balance_infos", []):
            currency = info.get("currency")
            if currency not in ("CNY", "USD"):
                continue
            value = _finite(info["total_balance"])
            result["raw_balances"][currency] = value
            result[f"balance_{currency.lower()}"] = value
        if not result["raw_balances"]:
            return {"error": "balance response has no CNY or USD balance"}
        usd = result["raw_balances"].get("USD", 0.0)
        cny = result["raw_balances"].get("CNY", 0.0)
        result["balance_total_usd"] = round(usd + cny / _CNY_PER_USD, 4)
        result["balance_total_cny"] = round(cny + usd * _CNY_PER_USD, 4)
        result["currencies"] = sorted(result["raw_balances"])
        if "balance_cny" in result:
            result["currency"] = "CNY"
        else:
            result["currency"] = "USD"
            result["balance_cny"] = round(usd * _CNY_PER_USD, 4)
        result.setdefault("balance_usd", 0.0)
        return result
    except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        return {"error": str(exc)}


def _balance_totals(balance: dict[str, Any]) -> tuple[float, float]:
    """USD and CNY totals for a cached balance, without double-counting synthesized CNY."""
    raw = balance.get("raw_balances")
    if isinstance(raw, dict) and raw:
        usd = max(0.0, _finite_or_zero(raw.get("USD")))
        cny = max(0.0, _finite_or_zero(raw.get("CNY")))
        return round(usd + cny / _CNY_PER_USD, 4), round(cny + usd * _CNY_PER_USD, 4)
    usd = max(0.0, _finite_or_zero(balance.get("balance_usd")))
    cny = max(0.0, _finite_or_zero(balance.get("balance_cny")))
    if balance.get("currency") == "USD":
        cny = 0.0  # legacy USD-only cache: balance_cny was synthesized from balance_usd
    return round(usd + cny / _CNY_PER_USD, 4), round(cny + usd * _CNY_PER_USD, 4)


def _balance_components(balance: dict[str, Any]) -> str:
    """Display only currencies with a positive reported value; hide synthesized CNY."""
    raw = balance.get("raw_balances")
    if isinstance(raw, dict) and raw:
        usd = max(0.0, _finite_or_zero(raw.get("USD")))
        cny = max(0.0, _finite_or_zero(raw.get("CNY")))
    else:
        usd = max(0.0, _finite_or_zero(balance.get("balance_usd")))
        cny = max(0.0, _finite_or_zero(balance.get("balance_cny")))
        if balance.get("currency") == "USD":
            cny = 0.0
    parts = []
    if usd:
        parts.append(f"${usd:.2f} USD")
    if cny:
        parts.append(f"¥{cny:.2f} CNY")
    return " + ".join(parts) or "no positive balance"


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
    """Keep samples inside the retention window plus the newest earlier one as the baseline."""
    cutoff = now - _RETENTION
    older = [s for s in samples if (parse_iso_ms(s.get("ts", "")) or now) < cutoff]
    return older[-1:] + [s for s in samples if s not in older]


def _valid_samples(raw: Any) -> list[dict[str, Any]]:
    """Cached samples with a timestamp and at least one finite balance."""
    out = []
    for s in raw if isinstance(raw, list) else []:
        try:
            if not isinstance(s, dict) or not parse_iso_ms(s["ts"]):
                continue
            sample: dict[str, Any] = {"ts": s["ts"]}
            for key in ("balance_cny", "balance_usd"):
                if key in s:
                    sample[key] = _finite(s[key])
            if len(sample) > 1:
                out.append(sample)
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _legacy_usd_only(prev: dict[str, Any]) -> bool:
    """A pre-schema cache whose only balance was recorded as synthesized CNY."""
    balance = prev.get("balance")
    return "_schema" not in prev and isinstance(balance, dict) and balance.get("currency") == "USD"


def _migrate_usd_only_samples(samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reinterpret a legacy USD-only history: its balance_cny was synthesized from USD."""
    out = []
    for sample in samples:
        record = dict(sample)
        if "balance_usd" not in record and "balance_cny" in record:
            record["balance_usd"] = round(record["balance_cny"] / _CNY_PER_USD, 6)
        record.pop("balance_cny", None)
        out.append(record)
    return out


def _sample_changed(prev: dict[str, Any], cur: dict[str, Any]) -> bool:
    for key in ("balance_cny", "balance_usd"):
        if (key in prev) != (key in cur):
            return True
        if key in prev and prev[key] != cur[key]:
            return True
    return False


def _spend_delta(prev: dict[str, Any], cur: dict[str, Any]) -> tuple[float, float]:
    """USD and CNY value of the decreases between two samples, per reported currency."""
    usd = cny = 0.0
    for key, usd_factor, cny_factor in (
        ("balance_usd", 1.0, _CNY_PER_USD),
        ("balance_cny", 1.0 / _CNY_PER_USD, 1.0),
    ):
        before, after = prev.get(key), cur.get(key)
        if before is None or after is None:
            continue
        drop = before - after
        if drop > 0:
            usd += drop * usd_factor
            cny += drop * cny_factor
    return usd, cny


def _spend_since(samples: list[dict[str, Any]], since: datetime) -> tuple[float, float]:
    """USD and CNY spend from balance decreases observed at samples timestamped at/after since."""
    usd = cny = 0.0
    for prev, cur in zip(samples, samples[1:]):
        ts = parse_iso_ms(cur.get("ts", ""))
        if not ts or ts < since:
            continue
        delta_usd, delta_cny = _spend_delta(prev, cur)
        usd += delta_usd
        cny += delta_cny
    return round(usd, 4), round(cny, 4)


def _finite_or_zero(value: Any) -> float:
    try:
        return _finite(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _month_bounds(now: datetime) -> tuple[datetime, datetime]:
    """UTC calendar-month start and the next start."""
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return start, (start + timedelta(days=32)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _balance_sample(balance: dict[str, Any], now: datetime) -> dict[str, Any] | None:
    """A snapshot with only the currencies this response actually reported."""
    raw = balance.get("raw_balances")
    if isinstance(raw, dict):
        values = {"balance_cny": raw.get("CNY"), "balance_usd": raw.get("USD")}
    else:
        values = {"balance_cny": balance.get("balance_cny"), "balance_usd": balance.get("balance_usd")}
    sample: dict[str, Any] = {"ts": now.isoformat()}
    for key, value in values.items():
        if value is None:
            continue
        try:
            sample[key] = _finite(value)
        except (TypeError, ValueError):
            continue
    return sample if len(sample) > 1 else None


def _update_locked(now: datetime) -> dict[str, Any]:
    prev = _load_usage_history()
    api_key = resolve_api_key()  # resolved once: the same key feeds the fingerprint and the fetch
    current_fp = key_fp(api_key) if api_key else prev.get("key_fp")
    if api_key and prev.get("key_fp") != current_fp:
        prev = {}  # a known different account: never diff balances across accounts

    samples = _valid_samples(prev.get("_balance_snapshots"))
    if _legacy_usd_only(prev):
        # Convert before publishing _schema so a failed first refresh cannot strand old samples.
        samples = _migrate_usd_only_samples(samples)

    total_cost_usd = _finite_or_zero(prev.get("_total_cost_usd"))
    total_cost_cny = _finite_or_zero(prev.get("_total_cost_cny"))
    if "_total_cost_usd" not in prev and "_total_cost_cny" in prev:
        total_cost_usd = round(total_cost_cny / _CNY_PER_USD, 4)
    elif "_total_cost_cny" not in prev and "_total_cost_usd" in prev:
        total_cost_cny = round(total_cost_usd * _CNY_PER_USD, 4)

    balance = fetch_balance(api_key) if api_key else {"error": "no API key found"}
    stale, last_error = False, None
    if "error" in balance:
        stale, last_error = True, balance["error"]
        prev_balance = prev.get("balance")
        balance = dict(prev_balance) if isinstance(prev_balance, dict) else {}  # keep the last valid baseline
    else:
        sample = _balance_sample(balance, now)
        if sample is not None and not samples:
            samples.append(sample)
        elif sample is not None and _sample_changed(samples[-1], sample):
            delta_usd, delta_cny = _spend_delta(samples[-1], sample)
            # Keep cumulative state precise; publish rounded values below.
            total_cost_usd = round(total_cost_usd + delta_usd, 8)
            total_cost_cny = round(total_cost_cny + delta_cny, 8)
            samples.append(sample)
    samples = _retain(samples, now)
    balance_usd_total, balance_cny_total = _balance_totals(balance)
    balance["balance_total_usd"] = balance_usd_total
    balance["balance_total_cny"] = balance_cny_total

    window = {name: _spend_since(samples, now - timedelta(hours=h)) for name, h in _WINDOWS_H.items()}
    today_usd, today_cny = _spend_since(
        samples, now.replace(hour=0, minute=0, second=0, microsecond=0)
    )
    month_start, month_next = _month_bounds(now)
    month_usd, month_cny = _spend_since(samples, month_start)
    unknown = {"tokens": None, "sessions": None}
    return {
        "_schema": _SCHEMA,
        "window_5h": dict(unknown),
        "window_7d": dict(unknown),
        "today": {**unknown, "cost": today_usd, "cost_cny": today_cny},
        "by_model": {},
        "balance": balance,
        "balance_total_usd": balance_usd_total,
        "balance_total_cny": balance_cny_total,
        "stale": stale,
        "last_error": last_error,
        "total_cost_usd": round(total_cost_usd, 4),
        "total_cost_cny": round(total_cost_cny, 4),
        "month_cost": month_usd,
        "month_cost_cny": month_cny,
        "month_resets_at": int(month_next.timestamp()),
        **{f"window_{name}_cost": window[name][0] for name in window},
        **{f"window_{name}_cost_cny": window[name][1] for name in window},
        "spend_scope": "account (includes ask_deepseek.py and any other use of this key)",
        "last_updated": now.isoformat(),
        "key_fp": current_fp,
        "_balance_snapshots": samples,
        "_total_cost_cny": total_cost_cny,
        "_total_cost_usd": total_cost_usd,
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
        stale = f"  (STALE: {result['last_error']})" if result.get("stale") else ""
        print(f"DeepSeek usage — {result['last_updated'][:19]}{stale}")
        print(f" Balance: ${bal.get('balance_total_usd', 0):.2f} total ({_balance_components(bal)})")
        print(f" Spend:   ${result['window_5h_cost']:.2f} (5h) · ${result['window_7d_cost']:.2f} (7d) · "
              f"${result['window_30d_cost']:.2f} (30d) · ${result['total_cost_usd']:.2f} tracked total")
        print(f" Month:   ${result['month_cost']:.2f} / $20.00 · ¥{result['month_cost_cny']:.2f}")
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
        print(f"Balance: ${_balance_totals(bal)[0]:.2f} total ({_balance_components(bal)})")
        print(f"Available: {bal.get('is_available', False)}")
        return 0

    if args.json:
        print(json.dumps(_load_usage_history(), indent=2, default=str))
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
