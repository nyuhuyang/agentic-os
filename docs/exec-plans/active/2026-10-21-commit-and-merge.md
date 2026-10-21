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
- [ ] Fresh Codex inspection approved.
- [ ] Archive.
