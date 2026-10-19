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
import contextlib
import json
import logging
import os
import shutil
import subprocess
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

CLAUDE_DIR = Path.home() / ".claude"
_PROTO = Path(__file__).resolve().parents[1]         # agentic-os/

def _find_workspace_claude_dir() -> Path:
    # Walk up from _PROTO collecting all .claude dirs that have rate-limits-live.json,
    # then return the one with the most recently modified file.
    p = _PROTO
    candidates: list[tuple[float, Path]] = []
    for _ in range(5):
        candidate = p / ".claude"
        f = candidate / "rate-limits-live.json"
        if f.exists():
            candidates.append((f.stat().st_mtime, candidate))
        p = p.parent
    if candidates:
        return max(candidates)[1]
    return _PROTO / ".claude"  # fallback

_workspace_claude_env = os.environ.get("WORKSPACE_CLAUDE_DIR", "").strip()
WORKSPACE_CLAUDE_DIR = Path(_workspace_claude_env).expanduser() if _workspace_claude_env else _find_workspace_claude_dir()
PROJECTS_DIR = CLAUDE_DIR / "projects"
STATS_CACHE = CLAUDE_DIR / "stats-cache.json"
CODEX_DB = Path.home() / ".codex" / "state_5.sqlite"
CODEX_SESSIONS_DIR = Path.home() / ".codex" / "sessions"
CODEX_LIVE_RATE_LIMITS_PATH = Path.home() / ".codex" / "rate-limits-live.json"
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
    "claude-opus-5-5":            20.00,  # claude.com/pricing 2026-10-16: $4 in / $20 out per MTok
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

_AGY_CACHE_TTL_S = 55.0
_AGY_MAX_AGE_S = 15 * 60
_agy_lock = threading.Lock()
_agy_groups: dict[str, dict] = {}
_agy_attempt_at = 0.0
_agy_error: str | None = None
_agy_refreshing = False


def parse_agy_usage(text: str) -> dict[str, dict]:
    """Parse Antigravity's tab-separated weekly quota records."""
    groups: dict[str, dict] = {}
    for line in text.splitlines():
        fields = line.split("\t")
        if len(fields) != 4:
            continue
        group, _, raw_pct, raw_reset = (field.strip() for field in fields)
        name = group.casefold()
        key = "gemini" if name.startswith("gemini") else "claude_gpt" if "claude" in name else None
        if key is None:
            continue
        try:
            if not raw_pct.endswith("%"):
                continue
            remaining_pct = max(0, min(100, int(raw_pct[:-1])))
        except ValueError:
            continue
        try:
            resets_at = datetime.fromisoformat(raw_reset.replace("Z", "+00:00"))
            if resets_at.tzinfo is None:
                resets_at = None
        except ValueError:
            resets_at = None
        groups[key] = {"remaining_pct": remaining_pct, "resets_at": resets_at}
    return groups


def fetch_agy_usage(timeout_s: float = 15.0) -> tuple[dict, str | None]:
    """Fetch Antigravity quotas without exposing CLI output in logs or errors."""
    try:
        agy_bin = shutil.which("agy") or str(Path.home() / ".local" / "bin" / "agy")
        if not Path(agy_bin).is_file() or not os.access(agy_bin, os.X_OK):
            logger.warning("agy quota fetch: not_installed")
            return {}, "not_installed"
        result = subprocess.run(
            [agy_bin, "--log-file", "/dev/null", "-p", "/usage"],
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
            errors="replace", timeout=timeout_s,
        )
        if result.returncode != 0:
            code = f"exit_{result.returncode}"
            logger.warning("agy quota fetch: %s rc=%s stdout_bytes=%s stderr_bytes=%s",
                           code, result.returncode, len(result.stdout.encode("utf-8")),
                           len(result.stderr.encode("utf-8")))
            return {}, code
        groups = parse_agy_usage(result.stdout)
        if not groups:
            logger.warning("agy quota fetch: unparseable rc=0 stdout_bytes=%s stderr_bytes=%s",
                           len(result.stdout.encode("utf-8")), len(result.stderr.encode("utf-8")))
            return {}, "unparseable"
        return groups, None
    except (FileNotFoundError, PermissionError):
        logger.warning("agy quota fetch: not_installed")
        return {}, "not_installed"
    except subprocess.TimeoutExpired:
        logger.warning("agy quota fetch: timeout")
        return {}, "timeout"
    except Exception:
        logger.warning("agy quota fetch: error")
        return {}, "error"


