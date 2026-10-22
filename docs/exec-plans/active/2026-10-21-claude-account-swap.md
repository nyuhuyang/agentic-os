---
status: in-progress
created: 2026-10-21
---

# Claude account swap (AGE-125)

## Goal

Switch the machine's Claude Code login between two saved subscription accounts with one command
or one dashboard click: no interactive `claude` session, no `/logout` + `/login` browser flow per
swap, no `launchctl kickstart` of the runner.

## Findings (recon)

- The runner never holds a Claude login. Every headless run spawns a fresh `claude -p`
  (`runner/app.py:2234` `_ai_cli`, `runner/project_runs.py:87` `agent_cli`) with
  `os.environ.copy()`; that child reads the macOS keychain item `Claude Code-credentials` at start.
  So after any login change new runs already use the new account: **the kickstart is not needed**.
- The only runner-side reader of the login is the quota cards: `_fetch_claude_oauth_usage`
  (`runner/app.py:1172`) reads the same keychain item every 55 s (`_CLAUDE_USAGE_CACHE_TTL_S`).
  After a swap the cards show the old account for at most ~55 s (longer only if the fetch fails).
- Keychain blob (`security find-generic-password -s "Claude Code-credentials" -w`) is JSON
  `{"claudeAiOauth": {accessToken, refreshToken, expiresAt, refreshTokenExpiresAt, scopes,
  subscriptionType, rateLimitTier, ...}}`. Observed refresh-token lifetime ≈ 4 weeks.
- `~/.claude.json` `oauthAccount` holds the account identity (`accountUuid`, `emailAddress`,
  `organizationUuid`, ...) that `claude auth status` reports. A login writes both places.
- Already-running processes (open interactive `claude` sessions, dashboard PTY tabs, in-flight
  runs) keep the account they started with until they exit.

## Options considered

- **Zero code:** `claude auth logout && claude auth login` in a terminal (no TUI, no kickstart).
  Still a browser OAuth per swap, and the browser must be signed in to the target claude.ai account.
  Kept as the documented fallback.
- **`claude setup-token` + `CLAUDE_CODE_OAUTH_TOKEN` per spawn:** clean per-run selection, but the
  token is inference-only, so the official usage API behind the quota cards would stop working,
  and interactive terminal sessions would stay on a different account. Rejected.
- **`CLAUDE_CONFIG_DIR` per account:** splits `~/.claude/projects` (session history/resume), skills,
  plugins and settings per account. Rejected as too invasive.
- **Chosen: keychain snapshot swap.** Log in to each account once, save a snapshot (keychain blob +
  `oauthAccount`) under a label; `use <label>` writes it back. Whole machine (terminal, runner,
  quota cards) follows one login, exactly like a manual re-login, but instant.

## Approach

New module `runner/claude_account.py` (stdlib only), CLI and importable:

- `save <label>`: read the live keychain blob and `~/.claude.json` `oauthAccount`; store
  `{"credentials": <blob>, "oauthAccount": {...}}` as a keychain generic password,
  service `agenticos-claude-account`, account `<label>`. Label: `[A-Za-z0-9_-]{1,32}`.
- `use <label>`: (1) find the saved label whose `oauthAccount.accountUuid` matches the live
  account and re-save the live blob into it first, so its rotated refresh token is not lost;
  (2) if the live account matches no saved label, refuse (exit non-zero, message says run
  `save <label>` first) unless `--force`; (3) write the target blob into `Claude Code-credentials`
  (same account attribute as the existing item, `-U`); (4) replace `oauthAccount` in
  `~/.claude.json` with the target's (fresh read, write to temp file in same dir, `os.replace`,
  preserve file mode). Using the already-active label is a no-op success.
- `list`: labels, email of each, which one is active (by `accountUuid`). Never prints tokens.
- Secrets never on argv: writes go through `security -i` on stdin with `-X <hex>`; reads use
  `find-generic-password -w` (output captured, never logged). Saved-label discovery uses
  `security dump-keychain` attribute output filtered to the service (no secrets read for listing),
  or a small non-secret index file — implementer picks the simpler one that works; record which.
