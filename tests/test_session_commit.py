"""Manual Commit on a session row (plan 2026-10-21-session-commit-button). Fixture repos only."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runner"))

import projects as pj  # noqa: E402


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setattr(pj, "WORKTREE_ROOT", tmp_path / "wt")
    for k in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{k}_NAME", "t")
        monkeypatch.setenv(f"GIT_{k}_EMAIL", "t@t.invalid")
    root = tmp_path / "alpha"
    (root / "src").mkdir(parents=True)
    (root / "a.txt").write_text("a\n")
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "init")
    return pj.Project(key="alpha", path=root, verify="true"), root


def count(root):
    return int(git(root, "rev-list", "--count", "HEAD"))


def test_dry_run_lists_changes_and_writes_nothing(repo):
    project, root = repo
    (root / "a.txt").write_text("changed\n")
    (root / "src" / "new.py").write_text("n\n")
    out = pj.commit_checkout(project, root / "src", dry_run=True)  # a session cwd below the repo top
    assert out["branch"] == "main" and out["committed"] is None and out["repo"] == str(root.resolve())
    assert sorted(out["files"]) == ["a.txt", "src/new.py"]
    assert count(root) == 1 and git(root, "diff", "--cached", "--name-only") == ""


def test_commit_stages_everything_in_one_commit(repo):
    project, root = repo
    (root / "a.txt").write_text("changed\n")
    (root / "b.txt").write_text("b\n")
    out = pj.commit_checkout(project, root, "Manual: my change")
    assert out["committed"] == git(root, "rev-parse", "HEAD") and count(root) == 2
    assert git(root, "log", "-1", "--format=%s") == "Manual: my change"
    assert git(root, "status", "--porcelain") == ""


def test_nothing_to_commit(repo):
    project, root = repo
    out = pj.commit_checkout(project, root, "msg")
    assert out["committed"] is None and out["files"] == [] and count(root) == 1


def test_repo_outside_the_project_is_refused(repo, tmp_path):
    project, _ = repo
    other = tmp_path / "other"
    other.mkdir()
    git(other, "init", "-q", "-b", "main")
    (other / "x").write_text("x")
    with pytest.raises(pj.ProjectError):
        pj.commit_checkout(project, other, "msg")
    assert git(other, "status", "--porcelain") == "?? x"


def test_detached_head_is_refused(repo):
    project, root = repo
    git(root, "checkout", "-q", "--detach")
    (root / "a.txt").write_text("c\n")
    with pytest.raises(pj.ProjectError, match="detached"):
        pj.commit_checkout(project, root, "msg")


def test_empty_message_is_refused(repo):
    project, root = repo
    (root / "a.txt").write_text("c\n")
    with pytest.raises(pj.ProjectError, match="message"):
        pj.commit_checkout(project, root, "   ")
    assert count(root) == 1


def test_worktree_commit_waits_for_its_ticket_lock(repo):
    project, root = repo
    with pj.ticket_lock("alpha", "T-1"):
        wt = Path(pj.create_worktree(project, "T-1")["worktree"])
    (wt / "a.txt").write_text("wt change\n")
    with pj.ticket_lock("alpha", "T-1"):  # a run, verify or terminal holds it
        with pytest.raises(pj.TicketLocked):
            pj.commit_checkout(project, wt, "msg")
    out = pj.commit_checkout(project, wt, "worktree commit")
    assert out["branch"] == "agent/T-1" and out["committed"] and git(wt, "log", "-1", "--format=%s") == "worktree commit"


def test_main_checkout_commit_waits_for_a_merge(repo):
    project, root = repo
    (root / "a.txt").write_text("c\n")
    with pj._MERGE_LOCK:
        with pytest.raises(pj.TicketLocked, match="merge"):
            pj.commit_checkout(project, root, "msg")
    assert pj.commit_checkout(project, root, "msg")["committed"]


def test_route_commits_a_session_row(repo, tmp_path, monkeypatch):
    project, root = repo
    import app as app_mod
    reg = tmp_path / "projects.yaml"
    reg.write_text(f"projects:\n  alpha:\n    path: {root}\n    verify: 'true'\n")
    monkeypatch.setattr(pj, "REGISTRY_PATH", reg)
    d = pj.CLAUDE_PROJECTS / pj._slug(str(root))
    d.mkdir(parents=True)
    (d / "s1.jsonl").write_text(json.dumps({"type": "user", "cwd": str(root), "entrypoint": "cli",
                                            "message": {"role": "user", "content": "hi"}}) + "\n")
    (root / "a.txt").write_text("route\n")
    c = app_mod.app.test_client()
    h = {"X-AgenticOS-Token": app_mod.REQUEST_TOKEN}
    pre = c.post("/api/projects/alpha/sessions/claude/s1/commit", json={"dry_run": True}, headers=h).get_json()
    assert pre["files"] == ["a.txt"] and pre["committed"] is None
    r = c.post("/api/projects/alpha/sessions/claude/s1/commit", json={"message": "via route"}, headers=h)
    assert r.status_code == 200 and r.get_json()["committed"] and git(root, "log", "-1", "--format=%s") == "via route"
    assert c.post("/api/projects/alpha/sessions/claude/nope/commit", json={"message": "m"}, headers=h).status_code == 404


# ── Inspection 1 fixes (SC-001..005) ─────────────────────────────────────────

def test_unfinished_merge_is_refused_without_writes(repo):
    project, root = repo
    git(root, "checkout", "-q", "-b", "side")
    (root / "a.txt").write_text("side\n"); git(root, "commit", "-qam", "side")
    git(root, "checkout", "-q", "main")
    (root / "a.txt").write_text("main\n"); git(root, "commit", "-qam", "main")
    subprocess.run(["git", "-C", str(root), "merge", "-q", "side"], capture_output=True)  # conflicts
    head = git(root, "rev-parse", "HEAD")
    with pytest.raises(pj.ProjectError, match="merge"):
        pj.commit_checkout(project, root, "msg")
    assert git(root, "rev-parse", "HEAD") == head and git(root, "ls-files", "-u")  # still unresolved


def test_rebase_in_progress_is_refused(repo):
    project, root = repo
    gp = Path(git(root, "rev-parse", "--absolute-git-dir")) / "rebase-merge"
    gp.mkdir()
    (root / "a.txt").write_text("c\n")
    with pytest.raises(pj.ProjectError, match="rebase"):
        pj.commit_checkout(project, root, "msg")


def test_dry_run_and_empty_commit_leave_the_index_alone(repo):
    project, root = repo
    import os
    os.utime(root / "a.txt", (1, 1))  # stat-dirty, same content: a plain status would refresh the index
    index = Path(git(root, "rev-parse", "--absolute-git-dir")) / "index"
    before = (index.read_bytes(), index.stat().st_mtime_ns)
    assert pj.commit_checkout(project, root, dry_run=True)["files"] == []
    assert pj.commit_checkout(project, root, "msg")["committed"] is None
    assert (index.read_bytes(), index.stat().st_mtime_ns) == before


def test_porcelain_rename_source_is_not_a_file():
    assert pj._porcelain_paths(b"R  new.txt\0original.txt\0 M a.txt\0?? b\0") == ["new.txt", "a.txt", "b"]
    assert pj._porcelain_paths(b"C  copy.txt\0o\0") == ["copy.txt"]


def test_staged_rename_counts_once(repo):
    project, root = repo
    git(root, "mv", "a.txt", "renamed.txt")
    assert pj.commit_checkout(project, root, dry_run=True)["files"] == ["renamed.txt"]


def test_commit_is_always_sandboxed(repo, monkeypatch):
    """Not confidential in the registry, still confined: no stale policy can leave git unconfined (SC-006)."""
    project, root = repo
    seen = []
    real = pj.sandbox_prefix
    monkeypatch.setattr(pj, "sandbox_prefix", lambda writable, temp=True: seen.append(list(writable)) or real(writable, temp))
    (root / "a.txt").write_text("c\n")
    assert not project.confidential and pj.commit_checkout(project, root, "msg")["committed"]
    assert [] in seen  # the status: nothing writable
    assert any(root.resolve() in w for w in seen)  # staging and commit: the checkout


def test_preview_status_is_sandboxed_too(repo, monkeypatch):
    """Status can run clean filters: the preview's status runs in a write-nothing sandbox (SC-008/011)."""
    project, root = repo
    argvs = []
    real = pj._run_bounded
    monkeypatch.setattr(pj, "_run_bounded", lambda argv, *a, **k: argvs.append(argv) or real(argv, *a, **k))
    (root / "a.txt").write_text("c\n")
    pj.commit_checkout(project, root, dry_run=True)
    status = [a for a in argvs if "status" in a]
    assert status and all(a[0] == "/usr/bin/sandbox-exec" and "(subpath" not in a[2] for a in status)


