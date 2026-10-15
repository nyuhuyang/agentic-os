# Review log — project registry in the dashboard

- Started 2026-10-15. Host: Claude Code (planner, builder). Plan reviewer and build inspector: fresh Codex CLI sessions (codex-cli 0.162.0, CLI default model, no effort override). Fallback: same-provider-on-unavailable. Plan review rounds ≤ 20; inspection rounds ≤ 20.
- Authorization: the user asked for the plan ("动手写plan"). Building is not yet authorized.
- Budget: user chose the default model with up to 20 rounds. Review reads the plan plus the relevant parts of runner/projects.py, runner/app.py and runner/templates/index.html.
- User decisions: add + edit + remove; history suggestions and manual paths, for existing repos and new folders; comments become a `note` field; no new dependency.
- User addition (mid-planning): every project already in the panel must be removable too, and add + remove ship together in one build. Plan updated: broken entries removable; remove dialog offers clean-up of work-free leftover worktrees.

## Plan review round 1 (2026-10-15)
- Codex session 01a14052-4070-7f72-a6e7-54592ab5afb7, cross-provider, 233 s. Result `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-prototypes-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/claudex/reg/r1/claudex-bduetbi6/result.json`.
- Verdict: **REVISE**, 8 findings.

```json
{
 "verdict": "REVISE",
 "summary": "The plan has material validation, destructive cleanup, concurrency and confidentiality gaps against existing repository behavior.",
 "findings": [
  {
   "id": "REGUI-001",
   "severity": "high",
   "path": "docs/exec-plans/active/2026-10-15-project-registry-ui.md:35",
   "evidence": "The proposed save validates entries with _parse_project, which does not validate project keys. Key validation occurs separately in load_registry (runner/projects.py:276). Creating an otherwise valid entry with key 'bad key' would therefore pass the proposed validation, then make subsequent loads reject the entire registry, including healthy projects.",
   "fix": "Validate create/edit keys against the registry identifier rules before writing or using them in filesystem paths. Add a rejected-invalid-key case that verifies byte-identical registry contents."
  },
  {
   "id": "REGUI-002",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-15-project-registry-ui.md:35",
   "evidence": "_check_seed_source checks existence and symlink containment, not committed ignore rules (runner/projects.py:387). An existing seed ignored only through .git/info/exclude passes both proposed validators and is saved, but dispatch rejects it in _copy_seeds at runner/projects.py:428. A tracked seed similarly passes save validation but collides during copying. This contradicts acceptance criterion 18.",
   "fix": "Before replacing the registry, validate seeds against the committed checkout used for fresh worktrees, including committed ignore rules and destination collisions. Reuse the dispatch checks or extract a shared validator."
  },
  {
   "id": "REGUI-003",
   "severity": "high",
   "path": "docs/exec-plans/active/2026-10-15-project-registry-ui.md:50",
   "evidence": "create_worktree(project, 'CHECK') explicitly reuses an existing worktree (runner/projects.py:517–525). CHECK is also a valid CLI ticket identifier. If that worktree already contains uncommitted files or unique commits, the planned baseline can verify it and then call remove_worktree, which uses worktree remove --force and branch -D (runner/projects.py:560–564). This can destroy existing work and does not provide a fresh baseline.",
   "fix": "Give each baseline a newly allocated identifier and require fresh creation. Clean up only resources successfully created by that invocation; never delete an existing CHECK worktree or branch on failure."
  },
  {
   "id": "REGUI-004",
   "severity": "high",
   "path": "docs/exec-plans/active/2026-10-15-project-registry-ui.md:36",
   "evidence": "The registry lock does not coordinate with launches. _run_project_ticket registers jobs and reads the registry without that lock (runner/app.py:2627,2647), while CLI worktree creation reads the project before taking only a ticket lock (runner/projects.py:949). After removal checks the running-job snapshot and enumerates directories, a new launch can read the still-present entry and create another ticket worktree while removal deletes the entry. The result is a running or orphaned project whose registry entry has disappeared.",
   "fix": "Introduce a cross-process project lifecycle lock shared by dispatch, CLI worktree operations, baseline and terminal acquisition. Removal must exclude new acquisitions, recheck activity and enumerate worktrees while holding exclusive ownership through the registry update."
  },
  {
   "id": "REGUI-005",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-15-project-registry-ui.md:36",
   "evidence": "The specified per-worktree check-and-delete sequence permits partial destruction: clean worktree A is removed, then dirty, committed or locked worktree B causes refusal. A and its branch are already gone even though the checklist at line 90 requires refusal with no change. Releasing individual ticket locks between preflight and deletion also permits intervening changes.",
   "fix": "Acquire all candidate ticket locks in a deterministic order and preflight every worktree's ownership, binding, base, cleanliness and commits before deleting any. Retain those locks through cleanup and distinguish preflight refusal from an operational deletion failure."
  },
  {
   "id": "REGUI-006",
   "severity": "high",
   "path": "docs/exec-plans/active/2026-10-15-project-registry-ui.md:49",
   "evidence": "Editing confidential from false to true during an active run leaves that run using its captured false binding (runner/app.py:2621–2623). Final logging and tracker comments use that captured value without rereading current policy (runner/app.py:2721–2737). tracker_comment then selects the full-content fallback, and LinearModule.post_comment forwards it without another confidentiality check (runner/project_runs.py:122; runner/modules/linear/__init__.py:1243). The UI can report the project as confidential while its finishing run publishes prompt/output to Linear.",
   "fix": "Reject confidentiality changes while an execution is active using the lifecycle lock, or implement an explicit transition that stops unsafe execution. Also recompute and persist sticky confidentiality before final logging and outbound comments so promotion cannot leave a stale permissive binding."
  },
  {
   "id": "REGUI-007",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-15-project-registry-ui.md:35",
   "evidence": "Keeping only the key immutable is insufficient for existing worktrees. Changing its path from repository A to B passes entry validation, but create_worktree subsequently rejects A's existing directory as belonging to another repository. Cleanup through the updated project also refuses it (runner/projects.py:518,557), and load_binding requires the recorded project_path to match (line 456). Persisted issue bindings continue routing retries to this key (runner/modules/linear/__init__.py:588–600). A successful edit can therefore strand tickets and prevent panel cleanup.",
   "fix": "Guard repository-identity changes while owned worktrees or executions exist, with an explicit recovery message, or design a migration that preserves ownership and durable ticket bindings. Document the restriction in the edit acceptance criterion."
  },
  {
   "id": "REGUI-008",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-15-project-registry-ui.md:35",
   "evidence": "The single read/hash check followed by validation and os.replace does not guarantee protection against concurrent hand edits. state_io.file_lock locks a sibling .lock file (runner/state_io.py:25), which an ordinary editor does not acquire. An editor can save after the hash check but before replacement; the UI then overwrites that edit without the promised 409. Seed validation can substantially widen this window.",
   "fix": "Define a cooperative locking protocol for supported manual edits if strict conflict guarantees are required. Recheck immediately before replacement to catch intervening edits, derive GET entries and their hash from one byte snapshot, and state the limitation for editors that ignore the protocol."
  }
 ],
 "coverage": [
  "Read the on-disk plan and verified SHA256 3fafef0033dec609a547c1d265bfef7f09e4631de4e7f0379b977ea627f5f870.",
  "Inspected runner/projects.py registry validation, seeds, bindings, worktree creation/removal, ticket locks, verification, session readers and CLI entry points.",
  "Traced runner/app.py request protection, project dispatch, running-job registration, durable issue-binding writes, confidentiality resolution, final logging and tracker comments.",
  "Traced related callers in runner/project_runs.py and runner/modules/linear/__init__.py, plus terminal ownership and ticket-lock acquisition in runner/modules/pty/__init__.py.",
  "Read runner/state_io.py, projects.example.yaml, current Projects rendering and escaping, and relevant existing test source in tests/test_projects.py, tests/test_project_dispatch.py and tests/test_project_sessions.py."
 ],
 "limitations": [
  "Static plan review against the current implementation; proposed helpers, routes and UI controls are not yet implemented.",
  "No files were edited, tests or browser checks run, or work delegated.",
  "Live projects.yaml, personal session stores and launchd/TCC behavior were not inspected; comment migration and protected-folder access remain unverified.",
  "Spec fidelity was assessed against the plan's acceptance criteria and inspected code/schema contracts; broader specification documents were not inspected."
 ]
}
```

