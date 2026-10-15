---
status: in-progress
created: 2026-10-15
---

# Move the checkout to the workspace root

## Goal
Move this repository from `~/Documents/AI_Workspace/prototypes/agentic-os` to `~/Documents/AI_Workspace/agentic-os` (user decision 2026-10-15: no longer a prototype; it is the workspace's runtime, a peer of `obsidian/`, not a `tools/` utility). The runner keeps working without a manual fix-up on the AgenticOS side; everything outside the repo that mentions the old path is listed for the user.

## Acceptance criteria
- [x] The old path no longer exists; the new path holds the full checkout (tracked files, `.venv`, `state/`, `outputs/`, `projects.yaml`, `.env`, `.claude/`)
- [x] launchd runs `com.agenticos.runner` from the new path (`launchctl print` program arguments name the new path) and the dashboard answers 200
- [x] `.venv` works from the new path: no file under `.venv` mentions the old path; `.venv/bin/python -m pytest tests/` passes from the new path
- [x] Every nested worktree under `.claude/worktrees/` resolves (`git worktree list` shows new paths; `git status` works in each)
- [x] The dashboard lists the registered projects with their sessions after the move
- [x] The runner resolves the workspace root to `~/Documents/AI_Workspace` from the new path (knowledge base and registry lookups unchanged; nothing written under `~/Documents/.claude`) — `WORKSPACE_ROOT` is the nearest ancestor holding `obsidian/` (REL-001)
- [x] Saved progress records that name the old checkout's `outputs/` still show their stream events (reader follows the moved checkout, REL-007) — live check: `/api/runs/6b914c2d…/progress` (its record names the old `…/prototypes/agentic-os/outputs/logs/…_stream.jsonl`) returns its events from the moved file
- [x] `.git/config` `core.hooksPath` points into the new checkout (REL-009)
- [x] If the runner does not come back on the new path, the script restores the old path, the venv, the worktrees and the plist, and restarts the runner there
- [x] The workspace map names `agentic-os/` at the root (repo `CLAUDE.md`, and the workspace-level `CLAUDE.md` if it is a separate file)
- [x] The user has the exact commands for what lives outside the repo and stays read-only to the agent: two hooks in `~/.claude/settings.json`, the trust entry in `~/.codex/config.toml`, and copying the Claude project folder (auto memory + session history) to the new path's slug

## Approach
`scripts/relocate_checkout.sh OLD NEW` (committed, reusable):
1. Refuse unless OLD is an AgenticOS checkout, NEW does not exist and its parent does, NEW is not inside OLD, the plist exists, the runner answers, `/api/runs?state=running` is empty, and no process other than the runner has OLD in its command line (CLI `run_skill.py`, scripts; REL-002). Every curl call has a 2 s connect / 5 s total timeout and readiness waits are bounded (REL-003).
2. Refuse if any `.claude/worktrees/*` is already broken (its own toplevel + `git status`). Take the maintenance lock exclusively through a helper that lives until the script ends (excluded from the busy scan by PID): `run_skill.py` takes `outputs/locks/maintenance.lock` shared first thing (before the registry and any prompt), refuses if held exclusively or if its own checkout has moved: it creates `outputs/` and `outputs/locks/` one level at a time (never `parents=True`, so a moved checkout makes that fail rather than recreating it) and, after locking, checks that the lock file and the checkout directory are still the same inodes, so no CLI skill is mid-run and none can start during the move, whatever its command line (REL-002 round 2).
2a. Back up the plist to a `mktemp` file and verify it with `cmp`; abort before touching anything if that fails (REL-005).
3. Install HUP/INT/TERM traps by phase: before the move a signal restarts the runner on OLD; during `mv` (phase `moving`) the handler looks where the checkout actually is and rolls back or restarts accordingly; after it, a full rollback (REL-008).
4. `launchctl bootout`; wait until no `OLD/runner/app.py` remains; re-check that no other process uses OLD; `mv OLD NEW` (on any failure here: restart on OLD, nothing changed).
5. Repoint, each step checked: `.venv/bin` text files and `.venv/pyvenv.cfg`; `core.hooksPath` when it names OLD (REL-009); `git worktree repair` per `.claude/worktrees/*`; the plist (`plutil -lint`).
6. Verify: no OLD in `.venv`, the plist or the local git config; every registered worktree is outside OLD, is its own toplevel and `git status` works in it. An inspection that cannot run (grep read error, git failure) fails the check (REL-006). Then `launchctl bootstrap` and wait for HTTP 200 from a `NEW/runner/app.py` process.
7. Rollback on any failure after the move (REL-004): stop (exit 2) if OLD was recreated meanwhile; bootout and confirm no NEW runner or NEW-using process remains, else stop and report (exit 2, checkout left at NEW); `mv NEW OLD`; repoint back and verify; restore the verified plist backup; bootstrap; require HTTP 200 from an `OLD/runner/app.py` process, else exit 2. If the reverse repoint or its verification failed, the runner is still restarted but the script exits 2 naming the damage.
8. Report the files outside the checkout that still name OLD.

Runner code: `WORKSPACE_ROOT` = nearest ancestor holding `obsidian/` (fallback: the checkout's parent), in `app.py` and `dashboard.py` (REL-001). Progress readers map a saved `…/outputs/…` path that no longer exists onto this checkout's `outputs/` (REL-007); the records themselves are left as written.

The Claude Code shell here cannot read the workspace root (macOS privacy), so the script is started from a dashboard terminal (runner context, which has Documents access), detached with `start_new_session=True` because its first act stops the runner. Its output goes to a log in the session scratchpad.

## Non-goals
- Editing `~/.claude` or `~/.codex` (read-only to the agent; the user runs the given commands)
- Rewriting historical path mentions in archived plans (2 files, 4 mentions)
- Moving `~/.agentic-os/worktrees` (independent of the checkout path)

## Risks
- macOS may ask again for Documents access because the runner's interpreter path changes; if the runner logs `Operation not permitted`, grant access in System Settings → Privacy & Security
- This Claude Code session's working directory disappears with the move; verification from the new path runs through the dashboard terminal, and the user restarts Claude Code in the new folder afterwards
- An open browser tab keeps the old request token; reload it

## Verification
- `.venv/bin/python -m pytest tests/test_relocate.py` (shimmed launchctl/curl/pgrep/plutil: success, refusals, rollback) before the real run
- After the run, from the new path via the dashboard terminal: `launchctl print gui/$UID/com.agenticos.runner | grep -A3 arguments`, `grep -rlI <old> .venv | wc -l` → 0, `git worktree list`, `git -C <each worktree> status`, full `pytest tests/`, `curl /api/projects` count

## Progress Checklist
- [x] Test: relocate succeeds (moved, venv + plist + nested worktree repointed, runner up from NEW)
- [x] Test: refuses running jobs, an existing target, a non-checkout source, with nothing changed
- [x] Test: rolls back fully when only the NEW checkout fails to start, and the restored runner is OLD's
- [x] Test: an interrupt after the move rolls back
- [x] Test: an unrepairable worktree rolls back
- [x] Test: another process using OLD is refused before anything changes
- [x] Test: a skill holding the maintenance lock (no OLD in its argv) blocks the move; `run_skill` refuses while maintenance holds it
- [x] Test: an incomplete reverse repair exits 2 with the runner restarted on OLD
- [x] Test: a failed worktree listing and a failed worktree repair each roll back
- [x] Test: an interrupt right after the rename rolls back
- [x] Test: an already broken worktree is refused before anything changes
- [x] Test: with the real process table, the script's own lock helper is not counted as busy; a real process naming OLD is (REL-010)
- [x] Test: `run_skill` holds the maintenance lock before its confirmation prompt, and a stale `run_skill` whose checkout moved never recreates it (REL-002 round 3)
- [x] Test: rollback stops (exit 2) when OLD was recreated meanwhile, never nesting the checkout
- [x] Test: a checkout renamed between run_skill's identity read and its lock-folder creation is not recreated (REL-002 round 4)
- [x] Test: `core.hooksPath` repointed on success and restored on rollback
- [x] Test: workspace root found from both checkout locations; saved stream paths follow the moved checkout
- [x] Codex plan review of this plan and the script returns APPROVED — round 5, 2026-10-15 (9 → 4 → 2 → 1 → 0)
- [x] Run the script against the real checkout from a dashboard terminal; log captured — 2026-10-15: started detached from a dashboard terminal (runner context) after a 20 s delay; `EXIT=0`, "runner up from …/AI_Workspace/agentic-os"; log in the session scratchpad (`move.log`)
- [x] Verify each acceptance criterion from the new path — `verify.log` (runner context, new path): old path gone; launchd arguments name the new path; 0 `.venv` files name the old path; `core.hooksPath` new; 6 worktrees listed under the new path and `git status` ok in each; `WORKSPACE_ROOT` = `~/Documents/AI_Workspace`, knowledge base found; no `~/Documents/.claude`; `/api/projects` lists the 3 projects with sessions (4, 5, 50); pytest 382 passed from the new path
- [x] Update the workspace map (repo `CLAUDE.md`, and the workspace-level one if separate) — repo `CLAUDE.md` gains an `agentic-os/` row; there is no separate workspace-level `CLAUDE.md` (`~/Documents/AI_Workspace` has none)
- [x] Give the user the commands for `~/.claude/settings.json`, `~/.codex/config.toml` and the Claude project folder — given in the session reply (2026-10-15): one `sed` per file and a non-clobbering copy of the Claude project folder
- [x] Fix: refuse a destination on another filesystem; refuse paths outside `A-Za-z0-9_./-`; literal matching (BUILD-003, BUILD-002)
- [x] Test: pattern characters and another filesystem refused up front; a dotted path replaced literally
- [x] Fix: maintenance gate — every run counted in flight until its record is written; new runs refused while the gate is closed; the script closes it and requires zero in flight before stopping the runner (BUILD-001, first deferred, then fixed after inspection 2)
- [x] Fix: escaped pgrep patterns; device check on physical paths (BUILD-002, BUILD-003 remainders)
- [x] Test: gate counts and refuses (/run, project dispatch, Linear dispatch); script refuses and reopens the gate with runs in flight; look-alike runner ignored on rollback; dotted OLD replaced literally; symlinked parent on another filesystem refused
- [x] Fix: `app.py` registers itself as module `app`, so the served instance and `from app import …` are one (BUILD-001: Linear jobs had lived in a second copy)
- [x] Fix: route-level reservations for retry, baseline and Linear dispatch (409 before any state); continuation slots for final tracker pushes; script takes the lock, then traps, then the gate, reopening it on any pre-stop exit (BUILD-004..007)
- [x] Test: script entrypoint shares one module; retry/baseline refused before state; push counted until persisted; lost gate answer, early signal, overlapping relocations
- [ ] Fresh cross-provider (Codex) build inspection of the script and tests returns no unresolved material findings — inspection 1 REVISE (2 fixed, 1 deferred); inspection 2 REVISE (3 fixed, deferral reversed); inspection 3 REVISE (5 fixed); inspection 4 pending
