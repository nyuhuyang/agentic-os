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

## Plan review round 3 (2026-10-15)
- Same Codex session (resumed), cross-provider, 84 s. Result `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-prototypes-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/claudex/move/r3/claudex-m36qba__/result.json`.
- Verdict: **REVISE**, 2 findings.

```json
{
 "verdict": "REVISE",
 "summary": "The prior rollback, verification, and move-phase fixes are present. The new maintenance implementation introduces a deterministic refusal and still permits stale CLI processes to recreate OLD.",
 "findings": [
  {
   "id": "REL-010",
   "severity": "high",
   "path": "scripts/relocate_checkout.sh:150",
   "evidence": "The maintenance helper started at line 61 has OLD/outputs/locks/maintenance.lock in its command line. The post-bootout others(OLD) scan therefore finds this helper: its command matches neither exclusion at line 35. A real invocation stops the runner, detects its own helper as busy, restarts OLD, and aborts before moving. The pgrep shim suppresses real process discovery, hiding this from the success test.",
   "fix": "Exclude the maintenance helper by its recorded PID, alongside precisely identified script and runner processes. Add coverage that supplies the helper's actual command line to the process scan."
  },
  {
   "id": "REL-002",
   "severity": "high",
   "path": "runner/run_skill.py:96",
   "evidence": "The shared lock is acquired after registry loading and interactive confirmation (lines 180–230). A relative CLI invocation can wait at the confirmation prompt without holding it. Once relocation proceeds after REL-010 is fixed, answering that prompt causes mkdir(parents=True) to recreate OLD/outputs/locks and open a new maintenance.lock inode, bypassing the exclusive lock now inside NEW. The CLI then writes records under OLD. If relocation subsequently rolls back, mv NEW OLD can nest the checkout inside the recreated directory instead of restoring its original location.",
   "fix": "Acquire maintenance protection before confirmation and other checkout-dependent work. Reject a stale or missing checkout before creating lock directories, and ensure lock identity remains stable across relocation. Add a case with a relative CLI paused at confirmation, resumed after the rename."
  }
 ],
 "coverage": [
  "Verified the supplied plan SHA256 and inspected commit ab3475d, the complete relocation script, run_skill.py changes, and all relocation tests.",
  "Confirmed the revised reverse-repair error handling, checked verification commands, worktree-root validation, and moving-phase signal recovery.",
  "Traced maintenance helper lifetime, process filtering, CLI confirmation and locking order, completion writes, dashboard shutdown, and shared-state helpers.",
  "Rechecked relevant specification requirements for running-job visibility and state integrity."
 ],
 "limitations": [
  "No files were edited, tests run, services changed, or work delegated.",
  "The host-reported 379 passing tests were not independently verified.",
  "Process discovery and relocation timing were assessed statically; current tests replace process discovery with a shim.",
  "Earlier resolved path-resolution fixes were not subjected to another exhaustive external-path audit."
 ]
}
```

### Host dispositions (round 3, both accepted)
- REL-010: `others()` now takes PIDs from `pgrep -f`, skips the lock helper (`$LOCKER`), the script (`$$`) and the runner/script by `ps -o command=`, and reports the remaining PIDs. Matching by PID also fixes multi-line argv: the real pgrep printed the helper's multi-line `-c` code as extra lines. The shim now delegates every non-runner pattern to the real `pgrep`. The success test therefore runs against the real process table with the helper alive. The refusal test uses a real process whose argv names OLD.
- REL-002: `cmd_run` takes the maintenance lock before the registry load and any prompt (the body moved to `_cmd_run`). `_maintenance_shared` refuses when this process's own file no longer exists, so a stale CLI never recreates OLD, and checks that the locked file is still the one at its path. Rollback stops with exit 2 when OLD was recreated, so the checkout is never nested. Tests: the lock is held during the confirmation prompt; a moved checkout is not recreated; the rollback guard works.
- pytest 381 passed (relocate suite 13 tests).

## Plan review round 4 (2026-10-15)
- Same Codex session (resumed), cross-provider, 83 s. Result `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-prototypes-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/claudex/move/r4/claudex-zqu0wkj4/result.json`.
- Verdict: **REVISE**, 1 finding.

```json
{
 "verdict": "REVISE",
 "summary": "The helper-PID exclusion and early lock acquisition address the previous scenarios. One race remains in the stale-checkout guard.",
 "findings": [
  {
   "id": "REL-002",
   "severity": "medium",
   "path": "runner/run_skill.py:101",
   "evidence": "The existence check and recursive mkdir are not atomic. A relative CLI can pause after _SELF.exists() succeeds at line 99; relocation then acquires the exclusive lock and renames OLD. When the CLI resumes, mkdir(parents=True) recreates OLD/outputs/locks. It opens a fresh maintenance.lock, whose inode matches its own pathname, so the check at line 106 passes despite the original lock remaining held inside NEW. This violates the old-path-absence criterion and can force rollback to stop at the recreated-OLD guard. The added test covers a checkout already missing before the existence check, not this interleaving.",
   "fix": "Prevent lock initialization from recreating checkout ancestors: create runtime directories only beneath an existing checkout, handle disappearance as refusal, and validate checkout identity after acquiring the shared lock. Consider directory-descriptor-based operations or a stable external lock. Add coverage that renames the checkout between the existence check and directory creation."
  }
 ],
 "coverage": [
  "Verified the supplied plan SHA256 and inspected commit 9c43fa4, the complete relocation script, revised CLI locking, and all relocation tests.",
  "Confirmed helper exclusion by PID, maintenance protection before confirmation and registry loading, and the rollback destination guard.",
  "Rechecked CLI completion writes, dashboard completion bookkeeping and shutdown, shared-state helpers, and relevant specification requirements.",
  "Previously resolved rollback, verification, signal-handling, and path-resolution findings were not reopened."
 ],
 "limitations": [
  "No files were edited, tests run, services changed, or work delegated.",
  "The host-reported 381 passing tests were not independently verified.",
  "The remaining race was established by source-level interleaving analysis; it was not reproduced.",
  "This follow-up did not repeat the external-path audit."
 ]
}
```