### Host dispositions (round 1)
- REGUI-001 accepted: `save_project` validates the key against `_IDENT` before anything else; test with `bad key` and `../x`.
- REGUI-002 accepted: when seeds or path change, save creates a throwaway fresh worktree (`REGCHECK-<unix-ms>`, must be `reused: False`) so the exact dispatch seed checks run (copy, collision, committed-ignore), then removes it. Tests for info/exclude-only and tracked seeds.
- REGUI-003 accepted: baseline uses a fresh `BASELINE-<unix-ms>` id, requires `reused: False`, aborts without removing anything otherwise, and removes only its own worktree.
- REGUI-004 accepted: new per-project lifecycle lock (`flock` on `WORKTREE_ROOT/<key>/PROJECT.lock`). Shared and blocking for dispatch (before its registry read until its record is written), CLI worktree/verify/cleanup, baseline, save-time seed check, and worktree terminals for their lifetime. Exclusive and non-blocking for remove and for edits changing path/confidential/seed. Dispatch re-reads the registry after taking the shared lock.
- REGUI-005 accepted: cleanup takes every ticket lock in sorted order, preflights all worktrees, refuses with the full list before deleting anything, deletes while holding all locks; a deletion error after preflight is reported as operational and the entry is kept.
- REGUI-006 accepted in part: confidentiality changes need the exclusive project lock, so they are refused while any run holds the shared lock, and the stale-binding window cannot occur through the UI. Rejected: re-deriving confidentiality before final logging. With the lock in place it is redundant; a hand edit of the file during a run is a pre-existing path outside this plan.
- REGUI-007 accepted: a path change is refused while any worktree of the key exists (and while busy). Durable bindings for a removed or re-pathed key are documented as failing with the existing errors, not migrated.
- REGUI-008 accepted: GET entries and hash come from one byte snapshot, and the hash is re-checked immediately before `os.replace`. The remaining instant is documented as a limitation in the acceptance criterion, because editors do not take the lock.

