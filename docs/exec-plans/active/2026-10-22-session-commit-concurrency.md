---
status: in-progress
created: 2026-10-22
---

# AGE-124: Session Commit — per-project opt-out, and merge while other sessions run

## Goal

Two user complaints about the Projects panel's per-session **Commit** button (screenshot 2026-10-22 03:17):

1. `knowledge_base` is notes, not code; its rows should have no Commit button. The two Shiny apps keep theirs.
2. Commit & merge from a worktree session row is refused with
   "another run of this project is in progress; merge after it finishes" whenever any other session
   of the project is running. A merge into `main` does not touch the other run's `agent/<id>` branch,
   so this forces one session at a time.

## Background (from the code)

- Commit on a row = `projects.commit_checkout`: stage **every** change in that session's checkout
  and commit locally (never pushed). Rows on `master`/`main` share one checkout, so any of them commits
  the same files. A worktree row (`agent/<id>`) commits there, then `_manual_merge` merges the branch
  into the main checkout.
- Why the refusal exists: each project-bound run (`_run_project_ticket`, app.py ~3278) fingerprints the
  main checkout before the agent starts and again after (`project_runs.closing_check`). Any change
  between the two — including a merge the user asked for — marks that run "main checkout changed".
  `_manual_merge` therefore refuses while any run of the project is before its closing fingerprint
  (`_project_runs_open`, app.py ~3483).
- A plain commit in the main checkout (master rows) is not guarded at all today, so it already flags
  every open run "main checkout changed" (false alarm).

## Approach

### A. Re-base open runs' fingerprints, one component at a time

- `projects.fingerprint` is split: `fingerprint_parts(project, exclude) -> dict` of component hashes and
  `fingerprint_of(parts) -> str`; `fingerprint()` = `fingerprint_of(fingerprint_parts(...))`, so every existing
  caller and test keeps its meaning. Components: `head` (HEAD sha), `branch` (symbolic-ref), `refs` (shared refs
  minus `agent/*`, remotes and the checked-out branch's own ref, which `head` covers), `tracked` (tracked path
  names), `flags` (only the `ls-files -v` entries whose tag is not `H`: skip-worktree / assume-unchanged bits,
  AGE124-R06), `staged`, `unstaged`, `untracked` (untracked/ignored stat list), `config`, `hooks`.
- Each project-bound run keeps its baseline parts in a private map `_RUN_BASELINES[run_id] = {key, project,
  exclude, parts}` (never in the job dict: `/api/runs` serialises jobs, AGE124-R01). Written under the
  checkout's `_merge_gate` with the opening fingerprint; insert/pop also under `_JOB_LOCK`.
