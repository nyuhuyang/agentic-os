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
