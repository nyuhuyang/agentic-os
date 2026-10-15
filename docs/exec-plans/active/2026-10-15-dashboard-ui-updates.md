---
status: in-progress
created: 2026-10-15
---

# Dashboard UI updates

Two dashboard changes requested on 2026-10-15, kept in one plan (user: "these are all UI changes"):
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
- [ ] Renaming a Claude session shows the new title in the panel and in `claude --resume`; renaming a Codex session shows it in the panel and in `codex resume`
- [ ] Removing a Codex session archives it (`threads.archived = 1`, `archived_at` set): gone from the panel and from `codex resume`, restorable by un-archiving
- [ ] Removing a Claude session moves its transcript (and its same-named sidecar folder, if any) to `~/.agentic-os/session-trash/<slug>/`: gone from the panel and from `claude --resume`; restoring is moving it back
- [ ] Remove asks for confirmation naming the session title; both actions are refused for a session that is live (running in a dashboard tab, a running job, or a transcript written in the last 2 minutes)
- [ ] Only sessions of a registered project are touched: the session's cwd must be under that project's path, and the file/row must resolve inside `~/.claude/projects` / `~/.codex`
- [ ] A failed write leaves the session exactly as it was (no half-written transcript, no partial DB update)

### Decisions
- User authorization (2026-10-15): the dashboard may write to `~/.claude` and `~/.codex` for these two actions only. Everything else there stays read-only.
- Claude rename uses the CLI's own record: append `{"type":"custom-title","customTitle":<title>,"sessionId":<id>}` to the transcript (the shape `/rename` writes, verified in Claude Code 2.1.300); the reader already takes the last `custom-title`.
- Codex rename sets `threads.name`; the reader already prefers `name`.
- Remove is never a hard delete: Codex has native archiving; Claude has none, so the transcript moves to a trash folder outside `~/.claude`.
- Titles: plain text, trimmed, 1–200 characters, no control characters.

### Approach
#### Backend (runner/projects.py, runner/app.py)
- [ ] `session_target(project, agent, id)`: resolve a session of this project (re-reads the session readers; refuses unknown ids, ids with path characters, cwd outside the project, files outside the stores)
- [ ] `rename_session(project, agent, id, title)`: Claude → append the `custom-title` line with `O_APPEND` (one write, newline-terminated); Codex → `UPDATE threads SET name = ? WHERE id = ?` in one transaction (sqlite timeout 5 s)
- [ ] `remove_session(project, agent, id)`: Claude → `os.rename` the transcript (and `<id>/` sidecar folder if present) into `~/.agentic-os/session-trash/<slug>/`, refusing if the destination exists; Codex → `UPDATE threads SET archived = 1, archived_at = <now> WHERE id = ? AND archived = 0`
- [ ] Live check: refuse when a dashboard terminal resumes this session id, when a running job's `agent_session_id` is this id, or when the transcript/rollout changed in the last 2 minutes
- [ ] Routes: `POST /api/projects/<key>/sessions/<agent>/<id>/rename` `{title}` and `POST …/remove`; both go through the maintenance request gate; 400 on validation, 409 on live/busy, 404 on unknown

#### UI (runner/templates/index.html)
- [ ] Session row: "Rename" (inline prompt prefilled with the current title) and "Remove" (confirm naming the title); the list refreshes after success; errors shown inline

#### Docs
- [ ] Note the two write exceptions to the read-only rule in the session-readers comment in `projects.py`

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
- [ ] Test: Claude rename appends exactly one well-formed `custom-title` line and the panel shows it; Codex rename updates `name`
- [ ] Test: Claude remove moves transcript + sidecar to the trash and the panel drops it; destination clash refused; Codex remove archives and the panel drops it
- [ ] Test: refusals — live session (tab, job, fresh file), foreign project, path-like id, bad title, unknown id; nothing changes
- [ ] Test: routes are gated by maintenance (409) and need the request token
- [ ] Implement backend helpers and routes
- [ ] Implement UI buttons
- [ ] Manual browser check on a throwaway session; native pickers confirm

## B. Pick a project when creating a task

### Goal
The new-task form (job board "+" / Todo) gets a Project selector listing the registered projects. The chosen project decides where the task runs: its dispatch goes to a worktree of that project, exactly like a Linear ticket labelled `project:<key>` today. If the user picks nothing, the task belongs to `agentic-os`. User request, 2026-10-15.

