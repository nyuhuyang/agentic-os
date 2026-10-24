# AGE-146 review log

Append-only transcript. Host/planner/builder: `deepseek` (dsh session). Plan reviewer: `codex`.
Code inspector: `codex`. Rounds: 20 plan reviews, 20 fix attempts, 20 inspections. Inspection
on. A DeepSeek host has no automatic same-provider fallback; an unavailable Codex is reported.

- Plan: `docs/exec-plans/active/2026-10-24-dsh-commit.md`
- Log: `docs/exec-plans/active/2026-10-24-dsh-commit.review-log.md`
- Pre-build commit: `bd7b540`
- Research: none (repository recon only)
- Authorization: AGE-146 asks to solve the dsh commit failure; implementation is authorized.
  Commits stay uncommitted for the runner per the project prompt.

## Round 1 — plan author

Scope: non-confidential project dsh runs get a workspace-mode Seatbelt overlay that adds the
worktree's git common dir; dsh is asked to commit; the runner keeps its leftover commit as a
net. Confidential dsh and Codex are unchanged.

### Round 1 result (Codex, cross_provider) — BLOCKED

Verdict BLOCKED. Finding PLAN-001 (low): actionable Approach steps were not individual
checkboxes and the progress list bundled prompt/removal work. Disposition: accepted; the
Approach list became design prose and the progress list was split into one-deliverable items.
Limitation: Codex could not read repository files because its nested read-only `sandbox-exec`
is refused inside this dsh session; the verdict covered the plan text only.

Environment workaround (not a code change): Codex fails to initialize with an unwritable
`~/.codex` under this dsh workspace sandbox. Reviews run with a private 0600 copy of
`~/.codex/{auth.json,config.toml}` under `/private/tmp`, and with
`runner/scripts/sandboxed-bin/codex` first on PATH so Codex's nested read-only Seatbelt becomes
the existing AGE-129 bypass. The runner still refuses a repository-mutating review; the
reviewer's read-only guarantee is enforced by the dsh workspace sandbox plus that audit, not by
Codex's inner sandbox. The temp home is deleted at the end of the ticket.

### Round 2 (Codex, cross_provider) — REVISE

- `AGE146-R1` (high, `runner/projects.py:1219`): granting dsh the shared git dir lets it write
  `.git/config`; `post_run`'s unsandboxed `git add -A` can then run a configured clean filter
  outside the agent sandbox. Disposition: accepted. `runner_commit` and
  `merge_into_checkout` will be write-confined for every project (common dir + worktree),
  matching `commit_checkout`; read-only status/fingerprint consumers are documented as not
  executing config commands, and a clean-filter regression test is added.
- `AGE146-R2` (medium, `runner/app.py:5269`): the shared `_project_cmd`/`_project_exec_env`
  also serve native session continuations, which would gain the overlay without `post_run`.
  Disposition: accepted. The overlay is gated by an explicit ticket-dispatch flag; the session
  caller passes false.
- `AGE146-R3` (low, plan checklist): independent substeps lacked their own checkbox.
  Disposition: accepted; the progress, acceptance and verification lists were split.

Coverage: Codex read the plan, the dsh prefix/env/wrapper/overlay, sandbox profiles, ticket
dispatch, session continuations, PTY callers, runner commit/merge and shared config consumers.

### Round 3 (Codex, cross_provider) — REVISE

- `AGE146-R1` (high, reopened): `git status`/working-tree `git diff` can run clean filters;
  `uncommitted` runs before staging and was unsandboxed for non-confidential projects, and the
  fingerprint/browse consumers were exposed too. Disposition: accepted. The plan now adds
  `read_git_confine()` (no writable roots, temp only) for `uncommitted`, `fingerprint_parts`,
  the browser's status/ls-files and `_ignored_by_committed_rule`, and keeps
  `write_git_confine(project, *paths)` for staging/commit/merge. Regression coverage covers a
  status-invoked filter and a fingerprint-invoked filter.
