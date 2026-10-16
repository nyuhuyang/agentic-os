# Review log — 2026-10-15-dashboard-ui-updates

- Started: 2026-10-15, claudex-loop 2.2.2, mode=review
- Roles: host/coordinator = Claude Code (Opus 5.5); plan reviewer = Codex CLI 0.162.0 (CLI default model gpt-6.1-sol, effort high per config; no explicit --model/--effort)
- Scope: plan review only (user: "审阅"). Build not authorized.
- Rounds: max 20. Fallback: same-provider-on-unavailable. Inspection: n/a (no build).
- Budget choice: full plan, default model/effort (user, 2026-10-15)
- Pre-review edit: header "Two dashboard changes" → "Five" (plan lists A–E)
- Runner artifacts: /private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/43734fe6-827b-4456-8612-0540ddad69af/scratchpad/claudex (outside checkout)

## Round 1 — Codex — REVISE
- Result: /private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/43734fe6-827b-4456-8612-0540ddad69af/scratchpad/claudex/r1/claudex-_sxs88tm/result.json
- Plan SHA256 reviewed: 22a88e592a685cffc465e9bd42ffa2df31ed74617cf62af7777f67ebbbe2d48b
```json
{
 "verdict": "REVISE",
 "summary": "The plan has material gaps in session mutation safety, project-binding preservation, streaming coverage, replay persistence, and interactive-session exclusion.",
 "findings": [
  {
   "id": "R01",
   "severity": "high",
   "path": "docs/exec-plans/active/2026-10-15-dashboard-ui-updates.md:40",
   "evidence": "A promises unchanged session state after a failed write, but O_APPEND permits a short write, leaving a partial JSON record. Removing a transcript and its sidecar requires two renames; if the second fails, the transcript has already disappeared from the native picker. Neither operation has a rollback or recovery design.",
   "fix": "Specify transactional replacement for title changes and staged removal with rollback and crash recovery. Validate both destinations before mutation and cover short writes, second-move failures, and cross-filesystem trash locations."
  },
  {
   "id": "R02",
   "severity": "high",
   "path": "docs/exec-plans/active/2026-10-15-dashboard-ui-updates.md:42",
   "evidence": "The proposed live check relies on session identities that current writers do not retain. Terminal has no agent/session_id fields (runner/modules/pty/__init__.py:61); open_terminal uses the supplied session ID only to build argv. Streaming readers and project dispatch obtain session IDs without publishing them into running jobs. A resumed session idle for over two minutes can therefore pass the freshness check while still active.",
   "fix": "Persist agent/session identity in terminals and running jobs, including known resume IDs before launch and IDs discovered from initialization events. Serialize mutation checks with dashboard resume/launch admission so a new resume cannot race removal."
  },
  {
   "id": "R03",
   "severity": "high",
   "path": "runner/modules/linear/__init__.py:874",
   "evidence": "B adds labels at creation but misses subsequent destructive writers. _bg_sync_to_linear replaces the labeled local task with the create response at lines 886–894. The current GraphQL create response omits labels, and _normalize_linear_issue only shallow-copies it. _localize_issue also explicitly omits labels. After synchronization or local fallback, an unbound task can lose project:<key> and dispatch at the runner root.",
   "fix": "Preserve labels through background replacement and every local backup/update writer. Return a fully normalized create result containing labels, or retain the validated local labels until a complete fetch succeeds. Add coverage for dispatch immediately after synchronization and after tracker fallback."
  },
  {
   "id": "R04",
   "severity": "high",
   "path": "runner/modules/linear/__init__.py:883",
   "evidence": "The required local-first dispatch exposes an identity split. A task launched before Linear creation binds issue:local-… to worktree LOC-N. Synchronization replaces its ID and identifier, but record_id_alias only supports browser migration; _durable_binding, running-job checks, dispatched state, and reset generations do not resolve that alias. Dispatching the synchronized card can create a second worktree under the Linear identifier while the original run remains active.",
   "fix": "Define a stable task identity across synchronization, or migrate/resolve aliases consistently across bindings, running jobs, dispatch exclusion, reset generations, tracker updates, and history. Preserve the original worktree binding and test synchronization during an active local-first run."
  },
  {
   "id": "R05",
   "severity": "high",
   "path": "docs/exec-plans/active/2026-10-15-dashboard-ui-updates.md:139",
   "evidence": "Hooking the named stream readers does not cover all promised launch paths. Non-project Linear Claude/Codex dispatch uses proc.communicate (runner/modules/linear/__init__.py:707), and Codex retry also uses communicate (runner/app.py:3831). These paths emit nothing until exit. Linear dispatch additionally leaves session_id unset for Claude/Codex, preventing the promised finished-session resume.",
   "fix": "Explicitly migrate every launch caller to the common streaming pipeline, select Claude stream-json where required, and capture session IDs for each agent. Verify live events and resumability through the actual Linear and retry entry points."
  },
  {
   "id": "R06",
   "severity": "medium",
   "path": "runner/project_runs.py:206",
   "evidence": "C proposes disk replay when the ring is empty, but project run_agent only keeps raw events in a local list, the in-memory ring, and socket emissions (lines 219–246). It never creates the proposed stream log. After restart, project runs have no tool-event history for the endpoint to replay.",
   "fix": "Add durable event-log writing to project runs as well as the other launch paths, using approved confidential-record locations. Persist enough format metadata for replay and verify recovery after clearing all in-memory event state."
  },
  {
   "id": "R07",
   "severity": "high",
   "path": "docs/exec-plans/active/2026-10-15-dashboard-ui-updates.md:169",
   "evidence": "The existing worktree-tab lock does not protect runner-root cards: open_terminal acquires ticket_lock only when both project and ticket exist (runner/modules/pty/__init__.py:304). A runner-root interactive resume can overlap quick reply or another resume. For project retries, the HTTP route already pushes running state and schedules work before the background launch attempts the ticket lock, so contention produces an accepted failed attempt rather than the required refusal.",
   "fix": "Introduce task/session exclusion covering project and runner-root sessions. Reserve it before tracker changes, comments, or retry acceptance, and retain ownership through background launch or interactive termination. Return a clear busy response without adding an attempt."
  },
  {
   "id": "R08",
   "severity": "medium",
   "path": "runner/app.py:3865",
   "evidence": "C2 promises that quick reply continues the same session, but the reused retry path silently launches a fresh Claude/Codex session whenever a resumed process exits unsuccessfully. This includes failures after tools have already executed. Scheduled-entrypoint routing also takes precedence over resume at line 3850. Reusing the route unchanged therefore does not guarantee session continuity and can repeat work.",
   "fix": "Add a strict continuation mode for quick replies: require an eligible session, select its resume command, and report resume failure without automatically starting a new session or invoking an unrelated entrypoint."
  },
  {
   "id": "R09",
   "severity": "medium",
   "path": "runner/templates/index.html:4080",
   "evidence": "C2 requires card terminals to stay out of the bottom panel until explicitly shown. On every Socket.IO connection, the current client enumerates all server terminals and calls _attachTab for each, which creates bottom-panel tabs. A connection interruption or page reload would expose a card-only terminal in the panel automatically, even if initial opening is implemented correctly.",
   "fix": "Track presentation/attachment intent separately from terminal existence. Reconnection should restore only explicitly selected panel attachments; card-only terminals should remain discoverable through the running-terminal picker. Cover reconnection and reload."
  },
  {
   "id": "R10",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-15-dashboard-ui-updates.md:216",
   "evidence": "E promises that browsing writes nothing, but git status --porcelain -z can refresh and rewrite the index with default Git settings. projects._git does not disable optional locks; its hardening only disables fsmonitor and hooks. Browsing an active worktree can therefore mutate Git state and contend with the agent's index operations.",
   "fix": "Run browser Git queries with --no-optional-locks or GIT_OPTIONAL_LOCKS=0 while retaining existing hardening and confinement. Include an index-unchanged check for browsing."
  }
 ],
 "coverage": [
  "Read the complete on-disk plan and verified its SHA256 matches the supplied digest.",
  "Traced session readers, project/worktree bindings, ticket locks, and confidential-run policy in runner/projects.py and runner/project_runs.py.",
  "Inspected dashboard launch, streaming, retry, event replay, run-log writers, status updates, request-token enforcement, and maintenance gating in runner/app.py.",
  "Traced local task creation, Linear background synchronization, ID aliases, cache/backup writers, dispatch, and GraphQL normalization.",
  "Inspected PTY lifecycle, resume admission, attachment/replay, dashboard terminal reconnection, card actions, and relevant existing test source.",
  "Reviewed A–E and C2 against the plan's acceptance criteria; no additional material issue identified for D."
 ],
 "limitations": [
  "Static plan review only; no edits, tests, browser checks, native CLI operations, or delegation were performed.",
  "Native Claude/Codex rename and archive behavior and live Linear API behavior were not independently exercised.",
  "SPEC.md and broader architecture/design documents were not inspected; spec-fidelity conclusions use the supplied plan's acceptance criteria.",
  "Planned helpers and UI behavior are not implemented here; findings identify concrete contradictions and integrations the plan must address."
 ]
}
```

