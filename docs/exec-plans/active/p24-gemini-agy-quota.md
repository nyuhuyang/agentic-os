# Plan: Gemini (Antigravity) weekly quota row in dashboard windows panel
_Locked via claudex-loop — by Claude + Yang Hu, 2026-09-23_

## Goal
Show the two free weekly quotas from Google Antigravity CLI (`agy`) — "Gemini Models"
(Flash/Pro) and "Claude and GPT models" (Opus/Sonnet/GPT-OSS) — as a new "✧ Gemini" row in the
runner dashboard's budget-window panel, between the Codex and DeepSeek rows. Refresh cadence must
match the existing Claude/Codex quota cards (55s server cache, 60s front-end poll) without ever
blocking the page on the ~5s `agy` call.

## Approach
1. **Parser (pure, testable)** — `runner/usage_reader.py`: add `parse_agy_usage(text: str) -> dict`.
   Input is `agy -p "/usage"` stdout: one TSV record per line,
   `<group>\t<label>\t<N>%\t<ISO-8601 UTC reset>`. Map group by prefix, case-insensitive:
   starts with `gemini` → key `gemini`; contains `claude` → key `claude_gpt`. Output per key:
   `{"remaining_pct": int 0..100 (clamped), "resets_at": aware datetime | None}`. Malformed lines
   (wrong field count, non-numeric pct) are skipped individually; a bad timestamp alone keeps the
   pct with `resets_at=None`, and the card then shows the pct with reset label "—" and no pace
   marker, subject only to the 15-min age rule. Unknown groups ignored.
2. **Fetch** — `runner/usage_reader.py` (no Flask import, so it is unit-testable):
   `fetch_agy_usage(timeout_s=15.0) -> tuple[dict, str | None]` returning `(groups, error_code)`.
   Binary resolved via `shutil.which("agy") or ~/.local/bin/agy` (launchd PATH already contains
   `~/.local/bin`; fallback is belt-and-braces). Run `[agy, "--log-file", "/dev/null", "-p",
   "/usage"]` with `stdin=DEVNULL`, `capture_output=True`, `text=True`, `errors="replace"`,
   `timeout=timeout_s`. No shell. If neither path is an executable file → `not_installed` before
   spawning; `FileNotFoundError`/`PermissionError` also map to `not_installed`,
   `subprocess.TimeoutExpired` → `timeout`. The whole body sits in `try/except Exception`. **Error codes are a
   fixed set** — `not_installed`, `timeout`, `exit_<rc>`, `unparseable`, `error` — and those are the
   only strings that ever reach the API/UI. The server log (`logging.warning`) records only the
   error code, exit status and output byte lengths. No CLI output text is logged anywhere. `--log-file /dev/null` keeps agy from writing one log
   file per call under `~/.gemini/antigravity-cli/log/`.
3. **Cache: stale-while-revalidate, per group** — `usage_reader.py`, class-free module state
   guarded by `_agy_lock`: `_agy_groups: dict[key, {"remaining_pct", "resets_at", "fetched_at"}]`
   (last good value **per group**), `_agy_attempt_at: float` (monotonic, last attempt),
   `_agy_error: str | None`, `_agy_refreshing: bool`. `_AGY_CACHE_TTL_S = 55.0` (same as
   `_CLAUDE_USAGE_CACHE_TTL_S` / `_CODEX_RESET_CACHE_TTL_S` in app.py).
   `load_agy_usage(fetch=fetch_agy_usage) -> tuple[dict, str | None]`: under the lock, if
   `now - _agy_attempt_at >= TTL` and no refresh is in flight, set `_agy_refreshing=True`,
   `_agy_attempt_at=now`, then start a daemon thread running `_refresh_agy(fetch)`. If
   `Thread.start()` raises, clear the flag and set error `error`. Returns a **copy** of
   `(_agy_groups, _agy_error)` immediately and never waits.
   `_refresh_agy`: `try` calls `fetch()`; under the lock it **merges** the returned groups into
   `_agy_groups` (a group missing from this fetch keeps its previous entry and `fetched_at`) and sets
   `_agy_error` to the returned code: None when both expected groups parsed, `unparseable` when
   zero parsed, and `partial_gemini` / `partial_claude_gpt` (naming the **missing** group) when only
   one parsed. That way a group that keeps disappearing is surfaced instead of being hidden
   behind its old cached value.
   `except Exception` sets `_agy_error="error"` and logs it; `finally` clears `_agy_refreshing`.
   Because `_agy_attempt_at` is stamped at spawn time, a broken `agy` gets retried once per TTL,
   not on every poll.
   **Staleness rule** (applied when building the cards, per group): a cached group is shown only
   while (`resets_at` is None or still in the future) **and** `now - fetched_at <= 15 min`. Otherwise the
   card shows "no data" with display_line "stale (last ok Nm ago)". A post-reset value is known to
   be wrong. Past 15 min, the value is too old to trust.
4. **Window shape** — `_load_agy_windows() -> dict` returns the same shape `load_windows` /
   `_updateOneRow` already consume: `{"agent": "gemini", "window_5h": <gemini card>,
   "window_7d": <claude_gpt card>, "aux": {}, "quota_source": "agy", "limits_estimated": False}`.
   Card fields: `title` ("Weekly · Gemini" / "Weekly · Claude & GPT"), `pct` = 100 − remaining
   (bar = used, matches Codex), `remaining_pct`, `used_pct: None`, `tokens: 0`, `limit: 100`,
   `sessions: 0`, `resets_at_unix`, `window_minutes: 10080`, `reset` = `_reset_label_from_epoch`
   countdown, `display_line` = "Flash · Pro · updated Ns ago" / "Opus · Sonnet · GPT-OSS · updated
   Ns ago" (+ " · refresh failed (<code>)" when `_agy_error` is set and the group is still fresh).
   `_load_agy_windows()` lives in app.py and calls `usage_reader.load_agy_usage()`.
   Special cases: remaining == 100 → `reset` = "Quota available", `window_minutes: 0` (hides pace
   marker, because agy reports a moving now+7d reset for untouched groups). Cold cache → pct 0,
   remaining_pct None, display_line "loading…". Error with no cache → display_line
   "agy unavailable (<code>)". Group missing from output → "no data" card for that group only.