def _refresh_agy(fetch: Callable[[], tuple[dict, str | None]]) -> None:
    global _agy_error, _agy_refreshing
    try:
        groups, error = fetch()
        fetched_at = datetime.now(timezone.utc)
        with _agy_lock:
            for key in ("gemini", "claude_gpt"):
                if key in groups:
                    _agy_groups[key] = {**groups[key], "fetched_at": fetched_at}
            missing = {"gemini", "claude_gpt"} - groups.keys()
            _agy_error = error or (
                None if not missing else
                "unparseable" if len(missing) == 2 else
                f"partial_{missing.pop()}"
            )
    except Exception:
        with _agy_lock:
            _agy_error = "error"
        logger.warning("agy quota refresh: error")
    finally:
        with _agy_lock:
            _agy_refreshing = False


def load_agy_usage(fetch: Callable[[], tuple[dict, str | None]] = fetch_agy_usage) -> tuple[dict, str | None]:
    """Return cached quotas immediately, starting one background refresh when due."""
    global _agy_attempt_at, _agy_error, _agy_refreshing
    with _agy_lock:
        now = time.monotonic()
        if not _agy_refreshing and now - _agy_attempt_at >= _AGY_CACHE_TTL_S:
            _agy_refreshing = True
            _agy_attempt_at = now
            try:
                threading.Thread(target=_refresh_agy, args=(fetch,), daemon=True).start()
            except Exception:
                _agy_refreshing = False
                _agy_error = "error"
                logger.warning("agy quota refresh: error")
        return {key: dict(value) for key, value in _agy_groups.items()}, _agy_error


def agy_card_state(entry: dict | None, now: datetime) -> tuple[str, float | None]:
    """Classify one cached group without Flask or mutable cache state."""
    if entry is None:
        return "missing", None
    try:
        age_s = max(0.0, (now - entry["fetched_at"]).total_seconds())
        resets_at = entry.get("resets_at")
        if age_s > _AGY_MAX_AGE_S or (resets_at is not None and resets_at <= now):
            return "stale", age_s
        return "fresh", age_s
    except (KeyError, TypeError, ValueError):
        return "stale", None


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _date_of(ts: str) -> str:
    try:
        return datetime.fromisoformat(ts).strftime("%Y-%m-%d")
    except Exception:
        return "?"


# ponytail: unbounded per-file caches (one entry per session file); prune if file counts explode
_file_caches: dict[str, dict[str, tuple[tuple[int, int], Any]]] = defaultdict(dict)


def _cached_by_stat(kind: str, path: Path, st: os.stat_result, compute: Callable[[Path], Any]) -> Any:
    """Re-run compute(path) only when the file's (mtime, size) changed since last call."""
    key = (st.st_mtime_ns, st.st_size)
    cache = _file_caches[kind]
    hit = cache.get(str(path))
    if hit and hit[0] == key:
        return hit[1]
    value = compute(path)
    cache[str(path)] = (key, value)
    return value


SESSION_TRASH_DIR = Path(os.environ.get("AGENTIC_OS_SESSION_TRASH", "~/.agentic-os/session-trash")).expanduser()


def _codex_rollouts():
    """Every Codex rollout: live sessions and archived ones (archived threads still consumed
    tokens and may hold the newest quota snapshot, IR19-02/R21-02)."""
    yield from CODEX_SESSIONS_DIR.rglob("*.jsonl")
    archived = CODEX_SESSIONS_DIR.parent / "archived_sessions"
    if archived.is_dir():
        yield from archived.glob("*.jsonl")


def _claude_jsonl_files():
    """Yield (path, stat) for every Claude project session JSONL, including transcripts the
    dashboard moved to its session trash: removing a session never un-counts its usage (IR19-02)."""
    dirs = [d for root in (PROJECTS_DIR, SESSION_TRASH_DIR) if root.exists() for d in root.iterdir()]
    for project_dir in dirs:
        if not project_dir.is_dir():
            continue
        for jsonl_path in project_dir.glob("*.jsonl"):
            try:
                yield jsonl_path, jsonl_path.stat()
            except OSError:
                continue


