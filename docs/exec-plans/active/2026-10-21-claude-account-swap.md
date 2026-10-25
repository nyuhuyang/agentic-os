---
status: in-progress
created: 2026-10-21
revised: 2026-10-24
---

# Claude account swap (AGE-125)

## Goal

Switch the machine's Claude Code subscription account with one command or one dashboard click:
no `/logout` + browser `/login` per swap, and no `launchctl kickstart` of the runner. The account
must be switchable in the middle of a session, and the same session must continue on the other
account.

## Status of the earlier design

The first implementation (2026-10-21) copied the live keychain credential into per-label snapshots
and wrote one back on `use`. It failed in the field on 2026-10-22: after switching to `nyu`, the
restored login died with "OAuth session expired and could not be refreshed" (evidence below).
Root cause: refresh tokens are single-use, and a snapshot shares its refresh token with every
Claude process still running on that account, so a long-lived interactive session rotates the token
and strands the snapshot. That design is retired by this revision. Its four plan reviews and six
inspections stay in `2026-10-21-claude-account-swap.review-log.md`.

The user chose the replacement on 2026-10-24: **one `CLAUDE_CONFIG_DIR` per account**, with the
shared session/skill/setting stores symlinked into each account directory.

## Findings (recon)

- Every headless run spawns a fresh `claude` (`_ai_cli`, `project_runs.agent_cli`) with an env
  built by `_registry_exec_env` / `_project_exec_env`; terminal tabs use `pty._shell_env`. The
  runner never holds a Claude login, and the live launchd environment sets no Claude override
  variable, so today all of them read the default login.
- Claude Code 2.1.309 stores OAuth credentials per configuration directory. From the bundled CLI
  (`vj()` in the secure-storage chunk, verified 2026-10-24):
  `service = "Claude Code" + suffix + "credentials" + (config_dir ? "-" + sha256(NFC(config_dir))[:8] : "")`,
  where `config_dir` is `CLAUDE_CONFIG_DIR` verbatim (it must be absolute); the account attribute is
  `$USER`. Production `suffix` is `""`. Without `CLAUDE_CONFIG_DIR` the service is the bare
  `Claude Code-credentials`, which is what the runner and the old implementation used.
- When keychain storage is unavailable, Claude falls back to plaintext `<config_dir>/.credentials.json`
  (`h()` in the same chunk). The reader must support both.
- With `CLAUDE_CONFIG_DIR` set, the global config file moves **inside** that directory:
  probe `CLAUDE_CONFIG_DIR=/tmp/age125-probe/cfgA claude auth status --json` created
  `/tmp/age125-probe/cfgA/.claude.json` (plus `backups/`), not `~/.claude.json`, and reported
  `"configDirectory": "/tmp/age125-probe/cfgA"`, `"loggedIn": false`. Session transcripts follow
  `"projectsDirectory": "<dir>/projects"`.
- `claude auth status --json` is a public, credential-free identity source: for the live login it
  returned `loggedIn`, `authMethod`, `email`, `orgId`, `orgName`, `subscriptionType`,
  `configDirectory`, `projectsDirectory`. No profile API is needed.
- `claude auth login --email <address>` pre-populates the browser login page (2.1.309 `--help`).
- `claude -p` in a directory without credentials prints `Not logged in · Please run /login` and
  **exits 0**; a broken login therefore yields an empty-but-"successful" run. `login`/`use` must
  surface this state (`status`, warning), not rely on the exit code.
- Claude Code rewrites `~/.claude.json` and the keychain item often, so neither is authoritative
  for "which account is selected". The selector must be runner-owned state.
- `projects.py` and `usage_reader.py` read `~/.claude/projects`; keeping that directory as the
  shared store leaves both unchanged.

## Design

One configuration directory per account: `~/.agentic-os/claude-accounts/<label>/` (0700), label
`[A-Za-z0-9_-]{1,32}`. Each directory is the account's `CLAUDE_CONFIG_DIR`; Claude Code then owns
that login's keychain item (`Claude Code-credentials-<sha256(dir)[:8]>`) and its refresh lifecycle.
No credential is ever copied between accounts, and no process on account A can rotate account B's
refresh token.

Runner-owned selector: `~/.agentic-os/claude-accounts.json` (0600, atomic write)

```json
{"active": "nyu",
 "accounts": {"nyu": {"email": "a@x", "subscription": "pro", "saved_at": "..."},
              "rancho": {"email": "b@x", "subscription": "max", "saved_at": "..."}}}
```

