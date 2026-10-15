# Review log: 2026-10-15-runner-write-safety

- Host: claude (Claude Code, Opus 5.5). Plan reviewer: Codex. Builder: Claude. Final inspector: fresh Codex session.
- Models: none requested; CLI defaults.
- Authorization (2026-10-15): "修订 2026-10-15-runner-write-safety.md，并用claude执行" (revise + build).
- Rounds: plan review ≤ 20, fix ≤ 20, inspection ≤ 20. Fallback: same-provider-on-unavailable. Inspection: on.
- Budget: default effort; unrelated work committed first (`5a28e45`) so the build base is clean.

## Plan review round 1

- Result: `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/rws/review1/claudex-3w37xm_w/result.json`
- Plan SHA256 reviewed: 6dcc611d0aaa77a115126e3a04569b77a1cc77ab9293fa0e6e5840e5a8709caa
- Verdict: **REVISE**, 5 findings (WS-001..004 medium, WS-005 low). BUILD-009 and BUILD-017 reviewed: no material defect; empty-directory rename edge agreed.

```json
{
 "verdict": "REVISE",
 "summary": "The cache publication approach is sound, but the plan leaves concrete timeout and cancellation gaps, including an ungrouped Linear caller and retries that can restart after cancellation.",
 "findings": [
  {
   "id": "WS-001",
   "severity": "medium",
   "path": "runner/app.py:749",
   "evidence": "The proposed timeout cleanup runs when the stdout reader remains alive. If a subprocess closes stdout and then sleeps, the reader finishes immediately and text/Claude streaming enters the existing unbounded proc.wait() at lines 749/2311. AI_RUN_TIMEOUT_S never triggers, and the request's inflight reservation remains held. The planned sleeping-child tests retain stdout and miss this case.",
   "fix": "Use one monotonic deadline for reader joins and process waiting. Pass the remaining time to proc.wait and route its TimeoutExpired through the same group-kill, reap and reader-stop cleanup. Add early-stdout-EOF cases for text and Claude."
  },
  {
   "id": "WS-002",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-15-runner-write-safety.md:42",
   "evidence": "Replacing signals in the existing cancel structure leaves SIGKILL conditional on the leader's wait timing out (runner/app.py:3459–3463). A leader can exit promptly on SIGTERM while a descendant in the same group ignores SIGTERM. wait then succeeds, escalation is skipped, and the descendant survives cancellation.",
   "fix": "Ensure surviving group members receive SIGKILL after the grace period even when the leader has exited, and reap the leader after escalation. Add a cancellation case with a TERM-responsive leader and a TERM-ignoring descendant."
  },
  {
   "id": "WS-003",
   "severity": "medium",
   "path": "runner/modules/linear/__init__.py:680",
   "evidence": "Linear dispatch writes into the same _running_procs map and calls _stream_dsh_run at line 690, but its Popen lacks start_new_session=True. The plan changes that shared reader and the non-project cancel handler to assume pgid == pid while updating only three app.py spawn sites. For a Linear DSH job, killpg(proc.pid, ...) normally fails and the fallback kills only the leader; ordinary descendants survive. Linear's own timeout handler at lines 728–733 also still kills only the leader.",
   "fix": "Include this shared caller in the ownership changes: create its execution subprocess in a new session and apply group cleanup and bounded reaping to its timeout path. Preserve the requested signal in any single-process fallback. Cover timeout and dashboard cancellation of a Linear-launched job with descendants."
  },
  {
   "id": "WS-004",
   "severity": "medium",
   "path": "runner/app.py:3671",
   "evidence": "Cancellation removes job/process entries and writes a cancelled record without setting a cancellation flag. Cancelling a resumed Claude or Codex retry makes its first dispatch return nonzero, which satisfies the resume-failure fallback at line 3671 and launches another agent at line 3678. The worker can also append review/error after the cancelled record; _load_runs_from uses the latest append for that run_id. Signal substitution alone preserves both failures.",
   "fix": "Record cancellation before signalling, synchronize it with launches and finalization, and check it before fallback dispatch. Give the worker responsibility for the terminal cancellation record so later completion cannot overwrite it. Add a cancelled-resume test asserting no fallback process starts and cancellation remains terminal."
  },
  {
   "id": "WS-005",
   "severity": "low",
   "path": "docs/exec-plans/active/2026-10-15-runner-write-safety.md:16",
   "evidence": "The acceptance criterion identifies POST /api/runs/<id>/cancel, but the implemented route is DELETE /api/runs/<run_id> (runner/app.py:3446), also used by runner/templates/index.html:2283. A verification request to the documented POST route will not exercise cancellation.",
   "fix": "Correct the acceptance criterion and verification instructions to use the existing DELETE endpoint."
  }
 ],
 "coverage": [
  "Verified the plan file SHA256 matches 6dcc611d0aaa77a115126e3a04569b77a1cc77ab9293fa0e6e5840e5a8709caa.",
  "Inspected execution-registry publication, state_io atomic helpers, CLI registry consumption and the related registry-cache writer.",
  "Traced all three stream implementations, dashboard dispatch, retry/resume fallback, cancellation, maintenance accounting, progress persistence and terminal-record writers/readers.",
  "Inspected related Linear dispatch, stall cleanup and project process-group helpers beyond the plan's file list.",
  "Reviewed BUILD-009 construction/start exception handling and both failure-test sources; no material defect found in that fix.",
  "Reviewed rename_dir, move/rollback callers and the destination-race test. The stated empty-directory replacement behavior preserves the unnested checkout.",
  "Checked relevant SPEC.md dispatch, timeout, concurrency and persistence requirements, plus selected existing test sources."
 ],
 "limitations": [
  "Static plan and source review only; no files edited, tests run, services changed or work delegated.",
  "The proposed implementation does not yet exist; runtime behavior and the claimed 410-test baseline were not verified.",
  "Accepted escaped-descendant survival and normal-path inherited-stderr risks remain outside the proposed guarantees."
 ]
}
```

