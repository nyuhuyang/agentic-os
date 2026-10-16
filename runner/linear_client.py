"""Linear GraphQL client for agentic-os job board."""
from __future__ import annotations

import logging
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)

_ENDPOINT = "https://api.linear.app/graphql"
_PAGE_SIZE = 50

_QUERY_ISSUES = """
query AgenticOSPoll($projectSlug: String!, $stateNames: [String!]!, $first: Int!, $after: String) {
  issues(
    filter: {project: {slugId: {eq: $projectSlug}}, state: {name: {in: $stateNames}}}
    first: $first
    after: $after
  ) {
    nodes {
      id
      identifier
      title
      description
      priority
      state { name }
      url
      assignee { id displayName }
      labels { nodes { name } }
      team { id key name }
      project { id }
      createdAt
      updatedAt
    }
    pageInfo { hasNextPage endCursor }
  }
}
"""

_QUERY_ISSUES_NO_PROJECT = """
query AgenticOSPollAll($stateNames: [String!]!, $first: Int!, $after: String) {
  issues(
    filter: {state: {name: {in: $stateNames}}}
    first: $first
    after: $after
  ) {
    nodes {
      id
      identifier
      title
      description
      priority
      state { name }
      url
      assignee { id displayName }
      labels { nodes { name } }
      team { id key name }
      project { id }
      createdAt
      updatedAt
    }
    pageInfo { hasNextPage endCursor }
  }
}
"""

_QUERY_TEAM_STATES = """
query AgenticOSTeamStates($projectSlug: String!) {
  issues(filter: {project: {slugId: {eq: $projectSlug}}}, first: 1) {
    nodes {
      team {
        id
        states { nodes { id name } }
      }
    }
  }
}
"""

_MUTATION_UPDATE_STATE = """
mutation AgenticOSUpdateState($issueId: String!, $stateId: String!) {
  issueUpdate(id: $issueId, input: {stateId: $stateId}) {
    success
    issue { id state { name } }
  }
}
"""

_MUTATION_UPDATE_ISSUE = """
mutation AgenticOSUpdateIssue($issueId: String!, $title: String, $description: String, $stateId: String) {
  issueUpdate(id: $issueId, input: {title: $title, description: $description, stateId: $stateId}) {
    success
    issue { id title description state { name } }
  }
}
"""

_MUTATION_CREATE_ISSUE = """
mutation AgenticOSCreateIssue($teamId: String!, $title: String!, $description: String, $stateId: String, $labelIds: [String!], $projectId: String) {
  issueCreate(input: {teamId: $teamId, title: $title, description: $description, stateId: $stateId, labelIds: $labelIds, projectId: $projectId}) {
    success
    issue {
      id identifier title description priority url createdAt updatedAt
      state { name }
      labels { nodes { name } }
      team { id key name }
      project { id }
    }
  }
}
"""

_QUERY_LABEL = """
query AgenticOSLabel($teamId: ID!, $name: String!) {
  issueLabels(filter: {name: {eqIgnoreCase: $name}, or: [{team: {id: {eq: $teamId}}}, {team: {null: true}}]}, first: 1) {
    nodes { id name }
  }
}
"""

_MUTATION_CREATE_LABEL = """
mutation AgenticOSCreateLabel($teamId: String!, $name: String!) {
  issueLabelCreate(input: {teamId: $teamId, name: $name}) {
    success
    issueLabel { id name }
  }
}
"""

_QUERY_TEAM_STATES_BY_ID = """
query AgenticOSTeamStatesById($teamId: String!) {
  team(id: $teamId) {
    states { nodes { id name } }
  }
}
"""

_QUERY_PROJECTS = """
query AgenticOSProjects {
  projects(first: 50) {
    nodes {
      id
      slugId
      name
      state
    }
  }
}
"""

_QUERY_TEAMS = """
query AgenticOSTeams {
  teams(first: 50) {
    nodes {
      id
      key
      name
    }
  }
}
"""

_QUERY_ISSUES_BY_TEAM = """
query AgenticOSPollTeam($teamId: ID!, $stateNames: [String!]!, $first: Int!, $after: String) {
  issues(
    filter: {team: {id: {eq: $teamId}}, state: {name: {in: $stateNames}}}
    first: $first
    after: $after
  ) {
    nodes {
      id
      identifier
      title
      description
      priority
      state { name }
      url
      assignee { id displayName }
      labels { nodes { name } }
      team { id key name }
      project { id }
      createdAt
      updatedAt
    }
    pageInfo { hasNextPage endCursor }
  }
}
"""

