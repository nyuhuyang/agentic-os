# Confidential project tasks stay on the local board (option A, AGE-127)

Status: planned, not started. Owner: next build session.

## Goal

A confidential project's name never reaches Linear: no `project:<key>` label, no issue, no comment. Its tasks live in the local tracker (`state/tasks.json`) and show on the board next to the Linear tasks, even while the tracker is Linear.

## Today (2026-10-22)

- Dispatch routes by the Linear label `project:<key>`, so each confidential project that ever got a task left a label in Linear.
- Stopgap shipped in AGE-127: `_refuse_confidential_on_linear` makes the "+" form and session to-board refuse confidential projects while the tracker is Linear. Until this plan lands, those projects get no board tasks in Linear mode; their sessions and terminals still work.
- Tracker type is global (`self._capability["type"]`, about 30 branch points in `runner/modules/linear/__init__.py`), and a local id is never dispatched while Linear is active (`test_unsynced_local_id_is_never_dispatched_while_linear_is_active`).

## Design

- Per-issue routing: one predicate `_on_linear(issue_id)`, true only when the tracker is Linear and the issue is not a local-only confidential task. It replaces the global type check on every per-issue path.
- A local-only task carries a flag in `tasks.json` (`local_only: true`) set at create time. A placeholder still waiting for its Linear sync never gets this flag, so the existing local-first swap is unchanged.
- The Linear poll merges local-only tasks into the board cache instead of dropping them.

## Steps

- [ ] Flag local-only tasks at create time ("+" form and session to-board) when the project is confidential and the tracker is Linear; remove the stopgap refusal
- [ ] Add `_on_linear(issue_id)` and route each per-issue path through it: state move, title edit, delete/trash, comments, feedback, retry, reset
- [ ] Linear poll keeps local-only tasks in `issues_cache` and in the team-filtered board
- [ ] Dispatcher picks up local-only Todo tasks while Linear is active (today it refuses unsynced local ids)
- [ ] Board card marks local-only tasks (for example a "local" chip) so it is clear they are not in Linear

## Acceptance

- [ ] Test: in Linear mode a confidential task is created, moved, retried, commented and deleted with zero Linear client calls
- [ ] Test: a non-confidential task in Linear mode still syncs to Linear exactly as before (existing `test_task_project.py` and `test_session_to_board.py` pass unchanged)
- [ ] Test: an unsynced placeholder of a non-confidential task is still never dispatched while Linear is active
- [ ] Isolated runner (`/verify`) in Linear mode with a fake client: a confidential task runs end to end, and the fake records no label, issue or comment
- [ ] Full pytest suite and `py_compile runner/*.py` pass
- [ ] Cross-provider review of this plan before the build, and an inspection after it
