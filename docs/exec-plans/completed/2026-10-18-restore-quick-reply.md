---
status: completed
created: 2026-10-18
completed: 2026-10-18
---

# Restore the card Terminal tab's quick reply, working

## Goal

The user asked (2026-10-18): "You removed quick reply, please add it back and make it work". It was
removed by the 2026-10-16 plan (§5 D5) after the report "这个task 里面的quick reply没什么用啊". The
causes found there were server-side and are fixed (D6: the agent's real error is recorded; D7: session
replies are not killed at 30 min). This plan brings the one-line reply back under the card's terminal
view so a reply can be sent while watching the session, and its run streams in the same place.

## Acceptance criteria

- [x] QR1 — The card's Terminal tab has a one-line reply box and Send button under the terminal view;
  Enter sends.
- [x] QR2 — Send continues the card's own session (`POST /api/runs/<latest>/retry`, `strict: true`):
  the same session, never a fresh one; the Terminal tab switches to the new attempt and streams it live.
- [x] QR3 — Offered only on the latest attempt and only when it has stopped; on an older attempt or
  while the latest is running the box is disabled with a reason in its placeholder.
- [x] QR4 — Refusals use the shared handling: the card's open interactive session asks "End it and
  continue?" (as Retry); a session open elsewhere asks once (`in_use_elsewhere`); declining sends nothing.
- [x] QR5 — On any failure the typed text stays and the status line shows the server's reason (e.g. the
  agent's usage-limit message); on success only the sent text is cleared.
- [x] QR6 — A reply typed for one card never goes to another (the box is reset when the card changes).

## Approach

- `index.html`: restore the markup/CSS removed in 1f3e108 (`.detail-term-reply`, `#detail-term-reply`);
  reset it in `_cardTermBind`; set enabled/placeholder in `_cardTermLoad`/`_cardTermUse` from "latest
  attempt" and "finished"; `_cardTermQuickReply` posts through `_postRetry(latest, {reply, strict: true})`
  (which already carries the card_interactive and in_use confirms), then refreshes the board, moves the view
  to the returned run (`_cardTermAttempts` + `_cardTermLoad`), and guards every await with the view
  generation.
- Tests: replace `test_quick_reply_is_gone` with a check that the box exists and posts a strict retry;
  the server's strict-continuation behaviour is already covered.

## Change found while verifying

- A strict (quick) reply used to fall through to a *new* session, noted, whenever the card's session could
  not be resumed (no transcript, moved, or claimed by another card) — the D3 fallback runs after the strict
  guard. A quick reply now refuses with the reason ("cannot continue this card's session: … — use Comment /
  Feedback to start a new one"), after the card-lock check so an open interactive session is still offered
  "end it and continue". The Comment / Feedback reply keeps its noted new-session fallback.
  `test_project_card_lock_refuses_quick_reply` updated to this rule; `test_a_quick_reply_never_starts_a_new_session` added.
- A quick reply whose run ends in error/timeout/stall gives its text back and says why in the status line.

## Non-goals

- Attachments or dictation in the quick reply (the Comment / Feedback box keeps those).
- Typing into a live interactive session from this box (the terminal itself takes input).

## Verification

- `.venv/bin/python -m pytest tests -q` — all pass.
- Isolated runner (verify skill, fake `claude`), Chrome: QR1–QR6 by hand, including the interactive-session
  confirm both ways and a failing reply keeping its text.
- Fresh Codex inspection of the diff.

## Progress Checklist

- [x] Markup, CSS and reset restored
- [x] Eligibility (latest + stopped) with placeholder reasons
- [x] `_cardTermQuickReply` via `_postRetry`, strict, live view of the new attempt, generation guards
- [x] Test replaced; full suite passes — 730 passed, 2026-10-18
- [x] Manual QR1–QR6 on the isolated runner — 2026-10-18: Enter sends; reply streamed in place under the card's own session (`[session 8efa0b88]` again); disabled "The agent is working" while running; usage-limit failure → text restored, status "reply not completed: You've hit your session limit…"; with the interactive session open, decline keeps both, accept ends it and continues session 90d73ecf with no extra prompt; text typed on A not shown on B
- [x] Codex inspection; findings dispositioned — 6 fresh Codex inspections, all findings fixed (server: strict reply never starts or swaps to another session; answers only the latest attempt, rechecked under the card lock; history-ordered latest attempt). Stopped there on the user's decision 2026-10-18 (cost vs. remaining edge cases); the inspection-6 fixes are verified by tests and browser but not re-inspected
- [x] Commit — full suite 735 passed, 2026-10-18
