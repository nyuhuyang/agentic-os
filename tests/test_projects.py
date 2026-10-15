"""runner/projects.py: registry loader, worktrees + seeds, verify harness. Fake project names only."""

import os
import time
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runner"))

import projects as pj  # noqa: E402


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setattr(pj, "WORKTREE_ROOT", tmp_path / "wt")
    r = tmp_path / "demo"
    (r / "tests").mkdir(parents=True)
    (r / "tests" / "check.sh").write_text("exit 0\n")
    (r / ".gitignore").write_text("data/\nlinked.csv\n")
    (r / "tracked.txt").write_text("t\n")
    (r / "sub").mkdir()
    (r / "sub" / "keep.txt").write_text("k\n")
    os.symlink("sub", r / "lnk")  # committed directory symlink
    git(r, "init", "-q", "-b", "main")
    git(r, "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
    git(r, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init")
    (r / "data").mkdir()
    (r / "data" / "real.csv").write_text("secret-data\n")
    os.symlink("real.csv", r / "data" / "nested_link.csv")
    os.symlink("data/real.csv", r / "linked.csv")
    return r


def project(repo, **kw):
    entry = {"path": str(repo), "verify": "sh tests/check.sh", **kw}
    return pj._parse_project("demo", entry)


def make(repo, ident="T-1", **kw):
    p = project(repo, **kw)
    with pj.ticket_lock(p.key, ident):
        info = pj.create_worktree(p, ident)
    return p, Path(info["worktree"]), info


# ── loader ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("entry, msg", [
    ({"path": None, "verify": "x"}, "'path' is required"),
    ({"path": "/nonexistent/x", "verify": "x"}, "not a git repository"),
    ({"verify": ""}, "'verify' is required"),
    ({"verify": "x", "colour": "red"}, "unknown field"),
    ({"verify": "x", "seed": ["/etc/passwd"]}, "must be relative"),
    ({"verify": "x", "seed": ["../outside"]}, "without '..'"),
    ({"verify": "x", "seed": ["nope.csv"]}, "missing or a dangling link"),
    ({"verify": "x", "verify_timeout_s": 0}, "positive integer"),
])
def test_loader_validation_errors(repo, entry, msg):
    entry = {"path": str(repo), **entry} if "path" not in entry else entry
    with pytest.raises(pj.ProjectError, match=msg):
        pj._parse_project("demo", entry)


def test_loader_dangling_seed_link(repo):
    os.symlink("gone.csv", repo / "data" / "dangling.csv")
    with pytest.raises(pj.ProjectError, match="dangling"):
        project(repo, seed=["data/dangling.csv"])


def test_registry_file_and_unknown_key(repo, tmp_path):
    reg = tmp_path / "projects.yaml"
    reg.write_text(f"projects:\n  demo:\n    path: {repo}\n    verify: sh tests/check.sh\n")
    loaded = pj.load_registry(reg)
    assert loaded["demo"].path == repo
    with pytest.raises(pj.ProjectError, match="unknown project 'other'"):
        pj.get_project("other", loaded)


# ── worktree + seeds ─────────────────────────────────────────────────────────

def test_worktree_created_on_agent_branch(repo):
    p, wt, info = make(repo)
    assert info["branch"] == "agent/T-1" and not info["reused"]
    assert (wt.stat().st_mode & 0o777) == 0o700
    assert info["base_sha"] == subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                                              capture_output=True, text=True).stdout.strip()
    _, _, again = make(repo)
    assert again["reused"]


def test_seed_copy_has_no_symlinks(repo):
    _, wt, _ = make(repo, seed=["data", "linked.csv"])
    for f in (wt / "data" / "real.csv", wt / "data" / "nested_link.csv", wt / "linked.csv"):
        assert f.is_file() and not f.is_symlink()
    (wt / "linked.csv").write_text("agent edit")
    assert (repo / "data" / "real.csv").read_text() == "secret-data\n"


