---
status: in-progress
created: 2026-10-21
---

# Claude account swap (AGE-125)

## Goal

Switch the machine's Claude Code login between saved subscription accounts with one command or
one dashboard click: no interactive `claude` session, no `/logout` + `/login` browser flow per
swap, no `launchctl kickstart` of the runner.

## Findings (recon)

- The runner never holds a Claude login. Every headless run spawns a fresh `claude -p`
  (`runner/app.py:2234` `_ai_cli`, `runner/project_runs.py:87` `agent_cli`) with
  `os.environ.copy()`; that child reads the macOS keychain item `Claude Code-credentials` at start.
  After any login change new runs already use the new account: **the kickstart is not needed**.
- The live runner's launchd environment sets none of `CLAUDE_CODE_OAUTH_TOKEN`,
  `ANTHROPIC_API_KEY`, `CLAUDE_CONFIG_DIR` (checked with `launchctl print`), so spawned `claude`
  uses the default keychain login.
- The only runner-side reader of the login is the quota cards: `_fetch_claude_oauth_usage`
  (`runner/app.py:1172`) reads the same keychain item, cached 55 s under `_claude_usage_lock`.
  When that fetch fails, `_load_claude_official_windows` falls back to `rate-limits-live.json`
  snapshots (`runner/app.py:1392`), which carry no account identity.
- Keychain blob is JSON `{"claudeAiOauth": {accessToken, refreshToken, expiresAt,
  refreshTokenExpiresAt, scopes, subscriptionType, rateLimitTier, ...}}`. Observed refresh-token
  lifetime ≈ 4 weeks.
- `GET https://api.anthropic.com/api/oauth/profile` with `Authorization: Bearer <accessToken>`
  returns `account.uuid` / `account.email` (verified live 2026-10-21, no beta header needed).
  This is the authoritative owner of a credential blob.
- `~/.claude.json` `oauthAccount` holds the identity `claude auth status` reports. A login writes it
  and the keychain; Claude Code rewrites the file often, so it is not authoritative.
- Already-running processes (open interactive sessions, dashboard PTY tabs, in-flight runs) keep
  the account they started with until they exit.

## Options considered

- **Zero code:** `claude auth logout && claude auth login` in a terminal (no TUI, no kickstart).
  Still a browser OAuth per swap, and the browser must be signed in to the target claude.ai
  account. Kept as the documented fallback.
- **`claude setup-token` + `CLAUDE_CODE_OAUTH_TOKEN` per spawn:** the token is inference-only, so
  the usage API behind the quota cards would stop working, and terminal sessions would stay on a
  different account. Rejected.
- **`CLAUDE_CONFIG_DIR` per account:** splits `~/.claude/projects`, skills, plugins and settings.
  Rejected as too invasive.
- **Chosen: keychain snapshot swap.** Log in to each account once and save a snapshot (keychain
  blob + `oauthAccount`) under a label; `use <label>` writes it back. The whole machine follows
  one login, like a manual re-login, but instant.

## Design

Module `runner/claude_account.py`, stdlib only, CLI and importable.

- Snapshot storage: keychain generic password, service `agenticos-claude-account`, account
  `<label>`, value JSON `{"uuid", "email", "credentials": <blob>, "oauthAccount": {...}}`.
  Labels match `[A-Za-z0-9_-]{1,32}`. A non-secret index file
  `~/.agentic-os/claude-accounts.json` (`{label: {uuid, email}}`, mode 0600) lists labels without
  reading secrets.
- Owner of the live blob (`live_owner()`), never taken from `oauthAccount`:
  (1) live `refreshToken` equals a saved snapshot's → that label;
  (2) else, access token unexpired → `/api/oauth/profile` `account.uuid` → matching label;
  (3) else unknown. `save` always uses (2) to learn the uuid/email (refuses if it cannot).
- One label per account: `save <label>` refuses when the verified uuid is already saved under a
  different label (message names it); re-saving the same label for the same uuid overwrites.
- Saved `oauthAccount` always matches the verified uuid: `save` stores the live `oauthAccount`
  only when its `accountUuid` equals the profile uuid, else a minimal one rebuilt from the profile
  response (`accountUuid`, `emailAddress`, `displayName`, `organizationUuid`, `organizationName`).
  The outgoing re-save inside `use` replaces only `credentials`, keeping the snapshot's
  already-verified identity fields.
- `save` and `use` both hold the same machine-wide lock for their whole operation; `use` calls an
  internal unlocked re-save helper.
