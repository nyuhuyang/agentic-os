"""Dashboard registry writes: save/remove/cleanup, lifecycle lock, init_repo, history suggestions.
Fake project names only."""

import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runner"))

import projects as pj  # noqa: E402


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


def make_repo(root: Path) -> Path:
    (root / "tests").mkdir(parents=True)
    (root / "tests" / "check.sh").write_text("exit 0\n")
    (root / ".gitignore").write_text("data/\n")
    (root / "tracked.txt").write_text("t\n")
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "t@t.invalid")
    git(root, "config", "user.name", "t")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "init")
    (root / "data").mkdir()
    (root / "data" / "d.csv").write_text("d")
    return root


@pytest.fixture
def reg(tmp_path, monkeypatch):
    monkeypatch.setattr(pj, "WORKTREE_ROOT", tmp_path / "wt")
    monkeypatch.setenv("GIT_AUTHOR_NAME", "t"); monkeypatch.setenv("GIT_AUTHOR_EMAIL", "t@t.invalid")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "t"); monkeypatch.setenv("GIT_COMMITTER_EMAIL", "t@t.invalid")
    a, b = make_repo(tmp_path / "alpha"), make_repo(tmp_path / "beta")
    path = tmp_path / "projects.yaml"
    path.write_text(yaml.safe_dump({"projects": {
        "alpha": {"path": str(a), "kind": "python", "verify": "sh tests/check.sh", "seed": ["data"],
                  "confidential": False, "no_push": True},
        "beta": {"path": str(b), "verify": "sh tests/check.sh", "confidential": False},
    }}, sort_keys=False))
    monkeypatch.setattr(pj, "REGISTRY_PATH", path)
    return path, a, b


def h(path):
    return pj.registry_snapshot(path)[1]


def entry(repo, **kw):
    return {"path": str(repo), "verify": "sh tests/check.sh", "confidential": False, **kw}


def worktree(key, ident):
    p = pj.get_project(key)
    with pj.ticket_lock(key, ident):
        return p, Path(pj.create_worktree(p, ident)["worktree"])


# ── save ─────────────────────────────────────────────────────────────────────

def test_create_edit_remove_round_trip_keeps_others_and_order(reg, tmp_path):
    path, a, b = reg
    c = make_repo(tmp_path / "gamma")
    pj.save_project("gamma", entry(c, note="hello", seed=["data"]), h(path), create=True)
    assert list(pj.raw_entries(path.read_bytes())) == ["alpha", "beta", "gamma"]
    assert pj.load_registry()["gamma"].note == "hello"
    before_alpha = pj.raw_entries(path.read_bytes())["alpha"]
    pj.save_project("gamma", entry(c, note="changed", seed=["data"]), h(path))
    assert pj.load_registry()["gamma"].note == "changed"
    assert pj.raw_entries(path.read_bytes())["alpha"] == before_alpha
    assert list(before_alpha) == ["path", "kind", "verify", "seed", "confidential", "no_push"]
    pj.remove_project("gamma", h(path))
    assert list(pj.load_registry()) == ["alpha", "beta"]
    assert not (pj.WORKTREE_ROOT / "gamma").exists()  # throwaway check locks and the key dir are gone


@pytest.mark.parametrize("key, bad, msg", [
    ("gamma", {"verify": "   "}, "'verify' must be a non-empty string"),
    ("gamma", {"env": {"A": 1}}, "'env' must map"),
    ("gamma", {"note": 3}, "'note' must be a string"),
    ("gamma", {"path": "/nonexistent/x"}, "does not exist"),
    ("alpha", {}, "already exists"),
    ("bad key", {}, "must match"),
    ("../x", {}, "must match"),
])
def test_invalid_create_leaves_file_byte_identical(reg, tmp_path, key, bad, msg):
    path, a, b = reg
    c = make_repo(tmp_path / "gamma")
    before = path.read_bytes()
    with pytest.raises(pj.ProjectError, match=msg):
        pj.save_project(key, {**entry(c), **bad}, h(path), create=True)
    assert path.read_bytes() == before


def test_edit_unknown_key_and_path_under_worktree_root_refused(reg):
    path, a, b = reg
    before = path.read_bytes()
    with pytest.raises(pj.ProjectError, match="unknown project"):
        pj.save_project("nope", entry(a), h(path))
    p, wt = worktree("alpha", "T-1")
    with pytest.raises(pj.ProjectError, match="must not be inside"):  # a worktree is a repo, never a project root
        pj.save_project("gamma", entry(wt), h(path), create=True)
    assert path.read_bytes() == before


