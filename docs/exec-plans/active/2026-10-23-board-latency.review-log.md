# Review log: board latency

## Scope and authorization

User (2026-10-23): dispatch (add Todo; agent icon In Review → In Progress) and the card UI are extremely slow; find the cause with /claudex-loop, check carefully and fix. Implementation authorized.

Roles: host/planner/builder = claude; plan reviewer = codex (default); inspector = codex (default). Rounds ≤ 20; fallback same-provider-on-unavailable. Inspection on.

## Recon evidence

See plan "Findings". Isolated copy at session scratchpad `wt/` (HEAD bed5c17 + copied `state/`, `outputs/`).

## Plan review round 1 — Codex — REVISE

Result: `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/b347833b-c03d-4ee6-868b-bc1897e63757/scratchpad/review-r1/claudex-tbxtt9by/result.json` (assurance cross_provider).

- BL-001 (medium): load_registry still spawns git per project on request threads, including dispatch admission. → accepted; kept deliberately, acceptance narrowed and spawn-spy test added.
- BL-002 (medium): invalidation during an active pass loses the follow-up refresh. → accepted; locked generation check with immediate re-run.
- BL-003 (low): plain bullets / bundled checkboxes. → accepted; split.

## Plan review round 2 — Codex — APPROVED (one low nit)

Result: `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/b347833b-c03d-4ee6-868b-bc1897e63757/scratchpad/review-r2/claudex-ttlm_b4i/result.json`. BL-001/BL-002 resolved. BL-003 remainder (manual dispatch+Todo check bundled) → accepted, split; re-sent for hash-bound approval.

## Plan review round 3 — Codex — APPROVED

No findings. `check` → "Approval matches the current plan; assurance=cross_provider".

## Build (claude, pre-build commit bed5c17)

Files: runner/app.py (commit-state cache + single worker with generation re-run; api_projects reads cache; session commit invalidates in `finally`), runner/projects.py (`_codex_rows` memo keyed by DB path + DB/WAL stat), runner/templates/index.html (single-flight `loadProjects`, `projects_commit_state` listener), tests.

Deviation: invalidation runs after every non-dry-run commit request, success or not (a failed merge may still have committed).

Proof:
- Targeted: tests/test_session_commit.py + tests/test_project_sessions.py → 86 passed.
- Full suite: 949 passed, 1 failed; base bed5c17: 946 passed, same 1 failed (`test_dashboard_select_needs_two_accounts[2-True]`, PermissionError reading obsidian wiki/log.md — sandbox). Failure sets identical.
- Isolated copy (state/outputs copied, no Linear key): `/api/projects` first call 2.34 s (includes warm-up; was 10.24 s), during a running pass 0.31 / 0.35 s, warm 0.229 / 0.236 / 0.234 s (was 8.5–10.6 s). After the pass, 61 session rows carry commit_state.

## Inspection 1 — Codex (fresh, base bed5c17) — REVISE

Result: `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/b347833b-c03d-4ee6-868b-bc1897e63757/scratchpad/inspect-1/claudex-ib0o6wcq/result.json` (cross_provider).

- BL-004 (medium): Codex-row memo can cache a pre-commit WAL snapshot under the final file signature indefinitely. → accepted; memo also expires after 5 s (`_CODEX_ROWS_MAX_AGE_S`), still one query per listing. Test `test_codex_rows_memo_expires`.
- BL-005 (medium): invalidation with an idle worker started nothing until another listing. → accepted; `_invalidate_commit_states` starts the worker itself when jobs are known. Test updated (no listing between commit and pass start).
- Targeted suites after fixes: 87 passed.

## Inspection 2 — Codex (fresh, base bed5c17) — APPROVED

Result: `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/b347833b-c03d-4ee6-868b-bc1897e63757/scratchpad/inspect-2/claudex-n225jrbe/result.json` (cross_provider). No findings; BL-004/BL-005 confirmed fixed. Full suite after fixes: 950 passed, 1 failed (same pre-existing env failure as base).

Pending: user-approved live runner restart, then manual live checks (`/api/projects` < 2 s, dispatch, Todo creation).
