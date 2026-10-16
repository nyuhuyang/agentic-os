# Review log: 2026-10-16-session-to-board

- Host: claude (Claude Code, Opus 5.5). Plan reviewer: **DeepSeek** (`dsh --profile headless`, `DSH_PERMISSION_MODE=read-only`). The user asked for it: "这些很重要的改动，需要仔细用deepseek审阅". This is a third-party review: it is not a cross-provider claudex approval, and the claudex runner does not drive it.
- Scope: plan and review. Building needs the user's go-ahead.
- Rounds: up to 20. Each run fingerprints the checkout before and after (git diff + status + untracked contents) to show that the reviewer changed nothing.

## Plan review round 1 (DeepSeek)
- Plan SHA256 reviewed: 356db117a4dde39ab6f0fa229e739a33605015d2e966243e0a286823ec79f5de
- Output: `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/stb/review1.out` (JSON repaired: the last array lacked its closing `]`; parsed copy `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/stb/review1.json`)
- Fingerprint before `d35145a0a3ae7530680beabd6ea2e47a7c697b8d93c7aa9fa887d38b60067581`, after `30b5385250c70b31a7a32493dd8bd3cf084f740e29f0e5c43ded6b6c77f22bd3`. They differ because another session committed `832dabb` (Run engine: whitespace-only stderr…; dashboard review log, runner/app.py, tests/test_run_engine.py) at 13:14 during the review. That commit is not the reviewer's: `git status` afterwards shows only this plan and its log as untracked.
- Verdict: **REVISE**, 11 findings (3 high, 5 medium, 3 low).