### Dispositions
Round 1 dispositions (host: Claude). All five findings verified against the code and accepted; the plan was revised.

- WS-001 accepted: one monotonic deadline per streamed run covers reader joins and proc.wait; any TimeoutExpired goes through the same stop/group-kill/reap/join cleanup. Early-stdout-EOF test added for all three readers.
- WS-002 accepted: cancel sends SIGTERM to the group, waits up to 5 s, then SIGKILL to the group unconditionally, then reaps. Test with a TERM-responsive leader and a TERM-ignoring descendant. Accepted ceiling: pgid reuse within the grace window, same as _terminate_group (noted with a ponytail comment).
- WS-003 accepted: the Linear dispatch Popen gets start_new_session=True; its timeout handler and its communicate branch use _kill_group plus bounded reaping; _kill_group's fallback keeps the requested signal (send_signal). Linear timeout test added.
- WS-004 accepted: cancel flags the job under _JOB_LOCK before signalling; workers call _take_job at every terminal point and skip their own record/comment/state push/emit when cancelled; the retry worker skips the resume-failure fallback when cancelled. Kept the cancel endpoint as the writer of the cancelled record (smallest change); a cancel racing after _take_job returns 404 and the finished run's own record stands (listed in Risks). Tests for retry and /api/run.
- WS-005 accepted: corrected to DELETE /api/runs/<run_id>.

## Plan review round 2

- Result: `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/rws/review2/claudex-qzv5ri1h/result.json`
- Verdict: **REVISE**, 4 findings (WS-004 still open, WS-006, WS-007 medium; WS-008 low). WS-001/002/003/005 addressed.