def test_seed_only_in_info_exclude_and_tracked_seed_refused_at_save(reg, tmp_path):
    path, a, b = reg
    c = make_repo(tmp_path / "gamma")
    (c / "local").mkdir()
    (c / "local" / "x").write_text("x")
    (c / ".git" / "info" / "exclude").write_text("local/\n")
    before = path.read_bytes()
    with pytest.raises(pj.ProjectError, match="not ignored"):
        pj.save_project("gamma", entry(c, seed=["local"]), h(path), create=True)
    with pytest.raises(pj.ProjectError, match="collides"):
        pj.save_project("gamma", entry(c, seed=["tracked.txt"]), h(path), create=True)
    assert path.read_bytes() == before
    assert not (pj.WORKTREE_ROOT / "gamma").exists() or pj._worktree_dirs("gamma") == []


def test_stale_hash_is_a_conflict(reg):
    path, a, b = reg
    stale = h(path)
    path.write_text(path.read_text() + "# hand edit\n")
    after = path.read_bytes()
    with pytest.raises(pj.RegistryConflict):
        pj.save_project("beta", entry(b, note="x"), stale)
    assert path.read_bytes() == after


def test_hand_edit_during_save_is_caught_by_the_final_recheck(reg, monkeypatch):
    path, a, b = reg
    real = pj.create_worktree

    def editing(project, ident):  # the editor saves while the throwaway seed check runs
        out = real(project, ident)
        path.write_text(path.read_text() + "# hand edit\n")
        return out
    monkeypatch.setattr(pj, "create_worktree", editing)
    with pytest.raises(pj.RegistryConflict):
        pj.save_project("beta", entry(b, seed=["data"]), h(path))
    assert path.read_text().endswith("# hand edit\n")


def test_note_round_trips_and_must_be_a_string(reg):
    path, a, b = reg
    pj.save_project("beta", entry(b, note="line one\nline two"), h(path))
    assert pj.load_registry()["beta"].note == "line one\nline two"
    with pytest.raises(pj.ProjectError, match="'note' must be a string"):
        pj.save_project("beta", entry(b, note=["x"]), h(path))


# ── lifecycle lock ───────────────────────────────────────────────────────────

def test_lifecycle_edits_wait_for_users_note_edits_do_not(reg, tmp_path):
    path, a, b = reg
    with pj.project_lock("beta"):  # a run/tab holds it shared
        with pytest.raises(pj.ProjectBusy):
            pj.save_project("beta", entry(b, confidential=True), h(path))
        with pytest.raises(pj.ProjectBusy):
            pj.save_project("beta", entry(make_repo(tmp_path / "other")), h(path))
        with pytest.raises(pj.ProjectBusy):
            pj.remove_project("beta", h(path))
        pj.save_project("beta", entry(b, note="ok while busy"), h(path))
    assert pj.load_registry()["beta"].note == "ok while busy"


def test_path_edit_refused_while_a_worktree_of_the_old_repo_exists(reg, tmp_path):
    path, a, b = reg
    worktree("alpha", "T-1")
    other = make_repo(tmp_path / "other")
    before = path.read_bytes()
    with pytest.raises(pj.ProjectError, match="cannot change while worktrees exist"):
        pj.save_project("alpha", entry(other, seed=["data"]), h(path))
    alias = tmp_path / "alias"
    os.symlink(a, alias)  # same repo, different spelling: sidecars record the old path literally (B002)
    with pytest.raises(pj.ProjectError, match="cannot change while worktrees exist"):
        pj.save_project("alpha", entry(alias, seed=["data"]), h(path))
    assert path.read_bytes() == before


def test_readding_with_leftover_worktrees_needs_the_exact_recorded_path(reg, tmp_path):
    path, a, b = reg
    worktree("alpha", "T-1")
    doc = yaml.safe_load(path.read_text())
    del doc["projects"]["alpha"]  # removed by hand, worktree left behind
    path.write_text(yaml.safe_dump(doc, sort_keys=False))
    alias = tmp_path / "alias"
    os.symlink(a, alias)
    with pytest.raises(pj.ProjectError, match="belong to another path"):
        pj.save_project("alpha", entry(alias, seed=["data"]), h(path), create=True)
    pj.save_project("alpha", entry(a, seed=["data"]), h(path), create=True)
    assert "alpha" in pj.load_registry()


