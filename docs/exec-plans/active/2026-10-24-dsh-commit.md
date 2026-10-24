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
- [ ] Non-macOS keeps the old unsandboxed read/commit fallback (no `sandbox-exec`).

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
- [ ] `git diff --check` exits 0.

## Risks

- The preflight composes the profile on every non-confidential dsh launch; a broken user patch
  now fails before the run with a clear message instead of a denied commit.
- Replacing the native sandbox with the runner wrapper changes the enforcement implementation,
  not its write boundary; the profile is derived from dsh's own bwrap arguments.
- A repository hook can still fail a dsh commit by writing outside the granted roots; the
  runner's post-run commit (`--no-verify`) remains the net.
- A live `git commit` cannot be exercised from inside this dsh session (nested
  `sandbox-exec` is denied); the runner-side launch is the first live check after restart.

## Progress Checklist

- [ ] Add `write_only` to `projects.sandbox_profile`.
- [ ] Add `write_only` pass-through to `projects.sandbox_prefix`.
- [ ] Add the optional mode token to `dsh_confine.build_argv`, defaulting to `confidential`.
- [ ] Build the `workspace` profile with the worktree, temp roots and git common dir.
- [ ] Keep the ambient TMPDIR for `workspace` and `/tmp` for `confidential`.
- [ ] Add `runner/scripts/dsh-workspace.yml` with the pinned runner command.
- [ ] Add `dsh_cli.workspace_cli_prefix`.
- [ ] Add `dsh_cli.workspace_problem`.
- [ ] Add `dsh_cli.verify_workspace_launch` and refuse an unapplied or replaced runner.
- [ ] Add the workspace-prefix parameter to `project_runs.agent_cli`.
- [ ] Select the workspace prefix in `app._project_cmd` by ticket dispatch.
- [ ] Set the runner/git env for non-confidential dsh in `app._project_exec_env`.
- [ ] Pass `ticket_dispatch=False` from the native session continuation.
- [ ] Add the macOS-gated `read_git_confine` helper.
- [ ] Add the macOS-gated `write_git_confine` helper.
- [ ] Use `read_git_confine` in `uncommitted`.
- [ ] Use `read_git_confine` in `fingerprint_parts`.
- [ ] Use `read_git_confine` in `_browse_root`.
- [ ] Use `read_git_confine` in `_ignored_by_committed_rule`.
- [ ] Use `write_git_confine` in `runner_commit` staging and commit.
- [ ] Use `write_git_confine` in `merge_into_checkout` merge-tree and merge.
- [ ] Use `write_git_confine` in `create_worktree`.
- [ ] Keep `None` on non-macOS so the fallback commit does not need `sandbox-exec`.
- [ ] Add a regression test for a clean filter run by status/uncommitted.
- [ ] Add a regression test for a clean filter run by the fingerprint.
- [ ] Add a regression test for a smudge filter run by a second worktree creation.
- [ ] Add a unit test that `runner_commit` passes a non-None confine for a non-confidential project.
- [ ] Change `leaves_commit_to_runner` to let dsh commit on macOS.
- [ ] Change the dsh project prompt to ask for a commit.
- [ ] Remove `dsh_cli.confidential_prompt`.
- [ ] Remove the `dsh_cli.confidential_prompt` call from `app.py`.
- [ ] Update `tests/test_dsh_confidential.py` for the removed helper.
- [ ] Update `tests/test_project_dispatch.py` for the dsh prompt and prefix.
- [ ] Add workspace-profile and read-only coverage in `tests/test_dsh_confidential.py`.
- [ ] Add workspace-prefix and env coverage in `tests/test_project_dispatch.py`.
- [ ] Run `.venv/bin/python3 -m py_compile runner/*.py`.
- [ ] Run the focused dsh/dispatch pytest file set.
- [ ] Run `git diff --check`.
- [ ] Update `docs/context-maintenance.md`.
- [ ] Update the dsh note in `AGENTS.md`.
- [ ] Have Codex inspect the final diff against the pre-build commit.
