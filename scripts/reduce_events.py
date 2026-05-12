#!/usr/bin/env python3
"""Reduce events.jsonl → reduced_state.json.

Reads state/events.jsonl (append‑only event log) and produces a
compact state summary that can be consumed by the UI and doc generators.

Usage:
    python scripts/reduce_events.py
"""

import json
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EVENTS_PATH = REPO_ROOT / "state" / "events.jsonl"
OUTPUT_PATH = REPO_ROOT / "state" / "reduced_state.json"


def reduce_events() -> dict:
    """Read events.jsonl and return a reduced state dict."""
    if not EVENTS_PATH.exists():
        print(f"Events file not found: {EVENTS_PATH}")
        return {}

    reduced = {
        "total_events": 0,
        "last_event_timestamp": None,
        "tasks": {},          # task_id → latest state
        "skills": {},         # skill_name → run count
        "backends": {},       # backend → run count
        "errors": [],         # last 10 error events
    }

    with open(EVENTS_PATH, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            reduced["total_events"] += 1
            ts = event.get("timestamp")
            if ts:
                reduced["last_event_timestamp"] = ts

            # Track per‑task state
            task_id = event.get("task_id")
            if task_id:
                reduced["tasks"][task_id] = event

            # Track skill usage
            skill = event.get("skill")
            if skill:
                reduced["skills"][skill] = reduced["skills"].get(skill, 0) + 1

            # Track backend usage
            backend = event.get("backend")
            if backend:
                reduced["backends"][backend] = reduced["backends"].get(backend, 0) + 1

            # Collect recent errors
            if event.get("type") == "error":
                reduced["errors"].append(event)
                if len(reduced["errors"]) > 10:
                    reduced["errors"].pop(0)

    return reduced


def main():
    reduced = reduce_events()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(reduced, f, indent=2)
    print(f"Reduced state written to {OUTPUT_PATH}")
    print(f"  total events: {reduced.get('total_events', 0)}")
    print(f"  tasks tracked: {len(reduced.get('tasks', {}))}")
    print(f"  skills seen: {len(reduced.get('skills', {}))}")
    print(f"  backends seen: {len(reduced.get('backends', {}))}")


if __name__ == "__main__":
    main()
