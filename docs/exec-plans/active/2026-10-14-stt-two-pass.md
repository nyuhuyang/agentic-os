---
status: in-progress
created: 2026-10-14
---

# Task: Two-pass voice input — Browser STT live, OpenAI transcribe + LLM polish as final

## Goal
One mic button. While speaking, Browser STT (Web Speech API) shows text live, as today. When the user stops, the recorded audio is re-transcribed by OpenAI and then polished by a text model. The result replaces the live text as the final version. This replaces today's either/or source selector, because both sources make frequent mistakes on their own: proper nouns, homophones, and a mis-heard product name ("open 4o" for "OpenAI 4o").

This also moves off OpenAI models that are being retired (source: developers.openai.com/api/docs/deprecations, checked 2026-10-14):

| In use | Where | Shutdown | Replacement |
|---|---|---|---|
| `gpt-4o-mini-transcribe` (default), `gpt-4o-transcribe`, `whisper-1` | `runner/modules/stt/__init__.py:27-32` | 2027-02-26 | `gpt-transcribe` (file upload) |
| `client.beta.realtime` + `gpt-realtime-mini` | `runner/modules/stt/__init__.py:111-184, 280-390` | beta API removed 2026-05-12; model 2027-01-20 | — (path is unused, delete) |

## Current State (recon 2026-10-14)
- Frontend uses only `POST /api/stt`, a file upload (`runner/templates/index.html:3100-3350`). The Socket.IO realtime path (`stt_openai_start/audio/stop`) is never called by the UI. It is also already broken, because the beta API it relies on has been removed.
- The source is chosen in a `.stt-source` dropdown that offers either `browser` or `openai:gpt-4o-mini-transcribe` (`index.html:1286-1330`, `3160-3180`), with two mic buttons, `mic-btn` and `mic-btn-desc`, plus a third copy in the new-issue modal at `index.html:3689`. Browser mode = `_startMic` (`index.html:3357`); OpenAI mode = `MediaRecorder` → `/api/stt`.
- No STT tests exist.

## Approach
1. **Frontend: one flow, no selector.** Pressing the mic starts both of these together on one `getUserMedia` stream:
   - Web Speech API recognition, writing interim and final text into the target field exactly as today;
   - a `MediaRecorder` that records the audio.
   
   On stop: the field keeps the browser text, the status line shows "refining…", and the frontend uploads the audio together with `browser_text` to `/api/stt`.
2. **Backend: `POST /api/stt` does two steps.**
   - Step A, transcribe: call `client.audio.transcriptions.create(model="gpt-transcribe", file=..., prompt=<context>, response_format="json", extra_body={"keywords": [...], "languages": ["zh"]})`.
     - The installed SDK 2.36.0 has no `keywords`/`languages` arguments, so they go in `extra_body`. Singular `language` is **not** sent.
     - `keywords` = the validated glossary (item 3). `<context>` = `browser_text`, trimmed to the documented prompt limit.
     - Parse `.text` from the JSON response.
     - The client is built with `with_options(timeout=30, max_retries=0)`.
   - Step B, polish: one call to a text model, configured by `OPENAI_STT_POLISH_MODEL`. Its instructions:
     - fix recognition errors, using the glossary and the browser text as a second witness;
     - remove fillers ("那个", "就是", "嗯");
     - fix punctuation;
     - **keep meaning, language mix and every instruction intact**;
     - do not summarize, translate or add content;
     - return only the text.
   - **Real total deadlines with real cancellation.** HTTPX timeouts apply per phase or read, so they are not enough. A thread pool cannot cancel running work either. The handler runs each stage with `asyncio.wait_for(<AsyncOpenAI call>, timeout)` on its own `loop = asyncio.new_event_loop()`: `loop.run_until_complete(...)`, then `finally: loop.close()`. Transcription gets 30 s, polish gets 8 s.
     - This deliberately avoids `asyncio.run()`, whose teardown joins the default executor and can block on an uncancellable DNS `getaddrinfo` thread.
     - `BaseEventLoop.close()` calls `executor.shutdown(wait=False)` instead. A stuck resolver thread then finishes on its own without holding the HTTP response. The cancelled coroutine never resumes, so it cannot go on to make the API call.
     - This works because the dashboard runs Flask-SocketIO in threading mode under werkzeug (`runner/app.py:149`, no eventlet or gevent), so each request thread can own a short-lived event loop.
     - On timeout, `wait_for` cancels the coroutine. That aborts the in-flight HTTPX request, closes its connection, and leaves no worker or queue behind.
     - Clients are created per request with `max_retries=0` and closed via `async with`.
     - Transcription past its deadline ⇒ 504 with error; the frontend keeps the browser text.
     - Polish past its deadline or erroring ⇒ return the step A transcript with `polished: false`.
     - The frontend 45 s abort only stops waiting; the browser text stays. The backend is already bounded at 38 s total (30 + 8), so it finishes or cancels by itself.
   - Response: `{"text": polished, "raw": transcript, "polished": bool}`.
