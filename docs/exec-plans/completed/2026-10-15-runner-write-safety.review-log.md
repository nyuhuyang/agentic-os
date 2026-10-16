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
- Base: `7c519f1`. Builder: Claude (host session).
- Proof: 433 passed (410 + 23 new). Pre-build code: 19/23 new tests fail, 4 are regression guards.
- Runner restarted 18:42; `/api/maintenance` → inflight 0.
- Public-repo check found two pre-existing doc leaks (completed multi-project-dispatch plan evidence line; this plan's own check line, which spelled out the pattern); both scrubbed. The names remain in the history of unpushed commit e738a77 — user decision pending.

## Inspection 1 (fresh Codex)

- Result: `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/rws/inspect1/claudex-28winedy/result.json`
- Verdict: **REVISE**, 4 findings (RWS-001..004 medium). BUILD-009 and BUILD-017: reviewed, no material defect.

```json
{
 "verdict": "REVISE",
 "summary": "The cache publication and process registration changes match the plan, but four lifecycle and recovery defects remain.",
 "findings": [
  {
   "id": "RWS-001",
   "severity": "medium",
   "path": "runner/modules/linear/__init__.py:672",
   "evidence": "Pause dispatch after publishing _running_jobs at line 662, then cancel that run. Cancellation removes the job and pushes review. When dispatch resumes, it still pushes running and emits the running event. Registration subsequently rejects and kills the process, and the new non-owner branch skips completion. The issue remains In Progress without a running agent. This occurs with synchronous tracker writes and no subsequent run, independently of the deferred tracker-ordering races.",
   "fix": "Order initial running publication and emission against cancellation/stall ownership. A successful cancellation must prevent subsequent startup writes from that worker. Add a deterministic cancellation case paused between job publication and the initial running push."
  },
  {
   "id": "RWS-002",
   "severity": "medium",
   "path": "runner/app.py:3601",
   "evidence": "Cancellation writes no agent, model, task_id, parent_run_id, attempt or reset_generation; the stall writer at runner/modules/stall_detection/__init__.py:84 has the same omissions. Now that workers correctly suppress their later records, these incomplete records remain authoritative. For example, cancel Codex retry B belonging to task A: _write_run_log defaults task_id to B, ancestry disappears, and retrying B can select the configured default Claude because neither its record nor _get_task_agent_lock(B) supplies an agent.",
   "fix": "Store execution and ancestry metadata in each job and carry it into the cancellation/stall owner's terminal record. Preserve the root task, parent, attempt, agent/model and launch generation. Cover retrying a cancelled or stalled retry and retrieving its history."
  },
  {
   "id": "RWS-003",
   "severity": "medium",
   "path": "runner/modules/stall_detection/__init__.py:84",
   "evidence": "Cancel and stall remove both live entries before persistence but have no ownership-preserving recovery if _write_run_log raises before appending. A one-shot write failure leaves no terminal record: the displaced worker now sees _end_job return False and writes nothing. In the stall path, the exception also escapes run_pass, which catches only MaintenanceRefused, terminating the watchdog thread and preventing future stall checks. The new persistence-failure test exercises only worker ownership.",
   "fix": "Retain recoverable finalization ownership and metadata until terminal persistence succeeds, without making the run launchable again. Add owner-side error recovery for cancellation/stall and isolate watchdog failures so subsequent passes continue. Cover one-shot persistence failures in both paths."
  },
  {
   "id": "RWS-004",
   "severity": "medium",
   "path": "runner/app.py:2436",
   "evidence": "Reader creation occurs before the cleanup try block. If the DSH stdout reader starts but constructing or starting the stderr reader fails, _start_counted releases only the failed reader's reservation. The exception reaches the worker's generic handler, which removes the process entry and logs error without killing the child or stopping the first reader. That reader can retain its in-flight slot indefinitely. Failure to start the sole text/Claude reader similarly leaves the spawned child running without a registered job.",
   "fix": "Create readers incrementally inside a cleanup-protected block. On startup failure, set stop, kill and reap the process group, and join every reader already started before propagating the error. Add an integration case where the second reader fails to start; the helper-only BUILD-009 tests do not cover this."
  }
 ],
 "coverage": [
  "Verified the supplied plan SHA256 and all seven changed-file digests against the manifest; inspected the changed code, tests and documentation.",
  "Traced dashboard, retry/fallback, Linear dispatch, cancellation and stall ownership through job/process registration, terminal persistence and tracker side effects.",
  "Inspected related registry consumption, state_io helpers, reset-generation handling, run-log readers, task/session locking, retry history and dashboard metadata consumers.",
  "Reviewed all three streaming implementations, non-streaming timeout cleanup, process-group signaling and maintenance accounting.",
  "Reviewed BUILD-009 construction/start exception handling and its existing test sources. The helper releases its failed reservation correctly; RWS-004 concerns caller cleanup.",
  "Reviewed BUILD-017 rename_dir, move/rollback callers and destination-race test source; no material defect found in that fix."
 ],
 "limitations": [
  "Static review only: no files edited, tests executed, services changed or work delegated. The reported 433 passing tests and restart result were not independently verified.",
  "The graph is older than these changes; conclusions were checked against current source.",
  "General tracker-write ordering and unchanged project-run lifecycle remain outside this change's scope. Documented escaped-descendant, inherited-stderr, process-group reuse and empty-directory replacement risks remain."
 ]
}
```

### Dispositions and fixes
Fix handoff after inspection 1 (builder: Claude). Base remains 7c519f1; this is a fresh full inspection of the whole build.

Inspection 1 found RWS-001..004 (all medium); all accepted and fixed. BUILD-009 and BUILD-017 were reviewed in inspection 1 with no material defect.
- RWS-001: Linear `_dispatch_issue_counted` now pushes `running` and emits before publishing `_running_jobs[run_id]`; a cancel/stall can only end the run after that push, so its `review` cannot be followed by this `running` (same order the retry path already used). Test: test_linear_running_push_cannot_follow_a_cancel (cancels at the running push if the job were already published).
- RWS-002: each job carries `record` launch metadata (/run: agent[, model, task_id]; retry: attempt, parent_run_id, agent, model, task_id, reset_generation; Linear: agent, model, task_id, selected_skill, reset_generation). New `_write_owner_record(run_id, job, status, error)` writes cancel/stall records with it. Test: cancel and stall of a codex retry keep agent/task_id/parent_run_id/attempt.
- RWS-003: `_write_owner_record` tries the write twice (logging each failure); the stall pass handles each job in `_stall(...)` inside a per-job try/except, so one failing job never kills the watchdog. Tests: one-shot write failure for cancel and stall; a failing job x does not stop job y. Declined part: keeping a recoverable ownership state beyond two attempts — a persistent disk failure cannot be recovered by the runner; it is logged.
- RWS-004: in all three readers the `_start_counted` calls moved inside the cleanup try; any BaseException there runs `_timeout_cleanup` (stop, kill group, reap, join started readers) and re-raises. Test: failing first reader (text/Claude/dsh) and second reader (dsh) leaves no child, no live reader and inflight unchanged.

Proof: 443 passed. The 10 new tests fail on the pre-fix build.

## Inspection 2 (fresh Codex)

- Result: `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/rws/inspect2/claudex-8iei0hug/result.json`
- Verdict: **REVISE**, 4 findings (RWS-005..008 medium).

```json
{
 "verdict": "REVISE",
 "summary": "The main ownership and timeout changes match the plan, but four cleanup and recovery gaps remain.",
 "findings": [
  {
   "id": "RWS-005",
   "severity": "medium",
   "path": "runner/app.py:3813",
   "evidence": "_dispatch_cmd removes its process entry while the job remains live. Suppose a resumed command starts a background descendant with stdout/stderr redirected, then exits unsuccessfully. Cancel between _dispatch_cmd returning and the fallback decision: DELETE finds the job but no process, writes cancelled, and prevents the fallback. The original group's descendant survives because cancellation has lost its process-group handle. This defeats the explicit requirement to kill descendants even after their leader exits.",
   "fix": "Retain process-group ownership until finalization, or terminate each attempt's remaining group before removing its handle. Handle replacement during fallback must preserve cancellation coverage. Add a cancellation case between attempts with a surviving descendant."
  },
  {
   "id": "RWS-006",
   "severity": "medium",
   "path": "runner/app.py:3881",
   "evidence": "A retry timeout calls end(), removing both live entries, and then writes its timeout record inside an except handler. If that write raises once before appending, the sibling generic except cannot catch it. The thread exits without a terminal record or _finish(), leaving its tracker issue In Progress with no live job. The same gap exists in the dashboard timeout handlers and Linear's timeout handler at runner/modules/linear/__init__.py:749. The persistence-recovery test only fails a normal review write.",
   "fix": "Put terminal persistence and recovery behind a common exception boundary that also covers timeout/error handlers, retaining the existing ownership claim and metadata. Cover a one-shot record-write failure following an actual timeout."
  },
  {
   "id": "RWS-007",
   "severity": "medium",
   "path": "runner/modules/linear/__init__.py:664",
   "evidence": "The reordered initial push runs before job publication and outside the inner finalization try. push_state updates issues_cache, then calls _start_counted at line 1246, which can raise RuntimeError when Thread.start fails. The outer handler only logs and emits an unrelated random run id. dispatched remains populated, the issue remains In Progress, no process starts, and no job exists for the watchdog to recover. A one-shot thread-start failure is sufficient; this is independent of deferred tracker-write ordering.",
   "fix": "Make initial state publication failure-safe while preserving its ordering before cancellation becomes available. On failure, finalize the actual run, clear its dispatch entry, and restore or complete the tracker state. Add a failure case for starting the initial tracker-push thread."
  },
  {
   "id": "RWS-008",
   "severity": "medium",
   "path": "runner/app.py:2409",
   "evidence": "All three streaming helpers still create RUN_PROGRESS_DIR before entering their cleanup-protected try blocks (also lines 781 and 2338). If directory creation raises after Popen—for example, ENOSPC or an invalid logs path—the exception reaches a generic worker handler that retires the job/process entries without killing the launched group. The agent continues running and subsequent DELETE returns 404. The RWS-004 tests inject only _start_counted failures, after this unprotected setup.",
   "fix": "Protect every post-launch setup operation with group cleanup, either in the streaming helpers or a caller-level process lifecycle guard. Add a progress-directory setup failure case and verify that the child is killed and reaped."
  }
 ],
 "coverage": [
  "Verified the supplied plan hash, all seven changed-file hashes, and tracked diff hash against the manifest.",
  "Inspected changed implementation, test sources, documentation changes, review history, and host dispositions.",
  "Traced dashboard, retry/fallback, Linear, cancellation and stall lifecycle paths through registration, ownership, persistence and tracker completion.",
  "Inspected related registry consumption, state_io helpers, run_skill logging, reset generations, local tracker writes, run-log readers, task locking and retry history.",
  "Reviewed all three streaming readers, non-streaming timeout cleanup and maintenance accounting.",
  "Explicitly reviewed BUILD-009 thread construction/start cleanup and BUILD-017 rename_dir with move/rollback callers and existing test sources; no material defect found in those two fixes."
 ],
 "limitations": [
  "Static review only: no files edited, tests executed, services changed or work delegated. The reported 443 passing tests and restart result were not independently verified.",
  "Fidelity was assessed against the supplied plan and inspected source; no full SPEC.md audit was performed.",
  "The graph predates these changes; relevant relationships were checked against current source.",
  "General tracker-write ordering remains explicitly deferred. Documented escaped-process, inherited-stderr, process-group reuse and empty-directory replacement risks remain."
 ]
}
```

### Dispositions and fixes
Fix handoff after inspection 2 (builder: Claude). Base remains 7c519f1; fresh full inspection of the whole build.

Inspection 2 found RWS-005..008 (all medium); all accepted and fixed at a shared point rather than per site:
- RWS-005: `_dispatch_cmd` no longer drops its handle in a finally. The handle stays registered until `_end_job` (run end) or until `_register_proc` replaces it for the next attempt — and `_register_proc` now kills the replaced attempt's group. A cancel or stall between attempts therefore still reaches the first group's leftovers. Test: cancel exactly at the fallback decision (after attempt 1 returned) → attempt 1's process is signalled, no fallback, record cancelled.
- RWS-006: new `_write_run_log_retrying` (two attempts, logs, never raises). All timeout/error/CLI-not-found handlers in /run, retry and Linear use it, and `_write_owner_record` is built on it. Normal-path writes still use `_write_run_log`, so a failure there still reaches the error handler with the claim kept (WS-009). Test: one-shot failure of the timeout record after a real timeout path → record written, tracker In Review.
- RWS-007: Linear's initial `running` push/emit is wrapped; on failure the run is finished in place: `dispatched` cleared, error record (retrying writer), guarded `_mark_issue_review`; no job is published and nothing is launched. Test: push_state("running") raises → no launch, no job, not dispatched, error record.
- RWS-008: every generic `except Exception` after launch kills the group first (/run entrypoint and agent handlers; Linear handler); retry `_dispatch_cmd` kills and reaps its group on any BaseException after registration. This covers the RUN_PROGRESS_DIR mkdir and any other post-launch setup. Test: RUN_PROGRESS_DIR under a regular file → launched `sleep 60` is dead after retry and after /run.
- Also hardened: the reader timeout branch tolerates a reader that never started (`[t] if t else []`).

Proof: 448 passed. The 5 new tests fail on the pre-fix build.

## Inspection 3 (fresh Codex)

- Result: `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/rws/inspect3/claudex-qj8q_wfl/result.json`
- Verdict: **REVISE**, 2 findings (RWS-009, RWS-010 medium).

```json
{
 "verdict": "REVISE",
 "summary": "Two cleanup gaps remain: buffered output can delay reader shutdown, and post-launch error handlers do not consistently reap killed processes.",
 "findings": [
  {
   "id": "RWS-009",
   "severity": "medium",
   "path": "runner/app.py:753",
   "evidence": "_iter_pipe_lines checks stop only when requesting another chunk. One 65,536-byte read can contain thousands of lines, all yielded after stop is set. Each consumed line can flush a log and persist progress JSON. A burst near the deadline can therefore keep the reader working beyond _timeout_cleanup's two-second join, retaining its _INFLIGHT slot after the timeout handler returns. The escaped-descendant tests exercise an idle reader and miss this case.",
   "fix": "Check stop before yielding each buffered line and before yielding the trailing fragment; discard pending output when stopping. Add a burst-output case with deliberately slowed progress persistence and verify that the reader exits and releases its reservation after timeout."
  },
  {
   "id": "RWS-010",
   "severity": "medium",
   "path": "runner/app.py:3159",
   "evidence": "The dashboard generic error handlers here and at line 3251, and Linear's handler at runner/modules/linear/__init__.py:765, signal the group but never wait for the leader. For example, a progress-directory setup failure after Popen kills the child and retires its registered handle without reaping it. If destruction occurs before the child exits, Python 3.12 retains the Popen in subprocess._active, whose cleanup depends on a later Popen; the exited child can remain a zombie meanwhile. test_a_setup_failure_after_launch_kills_the_agent calls poll(), which itself reaps the child and masks this omission.",
   "fix": "Use shared bounded kill-and-reap cleanup in every post-launch error handler, including the dashboard FileNotFoundError branch when a process already exists. Verify that production cleanup waits for the leader rather than relying on the test's poll() call."
  }
 ],
 "coverage": [
  "Verified the supplied plan hash, all seven changed-file hashes and tracked diff hash against the manifest.",
  "Reviewed changed implementation, test sources, documentation changes and prior review dispositions.",
  "Traced dashboard, retry/fallback, Linear, cancellation and stall paths through process registration, terminal ownership, persistence and tracker completion.",
  "Inspected related state_io helpers, run_skill registry consumption and state writers, reset generations, local tracker persistence, run-log readers and task/session locking.",
  "Reviewed all three streaming readers, non-streaming timeout cleanup and maintenance accounting.",
  "Explicitly reviewed BUILD-009 thread construction/start cleanup and BUILD-017 rename_dir, move/rollback callers and relevant test sources; no material defect found in those fixes."
 ],
 "limitations": [
  "Static review only: no edits, tests, service changes or delegation. The reported 448 passing tests and restart result were not independently verified.",
  "Fidelity was assessed against the supplied plan and inspected source; no full SPEC.md audit was performed.",
  "The graph predates the build, so conclusions were checked against current source. Deferred tracker-write ordering and documented accepted risks were not reopened."
 ]
}
```

### Dispositions and fixes
Fix handoff after inspection 3 (builder: Claude). Base remains 7c519f1; fresh full inspection of the whole build.

Inspection 3 found RWS-009 and RWS-010 (medium); both accepted and fixed:
- RWS-009: `_iter_pipe_lines` returns before yielding any further buffered line once `stop` is set, and drops the trailing fragment when stopping. Test: 2000 lines in one chunk; after the first line, stop → nothing more is yielded.
- RWS-010: new `_kill_and_reap(proc)` (group kill + bounded wait, exceptions suppressed). Used by every post-launch cleanup: /run timeout and generic handlers (both paths) and the CLI-not-found branch (proc may be None), Linear timeout/communicate-timeout/generic handlers, retry `_dispatch_cmd` (communicate timeout and BaseException), `_register_proc` rejection and `_timeout_cleanup`. Remaining bare `_kill_group` calls: cancel (followed by its own waits), the replaced earlier attempt's leftovers in `_register_proc` (its leader was already waited; the leftovers are not our children), and the retry timeout handler (the reader cleanup already reaped). The setup-failure test now asserts `returncode is not None` (set only by a wait) instead of calling poll().

Proof: 449 passed. Both tests fail on the pre-fix build ([run] variant and the buffered-lines test).

## Inspection 4 (fresh Codex)

- Result: `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/rws/inspect4/claudex-zlcpgpl0/result.json`
- Verdict: **REVISE**, 2 findings (RWS-011 medium, RWS-012 medium/test).

```json
{
 "verdict": "REVISE",
 "summary": "Two defects remain: fallback setup failures can orphan retry descendants, and a new regression test can deadlock on smaller pipes.",
 "findings": [
  {
   "id": "RWS-011",
   "severity": "medium",
   "path": "runner/app.py:3907",
   "evidence": "The retry worker's outer error handler retires the job without cleaning up its registered process group. For example, a resumed Codex attempt starts a background descendant with redirected stdout/stderr, then exits unsuccessfully. If fallback command construction fails while reading SKILL.md, or fallback cache publication raises ENOSPC, execution never reaches the protected portion of _dispatch_cmd. The outer handler calls end(), discards the first attempt's retained handle, and records error while its descendant survives. Subsequent cancellation returns 404.",
   "fix": "Retain the current attempt's handle locally and apply kill-and-reap cleanup to outer worker failures, including failures between attempts and before fallback registration. Add a regression case that fails fallback setup after an unsuccessful attempt leaves a same-group descendant."
  },
  {
   "id": "RWS-012",
   "severity": "medium",
   "path": "tests/test_runner_write_safety.py:529",
   "evidence": "The test performs a blocking 18,890-byte os.write before starting any reader. On a supported Linux environment with an 8 KiB pipe capacity, this write blocks indefinitely; execution never reaches _iter_pipe_lines. The regression test can therefore hang the full suite, although it succeeds on hosts with larger pipes.",
   "fix": "Use a regular temporary file with a real descriptor, or construct a payload guaranteed to fit the pipe before reading. Preserve the assertion that buffered lines are discarded after stop is set."
  }
 ],
 "coverage": [
  "Verified the plan hash, all seven changed-file hashes and tracked diff hash against the supplied manifest.",
  "Reviewed changed implementation, test sources, documentation changes and prior review dispositions.",
  "Traced dashboard, retry/fallback, Linear dispatch, cancellation and stall ownership through process registration, terminal persistence and tracker completion.",
  "Inspected related state_io helpers, run_skill registry consumption and state writers, reset generations, local tracker persistence, run-log readers, task/session locking and dashboard event consumers.",
  "Reviewed all three streaming readers, non-streaming timeout cleanup, process-group signaling and maintenance accounting.",
  "Explicitly reviewed BUILD-009 thread construction/start cleanup and its test sources; no material defect found in that helper.",
  "Explicitly reviewed BUILD-017 rename_dir, move/rollback callers and destination-race test source; no material defect found in that fix."
 ],
 "limitations": [
  "Static review only: no files edited, tests executed, services changed or work delegated. The reported 449 passing tests and restart result were not independently verified.",
  "Fidelity was assessed against the supplied plan and inspected source; no full SPEC.md audit was performed.",
  "General tracker-write ordering remains explicitly deferred. Documented escaped-descendant, inherited-stderr, process-group reuse and empty-directory replacement risks were not reopened."
 ]
}
```

### Dispositions and fixes
Fix handoff after inspection 4 (builder: Claude). Base remains 7c519f1; fresh full inspection of the whole build.

Inspection 4 found RWS-011 and RWS-012 (medium); both accepted and fixed:
- RWS-011: the retry worker's outer `except Exception` handler now calls `_kill_and_reap(_running_procs.get(new_run_id))` before `end()`, so a failure between attempts (fallback command construction, cache publication) still ends the registered attempt's group. Test: resume attempt fails (rc 1), the fallback `_ai_command` raises → the first attempt's process is signalled, one error record.
- RWS-012: `test_buffered_lines_stop_with_the_reader` writes the 2000-line burst to a temporary regular file and reads it through `_iter_pipe_lines` (select on a regular file is always ready), so no pipe capacity can block the write. The assertion is unchanged.

Proof: 450 passed. The RWS-011 test fails on the pre-fix build.

## Inspection 5 (fresh Codex)

- Result: `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/rws/inspect5/claudex-2xc8la73/result.json`
- **Failed: provider_unavailable** (Codex usage limit, resets 7:59 PM; fallback_eligible=true). Automatic fallback per policy: fresh same-provider (Claude) inspection, assurance=degraded_same_provider.

## Inspection 5b (fresh Claude, degraded fallback)
- Fallback launch refused by the runner ("Code changed after the failed primary inspection": the review-log append above changed the snapshot). Host decision: wait for the Codex reset (7:59 PM) and rerun the primary cross-provider inspection instead of a degraded one.

## Inspection 5 retry (fresh Codex, after quota reset)
- History rewrite (user-approved 2026-10-15: "之前那个 e738a77要改写历史把它们去掉"): the three unpushed commits e738a77, 5a28e45, 7c519f1 were rewritten with `git filter-branch --tree-filter` to remove two private names (one evidence line, one grep pattern). New SHAs 342cb2f, e59597d, 7b715a4; trees differ from the originals in exactly those two lines. Old objects pruned (stash, refs/original, reflog expired, gc). Inspection base is now `7b715a4`.

- Result: `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/rws/inspect5r/claudex-1co5gcul/result.json`
- Verdict: **REVISE** (cross_provider), 1 finding (RWS-013 medium).

```json
{
 "verdict": "REVISE",
 "summary": "One recovery gap remains: a transient local tracker-comment failure can strand a finished issue In Progress.",
 "findings": [
  {
   "id": "RWS-013",
   "severity": "medium",
   "path": "runner/app.py:3904",
   "evidence": "After a retry times out, end() removes its live entries and the timeout record is persisted. If _post_linear_comment then raises once, _finish(\"review\") is skipped; exceptions inside this except handler bypass the sibling error handler. LocalTracker.post_comment propagates tasks.json persistence errors. The issue remains In Progress without a live job for the watchdog to recover. The same gap exists in retry error handling and Linear dispatch's timeout/error handlers at runner/modules/linear/__init__.py:758 and :768.",
   "fix": "Isolate optional comment failures so owner-controlled tracker completion still runs, preserving generation guards. Add regression coverage for one-shot local-comment persistence failures in timeout and error paths."
  }
 ],
 "coverage": [
  "Verified the plan hash, all six manifest file hashes, and tracked diff hash.",
  "Reviewed changed implementation, test sources, plan and review dispositions.",
  "Traced dashboard, retry/fallback, Linear dispatch, cancel and stall process registration, ownership, cleanup and terminal effects.",
  "Inspected related atomic state helpers, run_skill registry consumption and state writes, reset guards, local tracker persistence, run-log consumers and dashboard event handling.",
  "Explicitly reviewed BUILD-009 thread construction/start cleanup and BUILD-017 rename_dir with move/rollback callers and relevant test sources; no material defects found in those fixes."
 ],
 "limitations": [
  "Static review only: no edits, tests, service changes or delegation. Reported test results were not independently verified.",
  "Spec fidelity was assessed against the supplied plan and inspected source; no full SPEC.md audit was performed.",
  "The graph predates this build; conclusions were checked against current source.",
  "Deferred tracker-write ordering and documented accepted process/pipe risks remain outside this review's approval scope."
 ]
}
```

### Dispositions and fixes
Fix handoff after inspection 5 (builder: Claude). Base 7b715a4 (7c519f1 before the user-approved history rewrite that removed private names; code identical). Fresh full inspection of the whole build.

Inspection 5 found RWS-013 (medium); accepted and fixed:
- New `_comment_quietly(post, *args)`: calls the comment poster, logs and swallows any exception. Every closing tracker comment in a terminal path uses it — retry normal/timeout/error (`_post_linear_comment`) and Linear normal/timeout/error (`self.post_comment`) — so the tracker completion after it (`_finish` / `_mark_issue_review`) always runs, with its generation guards unchanged. Test: one-shot comment failure on retry and Linear, timeout and error paths → ticket In Review, terminal record unchanged.

Proof: 454 passed. The 4 new cases fail on the pre-fix build.

## Inspection 6 (fresh Codex)

- Result: `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/rws/inspect6/claudex-erb4ywjn/result.json`
- Verdict: **REVISE** (cross_provider), 1 finding (RWS-014 medium; inspector notes it is pre-existing and adjacent). BUILD-009 and BUILD-017 re-reviewed: no material defect.

```json
{
 "verdict": "REVISE",
 "summary": "Closing-comment failures are isolated correctly, but feedback retries retain a startup failure path that can leave an issue In Progress without an agent.",
 "findings": [
  {
   "id": "RWS-014",
   "severity": "medium",
   "path": "runner/app.py:3782",
   "evidence": "Retry a linked run with a nonempty reply. After the running push succeeds, let the initial Human Feedback comment encounter a one-shot tasks.json persistence failure. LocalTracker.post_comment propagates that exception, and this unguarded call aborts the request before job publication at line 3790 or worker startup. The issue remains In Progress with no process, terminal record, or watchdog-visible job. The new comment-failure tests submit an empty request and skip this call.",
   "fix": "Isolate the optional initial feedback comment with _comment_quietly, or finalize startup failures through guarded cleanup. Add a reply-bearing retry case where the initial comment fails and verify that execution continues or the issue is completed cleanly."
  }
 ],
 "coverage": [
  "Verified the plan SHA256, all eight manifest file hashes, and tracked diff hash.",
  "Inspected every manifested file, including regression-test sources and review dispositions.",
  "Traced dashboard, retry/fallback, Linear, cancellation and stall lifecycle paths through registration, cleanup, terminal ownership and persistence.",
  "Inspected related registry consumption, atomic state helpers, run-log consumers, reset generations, tracker persistence and polling recovery.",
  "Reviewed BUILD-009 thread construction/start cleanup and existing test sources; no material defect found in that helper.",
  "Reviewed BUILD-017 rename_dir, move/rollback callers and destination-race test source; no material defect found in that fix."
 ],
 "limitations": [
  "Static review only: no edits, tests, service changes or delegation. Reported test results were not independently verified.",
  "RWS-014 is an existing adjacent startup defect, not a regression introduced by the closing-comment wrapper.",
  "Spec fidelity was assessed against the supplied plan and inspected source; no full SPEC.md audit was performed.",
  "The graph predates this build; relationships were checked against current source. Deferred tracker ordering and documented accepted process/pipe risks remain."
 ]
}
```

### Dispositions and fixes
Fix handoff after inspection 6 (builder: Claude). Base 7b715a4. Fresh full inspection of the whole build.

Inspection 6 found RWS-014 (medium, noted by the inspector as pre-existing and adjacent); accepted and fixed:
- The retry route's initial "Human Feedback" comment — both the project-bound branch (`project_runs.tracker_comment` body) and the plain branch — now goes through `_comment_quietly`, so a comment-persistence failure never aborts the request before job publication/worker start. Test: retry with a reply whose first comment fails once → the run launches and the ticket ends In Review.
- Left unchanged by plan scope: the project-run helper's own closing comment in `_run_project_ticket_locked` (project-run lifecycle is a declared non-goal).

NOT part of this build — please ignore: `docs/exec-plans/active/2026-10-15-dashboard-ui-updates.md` (modified) and `docs/exec-plans/active/2026-10-15-dashboard-ui-updates.review-log.md` (untracked). They belong to a separate concurrent session working on a different plan.

Proof: 455 passed. The new test fails on the pre-fix build.

## Inspection 7 (fresh Codex)

- Result: `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/rws/inspect7/claudex-onepd29e/result.json`
- Status: runner marked **failed** because the concurrent dashboard-plan documents changed during the run; the inspector reports the safety implementation hashes unchanged. Verdict in the response: **REVISE**, 2 findings (RWS-015, RWS-016 medium; both pre-existing adjacent). BUILD-009 and BUILD-017 re-reviewed: no material defect.

```json
{
 "verdict": "REVISE",
 "summary": "Two adjacent lifecycle gaps remain: retry startup can leave unowned state changes, and Linear routing timeouts can orphan descendants.",
 "findings": [
  {
   "id": "RWS-015",
   "severity": "medium",
   "path": "runner/app.py:3780",
   "evidence": "The initial retry running push remains outside startup recovery. LinearModule.push_state changes issues_cache to In Progress before calling _start_counted at linear/__init__.py:1254. If Thread.start raises once, the exception escapes the retry request before job publication at app.py:3791. Dispatch bookkeeping and cached running state remain, but no worker, terminal record or watchdog-visible job exists to finalize this attempted retry. RWS-007 handles this failure for Linear dispatch only; the new feedback-comment wrapper does not cover it. This is a pre-existing adjacent defect.",
   "fix": "Protect retry startup publication and worker scheduling with failure recovery. Clear dispatch bookkeeping, persist an error record with retry metadata, and restore or complete tracker state using the launch generation. Cover a one-shot initial tracker-thread start failure through the retry route."
  },
  {
   "id": "RWS-016",
   "severity": "medium",
   "path": "runner/modules/linear/__init__.py:645",
   "evidence": "Linear's skill-routing agent still runs through subprocess.run(timeout=60) without a new session or group cleanup. If that CLI starts an ordinary tool descendant and then times out, subprocess.run kills only the leader. The descendant survives while the handler selects _prompt and launches the main agent. It has no registered process handle, so cancellation and timeout cleanup for the main run cannot reach it. The same backend command builder enables tool execution for this routing call. This pre-existing caller remains outside the implemented timeout protection.",
   "fix": "Give the routing subprocess its own process group and apply bounded group-kill/reap cleanup on timeout and post-launch failure. Add coverage where routing times out after spawning a descendant that remains alive unless the group is killed."
  }
 ],
 "coverage": [
  "Verified the safety plan, changed runner implementations and new test file against their supplied SHA256 values.",
  "Inspected every manifested file, including both concurrent dashboard-plan documents and the safety review dispositions.",
  "Traced dashboard, retry/fallback, Linear routing/execution, cancellation and stall paths through process registration, ownership, persistence and tracker completion.",
  "Inspected related atomic state helpers, CLI registry consumption, shared log/state writers, run-history readers, reset generations, local tracker persistence and polling recovery.",
  "Reviewed all three streaming readers, non-streaming cleanup and maintenance accounting.",
  "Explicitly reviewed BUILD-009 thread construction/start cleanup and its test sources; no material defect found in that helper.",
  "Explicitly reviewed BUILD-017 os.rename, move/rollback callers and destination-race test source; no material defect found within the documented empty-directory behavior."
 ],
 "limitations": [
  "Static review only: no edits, tests, service changes or delegation. Reported test results were not independently verified.",
  "Both findings concern existing adjacent paths, rather than regressions introduced by the latest comment-wrapper fix.",
  "The two dashboard-plan documents changed concurrently and no longer matched the supplied manifest; the reviewed safety implementation hashes remained unchanged.",
  "Spec fidelity was assessed against the supplied plan and inspected source; SPEC.md was not inspected.",
  "The graph predates this build; relationships were checked against current source. Deferred tracker ordering and documented accepted process/pipe risks were not reopened."
 ]
}
```

- User decision (2026-10-15): fix both, then one more inspection ("修完再审一轮").

### Dispositions and fixes
Fix handoff after inspection 7 (builder: Claude). Base 7b715a4. Fresh full inspection of the whole build. The user decided this is the final planned inspection round (fix RWS-015/016, then one more inspection).

Inspection 7 found RWS-015 and RWS-016 (medium; the inspector noted both are pre-existing adjacent paths). Both accepted and fixed:
- RWS-015: the retry route defines `_start_failed(exc)`: logs, `_end_job(new_run_id)`, clears its own `_linear_dispatched` entry, writes an error record through `_write_run_log_retrying` with the retry metadata (attempt, parent_run_id, agent, model, task_id, reset_generation), pushes a guarded `review` (gen=_launch_gen, suppressed), returns 500. It wraps the initial `running` push in both the project-bound and plain branches, and the worker start (`_start_counted(_do_retry)` and the project `_start_counted(_run_project_ticket, ...)`). Test: push_state("running") raises once → 500, nothing launched, no job, dispatch cleared, ticket In Review, error record with parent/attempt.
- RWS-016: new `_run_grouped(cmd, timeout, **kw)` — a subprocess.run equivalent that starts the command in its own session and, on timeout or any failure, kills and reaps the whole group. Linear skill routing uses it (timeout 60, text=True). The two existing dsh routing tests (tests/test_dsh_backend.py) now stub `app._run_grouped` instead of `subprocess.run`, with the same assertions. Tests: `_run_grouped` timeout kills a background descendant; Linear routing calls `_run_grouped` with timeout 60.

NOT part of this build — please ignore: docs/exec-plans/active/2026-10-15-dashboard-ui-updates.md and its .review-log.md (a separate concurrent session; last modified 20:19, before this handoff).

Proof: 458 passed. The 3 new tests fail on the pre-fix build.

## Inspection 8 (fresh Codex, final planned round)

- Result: `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/rws/inspect8/claudex-fwvppfy5/result.json`
- Verdict: **REVISE** (cross_provider), 2 findings (RWS-017 high, RWS-018 medium; both regressions from the RWS-015 fix). BUILD-009/017 re-reviewed: no material defect.

```json
{
 "verdict": "REVISE",
 "summary": "Two defects remain in the new retry startup recovery: confidential-record safeguards are bypassed, and successful cancellation can be overwritten.",
 "findings": [
  {
   "id": "RWS-017",
   "severity": "high",
   "path": "runner/app.py:3766",
   "evidence": "_start_failed writes the complete retry prompt without checking the project's confidentiality or _records_unsafe(). Concrete scenario: start with an external RUN_LOG_PATH and a public project, then promote that project to confidential through the supported project route. Retry an existing bound run with sensitive feedback and let worker-thread creation fail. The new handler writes that feedback into the external log. Normal project finalization at lines 3056–3065 would withhold it. The startup error record also omits the project binding.",
   "fix": "Apply the project record-location and redaction policy to startup failures, including unknown confidentiality, and preserve binding metadata. Add a project-bound startup-failure case with unsafe record locations and sensitive feedback."
  },
  {
   "id": "RWS-018",
   "severity": "medium",
   "path": "runner/app.py:3763",
   "evidence": "The plain retry publishes its job and running event at lines 3828–3837 before starting the worker. A DELETE can then successfully remove that job and persist cancelled. If worker-thread creation subsequently fails, _start_failed ignores _end_job returning False and appends error for the same run, followed by another tracker push. Latest-record readers consequently replace the successful cancellation with error, violating the single-owner acceptance criterion. The new startup-failure test fails the initial running push before job publication and misses this sequence.",
   "fix": "Distinguish unpublished startup failures from failures after job publication. Once published, finalize only after successfully claiming ownership; if cancel or stall already owns the run, skip terminal persistence and tracker effects. Add a deterministic cancel-before-worker-start-failure case."
  }
 ],
 "coverage": [
  "Verified the supplied plan hash, all nine manifested file hashes, and tracked diff hash.",
  "Inspected changed implementation, regression-test sources, manifested documentation, and prior review dispositions.",
  "Traced dashboard, retry/fallback, Linear routing/execution, cancellation and stall ownership through registration, cleanup, persistence and tracker completion.",
  "Inspected related registry consumption, atomic state helpers, CLI state writers, run-history readers, reset generations, tracker persistence and polling.",
  "Traced project-bound startup recovery through confidentiality resolution, record-location checks and normal project finalization.",
  "Explicitly reviewed BUILD-009 thread construction/start cleanup and its existing test sources; no material defect found in the helper.",
  "Explicitly reviewed BUILD-017 os.rename, move/rollback callers and destination-race test source; no material defect found within the documented empty-directory behavior."
 ],
 "limitations": [
  "Static review only: no edits, tests, service changes or delegation. Reported passing tests were not independently verified.",
  "Spec fidelity was assessed against the supplied plan and inspected implementation; SPEC.md was not inspected.",
  "The graph predates this build; relevant relationships were checked against current source.",
  "Concurrent dashboard-plan documents were inspected as manifested evidence; their separate implementation was not evaluated. Deferred tracker ordering and documented accepted process/pipe risks remain outside approval scope."
 ]
}
```

- User decision (2026-10-15): "上升到20轮审阅" — continue the fix/inspect loop up to 20 inspection rounds.

### Dispositions and fixes
Fix handoff after inspection 8 (builder: Claude). Base 7b715a4. Fresh full inspection of the whole build. The user raised the inspection budget to 20 rounds.

Inspection 8 found RWS-017 (high) and RWS-018 (medium), both regressions introduced by the RWS-015 `_start_failed` helper. Both accepted and fixed:
- RWS-017: `_start_failed(exc, published=False, binding=None)`. The project-bound branch passes `binding=bound`. When `binding.get("confidential") is not False and _records_unsafe()` (the same rule `_run_project_ticket_locked` uses for its own records), the prompt is replaced by the withheld marker and the error by the withheld message; the record carries the binding through `extra=` (additive fields: project_key, issue_identifier, confidential, …). Test: confidential project, unsafe record location, sensitive reply, project worker start fails → the reply text never appears in the run log; the error record has project_key and a withheld prompt.
- RWS-018: the worker-start wrapper passes `published=True`; `_start_failed` then requires `_end_job(new_run_id)` to succeed before any terminal effect. If a cancel or stall already ended the run, it returns 409 and writes/pushes nothing. Unpublished failures (initial running push; project branch, where the retry route publishes no job) keep the previous behavior. Test: DELETE lands between job publication and a failing `_start_counted(_do_retry)` → the only record is `cancelled`, response 409.

NOT part of this build — please ignore: docs/exec-plans/active/2026-10-15-dashboard-ui-updates.md and its .review-log.md (a separate concurrent session).

Proof: 460 passed. The 2 new tests fail on the pre-fix build.

## Inspection 9 (fresh Codex)

- Result: `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/rws/inspect9/claudex-bg38768i/result.json`
- Verdict: **REVISE** (cross_provider), 1 finding (RWS-019 medium). RWS-017/018 confirmed fixed.

```json
{
 "verdict": "REVISE",
 "summary": "The latest ownership and confidentiality fixes address RWS-017/018. One edge-case regression remains in the new pipe reader.",
 "findings": [
  {
   "id": "RWS-019",
   "severity": "medium",
   "path": "runner/app.py:735",
   "evidence": "The new reader uses select.select, which rejects descriptors outside FD_SETSIZE (normally 1024). On a supported host with a higher open-file limit, enough concurrent connections or runs can give subprocess stdout such a descriptor. The reader then raises ValueError inside its background thread. That exception never reaches the streaming controller: a small Claude run can finish as review with its output and session metadata lost; a verbose child can block on its undrained pipe and eventually be reported as timed out. The previous buffered iteration supported these descriptors.",
   "fix": "Use selectors.DefaultSelector with the existing bounded polling interval. Propagate reader failures to the controller so they trigger cleanup and an error record. Add coverage using a valid pipe descriptor above select's limit."
  }
 ],
 "coverage": [
  "Verified the plan SHA256, all nine manifested file hashes, and tracked diff hash.",
  "Inspected manifested implementation, regression-test sources, documentation changes and prior review dispositions.",
  "Traced dashboard, retry/fallback, Linear routing/execution, cancellation and stall ownership through process registration, cleanup, persistence and tracker completion.",
  "Inspected related atomic state helpers, run_skill registry consumption and shared-state writers, reset generations, run-history readers and dashboard consumers.",
  "Checked project retry startup recovery against confidentiality resolution and normal project record safeguards.",
  "Explicitly reviewed BUILD-009 thread construction/start cleanup and relevant test sources; no material defect found.",
  "Explicitly reviewed BUILD-017 os.rename, move/rollback callers and destination-race test source; no material defect found within the documented empty-directory behavior."
 ],
 "limitations": [
  "Static review only: no edits, tests, service changes or delegation. Reported passing tests were not independently verified.",
  "Spec fidelity was assessed against the supplied plan and inspected implementation; SPEC.md was not inspected.",
  "The existing graph predates these changes; relevant relationships were checked against current source.",
  "Concurrent dashboard documents were inspected as evidence; their separate implementation was not evaluated. Deferred tracker ordering and documented accepted process/pipe risks remain outside approval scope."
 ]
}
```

### Dispositions and fixes
Fix handoff after inspection 9 (builder: Claude). Base 7b715a4. Fresh full inspection of the whole build. Inspection budget: 20 rounds (user decision).

Inspection 9 found RWS-019 (medium); accepted and fixed:
- `_iter_pipe_chunks` now uses `selectors.DefaultSelector()` (kqueue on macOS, epoll on Linux) with the same 0.25 s polling, so descriptors above FD_SETSIZE work. The `select` import stays for the unrelated codex app-server probe.
- New `_guarded(fn, errors)` wraps every reader (`functools.wraps` keeps names); a reader exception is appended to `errors` instead of dying in its thread. Text/Claude controllers raise `errors[0]` after the join (before waiting for the leader); the dsh controller joins its two readers in ≤0.25 s slices and raises the first error at once. The raise lands in the existing `except BaseException` cleanup (stop, kill group, reap, join readers) and then reaches the worker's error handler.
- Tests: a pipe dup'ed to fd 1500 is read through `_iter_pipe_lines` (raises the soft RLIMIT_NOFILE if needed, skips if the hard limit is too low); a failing `_iter_pipe_lines` makes each of the three stream helpers raise that error with the child reaped. The burst test (RWS-012) now writes ~1.8 KB of lines into a real pipe — below any pipe capacity, and epoll cannot watch regular files.
- Test harness only: the route-test fixture restores `_INFLIGHT` on teardown. Those tests send DELETE/PATCH from inside another test-client request; nested test-client requests share `flask.g`, so the maintenance gate releases one slot for two. Production requests never nest. (Before, this only leaked into later files; the suite order hid it.)

NOT part of this build — please ignore: docs/exec-plans/active/2026-10-15-dashboard-ui-updates.md and its .review-log.md (a separate concurrent session).

Proof: 464 passed. The 4 new cases fail on the pre-fix build.

## Inspection 10 (fresh Codex)

- Result: `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/rws/inspect10/claudex-ax2zsiii/result.json`
- Verdict: **REVISE** (cross_provider), 2 findings (RWS-020 high, RWS-021 medium).

```json
{
 "verdict": "REVISE",
 "summary": "Two retry-recovery defects remain: stale confidentiality policy can expose feedback, and persistence-error cleanup can lose the process-group handle.",
 "findings": [
  {
   "id": "RWS-020",
   "severity": "high",
   "path": "runner/app.py:3794",
   "evidence": "Project retry resolves confidentiality at line 3810 without holding project_lock, then _start_failed trusts that snapshot. Start with a public project and an external RUN_LOG; pause a bound retry after policy resolution, promote the project through PATCH /api/projects/<key>, then let worker-thread startup fail. Promotion succeeds because this request holds no shared project lock. The recovery handler still sees confidential=False and writes the new feedback unredacted to the external log. Normal project startup acquires the lifecycle lock and resolves policy again.",
   "fix": "Protect bound retry startup and failure finalization with the shared project lifecycle lock, resolving current sticky confidentiality under it before recording anything. Cover promotion between initial policy resolution and worker-start failure, including unsafe record locations."
  },
  {
   "id": "RWS-021",
   "severity": "medium",
   "path": "runner/app.py:3989",
   "evidence": "A retry attempt can leave a same-group descendant with redirected stdout/stderr while its leader exits. Normal completion calls end() at line 3953, which removes the process handle through _end_job. If _write_run_log then raises once, the generic recovery handler looks up that already-removed handle and calls _kill_and_reap(None). It writes error, but the descendant survives and subsequent cancellation returns 404. Dashboard and Linear handlers retain their local proc; retry recovery does not.",
   "fix": "Keep the current attempt's process handle locally through finalization and persistence recovery, and use it for outer error cleanup even after ownership removes the shared entries. Extend the persistence-failure regression to include a surviving same-group descendant."
  }
 ],
 "coverage": [
  "Verified the plan SHA256, all nine manifested file hashes, and tracked diff SHA256.",
  "Inspected manifested code, test sources, documentation and prior review dispositions.",
  "Traced dashboard, retry/fallback, Linear routing/execution, cancellation and stall ownership, process cleanup and terminal effects.",
  "Inspected related atomic-state helpers, run_skill registry consumption and shared-state writers, reset guards, tracker persistence and run-history readers.",
  "Traced project confidentiality resolution, promotion routes, lifecycle locks and record-location safeguards.",
  "Reviewed BUILD-009 thread construction/start cleanup and BUILD-017 rename_dir, move/rollback callers and relevant test sources; no material defect identified in those fixes."
 ],
 "limitations": [
  "Static review only: no edits, tests, service changes or delegation. Reported passing tests were not independently verified.",
  "Spec fidelity was assessed against the supplied plan and inspected implementation; SPEC.md was not inspected.",
  "The graph predates this build; relevant relationships were checked against current source.",
  "Separate dashboard implementation and deferred tracker-write ordering were not evaluated. Documented accepted process and pipe risks remain."
 ]
}
```

### Dispositions and fixes
- RWS-020 (high) fixed: for a project-bound run, `_start_failed` withholds the prompt and error whenever `_records_unsafe()`, no longer trusting the request-start confidentiality snapshot. Test: stale public snapshot, unsafe location, sensitive reply → reply absent from the run log.
- RWS-021 (medium) fixed: `_do_retry` keeps `attempt_proc[0]` (set after registration) and the outer error handler kills and reaps it, even after `_end_job` removed the shared entry. Test: a one-shot review-record failure → the attempt's process is signalled again by the handler.
- Full suite: 466 passed. Both new tests fail on the pre-fix build. Runner restarted 21:04; /api/maintenance → inflight 0. Public-name grep clean.

## Closure (user decision, 2026-10-15)
- User: "定收敛标准后收尾：只修 high，以及在 macOS 本机、单用户场景下真能复现的问题。'注入一次性失败'一类的 medium 记为已接受风险，写进 RWS 日志。第 10 次检查回来后按这个标准处理完就 commit。"
- Applied: RWS-020 (high) fixed. RWS-021 is a one-shot injected failure, so it is an accepted-risk class; it was already fixed before the standard arrived, and the fix is kept. No further inspection.
- **Unreviewed edits:** the RWS-020 and RWS-021 fixes were made after inspection 10 and have not been independently inspected.
- Accepted risks (see the plan's 'Accepted risks' section):
  - further one-shot injected failures of the same class (thread start, single failed record/comment/tracker write, failure inside an error handler);
  - deferred tracker write ordering;
  - escaped setsid descendants;
  - inherited stderr on the normal path;
  - pgid reuse within the cancel grace;
  - empty-directory rename replacement.
- Root fix planned as the prerequisite of part C of the dashboard UI plan: one `run_agent_process(run_id, cmd, …)` in place of five copies of the lifecycle.
- Inspections: 10 Codex (cross_provider) plus 1 failed launch (Codex usage limit; the degraded fallback was refused by the runner and not used). Assurance: cross_provider for everything up to the inspection-10 fixes.
