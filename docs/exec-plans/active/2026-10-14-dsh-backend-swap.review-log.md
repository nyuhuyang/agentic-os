# Review log: 2026-10-14-dsh-backend-swap

- 2026-10-14: Claude (host) wrote the plan at the user's request: "replace DS TUI with DeepSeek Harness and retire deepseek". The user asked for no review yet.
- Evidence gathered locally:
  - `dsh --version` = 0.1.0-rc.7;
  - `dsh --profile headless --help` and `--dump-config` (sandbox and approval presets);
  - `~/.dsh/profiles` contains only `headless`;
  - the launchd plist PATH;
  - `git grep` for deepseek references in `runner/`.
- Status: **NOT YET REVIEWED.**

## claudex-loop run (mode=review) — 2026-10-14
- Roles: host=claude (coordinator), reviewer=Codex CLI 0.162.0 (config default gpt-6.1-sol, effort high; no explicit model override), builder=Claude (not yet authorized), inspector=fresh Codex.
- MAX_ROUNDS=20; fallback=same-provider-on-unavailable; inspect=on.
- Budget choice (user): default model/effort, no round cap beyond 20. Rough estimate 100–200k tokens/round (plan + ~9.2k lines in runner/app.py, linear/__init__.py, index.html).
- Authorization: review only; build not authorized.

### Round 1 — Codex — REVISE
- Result: /private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-prototypes-agentic-os/c3556399-efee-4cfb-8b33-41a356cb4134/scratchpad/claudex/r1/claudex-rq3inbkm/result.json; session 01a13bb8-def3-7b21-b7c9-546ab4b8ba25; plan sha256 104ae23a…; assurance=cross_provider; observed model: not reported; 191 s.
- Findings (full text in result.json):
  - DSH-01 high: Seatbelt is (allow default) + write deny only, so network is open; confidential eligibility not gated.
  - DSH-02 high: module_registry appends the module name 'deepseek', so the dsh button would be hidden.
  - DSH-03 med: registry agents lists and load_registry('dsh') fall through to the unfiltered master.
  - DSH-04 med: JS retry/lock compares raw historical agent ids.
  - DSH-05 med: monitor reads the Rust checkpoint, which dsh never writes, so usage windows go stale.
  - DSH-06 med: monitor writes ~/.deepseek/usage.json, which contradicts the constraint.
  - DSH-07 low: session-dir diff can misattribute ids.
- Limitations: static only; dsh runtime behaviour unverified; canonical external registry unreadable.
- Dispositions:
  Round 1 dispositions (host = Claude). All 7 findings verified against source and ACCEPTED.
  
  - DSH-01 accepted. Verified seatbeltProfileArgs = (allow default) + file-write deny only. Decision 3 now: dsh always rejected for confidential projects regardless of mode (until a future release adds network confinement and spike (c)/(d) prove it). Permission-mode choice applies to non-confidential only. Decision 9 sequencing text updated.
  - DSH-02 accepted. backends/deepseek.py capability sets backend:"dsh"; module_registry.get_capabilities appends cap["backend"] when string, else module name. Test added: backends contains dsh, not deepseek.
  - DSH-03 accepted. New runner/agent_ids.py canonical_agent(); registry_loader.load_registry gets a dsh branch filtering on aliased agents lists; /run check and data-agents see dsh. Test added (legacy-compatible vs Claude-only skill).
  - DSH-04 accepted. JS canonAgent() used in card retry group, _updateDetailRetryLock, skill-card filter; lock skipped when canonical agent is dsh. Acceptance criterion added.
  - DSH-05 accepted. Monitor switches to balance-delta spend windows (decreases summed, top-ups ignored); tokens/sessions null, UI "n/a", labelled account-level. scan_checkpoint removed. Test + acceptance criterion added.
  - DSH-06 accepted. Constraint now explicitly permits the monitor's existing runner-owned cache ~/.deepseek/usage.json; config/sessions still protected.
  - DSH-07 accepted, simpler fix: drop the session-dir diff entirely; agent_session_id always null; runner never reads ~/.dsh. Resume + correlated ids deferred to a follow-up plan if spike finds a headless resume path.
  
  Also (host-found): checklist now names additional alias sites app.py:414-421, 2151-2157 (_agent_model), 2390 (_build_resume_cmd), linear/__init__.py:886.