def test_init_runs_after_the_checks_and_is_rolled_back_on_failure(reg, tmp_path):
    path, a, b = reg
    fresh = tmp_path / "fresh"
    with pytest.raises(pj.RegistryConflict):
        pj.save_project("gamma", entry(fresh, verify="true"), "stale", create=True)
    assert not fresh.exists()  # a stale hash creates nothing
    with pytest.raises(pj.ProjectError, match="already exists"):
        pj.save_project("alpha", entry(fresh, verify="true"), h(path), create=True)
    assert not fresh.exists()
    with pytest.raises(pj.ProjectError, match="'env' must map.*created and kept") as exc:
        pj.save_project("gamma", entry(fresh, verify="true", env={"A": 1}), h(path), create=True)
    assert exc.value.initialized == str(fresh) and (fresh / ".git").exists()  # never deleted (B006)
    pj.save_project("gamma", entry(fresh, verify="true"), h(path), create=True)  # retry without init
    assert "gamma" in pj.load_registry()


def test_init_folder_kept_when_a_hand_edit_lands_during_validation(reg, tmp_path, monkeypatch):
    path, a, b = reg
    fresh = tmp_path / "fresh"
    real = pj._validate_for_save

    def editing(*args):
        out = real(*args)
        path.write_text(path.read_text() + f"# hand edit naming {fresh}\n")
        return out
    monkeypatch.setattr(pj, "_validate_for_save", editing)
    with pytest.raises(pj.RegistryConflict) as exc:
        pj.save_project("gamma", entry(fresh, verify="true"), h(path), create=True)
    assert exc.value.initialized == str(fresh) and (fresh / ".git").exists()


def test_env_values_round_trip_verbatim(reg):
    path, a, b = reg
    env = {"MULTI": "line one\nline two", "PADDED": "  spaced  "}
    pj.save_project("beta", entry(b, env=env), h(path))
    assert pj.raw_entries(path.read_bytes())["beta"]["env"] == env


def test_registry_temp_files_are_gitignored():
    root = Path(__file__).resolve().parents[1]
    for name in ("projects.yaml", "projects.yaml.lock", ".projects.yaml.abc123.tmp"):
        assert subprocess.run(["git", "-C", str(root), "check-ignore", "-q", name]).returncode == 0, name


def test_seed_edit_runs_its_check_under_its_own_exclusive_lock(reg):
    path, a, b = reg
    done = []
    t = threading.Thread(target=lambda: done.append(pj.save_project("beta", entry(b, seed=["data"]), h(path))))
    t.start()
    t.join(timeout=60)
    assert done and pj.load_registry()["beta"].seed == ("data",)


def test_lock_files_never_collide_with_ticket_ids(reg):
    path, a, b = reg
    # git refuses "*.lock" branch names, so such a ticket never exists; a stray dir of that
    # name in the key dir must still not disturb the lifecycle lock, which lives elsewhere.
    _, wt = worktree("alpha", "PROJECT")
    (pj.WORKTREE_ROOT / "alpha" / "PROJECT.lock").mkdir()
    with pj.project_lock("alpha", exclusive=True, blocking=False):
        pass
    assert (pj.WORKTREE_ROOT / ".project-locks" / "alpha.lock").is_file() and wt.is_dir()
    assert not (pj.WORKTREE_ROOT / "alpha" / "alpha.lock").exists()


# ── remove ───────────────────────────────────────────────────────────────────

def test_remove_lists_worktrees_then_cleans_up_work_free_ones(reg):
    path, a, b = reg
    worktree("alpha", "T-1")
    worktree("alpha", "T-2")
    before = path.read_bytes()
    with pytest.raises(pj.WorktreesRemain) as exc:
        pj.remove_project("alpha", h(path))
    assert exc.value.worktrees == ["T-1", "T-2"] and path.read_bytes() == before
    out = pj.remove_project("alpha", h(path), cleanup=True)
    assert out["worktrees_removed"] == ["T-1", "T-2"] and "alpha" not in pj.load_registry()
    branches = subprocess.run(["git", "-C", str(a), "branch", "--list", "agent/*"], capture_output=True, text=True).stdout
    assert branches.strip() == ""
    assert (a / "tracked.txt").exists()  # project files untouched


