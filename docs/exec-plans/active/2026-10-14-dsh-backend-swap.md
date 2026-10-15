---
status: in-progress
created: 2026-10-14
---

# Task: Replace DS TUI with DeepSeek Harness (`dsh`), retire the direct-API DeepSeek backend

> Under claudex-loop review (Codex). Rounds 1–3 approved the rc.7 version. Revised the same day for `dsh` 0.2.0-rc.2 after the user approved the upgrade; needs re-review. See the review log.

## Goal
The dashboard offers two DeepSeek agents. Both predate DeepSeek's official harness:
- **`deepseek`** (button "DeepSeek") is a direct-API loop in `runner/deepseek_agent.py`. It runs in-process with `workspace=ROOT` and has no CLI session.
- **`deepseek-tui`** (button "DS TUI", currently `agent-hidden`) wraps the third-party Rust CLI `deepseek exec --auto --output-format stream-json`, with a version gate at `runner/app.py:2039-2058`.

This plan replaces both with **one** agent, `dsh`, backed by the official DeepSeek Harness. The npm package is `@deepseek-ai/dsh`, installed at `/opt/homebrew/bin/dsh` (`0.2.0-rc.2`, upgraded from rc.7 on 2026-10-14; Node ≥ 22, local v25.1.0), and the agent runs `dsh --profile headless --json -- "<task>"`. The result is one DeepSeek path, maintained by the vendor, that has a real sandbox. It also stops `deepseek` from being the odd backend that cannot run in a project worktree, which the multi-project dispatch plan currently has to special-case.

## Verified facts (2026-10-14, local, `dsh` 0.2.0-rc.2; read from `--help`, `--dump-config` and the installed `dsh-headless/lib` source)
- **Headless CLI.** `dsh --profile headless [--json] [--session-id <id>] [task...]`. The task can also come from stdin with `-`, and `--` ends the options. Diagnostics go to stderr.
- **`--json` events** (`dsh-headless/lib/json-stream-*.js` `projectJsonRun`): NDJSON on stdout, one object per line.
  - The first line is `{"type":"session","sessionId","cwd"}`, written by this process for its own agent, so the id is tied to the process.
  - Then `status` (`phase`: `turn_start`/`step_start`/`step_end`/`turn_end`, where `step_end` may carry `usage{inputTokens,outputTokens,cacheReadTokens?,reasoningTokens?…}` and omits it when the step total is incomplete), plus `thinking`, `text`, `tool_call {callId,tool,input}` and `tool_result {callId,status,result}`. String fields are capped at 8 KiB.
  - The run ends with `{"type":"final","text"}`, unbounded. A usage error prints `{"type":"error","message"}` and exits 1.
- **Resume.** `--session-id <id>` adopts a persisted session. `assertAdoptable` rejects it when the session's recorded `cwd` differs from the current cwd, when it is a subagent or forked session, or when it uses an agent preset. An unknown id is an error.
- **Sandbox.** The headless profile (`dsh --profile headless --dump-config`) loads `dsh-sandbox-local`, `dsh-bash-sandbox` and `dsh-sandbox-policy`.
  - The policy mode comes from `DSH_PERMISSION_MODE`, default `workspace-write`, with `workspaceRoot = process.cwd()`.
  - The presets are `read-only` (approval `ask`), `workspace-write` (approval `ask`) and `danger-full-access` (approval `never`).
  - When headless, `ask` auto-denies escalation without hanging (spike (a) in the checklist).
  - On macOS the Seatbelt profile (`dsh-sandbox-local/lib/index.js` `seatbeltProfileArgs`, unchanged in 0.2.0-rc.2) is `(allow default)` plus a `file-write*` deny outside the writable roots. It confines **writes only**: shell network and reads stay open in every mode.