### Host disposition (round 4, accepted)
- REL-002 (remaining race): `_maintenance_shared` reads the checkout directory's inode first. It then creates `outputs/` and `outputs/locks/` one level at a time, with no `parents=True`, so a checkout renamed in between makes `mkdir` fail and run_skill refuses without recreating anything. After `flock` it also requires that the lock file and the checkout directory still have the same inodes. Test: the checkout is renamed inside the first `mkdir` call; `_maintenance_shared()` returns None, the old path stays absent, and the moved checkout is intact. pytest 382 passed (relocate suite 14).

## Plan review round 5 (2026-10-15)
- Same Codex session (resumed), cross-provider, 32 s. Result `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-prototypes-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/claudex/move/r5/claudex-v33bh92u/result.json`.
- Verdict: **APPROVED**, 0 findings; bound to plan sha256 `adb570909a6dc7aee46a2b5fe8dae97c00ec2d7c401ababcb45b17b34da41d80`. Plan review: 5 rounds (9 → 4 → 2 → 1 → 0).
- After approval only checkbox state changed (word diff: 18 `[ ]`→`[x]` plus one evidence note); the strict sha check therefore reports a change. Plan text approved in round 5 is unchanged.
- Run 2026-10-15: relocation EXIT=0 from a dashboard terminal (runner context); verify.log all green (see plan). Workspace map updated in the repo CLAUDE.md (no workspace-level CLAUDE.md exists). Outside-repo edits handed to the user.

## Build inspection 1 (2026-10-15)
- Fresh Codex session 01a14100-1bfa-7230-8207-a270bcc8fd6e, base 2395d08, cross-provider, 193 s. Result `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-prototypes-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/claudex/move/i1/claudex-5macompx/result.json`.
- Verdict: **REVISE**, 3 findings.

```json
{
 "verdict": "REVISE",
 "summary": "Dashboard writers remain outside maintenance coordination. The reusable script also has unresolved path-handling and cross-filesystem recovery defects.",
 "findings": [
  {
   "id": "BUILD-001",
   "severity": "high",
   "path": "scripts/relocate_checkout.sh:33",
   "evidence": "The empty running-jobs check and exclusive CLI lock do not drain dashboard completion writers. For example, runner/modules/linear/__init__.py:677 removes a job before calling _write_run_log at line 680. Its daemon worker can pause there, allowing relocation to observe [], acquire maintenance, and bootout the runner. runner/app.py:2572 waits only for project jobs, so this non-project completion can be discarded without its record. POST /run has the same ordering at app.py:2841. New AI-only dispatches can also start between preflight and bootout without taking maintenance protection.",
   "fix": "Apply shared maintenance protection to every dispatch path, from admission through final record and state writes. Acquire exclusive protection before shutdown and refuse relocation while any such worker remains active. Cover a paused non-project completion and dispatch after preflight."
  },
  {
   "id": "BUILD-002",
   "severity": "medium",
   "path": "scripts/relocate_checkout.sh:100",
   "evidence": "OLD and NEW are interpolated directly into sed expressions, while grep and pgrep interpret paths as regular expressions. A valid destination such as /tmp/agentic-os&archive expands '&' to OLD during sed replacement, corrupting shebangs and pyvenv.cfg. Verification triggers rollback, but reverse replacement searches for the intended NEW string, which the corrupted files do not contain, leaving incomplete recovery. The tests use paths without these characters.",
   "fix": "Use literal byte/string replacement for venv text, structured plist editing, and literal or escaped process/path matching. Add success and rollback cases with regex metacharacters, '&', and the substitution delimiter in paths."
  },
  {
   "id": "BUILD-003",
   "severity": "medium",
   "path": "scripts/relocate_checkout.sh:165",
   "evidence": "Preflight accepts a destination parent on another filesystem, but recovery assumes mv is an atomic rename. Cross-filesystem mv copies and deletes: an interrupted or failed copy can leave both OLD and a partial NEW. The failure branch merely restarts OLD and reports 'nothing changed'; the moving-phase handler likewise restarts OLD whenever both paths exist. Interruption during source removal can leave OLD incomplete. Copying maintenance.lock also creates a different inode, defeating the helper's protection at NEW.",
   "fix": "Require OLD and the destination parent to share a filesystem before stopping the runner, then use an atomic rename. Otherwise implement an explicit staged-copy transaction with stable external maintenance locking and recovery for partial source/destination states."
  }
 ],
 "coverage": [
  "Verified all nine manifest file hashes, including the supplied plan SHA256.",
  "Inspected every changed file, including relocation tests, path-resolution changes, maintenance locking, workspace map, and review history.",
  "Traced dashboard and Linear dispatch, completion bookkeeping, shared-state writers, stall detection, project shutdown, and PTY cleanup beyond the manifest.",
  "Traced registry resolution and both saved-stream readers.",
  "Inspected the current LaunchAgent plist, local Git configuration, and registered worktree paths.",
  "Checked relevant specification requirements for dispatch records, shared state, running-job visibility, and CLI behavior."
 ],
 "limitations": [
  "No files were edited, tests executed, services changed, or work delegated.",
  "Failure scenarios were established statically and were not reproduced.",
  "The reported successful relocation and 382 passing tests were not independently verified.",
  "External configuration and historical runtime records were not exhaustively audited."
 ]
}
```