def test_seed_destination_symlink_ancestor_rejected(repo):
    (repo / "sub" / "x.csv").write_text("x")  # source resolves inside the root via lnk
    with pytest.raises(pj.ProjectError, match="ancestor 'lnk' is a symlink"):
        make(repo, seed=["lnk/x.csv"])
    assert not (pj.WORKTREE_ROOT / "demo" / "T-1").exists()


def test_seed_tracked_path_collision_rejected(repo):
    with pytest.raises(pj.ProjectError, match="collides"):
        make(repo, seed=["tracked.txt"])


def test_seed_only_ignored_by_uncommitted_rule_rejected(repo):
    (repo / "local.csv").write_text("l")
    (repo / ".git" / "info" / "exclude").write_text("local.csv\n")
    with pytest.raises(pj.ProjectError, match="not ignored by the worktree's committed"):
        make(repo, seed=["local.csv"])


def test_committed_seed_detected(repo):
    p, wt, info = make(repo, seed=["data"])
    git(wt, "add", "-f", "data/real.csv")
    git(wt, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "oops")
    assert pj.committed_seeds(p, wt, info["base_sha"]) == ["data"]


def test_untracked_verify_target_refused(repo):
    (repo / "tests" / "new.sh").write_text("exit 0\n")
    with pytest.raises(pj.ProjectError, match="not committed at HEAD"):
        make(repo, verify="sh tests/new.sh")


def test_cleanup_removes_worktree_and_branch(repo):
    p, wt, _ = make(repo)
    with pj.ticket_lock(p.key, "T-1"):
        pj.remove_worktree(p, "T-1")
    assert not wt.exists()
    out = subprocess.run(["git", "-C", str(repo), "branch", "--list", "agent/T-1"], capture_output=True, text=True)
    assert out.stdout.strip() == ""


def test_ticket_lock_is_exclusive(repo):
    with pj.ticket_lock("demo", "T-1"):
        with pytest.raises(pj.TicketLocked):
            with pj.ticket_lock("demo", "T-1"):
                pass
        with pj.ticket_lock("demo", "T-2"):  # other tickets are independent
            pass


# ── verify ───────────────────────────────────────────────────────────────────

def test_verify_prepends_path(repo):
    p, wt, _ = make(repo, verify="echo $PATH", env={"PATH": "~/fakebin"})
    out = pj.run_verify(p, wt)
    assert out["status"] == "pass"
    first = out["tail"].strip().split(os.pathsep)
    assert first[0] == os.path.expanduser("~/fakebin") and len(first) > 1


def test_verify_expands_root_and_base(repo):
    p, wt, info = make(repo, verify="echo R={root} B={base}")
    out = pj.run_verify(p, wt, base=info["base_sha"])
    assert f"R={repo}" in out["tail"] and f"B={info['base_sha']}" in out["tail"]
    assert f"B={info['base_sha']}" in pj.run_verify(p, wt)["tail"]  # defaults to the binding's base


def test_verify_failure_and_timeout(repo):
    p, wt, _ = make(repo, verify="exit 3")
    assert pj.run_verify(p, wt)["status"] == "fail"
    p, wt, _ = make(repo, ident="T-2", verify="sleep 30", verify_timeout_s=1)
    out = pj.run_verify(p, wt)
    assert out["status"] == "timeout" and out["exit"] != 0 and out["duration_s"] < 15


def test_verify_requires_owned_worktree(repo):
    p = project(repo)
    with pytest.raises(pj.ProjectError, match="not a worktree AgenticOS created"):
        pj.run_verify(p, repo)


def test_verify_cli_requires_worktree(capsys):
    with pytest.raises(SystemExit) as exc:
        pj.main(["verify", "demo"])
    assert exc.value.code == 2
    assert "--worktree" in capsys.readouterr().err