## Plan review round 2 (2026-10-15)
- Same Codex session (resumed), cross-provider, 220 s. Result `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-prototypes-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/claudex/reg/r2/claudex-8w0pjs8c/result.json`.
- Verdict: **REVISE**, 5 findings.

```json
{
 "verdict": "REVISE",
 "summary": "The revision addresses most round-1 findings. Remaining defects concern lifecycle-lock boundaries, nested locking, deletion conflict checks, broken-entry removal and lock-file placement.",
 "findings": [
  {
   "id": "REGUI-006",
   "severity": "high",
   "path": "docs/exec-plans/active/2026-10-15-project-registry-ui.md:33",
   "evidence": "The specified shared-lock lifetime ends when the run record is written. However, _run_project_ticket posts its tracker comment afterward (runner/app.py:2728–2737) and removes the running-job entry only at line 2744. A UI confidentiality promotion can therefore acquire the exclusive lock after logging but before comment publication. The captured false binding still selects the full-content fallback in runner/project_runs.py:122, and LinearModule.post_comment forwards it without another policy check. This is a remaining UI race, distinct from the accepted hand-edit limitation.",
   "fix": "Hold the shared project lock through the entire launch helper, including tracker comments, final state updates and running-job removal. This closes the gap without requiring the rejected final-policy reread."
  },
  {
   "id": "REGUI-009",
   "severity": "high",
   "path": "docs/exec-plans/active/2026-10-15-project-registry-ui.md:33",
   "evidence": "Path/seed edits are exclusive project-lock holders, but their save-time seed checks are separately specified as blocking shared holders of the same lock. Acquiring the checker's shared flock through another descriptor while the save retains its exclusive flock blocks against the caller's own lock. The save also holds the registry lock, so this can stall subsequent registry mutations. Converting the existing descriptor to shared instead would relinquish the exclusive protection required by the edit.",
   "fix": "Specify that seed validation inherits the save's existing exclusive lock and never reacquires or downgrades it. Acquire shared ownership only when no exclusive ownership is already held, and define one consistent project/registry/ticket lock order."
  },
  {
   "id": "REGUI-008",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-15-project-registry-ui.md:40",
   "evidence": "The final hash recheck now appears in save_project, but remove_project checks only before worktree preflight and cleanup. An ordinary editor can save during those potentially lengthy Git operations because state_io.file_lock protects only a sibling advisory lock file (runner/state_io.py:25). Removal can then overwrite that edit when writing the registry. This window is much larger than the explicitly accepted final-instant race.",
   "fix": "Apply the final hash recheck immediately before registry replacement in remove_project as well. On conflict, preserve the editor's registry and report any cleanup already completed."
  },
  {
   "id": "REGUI-010",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-15-project-registry-ui.md:40",
   "evidence": "The new broken-entry rule contradicts the requirement that broken projects with disposable worktrees remain removable. For example, create a clean ticket worktree, then delete a seed from the main checkout. _seed_path now makes the registry entry unparseable (runner/projects.py:198), although its existing worktree and binding remain valid. Normal removal refuses the leftover directory, cleanup explicitly refuses broken entries, and the UI prohibits editing them. The project cannot be removed through the panel despite holding no work.",
   "fix": "Support ownership-checked cleanup independently of unrelated registry validation failures, using a minimal repository descriptor and validated worktree bindings. Continue refusing unverifiable ownership. Alternatively, explicitly revise the acceptance criterion and user decision to document this removal exception."
  },
  {
   "id": "REGUI-011",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-15-project-registry-ui.md:33",
   "evidence": "PROJECT.lock occupies the ticket-worktree namespace. The existing identifier rule permits the ticket id 'PROJECT.lock' (runner/projects.py:42), and worktree_path maps it to exactly the proposed lifecycle-lock path (line 346). Once the lock file exists, creating that otherwise valid worktree fails ownership checks. A pre-existing worktree with that id also conflicts with creation of the lifecycle lock file. Existing metadata deliberately avoids this namespace collision by residing under .meta.",
   "fix": "Place lifecycle locks outside ticket directories, for example WORKTREE_ROOT/.project-locks/<key>.lock, with appropriate permissions and a stable inode. Cover both a pre-existing PROJECT.lock ticket directory and creation of that valid ticket id."
  }
 ],
 "coverage": [
  "Verified the on-disk plan SHA256: 0e34a83b42c7427749f50a1050b2a0beac82b3a16f50b5aeea669ca9e22fba76.",
  "Checked all eight prior findings against the revision. Accepted the key-validation, fresh seed-validation worktree, baseline ownership, cleanup preflight and path-edit restrictions as plan-level resolutions.",
  "Accepted the snapshot-based GET, save-time hash recheck and documented final-instant editor limitation; the remaining deletion-path gap is identified separately.",
  "Inspected runner/projects.py validation, identifier namespaces, worktree ownership, bindings, verification, ticket locks and CLI callers.",
  "Traced runner/app.py confidentiality capture, durable binding writes, final logging, tracker publication and running-job cleanup; inspected runner/project_runs.py and LinearModule.post_comment.",
  "Inspected PTY worktree acquisition and lifetime ownership, runner/state_io.py, current Projects rendering/API protection, projects.example.yaml and relevant existing test source."
 ],
 "limitations": [
  "Static review of the plan against existing code; the proposed implementation is not yet present.",
  "No files were edited, tests or browser checks run, or work delegated.",
  "Live registry contents, personal session stores and launchd/TCC behavior were not inspected.",
  "Spec fidelity was assessed against the plan's acceptance criteria and inspected repository contracts; broader specification documents were not inspected."
 ]
}
```

