# Review log — move the checkout to the workspace root

- Started 2026-10-15. User decision: move to `~/Documents/AI_Workspace/agentic-os`; the user asked for a Codex review and Claude's own verification. Host Claude Code: planner and builder. Plan reviewer and build inspector: fresh Codex CLI sessions (CLI default model), up to 20 rounds each.
- A first, unreviewed launch attempt never ran: the command typed into the dashboard terminal lacked a real newline. Nothing changed (old dir intact, runner up, plist unchanged). It was replaced by this reviewed plan and the committed script.

## Plan review round 1 (2026-10-15)
- Codex session 01a140dc-890b-7641-b0b4-6bced0396c50, cross-provider, 188 s. Result `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-prototypes-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/claudex/move/r1/claudex-9olrg6tf/result.json`.
- Verdict: **REVISE**, 9 findings.

```json
{
 "verdict": "REVISE",
 "summary": "The move breaks workspace-relative lookups and saved log references. Failure handling can also leave the runner stopped, report incomplete repairs as success, or move the checkout while a process still writes to it.",
 "findings": [
  {
   "id": "REL-001",
   "severity": "high",
   "path": "runner/app.py:51",
   "evidence": "WORKSPACE_ROOT = _PROTO.parent.parent resolves to ~/Documents after the proposed move. This redirects registry and knowledge-base lookups away from AI_Workspace, selects the local fallback registry, and lets registry_loader.py:114 write generated caches under ~/Documents/.claude. runner/dashboard.py:34 has the same assumption. HTTP 200 does not detect these regressions.",
   "fix": "Update workspace-root resolution for the new layout, preferably through a shared explicit resolver. Verify the canonical registry, generated-cache destinations, and knowledge-base lookups after relocation."
  },
  {
   "id": "REL-002",
   "severity": "high",
   "path": "scripts/relocate_checkout.sh:26",
   "evidence": "The empty running-jobs response does not establish that all writers are idle. A separately invoked run_skill.py holds its own lock and never enters the dashboard's _running_jobs. After relocation, its completion writes still target OLD/outputs (runner/run_skill.py:90–100), so completion logging can fail. Dashboard dispatch can also start between the check and bootout, and app.py:2825 removes a job before writing its completion record.",
   "fix": "Establish exclusive maintenance coordination across dispatch and CLI execution, then drain completion writers before stopping and moving. Refuse relocation while independent CLI locks or relevant processes remain active."
  },
  {
   "id": "REL-003",
   "severity": "high",
   "path": "scripts/relocate_checkout.sh:39",
   "evidence": "Every curl call lacks a connection and request timeout. If the new runner accepts a connection but never finishes GET /, wait_up blocks inside curl indefinitely; its iteration limit never advances and rollback never runs.",
   "fix": "Set explicit curl connection and total timeouts and enforce an overall readiness deadline. Apply bounded requests to preflight and rollback health checks too."
  },
  {
   "id": "REL-004",
   "severity": "high",
   "path": "scripts/relocate_checkout.sh:52",
   "evidence": "Rollback ignores bootout and wait_down failures and proceeds to mv while the NEW runner may still be alive. It also continues after a failed reverse move or repoint, restores the old plist, and treats any HTTP 200 as successful recovery. A surviving NEW process can keep writing to NEW or supply that 200. tests/test_relocate.py:81 sets SHIM_FAIL_UP for both destinations and never asserts that the restored runner starts.",
   "fix": "Check each recovery operation and stop advancing when a prerequisite fails. Confirm the NEW process has exited before moving, verify reverse repairs, and verify the restored OLD launchd job and process identity. Make the rollback test fail startup only at NEW and assert successful OLD recovery."
  },
  {
   "id": "REL-005",
   "severity": "high",
   "path": "scripts/relocate_checkout.sh:60",
   "evidence": "Neither mktemp nor the backup cp is checked. If copying fails, such as from insufficient temporary-volume space, execution still stops the runner and edits the plist. Rollback then copies an empty or partial backup over the user's plist.",
   "fix": "Require successful backup creation and a verified complete copy before bootout. Preserve that verified backup until recovery or post-move validation succeeds."
  },
  {
   "id": "REL-006",
   "severity": "medium",
   "path": "scripts/relocate_checkout.sh:46",
   "evidence": "A failed git worktree repair is masked by subsequent commands and successful plutil linting. The residual-path scan excludes Git metadata, and git worktree list neither validates each worktree nor has its exit status checked. A failed repair can therefore leave nested worktrees unusable while the script prints DONE.",
   "fix": "Propagate every repair failure and validate git status in every registered relocated worktree before declaring success. Add failure coverage for an unsuccessful repair."
  },
  {
   "id": "REL-007",
   "severity": "medium",
   "path": "runner/app.py:892",
   "evidence": "Existing progress records retain absolute stream_log paths under OLD. For example, outputs/logs/35f401f5-9b8f-4cbb-8dd9-e71695a789dd.json:3 points to an existing stream file that will move. _build_progress_payload reads that saved path directly, so historical progress loses its events after relocation. Stored log_path fields also remain stale in operational JSON/JSONL files.",
   "fix": "Resolve checkout-owned progress and log paths relative to the current checkout or derive them from run_id. Preserve append-only journals; use reader-side normalization or a reversible migration of mutable progress records."
  },
  {
   "id": "REL-008",
   "severity": "medium",
   "path": "scripts/relocate_checkout.sh:64",
   "evidence": "No interruption traps are installed. SIGTERM or SIGHUP after bootout or mv exits the script without restarting or restoring the runner, bypassing the plan's rollback promise.",
   "fix": "Track relocation phases and install interruption handlers before stopping the runner. Restore the appropriate location and configuration on catchable termination signals, and test interruption before and after the move."
  },
  {
   "id": "REL-009",
   "severity": "low",
   "path": ".git/config:8",
   "evidence": "core.hooksPath is an absolute OLD/.git/hooks path. Moving the directory and running worktree repair does not update this setting, leaving every worktree configured to use a nonexistent hook directory. Only sample hooks are currently present, so no active hook bypass was established.",
   "fix": "Repoint this local Git configuration transactionally and restore it on rollback. Include Git configuration in the residual operational-path audit."
  }
 ],
 "coverage": [
  "Verified the plan file matches the supplied SHA256 and inspected the committed relocation script and all relocation tests.",
  "Traced workspace and registry resolution through app.py, dashboard.py, run_skill.py, and core/registry_loader.py.",
  "Traced running-job registration, completion writes, shutdown, CLI locks, shared-state helpers, Linear dispatch, and PTY cleanup.",
  "Inspected actual operational path fields, progress records, projects.yaml, session readers, LaunchAgent plist, Git configuration, six registered nested worktrees, and venv text references and interpreter symlinks.",
  "Checked relevant SPEC requirements for registry display, append-only logging, crash integrity, and the in-memory running-jobs endpoint."
 ],
 "limitations": [
  "No files were edited, tests executed, services stopped, or work delegated.",
  "The workspace-level canonical registry contents could not be read because macOS denied access; its filesystem metadata was visible.",
  "Launchd recovery, relocated interpreter behavior, and macOS Documents permissions were assessed statically.",
  "External configuration checks were targeted; a complete audit of all files outside the checkout was not performed.",
  "The existing graph index was stale and truncated; findings were confirmed against implementation files."
 ]
}
```

