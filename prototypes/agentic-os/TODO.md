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

- [ ] **Live elapsed timer on In Progress cards** — client-side tick from `started_at` using in-memory `_running_jobs`. No server change needed.
- [ ] **Last-event / live status line on running cards** — emit `run_progress` SocketIO event during SSE streaming with latest output snippet; show on card below skill name.
- [ ] **Cancel button on running cards** — `DELETE /api/runs/<run_id>` → kill subprocess by PID, write `cancelled` status to log. Only enabled for `running` state.
- [ ] **Retry column / "Queued" state** — when `/api/runs/<id>/retry` is confirmed, write a `queued` record; server schedules delayed re-dispatch. Show in Todo column or a dedicated Queued sub-state.

---

## P2 — Attempt Tracking and Retry Backoff

- [ ] **Attempt counter** — `run_log.jsonl` records gain `attempt` field (0 = first, 1+ = retry). Retry endpoint copies `attempt+1` to new record and sets `parent_run_id` pointing to original.
- [ ] **Retry backoff** — server-side: store `due_at` on queued retry records; `/api/runs?state=queued` returns them; board shows countdown `due in Xm`.
- [ ] **Stall detection** — background thread: if running job has no SocketIO `run_progress` event for `STALL_TIMEOUT_S` (default 300s), auto-transition to `failed` with error `stalled`.

---

## P3 — Token and Runtime Visibility

- [ ] **Backend selector (CLAUDE / CODEX)** — toggle in dashboard header to switch active agent backend. Writes `agent.backend` into `WORKFLOW.md` (or equivalent config). Highlighted button reflects current backend. Token and runtime panels update label to match selected backend (e.g. "Total CLAUDE runtime").

- [ ] **Per-run token count on cards** — parse `input_tokens`/`output_tokens` from `claude -p` JSON output before logging; store in `run_log.jsonl`; show on card footer.
- [ ] **Aggregate runtime panel** — stat chip in header: total `duration_s` summed from `run_log.jsonl` + elapsed from `_running_jobs`. Mirror Symphony `codex_totals.seconds_running`.
- [ ] **Turn count on running cards** — SSE stream: count output chunks as turn proxy, emit `turn_count` via SocketIO on `run_state_change`; show `T:N` badge on In Progress cards.

---

## P4 — Linear Sync

- [ ] **Sync job board with Linear** — poll Linear API for issues in configured project; mirror issue state (Todo, In Progress, Done, etc.) onto job board columns. Map Linear states → board statuses bidirectionally.
- [ ] **Create/update Linear issues from board** — allow creating a Linear issue from a job card and pushing status transitions back to Linear (e.g. moving card to Done → marks Linear issue Done).
- [ ] **Linear project selector** — UI dropdown to pick active Linear project (`project_slug`); persisted to config. Drives which issues are synced.
- [ ] **Modify Linear issues** — edit title, description, state, and labels directly from card detail modal via Linear GraphQL API.

---

## P5 — Board UX Polish

- [ ] **Attempt badge on cards** — if `attempt > 0`, show `↺N` badge. Visual link between retry chain members.
- [ ] **Stale "sent" cleanup** — Backlog entries auto-archive after 24h or add "clear sent" button.
- [ ] **Column card limit** — currently hard-coded to 15 per column. Make configurable or paginate within column.
