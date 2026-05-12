"""Linear 集成模块 + 本地任务跟踪降级方案。

当 LINEAR_API_KEY 可用且 WORKFLOW.md 中 tracker.kind == "linear" 时，
该模块连接到 Linear GraphQL API。当不可用时，自动降级到本地
`state/tasks.json` 文件跟踪。

模块名: "linear"
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from runner.core.module_registry import AgenticModule

logger = logging.getLogger(__name__)

_HERE = Path(__file__).resolve().parent
_PROTO = _HERE.parent.parent.parent          # agentic-os root
STATE_DIR = _PROTO / "state"
# .env is loaded by app.py at startup; do NOT re-load here to avoid
# re-introducing env vars that were explicitly unset for testing.


def _load_workflow_config() -> dict:
    """Load WORKFLOW.md YAML front matter."""
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


def _has_env_key(name: str) -> bool:
    """Check if env var looks like a real API key."""
    val = os.environ.get(name, "").strip()
    if not val:
        return False
    if val.startswith("$"):
        return bool(val[1:]) and bool(os.environ.get(val[1:], "").strip())
    return True


def _tracker_type() -> str | None:
    """Return tracker kind from workflow config, or None."""
    cfg = _load_workflow_config()
    return (cfg.get("tracker") or {}).get("kind")


class LinearModule(AgenticModule):
    """Tracker module — Linear or local fallback.

    Resolution chain:
        1. If WORKFLOW.md tracker.kind == "linear" AND LINEAR_API_KEY → use Linear
        2. Otherwise → use LocalTracker (state/tasks.json)
    """

    name = "linear"
    label = "Task Tracker"
    required_env: list[str] = []

    def __init__(self) -> None:
        super().__init__()
        self._linear_loaded = False
        self._local_tracker = None

    def check_capabilities(self) -> dict:
        """Detect whether Linear or local tracker should be used."""
        kind = _tracker_type()

        if kind == "linear" and _has_env_key("LINEAR_API_KEY"):
            return {
                "available": True,
                "reason": "",
                "type": "linear",
                "local_fallback": False,
            }

        # Linear not available — use local tracker
        return {
            "available": True,
            "reason": "LINEAR_API_KEY not set or tracker.kind != linear",
            "type": "local",
            "local_fallback": True,
        }

    def get_local_tracker(self):
        """Lazy-init and return LocalTracker instance."""
        if self._local_tracker is None:
            from runner.modules.linear.local_tracker import LocalTracker
            self._local_tracker = LocalTracker(STATE_DIR)
        return self._local_tracker

    def push_state(self, issue_id: str, board_status: str) -> None:
        """Push board status to tracker (Linear or local).

        Thread-safe: runs in a daemon thread.
        """
        import threading
        threading.Thread(target=self._push_sync, args=(issue_id, board_status), daemon=True).start()

    def _push_sync(self, issue_id: str, board_status: str) -> None:
        """Synchronous state push, called from background thread."""
        cfg = _load_workflow_config()
        tracker_cfg = cfg.get("tracker", {})

        if tracker_cfg.get("kind") == "linear" and _has_env_key("LINEAR_API_KEY"):
            self._push_linear(issue_id, board_status, tracker_cfg)
        else:
            self.get_local_tracker().push_state(issue_id, board_status)

    def _push_linear(self, issue_id: str, board_status: str, tracker_cfg: dict) -> None:
        """Push state to Linear GraphQL."""
        _BOARD_TO_LINEAR = {
            "todo": "Todo", "running": "In Progress", "review": "In Review",
            "success": "Done", "cancelled": "Canceled", "duplicate": "Duplicate",
            "rework": "In Progress", "merging": "In Progress",
        }
        linear_state = _BOARD_TO_LINEAR.get(board_status)
        if not linear_state:
            return  # failed/error/stalled: board-only

        try:
            from linear_client import LinearClient
            api_key = tracker_cfg.get("api_key", "")
            if api_key.startswith("$"):
                api_key = os.environ.get(api_key[1:], "")
            if not api_key or not tracker_cfg.get("project_slug"):
                return
            client = LinearClient(api_key, tracker_cfg.get("project_slug", ""))
            client.update_issue_state(issue_id, linear_state)
            logger.info("Linear state pushed: %s → %s", issue_id, linear_state)
        except Exception as e:
            logger.error("Linear state push failed: %s", e)

    def post_comment(self, issue_id: str, body: str) -> bool:
        """Post comment to tracker."""
        cfg = _load_workflow_config()
        tracker_cfg = cfg.get("tracker", {})
        if tracker_cfg.get("kind") == "linear" and _has_env_key("LINEAR_API_KEY"):
            return self._post_linear_comment(issue_id, body, tracker_cfg)
        return self.get_local_tracker().post_comment(issue_id, body)

    def _post_linear_comment(self, issue_id: str, body: str, tracker_cfg: dict) -> bool:
        """Post comment to Linear GraphQL."""
        import json
        import urllib.request

        api_key = tracker_cfg.get("api_key", "")
        if api_key.startswith("$"):
            api_key = os.environ.get(api_key[1:], "")
        if not api_key:
            return False

        _MUTATION = """
        mutation AgenticOSCommentCreate($issueId: String!, $body: String!) {
            commentCreate(input: {issueId: $issueId, body: $body}) {
                success
                comment { id }
            }
        }
        """
        try:
            payload = json.dumps({
                "query": _MUTATION,
                "variables": {"issueId": issue_id, "body": body},
            }).encode("utf-8")
            req = urllib.request.Request(
                "https://api.linear.app/graphql",
                data=payload,
                headers={"Content-Type": "application/json", "Authorization": api_key},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read())
            return not result.get("errors")
        except Exception:
            return False


# ── Module registration ────────────────────────────────────────────────────

module = LinearModule()
"""Exported instance for module discovery."""
