---
status: completed
created: 2026-10-16
completed: 2026-10-16
---

# Sessions go back to the board; terminals live on the card

## Goal
Resuming a session means putting it back on the job board: "Resume" puts the session's card in **Todo**, where the user writes the next reply and dispatches it. Continuing a session therefore goes through the same reply-and-dispatch flow as any other card.
- The bottom terminal panel is optional: it opens only when the user asks for it from the card.
- The project panel's "copy resume" and "Resume in tab" merge into one "Resume" button.
- Terminals: the card's existing Terminal tab already shows on every run card in every column and stays exactly as it is (user, 2026-10-16: "不要在旁边加 \"Open terminal\" 和 \"Copy command\" 两个按钮，现在就很好").

User request, 2026-10-16. Follow-up to `docs/exec-plans/active/2026-10-15-dashboard-ui-updates.md`. That plan is in its final inspection in another session, so this work has its own plan (user decision).

## Decisions (user, 2026-10-16)
- **Card placement.** If the session already has a card, that card moves back to Todo. If it has none (for example a session started in VS Code), a new Todo card is created and bound to it (agent, session id, project, the session's own folder). A card whose session is running or launching is not moved: the button reports that it is still running.
- **One button.** "Resume" puts the card in Todo and opens the card's detail view with the reply box focused. It does not open the bottom panel. The separate "copy resume" goes away; the card's existing "Open interactive" covers resuming in a terminal.
- **Session open elsewhere.** If the session is being used somewhere else, the card shows a warning, and sending a reply asks for one confirmation. It is not blocked.
- **Reviewer.** DeepSeek (`dsh`, read-only) reviews this plan, at the user's request: "需要仔细用deepseek审阅". This is a third-party review, recorded as such; it is not a cross-provider claudex approval. After the user reported Codex usage reset (2026-10-16), the claudex Codex plan review runs too (`SBR-` findings), under the same convergence standard.
- **In progress stays as it is (user, 2026-10-16):** "现在在 In progress 可以在tab里面打开terminal，这个功能很好，不用改。" Then (same day): "No，不要在旁边加 \"Open terminal\" 和 \"Copy command\" 两个按钮，现在就很好". The card Terminal tab is not changed at all by this plan: no new buttons in any column.
- **Convergence (user, 2026-10-16).** The user said: "定过一个收敛标准：只修高危，以及在 macOS单用户环境下真能复现的问题。要把这个标准也用到 plan". After round 12, plan review stops. Only high findings and findings reproducible on this macOS single-user setup are fixed; the rest are accepted risks, listed below.
- **Scope.** Plan and review only. Building needs a separate go-ahead; standing rule: "你先别动手改，全部都写入plan".

## Acceptance criteria
- [x] The project session row shows one **Resume** button instead of "copy resume" + "Resume in tab"; Rename/Remove stay — manual, isolated runner + Chrome 2026-10-16: row shows Resume/Rename/Remove
- [x] Resume on a session whose card is in Backlog, In review, Done or Error moves that card to Todo, keeping its history and attempts — tests/test_session_to_board.py::test_to_board_on_a_found_card…; manual, isolated runner + Chrome 2026-10-16: In Review card → Todo
  - [x] the card's tracker issue moves to Todo (Linear updated when configured), and the intent is bound to the new reset generation — tests/test_session_to_board.py::test_to_board_on_a_found_card… (gen 0→1), test_failed_move_restores…
- [x] Resume on a session with no card creates one tracker issue in Todo (as the "+" form does) with a linked run record bound to the session, titled with the session title, visible on the board — tests/test_session_to_board.py::test_to_board_without_a_card…; manual, isolated runner + Chrome 2026-10-16
- [x] Resume on a session that is running or launching (claimed) returns "still running" and changes nothing — tests/test_session_to_board.py::test_to_board_refuses_a_running_or_claimed…
- [x] After Resume the card detail opens with the reply box and send controls visible and the reply box focused; the bottom terminal panel does not open — manual, isolated runner + Chrome 2026-10-16: detail open, reply focused, terminal panel closed
- [x] Replying from Todo continues **the same session** (same agent, enforced, and session id), never a fresh session; a failed continuation is an error — tests/test_session_to_board.py::test_reply_continues…, test_intent_survives…(strict error); manual, isolated runner + Chrome 2026-10-16
- [x] A second and later reply on the same card (from Todo, In review, Done or Error) continues the same session in the same folder until a reset to Todo — tests/test_session_to_board.py::test_reply_continues… (from Done); manual, isolated runner + Chrome 2026-10-16: reply from a Done card
- [x] Open interactive on a resumed session card opens in the session's folder (or its ticket worktree when that is the session's folder) — tests/test_session_to_board.py::test_session_card_terminal_opens_in_the_session_folder
- [x] Choosing In Progress in the issue editor of a resumed Todo card opens the reply instead of dispatching — manual, isolated runner + Chrome 2026-10-16: saveLinearIssue sent no PATCH, reply focused
- [x] Local tracker identifiers are never reused after a delete or Empty trash — tests/test_session_to_board.py::test_empty_trash_local…, test_identifier_floor…
- [x] Session cards are claude/codex only; dsh sessions show no Resume button — tests/test_session_to_board.py::test_to_board_refuses_sessions_outside_the_project_and_dsh (dsh → 400); dsh sessions are not listed
- [x] Replies run under the project's policy — tests/test_session_to_board.py::test_confidential_reply_is_sandboxed_or_refused…; manual, isolated runner + Chrome 2026-10-16: alpha reply had sandbox --settings
  - [x] confidential projects use the sandboxed CLI from `project_runs.agent_cli` and refuse dsh — tests/test_session_to_board.py::test_confidential_reply…; dsh is not a session-card agent
  - [x] records withhold text where record locations are unsafe, and a confidential reply outside a ticket worktree refuses to launch when record locations are unsafe — tests/test_session_to_board.py::test_confidential_reply… (refused, reply text absent)
- [x] A card moved to Todo the existing way (drag or reset), including one that was resumed earlier, starts fresh: Decision 11 unchanged — tests/test_session_to_board.py::test_reply_rules_agent_empty_and_reset
- [x] When the session is in use elsewhere, the card shows a warning, and the first send (card reply or quick reply) asks for confirmation; with confirmation the reply is dispatched — tests/test_session_to_board.py::test_reply_asks_when…; manual, isolated runner + Chrome 2026-10-16: warning shown, one confirm, dispatched
  - [x] the card's own just-finished run never counts as "elsewhere" — tests/test_session_to_board.py::test_own_finished_run_is_not_elsewhere
- [x] The card Terminal tab is unchanged in every column (live view, replay, Show in panel, Open interactive); no new buttons — no Terminal-tab UI code changed (diff); backend folder fix tested
- [x] A project run that changed nothing shows no verify badge; a run with changes but no check command shows a grey "no check"; failures stay red — tests/test_session_to_board.py::test_badge_for_a_run_that_changed_nothing; tests/test_project_dispatch.py::test_question_only_run…; neutral .verify-badge.none
- [x] Claude run records and cards show the model the CLI reported (init event or `modelUsage`), and cost uses it — tests/test_session_to_board.py::test_observed_model_and_cost; manual, isolated runner + Chrome 2026-10-16: card shows CLAUDE-OPUS-5-5[1M]
- [x] A session launched from the board (headless claude/codex) appears under its project with its card identifier; other headless sessions stay hidden — tests/test_session_to_board.py::test_board_launched_headless…, test_codex_exec_threads…
- [x] Issues created for a non-confidential project go into its same-named Linear Project; confidential and unbound ones stay in the default Project; AGE ids unchanged — tests/test_session_to_board.py::test_linear_project_mapping, test_linear_session_issue…, test_dispatch_moves…
- [x] Empty trash archives every Canceled issue (Linear archive, local delete) after one confirmation; run records and transcripts stay; Resume on a session whose card was archived creates a new card — tests/test_session_to_board.py::test_empty_trash_local…, test_empty_trash_linear…, test_archived_issues_stay_out…; manual, isolated runner + Chrome 2026-10-16: one confirm, count 1→0
- [x] Projects panel is a tab strip; tabs drag to reorder, the order and the selected tab survive a reload, and new or removed projects are handled; Alt+Left/Right reorders by keyboard — manual, isolated runner + Chrome 2026-10-16: drag and Alt+←/→ reorder, reload keeps order and selection, added project appended
- [x] Full suite passes: `.venv/bin/python -m pytest tests/ -q -p no:cacheprovider` — 629 passed

