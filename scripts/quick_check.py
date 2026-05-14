import json
lines = [l for l in open("outputs/run_log.jsonl").read().splitlines() if l]
seen = {}
for line in reversed(lines):
    r = json.loads(line); rid = r.get("run_id")
    if rid and rid not in seen: seen[rid] = r.get("status","?")
total = len(seen)
archived = sum(1 for s in seen.values() if s == "archived")
print(f"Unique: {total}, Archived(latest): {archived}, Non-archived: {total-archived}")
