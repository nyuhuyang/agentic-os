# SPEC.md — AgenticOS Runner & Dashboard

Version: 1.0  
Status: Draft  
Consumers: Claude Code, Codex, human reviewers

---

## 1. Goal

Provide a single-host web dashboard and CLI job runner that lets a user view, trigger, monitor, and triage AI skill executions, and observe token budget consumption across agents — without leaving the browser.

---

## 2. Scope

**In scope:**
- Web dashboard (single-page, single-user, localhost)
- CLI job runner for schedulable skills
- Run lifecycle management (dispatch, log, archive, restore, retry)
- Token budget visualization for Claude and Codex agents
- Embedded terminal (PTY) with skill injection
- Skill registry display, grouped by stack

**Out of scope (see Section 8):**
- Multi-user or multi-host deployments
- Skill authoring or registry editing
- Authentication / authorization
- Scheduling / cron management (triggering scheduled runs)
- Persistent storage beyond flat files (`run_log.jsonl`, `job_state.json`)

---

## 3. Definitions

| Term | Definition |
|------|-----------|
| **Skill** | An entry in the skill registry (`AI_Workspace/.codex/registry.json`) |
| **Schedule-eligible skill** | A skill with `schedule_eligible: true` AND a non-empty `entrypoint` field in the registry |
| **AI-only skill** | A skill with no `entrypoint`; dispatched directly to an agent CLI |
| **Run** | A single execution instance identified by a unique `run_id` (UUID) |
| **Run status** | One of the closed set: `running`, `success`, `failed`, `error`, `timeout`, `sent`, `archived` |
| **Agent** | One of: `claude`, `codex` |
| **Budget window** | A rolling time window (5-hour or 7-day) used to track token quota consumption |
| **Server-reported limits** | Rate limit data sourced from a live drop file or session logs written by the agent CLI |
| **Estimated limits** | Rate limit data computed locally from JSONL/SQLite when no server data is available |
| **Archive** | Soft-delete a run: set status to `archived`, preserving the original status in `prev_status` |
| **Restore** | Undo an archive: reinstate the `prev_status` as the current status |

---

## 4. Functional Requirements

### 4.1 Skill Registry Display

**FR-01** The dashboard must display all skills from the registry, grouped by their `stack` field.  
**FR-02** Stack display order must be: knowledge, research, admin, trading, publishing, automation, then any remaining stacks alphabetically.  
**FR-03** Each skill card must show: name, purpose (truncated to 80 chars), risk level badge, `confirmation_required` badge (if applicable), and `schedulable` badge (if `schedule_eligible` and `entrypoint` are both set).  
**FR-04** Skill cards incompatible with the active agent must be visually disabled and non-interactive.

### 4.2 Agent Selection

**FR-05** The user must be able to switch between `claude` and `codex` agents at any time.  
**FR-06** Switching agent must immediately: (a) update the budget window display for that agent, (b) disable skill cards whose `agents` list does not include the selected agent.  
**FR-07** The active agent determines the CLI command injected into the terminal when a skill card is clicked: `/<skill>` for Claude, `$<skill>` for Codex.

### 4.3 Skill Dispatch

**FR-08** Clicking a skill card must inject a command into the terminal PTY and emit a `skill_selected` event to the server identifying the skill and run_id.  
**FR-09** Alt-click or Shift-click on a skill card must inject the skill's first `trigger_phrase` instead of the CLI command.  
**FR-10** `POST /run` must dispatch the skill using the following routing logic:
  - If the skill is schedule-eligible (has `entrypoint`): execute via `run_skill.py`
  - Otherwise: spawn the agent CLI with the prompt
**FR-11** `POST /run` must reject dispatch if the selected agent is not listed in the skill's `agents` field. Response: `{"ok": false, "error": "..."}` with HTTP 200.  
**FR-12** `GET /stream` must provide the same dispatch logic as `POST /run` but stream output as Server-Sent Events until the process exits.  
**FR-13** `POST /run` timeout: 300s for schedule-eligible skills, 120s for AI-only dispatches.

### 4.4 Run Lifecycle

