# Review log — 2026-10-22-session-commit-concurrency (AGE-124)

- Host/coordinator: Claude Code (Opus 5.5). Plan reviewer: Codex (CLI default model/effort). Builder: Claude. Inspector: fresh Codex.
- Rounds: plan review max 20; fix max 20; inspection max 20. Fallback: same-provider-on-unavailable. Inspection: on.
- Authorization: ticket dispatch (plan + implement + local commit on agent/AGE-124; no push).
- Non-interactive session: Phase 1 questions resolved by the host (recorded as assumptions in the plan).
- Budget: plan small (~2 runner files + index.html); single review session resumed per round; fixes batched before reinspection.

## Round 1 — Codex REVISE
result: /tmp/claudex-AGE-124/review1/claudex-x21gjs78/result.json
{
 "verdict": "REVISE",
 "summary": "The plan can break live-run APIs and hide unrelated checkout changes during rebasing. Its main-checkout commit acceptance criterion also exceeds the proposed algorithm.",
 "findings": [
  {
   "id": "AGE124-R01",
   "severity": "high",
   "path": "docs/exec-plans/active/2026-10-22-session-commit-concurrency.md:36",
   "evidence": "The proposed fingerprint metadata goes directly into job dictionaries. Existing /api/runs?state=running serializes entire jobs (runner/app.py:5179), and /api/runs/<run_id> does likewise (5241–5249). The existing exclude value is a set (runner/project_runs.py:732–741); Project also contains a Path. Storing these values as proposed causes JSON serialization failures while project runs are open. The dashboard consumes the running endpoint during board refresh (runner/templates/index.html:2939–2944).",
   "fix": "Keep fingerprint metadata in a private run-id map, or explicitly omit it from both API responses. Add verification that running-list and live-detail requests remain serializable while fingerprint metadata exists."
  },
  {
   "id": "AGE124-R02",
   "severity": "high",
   "path": "docs/exec-plans/active/2026-10-22-session-commit-concurrency.md:41",
   "evidence": "Matching the baseline before a sanctioned operation does not establish that every subsequent change came from that operation. For example, after the pre-check matches, an open non-confidential run writes .git/hooks/post-commit while another session's merge is executing. The post-operation fingerprint includes that write and becomes the new baseline, so closing_check reports unchanged. The merge gate does not constrain agent or verify processes: non-confidential Claude uses bypassPermissions (runner/project_runs.py:108), and non-confidential verify runs without confinement (runner/projects.py:1540–1545). Hook changes are explicitly fingerprinted (1471–1478), and tests/test_project_dispatch.py:537–547 establishes that such writes must be detected.",
   "fix": "Preserve detection of unrelated fingerprint components instead of replacing the entire baseline with observed post-operation state. Validate the expected merge/commit delta and retain detection for hooks, configuration, and unrelated files. Add a deterministic regression where an unrelated write occurs between the pre-check and completion."
  },
  {
   "id": "AGE124-R03",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-22-session-commit-concurrency.md:86",
   "evidence": "The acceptance criterion says a main-checkout commit during an open bound run does not flag that run. However, start a run on clean main, edit a main-checkout file, then click Commit: fingerprint includes staged and unstaged diffs (runner/projects.py:1449–1450), so the pre-commit fingerprint already differs. The proposed equality filter excludes this run from rebasing, and closing still reports changed. The algorithm only suppresses the commit's effect when the pre-commit state already matches the opening baseline.",
   "fix": "Resolve this policy explicitly. Qualify the acceptance criterion to cover only commit-induced changes with a matching pre-operation baseline, and verify both edits present before run opening and edits made afterward. If later edits must also be sanctioned, define their authorization separately without silently clearing unrelated violations."
  },
  {
   "id": "AGE124-R04",
   "severity": "low",
   "path": "docs/exec-plans/active/2026-10-22-session-commit-concurrency.md:36",
   "evidence": "Actionable approach items are ordinary bullets rather than their own '- [ ]' checkboxes. Lines 36–52 specify baseline publication, gated closing and removal, cancellation callback reuse, snapshot eligibility, fingerprint-error and exception handling, retained activity blockers, and main_guard conditions/lock order. Lines 58–64 specify registry/API/UI behavior and the user's knowledge_base configuration step. The coarse Progress Checklist does not give each of these sub-steps its own checkbox; the configuration step at line 64 has no checklist counterpart.",
   "fix": "Give every actionable item and sub-step its own unchecked checkbox, including configuring knowledge_base. Keep background, risks, and non-goals as prose."
  }
 ],
 "coverage": [
  "Read the on-disk plan and verified its SHA256 matches the supplied hash.",
  "Traced project-run admission, opening and closing fingerprints, cancellation, finalization, manual merge, and background merge-queue writers.",
  "Inspected registry parsing and mutation, lifecycle and ticket locks, commit/merge helpers, and fingerprint contents.",
  "Inspected Projects rendering, commit preview/submission, project forms, API responses, and live-run serialization consumers.",
  "Traced related shared-state paths in PTY admission and stall detection; read relevant existing commit, registry, dispatch, and concurrency tests."
 ],
 "limitations": [
  "Static plan review against the current implementation; no implementation diff was present.",
  "No files edited, tests executed, runtime/browser checks performed, or work delegated.",
  "Did not inspect the external live projects.yaml or formal SPEC.md."
 ]
}

