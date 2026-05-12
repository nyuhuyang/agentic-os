# P6 — Structured Operational Memory + Architecture Index

**Status:** Active — remaining work documented below  
**Started:** 2026-05-11  
**Owner:** AgenticOS

---

## ✅ Completed (code written and verified)

- `app.py` defines `STATE_DIR`, `STATE_TASK_STATE`, `STATE_RUN_LOG`
- `app.py` calls `STATE_DIR.mkdir(parents=True, exist_ok=True)` at startup → `state/` created on first run
- `_load_task_state()` implemented; task state written to `state/task_state.json` on each run completion
- `render_roadmap_md.py` logic complete — can generate `ROADMAP.md`, `ACTIVE_TASKS.md`, `COMPLETED.md`
- `reduce_events.py` exists
- Markdown is no longer authoritative (state is JSON/JSONL)
- Agent retrieval discipline documented in `AGENTS.md`
- Graphify evaluated and integrated (`graphify-out/graph.json`, `graphify-out/GRAPH_REPORT.md`)

---

## ❌ Not Yet Done (system never initialized / never run)

> Note: previous ✅ marks on these items were premature — code supports them but files don't exist.

- [ ] `state/roadmap.json` — **missing**; `render_roadmap_md.py` exits immediately without it
- [ ] `state/events.jsonl` — missing (populated only after app runs)
- [ ] `docs/generated/` — directory never created; `ACTIVE_TASKS.md` and `COMPLETED.md` never generated
- [ ] `docs/exec-plans/ROADMAP.md` — never generated (script never successfully run)

**Fix:** Create `state/roadmap.json` with P6 + P7 content, then run `render_roadmap_md.py` once to bootstrap.

---

## 🐛 Bugs in `render_roadmap_md.py` — needs fix

These bugs block the script from running at all:

1. **`--no-completed` defined twice** (lines 128 and 145) → `argparse` crash on startup
2. **`--no-active-tasks` defined twice** (lines 144 and 146) → same crash
3. **Duplicate generation blocks**: `ACTIVE_TASKS.md` generated twice (lines 273–297, 325–349); `COMPLETED.md` generated twice (lines 299–323, 351–375) — harmless but dead code
4. **`args.no_completed` semantic collision**: same flag controls both "skip Completed section in ROADMAP.md" and "skip generating COMPLETED.md" — ambiguous, use `--no-completed-file` for the latter

**Assign to:** Aider / DeepSeek (Phase 1 of P7 unblocks this agent)

---

## 📋 Remaining Open Goals (moved to Backlog)

These are ongoing principles, not discrete tasks. Removed from P6 active checklist:

- **Reduce agent token waste from repo-wide exploration** → PLANS.md Backlog
- **Controlled autonomy / layered permissions** → PLANS.md Backlog (P8 prerequisite)

---

## Definition of Done for P6

P6 closes when:
1. `render_roadmap_md.py` bugs fixed (argparse crash + duplicate blocks)
2. `state/roadmap.json` initialized with current project state
3. `docs/generated/ACTIVE_TASKS.md` and `docs/generated/COMPLETED.md` exist and are current
4. `docs/exec-plans/ROADMAP.md` generated successfully
