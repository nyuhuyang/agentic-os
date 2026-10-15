---
status: in-progress
created: 2026-10-15
---

# Project registry in the dashboard

## Goal
The user adds, edits and removes AgenticOS projects from the dashboard's Projects panel instead of hand-editing `projects.yaml`. "Adding" covers three sources: a directory found in Claude/Codex session history, an existing git repo typed by path, and a brand-new folder that the dashboard creates and `git init`s. Each project can run its verify baseline from the panel.

## Acceptance criteria
- [x] From the Projects panel, a project added through the form (either source: history pick or typed path) appears in the panel and in `projects.yaml` without a runner restart, and a `project:<key>` ticket dispatches into it
- [x] A typed path that does not exist can be created as a new folder with `git init` and an empty initial commit, then registered
- [x] The "from history" list shows git repo roots seen in Claude/Codex sessions that are not yet registered; picking one pre-fills the form
- [x] Edit changes any field except the key; the change is visible to the next dispatch without a restart. Changing `path`, `confidential` or `seed` is refused while the project is busy (a run, baseline, CLI worktree command or open project tab holds it); changing `path` is also refused while any worktree of the key exists
- [x] Every project shown in the panel, including one whose entry fails to parse, can be removed from the panel; removal deletes the registry entry only (project files untouched)
- [x] Remove with leftover worktrees lists them; "Clean up and remove" removes each worktree and its `agent/<id>` branch only when it has no uncommitted changes and no commits beyond its base, and otherwise refuses naming the worktrees that hold work; a running job for the key always refuses
- [x] Every save is validated with the same rules dispatch uses: key rule (`_IDENT`), `_parse_project`, and, when seeds or path change, a throwaway fresh worktree that runs the dispatch seed checks (copy, collision, committed-`.gitignore` rule) and is then removed; an invalid entry is refused with the error text and `projects.yaml` stays byte-identical
- [x] A hand edit of `projects.yaml` between the form's load and its save makes the save fail with 409 instead of overwriting it (limitation: an editor that saves in the final instant between the last hash re-check and `os.replace` can still be overwritten; editors do not take the registry lock)
- [x] "Baseline" runs verify in a newly created seeded worktree with its own fresh id, shows pass/fail, exit code, duration and the output tail, and removes only what it created
- [x] Each project's `note` text is shown in the panel and editable in the form
- [x] No project names, paths or notes enter tracked files (the repo is public); `git grep` for the registered keys stays empty

## Decisions (user, 2026-10-15)
1. Scope: add + edit + remove, all in this one build (no phasing). Every project in the panel is removable, including broken entries. Leftover worktrees can be cleaned up from the remove dialog when they hold no work.
2. Sources: session history suggestions and manual path, for both existing repos and new folders.
3. Comments in `projects.yaml` become a new optional `note` field (free text, shown and editable in the UI). The local file's existing comments are migrated by hand once (it is gitignored, so no migration code). Writes use the installed PyYAML; no new dependency.
4. Plan review: Codex, CLI default model, up to 20 rounds.

## Approach

### Project lifecycle lock (runner/projects.py, used by app.py and the PTY module)
- [x] `project_lock(key, exclusive, blocking)`: `fcntl.flock` on `WORKTREE_ROOT/.project-locks/<key>.lock` (dir 0700, file 0600, never deleted so the inode stays stable; outside every key dir, and `_IDENT` keys cannot start with `.`). Shared holders, blocking: `_run_project_ticket` for its entire body, from before its registry read through tracker comments, final state updates and running-job removal; the CLI `worktree`, `verify` and `cleanup` subcommands; baseline and save-time seed checks; every project tab (main-path shell, worktree or resume) for its lifetime (fd closed when the tab closes; broader than "worktree terminal": a project with an open tab cannot be removed). Exclusive holders, non-blocking (busy → refuse with "project busy"): remove, and edits that change `path`, `confidential` or `seed`. Edits of `kind`, `verify`, `verify_timeout_s`, `env`, `no_push` and `note` take no project lock
- [x] One lock order everywhere: project lock → registry lock (`state_io.file_lock(REGISTRY_PATH)`) → ticket locks (sorted). Work done inside an exclusive holder (save-time seed check, cleanup) runs under that exclusive lock and never re-acquires or downgrades the project lock; the shared-lock acquisition helpers take an `already_held` flag that skips acquisition
- [x] After acquiring a shared lock, dispatch re-reads the registry; a removed project fails the run with "unknown project" before any worktree is created

