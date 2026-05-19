#!/usr/bin/env python3
"""DeepSeek API usage monitor — balance, token usage, and cost tracking.

Reads from:
  • ~/.deepseek/config.toml       — API key
  • ~/.deepseek/sessions/checkpoints/latest.json — current session metadata
  • ~/.deepseek/usage.json        — persisted usage history (written by us)

Writes to ~/.deepseek/usage.json in the format expected by usage_reader.py
plus extra balance and per-model cost fields.

Usage:
    python3 runner/deepseek_monitor.py --update   # refresh and print
    python3 runner/deepseek_monitor.py --json     # just print current usage
    python3 runner/deepseek_monitor.py --balance  # just print balance
"""

from __future__ import annotations

import json
import os
import sys
import tomllib
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent          # runner/
_DEEPSEEK_DIR = Path.home() / ".deepseek"
_CONFIG_PATH = _DEEPSEEK_DIR / "config.toml"
_CHECKPOINT_PATH = _DEEPSEEK_DIR / "sessions" / "checkpoints" / "latest.json"
_USAGE_PATH = _DEEPSEEK_DIR / "usage.json"

# ── DeepSeek V4 pricing (USD per 1M tokens) ─────────────────────────────
# Source: official DeepSeek pricing page (approximate).
# Override via ~/.deepseek/pricing.json if needed.
DEEPSEEK_MODEL_PRICING: dict[str, dict[str, float]] = {
    "deepseek-v4-flash": {
        "input_per_m": 0.14,
        "output_per_m": 0.14,
    },
    "deepseek-v4-pro": {
        "input_per_m": 0.42,
        "output_per_m": 0.42,
    },
}
# Fallback pricing for unknown models
_DEFAULT_INPUT_MISS_PRICE = 0.14
_DEFAULT_INPUT_HIT_PRICE = 0.0028
_DEFAULT_OUTPUT_PRICE = 0.28

# Estimated input/output split when only total_tokens is available
_DEFAULT_INPUT_PCT = 0.70  # 70% input, 30% output
# Estimated cache hit rate on input tokens for DeepSeek TUI sessions.
# Long-running sessions with cached system prompt hit ~90%+.
_DEFAULT_CACHE_HIT_RATE = 0.90