### Host dispositions (build inspection 1)
- BUILD-003 accepted: the script refuses a destination whose parent is on another filesystem (`stat -f %d`) before anything changes, so `mv` is always an atomic rename. Test uses a devfs destination.
- BUILD-002 accepted (narrowed): OLD and NEW may contain only `A-Za-z0-9_./-`; anything else is refused up front (tests: `&`, `|`, space). Detection uses `grep -F`, and the one remaining pattern character, `.`, is escaped in the sed patterns. Test: a dotted destination leaves a look-alike path (`agenticXos`) untouched.
- BUILD-001 rejected for this plan, recorded as a follow-up: a non-project dashboard job removes itself from `_running_jobs` before writing its record, and shutdown waits only for project jobs. Any runner restart (`launchctl kickstart -k`, a crash, a reboot) can therefore lose such a record; relocation only adds one more restart. A proper fix changes runner shutdown (drain every job through its record write and refuse new admissions on SIGTERM), which is runner work outside this move. The relocation already refuses while any job is listed as running. Follow-up for the user: "runner shutdown drains all jobs".
- pytest: relocate suite 19, full suite below.

## Build inspection 2 (2026-10-15)
- Fresh Codex session 01a14106-9dec-7381-a810-12625caa176b, base e10c1cd, cross-provider, 111 s. Result `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-prototypes-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/claudex/move/i2/claudex-p1etqcxn/result.json`.
- Verdict: **REVISE**, 3 findings (BUILD-001 rejection not accepted by the inspector; host reversed it).

```json
{
 "verdict": "REVISE",
 "summary": "The sed fixes address the reported substitution corruption. BUILD-002 and BUILD-003 remain partially unresolved, and the BUILD-001 deferral leaves a concrete data-loss path during relocation.",
 "findings": [
  {
   "id": "BUILD-001",
   "severity": "high",
   "path": "scripts/relocate_checkout.sh:36",
   "evidence": "The running-jobs snapshot and CLI maintenance lock still do not establish dashboard quiescence. A Linear worker can pause after removing its job at runner/modules/linear/__init__.py:677 but before _write_run_log at line 680. Relocation then observes [], acquires maintenance and stops the runner; runner/app.py:2572 drains only project jobs. The completion record and subsequent tracker update can be lost. POST /run similarly removes jobs before logging at app.py:2841 and 2917. Although the shutdown weakness predates relocation, this script deliberately invokes that unsafe shutdown, so documenting it as a follow-up does not resolve the integration defect or satisfy SPEC FR-14.",
   "fix": "Coordinate dashboard and Linear admission and completion with maintenance protection, held through final record/state writes. Acquire exclusive protection before stopping the runner and prevent further admissions. Cover a worker paused before its completion write and a dispatch attempted after preflight."
  },
  {
   "id": "BUILD-002",
   "severity": "medium",
   "path": "scripts/relocate_checkout.sh:87",
   "evidence": "Process matching remains regex-based: runner_from and others pass unescaped paths to pgrep. For NEW=/tmp/agentic.os, an unrelated runner at /tmp/agenticXos/runner/app.py on another port matches. If the NEW runner fails startup, rollback's wait_down(NEW) mistakes that unrelated process for the relocated runner, exits 2 and leaves the service unrecovered at NEW. The allowed-character restriction explicitly permits dots. The pgrep test shim uses literal equality for runner paths, hiding this behavior; the dotted-path test also leaves OLD undotted, so it does not exercise dotted search-pattern replacement.",
   "fix": "Escape the complete pgrep pattern, including the dot in app.py, or compare process arguments literally. Add rollback coverage with a dotted destination and an unrelated look-alike runner, plus replacement coverage with a dotted OLD."
  },
  {
   "id": "BUILD-003",
   "severity": "medium",
   "path": "scripts/relocate_checkout.sh:32",
   "evidence": "The filesystem check can be bypassed by a symlinked destination parent. macOS stat defaults to lstat, as documented in /usr/share/man/man1/stat.1:79; following the target requires -L. If /tmp/external is a symlink on OLD's filesystem pointing to another mounted filesystem, NEW=/tmp/external/agentic-os passes this comparison. mv traverses the parent symlink and performs a cross-filesystem copy/delete. An interruption can consequently leave partial trees, while the moving-phase handler assumes an atomic rename. The added devfs test does not cover this case.",
   "fix": "Resolve and validate physical source and destination-parent paths before comparing devices, or reject symlinked locations. Use a rename operation that fails on EXDEV instead of falling back to copying. Add coverage for a destination-parent symlink targeting another filesystem."
  }
 ],
 "coverage": [
  "Verified all four manifest file hashes, including the supplied plan SHA256.",
  "Read every manifested file and inspected the tracked code/test changes against the supplied base.",
  "Traced CLI maintenance locking through completion writes; dashboard and Linear admission, completion logging and shutdown; shared JSON locking; project finalization and PTY cleanup.",
  "Checked relevant specification requirements and local macOS stat/pgrep documentation."
 ],
 "limitations": [
  "No files were edited, tests run, services changed or work delegated.",
  "Failure scenarios were established statically and were not reproduced.",
  "Reported relocation success and test results were not independently verified.",
  "This reinspection did not repeat the live launchd, external-configuration or historical-runtime-path audit."
 ]
}
```

### Host dispositions (build inspection 2, all accepted)
- BUILD-001 (reversed, now fixed): the runner has a maintenance gate. `_inflight_work()` counts every run from admission until its worker returns, which is after the record write, so the gap between leaving `_running_jobs` and writing the record is covered. It refuses new work while maintenance is on. Turning the gate on and admitting work take the same lock, so a run is either counted or refused. Counted: the `/run` route, the project launch helper, retry/rework workers, Linear `_dispatch_issue`, and baseline. `POST /api/maintenance {on}` returns `{maintenance, inflight}`. The script closes the gate first and aborts unless `inflight` is 0, then also requires no running jobs. On any abort before the stop, including a signal, it reopens the gate; once the runner is stopped, a restart starts with the gate open. Tests: in-flight work counted, `/run` 409, a project dispatch refused before any job or worktree, Linear dispatch refused and then admitted, and the script refuses and reopens the gate when runs are in flight.
- BUILD-002: every pgrep pattern is escaped (`lit`, including the dot in `app.py`). Tests: rollback with a dotted NEW and a look-alike runner (shim pgrep now applies the real regex); a dotted OLD is replaced literally while a look-alike path survives.
- BUILD-003: devices are compared on physical paths (`cd -P` + `stat -f %d .`). Test: a destination parent that is a symlink to /dev is refused.
- pytest 393 passed (relocate suite 23).

