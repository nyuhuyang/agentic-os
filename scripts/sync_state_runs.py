#!/usr/bin/env python3
"""Sync RUN_LOG entries missing from STATE_RUN_LOG by comparing latest entry per run_id."""
import json
from pathlib import Path

state_path = Path("state/runs.jsonl")
run_log_path = Path("outputs/run_log.jsonl")

def load_latest(path: Path) -> dict[str, dict]:
    """Load latest (reversed, deduped) entry per run_id from a JSONL file."""
    if not path.exists():
        return {}
    lines = [l for l in path.read_text().strip().splitlines() if l]
    latest: dict[str, dict] = {}
    for line in reversed(lines):
        try:
            r = json.loads(line)
            rid = r.get("run_id")
            if rid and rid not in latest:
                latest[rid] = r
        except Exception:
            continue
    return latest

state_latest = load_latest(state_path)
run_log_latest = load_latest(run_log_path)

print(f"STATE_RUN_LOG: {len(state_latest)} unique run_ids")
print(f"RUN_LOG: {len(run_log_latest)} unique run_ids")

# Find entries where RUN_LOG has a different latest entry than STATE_RUN_LOG
# (i.e., status was updated via PATCH which old code only wrote to RUN_LOG)
to_sync = []
for rid, r in run_log_latest.items():
    sr = state_latest.get(rid)
    if sr and sr != r:
        to_sync.append(json.dumps(r))
    elif rid not in state_latest:
        to_sync.append(json.dumps(r))

print(f"Entries with updated/newer data in RUN_LOG: {len(to_sync)}")

# Also count specifically archived entries
archived_diff = sum(
    1 for rid in run_log_latest
    if run_log_latest[rid].get("status") == "archived"
    and (rid not in state_latest or state_latest[rid].get("status") != "archived")
)
print(f"Archived entries missing from STATE_RUN_LOG: {archived_diff}")

if to_sync:
    # Append missing/updated entries to STATE_RUN_LOG
    with open(state_path, "a") as f:
        for rec in to_sync:
            f.write(rec + "\n")
    print(f"Synced {len(to_sync)} entries to STATE_RUN_LOG")
    
    # Verify
    state_latest2 = load_latest(state_path)
    archived_new = sum(1 for r in state_latest2.values() if r.get("status") == "archived")
    print(f"Archived entries in STATE_RUN_LOG after sync: {archived_new}")
else:
    print("Already in sync - no action needed")
