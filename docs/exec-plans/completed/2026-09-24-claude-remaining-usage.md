---
status: completed
created: 2026-09-24
completed: 2026-09-24
---

# Show Claude quota remaining

## Goal and acceptance

Show `% remaining` on all three Claude quota cards on initial load and after live refresh. For the screenshot's 95% and 25% used values, display 5% and 75% remaining. Keep the used-percentage bar, pace marker, and other agents' display unchanged. Missing or stale Claude values continue to show no data.

## Approach and decisions

The Claude quota builder already supplies `remaining_pct = 100 - used_pct` for live values (`runner/app.py`, `_claude_quota_card`). In `runner/templates/index.html`, give Claude's remaining value display priority in the shared row macro and `_updateOneRow` refresh path. Keep the existing fallback ordering for Codex. This is a display-only bug fix; no API, schema, quota calculation, or dependency changes.

## Assumptions and risks

- The shown number is Claude's official quota value; the backend reports both used and remaining for live snapshots (`runner/app.py`, `_claude_quota_card`).
- `_updateOneRow` refreshes Claude, Codex, Gemini, DeepSeek, and DeepSeek TUI rows (`runner/templates/index.html`). Only `windows-row-claude` gets remaining-first display order.
- The only material risk is inconsistency between initial HTML and refreshed DOM; verify both paths.

## Toolchain and verification

Codex builds in this checkout. Claude CLI 2.1.282 is available for review and inspection. No requested model or effort override. Run `.venv/bin/python3 -m py_compile runner/*.py`, a focused Jinja render check for Claude live and missing values, and a focused JavaScript refresh check. Inspect the final diff and Claude's fresh inspection result.

## Progress Checklist

- [x] Obtain independent review of this plan and confirm approval applies to its final hash.
- [x] Update initial render and refresh display of Claude's three quota cards.
- [x] Run Python compile and focused initial-render/refresh behavior checks.
- [x] Record validation and next action in `docs/context-maintenance.md`.
- [x] Inspect the final diff in a fresh Claude session and resolve material findings.
- [x] Recheck evidence, complete this plan, and archive it with the review log.
