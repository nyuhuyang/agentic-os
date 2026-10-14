---
status: in-progress
created: 2026-10-14
---

# Task: Replace DS TUI with DeepSeek Harness (`dsh`), retire the direct-API DeepSeek backend

> Not yet reviewed. Written at the user's request on 2026-10-14; send it to review before building.

## Goal
The dashboard offers two DeepSeek agents. Both predate DeepSeek's official harness:
- **`deepseek`** (button "DeepSeek") is a direct-API loop in `runner/deepseek_agent.py`. It runs in-process with `workspace=ROOT` and has no CLI session.
- **`deepseek-tui`** (button "DS TUI", currently `agent-hidden`) wraps the third-party Rust CLI `deepseek exec --auto --output-format stream-json`, with a version gate at `runner/app.py:2039-2058`.

This plan replaces both with **one** agent, `dsh`, backed by the official DeepSeek Harness. The npm package is `@deepseek-ai/dsh`, installed at `/opt/homebrew/bin/dsh` (`0.1.0-rc.7`, Node ≥ 22), and the agent runs `dsh --profile headless "<task>"`. The result is one DeepSeek path, maintained by the vendor, that has a real sandbox. It also stops `deepseek` from being the odd backend that cannot run in a project worktree, which the multi-project dispatch plan currently has to special-case.

## Verified facts (2026-10-14, local)
- **Headless output.** `dsh --profile headless --help` says it will "Answer one task, print the final assistant message, and exit". It has no flags besides `-h`, so there is no stream-json, no token counts and no session id on stdout.
- **Sandbox.** The headless profile (`dsh --profile headless --dump-config`) loads `dsh-sandbox-local`, `dsh-bash-sandbox` and `dsh-sandbox-policy`.
  - The policy mode comes from `DSH_PERMISSION_MODE`, default `workspace-write`, with `workspaceRoot = process.cwd()`.
  - The presets are `read-only` (approval `ask`), `workspace-write` (approval `ask`) and `danger-full-access` (approval `never`).
  - How `ask` behaves when headless (auto-deny, hang or error) is **unknown**.
- **Sessions.** Sessions persist to `~/.dsh/sessions/<cwd-slug>/session-<uuid>/session.jsonl.zstd`, which is zstd-compressed.
- **Profiles.** Only a `headless` profile is installed under `~/.dsh/profiles`, so `--profile tui` does not exist. Whether headless runs can resume a session is unverified.
- **Shebang.** `dsh` starts with `#!/usr/bin/env node`. The main launchd plist PATH includes `/opt/homebrew/bin`. `com.agenticos.runner.local.plist` sets no PATH, which would break `dsh` if that plist is used.
- **API key.** The key comes from `DEEPSEEK_API_KEY` or `~/.deepseek/config.toml`; the user's existing wrapper `~/.claude/skills/deepseek/dsh-headless` already does this.
- **Footprint.**
  - The direct-API backend is referenced in `runner/app.py` (`:93-99`, `:2500-2540`, `:3015-3060`) and `runner/modules/linear/__init__.py` (`:506-590`).
  - The `deepseek-tui` agent appears in `_ai_cli` (`:2069-2079`), `_stream_deepseek_tui_run` (`:2276`), `_build_resume_cmd` (`:2402`), the backend list (`:3282-3294`) and the agent allow-lists (`app.py:468,2973`; `linear/__init__.py:134,156,767,851`).
  - In the UI, `runner/templates/index.html` has buttons at `:721-722`, `:878-885`, colour classes at `:183-245` and the agent list at `:1179`.

