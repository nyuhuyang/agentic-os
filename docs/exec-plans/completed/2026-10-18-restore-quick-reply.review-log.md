# Review log: restore quick reply

- Host / builder: Claude Code (Opus 5.5). Inspector: fresh Codex session. Base: a2cf449.
- Authorization: user, 2026-10-18: "commit, but don't close it. One more thing. You removed quick reply, please add it back and make it work". No separate plan review (small, user-specified scope); a fresh Codex inspection of the diff.
- Verification so far: full suite 730 passed; manual QR1–QR6 on an isolated runner (see plan).

## Inspection 1 — Codex (fresh session, base a2cf449): REVISE
Result: /private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/26a69158-7491-43cc-b4a8-908d071b16b1/scratchpad/claudex/q1/claudex-0h9ntbac/result.json
Summary: Five concrete defects remain in failure recovery, asynchronous state handling, and latest-attempt eligibility.

- **QR-001 (medium)** runner/templates/index.html:4879: Failure reporting reads last_message, but /events exposes only assistant output, not the recorded error (app.py:4614–4617). Project/session workers can record a Codex turn.failed reason, launch exception, or timeout solely in error. The status then shows generic 'error'/'timeout', or unrelated partial output, instead of the server's reason, violating QR5.
  Fix: Expose the appropriately sanitized recorded error through /events and prefer it when reporting an unsuccessful reply.
- **QR-002 (medium)** runner/templates/index.html:4875: The completion handler discards quickReply before classifying the outcome and restores text only for error, timeout, and stalled. Cancellation writers produce status 'cancelled' (app.py:3138, 3391, 5466). An accepted reply subsequently cancelled or dropped before launch is treated as successful: its text remains cleared and its status message disappears.
  Fix: Restore the pending text for cancelled and other unsuccessful terminal outcomes. Clear recovery state as successful only for explicitly successful outcomes.
- **QR-003 (medium)** runner/templates/index.html:4918: sendingReply belongs to the shared _cardTerm object but is neither reset by _cardTermBind nor generation-guarded in finally. Send on A, open stopped card B while A's request is pending, and let B finish loading: B inherits 'Sending…'. When A resolves, finally clears the flag, then the generation check returns before updating B's controls. B remains disabled until another terminal reload.
  Fix: Reset sending state when binding a card and associate each pending request with its generation or ownership token. Only its current owner should clear the flag and refresh controls.
- **QR-004 (medium)** runner/templates/index.html:4895: latestRunId is refreshed only when opening the terminal or after this box sends. Board refreshes and run-state notifications do not refresh the attempt list. If another browser starts and completes attempt B while this modal shows A, A remains enabled as 'latest'. The server's strict guard checks session-id equality rather than latest run identity (app.py:5253), so A's stale reply is accepted when both attempts use the same session. This violates QR3.
  Fix: Refresh attempt eligibility when the card gains an attempt, and validate latest-attempt identity server-side during strict retry admission.
- **QR-005 (medium)** runner/templates/index.html:4875: Project retry returns success after starting a background thread (app.py:5386–5398), while _running_jobs is populated later inside _run_project_ticket_locked, after acquiring the project lifecycle lock. If that worker is delayed, the immediate /events request reports finished:true with status:null because no job or record exists yet (app.py:4609). The new handler treats that as success and discards quickReply. A later actual failure can no longer restore the sent text; the box is also enabled during the pending launch.
  Fix: Publish pending launch state before returning the run id, and require a known terminal outcome before consuming quickReply. Treat missing or indeterminate event metadata as loading, with replies disabled.

