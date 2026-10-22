# Review log — 2026-10-22-confidential-local-tasks

- Roles: host/planner/builder = Claude Code (this session); plan reviewer = Codex CLI 0.163.0; final inspector = fresh Codex session. Fallback: same-provider on recorded unavailability.
- Models: CLI defaults (no explicit model/effort requested); observed models recorded per round.
- Scope: AGE-127 option A — confidential project tasks local-only while the tracker is Linear; remove stopgap `_refuse_confidential_on_linear`.
- Authorization: user asked to plan and build with multi-round claudex-loop ("不管怎么样，用多轮/claudex-loop，这个必须改掉", 2026-10-22). Commit on agent/AGE-127; no push.
- Limits: 20 plan-review rounds, 20 fix rounds, 20 inspection rounds.
- Budget: rough estimate — plan review reads the plan plus `runner/modules/linear/__init__.py` (~2000 lines), parts of `runner/app.py`, `local_tracker.py`, tests; inspection gets the diff (expected a few hundred lines). User explicitly requested multi-round; no token-reducing option taken.
- Run artifacts: /tmp/claudex-AGE-127/ (outside the checkout).

## Round 1 — plan review
- Result: /tmp/claudex-AGE-127/review1/claudex-a4qa9ua6/result.json — verdict REVISE, assurance cross_provider, session 01a163f0-e236-7c60-8a6d-b7f0e53cdd77, plan sha 63ca118b…, 266 s.
- R1 (high) persisted local_only must be authoritative over a partial cache entry — ACCEPTED: predicate reads tasks.json when the cache entry lacks the flag; push_state hydrates; test added.
- R2 (medium) cache→local backup and terminal carry-over can overwrite comments — ACCEPTED: both skip local-only; poll publish refreshes from tasks.json; test added.
- R3 (medium) Linear overrides mask local-only state — ACCEPTED: overrides ignored/dropped for local-only; Todo-reset-then-run test added.
- R4 (high) _issues_comment bypasses post_comment — ACCEPTED: route listed; declassified-before-dispatch test; raw comment transport faked to fail.
- R5 (low) checkbox format — ACCEPTED: every actionable item is its own box.

## Round 2 — plan review
- Result: /tmp/claudex-AGE-127/review2/claudex-kdkvt70y/result.json — verdict REVISE, cross_provider, same session, plan sha cf10b70b…, 204 s. R1–R4 confirmed resolved.
- R6 (medium) async state pushes can persist out of order — ACCEPTED: local-only pushes persist synchronously under the issue lock; ordering test added.
- R5 (low, partial) grouped boxes remain — ACCEPTED: split every grouped implementation, verification and acceptance item.

## Round 3 — plan review
- Result: /tmp/claudex-AGE-127/review3/claudex-vwva3aej/result.json — verdict APPROVED, cross_provider, same session, plan sha fc1132f9498f5211…, 85 s. R1–R6 resolved; no further material defects.
- Approval check passed on the approved hash. Pre-build base: b749d95. Builder: Claude (host). Deviation: the host started editing code while round 3 ran; those edits follow the approved plan and are covered by the build inspection.

## Build
- Built by Claude (host) on base b749d95. Proof: py_compile OK; full pytest 934 passed (before the last two tests; task_project 38 passed after); targeted mutations (poll merge, cache write-back, terminal carry-over, async push, override apply, comment route, team view, unsynced gate) each fail a test.
- /verify: isolated runner 8599, Linear mode (dummy key), sitecustomize answering api.linear.app locally. "+" form → local-only LOC-1; board shows "local" chip, no "syncing…", ▶ dispatch button; dispatch ran in the project worktree, record status review, tasks.json In Review. Linear request log: 2 team queries, 0 naming the task, its identifier, title or project.

## Inspection round 1
- Result: /tmp/claudex-AGE-127/inspect1/claudex-ec0ihbzd/result.json — verdict REVISE, cross_provider, fresh session 01a16404-d5a0-7a22-8200-5ce5ab935273, 234 s.
- F1 (high) after Empty trash the local_only record is gone, so a late comment for that local- id could reach Linear — ACCEPTED: `_local_id` guard at the outbound boundaries (`_post_linear_comment_raw`, `post_comment`, `_push_sync`, `_linear_sync_patch_locked`) refuses every `local-` id whatever its record says; the comment route 404s an emptied card. The unsynced-placeholder dispatch gate is unchanged. Tests: feedback, runner comment, push and sync patch after Empty trash of a declassified task make no Linear call; the raw transport refuses a local id. Full suite: 938 passed, 26 warnings in 352.26s (0:05:52).

## Inspection round 2
- Result: /tmp/claudex-AGE-127/inspect2/claudex-ct5p16_t/result.json — verdict REVISE, cross_provider, fresh session 01a1640e-c7dd-7c03-857d-21abd87dd2ea, 145 s.
- I2-01 (high) a deleted local-only id made _on_linear true (rename, detail could send it) — ACCEPTED: _on_linear treats every local- id as local; _issues_patch_reserved keeps the unsynced placeholder's Linear-branch 409 explicitly; set_card_title rechecks the archived set under its lock. Test: detail 404 and rename refused after Empty trash, no Linear call.
- I2-02 (medium) run-end "review" push overwrote a Canceled/Done local-only task — ACCEPTED: push_state keeps a persisted terminal state against a "review" push (run ends, run cancel); explicit "running" (dispatch/retry) still applies. Test parametrized Canceled/Done, also across a poll. Linear tasks unchanged (out of scope).
- I2-03 (medium) Empty trash text promised Linear recovery for local tasks — ACCEPTED: the confirm counts Linear issues (archived, recoverable) and local tasks (deleted for good) separately. Browser check on isolated runner 8599: local-only only and mixed messages correct; Linear request log names nothing.
- Mutations: _on_linear by flag only → fails; terminal guard off → fails; the rename recheck is a second guard (local branch already refuses a missing card). Full suite: 941 passed, 26 warnings in 343.67s (0:05:43).

## Inspection round 3
