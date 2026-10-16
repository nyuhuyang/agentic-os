"""dsh backend swap: argv/env, NDJSON parsing, outcome, session lock, retry, aliases, monitor."""

import json
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runner"))

import dsh_cli  # noqa: E402
from agent_ids import canonical_agent  # noqa: E402

KEY = "sk-test-SECRET-1234"
SID = "session-d62d80de-9d55-48e0-9291-08dfe22d66b9"


def ev(**kw) -> str:
    return json.dumps(kw)


OK_STREAM = [
    ev(type="session", sessionId=SID, cwd="/x"),
    ev(type="status", phase="turn_start", turn=1),
    ev(type="tool_call", callId="c1", tool="bash", input={"command": "ls"}),
    ev(type="tool_result", callId="c1", status="ok", result="a"),
    ev(type="status", phase="step_end", usage={"inputTokens": 100, "outputTokens": 7}),
    "not json at all",
    ev(type="status", phase="step_end", usage={"inputTokens": 50, "outputTokens": 3}),
    ev(type="final", text="done"),
]


@pytest.fixture(scope="module")
def app_mod():
    import app
    return app


class FakeProc:
    """Popen stand-in: yields NDJSON lines on stdout, fixed exit code."""
    instances: list = []

    def __init__(self, lines, code=0, stderr=b""):
        self.stdout = iter((line + "\n").encode() for line in lines)
        self._stderr = stderr
        self.returncode = None
        self._code = code
        self.args = ["dsh"]
        FakeProc.instances.append(self)

    @property
    def stderr(self):
        class _E:
            def __init__(s, b): s.b = b
            def read(s): return s.b
        return _E(self._stderr)

    def wait(self, timeout=None):
        self.returncode = self._code
        return self._code

    def kill(self):
        pass


# ── aliases ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw", ["deepseek", "deepseek-tui", "aider", "DeepSeek", " dsh "])
def test_legacy_ids_resolve_to_dsh(raw):
    assert canonical_agent(raw) == "dsh"


def test_unknown_agent_is_none():
    assert canonical_agent("gemini") is None and canonical_agent(None) is None


def test_ticket_marker_and_compose_use_dsh():
    from runner.modules.linear import _compose_issue_description, _extract_issue_agent
    assert _extract_issue_agent("x\n<!-- agent_backend: deepseek-tui -->") == "dsh"
    assert _extract_issue_agent("<!-- agent_backend: aider -->") == "dsh"
    assert _compose_issue_description("body", "deepseek").endswith("<!-- agent_backend: dsh -->")


def test_preferred_agent_setting_alias(app_mod):
    assert app_mod._preferred_task_agent({"agent": "deepseek"}) == "dsh"
    assert app_mod._preferred_task_agent({"agent": "deepseek-tui"}) == "dsh"


# ── argv / env ───────────────────────────────────────────────────────────

@pytest.fixture
def fake_prefix(app_mod):
    with patch.object(app_mod.dsh_cli, "cli_prefix", return_value=["dsh", "--profile", "headless"]):
        yield


def test_fresh_and_resume_argv(app_mod, fake_prefix):
    assert app_mod._ai_command("dsh", "-x task") == ["dsh", "--profile", "headless", "--json", "--", "-x task"]
    assert app_mod._build_resume_cmd("dsh", SID, "go on") == [
        "dsh", "--profile", "headless", "--json", "--session-id", SID, "--", "go on"]


def test_text_mode_has_no_json(app_mod, fake_prefix):
    assert "--json" not in app_mod._ai_command("dsh", "p", output_format="text")


def test_env_has_key_and_mode_not_argv(app_mod, fake_prefix, monkeypatch, tmp_path):
    monkeypatch.setenv("DEEPSEEK_API_KEY", KEY)
    monkeypatch.setattr(app_mod, "REGISTRY_CACHE_DIR", tmp_path)
    env = app_mod._registry_exec_env("dsh", {})
    assert env["DEEPSEEK_API_KEY"] == KEY and env["DSH_PERMISSION_MODE"] == "workspace-write"
    assert KEY not in " ".join(app_mod._ai_command("dsh", "p"))
    assert "DSH_PERMISSION_MODE" not in app_mod._registry_exec_env("codex", {})


