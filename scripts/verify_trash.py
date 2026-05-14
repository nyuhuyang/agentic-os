#!/usr/bin/env python3
"""Verify archived runs visibility in load_runs(200, include_archived=True)."""
import json
from pathlib import Path

run_log_path = Path("outputs/run_log.jsonl")
lines = [l for l in run_log_path.read_text().strip().splitlines() if l]

# Load latest per run_id (same as _load_runs_from)
latest = {}
for line in reversed(lines):
    r = json.loads(line)
    rid = r.get("run_id")
    if rid and rid not in latest:
        latest[rid] = r

# Top 200 most recent (simulating load_runs(200, include_archived=True))
items = list(latest.items())
recent = items[:200]

archived_ids = [(rid, r.get("started_at", "?")) for rid, r in items if r.get("status") == "archived"]
print(f"Total unique run_ids: {len(items)}")
print(f"Archived as LATEST status: {len(archived_ids)}")
print(f"Archived in top 200: {sum(1 for rid, _ in recent if rid in {a[0] for a in archived_ids})}")

print("\nArchived runs (latest entry archived):")
for rid, dt in archived_ids:
    pos = next(i for i, (r, _) in enumerate(items) if r == rid)
    print(f"  {rid[:16]}...  pos={pos}  started={dt}")
