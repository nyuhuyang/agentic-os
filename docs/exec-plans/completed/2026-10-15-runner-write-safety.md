---
status: completed
created: 2026-10-15
completed: 2026-10-15
---

# Runner write-safety hardening (follow-up)

## Goal
Close the remaining concurrent-write, timeout-cleanup and cancellation gaps that the relocation inspections found in the runner itself, not in the move.

Origin: `docs/exec-plans/completed/2026-10-15-relocate-to-workspace-root.md` and its review log. Inspection 7 there raised BUILD-014, BUILD-016, BUILD-017 and BUILD-009. On 2026-10-15 the user decided to stop that plan's review after inspection 7 and carry the rest here. Plan review round 1 added WS-001 to WS-005.

Authorization (2026-10-15): "修订 … 并用claude执行". Revise, get a Codex plan review, then Claude builds and a fresh Codex session inspects.

## Acceptance criteria
- [x] BUILD-016: `_registry_exec_env` publishes its cache file atomically (unique temp file + `os.replace`). A reader that opened the published file before a concurrent republish still reads the complete old file, never a truncated or partial one.
- [x] BUILD-014 remainder, part 1: agent subprocesses for dashboard and Linear runs start in their own process group, and on timeout the whole group is killed and the leader is reaped. This covers:
  - [x] the run_skill entrypoint in `/api/run`
  - [x] the agent CLI in `/api/run`
  - [x] both retry paths in `_dispatch_cmd`
  - [x] the Linear dispatch `Popen` in `runner/modules/linear/__init__.py`
- [x] BUILD-014 remainder, part 2: after a timeout, the stdout/stderr readers stop within a bounded time even if a descendant outside the group still holds the pipe open. Their in-flight slots return, so `/api/maintenance` reports `inflight` back to its pre-run value.
- [x] One deadline covers each streamed run, including reader joins and `proc.wait`. A child that closes stdout early and then sleeps still times out at `timeout` and gets the same group-kill cleanup (WS-001).
- [x] Non-streaming runs (`communicate` in retry and in Linear) kill and reap the group on timeout. Today:
  - [x] retry: the `finally` clause pops `_running_procs` before the `except` handler runs, so the handler's `proc.kill()` never fires;
  - [x] Linear: only the leader is killed.
- [x] Cancel (`DELETE /api/runs/<run_id>`, the non-project branch) sends SIGTERM to the process group, then SIGKILL to the group after a 5 s grace. The SIGKILL is sent even when the leader has already exited, so a descendant that ignores SIGTERM still dies (WS-002).
- [x] A cancelled or stalled run stays that way (WS-004, WS-006, WS-007):
  - [x] exactly one party (worker, cancel or stall) ends a run, by removing its job and proc entries together under `_JOB_LOCK`, and only that party writes the terminal record;
  - [x] a process launched after its run was cancelled or stalled, including the retry fallback, is killed at registration;
  - [x] a cancel after the worker ended the run returns 404, and the worker's record stands;
  - [x] only the owner does terminal side effects (record, tracker push, emits); the stall pass, as owner, completes a Linear-linked run through `_mark_issue_review` with the run's launch generation, so a stalled run reaches In Review with `dispatched` cleared, unless the issue was reset since launch or is Done/Canceled/Duplicate (WS-013);
  - [x] a worker claims ownership once and keeps it through persistence-error recovery.
- [x] The two post-inspection fixes get independent Codex review in both the plan review and the build inspection (plan review round 1; inspections 1, 6–9: no material defect): `_start_counted` constructing and starting the thread inside the release handler (BUILD-009), and `rename_dir` using `os.rename` in `scripts/relocate_checkout.sh` (BUILD-017).
- [x] The full suite passes: `.venv/bin/python -m pytest tests/ -q -p no:cacheprovider`. The baseline is 410 passed at `5a28e45`.

## Approach

