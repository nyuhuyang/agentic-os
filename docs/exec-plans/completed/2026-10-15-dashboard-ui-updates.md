---
status: completed
created: 2026-10-15
---

# Dashboard UI updates

Five dashboard changes requested on 2026-10-15, kept in one plan (user: "these are all UI changes"):
- A. Rename and remove sessions from the Projects panel
- B. Pick a project when creating a task (default `agentic-os`)
- C. Live terminal view of a card's session from any board column
- D. Rename the project panel's "Baseline" button to "Run tests"
- E. Browse a project's files (tree + preview) from the Projects panel

Each part has its own goal, criteria and checklist; one Codex plan review and one build inspection cover all parts.

## A. Rename and remove sessions

### Goal
Each session row in the Projects panel gets "Rename" and "Remove". Rename changes the title everywhere the native tools show it; Remove takes the session out of the panel and out of the native resume pickers, recoverably. Today the list is read-only.

### Acceptance criteria
- [x] Renaming a Claude session shows the new title in the panel and in `claude --resume`; renaming a Codex session shows it in the panel and in `codex resume` — panel title verified (tests + isolated browser check); native pickers confirmed 2026-10-24 (item 74)
- [x] Removing a Codex session archives it (`threads.archived = 1`, `archived_at` set): gone from the panel and from `codex resume`, restorable by un-archiving — archived row and panel verified; native pickers confirmed 2026-10-24 (item 74), un-archive brings it back
- [x] Removing a Claude session moves its transcript (and its same-named sidecar folder, if any) to `~/.agentic-os/session-trash/<slug>/`: gone from the panel and from `claude --resume`; restoring is moving it back — trash move, sidecar and panel verified; native pickers confirmed 2026-10-24 (item 74), moving it back brings it back
- [x] Remove asks for confirmation naming the session title; both actions are refused for a session that is live (running in a dashboard tab, a running job, or a transcript written in the last 2 minutes)
- [x] Only sessions of a registered project are touched: the session's cwd must be under that project's path, and the file/row must resolve inside `~/.claude/projects` / `~/.codex`
- [x] A failed write leaves the session exactly as it was (no half-written transcript, no partial DB update)

### Decisions
- User authorization (2026-10-15): the dashboard may write to `~/.claude` and `~/.codex` for these two actions only. Everything else there stays read-only.
- Claude rename uses the CLI's own record: append `{"type":"custom-title","customTitle":<title>,"sessionId":<id>}` to the transcript (the shape `/rename` writes, verified in Claude Code 2.1.300); the reader already takes the last `custom-title`.
- Codex rename sets `threads.name`; the reader already prefers `name`.
- Remove is never a hard delete: Codex has native archiving; Claude has none, so the transcript moves to a trash folder outside `~/.claude`.
- Titles: plain text, trimmed, 1–200 characters, no control characters.

### Approach
#### Backend (runner/projects.py, runner/app.py)
- [x] `session_target(project, agent, id)`: resolve a session of this project (re-reads the session readers; refuses unknown ids, ids with path characters, cwd outside the project, files outside the stores)
- [x] `rename_session(project, agent, id, title)`: Claude → record the transcript size, append the `custom-title` line with `O_APPEND` in one `os.write` (newline-terminated); if the write returns short or raises, `ftruncate` back to the recorded size, so no partial record survives (safe because live sessions are refused, so nothing else appends meanwhile); Codex → `UPDATE threads SET name = ? WHERE id = ?` in one transaction (sqlite timeout 5 s)
- [x] `remove_session(project, agent, id)`: Claude → check that neither trash destination (`~/.agentic-os/session-trash/<slug>/<id>.jsonl`, `<id>/`) exists, then `os.rename` the transcript first and the sidecar folder second; if the sidecar move fails, move the transcript back and report the error. No copy fallback: a cross-filesystem trash (`EXDEV`) is refused before anything moves. A crash between the two renames leaves only an orphan sidecar in `~/.claude/projects` — nothing is lost, the confirm text's restore note covers it. Codex → `UPDATE threads SET archived = 1, archived_at = <now> WHERE id = ? AND archived = 0`
- [x] Session identity on writers (today they do not keep it): `Terminal` gains `agent` / `session_id` (set at open for resume tabs); running jobs record `agent_session_id` before launch for resumes and as soon as the init event reveals it for fresh runs, on every launch path
- [x] Live check: refuse when a dashboard terminal holds this session id, when a running job's `agent_session_id` is this id, or when the transcript/rollout changed in the last 2 minutes. The check and the mutation run under a per-session admission lock (`session_lock(agent, id)`) that resume-tab opening and retry/quick-reply launch also take for their admission, so a resume cannot start between check and write
- [x] Routes: `POST /api/projects/<key>/sessions/<agent>/<id>/rename` `{title}` and `POST …/remove`; both go through the maintenance request gate; 400 on validation, 409 on live/busy, 404 on unknown