_QUERY_ISSUE = """
query AgenticOSIssue($id: String!) {
  issue(id: $id) {
    id
    identifier
    title
    description
    priority
    state { id name }
    url
    assignee { id displayName }
    labels { nodes { id name } }
    team { id key name states { nodes { id name } } }
    project { id }
    createdAt
    updatedAt
  }
}
"""


_QUERY_PROJECT_BY_NAME = """
query AgenticOSProjectByName($name: String!, $teamId: ID!) {
  projects(filter: {name: {eq: $name}, accessibleTeams: {some: {id: {eq: $teamId}}}}, first: 5) {
    nodes { id name }
  }
}
"""

_QUERY_PROJECT_BY_SLUG = """
query AgenticOSProjectBySlug($slug: String!) {
  projects(filter: {slugId: {eq: $slug}}, first: 1) { nodes { id } }
}
"""

_MUTATION_CREATE_PROJECT = """
mutation AgenticOSCreateProject($name: String!, $teamIds: [String!]!) {
  projectCreate(input: {name: $name, teamIds: $teamIds}) {
    success
    project { id name }
  }
}
"""

_MUTATION_SET_ISSUE_PROJECT = """
mutation AgenticOSSetIssueProject($issueId: String!, $projectId: String!) {
  issueUpdate(id: $issueId, input: {projectId: $projectId}) { success }
}
"""

_MUTATION_ARCHIVE_ISSUE = """
mutation AgenticOSArchiveIssue($id: String!) {
  issueArchive(id: $id) { success }
}
"""


class LinearError(RuntimeError):
    """A Linear call that failed (transport, GraphQL error, rate limit, or success: false).
    Only the strict calls raise it; the older ones still log and return empty (STB-072)."""


def _normalize(node: dict) -> dict:
    team = node.get("team") or {}
    return {
        "id": node.get("id", ""),
        "identifier": node.get("identifier", ""),
        "title": node.get("title", ""),
        "description": node.get("description", ""),
        "priority": node.get("priority", 0),
        "state": (node.get("state") or {}).get("name", ""),
        "url": node.get("url", ""),
        "assignee": (node.get("assignee") or {}).get("displayName", ""),
        "labels": [l["name"] for l in (node.get("labels") or {}).get("nodes", [])],
        "team_id": team.get("id", ""),
        "team_key": team.get("key", ""),
        "team_name": team.get("name", ""),
        "project_id": (node.get("project") or {}).get("id", ""),  # Linear Project, "" = none (STB §10)
        "created_at": node.get("createdAt", ""),
        "updated_at": node.get("updatedAt", ""),
    }