## Build inspection 3 (2026-10-15)
- Fresh Codex session 01a1410d-d310-7d62-8ef2-f0dd050ecc97, base 1d139fe, cross-provider, 298 s. Result `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-prototypes-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/claudex/move/i3/claudex-8lf3fxf2/result.json`.
- Verdict: **REVISE**, 5 findings.

```json
{
 "verdict": "REVISE",
 "summary": "BUILD-002 and BUILD-003 address the reported scenarios. BUILD-001 remains unresolved, and the maintenance gate introduces admission and cleanup defects.",
 "findings": [
  {
   "id": "BUILD-001",
   "severity": "high",
   "path": "runner/modules/linear/__init__.py:574",
   "evidence": "The installed LaunchAgent executes runner/app.py directly, so the serving application and maintenance endpoint belong to __main__. Linear imports _inflight_work from app, loading a separate module with its own _MAINTENANCE, _INFLIGHT and _running_jobs; app.py contains no module alias. A Linear worker paused between removing its job and writing its record can therefore remain active while the serving endpoint reports inflight=0 and no running jobs. Relocation then stops the runner and loses the completion record. The new tests use import app throughout, hiding this split.",
   "fix": "Use one canonical application/state instance, or move admission and job state into a shared module. Add coverage using the actual script entrypoint, with a Linear completion paused before its record write."
  },
  {
   "id": "BUILD-004",
   "severity": "medium",
   "path": "runner/app.py:3546",
   "evidence": "Retry admission happens inside the background worker, after the route publishes running state and returns success. During maintenance, an unbound retry inserts _running_jobs at line 3537, but _counted refuses its worker without executing cleanup or logging. Bound retries similarly push the tracker to running before their project worker refuses. Baseline admission has the same ordering: lines 3193–3195 publish running and return success, while the refused worker never clears _BASELINES; subsequent baseline requests remain blocked after maintenance ends.",
   "fix": "Reserve admission atomically before publishing state or launching a thread, return 409 on refusal, and transfer that reservation to the worker through finalization. Reuse the reservation across nested project dispatch rather than checking admission again."
  },
  {
   "id": "BUILD-005",
   "severity": "medium",
   "path": "runner/modules/linear/__init__.py:1216",
   "evidence": "Counted workers still return before their final tracker writes finish. Project completion calls _push_linear_state_async at app.py:2814, and non-project Linear completion reaches push_state through _mark_issue_review. push_state only updates memory and launches an uncounted daemon thread; _push_sync performs the durable local or remote update later. If that thread is delayed, inflight reaches zero and relocation can terminate it, leaving a completed ticket persistently In Progress. This remains possible even after the module-instance defect is fixed.",
   "fix": "Keep final tracker updates within the admitted operation, or reserve continuation work before spawning the thread and release it only after persistence finishes. Existing completion work must remain allowed after admission closes."
  },
  {
   "id": "BUILD-006",
   "severity": "medium",
   "path": "scripts/relocate_checkout.sh:50",
   "evidence": "The script closes admission at line 50, but installs HUP/INT/TERM handlers only at line 179. A signal during worktree checks, lock acquisition or backup exits without reopening admission; the EXIT trap at line 95 only releases the lock helper. The runner stays up but rejects new runs indefinitely. Also, if the server closes admission but curl times out receiving its response, MAINT is still off and die skips reopening it.",
   "fix": "Install phase-aware cleanup before attempting to close admission. Handle uncertain request outcomes and every pre-stop exit by restoring admission, and report explicitly if restoration cannot be confirmed. Cover early interruption and a response timeout after server-side gate activation."
  },
  {
   "id": "BUILD-007",
   "severity": "medium",
   "path": "scripts/relocate_checkout.sh:27",
   "evidence": "Admission is a shared boolean without ownership, and scripts modify it before obtaining the exclusive maintenance lock. If attempt A holds the lock and pauses before bootout, attempt B closes the already-closed gate, detects A's lock helper in others(), and aborts. B's die then reopens A's gate. A never rechecks admission or inflight before stopping the runner, allowing newly admitted work to be interrupted and its completion lost.",
   "fix": "Serialize relocation attempts before modifying the runner gate, or introduce ownership so an abort can release only its own maintenance reservation. Cover overlapping attempts where the second aborts while the first remains active."
  }
 ],
 "coverage": [
  "Verified all seven manifested file hashes, the supplied plan SHA256, and the tracked diff SHA256 against the supplied base.",
  "Inspected every manifested file, including relocation logic, review history, changed runtime paths and regression tests.",
  "Traced launchd startup, module registration and lazy imports, run/retry/project/baseline admission, Linear dispatch, completion logging and shutdown.",
  "Inspected related CLI maintenance locking, tracker persistence, shared-state helpers, cancellation, stall detection and PTY handoff writers beyond the manifest.",
  "Checked relevant specification requirements and confirmed the reported regex-escaping and symlinked-filesystem fixes statically."
 ],
 "limitations": [
  "No files were edited, tests run, services changed or work delegated.",
  "Failure scenarios were established through static source and interleaving analysis, without reproduction.",
  "The reported successful relocation and 393 passing tests were not independently verified.",
  "External configuration and historical runtime paths were not exhaustively audited; the installed LaunchAgent plist was inspected."
 ]
}
```