def _claude_usage_records(path: Path) -> list[tuple]:
    """Assistant usage records in one Claude JSONL:
    (ts_str, ts|None, model, session_id, input, output, cache_read, cache_creation)."""
    records: list[tuple] = []
    try:
        for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if '"assistant"' not in raw:
                continue
            try:
                record = json.loads(raw)
            except Exception:
                continue
            if record.get("type") != "assistant":
                continue
            msg = record.get("message", {})
            usage = msg.get("usage", {})
            if not usage:
                continue
            ts_str = record.get("timestamp", "")
            ts = None
            if ts_str:
                try:
                    ts = datetime.fromisoformat(ts_str)
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                except Exception:
                    ts = None
            records.append((
                ts_str, ts, msg.get("model", "unknown"), record.get("sessionId", ""),
                usage.get("input_tokens", 0), usage.get("output_tokens", 0),
                usage.get("cache_read_input_tokens", 0), usage.get("cache_creation_input_tokens", 0),
            ))
    except Exception:
        pass
    return records


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

    for jsonl_path, st in _claude_jsonl_files():
        for ts_str, _ts, model, session_id, inp, out, cr, cc in _cached_by_stat(
                "claude", jsonl_path, st, _claude_usage_records):
            date = _date_of(ts_str) if ts_str else "?"
            if date < since_date:
                continue

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
                     "_balance_snapshots", "stale", "last_error", "spend_scope"):
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
        if "window_5h_reset" in ag:
            result["window_5h_reset"] = ag["window_5h_reset"]
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


def _codex_last_rate_event(path: Path) -> tuple[str, datetime, dict] | None:
    """Classify the last token_count rate-limit event in one session JSONL:
    ("codex", ts, snapshot) | ("limit_hit", ts, {}) | ("other", ts, {}) | None."""
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return None
    # Scan from newest to oldest; only the last token_count per file counts.
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
        ts = _parse_iso_utc(record.get("timestamp"))
        if ts is None:
            continue
        if rate.get("limit_id") == "codex":
            info = payload.get("info") or {}
            total = (info.get("total_token_usage") or {}).get("total_tokens")
            return "codex", ts, {
                "timestamp": record.get("timestamp"),
                "plan_type": rate.get("plan_type"),
                "primary": rate.get("primary") or {},
                "secondary": rate.get("secondary") or {},
                "total_tokens": int(total) if isinstance(total, (int, float)) else None,
                "model_context_window": info.get("model_context_window"),
            }
        if rate.get("primary") is None and not (rate.get("credits") or {}).get("has_credits", True):
            # limit_id switched away from "codex" with null windows = limit hit
            return "limit_hit", ts, {}
        return "other", ts, {}
    return None


def load_latest_codex_rate_limits() -> dict[str, Any]:
    """Read the latest server-reported Codex rate limit snapshot.

    Checks ~/.codex/rate-limits-live.json first (written by codex_snap_rate_limits.py
    hook after each session). Falls back to scanning session JSONL files directly.
    """
    now = datetime.now(timezone.utc)

    # Live file written by hook — use if < 30 min old
    if CODEX_LIVE_RATE_LIMITS_PATH.exists():
        try:
            live = json.loads(CODEX_LIVE_RATE_LIMITS_PATH.read_text(encoding="utf-8"))
            captured = _parse_iso_utc(live.get("captured_at"))
            if captured and now - captured <= timedelta(minutes=30):
                return {
                    "timestamp": live.get("captured_at"),
                    "plan_type": live.get("plan_type"),
                    "primary":   live.get("primary") or {},
                    "secondary": live.get("secondary") or {},
                }
        except Exception:
            pass

    if not CODEX_SESSIONS_DIR.exists():
        return {}

    try:
        best_ts: datetime | None = None
        best: dict[str, Any] = {}
        # Track the most recent "limit hit" signal: limit_id != "codex" with null primary
        limit_hit_ts: datetime | None = None

        for path in _codex_rollouts():  # archived ones too: removing a session never hides its quota snapshot (R21-02)
            try:
                st = path.stat()
            except OSError:
                continue
            event = _cached_by_stat("codex_rate", path, st, _codex_last_rate_event)
            if event is None:
                continue
            kind, ts, snapshot = event
            if kind == "codex":
                if best_ts is None or ts > best_ts:
                    best_ts = ts
                    best = dict(snapshot)
            elif kind == "limit_hit":
                if limit_hit_ts is None or ts > limit_hit_ts:
                    limit_hit_ts = ts

        # If a limit-hit event is newer than the last codex quota snapshot, mark as exhausted.
        if limit_hit_ts and (best_ts is None or limit_hit_ts > best_ts):
            pri = best.get("primary") or {}
            best["primary"] = {**pri, "used_percent": 100}
            best["limit_hit"] = True
            best["limit_hit_at"] = limit_hit_ts.isoformat()
            if not best.get("timestamp"):
                best["timestamp"] = limit_hit_ts.isoformat()

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

    for jsonl_path, st in _claude_jsonl_files():
        # Last write precedes window start → no record inside it; skip without reading.
        if st.st_mtime < since.timestamp():
            continue
        for _ts_str, ts, _model, sid, i, o, _cr, c in _cached_by_stat(
                "claude", jsonl_path, st, _claude_usage_records):
            if ts is None or not (since <= ts < until):
                continue
            # Exclude cache_read_input_tokens: billed at 0.1x, inflates count 10-20x
            tokens += i + o + c
            out += o
            if sid:
                sessions.add(sid)
            if earliest_ts is None or ts < earliest_ts:
                earliest_ts = ts

    return {"tokens": tokens, "sessions": len(sessions), "output": out, "earliest_ts": earliest_ts}


