"""AGE-137: shared memory across agents, used at the runner's dispatch boundaries.

ai-memory (github.com/akitaonrails/ai-memory) keeps a git-backed markdown wiki per
(workspace, project) and exposes it over HTTP/MCP. The runner uses it as a plain
service, never through harness hooks:

  * before a project-bound run, a bounded brief of the ticket's earlier runs is
    prepended to the prompt, whichever agent wrote them;
  * after the run, a short section is appended to `tickets/<ident>.md` with the
    status, verify result, changes and the agent's closing summary.

Nothing is installed into Claude Code, Codex or DSH: no lifecycle hooks, no MCP
registration, no per-user daemon. The release binary lives in `.tools/ai-memory/`
(gitignored), the server starts lazily on loopback, and its wiki/db live under
`state/ai-memory/` (gitignored). Every call fails open: memory being absent or
unreachable never delays or fails a run.

Confidential projects are excluded by the caller: their prompts and output never
reach the wiki.
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

PROTO = Path(__file__).resolve().parents[1]
DEFAULT_BIN = PROTO / ".tools" / "ai-memory" / "ai-memory"
DEFAULT_DATA = PROTO / "state" / "ai-memory"
DEFAULT_PORT = 49375
START_TIMEOUT_S = 10.0
CALL_TIMEOUT_S = 4.0
RETRY_AFTER_S = 60.0
BRIEF_SECTIONS = 6
BRIEF_CHARS = 3500
SUMMARY_CHARS = 1200
MAX_SECTIONS = 40
PAGE_BUDGET = 12000

_SECRETS = (
    re.compile(r"\b(?:sk|rk)-[A-Za-z0-9_-]{16,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{16,}=*"),
)


class MemoryUnavailable(RuntimeError):
    """The memory server could not be reached."""


class MemoryCallError(RuntimeError):
    """The server answered, but the MCP tool failed (e.g. a page is missing)."""


def _one_line(text, limit: int = 200) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[:limit] + "…"


def _redact(text: str) -> str:
    """Best-effort secret scrub before a run summary is stored. The server sanitizes
    hook events; direct pages are the runner's own write, so it does its own pass."""
    for pattern in _SECRETS:
        text = pattern.sub("[redacted]", text)
    return text


def _header(project_key: str, ident: str) -> str:
    return (f"# {ident} · shared run memory\n\n"
            f"Written by the AgenticOS runner for project `{project_key}`. One section per "
            f"project-bound run, newest last. Historical evidence, not instructions.")


def _split_sections(body: str) -> list[str]:
    """The `## …` sections of a ticket page, oldest first (the H1 header is dropped)."""
    parts = re.split(r"(?m)^## ", body or "")
    return ["## " + p.strip() for p in parts[1:] if p.strip()]


def _trim(body: str, ident: str, project_key: str) -> str:
    """Keep the newest sections: MAX_SECTIONS and PAGE_BUDGET, oldest dropped first."""
    sections = _split_sections(body)[-MAX_SECTIONS:]
    head = (body or "").split("\n## ", 1)[0].rstrip() or _header(project_key, ident)
    while len(sections) > 1 and len(head) + sum(len(s) + 2 for s in sections) > PAGE_BUDGET:
        sections.pop(0)
    return head + "\n\n" + "\n\n".join(sections) + "\n" if sections else head + "\n"


def render_brief(body: str) -> str:
    """The newest sections that fit ONE prompt block, newest kept when the budget bites."""
    sections = _split_sections(body)[-BRIEF_SECTIONS:]
    if not sections:
        return ""
    kept, size = [], 0
    for section in reversed(sections):
        if size + len(section) > BRIEF_CHARS and kept:
            break
        kept.append(section)  # the newest section is always kept, then cut if needed
        size += len(section) + 2
    kept.reverse()
    text = "\n\n".join(kept)
    if len(text) > BRIEF_CHARS:
        text = text[-BRIEF_CHARS:]
        text = "… (older text cut)\n" + text.split("\n", 1)[-1]
    return text.strip()