### Dispositions
Round 1 dispositions (host = Claude). All 10 findings verified against the code and ACCEPTED; plan revised.

- R01 accepted: Claude rename records size, single os.write, ftruncate back on short/failed write (live sessions refused, so no concurrent appender). Remove: precheck both trash destinations, transcript first then sidecar, roll transcript back if sidecar move fails, EXDEV refused before any move, crash-between-renames outcome documented (orphan sidecar, no data loss). Tests added.
- R02 accepted: Terminal gains agent/session_id; running jobs record agent_session_id (pre-launch for resumes, from init event otherwise) on every path; per-session admission lock shared by mutation and resume/retry admission. Tests added.
- R03 accepted: label-preserving writers listed (_bg_sync_to_linear, _localize_issue, _normalize_linear_issue, create mutation selection). Tests added.
- R04 accepted with a narrower fix: instead of alias resolution across bindings/jobs/generations, dispatch/retry of a task whose Linear create is in flight is refused (409) via a pending-sync set; a failed create leaves the task local-only permanently (no re-sync path exists in modules/linear), so no identity split can occur. The old acceptance criterion "dispatched before its Linear copy exists" was replaced accordingly.
- R05 accepted: Linear Claude/Codex dispatch and Codex retry move to streaming readers; session ids captured on every path. Tests added.
- R06 accepted: durable stream log on every path incl. project run_agent, with format header; confidential runs use the confidential records location. Tests added.
- R07 accepted: runner-root cards get task_lock(issue_id); retry route reserves lock synchronously before tracker changes and hands it to the background launch; 409 with no attempt logged. Tests added.
- R08 accepted: quick reply uses strict continuation mode (resume required, no entrypoint routing, no fresh-session fallback). Tests added.
- R09 accepted: per-terminal in_panel flag; reconnect attaches only in_panel terminals. Test added.
- R10 accepted: GIT_OPTIONAL_LOCKS=0 for browse git queries; index-unchanged test added.

