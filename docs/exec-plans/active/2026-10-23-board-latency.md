---
status: in-progress
created: 2026-10-23
---

# Board latency: dispatch and card UI crawl

## Goal

Adding a Todo, dispatching a card (agent icon → In Progress) and opening cards respond in about a second again on the live runner.

## Findings (measured 2026-10-23, live runner pid 48952, 127.0.0.1:8510)

- `GET /api/projects` took **134.9 s** live (74 KB). On an isolated copy of `state/` + `outputs/` (worktree in the session scratchpad, no Linear key) it takes 8.5–10.5 s. Every other board endpoint is under 0.4 s (`/api/linear/issues` 0.14 s, `/api/runs?limit=80` 0.16 s, `/api/runs/latest-by-issue` 0.38 s).
- cProfile of the isolated call: `_with_commit_state` 7.9 s of 8.6 s — 63 `commit_state` calls, 281 git subprocesses (each `fork_exec` under `projects._LIVE_LOCK`), plus `codex_sessions` 1.25 s (the same `~/.codex/state_5.sqlite` `fetchall` repeated for each of 8 projects).
- `commit_state` entered `/api/projects` in a4bc88e (2026-10-21, "Commit button green when work is left, grey when merged"), with 7b734c2 adding the bound-branch check (more git per worktree). That matches the onset.
- The page calls `loadProjects()` 500 ms after every `linear_issues_updated` event (every create, dispatch, state change), on a 60 s timer, and after commits. The live log shows 3–5 `/api/projects` per minute; with each taking minutes they overlap and occupy the browser's HTTP/1.1 per-host connection pool (6), so the dispatch PATCH, the board refresh and card fetches queue behind them. The live process sits at ~83 % CPU from the git forks.
- The add-Todo form's project picker waits on `loadProjects()` (`__default__` placeholder), so adding a Todo waits on the 135 s call directly.
- The dispatch PATCH itself does flock + tracker writes + thread start, plus registry validation (`reserve_card` → `registered_key` → `load_registry`: one `git rev-parse` per registered project, 11 today, ~0.23 s isolated). That validation stays (fresh admission check); it is slow live only because it queues for `_LIVE_LOCK` behind the commit-state forks.

## Approach

Commit state moves off the request path. `api_projects` attaches `commit_state` from an in-process cache keyed by `(project key, session cwd)`; a missing entry is `None` (button neutral, as today for unreadable checkouts). When the cache is older than 30 s, or was invalidated, the request asks for a refresh. One worker thread at a time recomputes every commit-enabled project's sessions with the existing `_with_commit_state` logic (one status per checkout root). Worker state, the generation counter and publication share one lock: the worker records the generation it started from; on finish it publishes only if the generation is unchanged, otherwise it immediately runs another pass (no overlap, no lost demand). After publishing it emits Socket.IO `projects_commit_state`; the page reloads projects (debounced) and that reload hits a fresh cache and starts nothing. A successful session commit bumps the generation (invalidation).

`codex_sessions` memoizes the `threads` rows by the stat signature (mtime_ns, size) of `state_5.sqlite` and its `-wal` file; per-project filtering stays as is.

`loadProjects()` becomes single-flight: one request in flight per page; calls during a flight share one follow-up load that starts after the current one, so `await loadProjects()` still sees data fetched after the call.

Registry validation (`load_registry`'s per-project `git rev-parse`) stays on request threads, including dispatch admission, because those checks must be fresh. The acceptance bound below counts it.

Decisions and trade-offs:

- Commit button colours may be up to ~30 s stale (or neutral on a cold start until the first pass lands). Accepted: the colour is advisory; the commit endpoint recomputes everything itself under locks.
- One global worker (ponytail: global worker; per-project passes if one project's git dominates).
- No change to `commit_state`/`_commit_state` semantics, the git hardening/sandbox, `load_registry`, or `spawn`'s lock.

Non-goals: `/api/windows/all` (10.5 s live, agy quota timeouts, 60 s timer — separate issue); run-log parsing cost (17 MB, sub-second today); replacing the dev server.

## Assumptions and risks

- Assumption: nothing besides the Projects panel reads `commit_state` from `/api/projects` (grep: only `index.html` session rows).
- Risk: a pass that started before a commit publishes pre-commit colours. Handled by the generation check and re-run described above; tested below.
- Risk: the worker runs during shutdown — `projects.spawn` refuses after `stop_all()`; `commit_state` failures already map to `None`.

## Acceptance Criteria

- [x] `GET /api/projects` on the isolated state copy returns in under 2 s warm.
- [x] The only git subprocesses spawned on the `/api/projects` request thread are registry validation (at most one per registered project).
- [x] `GET /api/projects` stays under 2 s on the isolated copy while a commit-state pass is running.
- [x] Commit-enabled session rows carry `commit_state` once a pass has run, with the same values as the synchronous code.
- [x] At most one `/api/projects` request is in flight per page.
- [x] After a session commit, a fresh commit-state pass publishes without waiting for an unrelated request.
- [x] Full test suite passes. — same pre-existing env failure as base, nothing new.

## Verification

- [x] `.venv/bin/python -m pytest tests -q -x` passes. — 949 passed; 1 pre-existing failure (`test_claude_account.py::test_dashboard_select_needs_two_accounts[2-True]`, sandbox denies reading the KB `wiki/log.md`) fails identically on base bed5c17.
- [x] Test: first GET returns neutral rows and starts one pass.
- [x] Test: after the pass, a GET returns the same states the synchronous code produced.
- [x] Test: a second GET inside the TTL starts no pass.
- [x] Test: commit invalidation during a running pass makes that pass discard its result and re-run, and the re-run publishes.
- [x] Test: `codex_sessions` queries SQLite once for several projects while the DB is unchanged.
- [x] Test: `codex_sessions` queries again after the DB changes.
- [x] Test: `/api/projects` request thread spawns only registry-validation git commands (spy on `projects.spawn`, thread-filtered).
- [x] Isolated-copy timing: warm `GET /api/projects` < 2 s (was 8.5–10.5 s).
- [x] Isolated-copy timing: `GET /api/projects` < 2 s while a pass is running.
- [x] Timings recorded in the review log.
- [ ] Manual check after a user-approved live runner restart: `/api/projects` < 2 s.
- [ ] Manual check after the restart: dispatching a card responds promptly.
- [ ] Manual check after the restart: creating a Todo responds promptly.

## Progress Checklist

- [x] Memoize `codex_sessions` rows by DB/WAL stat signature (`runner/projects.py`).
- [x] Add commit-state cache, generation counter and single worker with re-run (`runner/app.py`).
- [x] Wire `api_projects` to read the cache and request passes.
- [x] Bump the generation after a successful session commit.
- [x] Single-flight `loadProjects()` (`runner/templates/index.html`).
- [x] Listen for `projects_commit_state` and reload projects (debounced).
- [x] Update `test_api_projects_rows_carry_commit_state`.
- [x] Add the new tests listed under Verification.
- [x] Run verification checks.
- [x] Record results in the review log.
- [x] Fresh Codex inspection of the diff. — inspection 1 REVISE (BL-004, BL-005 fixed), inspection 2 APPROVED.
