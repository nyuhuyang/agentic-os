# AGE-147 review log

Append-only transcript. Host/planner/builder: `deepseek` (dsh session). Plan reviewer: `codex`.
Code inspector: `codex`. Cap: 4 plan-review rounds, 4 inspection rounds, 4 fix rounds.
Inspection on. A DeepSeek host has no automatic same-provider fallback; an unavailable Codex is
reported, and any replacement is an explicit recorded selection.

- Plan: `docs/exec-plans/active/2026-10-24-deepseek-dual-currency-budget.md`
- Log: `docs/exec-plans/active/2026-10-24-deepseek-dual-currency-budget.review-log.md`
- Pre-build commit: recorded before implementation
- Research: none (repository recon only)
- Authorization: AGE-147 asks for the usage UI update, the $20 monthly cap, and repeated Codex
  review; implementation and commit on `agent/AGE-147` are authorized.
- Environment: Codex runs with a private `CODEX_HOME` under `/private/tmp` and
  `runner/scripts/sandboxed-bin/codex` first on `PATH`, because the dsh workspace sandbox does
  not let Codex's inner Seatbelt start. The runner still audits the reviewed snapshot.

## Round 1 — plan author

Scope: record both reported balances per sample, sum per-currency spend into a USD-normalized
total, add a UTC calendar-month $20 budget, and render three DeepSeek cards (budget, balance,
recent spend) in both currencies while preserving old CNY-only history.

### Round 1 result (Codex, cross_provider) — REVISE

- `R1` (high, `runner/usage_reader.py:424`): `load_deepseek_usage` is an allowlist and drops
  the five proposed fields, so the month value would never reach `compute_windows` or the API
  wrappers. Disposition: accepted. All five fields are added to the allowlist and a file-backed
  test asserts the month value wins over the 30-day fallback.
- `R2` (medium, plan totals): a legacy USD-only cache has synthesized `balance_cny`, so
  `balance_usd + balance_cny/7.2` would double the total. Disposition: accepted. Totals come
  from `raw_balances`; legacy fallback uses `balance.currency` to count USD once.
- `R3` (medium, plan snapshots): legacy USD-only snapshots store synthesized CNY, so a direct
  per-currency comparison would invent CNY spend on upgrade. Disposition: accepted. A
  `balance.currency == "USD"` history is converted to USD observations before comparison;
  tests cover the USD-only-to-dual upgrade.
- `R4` (low, plan checklists): actionable Approach items lacked their own checkboxes.
  Disposition: accepted. Approach is design prose and every implementation/deliverable step is
  its own Progress Checklist item.

Coverage: Codex read the plan (SHA256
`4140279f4049709813015ee8e5223e2f63ba41e7aff02ea151d60c322240e34f`), balance parsing,
snapshot retention, spend/cumulative accounting, the shared loader, display normalization and
existing monitor tests. Limitation: plan text and repository reads only; no patch, live API or
browser.

### Round 2 result (Codex, cross_provider) — REVISE

- `R5` (medium, migration): `balance.currency == "USD"` is not an upgrade-only marker. After a
  genuine CNY history later sees a USD-only response, the retained CNY samples would be
  reinterpreted as USD. Disposition: accepted. The cache now writes `_schema: 2`; USD-only
  migration runs only for an unmarked legacy cache, and a CNY -> dual -> USD-only repeated
  poll regression is added.
- `R4` (low, checklist): fix application, proof rerun, re-inspection, archival, completion
  status and final commit shared checkboxes. Disposition: accepted; each is now its own item.

Coverage: Codex verified the revised plan SHA256
`4da72eed769cca62dc26786510664edcdd948ef6603b3b3da9a78902dbef4cf4`, the loader/allowlist,
raw-balance totals, legacy fallback and the remaining checklist. Limitation: plan text only; no
patch, live API or browser.

### Round 3 result (Codex, cross_provider) — REVISE

- `R6` (medium, failure path): publishing `_schema: 2` on a failed first refresh would leave a
  legacy USD-only cache un-converted and skip migration forever. Disposition: accepted. Legacy
  conversion and cumulative-total derivation now run before the marker is published, including
  on a failed refresh; the failed result persists the converted history with no new sample or
  spend. A regression test covers legacy USD-only -> failed first refresh -> successful dual
  refresh.

Coverage: Codex verified plan SHA256
`ca5763f55007b442e7628511ded88408e77bc19434f8e962961846670cbb6a9d`, the schema guard, failed
fetch handling, unconditional cache publication and affected writers. Limitation: plan text
only; no patch, live API or browser.

### Round 4 result (Codex, cross_provider) — APPROVED

No findings. Codex verified plan SHA256
`b6178600cb129ff38412c731a3180f4f57fd90a2459137875fabfd68b46a638d`, the R6 migration ordering
and failed-fetch persistence, the loader allowlist, currency-aware totals, the upgrade-only
schema guard and the split checklist. Approval is bound to that plan hash. Implementation now
starts from the recorded pre-build commit; the approved plan is not changed without a new
review.

## Build notes (host=deepseek, builder=deepseek)

Pre-build commit: `68972a84db1678d2febeb4ed0409363a5c886fd6`.