def test_seed_ignored_only_by_excludes_file_rejected(repo, tmp_path):
    excludes = tmp_path / "global-excludes"
    excludes.write_text("viaglobal.csv\n")
    git(repo, "config", "core.excludesFile", str(excludes))
    (repo / "viaglobal.csv").write_text("g")
    with pytest.raises(pj.ProjectError, match="not ignored by the worktree's committed"):
        make(repo, seed=["viaglobal.csv"])


def test_uncommitted_gitignore_edit_does_not_count(repo):
    p, wt, _ = make(repo)
    assert pj._ignored_by_committed_rule(wt, "data/x.csv")  # committed rule counts
    (wt / "extra.csv").write_text("e")
    with open(wt / ".gitignore", "a") as f:
        f.write("extra.csv\n")
    assert not pj._ignored_by_committed_rule(wt, "extra.csv")
    assert not pj._ignored_by_committed_rule(wt, "data/x.csv")  # an edited .gitignore no longer counts


def test_hardened_git_runs_no_fsmonitor_or_hook(repo, tmp_path):
    marker = tmp_path / "ran"
    script = tmp_path / "evil.sh"
    script.write_text(f"#!/bin/sh\necho ran >> {marker}\n")
    script.chmod(0o755)
    git(repo, "config", "core.fsmonitor", str(script))
    hook = repo / ".git" / "hooks" / "post-checkout"
    hook.write_text(f"#!/bin/sh\necho hook >> {marker}\n")
    hook.chmod(0o755)
    pj._git(repo, "status", "--porcelain")
    make(repo)  # worktree add would fire post-checkout
    assert not marker.exists()


def test_sandbox_prefix_blocks_outside_write(repo):
    # $TMPDIR is writable by design, so probe a path in the home directory instead.
    outside = Path.home() / f".agentic-os-sandbox-probe-{os.getpid()}"
    try:
        proc = subprocess.run([*pj.sandbox_prefix([repo]), "/bin/sh", "-c", f"echo x > {outside}"], capture_output=True)
        assert proc.returncode != 0 and not outside.exists()
    finally:
        outside.unlink(missing_ok=True)
    inside = repo / "inside.txt"
    proc = subprocess.run([*pj.sandbox_prefix([repo]), "/bin/sh", "-c", f"echo x > {inside}"], capture_output=True)
    assert proc.returncode == 0 and inside.exists()


# ── fingerprint ──────────────────────────────────────────────────────────────

def _fp(repo, **kw):
    return pj.fingerprint(project(repo), **kw)


def test_fingerprint_stable_when_nothing_changes(repo):
    assert _fp(repo) == _fp(repo)


@pytest.mark.parametrize("change", ["dirty_edit", "commit", "ignored_file", "config", "include", "worktree_config", "hook", "hookspath"])
def test_fingerprint_catches(repo, tmp_path, change):
    (repo / "tracked.txt").write_text("dirty\n")  # an already-dirty file
    inc = repo / ".git" / "extra.conf"
    inc.write_text("[core]\n")
    git(repo, "config", "include.path", "extra.conf")
    before = _fp(repo)
    if change == "dirty_edit":
        (repo / "tracked.txt").write_text("dirtier\n")
    elif change == "commit":
        git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qam", "c")
    elif change == "ignored_file":
        (repo / "data" / "new.csv").write_text("n")
    elif change == "config":
        git(repo, "config", "core.fsmonitor", "/tmp/evil")
    elif change == "include":
        inc.write_text("[core]\n\tfsmonitor = /tmp/evil\n")
    elif change == "worktree_config":
        git(repo, "config", "extensions.worktreeConfig", "true")
        before = _fp(repo)
        git(repo, "config", "--worktree", "core.fsmonitor", "/tmp/evil")
    elif change == "hook":
        (repo / ".git" / "hooks" / "post-commit").write_text("#!/bin/sh\n")
    elif change == "hookspath":
        hooks = tmp_path / "hooks"
        hooks.mkdir()
        git(repo, "config", "core.hooksPath", str(hooks))
        before = _fp(repo)
        (hooks / "pre-commit").write_text("#!/bin/sh\n")
    assert _fp(repo) != before


