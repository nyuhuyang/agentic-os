---
status: in-progress
created: 2026-10-15
---

# Move the checkout to the workspace root

## Goal
Move this repository from `~/Documents/AI_Workspace/prototypes/agentic-os` to `~/Documents/AI_Workspace/agentic-os` (user decision 2026-10-15: no longer a prototype; it is the workspace's runtime, a peer of `obsidian/`, not a `tools/` utility). The runner keeps working without a manual fix-up on the AgenticOS side; everything outside the repo that mentions the old path is listed for the user.

## Acceptance criteria
- [ ] The old path no longer exists; the new path holds the full checkout (tracked files, `.venv`, `state/`, `outputs/`, `projects.yaml`, `.env`, `.claude/`)
- [ ] launchd runs `com.agenticos.runner` from the new path (`launchctl print` program arguments name the new path) and the dashboard answers 200
- [ ] `.venv` works from the new path: no file under `.venv` mentions the old path; `.venv/bin/python -m pytest tests/` passes from the new path
- [ ] Every nested worktree under `.claude/worktrees/` resolves (`git worktree list` shows new paths; `git status` works in each)
- [ ] The dashboard lists the registered projects with their sessions after the move
- [ ] If the runner does not come back on the new path, the script restores the old path, the venv, the worktrees and the plist, and restarts the runner there
- [ ] The workspace map names `agentic-os/` at the root (repo `CLAUDE.md`, and the workspace-level `CLAUDE.md` if it is a separate file)
- [ ] The user has the exact commands for what lives outside the repo and stays read-only to the agent: two hooks in `~/.claude/settings.json`, the trust entry in `~/.codex/config.toml`, and copying the Claude project folder (auto memory + session history) to the new path's slug

## Approach
`scripts/relocate_checkout.sh OLD NEW` (committed, reusable):
1. Refuse unless OLD is an AgenticOS checkout, NEW does not exist and its parent does, NEW is not inside OLD, the plist exists, the runner answers, and `/api/runs?state=running` is empty.
2. Back up the plist; `launchctl bootout`; wait until no `OLD/runner/app.py` process remains.
3. `mv OLD NEW` (on failure: restart the runner on OLD, nothing changed).
4. Repoint: rewrite OLD → NEW in `.venv/bin` text files (`grep -rlI --null | xargs -0 sed`) and `.venv/pyvenv.cfg`; `git worktree repair` each `.claude/worktrees/*`; rewrite the plist and `plutil -lint` it.
5. Check that no `.venv` file or the plist still names OLD; `launchctl bootstrap`; wait for HTTP 200 and for a `NEW/runner/app.py` process.
6. Any failure after the move → rollback: bootout, `mv NEW OLD`, repoint back, restore the plist backup, bootstrap, wait for 200.
7. Report the files outside the checkout that still name OLD.

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
- [ ] Test: relocate succeeds (moved, venv + plist + nested worktree repointed, runner up from NEW)
- [ ] Test: refuses running jobs, an existing target, a non-checkout source, with nothing changed
- [ ] Test: rolls back fully when the runner does not come up on NEW
- [ ] Codex plan review of this plan and the script returns APPROVED
- [ ] Run the script against the real checkout from a dashboard terminal; log captured
- [ ] Verify each acceptance criterion from the new path
- [ ] Update the workspace map (repo `CLAUDE.md`, and the workspace-level one if separate)
- [ ] Give the user the commands for `~/.claude/settings.json`, `~/.codex/config.toml` and the Claude project folder
- [ ] Fresh cross-provider (Codex) build inspection of the script and tests returns no unresolved material findings
