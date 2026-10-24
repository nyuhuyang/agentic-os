---
status: completed
created: 2026-10-23
completed: 2026-10-23
---

# dsh for confidential projects (AGE-139)

## Goal

Allow a confidential project's Linear ticket to run on `dsh` without weakening Decision 9:
dsh's shell commands and any code it executes get no network and can write only inside the
ticket worktree (plus the trusted temp root), exactly like the other confidential backends.

## Findings (recon)

- `runner/project_runs.py:110-114` refuses `dsh` for a confidential project with
  `dsh is not allowed for confidential projects (its sandbox leaves shell network open)`.
  The refusal is also asserted in `tests/test_project_dispatch.py:139-142` and documented in
  `AGENTS.md` and `docs/exec-plans/completed/2026-10-14-dsh-backend-swap.md` (Decision 3).
- dsh 0.2.1-rc.2 is installed. Its local sandbox provider (`@deepseek-ai/dsh-sandbox-local`)
  builds a Seatbelt profile that is `(allow default)(deny file-write*)` plus writable roots.
  `@deepseek-ai/dsh-sandbox`'s type says network is explicitly outside that vocabulary, so
  every dsh mode leaves shell network open.
- dsh exposes the `sandbox` provider's `runnerCommand` seam: it replaces the built-in runner
  and receives the confined command argv (dsh appends bwrap-compatible profile arguments and
  `--`). It is supported in 0.2.0-rc.2 through 0.2.1-rc.2 and is configurable through dsh's
  `--patch` layer, which is applied after the profile and the user's
  `$DSH_HOME/cordis.patch.yml`.
- `/opt/homebrew/bin/dsh` is a Node script with a `#!/usr/bin/env node` shebang. Project
  `PATH` overrides are applied to the child (`runner/app.py:2745`), so a worktree-local
  `bin/node` can run before the sandbox exists, and the composition probes would run it too.
  dsh must be launched through an absolute Node interpreter and its absolute script path.
- `dsh-subprocess/lib/index.js:52` strips every `DSH_*` variable from a child's environment;
  `dsh-ptc-runtime-node/lib/index.js` also unsets ambient variables for workflow/PTC workers.
  Environment is therefore not a reliable channel for the trusted worktree root. argv is.
- `dsh-app-boot/lib/index.js:3736-3743` loads unset variables from the worktree's and the
  harness home's `.env`; `TMPDIR`, `TMP` and `TEMP` are not in its bootstrap denylist. A
  repository `.env` can therefore move dsh's and the wrapper's temp roots (and
  `projects.sandbox_profile` trusts `tempfile.gettempdir()`), widening writable paths.
- `dsh-tool-bash` resolves `workdir` per call, but the sandbox policy's workspace root comes
  from the session cwd (`dsh-sandbox-policy/lib/index.js:141-155`). The headless profile also
  enables `tool-web` (direct network egress by the model process), `tool-working-directory`
  (moves the session cwd) and `tool-fs` (native read/write/edit). `dsh-fs-sandbox` is a
  trusted-code containment check, not a kernel boundary, and documents an ancestor-symlink
  TOCTOU; native mutations can therefore escape the worktree when shell code races it.
  `tool-working-directory` and the `working-directory` service exist in 0.2.1-rc.2 but not in
  0.2.0-rc.2, so confidential dsh needs `>= 0.2.1-rc.2`.
- `dsh-permission-presets` infers a default preset from the composed sandbox and approval
  defaults and throws when they are `workspace-write` + `never`. `workspace-write` + `ask` is
  the stock matching pair; headless has no approval answerer, so `ask` fails closed.
- A resumed dsh session can carry persisted `sandbox`/`approval`/`permission/preset` events
  that override deployment defaults; a session first used non-confidentially could resume
  `danger-full-access`. Confidential dsh must not resume.
- `--dump-default-config` includes the user's selected bundles from the profile
  `package.json`, not just the shipped headless list; a user-added vendor bundle appears in
  both the baseline and the patched dump. The baseline must require the exact shipped bundle
  identities and an empty profile dependency set.
