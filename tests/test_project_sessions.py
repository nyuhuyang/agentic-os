"""Phase 1 session readers against fixture JSONL / SQLite (fake paths only)."""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runner"))

import projects as pj  # noqa: E402

PROJ = "/a/proj"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(pj, "CLAUDE_PROJECTS", tmp_path / "claude")
    monkeypatch.setattr(pj, "CODEX_DB", tmp_path / "state_5.sqlite")
    monkeypatch.setattr(pj, "WORKTREE_ROOT", Path("/wt"))
    project = pj.Project(key="demo", path=Path(PROJ), verify="true")
    return tmp_path, project


def claude_session(root, sid, cwd, *records, entrypoint="cli", slug_of=None):
    d = root / "claude" / pj._slug(slug_of or cwd)
    d.mkdir(parents=True, exist_ok=True)
    lines = [{"type": "user", "cwd": cwd, "entrypoint": entrypoint, "gitBranch": "main",
              "message": {"role": "user", "content": "first real question"}},
             {"type": "assistant", "message": {"content": []}}, *records]
    (d / f"{sid}.jsonl").write_text("\n".join(json.dumps(x, separators=(",", ":")) for x in lines) + "\n")


def codex_db(root, rows):
    db = sqlite3.connect(root / "state_5.sqlite")
    db.execute("CREATE TABLE threads (id TEXT, cwd TEXT, name TEXT, title TEXT, first_user_message TEXT, "
               "updated_at INTEGER, tokens_used INTEGER, git_branch TEXT, source TEXT, archived INTEGER)")
    db.executemany("INSERT INTO threads VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    db.commit()
    db.close()


def ids(rows):
    return sorted(r["id"] for r in rows)


def test_cwd_boundary(env):
    root, project = env
    claude_session(root, "in", PROJ)
    claude_session(root, "sub", PROJ + "/src", slug_of=PROJ)
    claude_session(root, "sibling", "/a/proj2")  # same slug prefix, different project
    claude_session(root, "worktree", "/wt/demo/T-1")
    codex_db(root, [("c-in", PROJ, None, "t", None, 1, 0, "main", "cli", 0),
                    ("c-sib", "/a/proj2", None, "t", None, 1, 0, "main", "cli", 0)])
    assert ids(pj.claude_sessions(project)) == ["in", "sub", "worktree"]
    assert ids(pj.codex_sessions(project)) == ["c-in"]


def test_noninteractive_sessions_excluded(env):
    root, project = env
    claude_session(root, "human", PROJ)
    claude_session(root, "headless", PROJ, entrypoint="sdk-cli")
    codex_db(root, [("cli", PROJ, None, "t", None, 1, 0, "", "cli", 0),
                    ("ide", PROJ, None, "t", None, 1, 0, "", "vscode", 0),
                    ("exec", PROJ, None, "t", None, 1, 0, "", "exec", 0),
                    ("sub", PROJ, None, "t", None, 1, 0, "", '{"subagent":{}}', 0),
                    ("arch", PROJ, None, "t", None, 1, 0, "", "cli", 1)])
    assert ids(pj.claude_sessions(project)) == ["human"]
    assert ids(pj.codex_sessions(project)) == ["cli", "ide"]


def test_title_precedence(env):
    root, project = env
    claude_session(root, "custom", PROJ, {"type": "ai-title", "aiTitle": "ai one"},
                   {"type": "custom-title", "customTitle": "mine"}, {"type": "ai-title", "aiTitle": "ai two"})
    claude_session(root, "ai", PROJ, {"type": "ai-title", "aiTitle": "ai one"}, {"type": "ai-title", "aiTitle": "ai last"})
    claude_session(root, "plain", PROJ)
    titles = {r["id"]: r["title"] for r in pj.claude_sessions(project)}
    assert titles == {"custom": "mine", "ai": "ai last", "plain": "first real question"}
    codex_db(root, [("named", PROJ, "user name", "auto", "first", 1, 0, "", "cli", 0),
                    ("titled", PROJ, None, "auto", "first", 1, 0, "", "cli", 0),
                    ("bare", PROJ, None, None, "first msg", 1, 0, "", "cli", 0)])
    assert {r["id"]: r["title"] for r in pj.codex_sessions(project)} == {
        "named": "user name", "titled": "auto", "bare": "first msg"}


def test_meta_and_command_messages_are_not_titles(env):
    root, project = env
    d = root / "claude" / pj._slug(PROJ)
    d.mkdir(parents=True)
    lines = [{"type": "user", "cwd": PROJ, "isMeta": True, "message": {"content": "meta"}},
             {"type": "user", "cwd": PROJ, "message": {"content": "<command-name>/clear</command-name>"}},
             {"type": "user", "cwd": PROJ, "message": {"content": [{"type": "text", "text": "the real one"}]}}]
    (d / "s.jsonl").write_text("\n".join(json.dumps(x) for x in lines))
    assert pj.claude_sessions(project)[0]["title"] == "the real one"


def test_unknown_formats_degrade(env):
    root, project = env
    d = root / "claude" / pj._slug(PROJ)
    d.mkdir(parents=True)
    (d / "garbage.jsonl").write_text("not json\n{}\n")
    (root / "state_5.sqlite").write_text("not a database")
    assert pj.claude_sessions(project) == []
    assert pj.codex_sessions(project) == []


def test_merged_newest_first_with_resume_commands(env):
    root, project = env
    claude_session(root, "old", PROJ)
    codex_db(root, [("new", PROJ, None, "t", None, 4_000_000_000, 0, "", "cli", 0)])
    rows = pj.project_sessions(project)
    assert [r["id"] for r in rows] == ["new", "old"]
    assert rows[0]["resume"] == f"cd {PROJ} && codex resume new"
    assert rows[1]["resume"] == f"cd {PROJ} && claude --resume old"


def test_api_projects_reports_sessions_and_bad_entries(env, monkeypatch):
    root, _ = env
    import app as app_mod
    good = root / "good"
    import subprocess
    subprocess.run(["git", "init", "-q", str(good)], check=True)
    reg = root / "projects.yaml"
    reg.write_text(f"projects:\n  good:\n    path: {good}\n    verify: 'true'\n    confidential: true\n"
                   f"  broken:\n    path: {root}/missing\n    verify: 'true'\n")
    monkeypatch.setattr(pj, "REGISTRY_PATH", reg)
    claude_session(root, "s1", str(good))
    r = app_mod.app.test_client().get("/api/projects", headers={"X-AgenticOS-Token": app_mod.REQUEST_TOKEN})
    data = r.get_json()["projects"]
    by_key = {p["key"]: p for p in data}
    assert by_key["good"]["confidential"] is True and [s["id"] for s in by_key["good"]["sessions"]] == ["s1"]
    assert "not a git repository" in by_key["broken"]["error"]


def test_valid_json_of_wrong_shape_degrades(env):
    root, project = env
    d = root / "claude" / pj._slug(PROJ)
    d.mkdir(parents=True)
    lines = ['[{"type":"user"}]', '"just a string"',
             json.dumps({"type": "user", "cwd": PROJ, "message": "plain string message"}),
             json.dumps({"type": "user", "cwd": PROJ, "message": {"content": [1, "x", {"type": "text", "text": "ok"}]}})]
    (d / "odd.jsonl").write_text("\n".join(lines))
    claude_session(root, "fine", PROJ)
    assert ids(pj.claude_sessions(project)) == ["fine", "odd"]


def test_wrong_field_types_degrade(env):
    root, project = env
    d = root / "claude" / pj._slug(PROJ)
    d.mkdir(parents=True)
    (d / "objentry.jsonl").write_text(json.dumps({"type": "user", "cwd": PROJ, "entrypoint": {"x": 1}}))
    (d / "numcwd.jsonl").write_text(json.dumps({"type": "user", "cwd": 42}))
    claude_session(root, "fine", PROJ)
    codex_db(root, [("bad", 7, None, "t", None, "not-a-number", 0, "", "cli", 0),
                    ("good", PROJ, None, "t", None, "x", 0, "", "cli", 0)])
    assert "fine" in ids(pj.claude_sessions(project))
    assert ids(pj.codex_sessions(project)) == ["good"]


def test_non_string_titles_and_blob_ids_degrade(env):
    root, project = env
    claude_session(root, "dict-title", PROJ, {"type": "custom-title", "customTitle": {"x": 1}})
    codex_db(root, [(b"blob-id", PROJ, None, "t", None, 1, 0, "", "cli", 0),
                    ("ok", PROJ, b"blob-name", None, "first", 1, 0, "", "cli", 0)])
    rows = {r["id"]: r for r in pj.claude_sessions(project) + pj.codex_sessions(project)}
    assert rows["dict-title"]["title"] == "first real question"
    assert set(rows) == {"dict-title", "ok"} and rows["ok"]["title"] == "first"
    import json as _j
    _j.dumps(list(rows.values()))  # serializable