Dispositions for round 1:
- AGE124-R01 ACCEPTED: baselines move to a private `_RUN_BASELINES` map; never in job dicts. Added AC + test for /api/runs serialisation.
- AGE124-R02 ACCEPTED: fingerprint split into components; only components the operation may change (merge: head, flags; commit: head, flags, staged, unstaged, untracked) are re-based, and only where pre == baseline. Any non-sanctioned component that changed between pre and post blocks re-basing for that run. Added hook-during-merge regression test.
- AGE124-R03 ACCEPTED: policy stated — commits only stop being blamed on runs whose main checkout was unchanged since they opened; later edits still flag. AC qualified.
- AGE124-R04 ACCEPTED: checklist split into one deliverable per box, including the knowledge_base configuration hand-off.

## Round 2 — Codex REVISE
result: /tmp/claudex-AGE-124/review2/claudex-unqt8nxs/result.json
{
 "verdict": "REVISE",
 "summary": "The private baseline map resolves R01, and the qualified acceptance criterion addresses R03's wording. However, component rebasing introduces two concrete ways to hide checkout violations. Some new algorithm substeps also remain without individual checkboxes.",
 "findings": [
  {
   "id": "AGE124-R05",
   "severity": "high",
   "path": "docs/exec-plans/active/2026-10-22-session-commit-concurrency.md:53",
   "evidence": "Keeping an old component value does not preserve an earlier violation when committing resets that component. Example: a run opens on clean HEAD H0; a tracked main-checkout file is edited afterward; then the user commits it. Before commit, head still matches baseline but unstaged differs. The algorithm rebases head to H1 while retaining the original empty unstaged hash. After commit, unstaged is empty again, so every baseline component matches and closing reports unchanged. This contradicts the explicit policy at lines 63–65. The existing commit path stages and commits these edits (runner/projects.py:1349–1353).",
   "fix": "Record a persistent violation when pre-operation state differs from the run's baseline, and preserve it through closing regardless of subsequent component equality. Alternatively, refuse all rebasing for that baseline once any component differs. Add a regression covering edits made after opening followed by a main-checkout commit."
  },
  {
   "id": "AGE124-R06",
   "severity": "high",
   "path": "docs/exec-plans/active/2026-10-22-session-commit-concurrency.md:48",
   "evidence": "The entire flags component is sanctioned during merges, but ls-files -v includes skip-worktree and assume-unchanged bits as well as filenames. After the merge completes but before the post snapshot, an open non-confidential worker can set skip-worktree on an unrelated tracked file and edit it. Git diffs/status hide that edit; only flags changes, and the algorithm absorbs that change into the baseline. Existing tests explicitly require detection of this scenario without rebasing (tests/test_projects.py:628–641). Non-confidential workers are not constrained by the merge gate (runner/project_runs.py:108). This is a remaining component-level gap distinct from the resolved hook example.",
   "fix": "Separate tracked-path membership from per-path index flags. Permit only membership changes justified by the merged tree, while preserving detection of unexpected flag changes. Add a merge-window regression that sets skip-worktree and edits an unrelated main-checkout file."
  },
  {
   "id": "AGE124-R07",
   "severity": "low",
   "path": "docs/exec-plans/active/2026-10-22-session-commit-concurrency.md:50",
   "evidence": "The revised algorithm introduces actionable substeps without their own '- [ ]' checkboxes: collect pre/post parts, reject rebasing on non-sanctioned changes, apply per-component eligibility, rebase nothing after an operation exception, and skip a baseline after fingerprint errors (lines 50–55). Progress item 138 only says to add _rebase_bound_runs and does not individually track these substeps.",
   "fix": "Add an individual unchecked checkbox for each algorithm substep, including both failure paths."
  }
 ],
 "coverage": [
  "Read the revised on-disk plan and verified SHA256 21c89ca06281b051d29810a2336c561d8a177d25b3a4f3ac8138d89bb2d1bf7b.",
  "Compared the revision with all four prior findings and host dispositions.",
  "Inspected current fingerprint components, commit/merge operations, private-baseline design, closing callbacks, and live-run serialization.",
  "Traced related callers and shared-state writers through automatic merge draining, cancellation/finalization, stall detection, and PTY admission.",
  "Inspected relevant existing fingerprint, index-flag, dispatch, registry, and session-commit tests, plus commit preview/submission behavior."
 ],
 "limitations": [
  "Static review only: no files edited, tests executed, browser checks performed, or work delegated.",
  "Implementation files changed during inspection; findings concern the supplied plan and source snapshots read, not a completed implementation.",
  "External live projects.yaml and formal SPEC.md were not inspected."
 ]
}