- dsh derives its default homes from `HOME`: a project `HOME` inside the worktree would make
  the default `~/.dsh` repository-controlled, while `DSH_HOME`/`DSH_AGENTS_HOME` relative
  values resolve against the child cwd. Both effective homes must be resolved from the final
  launch environment, pinned absolute, and checked.
- Project env names such as `NODE_OPTIONS`, `NODE_PATH`, `PYTHONPATH`, `PYTHONSTARTUP` and
  `DYLD_*` execute code before dsh reaches its sandbox; the installed child scrub removes
  credential and `DSH_*` names only. A trusted bootstrap env must drop those project
  overrides, and the Python wrapper must start with `-I`.
- dsh's unsandboxed spill writers cache a directory under the parent `TMPDIR`
  (`dsh-subprocess-local/lib/output.js`, `dsh-spill-local`). A confined shell can rename that
  ancestor and substitute a symlink before a spill, so the runner must point dsh's `TMPDIR` at
  a runner-owned directory outside every shell-writable root while the shell itself uses a
  separate `/tmp` root.
- The launcher, wrapper, patch and profile paths must be outside the worktree *and* every
  sandbox-writable temp root (`/tmp`, `/private/tmp`, `/var/folders`); a runner installed under
  `/private/tmp` would otherwise be rewritable by a confidential shell.
- Non-confidential dsh argv is a compatibility contract; only `confidential_cli_prefix()`
  may switch to the absolute Node launcher. `cli_prefix()` keeps its existing shim.
- `runner/projects.py:105-122` owns the Decision 9 Seatbelt profile used for confidential
  verify and runner git: `(deny network*)`, writes only under the given roots and temp, and
  the launchd/AppleEvents closes. Reusing it keeps one write policy.
- `runner/project_runs.post_run` commits leftover changes for any agent, so a confidential dsh
  run can leave its edits uncommitted and never needs write access to `.git`.
- `_project_exec_env` (`runner/app.py:2745`) is the one place that builds a project run's env;
  `_project_cmd` (`runner/app.py:2703`) is the one place that builds its argv, and both
  dispatch and session continuation go through them.

## Design

- [x] Add `runner/dsh_confine.py` with `build_argv`/`main` (stdlib plus `runner/projects.py`).
- [x] Take the worktree root from the first launcher argument after the script, because dsh's
  child-env scrubbing (bash and PTC) drops ambient variables.
- [x] Require the wrapper root to be absolute and an existing directory, the argv to contain
  `--`, and a non-empty command; ignore the bwrap dialect before `--`.
- [x] Make the wrapper exec only `/usr/bin/sandbox-exec -p <projects.sandbox_profile> <command>`,
  refuse a command whose first argument looks like an option, and fail with exit 126 and a
  `dsh-confine:` line on any refusal.
- [x] Validate the wrapper's temp root against `/tmp`, `/private/tmp`, `/var/folders` and
  `/private/var/folders` before building the profile; refuse a wider temp root.
- [x] Add `runner/scripts/dsh-confidential.yml` with the pinned entries.
- [x] Pin `sandbox-policy` to `workspace-write` and `workspaceRoot: process.cwd()`.
- [x] Point `sandbox.runnerCommand` at `[...JSON.parse(AGENTICOS_DSH_CONFINE_RUNNER), process.cwd()]`,
  add a `dsh-confine:` failure signature, and throw when the variable is absent.
- [x] Replace the `permission` presets with `read-only`/`ask` and `workspace-write`/`ask` and
  set `defaultPreset: workspace-write`; do not expose `danger-full-access`.
- [x] Disable `tool-web`, `tool-working-directory`, `tool-fs`, `otel` and
  `session-telemetry-otel`; the confined shell is the only path for file mutations.
- [x] Pin `approval` to the vendor name with `policy: ask`, so only a no-answerer approval
  request can ever gate a wider mode.
- [x] Pin the enforcing provider names and enabled state for `sandbox`, `bash-sandbox`,
  `tool-bash`, `fs-sandbox`, `fs-observation-policy`, `subprocess`, `shell-env` and
  `working-directory`.