### Host dispositions (round 1, all accepted)
- REL-001: `_workspace_root(checkout)` returns the nearest ancestor holding `obsidian/` (fallback: the parent). `app.py` uses it and `dashboard.py` applies the same rule. Test covers both checkout locations.
- REL-002: before bootout, and again after it, the script refuses while any process other than the runner (and itself) has OLD in its command line. Dashboard dispatch already stops through the runner's SIGTERM shutdown path, which waits for project jobs. Test added.
- REL-003: every curl has `--connect-timeout 2 -m 5`; readiness waits are bounded (`AOS_WAIT`, default 40 s).
- REL-004: each rollback step is checked. A surviving NEW runner or a NEW-using process stops the rollback with exit 2 and the checkout left at NEW. After moving back it repoints and verifies, restores the plist backup, and requires 200 from an `OLD/runner/app.py` process (exit 2 otherwise). The test now fails only NEW's startup and asserts OLD's runner is back.
- REL-005: the backup is created with `mktemp` and verified with `cp && cmp` before bootout; it is removed only after success.
- REL-006: `repoint` stops at the first failing step. `verified` checks `.venv`, the plist and the local git config for the old path, and runs `git status` in every registered worktree. Test with an unrepairable worktree added.
- REL-007: `_checkout_path` maps a saved `…/outputs/…` path that no longer exists onto the current `OUTPUTS_DIR`. Both progress readers use it; records stay as written. Test added.
- REL-008: phase-aware HUP/INT/TERM traps: a signal before the move restarts OLD, after the move it rolls back. Test sends TERM during the NEW bootstrap.
- REL-009: `core.hooksPath` naming OLD is rewritten inside `repoint` (and so restored on rollback), and the local git config is part of `verified`. Tests cover both directions.
- pytest 373 passed (relocate suite 5 tests, 7.7 s).

## Plan review round 2 (2026-10-15)
- Same Codex session (resumed), cross-provider, 117 s. Result `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-prototypes-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/claudex/move/r2/claudex-3xwc220e/result.json`.
- Verdict: **REVISE**, 4 findings.

