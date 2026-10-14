# Review Log: Two-pass voice input

## Setup — 2026-10-14
- Workflow: claudex-loop 2.2.2, mode=review (plan written in-session after recon of `runner/modules/stt/__init__.py` and `runner/templates/index.html` STT code)
- Roles: host/planner = Claude Code (Opus 5.5); plan reviewer = Codex CLI (default model/effort); builder = Claude (default); inspector = fresh Codex session
- Authorization: plan review only; build NOT authorized ("先写成计划，别急着做")
- Budget: default model, MAX_ROUNDS=5 (carried over from user's choice on the 2026-10-13 plan); at round 5 without convergence STOP and ask: (a) continue to 20, (b) cut scope + restart, (c) lock with Open Issues
- Fallback: same-provider-on-unavailable; inspection on
- Known open questions in the plan (user-owned): polish model id; permission to call `models.list()`; private glossary contents
- Privacy: public repo — no project names/paths in plan, log or glossary

## Round 1 — Codex (2026-10-14)
- Result: `<session-scratchpad>/claudex-stt/r1/result.json`
- Session 01a13bad-8e3a-75a1-af54-6bd5c036a3b4 · codex-cli 0.162.0 · model: CLI default (observed unknown) · assurance cross_provider · plan sha256 89e1a3dd…
- Verdict: **REVISE** (3 high, 5 medium)

```json
{
 "verdict": "REVISE",
 "summary": "The plan hash matches. The transcription request is incompatible with the documented API, and the frontend plan leaves concrete overwrite, lifecycle, and persistence defects unresolved.",
 "findings": [
  {
   "id": "STT-01",
   "severity": "high",
   "path": "docs/exec-plans/active/2026-10-14-stt-two-pass.md:30",
   "evidence": "Step A specifies language='zh', but gpt-transcribe uses languages instead of language. The installed OpenAI SDK 2.36.0 also has no direct keywords or languages arguments in audio.transcriptions.create (.venv/lib/python3.12/site-packages/openai/resources/audio/transcriptions.py:441). Passing keywords directly raises TypeError; retaining language sends the wrong request contract. See [official OpenAI documentation](https://developers.openai.com/api/docs/guides/speech-to-text).",
   "fix": "Specify prompt and JSON output explicitly, and pass keywords plus languages=['zh'] through extra_body with the installed SDK. Remove singular language from the outbound request. Update Phase 0 and the fake-client assertions to verify this exact shape."
  },
  {
   "id": "STT-02",
   "severity": "high",
   "path": "runner/templates/index.html:3309",
   "evidence": "The replacement rule checks field text but does not establish recording or issue ownership. Upload completion reads the mutable global _micTranscriptBase (3338), and cleanup can stop/reset a newer recording (3238). In final-only mode, recording A can start with an empty reply, then its modal can close and issue B can open with the same empty reply; A's response passes a text-equality check and inserts A's instructions into B. Draft keys and retry dispatch use the current issue identity (1528–1535, 1640, 2696).",
   "fix": "Require a per-recording context containing immutable base text, expected value, chunks, target element, issue identity, modal generation, and request token. Validate ownership on every callback, hint action, and cleanup. Invalidate pending sessions on modal close, issue switch, submission, and dispatch; ensure old callbacks cannot reset a newer session."
  },
  {
   "id": "STT-03",
   "severity": "high",
   "path": "runner/templates/index.html:3122",
   "evidence": "The plan preserves today's live rendering, which unconditionally assigns base + transcript and updates _micLastRenderedValue. Only the reply input stops recognition on manual edits (3425–3447); editing either description remains vulnerable. Attachment handlers also append paths without input events (3803–3842). A subsequent recognition result erases an edit or attachment path, updates the expected value, and lets the final replacement check pass.",
   "fix": "Apply the unchanged-value guard before every live write, not only final replacement. On any external change, preserve the field and stop writing into it or maintain a tracked insertion range. Cover typing and programmatic attachment writes for all three targets, including while permission acquisition is pending."
  },
  {
   "id": "STT-04",
   "severity": "medium",
   "path": "runner/templates/index.html:3689",
   "evidence": "The Linear-description and new-issue controls both use mic-btn-desc and mic-status-desc (800–803 and 3689–3692). getElementById therefore resolves the earlier Linear controls when the new-issue mic runs. Recording and refining status appear in the wrong modal, and button identity cannot distinguish these targets. Removing selectors does not resolve these remaining duplicate IDs.",
   "fix": "Give each mic button, status element, and refinement hint a unique ID, or resolve controls relative to the target field. Include both description modals in verification."
  },
  {
   "id": "STT-05",
   "severity": "medium",
   "path": "runner/templates/index.html:3441",
   "evidence": "Live rendering assigns .value without persisting a draft (3122–3128). Browser-only and transcription-failure paths therefore have no successful upload input event to save the spoken text. Additionally, _bindDraftPersistence runs at 3468 before new-issue markup is parsed at 3662, so its new-issue listeners are never attached. Closing and reopening that modal restores the old stored description (1616, 3725), losing speech even if refinement dispatched an input event.",
   "fix": "Bind draft listeners after all modal markup exists, and persist each accepted live, refined, and raw replacement using the recording's valid owner. Update the expected rendered value before dispatching input so persistence does not falsely classify the write as a user edit."
  },
  {
   "id": "STT-06",
   "severity": "medium",
   "path": "runner/templates/index.html:3276",
   "evidence": "The existing recorder requires audio/webm and labels every upload recording.webm (3277, 3315–3322). The plan does not add recorder-format negotiation or recorder-start failure handling. On a browser that supports recording only another format, construction fails and the promised final-only fallback cannot run. The acquired stream is also leaked because cleanup retains no stream reference when construction fails. Format support must be checked independently of SpeechRecognition support; see [MediaRecorder documentation](https://developer.mozilla.org/en-US/docs/Web/API/MediaRecorder/isTypeSupported_static).",
   "fix": "Negotiate an API-supported recording MIME type and matching filename, retain the acquired stream for cleanup, and handle missing MediaRecorder, constructor/start failures, and asynchronous errors. Preserve browser recognition when recording alone fails; stop all acquired tracks when capture cannot continue."
  },
  {
   "id": "STT-07",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-14-stt-two-pass.md:44",
   "evidence": "The plan promises polish fallback after eight seconds but does not define a total deadline or retry policy. The existing client uses SDK defaults (runner/modules/stt/__init__.py:255): a 600-second timeout and two retries (_constants.py:9–10). Even setting timeout=8 alone allows three timed-out attempts plus backoff (_base_client.py:1042–1052), delaying raw-transcript fallback well beyond eight seconds.",
   "fix": "Specify an eight-second total polish deadline, disable automatic retries for that stage, and ensure late work cannot update the result. Also bound transcription and frontend waiting so a stalled Step A does not leave refinement pending indefinitely. Add timeout and retry-policy cases to the planned validation."
  },
  {
   "id": "STT-08",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-14-stt-two-pass.md:39",
   "evidence": "The glossary is passed directly as keywords, including arbitrary private extras, without validation requirements. A private entry such as '<ProjectX>' causes the entire transcription request to be rejected; excessive browser_text context also triggers rejection. These are documented request constraints, so a malformed optional glossary can disable refinement for every utterance. See [official transcription constraints](https://developers.openai.com/api/docs/guides/speech-to-text).",
   "fix": "Define trimming, deduplication, keyword-character validation, and context-length limits before calling OpenAI. Treat missing, unreadable, or invalid optional extras as a recoverable glossary warning and retain the generic glossary."
  }
 ],
 "coverage": [
  "Read the on-disk plan and verified SHA256 89e1a3dd97b3260b4f0ef8ce994564546dd025f917972c9976ce62f5d3a55ca8.",
  "Inspected STT HTTP handling, capabilities, realtime worker and handlers, frontend capture/upload/rendering, and all three mic entry points.",
  "Traced modal ownership, draft storage/restoration, attachment writers, issue save/create, and retry/dispatch consumers beyond the STT functions.",
  "Inspected module discovery and registry initialization, Linear client writes, and the local tracker persistence path.",
  "Checked relevant SPEC.md scope and nonfunctional requirements; it contains no STT-specific functional contract.",
  "Inspected installed OpenAI SDK signatures and retry/timeout implementation; checked official transcription and deprecation documentation plus browser API documentation.",
  "Used existing Graphify STT relationships as navigation evidence and checked relevant implementation sources directly."
 ],
 "limitations": [
  "Static plan review only: no edits, tests, compilation, browser execution, restarts, or delegation.",
  "Account model access, the selected polish model, latency, and actual audio requests remain unverified.",
  "Frontend findings identify existing behavior the plan retains or does not explicitly address; the proposed implementation does not yet exist.",
  "No independent new security vulnerability was established from the inspected paths; this was not a repository-wide security audit."
 ]
}
```

### Host dispositions
Round 1 dispositions (host = Claude). Spot-checked STT-01 (SDK 2.36.0 create() has `language`, no `keywords`/`languages`) and STT-04 (duplicate mic-btn-desc/mic-status-desc at index.html:800-803 vs 3689-3692). All 8 accepted:
- STT-01: Step A uses extra_body {keywords, languages:["zh"]}, no singular language, response_format="json", parse .text; Phase 0 + test assert exact shape.
- STT-02: per-recording session object (id, targetEl, owner = modal+issue, base, expected, stream, recorder, AbortController); every callback checks ownership; invalidation on modal close / issue switch / submit / dispatch; stale callbacks are no-ops (Approach 4).
- STT-03: guard before every write (live and final) by value equality to session.expected; external change (typing, attachment append without input event) => stop writing, final result only as hint. Covers all three targets.
- STT-04: unique IDs for new-issue mic/status/hint (4a).
- STT-05: write sets expected before dispatching input so drafts persist; new-issue draft listeners bound on modal creation (4b).
- STT-06: MIME negotiation via isTypeSupported + matching extension; recorder missing/construct/start/async error => browser-only; stream kept on session and tracks stopped on every end path (4c).
- STT-07: polish with_options(timeout=8, max_retries=0); transcription timeout=30, max_retries=0; frontend 45 s abort.
- STT-08: glossary trimmed/deduped/validated against documented limits (Phase 0 records them); invalid entries dropped; bad extras file = warning only.

## Round 2 — Codex (2026-10-14)
- Result: `<session-scratchpad>/claudex-stt/r2/result.json`
- Session resumed 01a13bad… · plan sha256 d7d99cc9… · assurance cross_provider
- Verdict: **REVISE** (3 medium)

```json
{
 "verdict": "REVISE",
 "summary": "The revised plan matches the supplied hash and addresses most first-round findings. The timeout guarantee remains incomplete, and the revised hint and resource-ownership rules contain two concrete edge-case defects.",
 "findings": [
  {
   "id": "STT-07",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-14-stt-two-pass.md:42",
   "evidence": "Disabling retries resolves the retry issue, but with_options(timeout=8) does not establish an eight-second total deadline. The installed HTTPX implementation assigns separate connect/read/write/pool limits (_config.py:127–130), and HTTPcore resets the read timeout for each socket read (_sync/http11.py:196–219). A connection taking six seconds followed by a response taking six seconds can succeed after twelve seconds. A response delivering chunks less than eight seconds apart can take considerably longer. The frontend's 45-second abort neither returns Step A's raw transcript nor cancels the backend call. See [HTTPX timeout documentation](https://www.python-httpx.org/advanced/timeouts/).",
   "fix": "Keep max_retries=0, but add an actual total polish deadline with cancellation or bounded execution that returns the raw transcript when the deadline expires. Define equivalent total bounds for transcription. Verify elapsed-time behavior rather than only asserting the client timeout configuration."
  },
  {
   "id": "STT-09",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-14-stt-two-pass.md:47",
   "evidence": "The hint is offered specifically when targetEl.value differs from session.expected. However, lines 47–48 require every final write to pass that same equality guard and state that the session stops writing after an external change. After the user types or adds an attachment, clicking 'Use refined text' therefore cannot apply the result. Bypassing the guard and writing base + refined text instead would erase those edits or attachment paths; attachment writers append directly to the field at runner/templates/index.html:3803–3842.",
   "fix": "Define a separate explicit hint action. It must preserve current edits and attachments by replacing only an identifiable recording span, or offer copying/inserting the refined text when that span cannot be identified safely. Keep ownership checks and the automatic-write guard, and verify clicking the hint after an edit—not merely its appearance."
  },
  {
   "id": "STT-10",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-14-stt-two-pass.md:46",
   "evidence": "The rule that stale callbacks do nothing conflicts with resource cleanup when microphone acquisition completes after cancellation. The current acquisition is asynchronous (runner/templates/index.html:3276). If the user starts capture, closes the modal while the permission prompt is pending, then grants permission, invalidation had no stream to stop. A stale fulfillment callback that simply returns leaves the newly acquired microphone tracks live. The session's fetch AbortController does not cancel getUserMedia; its documented signature accepts constraints, and the permission promise can remain pending. See [getUserMedia documentation](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia).",
   "fix": "Require late getUserMedia fulfillment to stop every track immediately when its session is cancelled or superseded, before returning. Distinguish forbidden stale UI/state writes from permitted cleanup of resources owned by the stale session. Add the pending-permission close/switch scenario to verification."
  }
 ],
 "coverage": [
  "Read the revised on-disk plan and verified SHA256 d7d99cc9245e55b24b669d04f1810cffb46e2e72d10bbc2c9706720bee05aff3.",
  "Compared all eight prior findings with the revision and host dispositions; accepted the plan-level remedies without re-reporting resolved baseline defects.",
  "Re-inspected microphone acquisition, recognition, recording, cleanup, modal close/switch, and draft input listeners.",
  "Traced shared field writers and consumers: attachments, draft keys, issue save/create, dispatch, and reply retry.",
  "Checked STT backend handling and related Linear/local-tracker description paths.",
  "Inspected installed OpenAI, HTTPX, and HTTPcore timeout code and consulted primary timeout and microphone-acquisition documentation.",
  "Retained the prior round's relevant SPEC.md review; no new spec-fidelity conflict was established."
 ],
 "limitations": [
  "Static plan review only; no files edited, tests run, browser execution, API calls, restarts, or delegation.",
  "The proposed session implementation does not yet exist, so implementation compliance remains unverified.",
  "Account model availability, polish-model selection, latency, and transcription request limits remain Phase 0 evidence to obtain."
 ]
}
```

### Host dispositions
Round 2 dispositions (host = Claude). All 3 accepted:
- STT-07: true total deadlines via module-level ThreadPoolExecutor + future.result(timeout) — 30 s transcription (=> 504), 8 s polish (=> raw transcript, polished:false); late results discarded; tests measure elapsed time with sleeping fakes.
- STT-09: the hint never writes to the field — read-only refined text + Copy (clipboard) + show raw. No span tracking. Verification clicks Copy after an edit.
- STT-10: stale callbacks may not write UI/state but must release owned resources; late getUserMedia resolution for a cancelled/superseded session stops all tracks. Pending-permission close scenario added to manual verification.

## Round 3 — Codex (2026-10-14)
- Result: `<session-scratchpad>/claudex-stt/r3/result.json`
- Session resumed 01a13bad… · plan sha256 db7ce46f… · assurance cross_provider
- Verdict: **REVISE** (1 medium)

```json
{
 "verdict": "REVISE",
 "summary": "The supplied hash matches. The three round-two findings are addressed at plan level, but the new executor design can retain abandoned work and exhaust refinement capacity.",
 "findings": [
  {
   "id": "STT-11",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-14-stt-two-pass.md:42",
   "evidence": "future.result(timeout=...) bounds the handler's wait but does not stop the submitted call. Line 45 incorrectly assumes a per-read timeout bounds the remaining worker lifetime: HTTPcore resets that timeout on each read, so an upstream response delivering chunks within the timeout can keep a worker occupied indefinitely. After max_workers such abandoned calls, subsequent recordings queue and time out without starting. Python 3.12's ThreadPoolExecutor uses an unbounded SimpleQueue (concurrent/futures/thread.py:153,178), and Future.result raises TimeoutError without cancelling the future (_base.py:451–458). Consequently, expired queued recordings can later initiate billable API calls after capacity becomes available. See [Python executor documentation](https://docs.python.org/3.12/library/concurrent.futures.html) and [HTTPX timeout semantics](https://www.python-httpx.org/advanced/timeouts/).",
   "fix": "Bound outstanding submissions and immediately use the appropriate fallback when capacity is exhausted. Cancel queued futures on timeout and check expiration before starting an API call. Ensure running requests have a cancellable total lifetime that releases their transport and worker resources, using cancellable async I/O or a deadline-aware transport. Add verification for pool saturation, capacity recovery, and expired queued work never invoking the API."
  }
 ],
 "coverage": [
  "Read the revised on-disk plan and verified SHA256 db7ce46fcf0945fa9004fd9e05041930cdc867793851818d49d9f9834c7ec3b2.",
  "Accepted the revised response-wait deadline, read-only Copy hint, and late microphone-acquisition cleanup remedies; did not re-report resolved findings.",
  "Inspected the installed Python 3.12 executor/future implementation and HTTPcore read-timeout behavior.",
  "Rechecked STT request handling, module initialization, microphone acquisition, modal cancellation, draft listeners, attachment writers, and reply consumers.",
  "Traced description writes through the Linear module and local tracker, beyond the STT file list.",
  "Rechecked relevant SPEC.md nonfunctional requirements and consulted primary Python and HTTPX documentation."
 ],
 "limitations": [
  "Static plan review only; no edits, tests, browser execution, API calls, restarts, or delegation.",
  "The proposed executor and session implementation does not yet exist.",
  "Account access, polish-model selection, latency, and exact transcription limits remain unverified Phase 0 items."
 ]
}
```

### Host dispositions
Round 3 disposition (host = Claude):
- STT-11 accepted, with a simpler remedy than bounding the pool: the executor is removed entirely. Each stage runs as asyncio.run(asyncio.wait_for(AsyncOpenAI call, timeout)) inside the request thread (Flask-SocketIO threading mode under werkzeug, runner/app.py:149, no eventlet/gevent). wait_for cancels the coroutine, which aborts the httpx request and closes its connection, so there is no worker pool, no queue, and no expired queued work that could start later. Per-request clients with max_retries=0, closed via async with. Tests assert elapsed time, observed CancelledError, and recovery after consecutive timeouts.

## Round 4 — Codex (2026-10-14)
- Result: `<session-scratchpad>/claudex-stt/r4/result.json`
- Session resumed 01a13bad… · plan sha256 8ede4444… · assurance cross_provider
- Verdict: **REVISE** (1 medium)

```json
{
 "verdict": "REVISE",
 "summary": "The hash matches. The async design addresses the abandoned API-worker issue, but per-stage asyncio.run() introduces a DNS-related teardown delay that can violate the promised response deadlines.",
 "findings": [
  {
   "id": "STT-12",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-14-stt-two-pass.md:42",
   "evidence": "The installed HTTPcore transport connects through AnyIO, whose asyncio backend resolves hostnames using loop.getaddrinfo (_asyncio.py:2748). Python 3.12 implements that operation through its default thread executor (asyncio/base_events.py:894–902). Cancelling the coroutine does not stop an already-running socket.getaddrinfo call. asyncio.run then waits for that executor during teardown (asyncio/runners.py:70–73), allowing up to 300 seconds. If DNS resolution blocks for 60 seconds, the eight-second polish timeout fires, but the handler cannot return the raw transcript until teardown finishes. The planned asyncio.sleep fakes do not exercise this path. See [Python runner documentation](https://docs.python.org/3.12/library/asyncio-runner.html).",
   "fix": "Keep the cancellable SDK calls, but prevent unresolved DNS work from being synchronously joined in the HTTP response path. Use cancellable DNS resolution or bounded background resolver/event-loop infrastructure whose shutdown is independent of individual requests. Ensure cancelled operations cannot resume into API calls, and verify handler elapsed time through cancellation and teardown with delayed DNS resolution."
  }
 ],
 "coverage": [
  "Read the revised on-disk plan and verified SHA256 8ede44449a19daa7464ff8a78bd39f6ed1e8d2db5a62e33d2d8165de6972ef96.",
  "Accepted the prior frontend, request-shape, glossary, and API-executor remedies without re-reporting resolved defects.",
  "Inspected AsyncOpenAI context-manager cleanup and HTTPcore cancellation/connection cleanup.",
  "Checked Flask-SocketIO backend selection and threaded Werkzeug serving; the inspected virtual environment contains neither eventlet nor gevent.",
  "Traced HTTPcore connection setup through AnyIO DNS resolution into Python 3.12 executor shutdown.",
  "Rechecked STT capabilities and handlers, modal cancellation, draft listeners, attachment writers, reply consumers, and Linear/local-tracker description writes.",
  "Consulted primary Python documentation for asyncio.run teardown behavior."
 ],
 "limitations": [
  "Static review only; no edits, tests, browser execution, API calls, restarts, or delegation.",
  "The proposed implementation does not yet exist; cancellation and elapsed-time behavior were not empirically tested.",
  "Account access, polish-model selection, latency, and exact transcription limits remain unverified Phase 0 items."
 ]
}
```

### Host dispositions
Round 4 disposition (host = Claude):
- STT-12 accepted. Replace asyncio.run() with new_event_loop() + run_until_complete(wait_for(...)) + finally loop.close(). In Python 3.12, BaseEventLoop.close() calls executor.shutdown(wait=False), so a stuck getaddrinfo thread is not joined in the response path; the cancelled coroutine cannot resume into the API call. The test patches getaddrinfo to block 20 s and asserts handler elapsed <= deadline + 1 s and that the API is never invoked. Under the plan's scope (single-user local dashboard), this is the last transport-level hardening we intend; please flag only remaining material defects.

## Round 5 — Codex (2026-10-14)
- Result: `<session-scratchpad>/claudex-stt/r5/result.json`
- Session resumed 01a13bad… · assurance cross_provider
- Verdict: **APPROVED** — bound to plan sha256 3b53d13606b60d7b9da45a694e9e9e0a685648ea7eb981d647380dd4c65e6bad

```json
{
 "verdict": "APPROVED",
 "summary": "No material unresolved defects found in the revised plan within its single-user, localhost scope. Prior findings are addressed at plan level; implementation and validation remain pending.",
 "findings": [],
 "coverage": [
  "Verified plan SHA256 3b53d13606b60d7b9da45a694e9e9e0a685648ea7eb981d647380dd4c65e6bad and checked the revision against prior findings.",
  "Confirmed from installed Python 3.12 source that loop.close() shuts down its executor without waiting, addressing STT-12's response-path delay.",
  "Inspected AsyncOpenAI client closure and HTTPcore cancellation cleanup.",
  "Reviewed STT handlers, capabilities, dashboard serving mode, modal ownership, recording cleanup, draft persistence, and attachment writers.",
  "Traced reply and description consumers through submission, retry, Linear updates, and local-tracker persistence.",
  "Checked relevant SPEC.md nonfunctional requirements."
 ],
 "limitations": [
  "Static plan approval only; no edits, tests, browser execution, API calls, restarts, or delegation.",
  "The proposed implementation does not yet exist, so deadline, cancellation, and frontend behavior remain unverified.",
  "DNS resolver threads may outlive cancelled responses until the OS lookup finishes, as acknowledged in the revision.",
  "Phase 0 model selection, account access, exact API limits, and request-shape verification remain prerequisites before implementation."
 ]
}
```

## Status
- Approved in 5/5 rounds; 12 findings, all accepted (STT-09/11/12 with simpler remedies than proposed).
- Remaining: Phase 0 user decisions (polish model id, models.list() permission, private glossary). Build NOT authorized.

## Post-approval change — 2026-10-14
- User: recording is owned by issue/task (same across columns); closing modal stops capture but result still belongs to that issue. User chose to continue review with cap raised to 20.
- Host also filled polish-model recommendation (gpt-6-luna, effort none; pending user confirmation).
- Prior approval (sha 3b53d136…) no longer covers the plan.

Post-approval user change (2026-10-14). Please re-review only what changed; the user raised the round cap to 20.
1. Ownership model (user decision). A recording belongs to the issue/task + field, identified by the field's existing draft key (index.html:1528-1535), no matter which column or tab the issue was opened from.
   - Modal close or issue switch: stop capture immediately, keep the session, and still upload the captured audio.
   - A detached result is written into the owner's draft (format-matched; reply drafts are JSON) only if the stored draft still equals `expected`. Otherwise it becomes a pending hint shown on the next open.
   - Reopening from any column reattaches the session.
   - A newer recording for the same owner supersedes the older one, whose result becomes hint-only.
   - Send/dispatch/create cancels the session.
   - One mic capture runs at a time.
   This replaces the earlier "cancel on modal close" rule.
2. Polish model: recommended default gpt-6-luna with reasoning_effort none. User confirmation is still pending (Open Questions).

## User decision + Phase 0 evidence — 2026-10-14
- User confirmed polish model = gpt-6-luna and allowed models.list().
- models.list() with the .env key: gpt-6-luna ✓, gpt-transcribe ✓, gpt-live-transcribe ✓ (also present: gpt-5.6-luna, legacy 4o transcribe ids).
- Plan edit deferred until round 6 returns (avoid changing the hash mid-review).

## Round 6 — Codex (2026-10-14)
- Result: `<session-scratchpad>/claudex-stt/r6/result.json`
- Session resumed 01a13bad… · plan sha256 3662d0cf… · assurance cross_provider · cap now 20
- Verdict: **REVISE** (2 high, 2 medium)

```json
{
 "verdict": "REVISE",
 "summary": "The hash matches. The changed ownership model has concrete draft-format, callback-lifecycle, and persistence defects. No material defect was established in the proposed polish-model default.",
 "findings": [
  {
   "id": "STT-13",
   "severity": "high",
   "path": "docs/exec-plans/active/2026-10-14-stt-two-pass.md:66",
   "evidence": "The plan treats both description drafts as plain text, but agenticos.draft.linear.<issue_id> stores a JSON object containing title, description, state, and preferred_agent (runner/templates/index.html:1693–1702). Comparing its serialized value with session.expected never matches. If the description is extracted for comparison but the prescribed plain-text write follows, the entire draft becomes invalid JSON; _restoreLinearDraft falls back to server values (1706–1721), losing refinement and unsaved edits to other fields.",
   "fix": "Use owner-specific draft adapters: plain text for the new-issue description, JSON.description for the Linear description, and JSON.value for replies. Compare the decoded field value, then update only that field in the latest stored payload while preserving other fields and metadata."
  },
  {
   "id": "STT-14",
   "severity": "high",
   "path": "docs/exec-plans/active/2026-10-14-stt-two-pass.md:60",
   "evidence": "Every callback still requires session === _activeSession, but the revision permits multiple owners to refine concurrently. Close A and start recording B: A's recorder-stop or fetch-completion callback fails that predicate, so its captured audio or detached result is discarded. The supersede rule also requires an older result to write a pending hint, while the stale-callback rule prohibits all state writes.",
   "fix": "Separate the current capture pointer from per-owner refinement ownership. Permit registered detached sessions to upload and complete independently of the visible owner. Define explicit attached, detached, superseded, and cancelled callback policies; superseded results may create hints only while their owner generation remains valid. Cancellation must invalidate all generations for that owner so old results cannot recreate hints after submission."
  },
  {
   "id": "STT-15",
   "severity": "medium",
   "path": "runner/templates/index.html:2260",
   "evidence": "The new cross-column persistence promise conflicts with existing draft deletion. Every board refresh clears reply drafts for issues outside In Review (2260–2261), and modal loading repeats this at 2581 and 2899. A detached result saved to A's reply draft can therefore disappear on the next refresh or reopen. Even in In Review, _restoreReplyDraft deletes the draft when issue_updated_at changes (1666–1672), including after an unrelated issue edit.",
   "fix": "Reconcile these writers with the new ownership contract. Preserve unsent STT drafts and pending results across column changes; clear them on explicit consumption or discard. Capture reply context metadata with the session, and expose results with outdated context as pending hints instead of silently deleting them. Verify reopening after a board refresh and an issue timestamp change."
  },
  {
   "id": "STT-16",
   "severity": "medium",
   "path": "runner/modules/linear/__init__.py:804",
   "evidence": "Draft keys do not always provide stable task identity. Local-first creation returns a local-* ID, then background synchronization replaces it with the Linear UUID and removes the original task/cache entry (787–823). If the user records in that task before synchronization finishes, the retained session, draft, and pending hint remain keyed by the local ID. Reopening the same task after synchronization uses the UUID, so it cannot reattach or discover the result. The update event supplies only count, without an old-to-new mapping.",
   "fix": "Provide a stable task identity or an explicit ID-migration mapping. Migrate the owner's session, draft, pending results, and cancellation generation together when local IDs become Linear IDs. Verify recording during delayed creation synchronization, closing, and reopening after the ID replacement."
  }
 ],
 "coverage": [
  "Verified plan SHA256 3662d0cfdd1d2bce02577257d353908371e68bef5f8a9b6d66efe244abb7a519.",
  "Reviewed only the changed ownership model, its integration effects, and the proposed polish-model default; previously approved transport behavior was not reopened.",
  "Traced draft serialization, restoration, deletion, modal loading, board refreshes, attachments, submission, dispatch, and retry consumers.",
  "Inspected local-first issue creation and background ID replacement beyond the frontend file.",
  "Verified GPT-6 Luna's listed pricing and support for none reasoning against [official OpenAI documentation](https://developers.openai.com/api/docs/models/gpt-6-luna)."
 ],
 "limitations": [
  "Static plan review only; no edits, tests, browser execution, API calls, restarts, or delegation.",
  "The revised session registry and detached-result implementation do not yet exist.",
  "User confirmation, account model access, latency, and exact transcription limits remain pending Phase 0 evidence."
 ]
}
```

### Host dispositions
Round 6 dispositions (host = Claude). All 4 accepted. STT-13 and STT-15 are removed by a simpler design rather than adapters:
- STT-13 + STT-15: detached results are never written into drafts. They go only to a separate `agenticos.stt.pending.<owner>` store, which avoids draft formats and existing draft deletion (board refresh, issue_updated_at). That store is cleared only by user Copy/Dismiss or by cancel, and is shown as the read-only Copy hint whenever that issue/field opens. Attached results still use the guarded field write plus an input event, so existing draft code is unchanged.
- STT-14: `_capture` (one live mic) is separate from per-owner `_sttSessions`, `_ownerGen` and `_ownerCancelGen`. Upload and completion do not depend on `_capture`. Results with gen == current are current; cancelGen < gen < current are hint-only; gen <= cancelGen are discarded.
- STT-16: the backend adds an additive `id_map {local_id: real_id}` to the post-swap `linear_issues_updated` emit. The frontend migrates owner-keyed STT state, pending keys and the issue's draft keys.
Also: user confirmed gpt-6-luna; models.list() verified gpt-6-luna, gpt-transcribe and gpt-live-transcribe; Phase 0 boxes checked.

## Round 7 — Codex (2026-10-14)
- Result: `<session-scratchpad>/claudex-stt/r7/result.json`
- Session resumed 01a13bad… · plan sha256 d86d3436… · assurance cross_provider
- Verdict: **REVISE** (2 medium)

```json
{
 "verdict": "REVISE",
 "summary": "The hash matches. The separate pending store and capture/refinement split address the previous draft and callback findings. Pending-result collisions and recovery of missed ID migrations remain unresolved.",
 "findings": [
  {
   "id": "STT-17",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-14-stt-two-pass.md:75",
   "evidence": "One pending object is stored per owner, but both current detached results and superseded results write that key. Record generation 1, then generation 2, and close the field. If generation 2 finishes first, its result becomes pending; generation 1 finishing later overwrites it with the older transcript. An undismissed result is lost despite the stated user-only clearing policy. Similarly, an asynchronous Copy-and-dismiss action can remove a newer result that replaced the copied one.",
   "fix": "Identify pending records by session ID and generation. Preserve undismissed results separately, display the newest candidate first, and make Copy/Dismiss remove only the selected record. Store explicit text, raw transcript, and polished status. Verify reversed completion order and a new result arriving during Copy-and-dismiss."
  },
  {
   "id": "STT-16",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-14-stt-two-pass.md:84",
   "evidence": "The new id_map event handles connected delivery but provides no recovery when that event is missed. A local task's pending result can already be saved in localStorage when the page reloads during synchronization. The backend removes the local ID and emits the mapping once (runner/modules/linear/__init__.py:805–818). The next page load sees only the real UUID; GET /api/linear/issues returns issue records without aliases (722–755), and the reconnect handler only starts the PTY (runner/templates/index.html:3518–3522). The saved local-ID result remains inaccessible.",
   "fix": "Retain an authoritative local-to-real alias mapping and expose it during initial load or reconnect, not only through the live event. Reconcile persisted pending records and drafts before displaying owners. Canonicalize in-flight session.owner and callback lookups as well as dictionary keys, and make migration idempotent and collision-safe. Verify synchronization during a page reload or socket disconnect."
  }
 ],
 "coverage": [
  "Verified plan SHA256 d86d34361a2c131513be2d171c716332f161a66509e0c87b077e35265f566004.",
  "Checked the pending-store and generation-policy revisions against STT-13 through STT-16; did not reopen previously approved transport behavior.",
  "Traced draft formats and deletion, modal ownership, submission, dispatch, retry, and attachment writers.",
  "Inspected local-first ID replacement, issue-list responses, Socket.IO update handling, reconnect handling, and persisted frontend storage."
 ],
 "limitations": [
  "Static review only; no edits, tests, browser execution, API calls, restarts, or delegation.",
  "The proposed pending store, generation tracking, and migration implementation do not yet exist.",
  "The host's reported account-model listing was not independently repeated; exact transcription limits and sample-request verification remain pending."
 ]
}
```

### Host dispositions
Round 7 dispositions (host = Claude). Both accepted:
- STT-17: the pending store is now a list per owner of {sid, gen, text, raw, polished, created_at}. It is appended, never overwritten, and shown newest gen first. Copy and Dismiss remove only that sid. Manual check covers reversed completion order and Copy racing with a new result.
- STT-16 (recovery): the alias is persisted at swap time in runner-owned outputs/id_aliases.json (locked atomic write) and exposed via GET /api/linear/id-aliases. The frontend loads it on page load and on reconnect, and also applies the live id_map. Migration is idempotent and collision-safe: pending lists merge by sid, and a draft moves only into an empty target, otherwise it is surfaced as a hint. Callbacks canonicalize session.owner via _canonOwner(). Reload during sync is added to manual verification.

## Round 8 — Codex (2026-10-14)
- Result: `<session-scratchpad>/claudex-stt/r8/result.json`
- Session resumed 01a13bad… · plan sha256 2ea3cbed… · assurance cross_provider
- Verdict: **REVISE** (1 medium)

```json
{
 "verdict": "REVISE",
 "summary": "The hash matches. Pending-result preservation and alias recovery address the prior findings, but generation and cancellation state still lack a safe merge rule when both aliases already have sessions.",
 "findings": [
  {
   "id": "STT-18",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-14-stt-two-pass.md:89",
   "evidence": "Generations are numbered independently per owner, yet migration only specifies renaming _sttSessions, _ownerGen, and _ownerCancelGen. Both owners can already exist: the backend exposes the real ID in its cache before performing a comment request with a 15-second timeout and emitting the alias event (runner/modules/linear/__init__.py:810–818, 243). A user can therefore start or cancel a real-ID recording while local-ID refinement remains pending. Renaming source counters over destination counters can erase the destination cancellation watermark and allow an older result to recreate a hint after submission. Taking numeric maxima is also insufficient because the two counters describe different recording sequences. The same ordering problem affects persisted pending rows after reload if fresh counters restart below their stored generations.",
   "fix": "Define alias-independent recording order and cancellation identity, or explicitly rebase every affected session and pending record during migration. Preserve cancellation decisions from both aliases, retain older valid sessions as hint-only, and select only the newest valid session as current. Restore ordering across reloads. Add cases with sessions and cancellation state under both IDs before migration, plus a new recording after reloading existing pending results."
  }
 ],
 "coverage": [
  "Verified plan SHA256 2ea3cbed73855e86069ea94f167aaeeccac3906b491cbe466ad726adae6909e8.",
  "Accepted the pending-list, record-specific dismissal, durable alias lookup, and callback canonicalization remedies.",
  "Traced generation predicates, migration rules, draft ownership, board polling, modal opening, and reconnect handling.",
  "Inspected local-first ID replacement, cache publication, delayed comment submission, notification timing, and the local tracker's atomic-write pattern.",
  "Did not reopen previously approved transport or model-selection decisions."
 ],
 "limitations": [
  "Static review only; no edits, tests, browser execution, API calls, restarts, or delegation.",
  "The proposed alias persistence, endpoint, and migration implementation do not yet exist.",
  "Account access remains host-reported; exact transcription limits and sample-request verification are still pending."
 ]
}
```

### Host dispositions
Round 8 disposition (host = Claude):
- STT-18 accepted via a simpler model. Per-owner generation counters are removed entirely.
  - Ordering: one global, alias-independent seq = max(Date.now()*1000, lastSeq+1), with lastSeq persisted, so it is monotonic across owners and reloads.
  - Cancellation: a persisted timestamp watermark per owner, on the same clock. Alias merge takes max(cancel[local], cancel[real]) and keeps both aliases' sessions under the canonical owner.
  - Classification: discard if seq <= cancel; the newest valid seq is current; other valid sessions are hint-only.
  - Tests: a pure helper extracted from index.html markers, tested with node --test, covering sessions and cancels under both aliases, cross-alias cancel suppression, and a new recording after reload ranking above persisted pending rows.

## Round 9 — Codex (2026-10-14)
- Result: `<session-scratchpad>/claudex-stt/r9/result.json`
- Session resumed 01a13bad… · assurance cross_provider
- Verdict: **APPROVED** — bound to plan sha256 b60ab2cc0f06f271f461f9c3e5af26ef58e209b3f6a78db8c4f778272057e4b9

```json
{
 "verdict": "APPROVED",
 "summary": "The revised plan addresses STT-18 with alias-independent ordering, persisted cancellation watermarks, and explicit merge rules. No additional material unresolved defects found within the reviewed scope.",
 "findings": [],
 "coverage": [
  "Verified plan SHA256 b60ab2cc0f06f271f461f9c3e5af26ef58e209b3f6a78db8c4f778272057e4b9.",
  "Checked global sequence persistence, cancellation-first classification, cross-alias watermark merging, pending-result ordering, and record-specific dismissal.",
  "Reviewed the proposed JavaScript checks for alias collisions, cancellation suppression, and ordering after reload.",
  "Re-inspected local-first ID replacement, cache publication, notification timing, board polling, and reconnect handling.",
  "Traced related draft storage, restoration, deletion, dispatch, reply submission, and local-tracker persistence.",
  "Did not reopen previously resolved transport, model-selection, or draft-format findings."
 ],
 "limitations": [
  "Static plan approval only; no edits, tests, browser execution, API calls, restarts, or delegation.",
  "Session classification, alias migration, pending storage, and cancellation behavior remain unverified until implemented and checked.",
  "Account-model availability is host-reported; exact transcription limits and sample-request verification remain pending Phase 0 work."
 ]
}
```

## Status
- Approved after 9 rounds (5 initial + 4 after user's ownership change); 18 findings, all accepted.
- Remaining Phase 0: keyword/prompt limits from the official guide; one 5 s sample request. Build NOT authorized.

## Build — 2026-10-14
- Authorized by user: "先 STT，再 dispatch Phase 0+1 授权claude 开工"; dispatch later reassigned by user to the other session reviewing it.
- Builder: Claude (host). Pre-build base: 301d437b9e53d673f3ac683f4beb89c7b6d93092 (plan+log committed as baseline). Other sessions' uncommitted dispatch/dsh plan edits left untouched.
- Proof (host): py_compile ok; pytest 65 passed; node --test 5 passed; live /api/stt 4.0 s; headless smoke 17/17. Plan boxes ticked except private glossary (user) and real-mic manual check.

## Inspection 1 — Codex (2026-10-14)
- Result: `<session-scratchpad>/claudex-stt/i1/result.json` · fresh session 01a13be7… · base 301d437 · assurance cross_provider
- Verdict: **REVISE** (1 high, 9 medium, 1 low)

```json
{
 "verdict": "REVISE",
 "summary": "The plan and manifest hashes match. Concrete defects remain in capture lifecycle, issue ownership, cancellation, and ID migration.",
 "findings": [
  {
   "id": "STTI-01",
   "severity": "high",
   "path": "runner/templates/index.html:3222",
   "evidence": "Live recognition checks only capture identity and attached state; _sttWrite also lacks an owner check. openDetailModal changes issue identity and reuses the textareas without synchronously detaching sessions. A delayed openLatestError request can open B while A is recording. Before the next one-second tick, A's first result can write into B's equally empty field and persist it as B's draft.",
   "fix": "Detach sessions synchronously before retargeting the modal. Before every live write, verify the visible field's canonical owner, session identity, cancellation watermark, and expected value."
  },
  {
   "id": "STTI-02",
   "severity": "medium",
   "path": "runner/templates/index.html:3202",
   "evidence": "Recognition starts before asynchronous getUserMedia acquisition and recorder startup. Speech heard during that delay appears live but is absent from the recording. If polish subsequently fails, the incomplete raw transcript replaces the complete browser text. rec.start() also acquires its own microphone input rather than using the promised shared stream. See the [Web Speech methods specification](https://webaudio.github.io/web-speech-api/#speechrecognition-methods).",
   "fix": "Coordinate startup so recording begins before announcing readiness or accepting live speech. Pass the acquired audio track to recognition where supported, with an explicit compatibility fallback."
  },
  {
   "id": "STTI-03",
   "severity": "medium",
   "path": "runner/templates/index.html:3232",
   "evidence": "Every recognition error and end event stops the entire capture. When browser recognition reports network, service-not-allowed, or language-not-supported while MediaRecorder is healthy, the recorder is stopped too. If microphone acquisition is still pending, its eventual stream is discarded and no final-only transcription occurs.",
   "fix": "Handle recognition failure independently from recorder failure. Keep healthy recording active in final-only mode and report that live recognition is unavailable."
  },
  {
   "id": "STTI-04",
   "severity": "medium",
   "path": "runner/templates/index.html:3257",
   "evidence": "With SpeechRecognition unavailable, denying getUserMedia calls _sttEndSession without clearing capturing, _sttCapture, or the recording button. _sttEndSession then suppresses the error display because that same capture is still active. The UI remains on Recording despite permission denial, and the next click merely clears the dead capture.",
   "fix": "Make terminal acquisition failures clear capture ownership, reset controls, and display the error. Ignore stale rejection callbacks except for owned-resource cleanup."
  },
  {
   "id": "STTI-05",
   "severity": "medium",
   "path": "runner/templates/index.html:3283",
   "evidence": "_sttStopCapture clears _sttCapture before calling recognition.stop(). The resulting final recognition event is rejected by the onresult identity check. In browser-only mode, or when refinement fails, the last phrase or corrected final result is lost. stop() explicitly attempts to return a result from already collected audio according to the [Web Speech specification](https://webaudio.github.io/web-speech-api/#speechrecognition-methods).",
   "fix": "Separate microphone capture from recognition draining. Accept final results until recognition ends, provided the session remains current, uncancelled, attached to its owner, and unchanged."
  },
  {
   "id": "STTI-06",
   "severity": "medium",
   "path": "runner/templates/index.html:3485",
   "evidence": "Alias migration moves existing storage and session keys but leaves _detailLinearIssueId and the draft helpers using the local ID. Subsequent live or refined writes dispatch input and recreate the retired local draft key. Reapplying the same alias returns early. Closing and reopening under the UUID therefore restores the earlier migrated draft and loses the later refinement.",
   "fix": "Canonicalize all draft reads, writes, and clears, and retarget the active issue context when its ID changes. Reconciliation must also handle writes occurring after the first migration."
  },
  {
   "id": "STTI-07",
   "severity": "medium",
   "path": "runner/templates/index.html:3512",
   "evidence": "Migration merges pending lists and cancellation watermarks independently, but neither migration nor hint rendering filters pending rows against the merged watermark. A local-ID pending result at seq 10 is restored under the UUID even when that UUID was cancelled at seq 20. Classification protects new completions only, so already stored cancelled results reappear.",
   "fix": "Merge cancellation watermarks first, then remove covered pending rows and terminate covered sessions. Apply the same cancellation check when rendering persisted hints."
  },
  {
   "id": "STTI-08",
   "severity": "medium",
   "path": "runner/templates/index.html:2642",
   "evidence": "Card retry calls retryRun with no modal open, so replyOwner is empty and no STT cancellation occurs. Close A while refining, then retry A from its card: A's result can still produce a hint after dispatch. Dragging a Linear issue to In Progress through _moveLinearIssueToColumn likewise launches it without cancelling its STT state.",
   "fix": "Derive cancellation ownership from the dispatched task rather than the visible modal. Cover card retry, drag-to-In-Progress, and other successful launch paths with one owner-aware cancellation helper."
  },
  {
   "id": "STTI-09",
   "severity": "medium",
   "path": "runner/templates/index.html:3414",
   "evidence": "Reply hints render only when the reply textarea is visible. For virtual issues, openDetailModal hides the entire reply section outside In Review (line 2449). Record a reply on a virtual In Review issue, close it, move it to Todo, and reopen: the pending result remains stored but its Copy hint is inaccessible, contrary to the cross-column recovery requirement.",
   "fix": "Expose pending reply results in an issue-level area that remains visible across columns, independently of whether reply editing is available."
  },
  {
   "id": "STTI-10",
   "severity": "medium",
   "path": "runner/modules/linear/__init__.py:828",
   "evidence": "The local task is removed from persistent tasks.json and replaced in caches before record_id_alias runs. If alias persistence fails, or the process restarts between those operations, the real task survives but its local-to-real mapping is permanently missing. Browser drafts and pending results under the old ID cannot be recovered; the exception path only logs the failure.",
   "fix": "Persist the alias successfully before removing the local identity or publishing the replacement. Preserve a recoverable placeholder and retry when persistence fails."
  },
  {
   "id": "STTI-11",
   "severity": "low",
   "path": "runner/templates/index.html:3519",
   "evidence": "The collision branch says it keeps the newer draft but always keeps the destination draft. Reply drafts already contain saved_at; a newer local draft loses active-draft precedence to an older UUID draft and becomes only a hint. No timestamp comparison occurs.",
   "fix": "Compare draft timestamps and retain the newer draft as specified. Add equivalent ordering metadata for description drafts, preserving the other text as a pending hint."
  }
 ],
 "coverage": [
  "Verified the supplied plan SHA256, every manifest file SHA256, and tracked diff SHA256 against base 301d437b9e53d673f3ac683f4beb89c7b6d93092.",
  "Inspected the STT backend, glossary, frontend changes, both added test files, plan, review log, and maintenance record.",
  "Traced modal loading and reuse, draft serialization/restoration/deletion, attachment writers, creation, retry, dispatch, and board drag callers beyond the STT block.",
  "Traced local-first creation, cache publication, local-tracker persistence, alias storage, endpoint reads, Socket.IO events, and reconnect handling.",
  "Inspected installed OpenAI client cleanup and HTTPcore/AnyIO connection and DNS paths; consulted official transcription documentation and the Web Speech specification.",
  "Read companion-plan documentation as manifest context; this verdict covers the STT implementation."
 ],
 "limitations": [
  "Static review only. No files were edited, tests or compilation run, browser checks performed, provider calls made, services restarted, or work delegated.",
  "Reported test passes, smoke checks, live latency, and account model access were not independently reproduced.",
  "The JavaScript tests cover pure helpers, not integrated capture, migration, cancellation, or modal lifecycle behavior.",
  "Real-microphone behavior and reply/description browser compatibility remain unverified. This review does not approve the separate browser-security or dispatch implementations."
 ]
}
```

### Host dispositions + fixes
Fix round 1 for inspection i1 (host = builder = Claude). All 11 findings were accepted.
- STTI-01: _sttWrite now also checks that the owner is the visible field's canonical owner and that seq > cancel watermark. The detail modal detaches reply/desc sessions synchronously at the start of openDetailModal and whenever the linear loader changes _detailLinearIssueId.
- STTI-02: when refinement is available, recognition starts only after MediaRecorder.start() succeeds ("Starting mic…" until then), so the recording covers all live text. Passing the audio track into SpeechRecognition.start(track) was not adopted, because support varies; recognition still opens its own input.
- STTI-03: recognition end/error no longer stops a healthy recorder; the status becomes "Recording… (live text paused)". In browser-only mode, recognition end still ends the capture.
- STTI-04: _sttAbortCapture clears capture ownership, resets the button, releases the stream, then shows the error. Stale rejections only end or clean up.
- STTI-05: stopping the mic sets draining=true and keeps accepting final results until onend. The upload waits up to 1.5 s for draining.
- STTI-06: _sttApplyAliases re-runs the storage migration on every call and retargets _detailLinearIssueId.
- STTI-07: rendering filters pending rows with seq <= cancel watermark. After migration, sessions covered by the merged watermark are terminated.
- STTI-08: retryRun cancels from the task (reply.run.<run_id> plus the board item's linear issue), not only from the modal. Moving an issue to In Progress cancels its STT state.
- STTI-09: the reply hint moved out of #detail-reply-section and renders whenever the detail modal is open.
- STTI-10: record_id_alias runs before the local id is removed. If persistence fails, the local placeholder is kept, since the swap never happens. Automatic retry was not added.
- STTI-11: on a draft collision, the newer draft is kept by saved_at (Linear description drafts now carry saved_at), and the other draft becomes a hint.
Proof:
- py_compile ok; pytest 65 passed; node --test 5 passed.
- The headless Chrome smoke (fake mic, fake SpeechRecognition, /api/stt held and released) passes 27/27 across two runs, with new checks for STTI-01/02/03/04/05/06/07/09.
- The dashboard was restarted to load the new template.

## Inspection 2 — Codex (2026-10-14)
- Result: `<session-scratchpad>/claudex-stt/i2/result.json` · fresh session 01a13bf7… · base 301d437 · assurance cross_provider
- Verdict: **REVISE** (1 high, 5 medium, 1 low)

```json
{
 "verdict": "REVISE",
 "summary": "The supplied plan, file hashes and tracked diff match. Material defects remain in cancellation, recognition draining and alias migration, including microphone leakage and loss of unsent results.",
 "findings": [
  {
   "id": "STTI-12",
   "severity": "high",
   "path": "runner/templates/index.html:3604",
   "evidence": "Alias reconciliation handles sessions covered by the merged cancellation watermark by setting done=true and deleting them from the registry. It does not stop recognition, the recorder or microphone tracks, abort fetch, or clear _sttCapture. A local-ID capture covered by a real-ID cancellation therefore keeps recording after reconciliation. The subsequent tick cannot clean it up because it has been removed from _sttSessions.",
   "fix": "Use targeted session disposal when applying merged cancellation: stop owned recognition and recorder resources, release tracks, abort fetch and clear capture ownership. Preserve the merged watermark and any newer valid sessions."
  },
  {
   "id": "STTI-13",
   "severity": "medium",
   "path": "runner/templates/index.html:3237",
   "evidence": "Draining recognition callbacks check attached state and capturing/draining, but neither they nor _sttWrite check whether the session has been superseded. Stop recording A and immediately start B in the same field. Before B's first write, A's late final result still passes its expected-value guard and changes the field. B then sees that change as an external edit and stops. Only final upload delivery applies the newest-sequence rule.",
   "fix": "Require current-session classification before every live or draining field write. Older sessions may collect their final recognition text for refinement, but must not change the field after a newer recording starts."
  },
  {
   "id": "STTI-14",
   "severity": "medium",
   "path": "runner/templates/index.html:2948",
   "evidence": "Saving a state change to In Progress dispatches the issue through the backend at runner/modules/linear/__init__.py:942–960, but saveLinearIssue cancels only description STT. A reply still refining becomes detached on close and can create a hint after dispatch. The card's setIssueAgent path at index.html:2110–2118 also dispatches without cancelling either field.",
   "fix": "Apply owner-aware cancellation to every reachable dispatch path, including Save to Linear with an In Progress state and setIssueAgent. Cancel both reply and description sessions for the dispatched issue."
  },
  {
   "id": "STTI-15",
   "severity": "medium",
   "path": "runner/templates/index.html:1489",
   "evidence": "Draft helpers still use raw issue IDs. _sttApplyAliases retargets only the currently open issue, while openDetailModal later assigns raw IDs from a card or run record at lines 2442 and 2543. Reopening a stale local-ID card after aliases have loaded, or a historical run retaining that ID, creates a canonical UUID STT session whose input events save into the retired local draft key. Opening the UUID then misses those later live/refined writes. Migration is not rerun by ordinary board refreshes.",
   "fix": "Canonicalize draft keys at every read, write and clear, and canonicalize issue identity when loading cards and run records. Do not rely solely on retargeting the modal during an alias notification."
  },
  {
   "id": "STTI-16",
   "severity": "medium",
   "path": "runner/templates/index.html:2657",
   "evidence": "retryRun captures submitted text before awaiting the request, but cancellation creates its watermark only after the response. The mic remains usable during that wait. If the user starts another recording for the same owner, the successful response cancels that newer recording even though its audio/text was never submitted. In final-only mode this can discard the entire new utterance. The same response-time cancellation pattern occurs during issue creation.",
   "fix": "Capture a submission cutoff when sending the request. On success, cancel only sessions and pending rows covered by that cutoff, preserving recordings started afterward."
  },
  {
   "id": "STTI-17",
   "severity": "medium",
   "path": "runner/templates/index.html:3599",
   "evidence": "_storageSet silently swallows setItem failures at lines 1473–1476, but alias migration unconditionally removes the source key after attempting the destination write. If storage is near quota, temporarily retaining both copies can make the write fail; migration then deletes the only persisted draft, pending list or cancellation watermark.",
   "fix": "Make migration writes report success and remove source keys only after destination persistence succeeds. Retain recoverable source data and retry reconciliation when a write fails."
  },
  {
   "id": "STTI-18",
   "severity": "low",
   "path": "runner/templates/index.html:3464",
   "evidence": "The Copy handler captures owner before awaiting clipboard.writeText. If alias migration moves that pending list while clipboard permission or writing is pending, the completion calls _sttRemovePending with the old local owner. That helper does not canonicalize it, so the copied row remains under the UUID and reappears despite Copy-and-dismiss succeeding.",
   "fix": "Resolve the canonical owner when pending removal executes, then remove only the selected sid from the current canonical list."
  }
 ],
 "coverage": [
  "Verified the plan SHA256, all thirteen manifest file hashes and tracked diff SHA256 against base 301d437b9e53d673f3ac683f4beb89c7b6d93092.",
  "Read the supplied diff and inspected every manifest file; companion dispatch and dsh documents were treated as context, not separately approved.",
  "Reviewed STT transcription, polish, deadline handling, glossary validation, capabilities, recorder fallbacks, recognition callbacks and resource cleanup.",
  "Traced modal reuse, draft reads/writes/deletions, attachment writers, creation, retry, card dispatch, state-save dispatch and pending-hint actions.",
  "Traced alias persistence, endpoint reads, local-first replacement, polling/cache publication and LocalTracker shared-state writers beyond the changed file list.",
  "Inspected both added test files and relevant installed OpenAI/HTTPcore/AnyIO cleanup code; checked hint rendering uses textContent."
 ],
 "limitations": [
  "Static review only: no edits, tests, compilation, browser checks, provider calls, service restarts or delegation.",
  "Host-reported test passes, smoke checks and live latency were not independently reproduced.",
  "Real microphone behavior, browser compatibility and runtime cancellation deadlines remain unverified.",
  "Spec fidelity was assessed against the supplied STT plan; this was not a repository-wide specification or security audit."
 ]
}
```

### Host dispositions + fixes
Fix round 2 for inspection i2 (host = builder = Claude). All 7 accepted.
- STTI-12: added `_sttDispose(s)`. It stops recognition and the recorder, releases tracks, aborts the fetch, clears `_sttCapture`, resets the UI and unregisters the session. Alias reconciliation and cancel both use it for sessions covered by the merged watermark.
- STTI-13: `_sttWrite` refuses when `s.seq < _sttLatestSeq[owner]`. A superseded session still collects final text for its own refinement but never writes into the field.
- STTI-14: `saveLinearIssue` with an In Progress state cancels both fields of the issue. `setIssueAgent` (card dispatch) cancels both fields before PATCHing.
- STTI-15: draft keys are canonical at the source. `_sttIssueId()` is used in `_currentLinearDraftKey`, `_currentReplyDraftKey`, `_clearReplyDraftForIssue` and `_clearLinearDraft`. `_detailLinearIssueId` is canonicalized wherever a card or run record sets it. `_sttAliases` is a `var`, so these earlier helpers can read it safely.
- STTI-16: `_sttCancel(owner, cutoff)` now cancels only sessions and pending rows with `seq <= cutoff`. Retry and new-issue creation take the cutoff when they send the request, so recordings started while it is in flight survive.
- STTI-17: alias migration removes a source key only after the destination key reads back.
- STTI-18: `_sttAddPending` and `_sttRemovePending` canonicalize the owner when they run.
Proof:
- py/JS syntax ok; pytest 65 passed; node --test 5 passed.
- Headless Chrome smoke: 32/32 on two consecutive runs. New checks cover STTI-12, 13, 15, 16 and 18.
- Dashboard restarted.

## Inspection 3 — Codex (2026-10-14)
- Result: `<session-scratchpad>/claudex-stt/i3/result.json` · fresh session 01a13c00… · base 301d437 · assurance cross_provider
- Verdict: **REVISE** (3 medium)

```json
{
 "verdict": "REVISE",
 "summary": "The plan, manifest file hashes and tracked diff match. Three concrete defects remain in alias migration and preservation of recordings made during submission.",
 "findings": [
  {
   "id": "STTI-19",
   "severity": "medium",
   "path": "runner/templates/index.html:3614",
   "evidence": "Migration checks whether the destination exists, rather than whether the intended write succeeded. If the UUID pending list already exists and quota prevents saving the merged list, _storageSet silently fails but line 3614 deletes the local list anyway. Its undismissed results are lost. The same problem affects newer drafts and cancellation watermarks; collision hints can also fail to persist before their source draft is removed.",
   "fix": "Report persistence success and verify the intended destination value, including any collision hint, before removing source keys. Preserve source data for reconciliation when any required write fails."
  },
  {
   "id": "STTI-20",
   "severity": "medium",
   "path": "runner/templates/index.html:2172",
   "evidence": "triggerLinearIssueWithAgent still creates its cancellation watermark after awaiting the PATCH response. Click an issue's Start button, reopen that issue and begin a new recording while the response is delayed: the successful response cancels this newer, unsubmitted recording and deletes its pending results. The submission-cutoff fix applied to retry and creation does not cover this reachable card dispatch path.",
   "fix": "Capture a cutoff before sending the PATCH and pass it to _sttCancelIssue on success. Preserve drafts and results created after that cutoff."
  },
  {
   "id": "STTI-21",
   "severity": "medium",
   "path": "runner/templates/index.html:4057",
   "evidence": "Creation preserves newer sessions through sttCutoff, but unconditionally clears their drafts. In browser-only mode, submit a task, then start another recording while the POST response is delayed. Its live text is saved by _saveNewIssueDraft. When success arrives, _clearNewIssueDraft deletes that unsent text and closeNewIssueModal detaches the recording. Browser-only sessions produce no pending refinement, so reopening the modal restores an empty description.",
   "fix": "Clear only the submitted draft version. Preserve post-submission field changes and completed voice writes; if closing the modal, keep their draft or explicitly retain their text in a recoverable pending record."
  }
 ],
 "coverage": [
  "Verified the supplied plan SHA256, all thirteen manifest file hashes and tracked diff SHA256 against base 301d437b9e53d673f3ac683f4beb89c7b6d93092.",
  "Reviewed the supplied changes, STT plan and inspection dispositions, backend, glossary, frontend controls and both added test files.",
  "Traced capture startup, recognition draining, recorder fallbacks, resource disposal, guarded writes, pending hints, ordering and cancellation.",
  "Traced draft persistence, modal reuse, attachment writers, creation, retry and card/state dispatch callers.",
  "Inspected alias persistence and serving, local-first replacement, Linear polling/cache publication and LocalTracker shared-state writers beyond the changed files.",
  "Companion dispatch and dsh documents were treated as manifest context, without granting standalone approval."
 ],
 "limitations": [
  "Static review only: no edits, tests, compilation, browser checks, provider calls, service restarts or delegation.",
  "Reported test passes, smoke checks and live latency were not independently reproduced.",
  "Real microphone behavior, browser compatibility and runtime cancellation deadlines remain unverified.",
  "Spec fidelity was assessed against the supplied STT plan. Vendor model/deprecation claims and separate browser-security work were not independently validated."
 ]
}
```

### Host dispositions + fixes
Fix round 3 for inspection i3 (host = builder = Claude). All 3 accepted.
- STTI-19: alias migration writes and then reads back each intended value (put = set + verify). That covers merged pending, cancel max, the moved draft and any collision hint. The source key is removed only when every required write has persisted; otherwise the source is kept and the next load or reconnect retries.
- STTI-20: triggerLinearIssueWithAgent takes the cutoff before the PATCH and passes it to _sttCancelIssue.
- STTI-21: on successful creation, any description text changed after Submit (typed or dictated) is written back as the next new-issue draft instead of being cleared.
Proof:
- JS syntax ok; pytest 65 passed; node 5 passed.
- Headless smoke 34/34 on two runs. New checks: a simulated quota failure keeps the source and a later retry migrates it; text added during a held POST survives as the draft. The POST is intercepted, so no real issue was created.
- Dashboard restarted.

## Inspection 4 — Codex (2026-10-14)
- Result: `<session-scratchpad>/claudex-stt/i4/result.json` · fresh session 01a13c06… · base 301d437 · assurance cross_provider
- Verdict: **REVISE** (3 medium)

```json
{
 "verdict": "REVISE",
 "summary": "The supplied plan, file hashes and tracked diff match. Three material persistence defects remain.",
 "findings": [
  {
   "id": "STTI-22",
   "severity": "medium",
   "path": "runner/templates/index.html:2172",
   "evidence": "triggerLinearIssueWithAgent preserves recordings started after sttCutoff, but still unconditionally clears the description draft. Start an issue, reopen it and complete a browser-only recording while the PATCH response is delayed. Its input events save the new draft; the successful response then deletes it. Closing and reopening loses that unsubmitted utterance because closeDetailModal does not save the field and browser-only sessions produce no pending refinement.",
   "fix": "Clear only the submitted draft version. Preserve description drafts changed after dispatch began, including completed voice writes, using a captured draft version or value comparison."
  },
  {
   "id": "STTI-23",
   "severity": "medium",
   "path": "runner/templates/index.html:3567",
   "evidence": "Alias reconciliation installs the canonical mapping before storage migration succeeds. If quota prevents writing the canonical cancellation key, the source watermark is retained but ignored: _sttCancelSeq reads only the canonical key. For example, a local-owner cancellation at seq 20 must suppress a real-owner pending result or refining session at seq 10. After the cancellation-key migration fails, canonical lookups return zero, so the cancelled result can reappear or write into the field. Retaining the source key alone does not preserve cancellation enforcement.",
   "fix": "Enforce the merged cancellation maximum in memory independently of persistence, and consult retained source watermarks during incomplete migration. Dispose covered sessions and filter hints using that effective maximum."
  },
  {
   "id": "STTI-24",
   "severity": "medium",
   "path": "runner/templates/index.html:3408",
   "evidence": "_sttAddPending uses _storageSet, which silently swallows quota and storage errors. _sttDeliver then marks the session done and unregisters it regardless of persistence success. When a detached result cannot be appended, its refined and raw text have no retained copy and disappear permanently. For an attached edited field, the UI even reports that refined text was kept below although no hint exists.",
   "fix": "Make pending insertion report verified persistence success. On failure, retain the result in a recoverable in-memory pending store, expose Copy and an explicit persistence warning, and support retrying storage."
  }
 ],
 "coverage": [
  "Verified the plan SHA256, all thirteen manifest file hashes and tracked diff SHA256 against base 301d437b9e53d673f3ac683f4beb89c7b6d93092.",
  "Inspected the manifest changes, STT plan and inspection dispositions, backend, glossary, frontend controls and both added test files.",
  "Traced capture lifecycle, recognition draining, recorder fallbacks, resource disposal, guarded writes, pending hints, ordering and cancellation.",
  "Traced draft persistence, modal reuse, attachment writers, creation, retry and card/state dispatch callers.",
  "Inspected alias persistence and serving, local-first replacement, board projection and LocalTracker shared-state writers beyond the changed files.",
  "Treated companion dispatch and dsh documents as manifest context without granting standalone approval."
 ],
 "limitations": [
  "Static review only: no edits, tests, compilation, browser checks, provider calls, service restarts or delegation.",
  "Host-reported test passes, smoke checks and live latency were not independently reproduced.",
  "Real microphone behavior, browser compatibility and runtime cancellation deadlines remain unverified.",
  "Spec fidelity was assessed against the supplied STT plan; vendor claims and separate browser-security work were not independently validated."
 ]
}
```

### Host dispositions
- STTI-22 accepted + fixed: triggerLinearIssueWithAgent clears the description draft only if it still equals the version captured before the PATCH. Regression: smoke 34/34, pytest 65.
- STTI-23, STTI-24 (localStorage quota-failure paths): pending a user decision (fix vs. accept as a documented limitation).

## Open Issues (accepted by user 2026-10-14)
- STTI-23: if localStorage quota blocks writing a canonical cancel watermark during alias migration, the retained source watermark is not consulted, so a cancelled result could reappear. Trigger needs ~5 MB localStorage full; STT data is a few KB.
- STTI-24: if localStorage quota blocks appending a pending result, the detached result is lost (no in-memory fallback). Same trigger condition.

## Inspection 5 — Codex FAILED (provider_unavailable) 2026-10-14
- Result: `<session-scratchpad>/claudex-stt/i5/result.json`; Codex usage limit ("try again at 7:30 PM"); fallback_eligible=true.
- Automatic fallback: fresh same-provider (Claude CLI) inspection → assurance=degraded_same_provider.
- Fallback Claude inspection (`<session-scratchpad>/claudex-stt/i5f/result.json`) also FAILED: provider_unavailable (Claude usage limit).
- STATUS: build complete, fixes for i1–i4 applied, final inspection NOT done. Unreviewed edits: STTI-22 fix (triggerLinearIssueWithAgent sent-draft check) and fix round 3 (STTI-19/20/21) are covered only by host tests (pytest 65, node 5, smoke 34/34). Next: rerun Codex inspect after quota reset (7:30 PM), base 301d437, feedback inspect-notes-5.md.
- Fallback retry from i5 refused by runner: another session's dsh plan files changed after i5, so i5's snapshot no longer matches. Re-running inspection in an isolated worktree (base 301d437 + only the STT changes).

## Inspection 6 — isolated worktree (base 301d437 + STT changes only), 2026-10-14
- Codex primary (`<session-scratchpad>/claudex-stt/i6/result.json`): failed in 4 s, provider_unavailable (usage limit).
- Claude fallback (`<session-scratchpad>/claudex-stt/i6f/result.json`), fresh session 6108d5c5…, observed model claude-opus-5-5[1m], **assurance=degraded_same_provider**
- Verdict: **REVISE** (1 medium, 4 low)

```json
{
 "verdict": "REVISE",
 "summary": "The STTI-22 fix does preserve dictation made while the PATCH is in flight. However, it compares the raw stored draft JSON, and that JSON is rewritten by things other than user edits: the saved_at field changes on every save, and setDetailIssueAgent saves the draft programmatically whenever the issue loads. As a result, simply opening the issue during the PATCH keeps a stale draft that still holds the pre-dispatch state, and that state comes back whenever the issue is reopened. Fix rounds 1–4 also introduced several low-severity edge cases: new-issue submit can re-save already-submitted text as the next draft, retry cancels unsent description results, an alias arriving mid-load can leave the Linear editor stuck on \"Loading…\", and a reattached session can write into the blank field during a load. I found no backend defects. This review is degraded same-provider (Claude reviewing Claude's build), not an independent cross-provider review. I did not re-raise STTI-23/24, which the user accepted.",
 "findings": [
  {
   "id": "STTI-25",
   "severity": "medium",
   "path": "runner/templates/index.html:2163-2176",
   "evidence": "triggerLinearIssueWithAgent keeps the draft unless `_storageGet(draftKey) === sentDraft`, comparing the raw JSON. `_saveLinearDraft` (1658-1670) stamps `saved_at: Date.now()` and is called without any user edit by setDetailIssueAgent (2817), which runs on every issue load via `_restoreLinearDraft` (1688) and at 2886. Scenario: click ▶ Start on a Todo card, then click the card while the dispatch PATCH (which triggers backend dispatch) is still running. The loader rewrites the draft with the fetched `state` (often still 'Todo') and a new saved_at. When the PATCH succeeds the strings differ, so the draft is kept. Linear drafts are never cleared anywhere else; the only other `_clearLinearDraft` call is at 2957. Every later reopen therefore runs `stateEl.value = draft.state` (2889) and shows Todo for an In Progress issue, and the next 'Save to Linear' sends `state_name: 'Todo'`, pulling the running issue back to Todo. Before this fix the draft was always cleared on success.",
   "fix": "Decide whether to keep the draft by its content, not the raw JSON: keep it only when the stored description or title differs from what was sent in `body`. When keeping it, rewrite its `state` to the dispatched state ('In Progress') and `preferred_agent` to `agentVal`, or store only the description text, so a stale state can never be restored."
  },
  {
   "id": "STTI-26",
   "severity": "low",
   "path": "runner/templates/index.html:4053-4068",
   "evidence": "submitNewIssue neither stops nor fences the live capture when Submit is clicked. The cancel watermark is only set after the POST returns, so a recognition result that arrives during the POST still passes `_sttWrite`. A typical case is Chrome finalizing an interim phrase, which adds punctuation via `_normalizeSpeechSegment`. The field then differs from the sent `desc`, so `descNow.trim() !== desc` is true and the entire already-submitted description plus that final phrase is saved as the next new-issue draft. The next 'New task' opens prefilled with text that was already submitted, which invites a duplicate task. The same pre-cutoff-writer pattern also defeats the STTI-22 equality check.",
   "fix": "Fence the pre-cutoff session at submit time: stop its capture and refuse its further field writes, for example with an in-memory submitting watermark that `_sttWrite` checks. Then, after success, keep only text the user added after `desc`, such as the suffix when `descNow` starts with the sent text, instead of the whole field."
  },
  {
   "id": "STTI-27",
   "severity": "low",
   "path": "runner/templates/index.html:2666-2668",
   "evidence": "retryRun sends only `reply`, yet `_sttCancelIssue(boardItem?.linear_issue_id, sttCutoff)` also cancels `agenticos.draft.linear.<id>`. Virtual In Review issues show the description mic (2462). A description dictation that is still refining, or whose refined result sits as a pending hint (for example because the field was edited), is disposed or deleted by `_sttCancel` when the user retries with a reply. That description text was never submitted, while the plan only cancels on send/dispatch/create of the owning text.",
   "fix": "On retry, cancel only the reply owners (`replyOwner`, `reply.run.<run_id>` and `reply.linear.<id>`), not the description owner."
  },
  {
   "id": "STTI-28",
   "severity": "low",
   "path": "runner/templates/index.html:2838-2859",
   "evidence": "`_sttApplyAliases` (STTI-06) retargets `_detailLinearIssueId` from the local id to the real id. If the `linear_issues_updated` id_map arrives while `_loadLinearIssueIntoModal` is still fetching, the loader captured `linear_issue_id` as the local id, so its staleness check `_detailLinearIssueId !== linear_issue_id` (2859) fails and it returns. Title and description stay blank, the inputs stay disabled (2847-2853) and the status stays 'Loading…'. If instead the fetch of the swapped-away local id 404s, the fields are re-enabled but left blank. This is reachable by opening a just-created local task, a step the plan's own manual check performs.",
   "fix": "In the loader, compare canonical ids, for example `_sttIssueId(_detailLinearIssueId) !== _sttIssueId(linear_issue_id)`. Alternatively, have `_sttApplyAliases` re-invoke the loader for the open issue after retargeting."
  },
  {
   "id": "STTI-29",
   "severity": "low",
   "path": "runner/templates/index.html:3554-3563",
   "evidence": "`_sttTick` treats the desc kind as visible as soon as `linear-edit-section` is shown, but `_loadLinearIssueIntoModal` blanks and disables the fields while fetching (2846-2853). Take a detached session that never wrote into the field (final-only mode with no SpeechRecognition, or recognition failing from the start) on an issue with an empty description, so `expected === ''`. If it reattaches and completes inside that loading window, `_sttWrite` writes into the disabled field. Its input event then saves a draft with title '', state '' and `preferred_agent: 'claude'`, because `_detailPreferredAgent` was reset at 2850. `_restoreLinearDraft` then merges that draft over the issue, so the issue's real preferred agent is silently replaced by 'claude'.",
   "fix": "Do not reattach or write while the target field is disabled or the loader is pending: treat the kind as not visible until loading finishes."
  }
 ],
 "coverage": [
  "Read the plan, the full tracked diff, and the current files: runner/modules/stt/__init__.py, runner/modules/stt/glossary.txt, tests/modules/test_stt.py and tests/stt_seq.test.mjs.",
  "Read runner/templates/index.html around the draft helpers (1460-1720), drag dispatch, setIssueAgent, triggerLinearIssueWithAgent (STTI-22), openDetailModal, closeDetailModal, dispatchFromDetail, retryRun, approveRun, the linear loader, saveLinearIssue, the STT block (capture, recorder, refine, deliver, end, detach, dispose, cancel), the new-issue modal, attachment writers and submitNewIssue.",
  "Traced every caller of triggerLinearIssueWithAgent, setIssueAgent, retryRun, _moveLinearIssueToColumn, openDetailModal and _loadLinearIssueIntoModal, plus all writers and clearers of agenticos.draft.linear.* keys.",
  "Checked the backend deadline handling (Python 3.12, so `except TimeoutError` catches asyncio timeouts), glossary validation, response shape, and the record_id_alias ordering and emit placement in runner/modules/linear/__init__.py.",
  "Verified that the STTI-22 fix covers its intended scenario: dictation during the PATCH changes the stored draft, so the draft is preserved."
 ],
 "limitations": [
  "This is a degraded same-provider fallback: the builder and the reviewer are both Claude, so it is not independent cross-provider assurance.",
  "Static review only. I did not edit files, run tests, compile, run browser checks, call providers or restart services. I did not verify the hashes of the plan, manifest or diff. The host-reported results (pytest 65, node 5, smoke 34/34) were not reproduced.",
  "Real-microphone behaviour, browser compatibility and runtime timing windows were not exercised, so the severity of STTI-26, STTI-28 and STTI-29 depends on timing.",
  "Pre-existing issue outside this diff: triggerLinearIssueWithAgent (2158-2162) builds its PATCH body from the shared detail-modal title and description fields even when started from a card, and closeDetailModal does not clear them. That can send another issue's title and description. I did not assess it further, but it should be checked separately.",
  "STTI-23 and STTI-24 (localStorage quota exhaustion) were not re-raised, per the user's acceptance. The companion dispatch and dsh plan documents were out of scope.",
  "DEGRADED_SAME_PROVIDER: preferred reviewer codex was unavailable; claude reviewed in a fresh fallback session without cross-provider independence."
 ]
}
```

### Host dispositions
- STTI-25 (regression from the STTI-22 fix) was accepted and fixed. The draft is now compared by description/title content against the PATCH body, not by raw JSON. A kept draft is re-stamped with state 'In Progress' and the dispatched agent, so a stale Todo state can't come back.
- STTI-27 was accepted and fixed: retry now cancels only the reply owners and leaves description dictation alone.
- STTI-26, STTI-28 and STTI-29 are low-severity, timing-dependent edge cases. Per the user's decision to commit now, they are open and unfixed (see Open Issues).
- Regression after fixes: pytest 65 passed, node 5 passed, headless smoke 34/34, dashboard restarted.
- The STTI-25/27 fixes were made after inspection 6 and have not been independently inspected.

## Open Issues (added 2026-10-14)
- STTI-26: a recognition result that lands during the new-issue POST can re-save the already-submitted description as the next draft.
- STTI-28: an alias arriving while the Linear loader is fetching can leave the editor showing 'Loading…'. Reopening the issue recovers.
- STTI-29: a detached session reattaching while the Linear loader has the field disabled can write into it.
- Pre-existing, outside this diff: triggerLinearIssueWithAgent builds its PATCH from the shared modal title/description fields even when started from a card.

## Commit — 2026-10-14
- The user chose to commit the current version ("目前这个版本我觉得还可以，那就直接 commit"). The final cross-provider inspection was not completed because Codex quota was exhausted. Recommended: one Codex inspection after the quota resets.