3. **Glossary** sits in a small tracked file, `runner/modules/stt/glossary.txt`, with generic product terms only: OpenAI, Claude, Codex, Linear, AgenticOS, STT, worktree, Shiny, R, Python, and similar. An optional `STT_GLOSSARY_EXTRA` env path points to a private, untracked list of project names, because the repo is public. Before any request, entries are trimmed, deduplicated and validated against the documented keyword constraints (allowed characters, max length, max count). Phase 0 records the exact limits from the official guide. Invalid entries are dropped with a log warning. A missing, unreadable or invalid extras file is a warning only: the generic glossary is kept and refinement still runs.
4. **Per-recording session object; it replaces today's mutable globals** (`_micTranscriptBase`, `_micLastRenderedValue`, `_micTargetId`, …). Each press creates `session = {id, targetEl, owner, base, expected, stream, recorder, abort: AbortController}`. `owner` is the **draft key of the target field**, which already identifies the issue/task and the field (`index.html:1528-1535`):
   - `agenticos.draft.reply.linear.<issue id>` for the reply,
   - `agenticos.draft.linear.<issue id>` for the Linear description,
   - `agenticos.draft.new_issue.description` for a new task that has no id yet,
   - the existing `agenticos.draft.reply.run.<run_id>` fallback for runs without a Linear issue.
   
   A recording belongs to that issue and field, whichever column or tab the issue was opened from (New task, In Review, …). Opening the same issue anywhere sees the same session. Rules (user decision 2026-10-14):
   - **Two separate pointers.**
     - `_capture` is the single live mic capture.
     - `_sttSessions[owner]` holds per-owner refinement state: `{seq, state: attached|detached}` plus the element when attached.
     - **Ordering is one global, alias-independent sequence.** Each recording gets `seq = Math.max(Date.now() * 1000, _lastSeq + 1)`, which is monotonic across owners. It also keeps rising across reloads, because `_lastSeq` is persisted in `agenticos.stt.lastSeq`.
     - Cancellation is a timestamp watermark, `agenticos.stt.cancel.<owner>` = the `seq` value at cancel time, persisted in localStorage.
   - **Callback policy:**
     - Recognition results and live writes require that the session is `_capture` and attached.
     - Recorder stop, upload and fetch completion **do not** depend on `_capture`. A detached session uploads and completes on its own.
     - A result is **cancelled** and discarded when `session.seq <= cancel[canonOwner]`. A late result can therefore never recreate a hint after the owner was sent or dispatched.
     - Among the remaining valid sessions of the canonical owner, the one with the highest `seq` is **current**. Every other valid session is **superseded** and may only create a pending hint.
   - **Guard before every write, live and final:** if `targetEl.value !== session.expected`, something external changed the field, such as typing or an attachment path appended without an input event. The session then stops writing into the field. Recognition stops; the recording still uploads. The final result goes only to a "Use refined text" hint, so nothing is overwritten.
   - Otherwise a write sets `value = base + text` and then `session.expected = value`, and only after that dispatches `input`. That ordering lets draft persistence save it without the guard mistaking it for a user edit. Live, refined and raw ("show raw") writes all use this path.
   - **Modal close / issue switch = stop recording, keep the session.**
     - Recognition and the recorder stop and tracks are released, so the mic is off immediately. The audio captured so far is still uploaded.
     - The session detaches from the DOM and stays in `_sttSessions[owner]` until its result lands.
   - **A detached result goes only to the pending store, never into drafts.** It is appended to `agenticos.stt.pending.<owner>`, which is a **list** of `{sid, seq, text, raw, polished: bool, created_at}`. A newer completion never overwrites an older undismissed result, even when completions arrive in reverse order. The hint shows the newest `seq` first, and Copy-and-dismiss or Dismiss removes only the record with that `sid`, so a result that arrives during a Copy survives.
     - This keeps it separate from draft formats: the Linear description draft is a JSON object (`index.html:1693-1702`), the reply draft is `{value, …}`. It is also safe from the existing draft deletions, which happen on board refresh outside In Review (`index.html:2260-2261`, `2581`, `2899`) and when `issue_updated_at` changes (`1666-1672`).
     - The pending store is cleared only by the user, through Copy-and-dismiss or Dismiss, or by cancel.
     - Whenever that issue/field opens, in any column, the pending result shows as the read-only Copy hint.
     - The live text was already in the field before close. It went through the normal input event, so the existing draft code saved it with its own format and lifecycle, which this plan does not change.
     - Results for an **attached** session still go through the guarded field write (see "Guard before every write" below).
   - **Reattach:** when a modal opens and its field's draft key equals a live session's owner (refining, or still recording in the background), the session reattaches to the new element. It resumes the normal live-field guard and status display. An issue whose draft key differs never receives the session's text.
   - **Supersede:** a new recording for the same owner has a higher `seq`. The older session's late result only becomes a pending hint, never a write.
   - **Cancel:** sending the reply, or dispatching or creating the issue, sets `cancel[owner] = nextSeq()`, because the text is already submitted. Cancel also aborts the fetch, stops recognition, the recorder and the tracks, and clears the pending hint.
   - **Local-id migration.** A local-first issue is created with a `local-*` id and later swapped for the Linear UUID (`runner/modules/linear/__init__.py:787-823`).
     - The backend adds an additive `id_map: {local_id: real_id}` field to the `linear_issues_updated` event it already emits after the swap.
     - The same mapping is also **persisted**: at swap time the backend appends `{local_id, real_id}` to runner-owned `outputs/id_aliases.json`, using the same lock + atomic-replace helper pattern. A new `GET /api/linear/id-aliases` returns it.
     - The frontend loads aliases on page load and on Socket.IO reconnect, before rendering any hint, and also applies `id_map` from the live event.
     - Migration is idempotent and collision-safe:
       - Both aliases' sessions are kept under the canonical owner. Because `seq` is global, "newest valid is current" stays correct after the merge.
       - The cancel watermark becomes `max(cancel[local], cancel[real])`. Both values are on the same global clock, so a cancellation under either alias still applies.
       - Pending lists are merged by `sid`.
       - A draft key moves only when the target key is empty; otherwise the newer draft is kept and the other is surfaced as a pending hint.
     - In-flight callbacks resolve `session.owner` through `_canonOwner()` (the alias map) before every lookup. A recording made before sync, or a reload during sync, is therefore still found afterwards.
   - Only one mic capture runs at a time. Starting a mic on another owner stops the current capture (as on close), and its refinement continues.
   - **The hint never writes to the field.** It shows the refined text read-only, with a **Copy** button (`navigator.clipboard.writeText`) and a "show raw" toggle. The user pastes it wherever they like, so edits and attachment paths are never at risk. No span tracking is attempted.
   - The hint is removed with its session.
   - **Stale callbacks may only clean up.** A stale callback must not write UI or state, but it **must** release resources it owns. In particular, a `getUserMedia` promise that resolves after its session was cancelled or superseded stops every track of that stream before returning. This covers closing the modal or switching issue while the permission prompt is still pending.
