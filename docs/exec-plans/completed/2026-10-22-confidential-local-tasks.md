---
status: completed
created: 2026-10-22
completed: 2026-10-22
---

# Confidential project tasks stay on the local board (option A, AGE-127)

## Goal

While the tracker is Linear, a task for a confidential project is created, shown, dispatched, moved, renamed, commented on and trashed entirely in the local tracker (`state/tasks.json`). Nothing about it reaches Linear: no issue, no `project:<key>` label, no comment, no state push. Non-confidential tasks behave exactly as today.

User decision (2026-10-22): option A. The stopgap `_refuse_confidential_on_linear` (AGE-127, commit a379ac8) blocks adding any task for a confidential project from the "+" form and from session to-board; the user reported that as a bug ("+ New task" shows "confidential project: its tasks are not created on Linear"). This plan removes it.

## Acceptance Criteria

- [x] In Linear mode, "+ New task" for a confidential project creates a task in `tasks.json` with `local_only: true`
- [x] No Linear request is made for that task
- [x] In Linear mode, session to-board for a confidential project creates a local-only task the same way
- [x] A local-only task stays on the board across Linear polls, in the all-teams view and in every team-filtered view
- [x] A local-only Todo task can be dispatched, runs in its project worktree, and moves running → review with every state change written only to the local tracker
- [x] Rename works for a local-only task with no Linear request
- [x] Description edit works for a local-only task with no Linear request
- [x] Preferred-agent change works for a local-only task with no Linear request
- [x] Todo reset works for a local-only task with no Linear request
- [x] Retry works for a local-only task with no Linear request
- [x] Cancel works for a local-only task with no Linear request
- [x] Empty trash works for a local-only task with no Linear request
- [x] Runner comments and dashboard feedback for a local-only task go to the local tracker (or are refused as today for confidential feedback), never to Linear, also after the project is declassified
- [x] A local-only task's state, title and comments in `tasks.json` are never overwritten by a stale cache copy
- [x] An unsynced placeholder of a non-confidential task (id `local-…`, no `local_only`) is still never dispatched or retried while Linear is active
- [x] Non-confidential tasks in Linear mode keep today's behaviour: the existing tests pass unchanged
- [x] The board shows a local-only card without the "syncing…" badge and with a "local" marker
- [x] The stopgap `_refuse_confidential_on_linear` and its error message are gone
- [x] No private project names in tracked files

## Approach

### One flag, one predicate

`LocalTracker.create_issue(..., local_only=False)` stores `"local_only": True` when asked. Only the confidential create paths set it; the local-first placeholder of a non-confidential task never does, so its background sync and id swap are unchanged.

`local_only_id(issue_id)` (module level) is true when the id starts with `local-` and either the cache entry or the persisted `tasks.json` record has `local_only: True`. The persisted record is authoritative: a cache entry without the flag (for example the bare `{id, state}` entry `push_state` builds) never makes it false (review R1). It does not depend on the tracker type, so it holds across restarts and tracker switches.

`LinearModule._on_linear(issue_id)` = tracker type is Linear and not `local_only_id(issue_id)`. Every per-issue path that branches on the global tracker type branches on this instead. `unsynced_local_id` returns False for local-only ids, which opens the dispatch, retry and board-move gates in `_dispatch_issue_held`, `_issues_local_patch`, `_issues_patch` and app.py's retry route.

### tasks.json is the only truth for local-only tasks

The Linear cache holds a copy of each local-only task for display, refreshed from `tasks.json` on every poll publish (under the issue locks the publish already holds). The copy never flows back: `_sync_cache_to_local` skips local-only entries, and the poll's stale terminal carry-over skips them too, since the fresh `tasks.json` copy replaces them (review R2). Comments, which `LocalTracker.post_comment` writes straight to `tasks.json`, therefore survive.

Local-only tasks get no Linear override: `_remember_local_override` ignores them, `_apply_local_override` returns them unchanged, and the local write paths drop any override already present (review R3). A cache write for a local-only id with no cache entry hydrates the full record from `tasks.json` first.

`push_state` persists a local-only state change synchronously, inside the issue lock it already takes, instead of handing it to a `_start_counted` worker. Pushes for one card then land in call order, so a delayed "running" write can never overwrite a later "review" (review R6). A local `tasks.json` write is fast, so the caller does not need the worker.

### Create paths

