---
status: in-progress
created: 2026-10-16
---

# Projects stacked vertically; one task, one session, named by the card title

## Goal
User request (2026-10-16, via /claudex-loop):
> 不要把这个 project 这样横着排，还是像以前那样竖着排比较合理。还有每个 session 有一个固定的名称。就用这个TITLE就可以，也支持可以直接在task里面改。尽量把不同的任务划分在不同的 session 里面，这样好找一点。我就不要开太多这种小的 session。

Three changes:
1. **Vertical projects.** The Projects panel goes back to a vertical list of collapsible project sections (as before `5f2c1ce`), not a horizontal tab strip.
2. **Fixed session name = the card title.** A session that belongs to a card is always named by that card's title:
   - in the Projects panel,
   - in the agents' own pickers (`claude --resume`, `codex resume`).
   Editing the title in the task (card) renames the session. Renaming the session renames the card.
3. **One task, one session.** Every dispatch of a card continues the card's own session instead of opening a new one. A new task (new card) gets a new session, so sessions map one-to-one to tasks and stay easy to find.

Follow-up to `docs/exec-plans/completed/2026-10-16-session-to-board.md`. That plan introduced the tab strip (its "Projects panel is a tab strip" criterion), the to-board route, `resume_session` intents, and the `_board_sessions` labels this plan builds on.

## Decisions
The session could not ask questions, so Claude took these recommended defaults. The user can override any of them before the build.
- **D1 Layout.** Collapsible vertical sections, ▸/▾ per project. Several projects can be open at once.
  - The open set and the order are per-browser preferences that survive a reload.
  - The existing saved order (`agenticos.projectTabs.order`) is kept, so the user's current order carries over.
  - Reordering: drag a project head up or down, or Alt+↑/↓ on a focused head.
  - The tab-strip markup, CSS, selection key and ←/→ handling are removed.
- **D2 Names, two-way.**
  - A card-bound session's display name and its native name are the card's title.
  - The card title is edited in the card's issue editor; that renames every session bound to the card.
  - Rename on a session row of a card-bound session renames the card. That in turn renames the sessions.
  - Sessions without a card keep their current title and today's Rename.
- **D3 One task, one session.** A dispatch continues the card's session for the dispatching agent when one exists and is still resumable. Otherwise it starts a new session, and the run view says why.
  - "Start over" means a new card; there is no "fresh session" toggle (non-goal).
  - Changing the card's agent necessarily starts that agent's own session, since one CLI cannot resume another's.
