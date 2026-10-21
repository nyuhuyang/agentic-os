# Review log: session-commit-button

- 2026-10-21. User request: add a manual Commit button between Resume and Rename/Remove on session rows.
- Roles: Claude plans and builds; a fresh Codex session inspects the code. There was no separate plan review: the user asked for the feature directly, not for a claudex-loop.
- Pre-build base: adc036a9acbdd766ba9c9efa81009953bba32573. Commit: yes, push: no.
- Build: 9 new tests; suite 791 passed; browser check passed (see the plan's Verification).

## Inspection 1 — Codex (fresh): REVISE
- Result: /private/tmp/claude-501/claudex-scb/i1/*/result.json, cross_provider.
- SC-001 (high) accepted: the route now applies session_confidential (registry, sidecar, bindings, session history; unknown = confidential).
- SC-002 (med) accepted: the route holds the shared project_lock for the whole operation.
- SC-003 (med) accepted: _git_operation refuses MERGE_HEAD, CHERRY_PICK_HEAD, REVERT_HEAD, rebase-merge/apply, and unmerged entries.
- SC-004 (low) accepted: uncommitted() uses --no-optional-locks.
- SC-005 (low) accepted: _porcelain_paths consumes the rename/copy source token (shared with the post-run dirty check).

## Inspection 2 — Codex (fresh): REVISE
- SC-006 (high) accepted: manual commits now always run git sandboxed (writes confined to the repo and its common git dir), whatever the policy. No confidentiality snapshot can go stale, and the route's policy read is removed.
- SC-007 (med) accepted at the source: _merge_when_last queues (ticket, verified sha) read under the ticket lock, and merge_into_checkout merges that exact sha (validated hex) with a "Merge branch 'agent/X'" message. A later commit on the branch (manual Commit or terminal) never rides in on an earlier verification. A head-read failure is recorded as merge failed.

## Inspection 3 — Codex (fresh): REVISE
- SC-008 (high) accepted: uncommitted() takes an explicit confine, and commit_checkout passes its unconditional sandbox, so the preview's status (which can run clean filters) is confined too. Test asserts every status call is confined.
- SC-009 (med) accepted: before merging a queued (ticket, sha), the drain takes that ticket's lock (except its own, already held) and check_queued_merge confirms the binding still exists and agent/<ticket> still contains the sha. Cleanup or a replaced branch refuses the merge (merge_error). Tests: cleanup and replacement refused; the drain checks every entry.

## Inspection 4 — Codex (fresh): REVISE
- SC-010 (med) accepted: the drain waits up to 120 s for another ticket's lock (its run is still finalizing) via _wait_ticket_lock. Only the acquire is retried. On timeout the entry is kept in the queue for the project's next run, not dropped. Test: a held lock is waited for, then kept.
- SC-011 (med) accepted: readonly_status runs git status in a write-nothing sandbox (no writable roots, not even temp), used for the preview and the count. Only confirmed staging and commit are writable. Test: a clean filter's side-effect files are not created by the preview.

## Inspection 5 — Codex (fresh): REVISE
- SC-012 (high) accepted: each queued ticket is checked and merged under _effective_project(project, ticket), its own sticky policy, not the drainer's.
- SC-013 (med) accepted: a timed-out entry is requeued only when no entry for that ticket is queued, so a newer verification wins.
- SC-014 (med) accepted: the preview and commit responses apply only to the editor object that sent them; a failure restores that editor's own preview.
- SC-015 (low) accepted: sandbox paths are escaped as profile string literals; control characters are refused. Test: a checkout named My "app" \x previews and commits sandboxed.
- Browser recheck of the commit flow passed (Enter commits; errors=[]).

## Inspection 6 — Codex (fresh): REVISE
- SC-016 (med) accepted in part: after the lock wait, the drain re-checks under _JOB_LOCK whether another project run has opened. If so, the entry is requeued, not merged. This brings the window back to the original AGE-111 milliseconds. FOLLOW-UP: a per-project admission gate closing that residual window, noted as a ponytail comment on _project_runs_open.
- SC-017 (med) accepted: a single commit request per editor (a pending flag; the button is disabled and shows "Committing…"; repeated Enter is ignored), and the typed message is kept on failure. Browser check: double-click plus Enter gave exactly one commit, and the row showed its sha.
