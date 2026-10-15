---
status: in-progress
created: 2026-10-15
---

# Runner write-safety hardening (follow-up)

## Goal
Close the remaining concurrent-write, timeout-cleanup and cancellation gaps that the relocation inspections found in the runner itself, not in the move.

Origin: `docs/exec-plans/completed/2026-10-15-relocate-to-workspace-root.md` and its review log. Inspection 7 there raised BUILD-014, BUILD-016, BUILD-017 and BUILD-009. On 2026-10-15 the user decided to stop that plan's review after inspection 7 and carry the rest here. Plan review round 1 added WS-001 to WS-005.

Authorization (2026-10-15): "修订 … 并用claude执行". Revise, get a Codex plan review, then Claude builds and a fresh Codex session inspects.

## Acceptance criteria
- [ ] BUILD-016: `_registry_exec_env` publishes its cache file atomically (unique temp file + `os.replace`). A reader that opened the published file before a concurrent republish still reads the complete old file, never a truncated or partial one.
- [ ] BUILD-014 remainder, part 1: agent subprocesses for dashboard and Linear runs start in their own process group, and on timeout the whole group is killed and the leader is reaped. This covers:
  - [ ] the run_skill entrypoint in `/api/run`
  - [ ] the agent CLI in `/api/run`
  - [ ] both retry paths in `_dispatch_cmd`
  - [ ] the Linear dispatch `Popen` in `runner/modules/linear/__init__.py`
- [ ] BUILD-014 remainder, part 2: after a timeout, the stdout/stderr readers stop within a bounded time even if a descendant outside the group still holds the pipe open. Their in-flight slots return, so `/api/maintenance` reports `inflight` back to its pre-run value.
- [ ] One deadline covers each streamed run, including reader joins and `proc.wait`. A child that closes stdout early and then sleeps still times out at `timeout` and gets the same group-kill cleanup (WS-001).
- [ ] Non-streaming runs (`communicate` in retry and in Linear) kill and reap the group on timeout. Today:
  - [ ] retry: the `finally` clause pops `_running_procs` before the `except` handler runs, so the handler's `proc.kill()` never fires;
  - [ ] Linear: only the leader is killed.
- [ ] Cancel (`DELETE /api/runs/<run_id>`, the non-project branch) sends SIGTERM to the process group, then SIGKILL to the group after a 5 s grace. The SIGKILL is sent even when the leader has already exited, so a descendant that ignores SIGTERM still dies (WS-002).
- [ ] A cancelled or stalled run stays that way (WS-004, WS-006, WS-007):
  - [ ] exactly one party (worker, cancel or stall) ends a run, by removing its job and proc entries together under `_JOB_LOCK`, and only that party writes the terminal record;
  - [ ] a process launched after its run was cancelled or stalled, including the retry fallback, is killed at registration;
  - [ ] a cancel after the worker ended the run returns 404, and the worker's record stands;
  - [ ] only the owner does terminal side effects (record, tracker push, emits); the stall pass, as owner, completes a Linear-linked run through `_mark_issue_review` with the run's launch generation, so a stalled run reaches In Review with `dispatched` cleared, unless the issue was reset since launch or is Done/Canceled/Duplicate (WS-013);
  - [ ] a worker claims ownership once and keeps it through persistence-error recovery.
- [ ] The two post-inspection fixes get independent Codex review in both the plan review and the build inspection: `_start_counted` constructing and starting the thread inside the release handler (BUILD-009), and `rename_dir` using `os.rename` in `scripts/relocate_checkout.sh` (BUILD-017).
- [ ] The full suite passes: `.venv/bin/python -m pytest tests/ -q -p no:cacheprovider`. The baseline is 410 passed at `5a28e45`.

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
  - [ ] BUILD-016: publish a cache, open it, republish the same agent/registry. Check that the held handle still parses as complete JSON and that its inode differs from the path's current inode. This fails on the old `write_text` (same inode, rewritten).
  - [ ] BUILD-014 group kill: run `sh -c 'sleep 60 & echo $!; exec sleep 60'` through each of `_stream_text_run`, `_stream_claude_run` and `_stream_dsh_run` with `start_new_session=True` and `timeout=1`. Expect `TimeoutExpired`, the leader reaped, and the background `sleep` (pid read from the stream log) gone.
  - [ ] BUILD-014 escaped descendant: a child that starts `sleep 60` with `start_new_session=True` (own group) inheriting stdout, then sleeps. Same three readers with `timeout=1`. Expect `TimeoutExpired` within 10 s, `_INFLIGHT` back to the pre-call value, and reader threads dead. The test kills the escaped sleep afterwards.
  - [ ] Early stdout EOF (WS-001): `sh -c 'exec >/dev/null; sleep 60'` through the three readers with `timeout=1`. Expect `TimeoutExpired` within 10 s and the leader reaped.
  - [ ] Non-streaming retry timeout: drive `_dispatch_cmd`'s communicate branch through the existing retry harness, with a child that has a background descendant and a short `AI_RUN_TIMEOUT_S`. Expect the whole group dead after the retry finishes.
  - [ ] Linear timeout (WS-003): drive the Linear dispatch path through its existing test harness, with a child that has a background descendant and a short timeout. Expect both gone and a timeout record written.
  - [ ] Cancel group kill (WS-002): a running job whose leader exits on SIGTERM and whose descendant ignores SIGTERM (`trap '' TERM`). After `DELETE /api/runs/<run_id>`, expect both gone.
  - [ ] Cancel terminal (WS-004), retry: cancel a resumed retry (stubbed resume command that sleeps). Expect no fallback process to start and the latest run-log record for that run_id to stay `cancelled`.
  - [ ] Cancel terminal (WS-004), `/api/run`: cancel mid-run. Expect no `review` record appended after `cancelled`.
  - [ ] Launch race (WS-004): remove the job (as cancel does) between job publication and `_register_proc`, using a patched `Popen` that removes it. Expect the launched process killed, `_register_proc` returning False, and no run record from the worker. Cover both the first launch and the retry fallback.
  - [ ] Finalization race (WS-006): after the worker's `_end_job` and before its record write (patched `_write_run_log` hook), `DELETE /api/runs/<run_id>` returns 404 and the worker's record is the only terminal one.
  - [ ] Stall then worker (WS-007): the stall pass ends a Linear-dispatched run. Expect the latest record `stalled`, no worker `review` record after it, the issue marked In Review (pushed by the stall pass) and removed from `dispatched`.
  - [ ] Claim once (WS-009): a worker whose first `_write_run_log` call raises once. Expect the error handler to write an `error` record as owner, not to treat the run as cancelled, and not to omit the terminal record.
  - [ ] Reset then stall (WS-013): reset a running Linear-linked issue to Todo, then let its old run stall. Expect the issue still in Todo. Also Done then stall: expect it still Done.
  - [ ] Late non-owner (WS-010): cancel retry A, start retry B for the same issue without a reset, then release A's delayed worker. Expect B's issue state still `running`/In Progress and `dispatched` still pointing at B.
