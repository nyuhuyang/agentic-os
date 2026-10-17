"""Linear 集成模块 + 本地任务跟踪降级方案。

当 LINEAR_API_KEY 可用且 WORKFLOW.md 中 tracker.kind == "linear" 时，
该模块连接到 Linear GraphQL API。当不可用时，自动降级到本地
`state/tasks.json` 文件跟踪。

模块名: "linear"
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import subprocess
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import jsonify, request

from runner.agent_ids import canonical_agent
from runner.core.module_registry import AgenticModule

logger = logging.getLogger(__name__)

_HERE = Path(__file__).resolve().parent
_PROTO = _HERE.parent.parent.parent
STATE_DIR = _PROTO / "state"
ID_ALIASES_PATH = _PROTO / "outputs" / "id_aliases.json"
_id_alias_lock = threading.Lock()


def load_id_aliases() -> dict[str, str]:
    """local-* id → Linear id map, kept so the dashboard can migrate per-issue browser state after a reload."""
    try:
        data = json.loads(ID_ALIASES_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def record_id_alias(local_id: str, real_id: str) -> None:
    with _id_alias_lock:  # only the Flask process writes this file
        aliases = load_id_aliases()
        aliases[local_id] = real_id
        ID_ALIASES_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=ID_ALIASES_PATH.parent, prefix=".id_aliases.")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(aliases, f)
        os.replace(tmp, ID_ALIASES_PATH)


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


def _has_env_key(name: str) -> bool:
    val = os.environ.get(name, "").strip()
    if not val:
        return False
    if val.startswith("$"):
        return bool(val[1:]) and bool(os.environ.get(val[1:], "").strip())
    return True


def _tracker_type() -> str | None:
    cfg = _load_workflow_config()
    return (cfg.get("tracker") or {}).get("kind")


def _linear_api_key_from_cfg(tracker: dict) -> str:
    api_key = tracker.get("api_key", "")
    if api_key.startswith("$"):
        api_key = os.environ.get(api_key[1:], "")
    return api_key


def _linear_state_key(state) -> str:
    if isinstance(state, dict):
        state = state.get("name")
    return re.sub(r"\s+", " ", (state or "").strip()).lower()


def _is_linear_in_progress(state: str | None) -> bool:
    return _linear_state_key(state) == "in progress"


def _linear_state_to_board(state: str | None) -> str:
    key = _linear_state_key(state)
    if key == "in progress":
        return "running"
    if key == "in review":
        return "review"
    if key == "done":
        return "success"
    if key in {"canceled", "cancelled"}:
        return "cancelled"
    if key == "duplicate":
        return "duplicate"
    if key in {"rework", "merging"}:
        return "running"
    return "todo"


def _linear_poll_states(tracker: dict) -> list[str]:
    """返回轮询用状态列表（仅 active 状态，排除 terminal 状态）。

    Terminal 状态（Done/Canceled/Duplicate）不参与拉取，避免将大量已关闭
    的历史 issue 拉入本地缓存和 dashboard。
    """
    active = list(tracker.get("active_states", ["Todo", "In Progress", "In Review"]))
    if "Backlog" not in active:
        active.insert(0, "Backlog")
    if "In Review" not in active:
        active.append("In Review")
    seen: set[str] = set()
    ordered: list[str] = []
    for s in active:
        if s not in seen:
            seen.add(s)
            ordered.append(s)
    return ordered


_BOARD_TO_LINEAR: dict[str, str] = {
    "todo": "Todo", "running": "In Progress", "review": "In Review",
    "success": "Done", "cancelled": "Canceled", "duplicate": "Duplicate",
    "rework": "In Progress", "merging": "In Progress",
}

_LINEAR_COMMENT_MUTATION = """
mutation AgenticOSCommentCreate($issueId: String!, $body: String!) {
    commentCreate(input: {issueId: $issueId, body: $body}) {
        success
        comment { id }
    }
}
"""

_ISSUE_AGENT_MARKER_RE = re.compile(
    r"<!--\s*agent_backend:\s*(claude|codex|dsh|aider|deepseek|deepseek-tui)\s*-->\s*", re.IGNORECASE
)


def _extract_issue_agent(description: str | None) -> str | None:
    if not description:
        return None
    m = _ISSUE_AGENT_MARKER_RE.search(description)
    if m:
        return canonical_agent(m.group(1))  # legacy ids resolve to dsh
    return None


def _strip_issue_metadata(description: str | None) -> str:
    if not description:
        return ""
    return _ISSUE_AGENT_MARKER_RE.sub("", description).strip()


def _compose_issue_description(description: str, preferred_agent: str | None) -> str:
    base = (description or "").strip()
    preferred_agent = canonical_agent(preferred_agent)
    if preferred_agent:
        marker = f"<!-- agent_backend: {preferred_agent} -->"
        return f"{base}\n\n{marker}" if base else marker
    return base


def _label_names(labels) -> list[str]:
    """Labels as a list of names, from names, {name} dicts or a GraphQL {nodes: [...]} block."""
    if isinstance(labels, dict):
        labels = labels.get("nodes") or []
    out = []
    for label in labels or []:
        name = label.get("name") if isinstance(label, dict) else label
        if isinstance(name, str) and name:
            out.append(name)
    return out


def _normalize_linear_issue(issue: dict) -> dict:
    normalized = dict(issue or {})
    normalized["labels"] = _label_names(normalized.get("labels"))
    raw = normalized.get("description", "") or ""
    normalized["preferred_agent"] = _extract_issue_agent(raw)
    normalized["description"] = _strip_issue_metadata(raw)
    return normalized


DEFAULT_PROJECT_KEY = "agentic-os"


def _project_labels(data: dict) -> list[str]:
    """`project:<key>` label for a new task (B). `project` omitted: the default project when it
    is registered, else none; "" = explicitly no project (runner root). An unknown or broken
    key raises ValueError, so nothing is created."""
    import projects
    import project_runs
    key = data.get("project")
    if key is not None and not str(key).strip():
        return []  # explicitly no project: the registry is not read at all (FB3-02)
    errors: dict = {}
    try:
        registry = projects.load_registry(errors=errors)
    except projects.ProjectError as exc:
        if key is None:
            return []  # broken registry: the default falls back to the runner root
        raise ValueError(f"project registry unreadable: {exc}") from None
    if key is None:
        return [f"{project_runs.LABEL_PREFIX}{DEFAULT_PROJECT_KEY}"] if DEFAULT_PROJECT_KEY in registry else []
    key = str(key).strip()
    if not key:
        return []
    if key in errors:
        raise ValueError(f"project {key!r} is broken: {errors[key]}")
    if key not in registry:
        raise ValueError(f"unknown project {key!r}")
    return [f"{project_runs.LABEL_PREFIX}{key}"]


def archived_ids() -> set[str]:
    """Issues emptied from the trash (STB §11). Persisted, so neither the poller's terminal
    carry-over nor a restart (which pre-fills the cache from tasks.json) brings them back."""
    from state_io import read_json
    data = read_json(STATE_DIR / "archived_issue_ids.json", default=list)
    return set(data) if isinstance(data, list) else set()


def _add_archived_ids(ids) -> None:
    from state_io import json_transaction
    with json_transaction(STATE_DIR / "archived_issue_ids.json", default=list) as store:
        store.extend(i for i in ids if i not in store)


def _registered_project(key: str | None):
    """The registered Project for a key, or None (unknown key or unreadable registry)."""
    import projects
    if not key:
        return None
    try:
        return projects.get_project(projects.registered_key(key) or key, projects.load_registry(errors={}))
    except projects.ProjectError:
        return None


def linear_project_id(client, team_id: str, project_key: str | None, project_slug: str = "") -> str | None:
    """The Linear Project an issue of `project_key` belongs in (STB §10): a registered
    non-confidential project's same-named Project in the team (found, else created; the id is
    cached in the runner state); unbound, unknown or confidential ones go into the default
    Project from `tracker.project_slug` (None when there is none). Raises LinearError."""
    from state_io import json_transaction, read_json
    project = _registered_project(project_key)
    if project is not None and not project.confidential:
        cache_key = f"{team_id}:{project.key}"
        name = project.key
    elif project_slug:
        cache_key, name = f"slug:{project_slug}", None
    else:
        return None
    path = STATE_DIR / "linear_projects.json"
    cached = read_json(path).get(cache_key)
    if cached:
        return cached
    pid = (client.find_project(name, team_id) or client.create_project(name, team_id)) if name \
        else client.find_project_by_slug(project_slug)
    with json_transaction(path) as store:
        store[cache_key] = pid
    return pid


def _note_linear_title(issue: dict | None, pending: set | None = None) -> None:
    """A title as Linear itself returned it: the only source a native session rename may use in
    Linear mode (DP-31), versioned by updatedAt (R4). With `pending`, a first or changed title's
    session sync is collected there, to start once the issue is published in the cache (R7-01)."""
    if isinstance(issue, dict) and issue.get("id"):
        with contextlib.suppress(Exception):
            from app import _confirm_linear_title
            _confirm_linear_title(issue["id"], issue.get("title"), issue.get("updated_at") or issue.get("updatedAt") or "",
                                  pending=pending)


def _start_title_syncs(pending: set) -> None:
    """The session syncs a poll collected, after its cache is published (R7-01)."""
    for issue_id in pending:
        _title_changed(issue_id)


def _title_changed(issue_id: str, title: str | None = None) -> None:
    """A confirmed title change: rename the card's sessions, in the background (§2 triggers)."""
    with contextlib.suppress(Exception):
        from app import _sync_titles_soon
        _sync_titles_soon(issue_id, title)


def unsynced_local_id(issue_id: str | None) -> bool:
    """A task still on its local-first id while the Linear tracker is active: its Linear copy
    is not confirmed, so it is never dispatched or retried (B, R11)."""
    from runner.core.module_registry import registry
    mod = registry.get("linear")
    return bool(issue_id and str(issue_id).startswith("local-") and mod is not None
                and getattr(mod, "_capability", {}).get("type") == "linear")


def reserve_card(issue: dict | None, issue_id: str) -> contextlib.ExitStack:
    """Take this card's lock now (ticket lock for a project card, card lock otherwise) and return
    it for the dispatch to keep until the run ends. Raises TicketLocked when it is held (UI3-01)."""
    import projects
    import project_runs
    from app import _durable_binding
    issue = issue or {}
    bound = _durable_binding(linear_issue_id=issue_id) or {}
    raw = bound.get("project_key") or project_runs.project_key_from_labels(issue.get("labels"))
    key = projects.registered_key(raw) if raw else None  # a label is untrusted text: lock only registered keys (FB3-01)
    if raw and not key:
        raise projects.ProjectError(f"unknown project {raw!r} in this card's label")
    hold = contextlib.ExitStack()
    try:
        if key:
            ident = bound.get("issue_identifier") or issue.get("identifier") or issue_id
            hold.enter_context(projects.ticket_lock(key, ident))
            hold.identity = ("ticket", key, ident)  # what was locked: the dispatch checks it before handing on (REV-01)
        else:
            hold.enter_context(projects.card_lock(issue_id))
            hold.identity = ("card", issue_id)
    except BaseException:
        hold.close()
        raise
    return hold