def _codex_session_summary(path: Path) -> tuple[datetime, str, int] | None:
    """(start ts, session id, total tokens) for one Codex session JSONL."""
    summary = None
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        first = next((json.loads(l) for l in lines if l.strip()), None)
        ts_str = (first or {}).get("timestamp", "")
        if ts_str:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            # Session ID is in payload.id for session_meta events, or in the filename
            sid = (first.get("payload") or {}).get("id", "")
            if not sid:
                sid = first.get("sessionId", "") or first.get("session_id", "")
            if not sid:
                _m = __import__("re").search(r"[\da-f]{8}-[\da-f]{4}-[\da-f]{4}-[\da-f]{4}-[\da-f]{12}", path.name)
                if _m:
                    sid = _m.group()
            tokens = 0
            # Find the last token_count event with actual info (skip null info entries)
            for raw in reversed(lines):
                if '"type":"token_count"' not in raw:
                    continue
                try:
                    payload = json.loads(raw).get("payload", {})
                except Exception:
                    continue
                if payload.get("type") != "token_count":
                    continue
                ttu = (payload.get("info") or {}).get("total_token_usage", {})
                if not ttu:
                    continue
                tokens = ((ttu.get("input_tokens", 0) or 0) + (ttu.get("output_tokens", 0) or 0)
                          + (ttu.get("cached_input_tokens", 0) or 0))
                break
            summary = (ts, sid, tokens)
    except Exception:
        summary = None
    return summary


def _codex_window_range(since: datetime, until: datetime) -> dict[str, Any]:
    """Aggregate Codex token usage between two datetimes, including cached input tokens.

    Reads session JSONL files for full token counts (input + output + cached_input),
    falling back to SQLite threads.tokens_used (input + output only) when JSONL
    is unavailable.
    """
    total_tokens = 0
    sessions: set[str] = set()
    earliest_ts: datetime | None = None

    if CODEX_SESSIONS_DIR.exists():
        try:
            for path in _codex_rollouts():
                try:
                    st = path.stat()
                except OSError:
                    continue
                # Last write precedes session start? Impossible — skip without reading.
                if st.st_mtime < since.timestamp():
                    continue
                summary = _cached_by_stat("codex_session", path, st, _codex_session_summary)
                if summary is None:
                    continue
                ts, sid, tokens = summary
                if not (since <= ts < until):
                    continue
                if sid:
                    sessions.add(sid)
                if earliest_ts is None or ts < earliest_ts:
                    earliest_ts = ts
                total_tokens += tokens
        except Exception:
            pass

    # Fallback: use SQLite threads table (input + output only, no cache)
    if not sessions and CODEX_DB.exists():
        try:
            import sqlite3
            db = sqlite3.connect(str(CODEX_DB))
            r = db.execute(
                "SELECT COALESCE(SUM(tokens_used),0), COUNT(*), MIN(created_at) FROM threads "
                "WHERE created_at >= ? AND created_at < ? AND tokens_used > 0",
                (since.timestamp(), until.timestamp()),
            ).fetchone()
            total_tokens = int(r[0])
            if not earliest_ts and r[2]:
                earliest_ts = datetime.fromtimestamp(r[2], tz=timezone.utc)
            _cnt = int(r[1])
        except Exception:
            pass

    return {"tokens": total_tokens, "sessions": len(sessions), "output": 0, "earliest_ts": earliest_ts}


def _deepseek_window_range(since: datetime, until: datetime) -> dict[str, Any]:
    """DeepSeek tokens are unknown at account level; the monitor tracks spend from balance changes."""
    return {"tokens": None, "sessions": None, "output": 0, "earliest_ts": None}


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


def _next_daily_reset_label(cfg: dict, now: datetime) -> str:
    """Compute time-until-reset from a daily anchor (hour + minute + tz)."""
    try:
        from zoneinfo import ZoneInfo
        _tz = ZoneInfo(cfg["tz"])
        _nl = now.astimezone(_tz)
        _tr = _nl.replace(hour=cfg["hour"], minute=cfg["minute"], second=0, microsecond=0)
        if _nl >= _tr:
            _tr += timedelta(days=1)
        _secs = int((_tr.astimezone(timezone.utc) - now).total_seconds())
        if _secs <= 300:
            return "NOW"
        _h, _r = divmod(_secs, 3600)
        _m = _r // 60
        _d, _h = divmod(_h, 24)
        if _d > 0:
            return f"{_d}d{_h:02d}h"
        return f"{_h}h{_m:02d}m" if _h else f"{_m}m"
    except Exception:
        return "—"


