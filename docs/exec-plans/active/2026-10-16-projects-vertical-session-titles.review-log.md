# Review log — 2026-10-16-projects-vertical-session-titles

- Roles: host Claude (Claude Code) plans and coordinates; plan reviewer Codex (claudex-loop runner `review`); builder Claude; final inspector a fresh Codex session.
- Fallback: when Codex has no usage, DeepSeek read-only (`DSH_PERMISSION_MODE=read-only dsh --profile headless`), recorded as third-party, not as claudex approval (standing user rule).
- Models: none requested; each CLI uses its own configured default.
- Rounds: plan review max 20; fix max 20; inspection max 20.
- Scope and authorization: plan and review only. The session was non-interactive (no questions could be asked), so D1–D4 are Claude's recommended defaults, open to user override. Build needs the user's go-ahead (D4).
- Budget: one plan file plus the referenced code (index.html projects panel, app.py `_board_sessions`, the rename and dispatch paths). Rough, moderate.

## Round 1 — Codex unavailable; DeepSeek third-party review ds1 (2026-10-16)
- Codex review `/private/tmp/claude-501/claudex-pvst/r1/claudex-yrh1w_01/result.json`: `provider_unavailable`, "You've hit your usage limit … try again at 9:33 PM."
- DeepSeek (read-only) `/private/tmp/claude-501/claudex-pvst/ds1/reply.txt`; checkout fingerprint before = after = `ffe96b85`. Verdict REVISE, 8 findings (7 medium, 1 low). The reply's JSON was malformed at its very end, a bracket in `limitations`; the findings are intact.

### Findings and dispositions (host Claude, all accepted)
- DP-01 (medium): a third return value from `_board_sessions` breaks two callers that unpack two. → It stays a 2-tuple; the new `_card_sessions()` returns the card map.
- DP-02 (medium): generic cards have no project to pass to `session_target`. → New store-confined `projects.find_session(agent, sid)` for runner-owned sessions. The generic continuation requires the session's cwd to be `ROOT`.
- DP-03 (medium): `ended=(agent, sid)` cannot tell the ending job from a terminal on the same session. → `ended_run=run_id` excludes only that run's job and claim. The sync runs after both the record write and the `_running_jobs` pop.
- DP-04 (medium): the editor's Linear title update ignores failure and masks it with the local override. → The card-row rename uses a strict `_set_card_title`, confirmed before any cache, override or native write. The editor route syncs only after a confirmed update.
- DP-05 (medium): a live-session refusal in the dispatch worker would leave the card In Progress. → The worker writes an error record and calls `_mark_issue_review`.
- DP-06 (medium): the sync re-takes the `session_lock` held by `_session_action`. → The card-bound rename has its own branch, outside `_session_action`.
- DP-07 (medium): "Decision 11 unchanged" contradicted D3. → The plan states the new invariant explicitly: a reset no longer forces a fresh session; generations still govern stale completions, replies/retry and the to-board intent.
- DP-08 (low): `cards` missed running jobs and claims. → `_card_sessions` includes them.

## Round 2 — DeepSeek third-party review ds2 (2026-10-16)
- `/private/tmp/claude-501/claudex-pvst/ds2/reply.txt`; fingerprint before = after = `ffe96b85`. Verdict REVISE. DP-01..08 confirmed addressed; 5 new findings (3 medium, 2 low). All accepted.
- DP-09 (medium): a missing bound worktree fails closed (I6-10), so "folder gone → new session" cannot hold for project tickets. → Project tickets keep the fail-closed error; the acceptance criterion is split.
- DP-10 (medium): the editor PATCHes `/local/<id>` in parallel, so a failed Linear update would still rename through the local route. → Only the authoritative tracker's route triggers a sync. `/local/<id>` never does in Linear mode.
- DP-11 (medium): the terminal-end sync hit the 120 s mtime rule. → `ended` is generalized to `("run", id)` or `("term", id)`; a finalized terminal waives the mtime rule for its own session.
- DP-12 (low): §2 still said `_board_sessions` returns `cards`. → Reworded.
- DP-13 (low): a `SessionBusy` from `_claim_session` would leave the card In Progress. → Caught, and handled like the live admission (error record + review).