@pytest.mark.parametrize("work", ["uncommitted", "commit"])
def test_cleanup_is_all_or_nothing(reg, work):
    path, a, b = reg
    worktree("alpha", "T-1")
    _, wt2 = worktree("alpha", "T-2")
    (wt2 / "new.txt").write_text("work")
    if work == "commit":
        git(wt2, "add", "new.txt")
        git(wt2, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "work")
    before = path.read_bytes()
    with pytest.raises(pj.ProjectError, match="nothing removed.*T-2"):
        pj.remove_project("alpha", h(path), cleanup=True)
    assert pj._worktree_dirs("alpha") == ["T-1", "T-2"] and path.read_bytes() == before


def test_broken_entry_is_removable_and_cleaned_via_minimal_descriptor(reg, monkeypatch):
    path, a, b = reg
    worktree("alpha", "T-1")
    import shutil
    shutil.rmtree(a / "data")  # the seed vanishes: the entry no longer parses
    errors = {}
    pj.load_registry(errors=errors)
    assert "alpha" in errors
    seen = []
    real = pj.uncommitted
    monkeypatch.setattr(pj, "uncommitted", lambda p, wt: seen.append(p.confidential) or real(p, wt))
    out = pj.remove_project("alpha", h(path), cleanup=True)
    assert out["worktrees_removed"] == ["T-1"] and seen == [True]  # confined preflight (REGUI-012)


def test_broken_entry_with_no_repo_refuses_cleanup(reg, tmp_path):
    path, a, b = reg
    worktree("alpha", "T-1")
    doc = yaml.safe_load(path.read_text())
    doc["projects"]["alpha"]["path"] = str(tmp_path / "gone")
    path.write_text(yaml.safe_dump(doc, sort_keys=False))
    before = path.read_bytes()
    with pytest.raises(pj.ProjectError, match="ownership"):
        pj.remove_project("alpha", h(path), cleanup=True)
    assert path.read_bytes() == before and pj._worktree_dirs("alpha") == ["T-1"]


def test_broken_entry_without_worktrees_is_removed(reg):
    path, a, b = reg
    doc = yaml.safe_load(path.read_text())
    doc["projects"]["alpha"]["colour"] = "red"
    path.write_text(yaml.safe_dump(doc, sort_keys=False))
    pj.remove_project("alpha", h(path))
    assert list(pj.raw_entries(path.read_bytes())) == ["beta"]


def test_sidecar_confidential_worktree_is_preflighted_confined(reg, monkeypatch):
    path, a, b = reg
    p, wt = worktree("beta", "T-1")
    with pj.ticket_lock("beta", "T-1"):
        pj.mark_confidential(p, "T-1")
    seen = []
    real = pj.uncommitted
    monkeypatch.setattr(pj, "uncommitted", lambda p, wt: seen.append(p.confidential) or real(p, wt))
    pj.remove_project("beta", h(path), cleanup=True)
    assert seen == [True]


def test_hand_edit_during_cleanup_keeps_the_editors_file(reg, monkeypatch):
    path, a, b = reg
    worktree("alpha", "T-1")
    real = pj.remove_worktree

    def editing(project, ident):
        real(project, ident)
        path.write_text(path.read_text() + "# hand edit\n")
    monkeypatch.setattr(pj, "remove_worktree", editing)
    with pytest.raises(pj.RegistryConflict, match="T-1"):
        pj.remove_project("alpha", h(path), cleanup=True)
    assert path.read_text().endswith("# hand edit\n") and "alpha" in pj.raw_entries(path.read_bytes())


# ── init_repo ────────────────────────────────────────────────────────────────

def test_init_repo(reg, tmp_path):
    root = pj.init_repo(str(tmp_path / "fresh"))
    log = subprocess.run(["git", "-C", str(root), "log", "--oneline"], capture_output=True, text=True).stdout
    assert len(log.splitlines()) == 1
    with pytest.raises(pj.ProjectError, match="already a git repository with commits"):
        pj.init_repo(str(root))
    empty = tmp_path / "empty"
    empty.mkdir()
    assert pj.init_repo(str(empty)) == empty and (empty / ".git").is_dir()
    with pytest.raises(pj.ProjectError, match="does not exist"):
        pj.init_repo(str(tmp_path / "missing" / "child"))