```json
{
 "verdict": "REVISE",
 "summary": "WS-001, WS-002, WS-003 and WS-005 are addressed at the plan level. WS-004 remains incomplete: cancellation is not synchronized with launch or finalization, and the new missing-job semantics break stall cleanup.",
 "findings": [
  {
   "id": "WS-004",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-15-runner-write-safety.md:80",
   "evidence": "The proposed cancellation check before fallback is separate from Popen and process registration. A retry can observe an uncancelled job, pause, then have DELETE flag/remove the job and write cancelled while no process is registered; the retry subsequently launches its fallback. Initial launches have the same window because jobs are published before Popen (app.py:2953–2963, 3007–3024; Linear:661–687). Terminal record suppression does not stop these processes.",
   "fix": "Synchronize cancellation with every launch and process registration, including initial and fallback launches. Use a shared lifecycle lock or a registration handshake that immediately stops a process whose launch raced with cancellation. Add deterministic tests pausing before launch and before registration."
  },
  {
   "id": "WS-006",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-15-runner-write-safety.md:77",
   "evidence": "_take_job removes only the job, whereas cancel returns 404 only when both job and process are absent. Existing normal completion removes the job before the process entry (app.py:2967–2968, 3043–3044; Linear:701–702). After _take_job commits an uncancelled outcome, DELETE can therefore still find the process and enter cancellation with no job to flag. This contradicts the stated 404 guarantee and can produce either a missing-job error or competing cancelled/completion records.",
   "fix": "Make the finalization decision and process-map retirement atomic with cancellation, or retain an explicit finalizing marker that cancellation rejects. Test DELETE after the worker claims finalization but before process removal and record persistence."
  },
  {
   "id": "WS-007",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-15-runner-write-safety.md:78",
   "evidence": "A missing job does not necessarily mean the cancel endpoint owns completion. The unchanged stall pass removes job/process entries and writes stalled without updating the tracker (runner/modules/stall_detection/__init__.py:76–90). Under the proposed helper, the awakened worker classifies that removal as cancellation and skips its tracker completion. For Linear dispatch this skips _mark_issue_review, which currently clears self.dispatched and moves the issue to In Review (Linear:569–582), leaving the issue In Progress after its process has stopped.",
   "fix": "Preserve an explicit termination reason and completion owner instead of inferring cancellation from absence. Ensure stalled runs retain their terminal record while still completing tracker and dispatch cleanup. Add a stall-to-worker-completion regression case."
  },
  {
   "id": "WS-008",
   "severity": "low",
   "path": "docs/exec-plans/active/2026-10-15-runner-write-safety.md:60",
   "evidence": "The stated plain-iteration fallback does not support existing stderr doubles. FakeProc.stderr in tests/test_dsh_backend.py:56–61 exposes only read(), with neither fileno nor iteration; tests/test_reset_gen.py:94 has the same shape. Applying that fallback to _iter_pipe_chunks raises TypeError and loses stderr diagnostics required by test_final_then_exit1_is_error and test_failed_resume_has_no_fallback.",
   "fix": "Specify separate fallback behavior: iteration for iterator stdout doubles, and read() for finite read-only stderr doubles. Handle fileno implementations that raise UnsupportedOperation as well as an absent method."
  }
 ],
 "coverage": [
  "Verified the plan SHA256 matches 60ea10bc79e5d7303325aeadb402554298e52d7fc7794a61eb8a6eaaabc2ed27.",
  "Checked all five prior findings against the revised approach and relevant implementation paths.",
  "Traced dashboard, retry and Linear launches, process registration, cancellation, terminal records and latest-record selection.",
  "Inspected the stall writer and Linear tracker/dispatch cleanup beyond the plan's changed-file list.",
  "Reviewed atomic cache publication and consumption, stream-reader behavior, relevant test doubles and SPEC.md requirements.",
  "Rechecked BUILD-009 and BUILD-017 helpers; retained the prior conclusions without reopening their accepted behavior."
 ],
 "limitations": [
  "Static plan/source review only; no edits, tests, service changes or delegation.",
  "Implementation and the claimed test baseline remain unverified.",
  "Accepted escaped-descendant, inherited-stderr and process-group reuse risks were not reopened."
 ]
}
```

