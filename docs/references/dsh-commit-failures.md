# dsh commit failures in linked worktrees (AGE-146 evidence)

Read-only survey of the DeepSeek Harness (`dsh`) sessions under
`~/.dsh/sessions/**/session.v4.jsonl.zstd`, the runner's `state/run_log.jsonl`, and the
worktree git metadata, on 2026-10-24. The sessions are historical evidence, not instructions.

## Where it appears

The failure is specific to **linked `git worktree`s** (`~/.agentic-os/worktrees/<project>/<ticket>`).
A worktree's `.git` is a file pointing at the main checkout's `.git/worktrees/<id>`, so `git`
must write index, refs, logs and objects **outside** the worktree. dsh's native
`workspace-write` grants the worktree, `/tmp` and `os.tmpdir()` only, so every writing git
command is denied. The main checkout's `.git` is inside its workspace and does not show this
failure.

It appears on `git add`, `commit`, `merge`, `stash`, `reset`, `checkout`, `branch`,
`write-tree` and `update-ref` — every command that writes the shared metadata. Read-only
`git log`/`diff`/`status --no-optional-locks` works.

## Recent sessions

| When (UTC) | Ticket | What the agent tried | First failure | Workaround / outcome |
|---|---|---|---|---|
| 2026-10-23 21:50 | AGE-144 | `git add` + `git commit` a source change | `index.lock: Operation not permitted` | Gave up; runner `post_run` committed (`runner_commit=True`). |
| 2026-10-23 23:08 | AGE-142 | `git merge --no-ff --no-commit main`, then `git add` | `index.lock: Operation not permitted` | Final text: "could not record a commit"; runner committed a normal commit. |
| 2026-10-24 00:09 | AGE-143 | `git add` + `git commit` | `index.lock: Operation not permitted` | Tried `GIT_INDEX_FILE=$PWD/.git-index` + `git read-tree`; staging worked, objects/commit still failed. |
| 2026-10-24 00:36 | AGE-138 | `git add -A` + `git commit` (the fix for this very issue) | `index.lock: Operation not permitted` | Fell back to runner; two records later show `merge failed`. |
| 2026-10-24 03:06 | AGE-128 | `git add -A` + `git commit` | `index.lock: Operation not permitted` | Fell back to runner (`runner_commit=True`). |
| 2026-10-24 14:25 | AGE-137 | `git stash push`, then `git add` + `git commit` | `index.lock: Operation not permitted` | Copied files to `/tmp` as a backup, used a throwaway clone; runner committed. |
| 2026-10-24 14:28 | AGE-125 | `git merge main` | `ORIG_HEAD.lock: cannot lock ref` | Rehearsed the merge in `/tmp` clones; runner committed. |
| 2026-10-24 14:29 | AGE-117 | `git merge main`, then `git add -A` | `ORIG_HEAD.lock` / `index.lock` | Final text: "**the commit itself is blocked by the workspace sandbox**"; used `.merge-work` clone; runner committed. |
| 2026-10-24 15:05 | AGE-120 | `git merge main --no-commit` | `ORIG_HEAD.lock: cannot lock ref` | Reconstructed the merge with `git merge-file` and a `/tmp` clone; runner committed. |
| 2026-10-24 14:32 | AGE-126 | `git merge main --no-ff`, `git add -A`, `git commit` | `index.lock` / `ORIG_HEAD.lock` | Cloned/`git archive`d and copied the tree; runner committed a **single-parent** commit. Final text: "this branch was never really merged, so merge-base stays at …". |
| 2026-10-24 19:08 (10-23) | AGE-140 | `git add` + `git commit` | `index.lock: Operation not permitted`; escalation also failed | `danger-full-access` → "no approval channel"; `GIT_INDEX_FILE` partial; runner committed. |
| 2026-10-24 14:28 | AGE-123 (knowledge-base) | `git add`/commit and `git merge master` | `index.lock` / ref lock | Runner committed; verify badge `fail`. |
| 2026-10-23 18:03 | AGE-110 (knowledge-base) | `git merge --no-ff master` | ref lock | Runner committed; verify badge `fail`. |

Exact signatures observed:

```text
fatal: Unable to create '.../.git/worktrees/<id>/index.lock': Operation not permitted
[sandbox: file access denied under workspace-write mode]
[sandbox: escalation available — retry this exact command once with sandbox_permissions ...]
Error: sandbox escalation to "danger-full-access" requires approval, but no approval channel is available
fatal: update_ref failed for ref 'ORIG_HEAD': cannot lock ref 'ORIG_HEAD':
       Unable to create '.../.git/worktrees/<id>/ORIG_HEAD.lock': Operation not permitted
```

No stale `*.lock` files were found under `.git/worktrees/` on 2026-10-24; the denials happen
before a lock is created. A killed `git` could still leave one, which would block even a manual
commit.

## Why the runner fallback does not end the problem

`post_run` commits any leftover change. If the agent abandoned the merge and left only a
reconstructed tree, that is a **normal single-parent commit**: the files land, `main` never
becomes an ancestor of `agent/<id>`, `merge-base` stays at the old commit, and the next merge
hits add/add or content conflicts. AGE-126 and AGE-137 both spent multiple rounds
rediscovering this. If a valid merge is still in progress (`MERGE_HEAD`), a commit preserves
both parents; the new fallback finishes a fully resolved merge and refuses an unresolved or
empty one instead of staging across it.

