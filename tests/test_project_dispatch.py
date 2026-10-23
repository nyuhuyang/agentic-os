"""Phase 2: project-bound dispatch — argv policy, comment gate, location guard, the launch helper."""

import contextlib
import json
import os
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

RUNNER = Path(__file__).resolve().parents[1] / "runner"
sys.path.insert(0, str(RUNNER))
sys.path.insert(0, str(RUNNER.parent))

import projects as pj  # noqa: E402
import project_runs as pr  # noqa: E402

SENTINEL = "SENTINEL-CONFIDENTIAL-4242"
REAL_RECORD_PROBLEM = pj.record_location_problem


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


@pytest.fixture
def proj(tmp_path, monkeypatch):
    monkeypatch.setattr(pj, "WORKTREE_ROOT", tmp_path / "wt")
    repo = tmp_path / "demo"
    (repo / "tests").mkdir(parents=True)
    (repo / "tests" / "check.sh").write_text("test -f feature.txt\n")
    (repo / ".gitignore").write_text("data/\n")
    (repo / "README.md").write_text("r\n")
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@t.invalid")
    git(repo, "config", "user.name", "t")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "init")
    (repo / "data").mkdir()
    (repo / "data" / "secret.csv").write_text("s")
    reg = tmp_path / "projects.yaml"

    def write_registry(confidential=False):
        reg.write_text(f"projects:\n  demo:\n    path: {repo}\n    verify: sh tests/check.sh\n"
                       f"    seed: [data]\n    confidential: {str(confidential).lower()}\n    no_push: true\n")
    write_registry()
    monkeypatch.setattr(pj, "REGISTRY_PATH", reg)
    return repo, write_registry


def project(repo, confidential=False):
    return pj._parse_project("demo", {"path": str(repo), "verify": "sh tests/check.sh", "confidential": confidential})


# ── argv policy (Decision 9) ─────────────────────────────────────────────────

def cli(agent, repo, confidential):
    return pr.agent_cli(agent, project(repo, confidential), "claude", lambda: ["dsh", "--profile", "headless"])


def test_confidential_argv_has_no_bypass(proj):
    repo, _ = proj
    for agent in ("claude", "codex"):
        argv = cli(agent, repo, True)
        assert "--dangerously-bypass-approvals-and-sandbox" not in argv and "bypassPermissions" not in argv


def test_confidential_codex_pins_the_whole_policy(proj):
    repo, _ = proj
    argv = cli("codex", repo, True)
    assert 'approval_policy="never"' in argv
    assert "sandbox_workspace_write.network_access=false" in argv
    assert "sandbox_workspace_write.writable_roots=[]" in argv
    assert argv[argv.index("--add-dir") + 1] == str((repo / ".git").resolve())


def test_confidential_claude_settings_and_sources(proj):
    repo, _ = proj
    argv = cli("claude", repo, True)
    settings = json.loads(argv[argv.index("--settings") + 1])["sandbox"]
    assert settings["failIfUnavailable"] is True and settings["allowUnsandboxedCommands"] is False
    assert argv[argv.index("--setting-sources") + 1] == "user" and "--strict-mcp-config" in argv
    codex_home = Path.home() / ".codex"
    assert settings["network"]["allowedDomains"] == pr.CODEX_DOMAINS and settings["network"]["strictAllowlist"]
    assert str(codex_home) in settings["filesystem"]["allowWrite"]
    assert str(codex_home / "config.toml") in settings["filesystem"]["denyWrite"]


def test_sandboxed_codex_shim(tmp_path):
    """Passes through outside a sandbox; inside one (nested sandbox-exec refused) it drops Codex's
    own sandbox for the outer one and points Codex at the bundled CA file."""
    if sys.platform != "darwin":
        pytest.skip("macOS seatbelt only")
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "codex").write_text('#!/bin/sh\necho "$CODEX_CA_CERTIFICATE|$*"\n')
    (fake / "codex").chmod(0o755)
    env = {**os.environ, "PATH": f"{pr.SANDBOXED_BIN}:{fake}:/usr/bin:/bin"}
    env.pop("CODEX_CA_CERTIFICATE", None)
    run = lambda *argv: subprocess.run(argv, env=env, capture_output=True, text=True).stdout.strip()
    assert run("codex", "exec", "-s", "read-only", "-") == "|exec -s read-only -"
    jail = ["/usr/bin/sandbox-exec", "-p", "(version 1)(allow default)(deny mach-lookup)"]  # refuses nesting
    assert run(*jail, "codex", "exec", "-s", "read-only", "-") == (
        "/etc/ssl/cert.pem|exec --dangerously-bypass-approvals-and-sandbox -s read-only -")
    assert run(*jail, "codex", "exec", "resume", "sid", "-") == (
        "/etc/ssl/cert.pem|exec resume --dangerously-bypass-approvals-and-sandbox sid -")
    assert run(*jail, "codex", "--version") == "/etc/ssl/cert.pem|--version"


def test_confidential_claude_exec_env_puts_sandboxed_codex_first(monkeypatch):
    import app
    monkeypatch.setattr(app, "_registry_exec_env", lambda agent, reg: {"PATH": "/usr/bin"})
    monkeypatch.setattr(app, "_load_registry", lambda agent: {})
    project = SimpleNamespace(env={}, confidential=True)
    assert app._project_exec_env("claude", project)["PATH"] == f"{pr.SANDBOXED_BIN}{os.pathsep}/usr/bin"
    assert app._project_exec_env("codex", project)["PATH"] == "/usr/bin"
    assert app._project_exec_env("claude", SimpleNamespace(env={}, confidential=False))["PATH"] == "/usr/bin"


def test_non_confidential_codex_uses_auto_review_without_sandbox_flag(proj):
    repo, _ = proj
    argv = cli("codex", repo, False)
    assert "--approve-for-me" in argv and "--sandbox" not in argv
    assert not any("approval_policy" in a for a in argv)


def test_non_confidential_claude_and_dsh_unchanged(proj):
    repo, _ = proj
    assert cli("claude", repo, False) == ["claude", "-p", "--verbose", "--permission-mode", "bypassPermissions",
                                          *pr.CLAUDE_SETTINGS]
    assert cli("dsh", repo, False) == ["dsh", "--profile", "headless"]


def test_rejected_backends(proj, monkeypatch):
    repo, _ = proj
    with pytest.raises(pr.ProjectRunError, match="dsh is not allowed"):
        cli("dsh", repo, True)
    with pytest.raises(pr.ProjectRunError, match="cannot run project tickets"):
        cli("deepseek-direct", repo, False)
    monkeypatch.setattr(pr, "CONFIDENTIAL_SANDBOX_VERIFIED", False)
    with pytest.raises(pr.ProjectRunError, match="confidential dispatch is disabled"):
        cli("claude", repo, True)


# ── tracker comment gate (Decision 4) ────────────────────────────────────────

def test_confidential_comment_carries_no_sentinel():
    leak = lambda: f"prompt {SENTINEL} output {SENTINEL}"
    binding = {"confidential": True}
    for kind, status in (("Run", "review"), ("Run", "error"), ("Retry", "timeout")):
        body = pr.tracker_comment(binding, kind, run_id="r1", status=status,
                                  verify={"status": "fail", "exit": 1, "duration_s": 2.0},
                                  shortstat="1 file changed", fallback=leak)
        assert SENTINEL not in body and "verify: fail" in body
    assert pr.tracker_comment(binding, "feedback", run_id="r1", fallback=leak) is None
    assert pr.tracker_comment({"confidential": False}, "Run", run_id="r1", fallback=leak) == leak()


# ── location guard (Decision 4a) ─────────────────────────────────────────────