- [ ] Existing FakeProc-based tests (`tests/test_dsh_backend.py`, `tests/test_reset_gen.py`) still pass. This covers the no-`fileno` fallback.

## Progress Checklist
- [x] Revise the plan with the concrete approach (this document)
- [x] Codex plan review returns APPROVED; final plan SHA256 recorded in the review log (round 8, 0ce298f7…)
- [ ] BUILD-016: `_registry_exec_env` writes through `write_text_atomic`
- [ ] Test: a held cache handle stays complete across a republish (fails on old code)
- [ ] `_kill_group` helper added (fallback keeps the requested signal)
- [ ] `start_new_session=True` on the four agent `Popen` sites (three in app.py, one in Linear)
- [ ] `_iter_pipe_lines` / `_iter_pipe_chunks` with select/stop and the no-fileno fallback
- [ ] `_stream_text_run`, `_stream_claude_run` and `_stream_dsh_run` use one deadline, the stop event and the group-kill timeout path
- [ ] Caller timeout handlers use `_kill_group` (app.py and Linear)
- [ ] Non-streaming retry and Linear `communicate` kill and reap the group on timeout
- [ ] Cancel endpoint: SIGTERM to the group, grace, unconditional SIGKILL to the group, reap
- [ ] `_register_proc` handshake at all four launch sites (incl. retry fallback); claim-once `end()` → `_end_job` at every worker terminal point; cancel and stall pop both entries under `_JOB_LOCK`; only the owner does terminal side effects
- [ ] Stall pass uses `_kill_group` and completes a Linear-linked run through `_mark_issue_review(issue_id, gen=launch_gen)`; Linear dispatch and retry store `launch_gen` in the job
- [ ] Test: reset-then-stall leaves the issue in Todo; Done-then-stall leaves it Done
- [ ] Test: group kill on timeout for all three readers (background descendant gone)
- [ ] Test: escaped descendant holding stdout; readers stop and in-flight returns, all three readers
- [ ] Test: early stdout EOF still times out (text, Claude, dsh)
- [ ] Test: non-streaming retry timeout kills the group
- [ ] Test: Linear dispatch timeout kills the group
- [ ] Test: cancel kills a SIGTERM-ignoring descendant after the leader exits
- [ ] Test: a cancelled resumed retry starts no fallback and stays `cancelled`; a cancelled `/api/run` appends nothing after `cancelled`
- [ ] Test: launch race kills the process (first launch and fallback)
- [ ] Test: cancel after `_end_job` returns 404 and the worker record stands
- [ ] Test: stall then worker keeps `stalled` and still marks the Linear issue In Review
- [ ] Test: a one-shot persistence failure after the claim still writes an owner `error` record
- [ ] Test: a late non-owner worker leaves retry B's issue state and `dispatched` alone
- [ ] Full suite passes (`.venv/bin/python -m pytest tests/ -q -p no:cacheprovider`)
- [ ] Runner restarted (`launchctl kickstart -k gui/$(id -u)/com.agenticos.runner`) and `/api/maintenance` answers with `inflight` 0
- [ ] Fresh cross-provider (Codex) build inspection, base `5a28e45`, returns no unresolved material findings; it explicitly covers BUILD-009 and BUILD-017
- [ ] Public-repo check: `git grep` for the private project names (pattern kept outside the repo) finds nothing in tracked files
- [ ] Commit (not pushed)
