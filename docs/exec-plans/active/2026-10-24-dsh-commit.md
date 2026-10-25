---
status: in-progress
created: 2026-10-24
---

# AGE-146: dsh commits its own work in a ticket worktree

## Goal

Make a non-confidential project's `dsh` run able to run `git add`/`git commit` in its linked
worktree, and ask it to commit, instead of telling it to leave every change to the runner. The
runner still commits any leftover change after the run, so a failed or skipped commit cannot
strand work.

## Findings (recon)

- A ticket worktree is a `git worktree`; its `.git` is a file pointing at the main checkout's
  `.git/worktrees/<id>`. `git rev-parse --git-common-dir` returned the main checkout's `.git`.
- `dsh` runs `workspace-write`; its native macOS Seatbelt profile is
  `(allow default)(deny file-write*)` plus the session cwd, `/tmp` and `os.tmpdir()`. The git
  common dir is outside all three, so `git add`/`git commit` is denied (AGE-138).
- AGE-138 worked around it by asking dsh to leave the commit to `post_run` and setting
  `GIT_OPTIONAL_LOCKS=0`; AGE-139 later gave *confidential* dsh the git common dir through
  `runner/dsh_confine.py` + `runner/scripts/dsh-confidential.yml` and `confidential_prompt`.
  Non-confidential project tickets never got that grant, which is the reported failure.
- `@deepseek-ai/dsh-sandbox-local` exposes `sandbox.runnerCommand`; it appends bwrap-dialect
  arguments (`--ro-bind / /`, `--tmpfs /tmp`, `--bind <root> <root>`, `--`, command) even on
  macOS. `dsh --patch` applies an entry overlay after the profile and user patch layers. Both
  are present in the installed `dsh` 0.2.1-rc.2 and were used by AGE-139.
- The wrapper must rebuild the profile itself, so it needs a mode: confidential keeps the
  network/app-service denials; workspace mirrors dsh's native write-only profile and adds the
  git common dir. `GIT_OPTIONAL_LOCKS=0` does not block `add`/`commit` (they take required
  locks); it only stops optional index refreshes.
- A survey of recent dsh sessions (`docs/references/dsh-commit-failures.md`) found the same
  denial in AGE-110/117/120/123/125/126/128/137/138/140/142/143/144: `index.lock` and
  `ORIG_HEAD.lock` under the main checkout's `.git/worktrees/<id>`, plus the dead-end
  `danger-full-access` escalation ("no approval channel"). Agents worked around it with
  `GIT_INDEX_FILE`, throwaway clones and copied trees. Those land the files, but the runner's
  `post_run` then makes a **single-parent** commit; `main` never becomes an ancestor and the
  next merge conflicts (AGE-126/137).
- The recent prompts made this worse: AGE-117/120/126 were told "leave uncommitted / do not run
  `git commit` or `git add`" while their task was "merge main". A merge requires those writes,
  so the agent obeyed the letter of one rule and reconstructed the tree in a clone.
- Everything after the agent still runs `project_runs.post_run`, which commits leftovers for
  every agent; that safety net stays.

## Design

The non-confidential dsh overlay keeps dsh's own write boundary and adds the linked worktree's
git common dir. `projects.sandbox_profile`/`sandbox_prefix` gain a `write_only=True` spelling:
`(allow default)(deny file-write*)` plus the writable roots, with no `(deny network*)`, no
lsopen/appleevent denials and no mach-lookup denials. The default (confidential) spelling is
unchanged.

`dsh_confine` takes an optional mode token after the git dir: `root, git-dir-or--,
confidential|workspace, bwrap-args..., --, command`. `confidential` keeps today's profile and
forces `/tmp` as the child TMPDIR. `workspace` builds the write-only profile over the worktree,
the ambient temp roots and the git common dir, and leaves TMPDIR alone. An absent token still
means `confidential`, so older callers cannot silently lose the network closure.

`runner/scripts/dsh-workspace.yml` pins only the `sandbox` entry's `runnerCommand` and failure
signature; it reuses `AGENTICOS_DSH_CONFINE_RUNNER`/`AGENTICOS_DSH_CONFINE_GIT` and passes
`workspace`. `dsh_cli.workspace_cli_prefix()` adds `--patch`; `verify_workspace_launch()`
composes it with `--dump-config` and refuses an unapplied patch or a sandbox block that is not
the dsh-confine runner. It deliberately does not require the stock profile, because
non-confidential runs may use a customized profile.