- Dashboard: `GET /api/claude-accounts` (list) and `POST /api/claude-accounts/use`
  `{"label": ...}` in `runner/app.py`; the POST calls `claude_account.use`, then resets
  `_claude_usage_cache`/`_claude_usage_retry_at` so the cards refetch for the new account. Both
  sit behind the existing per-process `X-AgenticOS-Token` check (no new auth path).
- `runner/templates/index.html`: in the Claude windows row label, a small `<select>` of saved
  labels (rendered from `index()` context, hidden when fewer than two are saved); change → POST,
  then reload the page. Errors shown with the existing alert/toast pattern.

## Key decisions

- Everything in the user's login keychain; nothing secret in the repo, `state/` or `outputs/`.
- No runner restart, no change to how runs spawn `claude`.
- No automatic swap on quota exhaustion (non-goal; add when manual swapping proves too slow).

## Non-goals

- Restarting already-running Claude processes or PTY tabs after a swap (they finish on the old account).
- Anthropic Console / API-key accounts; more than a handful of accounts; Linux/Windows.

## Remaining risks

- A Claude process started under account A that refreshes its token after the swap may write A's
  credentials back into the live item (Claude Code's refresh behaviour is not documented). Symptom:
  `list` shows active = B but runs bill A. Mitigation: `use` prints a warning naming the number of
  running `claude` processes; re-run `use <label>` after they exit. No engineering beyond that.
- A saved snapshot unused for longer than the refresh-token lifetime (~4 weeks) dies; `use` then
  produces a logged-out CLI. Recovery: `claude auth login` once, `save <label>` again.
- Editing `~/.claude.json` races with Claude Code writing it; the atomic replace keeps the file
  valid, worst case `oauthAccount` is reverted by a concurrent writer (cosmetic: `auth status`
  label; auth itself comes from the keychain).

## Acceptance Criteria

- [ ] After `save a` (logged in as A) and `save b` (logged in as B), `use a` makes
  `claude auth status --json` report A's email and a new `claude -p` run work, with no runner restart.
- [ ] `use` refuses when the live account is unsaved and `--force` is not given; nothing is written.
- [ ] `use` re-saves the outgoing account's live blob before switching.
- [ ] No token appears on any process argv, in logs, `state/`, or command output.
- [ ] Dashboard select switches account and the Claude quota cards show the new account after reload.
- [ ] One-time setup and daily swap are documented in the module docstring shown by `claude_account.py --help`.

## Verification

- [ ] `.venv/bin/python3 -m py_compile runner/*.py` passes.
- [ ] `.venv/bin/python3 -m pytest tests/test_claude_account.py -q` passes: fake `security` runner +
  tmp `~/.claude.json`, covering save, use (re-save outgoing, write target, oauthAccount replaced,
  file mode kept), refuse-unsaved, `--force`, same-label no-op, invalid label, list without secrets,
  and that no secret is passed on argv.
- [ ] Test: POST `/api/claude-accounts/use` without the request token is rejected; with it, calls
  `use` and resets the usage cache.
- [ ] `.venv/bin/python3 -m pytest tests -q` passes (no regressions).
- [ ] `.venv/bin/python3 runner/claude_account.py list` runs against the real keychain without
  error and without printing secrets (read-only check; no `use` on the real login in this session).
- [ ] `/verify` isolated-runner check: dashboard renders with the select hidden (0–1 saved) and the
  endpoints respond.
- [ ] Manual (user, after merge): `save` both accounts, `use` each, confirm `claude auth status` and
  a dashboard run. — recorded as user follow-up, not claimable here.

## Progress Checklist

- [ ] Write `runner/claude_account.py` (save/use/list + CLI).
- [ ] Write `tests/test_claude_account.py`.
- [ ] Add the two endpoints in `runner/app.py` and the cache reset.
- [ ] Add the select to `runner/templates/index.html` and pass labels from `index()`.
- [ ] Endpoint test.
- [ ] Run the Verification checks.
- [ ] Fresh Codex inspection of the diff; resolve findings.
- [ ] Update `docs/context-maintenance.md` with validation and next action.
- [ ] `graphify update .` if available.
- [ ] Commit on `agent/AGE-125`.