Dispositions for round 2:
- AGE124-R05 ACCEPTED: per-component retention replaced by a sticky `changed` mark. Any baseline whose `pre` differs from it is marked changed; closing reports changed regardless of later equality. Regression test added (edit after open, then main commit).
- AGE124-R06 ACCEPTED: `ls-files -v` split into `tracked` (names, sanctioned for merge/commit) and `flags` (non-`H` entries, never sanctioned). Regression test added (skip-worktree + edit during merge).
- AGE124-R07 ACCEPTED: each algorithm substep and failure path has its own checkbox.
Note: implementation of the uncontested parts (commit flag; fingerprint split) started in the worktree while this round ran; it follows the plan as written.

## Round 3 — Codex REVISE
result: /tmp/claudex-AGE-124/review3/claudex-galaf4fn/result.json
{
 "verdict": "REVISE",
 "summary": "The revised plan addresses the prior fingerprint and checkbox findings. One new state-transition defect remains in the partial Commit-toggle implementation.",
 "findings": [
  {
   "id": "AGE124-R08",
   "severity": "medium",
   "path": "runner/templates/index.html:1225",
   "evidence": "Open a session's Commit preview, then open the project's Edit dialog, disable Commit, and save. Neither _projectFormOpen nor loadProjects clears _sessionEdit. Although the ordinary button respects commit=false at line 1210, the existing commit editor ignores that flag at line 1225 and renders Commit/Commit & merge again at line 1242. The endpoint rejects submission, but the disabled project retains an actionable Commit button, violating acceptance criterion 109. The error handler also preserves the preview, so rejection does not remove the button.",
   "fix": "Invalidate commit-editor state when refreshed project data disables Commit, and guard the commit-editor rendering branch with the flag. Invalidate pending preview responses as well. Add an acceptance/verification checkbox covering disabling Commit while a preview is already open."
  }
 ],
 "coverage": [
  "Read the on-disk plan and verified SHA256 6b60bc717a8231abce6f212a2bfc20939da52a2395a6652ca94f0f87b9569ffe.",
  "Checked prior dispositions: private metadata, sticky violation tracking, separate index flags, and individual algorithm checkboxes address the previously reported scenarios.",
  "Inspected current fingerprint splitting, commit/merge helpers, activity gates, and automatic merge-queue interactions.",
  "Traced related shared-state paths through stall detection and PTY admission.",
  "Reviewed partial registry/API/UI changes and traced commit preview state through project editing, refresh, rendering, submission, and rejection.",
  "No additional unboxed actionable substep identified beyond the items addressed by the revised checklist."
 ],
 "limitations": [
  "Static review only; no files edited, tests executed, browser checks performed, or work delegated.",
  "Implementation is partial; this is not approval of a completed implementation.",
  "External live projects.yaml and formal SPEC.md were not inspected."
 ]
}