def test_route_holds_the_lifecycle_lock(repo, tmp_path, monkeypatch):
    project, root = repo
    import app as app_mod
    reg = tmp_path / "projects.yaml"
    reg.write_text(f"projects:\n  alpha:\n    path: {root}\n    verify: 'true'\n")
    monkeypatch.setattr(pj, "REGISTRY_PATH", reg)
    d = pj.CLAUDE_PROJECTS / pj._slug(str(root))
    d.mkdir(parents=True)
    (d / "s1.jsonl").write_text(json.dumps({"type": "user", "cwd": str(root), "entrypoint": "cli",
                                            "message": {"role": "user", "content": "hi"}}) + "\n")
    seen = {}

    def fake_commit(p, cwd, message, dry_run=False, merger=None):
        try:
            with pj.project_lock("alpha", exclusive=True, blocking=False):
                seen["locked"] = False
        except pj.ProjectBusy:
            seen["locked"] = True  # exclusive edits (path / confidential / remove) wait (SC-002)
        return {"repo": str(root), "branch": "main", "files": [], "committed": None}

    monkeypatch.setattr(pj, "commit_checkout", fake_commit)
    h = {"X-AgenticOS-Token": app_mod.REQUEST_TOKEN}
    r = app_mod.app.test_client().post("/api/projects/alpha/sessions/claude/s1/commit", json={"dry_run": True}, headers=h)
    assert r.status_code == 200 and seen["locked"] is True