**FR-14** Every dispatched run must produce a record in `outputs/run_log.jsonl` with fields: `run_id`, `skill`, `status`, `started_at`, `duration_s`, `prompt`, `output`, `error`, `output_path`.  
**FR-15** `run_log.jsonl` must be append-only. No line may be deleted or modified in place.  
**FR-16** When multiple records share the same `run_id`, the last record in the file is authoritative.  
**FR-17** `outputs/job_state.json` must be updated atomically on every run completion, storing `last_run`, `status`, `exit_code`, `duration_s`, `error` per skill.  
**FR-18** Concurrent runs of the same skill must be rejected with an error response; the second request must not start a new process.  
**FR-19** A run may be archived via `PATCH /api/runs/<run_id>/status` with `{"status": "archived"}`. The original status must be stored in `prev_status`.  
**FR-20** An archived run may be restored via `POST /api/runs/<run_id>/restore`. The `prev_status` must become the current `status`.  
**FR-21** Retry (`GET /api/runs/<run_id>/retry`) must return the original skill name and prompt without re-executing. Execution is the client's responsibility after receiving this data.  
**FR-22** Every status transition must emit a `run_state_change` SocketIO event with `run_id` and the new state.

### 4.5 Job Board

**FR-23** The job board must display runs in four columns with the following state mappings:

| Column | States |
|--------|--------|
| Backlog | `sent` |
| In Progress | `running` |
| Human Review | `failed`, `error`, `timeout` |
| Done | `success` |

**FR-24** Archived runs must not appear in the kanban columns.  
**FR-25** Each column must show a count of its current items.  
**FR-26** A run card must show: short ID (`AS-<first 6 chars>`), skill name, truncated prompt, relative timestamp, duration.  
**FR-27** Each non-running card must have a dismiss (archive) button.  
**FR-28** Cards in `review` and `done` columns must be draggable to any other droppable column. Dropping changes the run's status to that column's `dropStatus`.  
**FR-29** The job board must auto-refresh every 15 seconds.  
**FR-30** Clicking a run card must open a detail modal showing: status badge, skill, started_at (localized), duration, run_id, prompt, output, error (if present), output_path (if present), and a retry button.  
**FR-31** The trash panel must show all archived runs. Each archived run must have a restore button.  
**FR-32** The trash panel must display a count of archived runs even when collapsed.

### 4.6 Budget Windows

**FR-33** The dashboard must display three budget window cards: 5-hour window, 7-day window, auxiliary (runs-today or Codex session count).  
**FR-34** Each window card must display: percent remaining, usage bar (color-coded: green <50%, yellow 50–79%, red ≥80%), time-until-reset, and a display line describing the data source.  
**FR-35** A pace marker must appear on each window bar indicating the expected usage at this point in the window. The marker must be visually distinct when usage is ahead of pace, behind pace, or on pace (±5% threshold).  
**FR-36** Budget data must be sourced from server-reported limits when available (Claude: drop file captured within 12h; Codex: latest session log snapshot). Fall back to local estimates otherwise.  
**FR-37** `GET /api/windows?agent=<agent>` must return the budget window data for that agent as JSON.  
**FR-38** Budget window cards must auto-refresh every 60 seconds.

### 4.7 Embedded Terminal (PTY)

**FR-39** The dashboard must provide a full PTY terminal (xterm.js) that connects to the server-side shell via SocketIO on page load.  
**FR-40** The PTY shell must start in the knowledge base root directory.  
**FR-41** Terminal height must be user-resizable via a drag handle and must persist the height to `localStorage` across page reloads.  
**FR-42** Dragging a file onto the terminal must upload the file to `outputs/uploads/` and inject the server-side path into the PTY (not the local filename).  
**FR-43** If a file with the same name already exists in `outputs/uploads/`, the uploaded file must be saved with a numeric suffix (`_1`, `_2`, …) without overwriting the existing file.  
**FR-44** On PTY disconnect, all server-side PTY state for that session (fd, input buffer, pending handoffs) must be cleaned up.

### 4.8 Activity Chart

**FR-45** The dashboard must display a line chart of run counts for the last 30 days.  
**FR-46** X-axis labels must appear at every 5th day.

