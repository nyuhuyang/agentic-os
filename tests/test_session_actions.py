"""Session rename/remove (dashboard UI plan, part A): the only writes to ~/.claude and ~/.codex.
Fixture stores under tmp_path; fake project names only."""

import errno
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runner"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import projects as pj  # noqa: E402


@pytest.fixture
def store(tmp_path, monkeypatch):
    proj = tmp_path / "proj"
    proj.mkdir()
    subprocess.run(["git", "init", "-q", str(proj)], check=True)
    monkeypatch.setattr(pj, "CLAUDE_PROJECTS", tmp_path / "claude")
    monkeypatch.setattr(pj, "CODEX_DB", tmp_path / "state_5.sqlite")
    monkeypatch.setattr(pj, "WORKTREE_ROOT", tmp_path / "wt")
    monkeypatch.setattr(pj, "SESSION_TRASH", tmp_path / "trash")
    reg = tmp_path / "projects.yaml"
    reg.write_text(yaml.safe_dump({"projects": {"demo": {"path": str(proj), "confidential": False}}}))
    monkeypatch.setattr(pj, "REGISTRY_PATH", reg)
    db = sqlite3.connect(tmp_path / "state_5.sqlite")
    db.execute("CREATE TABLE threads (id TEXT, cwd TEXT, name TEXT, title TEXT, first_user_message TEXT, "
               "updated_at INTEGER, tokens_used INTEGER, git_branch TEXT, source TEXT, archived INTEGER, "
               "archived_at INTEGER, rollout_path TEXT)")
    db.commit()
    db.close()
    return pj.get_project("demo"), tmp_path


def claude(root, sid, cwd, age=600, sidecar=False):
    d = root / "claude" / pj._slug(cwd)
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{sid}.jsonl"
    f.write_text(json.dumps({"type": "user", "cwd": str(cwd), "entrypoint": "cli",
                             "message": {"role": "user", "content": "hello"}}) + "\n")
    if sidecar:
        (d / sid).mkdir()
        (d / sid / "note.txt").write_text("x")
    os.utime(f, (time.time() - age, time.time() - age))
    return f


def codex(root, tid, cwd, age=600):
    rollout = root / f"rollout-{tid}.jsonl"
    rollout.write_text("{}\n")
    os.utime(rollout, (time.time() - age, time.time() - age))
    db = sqlite3.connect(root / "state_5.sqlite")
    db.execute("INSERT INTO threads VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
               (tid, str(cwd), None, "t", "first", 1, 0, "main", "cli", 0, None, str(rollout)))
    db.commit()
    db.close()


def thread(root, tid):
    db = sqlite3.connect(root / "state_5.sqlite")
    try:
        return db.execute("SELECT name, archived, archived_at FROM threads WHERE id = ?", (tid,)).fetchone()
    finally:
        db.close()


def titles(project):
    return {r["id"]: r["title"] for r in pj.project_sessions(project)}


def test_claude_rename_appends_one_record_and_the_panel_shows_it(store):
    project, root = store
    f = claude(root, "c1", project.path)
    before = f.read_bytes()
    t = pj.session_target(project, "claude", "c1")
    mtime = f.stat().st_mtime_ns
    assert pj.rename_session(t, "  New name  ") == "New name"
    assert f.stat().st_mtime_ns == mtime  # neither "live" nor bumped in the picker (FB-03)
    added = f.read_bytes()[len(before):]
    assert added.endswith(b"\n") and added.count(b"\n") == 1
    assert json.loads(added) == {"type": "custom-title", "customTitle": "New name", "sessionId": "c1"}
    assert titles(project)["c1"] == "New name"


def test_codex_rename_sets_name(store):
    project, root = store
    codex(root, "x1", project.path)
    pj.rename_session(pj.session_target(project, "codex", "x1"), "Renamed")
    assert thread(root, "x1")[0] == "Renamed" and titles(project)["x1"] == "Renamed"
    assert not (root / "session_index.jsonl").exists()  # Codex's shared index is never written (R24-01)