### Registry writes (runner/projects.py)
- [x] Add `note` to `_FIELDS`; it must be a string; `Project` gains `note: str = ""`
- [x] `registry_snapshot()`: one byte read returning `(entries, hash)`; `GET /api/projects` builds both its entries and `registry_hash` from that one read
- [x] `save_project(key, entry, expected_hash, *, create=False)`: validate `key` against `_IDENT` first; under `state_io.file_lock(REGISTRY_PATH)` (and the exclusive project lock when required, see above) re-read, refuse with `RegistryConflict` on a hash mismatch, refuse a duplicate key on create or an unknown key on edit, refuse a `path` change while any worktree of the key exists, validate with `_parse_project`; when seeds or path change, create a throwaway worktree with a fresh id (`REGCHECK-<unix-ms>`), require `reused: False`, then `remove_worktree` it. Re-check the hash immediately before writing; write the whole mapping with `yaml.safe_dump(sort_keys=False)` to a temp file and `os.replace` it. The key is immutable (worktrees, sidecars and bindings are keyed by it)
- [x] `remove_project(key, expected_hash, cleanup=False)`: works on the raw YAML entry, so a key whose entry fails to parse is removable. Takes the exclusive project lock (non-blocking) and the registry lock; refuses on a hash mismatch, and re-checks the hash immediately before `os.replace` (on a late conflict the editor's file is kept and the response reports any cleanup already done). Lists only directories under `WORKTREE_ROOT/<key>` except `.meta/` (lock files are not worktrees). Without `cleanup`, any worktree refuses with the list. With `cleanup`: acquire every worktree's ticket lock in sorted order, preflight all of them (it is a worktree of this project, its sidecar binding loads, `uncommitted()` is empty, `git rev-list <base>..agent/<id>` is empty) and refuse with the full list of failures before deleting anything; then remove each via `remove_worktree` while still holding all locks. A deletion error after a clean preflight is reported as an operational failure naming what was and was not removed, and the registry entry is kept. Before any git check on a worktree (preflight included), the descriptor is replaced by `effective(project, sidecar_meta)` so a sidecar-confidential worktree stays sandboxed. For a broken entry, cleanup uses a minimal descriptor built from the raw `path` only (no `verify`/`seed`/`env` validation) and always `confidential=True`, so every git call runs confined: ownership is still checked (`_is_worktree_of`, sidecar binding `project_path` match); when the raw path is missing or not a git repo, ownership is unverifiable and cleanup refuses, naming the worktrees
- [x] Durable issue bindings for a removed key stay in `state/issue_bindings.json`; a later retry of such a ticket fails with the existing "unknown project" / binding-mismatch errors (documented, not migrated)
- [x] Paths are stored as typed (`~/…` kept); a path inside `WORKTREE_ROOT` is refused
- [x] Every other field written by the form passes the same type rules as hand-written YAML (env string map, seed list, positive int timeout, bool flags)

### New folder (runner/projects.py)
- [x] `init_repo(path)`: only when the path does not exist and its parent does; `mkdir`, `git init`, `git commit --allow-empty -m "Initial commit"` with the hardened git argv; refuses anything else

### History suggestions (runner/projects.py)
- [x] `session_dirs()`: distinct `cwd` values from Claude session JSONLs (first `user` line per file, via the existing per-file stat cache) and from the Codex `threads` table (read-only), mapped to `git rev-parse --show-toplevel`; drop non-repos, paths under `WORKTREE_ROOT`, and roots already registered; return `[{path, last_used, sessions}]`, newest first, capped at 50. A reader failure yields an empty list, never an error

### API (runner/app.py, all token-protected like every other non-GET route)
- [x] `GET /api/projects` adds `registry_hash`, each project's full editable entry (raw values as stored, including `note`) and `errors`
- [x] `GET /api/projects/suggestions` → `session_dirs()`
- [x] `POST /api/projects` (create; optional `init: true` to run `init_repo` first), `PUT /api/projects/<key>` (edit), `DELETE /api/projects/<key>`; body carries `registry_hash`; 409 on conflict, 400 with the validation text otherwise
- [x] `POST /api/projects/<key>/baseline`: in a background thread holding the shared project lock and the ticket lock of a fresh id (`BASELINE-<unix-ms>`), `create_worktree` must return `reused: False` (otherwise abort without removing anything) → `run_verify` → `remove_worktree` of that id only; a second request for the key while one runs returns 409; the result (status, exit, duration, tail) is kept in memory per key and returned by `GET /api/projects/<key>/baseline`
- [x] A confidential project's save runs `record_location_problem` and returns its text as a warning (saved anyway; dispatch already refuses unsafe records)

### UI (runner/templates/index.html)
- [x] Projects panel header: "+ Project" button opening a form: key, path (with a "From history" picker and a "create new folder" checkbox shown when the path is missing), kind, verify, verify timeout, env rows, seed rows, confidential (default on), no_push (default on), note
- [x] Each project head, broken entries included: Edit (parsed entries only), Remove (confirm dialog naming the key; on a worktree refusal it lists them and offers "Clean up and remove"), Baseline; the note shows under the head; baseline result shows inline with the tail in a collapsible block
- [x] All values rendered through `_esc`; errors from the API shown in the form

### Docs
- [x] `projects.example.yaml` documents `note`
- [x] Hand-migrate the local `projects.yaml` comments into `note` fields (gitignored file; not committed)

## Non-goals
- Renaming a key (remove + add instead)
- Deleting project files, worktrees or branches from the UI (Remove only edits the registry)
- Preserving YAML comments (replaced by `note`)
- Editing projects that fail to parse: the panel shows their error; fix them in the file

## Assumptions and sources
- Registry loader and validation: `runner/projects.py:212` (`_parse_project`), `:263` (`load_registry`), `:387` (`_check_seed_source`)
- Every non-GET route already requires the page token: `runner/app.py:182` (`_require_request_token`)
- Registry is re-read on every dispatch and every `/api/projects` call (`runner/app.py:2647`, `:2974`), so no restart is needed
- File lock and atomic write helpers: `runner/state_io.py:21` (`file_lock`), `:33` (`write_json_atomic`)
- Session readers: `runner/projects.py:821` (`_claude_summary`), `:895` (`codex_sessions`)
- The launchd runner has the TCC access the Claude Code shell lacks, so registry reads of protected folders work from the dashboard

## Risks
- `yaml.safe_dump` reorders nothing (`sort_keys=False`) but drops comments: mitigated by the `note` migration before the first UI save
- A verify command is arbitrary shell; the form gives the same power the file already has, and only a token-holding local page can call it
- Turning `confidential` off for a project with existing confidential tickets: per-ticket stickiness (sidecar, binding) still protects those tickets; the form warns

## Verification
- Proof command: `.venv/bin/python -m pytest tests/` → all pass
- Manual: headless browser (Playwright, Chrome channel) drives the panel against the live runner on a throwaway repo registered through the UI, then removes it; screenshots in the session scratchpad

## Progress Checklist
- [x] Test: create/edit/remove round-trip keeps other entries and field order, and the result reloads through `load_registry`
- [x] Test: invalid entry (missing verify, bad env, seed not ignored by a committed rule, path not a repo, path under WORKTREE_ROOT, duplicate key, unknown key on edit) is refused and the file stays byte-identical
- [x] Test: stale `registry_hash` → 409 and no write
- [x] Test: remove refuses with a worktree present (lists it) and while a shared project lock is held; removes a broken (unparseable) entry
- [x] Test: a broken entry (a seed deleted after a clean worktree was made) is removed with cleanup via the minimal descriptor; a broken entry whose path is not a repo refuses cleanup
- [x] Test: cleanup preflight of a broken entry, and of a sidecar-confidential worktree of a registry-non-confidential project, runs its git calls confined (`confine_for` returns the sandbox)
- [x] Test: a hand edit landing during remove's cleanup is caught by the final re-check; the editor's file is kept
- [x] Test: lifecycle locks never live in a key dir: a stray `PROJECT.lock` dir there leaves the lock working (git refuses `*.lock` branch names, so such a ticket id cannot exist)
- [x] Test: a path/seed edit runs its seed check under its own exclusive lock without deadlock (bounded by a timeout in the test)
- [x] Test: a confidentiality edit is refused until the launch helper has posted its comment and removed its running-job entry
- [x] Test: cleanup-and-remove deletes clean worktrees and their branches, and refuses with nothing deleted when any one worktree has an uncommitted file or a commit beyond base
- [x] Test: an invalid key (`bad key`, `../x`) is refused and the file stays byte-identical
- [x] Test: a seed ignored only by `.git/info/exclude`, and a tracked seed, are refused at save time
- [x] Test: baseline never touches a pre-existing worktree (an existing `BASELINE-<id>` worktree with an uncommitted file survives an id collision)
- [x] Test: an edit changing `confidential` or `path` is refused while a shared project lock is held; a `note` edit succeeds; a `path` edit is refused while a worktree exists
- [x] Test: dispatch waiting on the project lock behind a remove fails with "unknown project" and creates no worktree
- [x] Test: a hand edit landing after the first hash check but before the write is caught by the re-check (409)
- [x] Test: `init_repo` creates a repo with one commit; refuses an existing path and a missing parent
- [x] Test: `session_dirs` maps a subdirectory cwd to its repo root, drops non-repos, worktrees and registered roots, and survives a malformed JSONL and a missing Codex DB
- [x] Test: API routes reject a missing token (403) and return 400 with the validation text
- [x] Test: baseline route runs once per key at a time (second call 409) and reports pass/fail with the tail
- [x] Test: `note` must be a string and round-trips
- [x] Implement registry writes, `note`, `init_repo`, `session_dirs`
- [x] Implement API routes
- [x] Implement UI form, history picker, edit/remove/baseline controls
- [x] Update `projects.example.yaml`
- [x] Migrate local `projects.yaml` comments into `note` (not committed)
- [x] Proof: `.venv/bin/python -m pytest tests/` passes — 339 passed (2026-10-15)
- [x] Fix: one-off ticket ids (`REGCHECK-`, `BASELINE-`) drop their lock files after use; remove deletes a key dir that holds only lock files
- [x] Fix: the registry lock file `projects.yaml.lock` is gitignored
- [x] Test: a project tab holds the shared lifecycle lock until it closes
- [x] Test: a project created through `save_project` dispatches into its own worktree
- [x] Fix (user request, 2026-10-15): `_playStartSound`, defined after `</html>` since 551d36d6 and shown as page text (its call threw ReferenceError), moved into the page script
- [x] Fix: the form dialog is centred with padding (the global `* { margin: 0; padding: 0 }` reset had pinned it top-left)
- [x] Manual browser check: add from history, add typed path, add new folder, edit, baseline, remove on a throwaway repo; screenshots captured — 2026-10-15, headless Chrome against the live runner: 13 history suggestions, a pick pre-fills path + key; typed-path (confidential, seed) and new-folder (git init, one commit) saves close the dialog; the note edit shows; baseline `pass · exit 0`; both removed; registry back to its 3 entries; no page errors; screenshots `ui_reg_1_history.png` … `ui_reg_4_dialog.png` in the session scratchpad
- [x] Fix: the form submits the hash it was opened with; a 409 keeps it stale until reopened (REGUI-B001) — browser check: hand edit + refresh → save refused twice, edit kept
- [x] Fix: path edits refused while any worktree exists; re-adding needs leftovers bound to the exact path (REGUI-B002)
- [x] Fix: env edited as JSON, seed lines verbatim, invalid input refused (REGUI-B003)
- [x] Fix: `.projects.yaml.*.tmp` gitignored (REGUI-B004)
- [x] Fix: new-folder init runs inside `save_project` after key/hash/duplicate checks (REGUI-B005; its rollback was replaced by keep-and-report, B006)
- [x] Test: symlink-alias path edit and alias re-add refused; init with stale hash / duplicate creates no folder; env values round-trip verbatim; registry temp patterns ignored
- [x] Fix: after `init`, a failed save keeps the new folder and reports `initialized`; the form retries without init (REGUI-B006)
- [x] Test: invalid entry and mid-validation hand edit both keep the initialized folder; API returns `initialized`; retry without init registers it
- [ ] Fresh cross-provider (Codex) build inspection returns no unresolved material findings — inspection 1 REVISE (5, fixed); inspection 2 REVISE (1, fixed); inspection 3 pending