- `use <label>` under the machine-wide `fcntl.flock` on `~/.agentic-os/claude-account.lock`
  (shared by CLI and dashboard):
  validate label and load + parse the target snapshot before any write; resolve the live owner;
  owner == target → re-save its live blob, rewrite `oauthAccount` (repair, not a skip), done;
  owner is another saved label → re-save the live blob into that label; owner unknown → refuse
  with nothing written unless `--force` (then the live blob is discarded, message says so);
  write target blob into `Claude Code-credentials` (`-U`, same account attribute as the existing
  item); replace `oauthAccount` in `~/.claude.json` (fresh read, temp file in same dir,
  `os.replace`, keep mode). A failed `oauthAccount` write is a warning, not a failure: ownership
  never depends on it. Touch the index file so its mtime marks the swap time. Print how many other
  `claude` processes are running (they keep the old account; see risks).
- Refuse `use`/`save` when the process env sets `CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_API_KEY` or
  `CLAUDE_CONFIG_DIR` (those override or relocate the keychain login). Per-project `env` overrides
  in `projects.yaml` are unsupported for swapping and documented as such.
- Secrets never on argv: keychain writes go through `security -i` on stdin with `-X <hex>`; reads
  use `find-generic-password -w` with output captured and never logged or printed.
- Dashboard: `GET /api/claude-accounts` → `{accounts: [{label, email}], active: label|null}` and
  `POST /api/claude-accounts/use` `{label}`, both behind the existing `X-AgenticOS-Token` check.
  Swap generation = index file `st_mtime_ns` (cross-process: CLI and dashboard swaps both touch
  it). `_load_claude_oauth_usage`, under `_claude_usage_lock`, clears cached usage and retry state
  when the generation differs from the one the cache was filled under, and publishes a fetch only
  if the generation did not change during it. `_load_claude_official_windows` treats a
  `rate-limits-live.json` snapshot captured before the last swap as unavailable.
- `index.html`: a small `<select>` beside the Claude row label, options from `index()` context,
  hidden when fewer than two labels are saved; change → POST → reload; error → existing alert.

## Key decisions

- Everything secret in the login keychain; nothing secret in the repo, `state/` or `outputs/`.
- No runner restart, no change to how runs spawn `claude`.
- No automatic swap on quota exhaustion (non-goal; add when manual swapping proves too slow).

## Non-goals

- Restarting already-running Claude processes or PTY tabs after a swap.
- Console/API-key accounts, per-project credential overrides, Linux/Windows.

## Remaining risks

- A Claude process started under A that refreshes after the swap may write A's credentials into
  the live item. Detection: `list` reports the authoritative owner (refresh-token/profile), so it
  shows A, not B. Recovery: `use b` again after those processes exit (same-label `use` repairs, it
  does not skip). Ownership checks keep A's credentials from ever being saved into B.
- A snapshot unused longer than the refresh-token lifetime (~4 weeks) dies; `use` then yields a
  logged-out CLI. Recovery: `claude auth login` once, then `save <label>`.
- A still-running A session can write a new `rate-limits-live.json` after the swap; the cards may
  show A's snapshot only while B's usage API call is failing. Accepted.

## Acceptance Criteria

- [ ] `use <label>` switches the keychain login to the saved account without a runner restart.
- [ ] After `use`, `claude auth status --json` reports the target email (oauthAccount rewritten).
- [ ] `use` refuses with nothing written when the live owner is unknown and `--force` is absent.
- [ ] `use` re-saves the outgoing account's live blob only into the label that owns it.
- [ ] `use <active label>` repairs (rewrites credentials + oauthAccount) instead of skipping.
- [ ] Concurrent `use` calls are serialized by the lock.
- [ ] `use`/`save` refuse when `CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_API_KEY` or `CLAUDE_CONFIG_DIR` is set.
- [ ] No token appears on any process argv, in logs, `state/`, or command output.
- [ ] Dashboard select switches account.
- [ ] The request-token check guards `GET /api/claude-accounts`.
- [ ] The request-token check guards `POST /api/claude-accounts/use`.
- [ ] A uuid can be saved under only one label.
- [ ] After any swap (CLI or dashboard), cached or in-flight pre-swap usage is not shown.
- [ ] `save` is serialized with `use` and other `save` calls by the same lock.
- [ ] A saved snapshot's `oauthAccount.accountUuid` always equals its verified uuid.
- [ ] A pre-swap `rate-limits-live.json` snapshot is not shown as live after a swap.
- [ ] One-time setup and daily swap are documented in the module docstring shown by `--help`.

## Verification

