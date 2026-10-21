# Review log: board-card-declutter

- 2026-10-21. The user started this with /claudex-loop and a screenshot of card AGE-110. Request: drop MODEL/CODEX text and colour the model badge with the agent colour; no Terminal badge; no verify:fail-style badges unless the last step failed; no card retry row (the detail modal keeps it). "一个个修"
- Roles: host = claude, plan reviewer = Codex, builder = Claude, final inspector = fresh Codex.
- Models: CLI defaults.
- Fallback: same-provider-on-unavailable. Inspection: on.
- Round limits: 20 / 20 / 20.
- Authorization: build is authorized ("把需求…写清楚，一个个修"). Commit: yes; push: no. Runner restart: only when idle.
- Pre-build base: f1ff397.
- Host interpretation D3 (which badges count as "last step failed") is recorded in the plan for the user to correct.

## Round 1 — Codex plan review: REVISE
- Result: /private/tmp/claude-501/claudex-bcd/r1/claudex-pxyxkwij/result.json (plan sha f2417186…). Findings R1 (med), R2 (high), R3 (med), R4 (low), R5 (low).
- Dispositions:
  Round 1 dispositions (all accepted):
  - R1: /api/runs/latest-by-issue now carries model, verify_badge, interactive_tab_open and main_checkout_changed (when present); the board mapping copies them (D4). Verification added for a card whose latest run is outside the window.
  - R2: the safety warning is derived from main_checkout_changed / interactive_tab_open, independent of verify_badge (so seed committed no longer hides it). Absent and null are kept distinct. The same _cardWarning helper drives sorting (D3/D5). Verification added for seed committed + changed, null, and the interactive tab.
  - R3: the board stores the raw model; the card falls back to the agent's title-case name when there is no model or the model is the legacy "codex" sentinel; the detail modal keeps _displayModelLabel. Verification added for model-less and "codex" records.
  - R4: upper-casing applies to the model name only; the agent fallback is title case.
  - R5: the numbered Items are now references to the checklist; every actionable step is its own checkbox; Key decisions are rationale only.

## Round 2 — Codex plan review: REVISE
- Result: /private/tmp/claude-501/claudex-bcd/r2/claudex-d7j6mjs1/result.json (plan sha d064160e…). R1–R4 confirmed addressed.
- Dispositions:
  Round 2 dispositions:
  - R6 accepted by narrowing: per-ticket attribution of deferred (queued) merge failures is an existing producer limitation in _merge_when_last and is out of scope for this UI declutter (new D7). The merge-failed criterion now covers the card's own record marked "merge failed". The follow-up is recorded in the review log.
  - R5 accepted: new checkboxes for idle/running placement (acceptance, progress, two browser checks) and for the legacy fallback (acceptance plus a browser check). _cardWarning is split into four boxes.
- FOLLOW-UP (out of scope): attribute a deferred merge's failure to its own ticket's card (merge_error[T] on a later run's record).

## Round 3 — Codex plan review: APPROVED
- Result: /private/tmp/claude-501/claudex-bcd/r3/claudex-ozddwj6z/result.json (plan sha 61d0fce2…); check: approval matches, cross_provider.

## Build (Claude)
- Base f1ff397. Suite 776 passed. Browser checks passed on an isolated runner :8599 (fakes for claude/codex/dsh).
- Incident during verification: the badge-click check re-dispatched a card to Codex. Before a fake codex was added, the real codex CLI on PATH started a run in the isolated worktree. It was killed within minutes and left no file changes (the worktree had only the patched files). Fakes for codex and dsh are now in the isolated bin.

## Inspection 1 — Codex (fresh): APPROVED
- Result: /private/tmp/claude-501/claudex-bcd/i1/claudex-to0981tz/result.json, cross_provider, no findings.
- Rounds: 3 plan reviews, 1 inspection. All code by Claude, inspected by Codex. Follow-up kept: deferred-merge failure attribution (D7).