def test_preview_runs_a_clean_filter_with_nothing_writable(repo):
    """A clean filter run by the preview's status cannot write the checkout or git dir (SC-011)."""
    project, root = repo
    marker = root / "preview-wrote"
    git(root, "config", "filter.spy.clean", f"touch {marker}; touch {root}/.git/spy; cat")
    (root / ".gitattributes").write_text("a.txt filter=spy\n")
    git(root, "add", ".gitattributes"); git(root, "commit", "-qm", "attrs")
    marker.unlink(missing_ok=True); (root / ".git" / "spy").unlink(missing_ok=True)  # setup ran the filter
    import os
    os.utime(root / "a.txt", (1, 1))  # stat-dirty: status re-reads it through the filter
    (root / "a.txt").write_text("changed\n")
    try:
        pj.commit_checkout(project, root, dry_run=True)
    except pj.ProjectError:
        pass  # a filter that fails under the read-only sandbox may fail the preview: still nothing written
    assert not marker.exists() and not (root / ".git" / "spy").exists()


def test_checkout_path_with_quotes_and_backslash_works_sandboxed(tmp_path, monkeypatch):
    """A valid folder name like My "app" must not break the sandbox profile (SC-015)."""
    monkeypatch.setattr(pj, "WORKTREE_ROOT", tmp_path / "wt")
    for k in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{k}_NAME", "t")
        monkeypatch.setenv(f"GIT_{k}_EMAIL", "t@t.invalid")
    root = tmp_path / 'My "app" \\x'
    root.mkdir()
    (root / "a.txt").write_text("a\n")
    git(root, "init", "-q", "-b", "main"); git(root, "add", "-A"); git(root, "commit", "-qm", "init")
    project = pj.Project(key="quoted", path=root, verify="true")
    (root / "a.txt").write_text("b\n")
    assert pj.commit_checkout(project, root, dry_run=True)["files"] == ["a.txt"]
    assert pj.commit_checkout(project, root, "quoted path")["committed"]
    with pytest.raises(pj.ProjectError, match="control"):
        pj.sandbox_profile([Path("/tmp/bad\nname")])


# ── Commit button colour (commit_state) ──────────────────────────────────────

def test_commit_state_main_checkout_dirty_then_clean(repo):
    project, root = repo
    assert pj.commit_state(project, root) == {"state": "clean", "files": 0, "ahead": 0}
    (root / "a.txt").write_text("c\n")
    assert pj.commit_state(project, root / "src") == {"state": "dirty", "files": 1, "ahead": 0}


def test_commit_state_worktree_unmerged_then_merged(repo):
    project, root = repo
    with pj.ticket_lock("alpha", "T-1"):
        wt = Path(pj.create_worktree(project, "T-1")["worktree"])
    (wt / "w.txt").write_text("w\n")
    assert pj.commit_state(project, wt)["state"] == "dirty"
    pj.commit_checkout(project, wt, "agent work")
    assert pj.commit_state(project, wt) == {"state": "unmerged", "files": 0, "ahead": 1}
    pj.merge_into_checkout(project, "T-1")
    assert pj.commit_state(project, wt) == {"state": "clean", "files": 0, "ahead": 0}


def test_commit_state_foreign_folder_is_neutral(repo, tmp_path):
    project, _ = repo
    other = tmp_path / "other"
    other.mkdir()
    git(other, "init", "-q")
    assert pj.commit_state(project, other) is None
    assert pj.commit_state(project, tmp_path) is None  # not a git checkout at all


