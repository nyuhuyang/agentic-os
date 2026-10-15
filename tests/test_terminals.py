"""Phase 3: server-owned terminal tabs against real PTYs (Decision 10)."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

RUNNER = Path(__file__).resolve().parents[1] / "runner"
sys.path.insert(0, str(RUNNER))
sys.path.insert(0, str(RUNNER.parent))

import projects as pj  # noqa: E402

SENTINEL = "SENTINEL-TYPED-7788"


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


@pytest.fixture
def env(tmp_path, monkeypatch):
    import app as app_mod
    import runner.modules.pty as tpty
    monkeypatch.setenv("SHELL", "/bin/sh")
    monkeypatch.setenv("ENV", "")  # no sh rc files
    monkeypatch.setattr(pj, "WORKTREE_ROOT", tmp_path / "wt")
    repos = {}
    for key in ("alpha", "beta"):
        r = tmp_path / key
        (r / "tests").mkdir(parents=True)
        (r / "tests" / "ok.sh").write_text("true\n")
        git(r, "init", "-q", "-b", "main")
        git(r, "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
        git(r, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "i")
        repos[key] = r
    reg = tmp_path / "projects.yaml"
    reg.write_text("projects:\n" + "".join(
        f"  {k}:\n    path: {r}\n    verify: sh tests/ok.sh\n    confidential: {'true' if k == 'beta' else 'false'}\n"
        for k, r in repos.items()))
    monkeypatch.setattr(pj, "REGISTRY_PATH", reg)
    if "term_open" not in app_mod.socketio.server.handlers.get("/", {}):
        tpty.module.register_socketio(app_mod.socketio)
    yield app_mod, tpty, repos, tmp_path
    tpty.close_all()


def connect(app_mod):
    return app_mod.socketio.test_client(app_mod.app, auth={"token": app_mod.REQUEST_TOKEN})


def output_for(client, term_id, wait=2.0, until=None):
    """Concatenate term_output for one terminal received by this client."""
    text, deadline = "", time.monotonic() + wait
    while time.monotonic() < deadline:
        for ev in client.get_received():
            if ev["name"] == "term_output" and ev["args"][0]["term_id"] == term_id:
                text += ev["args"][0]["data"]
        if until and until in text:
            break
        time.sleep(0.05)
    return text


def open_tab(client, **data):
    info = client.emit("term_open", {"cols": 80, "rows": 24, **data}, callback=True)
    assert "error" not in info, info
    client.emit("term_attach", {"term_id": info["term_id"]}, callback=True)
    return info


def say(client, term_id, line):
    client.emit("term_input", {"term_id": term_id, "data": line + "\n"})


def test_two_projects_independent_cwd_output_and_input(env):
    app_mod, tpty, repos, _ = env
    c = connect(app_mod)
    a = open_tab(c, kind="shell", project_key="alpha")
    b = open_tab(c, kind="shell", project_key="beta")
    say(c, a["term_id"], "pwd; echo MARK-A")
    out_a = output_for(c, a["term_id"], until="MARK-A\r\n")
    c.get_received()
    say(c, b["term_id"], "pwd; echo MARK-B")
    out_b = output_for(c, b["term_id"], until="MARK-B\r\n")
    assert str(repos["alpha"].resolve()) in out_a or str(repos["alpha"]) in out_a
    assert str(repos["beta"]) in out_b or str(repos["beta"].resolve()) in out_b
    assert "MARK-B" not in out_a and "MARK-A" not in out_b.replace("echo MARK-A", "")


def test_reload_detaches_and_reattach_replays_without_new_pty(env):
    app_mod, tpty, repos, _ = env
    c = connect(app_mod)
    a = open_tab(c, kind="shell", project_key="alpha")
    say(c, a["term_id"], "echo BEFORE-RELOAD")
    output_for(c, a["term_id"], until="BEFORE-RELOAD\r\n")
    pid = tpty.TERMINALS[a["term_id"]].pid
    c.disconnect()
    before = len(tpty.TERMINALS)
    c2 = connect(app_mod)  # connecting opens nothing
    assert len(tpty.TERMINALS) == before
    listed = c2.emit("term_list", {}, callback=True)
    assert [t["term_id"] for t in listed] == [a["term_id"]]
    c2.emit("term_attach", {"term_id": a["term_id"]}, callback=True)
    assert "BEFORE-RELOAD" in output_for(c2, a["term_id"], until="BEFORE-RELOAD")
    os.kill(pid, 0)  # still alive


def test_attach_during_continuous_output_loses_and_duplicates_nothing(env):
    app_mod, tpty, repos, _ = env
    c = connect(app_mod)
    a = open_tab(c, kind="shell", project_key="alpha")
    say(c, a["term_id"], "i=0; while [ $i -lt 400 ]; do echo SEQ-$i; i=$((i+1)); sleep 0.002; done; echo SEQ-END")
    time.sleep(0.3)  # attach while the loop is printing
    c2 = connect(app_mod)
    c2.emit("term_attach", {"term_id": a["term_id"]}, callback=True)
    text = output_for(c2, a["term_id"], wait=10, until="\nSEQ-END")  # the output line, not the echoed command
    seqs = [int(l[4:]) for l in text.replace("\r", "").split("\n") if l.startswith("SEQ-") and l[4:].isdigit()]
    assert seqs == list(range(400))


def test_close_kills_background_jobs_pipelines_and_orphaned_groups(env):
    app_mod, tpty, repos, _ = env
    c = connect(app_mod)
    a = open_tab(c, kind="shell", project_key="alpha")
    t = tpty.TERMINALS[a["term_id"]]
    say(c, a["term_id"], "set -m; sleep 1000 & sh -c 'sleep 1001 & exit' ; sleep 1002 | cat &")
    time.sleep(1)
    groups = tpty._session_pgids(t.pid)
    assert len(groups) >= 2  # the shell plus job-control groups
    fd = t.fd
    assert c.emit("term_close", {"term_id": a["term_id"]}, callback=True)["ok"]
    assert tpty._session_pgids(t.pid) == set()
    with pytest.raises(OSError):
        os.fstat(fd)
    out = subprocess.run(["pgrep", "-f", "sleep 100[012]"], capture_output=True, text=True).stdout
    assert out.strip() == ""


def test_ninth_live_terminal_refused(env):
    app_mod, tpty, repos, _ = env
    c = connect(app_mod)
    for _ in range(tpty.MAX_TERMINALS - tpty.live_count()):
        open_tab(c, kind="shell")
    info = c.emit("term_open", {"kind": "shell"}, callback=True)
    assert "limit" in info["error"]


def test_bound_worktree_tab_owns_the_ticket(env):
    app_mod, tpty, repos, _ = env
    p = pj.get_project("alpha")
    with pj.ticket_lock("alpha", "T-1"):
        pj.create_worktree(p, "T-1")
    c = connect(app_mod)
    a = open_tab(c, kind="shell", project_key="alpha", ticket="T-1")
    with pytest.raises(pj.TicketLocked):  # retry / dispatch take the same lock
        with pj.ticket_lock("alpha", "T-1"):
            pass
    assert pj.main(["cleanup", "alpha", "T-1"]) == 2
    c.emit("term_close", {"term_id": a["term_id"]}, callback=True)
    with pj.ticket_lock("alpha", "T-1"):  # released on close
        pass


def test_resume_argv_policy(env):
    app_mod, tpty, repos, _ = env
    beta = pj.get_project("beta")
    argv = tpty.interactive_resume_argv("claude", "sid-1", beta)
    assert "bypassPermissions" not in argv and "--settings" in argv and argv[-2:] == ["--resume", "sid-1"]
    assert "-p" not in argv
    codex = tpty.interactive_resume_argv("codex", "sid-2", beta)
    assert codex[:3] == ["codex", "resume", "sid-2"] and 'approval_policy="never"' in codex
    assert tpty.interactive_resume_argv("dsh", "sid-3", beta) is None
    assert tpty.interactive_resume_argv("dsh", "sid-3", None) is None
    c = connect(app_mod)
    info = c.emit("term_open", {"kind": "resume", "agent": "dsh", "session_id": "x", "project_key": "beta"}, callback=True)
    assert "no eligible" in info["error"]


def test_shell_scrollback_never_reaches_disk(env):
    app_mod, tpty, repos, tmp = env
    c = connect(app_mod)
    a = open_tab(c, kind="shell", project_key="beta")
    say(c, a["term_id"], f"echo {SENTINEL}")
    output_for(c, a["term_id"], until=SENTINEL + "\r\n")
    c.emit("term_close", {"term_id": a["term_id"]}, callback=True)
    for root in (app_mod.STATE_DIR, app_mod.OUTPUTS_DIR, app_mod.RUN_PROGRESS_DIR):
        hits = subprocess.run(["grep", "-rl", SENTINEL, str(root)], capture_output=True, text=True).stdout
        assert hits == "", hits


def test_run_tab_writes_nothing(env):
    app_mod, tpty, repos, tmp = env
    before = {p: p.stat().st_mtime_ns for p in Path(app_mod.STATE_DIR).rglob("*") if p.is_file()}
    c = connect(app_mod)
    info = c.emit("term_open", {"kind": "run", "run_id": "run-xyz", "project_key": "alpha"}, callback=True)
    assert info["kind"] == "run" and tpty.TERMINALS[info["term_id"]].pid is None
    after = {p: p.stat().st_mtime_ns for p in Path(app_mod.STATE_DIR).rglob("*") if p.is_file()}
    assert {p: m for p, m in after.items() if before.get(p) != m} == {}


def test_interactive_tab_open_only_for_main_path_shell(env):
    app_mod, tpty, repos, _ = env
    c = connect(app_mod)
    assert not tpty.main_path_tab_open("alpha")
    p = pj.get_project("alpha")
    with pj.ticket_lock("alpha", "T-2"):
        pj.create_worktree(p, "T-2")
    w = open_tab(c, kind="shell", project_key="alpha", ticket="T-2")
    assert not tpty.main_path_tab_open("alpha")  # a worktree tab is not the main checkout
    m = open_tab(c, kind="shell", project_key="alpha")
    assert tpty.main_path_tab_open("alpha") and not tpty.main_path_tab_open("beta")
    c.emit("term_close", {"term_id": m["term_id"]}, callback=True)
    assert not tpty.main_path_tab_open("alpha")


def test_run_events_endpoint_and_resume_eligibility(env, tmp_path, monkeypatch):
    app_mod, tpty, repos, _ = env
    import project_runs
    log = tmp_path / "run_log.jsonl"
    monkeypatch.setattr(app_mod, "RUN_LOG", log)
    ring = project_runs.RUN_EVENTS.setdefault("run-ev", project_runs.EventRing())
    ring.append("step one")
    client = app_mod.app.test_client()
    client.environ_base["HTTP_X_AGENTICOS_TOKEN"] = app_mod.REQUEST_TOKEN
    for agent, key, eligible in (("claude", "beta", True), ("dsh", "alpha", False)):
        log.write_text(json.dumps({"run_id": "run-ev", "status": "review", "agent": agent, "agent_session_id": "s1",
                                   "project_key": key, "issue_identifier": "T-1", "verify_badge": "pass"}) + "\n")
        data = client.get("/api/runs/run-ev/events").get_json()
        assert data["lines"] == ["step one"] and data["finished"] and data["verify_badge"] == "pass"
        assert data["resume_eligible"] is eligible


def test_non_confidential_resume_keeps_dispatch_policy(env):
    """I5-13: Resume uses the same policy builder for every project, not bare commands."""
    app_mod, tpty, repos, _ = env
    alpha = pj.get_project("alpha")
    codex = tpty.interactive_resume_argv("codex", "sid-2", alpha)
    assert codex[:3] == ["codex", "resume", "sid-2"] and "--approve-for-me" in codex and "--add-dir" in codex
    claude = tpty.interactive_resume_argv("claude", "sid-1", alpha)
    assert claude[-2:] == ["--resume", "sid-1"] and "-p" not in claude and "bypassPermissions" in claude


def test_resume_in_worktree_takes_ticket_lock_without_ticket_field(env, monkeypatch):
    """I5-08: the server derives the ticket from the session folder."""
    app_mod, tpty, repos, tmp = env
    monkeypatch.setattr(tpty, "interactive_resume_argv", lambda *a: ["true"])  # no real agent CLI
    p = pj.get_project("alpha")
    with pj.ticket_lock("alpha", "T-3"):
        info = pj.create_worktree(p, "T-3")
    c = connect(app_mod)
    tab = open_tab(c, kind="resume", agent="claude", session_id="s", project_key="alpha", cwd=info["worktree"])
    assert tpty.TERMINALS[tab["term_id"]].ticket == "T-3"
    with pytest.raises(pj.TicketLocked):
        with pj.ticket_lock("alpha", "T-3"):
            pass
    out = c.emit("term_open", {"kind": "resume", "agent": "claude", "session_id": "s", "project_key": "alpha",
                               "cwd": str(tmp)}, callback=True)
    assert "outside project" in out["error"]


def test_confidential_tab_refused_and_handoff_withheld_when_records_unsafe(env, monkeypatch):
    """I6-04: PTY writers obey the record-location guard for confidential projects."""
    app_mod, tpty, repos, _ = env
    monkeypatch.setattr(app_mod, "_records_unsafe", lambda: "records outside the checkout")
    c = connect(app_mod)
    out = c.emit("term_open", {"kind": "shell", "project_key": "beta", "cols": 80, "rows": 24}, callback=True)
    assert "outside the checkout" in out["error"]
    a = open_tab(c, kind="shell", project_key="alpha")  # non-confidential: allowed
    logged = []
    monkeypatch.setattr(tpty, "_write_run_log", lambda *args, **kw: logged.append(kw["prompt"]))
    t = tpty.TERMINALS[a["term_id"]]
    t.project_key, t.pending_handoff = "beta", {"skill": "s", "run_id": "r"}  # registry says confidential
    tpty._record_pending_handoff(t, f"run {SENTINEL}", app_mod.socketio)
    assert logged and SENTINEL not in logged[0]


def test_project_tab_holds_the_project_lifecycle_lock(env):
    app_mod, tpty, repos, _ = env
    c = connect(app_mod)
    a = open_tab(c, kind="shell", project_key="alpha")
    with pytest.raises(pj.ProjectBusy):  # remove / lifecycle edits wait for the tab
        with pj.project_lock("alpha", exclusive=True, blocking=False):
            pass
    c.emit("term_close", {"term_id": a["term_id"]}, callback=True)
    with pj.project_lock("alpha", exclusive=True, blocking=False):  # released on close
        pass
