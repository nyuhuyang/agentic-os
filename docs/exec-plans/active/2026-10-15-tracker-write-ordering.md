---
status: in-progress
created: 2026-10-15
---

# Tracker write ordering per issue

## Goal
For one issue, an older tracker state write must never land after a newer one. This holds across every writer:
- run-scoped pushes from different runs of the same issue;
- two pushes from the same run;
- manual PATCH moves;
- the async `_linear_sync_patch`.

Origin: plan review rounds 4–6 of `docs/exec-plans/completed/2026-10-15-runner-write-safety.md` (WS-010 owner-push ordering, WS-011, WS-012). It was split out on 2026-10-15 because the race predates that plan and spans every tracker writer. Not started; it needs its own plan review before building. Build after runner-write-safety lands, since it reuses that plan's owner-only side effects.

## Findings carried over (from the runner-write-safety review log)
- WS-010: the owner's cancel/stall `review` push runs outside `_JOB_LOCK`, retry admission does not refuse (`app.py` ≈L3530 is `pass`), and each `push_state` write runs on its own `_push_sync` thread. As a result, A's `review` can overwrite retry B's `running`. `_mark_issue_review` changes `issues_cache` and `dispatched` and emits before any guard runs.
- WS-011: two pushes from one run (`running`, then `review`) can persist out of order, which returns a finished issue to In Progress.
- WS-012: the PATCH dispatch route queues `_linear_sync_patch` (Linear ≈L989–995), which checks only the reset generation. Direct PATCH writes (Linear ≈L949–965) do not invalidate queued pushes, and a manual Done does not bump the reset generation (≈L242–244), so an old queued `running` can overwrite Done.

## Draft approach (from rounds 4–5, to be extended for WS-012)
- `LinearModule.push_state(issue_id, status, gen=None, run_id=None)` and `_push_linear_state_async(..., run_id=None)` take an optional `run_id`.
  - The module keeps `issue_run[issue_id]`.
  - Under `reset_gen.issue_lock`, a `running` push with a `run_id` claims the issue, and any push whose `run_id` differs from the claim is dropped. The check runs in `push_state` and again in `_push_sync`.
- `_mark_issue_review(issue_id, gen, run_id=None)` checks the run before any mutation or emit.
- A per-issue sequence number is allocated whenever a state change is accepted. This covers `push_state`, direct PATCH state mutations and the PATCH dispatch sync. Each async state write (`_push_sync`, `_linear_sync_patch`) drops itself under the issue lock unless it is still the latest. Metadata-only edits do not bump the sequence.
- Every run-scoped caller passes its run:
  - Linear dispatch `running` / `_mark_issue_review`;
  - retry `running` / `_finish`;
  - cancel and stall `review`.
- ponytail: `issue_run` and the sequence map are never pruned.

## Progress Checklist
- [ ] Re-read the current tracker writers (push_state, _push_sync, _mark_issue_review, PATCH routes, _linear_sync_patch, local tracker) and finish the approach
- [ ] Codex plan review returns APPROVED
- [ ] Run-scoped pushes: `run_id` parameter, the claim on `running`, and the mismatch drop in `push_state` and `_push_sync`; all run-scoped callers pass their run
- [ ] `_mark_issue_review` checks the run before any mutation
- [ ] Per-issue sequence shared by push_state, direct PATCH state changes and `_linear_sync_patch`; superseded async writes dropped under the issue lock
- [ ] Test: delayed owner push. Pause A's cancel after its record and before its `review` push, let B claim and push `running`, then resume A. B stays `running` and keeps `dispatched`.
- [ ] Test: reordered persisted writes. A's `review` `_push_sync` runs after B's `running` one; the persisted state stays `running`.
- [ ] Test: delayed owning worker. Pause A before `_mark_issue_review`, let B claim, then release A. B's `issues_cache`, `dispatched` and emits are unchanged.
- [ ] Test: same-run reorder. The same run's `running` runs after its `review`; the persisted state is `review`.
- [ ] Test: a delayed PATCH-dispatch `_linear_sync_patch` cannot overwrite a later `review`
- [ ] Test: a queued old `running` push cannot overwrite a manual Done
- [ ] Full suite passes (`.venv/bin/python -m pytest tests/ -q -p no:cacheprovider`)
- [ ] Fresh cross-provider (Codex) build inspection returns no unresolved material findings
- [ ] Commit (not pushed)