#### UI (runner/templates/index.html)
- [x] Session row: "Rename" (inline prompt prefilled with the current title) and "Remove" (confirm naming the title); the list refreshes after success; errors shown inline

#### Docs
- [x] Note the two write exceptions to the read-only rule in the session-readers comment in `projects.py`

### Non-goals
- Restore UI (move the file back / un-archive by hand; documented in the confirm text)
- Bulk actions, renaming sessions of unregistered folders
- Editing `sdk-cli` headless sessions (not listed today)

### Risks
- The Claude CLI rewrites its own `custom-title` when a resumed session saves; the last record wins, so a later rename inside Claude Code takes over — expected
- A Codex app or VS Code extension caching thread lists may show the old name until it reloads

### Verification
- Proof: `.venv/bin/python -m pytest tests/` passes
- Manual: on a throwaway session in a throwaway project, rename and remove from the dashboard (headless browser), then confirm in `claude --resume` / `codex resume`

### Progress Checklist
- [x] Test: Claude rename appends exactly one well-formed `custom-title` line and the panel shows it; Codex rename updates `name`
- [x] Test: Claude remove moves transcript + sidecar to the trash and the panel drops it; destination clash refused; Codex remove archives and the panel drops it
- [x] Test: failure leaves the session as it was — a short/failed Claude append is truncated back (byte-identical file); a failed sidecar move puts the transcript back; an `EXDEV` trash is refused before any move
- [x] Test: refusals — live session (tab, job, fresh file), foreign project, path-like id, bad title, unknown id; nothing changes
- [x] Test: a resume tab opened for the session id while a remove holds `session_lock` waits or is refused; a running job and a resume tab expose their session id to the live check
- [x] Test: routes are gated by maintenance (409) and need the request token
- [x] Implement backend helpers and routes
- [x] Implement UI buttons
- [x] Manual browser check on a throwaway session; native pickers confirm — dashboard flow verified in an isolated runner against fixture stores (rename, 2-min refusal, remove + sidecar, Codex archive). Native pickers, 2026-10-24: throwaway sessions in a temp `CLAUDE_CONFIG_DIR` / `CODEX_HOME` (the real `~/.claude` / `~/.codex` untouched), changed by `projects.rename_session` / `remove_session` (what the routes call), then the real `claude --resume` (2.1.309) and `codex resume` (0.163.0) opened in a pty: the renamed title is listed, the removed/archived session is gone, and moving it back / un-archiving lists it again

## B. Pick a project when creating a task

### Goal
The new-task form (job board "+" / Todo) gets a Project selector listing the registered projects. The chosen project decides where the task runs: its dispatch goes to a worktree of that project, exactly like a Linear ticket labelled `project:<key>` today. If the user picks nothing, the task belongs to `agentic-os`. User request, 2026-10-15.