def _state_committed() -> None:
    """The tracker accepted this request's state change (read by _tracker_reset_route)."""
    from flask import g
    g.tracker_state_committed = True


def card_locked(issue: dict | None, issue_id: str) -> bool:
    """An interactive terminal (or a running attempt) holds this card's lock (C2)."""
    import projects
    import project_runs
    from app import _durable_binding
    issue = issue or {}
    bound = _durable_binding(linear_issue_id=issue_id) or {}
    raw = bound.get("project_key") or project_runs.project_key_from_labels(issue.get("labels"))
    key = projects.registered_key(raw) if raw else None
    if raw and not key:
        return False  # unknown project: the dispatch records that error itself (FB3-01)
    if key:
        return projects.card_busy(key, bound.get("issue_identifier") or issue.get("identifier") or issue_id, None)
    return projects.card_busy(None, None, issue_id)


def _resolve_linear_state_name(issue: dict | None, target_state_key: str) -> str | None:
    if not issue:
        return None
    target_state_key = _linear_state_key(target_state_key)
    team_states = issue.get("team_states") or []
    for s in team_states:
        name = s.get("name", "")
        if name and _linear_state_key(name) == target_state_key:
            return name
    current = issue.get("state", "")
    if current and _linear_state_key(current) == target_state_key:
        return current
    return None


def _format_attachments_for_text(attachments: list[dict] | None) -> str:
    if not attachments:
        return ""
    lines: list[str] = []
    for idx, attachment in enumerate(attachments, start=1):
        name = attachment.get("name", f"file_{idx}")
        url = attachment.get("url", "")
        parts = [f"{idx}. {name}"]
        if url:
            parts.append(f"url: {url}")
        lines.append(" | ".join(parts))
    if not lines:
        return ""
    return "[Attachments]\n" + "\n".join(lines)

def _append_attachments_to_text(text: str, attachments: list[dict] | None) -> str:
    attachment_text = _format_attachments_for_text(attachments)
    base = (text or "").strip()
    if not attachment_text:
        return base
    return f"{base}\n\n{attachment_text}" if base else attachment_text


def _tracker_reset_route(fn):
    """Tracker PATCH routes hold the issue's lock for the whole update, and a move back to
    Todo bumps its reset generation first (Decision 11, DSH-30)."""
    import functools

    @functools.wraps(fn)
    def wrapper(issue_id: str, *args, **kwargs):
        import reset_gen
        from flask import g, make_response
        state_name = (request.get_json(silent=True) or {}).get("state_name")
        with reset_gen.issue_lock(issue_id):
            if not (state_name and _linear_state_to_board(state_name) == "todo"):
                return fn(issue_id, *args, **kwargs)
            previous = reset_gen.current(issue_id)
            bumped = reset_gen.bump(issue_id)
            g.tracker_state_committed = False
            resp = make_response(fn(issue_id, *args, **kwargs))
            # Undo only a reset whose state change never committed; a refresh failing after a
            # committed change keeps the new generation (IR13-01, UI14-03).
            if resp.status_code >= 400 and not g.get("tracker_state_committed"):
                reset_gen.restore(issue_id, previous, bumped)
            return resp
    return wrapper


def _linear_comment_body(*, title: str, prompt: str = "", output: str = "",
                         error: str = "", feedback: str = "",
                         attachments: list[dict] | None = None) -> str:
    parts = [f"### {title}", ""]
    if prompt:
        parts.append(f"**Prompt:**\n{prompt}\n")
    if output:
        max_out = output[:3000]
        parts.append(f"**Output:**\n```\n{max_out}\n```\n")
    if error:
        parts.append(f"**Error:**\n```\n{error}\n```\n")
    if feedback:
        parts.append(f"**Feedback:**\n{feedback}\n")
    attachment_text = _format_attachments_for_text(attachments)
    if attachment_text:
        parts.append(f"**Attachments:**\n{attachment_text}\n")
    return "\n".join(parts).strip()


def _issue_agent_comment_body(agent: str | None, title: str = "AgenticOS Model") -> str:
    return _linear_comment_body(title=title, feedback=f"Agent backend: {agent or 'default'}")


