---
status: in-progress
created: 2026-10-15
---

# Simpler "add project" in the dashboard

## Goal
Adding a project takes one folder and at most one choice. The user picks a folder (from session history, by dragging it onto the dialog, or by pasting its path); the key is the folder name; the only option is "confidential". Everything else (how to test, data folders, env) the agent works out inside the folder. The Projects panel stops showing notes, and "+ Project" looks like the agent selector buttons.

## Acceptance criteria
- [ ] The Projects panel shows no note text under any project; `note` stays in `projects.yaml` and the backend keeps supporting it
- [ ] "+ Project" is styled like the active agent-selector button (accent colour, same size and padding as `.agent-btn.active`)
- [ ] The add dialog has exactly: a path field with "From history" and a drop zone, a read-only key preview (the folder name), one "Confidential" checkbox (default on), Cancel and Save
- [ ] Dragging a folder from Finder onto the dialog fills the path only when the search finished and found exactly one match; several matches, or any result from a search that hit its time limit, are listed for the user to pick; none asks for a pasted path
- [ ] The key is the folder name made valid for `_IDENT` (invalid characters → `-`, leading non-alphanumerics dropped; an empty result such as a Unicode-only or punctuation-only name falls back to `project`); a clash with an existing key appends `-2`, `-3`, …
- [ ] A new project is saved as `{path, confidential, no_push: true}`; `verify`, `kind`, `env`, `seed` are not asked for
- [ ] A project without `verify` dispatches normally: post-run skips verify, the badge reads `no check` (unless a stronger badge applies), and the agent prompt tells the agent to find and run the project's own tests
- [ ] Baseline is hidden for a project without `verify`; the CLI `verify` and the baseline route refuse it with a clear error
- [ ] A new project's path must be a repository root (its canonical path equals `git rev-parse --show-toplevel`). A path that does not exist, or an existing empty folder that is not a repo root (including one inside another repo), is `git init`ed with an empty initial commit; a non-empty folder that is not a repo root is refused ("run git init and commit first"); the "create new folder" checkbox is gone
- [ ] Edit shows the path read-only and only the Confidential checkbox; saving changes only `confidential` in the stored entry, every other field (including empty or null ones) unchanged
- [ ] Existing projects with `verify`, `env`, `seed` behave exactly as before

## Decisions (user, 2026-10-15)
1. Drag and drop: the browser exposes only the dropped folder's name and its entries, not its path. The server locates it by name + entry names among session-history repo roots and a bounded scan under the home folder; one match fills the path, several are offered, none asks for a paste.
2. `verify` becomes optional. Without it, post-run verify is skipped (badge `no check`) and the agent is told to run the project's own tests.
3. Not-a-repo folder: missing or empty → `git init` + empty commit; non-empty → refused.
4. Notes: hidden from the UI, kept in the file.
5. Builder Claude, plan review and build inspection by fresh Codex sessions (CLI default model, ≤ 20 rounds each), as before.

## Approach

### Optional verify (runner/projects.py, runner/project_runs.py)
- [ ] `_parse_project`: `verify` optional; when present it must be a non-empty string; `Project.verify` defaults to `""`
- [ ] `run_verify` raises `ProjectError("<key>: no verify command configured")` when `project.verify` is empty (CLI `verify` and baseline surface it)
- [ ] `post_run`: when `project.verify` is empty, skip only the `run_verify` call; the binding re-check, uncommitted re-check, seed-history scan, shortstat and closing fingerprint still run; the badge order stays (seed committed > main checkout unchecked/changed > error > uncommitted changes) and ends in `no check` instead of the verify status
- [ ] `project_prompt`: with no `verify`, add "No check command is configured for this project: find and run its own tests before you finish, and report the result."

### Locate a dropped folder (runner/projects.py, runner/app.py)
- [ ] `locate_folder(name, entries, budget_s=3)`: no git calls. Candidates are directories named exactly `name`, from (a) the recorded session cwds and their ancestors (string ops on the cwd values read from Claude JSONLs and the Codex DB, sharing the deadline), and (b) a breadth-first scan of `~/Documents`, `~/code`, `~/Projects`, `~/Developer`, `~/src`, `~/repos`, `~/work` and the home folder itself, at most 4 levels deep. Skips are applied to canonical paths and symlinked directories are not followed: hidden dirs, `~/Library`, `~/Desktop`, `~/Downloads`, `node_modules`, `.venv`, `WORKTREE_ROOT`, temp roots. A candidate matches when its entry names include every name in `entries` (up to 50 sent; an empty `entries` matches only an empty directory). One deadline covers both phases; returns `{matches, complete}` with `complete=False` when the deadline or the 20-result cap cut the search short; paths `~`-abbreviated, newest mtime first
- [ ] `POST /api/projects/locate` `{name, entries}` → `{matches: [...], complete: bool}`; `name` must be a single path component (no `/`, not `.`/`..`)

### Save with automatic init (runner/projects.py)
- [ ] `save_project(create=True)` replaces the `init` flag: after the key/hash/duplicate checks, if the canonical path is not its own repo root (`git rev-parse --show-toplevel` missing or different, so a folder inside another repo counts as "not a repo root"), then a missing path (parent exists) or an existing empty directory is initialised (`git init` + empty commit); a non-empty one is refused before anything is written. The B006/B007 rule holds: once initialised, a later failure keeps the folder and reports `initialized`
- [ ] `init_repo` accepts an existing empty directory; on its own failure it removes only what it created (the whole folder if it made it, else just `.git`)

