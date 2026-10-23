# How Claude and Codex usage windows reset (AGE-104 research, 2026-10-23)

Why this matters: the dashboard shows each provider's server-reported `resets_at`.
That time is correct when it is read, but both providers also reset limits outside
that schedule, so a countdown can go stale without warning.

## Codex (ChatGPT plan, `limit_id: codex`)

**Evidence.** The weekly (`secondary`, 10080 min) window was traced from 2,761
rate-limit snapshots in `~/.codex/sessions/**/*.jsonl` between 2026-10-01 and 2026-10-23.
Each row below is a window that ended before its `resets_at`:

| Reset between (ET) | Weekly used before | New window starts (= new `resets_at` − 7d) | Cause |
|---|---|---|---|
| Fri 10-16 12:35 → 16:33 | 100% | 16:33 | No global reset that day → a **banked full reset** used at the limit |
| Sat 10-17 15:25 → 20:03 | 44% | 20:03 | Global reset, Oct 17 21:12 UTC (17:12 ET) |
| Mon 10-19 09:50 → Tue 10-20 13:50 | 34% | 13:50 | Global reset, Oct 20 06:33 UTC (02:33 ET) |
| Thu 10-22 11:03 → 14:42 | 45% | 14:42 | Global reset, Oct 22 17:00 UTC (13:00 ET / 10:00 PT) |

Global reset times come from the trackers below. Each one matches a reset seen in the logs.

**Rules this implies**

- The weekly window has no fixed weekday. After any reset (scheduled, global or banked),
  the next window starts at the **first request after the reset**, and `resets_at` is that
  moment + 7 days. A window that expires unused stays expired until the next request.
- OpenAI runs **global resets** often and without a schedule: seven between Oct 2 and
  Oct 22, 2026, usually announced by Codex lead Tibo (@thsottiaux) on X. They are not
  recorded locally and nothing in the API says one is coming.
- **Banked resets** are credits that OpenAI hands out to every account
  (e.g. Sep 22, Sep 29, Oct 7). The user spends them. App-server exposes them as
  `rateLimitResetCredits` (`availableCount`, credits with `status`
  `available` / `redeeming` / `redeemed`, plus `granted_at` and `expires_at`). Credits that
  have been spent drop out of the list, so the list says nothing about past use.
- Codex's local logs (`~/.codex/logs_2.sqlite`) do not record when a credit was used.

## Claude (claude.ai subscription)

- The weekly window is **anchored to a fixed time per account**. On the personal account,
  `seven_day.resets_at` read `2026-10-23T00:59:59Z` on both 10-16 and 10-17, with
  `seven_day_breakdown.window_started_at` at `2026-10-16T00:59:59Z`. The team account's
  limit errors said "weekly limit resets Oct 5 at 1am" and later "Oct 19 at 1am"
  (America/New_York). Both are Sundays, two weeks apart.
- `five_hour` is a rolling window that starts at the first message after the previous one ends.
- **Reset grants** (`cedar_ember` in `/api/oauth/usage?cedar_ember=1`, sent with the Claude
  Code User-Agent): user-triggered, they clear the windows named in `clears`, and they have
  an `ends_at` expiry. Example: the "Claude Opus 5.5 launch" grant was usable until
  2026-10-22 16:00Z. Third-party guides say using one does **not** move the weekly reset time.
- `juniper_tide`: a separate session-limit (5h) reset offered once a week. It was `null`
  on this account.
- Anthropic has also reset everyone's limits a few times in 2026 (May 15, Jul 10, Jul 16),
  usually after outages and often with no explanation. Reports say the per-account weekly
  time stays the same.

## Dashboard consequences

- Codex `resets_at` is a best estimate until the next global reset. After a reset the
  value changes only once the account is used again. Don't treat a countdown as a promise.
- Claude `resets_at` is stable week to week. Only an Anthropic-wide reset or a spent grant
  refills a window early, and neither moves the anchor.

## Sources

- Codex global/banked reset log: <https://codex-resets.com/>, <https://opentherank.com/codex-reset/>
- Reset-scope caveats: <https://github.com/openai/codex/issues/20395>,
  <https://community.openai.com/t/codex-rate-limits-reset-for-all-paid-plans-april-28-2026/1379921>
- Claude reset grants and fixed weekly time: <https://www.ssdnodes.com/learn/can-you-reset-claude-usage-limits>,
  <https://smartscope.blog/en/blog/claude-usage-limit-reset-weekly-schedule-codex-2026/>
- Anthropic-wide resets: <https://startupfortune.com/anthropic-resets-claude-code-usage-limits-again-after-a-rough-week-of-outages/>,
  <https://www.implicator.ai/anthropic-resets-claude-limits-for-third-week-without-explaining-why/>,
  <https://pasqualepillitteri.it/de/news/2617/claude-rate-limits-zuruecksetzen-5-stunden-wochenzaehler-15-mai-2026>
