"""Pick a project when creating a task (dashboard UI plan, part B). Fake project names only."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

RUNNER = Path(__file__).resolve().parents[1] / "runner"
sys.path.insert(0, str(RUNNER))
sys.path.insert(0, str(RUNNER.parent))

from test_reset_gen import ISSUE, env, write_log  # noqa: E402,F401  (env: fixture)


def git_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    return path


@pytest.fixture
def reg(env, tmp_path, monkeypatch):
    import projects as pj
    reg = tmp_path / "projects.yaml"
    reg.write_text(yaml.safe_dump({"projects": {
        "agentic-os": {"path": str(git_repo(tmp_path / "aos")), "confidential": False},
        "demo": {"path": str(git_repo(tmp_path / "demo")), "confidential": False},
        "broken": {"path": str(tmp_path / "missing"), "confidential": False},
    }}))
    monkeypatch.setattr(pj, "REGISTRY_PATH", reg)
    return env, reg


def tasks(tmp):
    return json.loads((tmp / "tasks.json").read_text())


def test_local_task_stores_labels_and_old_files_read_empty(tmp_path):
    from runner.modules.linear.local_tracker import LocalTracker
    t = LocalTracker(tmp_path)
    (tmp_path / "tasks.json").write_text(json.dumps({"old": {"id": "old", "state": "Todo", "title": "o"}}))
    new = t.create_issue("n", labels=["project:demo"])
    assert t.fetch_issue(new["id"])["labels"] == ["project:demo"]
    assert t.fetch_issue("old")["labels"] == []
    assert {i["id"]: i["labels"] for i in t.fetch_issues()} == {"old": [], new["id"]: ["project:demo"]}


def test_create_route_project_default_none_and_refusals(reg):
    (app_mod, mod, client, log, events, tmp), path = reg
    def create(**body):
        return client.post("/api/linear/issues", json={"title": "t", **body})
    r = create(project="demo")
    assert r.status_code == 200 and r.get_json()["issue"]["labels"] == ["project:demo"]
    assert create().get_json()["issue"]["labels"] == ["project:agentic-os"]  # omitted -> default
    assert create(project="").get_json()["issue"]["labels"] == []  # explicit "No project"
    before = tasks(tmp)
    assert create(project="nope").status_code == 400
    assert create(project="broken").status_code == 400
    assert tasks(tmp) == before  # nothing created
    doc = yaml.safe_load(path.read_text())
    del doc["projects"]["agentic-os"]
    path.write_text(yaml.safe_dump(doc))
    assert create().get_json()["issue"]["labels"] == []  # default not registered -> runner root


def test_local_first_dispatch_uses_the_project_worktree(reg, monkeypatch):
    (app_mod, mod, client, log, events, tmp), _ = reg
    issue = client.post("/api/linear/issues", json={"title": "t", "project": "demo"}).get_json()["issue"]
    seen = {}
    monkeypatch.setattr(app_mod, "_run_project_ticket", lambda **kw: seen.update(kw))
    mod._dispatch_issue(mod.issues_cache[issue["id"]], {"agent": {"backend": "claude"}}, app_mod.socketio)
    assert seen["project_key"] == "demo" and seen["ident"] == issue["identifier"]


class FakeClient:
    """LinearClient stand-in: records calls, returns a create response with or without labels."""
    def __init__(self, with_labels, calls):
        self.with_labels, self.calls = with_labels, calls

    def __call__(self, *a, **k):
        return self

    def ensure_label(self, team_id, name):
        self.calls.append(("label", name))
        return "lbl-1"

    def create_issue(self, team_id, title, desc, label_ids=None):
        self.calls.append(("create", label_ids))
        out = {"id": "lin-1", "identifier": "ENG-1", "title": title, "description": desc, "state": "Todo",
               "team_id": team_id}
        if self.with_labels:
            out["labels"] = ["project:demo"]
        return out


@pytest.mark.parametrize("with_labels", [True, False])
def test_labels_survive_the_background_swap_and_backups(reg, monkeypatch, with_labels):
    (app_mod, mod, client, log, events, tmp), _ = reg
    import linear_client
    import runner.modules.linear as lin
    calls = []
    monkeypatch.setattr(linear_client, "LinearClient", FakeClient(with_labels, calls))
    monkeypatch.setattr(lin, "_linear_api_key_from_cfg", lambda tc: "key")
    monkeypatch.setattr(lin, "_post_linear_comment_raw", lambda *a: None)
    monkeypatch.setattr(lin, "record_id_alias", lambda *a: None)
    monkeypatch.setattr(mod, "_capability", {"available": True, "type": "linear"})
    r = client.post("/api/linear/issues", json={"title": "t", "project": "demo", "team_id": "team"})
    assert r.status_code == 200
    assert ("label", "project:demo") in calls and ("create", ["lbl-1"]) in calls
    assert tasks(tmp)["lin-1"]["labels"] == ["project:demo"] and mod.issues_cache["lin-1"]["labels"] == ["project:demo"]
    mod._localize_issue({"id": "lin-1", "title": "renamed", "description": "", "state": "Todo"})  # backup update
    assert tasks(tmp)["lin-1"]["labels"] == ["project:demo"]
    mod._localize_issue({"id": "lin-2", "title": "x", "description": "", "state": "Todo",
                         "labels": {"nodes": [{"name": "project:demo"}]}})  # backup create
    assert tasks(tmp)["lin-2"]["labels"] == ["project:demo"]
    seen = {}
    monkeypatch.setattr(app_mod, "_run_project_ticket", lambda **kw: seen.update(kw))
    mod._dispatch_issue(mod.issues_cache["lin-1"], {"agent": {"backend": "claude"}}, app_mod.socketio)
    assert seen["project_key"] == "demo"


def test_unresolved_label_keeps_the_task_local(reg, monkeypatch):
    (app_mod, mod, client, log, events, tmp), _ = reg
    import linear_client
    import runner.modules.linear as lin
    calls = []
    fake = FakeClient(True, calls)
    fake.ensure_label = lambda team_id, name: calls.append(("label", name))  # Linear refused the label
    monkeypatch.setattr(linear_client, "LinearClient", fake)
    monkeypatch.setattr(lin, "_linear_api_key_from_cfg", lambda tc: "key")
    monkeypatch.setattr(mod, "_capability", {"available": True, "type": "linear"})
    issue = client.post("/api/linear/issues", json={"title": "t", "project": "demo", "team_id": "team"}).get_json()["issue"]
    assert not any(c[0] == "create" for c in calls)  # no Linear issue without its project label (UI-01)
    assert issue["id"] in tasks(tmp) and tasks(tmp)[issue["id"]]["labels"] == ["project:demo"]


def test_unsynced_local_id_is_never_dispatched_while_linear_is_active(reg, monkeypatch):
    (app_mod, mod, client, log, events, tmp), _ = reg
    issue = client.post("/api/linear/issues", json={"title": "t", "project": "demo"}).get_json()["issue"]
    seen = []
    monkeypatch.setattr(app_mod, "_run_project_ticket", lambda **kw: seen.append(kw))
    monkeypatch.setattr(mod, "_capability", {"available": True, "type": "linear"})
    import runner.modules.linear as lin
    monkeypatch.setattr(lin, "_linear_api_key_from_cfg", lambda tc: "key")
    before = tasks(tmp)
    mod._dispatch_issue(mod.issues_cache[issue["id"]], {"agent": {"backend": "claude"}}, app_mod.socketio)
    assert client.patch(f"/api/linear/issues/local/{issue['id']}", json={"state_name": "In Progress"}).status_code == 409
    r = client.patch(f"/api/linear/issues/{issue['id']}", json={"state_name": "In Progress"})
    assert r.status_code == 409 and seen == [] and tasks(tmp) == before
    assert issue["id"] not in mod._local_overrides  # no override installed by a refused move (UI2-08)
    write_log(log, {"run_id": "a", "agent": "claude", "status": "review", "linear_issue_id": issue["id"]})
    assert client.post("/api/runs/a/retry", json={}).status_code == 409
    monkeypatch.setattr(mod, "_capability", {"available": True, "type": "local"})  # local tracker only
    mod._dispatch_issue(mod.issues_cache[issue["id"]], {"agent": {"backend": "claude"}}, app_mod.socketio)
    assert seen and seen[0]["project_key"] == "demo"


def test_linear_client_ensure_label_and_label_ids(monkeypatch):
    import linear_client
    c = linear_client.LinearClient("k", "")
    sent = []
    replies = iter([{"issueLabels": {"nodes": [{"id": "L1", "name": "project:x"}]}},
                    {"issueLabels": {"nodes": []}},
                    {"issueLabelCreate": {"success": True, "issueLabel": {"id": "L2"}}},
                    {"issueCreate": {"success": True, "issue": {"id": "i", "identifier": "E-1", "title": "t",
                                                                 "state": {"name": "Todo"},
                                                                 "labels": {"nodes": [{"name": "project:x"}]},
                                                                 "team": {"id": "T"}}}}])
    monkeypatch.setattr(c, "_graphql", lambda q, v=None: sent.append((q, v)) or next(replies))
    monkeypatch.setattr(c, "resolve_state_id_by_team", lambda *a: None)
    assert c.ensure_label("T", "project:x") == "L1" and len(sent) == 1  # reused
    assert "eqIgnoreCase" in sent[0][0] and "null: true" in sent[0][0]  # workspace labels, any case (FB-01)
    assert c.ensure_label("T", "project:y") == "L2" and "issueLabelCreate" in sent[-1][0]  # created
    issue = c.create_issue("T", "t", label_ids=["L1"])
    assert sent[-1][1]["labelIds"] == ["L1"] and issue["labels"] == ["project:x"] and issue["state"] == "Todo"


def test_ensure_label_rechecks_after_a_refused_create(monkeypatch):
    import linear_client
    c = linear_client.LinearClient("k", "")
    replies = iter([{"issueLabels": {"nodes": []}}, {"issueLabelCreate": {"success": False}},
                    {"issueLabels": {"nodes": [{"id": "L9", "name": "Project:X"}]}}])
    monkeypatch.setattr(c, "_graphql", lambda q, v=None: next(replies))
    assert c.ensure_label("T", "project:x") == "L9"  # created meanwhile / refused as a duplicate (FB-01)


@pytest.mark.parametrize("label", ["project:../x", "project:/abs/x", "project:a/../../b"])
def test_untrusted_label_never_creates_paths_outside_the_worktree_root(reg, monkeypatch, tmp_path, label):
    (app_mod, mod, client, log, events, tmp), _ = reg
    import projects as pj
    monkeypatch.setattr(pj, "WORKTREE_ROOT", tmp_path / "wt-root")
    mod.issues_cache[ISSUE] = {"id": ISSUE, "identifier": "LOC-9", "title": "t", "labels": [label], "state": "Todo"}
    before = {p for p in tmp_path.rglob("*")}
    r = client.patch(f"/api/linear/issues/{ISSUE}", json={"state_name": "In Progress"})
    assert r.status_code == 400 and "unknown project" in r.get_json()["error"]  # not "a terminal holds it" (FB3-01)
    created = {p for p in tmp_path.rglob("*")} - before
    assert not any(".meta" in p.parts for p in created)
    assert not Path("/abs").exists()
    with pytest.raises(pj.ProjectError):
        with pj.ticket_lock("../x", "T-1"):
            pass


def test_broken_registry_still_allows_tasks_without_a_project(reg):
    (app_mod, mod, client, log, events, tmp), path = reg
    path.write_text("projects: [not, a, mapping]\n")
    assert client.post("/api/linear/issues", json={"title": "t", "project": ""}).status_code == 200  # FB3-02
    r = client.post("/api/linear/issues", json={"title": "t"})
    assert r.status_code == 200 and r.get_json()["issue"]["labels"] == []
    r = client.post("/api/linear/issues", json={"title": "t", "project": "demo"})
    assert r.status_code == 400 and "registry" in r.get_json()["error"]


def test_label_case_maps_onto_the_registered_project(reg, monkeypatch):
    (app_mod, mod, client, log, events, tmp), _ = reg
    seen = {}
    monkeypatch.setattr(app_mod, "_run_project_ticket", lambda **kw: seen.update(kw))
    issue = {"id": "lin-c", "identifier": "ENG-2", "title": "t", "description": "", "labels": ["project:DEMO"]}
    mod._dispatch_issue(issue, {"agent": {"backend": "claude"}}, app_mod.socketio)
    assert seen["project_key"] == "demo"  # FB3-03


def test_dispatch_after_restart_holds_the_projects_ticket_lock(reg, monkeypatch):
    (app_mod, mod, client, log, events, tmp), _ = reg
    import projects as pj
    issue = client.post("/api/linear/issues", json={"title": "t", "project": "demo"}).get_json()["issue"]
    mod.issues_cache.clear()  # a local-tracker restart: the cache is empty, the task is on disk (REV-01)
    monkeypatch.setattr(mod, "_socketio", app_mod.socketio)
    seen = {}

    def helper(**kw):
        seen.update(kw, ticket_busy=pj.card_busy("demo", issue["identifier"], None),
                    card_busy=pj.card_busy(None, None, issue["id"]))
    monkeypatch.setattr(app_mod, "_run_project_ticket", helper)
    assert client.patch(f"/api/linear/issues/{issue['id']}", json={"state_name": "In Progress"}).status_code == 200
    assert seen["project_key"] == "demo" and seen["ticket_hold"] is not None
    assert seen["ticket_busy"] and not seen["card_busy"]  # the project's ticket lock, not a generic card lock


def test_rejected_linear_state_is_reported_not_masked(reg, monkeypatch):
    (app_mod, mod, client, log, events, tmp), _ = reg
    import linear_client
    import runner.modules.linear as lin

    class Refusing:
        def __init__(self, *a, **k): pass
        def fetch_issue(self, i): return {"id": i, "title": "t", "description": "", "state": "In Review"}
        def update_issue(self, i, **kw): pass
        def update_issue_state(self, i, s): return False
    monkeypatch.setattr(linear_client, "LinearClient", Refusing)
    monkeypatch.setattr(lin, "_linear_api_key_from_cfg", lambda tc: "key")
    monkeypatch.setattr(mod, "_capability", {"available": True, "type": "linear"})
    r = client.patch("/api/linear/issues/lin-9", json={"state_name": "Done"})
    assert r.status_code == 502 and "lin-9" not in mod._local_overrides  # UI11-01


def test_refused_move_to_todo_does_not_reset_the_ticket(reg, monkeypatch):
    (app_mod, mod, client, log, events, tmp), _ = reg
    import linear_client
    import reset_gen
    import runner.modules.linear as lin

    class Refusing:
        def __init__(self, *a, **k): pass
        def fetch_issue(self, i): return {"id": i, "title": "t", "description": "", "state": "In Review"}
        def update_issue(self, i, **kw): pass
        def update_issue_state(self, i, s): return False
    monkeypatch.setattr(linear_client, "LinearClient", Refusing)
    monkeypatch.setattr(lin, "_linear_api_key_from_cfg", lambda tc: "key")
    monkeypatch.setattr(mod, "_capability", {"available": True, "type": "linear"})
    before = reset_gen.current("lin-7")
    assert client.patch("/api/linear/issues/lin-7", json={"state_name": "Todo"}).status_code == 502
    assert reset_gen.current("lin-7") == before  # a refused reset keeps the session resumable (IR13-01)
    write_log(log, {"run_id": "z", "agent": "claude", "status": "review", "linear_issue_id": "lin-7",
                    "task_id": "tz", "agent_session_id": "S", "reset_gen": before})
    assert app_mod._get_task_agent_lock("tz")["agent_session_id"] == "S"


def test_committed_reset_keeps_its_generation_when_the_refresh_fails(reg, monkeypatch):
    (app_mod, mod, client, log, events, tmp), _ = reg
    import linear_client
    import reset_gen
    import runner.modules.linear as lin

    class AcceptsThenFails:
        calls = 0
        def __init__(self, *a, **k): pass
        def fetch_issue(self, i):
            AcceptsThenFails.calls += 1
            if AcceptsThenFails.calls > 1:
                raise RuntimeError("network down")
            return {"id": i, "title": "t", "description": "", "state": "In Review"}
        def update_issue(self, i, **kw): pass
        def update_issue_state(self, i, s): return True
    monkeypatch.setattr(linear_client, "LinearClient", AcceptsThenFails)
    monkeypatch.setattr(lin, "_linear_api_key_from_cfg", lambda tc: "key")
    monkeypatch.setattr(mod, "_capability", {"available": True, "type": "linear"})
    before = reset_gen.current("lin-8")
    assert client.patch("/api/linear/issues/lin-8", json={"state_name": "Todo"}).status_code == 500
    assert reset_gen.current("lin-8") == before + 1  # Linear took Todo: the reset stands (UI14-03)


class TeamsClient(FakeClient):
    """FakeClient whose fetch_teams answers come from a list, one per call; create records the team."""
    def __init__(self, calls, answers):
        super().__init__(True, calls)
        self.answers = answers

    def fetch_teams(self):
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def create_issue(self, team_id, title, desc, label_ids=None):
        self.calls.append(("create_team", team_id))
        return super().create_issue(team_id, title, desc, label_ids)


def _all_teams(reg, monkeypatch, answers):
    """Linear mode with "All Teams" selected (empty tracker.team_id, as the dashboard stores it)."""
    (app_mod, mod, client, log, events, tmp), _ = reg
    import linear_client
    import runner.modules.linear as lin
    calls = []
    monkeypatch.setattr(linear_client, "LinearClient", TeamsClient(calls, answers))
    monkeypatch.setattr(lin, "_linear_api_key_from_cfg", lambda tc: "key")
    monkeypatch.setattr(lin, "_load_workflow_config", lambda: {"tracker": {"kind": "linear", "team_id": ""}})
    monkeypatch.setattr(lin, "_post_linear_comment_raw", lambda *a: None)
    monkeypatch.setattr(lin, "record_id_alias", lambda *a: None)
    monkeypatch.setattr(mod, "_capability", {"available": True, "type": "linear"})
    return mod, client, calls, (lambda: tasks(tmp))


ONE = [{"id": "age", "key": "AGE", "name": "Agenticos"}]


def test_all_teams_creates_in_the_viewers_only_team(reg, monkeypatch):
    mod, client, calls, stored = _all_teams(reg, monkeypatch, [ONE])
    r = client.post("/api/linear/issues", json={"title": "t", "team_id": ""})
    assert r.status_code == 200 and ("create_team", "age") in calls  # AGE-122
    assert client.post("/api/linear/issues", json={"title": "t", "team_id": "picked"}).status_code == 200
    assert ("create_team", "picked") in calls  # a selected team still wins, no lookup (answers exhausted)


def test_all_teams_with_several_teams_refuses_and_creates_nothing(reg, monkeypatch):
    mod, client, calls, stored = _all_teams(reg, monkeypatch, [ONE + [{"id": "ml", "key": "ML4", "name": "ml4t"}]])
    before = stored()
    r = client.post("/api/linear/issues", json={"title": "t"})
    assert r.status_code == 400 and "Select a team" in r.get_json()["error"] and "2 teams" in r.get_json()["error"]
    assert stored() == before and not calls


def test_failed_team_lookup_refuses_then_recovers(reg, monkeypatch):
    mod, client, calls, stored = _all_teams(reg, monkeypatch, [[], ONE])
    before = stored()
    r = client.post("/api/linear/issues", json={"title": "t"})
    assert r.status_code == 400 and "Could not read" in r.get_json()["error"] and stored() == before
    assert client.post("/api/linear/issues", json={"title": "t"}).status_code == 200 and ("create_team", "age") in calls


def test_stale_team_cache_is_never_used_to_create(reg, monkeypatch):
    mod, client, calls, stored = _all_teams(reg, monkeypatch, [[]])
    monkeypatch.setattr(mod, "_teams_cache", [{"id": "stale", "key": "OLD", "name": "old"}])
    monkeypatch.setattr(mod, "_teams_last_refreshed", 0)
    before = stored()
    r = client.post("/api/linear/issues", json={"title": "t"})
    assert r.status_code == 400 and "Could not read" in r.get_json()["error"] and stored() == before and not calls


def test_raising_team_lookup_refuses_then_recovers(reg, monkeypatch):
    # GraphQL errors with data: null make fetch_teams raise, not return [] (inspection R1)
    mod, client, calls, stored = _all_teams(reg, monkeypatch, [AttributeError("'NoneType' has no attribute 'get'"), ONE])
    before = stored()
    r = client.post("/api/linear/issues", json={"title": "t"})
    assert r.status_code == 400 and "Could not read" in r.get_json()["error"] and stored() == before and not calls
    assert client.post("/api/linear/issues", json={"title": "t"}).status_code == 200 and ("create_team", "age") in calls