Module `runner/claude_account.py` (stdlib only, CLI + importable):

- `normalize_dir(path)` → NFC-normalized absolute path string; `keychain_service(dir)` →
  `Claude Code-credentials-<sha256(dir.encode())[:8]>`. The string hashed is exactly the string
  passed as `CLAUDE_CONFIG_DIR` (no symlink resolution, no trailing slash), because Claude hashes
  the env value verbatim.
- `account_dir(label)`, `prepare(label)` (mkdir 0700, create `~/.claude` and the canonical
  `~/.claude/projects` when absent, seed `<dir>/.claude.json` from `~/.claude.json` when absent,
  then `_link_shared`), `_link_shared(dir)` (for every entry of `~/.claude` except `.claude.json`,
  `.claude.json.lock`, `.credentials.json`, `backups`: create a symlink in `dir` when the name is
  missing; never move or replace a real entry Claude created there; idempotent).
  `~/.claude` itself and the shared stores are created before the first link, so they are shared
  from the first account even on a machine where none exists yet: `projects`, `skills`, `plugins`,
  `commands`, `agents`, `hooks`, `output-styles`, `todos` (directories) plus `settings.json` and
  `CLAUDE.md` (files). A real account-local copy of any of them, found while the canonical name is
  absent, is moved into `~/.claude` with a same-filesystem rename (atomic, open file handles keep
  working) and replaced by a symlink; if the canonical name already exists, the local entry is left
  alone and reported. `local_only(dir)` lists real entries in `dir` that are known shared names or
  also exist in `~/.claude`, so a leftover is visible in `status`.
- `credentials(dir)` → parsed blob from the account's keychain service, else
  `<dir>/.credentials.json`, else `None`. Read-only. A keychain *failure* (not a missing item)
  still falls back to the plaintext file, matching Claude's own storage fallback; the error is
  raised only when neither source exists, so `status` can say "unreadable". `_kc_read` converts a
  `security` launch failure or timeout into `AccountError`, so that fallback also runs when the
  keychain command itself fails.
- `access_token()` → the active account's access token, or, **only when no account is configured**,
  the legacy default-service token. It never falls back to the default item while an account is
  active (that would show another account's quota).
- `index()` / `_write_index()` / `swap_generation()` (index `st_mtime_ns`) / `accounts()` (labels,
  emails, active from the index — no keychain or subprocess) / `active_account()`.
- `activate_env(env)` → sets `env["CLAUDE_CONFIG_DIR"]` to the active directory (override); a
  missing or unreadable index leaves `env` unchanged, so a fresh install behaves exactly as today.
  `inherit_env(env)` → same but only when the key is absent (used where an explicit value should
  win).
- `login(label, email=None)`: `_check_env()` (refuses `CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_API_KEY`,
  `CLAUDE_SECURESTORAGE_CONFIG_DIR`, `CLAUDE_CODE_CUSTOM_OAUTH_URL`, `CLAUDE_CODE_OAUTH_CLIENT_ID`);
  `prepare`; run `claude auth login [--email E]` with `CLAUDE_CONFIG_DIR=<dir>` and inherited stdio;
  then `auth_status(dir)` must report `loggedIn` and its `configDirectory` must equal the account
  dir; a supplied `--email` must match the returned email. Record the identity under the index lock;
  a duplicate email under another label is refused naming that label. The first account becomes
  `active` automatically; later ones do not switch anything.
- `record(label, email=None)` (CLI `save`) → the same verification and recording without launching
  the browser, for a login completed by hand in the account directory.
- `use(label)`: under the index lock, require the label and its directory; `_link_shared` to pick up
  new shared entries; write `active`; return warnings (never failures) when `claude auth status`
  says the account is not logged in, when the credential item is unreadable, or when other `claude`
  processes are running (they keep the account they started with). No credential write, so a
  switch cannot corrupt either login.
- `status()`: active label/dir, live `claude auth status --json` for that dir, credential source
  (`keychain` / `file` / `none`, never the value), shared-link count and any `local_only` names,
  and the env overrides that would defeat switching.
- CLI: `login <label> [--email E]`, `save <label> [--email E]`, `use <label>`, `list`, `status`,
  and `claude [args...]` which execs the active account's `claude` (for terminal use; an alias
  `alias claude='python3 .../claude_account.py claude'` makes interactive sessions follow swaps).
  `list` prints `* label  email`; a legacy flat index (`{"a": {"uuid": ...}}` from the retired
  design) is ignored with a one-line hint to run `login` again; its keychain snapshots are left in
  place (no automatic deletion).