def test_claude_remove_moves_transcript_and_sidecar_then_clash_is_refused(store):
    project, root = store
    f = claude(root, "c2", project.path, sidecar=True)
    out = pj.remove_session(pj.session_target(project, "claude", "c2"))
    trash = root / "trash" / f.parent.name
    assert Path(out["trash"]) == trash / "c2.jsonl" and (trash / "c2" / "note.txt").exists()
    assert not f.exists() and not (f.parent / "c2").exists() and "c2" not in titles(project)
    f2 = claude(root, "c2", project.path)  # same id again: the trash already holds one
    with pytest.raises(pj.ProjectError, match="already holds"):
        pj.remove_session(pj.session_target(project, "claude", "c2"))
    assert f2.exists()


def test_codex_remove_archives(store):
    project, root = store
    codex(root, "x2", project.path)
    pj.remove_session(pj.session_target(project, "codex", "x2"))
    name, archived, archived_at = thread(root, "x2")
    assert archived == 1 and archived_at and "x2" not in titles(project)
    # like Codex's own archive: the rollout moved into archived_sessions/, the row points there (FB4-02)
    assert not (root / "rollout-x2.jsonl").exists() and (root / "archived_sessions" / "rollout-x2.jsonl").exists()
    db = sqlite3.connect(root / "state_5.sqlite")
    assert db.execute("SELECT rollout_path FROM threads WHERE id='x2'").fetchone()[0].endswith("archived_sessions/rollout-x2.jsonl")
    db.close()


def test_failed_writes_leave_the_session_as_it_was(store, monkeypatch):
    project, root = store
    f = claude(root, "c3", project.path, sidecar=True)
    before = f.read_bytes()
    t = pj.session_target(project, "claude", "c3")
    real_write = os.write
    monkeypatch.setattr(pj.os, "write", lambda fd, data: real_write(fd, data[:5]))  # short write
    with pytest.raises(OSError, match="short write"):
        pj.rename_session(t, "half")
    assert f.read_bytes() == before  # truncated back, byte-identical
    monkeypatch.setattr(pj.os, "write", real_write)

    real_rename = os.rename
    def rename(src, dst):
        if Path(src).name == "c3":  # the sidecar move fails
            raise OSError(errno.EACCES, "denied")
        return real_rename(src, dst)
    monkeypatch.setattr(pj.os, "rename", rename)
    with pytest.raises(OSError):
        pj.remove_session(t)
    assert f.read_bytes() == before and (f.parent / "c3" / "note.txt").exists()
    assert not (root / "trash" / f.parent.name / "c3.jsonl").exists()
    monkeypatch.setattr(pj.os, "rename", real_rename)

    real_stat = os.stat
    def stat(path, *a, **k):
        st = real_stat(path, *a, **k)
        if Path(path) == root / "trash" / f.parent.name:  # trash on another filesystem
            return os.stat_result((st.st_mode, st.st_ino, st.st_dev + 1, *tuple(st)[3:]))
        return st
    monkeypatch.setattr(pj.os, "stat", stat)
    with pytest.raises(pj.ProjectError, match="another filesystem"):
        pj.remove_session(t)
    assert f.read_bytes() == before


def test_refusals_change_nothing(store):
    project, root = store
    f = claude(root, "c4", project.path)
    fresh = claude(root, "c5", project.path, age=10)
    claude(root, "foreign", root / "elsewhere")
    codex(root, "x4", project.path)
    snapshot = (f.read_bytes(), fresh.read_bytes(), thread(root, "x4"))
    with pytest.raises(pj.SessionBusy):  # held by a tab / job
        pj.check_session_idle(pj.session_target(project, "claude", "c4"), {("claude", "c4")})
    with pytest.raises(pj.SessionBusy, match="2 minutes"):
        pj.check_session_idle(pj.session_target(project, "claude", "c5"), set())
    with pytest.raises(pj.SessionNotFound):
        pj.session_target(project, "claude", "foreign")
    with pytest.raises(pj.SessionNotFound):
        pj.session_target(project, "claude", "nope")
    for bad in ("../c4", "c4/x", "", ".hidden"):
        with pytest.raises(pj.ProjectError):
            pj.session_target(project, "claude", bad)
    t = pj.session_target(project, "codex", "x4")
    for title in ("", "   ", "a" * 201, "line\nbreak", "bell\x07"):
        with pytest.raises(pj.ProjectError):
            pj.rename_session(t, title)
    assert (f.read_bytes(), fresh.read_bytes(), thread(root, "x4")) == snapshot