- [x] Keep `dsh_cli.cli_prefix()` unchanged for non-confidential dsh.
- [x] Refuse a confidential dsh launch that has no absolute-node prefix callback; never fall
  back to the shebang launcher.
- [x] Grant the worktree write access only when dsh's bwrap argv contains `--bind <root> <root>`;
  a read-only/plan-mode call gets no writable roots.
- [x] Add the `0.2.1-rc.2` confidential version floor and require the absolute Node launcher
  only for a confidential prefix.
- [x] Add `confidential_cli_prefix()` returning `node bin.js --profile headless --patch <file>`.
- [x] Resolve `HOME`, `DSH_HOME` and `DSH_AGENTS_HOME` from the final launch env, expand `~`
  against that home, pin the absolute values, and reject a relative, worktree or temp path.
- [x] Reject `HOME` itself inside the worktree or a temp root.
- [x] Remove every ambient `DSH_*` switch (except the two pinned homes and the permission
  mode) from the confidential child env so the preflight and launch compose the same profile.
- [x] Force `DSH_TELEMETRY_DISABLED=1` for confidential dsh and disable the `otel` /
  `session-telemetry-otel` entries, so stripping the user's telemetry opt-out cannot enable it.
- [x] Remove project-provided `NODE_OPTIONS`, `NODE_PATH`, `PYTHONPATH`, `PYTHONSTARTUP`,
  `NODE_EXTRA_CA_CERTS`, every `DYLD_*` name and the other bootstrap names from the
  confidential child env.
- [x] Launch the wrapper with `python -I` so `PYTHONPATH`, user site and startup hooks do not
  load repository code.
- [x] In `verify_confidential_launch(env, worktree)`, require the profile `package.json` to
  select exactly `@deepseek-ai/dsh-base` and `@deepseek-ai/dsh-headless`, with no profile
  dependencies or profile-local `node_modules`.
- [x] Run `dsh --profile headless --dump-default-config` and
  `dsh --profile headless --patch <file> --dump-config` (with a trusted env) on every
  confidential launch; do not cache a successful verdict.
- [x] Reject a nonzero dump exit, a `patch: entry` warning, or a missing marker that our
  patch was applied.
- [x] Reject any profile layer header whose origin or patch source is not a `@deepseek-ai/*`
  bundle or our own patch file.
- [x] Compare the enabled entry ids with the stock default minus `tool-web`,
  `tool-working-directory` and `tool-fs`; reject any extra or missing id.
- [x] Require the composed `sandbox` entry to contain `runnerCommand` and `dsh-confine:`.
- [x] Require `tool-web`, `tool-working-directory`, `tool-fs`, `otel` and
  `session-telemetry-otel` to be disabled.
- [x] Require `sandbox-policy` to be `workspace-write`, the `permission` block to default to
  `workspace-write` with no `danger-full-access`, and `approval` to be `policy: ask`.
- [x] Require the launcher, wrapper, patch, profile and interpreter paths used by the
  confidential prefix to resolve outside the ticket worktree and every temp prefix.
- [x] Return the confidential prefix from `project_runs.agent_cli` only when
  `project.confidential`.
- [x] In `_project_exec_env(agent, project, cwd)`, validate the runner's temp root for the
  home/record checks, then pin dsh's `TMPDIR`, `TMP` and `TEMP` to the per-run spill directory
  after the project env so a repository `.env` or project entry cannot widen them.
- [x] Set `DSH_PERMISSION_MODE=workspace-write` and
  `AGENTICOS_DSH_CONFINE_RUNNER=<json [python, dsh_confine.py]>` for confidential dsh.
- [x] Refuse a `DSH_HOME` or `DSH_AGENTS_HOME` that resolves inside the ticket worktree or the
  trusted temp root.
- [x] Run `dsh_cli.verify_confidential_launch(env, cwd)` from `_project_exec_env` and
  re-raise a failure as `project_runs.ProjectRunError`.
- [x] Refuse a confidential dsh `resume_session` in `_project_cmd`; fresh sessions only.
- [x] Tell a confidential dsh prompt to leave changes uncommitted, as Codex is told, so the
  runner commits them and `.git` stays unwritable by the agent.