## Round 2 — Codex — REVISE
- Result: /private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/43734fe6-827b-4456-8612-0540ddad69af/scratchpad/claudex/r2/claudex-t16or7cx/result.json
- Plan SHA256 reviewed: 67906c590d37eea404b361dc9550772f32afd1bdf13f1c92988262d30dd56909
```json
{
 "verdict": "REVISE",
 "summary": "The revision addresses eight prior findings at plan level. The narrower R04 fix and the R07 lock design still have concrete gaps described below.",
 "findings": [
  {
   "id": "R11",
   "severity": "high",
   "path": "docs/exec-plans/active/2026-10-15-dashboard-ui-updates.md:101",
   "evidence": "Clearing pending-sync in finally does not establish that a failed create left no Linear issue. LinearClient._graphql catches request timeouts and returns {} (runner/linear_client.py:218–238), which create_issue converts to None. If Linear commits the issue before the response is lost, the guard clears and permits local dispatch while polling can discover the remote copy. Both identities can then acquire separate worktree bindings. A failure persisting the alias after successful creation has the same problem.",
   "fix": "Distinguish confirmed rejection from an unknown creation outcome. Persist a correlation identifier and creation state, reconcile ambiguous outcomes before permitting dispatch, and recover across restart. Cover a lost response after remote commit and failure between remote creation and local replacement."
  },
  {
   "id": "R12",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-15-dashboard-ui-updates.md:86",
   "evidence": "The revised promise that failed creates become permanently local-only requires changes beyond removing the pending guard. The polling loop replaces caches with remote issues and preserves only terminal local entries (runner/modules/linear/__init__.py:435–469), so a failed-create Todo task disappears when another remote issue exists. _push_sync and post_comment choose Linear globally rather than per task (lines 1258–1296); completion updates for local-* IDs therefore miss LocalTracker, leaving persisted state stale.",
   "fix": "Represent per-task tracker ownership explicitly. Preserve pending and confirmed local-only tasks during polling, and route their edits, completion states, comments, and close actions through LocalTracker even while Linear is configured. Verify persistence through polling and restart."
  },
  {
   "id": "R13",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-15-dashboard-ui-updates.md:179",
   "evidence": "The proposed runner-root lock uses a tracker ID, but dashboard /run cards have no tracker ID. Their records contain task_id=run_id without linear_issue_id (runner/app.py:3232–3240), and retry explicitly falls back to that task ID (lines 3689–3693). task_lock(issue_id) therefore leaves these advertised cards without a defined exclusion key; skipping the lock permits overlapping continuations, while using None conflates unrelated cards.",
   "fix": "Define a canonical server-resolved lock key using tracker ID when present and the root task ID otherwise. Use it consistently for interactive opening, retry, quick reply, and dispatch. Cover exclusion across multiple attempts of a /run task and independence between unrelated /run tasks."
  }
 ],
 "coverage": [
  "Verified the on-disk plan SHA256 matches 67906c590d37eea404b361dc9550772f32afd1bdf13f1c92988262d30dd56909.",
  "Compared all ten prior findings and host dispositions against the revised A–E and C2 requirements.",
  "Traced Linear creation failures, pending-task publication, alias replacement, polling/cache writers, local backup, tracker updates, and comments.",
  "Traced dashboard run identities, retry ancestry, durable project bindings, background scheduling, and PTY lock ownership.",
  "Accepted the plan-level resolutions for R01–R03, R05–R06, and R08–R10 without reopening them."
 ],
 "limitations": [
  "Static plan review only; no files were edited, tests run, or work delegated.",
  "Native CLI behavior, browser behavior, and live Linear failure scenarios were not exercised.",
  "Reviewed fidelity against the supplied acceptance criteria; SPEC.md and broader design documents were not inspected."
 ]
}
```