`app._project_exec_env` sets the two dsh-confine variables for a non-confidential dsh project
run, and `project_runs.agent_cli` returns the workspace prefix. `leaves_commit_to_runner` stays
true for Codex and becomes false for dsh on macOS, so the prompt asks dsh to commit. The
`confidential_prompt` override is removed because the shared prompt now covers both dsh modes.
`post_run`'s runner commit remains the safety net, and `GIT_OPTIONAL_LOCKS=0` remains for the
fallback where the overlay is unavailable.

Granting dsh the git common dir also lets it write `.git/config`, so a repository-configured
clean filter could otherwise run as the unsandboxed runner during `post_run`'s `git add -A`.
The runner's git is therefore confined for every project, not only confidential. Two helpers
are gated to macOS (else `None`, preserving the old non-macOS behaviour): `read_git_confine()`
returns no writable roots (temp only), and `write_git_confine(project, *paths)` returns the
git common dir plus the worktree/checkout. `uncommitted`, `fingerprint_parts`, the project
browser's `status`/`ls-files` and `_ignored_by_committed_rule` use the read-only profile,
because `git status` and working-tree `git diff` can run clean filters; `runner_commit`
(staging and commit), `merge_into_checkout` (merge-tree and merge) and `create_worktree`
(`git worktree add`, whose checkout runs smudge filters) use the writable one, matching
`commit_checkout`. Flags (`--no-optional-locks`, hooks/fsmonitor off,
`--no-ext-diff/--no-textconv`) remain, but they are not the defence: the Seatbelt profile is.

The workspace overlay is selected by an explicit ticket-dispatch flag on the shared launch
helpers. A native session continuation passes false, so it keeps today's prefix and no git
grant; only a validated ticket worktree gets the overlay and its leftover-commit path.

The dsh project prompt for a macOS ticket adds the missing merge guidance: the worktree git
metadata is writable, a merge task must run a real `git merge` in the worktree, and a clone,
`git archive`, `GIT_INDEX_FILE` or a copied tree is not a substitute because the runner's
leftover commit would lose the merge parent. `_project_exec_env` also exports the same
fallback author/committer identity the runner already uses, so a repo with no `user.email`
does not fail dsh's own commit.

Nested sandboxing is skipped **only for non-confidential workspace git**, and only when the
marker is `workspace` **and** an actual `/usr/bin/sandbox-exec` probe is refused (a parent
Seatbelt is active). The marker is child-controlled, so it is never trusted for a confidential
operation: confidential git, verify and manual commit always attempt the inner profile and
fail closed if it cannot start. The runner clears any inherited marker at startup; a spoofed
or `confidential` value is ignored. A failed probe with no marker still attempts the inner
profile.

`runner_commit` inspects the git operation state before staging. An unresolved merge, a
rebase/cherry-pick/revert, a pending sequencer (multi-commit cherry-pick/revert), or unmerged
index entries are refused without touching the index.
A fully resolved merge proceeds and `MERGE_HEAD` makes the fallback a real two-parent commit.
An empty pending merge is refused instead of leaving `MERGE_HEAD` behind. `post_run` also
refuses a clean tree that still has an operation in progress, so it cannot report success or
auto-merge an unfinished merge.

The `.codegraph` snapshot copy is hardened too: the DB is built in runner-owned
`WORKTREE_ROOT/<key>/.meta`, and the copy/rename is anchored to an `O_DIRECTORY|O_NOFOLLOW`
descriptor of the destination (`.gitignore` uses `O_EXCL|O_NOFOLLOW`), so a planted symlink or
a path swap during the copy cannot redirect the write. A planted `codegraph.db` link is
replaced, not followed.
Off macOS, a non-confidential project keeps the old unsandboxed fallback; a confidential
project still returns writable roots, so the missing Seatbelt fails closed instead of running
an unconfined filter/hook.