- `AGE146-R4` (medium, plan line 67): applying Seatbelt unconditionally would break the
  non-macOS fallback commit. Disposition: accepted. Both helpers return `None` off macOS,
  preserving AGE-138 there; a platform-simulation check is in verification.

Coverage: Codex re-read the plan and traced status/fingerprint/browse consumers, the fallback
staging/commit path and the platform-specific sandbox selection.

### Round 4 (Codex, cross_provider) — REVISE

- `AGE146-R5` (high, `runner/projects.py:1183`): `create_worktree` runs `git worktree add`
  unsandboxed for non-confidential projects; checkout runs smudge filters, which the new
  shared-config grant lets dsh plant. Disposition: accepted. `create_worktree` uses
  `write_git_confine(project, wt)`, and a second-worktree smudge-filter regression is added.
- `AGE146-R6` (low, plan checklist): `_browse_root` and `_ignored_by_committed_rule` shared a
  checkbox. Disposition: accepted; split.

Coverage: Codex traced worktree creation/reuse, smudge filters, shared config and attributes,
and the remaining confined consumers.

### Round 5 (Codex, cross_provider) — REVISE

- `AGE146-R7` (high, `runner/projects.py:267`): `AGENTICOS_DSH_SANDBOX` alone disabled
  confinement. Disposition: accepted. The bypass now needs a valid
  `confidential|workspace` marker **and** a refused `/usr/bin/sandbox-exec` probe; the runner
  clears an inherited marker in `main()`; a spoofed/unknown value is ignored; tests cover it.
- `AGE146-R8` (high, `runner/projects.py:1274`): `runner_commit` could stage across an
  unresolved merge, and a clean `MERGE_HEAD` could be reported as success/auto-merged.
  Disposition: accepted. `runner_commit` refuses unresolved conflicts, rebase/cherry-pick/
  revert and empty pending merges without touching the index; a fully resolved merge is
  committed with both parents. `post_run` refuses a clean but unfinished operation. Tests
  cover unresolved/resolved/empty merges; the evidence doc was corrected.
- `AGE146-R9` (low, plan): restart/verification had no checkbox. Disposition: accepted; a
  restart step and a fresh-ticket live check were added.

### Round 6 (Codex, cross_provider) — REVISE

- `AGE146-R7` (reopened, high): either marker mode skipped confidential confinement, so a
  workspace parent could run a confidential verify with network open. Disposition: accepted.
  `already_confined("confidential")` now requires a `confidential` parent; `confine_for` and
  confidential `run_verify` use it. A workspace parent attempts the inner sandbox and fails
  closed. Tests cover the policy split and a confidential project under a workspace parent.
- `AGE146-R8` (reopened, medium): verify can leave a clean `MERGE_HEAD` after the pre-verify
  check. Disposition: accepted. `post_run` rechecks the operation after verify; a regression
  test has a passing verify leave an empty pending merge and asserts `post_run_error` + `error`.
- `AGE146-R10` (low, plan): combined regression checkboxes. Disposition: accepted; split into
  marker/probe, unresolved, resolved, empty and post-verify cases.

Validation: `tests/test_projects.py` 90 passed / 3 failed; `test_dsh_confidential.py` +
`test_project_dispatch.py` 139 passed / 10 failed. The failures are the confidential
nested-`sandbox-exec` class (HEAD has 11 in the dispatch file) and the Codex shim; the
non-confidential tests and every new AGE-146 regression pass. The host/runner, which is
unsandboxed, is the first place the nested confidential profile can actually run.

### Round 7 / inspection 1 (Codex, cross_provider) — REVISE

- `AGE146-I01` (high, `runner/projects.py:291`): the child-controlled marker could be forged as
  `confidential`, and a workspace parent could skip a confidential verify. Disposition:
  accepted. The marker is now trusted **only** for non-confidential workspace git. Confidential
  `read_git_confine`, `write_git_confine`, `confine_for`, `run_verify` and the manual commit
  always attempt the inner profile and fail closed. A `confidential` marker value is ignored.