def test_key_falls_back_to_config(monkeypatch, tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('api_key = "sk-from-file"\n')
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(dsh_cli, "_DEEPSEEK_CONFIG", cfg)
    assert dsh_cli.resolve_api_key() == "sk-from-file"
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env")
    assert dsh_cli.resolve_api_key() == "sk-env"  # env first


def test_routing_call_passes_env(app_mod, fake_prefix, monkeypatch):
    """Linear skill routing runs dsh in text mode with the key in env."""
    import runner.modules.linear as lin
    seen = {}

    def fake_run(cmd, timeout, **kw):
        seen["cmd"], seen["env"] = cmd, kw.get("env")
        raise RuntimeError("stop after routing")
    monkeypatch.setenv("DEEPSEEK_API_KEY", KEY)
    monkeypatch.setattr(app_mod, "_load_registry", lambda agent: {})
    monkeypatch.setattr(app_mod, "_registry_exec_env", lambda agent, reg: {"DEEPSEEK_API_KEY": KEY})
    monkeypatch.setattr(app_mod, "_run_grouped", fake_run)
    monkeypatch.setattr(app_mod, "_write_run_log", lambda *a, **k: None)  # never touch real run logs
    mod = lin.LinearModule()
    for name in ("push_state", "post_comment", "_mark_issue_review"):
        monkeypatch.setattr(mod, name, lambda *a, **k: None)
    with patch("subprocess.Popen", side_effect=RuntimeError("no dispatch")):
        mod._dispatch_issue({"id": "i1", "identifier": "T-1", "title": "t", "preferred_agent": "deepseek"},
                            {}, type("S", (), {"emit": lambda *a, **k: None})())
    assert "--json" not in seen["cmd"] and seen["env"]["DEEPSEEK_API_KEY"] == KEY


@pytest.mark.parametrize("version,ok", [("0.2.0-rc.2", True), ("0.2.0", True), ("0.2.1-rc.1", True),
                                        ("0.2.0-rc.1", False), ("0.1.9", False), ("garbage", False)])
def test_version_gate(monkeypatch, tmp_path, version, ok):
    fake = tmp_path / "dsh"
    fake.write_text("")
    monkeypatch.setattr(dsh_cli, "_probe_version", lambda b, m: version)
    if ok:
        assert dsh_cli.check_version(str(fake)) == version
    else:
        with pytest.raises(RuntimeError):
            dsh_cli.check_version(str(fake))


def test_missing_binary_is_clear_error(monkeypatch):
    monkeypatch.setattr(dsh_cli, "resolve_bin", lambda: None)
    with pytest.raises(FileNotFoundError, match="dsh CLI not found"):
        dsh_cli.cli_prefix()


# ── stream parsing and outcome ───────────────────────────────────────────

@pytest.fixture
def quiet_app(app_mod, monkeypatch, tmp_path):
    monkeypatch.setattr(app_mod, "RUN_PROGRESS_DIR", tmp_path)
    monkeypatch.setattr(app_mod.socketio, "emit", lambda *a, **k: None)
    return app_mod


def test_stream_ok(quiet_app):
    proc = FakeProc(OK_STREAM)
    out, it, ot, model, sid, err = quiet_app._stream_dsh_run(proc, "r1", timeout=5)
    assert (out, it, ot, model, sid) == ("done", 150, 10, None, SID)
    assert quiet_app._dsh_ok(proc, out)


def test_missing_usage_gives_null_tokens(quiet_app):
    lines = [ev(type="session", sessionId=SID), ev(type="status", phase="step_end", usage={"inputTokens": 5, "outputTokens": 1}),
             ev(type="status", phase="step_end"), ev(type="final", text="x")]
    _, it, ot, _, _, _ = quiet_app._stream_dsh_run(FakeProc(lines), "r2", timeout=5)
    assert (it, ot) == (None, None)


def test_final_then_exit1_is_error(quiet_app):
    proc = FakeProc([ev(type="session", sessionId=SID), ev(type="final", text="partial")], code=1,
                    stderr=b"noise\ndsh: E: msg\n")
    out, *_, err = quiet_app._stream_dsh_run(proc, "r3", timeout=5)
    assert out == "partial" and not quiet_app._dsh_ok(proc, out)
    assert "dsh: E: msg" in err and "dsh: exit 1" in err
    assert "dsh: E: msg" in quiet_app._extract_real_errors(err)


def test_exit0_without_final_is_error(quiet_app):
    proc = FakeProc([ev(type="session", sessionId=SID), ev(type="error", message="boom")])
    out, *_, err = quiet_app._stream_dsh_run(proc, "r4", timeout=5)
    assert out is None and not quiet_app._dsh_ok(proc, out)
    assert "dsh: boom" in err and "no final event" in err


# ── session lock provenance ──────────────────────────────────────────────

def _log(path, *records):
    path.write_text("".join(json.dumps({"task_id": "T", **r}) + "\n" for r in records))


def test_lock_ignores_rust_session(app_mod, monkeypatch, tmp_path):
    log = tmp_path / "run_log.jsonl"
    monkeypatch.setattr(app_mod, "RUN_LOG", log)
    _log(log, {"run_id": "a", "agent": "deepseek-tui", "status": "review", "agent_session_id": "rust-123"})
    assert app_mod._get_task_agent_lock("T") == {"agent": "dsh", "agent_session_id": None}


def test_lock_uses_dsh_session_and_rework_clears(app_mod, monkeypatch, tmp_path):
    log = tmp_path / "run_log.jsonl"
    monkeypatch.setattr(app_mod, "RUN_LOG", log)
    _log(log, {"run_id": "a", "agent": "codex", "status": "review", "agent_session_id": "codex-sid"},
         {"run_id": "b", "agent": "dsh", "status": "review", "agent_session_id": SID})
    assert app_mod._get_task_agent_lock("T") == {"agent": "dsh", "agent_session_id": SID}
    _log(log, {"run_id": "b", "agent": "dsh", "status": "review", "agent_session_id": SID},
         {"run_id": "b", "agent": "dsh", "status": "rework", "agent_session_id": SID})
    assert app_mod._get_task_agent_lock("T") is None


def test_reset_boundary(app_mod, monkeypatch, tmp_path):
    """S1 → rework copy → fresh run failing with no session → retry must not resume S1."""
    log = tmp_path / "run_log.jsonl"
    monkeypatch.setattr(app_mod, "RUN_LOG", log)
    _log(log, {"run_id": "a", "agent": "dsh", "status": "review", "agent_session_id": SID},
         {"run_id": "a", "agent": "dsh", "status": "rework", "agent_session_id": SID},
         {"run_id": "c", "agent": "dsh", "status": "error"})
    assert app_mod._get_task_agent_lock("T") == {"agent": "dsh", "agent_session_id": None}


# ── retry: resume, no fallback ───────────────────────────────────────────

def _retry(app_mod, monkeypatch, tmp_path, lines, code, stderr=b""):
    log = tmp_path / "run_log.jsonl"
    _log(log, {"run_id": "a", "agent": "dsh", "status": "review", "agent_session_id": SID,
               "skill": "_prompt", "prompt": "task"})
    monkeypatch.setattr(app_mod, "RUN_LOG", log)
    monkeypatch.setattr(app_mod, "RUN_PROGRESS_DIR", tmp_path)
    monkeypatch.setattr(app_mod.socketio, "emit", lambda *a, **k: None)
    monkeypatch.setattr(app_mod, "_load_registry", lambda agent: {})
    monkeypatch.setattr(app_mod, "_registry_exec_env", lambda agent, reg: {})
    monkeypatch.setattr(app_mod.dsh_cli, "cli_prefix", lambda: ["dsh", "--profile", "headless"])
    logged, cmds = [], []
    monkeypatch.setattr(app_mod, "_write_run_log", lambda *a, **k: logged.append((a, k)))

    def popen(cmd, **kw):
        cmds.append(cmd)
        return FakeProc(lines, code, stderr)
    monkeypatch.setattr(app_mod.subprocess, "Popen", popen)

    class SyncThread:
        def __init__(self, target, daemon=None): self.target = target
        def start(self): self.target()
        def join(self, timeout=None): pass
        def is_alive(self): return False
    monkeypatch.setattr(app_mod.threading, "Thread", SyncThread)
    resp = app_mod.app.test_client().post(
        "/api/runs/a/retry", json={}, headers={"X-AgenticOS-Token": app_mod.REQUEST_TOKEN})
    assert resp.status_code == 200
    return cmds, logged


def test_retry_resumes_session(app_mod, monkeypatch, tmp_path):
    cmds, logged = _retry(app_mod, monkeypatch, tmp_path, OK_STREAM, 0)
    assert len(cmds) == 1 and cmds[0][4:6] == ["--session-id", SID]
    (args, kw), = logged
    assert args[1] == "review" and kw["agent_session_id"] == SID and kw["agent"] == "dsh"


def test_failed_resume_has_no_fallback(app_mod, monkeypatch, tmp_path):
    lines = [ev(type="error", message=f"session {SID} was recorded in /a, not /b")]
    cmds, logged = _retry(app_mod, monkeypatch, tmp_path, lines, 1, b"dsh: session/writer-held\n")
    assert len(cmds) == 1  # exactly one process
    (args, kw), = logged
    assert args[1] == "error" and "writer-held" in kw["error"]


# ── registry and capabilities ────────────────────────────────────────────

def test_registry_dsh_branch(tmp_path):
    from runner.core import registry_loader as rl
    master = tmp_path / "registry.json"
    master.write_text(json.dumps({"skills": {
        "a": {"agents": ["claude", "deepseek"]}, "b": {"agents": ["claude"]},
        "c": {"agents": ["dsh"]}, "d": {"agents": ["aider"]}}}))
    with patch.object(rl, "_PROJECT_ROOT", tmp_path), patch.object(rl, "_MASTER_REGISTRY_JSON", master):
        reg = rl.load_registry("dsh")
    assert set(reg) == {"a", "c", "d"} and all("dsh" in e["agents"] for e in reg.values())
    assert json.loads(master.read_text())["skills"]["a"]["agents"] == ["claude", "deepseek"]  # not rewritten


def test_capabilities_list_dsh():
    from runner.core.module_registry import AgenticModule, ModuleRegistry

    class DS(AgenticModule):
        name, label = "deepseek", "DeepSeek"
        def check_capabilities(self): return {"available": True, "backend": "dsh"}
    reg = ModuleRegistry()
    reg.register(DS())
    reg.load_all()
    assert reg.get_capabilities()["backends"] == ["dsh"]


# ── monitor ──────────────────────────────────────────────────────────────

@pytest.fixture
def mon(monkeypatch, tmp_path):
    import deepseek_monitor as m
    monkeypatch.setattr(m, "_DEEPSEEK_DIR", tmp_path)
    monkeypatch.setattr(m, "_USAGE_PATH", tmp_path / "usage.json")
    monkeypatch.setattr(m, "_LOCK_PATH", tmp_path / "usage.json.lock")
    monkeypatch.setattr(m, "resolve_api_key", lambda: KEY)
    return m


def _poll(m, monkeypatch, now, balance):
    monkeypatch.setattr(m, "_now", lambda: now)
    monkeypatch.setattr(m, "fetch_balance",
                        lambda key=None: {"error": "down"} if balance is None else {"balance_cny": balance, "balance_usd": 0.0, "currency": "CNY"})
    return m.update_usage()


def test_balance_decrease_windows_and_topup(mon, monkeypatch):
    t0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
    _poll(mon, monkeypatch, t0, 100.0)
    _poll(mon, monkeypatch, t0 + timedelta(days=1), 90.0)      # spend 10, outside 5h
    _poll(mon, monkeypatch, t0 + timedelta(days=2), 150.0)     # top-up ignored
    r = _poll(mon, monkeypatch, t0 + timedelta(days=2, hours=1), 147.5)  # spend 2.5
    assert r["window_5h_cost_cny"] == 2.5 and r["window_7d_cost_cny"] == 12.5
    assert r["window_5h"]["tokens"] is None and r["window_7d"]["sessions"] is None
    assert r["total_cost_cny"] == 12.5


def test_failure_creates_no_spend(mon, monkeypatch):
    t0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
    _poll(mon, monkeypatch, t0, 100.0)
    r = _poll(mon, monkeypatch, t0 + timedelta(minutes=2), None)
    assert r["stale"] is True and r["last_error"] == "down" and r["balance"]["balance_cny"] == 100.0
    r = _poll(mon, monkeypatch, t0 + timedelta(minutes=4), 100.0)
    assert r["stale"] is False and r["total_cost_cny"] == 0 and len(r["_balance_snapshots"]) == 1


def test_old_spend_survives_many_polls(mon, monkeypatch):
    now = datetime(2026, 10, 10, tzinfo=timezone.utc)
    _poll(mon, monkeypatch, now - timedelta(days=40), 100.0)   # outside retention: kept as baseline
    _poll(mon, monkeypatch, now - timedelta(days=2), 90.0)
    for i in range(250):  # unchanged balance → no new samples
        r = _poll(mon, monkeypatch, now - timedelta(days=2) + timedelta(minutes=2 * (i + 1)), 90.0)
    assert r["window_7d_cost_cny"] == 10.0
    assert [s["balance_cny"] for s in r["_balance_snapshots"]] == [100.0, 90.0]
    r = _poll(mon, monkeypatch, now + timedelta(days=30), 90.0)
    assert [s["balance_cny"] for s in r["_balance_snapshots"]][0] == 90.0  # newest pre-window kept


def test_concurrent_updates_keep_both_samples(mon, monkeypatch):
    values = iter([100.0, 95.0])
    guard = threading.Lock()

    def slow_fetch(key=None):
        with guard:
            v = next(values)
        time.sleep(0.05)
        return {"balance_cny": v, "balance_usd": 0.0, "currency": "CNY"}
    monkeypatch.setattr(mon, "fetch_balance", slow_fetch)
    threads = [threading.Thread(target=mon.update_usage) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    data = json.loads(mon._USAGE_PATH.read_text())
    assert [s["balance_cny"] for s in data["_balance_snapshots"]] == [100.0, 95.0]


def test_key_change_resets_history(mon, monkeypatch):
    t0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
    _poll(mon, monkeypatch, t0, 100.0)
    monkeypatch.setattr(mon, "resolve_api_key", lambda: "sk-other-account")
    r = _poll(mon, monkeypatch, t0 + timedelta(hours=1), 20.0)
    assert r["total_cost_cny"] == 0 and len(r["_balance_snapshots"]) == 1
    assert r["key_fp"] == dsh_cli.key_fp("sk-other-account")


def test_missing_key_keeps_history(mon, monkeypatch):
    """DSH-20: an unresolvable key is a failed fetch, not an account change."""
    t0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
    _poll(mon, monkeypatch, t0, 100.0)
    _poll(mon, monkeypatch, t0 + timedelta(hours=1), 90.0)
    monkeypatch.setattr(mon, "resolve_api_key", lambda: None)
    r = _poll(mon, monkeypatch, t0 + timedelta(hours=2), 50.0)
    assert r["stale"] is True and r["total_cost_cny"] == 10.0 and len(r["_balance_snapshots"]) == 2
    assert r["key_fp"] == dsh_cli.key_fp(KEY) and r["balance"]["balance_cny"] == 90.0


def test_direct_api_run_never_locks(app_mod, monkeypatch, tmp_path):
    """DSH-21: a historical direct-API deepseek run has no session and never locks retry."""
    log = tmp_path / "run_log.jsonl"
    monkeypatch.setattr(app_mod, "RUN_LOG", log)
    _log(log, {"run_id": "a", "agent": "deepseek", "status": "review"})
    assert app_mod._get_task_agent_lock("T") is None


def test_dsh_cost_unknown(app_mod):
    """DSH-22: no model → no invented price."""
    assert app_mod._compute_token_cost(500_000, 500_000, None) is None


def test_stream_drains_large_stderr(quiet_app):
    """DSH-23: a real child writing far past the pipe buffer to stderr still finishes."""
    import subprocess as sp
    script = ("import sys; sys.stderr.write('x' * 300000); sys.stderr.flush(); "
              f"print({ev(type='session', sessionId=SID)!r}); print({ev(type='final', text='ok')!r})")
    proc = sp.Popen([sys.executable, "-c", script], stdout=sp.PIPE, stderr=sp.PIPE)
    out, *_ = quiet_app._stream_dsh_run(proc, "r5", timeout=20)
    assert out == "ok" and quiet_app._dsh_ok(proc, out)


def test_stream_deadline_kills_child(quiet_app):
    import subprocess as sp
    proc = sp.Popen([sys.executable, "-c", "import time; time.sleep(30)"], stdout=sp.PIPE, stderr=sp.PIPE)
    with pytest.raises(sp.TimeoutExpired):
        quiet_app._stream_dsh_run(proc, "r6", timeout=1)
    assert proc.poll() is not None  # killed and reaped


def test_usd_only_account_tracks_spend(mon, monkeypatch):
    """DSH-26: USD-only balances are normalized, not discarded as stale."""
    import io
    t0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
    for i, usd in enumerate(("10.00", "9.00")):
        body = json.dumps({"is_available": True, "balance_infos": [{"currency": "USD", "total_balance": usd}]})
        monkeypatch.setattr(mon.urllib.request, "urlopen", lambda req, timeout=None, b=body: io.BytesIO(b.encode()))
        monkeypatch.setattr(mon, "_now", lambda i=i: t0 + timedelta(hours=i))
        r = mon.update_usage()
    assert r["stale"] is False and r["balance"]["currency"] == "USD" and r["total_cost_cny"] == 7.2


@pytest.mark.parametrize("bad", ["Infinity", "NaN", "1e309", "-inf"])
def test_non_finite_balance_is_a_failed_fetch(mon, monkeypatch, bad):
    """DSH-27: non-finite balances never become samples; the usage file stays valid JSON."""
    import io
    real_fetch = mon.fetch_balance
    t0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
    _poll(mon, monkeypatch, t0, 100.0)
    body = json.dumps({"balance_infos": [{"currency": "CNY", "total_balance": bad}]})
    monkeypatch.setattr(mon, "fetch_balance", real_fetch)
    monkeypatch.setattr(mon.urllib.request, "urlopen", lambda req, timeout=None: io.BytesIO(body.encode()))
    monkeypatch.setattr(mon, "_now", lambda: t0 + timedelta(hours=1))
    r = mon.update_usage()
    assert r["stale"] is True and [s["balance_cny"] for s in r["_balance_snapshots"]] == [100.0]
    json.loads(mon._USAGE_PATH.read_text())


def test_cached_non_finite_samples_dropped(mon, monkeypatch):
    mon._USAGE_PATH.write_text(json.dumps({"key_fp": dsh_cli.key_fp(KEY), "_total_cost_cny": "Infinity",
                                           "_balance_snapshots": [{"ts": "2026-10-01T00:00:00+00:00", "balance_cny": "NaN"},
                                                                  {"ts": "2026-10-01T01:00:00+00:00", "balance_cny": 50.0}]}))
    r = _poll(mon, monkeypatch, datetime(2026, 10, 1, 2, tzinfo=timezone.utc), 40.0)
    assert r["total_cost_cny"] == 10.0 and [s["balance_cny"] for s in r["_balance_snapshots"]] == [50.0, 40.0]


def test_linear_dispatch_sends_selected_skill_instructions(app_mod, fake_prefix, monkeypatch, tmp_path):
    """DSH-25: the routed AI-only skill's SKILL.md reaches dsh in the execution argv."""
    import runner.modules.linear as lin
    skill_md = tmp_path / "SKILL.md"
    skill_md.write_text("---\nname: myskill\n---\nALWAYS-SAY-PELICAN\n")
    registry = {"myskill": {"skill_path": str(skill_md), "purpose": "p", "agents": ["dsh"]}}
    monkeypatch.setattr(app_mod, "_load_registry", lambda agent: registry)
    monkeypatch.setattr(app_mod, "_registry_exec_env", lambda agent, reg: {})
    monkeypatch.setattr(app_mod, "_write_run_log", lambda *a, **k: None)
    monkeypatch.setattr(app_mod, "_run_grouped", lambda cmd, timeout, **kw: type("R", (), {"stdout": "myskill"})())
    seen = []

    def popen(cmd, **kw):
        seen.append(cmd)
        raise RuntimeError("stop before running")
    monkeypatch.setattr("subprocess.Popen", popen)
    mod = lin.LinearModule()
    for name in ("push_state", "post_comment", "_mark_issue_review"):
        monkeypatch.setattr(mod, name, lambda *a, **k: None)
    mod._dispatch_issue({"id": "i2", "identifier": "T-2", "title": "t", "preferred_agent": "dsh"},
                        {}, type("S", (), {"emit": lambda *a, **k: None})())
    assert seen and "ALWAYS-SAY-PELICAN" in seen[0][-1] and seen[0][3] == "--json"


def test_linear_launch_failure_is_cleaned_up(app_mod, monkeypatch):
    """DSH-28: a missing dsh fails the actual run (error record, no stuck running job/dispatch)."""
    import runner.modules.linear as lin
    monkeypatch.setattr(app_mod.dsh_cli, "cli_prefix", lambda: (_ for _ in ()).throw(FileNotFoundError("dsh CLI not found")))
    monkeypatch.setattr(app_mod, "_load_registry", lambda agent: {})
    logged = []
    monkeypatch.setattr(app_mod, "_write_run_log", lambda *a, **k: logged.append((a, k)))
    mod = lin.LinearModule()
    reviewed = []
    monkeypatch.setattr(mod, "push_state", lambda *a, **k: None)
    monkeypatch.setattr(mod, "post_comment", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_mark_issue_review", lambda iid, gen=None: (reviewed.append(iid), mod.dispatched.pop(iid, None)))
    mod._dispatch_issue({"id": "i3", "identifier": "T-3", "title": "t", "preferred_agent": "dsh"},
                        {}, type("S", (), {"emit": lambda *a, **k: None})())
    (args, kw), = logged
    assert args[1] == "error" and "dsh CLI not found" in kw["error"] and kw["agent"] == "dsh"
    assert kw["run_id"] not in app_mod._running_jobs and "i3" not in mod.dispatched and reviewed == ["i3"]