def test_api_projects_rows_carry_commit_state(repo, tmp_path, monkeypatch):
    project, root = repo
    import app as app_mod
    reg = tmp_path / "projects.yaml"
    reg.write_text(f"projects:\n  alpha:\n    path: {root}\n    verify: 'true'\n")
    monkeypatch.setattr(pj, "REGISTRY_PATH", reg)
    d = pj.CLAUDE_PROJECTS / pj._slug(str(root))
    d.mkdir(parents=True)
    for sid in ("s1", "s2"):  # two sessions, one checkout: one status
        (d / f"{sid}.jsonl").write_text(json.dumps({"type": "user", "cwd": str(root), "entrypoint": "cli",
                                                    "message": {"role": "user", "content": "hi"}}) + "\n")
    (root / "a.txt").write_text("c\n")
    calls = []
    real = pj.readonly_status
    monkeypatch.setattr(pj, "readonly_status", lambda cwd: calls.append(cwd) or real(cwd))
    r = app_mod.app.test_client().get("/api/projects", headers={"X-AgenticOS-Token": app_mod.REQUEST_TOKEN})
    rows = next(p for p in r.get_json()["projects"] if p["key"] == "alpha")["sessions"]
    assert {s["commit_state"]["state"] for s in rows} == {"dirty"} and len(calls) == 1


# ── Commit & merge from a worktree row ───────────────────────────────────────

def _wt(project):
    with pj.ticket_lock(project.key, "T-1"):
        return Path(pj.create_worktree(project, "T-1")["worktree"])


def test_worktree_commit_then_merge_into_main(repo):
    project, root = repo
    wt = _wt(project)
    (wt / "w.txt").write_text("w\n")
    pre = pj.commit_checkout(project, wt, dry_run=True)
    assert (pre["into"], pre["ahead"], pre["files"]) == ("main", 1, ["w.txt"])
    out = pj.commit_checkout(project, wt, "agent work", merger=lambda ident: pj.merge_into_checkout(project, ident))
    assert out["committed"] and out["merged_head"] and (root / "w.txt").read_text() == "w\n"
    assert pj.commit_state(project, wt)["state"] == "clean"


def test_clean_worktree_ahead_merges_without_a_message(repo):
    project, root = repo
    wt = _wt(project)
    (wt / "w.txt").write_text("w\n")
    pj.commit_checkout(project, wt, "committed earlier")
    out = pj.commit_checkout(project, wt, "", merger=lambda ident: pj.merge_into_checkout(project, ident))
    assert out["committed"] is None and out["merged_head"] and (root / "w.txt").exists()


def test_merge_refusal_keeps_the_commit(repo, monkeypatch):
    project, root = repo
    import app as app_mod
    wt = _wt(project)
    (wt / "w.txt").write_text("w\n")
    monkeypatch.setattr(app_mod, "_running_jobs", {"other": {"project_key": "alpha"}})  # another run is open
    out = pj.commit_checkout(project, wt, "keep me", merger=lambda ident: app_mod._manual_merge(project, ident))
    assert out["committed"] and "another run" in out["merge_error"] and not (root / "w.txt").exists()
    assert git(wt, "log", "-1", "--format=%s") == "keep me"


def test_manual_merge_merges_when_no_run_is_open(repo, monkeypatch):
    project, root = repo
    import app as app_mod
    wt = _wt(project)
    (wt / "w.txt").write_text("w\n")
    monkeypatch.setattr(app_mod, "_running_jobs", {})
    monkeypatch.setattr(app_mod, "_ticket_confidential", lambda *a: False)
    out = pj.commit_checkout(project, wt, "m", merger=lambda ident: app_mod._manual_merge(project, ident))
    assert out["merged_head"] and (root / "w.txt").exists()


# ── Inspection fixes (CM-001..003) ───────────────────────────────────────────

def test_switched_worktree_is_refused_and_neutral(repo):
    project, root = repo
    wt = _wt(project)
    git(wt, "checkout", "-q", "-b", "elsewhere")
    (wt / "w.txt").write_text("w\n")
    with pytest.raises(pj.ProjectError, match="not agent/T-1"):
        pj.commit_checkout(project, wt, "m", merger=lambda i: pj.merge_into_checkout(project, i))
    assert pj.commit_state(project, wt) is None and not (root / "w.txt").exists()