Integration (env is the only change to how runs spawn):

- `app._registry_exec_env`: `if agent == "claude": claude_account.activate_env(env)` — covers skill
  runs, card runs, Linear dispatch, retries, resume and routing calls (all four
  `run_agent_process` sites build their env here).
- `app.run_agent_process`: apply the account for `stream == "claude"` right before the spawn, so a
  `CLAUDE_CONFIG_DIR` from `project.env` cannot silently defeat switching (main's
  `_project_exec_env` is left untouched; see "Merge with main").
- `project_runs.run_agent`: the same last word for the project-ticket path, which spawns its own
  process instead of going through `run_agent_process`.
- `pty._shell_env`: apply it to every terminal tab **after** `project.env`, so `claude` typed in a
  tab created after the switch uses the active account and a `CLAUDE_CONFIG_DIR` in `projects.yaml`
  cannot override it. A tab keeps the account it was opened under (its environment is fixed at
  spawn), exactly like any other running process; `claude_account.py claude` resolves the active
  directory on every invocation and is the documented way to follow a switch inside an older tab.
- `run_skill.py`: pass `inherit_env(os.environ.copy())` to the skill script, so a CLI skill that
  shells out to `claude` follows the active account while an explicit value still wins.
- `app._fetch_claude_oauth_usage`: read the token via `claude_account.access_token()` instead of the
  hardcoded `Claude Code-credentials` item. Unreadable → `{}` (empty cards), never another
  account's usage. `swap_generation()` still drops cached usage and pre-swap
  `rate-limits-live.json` snapshots on every switch.
- Dashboard `GET /api/claude-accounts` and `POST /api/claude-accounts/use` keep their shape and
  token check; `accounts()` is now a pure index read, so the picker no longer needs keychain or
  network work. `index.html` is unchanged.

Authentication failures are run failures, not silent successes: a logged-out `claude -p` exits 0
but emits a stream-json `result` event with `is_error: true`, `terminal_reason: "api_error"` and the
text `Not logged in · Please run /login` (probed 2026-10-24). Two existing parsers already see that
event and must act on it:

- `_stream_claude_run` returns a new `ok` value (`returncode == 0 and not result_event["is_error"]`);
  `run_agent_process` uses it instead of `proc.returncode == 0` for the `claude` stream. The run is
  recorded as failed with the result text as its error.
- `_parse_project_output` (project dispatch) keeps its `is_error` check and reports
  `result["result"]` as the error when stderr is empty, so the card shows the auth message.
- `use` warns when `claude auth status` reports the target as logged out; the switch itself still
  succeeds (the user may be about to repair it with `login`).

Failure behaviour: with no accounts configured nothing changes (default login, default keychain
item, picker hidden). With an account active, `activate_env` always passes that account's directory
through — including when the directory or its login is missing — so Claude fails with its own auth
message and the runner never silently falls back to the default or an inherited login. A missing
directory is logged once.

Migration from the retired design: log in once per account through its new directory
(`login nyu`, `login rancho`), then `use`. The old `agenticos-claude-account` keychain items and the
old index are inert; the plan documents the manual `security delete-generic-password` cleanup but
performs no deletion.

## Key decisions

- One keychain item per account directory; the runner switches only a pointer, never credentials.
- Shared stores by symlink into each account directory (sessions, skills, plugins, settings,
  history, caches); only the account's `.claude.json`, `.credentials.json` and `backups/` stay
  per-account.
- Identity comes from `claude auth status --json`, not from `~/.claude.json` or a private API.
- Switching changes future spawns only; running processes are never restarted or migrated.
- No automatic swap on quota exhaustion (still a non-goal).

## Non-goals

- Restarting running Claude processes or PTY tabs after a switch.
- Console/API-key accounts, per-project credential overrides, Linux/Windows.
- Automatic deletion of the retired snapshots, or of old account directories.

## Remaining risks

- Claude Code internals: the hashed keychain service name and the `<dir>/.claude.json` /
  `<dir>/projects` layout are not public contracts. If they change, switching still works (it is
  only an env pointer) but `status`/quota cards report `none`. `access_token()` never falls back to
  the default item while an account is active, so a rename shows empty cards instead of another
  account's numbers.
