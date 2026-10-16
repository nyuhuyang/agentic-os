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
        "team_id": "linear-team-uuid | ''",
        "team_key": "AGE | ML4T | ''",
        "team_name": "Agenticos | ''",
        "created_at": "ISO datetime",
        "updated_at": "ISO datetime",
    }
"""

from __future__ import annotations

import contextlib
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
    """Atomically write tasks to state/tasks.json (caller holds _tasks_lock)."""
    from state_io import write_json_atomic
    write_json_atomic(state_dir / "tasks.json", tasks, indent=2, ensure_ascii=False)


class _Tasks(dict):
    """tasks.json contents plus the identifier high-water mark (`loc_max`, SBR-004), both read
    and written under the same lock."""
    loc_max = 0


@contextlib.contextmanager
def _tasks_txn(state_dir: Path):
    """Whole load -> change -> save of tasks.json under one cross-process lock (plan 4b)."""
    from state_io import file_lock, read_json, write_json_atomic
    with file_lock(state_dir / "tasks.json"):
        tasks = _Tasks(_load_state(state_dir))
        meta_path = state_dir / "local_tracker_meta.json"
        meta = read_json(meta_path)
        start = meta.get("loc_max") if isinstance(meta.get("loc_max"), int) else _allocated_floor(state_dir, tasks)
        tasks.loc_max = start
        yield tasks
        _save_state(state_dir, dict(tasks))
        tasks.loc_max = max(tasks.loc_max, _max_loc(t.get("identifier") for t in tasks.values()))
        if tasks.loc_max != meta.get("loc_max"):
            write_json_atomic(meta_path, {**meta, "loc_max": tasks.loc_max})


_LOC = re.compile(r"LOC-(\d+)")


def _max_loc(texts) -> int:
    return max((int(m) for t in texts if isinstance(t, str) for m in _LOC.findall(t)), default=0)


def _allocated_floor(state_dir: Path, tasks: dict) -> int:
    """First use without the meta file: the highest LOC-n ever handed out, from the tasks, the
    run logs' identifiers and the ticket directories under the worktree root (SBR-004)."""
    found = [_max_loc(t.get("identifier") for t in tasks.values())]
    for name in ("run_log.jsonl", "runs.jsonl"):
        with contextlib.suppress(OSError):
            found.append(_max_loc(re.findall(r'"issue_identifier":\s*"(LOC-\d+)"',
                                             (state_dir / name).read_text(encoding="utf-8", errors="replace"))))
    with contextlib.suppress(Exception):
        import projects
        root = projects.WORKTREE_ROOT
        names = [p.name for d in root.iterdir() if d.is_dir() for p in d.iterdir()] if root.is_dir() else []
        found.append(_max_loc(names))
    return max(found)


def _next_identifier(tasks: dict) -> str:
    """Next LOC-<n>: above every task and every identifier ever handed out, so a deleted task's
    number (and its ticket binding, branch and worktree) is never reused (SBR-004)."""
    n = max(getattr(tasks, "loc_max", 0), _max_loc(t.get("identifier", "") for t in tasks.values())) + 1
    if isinstance(tasks, _Tasks):
        tasks.loc_max = n
    return f"LOC-{n}"


def _with_labels(issue: dict) -> dict:
    """A copy with `labels` always a list: task files written before labels existed read as []."""
    out = dict(issue)
    if not isinstance(out.get("labels"), list):
        out["labels"] = []
    return out


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

    def fetch_issues(self, states: list[str] | None = None, team_id: str | None = None) -> list[dict]:
        """Return all tasks, optionally filtered by state names and/or team_id.

        Returns format compatible with _normalize_linear_issue output.
        """
        tasks = _load_state(self._state_dir)
        results: list[dict] = list(tasks.values())
        if states:
            state_set = set(_state_key(s) for s in states)
            results = [t for t in results if _state_key(t.get("state")) in state_set]
        if team_id:
            results = [t for t in results if t.get("team_id") == team_id]
        return [_with_labels(t) for t in results]

    def fetch_issue(self, issue_id: str) -> dict | None:
        """Return a single task by id."""
        tasks = _load_state(self._state_dir)
        issue = tasks.get(issue_id)
        return _with_labels(issue) if issue else None

    def create_issue(
        self,
        title: str,
        description: str = "",
        state_name: str = "Todo",
        preferred_agent: str | None = None,
        team_id: str = "",
        team_key: str = "",
        team_name: str = "",
        labels: list[str] | None = None,
    ) -> dict:
        """Create a new task, return normalized issue dict."""
        with _tasks_txn(self._state_dir) as tasks:
            issue = self._new_issue(tasks, title, description, state_name, preferred_agent,
                                    team_id, team_key, team_name)
            issue["labels"] = list(labels or [])
        logger.info("Local task created: %s — %s", issue["identifier"], title)
        return dict(issue)

    @staticmethod
    def _new_issue(tasks, title, description, state_name, preferred_agent, team_id, team_key, team_name) -> dict:
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
            "team_id": team_id,
            "team_key": team_key,
            "team_name": team_name,
            "created_at": now,
            "updated_at": now,
        }
        tasks[issue_id] = issue
        return issue

    def update_issue_state(self, issue_id: str, state_name: str) -> bool:
        """Update task state, return True on success."""
        with _tasks_txn(self._state_dir) as tasks:
            issue = tasks.get(issue_id)
            if not issue:
                logger.warning("Local task not found: %s", issue_id)
                return False
            issue["state"] = state_name
            issue["updated_at"] = _now_iso()
        logger.info("Local task %s → %s", issue_id, state_name)
        return True

    def update_issue(
        self,
        issue_id: str,
        title: str | None = None,
        description: str | None = None,
        state_name: str | None = None,
        preferred_agent: str | None = None,
        labels: list[str] | None = None,
    ) -> dict | None:
        """Update task fields, return updated issue or None."""
        with _tasks_txn(self._state_dir) as tasks:
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
            if labels is not None:
                issue["labels"] = list(labels)
            issue["updated_at"] = _now_iso()
            return _with_labels(issue)

    def delete_issue(self, issue_id: str) -> bool:
        """Delete a task, return True on success."""
        with _tasks_txn(self._state_dir) as tasks:
            if issue_id not in tasks:
                return False
            tasks.loc_max = max(tasks.loc_max, _max_loc([tasks[issue_id].get("identifier")]))  # never reused (SBR-004)
            del tasks[issue_id]
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
        with _tasks_txn(self._state_dir) as tasks:
            issue = tasks.get(issue_id)
            if not issue:
                return False
            issue.setdefault("comment_log", []).append({"body": body, "created_at": _now_iso()})
            issue["updated_at"] = _now_iso()
            return True

    def get_in_progress_ids(self) -> set[str]:
        """Return set of issue IDs that are in 'In Progress' state."""
        tasks = _load_state(self._state_dir)
        return {
            tid for tid, t in tasks.items()
            if _state_key(t.get("state")) == "in progress"
        }

    # ── Raw access for sync_cache_to_local ──────────────────────────────

    def raw_transaction(self):
        """`with tracker.raw_transaction() as tasks:` — locked raw access for the Linear
        cache sync, which writes issues keyed by their Linear UUID."""
        return _tasks_txn(self._state_dir)

    @property
    def is_available(self) -> bool:
        """Always available — no API key needed."""
        return True
