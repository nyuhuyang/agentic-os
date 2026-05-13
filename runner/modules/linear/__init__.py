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
                for iid in list(self.dispatched):
                    if iid not in in_progress_ids and not self._issue_is_running(iid):
                        self.dispatched.pop(iid, None)
                self.issues_cache.clear()
                self.issues_cache.update(new_cache)
                self._sync_cache_to_local()
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
            threading.Thread(
                target=self._linear_sync_patch,
                args=(issue_id, {"state_name": state_name}, cfg, None),
                daemon=True,
            ).start()

    def _dispatch_issue(self, issue: dict, cfg: dict, socketio, previous_board_status: str | None = None) -> None:
        import subprocess
        from app import _running_jobs, _running_procs, _python_path, RUNNER, ROOT, _load_registry, _ai_command, _agent_model, _parse_agent_output, _extract_skill_name, _execute_deepseek_commands, _write_run_log, AI_RUN_TIMEOUT_S, _extract_real_errors, _registry_exec_env, _ds_dispatch
        issue_id = issue["id"]
        if issue_id in self.dispatched:
            return

        agent_cfg = cfg.get("agent", {})
        backend = issue.get("preferred_agent") or agent_cfg.get("backend", "claude")

        if backend == "deepseek":
            run_id = str(uuid.uuid4())
            started_at = datetime.now(timezone.utc).isoformat()
            t0 = time.monotonic()
            prompt = f"{issue['identifier']}: {issue['title']}\n\n{_strip_issue_metadata(issue.get('description') or '')}"
            self.dispatched[issue_id] = run_id
            _running_jobs[run_id] = {
                "run_id": run_id,
                "skill": "_prompt",
                "started_at": started_at,
                "prompt": prompt,
                "state": "running",
                "last_progress_at": time.monotonic(),
                "linear_issue_id": issue_id,
                "agent": "deepseek",
            }
            self.push_state(issue_id, "running")
            socketio.emit("run_state_change", {"run_id": run_id, "state": "running", "skill": "_prompt"})
            try:
                result = _ds_dispatch(prompt, run_id)
                dur = time.monotonic() - t0
                _running_jobs.pop(run_id, None)
                _running_procs.pop(run_id, None)
                if result.get("ok"):
                    output = result.get("output", "")
                    output = _execute_deepseek_commands(output)
                    it = result.get("input_tokens")
                    ot = result.get("output_tokens")
                    pm = result.get("model")
                    _write_run_log(
                        "_prompt",
                        "review",
                        started_at,
                        dur,
                        prompt=prompt,
                        output=output,
                        run_id=run_id,
                        linear_issue_id=issue_id,
                        selected_skill="_prompt",
                        input_tokens=it,
                        output_tokens=ot,
                        agent="deepseek",
                        model=pm or _agent_model("deepseek", cfg),
                        task_id=run_id,
                    )
                    self.push_state(issue_id, "review")
                    self.post_comment(issue_id, _linear_comment_body(title="AgenticOS Run", prompt=prompt, output=output))
                    socketio.emit("run_state_change", {"run_id": run_id, "state": "review", "skill": "_prompt"})
                else:
                    err = result.get("error", "unknown deepseek error")
                    _write_run_log(
                        "_prompt",
                        "error",
                        started_at,
                        dur,
                        prompt=prompt,
                        error=err,
                        run_id=run_id,
                        linear_issue_id=issue_id,
                        agent="deepseek",
                    )
                    self._restore_issue_state(issue_id, previous_board_status or "todo", cfg)
                    self.post_comment(issue_id, _linear_comment_body(title="AgenticOS Run Error", prompt=prompt, error=err))
                    socketio.emit("run_state_change", {"run_id": run_id, "state": "error", "skill": "_prompt"})
                socketio.emit("run_logged", {"skill": "_prompt", "run_id": run_id})
            except Exception as e:
                _running_jobs.pop(run_id, None)
                _running_procs.pop(run_id, None)
                self._restore_issue_state(issue_id, previous_board_status or "todo", cfg)
                _write_run_log(
                    "_prompt",
                    "error",
                    started_at,
                    0.0,
                    prompt=prompt,
                    error=str(e),
                    run_id=run_id,
                    linear_issue_id=issue_id,
                    agent="deepseek",
                )
                self.post_comment(issue_id, _linear_comment_body(title="AgenticOS Run Error", prompt=prompt, error=str(e)))
                socketio.emit("run_state_change", {"run_id": run_id, "state": "error", "skill": "_prompt"})
                socketio.emit("run_logged", {"skill": "_prompt", "run_id": run_id})
            return

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
            try:
                result = subprocess.run(
                    _ai_command(backend, routing_prompt, output_format="text"),
                    cwd=str(ROOT),
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                selected_skill = _extract_skill_name(result.stdout or "", registry)
            except Exception:
                selected_skill = "_prompt"

            run_id = str(uuid.uuid4())
            started_at = datetime.now(timezone.utc).isoformat()
            t0 = time.monotonic()
            prompt = f"{issue['identifier']}: {issue['title']}\n\n{_strip_issue_metadata(issue.get('description') or '')}"
            self.dispatched[issue_id] = run_id
            _running_jobs[run_id] = {
                "run_id": run_id,
                "skill": selected_skill,
                "started_at": started_at,
                "prompt": prompt,
                "state": "running",
                "last_progress_at": time.monotonic(),
                "linear_issue_id": issue_id,
                "agent": backend,
            }
            self.push_state(issue_id, "running")
            socketio.emit("run_state_change", {"run_id": run_id, "state": "running", "skill": selected_skill})
            entry = registry.get(selected_skill, {})
            cmd = [_python_path(), str(RUNNER), selected_skill] if entry.get("schedule_eligible") and entry.get("entrypoint") else _ai_command(backend, prompt, output_format="json")
            try:
                proc = subprocess.Popen(
                    cmd,
                    cwd=str(ROOT),
                    env=_registry_exec_env(backend, registry),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                _running_procs[run_id] = proc
                stdout_b, stderr_b = proc.communicate(timeout=AI_RUN_TIMEOUT_S)
                dur = time.monotonic() - t0
                stdout_s = stdout_b.decode("utf-8", errors="replace").strip()
                stderr_s = stderr_b.decode("utf-8", errors="replace").strip()
                error_s = _extract_real_errors(stderr_s)
                output, it, ot, pm = _parse_agent_output(backend, stdout_s)
                _running_jobs.pop(run_id, None)
                _running_procs.pop(run_id, None)
                final_state = "review"
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
                )
                self.push_state(issue_id, final_state)
                self.post_comment(issue_id, _linear_comment_body(title="AgenticOS Run", prompt=prompt, output=output, error=error_s))
                socketio.emit("run_state_change", {"run_id": run_id, "state": final_state, "skill": selected_skill})
                socketio.emit("run_logged", {"skill": selected_skill, "run_id": run_id})
            except subprocess.TimeoutExpired:
                dur = time.monotonic() - t0
                proc = _running_procs.pop(run_id, None)
                if proc:
                    proc.kill()
                _running_jobs.pop(run_id, None)
                msg = f"Timed out after {AI_RUN_TIMEOUT_S}s"
                _write_run_log(selected_skill, "timeout", started_at, dur, prompt=prompt, error=msg, run_id=run_id, linear_issue_id=issue_id, agent=backend)
                self._restore_issue_state(issue_id, previous_board_status or "todo", cfg)
                self.post_comment(issue_id, _linear_comment_body(title="AgenticOS Run Timeout", prompt=prompt, error=msg))
                socketio.emit("run_state_change", {"run_id": run_id, "state": "timeout", "skill": selected_skill})
                socketio.emit("run_logged", {"skill": selected_skill, "run_id": run_id})
            except Exception as e:
                _running_procs.pop(run_id, None)
                _running_jobs.pop(run_id, None)
                _write_run_log(selected_skill, "error", started_at, 0.0, prompt=prompt, error=str(e), run_id=run_id, linear_issue_id=issue_id, agent=backend)
                self._restore_issue_state(issue_id, previous_board_status or "todo", cfg)
                self.post_comment(issue_id, _linear_comment_body(title="AgenticOS Run Error", prompt=prompt, error=str(e)))
                socketio.emit("run_state_change", {"run_id": run_id, "state": "error", "skill": selected_skill})
                socketio.emit("run_logged", {"skill": selected_skill, "run_id": run_id})
        except Exception as e:
            logger.exception("_dispatch_issue failed for %s: %s", issue_id, e)
            self._restore_issue_state(issue_id, previous_board_status or "todo", cfg)
            try:
                socketio.emit("run_state_change", {"run_id": str(uuid.uuid4()), "state": "error", "skill": "unknown"})
            except Exception:
                pass

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
                # Return cache immediately; avoid blocking on Linear API
                if not self.issues_cache:
                    try:
                        local = self.get_local_tracker()
                        for issue in local.fetch_issues():
                            self.issues_cache[issue["id"]] = issue
                    except Exception:
                        pass
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
            preferred_agent = (data.get("preferred_agent") or "").strip().lower() or None
            if preferred_agent not in {"claude", "codex", "deepseek"}:
                preferred_agent = None
            if self._capability.get("type") == "local":
                issue = self.get_local_tracker().update_issue(
                    issue_id,
                    title=data.get("title"),
                    description=data.get("description"),
                    state_name=data.get("state_name"),
                    preferred_agent=preferred_agent,
                )
                if issue:
                    self.issues_cache[issue_id] = issue
                    return jsonify({"ok": True, "issue": issue})
                return jsonify({"error": "not found"}), 404
            ak = _linear_api_key_from_cfg(tc)
            if not ak:
                return jsonify({"error": "not configured"}), 400

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
                if not self._issue_is_running(issue_id):
                    self.dispatched.pop(issue_id, None)
                    threading.Thread(target=self._dispatch_issue, args=(cached, cfg, self._socketio, previous_board_status), daemon=True).start()
                threading.Thread(target=self._linear_sync_patch, args=(issue_id, data, cfg, preferred_agent), daemon=True).start()
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
                    cl.update_issue_state(issue_id, data["state_name"])
                issue = cl.fetch_issue(issue_id)
                if issue:
                    n = _normalize_linear_issue(issue)
                    self.issues_cache[issue_id] = n
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
            for issue in live:
                self._localize_issue(issue)
                updated[issue["id"]] = _normalize_linear_issue(issue)
            self.issues_cache.clear()
            self.issues_cache.update(updated)
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
                    "created_at": issue.get("created_at", ""),
                    "updated_at": issue.get("updated_at", ""),
                }
                tasks_path = STATE_DIR / "tasks.json"
                tasks = {}
                if tasks_path.exists():
                    import json as _json
                    try:
                        tasks = _json.loads(tasks_path.read_text(encoding="utf-8"))
                    except Exception:
                        tasks = {}
                tasks[issue["id"]] = data
                tasks_path.parent.mkdir(parents=True, exist_ok=True)
                tmp = tasks_path.with_suffix(".tmp")
                import json as _json
                tmp.write_text(_json.dumps(tasks, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                tmp.replace(tasks_path)
        except Exception as e:
            logger.debug("localize_issue failed for %s: %s", issue.get("id", "?"), e)

    def _sync_cache_to_local(self) -> None:
        """Sync all cached issues to local tracker."""
        for issue in self.issues_cache.values():
            try:
                local = self.get_local_tracker()
                existing = local.fetch_issue(issue["id"])
                if existing:
                    local.update_issue(
                        issue["id"],
                        title=issue.get("title"),
                        description=issue.get("description"),
                        state_name=issue.get("state"),
                        preferred_agent=issue.get("preferred_agent"),
                    )
                else:
                    local.create_issue(
                        title=issue.get("title", ""),
                        description=issue.get("description", ""),
                        state_name=issue.get("state", "Todo"),
                        preferred_agent=issue.get("preferred_agent"),
                    )
            except Exception as e:
                logger.debug("sync_cache_to_local failed for %s: %s", issue.get("id", "?"), e)

    def _linear_sync_patch(self, issue_id: str, data: dict, cfg: dict, preferred_agent: str | None) -> None:
        """Async Linear sync for state/metadata updates (runs in daemon thread)."""
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
                self.issues_cache[issue_id] = _normalize_linear_issue(synced)
        except Exception as e:
            logger.error("Async Linear sync failed for %s: %s", issue_id, e)

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