- **Sessions.** Sessions persist to `~/.dsh/sessions/<cwd-slug>/session-<uuid>/session.jsonl.zstd`, which is zstd-compressed.
- **Profiles.** Only a `headless` profile is installed under `~/.dsh/profiles`, so `--profile tui` does not exist.
- **Shebang.** `dsh` starts with `#!/usr/bin/env node`. The main launchd plist PATH includes `/opt/homebrew/bin`. `com.agenticos.runner.local.plist` sets no PATH, which would break `dsh` if that plist is used.
- **API key.** The key comes from `DEEPSEEK_API_KEY` or `~/.deepseek/config.toml`; the user's existing wrapper `~/.claude/skills/deepseek/dsh-headless` already does this.
- **Footprint.**
  - The direct-API backend is referenced in `runner/app.py` (`:93-99`, `:2500-2540`, `:3015-3060`) and `runner/modules/linear/__init__.py` (`:506-590`).
  - The `deepseek-tui` agent appears in `_ai_cli` (`:2069-2079`), `_stream_deepseek_tui_run` (`:2276`), `_build_resume_cmd` (`:2402`), the backend list (`:3282-3294`) and the agent allow-lists (`app.py:468,2973`; `linear/__init__.py:134,156,767,851`).
  - In the UI, `runner/templates/index.html` has buttons at `:721-722`, `:878-885`, colour classes at `:183-245` and the agent list at `:1179`.

## Key Decisions
1. **One agent id: `dsh`, labelled "DeepSeek".** Old ids are aliased on read and never rewritten. That covers `deepseek`, `deepseek-tui` and the legacy `aider` (already mapped at `linear/__init__.py:144`), wherever they occur:
   - preferred-agent settings and `<!-- agent_backend: … -->` ticket markers;
   - run-record filters;
   - skill registry `agents` lists. `registry_loader.load_registry("dsh")` filters, through a new branch, on the aliased lists, so `dsh` no longer falls through to the unfiltered master. The `/run` compatibility check and the `data-agents` that `index.html` reads see `dsh` too. Source registry files are not rewritten.
   - Python and JS each have one alias helper: `canonical_agent()` in `runner/agent_ids.py`, imported by `app.py`, `linear/__init__.py` and `registry_loader.py`, and `canonAgent()` in `index.html`.
   - Historical run records keep their original `agent` value. Run history displays it as-is, but every **retry/lock comparison** in the browser canonicalizes it first. That covers the card retry group (`index.html:2106-2124`), `_updateDetailRetryLock` (`:2636-2655`) and the skill-card filter (`:1064`). Card and detail retry locks apply to `dsh` like the other agents, because `dsh` now resumes (Decision 4). A historical `deepseek` run, which has no session, never locks.