### Round 2 — Codex (resumed session 01a13bb8…) — REVISE
- Result: /private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-prototypes-agentic-os/c3556399-efee-4cfb-8b33-41a356cb4134/scratchpad/claudex/r2/claudex-uk8o_aaj/result.json; plan sha256 32bdf199…; 88 s. DSH-01..07 accepted as resolved by reviewer.
- New findings, all in the balance-snapshot design introduced by the DSH-05 fix:
  - DSH-08 med: 200-sample cap holds only about 7 h.
  - DSH-09 med: a failed fetch is recorded as balance 0 and fakes spend.
  - DSH-10 med: unlocked multi-writer read-modify-write plus a shared tmp file.
  - DSH-11 med: monitor key precedence is config-first, but dispatch is env-first.
- Dispositions:
  Round 2 dispositions (host = Claude). All 4 verified in runner/deepseek_monitor.py and ACCEPTED; all folded into Decision 5's new "harden snapshot history" bullets, plus tests and the checklist.
  - DSH-08: append only on balance change; time-based retention (longest displayed window, which is 7d per usage_reader) keeping one pre-window predecessor; 200-cap removed. Test: spend 2d ago survives >200 polls.
  - DSH-09: append only on a validated successful fetch; failure keeps the baseline and sets stale/last_error. Test: success→failure→success gives no spend and no top-up.
  - DSH-10: fcntl.flock on usage.json.lock around the whole fetch→read→append→write cycle (thread + process); mkstemp + os.replace. Fetching inside the lock orders the observations. Test: two overlapping threads.
  - DSH-11: monitor key resolution becomes env-first; one shared resolver for dispatch, capability and monitor; key_fp (12-hex sha256 prefix) stored, and a mismatch resets the history. Test: key change gives no spend.

### Round 3 — Codex (resumed session 01a13bb8…) — APPROVED
- Result: /private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-prototypes-agentic-os/c3556399-efee-4cfb-8b33-41a356cb4134/scratchpad/claudex/r3/claudex-cyfyh881/result.json; plan sha256 2af08dd8c3bc20a434578144de6ca6a8aa2ead6eb07b1b35a7b0caaad71516f0; 39 s; assurance=cross_provider; observed model not reported (CLI default gpt-6.1-sol/high per config).
- Findings: none. Limitations: plan-level only; spike, worktree commit, launchd and end-to-end dispatch remain unverified until build.
- Approval is bound to the sha256 above. Any plan edit (including the banner line) requires re-review before build.
- Rounds used: 3/20. Build: NOT authorized yet.

### Post-approval change — dsh upgraded to 0.2.0-rc.2 (user-approved)
- User asked "do you need to download DeepSeek Harness?". Answer: rc.7 was already installed; npm latest was 0.2.0-rc.2. User chose "升级" (upgrade). Ran `npm i -g @deepseek-ai/dsh@0.2.0-rc.2`; `dsh --version` = 0.2.0-rc.2.
- The round-3 approval (sha 2af08dd8…) is VOID for the revised plan. New plan sha256 04f866cd…; re-review requested.
- Change summary:
  Post-approval plan change (host = Claude). The user approved upgrading dsh 0.1.0-rc.7 → 0.2.0-rc.2 (installed globally via npm, 2026-10-14). Your round-3 approval covered the rc.7 version; please review the delta.
  
  Facts verified from the installed 0.2.0-rc.2 source (paths under /opt/homebrew/lib/node_modules/@deepseek-ai/dsh/node_modules/@deepseek-ai/):
  - dsh-headless/lib/startup.js: new --json (NDJSON) and --session-id <id> (resume); stdin task via '-'.
  - dsh-headless/lib/json-stream-*.js projectJsonRun: first line is a session event {sessionId, cwd} from this process's own agent; then status/thinking/text/tool_call/tool_result; step_end.usage is present only when complete; final {text}; error {message} on a usage error.
  - dsh-headless/lib/index.js assertAdoptable: resume requires the same cwd, non-subagent, no agent preset.
  - dsh-sandbox-local seatbeltProfileArgs is unchanged: (allow default) + write deny. Confidential rejection stands.
  - --dump-config: permission/approval presets unchanged.
  
  Plan changes:
  - Decision 2: argv adds --json and '--'; resume argv adds --session-id; version gate >= 0.2.0-rc.2.
  - Decision 4 rewritten: _stream_dsh_run replaces _stream_deepseek_tui_run with the same tuple and progress file, so live streaming works. Session id comes from the session event (process-correlated; supersedes the DSH-07 null decision). Tokens are summed from step_end.usage, null if any step lacks usage. Retry/rework resume via --session-id; _session_lock treats dsh like codex; adoption failure means a failed run, with no silent fresh fallback.
  - Decision 1: the JS lock now applies to dsh (it reversed the round-1 skip); a historical deepseek run never locks.
  - Monitor: unchanged (balance-delta); per-run tokens are in run records; aggregating them is out of scope.
  - Spike (g)/(h) now probe the session event, usage and a real resume; tests add an NDJSON fixture case; acceptance adds resume; risks updated.