- The closing check runs under the gate: pop the entry, compare `fingerprint(now)` with `fingerprint_of(parts)`.
  `post_run` gets an optional `closing` callable (default: today's `closing_check`); the cancelled path uses the
  same callable. After the pop the run no longer takes part in re-basing.
- `_rebase_bound_runs(project, op)` context manager (caller holds the gate), `op` in
  `{"merge", "commit"}` with sanctioned components `merge = {head, tracked}`,
  `commit = {head, tracked, staged, unstaged, untracked}`. For every baseline of the same checkout:
  - read `pre` parts before the operation;
  - if `pre != base` (the checkout already changed since the run opened), mark the entry `changed` (sticky): the
    closing check then reports changed whatever the later state, so a commit that resets a component cannot
    launder an earlier change (AGE124-R05);
  - after the operation succeeds read `post`; if any non-sanctioned component differs between `pre` and `post`
    (an agent wrote a hook, a flag bit or an untracked file meanwhile), mark it `changed`; otherwise `base = post`;
  - an exception in the operation re-bases nothing (the closing check then sees the difference); a fingerprint
    error marks that entry `changed` (fail closed).
- Closing check: `changed = entry["changed"] or fingerprint(now) != fingerprint_of(entry["parts"])`.
- `_manual_merge`: project-bound runs (`project_key` in the checkout's keys) no longer block; the merge runs inside
  `_rebase_bound_runs(project, "merge")`. Still refused: an agent working in the main checkout itself
  (`session_project` continuation, retiring/launching jobs, runner-root jobs), a running baseline test, an
  interactive tab in the main checkout.
- Main-checkout commit (master rows): `commit_checkout` gets an optional `main_guard` context factory, entered
  only for a real (non-dry-run) main-checkout commit, before `_MERGE_LOCK`; the app passes gate +
  `_rebase_bound_runs(project, "commit")`. Lock order stays ticket -> gate -> `_MERGE_LOCK`.
- Policy (AGE124-R03): a commit only stops being blamed on runs whose main checkout was unchanged since they opened.
  Edits made in the main checkout after a run opened still flag that run, as today: the fingerprint cannot tell a
  user's edit from an agent's.
- Out of scope: the background auto-merge queue (`_merge_when_last`) still waits for the project's other runs.

### B. Per-project `commit` flag (default true)

- `projects.yaml` gains optional `commit: false` (registry `_FIELDS`, `Project.commit`, parser, example yaml).
- `/api/projects` returns `commit`; commit state is not computed for such projects.
- `POST .../sessions/<agent>/<sid>/commit` returns 400 "Commit is off for this project" when `commit` is false.
- `set_confidential` becomes `set_flags(key, {confidential?, commit?}, hash)`; the PATCH endpoint passes both.
- Dashboard: rows of a `commit: false` project show no Commit button; the project form gets a checkbox
  "Commit button on session rows" (add and edit; add stores `commit: false` only when unchecked).
- The user turns it off for `knowledge_base` in the Edit dialog (`projects.yaml` is outside this worktree).

## Non-goals

- No change to what Commit includes (whole checkout; git cannot attribute edits to a session).
- No push, no auto-merge queue change, no run status set change.

## Assumptions and risks

- Decision made without the user (non-interactive session): an additive optional registry field. Additive and
  default-preserving, so existing `projects.yaml` files stay valid.
- Holding the gate during the closing fingerprint can delay another run's opening fingerprint by one fingerprint
  duration (seconds on large ignored dirs). Acceptable.
- Residual (main-checkout commit): a file an agent writes into the main checkout during the commit's few hundred
  milliseconds is staged by `git add -A` and absorbed. Accepted; the commit preview already lists the files.
- A merge that adds a tracked file inside a wholly ignored directory changes `untracked`, so that run is not
  re-based and is flagged (false alarm, fail closed). Accepted.
- Risk: a run that legitimately reads main-checkout source files via `{root}` in verify could see a merge land
  mid-verify. Verify is documented for tools only (`{root}/.venv/bin/python`); accepted.

## Acceptance Criteria

- [ ] A worktree row's Commit & merge succeeds while another project-bound run of the same project is open.
- [ ] That other run does not report "main checkout changed" because of the merge.
- [ ] A run whose main checkout already changed before the merge still reports "main checkout changed".
- [ ] A change outside the sanctioned components made during the merge still flags the run.
- [ ] A merge is still refused while an agent works in the main checkout itself.
- [ ] A main-checkout commit does not flag an open bound run whose main checkout was unchanged since it opened.
- [ ] `/api/runs?state=running` and `/api/runs/<id>` stay JSON-serialisable while a bound run is open.
- [ ] A project with `commit: false` shows no Commit button and its commit endpoint returns 400.
- [ ] The project form toggles `commit` for add and edit.
- [ ] Turning Commit off while a row's Commit editor is open removes that editor and its button.

## Verification

- [ ] `.venv/bin/python3 -m py_compile runner/*.py` passes.
- [ ] Test: `fingerprint()` equals `fingerprint_of(fingerprint_parts())`.
- [ ] Test: manual merge with an open bound run merges and the run's closing check reports unchanged.
- [ ] Test: a bound run whose `unstaged` part already differed is still flagged after the merge.
- [ ] Test: a hook written between pre and post of a merge leaves the run flagged.
- [ ] Test: skip-worktree set on an unrelated file plus an edit during a merge leaves the run flagged.
- [ ] Test: an edit made in the main checkout after a run opened, then a main-checkout commit, leaves the run flagged.
- [ ] Test: main-checkout commit re-bases an open bound run with a matching baseline.
- [ ] Test: running-job APIs serialise while `_RUN_BASELINES` holds an entry.
- [ ] Test: `test_merge_refusal_keeps_the_commit` uses a session-in-main worker.
- [ ] Test: registry `commit: false` parses; `set_flags` writes `commit` and keeps other fields.
- [ ] Test: commit endpoint returns 400 for a `commit: false` project.
- [ ] `.venv/bin/python3 -m pytest -q tests/test_session_commit.py tests/test_project_registry.py tests/test_project_dispatch.py tests/test_projects.py` passes.
- [ ] Full `.venv/bin/python3 -m pytest -q tests` shows no new failures versus base.
- [ ] Browser check: open a Commit preview, turn Commit off in Edit, save; the row shows no Commit button.
- [ ] `/verify` against an isolated runner: Projects panel renders, form shows the Commit checkbox, a `commit: false` project has no Commit button.

## Progress Checklist

- [ ] Split `fingerprint` into `fingerprint_parts` + `fingerprint_of` (refs part excludes the current branch ref).
- [ ] Split `ls-files -v` into `tracked` names and non-`H` `flags`.
- [ ] Add `commit` to `_FIELDS`, `Project`, `_parse_project`, `projects.example.yaml`.
- [ ] Replace `set_confidential` with `set_flags`; update the PATCH endpoint.
- [ ] Update `set_confidential` tests to `set_flags`.
- [ ] Return `commit` from `/api/projects`; skip commit state when it is off.
- [ ] Refuse the commit endpoint for a `commit: false` project.
- [ ] Dashboard: pass the project to `_sessionRow`; hide Commit when off.
- [ ] Dashboard: an open Commit editor is not rendered when the project's Commit is off.
- [ ] Dashboard: Commit checkbox in the project form (add sends `commit: false` only when unchecked; edit PATCHes it).
- [ ] Add `_RUN_BASELINES`; write it with the opening fingerprint under the gate and `_JOB_LOCK`.
- [ ] Add `closing` param to `post_run`; app closing callable pops the baseline under the gate.
- [ ] Use the same closing callable on the cancelled path.
- [ ] Make sure the baseline entry is dropped on every exit of `_run_project_ticket`.
- [ ] `_rebase_bound_runs`: read `pre` parts for each baseline of the checkout.
- [ ] `_rebase_bound_runs`: mark `changed` when `pre` differs from the baseline.
- [ ] `_rebase_bound_runs`: after success, mark `changed` when a non-sanctioned component moved, else `base = post`.
- [ ] `_rebase_bound_runs`: re-base nothing when the operation raises.
- [ ] `_rebase_bound_runs`: mark `changed` on a fingerprint error.
- [ ] Closing callable honours the sticky `changed` mark.
- [ ] `_project_runs_open`: option to skip project-bound runs; `_manual_merge` uses it and wraps the merge.
- [ ] Add `main_guard` to `commit_checkout`; pass it from `api_session_commit`.
- [ ] Write the tests listed under Verification.
- [ ] Run verification.
- [ ] Fresh Codex inspection of the diff.
- [ ] Update `docs/context-maintenance.md` with validation and next action.
- [ ] Commit on `agent/AGE-124`.
- [ ] Tell the user to untick "Commit button" for `knowledge_base` in its Edit dialog (`projects.yaml` is outside this worktree).
