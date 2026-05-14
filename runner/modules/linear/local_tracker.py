"""Local task tracker — fallback when Linear is not available.

Stores tasks in `state/tasks.json` with the same format as Linear issues,
so the frontend job board works without modification in both modes.

Task format (matches _normalize_linear_issue output):
    {
        "id": "local-<uuid>",
        "identifier": "LOC-<n>",
        "title": "...",
        "description": "...",
        "state": "Todo | In Progress | In Review | Done | Canceled",
        "url": "",
        "preferred_agent": "claude | codex | deepseek | null",
        "created_at": "ISO datetime",
        "updated_at": "ISO datetime",
    }
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# Board status → tracker state mapping (matches _BOARD_TO_LINEAR in app.py)
BOARD_TO_STATE: dict[str, str] = {
    "todo": "Todo",
    "running": "In Progress",
    "review": "In Review",
    "success": "Done",
    "cancelled": "Canceled",
    "duplicate": "Duplicate",
    "rework": "In Progress",
    "merging": "In Progress",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _state_key(state: str | None) -> str:
    return re.sub(r"\s+", " ", (state or "").strip()).lower()


def _load_state(state_dir: Path) -> dict:
    """Load tasks from state/tasks.json."""
    path = state_dir / "tasks.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("Failed to load tasks.json: %s", e)
        return {}


def _save_state(state_dir: Path, tasks: dict) -> None:
    """Atomically write tasks to state/tasks.json."""
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / "tasks.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(tasks, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def _next_identifier(tasks: dict) -> str:
    """Generate next LOC-<n> identifier."""
    max_n = 0
    for t in tasks.values():
        ident = t.get("identifier", "")
        m = re.search(r"LOC-(\d+)", ident)
        if m:
            n = int(m.group(1))
            if n > max_n:
                max_n = n
    return f"LOC-{max_n + 1}"


class LocalTracker:
    """Local task tracker — file-based alternative to Linear.

    Usage:
        tracker = LocalTracker(Path("state"))
        issues = tracker.fetch_issues()
        tracker.create_issue("My title", "desc")
        tracker.update_issue_state(issue_id, "Done")
    """

    def __init__(self, state_dir: Path) -> None:
        self._state_dir = state_dir

    # ── Matching LinearClient interface ──────────────────────────────────

    def fetch_issues(self, states: list[str] | None = None) -> list[dict]:
        """Return all tasks, optionally filtered by state names.

        Returns format compatible with _normalize_linear_issue output.
        """
        tasks = _load_state(self._state_dir)
        if states:
            state_set = set(_state_key(s) for s in states)
            return [
                t for t in tasks.values()
                if _state_key(t.get("state")) in state_set
            ]
        return list(tasks.values())

    def fetch_issue(self, issue_id: str) -> dict | None:
        """Return a single task by id."""
        tasks = _load_state(self._state_dir)
        return tasks.get(issue_id)

    def create_issue(
        self,
        title: str,
        description: str = "",
        state_name: str = "Todo",
        preferred_agent: str | None = None,
    ) -> dict:
        """Create a new task, return normalized issue dict."""
        tasks = _load_state(self._state_dir)
        issue_id = f"local-{uuid.uuid4().hex[:12]}"
        now = _now_iso()
        issue = {
            "id": issue_id,
            "identifier": _next_identifier(tasks),
            "title": title,
            "description": description,
            "state": state_name,
            "url": "",
            "preferred_agent": preferred_agent,
            "created_at": now,
            "updated_at": now,
        }
        tasks[issue_id] = issue
        _save_state(self._state_dir, tasks)
        logger.info("Local task created: %s — %s", issue["identifier"], title)
        return dict(issue)

    def update_issue_state(self, issue_id: str, state_name: str) -> bool:
        """Update task state, return True on success."""
        tasks = _load_state(self._state_dir)
        issue = tasks.get(issue_id)
        if not issue:
            logger.warning("Local task not found: %s", issue_id)
            return False
        issue["state"] = state_name
        issue["updated_at"] = _now_iso()
        _save_state(self._state_dir, tasks)
        logger.info("Local task %s → %s", issue_id, state_name)
        return True

    def update_issue(
        self,
        issue_id: str,
        title: str | None = None,
        description: str | None = None,
        state_name: str | None = None,
        preferred_agent: str | None = None,
    ) -> dict | None:
        """Update task fields, return updated issue or None."""
        tasks = _load_state(self._state_dir)
        issue = tasks.get(issue_id)
        if not issue:
            return None
        if title is not None:
            issue["title"] = title
        if description is not None:
            issue["description"] = description
        if state_name is not None:
            issue["state"] = state_name
        if preferred_agent is not None:
            issue["preferred_agent"] = preferred_agent
        issue["updated_at"] = _now_iso()
        _save_state(self._state_dir, tasks)
        return dict(issue)

    def delete_issue(self, issue_id: str) -> bool:
        """Delete a task, return True on success."""
        tasks = _load_state(self._state_dir)
        if issue_id not in tasks:
            return False
        del tasks[issue_id]
        _save_state(self._state_dir, tasks)
        return True

    # ── AgenticOS-specific helpers ───────────────────────────────────────

    def push_state(self, issue_id: str, board_status: str) -> None:
        """Translate board status to tracker state and update.

        Matches _push_linear_state_async behavior in app.py.
        """
        tracker_state = BOARD_TO_STATE.get(board_status)
        if not tracker_state:
            return
        self.update_issue_state(issue_id, tracker_state)

    def post_comment(self, issue_id: str, body: str) -> bool:
        """Post a comment to the task (stored as log entry)."""
        tasks = _load_state(self._state_dir)
        issue = tasks.get(issue_id)
        if not issue:
            return False
        if "comment_log" not in issue:
            issue["comment_log"] = []
        issue["comment_log"].append({
            "body": body,
            "created_at": _now_iso(),
        })
        issue["updated_at"] = _now_iso()
        _save_state(self._state_dir, tasks)
        return True

    def get_in_progress_ids(self) -> set[str]:
        """Return set of issue IDs that are in 'In Progress' state."""
        tasks = _load_state(self._state_dir)
        return {
            tid for tid, t in tasks.items()
            if _state_key(t.get("state")) == "in progress"
        }

    # ── Raw access for sync_cache_to_local ──────────────────────────────

    def _load_raw(self) -> dict:
        """Load the raw tasks dict directly (bypassing the class abstraction).

        Used by LinearModule._sync_cache_to_local to write issues keyed by
        their Linear UUID instead of a generated local-* id.
        """
        return _load_state(self._state_dir)

    def _save_raw(self, tasks: dict) -> None:
        """Atomically write the raw tasks dict."""
        _save_state(self._state_dir, tasks)

    @property
    def is_available(self) -> bool:
        """Always available — no API key needed."""
        return True
