#!/usr/bin/env python3
"""Read Claude Code token usage from ~/.claude/ project JSONL files.

Aggregates across all projects and sessions. Returns structured usage stats
suitable for the dashboard.

Usage:
    python3 usage_reader.py                  # today's stats
    python3 usage_reader.py --days 7         # last 7 days
    python3 usage_reader.py --json           # machine-readable output
"""

from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

CLAUDE_DIR = Path.home() / ".claude"
_PROTO = Path(__file__).resolve().parents[1]         # agentic-os/

def _find_workspace_claude_dir() -> Path:
    # Walk up from _PROTO looking for a .claude dir that has rate-limits-live.json
    p = _PROTO
    for _ in range(5):
        candidate = p / ".claude"
        if (candidate / "rate-limits-live.json").exists():
            return candidate
        p = p.parent
    return _PROTO / ".claude"  # fallback

_workspace_claude_env = os.environ.get("WORKSPACE_CLAUDE_DIR", "").strip()
WORKSPACE_CLAUDE_DIR = Path(_workspace_claude_env).expanduser() if _workspace_claude_env else _find_workspace_claude_dir()
PROJECTS_DIR = CLAUDE_DIR / "projects"
STATS_CACHE = CLAUDE_DIR / "stats-cache.json"
CODEX_DB = Path.home() / ".codex" / "state_5.sqlite"
CODEX_SESSIONS_DIR = Path.home() / ".codex" / "sessions"
DEEPSEEK_USAGE_PATH = Path.home() / ".deepseek" / "usage.json"
BUDGET_CONFIG_PATH = CLAUDE_DIR / "budget.json"
CLAUDE_LIVE_RATE_LIMITS_PATH = WORKSPACE_CLAUDE_DIR / "rate-limits-live.json"

MODEL_CTX = {
    "claude-opus-4-7":          200_000,
    "claude-sonnet-4-6":        200_000,
    "claude-haiku-4-5-20251001": 200_000,
    "claude-sonnet-4-5-20250929": 200_000,
}
DEFAULT_CTX = 200_000

# Output token price per 1M (USD)
MODEL_PRICES: dict[str, float] = {
    "claude-opus-4-7":            15.00,
    "claude-sonnet-4-6":           3.00,
    "claude-sonnet-4-5-20250929":  3.00,
    "claude-haiku-4-5-20251001":   1.25,
    "gpt-5.4":                     6.00,
}
DEFAULT_PRICE = 3.00

# DeepSeek V4 pricing (USD per 1M tokens) — used by deepseek_monitor.py
DEEPSEEK_MODEL_PRICING: dict[str, dict[str, float]] = {
    "deepseek-v4-flash": {"input_miss_per_m": 0.14, "input_hit_per_m": 0.0028, "output_per_m": 0.28},
    "deepseek-v4-pro":   {"input_miss_per_m": 0.435, "input_hit_per_m": 0.003625, "output_per_m": 0.87},
}

# These defaults are inferred from /cost data (19.8M tokens = 83% of 5h; 155M = 15% of 7d).
# They are ESTIMATES — Claude's actual rate-limit unit may differ from raw JSONL token counts.
# Override in ~/.claude/budget.json if your plan differs.
DEFAULT_LIMITS: dict[str, dict] = {
    "claude": {"window_5h": 30_000_000, "window_7d": 1_000_000_000, "daily_runs_max": 5},
    "codex":  {"window_5h": 30_000_000, "window_7d": 150_000_000,   "daily_runs_max": 5},
    "deepseek":  {"window_5h": 10_000_000, "window_7d":  50_000_000,   "daily_runs_max": 20},
}


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _date_of(ts: str) -> str:
    try:
        return datetime.fromisoformat(ts).strftime("%Y-%m-%d")
    except Exception:
        return "?"


def _collect_jsonl_usage(since_date: str) -> dict[str, Any]:
    """Scan all project JSONL files and aggregate token usage since since_date."""
    daily: dict[str, dict] = defaultdict(lambda: {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read": 0,
        "cache_creation": 0,
        "messages": 0,
        "sessions": set(),
    })
    by_model: dict[str, dict] = defaultdict(lambda: {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read": 0,
        "cache_creation": 0,
    })
    total_messages = 0

    if not PROJECTS_DIR.exists():
        return {"daily": {}, "by_model": {}, "total_messages": 0}

    for project_dir in PROJECTS_DIR.iterdir():
        if not project_dir.is_dir():
            continue
        for jsonl_path in project_dir.glob("*.jsonl"):
            try:
                for raw in jsonl_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                    if not raw.strip():
                        continue
                    try:
                        record = json.loads(raw)
                    except Exception:
                        continue

                    if record.get("type") != "assistant":
                        continue

                    ts = record.get("timestamp", "")
                    date = _date_of(ts) if ts else "?"
                    if date < since_date:
                        continue

                    msg = record.get("message", {})
                    usage = msg.get("usage", {})
                    if not usage:
                        continue

                    model = msg.get("model", "unknown")
                    session_id = record.get("sessionId", "")

                    inp = usage.get("input_tokens", 0)
                    out = usage.get("output_tokens", 0)
                    cr  = usage.get("cache_read_input_tokens", 0)
                    cc  = usage.get("cache_creation_input_tokens", 0)

                    day = daily[date]
                    day["input_tokens"]  += inp
                    day["output_tokens"] += out
                    day["cache_read"]    += cr
                    day["cache_creation"] += cc
                    day["messages"]      += 1
                    if session_id:
                        day["sessions"].add(session_id)

                    bm = by_model[model]
                    bm["input_tokens"]  += inp
                    bm["output_tokens"] += out
                    bm["cache_read"]    += cr
                    bm["cache_creation"] += cc

                    total_messages += 1
            except Exception:
                continue

    # Convert sets to counts
    for day in daily.values():
        day["sessions"] = len(day["sessions"])

    return {
        "daily": dict(daily),
        "by_model": dict(by_model),
        "total_messages": total_messages,
    }