class LinearClient:
    def __init__(self, api_key: str, project_slug: str, endpoint: str = _ENDPOINT):
        self.api_key = api_key
        self.project_slug = project_slug
        self.endpoint = endpoint
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": api_key,
            "Content-Type": "application/json",
        })
        self._state_cache: dict[str, str] = {}  # name -> id

    def _graphql(self, query: str, variables: dict | None = None) -> dict:
        payload: dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables
        resp = None
        try:
            resp = self._session.post(self.endpoint, json=payload, timeout=15)
            data = resp.json()
            errors = data.get("errors", [])
            if errors:
                code = (errors[0].get("extensions") or {}).get("code", "")
                if code == "RATELIMITED":
                    logger.warning("Linear rate limit hit — back off and retry later")
                    return {}
                logger.error("Linear GraphQL errors: %s", errors)
            resp.raise_for_status()
            return data.get("data", {})
        except Exception as e:
            body = resp.text[:300] if resp is not None else "(no response)"
            logger.error("Linear GraphQL request failed: %s — %s", e, body)
            return {}

    def _graphql_strict(self, query: str, variables: dict | None = None) -> dict:
        """Like _graphql, but every failure raises LinearError with its reason (STB-072)."""
        payload: dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables
        try:
            resp = self._session.post(self.endpoint, json=payload, timeout=15)
            data = resp.json()
        except Exception as e:
            raise LinearError(f"Linear request failed: {e}") from None
        errors = data.get("errors") or []
        if errors:
            code = (errors[0].get("extensions") or {}).get("code", "")
            raise LinearError("Linear rate limit hit; try again shortly" if code == "RATELIMITED"
                              else f"Linear error: {errors[0].get('message', errors[0])}")
        if resp.status_code >= 400:
            raise LinearError(f"Linear HTTP {resp.status_code}")
        return data.get("data") or {}

    def find_project(self, name: str, team_id: str) -> str | None:
        """The id of the team's non-archived Project named exactly `name`, or None."""
        data = self._graphql_strict(_QUERY_PROJECT_BY_NAME, {"name": name, "teamId": team_id})
        for n in (data.get("projects") or {}).get("nodes") or []:
            if n.get("name") == name and n.get("id"):
                return n["id"]
        return None

    def create_project(self, name: str, team_id: str) -> str:
        data = self._graphql_strict(_MUTATION_CREATE_PROJECT, {"name": name, "teamIds": [team_id]})
        result = data.get("projectCreate") or {}
        pid = (result.get("project") or {}).get("id") if result.get("success") else None
        if not pid:
            raise LinearError(f"Linear did not create project {name!r}")
        return pid

    def find_project_by_slug(self, slug: str) -> str:
        data = self._graphql_strict(_QUERY_PROJECT_BY_SLUG, {"slug": slug})
        nodes = (data.get("projects") or {}).get("nodes") or []
        if not nodes or not nodes[0].get("id"):
            raise LinearError(f"no Linear project with slug {slug!r}")
        return nodes[0]["id"]

    def set_issue_project(self, issue_id: str, project_id: str) -> None:
        data = self._graphql_strict(_MUTATION_SET_ISSUE_PROJECT, {"issueId": issue_id, "projectId": project_id})
        if not (data.get("issueUpdate") or {}).get("success"):
            raise LinearError(f"Linear did not move {issue_id} into the project")

    def archive_issue(self, issue_id: str) -> None:
        """Archive (recoverable in Linear), never delete (STB §11)."""
        data = self._graphql_strict(_MUTATION_ARCHIVE_ISSUE, {"id": issue_id})
        if not (data.get("issueArchive") or {}).get("success"):
            raise LinearError(f"Linear did not archive {issue_id}")

    def _fetch_paged(self, query: str, variables: dict) -> list[dict]:
        issues: list[dict] = []
        after: str | None = None
        while True:
            v = {**variables, "first": _PAGE_SIZE}
            if after:
                v["after"] = after
            data = self._graphql(query, v)
            page = data.get("issues") or {}
            nodes = page.get("nodes", [])
            issues.extend(_normalize(n) for n in nodes)
            page_info = page.get("pageInfo", {})
            if not page_info.get("hasNextPage"):
                break
            after = page_info.get("endCursor")
        return issues

    def fetch_issues(self, states: list[str], team_id: str | None = None) -> list[dict]:
        seen: dict[str, dict] = {}
        if team_id:
            for issue in self._fetch_paged(_QUERY_ISSUES_BY_TEAM, {"teamId": team_id, "stateNames": states}):
                seen[issue["id"]] = issue
        else:
            if self.project_slug:
                for issue in self._fetch_paged(_QUERY_ISSUES, {"projectSlug": self.project_slug, "stateNames": states}):
                    seen[issue["id"]] = issue
            for issue in self._fetch_paged(_QUERY_ISSUES_NO_PROJECT, {"stateNames": states}):
                seen.setdefault(issue["id"], issue)
        return list(seen.values())

    def resolve_state_id(self, state_name: str) -> str | None:
        if state_name in self._state_cache:
            return self._state_cache[state_name]
        data = self._graphql(_QUERY_TEAM_STATES, {"projectSlug": self.project_slug})
        nodes = (((data.get("issues") or {}).get("nodes") or [{}])[0]
                 .get("team", {}).get("states", {}).get("nodes", []))
        for s in nodes:
            self._state_cache[s["name"]] = s["id"]
        return self._state_cache.get(state_name)

    def update_issue_state(self, issue_id: str, state_name: str) -> bool:
        state_id = None
        issue = self.fetch_issue(issue_id)
        if issue:
            for s in issue.get("team_states", []):
                if s.get("name") == state_name:
                    state_id = s.get("id")
                    self._state_cache[state_name] = state_id
                    break
        if not state_id:
            state_id = self.resolve_state_id(state_name)
        if not state_id:
            logger.error("Cannot resolve Linear state '%s'", state_name)
            return False
        data = self._graphql(_MUTATION_UPDATE_STATE, {"issueId": issue_id, "stateId": state_id})
        return bool((data.get("issueUpdate") or {}).get("success"))

    def fetch_issue(self, issue_id: str) -> dict | None:
        data = self._graphql(_QUERY_ISSUE, {"id": issue_id})
        node = data.get("issue")
        if not node:
            return None
        result = _normalize(node)
        result["state_id"] = (node.get("state") or {}).get("id", "")
        result["team_states"] = [
            {"id": s["id"], "name": s["name"]}
            for s in (node.get("team") or {}).get("states", {}).get("nodes", [])
        ]
        return result

    def update_issue(self, issue_id: str, title: str | None = None,
                     description: str | None = None, state_name: str | None = None) -> dict | None:
        variables: dict = {"issueId": issue_id}
        if title is not None:
            variables["title"] = title
        if description is not None:
            variables["description"] = description
        if state_name is not None:
            state_id = self.resolve_state_id(state_name)
            if state_id:
                variables["stateId"] = state_id
        data = self._graphql(_MUTATION_UPDATE_ISSUE, variables)
        result = data.get("issueUpdate") or {}
        if result.get("success"):
            return result.get("issue")
        return None

    def fetch_projects(self) -> list[dict]:
        data = self._graphql(_QUERY_PROJECTS)
        nodes = (data.get("projects") or {}).get("nodes", [])
        return [{"id": n["id"], "slug_id": n["slugId"], "name": n["name"], "state": n.get("state", "")}
                for n in nodes]

    def fetch_teams(self) -> list[dict]:
        data = self._graphql(_QUERY_TEAMS)
        nodes = (data.get("teams") or {}).get("nodes", [])
        return [{"id": n["id"], "key": n["key"], "name": n["name"]} for n in nodes]

    def resolve_state_id_by_team(self, team_id: str, state_name: str) -> str | None:
        cache_key = f"{team_id}:{state_name}"
        if cache_key in self._state_cache:
            return self._state_cache[cache_key]
        data = self._graphql(_QUERY_TEAM_STATES_BY_ID, {"teamId": team_id})
        nodes = (data.get("team") or {}).get("states", {}).get("nodes", [])
        for s in nodes:
            self._state_cache[f"{team_id}:{s['name']}"] = s["id"]
        return self._state_cache.get(cache_key)

    def ensure_label(self, team_id: str, name: str) -> str | None:
        """The id of label `name` (team or workspace label, any case), created in the team when
        missing (needs write scope). A failed create is looked up once more: another create, or
        a label Linear refused to duplicate, may already exist (FB-01)."""
        def lookup() -> str | None:
            data = self._graphql(_QUERY_LABEL, {"teamId": team_id, "name": name})
            nodes = ((data.get("issueLabels") or {}).get("nodes")) or []
            return nodes[0].get("id") if nodes and nodes[0].get("id") else None
        found = lookup()
        if found:
            return found
        data = self._graphql(_MUTATION_CREATE_LABEL, {"teamId": team_id, "name": name})
        result = data.get("issueLabelCreate") or {}
        created = (result.get("issueLabel") or {}).get("id") if result.get("success") else None
        return created or lookup()

    def create_issue(self, team_id: str, title: str, description: str = "",
                     state_name: str = "Todo", label_ids: list[str] | None = None,
                     project_id: str | None = None) -> dict | None:
        """Create an issue; returns it normalized (labels as names), or None. With `project_id`
        (a Linear Project, STB §10) it is strict: any failure raises LinearError."""
        state_id = self.resolve_state_id_by_team(team_id, state_name)
        variables: dict = {"teamId": team_id, "title": title}
        if description:
            variables["description"] = description
        if state_id:
            variables["stateId"] = state_id
        if label_ids:
            variables["labelIds"] = list(label_ids)
        if project_id:
            variables["projectId"] = project_id
            result = self._graphql_strict(_MUTATION_CREATE_ISSUE, variables).get("issueCreate") or {}
            if not (result.get("success") and result.get("issue")):
                raise LinearError("Linear did not create the issue")
            return _normalize(result["issue"])
        data = self._graphql(_MUTATION_CREATE_ISSUE, variables)
        result = (data.get("issueCreate") or {})
        if result.get("success") and result.get("issue"):
            return _normalize(result["issue"])
        return None
