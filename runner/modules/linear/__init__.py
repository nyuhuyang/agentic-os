"""Linear 集成模块 + 本地任务跟踪降级方案。

当 LINEAR_API_KEY 可用且 WORKFLOW.md 中 tracker.kind == "linear" 时，
该模块连接到 Linear GraphQL API。当不可用时，自动降级到本地
`state/tasks.json` 文件跟踪。

模块名: "linear"
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import jsonify, request

from runner.core.module_registry import AgenticModule

logger = logging.getLogger(__name__)

_HERE = Path(__file__).resolve().parent
_PROTO = _HERE.parent.parent.parent
STATE_DIR = _PROTO / "state"


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


def _linear_state_key(state: str | None) -> str:
    return re.sub(r"\s+", " ", (state or "").strip()).lower()


def _is_linear_in_progress(state: str | None) -> bool:
    return _linear_state_key(state) == "in progress"


def _linear_poll_states(tracker: dict) -> list[str]:
    active = list(tracker.get("active_states", ["Todo", "In Progress", "In Review"]))
    if "Backlog" not in active:
        active.insert(0, "Backlog")
    if "In Review" not in active:
        active.append("In Review")
    terminal = list(tracker.get("terminal_states", ["Done", "Canceled", "Duplicate"]))
    seen: set[str] = set()
    ordered: list[str] = []
    for s in active + terminal:
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
    r"<!--\s*agent_backend:\s*(claude|codex|aider|deepseek)\s*-->\s*", re.IGNORECASE
)


def _extract_issue_agent(description: str | None) -> str | None:
    if not description:
        return None
    m = _ISSUE_AGENT_MARKER_RE.search(description)
    if m:
        agent = m.group(1).strip().lower()
        return "deepseek" if agent == "aider" else agent
    return None


def _strip_issue_metadata(description: str | None) -> str:
    if not description:
        return ""
    return _ISSUE_AGENT_MARKER_RE.sub("", description).strip()


def _compose_issue_description(description: str, preferred_agent: str | None) -> str:
    base = (description or "").strip()
    if preferred_agent in {"claude", "codex", "deepseek"}:
        marker = f"<!-- agent_backend: {preferred_agent} -->"
        return f"{base}\n\n{marker}" if base else marker
    return base


def _normalize_linear_issue(issue: dict) -> dict:
    normalized = dict(issue or {})
    raw = normalized.get("description", "") or ""
    normalized["preferred_agent"] = _extract_issue_agent(raw)
    normalized["description"] = _strip_issue_metadata(raw)
    return normalized


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


def _linear_comment_body(*, title: str, prompt: str = "", output: str = "",
                         error: str = "", feedback: str = "") -> str:
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
        return [threading.Thread(target=self._polling_loop, args=(socketio,), daemon=True)]

    def _polling_loop(self, socketio) -> None:
        while True:
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
                from linear_client import LinearClient
                client = LinearClient(api_key, tracker.get("project_slug", ""))
                states = _linear_poll_states(tracker)
                issues = client.fetch_issues(states, team_id=tracker.get("team_id", "") or None)
                if not self.dispatches_warmed:
                    self._warm_dispatches()
                    self.dispatches_warmed = True
                new_cache: dict[str, dict] = {}
                in_progress_ids: set[str] = set()
                for issue in issues:
                    iid = issue["id"]
                    new_cache[iid] = _normalize_linear_issue(issue)
                    if _is_linear_in_progress(issue.get("state")):
                        in_progress_ids.add(iid)
                        if iid not in self.dispatched and not self._issue_is_running(iid):
                            threading.Thread(target=self._dispatch_issue, args=(issue, cfg, socketio), daemon=True).start()
                for iid in list(self.dispatched):
                    if iid not in in_progress_ids and not self._issue_is_running(iid):
                        self.dispatched.pop(iid, None)
                self.issues_cache.clear()
                self.issues_cache.update(new_cache)
                socketio.emit("linear_issues_updated", {"count": len(new_cache)})
            except Exception as e:
                logger.error("Linear polling error: %s", e)
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

    def _dispatch_issue(self, issue: dict, cfg: dict, socketio) -> None:
        import subprocess
        from app import _running_jobs, _running_procs, _python, RUNNER, ROOT, _load_registry, _ai_command, _agent_model, _parse_agent_output, _extract_skill_name, _strip_issue_metadata as _sim, _execute_deepseek_commands, _write_run_log, AI_RUN_TIMEOUT_S, _extract_real_errors
        issue_id = issue["id"]
        if issue_id in self.dispatched:
            return
        agent_cfg = cfg.get("agent", {})
        backend = issue.get("preferred_agent") or agent_cfg.get("backend", "claude")
        registry = _load_registry(backend)
        skill_list = "\n".join(f"- {n}: {e.get('purpose', '')[:100]}" for n, e in registry.items())
        routing_prompt = f"Given this issue, return only the skill name that best matches.\n\nIssue: {issue['identifier']} — {issue['title']}\n{(issue.get('description') or '')[:500]}\n\nAvailable skills:\n{skill_list}\n\nReturn exactly one skill name, nothing else."
        try:
            result = subprocess.run(_ai_command(backend, routing_prompt, output_format="text"), cwd=str(ROOT), capture_output=True, text=True, timeout=60)
            selected_skill = _extract_skill_name(result.stdout or "", registry)
        except Exception:
            selected_skill = "_prompt"
        run_id = str(uuid.uuid4())
        started_at = datetime.now(timezone.utc).isoformat()
        t0 = time.monotonic()
        prompt = f"{issue['identifier']}: {issue['title']}\n\n{_sim(issue.get('description') or '')}"
        self.dispatched[issue_id] = run_id
        _running_jobs[run_id] = {"run_id": run_id, "skill": selected_skill, "started_at": started_at, "prompt": prompt, "state": "running", "last_progress_at": time.monotonic(), "linear_issue_id": issue_id, "agent": backend}
        self.push_state(issue_id, "running")
        socketio.emit("run_state_change", {"run_id": run_id, "state": "running", "skill": selected_skill})
        entry = registry.get(selected_skill, {})
        cmd = [_python(), str(RUNNER), selected_skill] if entry.get("schedule_eligible") and entry.get("entrypoint") else _ai_command(backend, prompt, output_format="json")
        try:
            proc = subprocess.Popen(cmd, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            _running_procs[run_id] = proc
            stdout_b, stderr_b = proc.communicate(timeout=AI_RUN_TIMEOUT_S)
            dur = time.monotonic() - t0
            stdout_s = stdout_b.decode("utf-8", errors="replace").strip()
            stderr_s = stderr_b.decode("utf-8", errors="replace").strip()
            error_s = _extract_real_errors(stderr_s)
            output, it, ot, pm = _parse_agent_output(backend, stdout_s)
            if backend == "deepseek":
                output = _execute_deepseek_commands(output)
            _running_jobs.pop(run_id, None)
            _running_procs.pop(run_id, None)
            final_state = "review"
            _write_run_log(selected_skill, final_state, started_at, dur, prompt=prompt, output=output, error=error_s, run_id=run_id, linear_issue_id=issue_id, selected_skill=selected_skill, input_tokens=it, output_tokens=ot, agent=backend, model=pm or _agent_model(backend, cfg), task_id=run_id)
            self.push_state(issue_id, final_state)
            self.post_comment(issue_id, _linear_comment_body(title="AgenticOS Run", prompt=prompt, output=output, error=error_s))
            socketio.emit("run_state_change", {"run_id": run_id, "state": final_state, "skill": selected_skill})
            socketio.emit("run_logged", {"skill": selected_skill, "run_id": run_id})
        except subprocess.TimeoutExpired:
            dur = time.monotonic() - t0
            proc = _running_procs.pop(run_id, None)
            if proc: proc.kill()
            _running_jobs.pop(run_id, None)
            msg = f"Timed out after {AI_RUN_TIMEOUT_S}s"
            _write_run_log(selected_skill, "timeout", started_at, dur, prompt=prompt, error=msg, run_id=run_id, linear_issue_id=issue_id, agent=backend)
            self.post_comment(issue_id, _linear_comment_body(title="AgenticOS Run Timeout", prompt=prompt, error=msg))
            socketio.emit("run_state_change", {"run_id": run_id, "state": "timeout", "skill": selected_skill})
        except Exception as e:
            _running_procs.pop(run_id, None)
            _running_jobs.pop(run_id, None)
            _write_run_log(selected_skill, "error", started_at, 0.0, prompt=prompt, error=str(e), run_id=run_id, linear_issue_id=issue_id, agent=backend)
            self.post_comment(issue_id, _linear_comment_body(title="AgenticOS Run Error", prompt=prompt, error=str(e)))
            socketio.emit("run_state_change", {"run_id": run_id, "state": "error", "skill": selected_skill})

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
            if self._capability.get("type") == "linear":
                cfg = _load_workflow_config()
                tc = cfg.get("tracker", {})
                ak = _linear_api_key_from_cfg(tc)
                if ak and tc.get("kind") == "linear":
                    try:
                        from linear_client import LinearClient
                        cl = LinearClient(ak, tc.get("project_slug", ""))
                        live = cl.fetch_issues(_linear_poll_states(tc), team_id=tc.get("team_id", "") or None)
                        self.issues_cache.clear()
                        for issue in live:
                            self.issues_cache[issue["id"]] = _normalize_linear_issue(issue)
                    except Exception as e:
                        logger.warning("linear issues refresh failed: %s", e)
                return jsonify(list(self.issues_cache.values()))
            t = self.get_local_tracker()
            cfg = _load_workflow_config()
            return jsonify(t.fetch_issues(_linear_poll_states(cfg.get("tracker", {}))))

        @app.route("/api/linear/issues", methods=["POST"])
        def _issues_post():
            data = request.get_json(silent=True) or {}
            title = (data.get("title") or "").strip()
            if not title:
                return jsonify({"error": "title required"}), 400
            desc = (data.get("description") or "").strip()
            pa = (data.get("agent") or "").strip().lower()
            pa = pa if pa in {"claude", "codex", "deepseek"} else None
            desc = _compose_issue_description(desc, pa)
            if self._capability.get("type") == "local":
                t = self.get_local_tracker()
                issue = t.create_issue(title, desc, preferred_agent=pa)
                nd = dict(issue)
                self.issues_cache[issue["id"]] = nd
                if self._socketio:
                    self._socketio.emit("linear_issues_updated", {"count": len(self.issues_cache)})
                return jsonify({"ok": True, "issue": nd})
            cfg = _load_workflow_config()
            tc = cfg.get("tracker", {})
            ak = _linear_api_key_from_cfg(tc)
            tid = (data.get("team_id") or "").strip() or tc.get("team_id", "")
            if not ak:
                return jsonify({"error": "Linear not configured"}), 503
            if not tid:
                return jsonify({"error": "team_id required"}), 400
            try:
                from linear_client import LinearClient
                issue = LinearClient(ak, tc.get("project_slug", "")).create_issue(tid, title, desc)
                if not issue:
                    return jsonify({"error": "Linear create failed"}), 500
                n = _normalize_linear_issue(issue)
                self.issues_cache[issue["id"]] = n
                _post_linear_comment_raw(issue["id"], _issue_agent_comment_body(n.get("preferred_agent")), ak)
                if self._socketio:
                    self._socketio.emit("linear_issues_updated", {"count": len(self.issues_cache)})
                return jsonify({"ok": True, "issue": n})
            except Exception as e:
                return jsonify({"error": str(e)}), 500

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
                return jsonify(_normalize_linear_issue(issue)) if issue else (jsonify({"error": "not found"}), 404)
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @app.route("/api/linear/issues/<issue_id>", methods=["PATCH"])
        def _issues_patch(issue_id: str):
            data = request.get_json(silent=True) or {}
            cfg = _load_workflow_config()
            tc = cfg.get("tracker", {})
            if self._capability.get("type") == "local":
                issue = self.get_local_tracker().update_issue(issue_id, title=data.get("title"), description=data.get("description"), state_name=data.get("state_name"))
                if issue:
                    self.issues_cache[issue_id] = issue
                    return jsonify({"ok": True, "issue": issue})
                return jsonify({"error": "not found"}), 404
            ak = _linear_api_key_from_cfg(tc)
            if not ak:
                return jsonify({"error": "not configured"}), 400
            try:
                from linear_client import LinearClient
                cl = LinearClient(ak, tc.get("project_slug", ""))
                existing = cl.fetch_issue(issue_id)
                if not existing:
                    return jsonify({"error": "not found"}), 404
                if data.get("title") is not None or data.get("description") is not None:
                    cl.update_issue(issue_id, title=data.get("title"), description=data.get("description"))
                if data.get("state_name"):
                    cl.update_issue_state(issue_id, data["state_name"])
                issue = cl.fetch_issue(issue_id)
                if issue:
                    n = _normalize_linear_issue(issue)
                    self.issues_cache[issue_id] = n
                    if _is_linear_in_progress(n.get("state")) and not self._issue_is_running(issue_id):
                        self.dispatched.pop(issue_id, None)
                        threading.Thread(target=self._dispatch_issue, args=(issue, cfg, self._socketio), daemon=True).start()
                    return jsonify({"ok": True, "issue": n})
                return jsonify({"error": "update failed"}), 500
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @app.route("/api/linear/issues/<issue_id>/comment", methods=["POST"])
        def _issues_comment(issue_id: str):
            text = (request.get_json(silent=True) or {}).get("text", "").strip()
            if not text:
                return jsonify({"error": "text required"}), 400
            body = _linear_comment_body(title="AgenticOS Feedback", feedback=text)
            if self._capability.get("type") == "local":
                return jsonify({"ok": self.get_local_tracker().post_comment(issue_id, body)})
            cfg = _load_workflow_config()
            tc = cfg.get("tracker", {})
            ak = _linear_api_key_from_cfg(tc)
            ok = _post_linear_comment_raw(issue_id, body, ak)
            return (jsonify({"ok": ok}) if ok else (jsonify({"ok": False, "error": "comment failed"}), 500))

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

    # ── Bridge methods (called from app.py) ──────────────────────────────

    def push_state(self, issue_id: str, board_status: str) -> None:
        threading.Thread(target=self._push_sync, args=(issue_id, board_status), daemon=True).start()

    def _push_sync(self, issue_id: str, board_status: str) -> None:
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
            LinearClient(ak, tc["project_slug"]).update_issue_state(issue_id, ls)
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
