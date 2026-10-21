# Context Maintenance

## Current WIP (WIP = 1)
<!-- One active task at a time. What is it? -->
- STT two-pass: done, plan archived in completed/ (2026-10-14); optional follow-ups = one cross-provider Codex inspection, low-severity Open Issues in its review log
- Multi-Project Dispatch — `docs/exec-plans/active/2026-10-13-multi-project-dispatch.md`: Phases 0–3 built on `feat/multi-project-dispatch` (2026-10-14). Open: the cross-provider Codex inspection of the build (Codex quota), spike (d2) for Codex, dogfood tickets, one user decision (`/run` free prompts), one project's committed .gitignore

## Last Validated State
<!-- What passed most recently? test suite / lint / manual check + date -->
- AGE-120 Claude Code Projects research: docs-only note `docs/references/claude-code-projects.md` (overlap table + pilot checklist); no code, pilot waits for beta access — 2026-10-21
- AGE-118 live dictation (ChatGPT-style): mic streams over WebRTC to an OpenAI Realtime transcription session (`gpt-live-transcribe`, secret from `POST /api/stt/live-token`), deltas fill the field while speaking; on stop the turn is committed and `POST /api/stt text=` only polishes. Connect failure falls back to the old two-pass path. 14 STT pytest + node seq tests pass; OpenAI accepted the session; isolated runner on 8599, Chrome with synthetic `say` audio: text appeared 1 s into speech, final ✓ Refined, stop-while-connecting leaves no live track. Warm connect ≈1.1 s, speech before "● Listening…" is lost. Real-mic check pending — 2026-10-21
- AGE-116 Codex cost: `turn.completed` input_tokens now excludes `cached_input_tokens` (matches Claude's uncached semantic), so `token_cost_usd` no longer prices re-sent context. The AGE-110 3-paper deep ingest read $22.08 = 7.36M tokens × $3 default with 96.8% cache hits; same usage now $0.86. Codex runs on the ChatGPT plan, so neither is billed cash. 128 pytest pass; isolated runner on 8599 with fake codex recorded input 233405 / cost 0.858564 — 2026-10-21
- AGE-117 card detail: Log tab removed (Terminal replay shows the same, copyable), with its `/api/runs/<id>/progress` and `/api/linear/issues/<id>/progress` routes and their Codex-session helpers; Error tab adds verify fail, merge_error and stderr tail. 782 pytest pass, `node --check` passes; isolated runner on 8599: tabs Output/Error/Terminal, stderr tail in run detail, progress route 404 — 2026-10-21
- Multi-project dispatch Phases 0–3: 265 pytest pass. Live: browser request checks (token/Host/Origin), project panel, terminal tabs (3 projects, reload, close), and sandboxed verify baselines (one R project 0 fail / 1031 pass; KB from the launchd context) — 2026-10-14
- STT two-pass (Browser STT live → `gpt-transcribe` + `gpt-6-luna` polish) built per `docs/exec-plans/completed/2026-10-14-stt-two-pass.md`: 65 pytest + 5 node tests pass; live `/api/stt` via launchd 4.0 s; headless Chrome smoke (fake mic) 17/17. A real-mic manual check is still pending — 2026-10-14
- Claude quota cards now display `remaining_pct` on initial render and live refresh; focused Jinja and Node checks cover live/missing Claude values and unaffected Codex/Gemini display, and `.venv/bin/python3 -m py_compile runner/*.py` passes — 2026-09-24
- `com.agenticos.runner` is registered and running under launchd on 127.0.0.1:8510. Live `/api/windows/all` and `/` returned HTTP 200; all three served Claude card labels matched the API's `remaining_pct` values (`100% remaining`, `100% remaining`, `no data`) — 2026-09-24
- Codex third usage card now reads `rateLimitResetCredits.availableCount`; current value `3` — 2026-07-02
- `.venv/bin/python3 -m py_compile runner/*.py` passes; `/` and `/api/windows/all` return HTTP 200 with Usage Resets data after launchd redeploy — 2026-07-02
- Codex now maps the server-reported 10080-minute window into both dashboard cards; Reset Activity exposes available credits, latest grant, and next expiry. `py_compile`, `/`, `/api/windows/all`, and `/api/usage` pass — 2026-07-14
- Dashboard is managed by `com.agenticos.runner` with launchd `RunAtLoad` + `KeepAlive`

## Open Decisions
<!-- Decisions made and their rationale — so a new session knows the "why" -->
- P15, P20, P23 parked in `docs/exec-plans/deferred/` (2026-10-13); P20 depended on `../symphony-ts`, which no longer exists
- Server bound to 127.0.0.1 only — multi-host/remote scope is explicitly out of scope
- Usage reset weekly limit is fixed at 3; unavailable Codex app-server data renders as no data
- One DeepSeek agent: `dsh` (official DeepSeek Harness, `workspace-write`); direct-API `deepseek` and Rust `deepseek-tui` retired, ids aliased on read; DeepSeek usage row is balance-delta spend, tokens n/a (2026-10-14, plan `2026-10-14-dsh-backend-swap`)

## Next Action
<!-- Concrete first step for the next session -->
- Multi-Project Dispatch: run the cross-provider Codex inspection of the build (base a8ab382) and spike (d2) for Codex, then dogfood one labelled ticket per project
