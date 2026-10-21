# AGE-114 — Multi-turn memory across agents (Steps 0–2)

**Status:** completed · **Created:** 2026-10-21 · **Research:** `docs/design-docs/multi-turn-memory.md`

## Problem

See the research doc §4: a resumed plain card re-sends the nested history (F1); a switch carries only the last turn and no dsh transcript (F2); a board dispatch after a switch may resume the old agent's stale session (F3); records do not keep the reply (F5).

## Decisions

- D1 A run that **resumes** a session sends only the reply (+ attachments); with no reply, "Continue the task from where you stopped." The fresh-session fallback after a failed resume sends the handoff instead.
- D2 A **new** session on a card with history gets a flat handoff built from the run chain (`parent_run_id`): the root task, then one block per turn (agent, human reply, agent output), the reply, the transcript of every earlier session (dsh: the runner's stream log), and a pointer to `git status` / `git log`. Budget: last 3 turns whole, older ones cut to 1 500 characters per field, older turns dropped past 30 000 characters.
- D3 Records keep the human turn as `reply`; legacy records without it are parsed from their prompt on a best-effort basis.
- D4 A board dispatch never resumes a card session when the card has a newer session of another agent: it starts fresh with the card history (note `new session: the card's latest session belongs to <agent>`).
- D5 Step 3 (user's choice: the setting, not an import): every runner-launched Claude gets `--settings` with `instructionFiles: claude-md-and-agents-md`; confidential runs keep `--setting-sources ""`, which loads neither file.

## Progress

- [x] D1 reply-only resume in `api_run_retry`, handoff on the fallback
- [x] D2 `_card_history` + `_handoff_prompt` rewrite
- [x] D3 `reply` field on retry and session-card records
- [x] D4 dispatch skips a stale other-agent session and sends history
- [x] Test: resume sends the reply only; no nested "Original task"
- [x] Test: switch handoff lists every turn of a 3-turn chain and each transcript (dsh stream log included)
- [x] Test: budget drops/cuts older turns
- [x] Test: dispatch after a switch does not resume the old Claude session
- [x] Full test suite passes
- [x] /verify against an isolated runner
- [x] Test: a failed resume falls back to a new session that gets the history

- [x] D5 `CLAUDE_SETTINGS` on headless, project and runner-root interactive Claude argv
- [x] Test: `test_every_runner_launched_claude_reads_agents_md_too`; terminal and dispatch argv tests updated
- [x] Real Claude 2.1.305 check: with the flag it sees AGENTS.md's "Critical Token Budget Rule", without it does not

## Evidence

- `tests/test_card_memory.py` (5 tests) pass. Full suite: 779 pass (2026-10-21).
- /verify on an isolated runner (port 8617, fake claude/codex; 8599 was held by another session's runner):
  - `/run` "ROOT TASK" then two replies: the fake claude got `--resume S1 … REPLY TWO` and `--resume S1 … REPLY THREE`, the reply alone. Records: prompt 9 and 11 characters, `reply` set.
  - Switch to codex with "OVER TO CODEX": `codex exec` without resume, prompt = flat handoff (task, turns 1–3 with each human reply and claude answer, feedback, `[Agent switch]`, git hint); record `session_note: new session: switched from claude`. No transcript line: the fake S1 has no file in `~/.claude/projects`.
  - Next plain reply: `codex exec … resume cx1 CODEX NEXT`. `/api/maintenance` inflight 0 after.
- Not driven live: the board dispatch after a switch (D4) — covered by `test_dispatch_never_resumes_a_session_another_agent_moved_past` at the helper level.
- D5: full suite 780 pass; isolated runner (fake claude) showed `--settings {"pluginConfigs": …}` on both the first run and the `--resume` reply (2026-10-21).