### Round 4 — Codex (resumed 01a13bb8…) — REVISE
- Result: /private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-prototypes-agentic-os/c3556399-efee-4cfb-8b33-41a356cb4134/scratchpad/claudex/r4/claudex-fnyq01df/result.json; plan sha256 04f866cd…; 152 s.
- Findings:
  - DSH-12: a Rust session id gets fed to --session-id.
  - DSH-13: rework/ticket redispatch don't resume.
  - DSH-14: routing parses NDJSON.
  - DSH-15: /stream stores NDJSON.
  - DSH-16: final + exit 1 failure is hidden.
- Dispositions:
  Round 4 dispositions (host = Claude). All 5 verified in source.
  - DSH-12 ACCEPTED. The lock helper now takes agent_session_id only from records whose raw agent equals the latest record's raw agent. A historical deepseek-tui Rust id is never passed to --session-id; the latest historical record gives a fresh dsh run. Test added.
  - DSH-13 PARTLY ACCEPTED, as a plan-wording defect. Decision: keep the existing semantics for all agents (retry of a completed run resumes; todo/rework reset and a Linear ticket returning to In Progress start fresh). Changing rework semantics globally is out of scope. Acceptance/test/dogfood wording changed from "rework resumes" to "retry resumes; reset fresh". "No silent fallback" removed: dsh uses the existing logged resume-failed→fresh fallback (app.py:3107-3115) like the other agents.
  - DSH-14 ACCEPTED. _ai_cli("dsh") has no --json; _ai_command adds --json only when output_format != "text". Routing sees plain final text. Routing subprocess.run gains env=_registry_exec_env(backend, registry), where dsh env is injected. Test added. (Thinking-vs-final fixture unnecessary: text mode never emits thinking.)
  - DSH-15 ACCEPTED IN PART. /stream uses text mode, so it stores the plain final message, never NDJSON. REJECTED: adding session/tokens metadata to /stream. /stream's _write_run_log (app.py:2697) records neither for claude/codex today, so that is a pre-existing gap across all agents, not introduced by dsh; it is out of scope.
  - DSH-16 ACCEPTED. ok = exit 0 AND final present; final.text is kept as output; error = error-event message + dsh:-prefixed stderr + exit code; _extract_real_errors keeps lines starting with "dsh:"; dsh call sites write status:error when not ok (other agents unchanged). Tests: final+exit1, exit0 with no final.

### Round 5 — Codex (resumed 01a13bb8…) — REVISE
- Result: /private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-prototypes-agentic-os/c3556399-efee-4cfb-8b33-41a356cb4134/scratchpad/claudex/r5/claudex-oxn16bir/result.json; plan sha256 28b2ae93…; 71 s. Reviewer accepted the DSH-12..16 dispositions, including the scope rejections.
- Findings:
  - DSH-17: the fresh fallback can double-run on a busy session or after a runtime failure.
  - DSH-18: session lookup crosses the reset boundary.
- Dispositions:
  Round 5 dispositions (host = Claude). Both verified (app.py:2962-2964 guard is a no-op; dsh-session-persistence throws SessionAlreadyOwnedError → session/writer-held).
  - DSH-17 ACCEPTED, with a simpler fix than classification: dsh has NO fresh fallback at all. The app.py:3107-3115 fallback is skipped for agent=="dsh"; any failed resumed run (adoption error, writer-held, or runtime failure after work) is recorded as status:error and the user resets to todo for fresh. Exactly one process per retry. Task-level reservation is not added: dsh's session write lease already serializes concurrent adopters, and the no-op guard is a pre-existing all-agent issue (out of scope). Test added.
  - DSH-18 ACCEPTED. The lock helper's backward scan stops at the newest todo/rework record and takes no id from it or anything older. Sequence test added (S1 → rework copy → fresh fail with no sid → retry is fresh).