### Host dispositions (build inspection 3, all accepted)
- BUILD-001: `app.py` registers itself as `sys.modules["app"]` (setdefault). When launchd runs it as `__main__`, the Linear, PTY and backends modules now reach the same instance: one Flask app, one `_running_jobs`, one gate. Before this fix, Linear dispatch registered its jobs in a second copy the dashboard never saw. Test: runs `runner/app.py` via `runpy` as `__main__` (with `--help`, so it does not serve), then checks `import app` returns that module.
- BUILD-004: an explicit reservation API (`_admit`, `_release`, `_start_reserved`, plus a thread-local "admitted" flag so nested work such as retry → project launch neither re-checks nor double-counts). Retry, baseline and the Linear PATCH dispatch reserve at the route start, before any comment, state, job or thread, and return 409 when refused. The single worker they start takes over the slot; if no worker starts, the route releases it. Test: retry and baseline under maintenance return 409 with no job, event, comment or baseline state, and inflight returns to 0.
- BUILD-005: `push_state` reserves a continuation slot before spawning the sync thread. Continuations are allowed after admission closes, and the thread releases the slot after `_push_sync` persists. Test: a push started inside an admitted run keeps inflight at 1 under maintenance until it persists, then 0.
- BUILD-006: the script installs its signal handler (defined before use) right after taking the maintenance lock, before touching the gate. `MAINT=on` is set before the close request, so a lost answer still leads to a reopen. `reopen` confirms `"maintenance":false` and otherwise prints a warning with the manual command. Tests: a lost gate answer reopens; a TERM right after the gate closes reopens and never stops the runner.
- BUILD-007: the maintenance lock is taken before the gate is touched, so a second relocation fails at the lock and never changes the first one's gate. Test covers overlapping attempts.
- pytest 399 passed (relocate suite 26).

## Build inspection 4 (2026-10-15)
- Fresh Codex session 01a1411e-92d6-7eb2-83a2-32570d081e1f, base ca21bf8, cross-provider, 162 s. Result `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-prototypes-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/claudex/move/i4/claudex-n8aorsof/result.json`.
- Verdict: **REVISE**, 4 findings (BUILD-001/004/006 confirmed).

```json
{
 "verdict": "REVISE",
 "summary": "BUILD-001, BUILD-004 and BUILD-006 are addressed in the inspected paths. Tracker persistence and overlapping relocations still have material gaps.",
 "findings": [
  {
   "id": "BUILD-005",
   "severity": "medium",
   "path": "runner/modules/linear/__init__.py:1002",
   "evidence": "The Linear PATCH route transfers its reservation to the dispatch worker but starts _linear_sync_patch in an uncounted daemon thread. That thread can remain delayed before acquiring the issue lock while the dispatch and its counted final pushes finish. Maintenance then reports inflight=0 and relocation terminates the pending writer. Accepted title, description or preferred-agent edits can be lost: this branch persists only the state locally at line 985.",
   "fix": "Reserve a separate continuation before starting _linear_sync_patch and release it after persistence, including exception and thread-start failure paths. Cover a delayed PATCH sync after dispatch completion."
  },
  {
   "id": "BUILD-007",
   "severity": "medium",
   "path": "scripts/relocate_checkout.sh:81",
   "evidence": "Overlapping attempts are serialized only if both helpers open the same lock inode. Attempt B can finish preflight and pause before starting its helper; attempt A then locks and renames OLD to NEW. B resumes and os.makedirs recreates OLD/outputs/locks, opening a different maintenance.lock. A can report success with OLD recreated, or refuse rollback at line 179 and leave the service stopped. The overlap test covers an already-held lock, not this interleaving.",
   "fix": "Prevent helper initialization from recreating checkout ancestors and verify checkout and lock identity after acquisition, as run_skill.py does, or use a stable external relocation lock. Add coverage with B paused before helper initialization until A renames the checkout."
  },
  {
   "id": "BUILD-008",
   "severity": "medium",
   "path": "runner/app.py:2602",
   "evidence": "_reserve_continuation unconditionally accepts work after maintenance closes, without requiring an existing admitted operation. PATCH /api/runs/<id>/status remains ungated and calls push_state through line 3394. After relocation observes inflight=0, a user can mark a linked run successful, receive success, and queue a remote Done update that bootout terminates. The saved run and tracker then disagree despite the claimed maintenance barrier.",
   "fix": "Admit independent mutation requests before their side effects and refuse them during maintenance. Permit post-closure continuations only under an existing reservation, keeping that reservation alive until the continuation is reserved."
  },
  {
   "id": "BUILD-009",
   "severity": "low",
   "path": "runner/modules/linear/__init__.py:1246",
   "evidence": "push_state increments _INFLIGHT before constructing and starting its thread, but releases the slot only inside that thread. If Thread.start raises, such as when thread resources are exhausted, the counter permanently retains the slot. Subsequent relocations refuse with runs in flight even after every actual worker finishes.",
   "fix": "Release the continuation reservation if thread construction or startup fails, following the exception handling in _start_reserved. Cover a failed thread start."
  }
 ],
 "coverage": [
  "Verified all seven manifested file hashes, the supplied plan SHA256 and tracked diff SHA256 against the supplied base.",
  "Inspected every manifested file, including the plan, review history, relocation script and both test files; runtime inspection focused on changed code and related callers.",
  "Traced script module aliasing, run/retry/baseline/Linear admission, nested project launch, reservation transfer, completion logging and tracker persistence.",
  "Inspected related CLI maintenance locking, local tracker writes, reset-generation locks, shared-state helpers, stall detection and PTY handoff logging beyond the manifest.",
  "Checked relevant specification requirements for dispatch records, state persistence and concurrent execution."
 ],
 "limitations": [
  "No files were edited, tests executed, services changed or work delegated.",
  "Findings rely on static source and interleaving analysis; scenarios were not reproduced.",
  "The reported successful relocation and 399 passing tests were not independently verified.",
  "Live launchd configuration, external settings and historical runtime paths were not independently audited."
 ]
}
```