### Dispositions
Round 2 dispositions (host = Claude). All 3 verified and ACCEPTED.

- R11 + R12 accepted by narrowing scope further rather than building creation-state reconciliation: while the Linear tracker is active, any `local-*` id is refused for dispatch/retry (409, no state change), regardless of whether its create is pending, failed, or had a lost response. Only a Linear-id copy ever runs, so no LOC-N binding can be orphaned and no second binding can appear; a lost-response remote copy is created with labelIds, so it carries the project. With the local tracker only (no Linear), local ids dispatch as today. The pending-set guard and the "failed create becomes local-only and dispatches" promise are removed. The pre-existing local-first gaps (polling drops failed-create Todo cards, duplicate after lost response, global tracker routing for local-* edits) are recorded as an explicit non-goal: B neither introduces nor relies on them, since such cards are never dispatched.
- R13 accepted: runner-root lock key is server-resolved card_key = linear_issue_id if present, else root task_id (the retry ancestry key); used by interactive open, retry, quick reply and dispatch. Tests added for shared lock across attempts of one /run task and independence of unrelated /run tasks.

## Round 3 — Codex — APPROVED
- Result: /private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/43734fe6-827b-4456-8612-0540ddad69af/scratchpad/claudex/r3/claudex-2r6wmjaa/result.json
- Plan SHA256 approved: 41065a410b2c2a76afa0a45b8fe1971c91c03959ad0ea07310bfe258bde4cfde
- runner check: "Approval matches the current plan; assurance=cross_provider."
```json
{
 "verdict": "APPROVED",
 "summary": "All prior findings are addressed at plan level through explicit fixes or the accepted scope reduction. No material unresolved defects identified in the revised plan.",
 "findings": [],
 "coverage": [
  "Verified the on-disk SHA256 matches 41065a410b2c2a76afa0a45b8fe1971c91c03959ad0ea07310bfe258bde4cfde.",
  "Checked R11–R12 against the unconditional local-ID dispatch/retry refusal while Linear is active, including lost-response and background replacement paths.",
  "Checked R13 against server-resolved card identity, retry ancestry, dashboard /run records, project bindings, and PTY admission.",
  "Traced related Linear polling, cache replacement, tracker-state writers, and dispatch callers beyond the plan's named files.",
  "Retained the previously reviewed resolutions for session mutation safety, streaming, replay persistence, strict continuation, terminal presentation, and read-only Git queries."
 ],
 "limitations": [
  "Approval covers the plan, not an implementation; build inspection and validation remain outstanding.",
  "No edits, tests, native CLI operations, browser checks, or delegation were performed.",
  "Creation reconciliation and local-card polling/edit gaps remain explicitly deferred; approval accepts the revised restriction preventing those cards from dispatching while Linear is active.",
  "SPEC.md and broader design documents were not inspected."
 ]
}
```

