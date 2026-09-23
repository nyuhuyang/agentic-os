# Plan Review Log: Gemini (Antigravity) weekly quota row
Phases 0-1 (recon + interrogation) complete — plan locked with the user. MAX_ROUNDS=5.
Reviewer: Codex (CLI default model).

## Round 1 — Codex

**Material issues in the plan:**

1. **Stale quota can remain visible indefinitely.** Failed refreshes retain the last good percentage, even after its reset time has passed. Fix: track last successful fetch separately from last attempt and show “unavailable” after a maximum age or expired reset.

2. **Partial output can erase a valid group.** The fetch treats one parsed group as success and replaces the whole cache, so a malformed or omitted second group becomes “no data.” Fix: validate both expected groups before replacing the snapshot, or cache and age each group independently.

3. **The background refresh needs a failure path for exceptions.** `subprocess.run(text=True)` can raise `OSError` or `UnicodeDecodeError`, and thread startup can fail; the plan does not say how those failures update retry state. Fix: catch these failures, record the attempt and error, and reliably clear `_agy_refreshing`.

4. **CLI error text should not reach the API.** “Sanitized” is undefined, while the proposed response includes a line of stderr or stdout that could contain account or credential details. Fix: return fixed error categories to the dashboard and keep diagnostic text out of API responses.

5. **Validation misses the main risk.** Parser tests and two immediate `curl` calls cannot establish that cold requests return promptly, concurrent requests start one process, or failed refreshes age out correctly. Fix: add mocked clock and fetch tests for those cache transitions, then poll the live endpoint until the 15-second timeout window has elapsed.

VERDICT: REVISE
### Claude's response
- 1 (stale indefinitely) — ACCEPTED: per-group `fetched_at`; group hidden once `resets_at` passed or >15 min since last success ("stale (last ok Nm ago)").
- 2 (partial output erases group) — ACCEPTED: per-group merge; groups absent from a fetch keep their previous entry.
- 3 (exception paths) — ACCEPTED: fetch body in try/except Exception, `errors="replace"`, Thread.start() failure clears flag, `finally` clears `_agy_refreshing`; attempt stamped at spawn so retries are once per TTL.
- 4 (CLI text leak) — ACCEPTED: fixed error-code set only reaches API/UI; raw text to server log only.
- 5 (validation) — PARTIALLY ACCEPTED: moved fetch+cache to usage_reader.py (Flask-free) and added unit tests for cold non-blocking, single-spawn under concurrency, failure retention, partial merge, exception cleanup, staleness. REJECTED live-endpoint polling across the 15s timeout window — failure paths proven by unit tests with injected fetch; live proof limited to happy path + cold latency.

## Round 2 — Codex

The revision resolves the unbounded stale cache and concurrency concerns. Four issues remain:

1. **Bad timestamps have contradictory handling.** The parser keeps a valid percentage with `resets_at=None`, but the staleness rule immediately hides it. Fix: either reject that record or allow its percentage for 15 minutes without a reset countdown.
2. **Partial fetches look fully successful.** If one group repeatedly disappears, the old group remains cached while `_agy_error=None`, concealing the parser or CLI regression. Fix: report a `partial` status and identify which group was missing.
3. **Raw CLI output still enters server logs.** The first 200 characters of an authentication error could contain sensitive account or token data. Fix: log the fixed error code and exit status only, with redacted diagnostics if needed.
4. **The proposed proof cannot isolate blocking by `agy`.** `/api/windows/all` also runs synchronous Claude and Codex loaders, so its cold response need not meet the proposed `<1s` threshold. Fix: test the endpoint with those loaders stubbed and `agy` fetch held open, then assert the response returns before the fetch completes.

VERDICT: REVISE
### Claude's response
- 1 (bad-timestamp contradiction) — ACCEPTED: `resets_at=None` group shown (label "—", no pace marker), only the 15-min age rule applies.
- 2 (partial looks successful) — ACCEPTED: `partial_<missing group>` error code.
- 3 (raw text in server log) — ACCEPTED: log error code, exit status, byte lengths only.
- 4 (proof can't isolate agy blocking) — PARTIALLY ACCEPTED: dropped the <1s live assertion (correct: endpoint runs other sync loaders). REJECTED Flask-endpoint harness with stubbed loaders — app.py import is heavy; `load_agy_usage` is the only agy entry point from the endpoint and unit test (a) proves it returns while fetch is held open.

## Round 3 — Codex

The revised plan is sound enough to implement. Two small details need attention during implementation:

- The `~/.local/bin/agy` fallback may be absent, making `not_installed` unreachable if `FileNotFoundError` falls through to `error`. Fix: check that the fallback is executable or map `FileNotFoundError` to `not_installed`.
- The listed cache tests do not exercise the real fetcher’s `not_installed` and `timeout` mappings. Fix: mock binary resolution and `subprocess.run` for those two cases.

VERDICT: APPROVED
### Claude's response
Both implementation notes ACCEPTED and folded into the plan: executable check + FileNotFoundError/PermissionError → `not_installed`, TimeoutExpired → `timeout`; tests for the real fetcher's not_installed/timeout/exit_1 mappings via monkeypatch.

## Resolution
APPROVED at round 3 of MAX_ROUNDS=5.