The canonical git common dir is resolved from the trusted main checkout (`git_common_dir`),
pinned in runner-owned `WORKTREE_ROOT/<key>/.meta/project.json` at the first grant, and never
accepted from the agent-writable ticket worktree. A later live value that disagrees with the
pin is refused, so a `commondir`/`.git` redirect cannot widen a grant. The binding also records
it, and `load_binding` refuses a worktree whose absolute git dir is no longer under that pinned
directory. The manual `commit_checkout` grant also comes from this pin. The pin's
lookup/compare/publish runs under a thread lock plus `state_io.file_lock` and is written with
`write_json_atomic`, so the dashboard and CLI cannot race on a fixed temp name. The operation
check gives rebase/sequencer state precedence over `MERGE_HEAD`, because
`rebase --rebase-merges` can have both.

Runner-owned git sets `GIT_NO_LAZY_FETCH=1` and the binding `cat-file` plus the post-run
`rev-list` run under `read_git_confine`, so a repo-configured promisor remote cannot make a
missing object trigger `core.sshCommand`. `GitConfine` also carries the profile policy:
non-confidential git keeps the write-only profile (network open for a downloading smudge/clean
filter); confidential git keeps the hostile profile (network closed).


## Non-goals

- Interactive/native dsh sessions launched outside project dispatch (their cwd is not the
  ticket worktree and they have no post-run commit path).
- Linux/bwrap enforcement: the workspace wrapper is the macOS Seatbelt path. Non-macOS keeps
  the AGE-138 behaviour.
- Letting Codex or dsh bypass the sandbox, or changing confidential dsh's network posture.
- Removing the runner's leftover commit.

## Assumptions

- A linked worktree's git metadata is wholly under `--git-common-dir`; granting that subtree is
  enough for `add`, `commit`, ref updates and reflogs.
- `dsh --patch` continues to accept a single `sandbox` entry overlay and the `!!js` runner
  command in the installed version.
- The runner process is unsandboxed, so its `--dump-config` preflight can write the profile.

## Acceptance Criteria

- [ ] A non-confidential dsh project run launches with `--patch <dsh-workspace.yml>` and has
      `AGENTICOS_DSH_CONFINE_RUNNER` and `AGENTICOS_DSH_CONFINE_GIT` set.
- [ ] Its composed `sandbox` entry names the runner and `dsh-confine:`, checked before launch.
- [ ] The workspace profile denies writes outside the worktree, temp roots and git common dir.
- [ ] The workspace profile does not deny network or app-service lookups.
- [ ] A read-only dsh call under `workspace` grants no writable roots.
- [ ] Confidential dsh keeps its network/app-service denials and `/tmp` TMPDIR.
- [ ] The dsh project prompt asks for a commit and no longer says to leave it to the runner.
- [ ] The dsh prompt requires a real `git merge` for a merge task and forbids tree-copy/clone
      workarounds.
- [ ] A repo with no configured identity gets the runner's fallback commit identity in dsh's env.
- [ ] The Codex prompt still leaves the commit to the runner.
- [ ] `post_run` still commits leftover changes for every agent.
- [ ] Non-macOS keeps the leave-it-to-the-runner prompt and native prefix.
- [ ] `py_compile` passes for `runner/*.py`.
- [ ] The focused dsh/dispatch tests pass, or the only failures reproduce on the pre-build
      commit in this sandbox.

- [ ] Runner staging/commit and merge are write-confined for a non-confidential project.
- [ ] A configured clean filter that writes outside the worktree/git dir cannot escape.
- [ ] A non-confidential dsh session continuation keeps the native prefix and no git grant.
- [ ] The dsh workspace overlay is selected only for ticket dispatch.
- [ ] Read-only git consumers are write-confined for non-confidential projects on macOS.
- [ ] Ticket worktree creation is write-confined on macOS, so a smudge filter cannot escape.
- [ ] Non-confidential non-macOS keeps the old unsandboxed read/commit fallback (no
      `sandbox-exec`); confidential fails closed instead.
- [ ] A planted CodeGraph DB/`.gitignore` symlink is replaced or skipped, never followed.
- [ ] A redirected worktree git dir is refused by `load_binding`.
- [ ] A rebase/sequencer state is refused even when `MERGE_HEAD` is also present.

## Verification

