---
status: completed
created: 2026-10-24
completed: 2026-10-24
---

# AGE-147: DeepSeek usage shows USD and a $20 monthly cap

## Goal

The DeepSeek account now reports two balances — USD and CNY — but the dashboard shows only CNY
and compares lifetime spend against the lifetime starting balance. Update the DeepSeek usage
row to show both currencies, track spend in both, and make the monthly budget a single
`$20.00` total (USD-normalized). The existing CNY history must keep working after the change.

Original request: "DeepSeek 的 usage 里面不光有人民币，还有美元。所以现在这个 UI 也要整体
update 一下，然后把每个月的上限设置为 total 二十美元。"

## Findings (recon)

- `deepseek_monitor.fetch_balance` already parses both `balance_infos` entries and returns
  `balance_cny` plus `balance_usd`, but `_balance_snapshots` stores only `balance_cny`, and
  `_spend_since` diffs only CNY. A USD balance is displayed as a number but never spent from
  the tracked totals.
- The live account currently reports `USD 20.00` and `CNY 0.67`; `~/.deepseek/usage.json` has
  372 CNY-only samples from 2026-10-15 onward, `total_cost_cny = 43.18` and
  `total_cost_usd = 5.9972`. That history must not be discarded when USD samples start.
- An old **USD-only** account is stored with a synthesized `balance_cny = balance_usd * 7.2`
  and `balance.currency = "USD"`. Its snapshots contain that synthesized CNY, so comparing
  them directly with a new dual-currency sample would invent a large CNY spend. Old code reset
  the sample list on a currency switch, so every legacy sample in one file shares the currency
  recorded in `balance.currency`.
- `usage_reader.load_deepseek_usage` is an allowlist: it drops any field not listed, so the new
  month/total fields never reach `compute_windows` or the API wrappers.
- `usage_reader.compute_windows("deepseek")` hard-codes `CAP_5H = 5`, `CAP_WEEKLY = 50`,
  `CAP_MONTHLY = 200` in CNY and never uses `CAP_MONTHLY`. The `window_5h` card is actually
  lifetime spend vs starting balance (`¥43.18 / ¥43.85`, 98%).
- `runner/templates/index.html` renders a single DeepSeek card (one of the three grid columns),
  so the row is visibly incomplete next to Claude, Codex and Gemini.
- The `compute_windows` deepseek branch returns unconditionally before an unreachable
  run-log fallback. It also calls `_today_stats_claude` (a Claude JSONL scan) even though the
  result is unused for DeepSeek.
- `_updateOneRow` in the template already supports a `value`/`value_suffix` big number for the
  third card only; the first two cards need the same branch to render a balance figure.

## Decisions

1. **USD is the budget currency.** The monthly cap is a single constant
 `DEEPSEEK_MONTHLY_CAP_USD = 20.0`. CNY spend is converted at the existing `_CNY_PER_USD = 7.2`
 and contributes to the USD total; USD spend contributes directly. Totals are also exposed in
 CNY so the UI can show both denominations.
2. **Monthly means the current UTC calendar month.** The monitor adds `month_cost`,
 `month_cost_cny` and `month_resets_at`. The 30-day rolling windows stay available for the
 recent-spend card. UTC matches the monitor's existing `today` boundary.
3. **Per-currency snapshots.** Snapshots keep raw reported balances: `balance_cny` only when the
 API reports CNY, `balance_usd` only when it reports USD. Old samples without `balance_usd`
 remain valid. Deltas are computed per currency only when both samples carry that currency, so
 a newly appearing balance is a baseline, not a spend, and a top-up is ignored.