### Claude dispositions (all accepted, fixed, verified)
- QR-001: `/api/runs/<id>/events` returns the recorded `error` (already withheld where records may leak); the quick reply's failure line prefers it. Test + browser: "reply not completed: You've hit your session limit · resets 10:50pm".
- QR-002: only `review`/`success` count as success; every other recorded outcome (error, timeout, stalled, cancelled…) gives the text back with its reason.
- QR-003: the sending state is a per-send token, reset when a card is bound; only its own send clears it.
- QR-004: a board refresh that shows the open card's latest attempt changed refreshes the attempt list (the viewed attempt stays selected) and the box's eligibility; the server refuses a strict reply to anything but the card's newest record ("a newer attempt exists on this card"). Test + browser (another tab replied → this page shows "Viewing an earlier attempt", server refuses the stale send).
- QR-005: a reply whose run has no job and no record yet is pending, not finished: the box says "Starting…" and the outcome is re-read until it is known.
- Full suite after inspection-1 fixes: 731 passed.

## Inspection 2 — Codex (fresh session, base a2cf449): REVISE
Result: /private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/26a69158-7491-43cc-b4a8-908d071b16b1/scratchpad/claudex/q2/claudex-1c4v8gvu/result.json
Summary: Three concrete defects remain in latest-attempt eligibility and recovery from event-fetch failures.

- **QR-R2-001 (medium)** runner/templates/index.html:2930: The new _cardTermSyncLatest call is unreachable during normal refreshes while the detail modal is open: _shouldDeferBoardRefresh returns true for any open task modal (2358), and refreshJobBoard returns before synchronization (2862). Socket notifications and the periodic refresh use this deferred path. If another tab starts attempt B while this modal displays stopped attempt A, A remains labeled latest with quick reply enabled, violating QR3.
  Fix: Refresh the open terminal's attempt metadata independently of deferred board rendering, including on run-state and run-logged notifications. Preserve the selected attempt and update reply eligibility.
- **QR-R2-002 (medium)** runner/app.py:5256: The strict guard equates the last appended record with the newest attempt. However, api_run_set_status appends copies of existing attempts (5062–5076), whereas /history deduplicates by run_id and sorts by started_at. With attempts A then B using the same session, marking A successful appends A again; quick reply to the actual latest attempt B is then rejected as stale. Skipping archived records without deduplication also allows an archived attempt's earlier record to reappear in this scan.
  Fix: Resolve each run's effective latest record first, exclude archived runs and closure audits, then select the newest attempt using the same ordering as /history. Share this selection logic between history and strict admission.
- **QR-R2-003 (medium)** runner/templates/index.html:4922: When /events fails or returns non-2xx, _cardTermLoad stores its fallback {lines: []} as data (4860–4866). This truthy object has neither finished nor status, so _cardTermReplyState enables Send despite unknown run state. Failure recovery also schedules another fetch only when finished is true. If an accepted reply finishes unsuccessfully before this failed fetch, its completion notification can already have been missed while the previous attempt was displayed; the cleared reply text and failure reason remain unrecovered until a manual reload.
  Fix: Require explicit stopped metadata before enabling a headless quick reply. Represent fetch failures as unknown state, display a retryable error, and retry outcome retrieval while quickReply remains unresolved, preserving its text.

### Claude dispositions (all accepted, fixed, verified)
- QR-R2-001: the open card re-reads its own attempt history (not the deferred board) on `run_logged` and on a run starting, keeping the viewed attempt selected and updating eligibility. Browser: another tab replied while this card stayed open → "Viewing an earlier attempt", no board refresh needed.
- QR-R2-002 (server): `_newest_attempt` orders a card's attempts as its history does (each run's latest record, running attempts included, archived runs and closure audits excluded, by started_at); the strict guard uses it. Test: marking older attempt A done (which appends A again) leaves B the latest; a reply to A is refused.
- QR-R2-003: a failed events fetch is "unknown", never "stopped": the box stays disabled ("Loading…"), the status says it is retrying, and the load is retried; a quick reply's outcome is therefore still read once the fetch succeeds.
- Full suite after inspection-2 fixes: 732 passed.

## Inspection 3 — Codex (fresh session, base a2cf449): REVISE
Result: /private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/26a69158-7491-43cc-b4a8-908d071b16b1/scratchpad/claudex/q3/claudex-vypb8g0s/result.json
Summary: Strict replies can still resume a different session or bypass latest-attempt validation. History-fetch failures and interactive metadata recovery also leave incorrect reply eligibility.