### Dispositions
Round 2 dispositions (host: Claude). All four findings verified against the code and accepted; plan revised (Approach step 3 fallback, step 9 rewritten, Risks, Verification, Checklist, Acceptance).

- WS-004 accepted: replaced the flag check with a launch handshake. `_register_proc(run_id, proc)` under `_JOB_LOCK` registers the proc only while the job entry still exists; otherwise it kills the group at once and returns False, and the caller reaps and ends without reading output. Used at all four launch sites incl. the retry fallback (`_dispatch_cmd`). The pre-fallback membership check is only an early-out. Deterministic launch-race tests (patched Popen removes the job) for first launch and fallback.
- WS-006 accepted: `_end_job(run_id)` pops job and proc together under `_JOB_LOCK` and returns ownership; it replaces the paired pops at every worker terminal point. Cancel pops both under the same lock and 404s when no job was popped. Test: DELETE after `_end_job` returns 404 and the worker record is the only terminal one.
- WS-007 accepted: ownership is no longer inferred as "cancelled". A non-owner worker skips only its run-log record, Linear run comment and run_state_change/run_logged emits; tracker cleanup (`_mark_issue_review` / retry `_finish` review push) always runs. The stall pass's non-project branch pops both entries under `_app._JOB_LOCK` and uses `_kill_group`. Stall-then-worker regression test added.
- WS-008 accepted: descriptor detection treats a missing `fileno` or one raising io.UnsupportedOperation/ValueError/OSError as "no fd"; then `_iter_pipe_lines` iterates and `_iter_pipe_chunks` yields `pipe.read()` once.

## Plan review round 3

- Result: `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/rws/review3/claudex-vx3fh6g3/result.json`
- Verdict: **REVISE**, 2 findings (WS-009, WS-010 medium). Earlier findings incorporated.

```json
{
 "verdict": "REVISE",
 "summary": "The prior corrections are incorporated. Two defects remain in the revised ownership and tracker-cleanup approach.",
 "findings": [
  {
   "id": "WS-009",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-15-runner-write-safety.md:86",
   "evidence": "Calling _end_job at every normal and error terminal point loses a worker's existing ownership during exception recovery. For example, normal completion claims ownership, then _write_run_log raises before appending. The surrounding handler (app.py:2994–2999 or 3079–3084) calls _end_job again, which returns False because this worker already removed the job. The proposed non-owner rule then suppresses the error record and reports cancellation despite no cancel or stall. _write_run_log performs multiple fallible filesystem operations (app.py:1931–1991).",
   "fix": "Claim completion once and retain that ownership through persistence and error recovery. Distinguish an existing worker claim from another party's claim. Add a one-shot persistence-failure case verifying that recovery does not become cancellation or silently omit the terminal record."
  },
  {
   "id": "WS-010",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-15-runner-write-safety.md:91",
   "evidence": "Unconditional tracker cleanup by a non-owner worker can overwrite a newer run's state. Cancel run A, start retry B for the same issue, then let A's delayed reader/worker finish. B reuses the current reset generation (app.py:3559) and pushes running at line 3595. A's prescribed cleanup subsequently pushes review through _finish or _mark_issue_review. Their generation checks still pass, so the issue becomes In Review while B is running. Linear push_state also unconditionally clears self.dispatched on review (Linear:1215–1248).",
   "fix": "Make tracker cleanup conditional on the ending run still owning that issue's execution state. Check run identity when updating the cache, clearing dispatch ownership and applying queued tracker pushes; reset generation alone is insufficient. Test cancelling A, starting B without a reset, then releasing A's delayed cleanup and verifying B remains In Progress."
  }
 ],
 "coverage": [
  "Verified plan SHA256 22a50502c2f8f629977c40b31b0840b4366c960e5d4d47b982fab4db95920c55.",
  "Checked prior findings against the revised launch handshake, paired finalization, stall cleanup and descriptor fallbacks.",
  "Traced dashboard, retry and Linear terminal branches, including exception recovery and terminal-record persistence.",
  "Inspected stall snapshots, maintenance accounting, tracker cache updates, dispatch removal and asynchronous tracker writers.",
  "Rechecked atomic cache publication/consumption and the unchanged BUILD-009/BUILD-017 helpers and relevant test sources.",
  "Checked relevant SPEC.md record and lifecycle requirements."
 ],
 "limitations": [
  "Static review only; no files edited, tests run, services changed or work delegated.",
  "The proposed helpers and regression cases are not implemented; runtime behavior and the claimed baseline remain unverified.",
  "Previously accepted escaped-descendant, inherited-stderr, empty-directory replacement and process-group reuse risks were not reopened."
 ]
}
```