### Round 6 — Codex (resumed 01a13bb8…) — APPROVED
- Result: /private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-prototypes-agentic-os/c3556399-efee-4cfb-8b33-41a356cb4134/scratchpad/claudex/r6/claudex-j_pl_4cn/result.json; plan sha256 e26092dab6000e715ed24a8d7cda5ad3755f368dbdaf0676ea9b836b1420983c; 22 s; assurance=cross_provider; observed model not reported (CLI default gpt-6.1-sol/high).
- Findings: none. Limitations: plan-level only; spike, implementation and end-to-end validation remain outstanding.
- Approval bound to the sha above, for dsh 0.2.0-rc.2. Any plan edit (including the banner) requires re-review. Rounds used: 6/20. Build NOT authorized yet.

### Post-approval edit — host (2026-10-14), NOT YET REVIEWED
- Trigger: multi-project dispatch Round 7, MPD-39. That plan's Security Precondition deletes `GET /stream`, which has no caller.
- Edited Decision 2 (lines 48, 51, 55) to drop the `/stream` text-mode, run-record and spawn-site requirements. Linear skill routing keeps text mode. No other change.
- Plan sha256 is now 77e13df9baf60de7702158cd04ffc9865712081c5e1a9b1bbff54190d02b802d. **The Round 6 approval (e26092da…) no longer covers it.** Re-review before build.

### Spike — 2026-10-14 (user: "先跑spike")
- Ran in session scratchpad `dsh-spike/` (throwaway repo with two worktrees and an `other` dir). No project code touched. `~/dsh-probe-B` (written by the full-access probe) was deleted afterwards. Six dsh runs on deepseek-flash, about 60k tokens total.
- Outcome:
  - headless `ask` auto-denies escalation ("no approval channel is available") with no hang;
  - workspace-write blocks outside writes, but the network is open;
  - git commit works in a worktree;
  - resume works in the same cwd and errors cleanly from another cwd;
  - bad key gives exit 1, `turn_end` error, and an empty final.
- Decision: `workspace-write`. Details are in the plan checklist.
- The plan changed, so the round-6 approval (sha e26092da…) is void. Re-review is needed before build.
- Cross-plan impact: multi-project dispatch MPD-33 (the runner-side dsh commit) is not needed, because a sandboxed dsh can commit in a worktree. That plan is not edited yet.

### Environment change — 2026-10-14 (user-requested cleanup)
- Found that `prototypes/DeepSeek-TUI/` (the Rust TUI build dir) no longer exists, so `/opt/homebrew/bin/deepseek` and `deepseek-tui` were dangling symlinks. The user had already removed the `deepseek-by` alias from `.zshrc`, and on the user's instruction ("直接开始清理") both dangling symlinks were removed.
- Plan edits: Decision 6 (the Rust binary is gone, so the deepseek-tui path is already broken); Constraints (dropped "do not uninstall the Rust binary"). Plan still needs re-review, together with MPD-39 and the spike edits.

### Round 7 — Codex (resumed 01a13bb8…) — REVISE
- Incremental re-review of the post-approval edits: MPD-39 `/stream` removal, spike results, Rust cleanup. Feedback: `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-prototypes-agentic-os/c3556399-efee-4cfb-8b33-41a356cb4134/scratchpad/claudex/feedback-r6.md`.
- Result: /private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-prototypes-agentic-os/c3556399-efee-4cfb-8b33-41a356cb4134/scratchpad/claudex/r7/claudex-_n9ob27k/result.json; plan sha256 aed5eb86…; 65 s.
- Finding DSH-19 (medium): `ask_deepseek.py --agentic` still shells out to the removed Rust `deepseek`, and `AGENTS.md:108` still recommends it.
- Disposition: ACCEPTED as proposed. Decision 5 records that `--agentic` is unavailable, that the script is not edited, and that migration is separate work. Decision 8 removes the `AGENTS.md` `--agentic` instruction. A stale "headless ask unknown" fact now points to spike (a).

