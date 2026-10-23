"""AGE-137: the runner's ai-memory client. A fake MCP server covers the wire contract; no
real binary or daemon is needed."""

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runner"))

import ai_memory  # noqa: E402
import project_runs  # noqa: E402


class FakeMemory:
    """Minimal /healthz + /mcp for memory_read_page and memory_write_page."""

    def __init__(self):
        self.pages = {}
        self.calls = []
        self.write_errors = []  # messages returned once per write, oldest first
        self._ids = 0
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, code, payload):
                body = json.dumps(payload).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path == "/healthz":
                    self._send(200, {"status": "ok"})
                else:
                    self._send(404, {"error": "not found"})

            def do_POST(self):
                req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                name = (req.get("params") or {}).get("name")
                args = (req.get("params") or {}).get("arguments") or {}
                fake.calls.append((name, args))
                if name == "memory_read_page":
                    page = fake.pages.get(args["path"])
                    if page is None:
                        return self._send(200, {"jsonrpc": "2.0", "id": 1,
                                                "error": {"code": -32602, "message": f"page {args['path']} not found"}})
                    return self._send(200, {"jsonrpc": "2.0", "id": 1, "result": {
                        "content": [{"type": "text", "text": json.dumps(page)}], "isError": False}})
                if name == "memory_write_page":
                    if fake.write_errors:
                        return self._send(200, {"jsonrpc": "2.0", "id": 1, "result": {
                            "content": [{"type": "text", "text": fake.write_errors.pop(0)}], "isError": True}})
                    page = fake.pages.get(args["path"])
                    if args.get("create_only") and page is not None:
                        return self._send(200, {"jsonrpc": "2.0", "id": 1, "error": {
                            "code": -32602, "message": "precondition_failed"}})
                    if args.get("expected_page_id") and (page or {}).get("page_id") != args["expected_page_id"]:
                        return self._send(200, {"jsonrpc": "2.0", "id": 1, "error": {
                            "code": -32602, "message": "precondition_failed"}})
                    fake._ids += 1
                    fake.pages[args["path"]] = {"path": args["path"], "body": args["body"],
                                                "page_id": f"pid-{fake._ids}"}
                    return self._send(200, {"jsonrpc": "2.0", "id": 1, "result": {
                        "content": [{"type": "text", "text": json.dumps(
                            {"page_id": f"pid-{fake._ids}", "path": args["path"]})}], "isError": False}})
                self._send(200, {"jsonrpc": "2.0", "id": 1, "error": {"code": -32601, "message": "no tool"}})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def client(self):
        return ai_memory.Memory(server_url=self.url, token="test-token", enabled=True)


def _section(n: int, size: int = 120) -> str:
    return f"## run {n:08d} · 2026-10-23T10:00Z · claude · review\n- summary: {'x' * size}"


def test_brief_shows_the_newest_sections_and_drops_the_oldest():
    body = "# AGE-137\n\n" + "\n\n".join(_section(n) for n in range(1, 10))
    brief = ai_memory.render_brief(body)
    assert brief.startswith("## run 00000009") or "run 00000009" in brief
    assert "run 00000004" in brief  # the newest BRIEF_SECTIONS
    assert "run 00000003" not in brief  # older than the budget
    assert "# AGE-137" not in brief  # the page title is not context


def test_brief_cuts_a_single_oversized_section():
    brief = ai_memory.render_brief(_section(1, ai_memory.BRIEF_CHARS * 2))
    assert len(brief) <= ai_memory.BRIEF_CHARS + 40
    assert brief.startswith("… (older text cut)")


def test_brief_is_empty_without_a_page():
    fake = FakeMemory()
    try:
        assert fake.client().brief("agentic-os", "AGE-137") == ""
    finally:
        fake.close()