### Dispositions
Round 3 dispositions (host: Claude). Both findings verified and accepted; plan revised (step 9, Verification, Checklist, Acceptance).

- WS-009 accepted: each worker claims once through a local `end()` that calls `_end_job` only while its local `owner` is None; normal, timeout and error branches all call `end()`, so a persistence failure after a successful claim reaches the error handler with owner=True and writes the error record as owner. Test: one-shot `_write_run_log` failure.
- WS-010 accepted, resolved by narrowing rather than adding run-identity checks to the tracker: the party that ends a run does every terminal side effect (record, tracker push, emits) and nobody else does. A non-owner worker now skips all of them, including `_mark_issue_review` and the retry `_finish` review push. The stall pass, as owner, now pushes Linear `review` itself (push_state("review") clears `dispatched`), which keeps WS-007 fixed without non-owner cleanup. Cancel/stall push at end time, before any new retry B can start (the run is no longer live), so A's late worker cannot touch B. Test: cancel A, start B without reset, release A; B stays running and owns `dispatched`.

## Plan review round 4

- Result: `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/rws/review4/claudex-sv3plbc8/result.json`
- Verdict: **REVISE**, 1 finding (WS-010 medium, ordering of owner pushes). WS-009 resolved.

```json
{
 "verdict": "REVISE",
 "summary": "WS-009 is resolved at the plan level. WS-010 remains: restricting side effects to the owner does not order those effects against a newer run.",
 "findings": [
  {
   "id": "WS-010",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-15-runner-write-safety.md:93",
   "evidence": "The claimed ordering is not established. Cancel removes entries under _JOB_LOCK, then signals, logs and pushes review outside that lock (plan:90). Pause cancellation A after its record is appended but before its review push; retry B can read that record, launch and push running. Retry has no admission barrier here—app.py:3530–3531 merely executes pass. Resuming A then overwrites B's state with review and clears dispatched. Independently, push_state launches separate _push_sync threads (Linear:1230–1248), whose execution order is not guaranteed; their reset-generation check cannot distinguish successive retries sharing a generation. Suppressing A's non-owner worker therefore fixes only one source of stale updates.",
   "fix": "Order issue-run admission against terminal effects and queued tracker writes, or attach a run identity/version that is checked before cache updates, dispatch removal and persisted tracker updates, including _push_sync. Extend verification to delay A's owning cancel/stall handler before its push, and to apply A's queued review after B's running push; B must remain running."
  }
 ],
 "coverage": [
  "Verified plan SHA256 05a8579edcfe12b330f3bc266b535abe62aaf46eb646a2d1df2906b19065dad5.",
  "Checked the claim-once correction against normal completion, persistence and exception-recovery branches.",
  "Traced cancellation, stall ownership, retry admission, tracker cache/dispatch changes and asynchronous Linear/local tracker writers.",
  "Rechecked cache publication/consumption, BUILD-009/BUILD-017 helpers and relevant SPEC.md lifecycle requirements.",
  "Retained prior resolved findings without reopening their accepted behavior."
 ],
 "limitations": [
  "Static review only; no edits, tests, service changes or delegation.",
  "The proposed implementation and claimed test baseline remain unverified.",
  "Previously accepted process-group, escaped-descendant, inherited-stderr and empty-directory replacement risks were not reopened."
 ]
}
```

