---
status: in-progress
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

- [ ] Rule 1 — AgenticOS: `key.lower() == "agentic-os"`, or no key and `skill == "_prompt"` (an unbound prompt runs in the runner's own checkout). Checked first, so agentic-os is never Work.
- [ ] Rule 2 — Work: `run.get("confidential") is True`, or `key.lower()` is in `confidential_keys` (registry entries with `confidential: true`).
- [ ] Rule 3 — Other: every remaining record (bound non-confidential project, project-less skill run).

Data contract:

- [ ] `build_chart_data(runs, confidential_keys=frozenset())` returns exactly `labels`, `agentic`, `work`, `other`; each list has 30 entries, oldest first, local days.
- [ ] Remove the old `values` and two-line `work` meaning; the template is the only consumer (`grep chart_data|chartData` confirms).
- [ ] The index route builds `confidential_keys` (lowercase) from `_projects.load_registry(errors={})`; any exception yields an empty set and the page still renders.

Record writer (Codex R2):

- [ ] `runner/modules/pty/__init__.py` `_record_pending_handoff` adds `"confidential": bool(confidential)` to its `extra` for a project tab, so a terminal skill handoff on a confidential project stays Work even after the registry changes. Historical handoffs: none exist in the live run log (0 records with `term_id`), so no backfill.

Template:

- [ ] Three datasets: Work `#4caf50`, AgenticOS `#e8723a`, Other `#4fa3e0`.
- [ ] Lines are not filled (three overlapping fills are unreadable).
- [ ] Legend shown.
- [ ] Tooltip mode `index`, intersect false (hover and click both select the day), lists the three counts.
- [ ] Tooltip footer `Total: N · Work: P%`; empty on a zero day.
- [ ] Title `Activity — last 30 days · T conversations · W work · A AgenticOS · O other`, sums computed in Jinja.
- [ ] Crosshair plugin unchanged.

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

- [ ] The Activity chart shows three lines labelled Work, AgenticOS and Other.
- [ ] A run on `agentic-os` (any case) or an unbound `_prompt` counts as AgenticOS only.
- [ ] A run with `confidential: true` counts as Work only.
- [ ] A run on a project whose registry entry is confidential counts as Work even when the record lacks the flag.
- [ ] Any other run (non-confidential project, skill run with no project) counts as Other only.
- [ ] Each day's three counts sum to that day's total run count.
- [ ] Hover or click on a day shows the three counts plus a `Total · Work %` footer and the crosshair.
- [ ] A registry read failure still renders the page.

## Verification

- [ ] `python3 -m py_compile runner/*.py runner/modules/pty/__init__.py` passes.
- [ ] Test (`tests/test_activity_chart.py`): `project_key="agentic-os"` lands in `agentic`.
- [ ] Test: `project_key="Agentic-OS"` lands in `agentic`.
- [ ] Test: unbound `_prompt` lands in `agentic`.
- [ ] Test: `agentic-os` with `confidential: true` still lands in `agentic`.
- [ ] Test: record `confidential: true` lands in `work`.
- [ ] Test: registry-confidential key (different case) without the record flag lands in `work`.
- [ ] Test: non-confidential project lands in `other`.
- [ ] Test: project-less skill run lands in `other`.
- [ ] Test: per-day `agentic + work + other` equals the runs that day.
- [ ] Test: runs older than 30 days are dropped.
- [ ] Test: unparseable timestamps are dropped.
- [ ] Test (`tests/test_terminals.py`): a confidential-tab handoff writes `confidential: True` in `extra`.
- [ ] Full suite `.venv/bin/python3 -m pytest -q` (main venv interpreter) passes.
- [ ] Isolated runner 8599, seeded log + registry with one confidential project: `/` returns 200.
- [ ] Isolated runner: chart has three datasets labelled Work, AgenticOS, Other.
- [ ] Isolated runner: scripted hover on a seeded day returns the expected three counts.
- [ ] Isolated runner: footer reads `Total: N · Work: P%` for that day.
- [ ] Isolated runner: crosshair drawn (active elements present after hover).
- [ ] Isolated runner with an unparseable `projects.yaml`: `/` still returns 200.

## Progress Checklist

- [ ] Change `build_chart_data` to the three-way classification and new return keys.
- [ ] Build `confidential_keys` in the index route with a safe fallback.
- [ ] Update the template datasets, tooltip footer and title.
- [ ] Persist `confidential` in `_record_pending_handoff`.
- [ ] Add `tests/test_activity_chart.py`.
- [ ] Extend `tests/test_terminals.py` for the handoff flag.
- [ ] Run the verification checks above.
- [ ] Fresh cross-provider code inspection of the change.
- [ ] Record validation in `docs/context-maintenance.md`.
- [ ] Commit on `agent/AGE-128`.
