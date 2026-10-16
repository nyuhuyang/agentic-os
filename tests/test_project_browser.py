"""Read-only project file browser: git-based listing, path confinement, previews, routes.
Fake project names only."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runner"))

import projects as pj  # noqa: E402


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setattr(pj, "WORKTREE_ROOT", tmp_path / "wt")
    for k in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{k}_NAME", "t")
        monkeypatch.setenv(f"GIT_{k}_EMAIL", "t@t.invalid")
    root = tmp_path / "alpha"
    (root / "src" / "deep").mkdir(parents=True)
    (root / "src" / "deep" / "x.py").write_text("x\n")
    (root / "Zeta.txt").write_text("z\n")
    (root / "apple.md").write_text("a\n")
    (root / ".gitignore").write_text("data/\n*.log\n")
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "init")
    (root / "data").mkdir()
    (root / "data" / "big.csv").write_text("d")
    (root / "run.log").write_text("l")
    (root / "new.txt").write_text("n")
    (root / "empty").mkdir()
    path = tmp_path / "projects.yaml"
    path.write_text(yaml.safe_dump({"projects": {"alpha": {"path": str(root), "confidential": False}}}))
    monkeypatch.setattr(pj, "REGISTRY_PATH", path)
    return pj.get_project("alpha"), root


def names(listing):
    return [(e["name"], e["kind"], e["status"], e["ignored"]) for e in listing["entries"]]


def test_lists_tracked_and_untracked_marks_ignored_hides_git_sorts_folders_first(repo):
    project, root = repo
    got = names(pj.list_dir(project, "main", ""))
    assert got == [
        ("data", "dir", "", True),
        ("src", "dir", "", False),
        (".gitignore", "file", "", False),
        ("apple.md", "file", "", False),
        ("new.txt", "file", "?", False),
        ("run.log", "file", "", True),
        ("Zeta.txt", "file", "", False),
    ]  # no .git, no empty folder
    assert names(pj.list_dir(project, None, "src")) == [("deep", "dir", "", False)]
    with pytest.raises(pj.ProjectError, match="ignored"):
        pj.list_dir(project, "main", "data")


def test_cap_summarises_the_rest(repo, monkeypatch):
    project, _ = repo
    monkeypatch.setattr(pj, "BROWSE_CAP", 3)
    out = pj.list_dir(project, "main", "")
    assert len(out["entries"]) == 3 and out["more"] == 4


def test_status_marks_in_agent_worktree_and_index_untouched(repo):
    project, root = repo
    with pj.ticket_lock("alpha", "T-1"):
        wt = Path(pj.create_worktree(project, "T-1")["worktree"])
    (wt / "apple.md").write_text("changed\n")
    (wt / "fresh.txt").write_text("f")
    # stat-dirty but content-identical: a plain `git status` would refresh the index
    os.utime(wt / "Zeta.txt", (1, 1))
    index = Path(subprocess.run(["git", "-C", str(wt), "rev-parse", "--git-path", "index"],
                                capture_output=True, text=True, check=True).stdout.strip())
    index = index if index.is_absolute() else wt / index
    before = (index.read_bytes(), index.stat().st_mtime_ns)
    marks = {e["name"]: e["status"] for e in pj.list_dir(project, "T-1", "")["entries"]}
    assert marks["apple.md"] == "M" and marks["fresh.txt"] == "?" and marks["Zeta.txt"] == ""
    assert (index.read_bytes(), index.stat().st_mtime_ns) == before
    assert pj.browse_worktrees(project) == ["main", "T-1"]


@pytest.mark.parametrize("bad", ["../alpha", "/etc", "src/../../x", ".git", ".git/config", "~/x"])
def test_escaping_paths_refused(repo, bad):
    project, _ = repo
    with pytest.raises(pj.ProjectError):
        pj.list_dir(project, "main", bad)
    with pytest.raises(pj.ProjectError):
        pj.read_file(project, "main", bad)


def test_symlinks_listed_not_followed_out(repo, tmp_path):
    project, root = repo
    (tmp_path / "outside.txt").write_text("secret")
    (root / "out").symlink_to(tmp_path / "outside.txt")
    (root / "in").symlink_to(root / "apple.md")
    kinds = {e["name"]: e["kind"] for e in pj.list_dir(project, "main", "")["entries"]}
    assert kinds["out"] == "link" and kinds["in"] == "link"
    with pytest.raises(pj.ProjectError, match="outside"):
        pj.read_file(project, "main", "out")
    assert pj.read_file(project, "main", "in")["text"] == "a\n"


def test_unknown_worktree_refused(repo):
    project, _ = repo
    with pytest.raises(pj.ProjectError):
        pj.list_dir(project, "NOPE-1", "")
    with pytest.raises(pj.ProjectError):
        pj.list_dir(project, "../alpha", "")


def test_read_file_text_limit_and_binary(repo):
    project, root = repo
    (root / "exact.txt").write_text("a" * 10)
    (root / "over.txt").write_text("a" * 11)
    (root / "blob.bin").write_bytes(b"\x89PNG\0\0data")
    assert pj.read_file(project, "main", "exact.txt", limit=10)["text"] == "a" * 10
    over = pj.read_file(project, "main", "over.txt", limit=10)
    assert over["text"] is None and over["too_large"] and over["size"] == 11
    blob = pj.read_file(project, "main", "blob.bin")
    assert blob["text"] is None and blob["binary"] and blob["size"] == 10
    with pytest.raises(pj.ProjectError):
        pj.read_file(project, "main", "src")


# ── routes ───────────────────────────────────────────────────────────────────

@pytest.fixture
def client(repo, monkeypatch):
    import app as app_mod
    ran = []
    monkeypatch.setattr(app_mod.subprocess, "run", lambda argv, **kw: ran.append(argv))
    return app_mod, app_mod.app.test_client(), {"X-AgenticOS-Token": app_mod.REQUEST_TOKEN}, ran


def test_routes_need_token_and_reveal_is_gated(client, repo):
    app_mod, c, tok, ran = client
    assert c.get("/api/projects/alpha/tree").status_code == 403
    r = c.get("/api/projects/alpha/tree?path=src", headers=tok)
    assert r.status_code == 200 and r.get_json()["entries"][0]["name"] == "deep"
    assert r.get_json()["worktrees"] == ["main"]
    assert c.get("/api/projects/alpha/file?path=apple.md", headers=tok).get_json()["text"] == "a\n"
    assert c.get("/api/projects/alpha/file?path=../x", headers=tok).status_code == 400
    assert c.post("/api/projects/alpha/reveal", json={"path": "apple.md"}).status_code == 403
    app_mod._MAINTENANCE.set()
    try:
        assert c.post("/api/projects/alpha/reveal", json={"path": "apple.md"}, headers=tok).status_code == 409
    finally:
        app_mod._MAINTENANCE.clear()
    assert ran == []
    assert c.post("/api/projects/alpha/reveal", json={"path": "apple.md"}, headers=tok).status_code == 200
    assert ran == [["open", "-R", str((repo[1] / "apple.md").resolve())]]
    assert c.post("/api/projects/alpha/reveal", json={"path": "/etc"}, headers=tok).status_code == 400


def test_wholly_untracked_folder_expands(repo):
    project, root = repo
    (root / "newdir" / "sub").mkdir(parents=True)
    (root / "newdir" / "file.py").write_text("x")
    (root / "newdir" / "sub" / "deep.txt").write_text("y")
    (root / "newdir" / "debug.log").write_text("ignored by *.log")
    top = {e["name"]: e for e in pj.list_dir(project, "main", "")["entries"]}
    assert top["newdir"]["kind"] == "dir" and top["newdir"]["status"] == "?"
    inside = [(e["name"], e["kind"], e["status"], e["ignored"]) for e in pj.list_dir(project, "main", "newdir")["entries"]]
    assert inside == [("sub", "dir", "?", False), ("debug.log", "file", "", True), ("file.py", "file", "?", False)]  # UI8-02
    assert [e["name"] for e in pj.list_dir(project, "main", "newdir/sub")["entries"]] == ["deep.txt"]


@pytest.mark.parametrize("swap", ["file", "ancestor"])
def test_a_path_swapped_after_the_check_is_refused(repo, tmp_path, monkeypatch, swap):
    project, root = repo
    outside = tmp_path / "outside"
    (outside / "deep").mkdir(parents=True)
    (outside / "deep" / "x.py").write_text("SECRET")
    real_check = pj._browse_path

    def check_then_swap(r, rel):  # an agent swaps the path between the check and the open (REV31-01)
        out = real_check(r, rel)
        if swap == "file":
            (root / "src" / "deep" / "x.py").unlink()
            (root / "src" / "deep" / "x.py").symlink_to(outside / "deep" / "x.py")
        else:
            import shutil
            shutil.rmtree(root / "src" / "deep")
            (root / "src" / "deep").symlink_to(outside / "deep")
        return out
    monkeypatch.setattr(pj, "_browse_path", check_then_swap)
    with pytest.raises(pj.ProjectError):
        pj.read_file(project, "main", "src/deep/x.py")


def test_a_folder_swapped_after_the_check_is_not_listed(repo, tmp_path, monkeypatch):
    project, root = repo
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "private.txt").write_text("p")
    real_check = pj._browse_path

    def check_then_swap(r, rel):
        out = real_check(r, rel)
        import shutil
        shutil.rmtree(root / "src" / "deep")
        (root / "src" / "deep").symlink_to(outside)
        return out
    monkeypatch.setattr(pj, "_browse_path", check_then_swap)
    with pytest.raises(pj.ProjectError):
        pj.list_dir(project, "main", "src/deep")


def test_listing_reports_file_sizes(repo):
    project, root = repo
    sizes = {e["name"]: e["size"] for e in pj.list_dir(project, "main", "")["entries"]}
    assert sizes["apple.md"] == 2 and sizes["Zeta.txt"] == 2 and sizes["src"] is None  # REV32-01