- A symlinked `projects` directory is assumed to be followed by Claude Code. Detection:
  `status` reports whether `projects` is a symlink, and a second-account resume of the same session
  is a user acceptance step. Contingency if Claude writes a real directory instead: stop sharing
  `projects` (sessions stay per account) and cancel the cross-account resume promise; the switch
  itself is unaffected.
- Two accounts sharing `skills/`, `plugins/` and `settings.json` can rewrite them concurrently.
  Claude Code already tolerates concurrent sessions; the shared files are user-owned and rarely
  written.
- A new top-level entry created by Claude inside one account directory stays local to that account
  until `use` links it (only names present in `~/.claude` are linked). `status` lists such names.
- An unmanaged default login (`~/.claude` + bare keychain item) can still be used by a bare
  `claude`, independently and safely; it does not follow switches.
- The runner process environment could still carry `CLAUDE_CODE_OAUTH_TOKEN`/`ANTHROPIC_API_KEY`
  from launchd, which would override the account for every spawn. `status` and a startup warning
  report it; the live launchd environment currently sets neither.

## Merge with main (2026-10-24)

`main` is at `68972a8` (it merged AGE-120/146 after this branch's last review). `git merge main` was
run for real in this worktree, preserving the merge parents; the branch is older, so **main's
version won every conflict where the branch only carried stale copies of main** and the ticket's
still-relevant changes were re-applied on top.

Conflicts (13) and resolution:

- `runner/app.py` — `_project_exec_env` is main's (new `worktree`/`run_id` parameters and the
  confidential-dsh environment). The AGE-125 guarantee is re-applied at the spawn points:
  `run_agent_process` (`stream == "claude"`) and `project_runs.run_agent` (the project-ticket
  spawn), with `_registry_exec_env` still setting the directory for skill/routing calls; main's
  `_project_exec_env` is untouched. Also re-applied: quota token via
  `claude_account.access_token()`, `is_error` stream results failing the run, the result text as
  the error, and the startup override warning.
- `runner/project_runs.py` — main's file plus the same last-word injection in `run_agent`.
- `AGENTS.md`, `docs/context-maintenance.md`, `docs/exec-plans/active/2026-10-21-scale-agent-fleet.md`,
  `docs/references/index.md`, `runner/dsh_cli.py`, `runner/dsh_confine.py`, `runner/projects.py`,
  `runner/scripts/dsh-confidential.yml`, `tests/test_dsh_confidential.py`,
  `tests/test_project_dispatch.py`, `tests/test_projects.py` — **main's version**, because the
  branch's copies only contained main's older state (AGE-120/146 and docs moved on).
- `docs/context-maintenance.md` therefore describes main's older AGE-125 design; the revision is
  recorded in this plan and the review log, and the Definition-of-Done item is marked N/A with that
  reason.
- Unchanged by main and kept: `runner/claude_account.py`, `tests/test_claude_account.py` (81
  tests), `runner/modules/pty/__init__.py`, `runner/run_skill.py`, `tests/conftest.py`, this plan
  and the review log.

The merge commit on `agent/AGE-125` has both `20dc04b` and `68972a8` as parents, so `main` is an
ancestor and the runner's merge into `main` cannot conflict on these files.

## Acceptance Criteria## Acceptance Criteria

Account setup and identity:

- [x] `login <label>` creates `~/.agentic-os/claude-accounts/<label>` with mode 0700. —
      `test_prepare_creates_private_dir_links_shared_entries_and_seeds_config`
- [x] `login <label>` symlinks every shared store name from `~/.claude` and skips `.claude.json`,
      `.claude.json.lock`, `.credentials.json` and `backups`. — same test
- [x] Preparing the first account on a clean machine creates and links every shared store, so a
      second account sees the first account's sessions, skills, plugins and settings. —
      `test_prepare_bootstraps_projects_so_two_accounts_share_sessions`,
      `test_prepare_creates_every_shared_store_on_a_clean_machine`
- [x] A pre-existing real shared store (directory or file) inside an account is moved into
      `~/.claude` and replaced by a symlink when the canonical name is absent; otherwise it is left
      alone and reported by `status`. — adoption tests for projects/skills/settings.json, "when
      `~/.claude` itself is absent", and canonical-present
- [x] `login <label>` seeds `<dir>/.claude.json` from `~/.claude.json` when the file is absent. —
      first prepare test