### Host dispositions (build inspection 4, all accepted; per-route patches replaced by one mechanism)
- BUILD-008 + BUILD-005: instead of reserving route by route, a Flask `before_request` gate admits every mutating request (anything but GET/HEAD/OPTIONS, `/api/maintenance` and `/socket.io`) and counts it until `teardown_request`, or returns 409 under maintenance. Every background writer now starts through `_start_counted`: spawned from admitted work (a request, or a counted worker or poll iteration), it takes its own slot even after admission closed, because its parent is still counted at that moment; spawned from anywhere else it must be admitted. This covers Linear PATCH sync threads, background creates, dispatch, retry, baseline and final pushes; `_reserve_continuation` is gone. The Linear poller admits each iteration (it writes the local tracker) and sleeps while maintenance is on. Tests: status PATCH and project POST return 409 while reads stay open; counted threads inherit admission.
- BUILD-009: `_start_counted` releases the slot when `Thread.start` raises. Test monkeypatches `Thread.start` to fail and checks inflight returns to 0.
- BUILD-007: the lock helper is now `scripts/maintenance_lock.py`, with the same rules as run_skill. It requires the checkout's inode recorded at the script's preflight, creates folders one level at a time, and re-checks the checkout and lock-file inodes after locking. Test: a checkout renamed before the helper starts gives "busy" without recreating it; a different folder at the old path gives "busy" without creating `outputs/`.
- Live check after restart: gate on → `POST /api/projects` returns 409 → gate off. pytest 402 passed.

## Build inspection 5 (2026-10-15)
- Fresh Codex session 01a1412c-6d89-7c81-9ba2-4b206980d4a6, base a6289ab, cross-provider, 179 s. Result `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-prototypes-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/claudex/move/i5/claudex-q46c5rkg/result.json`.
- Verdict: **REVISE**, 3 findings (BUILD-005/007/008/009 confirmed).

```json
{
 "verdict": "REVISE",
 "summary": "The BUILD-005/007/008/009 fixes address their reported scenarios, but maintenance still excludes three paths that write persistent state.",
 "findings": [
  {
   "id": "BUILD-010",
   "severity": "medium",
   "path": "runner/app.py:2667",
   "evidence": "All GET/HEAD requests bypass admission, but both progress GET endpoints call _build_progress_payload, which rewrites the saved progress JSON at line 928 using non-atomic write_text at line 677. An open detail panel polls these endpoints every three seconds. Maintenance can report inflight=0 while such a request is writing; bootout can leave the file truncated, losing its saved stream_log reference and making historical events disappear despite the relocation acceptance criterion.",
   "fix": "Make progress GETs read-only, or admit and count these handlers before any persistence and refuse them during maintenance. Audit other GET-side writes, including task-state migration. Add coverage for a progress request paused during persistence."
  },
  {
   "id": "BUILD-011",
   "severity": "medium",
   "path": "runner/modules/pty/__init__.py:421",
   "evidence": "Socket.IO handlers bypass Flask before_request admission. term_input calls _record_pending_handoff, which writes journals and task state through _write_run_log at line 384 without a reservation. After maintenance reports zero, an existing terminal can submit a selected skill and start this writer. Shutdown closes terminal processes but does not join these handlers, so relocation can interrupt the handoff record between its journal and state writes. This path never registers a _running_jobs entry.",
   "fix": "Apply admission to terminal mutation handlers before consuming pending handoffs or forwarding commands, and hold it through their persistent writes. Return an explicit maintenance refusal to the client. Cover both a handoff already writing when maintenance closes and a new handoff after closure."
  },
  {
   "id": "BUILD-012",
   "severity": "medium",
   "path": "runner/modules/stall_detection/__init__.py:43",
   "evidence": "The stall-detection daemon remains uncounted and does not pause under maintenance. Its hourly _archive_stale_sent call appends to RUN_LOG and STATE_RUN_LOG separately (app.py:345–349), even with no running jobs. Relocation can therefore observe inflight=0 and stop the runner between those appends, leaving the journals inconsistent. check_once also writes run records directly at line 73 and can outlive the counted worker whose job it inspected.",
   "fix": "Admit each stall/cleanup iteration through _inflight_work, skip it while maintenance is closed, and retain the reservation through all journal and state writes. Keep the sleep outside the reservation. Add coverage with cleanup paused between journal writes."
  }
 ],
 "coverage": [
  "Verified all eight manifested file hashes, the plan SHA256, and the tracked diff SHA256 against the supplied base.",
  "Inspected every manifested file, including the relocation script, lock helper, review history, and both test files.",
  "Traced request admission, counted thread startup, retry, baseline, project dispatch, Linear dispatch/sync/push, and poller reservations.",
  "Inspected related CLI locking, shared-state helpers, progress polling, Socket.IO handoffs, periodic cleanup, module startup, and shutdown beyond the manifest.",
  "Checked relevant SPEC.md requirements for dispatch records, journal integrity, and persistent state; inspected installed Flask-SocketIO event handling."
 ],
 "limitations": [
  "No files were edited, tests executed, services changed, or work delegated.",
  "Failure scenarios were established through static source and interleaving analysis, without reproduction.",
  "The reported relocation success and 402 passing tests were not independently verified.",
  "Live launchd configuration, external settings, and historical runtime records were not independently audited."
 ]
}
```

### Host dispositions (build inspection 5, all accepted) and a full writer audit
- BUILD-010: `_write_run_progress_json` now uses `write_json_atomic`. The GET progress handlers only refresh this cache, and an interrupted write leaves the previous file whole, so they stay outside admission. Task-state migration on GET was already atomic (`write_json_atomic`). Test: a write killed at `os.replace` leaves the old file intact.
- BUILD-011: `term_input` that completes a pending skill handoff runs `_record_pending_handoff` and the forward under `_inflight_work()`. Under maintenance the handoff is dropped before anything is recorded or forwarded, and the terminal shows the refusal. Ordinary keystrokes are not file writes and pass through. Test: refused under maintenance with nothing recorded; recorded after the gate reopens.
- BUILD-012: each stall/cleanup pass (`run_pass`) is admitted and counted through `check_once` and `_archive_stale_sent`, and skipped under maintenance; the sleep stays outside. Test: counted (inflight 1 inside), skipped under maintenance.
- Writer audit (grep of every write in runner/, by context), so coverage can be checked as a whole:
  - mutating HTTP routes → request gate (`before_request` / `teardown_request`)
  - background threads → `_start_counted` (dispatch, retry, baseline, Linear sync/create/push)
  - Linear poller iteration → admitted per iteration, paused under maintenance
  - stall/cleanup pass → admitted per pass
  - terminal skill handoff (Socket.IO) → admitted around the record
  - GET-side writes (progress cache, task-state migration) → atomic replace only
  - DeepSeek usage poller → its cache is written with `os.replace` under its own lock (atomic; not counted)
  - startup migration → runs before serving
  - run_skill.py CLI → shared maintenance lock
