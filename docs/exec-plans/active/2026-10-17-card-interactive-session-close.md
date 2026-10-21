---
status: in-progress
created: 2026-10-17
---

# A card's interactive session can always be ended, and never locks the card forever

## Goal

After **Open interactive** on a card, the user can always get the card back: the session ends
when its agent exits, every action it blocks offers to end it, moving the card offers to end it,
and the board shows which cards hold one. Today (reproduced 2026-10-17 on AGE-105 and on an
isolated runner) the session outlives the agent as a login shell, holds the card's lock with no
visible owner, and Retry/Resume/reply answer only `409 an interactive terminal holds this card`.

## Acceptance criteria

- [x] AC1 — Exiting the agent (`/exit`, crash, Ctrl-C out) in a card-bound interactive session ends
  the terminal: no login shell remains, the card's lock (card or ticket lock) is released, and the
  card offers Mark done / Send back to Todo / Leave in review (existing `term_exit` → `_offerCardNext`). — verified: /exit ends the terminal, card unlocked, choice shown; leftover processes ended (tests)
- [x] AC2 — Retry (↺ Claude/Codex/DeepSeek), the Comment/Feedback reply of a session card, the
  Projects-panel **Resume** of a card session, and a drag/save to In Progress, when refused because
  an interactive terminal holds the card, show a confirm *"An interactive session is open on this
  card. End it and continue?"*. Yes ends that terminal and re-sends the same request once; No
  changes nothing. A refusal caused by a running headless attempt is unchanged (no confirm). — verified: board ↺, detail ↺, reply, drag/Start/agent badge, Resume (unit) — decline changes nothing, accept resends once
- [x] AC3 — Moving a card that holds a live interactive session to Done, Cancelled or Todo (board
  drag or the detail State + Save) first asks *"This card has an open interactive session. End it
  too?"*. Yes ends it then moves; No moves and keeps the session. — verified: Done/Cancelled/Todo (drag, Save, Approve, ×) ask; both branches
- [x] AC4 — A board card whose card holds a live interactive session shows a "session open" badge;
  the detail modal shows **End session** in its header whenever that card holds a live session,
  and opens the Terminal tab by default in that case, whatever the column. — verified: badge, header End session, Terminal first, also after tab close/reopen and for trash cards
- [x] AC5 — Nothing is ever ended without the user's click: no automatic kill on browser close,
  modal close, reload, or card move.

## Approach