- [x] `login <label>` runs `claude auth login` with `CLAUDE_CONFIG_DIR` set to the exact account
      directory string and forwards an optional `--email`. —
      `test_login_passes_the_exact_config_dir_and_email_flag`
- [x] `login <label>` verifies `claude auth status --json` reports `loggedIn: true`. —
      `test_login_refuses_when_status_says_logged_out`
- [x] `login <label>` verifies the reported `configDirectory` equals the account directory. —
      `test_login_refuses_a_different_reported_config_directory`
- [x] `login <label> --email E` refuses a login whose email differs from `E`. —
      `test_login_refuses_an_email_mismatch`
- [x] `login <label>` records the email and subscription from `claude auth status --json` under
      the cross-process index lock. — identity test + `test_use_waits_for_the_cross_process_index_lock`
- [x] `login <label>` refuses, leaving the index unchanged, when the CLI exits non-zero, when the
      status is not logged in, or when the email is already saved under another label. — three
      refusal tests
- [x] `login <label>` refuses when any of the five override variables is set, naming the
      variable. — parametrized `test_login_refuses_override_variables`
- [x] The first saved account becomes active; a later `login` does not change the active account. —
      `test_a_second_login_does_not_switch_the_active_account`
- [x] `save <label>` records a login already completed in that directory without launching the
      browser. — `test_save_records_an_existing_login_without_launching`
- [x] `list` prints `* label  email` and a hint (not a traceback) when it finds a legacy flat
      index. — `test_legacy_index_is_ignored_everywhere`

Switching and run integration:

- [x] `use <label>` writes the active label under the cross-process index lock and bumps
      `swap_generation`, without writing any credential. — `test_use_switches_and_bumps_the_generation`,
      `test_use_never_writes_a_credential`
