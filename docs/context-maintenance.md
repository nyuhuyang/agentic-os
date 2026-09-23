# Context Maintenance

## Current WIP (WIP = 1)
<!-- One active task at a time. What is it? -->
- P20 — Dashboard Fixes & Token Panel Redesign. Codex Usage Resets card is complete; other unchecked P20 items remain.

## Last Validated State
<!-- What passed most recently? test suite / lint / manual check + date -->
- Codex third usage card now reads `rateLimitResetCredits.availableCount`; current value `3` — 2026-07-02
- `.venv/bin/python3 -m py_compile runner/*.py` passes; `/` and `/api/windows/all` return HTTP 200 with Usage Resets data after launchd redeploy — 2026-07-02
- Codex now maps the server-reported 10080-minute window into both dashboard cards; Reset Activity exposes available credits, latest grant, and next expiry. `py_compile`, `/`, `/api/windows/all`, and `/api/usage` pass — 2026-07-14
- Dashboard is managed by `com.agenticos.runner` with launchd `RunAtLoad` + `KeepAlive`

## Open Decisions
<!-- Decisions made and their rationale — so a new session knows the "why" -->
- P23 (Shared agent context injection) deferred pending research — not started
- Server bound to 127.0.0.1 only — multi-host/remote scope is explicitly out of scope
- Usage reset weekly limit is fixed at 3; unavailable Codex app-server data renders as no data

## Next Action
<!-- Concrete first step for the next session -->
- Continue P20 from unchecked items, starting with 1-H validation and 1-J `pnpm build`
- Reconcile generated roadmap links with actual active plans before regenerating docs