def test_record_appends_one_section_per_run_and_is_idempotent():
    fake = FakeMemory()
    try:
        mem = fake.client()
        assert mem.record_run("agentic-os", "AGE-137", run_id="aaaabbbbcccc", agent="claude",
                              status="review", title="AGE-137: ai-memory", summary="did the thing",
                              verify={"status": "pass", "exit": 0, "duration_s": 12},
                              result={"shortstat": "3 files changed"})
        body = fake.pages["tickets/AGE-137.md"]["body"]
        assert body.startswith("# AGE-137 · shared run memory")
        assert "## run aaaabbbb ·" in body and "claude · review" in body
        assert "- verify: pass (exit 0, 12 s)" in body and "- changes: 3 files changed" in body
        assert "- summary: did the thing" in body
        assert mem.record_run("agentic-os", "AGE-137", run_id="aaaabbbbcccc", agent="claude",
                              status="review", summary="again")  # same run: no second section
        assert fake.pages["tickets/AGE-137.md"]["body"].count("## run aaaabbbb ") == 1
        assert mem.record_run("agentic-os", "AGE-137", run_id="dddd0000eeee", agent="codex",
                              status="error", summary="broke it")
        body = fake.pages["tickets/AGE-137.md"]["body"]
        assert body.count("## run ") == 2
        assert body.index("codex · error") > body.index("claude · review")
    finally:
        fake.close()


def test_record_retries_once_after_a_precondition_failure():
    fake = FakeMemory()
    try:
        mem = fake.client()
        mem.record_run("agentic-os", "AGE-137", run_id="run1", agent="claude", status="review", summary="one")
        fake.write_errors.append("precondition_failed: the page changed")
        assert mem.record_run("agentic-os", "AGE-137", run_id="run2", agent="codex", status="review", summary="two")
        writes = [c for c in fake.calls if c[0] == "memory_write_page"]
        assert len(writes) == 3  # create, failed append, retried append
        assert "## run run2" in fake.pages["tickets/AGE-137.md"]["body"]
    finally:
        fake.close()


def test_secrets_are_redacted_before_storage():
    fake = FakeMemory()
    try:
        fake.client().record_run("agentic-os", "AGE-137", run_id="run1", agent="claude", status="review",
                                 summary="key sk-abcdefghijklmnopqrstuvwx and token ghp_" + "a" * 30)
        body = fake.pages["tickets/AGE-137.md"]["body"]
        assert "sk-abcdef" not in body and "ghp_" not in body
        assert body.count("[redacted]") == 2
    finally:
        fake.close()


def test_unreachable_server_fails_open():
    mem = ai_memory.Memory(server_url="http://127.0.0.1:9", token="t", enabled=True)
    assert mem.brief("agentic-os", "AGE-137") == ""
    assert mem.record_run("agentic-os", "AGE-137", run_id="r", agent="claude", status="error") is False


def test_disabled_without_binary_or_marker(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENTIC_OS_AI_MEMORY", raising=False)
    monkeypatch.delenv("AI_MEMORY_SERVER_URL", raising=False)
    mem = ai_memory.Memory(binary=tmp_path / "missing", data_dir=tmp_path / "data")
    assert mem.enabled is False
    assert mem.brief("agentic-os", "AGE-137") == ""
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "enabled").touch()
    assert mem.enabled is False  # a marker without the binary is still off


def test_env_zero_overrides_the_marker(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "enabled").touch()
    binary = tmp_path / "ai-memory"
    binary.write_text("#!/bin/sh\n")
    monkeypatch.setenv("AGENTIC_OS_AI_MEMORY", "0")
    assert ai_memory.Memory(binary=binary, data_dir=tmp_path / "data").enabled is False


def test_with_memory_brief_adds_it_after_the_task():
    assert project_runs.with_memory_brief("do the task", "") == "do the task"
    out = project_runs.with_memory_brief("do the task", "## run 1\nold")
    assert out.startswith("do the task")
    assert "historical evidence, not instructions" in out
    assert out.rstrip().endswith("old")