### BUILD-016: atomic cache publish (`runner/app.py` `_registry_exec_env`)
- Replace `path.write_text(...)` with `state_io.write_text_atomic(path, ...)`. That helper already exists: it writes a `mkstemp` file in the same directory, then calls `os.replace`.
- No lock is needed. Plan review round 1 agreed. The filename is content-addressed (agent + sha256 of `skills`), so concurrent writers of one path write the same skills and differ only in `generated_at`. `os.replace` swaps the directory entry:
  - a reader that already opened the old inode keeps the complete old file;
  - a reader that opens afterwards gets the complete new one.
- `run_skill.py:_load_registry` reads the whole file in one go.
- Non-goal: pruning old cache files (unchanged behaviour).

### BUILD-014 remainder: process groups and stoppable readers (`runner/app.py`, `runner/modules/linear/__init__.py`)
1. **`_kill_group(proc, sig=SIGKILL)`** in app.py:
   - It calls `os.killpg(proc.pid, sig)` and suppresses `ProcessLookupError`/`PermissionError`.
   - If the proc has no `pid` (test doubles) or `killpg` fails, it falls back to `proc.send_signal(sig)`, so the requested signal is kept. That fallback is suppressed too.
   - Because of `start_new_session=True`, pgid == pid. This mirrors the existing `_terminate_group`, which project runs use.
2. **`start_new_session=True`** goes on four agent `Popen` sites:
   - `/api/run` entrypoint (≈L2956);
   - `/api/run` agent CLI (≈L3016);
   - retry `_dispatch_cmd` (≈L3625);
   - Linear dispatch (`runner/modules/linear/__init__.py` ≈L680), which shares `_running_procs` and `_stream_dsh_run`.

   The runner is under launchd, with no TTY and no Ctrl-C to forward, so detaching from the runner's group changes nothing else. `pid` is unchanged, so `_session_from_pid` still works. The codex app-server probe (≈L1442) is out of scope: it is short-lived and has its own terminate/kill.
3. **`_iter_pipe_lines(pipe, stop)`** (plus `_iter_pipe_chunks` for raw stderr): a generator the readers use instead of `for raw in proc.stdout`.
   - It loops `select.select([fd], [], [], 0.25)` and `os.read(fd, 65536)`, splits on `\n`, and yields complete lines plus any trailing partial line at EOF.
   - It ends on EOF or once `stop.is_set()`.
   - Fallback when the pipe has no usable descriptor (`fileno` missing, or raising `io.UnsupportedOperation`/`ValueError`/`OSError`), WS-008: `_iter_pipe_lines` iterates the object (iterator stdout doubles), and `_iter_pipe_chunks` yields `pipe.read()` once (read-only stderr doubles in `tests/test_dsh_backend.py` and `tests/test_reset_gen.py`).
   - It never mixes with the buffered `proc.stdout` object, which is not read anywhere else.