### Dispositions
Round 4 dispositions (host: Claude). WS-010 verified and accepted; added Approach step 10, two tests, checklist and acceptance items.

- WS-010 accepted with a run identity on tracker pushes rather than an admission barrier: `push_state` and `_push_linear_state_async` take an optional `run_id`; the Linear module keeps `issue_run[issue_id]`; under `reset_gen.issue_lock`, a `running` push with a run_id claims the issue and any push whose run_id differs from the current claim is dropped, checked in `push_state` (cache + dispatched removal) and again in `_push_sync` (persisted write). All run-scoped pushes pass their run (Linear dispatch running/_mark_issue_review, retry running/_finish, cancel and stall review); pushes without run_id (manual moves, resets) are unchanged. B claims in its launch thread before its process starts, so A's review loses in both orders. Tests: A's cancel paused before its push while B claims then resumes; A's _push_sync reordered after B's. Known ceiling: issue_run is never pruned (one entry per issue).

## Plan review round 5

- Result: `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/rws/review5/claudex-n_pdi1pm/result.json`
- Verdict: **REVISE**, 2 findings (WS-010 _mark_issue_review pre-guard mutation; WS-011 same-run reorder).

```json
{
 "verdict": "REVISE",
 "summary": "Run identity addresses the previously reported delayed-owner cases, but a caller still mutates shared state before the guard, and writes within one run remain unordered.",
 "findings": [
  {
   "id": "WS-010",
   "severity": "medium",
   "path": "runner/modules/linear/__init__.py:567",
   "evidence": "The plan checks run identity in push_state and _push_sync, but _mark_issue_review directly sets issues_cache to In Review, removes dispatched and emits before calling push_state (lines 576–582). If owning worker A pauses before this helper and retry B claims the issue, A can still overwrite B's cache and dispatch entry before its nested push is rejected. Passing run_id through the helper alone does not protect these earlier mutations.",
   "fix": "Check run identity inside _mark_issue_review under the issue lock before any mutation or emit, or consolidate its mutations into the guarded push_state path. Add a delayed owning-worker test that starts B before releasing A's _mark_issue_review."
  },
  {
   "id": "WS-011",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-15-runner-write-safety.md:104",
   "evidence": "Run identity cannot order two updates from the same run. push_state starts an independent _push_sync thread for each update (Linear:1230–1248). A fast run can queue running and then review; if review persists first and the delayed running thread executes afterward, both match issue_run and the reset generation. The persisted tracker returns to In Progress after completion. The proposed reordered-write test uses different runs and misses this case.",
   "fix": "Add ordering within each issue's updates, such as a push sequence checked before persistence or an ordered queue. A superseded running write must be rejected even when its run_id still matches. Test one run whose queued running write executes after its terminal review write."
  }
 ],
 "coverage": [
  "Verified plan SHA256 4af1777ce2eb9c89251caecc45c3d81ca43e1c6ac464755a9f5418ab977a465d.",
  "Compared the new run-identity approach with prior findings and regression scenarios.",
  "Traced tracker push callers across retry, cancellation, Linear dispatch and project-bound paths.",
  "Inspected direct cache/dispatch writers, asynchronous persistence, reset-generation locking and local/remote tracker branches.",
  "Rechecked claim-once handling and BUILD-009; retained prior conclusions on unchanged cache publication and BUILD-017."
 ],
 "limitations": [
  "Static review only; no edits, tests, service changes or delegation.",
  "Proposed behavior and the claimed test baseline remain unverified.",
  "Previously accepted risks were not reopened."
 ]
}
```

### Dispositions
Round 5 dispositions (host: Claude). Both verified and accepted; Approach step 10 extended, two tests, checklist and acceptance items added.