### Acceptance criteria
- [ ] The new-task form shows a Project selector with every registered (parseable) project; `agentic-os` is preselected when registered
- [ ] Creating a task with a project stores `project:<key>` as a label on the local task and on the Linear issue, and its dispatch runs in a worktree of that project on `agent/<id>`
- [ ] Creating a task without choosing uses `agentic-os`; if `agentic-os` is not registered, the task is created without a project and the form says it will run at the runner root (today's behaviour)
- [ ] A task dispatched before its Linear copy exists (local-first) already carries the project, so it never falls back to the runner root
- [ ] An unknown or broken project key is refused at creation (400) with nothing created
- [ ] Existing tasks without a project keep today's behaviour

### Decisions
- The project travels as the existing `project:<key>` label, so dispatch, retry and the durable binding need no new path (`project_runs.project_key_from_labels`, `_dispatch_issue`).
- The local tracker gains a `labels` list on each task (default empty) and the normalized issue exposes it; old task files without the field read as `[]`.
- Linear: the label is looked up by name (`issueLabels(filter: {name: {eq}})`), created in the team when missing (`issueLabelCreate`), and attached at create (`issueCreate.labelIds`); the background create already runs there.
- Default `agentic-os` is the registry key, resolved at form-load time from `/api/projects`; the server applies the same default when the request omits `project`.

### Approach
- [ ] `local_tracker.create_issue(..., labels=None)` stores `labels`; `_normalize` / `fetch_issue(s)` return it
- [ ] `POST /api/linear/issues` accepts `project` (key or empty): validate against the registry (refuse unknown/broken), default to `agentic-os` when registered, pass `labels=["project:<key>"]` to the local create and to the background Linear create
- [ ] `LinearClient`: `ensure_label(team_id, name)` and `create_issue(..., label_ids=[...])`
- [ ] UI: Project `<select>` in the new-task form (registered keys from `/api/projects`, `agentic-os` preselected, "No project (runner root)" as the last option); the draft keeps the choice
- [ ] The board card shows the task's project as a small badge

### Non-goals
- Changing the project of an existing task (re-labelling a bound ticket conflicts with its durable binding)
- Creating a project from the task form (use "+ Project")

### Risks
- A task created under `agentic-os` now runs in an `agentic-os` worktree, not in the runner's own checkout; tasks that relied on the runner root (e.g. editing `state/`) need "No project"
- Label creation needs the Linear key's write scope (already used for comments and issue creation)

### Verification
- Proof: `.venv/bin/python -m pytest tests/` passes
- Manual: create one task with a project, one with the default, one with "No project"; dispatch each and check the worktree/branch (or runner root) and the Linear label

### Progress Checklist
- [ ] Test: local task stores and returns `labels`; an old task file without the field reads as `[]`
- [ ] Test: create with `project` → label on the local task; omitted → `agentic-os` when registered, none when not; unknown key → 400, nothing created
- [ ] Test: a local-first task dispatched before its Linear sync runs in the chosen project's worktree
- [ ] Test: `ensure_label` reuses an existing label and creates a missing one; `create_issue` sends `labelIds`
- [ ] Implement tracker labels, route, Linear client, UI selector and card badge
- [ ] Manual check of the three creation cases, including the Linear label

## C. Live terminal view from any board card

### Goal
The terminal panel at the bottom stays as it is. Any card in Backlog, Todo, In progress, In review or Done that has a session gets a "Terminal" action that opens a tab in that panel showing the session live — what the agent is doing as it happens, not the after-the-fact Output / Log / Error panes. User request, 2026-10-15.

### Acceptance criteria
- [ ] Every card with a running job or a recorded session shows a "Terminal" action on the card and in its detail view, in all five columns; cards with neither show nothing
- [ ] Running job (any path: dashboard `/run`, Linear dispatch, retry/rework, project dispatch): the tab streams the agent's events in real time — assistant text, each tool call with its arguments, tool results (truncated), errors — as terminal lines, starting with what was already emitted
- [ ] Finished job with a resumable session: the tab first replays the last run's events (from the stream log on disk, so it works after a runner restart), then offers "Resume here", which opens the interactive `claude --resume` / `codex resume` in the run's own folder (worktree or runner root), using the existing resume-tab rules (ticket lock, confidential policy)
- [ ] A card with several attempts lets the user pick the attempt; the latest is the default
- [ ] Opening the same card twice focuses the existing tab
- [ ] Confidential runs show their live view only in the dashboard (never sent to Linear), same as the run tab today

### Decisions
- Agents run headless (`-p` / `exec --json`), so there is no TTY to mirror while they run; "live terminal" means rendering their event stream as it arrives. Interactive control is the resume tab once the run has ended.
- One event source for all runs: the existing `project_runs.RUN_EVENTS` ring and `run_event` socket event, now fed by every stream reader (`_stream_claude_run`, `_stream_text_run`, `_stream_dsh_run`, project `run_agent`), not only project dispatch.
- Replay after the run reads the run's stream log (`outputs/logs/<run>_stream.jsonl` or the text stream) through the same renderer, so live and replay look identical.

### Approach
- [ ] `render_event(agent, raw) -> list[str]`: one renderer from Claude stream-json / Codex JSON / dsh / plain text to terminal lines (ANSI-dim tool results, colored errors), shared by live and replay
- [ ] Every stream reader pushes rendered lines into `RUN_EVENTS[run_id]` and emits `run_event`
- [ ] `GET /api/runs/<id>/events` replays from the stream log when the ring is empty (finished or after restart) and reports `resume_eligible` for every path, not only project runs
- [ ] Board card + detail view: "Terminal" action (attempt picker when there are several); opens `openRunTab`, which on finish shows "Resume here"
- [ ] The existing project-only "▤ run tab" badge becomes this action

### Non-goals
- Typing into a running headless agent (not possible; resume after it ends)
- Changing the terminal panel layout

### Risks
- Very chatty runs: the ring stays bounded (existing `EventRing` limit); replay reads the tail of the log, not the whole file

### Verification
- Manual: a running dashboard `/run`, a running Linear dispatch and a finished project ticket each open a live/replay tab from their card; "Resume here" opens an interactive session in the right folder

### Progress Checklist
- [ ] Test: renderer turns sample Claude, Codex, dsh and text events into the expected lines
- [ ] Test: each stream reader feeds the ring and emits `run_event` (non-project and project paths)
- [ ] Test: events endpoint replays from the stream log after the ring is gone, and flags resume for a non-project run
- [ ] Implement renderer, reader hooks, replay, card/detail action and attempt picker
- [ ] Manual check: live view for a running job, replay + "Resume here" for a finished one, from cards in different columns

### C2. Answering a session that stopped for review (e.g. `/claudex-loop` asking for sign-off)
A headless run that ends by asking the user something lands in In review. The user needs to read what it asked, with context, and continue the same session. User idea: an openable terminal inside the card's tab; refined as below.

#### Acceptance criteria
- [ ] The card detail view gains a fourth tab, "Terminal", next to Output / Log / Error; it opens by default when the card is In review or has a running job
- [ ] The Terminal tab shows the C view (live or replayed events) with the run's last assistant message pinned at the top
- [ ] "Quick reply": a text box under the view; sending it continues the same session headless through the existing reply/retry path (`/api/runs/<id>/retry` with `reply`), so the card goes back to In progress and the attempt is logged
- [ ] "Open interactive": starts the interactive `claude --resume` / `codex resume` inside the Terminal tab, in the run's folder (worktree or runner root). The bottom terminal panel does not open, expand or switch to it, and it is not added to the panel's tab strip; the session keeps running in the background when the detail view closes, and appears in the bottom panel only when the user asks ("Show in panel" in the detail tab, or picking it from the panel's list of running terminals)
- [ ] While the interactive terminal is open it holds the ticket lock (existing worktree-tab rule), so quick reply, retry and auto-dispatch for that card are refused with a clear message
- [ ] Closing the interactive terminal asks what next — Mark done / Send back to Todo / Leave in review — and records a run-log entry `interactive session ended` with the session id, so the card history shows it
- [ ] In review cards whose last assistant message is a question show a "Waiting for you" badge with the first line of that message

#### Decisions
- Quick reply stays headless and reuses retry-with-feedback, so pipelines like `/claudex-loop` keep their recorded attempts; the interactive terminal is for longer back-and-forth or hands-on work.
- The embedded terminal is the same PTY terminal object the bottom panel uses (one process per session; the bottom panel can attach a second xterm to the same `term_id` with the existing replay-on-attach). Attaching is on demand only: nothing in the bottom panel opens automatically (user, 2026-10-15).
- The C live/replay run tab follows the same rule: opened from a card it shows in the card's Terminal tab, not in the bottom panel, unless the user asks.
- "Waiting for you" uses the last assistant text: it ends with a question mark (ASCII or full-width) or matches an approval phrasing list kept in one place (ponytail: a heuristic; a structured "needs-input" marker from the agent can replace it).

#### Progress Checklist
- [ ] Test: Terminal tab defaults (In review / running), pinned last message, "Waiting for you" detection on sample messages (EN/ZH, question vs statement)
- [ ] Test: quick reply calls the retry path with the reply and the same session; refused while an interactive tab holds the ticket lock
- [ ] Test: closing the interactive terminal records `interactive session ended` and applies the chosen next state
- [ ] Test: opening a card's terminal (live view or interactive) adds nothing to the bottom panel's tab strip and does not expand it; "Show in panel" attaches the same `term_id` there; closing the detail view leaves the session running
- [ ] Implement the Terminal tab, pinned message, quick reply, embedded interactive terminal, close prompt and badge
- [ ] Manual check: a `/claudex-loop` run stopped for sign-off is answered once by quick reply and once interactively

## D. "Baseline" becomes "Run tests"

### Goal
"Baseline" runs the project's own `verify` command (its existing tests) in a fresh worktree of HEAD with seeds, so a project's tests are known to pass in the runner's environment before agents change anything. The label does not say that. User question, 2026-10-15.

### Acceptance criteria
- [ ] The project-head button reads "Run tests"; its tooltip shows the exact command and "on a clean copy of HEAD"
- [ ] The inline result line reads "tests: pass / fail · exit N · T s" instead of "baseline: …"
- [ ] Projects without `verify` still show no button; the API route and its behaviour are unchanged

### Progress Checklist
- [ ] Implement the label, tooltip and result wording in `index.html`
- [ ] Manual check: the button and result on a project with `verify`, absent on one without

## E. Browse a project's files from the Projects panel

### Goal
Opening a project in the Projects panel should let the user look at its folder the way they would in an editor: a tree they can expand, and a quick look at a file. Today an opened project shows only its sessions. User request, 2026-10-15.

### Acceptance criteria
- [ ] An opened project shows two tabs: "Sessions" (today's list) and "Files"; the choice is remembered per project in the browser
- [ ] "Files" shows the project's main checkout as a tree: folders first, then files, alphabetical; folders expand on click and load lazily (one level per request)
- [ ] What is listed follows git: tracked files and untracked-but-not-ignored files; gitignored folders (e.g. `data/`, `results/`) appear once, greyed and marked "ignored", and are not expanded; `.git/` never appears
- [ ] A worktree switcher lists the main checkout and each agent worktree of the project (`agent/<id>`), so the user can browse what an agent changed; changed/untracked files are marked (git status letter)
- [ ] Clicking a file opens a read-only preview: text files up to 200 KB with line numbers; larger or binary files show size and type only; images are not rendered
- [ ] "Reveal in Finder" opens the folder or file in Finder (macOS `open -R`)
- [ ] Nothing is written; every path is checked to resolve inside the chosen checkout (no `..`, no symlink that escapes); a refused path returns 400

### Decisions
- Listing comes from git, not a raw directory walk: `git ls-files --cached --others --exclude-standard -z` for the folder plus `git status --porcelain -z` for marks, through the hardened, bounded `projects._git` (confined for confidential projects). Ignored folders come from `git check-ignore` on the folder's direct children.
- Confidential projects are browsable here too: the dashboard is local-only and nothing leaves the machine; previews never go to logs, run records or Linear.
- Read-only by design: no edit, rename or delete in this view (the agent or the user's editor does that).

### Approach
- [ ] `projects.list_dir(project, worktree, rel)`: one level of entries `{name, kind: dir|file, size, status, ignored}` with the git sources above; refuses paths outside the checkout
- [ ] `projects.read_file(project, worktree, rel, limit=200_000)`: `{text | null, size, binary, truncated}`
- [ ] Routes: `GET /api/projects/<key>/tree?wt=<id|main>&path=<rel>`, `GET /api/projects/<key>/file?wt=…&path=…`, `POST /api/projects/<key>/reveal` (gated like every mutating request; runs `open -R` on the resolved path)
- [ ] UI: Sessions/Files tabs in the opened project, lazy tree, worktree switcher, preview pane, "Reveal in Finder"

### Non-goals
- Editing, creating or deleting files; full-text search; image or PDF rendering; diff view (a later step can add a per-worktree diff against its base)

### Risks
- Very large repos: one level per request and a 2,000-entry cap per folder (rest summarised as "… N more")
- macOS privacy: the runner (launchd) already reads these folders; `open -R` runs as the user

### Progress Checklist
- [ ] Test: `list_dir` lists tracked + untracked, marks ignored folders without listing them, hides `.git`, sorts folders first, caps at 2,000
- [ ] Test: status marks for a modified and an untracked file in an agent worktree
- [ ] Test: `..`, an absolute path and an escaping symlink are refused; a symlink inside the checkout is listed but not followed out
- [ ] Test: `read_file` returns text with truncation at the limit, and only size/type for a binary file
- [ ] Test: routes need the token; `reveal` is gated by maintenance
- [ ] Implement helpers, routes and the Files tab
- [ ] Manual check: browse a project's main checkout and an agent worktree, preview a file, reveal in Finder

## Shared checklist
- [ ] Codex plan review returns APPROVED
- [ ] Proof: `.venv/bin/python -m pytest tests/` passes
- [ ] Fresh cross-provider (Codex) build inspection returns no unresolved material findings