def _checkout(tmp_path):
    root = tmp_path / "aos"
    root.mkdir()
    (root / ".gitignore").write_text("state/\n")
    git(root, "init", "-q")
    git(root, "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
    git(root, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "i")
    (root / "state").mkdir()
    return root


def test_guard_refuses_unregistered_public_repo(proj, tmp_path):
    repo, _ = proj
    root = _checkout(tmp_path)
    other = tmp_path / "public"
    other.mkdir()
    git(other, "init", "-q")
    reg = {"demo": project(repo, True)}
    with pytest.raises(pj.ProjectError, match="outside"):
        pj.check_record_locations([other / "log.jsonl"], root, reg)


def test_guard_refuses_registered_project_tree(proj, tmp_path):
    repo, _ = proj
    with pytest.raises(pj.ProjectError):
        pj.check_record_locations([repo / "run_log.jsonl"], _checkout(tmp_path), {"demo": project(repo, True)})


def test_guard_accepts_default_state_dir(proj, tmp_path):
    repo, _ = proj
    root = _checkout(tmp_path)
    pj.check_record_locations([root / "state" / "run_log.jsonl", root / "state"], root, {"demo": project(repo, True)})


def test_guard_inactive_without_confidential_projects(proj, tmp_path):
    repo, _ = proj
    pj.check_record_locations([tmp_path / "anywhere.jsonl"], _checkout(tmp_path), {"demo": project(repo, False)})


def test_guard_refuses_info_exclude_only(proj, tmp_path):
    repo, _ = proj
    root = _checkout(tmp_path)
    (root / ".git" / "info" / "exclude").write_text("private/\n")
    with pytest.raises(pj.ProjectError, match="not ignored"):
        pj.check_record_locations([root / "private" / "log.jsonl"], root, {"demo": project(repo, True)})


# ── live run events ──────────────────────────────────────────────────────────

def test_run_agent_streams_events_before_exit(tmp_path):
    script = tmp_path / "agent.py"
    script.write_text(textwrap.dedent('''
        import json, sys, time
        for i in range(3):
            print(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": f"step {i}"}}), flush=True)
            time.sleep(0.4)
    '''))
    seen = []
    t0 = time.monotonic()
    lines, err, code, timed_out = pr.run_agent([sys.executable, str(script)], str(tmp_path), dict(os.environ),
                                               "run-x", "codex", 20, lambda ev, data: seen.append((time.monotonic() - t0, data["line"])))
    end = time.monotonic() - t0
    assert [line for _, line in seen] == ["step 0", "step 1", "step 2"]
    assert seen[0][0] < end - 0.5  # the first event arrived well before the agent exited
    assert pr.RUN_EVENTS["run-x"].snapshot() == ["step 0", "step 1", "step 2"]


# ── the launch helper, end to end with a fake agent ──────────────────────────

FAKE = textwrap.dedent('''
    import json, os, subprocess, sys
    mode = sys.argv[1]
    if mode in ("commit", "commit_and_bg", "touch_main"):
        open("feature.txt", "w").write("done")
        subprocess.run(["git", "add", "feature.txt"], check=True)
        subprocess.run(["git", "commit", "-qm", "feature"], check=True)
    if mode == "uncommitted":
        open("feature.txt", "w").write("done")
    if mode == "commit_and_bg":
        subprocess.Popen(["/bin/sh", "-c", f"sleep 2; touch {sys.argv[2]}"])
    if mode == "touch_main":
        open(os.path.join(sys.argv[2], "stray.txt"), "w").write("agent wrote here")
    if mode == "switch_branch":
        subprocess.run(["git", "checkout", "-q", "-b", "other"], check=True)
        open("feature.txt", "w").write("done")
    if mode == "stream":
        import time
        for i in range(10):
            print(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": f"s{i}"}]}}), flush=True)
            time.sleep(0.2)
        open("feature.txt", "w").write("done")
        subprocess.run(["git", "add", "feature.txt"], check=True)
        subprocess.run(["git", "commit", "-qm", "feature"], check=True)
    if mode == "silent":
        import time
        time.sleep(30)
    print(json.dumps({"type": "system", "session_id": "sess-1"}), flush=True)
    print(json.dumps({"type": "result", "result": "finished", "session_id": "sess-1",
                      "usage": {"input_tokens": 1, "output_tokens": 2}}), flush=True)
''')


@pytest.fixture
def helper(proj, tmp_path, monkeypatch):
    import app as app_mod
    import reset_gen
    repo, write_registry = proj
    monkeypatch.setattr(reset_gen, "GEN_PATH", tmp_path / "gens.json")
    for name, value in (("RUN_LOG", tmp_path / "run_log.jsonl"), ("STATE_RUN_LOG", tmp_path / "runs.jsonl"),
                        ("RUN_PROGRESS_DIR", tmp_path / "progress"), ("STATE_TASK_STATE", tmp_path / "ts.json"),
                        ("JOB_STATE", tmp_path / "js.json"), ("OUTPUTS_DIR", tmp_path / "out"),
                        ("STATE_DIR", tmp_path / "st")):
        monkeypatch.setattr(app_mod, name, value)
    monkeypatch.setattr(app_mod, "_load_registry", lambda agent: {})
    monkeypatch.setattr(pj, "record_location_problem", lambda paths, checkout: None)  # tmp records
    monkeypatch.setattr(app_mod, "_tracker_issue", lambda iid: {"id": iid})  # this fixture's cards are live (R2)
    events, comments, pushes = [], [], []
    monkeypatch.setattr(app_mod.socketio, "emit", lambda *a, **k: events.append(a))
    monkeypatch.setattr(app_mod, "_post_linear_comment", lambda i, b: comments.append(b))
    monkeypatch.setattr(app_mod, "_push_linear_state_async", lambda i, s, gen=None: pushes.append(s))
    fake = tmp_path / "fake_agent.py"
    fake.write_text(FAKE)
    state = {"mode": "commit", "arg": ""}
    monkeypatch.setattr(app_mod, "_project_cmd",
                        lambda agent, project, prompt, resume: [sys.executable, str(fake), state["mode"], state["arg"]])

    def run(agent="claude", ident="T-1", **kw):
        return app_mod._run_project_ticket(project_key="demo", ident=ident, agent=agent, prompt=f"do it {SENTINEL}",
                                           title="feature", run_id=kw.pop("run_id", f"run-{ident}"),
                                           linear_issue_id="iss" if ident == "T-1" else f"iss-{ident}",
                                           task_id="task" if ident == "T-1" else f"task-{ident}", launch_gen=0, **kw)

    def records():
        return [json.loads(l) for l in (tmp_path / "run_log.jsonl").read_text().splitlines()]
    return app_mod, run, records, state, events, comments, pushes, repo, write_registry


def test_dispatch_records_binding_verify_and_badge(helper):
    app_mod, run, records, state, events, comments, pushes, repo, _ = helper
    out = run()
    rec = records()[-1]
    assert rec["status"] == "review" and rec["project_key"] == "demo" and rec["branch"] == "agent/T-1"
    assert rec["worktree"].endswith("demo/T-1") and rec["base_sha"]
    assert rec["verify"]["status"] == "pass" and rec["verify_badge"] == "pass"
    assert "1 file changed" in rec["shortstat"] and rec["agent_session_id"] == "sess-1"
    assert pushes == ["review"] and comments  # non-confidential: today's comment body
    git(repo, "status", "--porcelain")  # main checkout untouched
    assert subprocess.run(["git", "-C", str(repo), "status", "--porcelain"], capture_output=True, text=True).stdout == ""


def test_sandboxed_codex_gets_a_runner_commit_without_the_seed(helper):
    app_mod, run, records, state, *_ = helper
    state["mode"] = "uncommitted"
    run(agent="codex")
    rec = records()[-1]
    assert rec["runner_commit"] and rec["verify"]["status"] == "pass" and rec["seed_committed"] == []
    names = subprocess.run(["git", "-C", rec["worktree"], "show", "--name-only", "--format=", rec["runner_commit"]],
                           capture_output=True, text=True).stdout.split()
    assert names == ["feature.txt"]


def test_successful_run_is_merged_into_the_main_checkout(helper):
    """AGE-111: the user sees a finished ticket in the main checkout without merging by hand."""
    app_mod, run, records, state, *_, repo, write_registry = helper
    run()
    rec = records()[-1]
    assert rec["merged"] == ["T-1"] and rec["verify_badge"] == "pass"
    assert (repo / "feature.txt").read_text() == "done"


def test_failed_run_is_not_merged(helper, monkeypatch):
    app_mod, run, records, state, *_, repo, write_registry = helper
    state["mode"] = "silent"
    monkeypatch.setattr(app_mod, "AI_RUN_TIMEOUT_S", 1)
    run()
    rec = records()[-1]
    assert "merged" not in rec and not (repo / "feature.txt").exists()


def test_merge_waits_for_the_projects_other_runs(helper, monkeypatch):
    """A merge under another run would read as that run changing the main checkout."""
    app_mod, *_ = helper
    p = SimpleNamespace(key="demo", auto_merge=True)
    merged = []
    monkeypatch.setattr(pj, "merge_into_checkout", lambda project, t, sha=None: merged.append((t, sha)) or "sha")
    monkeypatch.setattr(pj, "branch_head", lambda project, t: f"head-of-{t}")
    checked = []
    monkeypatch.setattr(pj, "check_queued_merge", lambda project, t, sha: checked.append(t))
    a, b = {"project_key": "demo"}, {"project_key": "demo"}
    monkeypatch.setattr(app_mod, "_running_jobs", {"a": a, "b": b, "c": {"project_key": "other"}})
    assert app_mod._merge_when_last(p, "T-1", a, eligible=True) == {"merge": "waiting for this project's other runs"}
    assert merged == []
    assert app_mod._merge_when_last(p, "T-2", b, eligible=True) == {"merged_head": "sha", "merged": ["T-1", "T-2"]}
    assert merged == [("T-1", "head-of-T-1"), ("T-2", "head-of-T-2")]  # the verified commits, not branch tips (SC-007)
    assert checked == ["T-1", "T-2"]  # every queued entry re-checked before it merges (SC-009)
    assert app_mod._merge_when_last(SimpleNamespace(key="demo", auto_merge=False), "T-3", b, eligible=True) == {}


def test_queued_merge_waits_for_a_finalizing_ticket_then_keeps_it(helper, monkeypatch):
    """SC-010: a queued ticket whose run still holds its lock is waited for, and kept (not dropped) on timeout."""
    app_mod, *_ = helper
    p = SimpleNamespace(key="demo", auto_merge=True)
    merged = []
    monkeypatch.setattr(pj, "merge_into_checkout", lambda project, t, sha=None: merged.append(t) or "sha")
    monkeypatch.setattr(pj, "branch_head", lambda project, t: f"head-of-{t}")
    monkeypatch.setattr(pj, "check_queued_merge", lambda project, t, sha: None)
    monkeypatch.setattr(app_mod, "_PENDING_MERGES", {"demo": [("T-1", "head-of-T-1")]})
    b = {"project_key": "demo"}
    monkeypatch.setattr(app_mod, "_running_jobs", {"b": b})
    real = app_mod._wait_ticket_lock
    monkeypatch.setattr(app_mod, "_wait_ticket_lock", lambda key, t: real(key, t, timeout=0.6))
    with pj.ticket_lock("demo", "T-1"):  # T-1's run is still finalizing
        out = app_mod._merge_when_last(p, "T-2", b, eligible=True)
    assert merged == ["T-2"] and "T-1 waits for this project's next run" in out["merge"]
    assert app_mod._PENDING_MERGES["demo"] == [("T-1", "head-of-T-1")]  # kept for the next run


def test_queued_merge_uses_each_tickets_own_policy_and_newest_entry(helper, monkeypatch):
    """SC-012: a confidential ticket drained by a public one merges under its own policy.
    SC-013: a timed-out old entry never displaces a newer verification of the same ticket."""
    app_mod, *_ = helper
    p = SimpleNamespace(key="demo", auto_merge=True, confidential=False)
    seen = []
    monkeypatch.setattr(pj, "merge_into_checkout", lambda project, t, sha=None: seen.append((t, project.confidential)) or "sha")
    monkeypatch.setattr(pj, "branch_head", lambda project, t: f"head-of-{t}")
    monkeypatch.setattr(pj, "check_queued_merge", lambda project, t, sha: None)
    monkeypatch.setattr(app_mod, "_ticket_confidential", lambda key, ident, *a: ident == "T-1")
    monkeypatch.setattr(app_mod.dataclasses, "replace", lambda obj, **kw: SimpleNamespace(**{**vars(obj), **kw}))
    monkeypatch.setattr(app_mod, "_PENDING_MERGES", {"demo": [("T-1", "old")]})
    b = {"project_key": "demo"}
    monkeypatch.setattr(app_mod, "_running_jobs", {"b": b})
    app_mod._merge_when_last(p, "T-2", b, eligible=True)
    assert ("T-1", True) in seen and ("T-2", False) in seen
    # SC-013: T-1 busy until timeout, while a newer T-1 verification is already queued again
    seen.clear()
    monkeypatch.setattr(app_mod, "_PENDING_MERGES", {"demo": [("T-1", "old")]})
    real = app_mod._wait_ticket_lock

    def slow(key, t):
        app_mod._PENDING_MERGES.setdefault("demo", []).append(("T-1", "new"))  # T-1 re-ran and queued meanwhile
        return real(key, t, timeout=0.3)

    monkeypatch.setattr(app_mod, "_wait_ticket_lock", slow)
    b2 = {"project_key": "demo"}
    monkeypatch.setattr(app_mod, "_running_jobs", {"b2": b2})
    with pj.ticket_lock("demo", "T-1"):
        app_mod._merge_when_last(p, "T-3", b2, eligible=True)
    assert app_mod._PENDING_MERGES["demo"] == [("T-1", "new")]


def test_queued_merge_deferred_when_a_run_starts_during_the_wait(helper, monkeypatch):
    """SC-016: a run admitted while the drain waited keeps the queued entry from merging under it."""
    app_mod, *_ = helper
    p = SimpleNamespace(key="demo", auto_merge=True, confidential=False)
    merged = []
    monkeypatch.setattr(pj, "merge_into_checkout", lambda project, t, sha=None: merged.append(t) or "sha")
    monkeypatch.setattr(pj, "branch_head", lambda project, t: f"head-of-{t}")
    monkeypatch.setattr(pj, "check_queued_merge", lambda project, t, sha: None)
    monkeypatch.setattr(app_mod, "_PENDING_MERGES", {"demo": [("T-1", "v1")]})
    b = {"project_key": "demo"}
    jobs = {"b": b}
    monkeypatch.setattr(app_mod, "_running_jobs", jobs)
    real = app_mod._wait_ticket_lock

    @contextlib.contextmanager
    def admitting(key, t):
        jobs["c"] = {"project_key": "demo"}  # a new run takes its fingerprint during the wait
        with real(key, t, timeout=0.3):
            yield

    monkeypatch.setattr(app_mod, "_wait_ticket_lock", admitting)
    out = app_mod._merge_when_last(p, "T-2", b, eligible=True)
    assert merged == []  # neither T-1 nor the drainer's own T-2 merges under T-3's fingerprint (SC-018)
    assert app_mod._PENDING_MERGES["demo"] == [("T-1", "v1"), ("T-2", "head-of-T-2")]
    assert "waits for this project's next run" in out["merge"]


def test_run_fingerprint_waits_for_a_merge_holding_the_gate(helper, monkeypatch):
    """SC-019: a merge blocked on the global merge lock still holds its project's gate, so a run
    admitted meanwhile fingerprints only after the merge completed."""
    app_mod, *_ = helper
    p = SimpleNamespace(key="demo", auto_merge=True, confidential=False)
    order = []
    release = threading.Event()

    def slow_merge(project, t, sha=None):
        order.append("merge-start")
        release.wait(2)  # e.g. waiting on _MERGE_LOCK held by a manual commit elsewhere
        order.append("merge-end")
        return "sha"

    monkeypatch.setattr(pj, "merge_into_checkout", slow_merge)
    monkeypatch.setattr(pj, "branch_head", lambda project, t: f"head-of-{t}")
    monkeypatch.setattr(pj, "check_queued_merge", lambda project, t, sha: None)
    monkeypatch.setattr(app_mod, "_PENDING_MERGES", {})
    b = {"project_key": "demo"}
    monkeypatch.setattr(app_mod, "_running_jobs", {"b": b})
    drain = threading.Thread(target=app_mod._merge_when_last, args=(p, "T-2", b, True))
    drain.start()
    while "merge-start" not in order:
        time.sleep(0.01)

    def admit():
        with app_mod._merge_gate("demo"):  # what a new run's opening fingerprint takes
            order.append("fingerprint")

    t3 = threading.Thread(target=admit)
    t3.start()
    time.sleep(0.2)
    assert "fingerprint" not in order  # blocked behind the merge
    release.set()
    drain.join(5); t3.join(5)
    assert order == ["merge-start", "merge-end", "fingerprint"]


def test_background_writer_is_gone_before_verify(helper, tmp_path):
    app_mod, run, records, state, *_ = helper
    marker = tmp_path / "late-write"
    state["mode"], state["arg"] = "commit_and_bg", str(marker)
    run()
    time.sleep(3)
    assert not marker.exists()


def test_cancelled_run_leaves_no_process_and_no_second_record(helper, tmp_path, monkeypatch):
    app_mod, run, records, state, *_ = helper
    marker = tmp_path / "late-write-cancel"
    script = tmp_path / "slow.py"
    script.write_text(f"import subprocess, time\nsubprocess.Popen(['/bin/sh', '-c', 'sleep 3; touch {marker}'])\ntime.sleep(30)\n")
    monkeypatch.setattr(app_mod, "_project_cmd", lambda *a: [sys.executable, str(script)])
    t = threading.Thread(target=run, kwargs={"run_id": "run-cancel"})
    t.start()
    for _ in range(100):
        if "run-cancel" in app_mod._running_procs:
            break
        time.sleep(0.1)
    client = app_mod.app.test_client()
    client.environ_base["HTTP_X_AGENTICOS_TOKEN"] = app_mod.REQUEST_TOKEN
    assert client.delete("/api/runs/run-cancel").status_code == 200
    t.join(20)
    time.sleep(4)
    assert not marker.exists()
    recs = [r for r in records() if r["run_id"] == "run-cancel"]
    assert [r["status"] for r in recs] == ["cancelled"]
    # I5-01: the cancel record keeps binding, agent and ancestry, so a retry stays bound
    assert recs[0]["project_key"] == "demo" and recs[0]["agent"] == "claude" and recs[0]["task_id"] == "task"


def test_main_checkout_write_is_flagged(helper):
    app_mod, run, records, state, events, comments, pushes, repo, _ = helper
    state["mode"], state["arg"] = "touch_main", str(repo)
    run()
    rec = records()[-1]
    assert rec["main_checkout_changed"] is True and rec["verify_badge"] == "main checkout changed"


def test_confidential_comment_and_record_location(helper):
    app_mod, run, records, state, events, comments, pushes, repo, write_registry = helper
    write_registry(confidential=True)
    run()
    assert comments and all(SENTINEL not in c for c in comments)
    assert SENTINEL in records()[-1]["prompt"]  # the full payload stays in the local run record


def test_retry_after_label_change_keeps_original_binding(helper):
    app_mod, run, records, *_ = helper
    run()
    out = run(reuse_only=True, run_id="run-retry", resume_session=None)
    rec = records()[-1]
    assert rec["run_id"] == "run-retry" and rec["project_key"] == "demo" and rec["branch"] == "agent/T-1"


def test_missing_worktree_fails_closed(helper):
    app_mod, run, records, *_ = helper
    out = run(ident="T-9", reuse_only=True)
    rec = records()[-1]
    assert rec["status"] == "error" and "bound worktree is missing" in rec["error"]
    assert not (pj.WORKTREE_ROOT / "demo" / "T-9").exists()


def test_concurrent_launch_of_same_ticket_rejected(helper):
    app_mod, run, records, *_ = helper
    with pj.ticket_lock("demo", "T-1"):
        run()
    rec = records()[-1]
    assert rec["status"] == "error" and "is busy" in rec["error"]


def test_cleanup_while_locked_rejected(proj):
    repo, _ = proj
    with pj.ticket_lock("demo", "T-1"):
        assert pj.main(["cleanup", "demo", "T-1"]) == 2


def test_confidential_verify_cannot_write_the_shared_git_dir(proj):
    repo, _ = proj
    p = project(repo, True)
    with pj.ticket_lock("demo", "T-1"):
        info = pj.create_worktree(p, "T-1")
    roots = [r.resolve() for r in pj.verify_writable_roots(Path(info["worktree"]))]
    common = (repo / ".git").resolve()
    assert Path(info["worktree"]).resolve() in roots
    assert all(r == common / "worktrees" / "T-1" or not r.is_relative_to(common) for r in roots)
    assert common not in roots and (common / "hooks") not in roots


def test_non_confidential_verify_hook_caught_by_closing_fingerprint(proj, tmp_path):
    repo, _ = proj
    (repo / "tests" / "check.sh").write_text(f"echo evil > {repo}/.git/hooks/post-commit; true\n")
    git(repo, "commit", "-qam", "evil verify")
    p = project(repo, False)
    with pj.ticket_lock("demo", "T-1"):
        info = pj.create_worktree(p, "T-1")
    before = pj.fingerprint(p)
    binding = {"worktree": info["worktree"], "base_sha": info["base_sha"], "issue_identifier": "T-1", "branch": info["branch"]}
    result = pr.post_run(p, binding, "claude", "t", before, set())
    assert result["main_checkout_changed"] is True and result["verify_badge"] == "main checkout changed"


def test_runner_bookkeeping_in_own_checkout_does_not_trip_fingerprint(proj):
    """A run in another project writes the runner's state/ (here: inside a registered checkout)."""
    repo, _ = proj
    (repo / ".gitignore").write_text("data/\nstate/\n")
    git(repo, "commit", "-qam", "ignore state")
    (repo / "state").mkdir()
    p = project(repo)
    exclude = pr.bookkeeping_paths(p, [repo / "state"])
    before = pj.fingerprint(p, exclude=exclude)
    (repo / "state" / "run_log.jsonl").write_text("another project's run\n")
    (repo / "state" / "tasks.json.lock").write_text("")
    assert pj.fingerprint(p, exclude=exclude) == before
    (repo / "data" / "new.csv").write_text("but other ignored files still count")
    assert pj.fingerprint(p, exclude=exclude) != before


@pytest.mark.parametrize("ignored", [True, False])
def test_claude_settings_staging_dir_does_not_trip_fingerprint(proj, ignored):
    """Claude Code makes an empty .claude/.cc-writes/ in the main checkout. Only that empty dir
    is ignored: its contents, a file or symlink in its place, and settings files still count."""
    repo, _ = proj
    if ignored:
        (repo / ".gitignore").write_text("data/\n.claude/\n")
        git(repo, "commit", "-qam", "ignore .claude")
    (repo / ".claude").mkdir()
    (repo / ".claude" / "settings.local.json").write_text("{}")
    p = project(repo)
    before = pj.fingerprint(p)
    staging = repo / ".claude" / ".cc-writes"
    staging.mkdir()
    assert pj.fingerprint(p) == before
    (staging / "left.txt").write_text("persistent")
    assert pj.fingerprint(p) != before
    (staging / "left.txt").unlink()
    staging.rmdir()
    staging.write_text("a file in its place")
    assert pj.fingerprint(p) != before
    staging.unlink()
    staging.symlink_to(repo / "data")
    assert pj.fingerprint(p) != before
    staging.unlink()
    assert pj.fingerprint(p) == before
    (repo / ".claude" / "settings.local.json").write_text('{"x": 1}')
    assert pj.fingerprint(p) != before


# ── build inspection 5 regressions ───────────────────────────────────────────

def api(app_mod):
    client = app_mod.app.test_client()
    client.environ_base["HTTP_X_AGENTICOS_TOKEN"] = app_mod.REQUEST_TOKEN
    return client


def wait_for(cond, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.05)
    return False


def test_retry_of_unbound_record_uses_durable_binding(helper, monkeypatch):
    """I5-01: a record written without the binding (old cancel/stall) never retries at the root."""
    app_mod, run, records, *_ = helper
    run()
    with app_mod.RUN_LOG.open("a") as f:
        f.write(json.dumps({"run_id": "old-stall", "status": "stalled", "task_id": "task", "skill": "_prompt",
                            "linear_issue_id": "iss", "prompt": "p"}) + "\n")
    seen = {}
    monkeypatch.setattr(app_mod, "_run_project_ticket", lambda **kw: seen.update(kw))
    assert api(app_mod).post("/api/runs/old-stall/retry", json={}).status_code == 200
    assert wait_for(lambda: seen)
    assert seen["project_key"] == "demo" and seen["reuse_only"] and seen["confidential"] is False


def test_unresolved_binding_never_posts_raw_comment(helper):
    """I5-02: registry lookup failing for a bound (or once-confidential) ticket -> template only."""
    app_mod, run, records, state, events, comments, *_ = helper
    pj.REGISTRY_PATH.write_text("projects: {}\n")
    run(confidential=True)
    run(run_id="run-unknown")  # confidentiality unknown
    assert len(comments) == 2 and all(SENTINEL not in c for c in comments)
    assert records()[-1]["status"] == "error"


def test_bound_issue_redispatch_ignores_label_changes(helper, monkeypatch):
    """I5-03: removing or changing the label of a bound issue changes nothing."""
    import runner.modules.linear as lin
    app_mod, run, records, state, events, comments, pushes, repo, write_registry = helper
    write_registry(confidential=True)
    run()
    write_registry(confidential=False)
    seen = []
    monkeypatch.setattr(app_mod, "_run_project_ticket", lambda **kw: seen.append(kw))
    mod = lin.LinearModule()
    monkeypatch.setattr(mod, "push_state", lambda *a, **k: None)
    stub = type("S", (), {"emit": lambda *a, **k: None})()
    for labels in ([], [{"name": "project:other"}]):
        mod._dispatch_issue({"id": "iss", "identifier": "T-1", "title": "t", "labels": labels}, {}, stub)
    assert [(k["project_key"], k["ident"], k["confidential"]) for k in seen] == [("demo", "T-1", True)] * 2
    assert mod._is_confidential_issue("iss")  # label gone, still confidential


def test_confidential_launch_refused_when_records_could_leak(helper, monkeypatch):
    """I5-04: the record-location guard runs on every confidential launch, not just at startup."""
    app_mod, run, records, state, events, comments, pushes, repo, write_registry = helper
    monkeypatch.setattr(pj, "record_location_problem", REAL_RECORD_PROBLEM)
    write_registry(confidential=True)
    run()
    rec = records()[-1]
    assert rec["status"] == "error" and "outside" in rec["error"]
    assert SENTINEL not in json.dumps(rec) and not (pj.WORKTREE_ROOT / "demo" / "T-1").exists()


def test_streaming_run_is_not_stalled_but_a_silent_one_is(helper, monkeypatch):
    """I5-07: streamed agent events count as progress; a stalled project run keeps its binding."""
    from runner.modules.stall_detection import check_once
    app_mod, run, records, state, *_ = helper
    monkeypatch.setattr(app_mod, "STALL_TIMEOUT_S", 2.0)  # > a loaded machine's commit + verify gap; silent sleeps 30 s
    for mode, ident, want in (("stream", "T-1", "review"), ("silent", "T-2", "stalled")):
        state["mode"] = mode
        t = threading.Thread(target=run, kwargs={"ident": ident, "run_id": f"run-{mode}"})
        t.start()
        while t.is_alive():
            check_once(app_mod, app_mod.socketio)
            t.join(0.1)
        rec = [r for r in records() if r["run_id"] == f"run-{mode}"]
        assert [r["status"] for r in rec] == [want] and rec[0]["project_key"] == "demo", rec


def test_cancel_during_verify_is_final(helper, tmp_path):
    """I5-09: cancel kills the verifier and no completion effect follows."""
    app_mod, run, records, state, events, comments, pushes, repo, _ = helper
    pj.REGISTRY_PATH.write_text(pj.REGISTRY_PATH.read_text().replace("sh tests/check.sh", "sleep 30"))
    t = threading.Thread(target=run, kwargs={"run_id": "run-v"})
    t.start()
    assert wait_for(lambda: app_mod._running_jobs.get("run-v", {}).get("phase") == "post_run"
                    and "run-v" in app_mod._running_procs)
    pid = app_mod._running_procs["run-v"].pid
    t0 = time.monotonic()
    assert api(app_mod).delete("/api/runs/run-v").status_code == 200
    t.join(20)
    assert time.monotonic() - t0 < 15
    with pytest.raises(ProcessLookupError):
        os.killpg(pid, 0)
    assert [r["status"] for r in records() if r["run_id"] == "run-v"] == ["cancelled"]
    assert comments == [] and pushes == ["review"]  # I6-06 rejected: cancel parks the ticket In Review


def test_runner_commit_refused_after_branch_switch(helper):
    """I5-10: the runner never commits onto a branch other than agent/<id>."""
    app_mod, run, records, state, *_ = helper
    state["mode"] = "switch_branch"
    run(agent="codex")
    rec = records()[-1]
    assert rec["status"] == "error" and "not agent/T-1" in rec["error"]
    other = subprocess.run(["git", "-C", rec["worktree"], "rev-parse", "other"], capture_output=True, text=True).stdout.strip()
    assert other == rec["base_sha"] and "main_checkout_changed" in rec


def test_uncommitted_work_is_committed_by_the_runner(helper):
    """AGE-111: an agent that forgets to commit still leaves its work on the branch."""
    app_mod, run, records, state, *_ = helper
    state["mode"] = "uncommitted"
    run(agent="claude")
    rec = records()[-1]
    assert rec["runner_commit"] and rec["uncommitted"] == []
    assert rec["verify"]["status"] == "pass" and rec["verify_badge"] == "pass"


def test_seed_committed_by_verify_is_caught(helper):
    """I5-14: the seed-history scan runs after verify."""
    app_mod, run, records, *_ = helper
    pj.REGISTRY_PATH.write_text(pj.REGISTRY_PATH.read_text().replace(
        "sh tests/check.sh", "git add -f -A && git commit -qm seed && test -f feature.txt"))
    run()
    rec = records()[-1]
    assert rec["seed_committed"] and rec["verify_badge"] == "seed committed"


def test_shutdown_kills_in_flight_agent(helper, tmp_path, monkeypatch):
    """I5-12: runner shutdown reaps project agents and refuses new launches."""
    app_mod, run, records, state, *_ = helper
    state["mode"] = "silent"
    t = threading.Thread(target=run, kwargs={"run_id": "run-sd"})
    t.start()
    assert wait_for(lambda: "run-sd" in app_mod._running_procs)
    pid = app_mod._running_procs["run-sd"].pid
    try:
        app_mod._stop_project_runs()
        with pytest.raises(ProcessLookupError):
            os.killpg(pid, 0)
        t.join(20)
        assert run(ident="T-2", run_id="run-late")["error"] == "runner is shutting down"
        with pytest.raises(pj.ProjectError):  # no new process of any kind (I6-08)
            pj._git(Path("."), "status")
    finally:
        app_mod._SHUTTING_DOWN.clear()
        pj.STOPPING.clear()


# ── build inspection 6 regressions ───────────────────────────────────────────

def test_binding_persisted_before_the_agent_starts(helper, monkeypatch):
    """I6-01: while the first run is still going, the issue is already bound (and confidential)."""
    import runner.modules.linear as lin
    app_mod, run, records, state, events, comments, pushes, repo, write_registry = helper
    write_registry(confidential=True)
    state["mode"] = "silent"
    t = threading.Thread(target=run, kwargs={"run_id": "run-first"})
    t.start()
    try:
        assert wait_for(lambda: "run-first" in app_mod._running_procs)
        b = app_mod._durable_binding(linear_issue_id="iss")
        assert b["project_key"] == "demo" and b["confidential"] is True and b["worktree"]
        assert lin.LinearModule()._is_confidential_issue("iss")  # no label in the cache at all
    finally:
        app_mod._signal_project_run("run-first", "cancelled")
        t.join(20)


def test_sticky_confidentiality_keeps_the_sandboxed_policy(helper, monkeypatch):
    """I6-02: registry flag dropped later -> the ticket still gets the confidential argv and verify."""
    app_mod, run, records, state, events, comments, pushes, repo, write_registry = helper
    write_registry(confidential=True)
    run()
    write_registry(confidential=False)
    seen = []
    monkeypatch.setattr(app_mod, "_project_cmd", lambda agent, project, prompt, resume: (
        seen.append(project.confidential), [sys.executable, "-c", "pass"])[1])
    run(run_id="run-2")
    assert seen == [True] and records()[-1]["confidential"] is True and all(SENTINEL not in c for c in comments)


def test_retry_feedback_uses_current_confidentiality(helper, monkeypatch):
    """I6-03: project became confidential after the first run -> feedback is not posted."""
    app_mod, run, records, state, events, comments, pushes, repo, write_registry = helper
    run()
    write_registry(confidential=True)
    monkeypatch.setattr(app_mod, "_run_project_ticket", lambda **kw: None)
    comments.clear()
    rid = records()[-1]["run_id"]
    assert api(app_mod).post(f"/api/runs/{rid}/retry", json={"reply": f"private {SENTINEL}"}).status_code == 200
    assert all(SENTINEL not in c for c in comments)


def test_unsafe_records_keep_no_raw_error(helper, monkeypatch):
    """I6-05: a refused confidential launch records a fixed error, not exception text."""
    app_mod, run, records, state, events, comments, pushes, repo, write_registry = helper
    monkeypatch.setattr(pj, "record_location_problem", REAL_RECORD_PROBLEM)
    pj.REGISTRY_PATH.write_text(f"projects:\n  demo:\n    path: {repo}\n    confidential: true\n    verify: [{SENTINEL}\n")
    run(confidential=True)
    rec = records()[-1]
    assert rec["status"] == "error" and rec["error"].startswith("withheld") and SENTINEL not in json.dumps(rec)


def test_cancel_escalates_to_sigkill(helper, tmp_path, monkeypatch):
    """I6-07: an agent ignoring SIGTERM is killed within seconds, not at the run timeout."""
    app_mod, run, records, *_ = helper
    script = tmp_path / "stubborn.py"
    script.write_text("import signal, time\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\ntime.sleep(60)\n")
    monkeypatch.setattr(app_mod, "_project_cmd", lambda *a: [sys.executable, str(script)])
    t = threading.Thread(target=run, kwargs={"run_id": "run-stub"})
    t.start()
    assert wait_for(lambda: "run-stub" in app_mod._running_procs)
    time.sleep(0.5)  # let it install the handler
    t0 = time.monotonic()
    app_mod._signal_project_run("run-stub", "cancelled")
    t.join(30)
    assert not t.is_alive() and time.monotonic() - t0 < 15
    assert [r["status"] for r in records() if r["run_id"] == "run-stub"] == ["cancelled"]


def test_dirty_after_verify_is_badged(helper):
    """I6-09: verify regenerating a tracked file leaves the badge non-green."""
    app_mod, run, records, *_ = helper
    pj.REGISTRY_PATH.write_text(pj.REGISTRY_PATH.read_text().replace(
        "sh tests/check.sh", "sh tests/check.sh && echo regen >> README.md"))
    run()
    rec = records()[-1]
    assert rec["verify"]["status"] == "pass" and rec["verify_badge"] == "uncommitted changes"
    assert rec["uncommitted"] == ["README.md"]


def test_redispatch_never_recreates_a_removed_worktree(helper, monkeypatch):
    """I6-10: after cleanup, a bound issue fails closed instead of starting from current HEAD."""
    import runner.modules.linear as lin
    app_mod, run, records, *_ = helper
    run()
    assert pj.main(["cleanup", "demo", "T-1"]) == 0
    mod = lin.LinearModule()
    monkeypatch.setattr(mod, "push_state", lambda *a, **k: None)
    mod._dispatch_issue({"id": "iss", "identifier": "T-1", "title": "t", "labels": []}, {},
                        type("S", (), {"emit": lambda *a, **k: None})())
    rec = records()[-1]
    assert rec["status"] == "error" and "bound worktree is missing" in rec["error"]
    assert not (pj.WORKTREE_ROOT / "demo" / "T-1").exists()


def test_cancelled_run_still_checks_the_main_checkout(helper, monkeypatch, tmp_path):
    """I6-13: cancel skips verify but not the closing fingerprint."""
    app_mod, run, records, state, events, comments, pushes, repo, _ = helper
    script = tmp_path / "touch_then_wait.py"
    script.write_text(f"import time\nopen({str(repo / 'stray.txt')!r}, 'w').write('x')\ntime.sleep(30)\n")
    monkeypatch.setattr(app_mod, "_project_cmd", lambda *a: [sys.executable, str(script)])
    t = threading.Thread(target=run, kwargs={"run_id": "run-c"})
    t.start()
    assert wait_for(lambda: (repo / "stray.txt").exists())
    app_mod._signal_project_run("run-c", "cancelled")
    t.join(20)
    rec = records()[-1]
    assert rec["status"] == "cancelled" and rec["main_checkout_changed"] is True
    assert rec["verify_badge"] == "main checkout changed"


def test_declared_confidentiality_counts_even_for_invalid_entries(tmp_path):
    """I6-04: the startup guard sees `confidential` on entries that fail validation."""
    reg = tmp_path / "p.yaml"
    reg.write_text("projects:\n  bad:\n    confidential: true\n")  # no path: invalid entry
    assert pj.declares_confidential(reg) and pj.load_registry(reg, errors={}) == {}
    reg.write_text("projects:\n  ok:\n    path: /x\n    verify: 'true'\n")
    assert not pj.declares_confidential(reg)
    reg.write_text("projects: [unclosed\n")
    assert pj.declares_confidential(reg)  # unreadable: fail closed


# ── build inspection 7 regressions ───────────────────────────────────────────

def test_cli_verify_keeps_sticky_confidentiality(helper, monkeypatch):
    """I7-02: `projects.py verify` sandboxes a ticket that ran confidential, whatever the registry says now."""
    app_mod, run, records, state, events, comments, pushes, repo, write_registry = helper
    write_registry(confidential=True)
    run()
    write_registry(confidential=False)
    sandboxed = []
    monkeypatch.setattr(pj, "sandbox_prefix", lambda roots: (sandboxed.append(roots), [])[1])
    assert pj.main(["verify", "demo", "--worktree", records()[-1]["worktree"]]) == 0
    assert sandboxed


def test_shutdown_finalizes_a_confidential_run_without_git(helper, monkeypatch):
    """I7-03: after stop_all() the location check cannot run git: the record is still written, redacted,
    before shutdown returns."""
    app_mod, run, records, state, events, comments, pushes, repo, write_registry = helper
    write_registry(confidential=True)
    monkeypatch.setattr(pj, "record_location_problem",
                        lambda paths, checkout: (pj._git(Path("."), "rev-parse", "HEAD"), None)[1])
    state["mode"] = "silent"
    t = threading.Thread(target=run, kwargs={"run_id": "run-cs"})
    t.start()
    try:
        assert wait_for(lambda: "run-cs" in app_mod._running_procs)
        app_mod._stop_project_runs()
        rec = [r for r in records() if r["run_id"] == "run-cs"]  # written before stop returned
        assert [r["status"] for r in rec] == ["cancelled"] and SENTINEL not in json.dumps(rec)
        assert rec[0]["verify_badge"] == "main checkout unchecked"  # git refused: fail closed
    finally:
        t.join(20)
        app_mod._SHUTTING_DOWN.clear()
        pj.STOPPING.clear()


def test_relocated_worktree_root_is_refused(helper, monkeypatch, tmp_path):
    """I7-06: the whole persisted binding must match, not just the base commit."""
    app_mod, run, records, *_ = helper
    run()
    assert pj.main(["cleanup", "demo", "T-1"]) == 0  # branch gone; HEAD unchanged
    monkeypatch.setattr(pj, "WORKTREE_ROOT", tmp_path / "elsewhere")
    run(run_id="run-moved")
    rec = records()[-1]
    assert rec["status"] == "error" and "differs from the first run" in rec["error"]


def test_failed_closing_snapshot_is_recorded(helper, monkeypatch):
    """I7-07: a closing fingerprint that fails is recorded and badges the run, on success and cancel."""
    app_mod, run, records, state, *_ = helper
    def flaky(project, exclude=frozenset()):  # the opening uses fingerprint_parts: only the closing fails (AGE-124)
        raise pj.ProjectError("index is corrupt")
    monkeypatch.setattr(pj, "fingerprint", flaky)
    run()
    rec = records()[-1]
    assert rec["main_checkout_changed"] is None and rec["verify_badge"] == "main checkout unchecked"
    assert "index is corrupt" in rec["closing_check_error"]
    state["mode"] = "silent"
    t = threading.Thread(target=run, kwargs={"ident": "T-2", "run_id": "run-cx"})
    t.start()
    assert wait_for(lambda: "run-cx" in app_mod._running_procs)
    app_mod._signal_project_run("run-cx", "cancelled")
    t.join(20)
    rec = records()[-1]
    assert rec["status"] == "cancelled" and rec["verify_badge"] == "main checkout unchecked"


# ── build inspection 8 regressions ───────────────────────────────────────────

def test_cli_made_confidential_worktree_stays_confidential(helper, monkeypatch):
    """I8-01: a worktree created confidential (CLI) keeps the sandboxed policy for dispatch and resume."""
    import runner.modules.pty as tpty
    app_mod, run, records, state, events, comments, pushes, repo, write_registry = helper
    write_registry(confidential=True)
    with pj.ticket_lock("demo", "T-1"):
        pj.create_worktree(pj.get_project("demo"), "T-1")
    write_registry(confidential=False)
    seen = []
    monkeypatch.setattr(app_mod, "_project_cmd", lambda agent, project, prompt, resume: (
        seen.append(project.confidential), [sys.executable, "-c", "pass"])[1])
    run()
    assert seen == [True] and records()[-1]["confidential"] is True and all(SENTINEL not in c for c in comments)
    argv = []
    monkeypatch.setattr(tpty, "_spawn", lambda t, a, *rest: argv.append(a))
    monkeypatch.setattr(tpty, "interactive_resume_argv", lambda agent, sid, project: ["x", str(project.confidential)])
    info = tpty.open_terminal({"kind": "resume", "agent": "claude", "session_id": "s", "project_key": "demo",
                               "cwd": str(pj.WORKTREE_ROOT / "demo" / "T-1")}, app_mod.socketio)
    tpty.TERMINALS.pop(info["term_id"]).holds.close()
    assert "True" in argv[0][-1]


def test_cancel_before_verify_keeps_the_safety_badge(proj, monkeypatch):
    """I8-05: a cancel before verify still badges a failed closing snapshot."""
    repo, _ = proj
    p = project(repo)
    with pj.ticket_lock("demo", "T-1"):
        info = pj.create_worktree(p, "T-1")
    binding = {"worktree": info["worktree"], "base_sha": info["base_sha"], "issue_identifier": "T-1", "branch": info["branch"]}
    monkeypatch.setattr(pj, "fingerprint", lambda *a, **k: (_ for _ in ()).throw(pj.ProjectError("broken index")))
    result = pr.post_run(p, binding, "claude", "t", "before", set(), stopped=lambda: True)
    assert "verify" not in result and result["verify_badge"] == "main checkout unchecked"


def test_cancel_refused_once_the_run_is_finishing(helper):
    """I8-06: no 200 for a cancel the worker would ignore."""
    app_mod, *_ = helper
    app_mod._running_jobs["run-fin"] = {"project_key": "demo", "phase": "finalizing"}
    try:
        assert api(app_mod).delete("/api/runs/run-fin").status_code == 409
        assert "cancelled" not in app_mod._running_jobs["run-fin"]
    finally:
        app_mod._running_jobs.pop("run-fin", None)


# ── build inspection 9 regressions ───────────────────────────────────────────

def test_locked_cli_confidential_worktree_leaks_nothing(helper):
    """I9-01: policy is resolved before the lock: a refused launch of a CLI-confidential ticket
    posts only the template."""
    app_mod, run, records, state, events, comments, pushes, repo, write_registry = helper
    write_registry(confidential=True)
    with pj.ticket_lock("demo", "T-1"):
        pj.create_worktree(pj.get_project("demo"), "T-1")
    write_registry(confidential=False)
    with pj.ticket_lock("demo", "T-1"):  # e.g. a resume tab holds it
        run()
    rec = records()[-1]
    assert rec["status"] == "error" and "busy" in rec["error"] and rec["confidential"] is True
    assert comments and all(SENTINEL not in c for c in comments)


def test_cli_verify_promotion_reaches_retry_feedback_and_comment_route(helper, monkeypatch):
    """I9-02: a confidentiality promotion made only by `projects.py verify` gates every comment."""
    import runner.modules.linear as lin
    app_mod, run, records, state, events, comments, pushes, repo, write_registry = helper
    run()  # non-confidential first run
    write_registry(confidential=True)
    assert pj.main(["verify", "demo", "--worktree", records()[-1]["worktree"]]) == 0  # promotes the sidecar
    write_registry(confidential=False)
    monkeypatch.setattr(app_mod, "_run_project_ticket", lambda **kw: None)
    comments.clear()
    rid = records()[-1]["run_id"]
    assert api(app_mod).post(f"/api/runs/{rid}/retry", json={"reply": f"private {SENTINEL}"}).status_code == 200
    assert all(SENTINEL not in c for c in comments)
    assert lin.LinearModule()._is_confidential_issue("iss")


# ── build inspection 10 regressions ──────────────────────────────────────────

def test_unreadable_sidecar_is_unknown_not_false(helper):
    """I10-01: a damaged sidecar keeps the ticket's policy unknown: template comment, no prompt."""
    app_mod, run, records, state, events, comments, pushes, repo, write_registry = helper
    write_registry(confidential=True)
    with pj.ticket_lock("demo", "T-1"):
        pj.create_worktree(pj.get_project("demo"), "T-1")
    write_registry(confidential=False)
    (pj.WORKTREE_ROOT / "demo" / ".meta" / "T-1.json").write_text("{not json")
    run()
    rec = records()[-1]
    assert rec["status"] == "error" and rec["confidential"] is None
    assert comments and all(SENTINEL not in c for c in comments)


def test_unbound_labelled_issue_with_cli_confidential_worktree(helper):
    """I10-02: the comment route sees a CLI-made confidential worktree before any dashboard run."""
    import runner.modules.linear as lin
    app_mod, run, records, state, events, comments, pushes, repo, write_registry = helper
    write_registry(confidential=True)
    with pj.ticket_lock("demo", "T-5"):
        pj.create_worktree(pj.get_project("demo"), "T-5")
    write_registry(confidential=False)
    mod = lin.LinearModule()
    mod.issues_cache["iss-5"] = {"id": "iss-5", "identifier": "T-5", "labels": [{"name": "project:demo"}]}
    mod.issues_cache["iss-6"] = {"id": "iss-6", "identifier": "T-6", "labels": [{"name": "project:demo"}]}
    mod.issues_cache["iss-7"] = {"id": "iss-7", "labels": [{"name": "project:demo"}]}
    assert mod._is_confidential_issue("iss-5") and mod._is_confidential_issue("iss-7")
    assert not mod._is_confidential_issue("iss-6")


# ── dashboard registry: lifecycle lock across the launch helper, API, baseline ──

def test_dispatch_behind_a_remove_fails_and_creates_no_worktree(helper):
    app_mod, run, records, *_ = helper
    out = []
    with pj.project_lock("demo", exclusive=True, blocking=False):
        t = threading.Thread(target=lambda: out.append(run()))
        t.start()
        time.sleep(0.5)
        assert t.is_alive() and not out  # waiting for the lock, before any registry read
        reg = pj.REGISTRY_PATH
        reg.write_text("projects: {}\n")  # the remove lands while the launch waits
    t.join(timeout=30)
    assert out and out[0]["status"] == "error" and "unknown project" in out[0]["error"]
    assert not (pj.WORKTREE_ROOT / "demo" / "T-1").exists()


def test_confidentiality_edit_waits_until_the_comment_is_posted(helper, monkeypatch):
    app_mod, run, records, state, events, comments, pushes, repo, _ = helper
    attempts = []

    def comment(issue, body):
        snap = pj.registry_snapshot()[1]
        entry = pj.raw_entries(pj.REGISTRY_PATH.read_bytes())["demo"]
        try:
            pj.save_project("demo", {**entry, "confidential": True}, snap)
            attempts.append("saved")
        except pj.ProjectBusy:
            attempts.append("busy")
        comments.append(body)
    monkeypatch.setattr(app_mod, "_post_linear_comment", comment)
    run()
    assert attempts == ["busy"] and not app_mod._running_jobs
    entry = pj.raw_entries(pj.REGISTRY_PATH.read_bytes())["demo"]
    pj.save_project("demo", {**entry, "confidential": True, "seed": entry["seed"]}, pj.registry_snapshot()[1])
    assert pj.load_registry()["demo"].confidential


def test_project_api_token_validation_and_conflicts(helper):
    app_mod, run, *_ = helper
    anon = app_mod.app.test_client()
    assert anon.post("/api/projects", json={}).status_code == 403
    assert anon.delete("/api/projects/demo", json={}).status_code == 403
    c = api(app_mod)
    listing = c.get("/api/projects").get_json()
    snap = listing["registry_hash"]
    assert snap and listing["projects"][0]["entry"]["verify"] == "sh tests/check.sh"
    r = c.post("/api/projects", json={"key": "bad key", "entry": {}, "registry_hash": snap})
    assert r.status_code == 400 and "must match" in r.get_json()["error"]
    r = c.put("/api/projects/demo", json={"entry": {"path": "x"}, "registry_hash": "stale"})
    assert r.status_code == 409
    fresh = pj.REGISTRY_PATH.parent / "fresh-repo"
    r = c.post("/api/projects", json={"key": "fresh", "registry_hash": snap,
                                      "entry": {"path": str(fresh), "verify": "true", "env": {"A": 1}}})
    assert r.status_code == 400 and r.get_json()["initialized"] == str(fresh) and (fresh / ".git").exists()
    run()  # leaves worktree T-1
    r = c.delete("/api/projects/demo", json={"registry_hash": c.get("/api/projects").get_json()["registry_hash"]})
    assert r.status_code == 409 and r.get_json()["worktrees"] == ["T-1"]


def test_baseline_reports_fail_with_tail_and_removes_only_its_worktree(helper, monkeypatch):
    app_mod, run, *_ = helper
    monkeypatch.setattr(app_mod, "_BASELINES", {})
    app_mod._run_baseline("demo")
    b = app_mod._BASELINES["demo"]
    assert b["status"] == "fail" and b["exit"] != 0 and "duration_s" in b
    assert pj._worktree_dirs("demo") == []


def test_baseline_never_touches_an_existing_worktree(helper, monkeypatch):
    app_mod, *_ = helper
    monkeypatch.setattr(app_mod, "_BASELINES", {})
    monkeypatch.setattr(app_mod.time, "time", lambda: 1234.5)
    p = pj.get_project("demo")
    with pj.ticket_lock("demo", "BASELINE-1234500"):
        wt = Path(pj.create_worktree(p, "BASELINE-1234500")["worktree"])
    (wt / "precious.txt").write_text("work")
    app_mod._run_baseline("demo")
    assert "already existed" in app_mod._BASELINES["demo"]["error"]
    assert (wt / "precious.txt").read_text() == "work"


def test_baseline_runs_once_per_key(helper, monkeypatch):
    app_mod, *_ = helper
    monkeypatch.setattr(app_mod, "_BASELINES", {"demo": {"state": "running"}})
    r = api(app_mod).post("/api/projects/demo/baseline")
    assert r.status_code == 409


def test_project_added_through_save_dispatches_into_its_worktree(helper):
    app_mod, run, records, state, events, comments, pushes, repo, _ = helper
    snap = pj.registry_snapshot()[1]
    pj.save_project("demo2", {"path": str(repo), "verify": "sh tests/check.sh", "seed": ["data"],
                              "confidential": False, "note": "added from the dashboard"}, snap, create=True)
    out = app_mod._run_project_ticket(project_key="demo2", ident="N-1", agent="claude", prompt="p", title="t",
                                      run_id="run-n1", linear_issue_id="iss-n1", task_id="task-n1", launch_gen=0)
    assert out["status"] == "review" and out["worktree"].endswith("demo2/N-1") and out["branch"] == "agent/N-1"


def test_project_without_verify_dispatches_with_no_check(helper, monkeypatch):
    app_mod, run, records, state, events, comments, pushes, repo, _ = helper
    pj.REGISTRY_PATH.write_text(f"projects:\n  demo:\n    path: {repo}\n    seed: [data]\n    confidential: false\n")
    prompts = []
    real = pr.project_prompt
    monkeypatch.setattr(pr, "project_prompt", lambda *a: prompts.append(real(*a)) or prompts[-1])
    run()
    rec = records()[-1]
    assert rec["status"] == "review" and rec["verify_badge"] == "no check" and "verify" not in rec
    assert "1 file changed" in rec["shortstat"] and rec["main_checkout_changed"] is False
    assert "find and run its own tests" in prompts[-1]
    assert pj.main(["verify", "demo", "--worktree", rec["worktree"]]) == 2


def test_baseline_refuses_a_project_without_verify_synchronously(helper, monkeypatch):
    app_mod, *_, repo, _ = helper
    pj.REGISTRY_PATH.write_text(f"projects:\n  demo:\n    path: {repo}\n    confidential: false\n")
    monkeypatch.setattr(app_mod, "_BASELINES", {})
    started = []
    monkeypatch.setattr(app_mod.threading, "Thread", lambda *a, **k: started.append(1))
    r = api(app_mod).post("/api/projects/demo/baseline")
    assert r.status_code == 400 and "no verify" in r.get_json()["error"]
    assert not started and app_mod._BASELINES == {} and not (pj.WORKTREE_ROOT / "demo").exists()


def test_colliding_baseline_never_unlinks_a_held_ticket_lock(helper, monkeypatch):
    app_mod, *_ = helper
    monkeypatch.setattr(app_mod, "_BASELINES", {})
    monkeypatch.setattr(app_mod.time, "time", lambda: 1234.5)
    lock = pj.WORKTREE_ROOT / "demo" / ".meta" / "BASELINE-1234500.lock"
    with pj.ticket_lock("demo", "BASELINE-1234500"):
        app_mod._run_baseline("demo")
        assert "busy" in app_mod._BASELINES["demo"]["error"] and lock.exists()
        with pytest.raises(pj.TicketLocked):  # the holder's lock still excludes a second acquirer
            with pj.ticket_lock("demo", "BASELINE-1234500"):
                pass


def test_locate_route_reports_completeness(helper, monkeypatch):
    app_mod, *_ = helper
    monkeypatch.setattr(pj, "locate_folder", lambda name, entries: {"matches": ["~/x/" + name], "complete": len(entries) < 2})
    c = api(app_mod)
    assert c.post("/api/projects/locate", json={"name": "p", "entries": ["a"]}).get_json() == {"matches": ["~/x/p"], "complete": True}
    assert c.post("/api/projects/locate", json={"name": "p", "entries": ["a", "b"]}).get_json()["complete"] is False
    monkeypatch.undo()
    assert c.post("/api/projects/locate", json={"name": "../x", "entries": []}).status_code == 400


def test_create_without_key_uses_the_folder_name(helper):
    app_mod, *_, repo, _ = helper
    c = api(app_mod)
    snap = c.get("/api/projects").get_json()["registry_hash"]
    fresh = pj.REGISTRY_PATH.parent / "Fresh Folder"
    r = c.post("/api/projects", json={"registry_hash": snap, "entry": {"path": str(fresh), "confidential": False, "no_push": True}})
    assert r.status_code == 200 and r.get_json()["key"] == "Fresh-Folder" and (fresh / ".git").exists()


def test_workspace_root_found_from_either_checkout_location(tmp_path):
    import app as app_mod
    ws = tmp_path / "AI_Workspace"
    (ws / "obsidian").mkdir(parents=True)
    assert app_mod._workspace_root(ws / "prototypes" / "agentic-os") == ws
    assert app_mod._workspace_root(ws / "agentic-os") == ws
    assert app_mod._workspace_root(tmp_path / "x" / "agentic-os") == tmp_path / "x"


def test_saved_stream_paths_follow_the_moved_checkout(tmp_path, monkeypatch):
    import app as app_mod
    monkeypatch.setattr(app_mod, "OUTPUTS_DIR", tmp_path / "outputs")
    (tmp_path / "outputs" / "logs").mkdir(parents=True)
    (tmp_path / "outputs" / "logs" / "r.stream").write_text("x")
    assert app_mod._checkout_path("/old/prototypes/agentic-os/outputs/logs/r.stream") == tmp_path / "outputs" / "logs" / "r.stream"
    assert app_mod._checkout_path("/elsewhere/file.log") == Path("/elsewhere/file.log")


def test_maintenance_gate_counts_in_flight_work_and_refuses_new_runs(helper, monkeypatch):
    app_mod, run, records, *_ = helper
    c = api(app_mod)
    started, release = threading.Event(), threading.Event()

    def busy():
        with app_mod._inflight_work():
            started.set(); release.wait(10)
    t = threading.Thread(target=busy); t.start(); started.wait(5)
    try:
        assert c.post("/api/maintenance", json={"on": True}).get_json() == {"maintenance": True, "inflight": 1}
        r = c.post("/run", json={"prompt": "hi", "agent": "claude"})
        assert r.status_code == 409 and "maintenance" in r.get_json()["error"]
        out = run()  # a project dispatch is refused before it registers a job or a worktree
        assert out["status"] == "error" and "maintenance" in out["error"] and not app_mod._running_jobs
        assert not (pj.WORKTREE_ROOT / "demo" / "T-1").exists()
    finally:
        release.set(); t.join(5)
        c.post("/api/maintenance", json={"on": False})
    assert c.get("/api/maintenance").get_json() == {"maintenance": False, "inflight": 0}
    assert run()["status"] == "review"  # admission open again


def test_linear_dispatch_is_refused_under_maintenance(helper, monkeypatch):
    app_mod, *_ = helper
    from runner.modules.linear import LinearModule
    mod = LinearModule()
    called = []
    monkeypatch.setattr(mod, "_dispatch_issue_counted", lambda *a, **k: called.append(1))
    app_mod._MAINTENANCE.set()
    try:
        mod._dispatch_issue({"id": "i1"}, {}, None)
        assert called == []
    finally:
        app_mod._MAINTENANCE.clear()
    mod._dispatch_issue({"id": "i1"}, {}, None)
    assert called == [1]


def test_script_entrypoint_shares_one_app_module():
    """launchd runs runner/app.py as __main__; `from app import ...` must reach that same module."""
    code = ("import runpy, sys; sys.argv = ['app.py', '--help']\n"
            "try:\n    runpy.run_path('runner/app.py', run_name='__main__')\nexcept SystemExit:\n    pass\n"
            "import app; print(app.__name__, hasattr(app, '_MAINTENANCE'))")
    out = subprocess.run([sys.executable, "-c", code], cwd=str(RUNNER.parent), capture_output=True, text=True,
                         env={**os.environ, "PYTHONPATH": f"{RUNNER}:{RUNNER.parent}"})
    assert out.stdout.strip().splitlines()[-1] == "__main__ True", out.stdout + out.stderr


def test_retry_and_baseline_are_refused_before_any_state(helper, monkeypatch):
    app_mod, run, records, state, events, comments, pushes, *_ = helper
    run()
    rid = records()[-1]["run_id"]
    c = api(app_mod)
    monkeypatch.setattr(app_mod, "_BASELINES", {})
    jobs_before, n_events = dict(app_mod._running_jobs), len(events)
    assert wait_for(lambda: c.get("/api/maintenance").get_json()["inflight"] == 0)  # the run's own name sync done
    app_mod._MAINTENANCE.set()
    try:
        r = c.post(f"/api/runs/{rid}/retry", json={"reply": "again"})
        assert r.status_code == 409
        r = c.post("/api/projects/demo/baseline")
        assert r.status_code == 409 and app_mod._BASELINES == {}
        assert app_mod._running_jobs == jobs_before and len(events) == n_events and len(comments) == 1
        assert c.get("/api/maintenance").get_json()["inflight"] == 0  # nothing leaked
    finally:
        app_mod._MAINTENANCE.clear()


def test_final_tracker_push_counted_until_persisted_even_after_admission_closes(helper, monkeypatch):
    app_mod, *_ = helper
    from runner.modules.linear import LinearModule
    mod = LinearModule()
    calls = []
    monkeypatch.setattr(mod, "_dispatch_issue", lambda *a, **k: calls.append("dispatch"))
    gate = threading.Event()
    monkeypatch.setattr(mod, "_push_sync", lambda *a, **k: gate.wait(5))
    mod.issues_cache["i1"] = {"id": "i1", "state": "Todo"}
    with app_mod._inflight_work():  # an admitted run pushing its final tracker state
        mod.push_state("i1", "review")
    app_mod._MAINTENANCE.set()
    try:  # admission closed, but the continuation is still counted until it persists
        assert app_mod.app.test_client().get("/api/maintenance",
               headers={"X-AgenticOS-Token": app_mod.REQUEST_TOKEN}).get_json()["inflight"] == 1
        gate.set()
        time.sleep(0.3)
        assert app_mod._INFLIGHT == 0
    finally:
        app_mod._MAINTENANCE.clear()


def test_every_mutating_request_is_gated(helper):
    app_mod, run, records, *_ = helper
    run()
    rid = records()[-1]["run_id"]
    c = api(app_mod)
    app_mod._MAINTENANCE.set()
    try:
        assert c.patch(f"/api/runs/{rid}/status", json={"status": "success"}).status_code == 409
        assert c.post("/api/projects", json={}).status_code == 409
        assert c.get("/api/projects").status_code == 200  # reads stay open
        assert c.get("/api/maintenance").get_json()["inflight"] == 0
    finally:
        app_mod._MAINTENANCE.clear()


def test_counted_threads_inherit_admission_and_release_on_failed_start(helper, monkeypatch):
    app_mod, *_ = helper
    done = threading.Event()
    app_mod._MAINTENANCE.set()
    try:
        with pytest.raises(app_mod.MaintenanceRefused):  # nothing admitted: refused
            app_mod._start_counted(done.set)
        app_mod._TL.admitted = True  # inside admitted work: a follow-up writer is still allowed
        try:
            app_mod._start_counted(done.wait, 5)
            assert app_mod._INFLIGHT == 1
        finally:
            app_mod._TL.admitted = False
        done.set()
        time.sleep(0.3)
        assert app_mod._INFLIGHT == 0
    finally:
        app_mod._MAINTENANCE.clear()

    def boom(self):
        raise RuntimeError("can't start new thread")
    monkeypatch.setattr(threading.Thread, "start", boom)
    with pytest.raises(RuntimeError):
        app_mod._start_counted(lambda: None)
    assert app_mod._INFLIGHT == 0  # the slot came back (BUILD-009)


def test_stall_pass_is_counted_and_skipped_under_maintenance(helper, monkeypatch):
    app_mod, *_ = helper
    from runner.modules import stall_detection as sd
    seen = []
    monkeypatch.setattr(sd, "check_once", lambda a, s: seen.append(app_mod._INFLIGHT))
    monkeypatch.setattr(app_mod, "_archive_stale_sent", lambda: seen.append("archive"))
    sd.run_pass(app_mod, None, 0.0)
    assert seen == [1, "archive"]  # counted while it writes
    seen.clear()
    app_mod._MAINTENANCE.set()
    try:
        sd.run_pass(app_mod, None, 0.0)
        assert seen == []
    finally:
        app_mod._MAINTENANCE.clear()


def test_progress_cache_write_is_atomic(helper, monkeypatch):
    app_mod, *_ = helper
    path = app_mod._run_progress_path("r1")
    app_mod._write_run_progress_json("r1", {"stream_log": "/x/outputs/logs/r1.stream"})
    before = path.read_text()
    import state_io
    monkeypatch.setattr(state_io.os, "replace", lambda *a: (_ for _ in ()).throw(OSError("killed mid-write")))
    with pytest.raises(OSError):
        app_mod._write_run_progress_json("r1", {"state": "x"})
    assert path.read_text() == before  # an interrupted write leaves the old file whole


def test_progress_updates_from_concurrent_writers_all_survive(helper):
    app_mod, *_ = helper
    keys = [f"k{i}" for i in range(12)]
    ts = [threading.Thread(target=app_mod._write_run_progress_json, args=("r2", {k: True})) for k in keys]
    for t in ts: t.start()
    for t in ts: t.join(10)
    saved = json.loads(app_mod._run_progress_path("r2").read_text())
    assert all(saved.get(k) for k in keys)  # no stale read-merge-replace overwrote another (BUILD-015)


def test_stream_readers_are_counted(helper, monkeypatch):
    app_mod, *_ = helper
    started = []
    real = app_mod._start_counted
    monkeypatch.setattr(app_mod, "_start_counted", lambda fn, *a, **k: started.append(fn.__name__) or real(fn, *a, **k))
    proc = subprocess.Popen(["/bin/sh", "-c", "echo hello"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, _ = app_mod._stream_text_run(proc, "r3", timeout=10)
    assert "hello" in out and started == ["_reader", "_drain_stderr"]  # BUILD-014; stderr drained alongside (UI-04)


def test_registry_cache_write_is_atomic(tmp_path, monkeypatch):
    from runner.core import registry_loader as rl
    import state_io
    monkeypatch.setattr(rl, "_CLAUDE_REGISTRY_JSON", tmp_path / "registry.json")
    monkeypatch.setattr(rl, "_CLAUDE_REGISTRY_MD", tmp_path / "registry.md")
    monkeypatch.setattr(rl, "filter_registry_for_agent", lambda agent: {"s": {"agents": ["claude"]}})
    rl.ensure_claude_registry()
    before = (tmp_path / "registry.json").read_text()
    monkeypatch.setattr(state_io.os, "replace", lambda *a: (_ for _ in ()).throw(OSError("killed")))
    rl.ensure_claude_registry()  # best-effort: swallowed, and the old file stays whole (BUILD-013)
    assert (tmp_path / "registry.json").read_text() == before


def test_counted_thread_construction_failure_releases_the_slot(helper, monkeypatch):
    app_mod, *_ = helper
    def broken(*a, **k):
        raise MemoryError("no room for a thread")
    monkeypatch.setattr(app_mod.threading, "Thread", broken)
    with pytest.raises(MemoryError):
        app_mod._start_counted(lambda: None)
    assert app_mod._INFLIGHT == 0  # BUILD-009, constructor variant


def test_question_only_run_has_no_badge_after_earlier_commits(helper):
    """Session-to-board §7 with real git: the badge looks at this run only (STB-022/033), and the
    record carries the observed cost (STB-034) and a session card's routing (SBR-001)."""
    app_mod, run, records, state, events, comments, pushes, repo, _ = helper
    run()
    assert records()[-1]["verify_badge"] == "pass"  # the first run committed a change
    state["mode"] = "question"  # the agent only answers
    run(run_id="run-2", reuse_only=True, record_extra={"source": "session", "resume_session": {"id": "s"}})
    rec = records()[-1]
    assert rec["status"] == "review" and "verify_badge" not in rec
    assert rec["token_cost_usd"] is not None and rec["source"] == "session" and rec["resume_session"] == {"id": "s"}
    assert rec["project_key"] == "demo"  # the binding wins over record_extra