- WS-010 (_mark_issue_review) accepted: `_mark_issue_review(issue_id, gen, run_id=None)` performs the run-identity check first inside its existing issue_lock, before touching issues_cache, dispatched or emitting; a mismatched run returns untouched. Test: owning worker A paused before _mark_issue_review, B claims, A released; B's cache/dispatch/emits unchanged.
- WS-011 accepted: per-issue push sequence. `push_state` bumps `push_seq[issue_id]` under the issue lock and hands the number to `_push_sync`, which drops its write unless it is still the latest; `_push_sync` already holds the issue lock for the whole write, so check+write are atomic. Only the newest queued push persists, for pushes with or without run_id. Test: same-run running queued after review is dropped; persisted state stays review.

## Plan review round 6

- Result: `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/rws/review6/claudex-tnf8rdox/result.json`
- Verdict: **REVISE**, 1 finding (WS-012 medium). Round-5 fixes accepted.

```json
{
 "verdict": "REVISE",
 "summary": "The round-5 fixes address their reported scenarios. Another tracker writer bypasses the proposed ordering mechanism.",
 "findings": [
  {
   "id": "WS-012",
   "severity": "medium",
   "path": "runner/modules/linear/__init__.py:1164",
   "evidence": "push_seq covers push_state/_push_sync, but PATCH dispatch also queues _linear_sync_patch, which checks only reset generation before writing state. The In Progress route starts dispatch and queues this separate sync at lines 989–995. A fast run can persist review before that delayed sync writes its original In Progress state, violating the ordering acceptance criterion. Direct PATCH writes also bypass sequence invalidation: queue an old running push, PATCH the issue to Done through the local route (lines 949–965), then release the queued push. Done does not bump reset generation (lines 242–244), so the old push still passes both proposed guards and overwrites Done.",
   "fix": "Share the issue-state sequence across direct PATCH mutations and _linear_sync_patch, as well as push_state. Allocate the sequence when accepting each state change and reject superseded asynchronous state writes under the issue lock, while preserving metadata-only edits. Add delayed PATCH-sync and manual-Done regression cases."
  }
 ],
 "coverage": [
  "Verified plan SHA256 862c2c5e4196f8029085d34f8db8307cddc7e12b4465dccfcc75acc47dd37a7f.",
  "Checked the early _mark_issue_review guard and sequence proposal against the prior findings.",
  "Traced shared tracker writers beyond push_state: local and remote PATCH routes, dispatch-triggered _linear_sync_patch, local persistence and reset-generation handling.",
  "Rechecked run-scoped callers, claim-once handling, atomic cache helpers and BUILD-009/BUILD-017 sources and relevant test definitions.",
  "Retained prior resolved findings without reopening accepted behavior."
 ],
 "limitations": [
  "Static review only; no edits, tests, service changes or delegation.",
  "The proposed implementation and claimed test baseline remain unverified.",
  "Previously accepted risks were not reopened."
 ]
}
```

### Dispositions
Round 6 dispositions (host: Claude, scope decision).

