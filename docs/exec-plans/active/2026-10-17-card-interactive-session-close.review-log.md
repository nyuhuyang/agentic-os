# Review log: card interactive session close

- Host / planner: Claude Code (Opus 5.5). Plan reviewer: Codex (CLI config model). Builder: Claude (default). Inspector: fresh Codex session.
- Fallback: same-provider-on-unavailable. Rounds: max 20. Inspection: on.
- Authorization: user asked to fix the bug and "think how to fix" (2026-10-17). Session is non-interactive: Q1–Q3 locked at the recommended answers pending user confirmation; build and the WIP commit of the 2026-10-16 index.html work are NOT authorized yet.
- Budget: one Codex plan review + one Codex inspection at CLI-default effort (rough: 1–2 medium sessions); stated to the user, no reduction requested.
- Recon evidence: live runner term `537bf733` (AGE-105, run d04019d7) still running claude; retry 409 ×2 in runner.err.log 05:42:32-33; isolated runner 8599 reproduction of the `exec $SHELL -l` fallback.

## Round 1 — Codex (REVISE)
Result: /private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/26a69158-7491-43cc-b4a8-908d071b16b1/scratchpad/claudex/r1/claudex-sw9vwi1o/result.json

Summary: The plan misses active refusal paths and a board Retry caller. It also needs to preserve client state on cancellation and suppress obsolete next-state choices during end-and-continue actions.

- **R1 (high)** runner/app.py:3902: Step 2 targets _resume_admission, but Projects Resume returns 409 'still running' directly from api_session_to_board when _live_session_ids includes the terminal. Session-card replies instead return in_use_elsewhere from _retry_session_card_held at line 4301, then a separate reserve_card failure at line 4317 after confirmation. Ordinary retries can also return in_use_elsewhere at line 5142 before reaching the planned TicketLocked branch. These paths bypass _resume_admission, so the proposed client helper receives no card_interactive code and cannot offer the required ending flow.
  Fix: Classify terminal ownership at the actual HTTP refusal sites, including to-board, both retry advisory branches, and session-card reserve_card failures. Return card_interactive metadata before the existing external-session advisory when a dashboard terminal is responsible. Preserve existing responses for headless jobs and external processes.
- **R2 (medium)** runner/templates/index.html:2659: Board ↺ buttons call retryRun directly. Step 3 names retryFromDetail as the Retry integration point, which this caller bypasses. Even with corrected server metadata, clicking Retry on the board would still reach retryRun's generic failure alert instead of the AC2 confirmation.
  Fix: Handle card_interactive in the shared _postRetry/retryRun request path used by board Retry, detail Retry, and reply submission. Preserve the original request body and allow only one resend.
- **R3 (medium)** runner/templates/index.html:3583: AC2 requires No to change nothing, but saveLinearIssue currently applies optimistic state, clears the draft, advances _detailLinearInitial, and closes the modal before either PATCH response arrives. _moveLinearIssueToColumn similarly changes optimistic state and cancels dictation before refusal handling. retryFromDetail clears attachments immediately after starting retryRun. Adding a confirmation only at the refusal sites leaves these changes in place when the user declines.
  Fix: Defer draft clearing, attachment removal, dictation cancellation, saved-state bookkeeping, and modal closure until the request succeeds. On decline or failure, restore optimistic state and retain the captured form contents and attachments. Ensure a resend uses the original captured payload.
- **R4 (medium)** runner/templates/index.html:4758: Closing an attached terminal emits term_exit, whose existing card and panel listeners call _offerCardNext. The proposed end-and-continue and move helpers do not suppress this path. For a session shown in the panel, an In Progress drag followed by Yes can reopen the detail modal with Mark done/Todo/Review choices while the replacement request starts. Those choices can subsequently overwrite the requested move or reset the new attempt's generation.
  Fix: Distinguish a close performed for a pending retry/move from a standalone End session or natural exit. Reserve suppression before emitting term_close, consume the obsolete next-state choice on successful continuation, and restore appropriate UI on failure. Cover both term_exit-before-ack and ack-before-term_exit ordering.

### Claude dispositions
Dispositions for round 1 (all accepted, plan revised):
- R1 (high) ACCEPTED: Step 2 now lists the six real HTTP refusal sites (to-board "still running"; session-card reply in_use_elsewhere and reserve_card; ordinary retry in_use_elsewhere and TicketLocked; tracker PATCH TicketLocked). card_terminal() is checked before the existing advisory; responses unchanged when no dashboard terminal is responsible. Tests cover each site.
- R2 (medium) ACCEPTED: handling moved into the shared _postRetry/retryRun path (board ↺, detail ↺, reply), resend reuses the captured body, once.
- R3 (medium) ACCEPTED: new Step 3b defers draft/attachment/dictation/_detailLinearInitial/modal-close/optimistic state until success; restored on decline/failure.
- R4 (medium) ACCEPTED: _endCardSession pre-adds the term to _offeredTerms before term_close (covers term_exit-first and ack-first orderings), removes it on failed close; only the standalone End session offers the next-state choice.