def test_fingerprint_excludes_bookkeeping(repo):
    before = _fp(repo, exclude={"data/real.csv"})
    (repo / "data" / "real.csv").write_text("changed by runner\n")
    assert _fp(repo, exclude={"data/real.csv"}) == before


# ── runner commit ────────────────────────────────────────────────────────────

def test_runner_commit_includes_edit_not_seed(repo):
    p, wt, info = make(repo, seed=["data"])
    (wt / "tracked.txt").write_text("agent edit\n")
    sha = pj.runner_commit(p, wt, "T-1: edit")
    assert sha
    names = subprocess.run(["git", "-C", str(wt), "show", "--name-only", "--format=", sha],
                           capture_output=True, text=True).stdout.split()
    assert names == ["tracked.txt"]
    assert pj.committed_seeds(p, wt, info["base_sha"]) == []


def test_runner_commit_nothing_to_commit(repo):
    p, wt, _ = make(repo)
    assert pj.runner_commit(p, wt, "T-1: nothing") is None


def test_runner_commit_ignores_gpg_sign(repo):
    git(repo, "config", "commit.gpgSign", "true")
    git(repo, "config", "gpg.program", "/bin/false")
    p, wt, _ = make(repo)
    (wt / "tracked.txt").write_text("edit\n")
    sha = pj.runner_commit(p, wt, "T-1: unsigned")
    sig = subprocess.run(["git", "-C", str(wt), "cat-file", "commit", sha], capture_output=True, text=True).stdout
    assert "gpgsig" not in sig


# ── confidential confinement ─────────────────────────────────────────────────

def test_confidential_verify_is_sandboxed(repo):
    outside = Path.home() / f".agentic-os-verify-probe-{os.getpid()}"
    try:
        p, wt, _ = make(repo, verify=f"echo inside > ok.txt && touch {outside}", confidential=True)
        out = pj.run_verify(p, wt)
        assert (wt / "ok.txt").exists() and not outside.exists() and out["status"] == "fail"
    finally:
        outside.unlink(missing_ok=True)


def test_confidential_worktree_and_commit_work_confined(repo):
    p, wt, info = make(repo, seed=["data"], confidential=True)
    (wt / "tracked.txt").write_text("edit\n")
    assert pj.runner_commit(p, wt, "T-1: confined")
    assert pj.committed_seeds(p, wt, info["base_sha"]) == []
    assert pj.fingerprint(p) == pj.fingerprint(p)
    with pj.ticket_lock(p.key, "T-1"):
        pj.remove_worktree(p, "T-1")
    assert not wt.exists()


# ── build inspection 2 regressions ───────────────────────────────────────────

def test_seed_explicitly_unignored_by_negation_rejected(repo):
    (repo / ".gitignore").write_text("data/\nlinked.csv\nkeep.csv\n!keep.csv\n")
    git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qam", "negate")
    (repo / "keep.csv").write_text("k")
    with pytest.raises(pj.ProjectError, match="not ignored"):
        make(repo, seed=["keep.csv"])


@pytest.mark.parametrize("name", ["private data/secret.csv", "données/é.csv", "odd\nname/x.csv"])
def test_committed_seed_detected_with_awkward_names(repo, name):
    seed = name.split("/")[0]
    (repo / ".gitignore").write_text(f"data/\nlinked.csv\n{seed.replace(chr(10), '?')}/\n")
    git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qam", "ignore")
    (repo / seed).mkdir()
    (repo / name).write_text("s")
    p, wt, info = make(repo, seed=[seed])
    git(wt, "add", "-f", "--", name)
    git(wt, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "leak")
    assert pj.committed_seeds(p, wt, info["base_sha"]) == [seed]