def test_manual_merge_ignores_a_same_named_tag(repo, monkeypatch):
    project, root = repo
    import app as app_mod
    wt = _wt(project)
    (wt / "w.txt").write_text("w\n")
    pj.commit_checkout(project, wt, "branch work")
    git(root, "tag", "agent/T-1", "main")  # a tag shadowing the branch name, pointing at main's HEAD
    monkeypatch.setattr(app_mod, "_running_jobs", {})
    monkeypatch.setattr(app_mod, "_ticket_confidential", lambda *a: False)
    with pytest.raises(pj.ProjectError):  # an ambiguous branch name: the binding check refuses outright
        pj.commit_checkout(project, wt, "", merger=lambda i: app_mod._manual_merge(project, i))
    with pj.ticket_lock("alpha", "T-1"):
        app_mod._manual_merge(project, "T-1")  # merges refs/heads/agent/T-1, never the tag (CM-002)
    assert (root / "w.txt").exists()


def test_commit_state_one_status_per_checkout_root(repo, monkeypatch):
    project, root = repo
    calls = []
    real = pj.readonly_status
    monkeypatch.setattr(pj, "readonly_status", lambda cwd: calls.append(cwd) or real(cwd))
    cache = {}
    (root / "src" / "deep").mkdir()
    for cwd in (root, root / "src", root / "src" / "deep"):
        pj.commit_state(project, cwd, cache)
    assert len(calls) == 1


# ── Inspection fixes (CM-004..006) ───────────────────────────────────────────

def test_manual_merge_refused_while_an_agent_works_in_the_main_checkout(repo, monkeypatch):
    project, root = repo
    import app as app_mod
    wt = _wt(project)
    (wt / "w.txt").write_text("w\n")
    session_worker = {"record_extra": {"session_project": "alpha"}}  # no top-level project_key (SBR-005)
    monkeypatch.setattr(app_mod, "_running_jobs", {"s": session_worker})
    out = pj.commit_checkout(project, wt, "m", merger=lambda i: app_mod._manual_merge(project, i))
    assert out["committed"] and "another run" in out["merge_error"] and not (root / "w.txt").exists()


def test_merge_completes_despite_merge_options_no_commit(repo):
    project, root = repo
    wt = _wt(project)
    (wt / "w.txt").write_text("w\n")
    pj.commit_checkout(project, wt, "branch work")
    (root / "m.txt").write_text("m\n"); git(root, "add", "-A"); git(root, "commit", "-qm", "diverge")  # no fast-forward
    git(root, "config", "branch.main.mergeOptions", "--no-commit --squash")
    head = pj.merge_into_checkout(project, "T-1")
    assert head == git(root, "rev-parse", "HEAD") and (root / "w.txt").exists()
    assert git(root, "rev-list", "--parents", "-n1", "HEAD").count(" ") == 2  # a real two-parent merge commit
    assert subprocess.run(["git", "-C", str(root), "rev-parse", "-q", "--verify", "MERGE_HEAD"]).returncode != 0


def test_failing_status_is_cached_as_neutral(repo, monkeypatch):
    project, root = repo
    calls = []

    def boom(cwd):
        calls.append(cwd)
        raise pj.ProjectError("git status timed out")

    monkeypatch.setattr(pj, "readonly_status", boom)
    cache = {}
    assert [pj.commit_state(project, c, cache) for c in (root, root / "src")] == [None, None]
    assert len(calls) == 1


# ── Inspection fixes (CM-007..011) ───────────────────────────────────────────

def _branch_ahead_and_main_diverged(project, root):
    wt = _wt(project)
    (wt / "w.txt").write_text("w\n")
    pj.commit_checkout(project, wt, "branch work")
    (root / "m.txt").write_text("m\n"); git(root, "add", "-A"); git(root, "commit", "-qm", "diverge")
    return wt


def test_merge_ignores_an_inherited_ours_strategy(repo):
    project, root = repo
    _branch_ahead_and_main_diverged(project, root)
    git(root, "config", "branch.main.mergeOptions", "-s ours")
    pj.merge_into_checkout(project, "T-1")
    assert (root / "w.txt").read_text() == "w\n"  # the branch's change really landed (CM-007)


def test_merge_never_autostashes_overlapping_user_edits(repo):
    project, root = repo
    wt = _wt(project)
    (wt / "a.txt").write_text("branch\n")
    pj.commit_checkout(project, wt, "branch edits a.txt")
    git(root, "config", "merge.autoStash", "true")
    (root / "a.txt").write_text("my uncommitted edit\n")
    head = git(root, "rev-parse", "HEAD")
    with pytest.raises(pj.ProjectError):
        pj.merge_into_checkout(project, "T-1")
    assert git(root, "rev-parse", "HEAD") == head and (root / "a.txt").read_text() == "my uncommitted edit\n"  # (CM-008)


