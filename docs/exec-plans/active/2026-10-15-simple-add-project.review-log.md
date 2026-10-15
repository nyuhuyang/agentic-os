# Review log — simpler "add project"

- Started 2026-10-15 from a /claudex-loop request with two screenshots. Host Claude Code: planner and builder. Plan reviewer and build inspector: fresh Codex CLI sessions (codex-cli 0.162.0, CLI default model). Fallback: same-provider-on-unavailable. Up to 20 rounds each.
- Authorization: the request directs the change ("删", "加大", "不要给这么多"), so the build is authorized once the plan review approves.
- User decisions (AskUserQuestion, all recommended): drop located by name + entries; verify optional (`no check`); missing/empty folder auto-init, non-empty non-repo refused; notes hidden in UI, kept in file.
- Budget: same as the previous plan (default model, ≤ 20 rounds).

## Plan review round 1 (2026-10-15)
- Codex session 01a140a1-2e3a-7133-ac6f-b51d6b54ddf8, cross-provider, 216 s. Result `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-prototypes-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/claudex/simple/r1/claudex-ktpdyuwg/result.json`.
- Verdict: **REVISE**, 7 findings.

```json
{
 "verdict": "REVISE",
 "summary": "The plan needs fixes for repository identity, folder lookup, key generation, baseline refusal, and edit preservation.",
 "findings": [
  {
   "id": "SAP-001",
   "severity": "high",
   "path": "docs/exec-plans/active/2026-10-15-simple-add-project.md:44",
   "evidence": "The automatic-init decision must distinguish a repository root from a directory inside another repository. Current runner/projects.py:239 checks only `git rev-parse --git-dir`, which succeeds inside a parent checkout. Selecting an existing empty child folder can therefore skip initialization; create_worktree at runner/projects.py:848-850 then creates a worktree of the entire parent repository. A non-empty child can likewise bypass the promised refusal.",
   "fix": "Require the canonical selected path to equal `git rev-parse --show-toplevel`. Handle missing or empty non-root directories according to the initialization policy, and refuse non-empty non-root directories. Cover both cases inside an existing parent repository."
  },
  {
   "id": "SAP-002",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-15-simple-add-project.md:40",
   "evidence": "The scan includes the home directory, but its skip list omits Desktop and Downloads. Breadth-first traversal will therefore enter both, contradicting the explicit promise at line 63 and potentially encountering the protected locations the design intends to avoid.",
   "fix": "Explicitly prune Desktop and Downloads before enumerating their contents. Apply scan exclusions to canonical paths so directory symlinks cannot bypass them."
  },
  {
   "id": "SAP-003",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-15-simple-add-project.md:40",
   "evidence": "The locator can stop after three seconds, yet returns only matches, and the UI automatically fills a singleton result. If two same-named clones have matching entries and the deadline expires after finding the first, an incomplete search appears unique and can select the wrong repository.",
   "fix": "Return whether lookup was incomplete. Require explicit path selection or confirmation when a partial search returns one candidate; do not treat that result as proven unique."
  },
  {
   "id": "SAP-004",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-15-simple-add-project.md:51",
   "evidence": "The specified sanitizer produces an empty key for valid folder names containing no ASCII alphanumerics, such as `研究` or `---`. runner/projects.py:310-312 rejects that key, and the new read-only preview removes the user's ability to correct it.",
   "fix": "Define a non-empty ASCII fallback, then apply collision suffixing. Cover Unicode-only names, punctuation-only names, and trailing path separators."
  },
  {
   "id": "SAP-005",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-15-simple-add-project.md:35",
   "evidence": "Adding only the prescribed run_verify guard does not make the baseline route refuse an unconfigured project. runner/app.py:3084-3091 returns success and starts a worker before inspecting the project; that worker creates a worktree before calling run_verify. The resulting exception also bypasses drop_ticket_lock at line 3075, leaving a one-off lock file.",
   "fix": "Reject missing verify synchronously before changing baseline state or starting the worker. Recheck under the worker's project lock before creating a worktree, and ensure transient ticket-lock cleanup runs on failure."
  },
  {
   "id": "SAP-006",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-15-simple-add-project.md:40",
   "evidence": "Reusing session_dirs does not provide a bounded lookup. runner/projects.py:1287-1327 scans all session files and resolves all recorded working directories before applying its result limit. Each uncached resolution can spend ten seconds in Git at line 1269, so a deadline checked only by the subsequent directory scan cannot enforce the advertised three-second budget.",
   "fix": "Propagate a shared deadline through history discovery and repository resolution, cap subprocess timeouts to the remaining budget, and report incomplete lookup when it expires."
  },
  {
   "id": "SAP-007",
   "severity": "low",
   "path": "docs/exec-plans/active/2026-10-15-simple-add-project.md:52",
   "evidence": "Submitting `{...entry, confidential}` does not preserve every other stored field through the existing backend. save_project calls _clean_entry at runner/projects.py:427, which removes empty strings, empty mappings/lists, and null values. A valid entry containing `note: \"\"`, `env: {}`, or `seed: []` loses those fields when Confidential alone is changed.",
   "fix": "Preserve untouched field presence and values on edit, preferably by updating confidential in the locked stored entry. Include explicit empty and null optional fields in preservation checks."
  }
 ],
 "coverage": [
  "Verified the on-disk plan SHA256 matches ba32d431f7b02ded537f0f8c73a8d9381416e2dcd5dbb292cbe8e9d5a4292089.",
  "Inspected targeted registry parsing, writes, locking, initialization, worktree ownership, verification, history discovery, dispatch, prompts, post-run checks, baseline routes, and dashboard form code.",
  "Traced related consumers and shared-state writers in runner/state_io.py, runner/reset_gen.py, runner/modules/pty/__init__.py, runner/modules/linear/__init__.py, and runner/modules/linear/local_tracker.py.",
  "Read relevant existing registry, dispatch, and verification test source, projects.example.yaml, SPEC.md sections, and the preceding multi-project plan."
 ],
 "limitations": [
  "Static review of a proposed implementation; the inspected code still requires verify.",
  "No tests, browser checks, or live API checks were run. No files were edited and no work was delegated.",
  "The existing graph snapshot is dated 2026-10-14 and its query was truncated; findings rely on inspected source."
 ]
}
```

### Host dispositions (round 1, all accepted)
- SAP-001: a new path must be its own repo root (its canonical path equals `--show-toplevel`). A missing or empty folder that is not a root, including one inside another repo, is initialised; a non-empty one is refused. Tests cover both cases inside a parent repo.
- SAP-002: Desktop, Downloads and Library are pruned explicitly. Skips apply to canonical paths, and symlinked dirs are not followed.
- SAP-003: locate returns `complete`. The UI fills the path only when the search is complete and found exactly one match; otherwise it shows a list labelled "search incomplete".
- SAP-004: an empty sanitized key falls back to `project`, then gets a clash suffix. Tests added.
- SAP-005: baseline refuses a project without `verify` synchronously, re-checks under the shared lock, and runs `drop_ticket_lock` in `finally`.
- SAP-006: locate makes no git calls. It works by string ops on session cwds and their ancestors plus a directory scan, under one shared deadline.
- SAP-007: the edit becomes `PATCH {confidential}` → `set_confidential`, which changes only that field on the stored raw entry (no `_clean_entry`). The test covers empty and null fields.

## Plan review round 2 (2026-10-15)
- Same Codex session (resumed), cross-provider, 89 s. Result `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-prototypes-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/claudex/simple/r2/claudex-s3qvrhsh/result.json`.
- Verdict: **REVISE**, 2 findings.

```json
{
 "verdict": "REVISE",
 "summary": "The seven prior findings are addressed in substance. Two integration defects remain in the revised API contract and baseline lock cleanup.",
 "findings": [
  {
   "id": "SAP-008",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-15-simple-add-project.md:41",
   "evidence": "The locator now returns `{matches, complete}`, and the UI requires `complete` before automatically filling a unique result, but the HTTP response contract still specifies only `{matches: [...]}`. A route implemented to that contract loses the completeness flag: even a completed singleton search cannot trigger the intended automatic fill.",
   "fix": "Specify `{matches, complete}` in the HTTP response contract and verify both complete and truncated searches through the route, including the UI singleton behavior."
  },
  {
   "id": "SAP-009",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-15-simple-add-project.md:49",
   "evidence": "The unconditional requirement to remove the ticket lock in `finally` is unsafe when acquisition fails. runner/projects.py:646-659 can raise TicketLocked because another CLI operation or terminal holds the lock, while drop_ticket_lock at line 541 simply unlinks its pathname. On a colliding BASELINE identifier, cleanup would unlink another operation's locked file; a subsequent caller could create a new inode and acquire a second lock for the same ticket. BASELINE identifiers are accepted by the public CLI, and existing tests already cover collisions with pre-existing baseline worktrees.",
   "fix": "Make cleanup conditional on ownership and successful disposal of this invocation's transient resources. Never unlink on failed acquisition or a pre-existing-ticket collision; retain such lock files for cleanup under an exclusive project lifecycle lock. Add a contention check proving a refused baseline cannot invalidate another holder's lock."
  }
 ],
 "coverage": [
  "Verified the plan SHA256 matches 91ca01c5ff2d6a7f9fb2ffb85441500cfb2fd022737950e476cba3473c25e4b4.",
  "Compared all seven prior findings against the revised requirements, approach, and proposed checks without reopening their resolved design decisions.",
  "Inspected registry parsing and mutation, initialization, project and ticket locking, CLI callers, post-run checks, baseline routes, and dashboard history handling.",
  "Traced related terminal and Linear dispatch consumers, durable binding writes, local tracker transactions, and runner/state_io.py.",
  "Read relevant existing test source, registry schema documentation, and SPEC.md requirements."
 ],
 "limitations": [
  "Static plan review; the proposed implementation is not present in the inspected source.",
  "No tests or live browser/API checks were run. No files were edited and no work was delegated."
 ]
}
```

### Host dispositions (round 2, both accepted)
- SAP-008: the route contract is now `{matches, complete}`; a route test covers a complete and a truncated search.
- SAP-009: baseline never deletes its lock file. `drop_ticket_lock` stays only in save's seed check, which holds the exclusive project lock and runs only after its own create+remove succeeds. A contention test proves a colliding baseline leaves the holder's lock intact.

## Plan review round 3 (2026-10-15)
- Same Codex session (resumed), cross-provider, 36 s. Result `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-prototypes-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/claudex/simple/r3/claudex-chmk8q18/result.json`.
- Verdict: **APPROVED**, 0 findings; bound to plan sha256 `891572e4d6a0057b3802c176e6508385ca7de500eedcf24a4b942eeaaba4074d`. Plan review: 3 rounds (7 → 2 → 0).
- Build (Claude, 2026-10-15): base 52da675. 360 tests pass; headless-browser check passed (see plan). Key derivation lives in `projects.derive_key` (the server also derives it when the POST has no key); the form mirrors it for the preview.

## Build inspection 1 (2026-10-15)
- Fresh Codex session 01a140bc-e138-7743-84d3-403d574a7e35, base 52da675, cross-provider, 181 s. Result `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-prototypes-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/claudex/simple/i1/claudex-94c45xuq/result.json`.
- Verdict: **REVISE**, 4 findings.

```json
{
 "verdict": "REVISE",
 "summary": "Four defects remain: confidentiality edits can affect another project, folder lookup does not enforce its bounds or exclusions consistently, and stale lookup responses can overwrite the selected path.",
 "findings": [
  {
   "id": "SAP-B001",
   "severity": "medium",
   "path": "runner/projects.py:650",
   "evidence": "set_confidential mutates the mapping returned by yaml.safe_load in place. A valid registry containing `alpha: &shared {path: /repo, confidential: true}` and `beta: *shared` gives both keys the same mapping. PATCHing alpha to false also changes beta, despite holding only alpha's lifecycle lock. Future unbound beta tickets then lose sandbox and tracker-comment protection through _ticket_confidential.",
   "fix": "Copy the selected entry and replace only doc['projects'][key] before changing confidential. Preserve all other entries and add coverage for YAML aliases."
  },
  {
   "id": "SAP-B002",
   "severity": "medium",
   "path": "runner/projects.py:688",
   "evidence": "The three-second budget and 20-result cap do not cover the whole locator. The Codex SELECT and every history-candidate consideration run without deadline or result-limit checks. SQLite uses its default lock timeout, which alone can exceed three seconds. Directory scans also materialize all children before checking time again. Large or locked history and large directories therefore keep the locate request running beyond the promised budget.",
   "fix": "Propagate the remaining budget through history reads and SQL execution, check time and match limits while processing candidates and directory entries, and stop all phases when either bound is reached. Return complete=false whenever bounded work is abandoned."
  },
  {
   "id": "SAP-B003",
   "severity": "medium",
   "path": "runner/projects.py:677",
   "evidence": "History candidates bypass the scan's hidden-directory and node_modules exclusions: consider() checks only skip_real and whether the final component is a symlink. A recorded cwd such as ~/.archive/demo or ~/code/app/node_modules/demo can therefore be returned and automatically selected as a complete singleton. Symlinked ancestors and symlinked initial scan roots are also traversed, contrary to the plan's exclusions.",
   "fix": "Apply one eligibility check to history candidates, initial roots, and traversal children. Check excluded ancestors and reject symlink traversal consistently before enumerating a candidate."
  },
  {
   "id": "SAP-B004",
   "severity": "medium",
   "path": "runner/templates/index.html:1213",
   "evidence": "_projectHandleDrop applies its asynchronous result to the shared form without checking whether the selection or dialog changed. Drop A, then paste or drop B while A's lookup is pending: a later response for A overwrites B. The same response can populate a newly reopened Add dialog after cancellation, allowing Save to register the wrong repository.",
   "fix": "Associate lookup requests with a form generation and selection version. Invalidate pending results on another drop, manual path input, dialog close, or reopen; apply responses only while their originating selection remains current."
  }
 ],
 "coverage": [
  "Verified all nine manifest file hashes, including the supplied plan SHA256.",
  "Inspected every changed file and the diff against base 52da6751087c953169eb741293799dfa10ae80ae.",
  "Traced registry parsing and writes, automatic initialization, worktree validation, optional verification, prompts, post-run checks, baseline state, CLI guards, and dashboard form behavior.",
  "Traced related locking, confidentiality, bindings, and tracker consumers in runner/state_io.py, runner/modules/pty/__init__.py, runner/modules/linear/__init__.py, runner/modules/linear/local_tracker.py, and runner/reset_gen.py.",
  "Read affected test source, relevant SPEC.md sections, and projects.example.yaml."
 ],
 "limitations": [
  "Static review only. No files were edited, tests or browser checks run, or work delegated.",
  "The plan's reported test and browser results were not independently verified.",
  "The graphify snapshot is stale and its query was truncated; findings rely on current source."
 ]
}
```

### Host dispositions (build inspection 1, all accepted)
- SAP-B001: `set_confidential` replaces `doc["projects"][key]` with a copy, so a YAML alias shared with another project keeps that project's value. Alias test added.
- SAP-B002: one deadline and one result cap now cover every locate phase: each JSONL file, the Codex query (sqlite `timeout` set to the remaining budget, plus a progress handler that aborts at the deadline), each history candidate, and each scandir entry. Any abandoned work returns `complete: false`. A test with slow history reads checks it stops within the budget.
- SAP-B003: one `eligible()` rule (no hidden or skipped component, no symlink anywhere on the path, not under a skipped root) applies to history candidates, scan roots and scan children. Test: a hidden history cwd, a node_modules cwd and a symlinked scan root all yield no match.
- SAP-B004: `_projectSelectionGen` is bumped on open, close, typed path, history pick and every drop; a locate result applies only while its generation is current and the dialog is open. Browser check with a delayed stub locate: a typed path survives a stale result, a reopened dialog stays empty, and the current drop applies.
- pytest 363 passed.

## Build inspection 2 (2026-10-15)
- Fresh Codex session 01a140c3-9efe-7193-8095-74224ea2c686, base 1798e62, cross-provider, 100 s. Result `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-prototypes-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/claudex/simple/i2/claudex-kta6__eb/result.json`.
- Verdict: **REVISE**, 2 findings (B001, B003 confirmed fixed; B002 partial).

```json
{
 "verdict": "REVISE",
 "summary": "SAP-B001 and SAP-B003 are fixed. SAP-B002 remains partially unresolved. SAP-B004 protects path selection, but a stale callback can still overwrite dialog status.",
 "findings": [
  {
   "id": "SAP-B002",
   "severity": "medium",
   "path": "runner/projects.py:695",
   "evidence": "Candidate matching still materializes every entry with set(os.listdir(d)), without deadline checks. History reading likewise calls _first_cwd, which reads up to 200 arbitrarily long JSONL lines without observing the deadline. A large candidate directory or session file can therefore exceed the three-second budget. If the final depth-limited scan entry overruns inside consider(), the loops can finish without another stop() call and return complete=true.",
   "fix": "Make candidate enumeration and history parsing deadline-aware, using incremental reads and bounded parsing. Do not cache incomplete history reads as completed results. Check the deadline before returning and report complete=false whenever bounded work remains."
  },
  {
   "id": "SAP-B005",
   "severity": "low",
   "path": "runner/templates/index.html:1228",
   "evidence": "After awaiting readEntries(), the handler writes 'Looking for…' before checking current(). Drop A, cancel, and reopen the dialog before A's directory callback finishes: A overwrites the reopened dialog's status, then returns without starting a lookup. It can similarly replace a newer validation error with a permanent misleading search message.",
   "fix": "Move the current() check immediately after the readEntries() await, before any DOM mutation."
  }
 ],
 "coverage": [
  "Verified all five manifest file hashes, including the supplied plan SHA256, and inspected the diff against 1798e6220e2433c0b48f803fc76bf6e31d47d97c.",
  "Read the plan, review log, changed implementation sections, and affected test source.",
  "Traced registry parsing, alias handling, lifecycle locks, atomic writes, save/remove writers, history readers, shared caches, locate routes, and dialog selection handling.",
  "Checked related confidentiality consumers and locking in app.py, project_runs.py, state_io.py, the PTY module, and the Linear module."
 ],
 "limitations": [
  "Static review only; no files edited, tests or browser checks run, or work delegated.",
  "Reported test and browser results were not independently verified.",
  "Review covered the four requested fixes and their interactions, rather than repeating the full implementation audit.",
  "The graphify snapshot predates these changes and its query was truncated; conclusions rely on current source."
 ]
}
```

### Host dispositions (build inspection 2, both accepted)
- SAP-B002: `consider()` reads entries one at a time and stops once every wanted name is seen, checking the deadline per entry. An empty drop stops at the first entry. `_first_cwd` reads at most 256 KB, a fixed rule, so caching stays deterministic. `locate_folder` checks the deadline again before returning. Tests cover a slow candidate listing (stops within budget, complete=false) and the bounded head read.
- SAP-B005: the `current()` check moved to directly after the `readEntries` await, before any DOM change.
- pytest 365 passed.