1. **Card-bound resume ends with its agent** — `runner/modules/pty/__init__.py` `open_terminal`:
   when `rec is not None` (the terminal is bound to a run's card), build
   `argv = [shell, "-l", "-c", shlex.join(resume)]` without `; exec $SHELL -l`. Unbound Projects-panel
   resumes keep the shell fallback. The reader thread already marks `alive=False`, calls
   `_finalize` (releases holds, audits once) and emits `term_exit`.
2. **Machine-readable refusal, at the real HTTP refusal sites** — new
   `pty.card_terminal(card_key=None, project_key=None, ticket=None, agent=None, session_id=None) -> str | None`:
   the `term_id` of a live terminal (`alive and pid`) matching any given key — `t.card_key == card_key`,
   or `(t.project_key, t.ticket) == (project_key, ticket)`, or `(t.agent, t.session_id) == (agent, session_id)`.
   At each site below, **before** the existing generic/advisory refusal, if `card_terminal(...)` finds a
   terminal, return the same status with `{"ok": false, "error": <existing text>, "code": "card_interactive",
   "term_id": ...}`. When none matches (a headless job, an external process, a rename), the response is
   byte-for-byte unchanged.
   - `api_session_to_board` — the `(agent, sid) in _live_session_ids()` → `409 "still running"` branch (~L3951);
   - session-card reply `_retry_session_card_held` — the `session_in_use` → `in_use_elsewhere` branch (~L4410)
     and the `reserve_card` `ProjectError` branch (~L4421);
   - ordinary retry — the `session_in_use` → `in_use_elsewhere` branch (~L5282) and the `card_lock`
     `TicketLocked` branch (~L5328);
   - tracker PATCH to In Progress — the `reserve_card` `TicketLocked` branch (`modules/linear/__init__.py` ~L1575);
   - local-mirror PATCH to In Progress — `_issues_local_patch`'s `card_locked(...)` → 409 branch
     (`modules/linear/__init__.py` ~L1519) gets the same classification (harmless for other callers).
     **Client sequencing for an In Progress target:** `_moveLinearIssueToColumn` and `saveLinearIssue` stop
     sending the local-mirror state write and send only the dispatching PATCH, awaited. That route already
     reserves the card before any write and itself updates the local tracker and cache (both tracker modes,
     `_issues_patch_reserved`), so a refusal writes nothing and No leaves the card where it was; its
     running-headless-attempt behavior (update without a second launch) is untouched. `saveLinearIssue`
     sends its title/description/agent through the local mirror without `state_name` only after the
     dispatching PATCH succeeds. A `card_interactive` refusal triggers the confirm and the resend repeats
     the same dispatching PATCH; any other refusal reverts the optimistic board state and shows its error.
     Moves to every other state keep today's two writes unchanged.
3. **One client helper, in the shared request paths** — `index.html`:
   `async function _endCardSession(termId) -> bool` closes one terminal over the socket and returns
   success. It first adds `termId` to `_offeredTerms` (the existing once-per-terminal set of
   `_offerCardNext`) so neither `term_exit` nor the close ack can open the obsolete Mark done / Todo /
   Review choice, whichever arrives first; on a failed close it removes it again. It also drops any panel
   tab of that terminal (as `_cardTermEnd` does).
   `async function _confirmEndThen(body, resend)`: if `body.code === 'card_interactive' && body.term_id` →
   `confirm("An interactive session is open on this card. End it and continue?")` → Yes:
   `_endCardSession` → on success `resend()` exactly once (a second refusal shows its own error, no loop);
   No or failure: return false and leave everything as it was.
   Wiring (one place each, so every caller is covered):
   - `_postRetry` / `retryRun` — used by board ↺, detail ↺ and the reply submit; the resend reuses the
     original captured request body (reply text, attachments, agent);
   - `_resumeToBoard` — Projects-panel Resume;
   - `_moveLinearIssueToColumn` and `saveLinearIssue` — a refused move to In Progress.
   **No optimistic loss on decline/failure:** draft clearing, attachment removal, dictation
   cancellation, `_detailLinearInitial` bookkeeping, optimistic board state and modal closure in
   `retryFromDetail`, `saveLinearIssue` and `_moveLinearIssueToColumn` happen only after the request
   (or its single resend) succeeds; on decline or failure the optimistic board state is reverted and the
   captured form content and attachments stay.
4. **Moves (AC3)** — `async function _maybeEndCardSession(cardKey) -> 'ended' | 'kept' | 'none'`:
   `term_list`, find a live `kind==='resume'` with `card_key === cardKey`; if found,
   `confirm("This card has an open interactive session. End it too?")`; Yes → `_endCardSession` (choice
   suppressed as above). Called before the PATCH in `_moveLinearIssueToColumn` and `saveLinearIssue`
   when the target state is Done, Cancelled or Todo. "kept" and a failed close continue the move with
   the session left open.
5. **Visibility (AC4)** — `refreshJobBoard` fetches `term_list` once per refresh and keeps
   `_liveCardKeys` (card_key of live `resume` terminals); the card renderer adds a `session open`
   badge when the item's `linear_issue_id || task_id` is in it. `openDetailModal` shows a header
   **End session** button and switches to the Terminal tab when the card's key is in the set; the
   header button uses the Terminal tab's own End session path (`_cardTermEnd`: close, drop any panel
   tab, offer the next-state choice once) — this standalone end is the one case that does offer it.