## Approach

### 0. What a board card is
`refreshJobBoard` builds the columns only from tracker issues (`/api/linear/issues`): Linear when configured, the local tracker otherwise. Each card's column comes from the issue state, and its `run_id` is the issue's **latest** run (`index.html` ≈L2682–2730). A run record with no `linear_issue_id` is never shown (STB-012). So "the session's card" means a tracker issue, and moving it means moving the issue.

### 1. A card can carry "resume this session" (generation-bound)
- Today a card's continuation comes from `_get_task_agent_lock`. Its lock clears when the latest record is `todo`/`rework`, so a Todo card starts fresh (Decision 11).
- Every move back to Todo bumps the issue's reset generation:
  - the tracker PATCH route through `_tracker_reset_route`;
  - `api_run_set_status` for `todo`/`rework`.
- A new optional field `resume_session: {"agent", "id", "project_key", "gen"}` is written **only** by the to-board route (§2).
  - `gen` is the reset generation that the route's own move to Todo produced.
  - `cwd` is not stored as authority: it is re-resolved server-side at every use.
- `api_run_retry` honours it only when **both** hold:
  1. it is on the issue's **latest** run record. "Latest" is one server-side predicate, `_intent_latest(issue)`: the newest record of the issue, skipping `interactive_ended` audits **and** `archived` records (STB-065/077). The intent check and the board payload's `resume_ok` both use it, and the board receives `resume_ok` precomputed rather than deriving it in JS. Opening and closing the card's tab therefore never voids the intent;
  2. `gen == reset_gen.current(issue)`.