- pytest 405 passed.

## Build inspection 6 (2026-10-15)
- Fresh Codex session 01a14134-51af-7d11-a8a2-b95956a578c2, base 59fca9d, cross-provider, 212 s. Result `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-prototypes-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/claudex/move/i6/claudex-kge0g15k/result.json`.
- Verdict: **REVISE**, 4 findings (BUILD-010 truncation and BUILD-012 confirmed).

```json
{
 "verdict": "REVISE",
 "summary": "BUILD-012 is addressed, and BUILD-010's truncation scenario is fixed. BUILD-011 retains a race, and the writer audit misses additional persistence paths.",
 "findings": [
  {
   "id": "BUILD-011",
   "severity": "medium",
   "path": "runner/modules/pty/__init__.py:435",
   "evidence": "Admission depends on an unlocked pending_handoff check. Socket.IO executes handlers concurrently by default. A newline handler can observe no pending handoff, then skill_selected can set one before _forward_input executes. The latter consumes it and writes run journals without admission, even while maintenance reports inflight=0. Shutdown can interrupt these writes. The added test exercises sequential events only.",
   "fix": "Reserve admission before every newline operation that could record a handoff, or serialize pending-handoff changes and consumption under one lock. Cover concurrent skill_selected and term_input while maintenance is closed."
  },
  {
   "id": "BUILD-013",
   "severity": "medium",
   "path": "runner/core/registry_loader.py:115",
   "evidence": "GET /api/registry?agent=claude calls load_registry → ensure_claude_registry, which overwrites the workspace's .claude/registry.json and registry.md with non-atomic write_text calls. GET / does the same when Claude is selected. Both bypass maintenance admission at app.py:2669. Relocation can therefore observe zero inflight and stop the runner during either overwrite, leaving an empty or partial generated registry. These GET-side writers are missing from the claimed audit.",
   "fix": "Make registry reads side-effect free, or protect cache generation with admission through completion. If retaining the atomic-cache exception, atomically replace both cache files and serialize competing writers. Add maintenance coverage for registry-loading GETs."
  },
  {
   "id": "BUILD-014",
   "severity": "medium",
   "path": "runner/app.py:743",
   "evidence": "_stream_text_run starts its persistent log writer as an uncounted daemon thread. On timeout it kills only the subprocess and raises without joining the reader. _stream_claude_run:2304 and _stream_dsh_run:2373 have the same lifetime gap. A reader delayed in persistence, or receiving stdout retained by a descendant, can keep writing after its parent records timeout and releases admission. Maintenance can report zero and terminate that writer, interrupting stream persistence.",
   "fix": "Give each persistent reader its own counted reservation, or retain the parent's reservation until every reader exits. Clean up subprocesses and pipes on timeout, and cover a reader paused during persistence after the parent times out."
  },
  {
   "id": "BUILD-015",
   "severity": "medium",
   "path": "runner/app.py:665",
   "evidence": "Atomic replacement does not protect the read-modify-write sequence. A progress GET can read a cache before stream_log is populated and pause before replacement. The stream worker can then write stream_log and finish; the delayed GET subsequently replaces that document with its stale copy lacking stream_log. Later progress requests have no saved stream reference and return no events for an unlinked run, despite the stream file existing. The new test checks replacement failure, not concurrent updates.",
   "fix": "Lock the entire cache read-merge-replace operation for every caller, or make progress GETs read-only. Add an interleaving test where a stale GET commits after the worker's final metadata update."
  }
 ],
 "coverage": [
  "Verified all seven manifested file hashes, the supplied plan SHA256, and the tracked diff SHA256 against the supplied base.",
  "Read every manifested file and inspected the relocation script, lock helper, and relocation tests.",
  "Traced HTTP admission, counted workers, run/retry/baseline/project dispatch, Linear polling and persistence, stall cleanup, terminal handoffs, and shutdown.",
  "Inspected related CLI locks, shared-state helpers, registry caches, stream readers, DeepSeek persistence, and installed Socket.IO concurrency behavior beyond the manifest.",
  "Checked relevant SPEC.md requirements for registry display, dispatch records, append-only journals, and crash integrity."
 ],
 "limitations": [
  "No files were edited, tests executed, services changed, or work delegated.",
  "Findings use static source and interleaving analysis; scenarios were not reproduced.",
  "Reported relocation success and 405 passing tests were not independently verified.",
  "Live launchd configuration, external settings, and historical runtime records were not independently audited."
 ]
}
```

### Host dispositions (build inspection 6, all accepted)
- BUILD-011: every newline in `term_input` is admitted first; only a completed line can record a handoff. When refused, `_forward_input(..., refused=…)` never records and drops a pending handoff with a message, so a concurrent `skill_selected` cannot slip a record past the gate.
- BUILD-013: `ensure_claude_registry` writes both cache files with `write_text_atomic` (new in state_io) under `file_lock`. Test: an interrupted replace leaves the old file whole.
- BUILD-014: stream readers (`_stream_text_run`, `_stream_claude_run`, `_stream_dsh_run`, plus the stderr drainer) start through `_start_counted`, which now returns the thread, so each stays counted until it stops writing, even past a timeout. Test checks the reader is started counted.
- BUILD-015: `_write_run_progress_json` holds a `file_lock` around read-merge-replace. Test: 12 concurrent writers each keep their key.
- pytest 408 passed.
- User decision (2026-10-15): one more inspection round, then stop. Any remaining findings go to a separate "runner write-safety hardening" plan and this plan is archived.