- WS-012 verified (PATCH dispatch's _linear_sync_patch and direct PATCH writes bypass the proposed sequence; manual Done does not bump the reset generation). Not fixed here: deferred together with the WS-010 owner-push ordering and WS-011 to a new plan, docs/exec-plans/active/2026-10-15-tracker-write-ordering.md, which carries all three findings, the draft approach from rounds 4–5 and the tests.
- Reason: rounds 4–6 show per-issue tracker write ordering is a design of its own that spans every tracker writer (push_state, _push_sync, _mark_issue_review, PATCH routes, _linear_sync_patch). The race predates this plan: today cancel already pushes review asynchronously and nothing orders it. This plan's goal is process groups, bounded readers, the cache publish, and the run lifecycle (cancel/stall/worker ownership). Removing Approach step 10 returns the tracker to today's ordering; nothing in this plan makes it worse.
- What this plan still guarantees for the tracker: a late non-owner worker makes no tracker write (owner-only side effects, WS-007 / late-worker part of WS-010), and the stall pass pushes review as owner. Acceptance items for cross-run and same-run push ordering were removed; the late non-owner test stays.
- Please review the remaining plan on its own scope. Do not re-raise tracker write-ordering findings here unless this plan's changes make an ordering strictly worse than today.

## Plan review round 7

- Result: `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/rws/review7/claudex-v1_1vrmb/result.json`
- Verdict: **REVISE**, 1 finding (WS-013 medium). Tracker-ordering deferral accepted as documented.

```json
{
 "verdict": "REVISE",
 "summary": "The tracker-ordering deferral is documented, but the new stall-owner push introduces a regression within the remaining scope.",
 "findings": [
  {
   "id": "WS-013",
   "severity": "medium",
   "path": "runner/modules/stall_detection/__init__.py:76",
   "evidence": "Approach step 9 adds _push_linear_state_async(issue_id, \"review\") without a generation. Reset an active issue to Todo, then let its old run stall. Today the stall pass makes no tracker push, and the worker's completion checks its launch generation (Linear _mark_issue_review at lines 567–582; retry _finish at app.py:3584–3591), preserving Todo. The proposed stall push uses gen=None, which reset_gen.is_current accepts unconditionally, and moves the reset issue back to In Review. For Linear-dispatched runs it also bypasses _mark_issue_review's existing Done/Canceled/Duplicate protection. This makes tracker behavior strictly worse than today.",
   "fix": "Preserve the displaced worker's tracker guards when transferring completion to the stall owner. Store the launch generation in the job and use it for the stall push; retain the existing terminal-state protection for Linear-dispatched runs. Add reset-then-stall and terminal-state-then-stall cases asserting that tracker state remains unchanged."
  }
 ],
 "coverage": [
  "Verified plan SHA256 7ac9cc932fa2f24c3613074f0e81988008242996c955f878b799e955b0a29ba0.",
  "Confirmed the separate plan carries deferred WS-010 owner-push ordering, WS-011 and WS-012.",
  "Traced dashboard, retry, Linear and stall job/proc ownership, timeout cleanup and tracker completion guards.",
  "Reviewed atomic cache publication and its reader, counted-thread cleanup, relocation rename calls and relevant test definitions.",
  "Retained previously resolved findings and accepted risks without reopening them."
 ],
 "limitations": [
  "Static plan review only; no files edited, tests run, services changed or delegation performed.",
  "Implementation and the claimed test baseline remain unverified.",
  "General tracker write ordering remains unresolved in the explicitly deferred plan."
 ]
}
```

### Dispositions
Round 7 dispositions (host: Claude). WS-013 verified and accepted.

- WS-013: the stall pass no longer pushes an unguarded review. Linear dispatch and retry store their launch generation in the job entry as `launch_gen`; the stall pass, as owner of a Linear-linked run with `launch_gen`, completes the tracker through the Linear module's `_mark_issue_review(issue_id, gen=launch_gen)`, which keeps the displaced worker's guards (reset since launch → untouched; Done/Canceled/Duplicate → untouched; otherwise In Review and dispatched cleared). A job without launch_gen gets no stall push, as today. For retry runs this adds terminal-state protection relative to the worker's `_finish` push. Tests added: reset-then-stall stays Todo; Done-then-stall stays Done.

## Plan review round 8

- Result: `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/rws/review8/claudex-rp5u9b0s/result.json`
- Verdict: **APPROVED**, no findings. Approved plan SHA256: 0ce298f7b03e4d32707a4a6154e70e601092aa2298317fde4627e355236cde04. `runner.py check`: "Approval matches the current plan; assurance=cross_provider."
- Limitations: static review only; tracker write ordering deferred to 2026-10-15-tracker-write-ordering.md; accepted risks remain.

## Build (Claude)
- Base: commit below (plan + tracker plan committed before any code change).
