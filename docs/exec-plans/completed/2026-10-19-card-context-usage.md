---
status: completed
created: 2026-10-19
completed: 2026-10-19
---

# Card detail: show the agent's context usage (ctx%)

## Goal

The user asked: "加一个UI feature，现在UI看不到agent的ctx%，需要把这个加在task界面的合适位置。"
When you open a card (the task detail modal), show how full the agent session's context window is: a percent, plus the used and window token counts.
While the modal is open, the value keeps refreshing.

## Acceptance Criteria

- [x] When a card's displayed attempt has a Claude, Codex or DeepSeek (dsh) session with recorded usage, the detail modal's meta line shows `Context: NN% (used / window)`, e.g. `Context: 42% (84k / 200k)`.
- [x] While the modal is open on a concrete run id, the value refreshes every 3 s. This holds for running, completed, Linear-linked, session-bound (no progress log) and interactively continued cards.
- [x] At 80% or more, the percent shows in `var(--yellow)`.
- [x] At 95% or more, the percent shows in `var(--red)`.
- [x] When the window is unknown, only the used tokens show: `Context: 84k used`.
- [x] When there is no usage data, no `Context` segment shows and nothing errors.
- [x] When a read or parse error occurs, `GET /api/runs/<id>/context` returns HTTP 200 with `{"context": null}`, never a 500.
- [x] A Claude session whose CLI-reported model ends in `[1m]` shows a 1M window, even while running, below 200k used, and with its init event more than 2 MB back in the stream log.

## Key decisions

- **D1 Placement.** The detail modal's meta line reads Started · Duration · Model · **Context** · ID. It is visible on every tab, next to the model, which is what defines the window. Board cards are left alone: one file read per card on every board refresh would be a cost the user didn't ask for.
- **D2 Source.** The agent's own session store comes first, so interactive PTY continuations are counted. The run stream log is the fallback for Claude and the only source for dsh.
- **D3 Definition.** Context is the prompt-side tokens of the last main-thread call. Output tokens are excluded, as in Claude Code's status line. Sidechain (subagent) calls are excluded because they use a separate context.
- **D3a dsh is an upper bound** (CTX-009, inspection 1). dsh's `step_end` usage sums every attempt of a step. Its stream carries no per-call usage, and its session store is zstd-compressed, which the runner's Python 3.12 can't read without a new dependency. A retried attempt that reported usage therefore counts twice. When an attempt reports no usage, dsh omits the step's usage entirely, so most retries are not counted twice. dsh results carry `approx: true`, and the UI prefixes `~` with an explanatory tooltip.
- **D4 Window.** The window is inferred, with no config key. A wrong guess only skews the percent; the used figure stays exact.
- **D5 Dedicated route.** Context gets its own route instead of riding on the progress endpoints (CTX-001). The issue-progress endpoint only resolves running jobs, and the progress builder persists its payload.
- **D6 Init model from an incremental scan** (CTX-006). The model is read from the stream log with a per-path `(size, offset, model)` cache that scans only the bytes appended since the last call. The init line can therefore never drop out of view.
- **D7 Poll admission** (CTX-007). The modal's existing interval also starts for any concrete (non-`linear-`) run id. Progress-log fetching inside the tick stays conditional on the old `hasLog` test.

## Non-goals

- No ctx% on board cards or in the Projects panel session rows.
- No new config key.

## Approach (each item is an implementation step)

### Parser: `runner/usage_reader.py`

- [x] Add `_tail_lines(path, limit=2_000_000)`: the lines of the last `limit` bytes, newest first. When the read starts mid-file, it drops the first partial line. On a missing or unreadable file it returns `[]`. `ponytail:` the 2 MB tail is a ceiling: usage written further back shows nothing. The upgrade path is a reverse block reader.
- [x] Add `context_usage(agent, path, model=None) -> dict | None`, which returns `{"used", "window", "pct"}` from the newest usable line.
- [x] Claude branch: take the newest line with `type == "assistant"`, `isSidechain` not true, `message.model != "<synthetic>"` and a dict `message.usage`. used = `input_tokens + cache_read_input_tokens + cache_creation_input_tokens`.
- [x] Claude window: 1,000,000 when `model` ends in `[1m]` or used is over 200,000, otherwise `DEFAULT_CTX` (200,000).
- [x] Codex branch: take the newest line with `payload.type == "token_count"` and a dict `payload.info.last_token_usage`. used = `last_token_usage.input_tokens`, which includes cached input. window = `info.model_context_window` when it is a positive int, else None.
- [x] dsh branch: take the newest line with `type == "status"`, `phase == "step_end"` and a dict `usage`. used = `inputTokens + cacheReadTokens + cacheWriteTokens`. window = 1,000,000, from `DEFAULT_CONTEXT_WINDOW = 1e6` in `@deepseek-ai/dsh-llm-deepseek/lib/index.js`, which covers `deepseek-flash` and `deepseek-v4-pro`.
- [x] Line validation: a non-int or negative token field makes that line unusable, and the scan continues to older lines.
- [x] Percent: pct = `min(100, round(used * 100 / window))`, or None when the window is None.
- [x] Add `stream_model(path)`: the `model` of the newest `{"type":"system","subtype":"init"}` line, from a module-level `{path: (inode, offset, model)}` cache (D6).
- [x] `stream_model` reads only from the cached `offset` to EOF.
- [x] `stream_model` advances `offset` only to the last newline, so a partial last line is read on the next call.
- [x] `stream_model` resets the cache entry when the inode changes or the size drops below `offset`.
- [x] `stream_model` holds a module lock while reading and updating the cache.