def load_codex_usage() -> dict[str, Any]:
    """Read Codex token usage from ~/.codex/state_5.sqlite threads table."""
    if not CODEX_DB.exists():
        return {}
    try:
        import sqlite3
        db = sqlite3.connect(str(CODEX_DB))
        now_ts = datetime.now(timezone.utc).timestamp()
        since_5h  = now_ts - 5 * 3600
        since_7d  = now_ts - 7 * 86400
        today_ts  = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()

        def _q(since: float) -> tuple[int, int]:
            r = db.execute(
                "SELECT COALESCE(SUM(tokens_used),0), COUNT(*) FROM threads WHERE created_at >= ? AND tokens_used > 0",
                (since,),
            ).fetchone()
            return int(r[0]), int(r[1])

        tok_5h,  ses_5h  = _q(since_5h)
        tok_7d,  ses_7d  = _q(since_7d)
        tok_day, ses_day = _q(today_ts)

        model_rows = db.execute(
            "SELECT model, COALESCE(SUM(tokens_used),0) FROM threads "
            "WHERE created_at >= ? AND tokens_used > 0 GROUP BY model ORDER BY 2 DESC",
            (since_7d,),
        ).fetchall()

        return {
            "window_5h":  {"tokens": tok_5h,  "sessions": ses_5h},
            "window_7d":  {"tokens": tok_7d,  "sessions": ses_7d},
            "today":      {"tokens": tok_day, "sessions": ses_day},
            "by_model":   {r[0]: int(r[1]) for r in model_rows},
        }
    except Exception:
        return {}


def load_deepseek_usage() -> dict[str, Any]:
    """Read DeepSeek token usage from ~/.deepseek/usage.json.

    Written by deepseek_monitor.py. Legacy fields (window_5h/7d, today,
    by_model) are always present. New fields (balance, total_cost_*,
    by_model_detail) pass through if available.
    """
    if not DEEPSEEK_USAGE_PATH.exists():
        return {}
    try:
        data = json.loads(DEEPSEEK_USAGE_PATH.read_text(encoding="utf-8"))
        result: dict[str, Any] = {
            "window_5h":  data.get("window_5h",  {"tokens": 0, "sessions": 0}),
            "window_7d":  data.get("window_7d",  {"tokens": 0, "sessions": 0}),
            "today":      data.get("today",      {"tokens": 0, "sessions": 0}),
            "by_model":   data.get("by_model",   {}),
        }
        # Pass through new fields if present
        for key in ("balance", "total_cost_usd", "total_cost_cny",
                     "by_model_detail", "current_session", "session_count",
                     "last_updated",
                     "window_5h_cost", "window_5h_cost_cny",
                     "window_7d_cost", "window_7d_cost_cny",
                     "window_30d_cost", "window_30d_cost_cny",
                     "_session_history", "_balance_snapshots",
                     "_known_total_cost_cny", "_seed_initial_balance_cny"):
            val = data.get(key)
            if val is not None:
                result[key] = val
        return result
    except Exception:
        return {}


def cross_check_stats_cache(jsonl_total_messages: int) -> dict[str, Any]:
    """Compare our JSONL message count against Claude's stats-cache.json.

    stats-cache is not always up-to-date; the comparison detects staleness.
    """
    if not STATS_CACHE.exists():
        return {}
    try:
        cache = json.loads(STATS_CACHE.read_text(encoding="utf-8"))
        last_date = cache.get("lastComputedDate", "?")
        cache_msgs = sum(d.get("messageCount", 0) for d in cache.get("dailyActivity", []))
        delta = jsonl_total_messages - cache_msgs
        pct = round(delta / cache_msgs * 100) if cache_msgs else None
        return {
            "last_computed": last_date,
            "cache_messages": cache_msgs,
            "jsonl_messages": jsonl_total_messages,
            "delta": delta,
            "delta_pct": pct,
        }
    except Exception:
        return {}