4a. **Unique controls.** The Linear-description and new-issue modals currently share the IDs `mic-btn-desc` and `mic-status-desc` (`index.html:800-803` vs `3689-3692`). The new-issue copies get unique IDs (`mic-btn-new` / `mic-status-new` / hint). Each session resolves its button, status and hint from its own IDs.
4b. **Draft persistence fix.** `_bindDraftPersistence()` runs at `index.html:3468`, before the new-issue markup exists (`3693`), so its new-issue listeners are never attached. Bind them when that modal is created. The reply and Linear-description listeners stay as they are.
4c. **Recorder robustness.**
   - Pick a MIME type with `MediaRecorder.isTypeSupported`, trying `audio/webm;codecs=opus`, then `audio/mp4`, then `audio/ogg`. Upload with the matching file extension.
   - If `MediaRecorder` is missing, or construction or `start()` fails, or it raises an async `error`: recognition continues as browser-only, with the status "refine unavailable".
   - The acquired stream is always kept on the session, and its tracks are stopped on every end path.
   - If speech recognition is unsupported and recording also fails, release the stream and show an error.
   - The frontend gives up waiting after 45 s via `AbortController`, keeping the live text.
5. **Fallbacks, all non-blocking.** In every case below, the browser text stays and the status shows a short reason:
   - no `OPENAI_API_KEY`, which means browser-only mode, the same as today's default;
   - step A fails;
   - step B fails or times out after 8 s, in which case the transcript from step A is used, marked unpolished;
   - Web Speech API is unsupported, in which case the field shows "listening…" and the final text arrives only after stop.