### Session file lookup: `runner/projects.py`

- [x] Add `session_file(agent, sid) -> Path | None`, path-only, which never reads file contents (CTX-003).
- [x] Claude branch of `session_file`: the same checks as `find_session` (`_SESSION_ID`, `CLAUDE_PROJECTS` is a dir, `<dir>/<sid>.jsonl` is a regular file and not a symlink, it resolves inside the store), with no `_claude_summary` call.
- [x] When the same id exists under several project folders (e.g. an old and a new checkout), the Claude branch of `session_file` returns the copy with the newest mtime (CTX-008).
- [x] Codex branch of `session_file`: return `find_session("codex", sid)["path"]` or None. That function reads the DB row and stats the rollout only.

### API: `runner/app.py`

- [x] `_run_context` record: `_running_jobs.get(run_id)` when present, else the newest entry with that run_id in the cached `_all_records()`. With neither, return None.
- [x] `_run_context` identity: agent = `canonical_agent(record agent)`. sid = `agent_session_id`, else the sid in `_SESSION_CLAIMS[run_id]`.
- [x] `_run_context` stream log: the progress JSON's `stream_log` (via `_checkout_path`) when that file exists, else `_claude_stream_log_path(run_id)` when it exists (CTX-002).
- [x] `_run_context` model: `_OBSERVED_MODELS.get(run_id)`, else `stream_model(stream log)` (Claude), else the record's `model` (CTX-004/006).
- [x] `_run_context` source: `session_file(agent, sid)` for Claude and Codex. Claude falls back to the stream log; dsh always uses the stream log.
- [x] `_run_context` safety: the whole body sits inside `try/except Exception: return None`.
- [x] Add a `GET /api/runs/<run_id>/context` route that returns `{"context": _run_context(run_id)}`.

### UI: `runner/templates/index.html`

- [x] In `openDetailModal`, append `<span id="detail-ctx"></span>` to the `detail-meta` HTML, after Model.
- [x] In `openDetailModal`, call `_refreshDetailCtx(run_id)` after rendering the meta.
- [x] In `openDetailModal`, start the interval when `hasLog || !run_id.startsWith('linear-')`, passing `withProgress = hasLog` (D7).
- [x] Give `_startDetailProgressPoll(runId, issueId, withProgress = true)` the new parameter. Each tick calls `_refreshDetailProgress` only when `withProgress`, and always calls `_refreshDetailCtx(runId)`.
- [x] Add `_refreshDetailCtx(runId)`; it returns at once for `linear-…` ids.
- [x] `_refreshDetailCtx` fetches `/api/runs/<runId>/context`.
- [x] `_refreshDetailCtx` writes `_ctxHtml(data.context)` into `#detail-ctx` only when `_detailRunId === runId` and the modal is still open.
- [x] `_refreshDetailCtx` swallows fetch and parse errors.
- [x] Add `_ctxHtml(c)`. It returns '' for null or a missing `used`. With pct it returns ` · Context: <span colour>NN%</span> (84k / 200k)`, and without a window ` · Context: 84k used`.
- [x] Add `_fmtCtxTok(n)`: `<1000` as is, `k` for thousands, and `M` with at most one decimal for millions.

## Assumptions (verified)

- Claude run records and the stream-json init event carry the observed model, e.g. `claude-opus-5-5[1m]` (state/run_log.jsonl; init line in `outputs/logs/*_stream.jsonl`).
- `_OBSERVED_MODELS[run_id]` holds the model during generic Claude runs (`runner/app.py` ~2536). Project runs don't fill it, so they rely on `stream_model`.
- Claude transcripts have `message.usage` with cache fields on assistant lines.
- Codex rollouts have `token_count` with `info.last_token_usage` and `info.model_context_window` (one live rollout reported window 475000).
- dsh `step_end` usage has `inputTokens/cacheReadTokens/cacheWriteTokens` (outputs/logs).
- Project-bound runs write `_claude_stream_log_path(run_id)` directly (`runner/app.py` ~3336).
- The modal close path already stops `_detailProgressTimer`, so the widened admission leaks no interval.

## Risks

- A 1M-window Claude session without the `[1m]` mark shows a 200k window until it passes 200k. Accepted (D4).
- Each 3 s tick for the one open modal costs one `stat` per `~/.claude/projects` directory plus a ≤2 MB tail read. Accepted.

## Verification