def test_cleanup_refuses_worktree_of_another_repo(repo, tmp_path):
    p, wt, _ = make(repo)
    (wt / "uncommitted.txt").write_text("work in progress")
    other = tmp_path / "other"
    other.mkdir()
    git(other, "init", "-q")
    git(other, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "i")
    repointed = pj._parse_project("demo", {"path": str(other), "verify": "true"})
    with pytest.raises(pj.ProjectError, match="refusing to delete"):
        pj.remove_worktree(repointed, "T-1")
    assert (wt / "uncommitted.txt").exists()


def test_subdirectory_of_worktree_is_not_owned(repo):
    p, wt, _ = make(repo)
    assert (wt / "sub").is_dir()  # a tracked directory inside the worktree
    with pytest.raises(pj.ProjectError, match="not a worktree AgenticOS created"):
        pj.run_verify(p, wt / "sub")
    with pytest.raises(pj.ProjectError, match="not a worktree AgenticOS created"):
        pj.ticket_from_worktree(p, wt / "sub")
    assert pj.ticket_from_worktree(p, wt) == "T-1"


def test_interrupted_verify_leaves_no_process(repo, monkeypatch):
    p, wt, _ = make(repo, verify="sleep 30 & sleep 30")
    started = []
    real_popen = subprocess.Popen

    class Interrupting(real_popen):
        def communicate(self, *a, **k):
            started.append(self.pid)
            raise KeyboardInterrupt

    monkeypatch.setattr(pj.subprocess, "Popen", Interrupting)
    with pytest.raises(KeyboardInterrupt):
        pj.run_verify(p, wt)
    with pytest.raises(ProcessLookupError):
        os.killpg(started[0], 0)


def test_reuse_keeps_original_base_and_checks_branch(repo):
    p, wt, info = make(repo)
    git(wt, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "ticket work")
    git(repo, "merge", "-q", "--ff-only", "agent/T-1")  # main fast-forwards to the ticket
    _, _, again = make(repo)
    assert again["reused"] and again["base_sha"] == info["base_sha"]
    git(wt, "checkout", "-q", "-b", "elsewhere")
    with pytest.raises(pj.ProjectError, match="not agent/T-1"):
        make(repo)
    git(wt, "checkout", "-q", "agent/T-1")
    pj._binding_path(p, "T-1").unlink()
    with pytest.raises(pj.ProjectError, match="binding metadata is missing"):
        make(repo)


def test_seed_nested_link_outside_root_rejected(repo, tmp_path):
    outside = tmp_path / "unrelated"
    outside.mkdir()
    (outside / "secret.csv").write_text("other project's data")
    os.symlink(outside, repo / "data" / "shared")
    with pytest.raises(pj.ProjectError, match="points outside the project root"):
        make(repo, seed=["data"])


def test_seed_link_cycle_rejected(repo):
    os.symlink("..", repo / "data" / "loop")
    with pytest.raises(pj.ProjectError, match="cycle|outside"):
        make(repo, seed=["data"])


def test_runner_commit_bounded_when_clean_filter_hangs(repo, monkeypatch):
    monkeypatch.setattr(pj, "COMMIT_TIMEOUT_S", 2)
    p, wt, _ = make(repo)
    git(repo, "config", "filter.hang.clean", "sleep 30")
    (wt / ".gitattributes").write_text("*.txt filter=hang\n")
    (wt / "tracked.txt").write_text("edit\n")
    t0 = time.monotonic()
    with pytest.raises(pj.ProjectError, match="timed out"):
        pj.runner_commit(p, wt, "T-1: hang")
    assert time.monotonic() - t0 < 20
    assert (wt / "tracked.txt").read_text() == "edit\n"  # changes preserved


def test_registry_syntax_error_is_a_project_error(tmp_path):
    reg = tmp_path / "projects.yaml"
    reg.write_text("projects:\n  demo: [unclosed\n")
    with pytest.raises(pj.ProjectError, match="cannot read registry"):
        pj.load_registry(reg)
    reg.write_text("projects: {}\n")
    reg.chmod(0)
    try:
        with pytest.raises(pj.ProjectError, match="cannot read registry"):
            pj.load_registry(reg)
    finally:
        reg.chmod(0o600)