### Confidential-only edit and baseline guard (runner/projects.py, runner/app.py)
- [ ] `set_confidential(key, value, expected_hash)`: exclusive project lock (non-blocking) → registry lock → hash check → set only `confidential` on the stored raw entry → re-parse the whole entry with `_parse_project` → final hash re-check and atomic write. No `_clean_entry`, so empty/null fields survive. `PATCH /api/projects/<key>` `{confidential, registry_hash}` calls it
- [ ] Baseline route: refuse synchronously (400, no state change, no thread) when the project has no `verify`; the worker re-checks under its shared project lock before creating a worktree. Baseline no longer deletes its one-off lock file at all (it holds only the shared lock, so another holder could share the pathname); the files are tiny and go when the project is removed. `drop_ticket_lock` stays only in save's seed check, which runs under the exclusive project lock (every ticket-lock holder takes the shared project lock first) and only after it created and removed its own worktree

### UI (runner/templates/index.html)
- [ ] Remove the note line from the panel
- [ ] "+ Project": a button with the `.agent-btn.active` look (class reuse, single button with full border radius)
- [ ] Add dialog: path input + "From history" select + a drop zone ("Drop a folder here"); key preview (read-only text: the derived key); "Confidential" checkbox; Cancel / Save. Drop handler: `dataTransfer.items[0].webkitGetAsEntry()`; a non-directory is refused; read its first 50 entry names, call `/api/projects/locate`; fill only on `complete` + one match, otherwise offer the list (labelled "search incomplete" when `complete` is false) or ask to paste
- [ ] Key derivation in the form (shared helper): folder name → `_IDENT`-valid key, suffix on clash with keys already in the panel; the server still validates
- [ ] Edit dialog: path read-only, Confidential checkbox only; sends `PATCH {confidential, registry_hash}` with the hash captured when it opened
- [ ] Baseline button only for projects whose entry has `verify`

## Non-goals
- Auto-detecting test commands (the agent finds them)
- Editing env, seed, verify, kind or note from the UI (hand-edit `projects.yaml`)
- Resolving drops without a match (paste the path instead)

## Assumptions and sources
- Browsers give a dropped directory's name and entries (`webkitGetAsEntry`, `createReader`) but never its absolute path
- Label matching is case-sensitive on the key after `project:` (`runner/project_runs.py:36`), so a key keeps the folder name's case
- The runner runs under launchd with access to `~/Documents`; the scan avoids `~/Library`, `~/Desktop` and `~/Downloads` to keep clear of TCC prompts

## Verification
- Proof: `.venv/bin/python -m pytest tests/` → all pass
- Manual: headless Chrome against the live runner: the panel has no note text; "+ Project" screenshot matches the agent buttons; add a throwaway repo from history and by a simulated drop (synthetic `DataTransfer` cannot carry a real directory, so the drop handler is driven with a stub entry and the locate API is called for real); add an empty folder (auto init); a non-empty non-repo folder is refused; Edit toggles confidential and keeps the other fields; remove both

## Progress Checklist
- [ ] Test: `_parse_project` accepts a missing `verify`, rejects an empty or non-string one
- [ ] Test: dispatch of a project without `verify` ends `review` with badge `no check`, shortstat recorded, closing check run; the prompt carries the run-your-own-tests rule
- [ ] Test: `run_verify`, CLI `verify` and the baseline route refuse a project without `verify`
- [ ] Test: `locate_folder` finds a unique match by name + entries, returns several when entries do not disambiguate, honours the depth/skip rules (Desktop, Downloads, Library, symlinked dirs), matches an empty drop only to an empty dir, reports `complete=False` when the deadline is hit, and rejects a `name` with `/` or `..`
- [ ] Test: create with a missing path and with an existing empty dir auto-inits, also when that dir sits inside another repo; a non-empty non-repo dir, and a non-empty subfolder of another repo, are refused with the file unchanged; a failure after init keeps the folder and reports `initialized`
- [ ] Test: `set_confidential` keeps every other field of the stored entry, including `note: ""`, `env: {}`, `seed: []` and a null field; refused while the project is busy; stale hash → conflict
- [ ] Test: baseline of a project without `verify` is refused synchronously (no thread, no state, no lock file)
- [ ] Test: a baseline whose id collides with a held ticket lock fails without unlinking that lock file, and the holder's lock still excludes a second acquirer
- [ ] Test: the locate route returns `complete` true for a finished search and false when the deadline is hit
- [ ] Test: key derivation: ASCII name kept, invalid characters replaced, Unicode-only and punctuation-only names fall back to `project`, clashes get `-2`
- [ ] Implement optional verify
- [ ] Implement `locate_folder` and its route
- [ ] Implement automatic init in `save_project` / `init_repo`
- [ ] Implement the UI changes
- [ ] Proof: `.venv/bin/python -m pytest tests/` passes
- [ ] Manual browser check as above; screenshots captured
- [ ] Fresh cross-provider (Codex) build inspection returns no unresolved material findings