2. **Command.** Implemented in `_ai_cli("dsh")`.
   - `_ai_cli("dsh")` is `[dsh_bin, "--profile", "headless"]`, with the binary resolved like the old deepseek-tui lookup: `shutil.which`, then `/opt/homebrew/bin`.
   - `_ai_command("dsh", prompt, output_format=…)` adds `--json` only when `output_format != "text"`, then `"--", prompt`. The `--` stops a prompt that starts with `-` from being parsed as a flag.
     - Text mode prints only the final message on stdout. That covers the Linear skill-routing call (`linear/__init__.py:606`), which passes stdout to `_extract_skill_name`. It never sees NDJSON. (`GET /stream` was the other text-mode caller; the multi-project dispatch plan's Security Precondition deletes it, so it is out of scope here.)
     - JSON mode is used by `/run`, retry and Linear execution, all parsed by `_stream_dsh_run`.
   - The resume argv (`_build_resume_cmd`) is `[dsh_bin, "--profile", "headless", "--json", "--session-id", sid, "--", prompt]`.
   - `/stream` is deleted by the multi-project dispatch plan's Security Precondition (it has no caller), so this plan adds no `dsh` support to it.
   - `cwd` is the run's cwd. That is `ROOT` today and the bound worktree once multi-project dispatch lands.
   - The child env gets `DEEPSEEK_API_KEY`, from the environment or else from `~/.deepseek/config.toml` via `tomllib`. The key is never put in argv, logs or run records.
   - The child env also gets `DSH_PERMISSION_MODE` as decided in Decision 3.
   - Both are injected in `_registry_exec_env(agent, registry)` when `agent == "dsh"`, which every remaining spawn site already uses (`app.py:2450,2552,3070`; `:2671` was `/stream`, which is deleted). The Linear routing `subprocess.run` (`linear/__init__.py:605`) passes no `env` today, so it gains `env=_registry_exec_env(backend, registry)`.
   - A version gate requires `dsh >= 0.2.0-rc.2`, the first version with `--json` and `--session-id`. rc builds can change the CLI, so the gate compares the full semver including the pre-release tag.
3. **Permission mode is decided by the spike, and it fails closed.**
   - **Confidential projects: `dsh` is always rejected**, in every permission mode. The installed Seatbelt profile leaves shell network open (see Verified facts), so it cannot meet the dispatch plan's Decision 9 "no shell network" rule. This changes only if a later dsh release adds network confinement *and* a rerun of spike items (c) and (d) proves it.
   - The permission mode below therefore covers non-confidential runs only.
   - **If headless `ask` auto-denies without hanging,** use `workspace-write`. Writes are then confined to the cwd and the agent never asks, which is the same model as Codex `approval_policy="never"`.
   - **If headless `ask` hangs or errors,** use `danger-full-access`, which matches today's `deepseek exec --auto`.
   - Record the outcome in this plan.
   - A sandboxed `workspace-write` run must also be able to commit in a git worktree, because the git common dir lies outside `workspaceRoot`. No `--add-dir` equivalent is known, so the spike checks it. If a sandboxed run cannot commit there, the prompt tells it to leave changes uncommitted and the runner commits on `agent/<id>` after the run.
4. **Output and session handling.** `_stream_dsh_run(proc, run_id, timeout)` replaces `_stream_deepseek_tui_run` (`app.py:2276`). It keeps the same return tuple `(output, input_tokens, output_tokens, model, session_id, stderr)` and the same progress JSONL file, so the existing run tab streams it live.
   - The `session` event sets `agent_session_id`. The id is the one this process printed for its own agent, so overlapping runs cannot be misattributed (this resolves DSH-07 properly). The runner still never reads or writes `~/.dsh`.
   - **Success means exit 0 *and* a `final` event.**
     - The installed driver (`dsh-headless/lib/index.js:340-345`) still emits `final` when the turn ends in error, then writes `dsh: <code>: <message>` to stderr and exits 1. So `final.text` becomes the output whenever it is present, and `ok` is false whenever the exit code is non-zero or `final` is missing.
     - The error text is the `error` event's message, plus the `dsh:`-prefixed stderr lines, plus `exit <code>`.
     - `_extract_real_errors` (`app.py:332`) also keeps lines that start with `dsh:`, so the retry path's filter no longer drops them.
     - The dsh call sites (`/run`, retry `app.py:3117`, Linear execution) write `status: error` with that error text when `ok` is false, instead of the unconditional `review`. The other agents' status handling is unchanged.
   - Tokens are the sums of `inputTokens` and `outputTokens` over the `step_end.usage` values. If any `step_end` lacks `usage`, the totals are `null`, because the total is unknowable and is never under-reported. Model is `null` (headless prints none), unless a later version adds it.
   - Malformed or non-JSON lines are written to the progress file and otherwise ignored.
   - **Retry resumes; resets start fresh.** These are the same semantics Claude and Codex have today, and they are not changed here.
     - `_get_task_agent_lock` (`app.py:2360`) drops the `agent == "deepseek"` early return for `dsh`. Retry of a completed `dsh` run is then locked to `dsh` and uses the resume argv.
     - A `todo` or `rework` status, a Linear ticket moved back to In Progress (`LinearModule._dispatch_issue`) or a fresh dispatch starts a new session, exactly as for Claude and Codex.
   - **Session provenance.** The lock helper takes `agent_session_id` only from records whose **raw** `agent` equals the latest record's raw `agent`. Today it takes the newest id from any record of the task.
     - The backward scan also **stops at the newest `todo`/`rework` record**. It never takes an id from that reset record or anything older. So a session discarded by a reset is never resumed, even when the fresh run after the reset failed before emitting its own `session` event. So a `dsh` resume id always comes from a `dsh` session event, and a historical `deepseek-tui` record with a Rust session id is never passed to `--session-id`.
     - When the latest record is a historical `deepseek-tui` or `deepseek` run, its canonical agent is `dsh`, but its session belongs to the Rust CLI or does not exist, so the lock returns no session and dispatch is a fresh `dsh` run.
   - `dsh` adoption requires the same cwd. That holds today (`ROOT`) and in the dispatch plan's bound worktree.
   - **No fresh fallback for `dsh`.** The retry path's "resume failed → full retry without resume" fallback (`app.py:3107-3115`) is skipped when `agent == "dsh"`. A failed resumed run is recorded as `status: error` with its message, and the user resets to `todo` to start fresh.
     - This covers an adoption error, `session/writer-held` (`SessionAlreadyOwnedError`) when two retries race for one session, and a runtime failure after the run did work.
     - So a dsh retry never launches a second agent and never hides its own error behind a fallback result.
     - dsh's own session write lease serializes concurrent adopters, so a task-level reservation is not needed for dsh. The no-op running guard at `app.py:2962-2964` is a pre-existing issue for all agents and is out of scope.
5. **Retire the direct-API agent.**
   - Delete `runner/deepseek_agent.py` and every `_run_deepseek_agent` branch in `app.py` and `linear/__init__.py`.
   - `runner/modules/backends/deepseek.py` keeps the balance and usage monitoring and polling. Its capability check becomes "dsh binary + Node ≥ 22 + API key", and its capability sets `"backend": "dsh"`.
   - `ModuleRegistry.get_capabilities` (`runner/core/module_registry.py:176`) appends `cap["backend"]` when it is a string, otherwise the module name. `/api/capabilities` then lists `dsh`, so the frontend shows the DeepSeek button. The module name and the monitoring identity stay `deepseek`.
   - **Usage windows.** `deepseek_monitor.py` derives window cost, tokens and sessions from the Rust CLI checkpoint `~/.deepseek/sessions/checkpoints/latest.json`, which dsh never writes. Replace that source with timestamped balance snapshots. Window cost is the sum of balance decreases inside the window; top-ups (increases) are ignored. The monitor's window tokens and session counts become `null`, and the UI shows "n/a". Per-run tokens now live in the run records (Decision 4), and summing them into the monitor is out of scope. Spend is account-level, so it also counts `ask_deepseek.py` usage, and the label says so. Remove `scan_checkpoint`.
   - The monitor already keeps `_balance_snapshots`, so harden that history rather than add a new store.
     - **Only valid samples.** Append a sample only when `fetch_balance()` succeeded with a numeric `balance_cny`. A failure appends nothing, keeps the last valid baseline, and sets `stale: true` plus `last_error` for the UI. Today a failure becomes balance 0, which fakes spend.
     - **Retention by time, not count.** Append only when the balance changed since the last sample. Drop samples older than the longest displayed window, but keep the newest pre-window sample as the baseline for the boundary delta. This replaces the 200-sample cap, which holds only about 7 h at 120 s polling.
     - **One writer at a time.** Wrap the whole fetch → read history → append → write cycle in `fcntl.flock` on `~/.deepseek/usage.json.lock`. That covers background polling, `POST /api/deepseek/refresh` and the `--update` CLI. Publish through a unique `tempfile.mkstemp` file in the same dir and then `os.replace`. Fetching inside the lock guarantees no older observation overwrites a newer one.
     - **Same account as dispatch.** `_get_api_key()` switches to environment-first, matching Decision 2 and `ask_deepseek.py`. History stores `key_fp`, the first 12 hex characters of the key's sha256. On a mismatch the history is reset, so balances from two accounts never produce fake spend.
     - Dispatch, the capability check and the monitor share one key resolver.
   - The monitor keeps writing its own cache, `~/.deepseek/usage.json`. That file is runner-owned and was always written by the monitor, so it is the one permitted write under `~/.deepseek/` (see Constraints).
   - `runner/scripts/ask_deepseek.py` is **out of scope and kept**. It is the agent-to-agent second-opinion tool referenced in `AGENTS.md:107`, not a dashboard backend.
     - Only its direct-API mode still works. Its `--agentic` mode (`ask_deepseek.py:196-205`) shells out to the Rust `deepseek exec --auto`, which was removed with the cleanup (Decision 6), so `--agentic` now exits 5 (no binary).
     - The script is not edited. The Decision 8 `AGENTS.md` edit removes the `--agentic` instruction (`AGENTS.md:108`).
     - Migrating `--agentic` to dsh is a separate task, unless its scope is explicitly added later.
6. **Retire the DS TUI agent.**
   - Delete `_check_deepseek_tui_version`, `_stream_deepseek_tui_run`, the `deepseek-tui` branch of `_ai_cli`/`_build_resume_cmd` and the synthetic-backend injection at `app.py:3282-3294`.
   - The Rust `deepseek`/`deepseek-tui` binaries are already gone. Their build dir `prototypes/DeepSeek-TUI/` no longer exists, and the dangling `/opt/homebrew/bin` symlinks were removed at the user's request on 2026-10-14. So the `deepseek-tui` path is already broken at runtime, and removing it loses nothing.
7. **UI.**
   - The agent buttons become Claude, Codex, Gemini and DeepSeek, with DeepSeek mapped to `dsh`.
   - Remove the DS TUI buttons in the agent picker, detail dispatch and detail retry, plus their colour classes.
   - The DeepSeek usage row stays.
8. **Docs.**
   - In `AGENTS.md`, update the repository map (drop `deepseek_agent.py`) and describe the agent list.
   - Also in `AGENTS.md`, remove the "DeepSeek Delegation" instruction to use `ask_deepseek.py --agentic` (`:108`), because that mode no longer has a binary (Decision 5). Keep the direct-API delegation line.
   - Mark `docs/exec-plans/deferred/p15-deepseek-tui-exec-tools.md` as superseded by this plan.
   - Add one line to `docs/context-maintenance.md`.
9. **Sequencing with multi-project dispatch.** Land this before that plan's Phase 2. Its backend list (Decision 3a) then names `claude`, `codex` and `dsh`. Its sandbox rule (Decision 9) rejects `dsh` for confidential projects, because shell network is open (Decision 3); that replaces the "reject direct-API `deepseek`" special case.

## Progress Checklist
- [x] Spike. In a throwaway git repo plus worktree, run `dsh --profile headless` once with `DSH_PERMISSION_MODE=workspace-write` and once with it unset. Record the answers here. (c) and (d) are recorded for the record only, because confidential eligibility is already decided as rejected (Decision 3).
  - Use `--json` for every probe and keep the NDJSON as evidence.
  - (a) Under `ask`, does the run finish or hang (use a 120 s timeout)? What `tool_result` status does a denied action produce?
  - (b) Can it edit a file inside the cwd?
  - (c) Does a write outside the cwd (`~/dsh-probe`) fail?
  - (d) Does `curl -sI https://example.com` fail?
  - (e) Can it `git commit` in the worktree?
  - (f) What is the exit code on a task failure?
  - (g) Does the first line carry `type: session` with a `sessionId`, and does the run end with `final`? Do `step_end` events carry `usage`?
  - (h) Does a second run with `--session-id <id>` in the same cwd keep context (ask it to recall a token from run 1)? Does it fail cleanly from a different cwd?
  - **Results (2026-10-14, dsh 0.2.0-rc.2, deepseek-flash; evidence in session scratchpad `dsh-spike/*.ndjson`).**
    - Deviation: the "unset" run is identical to `workspace-write`, since that is the default. Run B used `danger-full-access` instead, to measure the fallback mode.
    - Runs: A = workspace-write in a worktree; B = danger-full-access in a second worktree; A2 = workspace-write with the model told to request escalation; C = resume of A in the same cwd; D = resume of A from another cwd; E = invalid API key.
    - (a) **No hang.** A sandbox denial comes back to the model as a `tool_result` with `Operation not permitted` and a hint that escalation is available. When the model then requests escalation (A2, `sandbox_permissions: "danger-full-access"`), the `tool_result` has `status: "error"`: `sandbox escalation to "danger-full-access" requires approval, but no approval channel is available`. The run continues and exits 0 in about 11 s. So headless `ask` **auto-denies (fails closed)**.
    - (b) Yes. `probe.txt` was created in the cwd in A and B.
    - (c) workspace-write: `~/dsh-probe-A` was denied (`Operation not permitted`) and the file is absent. danger-full-access: `~/dsh-probe-B` was written (since deleted).
    - (d) `curl -sI https://example.com` returned `HTTP/2 200` in **both** modes, so network is open. This confirms that confidential projects are rejected (Decision 3).
    - (e) **`git commit` in the worktree succeeds under workspace-write** (A: `[agent/spike d99afed] probe`, visible in the main repo's `git log --all`). No runner-side commit is needed.
    - (f) Invalid key (E): exit 1; `turn_end.reason = {kind: "error", error: {code: "AUTH", status: 401, message}}`; `final.text` is `""`; stderr has `dsh: AUTH: …`; that `step_end` has no `usage`, so tokens are null as designed. The provider's message includes a masked key suffix (`****` plus the last 4 characters). That is not the key, but the error text stored in run records will contain it.
    - (g) Yes. Every run's first line is `session` with a `sessionId` and a `cwd`, and every completed run ends with `final`. `step_end.usage` is present on successful steps, for example `{inputTokens, outputTokens, cacheReadTokens, cacheWriteTokens, totalTokens}`.
    - (h) **Resume works.** C (`--session-id` A, same cwd) printed `session` with the same id, `turn: 2`, and `final` `PELICAN-42`, recalled from A, then exit 0. D (other cwd) printed only `{"type":"error","message":"session … was recorded in …/wt, not …/other"}` with no `session` line, then exit 1, with the same message on stderr.
- [x] Decide the permission mode (Decision 3) from the spike results and record it. **Decision: `workspace-write` for all (non-confidential) dsh runs.** Headless `ask` auto-denies escalation without hanging (a), outside writes are blocked (c), and worktree commits work (e). Confidential projects are still rejected because of (d).
- [x] `runner/agent_ids.py` `canonical_agent()`; use it at every agent allow-list and alias site. That covers `app.py:414-421,468,2973`, `linear/__init__.py:134-156,767,851,886` and `registry_loader.load_registry`, which gets a `dsh` branch.
- [x] `_ai_cli("dsh")`: binary lookup, version gate (≥ 0.2.0-rc.2), env (key and permission mode); `_agent_model("dsh")` (`app.py:2151-2157`) returns `None`; `_build_resume_cmd` adds the `--session-id` form; `_session_lock` (`:2390`) treats `dsh` like `codex`.
- [x] `_stream_dsh_run` (Decision 4), wired at both dispatch sites that call `_stream_deepseek_tui_run` today (`app.py:2562`, `:3079`) and at the Linear dispatch path; `ok`/`status: error` propagation; `dsh:` lines kept by `_extract_real_errors`.
- [x] `_registry_exec_env` dsh env injection; Linear routing gains `env=`; `_ai_command` adds `--json` only outside text mode; lock-helper session provenance (Decision 4).
- [x] Remove the direct-API agent: delete `runner/deepseek_agent.py` and its branches; `backends/deepseek.py` advertises `backend: "dsh"`; `module_registry.get_capabilities` appends `cap["backend"]`.
- [x] Monitor: replace the checkpoint source with balance-delta windows; tokens and sessions become `null`; only valid samples, change-only appends, time retention, a flock plus a unique temp file, an env-first shared key resolver, and a `key_fp` reset (Decision 5); update the `usage_reader.load_deepseek_usage` consumers and the UI "n/a" and stale display.
- [x] Remove DS TUI code paths (Decision 6).
- [x] UI changes (Decision 7), plus `canonAgent()` in every retry/lock/skill-filter comparison (Decision 1).
- [x] Tests:
  - `dsh` argv (fresh and resume) and env, with the key absent from argv and from the run record;
  - `_stream_dsh_run` on a recorded NDJSON fixture: session id, output from `final`, summed tokens; a `step_end` with no `usage` gives `null` tokens; malformed lines are ignored;
  - failure: `final` followed by exit 1 with `dsh: E: msg` on stderr gives `ok` False, keeps the `final` text and records an error containing `dsh: E: msg`; exit 0 with no `final` gives `ok` False; the `error` event's message is kept;
  - session provenance: a task whose latest record is `deepseek-tui` with a Rust `agent_session_id` produces a fresh `dsh` argv (no `--session-id`); after a `dsh` run, retry uses that run's id; a `rework` record clears the lock;
  - reset boundary: the sequence dsh S1 → `rework` record (copying S1) → fresh dsh run failing with no session id → retry produces a fresh argv, not S1;
  - no fallback: a dsh resume that fails (adoption error, or exit 1 after `final`) launches exactly one process and records `status: error`;
  - text mode: `_ai_command("dsh", p, output_format="text")` has no `--json`; the Linear routing call passes `env` that includes the key;
  - legacy ids `deepseek`, `deepseek-tui` and `aider` resolve to `dsh` in preferred-agent settings and ticket markers;
  - registry: `load_registry("dsh")` returns skills whose `agents` contain `dsh` or a legacy alias, and excludes Claude-only skills;
  - `get_capabilities()["backends"]` contains `dsh` and not `deepseek` when the DeepSeek module is available;
  - monitor: a balance-decrease series gives the expected 5h/7d cost windows, a top-up is ignored, and tokens are `null`;
  - monitor: a success → failure → success sequence creates no spend and no top-up, and sets `stale` while failing;
  - monitor: a spend 2 days ago still shows in the 7d window after more than 200 later polls (unchanged balance, so no new samples), and the predecessor sample is kept;
  - monitor: two overlapping `update_usage()` calls (threads) leave valid JSON that contains both samples in order;
  - monitor: a `key_fp` change resets the history and creates no spend;
  - a missing binary or old version gives a clear error and no launch;
  - `tests/modules/test_backend_modules.py` updated for the monitoring-only module.
- [x] Docs (Decision 8).
- [ ] Dogfood: one real non-confidential ticket dispatched with DeepSeek from the dashboard, end to end, including one retry that resumes; record the outcome here.
- [x] Definition of Done: `.venv/bin/python3 -m py_compile runner/*.py` and `.venv/bin/python -m pytest tests/` pass; `git grep -n "deepseek_agent\|deepseek-tui\|_stream_deepseek_tui_run" -- runner/` returns nothing apart from the alias map.
  - **Build notes (2026-10-14, worktree `feat/dsh-backend-swap`, base `aa9cf13`).**
    - DoD: `py_compile` is clean and `pytest tests/` gives 103 passed. The grep hits only the alias maps (`linear/__init__.py:158` marker regex, `index.html` `_AGENT_ALIASES`) plus `ask_deepseek.py:55` (`.deepseek_agentic_session`, a substring match in an out-of-scope file).
    - Tests are in `tests/test_dsh_backend.py`; `tests/modules/test_backend_modules.py` was updated.
    - Live smoke with real dsh 0.2.0-rc.2 through `_ai_command`, `_stream_dsh_run` and `_build_resume_cmd` in a scratch cwd:
      - fresh run: ok, 7198/2 tokens, `final` "OK";
      - resume of the same session id: recalled `HERON-77`;
      - the key was absent from argv.
    - Pure helpers (binary, version gate, env-first key, `key_fp`, NDJSON accumulator) live in `runner/dsh_cli.py`, shared by `app.py`, the backend module and the monitor.
    - `_stream_dsh_run` returns `output=None` when no `final` arrived. When the run is not ok, its stderr slot carries the composed `dsh: …` error lines. `_dsh_ok()` is the success test.
    - Linear errors still push "In Review" to Linear, which has no error state; the board record is `status: error`.

## Acceptance Criteria
- [ ] The dashboard shows exactly one DeepSeek agent. Dispatch runs `dsh --profile headless --json` in the run's cwd, streams progress into the run tab, and stores the `final` text, the session id and the tokens.
- [ ] Retry of a completed dsh run resumes the same session (`--session-id`), and the agent recalls context from the earlier run. A `todo`/`rework` reset starts fresh.
- [ ] A dsh run that ends in a runtime error is recorded as `status: error` with the `dsh:` message visible.
- [ ] Old run records and tickets that name `deepseek` or `deepseek-tui` still display, and re-dispatching them uses `dsh`.
- [ ] The API key never appears in argv (`ps`), `RUN_LOG` or run records.
- [ ] The permission mode chosen in the spike is the one used, and the plan records the spike evidence for it.
- [ ] The DeepSeek balance and usage row still updates, and a dsh-only run moves the 5h cost window.
- [ ] A historical `deepseek`/`deepseek-tui` run card shows retry buttons, with DeepSeek mapped to `dsh`.
- [ ] `dsh` is refused for a confidential project.

## Constraints
- Do not modify `~/.deepseek/` config and sessions, `~/.dsh/` or `~/.claude/skills/deepseek/`. The one exception is the monitor's existing runner-owned cache `~/.deepseek/usage.json`, which it keeps writing.
- Do not touch `runner/scripts/ask_deepseek.py`.
- Do not rewrite historical run records.
- Do not install unofficial packages. Only `@deepseek-ai/dsh` is official; `deepseek-harness` and `deepseek-harness-cli` on npm are not.

## Risks
- `dsh` is a release candidate (`0.2.0-rc.2`); rc.7 → 0.2 already added `--json` and `--session-id`. CLI flags, the event schema and the profile layout may change again. The version gate, the NDJSON fixture test and a spike rerun after upgrades mitigate this.
- `--json` caps string fields at 8 KiB per event, so the progress view truncates long tool output. The `final` text is not capped.
- The monitor's usage windows are account-level spend from balance changes. Per-run tokens are in the run records, but nothing aggregates them.
- `com.agenticos.runner.local.plist` has no PATH, so `env node` may fail under it. Use the absolute Node path or set PATH in that plist.

## Test
`.venv/bin/python -m pytest tests/`. Then, in the dashboard, select DeepSeek, run a small ticket, and confirm the live stream, the output, the `agent: dsh` record with its session id and tokens, and the usage row. Then retry it and confirm that it resumes. Also run `ps -o args= -p <pid>` during the run and confirm no key appears.
