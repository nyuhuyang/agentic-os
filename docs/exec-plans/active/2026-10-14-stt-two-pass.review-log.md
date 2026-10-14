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