### Host dispositions (round 2, all accepted)
- REGUI-006: the shared project lock now covers the entire launch helper body, including tracker comments, final state updates and running-job removal. Test added.
- REGUI-009: one lock order (project → registry → ticket, sorted). Work inside an exclusive holder never re-acquires or downgrades the project lock; shared helpers take an `already_held` flag. Deadlock test added, bounded by a timeout.
- REGUI-008: `remove_project` re-checks the hash immediately before `os.replace`; on a late conflict the editor's file is kept and the response reports any cleanup already done. Test added.
- REGUI-010: cleanup for a broken entry uses a minimal descriptor from the raw `path`; ownership is still checked through `_is_worktree_of` and the sidecar `project_path`. An unverifiable path (missing, or not a repo) refuses cleanup. Tests added.
- REGUI-011: lifecycle locks move to `WORKTREE_ROOT/.project-locks/<key>.lock`, outside every key dir; `_IDENT` keys cannot start with `.`. Worktree enumeration lists directories only. Test for a `PROJECT.lock` / `*.lock` ticket id added.

## Plan review round 3 (2026-10-15)
- Same Codex session (resumed), cross-provider, 425 s. Result `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-prototypes-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/claudex/reg/r3/claudex-zs7r_pui/result.json`.
- Verdict: **REVISE**, 1 finding.