## Round 3 — DeepSeek third-party review ds3 (2026-10-16)
- `/private/tmp/claude-501/claudex-pvst/ds3/reply.txt`; fingerprint unchanged (`ffe96b85`). Verdict REVISE. DP-01..13 confirmed addressed; 5 new findings (2 medium, 3 low). All accepted.
- DP-14 (medium): the generic path forces `ok=True`, so a failed resume would be recorded as `review`. → A resumed launch keeps its real result: a failure becomes `error`.
- DP-15 (medium): a running generic job has no `agent_session_id` until it exits. → `run_agent_process` gets an `on_session` callback, and a resumed launch sets the id before it starts.
- DP-16 (low): the rename input was prefilled with the native title (the preamble). → It is prefilled with `card_title || title`.
- DP-17 (low): a title is validated only after the tracker write. → `_clean_title` runs before `_set_card_title`.
- DP-18 (low): the panel only refreshes on the 60 s poll. → `linear_issues_updated` also calls `loadProjects()`, debounced.

## Round 4 — DeepSeek third-party review ds4 (2026-10-16)
- `/private/tmp/claude-501/claudex-pvst/ds4/reply.txt`; fingerprint unchanged (`ffe96b85`). Verdict REVISE. DP-01..18 confirmed addressed; 5 new findings (2 medium, 3 low). All accepted. The user asked for DeepSeek review ("用deepseek review").
- DP-19 (medium): a plain system line in a claude/codex stream is dropped by `render_event`. → An `agenticos-note` JSON line, rendered for every format; also `session_note` on the record.
- DP-20 (medium): cancel and stall write via `_write_owner_record` and skip the worker triggers. → The sync is also triggered after `_write_owner_record` for card runs.
- DP-21 (low): entrypoint skills would be bypassed by a resume. → Excluded from D3.
- DP-22 (low): `_card_session` would match dsh. → Restricted to claude/codex.
- DP-23 (low): `_set_card_title` missed the team cache. → It updates `_issues_by_team` too.

## Round 5 — DeepSeek third-party review ds5 (2026-10-16)
- `/private/tmp/claude-501/claudex-pvst/ds5/reply.txt`; fingerprint unchanged (`ffe96b85`). Verdict REVISE. DP-01..23 confirmed addressed; 2 new medium findings. Both accepted.
- DP-24 (medium): `issue_title` bypassed the confidential withholding (`_write_run_log` copies extras as-is). → Omitted whenever the run is confidential and `_records_unsafe()`, on every writer.
- DP-25 (medium): resumed dispatch did not check for a session open outside the dashboard. → `session_in_use(target, None, _own_activity_end(issue))` added to the admission; a positive result refuses with an error record and the card goes to review.

## Round 6 — DeepSeek third-party review ds6b (2026-10-16)
- The first attempt (`/private/tmp/claude-501/claudex-pvst/ds6`) was killed by the host's background time limit with no reply. It was rerun detached as `/private/tmp/claude-501/claudex-pvst/ds6b`; fingerprint before = after = `ffe96b85`. Verdict REVISE, 8 findings (2 high, 4 medium, 2 low). All accepted.
- DP-26 (high): a title edit within 120 s of a run hit the mtime rule. → The card's own last write (`_own_activity_end + 5 s`) is exempt, as in `session_in_use`.
- DP-27 (high): cancel and stall records had `duration_s=0`, so the next dispatch was refused as "in use". → `_write_owner_record` writes the real duration.
- DP-28 (medium): the routing CLI left a small session on every dispatch. → A resumed dispatch skips routing. A fresh routing call uses `--no-session-persistence` (claude) or `--ephemeral` (codex), both verified in the installed CLIs' `--help`.
- DP-29 (medium): archived cards still counted as cards. → `_tracker_issue` filter.
- DP-30 (medium): the sync compared the Codex display title, not `threads.name`. → `native_title` from `find_session`.
- DP-31 (medium): the sync could read an unconfirmed `/local` title; the local-first In Progress branch had no trigger. → Confirmed title (`_linear_titles`), and a trigger in `_linear_sync_patch_locked`.
- DP-32 (low): no writer for the note. → It is persisted and published before launch.
- DP-33 (low): the reset-test plan was contradictory. → D3 now covers reply/retry after a reset too (one task, one session on every path). The changed `test_reset_gen` tests are named; the agent lock and stale-completion guards are kept.