- [ ] `.venv/bin/python3 -m py_compile runner/*.py` exits 0.
- [ ] `.venv/bin/python3 -m pytest tests/test_dsh_confidential.py tests/test_project_dispatch.py -q`
      passes.
- [ ] Any `sandbox-exec`/PTY failure in that run is compared with the pre-build commit.
- [ ] A non-macOS simulation (`sys.platform != "darwin"`) returns `None` from both helpers.
- [ ] A unit check prints `dsh_confine.build_argv` for `workspace` and asserts the profile has
      no `(deny network*)`, contains the git-dir subpath, and contains the worktree subpath.
- [ ] A unit check prints `dsh_confine.build_argv` for a read-only workspace call and asserts no
      writable roots are granted.
- [x] `docs/references/dsh-commit-failures.md` records the recent sessions, signatures and
      remaining edge cases.
- [x] `git diff --check` exits 0.

## Risks

- The preflight composes the profile on every non-confidential dsh launch; a broken user patch
  now fails before the run with a clear message instead of a denied commit.
- Replacing the native sandbox with the runner wrapper changes the enforcement implementation,
  not its write boundary; the profile is derived from dsh's own bwrap arguments.
- A repository hook can still fail a dsh commit by writing outside the granted roots; the
  runner's post-run commit (`--no-verify`) remains the net.
- A live `git commit` cannot be exercised from inside this dsh session (nested
  `sandbox-exec` is denied); the runner-side launch is the first live check after restart.
- The live runner must be restarted after this merges; otherwise queued/running sessions keep
  the old prompt and the old overlay, and the failure looks unchanged (the AGE-138 restart
  gap is why AGE-140 still asked for a commit).
- Native dsh sessions in a linked worktree still have no overlay; only project dispatch does.
- A failing hook/signature, a stale lock left by a killed `git`, or an agent that ignores the
  merge guidance remains outside the runner's control; the `post_run` commit is the net.
- The nested-sandbox probe costs one cached `sandbox-exec` call per process; the marker is
  cleared at runner startup, so only the dsh wrapper's child carries it.

## Progress Checklist

- [x] Add `write_only` to `projects.sandbox_profile`.
- [x] Add `write_only` pass-through to `projects.sandbox_prefix`.
- [x] Add the optional mode token to `dsh_confine.build_argv`, defaulting to `confidential`.
- [x] Build the `workspace` profile with the worktree, temp roots and git common dir.
- [x] Keep the ambient TMPDIR for `workspace` and `/tmp` for `confidential`.
- [x] Add `runner/scripts/dsh-workspace.yml` with the pinned runner command.
- [x] Add `dsh_cli.workspace_cli_prefix`.
- [x] Add `dsh_cli.workspace_problem`.
- [x] Add `dsh_cli.verify_workspace_launch` and refuse an unapplied or replaced runner.
- [x] Add the workspace-prefix parameter to `project_runs.agent_cli`.
- [x] Select the workspace prefix in `app._project_cmd` by ticket dispatch.
- [x] Set the runner/git env for non-confidential dsh in `app._project_exec_env`.
- [x] Pass `ticket_dispatch=False` from the native session continuation.
- [x] Add the macOS-gated `read_git_confine` helper.
- [x] Add the macOS-gated `write_git_confine` helper.
- [x] Use `read_git_confine` in `uncommitted`.
- [x] Use `read_git_confine` in `fingerprint_parts`.
- [x] Use `read_git_confine` in `_browse_root`.
- [x] Use `read_git_confine` in `_ignored_by_committed_rule`.
- [x] Use `write_git_confine` in `runner_commit` staging and commit.
- [x] Use `write_git_confine` in `merge_into_checkout` merge-tree and merge.
- [x] Use `write_git_confine` in `create_worktree`.
- [x] Keep `None` on non-macOS so the fallback commit does not need `sandbox-exec`.
- [x] Add a regression test for a clean filter run by status/uncommitted.
- [x] Add a regression test for a clean filter run by the fingerprint.
- [x] Add a regression test for a smudge filter run by a second worktree creation.
- [x] Add a unit test that `runner_commit` passes a non-None confine for a non-confidential project.
- [x] Change `leaves_commit_to_runner` to let dsh commit on macOS.
- [x] Change the dsh project prompt to ask for a commit.
- [x] Add the merge-task guidance to the dsh project prompt.
- [x] Export the fallback commit identity to the non-confidential dsh env.
- [x] Require both a valid marker and a refused nested-sandbox probe for the bypass.
- [x] Clear an inherited marker at runner startup.
- [x] Refuse an unresolved/non-merge operation in `runner_commit` without staging.
- [x] Finish a fully resolved merge as a two-parent commit.
- [x] Refuse an empty pending merge in `runner_commit`.
- [x] Refuse a clean unfinished operation in `post_run` before and after verify.
- [x] Add the session/edge-case evidence to `docs/references/dsh-commit-failures.md`.
- [x] Remove `dsh_cli.confidential_prompt`.
- [x] Remove the `dsh_cli.confidential_prompt` call from `app.py`.
- [x] Update `tests/test_dsh_confidential.py` for the removed helper.
- [x] Update `tests/test_project_dispatch.py` for the dsh prompt and prefix.
- [x] Add workspace-profile and read-only coverage in `tests/test_dsh_confidential.py`.
- [x] Add workspace-prefix and env coverage in `tests/test_project_dispatch.py`.
- [x] Run `python3 -m py_compile runner/*.py` (no `.venv` in this worktree).
- [x] Run the focused dsh/dispatch pytest file set with `AGENTICOS_DSH_SANDBOX=workspace`
      (simulates the new wrapper): 147 passed, 1 pre-existing Codex-shim failure.