# ── history suggestions ──────────────────────────────────────────────────────

def test_session_dirs(reg, tmp_path, monkeypatch):
    path, a, b = reg
    other = make_repo(tmp_path / "other")
    (other / "sub").mkdir()
    plain = tmp_path / "plain"
    plain.mkdir()
    claude = tmp_path / "claude-projects"
    d = claude / "x"
    d.mkdir(parents=True)
    rows = {"s1": str(other / "sub"), "s2": str(plain), "s3": str(a), "s4": str(pj.WORKTREE_ROOT / "alpha" / "T-9")}
    for name, cwd in rows.items():
        (d / f"{name}.jsonl").write_text(json.dumps({"type": "user", "cwd": cwd}) + "\n")
    (d / "bad.jsonl").write_text("{not json\n")
    monkeypatch.setattr(pj, "CLAUDE_PROJECTS", claude)
    monkeypatch.setattr(pj, "CODEX_DB", tmp_path / "missing.sqlite")
    monkeypatch.setattr(pj, "_TEMP_ROOTS", ())
    pj._TOPLEVEL.clear()
    out = pj.session_dirs([a, b])
    assert [Path(os.path.expanduser(r["path"])).resolve() for r in out] == [other.resolve()]
    assert out[0]["agents"] == ["claude"] and out[0]["name"] == "other"
    db = tmp_path / "codex.sqlite"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE threads (cwd TEXT, updated_at REAL, archived INT)")
    con.execute("INSERT INTO threads VALUES (?, ?, 0)", (str(other), time.time()))
    con.commit(); con.close()
    monkeypatch.setattr(pj, "CODEX_DB", db)
    out = pj.session_dirs([a, b])
    assert out[0]["agents"] == ["claude", "codex"] and out[0]["sessions"] == 2


def test_registry_write_failure_after_init_keeps_and_reports_the_folder(reg, tmp_path, monkeypatch):
    path, a, b = reg
    fresh = tmp_path / "fresh"
    real = pj.tempfile.mkstemp
    monkeypatch.setattr(pj.tempfile, "mkstemp", lambda **kw: (_ for _ in ()).throw(PermissionError("read-only dir")))
    with pytest.raises(pj.ProjectError, match="cannot write.*created and kept") as exc:
        pj.save_project("gamma", entry(fresh, verify="true"), h(path), create=True)
    assert exc.value.initialized == str(fresh) and (fresh / ".git").exists()
    monkeypatch.setattr(pj.tempfile, "mkstemp", real)
    pj.save_project("gamma", entry(fresh, verify="true"), h(path), create=True)
    assert "gamma" in pj.load_registry()


# ── simpler add-project: optional verify, auto-init, confidential-only edit, locate, keys ──

def test_verify_is_optional_but_never_blank(reg, tmp_path):
    path, a, b = reg
    assert pj._parse_project("x", {"path": str(a)}).verify == ""
    for bad in ("   ", 3):
        with pytest.raises(pj.ProjectError, match="'verify' must be a non-empty string"):
            pj._parse_project("x", {"path": str(a), "verify": bad})
    p = pj._parse_project("x", {"path": str(a)})
    with pytest.raises(pj.ProjectError, match="no verify command"):
        pj.run_verify(p, a)


def test_create_auto_inits_missing_and_empty_folders_only(reg, tmp_path):
    path, a, b = reg
    missing, empty, inside = tmp_path / "missing", tmp_path / "empty", a / "sub-empty"
    empty.mkdir(); inside.mkdir()
    for key, folder in (("m", missing), ("e", empty), ("i", inside)):
        pj.save_project(key, {"path": str(folder), "confidential": False}, h(path), create=True)
        assert pj._is_repo_root(folder), key
    full = tmp_path / "full"
    full.mkdir(); (full / "data.csv").write_text("x")
    (a / "src").mkdir(); (a / "src" / "f.py").write_text("x")
    before = path.read_bytes()
    with pytest.raises(pj.NeedsCommit, match="1 file"):
        pj.save_project("n", {"path": str(full)}, h(path), create=True)
    with pytest.raises(pj.ProjectError, match="inside the git repository"):
        pj.save_project("n", {"path": str(a / "src")}, h(path), create=True)
    assert path.read_bytes() == before and not (full / ".git").exists()