def test_session_lock_refuses_concurrent_admission(store):
    with pj.session_lock("claude", "c6"):
        with pytest.raises(pj.SessionBusy):
            with pj.session_lock("claude", "c6"):
                pass
    with pj.session_lock("claude", "c6"):
        pass


# ── routes ───────────────────────────────────────────────────────────────────

@pytest.fixture
def client(store, monkeypatch):
    import app as app_mod
    monkeypatch.setattr(app_mod, "_running_jobs", {})
    return app_mod, app_mod.app.test_client(), {"X-AgenticOS-Token": app_mod.REQUEST_TOKEN}


def test_routes_rename_remove_and_status_codes(client, store):
    app_mod, c, tok = client
    project, root = store
    f = claude(root, "c7", project.path)
    base = "/api/projects/demo/sessions/claude/c7"
    assert c.post(f"{base}/rename", json={"title": "x"}).status_code == 403  # token
    assert c.post(f"{base}/rename", json={"title": ""}, headers=tok).status_code == 400
    assert c.post("/api/projects/demo/sessions/claude/zzz/rename", json={"title": "x"}, headers=tok).status_code == 404
    app_mod._MAINTENANCE.set()
    try:
        assert c.post(f"{base}/remove", headers=tok).status_code == 409
    finally:
        app_mod._MAINTENANCE.clear()
    app_mod._running_jobs["r1"] = {"agent": "claude", "agent_session_id": "c7"}  # a running job holds it
    assert c.post(f"{base}/remove", headers=tok).status_code == 409 and f.exists()
    app_mod._running_jobs.clear()
    app_mod._SESSION_CLAIMS["r2"] = ("claude", "c7")  # a retry about to resume it
    assert c.post(f"{base}/rename", json={"title": "y"}, headers=tok).status_code == 409
    app_mod._SESSION_CLAIMS.clear()
    assert c.post(f"{base}/rename", json={"title": "Done"}, headers=tok).get_json()["title"] == "Done"
    assert c.post(f"{base}/remove", headers=tok).status_code == 200 and not f.exists()  # our rename keeps it idle (FB-03)


def test_resume_tab_exposes_its_session_and_waits_for_the_lock(client, store, monkeypatch):
    app_mod, c, tok = client
    project, root = store
    claude(root, "c8", project.path)
    import runner.modules.pty as pty_mod
    monkeypatch.setattr(pty_mod, "_spawn", lambda t, argv, env, cols, rows, sio: setattr(t, "pid", 1))
    monkeypatch.setattr(pty_mod, "TERMINALS", {})
    with pj.session_lock("claude", "c8"):  # a remove is in flight
        out = pty_mod.open_terminal({"kind": "resume", "agent": "claude", "session_id": "c8",
                                     "project_key": "demo", "cwd": str(project.path)}, None)
    assert "busy" in out["error"] and not pty_mod.TERMINALS
    out = pty_mod.open_terminal({"kind": "resume", "agent": "claude", "session_id": "c8",
                                 "project_key": "demo", "cwd": str(project.path)}, None)
    assert out["session_id"] == "c8" and ("claude", "c8") in app_mod._live_session_ids()
    for t in pty_mod.TERMINALS.values():
        t.holds.close()