def _next_daily_reset_ts(cfg: dict, now: datetime) -> int:
    """Return Unix timestamp of the next daily reset."""
    try:
        from zoneinfo import ZoneInfo
        _tz = ZoneInfo(cfg["tz"])
        _nl = now.astimezone(_tz)
        _tr = _nl.replace(hour=cfg["hour"], minute=cfg["minute"], second=0, microsecond=0)
        if _nl >= _tr:
            _tr += timedelta(days=1)
        return int(_tr.astimezone(timezone.utc).timestamp())
    except Exception:
        return int(now.timestamp())


def _prev_daily_reset_dt(cfg: dict, now: datetime) -> datetime:
    """Return the most recent daily reset datetime (UTC) before now."""
    try:
        from zoneinfo import ZoneInfo
        _tz = ZoneInfo(cfg["tz"])
        _nl = now.astimezone(_tz)
        _tr = _nl.replace(hour=cfg["hour"], minute=cfg["minute"], second=0, microsecond=0)
        if _nl < _tr:
            _tr -= timedelta(days=1)
        return _tr.astimezone(timezone.utc)
    except Exception:
        return now - timedelta(hours=5)


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

    _w5h_r_cfg = limits.get("window_5h_reset")
    if _w5h_r_cfg:
        _w5h_since = _prev_daily_reset_dt(_w5h_r_cfg, now)
    else:
        _w5h_since = now - timedelta(hours=5)
    cur_5h  = _range(_w5h_since,  now)
    pri_5h  = _range(_w5h_since - timedelta(hours=5), _w5h_since)
    cur_7d  = _range(now - timedelta(days=7),   now)
    pri_7d  = _range(now - timedelta(days=14),  now - timedelta(days=7))

    lim_5h = limits["window_5h"]
    lim_7d = limits["window_7d"]
    lim_runs = limits["daily_runs_max"]

    def _pct(val: int, lim: int) -> int:
        return min(100, round(val / lim * 100)) if lim else 0

    # Compute today stats per agent
    if agent == "codex":
        _codex_usage = load_codex_usage()
        _today_codex = _codex_usage.get("today", {})
        today_stats = {
            "tokens": int(_today_codex.get("tokens", 0) or 0),
            "sessions": int(_today_codex.get("sessions", 0) or 0),
            "cost": 0.0,
        }
    else:
        today_stats = _today_stats_claude(now)

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

        _total_cost = float(_ds_usage.get("total_cost_cny", 0) or 0)
        _total_value = _bal_cny + _total_cost
        _total_pct = min(100, round(_total_cost / _total_value * 100)) if _total_value > 0 else 0
        _total_rem = max(0, 100 - _total_pct)
        # Tokens are unknown at account level (per-run tokens are in run records).
        _ds_tok = 0
        _ds_tok_fmt = "n/a"
        _stale = bool(_ds_usage.get("stale"))
        return {
            "agent": agent, "limits_estimated": True,
            "quota_source": "usage.json",
            "balance_cny": round(_bal_cny, 2),
            "stale": _stale,
            "last_error": _ds_usage.get("last_error"),
            "window_5h": {
                "title": "Total Spend", "reset": "Tracked",
                "pct": _total_pct, "remaining_pct": _total_rem,
                "tokens": _ds_tok, "limit": _ds_tok,
                "value_line": f"¥{_total_cost:.2f} / ¥{_total_value:.2f}",
                "sub_line": f"¥{_bal_cny:.2f} remaining · {_ds_tok_fmt} tokens" + (" · stale" if _stale else ""),
                "display_line": f"¥{_total_cost:.2f} spent · ¥{_bal_cny:.2f} left · {_ds_tok_fmt} tokens"
                                + " · account-level (all uses of this key, incl. ask_deepseek.py)"
                                + (" · stale" if _stale else ""),
                "resets_at_unix": None, "window_minutes": 0,
            },
            "window_7d": {
                "title": "Balance", "reset": "—",
                "pct": 0, "remaining_pct": None,
                "tokens": int(_bal_cny * 100), "limit": int(_total_cost * 100),
                "value_line": f"¥{_bal_cny:.2f}",
                "sub_line": f"¥{_total_cost:.2f} spent to date",
                "display_line": f"¥{_bal_cny:.2f} balance · ¥{_total_cost:.2f} spent",
                "resets_at_unix": None, "window_minutes": 0,
            },
            "aux": {
                "title": "Recent Spend", "reset": midnight_label,
                "pct": _cost_pct(_cost_5h, CAP_5H) if CAP_5H else 0,
                "value_line": f"¥{_cost_5h:.2f} (5h) · ¥{_cost_weekly:.2f} (7d)",
                "sub_line": f"¥{_cost_monthly:.2f} (30d) · account-level, all uses of this key",
                "tokens": int(_cost_5h * 100),
                "display_line": f"¥{_cost_5h:.2f} last 5h · ¥{_cost_weekly:.2f} last 7d",
                "resets_at_unix": None, "window_minutes": 0,
            },
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

    # today_stats was computed above per agent

    if agent == "codex":
        codex_live = load_latest_codex_rate_limits()
        codex_captured = _parse_iso_utc(codex_live.get("timestamp"))
        pri = codex_live.get("primary") or {}
        sec = codex_live.get("secondary") or {}

        # Codex may move the only weekly window between primary and secondary.
        # Identify it by duration so the dashboard does not mistake weekly data
        # for the removed 5-hour limit.
        quota_windows = [w for w in (pri, sec) if isinstance(w, dict) and w]
        weekly = next(
            (w for w in quota_windows
             if int(w.get("window_minutes") or w.get("windowDurationMins") or 0) >= 10080),
            None,
        ) or (quota_windows[0] if quota_windows else {})
        weekly_resets_at = weekly.get("resets_at")
        weekly_resets_dt = (
            datetime.fromtimestamp(float(weekly_resets_at), tz=timezone.utc)
            if weekly_resets_at else None
        )
        server_weekly_reset_valid = bool(weekly_resets_dt and weekly_resets_dt > now)
        weekly_window_minutes = int(
            weekly.get("window_minutes") or weekly.get("windowDurationMins") or 10080
        )

        # Use server pct whenever the snapshot is fresh or its weekly reset is
        # still in the future. Local token counts span windows and are only a
        # fallback when no trustworthy server snapshot is available.
        snapshot_fresh = bool(codex_captured and (
            server_weekly_reset_valid
            or now - codex_captured <= timedelta(hours=2)
        ))
        if snapshot_fresh:
            used_weekly = _window_percent_from_snapshot(
                weekly.get("used_percent", 0),
                weekly_resets_at,
                codex_captured,
                now,
            )
            _pct_weekly = used_weekly
            _disp_tok_weekly = int(used_weekly * lim_7d / 100) if used_weekly > 0 else 0
            _reset_weekly_label = _reset_label_from_epoch(weekly_resets_at, now)
            _quota_src = "server"
            _limits_est = False
        else:
            _pct_weekly = _pct(cur_7d["tokens"], lim_7d)
            _disp_tok_weekly = cur_7d["tokens"]
            _reset_weekly_label = (
                _reset_label_from_epoch(weekly_resets_at, now) if server_weekly_reset_valid
                else _next_weekly_reset_label(weekly_reset_cfg, now) if weekly_reset_cfg
                else _reset_label(cur_7d.get("earliest_ts"), 168, now)
            )
            _quota_src = "server+local"
            _limits_est = True

        weekly_card = {
            "title":         "Weekly",
            "tokens":        _disp_tok_weekly,
            "limit":         lim_7d,
            "pct":           _pct_weekly,
            "remaining_pct": max(0, 100 - _pct_weekly),
            "sessions":      cur_7d["sessions"],
            "reset":         _reset_weekly_label,
            "display_line":  (
                f"{_fmt_tok(_disp_tok_weekly)} / {_fmt_tok(lim_7d)} · "
                f"{max(0, 100 - _pct_weekly)}% remaining"
                if snapshot_fresh else
                f"{_fmt_tok(_disp_tok_weekly)} / {_fmt_tok(lim_7d)} · {cur_7d['sessions']} sessions"
            ),
            "resets_at_unix": weekly_resets_at if server_weekly_reset_valid else None,
            "window_minutes": weekly_window_minutes,
        }
        return {
            "agent": agent,
            "limits_estimated": _limits_est,
            "quota_source": _quota_src,
            "window_5h": dict(weekly_card),
            "window_7d": dict(weekly_card),
            "aux": {
                "title":      "Today Tokens",
                "reset":      midnight_label,
                "pct":        _pct(today_stats["tokens"], lim_7d // 7),
                "value_line": f"{_fmt_tok(today_stats['tokens'])} tokens",
                "sub_line":   (
                    f"{today_stats['sessions']} session"
                    f"{'s' if today_stats['sessions'] != 1 else ''}"
                    + (f" · snapshot {codex_captured.strftime('%H:%M')} UTC" if codex_captured else "")
                ),
            },
        }

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
            # Derive effective limits from server pct + JSONL token counts
            _eff_5h = int(cur_5h["tokens"] / (used_5h / 100)) if used_5h > 0 else lim_5h
            _eff_7d = int(cur_7d["tokens"] / (used_7d / 100)) if used_7d > 0 else lim_7d
            return {
                "agent": agent,
                "limits_estimated": False,
                "quota_source": "server",
                "window_5h": {
                    "tokens":        cur_5h["tokens"],
                    "limit":         _eff_5h,
                    "pct":           used_5h,
                    "remaining_pct": max(0, 100 - used_5h),
                    "sessions":      cur_5h["sessions"],
                    "reset":         _reset_label_from_epoch(five.get("resets_at"), now),
                    "display_line":  f"{_fmt_tok(cur_5h['tokens'])} / {_fmt_tok(_eff_5h)} · {cur_5h['sessions']} sessions",
                    "resets_at_unix": five.get("resets_at"),
                    "window_minutes": 300,
                },
                "window_7d": {
                    "tokens":        cur_7d["tokens"],
                    "limit":         _eff_7d,
                    "pct":           used_7d,
                    "remaining_pct": max(0, 100 - used_7d),
                    "sessions":      cur_7d["sessions"],
                    "reset":         _reset_label_from_epoch(seven.get("resets_at"), now),
                    "display_line":  f"{_fmt_tok(cur_7d['tokens'])} / {_fmt_tok(_eff_7d)} · {cur_7d['sessions']} sessions",
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

    # Reset labels: 5h uses window_5h_reset if configured, else earliest_ts; 7d uses weekly_reset if available
    _w5h_r = limits.get("window_5h_reset")
    _reset_5h = _next_daily_reset_label(_w5h_r, now) if _w5h_r and cur_5h.get("earliest_ts") else _reset_label(cur_5h.get("earliest_ts"), 5, now)
    _reset_7d = (
        _next_weekly_reset_label(weekly_reset_cfg, now)
        if weekly_reset_cfg
        else _reset_label(cur_7d.get("earliest_ts"), 168, now)
    )

    # Pace marker for rolling windows: use earliest usage timestamp
    _e5 = cur_5h.get("earliest_ts")
    _e7 = cur_7d.get("earliest_ts")
    _resets_5h = _next_daily_reset_ts(_w5h_r, now) if _w5h_r else (int(_e5.timestamp()) + 300 * 60 if _e5 else int(now.timestamp()))
    if weekly_reset_cfg:
        try:
            from zoneinfo import ZoneInfo
            _tz = ZoneInfo(weekly_reset_cfg["tz"])
            _nl = now.astimezone(_tz)
            _da = weekly_reset_cfg["weekday"] - _nl.weekday()
            if _da < 0:
                _da += 7
            elif _da == 0 and (_nl.hour, _nl.minute) >= (weekly_reset_cfg["hour"], weekly_reset_cfg["minute"]):
                _da += 7
            _nr = _nl.replace(hour=weekly_reset_cfg["hour"], minute=weekly_reset_cfg["minute"], second=0, microsecond=0) + timedelta(days=_da)
            _resets_7d = int(_nr.astimezone(timezone.utc).timestamp())
        except Exception:
            _resets_7d = int(_e7.timestamp()) + 10080 * 60 if _e7 else int(now.timestamp())
    else:
        _resets_7d = int(_e7.timestamp()) + 10080 * 60 if _e7 else int(now.timestamp())

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
            "reset":         _reset_5h,
            "estimate_only": True,
            "display_line":  f"{_fmt_tok(cur_5h['tokens'])} / {_fmt_tok(lim_5h)} · {cur_5h['sessions']} sessions",
            "resets_at_unix": _resets_5h,
            "window_minutes": 300,
        },
        "window_7d": {
            "tokens":        cur_7d["tokens"],
            "limit":         lim_7d,
            "pct":           _real_7d_pct,
            "remaining_pct": _rem(cur_7d["tokens"], lim_7d),
            "sessions":      cur_7d["sessions"],
            "reset":         _reset_7d,
            "estimate_only": True,
            "display_line":  f"{_fmt_tok(cur_7d['tokens'])} / {_fmt_tok(lim_7d)} · {cur_7d['sessions']} sessions",
            "resets_at_unix": _resets_7d,
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


# ── Context-window usage of one agent session (card detail ctx%) ─────────────

CTX_TAIL_BYTES = 2_000_000
CTX_1M = 1_000_000
_STREAM_MODELS: dict[str, tuple[int, int, str | None]] = {}  # path -> (inode, offset, model)
_STREAM_MODELS_LOCK = threading.Lock()


def _tail_lines(path: Path, limit: int | None = None) -> list[str]:
    """Lines of the file's last `limit` bytes, newest first; [] when unreadable.
    ponytail: a fixed tail; usage written further back shows nothing (reverse block reader if needed)."""
    limit = limit or CTX_TAIL_BYTES
    try:
        with open(path, "rb") as f:
            size = f.seek(0, os.SEEK_END)
            start = max(0, size - limit)
            f.seek(start)
            data = f.read()
    except OSError:
        return []
    lines = data.decode("utf-8", errors="ignore").splitlines()
    if start and lines:
        lines = lines[1:]  # a read starting mid-file begins with a partial line
    return lines[::-1]


def _tok(*values) -> int | None:
    """Sum of token counts, None when any is not a non-negative int (missing counts as 0)."""
    total = 0
    for v in values:
        if v is None:
            continue
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            return None
        total += v
    return total


def _ctx_line(agent: str, raw: str) -> tuple[int, int | None] | None:
    """(used, reported window) from one JSONL line, or None when it carries no usable usage."""
    try:
        r = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(r, dict):
        return None
    if agent == "codex":
        p = r.get("payload")
        info = p.get("info") if isinstance(p, dict) and p.get("type") == "token_count" else None
        last = info.get("last_token_usage") if isinstance(info, dict) else None
        if not isinstance(last, dict) or not isinstance(last.get("input_tokens"), int):
            return None
        used = _tok(last["input_tokens"])
        win = info.get("model_context_window")
        return (used, win if isinstance(win, int) and not isinstance(win, bool) and win > 0 else None) \
            if used is not None else None
    if agent == "dsh":
        u = r.get("usage")
        if r.get("type") != "status" or r.get("phase") != "step_end" or not isinstance(u, dict) \
                or not isinstance(u.get("inputTokens"), int):
            return None
        used = _tok(u["inputTokens"], u.get("cacheReadTokens"), u.get("cacheWriteTokens"))
        return (used, CTX_1M) if used is not None else None  # dsh-llm-deepseek DEFAULT_CONTEXT_WINDOW = 1e6
    m = r.get("message")
    if r.get("type") != "assistant" or r.get("isSidechain") is True or not isinstance(m, dict) \
            or m.get("model") == "<synthetic>" or not isinstance(m.get("usage"), dict):
        return None
    u = m["usage"]
    if not isinstance(u.get("input_tokens"), int):
        return None
    used = _tok(u["input_tokens"], u.get("cache_read_input_tokens"), u.get("cache_creation_input_tokens"))
    return (used, None) if used is not None else None


def context_usage(agent: str, path: Path | None, model: str | None = None) -> dict | None:
    """{used, window, pct} from the newest main-thread model call in a session file, or None.
    used = prompt-side tokens of that call (output excluded, like Claude Code's status line)."""
    if path is None:
        return None
    for raw in _tail_lines(Path(path)):
        hit = _ctx_line(agent, raw)
        if hit is None:
            continue
        used, window = hit
        if agent == "claude":
            window = CTX_1M if (model or "").endswith("[1m]") or used > DEFAULT_CTX else DEFAULT_CTX
        pct = min(100, round(used * 100 / window)) if window else None
        out = {"used": used, "window": window, "pct": pct}
        if agent == "dsh":
            # dsh's step_end sums every attempt of the step, so a retried attempt that reported
            # usage counts twice; its stream has no per-call usage (CTX-009). An upper bound.
            out["approx"] = True
        return out
    return None


def stream_model(path: Path | None) -> str | None:
    """Model of the newest stream-json init event in a Claude stream log. Scans only the bytes
    appended since the last call, so an old init line never falls out of view (D6)."""
    if path is None:
        return None
    key = str(path)
    with _STREAM_MODELS_LOCK:
        try:
            with open(path, "rb") as f:
                st = os.fstat(f.fileno())
                inode, offset, model = _STREAM_MODELS.get(key, (st.st_ino, 0, None))
                if inode != st.st_ino or st.st_size < offset:
                    offset, model = 0, None
                f.seek(offset)
                data = f.read()
        except OSError:
            return None
        end = data.rfind(b"\n") + 1  # only whole lines; a partial last line is read next time
        for raw in data[:end].splitlines():
            if b'"subtype":"init"' not in raw and b'"subtype": "init"' not in raw:
                continue
            with contextlib.suppress(ValueError):
                r = json.loads(raw)
                if isinstance(r, dict) and r.get("type") == "system" and r.get("subtype") == "init" \
                        and isinstance(r.get("model"), str):
                    model = r["model"]
        _STREAM_MODELS[key] = (st.st_ino, offset + end, model)
        return model


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
