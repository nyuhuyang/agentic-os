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
