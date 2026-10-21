---
status: in-progress
created: 2026-10-21
---

# Projects panel: a manual Commit button on each session row

## Goal

The user asked (2026-10-21): "在 project dashboard 上面……不同的 session 后面……在 resume、rename、remove 中间加一个 commit……这样我可以手动地 commit".

Each session row gets a **Commit** button between Resume and Rename. Clicking it shows what would be committed. When the user confirms, the button commits every change in that session's checkout locally. It never pushes.

## Acceptance Criteria

- [x] Each session row shows buttons in this order: Resume, Commit, Rename, Remove.
- [x] Clicking Commit opens an inline editor in the row, the same way Rename does, with no modal.
  - It shows how many files changed, the branch and the folder.
  - It has a message input prefilled with the session's shown title.
  - It has Commit and Cancel buttons.
- [x] Committing stages all changes in that checkout (`git add -A`) and makes one local commit with the entered message on the checked-out branch. It never pushes.
- [x] The preview states plainly that it commits every change in that folder, not only this session's. Git can't tell which session made which edit.
- [x] After a commit, the row shows `committed <short sha> (N files)`.
- [x] With nothing to commit, the row shows `nothing to commit` and nothing is written.
- [x] Committing is refused, with nothing written and the reason shown in the row, when:
  - the session's checkout is neither the project's own folder nor an AgenticOS worktree of it;
  - HEAD is detached;
  - the message is empty;
  - the checkout is a ticket worktree whose ticket lock is held (a run, verify, cleanup or terminal is using it);
  - it is the main checkout while a merge into it is in progress.

## Approach

- `projects.commit_checkout(project, cwd, message, dry_run)`:
  - The repo is `git -C cwd rev-parse --show-toplevel`. It must resolve to `project.path`, or to an owned worktree (`ticket_from_worktree`).
  - In a worktree it holds `ticket_lock(key, ident)`, non-blocking. In the main checkout it holds `_MERGE_LOCK`, non-blocking.
  - For a dry run it returns `{repo, branch, files}` from `git status --porcelain -z --untracked-files=all`.
  - For a real commit it runs `git add -A`, then `git diff --cached --quiet` (meaning nothing to commit), then `git commit --no-verify --no-gpg-sign -q -m <message>`. The commit uses the existing hardened `_git` and confinement and the `_identity_env` fallback, the same as `runner_commit`.
- `POST /api/projects/<key>/sessions/<agent>/<sid>/commit` with `{message, dry_run}`. It resolves the row through `session_target`, which is project-confined, then calls `commit_checkout`. Errors come back as 4xx with a message.
- UI: `_sessionRow` adds the button. The Commit action fetches the dry run, then renders the inline editor; Save posts the real commit.

## Decisions

- **The whole checkout, said plainly.** A session doesn't own its edits. The preview counts every changed file in that folder, so the user decides with full information.
- **Hooks off, unsigned.** This matches `runner_commit`: the runner never executes repository-configured hooks (agent-writable). A user who needs hooks commits in a terminal.
- **No idle requirement for the session.** It is the user's own choice. Runner-owned work is protected by the ticket lock and the merge lock.

## Verification

- [x] Unit test: a dry run lists changed and untracked files and the branch, and writes nothing.
- [x] Unit test: a commit stages everything and makes one commit with the message.
- [x] Unit test: nothing to commit gives `committed: null` and no new commit.
- [x] Unit test: a repo top outside the project is refused.
- [x] Unit test: a detached HEAD is refused.
- [x] Unit test: an empty message is refused.
- [x] Unit test: a held ticket lock refuses a worktree commit.
- [x] Unit test: a held merge lock refuses a main-checkout commit.
- [x] Route test: the endpoint commits for a valid session row, and refuses an unknown session with 404.
- [x] Browser (isolated runner): the row shows Resume · Commit · Rename · Remove in that order.
- [x] Browser: Commit shows the preview and the prefilled message, then commits, and the row shows `committed <sha>`.
- [x] Browser: the console shows no errors. Evidence (isolated runner :8599): the buttons were [Resume, Commit, Rename, Remove]; the preview said "all 2 changed files in Demo_app · main" with the prefilled "Fix the widget"; the commit gave "committed b5fb618 (2 files)"; git log showed the message and git status was clean; errors=[].
- [x] Full suite passes: 791 passed.

## Progress Checklist

- [x] Add `projects.commit_checkout`.
- [x] Add the commit route.
- [x] Add the UI button and inline editor.
- [x] Write the tests.
- [x] Run the browser checks.
- [x] Run the full suite.
- [x] Commit (no push).
- [x] Inspection 1 fixes: sticky confidentiality plus the shared lifecycle lock in the route (SC-001/002); refusal on git's own in-progress merge, cherry-pick, revert or rebase, or unmerged entries (SC-003); a read-only status (SC-004); a correct rename/copy porcelain parse shared by `uncommitted()` (SC-005). 6 tests added; a manual check confirmed sandboxed commits work for a confidential main checkout and worktree.
- [x] Inspection 2 fixes: always-sandboxed manual commits (SC-006); queued merges take the verified sha (SC-007). Tests added.
- [x] Inspection 3 fixes: the preview status is sandboxed (SC-008); queued merges are re-validated under the ticket lock (SC-009).
- [x] Inspection 4 fixes: a bounded wait for a finalizing ticket's lock, with the entry kept on timeout (SC-010); the preview status runs in a write-nothing sandbox (SC-011).
- [ ] Fresh Codex inspection approved.
- [ ] Restart the live runner when it is idle.
- [ ] Archive the plan and its log.