### Acceptance criteria
- [x] The new-task form shows a Project selector with every registered (parseable) project; `agentic-os` is preselected when registered
- [x] Creating a task with a project stores `project:<key>` as a label on the local task and on the Linear issue, and its dispatch runs in a worktree of that project on `agent/<id>` (Linear issue side: fake-client test `test_labels_survive_the_background_swap_and_backups`)
- [x] Creating a task without choosing uses `agentic-os`; if `agentic-os` is not registered, the task is created without a project and the form says it will run at the runner root (today's behaviour)
- [x] A local-first task keeps its `project:<key>` label through every later write: the background swap to the Linear id, `_localize_issue` backups, tracker fallback and updates; dispatch right after sync still runs in the project's worktree
- [x] While the Linear tracker is active, a task that still has a `local-*` id is never dispatched or retried (409, "not synced to Linear yet", button disabled), whether its create is pending, failed or had a lost response: only the Linear-id copy runs, so a run never binds to `LOC-N` and then loses that identity. Without Linear (local tracker only) local ids dispatch as today
- [x] An unknown or broken project key is refused at creation (400) with nothing created
- [x] Existing tasks without a project keep today's behaviour

### Decisions
- The project travels as the existing `project:<key>` label, so dispatch, retry and the durable binding need no new path (`project_runs.project_key_from_labels`, `_dispatch_issue`).
- The local tracker gains a `labels` list on each task (default empty) and the normalized issue exposes it; old task files without the field read as `[]`.
- Linear: the label is looked up by name (`issueLabels(filter: {name: {eq}})`), created in the team when missing (`issueLabelCreate`), and attached at create (`issueCreate.labelIds`); the background create already runs there.
- Default `agentic-os` is the registry key, resolved at form-load time from `/api/projects`; the server applies the same default when the request omits `project`.

### Approach
- [x] `local_tracker.create_issue(..., labels=None)` stores `labels`; `_normalize` / `fetch_issue(s)` return it
- [x] `POST /api/linear/issues` accepts `project` (key or empty): validate against the registry (refuse unknown/broken), default to `agentic-os` when registered, pass `labels=["project:<key>"]` to the local create and to the background Linear create
- [x] `LinearClient`: `ensure_label(team_id, name)` and `create_issue(..., label_ids=[...])`; the create mutation's selection includes `labels { nodes { name } }`
- [x] Label-preserving writers: `_bg_sync_to_linear` writes the normalized create result with labels (falling back to the validated local labels if the response lacks them); `_localize_issue` passes `labels` on create and update; `_normalize_linear_issue` maps label nodes to the `labels` list
- [x] Local-id guard: when the Linear tracker is active, `_dispatch_issue` and the dashboard dispatch/retry routes refuse any `local-*` issue id with 409 (no state change, nothing launched); the card shows "syncing…" and no dispatch button. No pending-state tracking is needed: the id itself says whether a Linear copy has been confirmed
- [x] UI: Project `<select>` in the new-task form (registered keys from `/api/projects`, `agentic-os` preselected, "No project (runner root)" as the last option); the draft keeps the choice
- [x] The board card shows the task's project as a small badge

### Non-goals
- Changing the project of an existing task (re-labelling a bound ticket conflicts with its durable binding)
- Fixing the pre-existing local-first gaps when Linear is active: a failed or lost-response create can leave a `local-*` card that polling later drops or that duplicates the remote copy, and global tracker routing does not send its edits to `LocalTracker`. This plan only guarantees such a card is never dispatched; reconciling it needs its own tracker plan (not yet written)
- Creating a project from the task form (use "+ Project")

### Risks
- A task created under `agentic-os` now runs in an `agentic-os` worktree, not in the runner's own checkout; tasks that relied on the runner root (e.g. editing `state/`) need "No project"
- Label creation needs the Linear key's write scope (already used for comments and issue creation)

### Verification
- Proof: `.venv/bin/python -m pytest tests/` passes
- Manual: create one task with a project, one with the default, one with "No project"; dispatch each and check the worktree/branch (or runner root) and the Linear label

### Progress Checklist
- [x] Test: local task stores and returns `labels`; an old task file without the field reads as `[]`
- [x] Test: create with `project` → label on the local task; omitted → `agentic-os` when registered, none when not; unknown key → 400, nothing created
- [x] Test: labels survive the background id swap (create response with and without labels), `_localize_issue` create/update and tracker fallback; dispatch right after sync uses the project's worktree
- [x] Test: with Linear active, dispatch/retry of a `local-*` task (create pending, failed, or returned nothing) → 409, nothing launched, state unchanged; with the local tracker only, the same task dispatches into the chosen project's worktree
- [x] Test: `ensure_label` reuses an existing label and creates a missing one; `create_issue` sends `labelIds`
- [x] Implement tracker labels, route, Linear client, UI selector and card badge
- [x] Manual check of the three creation cases, including the Linear label — all three creation cases verified in the isolated runner (local tracker). Linear label path confirmed in production, 2026-10-24: 43 live Linear issues carry `project:<key>` labels across 9 projects (agentic-os, knowledge-base, Trading, study_research, …) and their runs used `~/.agentic-os/worktrees/<key>/<id>` on `agent/<id>` (e.g. AGE-117 → agentic-os, AGE-123 → knowledge-base, AGE-135 → Trading)

## C. Live terminal view from any board card

### Goal
The terminal panel at the bottom stays as it is. Any card in Backlog, Todo, In progress, In review or Done that has a session gets a "Terminal" action that opens a tab in that panel showing the session live — what the agent is doing as it happens, not the after-the-fact Output / Log / Error panes. User request, 2026-10-15.

### Acceptance criteria
- [x] Every card with a running job or a recorded session shows a "Terminal" action on the card and in its detail view, in all five columns; cards with neither show nothing
- [x] Running job (any path: dashboard `/run`, Linear dispatch, retry/rework, project dispatch): the tab streams the agent's events in real time — assistant text, each tool call with its arguments, tool results (truncated), errors — as terminal lines, starting with what was already emitted
- [x] Finished job with a resumable session: the tab first replays the last run's events (from the stream log on disk, so it works after a runner restart), then offers "Resume here", which opens the interactive `claude --resume` / `codex resume` in the run's own folder (worktree or runner root), using the existing resume-tab rules (ticket lock, confidential policy)
- [x] A card with several attempts lets the user pick the attempt; the latest is the default
- [x] Opening the same card twice focuses the existing tab
- [x] Confidential runs show their live view only in the dashboard (never sent to Linear), same as the run tab today

### Decisions
- Agents run headless (`-p` / `exec --json`), so there is no TTY to mirror while they run; "live terminal" means rendering their event stream as it arrives. Interactive control is the resume tab once the run has ended.
- One event source for all runs: the existing `project_runs.RUN_EVENTS` ring and `run_event` socket event, now fed by every stream reader (`_stream_claude_run`, `_stream_text_run`, `_stream_dsh_run`, project `run_agent`), not only project dispatch.
- Replay after the run reads the run's stream log (`outputs/logs/<run>_stream.jsonl` or the text stream) through the same renderer, so live and replay look identical.
- **Prerequisite (user decision, 2026-10-15):** one agent-process lifecycle comes before any streaming work. Today five near-copies run the same sequence: Popen in its own group, the `_register_proc` handshake, stream/communicate, one deadline, group kill and reap, `_RunClaim`/`_end_job`, and owner-only record plus tracker push. The copies are `/run` entrypoint, `/run` agent, retry `_dispatch_cmd`/`_do_retry`, Linear `_dispatch_issue_counted`, and the project helper. Their failure paths cost 10 inspection rounds in `docs/exec-plans/completed/2026-10-15-runner-write-safety.md`. Their process part becomes one engine, `run_agent_process(run_id, cmd, …)`, and the Linear/retry migration to streaming happens on that engine, never as a sixth copy. Its behavior is fixed by the existing tests in `tests/test_runner_write_safety.py`, which must keep passing unchanged.
- **C0 boundary (round 4, R14/R15):** the engine runs exactly one process and never ends the run: no `_RunClaim`/`_end_job`, no terminal record, no tracker push. Run completion stays with each caller's coordinator, because callers differ after the process exits: retry runs a resume then maybe a lazily built fallback under one run id and claims once after the fallback decision; quick reply (strict continuation) is the same coordinator with the fallback disabled; the project path keeps its job through post-run verification, binding and confidential recording. The project path is exempt from the engine: it already launches through `projects.spawn` (group registry used by shutdown and by git/verify) and streams through `project_runs.run_agent`, which is the existing event source; it only gains the durable log. Process handles stay registered between attempts (existing `attempt_proc` rule) and card reservations stay held until the caller's run ends.

### Approach
- [x] C0 prerequisite: extract the process engine `run_agent_process(run_id, cmd, *, stream, timeout, cwd, env) -> (output, in_tokens, out_tokens, model, session_id, stderr, ok)` in `runner/app.py`. It owns Popen (own session), the `_register_proc` handshake (raises `_RunEnded` when the run already ended), the streaming readers (`_guarded`, selector, stop event) or `communicate` for non-streaming commands, the single deadline, `_kill_and_reap` on every failure after launch, and feeding `RUN_EVENTS` / the durable log. It does not claim, record or push the tracker (see C0 boundary). Callers: `/run` entrypoint, `/run` agent, retry `_dispatch_cmd` (each attempt, incl. the lazily built resume fallback) and Linear `_dispatch_issue`. Each keeps its own coordinator: claim, record, tracker, comments. The project path stays on `projects.spawn` / `project_runs.run_agent` (exempt, see boundary)
- [x] `render_event(agent, raw) -> list[str]`: one renderer from Claude stream-json / Codex JSON / dsh / plain text to terminal lines (ANSI-dim tool results, colored errors), shared by live and replay
- [x] Every stream reader pushes rendered lines into `RUN_EVENTS[run_id]` and emits `run_event`
- [x] Launch paths that buffer with `proc.communicate` today move to streaming: non-project Linear Claude/Codex dispatch (`modules/linear` `_dispatch_issue`, uses `output_format="json"`) and Codex retry (`app.py` `_dispatch_cmd` `else` branch). Claude switches to stream-json through `_stream_claude_run`; Codex `exec --json` is read line by line by a shared reader that also extracts the thread id. Every path records `agent_session_id` (Claude init event / Codex thread id) on the run, so finished Linear runs are resumable
- [x] Durable event log on every path, including project `run_agent` (today it keeps events only in memory): raw lines append to the existing stream log (`_claude_stream_log_path(run)`, unchanged raw contract — existing tests read its first token), and the replay metadata `{agent, format}` goes to a separate sidecar `<run>_stream.meta.json` written at launch; confidential runs write to the confidential records location already used for their run records (`_records_unsafe` rules), never elsewhere
- [x] `GET /api/runs/<id>/events` replays from the stream log when the ring is empty (finished or after restart) and reports `resume_eligible` for every path, not only project runs
- [x] Board card + detail view: "Terminal" action (attempt picker when there are several); opens `openRunTab`, which on finish shows "Resume here" (per the C2 decision it opens the card's Terminal tab; "Show in panel" opens `openRunTab`)
- [x] The existing project-only "▤ run tab" badge becomes this action

### Non-goals
- Typing into a running headless agent (not possible; resume after it ends)
- Changing the terminal panel layout

### Risks
- Very chatty runs: the ring stays bounded (existing `EventRing` limit); replay reads the tail of the log, not the whole file

### Verification
- Manual: a running dashboard `/run`, a running Linear dispatch and a finished project ticket each open a live/replay tab from their card; "Resume here" opens an interactive session in the right folder

### Progress Checklist
- [x] C0: `run_agent_process` extracted; a spy test drives `/run` entrypoint, `/run` agent, retry (resume, fallback, strict quick reply) and Linear dispatch with a fake CLI and asserts each launch goes through the engine, and that each run writes exactly one terminal record (no duplicate ownership); the project path still launches through `projects.spawn`
- [x] C0: retry under the engine — a failed resume followed by the fallback stays one run with one claim and one record; cancel between the two attempts and a fallback whose command construction fails behave as the existing write-safety tests expect; strict quick reply skips the fallback
- [x] C0: project cancel during post-run verification and the final binding/verify record behave as `tests/test_project_dispatch.py` expects (project path untouched by the engine)
- [x] C0: `tests/test_runner_write_safety.py` and the full suite pass unchanged after the extraction
- [x] C0: the Linear/retry streaming migration below is built on `run_agent_process`
- [x] Test: renderer turns sample Claude, Codex, dsh and text events into the expected lines
- [x] Test: each stream reader feeds the ring and emits `run_event` (non-project and project paths), including the migrated Linear dispatch and Codex retry entry points, which emit events before the process exits
- [x] Test: Linear Claude and Codex dispatch record `agent_session_id`; the finished run reports `resume_eligible`
- [x] Test: events endpoint replays from the stream log after `RUN_EVENTS` is cleared (restart), for a project run and a non-project run; a confidential run's log lands only in the confidential records location; replay reads the agent/format from the `.meta.json` sidecar and the raw log keeps its existing format (first token unchanged)
- [x] Implement renderer, reader hooks, replay, card/detail action and attempt picker
- [x] Manual check: live view for a running job, replay + "Resume here" for a finished one, from cards in different columns (isolated runner: live lines during a quick-reply run on an In progress card; replay + Open interactive on an In review card)

### C2. Answering a session that stopped for review (e.g. `/claudex-loop` asking for sign-off)
A headless run that ends by asking the user something lands in In review. The user needs to read what it asked, with context, and continue the same session. User idea: an openable terminal inside the card's tab; refined as below.

#### Acceptance criteria
- [x] The card detail view gains a fourth tab, "Terminal", next to Output / Log / Error; it opens by default when the card is In review or has a running job
- [x] The Terminal tab shows the C view (live or replayed events) with the run's last assistant message pinned at the top
- [x] "Quick reply": a text box under the view; sending it continues the same session headless through the existing reply/retry path (`/api/runs/<id>/retry` with `reply`), so the card goes back to In progress and the attempt is logged. It runs in strict continuation mode: it needs a resumable session (else 409, nothing logged), always uses the resume command (no scheduled-entrypoint routing), and a failed resume is reported as the attempt's error — it never falls back to a fresh session
- [x] "Open interactive": starts the interactive `claude --resume` / `codex resume` inside the Terminal tab, in the run's folder (worktree or runner root). The bottom terminal panel does not open, expand or switch to it, and it is not added to the panel's tab strip; the session keeps running in the background when the detail view closes, and appears in the bottom panel only when the user asks ("Show in panel" in the detail tab, or picking it from the panel's list of running terminals)
- [x] While the interactive terminal is open it holds the card's lock, so quick reply, retry and auto-dispatch for that card are refused with a clear message (409, no tracker change, no comment, no attempt logged). Project cards use the existing `ticket_lock`; runner-root cards (no project) get the same lock keyed by a server-resolved card key — the tracker id when the run has `linear_issue_id`, otherwise the root `task_id` that retry already chains attempts to (dashboard `/run` cards have no tracker id) — via `task_lock(card_key)`, which `open_terminal` takes for runner-root resume tabs, and retry, quick reply and dispatch take for their admission. The retry route reserves the lock synchronously before any tracker update or scheduling, and hands it to the background launch, which keeps it until the attempt ends
- [x] A page reload or socket reconnect does not put card-only terminals into the bottom panel: the server keeps a per-terminal `in_panel` flag (set when opened from the panel or by "Show in panel"); reconnect attaches only `in_panel` terminals, the rest stay in the running-terminals list
- [x] Closing the interactive terminal asks what next — Mark done / Send back to Todo / Leave in review — and records a run-log entry `interactive session ended` with the session id, so the card history shows it
- [x] In review cards whose last assistant message is a question show a "Waiting for you" badge with the first line of that message

#### Decisions
- Quick reply stays headless and reuses retry-with-feedback, so pipelines like `/claudex-loop` keep their recorded attempts; the interactive terminal is for longer back-and-forth or hands-on work.
- The embedded terminal is the same PTY terminal object the bottom panel uses (one process per session; the bottom panel can attach a second xterm to the same `term_id` with the existing replay-on-attach). Attaching is on demand only: nothing in the bottom panel opens automatically (user, 2026-10-15).
- The C live/replay run tab follows the same rule: opened from a card it shows in the card's Terminal tab, not in the bottom panel, unless the user asks.
- "Waiting for you" uses the last assistant text: it ends with a question mark (ASCII or full-width) or matches an approval phrasing list kept in one place (ponytail: a heuristic; a structured "needs-input" marker from the agent can replace it).

#### Progress Checklist
- [x] Test: Terminal tab defaults (In review / running), pinned last message, "Waiting for you" detection on sample messages (EN/ZH, question vs statement)
- [x] Test: quick reply calls the retry path with the reply and the same session; refused (409, no attempt, no tracker change) while an interactive tab holds the lock, for a project card, a Linear runner-root card and a dashboard `/run` card
- [x] Test: card key — all attempts of one `/run` task share one lock (an interactive tab on attempt 1 blocks a retry of attempt 2); two unrelated `/run` tasks do not block each other
- [x] Test: strict continuation — a quick reply whose resume fails is recorded as an error and launches no fresh session; a card without a resumable session is refused; a scheduled-entrypoint skill still resumes
- [x] Test: reconnect (`term_list` on `connect`) attaches only `in_panel` terminals; a card-only terminal stays out of the tab strip after reload
- [x] Test: closing the interactive terminal records `interactive session ended` and applies the chosen next state
- [x] Test: opening a card's terminal (live view or interactive) adds nothing to the bottom panel's tab strip and does not expand it; "Show in panel" attaches the same `term_id` there; closing the detail view leaves the session running
- [x] Implement the Terminal tab, pinned message, quick reply, embedded interactive terminal, close prompt and badge
- [x] Manual check: a `/claudex-loop` run stopped for sign-off is answered once by quick reply and once interactively (isolated runner, fake agent ending with "Shall I start the build?": answered by quick reply and in an embedded interactive session)

## D. "Baseline" becomes "Run tests"

### Goal
"Baseline" runs the project's own `verify` command (its existing tests) in a fresh worktree of HEAD with seeds, so a project's tests are known to pass in the runner's environment before agents change anything. The label does not say that. User question, 2026-10-15.

### Acceptance criteria
- [x] The project-head button reads "Run tests"; its tooltip shows the exact command and "on a clean copy of HEAD"
- [x] The inline result line reads "tests: pass / fail · exit N · T s" instead of "baseline: …"
- [x] Projects without `verify` still show no button; the API route and its behaviour are unchanged (condition unchanged: `(p.entry || {}).verify`)

### Progress Checklist
- [x] Implement the label, tooltip and result wording in `index.html`
- [x] Manual check: the button and result on a project with `verify`, absent on one without (isolated runner: "Run tests" + "tests: pass · exit 0 · 0 s"; the absent case is the unchanged condition)

## E. Browse a project's files from the Projects panel

### Goal
Opening a project in the Projects panel should let the user look at its folder the way they would in an editor: a tree they can expand, and a quick look at a file. Today an opened project shows only its sessions. User request, 2026-10-15.

### Acceptance criteria
- [x] An opened project shows two tabs: "Sessions" (today's list) and "Files"; the choice is remembered per project in the browser
- [x] "Files" shows the project's main checkout as a tree: folders first, then files, alphabetical; folders expand on click and load lazily (one level per request)
- [x] What is listed follows git: tracked files and untracked-but-not-ignored files; gitignored folders (e.g. `data/`, `results/`) appear once, greyed and marked "ignored", and are not expanded; `.git/` never appears
- [x] A worktree switcher lists the main checkout and each agent worktree of the project (`agent/<id>`), so the user can browse what an agent changed; changed/untracked files are marked (git status letter)
- [x] Clicking a file opens a read-only preview: text files up to 200 KB with line numbers; larger or binary files show size and type only; images are not rendered
- [x] "Reveal in Finder" opens the folder or file in Finder (macOS `open -R`) (route test with `open -R` stubbed; not clicked in the browser check to avoid opening Finder)
- [x] Nothing is written; every path is checked to resolve inside the chosen checkout (no `..`, no symlink that escapes); a refused path returns 400

### Decisions
- Listing comes from git, not a raw directory walk: `git ls-files --cached --others --exclude-standard -z` for the folder plus `git status --porcelain -z` for marks, through the hardened, bounded `projects._git` (confined for confidential projects), with `GIT_OPTIONAL_LOCKS=0` so `git status` never refreshes the index or contends with an agent's git operations. Ignored folders come from `git check-ignore` on the folder's direct children.
- Confidential projects are browsable here too: the dashboard is local-only and nothing leaves the machine; previews never go to logs, run records or Linear.
- Read-only by design: no edit, rename or delete in this view (the agent or the user's editor does that).

### Approach
- [x] `projects.list_dir(project, worktree, rel)`: one level of entries `{name, kind: dir|file, size, status, ignored}` with the git sources above; refuses paths outside the checkout
- [x] `projects.read_file(project, worktree, rel, limit=200_000)`: `{text | null, size, binary, truncated}`
- [x] Routes: `GET /api/projects/<key>/tree?wt=<id|main>&path=<rel>`, `GET /api/projects/<key>/file?wt=…&path=…`, `POST /api/projects/<key>/reveal` (gated like every mutating request; runs `open -R` on the resolved path)
- [x] UI: Sessions/Files tabs in the opened project, lazy tree, worktree switcher, preview pane, "Reveal in Finder"

### Non-goals
- Editing, creating or deleting files; full-text search; image or PDF rendering; diff view (a later step can add a per-worktree diff against its base)

### Risks
- Very large repos: one level per request and a 2,000-entry cap per folder (rest summarised as "… N more")
- macOS privacy: the runner (launchd) already reads these folders; `open -R` runs as the user

### Progress Checklist
- [x] Test: `list_dir` lists tracked + untracked, marks ignored folders without listing them, hides `.git`, sorts folders first, caps at 2,000
- [x] Test: status marks for a modified and an untracked file in an agent worktree; the worktree's index file (bytes and mtime) is unchanged after listing it, even with a stat-dirty file
- [x] Test: `..`, an absolute path and an escaping symlink are refused; a symlink inside the checkout is listed but not followed out
- [x] Test: `read_file` returns text with truncation at the limit, and only size/type for a binary file
- [x] Test: routes need the token; `reveal` is gated by maintenance
- [x] Implement helpers, routes and the Files tab
- [x] Manual check: browse a project's main checkout and an agent worktree, preview a file, reveal in Finder (isolated runner: main checkout + agent/LOC-1 browsed, file previewed; Reveal covered by the route test)

## Shared checklist
- [x] Codex plan review returns APPROVED (round 5 after the post-approval C0 change, plan sha256 04f33a95…; see review log)
- [x] Proof: `.venv/bin/python -m pytest tests/` passes (575 passed, 2026-10-16)
- [x] Fresh cross-provider (Codex) build inspection returns no unresolved material findings — Codex inspection 37 on `8095cc2`: APPROVED, no findings, assurance cross_provider (`/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/43734fe6-827b-4456-8612-0540ddad69af/scratchpad/claudex/i37/claudex-wuobz0i5/result.json`); full suite 588 passed
