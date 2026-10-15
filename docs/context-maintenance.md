# Context Maintenance

## Current WIP (WIP = 1)
<!-- One active task at a time. What is it? -->
- STT two-pass: done, plan archived in completed/ (2026-10-14); optional follow-ups = one cross-provider Codex inspection, low-severity Open Issues in its review log
- Multi-Project Dispatch — `docs/exec-plans/active/2026-10-13-multi-project-dispatch.md` (plan approved by Codex review 2026-10-13; build not started)

## Last Validated State
<!-- What passed most recently? test suite / lint / manual check + date -->
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
- Start Multi-Project Dispatch Phase 0 (first unchecked item in its plan) once the build is authorized
