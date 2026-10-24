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

import http.client
import json
import logging
import os
import re
import socket
import subprocess
import threading
import time
import zlib
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

log = logging.getLogger(__name__)

PROTO = Path(__file__).resolve().parents[1]
DEFAULT_BIN = PROTO / ".tools" / "ai-memory" / "ai-memory"
DEFAULT_DATA = PROTO / "state" / "ai-memory"
DEFAULT_PORT = 49375
START_TIMEOUT_S = 3.0  # cold start stays inside one memory call's budget
HEALTH_TIMEOUT_S = 1.0
LOCK_TIMEOUT_S = 1.0
CALL_TIMEOUT_S = 4.0
RETRY_AFTER_S = 60.0
RESPONSE_BYTES = 2_000_000
MAX_INFLIGHT = 4
RUN_INDEX = 100  # full run ids kept in the page header, beyond the 40 retained sections
BRIEF_SECTIONS = 6
BRIEF_BYTES = 3500
SUMMARY_BYTES = 1200
MAX_SECTIONS = 40
PAGE_BYTES = 12000

_TOKEN_RE = re.compile(r"^[A-Za-z0-9\-._~+/]+=*$")

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


def _port_for(data_dir: Path) -> int:
    """A per-checkout port: two checkouts have separate data dirs and tokens, so they must not
    reuse each other's service just because both defaulted to one port."""
    return DEFAULT_PORT + zlib.crc32(str(data_dir).encode("utf-8")) % 200


def _clip(text: str, limit: int) -> str:
    """Cut to a UTF-8 byte budget without splitting a character (the budgets are bytes, not
    Python characters: a Chinese summary would otherwise overrun 1.2 KB by ~3x)."""
    raw = (text or "").encode("utf-8")
    if len(raw) <= limit:
        return text or ""
    if limit <= 4:
        return ""
    return raw[:limit - 3].decode("utf-8", "ignore") + "…"


def _one_line(text, limit: int = 200) -> str:
    return _clip(" ".join(str(text or "").split()), limit)


def _redact(text: str, secret: str | None = None) -> str:
    """Best-effort secret scrub before a title/summary is stored. The server sanitizes hook
    events; direct pages are the runner's own write, so it does its own pass. `secret` is the
    configured bearer token, which has no recognizable prefix of its own."""
    text = text or ""
    if secret:
        text = text.replace(secret, "[redacted]")
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


_INDEX_RE = re.compile(r"(?m)^<!-- agenticos-runs: (.*?) -->$")


def _indexed_runs(body: str) -> list[str]:
    match = _INDEX_RE.search(body or "")
    return match.group(1).split() if match else []


def _section_run_id(section: str) -> str | None:
    lines = section.split("\n")
    if len(lines) > 1 and lines[0].startswith("## run "):
        match = re.fullmatch(r"<!-- agenticos-run: (.+?) -->", lines[1].strip())
        return match.group(1) if match else None
    return None


def _with_indexed_runs(body: str, run_ids: list[str]) -> str:
    """Put the id index in the page header, before the first section. A pre-index page may carry
    it inside a section (an older version did); move it out so trimming cannot evict it."""
    line = f"<!-- agenticos-runs: {' '.join(run_ids)} -->"
    body = _INDEX_RE.sub("", body or "").strip("\n")
    head, sep, rest = body.partition("\n## ")
    return head.rstrip() + "\n" + line + ("\n\n## " + rest if sep else "")


def _has_run(body: str, run_id: str) -> bool:
    """True only when a section's metadata line is this exact full run id. Matching anywhere in
    the body would let one summary suppress a later run that it happens to name."""
    return any(_section_run_id(section) == run_id for section in _split_sections(body))


def _trim(body: str, ident: str, project_key: str) -> str:
    """Keep the newest sections: MAX_SECTIONS and PAGE_BYTES, oldest dropped first."""
    sections = _split_sections(body)[-MAX_SECTIONS:]
    head = (body or "").split("\n## ", 1)[0].rstrip() or _header(project_key, ident)
    def size() -> int:
        return len((head + "\n\n" + "\n\n".join(sections) + "\n").encode("utf-8"))
    while len(sections) > 1 and size() > PAGE_BYTES:
        sections.pop(0)
    text = head + "\n\n" + "\n\n".join(sections) + "\n" if sections else head + "\n"
    return text if len(text.encode("utf-8")) <= PAGE_BYTES else _clip(text, PAGE_BYTES)