## User report folded in (2026-10-16): "这个task 里面的quick reply没什么用啊？看一下怎么回事"
- Diagnosis from the AGE-105 run log:
  - reply `2a2be2ea` was killed by the 1800 s cap;
  - reply `fd322e96` hit Claude's usage limit, but recorded "resume of session … failed" because the error comes from stderr only;
  - the Terminal tab's quick reply duplicates the Comment / Feedback reply (same `/retry`).
- → New §5: D5 one reply box, D6 the agent's own failure text, D7 stall detector + a 4 h ceiling for session-card replies. Claude's defaults; the user can override.

## Round 7 — DeepSeek third-party review ds7 (2026-10-16)
- `/private/tmp/claude-501/claudex-pvst/ds7/reply.txt`; fingerprint unchanged (`ffe96b85`). Verdict REVISE, 10 findings (2 high, 7 medium, 1 low). All accepted.
- DP-34 (high): a retry after a reset fell into the old `bound` block (the AGE-105 records carry a project_key with no worktree, so it would fail closed). → A transient intent through `_retry_session_card_held`, routed by the session's folder.
- DP-35 (high): the plain retry's fresh fallback would silently start a new session. → Every card-session continuation is strict.
- DP-36 (medium): the project helper used `AI_RUN_TIMEOUT_S` only. → `timeout` parameter.
- DP-37 (medium): no channel carried the agent's error result. → `_RUN_AGENT_ERRORS` side channel, plus `_parse_project_output`.
- DP-38 (medium): the card-row rename did not update `_linear_titles`. → It does, and the confirmed title is passed to the sync.
- DP-39 (medium): the project reader's `"w"` open erased the note. → `run_agent` writes it after opening.
- DP-40 (medium): a lock without a session id skipped `_card_session`. → Consulted whenever `_lock_session_id` is None.
- DP-41 (medium): leftover `detail-term-reply` references would throw. → All removed; the static test checks for any occurrence.
- DP-42 (medium): `update_issue` sends the description as null. → A title-only mutation.
- DP-43 (low): `_card_session` lacked the live-issue filter. → Added.

## Round 8 — DeepSeek third-party review ds8 (2026-10-16/17)
- `/private/tmp/claude-501/claudex-pvst/ds8/reply.txt`, exit 0 (the session watching it ended first; read on resume). Verdict REVISE, 5 findings (2 high, 3 medium). All accepted.
- DP-34 again (high): a transient intent fails `_retry_session_card_held`'s `_valid_intent` equality. → New `card_sourced=True` admission: live issue + current generation under the issue lock; no `resume_session` persisted.
- DP-42 again (high): the plan still allowed `update_issue` as an alternative. → A dedicated title-only mutation is required; `update_issue` is forbidden here.
- DP-44 (medium): Codex project failures still recorded stderr. → `turn.failed`/`error` message extracted.
- DP-45 (medium): the persisted-intent reply path lacked the live-issue gate. → `_valid_intent` returns None without a live issue.
- DP-46 (medium): the own-title fallback could write the preamble as the native name. → Display-only fallback; `create_session_issue` writes `_linear_titles`; the to-board record carries `issue_title`.