def load_budget(agent: str) -> dict[str, Any]:
    defaults = DEFAULT_LIMITS.get(agent, DEFAULT_LIMITS["claude"])
    if not BUDGET_CONFIG_PATH.exists():
        return dict(defaults)
    try:
        cfg = json.loads(BUDGET_CONFIG_PATH.read_text(encoding="utf-8"))
        ag = cfg.get(agent, {})
        result = {
            "window_5h":      ag.get("window_5h",      defaults["window_5h"]),
            "window_7d":      ag.get("window_7d",      defaults["window_7d"]),
            "daily_runs_max": ag.get("daily_runs_max", defaults["daily_runs_max"]),
        }
        if "weekly_reset" in ag:
            result["weekly_reset"] = ag["weekly_reset"]
        return result
    except Exception:
        return dict(defaults)


def _next_weekly_reset_label(reset_cfg: dict, now: datetime) -> str:
    """Compute time-until-reset from a fixed weekly anchor (weekday + hour + tz)."""
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(reset_cfg["tz"])
        now_local = now.astimezone(tz)
        target_day = reset_cfg["weekday"]   # 0=Mon, 2=Wed
        target_h   = reset_cfg["hour"]
        target_m   = reset_cfg["minute"]

        days_ahead = target_day - now_local.weekday()
        if days_ahead < 0:
            days_ahead += 7
        elif days_ahead == 0 and (now_local.hour, now_local.minute) >= (target_h, target_m):
            days_ahead += 7

        next_reset_local = now_local.replace(
            hour=target_h, minute=target_m, second=0, microsecond=0
        ) + timedelta(days=days_ahead)
        secs = int((next_reset_local.astimezone(timezone.utc) - now).total_seconds())

        if secs <= 300:
            return "NOW"
        h, remainder = divmod(secs, 3600)
        m = remainder // 60
        d, h = divmod(h, 24)
        if d > 0:
            return f"{d}d{h:02d}h"
        return f"{h}h{m:02d}m"
    except Exception:
        return "—"


def _reset_label_from_epoch(reset_ts: int | float | None, now: datetime) -> str:
    if not reset_ts:
        return "—"
    try:
        reset_at = datetime.fromtimestamp(float(reset_ts), tz=timezone.utc)
    except Exception:
        return "—"
    secs = int((reset_at - now).total_seconds())
    if secs <= 300:
        return "NOW"
    h, remainder = divmod(secs, 3600)
    m = remainder // 60
    d, h = divmod(h, 24)
    if d > 0:
        return f"{d}d{h:02d}h"
    return f"{h}h{m:02d}m" if h else f"{m}m"