Changed files:
- `runner/deepseek_monitor.py` — raw per-currency snapshots, `_schema: 2`, one-shot USD-only
  migration, dual-currency deltas/totals, UTC month fields, clamped display totals, dual-currency CLI.
- `runner/usage_reader.py` — `DEEPSEEK_MONTHLY_CAP_USD = 20.0`, loader allowlist, three DeepSeek
  cards, old-cache fallbacks, no Claude scan for DeepSeek, removed the unreachable run-log branch.
- `runner/templates/index.html` — `value` support in `_updateOneRow` and the three-card row.
- `runner/app.py`, `runner/modules/backends/deepseek.py` — additive API pass-through.
- `tests/test_deepseek_usage.py` — 10 focused tests.

Proofs run:
- `python3 -m py_compile runner/deepseek_monitor.py runner/usage_reader.py runner/app.py runner/modules/backends/deepseek.py` — pass.
- `pytest tests/test_deepseek_usage.py -q` — 10 passed.
- `pytest tests/test_dsh_backend.py -q` with `GIT_OPTIONAL_LOCKS` unset — 49 passed. (The ambient
  dsh session exports `GIT_OPTIONAL_LOCKS=0`; the unmodified env test asserts it is absent.)
- `pytest tests/test_claude_account.py tests/test_activity_chart.py -q` — 45 passed.
- Live temp-cache dry run against `/user/balance`: schema 2, month `$6.10 / $20.00`, balance
  `$19.81 USD + ¥0.00 CNY`, recent `$0.19 (5h) · $3.57 (7d) · $6.10 (30d)`. No write to
  `~/.deepseek/usage.json`.

Deviations to inspect:
- Retention is **31 days**, not the plan's 32: one calendar month is at most 31 days and this
  keeps the existing retention-boundary test (`test_old_spend_survives_many_polls`) valid.
- The live API returned a small negative CNY balance (`-0.05`). Display totals clamp each
  currency at zero so the balance card stays consistent; raw negative values remain in the
  monitor's `balance` record and spend deltas still count an overdraft.
- Top-level `balance_total_usd`/`balance_total_cny` are written by the monitor in addition to
  the nested `balance` copy, so the loader and API wrappers do not need a fallback.

### Inspection round 1 (Codex, cross_provider) — REVISE

Base `68972a8`; snapshot `098eb8a71075dc37454239b2bf9176878f546831690bc73dddf0bf2a22f8f1a0`;
diff `7b63293f69127a3b7849c5d8af0250fbbd197ff030d8f89b46bf45cf48839235`.

- `AGE147-01` (medium, monitor rounding): `_spend_delta` rounded every drop before summing, so
  thousands of ¥0.01 drops drifted to $5.04 instead of $5.00. Disposition: accepted.
  `_spend_delta` now returns full precision, `_spend_since` rounds the aggregate, and cumulative
  state keeps 8 decimals. Added the 3,600-small-drops and 100-poll cumulative tests.
- `AGE147-02` (medium, USD-only display): the synthesized `balance_cny` was shown as extra CNY.
  Disposition: accepted. Display components come from `raw_balances`; a legacy USD-only
  `currency` marker suppresses synthesized CNY. The monitor CLI uses the same rule. Added the
  USD-only display test; the live check now prints `$19.76 total ($19.76 USD)`.
- `AGE147-03` (medium, API totals): `_ds_load_usage` and `Module.load_usage` defaulted missing
  totals to zero. Disposition: accepted. Both use the shared
  `usage_reader.deepseek_balance_totals`, with a legacy-wrapper test.
- `AGE147-04` (low, notices): the account-level and stale notices lived only in `sub_line`,
  which the template does not render. Disposition: accepted. `display_line` now carries
  `account-level` and `stale`; `sub_line` is the card tooltip in both initial HTML and JS.
  Added the stale-display test.
- Limitations: the file-backed precedence test used the same month/30-day value, and the
  genuine-CNY -> dual -> USD-only regression was missing. Disposition: accepted. The file-backed
  test now uses 30-day 9.0 against month 6.0, and `test_cny_history_survives_later_usd_only`
  covers the sequence.

Rerun proofs after fixes: `py_compile` pass; `tests/test_deepseek_usage.py` 16 passed;
`tests/test_dsh_backend.py` 49 passed (with ambient `GIT_OPTIONAL_LOCKS` unset);
`tests/test_claude_account.py tests/test_activity_chart.py` 45 passed.

### Inspection round 2 (Codex, cross_provider) — APPROVED

Base `68972a8`; snapshot `98be4fc3de3463bf0ab01f47278ae04e704379b07f453ed3c973a37932b1db81`;
diff `3cfd9c7f8b4e49524693aab49bc8f1488737412fd7db415b14478a6782ae7865`. No findings. All
manifest hashes matched. The final code snapshot is unchanged from this inspection; the only
later edits are this log, the plan checkboxes/status, and `docs/context-maintenance.md`.

## Completion

Plan and log archived to `docs/exec-plans/completed/`. Validation and next action are recorded
in `docs/context-maintenance.md`: restart the managed runner so the DeepSeek poll rewrites
`~/.deepseek/usage.json` with `_schema: 2` and the month fields, then confirm the live row.