## Build inspection 7 (2026-10-15, final by user decision)
- Fresh Codex session 01a14149-06ee-7da0-96fe-868327ecc62f, base d91c3d9, cross-provider, 210 s. Result `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-prototypes-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/claudex/move/i7/claudex-lwb3fnym/result.json`.
- Verdict: **REVISE**, 4 findings (BUILD-011/013/015 confirmed; BUILD-014 counting confirmed).

```json
{
 "verdict": "REVISE",
 "summary": "BUILD-011, BUILD-013 and BUILD-015 address their reported scenarios. BUILD-014 now counts readers correctly, but timeout cleanup remains incomplete. Additional cache, relocation and reservation defects remain, ranked below.",
 "findings": [
  {
   "id": "BUILD-016",
   "severity": "medium",
   "path": "runner/app.py:285",
   "evidence": "The separate execution-registry cache still uses write_text on a shared content-derived filename. Two concurrent dispatches with the same agent and registry overwrite the same file. After dispatch A publishes the path, dispatch B can truncate it while A's run_skill subprocess reads it. runner/run_skill.py:65 then raises JSONDecodeError on empty or partial JSON. Maintenance counting does not serialize these concurrent writers. This pre-existing path is separate from the repaired Claude registry cache.",
   "fix": "Publish execution-registry caches atomically and avoid truncating published files. Add an interleaving check where one subprocess reads while another dispatch republishes the same cache."
  },
  {
   "id": "BUILD-014",
   "severity": "medium",
   "path": "runner/app.py:744",
   "evidence": "Reader reservations prevent premature shutdown, but timeout handling kills only the direct subprocess and leaves readers running. If an agent starts a background descendant that retains stdout, the reader can block indefinitely after the parent times out and removes its job/process entries. Its new reservation keeps inflight positive, permanently refusing relocation until that descendant exits or the runner restarts. The Claude and DSH readers have the same gap. The new test checks successful reader startup, not timeout cleanup.",
   "fix": "Give these subprocesses owned process groups and bounded timeout cleanup that terminates descendants, reaps processes and stops pipe readers. Retain reservations until persistence finishes. Cover a descendant retaining stdout after the direct process is killed."
  },
  {
   "id": "BUILD-017",
   "severity": "medium",
   "path": "scripts/relocate_checkout.sh:185",
   "evidence": "NEW is checked for existence only at line 42. If another process creates NEW before line 185, mv OLD NEW succeeds by nesting the checkout inside that directory. Repointing then fails because NEW/.venv is absent. Rollback moves the entire destination directory back to OLD, leaving the checkout nested there, so restart_old cannot start OLD/runner/app.py. The exclusive maintenance lock protects the source checkout, not the destination namespace.",
   "fix": "Use a rename operation that atomically refuses an existing destination instead of nesting. Verify the relocated directory's identity before repointing or rollback, and cover destination creation between preflight and rename."
  },
  {
   "id": "BUILD-009",
   "severity": "low",
   "path": "runner/app.py:2642",
   "evidence": "This revision moves threading.Thread construction outside the exception handler, after reserving an inflight slot. If construction raises, such as MemoryError while allocating its synchronization objects, no worker exists to release the slot and the exception handler is skipped. After resource recovery, maintenance still reports phantom work. Previously both construction and startup were protected.",
   "fix": "Place thread construction and startup inside the same reservation-release exception handler. Extend failure coverage to a constructor exception."
  }
 ],
 "coverage": [
  "Verified all seven manifested file hashes, the supplied plan SHA256 and the tracked diff SHA256 against the supplied base.",
  "Read every manifested file, the complete relocation script, maintenance helper and relocation tests.",
  "Reinspected terminal admission, registry publication, progress read-merge-replace locking and all three counted stream implementations.",
  "Traced related run/retry/project/Linear callers, CLI registry reads and maintenance locks, tracker persistence, stall cleanup and shutdown.",
  "Checked relevant SPEC.md requirements for dispatch records, atomic state, concurrency and crash integrity."
 ],
 "limitations": [
  "No files were edited, tests executed, services changed or work delegated.",
  "Findings rely on static source and interleaving analysis; failure scenarios were not reproduced.",
  "The reported successful relocation and 408 passing tests were not independently verified.",
  "Live launchd state, external configuration, historical runtime records and every repository writer were not exhaustively audited."
 ]
}
```

### Host dispositions (build inspection 7, the last round by user decision)
- BUILD-009 (my regression): thread construction moved back inside the release-on-failure handler. Test: a `Thread` constructor that raises leaves inflight at 0. Fixed after this inspection, so not independently reviewed; carried to the follow-up plan for review.
- BUILD-017: the script renames with `os.rename` (`rename_dir`) instead of `mv`. A destination that appears after the preflight makes the rename fail (non-empty dir) rather than nesting the checkout; the runner restarts on OLD. Test: a destination created at bootout gives "rename failed", nothing nested, OLD running. Fixed after this inspection, so not independently reviewed; carried to the follow-up plan.
- BUILD-016 (pre-existing execution-registry cache race) and the BUILD-014 remainder (timeout cleanup of process groups and readers): moved to `docs/exec-plans/active/2026-10-15-runner-write-safety.md`. The BUILD-014 remainder can only make the script refuse (in-flight stays above 0); it does not lose data.
- pytest 410 passed. Inspection rounds used: 7 of 20. Assurance: cross_provider throughout.

### Summary
- Plan review: 5 rounds (9 → 4 → 2 → 1 → 0). Build inspections: 7 (3 → 3 → 5 → 4 → 3 → 4 → 4), all cross-provider. The relocation itself ran once, successfully, and was verified from the new path. Remaining items live in the follow-up plan.