### 4.9 API

**FR-47** `GET /api/runs?limit=N` must return the N most recent non-archived runs, deduplicated by `run_id`.  
**FR-48** `GET /api/runs?state=running` must return only currently in-flight runs from in-memory state (not the log file).  
**FR-49** `GET /api/runs?state=archived` must return only archived runs.  
**FR-50** `GET /api/runs/<run_id>` must return the single most-recent record for that `run_id` or `404`.  
**FR-51** `GET /api/registry` must return the raw registry `skills` object.  
**FR-52** `GET /api/usage` must return combined usage stats for Claude and Codex as JSON.

### 4.10 CLI Runner (`run_skill.py`)

**FR-53** `run_skill.py <skill>` must only execute skills with `schedule_eligible: true` and a defined `entrypoint`. Any other skill must produce an error and exit non-zero.  
**FR-54** `run_skill.py --headless <skill>` must abort (exit non-zero, no execution) if the skill has `confirmation_required: true` or `risk_level: destructive`.  
**FR-55** `run_skill.py <skill>` (interactive, no `--yes`) must prompt for confirmation if `confirmation_required: true` before executing.  
**FR-56** `run_skill.py --list` must print all schedule-eligible skills with their execution mode and entrypoint.  
**FR-57** `run_skill.py --status` must print the last-known status, last run time, and duration for all skills that have been run.  
**FR-58** `run_skill.py <skill> --retry N` must re-execute the skill up to N additional times on failure, stopping on first success.  
**FR-59** `run_skill.py <skill> --dry-run` must print the command that would be executed without running it, then exit 0.

---

## 5. Non-Functional Requirements

**NFR-01 Single-user, localhost only.** The server must bind to `127.0.0.1` by default. It must not be exposed to external networks without explicit `--host` override.

**NFR-02 No data loss on crash.** Because `run_log.jsonl` is append-only and `job_state.json` uses atomic rename, a process crash between writes must leave both files in a valid, parseable state.

**NFR-03 Run log size.** The system must remain functional when `run_log.jsonl` contains ≥10,000 lines. The `load_runs(limit)` function must not read the entire file into memory before applying the limit when the file is large.

**NFR-04 Concurrent run safety.** Two simultaneous requests to dispatch the same schedule-eligible skill must result in exactly one process being started. The second must return an error without spawning a process.

**NFR-05 No network dependency at startup.** The dashboard must load and display the registry, run log, and skill cards without any outbound network request. CDN assets for Chart.js, xterm.js, and Socket.IO are loaded client-side; the server must not block on them.

**NFR-06 Template rendering latency.** `GET /` must return HTTP 200 within 5 seconds on a machine where `~/.claude/projects/` contains ≤500 JSONL files totalling ≤500 MB.

**NFR-07 PTY cleanup.** A PTY file descriptor must not remain open after the WebSocket session disconnects.

**NFR-08 File upload safety.** Uploaded filenames must be sanitized (werkzeug `secure_filename`) before being written to disk. Path traversal via filename must be impossible.

---

## 6. Edge Cases

**EC-01 Missing registry.** If `AI_Workspace/.codex/registry.json` does not exist: the dashboard must render with zero skills and zero stats (not crash). `run_skill.py` must exit non-zero with a descriptive error.

**EC-02 Missing `outputs/` directory.** The first run must create `outputs/` (and `outputs/locks/`) if they do not exist, then succeed normally.

**EC-03 Corrupt `run_log.jsonl` line.** A non-parseable JSON line must be silently skipped; all other lines must be processed normally.

**EC-04 Corrupt `job_state.json`.** If `job_state.json` is not valid JSON, the system must treat it as empty and overwrite it on the next run completion.

**EC-05 Duplicate `run_id` in log.** If two records share the same `run_id`, the last one in the file is authoritative. Both must be deduplicated out of API responses (only the last survives).

**EC-06 `run_id` absent (legacy records).** Records without a `run_id` must be assigned a stable deterministic ID derived from `started_at` + `skill` (e.g., `legacy-<md5[:8]>`).