```json
{
 "verdict": "REVISE",
 "summary": "The plan's core idea is sound, but tracing the reply path shows it would (1) run confidential project sessions unsandboxed, (2) leak confidential prompt/output because the plain retry worker never withholds, (3) have no reachable reply UI for the very cards it creates, and (4) leave resume_session on records after a drag/reset. Several concurrency and spec gaps follow. Material fixes are needed before build.",
 "findings": [
  {
   "id": "STB-001",
   "severity": "high",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §3; runner/app.py:2311-2320; runner/project_runs.py:77-98",
   "evidence": "Plan §3 says a session-card reply 'does not use the project worktree branch' and runs `_build_resume_cmd`, which is built from `_ai_cli` (claude `--permission-mode bypassPermissions`; codex `--dangerously-bypass-approvals-and-sandbox --json`). For a confidential project, normal dispatch uses `project_runs.agent_cli`, which returns claude with `--settings <sandbox>` / codex `--sandbox workspace-write ... network_access=false`, and refuses dsh. Routing a confidential project session through the plain path therefore executes the agent with no sandbox and also accepts backends the project policy forbids.",
   "fix": "For a project-bound session card build the resume argv on top of `project_runs.agent_cli(project, ...)` (like `_project_cmd`), keep the confidential gate/refusal, and validate the cwd is an allowed project/worktree root; or run project session cards through `_run_project_ticket` with `resume_session`."
  },
  {
   "id": "STB-002",
   "severity": "high",
   "path": "runner/app.py:4355-4366,4377,4390-4393 vs 3262-3265,4199-4203",
   "evidence": "The plain retry worker writes `prompt=prompt, output=output` directly (`_do_retry_attempts` success, timeout and error branches). Only the project path (`_run_project_ticket_locked`) and `_start_failed` apply `_records_unsafe()` withholding. Since the plan deliberately routes project (and possibly confidential) session replies through the plain worker, a confidential reply's feedback text and agent output are written to RUN_LOG/OUTPUTS even when the record location is unsafe, contradicting plan §3 ('Confidential runs follow `_records_unsafe` for prompt and output text').",
   "fix": "Apply the same `_records_unsafe()` withholding to the session-resume records in `_do_retry_attempts` (normal, timeout, error), or funnel these runs through a writer that already withholds."
  },
  {
   "id": "STB-003",
   "severity": "high",
   "path": "runner/templates/index.html:3029,3034,3043",
   "evidence": "`openDetailModal` sets `canRetry = !!r.linear_issue_id && ...` (line 3029), hides `#detail-retry-group` unless that is true, shows `#detail-reply-section` only when `r.linear_issue_id` (line 3043), and the dispatch group also requires `linear_issue_id` (line 3034). The plan's to-board 'No card' record (plan §2) has `project_key` but no `linear_issue_id`; after Resume the board state is `todo`, so `canRetry` is false anyway. The result: `openDetailModal` hides `#detail-reply-input`, so the acceptance criteria 'detail opens with the reply box focused' and 'replying from Todo continues the same session' cannot be exercised.",
   "fix": "Show the reply box and retry controls for session cards based on `resume_session`/`agent_session_id` (not `linear_issue_id`), and allow them in the Todo column; state this UI change explicitly in §5/§6."
  },
  {
   "id": "STB-004",
   "severity": "medium",
   "path": "runner/app.py:3977,4018; runner/templates/index.html:1869-1873,4551-4552",
   "evidence": "`api_run_set_status` writes `record = {**original, 'status': new_status}`, copying every field, and the drag handler PATCHes `{status: col.dropStatus}` (todo for a drop into Todo); `api_run_restore` copies similarly. So once Resume writes a Todo record with `resume_session`, any later status change (drag/reset to Todo, Backlog, etc.) carries `resume_session` forward and the next retry resumes the old session. This directly breaks the acceptance criterion 'A card moved to Todo the existing way still starts fresh' and the checklist test 'a drag/reset to Todo after Resume clears the intent'.",
   "fix": "Strip `resume_session` in `api_run_set_status` (and `api_run_restore`) when building the new record, or scope the intent to a single writer: have retry treat `resume_session` as active only when the latest record was written by the to-board route (e.g. a one-shot marker consumed at dispatch)."
  },
  {
   "id": "STB-005",
   "severity": "medium",
   "path": "runner/app.py:3750-3767,4179; plan §4",
   "evidence": "`_claim_session` records `(agent, sid)` in `_SESSION_CLAIMS`, and `_live_session_ids()` returns `set(_SESSION_CLAIMS.values())`. The retry route calls `_claim_session` at line 4179 before any launch. Plan §4 makes `session_in_use` (which uses `_live_session_ids()`) the gate for 'retry for a session card without `confirm_in_use`'. If the check is placed after the existing claim (the natural location), every session reply sees its own claim and returns 409 even with nothing else using the session.",
   "fix": "Call `session_in_use` before `_claim_session`, or pass the new `run_id` and exclude that run's claim from the live set for the self-check."
  },
  {
   "id": "STB-006",
   "severity": "medium",
   "path": "runner/templates/index.html:4585-4599; runner/projects.py:1654-1662; plan §4",
   "evidence": "`_cardTermQuickReply` posts `{reply, strict: true}` and only prints `r.data.error`; it has no confirm/resend path. Plan §4 makes any session retry without `confirm_in_use: true` return 409. `check_session_idle` treats a transcript written in the last 120s as busy, and any just-finished run satisfies that, so quick reply (the primary C2 flow) would fail for two minutes after every run and never offer the required confirmation.",
   "fix": "Give quick reply the same confirm-once flow as the card reply, or exempt the card's own just-finished session from the in-use gate while keeping the external-process checks."
  },
  {
   "id": "STB-007",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §3; runner/app.py:4214-4251,3130-3230",
   "evidence": "The plan explicitly bypasses the project branch. That branch runs `_run_project_ticket` -> `_run_project_ticket_locked`, which supplies the project exec env, worktree handling, runner commit, verify/seed checks, durable binding and confidential tracker/comment policy. The plain worker uses `_registry_exec_env` and none of those. A project session reply therefore skips commit/verify and the documented project-run contract (AGENTS.md: a `project:<key>` ticket runs in `~/.agentic-os/worktrees/<key>/<id>`), and the plan does not call out the loss.",
   "fix": "Either route project session cards through the project helper with the recorded session cwd/resume data, or state explicitly in the plan which project guarantees (commit, verify, binding, tracker push) are intentionally dropped for session replies and why."
  },
  {
   "id": "STB-008",
   "severity": "medium",
   "path": "runner/app.py:3753-3756,3154; plan §2",
   "evidence": "`_claim_session` registers `_SESSION_CLAIMS` synchronously and releases the session lock, while the project worker publishes `_running_jobs[run_id]` only later inside `_run_project_ticket_locked`. to-board's 'Running' check uses only `_running_jobs` or latest status `running` (plan §2), so during that launch window it can append a Todo/resume record for a card that is already starting, or create a second card while a resume is in flight.",
   "fix": "Base the to-board running check on `_live_session_ids()`/`session_in_use()` (which include `_SESSION_CLAIMS`), not only `_running_jobs` and the latest record status."
  },
  {
   "id": "STB-009",
   "severity": "low",
   "path": "runner/app.py:3993-3994; plan §2",
   "evidence": "The found-card branch appends a `todo` record 'as PATCH does' but never calls `_push_linear_state_async`. `api_run_set_status` pushes the new state for a Linear-linked run (line 3993-3994). A found card that carries `linear_issue_id` (a project ticket) would show Todo locally while the Linear issue keeps its old state, so Resume diverges from a drag/reset.",
   "fix": "Push the todo state for Linear-linked found cards, or refuse/adjust to-board for Linear-linked cards and say so in the plan."
  },
  {
   "id": "STB-010",
   "severity": "low",
   "path": "runner/modules/pty/__init__.py:317-422; runner/templates/index.html:2901,2932-2969; plan §5",
   "evidence": "Plan §5 sends `term_open {kind:'shell', cwd_for:<run_id or linear-id>}` and claims every card, including Linear cards with no run, gets a working Open terminal. `open_terminal` resolves shell cwd only from `project_key`/`ticket`/record and otherwise falls back to `ROOT`; there is no path from a raw Linear issue id to a project/worktree. `openDetailModal` also hides the Terminal tab and returns before `_cardTermBind` for `linear-*` with no `latest_run_id` (lines 2901, 2932-2969).",
   "fix": "Specify server-side resolution for linear cards (durable binding plus `project:<key>` labels / issue identifier) and add the `_cardTermBind`/tab-enable step in the linear no-run branch; otherwise scope the acceptance criterion to run cards."
  },
  {
   "id": "STB-011",
   "severity": "low",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §3; docs/exec-plans/active/2026-10-15-dashboard-ui-updates.md:148-172; runner/app.py:2604,4301-4311",
   "evidence": "§3 says to give `_dispatch_cmd` a `cwd` parameter, but also says 'If the dashboard plan's C0 has landed by build time, this path calls it instead of extending `_dispatch_cmd`.' The dashboard plan's C0 items are all checked complete, and `run_agent_process(run_id, cmd, ..., cwd=...)` already exists and is the only launch used by `_dispatch_cmd`. The two instructions cannot both be followed.",
   "fix": "State one path: call `run_agent_process(new_run_id, cmd, stream=..., env=..., cwd=target['cwd'])` directly for the session resume, and drop the 'extend `_dispatch_cmd`' wording."
  }
 ],
 "coverage": [
  "Verified the plan SHA256 (356db117…) before review.",
  "Read the full new plan and both prior plans (dashboard-ui-updates, runner-write-safety), including the C0 contract and the project/confidential dispatch rules.",
  "runner/app.py: traced `_get_task_agent_lock`, `_records_unsafe`, `_build_resume_cmd`, `_ai_cli`, `_live_session_ids`/`_SESSION_CLAIMS`, `_claim_session`, `run_agent_process`, `_run_project_ticket`/`_run_project_ticket_locked`, `api_run_retry` (project branch, `_dispatch_cmd`, `_do_retry_attempts`, `_start_failed`), `api_run_detail`, `api_run_set_status`, `api_run_restore`, `api_run_events`, `card_run_for_session`, `_write_run_log`, the token gate and the maintenance gate.",
  "runner/projects.py: `session_target`, `session_lock`, `check_session_idle`, `_session_roots`, `project_sessions`, and the rename/remove writers.",
  "runner/project_runs.py: `agent_cli` sandbox/confidential argv and `tracker_comment` policy.",
  "runner/modules/pty/__init__.py: `open_terminal` shell/resume branches, Terminal.info fields (`session_id`, `card_key`, `in_panel`), and the resume admission/lock behavior.",
  "runner/templates/index.html: `_sessionRow`, project-row Open terminal, detail Terminal markup, `openDetailModal` gating, `retryRun`/`retryFromDetail`, board drag PATCH, `_cardTermBind/Open/Load/QuickReply/Next`, `openShellTab`/`openResumeTab`."
 ],
 "limitations": [
  "Read-only review; I did not edit files, run pytest, launch the app, or exercise a browser, so no runtime behavior was executed or verified.",
  "I inspected the cited functions and their callers, not every line of the ~12k-line files; findings are grounded in the referenced ranges.",
  "I did not read the prior plan's review log or the test files, so test coverage claims in the plan were not independently validated.",
  "`ps`-based detection, sandbox behavior, and macOS process semantics were reasoned from code, not executed."
 ]
}```

### Dispositions
Round 1 dispositions (host: Claude). All 11 findings checked against the code and accepted; the plan was rewritten.
- STB-001/007 (high/medium): a project ticket whose session sits in its own worktree goes through `_run_project_ticket(..., resume_session, reuse_only)`, which keeps the sandbox, commit, verify, binding and tracker rules. Every other session card runs through `run_agent_process` in the session cwd with argv built on `project_runs.agent_cli` (confidential → sandbox flags; dsh refused). The plan states that the runner neither commits nor verifies in that folder.
- STB-002 (high): records on the session path (normal, timeout, error) go through one helper that applies `_records_unsafe()` withholding for confidential bindings.
- STB-003 (high): the reply section and send controls show for session cards (`resume_session`, or `agent_session_id` plus `source == "session"`); `canRetry` allows `todo` for them.
- STB-004 (medium): `api_run_set_status` and `api_run_restore` strip `resume_session`, so the intent is one-shot and only to-board writes it.
- STB-005 (medium): the in-use check runs before `_claim_session` and excludes this run's own claim.
- STB-006 (medium): a fresh write counts only if it lands after the card's last run ended plus 5 s. Quick reply gets the same confirm-once flow as the card reply.
- STB-008 (medium): the to-board running check includes `_live_session_ids()` (`_SESSION_CLAIMS`).
- STB-009 (low): a found card moves through the status helper factored out of `api_run_set_status`, which includes the Linear push.
- STB-010 (low): a no-run Linear card resolves its folder through the durable binding, then its `project:<key>` label, then the runner root; its tab is enabled with Open terminal only.
- STB-011 (low): one path only — `run_agent_process` (C0 has landed); the "extend `_dispatch_cmd`" wording is dropped.
- New user constraint, added: the In progress Terminal tab (live view, Show in panel, Open interactive) stays exactly as it is.

## Plan review round 2 (DeepSeek, fresh run with the round-1 dispositions)
- Plan SHA256 reviewed: 4c1d14eab7c2dc5a75a9f0e631299bf8a0c83945cc4d3cff9d5b16adab0c319d
- Output: `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/stb/review2.out` (parsed: `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/stb/review2.json`)
- Fingerprint before `30a063e7d3e088e6c3072f17330593c85cf102cf98394e85c65182b810c280ff`, after `4ecb34585b8595abbc2046e7011f584cf045eb1e79c02febbadb97e5cddb43f8`. HEAD stayed `832dabb`. The difference is the host editing this plan mid-review: the user's §5 removal and the new §7/§8. The reviewer did not cause it; `git status` shows only this plan and its log.
- Verdict: **REVISE**, 9 findings (2 high, 4 medium, 3 low). STB-001..011 confirmed resolved.

```json
{
 "verdict": "REVISE",
 "summary": "The revision resolves round-1 STB-001..STB-011 against the code (project-worktree route, withholding helper, reply-UI condition, field stripping, pre-claim check, freshness window, _live_session_ids, status helper, no-run Linear card, single run_agent_process path), but it introduces/leaves two high defects plus several medium/low edge cases: a no-card session becomes only a run record that the job board never renders, and a confidential generic reply writes the full durable event stream before any withholding. Four medium and three low spec/edge defects also stand.",
 "findings": [
  {
   "id": "STB-012",
   "severity": "high",
   "path": "runner/templates/index.html (refreshJobBoard/_renderBoardItems); plan §2.5 and Non-goals",
   "evidence": "The plan creates the no-card session 'card' as only a run record (run_id/task_id uuid, status todo, skill _prompt, no linear_issue_id) and says 'they are local run cards'. But refreshJobBoard builds the board exclusively from /api/linear/issues (index.html:2674 fetches, 2682-2732 maps only linearIssues into `all`; `_renderBoardItems(all)` at 2732/2748 never receives a raw run record). A record with no linear_issue_id therefore never appears in any column, so acceptance 'Resume on a session with no card creates one Todo card' fails and `_boardItemsByRunId[run_id]` is undefined (so card-level canRetry/quick reply paths lack boardItem).",
   "fix": "Have the to-board 'None' path create a local tracker issue (get_local_tracker().create_issue) and link the run record with that issue id (as the + form does), or extend refreshJobBoard/_renderBoardItems to render local run cards by task_id."
  },
  {
   "id": "STB-013",
   "severity": "high",
   "path": "runner/app.py run_agent_process/_stream_claude_run/_stream_text_run/_stream_dsh_run; plan §3.2 and §3.4",
   "evidence": "The generic session branch runs through run_agent_process. Its readers open `_claude_stream_log_path(run_id)` = RUN_PROGRESS_DIR/<run>_stream.jsonl (app.py:2452-2454) where RUN_PROGRESS_DIR = OUTPUTS_DIR/logs (app.py:143), and write every raw event unconditionally (app.py:2475, 2527; text path 922-928). The project path refuses to launch when `_records_unsafe()` is non-None (app.py:3181-3183 raises). Plan §3.4 only withholds the final normal/timeout/error record; it never gates the launch or the stream log, so for a confidential binding with unsafe record locations (e.g. outputs/ resolves outside the checkout, or its committed .gitignore changed) the confidential agent's full output is still persisted to outputs/logs/.",
   "fix": "For a confidential binding, fail closed before run_agent_process when `_records_unsafe()` is non-None (mirroring `_run_project_ticket_locked`), or make the stream readers write only where `_records_unsafe()` approves."
  },
  {
   "id": "STB-014",
   "severity": "medium",
   "path": "runner/projects.py session_target; plan §2.1, §3.1, §3.2",
   "evidence": "session_target raises `ProjectError(f\"unknown agent {agent!r}\")` for any agent outside ('claude','codex') (projects.py:1614-1615). Both the to-board route (§2.1) and the reply re-resolve (§3.1) call it, so a dsh session card can be neither created nor resumed. Plan §3.2's 'refuse dsh' for confidential projects and its `_project_cmd` dsh flags (claude/codex/dsh resume) are therefore unreachable, and the plan's implication that dsh sessions can be continued on public projects is false.",
   "fix": "State explicitly that session cards are claude/codex only and delete the dsh branch, or add dsh resolution to session_target (projects.py) and the reader so §3.2 is reachable."
  },
  {
   "id": "STB-015",
   "severity": "medium",
   "path": "runner/app.py api_run_retry agent selection; runner/templates/index.html card retry buttons; plan §1, §3.1, §5",
   "evidence": "In retry, `agent = agent_override or ...` and the override is ignored only when `_get_task_agent_lock(task_id)` returns a lock (app.py:4151-4167). A session card in Todo has no lock (`_get_task_agent_lock` returns None at app.py:2675-2676), so a client-sent agent wins. The UI exposes all three agent buttons for a todo card (index.html:2536-2548; `retryRun(run.run_id, key)` at 2552), so a codex session card can be replied to as claude; the plan never says `resume_session.agent` overrides the request, so the reply then fails at session_target (or would run the wrong CLI if the id resolved).",
   "fix": "When resume_session is present, force `agent = resume_session['agent']`, reject/ignore a conflicting body agent, and lock the UI agent buttons to that agent."
  },
  {
   "id": "STB-016",
   "severity": "medium",
   "path": "runner/templates/index.html board card run_id / retryRun; plan §2.3-§2.4",
   "evidence": "The board card's run_id/latest_run_id is the newest attempt (`latest?.run_id` at index.html:2703-2704). Plan §2.3 finds the newest record with agent_session_id == sid (possibly an older attempt) and §2.4 attaches resume_session to the record the helper writes. On a card with a later fresh attempt, attaching to an older attempt means reopening the card from the board uses `boardItem.latest_run_id` in `retryRun` (`targetRunId = boardItem?.latest_run_id || run_id`, index.html:3148), so the reply no longer continues the session; only the immediate Resume-opened detail (run_id returned by to-board) does.",
   "fix": "Write the Todo record and attach resume_session to the card's latest run_id (the record the board shows), or make retryRun prefer the detail/record's resume_session over latest_run_id."
  },
  {
   "id": "STB-017",
   "severity": "medium",
   "path": "runner/app.py record_interactive_ended; plan §2.3",
   "evidence": "record_interactive_ended appends an audit record with `agent_session_id = session_id` and `interactive_ended = True` (app.py:4079-4084). Plan §2.3 searches the newest record whose agent_session_id == sid without excluding such records, so after an interactive session ends the to-board route can select the audit record's run_id; the helper then writes a Todo record for the audit and openDetailModal shows 'interactive session ended' instead of the card. _get_task_agent_lock (app.py:2662) and api_run_history (index.html history path) already skip interactive_ended records.",
   "fix": "Exclude interactive_ended (and archived) records when finding the card, as _get_task_agent_lock does."
  },
  {
   "id": "STB-018",
   "severity": "low",
   "path": "runner/app.py _write_run_log/retry record; plan §3.4, §5",
   "evidence": "Plan §5 shows the reply section when `resume_session` or (`agent_session_id` and `source == 'session'`). _write_run_log builds a fresh record from explicit fields and only carries source through `extra` (app.py:2125-2161); the plan's reply-record list (§3.4: agent_session_id, binding, resume_session cleared) omits source, and the generic retry `_write_run_log` call (app.py:4355-4366) passes no such extra. After the first continuation, a session card with no linear_issue_id has neither resume_session nor source, so #detail-reply-section and detail canRetry (index.html:3029, 3043) hide.",
   "fix": "Carry source: 'session' (with project_key/confidential binding) into the reply record so the card-reply UI survives subsequent attempts."
  },
  {
   "id": "STB-019",
   "severity": "low",
   "path": "plan §4.2; runner/app.py _live_session_ids",
   "evidence": "The plan names `ps -A -o pid=,args=` while requiring 'excluding the runner and its children'; that listing has no ppid, so the runner's own agent process (whose argv contains the session id) cannot be distinguished from an external one. The own-run subtraction only removes one `(agent, sid)` tuple from the `_live_session_ids()` set (app.py:3763-3767), which also masks a second concurrent claimant of the same session.",
   "fix": "List ppid (`ps -A -o pid=,ppid=,args=`) and skip the runner's process tree, and key the own exclusion by run_id rather than by tuple value."
  },
  {
   "id": "STB-020",
   "severity": "low",
   "path": "plan §5 Copy command; runner/modules/pty/__init__.py interactive_resume_argv",
   "evidence": "The plan builds the copied resume command as plain `cd <cwd> && claude --resume <id>` / `codex resume <id>`. For a confidential project the eligible interactive command is interactive_resume_argv, which pins the sandbox via project_runs.agent_cli (pty/__init__.py:287-314). A user copying the plan's command runs the session outside the confidential policy the plan claims to preserve.",
   "fix": "Build the Copy command through interactive_resume_argv (or hide Copy command for confidential bindings)."
  }
 ],
 "coverage": [
  "Verified round-1 dispositions STB-001..STB-011 against the tree: project-worktree branch reuses _run_project_ticket(..., resume_session, reuse_only=True) and _run_project_ticket_locked (app.py:3130-3285) with the sandboxed CLI/commit/verify; the record helper mirrors the withholding in app.py:3262-3268; the reply-section condition matches index.html:3043; api_run_set_status/api_run_restore copy {**original} today (app.py:3977, 4018) so stripping is needed; _claim_session/session_lock ordering (app.py:4178-4181, projects.py:1597-1608); SESSION_FRESH_S=120 (projects.py:1583); _live_session_ids includes _SESSION_CLAIMS (app.py:3763-3767); api_run_set_status pushes Linear for non-archived (app.py:3992-3994); openDetailModal currently hides the terminal tab for linear-* (index.html:2901); run_agent_process is the single non-project engine (app.py:2604-2642) with no _dispatch_cmd change needed.",
  "Read runner/app.py: run_agent_process, _get_task_agent_lock, _project_cmd, _parse_project_output, _records_unsafe, _run_project_ticket(_locked), _build_resume_cmd, _SESSION_CLAIMS/_claim_session/_live_session_ids, api_run_detail, api_run_set_status, api_run_restore, api_run_cancel, record_interactive_ended, api_run_retry (incl. _do_retry_attempts/_dispatch_cmd), api_runs, api_runs_latest_by_issue, maintenance/auth gates.",
  "Read runner/projects.py: session_target, session_lock, check_session_idle, project_sessions, _session_roots, record_location_problem, _ignored_by_committed_rule, create_worktree.",
  "Read runner/modules/pty/__init__.py: open_terminal/term_open, interactive_resume_argv, shell spawning and confidential handling.",
  "Read runner/templates/index.html: _renderProjects/_sessionRow, refreshJobBoard/_renderBoardItems, openDetailModal, retryRun/retryFromDetail, card rendering, _cardTerm* (open/load/quick reply/interactive), term_open usage, project-row handlers.",
  "Read the earlier plans docs/exec-plans/active/2026-10-15-dashboard-ui-updates.md and docs/exec-plans/completed/2026-10-15-runner-write-safety.md; plan sha256 matches the supplied digest."
 ],
 "limitations": [
  "Read-only inspection; no tests were run and I do not claim any pass.",
  "Did not read project_runs.run_agent/spawn, project_runs.confine_for, or all 5,040 lines of index.html; findings about codex `exec ... resume` argv syntax and some UI paths are not exhaustively traced.",
  "Did not inspect git history, branches, or the other session's uncommitted work; conclusions use the working tree at the given plan hash.",
  "Cannot confirm whether a planned-but-unstated UI change would render local run cards, which is why STB-012 is reported at the current tree state."
 ]
}```

### Dispositions
Round 2 dispositions (host: Claude). Every finding was checked against the code.
- STB-012 (high) accepted. Verified: `refreshJobBoard` maps only tracker issues. New §0 says so. §2.5 now creates a tracker issue through the "+"-form path (part B), and the run record is linked to it with `linear_issue_id`.
- STB-013 (high) accepted. A confidential reply outside a ticket worktree refuses before launch when `_records_unsafe()` is non-None, mirroring `_run_project_ticket_locked`. Nothing is launched or streamed.
- STB-014 (medium) accepted. Session cards are claude/codex only; dsh gets no Resume button and the dsh branch is gone.
- STB-015 (medium) accepted. The agent is forced to `resume_session.agent`; a different body agent → 409; the UI shows only that agent.
- STB-016 (medium) accepted. The todo record and the intent go on the issue's latest `run_id`, the run the board shows.
- STB-017 (medium) accepted. Card lookup skips `interactive_ended` and `archived` records.
- STB-018 (low) accepted. Reply records carry `linear_issue_id`, `source` and the binding.
- STB-019 (low) accepted. `ps -A -o pid=,ppid=,args=`, skipping the runner's process tree; own-claim exclusion is keyed by run_id.
- STB-020 (low) N/A. The user removed Copy command / Open terminal from scope ("No，不要在旁边加 … 现在就很好"); the card Terminal tab is unchanged.
- Also changed. Verified: every move to Todo bumps the reset generation (`_tracker_reset_route`, `api_run_set_status`). The intent is now generation-bound: it stores the `gen` that Resume's own move produced, and retry honours it only while `gen == reset_gen.current(issue)`. A later drag to Todo therefore voids it, even though the tracker PATCH writes no run record (§1).
- New sections, all from the user and not reviewed before:
  - §7: a project run that changed nothing gets no verify badge; "no check" turns grey.
  - §8: record the Claude model the CLI reported (init event / `modelUsage`).
  - §9: board-launched headless sessions appear under their project.

## Plan review round 3 (DeepSeek)
- Plan SHA256 reviewed: 30bb85a9b2f41f5ae04bf4dae7abb58841856b8edd302f7cd85962cfd171b834
- Output: `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/stb/review3.out` (parsed: `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/stb/review3.json`)
- Fingerprint before = after `b9a83d2db349a25a16f1cb54d015ab635483965f3aedb53700c5b15699754ba9`: the reviewer changed nothing.
- Verdict: **REVISE**, 8 findings (1 high, 4 medium, 3 low). STB-001..020 confirmed resolved where touched.

```json
{
 "verdict": "REVISE",
 "summary": "The revised plan resolves the round-1/2 points in the places they touched (project-worktree route, withholding helper, field stripping, pre-claim check, freshness window, interactive_ended/archived skip, run-log-based listing). Reviewing the new §0, §7, §8 and §9 against the code found four material defects plus four smaller ones. The no-card path's Linear local-first id is never aliased onto the run record, so the created card is orphaned and retry 409s forever; §7 measures 'changed nothing' against the worktree's fixed base_sha so a question-only run on a ticket with prior commits still gets a badge; §8 names a dead code path and misses the project parser that actually produces the AGE-102 symptom, and its cost claim fails because the observed model is absent from MODEL_PRICES; §2.5 claims confidential title handling that does not exist.",
 "findings": [
  {
   "id": "STB-021",
   "severity": "high",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §2.5; runner/modules/linear/__init__.py:1014-1065,239-245; runner/templates/index.html:2686-2694; runner/app.py:4116-4118",
   "evidence": "With Linear configured, the '+' path the plan reuses is local-first: `_issues_post` creates `local-<hex>`, returns it, and the background `_bg_sync_to_linear` later does `raw.pop(local_id); raw[real_id]=...; issues_cache.pop(local_id); issues_cache[real_id]=n` and only calls `record_id_alias` (consumed by the frontend for STT drafts, not by run records). §2.5 writes the session run record with that local id, but the board joins runs to issues by `linear_issue_id` against the swapped real id (index.html:2686-2694, app.py:3890-3895), so the record never matches a card. `unsynced_local_id` only checks `str(issue_id).startswith('local-')` and the tracker type, so `api_run_retry` (app.py:4116-4118) keeps returning 409 'not synced to Linear yet' after the issue exists. Failure: Linear-configured, no-card Resume creates a card the board cannot link and a reply box that can never send — the acceptance 'visible on the board' and 'Replying from Todo continues the same session' both fail, and §2.5's 'the user resends' is impossible.",
   "fix": "Resolve the local→real alias before writing the run record and make retry/`unsynced_local_id` alias-aware (or rewrite the record's `linear_issue_id` on the sync completion), or bypass local-first for this route (create the Linear issue synchronously) so the record is linked to the id the board lists."
  },
  {
   "id": "STB-022",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §7; runner/project_runs.py:507-527; runner/projects.py:1074,1080-1091",
   "evidence": "`post_run` computes `shortstat` as `git diff --shortstat binding['base_sha'] HEAD`, and `create_worktree` returns the base recorded at worktree creation for every reused run (projects.py:1074). A ticket whose earlier attempt committed work therefore has a non-empty `base_sha..HEAD` even when the current run changed nothing, so the §7 rule ('shortstat empty against base_sha, dirty false, no seeds' → no badge) is false and `verify is None` still yields 'no check' (project_runs.py:526-527). Failure: the exact reported card (Trading '牛熊判断', Done) still shows a red 'verify: no check' on its next question-only attempt whenever the ticket already carries commits.",
   "fix": "Capture the worktree HEAD before the agent starts (a per-run start sha) and judge 'changed nothing' on that range, not on the fixed `base_sha`; keep `base_sha` only for the seed/verify accounting."
  },
  {
   "id": "STB-023",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §8; runner/app.py:2418-2427,2599-2601,2635,2713-2727,3224,3271; outputs/logs/791b6907-8b4c-4c1d-9fb8-6c2de03c4d75_stream.jsonl",
   "evidence": "§8 names `_parse_agent_output` for '--output-format json runs (Linear dispatch)', but `_agent_output_format` returns 'stream-json' for claude (app.py:2599-2601) and `_parse_agent_output` is only ever called with 'codex' (app.py:2635, 2730); its claude branch is unreachable. The AGE-102 case is a project run: `_run_project_ticket_locked` parses via `_parse_project_output` (app.py:3224, 3271), which reads `result.get('model')`. The actual transcript's result event has `model: null` while `modelUsage` carries `claude-opus-5-5[1m]` (and the init event carries it too), so changing only `_stream_claude_run` leaves AGE-102 (and every Linear/project claude run) on the `_agent_model()` Sonnet fallback (app.py:2376).",
   "fix": "Read the model in `_parse_project_output` from the `system/init` event or the `result` event's `modelUsage` first key, in addition to `_stream_claude_run`; delete the `_parse_agent_output` json instruction or state that its claude branch is dead and why it is still being changed."
  },
  {
   "id": "STB-024",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §8; runner/app.py:2098-2102; runner/usage_reader.py:68-75",
   "evidence": "§8 promises 'the observed model goes into `model` and into `_compute_token_cost`', but `_compute_token_cost` looks the model up exactly in `MODEL_PRICES` and falls back to `DEFAULT_PRICE`. `MODEL_PRICES` has no `claude-opus-5-5[1m]` (or `[1m]`-suffixed key), so the observed model is priced at 3.00 — the Sonnet default the §8 problem statement complains about. Failure: after the fix, cards/records show opus but cost is still Sonnet-priced, so the acceptance 'cost uses it' is not met.",
   "fix": "Add/normalize price keys (strip the `[1m]` suffix or match on family/prefix) so the observed model maps to the opus rate, and add a test asserting the cost differs from the Sonnet default for the observed string."
  },
  {
   "id": "STB-025",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §2.5; runner/modules/linear/__init__.py:979-1007,663-676,1252-1253",
   "evidence": "§2.5 says the issue is created 'through the same code path the + new-task form uses ... its existing confidential handling for titles', but `_issues_post` (979-1007) never consults the project's confidentiality: it passes the caller's title straight to `create_issue`/Linear. The only confidential guards are `_is_confidential_issue` for comments/feedback (663-676, 1252-1253). Failure: for a confidential project, the session title (often the transcript's first user message or ai-title) is posted to Linear as the issue title, unlike the template-only tracker policy the plan claims to preserve.",
   "fix": "For a confidential binding, do not send the session title to the tracker (withhold/replace it or keep the card local-only), and drop the claim that the '+' path already handles confidential titles."
  },
  {
   "id": "STB-026",
   "severity": "low",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §2.4,§4.3; runner/app.py:3912-3925; runner/projects.py:1583,1654-1662",
   "evidence": "`session_in_use` takes `own_finished_at` and §4.3 exempts transcript writes before 'the card's latest run ended plus 5 s'. But §2.4 appends its Todo/intent record on the card's latest `run_id`, and `api_run_detail` returns the newest record with that id (app.py:3912-3925) — the to-board record, whose `started_at` is now and `duration_s` is 0. If `own_finished_at` is taken from the record being viewed, the exemption is now+5s and every write in the last 120 s (projects.py:1583, 1661) is ignored, suppressing the warning the acceptance requires; if it is taken from the last real attempt, the plan does not say so.",
   "fix": "Define `own_finished_at` as the end of the card's last real attempt (newest non-to-board record with a real status, `started_at + duration_s`), and add the test that an external writer within 120 s still produces `in_use_elsewhere` on the first reply after Resume."
  },
  {
   "id": "STB-027",
   "severity": "low",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §2.2,§2.6; runner/app.py:3753-3767; runner/projects.py:1597-1608",
   "evidence": "§2.2's running check is step 2 and §2.6 puts the find-and-write under `projects.session_lock` at step 6. `_claim_session` (app.py:3753-3756) takes the same non-blocking `session_lock`, inserts the claim, and releases the lock immediately while the claim persists. If the running check runs before the route acquires the lock, a retry can claim the session in the gap and to-board then appends a Todo/intent for a session already launching — the STB-008 race is not closed by the stated ordering.",
   "fix": "Acquire `projects.session_lock(agent, sid)` first and do the `_live_session_ids()`/`_running_jobs` re-check inside it, then find and write."
  },
  {
   "id": "STB-028",
   "severity": "low",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §9; runner/app.py:3208,3219,3269; runner/projects.py:1417-1446",
   "evidence": "§9 derives the headless id set from `RUN_LOG`, but a project run's record is written only at the end (`_write_run_log` at app.py:3269); while it runs, its session id exists only in `_running_jobs`/`_SESSION_CLAIMS` (app.py:3208, 3219). The user's 'I opened an AGE-102 and should see the new session under Trading' will therefore still be missing while the run is live, and the plan does not state that limitation.",
   "fix": "Include the live session ids (running jobs/claims) in the §9 id set, or state explicitly that only completed board runs are listed."
  }
 ],
 "coverage": [
  "Verified the plan SHA256 (30bb85a9…) against the supplied digest and read the full plan plus the review log's round-1/2 outputs and dispositions.",
  "Checked the round-2 fixes in code: §0/§2.5 tracker-issue path (modules/linear `_issues_post`, `LocalTracker.create_issue`); §3.2/§1 project-worktree route (`_run_project_ticket`/`_run_project_ticket_locked`, `_project_cmd`); §3.3 withholding (`_records_unsafe`, record writes at app.py:3255-3271,4198-4208); §3.1 agent forcing (`_get_task_agent_lock`, `canonical_agent`); §3.4/records (`_write_run_log`, `api_run_set_status`, `api_run_restore`); §4.1 own-claim exclusion (`_SESSION_CLAIMS`, `_live_session_ids`); §2.4/§2.3 latest-run lookup (`_latest_linear_runs`, `api_runs_latest_by_issue`, index.html `_preferRun`/refreshJobBoard).",
  "Read and traced: app.py `api_run_retry`/`_do_retry_attempts`/`_dispatch_cmd`/`_build_resume_cmd`/`run_agent_process`/`_stream_claude_run`/`_parse_agent_output`/`_parse_project_output`/`_agent_model`/`_compute_token_cost`/`api_run_detail`/`record_interactive_ended`; projects.py `session_target`, `session_lock`, `check_session_idle`, `claude_sessions`, `codex_sessions`, `project_sessions`, `_session_roots`, `create_worktree`, `runner_commit`, `committed_seeds`; project_runs.py `post_run`/`agent_cli`/`run_agent`; reset_gen.py; modules/linear `_issues_post`, `unsynced_local_id`, `_tracker_reset_route`, `_bg_sync_to_linear`, `_dispatch_issue_held`, `push_state`; index.html `_sessionRow`, `refreshJobBoard`, `openDetailModal`, `retryRun`/`retryFromDetail`, card verify badge.",
  "Confirmed §7's premise against real code: `project_runs.py:507` uses the fixed `base_sha` and `projects.py:1074` returns it for reused worktrees.",
  "Confirmed §8 against real data: inspected `outputs/logs/*_stream.jsonl`; the init event carries `model: claude-opus-5-5[1m]`, the result event carries `model: null` plus `modelUsage`, and `usage_reader.MODEL_PRICES` lacks that key.",
  "Read the earlier plans `2026-10-15-dashboard-ui-updates.md` (C0/C2 landed) and the review log for `2026-10-15-runner-write-safety.md` rules referenced by the plan."
 ],
 "limitations": [
  "Read-only review: I edited nothing, ran no pytest, launched no runner, and exercised no browser, so no runtime behavior is claimed to pass.",
  "I did not read all ~12,000 lines of app.py/index.html; findings are grounded in the cited functions and line ranges.",
  "`ps`/process-tree semantics and the sandbox behavior of the planned confidential generic path were reasoned from code, not executed.",
  "I did not inspect other sessions' uncommitted work, git branches, or test files; conclusions use the working tree at the given plan hash.",
  "For STB-021 I traced the local-first create and alias swap in code but did not run a live Linear sync; the conclusion follows the code paths (`record_id_alias` is only consumed by STT/UI, and `unsynced_local_id` ignores aliases)."
 ]
}```

### Dispositions
Round 3 dispositions (host: Claude). All 8 findings accepted.
- STB-021 (high): §2.5 creates the Linear issue synchronously through `LinearClient.create_issue`, not the local-first `_issues_post`, so the record links to the real id the board lists. A Linear error → 409 and nothing written. The local tracker creates final ids directly.
- STB-022: §7 judges "this run changed nothing" on `run_start_sha..HEAD` (worktree HEAD captured before the agent starts), plus clean and no seeds. `base_sha` stays for seed/verify accounting.
- STB-023: §8 reads the observed model in `_stream_claude_run` and `_parse_project_output` (init event model, else the `result.modelUsage` first key). The dead `_parse_agent_output` claude branch is left alone.
- STB-024: `_compute_token_cost` strips a `[…]` suffix, then falls back to the longest family prefix. An Opus 5.5 price entry is added, with the rate from Anthropic's pricing page at build time.
- STB-025: the claim about the "+" path is withdrawn. Confidential (or unknown) projects send the neutral title `Session <8 chars>` to the tracker.
- STB-026: `own_finished_at` = the end of the card's last real attempt, excluding the to-board todo record and interactive_ended audits.
- STB-027: to-board takes `session_lock` first and runs the running check and the write inside it.
- STB-028: the §9 id set also includes live running-job and claim ids.
- New user sections, unreviewed until this round:
  - §10: each non-confidential registered project maps to a same-named Linear Project; confidential and unbound tasks stay in the default; AGE ids unchanged.
  - §11: Empty trash archives Canceled issues (Linear `issueArchive`, local delete); run records and transcripts stay; a card lookup that lands on an archived or missing issue counts as "no card".

## Plan review round 4 (DeepSeek)
- Plan SHA256 reviewed: 4757a13aa3b485d0bde812ebe6280e99b14f5bca42ff8908d460e0c055a560ad
- Output: `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/stb/review4.out` (parsed: `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/stb/review4.json`)
- Fingerprint before = after `c9de798ccdecfd35be4dc69096dbc38805285f300d9a64ba0230ba51bf44dd7b`: the reviewer changed nothing.
- Verdict: **REVISE**, 9 findings (1 high, 6 medium, 2 low). STB-021..028 confirmed resolved.

```json
{
 "verdict": "REVISE",
 "summary": "Round-3 dispositions STB-021..028 check out against the code where they touch it: §2.5's synchronous LinearClient.create_issue avoids the local-first alias swap; §7's run_start_sha is capturable next to the existing fingerprint; §8 now reads the init event model in both _stream_claude_run and _parse_project_output; §8's price normalization plus an explicit Opus 5.5 key can resolve claude-opus-5-5[1m]; §2.5's neutral title replaces the false '+' confidentiality claim; §4.3's own_finished_at is defined as the last real attempt; §2.2's session_lock-first ordering closes the STB-008/027 race; §9 includes live ids. New material defects remain in the new §10/§11 and in how the revised §2/§3 records interact with existing readers/writers. The strongest are: Empty trash cannot clear Linear-mode trash because the poller re-adds terminal issues from its own cache and rewrites state/tasks.json; §10 needs a Linear API surface (projectId on issueCreate, project create/lookup) that does not exist and whose current-behaviour premise is contradicted by the code; the synchronous §2.5 create skips the cache insert that the board reads.",
 "findings": [
  {
   "id": "STB-029",
   "severity": "high",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §11; runner/modules/linear/__init__.py:438-447,505-523,551-580,1360-1378; runner/modules/linear/local_tracker.py:220-226",
   "evidence": "The poller keeps terminal issues from the *current* cache (`terminal_issues = {k:v for k,v in self.issues_cache.items() if v.get('state') in ('Canceled','Done','Duplicate')}`, lines 552-555) and re-adds the last 100 after rebuilding from Linear (`self.issues_cache.update(dict(terminal_list[-100:]))`, line 573; `_issues_by_team` too, 576-579), then `_sync_cache_to_local()` rewrites state/tasks.json (1360-1378). `start_background` also pre-populates the cache from tasks.json (438-447). So after Empty trash calls Linear `issueArchive` (an `issueArchive` mutation that also does not exist in linear_client.py), the next poll's `new_cache` omits the archived issue but `terminal_issues` re-adds it from the stale cache and tasks.json is rewritten. The 🗑 chip keeps counting it, it survives a runner restart, and §2.3's 'archived issue counts as no card' never fires because the cache still holds the issue (so Resume tries to move a Canceled/archived issue and fails).",
   "fix": "On Empty trash, evict each archived id from `issues_cache`, `_issues_by_team`, `_local_overrides`, the local tracker (tasks.json) and any dismissed set before emitting; add a Linear `issueArchive` mutation to LinearClient; and have §2.3 treat a `linear_issue_id` that is absent from the live cache (or marked archived) as 'no card', not merely a record field."
  },
  {
   "id": "STB-030",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §10; runner/linear_client.py:98-110,137-148,349-353,386-400; runner/modules/linear/__init__.py:1022-1032",
   "evidence": "The GraphQL `_MUTATION_CREATE_ISSUE` input is `{teamId,title,description,stateId,labelIds}` (linear_client.py:98-110) and `create_issue` builds only those variables (386-400); there is no `projectId` parameter and no `projectCreate` mutation anywhere in the repo. `_bg_sync_to_linear` calls `client.create_issue(tid,title,desc,label_ids=...)` with no project (__init__.py:1032). Therefore the plan's premise that 'the runner currently puts every issue in one Linear Project (tracker.project_slug, shown as Agenticos)' is not supported by the code, and 'found by name and created when missing' plus 'issues created for a project go into its Linear Project' cannot be implemented without new client methods/fields the plan never names.",
   "fix": "State the LinearClient changes explicitly: add `projectId` to the create mutation and a `project_id` argument to `create_issue`, add a `projectCreate` mutation (and a team-scoped lookup that excludes archived projects) or a documented equivalent, and correct the §10 premise about current behaviour."
  },
  {
   "id": "STB-031",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §2.5, §6; runner/modules/linear/__init__.py:944-971,1008-1020; runner/templates/index.html:2674,2691-2732",
   "evidence": "`GET /api/linear/issues` in Linear mode serves `self.issues_cache`/`_issues_by_team` (__init__.py:956-971), and `refreshJobBoard` builds every column only from that response (index.html:2674, 2691-2732). The '+' path inserts the new issue into `issues_cache` and `_issues_by_team` and emits `linear_issues_updated` immediately (__init__.py:1013-1020). §2.5 instead calls `LinearClient.create_issue` directly and never says to insert the result into the cache or emit. After Resume on a no-card session, §6's immediate `refreshJobBoard()` therefore shows no card until the next poll (polling.interval_ms is 30000 in WORKFLOW.md), so 'creates one tracker issue in Todo ... visible on the board' is delayed and `_boardItemsByRunId[run_id]` is undefined for the card.",
   "fix": "After the synchronous create, write the normalized issue into `issues_cache` and `_issues_by_team` and emit `linear_issues_updated` (mirroring _issues_post), and have §6 tolerate an absent boardItem."
  },
  {
   "id": "STB-032",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §3.3; runner/project_runs.py:83-98; runner/app.py:3177-3180,3148-3150",
   "evidence": "`project_runs.agent_cli` decides the sandbox from `project.confidential` (project_runs.py:83-98). §3.3 builds the generic resume argv on `project_runs.agent_cli(agent, project, ...)` and only refuses for 'the binding is confidential and _records_unsafe()'. The project path instead forces the effective project sticky: `if binding['confidential'] is not False: project = dataclasses.replace(project, confidential=True)` (app.py:3177-3180), so a binding whose registry flag was later changed to false (or an unknown binding) still runs sandboxed there. On the generic session path a formerly-confidential or unknown binding would run `agent_cli` with `project.confidential=False`, i.e. claude `--permission-mode bypassPermissions` / codex `--approve-for-me`, unsandboxed and unwithheld.",
   "fix": "For the generic branch derive the effective project from `_ticket_confidential`/the durable binding (treat any non-False binding as confidential) before calling `agent_cli` and before the `_records_unsafe()` refusal, exactly as `_run_project_ticket_locked` does."
  },
  {
   "id": "STB-033",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §7; runner/project_runs.py:505,514-529; runner/projects.py:1137-1152",
   "evidence": "`post_run` computes `seeds = projects.committed_seeds(project, wt, binding['base_sha'])` and `committed_seeds` scans `rev-list base..HEAD` (projects.py:1141), and the badge order is `if seeds: badge = 'seed committed'` first (project_runs.py:514-515). The plan's STB-022 fix judges 'changed nothing' on `run_start_sha..HEAD` but keeps `base_sha` for seeds. On a reused ticket whose earlier attempt committed a seed path, a later question-only run leaves HEAD at run_start_sha yet `base_sha..HEAD` still contains the earlier seed commit, so `seeds` is non-empty and the card shows a red 'verify: seed committed' instead of no badge, contradicting §7's 'changed nothing -> no badge'.",
   "fix": "Judge seed commits over `run_start_sha..HEAD` too (the plan already captures that sha), or explicitly exclude seed commits that predate `run_start_sha`, and place the changed-nothing rule so it suppresses non-error badges."
  },
  {
   "id": "STB-034",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §8; runner/app.py:3269-3271,3419-3427,4354-4364,2089-2102; runner/modules/linear/__init__.py:866-884",
   "evidence": "`_compute_token_cost` is called only on the `/run` agent path (app.py:3419) and the retry path (app.py:4354). `_run_project_ticket_locked` writes records with `input_tokens`/`output_tokens` but no `token_cost_usd` (app.py:3269-3271), and Linear `_dispatch_issue` likewise (__init__.py:866-884). The motivating case, AGE-102, is a project run: after §8 fixes the model it will show the model but still no Cost, so §8's acceptance 'and cost uses it' holds only for `/run` and retry, not for the project/Linear records the problem statement is about.",
   "fix": "Call `_compute_token_cost(output_tokens, input_tokens, observed_model)` in `_run_project_ticket_locked` and `_dispatch_issue` and pass `token_cost_usd`, or narrow the acceptance to the paths that actually compute cost."
  },
  {
   "id": "STB-035",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §2.4, §5; runner/app.py:3560-3569,3573-3599; runner/templates/index.html:4381-4393,4494-4500",
   "evidence": "§2.4 appends the to-board record on the issue's latest `run_id`. `_latest_record(run_id)` returns the newest record for that run_id (app.py:3560-3569), and `api_run_events`/`api_run_detail` use it, so the synthetic to-board record shadows the real attempt: `agent_session_id`, `output`/`last_message`, `resume_eligible` and `_cardKey` all come from the synthetic record. §2.4 does not state that the record copies `agent_session_id`, `task_id`, the binding, `source`, prompt and output; if it does not, the detail/Terminal view loses the pinned message and 'Open interactive'/quick-reply eligibility, and §5's 'Terminal tab unchanged' fails for exactly these cards.",
   "fix": "Specify the found-card record's full field set (copy the latest run's agent_session_id/task_id/project_key/confidential/source/prompt/output, plus the matching run_id), or make `_latest_record`/`api_run_events` skip to-board-only records when resolving run metadata."
  },
  {
   "id": "STB-036",
   "severity": "low",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §5; runner/templates/index.html:3029-3034,3125-3143",
   "evidence": "`openDetailModal` shows `#detail-dispatch-group` for `isTodo && r.linear_issue_id` (index.html:3034), independent of any resume intent, and its buttons call `dispatchFromDetail`, which PATCHes In Progress and starts a fresh dispatch. §5 only changes `canRetry` to admit Todo; it does not hide/adjust the dispatch group. A resumed session card in Todo therefore shows both the resume controls and the fresh-dispatch buttons, and clicking a dispatch button starts a fresh run, abandoning the session the user just resumed.",
   "fix": "When the latest record carries a valid `resume_ok` intent, hide (or clearly separate and confirm) the dispatch group so a Todo session card offers only the continuation, or route the dispatch buttons through the same strict continuation."
  },
  {
   "id": "STB-037",
   "severity": "low",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §4.3; runner/app.py:4066-4086; runner/projects.py:1654-1662",
   "evidence": "`record_interactive_ended` writes `started_at = now`, `duration_s = 0.0`, `interactive_ended = True` (app.py:4079-4084), and `check_session_idle` treats a transcript written in the last `SESSION_FRESH_S` (120 s) as busy (projects.py:1661). §4.3 excludes interactive_ended audits from `own_finished_at`. For a card just used in the runner's own card Terminal tab, `own_finished_at` is the older real attempt (or None for a session with no real run), so the fresh transcript write is counted as 'in use elsewhere' and the first reply after closing the tab gets a false confirmation prompt, contradicting the acceptance that the card's own activity never counts.",
   "fix": "Use the interactive_ended audit's timestamp (`started_at + duration_s`) as an own-finished time when it is newer than the last real attempt, or otherwise exempt the card's own just-closed interactive writes from the freshness reason."
  }
 ],
 "coverage": [
  "Verified plan SHA256 4757a13aa3b485d0bde812ebe6280e99b14f5bca42ff8908d460e0c055a560ad and read the full plan plus the round-1/2/3 review log and dispositions.",
  "Checked the round-3 fixes in code: §2.5 synchronous create vs _issues_post/_bg_sync_to_linear (linear/__init__.py:979-1065); §7 run_start_sha feasibility vs post_run/fingerprint (project_runs.py:481-532, app.py:3193-3238); §8 init/modelUsage in _stream_claude_run and _parse_project_output (app.py:2457-2506, 2711-2738) and MODEL_PRICES (usage_reader.py:59-75, app.py:2089-2102); §4.3 own_finished_at vs record_interactive_ended (app.py:4066-4086) and check_session_idle (projects.py:1654-1662); §2.2 lock-first vs _claim_session/session_lock (app.py:3753-3767, projects.py:1597-1608); §9 live ids vs _running_jobs/_SESSION_CLAIMS (app.py:3763-3767).",
  "Read for §10/§11: runner/modules/linear/__init__.py (background poll/prepopulate/terminal retention/_sync_cache_to_local, _issues_post, _issues_patch, push_state, _push_linear), runner/linear_client.py, runner/modules/linear/local_tracker.py, and the trash/board UI in index.html:2667-2884.",
  "Read runner/app.py: api_run_retry/_do_retry_attempts/_dispatch_cmd, _get_task_agent_lock, _build_resume_cmd, run_agent_process, api_run_detail, api_run_set_status, api_run_restore, api_run_events/_latest_record/card_run_for_session, _durable_binding/_ticket_confidential/_effective_project/_records_unsafe, _run_project_ticket_locked, and the maintenance/session-claim plumbing; runner/project_runs.py agent_cli/post_run/committed_seeds; projects.py session_target/claude_sessions/codex_sessions/_session_roots/check_session_idle/create_worktree/committed_seeds; reset_gen.py; runner/modules/pty/__init__.py open_terminal/interactive_resume_argv; index.html _sessionRow, project row handlers, openDetailModal, retryRun/retryFromDetail, _cardTerm* and refreshJobBoard/_renderBoardItems/renderTrash.",
  "Read the earlier plans 2026-10-15-dashboard-ui-updates.md (C0/C2 contracts) and completed/2026-10-15-runner-write-safety.md, and WORKFLOW.md/projects.yaml for tracker active_states, team_id, project_slug, seeds and confidential flags."
 ],
 "limitations": [
  "Read-only plan review: I edited nothing, ran no pytest, launched no runner, exercised no browser and made no Linear API call; no runtime or test result is claimed.",
  "I did not read all ~12k lines of app.py/index.html; findings are grounded in the cited functions and ranges. In particular I did not fully trace _events/replay, every _write_run_log caller, or the STT/draft paths.",
  "The §11 conclusion is derived from the polling/retention code path (terminal_issues from issues_cache and _sync_cache_to_local); I did not run a live archive/poll cycle, and Linear's exact includeArchived default was not exercised.",
  "Process-argv detection, sandbox argv effects and macOS ps output were reasoned from code, not executed.",
  "I did not inspect other sessions' uncommitted work, branches, or the test files beyond the sdk-session assertions in tests/test_project_sessions.py."
 ]
}```

### Dispositions
Round 4 dispositions (host: Claude). All 9 findings accepted. Verified: with team_id configured, fetching is team-scoped; create_issue sends no projectId.
- STB-029 (high), §11:
  - adds `LinearClient.archive_issue` (`issueArchive`);
  - evicts archived ids from `issues_cache`, `_issues_by_team`, `_local_overrides`, the `tasks.json` mirror and dismissed sets before emitting;
  - keeps a persisted `archived_ids` set that the poller's carry-over skips, so a restart does not resurrect them;
  - §2.3 treats an issue absent from the live cache, or archived, as no card.
- STB-030, §10:
  - premise corrected: issues get no Linear Project today; `project_slug` only scopes no-team fetching and the state lookup; §10 requires `team_id`;
  - LinearClient changes named: `create_issue(project_id)`, `find_project`, `create_project`, `set_issue_project`.
- STB-031: the §2.5 synchronous create also writes the issue into `issues_cache`/`_issues_by_team` and emits; the UI tolerates a missing boardItem.
- STB-032: the generic session path derives effective confidentiality from the binding (non-False → confidential) before `agent_cli` and before the unsafe refusal, as the project path does.
- STB-033: §7 also judges seed commits over `run_start_sha..HEAD`, and the rule runs before the other non-error badges.
- STB-034: project and Linear dispatch paths now compute and write `token_cost_usd` from the observed model.
- STB-035: the found-card to-board record is `{**latest_record, status: todo, resume_session, reset_gen, to_board: true}`, so detail and events keep their fields.
- STB-036: the fresh-dispatch group is hidden while `resume_ok` holds.
- STB-037: `own_finished_at` also takes the card's newest `interactive_ended` audit time, if that is later.

## Plan review round 5 (DeepSeek)
- Plan SHA256 reviewed: e79f4add15a37455d116236cddf3c48641bebec50ab4b2ab323cee8cb2b2ccd8
- Output: `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/stb/review5.out` (parsed: `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/stb/review5.json`)
- Fingerprint before = after `5ab15cde735d5d0d38a26d46a2865d818689d182f4be09a4b425c41b6bb3c76b`: the reviewer changed nothing.
- Verdict: **REVISE**, 8 findings (1 high, 6 medium, 1 low). STB-029..037 confirmed resolved.

```json
{
 "verdict": "REVISE",
 "summary": "All nine round-4 dispositions are present in the plan text and their mechanics are supported by the code I read (archive/evict + persisted archived_ids; named LinearClient project methods; synchronous cache insert; effective confidentiality from the binding; seeds over run_start_sha..HEAD; token_cost_usd on project/Linear paths; {**latest_record,...} to-board record; dispatch group hidden while resume_ok; interactive_ended in own_finished_at). New materially unresolved defects remain in the §2/§3 retry integration (the existing bound/_run_project_ticket block misroutes the new generic session cards), in §7's badge ordering versus its own red-badge rule, in §2.5's local/Linear direct create (labels, ensure_label, agent marker), in §2.4 (no _records_unsafe withholding; no failure path when the Todo move fails), and in the §10 claim that a confidential project name is never sent to Linear. Verdict: REVISE.",
 "findings": [
  {
   "id": "STB-038",
   "severity": "high",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §2.5/§3.3; runner/app.py:4214-4248",
   "evidence": "§2.5's no-card record carries the project binding as top-level `project_key`/`confidential` but no `issue_identifier`/`worktree`. In `api_run_retry`, `bound = _durable_binding(...) or (original if original.get('project_key') else None)` (app.py:4214) is therefore truthy, `bound.get('issue_identifier')` is None so neither the ticket branch nor the `elif not bound` card-lock branch runs (app.py:4216-4224), and `if bound:` then calls `_run_project_ticket(..., ident=bound.get('issue_identifier') or '', resume_session=..., reuse_only=True)` (app.py:4225-4248) with an empty ident. The plan's cwd-based decision (ticket worktree vs any other session card) is never expressed as a replacement for this existing bound-based block. A found card whose binding has an `issue_identifier` but whose session cwd is the main checkout also takes the ticket branch, contradicting §3.3.",
   "fix": "State explicitly that the existing `bound`/`_run_project_ticket` block is replaced by the cwd-based decision: route to `_run_project_ticket` only when the durable binding's `worktree`/`issue_identifier` matches the resolved session cwd, and never let a `project_key`-only inline binding reach that helper (the generic path must resolve its project from the record/route and use `run_agent_process`)."
  },
  {
   "id": "STB-039",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §7.1/§7.3; runner/project_runs.py:497-531",
   "evidence": "`post_run` runs `run_verify` whenever `project.verify` is set (project_runs.py:498-501) and the badge order is seed → main checkout → error → uncommitted → no check/verify (lines 514-529), so a question-only run can still produce `verify['status'] == 'fail'` or `main checkout changed`. §7.1 puts the changed-nothing rule \"before the other non-error badges\" and returns no badge, while §7.3 says fail/error and the main-checkout and seed warnings stay red. Implemented literally, a no-change run that fails its verify command or changed the main checkout (Claude writes `.claude/.cc-writes` there even for worktree runs, projects.py:1173-1175) is rendered with no badge, hiding exactly the red safety/warning states §7.3 promises to keep.",
   "fix": "Evaluate fail/error and the main-checkout/seed warnings before (or independently of) the changed-nothing suppression; apply the no-change rule only to the run-owned `no check`/`uncommitted changes` badges."
  },
  {
   "id": "STB-040",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §2.5; runner/modules/linear/__init__.py:1000,1013-1020; runner/modules/linear/local_tracker.py:141-158",
   "evidence": "The `+` path passes `labels=labels` and `preferred_agent=pa` to `create_issue` for both the local tracker (`local.create_issue(title, desc, preferred_agent=pa, team_id=tid, labels=labels)`, linear/__init__.py:1000) and the Linear background sync (line 1015), where `labels` is `_project_labels(data)` = `['project:<key>']`. §2.5's local bullet only says \"create through the local tracker's create function (ids are final immediately)\" and never mentions the label or the preferred agent. A project session with no card in local mode therefore gets a card with `labels=[]` and no agent marker, so once the one-shot intent is voided (drag/reset to Todo) a fresh dispatch is not project-bound and runs in the runner root with the default backend.",
   "fix": "Pass the same `['project:<key>']` label and the session agent (composed description/`preferred_agent`) that `_project_labels`/`_compose_issue_description` supply on the `+` path."
  },
  {
   "id": "STB-041",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §2.5; runner/linear_client.py:370-384; runner/modules/linear/__init__.py:1027-1031",
   "evidence": "`LinearClient.create_issue` accepts `label_ids`, not label names (linear_client.py:386-400), and the only label lookup/create is `ensure_label` (lines 370-384). `_bg_sync_to_linear` calls `ensure_label(tid, name)` for every label and raises so the task stays local if any cannot be resolved (linear/__init__.py:1027-1031). §2.5 says the direct create \"gets the `project:<key>` label\" but never names `ensure_label` or any label-id lookup, so for a project whose label has never been created the direct `LinearClient.create_issue` will produce an issue with no project label (binding lost on a later fresh dispatch) or an unresolved `labelIds` entry.",
   "fix": "Resolve `ensure_label(team_id, 'project:<key>')` before the direct create and fail the to-board with 409 when it is missing, mirroring `_bg_sync_to_linear`."
  },
  {
   "id": "STB-042",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §2.4 vs §2.5/§3.5; runner/app.py:3262-3268,4199-4203",
   "evidence": "§2.4's found-card record is `{**latest_record, 'status': 'todo', 'resume_session': …, 'reset_gen': <bumped>, 'to_board': true}` and explicitly keeps `prompt` and `output`. §2.5's no-card record and §3.5's reply records are required to apply `_records_unsafe()` withholding, but §2.4 says nothing about it. For a confidential binding whose record locations have since become unsafe, the to-board route appends a new run-log line duplicating the previous attempt's confidential prompt/output, even though the project path refuses every confidential launch on the same check (app.py:3181-3183) and the retry's own startup-failure path withholds (app.py:4199-4203). This violates the plan's acceptance \"records withhold text where record locations are unsafe\".",
   "fix": "Run the found-card record through the same withholding helper (prompt marker, withheld output/error) when the binding is confidential or unknown and `_records_unsafe()` is non-None, or refuse the to-board move in that state."
  },
  {
   "id": "STB-043",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §2.4; runner/modules/linear/__init__.py:335-357,1208-1243",
   "evidence": "The tracker PATCH path bumps the issue generation inside `_tracker_reset_route` and restores it only when `resp.status_code >= 400 and not g.tracker_state_committed` (lines 348-356); the Linear synchronous branch can also return 502 after `_remember_local_override` was written (lines 1208-1230). §2.4 says to move the issue to Todo, bump the generation, then append the record, but never says to abort the record write on a failed move/push or to re-read `reset_gen.current(issue)` after it. A failed push can leave the record's `resume_session.gen` matching a restored generation (intent silently void, criterion 2 of §1 fails) or a stale bump while the issue never reached Todo.",
   "fix": "Make the record write conditional on a confirmed Todo move, read `gen = reset_gen.current(issue)` after the move rather than using the pre-move bump, and return 409 with nothing appended when the state push fails."
  },
  {
   "id": "STB-044",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §2.5/§10; runner/modules/linear/__init__.py:211-236",
   "evidence": "§2.5 says the created issue \"gets the `project:<key>` label\" for any project, and `_project_labels` returns `project:<key>` for a specified project independent of confidentiality (linear/__init__.py:229-236). §10 asserts \"A confidential project's name is never sent to Linear\" and that confidential projects stay in the default Project. Since the registry key is the private project name the repo scrubs (AGENTS.md public-repo check), the label does send it to Linear. The plan's own §10 sentence is therefore not implementable as stated while §2.5 applies the label unconditionally.",
   "fix": "For a confidential or unknown binding, use the default `project_slug`/`agentic-os` label (or no project label) and resolve the project from the record/binding instead, and correct §10's claim accordingly."
  },
  {
   "id": "STB-045",
   "severity": "low",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §2.5; runner/modules/linear/__init__.py:178-185,203-204,994,1032",
   "evidence": "`_normalize_linear_issue` derives `preferred_agent` by parsing the agent marker out of the description (`_extract_issue_agent`, lines 202-204), and the `+` path composes that marker via `_compose_issue_description(desc, pa)` (line 994) before the local create and the Linear create (line 1032). §2.5's direct `LinearClient.create_issue` passes only title/description/labels, so the new card's `preferred_agent` is None; after the intent is voided and the card is dispatched fresh, `_dispatch_issue` falls back to the global default backend rather than the session's agent.",
   "fix": "Compose the description with the session's agent marker before the direct create (or extend `create_issue`/the record contract to carry the agent explicitly)."
  }
 ],
 "coverage": [
  "Verified the plan file SHA256 e79f4add15a37455d116236cddf3c48641bebec50ab4b2ab323cee8cb2b2ccd8 and the read-only policy; edited nothing and ran no tests.",
  "Read the round-1..4 review log (docs/exec-plans/active/2026-10-16-session-to-board.review-log.md) to confirm STB-001..037 and the round-4 dispositions, so new findings start at STB-038.",
  "runner/app.py: api_run_retry/_do_retry_attempts/_dispatch_cmd, _get_task_agent_lock, _build_resume_cmd, _project_cmd, run_agent_process, _stream_claude_run, _parse_agent_output, _agent_model, _compute_token_cost, _run_project_ticket(_locked), _parse_project_output, _records_unsafe, _claim_session/_release_session/_live_session_ids, _reset_key, card_run_for_session, _latest_record, api_run_detail, api_run_set_status/restore, record_interactive_ended, _latest_linear_runs, api_runs_latest_by_issue.",
  "runner/projects.py: session_target, session_lock, check_session_idle, project_sessions, claude_sessions/codex_sessions, _session_roots, _under/_under_resolved/_slug, SESSION_FRESH_S, committed_seeds, runner_commit, record_location_problem, worktree_path.",
  "runner/project_runs.py: agent_cli, project_prompt, common_dir, post_run, closing_check; runner/modules/pty/__init__.py: open_terminal/term_open, interactive_resume_argv, TERMINALS/live ids.",
  "runner/modules/linear/__init__.py: poller/prepopulate/terminal carry-over/_sync_cache_to_local, _normalize_linear_issue, _project_labels, _tracker_reset_route, _issues_get/_issues_post/_bg_sync_to_linear, _issues_patch/_issues_patch_reserved, _dispatch_issue_held, push_state/_push_sync/_push_linear, _is_confidential_issue; runner/linear_client.py (create_issue, ensure_label, fetch_projects, GraphQL mutations/queries); runner/modules/linear/local_tracker.py (create/update/delete/raw_transaction); runner/reset_gen.py.",
  "runner/templates/index.html: _sessionRow and project-row handlers, refreshJobBoard/_moveLinearIssueToColumn, renderTrash/trash chip, openDetailModal, retryRun/retryFromDetail, _cardTerm* (bind/open/load/quick reply/next), detail reply/dispatch/retry DOM.",
  "Cross-checked the earlier plans docs/exec-plans/active/2026-10-15-dashboard-ui-updates.md (C0/C2 contracts) and docs/exec-plans/completed/2026-10-15-runner-write-safety.md."
 ],
 "limitations": [
  "Read-only plan review: no pytest, no runner launch, no browser, no Linear API call; no runtime or test result is claimed and the plan's \"full suite passes\" line is unverified.",
  "I inspected the cited functions and ranges, not every line of app.py (4,735) or index.html (5,040); findings are grounded in the referenced code.",
  "I did not re-raise STB-019's own-claim exclusion; the plan §4.1 wording still names `_live_session_ids()` (which returns `set[(agent,sid)]` and exposes no run_id) rather than `_SESSION_CLAIMS.items()`, so the implementer must iterate the claim map to exclude by run_id, but I treat that as already-disposed intent.",
  "Linear GraphQL capabilities (team-scoped `projects` filter, `issueArchive`, `projectCreate`, `includeArchived` default) were reasoned from the client code, not exercised against Linear, and no live poll/archive cycle was run.",
  "macOS `ps -A -o pid=,ppid=,args=` behavior and the confidential sandbox argv effects were reasoned from code, not executed."
 ]
}```

### Dispositions
Round 5 dispositions (host: Claude). All 8 accepted.
- STB-038 (high): §3.3 now explicitly replaces the existing `bound`/`_run_project_ticket` block for intent cards. A card goes to the helper only when the *durable* binding has an `issue_identifier` whose `worktree_path` equals the resolved session cwd, called with that ident. Inline `project_key`-only cards never reach the helper; their project resolves from the registry.
- STB-039: §7 order. Red states (verify fail/error, main checkout changed/unchecked, a seed committed in this run, post_run_error) are evaluated first and always win; the changed-nothing rule only suppresses `no check` / `uncommitted changes`.
- STB-040/045: §2.5 uses the same composition as the "+" path: `_project_labels`, `_compose_issue_description(desc, agent)` (agent marker → `preferred_agent`); the local tracker gets `preferred_agent`.
- STB-041: Linear direct create resolves `ensure_label(team_id, 'project:<key>')` first; an unresolvable label → 409, nothing created.
- STB-042: the §2.4 found-card record goes through the withholding helper when the binding is confidential or unknown and records are unsafe.
- STB-043: §2.4 writes the record only after the Todo move/push is confirmed, reads `gen` after the move, and returns 409 with nothing appended on failure.
- STB-044: §10's claim is corrected. Confidential projects get no Linear Project. `project:<key>` labelling stays as in part B; Linear is the user's private workspace and the public-repo rule covers git only.

## Plan review round 6 (DeepSeek)
- Plan SHA256 reviewed: f73b4eb5114bedabf3a8a3e29576afb01661bb04c2df3c21c5e1317a07bba535
- Output: `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/stb/review6.out` (parsed: `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/stb/review6.json`)
- Fingerprint before = after `16cd596f8e24a26a8b8530195ce943c9ffd61a6e47df4056f5a718384ad85895`.
- Verdict: **REVISE**, 6 findings (3 medium, 3 low). STB-038..045 confirmed resolved.

```json
{
 "verdict": "REVISE",
 "summary": "Round-5 dispositions STB-038..045 are present in the plan text and their mechanics match the code I read: the cwd-based replacement of the bound/_run_project_ticket block is now explicit (STB-038), the §7 red-first order is stated (STB-039), §2.5 mirrors the + path composition (STB-040/045), ensure_label precedes the direct create (STB-041), the found-card record goes through withholding (STB-042), the record write is conditional on a confirmed Todo move with gen read after it (STB-043), and the §10 confidential claim is corrected (STB-044). However the retry integration still has an unreconciled mismatch between the session named by the intent and the card's latest record, §2.5 still leaves the Linear description undefined for confidential sessions, and four smaller spec/security/price/eviction/concurrency gaps remain. Verdict: REVISE.",
 "findings": [
  {
   "id": "STB-046",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §1/§2.3/§2.4/§3; runner/app.py:4168-4172,4334-4341",
   "evidence": "§2.3 finds the card from the newest record with `agent_session_id == sid`, but §2.4 writes the intent as `{**latest_record, ...}` and explicitly keeps `agent_session_id` from the *issue's latest run*, which can be a different session. §1/§3 then make the intent a strict continuation, so `_lock_session_id = resume_session.id` while `original[\"agent_session_id\"]` is the latest record's session. Concrete: S1 ran on AGE-1, the card was reset and S2 ran; Resume on S1's project row moves AGE-1 to Todo and appends `resume_session.id = S1` on S2's run_id. api_run_retry then hits the existing guard at app.py:4170 (`strict and original[\"agent_session_id\"] != _lock_session_id`) and returns 409 forever, so the card's reply box can never send. If the implementer does not set `strict` for the intent, the same mismatch falls through to the resume-failure fallback at app.py:4334, which starts a *fresh* session — violating the acceptance 'never a fresh session; a failed continuation is an error'.",
   "fix": "On the found-card path write `agent_session_id = sid` (and the matching binding) into the to-board record so the latest record and the intent name the same session, or reject to-board when `sid` is not the card's current session; and make the intent path strict while stating how it satisfies/replaces the UI11-02 guard at app.py:4170 (otherwise the guard and the intent contradict each other)."
  },
  {
   "id": "STB-047",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §2.5; runner/modules/linear/__init__.py:178-184,1000,1032",
   "evidence": "§2.5 says `description = _compose_issue_description(desc, agent)`, but `desc` is never defined and the composed string is sent verbatim to the tracker (`local.create_issue(title, desc, ...)`, line 1000; `client.create_issue(tid, title, desc, ...)`, line 1032). The plan neutralizes only the *title* for a confidential/unknown binding. For a session card the natural `desc` is the session title/first message (the + path's description source), so the confidential session text would be posted to Linear in the description even though the title is neutral — defeating the same private-repo policy the plan says it keeps.",
   "fix": "Specify `desc` for session cards; for a confidential or unknown binding send an empty/no-content description (only the `_compose_issue_description` agent marker), or refuse to create the Linear issue and keep the card local."
  },
  {
   "id": "STB-048",
   "severity": "low",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §7; runner/project_runs.py:514-529",
   "evidence": "§7's STB-039 order suppresses the changed-nothing rule only for `no check` and `uncommitted changes`, leaving red states first. But when `project.verify` is configured `post_run` still runs verify (lines 498-501), and for a no-change run the badge becomes `verify['status']` (lines 528-529), e.g. `pass`. The card therefore shows `verify: pass` on a run that changed nothing, contradicting the acceptance 'A project run that changed nothing shows no verify badge' (only `fail`/`error` and the main/seed warnings should survive).",
   "fix": "When `run_start_sha..HEAD` is empty and the worktree is clean, emit no badge unless the badge is one of the red states (verify fail/error, main checkout changed/unchecked, seed committed this run, post_run_error)."
  },
  {
   "id": "STB-049",
   "severity": "low",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §8; runner/app.py:2098-2102,2377-2390; runner/usage_reader.py:68-75",
   "evidence": "§8 changes `_compute_token_cost` to fall back to the longest matching family prefix. `_agent_model('codex')` returns `gpt-5.4-mini` (app.py:2390) whenever `codex_model` is unset, and `MODEL_PRICES` has only `gpt-5.4` (6.00) with `DEFAULT_PRICE` 3.00 (usage_reader.py:73-75). A longest-prefix lookup therefore matches `gpt-5.4-mini` to `gpt-5.4` and silently changes every codex run's `token_cost_usd` from the current 3.00 default to 6.00, a fidelity regression the plan does not mention.",
   "fix": "Add an exact `gpt-5.4-mini` price entry, or scope the prefix fallback to the `[…]` suffix case / Claude ids instead of matching arbitrary longer ids against shorter keys."
  },
  {
   "id": "STB-050",
   "severity": "low",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §11; runner/modules/linear/__init__.py:505-520,566-580; runner/linear_client.py:162-186,279-290",
   "evidence": "The STB-029 fix evicts archived ids and makes only the poller's *carry-over* skip the persisted `archived_ids`. The poller still rebuilds `new_cache` from `client.fetch_issues(...)` (lines 505-520) and commits it with `self.issues_cache.update(new_cache)` plus `_sync_cache_to_local()` (lines 566-580). The team/all-issues GraphQL queries pass no `includeArchived: false` (linear_client.py:162-186,279-290), so if Linear returns the just-archived issue, it is re-added from the live fetch despite `archived_ids`; the trash chip and §2.3's 'absent from cache' rule then stop working while `tasks.json` is rewritten.",
   "fix": "Filter `archived_ids` while building `new_cache` (and before `_sync_cache_to_local`) in addition to the carry-over, and/or add `includeArchived: false` to the `issues` queries so an archived issue never re-enters the poll."
  },
  {
   "id": "STB-051",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §3.3; runner/app.py:4214-4224",
   "evidence": "The plan says the existing `bound`/`_run_project_ticket` block is replaced for intent cards, but it does not say how the card/ticket lock is chosen. The existing lock block takes `ticket_lock` only when `bound.get('issue_identifier')` is set and `card_lock` only in the `elif not bound` branch (app.py:4216-4219). For the §2.5 record (and any `project_key`-only inline binding, which the plan explicitly says must not reach the helper) `bound` is the `original` record because it has `project_key`, so it has no `issue_identifier` and `bound` is truthy: neither lock is taken. A concurrent board drag to In Progress (which reserves the card via `reserve_card`/card_lock) can then dispatch the same card while the session reply runs, and the project `project_lock` is also never taken on the generic path.",
   "fix": "State explicitly that a generic intent card still acquires the card lock (or the ticket lock when the durable binding has an `issue_identifier`) before launch, and compute the routing decision from the durable binding while leaving the lock decision independent of the inline `project_key`."
  }
 ],
 "coverage": [
  "Verified plan SHA256 f73b4eb5… and read the full plan plus the round-1..5 review log and dispositions so new findings start at STB-046.",
  "Read runner/app.py: api_run_retry/_do_retry_attempts/_dispatch_cmd, _get_task_agent_lock, _build_resume_cmd, _project_cmd, run_agent_process, _stream_claude_run, _parse_agent_output, _parse_project_output, _agent_model, _compute_token_cost, _run_project_ticket(_locked), _records_unsafe, _effective_project/_ticket_confidential/_durable_binding, _claim_session/_release_session/_live_session_ids, card_run_for_session, _latest_record/api_run_events, api_run_detail, api_run_set_status/restore, api_run_cancel, record_interactive_ended, _latest_linear_runs, the auth and maintenance gates.",
  "Read runner/projects.py: session_target, session_lock, check_session_idle, claude_sessions/codex_sessions, project_sessions, _session_roots, _slug, _under/_under_resolved, SESSION_FRESH_S, worktree_path.",
  "Read runner/project_runs.py: agent_cli, common_dir, project_prompt, run_agent, post_run, closing_check, committed_seeds usage.",
  "Read runner/modules/linear/__init__.py: poller/terminal carry-over/_sync_cache_to_local, _normalize_linear_issue, _project_labels, _compose_issue_description, _tracker_reset_route, _issues_get/_issues_post/_bg_sync_to_linear, _issues_patch/_issues_patch_reserved, _dispatch_issue_held, push_state/_push_sync/_push_linear, _is_confidential_issue, start_background prepopulation; runner/linear_client.py (queries/mutations, create_issue, ensure_label, fetch_issues, fetch_projects); runner/modules/linear/local_tracker.py; runner/reset_gen.py.",
  "Read runner/templates/index.html: _sessionRow and project-row handlers, refreshJobBoard/_latestLinearRuns/_preferRun/_renderBoardItems/renderTrash, openDetailModal, retryRun/retryFromDetail, _updateDetailRetryLock/_agentLocksRetry, _cardTerm* and _cardTermQuickReply, the reply/dispatch/retry DOM.",
  "Read the earlier plans docs/exec-plans/active/2026-10-15-dashboard-ui-updates.md and docs/exec-plans/completed/2026-10-15-runner-write-safety.md for the C0/C2 and write-safety contracts referenced by the plan."
 ],
 "limitations": [
  "Read-only review: I edited nothing, ran no pytest, launched no runner, exercised no browser and made no Linear API call; no runtime or test result is claimed.",
  "I inspected the cited functions and ranges, not every line of app.py (4,735) or index.html (5,040); findings are grounded in the referenced code.",
  "I did not independently confirm Linear's GraphQL `includeArchived` default; STB-050 is therefore stated conditionally on `fetch_issues` returning archived issues, which the queried fields and the client's lack of `includeArchived: false` make possible.",
  "I could not execute the planned process-argv `ps` detection or the confidential sandbox argv effects; those were reasoned from code.",
  "I did not inspect other sessions' uncommitted work, git branches, or test files beyond a targeted look at tests/test_card_terminal.py and tests/test_project_dispatch.py."
 ]
}```

### Dispositions
Round 6 dispositions (host: Claude). All 6 accepted.
- STB-046: the found-card to-board record sets `agent_session_id = sid` and the session agent, so the latest record and the intent name the same session. Intent continuations are always strict, and the existing guard (app.py ≈4170) passes by construction.
- STB-047: §2.5 `desc` defined. Public → the session title; confidential or unknown → empty (agent marker only), so no session text reaches the tracker.
- STB-048: a no-change run shows no badge unless the badge is red; `verify: pass` is suppressed too.
- STB-049: no generic prefix fallback; only the `[…]` suffix strip plus an explicit Opus 5.5 entry. Unknown ids keep `DEFAULT_PRICE`, so `gpt-5.4-mini` is unchanged.
- STB-050: the poller drops `archived_ids` while building `new_cache`, not only in the carry-over. Observed today: after archiving 92 issues manually (user-approved cleanup), a poll returned none of them, consistent with Linear's default exclusion.
- STB-051: intent cards take the ticket lock (durable binding with an identifier) or the card lock otherwise, independent of routing and inline `project_key`. The generic path also holds `project_lock`.

### Side note: one-time trash cleanup (user-approved "清理垃圾桶", 2026-10-16)
- Archived (not deleted) all 92 Canceled issues of the team in Linear (`issueArchive`, 92/92).
- Removed 90 matching entries from `state/tasks.json` with the runner stopped (backup `~/.agentic-os/backups/trash-1792173432/tasks.json`), then restarted it. The extra entry was AGE-92 "cancel-test": local Todo, Linear Canceled.
- After one poll, none came back; the board lists only AGE-102. Run records and transcripts untouched. Scripts are kept outside the repo.

## Plan review round 7 (DeepSeek)
- Plan SHA256 reviewed: dadb1b842221c8b905699c6e8a4374d1901981745aa74a97a4a4bf21c6f37c23
- Output: `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/stb/review7.out` (parsed: `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/stb/review7.json`)
- Fingerprint before = after `1f5c837963b7c3c53050b7726ebd903cd8b524ee9d384c63477042521bc96713`.
- Verdict: **REVISE**, 4 findings (1 high, 3 medium). STB-046..051 confirmed resolved.

```json
{
 "verdict": "REVISE",
 "summary": "Round-6 dispositions STB-046..051 are present in the plan text and their mechanics match most of the code I read (agent_session_id=sid on the found-card record; §2.5 desc defined; verify badge suppression; explicit Opus price with no generic prefix match; archived_ids dropped while building new_cache; ticket/card lock choice stated). Four material defects remain: the generic confidential reply path still posts the reply and agent output to the tracker as comments, bypassing the project comment gate; the board card's inline Start button still dispatches a fresh run on a resumed Todo card because §5 only hides the detail dispatch group and the board payload never carries resume_ok; the reply lock for a project-labelled card with no durable binding is a card lock while the dispatch/`reserve_card` path takes a ticket lock, so the two do not exclude each other; and the plan never says where the retry gets the resumed session id, while the existing source (`_get_task_agent_lock`) returns None for the todo record the to-board route writes.",
 "findings": [
  {
   "id": "STB-052",
   "severity": "high",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §3.3/§3.4; runner/app.py:4235-4240,4268-4277,4368,4382,4394-4399; runner/project_runs.py:118-138; runner/modules/linear/__init__.py:1485-1490",
   "evidence": "The plan routes confidential session cards that are not in their ticket worktree (main checkout, another folder under the project roots, inline project_key) through the generic path. That path reuses the existing non-bound retry block, which posts the reply verbatim: `_comment_quietly(_post_linear_comment, linear_issue_id, _linear_comment_body(title='Human Feedback', feedback=reply, ...))` (app.py:4268-4277) and `_linear_comment_body(title='AgenticOS Retry', prompt=prompt, output=output)` on completion (app.py:4368), plus timeout/error bodies. `_post_linear_comment` calls `LinearModule.post_comment` (linear/__init__.py:1485-1490), which posts raw to Linear and has no confidential gate; only `project_runs.tracker_comment` suppresses confidential feedback/comment text (project_runs.py:118-138). Concrete failure: Resume a confidential project session whose cwd is the main checkout, type a reply, records are safe so the launch is allowed, and the reply text plus the agent output are written to Linear. This defeats the confidential-tracker policy the plan says it preserves ('template-only tracker comments') and the acceptance that confidential replies be handled per project policy.",
   "fix": "For the generic intent path, resolve the effective binding before launch and route every automatic comment (feedback, run, timeout, error) through `project_runs.tracker_comment(bound, 'feedback'/'Run', ...)` — which returns None/template for a non-False confidential binding — or skip comments entirely for confidential/unknown bindings. Add a test asserting no reply/output text reaches the tracker for a confidential generic session card."
  },
  {
   "id": "STB-053",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §5; runner/templates/index.html:2459-2463,2479,2614-2647; runner/app.py:3880-3895",
   "evidence": "`_buildCard` renders `todoAgentToggle` — a '▶ <agent>' button — for every Todo Linear card with an assigned agent and `!run.unsynced` (index.html:2459-2463,2479). `triggerLinearIssueWithAgent` PATCHes `{state_name:'In Progress'}` (index.html:2614-2647), which dispatches a fresh run, ignoring any `resume_session`. The plan §5 only hides `#detail-dispatch-group` while `resume_ok` holds; it does not suppress this board-level button. §5 also says `resume_ok` is exposed only in the run payload, and `/api/runs/latest-by-issue` (app.py:3880-3895) and `/api/runs?limit=80` never return `resume_ok`/`resume_session`, so the board cannot gate the button even if it wanted to. Concrete failure: click Resume (card lands in Todo), then click the card's '▶ claude' button on the board — it starts a fresh run and abandons the resumed session, contradicting 'a resumed session card offers only the continuation' and the acceptance that replying from Todo continues the same session.",
   "fix": "Carry `resume_ok` (and the forced intent agent) in the board payload (`/api/runs` and `/api/runs/latest-by-issue`), and suppress or repoint `todoAgentToggle` while it holds, so the only board action on a resumed card is the continuation."
  },
  {
   "id": "STB-054",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §3.3 (Locks); runner/app.py:4214-4224; runner/modules/linear/__init__.py:248-272; runner/projects.py:842-873",
   "evidence": "For a §2.5-created card the record carries `project_key`/`confidential` but no `issue_identifier` and no durable binding, so the plan's lock rule makes the reply take `card_lock(card_key)`. A concurrent board drag to In Progress goes through `_issues_patch` → `reserve_card` (linear/__init__.py:248-272), which derives `key` from the `project:<key>` label and takes `ticket_lock(key, issue.identifier)` (lines 262-264). `card_lock` stores `~/.agentic-os/card-locks/<key>.lock` while `ticket_lock` stores `WORKTREE_ROOT/<key>/.meta/<ident>.lock` (projects.py:842-873), so the two are disjoint. Concrete failure: on a confidential or public project session card created by Resume, a concurrent drag to In Progress and the reply both pass their locks and launch two runs (the drag's fresh dispatch and the reply's continuation) on the same card/session. STB-051's stated fix does not close this because the dispatch lock is chosen from the label, not the durable binding.",
   "fix": "Specify that the intent reply acquires the *same* primitive the dispatch uses (`reserve_card`, which selects ticket vs card from the binding/label), or persist an `issue_identifier` binding for the §2.5 card and take that ticket lock, so the reply and the drag serialize."
  },
  {
   "id": "STB-055",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §1,§3.2; runner/app.py:2645-2691,4156-4181,4334",
   "evidence": "The retry derives the session to continue only from `_lock_session_id = _task_lock.get('agent_session_id')`, where `_task_lock = _get_task_agent_lock(task_id)` (app.py:4157-4161). `_get_task_agent_lock` returns None as soon as the latest same-generation record's status is `todo`/`rework` (app.py:2675-2676). The to-board record is `{**latest_record, 'status':'todo', ..., 'resume_session':…}` (§2.4), so it is the newest record and `_lock_session_id` stays None. The plan never says to take the id from `resume_session.id`; §3.2 only says 'Then claim as today', which is exactly the call that uses `_get_task_agent_lock`. Concrete failure: `strict` (which §1/§3 require for the intent) hits the guard at app.py:4168 (`strict and not _lock_session_id`) and returns 409 'no resumable session for this card'; if strict is not set, `_lock_session_id` is None so `_do_retry_attempts` builds a fresh `_ai_command`, violating 'never a fresh session'. Either way the acceptance fails.",
   "fix": "State explicitly that a valid intent sets `_lock_session_id = resume_session['id']` (and forces the agent) before the strict guard and `_claim_session`, bypassing `_get_task_agent_lock` for the todo intent record, and add a test that a to-board card's reply resumes the named id."
  }
 ],
 "coverage": [
  "Verified the plan SHA256 dadb1b842221c8b905699c6e8a4374d1901981745aa74a97a4a4bf21c6f37c23 matches the supplied digest, and read the full plan and the round-1..6 review log with dispositions."
 ],
 "limitations": [
  "Read-only review: I edited nothing, ran no pytest, launched no server, exercised no browser and made no Linear API call; no runtime or test result is claimed.",
  "I inspected the cited functions, not every line of app.py (4,735), index.html (5,040), projects.py (2,065) or linear/__init__.py (1,504); findings are grounded in the referenced ranges.",
  "Linear GraphQL capabilities (projectId on issueCreate, projectCreate, issueArchive, team-scoped project name filter, includeArchived default) were reasoned from the client code, not exercised against Linear.",
  "macOS ps output, process-tree semantics and the confidential sandbox argv effects were reasoned from code, not executed.",
  "I did not inspect other sessions' uncommitted work, git branches, or tests beyond test_card_terminal.py/test_reset_gen.py/conftest.py; the plan's new tests do not exist yet, so the planned 'full suite passes' line is unverified."
 ]
}```

### Dispositions
Round 7 dispositions (host: Claude). All 4 accepted.
- STB-052 (high): on the generic intent path every automatic comment (feedback, run, timeout, error) goes through `project_runs.tracker_comment(binding, …)` with the effective binding, so a confidential or unknown binding gets the template or nothing. The raw `_linear_comment_body` posts are not used for intent cards.
- STB-053: the board payload (`/api/runs`, `/api/runs/latest-by-issue`) carries `resume_ok` and the intent agent. While they hold, the inline ▶ button opens the reply instead of `triggerLinearIssueWithAgent`.
- STB-054: the intent reply takes `reserve_card`, the same primitive as a drag to In Progress, which picks the ticket or card lock from binding and label. Reply and drag therefore always contend for the same lock.
- STB-055: a valid intent sets `_lock_session_id = resume_session.id` and the forced agent before the strict guard and `_claim_session`, bypassing `_get_task_agent_lock` (which returns None on the todo record).

## Plan review round 8 (DeepSeek)
- Plan SHA256 reviewed: 6867495d3e52130eb33dfa7394298a0c333ad72287c5dab8ac0cd76705ad3886
- Output: `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/stb/review8.out` (parsed: `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/stb/review8.json`)
- Fingerprint before = after `f66a41d409a169f3cbffddcbaa00587614c7e501f49c0b0b97bce4a24dcb8ae3`.
- Verdict: **REVISE**, 4 findings (1 high, 2 medium, 1 low). STB-052..055 confirmed resolved.

```json
{
 "verdict": "REVISE",
 "summary": "Round-7 dispositions STB-052..055 are present in the plan text and their mechanics match the code paths I read: §3.4 routes generic-intent comments through project_runs.tracker_comment; §5 hides #detail-dispatch-group and repoints todoAgentToggle; §3.3 takes reserve_card; §3.2 sets _lock_session_id=resume_session.id before the strict guard. New material defects remain in the same UI/hand-off area and in the §2/§2.5 record shape. The strongest: a second board control (the agent badge) still dispatches a fresh run on a resumed Todo card; the §2.2 running check references the issue before §2.3 resolves it; and the §2.5 record omits issue_identifier, so an opened interactive tab on such a card holds neither the ticket nor the card lock and a concurrent drag/reply is not excluded.",
 "findings": [
  {
   "id": "STB-056",
   "severity": "high",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §5; runner/templates/index.html:2449-2456,2614-2629",
   "evidence": "The plan only fixes the board's inline `▶ <agent>` button (`todoAgentToggle`, index.html:2459-2463). The card also renders an `agent-badge` whose `agentBadgeClick` (index.html:2449-2453) is set to `onclick=\"...triggerLinearIssueWithAgent('...','<agent>')\"` whenever `!agentLocked && state === 'todo' && badgeAgent`. A resumed Todo card satisfies all three: `refreshJobBoard` sets `_is_linear_issue`, the to-board record copies the session `agent`, and the issue carries `preferred_agent` (the agent marker §2.5 writes). `triggerLinearIssueWithAgent` PATCHes `{preferred_agent, state_name:'In Progress'}` (index.html:2619-2629), which `_issues_patch` treats as a fresh dispatch, abandoning the `resume_session` intent. §5's fix (repoint `todoAgentToggle`, hide `#detail-dispatch-group`) does not touch this second control. Concrete failure: click Resume (card lands in Todo), then click the agent badge on the card — a fresh run starts and the resumed session is dropped, contradicting the acceptance that a resumed card offers only the continuation.",
   "fix": "Gate `agentBadgeClick` on `!run.resume_ok` (repoint it to `openDetailModal(run.run_id)` with the reply box focused, exactly like `todoAgentToggle`), or do not render the badge's dispatch onclick while a valid intent holds."
  },
  {
   "id": "STB-057",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §2.2/§2.3; runner/app.py:3763-3767",
   "evidence": "§2.2 lists as the third running check `the issue's latest run is `running``, but the issue/card is only resolved in §2.3 ('Find the card'). At step 2 there is no issue object to test, so a literal implementation must either drop this check or evaluate it after step 3, contradicting the stated 'lock, then check' ordering that STB-027/STB-008 fixed. Concrete case: a card whose latest run is `running` on a different session (or a run whose `job` has no `agent_session_id` yet and whose session was never put in `_SESSION_CLAIMS`, e.g. a project launch before `on_session` fires) passes bullets 1-2 because `_live_session_ids()` is keyed by `(agent, sid)`. Without bullet 3, `to-board` moves the issue to Todo and writes the intent while that run is in flight; the reply can then start a second writer/run on the same card, and the running run's later review push is silently dropped by the generation bump.",
   "fix": "Restructure: resolve the card (§2.3) inside the held `session_lock` first, then evaluate all three running checks against that resolved issue (including its latest run status) before any move or record append; state explicitly that the running check runs after, not before, card resolution."
  },
  {
   "id": "STB-058",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §2.5; runner/modules/pty/__init__.py:340-389",
   "evidence": "§2.5's new run record is specified as carrying only `run_id/task_id`, `linear_issue_id`, `status`, `skill`, `agent`, `agent_session_id`, `resume_session`, the project binding (`project_key`, `confidential`) and `source` — it omits `issue_identifier`. `open_terminal` (pty/__init__.py:350-352) overwrites the browser ticket with `rec.get('issue_identifier') if rec.get('project_key') else None`; with `project_key` set and no `issue_identifier`, and a session in the main checkout (cwd under `project.path`, not under `WORKTREE_ROOT/<key>`), `ticket` stays None, so no `ticket_lock` is entered; then the card-lock fallback `if not rec.get('project_key'): card_lock(...)` (lines 386-389) is skipped because `project_key` is truthy. The tab therefore holds only `project_lock`. A concurrent drag to In Progress goes through `_issues_patch` → `reserve_card`, which derives `key` from the `project:<key>` label and takes `ticket_lock(key, issue.identifier)` — a lock the tab does not hold — and `card_locked`/`_issue_is_running` do not see the tab, so a fresh run launches while the interactive tab is live on the same session/transcript. This affects both §2.5 cards and cards first brought to the board by a previous §2.5 run.",
   "fix": "Write the tracker issue's `identifier` as `issue_identifier` on the §2.5 record (the issue is created synchronously and its identifier is available), so the tab takes the same ticket lock as the reply/dispatch; or make `open_terminal` fall back to `card_lock(rec.linear_issue_id)` whenever a `project_key`-bearing record resolves no ticket."
  },
  {
   "id": "STB-059",
   "severity": "low",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §3.1/§5; runner/templates/index.html:2419,2532-2554",
   "evidence": "`_buildCard`'s `canRetry = !isRunning && !!run.latest_run_id` (index.html:2419) is state-independent, and `sessionLocked` is forced false when `state === 'todo'` (line 2536). On a resumed Todo card `latest_run_id` is set, so the card renders all three `↺ Claude/Codex/DeepSeek` buttons. §3.1 says 'the agent buttons for such a card show only that agent'; clicking a non-intent button calls `retryRun(run.run_id, 'codex')`, which §3.1 makes return 409. The UI thus shows buttons that always fail with an alert.",
   "fix": "Include the intent agent when computing `sessionLocked`/`_cardAgents` for a card with `run.resume_ok`, so only the intent agent's retry button renders."
  }
 ],
 "coverage": [
  "Verified the plan SHA256 6867495d3e52130eb33dfa7394298a0c333ad72287c5dab8ac0cd76705ad3886 and read the full plan plus the round-1..7 review log and dispositions (STB-001..055).",
  "Read app.py: _get_task_agent_lock (2645), _records_unsafe (2815), run_agent_process (2604), _run_project_ticket/_locked (3117-3285), _build_resume_cmd (3293), _claim_session/_release_session/_live_session_ids (3753-3767), _latest_linear_runs (380), api_runs/api_runs_latest_by_issue (3842-3895), api_run_detail (3898), api_run_set_status/api_run_restore (3943-4029), api_run_retry (4090-4406), _write_run_log (2105), _compute_token_cost (2089), _parse_project_output (2711), _stream_claude_run (2457), _parse_agent_output (2396), _load_runs_from (618).",
  "Read projects.py: project_lock (318), ticket_lock/card_lock/card_busy (842-889), _session_roots/claude_sessions/codex_sessions/project_sessions (1361-1577), session_lock/session_target/check_session_idle (1597-1663).",
  "Read runner/modules/pty/__init__.py open_terminal and term handlers (280-422, 506-561); runner/modules/linear/__init__.py (_project_labels, reserve_card, _tracker_reset_route, polling loop, _issues_get/_issues_post, _issues_patch, _dispatch_issue_held, push_state); runner/project_runs.py (tracker_comment, post_run, run_agent); runner/linear_client.py; runner/modules/linear/local_tracker.py; runner/reset_gen.py.",
  "Read index.html: _sessionRow/project row (1105-1156, 1437-1489), _buildCard/agent badge/todoAgentToggle (2390-2562), setIssueAgent/triggerLinearIssueWithAgent (2571-2647), refreshJobBoard/_latestLinearRuns (2261-2285, 2667-2734), openDetailModal/retryRun/retryFromDetail (2886-3178), _moveLinearIssueToColumn (1983-2003), openResumeTab/_cardTermInteractive/_cardTermQuickReply (4259-4600)."
 ],
 "limitations": [
  "Read-only review: no files were edited, no tests or pytest were run, no server was launched and no browser/Linear API call was made; no runtime or test result is claimed.",
  "I inspected the cited functions and ranges, not every line of app.py (4,735), index.html (5,040), projects.py (2,065), linear/__init__.py (1,504) or linear_client.py (401); findings are grounded in the referenced ranges.",
  "The plan's new code (to-board route, session_in_use, reserve_card hand-off, §10/§11 Linear mutations) does not exist yet, so correctness is judged against the current callers/writers and the plan text.",
  "Linear GraphQL capabilities claimed in §10/§11 (projectId on issueCreate, team-scoped project name lookup, projectCreate/issueArchive, includeArchived default) were reasoned from linear_client.py, not exercised against Linear.",
  "macOS `ps`/process-tree semantics and the confidential sandbox argv effects were reasoned from code, not executed.",
  "I did not inspect other sessions' uncommitted work, git branches, or the test suite beyond the referenced helpers; the planned 'full suite passes' line is unverified."
 ]
}```

### Dispositions
Round 8 dispositions (host: Claude). All 4 accepted.
- STB-056 (high): while `resume_ok` holds, every board dispatch control on the Todo card opens the reply instead of dispatching: the inline ▶ (`todoAgentToggle`) and the `agent-badge` (`agentBadgeClick`).
- STB-057: the third running check (issue's latest run running, reserved or running via `_issue_is_running`/`card_locked`) runs after step 3 resolves the card, inside the lock and before any move or append.
- STB-058: the §2.5 record carries `issue_identifier`, so the tab, the reply and a drag all take the same `ticket_lock`. Routing still uses only the durable binding.
- STB-059: `_buildCard` treats a resumed card as agent-locked to the intent agent, so only that `↺` button renders.

## Plan review round 9 (DeepSeek)
- Plan SHA256 reviewed: 6f21c7daee5cccb6b8f4cffb35d403c61046e682fa594a2584775af022e8ca60
- Output: `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/stb/review9.out` (parsed: `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/stb/review9.json`)
- Fingerprint before = after `52c692ab21d2d15b7fc2f5a50ab606198f440943fd9a49277bdfe2ee2a19e2b0`.
- Verdict: **REVISE**, 4 findings (3 medium, 1 low). STB-056..059 confirmed resolved.

```json
{
 "verdict": "REVISE",
 "summary": "Round-8 dispositions STB-056..059 are present in the plan text and match the code I read: §2.2's third running check is explicitly deferred until after card resolution (STB-057); §2.5's record now carries `issue_identifier` so the tab/reply/drag share the ticket lock (STB-058); §5 gates both `todoAgentToggle` and `agentBadgeClick` on `resume_ok` (STB-056) and makes the board card agent-locked to the intent agent (STB-059). New material defects remain in the same hand-off area and in the record shape: a card reply never forces `strict`, so a failed continuation silently falls back to a fresh session; reply records on the generic path omit `issue_identifier`, re-opening STB-058 for the Terminal tab; and a resumed Todo card can still be dragged to In Progress, which dispatches fresh and abandons the resumed session. A smaller §9 gap: the promised card identifier has no named source in projects.py. Verdict: REVISE.",
 "findings": [
  {
   "id": "STB-060",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §1/§3.2/§5; runner/app.py:4124,4157-4172,4334-4352; runner/templates/index.html:3145-3158",
   "evidence": "`strict = bool(req_data.get(\"strict\"))` (app.py:4124). The plan's card-reply path is `retryRun` (index.html:3145), which POSTs `{agent, reply, attachments}` at 3153 with no `strict`; only the quick reply sends `strict: true` (index.html:4591). §3.2 only says a valid intent sets `_lock_session_id` \"before the strict guard\", and §2.4 merely asserts \"intent continuations are always strict\"; nothing sets the `strict` flag server-side. Concrete failure: a valid to-board intent sets `_lock_session_id`, `_build_resume_cmd` is used, the resume fails (session removed/writer-held), and the fallback at app.py:4334 (`_used_resume and not ok and agent != \"dsh\" and not strict and new_run_id in _running_jobs`) rebuilds `_ai_command` (a fresh session) and records `review` (line 4350). That violates the acceptance \"never a fresh session; a failed continuation is an error\" and §1's strict-continuation rule.",
   "fix": "When the validated intent is present, force `strict = True` in `api_run_retry` before the strict guard/`_claim_session` (do not rely on the request body), and add a test that a card reply with no `strict` in the body is still strict and never falls back."
  },
  {
   "id": "STB-061",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §3.4; runner/modules/pty/__init__.py:350-352,373-389; runner/modules/linear/__init__.py:262-264",
   "evidence": "§3.4 specifies the reply record fields as `agent_session_id`, `linear_issue_id`, \"the binding\" and `source: \"session\"` — no `issue_identifier` — and §3.3 says a generic card's binding is only `project_key`/`confidential`. `open_terminal` sets `ticket = rec.get(\"issue_identifier\") if rec.get(\"project_key\") else None` (pty:350-352). With `project_key` truthy and no identifier, line 373 (`if ticket and project:`) takes no ticket lock and line 388 (`if not rec.get(\"project_key\")`) skips the card-lock fallback, so the interactive tab holds only the shared `project_lock`. A concurrent drag then goes through `_issues_patch` → `reserve_card`, which takes `ticket_lock(key, issue.identifier)` (linear:262-264) — a lock the tab does not hold — and `card_locked`/`_issue_is_running` do not see the tab, so a fresh run launches while the interactive tab is live on the same session/transcript. This is exactly the STB-058 failure, but for reply records rather than the §2.5 record.",
   "fix": "Carry the card's tracker `identifier` as `issue_identifier` on every intent and reply record (as §2.5 now does), and/or make `open_terminal` fall back to `card_lock(linear_issue_id or task_id)` whenever a `project_key`-bearing record resolves no ticket."
  },
  {
   "id": "STB-062",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §5; runner/templates/index.html:2391-2405,1838-1875,1983-2003; runner/modules/linear/__init__.py:1133-1146,782-790",
   "evidence": "§5 claims \"every board control that would dispatch the Todo card opens the card detail ... instead\" and \"a resumed session card offers only the continuation\", but it names only `todoAgentToggle` and `agentBadgeClick`. A `_is_linear_issue` card is unconditionally `draggable = true` (index.html:2392); the column drop handler accepts a linear issue in every column (1838-1866) and `_moveLinearIssueToColumn` PATCHes `{state_name:'In Progress'}` (1993-2002), which `_issues_patch` treats as a dispatch (`reserve_card` → `_start_dispatch`, linear:1133-1146/782-790) with the issue's `preferred_agent`, ignoring `resume_session`. Concrete failure: click Resume (card lands in Todo with `resume_ok`), then drag the card onto In Progress — a fresh run starts and the resumed session is abandoned, contradicting the acceptance that a resumed card offers only the continuation.",
   "fix": "While `run.resume_ok` holds, disable the card's drag (or refuse/repoint the In Progress drop to `openDetailModal` with the reply focused), and add this path to the STB-056 test."
  },
  {
   "id": "STB-063",
   "severity": "low",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §9; runner/projects.py:1417-1446,1454-1484,1574-1577; runner/app.py:380,3560-3568",
   "evidence": "§9 requires that a listed headless row \"shows the card's identifier before the title (e.g. `AGE-102 · 牛熊判断`)\" and derives the id set from `RUN_LOG`. But the run record stores only `linear_issue_id` (a Linear UUID), and the session rows are built in `projects.py` (`claude_sessions`/`codex_sessions`/`project_sessions`), which has no access to `app`'s `issues_cache` (the only place UUID→`identifier` is held). The plan names no source or plumbing for the identifier. Failure: the required label cannot be produced from the stated data; a builder must invent a cross-module lookup (circular-import risk) or silently drop the acceptance criterion.",
   "fix": "State the identifier source explicitly (e.g. read the `state/tasks.json` mirror, which is written by `_sync_cache_to_local`, from `projects.py`, or have `api_projects` pass an id→identifier map into `project_sessions`), or relax the requirement."
  }
 ],
 "coverage": [
  "Verified plan SHA256 6f21c7daee5cccb6b8f4cffb35d403c61046e682fa594a2584775af022e8ca60 and read the full plan plus the round-1..8 review log and dispositions (STB-001..059), so new findings start at STB-060.",
  "Checked round-8 fixes in code: §2.2 third running check placement vs `_issue_is_running`/`card_locked`/`reserve_card` (linear/__init__.py:281-294,597-602); §2.5 `issue_identifier` vs `open_terminal` (pty/__init__.py:317-422); §5 `resume_ok` gating vs `todoAgentToggle`/`agentBadgeClick`/`_buildColCard` (index.html:2385-2562) and the drop handler (1838-1875,1983-2003).",
  "runner/app.py: api_run_retry (4090-4406), strict handling and resume-failure fallback (4124,4157-4172,4313-4352), _task_agent_lock (2645-2691), _run_project_ticket(_locked) (3117-3285), _build_resume_cmd/_project_cmd (2701-2708,3293-3302), run_agent_process (2604-2642), _stream_claude_run (2457-2506), _parse_project_output (2711-2738), _compute_token_cost (2089-2102), _records_unsafe (2815-2821), _durable_binding/_ticket_confidential (2779-2805), _write_run_log (2105-2174), load_runs/_load_runs_from (618-660), _latest_linear_runs (380-399), api_run_detail/api_run_set_status/api_run_restore (3899-4029), api_run_events/_latest_record/card_run_for_session (3544-3599), record_interactive_ended (4066-4086), api_run_history (4409-4468).",
  "runner/projects.py: session_lock/session_target/check_session_idle (1597-1662), _session_roots (1361-1362), claude_sessions/codex_sessions/project_sessions (1417-1577), ticket_lock/card_lock/card_busy (842-890), project_lock (318-334).",
  "runner/project_runs.py: agent_cli (77-98), tracker_comment (118-138), post_run (481-532).",
  "runner/modules/linear/__init__.py: reserve_card/card_locked/_tracker_reset_route (248-357), poller/terminal carry-over/_sync_cache_to_local (434-581,1360-1429), _issue_is_running/_remember_local_override (597-633), _dispatch_issue_held (706-895), _issues_post/_bg_sync_to_linear (979-1065), _issues_local_patch/_issues_patch (1087-1243); runner/linear_client.py (queries/mutations, create_issue, ensure_label, fetch_issues, fetch_projects); runner/modules/linear/local_tracker.py; runner/reset_gen.py.",
  "runner/templates/index.html: _renderProjectsInto/_sessionRow (1105-1156), board drag/drop (1777-1881), _buildColCard/agent badge/todoAgentToggle/retry buttons (2385-2562), refreshJobBoard/_latestLinearRuns/_renderBoardItems/renderTrash (2660-2884), openDetailModal (2886-3073), dispatchFromDetail/retryRun/retryFromDetail (3125-3178), _cardTermInteractive/_cardTermQuickReply (4494-4600).",
  "Read the earlier plans docs/exec-plans/active/2026-10-15-dashboard-ui-updates.md and docs/exec-plans/completed/2026-10-15-runner-write-safety.md as referenced by the plan."
 ],
 "limitations": [
  "Read-only plan review: I edited nothing, ran no pytest, launched no runner, exercised no browser and made no Linear API call; no runtime or test result is claimed and the plan's \"full suite passes\" line is unverified.",
  "I inspected the cited functions and line ranges, not every line of app.py (4,735), index.html (5,040), projects.py (2,065) or linear/__init__.py (1,504); findings are grounded in the referenced code.",
  "The plan's new code (to-board route, session_in_use, intent/record fields, §10/§11 mutations) does not exist yet, so correctness is judged against the current callers/writers and the plan text.",
  "Linear GraphQL capabilities (team-scoped project lookup, projectCreate, issueArchive, includeArchived default) were reasoned from linear_client.py, not exercised against Linear.",
  "macOS ps/ppid process-tree semantics and the confidential sandbox argv effects were reasoned from code, not executed.",
  "I did not inspect other sessions' uncommitted work, git branches, or the test suite beyond the referenced helpers; no live to-board/reply/drag race was executed."
 ]
}```

### Dispositions
Round 9 dispositions (host: Claude). All 4 accepted.
- STB-060: a valid intent forces `strict = True` server-side, regardless of the body, together with `_lock_session_id` and the agent, before the strict guard and the claim.
- STB-061: every intent and reply record carries `issue_identifier`, so `open_terminal`, the reply and a drag share the ticket lock.
- STB-062: while `resume_ok` holds, a drop onto In Progress opens the reply instead of PATCHing. Other drops work normally; a drop into Todo voids the intent through the gen bump.
- STB-063: §9 identifiers come from an id→identifier map that `api_projects` builds from `issues_cache` (and record `issue_identifier`) and passes into `project_sessions`; `projects.py` never imports `app`.

## Plan review round 10 (DeepSeek)
- Plan SHA256 reviewed: ffd5417c995b1f8c500eab4d89e1b384f27a9ace6182e2267d111041ca6c85c4
- Output: `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/stb/review10.out` (parsed: `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/stb/review10.json`)
- Fingerprint before = after `8273977861ad74a0513f3e086e9c1f2d248f028c4800084ced15576f869b0567`.
- Verdict: **REVISE**, 6 findings (5 medium, 1 low). STB-060..063 confirmed resolved.

```json
{
 "verdict": "REVISE",
 "summary": "Round-9 dispositions STB-060..063 are present in the plan text: §3.2 forces strict/_lock_session_id/agent server-side (STB-060), §3.6 carries issue_identifier on reply records and §2.5 on new-card records (STB-061), §5 repoints the In-Progress drop to the reply (STB-062), and §9 names api_projects as the id→identifier plumbing with no projects→app import (STB-063). New material defects remain: §10 contradicts its own acceptance for the default Linear Project; §1's 'issue latest run record' predicate is not defined against the interactive_ended audits the board skips, so a natural server implementation voids a live intent and starts a fresh session; §2.4's intent record still omits issue_identifier (incomplete STB-061 fix); §9's live-run id set has no carrier now that projects.py must not import app; §2.4 requires a generation bump that no named mechanism performs; and §2.5 names no source for the session title. Verdict: REVISE.",
 "findings": [
  {
   "id": "STB-064",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §10; runner/linear_client.py:98-110,386-400; runner/modules/linear/__init__.py:1022-1032",
   "evidence": "The acceptance requires 'confidential and unbound ones stay in the default Project', and §10 repeats 'Unbound tasks and confidential projects stay in the default `project_slug` Project'. But §10's mechanism passes `project_id` only for named projects ('the \"+\" form with a project and §2.5 pass `project_id` on create'); the new `create_issue(..., project_id=None)` adds `projectId` only when a value is passed, and today's create mutation/variables have no project at all (linear_client.py:98-110,386-400). `_bg_sync_to_linear` also calls `create_issue(tid, title, desc, label_ids=...)` with no project (linear/__init__.py:1032). An unbound or confidential issue is therefore created in no Linear Project, not the configured `project_slug` Project.",
   "fix": "Resolve `tracker.project_slug` to a project id via find_project/create_project and pass it as the default `project_id` for unbound and confidential creates (never create a same-named Project for a confidential project), or correct the acceptance/§10 text to 'no Linear Project'."
  },
  {
   "id": "STB-065",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §1/§2.4; runner/app.py:380-399,4066-4086; runner/templates/index.html:2271-2285",
   "evidence": "§1 validates the intent only when 'it is on the issue's **latest** run record', and §2.4 pins 'latest' to 'the run the board shows'. The board's latest predicate is `_latestLinearRuns`, which explicitly drops `interactive_ended` entries (index.html:2275). The server helper `_latest_linear_runs` (app.py:380-399) only skips archived records; it returns the newest record even when that is an `interactive_ended` audit (audits are written with a fresh run_id by `record_interactive_ended`, app.py:4066-4086). Concrete failure: click Resume (intent on run R), open then close the card's Terminal tab (audit A on the issue), then reply from the card — a guard implemented with `_latest_linear_runs` sees A, not R, so the valid intent is voided; `_get_task_agent_lock` returns None for the `todo` record, `_lock_session_id` stays None and the launch falls back to a fresh session, directly violating 'never a fresh session'.",
   "fix": "State that the intent's 'issue latest run record' predicate is the board's (skips both `interactive_ended` and archived records), and if a server helper is used make it skip audits; add a test that a card reply after opening/closing the card's interactive tab still continues the same session."
  },
  {
   "id": "STB-066",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §2.4; runner/modules/pty/__init__.py:350-352,373-389; runner/modules/linear/__init__.py:262-264",
   "evidence": "Round-9 STB-061 states 'every intent and reply record carries `issue_identifier`', but §2.4's explicit record is `{**latest_record, status: \"todo\", agent_session_id: sid, agent: <session agent>, resume_session, reset_gen, to_board: true}` and never sets `issue_identifier`; it is present only if the copied `latest_record` already had it. For a card whose latest record has `project_key` but no `issue_identifier` (any pre-feature record, or a path that did not persist the binding), `open_terminal` sets `ticket = rec.get('issue_identifier') if rec.get('project_key') else None` -> None (pty:350-352), and line 388 (`if not rec.get('project_key')`) skips the card-lock fallback because `project_key` is truthy, so the interactive tab holds only `project_lock`. A concurrent reply/drag `reserve_card` takes `ticket_lock(key, bound/issue identifier)` (linear/__init__.py:262-264) — a lock the tab does not hold — so both run on the same session/transcript, re-opening STB-058/061.",
   "fix": "Set `issue_identifier` explicitly in §2.4 (`bound['issue_identifier']` or the resolved issue's identifier), as §2.5 and §3.6 already do, and/or make `open_terminal` fall back to `card_lock(linear_issue_id or task_id)` whenever a `project_key`-bearing record resolves no ticket."
  },
  {
   "id": "STB-067",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §9; runner/app.py:3614-3620,3763-3767; runner/projects.py:1574-1577",
   "evidence": "§9 says the listed/resolvable id set is '`RUN_LOG` ... plus the live ids of running jobs and session claims', and STB-028 explicitly requires a still-running run to be listed. But the only plumbing STB-063 names is `api_projects` passing an id→identifier map into `project_sessions(project, labels=...)`; the live ids live in app.py (`_running_jobs`, `_SESSION_CLAIMS`, `_live_session_ids`, app.py:3763-3767) and `projects.py` must not import app. `project_sessions` (projects.py:1574) takes no id set, and `api_projects` currently calls it bare (app.py:3618). A board-launched headless run writes its run record only when it ends (`_write_run_log` runs after the process), so while it runs `claude_sessions`/`session_target` cannot see its id: the session is neither listed under its project nor resolvable by `session_target`, contradicting STB-028 and the acceptance.",
   "fix": "State the carrier for the live set: `api_projects` (and `_session_action`) passes the live `(agent, sid)` set, or the union of RUN_LOG ids and live ids, into `project_sessions`/`session_target`; add the §9 test for a session whose run is still in progress."
  },
  {
   "id": "STB-068",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §1/§2.4; runner/modules/linear/__init__.py:335-357,1431-1450",
   "evidence": "§1 requires every move back to Todo to bump the issue generation, and §2.4 writes `reset_gen` read 'after the move', so the to-board move itself must bump. The two existing bumping sites are the HTTP PATCH wrappers: `_tracker_reset_route`, which bumps only when `request.get_json()['state_name']` maps to todo (linear/__init__.py:341-356), and `api_run_set_status` (app.py:3982-3984). The natural server-side move — `push_state` (linear/__init__.py:1431-1450) or a direct `LinearClient.update_issue_state` — does not bump, and a to-board POST body carries no `state_name`, so reusing the decorator in-process would not bump either. The intent is then bound to the pre-move generation, contradicting the acceptance 'the intent is bound to the new reset generation' and leaving a same-generation stale intent possible.",
   "fix": "State that §2.4 calls `reset_gen.bump(issue)` under the issue lock before its Todo push and `reset_gen.restore` if the move/push fails, and that the record's `gen` is that bumped value; add the found-card gen-bump test."
  },
  {
   "id": "STB-069",
   "severity": "low",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §2.5; runner/projects.py:1611-1651; runner/app.py:3614-3618",
   "evidence": "§2.5 titles a public card with 'the session title' and uses it as `desc`, and the acceptance requires the created issue be 'titled with the session title', but §2.1's only resolver, `session_target`, returns `{agent, id, cwd, path}` (projects.py:1611-1651) and the plan names no title source or whether a client-sent title is trusted. A builder must invent a lookup (e.g. the `title` from the `claude_sessions`/`project_sessions` row) or accept a browser value, so the required title is under-specified.",
   "fix": "Name the title source (for example the `title` on the `claude_sessions`/`project_sessions` row, or add `title` to `session_target`) and state that a client-supplied title/description is ignored for confidential or unknown bindings."
  }
 ],
 "coverage": [
  "Verified plan SHA256 ffd5417c995b1f8c500eab4d89e1b384f27a9ace6182e2267d111041ca6c85c4 and read the full plan plus `docs/exec-plans/active/2026-10-16-session-to-board.review-log.md` (rounds 1-9, STB-001..063 dispositions).",
  "Checked round-9 fixes against code: §3.2 strict/_lock_session_id vs `api_run_retry` strict guard and fallback (app.py:4124,4157-4172,4320-4352); §5 drop/repoint vs the board drop handler and `_moveLinearIssueToColumn` (index.html:1838-1878,1983-2003,2385-2562); §2.5/§3.6 issue_identifier vs `open_terminal` (pty/__init__.py:317-422) and `reserve_card` (linear/__init__.py:248-272); §9 identifier plumbing vs `api_projects`/`project_sessions`/`session_target`/`_session_roots` (app.py:3602-3622, projects.py:1361-1662).",
  "app.py: `_compute_token_cost` (2089), `_write_run_log` (2105), `_ai_command`/`_agent_model`/`_parse_agent_output` (2343-2427), `_stream_claude_run` (2457), `run_agent_process` (2604), `_get_task_agent_lock` (2645), `_project_cmd`/`_parse_project_output` (2701-2738), `_durable_binding`/`_ticket_confidential`/`_records_unsafe` (2779-2821), `_run_project_ticket(_locked)` (3117-3285), `_build_resume_cmd` (3293), `_replay_lines`/`card_run_for_session`/`_latest_record` (3520-3599), `api_projects` (3602), `_claim_session`/`_live_session_ids`/`_session_action` (3753-3785), `api_runs`/`api_runs_latest_by_issue`/`api_run_detail` (3842-3925), `api_run_set_status`/`api_run_restore`/`api_run_cancel` (3942-4063), `record_interactive_ended` (4066), `api_run_retry`/`_dispatch_cmd` (4089-4406).",
  "projects.py: `registered_key`/`ticket_lock`/`card_lock`/`card_busy` (792-890), `record_location_problem` (1322), `_session_roots`/`claude_sessions`/`codex_sessions`/`project_sessions` (1361-1577), `session_lock`/`session_target`/`check_session_idle` (1597-1663).",
  "linear/__init__.py: `_project_labels`/`reserve_card`/`card_locked`/`_tracker_reset_route` (211-357), poller and terminal carry-over (463-588), `_issue_is_running`/`_remember_local_override` (597-643), `_dispatch_issue_held` (706-921), `_issues_get`/`_issues_post`/`_bg_sync_to_linear` (945-1065), `_issues_local_patch`/`_issues_patch`/`_issues_patch_reserved` (1087-1243), `push_state`/`_push_sync`/`_push_linear` (1431-1483). linear_client.py (create/ensure_label/update/fetch/projects), local_tracker.py, reset_gen.py, project_runs.py (agent_cli/tracker_comment/post_run), pty/__init__.py (open_terminal).",
  "index.html: `_sessionRow`/project row and delegated handlers (1105-1156,1373-1489), board drag/drop and `_moveLinearIssueToColumn` (1777-2003), `_buildColCard`/agent badge/todoAgentToggle/retry buttons (2385-2562), `refreshJobBoard`/`_latestLinearRuns`/`_renderBoardItems` (2261-2285,2665-2776), `openDetailModal`/retryRun/retryFromDetail (2886-3178), `_cardTerm*`/`_cardTermQuickReply` (4376-4626).",
  "Read the earlier plans `docs/exec-plans/active/2026-10-15-dashboard-ui-updates.md` and `docs/exec-plans/completed/2026-10-15-runner-write-safety.md` for the C2 strict-continuation and single-writer invariants."
 ],
 "limitations": [
  "Read-only plan review: I edited nothing, ran no pytest, launched no runner, exercised no browser and made no Linear API call; no runtime/test result is claimed and the plan's 'full suite passes' line is unverified.",
  "Inspected the cited functions and ranges, not every line of app.py (4735), index.html (5040), projects.py (2065) or linear/__init__.py (1504); findings are grounded in those ranges.",
  "The plan's new code (to-board route, session_in_use, intent/record fields, §10/§11 mutations) does not exist yet, so correctness is judged against the current callers/writers and the plan text.",
  "Linear GraphQL capabilities assumed by §10/§11 (projectId on issueCreate, a team-scoped projects name filter, projectCreate with teamIds, issueArchive, and the archived-exclusion default) were reasoned from linear_client.py, not exercised against Linear.",
  "macOS `ps`/ppid process-tree semantics and the confidential sandbox argv effects were reasoned from code, not executed; no live to-board/reply/drag/interactive-tab race was run.",
  "The plan does not state where the `in_use_elsewhere` warning is rendered in the card UI (only the detail payload field and the confirm-on-409 flow); I treat this as an acceptance-rendering gap rather than a separate finding.",
  "I did not inspect other sessions' uncommitted work, git branches, or the test suite beyond the session-reader fixtures referenced above."
 ]
}```

### Dispositions
Round 10 dispositions (host: Claude). All 6 accepted.
- STB-064: `tracker.project_slug` is resolved once to a project id; unbound and confidential creates (`+` path, §2.5, `_bg_sync_to_linear`) pass it as the default `project_id`.
- STB-065: the intent's "latest record" uses the board predicate, which skips `interactive_ended` audits and archived records; any server helper for this check skips audits too.
- STB-066: the §2.4 record sets `issue_identifier` explicitly, from the durable binding or else the issue's identifier.
- STB-067: `api_projects`/`_session_action` compute `board_ids` (run-log ids ∪ live ids) in app.py and pass it into `project_sessions`/`session_target` as a parameter.
- STB-068: §2.4 calls `reset_gen.bump` explicitly under the issue lock before the push, and `reset_gen.restore` on failure.
- STB-069: `session_target` returns the derived title; client titles are ignored.
- New user section, unreviewed: §12, the Projects panel as draggable tabs (localStorage order per viewer, keyboard reorder, server unchanged).

## Plan review round 11 (DeepSeek)
- Plan SHA256 reviewed: d1e840a3ddca0ed5bb0326ac4dcadcd6857958c27a3458096c459b81935570dd
- Output: `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/stb/review11.out` (parsed: `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/stb/review11.json`)
- Fingerprint before = after `e606ead6b57a5175883d3c578c1e5fae6bf693df15e070e3c0b09a9fc69de532`.
- Verdict: **REVISE**, 9 findings (1 high, 8 medium). STB-064..069 reflected, with two residual gaps (now 070/077).

```json
{
 "verdict": "REVISE",
 "summary": "Round-11 review of the §1–§12 plan against app.py, projects.py, project_runs.py, linear/__init__.py, linear_client.py, local_tracker.py, pty/__init__.py and index.html. Round-10 dispositions STB-064..069 are reflected in the plan text, but two leave residual gaps: the STB-067 board_ids carrier is only wired to api_projects/_session_action, and the STB-065 'latest' predicate claim is factually wrong. §12 (new) has a concrete HTML/behavior defect. Nine material new defects found (STB-070..078).",
 "findings": [
  {
   "id": "STB-070",
   "severity": "high",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §2.1, §3.2, §9 (L68, L208); runner/projects.py:1611-1651",
   "evidence": "§9 makes session_target accept a board_ids parameter so headless board sessions are resolvable, and says only api_projects and _session_action pass it (plan L208). But §2.1 resolves the to-board session with `projects.session_target(project, agent, sid)` (plan L68) and §3.2 re-resolves it for a reply without board_ids. Today session_target rejects a claude session whose entrypoint starts with sdk- (projects.py:1630) and a codex row whose source is not cli/vscode (projects.py:1638-1639) — exactly the sdk-cli/exec board runs of §9. So clicking Resume on a board-launched session returns SessionNotFound -> 404 and a reply on it 409s, breaking the §9 acceptance criterion 'A session launched from the board … appears under its project' plus Resume.",
   "fix": "Compute board_ids in the to-board route and in api_run_retry and pass it to session_target (or resolve the session from its run record) so sdk-cli/exec board sessions resolve on both paths."
  },
  {
   "id": "STB-071",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §2.2/§2.4; runner/projects.py:876-890; runner/modules/linear/__init__.py:281-294,335-357",
   "evidence": "§2.2's third running check uses card_locked, which calls projects.card_busy and acquires+releases the ticket lock immediately (a probe, not a hold). A concurrent board drag to In Progress runs _issues_patch, which takes the real lock in reserve_card and then dispatches; _tracker_reset_route only enters reset_gen.issue_lock for a Todo state_name (linear/__init__.py:345-347), not In Progress, so the to-board route's reset_gen.issue_lock does not serialize with it. Between the probe and the move the drag can start a run; to-board then bumps the generation, moves the card to Todo and appends its record, while the dispatch writes its own running/review record under the stale generation. The 'launch not yet claimed -> 409' claim does not close this window.",
   "fix": "After resolving the card, enter and hold reserve_card(issue, issue_id) (or the same ticket/card lock) across the bump, move and append, then close it; do not rely on the card_locked probe."
  },
  {
   "id": "STB-072",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §10 (L220-226); runner/linear_client.py:228-401",
   "evidence": "The LinearClient change list defines find_project(name, team_id) (L221) but L226 resolves the default Project via `find_project_by_slug`, a method never introduced anywhere in the plan. `create_issue(..., project_id=None)` (L220) also has no defined failure signal, and the existing _graphql returns {} on every exception and on RATELIMITED (linear_client.py:249-260), so a caller cannot tell a created project from a failed create; create_issue already returns None on failure. The stated 'resolved once to its project id (find_project_by_slug, cached)' is therefore unimplementable as written.",
   "fix": "Name and specify the slug lookup (e.g. find_project_by_slug(slug, cached)) in the LinearClient section, and define the return/failure contract for find_project/create_project/set_issue_project/archive_issue."
  },
  {
   "id": "STB-073",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §11 (L237); runner/modules/linear/__init__.py:123-140,972-977; runner/modules/linear/local_tracker.py:121-133",
   "evidence": "§11 says 'In the local tracker the issue is removed', but /api/linear/issues in local mode calls LocalTracker.fetch_issues(_linear_poll_states(...)); _linear_poll_states deliberately returns only active states (Backlog/Todo/In Progress/In Review, L123-140) and fetch_issues filters by that list (local_tracker.py:128-130). The trash panel is built from _boardItems (`_cancelledItems = _boardItems.filter(... === 'cancelled')`, index.html:2765), so a local Canceled task never appears. The acceptance 'Empty trash archives every Canceled issue (Linear archive, local delete)' cannot be exercised for the local tracker.",
   "fix": "Include Canceled (and Done/Duplicate) in the local board fetch, or have Empty trash read the local tracker's tasks directly."
  },
  {
   "id": "STB-074",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §2.5 (L97), §10 (L220-223), §11 (L237); runner/linear_client.py:240-260",
   "evidence": "§2.5 requires 'A Linear error → 409 with the reason, nothing written' and §11 archives each Canceled issue, but the newly proposed create_project/set_issue_project/archive_issue would sit on _graphql, which swallows every exception and the RATELIMITED code and returns {} with no reason (linear_client.py:249-260). create_issue already converts failure to None. Callers cannot distinguish success from failure or produce the promised reason, so Empty trash can report an archive that never happened.",
   "fix": "Give each new mutation a typed result (ok/reason or raise) and make the route/Empty trash aggregate failures and report them instead of the bare success shape."
  },
  {
   "id": "STB-075",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §12 (L250); runner/templates/index.html Projects panel (L1105-1127, L1427-1489)",
   "evidence": "§12 says tabs are <button>s in a role=\"tablist\" and that 'An error project shows as a red tab, with Remove inside it'. A <button> nested inside a <button> is invalid HTML (the parser closes the outer button), so the tab's own click/drag target and the Remove control become ambiguous, and native HTML5 drag started from the inner control is undefined. Nested interactive controls also break the tablist semantics §12 relies on.",
   "fix": "Render Remove in the error tab's body (or a sibling control) rather than inside the tab button; keep tabs free of nested interactive elements."
  },
  {
   "id": "STB-076",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §7 (L180); runner/projects.py:1290-1304; runner/project_runs.py:526-531; runner/templates/index.html:208-210,2470",
   "evidence": "run_verify returns status in {pass, fail, timeout} (projects.py:1294-1301) and post_run copies verify['status'] into verify_badge (project_runs.py:529). §7 names only 'verify fail/error' plus the main-checkout and seed warnings as red and adds a neutral .verify-badge.none for 'no check'; run_verify never emits 'error' (post_run_error does), and 'timeout' is omitted from the red set. A timed-out verify would therefore render with the neutral style, contradicting 'failures stay red'.",
   "fix": "Keep timeout in the red set (fail/error/timeout), and state the mapping from run_verify's pass/fail/timeout plus post_run_error/warnings explicitly."
  },
  {
   "id": "STB-077",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §1 (L62); runner/templates/index.html:2271-2285; runner/app.py:380-399",
   "evidence": "§1 claims the board predicate _latestLinearRuns skips 'interactive_ended audits and archived records'. The JS _latestLinearRuns skips only interactive_ended (index.html:2275) and never checks status === 'archived'; the Python _latest_linear_runs defaults include_archived=True and only skips archived when false (app.py:380-399). Because api_run_set_status drops resume_session only on the archived copy, the intent survives on the prior record, so a server check that skips archived records would honour an intent the board/archive no longer shows, or vice versa.",
   "fix": "Specify one exact predicate (skip interactive_ended and archived) and apply it in both the server helper used by the intent check and the board payload's resume_ok computation."
  },
  {
   "id": "STB-078",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §3.3; runner/app.py:4151-4177,4214-4251",
   "evidence": "§3.3 routes only cards that resolve a project_key (durable binding, inline project:<key>, or the record field) and computes effective confidentiality from that binding. A found card whose latest record has linear_issue_id and agent_session_id but no project_key (e.g. a 'No project (runner root)' Linear ticket whose session cwd is a registered project root) is copied by §2.4 with no project binding; §3.3 then has no project to resolve, so _effective_project/agent_cli sandboxing cannot apply and the reply uses the unsandboxed generic command even though the session is listed under a confidential project.",
   "fix": "Derive an effective project/confidentiality floor from the resolved session's registered project (or refuse a session card whose record has no project binding) before building the resume command."
  }
 ],
 "coverage": [
  "Read the full plan and verified its sha256 (d1e840a3…).",
  "runner/app.py: _latest_linear_runs, _compute_token_cost, _agent_model, run_agent_process, _get_task_agent_lock, _run_project_ticket_locked, _build_resume_cmd, /run, api_run_detail, api_projects, _session_action, api_run_set_status, api_run_restore, api_run_retry, _claim_session/_live_session_ids, card_run_for_session, _latest_record, request-token and maintenance gates.",
  "runner/projects.py: session readers (_claude_summary, claude_sessions, codex_sessions), project_sessions, session_lock/session_target/check_session_idle, ticket_lock/card_lock/card_busy, worktree_path, record_location_problem, run_verify, committed_seeds, post_run entry points.",
  "runner/project_runs.py: agent_cli, tracker_comment, post_run, closing_check.",
  "runner/modules/linear/__init__.py: _project_labels, _linear_state_to_board/_linear_poll_states, reserve_card/card_locked, _tracker_reset_route, polling loop carry-over/eviction, _issues_get/_issues_post/_issues_patch, _dispatch_issue_held, _linear_sync_patch, push_state, _sync_cache_to_local.",
  "runner/linear_client.py: create_issue, ensure_label, _graphql error handling, project/state/label queries.",
  "runner/modules/linear/local_tracker.py: create/update/delete/fetch_issues and label/state handling.",
  "runner/modules/pty/__init__.py: open_terminal, issue_identifier/card_key lock selection.",
  "runner/templates/index.html: refreshJobBoard/_latestLinearRuns, _renderProjects/_renderProjectsInto/_sessionRow/_projectBody, project click/keydown/change handlers, loadProjects interval, openDetailModal, retryRun/retryFromDetail, _cardTermQuickReply, verify-badge CSS/render, board drag/drop (LINEAR_STATE_BY_COL_KEY, _moveLinearIssueToColumn).",
  "docs/exec-plans/active/2026-10-15-dashboard-ui-updates.md and docs/exec-plans/completed/2026-10-15-runner-write-safety.md for context.",
  "Round-10 dispositions STB-064..069 checked against the plan text and the code they cite."
 ],
 "limitations": [
  "Read-only review; no tests were run and no claim is made that the suite passes.",
  "Most of the plan describes code that does not exist yet, so several findings are about the plan's internal consistency and its assumptions about existing code rather than a live failure.",
  "The 5,040-line index.html was inspected by targeted greps/open ranges, not read end to end.",
  "No Linear API access: the GraphQL shape of the proposed find_project/create_project/archive_issue queries (e.g. team-scoping of projects, projectCreate teamIds) could not be executed or verified against the live schema.",
  "I could not see rounds 1–9 findings, so I cannot guarantee that none of the above overlaps an earlier unresolved item; each finding is tied to code or plan text inspected this round.",
  "I did not verify the round-10 fixes are reflected in an implementation because the plan is not built; I checked the plan text and the current code it relies on."
 ]
}```

### Dispositions
Round 11 dispositions (host: Claude). All 9 accepted.
- STB-070 (high): to-board (§2.1) and retry (§3.2) both pass `board_ids` to `session_target`.
- STB-071: for a found card, to-board enters and holds `reserve_card(issue)` across bump, move and append; the probe is not relied on.
- STB-072/074: new Linear calls use `_graphql_strict`, which raises `LinearError(reason)`, and typed returns. `find_project_by_slug` and `archive_issue` are named. Routes return 409 with the reason; Empty trash reports per-issue failures.
- STB-073: local-mode Empty trash and its count read Canceled tasks from the local tracker directly.
- STB-075: the error project's Remove lives in the tab body; no nested controls in tabs.
- STB-076: red covers verify fail and timeout, post_run_error, main-checkout warnings and this-run seeds. Neutral: no check. Hidden when nothing changed: pass, no check, uncommitted.
- STB-077: one server predicate, `_intent_latest`, skips interactive_ended and archived records. It is used by the intent check and by the board's `resume_ok`, which is precomputed server-side.
- STB-078: project floor = record binding, else `resume_session.project_key` (always set). Confidential = `project.confidential OR binding confidential is not False`.

## Plan review round 12 (DeepSeek)
- Plan SHA256 reviewed: 1d4bbfbb89129476047a2b2d5d17a3c3eae3ad8f5d088d54a6becfa88db0798a
- Output: `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/stb/review12.out` (parsed: `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/stb/review12.json`)
- Fingerprint before = after `33c00c93904e5e316dd74c61892a00f0f70836636f9bbe629123ca8b4a0dc1ef`.
- Verdict: **REVISE**, 8 findings (1 high, 7 medium). STB-070..078 confirmed reflected.

```json
{
 "verdict": "REVISE",
 "summary": "Reviewed plan 1d4bbfbb against runner/app.py, runner/projects.py, runner/project_runs.py, runner/modules/linear/__init__.py, runner/linear_client.py, runner/modules/linear/local_tracker.py, runner/reset_gen.py, runner/modules/pty/__init__.py and runner/templates/index.html. Round-11 dispositions STB-070..078 are reflected in the plan text and their mechanics mostly check out (to-board/retry pass board_ids; found-card to-board holds reserve_card; new Linear calls are named on _graphql_strict; local Empty trash reads Canceled tasks; Remove lives in the tab body; timeout is red; _intent_latest is named; project floor uses resume_session.project_key). New material defects remain: the §3.3 project-ticket reply re-acquires the ticket lock it already holds via reserve_card (a hard self-conflict), §9 cannot link a session row to its card identifier with the map it specifies, §7's dirty snapshot includes verify's own artifacts, §4 tries to exclude an own claim by run_id from a set that has already discarded run_id, §5 leaves the intent card's ↺ button dispatching with an empty prompt, and the to-board append does not invalidate the 3s runs cache, which can hide resume_ok from the just-opened detail.",
 "findings": [
  {
   "id": "STB-079",
   "severity": "high",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §3.3 ('the intent reply takes ... reserve_card'); runner/app.py:3188,4214-4251; runner/projects.py:842-854",
   "evidence": "For a card whose durable binding owns a ticket worktree, §3.3 says the reply takes reserve_card (an ExitStack holding projects.ticket_lock) and then routes to _run_project_ticket(..., reuse_only=True). But _run_project_ticket -> _run_project_ticket_locked acquires projects.ticket_lock(project.key, ident) unless ticket_hold is passed (app.py:3188), and ticket_lock uses flock(LOCK_EX|LOCK_NB) on a fresh fd and is explicitly non-reentrant across fds (projects.py:842-854). The existing bound path avoids this by passing ticket_hold=card_hold / held.pop_all() (app.py:4217,4248; modules/linear/__init__.py:775). The plan never says the reserve_card hold is handed to the helper, so as written every project-ticket intent reply self-conflicts and fails '.../... is busy', after the tracker flush, or leaks a held lock.",
   "fix": "State that the reserve_card ExitStack is passed to _run_project_ticket as ticket_hold (and to the generic worker as the lifecycle hold), mirroring _dispatch_issue_held/held.pop_all(); or take the ticket lock only inside the routing helper for the worktree branch."
  },
  {
   "id": "STB-080",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §9 ('a linear_issue_id → identifier map ... into project_sessions(project, labels=...)'); runner/projects.py:1574; runner/app.py:3618",
   "evidence": "§9 requires a board-launched session row to show 'AGE-102 · title'. The only plumbing named is api_projects building a linear_issue_id→identifier map (from issues_cache plus run-record issue_identifier) and a board_ids set ('run-log ids ∪ _live_session_ids() ∪ running-job session ids'). projects.py cannot import app and project_sessions(project) currently only reads ~/.claude and ~/.codex; given a set of session ids and an issue→identifier map there is no session→issue key, so the promised identifier cannot be attached to the row. The plan never names a session_id→identifier (or session→issue) map.",
   "fix": "Have api_projects build and pass a session_id → identifier map (derived from the run log's agent_session_id + linear_issue_id/issue_identifier) into project_sessions, and say so explicitly; keep the issue→identifier map only as the source for that lookup."
  },
  {
   "id": "STB-081",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §7.1 ('the worktree is clean (dirty false)'); runner/project_runs.py:495-505,514-527",
   "evidence": "post_run computes dirty before verify (line 495) and then recomputes dirty as the union with the post-verify uncommitted set (line 503, explicitly 'verify may dirty it too (I6-09)'), and the badge order uses that union (lines 524-527). §7 defines 'this run changed nothing' with that dirty. A run whose agent made no change but whose verify command writes a temp/artifact file therefore counts as changed, paints 'uncommitted changes', and the §7.3 suppression ('Hidden when nothing changed: ... uncommitted changes') never fires — contradicting the acceptance 'a project run that changed nothing shows no verify badge'.",
   "fix": "Define 'changed nothing' on run_start_sha..HEAD plus the agent's own uncommitted set captured before verify (or exclude runner/verify-owned paths), and state explicitly that verify's side effects do not by themselves make the run 'changed'; keep the post-verify dirty only for the genuine 'uncommitted changes' red/soft badge when the agent did leave work uncommitted."
  },
  {
   "id": "STB-082",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §4.1; runner/app.py:3753-3767",
   "evidence": "§4.1 says session_in_use checks _live_session_ids() 'with this run's own claim excluded by its run_id key, so a second claimant of the same session still counts'. _live_session_ids() builds set(_SESSION_CLAIMS.values()), i.e. a set[(agent,sid)] that has already discarded run_id, so subtracting the own (agent,sid) pair also drops a second claimant of the same session — the exact thing STB-019 requires to keep counting. A helper that follows the plan literally will let a second run sharing the session through.",
   "fix": "Specify that session_in_use derives the live set from _SESSION_CLAIMS with run == own_run_id skipped (and separately from terminals/running jobs), not by subtracting a pair from _live_session_ids(); state that a second claim with a different run_id still returns a reason."
  },
  {
   "id": "STB-083",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §3.5/§5; runner/templates/index.html:2419,2532-2555",
   "evidence": "§5 makes the board card agent-locked to the intent agent so 'only that agent's ↺ retry button renders'; canRetry is !isRunning && !!latest_run_id (index.html:2419), and that button calls retryRun(run.run_id, key) with no reply (index.html:2552). §3.5 then says an intent reply's prompt is only the reply plus the attachment note, so clicking ↺ sends a strict resume with an empty prompt (claude --resume <id> ... \"\"), which is a continuation with no instruction. The plan neither hides the ↺ controls while resume_ok holds nor defines what prompt they should send.",
   "fix": "While resume_ok holds, render only the reply/send path (hide or disable the ↺ group), or specify the fallback prompt the ↺ button sends (e.g. the copied latest_record prompt) so a strict resume is never issued empty."
  },
  {
   "id": "STB-084",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §2.4/§2.5; runner/app.py:649-660,2167-2172; runner/templates/index.html:2682-2700,3029-3034",
   "evidence": "§2.4 says to append one todo record and §2.5 says to append a linked run record, but neither says the record goes through _write_run_log. _runs_cache is a 3s TTL cache invalidated only inside _write_run_log (app.py:2171). If the route appends to RUN_LOG directly, /api/runs?limit=80 can serve the pre-to-board record for that run_id; refreshJobBoard builds latestRunByIssue from that response and only consults /api/runs/latest-by-issue when it has no entry, so the board item lacks resume_ok. openDetailModal's canRetry then reads boardItem and does not allow todo, hiding the retry/send controls right after Resume until the next refresh.",
   "fix": "Write the to-board record through _write_run_log(..., audit=True) (which also avoids polluting task_state/job_state) or explicitly clear _runs_cache after the append; alternatively attach the precomputed resume_ok to the GET /api/runs/<id> detail payload so the detail does not depend on the board cache."
  },
  {
   "id": "STB-085",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §10 ('Linear dispatch ... calls set_issue_project'); runner/modules/linear/__init__.py:755-778; runner/linear_client.py:240-260",
   "evidence": "§10 has _dispatch_issue_held call set_issue_project for a project:<key> ticket that has no Project, and §10 also says the new Linear calls use _graphql_strict, which raises LinearError on transport errors, GraphQL errors and RATELIMITED. The dispatch path pushes state 'running' (intro, line 763 for the worktree branch) before the run and has no try/except around this new call; a transient rate-limit or schema error would propagate, leaving the ticket In Progress with no run record and no 'could not start' handling, unlike the existing push_state try/except (RWS-007).",
   "fix": "State that set_issue_project is best-effort (catch LinearError, log/record it, continue the dispatch), or call it before push_state('running') and convert failure into an error record + review push like the existing RWS-007 path."
  },
  {
   "id": "STB-086",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-16-session-to-board.md §9 ('board_ids = run-log ids ∪ _live_session_ids() ∪ running-job session ids'); runner/app.py:3763-3767; runner/projects.py:1611-1651",
   "evidence": "§9 mixes bare session-id strings (run-log agent_session_id values) with _live_session_ids(), which returns (agent, sid) tuples. session_target currently keys its own live-id check on (target['agent'], target['id']) (projects.py:1657) and §3.2's in-use check does the same; a naive `sid in board_ids` or `(agent,sid) in board_ids` will miss one of the two sources, so board-launched sdk/exec sessions still 404/409 depending on which source holds the id. The plan does not normalize the set or state the membership rule.",
   "fix": "Specify board_ids as a normalized set of (agent, sid) pairs (or a dict keyed by sid) and the exact membership test session_target uses; keep terminals/running-job/claim entries in the same shape."
  }
 ],
 "coverage": [
  "Verified the plan SHA256 (1d4bbfbb89129476047a2b2d5d17a3c3eae3ad8f5d088d54a6becfa88db0798a) and read the full plan plus the round-11 findings and dispositions in docs/exec-plans/active/2026-10-16-session-to-board.review-log.md.",
  "runner/app.py: _compute_token_cost/MODEL_PRICES, _agent_model, _parse_agent_output, _stream_claude_run, run_agent_process, _get_task_agent_lock, _parse_project_output, _records_unsafe, _run_project_ticket(_locked), _build_resume_cmd/_project_cmd, api_run_detail, api_run_set_status/restore, api_run_retry/_do_retry_attempts/_dispatch_cmd, _claim_session/_live_session_ids/_session_action, card_run_for_session/_latest_record, api_runs/api_runs_latest_by_issue, api_projects, _load_runs_from/_runs_cache, _write_run_log.",
  "runner/projects.py: _session_roots, _claude_summary/claude_sessions/codex_sessions, project_sessions, session_lock/session_target/check_session_idle, ticket_lock/card_lock/card_busy, project_lock, registered_key, worktree_path, committed_seeds, run_verify, record_location_problem.",
  "runner/project_runs.py: agent_cli, project_prompt, tracker_comment, post_run, run_agent, committed_seeds usage, is_sandboxed_codex.",
  "runner/modules/linear/__init__.py: _compose_issue_description, _project_labels, reserve_card, card_locked, _tracker_reset_route, _issue_is_running, _dispatch_issue_held/_start_dispatch, _issues_get/_issues_post/_issues_patch(_reserved), polling carry-over and _sync_cache_to_local, push_state/_push_sync.",
  "runner/linear_client.py: _normalize, _graphql error handling, create_issue, ensure_label, fetch_issues, resolve_state_id_by_team, _QUERY_* shapes.",
  "runner/modules/linear/local_tracker.py: create_issue, update_issue, delete_issue, fetch_issues, raw_transaction.",
  "runner/reset_gen.py: current/bump/restore/issue_lock/is_current.",
  "runner/modules/pty/__init__.py: open_terminal (resume, ticket/card lock selection, issue_identifier), interactive_resume_argv.",
  "runner/templates/index.html: refreshJobBoard/_latestLinearRuns mapping, _buildColCard/canRetry/agent-badge/todoAgentToggle, drop handlers/_moveLinearIssueToColumn, openDetailModal, retryRun/retryFromDetail, _cardTerm* quick reply, trash chip/_cancelledItems, _sessionRow/_renderProjectsInto."
 ],
 "limitations": [
  "Read-only review: no tests were run and no claim is made that the suite passes; the plan describes code that does not exist yet, so findings are about the plan's consistency with current code and its stated mechanics.",
  "The 5,040-line index.html was inspected by targeted greps/open ranges, not end to end.",
  "No Linear API access: the GraphQL shape of the proposed find_project/create_project/set_issue_project/archive_issue queries (e.g. team-scoped projects filtering, projectCreate teamIds) could not be executed or verified against the live schema, and RATELIMITED behavior is inferred from _graphql.",
  "A possible confidentiality gap when a record's durable binding names project A while the resolved session lives in confidential project B (the plan's floor uses the record binding and ignores resume_session.project_key in that case) was considered but not raised as a finding because I could not construct a reachable route that links a session to a card bound to a different project.",
  "I assumed the to-board/retry routes compute board_ids and hold reserve_card as the plan states; I did not verify an implementation because the plan is not built."
 ]
}```

### Dispositions
Round 12 dispositions (host: Claude), under the user's convergence standard ("只修高危，以及在 macOS单用户环境下真能复现的问题"):
- Fixed STB-079 (high): the `reserve_card` hold is handed on (`ticket_hold=held.pop_all()` to `_run_project_ticket`; the lifecycle hold to the generic worker), never re-acquired.
- Fixed STB-080 (reproducible: the requested label could not be produced): app.py builds a `(agent, sid) → identifier` map and passes it as `labels`.
- Fixed STB-081 (reproducible with any project whose verify writes files): "changed nothing" uses the uncommitted set captured before verify.
- Fixed STB-083 (reproducible by one click): no ↺ group while `resume_ok`; the reply box is the only send path.
- Fixed STB-084 (reproducible right after every Resume): to-board records go through `_write_run_log(audit=True)`, which invalidates `_runs_cache`, and the detail payload carries `resume_ok`.
- Fixed STB-086 (deterministic shape mismatch): `board_ids` is a normalized set of `(agent, sid)` pairs.
- Accepted risk STB-082: second concurrent claimant of one session; not reproducible single-user.
- Accepted risk STB-085: transient Linear error in `set_issue_project` during dispatch; injected or rare failure; to be made best-effort at build time.

## Closure of plan review (user decision, 2026-10-16)
- The user said: "定过一个收敛标准：只修高危，以及在 macOS单用户环境下真能复现的问题。要把这个标准也用到 plan".
- Plan review stopped after round 12. Findings per round: 11, 9, 8, 9, 8, 6, 4, 4, 4, 6, 9, 8. Every high finding across all rounds was fixed. Accepted risks STB-082 and STB-085 are listed in the plan.
- The round-12 fixes (STB-079/080/081/083/084/086) were not reviewed again.
- Assurance: third-party DeepSeek review; this is not a claudex cross-provider approval. Building waits for the user's go-ahead.
- Final plan SHA256: ce401a887dd0dda6734f8690606e68a95e214d9418abf2e7983b331cec84dfaa

## Codex plan review — round 1 (2026-10-16)
- User: "已经reset codex usage". The claudex cross-provider plan review now runs on Codex; the DeepSeek rounds above stay third-party.
- Runner result: `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/stb/codex/r1/claudex-4xvvwf5p/result.json`
- Provider codex, codex-cli 0.163.0, session `01a1466b-2eba-7593-8611-2d193cbe787f`, assurance `cross_provider`, requested model: CLI default (observed: unknown), plan SHA256 `ce401a887dd0dda6734f8690606e68a95e214d9418abf2e7983b331cec84dfaa`.
- Verdict: **REVISE**

```json
{
  "verdict": "REVISE",
  "summary": "Four concrete plan defects remain: later replies lose the intended routing, imported cards break interactive terminals, an editor action bypasses continuation, and trash cleanup permits ticket-identifier reuse.",
  "findings": [
    {
      "id": "SBR-001",
      "severity": "high",
      "path": "docs/exec-plans/active/2026-10-16-session-to-board.md:119",
      "evidence": "The routing replacement applies only while resume_session is valid, and §3.6 removes that field after the first reply. A subsequent reply from an imported main-checkout session therefore reaches the existing bound block in runner/app.py:4214–4248. Its inline project_key and issue_identifier cause _run_project_ticket(reuse_only=True): a new card fails because its worktree does not exist; an existing ticket can resume in its ticket worktree instead of the session's folder.",
      "fix": "Separate persistent session routing from the one-shot Todo intent. Apply session resolution, folder selection, policy and strict continuation to subsequent session-card replies until an explicit reset starts fresh."
    },
    {
      "id": "SBR-002",
      "severity": "medium",
      "path": "docs/exec-plans/active/2026-10-16-session-to-board.md:99",
      "evidence": "New imported cards receive project_key and issue_identifier without creating a ticket worktree. The unchanged runner/modules/pty/__init__.py:350–381 interprets those fields as a worktree binding, calls projects.load_binding, and selects that worktree as cwd. Clicking the card's existing Open interactive therefore fails with missing binding metadata. For a bound ticket's main-checkout session, it selects the wrong folder.",
      "fix": "Update terminal backend routing to distinguish the tracker identifier used for locking from an actual worktree binding. Resolve the session cwd server-side, preserve the same card reservation and project policy, and retain the existing Terminal UI."
    },
    {
      "id": "SBR-003",
      "severity": "medium",
      "path": "docs/exec-plans/active/2026-10-16-session-to-board.md:154",
      "evidence": "The listed UI guards omit the issue editor's state selector and Save to Linear action. runner/templates/index.html:3358 populates all team states, and saveLinearIssue at line 3419 PATCHes the selected state directly. Selecting In Progress on a resumed Todo card still reaches _issues_patch_reserved and _dispatch_issue_held, which starts a fresh run without the continuation reply or session checks.",
      "fix": "Guard the editor's In Progress transition while resume_ok holds and focus the reply controls instead. Include this dispatch entry point in the verification checklist."
    },
    {
      "id": "SBR-004",
      "severity": "high",
      "path": "docs/exec-plans/active/2026-10-16-session-to-board.md:248",
      "evidence": "Local trash cleanup deletes tasks while preserving execution state. However, LocalTracker._next_identifier in runner/modules/linear/local_tracker.py:85 derives LOC-n solely from remaining tasks. Run LOC-1 for project P, cancel it, empty trash, then create another task: LOC-1 is reused. The preserved ticket:P/LOC-1 durable binding and projects.create_worktree's reuse behavior can attach the unrelated task to the old branch and worktree.",
      "fix": "Persist a monotonically increasing local identifier counter under the tracker transaction, initialized above all previously allocated identifiers. Never reuse identifiers after deletion; add a delete-create-dispatch regression scenario."
    }
  ],
  "coverage": [
    "Verified the plan file matches the supplied SHA256.",
    "Inspected retry routing, session claims, reset generations, durable bindings, run-log readers/writers, and cancel/stall record ownership.",
    "Traced tracker creation, dispatch, polling, cache mirroring, and local identifier allocation beyond the plan's primary files.",
    "Inspected session resolution, project policy, worktree reuse, PTY admission, terminal metadata, and UI dispatch callers.",
    "Inspected relevant SPEC.md excerpts, verification-badge logic, Claude model parsing, cost lookup, and selected existing test definitions."
  ],
  "limitations": [
    "Static plan review only; no files edited, tests executed, or delegation performed.",
    "The proposed implementation does not yet exist, so runtime behavior and browser interactions were not verified.",
    "Live Linear contracts, installed CLI behavior, and current model pricing were not externally verified.",
    "SPEC.md is a draft and differs from existing lifecycle behavior; pre-existing discrepancies were not reported as new plan defects."
  ]
}
```

### Dispositions
- SBR-001 (high) — accepted, fixed. §1 "Not consumed by a reply"; §3.6; acceptance criterion and test added.
- SBR-002 (medium; reproducible: Open interactive on a new session card) — accepted, fixed. §5 "Backend for session cards"; test added.
- SBR-003 (medium; reproducible via the issue editor) — accepted, fixed. §5 "Issue editor"; test added.
- SBR-004 (high) — accepted, fixed. §11 "Local identifiers are never reused"; test added.


## Codex plan review — round 2 (2026-10-16)
- Runner result: `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/stb/codex/r2/claudex-8hhgpna4/result.json`
- Provider codex, codex-cli 0.163.0, session `01a1466b-2eba-7593-8611-2d193cbe787f`, assurance `cross_provider`, requested model: CLI default (observed: unknown), plan SHA256 `b2147a6264b93c2005993ed09653b1dc12e3d222654d6e65c16af7a22c5e9d00`.
- Verdict: **REVISE**

```json
{
  "verdict": "REVISE",
  "summary": "SBR-001 through SBR-004 are addressed for their original scenarios. Four additional gaps remain in cancellation, metadata saves, terminal history, and Done-card reply controls.",
  "findings": [
    {
      "id": "SBR-005",
      "severity": "high",
      "path": "docs/exec-plans/active/2026-10-16-session-to-board.md:140",
      "evidence": "The generic route's record helper covers normal, timeout and error outcomes, but Cancel and stall write independently through _write_owner_record (runner/app.py:3069; runner/modules/stall_detection/__init__.py:89). Existing retry job metadata at app.py:4282 contains neither the intent nor project binding. Cancel an imported confidential session's reply: the owner record becomes latest without those fields, so the next reply can reach the ordinary retry route and its unsandboxed _build_resume_cmd, bypassing project policy. The worktree record_extra addition does not cover this generic owner.",
      "fix": "Explicitly integrate generic cancel/stall ownership with the shared record helper, preserving resume_session, binding, source and confidentiality handling. Define cancellation ownership for generic project-session jobs so project_key classification cannot silently select the worktree-only lifecycle."
    },
    {
      "id": "SBR-006",
      "severity": "medium",
      "path": "docs/exec-plans/active/2026-10-16-session-to-board.md:167",
      "evidence": "The editor fix guards started states but leaves other saves unchanged. saveLinearIssue (runner/templates/index.html:3422) always sends state_name, even when only the title changed. On a resumed Todo card, saving a title therefore sends Todo to _tracker_reset_route (runner/modules/linear/__init__.py:335), which unconditionally bumps the generation. This invalidates session routing although the user performed no drag or reset; the next send loses the intended continuation.",
      "fix": "Omit state_name from metadata-only saves when the state is unchanged. Preserve explicit Todo drag/reset behavior and verify that editing a resumed Todo card's title or description keeps its intent valid."
    },
    {
      "id": "SBR-007",
      "severity": "medium",
      "path": "docs/exec-plans/active/2026-10-16-session-to-board.md:171",
      "evidence": "The terminal backend correction applies only to a record with a valid intent. Import a session without a worktree, then explicitly reset its card to Todo: the generation invalidates that intent, while project_key, issue_identifier and agent_session_id remain. Open interactive then falls back to the existing load_binding branch at runner/modules/pty/__init__.py:375 and fails because no worktree metadata exists. Historical attempts similarly cease to satisfy the issue-latest predicate after another continuation.",
      "fix": "Resolve terminal session folders independently of retry-intent eligibility, including reset and historical records. Keep generation checks for headless continuation while retaining server-side session validation, project policy and card locking for terminals."
    },
    {
      "id": "SBR-008",
      "severity": "medium",
      "path": "docs/exec-plans/active/2026-10-16-session-to-board.md:158",
      "evidence": "The revised acceptance criteria explicitly allow later replies from Done, but the UI change only extends canRetry to Todo. The existing predicate at runner/templates/index.html:3034 still excludes done. After a continuation is marked Done, its main reply textarea remains visible but its send buttons remain hidden; the plan also suppresses the board retry group while resume_ok holds. Preserving backend routing alone does not enable this promised reply flow.",
      "fix": "Make a valid, non-running session intent enable the main reply send controls in every promised state, including Done, with the forced agent. Add a UI scenario that marks a continuation Done and sends another reply from the main reply box."
    }
  ],
  "coverage": [
    "Verified the revised plan matches SHA256 b2147a6264b93c2005993ed09653b1dc12e3d222654d6e65c16af7a22c5e9d00.",
    "Checked all four prior dispositions against the revised plan and relevant implementation.",
    "Traced generic retry, cancel/stall owners, session claims, binding lookup and CLI construction.",
    "Traced editor PATCH writers, reset-generation handling, status/restore records, terminal admission and historical-attempt controls.",
    "Checked local identifier allocation and the proposed high-water-mark correction."
  ],
  "limitations": [
    "Static review only; no files edited, tests run, or delegation performed.",
    "The proposed implementation does not yet exist; findings concern integration gaps between the plan and current callers.",
    "No live Linear, agent CLI, browser interaction or current pricing verification was performed."
  ]
}
```

### Dispositions
- SBR-005 (high) — ACCEPTED. Confirmed _write_owner_record builds from job["record"] (app.py ≈L3069) and retry job metadata (≈L4282) lacks intent/binding; cancel/stall classify by top-level project_key. Fix: §3.6 "Cancel and stall": the generic job's record carries resume_session, agent_session_id, linear_issue_id, issue_identifier, project_key, confidential, source; _write_owner_record applies the withholding helper; binding only inside job["record"], never top-level project_key, so cancel/stall use the run_agent_process path. Test added.
- SBR-006 (medium, reproducible: title edit) — ACCEPTED. §5 "Metadata-only saves": state_name sent only when stateChanged. Test added.
- SBR-007 (medium, reproducible: reset then Open interactive) — ACCEPTED. §5 "Independent of the intent": terminal folder choice depends on record session/binding/session cwd, not on intent validity. Test added.
- SBR-008 (medium, reproducible: reply from Done) — ACCEPTED. §5 "Reply controls in every state": canRetry true while resume_ok and not running, intent agent only. Test added.


## Codex plan review — round 3 (2026-10-16)
- Runner result: `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/stb/codex/r3/claudex-jydloiqy/result.json`
- Provider codex, codex-cli 0.163.0, session `01a1466b-2eba-7593-8611-2d193cbe787f`, assurance `cross_provider`, requested model: CLI default (observed: unknown), plan SHA256 `165a1ea17772e8f1aadff7eacf9ce9692f70048e7e17c42999c8af50ab84657b`.
- Verdict: **REVISE**

```json
{
  "verdict": "REVISE",
  "summary": "SBR-001 through SBR-008 are addressed in the plan. One additional shutdown defect remains in the generic session-job lifecycle.",
  "findings": [
    {
      "id": "SBR-009",
      "severity": "high",
      "path": "docs/exec-plans/active/2026-10-16-session-to-board.md:142",
      "evidence": "The revised generic job deliberately omits top-level project_key. However, runner/app.py:2955–2966 uses that same field to select jobs for shutdown cancellation and finalization waiting. Its projects.stop_all() call only kills processes registered through projects.spawn (runner/projects.py:139–165), whereas the planned generic route uses run_agent_process, which calls subprocess.Popen directly with start_new_session=True (app.py:2616). Start a long-running session reply, then SIGTERM a directly launched dashboard: neither shutdown mechanism selects its process. The agent can survive while the runner exits, releases its locks and loses its session claim, allowing a restarted dashboard to launch another writer against the same session.",
      "fix": "Explicitly include generic session jobs in shutdown admission, process-group termination, reaping and final-record waiting without classifying them as worktree workers for cancel/stall. Use a separate lifecycle discriminator or inspect their nested binding metadata. Add a shutdown scenario covering a silent generic session reply, preserved/redacted completion metadata, and refusal to launch after shutdown begins."
    }
  ],
  "coverage": [
    "Verified the plan matches SHA256 165a1ea17772e8f1aadff7eacf9ce9692f70048e7e17c42999c8af50ab84657b.",
    "Checked the SBR-005–008 revisions and retained SBR-001–004 corrections.",
    "Traced job classification through cancellation, stall detection, shutdown handlers, process registration, daemon workers and session claims.",
    "Read existing shutdown test definitions as evidence of the established lifecycle contract."
  ],
  "limitations": [
    "Static plan review only; no files edited, tests executed or delegation performed.",
    "The proposed implementation and shutdown scenario were not executed.",
    "Live Linear, browser, CLI and launcher behavior were not verified."
  ]
}
```

### Dispositions
- SBR-009 (high) — ACCEPTED. Confirmed _stop_project_runs (app.py ≈L2955) selects by top-level project_key and projects.stop_all() covers only projects.spawn; run_agent_process jobs (own session, _running_procs) survive SIGTERM. This is a pre-existing gap for every generic run, so the fix covers all run_agent_process jobs: new §3.7 "Shutdown" — refuse launches once _SHUTTING_DOWN is set via the _register_proc handshake; mark non-project jobs cancelled under _JOB_LOCK and _kill_group their _running_procs entry; the 10 s wait includes them so their cancel records (with §3.6 fields, withheld when needed) are written; cancel/stall classification unchanged. Test added.


## Codex plan review — round 4 (2026-10-16)
- Runner result: `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/stb/codex/r4/claudex-f5xx00eh/result.json`
- Provider codex, codex-cli 0.163.0, session `01a1466b-2eba-7593-8611-2d193cbe787f`, assurance `cross_provider`, requested model: CLI default (observed: unknown), plan SHA256 `6297be724e6418f46bfa086ab278874a04cdf0b080940be2b389447de0de69cf`.
- Verdict: **REVISE**

```json
{
  "verdict": "REVISE",
  "summary": "The revision addresses process termination, but shutdown completion ownership remains incomplete. Earlier findings remain addressed at plan level.",
  "findings": [
    {
      "id": "SBR-010",
      "severity": "medium",
      "path": "docs/exec-plans/active/2026-10-16-session-to-board.md:145",
      "evidence": "Marking a generic job cancelled does not invoke its cancellation owner. Generic workers never read job.cancelled: after shutdown kills the process, _RunClaim calls _end_job and the worker records its ordinary outcome—error for a strict reply, often review for other generic runs (runner/app.py:3081–3095, 4347–4370; runner/modules/linear/__init__.py:860–887). Only worktree workers interpret the cancellation flag. Furthermore, _end_job removes the registry entry before the record is written, so extending the shutdown wait to _running_jobs does not establish that durable completion finished. A silent generic reply stopped by SIGTERM therefore does not reliably produce the promised cancelled record before shutdown returns.",
      "fix": "Define explicit generic shutdown ownership. Reuse cancellation's atomic owner takeover and write through _write_owner_record after terminating and reaping the process, preventing the displaced worker from logging another outcome. Track already-finalizing workers separately until their durable writes finish. Verify that a cancelled record exists before shutdown returns, rather than merely checking that the job disappeared."
    }
  ],
  "coverage": [
    "Verified SHA256 6297be724e6418f46bfa086ab278874a04cdf0b080940be2b389447de0de69cf.",
    "Checked the SBR-009 revision against shutdown, process registration, cancellation ownership and record persistence.",
    "Traced generic completion callers in /run, retry and Linear dispatch, including their _RunClaim ordering.",
    "Read existing shutdown test definitions; retained the previous review's coverage of SBR-001 through SBR-008."
  ],
  "limitations": [
    "Static plan review only; no edits, test execution or delegation.",
    "The proposed shutdown changes have not been implemented or exercised.",
    "Live CLI, browser, Linear and launcher behavior were not verified."
  ]
}
```

### Dispositions
- SBR-010 (medium; reproducible: restart the dashboard while a reply runs) — ACCEPTED. Confirmed generic workers ignore job["cancelled"] and _end_job pops before the record write. §3.7 now: the generic branch of api_run_cancel (≈L4039–4062) becomes _cancel_generic(run_id, error) — pop under _JOB_LOCK, SIGTERM/SIGKILL with reaping, synchronous _write_owner_record — used by the cancel route and by _stop_project_runs for every job without a top-level project_key; the displaced worker finds no job and writes nothing. Workers that already won _end_job are tracked in a _finalizing set (added at ownership, removed in finally after the record write), and the shutdown wait covers it. Test asserts the cancelled record exists when shutdown returns.


## Codex plan review — round 5 (2026-10-16)
- Runner result: `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/stb/codex/r5/claudex-yvqbzgj8/result.json`
- Provider codex, codex-cli 0.163.0, session `01a1466b-2eba-7593-8611-2d193cbe787f`, assurance `cross_provider`, requested model: CLI default (observed: unknown), plan SHA256 `00df38e78c4394698f36aba301c11e1be7cad8825bad3682ab3a3c8f359b3404`.
- Verdict: **APPROVED**

```json
{
  "verdict": "APPROVED",
  "summary": "SBR-001 through SBR-010 are addressed at plan level. The revised shutdown ownership and finalization tracking resolve the latest finding. No additional material unresolved defects identified.",
  "findings": [],
  "coverage": [
    "Verified SHA256 00df38e78c4394698f36aba301c11e1be7cad8825bad3682ab3a3c8f359b3404.",
    "Rechecked shutdown admission, cancellation ownership, process termination, record persistence and finalizing-worker tracking against relevant callers.",
    "Across review rounds, traced session routing, reset generations, durable bindings, tracker/cache writers, local identifiers, terminal history and UI dispatch paths.",
    "Inspected relevant existing test definitions without executing them."
  ],
  "limitations": [
    "Approval covers the plan, not an implemented change.",
    "No files edited, tests executed or delegation performed.",
    "Runtime behavior, live Linear contracts, CLI behavior and current pricing remain unverified."
  ]
}
```

### Dispositions
- None. Approved.


## Codex plan review — closure
- **APPROVED** in round 5 (findings per round: 4, 4, 1, 1, 0; SBR-001…SBR-010 all fixed). Assurance `cross_provider`.
- Approved plan SHA256: `00df38e78c4394698f36aba301c11e1be7cad8825bad3682ab3a3c8f359b3404`. `runner.py check --approval <r5 result>` → "Approval matches the current plan; assurance=cross_provider."
- The checklist box "Codex plan review … approved" is left unticked on purpose: ticking it changes the plan hash. It is ticked at build start, right after `check` re-confirms the approval.
- Building waits for the user's go-ahead.