### Round 8 — Codex (resumed 01a13bb8…) — APPROVED
- Result: /private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-prototypes-agentic-os/c3556399-efee-4cfb-8b33-41a356cb4134/scratchpad/claudex/r8/claudex-hjhyt27w/result.json; plan sha256 b4005b9ee029dc3fe6e5cb54c0c6096c74e84f8c66e926aa39255b0bcb648399; 20 s; assurance=cross_provider. No findings.
- `runner.py check` passed against this sha. Rounds used: 8/20.

### Build — authorized 2026-10-14 (user: "可以开始用claude 来build")
- Builder: Claude (host). Inspector: fresh Codex.
- Isolated worktree `.claude/worktrees/dsh-backend-swap`, branch `feat/dsh-backend-swap`, base `aa9cf13`.
- Reason for the worktree: the main checkout has unrelated uncommitted edits by another session (`runner/app.py` RUN_LOG move, `CLAUDE.md`, the dispatch plan).
- From here on, checklist updates are made in the worktree copy of this plan.

### Build — Claude, worktree `feat/dsh-backend-swap` (base `aa9cf13`)
- Proof: `py_compile` clean; `pytest tests/` 116 passed; `node --check` on the inline JS passed.
- Live smoke on real dsh 0.2.0-rc.2: a fresh run, then a resume of the same session that recalled `HERON-77`. The key was absent from argv.

### Inspection 1 — fresh Codex — REVISE (DSH-20..24)
- Result: /private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-prototypes-agentic-os/c3556399-efee-4cfb-8b33-41a356cb4134/scratchpad/claudex/i1/claudex-otkbo4n8/result.json
- All five ACCEPTED and fixed:
  - DSH-20: monitor key resolved once; a missing key is a failed fetch, not an account change.
  - DSH-21: historical direct-API `deepseek` runs never lock retry (backend and UI).
  - DSH-22: no invented cost when the model is unknown.
  - DSH-23: stderr drained concurrently; one deadline; kill and reap on expiry.
  - DSH-24: `/stream` canonicalizes its agent.

### Inspection 2 — fresh Codex — REVISE (DSH-25..27)
- Result: /private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-prototypes-agentic-os/c3556399-efee-4cfb-8b33-41a356cb4134/scratchpad/claudex/i2/claudex-aw8z99jz/result.json
- All three ACCEPTED and fixed:
  - DSH-25: Linear execution passes the selected skill to `_ai_command`. This also fixes codex, which had the same gap.
  - DSH-26: USD-only balances are normalized to CNY; a currency switch resets history.
  - DSH-27: non-finite balances are rejected; cached samples are validated; files are written with `allow_nan=False`.

### Inspection 3 — fresh Codex — REVISE (DSH-28, DSH-29)
- Result: /private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-prototypes-agentic-os/c3556399-efee-4cfb-8b33-41a356cb4134/scratchpad/claudex/i3/claudex-jhtfuycm/result.json
- Both ACCEPTED and fixed:
  - DSH-28: the Linear launch command is built inside the cleanup try, so a launch failure is recorded against the real run and the ticket is cleaned up.
  - DSH-29: the account-level spend scope is shown on the rendered DeepSeek card.

### Inspection 4 — fresh Codex — REVISE (DSH-30)
- Result: /private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-prototypes-agentic-os/c3556399-efee-4cfb-8b33-41a356cb4134/scratchpad/claudex/i4/claudex-d8fwihw8/result.json. It confirmed DSH-28 and DSH-29 fixed; no other findings.
- DSH-30 is REJECTED as out of scope; it is pre-existing and affects all agents. Dragging a linked ticket to Todo through the tracker PATCH routes writes no todo/rework run record, so a later retry still resumes the old session.
  - The base `_get_task_agent_lock` (aa9cf13) reads only RUN_LOG todo/rework records, so Claude and Codex resume the discarded session the same way.
  - The plan keeps the existing reset semantics for all agents (Decision 4; Round 4 DSH-13 precedent).
  - The fix needs a tracker-route reset boundary that changes semantics for every agent. At the user's request it was moved to `2026-10-13-multi-project-dispatch.md`, Phase 2 checklist.
- Inspections used: 4/20. The code is unchanged since Inspection 4, so it covers the final diff. Assurance: cross_provider.