## Round 2 — Codex (REVISE)
Result: /private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/26a69158-7491-43cc-b4a8-908d071b16b1/scratchpad/claudex/r2/claudex-i2aff1eg/result.json

Summary: The revision incorporates the four prior fixes. Two additional edge cases remain: failed-close finalization and Resume of an older session belonging to a locked card.

- **R5 (high)** runner/modules/pty/__init__.py:239: close_terminal sets t.closing=True before cleanup, but its exception path never clears it. If process enumeration fails or times out, then the agent exits, _reader marks the terminal dead and skips _finalize because t.closing remains true (line 187). Its card/ticket locks remain held. The planned lookup and badge both exclude dead terminals, recreating an invisible lock with no end-and-continue recovery. Step 4 explicitly allows continuing after a failed close without addressing this server state.
  Fix: Restore finalization ownership on cleanup failure, including the race where the reader already exited during cleanup. Preserve retryable cleanup state while processes remain, and ensure verified exit releases holds and audits exactly once. Add regression coverage for cleanup failure followed by exit, and exit during failed cleanup.
- **R6 (medium)** runner/app.py:4199: Projects Resume has another refusal after the newly covered session-id check. Suppose sessions A and B both belong to one card, and B holds its live interactive terminal. Resume on older session A passes api_session_to_board's live-session check, then _session_card resolves the shared card and _to_board_locked returns generic 409 'still running' through card_locked. Step 2 does not cover this branch or its subsequent reserve_card exception at line 4208. Multiple historical sessions per card are supported by _session_card and the existing test_to_board_on_a_found_card_moves_it_to_todo_and_keeps_its_history.
  Fix: Extend terminal classification to _to_board_locked's card-lock refusal and reservation failure, using the resolved card/ticket identity. Preserve headless-only refusals. Cover Resume of an older session while another session holds the same card.

### Claude dispositions
Dispositions for round 2 (both accepted, plan revised):
- R5 (high) ACCEPTED: new Step 6 — on _kill_session failure, close_terminal clears t.closing under _finalize_lock and finalizes itself if the reader already marked the terminal dead; _finalize's once-guard keeps the audit single; the terminal stays registered (cleanup_failed) and matchable while alive so the close can be retried. Regression tests: failure-then-exit, and exit-during-failed-cleanup.
- R6 (medium) ACCEPTED: Step 2 now also covers _to_board_locked's card_locked "still running" branch and its reserve_card failure, classified by the resolved card key and (project, ident); test: Resume of older session A while session B holds the card's live terminal; headless-only refusal unchanged.

## Round 3 — Codex (REVISE)
Result: /private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/26a69158-7491-43cc-b4a8-908d071b16b1/scratchpad/claudex/r3/claudex-1erk8zw1/result.json

Summary: The prior fixes are incorporated. Step 6 needs an explicit lock boundary to avoid a self-deadlock in its new recovery path.

- **R7 (high)** docs/exec-plans/active/2026-10-17-card-interactive-session-close.md:94: Step 6 describes recovery under _finalize_lock and says to call _finalize(t) 'there' when the reader has already marked the terminal dead. _finalize_lock is a non-reentrant threading.Lock (pty/__init__.py:100), and _finalize immediately acquires it again (line 107). Invoking it within that recovery critical section deadlocks the close handler before releasing the card's holds and blocks finalization of other terminals.
  Fix: Explicitly clear t.closing and capture whether finalization is needed under _finalize_lock, then release the lock before calling _finalize(t). Retain its existing once-guard. Ensure the exit-during-failed-cleanup regression checks that close returns and the lock is released.

### Claude dispositions
Dispositions for round 3:
- R7 (high) ACCEPTED: Step 6 rewritten. Decisions are taken under _finalize_lock and _finalize is called only after releasing it. Also fixed a race the old wording left open (reader read t.closing without the lock, close checked t.alive set under a different lock, so both sides could skip): a new t.reader_done flag set by the reader under _finalize_lock; reader owns finalize iff not t.closing; failed close clears t.closing and finalizes iff t.reader_done — serialized, exactly one side finalizes. Tests assert close returns (timeout-bounded) and the lock is free in both orders.

## Round 4 — Codex (APPROVED)
Result: /private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/26a69158-7491-43cc-b4a8-908d071b16b1/scratchpad/claudex/r4/claudex-3f4otyb7/result.json
Plan SHA256: 43884eea8d8e7b70ccfb1c5f8d7d310f810c654e69d95b7884beb9ffcecd9115 (approval check run).
Summary: The revision addresses R1–R7. The explicit reader_done handoff and finalization outside _finalize_lock resolve the last finding. No material unresolved plan defects identified.
Limitations: static plan review; implementation unverified.

## Status
Approved after 4 rounds (7 findings, all accepted). Build NOT started: awaiting user confirmation of Q1–Q3 and how to isolate the uncommitted 2026-10-16 index.html work.
