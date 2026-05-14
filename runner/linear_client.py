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
mutation AgenticOSCreateIssue($teamId: String!, $title: String!, $description: String, $stateId: String) {
  issueCreate(input: {teamId: $teamId, title: $title, description: $description, stateId: $stateId}) {
    success
    issue { id identifier title state { name } url }
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
    createdAt
    updatedAt
  }
}
"""


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

    def create_issue(self, team_id: str, title: str, description: str = "",
                     state_name: str = "Todo") -> dict | None:
        state_id = self.resolve_state_id_by_team(team_id, state_name)
        variables: dict = {"teamId": team_id, "title": title}
        if description:
            variables["description"] = description
        if state_id:
            variables["stateId"] = state_id
        data = self._graphql(_MUTATION_CREATE_ISSUE, variables)
        result = (data.get("issueCreate") or {})
        if result.get("success"):
            return result.get("issue")
        return None
