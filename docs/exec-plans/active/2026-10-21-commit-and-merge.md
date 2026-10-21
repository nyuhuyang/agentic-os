---
status: in-progress
created: 2026-10-21
---

# Session Commit: colour by state, and commit & merge on worktree rows

## Goal

The user asked for two things (2026-10-21):

- Grey Commit when the work is already merged into main, green when it isn't.
- A green Commit should "commit and merge to main", instead of showing "Nothing to commit".

## Acceptance Criteria

- [x] Each session row carries a read-only `commit_state`:
  - `dirty`: uncommitted changes in the folder;
  - `unmerged`: a clean worktree whose `agent/<id>` has commits the main checkout's HEAD lacks;
  - `clean`: neither;
  - none (neutral): the folder is outside the project.
- [x] The status runs in the write-nothing sandbox, once per checkout.
- [x] The button is green for `dirty` / `unmerged` and grey for `clean`, and its tooltip says which.
- [x] On a worktree row, Commit commits any changes, then merges `agent/<id>` into the main checkout. It holds the ticket lock throughout and uses `merge_into_checkout`: conflict-free only, under the ticket's own policy, and inside the project's merge gate.
- [x] A clean worktree that is ahead of main gets a merge-only action (no message needed).
- [x] The merge is refused while another run of the project is open. The commit then stands, and the row says why it didn't merge.
- [x] The preview names the commit and the merge target, and the button reads `Commit & merge`, `Merge` or `Commit` to match.

## Verification

- [x] tests/test_session_commit.py covers `commit_state` (dirty, unmerged, clean and neutral; one status per checkout).
- [x] tests/test_session_commit.py covers commit then merge, merge only, a refused merge keeping the commit, and `_manual_merge` with no run open.
- [x] Browser check:
  - the worktree row's button was green;
  - the preview said "…, then merge into main";
  - "Commit & merge" gave "committed f05032b · merged into main";
  - the button then turned grey, and the file was in main;
  - errors=[].
- [x] Full suite: 815 passed.

## Progress Checklist

- [x] Implement and test.
- [x] Inspection 1 fixes:
  - CM-001: the binding and branch are validated under the ticket lock; a switched worktree is refused and shows neutral.
  - CM-002: the manual merge takes the `refs/heads` sha, and the default merge target is fully qualified.
  - CM-003: one status per checkout root.
- [x] Inspection 2 fixes:
  - CM-004: a manual merge also counts session-card agents working in the main checkout, which register under the merge gate.
  - CM-005: `--commit --no-squash`, plus a post-merge check that the commit landed.
  - CM-006: a failed status is cached as neutral.
- [x] Inspection 3 fixes:
  - the merge clears inherited mergeOptions, never autostashes, refuses a target mid-operation, and verifies the merged tree (CM-007/008/009);
  - the manual merge counts runner-root jobs when the project is the runner's checkout, and jobs still retiring (CM-010/011).
- [x] Inspection 4 fixes: the mergeOptions key comes from the full ref (CM-012); a stalled job stays in _RETIRING while it is killed, and the cancel/stall paths always clear it (CM-014).
- [x] CM-013: every runner-root launch (/run, generic retry, unbound Linear dispatch and its routing call) takes the project merge gate before it publishes its job, so none can start mid-merge when the project is the runner's own checkout. Done after the user said "做": `_publish_job` publishes these jobs under that gate, and `_root_activity` counts a routing call while it runs. The runner-root lookup reads only the registry file. Tests added; the suite passed (831).
- [x] Inspection 5 fixes:
  - `--strategy=ort` (CM-015);
  - `--no-overwrite-ignore` (CM-016);
  - a launch-gap marker until the Popen handshake (CM-017);
  - gates and activity keyed by checkout (CM-018);
  - normal completions are no longer retiring activity (CM-019).
- [x] Inspection 6 fixes:
  - no launch for an ended run, and the marker carries the live job (CM-020);
  - successful generic runs kill leftover descendants (CM-021);
  - checkout aliasing for the manual merge only (CM-022).
- [x] Inspection 7 fixes: the routing helper kills its group on success (CM-023); agent tabs in the main checkout block manual merges and spawn under the merge gate (CM-024).
- [ ] Fresh Codex inspection approved.
- [ ] Archive.