- [x] Point dsh's `TMPDIR`/`TMP`/`TEMP` at a per-run runner-owned spill directory outside
  the worktree and temp roots, give the confined shell a separate `/tmp` root, refuse the
  launch when records are unsafe, and remove only a direct child of the spill root after the
  run (never a path inherited from a child env).
- [x] Add `(global-name "com.apple.dnssd.service")` to the shared Seatbelt mach-lookup
  denials so DNS cannot carry data past `(deny network*)`.
- [x] Update `AGENTS.md` and `docs/context-maintenance.md`; no UI change is needed.

Non-goals: a dsh release upgrade, a Linux sandbox implementation, network allowlists for
confidential shell commands (shell gets none), resuming a confidential dsh session, and
changing the confidentiality model for Claude or Codex. A dsh model API call still runs in
the main dsh process, outside the shell sandbox.

## Acceptance Criteria

- [x] A confidential project ticket can select `dsh` and is launched with the absolute Node
  launcher and `--patch runner/scripts/dsh-confidential.yml`, not refused.
- [x] A confidential dsh shell runs only under the Seatbelt profile; a missing root, missing
  separator, missing command or untrusted temp root exits 126 with `dsh-confine:` and runs
  nothing.
- [x] The Seatbelt profile denies `network*`, denies writes outside the ticket worktree and
  the validated temp root, denies the DNS mach service, and keeps the launchd/AppleEvents
  closes.
- [x] The confidential launch env pins `HOME`, `DSH_HOME`, `DSH_AGENTS_HOME`,
  `DSH_PERMISSION_MODE=workspace-write`, `DSH_TELEMETRY_DISABLED=1`, and `TMPDIR`/`TMP`/`TEMP`
  to the per-run spill directory, drops project bootstrap names, and fails when the
  composition check fails.
- [x] The confidential prefix launches through an absolute Node interpreter and absolute
  `bin.js`; the launcher, wrapper, patch and profile are outside the worktree and every temp
  prefix.
- [x] The Python wrapper runs with `-I`, and project `NODE_OPTIONS`/`PYTHONPATH`/`DYLD_*` do
  not reach the dsh or wrapper process.
- [x] dsh's spill directory is outside the shell-writable worktree/temp roots, and the shell
  temp root is `/tmp`.
- [x] `tool-web`, `tool-working-directory`, `tool-fs`, `otel` and `session-telemetry-otel`
  are disabled in the composed profile; approval is `ask`; the only permission presets are
  `read-only`/`ask` and `workspace-write`/`ask`, defaulting to `workspace-write`.
- [x] A non-vendor profile layer, an extra vendor bundle, profile dependencies, a profile-local
  `node_modules`, or any enabled id outside the stock set minus the three disabled tools
  refuses the launch.
- [x] A confidential dsh continuation with a stored session id is refused, not resumed.
- [x] A confidential dsh prompt says to leave changes uncommitted; the runner commits them.
- [x] Non-confidential dsh argv and env are unchanged.
- [x] A dsh older than 0.2.1-rc.2 is refused for confidential projects with a clear error.
- [x] Tests cover the wrapper, argv, env/temp pinning, composition checks, resume refusal,
  node launcher and the removed refusal.

## Verification

- [x] `python -m py_compile runner/*.py` passes with the venv Python.
- [x] `pytest tests/test_dsh_confidential.py tests/test_dsh_backend.py` passes.
- [x] The selected sandbox-independent `tests/test_project_dispatch.py` tests pass; the full
  file is an owner-run check because nested `sandbox-exec` is refused here.
- [x] The Seatbelt probe test is excluded in this agent sandbox because nested
  `sandbox-exec` is refused here; the exclusion is recorded.
- [x] `composition_problem` accepts a synthetic stock/patched pair with only the three tools
  disabled and the required entries.
- [x] `composition_problem` rejects a synthetic non-vendor layer header.
- [x] `composition_problem` rejects a synthetic extra enabled id.
- [x] `composition_problem` rejects a synthetic missing `fs-sandbox` id.
- [x] `composition_problem` rejects a synthetic `danger-full-access` permission preset.
- [x] The stock-bundle check rejects a profile with an added vendor bundle.
- [x] The wrapper test shows `(deny network*)` and a `(subpath "<realpath worktree>")` in the
  profile, with the command after `--`.
