---
status: completed
created: 2026-10-21
completed: 2026-10-21
---

# Board card declutter

## Goal

The user's request (2026-10-20, with a screenshot of card AGE-110): "既然这个 tab 已经写了具体的 GPT-6.1-SOL，就不用写MODEL这几个字，CODEX也不要写，把CODEX这个蓝色放在GPT-6.1-SOL上面，如果模型是claude或deepseek也是类似的操作，terminal 也不用写了。除非是最后一步出了问题，什么verify:fail 类似的error都不要写。tab下方的三个模型选择也都删掉……需要具体点击去之后detail，下方的三个模型选择才有必要保留。"

The card in the screenshot shows two badges, `MODEL · GPT-6.1-SOL` and `CODEX`. Below them are a project badge, `verify: fail` and `▤ Terminal`, and at the bottom three retry buttons: `↺ Claude`, `↺ Codex` and `↺ DeepSeek`.

The goal is a card that shows only what the user needs at a glance. The detail modal keeps every control and detail that leaves the card. The four items are fixed one by one, in the order of the Progress Checklist:

1. One model badge in the agent's colour.
2. No Terminal badge.
3. No verify-style badges unless the last step failed.
4. No retry row.

## Acceptance Criteria

- [x] A card with a recorded model shows one badge whose text is the model name, upper-cased (e.g. `GPT-6.1-SOL`). It has no `MODEL` text, and there is no separate agent-name badge.
- [x] That badge uses the agent's colour: Codex blue `#6fb5d4`, Claude orange `#e8a87c`, DeepSeek green `#7ec8a0`.
- [x] A card with an agent but no recorded model shows the same coloured badge with the agent's name in title case: `Codex`, `Claude`, `DeepSeek`. This covers a Todo card that never ran and a run record with no `model`, or with the legacy `model: "codex"` sentinel. The card never shows the synthetic `gpt-5.4-mini` guess.
- [x] A card with neither an agent nor a model shows no badge.
- [x] On tracker cards, the combined badge keeps the old agent badge's click behaviour. It toggles the preferred agent, starts a Todo card with its agent, opens a session card's reply, and does nothing while the card is locked.
- [x] On tracker cards, the combined badge keeps the old agent badge's tooltip.
- [x] A running card's badge is bold and uses the agent colour.
- [x] The badge sits in the card's meta row while idle and in the card's id row while running (D2).
- [x] No card shows a `▤ Terminal` badge.
- [x] No card shows a verify result or other non-final outcome: `pass`, `fail`, `timeout`, `error`, `no check`, `uncommitted changes` or `seed committed`.
- [x] A card shows a red `merge failed` badge when its own latest run record has `verify_badge: "merge failed"` (merge, the last step, failed for that ticket in that run).
- [x] A card shows a red `main checkout changed` badge when its run's `main_checkout_changed` is `true`. When `interactive_tab_open` is also true, it reads `main checkout changed (interactive tab open)`. This holds even when `verify_badge` is `seed committed`.
- [x] A card shows a red `main checkout unchecked` badge when its run's record has `main_checkout_changed` present and `null`.
- [x] A legacy record with no `main_checkout_changed` field but a `verify_badge` starting with `main checkout` shows that value as its red badge. A legacy record with neither field shows nothing.
- [x] The three badges above also show on cards whose latest run is older than the board's recent-runs window.
- [x] The In Review column puts a card first only when it shows one of those badges.
- [x] The detail modal's meta line shows `Verify: <value>` whenever the run record has a `verify_badge`.
- [x] No card shows the `↺ Claude / ↺ Codex / ↺ DeepSeek` retry row.
- [x] The detail modal footer still shows its three retry buttons, and they still work.
- [x] A Todo card keeps its single `▶ <Agent>` start button, and a session card keeps `✎ Reply`.

## Key decisions

- **D1 One badge, agent coloured.** The model badge takes over the agent badge's role: its colour, click handler, tooltip and locked state.
  - It reuses the existing `.agent-badge.claude/.codex/.dsh` colour rules; no new colours are added.
  - The text is the raw recorded model. When there is none, or it is the legacy `"codex"` sentinel, the text falls back to the agent's title-case name.
  - Upper-casing applies only to a model name (R4).
  - The board stops storing the synthesized `_displayModelLabel` value as `model`, so the card can tell "no model recorded" apart from a real one (R3).
  - The detail modal keeps using `_displayModelLabel` unchanged.
