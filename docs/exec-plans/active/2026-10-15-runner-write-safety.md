---
status: in-progress
created: 2026-10-15
---

# Runner write-safety hardening (follow-up)

## Goal
Close the remaining concurrent-write and shutdown gaps the relocation inspections found in the runner itself (not in the move). Origin: `docs/exec-plans/completed/2026-10-15-relocate-to-workspace-root.md`. The user decided on 2026-10-15 to stop that plan's review after inspection 7 and carry the rest here. Not started; needs its own plan review before building.

## Acceptance criteria
- [ ] Execution-registry caches (`app.py` `_registry_exec_env`) are published atomically under a lock, and a subprocess reading a published cache never sees it truncated by a concurrent dispatch (BUILD-016)
- [ ] An agent subprocess that times out is ended with its whole process group, its pipes are closed and its stream readers stop within a bounded time, so a background descendant that keeps stdout open cannot hold an in-flight slot forever (BUILD-014 remainder)
- [ ] The two fixes made after the last relocation inspection get an independent Codex review: `_start_counted` constructor failure (BUILD-009) and the `rename_dir` destination guard (BUILD-017)

## Progress Checklist
- [ ] Write the detailed approach and get a Codex plan review
- [ ] Test: a cache republished while a reader holds it never yields partial JSON
- [ ] Test: a timed-out agent whose descendant keeps stdout open releases its reader slot
- [ ] Implement and prove with `.venv/bin/python -m pytest tests/`
- [ ] Fresh cross-provider (Codex) build inspection returns no unresolved material findings