def render_brief(body: str) -> str:
    """The newest sections that fit ONE prompt block, newest kept when the budget bites."""
    sections = _split_sections(body)[-BRIEF_SECTIONS:]
    if not sections:
        return ""
    kept, size = [], 0
    for section in reversed(sections):
        n = len(section.encode("utf-8")) + 2
        if size + n > BRIEF_BYTES and kept:
            break
        kept.append(section)  # the newest section is always kept, then cut if needed
        size += n
    kept.reverse()
    text = "\n\n".join(kept)
    if len(text.encode("utf-8")) > BRIEF_BYTES:
        marker = "… (older text cut)\n"
        text = marker + _clip(text, BRIEF_BYTES - len(marker.encode("utf-8")))
    return text.strip()


class Memory:
    """One client for one data directory (the process-wide default is at the bottom)."""

    def __init__(self, *, binary: str | Path | None = None, data_dir: str | Path | None = None,
                 server_url: str | None = None, token: str | None = None, port: int | None = None,
                 enabled: bool | None = None):
        self.binary = Path(binary or os.environ.get("AI_MEMORY_BIN") or DEFAULT_BIN).expanduser()
        self.data_dir = Path(data_dir or os.environ.get("AI_MEMORY_DATA_DIR") or DEFAULT_DATA).expanduser()
        try:  # a bad env value must not stop the dashboard from importing this module
            self.port = int(port or os.environ.get("AGENTIC_OS_AI_MEMORY_PORT") or _port_for(self.data_dir))
        except (TypeError, ValueError):
            log.warning("ai-memory: invalid AGENTIC_OS_AI_MEMORY_PORT; using %s", DEFAULT_PORT)
            self.port = DEFAULT_PORT
        env_url = (server_url or os.environ.get("AI_MEMORY_SERVER_URL") or "").strip()
        self.server_url = (env_url or f"http://127.0.0.1:{self.port}").rstrip("/")
        self.external = bool(env_url)
        self._token = token
        self._enabled = enabled
        self._lock = threading.Lock()
        self._inflight = 0
        self._inflight_lock = threading.Lock()
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
            return self._valid_token(self._token)
        env = os.environ.get("AI_MEMORY_AUTH_TOKEN", "").strip()
        if env:
            return self._valid_token(env)
        if self.external:
            return None  # never send this checkout's bearer token to another host
        try:
            return self._valid_token((self.data_dir / "auth-tokens" / "default").read_text(encoding="utf-8"))
        except OSError:
            return None

    @staticmethod
    def _valid_token(value: str | None) -> str | None:
        """Reject a token the HTTP client would reject anyway; its error message embeds the whole
        header value, so an invalid token must never reach the transport or a log."""
        value = (value or "").strip()
        if not value:
            return None
        if not _TOKEN_RE.fullmatch(value):
            log.warning("ai-memory: ignoring an invalid auth token (whitespace or control characters)")
            return None
        return value

    # ── transport ────────────────────────────────────────────────────────────

    def _url(self, path: str) -> str:
        return f"{self.server_url}{path}"

    def _request(self, method: str, path: str, body: bytes | None, timeout: float,
                 headers: dict | None = None, secret: str | None = None) -> tuple[int, bytes]:
        """One bounded HTTP request: absolute deadline, cancellable connect/read, closed socket.

        A socket timeout bounds inactivity, not total time; a server can drip a byte per interval
        forever. The request runs in a daemon worker the caller joins for exactly `timeout`. On
        expiry a cancel flag is set, the socket is shut down (waking a blocked connect or read),
        the connection is closed and `MemoryUnavailable` is raised. A worker that resumes after a
        stalled resolver sees the flag and sends nothing. At most MAX_INFLIGHT requests exist.
        """
        base = urlsplit(self.server_url)
        target = (base.path.rstrip("/") + path) or "/"
        conn_cls = http.client.HTTPSConnection if base.scheme == "https" else http.client.HTTPConnection
        deadline = time.monotonic() + timeout
        conn = None
        box: dict = {}
        sock_box: dict = {}
        resp_box: dict = {}
        cancel = threading.Event()

        def call() -> None:
            nonlocal conn
            resp = None
            try:
                conn = conn_cls(base.hostname, base.port, timeout=timeout)
                conn.connect()
                conn.auto_open = 0  # a cancelled caller may close the socket before request()
                sock_box["sock"] = conn.sock
                if cancel.is_set():
                    return
                conn.request(method, target, body=body, headers=headers or {})
                if cancel.is_set():
                    return
                resp = conn.getresponse()
                resp_box["resp"] = resp
                box["status"] = resp.status
                box["data"] = resp.read(RESPONSE_BYTES + 1)
            except BaseException as exc:  # noqa: BLE001 - relayed below; never die silently
                if not cancel.is_set():
                    box["error"] = exc
            finally:
                if resp is not None:
                    try:
                        resp.close()
                    except OSError:
                        pass
                if conn is not None:
                    try:
                        conn.close()
                    except OSError:
                        pass
                with self._inflight_lock:
                    self._inflight -= 1

        with self._inflight_lock:
            if self._inflight >= MAX_INFLIGHT:
                raise MemoryUnavailable("too many outstanding memory requests")
            self._inflight += 1
        worker = threading.Thread(target=call, name="ai-memory-http", daemon=True)
        try:
            worker.start()
        except BaseException:
            with self._inflight_lock:
                self._inflight -= 1
            raise
        worker.join(max(0.0, deadline - time.monotonic()))
        if worker.is_alive():
            cancel.set()
            sock = sock_box.get("sock") or getattr(
                getattr(getattr(resp_box.get("resp"), "fp", None), "raw", None), "_sock", None)
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            if conn is not None:
                try:
                    conn.close()
                except OSError:
                    pass
            self._ready = False
            raise MemoryUnavailable(f"no response within {timeout}s")
        error = box.get("error")
        if error is not None:
            self._ready = False  # the next call may start the server again
            text = str(error)
            if secret and secret in text:  # never carry the bearer token into a log or traceback
                raise MemoryUnavailable(text.replace(secret, "[redacted]")) from None
            raise MemoryUnavailable(text) from error
        return box["status"], box["data"]

    def _post(self, path: str, payload: dict, timeout: float) -> dict:
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        token = self.token
        if token:
            headers["Authorization"] = f"Bearer {token}"
        status, data = self._request("POST", path, json.dumps(payload).encode(), timeout, headers, secret=token)
        if status in (401, 403):
            # A different checkout's server is on our port (or its token changed): stop retrying
            # it. With a per-checkout port this is a genuine conflict, not a transient failure.
            self._ready = False
            self._retry_after = time.monotonic() + RETRY_AFTER_S
            raise MemoryUnavailable(f"HTTP {status} from {path}: is another ai-memory using port {self.port}?")
        if not 200 <= status < 300:
            raise MemoryUnavailable(f"HTTP {status} from {path}")
        if len(data) > RESPONSE_BYTES:
            raise MemoryUnavailable("memory response is too large")
        try:
            return json.loads(data.decode("utf-8"))
        except ValueError as exc:
            raise MemoryUnavailable(str(exc)) from exc

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

    def _healthy(self, timeout: float = HEALTH_TIMEOUT_S) -> bool:
        try:
            status, _ = self._request("GET", "/healthz", None, timeout)
        except MemoryUnavailable:
            return False
        return status == 200

    def _ensure(self) -> bool:
        if not self.enabled:
            return False
        if self._ready:
            return True
        if time.monotonic() < self._retry_after:
            return False
        deadline = time.monotonic() + START_TIMEOUT_S
        if self._healthy(max(0.1, min(HEALTH_TIMEOUT_S, deadline - time.monotonic()))):
            self._ready = True
            return True
        # Never queue behind a slow starter longer than one lifecycle budget: a concurrent
        # caller fails open and the next dispatch reuses the server it started.
        if not self._lock.acquire(timeout=max(0.1, min(LOCK_TIMEOUT_S, deadline - time.monotonic()))):
            return False
        try:
            if self._ready:
                return True
            if time.monotonic() < self._retry_after:
                return False
            if self._spawn(deadline):
                self._ready = True
                return True
            self._retry_after = time.monotonic() + RETRY_AFTER_S
            return False
        finally:
            self._lock.release()

    def _spawn(self, deadline: float | None = None) -> bool:
        if self.external:
            return False
        if not self.binary.is_file():
            if not self._warned:
                log.info("ai-memory: %s is missing; shared memory is off (scripts/install_ai_memory.sh)", self.binary)
                self._warned = True
            return False
        if not (self.data_dir / "config.toml").is_file():
            # The installer always initialises this. Do not pay a 30 s `init` inside dispatch.
            if not self._warned:
                log.info("ai-memory: %s is not initialised; run scripts/install_ai_memory.sh", self.data_dir)
                self._warned = True
            return False
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
        deadline = deadline or (time.monotonic() + START_TIMEOUT_S)
        while time.monotonic() < deadline:
            if self._healthy(max(0.1, min(HEALTH_TIMEOUT_S, deadline - time.monotonic()))):
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
        section = self._section(run_id, agent, status, title, summary, verify, result or {}, secret=self.token)
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
            if _has_run(body, run_id):  # exact full id in the metadata line, not body text
                return True
            ids = _indexed_runs(body)
            if not ids:  # pre-index page: seed from the section metadata it still has
                ids = [sid for section in _split_sections(body) if (sid := _section_run_id(section))]
            if run_id in ids:  # its section was evicted, but the header index still remembers it
                return True
            # Append first, then trim both limits: trimming the old page alone would allow
            # MAX_SECTIONS + 1 after the append. The header id index survives section trimming.
            base = body if (body or "").strip() else _header(project_key, ident)
            new_body = _with_indexed_runs(base, (ids + [run_id])[-RUN_INDEX:])
            new_body = _trim(new_body, ident, project_key).rstrip() + "\n\n" + section + "\n"
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
                 verify: dict | None, result: dict, secret: str | None = None) -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
        lines = [f"## run {run_id[:8]} · {stamp} · {agent} · {status}",
                 f"<!-- agenticos-run: {run_id} -->"]
        if title:
            lines.append(f"- task: {_clip(_redact(" ".join(str(title).split()), secret), 240)}")
        if verify:
            lines.append(f"- verify: {verify.get('status', '?')} (exit {verify.get('exit', '?')}, "
                         f"{verify.get('duration_s', '?')} s)")
        if result.get("shortstat"):
            lines.append(f"- changes: {_one_line(result['shortstat'], 240)}")
        commit = result.get("runner_commit") or result.get("commit")
        if commit:
            lines.append(f"- commit: {str(commit)[:12]}")
        text = _clip(_redact(" ".join((summary or "").split()), secret), SUMMARY_BYTES)
        if text:
            lines.append(f"- summary: {text}")
        return "\n".join(lines)