- **D2 Position unchanged.** The badge sits in the meta row while idle and in the id row while running, as the model badge does today.
- **D3 "The last step went wrong".** A project run goes through agent run → commit → verify → closing main-checkout check → merge.
  - The card shows a red badge only for the last step, merge (`merge failed`), and for the closing safety check (`main checkout changed…` / `main checkout unchecked`). Both need the user's action.
  - The safety warning comes from the record's own `main_checkout_changed` / `interactive_tab_open` fields, independent of `verify_badge`. `post_run` puts `seed committed` ahead of the safety values in `verify_badge`, so reading only `verify_badge` would hide the warning (R2).
  - A legacy record with no `main_checkout_changed` falls back to a `verify_badge` value starting with `main checkout`.
  - Every other outcome is hidden on the card and stays in the detail meta line and the terminal log.
  - The badge text has no `verify: ` prefix.
  - The user named `verify:fail` as the thing not to show. This set is the host's reading and can be changed easily.
- **D4 Older cards carry the same fields** (R1). `/api/runs/latest-by-issue`, which the board uses when a card's last run is outside the 80-run window, adds `model`, `verify_badge`, `main_checkout_changed` (only when present in the record) and `interactive_tab_open`. The board item mapping copies them.
- **D5 One helper** `_cardWarning(run)` returns the badge text or `''`. Both the card and `_verifyRank` use it.
- **D7 Deferred merges are out of scope** (R6). When ticket T-1 finishes while another run of the same project is still going, its merge is queued. A later run (T-2) then drains that queue. If T-1's merge fails at that point, the error is recorded only as `merge_error["T-1"]` on T-2's record, so T-1's card gets no `merge failed`. This is an existing producer limitation in `_merge_when_last`, not something the card can fix. This plan shows `merge failed` only for a record marked that way and leaves per-ticket attribution of deferred merges as a follow-up (noted in the review log).
- **D6 Dead code goes.** `openCardTerminal` has no caller other than the removed badge, so it is deleted.

## Non-goals

- No change to the detail modal's retry and dispatch buttons, the Terminal tab, or the server-side verify, merge and closing-check logic.
- No change to the project badge, attempt counter, tokens, or the waiting and session-open badges.

## Assumptions (verified at f1ff397)

- `_buildColCard` (`runner/templates/index.html` ~2601) builds the card.
  - `_modelBadgeHtml` (~2480) prints `MODEL · <label>`.
  - The agent badge uses `.agent-badge.<agent>` (lines 243–245).
  - `verifyHtml` holds both `verify: …` and `▤ Terminal` (~2691–2695).
  - The retry row is `_cardAgents` / `job-btn-group` at the end of the function.
- The board mapping (~2945) sets `model: _displayModelLabel(latest)`, which turns a model-less Codex record into `gpt-5.4-mini`.
- `/api/runs` returns every record field. `/api/runs/latest-by-issue` (`runner/app.py` ~5002) returns only `run_id, status, agent, agent_session_id, project_key, started_at, waiting` plus the resume fields.
- Run records carry `main_checkout_changed` (true / false / null, with `closing_check_error` when null) and `interactive_tab_open`. These come from `project_runs.closing_check` and `post_run`, and from `app.py` ~3364–3378.
- `merge failed` is set in `app.py` `_merge_when_last` (~3464).
- The detail modal footer has its own `#detail-retry-group` with the same three agents.

## Verification