- **QR-R3-001 (medium)** runner/app.py:5277: Card A previously used S0, then its latest attempt used S1. If another card subsequently owns S1, the strict identity check at 5259 passes before session resolution clears S1 and substitutes A's older S0 through _card_session. The guard at 5363 does not refuse because S0 is nonempty and card_note is unset. The reply therefore resumes S0 despite promising the latest attempt's same session, violating QR2.
  Fix: Preserve the requested attempt's session identity throughout strict admission. Refuse an ownership conflict or any replacement session, including before the transient _retry_session_card return.
- **QR-R3-002 (medium)** runner/app.py:5204: A valid persisted session intent returns through _retry_session_card before strict is parsed or _newest_attempt is checked. With session-card attempts A then B, PATCHing A to success appends A again while preserving resume_session (5062–5076). _valid_intent uses append order (3788–3812), so A becomes valid again even though history correctly identifies B as newest. A strict reply to A is accepted, bypassing QR3.
  Fix: Apply the shared strict latest-attempt check to every retry path, including persisted intents. Revalidate during card-lock admission before tracker changes or launch.
- **QR-R3-003 (medium)** runner/templates/index.html:4909: _cardTermSyncLatest calls _cardTermAttempts, which treats a failed history fetch as an empty chain and replaces latestRunId with the originally opened run (4818–4832). After B is discovered while stopped A remains displayed, one failed synchronization relabels A as latest and enables its reply box. Overlapping requests can similarly overwrite B with an older snapshot because the generation guard distinguishes cards, not history requests. This violates QR3.
  Fix: Preserve successful history on fetch failure, mark eligibility unknown where necessary, and retry. Sequence history requests so superseded responses cannot overwrite newer metadata.
- **QR-R3-004 (low)** runner/templates/index.html:4840: When opening a retained interactive terminal, _cardTermUse stores unknown:true after a transient /events failure but still returns true, allowing attachment. _cardTermReplyState then disables quick reply as Loading indefinitely. Unlike _cardTermLoad, this path schedules no metadata retry; subsequent history synchronizations and interactive reconnects do not replace the unknown data.
  Fix: Retry interactive metadata retrieval with card, attempt, and terminal ownership guards, preserving the attached terminal. Show a retryable loading error until eligibility is known.

### Claude dispositions (all accepted, fixed, verified)
- QR-R3-001 (server): a strict reply keeps the answered attempt's session identity: it is refused ("this card's current session is not the one this attempt used…") if the persisted intent, the transient session-card route or the resolved lock session would continue any other session. Test with the lock's session owned by another card and an older session substituted → refused, nothing launched.
- QR-R3-002 (server): the latest-attempt check runs at the top of the retry route, before the persisted-intent branch, so every path is covered. The history-order test now carries a persisted intent on the re-appended older attempt.
- QR-R3-003: history requests are sequenced (a superseded response is dropped); a failed history read keeps the known attempts, marks eligibility unknown ("Loading…") and retries.
- QR-R3-004: unreadable metadata for the attempt on screen (e.g. an attached interactive session) is re-read every 2 s until known, without detaching the terminal.
- Browser smoke after the changes: reply continues the same session and streams in place; with the interactive session open, accept ends it and continues; another tab's newer attempt disables this page's box.
- Full suite after inspection-3 fixes: 733 passed.

## Inspection 4 — Codex (fresh session, base a2cf449): REVISE
Result: /private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/26a69158-7491-43cc-b4a8-908d071b16b1/scratchpad/claudex/q4/claudex-_pasryod/result.json
Summary: Four defects remain in strict retry admission, failure recovery, and history synchronization.

- **QR-R4-001 (medium)** runner/app.py:5204: Latest-attempt validation runs before session discovery and card-lock acquisition. A request answering A can pass this check, pause during session discovery, and acquire the lock after another request has completed attempt B using the same session. Neither ordinary admission at 5371–5386 nor session-card admission at 4441–4449 rechecks the requested run identity. Persisted intent equality also remains true when B retains the same intent. The stale reply to A is therefore admitted, violating QR3.
  Fix: Revalidate the requested run against _newest_attempt after acquiring the card reservation on every strict retry path, before tracker changes or scheduling. Release reservations and session claims when refusing.
