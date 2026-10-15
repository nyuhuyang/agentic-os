---
status: in-progress
created: 2026-10-15
---

# Pick a project when creating a task

## Goal
The new-task form (job board "+" / Todo) gets a Project selector listing the registered projects. The chosen project decides where the task runs: its dispatch goes to a worktree of that project, exactly like a Linear ticket labelled `project:<key>` today. If the user picks nothing, the task belongs to `agentic-os`. User request, 2026-10-15.

## Acceptance criteria
- [ ] The new-task form shows a Project selector with every registered (parseable) project; `agentic-os` is preselected when registered
- [ ] Creating a task with a project stores `project:<key>` as a label on the local task and on the Linear issue, and its dispatch runs in a worktree of that project on `agent/<id>`
- [ ] Creating a task without choosing uses `agentic-os`; if `agentic-os` is not registered, the task is created without a project and the form says it will run at the runner root (today's behaviour)
- [ ] A task dispatched before its Linear copy exists (local-first) already carries the project, so it never falls back to the runner root
- [ ] An unknown or broken project key is refused at creation (400) with nothing created
- [ ] Existing tasks without a project keep today's behaviour

## Decisions
- The project travels as the existing `project:<key>` label, so dispatch, retry and the durable binding need no new path (`project_runs.project_key_from_labels`, `_dispatch_issue`).
- The local tracker gains a `labels` list on each task (default empty) and the normalized issue exposes it; old task files without the field read as `[]`.
- Linear: the label is looked up by name (`issueLabels(filter: {name: {eq}})`), created in the team when missing (`issueLabelCreate`), and attached at create (`issueCreate.labelIds`); the background create already runs there.
- Default `agentic-os` is the registry key, resolved at form-load time from `/api/projects`; the server applies the same default when the request omits `project`.

## Approach
- [ ] `local_tracker.create_issue(..., labels=None)` stores `labels`; `_normalize` / `fetch_issue(s)` return it
- [ ] `POST /api/linear/issues` accepts `project` (key or empty): validate against the registry (refuse unknown/broken), default to `agentic-os` when registered, pass `labels=["project:<key>"]` to the local create and to the background Linear create
- [ ] `LinearClient`: `ensure_label(team_id, name)` and `create_issue(..., label_ids=[...])`
- [ ] UI: Project `<select>` in the new-task form (registered keys from `/api/projects`, `agentic-os` preselected, "No project (runner root)" as the last option); the draft keeps the choice
- [ ] The board card shows the task's project as a small badge

## Non-goals
- Changing the project of an existing task (re-labelling a bound ticket conflicts with its durable binding)
- Creating a project from the task form (use "+ Project")

## Risks
- A task created under `agentic-os` now runs in an `agentic-os` worktree, not in the runner's own checkout; tasks that relied on the runner root (e.g. editing `state/`) need "No project"
- Label creation needs the Linear key's write scope (already used for comments and issue creation)

## Verification
- Proof: `.venv/bin/python -m pytest tests/` passes
- Manual: create one task with a project, one with the default, one with "No project"; dispatch each and check the worktree/branch (or runner root) and the Linear label

## Progress Checklist
- [ ] Test: local task stores and returns `labels`; an old task file without the field reads as `[]`
- [ ] Test: create with `project` → label on the local task; omitted → `agentic-os` when registered, none when not; unknown key → 400, nothing created
- [ ] Test: a local-first task dispatched before its Linear sync runs in the chosen project's worktree
- [ ] Test: `ensure_label` reuses an existing label and creates a missing one; `create_issue` sends `labelIds`
- [ ] Implement tracker labels, route, Linear client, UI selector and card badge
- [ ] Codex plan review returns APPROVED
- [ ] Proof: `.venv/bin/python -m pytest tests/` passes
- [ ] Manual check of the three creation cases, including the Linear label
- [ ] Fresh cross-provider (Codex) build inspection returns no unresolved material findings