```json
{
 "verdict": "REVISE",
 "summary": "The prior findings are addressed at plan level. The new broken-entry cleanup descriptor introduces a confidentiality gap.",
 "findings": [
  {
   "id": "REGUI-012",
   "severity": "high",
   "path": "docs/exec-plans/active/2026-10-15-project-registry-ui.md:41",
   "evidence": "Cleanup now constructs a descriptor from raw path only, but Project.confidential defaults to False (runner/projects.py:62). Loading a sidecar does not automatically apply its confidentiality; that requires effective(project, meta) (line 497). Consequently, cleanup of a confidential project with a deleted seed can call uncommitted() using a non-confidential descriptor. That helper runs git status through confine_for(), which returns no sandbox when confidentiality is false (lines 188–191,703). Git status can execute repository-configured clean/process filters when examining modified tracked files; the hardening flags disable only fsmonitor and hooks. A repository-controlled filter can therefore execute with network access during preflight, even if cleanup subsequently refuses the dirty worktree.",
   "fix": "Explicitly preserve confidentiality in cleanup descriptors. Conservatively sandbox broken-entry cleanup, and apply each worktree's sticky confidentiality from its validated sidecar and applicable durable policy before potentially executable Git checks. Add regression coverage confirming that broken confidential entries and sidecar-confidential worktrees retain confinement during cleanup preflight."
  }
 ],
 "coverage": [
  "Verified the on-disk plan SHA256: 3f07784456991413814a3396e5e64cd16fa4eb1c72729b2bb62b553285d2a055.",
  "Checked all five round-2 dispositions: complete launch-helper lock lifetime, inherited exclusive ownership, removal hash recheck, minimal ownership descriptor and separate lifecycle-lock namespace are reflected in the revision.",
  "Inspected registry validation, worktree creation/removal, binding metadata, identifier namespaces, CLI operations and ticket locks in runner/projects.py.",
  "Traced cleanup confinement through Project defaults, effective(), confine_for(), uncommitted(), Git hardening and existing filter-related test source.",
  "Rechecked dispatch confidentiality, durable issue-binding writers, final logging, tracker comments and running-job cleanup in runner/app.py, plus related project_runs, Linear, PTY, state_io and reset-generation paths.",
  "Consulted installed Git documentation for filter behavior; no Git behavior checks were executed."
 ],
 "limitations": [
  "Static plan review against existing code; proposed helpers and routes are not implemented yet.",
  "No files were edited, tests or browser checks run, or work delegated.",
  "Live registry/session data and launchd/TCC behavior were not inspected. Broader specification documents were not inspected; fidelity was assessed against the plan and repository contracts."
 ]
}
```

### Host disposition (round 3, accepted)
- REGUI-012: before any git check, every cleanup applies `effective(project, sidecar_meta)` per worktree. The broken-entry descriptor is always `confidential=True`, so every preflight git call runs confined. Regression test covers both cases.

## Plan review round 4 (2026-10-15)
- Same Codex session (resumed), cross-provider, 36 s. Result `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-prototypes-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/claudex/reg/r4/claudex-fxlz5877/result.json`.
- Verdict: **APPROVED**, 0 findings. Approval bound to plan sha256 `f3ae4fbb9dd8fcda67ab88e35b23ee548776a97c23868b394e4fe9bac8566e42`.

```json
{
 "verdict": "APPROVED",
 "summary": "The revised plan addresses the prior findings, including REGUI-012's cleanup confidentiality gap. No additional material defects were identified within the static review scope.",
 "findings": [],
 "coverage": [
  "Verified the on-disk plan SHA256: f3ae4fbb9dd8fcda67ab88e35b23ee548776a97c23868b394e4fe9bac8566e42.",
  "Checked prior dispositions against the revised lock lifetimes, acquisition order, conflict checks, cleanup preflight, ownership safeguards and confidentiality requirements.",
  "Traced runner/projects.py worktree ownership, sidecar bindings, effective confidentiality, Git confinement, cleanup and CLI callers.",
  "Rechecked runner/app.py dispatch, durable issue-binding writes, final logging, tracker comments and running-job removal.",
  "Inspected related callers in runner/project_runs.py, Linear and PTY modules, plus runner/state_io.py and relevant existing test source."
 ],
 "limitations": [
  "Approval applies to the plan; the proposed implementation and regression checks remain unverified.",
  "No files were edited, tests or browser checks run, or work delegated.",
  "Live registry/session data and launchd/TCC behavior were not inspected. Spec fidelity was assessed against the plan's acceptance criteria and inspected repository contracts."
 ]
}
```
- Plan review: 4 of 20 rounds; findings 8 → 5 → 1 → 0.
- Build (Claude, 2026-10-15): base 18a104f. 339 tests pass; headless-browser check of add/edit/baseline/remove passed. User request mid-build: also fix the stray `_playStartSound` after `</html>` (done).