Dispositions for round 3:
- AGE124-R08 ACCEPTED: `_sessionRow` drops a commit-mode editor when the project's Commit is off (covers a preview response arriving later too, since rendering ignores it). Added AC, verification and checklist boxes.
Implementation status: commit flag, fingerprint split (tracked vs flags), private baselines, gated closing, `_rebase_bound_runs` with sticky `changed`, merge/commit wiring and tests are in the worktree; tests/test_session_commit.py 64 passed.

## Round 4 — Codex APPROVED (plan sha256 70827f10…)
result: /tmp/claudex-AGE-124/review4/claudex-v1ioxm5e/result.json
{
 "verdict": "APPROVED",
 "summary": "No material unresolved defects found in the revised plan and inspected changes. Prior findings are addressed, including the open-editor case.",
 "findings": [],
 "coverage": [
  "Verified the on-disk plan matches SHA256 70827f10421449f4fa78ae9bd80810e5f99a6cf6d1aede4e49c32da2071ad15e.",
  "Reviewed all seven modified files and checked prior findings R01–R08 against the revision.",
  "Traced baseline publication, rebasing, gated closing, exception cleanup, cancellation, and finalization.",
  "Checked manual and automatic merge interactions, ticket/gate/merge-lock ordering, checkout aliases, and live-run serialization.",
  "Traced related activity writers through baseline testing, stall detection, and PTY admission.",
  "Reviewed registry mutations, commit endpoint enforcement, project forms, and disabled Commit rendering with an existing or delayed preview.",
  "Read added regression tests as source. Previously identified actionable substeps now have checklist entries."
 ],
 "limitations": [
  "Static review only; no files edited, tests executed, browser checks performed, or work delegated.",
  "Host-reported test results were not independently verified.",
  "External live projects.yaml and formal SPEC.md were not inspected.",
  "Approval applies to the inspected plan and source snapshots; planned runtime verification remains outstanding."
 ]
}