6. **A failed close never leaves an invisible lock** — `pty`: a new `Terminal.reader_done: bool` flag.
   Both hand-off decisions are made under `_finalize_lock`, and `_finalize(t)` is always called **after**
   releasing it (the lock is non-reentrant and `_finalize` takes it itself):
   - `_reader` at EOF: `with _finalize_lock: t.reader_done = True; own = not t.closing` → then, outside the
     lock, `if t.kind == "resume" and own: _finalize(t)` (replaces today's unlocked `not t.closing` read);
   - `close_terminal` when `_kill_session` raises: `with _finalize_lock: t.closing = False; need = t.reader_done`
     → then, outside the lock, `if need: _finalize(t)`; return the existing `cleanup failed` error.
   Serialized this way, exactly one side sees the other's state, so finalization happens once whichever of
   "agent exits" and "cleanup fails" comes first; `_finalize`'s once-guard stays as a backstop. The terminal
   stays registered with `cleanup_failed=True` and, while alive, matchable by `card_terminal()`, so End
   session / end-and-continue can retry the close.

## Key decisions & trade-offs

- **End on agent exit, card-bound only** (Q1, confirmed by the user 2026-10-17): the
  leftover login shell is the root cause of the "locked forever" state. Losing the shell is cheap —
  the project's **Open terminal** still gives one. Unbound resumes keep today's behavior.
- **Ask, then end and continue** (Q2, confirmed by the user): no silent kill of a working agent;
  one click instead of a dead end. Rejected: auto-end (could kill live work), error-with-button
  (two extra clicks, same result).
- **Ask on move** (Q3, confirmed by the user): moving to Done/Cancelled/Todo is the moment the user
  is done with the card; "No" keeps today's behavior for anyone mid-session.
- Server-owned sessions that survive reload/browser close stay as designed (C2/UI-07); this plan
  only adds ending paths and visibility.
- `code`/`term_id` added to existing 409/400 bodies instead of new status codes: old clients ignore
  the extra fields.

## Non-goals

- Idle timeouts or automatic ending of sessions.
- Changing headless dispatch, quick-reply removal, or the Projects panel layout (2026-10-16 plan).
- Shell terminals opened from a project header (not bound to a card).

## Assumptions (sources)

1. Live refusal seen by the user: `POST /api/runs/d04019d7…/retry` → 409 twice
   (`~/Library/Logs/AgenticOS/runner.err.log`, 2026-10-17 05:42:32-33).
2. The fallback shell: `runner/modules/pty/__init__.py:468`
   (`shlex.join(resume) + f"; exec {shlex.quote(argv[0])} -l"`).
3. Natural exit already finalizes and frees the card: `_reader` → `_finalize` (`pty/__init__.py:183`);
   covered by `tests/test_card_terminal.py::test_natural_exit_frees_the_card_and_records_once`.
4. Card key: client `_cardKey()` = `linear_issue_id || task_id || runId` (`index.html:4569`); server
   `t.card_key` = same fields of the run record (`pty/__init__.py`, `t.card_key = ...` in `open_terminal`).
5. Reopening a card's Terminal tab does reattach a live session (verified on the isolated runner
   and on AGE-105 live); the defect is ending/unlocking and visibility, not reattach.

## Risks

- 2026-10-17 06:03: another session (the 2026-10-16 plan's build, run in the AGE-105 interactive
  terminal) was editing `app.py`, `pty/__init__.py`, `modules/linear/__init__.py`, `index.html` and
  others (808+/151- uncommitted). This build must start only after that work is committed, from its
  commit, and re-check the refusal-site line numbers in Step 2 against it.

- `index.html` carries uncommitted work from the 2026-10-16 plan; the build must start from a
  commit that isolates it (user decision pending), or the diff mixes both.
- A confirm() inside a socket callback chain must keep the existing generation guards (UI-05):
  a resend after the user moved to another card must not run against the wrong card.

- Open after the inspection budget (CR-01/02/03, see review log): all need a second browser tab with
  specific timing, or text typed while a retry is pending and the modal then closed.
- (Resolved in inspection 15, ICS-40: the cross-tab obsolete-prompt race of ICS-38 is closed by the
  per-terminal cleanup lock and the terminal-level superseded flag.)

## Verification

