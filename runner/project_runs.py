"""Project-bound runs (plan Phase 2): binding, sandboxed argv, live run events, post-run checks.

A Linear ticket labelled `project:<key>` runs in its own worktree of that project
(runner/projects.py). This module holds the parts that do not need Flask: the
per-agent command for a binding, the dispatch prompt, the confidential comment
template, the bounded live-event ring and the checks that run after the agent.
"""

from __future__ import annotations

import collections
import json
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

import projects

LABEL_PREFIX = "project:"
# Spike (g), 2026-10-14: sandbox-exec confines verify and runner git. If it ever fails,
# set False: confidential dispatch is then refused outright (Decision 9 / MPD-R1).
CONFIDENTIAL_SANDBOX_VERIFIED = True
PROJECT_AGENTS = ("claude", "codex", "dsh")
RING_BYTES = 256 * 1024


class ProjectRunError(Exception):
    """A project launch refused before (or instead of) running an agent."""


# ── binding ──────────────────────────────────────────────────────────────────

def project_key_from_labels(labels) -> str | None:
    for label in labels or []:
        name = label.get("name") if isinstance(label, dict) else label
        if isinstance(name, str) and name.lower().startswith(LABEL_PREFIX):
            return name[len(LABEL_PREFIX):].strip() or None
    return None


def binding_fields(project: projects.Project, ident: str, wt_info: dict) -> dict:
    """The additive run-record fields that persist a ticket's binding (Decision 1)."""
    return {
        "project_key": project.key, "issue_identifier": ident, "worktree": wt_info["worktree"],
        "branch": wt_info["branch"], "base_sha": wt_info["base_sha"],
    }


def common_dir(project: projects.Project) -> Path:
    out = projects._git(project.path, "rev-parse", "--git-common-dir").stdout.strip()
    return (project.path / out).resolve()


# ── agent command (Decision 9) ───────────────────────────────────────────────

def claude_confidential_settings(common: Path) -> str:
    return json.dumps({
        "sandbox": {
            "enabled": True, "failIfUnavailable": True, "allowUnsandboxedCommands": False,
            "autoAllowBashIfSandboxed": True, "excludedCommands": [],
            "network": {"allowedDomains": [], "strictAllowlist": True},
            "filesystem": {"allowWrite": [str(common)]},
        },
        "permissions": {"deny": ["Read(**/.env*)", "Read(~/.ssh/**)"]},
    })


def is_sandboxed_codex(agent: str, project: projects.Project) -> bool:
    """Codex under workspace-write cannot write .git (spike), so the runner commits for it."""
    return agent == "codex"  # confidential: workspace-write; otherwise --approve-for-me


def agent_cli(agent: str, project: projects.Project, claude_bin: str, dsh_prefix: Callable[[], list[str]]) -> list[str]:
    """Headless CLI prefix for a project-bound run. Raises ProjectRunError for a backend the
    binding does not allow."""
    if agent not in PROJECT_AGENTS:
        raise ProjectRunError(f"backend {agent!r} cannot run project tickets (allowed: {', '.join(PROJECT_AGENTS)})")
    common = str(common_dir(project))
    if project.confidential:
        if not CONFIDENTIAL_SANDBOX_VERIFIED:
            raise ProjectRunError("confidential dispatch is disabled: the verify/git sandbox failed its spike")
        if agent == "dsh":
            raise ProjectRunError("dsh is not allowed for confidential projects (its sandbox leaves shell network open)")
        if agent == "codex":
            return ["codex", "exec", "--json", "--sandbox", "workspace-write", "--add-dir", common,
                    "-c", 'approval_policy="never"', "-c", "sandbox_workspace_write.network_access=false",
                    "-c", "sandbox_workspace_write.writable_roots=[]"]
        return [claude_bin, "-p", "--verbose", "--permission-mode", "acceptEdits", "--permission-prompts", "none",
                "--add-dir", common, "--setting-sources", "", "--settings", claude_confidential_settings(Path(common))]
    if agent == "codex":
        return ["codex", "exec", "--json", "--approve-for-me", "--add-dir", common]
    if agent == "dsh":
        return dsh_prefix()
    return [claude_bin, "-p", "--verbose", "--permission-mode", "bypassPermissions"]