def test_create_commits_existing_files_on_request(reg, tmp_path, monkeypatch):
    path, a, b = reg
    plain, bare = tmp_path / "plain", tmp_path / "bare"  # no repo yet / repo with no commit (AGE-127)
    for folder in (plain, bare):
        folder.mkdir(); (folder / "a.py").write_text("x"); (folder / ".gitignore").write_text("big/\n")
        (folder / "big").mkdir(); (folder / "big" / "blob").write_text("y")
    git(bare, "init", "-q")
    with pytest.raises(pj.NeedsCommit):
        pj.save_project("bare", {"path": str(bare)}, h(path), create=True)
    assert (bare / ".git").is_dir()  # a pre-existing .git is never removed
    for key, folder in (("plain", plain), ("bare", bare)):
        pj.save_project(key, {"path": str(folder)}, h(path), create=True, commit_existing=True)
        tracked = subprocess.run(["git", "-C", str(folder), "ls-files"], capture_output=True, text=True).stdout.split()
        assert sorted(tracked) == [".gitignore", "a.py"], key
    huge = tmp_path / "huge"
    huge.mkdir()
    with open(huge / "h.bin", "wb") as f:
        f.truncate(pj.MAX_INIT_FILE_BYTES + 1)
    with pytest.raises(pj.ProjectError, match="over 50 MB.*h.bin"):
        pj.save_project("huge", {"path": str(huge)}, h(path), create=True, commit_existing=True)
    assert not (huge / ".git").exists() and "huge" not in pj.raw_entries(path.read_bytes())


def test_set_confidential_changes_only_that_field(reg):
    path, a, b = reg
    doc = yaml.safe_load(path.read_text())
    doc["projects"]["beta"].update({"note": "", "env": {}, "seed": [], "kind": None})
    path.write_text(yaml.safe_dump(doc, sort_keys=False))
    before = dict(pj.raw_entries(path.read_bytes())["beta"])
    pj.set_confidential("beta", True, h(path))
    after = pj.raw_entries(path.read_bytes())["beta"]
    assert after.pop("confidential") is True and before.pop("confidential") is False and after == before
    with pj.project_lock("beta"):
        with pytest.raises(pj.ProjectBusy):
            pj.set_confidential("beta", False, h(path))
    with pytest.raises(pj.RegistryConflict):
        pj.set_confidential("beta", False, "stale")


@pytest.mark.parametrize("name, want", [("my-repo", "my-repo"), ("My Repo!", "My-Repo-"), ("研究", "project"),
                                        ("---", "project"), ("_x", "x"), ("alpha", "alpha-2"),
                                        ("Alpha", "Alpha-2")])
def test_derive_key(name, want):
    assert pj.derive_key(name, {"alpha": {}}) == want


def test_create_refuses_a_key_differing_only_in_case(reg, tmp_path):
    path, a, b = reg  # worktree folders are named by key; macOS folders ignore case (AGE-127)
    with pytest.raises(pj.ProjectError, match="'alpha' already exists"):
        pj.save_project("ALPHA", {"path": str(tmp_path / "new")}, h(path), create=True)
    assert not (tmp_path / "new").exists()


@pytest.fixture
def home(tmp_path, monkeypatch):
    h_ = tmp_path / "home"
    h_.mkdir()
    monkeypatch.setenv("HOME", str(h_))
    monkeypatch.setattr(pj, "_TEMP_ROOTS", ())
    monkeypatch.setattr(pj, "CLAUDE_PROJECTS", tmp_path / "no-claude")
    monkeypatch.setattr(pj, "CODEX_DB", tmp_path / "no-codex.sqlite")
    monkeypatch.setattr(pj, "WORKTREE_ROOT", tmp_path / "wt")
    return h_


def mk(root, *files):
    root.mkdir(parents=True)
    for f in files:
        (root / f).write_text("x")
    return root