- `AGE146-I02` (medium, `runner/projects.py:1533`): a multi-commit cherry-pick/revert can leave
  `sequencer/` after `CHERRY_PICK_HEAD` is cleared. Disposition: accepted; `_git_operation`
  checks `sequencer` and returns "a cherry-pick/revert sequence"; a test covers it.
- `AGE146-I03` (medium, `tests/test_projects.py:537`): filter probes were under the granted
  temp root and broad errors could pass. Disposition: accepted. The outside marker is in
  `$HOME`, the filter writes an in-repo sentinel to prove it ran, sandbox-init failures skip
  (not pass), and the preview test in `test_session_commit.py` does the same.

Final focused validation (this dsh session, `AGENTICOS_DSH_SANDBOX=workspace`):
`tests/test_dsh_confidential.py` 48 passed; `tests/test_projects.py` 88 passed / 3 failed / 3
skipped; `tests/test_project_dispatch.py` 90 passed / 11 failed. Every failure is the
confidential nested-`sandbox-exec` class (the dispatch file's 11 reproduce on HEAD) or the
Codex shim; every AGE-146 regression passes. `py_compile` and `git diff --check` pass.

### Round 8 / inspection 2 (Codex, cross_provider) — REVISE

- `AGE146-REVIEW-01` (high, `runner/projects.py:1277`): a smudge filter could plant
  `.codegraph/codegraph.db` as a symlink and `_copy_codegraph` followed it. Disposition:
  accepted. The snapshot is built in a fresh temp DB and `os.replace`d onto the destination
  (which replaces a link itself); a planted `codegraph.db` link is unlinked, and `.gitignore`
  is created with `O_EXCL|O_NOFOLLOW`. A regression test plants both links and asserts the
  external targets are untouched.
- `AGE146-REVIEW-02` (high, `runner/projects.py:318`): off macOS both helpers returned `None`
  before checking confidentiality, so confidential git could run unconfined. Disposition:
  accepted. Only non-confidential gets the off-macOS fallback; confidential returns roots and
  the missing Seatbelt fails closed. Tests cover both.
- `AGE146-REVIEW-03` (medium, `tests/test_session_commit.py:250`): the preview test's sentinel
  could not be written under the no-write profile. Disposition: accepted. The filter now exits
  nonzero after trying the outside write; the test asserts the failure proves the filter ran
  and that the outside marker is absent, and skips only when nested sandbox-exec is unavailable.

Focused validation after these fixes: `tests/test_projects.py` 88 passed / 3 failed / 3 skipped;
`tests/test_dsh_confidential.py` 48 passed; `tests/test_project_dispatch.py` 90 passed / 11
failed; the same confidential/nested-sandbox class. `py_compile` and `git diff --check` pass.

### Round 9 / inspection 3 (Codex, cross_provider) — REVISE

- `AGE146-I09-001` (high, `runner/projects.py:336`): the agent-writable worktree `.git`/
  `commondir` could redirect a later grant to another repository. Disposition: accepted. The
  common dir is resolved from the trusted main checkout (`git_common_dir`), written into the
  binding, and `load_binding` refuses a worktree whose `--absolute-git-dir` is outside it.
  Tests cover a redirected `.git` file.
- `AGE146-I09-002` (medium, `runner/projects.py:1562`): `MERGE_HEAD` outranked rebase state, so
  `rebase --rebase-merges` could be committed as a merge. Disposition: accepted; rebase/
  sequencer checks now run first. Tests cover a simultaneous `rebase-merge` + `MERGE_HEAD`.
- `AGE146-I09-003` (medium, `tests/test_session_commit.py:236`): a non-required failing clean
  filter can pass through. Disposition: accepted; the preview test sets
  `filter.spy.required=true` after setup, so the filter failure is observable.

Focused validation after these fixes: `test_projects.py` 3 nested/confidential failures + 3
skips; `test_dsh_confidential.py` 48 passed; `test_project_dispatch.py` the same 11
confidential/Codex-shim failures. `py_compile` and `git diff --check` pass.

### Round 10 / inspection 4 (Codex, cross_provider) — REVISE

- `AGE146-I10-001` (high, `runner/projects.py:250`): a writable `commondir` in the main `.git`
  could redirect every later grant. Disposition: accepted. `git_common_dir` pins the canonical
  value in runner-owned `WORKTREE_ROOT/<key>/.meta/project.json` at the first grant; a live
  value that disagrees with the pin is refused. A registry path change re-pins; a worktree
  binding for another path is ignored. Tests cover the redirect and binding pin.
- `AGE146-I10-002` (high, `runner/projects.py:1175`): the CodeGraph temp file was reopened by
  path and could be swapped. Disposition: accepted. The DB is built in runner-owned `.meta`,
  and the final rename/`.gitignore` use an `O_DIRECTORY|O_NOFOLLOW` destination descriptor
  (`O_EXCL|O_NOFOLLOW` for `.gitignore`). A path-swap regression test proves the write stays
  in the opened directory.

Final focused run: `test_projects.py` + `test_project_dispatch.py` = 184 passed / 14 failed /
3 skipped. The 14 failures are the confidential nested-`sandbox-exec` class and the Codex shim
(the same class as HEAD's 11 in the dispatch file); every AGE-146 regression passes.

### Round 11 / inspection 5 (Codex, cross_provider) — REVISE

- `AGE146-F01` (high, `runner/projects.py:1569`): the manual `commit_checkout` path re-read
  `--git-common-dir` and bypassed the pin. Disposition: accepted; it now grants
  `git_common_dir(project)`. A redirected main `.git/commondir` makes the manual Commit refuse
  before staging; a test covers it.
- `AGE146-F02` (medium, `runner/projects.py:280`): the pin's thread lock did not cover the
  dashboard and `projects.py` CLI, and the fixed `project.tmp` name raced. Disposition:
  accepted; the lookup/compare/publish now uses the existing `state_io.file_lock` plus
  `write_json_atomic` (unique temp), with a threaded regression test.

Final focused run: 186 passed / 14 failed / 3 skipped; the 14 are the confidential nested-
`sandbox-exec` class and the Codex shim. `py_compile` and `git diff --check` pass.

### Round 12 / inspection 6 (Codex, cross_provider) — REVISE

- `AGE146-I12-001` (high, `runner/projects.py:1300`): `cat-file -e` / `rev-list` could lazy-fetch
  a missing base object through a repo-configured promisor remote and run `core.sshCommand`.
  Disposition: fixed. `_git`/`_git_bytes`/browser git set `GIT_NO_LAZY_FETCH=1`; the binding
  `cat-file` and the post-run `rev-list` run under `read_git_confine`. A test asserts the env.
- `AGE146-I12-003` (medium, `runner/projects.py:1371`): runner git used the hostile profile for
  non-confidential projects, so a network-dependent smudge/clean filter could no longer
  download. Disposition: fixed. `GitConfine` carries a `write_only` policy: non-confidential
  git uses the write-only profile (network open); confidential keeps the hostile one. A test
  checks the profile strings.
- `AGE146-I12-002` (high, `runner/projects.py:1189`): a smudge-filter detached child can still
  swap a seed destination between `_check_seed_destinations` and `shutil.copy2`/`copytree`,
  which run unsandboxed. **Not fixed in this change.** Follow-up: copy seeds through
  descriptor-anchored traversal (`O_NOFOLLOW`/`O_EXCL` per component) or a write-confined
  worker, with a path-swap regression test. Recorded as a residual risk.

Inspection verdict remains **REVISE** because of the residual I12-002; the commit feature and
the other findings are implemented and tested. Final focused run after the I12-001/003 fixes is
recorded below.