## Key Decisions
1. **One agent id: `dsh`, labelled "DeepSeek".** Old ids are aliased on read and never rewritten. That covers `deepseek`, `deepseek-tui` and the legacy `aider` (already mapped at `linear/__init__.py:144`), wherever they occur: preferred-agent settings, `<!-- agent_backend: … -->` ticket markers and run-record filters. Historical run records keep their original `agent` value. Run history renders them as-is.
2. **Command.** Implemented in `_ai_cli("dsh")`.
   - The argv is `[dsh_bin, "--profile", "headless", prompt]`, with the binary resolved like the old deepseek-tui lookup: `shutil.which`, then `/opt/homebrew/bin`.
   - `cwd` is the run's cwd. That is `ROOT` today and the bound worktree once multi-project dispatch lands.
   - The child env gets `DEEPSEEK_API_KEY`, from the environment or else from `~/.deepseek/config.toml` via `tomllib`. The key is never put in argv, logs or run records.
   - The child env also gets `DSH_PERMISSION_MODE` as decided in Decision 3.
   - A version gate requires `dsh >= 0.1.0-rc.7`, because rc builds can change the CLI.
3. **Permission mode is decided by the spike, and it fails closed.**
   - **If headless `ask` auto-denies without hanging,** use `workspace-write` for every dsh run. The agent is then sandboxed and never asks, which is the same model as Codex `approval_policy="never"`.
   - **If headless `ask` hangs or errors,** non-confidential runs use `danger-full-access`, which matches today's `deepseek exec --auto`. Under the dispatch plan's Decision 9, `dsh` is then rejected for confidential projects.
   - Record the outcome in this plan.
   - A sandboxed `workspace-write` run must also be able to commit in a git worktree, because the git common dir lies outside `workspaceRoot`. No `--add-dir` equivalent is known, so the spike checks it. If a sandboxed run cannot commit there, the prompt tells it to leave changes uncommitted and the runner commits on `agent/<id>` after the run.
4. **Output and session handling.**
   - Stdout is the final message, and it is stored as the run output.
   - Token counts are recorded as `null`. DeepSeek spend stays visible through the existing balance and usage monitor (`deepseek_monitor.py`, `runner/modules/backends/deepseek.py`), which is kept.
   - The session id is found by listing `~/.dsh/sessions/<cwd-slug>/` before and after the run. Exactly one new `session-<uuid>` dir is recorded as `agent_session_id`; anything else records `null`.
   - The runner reads `~/.dsh` but never writes it.
   - Retry and rework start a fresh run unless the spike proves that headless resume works. `_session_lock` treats `dsh` like the old API agent and takes no session lock.
   - The run tab in the dispatch plan's Decision 10 shows "no live stream (dsh headless)" until the final output arrives.
5. **Retire the direct-API agent.**
   - Delete `runner/deepseek_agent.py` and every `_run_deepseek_agent` branch in `app.py` and `linear/__init__.py`.
   - `runner/modules/backends/deepseek.py` keeps the balance and usage monitoring and polling but no longer offers dispatch. Its capability check becomes "dsh binary + Node ≥ 22 + API key".
   - `runner/scripts/ask_deepseek.py` is **out of scope and kept**. It is the agent-to-agent second-opinion tool referenced in `AGENTS.md:107`, not a dashboard backend.
6. **Retire the DS TUI agent.**
   - Delete `_check_deepseek_tui_version`, `_stream_deepseek_tui_run`, the `deepseek-tui` branch of `_ai_cli`/`_build_resume_cmd` and the synthetic-backend injection at `app.py:3282-3294`.
   - The Rust `deepseek` binary stays installed on the machine; the runner simply stops calling it.
7. **UI.**
   - The agent buttons become Claude, Codex, Gemini and DeepSeek, with DeepSeek mapped to `dsh`.
   - Remove the DS TUI buttons in the agent picker, detail dispatch and detail retry, plus their colour classes.
   - The DeepSeek usage row stays.
8. **Docs.**
   - In `AGENTS.md`, update the repository map (drop `deepseek_agent.py`) and describe the agent list.
   - Mark `docs/exec-plans/deferred/p15-deepseek-tui-exec-tools.md` as superseded by this plan.
   - Add one line to `docs/context-maintenance.md`.
9. **Sequencing with multi-project dispatch.** Land this before that plan's Phase 2. Its backend list (Decision 3a) and sandbox rule (Decision 9) then name `claude`, `codex` and `dsh`, and the "reject direct-API `deepseek`" special case disappears.