## Outcome
- APPROVED after 3 of 20 rounds; assurance=cross_provider; no fallback used.
- Post-approval edit: only the shared checkbox 'Codex plan review returns APPROVED' ticked. New plan SHA256: 75442c97dae54cff2bb7a1d9ee969ad36c8fc686001a74ada60de31437612bf9. Before build, rerun the runner check — it will report the hash change; the diff is the single checkbox line.
- Deferred (non-goal, needs own plan): local-first create reconciliation / polling / per-task tracker routing while Linear is active.
- Build: not authorized in this session.

## Post-approval changes (found at build start, 2026-10-15)
- Plan edited by the runner-write-safety session after round-3 approval: C0 prerequisite added (one run_agent_process lifecycle; user decision). Code changed: fb798bc landed. Approval void; runner check: "Plan changed after approval".
- User authorized build with Claude ("正式开始用claude build"). Round 4 review requested before building.

### Round 4 request
Round 4 request (host = Claude). Your round-3 APPROVED is void: the plan changed after approval, and the code it references changed.

Changes since round 3:
1. Plan: part C gained a prerequisite C0 (user decision, 2026-10-15, written by the runner-write-safety session): extract one `run_agent_process(run_id, cmd, …)` in runner/app.py that replaces the five near-copies of the Popen → register → stream/communicate → deadline → group kill/reap → claim → owner-only record/tracker sequence (`/run` entrypoint, `/run` agent, retry `_dispatch_cmd`/`_do_retry`, Linear `_dispatch_issue_counted`, project helper). The Linear/retry streaming migration in C must be built on it. Its behaviour is pinned by tests/test_runner_write_safety.py, which must pass unchanged. See the C Decisions "Prerequisite" bullet, the C0 Approach item and the three C0 checklist items.
2. Code: commit fb798bc (runner write safety: process groups, stoppable readers, single-owner runs, 466 tests) landed after your round-3 read. Line references in the plan may have moved. The completed plan is docs/exec-plans/completed/2026-10-15-runner-write-safety.md (its "Root fix for the duplicated lifecycle" note at ~L152 is the origin of C0).
3. Plan: header "Two" → "Five" was already in your round-3 snapshot; the shared "Codex plan review returns APPROVED" box is unticked again.