- [ ] `.venv/bin/python3 -m py_compile runner/*.py` passes.
- [ ] Test: `save` stores the snapshot with the uuid from the profile call.
- [ ] Test: `save` adds the label to the index file.
- [ ] Test: `save` with mismatched live `oauthAccount` stores one rebuilt from the profile.
- [ ] Test: re-save inside `use` keeps the snapshot's identity fields.
- [ ] Test: `save` rejects an invalid label.
- [ ] Test: `save` refuses a uuid already saved under another label.
- [ ] Test: `use` identifies the outgoing owner by refresh-token match and re-saves it.
- [ ] Test: `use` writes the target blob to the live keychain item.
- [ ] Test: `use` writes the target `oauthAccount` into `~/.claude.json`.
- [ ] Test: owner found via profile when the refresh token rotated.
- [ ] Test: unknown owner → refusal, no keychain or file write.
- [ ] Test: `--force` with unknown owner switches without re-saving.
- [ ] Test: same-label `use` rewrites credentials and oauthAccount.
- [ ] Test: unknown target label → refusal before any write.
- [ ] Test: `~/.claude.json` mode preserved.
- [ ] Test: `~/.claude.json` keys other than `oauthAccount` untouched.
- [ ] Test: oauthAccount write failure → warning, keychain switch kept, exit 0.
- [ ] Test: env override present → refusal.
- [ ] Test: no secret in any argv passed to the fake `security`.
- [ ] Test: a `use` blocks while another holder has the lock.
- [ ] Test: a `save` blocks while another holder has the lock.
- [ ] Test: POST without the request token is rejected.
- [ ] Test: POST with the token calls `use`.
- [ ] Test: GET returns labels and emails, no secrets.
- [ ] Test: generation change during a fetch stops it from publishing.
- [ ] Test: generation change (external CLI swap) clears cached usage.
- [ ] Test: rate-limits snapshot older than the swap → not live.
- [ ] `.venv/bin/python3 -m pytest tests -q` passes (no regressions).
- [ ] `.venv/bin/python3 runner/claude_account.py list` runs against the real keychain without printing secrets (read-only).
- [ ] `/verify` isolated runner: dashboard renders.
- [ ] `/verify` isolated runner: select hidden with < 2 saved accounts.
- [ ] `/verify` isolated runner: `GET /api/claude-accounts` responds.

## Progress Checklist

- [ ] `claude_account.py`: keychain write via `security -i` + hex.
- [ ] `claude_account.py`: keychain read via `-w`.
- [ ] `claude_account.py`: index file read/write.
- [ ] `claude_account.py`: lock helper.
- [ ] `claude_account.py`: env-override refusal.
- [ ] `claude_account.py`: `live_owner()` refresh-token match.
- [ ] `claude_account.py`: `live_owner()` profile API fallback.
- [ ] `claude_account.py`: `save` with identity check.
- [ ] `claude_account.py`: `use` target validation before writes.
- [ ] `claude_account.py`: `use` unknown-owner refusal and `--force`.
- [ ] `claude_account.py`: `use` outgoing re-save.
- [ ] `claude_account.py`: `use` live keychain write.
- [ ] `claude_account.py`: `use` `oauthAccount` write (warning on failure).
- [ ] `claude_account.py`: `use` index touch (swap generation).
- [ ] `claude_account.py`: running-`claude` count notice.
- [ ] `claude_account.py`: `list`.
- [ ] `claude_account.py`: argparse CLI.
- [ ] `claude_account.py`: setup docstring shown by `--help`.
- [ ] `claude_account.py`: one-label-per-uuid check in `save`.
- [ ] Write `tests/test_claude_account.py`.
- [ ] `runner/app.py`: `GET /api/claude-accounts`.
- [ ] `runner/app.py`: `POST /api/claude-accounts/use`.
- [ ] `runner/app.py`: clear cached usage on generation change.
- [ ] `runner/app.py`: skip publishing a fetch whose generation changed.
- [ ] `runner/app.py`: ignore pre-swap rate-limits snapshot.
- [ ] `runner/app.py`: pass account list to `index()` template.
- [ ] `index.html`: select rendered beside the Claude label.
- [ ] `index.html`: select hidden with < 2 accounts.
- [ ] `index.html`: change → POST.
- [ ] `index.html`: success → reload.
- [ ] `index.html`: error → alert.
- [ ] Endpoint/cache tests.
- [ ] Run the Verification checks.
- [ ] Fresh Codex inspection of the diff.
- [ ] Resolve inspection findings.
- [ ] Update `docs/context-maintenance.md` with validation and next action.
- [ ] Commit on `agent/AGE-125`.

## User follow-up (not claimable in this session)

- [ ] Log in as account A.
- [ ] Run `claude_account.py save a`.
- [ ] Log in as account B.
- [ ] Run `claude_account.py save b`.
- [ ] Run `use a`.
- [ ] Confirm `claude auth status` shows A.
- [ ] Start a dashboard run; confirm it works on A.
- [ ] Switch to B from the dashboard select; confirm the quota cards change.