def test_locate_folder(home):
    one = mk(home / "Documents" / "a" / "proj", "app.R", "README.md")
    mk(home / "code" / "proj", "main.py")
    mk(home / "Desktop" / "proj", "app.R", "README.md")      # never scanned
    mk(home / "Library" / "x" / "proj", "app.R", "README.md")
    os.symlink(one.parent, home / "code" / "linked")           # symlinked dirs are not followed
    mk(home / "Documents" / "deep" / "1" / "2" / "3" / "4" / "proj", "app.R", "README.md")  # too deep
    out = pj.locate_folder("proj", ["app.R", "README.md"])
    assert out == {"matches": ["~/Documents/a/proj"], "complete": True}
    assert len(pj.locate_folder("proj", [])["matches"]) == 0  # an empty drop matches only empty dirs
    mk(home / "work" / "proj")
    assert pj.locate_folder("proj", [])["matches"] == ["~/work/proj"]
    assert len(pj.locate_folder("proj", ["x-not-there"])["matches"]) == 0
    assert pj.locate_folder("proj", ["app.R"], budget_s=0)["complete"] is False
    for bad in ("a/b", "..", ".", ""):
        with pytest.raises(pj.ProjectError, match="single path component"):
            pj.locate_folder(bad, [])


def test_set_confidential_does_not_leak_through_a_yaml_alias(reg):
    path, a, b = reg
    path.write_text(f"projects:\n  alpha: &shared\n    path: {a}\n    confidential: true\n  beta: *shared\n")
    pj.set_confidential("alpha", False, h(path))
    raw = pj.raw_entries(path.read_bytes())
    assert raw["alpha"]["confidential"] is False and raw["beta"]["confidential"] is True


def test_locate_applies_one_eligibility_rule_to_history_too(home, tmp_path, monkeypatch):
    hidden = mk(home / ".archive" / "proj", "a.txt")
    nm = mk(home / "code" / "app" / "node_modules" / "proj", "a.txt")
    real_root = mk(tmp_path / "elsewhere" / "proj", "a.txt")
    os.symlink(real_root.parent, home / "Documents")  # a symlinked scan root is not traversed
    claude = tmp_path / "claude"
    (claude / "x").mkdir(parents=True)
    for i, cwd in enumerate((hidden, nm, home / "Documents" / "proj")):
        (claude / "x" / f"s{i}.jsonl").write_text(json.dumps({"type": "user", "cwd": str(cwd)}) + "\n")
    monkeypatch.setattr(pj, "CLAUDE_PROJECTS", claude)
    assert pj.locate_folder("proj", ["a.txt"]) == {"matches": [], "complete": True}


def test_locate_history_phase_honours_the_deadline(home, tmp_path, monkeypatch):
    claude = tmp_path / "claude"
    (claude / "x").mkdir(parents=True)
    for i in range(40):
        (claude / "x" / f"s{i}.jsonl").write_text(json.dumps({"type": "user", "cwd": f"/nowhere/{i}"}) + "\n")
    monkeypatch.setattr(pj, "CLAUDE_PROJECTS", claude)
    monkeypatch.setattr(pj, "_first_cwd", lambda f: time.sleep(0.05) or "/nowhere")
    t0 = time.monotonic()
    out = pj.locate_folder("proj", ["a"], budget_s=0.3)
    assert out["complete"] is False and time.monotonic() - t0 < 1.5


def test_locate_candidate_listing_honours_the_deadline(home, monkeypatch):
    big = mk(home / "Documents" / "proj", *[f"f{i}" for i in range(30)])
    real = pj.os.scandir

    class Slow:
        def __init__(self, d): self.it = real(d)
        def __enter__(self): return self
        def __exit__(self, *a): self.it.close()
        def __iter__(self):
            for e in self.it:
                time.sleep(0.05)
                yield e
    monkeypatch.setattr(pj.os, "scandir", lambda d: Slow(d) if Path(d) == big else real(d))
    t0 = time.monotonic()
    out = pj.locate_folder("proj", ["not-there"], budget_s=0.3)
    assert out["complete"] is False and time.monotonic() - t0 < 1.5


def test_first_cwd_reads_a_bounded_head(tmp_path):
    f = tmp_path / "s.jsonl"
    f.write_text("x" * 300000 + "\n" + json.dumps({"type": "user", "cwd": "/late"}) + "\n")
    assert pj._first_cwd(f) is None
    f.write_text(json.dumps({"type": "user", "cwd": "/early"}) + "\n" + "x" * 300000)
    assert pj._first_cwd(f) == "/early"


def test_first_cwd_keeps_records_with_unicode_line_separators(tmp_path):
    f = tmp_path / "s.jsonl"
    f.write_text(json.dumps({"type": "user", "cwd": "/a\u2028b", "message": "x\u2029y"}, ensure_ascii=False) + "\n",
                 encoding="utf-8")
    assert pj._first_cwd(f) == "/a\u2028b"