Please check specifically:
- Is C0 well-specified and safe as written: signature, which paths must call it, what may stay outside (project helper "where its worktree/verify phases allow, or the plan records why not"), and whether the grep-based checklist item is a sound completion test against the actual current code.
- Whether earlier resolutions (R02 session identity on every launch path, R05 streaming migration, R06 durable log, R07/R13 card lock taken by retry admission, R08 strict continuation) still fit the post-fb798bc code and compose with C0 rather than adding a sixth copy.
- Whether the earlier resolutions for A, B, D, E still hold after fb798bc.

## Round 4 — Codex — REVISE
- Result: /private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/43734fe6-827b-4456-8612-0540ddad69af/scratchpad/claudex/r4/claudex-_it1bh01/result.json
- Plan SHA256 reviewed: 632287d5d777a7a83e8dcec1ceba3cc56f667a52cbda90b8daca0e81e53b3f76
```json
{
 "verdict": "REVISE",
 "summary": "C0 needs explicit boundaries between process completion and run completion. Its project exception and completion check are insufficiently defined, and the log-header requirement conflicts with newly frozen tests. Earlier A, B, D and E resolutions remain valid.",
 "findings": [
  {
   "id": "R14",
   "severity": "high",
   "path": "docs/exec-plans/active/2026-10-15-dashboard-ui-updates.md:147",
   "evidence": "The proposed helper accepts one cmd but owns the terminal claim and record. Retry currently executes a failed resume and its fallback under one run_id, claiming completion only after the fallback decision (runner/app.py:3885–3957). Finalizing the first helper invocation removes the job, causing fallback to be skipped or rejected by _register_proc. The signature also provides no attempt/fallback policy to distinguish ordinary retry from strict quick reply. Existing tests explicitly exercise cancellation and command-construction failure between these processes.",
   "fix": "Define a run-level coordinator that owns the complete attempt sequence, including lazy fallback construction and an explicit strict-continuation policy, with one final claim and record. Alternatively, separate a reusable process engine from that coordinator. Preserve process handles through between-attempt failures and keep card reservations until the logical run ends."
  },
  {
   "id": "R15",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-15-dashboard-ui-updates.md:167",
   "evidence": "The project integration decision is deferred, and the grep check cannot establish lifecycle consolidation. Project agents launch indirectly through project_runs.run_agent → projects.spawn; start_new_session=True is actually in runner/projects.py:142. Leaving that independent reader/timeout engine untouched can pass a check limited to app.py and Linear. Conversely, applying the proposed claim-at-process-end behavior removes the project job before post_run verification, breaking cancellation during verification and final binding/verify recording (runner/app.py:3039–3090; tests/test_project_dispatch.py:524).",
   "fix": "Specify the project boundary now: share process execution while retaining project orchestration, cancellation through verification, shutdown registration, and final confidential recording until all phases finish. Define any exemption precisely. Replace the literal grep criterion with caller tracing and checks that each required launch path reaches the shared engine without duplicate terminal ownership."
  },
  {
   "id": "R16",
   "severity": "medium",
   "path": "docs/exec-plans/active/2026-10-15-dashboard-ui-updates.md:151",
   "evidence": "The mandatory first log header conflicts with tests introduced by fb798bc that must remain unchanged. test_timeout_kills_the_whole_group parses the first stream-log token as a PID (tests/test_runner_write_safety.py:75), and test_escaped_descendant_cannot_pin_the_readers does the same for cleanup at lines 99–101. Adding the header through the shared readers makes those conversions fail and prevents the latter cleanup from killing its escaped descendant.",
   "fix": "Preserve the existing raw-log contract and store agent/format metadata separately, or explicitly define a compatible reader mode that leaves these existing calls unchanged. Add production replay coverage for the chosen metadata mechanism."
  }
 ],
 "coverage": [
  "Verified the supplied plan SHA256 and confirmed repository HEAD is fb798bc.",
  "Traced both /run paths, retry and fallback, Linear dispatch, project execution, registration, ownership claims, and terminal recording.",
  "Inspected related cancel, stall, shutdown, project spawn/reap, and verification paths beyond the plan's named files.",
  "Read relevant write-safety and project-dispatch test source covering ownership, fallback, cleanup, verification cancellation, and log assumptions.",
  "Rechecked session identity, streaming, durable replay, card-lock admission, and strict continuation against C0.",
  "Confirmed fb798bc leaves projects.py, project_runs.py, linear_client.py, index.html, and LocalTracker unchanged; no additional material A, B, D or E defect identified."
 ],
 "limitations": [
  "Static plan review only; no edits, tests, native CLI operations, browser checks, or delegation were performed.",
  "C0 is not implemented, so findings identify contract conflicts and unresolved integration boundaries.",
  "Historical test-pass claims were not independently verified.",
  "SPEC.md and unrelated design documents were not inspected; the explicitly referenced completed write-safety plan was inspected."
 ]
}
```