def project_prompt(prompt: str, project: projects.Project, binding: dict, agent: str) -> str:
    rules = [f"You are working in a git worktree of project '{project.key}' on branch {binding['branch']}."]
    if is_sandboxed_codex(agent, project):
        rules.append("Leave your changes uncommitted; the runner commits them on this branch after you finish.")
    else:
        rules.append("Commit your work on this branch. Do not switch branches.")
    if project.no_push:
        rules.append("Do not push, deploy or publish anything.")
    rules.append("Never edit files outside this worktree.")
    if not project.verify:
        rules.append("No check command is configured for this project: find and run its own tests "
                     "before you finish, and report the result.")
    return "\n".join(rules) + "\n\n" + prompt


# ── tracker comments (Decision 4) ────────────────────────────────────────────

def tracker_comment(binding: dict | None, kind: str, *, run_id: str, status: str = "",
                    verify: dict | None = None, shortstat: str = "", fallback: Callable[[], str]) -> str | None:
    """The one gate for automatic tracker comments.

    Non-project and non-confidential bindings keep today's body (`fallback()`). For a
    confidential binding, or a project binding whose confidentiality is unknown (registry
    lookup failed, I5-02), the body is a fixed template from trusted structured fields only;
    feedback comments are not posted at all (None)."""
    conf = (binding or {}).get("confidential", None if (binding or {}).get("project_key") else False)
    if not conf and conf is not None:  # explicitly not confidential, or no project binding at all
        return fallback()
    if kind == "feedback":
        return None
    lines = [f"AgenticOS {kind}", f"status: {status or 'unknown'}"]
    if verify:
        lines.append(f"verify: {verify.get('status', '?')} (exit {verify.get('exit')}, {verify.get('duration_s')} s)")
    if shortstat:
        lines.append(f"changes: {shortstat}")
    if status in ("error", "timeout"):
        lines.append(f"see local run {run_id}")
    return "\n".join(lines)


# ── live run events (MPD-31) ─────────────────────────────────────────────────

class EventRing:
    """Bounded in-memory event lines for one run (shown by Phase 3 run tabs)."""

    def __init__(self, max_bytes: int = RING_BYTES):
        self._lines: collections.deque = collections.deque()
        self._bytes, self._max = 0, max_bytes
        self._lock = threading.Lock()

    def append(self, line: str) -> None:
        with self._lock:
            self._lines.append(line)
            self._bytes += len(line)
            while self._bytes > self._max and self._lines:
                self._bytes -= len(self._lines.popleft())

    def snapshot(self) -> list[str]:
        with self._lock:
            return list(self._lines)


RUN_EVENTS: dict[str, EventRing] = {}