# ── build inspection 3 regressions ───────────────────────────────────────────

def _commit(cwd, msg):
    git(cwd, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", msg)


def test_seed_introduced_only_by_merge_detected(repo):
    p, wt, info = make(repo, seed=["data"])
    git(wt, "checkout", "-q", "-b", "side")
    _commit(wt, "side")
    git(wt, "checkout", "-q", "agent/T-1")
    _commit(wt, "main line")
    git(wt, "merge", "-q", "--no-commit", "--no-ff", "side")
    git(wt, "add", "-f", "data/real.csv")
    git(wt, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "merge")
    assert pj.committed_seeds(p, wt, info["base_sha"]) == ["data"]


def test_seed_name_starting_with_newline(repo):
    seed = "\nprivate"
    (repo / ".gitignore").write_text("data/\nlinked.csv\n?private/\n")
    git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qam", "ignore")
    (repo / seed).mkdir()
    (repo / seed / "secret.csv").write_text("s")
    p, wt, info = make(repo, seed=[seed])
    git(wt, "add", "-f", "--", f"{seed}/secret.csv")
    _commit(wt, "leak")
    assert pj.committed_seeds(p, wt, info["base_sha"]) == [seed]


@pytest.mark.parametrize("ok", [True, False])
def test_bounded_command_reaps_background_children(tmp_path, ok):
    marker = tmp_path / "alive"
    script = f"(sleep 3; touch {marker}) >/dev/null 2>&1 & exit {0 if ok else 3}"
    code, _, _ = pj._run_bounded(["/bin/sh", "-c", script], timeout=10)
    assert code == (0 if ok else 3)
    time.sleep(4)
    assert not marker.exists()


def test_verify_refuses_switched_branch_and_missing_binding(repo):
    p, wt, _ = make(repo)
    git(wt, "checkout", "-q", "-b", "elsewhere")
    with pytest.raises(pj.ProjectError, match="not agent/T-1"):
        pj.run_verify(p, wt)
    git(wt, "checkout", "-q", "agent/T-1")
    pj._binding_path(p, "T-1").unlink()
    with pytest.raises(pj.ProjectError, match="binding metadata is missing"):
        pj.run_verify(p, wt)


def test_seed_internal_directory_alias_allowed(repo):
    (repo / "data" / "real").mkdir()
    (repo / "data" / "real" / "x.csv").write_text("x")
    os.symlink("real", repo / "data" / "shortcut")
    _, wt, _ = make(repo, seed=["data"])
    assert (wt / "data" / "shortcut" / "x.csv").is_file() and not (wt / "data" / "shortcut").is_symlink()


@pytest.mark.parametrize("cmd", ["sh tests/new.sh;", "true && sh tests/new.sh", "sh tests/new.sh|cat"])
def test_untracked_verify_target_found_next_to_shell_operators(repo, cmd):
    (repo / "tests" / "new.sh").write_text("exit 0\n")
    assert pj.untracked_verify_targets(project(repo, verify=cmd)) == ["tests/new.sh"]


def test_verify_timeout_keeps_output_printed_before(repo):
    p, wt, _ = make(repo, verify="echo SENTINEL-BEFORE-HANG; sleep 30", verify_timeout_s=1)
    out = pj.run_verify(p, wt)
    assert out["status"] == "timeout" and "SENTINEL-BEFORE-HANG" in out["tail"]


# ── build inspection 4 regressions (degraded same-provider review) ───────────

def test_sandbox_blocks_open_url_osascript_and_launchd(tmp_path):
    import http.server, threading
    hits = []

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path); self.send_response(204); self.send_header("Connection", "close"); self.end_headers()
        def log_message(self, *a): pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    pre = pj.sandbox_prefix([tmp_path])
    probe = Path.home() / f".aos-escape-{os.getpid()}"
    try:
        subprocess.run([*pre, "/usr/bin/open", "-g", f"http://127.0.0.1:{srv.server_port}/leak"], capture_output=True, timeout=15)
        subprocess.run([*pre, "/usr/bin/osascript", "-e", f'do shell script "touch {probe}"'], capture_output=True, timeout=15)
        subprocess.run([*pre, "/bin/launchctl", "submit", "-l", f"aos.probe.{os.getpid()}", "--", "/usr/bin/touch", str(probe)],
                       capture_output=True, timeout=15)
        time.sleep(3)
        assert hits == [] and not probe.exists()
    finally:
        subprocess.run(["/bin/launchctl", "remove", f"aos.probe.{os.getpid()}"], capture_output=True)
        probe.unlink(missing_ok=True)
        srv.shutdown()


