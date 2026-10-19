# Review log: card-context-usage

- 2026-10-19. The user started this with /claudex-loop: "加一个UI feature，现在UI看不到agent的ctx%, 需要把这个加在task 界面的合适位置。"
- Roles:
  - host = claude (planner and coordinator);
  - plan reviewer = Codex;
  - builder = Claude;
  - final inspector = a fresh Codex session.
- Models: CLI defaults; none requested explicitly.
- Fallback: same-provider-on-unavailable. Inspection: on.
- Round limits: 20 plan-review rounds, 20 fix rounds, 20 inspection rounds.
- Authorization:
  - Build: the feature request authorizes it, following this repo's prior claudex-loop practice ("claude build it, and codex review").
  - Commit: yes. Push: no.
  - Runner restart: only when idle.
- Budget: a small feature; a plan review is roughly 3 files plus the plan. The host resolved the routine choices itself (D1–D4) and asked no questions.

## Round 1 — Codex plan review: REVISE
- Result: /private/tmp/claude-501/claudex-ctx/r1/claudex-n6bxkld0/result.json (plan sha c9314efe…)
- Findings CTX-001..005 (4 medium, 1 low): completed linked cards lose ctx on issue-progress poll; project dsh stream log not discoverable via progress JSON; find_session scans full transcript; live model missing for [1m]; checkbox granularity.
- Dispositions: all accepted (see fb2.md text):
  Round 1 dispositions (all accepted):
  - CTX-001 accepted: context moved to a dedicated GET /api/runs/<run_id>/context route (D5), polled from the same 3 s tick for the displayed run id; progress endpoints untouched.
  - CTX-002 accepted: stream log falls back to deterministic _claude_stream_log_path(run_id) when the progress JSON has no stream_log.
  - CTX-003 accepted: new path-only projects.session_file(agent, sid); Claude never goes through _claude_summary.
  - CTX-004 accepted: model = _OBSERVED_MODELS[run_id], else newest stream-json init model, else record model.
  - CTX-005 accepted: every implementation step and verification case is its own checkbox.

## Round 2 — Codex plan review: REVISE
- Result: /private/tmp/claude-501/claudex-ctx/r2/claudex-1wldzunv/result.json (plan sha 6da7a800…)
- CTX-001..003 confirmed addressed. New: CTX-006 (init model can leave 2 MB tail), CTX-007 (session-bound cards without log never poll); CTX-005 still open.
- Dispositions:
  Round 2 dispositions (all accepted):
  - CTX-006 accepted: stream_model now scans incrementally with a per-path (inode, offset, model) cache (D6), so the init model never leaves view; added a route test with init >2 MB back and 180k usage -> 18%.
  - CTX-007 accepted: the modal interval now starts for any concrete non-linear run id; progress fetch stays gated on hasLog (D7); added a browser check for a session-bound card with no log_path.
  - CTX-005 accepted: Approach bullets are now individual checkboxes; split tail/partial-line, symlink/invalid-sid, span/refresh, helpers, and plan/log archiving into separate boxes. Design rationale stays in Key decisions prose.

## Round 3 — Codex plan review: REVISE (low only)
- Result: /private/tmp/claude-501/claudex-ctx/r3/claudex-8z8ga64y/result.json (plan sha 14a9fe05…). Prior correctness findings confirmed addressed.
- Dispositions:
  Round 3 disposition:
  - CTX-005 accepted: stream_model sub-steps (offset read, newline advance, reset, lock) and _refreshDetailCtx sub-steps (linear skip, fetch, guarded render, error swallow) are now separate checkboxes; the stream_model append and truncation checks are split. No nested plain bullets remain in Approach.
- Note: host drafted usage_reader.context_usage/stream_model, projects.session_file and app._run_context during rounds 2–3 (design unchanged since round 2).

## Round 4 — Codex plan review: APPROVED
- Result: /private/tmp/claude-501/claudex-ctx/r4/claudex-telqr478/result.json (plan sha e69f5ad8…), check: approval matches, assurance=cross_provider.

## Build (Claude)
- Pre-build base d767441. Suite 761 passed. Browser checks passed (isolated runner :8599, Playwright Chromium; script /private/tmp/claude-501/ctx-verify/check_ctx.py).
- Build fix: _tail_lines default arg bound at def time; now reads CTX_TAIL_BYTES at call time.