def test_merge_refused_into_a_checkout_mid_operation(repo):
    project, root = repo
    _branch_ahead_and_main_diverged(project, root)
    (Path(git(root, "rev-parse", "--absolute-git-dir")) / "rebase-merge").mkdir()
    head = git(root, "rev-parse", "HEAD")
    with pytest.raises(pj.ProjectError, match="rebase"):
        pj.merge_into_checkout(project, "T-1")
    assert git(root, "rev-parse", "HEAD") == head  # refused before anything ran (CM-009)


def test_activity_counts_runner_root_jobs_and_retiring_ones(monkeypatch):
    import app as app_mod
    monkeypatch.setattr(app_mod, "_running_jobs", {"free": {"skill": "_prompt"}})  # a /run job in the runner root
    monkeypatch.setattr(app_mod, "_RETIRING", {})
    assert not app_mod._project_runs_open("os", None, sessions=True)
    assert app_mod._project_runs_open("os", None, sessions=True, runner_root=True)  # (CM-010)
    monkeypatch.setattr(app_mod, "_running_jobs", {})
    monkeypatch.setattr(app_mod, "_RETIRING", {"c": {"record_extra": {"session_project": "os"}}})  # cancelled, still stopping
    assert app_mod._project_runs_open("os", None, sessions=True)  # (CM-011)
    assert not app_mod._project_runs_open("os", None)  # the auto-merge drain is unchanged


def test_merge_options_cleared_even_with_a_same_named_main_tag(repo):
    project, root = repo
    _branch_ahead_and_main_diverged(project, root)
    git(root, "tag", "main", "HEAD~1")  # makes `symbolic-ref --short HEAD` say heads/main
    git(root, "config", "branch.main.mergeOptions", "-s ours")
    pj.merge_into_checkout(project, "T-1")
    assert (root / "w.txt").read_text() == "w\n"  # (CM-012)


def test_stalled_job_counts_as_activity_until_it_is_stopped(monkeypatch):
    import app as app_mod
    from runner.modules import stall_detection as sd
    seen = []
    job = {"record_extra": {"session_project": "os"}}
    monkeypatch.setattr(app_mod, "_running_jobs", {"r": job})
    monkeypatch.setattr(app_mod, "_running_procs", {"r": object()})
    monkeypatch.setattr(app_mod, "_RETIRING", {})
    monkeypatch.setattr(app_mod, "_kill_group", lambda proc, *a: seen.append(app_mod._project_runs_open("os", None, sessions=True)))
    monkeypatch.setattr(app_mod, "_write_owner_record", lambda *a, **k: None)
    sd._stall(app_mod, type("S", (), {"emit": lambda *a, **k: None})(), "r", job)
    assert seen == [True] and app_mod._RETIRING == {}  # counted while being killed, gone after (CM-014)


# ── CM-013: runner-root launches are admitted through the runner checkout's gate ────

def test_runner_root_job_waits_for_a_merge_holding_the_gate(monkeypatch):
    import threading, time
    import app as app_mod
    monkeypatch.setattr(app_mod, "_runner_root_key", lambda: "os")
    monkeypatch.setattr(app_mod, "_running_jobs", {})
    gate = app_mod._merge_gate("os")
    gate.acquire()  # a manual merge between its activity check and the end of its merge
    t = threading.Thread(target=app_mod._publish_job, args=("free", {"skill": "_prompt"}))
    t.start()
    time.sleep(0.2)
    assert "free" not in app_mod._running_jobs  # not published mid-merge
    gate.release()
    t.join(5)
    assert "free" in app_mod._running_jobs


def test_routing_call_counts_as_runner_root_activity(monkeypatch):
    import app as app_mod
    monkeypatch.setattr(app_mod, "_runner_root_key", lambda: "os")
    monkeypatch.setattr(app_mod, "_running_jobs", {})
    monkeypatch.setattr(app_mod, "_RETIRING", {})
    assert not app_mod._project_runs_open("os", None, sessions=True, runner_root=True)
    with app_mod._root_activity():
        assert app_mod._project_runs_open("os", None, sessions=True, runner_root=True)
        assert not app_mod._project_runs_open("other", None, sessions=True)  # other projects unaffected
    assert app_mod._ROOT_ACTIVE == 0