```json
{
 "verdict": "REVISE",
 "summary": "Several prior defects are addressed, but writer detection, rollback completeness, verification errors, and signal handling still have concrete failure paths.",
 "findings": [
  {
   "id": "REL-002",
   "severity": "high",
   "path": "scripts/relocate_checkout.sh:35",
   "evidence": "The new process scan searches only command lines containing the absolute OLD path. The documented invocation, `.venv/bin/python3 runner/run_skill.py <skill>` (runner/run_skill.py:8), need not contain that path. An independently launched CLI run therefore remains invisible to both this scan and the dashboard's running-jobs endpoint. After the move, its completion writes still target OLD/outputs (run_skill.py:90–100), potentially losing the completion record. No shared maintenance lock prevents a new CLI invocation after the final scan either.",
   "fix": "Coordinate relocation with CLI execution through a shared maintenance lock held through completion writes. Detect existing users through held locks and cwd/open-file inspection rather than command-line substrings alone. Add coverage for the documented relative CLI invocation."
  },
  {
   "id": "REL-004",
   "severity": "high",
   "path": "scripts/relocate_checkout.sh:85",
   "evidence": "Reverse repointing and verification failures are still reduced to warnings. For example, if reverse shebang rewriting fails after a successful forward repair, rollback skips later worktree repairs, restarts OLD, and can print 'rolled back; runner up' with exit 1 while entrypoints or worktrees still reference NEW. The runner's interpreter can start independently of those broken entrypoints. This contradicts the revised plan's checked rollback and exit-2 contract.",
   "fix": "Track reverse repair and verification failures as incomplete recovery. Restore the verified plist and attempt service recovery where safe, but exit 2 and identify remaining damage unless all rollback invariants pass. Add a case where reverse repair fails while OLD can still answer HTTP."
  },
  {
   "id": "REL-006",
   "severity": "medium",
   "path": "scripts/relocate_checkout.sh:68",
   "evidence": "The new verification still treats inspection failures as success. A failed `git worktree list` at line 72 supplies no rows, leaving the final while loop successful without validating any worktrees. Similarly, grep read errors at lines 69–70 and a failed Git configuration read at line 71 can look like 'no old path found'. These paths can reach DONE despite incomplete verification.",
   "fix": "Check inspection commands separately before consuming their output. Distinguish grep's no-match status from execution/read failures, require successful Git enumeration, and fail verification on any unreadable required evidence. Add fault-injection coverage for these commands."
  },
  {
   "id": "REL-008",
   "severity": "high",
   "path": "scripts/relocate_checkout.sh:104",
   "evidence": "PHASE remains 'stopped' while mv executes and changes to 'moved' only afterward. If TERM arrives after the rename succeeds but before that assignment, the shell can run the pending trap with PHASE=stopped. The handler then tries to restart OLD, whose directory is already gone, instead of rolling back NEW. The added interruption test signals during bootstrap, so it misses this boundary.",
   "fix": "Introduce a moving phase that reconciles the actual directory locations, or defer signal recovery until the move result and phase transition are recorded. Add interruption coverage immediately after a successful rename and before the next shell statement."
  }
 ],
 "coverage": [
  "Verified the revised plan SHA256 and inspected commit c6569cc, the complete relocation script, relocation tests, and added path-resolution tests.",
  "Confirmed source fixes for REL-001, REL-003, REL-005, REL-007, and REL-009; forward worktree repair failures now propagate.",
  "Traced CLI locks and completion writes, dashboard completion bookkeeping and shutdown, project-process shutdown, shared-state locking, and both progress readers.",
  "Inspected the live LaunchAgent plist, local Git configuration, and registered nested worktree paths.",
  "Rechecked relevant specification requirements for in-memory running-job visibility, append-only journals, and state integrity."
 ],
 "limitations": [
  "No files were edited, tests run, services changed, or work delegated.",
  "The host-reported 373 passing tests were not independently verified.",
  "Signal timing, process detection, and launchd recovery were assessed statically.",
  "This follow-up focused on the revision and related callers and writers; it did not repeat an exhaustive external-path audit."
 ]
}
```

### Host dispositions (round 2, all accepted)
- REL-002: a shared maintenance lock. `run_skill.py` holds `outputs/locks/maintenance.lock` with LOCK_SH for its whole run, through its record write, and refuses to start while it is held exclusively. The script takes it exclusively through a `/usr/bin/python3` helper that holds it until the script exits; the helper also exits when its parent dies. A skill already running, whatever its argv (relative CLI invocation), makes the script abort before anything changes; a skill started during the move is refused. Tests: a lock holder whose argv lacks OLD blocks the move, and `_maintenance_shared()` returns None while the lock is held exclusively.
- REL-004: failures in the reverse repoint or its verification are recorded. The runner is still restarted on OLD, but the script exits 2 ("recovery is incomplete: …"). Test: reverse sed fails while OLD answers → exit 2, runner up on OLD.
- REL-006: `verified` tells grep's no-match (1) apart from errors (≥2), and requires `git config --list` and `git worktree list` to succeed. Each worktree must be its own toplevel (a subdirectory that falls back to the main repo no longer passes) and `git status` must work. Tests: a failed worktree listing and a failed repair each roll back. An already broken worktree is refused before anything changes.
- REL-008: a new `moving` phase. A signal during `mv` checks where the checkout actually is, then rolls back or restarts. Test: TERM delivered right after the rename, before the next statement, rolls back.
- pytest 379 passed (relocate suite 11 tests).