- **QR-R4-002 (medium)** runner/templates/index.html:4906: Failure recovery only executes when _cardTermLoad loads quickReply.runId. Send a reply creating B, then select older attempt A while B runs. B's completion is ignored by the viewRunId condition at 5261; run_logged only refreshes history. Even if B fails, the reply text remains cleared and its error is never shown unless the user manually selects B. Closing the card then discards the remaining recovery state. This violates QR5.
  Fix: Track the pending reply's outcome independently of the displayed attempt. On completion, fetch its metadata and preserve failed text and the error for the owning card without switching the terminal view.
- **QR-R4-003 (low)** runner/templates/index.html:4828: History retry scheduling requires an existing latestRunId. _cardTermBind resets that value to null, so a transient failure of the first history request skips the retry branch, sets historyUnknown=true, and leaves Send disabled as Loading. On an otherwise idle card, periodic board refreshes are deferred while the modal is open, so recovery requires reopening the card or an unrelated run notification.
  Fix: Schedule a generation-guarded history retry for every failed history request, including the initial request, while keeping reply eligibility unknown.
- **QR-R4-004 (low)** runner/templates/index.html:5276: Reconnect reloads the displayed run's events but does not refresh attempt history. If another browser creates B while this browser is disconnected with stopped A open, the missed running/run_logged notifications are not reconciled. After reconnect, A remains marked latest with Send enabled; periodic board refreshes still defer while the modal is open. The server refuses the stale send, but QR3's eligibility remains incorrect.
  Fix: Refresh attempt history on reconnect independently of board rendering, preserve the viewed attempt, and keep Send disabled until current history is known.

### Claude dispositions (all accepted, fixed, verified)
- QR-R4-001 (server): a strict reply re-checks the latest attempt under the card's lock (ordinary path) and under the card's reservation (session-card path), releasing its claims when refused. Test: a newer attempt appears between the first check and the lock → refused, nothing launched.
- QR-R4-002: pending quick replies are tracked by run (`_pendingReplies`), independent of the attempt or card on screen; their run stopping (run_state_change, reconnect, or a load of that run) resolves them: success is done, any other outcome gives the text and reason back to its card — at once if open, else when that card opens (`_unsentReplies`). Browser: a failing reply while viewing an older attempt restored its text; one that failed while the card was closed was restored on reopening.
- QR-R4-003: every failed history read is retried (the first included) while replies wait.
- QR-R4-004: a disconnect marks the open card's history unknown (replies wait); reconnect re-reads it.
- Full suite after inspection-4 fixes: 734 passed.

## Inspection 5 — Codex (fresh session, base a2cf449): REVISE
Result: /private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/26a69158-7491-43cc-b4a8-908d071b16b1/scratchpad/claudex/q5/claudex-p71nx542/result.json
Summary: Two unresolved defects remain in quick-reply failure recovery across navigation and completion notifications.

- **QR-R5-001 (medium)** runner/templates/index.html:5001: Send from card A, then close it or open B before the retry POST resolves. The generation check returns before the accepted run is registered in _pendingReplies at line 5007. If that run fails, neither its completion notification nor reopening A can restore the reply text or report its reason. _cardTermBind also clears the input. This violates QR5 and leaves the previous navigation-recovery finding partly unresolved.
  Fix: Register accepted replies and begin outcome reconciliation independently of the current view, before the generation check. Guard only mutations of the visible card. Preserve request failures under the originating card key as well.