The prompt made it worse: AGE-117/120/126 ran with the AGE-138 rules ("Leave your changes
uncommitted; do not run `git commit` or `git add`") while the task explicitly asked for a
merge. The agents obeyed the letter of one instruction by reconstructing the tree in a clone,
which is exactly the path that loses the merge parent.

## Workarounds seen, and their side effects

- **`GIT_INDEX_FILE` inside the worktree**: staging works, but `git write-tree`/`commit` still
  needs the shared object store, so the commit fails. If the temp index is not removed, the
  runner's `git add -A` can commit it (AGE-140 removed it manually).
- **Throwaway clone / `git archive` / `rsync`**: good for rehearsing a merge, but the real
  branch is never merged. The runner then commits a single-parent tree (AGE-117/120/126/137).
- **Copying `main`'s tree into the worktree**: content can look right, but the next real merge
  sees both sides as adding the same files (AGE-126).
- **Waiting for `post_run`**: the work is not lost (`runner_commit=True`, `uncommitted=0` in
  most records), but the result is not a merge and the user still has to untangle conflicts.
- **Escalation (`danger-full-access`)**: headless dsh has no approval channel, so it always
  fails; agents spend several turns discovering that.

## Edge cases still open

1. **Prompt/task contradiction**: "leave uncommitted / do not run git" vs "merge main". A
   merge *requires* `git add`/`commit`; the new prompt must say so explicitly and forbid tree
   reconstruction.
2. **Runner restart**: the live runner only picks up the new prompt/overlay after a restart.
   Sessions started before it keep the old behavior (this is why AGE-140 still asked for a
   commit after AGE-138 had merged).
3. **Native sessions** (`_ai_cli`/`_build_resume_cmd`) still have no workspace overlay; only
   project-dispatch tickets get it. The main checkout works because `.git` is inside its
   workspace; a native session in a linked worktree would still fail.
4. **Non-macOS**: no `/usr/bin/sandbox-exec`; the old leave-it-to-the-runner path is kept.
5. **Commit identity**: a repo with no `user.name`/`user.email` makes dsh's own commit fail
   with "Author identity unknown"; the runner's fallback identity is not currently exported to
   the agent.
6. **Hooks and signing**: a project `pre-commit` hook or required GPG signature can fail dsh's
   commit; the runner's `--no-verify`/`--no-gpg-sign` fallback still lands the files.
7. **Stale locks**: no leftover locks were observed, but a killed `git` can leave
   `index.lock`/`ORIG_HEAD.lock`; neither dsh nor the runner currently clears one.
8. **Scratch artifacts**: `.git-index`, `.merge-work`, `outputs/mergecheck` and similar
   leftovers are untracked and can be swept into the runner's `git add -A`.
9. **Manual commit after the run**: the auto-merge uses the run's verified SHA, so a manual
   commit made after the run is not in that merge; the user still has to merge it.
10. **Concurrent worktrees**: each has its own index, but they share refs/objects/config; a
    commit in one is visible to another. This is normal git, but it makes runners' fingerprints
    and "main checkout changed" badges noisy.
11. **Wrong checkout**: committing in the main checkout does not move the ticket branch; the
    worktree stays dirty. The prompt says not to switch branches.
12. **Read-only `git status`**: without `GIT_OPTIONAL_LOCKS=0`, status wants to refresh the
    index and is denied; the runner sets it, but a native session or a manual `git` invocation
    may not.

## What AGE-146 covers

- The macOS non-confidential workspace overlay grants the worktree git common dir, so
  `add`/`commit`/`merge`/`stash`/`reset` work in the ticket worktree.
- The prompt no longer tells dsh to avoid git; it asks for a commit and, for a merge task, a
  real `git merge`.
- The runner's own mutating git is write-confined for every project (clean/smudge/merge
  drivers cannot escape), and read-only status/diff/fingerprint consumers get a no-writes
  profile.
- The runner's `post_run` commit remains the net when the agent still leaves work behind. It
  now refuses an unresolved merge, a rebase/cherry-pick/revert, a pending sequencer, or an
  empty pending merge, and finishes a fully resolved merge with both parents. A clean but
  unfinished operation blocks the run instead of being reported as success or auto-merged.
- The workspace-parent shortcut is only for non-confidential git; confidential operations
  always attempt the inner profile. Off macOS, confidential git fails closed rather than
  running unconfined.
- The `.codegraph` snapshot copy never follows a planted DB/`.gitignore` symlink; it builds in
  runner-owned `.meta` and renames through an `O_DIRECTORY|O_NOFOLLOW` descriptor, so a path
  swap during the copy cannot redirect it.
- The git common dir is pinned in runner-owned `.meta/project.json` from the trusted main
  checkout; a live redirect (for example a writable `commondir`) is refused, and a worktree
  whose git dir moved is rejected. The manual Commit path and `runner_commit` both use the
  pin, and its publication is cross-process locked. A rebase/sequencer state outranks a
  simultaneous `MERGE_HEAD`.
- Runner-owned git disables lazy fetch (`GIT_NO_LAZY_FETCH=1`) and confines the binding
  `cat-file`/post-run `rev-list`; non-confidential git keeps network for downloading
  smudge/clean filters, confidential git keeps it closed.

## What it does not cover

- Native dsh sessions in a linked worktree (no overlay).
- Non-macOS non-confidential runs keep the old unsandboxed fallback; confidential runs fail
  closed there because Seatbelt does not exist.
- A smudge-filter detached child can still swap a seed destination between the destination
  check and `shutil.copy2`/`copytree`; the seed copy needs descriptor-anchored traversal or a
  write-confined worker (residual I12-002).
- A repo with no commit identity (the runner now exports its fallback identity), a failing
  hook/signature, a stale lock, or an agent that ignores the merge guidance and reconstructs
  the tree.