# ── Helpers ──────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_iso_ms(ts: str) -> datetime | None:
    """Parse ISO 8601 timestamp with optional fractional seconds/microseconds."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        pass
    try:
        return datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    return None


def _load_config() -> dict[str, Any]:
    """Load DeepSeek config.toml and return the api_key."""
    if not _CONFIG_PATH.exists():
        return {}
    try:
        with open(_CONFIG_PATH, "rb") as f:
            return tomllib.load(f)
    except Exception:
        return {}


def _get_api_key() -> str | None:
    """Return DeepSeek API key from config or env."""
    cfg = _load_config()
    key = cfg.get("api_key", "").strip()
    if key:
        return key
    return os.environ.get("DEEPSEEK_API_KEY")


def _model_pricing(model: str) -> dict[str, float]:
    """Return {input_miss_per_m, input_hit_per_m, output_per_m} for a given model."""
    base = DEEPSEEK_MODEL_PRICING.get(model, {})
    if base:
        return base
    for key, prices in DEEPSEEK_MODEL_PRICING.items():
        if model.startswith(key) or key.startswith(model):
            return prices
    return {
        "input_miss_per_m": _DEFAULT_INPUT_MISS_PRICE,
        "input_hit_per_m": _DEFAULT_INPUT_HIT_PRICE,
        "output_per_m": _DEFAULT_OUTPUT_PRICE,
    }


def _pro_discount_active() -> bool:
    """Return True if the V4-Pro 75% discount is still active."""
    try:
        from datetime import datetime, timezone
        expiry = datetime.fromisoformat(PRO_DISCOUNT_EXPIRY)
        return datetime.now(timezone.utc) < expiry
    except Exception:
        return False


def _estimate_cost(
    model: str,
    total_tokens: int,
    cache_hit_rate: float = 0.0,
) -> dict[str, float]:
    """Estimate cost from total_tokens, splitting into input/output.

    cache_hit_rate: fraction of input tokens that are cache hits (0.0–1.0).
    Default 0.0 means all input tokens are cache misses (conservative).

    Returns {cost_usd, cost_cny, input_tokens, output_tokens, cache_hit_rate}.
    """
    p = _model_pricing(model)
    input_miss = p.get("input_miss_per_m", _DEFAULT_INPUT_MISS_PRICE)
    input_hit = p.get("input_hit_per_m", _DEFAULT_INPUT_HIT_PRICE)
    output_price = p.get("output_per_m", _DEFAULT_OUTPUT_PRICE)

    input_tokens = int(total_tokens * _DEFAULT_INPUT_PCT)
    output_tokens = total_tokens - input_tokens
    input_miss_tok = int(input_tokens * (1.0 - cache_hit_rate))
    input_hit_tok = input_tokens - input_miss_tok

    cost_usd = (
        (input_miss_tok / 1_000_000) * input_miss
        + (input_hit_tok / 1_000_000) * input_hit
        + (output_tokens / 1_000_000) * output_price
    )
    cost_cny = cost_usd * 7.2
    return {
        "cost_usd": round(cost_usd, 4),
        "cost_cny": round(cost_cny, 4),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "input_miss_tokens": input_miss_tok,
        "input_hit_tokens": input_hit_tok,
        "cache_hit_rate": round(cache_hit_rate, 4),
    }


# ── Balance API ──────────────────────────────────────────────────────────

def fetch_balance() -> dict[str, Any]:
    """Call DeepSeek /user/balance and return structured result.

    Returns {
        "balance_usd": 0.0,
        "balance_cny": 10.80,
        "currency": "CNY",
        "is_available": true,
        "balance_infos": [...]
    }
    Returns {"error": ...} on failure.
    """
    api_key = _get_api_key()
    if not api_key:
        return {"error": "no API key found"}

    req = urllib.request.Request(
        "https://api.deepseek.com/user/balance",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, OSError) as exc:
        return {"error": str(exc)}

    balance_infos = data.get("balance_infos", [])
    result: dict[str, Any] = {
        "balance_infos": balance_infos,
        "is_available": data.get("is_available", False),
    }
    for info in balance_infos:
        cur = info.get("currency", "")
        total = float(info.get("total_balance", 0))
        if cur == "USD":
            result["balance_usd"] = total
        elif cur == "CNY":
            result["balance_cny"] = total
    result.setdefault("balance_usd", 0.0)
    result.setdefault("balance_cny", 0.0)
    result["currency"] = "CNY" if result["balance_cny"] > 0 else "USD"
    return result


# ── Checkpoint Scanner ───────────────────────────────────────────────────

def scan_checkpoint() -> dict[str, Any] | None:
    """Read the current session checkpoint.

    Returns {
        "session_id": "...",
        "model": "deepseek-v4-flash",
        "message_count": 74,
        "total_tokens": 1104142,
        "created_at": "...",
        "updated_at": "...",
    }
    Returns None if no checkpoint exists.
    """
    if not _CHECKPOINT_PATH.exists():
        return None
    try:
        data = json.loads(_CHECKPOINT_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    meta = data.get("metadata", {})
    sid = meta.get("id")
    if not sid:
        return None

    return {
        "session_id": sid,
        "model": meta.get("model", "unknown"),
        "message_count": meta.get("message_count", 0),
        "total_tokens": meta.get("total_tokens", 0) or 0,
        "created_at": meta.get("created_at", ""),
        "updated_at": meta.get("updated_at", ""),
    }


# ── Usage History Persistence ────────────────────────────────────────────

def _load_usage_history() -> dict[str, Any]:
    """Load persisted usage.json; returns {} if absent."""
    if not _USAGE_PATH.exists():
        return {}
    try:
        return json.loads(_USAGE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_usage_history(data: dict[str, Any]) -> None:
    """Atomically write usage.json."""
    _DEEPSEEK_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _USAGE_PATH.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    tmp.replace(_USAGE_PATH)


# ── Window Calculations ──────────────────────────────────────────────────

def _is_in_window(ts_str: str, hours: int, now: datetime | None = None) -> bool:
    if not ts_str:
        return False
    dt = parse_iso_ms(ts_str)
    if dt is None:
        return False
    if now is None:
        now = datetime.now(timezone.utc)
    return (now - dt).total_seconds() <= hours * 3600


# ── Main Update Logic ────────────────────────────────────────────────────

def update_usage() -> dict[str, Any]:
    """Run a full update cycle: fetch balance, scan checkpoint, persist.

    Returns the updated usage data dict.
    """
    prev = _load_usage_history()
    prev_sessions = prev.get("_session_history", [])
    prev_by_model = prev.get("by_model_detail", {})

    balance = fetch_balance()
    checkpoint = scan_checkpoint()

    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    # ── Balance-based cost (ground truth from API balance changes) ───────
    bal_cny = float(balance.get("balance_cny", 0) or 0)

    # Balance snapshot history for real cost tracking across top-ups
    balance_snapshots: list[dict[str, Any]] = prev.get("_balance_snapshots", [])

    # Seed initial snapshot if a known initial balance is configured
    seed_initial = float(prev.get("_seed_initial_balance_cny", 0) or 0)
    if seed_initial > 0 and (not balance_snapshots or len(balance_snapshots) == 0):
        balance_snapshots.insert(0, {"ts": now_iso, "balance_cny": seed_initial})

    balance_snapshots.append({"ts": now_iso, "balance_cny": bal_cny})
    if len(balance_snapshots) > 200:
        balance_snapshots = balance_snapshots[-200:]

    # Compute real cost from balance decreases between consecutive snapshots.
    # If balance increased between snapshots, it's a top-up event.
    real_total_cost_cny = 0.0
    topup_events: list[dict[str, Any]] = []
    last_bal: float | None = None
    for snap in balance_snapshots:
        b = snap["balance_cny"]
        if last_bal is not None:
            if b < last_bal:
                real_total_cost_cny += last_bal - b
            elif b > last_bal:
                topup_events.append({"ts": snap["ts"], "amount_cny": round(b - last_bal, 2)})
        last_bal = b
    real_total_cost_cny = round(real_total_cost_cny, 4)
    real_total_cost_usd = round(real_total_cost_cny / 7.2, 4)

    # Legacy _initial_balance tracking (kept for backwards compat)
    initial_balance_cny = float(prev.get("_initial_balance_cny", 0) or 0)
    if not initial_balance_cny and bal_cny > 0:
        initial_balance_cny = bal_cny

    # Daily tracking
    today_str = str(now.date())
    daily_key = f"_daily_balance_{today_str}"
    daily_initial = float(prev.get(daily_key, 0) or 0)
    if not daily_initial and bal_cny > 0:
        daily_initial = bal_cny
    today_spent_cny = round(max(0.0, daily_initial - bal_cny), 4)
    today_spent_usd = round(today_spent_cny / 7.2, 4)

    # ── Recalculate historical session costs with current pricing ────────
    for s in prev_sessions:
        total_tok = s.get("total_tokens", 0) or 0
        if total_tok > 0:
            model = s.get("model", "deepseek-v4-flash")
            new_est = _estimate_cost(model, total_tok, _DEFAULT_CACHE_HIT_RATE)
            s["_cost_estimate"] = new_est

    # ── Track session transitions ────────────────────────────────────────
    last_session_id = prev.get("_last_session_id")
    current_session = prev.get("_current_session")
    last_ckpt_tokens = prev.get("_last_checkpoint_tokens", 0)

    if checkpoint:
        sid = checkpoint["session_id"]
        model = checkpoint["model"]
        total_tokens = checkpoint["total_tokens"]
        msg_count = checkpoint["message_count"]
        # checkpoint total_tokens is cumulative across TUI process lifetime;
        # use delta since last read for per-session token counting.
        # On first read (last_ckpt_tokens==0), count total_tokens fully.
        if last_ckpt_tokens > 0 and total_tokens > last_ckpt_tokens:
            delta_tokens = total_tokens - last_ckpt_tokens
        elif last_ckpt_tokens == 0:
            delta_tokens = total_tokens
        else:
            # No new tokens since last read; keep current_session's existing total
            delta_tokens = 0
        last_ckpt_tokens = total_tokens

        if last_session_id and last_session_id != sid and current_session:
            # Session changed — archive the previous one
            archived = dict(current_session)
            archived["ended_at"] = now_iso
            prev_sessions.append(archived)

            archived_cost = archived.get("_cost_estimate", {})
            archived_tokens = archived.get("total_tokens", 0) or 0
            archived_model = archived.get("model", "unknown")
            bm = prev_by_model.setdefault(archived_model, {
                "total_tokens": 0, "input_tokens": 0, "output_tokens": 0,
                "cost_usd": 0.0, "cost_cny": 0.0, "sessions": 0,
            })
            bm["total_tokens"] += archived_tokens
            bm["input_tokens"] += archived_cost.get("input_tokens", 0)
            bm["output_tokens"] += archived_cost.get("output_tokens", 0)
            bm["cost_usd"] = round(bm["cost_usd"] + archived_cost.get("cost_usd", 0), 4)
            bm["cost_cny"] = round(bm["cost_cny"] + archived_cost.get("cost_cny", 0), 4)
            bm["sessions"] += 1

        # Update current session: accumulate delta_tokens into running total
        if current_session and current_session.get("session_id") == sid:
            old_tok = current_session.get("total_tokens", 0) or 0
            new_total = old_tok + delta_tokens
        else:
            new_total = delta_tokens
        cost_est = _estimate_cost(model, new_total, _DEFAULT_CACHE_HIT_RATE)
        current_session = {
            "session_id": sid,
            "model": model,
            "message_count": msg_count,
            "total_tokens": new_total,
            "created_at": checkpoint.get("created_at", ""),
            "updated_at": checkpoint.get("updated_at", ""),
            "_cost_estimate": cost_est,
        }
        last_session_id = sid

    elif current_session:
        # Checkpoint disappeared — session ended
        archived = dict(current_session)
        archived["ended_at"] = now_iso
        prev_sessions.append(archived)

        archived_cost = archived.get("_cost_estimate", {})
        archived_tokens = archived.get("total_tokens", 0) or 0
        archived_model = archived.get("model", "unknown")
        _bm_defaults = {"total_tokens": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "cost_cny": 0.0, "sessions": 0}
        bm = prev_by_model.setdefault(archived_model, {})
        for _k, _v in _bm_defaults.items():
            bm.setdefault(_k, _v)
        bm["total_tokens"] += archived_tokens
        bm["input_tokens"] += archived_cost.get("input_tokens", 0)
        bm["output_tokens"] += archived_cost.get("output_tokens", 0)
        bm["cost_usd"] = round(bm["cost_usd"] + archived_cost.get("cost_usd", 0), 4)
        bm["cost_cny"] = round(bm["cost_cny"] + archived_cost.get("cost_cny", 0), 4)
        bm["sessions"] += 1

        current_session = None
        last_session_id = None

    # Trim history to last 100 sessions
    if len(prev_sessions) > 100:
        prev_sessions = prev_sessions[-100:]

    # ── Compute budget-window summaries ──────────────────────────────────
    def _window_totals(sessions: list[dict], hours: int) -> tuple[int, int, float, float]:
        tok = 0
        ses = 0
        cost_usd = 0.0
        cost_cny = 0.0
        for s in sessions:
            created = s.get("created_at", "") or s.get("started_at", "")
            if _is_in_window(created, hours, now):
                tok += s.get("total_tokens", 0) or 0
                ses += 1
                ce = s.get("_cost_estimate", {})
                cost_usd += ce.get("cost_usd", 0)
                cost_cny += ce.get("cost_cny", 0)
        if current_session:
            created = current_session.get("created_at", "")
            if _is_in_window(created, hours, now):
                tok += current_session.get("total_tokens", 0) or 0
                if hours <= 168:
                    ses += 1
                ce = current_session.get("_cost_estimate", {})
                cost_usd += ce.get("cost_usd", 0)
                cost_cny += ce.get("cost_cny", 0)
        return tok, ses, round(cost_usd, 4), round(cost_cny, 4)

    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    (window_5h_tok, window_5h_ses, window_5h_cost, window_5h_cost_cny) = _window_totals(prev_sessions, 5)
    (window_7d_tok, window_7d_ses, window_7d_cost, window_7d_cost_cny) = _window_totals(prev_sessions, 168)
    (window_30d_tok, window_30d_ses, window_30d_cost, window_30d_cost_cny) = _window_totals(prev_sessions, 720)

    today_tok = 0
    today_ses = 0
    today_cost = 0.0
    for s in prev_sessions:
        created = s.get("created_at", "") or s.get("started_at", "")
        dt = parse_iso_ms(created)
        if dt and dt >= today_start:
            today_tok += s.get("total_tokens", 0) or 0
            today_ses += 1
            ce = s.get("_cost_estimate", {})
            today_cost += ce.get("cost_usd", 0)
    if current_session:
        created = current_session.get("created_at", "")
        dt = parse_iso_ms(created)
        if dt and dt >= today_start:
            today_tok += current_session.get("total_tokens", 0) or 0
            today_ses += 1
            ce = current_session.get("_cost_estimate", {})
            today_cost += ce.get("cost_usd", 0)
    today_cost = round(today_cost, 4)

    # Balance-based cost (ground truth from API balance snapshots)
    total_cost_usd = real_total_cost_usd
    total_cost_cny = real_total_cost_cny

    # Today cost from balance tracking
    today_cost = today_spent_usd

    # Legacy by_model format: model_name -> total_tokens
    by_model_legacy: dict[str, int] = {}
    for mn, bm in prev_by_model.items():
        by_model_legacy[mn] = bm["total_tokens"]
    if current_session:
        m = current_session.get("model", "unknown")
        by_model_legacy[m] = by_model_legacy.get(m, 0) + current_session.get("total_tokens", 0)

    result: dict[str, Any] = {
        # Legacy fields (for load_deepseek_usage compatibility)
        "window_5h": {"tokens": window_5h_tok, "sessions": window_5h_ses},
        "window_7d": {"tokens": window_7d_tok, "sessions": window_7d_ses},
        "today": {"tokens": today_tok, "sessions": today_ses, "cost": today_cost},
        "by_model": by_model_legacy,
        # New fields
        "balance": balance,
        "total_cost_usd": total_cost_usd,
        "total_cost_cny": total_cost_cny,
        "window_5h_cost": window_5h_cost,
        "window_5h_cost_cny": window_5h_cost_cny,
        "window_7d_cost": window_7d_cost,
        "window_7d_cost_cny": window_7d_cost_cny,
        "window_30d_cost": window_30d_cost,
        "window_30d_cost_cny": window_30d_cost_cny,
        "by_model_detail": prev_by_model,
        "current_session": current_session,
        "session_count": len(prev_sessions) + (1 if current_session else 0),
        "last_updated": now_iso,
        # Internal state
        "_last_session_id": last_session_id,
        "_current_session": current_session,
        "_session_history": prev_sessions,
        "_initial_balance_cny": initial_balance_cny,
        "_balance_snapshots": balance_snapshots,
        "_topup_events": topup_events,
        "_known_total_cost_cny": prev.get("_known_total_cost_cny"),
        "_seed_initial_balance_cny": prev.get("_seed_initial_balance_cny"),
        "_last_checkpoint_tokens": last_ckpt_tokens,
        daily_key: daily_initial,
    }

    _save_usage_history(result)
    return result


# ── CLI ──────────────────────────────────────────────────────────────────

def _fmt_tok(n: int) -> str:
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)


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
        else:
            bal = result.get("balance", {})
            b_cny = bal.get("balance_cny", 0)
            b_usd = bal.get("balance_usd", 0)
            print("━" * 50)
            print(f" DeepSeek Usage Monitor — {result.get('last_updated', '?')[:19]}")
            print("━" * 50)
            print(f" Balance: ¥{b_cny} / ${b_usd}")
            print(f" Total cost: ${result['total_cost_usd']} / ¥{result['total_cost_cny']}")
            print()
            print(" Today:")
            td = result.get("today", {})
            print(f"   {_fmt_tok(td.get('tokens', 0))} tokens · {td.get('sessions', 0)} sessions · ${td.get('cost', 0)}")
            print(" 5h window:")
            w5 = result.get("window_5h", {})
            print(f"   {_fmt_tok(w5.get('tokens', 0))} tokens · {w5.get('sessions', 0)} sessions")
            print(" 7d window:")
            w7 = result.get("window_7d", {})
            print(f"   {_fmt_tok(w7.get('tokens', 0))} tokens · {w7.get('sessions', 0)} sessions")
            print()
            print(" By model:")
            detail = result.get("by_model_detail", {})
            for mn, bm in sorted(detail.items()):
                print(f"   {mn:<30} {_fmt_tok(bm['total_tokens'])} tokens  "
                      f"${bm['cost_usd']}  ({bm['sessions']} sessions)")
            cs = result.get("current_session")
            if cs:
                print(f"\n Active: {cs['model']} · {_fmt_tok(cs['total_tokens'])} tokens · {cs['message_count']} msgs")
            print(f"\n {result.get('session_count', 0)} sessions tracked")
        return 0

    if args.balance:
        bal = fetch_balance()
        if args.json:
            print(json.dumps(bal, indent=2, default=str))
        else:
            err = bal.get("error")
            if err:
                print(f"Balance check failed: {err}", file=sys.stderr)
                return 1
            print(f"Balance: ${bal.get('balance_usd', 0)} / ¥{bal.get('balance_cny', 0)}")
            print(f"Available: {bal.get('is_available', False)}")
        return 0

    if args.json:
        data = _load_usage_history()
        print(json.dumps(data, indent=2, default=str))
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