def test_ownership_uses_resolved_paths(store, tmp_path):
    project, root = store
    (root / "foreign").mkdir()
    d = root / "claude" / pj._slug(project.path)
    d.mkdir(parents=True, exist_ok=True)
    (d / "trav.jsonl").write_text(json.dumps({"type": "user", "cwd": f"{project.path}/../foreign", "entrypoint": "cli",
                                              "message": {"role": "user", "content": "x"}}) + "\n")
    (project.path / "link").symlink_to(root / "foreign")
    (d / "sym.jsonl").write_text(json.dumps({"type": "user", "cwd": f"{project.path}/link", "entrypoint": "cli",
                                             "message": {"role": "user", "content": "x"}}) + "\n")
    for sid in ("trav", "sym"):
        with pytest.raises(pj.SessionNotFound):  # IR9-03
            pj.session_target(project, "claude", sid)
    db = sqlite3.connect(root / "state_5.sqlite")
    db.execute("INSERT INTO threads VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
               ("x-out", str(project.path), None, "t", "f", 1, 0, "main", "cli", 0, None, "/etc/hosts"))
    db.commit()
    db.close()
    with pytest.raises(pj.ProjectError, match="no rollout inside"):
        pj.session_target(project, "codex", "x-out")


def test_codex_database_symlink_out_of_the_store_is_refused(store, tmp_path, monkeypatch):
    project, root = store
    codex(root, "x9", project.path)
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (root / "state_5.sqlite").rename(outside / "state_5.sqlite")
    (root / "state_5.sqlite").symlink_to(outside / "state_5.sqlite")
    with pytest.raises(pj.ProjectError, match="outside the Codex store"):  # UI10-04
        pj.session_target(project, "codex", "x9")


def test_codex_archive_dir_symlink_out_of_the_store_is_refused(store, tmp_path):
    project, root = store
    codex(root, "xb", project.path)
    outside = tmp_path / "outside-archive"
    outside.mkdir()
    (root / "archived_sessions").symlink_to(outside)
    with pytest.raises(pj.ProjectError, match="outside the Codex store"):
        pj.remove_session(pj.session_target(project, "codex", "xb"))
    assert (root / "rollout-xb.jsonl").exists() and not list(outside.iterdir())  # CR-02


def test_trashed_transcripts_still_count_for_usage(store, monkeypatch, tmp_path):
    import usage_reader as ur
    project, root = store
    f = claude(root, "u1", project.path)
    monkeypatch.setattr(ur, "PROJECTS_DIR", root / "claude")
    monkeypatch.setattr(ur, "SESSION_TRASH_DIR", root / "trash")
    before = sorted(p.name for p, _ in ur._claude_jsonl_files())
    pj.remove_session(pj.session_target(project, "claude", "u1"))
    assert sorted(p.name for p, _ in ur._claude_jsonl_files()) == before == ["u1.jsonl"]  # IR19-02


def test_codex_rollouts_include_archived_ones(tmp_path, monkeypatch):
    import usage_reader as ur
    (tmp_path / "sessions" / "2026").mkdir(parents=True)
    (tmp_path / "sessions" / "2026" / "live.jsonl").write_text("{}\n")
    (tmp_path / "archived_sessions").mkdir()
    (tmp_path / "archived_sessions" / "gone.jsonl").write_text("{}\n")
    monkeypatch.setattr(ur, "CODEX_SESSIONS_DIR", tmp_path / "sessions")
    assert sorted(p.name for p in ur._codex_rollouts()) == ["gone.jsonl", "live.jsonl"]  # quota and tokens both (R21-02)


def test_snapshot_script_reads_archived_rollouts(tmp_path, monkeypatch):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runner" / "scripts"))
    import codex_snap_rate_limits as snapmod
    (tmp_path / "sessions").mkdir()
    (tmp_path / "archived_sessions").mkdir()
    rec = {"timestamp": "2026-10-16T05:00:00Z", "payload": {"type": "token_count",
           "rate_limits": {"limit_id": "codex", "primary": {"used_percent": 80}}}}
    (tmp_path / "archived_sessions" / "a.jsonl").write_text(json.dumps(rec) + "\n")
    monkeypatch.setattr(snapmod, "SESSIONS_DIR", tmp_path / "sessions")
    out = snapmod.snap()
    assert out and "80" in json.dumps(out)  # REV23-02