6. **Delete dead code:** the realtime worker, Socket.IO handlers, `_RealtimeStreamState`, `_REALTIME_TRANSPORT_MODEL`, the `.stt-source` selectors and their localStorage key, `_OPENAI_STT_MODELS` and its whisper/4o entries. `check_capabilities` keeps reporting the `openai` backend so the UI knows whether refinement is available.

## Decisions (user, 2026-10-14)
- Cleanup level = transcription **plus** LLM polish (not transcription-only).
- Build STT now, before multi-project dispatch; plan first, no code until approved.

## Open Questions (resolve before build)
- [x] Polish model = `gpt-6-luna` with `reasoning_effort` none, overridable via `OPENAI_STT_POLISH_MODEL`. User confirmed 2026-10-14. Price is $0.10 / $0.50 per 1M tokens (developers.openai.com/api/docs/models).
- [x] Should the polish step also run for Browser-only mode without audio, for example when OpenAI transcription fails? Default: no. Polish only runs on the OpenAI transcript. — kept default: no (2026-10-14)
- [ ] Glossary contents beyond the generic list (private extras go in `STT_GLOSSARY_EXTRA`).

## Non-goals
- Live streaming through `gpt-live-transcribe` / the GA Realtime API. Browser STT already covers the live preview.
- Local whisper backend; speaker diarization; transcript history.

## Risks
- The polish step can still change meaning. The prompt forbids it and `raw` is returned; the hint shows "polished · show raw" so the original transcript is one click away.
- Browser and recorder share one mic stream. Chrome supports this. Safari's Web Speech support is partial, and the fallback is final-only.
- Cost: one transcription plus one text call per utterance. That is small for personal use. The status line shows the model ids.