- **QR-R5-002 (medium)** runner/templates/index.html:4943: Pending outcomes are checked on non-running run_state_change notifications, but run_logged only refreshes history (line 5284). Both queued-cancellation writers in app.py:4552–4557 and 5492–5501 record cancelled and emit only run_logged. If an accepted reply is dropped because its card was removed/reset before launch, after the user closes the card or selects another attempt, its cleared text and cancellation reason remain unrecovered. _checkReply also stops checking when it observes finished:false, so an earlier check does not bridge this gap.
  Fix: Reconcile matching pending replies on run_logged and continue bounded polling while their outcome remains unresolved. Keep outcome tracking independent of the displayed attempt and deduplicate scheduled checks.

### Claude dispositions (both accepted, fixed, verified)
- QR-R5-001: an accepted reply is registered and followed right after the request returns, before the view check; a refused or declined one whose card is no longer on screen keeps its text (and reason) for that card. Browser: send on A, open B before the response, the reply fails → B untouched; reopening A shows the text and "reply not completed: You've hit your session limit…".
- QR-R5-002: each pending reply has one outcome check at a time that keeps polling every 3 s until its outcome is known; `run_logged` (the only signal of a cancelled launch) also triggers the checks.
- Full suite after inspection-5 fixes: 734 passed.

## Inspection 6 — Codex (fresh session, base a2cf449): REVISE
Result: /private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/26a69158-7491-43cc-b4a8-908d071b16b1/scratchpad/claudex/q6/claudex-yqcqzlp4/result.json
Summary: Three defects remain in session selection, failure recovery, and reply eligibility.

- **QR-R6-001 (medium)** runner/app.py:5257: Session selection still uses append order: _get_task_agent_lock (2696–2742) selects the last appended session. Given same-task, same-generation attempts A/S1 then B/S2, PATCHing A to success appends A again (5067–5081). _newest_attempt correctly identifies B, but strict retry of B then rejects it at 5270 because the lock selects S1. The added history-order test neither uses different sessions nor actually retries B.
  Fix: Resolve the current session consistently with effective attempt ordering while preserving reset boundaries and ownership checks. Add coverage that retries B after a status copy of A, using distinct session IDs.
- **QR-R6-002 (medium)** runner/templates/index.html:5006: Send from A, close and reopen A before the POST returns, then receive a refusal or connection failure. Reopening clears the input and changes the generation. The response consequently stores the text in _unsentReplies and returns, even though A is already open. That map is consumed only during opening (3296–3297), so the current card shows neither the failed text nor its reason until another reopening, violating QR5.
  Fix: Preserve failures independently of view generation, then reconcile them immediately when the currently open card has the originating key. Preserve any newer draft separately.
- **QR-R6-003 (low)** runner/templates/index.html:5001: After an accepted POST, sendingReply is cleared and _cardTermReplyState runs against the previous stopped attempt before awaiting history. If history synchronization is delayed, Send becomes enabled while the new attempt is running. Another Enter targets the previous latestRunId and receives a stale-attempt refusal. This violates QR3 during the transition.
  Fix: Immediately publish the returned attempt as pending and invalidate the previous metadata before updating controls. Keep Send disabled until the new attempt's state is known.

### Claude dispositions (all accepted, fixed, verified)
- QR-R6-001 (server): when the answered attempt is the card's newest by history order, a strict reply uses that attempt's own session as the card's current one (ownership, transcript and folder checks still apply), instead of the session the task lock picked by append order. Test: A/S1, B/S2, A re-appended by a status change → quick reply to B continues S2.
- QR-R6-002: a refused, failed or declined send whose card was closed and reopened meanwhile shows its text and reason in that open card at once; otherwise it is kept for when the card opens.
- QR-R6-003: an accepted reply keeps the box in "sending" until its own attempt is on screen, and marks it the latest at once, so a second Enter can never target the previous attempt. Browser: the box stayed disabled from Send through the run ("The agent is working") and re-enabled when it stopped.

## Stop
User decision 2026-10-18 ("好的，同意"): stop the inspection loop after inspection 6 because of cost; commit after a passing full suite and restart the live runner. The inspection-6 fixes (QR-R6-001..003) are covered by tests and a browser check but were not re-inspected.
- Full suite before commit: 735 passed.