## Codex plan review requested by the user (2026-10-17: "用codex审阅")
### Codex round 1 — REVISE (cross_provider)
- Result: `/private/tmp/claude-501/claudex-pvst/c1/claudex-bltqd92g/result.json` (194 s). 4 findings: 2 high, 2 medium. All accepted.
- R1 (high): after the first card-sourced reply, the agent lock supplies the session, and the old `bound` block resumes in a missing worktree. → Every tracker-card continuation is routed by `find_session`'s folder, whatever the session source.
- R2 (high): `_valid_intent → None` only falls through; it does not refuse. → `api_run_retry` refuses 409 first when the tracker issue is gone, and both workers recheck liveness under the issue lock.
- R3 (medium): a plain Retry had no `on_session`. → Every tracker-card launch publishes its session id while running.
- R4 (medium): `_linear_titles` had no freshness rule against a stale poll. → Versioned by `updatedAt` under the issue lock.
### Codex round 2 — REVISE (cross_provider)
- Result: `/private/tmp/claude-501/claudex-pvst/c2/claudex-vk33r8he/result.json` (85 s). R1–R4 confirmed addressed; 2 new medium findings. Both accepted.
- R5: native sync was not serialized with title updates, so a delayed run-end sync could write an old title. → Per-issue `_title_sync_lock` around title selection and native write. Confirmed-title writers take the same lock, and an explicit title is revalidated.
- R6: stall and cancel only signal the process group, so the `ended` exemption was granted before the writer had exited. → The sync waits (bounded, ≤ 10 s, background) for the group to be gone; without confirmation there is no exemption.
### Codex round 3 — REVISE (cross_provider)
- Result: `/private/tmp/claude-501/claudex-pvst/c3/claudex-ou0dzivj/result.json` (35 s). R1–R5 confirmed addressed. R6 is still open: after the 10 s timeout, the own-activity exemption (stall time) still let the rename through, and reaping the leader does not prove its descendants are gone.
- Disposition: accepted. A closing marker `_CLOSING_SESSIONS[(agent, sid)] = pgid` is set before the owner record and counts as live for every sync. The watcher clears it only when `killpg(pgid, 0)` fails with ProcessLookupError; on a 5-minute timeout the marker stays and nothing is renamed.
### Codex round 4 — APPROVED (cross_provider)
- Result: `/private/tmp/claude-501/claudex-pvst/c4/claudex-cem8_iks/result.json` (25 s). R1–R6 addressed; no material unresolved defects.
- The approval is bound to plan SHA-256 `6329d3bd99dcb8ba49985fb8b059dfad07a3b61b075c12bf4628537f392e4d92`.
- Reviewer limitations: plan only; implementation, browser, native CLI and concurrency behaviour were not exercised.
- Totals: DeepSeek third-party rounds 1–8 (DP-01..46) and Codex rounds 1–4 (R1–R6), all findings accepted.
- Next: the build waits for the user's go-ahead (D4).

## Build (2026-10-17)
- The user authorized it: "claude build it, and codex review". Builder: Claude (host). Final inspector: a fresh Codex session.
- Build commit `1f3e108`, base `dbbacd0`. Proof: full suite 674 passed. New tests: `tests/test_session_titles.py`, 30 passed.
- Deviations and notes:
  - `on_session`: `_publish_run_line` already records every streamed session id on its job for every `run_agent_process` caller, so the generic and retry paths needed no new callback. A resumed dispatch sets the id on its job before launch.
  - D6: one channel, `project_runs.AGENT_ERRORS`, filled by `_publish_run_line` and by `project_runs.run_agent`. It is used before stderr on every continuation path, and in the project helper.
  - Retry: when the agent lock names a session whose store entry is not visible, the retry keeps today's resume with its fresh fallback. A session from `_card_session` that is not on disk starts fresh with a note.
  - Test safety: `tests/conftest.py` now points `CLAUDE_PROJECTS` and `CODEX_DB` at tmp in every test, so no sync can touch the real stores.
  - The R2 liveness check made 3 `test_project_dispatch.py` retries hit fixture cards that do not exist; that fixture now treats its cards as live.
- Manual browser checks BLOCKED: the Chrome extension is not connected, and headless Chrome refuses DevTools attach to pages ("Not allowed"). Playwright 's driver fails on Chrome 155.

## Codex build inspection 1 — REVISE (cross_provider)
- Result: `/private/tmp/claude-501/claudex-pvst/i1/claudex-4oboigmj/result.json` (223 s), on `8e1d070` against `dbbacd0`. 6 findings: 1 high, 5 medium. All accepted.
- R1 (high): the project dispatch refusal record wrote the real title with no binding. → `_refuse_resume(binding=…)` withholds the title under the confidential + unsafe rule and keeps the binding.
- R2 (medium): a locked session missing from disk was still resumed, with the fresh fallback and the 30-minute cap. → A new session with a "removed or archived" note. Every attempted tracker-card resume stays strict with `AI_SESSION_TIMEOUT_S`.
- R3 (medium): cancel and stall took the job out of the live set before the closing marker existed. → `_mark_job_closing` runs under `_JOB_LOCK` before the job is popped.
- R4 (medium): the ordinary retry and the project helper did not recheck liveness/generation once admitted. → `_card_admitted` (issue lock) runs before any tracker change in the retry route, and the project helper refuses a gone card before launch.
- R5 (medium): a failed `push_state` in project dispatch leaked the session claim and `dispatched`. → Both are released before the helper owns cleanup.
- R6 (medium): Codex `find_session` accepted a thread whose rollout was gone. → It now requires an existing, readable rollout file.
- Tests: 6 new regression tests. 9 older tests adapted to D3:
  - card continuations now have a session on disk;
  - fallback-mechanics tests use `/run` cards (no tracker issue), the only cards that keep the fresh fallback;
  - the project ticket-lock test expects a new session for a session not in any store.