def test_seed_in_orphan_root_commit_detected(repo):
    p, wt, info = make(repo, seed=["data"])
    git(wt, "checkout", "-q", "--orphan", "tmp")
    git(wt, "add", "-f", "data/real.csv")
    git(wt, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "orphan")
    git(wt, "branch", "-M", "tmp", "agent/T-1")
    assert pj.committed_seeds(p, wt, info["base_sha"]) == ["data"]


@pytest.mark.parametrize("change", ["branch_switch", "stash_drop", "skip_worktree"])
def test_fingerprint_catches_ref_and_index_flag_changes(repo, change):
    if change == "stash_drop":
        (repo / "tracked.txt").write_text("stashed\n")
        git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "stash", "-q")
    before = _fp(repo)
    if change == "branch_switch":
        git(repo, "checkout", "-q", "-b", "other")  # same commit, same diffs
    elif change == "stash_drop":
        git(repo, "stash", "drop", "-q")
    else:
        git(repo, "update-index", "--skip-worktree", "tracked.txt")
        (repo / "tracked.txt").write_text("hidden edit\n")
    assert _fp(repo) != before


def test_interrupted_creation_leaves_no_reusable_worktree(repo, monkeypatch):
    def boom(*a, **k):
        raise KeyboardInterrupt
    real_copy = pj._copy_seeds
    monkeypatch.setattr(pj, "_copy_seeds", boom)
    with pytest.raises(KeyboardInterrupt):
        make(repo, seed=["data"])
    assert not (pj.WORKTREE_ROOT / "demo" / "T-1").exists()
    monkeypatch.setattr(pj, "_copy_seeds", real_copy)  # not undo(): that would drop the WORKTREE_ROOT redirect
    _, _, info = make(repo, seed=["data"])
    assert not info["reused"]


def test_reuse_requires_seeds_still_present(repo):
    p, wt, _ = make(repo, seed=["data"])
    import shutil as sh
    sh.rmtree(wt / "data")
    with pytest.raises(pj.ProjectError, match="missing or no longer ignored"):
        make(repo, seed=["data"])


def test_verify_passes_when_background_child_holds_stdout(repo):
    p, wt, _ = make(repo, verify="(sleep 30 &) ; echo done", verify_timeout_s=10)
    t0 = time.monotonic()
    out = pj.run_verify(p, wt)
    assert out["status"] == "pass" and "done" in out["tail"] and time.monotonic() - t0 < 15


def test_registry_entry_errors_of_any_kind_are_isolated(tmp_path, repo):
    reg = tmp_path / "projects.yaml"
    reg.write_text(f"projects:\n  good:\n    path: {repo}\n    verify: 'true'\n"
                   "  weird:\n    path: ~nouser-aos/x\n    verify: 'true'\n")
    errors = {}
    loaded = pj.load_registry(reg, errors=errors)
    assert list(loaded) == ["good"] and "weird" in errors


def test_diff_calls_always_disable_drivers():
    argv = pj._git_argv(Path("/x"), ("diff", "--quiet", "HEAD"), None)
    assert "--no-ext-diff" in argv and "--no-textconv" in argv


def test_ticket_named_like_a_sidecar_does_not_collide(repo):
    make(repo, ident="T-1.json")
    _, _, info = make(repo, ident="T-1")
    assert not info["reused"]