- [x] Run `git diff --check`.
- [x] Update `docs/context-maintenance.md`.
- [x] Update the dsh note in `AGENTS.md`.
- [x] Add a regression test for the marker/probe bypass.
- [x] Add a regression test for an unresolved merge.
- [x] Add a regression test for a fully resolved merge with both parents.
- [x] Add a regression test for an empty pending merge.
- [x] Add a regression test for a clean pending merge left by verify.
- [x] Trust the workspace-parent shortcut only for non-confidential git.
- [x] Add the sequencer directory to `_git_operation`.
- [x] Move filter probes outside the granted temp roots and prove the filter ran.
- [x] Build the CodeGraph snapshot in a temp file and replace the destination atomically.
- [x] Keep confidential fail-closed off macOS; only non-confidential keeps the fallback.
- [x] Add a planted CodeGraph symlink regression test.
- [x] Add a non-macOS confidential fail-closed assertion.
- [x] Prove the preview filter ran with a failing filter instead of a sentinel write.
- [x] Resolve the common dir from the trusted main checkout and pin it in the binding.
- [x] Refuse a worktree whose absolute git dir moved outside the pin.
- [x] Give rebase/sequencer state precedence over `MERGE_HEAD`.
- [x] Set `filter.spy.required` so the preview test's failing filter really fails.
- [x] Add redirected-gitdir, rebase-precedence and rebase-with-merge-head tests.
- [x] Pin the project common dir in runner-owned `.meta/project.json` and refuse live redirects.
- [x] Build the CodeGraph DB in `.meta` and rename with `dst_dir_fd`/`O_NOFOLLOW`.
- [x] Add a path-swap test for the descriptor-anchored CodeGraph copy.
- [x] Build the manual-commit grant from `git_common_dir`, not a fresh `rev-parse`.
- [x] Make the pin read/compare/publish cross-process safe (`file_lock` + `write_json_atomic`).
- [x] Add manual-commit redirect and threaded-pin tests.
- [x] Set `GIT_NO_LAZY_FETCH=1` and confine the binding `cat-file` / post-run `rev-list`.
- [x] Keep network open for non-confidential git with `GitConfine(write_only=...)`.
- [x] Add lazy-fetch and non-confidential-network tests.
- [ ] Copy seeds through descriptor-anchored traversal or a write-confined worker
      — BLOCKED: residual inspection finding I12-002 (a smudge-filter detached child can swap
      a seed destination before `shutil` copies); not in this change.
- [ ] Restart the live runner after this merges (`launchctl kickstart -k gui/$(id -u)/com.agenticos.runner`).
- [ ] Dispatch one fresh ticket and confirm the new prompt + overlay are live.
- [ ] Have Codex inspect the final diff against the pre-build commit (last verdict REVISE on
      the residual I12-002).