- [x] Claude transcript test: the newest main-thread usage wins.
- [x] Claude transcript test: sidechain lines are skipped.
- [x] Claude transcript test: `<synthetic>` lines are skipped.
- [x] Claude transcript test: a `[1m]` model under 200k gives a 1M window.
- [x] Claude transcript test: an unmarked model over 200k gives 1M.
- [x] Claude transcript test: an unmarked model under 200k gives 200k.
- [x] Codex rollout test: the reported `model_context_window` is used.
- [x] Codex rollout test: a missing window gives `pct=None` and keeps `used`.
- [x] dsh stream test: step_end usage sums into `used`, with a 1M window.
- [x] Parser test: a file with no usage line gives None.
- [x] Parser test: a missing file gives None.
- [x] Parser test: malformed JSON lines are skipped.
- [x] Parser test: a non-int token field falls through to an older valid line.
- [x] Tail test: usage beyond the 2 MB tail gives None.
- [x] Tail test: the partial first line of a mid-file read is dropped.
- [x] `stream_model` test: it returns the newest init line's model.
- [x] `stream_model` test: an init line followed by more than 2 MB of later lines is still found.
- [x] `stream_model` test: bytes appended since the last call are scanned incrementally.
- [x] `stream_model` test: a truncated or replaced file resets the cache.
- [x] `session_file` test: it returns the confined Claude path without calling `_claude_summary`.
- [x] `session_file` test: with a duplicate session id, the newest copy wins (CTX-008). Live check: run 614ee14a now shows 6%, not 24%.
- [x] dsh test: results carry `approx: true`; a retried-step aggregate is flagged as an upper bound (CTX-009).
- [x] UI: `_ctxHtml` prefixes `~` and adds a tooltip when `approx` is set.
- [x] Full suite re-run after the inspection-1 fixes: 763 passed.
- [x] Fresh Codex reinspection after the inspection-1 fixes: inspection 2 confirmed CTX-008/009 and raised only CTX-010 (low).
- [x] Tail test: a tail that starts exactly on a line boundary keeps that line (CTX-010).
- [x] Fresh Codex reinspection after the CTX-010 fix: inspection 3 raised only CTX-011 (low).
- [x] Parser test: U+2028/U+2029/U+0085 inside JSON text do not split a record (CTX-011).
- [x] Full suite after the CTX-010/011 fixes: 765 passed.
- [x] Fresh Codex reinspection after the CTX-011 fix: inspection 4 APPROVED (cross_provider).
- [x] Browser checks re-run on final HEAD 75053d8: all pass, and dsh renders `~40%` with its tooltip.
- [x] `session_file` test: it refuses a symlinked transcript.
- [x] `session_file` test: it refuses an invalid sid.
- [x] Route test: a completed record with a Claude session returns `context`.
- [x] Route test: a running job whose `_OBSERVED_MODELS` model is `[1m]` gives a 1M window under 200k.
- [x] Route test: a project-style Claude run with no `_OBSERVED_MODELS`, a `[1m]` init line more than 2 MB back, and recent usage of 180k gives 18%.
- [x] Route test: a project-style dsh run with no progress JSON falls back to the deterministic stream log.
- [x] Route test: `context_usage` raising gives HTTP 200 `{"context": null}`.
- [x] Route test: an unknown run id gives `{"context": null}`.
- [x] The full suite `.venv/bin/python -m pytest -q` passes, with no new failures against the prior 739 passing. Evidence: 761 passed (739 + 22 new).
- [x] Browser (isolated runner, Playwright Chromium): a fake-claude card's modal shows `Context: NN% (… / …)`.
- [x] Browser: after the fake transcript gains a new usage line, the shown value changes within 4 s.
- [x] Browser: a Linear-linked completed card keeps its context across poll ticks.
- [x] Browser: a session-bound card with no `log_path` updates after its transcript changes.
- [x] Browser: a card with no usage shows no `Context` segment.
- [x] Browser: the console shows no errors during these checks. Evidence: `/private/tmp/claude-501/ctx-verify/check_ctx.py` gave 15% (151k / 1M) on the card, 90% after 2.9 s, still shown after 7 s, yellow at 90%, a session-bound card went 40%→96% in red, the no-usage card had no segment, and errors=[].

## Progress Checklist

- [x] Codex plan review approved (claudex-loop Phase 2).
- [x] All Approach steps above are done.
- [x] `tests/test_context_usage.py` is written.
- [x] The full suite has been run.
- [x] The browser checks have been run.
- [x] Committed (no push).
- [x] A fresh Codex inspection approved the change (inspection 4).
- [x] The live runner restart is armed for when it goes idle. The idle watcher (`/private/tmp/claude-501/pvst-verify/restart_when_idle.sh`, log `/private/tmp/claude-501/ctx-verify/restart_when_idle.log`) is running. Its only running job is this coordinating session, so the restart happens when the session ends.
- [x] The plan is moved to `docs/exec-plans/completed/`.
- [x] The review log is moved to `docs/exec-plans/completed/`.
