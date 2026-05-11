# Exec Plan: P1–P5 Implementation

**Created:** 2026-05-07  
**Status:** In Progress

## Decisions (from grill session)

- Cancel: unify all dispatch to Popen, store proc handle, DELETE endpoint kills proc
- Retry (P1): immediate re-dispatch; no queued state yet
- Retry backoff (P2): queued + due_at on top of P1 retry
- stalled = new status (distinct from failed), maps to Human Review column
- WORKFLOW.md at agentic-os root for backend + Linear config
- Linear issues = primary board entity; run_log.jsonl = audit log with linear_issue_id
- Board filters: only show records with linear_issue_id (legacy hidden)
- Dispatch: semi-auto (In Progress issues auto-dispatch; Todo waits for human drag)
- Skill selection: single Claude routing call per issue
- Human Review → Linear: no push (issue stays In Progress in Linear)

## Task Checklist

### P1 — Core Board Parity

#### Backend (app.py)
- [ ] Add `_running_procs: dict[str, Popen]` global
- [ ] Add `last_progress_at: float` to `_running_jobs` entries
- [ ] Convert `/run` subprocess.run → Popen + proc.wait() (both skill and AI paths)
- [ ] Store proc in `_running_procs` on start, pop on finish
- [ ] `/stream`: store proc in `_running_procs`, emit `run_progress` SocketIO events
- [ ] `DELETE /api/runs/<run_id>`: terminate proc, write cancelled to log
- [ ] `POST /api/runs/<run_id>/retry`: re-dispatch immediately (call _dispatch helper)
- [ ] Add `stalled`, `queued` to PATCH allowlist
- [ ] Emit `run_progress` with latest output snippet during SSE streaming

#### Frontend (index.html)
- [ ] Cancel button on In Progress cards → `DELETE /api/runs/<id>`
- [ ] Live elapsed timer on running cards (JS tick from started_at)
- [ ] Last-event status line on running cards (updated by `run_progress` SocketIO event)
- [ ] `stalled` badge in _stateBadgeHtml
- [ ] Human Review states: add `stalled`

### P2 — Attempt Tracking and Retry Backoff

#### Backend
- [ ] `_write_run_log`: add `attempt`, `parent_run_id` params (default 0, None)
- [ ] Retry endpoint: copy attempt+1, set parent_run_id
- [ ] Add `queued` status + `due_at` field for retry backoff
- [ ] Stall detection: background thread, check `last_progress_at`, STALL_TIMEOUT_S=300
- [ ] Stall thread: emit `run_state_change` with `stalled` and write to log

#### Frontend
- [ ] Attempt badge `↺N` on cards with attempt > 0
- [ ] Queued countdown `due in Xm` for queued state

### P3 — Token and Runtime Visibility

#### Backend
- [ ] Read/write WORKFLOW.md `agent.backend` field
- [ ] `GET /api/config` + `PATCH /api/config` endpoints
- [ ] Parse `input_tokens`/`output_tokens` from claude -p JSON output; store in run_log
- [ ] Aggregate runtime endpoint: sum duration_s from run_log + elapsed from _running_jobs

#### Frontend
- [ ] Agent toggle: on switch, PATCH /api/config with new backend
- [ ] On page load: GET /api/config to restore backend selection
- [ ] Per-run token count on card footer
- [ ] Aggregate runtime stat chip in header
- [ ] Turn count badge on In Progress cards (count SSE output chunks via run_progress)

### P4 — Linear Sync

#### Backend (new file: runner/linear_client.py)
- [ ] Parse WORKFLOW.md tracker config (YAML front matter)
- [ ] `LinearClient`: GraphQL client using requests
  - `fetch_issues(active_states)` → list of normalized issues
  - `update_issue_state(issue_id, state_name)` → mutation
  - `resolve_state_id(state_name)` → Linear state UUID
- [ ] Linear polling thread: every `polling.interval_ms` ms, fetch active issues
- [ ] On new issue found in In Progress: trigger skill routing + dispatch
- [ ] `GET /api/linear/issues` endpoint
- [ ] `GET /api/linear/config` endpoint (return tracker config)
- [ ] Patch `PATCH /api/runs/<id>/status`: if run has linear_issue_id + new_status maps to Linear state → push to Linear
- [ ] Skill routing: single claude -p call with issue + registry → returns skill name
- [ ] Store `linear_issue_id`, `selected_skill` on run records

#### Frontend (index.html)
- [ ] Board `refreshJobBoard()`: fetch `/api/linear/issues` alongside runs; merge into board
- [ ] Linear issue cards: show issue identifier (e.g. ENG-123), title, Linear badge
- [ ] Board filter: hide run records without `linear_issue_id` (legacy)
- [ ] Linear project selector dropdown in header
- [ ] Drag Linear issue card to column → push state to Linear + write run record

### P5 — Board UX Polish

#### Frontend
- [ ] Attempt badge `↺N` on cards (if attempt > 0)
- [ ] Stale sent cleanup: auto-archive backlog entries older than 24h (server-side background job)
- [ ] Column card limit: make `15` configurable via `GET /api/config` `board.col_limit`

## Files to Modify

- `runner/app.py` — backend
- `runner/templates/index.html` — frontend
- `runner/linear_client.py` — new file
- `TODO.md` — update as items complete
- `WORKFLOW.md` — create at agentic-os root

## Order of Implementation

1. P1 backend (app.py): Popen unification + cancel + retry + run_progress
2. P1 frontend (index.html): cancel button + elapsed timer + status line
3. P2 backend: attempt tracking + stall detection + queued state
4. P2 frontend: badges + countdown
5. P3 backend: config endpoint + token parsing + runtime aggregate
6. P3 frontend: persist agent + token on cards + runtime chip
7. P4 backend: linear_client.py + polling + dispatch
8. P4 frontend: Linear board cards + project selector
9. P5: UX polish
