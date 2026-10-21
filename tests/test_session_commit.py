"""Manual Commit on a session row (plan 2026-10-21-session-commit-button). Fixture repos only."""

import json
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
    monkeypatch.setattr(pj, "sandbox_prefix", lambda writable: seen.append(list(writable)) or real(writable))
    (root / "a.txt").write_text("c\n")
    assert not project.confidential and pj.commit_checkout(project, root, "msg")["committed"]
    assert seen and all(root.resolve() in w for w in seen)


def test_preview_status_is_sandboxed_too(repo, monkeypatch):
    """Status can run clean filters: the preview's status is confined like the commit (SC-008)."""
    project, root = repo
    calls = []
    real = pj._git_bytes
    monkeypatch.setattr(pj, "_git_bytes", lambda cwd, *a, confine=None, **k: calls.append((a, confine)) or real(cwd, *a, confine=confine, **k))
    (root / "a.txt").write_text("c\n")
    pj.commit_checkout(project, root, dry_run=True)
    status = [c for a, c in calls if "status" in a]
    assert status and all(c and root.resolve() in c for c in status)


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

    def fake_commit(p, cwd, message, dry_run=False):
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