**EC-07 Budget window reset boundary.** If the server-reported snapshot was captured before the most recent window reset, the usage percentage must be treated as 0% (not the stale value from before the reset).

**EC-08 No live rate limit data.** If no server-reported rate limit data is available (drop file absent or older than 12h), the dashboard must display estimated limits with a visible indicator that the values are estimates, not actuals.

**EC-09 Agent CLI not found.** If `claude` or `codex` binary is not on PATH, `POST /run` must return `{"ok": false, "error": "<agent> CLI not found."}` without crashing the server.

**EC-10 Skill `agents` field absent.** If a skill has no `agents` field in the registry, it must be treated as `["claude"]` (default to Claude only).

**EC-11 Skill card for running job.** A card for a currently-running skill must not be dismissible or draggable.

**EC-12 Retry of archived run.** `GET /api/runs/<run_id>/retry` must succeed even if the run is archived — it returns skill + prompt for re-dispatch; it does not change the archived status.

**EC-13 File upload collision.** If `secure_filename` produces an empty string (e.g., all-special-character filename), the upload must be rejected with `{"error": "empty filename"}`.

**EC-14 `KNOWLEDGE_BASE` env var.** If set, all path resolution (registry, outputs, wiki) must use the provided path instead of the default relative path. The server must fail with a clear error at startup if the provided path does not exist.

---

## 7. Acceptance Criteria

Each criterion is traceable to a functional or non-functional requirement.

### Dashboard loads

**AC-01** `GET /` returns HTTP 200 with `<title>AgenticOS</title>` in the body. *(FR-01)*  
**AC-02** With an empty registry, `GET /` returns HTTP 200; the skill grid is empty; stats show `0` for all counts. *(EC-01)*  
**AC-03** With `KNOWLEDGE_BASE=/nonexistent`, the server process exits within 5 seconds with a non-zero code and a message referencing the missing path. *(EC-14)*

### Skill display

**AC-04** Given a registry with skills in stacks `[knowledge, trading, other]`, the rendered HTML presents `knowledge` before `trading` before `other`. *(FR-02)*  
**AC-05** A skill with `schedule_eligible: true` and `entrypoint` set renders with a `schedulable` badge. A skill without `entrypoint` does not. *(FR-03)*  
**AC-06** A skill with `agents: ["codex"]` has class `agent-disabled` when the active agent is `claude`, and does not have that class when the active agent is `codex`. *(FR-04, FR-06)*

### Skill dispatch — `POST /run`

**AC-07** `POST /run` with `{"skill": "X", "agent": "codex", "prompt": "p"}` where skill `X` has `agents: ["claude"]` returns `{"ok": false}` and does not append to `run_log.jsonl`. *(FR-11)*  
**AC-08** `POST /run` with a schedule-eligible skill returns `{"ok": true, "run_id": "<uuid>", "duration_s": <number>}` and appends one record to `run_log.jsonl`. *(FR-10, FR-14)*  
**AC-09** `POST /run` with a prompt exceeding the 120s timeout returns `{"ok": false, "error": "Timed out after 120s."}` and appends a `timeout` record to `run_log.jsonl`. *(FR-13, FR-14)*

### Run log integrity

**AC-10** After 100 sequential runs of the same skill, `run_log.jsonl` has exactly 100 lines, each valid JSON, each with a unique `run_id`. *(FR-14, FR-15)*  
**AC-11** If a line in `run_log.jsonl` is manually corrupted (set to `{invalid`), `GET /api/runs` returns all valid records and omits the corrupt line without error. *(EC-03)*  
**AC-12** `job_state.json` contains valid JSON after each run. If the file is manually set to `{invalid}` before a run, `job_state.json` contains valid JSON after the run completes. *(FR-17, EC-04)*

### Concurrent dispatch

**AC-13** Two simultaneous `POST /run` requests for the same schedule-eligible skill result in exactly one process being spawned. The second response includes `"ok": false` referencing a lock or already-running condition. *(NFR-04, FR-18)*

### Run status transitions