def _parse_iso_utc(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _window_percent_from_snapshot(
    used_percent: int | float | None,
    reset_ts: int | float | None,
    snapshot_ts: datetime | None,
    now: datetime,
) -> int:
    pct = int(round(used_percent or 0))
    if not reset_ts:
        return max(0, min(100, pct))
    try:
        reset_at = datetime.fromtimestamp(float(reset_ts), tz=timezone.utc)
    except Exception:
        return max(0, min(100, pct))

    # If the last server snapshot predates the reset boundary and we are already
    # past that boundary, the old percent belongs to the previous window.
    if snapshot_ts and snapshot_ts < reset_at <= now:
        return 0
    return max(0, min(100, pct))


def load_latest_codex_rate_limits() -> dict[str, Any]:
    """Read the latest server-reported Codex rate limit snapshot from session logs.

    Scans all session files and returns the record with the most recent timestamp,
    not just the last record in the alphabetically-last file. Sessions can overlap:
    a session started earlier (lower filename sort) may have newer token_count events
    than a session started later.
    """
    if not CODEX_SESSIONS_DIR.exists():
        return {}

    try:
        best_ts: datetime | None = None
        best: dict[str, Any] = {}

        for path in CODEX_SESSIONS_DIR.rglob("*.jsonl"):
            try:
                lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
            except Exception:
                continue
            # Find the last (most recent) token_count record in this file.
            for raw in reversed(lines):
                if '"type":"token_count"' not in raw or '"rate_limits"' not in raw:
                    continue
                try:
                    record = json.loads(raw)
                except Exception:
                    continue
                payload = record.get("payload", {})
                if payload.get("type") != "token_count":
                    continue
                rate = payload.get("rate_limits") or {}
                if rate.get("limit_id") != "codex":
                    continue
                ts = _parse_iso_utc(record.get("timestamp"))
                if ts is not None and (best_ts is None or ts > best_ts):
                    best_ts = ts
                    info = payload.get("info") or {}
                    total = (info.get("total_token_usage") or {}).get("total_tokens")
                    best = {
                        "timestamp": record.get("timestamp"),
                        "plan_type": rate.get("plan_type"),
                        "primary": rate.get("primary") or {},
                        "secondary": rate.get("secondary") or {},
                        "total_tokens": int(total) if isinstance(total, (int, float)) else None,
                        "model_context_window": info.get("model_context_window"),
                    }
                break  # Only the last token_count per file; no need to scan further.

        return best
    except Exception:
        return {}


def load_live_claude_rate_limits() -> dict[str, Any]:
    """Read latest server-reported Claude rate limits from the statusline drop file."""
    if not CLAUDE_LIVE_RATE_LIMITS_PATH.exists():
        return {}
    try:
        payload = json.loads(CLAUDE_LIVE_RATE_LIMITS_PATH.read_text(encoding="utf-8"))
        rate = payload.get("rate_limits") or {}
        five = rate.get("five_hour") or {}
        seven = rate.get("seven_day") or {}
        captured_at = _parse_iso_utc(payload.get("captured_at"))
        return {
            "captured_at": captured_at,
            "captured_at_raw": payload.get("captured_at"),
            "workspace": payload.get("workspace"),
            "model": payload.get("model"),
            "five_hour": {
                "used_percent": five.get("used_percentage"),
                "resets_at": five.get("resets_at"),
            },
            "seven_day": {
                "used_percent": seven.get("used_percentage"),
                "resets_at": seven.get("resets_at"),
            },
        }
    except Exception:
        return {}


def _claude_window_range(since: datetime, until: datetime) -> dict[str, Any]:
    """Aggregate Claude JSONL token usage between two datetimes."""
    tokens = out = 0
    sessions: set[str] = set()
    earliest_ts: datetime | None = None

    if not PROJECTS_DIR.exists():
        return {"tokens": 0, "sessions": 0, "output": 0, "earliest_ts": None}

    for project_dir in PROJECTS_DIR.iterdir():
        if not project_dir.is_dir():
            continue
        for jsonl_path in project_dir.glob("*.jsonl"):
            try:
                for raw in jsonl_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                    if not raw.strip():
                        continue
                    try:
                        record = json.loads(raw)
                    except Exception:
                        continue
                    if record.get("type") != "assistant":
                        continue
                    ts_str = record.get("timestamp", "")
                    if not ts_str:
                        continue
                    try:
                        ts = datetime.fromisoformat(ts_str)
                        if ts.tzinfo is None:
                            ts = ts.replace(tzinfo=timezone.utc)
                    except Exception:
                        continue
                    if not (since <= ts < until):
                        continue
                    msg = record.get("message", {})
                    usage = msg.get("usage", {})
                    if not usage:
                        continue
                    i = usage.get("input_tokens", 0)
                    o = usage.get("output_tokens", 0)
                    c = usage.get("cache_creation_input_tokens", 0)
                    # Exclude cache_read_input_tokens: billed at 0.1x, inflates count 10-20x
                    tokens += i + o + c
                    out += o
                    sid = record.get("sessionId", "")
                    if sid:
                        sessions.add(sid)
                    if earliest_ts is None or ts < earliest_ts:
                        earliest_ts = ts
            except Exception:
                continue

    return {"tokens": tokens, "sessions": len(sessions), "output": out, "earliest_ts": earliest_ts}


def _codex_window_range(since: datetime, until: datetime) -> dict[str, Any]:
    if not CODEX_DB.exists():
        return {"tokens": 0, "sessions": 0, "output": 0, "earliest_ts": None}
    try:
        import sqlite3
        db = sqlite3.connect(str(CODEX_DB))
        r = db.execute(
            "SELECT COALESCE(SUM(tokens_used),0), COUNT(*), MIN(created_at) FROM threads "
            "WHERE created_at >= ? AND created_at < ? AND tokens_used > 0",
            (since.timestamp(), until.timestamp()),
        ).fetchone()
        earliest_ts = datetime.fromtimestamp(r[2], tz=timezone.utc) if r[2] else None
        return {"tokens": int(r[0]), "sessions": int(r[1]), "output": 0, "earliest_ts": earliest_ts}
    except Exception:
        return {"tokens": 0, "sessions": 0, "output": 0, "earliest_ts": None}


def _deepseek_window_range(since: datetime, until: datetime) -> dict[str, Any]:
    """Aggregate DeepSeek token usage from ~/.deepseek/usage.json between two datetimes."""
    usage = load_deepseek_usage()
    if not usage:
        return {"tokens": 0, "sessions": 0, "output": 0, "earliest_ts": None}
    # usage.json stores pre‑aggregated windows; we approximate by returning
    # the 7‑day window for any range that includes the last 7 days.
    # For finer granularity we would need per‑session logs.
    now = datetime.now(timezone.utc)
    # If the requested range covers the last 7 days, return the 7‑day total.
    if since <= now - timedelta(days=7) and until >= now:
        w7 = usage.get("window_7d", {})
        return {
            "tokens":   w7.get("tokens", 0),
            "sessions": w7.get("sessions", 0),
            "output":   0,
            "earliest_ts": None,
        }
    # If the requested range covers the last 5 hours, return the 5‑hour total.
    if since <= now - timedelta(hours=5) and until >= now:
        w5 = usage.get("window_5h", {})
        return {
            "tokens":   w5.get("tokens", 0),
            "sessions": w5.get("sessions", 0),
            "output":   0,
            "earliest_ts": None,
        }
    # Otherwise return today's total (best approximation).
    today = usage.get("today", {})
    return {
        "tokens":   today.get("tokens", 0),
        "sessions": today.get("sessions", 0),
        "output":   0,
        "earliest_ts": None,
    }


def _trend_badge(current: int, prior: int) -> str:
    # Treat prior windows with <2% of current as "no meaningful baseline".
    if prior == 0 or (current > 0 and prior < current * 0.02):
        return "NEW" if current > 0 else "—"
    pct = round((current - prior) / prior * 100)
    if abs(pct) < 5:
        return "FLAT"
    # Cap at ±999% — larger swings are noise, not signal.
    pct = max(-999, min(999, pct))
    arrow = "▲" if pct > 0 else "▼"
    return f"{arrow}{abs(pct)}%"


def _reset_label(earliest_ts: datetime | None, window_hours: float, now: datetime) -> str:
    if not earliest_ts:
        return "—"
    reset_at = earliest_ts + timedelta(hours=window_hours)
    secs = int((reset_at - now).total_seconds())
    if secs <= 0:
        return "NOW"
    if secs < 60:
        return "<1m"
    h, remainder = divmod(secs, 3600)
    m = remainder // 60
    return f"{h}h{m:02d}m" if h else f"{m}m"


def _today_stats_claude(now: datetime) -> dict[str, Any]:
    """Tokens, sessions, and estimated cost for today (local calendar day)."""
    # Use local midnight so non-UTC users see their own "today", not UTC's.
    local_midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    local_midnight_utc = local_midnight.astimezone(timezone.utc)
    data = _claude_window_range(local_midnight_utc, now)
    tokens = data["tokens"]
    sessions = data["sessions"]
    cost = round(data.get("output", 0) / 1_000_000 * DEFAULT_PRICE, 4)
    return {"tokens": tokens, "sessions": sessions, "cost": cost}


def _fmt_tok(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def _count_runs_today(run_log_path: Path, now: datetime) -> int:
    if not run_log_path or not run_log_path.exists():
        return 0
    today_str = now.strftime("%Y-%m-%d")
    count = 0
    for raw in run_log_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not raw.strip():
            continue
        try:
            r = json.loads(raw)
            if r.get("started_at", "").startswith(today_str):
                count += 1
        except Exception:
            continue
    return count


def compute_windows(agent: str = "claude", run_log_path: Path | None = None) -> dict[str, Any]:
    """Return three budget-window panels."""
    now = datetime.now(timezone.utc)
    limits = load_budget(agent)

    if agent == "deepseek":
        _range = _deepseek_window_range
    elif agent == "codex":
        _range = _codex_window_range
    else:
        _range = _claude_window_range

    cur_5h  = _range(now - timedelta(hours=5),  now)
    pri_5h  = _range(now - timedelta(hours=10), now - timedelta(hours=5))
    cur_7d  = _range(now - timedelta(days=7),   now)
    pri_7d  = _range(now - timedelta(days=14),  now - timedelta(days=7))

    lim_5h = limits["window_5h"]
    lim_7d = limits["window_7d"]
    lim_runs = limits["daily_runs_max"]

    def _pct(val: int, lim: int) -> int:
        return min(100, round(val / lim * 100)) if lim else 0

    today_stats = _today_stats_claude(now) if agent != "codex" else None

    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    secs_to_midnight = int((midnight - now).total_seconds())
    h, remainder = divmod(secs_to_midnight, 3600)
    m = remainder // 60
    midnight_label = f"{h}h{m:02d}m"

    # Weekly reset: use fixed anchor from budget config if available, else rolling fallback.
    weekly_reset_cfg = limits.get("weekly_reset")
    weekly_reset_label = (
        _next_weekly_reset_label(weekly_reset_cfg, now)
        if weekly_reset_cfg
        else _reset_label(cur_7d["earliest_ts"], 7 * 24, now)
    )

    def _rem(val: int, lim: int) -> int:
        return max(0, 100 - _pct(val, lim))

    if agent == "deepseek":
        # Cost-based budget windows (CNY)
        CAP_5H = 5.0
        CAP_WEEKLY = 50.0
        CAP_MONTHLY = 200.0

        _ds_usage = load_deepseek_usage()
        _bal_cny = 0.0
        _cost_5h = 0.0
        _cost_weekly = 0.0
        _cost_monthly = 0.0

        if _ds_usage:
            _bal = _ds_usage.get("balance", {})
            _bal_cny = max(0.0, float(_bal.get("balance_cny", 0) or 0))
            _cost_5h = float(_ds_usage.get("window_5h_cost_cny", 0) or 0)
            _cost_weekly = float(_ds_usage.get("window_7d_cost_cny", 0) or 0)
            _cost_monthly = float(_ds_usage.get("window_30d_cost_cny", 0) or 0)

            # ── Calibrate: token-proportional distribution of real cost ──
            _real_total = float(
                _ds_usage.get("_known_total_cost_cny", 0)
                or _ds_usage.get("total_cost_cny", 0)
                or 0
            )
            if _real_total > 0:
                _sessions = _ds_usage.get("_session_history", [])
                _cut_5h = now - timedelta(hours=5)
                _cut_7d = now - timedelta(days=7)
                _cut_30d = now - timedelta(days=30)
                _tok_5h = _tok_7d = _tok_30d = 0
                for _s in _sessions:
                    _ts = _s.get("created_at", "") or _s.get("started_at", "")
                    _tok = _s.get("total_tokens", 0) or 0
                    if _ts >= _cut_30d.isoformat():
                        _tok_30d += _tok
                        if _ts >= _cut_7d.isoformat():
                            _tok_7d += _tok
                            if _ts >= _cut_5h.isoformat():
                                _tok_5h += _tok
                _total_tok = _tok_30d
                if _total_tok > 0:
                    _cost_5h = round(_real_total * _tok_5h / _total_tok, 2)
                    _cost_weekly = round(_real_total * _tok_7d / _total_tok, 2)
                    _cost_monthly = round(_real_total, 2)

        def _cost_pct(cost: float, cap: float) -> int:
            return min(100, round(cost / cap * 100)) if cap else 0

        def _cost_card(cost: float, cap: float, title: str,
                       reset_label: str, balance: float | None = None) -> dict:
            pct = _cost_pct(cost, cap)
            cost_fmt = f"¥{cost:.2f}"
            cap_fmt = f"¥{cap:.2f}"
            card: dict[str, Any] = {
                "title": title,
                "cost_cny": round(cost, 2),
                "cap_cny": cap,
                "pct": pct,
                "tokens_fmt": cost_fmt,
                "display_line": f"{cost_fmt} / {cap_fmt} · {reset_label}",
                "value_line": f"{cost_fmt} / {cap_fmt}",
                "sub_line": reset_label,
                "reset": reset_label,
                "tokens": int(cost * 100),
                "limit": int(cap * 100),
                "remaining_pct": _rem(int(cost * 100), int(cap * 100)) if cap else 100,
                "resets_at_unix": None,
            }
            if balance is not None and cap > 0:
                marker = min(100, _cost_pct(cost + balance, cap))
                card["balance_marker_pct"] = marker
            return card

        return {
            "agent": agent, "limits_estimated": True,
            "quota_source": "usage.json",
            "balance_cny": round(_bal_cny, 2),
            "window_5h": _cost_card(_cost_5h, CAP_5H, "5-Hour", midnight_label),
            "window_7d": _cost_card(_cost_weekly, CAP_WEEKLY, "Weekly", weekly_reset_label, _bal_cny),
            "aux": _cost_card(_cost_monthly, CAP_MONTHLY, "Monthly", "—", _bal_cny),
        }
        # Fallback: run_log-based estimate
        sum_5h, sum_7d, runs_5h, runs_7d = 0, 0, 0, 0
        cutoff_5h = now - timedelta(hours=5)
        cutoff_7d = now - timedelta(days=7)
        if run_log_path and run_log_path.exists():
            for raw in run_log_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                if not raw.strip():
                    continue
                try:
                    r = json.loads(raw)
                    if r.get("agent") != "deepseek":
                        continue
                    ts = _parse_iso_utc(r.get("started_at") or "")
                    if ts is None:
                        continue
                    tok = (r.get("input_tokens") or 0) + (r.get("output_tokens") or 0)
                    if ts >= cutoff_7d:
                        sum_7d += tok
                        runs_7d += 1
                    if ts >= cutoff_5h:
                        sum_5h += tok
                        runs_5h += 1
                except Exception:
                    continue
        return {
            "agent": "deepseek", "limits_estimated": True,
            "quota_source": "run_log",
            "window_5h": {
                "title": "5-Hour (run_log)",
                "tokens": sum_5h, "limit": lim_5h,
                "pct": _pct(sum_5h, lim_5h),
                "remaining_pct": _rem(sum_5h, lim_5h),
                "sessions": runs_5h, "reset": midnight_label,
                "resets_at_unix": None, "window_minutes": 300,
                "display_line": f"{_fmt_tok(sum_5h)} / {_fmt_tok(lim_5h)} · {runs_5h} runs",
            },
            "window_7d": {
                "title": "Weekly (run_log)",
                "tokens": sum_7d, "limit": lim_7d,
                "pct": _pct(sum_7d, lim_7d),
                "remaining_pct": _rem(sum_7d, lim_7d),
                "sessions": runs_7d, "reset": weekly_reset_label,
                "resets_at_unix": None, "window_minutes": 10080,
                "display_line": f"{_fmt_tok(sum_7d)} / {_fmt_tok(lim_7d)} · {runs_7d} runs",
            },
            "aux": {
                "title": "DeepSeek Usage",
                "value_line": f"{_fmt_tok(sum_7d)} tokens this week",
                "sub_line": f"{runs_7d} runs",
                "reset": weekly_reset_label,
                "pct": _pct(sum_7d, lim_7d),
            },
        }

    if agent == "codex":
        live = load_latest_codex_rate_limits()
        if live:
            snapshot_ts = _parse_iso_utc(live.get("timestamp"))
            primary = live.get("primary", {})
            secondary = live.get("secondary", {})
            used_5h = _window_percent_from_snapshot(
                primary.get("used_percent", 0),
                primary.get("resets_at"),
                snapshot_ts,
                now,
            )
            used_7d = _window_percent_from_snapshot(
                secondary.get("used_percent", 0),
                secondary.get("resets_at"),
                snapshot_ts,
                now,
            )
            local_total = live.get("total_tokens")
            local_total_label = f"{local_total:,} local tokens".replace(",", "_").replace("_", ",") if local_total else None
            codex_usage = load_codex_usage()
            today = codex_usage.get("today", {})
            today_tokens = int(today.get("tokens", 0) or 0)
            today_sessions = int(today.get("sessions", 0) or 0)
            display_5h = "server-reported usage"
            if used_5h == 0 and snapshot_ts:
                try:
                    reset_at = datetime.fromtimestamp(float(primary.get("resets_at")), tz=timezone.utc)
                    if snapshot_ts < reset_at <= now:
                        display_5h = "window reset; awaiting next Codex usage snapshot"
                except Exception:
                    pass

            return {
                "agent": agent,
                "limits_estimated": False,
                "quota_source": "server",
                "plan_type": live.get("plan_type"),
                "window_5h": {
                    "tokens":        cur_5h["tokens"],
                    "limit":         100,
                    "pct":           used_5h,
                    "remaining_pct": max(0, 100 - used_5h),
                    "sessions":      cur_5h["sessions"],
                    "reset":         _reset_label_from_epoch(primary.get("resets_at"), now),
                    "display_line":  display_5h + (f" · {local_total_label}" if local_total_label else ""),
                    "resets_at_unix": primary.get("resets_at"),
                    "window_minutes": primary.get("window_minutes", 300),
                },
                "window_7d": {
                    "tokens":        cur_7d["tokens"],
                    "limit":         100,
                    "pct":           used_7d,
                    "remaining_pct": max(0, 100 - used_7d),
                    "sessions":      cur_7d["sessions"],
                    "reset":         _reset_label_from_epoch(secondary.get("resets_at"), now),
                    "display_line":  "server-reported usage",
                    "resets_at_unix": secondary.get("resets_at"),
                    "window_minutes": secondary.get("window_minutes", 10080),
                },
                "aux": {
                    "title":      "Today Tokens",
                    "reset":      midnight_label,
                    "pct":        0,
                    "value_line": f"{today_tokens:,} local tokens".replace(",", "_").replace("_", ","),
                    "sub_line":   f"{today_sessions} session{'s' if today_sessions != 1 else ''}",
                },
            }

    # Ensure today_stats is defined for deepseek (fallback path)
    today_stats = {"tokens": 0, "sessions": 0, "cost": 0}

    if agent == "claude":
        live = load_live_claude_rate_limits()
        captured_at = live.get("captured_at")
        if captured_at and now - captured_at <= timedelta(hours=12):
            five = live.get("five_hour", {})
            seven = live.get("seven_day", {})
            used_5h = _window_percent_from_snapshot(
                five.get("used_percent", 0),
                five.get("resets_at"),
                captured_at,
                now,
            )
            used_7d = _window_percent_from_snapshot(
                seven.get("used_percent", 0),
                seven.get("resets_at"),
                captured_at,
                now,
            )
            return {
                "agent": agent,
                "limits_estimated": False,
                "quota_source": "server",
                "window_5h": {
                    "tokens":        cur_5h["tokens"],
                    "limit":         100,
                    "pct":           used_5h,
                    "remaining_pct": max(0, 100 - used_5h),
                    "sessions":      cur_5h["sessions"],
                    "reset":         _reset_label_from_epoch(five.get("resets_at"), now),
                    "display_line":  "server-reported usage"
                                     f" · {cur_5h['tokens']:,} local tokens"
                                     f" · {cur_5h['sessions']} sessions",
                    "resets_at_unix": five.get("resets_at"),
                    "window_minutes": 300,
                },
                "window_7d": {
                    "tokens":        cur_7d["tokens"],
                    "limit":         100,
                    "pct":           used_7d,
                    "remaining_pct": max(0, 100 - used_7d),
                    "sessions":      cur_7d["sessions"],
                    "reset":         _reset_label_from_epoch(seven.get("resets_at"), now),
                    "display_line":  "server-reported usage"
                                     f" · {cur_7d['tokens']:,} local tokens"
                                     f" · {cur_7d['sessions']} sessions",
                    "resets_at_unix": seven.get("resets_at"),
                    "window_minutes": 10080,
                },
                "aux": {
                    "title":      "Today Tokens",
                    "reset":      midnight_label,
                    "pct":        _pct(today_stats["tokens"], lim_7d // 7),
                    "value_line": f"{_fmt_tok(today_stats['tokens'])} tokens",
                    "sub_line":   (
                        f"${today_stats['cost']:.3f} est. cost"
                        f" · {today_stats['sessions']} session"
                        f"{'s' if today_stats['sessions'] != 1 else ''}"
                    ),
                },
            }

    _real_5h_pct = _pct(cur_5h["tokens"], lim_5h)
    _real_7d_pct = _pct(cur_7d["tokens"], lim_7d)
    return {
        "agent": agent,
        "limits_estimated": True,
        "quota_source": "local-estimate",
        "window_5h": {
            "tokens":        cur_5h["tokens"],
            "limit":         lim_5h,
            "pct":           _real_5h_pct,
            "remaining_pct": _rem(cur_5h["tokens"], lim_5h),
            "sessions":      cur_5h["sessions"],
            "reset":         "Not synced",
            "estimate_only": True,
            "display_line":  "estimated local usage"
                             f" · {cur_5h['tokens']:,} / {lim_5h:,}"
                             f" · {cur_5h['sessions']} sessions",
        },
        "window_7d": {
            "tokens":        cur_7d["tokens"],
            "limit":         lim_7d,
            "pct":           _real_7d_pct,
            "remaining_pct": _rem(cur_7d["tokens"], lim_7d),
            "sessions":      cur_7d["sessions"],
            "reset":         "Not synced",
            "estimate_only": True,
            "display_line":  "estimated local usage"
                             f" · {cur_7d['tokens']:,} / {lim_7d:,}"
                             f" · {cur_7d['sessions']} sessions",
        },
        "aux": {
            "title":      "Today Tokens",
            "reset":      midnight_label,
            "pct":        _pct(today_stats["tokens"], lim_7d // 7),
            "value_line": f"{_fmt_tok(today_stats['tokens'])} tokens",
            "sub_line":   (
                f"${today_stats['cost']:.3f} est. cost"
                f" · {today_stats['sessions']} session"
                f"{'s' if today_stats['sessions'] != 1 else ''}"
            ),
        },
    }


def compute_stats(days: int = 30) -> dict[str, Any]:
    today = _today()
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    data = _collect_jsonl_usage(since)

    daily = data["daily"]
    by_model = data["by_model"]

    # Today's stats
    today_data = daily.get(today, {})
    today_tokens = (
        today_data.get("input_tokens", 0)
        + today_data.get("output_tokens", 0)
        + today_data.get("cache_creation", 0)
    )

    # Last 7 days
    week_tokens = 0
    week_messages = 0
    week_sessions = 0
    for i in range(7):
        d = (datetime.now(timezone.utc) - timedelta(days=i)).strftime("%Y-%m-%d")
        dd = daily.get(d, {})
        week_tokens   += dd.get("input_tokens", 0) + dd.get("output_tokens", 0) + dd.get("cache_creation", 0)
        week_messages += dd.get("messages", 0)
        week_sessions += dd.get("sessions", 0)

    # Total across window
    total_tokens = sum(
        dd.get("input_tokens", 0) + dd.get("output_tokens", 0)
        + dd.get("cache_creation", 0)
        for dd in daily.values()
    )

    # Primary model (most output tokens)
    primary_model = max(by_model, key=lambda m: by_model[m]["output_tokens"], default="unknown")
    ctx_window = MODEL_CTX.get(primary_model, DEFAULT_CTX)

    # Build daily chart for last `days`
    chart_labels = []
    chart_values = []
    for i in range(days - 1, -1, -1):
        d = (datetime.now(timezone.utc) - timedelta(days=i)).strftime("%Y-%m-%d")
        dd = daily.get(d, {})
        tokens = (
            dd.get("input_tokens", 0) + dd.get("output_tokens", 0)
            + dd.get("cache_read", 0) + dd.get("cache_creation", 0)
        )
        chart_labels.append(d[5:] if i % 5 == 0 else "")  # MM-DD every 5 days
        chart_values.append(tokens)

    return {
        "today": {
            "tokens": today_tokens,
            "messages": today_data.get("messages", 0),
            "sessions": today_data.get("sessions", 0),
            "input": today_data.get("input_tokens", 0),
            "output": today_data.get("output_tokens", 0),
            "cache_read": today_data.get("cache_read", 0),
            "cache_creation": today_data.get("cache_creation", 0),
        },
        "week": {
            "tokens": week_tokens,
            "messages": week_messages,
            "sessions": week_sessions,
        },
        "window": {
            "total_tokens": total_tokens,
            "days": days,
        },
        "primary_model": primary_model,
        "ctx_window": ctx_window,
        "by_model": by_model,
        "chart": {
            "labels": chart_labels,
            "values": chart_values,
        },
    }


def _fmt(n: int) -> str:
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)


def main() -> int:
    parser = argparse.ArgumentParser(description="Claude Code token usage reader.")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    stats = compute_stats(args.days)

    if args.as_json:
        print(json.dumps(stats, indent=2))
        return 0

    print(f"=== Claude Code Usage ({args.days}d window) ===")
    print(f"Today    {_fmt(stats['today']['tokens'])} tokens  "
          f"({stats['today']['messages']} msgs, {stats['today']['sessions']} sessions)")
    print(f"7 days   {_fmt(stats['week']['tokens'])} tokens  "
          f"({stats['week']['messages']} msgs, {stats['week']['sessions']} sessions)")
    print(f"Total    {_fmt(stats['window']['total_tokens'])} tokens in {args.days}d")
    print(f"Model    {stats['primary_model']} (ctx {_fmt(stats['ctx_window'])})")
    print()
    print("By model:")
    for model, mu in sorted(stats["by_model"].items()):
        total = mu["input_tokens"] + mu["output_tokens"] + mu["cache_read"] + mu["cache_creation"]
        print(f"  {model:<40} {_fmt(total)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
