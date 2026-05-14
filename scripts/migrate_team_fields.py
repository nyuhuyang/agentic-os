#!/usr/bin/env python3
"""Migrate state/tasks.json to add team_id/team_key/team_name to old entries.

Usage:
    ../.venv/bin/python3 scripts/migrate_team_fields.py
    ../.venv/bin/python3 scripts/migrate_team_fields.py --dry-run

Scans all entries in state/tasks.json. For entries missing team_id:
  1. Tries Linear API (if LINEAR_API_KEY set in WORKFLOW.md or env) to
     look up team by identifier prefix
  2. Falls back to a prefix mapping table
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROTO = _HERE.parent
STATE_DIR = _PROTO / "state"


def _load_tasks() -> dict:
    path = STATE_DIR / "tasks.json"
    if not path.exists():
        print("No state/tasks.json found.")
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _save_tasks(tasks: dict) -> None:
    path = STATE_DIR / "tasks.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(tasks, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def _load_workflow_config() -> dict:
    wf = _PROTO / "WORKFLOW.md"
    if not wf.exists():
        return {}
    try:
        text = wf.read_text(encoding="utf-8")
        if text.startswith("---"):
            end = text.find("---", 3)
            if end != -1:
                import yaml
                return yaml.safe_load(text[3:end]) or {}
    except Exception:
        pass
    return {}


def _get_linear_api_key() -> str | None:
    cfg = _load_workflow_config()
    tc = cfg.get("tracker", {})
    api_key = tc.get("api_key", "")
    if api_key.startswith("$"):
        api_key = os.environ.get(api_key[1:], "")
    return api_key if api_key else None


def _build_prefix_map_via_api(api_key: str) -> dict[str, dict[str, str]]:
    """Query Linear API to build identifier-prefix -> team mapping."""
    import requests
    endpoint = "https://api.linear.app/graphql"
    query = """
    query MigrateTeamFields {
      teams(first: 50) {
        nodes { id key name }
      }
    }
    """
    try:
        resp = requests.post(
            endpoint,
            json={"query": query},
            headers={"Authorization": api_key, "Content-Type": "application/json"},
            timeout=10,
        )
        data = resp.json()
        teams = (data.get("data") or {}).get("teams", {}).get("nodes", [])
        mapping: dict[str, dict[str, str]] = {}
        for t in teams:
            key = t.get("key", "")
            if key:
                mapping[key] = {
                    "team_id": t.get("id", ""),
                    "team_key": key,
                    "team_name": t.get("name", ""),
                }
        print(f"Built prefix map from Linear API: {list(mapping.keys())}")
        return mapping
    except Exception as e:
        print(f"Linear API lookup failed: {e}")
        return {}


def main() -> None:
    dry_run = "--dry-run" in sys.argv

    tasks = _load_tasks()
    if not tasks:
        return

    # Prefer Linear API for prefix mapping
    api_key = _get_linear_api_key()
    prefix_map = _build_prefix_map_via_api(api_key) if api_key else {}

    modified = 0
    for issue_id, issue in tasks.items():
        if issue.get("team_id"):
            continue  # already has team info

        identifier = issue.get("identifier", "")
        m = re.match(r"^([A-Z]+)-\d+", identifier)
        prefix = m.group(1) if m else ""

        team_info = prefix_map.get(prefix, {})
        issue["team_id"] = team_info.get("team_id", "")
        issue["team_key"] = team_info.get("team_key", prefix)
        issue["team_name"] = team_info.get("team_name", prefix)
        modified += 1
        print(f"  [{identifier}] -> team_key={issue['team_key']}, team_id={issue['team_id'][:12]}...")

    if modified == 0:
        print("All entries already have team fields. Nothing to migrate.")
        return

    print(f"\nTotal modified entries: {modified}")
    if dry_run:
        print("DRY RUN - changes not saved.")
    else:
        _save_tasks(tasks)
        print("Migration saved to state/tasks.json")


if __name__ == "__main__":
    main()
