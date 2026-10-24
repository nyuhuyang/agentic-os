---
status: completed
completed: 2026-10-23
created: 2026-10-23
---

# Activity chart: AgenticOS vs work vs other (AGE-128 follow-up)

## Goal

The dashboard Activity chart shows three daily lines over the last 30 local days so the user can see how much of their agent time goes to their day job:

1. **AgenticOS** — work on this tool itself.
2. **Work** — every confidential project (the user's day-job projects are exactly the confidential ones).
3. **Other** — everything else (personal projects, skill runs).

Hovering or clicking a day shows the three counts, the day's total and the Work share, with the existing crosshair.

## Current state (from commit 717a61a)

- `runner/app.py` `build_chart_data(runs)` returns `labels`, `values` (all runs) and `work` (runs outside AgenticOS). It is called with `load_runs(1_000_000, include_archived=True)` (all deduplicated run records, archived included).
- `runner/templates/index.html` draws two lines (`All conversations`, `Outside AgenticOS`), a crosshair plugin, and a tooltip footer with the AgenticOS share. The chart title sums `values` and `work`.

## Approach

Classification of one run record, applied in this order (`key = run.project_key or run.session_project`):

- [x] Rule 1 — AgenticOS: `key.lower() == "agentic-os"`, or no key and `skill == "_prompt"` (an unbound prompt runs in the runner's own checkout). Checked first, so agentic-os is never Work.
- [x] Rule 2 — Work: `run.get("confidential") is True`, or `key.lower()` is in `confidential_keys` (registry entries with `confidential: true`).
- [x] Rule 3 — Other: every remaining record (bound non-confidential project, project-less skill run).

Data contract:

- [x] `build_chart_data(runs, confidential_keys=frozenset())` returns exactly `labels`, `agentic`, `work`, `other`; each list has 30 entries, oldest first, local days.
- [x] Remove the old `values` and two-line `work` meaning; the template is the only consumer (`grep chart_data|chartData` confirms).
- [x] The index route builds `confidential_keys` (lowercase) from `_projects.load_registry(errors={})`; any exception yields an empty set and the page still renders.

Record writer (Codex R2):

- [x] `runner/modules/pty/__init__.py` `_record_pending_handoff` adds `"confidential": bool(confidential)` to its `extra` for a project tab, so a terminal skill handoff on a confidential project stays Work even after the registry changes. Historical handoffs: none exist in the live run log (0 records with `term_id`), so no backfill.

Template:

- [x] Three datasets: Work `#4caf50`, AgenticOS `#e8723a`, Other `#4fa3e0`.
- [x] Lines are not filled (three overlapping fills are unreadable).
- [x] Legend shown.
- [x] Tooltip mode `index`, intersect false (hover and click both select the day), lists the three counts.
- [x] Tooltip footer `Total: N · Work: P%`; empty on a zero day.
- [x] Title `Activity — last 30 days · T conversations · W work · A AgenticOS · O other`, sums computed in Jinja.
- [x] Crosshair plugin unchanged.

### Non-goals

- No time-based measure (duration); counts of conversations only, as in the previous ticket.
- No new API endpoint; the page renders chart data server-side as today.
- No change to `stats.total_runs` or the header chip.
- The legacy CLI log `outputs/run_log.jsonl` (written by `run_skill.py`, last write 2026-05-21) stays out of the chart, as it is out of every other dashboard view (Codex R1, rejected with this reason).

### Privacy

The chart exposes only per-day counts on the local dashboard; no project names or titles are rendered. No private project names go into tracked files (tests use made-up keys).

## Assumptions

- The user's day-job projects are exactly the confidential projects (stated in the request: "confidential project，也就是全部涉及本职工作").
- Every project-bound run since 2026-09-23 carries a `confidential` field (live run log: 118 agentic-os false, 50 other false, 34 other true, 2 unbound without the field).
- Old keys renamed in AGE-127 are no longer in the registry; their records still carry `confidential: true`, so rule 3's record flag covers them.

## Risks

- A project flagged confidential later counts all its earlier runs as Work (registry rule). Accepted: the user wants the current classification.
- A project un-flagged later keeps earlier runs as Work via their record flag. Accepted: rare, and the record was truly confidential at the time.

## Acceptance Criteria

- [x] The Activity chart shows three lines labelled Work, AgenticOS and Other.
- [x] A run on `agentic-os` (any case) or an unbound `_prompt` counts as AgenticOS only.
- [x] A run with `confidential: true` counts as Work only.
- [x] A run on a project whose registry entry is confidential counts as Work even when the record lacks the flag.
- [x] Any other run (non-confidential project, skill run with no project) counts as Other only.
- [x] Each day's three counts sum to that day's total run count.
- [x] Hover or click on a day shows the three counts plus a `Total · Work %` footer and the crosshair.
- [x] A registry read failure still renders the page.

## Verification

- [x] `python3 -m py_compile runner/*.py runner/modules/pty/__init__.py` passes.
- [x] Test (`tests/test_activity_chart.py`): `project_key="agentic-os"` lands in `agentic`.
- [x] Test: `project_key="Agentic-OS"` lands in `agentic`.
- [x] Test: unbound `_prompt` lands in `agentic`.
- [x] Test: `agentic-os` with `confidential: true` still lands in `agentic`.
- [x] Test: record `confidential: true` lands in `work`.
- [x] Test: registry-confidential key (different case) without the record flag lands in `work`.
- [x] Test: non-confidential project lands in `other`.
- [x] Test: project-less skill run lands in `other`.
- [x] Test: per-day `agentic + work + other` equals the runs that day.
- [x] Test: runs older than 30 days are dropped.
- [x] Test: unparseable timestamps are dropped.
- [x] Test (`tests/test_terminals.py`): a confidential-tab handoff writes `confidential: True` in `extra`.
- [x] Full suite `.venv/bin/python3 -m pytest -q` (main venv interpreter) passes.
- [x] Isolated runner 8599, seeded log + registry with one confidential project: `/` returns 200.
- [x] Isolated runner: chart has three datasets labelled Work, AgenticOS, Other.
- [x] Isolated runner: scripted hover on a seeded day returns the expected three counts.
- [x] Isolated runner: footer reads `Total: N · Work: P%` for that day.
- [x] Isolated runner: crosshair drawn (active elements present after hover).
- [x] Isolated runner with an unparseable `projects.yaml`: `/` still returns 200.

## Progress Checklist

- [x] Change `build_chart_data` to the three-way classification and new return keys.
- [x] Build `confidential_keys` in the index route with a safe fallback.
- [x] Update the template datasets, tooltip footer and title.
- [x] Persist `confidential` in `_record_pending_handoff`.
- [x] Add `tests/test_activity_chart.py`.
- [x] Extend `tests/test_terminals.py` for the handoff flag.
- [x] Run the verification checks above.
- [x] Fresh cross-provider code inspection of the change.
- [x] Record validation in `docs/context-maintenance.md`.
- [x] Commit on `agent/AGE-128`.

## Revision 2026-10-23 — one stacked chart

User feedback after completion: do not show three separate curves. Use one combined chart, AgenticOS at the bottom, Work in the middle, Other on top, where a band's thickness is that kind's conversations and the top line's height is the day's total. Implemented in the same three datasets with `fill` plus `y.stacked` (no server change), title now carries the Work share. Checked in headless Chromium against this chart code with sample data: Oct 20 = AgenticOS 2 / Work 4 / Other 2, `Total: 8 · Work: 50%`; legend toggles re-stack cleanly once the animation settles.

Second feedback: the green/blue boundary was hard to see. All three boundary lines are now black (`borderColor: '#000'`) while each band keeps its solid colour fill; the legend swatches still carry the colour. Re-checked in headless Chromium: the black separators are visible along both interior boundaries and the outer edge.
