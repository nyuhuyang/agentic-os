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
