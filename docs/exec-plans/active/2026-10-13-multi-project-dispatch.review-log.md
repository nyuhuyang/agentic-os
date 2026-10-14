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