4. **Legacy USD-only history is converted once, behind a schema marker.** The cache gains an
 additive `_schema: 2` marker. Only a cache without that marker is legacy; when its
 `balance.currency` is `"USD"`, every legacy snapshot's synthesized `balance_cny` becomes
 `balance_usd = balance_cny / 7.2` and the CNY key is dropped. A new dual-currency sample then
 shares USD with the legacy samples; the new CNY balance is a baseline. The conversion runs as soon
 as a legacy cache is loaded, **before** `_schema: 2` is published, even when the first refresh
 fails: a failed fetch may publish the migrated history and the migrated cumulative totals, but
 no new observation and no spend increment. Once `_schema` is 2, raw samples are never
 reinterpreted from the latest `balance.currency`, so a later USD-only response cannot turn
 genuine CNY history into USD history. Genuine CNY legacy history is left untouched.
5. **Retention grows to 32 days** so the oldest monthly baseline survives a 31-day month.
6. **No currency-set reset.** The old code reset all history when the reported currency changed;
 per-currency deltas plus the legacy USD conversion make that unnecessary.
7. **Three cards.** The DeepSeek row becomes: `Monthly Budget` (progress vs $20),
 `Balance` (USD + CNY and total), `Recent Spend` (5h/7d/30d in USD plus CNY equivalent).
8. **Backward compatibility.** Existing `window_*_cost`, `window_*_cost_cny`, `total_cost_usd`,
 `total_cost_cny` and `balance_*` keys keep their names. New keys are additive and added to the
 shared loader allowlist. The reader falls back to `window_30d_cost` when `month_cost` is absent
 (old cache).

## Approach

`fetch_balance` keeps the normalized `balance_cny`/`balance_usd` fields and adds
`raw_balances: {"CNY": float, "USD": float}` containing only currencies the API reported.
`balance_total_usd` and `balance_total_cny` are computed from `raw_balances`, so a USD-only
account is counted once, not as USD plus synthesized CNY. A USD-only account still gets the
legacy synthesized `balance_cny` for old consumers, and a CNY-only account keeps
`balance_usd = 0.0`.

`_valid_samples` accepts a sample with a finite `balance_cny` and/or `balance_usd` and keeps
whichever keys are present. A `_SCHEMA = 2` marker is written on every update. A small
`_migrate_usd_only_samples` helper runs only when the preceding cache has no schema marker
 **and** its `balance.currency == "USD"`; it rewrites those legacy synthesized-CNY samples to
 USD observations. The migration and cumulative-total derivation happen before the schema
 marker is published, so a failed first refresh persists the converted history (without a new
 sample or spend) and cannot bypass migration on the next poll. A cache that already carries
 `_schema: 2` is never migrated again, even if a later fetch reports only USD.

The spend helper returns `(usd, cny)` for one window: CNY drops add `drop / 7.2` USD and `drop`
CNY; USD drops add `drop` USD and `drop * 7.2` CNY. `_update_locked` builds the new sample from
`raw_balances` (falling back to the normalized fields for old/mocked payloads), skips sample
mutation when the fetch failed, appends only when a reported balance changed, and adds the
incremental per-currency cost to cumulative `_total_cost_usd` / `_total_cost_cny`. If either
cumulative key is missing, it is derived from the other at the fixed rate.

The UTC month start and next-month start produce `month_cost`, `month_cost_cny` and
`month_resets_at`; all existing `today` and `window_*` keys stay. The CLI prints both
currencies and the monthly figure. `_RETENTION` becomes 32 days.