### Dispositions
Round 4 dispositions (host = Claude). All 3 verified against current code and ACCEPTED.

- R14 accepted: C0 is now a process engine only. `run_agent_process(run_id, cmd, *, stream, timeout, cwd, env)` runs exactly one process (Popen in own session, _register_proc handshake raising _RunEnded, streaming readers or communicate, single deadline, _kill_and_reap after launch, RUN_EVENTS/durable log) and returns the parsed result. It never claims, records or pushes. Each caller keeps its coordinator: retry runs resume then a lazily built fallback under one run id and claims once after the fallback decision; strict quick reply is the same coordinator with fallback disabled; handles stay registered between attempts (attempt_proc rule); card reservations held until the caller's run ends. New "C0 boundary" decision bullet + revised approach item + checklist test for resume→fallback/cancel-between/fallback-construction-failure/strict.
- R15 accepted: project path explicitly exempt — stays on projects.spawn / project_runs.run_agent (shutdown group registry, verify phases, binding and confidential recording unchanged); it only gains the durable log. Grep criterion replaced by a spy test over the four callers asserting launches go through the engine and exactly one terminal record per run, plus a project-dispatch test item (cancel during verification, final binding/verify record).
- R16 accepted: raw stream-log contract unchanged (first token still what tests read); replay metadata {agent, format} goes to a separate `<run>_stream.meta.json` sidecar written at launch; replay test covers the sidecar.

## Round 5 — Codex — APPROVED
- Result: /private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/43734fe6-827b-4456-8612-0540ddad69af/scratchpad/claudex/r5/claudex-36fsfd1w/result.json
- Plan SHA256 approved: 04f33a952af30caec8d67c5ecbc1f179f1439bd047a6bd1bedf1e0911bdafef9 (HEAD fb798bc)
- runner check: Approval matches the current plan; assurance=cross_provider.
```json
{
 "verdict": "APPROVED",
 "summary": "R14–R16 are resolved at plan level. C0 now separates process execution from run completion, defines the project exemption, and preserves the raw-log contract. No material unresolved plan defects identified.",
 "findings": [],
 "coverage": [
  "Verified the on-disk SHA256 matches 04f33a952af30caec8d67c5ecbc1f179f1439bd047a6bd1bedf1e0911bdafef9; repository HEAD remains fb798bc.",
  "Checked process registration, retry fallback, retained process handles, caller-owned completion, and strict-continuation requirements.",
  "Checked the explicit project exemption against shutdown registration, verification phases, cancellation, and final recording.",
  "Confirmed sidecar metadata avoids the existing tests' first-token log-format conflict.",
  "Reviewed the replacement launch-spy checks and relevant write-safety and project-dispatch test source.",
  "Retained earlier resolutions for session identity, card reservations, project labels, request gating, and read-only file browsing."
 ],
 "limitations": [
  "Approval covers the plan; implementation inspection and validation remain outstanding.",
  "No edits, tests, native CLI operations, browser checks, or delegation were performed.",
  "Deferred Linear creation-reconciliation gaps remain outside the approved scope.",
  "SPEC.md and unrelated design documents were not inspected."
 ]
}
```

## Build (Claude)
- Builder: Claude Code (Opus 5.5), host. Authorized by user: "正式开始用claude build".
- Order: D → E → A → B → C0 → C → C2. Proof: .venv/bin/python -m pytest tests/ -q -p no:cacheprovider