- [x] `accounts()` (and the picker's GET) is a pure index read: no keychain call, no subprocess. —
      `test_accounts_is_a_pure_index_read`
- [x] `use <label>` refuses an unknown label and a missing account directory. — two refusal tests
- [x] `use <label>` links shared names that appeared since the directory was created. —
      `test_use_links_shared_names_that_appeared_later`
- [x] `use <label>` returns a warning (no failure) when the target reports not logged in. —
      `test_use_warns_when_the_target_reports_logged_out`
- [x] `use <label>` returns a warning (no failure) when the account's credential item is
      unreadable, including a keychain timeout. — two warning tests
- [x] `use <label>` returns a warning (no failure) naming how many other `claude` processes keep
      the account they started with. — `test_use_warns_about_running_claude_processes`
- [x] `activate_env` sets `CLAUDE_CONFIG_DIR` to the active directory for every Claude spawn, even
      when the caller already set it. — `test_activate_env_overrides_an_existing_value`
- [x] `activate_env` leaves the env byte-identical when no account is configured or the index is
      unreadable. — two tests
- [x] `activate_env` keeps passing a selected account whose directory is missing (no default-login
      fallback). — `test_activate_env_keeps_a_selected_account_whose_directory_is_missing`
- [x] `_credential_raw` reads `<dir>/.credentials.json` when the keychain read fails (error or
      timeout), and raises only when neither source exists. — three credential tests
- [x] `inherit_env` sets the variable only when the caller has not set it. —
      `test_inherit_env_preserves_an_explicit_value`
- [x] `_registry_exec_env` applies the account for `claude` and never for `codex` or `dsh`. —
      `test_registry_exec_env_sets_the_account_for_claude_only`
- [x] the run engine applies the account after `project.env`, for both spawn paths. —
      `test_run_agent_process_applies_the_account_after_project_env`,
      `test_project_run_agent_applies_the_account_after_project_env`
- [x] `pty._shell_env` includes the active directory after `project.env`. — two tab tests
- [x] `claude_account.py claude ARGS...` execs the active account's `claude` with those arguments. —
      `test_cli_claude_execs_with_the_active_env`
- [x] `run_skill.py` gives its skill script `inherit_env` of the environment. —
      `test_run_skill_passes_the_account_to_the_skill_script`

Authentication failures and quota:

- [x] A Claude stream whose `result` event has `is_error: true` is a failed run, not a success,
      and its error text is the result text. —
      `test_stream_claude_error_result_is_a_failed_run`
- [x] `_parse_project_output` reports the result text as the error for an `is_error` result. —
      `test_parse_project_output_reports_the_result_text_as_the_error`
- [x] `access_token()` reads the active account's hashed keychain item. —
      `test_access_token_reads_the_active_account_item`
- [x] `access_token()` falls back to `<dir>/.credentials.json` when the item is missing or the
      keychain fails. — two fallback tests
- [x] `access_token()` reads the default `Claude Code-credentials` item only when no account is
      configured. — two default-item tests
- [x] A switch invalidates cached usage and pre-swap `rate-limits-live.json` snapshots. — cache,
      mid-fetch, and snapshot tests
- [x] The dashboard picker lists the index and switches via `use`; fewer than two accounts hides
      it. — endpoint + picker tests
- [x] No credential value appears in output, logs, `state/`, or the index; the index is 0600. —
      `test_cli_status_never_prints_a_token`, index-mode assertion
- [x] `status` reports active label/dir, `loggedIn`, email, credential source, shared-link state
      and override variables; it prints no token. — status tests
- [x] A legacy flat index does not crash `list`, `accounts()` or `activate_env`. —
      `test_legacy_index_is_ignored_everywhere`
- [x] The module never invokes a keychain write (`add-generic-password` absent from every argv). —
      `test_use_never_writes_a_credential`
- [x] The retired snapshots' manual cleanup command is documented, and nothing deletes them. —
      module docstring; no deletion code exists

## Verification

- [x] `.venv/bin/python3 -m py_compile runner/*.py` passes.
- [x] Test: `keychain_service` matches `sha256(NFC(dir))[:8]` and does not resolve symlinks. — three
      tests
- [x] Test: `prepare` creates a 0700 directory, seeds `.claude.json`, links shared entries, skips
      the deny list, and is idempotent. — two tests
- [x] Test: a clean machine gets every shared store created and linked, and both accounts see the
      same contents.
- [x] Test: a real account-local store (projects, skills, settings.json) is adopted when the
      canonical name is absent, including when `~/.claude` itself is absent, and reported when the
      canonical store exists.
- [x] Test: a real entry Claude created in the account dir is not replaced or moved.
- [x] Test: `login` passes the exact `CLAUDE_CONFIG_DIR`, forwards `--email`, and records
      email/subscription.
- [x] Test: every `login` refusal leaves the index unchanged (exit code, logged out, wrong
      `configDirectory`, email mismatch, duplicate email, bad label, each override variable).
- [x] Test: first account becomes active, second does not.
- [x] Test: `save` records without launching the CLI.
- [x] Test: `use` sets active, bumps the generation, links new shared entries, and returns each
      warning without failing.
- [x] Test: a second writer blocks on the index lock until the first releases it.
- [x] Test: `accounts()` performs no keychain read and spawns no process.
- [x] Test: `use` refuses unknown labels and missing directories.
- [x] Test: `activate_env` (override), `inherit_env` (preserve), no-account, unreadable-index,
      missing-account-directory (kept).
- [x] Test: credential file fallback after a keychain error or timeout, and the raise when both
      sources are absent.
- [x] Test: `pty._shell_env` includes the active directory and wins over a conflicting
      `project.env`.
- [x] Test: `_registry_exec_env` sets the variable for claude and not for codex/dsh.
- [x] Test: `run_agent_process` and `project_runs.run_agent` override a `CLAUDE_CONFIG_DIR` from
      `project.env`.
- [x] Test: `claude_account.py claude --resume x` execs `claude` with the resolved env.
- [x] Test: `run_skill.run_once` gives its script the active directory.
- [x] Test: a stream-json run with an `is_error` result event is recorded as failed with that text.
- [x] Test: `_parse_project_output` returns the result text as the error.
- [x] Test: `_fetch_claude_oauth_usage` uses `claude_account.access_token()`.
- [x] Test: GET/POST endpoints keep their token check and payload shape.
- [x] Test: the module never invokes a keychain write.
- [x] `.venv/bin/python3 -m pytest tests -q` on the merged tree — 1073 passed / 46 failed / 4
      skipped. The same 46 failures occur in a clean `main` clone at `68972a8` (identical names,
      eight confinement/PTY modules): they need `/usr/bin/sandbox-exec` or a PTY, both refused in
      this sandbox. No failure is introduced by the merge; the unsandboxed venv remains the
      authority.
- [x] Real merge: `git merge main` in this worktree, 13 conflicts, main's version kept where the
      branch only carried stale copies and the AGE-125 feature re-applied on top. Merge commit
      `b11254b` has parents `20dc04b` and `68972a8`; `main` is now an ancestor.
- [x] `claude_account.py list` and `status` run on the real machine without printing secrets.
      (Both report the retired index and no active account, as expected before the user logs in.)
- [x] Dashboard via the Flask test client: `/` renders, the picker is hidden with < 2 accounts and
      shown with 2, and GET/POST enforce the request token. (`/verify` is not available from this
      session; the test client covers the same paths.)

## Progress Checklist

- [x] `claude_account.py`: constants, label validation, NFC/absolute `normalize_dir`.
- [x] `claude_account.py`: `keychain_service` + read-only `credentials`.
- [x] `claude_account.py`: index read/write (0600, atomic), legacy ignore, `swap_generation`.
- [x] `claude_account.py`: `account_dir` / `prepare` / `_link_shared` / `local_only`.
- [x] `claude_account.py`: canonical shared-store bootstrap + account-local shared-store
      adoption/report.
- [x] `claude_account.py`: `login` (prepare, launch, env override refusal, status + configDirectory
      verification, `--email` match, duplicate-email refusal, first-account activation, identity
      recorded under the index lock).
- [x] `claude_account.py`: `record` (`save`, no browser).
- [x] `claude_account.py`: `use` (locked active write, link refresh, three warnings, no credential
      write).
- [x] `claude_account.py`: `accounts()` / `active_account()` as credential-free index reads.
- [x] `claude_account.py`: `list` / `status` / `claude` wrapper.
- [x] `claude_account.py`: `activate_env` / `inherit_env` / `access_token` / credential file
      fallback on a keychain error or timeout.
- [x] `claude_account.py`: argparse + docstring/`--help` with setup, daily swap, migration and the
      retired-snapshot cleanup command.
- [x] `app._registry_exec_env`: account env for claude only.
- [x] `app.run_agent_process` + `project_runs.run_agent`: account env after `project.env`.
- [x] `pty._shell_env`: account env for tabs, after `project.env`.
- [x] `app._fetch_claude_oauth_usage`: token via `access_token()`.
- [x] `app._stream_claude_run` + `run_agent_process`: `is_error` result fails the run.
- [x] `app._parse_project_output`: result text as the error for `is_error`.
- [x] `app.main`: warn once when override variables are set and an account is configured.
- [x] `run_skill.py`: `inherit_env` for the skill script.
- [x] Rewrite `tests/test_claude_account.py` for the new model (81 tests).
- [x] Add the stream/auth-failure and run-skill tests.
- [x] Add `tests/conftest.py` `WORKTREE_ROOT` isolation (unrelated real-worktree leak that failed
      `test_local_tracker` on this machine).
- [x] `docs/context-maintenance.md` records the revision (the three AGE-125 lines updated on top of
      main after the merge commit, so they cannot conflict).
- [x] Run the verification checks above.
- [x] Three fresh Codex plan reviews (R1-R5 resolved). No approving verdict: the reviewer cannot
      read repository files in this sandbox, and Claude review is organization-blocked. Recorded in
      the review log as a limitation, not as approval.
- [x] Codex inspection rounds; every finding resolved and re-tested (R1-R3 in round 7, I8-01/02 in
      round 8; round 9 returned no new finding). Independent approval withheld for the same
      repository-access reason.
- [x] Merge `main` into `agent/AGE-125` and commit the merge (parents `20dc04b` and `68972a8`);
      no push.

## User follow-up (not claimable in this session)

- [ ] `claude_account.py login nyu` (browser).
- [ ] `claude_account.py login rancho` (browser).
- [ ] `use nyu`; a dashboard task runs; switch to `rancho` mid-session and resume the same card.
- [ ] Confirm `claude_account.py status` and the dashboard picker agree.

## Field failure (2026-10-22, retired design)

After the 16:55 switch to `nyu`, the restored login worked until its access token expired (~17:33).
The next refresh failed: run b8afdef4 at 18:18, "OAuth session expired and could not be refreshed".
The two swap attempts at 18:19 got 400. Later runs succeed again, and the index did not change, so
the login was most likely repaired by a manual `claude auth login`. Refresh tokens are single-use;
a snapshot shares its refresh token with every Claude process running on that account, and two
interactive `claude --resume` processes had been alive for 3 days 20 hours. Any long-lived session
therefore triggers the failure within one ~8 h access-token lifetime. The per-account config
directory removes the shared token instead of trying to repair the copies.