"+" form (`_issues_post`): after `_project_labels`, when the tracker is Linear and the labelled project is registered and confidential, create the task locally with `local_only=True` (team id = the request's team or `tracker.team_id`, may be empty), put it in the caches and `_fresh_ids`, emit, and return before any Linear client is built. Session to-board (`create_session_issue`) applies the same rule inside its Linear branch. `_refuse_confidential_on_linear` is replaced by `_confidential_labels(labels)`.

### Team views

`_issues_get` with a team filter includes every local-only task (it belongs to no Linear team), still filtered by the archived set. The empty-cache fallback already loads `tasks.json`.

### Comments

`_issues_comment` keeps its confidential refusal first (Decision 4). A permitted comment for a local-only task (the project was declassified before any binding pinned it) goes to the local tracker; the route no longer calls `_post_linear_comment_raw` for it (review R4). `post_comment` routes the same way for runner comments.

### Non-goals

- Existing Linear issues of confidential projects stay on Linear; no migration.
- A project switched from confidential to non-confidential keeps its local-only tasks local.
- `_refresh_linear_async` has no caller; it is left untouched.

## Assumptions and risks

- Local ids start with `local-` (`local_tracker._new_issue`); identifiers are `LOC-<n>` from `_next_identifier`, unique within `tasks.json`, so project worktree paths stay unique.
- Risk: a per-issue Linear path missed by the checklist would 404/500 or send the local id to Linear. Mitigation: the tests replace both Linear transports (`LinearClient` and the raw comment request in `_post_linear_comment_raw`) with fakes that fail the test on any call, and drive every route a local-only card uses.
- Risk: a create inside the poll's fetch–publish window: covered by `_fresh_ids` and by the publish re-reading `tasks.json`.

## Verification

- [x] `.venv/bin/python3 -m py_compile runner/*.py runner/modules/linear/*.py` passes
- [x] Test: "+" form, Linear mode, confidential project → 200
- [x] Test: that task's `tasks.json` entry has `local_only: true`
- [x] Test: the "+" form case makes no Linear request (failing fakes for `LinearClient` and the raw comment transport)
- [x] Test: session to-board, Linear mode, confidential project → local-only task, no Linear request
- [x] Test: a simulated poll keeps the local-only task in `issues_cache`
- [x] Test: a team-filtered `/api/linear/issues?team_id=…` response includes the local-only task
- [x] Test: dispatching a local-only Todo task reaches `_run_project_ticket` with the project key and the `LOC-` identifier
- [x] Test: `push_state` for a local-only id with no cache entry writes `tasks.json` (R1)
- [x] Test: that `push_state` makes no Linear request (R1)
- [x] Test: a comment appended to `tasks.json` between a poll's fetch and its publish survives `_sync_cache_to_local` (R2)
- [x] Test: the same holds for a Canceled local-only task kept by the terminal carry-over (R2)
- [x] Test: a Todo reset (mirror PATCH then authoritative PATCH) followed by dispatch and run end shows the card in review, not a stale Todo override (R3)
- [x] Test: dashboard feedback on a local-only task of a declassified project goes to `tasks.json`, not Linear (R4)
- [x] Test: renaming a local-only task updates `tasks.json` with no Linear request
- [x] Test: moving a local-only task to Todo updates `tasks.json` with no Linear request
- [x] Test: the retry route accepts a local-only task in Linear mode
- [x] Test: Empty trash deletes a Canceled local-only task from `tasks.json` with no Linear request
- [x] Test: `push_state("running")` then `push_state("review")` for a local-only task leaves `tasks.json` and the next poll at In Review, with no worker between them (R6)
- [x] Test: the existing `test_unsynced_local_id_is_never_dispatched_while_linear_is_active` passes unchanged
- [x] Test: the stopgap test is replaced; no test expects the "not created on Linear" refusal
- [x] Full pytest suite passes
- [x] `/verify`: isolated runner on 8599 in Linear mode (dummy `LINEAR_API_KEY`), with a `sitecustomize.py` on `PYTHONPATH` that answers every `api.linear.app` request locally and logs it
- [x] `/verify`: a confidential task created from the "+" form renders without "syncing…" and with the "local" chip
- [x] `/verify`: the task runs with a fake agent and the card ends in review
- [x] `/verify`: the request log has no call naming the task's id, identifier or title
- [x] `git grep` for the private project names (pattern kept outside the repo) finds nothing

## Progress Checklist

- [x] Plan reviewed by Codex (cross-provider) and approved
- [x] `LocalTracker.create_issue` gains `local_only`
- [x] `local_only_id` added, persisted flag authoritative
- [x] `_on_linear` added
- [x] `_confidential_labels` added
- [x] `unsynced_local_id` excludes local-only ids
- [x] "+" form creates local-only tasks for confidential projects in Linear mode
- [x] `create_session_issue` creates local-only tasks for confidential projects in Linear mode
- [x] `_refuse_confidential_on_linear` deleted
- [x] Poll publish refreshes local-only tasks from `tasks.json`
- [x] Poll terminal carry-over skips local-only entries
- [x] `_sync_cache_to_local` skips local-only entries
- [x] Team-filtered `_issues_get` includes local-only tasks
- [x] `_remember_local_override` ignores local-only ids
- [x] `_apply_local_override` returns local-only issues unchanged
- [x] `_issues_detail` reads local-only tasks locally
- [x] `_issues_local_patch` renames sessions for local-only titles
- [x] `_issues_local_patch` drops overrides of local-only ids
- [x] `_issues_patch` fetches the persisted local-only issue before `reserve_card`
- [x] `_issues_patch_reserved` takes the local branch for local-only ids
- [x] `move_to_todo` routes by `_on_linear`
- [x] `set_card_title` routes by `_on_linear`
- [x] `_restore_issue_state` routes by `_on_linear`
- [x] `_ensure_linear_project` skips local-only ids
- [x] `push_state` hydrates a missing cache entry from `tasks.json`
- [x] `push_state` persists local-only state synchronously under the issue lock
- [x] `_push_sync` routes by `_on_linear`
- [x] `post_comment` routes by `_on_linear`
- [x] `_issues_comment` routes permitted local-only comments to the local tracker
- [x] `_linear_sync_patch_locked` returns early for local-only ids
- [x] `canceled_issues` includes Canceled local-only tasks
- [x] `_still_canceled` reads local-only tasks locally
- [x] `empty_trash` deletes local-only tasks locally instead of `archive_issue`
- [x] app.py `_tracker_issue` falls back to `tasks.json` for local-only ids
- [x] app.py `_confirmed_title` reads local-only titles from `tasks.json`
- [x] Board UI: `unsynced` excludes local-only tasks
- [x] Board UI: "local" chip on local-only cards
- [x] Tests written for every Verification test item
- [x] Verification checks run and ticked
- [x] Fresh Codex inspection of the build
- [x] Accepted inspection findings fixed and reinspected in a fresh session
- [x] `docs/context-maintenance.md` records the result and next action
- [x] Plan and review log archived to `docs/exec-plans/completed/`