`usage_reader` gains `DEEPSEEK_MONTHLY_CAP_USD = 20.0` and an extended
`load_deepseek_usage` allowlist (`month_cost`, `month_cost_cny`, `month_resets_at`,
`balance_total_usd`, `balance_total_cny`). The deepseek branch builds three complete cards
(including `tokens`, `limit`, `sessions`, `display_line`, `resets_at_unix`, `window_minutes` so
`load_windows`'s formatter keeps working). `window_5h` is `Monthly Budget` with
`pct = month USD / 20` and the line `$6.00 / $20.00 · ¥43.18`; `window_7d` is `Balance` with
`value = "$20.09"` and the line `$20.00 USD + ¥0.67 CNY · ¥144.67 total`; `aux` is
`Recent Spend` with `value = "$6.00"` and
`$0.09 (5h) · $3.47 (7d) · $6.00 (30d) · ¥43.18`, plus the account-level scope note and
`stale` when the cache is stale. Older caches fall back to `window_30d_cost` and computed
totals, using `balance.currency` to avoid double-counting a synthesized CNY balance. The
Claude `today` scan is skipped for DeepSeek, and the unreachable run-log fallback is removed.

`index.html` gains a `value`/`value_suffix` branch in the first-two-card loop of
`_updateOneRow`, guarded so existing agents are unchanged, and replaces the single DeepSeek
card with a three-card row driven by `windows_deepseek.window_5h`, `.window_7d` and `.aux`.
No pace or balance markers are added to the DeepSeek cards.

`app._ds_load_usage` and `Module.load_usage` forward the additive `month_cost`,
`month_cost_cny`, `month_resets_at`, `balance_total_usd` and `balance_total_cny` fields while
keeping every existing key.

## Non-goals

- No new exchange-rate service; `7.2` remains the fixed conversion used by the existing code.
- No change to token-based limits for Claude, Codex or Gemini.
- No change to the DeepSeek API key, polling interval or dsh dispatch.
- No schema migration of `usage.json` beyond additive keys; old files stay readable.

## Acceptance Criteria

- [x] A snapshot records only the currencies the balance API reported, and old CNY-only
      snapshots remain valid.
- [x] Spend decreases in CNY and USD both advance the USD total; top-ups are ignored; a
      newly reported currency starts as a baseline with no spend.
- [x] A legacy USD-only cache (`balance.currency == "USD"`, synthesized `balance_cny`, no
      `_schema`) is migrated once to USD observations without inventing CNY spend or doubling
      the balance total.
- [x] After `_schema: 2` is written, a later USD-only response does not reinterpret retained
      raw CNY samples; genuine CNY history and monthly spend stay unchanged.
- [x] A legacy USD-only cache whose first refresh fails still persists the converted USD
      history and schema marker; the next successful dual-currency refresh adds no fictitious
      CNY spend.
- [x] `usage.json` exposes additive `month_cost`, `month_cost_cny`, `month_resets_at`,
      `balance_total_usd`, `balance_total_cny`; existing keys still exist with the same meaning.
- [x] `load_deepseek_usage` forwards every new field, and a file-backed test proves the
      monthly value wins over the rolling 30-day fallback.
- [x] `compute_windows("deepseek")` reports the cap as `$20.00`, computes the monthly progress
      from `month_cost`, and renders USD plus CNY in all three cards.
- [x] The dashboard DeepSeek row renders three cards and `/api/windows/all` updates them without
      JavaScript errors.
- [x] An old `usage.json` without the new fields still renders using the 30-day and computed
      total fallbacks.
- [x] Existing DeepSeek monitor tests continue to pass.

## Verification

- [x] `python3 -m py_compile runner/deepseek_monitor.py runner/usage_reader.py runner/app.py runner/modules/backends/deepseek.py` — exits 0.
- [x] `.../.venv/bin/python3 -m pytest tests/test_dsh_backend.py tests/test_deepseek_usage.py -q` — all pass.
- [x] `.../.venv/bin/python3 -m pytest tests/test_claude_account.py tests/test_activity_chart.py -q` — no regression in the dashboard index render.
- [x] Unit test: dual-currency drops (`CNY 100/USD 20` → `CNY 90/USD 20` → `CNY 90/USD 15`)
      gives USD total `10/7.2 + 5` and CNY total `10 + 5*7.2`.
- [x] Unit test: samples before the UTC month start do not enter `month_cost`, while a sample
      inside the month does.
- [x] Unit test: a legacy history with `_total_cost_cny` and no `_total_cost_usd` migrates the
      cumulative total at 7.2.
- [x] Unit test: a legacy USD-only cache's synthesized-CNY snapshots become USD observations,
      and a following dual-currency response adds no fictitious CNY spend.
- [x] Unit test: genuine CNY history -> dual-currency -> USD-only -> repeated poll keeps the
      retained CNY samples and the monthly spend unchanged after the first upgrade.
- [x] Unit test: legacy USD-only cache -> failed first refresh -> successful dual-currency
      refresh keeps the converted history, writes `_schema: 2`, and adds no fictitious spend.
- [x] Unit test: `compute_windows("deepseek")` returns cap 20, dual-currency display lines and
      pct = month spend / 20.
- [x] Unit test: a file-backed `usage.json` with both `month_cost` and `window_30d_cost` loads
      through `load_deepseek_usage`, and the month value is the one used by `compute_windows`.
- [x] Render check: `app.app.test_client().get("/")` contains `Monthly Budget`, `$20.00` and
      `Recent Spend` when the DeepSeek usage fixture is installed.
- [x] Manual/visual check of the DeepSeek row against the live cache: three cards, no overflow,
      monthly pct matches `month_cost / 20`.

## Progress Checklist

- [x] Write the plan and start the append-only review log.
- [x] Plan review round 1 with Codex; record verdict and dispositions.
- [x] Revise the plan for accepted findings and re-review until APPROVED (cap 4 rounds).
- [x] Record the pre-build commit and implement the monitor snapshot/spend changes.
- [x] Implement `raw_balances` and USD/CNY `balance_total_*` in `fetch_balance`.
- [x] Extend `_valid_samples` to accept either currency and add `_migrate_usd_only_samples`.
- [x] Replace the CNY-only spend helper with a `(usd, cny)` per-currency delta helper.
- [x] Add the `_SCHEMA` marker and make USD-only migration run only for an unmarked legacy
      cache.
- [x] Rework `_update_locked` to append per-currency samples, skip failed fetches, and migrate
      cumulative totals.
- [x] Add the UTC month fields and raise `_RETENTION` to 32 days.
- [x] Update the monitor CLI output to show both currencies and the monthly figure.
- [x] Add `DEEPSEEK_MONTHLY_CAP_USD` and the new fields to the `load_deepseek_usage` allowlist.
- [x] Implement the `Monthly Budget` card in `compute_windows`.
- [x] Implement the `Balance` card in `compute_windows`.
- [x] Implement the `Recent Spend` card in `compute_windows`.
- [x] Skip `_today_stats_claude` for DeepSeek and delete the unreachable run-log fallback.
- [x] Add the `value` branch and the three-card DeepSeek row in `index.html`.
- [x] Forward the additive fields in `app._ds_load_usage`.
- [x] Forward the additive fields in `Module.load_usage`.
- [x] Add monitor tests for dual-currency spend, month boundaries and cumulative migration.
- [x] Add monitor tests for the legacy USD-only upgrade and failed-fetch no-append path.
- [x] Add the CNY-history -> dual -> USD-only repeated-poll regression test.
- [x] Add the legacy USD-only -> failed first refresh -> successful dual regression test.
- [x] Add reader tests for the cap, the three cards and the file-backed loader.
- [x] Add the dashboard render test for the DeepSeek row.
- [x] Run `py_compile` and the targeted pytest commands.
- [x] Inspect the live DeepSeek row data and confirm three cards and the $20 cap.
- [x] Run the first fresh Codex inspection against the recorded base commit.
- [x] Apply each accepted inspection fix to the code.
- [x] Rerun the affected proof checks after each accepted fix.
- [x] Re-inspect the new snapshot with a fresh Codex session (cap 4 rounds).
- [x] Update `docs/context-maintenance.md` with validation and next action.
- [x] Move the plan and log to `docs/exec-plans/completed/`.
- [x] Set plan `status: completed` and add the completion date.
- [x] Commit the final tree on `agent/AGE-147`.