## Inspection 1 — fresh Codex, REVISE (cross_provider)
result: /tmp/claudex-AGE-124/inspect1/claudex-ieec39lo/result.json
{
 "verdict": "REVISE",
 "summary": "Two rebasing defects can hide unrelated main-checkout changes from open runs.",
 "findings": [
  {
   "id": "AGE124-I01",
   "severity": "high",
   "path": "runner/app.py:3411",
   "evidence": "Commit rebasing sanctions the entire staged, unstaged and untracked components. Suppose a run opens with a pending user edit and an ignored .env file. During the user's commit, another non-confidential worker changes .env. git add -A never includes that ignored file, but _rebase_bound_runs accepts its changed untracked hash and replaces the baseline at line 3443. Closing consequently reports unchanged. Unrelated tracked edits made after staging are similarly absorbed while remaining uncommitted. These cases exceed the plan's accepted risk of concurrent edits actually included in the user's commit.",
   "fix": "Rebase only changes explained by the completed commit. Preserve ignored-file fingerprints and detect unexpected remaining staged, unstaged or untracked changes. Add deterministic regressions for an ignored-file write during commit and an unrelated tracked edit after staging."
  },
  {
   "id": "AGE124-I02",
   "severity": "high",
   "path": "runner/app.py:3440",
   "evidence": "Merge rebasing permits arbitrary head and tracked changes without comparing them to the merge result. After merge_into_checkout completes its validation and returns H1, an open non-confidential worker can reset the main checkout to H0 before the post snapshot. Only sanctioned components change; staged/unstaged remain clean, and fingerprint_parts excludes the current branch's ref. The baseline is accepted, closing reports unchanged, and _manual_merge still returns H1 although the requested merge has been removed. The gate does not constrain the worker's git commands.",
   "fix": "Pass the validated merge result into rebasing and require the post snapshot's HEAD and tracked membership to match that result. Mark baselines changed on any unexpected delta. Add a regression that resets HEAD after the merge helper returns but before rebasing snapshots it."
  }
 ],
 "coverage": [
  "Read the plan, review log, and changed portions of every manifested file; verified all supplied file hashes and the tracked diff hash.",
  "Traced baseline publication, rebasing, closing, cancellation, exception cleanup, finalization, and live-run serialization.",
  "Traced manual and automatic merges, commit callers, checkout aliases, lifecycle/ticket/merge locks, baseline-test activity, PTY admission, and stall handling.",
  "Reviewed registry persistence, Commit enforcement, project forms, preview rendering, and relevant regression-test source."
 ],
 "limitations": [
  "Static review only; no files edited, tests executed, browser checks performed, or work delegated.",
  "Formal SPEC.md and external live projects.yaml were not inspected.",
  "Graphify output was absent; related callers and state writers were traced directly in source."
 ]
}

Dispositions:
- AGE124-I01 ACCEPTED: `ignored` split from `untracked` and never sanctioned; after a commit the guard requires staged/unstaged/untracked to be empty (`CLEAN_PARTS`), HEAD to be the reported commit and its parent the pre-commit HEAD. Regressions: ignored-file write during commit; tracked edit left after commit.
- AGE124-I02 ACCEPTED: the merge reports its HEAD and branch tip; post HEAD must equal it, with first parent = pre HEAD or (fast-forward) HEAD = tip and pre HEAD an ancestor. Regressions: HEAD reset after merge; non-fast-forward merge still re-based.
Tests: test_session_commit.py + test_projects.py 149 passed.

## Inspection 2 — fresh Codex, REVISE (cross_provider)
result: /tmp/claudex-AGE-124/inspect2/claudex-xs4icgf1/result.json

Dispositions:
- AGE124-I03 ACCEPTED: merge_into_checkout reads HEAD once and validates that sha (ancestry + tree) before returning it. Regression: HEAD replaced after the check is not returned; the run is flagged.
- AGE124-I04 ACCEPTED: `_explained` accepts an unchanged checkout whose reported HEAD equals the pre HEAD (already-merged no-op). Regression added.
Note: the session restarted after inspection 2; the runner auto-committed the work as a30ef92 meanwhile.