- [x] Browser (isolated runner, Playwright Chromium): a reviewed Codex card whose record has `model: "gpt-6.1-sol"` shows exactly `GPT-6.1-SOL`, with no `MODEL` and no `CODEX` badge.
- [x] Browser: that badge's computed colour is `rgb(111, 181, 212)`.
- [x] Browser: a Claude card's badge colour is `rgb(232, 168, 124)`.
- [x] Browser: a DeepSeek card's badge colour is `rgb(126, 200, 160)`.
- [x] Browser: a Todo card with preferred agent Codex and no run shows `Codex` in title case, in blue.
- [x] Browser: a card whose latest record is Codex with no `model` shows `Codex`, not `GPT-5.4-MINI`.
- [x] Browser: a card whose latest record is Codex with `model: "codex"` shows `Codex`.
- [x] Browser: clicking the combined badge on a non-locked In Review tracker card changes its preferred agent.
- [x] Browser: no `▤ Terminal` badge exists on any card.
- [x] Browser: a card with `verify_badge: "fail"` and `main_checkout_changed: false` shows no warning badge.
- [x] Browser: a card with `verify_badge: "merge failed"` shows a red `merge failed`.
- [x] Browser: a card with `verify_badge: "seed committed"` and `main_checkout_changed: true` shows a red `main checkout changed`.
- [x] Browser: a card with `main_checkout_changed: null` shows a red `main checkout unchecked`.
- [x] Browser: a legacy card with `verify_badge: "main checkout changed"` and no `main_checkout_changed` field shows a red `main checkout changed`.
- [x] Browser: an idle card's badge is inside `.job-card-meta`.
- [x] Browser: a running card's badge is inside `.job-card-id`.
- [x] Browser: a card with `main_checkout_changed: true` and `interactive_tab_open: true` shows `main checkout changed (interactive tab open)`.
- [x] Browser: a card whose latest run is pushed out of the recent-runs window, with `main_checkout_changed: true` and a recorded model, keeps both its warning and its model badge.
- [x] Browser: in In Review, the warned card sorts above an unwarned card with `verify_badge: "fail"`.
- [x] Browser: the detail modal of the `verify_badge: "fail"` card shows `Verify: fail` on its meta line.
- [x] Browser: no card contains a `↺ Claude/Codex/DeepSeek` button.
- [x] Browser: the detail modal footer shows its three retry buttons.
- [x] Browser: the console shows no errors. Evidence: `/private/tmp/claude-501/bcd-verify/check.py` passed all checks with errors=[]. `Verify: fail` was confirmed separately: the script's inner_text check split it across a newline. Screenshot: `/private/tmp/claude-501/bcd-verify/board2.png`.
- [x] Board screenshot, read by the host to confirm it visually.
- [x] `grep -n openCardTerminal runner/templates/index.html` returns nothing.
- [x] Unit test: `/api/runs/latest-by-issue` includes `model`, `verify_badge`, `main_checkout_changed` and `interactive_tab_open` for a record that has them.
- [x] Unit test: `/api/runs/latest-by-issue` omits `main_checkout_changed` for a record without it.
- [x] Full suite `.venv/bin/python -m pytest -q` passes, with no new failures. Evidence: 776 passed.

## Progress Checklist

- [x] Codex plan review approved.
- [x] Item 1: `_modelBadgeHtml` drops its `MODEL · ` prefix.
- [x] Item 1: the board mapping stores the raw `latest.model` instead of `_displayModelLabel(latest)` (D1/R3).
- [x] Item 1: `_buildColCard` builds one badge with the `agent-badge <agent>` classes, text from the raw model or the title-case agent name, and the old agent badge's click, tooltip, locked and running states.
- [x] Item 1: CSS: model text upper-cased, agent fallback not upper-cased, running state bold.
- [x] Item 1: keep the badge in the meta row when idle and the id row when running (D2).
- [x] Item 1: the separate agent badge is removed from the card.
- [x] Item 2: the `▤ Terminal` badge is removed.
- [x] Item 2: `openCardTerminal` is deleted (D6).
- [x] Item 3: `/api/runs/latest-by-issue` adds `model`, `verify_badge`, `interactive_tab_open`, and `main_checkout_changed` when present (D4).
- [x] Item 3: the board mapping copies `main_checkout_changed` (keeping absent versus null) and `interactive_tab_open`.
- [x] Item 3: `_cardWarning(run)` returns `merge failed` for that `verify_badge`.
- [x] Item 3: `_cardWarning(run)` returns the safety warning from `main_checkout_changed` / `interactive_tab_open` when the field is present.
- [x] Item 3: `_cardWarning(run)` falls back to a `verify_badge` starting with `main checkout` when `main_checkout_changed` is absent.
- [x] Item 3: `_cardWarning(run)` returns `''` otherwise.
- [x] Item 3: the card renders only `_cardWarning`, red, with no prefix.
- [x] Item 3: `_verifyRank` uses `_cardWarning` (D5).
- [x] Item 3: the detail meta line shows `Verify: <value>`.
- [x] Item 4: the card retry row is removed.
- [x] Write the unit tests for `/api/runs/latest-by-issue`.
- [x] Run the browser checks.
- [x] Run the full suite.
- [x] Commit (no push).
- [x] Fresh Codex inspection approved: inspection 1, cross_provider, no findings.
- [x] Restart the live runner when it is idle. The idle-restart watcher (`/private/tmp/claude-501/pvst-verify/restart_when_idle.sh`) is armed, and it restarts once no job is running and no terminal is open.
- [x] Move the plan to `docs/exec-plans/completed/`.
- [x] Move the review log to `docs/exec-plans/completed/`.
