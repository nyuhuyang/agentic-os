#!/usr/bin/env python3
"""Snapshot the latest Codex rate-limit data to ~/.codex/rate-limits-live.json.

Run this after each Codex session ends (wire as a hook). The dashboard reads
this file instead of scanning all session JSONLs, giving a fresh reading.

Usage:
    python3 codex_snap_rate_limits.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SESSIONS_DIR = Path.home() / ".codex" / "sessions"
OUT_PATH = Path.home() / ".codex" / "rate-limits-live.json"


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


def snap() -> dict | None:
    if not SESSIONS_DIR.exists():
        return None

    best_ts: datetime | None = None
    best: dict = {}

    for path in SESSIONS_DIR.rglob("*.jsonl"):
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception:
            continue
        for raw in reversed(lines):
            if '"token_count"' not in raw or '"rate_limits"' not in raw:
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
            if ts is None:
                continue
            if best_ts is None or ts > best_ts:
                best_ts = ts
                best = {
                    "captured_at": record.get("timestamp"),
                    "plan_type": rate.get("plan_type"),
                    "primary": rate.get("primary") or {},
                    "secondary": rate.get("secondary") or {},
                }
            break  # newest token_count per file is sufficient

    if not best or best_ts is None:
        return None

    return best


def main() -> int:
    result = snap()
    if not result:
        print("No Codex rate-limit data found in session files.", file=sys.stderr)
        return 1

    # Don't overwrite if existing live file is already newer than what we found.
    new_ts = _parse_iso_utc(result.get("captured_at"))
    if OUT_PATH.exists() and new_ts:
        try:
            existing = json.loads(OUT_PATH.read_text(encoding="utf-8"))
            existing_ts = _parse_iso_utc(existing.get("captured_at"))
            if existing_ts and existing_ts > new_ts:
                print(f"Live file already newer ({existing_ts.strftime('%H:%M:%SZ')} > {new_ts.strftime('%H:%M:%SZ')}), skipping.")
                return 0
        except Exception:
            pass

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(result, indent=2), encoding="utf-8")
    pri = result.get("primary", {})
    print(f"Saved: 5h {100 - (pri.get('used_percent') or 0):.0f}% remaining → {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