def test_publish_without_a_runner_project_takes_no_gate(monkeypatch):
    import app as app_mod
    monkeypatch.setattr(app_mod, "_runner_root_key", lambda: None)
    monkeypatch.setattr(app_mod, "_running_jobs", {})
    app_mod._publish_job("x", {"skill": "_prompt"})
    assert "x" in app_mod._running_jobs


def test_runner_root_key_reads_the_file_only(tmp_path, monkeypatch):
    """Called on every job publish: no registry validation, no git (a full load spawned git per project)."""
    import app as app_mod
    reg = tmp_path / "projects.yaml"
    reg.write_text(f"projects:\n  self:\n    path: {app_mod._PROTO}\n  other:\n    path: {tmp_path}\n")
    monkeypatch.setattr(pj, "REGISTRY_PATH", reg)
    monkeypatch.setattr(app_mod, "_ROOT_KEY_CACHE", {})
    monkeypatch.setattr(pj, "_git", lambda *a, **k: pytest.fail("no git on the publish path"))
    monkeypatch.setattr(pj, "load_registry", lambda *a, **k: pytest.fail("no full registry load"))
    assert app_mod._runner_root_key() == "self"


# ── Inspection fixes (CM-015..019) ───────────────────────────────────────────

def test_merge_ignores_pull_twohead_ours(repo):
    project, root = repo
    _branch_ahead_and_main_diverged(project, root)
    git(root, "config", "pull.twohead", "ours")
    pj.merge_into_checkout(project, "T-1")
    assert (root / "w.txt").read_text() == "w\n"  # (CM-015)


def test_merge_never_overwrites_an_ignored_local_file(repo):
    project, root = repo
    (root / ".gitignore").write_text(".env\n"); git(root, "add", "-A"); git(root, "commit", "-qm", "ignore .env")
    wt = _wt(project)
    (wt / ".env").write_text("from the branch\n")
    git(wt, "add", "-f", ".env"); git(wt, "commit", "-qm", "branch tracks .env")
    (root / ".env").write_text("MY_SECRET=1\n")  # ignored, local only
    head = git(root, "rev-parse", "HEAD")
    with pytest.raises(pj.ProjectError):
        pj.merge_into_checkout(project, "T-1")
    assert (root / ".env").read_text() == "MY_SECRET=1\n" and git(root, "rev-parse", "HEAD") == head  # (CM-016)


def test_launch_gap_counts_as_activity_until_the_handshake(monkeypatch):
    import app as app_mod
    monkeypatch.setattr(app_mod, "_running_jobs", {})
    monkeypatch.setattr(app_mod, "_RETIRING", {})
    monkeypatch.setattr(app_mod, "_LAUNCHING", {"r": {"record_extra": {"session_project": "os"}}})  # Popen done, not registered
    assert app_mod._project_runs_open("os", None, sessions=True)
    killed = []
    monkeypatch.setattr(app_mod, "_kill_and_reap", lambda proc: killed.append(proc))
    assert app_mod._register_proc("r", object()) is False  # the run was cancelled in the gap: child killed
    assert killed and app_mod._LAUNCHING == {} and not app_mod._project_runs_open("os", None, sessions=True)  # (CM-017)


def test_two_registrations_of_one_checkout_share_gate_and_activity(tmp_path, monkeypatch):
    import app as app_mod
    reg = tmp_path / "projects.yaml"
    reg.write_text(f"projects:\n  a:\n    path: {tmp_path}/same\n  b:\n    path: {tmp_path}/same/\n  c:\n    path: {tmp_path}/other\n")
    (tmp_path / "same").mkdir(); (tmp_path / "other").mkdir()
    monkeypatch.setattr(pj, "REGISTRY_PATH", reg)
    monkeypatch.setattr(app_mod, "_ROOT_KEY_CACHE", {})
    assert app_mod._merge_gate("a") is app_mod._merge_gate("b") and app_mod._merge_gate("a") is not app_mod._merge_gate("c")
    monkeypatch.setattr(app_mod, "_running_jobs", {"j": {"project_key": "b"}})
    assert app_mod._project_runs_open("a", None, sessions=True) and not app_mod._project_runs_open("c", None, sessions=True)  # (CM-018)
    assert not app_mod._project_runs_open("a", None)  # the auto-drain stays per key, like its queue (CM-022)


def test_normal_completion_never_blocks_merges(monkeypatch):
    import app as app_mod
    monkeypatch.setattr(app_mod, "_running_jobs", {"r": {"record_extra": {"session_project": "os"}}})
    monkeypatch.setattr(app_mod, "_RETIRING", {})
    assert app_mod._end_job("r") and app_mod._RETIRING == {}  # its process has ended: not activity (CM-019)
    app_mod._FINALIZING.discard("r")