## Build inspection 1 (2026-10-15)
- Fresh Codex session 01a14076-e55f-7b30-9920-8298ae6f7c5e, base 18a104f, cross-provider, 207 s. Result `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-prototypes-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/claudex/reg/i1/claudex-4asiomxq/result.json`.
- Verdict: **REVISE**, 5 findings.

```json
{
 "verdict": "REVISE",
 "summary": "The build has unresolved conflict-protection, worktree-binding, form round-trip, privacy, and failed-creation defects.",
 "findings": [
  {
   "id": "REGUI-B001",
   "severity": "high",
   "path": "runner/templates/index.html:1160",
   "evidence": "The form submits the current global registry_hash rather than the hash captured when its fields were loaded. loadProjects refreshes that global every 60 seconds (1243), without refreshing the open form. A hand edit followed by this refresh is therefore overwritten by stale form values without a 409. This can also silently undo a confidentiality promotion. After a 409, loadProjects similarly enables a second Save to overwrite the conflicting changes.",
   "fix": "Capture the registry hash when opening the form and retain it through submission. After a conflict, require an explicit reload or reconciliation of the form before accepting a newer hash."
  },
  {
   "id": "REGUI-B002",
   "severity": "medium",
   "path": "runner/projects.py:441",
   "evidence": "Path changes reject only worktrees belonging to another repository, contrary to the requirement to refuse while any worktree exists. Changing a project path from its real directory to a symlink alias passes _is_worktree_of because it resolves paths (718), and the save succeeds. Existing sidecars retain the original project_path, which load_binding compares literally (739). Subsequent dispatch, verify, terminal opening and dashboard cleanup reject those worktrees as belonging to another project.",
   "fix": "Reject path changes whenever _worktree_dirs(key) is nonempty, while holding the exclusive lifecycle lock. Cover a symlink alias of the same repository."
  },
  {
   "id": "REGUI-B003",
   "severity": "medium",
   "path": "runner/templates/index.html:1143",
   "evidence": "Opening and saving an existing entry does not preserve valid environment values. Values are flattened into newline-separated text at 1129, then split and trimmed at 1143–1145. A valid multiline value is truncated, and leading or trailing spaces are removed. Even editing only the note silently changes the environment used by later dispatch and verification.",
   "fix": "Use an editor that preserves arbitrary string values, including whitespace and newlines. Reject malformed input instead of silently dropping lines."
  },
  {
   "id": "REGUI-B004",
   "severity": "medium",
   "path": "runner/projects.py:382",
   "evidence": "_write_registry writes the complete private registry into .projects.yaml.<random>.tmp in the public repository root. The changed .gitignore ignores projects.yaml and projects.yaml.lock, but not these temporary files. A process termination before replacement leaves an unignored file containing project names, paths, notes and environment values; a subsequent git add -A can publish it. Concurrent staging can also capture it during a successful save.",
   "fix": "Ignore the registry temporary-file pattern in the tracked .gitignore, or place temporary files in an ignored directory on the same filesystem while retaining atomic replacement."
  },
  {
   "id": "REGUI-B005",
   "severity": "medium",
   "path": "runner/app.py:3026",
   "evidence": "New-folder initialization happens before save_project checks the registry hash, duplicate key or remaining entry validation. A stale-hash request creates and commits the folder, then returns 409 while leaving it unregistered. The form retains its checked initialization option, so retrying after refresh fails with 'already exists'. Validation failures produce the same abandoned-folder workflow.",
   "fix": "Check the key, duplicate and expected hash before initialization under the appropriate locks. Handle subsequent save failures explicitly: either safely roll back resources created by this request, or report successful initialization and switch the form to registering the existing repository."
  }
 ],
 "coverage": [
  "Verified the plan SHA256 and all manifested file hashes against the supplied values.",
  "Reviewed every manifested file's changes, including the plan, review log, example registry, ignore rules and added regression-test source.",
  "Inspected registry parsing, atomic writes, lifecycle and ticket locks, worktree ownership, sidecars, cleanup, baseline, history suggestions and CLI entry points.",
  "Traced dispatch, retry, durable issue-binding writers, confidentiality, final logging and tracker publication through app.py, project_runs.py and the Linear module.",
  "Inspected PTY acquisition and release, state_io.py, form serialization, token protection, escaping, dialog CSS and the start-sound relocation."
 ],
 "limitations": [
  "Static review only; no files were edited, tests or browser checks run, or work delegated. Builder-reported test results were not independently verified.",
  "Live projects.yaml, personal session stores, screenshot artifacts and launchd/TCC behavior were not inspected.",
  "Spec fidelity was assessed against the supplied plan and inspected repository contracts; broader specification documents were not inspected.",
  "The existing graph was stale and used only for navigation; findings are grounded in current source."
 ]
}
```