## Progress Checklist
**Phase 0 — confirm**
- [x] User picked `gpt-6-luna`. `models.list()` with the `.env` key lists `gpt-6-luna`, `gpt-transcribe` and `gpt-live-transcribe` (2026-10-14).
- [x] Documented limits (official speech-to-text guide, 2026-10-14). `keywords` must not contain `<`, `>`, CR or LF, or the whole request is rejected; no max length or count is documented, so we self-cap at 64 chars and 100 entries. `prompt` has no stated limit for `gpt-transcribe`, so we self-cap `browser_text` at 1000 chars. `languages` takes ISO 639-1 codes (`zh`) and replaces `language`. Audio formats are mp3/mp4/mpeg/mpga/m4a/wav/webm, up to 25 MB.
- [x] Live sample (macOS `say` → m4a, 2026-10-14). The request shape `extra_body={keywords, languages:["zh"]}` + `prompt` + `response_format="json"` returned `.text` with OpenAI/Codex/Linear spelled correctly, plus `languages:[{code:"zh"}]`, in 2.7 s. The Luna polish (Responses API, `reasoning={"effort":"none"}`) took 2.6 s.

**Phase 1 — backend**
- [x] `/api/stt`: step A (`gpt-transcribe`, keywords, browser_text prompt, JSON parse) + step B (polish, 8 s timeout) + fallbacks; env `OPENAI_STT_MODEL` (default `gpt-transcribe`), `OPENAI_STT_POLISH_MODEL`, `STT_GLOSSARY_EXTRA` — done 2026-10-14; live `/api/stt` through the launchd runner: 4.0 s, polished, OpenAI/Codex/Linear correct
- [x] `runner/modules/stt/glossary.txt` (generic terms only) — done
- [x] Delete realtime worker + Socket.IO handlers + beta/retired model constants — done; module 390 → ~190 lines
- [x] `tests/modules/test_stt.py` with a fake OpenAI client: — 11 tests pass. Deviation: the DNS case is simulated by blocking executor work (`run_in_executor(time.sleep)`), which is the same uncancellable-executor-thread mechanism, rather than by patching `getaddrinfo`
  - Happy path returns polished + raw.
  - The outbound call has `extra_body` keywords + `languages`, no `language`, a trimmed `prompt`, and `response_format="json"`.
  - A fake async polish call that awaits `asyncio.sleep(20)` ⇒ the response arrives in <9 s with the raw transcript and `polished: false`, and the fake records `CancelledError`, so the call really was cancelled.
  - A fake transcription call that sleeps 60 s ⇒ 504 in <31 s and was cancelled.
  - Two consecutive timed-out requests leave no pending tasks and a third request succeeds normally.
  - Delayed DNS: patch `loop.getaddrinfo` to block in the executor for 20 s ⇒ the handler still returns within its deadline (+1 s), and the fake API call is never invoked.
  - Both clients have `max_retries=0`.
  - Transcription failure ⇒ 502 + error.
  - Glossary: an invalid entry is dropped; a missing, unreadable or invalid extras file ⇒ warning only, generic glossary kept.

**Phase 2 — frontend**
- [x] One flow in `toggleMicFor` with the session object (Approach 4): Web Speech + MediaRecorder on one stream; stop ⇒ upload with `browser_text`; "refining…" status — done; headless Chrome smoke (fake mic, `/api/stt` intercepted) passes
- [x] Recorder MIME negotiation + failure fallbacks + stream cleanup (4c) — done. Deviation: `audio/ogg` dropped because `/v1/audio/transcriptions` does not accept ogg; the candidates are webm(opus), webm and mp4→m4a
- [x] Unique IDs for the new-issue mic/status/hint (4a); bind new-issue draft listeners on modal creation (4b) — done; draft binding moved to `DOMContentLoaded`; smoke confirms the new-issue draft saves on input
- [x] Session registry keyed by draft key with `_capture` / `_sttSessions`, a global persisted `seq`, and persisted cancel watermarks: — done. Deviation: the helper is `_sttClassify(seq, cancelSeq, latestSeq)`, not `_classifyResult(...)`; `tests/stt_seq.test.mjs` has 5 passing node tests. Smoke covers close→reopen hint, cancel drop, and reverse order
  - Close or switch stops the capture and detaches the session.
  - A detached result goes only to `agenticos.stt.pending.<owner>`.
  - Reopening from any column reattaches.
  - Superseded results become hint-only; results from before a cancel are discarded.
  - The seq/cancel logic is a pure JS helper, `_classifyResult(session, sessions, cancel)`, kept inline in `index.html` between `// stt-pure:start` and `// stt-pure:end` markers (there is no build step). It is exercised by `tests/stt_seq.test.mjs`, which extracts that block and runs under `node --test`, covering:
    - sessions and cancels under both aliases, then a merge;
    - a cancel under one alias suppresses an older result under the other;
    - a new recording after a reload ranks above the persisted pending rows.
  - Cancel on send, dispatch or create.
  - A late `getUserMedia` for a cancelled or detached session stops its tracks.