- Proof: 680 passed.

## Codex build inspection 2 — REVISE (cross_provider)
- Result: `/private/tmp/claude-501/claudex-pvst/i2/claudex-ky80vxwe/result.json` (252 s). 5 findings: 1 high, 4 medium. All accepted.
- PVST-01 (high): the session-card reply's `record_extra` and the to-board record copied from `latest` could still carry `issue_title` once records became unsafe. → It is dropped at write time under the confidential + unsafe rule, on both writers.
- PVST-02 (medium): a card-sourced Retry with no reply got 400 "write a reply first". → A card-sourced Retry with no reply continues the session with the task prompt.
- PVST-03 (medium): `issue_title` recorded the display-cache title, which can be an unconfirmed /local edit. → Only the confirmed title is recorded.
- PVST-04 (medium): name syncs ran on raw threads, outside the maintenance count. → They go through `_start_counted`. The terminal-end trigger runs inside the audit's `_inflight_work`, so under maintenance neither runs.
- PVST-05 (medium): the session-card worker's exception branch had no run-end sync. → Added.
- Deviation: the closing-marker watcher polls every 0.2 s instead of every 1 s, so a counted watcher releases quickly.
- Tests: 2 new. `test_retry_and_baseline_are_refused_before_any_state` now waits for its own run's counted sync before it switches maintenance on.
- Proof: 682 passed.

## Codex build inspection 3 — REVISE (cross_provider)
- Result: `/private/tmp/claude-501/claudex-pvst/i3/claudex-p9970q4m/result.json` (185 s). 3 medium findings. All accepted.
- PVST-R3-01: queued workers launched without rechecking the card. → Each one now calls `_card_admitted` (liveness + generation, under the issue lock) right before launch: the session-card worker, the plain retry worker, generic dispatch after routing, and the project helper (generation added). Stale work is recorded `cancelled` and nothing launches.
- PVST-R3-02: in local mode after a restart (empty cache), labels used the recorded title. → `_board_sessions` resolves each issue live, local tracker included.
- PVST-R3-03: `_card_session` and the lock could pick a session another card now owns. → Both are validated against the `_card_sessions` newest-owner map; another card's session is never resumed.
- Tests: 4 new. 2 dsh dispatch tests whose cards are not in any tracker now treat their cards as live.
- Proof: 686 passed.

## Codex build inspection 4 — REVISE (cross_provider)
- Result: `/private/tmp/claude-501/claudex-pvst/i4/claudex-gqtf6dgb/result.json` (216 s). 3 medium findings. All accepted.
- PVST-R4-01: dispatch read its generation inside the worker, so a reset queued before the worker started was adopted. → `_start_dispatch` captures the generation when the dispatch is asked for and passes it through; the worker drops the dispatch if the card was reset since.
- PVST-R4-02: a persisted intent was accepted for a session another card now owns. → `_valid_intent` and the session-card admission both check the newest-owner map.
- PVST-R4-03: a structured failure (Claude `is_error`, Codex `turn.failed`) at exit 0 was recorded as review. → `project_runs.pop_agent_failure` adds a terminal-failure flag. It fails the session-card reply, card continuations on the retry path, a resumed dispatch, and the project helper. A Codex `error` event alone stays diagnostic.
- Tests: 3 new. Proof: 689 passed.

## Codex build inspection 5 — REVISE (cross_provider)
- Result: `/private/tmp/claude-501/claudex-pvst/i5/claudex-wob0d3ih/result.json` (266 s). 1 medium finding, accepted.
- PVST-R5-01: `_rename_idle` read the marker and the jobs without `_JOB_LOCK`, and normal completion retired the job before any marker existed.
  - `_rename_idle` now takes its marker and live-set snapshot under `_JOB_LOCK`.
  - `_end_job` (normal completion) installs the closing marker under the same lock before popping, like cancel and stall.
  - The project helper's final job removal does the same.
- Tests: 2 new deterministic ones, with a surviving descendant and a TERM-ignoring group. Proof: 691 passed.