4. **Readers**:
   - `_stream_text_run`, `_stream_claude_run` and `_stream_dsh_run` (plus dsh's `_drain_stderr`, through `_iter_pipe_chunks`) take a shared `stop = threading.Event()`.
   - The one-shot `proc.stderr.read()` after a normal exit stays as is in text/Claude.
5. **One deadline (all three readers, WS-001)**:
   - `deadline = time.monotonic() + timeout`. Join the readers with the remaining time, then `proc.wait(timeout=remaining)`.
   - Any `TimeoutExpired` (a reader still alive, or the leader still running after stdout EOF) goes to one cleanup: `stop.set()` → `_kill_group(proc)` → `proc.wait(timeout=5)` (suppressing `TimeoutExpired`) → join each reader with `timeout=2` → raise `subprocess.TimeoutExpired`.
   - Readers poll `stop` every 0.25 s, so they end within about 0.25 s of the join even when an escaped descendant keeps the pipe open. Their `_start_counted` slots release in the thread's `finally`.
6. **Callers' `except subprocess.TimeoutExpired`**: replace `_running_procs[run_id].kill()` and `proc.kill()` (three in app.py, one in Linear) with `_kill_group(...)`. This is harmless when the group is already dead.
7. **Non-streaming runs**: in `_dispatch_cmd` and in the Linear `proc.communicate` branch, catch `TimeoutExpired`, call `_kill_group(p)` and `p.wait(timeout=5)` (suppressed), then re-raise. The existing retry `finally` still pops `_running_procs`.
8. **Cancel endpoint** (`DELETE /api/runs/<run_id>`, ≈L3446, WS-002):
   - `_kill_group(proc, SIGTERM)`, then `proc.wait(timeout=5)` (suppressed).
   - Then `_kill_group(proc, SIGKILL)` unconditionally, so a descendant that ignores SIGTERM dies even when the leader exited promptly.
   - Then a final `proc.wait(timeout=5)` (suppressed).
   - ponytail: the SIGKILL after the leader is reaped targets a pgid that could in theory be reused within those 5 s. Accepted; it is the same ceiling as `_terminate_group`.
9. **One lifecycle under `_JOB_LOCK` (WS-004, WS-006, WS-007).** Today cancel pops the job and writes `cancelled`. The worker then sees a non-zero exit, may start the resume-failure fallback (≈L3671), and then appends its own `review`/`error`, which `_load_runs_from` treats as the latest record. The stall pass has the same overwrite.

   The rule: a non-project run is *live* while its `_running_jobs` entry exists. Exactly one party ends it, by removing the job and proc entries together under `_JOB_LOCK`. That party is the record owner. The ending parties are the worker finishing, the cancel endpoint, or the stall pass.
   - **`_register_proc(run_id, proc) -> bool`** (launch handshake). Under `_JOB_LOCK`:
     - if the job entry is gone (cancelled or stalled before or during the `Popen`), `_kill_group(proc)` and return False;
     - otherwise set `_running_procs[run_id] = proc` and return True.
     - It replaces the bare `_running_procs[...] = proc` at all four launch sites, including the retry fallback, which launches through `_dispatch_cmd`.
     - On False the caller reaps the proc (`wait(timeout=5)`, suppressed) and goes to its terminal point. It must not read output.
     - The window between "job removed" and "process registered" therefore always ends with the process killed.
   - **`_end_job(run_id) -> bool`** (worker terminal point, WS-006). Under `_JOB_LOCK`, pop both `_running_jobs[run_id]` and `_running_procs[run_id]`. Return True (the worker owns the record) only when the job entry was still there.
     - The existing paired `_running_jobs.pop` / `_running_procs.pop` lines at the worker terminal points (normal, timeout, error) are replaced by this one call.
     - After it, cancel finds neither entry and returns 404 ("not running"), so its result stands.
   - **Cancel endpoint**. Under `_JOB_LOCK`, pop both entries. If no job was popped, return 404; a proc without a job cannot exist once the handshake is in place. Then, outside the lock: signal the group (step 8), write the `cancelled` record, push Linear `review` and emit, as today.
   - **Stall pass** (`runner/modules/stall_detection/__init__.py`, non-project branch). Pop both entries under `_app._JOB_LOCK`. Use `_app._kill_group(proc)` instead of `proc.kill()`. It keeps writing `stalled`. When the job has a `linear_issue_id` and a `launch_gen`, it now also completes the tracker through the Linear module's guarded `_mark_issue_review(issue_id, gen=job["launch_gen"])`, the same helper the displaced Linear worker would have used (WS-007, WS-013). That helper keeps every guard the worker had:
     - a reset since launch (`reset_gen.is_current`) leaves the issue alone;
     - Done/Canceled/Duplicate stay put;
     - otherwise the issue moves to In Review and `dispatched` is cleared.
     Linear dispatch and retry store their launch generation in the job entry as `launch_gen` (they already have it as `launch_gen` / `_launch_gen`). A job without `launch_gen` gets no stall push, as today. Retry runs move from the unguarded `_finish` push to this guarded helper on stall, which only adds the terminal-state protection.
   - **The owner does every side effect (WS-007; the late-worker part of WS-010).** The party that ended the run writes the terminal record, pushes the tracker state and emits, and no one else does. A worker that does not own the run (`_end_job` returned False) skips all of its terminal side effects: run-log record, Linear run comment, `_mark_issue_review`, the retry `_finish` review push, and the `run_state_change`/`run_logged` emits.
     - Cancel and stall push `review` at the moment they end the run. A new retry B for the same issue can only start after that, because the run is no longer live. A's late worker then touches nothing, so B's `running` state cannot be overwritten.
     - `/api/run` returns `{"ok": false, "error": "cancelled"}` in that case.
   - **Claim once (WS-009).** Each worker keeps its claim in a local, e.g. `owner: bool | None = None`, set by a small local `end()` that calls `_end_job` only while `owner is None`. Normal, timeout and error branches all call `end()`. A persistence failure after a successful claim (for example `_write_run_log` raising) reaches the error handler with `owner` already True. The handler then still writes its error record as the owner, instead of mistaking its own earlier pop for another party's claim.
   - **Retry fallback**: before the fallback, `if new_run_id not in _running_jobs`, skip it. This is only an early out; the handshake alone already prevents a fallback process from surviving a cancel.
   - Project runs (`_signal_project_run`) are untouched; they already use `phase`/`cancelled` under `_JOB_LOCK`.

### Moved out: tracker write ordering (WS-010 owner-push ordering, WS-011, WS-012)
Plan review rounds 4–6 showed that ordering tracker writes for one issue is a design of its own: run-scoped `push_state`, per-issue sequence numbers, `_mark_issue_review`, `_linear_sync_patch` and direct PATCH writes. The race predates this plan; today cancel already pushes `review` asynchronously. It moved to `docs/exec-plans/active/2026-10-15-tracker-write-ordering.md` on 2026-10-15 (host decision, review round 6). This plan guarantees only that a late non-owner worker makes no tracker write. The owner's own push keeps today's ordering.

### BUILD-009 / BUILD-017: review only
- No new code planned. Plan review round 1 found no material defect in either. Current state:
  - `_start_counted` (≈L2623) builds and starts the thread inside `try/except BaseException: _release(); raise`. Tests: `test_counted_thread_construction_failure_releases_the_slot` and the `Thread.start` variant.
  - `rename_dir` (`scripts/relocate_checkout.sh:41`) is `os.rename`, used for the move (L189) and the rollback (L174). Test: a destination created at bootout gives "rename failed", nothing is nested, and OLD keeps running.
- Known edge, accepted: `rename(2)` replaces an existing **empty** directory instead of failing. The checkout still lands at NEW un-nested. Plan review round 1 agreed.

## Non-goals
- Project-run subprocesses (`runner/projects.py`) already use process groups and `_terminate_group`. They are unchanged.
- Runner shutdown and `_stop_project_runs` are unchanged. The stall pass changes only in its non-project branch (step 9).
- No new dependencies.

## Risks
- A descendant that called `setsid` itself escapes `killpg`. The readers still stop (the `stop` event), but that process lives on. It no longer pins an in-flight slot, which is the BUILD-014 harm. Killing it would need process-tree walking (psutil), which is out of scope.
- text/Claude: on the normal path, a descendant that escaped the group and keeps stderr open would block `proc.stderr.read()` after the leader exits. This risk existed before and is not made worse. dsh already drains stderr concurrently. Accepted; noted for the inspector.
- A cancel that lands after a worker's `_end_job` finds no entries and returns 404 ("not running"). The run finished, and its own record stands.
- A cancel that lands after the process exited but before `_end_job` wins: the record says `cancelled`, although the agent finished. This is the user's explicit choice and is consistent with the record.
- `select` on pipe fds works on macOS/Linux, the only runner platforms.

## Verification
- Proof: `.venv/bin/python -m pytest tests/ -q -p no:cacheprovider 2>&1 | grep -E "passed|failed"`. Expected: all pass, ≥ 410 + new tests.
- New tests (in `tests/test_project_dispatch.py` unless noted):
  - [x] BUILD-016: publish a cache, open it, republish the same agent/registry. Check that the held handle still parses as complete JSON and that its inode differs from the path's current inode. This fails on the old `write_text` (same inode, rewritten).
  - [x] BUILD-014 group kill: run `sh -c 'sleep 60 & echo $!; exec sleep 60'` through each of `_stream_text_run`, `_stream_claude_run` and `_stream_dsh_run` with `start_new_session=True` and `timeout=1`. Expect `TimeoutExpired`, the leader reaped, and the background `sleep` (pid read from the stream log) gone.
  - [x] BUILD-014 escaped descendant: a child that starts `sleep 60` with `start_new_session=True` (own group) inheriting stdout, then sleeps. Same three readers with `timeout=1`. Expect `TimeoutExpired` within 10 s, `_INFLIGHT` back to the pre-call value, and reader threads dead. The test kills the escaped sleep afterwards.
  - [x] Early stdout EOF (WS-001): `sh -c 'exec >/dev/null; sleep 60'` through the three readers with `timeout=1`. Expect `TimeoutExpired` within 10 s and the leader reaped.
  - [x] Non-streaming retry timeout: drive `_dispatch_cmd`'s communicate branch through the existing retry harness, with a child that has a background descendant and a short `AI_RUN_TIMEOUT_S`. Expect the whole group dead after the retry finishes.
  - [x] Linear timeout (WS-003): drive the Linear dispatch path through its existing test harness, with a child that has a background descendant and a short timeout. Expect both gone and a timeout record written.
  - [x] Cancel group kill (WS-002): a running job whose leader exits on SIGTERM and whose descendant ignores SIGTERM (`trap '' TERM`). After `DELETE /api/runs/<run_id>`, expect both gone.
  - [x] Cancel terminal (WS-004), retry: cancel a resumed retry (stubbed resume command that sleeps). Expect no fallback process to start and the latest run-log record for that run_id to stay `cancelled`.
  - [x] Cancel terminal (WS-004), `/api/run`: cancel mid-run. Expect no `review` record appended after `cancelled`.
  - [x] Launch race (WS-004): remove the job (as cancel does) between job publication and `_register_proc`, using a patched `Popen` that removes it. Expect the launched process killed, `_register_proc` returning False, and no run record from the worker. Cover both the first launch and the retry fallback.
  - [x] Finalization race (WS-006): after the worker's `_end_job` and before its record write (patched `_write_run_log` hook), `DELETE /api/runs/<run_id>` returns 404 and the worker's record is the only terminal one.
  - [x] Stall then worker (WS-007): the stall pass ends a Linear-dispatched run. Expect the latest record `stalled`, no worker `review` record after it, the issue marked In Review (pushed by the stall pass) and removed from `dispatched`.
  - [x] Claim once (WS-009): a worker whose first `_write_run_log` call raises once. Expect the error handler to write an `error` record as owner, not to treat the run as cancelled, and not to omit the terminal record.
  - [x] Reset then stall (WS-013): reset a running Linear-linked issue to Todo, then let its old run stall. Expect the issue still in Todo. Also Done then stall: expect it still Done.
  - [x] Late non-owner (WS-010): cancel retry A, start retry B for the same issue without a reset, then release A's delayed worker. Expect B's issue state still `running`/In Progress and `dispatched` still pointing at B.
- [x] Existing FakeProc-based tests (`tests/test_dsh_backend.py`, `tests/test_reset_gen.py`) still pass. This covers the no-`fileno` fallback.

## Accepted risks (user convergence standard, 2026-10-15)
- One-shot injected failures beyond those already handled: for example a thread that cannot start, a single failed write of a record, comment or tracker state, or a failure inside a handler that is already handling one. Each failure path found in inspections 1–10 was fixed. Others of the same kind may remain and are accepted rather than chased.
- Tracker write ordering across runs and writers: deferred to `docs/exec-plans/active/2026-10-15-tracker-write-ordering.md`.
- A descendant that called `setsid` itself escapes the group kill; the readers still stop.
- A stderr held open by an escaped descendant can block the text/Claude normal path.
- The process-group id could be reused within the 5 s cancel grace.
- `rename(2)` replaces an empty destination directory.
- Root fix for the duplicated lifecycle: five near-copies of the launch, read, timeout, claim and record flow (`/run` ×2, retry, Linear, project helper) should become one `run_agent_process(...)`. It is the prerequisite step of part C in `docs/exec-plans/active/2026-10-15-dashboard-ui-updates.md`.

## Progress Checklist
- [x] Revise the plan with the concrete approach (this document)
- [x] Codex plan review returns APPROVED; final plan SHA256 recorded in the review log (round 8, 0ce298f7…)
- [x] BUILD-016: `_registry_exec_env` writes through `write_text_atomic`
- [x] Test: a held cache handle stays complete across a republish (fails on old code)
- [x] `_kill_group` helper added (fallback keeps the requested signal)
- [x] `start_new_session=True` on the four agent `Popen` sites (three in app.py, one in Linear)
- [x] `_iter_pipe_lines` / `_iter_pipe_chunks` with select/stop and the no-fileno fallback
- [x] `_stream_text_run`, `_stream_claude_run` and `_stream_dsh_run` use one deadline, the stop event and the group-kill timeout path
- [x] Caller timeout handlers use `_kill_group` (app.py and Linear)
- [x] Non-streaming retry and Linear `communicate` kill and reap the group on timeout
- [x] Cancel endpoint: SIGTERM to the group, grace, unconditional SIGKILL to the group, reap
- [x] `_register_proc` handshake at all four launch sites (incl. retry fallback); claim-once `end()` → `_end_job` at every worker terminal point; cancel and stall pop both entries under `_JOB_LOCK`; only the owner does terminal side effects
- [x] Stall pass uses `_kill_group` and completes a Linear-linked run through `_mark_issue_review(issue_id, gen=launch_gen)`; Linear dispatch and retry store `launch_gen` in the job
- [x] Test: reset-then-stall leaves the issue in Todo; Done-then-stall leaves it Done
- [x] Test: group kill on timeout for all three readers (background descendant gone)
- [x] Test: escaped descendant holding stdout; readers stop and in-flight returns, all three readers
- [x] Test: early stdout EOF still times out (text, Claude, dsh)
- [x] Test: non-streaming retry timeout kills the group
- [x] Test: Linear dispatch timeout kills the group
- [x] Test: cancel kills a SIGTERM-ignoring descendant after the leader exits
- [x] Test: a cancelled resumed retry starts no fallback and stays `cancelled`; a cancelled `/api/run` appends nothing after `cancelled`
- [x] Test: launch race kills the process (first launch and fallback)
- [x] Test: cancel after `_end_job` returns 404 and the worker record stands
- [x] Test: stall then worker keeps `stalled` and still marks the Linear issue In Review
- [x] Test: a one-shot persistence failure after the claim still writes an owner `error` record
- [x] Test: a late non-owner worker leaves retry B's issue state and `dispatched` alone
- [x] Full suite passes (`.venv/bin/python -m pytest tests/ -q -p no:cacheprovider`) — 433 passed (410 + 23 new in `tests/test_runner_write_safety.py`); 19 of the 23 fail on the pre-build code, the other 4 are regression guards
- [x] Runner restarted (`launchctl kickstart -k gui/$(id -u)/com.agenticos.runner`) and `/api/maintenance` answers with `inflight` 0 — 2026-10-15 18:42, `{"inflight":0,"maintenance":false}`
- [x] Inspection 1 fix RWS-001: Linear dispatch pushes `running` before publishing the job, so a cancel/stall `review` can never be followed by it — test `test_linear_running_push_cannot_follow_a_cancel`
- [x] Inspection 1 fix RWS-002: jobs carry `record` metadata (agent, model, task_id, parent_run_id, attempt, reset_generation); cancel and stall write it through `_write_owner_record` — test `test_cancel_and_stall_records_keep_the_launch_metadata`
- [x] Inspection 1 fix RWS-003: the owner record write is tried twice; one failing stall never stops the watchdog (`_stall` per job, exceptions logged) — tests `test_a_failed_owner_record_write_is_retried`, `test_one_failing_stall_does_not_stop_the_watchdog`
- [x] Inspection 1 fix RWS-004: readers start inside the cleanup block; a failed start stops the started readers and kills the group — test `test_a_reader_that_cannot_start_ends_the_run` (text, Claude, dsh first and second reader)
- [x] Full suite after inspection-1 fixes: 443 passed; the 10 new tests all fail on the pre-fix build
- [x] Inspection 2 fix RWS-005: the retry keeps each attempt's process handle registered until the run ends or the next attempt replaces it; `_register_proc` kills the replaced attempt's group — test `test_cancel_between_attempts_still_ends_the_first_group`
- [x] Inspection 2 fix RWS-006: timeout/error handlers (/run, retry, Linear) write through `_write_run_log_retrying` (twice, never raises), so the tracker completion after it still runs — test `test_a_failed_timeout_record_write_is_retried`
- [x] Inspection 2 fix RWS-007: a failed initial `running` publication in Linear dispatch finishes the run (dispatch cleared, error record, guarded In Review) — test `test_linear_start_failure_finishes_the_run`
- [x] Inspection 2 fix RWS-008: every generic post-launch failure kills the group (/run handlers, Linear handler, retry `_dispatch_cmd`) — test `test_a_setup_failure_after_launch_kills_the_agent` (retry, /run)
- [x] Full suite after inspection-2 fixes: 448 passed; the 5 new tests all fail on the pre-fix build
- [x] Inspection 3 fix RWS-009: `_iter_pipe_lines` checks `stop` before every buffered line and the trailing fragment — test `test_buffered_lines_stop_with_the_reader`
- [x] Inspection 3 fix RWS-010: shared `_kill_and_reap` (group kill + bounded wait) in every post-launch handler (/run timeout/error/CLI-missing, Linear timeout/error, retry, `_register_proc`, `_timeout_cleanup`); the setup-failure test now checks `returncode` instead of `poll()`
- [x] Full suite after inspection-3 fixes: 449 passed; both changed/new tests fail on the pre-fix build
- [x] Inspection 4 fix RWS-011: the retry worker's outer error handler kills and reaps the registered attempt's group before ending the run (fallback setup failures) — test `test_a_fallback_setup_failure_ends_the_first_attempts_group`
- [x] Inspection 4 fix RWS-012: the buffered-lines test reads a temporary file instead of a pipe, so it cannot block on a small pipe buffer
- [x] Full suite after inspection-4 fixes: 450 passed; the RWS-011 test fails on the pre-fix build
- [x] Inspection 5 fix RWS-013: closing tracker comments in every terminal path (retry and Linear: normal, timeout, error) go through `_comment_quietly`, so a comment failure never skips the tracker completion — test `test_a_failed_closing_comment_still_completes_the_ticket` (retry/Linear × timeout/error)
- [x] Full suite after inspection-5 fixes: 454 passed; the 4 new cases fail on the pre-fix build
- [x] Inspection 6 fix RWS-014 (pre-existing, adjacent): the retry's initial Human Feedback comment (plain and project-bound) goes through `_comment_quietly`, so a comment failure never aborts the launch — test `test_a_failed_feedback_comment_does_not_abort_the_retry`
- [x] Full suite after inspection-6 fixes: 455 passed; the new test fails on the pre-fix build
- [x] Inspection 7 fix RWS-015 (pre-existing, adjacent; user chose fix + one more inspection): retry startup failures (initial `running` push, worker start; plain and project-bound) finish the run in `_start_failed` (job ended, dispatch cleared, error record with retry metadata, guarded review push, 500) — test `test_a_failed_running_push_finishes_the_retry`
- [x] Inspection 7 fix RWS-016 (pre-existing, adjacent): Linear skill routing runs through `_run_grouped` (own process group, group kill and reap on timeout/failure); the two dsh routing tests stub `_run_grouped` instead of `subprocess.run` — tests `test_a_routing_timeout_kills_its_group`, `test_linear_routing_goes_through_the_grouped_runner`
- [x] Full suite after inspection-7 fixes: 458 passed; the 3 new tests fail on the pre-fix build
- [x] Inspection 8 fix RWS-017 (high, regression from the RWS-015 fix): a project-bound retry's startup-failure record follows the project finalization policy — confidential and unsafe record locations → prompt and error withheld — and carries the binding — test `test_a_confidential_project_retry_start_failure_withholds_the_feedback`
- [x] Inspection 8 fix RWS-018 (regression from the RWS-015 fix): a worker-start failure after job publication finalizes only after `_end_job` claims the run; a cancel/stall that already ended it keeps its record (409) — test `test_a_worker_start_failure_after_a_cancel_keeps_the_cancel`
- [x] Full suite after inspection-8 fixes: 460 passed; both new tests fail on the pre-fix build
- [x] Inspection 9 fix RWS-019: `_iter_pipe_chunks` uses `selectors.DefaultSelector` (no FD_SETSIZE ceiling); readers run through `_guarded`, so a reader exception reaches its controller, which cleans up (kill, reap, stop) and re-raises; the dsh controller joins in short slices so the error surfaces at once — tests `test_a_pipe_above_fd_setsize_is_still_read`, `test_a_failing_reader_ends_the_run_with_its_error` (×3); the burst test uses a small real pipe (epoll cannot watch regular files); the harness restores `_INFLIGHT` (nested test-client requests share `flask.g`)
- [x] Full suite after inspection-9 fixes: 464 passed; the 4 new cases fail on the pre-fix build
- [x] Inspection 10 fix RWS-020 (high): a project-bound retry's startup-failure record withholds the prompt whenever record locations are unsafe, whatever the (possibly stale) confidentiality snapshot says — test `test_a_project_retry_start_failure_withholds_even_on_a_stale_public_snapshot`
- [x] Inspection 10 fix RWS-021 (medium, fixed before the convergence standard arrived): the retry worker keeps the current attempt's process handle locally, so the outer error handler still ends its group after `_end_job` removed the shared entry — test `test_a_failed_record_write_still_ends_the_attempts_group`
- [x] Full suite after inspection-10 fixes: 466 passed; both new tests fail on the pre-fix build; runner restarted 21:04, `/api/maintenance` → `{"inflight":0,"maintenance":false}`
- [x] Fresh cross-provider (Codex) build inspection, base `7b715a4` (plan commit; was `7c519f1` before the 2026-10-15 history rewrite that removed private names), returns no unresolved material findings; it explicitly covers BUILD-009 and BUILD-017 — N/A by user decision (2026-10-15): convergence standard "只修 high，以及在 macOS 本机、单用户场景下真能复现的问题；注入一次性失败一类的 medium 记为已接受风险；第 10 次检查回来后按这个标准处理完就 commit". Ten inspections ran (findings 4, 4, 2, 2, 1, 1, 2, 2, 1, 2); every finding was fixed. The RWS-020/021 fixes after inspection 10 have NOT been independently inspected. BUILD-009 and BUILD-017 were reviewed in inspections 1, 6, 7, 8 and 9: no material defect.
- [x] Public-repo check: `git grep` for the private project names (pattern kept outside the repo) finds nothing in tracked files — clean after scrubbing two pre-existing doc leaks (a completed plan's evidence line; this plan's own check line)
- [x] Commit (not pushed) — the commit that archives this plan