- Any later drag or reset to Todo bumps the generation, so the intent becomes void without anyone having to clear it. `api_run_set_status` for `todo`/`rework` also drops the field when it copies `{**original}` (STB-004); its other statuses and `api_run_restore` keep it, and it is still checked against the generation at every use.
- **Not consumed by a reply (SBR-001).** The intent is the card's session routing until the next reset, not only for the first reply. Every continuation record, on both routes of §3.3, copies the same `resume_session` (same `gen`). A second reply, from Todo, In review, Done or Error, therefore takes §3 again: same session, same folder, same policy. Without this, a later reply would reach the old `bound` block (its inline `project_key` and `issue_identifier`) and call `_run_project_ticket(reuse_only=True)`, which fails for a new card and runs a bound ticket's main-checkout session in the worktree.
- With the intent: strict continuation (no fresh fallback, failure → `error`, as C2's quick reply). Without it: today's behaviour.

### 2. `POST /api/projects/<key>/sessions/<agent>/<sid>/to-board`
1. **Resolve the session** with `projects.session_target(project, agent, sid, board_ids=<computed in app.py as in §9>)`, so board-launched headless sessions resolve (STB-070).
   - This gives an id format check, a project-root check and the cwd from the transcript.
   - Any client-sent cwd is ignored.
   - Outside the project → 404.
   - **Title (STB-069).** `session_target` also returns the session's `title`, using the same derivation as its listing row: `_claude_summary` custom, ai or first title; the codex thread name or first message. A title or description sent by the client is ignored.
   - Only claude and codex sessions exist there. dsh sessions are out of scope, and the Resume button is not shown for them (STB-014).
2. **Lock, then check (STB-027).** Take `projects.session_lock(agent, sid)` non-blocking first (busy → 409); everything below runs inside it. Running check (STB-008), 409 `{"error": "still running"}` if any holds:
   - `(agent, sid)` is in `_live_session_ids()` (claims included, so the launch window is covered);
   - a job in `_running_jobs` has this session;
   - the issue's latest run is `running`, or the issue is reserved or running per `_issue_is_running`/`card_locked`. This third check is evaluated **after** step 3 has resolved the card, still inside the lock and before any move or append (STB-057). A card with an in-flight run on another session, or a launch not yet claimed, → 409. For a found card, the route then **enters and holds `reserve_card(issue)`** (the same ticket/card lock a drag to In Progress takes) across the bump, move and append, and releases it at the end (STB-071). A concurrent dispatch is excluded by the real lock, not by the `card_locked` probe.
3. **Find the card.** Take the newest run record with `agent_session_id == sid`, the same raw agent and a `linear_issue_id`, skipping `interactive_ended` and `archived` records (as `_get_task_agent_lock` does, STB-017). Its `linear_issue_id` is the card, **only if** that issue is in the live issue cache (`issues_cache` / the local tracker) and not archived. An issue that is gone or archived counts as no card (§11, STB-029).
4. **Found.**
   - Under `reset_gen.issue_lock(issue)`: call `reset_gen.bump(issue)` explicitly (STB-068: the in-process move has no PATCH body for `_tracker_reset_route` to see), then move the issue to Todo the way a board drag does (state push included, STB-009). If the move or the push fails, call `reset_gen.restore(issue, previous, bumped)`. **Only after the move is confirmed** (state committed, push accepted) are the record and its `gen` written, with `gen` read as `reset_gen.current(issue)` **after** the move (STB-043). A failed move or push returns 409 with nothing appended, and a restored generation never leaves a stale intent. Then append one `todo` record on the issue's **latest** `run_id` (the run the board shows, STB-016). The record is `{**latest_record, "status": "todo", "agent_session_id": sid, "agent": <session agent>, "issue_identifier": <durable binding's identifier, else the issue's tracker identifier>, "resume_session": …, "reset_gen": <bumped>, "to_board": true}`. `issue_identifier` is always set (STB-066), so `open_terminal` takes the same ticket lock as `reserve_card`. `agent_session_id` is set to the resumed session (STB-046), so the latest record and the intent name the same session even when the card's last run was a different one. The existing strict guard (`original["agent_session_id"] != _lock_session_id`, app.py ≈L4170) therefore passes, and intent continuations are always strict. The other copied fields are so `agent_session_id`, `task_id`, binding, `source`, prompt, output and pinned message are all kept. The detail and Terminal views (which read the newest record of that `run_id`) look exactly as before (STB-035). `to_board: true` marks it as no real attempt (§4.3). If the binding is confidential (or unknown) and `_records_unsafe()` is non-None, the copied prompt, output and pinned text go through the same withholding helper as §3.5, so no confidential text is duplicated where records may leak (STB-042).
   - Return that `run_id`.
5. **None.**
   - Create a tracker issue **synchronously**, then write the record against the id the board lists (STB-021):
     - **Same composition as the "+" path (STB-040/045):**
       - labels = `_project_labels` → `['project:<key>']`;
       - description = `_compose_issue_description(desc, agent)`, so the session's agent marker sets the card's `preferred_agent` (a later fresh dispatch then keeps that agent and project). `desc` is defined per binding (STB-047):
         - **public project:** the session title;
         - **confidential or unknown:** empty, so only the agent marker is sent and no session text reaches the tracker;
       - the local tracker also gets `preferred_agent=agent`.
     - **Linear configured:** call `LinearClient.create_issue` directly, not the local-first `_issues_post`, so no `local-…` placeholder or alias swap is involved.
       - Label ids come from `ensure_label(team_id, 'project:<key>')` first. A label that cannot be resolved → 409, nothing created (STB-041), as `_bg_sync_to_linear` does.
       - The issue gets the Todo state and the §10 Project. A Linear error → 409 with the reason, nothing written.
     - **Local tracker:** create through the local tracker's create function (ids are final immediately).
     - Either way, the normalized issue is then written into `issues_cache` and `_issues_by_team`, and `linear_issues_updated` is emitted, as `_issues_post` does (STB-031). The board's immediate refresh therefore shows it without waiting for the 30 s poll.
   - **Title (STB-025).** For a public project, the issue title is the session title. For a confidential project (binding confidential or unknown), the title sent to the tracker is a neutral `Session <first 8 chars of the id>`. The `+` path has no confidential title handling to rely on.
   - Then append a run record linked to it, carrying:
     - `run_id` = `task_id` = new uuid;
     - `linear_issue_id`, and `issue_identifier` = the created issue's identifier (STB-058). An interactive tab, a reply and a drag on this card then all take the same `ticket_lock(project_key, identifier)` (`open_terminal` uses the record's `issue_identifier`). Routing (§3.3) still uses only the durable binding;
     - `status: "todo"`, `skill: "_prompt"`, `agent`, `agent_session_id: sid`;
     - `resume_session` (with the issue's current `gen`);
     - the project binding (`project_key`, `confidential`);
     - `source: "session"`.
   - **Confidential project with `_records_unsafe()`:** the record's prompt is the withheld marker.
   - Return the `run_id`.
6. **Writes (STB-084).** Both the found-card and the new-card record are written through `_write_run_log(..., audit=True)`, which invalidates the 3 s `_runs_cache` and keeps task/job state clean. `GET /api/runs/<id>` also carries the precomputed `resume_ok`, so the detail opened right after Resume shows the reply controls without waiting for a board refresh.
7. Because the lock is held from step 2 to the end, two clicks cannot create two cards, and a retry cannot claim the session between the running check and the write.

### 3. Dispatching a reply from a session card
`api_run_retry` with a valid intent (§1) on the latest record:

1. **Agent.** It is forced to `resume_session.agent`. A different `agent` in the body → 409. In the UI, the agent buttons for such a card show only that agent (STB-015).
2. **Checks, before `_claim_session` (STB-005).**
   - Re-resolve `session_target(..., board_ids=...)` (STB-070) (gone or outside → 409, nothing recorded).
   - Run the in-use check (§4) unless `confirm_in_use: true` → 409 `{"in_use_elsewhere": reason}`.
   - **Session id (STB-055).** A valid intent sets `_lock_session_id = resume_session["id"]`, the forced agent and **`strict = True`**, server-side and regardless of the request body (STB-060), **before** the strict guard and `_claim_session`. It bypasses `_get_task_agent_lock`, which returns None for the to-board `todo` record. The strict guard then sees the id, and the attempt builds the resume command, never a fresh `_ai_command`.
   - Then claim as today.
3. **Route, preserving project guarantees (STB-001/007).**
   - **This replaces the existing `bound`/`_run_project_ticket` block in `api_run_retry`** for cards with a valid intent (STB-038). The old block treats any record with `project_key` as bound and calls the helper with an empty `ident`. The decision is now made on the resolved session cwd:
   - **Project ticket in its own worktree.** The **durable** binding (`_durable_binding`, not an inline `project_key`) has an `issue_identifier`, and `projects.worktree_path(project, ident)` resolves to the session cwd → `_run_project_ticket(..., ident=<that identifier>, resume_session=sid, reuse_only=True)`. This keeps the sandbox, commit, verify, binding, the tracker rules and its own `_records_unsafe` refusal.
   - **Locks (STB-051).** Locking is decided independently of routing and of any inline `project_key`:
     - the intent reply takes the **same primitive the board dispatch uses**, `reserve_card` (linear module). It chooses the ticket lock or the card lock from the binding and the `project:<key>` label, exactly as a drag to In Progress does. The reply and a concurrent drag therefore always contend for the same lock (STB-054). A card with no tracker issue cannot occur (§0). The `reserve_card` hold is **handed on**, never re-acquired (STB-079):
       - to `_run_project_ticket(..., ticket_hold=held.pop_all())` on the worktree branch, as the existing bound path and `_dispatch_issue_held` do (`ticket_lock` is non-reentrant across fds);
       - to the generic worker as its lifecycle hold, released when the record is written;
     - the generic path additionally holds `project_lock(project_key)` across launch and record, like `_run_project_ticket`.
   - **Any other session card** (main checkout, another folder under the project roots, or a card whose binding is only an inline `project_key`). The project comes from the record's `project_key` through the registry; the card never reaches `_run_project_ticket`:
     - **Project floor (STB-078):** the project is the record's binding when present, else `resume_session.project_key`, always set by to-board because it runs under a project route. A session card always has a registered project. Its confidentiality is `project.confidential OR binding confidential is not False`.
     - **Effective confidentiality (STB-032):** as in `_run_project_ticket_locked`, any binding whose `confidential` is not `False` (true or unknown, via `_ticket_confidential`) makes the effective project confidential (`dataclasses.replace(project, confidential=True)`) **before** `agent_cli` is called and before the refusal below.
     - **Confidential and unsafe:** if the effective binding is confidential and `_records_unsafe()` is non-None, refuse before launch with the same error the project path raises (STB-013). Nothing is launched, nothing is streamed, an error record is written withheld.
     - Otherwise run `run_agent_process(new_run_id, cmd, stream=agent, cwd=target["cwd"], env=...)` (C0, STB-011).
     - `cmd` is the resume argv built on `project_runs.agent_cli(agent, project, ...)` with `_project_cmd`'s resume flags (claude `--resume <id>`, codex `resume <id>`). A confidential project therefore gets the sandboxed CLI.
     - The runner does **not** commit or verify in that folder: it is the user's own session in their own checkout, like an interactive resume tab.
4. **Tracker comments (STB-052).** On the generic path every automatic comment goes through `project_runs.tracker_comment(binding, kind, …)` with the effective binding: the feedback, run, timeout and error comments. That function returns the template, or nothing, for a non-False (confidential or unknown) binding. The raw `_linear_comment_body(...)` posts of the plain retry block are not used for intent cards, so no reply or agent output text reaches the tracker for a confidential session.
5. **Prompt.** Only the reply plus the attachment note. It does not include the "Original task / Previous output" wrapper.
6. **Records (STB-002, STB-018).**
   - Normal, timeout and error records go through one helper that applies `_records_unsafe()` withholding for confidential bindings.
   - **Cancel and stall (SBR-005).** Those records are written by `_write_owner_record` from `job["record"]` (app.py ≈L3069), not by the worker. On the generic path, `_running_jobs[run_id]["record"]` therefore carries every field a continuation record needs: `resume_session`, `agent_session_id`, `linear_issue_id`, `issue_identifier`, `project_key`, `confidential` and `source`. `_write_owner_record` applies the same withholding helper, so a confidential prompt is withheld where records are unsafe. The binding sits **only** inside `job["record"]`, never as the job's top-level `project_key`: cancel (app.py ≈L4034) and the stall pass (`stall_detection` ≈L67) treat a top-level `project_key` as a worktree project run and call `_signal_project_run`. A generic session job uses the `run_agent_process` cancel and kill path. A cancelled or stalled reply therefore leaves a latest record that still routes the next reply through §3.
7. **Shutdown (SBR-009).** `_stop_project_runs` (app.py ≈L2955) selects jobs by top-level `project_key`, and its `projects.stop_all()` kills only processes started through `projects.spawn`. A `run_agent_process` job (own session, `_running_procs`) is neither, so on SIGTERM its agent outlives the runner, and after a restart the session claim is gone while the agent still writes. This gap exists today for every generic run; the session reply makes a second writer on one session likely. Fix, for **every** `run_agent_process` job, not only session replies:
   - `run_agent_process` refuses to start once `_SHUTTING_DOWN` is set, through the same `_register_proc` handshake (the new process is killed and reaped; the run records `error: shutting down`);
   - **Shutdown owns the record (SBR-010).** Generic workers never read `job["cancelled"]`; only the party that pops the job owns its record. So the generic branch of `api_run_cancel` (app.py ≈L4039–4062: pop job and proc under `_JOB_LOCK`, SIGTERM then SIGKILL the group with reaping, `_write_owner_record`) becomes one helper, `_cancel_generic(run_id, error)`, used by the cancel route and by shutdown. `_stop_project_runs` calls it, next to `projects.stop_all()`, for every job without a top-level `project_key`, with `error="Cancelled: dashboard shutting down"`. The displaced worker then finds its job gone (`_RunClaim` → not owner) and writes nothing. The record is written synchronously before the helper returns, so shutdown does not rely on the job disappearing;
   - **Already finalizing.** A worker that won `_end_job` first is still writing. `_RunClaim` adds its run_id to a `_finalizing` set when it takes ownership and removes it after the record write (in a `finally`). The 10 s shutdown wait covers that set as well as the project jobs;
   - cancel and stall classification is unchanged (top-level `project_key` only).
   - Each record carries `agent_session_id: sid`, `linear_issue_id`, `issue_identifier` (the card's tracker identifier, STB-061: so `open_terminal` keeps taking the same ticket lock as the reply and a drag), the binding and `source: "session"`. It also carries the unchanged `resume_session` (SBR-001), so the next reply routes the same way until a reset bumps the generation. The worktree route passes it through a new `_run_project_ticket(..., record_extra=...)` parameter that is merged into every record it writes.

### 4. In use elsewhere
`session_in_use(target, own_run_id, own_finished_at) -> str | None` returns a reason, or None. It checks:
1. **Live ids.** `_live_session_ids()` with this run's own claim excluded **by its run_id key**, so a second claimant of the same session still counts (STB-019).
2. **Process argv.** Any process whose argv contains the session id, from `ps -A -o pid=,ppid=,args=`. The runner's own process tree (the runner pid and its descendants via ppid) is skipped (STB-019).
3. **Recent writes.** `own_finished_at` is the later of two times: the end (`started_at + duration_s`) of the card's last **real attempt** (newest record with a run status, excluding `to_board` records and `interactive_ended` audits, STB-026), and the time of the card's newest `interactive_ended` audit, because the card's own just-closed interactive tab is the card's activity (STB-037). The transcript/rollout was written in the last `SESSION_FRESH_S`, **but only if written after the card's latest run ended plus 5 s**. The card's own just-finished run therefore never counts (STB-006).

Where it is used:
- `GET /api/runs/<id>` includes `in_use_elsewhere` for session cards.
- Retry checks it as in §3.2.
- In the UI, both the card reply (`retryRun`) and the quick reply (`_cardTermQuickReply`) handle 409 `{in_use_elsewhere}` the same way: one `confirm()` with the reason, then a resend with `confirm_in_use: true`.

### 5. Reply UI for session cards (Terminal tab unchanged)
- **Reply UI.** In `openDetailModal`:
  - the card is an issue card, so `#detail-reply-section` already shows (it shows for `linear_issue_id`);
  - `canRetry` additionally allows the `todo` state when the latest run carries a valid intent (§1), exposed in the run payload as `resume_ok`;
  - sending calls `retryRun` with the reply;
  - `resume_ok` and the intent agent are carried in the board payload too (`/api/runs` and `/api/runs/latest-by-issue`). While they hold:
    - **every** board control that would dispatch the Todo card opens the card detail with the reply box focused instead of calling `triggerLinearIssueWithAgent`. This covers the inline `▶ <agent>` button (`todoAgentToggle`, STB-053) and the `agent-badge` click (`agentBadgeClick`, STB-056);
    - `_buildCard` renders **no** `↺` retry group while `resume_ok` holds; the reply box is the only send path, so an empty strict resume is never issued (STB-083, supersedes STB-059);
    - a drop onto **In Progress** opens the card detail with the reply focused instead of PATCHing the state, so it does not dispatch (STB-062). Drops onto other columns still work, and a drop back into Todo voids the intent through the generation bump, as any drag does;
  - while `resume_ok` holds, `#detail-dispatch-group` (fresh dispatch into In Progress) is hidden, so a resumed session card offers only the continuation (STB-036). A drag or reset voids the intent and brings the dispatch buttons back;
  - `resumeFromProject` tolerates a missing `_boardItemsByRunId[run_id]` (opening the detail by `run_id` directly) (STB-031);
  - after a continuation the reply UI stays, because later records keep `linear_issue_id` and `source` (STB-018).
  - **Issue editor (SBR-003).** `saveLinearIssue` PATCHes the selected state directly, so choosing In Progress in the editor would dispatch a fresh run. While `resume_ok` holds, a save whose state is a started state does not PATCH; it opens the reply focused, as the In Progress drop does. Other fields and other states save as today.
  - **Metadata-only saves (SBR-006).** `saveLinearIssue` sends `state_name` on every save, and `_tracker_reset_route` bumps the generation whenever `state_name` is Todo. Saving only the title of a resumed Todo card would therefore void its intent. The save sends `state_name` only when the state changed (`stateChanged` is already computed there), for every card. An explicit move to Todo still bumps.
  - **Reply controls in every state (SBR-008).** `canRetry` (index.html ≈L3034) excludes `done` and `todo`. While `resume_ok` holds and the latest run is not running, it is true in every state, Done included, and the retry group shows only the intent agent. So the main reply box can send a later reply from Done as §1 promises.
- **Terminal tab: no UI change.**
  - It already shows on every run card in every column (`openDetailModal` hides it only for `linear-*` cards with no run).
  - Its live view, replay, Show in panel and Open interactive stay as they are (user decision).
  - **Backend for session cards (SBR-002).** `open_terminal` (`runner/modules/pty/__init__.py` ≈L350–381) treats a record's `project_key` + `issue_identifier` as a worktree binding: it calls `projects.load_binding` and opens in the ticket worktree. A to-board card has those fields without a worktree, so Open interactive would fail, and a bound ticket's main-checkout session would open in the wrong folder. For a record with a valid intent (§1):
    - the tab still takes `ticket_lock(project_key, issue_identifier)` (the lock file needs no binding), so it contends with reply and drag as before;
    - only when a durable binding exists and its worktree equals the session cwd does it take today's worktree path (`load_binding`, `_effective_project`);
    - otherwise the cwd is the session's folder from `session_target(..., board_ids=...)`, re-resolved server-side, and the project's confidentiality is the §3.3 effective one. A client cwd is ignored.
    - **Independent of the intent (SBR-007).** This folder choice depends only on the record's `agent_session_id`, binding and session cwd, never on whether the intent is still valid. A card reset to Todo afterwards, and an older attempt opened from history, therefore still open in the session's folder. The generation check governs only headless continuation (§1).
  - No Open terminal and no Copy command are added (STB-020 N/A). The project row's "Open terminal" stays where it is.

### 6. Project session row
- "copy resume" + "Resume in tab" → one **Resume** button.
  - It calls `to-board`, then `refreshJobBoard()` and `openDetailModal(run_id)`, and focuses `#detail-reply-input`.
  - On 409 it shows the reason inline in the row (no `alert`).
- `openResumeTab` stays for the card's "Open interactive" (C2).

### 7. No "verify: no check" on runs that changed nothing
- **Problem.** The user asked (2026-10-16, screenshot of a Done card "牛熊判断", project Trading): "这个verfiy: no check是什么？这种询问的task不需要verify吧".
  - `project_runs` sets `verify_badge = "no check"` whenever the project has no `verify` command (`runner/project_runs.py:527`).
  - The board paints every badge other than `pass` red (`runner/templates/index.html:2470`).
  - So a question-only run looks failed.
- **Fix.**
  1. If **this run** changed nothing, no badge is set unless the badge is red (STB-048): `verify: pass` and the soft badges are suppressed too. The worktree HEAD is captured just before the agent starts (`run_start_sha`), and "nothing changed" means all of the following (STB-022):
     - `run_start_sha..HEAD` is empty;
     - the agent left nothing uncommitted: the uncommitted set captured **before** verify runs, so verify's own artifacts never make the run count as changed (STB-081);
     - no seed was committed **in this run** (`committed_seeds` over `run_start_sha..HEAD` for this check, STB-033).
     - **Order (STB-039).** The red states are evaluated first and always win: verify `fail`/`error`, `main checkout changed`/`unchecked`, a seed committed in this run, and `post_run_error`. The changed-nothing rule only suppresses the run-owned soft badges (`no check`, `uncommitted changes`). An earlier attempt's seed commit or the ticket's earlier commits therefore never put a badge on a question-only run, while a real failure still shows. `base_sha` stays only for the verify accounting, because a ticket with earlier commits always has a non-empty `base_sha..HEAD`.
  2. A run that did change files but has no check command keeps "no check", styled neutral (grey, new `.verify-badge.none`).
  3. Red (STB-076): verify `fail` and `timeout` (from `run_verify`), `post_run_error` → `error`, `main checkout changed`/`unchecked`, and a seed committed in this run. Neutral: `no check`. Hidden when nothing changed: `pass`, `no check`, `uncommitted changes`.
- The order of the other badges (seed, main checkout, error, uncommitted) is unchanged.

### 8. Record the Claude model that actually ran
- **Problem.** The user asked (2026-10-16): "claude model怎么是 sonnet-4-6,提高到opus5.5".
  - The runner never passes `--model`, so Claude runs with the user's global setting (`~/.claude/settings.json` `"model": "opus[1m]"`). The AGE-102 stream log's init event says `claude-opus-5-5[1m]`.
  - The records and cards still show `claude-sonnet-4-6`, because `_agent_model()` falls back to that hard-coded name (`runner/app.py:2376`) when the result carries no model.
  - Token cost is then priced as Sonnet.
- **Fix (user: "有第一条就够了吧" — only this item).** Record the observed model:
  - **Every Claude path is stream-json** (`_agent_output_format` returns `stream-json` for claude); the `_parse_agent_output` claude branch is dead and is not touched (STB-023). The observed model is the `system`/`init` event's `model`, or else the first key of the `result` event's `modelUsage` (AGE-102's result has `model: null`, but `modelUsage` names `claude-opus-5-5[1m]`). It is read in:
    - `_stream_claude_run` (dashboard, retry and Linear runs through `run_agent_process`);
    - `_parse_project_output` (project runs such as AGE-102, which today reads only `result.model`).
  - **Price lookup (STB-024).** `_compute_token_cost` normalizes the name before its `MODEL_PRICES` lookup:
    - it strips a `[…]` context suffix such as `[1m]`;
    - there is **no** generic prefix fallback (STB-049): a longer id such as `gpt-5.4-mini` must not silently match a shorter key such as `gpt-5.4`. An id that is still unknown after stripping keeps today's `DEFAULT_PRICE`.
    - `MODEL_PRICES` gains an entry for the Opus 5.5 id, with its rate taken from Anthropic's current pricing page at build time, not from memory.
  - **Cost on every path (STB-034).** `_run_project_ticket_locked` and Linear `_dispatch_issue` call `_compute_token_cost(output_tokens, input_tokens, observed_model)` and write `token_cost_usd`, as `/run` and retry already do.
- No `--model` pin; the hard-coded fallback stays (user decision).

### 9. Board-launched sessions appear under their project
- **Problem.** The user (2026-10-16, screenshot): "我打开了一个AGE-102,按理来讲应该在Trading project下面看到这个新的session，但是没有。这个需要同步一下".
  - The AGE-102 run's transcript exists: `~/.claude/projects/-Users-yanghu--agentic-os-worktrees-Trading-AGE-102/8c3c2d86….jsonl`, cwd `~/.agentic-os/worktrees/Trading/AGE-102`, `entrypoint: sdk-cli`.
  - `claude_sessions` drops every `sdk-*` session (`runner/projects.py:1438`), and `session_target` does too (≈L1630).
  - `codex_sessions` keeps only `source IN ('cli','vscode')`, which drops `exec`.
  - Board runs are headless (`claude -p`, `codex exec`), so none of them ever show.
- **Fix.**
  - A headless session is listed, and resolvable by `session_target`, when its id is the `agent_session_id` of a runner run record.
    - The id set comes from `RUN_LOG` (cached by file stat as the other readers do), plus the live ids of running jobs and session claims. A run that is still going is listed too (STB-028).
    - **Carrier (STB-067).** `projects.py` cannot read app state, so app.py builds two values and passes them into `project_sessions(project, board_ids=..., labels=...)` / `session_target(project, agent, sid, board_ids=...)`. The callers are `api_projects`, `_session_action`, to-board and retry.
      - `board_ids` is a **normalized set of `(agent, sid)` pairs** (STB-086): run-log `(agent, agent_session_id)`, `_live_session_ids()` and running-job sessions, all in that one shape. Membership is `(agent, sid) in board_ids`.
      - `labels` is a **session → identifier map** (STB-080): `{(agent, sid): identifier}`, built from the run log's `agent_session_id` with its record's `issue_identifier`, or with `linear_issue_id` looked up in `issues_cache`.
    - Other sdk/exec sessions (other tools) stay hidden.
  - Such a row shows the card's identifier before the title (e.g. `AGE-102 · 牛熊判断`), so the user sees where it came from. Source (STB-063): `api_projects` builds a `linear_issue_id → identifier` map from the linear module's `issues_cache` (plus the record's own `issue_identifier` when present) and passes it into `project_sessions(project, labels=...)`. `projects.py` never imports `app`.
  - Its Resume button (§6) finds that card (§2.3) instead of creating a new one.
  - The confidential and root checks are unchanged: only sessions whose cwd is under the project roots are listed.

### 10. Linear Projects follow the registered projects
- **Decision.** The user asked (2026-10-16): "AGE这些tag什么意思，应该把Linear那边的tag改掉，跟project同步吧？". They then chose: "编号不动，Linear 里用 Project 分组".
  - `AGE` is the Linear team key; every issue in the one configured team (`tracker.team_id`) is `AGE-n`.
  - Today issues are created with **no** Linear Project: `create_issue` sends only `teamId/title/description/stateId/labelIds`. `project_slug` only scopes fetching when no `team_id` is set, plus the state lookup. Fetching here is by `team_id`, so issues in any Project of the team stay visible. §10 requires `team_id` to be set, and says so in its config check.
- **Fix.**
  - **LinearClient contract (STB-072/074).** New calls use `_graphql_strict`, which raises `LinearError(reason)` on transport errors, GraphQL errors and RATELIMITED, unlike `_graphql`, which returns `{}`. They return a typed value or raise. Routes turn `LinearError` into 409 with the reason; Empty trash collects per-issue failures and reports them.
  - **LinearClient changes (STB-030):**
    - `create_issue(..., project_id=None)` adds `projectId` to the create mutation;
    - new `find_project(name, team_id)`: a team-scoped `projects` query with name equality, excluding archived;
    - new `create_project(name, team_id)`: `projectCreate` with `teamIds`;
    - new `set_issue_project(issue_id, project_id)`: `issueUpdate`;
    - new `find_project_by_slug(slug) -> id` (cached), which resolves `tracker.project_slug`;
    - new `archive_issue(issue_id)` (§11);
    - the new `create_issue(project_id=…)` variant raises on failure instead of returning None.
  - Each registered **non-confidential** project has a same-named Linear Project in that team, found by name and created when missing. The id is cached in the runner state.
  - Issues created for a project go into its Linear Project: the "+" form with a project and §2.5 pass `project_id` on create. Linear dispatch of a `project:<key>` ticket that has no Project calls `set_issue_project`.
  - Unbound tasks and confidential projects go into the **default** Project. `tracker.project_slug` is resolved once to its project id (`find_project_by_slug`, cached), and that id is passed as `project_id` on every unbound or confidential create (STB-064). The `+` path, §2.5 and `_bg_sync_to_linear` all pass it. No Linear Project is created for a confidential project.
  - The `project:<key>` label is applied as in part B for every project, confidential ones included. Linear is the user's own private workspace, and the public-repo rule covers the git repo, not the tracker. This plan does not change that labelling (STB-044 corrects an earlier overstatement).
  - Identifiers (`AGE-n`), worktree paths and existing bindings do not change. Existing issues are not moved.
  - The local tracker (no Linear) is unaffected.

### 11. Empty the trash
- **Decision.** The user asked (2026-10-16): "垃圾站里面的 canceled 其实都可以清理 … 在这里删了也没关系".
  - The 🗑 chip lists board items whose issue state is Canceled (88 today).
  - Agent transcripts (`~/.claude/projects`, `~/.codex`) and run records (`state/run_log.jsonl`) do not depend on the issue, so sessions stay resumable.
- **Fix.**
  - The trash panel gets **Empty trash**, with one `confirm()` showing the count.
  - **Local tracker (STB-073).** The board fetch returns only active states, so Empty trash reads Canceled tasks from the local tracker directly (`LocalTracker` raw tasks), and the 🗑 count for local mode comes from that read too.
  - It archives each Canceled issue. In Linear this uses a new `LinearClient.archive_issue` (`issueArchive` mutation): recoverable from Linear's archive, never a hard delete. In the local tracker the issue is removed.
  - **Local identifiers are never reused (SBR-004).** `LocalTracker._next_identifier` derives `LOC-n` from the remaining tasks only, so after a delete the next task can get a removed task's identifier, and with it the old `ticket:<key>/LOC-n` binding, branch and worktree. Fix:
    - a persisted high-water mark (`state/local_tracker_meta.json`, `{"loc_max": n}`) read and written inside the same `_tasks_txn` lock;
    - `_next_identifier` returns `max(tasks, loc_max) + 1` and raises `loc_max`;
    - `delete_issue` (Empty trash and any other delete) raises `loc_max` to at least the deleted identifier;
    - when the file is missing, `loc_max` starts from the highest `LOC-n` among the tasks, the run log's `issue_identifier` values and the ticket directories under `WORKTREE_ROOT`.
  - **Poll filter (STB-050).** The poller drops `archived_ids` while building `new_cache` (before `issues_cache.update` and `_sync_cache_to_local`), not only in its carry-over. The `issues` queries keep Linear's default of excluding archived issues: observed on 2026-10-16, a poll after archiving 92 issues returned none of them.
  - **Eviction (STB-029).** Each archived id is removed from every place the poller and the board read: `issues_cache`, `_issues_by_team`, `_local_overrides`, the local tracker's `tasks.json` mirror and any dismissed set, before `linear_issues_updated` is emitted. Otherwise the poller's terminal-issue carry-over and `_sync_cache_to_local` would bring it back.
    - The id also goes into a persisted `archived_ids` set that the poller's carry-over skips, so a restart (which pre-fills the cache from `tasks.json`) does not resurrect it.
  - Run records and transcripts are not touched.
  - Afterwards a §2.3 card lookup that lands on an archived or missing issue counts as "no card", so Resume creates a new one.
  - Issues of other states are never touched.

### 12. Projects panel as draggable tabs
- **Decision.** The user asked (2026-10-16, screenshot of the Projects list): "projects 最好也做成tab模式，可以拖拽，改变位置".
- **UI** (`runner/templates/index.html`, Projects panel):
  - **Tab strip.**
    - A horizontal strip has one tab per registered project. The tab shows the key, the `confidential`/`no push`/kind badges, and the session count.
    - An error project shows as a red tab. Its Remove button lives in that tab's **body**, never inside the tab; tabs contain no nested interactive elements (STB-075).
    - "+ Project" sits at the right end of the strip.
  - **Body.** The selected tab's body is today's expanded project:
    - the Sessions/Files switch (E);
    - the session rows (§6 Resume, Rename, Remove);
    - the project actions: Run tests (when `verify` is set), Edit, Remove, and the existing "Open terminal". The baseline line stays here too.
  - **Drag to reorder.**
    - Tabs reorder by drag and drop, using native HTML5 drag events, no library.
    - The order is saved per browser in `localStorage` (`agenticos.projectTabs.order`); the selected tab in `agenticos.projectTabs.active`. Every `localStorage` access is wrapped in try/catch, and it falls back to registry order.
    - New projects append at the end; removed keys are dropped from the saved order.
- **Server.** Unchanged: `/api/projects` keeps registry order, and the order is a viewer preference.
- **Keyboard.** Tabs are buttons in a `role="tablist"`. Left and Right arrows move between them; Alt+Left and Alt+Right move the selected tab one place (an accessible alternative to dragging).

## Non-goals
- Changing what a drag/reset to Todo means (Decision 11 stays).
- Any change to the card Terminal tab, in any column (user decision): no Open terminal, no Copy command, no tab for no-run Linear cards.
- Moving or removing the project row's "Open terminal".
- Runner commit/verify for replies to sessions outside a ticket worktree (§3.2).
- Tracker write ordering: `docs/exec-plans/active/2026-10-15-tracker-write-ordering.md`.

## Accepted plan-review risks (convergence standard)
- **STB-082.** A second, concurrent claimant of the *same* session could be hidden by the own-claim exclusion in `session_in_use`. With one user, the same session is not continued by two runs at once.
- **STB-085.** `set_issue_project` during Linear dispatch can raise on a transient Linear error such as a rate limit. This needs an injected or rare failure. At build time it will be made best-effort (logged, dispatch continues), but the plan text is not reworked for it.

## Risks
- **Two writers on one transcript.** Continuing a session that another process also has open interleaves the transcript. The warning makes it visible; it is not prevented (user decision).
- **Detection can miss.** A process that opened the session without its id in argv and has not written since our last run is missed. The check is advisory by design.
- **No commit or verify.** Replies in the main checkout get no runner commit or verify. This is intended, and the reply UI says "runs in <folder>" so the user knows where it acts.

## Verification
- Proof: `.venv/bin/python -m pytest tests/ -q -p no:cacheprovider` → all pass.
- Manual: the `verify` skill recipe (isolated runner on :8599, fake `claude` on PATH that echoes argv and cwd, fixture session in a temporary project; a confidential variant):
  - Resume from the project row → the card lands in Todo and the detail opens with the reply focused, no panel;
  - a reply continues the same session id in the session's folder, sandboxed for the confidential project;
  - drag to Review and back to Todo → the next reply starts fresh;
  - the card Terminal tab looks and works as before in every column.

## Progress Checklist
- [x] DeepSeek plan review (third-party, read-only); dispositions in the review log. Closed under the user's convergence standard after 12 rounds (findings 11, 9, 8, 9, 8, 6, 4, 4, 4, 6, 9, 8; every high fixed; round 12's high and reproducible ones fixed; STB-082 and STB-085 accepted). Not a claudex cross-provider approval.
- [x] Codex plan review (claudex cross-provider) approved, or closed under the convergence standard; dispositions in the review log — APPROVED round 5, SHA 00df38e7…, check re-confirmed at build start
- [x] User go-ahead to build — 2026-10-16: "claude 写，然后codex检查"
- [x] Test: to-board with no card → a tracker issue in Todo (local tracker) plus a linked run record with `resume_session` (current gen), binding, title (withheld when confidential + unsafe); the board lists it — tests/test_session_to_board.py::test_to_board_without_a_card…, test_confidential_new_card…
- [x] Test: to-board on a found card (Review/Done/Backlog/Error) → issue to Todo, gen bumped, `todo` record with `resume_session` on the issue's latest run_id; interactive_ended/archived records are never picked — tests/test_session_to_board.py::test_to_board_on_a_found_card…
- [x] Test: to-board while the session is claimed, launching or running → 409, nothing appended — tests/test_session_to_board.py::test_to_board_refuses_a_running_or_claimed…
- [x] Test: two concurrent to-board calls → one card — tests/test_session_to_board.py::test_two_concurrent_to_board_calls_make_one_card
- [x] Test: a client cwd is ignored; a session outside the project roots → 404 — tests/test_session_to_board.py::test_to_board_refuses_sessions_outside… (the route reads no cwd)
- [x] Test: drag to Todo after Resume (tracker PATCH and run status PATCH both) → gen bumped → next retry fresh; `api_run_set_status`/`api_run_restore` drop `resume_session` — tests/test_session_to_board.py::test_reply_rules_agent_empty_and_reset; restore keeps the field per SBR-001
- [x] Test: retry on a session card with a different body agent → 409; dsh session → no to-board — tests/test_session_to_board.py::test_reply_rules…, test_to_board_refuses_sessions_outside_the_project_and_dsh
- [x] Test: reply on a ticket-worktree session card goes through `_run_project_ticket` with `resume_session` (commit/verify kept) — tests/test_session_to_board.py::test_ticket_session_in_its_worktree…
- [x] Test: reply on another session card → `run_agent_process` in the session cwd with the `agent_cli` argv; confidential → sandbox flags; dsh on confidential → refused; strict failure → error — tests/test_session_to_board.py::test_reply_continues…, test_confidential_reply…, test_intent_survives…
- [x] Test: confidential session reply outside a ticket worktree with unsafe record locations → refused before launch, nothing streamed, withheld error record — tests/test_session_to_board.py::test_confidential_reply…
- [x] Test: reply records keep `linear_issue_id` and `source`; the reply UI stays after a continuation — tests/test_session_to_board.py::test_reply_continues…; manual, isolated runner + Chrome 2026-10-16
- [x] Test: session moved away → retry 409, nothing recorded, no claim leaked — tests/test_session_to_board.py::test_session_moved_away…
- [x] Test: `session_in_use` reasons (other live id, process argv outside the runner tree, fresh write after own run); own claim (by run_id) and own just-finished run never count; a second claimant does; retry without confirm → 409, with confirm → dispatched — tests/test_session_to_board.py::test_own_finished_run_is_not_elsewhere, test_reply_asks_when…
- [x] Implement §1–§3 backend (record field and stripping, status helper, to-board route, retry branch on `run_agent_process`/project helper, record withholding) — runner/app.py session-card section
- [x] Implement §4 (`session_in_use`, detail payload field, confirm on card reply and quick reply) — session_in_use, detail fields, _postRetry and quick-reply confirm
- [x] Implement §5 (reply UI for session cards only; Terminal tab untouched) — index.html detail/board controls
- [x] Implement §6 (Resume button, inline errors) — _resumeToBoard, inline row error
- [x] Test: §7 badge — no changes → no badge; changes + no check → "no check"; verify fail → fail — tests/test_session_to_board.py::test_badge_for_a_run_that_changed_nothing
- [x] Implement §7 (badge rule in `project_runs`, neutral style in `index.html`) — project_runs.post_run start_sha rule; .verify-badge.none
- [x] Test: §8 — a stream with an init event `model: claude-opus-5-5[1m]` and a json result with `modelUsage` both record that model; cost uses it — tests/test_session_to_board.py::test_observed_model_and_cost
- [x] Implement §8 (init-event model in the stream readers, `modelUsage` in `_parse_agent_output`) — _observed_claude_model in both readers; price key strip
- [x] Test: §9 — an sdk-cli transcript whose id is in the run log is listed (with identifier) and resolvable; one not in the run log is hidden; a codex `exec` thread likewise — tests/test_session_to_board.py::test_board_launched_headless…, test_codex_exec_threads…
- [x] Implement §9 (run-log id set, listing and `session_target` filters, identifier label) — _board_sessions → project_sessions/session_target
- [x] Test: §2.5 Linear path creates the issue synchronously (fake client) with `ensure_label` label ids and the agent marker, inserts it into the cache and emits; the record links to the real id; confidential → neutral title; unresolvable label → 409, nothing created; local path sets labels and `preferred_agent` — tests/test_session_to_board.py::test_linear_session_issue…, test_linear_error_on_create…, test_confidential_new_card…
- [x] Test: §2.4 failed Todo move or push → 409, nothing appended, gen unchanged; confidential + unsafe → copied text withheld — tests/test_session_to_board.py::test_failed_move_restores…
- [x] Test: §3.3 inline-`project_key` card never calls `_run_project_ticket`; durable binding whose worktree equals the session cwd does; main-checkout session of a bound ticket takes the generic path — tests/test_session_to_board.py::test_reply_continues…, test_main_checkout_session_of_a_bound_ticket…, test_ticket_session_in_its_worktree…
- [x] Test: §7 order — no-change run with verify fail or main checkout changed keeps its red badge; no-change run with verify pass shows no badge — tests/test_session_to_board.py::test_badge_for_a_run_that_changed_nothing
- [x] Test: found-card to-board on a card whose latest run used another session → record's `agent_session_id` is the resumed one; retry passes the strict guard — tests/test_session_to_board.py::test_to_board_on_a_found_card…
- [x] Test: a card reply without `strict` in the body is still strict and never falls back to a fresh session (STB-060); reply records carry `issue_identifier` (STB-061); a drop of a resumed card onto In Progress opens the reply and does not dispatch (STB-062); §9 identifier label comes from the passed map (STB-063) — tests/test_session_to_board.py::test_intent_survives…; manual, isolated runner + Chrome 2026-10-16: drop onto In Progress opened the reply; §9 label test
- [x] Test: on a resumed Todo card neither the ▶ button nor the agent badge dispatches; only the intent agent's retry button renders (STB-056/059); to-board on a card with an in-flight run on another session → 409 (STB-057); §2.5 record carries `issue_identifier`, and an open tab on it blocks a drag (STB-058) — manual, isolated runner + Chrome 2026-10-16: ✎ Reply and badge open the reply, only the intent agent's button; tests/test_session_to_board.py::test_to_board_refuses_a_running…
- [x] Test: a to-board card's reply resumes `resume_session.id` with strict on (STB-055); generic confidential reply posts no reply/output text to the tracker (STB-052); intent reply and a concurrent drag contend for the same `reserve_card` lock (STB-054); board payload carries `resume_ok`, and the inline ▶ button opens the reply instead of dispatching (STB-053) — tests/test_session_to_board.py::test_reply_continues…, test_reply_holds_the_card_and_project_locks…, test_to_board_contends…
- [x] Test: confidential §2.5 sends an empty description (agent marker only); `gpt-5.4-mini` cost unchanged; poll with an archived id in the fetch result drops it; intent card reply holds the card or ticket lock and `project_lock` — tests/test_session_to_board.py::test_confidential_new_card…, test_observed_model_and_cost, test_archived_issues_stay_out…, test_reply_holds…; poll-loop filter by code review only
- [x] Test: found-card to-board record keeps the latest run's fields (detail and events unchanged); dispatch group hidden while `resume_ok`; own interactive_ended audit is not "elsewhere"; generic session path treats a non-False binding as confidential — tests/test_session_to_board.py::test_to_board_on_a_found_card…, test_intent_survives…; manual, isolated runner + Chrome 2026-10-16: dispatch group hidden
- [x] Test: project and Linear runs write `token_cost_usd` from the observed model — tests/test_project_dispatch.py::test_question_only_run…; Linear dispatch by code review
- [x] Test: §7 per-run start sha (ticket with earlier commits or an earlier seed commit, question-only run → no badge); §8 `_parse_project_output` reads init/`modelUsage`; cost for `claude-opus-5-5[1m]` uses the Opus rate — tests/test_project_dispatch.py::test_question_only_run…; test_observed_model_and_cost
- [x] Test: §10 project → Linear Project mapping (fake client): `find_project`/`create_project` once, reused; `project_id` on create; `set_issue_project` on dispatch; confidential skipped — tests/test_session_to_board.py::test_linear_project_mapping, test_linear_session_issue…, test_dispatch_moves…
- [x] Implement §10 — linear_client project calls, linear_project_id, create/dispatch wiring
- [x] Test: §11 empty trash archives only Canceled issues (fake client `archive_issue`), evicts them from cache, `_issues_by_team`, overrides and `tasks.json`; a following poll (carry-over) and a restart do not bring them back; run records untouched; Resume afterwards creates a new card — tests/test_session_to_board.py::test_empty_trash_local…, test_empty_trash_linear…, test_archived_issues_stay_out…
- [x] Implement §11 — empty_trash/_evict, archived_ids, poll filter, UI button
- [x] Test: §2.4 explicit bump and restore on a failed move; intent survives opening and closing the card's tab (STB-065/068); §2.4 record has `issue_identifier`; `session_target` title used, client title ignored; unbound/confidential creates carry the default project id; a running board session is listed via `board_ids` — tests/test_session_to_board.py::test_failed_move_restores…, test_intent_survives…, test_to_board_without_a_card…
- [x] Test: board-launched session resolves for to-board and reply (STB-070); to-board holds `reserve_card` and a concurrent drag waits (STB-071); LinearError surfaces as 409 and per-issue trash failures (STB-072/074); local Empty trash reads Canceled tasks directly (STB-073); verify timeout is red (STB-076); intent predicate skips archived (STB-077); session card without a record binding uses the `resume_session` project's confidentiality (STB-078) — tests/test_session_to_board.py::test_board_launched_headless…, test_to_board_contends…, test_linear_error_on_create…, test_empty_trash_linear…
- [x] Test: second reply after a continuation (record carries `resume_session`) from In review/Done takes §3 again, never `_run_project_ticket(reuse_only=True)` for a non-worktree session; `api_run_set_status` to done keeps the field, to todo drops it (SBR-001) — tests/test_session_to_board.py::test_reply_continues…
- [x] Test: `open_terminal` on a new to-board card opens in the session cwd without `load_binding`, takes the ticket lock; on a bound ticket's main-checkout session opens the main checkout; on a worktree session opens the worktree (SBR-002) — tests/test_session_to_board.py::test_session_card_terminal_opens_in_the_session_folder
- [x] Test: issue editor save with a started state on a `resume_ok` card does not PATCH and opens the reply (SBR-003) — manual, isolated runner + Chrome 2026-10-16
- [x] Test: local tracker create LOC-1, delete, create → LOC-2; missing meta file initialised from tasks, run log and worktree dirs (SBR-004) — tests/test_session_to_board.py::test_empty_trash_local…, test_identifier_floor…
- [x] Test: cancel and stall of a generic session reply write a record carrying `resume_session`, binding, `issue_identifier` and `source` (withheld when confidential + unsafe); the job has no top-level `project_key`; the next reply takes §3 (SBR-005) — tests/test_session_to_board.py::test_cancel_of_a_session_reply_keeps_its_routing
- [x] Test: title-only save of a resumed Todo card sends no `state_name` and keeps the generation (SBR-006) — manual, isolated runner + Chrome 2026-10-16: no state_name sent, resume_ok kept
- [x] Test: Open interactive on a session card after a reset to Todo, and on an older attempt, opens the session folder (SBR-007) — tests/test_session_to_board.py::test_session_card_terminal_opens_in_the_session_folder
- [x] Test: a continuation marked Done shows the reply send controls (intent agent only) and the main reply box sends a continuation (SBR-008) — manual, isolated runner + Chrome 2026-10-16: Done card showed ↺ Codex only and sent the reply
- [x] Test: SIGTERM shutdown with a silent generic session reply running kills its process group, writes its cancel record with the §3.6 fields, and a launch after shutdown began is refused (SBR-009) — tests/test_session_to_board.py::test_shutdown_cancels_generic_runs…
- [x] Test: shutdown with a silent generic reply → exactly one `cancelled` record (written by `_cancel_generic`, §3.6 fields) exists when `_stop_project_runs` returns, the worker writes none; a worker already finalizing is waited for via `_finalizing` (SBR-010) — tests/test_session_to_board.py::test_shutdown_cancels_generic_runs…, test_finalizing_runs_are_waited_for
- [x] Implement §12 (tab strip, drag reorder, localStorage order/active, keyboard reorder) — index.html tab strip
- [x] Manual: §12 in the isolated runner — reorder by drag and by keyboard, reload keeps order, add/remove a project — manual, isolated runner + Chrome 2026-10-16
- [x] Full suite passes — 629 passed
- [x] Manual check in the isolated runner (verify skill), each column, both agents, confidential variant — manual, isolated runner + Chrome 2026-10-16: claude, codex, confidential; Todo/In Review/Done paths
- [x] Fresh build inspection (Codex, or DeepSeek if Codex is unavailable, recorded as third-party) with no unresolved high findings — Codex 3 rounds (SBI-001..015) + DeepSeek 2 rounds third-party (SBI-016..019, Codex usage limit); all fixed, none unresolved; SBI-018/019 fixes not re-inspected
- [x] Public-repo check: `git grep` for the private project names (pattern kept outside the repo) finds nothing in tracked files — no hits after removing the old `agentic-os-dashboard.png` (user, 2026-10-16: "yes, remove the old png"); it remains in pushed history (1e18fa3)
- [x] Commit (not pushed) — this commit; /verify passed on the staged tree first