- **D5–D7 Card replies.** See §5 (added after the user's 2026-10-16 report on quick reply).
- **D4 Build.** Plan and review now. Building starts only after the user's go-ahead: the request was a claudex-loop run, and no build authorization was given.
- **Reviewer.** Codex plan review (claudex-loop). If Codex has no usage, DeepSeek read-only (standing user rule), recorded as third-party.

## Definitions
- **Card-bound session.** An (agent, session id) pair carried by any of:
  - a run record that has a `linear_issue_id`;
  - a running job that has one;
  - a session claim (`_SESSION_CLAIMS`) whose run is such a job.

  Its card is that issue; when several issues claim one session, the newest record wins. Only claude and codex sessions (no dsh).
  - The issue must be live: `_tracker_issue(issue_id)` is not None, the same rule as `_session_card`. An archived or emptied card makes its sessions card-less again: their Rename behaves as today, and no dispatch or reply resumes through them (DP-29).
    - This includes the existing persisted-intent path: `_valid_intent` returns None when `_tracker_issue(issue_id)` is None (DP-45).
    - **Explicit refusal (Codex R2).** `api_run_retry` checks liveness first, for any record with a `linear_issue_id`. That check runs before intent fallback, agent-lock continuation, tracker updates or worker scheduling. A missing issue → 409 "this card no longer exists", and nothing launches.
    - Liveness is checked again under `reset_gen.issue_lock` at admission, in both workers. External deletion bumps no generation, so it cannot rely on the generation check.
- **`_card_sessions()`** (new, app.py) returns (agent, sid) → issue id, built from all three sources (DP-01, DP-08).
  - `_board_sessions()` keeps its 2-tuple shape, so none of its callers change.
- **Runner-owned session lookup.** `projects.find_session(agent, sid)` (new) gives `{agent, id, cwd, path, title, native_title}` for a session the runner itself launched or bound (DP-02).
  - `native_title` is the name the agent's picker uses: Claude's newest `custom-title`, or Codex's `threads.name`. It is `None` when unset, and is separate from the display `title` fallback chain (DP-30).
  - The id is format-checked.
  - Claude: `<store>/*/<sid>.jsonl` inside the resolved `~/.claude/projects`, not a symlink.
  - Codex: a non-archived `threads` row with its rollout inside the resolved Codex store.
  - No project-root check: the id comes from the runner's own records, never from a client.
  - Used for dispatch continuation and for native renames of card-bound sessions. `session_target` (project-scoped, client-facing) stays for the panel's own routes.
- **Card title (display).** The tracker's current title: the Linear cache, or the local tracker.
- **Card title (confirmed), for native renames (DP-31).**
  - Local mode: the local tracker's stored title.
  - Linear mode: `_linear_titles[issue_id] = (title, updatedAt)`, written only from issues Linear itself returned (poll, `fetch_issue`, a confirmed update), before any local override is applied.
    - **Freshness (Codex R4).** A write is taken under the issue's lock, and only when its `updatedAt` is newer than or equal to the stored one.
    - A poll that fetched an older title before a confirmed rename therefore cannot roll the confirmed title, or the native name, back.
    - The confirmed update's `updatedAt` comes from the mutation's response (`issue { title updatedAt }`).
  - A native rename only ever uses the confirmed title. The display cache can hold an unconfirmed `/local` title, so it is never used for one.
  - Fallback: `issue_title`, a new field written on each card run record at launch.
  - Final fallback, **display only**: the session's own title.
  - A native rename never falls back to the session's own title, which for a headless card session is the runner preamble. With no confirmed tracker title and no record `issue_title`, the sync skips (DP-46).
  - `create_session_issue` writes `_linear_titles` from the issue it created, and the to-board record carries `issue_title`. A brand-new to-board card therefore has a confirmed title before its first poll.
- **Native name.**
  - Claude: the newest `custom-title` record in the transcript, which is what `/rename` writes and `claude --resume` shows.
  - Codex: `threads.name`.
  - Written only through `projects.rename_session`.
- **Session name text.** The card title with control characters replaced by spaces, whitespace collapsed, and cut to 200 characters (the limit `_clean_title` enforces). An empty result leaves the native name unchanged.

## Acceptance criteria
- [x] Projects panel shows projects stacked vertically, each with a ▸/▾ head (name, badges, session count, Open terminal, Run tests, Edit, Remove); no horizontal tab strip remains — code: `_renderProjectsInto` sections, tab-strip code/CSS removed (grep: no `data-ptab`/`proj-tab`); node --check passes; browser check BLOCKED (see Manual)
  - [ ] several projects can be open at once; open set and order survive a reload; a new project appears at the end (closed); a removed one drops out
  - [ ] drag a head to reorder; Alt+↑/↓ on a focused head moves it; plain click/Enter toggles open
  - [ ] the Sessions / Files tabs inside an open project work as before (Files state per project)
  - [ ] an error project shows its error and Remove in its head
- [x] Every card-bound session row shows `IDENT · <card title>` (never the runner preamble), including a session whose run is still running — `_board_sessions` labels running jobs with their card title; tests/test_session_titles.py (labels via `_card_sessions`)
- [x] After a card run ends, its session's native name equals the card title (`claude --resume` / `codex resume` show it) — tests/test_session_titles.py::test_retry_after_reset_continues_the_card_session (custom-title written), ::test_codex_name_is_written_even_when_its_display_title_matches
- [ ] Editing a card's title in its issue editor (Linear or local tracker) renames its idle card-bound sessions at once; a busy one is renamed when its run or terminal ends; the panel shows the new title immediately either way
- [x] Rename on a card-bound session row changes the card title (tracker first) and the session's native name; a tracker failure changes nothing and shows the error; Rename on a session without a card behaves as today — tests/test_session_titles.py::test_card_row_rename_renames_the_card_and_the_session, ::…validates_before_any_write, ::…failed_linear_update_changes_nothing, ::test_archived_cards_session_row_renames_only_the_session
- [x] Dispatching a card that already has a resumable session for the dispatching agent continues that session (same session id, same folder), for both a generic card and a project ticket card, including after a drag back to Todo — tests/test_session_titles.py::test_dispatch_continues_the_card_session_without_routing, ::test_project_dispatch_continues_the_session_in_its_worktree; tests/test_reset_gen.py (rewritten D3 tests)
- [x] Dispatching with no resumable session (none yet, removed or archived, in another folder, other agent) starts a new session, and the run view states the reason — tests/test_session_titles.py::test_fresh_dispatch_routes_without_leaving_a_session, ::test_project_dispatch_with_the_session_elsewhere_starts_fresh_with_a_note, ::test_retry_without_a_session_on_disk_starts_fresh_with_a_note
  - [x] a resume that fails at launch ends the run as an error (no silent new session) — tests/test_session_titles.py::test_failed_card_resume_is_an_error_with_the_agents_reason
  - [x] a project ticket whose bound worktree is gone keeps today's fail-closed error (I6-10) — tests/test_project_dispatch.py::test_redispatch_never_recreates_a_removed_worktree (unchanged, passes)
- [x] Decision 11 completion/stale-record guards, the agent lock, and the to-board `resume_session` intent behave as before; only the named reset tests change, to assert the D3 continuation — tests/test_reset_gen.py: the four named tests rewritten; the others unchanged and passing
- [x] Full suite passes: `.venv/bin/python -m pytest tests/ -q -p no:cacheprovider` — 674 passed (2026-10-17)

## Approach

### 1. Vertical projects (index.html only)
- `_renderProjectsInto`: restore the section-per-project rendering of `5f2c1ce^`.
  - Iterate in `_projTabOrder(ps)` order (key unchanged).
  - Open state comes from `agenticos.projects.open`, a JSON list of keys read and written through `_storageGet`/`_storageSet`, wrapped like the other storage calls. A missing or invalid value means none open.
- Head: `<div class="project-head" draggable="true" tabindex="0" data-key=…>`, with the ▸/▾ toggle on click or Enter/Space.
  - Clicks on its buttons don't toggle; that guard is kept from the old code.
  - Error projects: head with the error and Remove, not draggable-toggleable.
- Reorder:
  - dragstart/dragover/drop on `.project-head`, reusing `_projTabMove`;
  - Alt+ArrowUp/ArrowDown on a focused head; focus stays on the moved head after the re-render.
- Delete:
  - `.proj-tabstrip` / `.proj-tab` CSS;
  - the `data-ptab` click, drag and key handlers;
  - `agenticos.projectTabs.active`.
- `_projectBody` (Sessions/Files) is reused unchanged for each open project.

### 2. Card-bound sessions and their names (app.py, projects.py)
- `_board_sessions()` also adds labels for running jobs that have both an `agent_session_id` and a `linear_issue_id`. This fixes the unlabeled "You are working in a git worktree…" row of a running card.
  - For the title it uses the tracker cache, falling back to the record's or job's `issue_title`.
  - The (agent, sid) → issue map is `_card_sessions()`, not a third return value: `_board_sessions()` stays a 2-tuple (DP-01, DP-12).
- A running card's session must be visible while it runs (DP-15, Codex R3):
  - `run_agent_process` gains an optional `on_session(sid)` callback, called from the stream readers as soon as the init event (Claude) or `thread.started` (Codex) names the session.
  - **Every** tracker-card call passes one that sets `_running_jobs[run_id]["agent_session_id"]`: generic dispatch, plain retry (`_dispatch_cmd`), and the session-card reply worker.
  - A cancel or stall after the session is announced therefore persists the id through `_write_owner_record`, and the next launch continues it.
  - The project helper already does this through `project_runs.run_agent(on_session=…)`.
- Launch paths write `issue_title` (the card title at launch) on the card's records:
  - `_dispatch_issue_held` (generic and project),
  - the retry/reply route,
  - the to-board reply.
  - **Confidentiality (DP-24).** `issue_title` follows the same withholding rule as prompt and output. When the run is confidential (`confidential is not False`) and `_records_unsafe()` is truthy, the field is omitted from the record. This holds on every writer: `_run_project_ticket_locked`, the retry/reply and to-board workers, `_dispatch_issue_held`, and `_write_owner_record`. Such a card's session then falls back to the tracker cache, or to its own title.
- New `_sync_card_session_names(issue_id, *, ended=None)` in app.py. For each card-bound session of the issue:
  1. resolve it with `find_session(agent, sid)`. Unresolvable → skip;
  2. skip it if its `native_title` already equals the session name text. The display `title` is never compared (DP-30);
  3. take `session_lock` (non-blocking; held → skip);

  **Serialization (Codex R5).** The whole sync for an issue runs under a per-issue `_title_sync_lock(issue_id)`. This is a blocking `threading.Lock`, separate from `reset_gen.issue_lock`, so routes that already hold the issue lock can call it without re-entering it.
  - Under it the sync re-reads the latest confirmed title. An explicit `title=` argument is used only if it is still the latest confirmed version; otherwise the latest wins.
  - It then does steps 1–5.
  - Every confirmed-title writer (`_linear_titles` update, local `update_issue`) takes the same lock around its write.
  - So a delayed run-end sync that picked title A before an edit to B either runs before the edit's sync, which then renames to B, or re-reads B.
  - Lock order: `_title_sync_lock` → `session_lock`.
  4. check that it is idle against a live set built from:
     - live terminals,
     - every running job except the `ended` owner,
     - every session claim except the `ended` owner's.

     The mtime 2-minute rule is waived in two cases. In both, any other live terminal, job or claim on the session still blocks the rename:
     - for the `ended` owner, the one whose own process has just exited: `("run", run_id)` or `("term", term_id)` (DP-03, DP-11);
     - when the transcript or rollout was last written no later than `_own_activity_end(issue_id) + 5 s`, i.e. by this card's own last run or terminal. This is the same exemption `session_in_use` uses. A title edit or card-row rename right after a run therefore renames at once (DP-26).

     Busy → skip, retried at the next trigger;
  5. `rename_session(target, name)`. Errors are logged at warning level and never raised.
- `_write_owner_record` records the real elapsed `duration_s` (now − the job's start) instead of `0.0`. `_own_activity_end` then ends at the cancel or stall time, so a cancelled card's own last write is not mistaken for "in use elsewhere" (DP-27).
- Triggers:
  - after every card run record written by `_write_owner_record` (cancel, stall, shutdown), for generic and project runs, after the job is popped (DP-20).
    - **Only after the writer has exited (Codex R6).** The stall and cancel paths only signal the process group (`_kill_group`, no wait).
      - When they signal a run that carries a session, they first set a **closing marker**, `_CLOSING_SESSIONS[(agent, sid)] = pgid`, before writing the owner record.
      - The marker is part of the live set for **every** native sync. So no trigger renames that session while the marker stands, not even an unrelated title edit, and the own-activity exemption does not apply to it.
      - A background watcher clears the marker only once **no process remains in the run's process group** (`os.killpg(pgid, 0)` → `ProcessLookupError`). Reaping the leader alone is not enough, because descendants in the group count too.
      - The watcher checks every second for up to 5 minutes. When the group is confirmed gone, it clears the marker and runs the sync with `ended=("run", run_id)`.
      - If the group is still present after 5 minutes, the marker stays, a warning is logged, and nothing is renamed. Any later sync attempt rechecks the group, and clears the marker only when the group is gone.
      - The owner record itself stays immediate;
  - after every card run ends, on all four launch paths: the generic dispatch, `_run_project_ticket_locked`, retry/reply, and the to-board reply. It runs after the run's record is written **and** after its `_running_jobs` entry is popped, on every path including the project helper (which pops after the record, app.py ≈L3362). It passes `ended=("run", run_id)`;
  - in `_finalize` of a card terminal, after `record_interactive_ended`, once its process group is gone (`_kill_session` reaped it, or it exited by itself). It passes `ended=("term", term_id)`, so the transcript the terminal wrote seconds ago does not block the rename (DP-11);
  - after a **confirmed** title change in the issue PATCH route of the **authoritative** tracker, when `title` is in the body (DP-04, DP-10):
    - Local tracker (`_capability.type == "local"`): either route, once `update_issue` has returned the issue.
    - Linear: only `/api/linear/issues/<id>`, once the update is confirmed. The route records `_linear_titles[issue_id]` from the confirmed result and then calls the sync with that title.
      - This holds both in the synchronous branch (after its `fetch_issue`) and in the local-first In Progress branch, inside `_linear_sync_patch_locked` after its fetched issue confirms the title (DP-31).
    - The `/local/<id>` route never triggers a rename in Linear mode. The editor fires it in parallel as a local mirror, and it would otherwise rename on a failed Linear update.
    - An unconfirmed Linear update keeps today's response, but triggers no rename;
  - after a card-row rename (§3).
- Panel: `_sessionRow` already shows `label · card_title`. `card_title` is now set for every card-bound row, so the display follows the card title even before the native rename lands.
- Refresh (DP-18): the `linear_issues_updated` handler also calls `loadProjects()`. It is debounced with the board refresh and runs whether or not Linear is configured. A title edit in the editor therefore shows in the session rows at once, not on the 60 s poll.

### 3. Rename on a card-bound session row
- `api_session_rename` first checks `_card_sessions()`. A card-bound (agent, sid) takes its own branch, **outside** `_session_action` and its session lock, so the sync can take that lock itself (DP-06):
  1. `_projects.session_target(project, agent, sid, board_ids)` still checks that the row belongs to the project in the URL. Unknown → 404, as today;
  2. the submitted title is validated with `_clean_title` (1–200 characters, no control characters) **before** anything is written. Invalid → 400, nothing changed (DP-17);
  3. `_set_card_title(issue_id, title)` (new) does a **strict** tracker update (DP-04):
     - Linear: `_graphql_strict` `issueUpdate(title)`, or `update_issue` followed by a `fetch_issue` that must show the new title;
     - local: `update_issue` must return the issue.

     - The Linear call is a dedicated **title-only** `issueUpdate(id, input: {title})` mutation, so the description is never sent as null and cleared (DP-42).
       - `LinearClient.update_issue` is **not** used here. Its shared mutation always sends `description` and `stateId`, and an omitted variable becomes null.
       - The test asserts that description and state are unchanged.
     - Only after confirmation does it update `issues_cache`, the team cache `_issues_by_team[tid][issue_id]` when present (DP-23), `_linear_titles[issue_id]` (DP-38), and the local override, then emit `linear_issues_updated`.
     - Unconfirmed → 502 with the error, and nothing else changes;
  4. `_sync_card_session_names(issue_id, title=<the confirmed title>)`. Every trigger that has just confirmed a title passes it explicitly. Other triggers read the confirmed title (DP-38). If this session was skipped as busy, the response is 200 with `pending: true`. The UI shows "session name follows when it is idle" on the row.
- UI (DP-16): the Rename input of a card-bound row is prefilled with `s.card_title || s.title`, the name it displays. An unedited Save therefore never writes the native title, such as the runner preamble, into the card.
- Not card-bound → today's behaviour.

### 4. One task, one session (dispatch)
- New `_card_session(issue_id, agent)`: the newest record of the issue with `canonical_agent(agent)` and an `agent_session_id`.
  - It returns None unless `_tracker_issue(issue_id)` is live (DP-43).
  - It looks across **all** reset generations and skips `interactive_ended` audits and archived records.
  - Returns `(sid, record)` or None.
- **The new invariant (DP-07, DP-33).** Today a reset to Todo forces a fresh session. That rule is deliberately replaced for tracker cards, on **every** launch path: dispatch, and a reply or Retry from the card.
  - A reset to Todo no longer forces a fresh session; only a new card does.
  - `_card_session` is therefore **not** generation-gated.
  - In the retry route: whenever `_lock_session_id` is None, `_card_session(issue, chosen agent)` is consulted. That covers no lock after a reset, and also a lock that carries no session id, e.g. a fresh launch that failed before announcing one (DP-40). The agent lock, if any, still decides the agent.
  - **Routing every tracker-card continuation (DP-34, Codex R1).** The session id may come from the agent lock (`_lock_session_id`) or from `_card_session`.
    - Either way, once the agent lock is enforced, a tracker card's continuation is routed by the folder that `find_session` resolves for that session.
    - It never goes through the old `bound` block's unconditional `_run_project_ticket(reuse_only=True)`.
    - So the second, third and later reply after a reset of a main-checkout session card keep running in that main checkout.
    - The old `bound` block remains only for its original case: a bound ticket whose session lives in its worktree. The routing below reaches the same helper for that case.
    - The route builds a transient intent `{agent, id, project_key: the card's binding or record project, gen: current}`.
    - It hands that intent to the existing session-card reply worker `_retry_session_card_held` (completed plan §3.3), with a new `card_sourced=True` admission mode (DP-34, round 8):
      - it skips only the `intent == _valid_intent(_intent_latest(issue))` equality, which a reset card can never satisfy;
      - instead, under `reset_gen.issue_lock`, it requires `_tracker_issue(issue)` to be live and `reset_gen.current(issue) == intent["gen"]` before claiming;
      - its records do **not** carry `resume_session`: a later reply finds the session again through `_card_session`, and no new persisted intent appears. That worker resolves the folder from the session and routes by it:
      - the bound ticket worktree → `_run_project_ticket`;
      - any other folder, a project main checkout included → `run_agent_process` in that folder, under the project policy, with the same card and project locks.
    - A card with no project (generic, `ROOT`) uses the plain retry path with the found session id, resumed in `ROOT`.
    - Every card-session continuation is **strict** (DP-35): the plain retry's "resume failed → fresh `_ai_command`" fallback is suppressed. The real error is recorded, with status `error`. The fallback stays only for non-card (`/run`) retries.
  - The admission is the same as for dispatch.
  - Generations keep governing:
    - stale completions and pushes;
    - the agent lock, so the agent can be changed after a reset;
    - the to-board `resume_session` intent.
  - `/run` cards (no tracker issue) are unchanged.
  - Existing tests whose expectation changes (named): `tests/test_reset_gen.py::test_tracker_reset_route_then_retry_starts_fresh`, `::test_restored_pre_reset_run_is_not_resumed`, `::test_reset_then_fresh_launch_failing_before_session_then_retry_still_fresh`, and the last two assertions of `::test_old_run_completing_after_reset_neither_resumes_nor_moves_ticket`. Each is rewritten to assert the continuation and renamed.
  - Unchanged: `test_agent_change_honored_after_reset`, the stale-completion assertions, and `tests/test_session_to_board.py::test_reply_rules_agent_empty_and_reset` (the intent is still voided).
- `_dispatch_issue_held`:
  - **Generic path.** If `_card_session` finds a session, `find_session` resolves it, and its cwd is the generic launch folder (`ROOT`, where generic dispatch runs), then the command becomes `_build_resume_cmd(agent, sid, prompt)`, run in `ROOT` as today.
    - The session is claimed with `_claim_session` for the run and released at the end, as retry does.
    - Admission: the session must not be live (`_live_session_ids`), must not be in use outside the dashboard, and `_claim_session` must succeed.
      - "In use outside the dashboard" is `session_in_use(target, None, _own_activity_end(issue_id))`, the predecessor's argv-match plus recent-write detector that the reply path already uses (DP-25). The worker has no confirmation channel, so a positive result refuses.
      - Live, in use elsewhere, or `SessionBusy` from the claim's non-blocking `session_lock` (e.g. a rename or sync holds it at that instant) → the worker writes an error record "session in use elsewhere" and calls `_mark_issue_review`, so the card leaves In Progress (DP-05, DP-13).
      - Nothing is launched; dispatch has no HTTP channel for a 409.
    - Failure of the resumed launch → error record "resume of session … failed", status `error`; no fresh fallback (DP-14).
      - Today's generic path forces `ok = True` for every non-dsh backend. That is kept for fresh launches only.
      - A resumed launch keeps the real result: non-zero exit, or no output → `error`.
    - The job's `agent_session_id` is set to `sid` before launch, so the live set and the panel label see it while it runs (DP-15).
  - **Project path.** `_run_project_ticket(..., resume_session=sid)`, but only when `find_session`'s cwd resolves to the ticket's bound worktree (`reuse_only` already keeps that worktree).
    - Session missing, or in another folder → a new session in the bound worktree, with the reason.
    - **Bound worktree missing** (e.g. after `projects cleanup`) → unchanged: today's fail-closed error "bound worktree is missing; refusing to fall back" (I6-10, `test_redispatch_never_recreates_a_removed_worktree`). No new session (DP-09).
    - The same admission applies (live, `session_in_use`, claim), with an error record and the card to review.
  - **No resumable session** → today's fresh launch, plus a run-view note `new session: <reason>`. Reasons: no session yet, session removed or archived, other agent, in a different folder than the ticket worktree, or a skill with its own entrypoint.
    - The note is a JSON stream line `{"type": "agenticos-note", "text": …}`. `project_runs.render_event` gains a branch that renders it for every format (claude, codex, dsh, text), so it shows both live and in replay (DP-19).
    - Writer (DP-32, DP-39):
      - Generic path: the dispatch worker appends that line to the run's durable stream log and publishes it (`_persist_and_publish`, ring + `run_event`) before launching the agent.
      - Project path: the note is passed into `_run_project_ticket(note=…)`. `project_runs.run_agent` writes it as the first line, right after it opens (truncates) the log, and publishes it. The project reader's `"w"` open therefore cannot erase it.
      - The run view gets the note live, and in replay from `/api/runs/<id>/events`.
    - It is also stored on the record as `session_note`.
- **No routing session (DP-28).** Today every generic dispatch first runs a routing CLI call (`_ai_command(backend, routing_prompt)`), which leaves a small headless session in the store.
  - A dispatch that continues a session skips routing and reuses its newest record's `selected_skill`.
  - A fresh dispatch still routes, but with `--no-session-persistence` (claude) or `--ephemeral` (codex exec). Both flags were checked in the installed CLIs' `--help` on 2026-10-16. The routing call therefore leaves no session.
  - Result: one card adds exactly one session to `claude --resume` / `codex resume`.
- **Scope of D3** (DP-21, DP-22):
  - Only canonical claude and codex. `_card_session` ignores other agents, and dsh dispatch always starts fresh.
  - A routed skill with its own entrypoint (`is_entrypoint`, launched as `run_skill.py <skill>`) keeps today's fresh launch, with the reason "skill has its own entrypoint".
- The prompt is unchanged (`IDENT: title\n\ndescription`): the agent sees the task again in the same conversation.
- See "The new invariant" above for what changes against Decision 11 and what does not.


### 5. Card replies (user report, 2026-10-16: "这个task 里面的quick reply没什么用啊？看一下怎么回事")
What the run log shows for the card AGE-105, which is bound to a Claude session:
- Reply 1 (`2a2be2ea`) was killed by the runner's fixed wall-clock cap: "Timed out after 1800s" (`AI_RUN_TIMEOUT_S`, app.py ≈L164). The session was still working, with background tasks pending, and producing output.
- Reply 2 (`fd322e96`) failed because Claude had hit its usage limit. The CLI's final result said "You've hit your session limit · resets 10:50pm", but the card shows only "resume of session 43734fe6… failed".
  - Cause: on a failed continuation, the error text comes from stderr only (app.py ≈L4097 session-card reply, ≈L4918 retry). The CLI's own error result (`is_error`, `result` / `api_error`) is ignored.
- The Terminal tab's "Quick reply" (`_cardTermQuickReply`, index.html ≈L4799) and the card's "Comment / Feedback" box both POST `/api/runs/<id>/retry` and continue the same session. The quick reply is a one-line duplicate without attachments or voice.

Decisions (Claude's defaults; the user can override):
- **D5 One reply box.** Remove the Terminal tab's quick-reply input and Send button, along with every reference to them (DP-41):
  - `_cardTermQuickReply`;
  - the `detail-term-reply` resets in `_cardTermBind`;
  - the disabled/placeholder logic in `_cardTermUse` and `_cardTermLoad`;
  - the `.detail-term-reply` CSS. The Comment / Feedback box is the card's single reply path. The Terminal tab keeps its live view, replay, Show in panel and Open interactive.
- **D6 The real failure reason.** When a continuation (session-card reply, retry, or D3 dispatch resume) fails, the record's `error` is the first available of:
  1. the agent's own error result: for Claude, the final `result` event with `is_error`, its `result` text and its `api_error`; for Codex, `turn.failed` / `error` events (already rendered by `render_event`);
  2. `_extract_real_errors(stderr)`;
  3. "resume of session … failed (exit N)".

  A usage limit then reads "You've hit your session limit · resets 10:50pm", not "resume … failed".
  - **Channel (DP-37).** The stream readers record the agent's error result in a per-run side channel, `_RUN_AGENT_ERRORS[run_id]`. Claude's reader (`_stream_claude_run`) sets it from the `result` event when `is_error`; the Codex reader from `turn.failed` / `error`. The caller pops the entry after the run. `run_agent_process`'s return tuple is unchanged, so no caller breaks.
  - The project path's `_parse_project_output` returns the agent's own error instead of stderr:
    - Claude: the `result` text when `is_error`;
    - Codex: the message of the last `turn.failed` or `error` event (DP-44).
  - It is used, before stderr, in `_retry_session_card_held`, the plain retry, the D3 dispatch resume, and `_run_project_ticket_locked`.
- **D7 No fixed 30-minute cap on session-card replies.** A reply to a session card (§3 of the session-to-board plan, and D3 resumes) runs under the stall detector (no output for `STALL_TIMEOUT_S` = 300 s → stalled), plus a 4-hour wall-clock ceiling (`AI_SESSION_TIMEOUT_S`, default 14400). Other runs keep `AI_RUN_TIMEOUT_S`.
  - The project helper gets a `timeout` parameter (default `AI_RUN_TIMEOUT_S`) on `_run_project_ticket` and `_run_project_ticket_locked`. The parameter is passed to `project_runs.run_agent` and used in its timeout record and message. Session-card replies and D3 resumes pass `AI_SESSION_TIMEOUT_S` on both the generic and the project path (DP-36).

Acceptance:
- [x] The card Terminal tab has no quick-reply box; Comment / Feedback replies still continue the same session — tests/test_session_titles.py::test_quick_reply_is_gone; the reply path is the retry route (D3 tests)
- [x] A continuation that fails on a Claude usage limit records the CLI's message (e.g. "You've hit your session limit · resets …") as `error`, and the card shows it — tests/test_session_titles.py::test_failed_card_resume_is_an_error_with_the_agents_reason
- [ ] A session-card reply that keeps producing output runs past 30 minutes; one silent for 300 s is ended as stalled; a reply past 4 h times out with "Timed out after 14400s"

Tests:
- [x] fake Claude CLI emitting an `is_error` result with `api_error: usage_limit_reached` → record `error` is that text, on the reply, retry and dispatch-resume paths — tests/test_session_titles.py::test_failed_card_resume_is_an_error_with_the_agents_reason (retry path), ::test_agent_error_of_claude_and_codex; one channel (`_publish_run_line` → AGENT_ERRORS) serves every run_agent_process path
- [ ] session-card reply timeout uses `AI_SESSION_TIMEOUT_S` (monkeypatched small) and other runs keep `AI_RUN_TIMEOUT_S`
- [ ] index.html has no occurrence at all of `detail-term-reply` or `_cardTermQuickReply` (static check); the card Terminal tab still opens and renders (browser check)
- [x] the agent's error result reaches the record on the worktree (project) path too — tests/test_session_titles.py::test_project_run_note_survives_and_codex_error_is_kept (run_agent captures it; the helper uses it as `error`)
- [ ] `AI_SESSION_TIMEOUT_S` applies on the project path, and its timeout message names it

## Assumptions (sources)
- The tab strip and its order key: `runner/templates/index.html` ≈L1114–1166, L1521–1585. The old vertical render is `git show 5f2c1ce^:runner/templates/index.html`, ≈L1105–1127 and L1489.
- Labels and card titles: `runner/app.py` `_board_sessions` ≈L3677–3696. Rows are built in `runner/projects.py` `_with_label` ≈L1422.
- Rename writes: `projects.rename_session` ≈L1707. It is idle-guarded by `_session_action` / `check_session_idle`, with `SESSION_FRESH_S = 120`.
- Dispatch is always fresh today: `runner/modules/linear/__init__.py` `_dispatch_issue_held` ≈L799–960, generic `_ai_command`, and project `_run_project_ticket` without `resume_session`.
  - Replies and retry continue via `_get_task_agent_lock` / `_build_resume_cmd` (app.py ≈L2667, L3370, L4724).
- Run log, 2026-10-16: 18 cards, 1 with more than one session. So D3 mostly changes behaviour after a reset to Todo, plus any later re-dispatch.
- Claude's resume picker shows the newest `custom-title`, and `rename_session` keeps mtime (FB-03). Codex's picker reads `threads.name` (R24-01).

## Risks
- **Concurrency.**
  - A native rename right after a run: the runner's own process has exited, so only another live process (VS Code, a terminal) could be writing, and the live set catches the terminal case.
  - An external VS Code session on the same id would not be in the live set. The mtime rule is waived only for `ended`, the session whose own runner process just exited. Accepted risk: VS Code writing the same session within seconds of a runner run.
- **Old cards.** Some sessions of old cards were never named and may be idle. They get named at their next trigger; there is no bulk backfill (non-goal).
- **Long conversations.** D3 makes a card's conversation grow across re-dispatches. Context limits are the agent CLI's concern (compaction).

## Non-goals
- Hiding or merging existing small sessions; bulk-renaming old sessions; a "start fresh session" switch; dsh sessions; changing the Terminal tab.

## Verification
- `.venv/bin/python -m pytest tests/ -q -p no:cacheprovider`: all pass.
- New `tests/test_session_titles.py` (fake Claude/Codex stores as in `tests/test_session_actions.py`):
  - labels for a running card session;
  - native rename after a run end (Claude custom-title appended, mtime kept; Codex `threads.name`);
  - title edit through both PATCH routes renames idle sessions and skips a live one;
  - card-row rename changes the tracker title first, and a failed tracker update changes nothing;
  - name text sanitizing;
  - `ended` (run or terminal) waives only the mtime rule for its own session, and another terminal or job on the same session still blocks the rename;
  - closing a card terminal right after a title edit renames the session;
  - in Linear mode, a failed Linear title update renames nothing, even though `/local/<id>` succeeded;
  - a card-row rename with a failed Linear update returns 502 and changes nothing (no cache, override or native rename);
  - a card-row rename with an invalid title (a control character, or more than 200 characters) returns 400 before any tracker write;
  - `_board_sessions` callers unchanged; `_card_sessions` includes running jobs and claims.
- New dispatch tests (`tests/test_project_dispatch.py` style, fake CLI):
  - re-dispatch after a drag to Todo resumes the same session for a generic card and for a project ticket;
  - a removed session, a missing folder or another agent starts a new session with the reason note;
  - a failed resume (non-zero exit) is an error record, not `review` and not a fresh session;
  - a running generic card's job carries its `agent_session_id` during the run (fake CLI init event), and its panel row shows the card label;
  - the `new session: <reason>` note is rendered by `render_event` for claude and codex streams, live and in replay;
  - an entrypoint skill and a dsh card still launch fresh, with the reason;
  - a cancelled or stalled card run renames its session; cancel → drag to Todo → dispatch resumes the same session (no "in use" refusal);
  - a title edit right after a run renames the native session at once;
  - an archived card's session row renames only the session;
  - Codex `threads.name` NULL with `threads.title` equal to the card title is still written;
  - in Linear mode, a failed title update does not rename at a later run end; a title + In Progress save renames once the async sync confirms;
  - a resumed generic dispatch launches the agent CLI once (no routing call); a fresh routing call carries `--no-session-persistence` / `--ephemeral`;
  - the `new session` note appears in `/api/runs/<id>/events` lines and as a live `run_event`;
  - a reply from a reset-to-Todo card continues the card session, both for a to-board card in a project main checkout (routed through `_retry_session_card_held`) and for a generic card;
  - a retry with a lock but no session id consults `_card_session`;
  - a failed card-session resume on a plain Retry is an `error`, never a fresh fallback;
  - an archived card's retry after a reset does not resume its session;
  - a Linear-mode card-row rename changes the native name, and leaves the description intact;
  - a project-ticket new-session note survives into replay;
  - a reset card's reply through `_retry_session_card_held(card_sourced=True)` is admitted and its record has no `resume_session`;
  - two consecutive replies after resetting a main-checkout session card both run in the main checkout: the second gets its session from the agent lock, and is still routed by folder;
  - an externally deleted issue with a current-generation agent lock: its retry returns 409 and nothing launches;
  - a plain generic Retry that starts a fresh session publishes the id while running; cancel after the announcement persists it, and the next dispatch continues it;
  - an older poll finishing after a confirmed rename does not change `_linear_titles`, and a later run-end sync keeps the newer name;
  - a delayed run-end sync that selected the old title, run after a newer title edit, leaves the native name at the newer title;
  - a stalled run whose process group is signalled but still alive: **no native write occurs** from any trigger, including a title edit, while the closing marker stands. Once every process in the group is gone, the marker clears and the sync renames;
  - a group whose leader was reaped but a descendant is still alive keeps the marker;
  - a reply with a valid persisted intent whose tracker issue is gone returns 409;
  - a fake Codex project run with `turn.failed` records the CLI message as `error`;
  - a terminal end on a brand-new to-board card before any poll never writes the preamble as the native name;
  - after a card-row rename, the team-filtered board payload shows the new title;
  - a live session, or a held `session_lock` at claim time, refuses with an error record, and the card goes to review, not stuck In Progress;
  - a project ticket with its bound worktree removed still fails closed;
  - a session open outside the dashboard (a fake `_process_table` entry whose argv contains the id) refuses the resume, and the card goes to review;
  - a confidential run with `_records_unsafe()` set has no `issue_title` (and no real title) in its record, on the dispatch, helper, reply and owner-record writers.
- Manual, isolated runner (`verify` skill) + browser:
  - vertical projects: open several, reorder by drag and Alt+↑/↓, reload keeps both;
  - edit a card title → the row changes without waiting for the poll, and the fake store's name changes;
  - open Rename on a card-bound row: the input shows the card title;
  - rename a card-bound row → the card title changes;
  - drag a finished card to Todo and dispatch → same session id in the run record.

## Progress Checklist
- [x] Plan reviewed (Codex, or DeepSeek when Codex has no usage) until approved — Codex round 4 APPROVED (cross_provider), plan sha256 6329d3bd…; DeepSeek third-party rounds 1–8 before it
- [x] User go-ahead to build (D4) — user, 2026-10-17: "claude build it, and codex review"
- [x] §1 vertical projects: render, open-state storage, drag and Alt+↑/↓ reorder, tab-strip code and CSS removed — commit 1f3e108
- [x] §2 `issue_title` on card records (withheld under the confidential and unsafe rule); running-job labels in `_board_sessions` (2-tuple kept); `_card_sessions()` from records, jobs and claims — tests/test_session_titles.py::test_issue_title_is_withheld_for_a_confidential_run_where_records_are_unsafe
- [x] §2 `projects.find_session` (store-confined, id-checked) with tests — tests/test_session_titles.py::test_find_session_gives_cwd_and_the_native_name_only
- [x] §2 `_sync_card_session_names` with the `ended` owner rule (run or terminal; only that owner excluded) — tests/test_session_titles.py::test_closing_marker_blocks_every_rename_until_the_group_is_gone, ::test_own_last_write_does_not_block_a_rename_right_after_a_run, ::test_title_edit_renames_idle_sessions_and_skips_a_live_one
- [x] §2 sync triggers: run end on all four launch paths, terminal finalize, the authoritative tracker's PATCH route on a confirmed title change — code in all paths (commit 1f3e108); tested: retry run end, local title PATCH
- [x] §3 card-bound session-row rename: own branch outside `_session_action`, strict `_set_card_title`, `pending` note in UI — tests/test_session_titles.py card-row tests; ::test_linear_title_update_is_title_only
- [x] §4 `_card_session` and dispatch continuation on the generic path, with claim, live admission (error record + review), strict failure and reason note — tests/test_session_titles.py::test_dispatch_refuses_a_session_open_elsewhere and the dispatch tests
- [x] §4 dispatch continuation on the project path, only in the bound worktree — tests/test_session_titles.py project dispatch tests
- [x] Rewrite the named `tests/test_reset_gen.py` tests to D3; keep `test_agent_change_honored_after_reset` and `test_reply_rules_agent_empty_and_reset` unchanged — done; both kept unchanged
- [x] New tests `tests/test_session_titles.py` and the dispatch tests pass — 30 passed
- [x] Full suite passes — 674 passed
- [ ] Manual isolated-runner + browser checks (Verification list) — BLOCKED: the Chrome extension is not connected, and headless Chrome refuses DevTools attach to pages ("Not allowed", likely a managed policy); isolated runner on :8599 served the page (HTTP 200). Needs the user's manual check
- [x] §5 D5 remove the Terminal tab quick reply (markup, handler, placeholder logic) — tests/test_session_titles.py::test_quick_reply_is_gone
- [x] §5 D6 continuation failures record the agent's own error result (reply, retry, dispatch resume) — see the D6 tests above
- [x] §5 D7 session-card replies and D3 resumes use the stall detector + `AI_SESSION_TIMEOUT_S` (4 h) — tests/test_session_titles.py::test_card_continuation_gets_the_session_timeout, ::test_project_dispatch_continues_the_session_in_its_worktree (timeout passed)
- [x] §5 tests pass — included in the 30
- [ ] Codex build inspection (fresh session) with no unresolved material findings
- [ ] Commit; restart the live runner when idle