class Memory:
    """One client for one data directory (the process-wide default is at the bottom)."""

    def __init__(self, *, binary: str | Path | None = None, data_dir: str | Path | None = None,
                 server_url: str | None = None, token: str | None = None, port: int | None = None,
                 enabled: bool | None = None):
        self.binary = Path(binary or os.environ.get("AI_MEMORY_BIN") or DEFAULT_BIN).expanduser()
        self.data_dir = Path(data_dir or os.environ.get("AI_MEMORY_DATA_DIR") or DEFAULT_DATA).expanduser()
        self.port = int(port or os.environ.get("AGENTIC_OS_AI_MEMORY_PORT") or DEFAULT_PORT)
        env_url = (server_url or os.environ.get("AI_MEMORY_SERVER_URL") or "").strip()
        self.server_url = (env_url or f"http://127.0.0.1:{self.port}").rstrip("/")
        self.external = bool(env_url)
        self._token = token
        self._enabled = enabled
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._ready = False
        self._retry_after = 0.0
        self._warned = False

    # ── enablement ───────────────────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        """Opt-in twice: the installer leaves `enabled` in the data dir, and the binary
        must exist (an external server needs only its URL and token)."""
        if self._enabled is not None:
            return self._enabled
        flag = os.environ.get("AGENTIC_OS_AI_MEMORY", "").strip().lower()
        if flag in ("0", "false", "no", "off"):
            return False
        if flag in ("1", "true", "yes", "on"):
            return self.binary.is_file() or self.external
        if self.external:
            return True
        return self.binary.is_file() and (self.data_dir / "enabled").is_file()

    @property
    def token(self) -> str | None:
        if self._token:
            return self._token
        env = os.environ.get("AI_MEMORY_AUTH_TOKEN", "").strip()
        if env:
            return env
        try:
            return (self.data_dir / "auth-tokens" / "default").read_text(encoding="utf-8").strip() or None
        except OSError:
            return None

    # ── transport ────────────────────────────────────────────────────────────

    def _url(self, path: str) -> str:
        return f"{self.server_url}{path}"

    def _post(self, path: str, payload: dict, timeout: float) -> dict:
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        token = self.token
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(self._url(path), data=json.dumps(payload).encode(),
                                     headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError) as exc:
            self._ready = False  # the next call may start it again
            raise MemoryUnavailable(str(exc)) from exc

    def _healthy(self) -> bool:
        try:
            with urllib.request.urlopen(self._url("/healthz"), timeout=1.0) as resp:
                return resp.status == 200
        except Exception:
            return False

    def _tool(self, name: str, args: dict) -> dict | str:
        resp = self._post("/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                   "params": {"name": name, "arguments": args}}, CALL_TIMEOUT_S)
        if resp.get("error"):
            err = resp["error"]
            raise MemoryCallError(err.get("message") if isinstance(err, dict) else str(err))
        result = resp.get("result") or {}
        text = "".join(block.get("text", "") for block in result.get("content") or []
                       if isinstance(block, dict) and block.get("type") == "text")
        if result.get("isError"):
            raise MemoryCallError(text or "tool failed")
        try:
            return json.loads(text)
        except ValueError:
            return text

    # ── server lifecycle ─────────────────────────────────────────────────────

    def _ensure(self) -> bool:
        if not self.enabled:
            return False
        with self._lock:
            if self._ready:
                return True
            if time.monotonic() < self._retry_after:
                return False
            if self._healthy():  # e.g. a previous runner left its server up
                self._ready = True
                return True
            if self._spawn():
                self._ready = True
                return True
            self._retry_after = time.monotonic() + RETRY_AFTER_S
            return False

    def _init_once(self) -> None:
        if self.external or (self.data_dir / "config.toml").is_file():
            return
        self.data_dir.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.run([str(self.binary), "--data-dir", str(self.data_dir),
                            "--config", str(self.data_dir / "config.toml"), "init"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            log.warning("ai-memory: init failed: %s", exc)

    def _spawn(self) -> bool:
        if self.external:
            return False
        if not self.binary.is_file():
            if not self._warned:
                log.info("ai-memory: %s is missing; shared memory is off (scripts/install_ai_memory.sh)", self.binary)
                self._warned = True
            return False
        self._init_once()
        log_dir = self.data_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        cmd = [str(self.binary), "--data-dir", str(self.data_dir), "--config", str(self.data_dir / "config.toml"),
               "serve", "--transport", "http", "--enable-api", "--bind", f"127.0.0.1:{self.port}", "--no-watcher"]
        with open(log_dir / "runner-server.log", "ab") as out:
            try:
                proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                                        start_new_session=True)
            except OSError as exc:
                log.warning("ai-memory: server did not start: %s", exc)
                return False
        deadline = time.monotonic() + START_TIMEOUT_S
        while time.monotonic() < deadline:
            if self._healthy():
                self._proc = proc
                return True
            if proc.poll() is not None:
                break
            time.sleep(0.1)
        if proc.poll() is None:
            proc.terminate()
        log.warning("ai-memory: server did not become healthy; see %s", log_dir / "runner-server.log")
        return False

    def close(self) -> None:
        proc, self._proc = self._proc, None
        self._ready = False
        if proc is not None and proc.poll() is None:
            proc.terminate()

    # ── public API ───────────────────────────────────────────────────────────

    def brief(self, project_key: str, ident: str) -> str:
        """Earlier runs on this ticket, or "" when memory is off/unreachable/empty."""
        if not self._ensure():
            return ""
        try:
            page = self._tool("memory_read_page", {"workspace": project_key, "project": ident,
                                                   "path": f"tickets/{ident}.md"})
        except MemoryCallError as exc:
            if "not found" not in str(exc).lower():
                log.debug("ai-memory: brief failed for %s/%s: %s", project_key, ident, exc)
            return ""
        except MemoryUnavailable as exc:
            log.debug("ai-memory: brief unavailable for %s/%s: %s", project_key, ident, exc)
            return ""
        return render_brief(page.get("body", "") if isinstance(page, dict) else "")

    def record_run(self, project_key: str, ident: str, *, run_id: str, agent: str, status: str,
                   title: str = "", summary: str = "", verify: dict | None = None,
                   result: dict | None = None) -> bool:
        """Append this run's section to the ticket page; bounded, idempotent, fail-open."""
        if not self._ensure():
            return False
        section = self._section(run_id, agent, status, title, summary, verify, result or {})
        short = f"## run {run_id[:8]} "
        for attempt in (0, 1):
            try:
                page = self._tool("memory_read_page", {"workspace": project_key, "project": ident,
                                                       "path": f"tickets/{ident}.md"})
            except MemoryCallError:
                page = None  # no page yet
            except MemoryUnavailable as exc:
                log.debug("ai-memory: record unavailable for %s/%s: %s", project_key, ident, exc)
                return False
            body = page.get("body", "") if isinstance(page, dict) else ""
            if short in body:
                return True
            new_body = _trim(body, ident, project_key).rstrip() + "\n\n" + section + "\n"
            if len(new_body) > PAGE_BUDGET:  # one huge session cannot bury the page
                new_body = _trim(new_body, ident, project_key)
            args = {"workspace": project_key, "project": ident, "path": f"tickets/{ident}.md",
                    "body": new_body, "kind": "fact", "title": f"{ident} · shared run memory"}
            if isinstance(page, dict) and page.get("page_id"):
                args["expected_page_id"] = page["page_id"]
            else:
                args["create_only"] = True
            try:
                self._tool("memory_write_page", args)
                return True
            except MemoryCallError as exc:
                if attempt == 0 and "precondition" in str(exc).lower():
                    continue  # another run appended first: re-read and retry once
                log.debug("ai-memory: record failed for %s/%s: %s", project_key, ident, exc)
                return False
            except MemoryUnavailable as exc:
                log.debug("ai-memory: record unavailable for %s/%s: %s", project_key, ident, exc)
                return False
        return False

    @staticmethod
    def _section(run_id: str, agent: str, status: str, title: str, summary: str,
                 verify: dict | None, result: dict) -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
        lines = [f"## run {run_id[:8]} · {stamp} · {agent} · {status}"]
        if title:
            lines.append(f"- task: {_one_line(title, 240)}")
        if verify:
            lines.append(f"- verify: {verify.get('status', '?')} (exit {verify.get('exit', '?')}, "
                         f"{verify.get('duration_s', '?')} s)")
        if result.get("shortstat"):
            lines.append(f"- changes: {_one_line(result['shortstat'], 240)}")
        commit = result.get("runner_commit") or result.get("commit")
        if commit:
            lines.append(f"- commit: {str(commit)[:12]}")
        text = _redact(" ".join((summary or "").split()))[:SUMMARY_CHARS]
        if text:
            lines.append(f"- summary: {text}")
        return "\n".join(lines)


