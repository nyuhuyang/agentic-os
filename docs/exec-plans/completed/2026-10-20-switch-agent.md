# AGE-113 — Switch a card to another agent

**Status:** completed · **Created:** 2026-10-20

## Problem

A card whose conversation ran on Claude cannot continue on Codex or DeepSeek (e.g. Claude usage ran out).

- P15 (`2f540c7`) hid the other agents' retry buttons once a card had a run, and `api_run_retry` silently replaced an explicit `agent` with the locked one.
- Session-to-board (`5f2c1ce`, STB-015) pinned session cards to their session's agent: the UI shows only that agent and `_retry_session_card` refuses any other with 409.
- The only way out was a reset to Todo, and the new agent then started from the issue text alone, without the conversation.

## Decision

An explicit, non-strict reply/retry with another agent is a **switch**:

- The new agent starts a **new session** in the same folder as the card's session: ticket worktree, project folder or runner root, whichever the old session used.
- Its prompt carries the task, the previous output, the reply and the path of the previous agent's transcript (`_handoff_prompt`).
- A session card persists no `resume_session` intent on a switch. The next reply continues the new agent's session in that folder through the existing card-session routing (D3).
- A quick reply (`strict`) still never switches: it keeps the same-session promise.

## Progress

- [x] `_handoff_prompt` helper shared by the plain retry and session-card switch
- [x] `api_run_retry`: explicit override ≠ lock → switch, routed by the old session's folder, fresh launch
- [x] `_retry_session_card`: non-strict other agent → fresh run of that agent in the session's folder, no intent
- [x] UI: card and detail retry groups show all three agents; the session agent stays highlighted, the others say "Switch to …"
- [x] Tests: plain card switch (fresh launch, previous output in prompt, codex CLI), session card switch (cwd = project folder, no intent, next reply resumes the new session), strict reply still refuses
- [x] Full test suite passes
- [x] /verify against an isolated runner

## Evidence

- `tests/test_switch_agent.py` (3 tests) pass; `tests/test_session_to_board.py` now asserts the strict refusal only. Full suite: 768 pass.
- /verify on an isolated runner (port 8599, fake claude/codex):
  - A review card last run by Claude shows ↺ Claude ("Continue this Claude session"), plus ↺ Codex and ↺ DeepSeek ("Switch to …"), both on the card and in the detail modal.
  - ↺ Codex with a reply launched `codex exec` without resume. Its prompt held the task, `CLAUDE ANSWER`, the reply and `[Agent switch]`. The record shows agent codex, the new thread id and `session_note: new session: switched from claude`.
  - A strict quick reply naming claude on that card stayed on Codex. It did not switch.