Correction to the Inspection 2 entry: its result is /tmp/claudex-AGE-124/inspect2/claudex-4qre2co3/result.json (the other directory was an interrupted relaunch). Response:
{
 "verdict": "REVISE",
 "summary": "Two concurrency defects remain: merge-result rebasing can absorb an unrelated HEAD replacement, and an already-completed merge can falsely flag open runs.",
 "findings": [
  {
   "id": "AGE124-I03",
   "severity": "high",
   "path": "runner/app.py:3423",
   "evidence": "merge_into_checkout validates moving HEAD at runner/projects.py:1296–1298, then reads HEAD again to return it at line 1300. Between those commands, an open non-confidential worker can reset main to its own existing commit B whose first parent is the pre-merge HEAD. The helper reports B; _explained accepts its matching HEAD and first parent without checking the expected merge tree or target ancestry. With a clean checkout, only sanctioned components differ, so the baseline absorbs the unrelated replacement and closing reports unchanged. The runner's locks do not constrain worker git commands.",
   "fix": "Capture the result SHA once and validate that immutable SHA against the expected merge tree and target ancestry, then return the same SHA. Keep the post-snapshot HEAD comparison. Add a regression replacing HEAD between helper validation and its current final HEAD read."
  },
  {
   "id": "AGE124-I04",
   "severity": "medium",
   "path": "runner/app.py:3426",
   "evidence": "commit_checkout checks _ahead before acquiring the merge gate (runner/projects.py:1361). While request A waits, another ticket's merge can incorporate A's tip and advance main beyond it. A subsequently performs an already-up-to-date merge. Its pre/post fingerprints are identical, but _explained rejects it because HEAD's first parent is not HEAD itself and returned HEAD differs from A's older tip. _rebase_bound_runs then permanently marks otherwise unchanged open runs as changed.",
   "fix": "Accept a verified no-op when post equals pre and the reported HEAD equals pre HEAD, or recheck merge necessity under the gate before entering rebasing. Add a regression with overlapping branch histories and two queued manual merge requests."
  }
 ],
 "coverage": [
  "Read the plan, review log, and changed sections of every manifested file; verified all supplied per-file SHA256 values.",
  "Traced baseline publication, rebasing, closing checks, cancellation, exception cleanup, finalization, and automatic merge draining.",
  "Inspected registry writers, lifecycle/ticket/merge locks, commit and merge helpers, fingerprints, and live-run serialization.",
  "Reviewed Commit enforcement, project forms, preview rendering, PTY admission, stall-state writers, and relevant test source.",
  "Inspected relevant SPEC.md scope, API, and non-functional requirements."
 ],
 "limitations": [
  "Static review only: no files edited, tests executed, runtime/browser checks performed, or work delegated.",
  "Host-reported test results were not independently verified.",
  "The external live projects.yaml was not inspected."
 ]
}

## Inspection 3 — fresh Codex, REVISE (cross_provider)
result: /tmp/claudex-AGE-124/inspect3/claudex-9w01zj84/result.json
{
 "verdict": "REVISE",
 "summary": "The merge fixes address I03/I04, but commit rebasing can still hide an unrelated replacement of the main checkout.",
 "findings": [
  {
   "id": "AGE124-I05",
   "severity": "high",
   "path": "runner/projects.py:1359",
   "evidence": "After git commit creates C, a concurrent non-confidential worker can reset main to an existing sibling commit B before rev-parse HEAD runs. The endpoint reports B and sets expect.head to B. If B's parent is the pre-operation HEAD and the checkout is clean, _explained (runner/app.py:3423–3433) accepts it without checking the committed tree. The changed baseline then hides the replacement, although the user's requested commit has disappeared from main. Worker git commands do not take the runner's locks.",
   "fix": "Capture the intended staged tree and parent, validate the captured result SHA against both before publishing it as expect.head, and retain the post-snapshot HEAD comparison. Mark affected baselines changed on mismatch. Add a regression that resets main to a different sibling commit after git commit returns but before HEAD is captured."
  }
 ],
 "coverage": [
  "Verified the plan SHA256 and inspected changed content in every manifested file.",
  "Traced baseline publication, rebasing, closing checks, cancellation, cleanup, and live-run serialization.",
  "Inspected commit and merge helpers, automatic merge draining, checkout aliases, and lifecycle/ticket/gate/merge lock interactions.",
  "Traced related activity writers through session launches, baseline verification, PTY admission, cancellation, and stall detection.",
  "Reviewed registry persistence, Commit enforcement, project forms, disabled-editor rendering, and regression-test source."
 ],
 "limitations": [
  "Static review only; no files edited, tests executed, browser checks performed, or work delegated.",
  "Formal SPEC.md and the external live projects.yaml were not inspected.",
  "All manifested implementation and test hashes matched; the review log contained an additional correction and differed from its supplied hash."
 ]
}

Dispositions:
- AGE124-I05 ACCEPTED: commit_checkout records the parent and the staged tree (`write-tree`) before `git commit`, reads HEAD once afterwards and refuses ("moved while committing") unless that sha has exactly that tree and parent; only then is it published as expect.head. Regression: HEAD swapped for a sibling right after `git commit`.
Tests: test_session_commit.py 71 passed; full suite 919 passed before this fix.

