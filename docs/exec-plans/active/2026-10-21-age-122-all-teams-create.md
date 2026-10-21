---
status: in-progress
created: 2026-10-21
---
# AGE-122 — Create a task while "All Teams" is selected

## Goal

With "All Teams" selected on the Job Board, the "+" form and a session's "to board" action create a task, the same as with a team selected.

## Root cause

- `selectLinearTeam('')` PATCHes `/api/config` with `linear_team_id: ""`, which `runner/app.py:6083` stores as `tracker.team_id = ""`. One field is both the board's view filter and the team new issues go to.
- `POST /api/linear/issues` (`runner/modules/linear/__init__.py:1431`) takes `team_id` from the body (the form sends `_currentTeamId`, so `""`), falls back to `tracker.team_id` (also `""`), and returns `400 team_id required` in Linear mode (`:1445`).
- `create_session_issue` (`:1256`) reads only `tracker.team_id` and raises `tracker.team_id is required` in Linear mode (`:1260`).
- Local tracker mode is unaffected: it accepts an empty team.

## Approach

Add one method on the Linear module, `_create_team_id(client, requested="")`, returning `(team_id, error)`. Both Linear-mode create paths call it and refuse when `team_id` is empty: POST → 400 `{"error": error}`; `create_session_issue` → `RuntimeError(error)`, which the to-board route maps to 409 (`runner/app.py:4494`). Messages:

- several teams: `"Select a team on the Job Board to create a task (you belong to N teams)"`;
- zero teams (a failed lookup: `_graphql` returns `{}` on any error, so `fetch_teams` cannot tell failure from empty): `"Could not read your Linear teams; select a team on the Job Board or try again"`.

Step 3 calls `client.fetch_teams()` directly, not the 30-min cache: a stale cached team must never be chosen after a failed or changed lookup (review R3). It runs only when no team is selected, once per create. The poller's `_get_or_refresh_teams` cache is left unchanged (review R4: suppressing empty fetches there would keep polling a team after a real zero-membership result).

### Decisions

- **Keep "All Teams" = empty `tracker.team_id`.** It is also the poller's "poll every team" switch (`:582-586`); splitting view filter and create team into two config keys is a schema change (escalation item) and not needed to fix the bug.
- **Several teams + "All Teams" → clear refusal, no guess.** Creating in an arbitrary team would file the task in the wrong place silently. A team picker in the "+" form is deferred until someone has more than one team (the user has one: AgenticOS).
- **Fresh team lookup on create, not the cache.** One extra GraphQL query per "All Teams" create (the create itself already makes several). A failed fetch gives the "Could not read" refusal, not a crash, and the next create retries.

### Non-goals

- No frontend change; no config schema change; no change to local tracker mode or to polling.

## Assumptions

- `_get_or_refresh_teams` returns `[{id, key, name}]` from `fetch_teams()` — `runner/modules/linear/__init__.py:539`, `runner/linear_client.py:476`.
- The to-board route turns `RuntimeError` from `create_session_issue` into an error response, not a 500 — check `runner/app.py:4493` while building.
- Live Linear: viewer belongs to one team (AGE) — verified 2026-10-21 via `viewer.teams`.

## Acceptance Criteria

- [ ] Linear mode, `tracker.team_id = ""`, viewer in one team: `POST /api/linear/issues` with `team_id: ""` returns 200 and the background create uses that team's id.
- [ ] Linear mode, `tracker.team_id = ""`, viewer in one team: to-board without a card creates the issue in that team.
- [ ] Linear mode, `tracker.team_id = ""`, viewer in two teams: POST returns 400 with the "Select a team" message and creates nothing (no local placeholder).
- [ ] A selected team (body `team_id` or `tracker.team_id`) is still used as before.
- [ ] A failed team lookup gives the "Could not read" refusal, and the next create after Linear recovers succeeds without waiting 30 min.

## Verification

- [ ] New pytest: POST with empty team, one viewer team → 200, create called with that team id.
- [ ] New pytest: POST with empty team, two viewer teams → 400 "Select a team", no task in `tasks.json`.
- [ ] New pytest: to-board with empty `tracker.team_id`, one viewer team → issue created with that team id.
- [ ] New pytest: first `fetch_teams` returns `[]` → POST 400 "Could not read" and no placeholder in `tasks.json`; second returns one team → POST 200.
- [ ] New pytest: module team cache pre-filled with a stale single team, `fetch_teams` returns `[]` → POST 400 "Could not read", no placeholder (cache not consulted).
- [ ] Existing suites pass: `.venv/bin/python3 -m pytest tests -q` (use the main checkout's `.venv` if the worktree has none).
- [ ] `python3 -m py_compile runner/*.py runner/modules/linear/__init__.py` passes.
- [ ] Isolated runner (`/verify` skill) in Linear-less local mode still creates a task with "All Teams" (regression check of local path).

## Progress Checklist

- [ ] Add `_create_team_id`: step 1, a non-empty `requested` (stripped) wins.
- [ ] `_create_team_id`: step 2, else a non-empty `tracker.team_id`.
- [ ] `_create_team_id`: step 3, else the only team when a fresh `client.fetch_teams()` returns exactly one.
- [ ] `_create_team_id`: step 4, else `""` plus the zero-teams or several-teams message.
- [ ] POST route: build the `LinearClient` before the team check (it already has the key).
- [ ] POST route: call `_create_team_id` in Linear mode before the local placeholder is written; empty → 400 with its message.
- [ ] `create_session_issue`: call `_create_team_id` with the existing `client`; empty → `RuntimeError(message)`.
- [x] Confirm the to-board route maps the `RuntimeError` to an error response (409, `runner/app.py:4494`; reviewer confirmed).
- [ ] Add the five pytest cases.
- [ ] Run Verification.
- [ ] Record validation in `docs/context-maintenance.md`.
- [ ] Commit on `agent/AGE-122`.
- [ ] Fresh Codex inspection of the diff.