### Host dispositions (build inspection 1, all accepted; fixes in 4b15b3f)
- REGUI-B001: the form keeps the hash it was opened with (`f.dataset.hash`) and submits that. A 409 leaves the hash stale, so saving again keeps failing until the form is reopened. Browser check: with the form open, a hand edit plus a list refresh → the save is refused twice and the edit is kept.
- REGUI-B002: a path edit is refused whenever any worktree of the key exists. Re-adding a key with leftover worktrees requires every one to `load_binding` against the exact new path, so a symlink alias is refused. Tests cover alias edit and alias re-add.
- REGUI-B003: env is edited as a JSON object, and invalid JSON is refused in the form. Seed lines are kept verbatim (no trimming). Test: multiline and padded env values round-trip unchanged.
- REGUI-B004: `.projects.yaml.*.tmp` is gitignored. Test checks that all three registry file patterns are ignored.
- REGUI-B005: `init` moved into `save_project`, after the key, hash and duplicate checks and under the locks. A later failure removes the folder this call created. Tests cover stale hash (nothing created), duplicate (nothing created), invalid entry (rolled back) and success.
- pytest 343 passed.

## Build inspection 2 (2026-10-15)
- Fresh Codex session 01a14081-e99f-7dc1-8682-dff5c010096f, base 6aed761, cross-provider, 124 s. Result `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-prototypes-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/claudex/reg/i2/claudex-16u3inaf/result.json`.
- Verdict: **REVISE**, 1 finding (B001-B004 confirmed fixed).

```json
{
 "verdict": "REVISE",
 "summary": "REGUI-B001 through B004 are addressed. B005 fixes initialization ordering but introduces an unsafe rollback on later failures.",
 "findings": [
  {
   "id": "REGUI-B006",
   "severity": "medium",
   "path": "runner/projects.py:447",
   "evidence": "After initialization, any validation or write exception recursively deletes the new repository without checking its current contents or references. For example, a hand edit during validation can register the newly created path; the final hash check then raises RegistryConflict, preserves that edited registry, and deletes the repository it now references. Files or commits added to the folder during this interval are also deleted. The registry lock excludes neither hand edits nor filesystem writers.",
   "fix": "Preserve the initialized repository on subsequent failures and return its initialization status so the form can retry registration with init disabled. If retaining automatic rollback, restrict deletion to resources whose ownership and unchanged state can be established, and preserve/report the folder whenever concurrent use or registry references are detected."
  }
 ],
 "coverage": [
  "Verified the plan, all seven manifested file hashes, and the tracked diff hash against the supplied values.",
  "Reviewed every manifested change and the complete registry regression-test source.",
  "Checked form snapshot hashes, conflict retries, JSON environment serialization, seed serialization, and registry temporary-file ignore rules.",
  "Traced save/init validation, atomic registry writes, lifecycle locks, worktree ownership and sidecar binding readers/writers.",
  "Inspected related dispatch, durable issue-binding persistence, baseline, CLI, PTY and state_io callers."
 ],
 "limitations": [
  "Static review only; no files were edited, tests or browser checks run, or work delegated. Builder-reported results were not independently verified.",
  "Reinspection was limited to REGUI-B001 through B005 and their interactions.",
  "Live registry contents, personal session stores and browser artifacts were not inspected.",
  "Spec fidelity was assessed against the supplied plan and inspected code contracts; broader specification documents were not inspected."
 ]
}
```

### Host disposition (build inspection 2, accepted)
- REGUI-B006: no automatic rollback. After `init`, any later `ProjectError` keeps the folder. The error text names it, and the exception carries `initialized`. The API returns `initialized` with the original status (409 for conflict/busy, else 400), and the form unchecks "create new folder" so a retry registers the existing repo. Tests: an invalid entry keeps the folder and a retry without init succeeds; a hand edit during validation → RegistryConflict with the folder kept; API 400 carries `initialized`. pytest 344 passed.