## Inspection 4 — fresh Codex, REVISE (cross_provider)
result: /tmp/claudex-AGE-124/inspect4/claudex-cdu1nhd6/result.json
{
 "verdict": "REVISE",
 "summary": "The I05 fix still permits an unrelated merge commit to replace the requested commit without flagging open runs.",
 "findings": [
  {
   "id": "AGE124-I06",
   "severity": "high",
   "path": "runner/projects.py:1362",
   "evidence": "Validation checks the captured commit's tree and first parent, but allows additional parents. After git commit creates C, a concurrent non-confidential worker can replace HEAD with B whose tree matches C and whose parents are [pre-operation HEAD, unrelated agent-branch tip]. Both checks pass, so B is published as expect.head. _explained also checks only the first parent (runner/app.py:3428–3433); with a clean checkout, rebasing absorbs B and closing reports unchanged. Unrequested branch history has entered main while the user's actual commit disappeared. The new regression covers only a replacement with a different tree.",
   "fix": "Validate the captured commit's complete parent list and require exactly [parent] for a plain commit. Retain the tree and post-snapshot HEAD checks. Add a regression replacing C with a same-tree commit carrying an additional parent, and verify refusal plus detection by the open run."
  }
 ],
 "coverage": [
  "Reviewed the plan, review log, and changed content in every manifested file; verified all supplied file hashes and the tracked diff hash.",
  "Traced baseline publication, rebasing, closing callbacks, cancellation, exception cleanup, finalization, and live-run serialization.",
  "Inspected manual and automatic merges, commit callers, checkout aliases, and lifecycle/ticket/gate/merge lock ordering.",
  "Traced related activity writers through session launches, baseline verification, PTY admission, and stall detection.",
  "Reviewed registry persistence, Commit enforcement, project forms, disabled-editor rendering, relevant SPEC.md requirements, and regression-test source."
 ],
 "limitations": [
  "Static review only; no files edited, tests executed, runtime/browser checks performed, or work delegated.",
  "Host-reported test results were not independently verified.",
  "The external live projects.yaml was not inspected."
 ]
}

Dispositions:
- AGE124-I06 ACCEPTED: commit_checkout requires the read-once HEAD's full parent list (`^@`) to be exactly [pre HEAD]. Same tightening applied in `_explained`: parents must be exactly [pre HEAD] (commit) or [pre HEAD, branch tip] (merge), else only a fast-forward to the tip passes. Regression: same-tree commit with an extra parent swapped in after `git commit`.
Tests: test_session_commit.py 72 passed; full suite 920 passed before this fix.

## Inspection 5 — fresh Codex, APPROVED (cross_provider)
result: /tmp/claudex-AGE-124/inspect5/claudex-5wagyuvk/result.json
{
 "verdict": "APPROVED",
 "summary": "No material unresolved defects found. The I06 fix validates the complete parent list and retains tree and post-operation HEAD checks.",
 "findings": [],
 "coverage": [
  "Read the plan, review log, and changed content in every manifested file; verified all supplied file hashes and the tracked diff hash.",
  "Traced baseline publication, rebasing, closing checks, cancellation, exception cleanup, and live-run serialization.",
  "Reviewed manual and automatic merges, commit validation, checkout aliases, and lifecycle/ticket/gate/merge lock ordering.",
  "Traced related activity writers through session launches, baseline verification, and PTY admission.",
  "Reviewed registry persistence, Commit endpoint enforcement, project forms, disabled-editor rendering, and regression-test source."
 ],
 "limitations": [
  "Static review only: no files edited, tests executed, runtime/browser checks performed, or work delegated. Host-reported test results were not independently verified.",
  "Formal SPEC.md and the external live projects.yaml were not inspected.",
  "Graphify output was absent; callers and shared-state writers were traced directly in source."
 ]
}

Final: plan review 4 rounds (approved), inspection 5 rounds (approved), assurance cross_provider, no fallback. Full suite 921 passed.