- [x] Backend: — done; emit moved before the slow Linear comment call
  - add `id_map` to the post-swap `linear_issues_updated` emit;
  - persist the alias in `outputs/id_aliases.json` (locked atomic write);
  - add `GET /api/linear/id-aliases`.
- [x] Frontend: — done; `_sttCanon()` plays the role of `_canonOwner()`; smoke covers pending/draft/cancel migration
  - load aliases on page load and on reconnect, plus the live `id_map`;
  - idempotent, collision-safe migration;
  - `_canonOwner()` in callbacks;
  - test (Python, Flask test client): the alias is persisted and returned by the endpoint.
- [x] Guard-before-every-write + expected-then-dispatch-input persistence + "Use refined text" hint + "show raw" toggle — done; the hint offers Copy/Dismiss/show raw and never writes the field; smoke: an edit during refine is preserved and a hint is shown
- [x] Remove `.stt-source` selectors (3 places) and their JS/localStorage; browser-only when capabilities lack `openai` — done; button title reflects whether openai is available

**Verification**
- [x] `.venv/bin/python3 -m py_compile runner/*.py runner/modules/stt/__init__.py` and `.venv/bin/python -m pytest tests/` pass — compile ok; 65 passed (2026-10-14)
- [ ] Manual in Chrome on the launchd dashboard: speak a sentence containing "OpenAI", "Codex", "Linear". Live text appears and is then replaced by the refined text. Typing during "refining…" shows the hint instead of overwriting. Clicking **Copy** in the hint puts the refined text on the clipboard and leaves the field untouched. If you start recording, close the modal while the permission prompt is pending, then grant permission, the mic indicator goes off immediately. The same holds for typing **during** live recognition, and for adding an attachment mid-recording, in all three targets: reply, Linear description and new-issue description. If you start recording in issue A, close it and open issue B, nothing from A is inserted into B. Close A mid-recording ⇒ the mic goes off at once. Reopening A from another column (for example In Review instead of Todo), and after a board refresh, shows A's pending Copy hint.
Close A, record in B, then reopen A: A's result is present, so the B capture did not discard it.
Send A's reply while A is still refining: no hint appears later.
Record in a just-created local task, then wait for Linear sync and reopen: the result is found. The same holds if you reload the page during sync.
Record twice in A without dismissing and let them finish in reverse order: both results are in the hint, newest first. Clicking Copy on one leaves the other. Reopening A while it is still refining shows "refining…" and then the result in place. Spoken text in the new-issue modal survives a close and reopen. The status and hint always show in the modal of the owning issue. With the OpenAI key temporarily unset in a dev run, the browser-only text stays.
- [x] `grep -n "beta.realtime\|gpt-4o-.*transcribe\|whisper-1" runner/` returns nothing — returns nothing
- [x] Update `docs/context-maintenance.md`; `graphify update .` — done 2026-10-14

## Test
`.venv/bin/python -m pytest tests/modules/test_stt.py tests/ -q`; restart dashboard (`launchctl kickstart -k gui/$(id -u)/com.agenticos.runner`); the manual Chrome check above.
