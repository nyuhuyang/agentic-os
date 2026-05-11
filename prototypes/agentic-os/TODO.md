# AgenticOS Job Board — TODO

Gap analysis vs Symphony orchestrator. See SPEC.md for acceptance criteria.

---

## P0 — Column Restructure (blocked by all board work below)

- [x] **Expand to 5 visible + hidden columns**

  Current (4 visible):
  ```
  Backlog (sent) | In Progress (running) | Human Review (failed,error,timeout) | Done (success)
  ```

  Target:
  ```
  Backlog (sent) | Todo | In Progress (running) | Human Review (failed,error,timeout) | [hidden group]
  ```

  Hidden columns (collapsed by default, togglable):
  - Rework
  - Merging
  - Done
  - Canceled
  - Duplicated

  Status → column mapping:
  | Status value | Column |
  |---|---|
  | `sent` | Backlog |
  | `todo` | Todo |
  | `running` | In Progress |
  | `failed`, `error`, `timeout` | Human Review |
  | `rework` | Hidden: Rework |
  | `merging` | Hidden: Merging |
  | `success` | Hidden: Done |
  | `cancelled` | Hidden: Canceled |
  | `duplicate` | Hidden: Duplicated |

  New status values (`todo`, `rework`, `merging`, `cancelled`, `duplicate`) must be added to the closed set in `SPEC.md` FR-14 and `app.py` PATCH allowed-statuses.

  Hidden group: single collapsed bar showing count per hidden column. Click to expand inline.

---

## P1 — Core Board Parity with Symphony

- [x] **Live elapsed timer on In Progress cards** — client-side tick from `started_at`, 1s interval.
- [x] **Last-event / live status line on running cards** — `run_progress` SocketIO event emitted during SSE streaming with latest output snippet + turn count.
- [x] **Cancel button on running cards** — `DELETE /api/runs/<run_id>` kills Popen proc, writes `cancelled`. All dispatch paths unified to Popen.
- [x] **Retry** — `POST /api/runs/<id>/retry` immediately re-dispatches in background thread with `attempt+1`, `parent_run_id`.

---

## P2 — Attempt Tracking and Retry Backoff

- [x] **Attempt counter** — `run_log.jsonl` gains `attempt`, `parent_run_id` fields.
- [ ] **Retry backoff** — `queued` status + `due_at` + countdown on cards. Not yet implemented (P1 retry is immediate only).
- [x] **Stall detection** — background thread checks `last_progress_at` every 30s; auto-transitions to `stalled` (new distinct status in Human Review) after 300s.

---

## P3 — Token and Runtime Visibility

- [x] **Backend selector persists** — `setAgent()` PATCHes `/api/config`; page load reads it from WORKFLOW.md via `GET /api/config`. Backend toggle preserved across reloads.
- [x] **Per-run token count on cards** — all blocking Claude dispatch paths (`/run`, retry, Linear auto-dispatch) use `--output-format json`; parse `usage.input_tokens`/`output_tokens`; stored on run record; shown on card footer.
- [x] **Aggregate runtime chip** — header chip pulls from `/api/runtime` (sum of `duration_s` + elapsed running jobs). Refreshes every 30s.
- [x] **Turn count on running cards** — SSE chunks counted, emitted as `turn` in `run_progress` event; shown as `T:N` on In Progress cards.

---

## P4 — Linear Sync

- [x] **Poll Linear API** — `_linear_polling_loop` thread reads WORKFLOW.md config, fetches issues via GraphQL, caches in `_linear_issues_cache`.
- [x] **Mirror issues onto board** — Linear issues appear as cards in board columns; board filters only `linear_issue_id`-linked run records.
- [x] **Bidirectional state push** — column drop triggers `_push_linear_state_async`; maps board status → Linear state name via `issueUpdate` mutation.
- [x] **Auto-dispatch In Progress issues** — semi-auto: `In Progress` Linear issues dispatch via Claude routing call to select skill.
- [x] **Linear project selector** — header dropdown; fetches projects from `/api/linear/projects`; selecting persists `project_slug` to WORKFLOW.md via PATCH `/api/config`; clears dispatch + issue cache on change.
- [x] **Modify Linear issues** — Linear edit section in detail modal; loads issue via `GET /api/linear/issues/<id>`; editable title, description, state dropdown (populated from team states); save via `PATCH /api/linear/issues/<id>` → `issueUpdate` mutation.

---

## P5 — Board UX Polish

- [x] **Attempt badge on cards** — `↺N` shown in card ID area when `attempt > 0`.
- [x] **Stale "sent" cleanup** — `_archive_stale_sent()` runs hourly in stall thread; auto-archives `sent` records older than 24h.
- [x] **Column card limit configurable** — `_colLimit` JS var; read from `/api/config` `board_col_limit` on init.