- [x] The wrapper test refuses a temp root outside the trusted prefixes.
- [x] The env test shows project `TMPDIR/TMP/TEMP` and a repository `.env` value are
  overwritten with the per-run spill directory (not the project or runner temp path).
- [x] The env test refuses `DSH_HOME` inside the worktree or temp.
- [x] The argv test shows a confidential dsh run gets the absolute Node launcher and the patch.
- [x] The argv test shows a non-confidential dsh run is unchanged.
- [x] The env test pins absolute `HOME`, `DSH_HOME` and `DSH_AGENTS_HOME`.
- [x] The env test rejects `HOME` or `DSH_HOME` inside the worktree or temp.
- [x] The env test shows ambient `DSH_SNAPSHOT`/`DSH_TOOLS_MODE`, project `NODE_OPTIONS`,
  `PYTHONPATH` and `DYLD_LIBRARY_PATH` are dropped, `DSH_TELEMETRY_DISABLED=1` is pinned,
  and the wrapper argv contains `-I`.
- [x] The composition test shows `otel` and `session-telemetry-otel` disabled and
  `approval` pinned to `ask`.
- [x] The wrapper test shows a read-only argv gets no worktree write grant and an option-like
  command is refused.
- [x] The env test shows an unsafe record location refuses the launch, an inherited
  `AGENTICOS_DSH_SPILL_DIR` is ignored by cleanup, and the per-run spill directory is removed
  by its caller.
- [x] The env test shows dsh's spill `TMPDIR` is outside the worktree/temp and the wrapper's
  shell temp root is `/tmp`.
- [x] The preflight test rejects a launcher/wrapper/patch path under a temp prefix.
- [x] The argv test shows a confidential dsh resume is refused.
- [x] The prompt test shows a confidential dsh run is told to leave changes uncommitted.
- [x] The composition test against the installed dsh passes and shows the required entries.
- [x] A manual review of the final diff confirms no non-confidential dsh path got the patch.
- [x] Live check on the user's runner: a confidential dsh `curl https://example.com` fails. — N/A: cannot run inside the agent sandbox (nested `sandbox-exec`); owner-run follow-up.
- [x] Live check: a write outside the ticket worktree fails in that shell. — N/A: cannot run inside the agent sandbox (nested `sandbox-exec`); owner-run follow-up.
- [x] Live check: a write inside the ticket worktree succeeds in that shell. — N/A: cannot run inside the agent sandbox (nested `sandbox-exec`); owner-run follow-up.
- [x] The live checks are recorded as owner-run, not claimed, because nested `sandbox-exec` — N/A: cannot run inside the agent sandbox (nested `sandbox-exec`); owner-run follow-up.
  is refused inside this agent session.
- [x] `docs/context-maintenance.md` records validation, the live-check limitation and the
  next action.

## Risks and trade-offs

- The wrapper and preflight are new security code; the plan review and a fresh Claude/Codex
  inspection must look for a bypass (env override, ignored patch, missing tool disable,
  persisted session, non-vendor layer, temp root, launcher shadowing).
- Disabling `tool-fs` removes native `read`/`write`/`edit` from confidential dsh; the model
  must read and edit through the confined shell. This is the cost of avoiding dsh's
  documented fs TOCTOU.
- Rejecting non-vendor profile/home layers and extra bundles means a user with a customized
  dsh profile cannot run confidential dsh until the profile is stock. This is deliberate
  fail-closed behavior.
- Refusing confidential dsh resume loses the continuation path for that backend; fresh runs
  work and the user can reset a card to todo.
- Denying `com.apple.dnssd.service`, `com.apple.trustd`, `com.apple.trustd.agent` and
  `com.apple.nsurlsessiond` also blocks those proxy paths in confidential verify and runner
  git. The profile remains a deny-list, not deny-default; another system daemon that fetches
  for a client could still proxy egress. The owner-run live probe should include an OCSP/AIA
  certificate check against a local listener, not only `curl`.