- `.venv/bin/python -m pytest tests -q` — expected: all pass (baseline 644 passed on 2026-10-17).
- New tests in `tests/test_card_terminal.py`:
  - card-bound resume argv has no shell fallback; unbound resume keeps it;
  - `card_terminal()` matches by card key, by (project, ticket) and by session, and ignores exited terminals;
  - local-mirror and dispatching PATCH to In Progress return `code=card_interactive` + `term_id` while a
    card terminal is live, and write nothing; with a running headless attempt the dispatching PATCH keeps
    today's response;
  - `_to_board_locked`: Resume of an older session A while session B of the same card holds a live
    terminal returns `code=card_interactive` with B's `term_id`; with a headless run instead, unchanged;
  - close cleanup failure followed by the agent's exit releases the card's locks and audits once; the
    agent exiting during the failed cleanup does the same; in both orders `close_terminal` returns (no
    deadlock, bounded by a test timeout) and `_finalize_lock` is free afterwards;
  - each refusal site of Step 2 (to-board, session-card reply in-use and reserve, ordinary retry in-use
    and TicketLocked, tracker PATCH) includes `code=card_interactive` and the right `term_id` while a
    card terminal is live, and is unchanged when a running attempt / external process holds it.
- Manual, isolated runner (verify skill, port 8599, fake `claude`; `SHELL` set to a wrapper that runs
  `/bin/zsh -f "$@"` so the fake stays on PATH):
  - AC1: Open interactive, end the fake agent → terminal ends, card unlocked, next-state choice shown;
  - AC2: with a live session, board ↺, detail ↺, reply submit, Projects Resume, drag to In Progress →
    confirm → Yes → session ended, the action runs once, no Mark done/Todo/Review prompt appears;
    No → nothing changes (reply text, attachments, card column and modal stay as they were);
  - AC3: drag the card to Done → confirm → both branches;
  - AC4: badge on the board card, header End session, Terminal tab opens by default; close the
    browser tab, open a new one → badge and End session still there.
- Live runner untouched until merge.

## Progress Checklist — verified: ends only on a confirm Yes or End session
- [x] User confirms Q1–Q3 recommendations (or overrides) and authorizes the build — "同意，go ahead claude to build", 2026-10-17
- [x] Isolate the 2026-10-16 uncommitted `index.html` work — N/A: its owner committed it (d4f6440); build base a35c029 is clean
- [x] Codex plan review approved — round 4, cross_provider, plan SHA256 43884eea…9115 (approval check passed)
- [x] Step 1: card-bound resume argv without shell fallback — test_card_bound_resume_ends_with_its_agent_and_unbound_keeps_a_shell
- [x] Step 2: `pty.card_terminal()` + `code`/`term_id` at all nine refusal sites (incl. `_to_board_locked`, local-mirror PATCH)
- [x] Step 3: `_endCardSession` / `_confirmEndThen` in `_postRetry`/`retryRun`, `_resumeToBoard`, move and save
- [x] Step 3b: optimistic changes deferred until success; restored on decline/failure
- [x] Step 4: `_maybeEndCardSession` before Done/Cancelled/Todo moves (drop + detail save; also Approve and the card's × cancel)
- [x] Step 6: failed-close cleanup hands finalization back to the reader — both-order tests, no deadlock
- [x] Step 5: board badge, header End session, Terminal tab default when a session is live
- [x] New server tests written and passing (8 in test_card_terminal.py, 1 in test_session_to_board.py)
- [x] Full suite passes — final code: 729 passed, 2026-10-18
- [x] Manual AC1 verified on isolated runner — /exit → terminal dead on server, no shell, next-state choice shown
- [x] Manual AC2 verified (both branches) — detail ↺ retry and drag to In Progress: decline = one 409, nothing changed (reply text kept, state Todo, no run); accept = 409 then one 200, one new attempt/dispatch, no next-state prompt. Projects-panel Resume covered by unit test only (no registered project on the isolated runner)
- [x] Manual AC3 verified (both branches) — move to Done declined: moved, session kept; move to Todo accepted: session ended, moved, no prompt
- [x] Manual AC4 verified, including after browser-tab close and reopen — badge, header End session, Terminal tab attached to the live session
- [x] AC5 confirmed: no path ends a session without a click — ends only via confirm() Yes or End session; modal close/reload only detach
- [ ] Fresh Codex inspection of the diff; findings dispositioned — BLOCKED: 20/20 inspections used; 47 findings dispositioned (45 fixed, 2 rejected with reasons), 3 open (CR-01 cross-tab supersession after a standalone close, CR-02 a pending cross-tab prompt restored after supersession, CR-03 reply text typed during a pending retry lost if the modal is then closed); user decides
- [ ] Live stuck session on AGE-105 ended by the user (or with their go-ahead)