## Progress Checklist
- [ ] Spike. In a throwaway git repo plus worktree, run `dsh --profile headless` once with `DSH_PERMISSION_MODE=workspace-write` and once with it unset. Record the answers here:
  - (a) Under `ask`, does the run finish or hang (use a 120 s timeout)?
  - (b) Can it edit a file inside the cwd?
  - (c) Does a write outside the cwd (`~/dsh-probe`) fail?
  - (d) Does `curl -sI https://example.com` fail?
  - (e) Can it `git commit` in the worktree?
  - (f) What is the exit code on a task failure?
  - (g) Does exactly one new session dir appear?
  - (h) Does any headless resume path exist?
- [ ] Decide the permission mode (Decision 3) from the spike results and record it.
- [ ] `_ai_cli("dsh")`: binary lookup, version gate, env (key and permission mode), session-dir diff helper; add `dsh` to every agent allow-list; add the legacy-id alias map in one helper used by `app.py` and `linear/__init__.py`.
- [ ] Remove the direct-API agent: delete `runner/deepseek_agent.py` and its branches; slim `backends/deepseek.py` down to monitoring.
- [ ] Remove DS TUI code paths (Decision 6).
- [ ] UI changes (Decision 7).
- [ ] Tests:
  - `dsh` argv and env, with the key absent from argv and from the run record;
  - legacy ids `deepseek`, `deepseek-tui` and `aider` resolve to `dsh` in preferred-agent settings and ticket markers;
  - the session-dir diff: one new dir gives its id, zero or two give `null`;
  - a missing binary or old version gives a clear error and no launch;
  - `tests/modules/test_backend_modules.py` updated for the monitoring-only module.
- [ ] Docs (Decision 8).
- [ ] Dogfood: one real non-confidential ticket dispatched with DeepSeek from the dashboard, end to end; record the outcome here.
- [ ] Definition of Done: `.venv/bin/python3 -m py_compile runner/*.py` and `.venv/bin/python -m pytest tests/` pass; `git grep -n "deepseek_agent\|deepseek-tui\|_stream_deepseek_tui_run" -- runner/` returns nothing apart from the alias map.

## Acceptance Criteria
- [ ] The dashboard shows exactly one DeepSeek agent. Dispatch, retry and rework with it run `dsh --profile headless` in the run's cwd and store the final message as output.
- [ ] Old run records and tickets that name `deepseek` or `deepseek-tui` still display, and re-dispatching them uses `dsh`.
- [ ] The API key never appears in argv (`ps`), `RUN_LOG` or run records.
- [ ] The permission mode chosen in the spike is the one used, and the plan records the spike evidence for it.
- [ ] The DeepSeek balance and usage row still updates.

## Constraints
- Do not uninstall or modify the Rust `deepseek` binary, `~/.deepseek/`, `~/.dsh/` or `~/.claude/skills/deepseek/`. The runner only reads them.
- Do not touch `runner/scripts/ask_deepseek.py`.
- Do not rewrite historical run records.
- Do not install unofficial packages. Only `@deepseek-ai/dsh` is official; `deepseek-harness` and `deepseek-harness-cli` on npm are not.

## Risks
- `dsh` is a release candidate (`rc.7`), so CLI flags, the profile layout and the session format may change. The version gate and the spike rerun after upgrades mitigate this.
- Headless mode gives no streaming and no token counts, so runs are less observable than today's stream-json `deepseek-tui`.
- Without headless resume, rework loses conversation context and re-reads the repo, which costs more tokens.
- `com.agenticos.runner.local.plist` has no PATH, so `env node` may fail under it. Use the absolute Node path or set PATH in that plist.

## Test
`.venv/bin/python -m pytest tests/`. Then, in the dashboard, select DeepSeek, run a small ticket, and confirm the output, the `agent: dsh` record and the usage row. Also run `ps -o args= -p <pid>` during the run and confirm no key appears.