def _post_linear_comment_raw(issue_id: str, body: str, api_key: str) -> bool:
    import urllib.request
    try:
        payload = json.dumps({
            "query": _LINEAR_COMMENT_MUTATION,
            "variables": {"issueId": issue_id, "body": body},
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://api.linear.app/graphql",
            data=payload,
            headers={"Content-Type": "application/json", "Authorization": api_key},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
        return not result.get("errors") and bool(
            ((result.get("data") or {}).get("commentCreate") or {}).get("success")
        )
    except Exception:
        return False


class LinearModule(AgenticModule):
    """Tracker module — Linear or local fallback."""

    name = "linear"
    label = "Task Tracker"
    required_env: list[str] = []

    def __init__(self) -> None:
        super().__init__()
        self._local_tracker = None
        self._socketio = None
        # Shared state for app.py bridge
        self.issues_cache: dict[str, dict] = {}
        self.dispatched: dict[str, str] = {}
        self.dispatches_warmed = False
        # Multi-team support
        self._issues_by_team: dict[str, dict[str, dict]] = {}  # team_id → {issue_id → issue}
        self._teams_cache: list[dict] = []
        self._teams_last_refreshed: float = 0
        self._local_overrides: dict[str, dict] = {}
        # Issues this process just created: a poll whose fetch predates them must not drop them
        # from the cache (SBI-016). id -> monotonic time of the insert.
        self._fresh_ids: dict[str, float] = {}

    def check_capabilities(self) -> dict:
        kind = _tracker_type()
        if kind == "linear" and _has_env_key("LINEAR_API_KEY"):
            return {"available": True, "reason": "", "type": "linear", "local_fallback": False}
        return {"available": True, "reason": "LINEAR_API_KEY not set or tracker.kind != linear",
                "type": "local", "local_fallback": True}

    # ── Background polling ────────────────────────────────────────────────

    def start_background(self, app, socketio) -> list[threading.Thread]:
        self._socketio = socketio
        if self._capability.get("type") != "linear":
            return []
        # Pre-populate cache from local tracker before first poll so terminal-state
        # issues (Canceled/Done/Duplicate) are immediately visible in the board & trash
        try:
            local = self.get_local_tracker()
            gone = archived_ids()
            for issue in local.fetch_issues():
                if issue["id"] not in gone:
                    self.issues_cache[issue["id"]] = issue
            if self.issues_cache:
                logger.info("Pre-populated issues_cache with %d issues from state/tasks.json", len(self.issues_cache))
        except Exception:
            pass
        return [threading.Thread(target=self._polling_loop, args=(socketio,), daemon=True)]

    def _get_or_refresh_teams(self, client) -> list[dict]:
        """Return cached teams list, refreshing from Linear API every 30 min."""
        now = time.time()
        if now - self._teams_last_refreshed > 1800:
            try:
                teams = client.fetch_teams()
                self._teams_cache = teams
                self._teams_last_refreshed = now
                logger.info("Refreshed teams list: %s", [t.get("key") for t in teams])
            except Exception as e:
                logger.debug("Failed to refresh teams: %s", e)
        return self._teams_cache

    def _polling_loop(self, socketio) -> None:
        while True:
            admitted = False
            try:
                cfg = _load_workflow_config()
                tracker = cfg.get("tracker", {})
                if tracker.get("kind") != "linear":
                    time.sleep(30)
                    continue
                api_key = tracker.get("api_key", "")
                if api_key.startswith("$"):
                    api_key = os.environ.get(api_key[1:], "")
                if not api_key:
                    time.sleep(30)
                    continue
                interval_ms = cfg.get("polling", {}).get("interval_ms", 5000)
                from app import _admit, _TL, MaintenanceRefused
                try:  # each iteration writes local state: counted, paused under maintenance
                    _admit()
                except MaintenanceRefused:
                    time.sleep(5)
                    continue
                admitted = True
                _TL.admitted = True
                from linear_client import LinearClient
                client = LinearClient(api_key, tracker.get("project_slug", ""))
                states = _linear_poll_states(tracker)

                # Resolve list of teams to poll
                teams = self._get_or_refresh_teams(client)
                configured_team_id = tracker.get("team_id", "") or None
                if configured_team_id:
                    team_ids_to_poll = [configured_team_id]
                else:
                    team_ids_to_poll = [t["id"] for t in teams]

                new_cache: dict[str, dict] = {}
                new_by_team: dict[str, dict[str, dict]] = {}
                all_in_progress_ids: set[str] = set()
                import reset_gen
                gens_before = reset_gen.snapshot()  # a reset during the fetch wins (I6-11)

                gone = archived_ids()  # emptied from the trash: never back into the cache (STB-050)
                title_syncs: set = set()  # started once this poll's cache is published (R7-01)
                for tid in team_ids_to_poll:
                    team_issues = client.fetch_issues(states, team_id=tid)
                    team_issue_dict: dict[str, dict] = {}
                    for issue in team_issues:
                        iid = issue["id"]
                        if iid in gone:
                            continue
                        _note_linear_title(issue, title_syncs)  # before any local override (DP-31)
                        normalized = _normalize_linear_issue(issue)
                        normalized = self._apply_local_override(iid, normalized)
                        local_state = self.issues_cache.get(iid, {}).get("state")
                        if (
                            _is_linear_in_progress(issue.get("state"))
                            and _linear_state_to_board(local_state) == "review"
                            and not self._issue_is_running(iid)
                        ):
                            normalized["state"] = "In Review"
                        team_issue_dict[iid] = normalized
                        new_cache[iid] = normalized
                        if _is_linear_in_progress(issue.get("state")):
                            all_in_progress_ids.add(iid)
                    new_by_team[tid] = team_issue_dict

                if not self.dispatches_warmed:
                    self._warm_dispatches()
                    self.dispatches_warmed = True

                for iid in list(self.dispatched):
                    if iid not in all_in_progress_ids and not self._issue_is_running(iid):
                        self.dispatched.pop(iid, None)

                # Late-guard: re-check right before commit so a cancel that raced
                # with the issue-iteration loop still prevents "In Progress" from
                # overwriting a cache entry already set to "In Review".
                for _iid2, _norm in list(new_cache.items()):
                    if (
                        _is_linear_in_progress(_norm.get("state"))
                        and _linear_state_to_board(self.issues_cache.get(_iid2, {}).get("state")) == "review"
                        and not self._issue_is_running(_iid2)
                    ):
                        _updated = dict(_norm)
                        _updated["state"] = "In Review"
                        new_cache[_iid2] = _updated

                with contextlib.ExitStack() as held:
                    # Publish under the lock of every issue polled or cached; an issue reset
                    # since the fetch keeps its current (post-reset) entry (I6-11, I7-04).
                    for iid in sorted(set(new_cache) | set(self.issues_cache)):
                        held.enter_context(reset_gen.issue_lock(iid))
                    gone = archived_ids()  # re-read: an Empty trash during the fetch wins (STB-050)
                    for iid in gone:
                        new_cache.pop(iid, None)
                        for team_dict in new_by_team.values():
                            team_dict.pop(iid, None)
                    # Keep terminal-state issues (Canceled/Done/Duplicate) for trash display
                    terminal_issues = {
                        k: v for k, v in self.issues_cache.items()
                        if v.get("state") in ("Canceled", "Done", "Duplicate") and k not in gone
                    }
                    gens_now = reset_gen.snapshot()
                    for iid in set(new_cache) | set(self.issues_cache):
                        if gens_now.get(iid, 0) != gens_before.get(iid, 0) and iid in self.issues_cache:
                            terminal_issues.pop(iid, None)
                            new_cache[iid] = self.issues_cache[iid]
                            for team_dict in new_by_team.values():
                                team_dict.pop(iid, None)
                            tid = new_cache[iid].get("team_id") or ""
                            if tid:  # also when the fetch did not include it (I8-07)
                                new_by_team.setdefault(tid, {})[iid] = new_cache[iid]
                    # just created here and not fetched yet: kept until Linear returns it or 120 s pass,
                    # however the poll's timing falls (SBI-016/018)
                    fresh = {iid: self.issues_cache[iid] for iid in list(self._fresh_ids)
                             if iid not in new_cache and iid in self.issues_cache and iid not in gone}
                    for iid in list(self._fresh_ids):
                        if iid in new_cache or time.monotonic() - self._fresh_ids[iid] > 120:
                            self._fresh_ids.pop(iid, None)
                    self.issues_cache.clear()
                    self.issues_cache.update(new_cache)
                    self.issues_cache.update(fresh)
                    self._issues_by_team.clear()
                    self._issues_by_team.update(new_by_team)
                    for iid, issue in fresh.items():
                        if issue.get("team_id"):
                            self._issues_by_team.setdefault(issue["team_id"], {})[iid] = issue

                    # Preserve last N terminal issues so the recycle bin stays populated
                    terminal_list = sorted(terminal_issues.items(), key=lambda x: x[1].get("updated_at", ""))
                    self.issues_cache.update(dict(terminal_list[-100:]))
                    # Also add terminal issues back into _issues_by_team so team-filtered
                    # requests (e.g. /api/linear/issues?team_id=xxx) still see them
                    for iid, issue in terminal_list[-100:]:
                        tid = issue.get("team_id") or ""
                        if tid:
                            self._issues_by_team.setdefault(tid, {})[iid] = issue
                    self._sync_cache_to_local()
                _start_title_syncs(title_syncs)  # the issues are visible now (R7-01)
                socketio.emit("linear_issues_updated", {"count": len(self.issues_cache)})
            except Exception as e:
                logger.error("Linear polling error: %s", e)
            if admitted:
                from app import _release, _TL
                admitted = _TL.admitted = False
                _release()
            time.sleep(max(1, interval_ms / 1000))

    def _warm_dispatches(self) -> None:
        from app import _latest_linear_runs
        for issue_id, run in _latest_linear_runs(include_archived=True).items():
            rid = run.get("run_id")
            if rid and issue_id not in self.dispatched:
                self.dispatched[issue_id] = rid

    def _issue_is_running(self, issue_id: str) -> bool:
        try:
            from app import _running_jobs
            return any(job.get("linear_issue_id") == issue_id and job.get("state") == "running" for job in _running_jobs.values())
        except Exception:
            return False

    def _remember_local_override(self, issue_id: str, data: dict, preferred_agent: str | None = None,
                                 ttl_s: float = 60.0) -> None:
        """Keep local-first updates visible while Linear catches up."""
        if not issue_id:
            return
        patch = dict((self._local_overrides.get(issue_id) or {}).get("patch") or {})
        if data.get("state_name"):
            patch["state"] = data["state_name"]
        if data.get("title") is not None:
            patch["title"] = data["title"]
        if data.get("description") is not None:
            patch["description"] = data["description"]
        if preferred_agent is not None:
            patch["preferred_agent"] = preferred_agent
        if not patch:
            return
        self._local_overrides[issue_id] = {"patch": patch, "expires_at": time.monotonic() + ttl_s}

    def _apply_local_override(self, issue_id: str, issue: dict | None) -> dict:
        if not issue:
            return issue or {}
        override = self._local_overrides.get(issue_id)
        if not override:
            return issue
        if time.monotonic() > override.get("expires_at", 0):
            self._local_overrides.pop(issue_id, None)
            return issue
        patched = dict(issue)
        patched.update(override.get("patch") or {})
        return patched

    def _clear_local_override_if_synced(self, issue_id: str, issue: dict | None) -> None:
        override = self._local_overrides.get(issue_id)
        if not override or not issue:
            return
        patch = override.get("patch") or {}
        for key, expected in patch.items():
            if expected is not None and issue.get(key) != expected:
                return
        self._local_overrides.pop(issue_id, None)

    def _restore_issue_state(self, issue_id: str, board_status: str, cfg: dict) -> None:
        state_name = _BOARD_TO_LINEAR.get(board_status)
        if not state_name:
            return
        try:
            local = self.get_local_tracker()
            local.update_issue_state(issue_id, state_name)
        except Exception:
            pass
        cached = dict(self.issues_cache.get(issue_id) or {})
        cached["state"] = state_name
        self.issues_cache[issue_id] = cached
        if self._capability.get("type") == "linear":
            import reset_gen
            from app import _start_counted
            _start_counted(self._linear_sync_patch, issue_id, {"state_name": state_name}, cfg, None,
                           reset_gen.current(issue_id))

    def _is_confidential_issue(self, issue_id: str) -> bool:
        import project_runs
        from app import _durable_binding, _ticket_confidential
        bound = _durable_binding(linear_issue_id=issue_id)
        if bound:  # the ticket's one policy, sidecar promotions included (I5-03, I9-02)
            return _ticket_confidential(bound["project_key"], bound.get("issue_identifier"), issue_id) is not False
        issue = self.issues_cache.get(issue_id) or {}
        key = project_runs.project_key_from_labels(issue.get("labels"))
        if not key:
            return False
        if not issue.get("identifier"):
            return True  # no ticket id to check its worktree with: fail closed
        # Unbound but labelled: same policy, so a CLI-made confidential worktree counts (I10-02).
        return _ticket_confidential(key, issue["identifier"], issue_id) is not False

    def _mark_issue_review(self, issue_id: str, gen: int | None = None) -> None:
        import reset_gen
        with reset_gen.issue_lock(issue_id):
            if not reset_gen.is_current(issue_id, gen):
                return  # the run finished after the ticket was reset: leave the ticket alone
            # Don't override terminal states (Canceled, Done, Duplicate)
            current_state = (self.issues_cache.get(issue_id) or {}).get("state", "")
            if _linear_state_key(current_state) in ("canceled", "cancelled", "done", "duplicate"):
                return
            cached = dict(self.issues_cache.get(issue_id) or {})
            cached["state"] = "In Review"
            self.issues_cache[issue_id] = cached
            self.dispatched.pop(issue_id, None)
            if self._socketio:
                self._socketio.emit("linear_issues_updated", {"count": len(self.issues_cache)})
            self.push_state(issue_id, "review", gen=gen)

    def _start_dispatch(self, issue: dict, cfg: dict, previous_board_status, card_hold=None) -> None:
        """Dispatch on a counted worker (the request that asked for it was admitted by the gate).
        `card_hold`: the card's lock, already reserved by the route; the dispatch keeps it."""
        from app import _start_counted
        import reset_gen
        launch_gen = reset_gen.current(issue["id"])  # when it was asked for: a reset before the worker runs wins (R4-01)
        try:
            _start_counted(self._dispatch_issue, issue, cfg, self._socketio, previous_board_status, card_hold, launch_gen)
        except BaseException:
            if card_hold is not None:
                card_hold.close()
            raise

    def _dispatch_issue(self, issue: dict, cfg: dict, socketio, previous_board_status: str | None = None,
                        card_hold=None, launch_gen: int | None = None) -> None:
        from app import _inflight_work, MaintenanceRefused
        try:
            with _inflight_work():  # counted until its record is written (BUILD-001)
                self._dispatch_issue_counted(issue, cfg, socketio, previous_board_status, card_hold, launch_gen)
        except MaintenanceRefused as exc:
            logger.warning("dispatch of %s refused: %s", issue.get("id"), exc)
            if card_hold is not None:
                card_hold.close()

    def _dispatch_issue_counted(self, issue: dict, cfg: dict, socketio, previous_board_status: str | None = None,
                                card_hold=None, launch_gen: int | None = None) -> None:
        held = card_hold if card_hold is not None else contextlib.ExitStack()
        try:
            self._dispatch_issue_held(issue, cfg, socketio, held, reserved=card_hold is not None, launch_gen=launch_gen)
        finally:
            held.close()  # every path, including early refusals, ends the card's reservation

    def _dispatch_issue_held(self, issue: dict, cfg: dict, socketio, held: contextlib.ExitStack, reserved: bool,
                             launch_gen: int | None = None) -> None:
        import subprocess
        from app import _running_jobs, _running_procs, _python_path, RUNNER, ROOT, _load_registry, _ai_command, _agent_model, _parse_agent_output, _extract_skill_name, _write_run_log, AI_RUN_TIMEOUT_S, _extract_real_errors, _registry_exec_env, _stream_dsh_run, _dsh_ok
        from app import (_RunClaim, _kill_and_reap, _write_run_log_retrying, _comment_quietly, _run_grouped,
                         run_agent_process, _stream_for, _agent_output_format, _compute_token_cost)
        issue_id = issue["id"]
        if issue_id in self.dispatched:
            return
        if unsynced_local_id(issue_id):
            logger.warning("dispatch of %s refused: not synced to Linear yet", issue_id)
            return
        if not reserved and card_locked(issue, issue_id):
            logger.warning("dispatch of %s refused: an interactive terminal holds the card", issue_id)
            return
        import reset_gen
        if launch_gen is None:
            launch_gen = reset_gen.current(issue_id)
        elif launch_gen != reset_gen.current(issue_id):  # reset after it was asked for, before it ran (R4-01)
            logger.warning("dispatch of %s dropped: the card was reset before its worker started", issue_id)
            return

        agent_cfg = cfg.get("agent", {})
        backend = (canonical_agent(issue.get("preferred_agent"))
                   or canonical_agent(agent_cfg.get("backend")) or "claude")

        import project_runs
        import projects as projects_mod
        from app import _durable_binding
        # An issue bound by an earlier run keeps that binding whatever its labels say now (I5-03).
        bound = _durable_binding(linear_issue_id=issue_id) or {}
        project_key = bound.get("project_key") or project_runs.project_key_from_labels(issue.get("labels"))
        if project_key and not bound.get("project_key"):  # "project:Agentic-OS" runs in agentic-os (FB3-03)
            with contextlib.suppress(Exception):
                project_key = projects_mod.registered_key(project_key) or project_key
        if project_key:  # project ticket: own worktree, no skill routing, one launch helper (3a)
            from app import _run_project_ticket
            ident = bound.get("issue_identifier") or issue.get("identifier") or issue_id
            if reserved and getattr(held, "identity", None) != ("ticket", project_key, ident):
                held.close()  # the route locked something else (e.g. a card before the label was known, REV-01)
                reserved = False
            self._ensure_linear_project(issue, project_key)
            run_id = str(uuid.uuid4())
            # One task, one session (D3): continue the card's session when it lives in the ticket's
            # worktree; a missing bound worktree still fails closed in the helper (I6-10, DP-09).
            from app import _resumable_card_session, _resume_admission, AI_SESSION_TIMEOUT_S
            resume_sid, why_new = None, None
            if backend in ("claude", "codex"):
                wt = None
                with contextlib.suppress(Exception):
                    wt = projects_mod.worktree_path(projects_mod.get_project(project_key, projects_mod.load_registry(errors={})), ident)
                resume_sid, why_new = _resumable_card_session(issue_id, backend, wt)
            if resume_sid:
                refused = _resume_admission(issue_id, backend, resume_sid, run_id)
                if refused:  # no HTTP channel here: an error record and the card back to review (DP-05/25)
                    from app import _ticket_confidential
                    conf = _ticket_confidential(project_key, ident, issue_id, None,
                                                *([bound["confidential"]] if "confidential" in bound else []))
                    self._refuse_resume(issue, run_id, backend, launch_gen, refused,
                                        binding={"project_key": project_key, "issue_identifier": ident, "confidential": conf})
                    return
            self.dispatched[issue_id] = run_id
            try:
                self.push_state(issue_id, "running", gen=launch_gen)
            except BaseException:  # before the helper owns cleanup: release what admission took (R5)
                from app import _release_session
                _release_session(run_id)
                self.dispatched.pop(issue_id, None)
                raise
            try:
                _run_project_ticket(
                    project_key=project_key, ident=bound.get("issue_identifier") or issue.get("identifier") or issue_id,
                    agent=backend, confidential=bound.get("confidential"),
                    reuse_only=bool(bound.get("worktree")),  # a bound worktree is never silently recreated (I6-10)
                    prompt=f"{issue.get('identifier', '')}: {issue.get('title', '')}\n\n"
                           f"{_strip_issue_metadata(issue.get('description') or '')}",
                    title=issue.get("title", ""), run_id=run_id, linear_issue_id=issue_id,
                    task_id=run_id, launch_gen=launch_gen,
                    # the route's reservation goes on only if it is this very ticket's lock; otherwise
                    # the helper takes the ticket lock itself (REV-01)
                    ticket_hold=held.pop_all() if reserved else None,
                    resume_session=resume_sid, timeout=AI_SESSION_TIMEOUT_S if resume_sid else None,
                    note=f"new session: {why_new}" if why_new and not resume_sid else None)
            finally:
                self.dispatched.pop(issue_id, None)
            return

        import projects
        card_hold = held
        if reserved and getattr(held, "identity", None) != ("card", issue_id):  # not this card's lock (REV-01)
            held.close()
            reserved = False
        if not reserved:
            try:  # held from here through the run, so an interactive terminal or retry cannot overlap (C2, UI-02)
                card_hold.enter_context(projects.card_lock(issue_id))
            except projects.ProjectError as exc:
                logger.warning("dispatch of %s refused: %s", issue_id, exc)
                return
        from app import (_resumable_card_session, _resume_admission, _session_note, _after_card_run,
                         _issue_title_extra, _card_session, _build_resume_cmd, _release_session,
                         AI_SESSION_TIMEOUT_S)
        run_id = None
        try:
            registry = _load_registry(backend)
            # One task, one session (D3): a card continues its own session in ROOT, where generic
            # dispatch runs, and then needs no routing call (DP-28).
            resume_sid, why_new = (None, None)
            if backend in ("claude", "codex"):
                resume_sid, why_new = _resumable_card_session(issue_id, backend, ROOT)
            prev = _card_session(issue_id, backend) if resume_sid else None
            prev_skill = (prev[1].get("selected_skill") or prev[1].get("skill")) if prev else None
            prev_entry = registry.get(prev_skill or "", {})
            if resume_sid and prev_entry.get("schedule_eligible") and prev_entry.get("entrypoint"):
                resume_sid, why_new = None, "skill has its own entrypoint"
        except Exception:
            logger.exception("dispatch of %s: session lookup failed", issue_id)
            resume_sid, why_new, prev_skill = None, None, None
        try:
            registry = _load_registry(backend)
            skill_list = "\n".join(f"- {n}: {e.get('purpose', '')[:100]}" for n, e in registry.items())
            routing_prompt = (
                "Given this issue, return only the skill name that best matches.\n\n"
                f"Issue: {issue['identifier']} — {issue['title']}\n"
                f"{(issue.get('description') or '')[:500]}\n\n"
                f"Available skills:\n{skill_list}\n\n"
                "Return exactly one skill name, nothing else."
            )
            if resume_sid:
                selected_skill = prev_skill if prev_skill in registry else "_prompt"  # no routing call (DP-28)
            else:
                try:
                    result = _run_grouped(  # its own group: a routing timeout ends descendants too (RWS-016)
                        # persist=False: the routing call leaves no session in the agent's store (DP-28)
                        _ai_command(backend, routing_prompt, output_format="text", persist=False),
                        60,
                        cwd=str(ROOT),
                        env=_registry_exec_env(backend, registry),
                        text=True,
                    )
                    selected_skill = _extract_skill_name(result.stdout or "", registry)
                except Exception:
                    selected_skill = "_prompt"

            run_id = str(uuid.uuid4())
            if resume_sid:
                refused = _resume_admission(issue_id, backend, resume_sid, run_id)
                if refused:  # no HTTP channel here: an error record and the card back to review (DP-05/25)
                    self._refuse_resume(issue, run_id, backend, launch_gen, refused)
                    return
            started_at = datetime.now(timezone.utc).isoformat()
            t0 = time.monotonic()
            prompt = f"{issue['identifier']}: {issue['title']}\n\n{_strip_issue_metadata(issue.get('description') or '')}"
            self.dispatched[issue_id] = run_id
            note = f"new session: {why_new}" if why_new and not resume_sid and backend in ("claude", "codex") else None
            card_extra = {**_issue_title_extra(issue_id), **({"session_note": note} if note else {})}
            # Running is pushed before the job is published: a cancel or stall can only end the
            # run after it, so their review is never followed by this running (RWS-001).
            try:
                self.push_state(issue_id, "running", gen=launch_gen)
                socketio.emit("run_state_change", {"run_id": run_id, "state": "running", "skill": selected_skill})
            except Exception as e:  # the run never started: finish it here, not In Progress forever (RWS-007)
                self.dispatched.pop(issue_id, None)
                _write_run_log_retrying(selected_skill, "error", started_at, 0.0, prompt=prompt,
                                        error=f"could not start: {e}", run_id=run_id, linear_issue_id=issue_id,
                                        agent=backend, reset_generation=launch_gen)
                with contextlib.suppress(Exception):
                    self._mark_issue_review(issue_id, gen=launch_gen)
                return
            _running_jobs[run_id] = {
                "run_id": run_id,
                "skill": selected_skill,
                "started_at": started_at,
                "prompt": prompt,
                "state": "running",
                "last_progress_at": time.monotonic(),
                "linear_issue_id": issue_id, "launch_gen": launch_gen,  # the stall pass's tracker guard (WS-013)
                "record": {"agent": backend, "model": _agent_model(backend, cfg), "task_id": run_id,  # RWS-002
                           "selected_skill": selected_skill, "reset_generation": launch_gen},
                "agent": backend,
                **({"agent_session_id": resume_sid} if resume_sid else {}),  # live while it runs (DP-15)
                "record_extra": card_extra,
            }
            entry = registry.get(selected_skill, {})
            is_entrypoint = bool(entry.get("schedule_eligible") and entry.get("entrypoint"))
            end = _RunClaim(run_id)  # cancel/stall may end the run first; then they own its side effects
            procs: list = []  # the launched process, for cleanup after a later failure
            try:
                # Built inside the try: a missing/old dsh fails this run cleanly (error record,
                # running/dispatch entries cleared, ticket back to review) instead of hanging as running.
                from app import _card_admitted
                if not _card_admitted(issue_id, launch_gen):  # reset or removed during routing (R3-01)
                    if end():
                        _write_run_log_retrying(selected_skill, "cancelled", started_at, 0.0, prompt=prompt,
                                                error="the card was removed or reset before its run started",
                                                run_id=run_id, linear_issue_id=issue_id, agent=backend, task_id=run_id,
                                                reset_generation=launch_gen)
                        socketio.emit("run_logged", {"skill": selected_skill, "run_id": run_id})
                    self.dispatched.pop(issue_id, None)
                    return
                if resume_sid and is_entrypoint:
                    resume_sid = None  # an entrypoint skill always starts fresh (DP-21)
                if note:
                    _session_note(run_id, note)
                cmd = ([_python_path(), str(RUNNER), selected_skill] if is_entrypoint else
                       _build_resume_cmd(backend, resume_sid, prompt) if resume_sid else
                       _ai_command(backend, prompt, output_format=_agent_output_format(backend),
                                   skill_name=selected_skill, registry=registry))
                # One process engine (C0): streamed live like every other launch, session id kept.
                output, it, ot, pm, session_id, stderr_s, ok = run_agent_process(
                    run_id, cmd, stream="text" if is_entrypoint else _stream_for(backend),
                    env=_registry_exec_env(backend, registry), on_proc=procs.append,
                    timeout=AI_SESSION_TIMEOUT_S if resume_sid else None)
                import project_runs as _pr
                agent_error, turn_failed = _pr.pop_agent_failure(run_id)
                if backend == "dsh" and not is_entrypoint:
                    output = output or ""
                elif resume_sid:
                    # a resumed session keeps its real result: no silent review (DP-14, R4-03)
                    ok = ok and bool(output) and not turn_failed
                else:
                    ok = True  # a fresh launch keeps the unconditional review status
                dur = time.monotonic() - t0
                error_s = _extract_real_errors(stderr_s)
                if not ok:
                    error_s = agent_error or error_s or (f"resume of session {resume_sid} failed" if resume_sid else error_s)
                if not end():
                    return
                final_state = "review" if ok else "error"
                _write_run_log(
                    selected_skill,
                    final_state,
                    started_at,
                    dur,
                    prompt=prompt,
                    output=output,
                    error=error_s,
                    run_id=run_id,
                    linear_issue_id=issue_id,
                    selected_skill=selected_skill,
                    input_tokens=it,
                    output_tokens=ot,
                    agent=backend,
                    model=pm or _agent_model(backend, cfg),
                    task_id=run_id,
                    token_cost_usd=_compute_token_cost(ot, it, pm or _agent_model(backend, cfg)),  # STB-034
                    agent_session_id=session_id or resume_sid,
                    reset_generation=launch_gen,
                    extra=card_extra or None,
                )
                _after_card_run(run_id, issue_id, backend, session_id or resume_sid, getattr(procs[0], "pid", None) if procs else None)
                _comment_quietly(self.post_comment, issue_id, _linear_comment_body(title="AgenticOS Run", prompt=prompt, output=output, error=error_s))
                self._mark_issue_review(issue_id, gen=launch_gen)
                if reset_gen.is_current(issue_id, launch_gen):
                    socketio.emit("run_state_change", {"run_id": run_id, "state": final_state, "skill": selected_skill})
                socketio.emit("run_logged", {"skill": selected_skill, "run_id": run_id})
            except subprocess.TimeoutExpired:
                dur = time.monotonic() - t0
                _kill_and_reap(procs[0] if procs else None)
                if not end():
                    return
                msg = f"Timed out after {AI_SESSION_TIMEOUT_S if resume_sid else AI_RUN_TIMEOUT_S}s"
                _write_run_log_retrying(selected_skill, "timeout", started_at, dur, prompt=prompt, error=msg, run_id=run_id,
                               linear_issue_id=issue_id, agent=backend, reset_generation=launch_gen, agent_session_id=end.session,
                               task_id=run_id, model=_agent_model(backend, cfg), extra=card_extra or None)  # findable by retry (FB5-01)
                _after_card_run(run_id, issue_id, backend, end.session, getattr(procs[0], "pid", None) if procs else None)
                _comment_quietly(self.post_comment, issue_id, _linear_comment_body(title="AgenticOS Run Timeout", prompt=prompt, error=msg))
                self._mark_issue_review(issue_id, gen=launch_gen)
                socketio.emit("run_state_change", {"run_id": run_id, "state": "review", "skill": selected_skill})
                socketio.emit("run_logged", {"skill": selected_skill, "run_id": run_id})
            except Exception as e:
                _kill_and_reap(procs[0] if procs else None)  # a failure after launch never leaves the agent running (RWS-008/010)
                if not end():
                    return
                _write_run_log_retrying(selected_skill, "error", started_at, 0.0, prompt=prompt, error=str(e), run_id=run_id,
                               linear_issue_id=issue_id, agent=backend, reset_generation=launch_gen, agent_session_id=end.session,
                               task_id=run_id, model=_agent_model(backend, cfg), extra=card_extra or None)  # findable by retry (FB5-01)
                _after_card_run(run_id, issue_id, backend, end.session, getattr(procs[0], "pid", None) if procs else None)
                _comment_quietly(self.post_comment, issue_id, _linear_comment_body(title="AgenticOS Run Error", prompt=prompt, error=str(e)))
                self._mark_issue_review(issue_id, gen=launch_gen)
                socketio.emit("run_state_change", {"run_id": run_id, "state": "review", "skill": selected_skill})
                socketio.emit("run_logged", {"skill": selected_skill, "run_id": run_id})
        except Exception as e:
            logger.exception("_dispatch_issue failed for %s: %s", issue_id, e)
            try:
                socketio.emit("run_state_change", {"run_id": str(uuid.uuid4()), "state": "error", "skill": "unknown"})
            except Exception:
                pass
        finally:
            if run_id:
                _release_session(run_id)  # the resume claim taken at admission
            card_hold.close()

    def _refuse_resume(self, issue: dict, run_id: str, backend: str, launch_gen: int, why: str,
                       binding: dict | None = None) -> None:
        """A dispatch that cannot continue the card's session right now: nothing launches; an error
        record says why, and the card leaves In Progress (DP-05, DP-13, DP-25). A project card's
        record keeps its binding and withholds its title where records may leak (R1)."""
        from app import _write_run_log_retrying, _agent_model, _records_unsafe, _WITHHELD_PROMPT
        issue_id = issue["id"]
        prompt = f"{issue.get('identifier', '')}: {issue.get('title', '')}"
        if binding is not None and binding.get("confidential") is not False and _records_unsafe():
            prompt = _WITHHELD_PROMPT
        _write_run_log_retrying("_prompt", "error", datetime.now(timezone.utc).isoformat(), 0.0, prompt=prompt,
                                error=why, run_id=run_id, linear_issue_id=issue_id, agent=backend, task_id=run_id,
                                reset_generation=launch_gen, model=_agent_model(backend), extra=binding)
        with contextlib.suppress(Exception):
            self._mark_issue_review(issue_id, gen=launch_gen)
        if self._socketio:
            self._socketio.emit("run_logged", {"skill": "_prompt", "run_id": run_id})

    def _linear_client(self):
        """(client, tracker config) for the configured Linear tracker; raises when unconfigured."""
        tc = _load_workflow_config().get("tracker", {})
        ak = _linear_api_key_from_cfg(tc)
        if not ak:
            raise RuntimeError("Linear not configured")
        from linear_client import LinearClient
        return LinearClient(ak, tc.get("project_slug", "")), tc

    def _ensure_linear_project(self, issue: dict, project_key: str) -> None:
        """A project ticket with no Linear Project goes into its project's one at dispatch (STB §10).
        Best effort: a Linear error is logged and the dispatch continues (STB-085)."""
        if self._capability.get("type") != "linear" or not ("project_id" in issue and not issue["project_id"]):
            return
        try:
            client, tc = self._linear_client()
            pid = linear_project_id(client, issue.get("team_id") or tc.get("team_id", ""), project_key,
                                    tc.get("project_slug", ""))
            if pid:
                client.set_issue_project(issue["id"], pid)
                cached = self.issues_cache.get(issue["id"])
                if cached is not None:
                    cached["project_id"] = pid
        except Exception as e:
            logger.warning("Linear Project for %s not set: %s", issue.get("identifier") or issue.get("id"), e)

    def move_to_todo(self, issue_id: str) -> None:
        """Move a card back to Todo the way a board drag does, tracker state included (STB §2.4).
        The caller holds reset_gen.issue_lock and has bumped the generation. Raises on failure."""
        state = _BOARD_TO_LINEAR["todo"]
        if self._capability.get("type") == "linear":
            client, _tc = self._linear_client()
            if not client.update_issue_state(issue_id, state):
                raise RuntimeError(f"Linear did not accept state {state!r}")
            with contextlib.suppress(Exception):
                self.get_local_tracker().update_issue_state(issue_id, state)
        elif not self.get_local_tracker().update_issue_state(issue_id, state):
            raise RuntimeError("local task not found")
        self._local_overrides.pop(issue_id, None)
        self.dispatched.pop(issue_id, None)
        if issue_id in self.issues_cache:
            cached = {**self.issues_cache[issue_id], "state": state}
            self.issues_cache[issue_id] = cached
            tid = cached.get("team_id") or ""
            if tid and issue_id in self._issues_by_team.get(tid, {}):
                self._issues_by_team[tid][issue_id] = cached
        if self._socketio:
            self._socketio.emit("linear_issues_updated", {"count": len(self.issues_cache)})

    def set_card_title(self, issue_id: str, title: str) -> None:
        """A card-row rename (§3): the tracker confirms the title first; only then do the caches,
        the local override and the board change. Raises with nothing changed otherwise (DP-04)."""
        import reset_gen
        with reset_gen.issue_lock(issue_id):
            if self._capability.get("type") == "linear":
                client, _tc = self._linear_client()
                confirmed = client.update_title(issue_id, title)  # title-only mutation (DP-42)
                from app import _confirm_linear_title
                _confirm_linear_title(issue_id, confirmed["title"], confirmed["updated_at"])
                with contextlib.suppress(Exception):  # the local backup follows Linear
                    self.get_local_tracker().update_issue(issue_id, title=title)
                self._remember_local_override(issue_id, {"title": title})  # a stale poll keeps it shown
            elif not self.get_local_tracker().update_issue(issue_id, title=title):
                raise ValueError("card not found")
            cached = dict(self.issues_cache.get(issue_id) or {"id": issue_id})
            cached["title"] = title
            self.issues_cache[issue_id] = cached
            tid = cached.get("team_id") or ""
            if tid and issue_id in self._issues_by_team.get(tid, {}):
                self._issues_by_team[tid][issue_id] = cached  # the team-filtered board too (DP-23)
        if self._socketio:
            self._socketio.emit("linear_issues_updated", {"count": len(self.issues_cache)})

    def create_session_issue(self, title: str, description: str, agent: str, project_key: str) -> dict:
        """One Todo issue for a session that has no card (STB §2.5), composed like the "+" form:
        `project:<key>` label, agent marker, the project's Linear Project. Synchronous, so the
        record links to the final id. Raises (ValueError, RuntimeError, LinearError) with nothing
        created on a refused label or Linear error."""
        labels = _project_labels({"project": project_key})
        agent = canonical_agent(agent)
        desc = _compose_issue_description(description, agent)
        tc = _load_workflow_config().get("tracker", {})
        tid = tc.get("team_id", "")
        if self._capability.get("type") == "linear":
            client, tc = self._linear_client()
            if not tid:
                raise RuntimeError("tracker.team_id is required")
            label_ids = []
            for name in labels:  # every label or no issue (STB-041)
                label_id = client.ensure_label(tid, name)
                if not label_id:
                    raise RuntimeError(f"Linear label {name!r} could not be resolved")
                label_ids.append(label_id)
            project_id = linear_project_id(client, tid, project_key, tc.get("project_slug", ""))
            created = client.create_issue(tid, title, desc, label_ids=label_ids,
                                          **({"project_id": project_id} if project_id else {}))
            if not created:
                raise RuntimeError("Linear did not create the issue")
            issue = _normalize_linear_issue(created)
            _note_linear_title(issue)  # a new to-board card has a confirmed title before any poll (DP-46)
            issue["labels"] = sorted(set(issue["labels"]) | set(labels))
            with self.get_local_tracker().raw_transaction() as raw:
                raw[issue["id"]] = dict(issue)
        else:
            issue = self.get_local_tracker().create_issue(title, desc, preferred_agent=agent, team_id=tid, labels=labels)
        self.issues_cache[issue["id"]] = dict(issue)
        self._fresh_ids[issue["id"]] = time.monotonic()
        if issue.get("team_id"):
            self._issues_by_team.setdefault(issue["team_id"], {})[issue["id"]] = dict(issue)
        if self._socketio:
            self._socketio.emit("linear_issues_updated", {"count": len(self.issues_cache)})
        return issue

    def canceled_issues(self) -> list[dict]:
        """The trash: Canceled issues. Local mode reads the tracker directly, since the board
        fetch returns only active states (STB-073)."""
        src = ([{**v, "id": k} for k, v in self.issues_cache.items()]  # the cache key is the id (SBI-019)
               if self._capability.get("type") == "linear" else self.get_local_tracker().fetch_issues())
        gone = archived_ids()
        return [i for i in src if _linear_state_key(i.get("state")) in ("canceled", "cancelled") and i.get("id") not in gone]

    def _still_canceled(self, issue_id: str) -> bool:
        if self._capability.get("type") == "linear":
            state = (self.issues_cache.get(issue_id) or {}).get("state")
        else:
            state = (self.get_local_tracker().fetch_issue(issue_id) or {}).get("state")
        return _linear_state_key(state) in ("canceled", "cancelled")

    def empty_trash(self) -> tuple[list[str], dict[str, str]]:
        """Archive every Canceled issue (Linear: issueArchive, recoverable; local: removed) and
        evict it everywhere the poller and board read. Run records and transcripts are not
        touched. Each issue is rechecked and archived under its issue lock, so a card that a
        Resume or drag moved meanwhile is skipped (SBI-004). Returns (archived ids,
        {identifier: failure reason}) (STB §11)."""
        import reset_gen
        linear = self._capability.get("type") == "linear"
        client = self._linear_client()[0] if linear else None
        done, failed = [], {}
        for issue in self.canceled_issues():
            iid = issue["id"]
            with reset_gen.issue_lock(iid):
                if not self._still_canceled(iid):
                    continue
                try:
                    if linear:
                        client.archive_issue(iid)
                    elif not self.get_local_tracker().delete_issue(iid):
                        continue
                except Exception as e:
                    failed[issue.get("identifier") or iid] = str(e)
                    continue
                reset_gen.bump(iid)  # a run still finishing can no longer push this card (SBI-005)
                self._evict([iid])
                done.append(iid)
        return done, failed

    def _evict(self, ids: list[str]) -> None:
        if not ids:
            return
        import reset_gen
        _add_archived_ids(ids)  # first: a poll after this point skips them (STB-050)
        for iid in ids:
            with reset_gen.issue_lock(iid):
                self.issues_cache.pop(iid, None)
                for team_dict in self._issues_by_team.values():
                    team_dict.pop(iid, None)
                self._local_overrides.pop(iid, None)
                self.dispatched.pop(iid, None)
        with self.get_local_tracker().raw_transaction() as tasks:
            for iid in ids:
                tasks.pop(iid, None)
        with contextlib.suppress(Exception):
            import app as app_mod
            if any(i in app_mod._linear_dismissed for i in ids):
                app_mod._linear_dismissed.difference_update(ids)
                app_mod._save_dismissed()
        if self._socketio:
            self._socketio.emit("linear_issues_updated", {"count": len(self.issues_cache)})

    # ── Route registration ────────────────────────────────────────────────

    def register_routes(self, app) -> None:
        self._register_linear_routes(app)
        self._register_config_route(app)

    def _register_linear_routes(self, app) -> None:
        @app.route("/api/linear/teams")
        def _teams():
            cfg = _load_workflow_config()
            tc = cfg.get("tracker", {})
            ak = _linear_api_key_from_cfg(tc)
            if not ak:
                return jsonify([])
            try:
                from linear_client import LinearClient
                return jsonify(LinearClient(ak, tc.get("project_slug", "")).fetch_teams())
            except Exception as e:
                logger.error("fetch_teams error: %s", e)
                return jsonify([])

        @app.route("/api/linear/issues")
        def _issues_get():
            team_id = (request.args.get("team_id") or "").strip() or None
            if self._capability.get("type") == "linear":
                # Return cache immediately; avoid blocking on Linear API
                if not self.issues_cache:
                    try:
                        local = self.get_local_tracker()
                        gone = archived_ids()
                        for issue in local.fetch_issues():
                            if issue["id"] not in gone:
                                self.issues_cache[issue["id"]] = issue
                    except Exception:
                        pass
                gone = archived_ids()  # a stray cache entry of an emptied card never shows (SBI-005)
                if team_id and team_id in self._issues_by_team:
                    return jsonify([
                        self._apply_local_override(iid, issue)
                        for iid, issue in self._issues_by_team[team_id].items() if iid not in gone
                    ])
                # Fallback: filter issues_cache by team_id field if team specified
                if team_id:
                    return jsonify([
                        self._apply_local_override(k, v)
                        for k, v in self.issues_cache.items()
                        if v.get("team_id") == team_id and k not in gone
                    ])
                return jsonify([  # filtered by cache key: an incomplete value cannot slip through (SBI-012)
                    self._apply_local_override(k, v)
                    for k, v in self.issues_cache.items() if k not in gone
                ])
            t = self.get_local_tracker()
            cfg = _load_workflow_config()
            return jsonify(t.fetch_issues(
                _linear_poll_states(cfg.get("tracker", {})),
                team_id=team_id,
            ))

        @app.route("/api/linear/issues", methods=["POST"])
        def _issues_post():
            data = request.get_json(silent=True) or {}
            title = (data.get("title") or "").strip()
            if not title:
                return jsonify({"error": "title required"}), 400
            desc = (data.get("description") or "").strip()
            attachments = data.get("attachments") or []
            desc = _append_attachments_to_text(desc, attachments)
            pa = (data.get("agent") or "").strip().lower()
            pa = canonical_agent(pa)
            try:  # validated before anything is created (B)
                labels = _project_labels(data)
            except ValueError as exc:
                return jsonify({"error": str(exc)}), 400
            desc = _compose_issue_description(desc, pa)
            cfg = _load_workflow_config()
            tc = cfg.get("tracker", {})
            tid = (data.get("team_id") or "").strip() or tc.get("team_id", "")
            if self._capability.get("type") == "local":
                t = self.get_local_tracker()
                issue = t.create_issue(title, desc, preferred_agent=pa, team_id=tid, labels=labels)
                nd = dict(issue)
                self.issues_cache[issue["id"]] = nd
                if tid:
                    self._issues_by_team.setdefault(tid, {})[issue["id"]] = nd
                if self._socketio:
                    self._socketio.emit("linear_issues_updated", {"count": len(self.issues_cache)})
                return jsonify({"ok": True, "issue": nd})
            ak = _linear_api_key_from_cfg(tc)
            if not ak:
                return jsonify({"error": "Linear not configured"}), 503
            if not tid:
                return jsonify({"error": "team_id required"}), 400
            # Local-first: write to local tracker immediately, return to client, sync Linear in background
            local = self.get_local_tracker()
            local_issue = local.create_issue(title, desc, preferred_agent=pa, team_id=tid, labels=labels)
            local_id = local_issue["id"]
            self.issues_cache[local_id] = dict(local_issue)
            self._fresh_ids[local_id] = time.monotonic()  # the placeholder survives polls until the swap (SBI-018)
            self._issues_by_team.setdefault(tid, {})[local_id] = dict(local_issue)
            if self._socketio:
                self._socketio.emit("linear_issues_updated", {"count": len(self.issues_cache)})

            def _bg_sync_to_linear():
                try:
                    from linear_client import LinearClient
                    client = LinearClient(ak, tc.get("project_slug", ""))
                    label_ids = []
                    for name in labels:  # every label or no issue: a task must never lose its project (UI-01)
                        label_id = client.ensure_label(tid, name)
                        if not label_id:
                            raise RuntimeError(f"Linear label {name!r} could not be resolved; task stays local")
                        label_ids.append(label_id)
                    project_id = None
                    try:  # its project's Linear Project, else the default one (STB §10/STB-064)
                        import project_runs
                        project_id = linear_project_id(client, tid, project_runs.project_key_from_labels(labels),
                                                       tc.get("project_slug", ""))
                    except Exception as e:
                        # ponytail: a Project that cannot be resolved never blocks the task itself
                        logger.warning("Linear Project for %s not resolved (%s); created without one", local_id, e)
                    linear_issue = client.create_issue(tid, title, desc, label_ids=label_ids,
                                                       **({"project_id": project_id} if project_id else {}))
                    if not linear_issue:
                        logger.warning("Linear create returned nothing for local %s", local_id)
                        return
                    n = _normalize_linear_issue(linear_issue)
                    _note_linear_title(n)  # confirmed by Linear's create response, before the id swap (R6-02)
                    # The project label decides where the task runs: never lose it in the swap (B, R03).
                    n["labels"] = sorted(set(n["labels"]) | set(labels))
                    real_id = linear_issue["id"]
                    # Persist the alias before the local id disappears, so the dashboard can always recover it.
                    record_id_alias(local_id, real_id)
                    # Swap local placeholder → real Linear ID in local tracker and cache
                    with local.raw_transaction() as raw:  # locked: concurrent writers survive (I5-05)
                        # ponytail: edits made while the create is pending are lost (pre-existing
                        # local-first gap, out of scope here; needs an acknowledged edit queue).
                        raw.pop(local_id, None)
                        raw[real_id] = dict(n)
                    if local_id in self._local_overrides:
                        self._local_overrides[real_id] = self._local_overrides.pop(local_id)
                    self.issues_cache.pop(local_id, None)
                    self._fresh_ids.pop(local_id, None)
                    self.issues_cache[real_id] = n
                    self._fresh_ids[real_id] = time.monotonic()
                    if tid:
                        team_cache = self._issues_by_team.setdefault(tid, {})
                        team_cache.pop(local_id, None)
                        team_cache[real_id] = n
                    if self._socketio:  # emit before the slow comment call so the dashboard migrates early
                        self._socketio.emit("linear_issues_updated", {"count": len(self.issues_cache),
                                                                       "id_map": {local_id: real_id}})
                    _post_linear_comment_raw(real_id, _issue_agent_comment_body(n.get("preferred_agent")), ak)
                except Exception as e:
                    logger.error("Background Linear create failed: %s", e)

            from app import _start_counted
            _start_counted(_bg_sync_to_linear)
            return jsonify({"ok": True, "issue": local_issue})

        @app.route("/api/linear/issues/<issue_id>")
        def _issues_detail(issue_id: str):
            if self._capability.get("type") == "local":
                issue = self.get_local_tracker().fetch_issue(issue_id)
                return jsonify(issue) if issue else (jsonify({"error": "not found"}), 404)
            cfg = _load_workflow_config()
            tc = cfg.get("tracker", {})
            ak = _linear_api_key_from_cfg(tc)
            if not ak:
                return jsonify({"error": "not configured"}), 400
            try:
                from linear_client import LinearClient
                issue = LinearClient(ak, tc.get("project_slug", "")).fetch_issue(issue_id)
                if not issue:
                    return jsonify({"error": "not found"}), 404
                normalized = _normalize_linear_issue(issue)
                self._clear_local_override_if_synced(issue_id, normalized)
                return jsonify(self._apply_local_override(issue_id, normalized))
            except Exception as e:
                return jsonify({"error": str(e)}), 500
        @app.route("/api/linear/issues/local/<issue_id>", methods=["PATCH", "POST"])
        @_tracker_reset_route
        def _issues_local_patch(issue_id: str):
            """Write-only local state update, no Linear API call."""
            if issue_id in archived_ids():  # emptied from the trash: never written back (SBI-017)
                return jsonify({"error": "this card was emptied from the trash"}), 404
            data = request.get_json(silent=True) or {}
            if data.get("state_name") and _is_linear_in_progress(data["state_name"]) and (
                    unsynced_local_id(issue_id) or card_locked(self.issues_cache.get(issue_id), issue_id)):
                # the board writes this before its dispatching PATCH: a refused dispatch changes nothing (UI2-08)
                return jsonify({"error": "this card cannot start now (not synced to Linear, or held by a terminal)"}), 409
            local = self.get_local_tracker()
            preferred_agent = canonical_agent(data.get("preferred_agent"))
            self._remember_local_override(issue_id, data, preferred_agent)
            updated = local.update_issue(
                issue_id,
                title=data.get("title"),
                description=data.get("description"),
                state_name=data.get("state_name"),
                preferred_agent=preferred_agent,
            )
            # Only an authoritative local tracker renames sessions; in Linear mode this route is the
            # editor's parallel mirror and would rename on a failed Linear update (DP-10).
            if updated and data.get("title") is not None and self._capability.get("type") == "local":
                _title_changed(issue_id, updated.get("title"))
            if issue_id in self.issues_cache:
                cached = dict(self.issues_cache[issue_id])
                if data.get("state_name"):
                    cached["state"] = data["state_name"]
                if data.get("title") is not None:
                    cached["title"] = data["title"]
                if data.get("description") is not None:
                    cached["description"] = data["description"]
                if preferred_agent is not None:
                    cached["preferred_agent"] = preferred_agent
                self.issues_cache[issue_id] = cached
                tid = cached.get("team_id") or ""
                if tid and issue_id in self._issues_by_team.get(tid, {}):
                    self._issues_by_team[tid][issue_id] = cached
            if self._socketio:
                self._socketio.emit("linear_issues_updated", {"count": len(self.issues_cache)})
            return jsonify({"ok": True})


        @app.route("/api/linear/issues/<issue_id>", methods=["PATCH", "POST"])
        @_tracker_reset_route
        def _issues_patch(issue_id: str):
            if issue_id in archived_ids():  # under the issue lock (_tracker_reset_route), before any write (SBI-017)
                return jsonify({"error": "this card was emptied from the trash"}), 404
            data = request.get_json(silent=True) or {}
            cfg = _load_workflow_config()
            tc = cfg.get("tracker", {})
            preferred_agent = canonical_agent(data.get("preferred_agent"))
            box = {"hold": None}  # the card's lock, reserved before any change and handed to dispatch (UI3-01)
            if data.get("state_name") and _is_linear_in_progress(data["state_name"]) \
                    and not unsynced_local_id(issue_id) and not self._issue_is_running(issue_id):
                import projects
                current = self.issues_cache.get(issue_id)
                if current is None and self._capability.get("type") == "local":
                    current = self.get_local_tracker().fetch_issue(issue_id)  # persisted, labels included (REV-01)
                try:
                    box["hold"] = reserve_card(current, issue_id)
                except projects.TicketLocked:
                    return jsonify({"error": "an interactive terminal holds this card; close it first"}), 409
                except projects.ProjectError as exc:  # e.g. an unknown project label: say so (FB3-01)
                    return jsonify({"error": str(exc)}), 400
            try:
                return _issues_patch_reserved(issue_id, data, cfg, tc, preferred_agent, box)
            finally:
                if box["hold"] is not None:  # not handed to a dispatch
                    box["hold"].close()

        def _issues_patch_reserved(issue_id, data, cfg, tc, preferred_agent, box):
            def _handoff():
                hold, box["hold"] = box["hold"], None
                return hold
            if self._capability.get("type") == "local":
                previous_board_status = _linear_state_to_board(self.issues_cache.get(issue_id, {}).get("state"))
                issue = self.get_local_tracker().update_issue(
                    issue_id,
                    title=data.get("title"),
                    description=data.get("description"),
                    state_name=data.get("state_name"),
                    preferred_agent=preferred_agent,
                )
                if issue:
                    _state_committed()
                    self.issues_cache[issue_id] = issue
                    if self._socketio:
                        self._socketio.emit("linear_issues_updated", {"count": len(self.issues_cache)})
                    if data.get("title") is not None:
                        _title_changed(issue_id, issue.get("title"))  # the local tracker is authoritative here
                    if data.get("state_name") and _is_linear_in_progress(data["state_name"]) and not self._issue_is_running(issue_id):
                        self.dispatched.pop(issue_id, None)
                        self._start_dispatch(issue, cfg, previous_board_status, card_hold=_handoff())
                    return jsonify({"ok": True, "issue": issue})
                return jsonify({"error": "not found"}), 404
            ak = _linear_api_key_from_cfg(tc)
            if not ak:
                return jsonify({"error": "not configured"}), 400
            if data.get("state_name") and _is_linear_in_progress(data["state_name"]) and unsynced_local_id(issue_id):
                # refused before any override or cache change (B, UI2-08)
                return jsonify({"error": "not synced to Linear yet; try again in a moment"}), 409
            self._remember_local_override(issue_id, data, preferred_agent)

            # ── Local-first: update local + dispatch immediately ──────────
            if data.get("state_name") and _is_linear_in_progress(data["state_name"]):
                local = self.get_local_tracker()
                previous_board_status = _linear_state_to_board(self.issues_cache.get(issue_id, {}).get("state"))
                local.update_issue_state(issue_id, data["state_name"])
                cached = dict(self.issues_cache.get(issue_id) or {})
                cached["state"] = data["state_name"]
                if data.get("title") is not None:
                    cached["title"] = data["title"]
                if data.get("description") is not None:
                    cached["description"] = data["description"]
                if preferred_agent is not None:
                    cached["preferred_agent"] = preferred_agent
                self.issues_cache[issue_id] = cached
                tid = cached.get("team_id") or ""
                if tid and issue_id in self._issues_by_team.get(tid, {}):
                    self._issues_by_team[tid][issue_id] = cached
                if not self._issue_is_running(issue_id):
                    self.dispatched.pop(issue_id, None)
                    self._start_dispatch(cached, cfg, previous_board_status, card_hold=_handoff())
                import reset_gen
                from app import _start_counted
                _start_counted(self._linear_sync_patch, issue_id, data, cfg, preferred_agent,
                               reset_gen.current(issue_id))  # counted until persisted (BUILD-005)
                return jsonify({"ok": True, "issue": cached})

            # ── Synchronous Linear path for non-dispatch updates ──────────
            try:
                from linear_client import LinearClient
                cl = LinearClient(ak, tc.get("project_slug", ""))
                existing = cl.fetch_issue(issue_id)
                if not existing:
                    return jsonify({"error": "not found"}), 404
                updates: dict[str, object] = {}
                if data.get("title") is not None or data.get("description") is not None:
                    updates["title"] = data.get("title")
                    updates["description"] = data.get("description")
                if preferred_agent is not None:
                    base_description = data.get("description")
                    if base_description is None:
                        base_description = existing.get("description", "")
                    updates["description"] = _compose_issue_description(str(base_description or ""), preferred_agent)
                if updates:
                    cl.update_issue(issue_id, **updates)  # type: ignore[arg-type]
                if data.get("state_name"):
                    if not cl.update_issue_state(issue_id, data["state_name"]):
                        # Linear refused (or could not resolve) the state: say so, keep no masking override (UI11-01)
                        self._local_overrides.pop(issue_id, None)
                        return jsonify({"error": f"Linear did not accept state {data['state_name']!r}"}), 502
                    _state_committed()
                issue = cl.fetch_issue(issue_id)
                if issue:
                    _note_linear_title(issue)  # what Linear confirmed, before any override (DP-31)
                    n = _normalize_linear_issue(issue)
                    self._clear_local_override_if_synced(issue_id, n)
                    n = self._apply_local_override(issue_id, n)
                    self.issues_cache[issue_id] = n
                    if self._socketio:
                        self._socketio.emit("linear_issues_updated", {"count": len(self.issues_cache)})
                    if data.get("title") is not None and issue.get("title") == data.get("title"):
                        _title_changed(issue_id, issue.get("title"))  # confirmed: rename the card's sessions
                    return jsonify({"ok": True, "issue": n})
                return jsonify({"error": "update failed"}), 500
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @app.route("/api/linear/issues/<issue_id>/comment", methods=["POST"])
        def _issues_comment(issue_id: str):
            data = request.get_json(silent=True) or {}
            text = (data.get("feedback") or data.get("text") or "").strip()
            attachments = data.get("attachments") or []
            if not text and not attachments:
                return jsonify({"error": "feedback or attachment required"}), 400
            if self._is_confidential_issue(issue_id):  # Decision 4: feedback stays in the local record
                return jsonify({"ok": False, "error": "confidential project: feedback is not posted to the tracker"}), 403
            body = _linear_comment_body(
                title=data.get("title") or "AgenticOS Feedback",
                feedback=text,
                attachments=attachments,
            )
            if self._capability.get("type") == "local":
                return jsonify({"ok": self.get_local_tracker().post_comment(issue_id, body)})
            cfg = _load_workflow_config()
            tc = cfg.get("tracker", {})
            ak = _linear_api_key_from_cfg(tc)
            ok = _post_linear_comment_raw(issue_id, body, ak)
            return (jsonify({"ok": ok}) if ok else (jsonify({"ok": False, "error": "comment failed"}), 500))

        @app.route("/api/linear/trash")
        def _trash_list():
            return jsonify(self.canceled_issues())

        @app.route("/api/linear/trash/empty", methods=["POST"])
        def _trash_empty():
            try:
                done, failed = self.empty_trash()
            except Exception as e:
                return jsonify({"ok": False, "error": str(e)}), 409
            return jsonify({"ok": not failed, "archived": len(done), "failed": failed})

        @app.route("/api/linear/id-aliases")
        def _id_aliases():
            return jsonify(load_id_aliases())

        @app.route("/api/linear/projects")
        def _projects():
            cfg = _load_workflow_config()
            tc = cfg.get("tracker", {})
            ak = _linear_api_key_from_cfg(tc)
            if not ak:
                return jsonify([])
            try:
                from linear_client import LinearClient
                return jsonify(LinearClient(ak, tc.get("project_slug", "")).fetch_projects())
            except Exception as e:
                return jsonify({"error": str(e)}), 500

    def _register_config_route(self, app) -> None:
        @app.route("/api/linear/config")
        def _linear_config():
            cfg = _load_workflow_config()
            tc = cfg.get("tracker", {})
            return jsonify({
                "api_key_set": bool(_linear_api_key_from_cfg(tc)),
                "kind": tc.get("kind", ""),
                "project_slug": tc.get("project_slug", ""),
                "team_id": tc.get("team_id", ""),
                "tracker_type": self._capability.get("type", "none"),
            })

    # ── Async Linear refresh (non-blocking) ──────────────────────────

    def _refresh_linear_async(self) -> None:
        """Refresh issues cache from Linear API in background thread."""
        try:
            cfg = _load_workflow_config()
            tc = cfg.get("tracker", {})
            ak = _linear_api_key_from_cfg(tc)
            if not ak or tc.get("kind") != "linear":
                return
            from linear_client import LinearClient
            cl = LinearClient(ak, tc.get("project_slug", ""))
            live = cl.fetch_issues(_linear_poll_states(tc), team_id=tc.get("team_id", "") or None)
            # Build new dict first, then swap — avoids empty-cache flicker
            updated: dict[str, dict] = {}
            title_syncs: set = set()
            for issue in live:
                self._localize_issue(issue)
                _note_linear_title(issue, title_syncs)
                updated[issue["id"]] = _normalize_linear_issue(issue)
            self.issues_cache.clear()
            self.issues_cache.update(updated)
            _start_title_syncs(title_syncs)
            # Only notify via socket if cache changed (the polling loop already handles periodic emit)
        except Exception as e:
            logger.debug("async linear refresh failed: %s", e)

    # ── Local backup helpers ───────────────────────────────────────────

    def _localize_issue(self, issue: dict) -> None:
        """Write a Linear issue to local state/tasks.json as backup."""
        try:
            local = self.get_local_tracker()
            n = _normalize_linear_issue(issue)
            # Upsert: update_issue for existing, create for new
            existing = local.fetch_issue(issue["id"])
            if existing:
                local.update_issue(
                    issue["id"],
                    title=n.get("title"),
                    description=n.get("description"),
                    state_name=n.get("state"),
                    preferred_agent=n.get("preferred_agent"),
                    labels=sorted(set(n.get("labels") or []) | set(existing.get("labels") or [])),
                )
            else:
                data = {
                    "id": issue["id"],
                    "identifier": issue.get("identifier", issue.get("id", "")),
                    "title": n.get("title", ""),
                    "description": n.get("description", ""),
                    "state": n.get("state", "Todo"),
                    "url": issue.get("url", ""),
                    "preferred_agent": n.get("preferred_agent"),
                    "labels": n.get("labels") or [],
                    "team_id": issue.get("team_id", ""),
                    "team_key": issue.get("team_key", ""),
                    "team_name": issue.get("team_name", ""),
                    "created_at": issue.get("created_at", ""),
                    "updated_at": issue.get("updated_at", ""),
                }
                with local.raw_transaction() as tasks:  # locked with every other tasks.json writer
                    tasks[issue["id"]] = data
        except Exception as e:
            logger.debug("localize_issue failed for %s: %s", issue.get("id", "?"), e)

    def _sync_cache_to_local(self) -> None:
        """Sync all cached issues to local tracker, keyed by Linear UUID.

        使用 Linear issue 的原始 UUID 作为 tasks.json 的存储 key，确保同一
        issue 每次轮询都能被正确识别为已有条目，避免每轮重复创建。
        """
        if not self.issues_cache:
            return
        try:
            local = self.get_local_tracker()
            with local.raw_transaction() as tasks:  # one locked load -> merge -> save (plan 4b)
                for issue in list(self.issues_cache.values()):
                    existing = tasks.get(issue["id"])
                    if existing:
                        existing.update(issue)
                    else:
                        tasks[issue["id"]] = dict(issue)
        except Exception as e:
            logger.debug("_sync_cache_to_local failed: %s", e)

    def _linear_sync_patch(self, issue_id: str, data: dict, cfg: dict, preferred_agent: str | None,
                           gen: int | None = None) -> None:
        """Async Linear sync for state/metadata updates (runs in daemon thread).

        Serialized with other tracker writers under the issue lock. A state change queued
        before a later reset is dropped; title/description edits still land (I5-06)."""
        import reset_gen
        with reset_gen.issue_lock(issue_id):
            if issue_id in archived_ids():
                return  # SBI-005
            if not reset_gen.is_current(issue_id, gen):
                data = {k: v for k, v in data.items() if k != "state_name"}
            self._linear_sync_patch_locked(issue_id, data, cfg, preferred_agent)

    def _linear_sync_patch_locked(self, issue_id: str, data: dict, cfg: dict, preferred_agent: str | None) -> None:
        tc = cfg.get("tracker", {})
        ak = _linear_api_key_from_cfg(tc)
        if not ak:
            return
        try:
            from linear_client import LinearClient
            cl = LinearClient(ak, tc.get("project_slug", ""))
            existing = cl.fetch_issue(issue_id)
            if not existing:
                return
            updates: dict[str, object] = {}
            if data.get("title") is not None or data.get("description") is not None:
                updates["title"] = data.get("title")
                updates["description"] = data.get("description")
            if preferred_agent is not None:
                base_description = data.get("description") or existing.get("description", "")
                updates["description"] = _compose_issue_description(str(base_description), preferred_agent)
            if updates:
                cl.update_issue(issue_id, **updates)
            if data.get("state_name"):
                cl.update_issue_state(issue_id, data["state_name"])
            # Refresh cache with Linear's authoritative version
            synced = cl.fetch_issue(issue_id)
            if synced:
                _note_linear_title(synced)
                if data.get("title") is not None and synced.get("title") == data.get("title"):
                    _title_changed(issue_id, synced.get("title"))  # the local-first branch's confirmation (DP-31)
                normalized = _normalize_linear_issue(synced)
                self._clear_local_override_if_synced(issue_id, normalized)
                normalized = self._apply_local_override(issue_id, normalized)
                self.issues_cache[issue_id] = normalized
                tid = normalized.get("team_id") or ""
                if tid and issue_id in self._issues_by_team.get(tid, {}):
                    self._issues_by_team[tid][issue_id] = normalized
                if self._socketio:
                    self._socketio.emit("linear_issues_updated", {"count": len(self.issues_cache)})
        except Exception as e:
            logger.error("Async Linear sync failed for %s: %s", issue_id, e)

    # ── Bridge methods (called from app.py) ──────────────────────────────

    def push_state(self, issue_id: str, board_status: str, gen: int | None = None) -> None:
        """`gen` = the reset generation the caller launched under (None: unconditional)."""
        import reset_gen
        with reset_gen.issue_lock(issue_id):
            # inside the lock: an Empty trash holding it finishes its eviction first (SBI-005/012)
            if not reset_gen.is_current(issue_id, gen) or issue_id in archived_ids():
                return
            state_name = _BOARD_TO_LINEAR.get(board_status)
            if state_name:
                cached = dict(self.issues_cache.get(issue_id) or {})
                cached["state"] = state_name
                cached.setdefault("id", issue_id)  # never an id-less entry (SBI-019)
                self.issues_cache[issue_id] = cached
                if board_status == "review":
                    self.dispatched.pop(issue_id, None)
                if self._socketio:
                    self._socketio.emit("linear_issues_updated", {"count": len(self.issues_cache)})
        from app import _start_counted, MaintenanceRefused
        try:  # counted until persisted; inherits the caller's admission (BUILD-005/008)
            _start_counted(self._push_sync, issue_id, board_status, gen)
        except MaintenanceRefused as exc:  # an uncounted caller during maintenance
            logger.warning("tracker push for %s refused: %s", issue_id, exc)

    def _push_sync(self, issue_id: str, board_status: str, gen: int | None = None) -> None:
        """Apply a state push. The generation is re-checked inside the issue lock, so a push
        still in flight when a reset arrives is dropped instead of landing after it (MPD-45)."""
        import reset_gen
        with reset_gen.issue_lock(issue_id):
            if not reset_gen.is_current(issue_id, gen) or issue_id in archived_ids():
                return
            cfg = _load_workflow_config()
            tc = cfg.get("tracker", {})
            if tc.get("kind") == "linear" and _has_env_key("LINEAR_API_KEY"):
                self._push_linear(issue_id, board_status, tc)
            else:
                self.get_local_tracker().push_state(issue_id, board_status)

    def _push_linear(self, issue_id: str, board_status: str, tc: dict) -> None:
        ls = _BOARD_TO_LINEAR.get(board_status)
        if not ls:
            return
        try:
            from linear_client import LinearClient
            ak = _linear_api_key_from_cfg(tc)
            if not ak or not tc.get("project_slug"):
                return
            cl = LinearClient(ak, tc["project_slug"])
            cl.update_issue_state(issue_id, ls)
            synced = cl.fetch_issue(issue_id)
            if synced:
                self.issues_cache[issue_id] = _normalize_linear_issue(synced)
                if self._socketio:
                    self._socketio.emit("linear_issues_updated", {"count": len(self.issues_cache)})
        except Exception as e:
            logger.error("Linear state push failed: %s", e)

    def post_comment(self, issue_id: str, body: str) -> bool:
        cfg = _load_workflow_config()
        tc = cfg.get("tracker", {})
        if tc.get("kind") == "linear" and _has_env_key("LINEAR_API_KEY"):
            return _post_linear_comment_raw(issue_id, body, _linear_api_key_from_cfg(tc))
        return self.get_local_tracker().post_comment(issue_id, body)

    def get_local_tracker(self):
        if self._local_tracker is None:
            from runner.modules.linear.local_tracker import LocalTracker
            self._local_tracker = LocalTracker(STATE_DIR)
        return self._local_tracker


# ── Module registration ────────────────────────────────────────────────────

from runner.core.module_registry import registry

module = LinearModule()
registry.register(module)