_DEFAULT: Memory | None = None
_DEFAULT_LOCK = threading.Lock()


def _default() -> Memory:
    """Created on first use, not at import: app.py loads the checkout's .env *after* importing this
    module, so an eager client would capture the wrong server URL, data dir and binary."""
    global _DEFAULT
    if _DEFAULT is None:
        with _DEFAULT_LOCK:
            if _DEFAULT is None:
                _DEFAULT = Memory()
    return _DEFAULT


def brief(project_key: str, ident: str) -> str:
    """The process-wide client's brief; any unexpected failure is still a run without memory."""
    try:
        return _default().brief(project_key, ident)
    except Exception:  # noqa: BLE001 - a memory bug must never fail a dispatch
        log.exception("ai-memory: brief failed for %s/%s", project_key, ident)
        return ""


def record_run(project_key: str, ident: str, **run) -> bool:
    try:
        return _default().record_run(project_key, ident, **run)
    except Exception:  # noqa: BLE001 - a memory bug must never fail a run record
        log.exception("ai-memory: record failed for %s/%s", project_key, ident)
        return False


def scrub_token(text: str, token: str | None = None) -> str:
    """Remove the configured bearer token from text that is about to be persisted (run log).
    Format-based scrubbing stays out of this path: a run log is otherwise verbatim."""
    if token is None:
        try:
            token = _default().token
        except Exception:  # noqa: BLE001 - never fail a record write over this
            token = None
    return (text or "").replace(token, "[redacted]") if token else (text or "")


def scrub_record(value, token: str | None = None):
    """Walk a run-record value and remove the configured token from every string leaf. Strings
    stay strings, lists stay lists and dicts keep their keys; other types pass through."""
    if isinstance(value, str):
        return scrub_token(value, token)
    if isinstance(value, list):
        return [scrub_record(v, token) for v in value]
    if isinstance(value, tuple):
        return tuple(scrub_record(v, token) for v in value)
    if isinstance(value, dict):
        return {k: scrub_record(v, token) for k, v in value.items()}
    return value


def status() -> dict:
    """Debug/ops view; never raises."""
    mem = _default()
    return {"enabled": mem.enabled, "server": mem.server_url, "healthy": mem._healthy(),
            "binary": str(mem.binary), "data_dir": str(mem.data_dir)}


if __name__ == "__main__":  # python runner/ai_memory.py [brief <project> <ticket>]
    import sys

    if len(sys.argv) >= 4 and sys.argv[1] == "brief":
        print(brief(sys.argv[2], sys.argv[3]) or "(no memory yet)")
    else:
        print(json.dumps(status(), indent=2))