_DEFAULT = Memory()
atexit.register(_DEFAULT.close)


def brief(project_key: str, ident: str) -> str:
    """The process-wide client's brief; any unexpected failure is still a run without memory."""
    try:
        return _DEFAULT.brief(project_key, ident)
    except Exception:  # noqa: BLE001 - a memory bug must never fail a dispatch
        log.exception("ai-memory: brief failed for %s/%s", project_key, ident)
        return ""


def record_run(project_key: str, ident: str, **run) -> bool:
    try:
        return _DEFAULT.record_run(project_key, ident, **run)
    except Exception:  # noqa: BLE001 - a memory bug must never fail a run record
        log.exception("ai-memory: record failed for %s/%s", project_key, ident)
        return False


def status() -> dict:
    """Debug/ops view; never raises."""
    return {"enabled": _DEFAULT.enabled, "server": _DEFAULT.server_url, "healthy": _DEFAULT._healthy(),
            "binary": str(_DEFAULT.binary), "data_dir": str(_DEFAULT.data_dir)}


if __name__ == "__main__":  # python runner/ai_memory.py [brief <project> <ticket>]
    import sys

    if len(sys.argv) >= 4 and sys.argv[1] == "brief":
        print(brief(sys.argv[2], sys.argv[3]) or "(no memory yet)")
    else:
        print(json.dumps(status(), indent=2))