- A confidential dsh session continuation uses its session folder as the writable root, which
  can be a project's main checkout rather than a ticket worktree; this matches confidential
  Codex and is not a new hole, but it is broader than the phrase "ticket worktree".
- The live `sandbox-exec` path cannot be executed inside this dsh session (the agent's own
  sandbox refuses nesting); the owner-run live check is required before relying on the
  boundary.

## Progress Checklist

- [x] Write `runner/dsh_confine.py`.
- [x] Write `runner/scripts/dsh-confidential.yml`.
- [x] Add the DNS denial to `projects.sandbox_profile`.
- [x] Add the constants and absolute Node launcher to `runner/dsh_cli.py`.
- [x] Add the version floor and `confidential_cli_prefix` to `runner/dsh_cli.py`.
- [x] Add the stock-bundle, layer, enabled-set and required-entry checks to `runner/dsh_cli.py`.
- [x] Add `verify_confidential_launch` to `runner/dsh_cli.py`.
- [x] Update `project_runs.agent_cli` for the confidential prefix.
- [x] Update `project_runs.project_prompt` for the uncommitted-changes rule.
- [x] Update `_project_cmd` for the confidential patch and resume refusal.
- [x] Update `_project_exec_env` for the temp pins, runner env, launcher check and `DSH_HOME`
  refusal.
- [x] Update `tests/test_project_dispatch.py`.
- [x] Add `tests/test_dsh_confidential.py`.
- [x] Add the home/bootstrap/wrapper `-I` tests to `tests/test_dsh_confidential.py`.
- [x] Add the spill-temp separation test to `tests/test_dsh_confidential.py`.
- [x] Add the temp-install preflight test to `tests/test_dsh_confidential.py`.
- [x] Add the non-confidential `cli_prefix` compatibility test.
- [x] Run `python -m py_compile runner/*.py`.
- [x] Run the focused pytest selection.
- [x] Run the installed-dsh composition test.
- [x] Get an independent code inspection.
- [x] Resolve accepted inspection findings.
- [x] Update `AGENTS.md`.
- [x] Update `docs/context-maintenance.md`.
- [x] Archive this plan to `docs/exec-plans/completed/`.
- [x] Archive this review log to `docs/exec-plans/completed/`.
- [x] Commit on `agent/AGE-139`. — direct `git` commit is blocked by the workspace-write sandbox; the runner's post_run commits uncommitted worktree changes.

## Post-completion change (2026-10-23, user request)

The user rejected the `.git` write denial: confidential runs still need `git add` / `git commit`
(they simply do not push). The wrapper now receives the repo's git common dir as its second
launcher argument and adds it to the writable roots when dsh grants `workspace-write`; the
prompt asks a confidential dsh run to commit its work. The runner still commits any leftovers.
The `.git` deny clause was removed from `projects.sandbox_profile` and the wrapper. This
supersedes the `.git`-denial statements in the inspection log above; the APPROVED inspection
covered the pre-change snapshot, and the focused tests were rerun after this change.
Trade-off: this grants the repo's git common dir (refs, config, hooks, objects) to the
confined shell, matching confidential Claude/Codex `--add-dir common`; the prompt still says
not to push.

## Merge `main` (2026-10-23)

- Base `1ab614d`, main `fe466a5`, branch `agent/AGE-139`.
- Seven textual conflicts (AGENTS.md, context-maintenance, app.py, dsh_cli.py,
  project_runs.py, projects.py, test_project_dispatch.py). Main's version was kept and the
  AGE-139 changes were re-applied with `git merge-file`; `leaves_commit_to_runner` now leaves
  only non-confidential dsh and Codex to the runner, because confidential dsh gets the git
  common dir and commits its own work.
- Full suite: 960 passed / 87 failed, the same DSH-sandbox/PTY environment class as main.
  Focused dsh: 87 passed; `test_project_dispatch.py`: 88 passed / 11 nested-sandbox failures.
- The resolved tree is uncommitted because the agent sandbox cannot write the shared `.git`;
  the runner's `post_run` commits it. No push.