## Build inspection 3 (2026-10-15)
- Fresh Codex session 01a14086-2c64-7a12-b6d0-a713352bb822, base ec74297, cross-provider, 75 s. Result `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-prototypes-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/claudex/reg/i3/claudex-70l0guho/result.json`.
- Verdict: **REVISE**, 1 finding (B006 rollback removal confirmed).

```json
{
 "verdict": "REVISE",
 "summary": "REGUI-B006's destructive rollback is removed, but post-initialization filesystem failures bypass the new recovery response.",
 "findings": [
  {
   "id": "REGUI-B007",
   "severity": "medium",
   "path": "runner/projects.py:448",
   "evidence": "Only ProjectError receives initialized metadata. After successful initialization, _write_registry can raise OSError from mkstemp, write, chmod or os.replace—for example, when the registry directory is unwritable while the project directory remains writable. This escapes both save_project and api_project_create's ProjectError handlers, producing HTTP 500 without initialized. The folder survives, but the form retains its checked initialization option; retrying then fails with 'already exists'. The added tests cover validation errors and RegistryConflict, but not operational write failures.",
   "fix": "Convert ordinary post-initialization operational exceptions into a handled error carrying initialized, preserving the repository and returning structured JSON. Cover a registry write failure and verify that retrying without initialization registers the retained repository."
  }
 ],
 "coverage": [
  "Verified all seven manifested file hashes, the plan hash and tracked diff hash against the supplied values.",
  "Reviewed every manifested change and the registry regression-test source.",
  "Traced initialization, validation, registry replacement, API exception handling and form retry behavior.",
  "Inspected related lifecycle-lock callers, worktree sidecar readers/writers, durable issue-binding persistence, CLI, PTY and state_io."
 ],
 "limitations": [
  "Static review only; no files edited, tests or browser checks run, or work delegated. Builder-reported results were not independently verified.",
  "Reinspection focused on REGUI-B006 and its interactions, not a fresh audit of the entire feature.",
  "Live registry contents, personal session stores and browser artifacts were not inspected. Spec fidelity was assessed against the supplied plan and inspected code contracts."
 ]
}
```

### Host disposition (build inspection 3, accepted)
- REGUI-B007: `_write_registry` turns any OSError (mkstemp, write, chmod, replace) into `ProjectError("cannot write …")`, and its temp file is removed in `finally`. After `init`, any exception becomes a ProjectError carrying `initialized`, so the API answers with structured JSON rather than a 500. Test: a registry write failure after init keeps the folder and reports `initialized`; a retry without init registers it. pytest 345 passed.

## Build inspection 4 (2026-10-15)
- Fresh Codex session 01a14089-7f8c-71a1-bd2b-2d3e150ed12a, base ccf5fcc, cross-provider, 68 s. Result `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-prototypes-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/claudex/reg/i4/claudex-wb2gd49n/result.json`.
- Verdict: **APPROVED**, 0 findings.

```json
{
 "verdict": "APPROVED",
 "summary": "REGUI-B007 is fixed: post-initialization save failures retain the repository and return initialized metadata through the API to the form. No material regressions were identified within the requested scope.",
 "findings": [],
 "coverage": [
  "Verified all four manifested file hashes, including the plan, and the tracked diff hash.",
  "Reviewed manifested changes and regression-test source covering registry-write failure, repository retention and retry.",
  "Traced initialization, validation, registry replacement, exception handling, API responses and form recovery.",
  "Inspected related registry-removal callers, lifecycle locks, dispatch, worktree sidecar and durable-binding writers, baseline, CLI and PTY paths."
 ],
 "limitations": [
  "Static review only; no files edited, tests or browser checks run, or work delegated. Builder-reported results were not independently verified.",
  "Reinspection focused on B007 and its interactions, rather than a fresh audit of the entire feature.",
  "Live registry and session data were not inspected. Spec fidelity was assessed against the supplied plan and inspected repository contracts."
 ]
}
```
- Summary: plan review 4 rounds (8 → 5 → 1 → 0); build inspections 4 of 20 (5 → 1 → 1 → 0), all cross-provider. Final proof: pytest 345 passed; headless-browser checks of add/edit/baseline/remove and of the stale-form 409 passed.