def normalize_event(agent: str, line: str) -> str | None:
    """One structured stdout line -> one display line (assistant text, [tool] …, [result] …)."""
    try:
        ev = json.loads(line)
    except ValueError:
        return line if agent == "dsh" else None
    if not isinstance(ev, dict):
        return None
    t = ev.get("type")
    if agent == "claude":
        if t == "assistant":
            out = []
            for block in (ev.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "text":
                    out.append(block.get("text", ""))
                elif isinstance(block, dict) and block.get("type") == "tool_use":
                    out.append(f"[tool] {block.get('name')} {json.dumps(block.get('input'))[:80]}")
            return "\n".join(out) or None
        if t == "result":
            return f"[result] {'error' if ev.get('is_error') else 'ok'}"
        return None
    if agent == "codex":
        item = ev.get("item") or {}
        if t == "item.completed" and item.get("type") == "agent_message":
            return item.get("text")
        if t == "item.completed" and item.get("type") == "command_execution":
            return f"[tool] shell {str(item.get('command'))[:80]}"
        if t == "turn.completed":
            return "[result] ok"
        if t in ("turn.failed", "error"):
            return "[result] error"
        return None
    if t == "final":
        return ev.get("text")
    if t == "tool_call":
        return f"[tool] {ev.get('tool')} {json.dumps(ev.get('input'))[:80]}"
    if t == "tool_result":
        return f"[result] {ev.get('status')}"
    return None


def run_agent(argv: list[str], cwd: str, env: dict, run_id: str, agent: str, timeout: float,
              emit: Callable[[str, dict], None], on_start: Callable[[subprocess.Popen], None] | None = None
              ) -> tuple[list[str], str, int | None, bool]:
    """Run one agent in its own process group, streaming stdout line by line.

    Every stdout line is kept for completion parsing; each structured event also goes to
    the run's EventRing and out as `run_event`. The whole process group is killed and
    reaped on every exit path. Returns (stdout_lines, stderr, returncode, timed_out)."""
    ring = RUN_EVENTS.setdefault(run_id, EventRing())
    proc = projects.spawn(argv, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          stdin=subprocess.DEVNULL)
    if on_start:
        on_start(proc)
    lines: list[str] = []
    err: list[bytes] = []

    def read_out():
        for raw in proc.stdout:
            line = raw.decode("utf-8", "replace").rstrip("\n")
            if not line:
                continue
            lines.append(line)
            shown = normalize_event(agent, line)
            if shown:
                ring.append(shown)
                emit("run_event", {"run_id": run_id, "line": shown})

    readers = [threading.Thread(target=read_out, daemon=True),
               threading.Thread(target=lambda: err.append(proc.stderr.read() or b""), daemon=True)]
    for r in readers:
        r.start()
    timed_out = False
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
    finally:
        projects.reap(proc)  # background servers/watchers the agent left behind
    for r in readers:
        r.join(timeout=5)
    return lines, b"".join(err).decode("utf-8", "replace").strip(), proc.returncode, timed_out


# ── after the agent ──────────────────────────────────────────────────────────

def post_run(project: projects.Project, binding: dict, agent: str, title: str,
             fingerprint_before: str, exclude: set[str], on_start=None,
             stopped: Callable[[], bool] = lambda: False) -> dict:
    """Runner commit (sandboxed Codex, branch checked first), uncommitted check, verify, then
    binding + seed-history checks after verify (it may run git too), shortstat, and the closing
    fingerprint last, also on failure (I4-05, I5-10/11/14). `on_start` gets the verify process
    so a cancel can kill it; `stopped()` skips verify after a cancel. Returns additive
    run-record fields and the badge."""
    wt = Path(binding["worktree"])
    result: dict = {}
    seeds, dirty, verify = [], [], None
    try:
        if is_sandboxed_codex(agent, project):
            result["runner_commit"] = projects.runner_commit(project, wt, f"{binding['issue_identifier']}: {title}"[:200])
        dirty = projects.uncommitted(project, wt)
        result["uncommitted"] = dirty[:50]
        if not stopped():  # a cancel skips verify, never the closing check and badge (I8-05)
            if project.verify:  # optional: without it the agent ran the project's own tests
                verify = projects.run_verify(project, wt, base=binding["base_sha"], on_start=on_start)
                result["verify"] = {k: verify[k] for k in ("status", "exit", "duration_s")}
                result["verify_tail"] = verify["tail"]  # local run record only, never a tracker comment
            projects.load_binding(project, binding["issue_identifier"])  # still on agent/<id> after verify
            dirty = sorted(set(dirty) | set(projects.uncommitted(project, wt)))  # verify may dirty it too (I6-09)
            result["uncommitted"] = dirty[:50]
            seeds = projects.committed_seeds(project, wt, binding["base_sha"])
            result["seed_committed"] = seeds
            result["shortstat"] = projects._git(wt, "diff", "--shortstat", binding["base_sha"], "HEAD",
                                                confine=projects.confine_for(project, wt)).stdout.strip()
    except projects.ProjectError as exc:  # e.g. the branch was switched: refuse, keep the fingerprint
        result["post_run_error"] = str(exc)
    finally:
        result.update(closing_check(project, exclude, fingerprint_before))
        changed = result["main_checkout_changed"]
    if seeds:
        badge = "seed committed"
    elif changed is None:
        badge = "main checkout unchecked"
    elif changed:
        badge = "main checkout changed"
    elif "post_run_error" in result:
        badge = "error"
    elif verify is None and stopped():
        badge = None  # cancelled before verify: the status says it
    elif dirty:
        badge = "uncommitted changes"  # verify (if any) ran on files the branch does not hold
    elif verify is None:
        badge = "no check" if not project.verify else "error"
    else:
        badge = verify["status"]
    if badge:
        result["verify_badge"] = badge
    return result


def closing_check(project: projects.Project, exclude: set[str], before: str) -> dict:
    """The closing main-checkout fingerprint. A snapshot that fails is recorded, never lost:
    main_checkout_changed None + the reason (fail closed, I7-07)."""
    try:
        return {"main_checkout_changed": projects.fingerprint(project, exclude=exclude) != before}
    except Exception as exc:  # ProjectError, or OSError while stat-ing a vanished file
        return {"main_checkout_changed": None, "closing_check_error": str(exc)[:500]}


def bookkeeping_paths(project: projects.Project, runner_dirs: list[Path]) -> set[str]:
    """Runner-written directories inside this project's checkout (only when the runner's own
    checkout is registered), excluded from its fingerprint as "dir/" prefixes."""
    root = project.path.resolve()
    out = set()
    for p in runner_dirs:
        p = Path(os.path.realpath(p))
        if p.is_relative_to(root) and p != root:
            out.add(p.relative_to(root).as_posix().rstrip("/") + "/")
    return out