**AC-14** `PATCH /api/runs/<run_id>/status` with `{"status": "archived"}` appends a record to `run_log.jsonl` where `status == "archived"` and `prev_status == <prior status>`. The original record is unchanged. *(FR-15, FR-19)*  
**AC-15** `POST /api/runs/<run_id>/restore` on an archived run appends a record where `status == prev_status`. Subsequent `GET /api/runs/<run_id>` returns the restored status. *(FR-20)*  
**AC-16** `PATCH /api/runs/<run_id>/status` with `{"status": "running"}` returns HTTP 400. *(FR-19 — `running` is not an allowed target status)*

**Assumption:** `running` is excluded from the PATCH-allowed set (`success`, `failed`, `archived`) based on `app.py:810`.

### Job board

**AC-17** `GET /api/runs` does not include runs with `status == "archived"` by default. `GET /api/runs?state=archived` returns only archived runs. *(FR-24, FR-49)*  
**AC-18** A run with `status == "running"` appears in the In Progress column; after `run_state_change` fires with `state == "success"`, it moves to Done on the next board refresh. *(FR-23, FR-22)*

### Budget windows

**AC-19** `GET /api/windows?agent=claude` returns a JSON object with keys `window_5h`, `window_7d`, and `aux`, each containing `pct`, `reset`, `sessions`. *(FR-37)*  
**AC-20** When `~/.claude/` rate-limits drop file is absent, the `window_5h` response includes `"estimate_only": true` or equivalent indicator; when present and captured within 12h, it does not. *(FR-36, EC-08)*  
**AC-21** If the drop file was captured before the last reset boundary and the current time is past that boundary, `pct` must be `0`. *(EC-07)*

### PTY and file upload

**AC-22** After uploading a file named `foo.txt` twice via drag-and-drop, `outputs/uploads/` contains both `foo.txt` and `foo_1.txt`. *(FR-43)*  
**AC-23** Uploading a file with name `../../../etc/passwd` results in `{"error": "empty filename"}` or the file being saved as `etcpasswd` (or similar sanitized name) inside `outputs/uploads/` — never outside that directory. *(NFR-08, EC-13)*  
**AC-24** After the WebSocket client disconnects, the file descriptor count for the server process does not increase (no fd leak). *(NFR-07, FR-44)*

### CLI runner

**AC-25** `run_skill.py nonexistent-skill` exits non-zero and prints to stderr. *(FR-53)*  
**AC-26** `run_skill.py <skill> --headless` where skill has `confirmation_required: true` exits non-zero without executing the entrypoint. *(FR-54)*  
**AC-27** `run_skill.py <skill> --dry-run` prints the command and exits 0 without appending to `run_log.jsonl`. *(FR-59)*  
**AC-28** `run_skill.py <ai-only-skill>` (no entrypoint) exits non-zero with a message indicating the skill is not schedule-eligible. *(FR-53)*  
**AC-29** `run_skill.py <skill> --retry 2` where the entrypoint fails twice then succeeds on the third attempt: exits 0 and `run_log.jsonl` contains one record with `status == "success"`. *(FR-58)*

**Assumption:** `run_skill.py` writes one final record per invocation, not one per attempt.

---

## 8. Out of Scope

- **Authentication / authorization.** Any client that can reach the server can dispatch skills and read all run data. Restricting access is the operator's responsibility (e.g., firewall, SSH tunnel).
- **Scheduling / cron management.** The dashboard can trigger individual runs but does not create, manage, or display recurring schedules. `launchd`/`cron` wiring is external.
- **Skill authoring.** Creating, editing, or deleting skill YAML manifests or entrypoint scripts.
- **Registry editing.** The registry is read-only from the dashboard's perspective. Rebuilding it (`build_registry.py`) is an external operation.
- **Run output storage beyond the log.** The system records a summary of output in `run_log.jsonl` but does not archive full output artifacts. Skill entrypoints are responsible for their own output paths.
- **Horizontal scaling / remote workers.** The runner is single-host. PTY sessions are in-process. No job queue, no distributed state.
- **Token cost billing accuracy.** Cost estimates are approximate (output-token-based). They are not suitable for financial reconciliation.
- **Mobile / narrow-viewport support.** The layout targets ≥1200px wide displays.