5. **Wiring** — `_compute_display_windows`: `if agent == "gemini": return _load_agy_windows()`
   before the generic path. `/api/windows/all`: loop over `("claude", "codex", "gemini",
   "deepseek")`. Index route: `windows_gemini = load_windows("gemini")`, passed to template.
   `load_windows` works unchanged because cards carry `tokens`, `limit`, `display_line`.
6. **Template** — `runner/templates/index.html`: new block between the Codex `win_row` call and
   the DeepSeek block, `id="windows-row-gemini"`, label "✧ Gemini", `windows-row-cards` with inline
   `grid-template-columns:1fr 1fr`, two cards identical in markup to the macro's first two cards
   (bar + pace marker + remaining + win-main). JS `updateWindows()`: add `'gemini'` to the agent
   list. `_updateOneRow` needs no change (it returns early when `cards[2]` is absent).
7. **Test** — `tests/test_agy_usage.py`, stdlib + pytest, no Flask:
   - `parse_agy_usage`: real captured output, a malformed line, a bad timestamp, pct clamping,
     empty input.
   - Cache transitions, with an injected fake `fetch` gated by a `threading.Event` and module
     state reset between tests: (a) a cold `load_agy_usage` returns `({}, None)` without waiting
     while the fake blocks; (b) 10 concurrent calls start exactly one fetch; (c) after a
     success, then a failure, the previous groups survive and the error is `exit_1`; (d) a
     partial fetch with one group keeps the other group; (e) a fetch that raises clears
     `_agy_refreshing` and sets `error`; (f) a one-group fetch sets `partial_<missing>`.
   - Real fetcher mappings (monkeypatch `shutil.which` / `subprocess.run`): missing binary →
     `not_installed`; `TimeoutExpired` → `timeout`; rc=1 → `exit_1`.
   - Staleness: a group whose `resets_at` has passed, or whose `fetched_at` is >15 min old,
     renders as "no data". Tested through a small pure helper `agy_card_state(entry, now)` in
     usage_reader.
8. **Manual proof** — restart runner, `curl /api/windows/all | jq .gemini` twice (first may be
   "loading…", second populated after ≥6s). Non-blocking is proven by unit test (a); the live
   endpoint also runs synchronous Claude/Codex loaders, so no absolute latency is asserted on it.
   Load the dashboard and confirm row order Claude → Codex → Gemini → DeepSeek and that the page
   renders without waiting on agy. Failure paths (`not_installed`, timeout, staleness) are
   proven by the unit tests, not by breaking the live binary.

## Key decisions & tradeoffs
- **CLI over internal API**: `agy -p /usage` (documented print-mode record output) instead of
  calling `cloudcode-pa…/v1internal:retrieveUserQuotaSummary` with the OAuth token from
  `~/.gemini/oauth_creds.json`. Costs ~5s + a 185MB binary spawn per refresh; buys no token
  handling and no dependency on an undocumented internal endpoint.
- **55s TTL, user-mandated parity** with Claude/Codex quota caches. At 60s front-end polling this
  means ~1 agy spawn per minute while a dashboard tab is open; zero when no one polls.
- **Stale-while-revalidate, not blocking** (Q1): data shown is up to ~one poll old; page render
  and `/api/windows/all` never wait on agy. Cold start shows "loading…" once.
- **Integer precision**: agy print-mode gives whole percent (84 vs TUI 84.45). Accepted.
- **Row label "Gemini"** per user wording, though the row also holds the Claude&GPT group
  (both are Antigravity quotas).

## Assumptions
1. "AGI" = Google Antigravity CLI `~/.local/bin/agy`, authenticated. — source: `agy --help`, `~/.gemini/antigravity-cli/`
2. `agy --log-file /dev/null -p "/usage"` exits 0 in ~4.7s, emits the TSV above, makes no model call, writes no log file. — source: direct runs 2026-09-23
3. Untouched (100%) group reports reset ≈ now+7d that drifts per call. — source: two calls 13s apart
4. Runner launchd PATH includes `~/.local/bin`. — source: `~/Library/LaunchAgents/com.agenticos.runner.plist`
5. Claude/Codex quota caches use 55s TTL; front-end polls `/api/windows/all` every 60s. — source: `app.py:1077,1354`, `index.html:3421`
6. `_updateOneRow` tolerates a 2-card row. — source: `index.html:1034-1090` (`if (!rc) return;`)

## Risks / open questions
- agy print-mode output format may change on `agy update`; parser skips unknown lines → row
  degrades to "no data" rather than breaking the panel.
- Flask dev server multi-threaded: lock + `_agy_refreshing` flag prevent concurrent spawns (unit-tested).
- Module state lives per process. If the runner ever runs multiple worker processes, each one spawns its own agy (today: a single process).
- Runner process has uncommitted unrelated edits in the same three files; build must not mix them.

## Out of scope
- Refresh button, persisting agy data to disk, history/trend charts.
- Using Antigravity as a dispatch agent/backend.
- Showing Antigravity quota anywhere other than the windows panel.