def test_no_launch_for_a_run_that_already_ended(monkeypatch):
    import app as app_mod
    monkeypatch.setattr(app_mod, "_running_jobs", {})
    monkeypatch.setattr(app_mod.subprocess, "Popen", lambda *a, **k: pytest.fail("must not launch"))
    with pytest.raises(app_mod._RunEnded):
        app_mod.run_agent_process("gone", ["true"], stream="text")
    assert "gone" not in app_mod._LAUNCHING  # (CM-020)


def test_successful_run_leaves_no_background_writer(tmp_path, monkeypatch):
    import os, time
    import app as app_mod
    monkeypatch.setattr(app_mod, "RUN_PROGRESS_DIR", tmp_path)
    monkeypatch.setattr(app_mod, "_running_jobs", {"ok": {"skill": "_prompt"}})
    monkeypatch.setattr(app_mod, "_running_procs", {})
    pidfile = tmp_path / "bg.pid"
    cmd = ["/bin/sh", "-c", f"(sleep 30 >/dev/null 2>&1 </dev/null & echo $! > {pidfile}); echo done"]
    out = app_mod.run_agent_process("ok", cmd, stream="text", timeout=20)
    assert out[-1] is True
    pid = int(pidfile.read_text())
    for _ in range(50):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        os.kill(pid, 9)
        pytest.fail("the background writer outlived its run")  # (CM-021)


def test_routing_helper_leaves_no_background_writer(tmp_path):
    import os, time
    import app as app_mod
    pidfile = tmp_path / "bg.pid"
    app_mod._run_grouped(["/bin/sh", "-c", f"(sleep 30 >/dev/null 2>&1 </dev/null & echo $! > {pidfile}); echo ok"], 20)
    pid = int(pidfile.read_text())
    for _ in range(50):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.1)
    os.kill(pid, 9)
    pytest.fail("the routing call's background writer outlived it")  # (CM-023)


def test_agent_tab_in_the_main_checkout_blocks_a_manual_merge(repo, monkeypatch):
    project, root = repo
    import app as app_mod
    from runner.modules import pty as pty_mod
    wt = _wt(project)
    (wt / "w.txt").write_text("w\n")
    monkeypatch.setattr(app_mod, "_running_jobs", {})
    monkeypatch.setattr(app_mod, "_ticket_confidential", lambda *a: False)
    tab = pty_mod.Terminal(term_id="t1", kind="resume", cwd=str(root / "src"))
    shell = pty_mod.Terminal(term_id="t2", kind="shell", cwd=str(root))
    monkeypatch.setattr(pty_mod, "TERMINALS", {"t1": tab, "t2": shell})
    out = pj.commit_checkout(project, wt, "m", merger=lambda i: app_mod._manual_merge(project, i))
    assert "interactive agent tab" in out["merge_error"] and not (root / "w.txt").exists()  # (CM-024)
    tab.alive, tab.cleaned = False, True  # its processes are proven gone
    assert pj.commit_checkout(project, wt, "", merger=lambda i: app_mod._manual_merge(project, i))["merged_head"]


def test_one_malformed_registry_path_never_hides_the_others(tmp_path, monkeypatch):
    import app as app_mod
    real = os.path.realpath

    def picky(p, *a, **k):
        if "bad" in str(p):
            raise ValueError("embedded null byte")
        return real(p, *a, **k)

    reg = tmp_path / "projects.yaml"
    reg.write_text(f"projects:\n  bad:\n    path: /x/bad\n  self:\n    path: {app_mod._PROTO}\n")
    monkeypatch.setattr(pj, "REGISTRY_PATH", reg)
    monkeypatch.setattr(app_mod, "_ROOT_KEY_CACHE", {})
    monkeypatch.setattr(app_mod.os.path, "realpath", picky)
    assert app_mod._runner_root_key() == "self"  # (CM-025)


def test_running_baseline_blocks_a_manual_merge(repo, monkeypatch):
    project, root = repo
    import app as app_mod
    wt = _wt(project)
    (wt / "w.txt").write_text("w\n")
    monkeypatch.setattr(app_mod, "_running_jobs", {})
    monkeypatch.setattr(app_mod, "_ticket_confidential", lambda *a: False)
    monkeypatch.setattr(app_mod, "_BASELINE_RUNS", {"alpha": 1})  # Run tests in flight
    out = pj.commit_checkout(project, wt, "m", merger=lambda i: app_mod._manual_merge(project, i))
    assert "tests are running" in out["merge_error"] and not (root / "w.txt").exists()  # (CM-026)
