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

### Build summary (Claude, base 995924c)
- Order built: D → E → A → B → C0 → C → C2, one checkout, no other writers.
- C0: `run_agent_process` in runner/app.py; /run (both paths), retry `_dispatch_cmd` (each attempt incl. fallback) and Linear `_dispatch_issue` call it; project path stays on projects.spawn / project_runs.run_agent and gains the durable log + meta sidecar. Readers now start on a real thread (`_start_counted(..., _thread=_REAL_THREAD)`): the write-safety harness swaps in synchronous threads, under which a streaming reader could never time out (test_non_streaming_retry_timeout_kills_the_group); tests/test_runner_write_safety.py passes unchanged.
- Deviation: tests/test_reset_gen.py FakeLinearClient gained `ensure_label` / `label_ids` (B's background create now calls them).
- Deviation (C, per C2 decision): the card's Terminal action opens the card detail's Terminal tab, not a bottom-panel tab; "Show in panel" opens the panel run tab.
- Manual: isolated runner (verify skill, port 8599, fake claude, fixture ~/.claude/~/.codex stores via CLAUDE_CONFIG_DIR/CODEX_HOME) — D, E, A, B (local tracker), C, C2 flows checked in a headless browser. Not done: native pickers (A item 74), live Linear (B item 125), real `open -R` click.
- Proof: `.venv/bin/python -m pytest tests/ -q -p no:cacheprovider` → 522 passed (baseline 466 at 995924c).

## Inspection 1 (fresh Codex) — REVISE
- Result: /private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/43734fe6-827b-4456-8612-0540ddad69af/scratchpad/claudex/i1/claudex-gbmupcix/result.json (assurance cross_provider)
```json
{
 "verdict": "REVISE",
 "summary": "Material defects remain in project dispatch, card locking, process streaming, terminal recovery, and replay consistency.",
 "findings": [
  {
   "id": "UI-01",
   "severity": "high",
   "path": "runner/modules/linear/__init__.py:931",
   "evidence": "Failed ensure_label calls return None and are silently discarded, after which create_issue still runs. A transient label-creation failure can therefore create a confirmed Linear issue without project:<key>. The cache temporarily invents the missing label at line 938, but polling replaces it with the remote labels and _sync_cache_to_local overwrites the backup. Dispatch before a durable binding exists then runs at the runner root, potentially bypassing the selected project's confidential policy.",
   "fix": "Require successful resolution of every requested label before creating the issue. Do not confirm synchronization until the remote issue's project label is established; keep unresolved local IDs non-dispatchable."
  },
  {
   "id": "UI-02",
   "severity": "high",
   "path": "runner/modules/linear/__init__.py:667",
   "evidence": "card_locked only probes and immediately releases the lock. Runner-root dispatch then performs routing, potentially for 60 seconds, and launches without acquiring card_lock. An interactive terminal opened after the probe can overlap the dispatch; a retry can overlap it too. The PATCH route likewise probes before changing tracker state and scheduling, so contention can produce an accepted state change instead of the required side-effect-free 409.",
   "fix": "Reserve the canonical card/ticket lock synchronously before tracker changes and scheduling, transfer ownership to dispatch, and retain it through completion. Apply the same reservation to other dispatch callers."
  },
  {
   "id": "UI-03",
   "severity": "high",
   "path": "runner/modules/pty/__init__.py:321",
   "evidence": "Runner-root exclusion depends on the browser supplying card_key. The normal 'Show in panel' → 'Resume in tab' flow calls _resumeFromRunTab at index.html:4306, which sends no card_key. That interactive session holds no card lock, so quick reply or retry can resume the same session concurrently. session_lock only covers opening admission and does not prevent this overlap.",
   "fix": "Pass a run reference through every resume entry point and resolve its canonical card key on the server. Require the corresponding lock for card-bound resumes instead of trusting an optional browser key."
  },
  {
   "id": "UI-04",
   "severity": "high",
   "path": "runner/app.py:835",
   "evidence": "The newly migrated Linear Claude/Codex dispatch and Codex retry use readers that drain stdout first and read stderr only after process exit. A CLI that fills its stderr pipe blocks before closing stdout, causing an otherwise healthy run to stall or time out. The final stderr.read is also outside the deadline and can hang if a descendant retains that pipe. These paths previously used communicate, which drained both streams.",
   "fix": "Drain stdout and stderr concurrently under the same deadline, stop event, exception handling, and cleanup mechanism, as _stream_dsh_run already does."
  },
  {
   "id": "UI-05",
   "severity": "high",
   "path": "runner/templates/index.html:4420",
   "evidence": "The term_open callback uses the current global _cardKey and attaches into the current modal rather than the card that initiated opening. If the user opens interactive session A and switches to card B before the response arrives, A's terminal is registered under B and displayed there. Input from B's terminal view then executes in A's session and project. Several other asynchronous card-terminal callbacks have the same missing ownership check.",
   "fix": "Capture the initiating card key, run ID, and view generation before each asynchronous operation. Store results against that captured identity and update or attach the visible terminal only if the initiating view remains current."
  },
  {
   "id": "UI-06",
   "severity": "medium",
   "path": "runner/app.py:4163",
   "evidence": "Strict quick reply disables fallback correctly, but a failed Claude or Codex resume still records status review because only dsh failures select error. A resume rejected with a nonzero exit can therefore look like a completed review attempt, contrary to C2's explicit requirement to report failed continuation as an error. The strict-failure test checks record count but never checks its status.",
   "fix": "Record an error when strict continuation returns unsuccessful, preserve a useful failure explanation, and strengthen the test to assert status and error content."
  },
  {
   "id": "UI-07",
   "severity": "medium",
   "path": "runner/templates/index.html:4376",
   "evidence": "Existing embedded terminals are found only through the in-memory _cardTerminals map. Reloading clears that map, while reconnect deliberately ignores card-only terminals. Reopening the card consequently shows the run replay; 'Open interactive' attempts a second terminal and receives busy from the existing terminal's lock. A socket reconnect also does not rejoin the embedded terminal's output room.",
   "fix": "Discover existing card terminals from server state using stable card/run identity and reattach them without changing in_panel. Rejoin the active embedded terminal on socket reconnect."
  },
  {
   "id": "UI-08",
   "severity": "medium",
   "path": "runner/app.py:3891",
   "evidence": "Ending an interactive session creates a new run ID containing only 'interactive session ended', an empty prompt, and no stream log. Board latest-run selection prefers this newer record over the actual execution. Reopening the card therefore defaults to an empty replay with the marker pinned, rather than the last agent run. Subsequent retry context also takes the marker's empty prompt and output.",
   "fix": "Represent closure as an audit event distinct from an executable attempt, or explicitly retain and resolve the last execution reference for replay, pinned messages, and continuation context. Preserve session and generation metadata server-side."
  },
  {
   "id": "UI-09",
   "severity": "medium",
   "path": "runner/app.py:3423",
   "evidence": "last_message and waiting are derived from the complete recorded output. Project completion appends '[verify tail]' and test output at line 3176. When an agent ends with 'Shall I start the build?' and verification emits several lines afterward, the question can fall outside waiting_question's final three lines and the pinned view displays verification output instead of the assistant's question.",
   "fix": "Persist or extract the actual last assistant message separately from verification output and other run summaries, and use that field for both pinning and waiting detection."
  },
  {
   "id": "UI-10",
   "severity": "medium",
   "path": "runner/app.py:2375",
   "evidence": "Ordinary retry can run a failed resume and then a fresh fallback under one run ID. Each stream reader opens the same durable log with mode 'w', while the event ring retains both processes' events. After restart, replay loses the failed resume's events and differs from the live history.",
   "fix": "Initialize the durable log once per logical run and append subsequent process attempts, or retain separate attempt logs with ordered replay metadata."
  },
  {
   "id": "UI-11",
   "severity": "medium",
   "path": "runner/templates/index.html:1179",
   "evidence": "A failed root tree request leaves the cache empty, clears loading, and calls _renderProjects at line 1226. Rendering immediately starts the same request again. A removed worktree, persistent Git failure, or rejected request therefore creates an unbounded request-and-render loop without another user action.",
   "fix": "Track failed load state separately from unloaded state. Stop automatic retries after failure and provide an explicit retry action or bounded backoff."
  },
  {
   "id": "UI-12",
   "severity": "medium",
   "path": "runner/project_runs.py:254",
   "evidence": "The common renderer does not provide the promised tool visibility for every backend. Codex command calls appear only on item.completed, so a long-running command is invisible while executing. DSH tool_result events render only their status and discard the result content, including the result field used by tests/test_dsh_backend.py. Tool arguments are also silently cut to 80 characters.",
   "fix": "Render tool-start events with their arguments and render bounded result content for each supported backend. Handle completion without duplicating the call, and make argument truncation explicit or expandable."
  },
  {
   "id": "UI-13",
   "severity": "medium",
   "path": "runner/templates/index.html:4396",
   "evidence": "_cardTermLoad enables live socket writes before awaiting the event snapshot, then resets the terminal when the HTTP response arrives. An event emitted after the server takes its snapshot but before the browser processes the response is first displayed live and then erased; it is absent from the snapshot. The panel's _loadRunEvents has the same race.",
   "fix": "Sequence events and return a snapshot cursor, buffering live events during loading and applying only events newer than the cursor. Use the same handoff for embedded and panel views."
  }
 ],
 "coverage": [
  "Verified the supplied plan digest and all 16 manifest file SHA256 values against disk.",
  "Reviewed the supplied plan, review log, changed implementation hunks, and all added or changed test files.",
  "Traced session resolution, rename/remove, freshness checks, admission claims, and PTY session identity.",
  "Traced project-label creation through Linear normalization, polling, cache replacement, local backups, dispatch, and durable bindings.",
  "Traced process-engine callers, retry fallback, strict continuation, cancellation, streaming readers, durable logs, and replay.",
  "Inspected card terminal actions, panel resume, reconnect, interactive closure, attempt selection, file browsing, and Run tests wording.",
  "Inspected related shared-state and lifecycle code beyond the manifest, including reset_gen.py, state_io.py, run_skill.py, usage_reader.py, stall detection, and relevant existing test source."
 ],
 "limitations": [
  "Static inspection only: no files edited, tests executed, browser/native CLI operations performed, or work delegated.",
  "Historical test-pass and manual-check claims were not independently verified.",
  "Native Claude/Codex picker behavior and live Linear API behavior were not exercised.",
  "SPEC.md and broader architecture/design documents were not inspected; fidelity was assessed against the supplied plan and inspected implementation contracts."
 ]
}
```

### Dispositions (host Claude; all 13 verified against the code and accepted)
- UI-01 fixed: every requested label must resolve or the background create raises; the task keeps its local id (non-dispatchable while Linear is active). Test `test_unresolved_label_keeps_the_task_local`.
- UI-02 fixed: runner-root Linear dispatch takes `card_lock(issue_id)` before routing and holds it through the run (released in the outer `finally`); refused with a log line when held. Test `test_runner_root_dispatch_holds_the_card_through_the_run`. Residual (accepted): the PATCH route's probe and the dispatch's own lock acquisition are separate steps; in that race the dispatch is still refused by the lock (project path: helper's ticket lock, as before) rather than the PATCH returning 409.
- UI-03 fixed: resume tabs carry `run_id`; `open_terminal` resolves the card key from the run record server-side (any browser `card_key` is ignored) and takes the card lock for runner-root cards. The run tab's "Resume in tab" passes its run id. Test updated (spoofed key ignored).
- UI-04 fixed: `_read_both` drains stdout and stderr side by side under one deadline for the claude and text readers (dsh already did). Tests `test_stderr_flood_does_not_stall_the_reader`; `test_stream_readers_are_counted` now expects both readers counted.
- UI-05 fixed: card-terminal JS rewritten with a view generation; every async callback drops its result unless its card/attempt is still current; a session opened for a card the user left is found later by card key.
- UI-06 fixed: a failed strict continuation records status `error` with the resume failure; test asserts status and error.
- UI-07 fixed: the card's interactive session is discovered from `term_list` by server-set `card_key`; reconnect rejoins the embedded terminal's room. Browser-checked: reload → reopen card → reattached, panel still empty.
- UI-08 fixed: the closure record is marked `interactive_ended` (audit entry) and copies the source prompt; the board's latest-run selection and the attempt picker skip it. Browser-checked: latest run stays the real run.
- UI-09 fixed: pinned message and "Waiting" use the output without the `[verify tail]` suffix. Test `test_waiting_ignores_the_verify_tail`.
- UI-10 fixed: stream logs open in append mode, so resume + fallback under one run id both replay. Test in `test_fallback_keeps_the_failed_attempts_log_and_seq_cursor`.
- UI-11 fixed: failed tree loads are remembered; no auto-retry loop; explicit Retry button.
- UI-12 fixed: Codex command calls render on `item.started` (output on completion, no duplicate), dsh tool results show content, tool arguments cut visibly at 300 chars with "…". Renderer test extended.
- UI-13 fixed: `EventRing` numbers lines; `run_event` carries `seq`; `/events` returns `cursor`; panel and card views buffer live lines while loading and apply only `seq > cursor`.
- Proof after fixes: 527 passed.

### Convergence bar (host, from inspection 2 on)
Lesson from runner-write-safety (10 inspections): later rounds drift into injected one-shot failures. From here, accepted fixes are: high findings, and medium findings with a realistic trigger on this local, single-user macOS runner. Findings that need an injected failure of the runner's own primitives (thread start, a one-shot write error) or a non-macOS environment are recorded as accepted risk with reasons, not fixed.

## Inspection 2 (fresh Codex) — REVISE
- Result: /private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/43734fe6-827b-4456-8612-0540ddad69af/scratchpad/claudex/i2/claudex-k15pvgc5/result.json (assurance cross_provider)
```json
{
 "verdict": "REVISE",
 "summary": "Material gaps remain in session exclusion, dispatch admission, interrupted-run recovery, and interactive-terminal lifecycle handling. Project defaults and event rendering also have concrete defects.",
 "findings": [
  {
   "id": "UI2-01",
   "severity": "high",
   "path": "runner/modules/pty/__init__.py:321",
   "evidence": "The Projects panel calls openResumeTab without run_id (index.html:1462). A runner-root task's session listed under the registered runner project therefore acquires neither a ticket lock nor a card lock. Quick reply or retry can then resume that session concurrently. session_lock only protects opening admission.",
   "fix": "Resolve card ownership from agent/session identity for every resume entry point, including Projects-panel resumes, and retain the corresponding card or ticket lock until the terminal closes."
  },
  {
   "id": "UI2-02",
   "severity": "medium",
   "path": "runner/modules/linear/__init__.py:1042",
   "evidence": "The PATCH route still probes and releases the card lock before changing tracker state and scheduling dispatch. An interactive terminal opened after that probe causes dispatch to be refused later, while PATCH has already returned success and changed the issue to In Progress. The project path can additionally log a failed attempt when its later ticket-lock acquisition fails. This violates C2's side-effect-free 409 requirement; the review-log disposition explicitly acknowledges the remaining race.",
   "fix": "Reserve the canonical card/ticket lock synchronously before mutations or scheduling, transfer that reservation to dispatch, and hold it through completion."
  },
  {
   "id": "UI2-03",
   "severity": "high",
   "path": "runner/app.py:819",
   "evidence": "The common publisher streams Claude/Codex activity without updating last_progress_at. Neither their readers nor _write_run_progress_json update it. The existing stall detector checks that timestamp and kills non-project jobs after 300 seconds, even while their new terminal view continuously displays activity. DSH and project runs explicitly refresh their heartbeat. This inherited integration defect remains present across the migrated paths.",
   "fix": "Refresh the running job's progress timestamp when the common reader receives activity, and verify that an actively streaming Claude/Codex run survives the stall threshold while a silent run does not."
  },
  {
   "id": "UI2-04",
   "severity": "medium",
   "path": "runner/app.py:2988",
   "evidence": "_publish_run_line stores discovered agent_session_id on the job, but cancellation and stall records use only job.record and omit that field. Cancelling a fresh Claude/Codex run after its initialization event therefore leaves a durable replay but no resumable session metadata. After restart, /events hides interactive resume and strict quick reply rejects the otherwise resumable session.",
   "fix": "Carry the current session identity into owner-written cancellation/stall records, including known resume identities before launch."
  },
  {
   "id": "UI2-05",
   "severity": "medium",
   "path": "runner/templates/index.html:4262",
   "evidence": "Open a card's interactive terminal, choose Show in panel, close the detail view, then close the panel tab. closeTab only calls term_close; server close_terminal releases locks and removes the terminal without recording interactive session ended or offering the three next-state choices. Those actions exist only in the card's _cardTermNext flow.",
   "fix": "Bind closure handling to the server terminal's run identity and invoke a common completion flow from every close entry point. Persist the closure audit exactly once and expose the next-state choice when closing from the panel."
  },
  {
   "id": "UI2-06",
   "severity": "medium",
   "path": "runner/templates/index.html:4403",
   "evidence": "After a page reload, reopening a card discovers and attaches its existing interactive terminal without calling _cardTermLoad. _cardTerm.data remains null. Ending that terminal then sends session_id=\"\" from _cardTermNext, and api_run_interactive_ended trusts that value, producing an audit record without the required session ID.",
   "fix": "Recover terminal/run metadata when reattaching and derive the audit session ID from server-owned terminal or run state instead of an optional browser field."
  },
  {
   "id": "UI2-07",
   "severity": "medium",
   "path": "runner/templates/index.html:4763",
   "evidence": "_projectData initially contains no projects. Opening New task before /api/projects finishes populates the selector with only No project and enables submission. Later loadProjects completion does not refill the open form. Submission explicitly sends project=\"\", bypassing the server's omitted-project default and running at the runner root even when agentic-os is registered.",
   "fix": "Wait for project loading before enabling creation, refresh the open selector after loading while preserving deliberate choices, and distinguish an unresolved default from an explicit No project selection."
  },
  {
   "id": "UI2-08",
   "severity": "medium",
   "path": "runner/modules/linear/__init__.py:1066",
   "evidence": "The unsynced-local dispatch guard runs after _remember_local_override. Dragging a pending local-* card to In Progress returns 409 but still installs a 60-second state override. Subsequent issue-list reads apply that override, displaying the rejected state despite B's explicit guarantee of no state change. The current test checks tasks.json but misses this shared-state mutation.",
   "fix": "Perform the unsynced-ID refusal before recording overrides or changing any cache, and verify that rejected dispatch leaves overrides and issue-list responses unchanged."
  },
  {
   "id": "UI2-09",
   "severity": "medium",
   "path": "runner/project_runs.py:310",
   "evidence": "DSH emits structured error events, as consumed by DshRun.feed_line in runner/dsh_cli.py. render_event handles type=error only for Codex; its DSH fallback also lacks an error case. A DSH error message is consequently absent from both live terminal output and replay, contrary to C's error-visibility criterion.",
   "fix": "Render DSH error events with their bounded message content and error styling, using the same renderer for live output and replay."
  }
 ],
 "coverage": [
  "Verified the plan digest and all 17 manifest file SHA256 values against disk.",
  "Read the plan, review log, changed implementation hunks, relevant surrounding code, and every added or changed test file.",
  "Traced session resolution, mutations, freshness checks, resume admission, and PTY lock ownership.",
  "Traced project labels through creation, normalization, synchronization, polling, local backups, fallback, and dispatch.",
  "Traced process-engine callers, retry/fallback, cancellation, stall detection, durable logs, replay, and completion-record writers.",
  "Inspected card terminals, attempt selection, reconnect, panel attachment, closure, project defaults, file browsing, and Run tests wording.",
  "Inspected related code beyond the manifest, including reset_gen.py, state_io.py, run_skill.py, dsh_cli.py, stall detection, and existing write-safety test source."
 ],
 "limitations": [
  "Static inspection only: no edits, tests, browser/native CLI operations, or delegation.",
  "Historical test-pass and manual-check claims were not independently verified.",
  "Native Claude/Codex picker behavior and live Linear API behavior were not exercised.",
  "SPEC.md and broader architecture/design documents were not inspected; fidelity was assessed against the supplied plan and inspected implementation contracts."
 ]
}
```

### Dispositions (host Claude; all 9 verified)
- UI2-01 fixed: a resume opened without a run (Projects panel) is matched to the newest run that recorded that agent session (`card_run_for_session`); any runner-root run's card lock is taken even when opened under a registered project. Test `test_projects_panel_resume_of_a_card_session_holds_the_card`.
- UI2-02 rejected (convergence bar, accepted risk): needs one user to open an interactive terminal in the same instant as dragging the card; the dispatch is then still refused by the lock it takes itself (runner-root: card lock held through the run since UI-02; project: helper's ticket lock). Only the 409 vs. later-refusal distinction is lost in that window.
- UI2-03 fixed: every streamed line refreshes the job's `last_progress_at` (the stall pass no longer kills an actively streaming Claude/Codex run). Inherited gap, now closed. Test `test_streaming_is_progress_and_cancel_keeps_the_session`.
- UI2-04 fixed: cancel/stall owner records carry the job's discovered or claimed `agent_session_id`. Same test.
- UI2-05/06 fixed: the closure audit moved to the server — `close_terminal` of a resume terminal bound to a run writes "interactive session ended" exactly once with the server-held session id, from every entry point (card End, panel close, shutdown). The `/interactive-ended` route is removed; the card's next-state buttons only move the card. Closing from the panel reopens the card on the same choice. Test `test_closing_a_card_session_records_it_once_from_any_entry_point`; browser-checked.
- UI2-07 fixed: until /api/projects has loaded, the form offers "Default project (loading…)" and omits `project` (server default); an open form refills when loading finishes; "No project" stays an explicit choice.
- UI2-08 fixed: the unsynced/card-held refusal runs before any override or cache change, in both the main PATCH and the board's local PATCH. Test asserts no override and no tasks.json change.
- UI2-09 fixed: dsh (and Codex) error events render red with their message. Renderer test extended.
- Proof: 529 passed.

## Inspection 3 (fresh Codex) — REVISE (9 medium, 0 high)
- Result: /private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/43734fe6-827b-4456-8612-0540ddad69af/scratchpad/claudex/i3/claudex-j4wrw52n/result.json (assurance cross_provider)
```json
{
 "verdict": "REVISE",
 "summary": "Concrete defects remain in dispatch admission, terminal lifecycle, continuation identity, streaming coverage, and saved project selection.",
 "findings": [
  {
   "id": "UI3-01",
   "severity": "medium",
   "path": "runner/modules/linear/__init__.py:1046",
   "evidence": "Dispatch PATCH still probes and releases the card lock before changing tracker state and scheduling work. If an interactive terminal acquires the lock afterward, dispatch is refused later, but PATCH has already returned success and moved the issue to In Progress. The project path can also record a failed attempt. This remains contrary to C2's side-effect-free 409 requirement, despite the review log accepting the race.",
   "fix": "Reserve the canonical card or ticket lock synchronously before mutations, then transfer that reservation to dispatch until completion."
  },
  {
   "id": "UI3-02",
   "severity": "medium",
   "path": "runner/app.py:3924",
   "evidence": "Interactive closure writes an ordinary review record containing the resumed session ID. _get_task_agent_lock at lines 2585–2603 does not exclude interactive_ended records. After a failed resume creates fallback session B, opening and closing older attempt A makes its audit record newest; a quick reply to B then resumes A. The same audit writer also updates task_state.json and job_state.json as if another execution completed.",
   "fix": "Keep closure audits separate from executable run state, or exclude them consistently from session selection and status materialization while retaining them in history."
  },
  {
   "id": "UI3-03",
   "severity": "medium",
   "path": "runner/modules/pty/__init__.py:150",
   "evidence": "When the embedded shell exits naturally, _reader only sets alive=False and emits term_exit. It neither releases t.holds nor records closure. The browser then hides End session and offers next-state choices at index.html:4543. Choosing Todo leaves the card's lock held, so subsequent dispatch or quick reply is refused until the dead terminal is separately closed through the panel.",
   "fix": "Finalize naturally exited terminals through a shared, idempotent cleanup path that releases locks and records closure before presenting next-state choices."
  },
  {
   "id": "UI3-04",
   "severity": "medium",
   "path": "runner/app.py:4158",
   "evidence": "Ordinary retry of a scheduled entrypoint leaves _stream set to claude or codex; only dsh switches to plain text. run_skill.py emits plain lines such as '[runner] started...' and forwards the script's stdout. The structured renderers discard those lines, leaving the new Terminal view and replay empty for these retry paths. Direct /run and Linear entrypoint launches correctly use stream='text'.",
   "fix": "Select plain-text streaming for every run_skill.py entrypoint retry, independently of the selected agent."
  },
  {
   "id": "UI3-05",
   "severity": "medium",
   "path": "runner/templates/index.html:4371",
   "evidence": "_cardTermBind clears terminal metadata but never clears or restores detail-term-reply. Type a reply on card A, switch to card B, and A's text remains in B's input. Send posts it to B's retry endpoint; for a non-confidential B, the backend can also publish that feedback to Linear.",
   "fix": "Scope quick-reply drafts by canonical card identity and clear or restore the input whenever the bound card changes."
  },
  {
   "id": "UI3-06",
   "severity": "medium",
   "path": "runner/templates/index.html:4776",
   "evidence": "A saved non-default project is discarded if New task opens before /api/projects finishes. _fillNewIssueProjects(saved) replaces it with __default__, and loadProjects later calls _fillNewIssueProjects(null). The restored title and description can consequently be submitted under agentic-os instead of the saved project, violating the draft-preservation requirement.",
   "fix": "Retain the pending saved project while loading and restore it after validation. Prevent submission from silently substituting the default for an unresolved saved selection."
  },
  {
   "id": "UI3-07",
   "severity": "medium",
   "path": "runner/templates/index.html:4490",
   "evidence": "Mark done and Send back to Todo only mutate state when linear_issue_id exists. A dashboard /run session opened through a run tab has no tracker ID; closing it presents these choices, but either choice merely displays a success message and leaves its recorded status unchanged.",
   "fix": "Use the existing run-status endpoint for cards without a tracker ID, mapping Done to success and Todo to todo, and report success only after the mutation succeeds."
  },
  {
   "id": "UI3-08",
   "severity": "medium",
   "path": "runner/modules/pty/__init__.py:214",
   "evidence": "term_close now writes both run logs and shared task/job state through record_interactive_ended, but its Socket.IO handler has no maintenance admission or in-flight reservation. Socket requests bypass the HTTP maintenance gate. Closing a card terminal while maintenance is active therefore writes despite inflight=0, breaking the invariant used by scripts/relocate_checkout.sh:105–112 before stopping the runner.",
   "fix": "Admit and count the closure audit before terminal teardown begins, with an explicit shutdown path that safely completes outstanding audits."
  },
  {
   "id": "UI3-09",
   "severity": "medium",
   "path": "runner/app.py:4282",
   "evidence": "History lookup only considers durable run records. While a new retry is running, its ID is absent from that lookup, so /history returns an empty chain. _cardTermAttempts then offers only the current run and hides the selector, even when the card has several completed attempts. Earlier attempts become selectable only after the current run finishes.",
   "fix": "Resolve history from the running job's canonical issue/task identity when no terminal record exists, then include completed attempts alongside the active run."
  }
 ],
 "coverage": [
  "Verified the supplied plan SHA256 and all 17 manifest file SHA256 values against disk.",
  "Reviewed the plan, review log, changed implementation hunks, relevant surrounding code, and every added test file.",
  "Traced session mutations, freshness checks, session claims, PTY admission, and card/ticket locks.",
  "Traced project labels through creation, synchronization, polling, backups, fallback, and dispatch.",
  "Traced process-engine callers, retry/fallback, cancellation, stall handling, durable logging, replay, and history.",
  "Inspected card terminals, reconnect, closure, project selection, file browsing, and Run tests wording.",
  "Inspected related state writers and callers beyond the manifest, including state_io.py, reset_gen.py, run_skill.py, stall detection, module registration, and relocation."
 ],
 "limitations": [
  "Static inspection only: no edits, tests, browser/native CLI operations, or delegation.",
  "Historical test-pass and manual-validation claims were not independently verified; native picker and live Linear behavior remain unverified.",
  "SPEC.md and broader architecture documents were not inspected; fidelity was assessed against the supplied plan and inspected implementation contracts."
 ]
}
```

### Dispositions (host Claude; all 9 verified and fixed)
- UI3-01 (= UI2-02) fixed instead of accepted: the PATCH route reserves the card's lock (`reserve_card`: ticket lock for a project card, card lock otherwise) before any override, cache or tracker change, and hands it to the dispatch (`_start_dispatch(card_hold=)` → `_dispatch_issue_counted` → project helper `ticket_hold` / runner-root run), which keeps it until the run ends; every early return closes it. Test `test_patch_reserves_the_card_and_the_dispatch_keeps_it`.
- UI3-02 fixed: closure audits are written with `audit=True` (run logs only, no task_state/job_state) and `_get_task_agent_lock` ignores them. Test `test_closure_audit_is_history_only`.
- UI3-03 fixed: one idempotent `_finalize` per terminal (release locks, audit once) runs on close and when a resume terminal's shell exits by itself. Test `test_natural_exit_frees_the_card_and_records_once`.
- UI3-04 fixed: every run_skill.py entrypoint retry streams plain text. Test `test_entrypoint_retry_streams_plain_text`.
- UI3-05 fixed: the quick-reply input is cleared whenever the card view is rebound.
- UI3-06 fixed: a saved draft project survives opening the form before the list loads (kept as a pending option, restored after load).
- UI3-07 fixed: for a card without a tracker id, Mark done / Send back to Todo set the run status (success / todo) via the existing status route and report the result.
- UI3-08 fixed: the closure audit runs under `_inflight_work()`; under maintenance it is skipped with a warning, the locks are still released. Test `test_closure_under_maintenance_writes_nothing`.
- UI3-09 fixed: the attempt picker reads the issue's history (`linear-<id>`), which exists while a retry is still running.
- Proof: 534 passed.

## Inspection 4 (Codex) — FAILED: provider unavailable
- Result: /private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/43734fe6-827b-4456-8612-0540ddad69af/scratchpad/claudex/i4/claudex-j8ipbwnr/result.json
- failure_kind=provider_unavailable, fallback_eligible=true. Codex: "You've hit your usage limit … try again at Oct 16th, 2026 1:02 AM."

## Inspection 4b (fresh Claude, degraded fallback) — REVISE (2 medium, 3 low)
- Result: /private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/43734fe6-827b-4456-8612-0540ddad69af/scratchpad/claudex/i4b/claudex-bqzi64ng/result.json (assurance degraded_same_provider)
```json
{
 "verdict": "REVISE",
 "summary": "The locking, the process engine and the session/file-browser paths held up when traced, but two medium defects remain. First, Linear label resolution only searches team-scoped labels, so a task can get stuck local and never dispatch. Second, the \"Waiting for you\" detector flags ordinary closing statements as questions. There are also three low-severity issues. This is a same-provider fallback review, so it is not independent of the builder.",
 "findings": [
  {
   "id": "FB-01",
   "severity": "medium",
   "path": "runner/linear_client.py:113",
   "evidence": "`_QUERY_LABEL` filters `issueLabels` by `team: {id: {eq: $teamId}}`, so workspace-level labels are never found. When the lookup misses, `ensure_label` calls `issueLabelCreate` for the team. Part B says the selector works 'exactly like a Linear ticket labelled project:<key> today', and those labels may already exist at workspace level or with different capitalisation. Linear rejects or duplicates such a create. `_bg_sync_to_linear` (modules/linear/__init__.py:981-985) raises when no id comes back, so the task stays on its `local-*` id. Because of `unsynced_local_id`, it can never be dispatched, and since the default project is agentic-os this affects every default task. Two concurrent first-time creates for the same project can race the same way.",
   "fix": "Look labels up by name across the team and the workspace (`or: [{team: {id: {eq}}}, {team: {null: true}}]`), case-insensitively (`eqIgnoreCase`). If create fails, query once more before giving up. Add a fake-client test where the label exists only at workspace level."
  },
  {
   "id": "FB-02",
   "severity": "medium",
   "path": "runner/project_runs.py:144",
   "evidence": "`waiting_question` does substring matching on the lowercased last three lines against `_ASKING`. That list includes 'approve', 'approval', 'let me know' and '是否'. 'Codex returned APPROVED.' matches 'approve', and that is the normal ending of the user's `/claudex-loop` runs. 'Let me know if you need anything else.' is a common Claude closing line. '检查是否通过' contains '是否'. All of these finished statements get the 'Waiting for you' badge. The plan only asks for this badge when the message asks the user something or matches an approval request.",
   "fix": "Match whole request phrases instead of bare substrings: e.g. 'please approve', 'do you approve', 'awaiting your approval', 'let me know whether/which/if you want', and '是否…？' only when the line ends with a question mark. Add statement-side tests ('APPROVED', 'Let me know if you need anything else.', '检查是否通过。')."
  },
  {
   "id": "FB-03",
   "severity": "low",
   "path": "runner/projects.py:1659",
   "evidence": "`rename_session` (Claude) appends to the transcript, which updates its mtime. `check_session_idle` refuses any transcript written in the last `SESSION_FRESH_S` (120 s). A user who renames and then fixes a typo, or renames and then removes, gets 409 'written in the last 2 minutes' for two minutes, caused by the dashboard's own write. The append also moves the session to the top of `claude --resume`'s list, which is sorted by recency.",
   "fix": "Record the file's (atime, mtime) before the append and restore them with `os.utime` after a successful write. Alternatively, have the freshness check ignore a trailing custom-title record the runner wrote itself."
  },
  {
   "id": "FB-04",
   "severity": "low",
   "path": "runner/projects.py:845",
   "evidence": "`CARD_LOCK_DIR` defaults to `~/.agentic-os/card-locks`. The retry route now always takes `card_lock(linear_issue_id or task_id)` for unbound cards. Only test_card_terminal.py and test_reset_gen.py patch the directory. tests/test_runner_write_safety.py (≈22 `/api/runs/a/retry` posts) and tests/test_run_engine.py do not, so the suite creates lock files in the real home directory and contends on fixed keys like 'a'/'b'. A background `_do_retry` from one test that is still holding the lock would turn the next test's retry into a 409.",
   "fix": "Add an autouse fixture (e.g. tests/conftest.py) that points `projects.CARD_LOCK_DIR` (and `SESSION_TRASH`) at tmp_path for every test."
  },
  {
   "id": "FB-05",
   "severity": "low",
   "path": "runner/modules/pty/__init__.py:181",
   "evidence": "When a resume shell exits on its own, `_reader` runs `_finalize`, and the card view shows the next-state choice. The dead terminal stays in TERMINALS. If the user later closes that tab from the panel, `close_terminal` returns `run_id` again, and `closeTab` (index.html:4275) calls `_promptCardNext`, which reopens the detail modal with the same choice a second time. The audit is not duplicated, but the prompt is.",
   "fix": "Have `close_terminal` return `run_id` only when that call is the one that performed the finalization, e.g. `_finalize` returns True only the first time."
  }
 ],
 "coverage": [
  "Read the supplied plan, review log and full tracked diff for runner/app.py, linear_client.py, modules/linear/__init__.py, local_tracker.py, modules/pty/__init__.py, project_runs.py, projects.py and templates/index.html",
  "Traced the retry route end to end: unsynced guard, strict continuation, session claim, card/ticket lock reservation and hand-off to the background worker or project helper, release on every exit path, and _get_task_agent_lock with the audit-record filter",
  "Traced Linear PATCH reserve_card → _start_dispatch → _dispatch_issue_held for the project and runner-root paths, plus the poller (unreserved) path and the local-patch refusal ordering",
  "Traced open_terminal: ticket lock, card_run_for_session/_latest_record card lock, session_lock admission and registration; close_terminal/_reader → _finalize → record_interactive_ended under _inflight_work",
  "Traced run_agent_process and _read_both (deadline, cleanup, real threads), _publish_run_line (ring/seq/progress/session id), durable log append and meta sidecar, /events replay and cursor",
  "Checked module import identity (runner.core.module_registry / runner.modules.* used consistently by app and modules)",
  "Reviewed session_target/rename/remove/check_session_idle, list_dir/read_file/_browse_path/_browse_root confinement, the git porcelain -z parsing, and _check_ident compatibility with UUID card keys",
  "Reviewed board/detail-modal JS for the card Terminal tab, generation guards, attempt picker, the project selector default/draft logic and the waiting badge",
  "Checked which tests patch CARD_LOCK_DIR / SESSION_TRASH"
 ],
 "limitations": [
  "Same-provider fallback reviewer (shares the builder's provider): not an independent cross-provider inspection",
  "Static inspection only: no tests run, no browser or native claude/codex picker checks, no live Linear API; the claimed 534 passing tests were not verified",
  "FB-01 depends on Linear's label-uniqueness behaviour across team and workspace scope, which was inferred, not tested against the API",
  "The full contents of the new test files and SPEC/architecture docs were not read in detail; the Codex thread-name store semantics (threads.name vs other indexes) were not verifiable",
  "DEGRADED_SAME_PROVIDER: preferred reviewer codex was unavailable; claude reviewed in a fresh fallback session without cross-provider independence."
 ]
}
```

### Dispositions (host Claude; all 5 verified and fixed)
- FB-01 fixed: label lookup matches the name case-insensitively among team and workspace labels; a refused create is looked up once more. Tests check the query shape and the re-lookup (live Linear semantics of `eqIgnoreCase` / `team: {null: true}` not exercised: no test workspace).
- FB-02 fixed: "Waiting" phrases are whole request phrases ("please approve", "awaiting your approval", "shall I", "请确认", …), not bare words; statement-side tests added ("Codex returned APPROVED.", "Let me know if you need anything else.", "检查是否通过。").
- FB-03 fixed: a Claude rename restores the transcript's atime/mtime, so the dashboard's own write neither trips the 2-minute rule nor reorders the native picker. Tests updated (rename then remove → 200).
- FB-04 fixed: tests/conftest.py points CARD_LOCK_DIR and SESSION_TRASH at tmp_path for every test. Five stray lock files that earlier test runs left in ~/.agentic-os/card-locks (i1, i2, i3, iss-1, T; all created 2026-10-15 22:13–22:16 by this build's tests) were removed with the empty directory.
- FB-05 fixed: `_finalize` reports whether this call finalized; `close_terminal` returns `run_id` (which triggers the next-state prompt) only then.
- Proof: 538 passed.

## Inspection 5 (Codex) — FAILED: provider unavailable (usage limit until 2026-10-16 01:02)
- Result: /private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/43734fe6-827b-4456-8612-0540ddad69af/scratchpad/claudex/i5/claudex-tv9j26zk/result.json

## Inspection 5b (fresh Claude, degraded fallback) — REVISE (1 medium, 3 low)
- Result: /private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/43734fe6-827b-4456-8612-0540ddad69af/scratchpad/claudex/i5b/claudex-gk1y1j2n/result.json (assurance degraded_same_provider)
```json
{
 "verdict": "REVISE",
 "summary": "One medium defect remains, plus three low ones. When a user closes a card's interactive session from the bottom panel on a real PTY, close_terminal races the PTY reader thread. The reader usually finalizes the terminal first, so close_terminal returns run_id=None and the next-state prompt (fix UI2-05) never appears. The tests stub _spawn and _kill_session, so they do not exercise this race. The low findings: a session claim leaks when maintenance refuses a project retry; a retry fallback leaves the wrong session id on the job for cancel/stall records; and one of the \"waiting\" phrases is too broad. Locking, the process engine, label handling, session rename/remove and file-browser confinement held up when traced. This review comes from the same provider as the builder, so it is not independent.",
 "findings": [
  {
   "id": "FB2-01",
   "severity": "medium",
   "path": "runner/modules/pty/__init__.py:228",
   "evidence": "close_terminal calls _kill_session(t) first. That function sends SIGHUP, then keeps polling `ps` through _session_pgids until the session's process groups are gone, and only then reaps and closes t.fd. Once the shell and the claude/codex child die, the master read returns EOF/EIO. The reader thread (lines 157-184) leaves its loop within 0.2 s and calls _finalize(t) for kind=='resume'; _finalize sets finalized=True under _finalize_lock. close_terminal is still inside the ps polling loop at that point. Its own _finalize(t) at line 238 then returns False, so it returns run_id=None (line 242). closeTab in index.html (~4275) only calls _promptCardNext when res.run_id is set. The detail view is closed and the _cardTerm term_exit handler ignores other terms, so closing a card session from the panel normally shows no Mark done / Todo / Review choice. That breaks the UI2-05 disposition. test_closing_a_card_session_records_it_once_from_any_entry_point stubs _spawn (pid None) and _kill_session, and test_natural_exit… calls _reader directly, so neither exercises the race.",
   "fix": "Decide whether to prompt by who initiated the close, not by who won _finalize. For example: in close_terminal, take `was_alive = t.alive and not t.finalized` before _kill_session (or set a `t.closing = True` flag that the reader checks before finalizing). Return run_id when was_alive or first. A terminal that had already exited still returns None, which keeps the FB-05 fix. Add a test with a real short-lived PTY child, or a reader thread that finalizes during _kill_session, and assert that run_id is returned."
  },
  {
   "id": "FB2-02",
   "severity": "low",
   "path": "runner/app.py:3036",
   "evidence": "api_run_retry calls _claim_session (line 4023) and then starts `_start_counted(_run_project_ticket, …)`. _run_project_ticket is wrapped by @_counted, and its `_release_session` callback is registered inside the wrapped body (line 3042). If maintenance turns on between route admission and thread start, _counted's `with _inflight_work()` raises MaintenanceRefused before the body runs. The wrapper closes ticket_hold (line 2839) but never calls _release_session. _SESSION_CLAIMS[new_run_id] then stays until the runner restarts. _live_session_ids includes it, so rename/remove of that session returns 409 'open in a terminal or a running job' indefinitely.",
   "fix": "In _counted's MaintenanceRefused branch, also call `_release_session(kw.get('run_id'))`, or register the release before the admission step. Add a test that sets _MAINTENANCE before the worker runs and asserts _SESSION_CLAIMS is empty afterwards."
  },
  {
   "id": "FB2-03",
   "severity": "low",
   "path": "runner/app.py:827",
   "evidence": "_publish_run_line only sets job['agent_session_id'] when it is empty. In an ordinary retry, the failed resume attempt announces session A (Claude init / Codex thread.started), and then the fallback under the same run_id announces a fresh session B. The job keeps A. If the run is cancelled or stalls during the fallback, _write_owner_record (line 2997) records agent_session_id=A. The next quick reply then resumes the dead A rather than B, the session that holds the fallback's work, and rename/remove's live check guards A instead of B.",
   "fix": "When run_agent_process launches a new attempt for a run_id, clear the job's announced session id (keep _SESSION_CLAIMS for the claimed resume). Alternatively, overwrite the id whenever a stream announces a session in an init/thread.started event instead of using setdefault semantics."
  },
  {
   "id": "FB2-04",
   "severity": "low",
   "path": "runner/project_runs.py:146",
   "evidence": "_ASKING still contains the bare phrase 'your sign-off', matched as a substring of the last three lines. A closing statement such as 'Got your sign-off; build finished.' or 'Implemented per your sign-off.' gets the 'Waiting for you' badge. This is the same false-positive class that FB-02 fixed for 'approve' / 'let me know'.",
   "fix": "Drop 'your sign-off' or replace it with request forms ('need your sign-off', 'requesting your sign-off', 'awaiting/waiting for your sign-off' are already listed). Add a statement-side test such as 'Got your sign-off; build finished.'"
  }
 ],
 "coverage": [
  "Read the plan, review-log dispositions and the full tracked diff for app.py, linear_client.py, modules/linear/__init__.py, local_tracker.py, modules/pty/__init__.py, project_runs.py, projects.py, index.html and the two changed tests",
  "Traced the PTY lifecycle in the current file: _reader → _finalize, close_terminal → _kill_session → _finalize, close_all, and open_terminal (ticket inference from cwd for Projects-panel resumes, card_run_for_session, card_lock and the session_lock admission)",
  "Traced api_run_retry end to end in the current file: unsynced guard, strict mode, _claim_session, card/ticket lock reservation, the _start_failed releases, project hand-off through @_counted _run_project_ticket, _do_retry release, fallback and strict error status",
  "Traced Linear _dispatch_issue_held against the current file: reserved vs probe paths, matching ticket ident between reserve_card and the project helper, the runner-root card_lock held through the run, agent_session_id written to the record",
  "Checked _counted/_start_counted/_maintenance_gate, RUN_PROGRESS_DIR (outputs/logs) against the _records_unsafe locations for the confidential log, _build_resume_cmd/_ai_command output formats, api_run_events resume_eligible and replay",
  "Checked board construction and openDetailModal for Linear cards (running runs give the card a real run_id) and the interactive_ended filters",
  "Read the relevant tests in tests/test_card_terminal.py to see what the closure tests stub"
 ],
 "limitations": [
  "DEGRADED_SAME_PROVIDER: same-provider fallback reviewer (shares the builder's provider); this is not a cross-provider independent inspection",
  "Static inspection only: no tests run, no browser, PTY, native claude/codex picker or live Linear checks. The claimed 538 passing tests were not verified",
  "FB2-01's timing argument comes from reading the code (ps polling in _kill_session vs a 0.2 s select loop in the reader); it was not reproduced on a live PTY",
  "Whether `codex resume` reads threads.name for its picker, and Linear's eqIgnoreCase / team-null filter semantics, could not be verified",
  "Not every new test file was read in full, and SPEC/architecture docs were not inspected",
  "DEGRADED_SAME_PROVIDER: preferred reviewer codex was unavailable; claude reviewed in a fresh fallback session without cross-provider independence."
 ]
}
```

### Dispositions (host Claude; all 4 verified and fixed)
- FB2-01 fixed: close_terminal decides the prompt by whether it closed a live, unfinalized session (`closing` flag set under the finalize lock before the kill; the reader no longer finalizes a terminal being closed). Test drives the reader inside the kill: `test_panel_close_prompts_even_when_the_reader_finalizes_first`.
- FB2-02 fixed: a project launch refused by maintenance also releases its session claim. Test `test_a_refused_project_retry_releases_its_session_claim`.
- FB2-03 fixed: the latest announced session id wins on the job, so a fallback's fresh session replaces the failed resume's. Test `test_fallback_session_replaces_the_failed_resume`.
- FB2-04 fixed: "your sign-off" → "need your sign-off"; statement test added.
- Proof: 542 passed.

## Inspection 6 (Codex) — FAILED: provider unavailable (usage limit)
- Result: /private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/43734fe6-827b-4456-8612-0540ddad69af/scratchpad/claudex/i6/claudex-uwdqej91/result.json
- Fallback 6b (Claude) — FAILED: Claude usage limit reached mid-run (/private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/43734fe6-827b-4456-8612-0540ddad69af/scratchpad/claudex/i6b/claudex-w7xex6te/result.json); no code change since, so the fallback was rerun against the same failed Codex result.

## Inspection 6c (fresh Claude, degraded fallback) — REVISE (2 medium, 1 low)
- Result: /private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/43734fe6-827b-4456-8612-0540ddad69af/scratchpad/claudex/i6c/claudex-f05_k68z/result.json (assurance degraded_same_provider)
```json
{
 "verdict": "REVISE",
 "summary": "Two medium defects remain, plus one low. (1) The new card-lock helpers (`reserve_card` and `card_locked`, which goes through `card_busy`) pass the raw `project:<key>` label text from Linear straight into `ticket_lock`. That function builds `WORKTREE_ROOT / key / \".meta\"` and runs mkdir before any key validation. A tracker label can therefore make the runner create directories and lock files outside the worktree root. A key that is unknown or invalid also comes back as the misleading 409 \"an interactive terminal holds this card\". (2) `_project_labels` calls `projects.load_registry`, which raises `ProjectError` when projects.yaml cannot be parsed. `ProjectError` is not a `ValueError`, so the create route's `except ValueError` misses it and returns a 500. While the registry is broken, no task can be created at all, even with \"No project\"; before this change, task creation never touched the registry. (3) Low: the case-insensitive label lookup added for FB-01 can return an existing label whose key part is cased differently. The background sync then keeps a project key that does not match the registry. The process engine, retry/strict continuation, the PTY close/finalize lifecycle, audit-record filtering, session rename/remove and file-browser confinement all held up when traced. This is a same-provider fallback review, so it is not independent of the builder.",
 "findings": [
  {
   "id": "FB3-01",
   "severity": "medium",
   "path": "runner/modules/linear/__init__.py:245",
   "evidence": "`reserve_card` and `card_locked` take `key = bound.get(\"project_key\") or project_runs.project_key_from_labels(issue.get(\"labels\"))`. `project_key_from_labels` returns the raw text after `project:` from a Linear label, which anyone in the workspace can set. That key goes straight to `projects.ticket_lock(key, ...)`, either directly or through `card_busy`. `ticket_lock` (runner/projects.py:832-834) runs `(WORKTREE_ROOT / key / \".meta\").mkdir(parents=True)` and `os.open(...lock)` with no key check; only the ident is validated, and only after the mkdir. Example: a Linear issue labelled `project:/tmp/x` that reaches In Progress, whether by board drag (PATCH → `reserve_card`), by the board's local PATCH (`card_locked`) or by the poller (`_dispatch_issue_held` → `card_locked`). The runner creates `/tmp/x/.meta/<ident>.lock`, and `project:a/../../..` escapes the same way. Before this change the label key only reached `_run_project_ticket`, which resolves it through the registry before any lock. A label key that is well-formed but unregistered also leaves stray `WORKTREE_ROOT/<key>/.meta` directories. In the PATCH path, any `ProjectError` from `ticket_lock` becomes 409 \"an interactive terminal holds this card\", which hides the real cause.",
   "fix": "Validate the key before locking. Resolve it through the registry (`projects.get_project(key, projects.load_registry(errors={}))`) and lock `project.key`, or at minimum run `_check_key(key)` inside `ticket_lock` before the mkdir. In `reserve_card`/`card_locked`, report an unknown or invalid project as its own error (or let dispatch record it) instead of 'held by a terminal'. Add a test with a label such as `project:../x` and one such as `project:/abs`: nothing should be created outside WORKTREE_ROOT, and the response should not claim a terminal holds the card."
  },
  {
   "id": "FB3-02",
   "severity": "medium",
   "path": "runner/modules/linear/__init__.py:214",
   "evidence": "`_project_labels` always calls `projects.load_registry(errors=errors)` first, even when `project` is \"\". `load_registry` raises `ProjectError` when projects.yaml cannot be parsed or lacks a `projects` mapping (runner/projects.py:290-299). `ProjectError` subclasses `Exception`, not `ValueError`. The create route (line 944-947) catches only `ValueError`, and runner/ has no Flask errorhandler, so POST /api/linear/issues returns 500 for every request. In the UI, `/api/projects` returns 200 with `error` and `projects: []`, so `_projectsLoaded` becomes true and the selector offers only \"No project (runner root)\". Submitting sends `project: \"\"`, the route still returns 500, and `submitNewIssue` fails on the non-JSON body. A malformed projects.yaml, which the Projects panel already reports as 'Registry error', therefore blocks all task creation. Before part B, task creation never read the registry.",
   "fix": "In `_project_labels`, return [] for an explicit \"\" before reading the registry. Catch `projects.ProjectError` from `load_registry`: an explicit key gets a 400 with the registry error; an omitted project falls back to no project and the form hint says so. Add a test with a broken projects.yaml: an explicit-empty create returns 200, and a create naming a project returns 400, not 500."
  },
  {
   "id": "FB3-03",
   "severity": "low",
   "path": "runner/modules/linear/__init__.py:991",
   "evidence": "The FB-01 fix matches existing labels with `eqIgnoreCase`, so `ensure_label(tid, \"project:agentic-os\")` can return an existing label named, for example, `project:Agentic-OS`. The created issue then carries that name. `_bg_sync_to_linear` sets `n[\"labels\"] = sorted(set(n[\"labels\"]) | set(labels))`, giving ['project:Agentic-OS', 'project:agentic-os']. `project_key_from_labels` returns the first one ('Agentic-OS'), and polling later replaces the list with the remote label only. Dispatch then calls `get_project('Agentic-OS')`, which fails case-sensitively, so the task records an 'unknown project' error instead of running in the project it was created for. Because the default is agentic-os, the default case is the one most exposed.",
   "fix": "Either match only exact-case names (and accept creating a team label when only a differently-cased one exists), or have `project_key_from_labels` / dispatch map the key case-insensitively onto a registered key. Also stop the union from placing a differently-cased variant ahead of the validated label. Add a fake-client test where the only existing label differs in case."
  }
 ],
 "coverage": [
  "Read the plan and the full tracked diff for runner/app.py, linear_client.py, modules/linear/__init__.py, local_tracker.py, modules/pty/__init__.py, project_runs.py, projects.py and templates/index.html",
  "Traced api_run_retry in the current file: unsynced guard, strict mode, `_claim_session`, card/ticket lock reservation and hand-off, `_start_failed` releases, project hand-off via @_counted `_run_project_ticket` (session release and ticket_hold close), the `_do_retry` finally, fallback, and strict error status",
  "Traced the project helper `_run_project_ticket_locked`: no fallback on resume, error status on a failed resume, the durable log and meta sidecar written after the `_records_unsafe` check, and on_session",
  "Traced Linear `_dispatch_issue_held` (project and runner-root, reserved and unreserved), `reserve_card`/`card_locked` → `ticket_lock`/`card_lock`/`card_busy`, and the PATCH and local-PATCH refusal order",
  "Traced PTY open_terminal (ticket inference from cwd, `card_run_for_session`, `_latest_record`, card lock, session_lock admission), close_terminal/`_reader`/`_finalize` with the closing flag, and `record_interactive_ended` with audit=True",
  "Checked every RUN_LOG reader for how it treats audit records (`_latest_linear_runs`/_warm_dispatches, `_get_task_agent_lock`, `card_run_for_session`, run status/restore/history, the board JS `_latestLinearRuns` and the attempt picker)",
  "Checked the `/events` replay, cursor and resume_eligible; `_publish_run_line` (progress and latest session id); `_read_both`; and `run_agent_process` callers in /run, retry and Linear dispatch",
  "Checked `projects.load_registry` error behaviour against `_project_labels` and the create route's exception handling; checked `ticket_lock`, `_check_ident`, `_IDENT` and WORKTREE_ROOT path construction",
  "Reviewed the board/detail JS: card Terminal binding, card key, quick reply, next-state choices, project selector loading/default/draft logic"
 ],
 "limitations": [
  "DEGRADED_SAME_PROVIDER: same-provider fallback reviewer (shares the builder's provider); not an independent cross-provider inspection",
  "Static inspection only: no tests run, no browser, PTY, native claude/codex picker or live Linear checks. The claimed 542 passing tests were not verified",
  "FB3-03 depends on Linear's eqIgnoreCase semantics and on a differently-cased label actually existing in the workspace; neither was tested against the API",
  "Whether `codex resume` reads threads.name, and whether `claude --resume` in print mode keeps the same session id, could not be verified",
  "New test files were not read in full; SPEC/architecture documents were not inspected",
  "DEGRADED_SAME_PROVIDER: preferred reviewer codex was unavailable; claude reviewed in a fresh fallback session without cross-provider independence."
 ]
}
```

### Dispositions (host Claude; all 3 verified and fixed)
- FB3-01 fixed (security): a `project:<key>` label is untrusted text. `reserve_card`/`card_locked` lock only a key that maps onto the registry (`projects.registered_key`); an unknown key is a 400 "unknown project …" from the PATCH (not "a terminal holds it"), and dispatch records the error itself. Defense in depth: `ticket_lock` now validates the key (`_check_key`) before any mkdir. Test `test_untrusted_label_never_creates_paths_outside_the_worktree_root` (../x, /abs/x, a/../../b).
- FB3-02 fixed: an explicit "No project" never reads the registry; an omitted project falls back to none when the registry is broken; a named project with a broken registry is a 400. Test `test_broken_registry_still_allows_tasks_without_a_project`.
- FB3-03 fixed: dispatch maps a label key case-insensitively onto the registered key ("project:DEMO" → demo). Test `test_label_case_maps_onto_the_registered_project`.
- Proof: 547 passed.

## Inspection 7 (fresh Codex, after quota reset) — REVISE (1 high, 3 medium)
- Result: /private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/43734fe6-827b-4456-8612-0540ddad69af/scratchpad/claudex/i7/claudex-k9sc7i6n/result.json (assurance cross_provider)
```json
{
 "verdict": "REVISE",
 "summary": "Material defects remain in project lock handoff, interrupted-session recovery, terminal error visibility, and attempt switching.",
 "findings": [
  {
   "id": "REV-01",
   "severity": "high",
   "path": "runner/modules/linear/__init__.py:1108",
   "evidence": "After a local-tracker restart, issues_cache is empty: start_background skips population, and the local GET route returns persisted tasks without populating it. Dispatching a project-labelled task without an existing binding therefore reserves card_lock(issue_id). The subsequent update returns the actual project-labelled issue, and line 751 passes that generic reservation as ticket_hold. app.py:3110 then skips the project's ticket_lock entirely. PTY, verify, or cleanup operations can consequently acquire the ticket lock while its agent is running, including removing the active worktree.",
   "fix": "Fetch the authoritative issue before reserving its lock. Carry and validate the reservation's project/ticket identity before permitting the project helper to skip acquisition. Cover dispatch of persisted project tasks with an initially empty cache."
  },
  {
   "id": "REV-02",
   "severity": "medium",
   "path": "runner/app.py:3364",
   "evidence": "Streaming discovers and stores agent_session_id on the running job, but worker-owned timeout/error handlers discard it. The /run timeout record also omits agent; Linear dispatch and retry timeout handlers likewise omit the discovered session. A continuously active agent that reaches the process deadline thus retains its replay log but loses interactive resume and strict quick reply. If retry fallback created session B before timing out, later session selection can fall back to the older session A.",
   "fix": "Preserve the job's current session and launch metadata before _RunClaim removes it, and include those fields in every worker-owned timeout/error record across the engine's callers."
  },
  {
   "id": "REV-03",
   "severity": "medium",
   "path": "runner/app.py:792",
   "evidence": "The stderr drain only accumulates bytes; terminal publication and durable replay receive stdout exclusively. An agent reporting an authentication, configuration, or runtime failure solely on stderr produces no terminal error line, either live or after restart. Project run_agent has the same omission. This leaves ordinary CLI failures invisible in the promised live/replay terminal view.",
   "fix": "Publish bounded stderr diagnostics as error lines and persist them for replay on every launch path, while preserving the existing raw-stdout log contract and confidential storage policy."
  },
  {
   "id": "REV-04",
   "severity": "medium",
   "path": "runner/templates/index.html:4431",
   "evidence": "Changing attempts updates viewRunId immediately but leaves the previous attempt's data and Open interactive button active until the new snapshot arrives. Clicking that button during loading sends the old session ID with the newly selected run ID. Separately, a pending term_open callback checks only the card generation, which does not change when selecting another attempt, so it can attach an older attempt's terminal beneath the new selection.",
   "fix": "Invalidate attempt metadata and disable controls immediately on selection changes. Use an attempt-specific generation for all asynchronous callbacks, and validate the run/agent/session association server-side before opening a resume terminal."
  }
 ],
 "coverage": [
  "Verified all 18 manifest file SHA256 values, including the supplied plan digest.",
  "Reviewed the supplied plan, review log, changed implementation hunks, all added tests, and affected existing test fixtures/assertions.",
  "Traced session resolution, rename/remove, freshness checks, claims, and PTY admission.",
  "Traced project labels through creation, synchronization, normalization, local backups, and dispatch.",
  "Traced lock reservation and handoff through local-tracker startup, dispatch, project execution, PTY, verify, and cleanup callers.",
  "Traced process-engine callers, retry/fallback, cancellation, stall handling, timeout records, durable logs, and replay.",
  "Inspected card terminal callbacks, reconnect, closure audits, project selection, file browsing, and Run tests wording.",
  "Inspected related shared-state code beyond the manifest, including reset_gen.py, state_io.py, run_skill.py, usage_reader.py, stall detection, and module registration."
 ],
 "limitations": [
  "Static inspection only: no files edited, tests executed, work delegated, or browser/native CLI operations performed.",
  "Historical test-pass and manual-validation claims were not independently verified.",
  "Native picker behavior and live Linear GraphQL semantics were not exercised.",
  "SPEC.md and broader architecture documents were not inspected; fidelity was assessed against the supplied plan and inspected implementation contracts."
 ]
}
```

### Dispositions (host Claude; all 4 verified and fixed)
- REV-01 fixed: the PATCH route reserves from the authoritative issue (the persisted task when the local-tracker cache is empty), and every reservation records what it locked (`identity`). Dispatch hands it on only when it is exactly this ticket's lock (project path) or this card's lock (runner-root); anything else is released and the path takes its own lock. Test `test_dispatch_after_restart_holds_the_projects_ticket_lock`.
- REV-02 fixed: `_RunClaim` keeps the job's last announced or claimed session when it takes ownership, and every worker-owned timeout/error record (/run both paths, retry, Linear) carries it (and the agent). Test `test_timeout_record_keeps_the_announced_session`.
- REV-03 fixed: the last 20 stderr lines are published red into the run view (`[stderr] …`) on every launch path and kept in the meta sidecar for replay; the raw stdout log is unchanged. Test `test_stderr_reaches_the_live_view_and_replay`.
- REV-04 fixed: choosing another attempt voids the previous attempt's metadata and hides Open interactive at once; term_open callbacks carry an attempt generation; the server refuses a resume whose session is not the run's recorded session. Test `test_resume_must_match_the_runs_session`.
- Proof: 551 passed.

## Inspection 8 (fresh Codex) — REVISE (1 high, 4 medium)
- Result: /private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/43734fe6-827b-4456-8612-0540ddad69af/scratchpad/claudex/i8/claudex-zgb_z3in/result.json (assurance cross_provider)
```json
{
 "verdict": "REVISE",
 "summary": "Unresolved defects remain in resume admission, untracked-directory browsing, stderr preservation, and attempt selection.",
 "findings": [
  {
   "id": "UI8-01",
   "severity": "high",
   "path": "runner/modules/pty/__init__.py:358",
   "evidence": "Run-bound resume validates the session ID but still derives project, ticket, cwd, and agent from the request. A term_open request containing a confidential project run's correct run_id/session_id but omitting project_key and ticket acquires neither its ticket lock nor a card lock: rec.project_key suppresses the latter. interactive_resume_argv then receives project=None and builds an unrestricted resume command. The resumed process can overlap another attempt and bypass the recorded project's policy.",
   "fix": "Resolve the run and durable binding before acquiring locks or constructing argv. Derive project, ticket, cwd, agent, and confidentiality server-side; reject conflicting request fields and require the recorded session identity."
  },
  {
   "id": "UI8-02",
   "severity": "medium",
   "path": "runner/projects.py:1788",
   "evidence": "The listing uses git ls-files --others --directory, which collapses a wholly untracked directory to its directory name. For newdir/file.py, expanding newdir can therefore return newdir/ again. Prefix removal produces an empty child name, and the subsequent scan discards file.py because it is neither in names nor ignored. A new directory created by an agent appears expandable but its contents disappear.",
   "fix": "Query files beneath the requested directory without collapsing that directory itself, then derive its direct children. Cover expansion of a wholly untracked directory containing files and nested directories."
  },
  {
   "id": "UI8-03",
   "severity": "medium",
   "path": "runner/app.py:791",
   "evidence": "The stderr reader only accumulates bytes; run_agent_process publishes them after the streaming reader returns successfully at line 2587. Errors written while a CLI remains running are absent from the live terminal. If that process reaches its deadline, _read_both raises and discards the accumulated diagnostics, so they are also absent from replay. The project reader similarly delays stderr publication until process completion.",
   "fix": "Publish and persist bounded stderr diagnostics incrementally while draining the pipe, including during timeout cleanup. Preserve the raw stdout contract and confidential storage rules."
  },
  {
   "id": "UI8-04",
   "severity": "medium",
   "path": "runner/app.py:2569",
   "evidence": "Every process attempt replaces the metadata sidecar with {format: stream}. During an ordinary failed-resume → fresh-fallback retry, _publish_stderr first saves the resume failure's stderr_tail, but launching the fallback deletes it. The live ring retains that failure while replay after restart loses it, despite stdout now being appended correctly.",
   "fix": "Initialize metadata once per logical run, or merge subsequent attempt metadata without removing earlier diagnostics. Verify replay consistency when a failed resume emits stderr before a successful fallback."
  },
  {
   "id": "UI8-05",
   "severity": "medium",
   "path": "runner/templates/index.html:4418",
   "evidence": "The attempt-picker fix only handles tracker-linked runs through linear-<issue_id>/history. After Quick reply starts a dashboard /run continuation without a tracker ID, it requests history using the new running run ID. api_run_history only searches completed records and returns an empty chain because that ID has not been logged yet. The picker consequently hides all previous attempts until the continuation finishes.",
   "fix": "Resolve history for active runs through their running job's canonical task identity and parent metadata, and return completed attempts alongside the active attempt."
  }
 ],
 "coverage": [
  "Verified the supplied plan digest and all 18 manifest file SHA256 values against disk.",
  "Inspected every manifest file, including implementation changes, added tests, affected existing tests, and review-log dispositions.",
  "Traced project labels through creation, normalization, synchronization, backups, dispatch, and lock handoff.",
  "Traced session mutations, claims, PTY admission, confidentiality policy, terminal closure, and closure-audit readers.",
  "Traced process-engine callers, retry/fallback, timeout, cancellation, stall handling, durable logs, replay, and attempt history.",
  "Inspected project browsing, previews, project selection, terminal callbacks, reconnect behavior, and Run tests wording.",
  "Inspected related callers and shared-state writers beyond the manifest, including reset_gen.py, state_io.py, run_skill.py, and stall_detection."
 ],
 "limitations": [
  "Static inspection only: no edits, tests, delegation, browser operations, or native CLI operations.",
  "Historical test-pass and manual-validation claims were not independently verified.",
  "Native picker behavior and live Linear GraphQL semantics were not exercised.",
  "SPEC.md and broader architecture documents were not inspected; fidelity was assessed against the supplied plan and inspected implementation contracts."
 ]
}
```

### Dispositions (host Claude; all 5 verified and fixed)
- UI8-01 fixed (policy): a resume tied to a run — by run_id, or a Projects-panel session that a run recorded — takes project, ticket and agent from the run record; the session must be the run's; a conflicting project is refused. The project policy and the card/ticket lock therefore always apply. Test `test_run_bound_resume_takes_project_and_ticket_from_the_record`.
- UI8-02 fixed: a folder git reports as one collapsed untracked entry is expanded from disk (children "?", ignored ones marked). Test `test_wholly_untracked_folder_expands`.
- UI8-03 fixed: `_StderrSink` publishes stderr lines live as they arrive (bounded to 200) and keeps the tail in the meta sidecar on every exit, a timeout included (dsh keeps its end-of-run publication; its errors also arrive as JSON error events).
- UI8-04 fixed: an attempt merges into the meta sidecar instead of replacing it. Test `test_stderr_survives_a_timeout_and_a_later_attempt` covers both.
- UI8-05 fixed: /history resolves a still-running attempt from its job (parent, task, attempt). Test `test_history_of_a_running_attempt_includes_its_chain`.
- Proof: 555 passed.

## Inspection 9 (fresh Codex) — REVISE (1 high, 3 medium)
- Result: /private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/43734fe6-827b-4456-8612-0540ddad69af/scratchpad/claudex/i9/claudex-rh7cyjp1/result.json (assurance cross_provider)
```json
{
 "verdict": "REVISE",
 "summary": "Resume ownership validation, session confinement, stderr streaming, and interactive completion still have concrete defects.",
 "findings": [
  {
   "id": "IR9-01",
   "severity": "high",
   "path": "runner/modules/pty/__init__.py:333",
   "evidence": "An explicit run_id bypasses card_run_for_session, and session matching is enforced only when that record contains agent_session_id. A request can therefore pair a runner-root entrypoint run without a session ID with a confidential session's ID. The code accepts the association, selects project=None, locks the unrelated card, and constructs an unrestricted resume command. This bypasses the actual session's project policy and ticket lock.",
   "fix": "Require every explicitly run-bound resume to have a recorded, matching session identity. Resolve its canonical ownership and durable binding before choosing policy, cwd, or locks; refuse missing or conflicting associations."
  },
  {
   "id": "IR9-02",
   "severity": "medium",
   "path": "runner/project_runs.py:380",
   "evidence": "Project runs still collect stderr with a blocking read and publish it only after run_agent returns (app.py:3213). A CLI reporting retry or runtime errors while remaining alive shows no live diagnostics. The DSH reader similarly buffers stderr; on timeout it raises before returning diagnostics, so run_agent_process never publishes or persists them. The latest stderr fix therefore does not cover every launch path required by C.",
   "fix": "Use incremental bounded stderr publication and persistence for project runs and DSH as well, including timeout and cancellation cleanup, while retaining the raw stdout format and confidential storage rules."
  },
  {
   "id": "IR9-03",
   "severity": "medium",
   "path": "runner/projects.py:1637",
   "evidence": "Session ownership uses _under's lexical prefix comparison rather than resolved paths. A transcript or row with cwd '<project>/../foreign' or a path through an escaping symlink passes and can be renamed or removed. The Codex branch also accepts arbitrary rollout_path values and follows CODEX_DB without checking its resolved store containment, despite A explicitly requiring resolved cwd/store confinement.",
   "fix": "Resolve session cwd and allowed roots before checking containment. Validate the database and rollout against the configured Codex store, and refuse unverifiable or escaping targets before any mutation. Add traversal and symlink cases to the session-action checks."
  },
  {
   "id": "IR9-04",
   "severity": "medium",
   "path": "runner/templates/index.html:4497",
   "evidence": "Terminal access is available from Done and Todo cards, but choosing 'Leave in review' after ending an interactive session performs no state mutation. _cardTermNext handles only done/todo and nevertheless reports 'left in review'. A resumed Done card therefore remains Done after the user selects review; runner-root cards have the same gap.",
   "fix": "Apply the review choice through the tracker state route or the run-status endpoint, as appropriate. Await the result before displaying success."
  }
 ],
 "coverage": [
  "Verified the supplied plan digest and all 18 manifest file SHA256 values against disk.",
  "Reviewed the plan, review log, implementation diffs and relevant surrounding code, all added test files, and affected existing test changes.",
  "Traced project labels through creation, synchronization, backups, dispatch, and lock reservation/handoff.",
  "Traced session mutations, PTY ownership, confidentiality policy, card/ticket locks, and closure audits.",
  "Traced process-engine callers, retry/fallback, timeout, cancellation, stall detection, durable logging, replay, and history.",
  "Inspected project browsing, task-project selection, terminal callbacks, and Run tests wording; followed related state writers in reset_gen.py, state_io.py, run_skill.py, and usage_reader.py."
 ],
 "limitations": [
  "Static inspection only: no edits, tests, delegation, browser operations, or native CLI operations.",
  "Historical test-pass and manual-validation claims were not independently verified.",
  "Native resume-picker behavior and live Linear GraphQL semantics were not exercised.",
  "SPEC.md and broader architecture documents were not inspected; fidelity was assessed against the supplied plan and inspected implementation contracts."
 ]
}
```

### Dispositions (host Claude; all 4 verified and fixed)
- IR9-01 fixed: an explicitly run-bound resume needs a recorded session on that run equal to the requested one; a run without a session (e.g. an entrypoint run) cannot vouch for another session. Test `test_explicit_run_without_a_recorded_session_cannot_resume`.
- IR9-02 fixed: project runs (`run_agent(on_stderr=)`) and dsh feed the same `_StderrSink` as the other readers: live as lines arrive, tail kept on every exit including timeout. Test `test_project_reader_streams_stderr_while_running`.
- IR9-03 fixed: session ownership compares resolved paths (no `..`, no escaping symlink); a Codex row whose rollout is not inside the Codex store is refused before any mutation. Test `test_ownership_uses_resolved_paths`.
- IR9-04 fixed: "Leave in review" now applies In Review (tracker move, or run status `review` for a /run card), so a resumed Done/Todo card lands where the user chose.
- Proof: 558 passed.

## Inspection 10 (fresh Codex) — REVISE (4 medium, 0 high)
- Result: /private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/43734fe6-827b-4456-8612-0540ddad69af/scratchpad/claudex/i10/claudex-hhbijd1c/result.json (assurance cross_provider)
```json
{
 "verdict": "REVISE",
 "summary": "Concrete defects remain in interrupted-session recovery, attempt selection, interactive completion, and Codex store confinement.",
 "findings": [
  {
   "id": "UI10-01",
   "severity": "medium",
   "path": "runner/project_runs.py:342",
   "evidence": "session_id_of reads session_id, but DSH announces its identity as {type: \"session\", sessionId: ...}, as consumed by runner/dsh_cli.py. Consequently, a fresh DSH run never publishes its session identity onto the running job. Cancellation, stall, or timeout before normal reader return writes a record without that identity, making strict quick reply reject an existing resumable session.",
   "fix": "Handle DSH's sessionId field and publish it onto the job immediately. Preserve known resume identities before launch and cover interrupted DSH runs in the recovery checks."
  },
  {
   "id": "UI10-02",
   "severity": "medium",
   "path": "runner/templates/index.html:4534",
   "evidence": "The attempt picker changes viewRunId, but Quick reply always posts to _cardTerm.runId. If attempt A used session S1 and a later fallback created S2, selecting A and answering its pinned question silently continues S2. The backend also resolves continuation through the task's latest session, so merely changing the requested run ID would not fully fix the association.",
   "fix": "Bind strict continuation to the displayed attempt's verified session, or disable Quick reply while viewing older attempts and clearly identify the session it will continue. Keep server-side card exclusion."
  },
  {
   "id": "UI10-03",
   "severity": "medium",
   "path": "runner/templates/index.html:4505",
   "evidence": "Tracker-linked completion immediately reports 'marked done', 'sent back to Todo', or 'left in review'. _moveLinearIssueToColumn starts two requests without awaiting or checking either response. A maintenance refusal, missing issue, or Linear failure therefore leaves the requested transition unapplied while hiding the choice controls and reporting success. The synchronous tracker route additionally ignores update_issue_state's False result.",
   "fix": "Await and validate the authoritative transition, propagate tracker mutation failures, and display success only after confirmation. Retain the next-state controls and show an actionable error when saving fails."
  },
  {
   "id": "UI10-04",
   "severity": "medium",
   "path": "runner/projects.py:1634",
   "evidence": "Codex target validation checks the resolved rollout against CODEX_DB.parent but never checks the database itself. If state_5.sqlite is a symlink to a database outside the configured Codex store, a matching row with an in-store rollout passes validation; _codex_update then follows that symlink and modifies the external database. This violates A's resolved store-containment requirement.",
   "fix": "Validate the resolved database path against the configured store before opening it, and carry that validated database target through the mutation. Refuse an escaping database symlink and add a corresponding confinement check."
  }
 ],
 "coverage": [
  "Verified the plan digest and all 18 manifest file SHA256 values against disk.",
  "Inspected every manifest file, including implementation changes, added tests, affected existing test code, and review-log dispositions.",
  "Traced project labels through creation, normalization, synchronization, backups, dispatch, and lock handoff.",
  "Traced session resolution, mutations, freshness checks, admission claims, PTY ownership, confidentiality policy, and closure audits.",
  "Traced process-engine callers, retry/fallback, cancellation, stall detection, timeout records, durable replay, and history.",
  "Inspected card terminal controls, attempt switching, reconnect, project selection, file browsing, and Run tests wording.",
  "Followed related callers and shared-state code beyond the manifest, including dsh_cli.py, reset_gen.py, state_io.py, run_skill.py, usage_reader.py, and stall_detection."
 ],
 "limitations": [
  "Static inspection only: no edits, tests, delegation, browser operations, or native CLI operations.",
  "Historical test-pass and manual-validation claims were not independently verified.",
  "Native resume-picker behavior and live Linear API semantics were not exercised.",
  "SPEC.md and broader architecture documents were not inspected under the supplied scope restriction; fidelity was assessed against the supplied plan and inspected implementation contracts."
 ]
}
```

### Dispositions (host Claude; all 4 verified and fixed)
- UI10-01 fixed: `session_id_of` reads dsh's `{"type": "session", "sessionId": …}`. Test `test_dsh_session_announcement_is_recognised`.
- UI10-02 fixed: quick reply is offered on the latest attempt only (input disabled with a hint on earlier attempts; the send path refuses too), so it can never continue a different session than the one viewed.
- UI10-03 fixed: the next-state choice awaits the authoritative PATCH (tracker route or run status) and shows success only on confirmation; on failure the choice stays with the error. Not changed (pre-existing, out of scope): the synchronous Linear route ignoring `update_issue_state`'s return value.
- UI10-04 fixed: the Codex database is resolved and must stay inside the Codex store before it is read or written (`_codex_db_checked`). Test `test_codex_database_symlink_out_of_the_store_is_refused`.
- Proof: 560 passed.

## Inspection 11 (fresh Codex) — REVISE (4 medium, 0 high)
- Result: /private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/43734fe6-827b-4456-8612-0540ddad69af/scratchpad/claudex/i11/claudex-3ug0tfrt/result.json (assurance cross_provider)
```json
{
 "verdict": "REVISE",
 "summary": "Four material defects remain in interactive completion, continuation identity, reconnect recovery, and asynchronous card updates.",
 "findings": [
  {
   "id": "UI11-01",
   "severity": "medium",
   "path": "runner/modules/linear/__init__.py:1208",
   "evidence": "The completion PATCH ignores update_issue_state's False result. If Linear rejects the mutation or cannot resolve the requested state, the subsequent fetch can succeed with the unchanged issue. _apply_local_override then masks that unchanged state, and the route returns ok:true. Consequently, _cardTermNext reports 'marked done' despite the remote issue remaining unchanged. Awaiting this route does not resolve the previously identified UI10-03 defect.",
   "fix": "Propagate mutation failures, remove the rejected state override, and confirm the returned state before reporting success. Keep the completion choices available when saving fails."
  },
  {
   "id": "UI11-02",
   "severity": "medium",
   "path": "runner/app.py:4076",
   "evidence": "Strict continuation selects the task's newest session rather than verifying the displayed run's session. A supported UI sequence exposes this: select older attempt A, open it interactively, show it in the panel, close the modal, then close its panel tab. _promptCardNext(A) reopens A; _cardTermAttempts incorrectly labels that opened run 'latest' even when attempt B exists. Quick reply displays A's question but resumes B's session through _get_task_agent_lock.",
   "fix": "Validate strict continuation against the requested run's recorded agent/session and reject stale associations before side effects. Derive the actual latest attempt from server history instead of treating the opened run as latest."
  },
  {
   "id": "UI11-03",
   "severity": "medium",
   "path": "runner/templates/index.html:4579",
   "evidence": "Reconnect only reattaches an embedded interactive PTY. An embedded headless run has no server terminal entry and receives no fresh /events snapshot. If the socket disconnects while that run emits its final events and completes, reconnect leaves missing output, the 'running…' pinned message, and hidden interactive-resume controls indefinitely. Board refresh does not reload the open terminal view.",
   "fix": "Reload the selected embedded run's event snapshot and completion metadata on reconnect, using the existing sequence buffering and view guards."
  },
  {
   "id": "UI11-04",
   "severity": "medium",
   "path": "runner/templates/index.html:4516",
   "evidence": "_cardTermNext's save callback lacks a card/view identity check. Choose a completion state for card A, then open card B while the Linear request is pending. A's response writes its success message into B's reused status element; a failure additionally exposes completion choices on B even if B's interactive session has not ended. Clicking those misplaced choices then changes B's state.",
   "fix": "Capture the initiating card, run, and view generation, and update visible controls only while that same view remains current."
  }
 ],
 "coverage": [
  "Verified the supplied plan digest and all 18 manifest file SHA256 values against disk.",
  "Reviewed the plan, review-log evidence, implementation changes, every added test source, and affected existing test hunks.",
  "Traced project labels through creation, synchronization, backups, dispatch, and lock reservation/handoff.",
  "Traced session mutations, PTY ownership and policy, terminal finalization, closure audits, retry/fallback, interrupted-run records, replay, and history.",
  "Inspected task-project selection, file browsing, terminal callbacks, reconnect handling, and Run tests wording.",
  "Followed related code beyond the manifest, including reset_gen.py, state_io.py, run_skill.py, dsh_cli.py, usage_reader.py, stall_detection, module registration, and relocation admission."
 ],
 "limitations": [
  "Static inspection only: no edits, tests, delegation, browser operations, or native CLI operations.",
  "Historical test-pass and manual-validation claims were not independently verified.",
  "Native resume-picker behavior and live Linear GraphQL semantics were not exercised.",
  "SPEC.md and broader architecture documents were not inspected; fidelity was assessed against the supplied plan and inspected implementation contracts."
 ]
}
```

### Dispositions (host Claude; all 4 verified and fixed)
- UI11-01 fixed: the synchronous Linear PATCH reports a refused state change (502) and drops its masking override, so the awaited next-state choice can no longer show success on an unchanged issue. Test `test_rejected_linear_state_is_reported_not_masked`.
- UI11-02 fixed: strict continuation is refused when the answered run's recorded session is not the card's current one; the attempt picker takes "latest" from the server's history (which includes a running attempt). Test `test_strict_reply_to_an_older_attempt_is_refused`.
- UI11-03 fixed: a socket reconnect reloads an embedded run view's snapshot (and rejoins an embedded interactive session).
- UI11-04 fixed: the next-state save updates the view only if the same card is still shown.
- Browser re-check (isolated runner): create with project → dispatch → live view → quick reply (attempt 2, same session) → attempt 1 has reply disabled, latest enabled → open interactive → End → Mark done: one audit entry, task Done, status "session ended · marked done".
- Proof: 562 passed.

## Inspection 12 (fresh Codex) — REVISE (3 medium, 0 high)
- Result: /private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/43734fe6-827b-4456-8612-0540ddad69af/scratchpad/claudex/i12/claudex-_lif4cpo/result.json (assurance cross_provider)
```json
{
 "verdict": "REVISE",
 "summary": "Three material defects remain in failed completion recovery, attempt history, and completion callbacks.",
 "findings": [
  {
   "id": "UI12-01",
   "severity": "medium",
   "path": "runner/modules/linear/__init__.py:338",
   "evidence": "Choosing “Send back to Todo” increments reset_generation before the tracker mutation. If Linear refuses that mutation, the route now returns 502, but the generation increment remains. The issue stays In Review while _get_task_agent_lock ignores its existing session records. Quick reply subsequently returns “no resumable session,” and ordinary retry starts fresh despite the rejected transition.",
   "fix": "Commit the generation change only when the state transition succeeds, while retaining issue-lock serialization. Verify that a refused Todo transition preserves both generation and continuation eligibility."
  },
  {
   "id": "UI12-02",
   "severity": "medium",
   "path": "runner/app.py:4376",
   "evidence": "For dashboard /run tasks without a tracker ID, history returns only the requested attempt and its ancestors. After A has continuation B, reopening A returns only A. _cardTermAttempts consequently hides B and labels A “latest.” If B established another session, Quick reply rejects A as stale, but the picker provides no way to select B. This leaves C's complete attempt picker and the latest-attempt restriction incomplete.",
   "fix": "Resolve the canonical task identity and return all its execution attempts, including descendants and active jobs. Derive the latest attempt from that complete history."
  },
  {
   "id": "UI12-03",
   "severity": "medium",
   "path": "runner/templates/index.html:4519",
   "evidence": "The completion callback checks card generation but not the selected attempt. End interactive attempt A, choose a state, then select attempt B while saving is pending. If A's save fails, its callback exposes completion choices beneath B. Clicking those choices on an unlinked /run task now updates B's status, although B's interactive session was not the one ended. _cardTermLoad neither changes the card generation nor clears these choices.",
   "fix": "Associate completion controls and pending saves with the ended run. Check the captured run identity before updating controls, and clear or restore completion controls appropriately when switching attempts."
  }
 ],
 "coverage": [
  "Verified the supplied plan digest and all 18 manifest file SHA256 values.",
  "Reviewed the plan, review log, every changed implementation file, all added test sources, and affected existing test changes.",
  "Traced project labels, local backups, synchronization, dispatch, and lock handoff.",
  "Traced session mutations, admission claims, PTY ownership, confidentiality policy, finalization, and closure audits.",
  "Traced process-engine callers, interruption records, event streaming, replay, history, and terminal callbacks.",
  "Inspected related shared-state code beyond the manifest, including reset_gen.py, state_io.py, run_skill.py, dsh_cli.py, stall detection, and relocation admission."
 ],
 "limitations": [
  "Static inspection only: no edits, tests, delegation, browser operations, or native CLI operations.",
  "Historical test-pass and manual-validation claims were not independently verified.",
  "Native resume-picker behavior and live Linear API semantics were not exercised.",
  "SPEC.md and broader architecture documents were not inspected; fidelity was assessed against the supplied plan and inspected implementation contracts."
 ]
}
```

### Dispositions (host Claude)
- UI12-01 deferred (accepted risk, pre-existing): `_tracker_reset_route` (Decision 11, runner-write-safety era) bumps the reset generation before any Todo transition; a transition Linear refuses has always left it bumped. This build only made the refusal visible (UI11-01). Ordering the generation commit after the tracker mutation is tracker-write ordering, owned by the pending plan `2026-10-15-tracker-write-ordering.md` (added there as a carried finding at its next revision).
- UI12-02 fixed: /history of a dashboard task returns every attempt sharing its root task id (descendants and a running one included); the picker's "latest" is therefore always the real latest. Test `test_history_of_an_older_dashboard_attempt_shows_the_later_ones`.
- UI12-03 fixed: the next-state choice belongs to the run whose session ended (`endedRunId`): switching attempts hides it for other runs, and a pending save's failure only re-shows it on the same attempt.
- Proof: 563 passed.

## Inspection 13 (fresh Codex) — REVISE (2 medium, 0 high)
- Result: /private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/43734fe6-827b-4456-8612-0540ddad69af/scratchpad/claudex/i13/claudex-g4j7knbl/result.json (assurance cross_provider)
```json
{
 "verdict": "REVISE",
 "summary": "Two material defects remain in failed tracker-transition recovery and interactive-terminal attempt ownership.",
 "findings": [
  {
   "id": "IR13-01",
   "severity": "medium",
   "path": "runner/modules/linear/__init__.py:338",
   "evidence": "The Todo route increments reset_generation before the tracker mutation. If Linear rejects the transition, the route returns 502 but leaves the generation incremented. The issue remains In Review while _get_task_agent_lock (app.py:2652) discards its existing session records. Quick reply then returns 'no resumable session', and ordinary retry starts fresh. The review log explicitly defers this defect; it remains reachable through C2's new completion controls.",
   "fix": "Commit the generation change only after a confirmed transition, retaining issue-lock serialization. A rejected transition must preserve the previous generation and continuation eligibility."
  },
  {
   "id": "IR13-02",
   "severity": "medium",
   "path": "runner/templates/index.html:4412",
   "evidence": "Reattachment finds an interactive terminal by card_key but ignores its run_id. With attempts A/S1 and B/S2, open A interactively, reload, then reopen the latest card B. The view attaches A's terminal while the selector identifies B; _cardTermAttach never updates viewRunId or loads A's metadata. Ending A consequently sets endedRunId to B (line 4502). On an unlinked task, completion changes B's status. After reload, Quick reply can also remain enabled and continue B/S2 despite the user having viewed A/S1.",
   "fix": "Bind reattached terminals to their server-reported run_id. Synchronize the selected attempt, session metadata, pinned message, reply eligibility, and completion controls with that identity. Use the terminal's owning run for closure actions."
  }
 ],
 "coverage": [
  "Verified the supplied plan SHA256 and all 18 manifest file hashes against disk.",
  "Reviewed the plan, review-log dispositions, changed implementation hunks, all added test sources, and affected existing test changes.",
  "Traced session mutation, freshness checks, admission claims, PTY ownership, confidentiality policy, and terminal finalization.",
  "Traced project labels through creation, synchronization, normalization, backups, dispatch, and lock handoff.",
  "Traced process-engine callers, retry/fallback, interruption records, streaming, replay, history, and card-terminal callbacks.",
  "Inspected file browsing, task-project selection, Run tests wording, and related shared-state code in reset_gen.py, state_io.py, run_skill.py, stall_detection, and relocation admission."
 ],
 "limitations": [
  "Static inspection only: no edits, tests, delegation, browser operations, or native CLI operations.",
  "Historical test-pass claims, native resume-picker behavior, and live Linear API behavior were not independently verified.",
  "SPEC.md and broader architecture documents were not inspected under the supplied scope restriction; fidelity was assessed against the plan and inspected implementation contracts."
 ]
}
```

### Dispositions (host Claude; both fixed)
- IR13-01 (= UI12-01) fixed instead of deferred: `_tracker_reset_route` still bumps first (in-flight older pushes are dropped during the move), but rolls the bump back (`reset_gen.restore`, only if nothing bumped again) when the route's response is an error, all under the issue lock. Test `test_refused_move_to_todo_does_not_reset_the_ticket`. The UI12-01 note about carrying this into the tracker-write-ordering plan is withdrawn.
- IR13-02 fixed: a reattached interactive terminal is shown as the attempt it belongs to (`_cardTermUse(run_id)`): selector, metadata, pinned message, reply eligibility and the ended-run identity follow the terminal's server-reported run.
- Proof: 564 passed.

## Inspection 14 (fresh Codex) — REVISE (3 medium, 0 high)
- Result: /private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/43734fe6-827b-4456-8612-0540ddad69af/scratchpad/claudex/i14/claudex-27i1v1i8/result.json (assurance cross_provider)
```json
{
 "verdict": "REVISE",
 "summary": "Three material defects remain in live-session exclusion, terminal attempt ownership, and reset-generation rollback.",
 "findings": [
  {
   "id": "UI14-01",
   "severity": "medium",
   "path": "runner/modules/pty/__init__.py:333",
   "evidence": "Projects-panel resumes resolve card ownership through card_run_for_session, which searches completed records only (app.py:3482). A fresh runner-root Codex session can already appear in the Projects panel while its identity exists only in _running_jobs. Resuming it finds no owning run and acquires no card lock, allowing an interactive process to overlap the headless run. The session_lock at line 393 only serializes admission; it does not check whether that session is already running.",
   "fix": "Resolve session ownership against running jobs and pending session claims as well as durable records. Refuse a resume of an actively running session before spawning, under the session admission lock."
  },
  {
   "id": "UI14-02",
   "severity": "medium",
   "path": "runner/templates/index.html:4513",
   "evidence": "End session captures the card generation but not the owning attempt. Start closing interactive attempt A, then select attempt B while term_close waits for process cleanup. Attempt selection leaves the card generation unchanged. A's callback therefore calls _cardTermEnded using B's current viewRunId, setting endedRunId to B. For an unlinked task, the completion choices subsequently change B's status although A's terminal was closed. The server's returned run_id is ignored.",
   "fix": "Capture the owning run, terminal, and attempt generation before closing. Associate completion choices with that captured run, and update visible controls only when the matching attempt remains selected. Apply equivalent attempt guards to asynchronous reattachment."
  },
  {
   "id": "UI14-03",
   "severity": "medium",
   "path": "runner/modules/linear/__init__.py:345",
   "evidence": "Reset rollback assumes every error response means the Todo transition was refused. However, update_issue_state can succeed at line 1214 and the subsequent fetch_issue can fail, producing a 500 at line 1227. The wrapper then restores the previous generation despite Linear having accepted Todo. Existing session records become current again, and an older run's completion can pass the generation check and move the successfully reset issue back to review.",
   "fix": "Track whether the authoritative state mutation committed. Roll back the generation only when the mutation was refused before committing; retain the new generation when a later refresh fails, and report the refresh failure separately."
  }
 ],
 "coverage": [
  "Verified the supplied plan digest and all 19 manifest file hashes against disk.",
  "Inspected every manifest file, including implementation changes, added test sources, affected existing tests, and review-log dispositions.",
  "Traced project labels through creation, synchronization, local backups, dispatch, and lock handoff.",
  "Traced session mutations, live identities, PTY admission, confidentiality policy, finalization, and closure audits.",
  "Traced process-engine callers, interruption records, streaming, durable replay, history, and terminal callbacks.",
  "Inspected file browsing, project selection, Run tests wording, and related callers and state writers in state_io.py, run_skill.py, usage_reader.py, and stall_detection."
 ],
 "limitations": [
  "Static inspection only: no edits, tests, delegation, browser operations, or native CLI operations.",
  "Historical test-pass and manual-validation claims were not independently verified.",
  "Native resume-picker behavior and live Linear API semantics were not exercised.",
  "SPEC.md and broader architecture documents were not inspected; fidelity was assessed against the supplied plan and inspected implementation contracts."
 ]
}
```

### Dispositions (host Claude; all 3 fixed)
- UI14-01 fixed: under the session admission lock, a resume of a session that is live (running job, pending claim, or another open tab) is refused before spawning. Test `test_resume_of_a_session_a_headless_run_is_in_is_refused`.
- UI14-02 fixed: End session captures the owning run (and uses the server's returned run_id); the next-state choice is shown only while that run is the selected attempt; an applied choice clears it so a reload does not offer it again.
- UI14-03 fixed: the reset rollback happens only when the request's state change never committed (`g.tracker_state_committed`, set after a successful local update or Linear state mutation). Test `test_committed_reset_keeps_its_generation_when_the_refresh_fails`.
- Test isolation: the C2 harness gives each test its own `_SESSION_CLAIMS` (a stubbed project helper never releases its claim).
- Proof: 566 passed.

## Inspection 15 (fresh Codex) — REVISE (2 medium, 0 high)
- Result: /private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/43734fe6-827b-4456-8612-0540ddad69af/scratchpad/claudex/i15/claudex-y624b1h5/result.json (assurance cross_provider)
```json
{
 "verdict": "REVISE",
 "summary": "Two material defects remain in terminal reattachment and active-attempt history.",
 "findings": [
  {
   "id": "UI15-01",
   "severity": "medium",
   "path": "runner/templates/index.html:4413",
   "evidence": "While reattaching interactive attempt A, _cardTermUse awaits its events request. If the user selects attempt B meanwhile, _cardTermUse returns without applying A's metadata, but _cardTermOpen still calls _cardTermAttach(A): it checks only the unchanged card generation. The selector, pinned message and reply eligibility can therefore describe B while keyboard input goes to A's session. This leaves the asynchronous reattachment gap identified in UI14-02 unresolved.",
   "fix": "Guard the entire reattachment operation with an attempt generation and owning run ID. Have _cardTermUse report whether it applied successfully, and attach only if that attempt remains selected. Reconcile attachment metadata with the terminal's server-reported run_id."
  },
  {
   "id": "UI15-02",
   "severity": "medium",
   "path": "runner/app.py:4346",
   "evidence": "History incorporates only the running job whose ID exactly matches the requested run_id. For GET /api/runs/linear-I/history, that lookup cannot find active attempt B keyed by its actual run ID. Both tracker-linked branches return before the later running-job enumeration. With completed A and running B belonging to issue I, issue history consequently returns A alone. Opening an older run reference can hide B from the attempt picker and incorrectly identify A as latest; the browser workaround appends only the opened run.",
   "fix": "Merge all matching running jobs into tracker-linked history before returning, deduplicated by run ID and sorted with completed attempts. Cover both virtual issue-history requests and requests through an older completed attempt."
  }
 ],
 "coverage": [
  "Verified the supplied plan digest and all 19 manifest file SHA256 values against disk.",
  "Reviewed the plan, review-log evidence, implementation changes, all added test sources, and affected existing test hunks.",
  "Traced project labels through creation, synchronization, backups, dispatch, and lock handoff.",
  "Traced session mutations, live-session admission, PTY ownership, confidentiality policy, finalization, and closure audits.",
  "Traced process-engine callers, interruption records, streaming, replay, history, and terminal callbacks.",
  "Inspected project browsing, project selection, Run tests wording, and related state writers in reset_gen.py, state_io.py, run_skill.py, usage_reader.py, and stall_detection."
 ],
 "limitations": [
  "Static inspection only: no edits, tests, delegation, browser operations, or native CLI operations.",
  "Historical validation claims, native resume-picker behavior, and live Linear API semantics were not independently verified.",
  "SPEC.md and broader architecture documents were not inspected; fidelity was assessed against the supplied plan and inspected implementation contracts."
 ]
}
```

### Dispositions (host Claude; both fixed)
- UI15-01 fixed: `_cardTermUse` reports whether it applied; reattachment attaches only if the owning attempt is still selected once its metadata lands.
- UI15-02 fixed: /history merges every running attempt (keyed by its own run id, with its issue/task/parent) before any branch, so issue history and history through an older attempt both include the active one. Test `test_issue_history_includes_a_running_attempt`.
- Proof: 567 passed.

## Inspection 16 (Codex) — FAILED: provider unavailable (usage limit until 06:05)
- Result: /private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/43734fe6-827b-4456-8612-0540ddad69af/scratchpad/claudex/i16/claudex-ys3jj4rv/result.json

## Inspection 16b (fresh Claude, degraded fallback) — APPROVED (2 low)
- Result: /private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/43734fe6-827b-4456-8612-0540ddad69af/scratchpad/claudex/i16b/claudex-2oio0scd/result.json (assurance degraded_same_provider)
```json
{
 "verdict": "APPROVED",
 "summary": "I found no material defects left after inspection round 15. I traced the paths most likely to break: retry and quick-reply admission (session claim, card/ticket lock reservation and hand-off), Linear PATCH reservation and dispatch hand-off, PTY open/close/finalize, run-bound resume ownership, events/history endpoints, session rename/remove confinement, file-browser confinement and git hardening. None of them showed a reachable correctness or security failure. Two low-severity items remain. First, the event ring for a run can be created twice when its stdout and stderr readers start at the same moment. Second, there is an unverified risk that a Codex \"remove\" which only sets the database flag does not match what Codex's own archive does. The native-picker acceptance criteria are already marked PARTIAL. This is a same-provider fallback review, so it is not independent of the builder.",
 "findings": [
  {
   "id": "FB4-01",
   "severity": "low",
   "path": "runner/project_runs.py:201",
   "evidence": "`ring_for` does a non-atomic check-then-set: `ring = RUN_EVENTS.get(run_id); if ring is None: ring = RUN_EVENTS[run_id] = EventRing()`. For every engine launch (`run_agent_process`), nothing creates the ring before the readers start. `_read_both` then starts the stdout reader (`_publish_run_line` → `ring_for`) and the stderr drain (`_StderrSink._line` → `ring_for`) on two real threads at the same time. If a CLI writes its first stdout event and a startup stderr warning together, both threads can see None, and each creates a ring. One ring overwrites the other, so the lines appended to the lost ring disappear from later `/events` snapshots. They were emitted live, so the replay and the live view diverge. Their `seq` numbers also come from two counters, which breaks the UI-13 cursor handoff for a viewer that loads during that window. `project_runs.run_agent` avoids this only because it calls `ring_for` before starting its readers.",
   "fix": "Make creation atomic. Use `ring = RUN_EVENTS.setdefault(run_id, EventRing())`, or a module lock around get/create/evict. Alternatively, call `project_runs.ring_for(run_id)` in `run_agent_process` before starting the readers, as `run_agent` already does."
  },
  {
   "id": "FB4-02",
   "severity": "low",
   "path": "runner/projects.py:1700",
   "evidence": "Codex remove only runs `UPDATE threads SET archived = 1, archived_at = ?`, and rename only sets `threads.name`. The plan's decision is to use Codex's 'native archiving'. As far as I recall (not verified here), Codex's own archive also moves the rollout file from `~/.codex/sessions/` to `~/.codex/archived_sessions/`, and some `codex resume` versions build their picker by scanning rollout files rather than the state database. If that holds, a dashboard-removed Codex session stays in `codex resume`, and a dashboard rename may not appear there. That would break acceptance criteria A1/A2 ('gone from … `codex resume`'). Those criteria are already PARTIAL because the native picker was never opened.",
   "fix": "Before marking A1/A2 done, check the installed Codex's archive and rename semantics: run the native archive/rename on a throwaway thread and diff `state_5.sqlite`, `sessions/`, `archived_sessions/` and `session_index.jsonl`. Then mirror exactly what Codex does, or document that only the database-backed views are affected."
  }
 ],
 "coverage": [
  "Read the full plan, the review-log dispositions through inspection 15, and the full tracked diff for runner/app.py, linear_client.py, modules/linear/__init__.py, local_tracker.py, modules/pty/__init__.py, project_runs.py, projects.py, reset_gen.py and templates/index.html",
  "Traced api_run_retry in the current file: unsynced guard, strict continuation and the stale-session check, _claim_session, the card_lock/ticket_lock reservation and its release on every early return, project hand-off (ticket_hold through @_counted and the _run_project_ticket ExitStack), and the job record fields used by _live_session_ids",
  "Traced Linear _issues_patch → reserve_card → _issues_patch_reserved → _start_dispatch → _dispatch_issue_held (project identity check and pop_all hand-off; runner-root card lock held through the run), plus the _issues_local_patch refusal and the concurrent board local/main PATCH ordering under reset_gen.issue_lock",
  "Checked _tracker_reset_route rollback against both PATCH routes and where _state_committed is called on the local, local-first and synchronous Linear paths",
  "Traced PTY open_terminal (run-bound resume via card_run_for_session/_latest_record, project/ticket/card lock, session_lock admission, live-session refusal, registration before the admission lock is released), plus close_terminal/_reader/_finalize",
  "Checked that every _running_jobs writer (/run both paths, retry, project helper, Linear dispatch) carries the 'agent' key that _live_session_ids relies on",
  "Reviewed api_run_events and api_run_history (running-attempt merge, dashboard root-task branch), _replay_lines, the meta sidecar merge, _StderrSink and _read_both",
  "Reviewed session_target/rename/remove (resolved-path containment, O_NOFOLLOW append with utime restore, EXDEV check, Codex DB containment) and list_dir/read_file/_browse_path/_browse_root, including the _git hardening and the repo-root guarantee for registered projects",
  "Checked the request-token gate (all /api routes need the token, including the GET tree/file routes) and the app/runner module aliasing (sys.modules['app'])",
  "Reviewed the board/detail JS for the card Terminal tab, the attempt picker, quick reply, next-state choices (status route accepts success/todo/review), the project selector and the waiting badge; confirmed the referenced helpers exist (_storageRemove, _detailDoneStateName, TERM_OPTS, _isModalOpen, _trackerType)"
 ],
 "limitations": [
  "DEGRADED_SAME_PROVIDER: same-provider fallback reviewer (shares the builder's provider); this is not an independent cross-provider inspection",
  "Static inspection only: no tests run, and no browser, PTY, native claude/codex picker or live Linear API checks. The claimed 567 passing tests were not verified",
  "FB4-02 relies on recalled Codex CLI archive/rename behaviour (rollout relocation, session index) that could not be checked against the installed Codex version",
  "The new test files were not read in full; SPEC.md was only grep-checked, and other architecture documents were not inspected",
  "Linear GraphQL semantics (eqIgnoreCase, team null filter) and Claude print-mode resume session-id stability were not verifiable",
  "DEGRADED_SAME_PROVIDER: preferred reviewer codex was unavailable; claude reviewed in a fresh fallback session without cross-provider independence."
 ]
}
```

### Dispositions (host Claude; both low findings fixed after the approval, so the approval does not cover them)
- FB4-01 fixed: `ring_for` creates a run's ring with `setdefault`, so a stdout reader and a stderr drain starting together share one ring.
- FB4-02 fixed after checking the installed Codex store read-only: its archived threads live in `~/.codex/archived_sessions/` with `rollout_path` pointing there, and thread names also live in `session_index.jsonl`. Remove now moves the rollout into `archived_sessions/` and archives the row with its new path (move undone if the database update fails); rename appends a `session_index.jsonl` entry and sets `threads.name` (index entry cut back if the database update fails). Tests extended.
- Proof: 567 passed.
- Next: a cross-provider Codex inspection after the quota reset (06:05) is required by the plan's completion criterion.

## Inspection 17 (fresh Codex, after quota reset) — REVISE (2 medium, 0 high)
- Result: /private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/43734fe6-827b-4456-8612-0540ddad69af/scratchpad/claudex/i17/claudex-cfm8xy43/result.json (assurance cross_provider)
```json
{
 "verdict": "REVISE",
 "summary": "Two material defects remain in the newly added Codex session mutations: rollback can erase unrelated index updates, and archiving can write outside the configured store.",
 "findings": [
  {
   "id": "CR-01",
   "severity": "medium",
   "path": "runner/projects.py:1706",
   "evidence": "Codex rename records the shared session_index.jsonl size, appends its entry, and truncates back to that size if the database update fails. Admission locks are per session, so another session can append meanwhile. For example, rename A waits on a busy SQLite database, rename B appends, and A times out: A's rollback deletes B's entry too. B can subsequently commit its database update, leaving its native-picker title inconsistent. This violates A's unchanged-on-failure guarantee.",
   "fix": "Serialize dashboard index mutations at store scope and replace unconditional truncation with rollback that preserves other writers' entries. Account for native Codex writers as well; use a supported native mutation or an operation-specific corrective entry. Cover concurrent appends during a failed database update."
  },
  {
   "id": "CR-02",
   "severity": "medium",
   "path": "runner/projects.py:1756",
   "evidence": "The new archive destination is never checked for resolved containment. If <CODEX_HOME>/archived_sessions is a symlink to an external directory, mkdir(exist_ok=True) accepts it, os.rename moves the rollout outside the Codex store, and the database update succeeds. Source-rollout and database checks do not protect this destination. The operation therefore violates A's resolved store-confinement requirement.",
   "fix": "Validate the archive directory and destination against the resolved Codex store before moving anything, rejecting escaping symlinks. Preserve that validated destination through the move and rollback, and add an escaping-archive-directory check."
  }
 ],
 "coverage": [
  "Verified the plan digest, all 19 manifest file hashes, and the tracked diff digest.",
  "Reviewed the supplied plan, review-log changes, every changed implementation file, all added test sources, and affected existing test code.",
  "Traced session mutations, live-session exclusion, PTY ownership, confidentiality policy, terminal finalization, and closure audits.",
  "Traced project labels through creation, synchronization, local backups, dispatch, and lock handoff.",
  "Inspected process-engine callers, interruption records, streaming, replay, history, card-terminal callbacks, file browsing, project selection, and Run tests wording.",
  "Followed related state readers and writers beyond the manifest, including state_io.py, run_skill.py, usage_reader.py, and stall_detection."
 ],
 "limitations": [
  "Static inspection only: no edits, tests, delegation, browser operations, or native CLI operations.",
  "Historical test-pass claims and manual-validation claims were not independently verified.",
  "Native resume-picker behavior and live Linear API semantics were not exercised.",
  "SPEC.md and broader architecture documents were not inspected; fidelity was assessed against the supplied plan and inspected implementation contracts."
 ]
}
```

### Dispositions (host Claude; both fixed)
- CR-01 fixed: Codex rename treats the shared session_index.jsonl as append-only — database first, then one appended entry; if the append fails the old name is restored in the database. The index is never truncated, so other writers' entries survive. Test `test_codex_index_rollback_never_cuts_other_entries`.
- CR-02 fixed: `archived_sessions` (and the index) must be a real path directly inside the resolved Codex store (`_codex_store_child`); an escaping symlink is refused before anything moves. Test `test_codex_archive_dir_symlink_out_of_the_store_is_refused`.
- Proof: 569 passed.

## Inspection 18 (fresh Codex) — REVISE (1 medium)
- Result: /private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/43734fe6-827b-4456-8612-0540ddad69af/scratchpad/claudex/i18/claudex-v5j2wwgx/result.json (assurance cross_provider)
```json
{
 "verdict": "REVISE",
 "summary": "Codex rename still violates Part A’s failure guarantee by leaving a partial record in the shared session index.",
 "findings": [
  {
   "id": "CR18-01",
   "severity": "medium",
   "path": "runner/projects.py:1710",
   "evidence": "If os.write appends only part of the session_index.jsonl entry, rename_session raises and restores the database name, but leaves the appended fragment. A short write caused by insufficient disk space therefore changes the native store despite reporting failure. The fragment lacks a newline, so the next writer’s entry is concatenated onto invalid JSON. test_codex_index_rollback_never_cuts_other_entries fails os.open before any bytes are written and misses this case.",
   "fix": "Use a recoverable append protocol that handles partial writes without truncating unrelated concurrent entries. Ensure failure leaves no unterminated record and verify both a short append and a subsequent unrelated append remain recoverable."
  }
 ],
 "coverage": [
  "Verified the plan digest, all 19 manifest file hashes, and the tracked-diff digest.",
  "Reviewed the plan, review-log changes, every changed implementation file, added test sources, and affected existing test code.",
  "Traced session mutation, freshness checks, admission claims, PTY ownership, confidentiality policy, finalization, and closure audits.",
  "Traced project labels through creation, synchronization, local backups, dispatch, and lock handoff.",
  "Inspected process-engine callers, interruption records, streaming, replay, history, terminal callbacks, project selection, file browsing, and Run tests wording.",
  "Followed related readers and writers beyond the manifest, including state_io.py, run_skill.py, usage_reader.py, dsh_cli.py, and stall_detection."
 ],
 "limitations": [
  "Static inspection only: no files edited, tests executed, work delegated, or browser/native CLI operations performed.",
  "Historical test-pass and manual-validation claims were not independently verified.",
  "Native resume-picker behavior and live Linear API semantics were not exercised.",
  "SPEC.md and broader architecture documents were not inspected; fidelity was assessed against the supplied plan and implementation contracts."
 ]
}
```

### Disposition (host Claude; fixed)
- CR18-01 fixed: `_append_line` appends to the shared index without ever cutting it — a record left unterminated earlier is closed first, a short write is finished, and a write that fails midway still closes its fragment, so the next record always starts on its own line (a reader skips one bad line, never two merged). Test `test_codex_index_partial_write_is_closed_and_healed`.
- Proof: 570 passed (full suite run below before the next inspection).

## Inspection 19 (fresh Codex) — REVISE (4 medium)
- Result: /private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/43734fe6-827b-4456-8612-0540ddad69af/scratchpad/claudex/i19/claudex-w4_trc__/result.json (assurance cross_provider)
```json
{
 "verdict": "REVISE",
 "summary": "Four material defects remain: failed Codex rename recovery, usage accounting after removal, Codex message selection, and active-run event retention.",
 "findings": [
  {
   "id": "IR19-01",
   "severity": "medium",
   "path": "runner/projects.py:1716",
   "evidence": "_append_line leaves appended bytes after a partial write fails; tests/test_session_actions.py:333 explicitly expects a corrupt fragment to remain. rename_session restores only the database name. If the short write contains the complete JSON object except its newline, the index can even retain the requested title despite failure. Appending a newline does not satisfy A's unchanged-on-failure guarantee. Multiple writes also permit another index writer's record to interleave.",
   "fix": "Implement coordinated, recoverable index mutation that restores both name stores on failure without damaging unrelated appends. Cover partial writes, failure after a complete JSON object, and concurrent writers; do not treat retained corruption as successful recovery."
  },
  {
   "id": "IR19-02",
   "severity": "medium",
   "path": "runner/projects.py:1786",
   "evidence": "Removing an idle session used today changes budget accounting. Claude transcripts move outside the only directory scanned by usage_reader._claude_jsonl_files (usage_reader.py:246), so their consumed tokens disappear from daily totals and budget windows. Codex rollout relocation similarly removes usage from _codex_window_range's sessions scan; its SQLite fallback runs only when no other sessions remain. Hiding a session therefore understates already-consumed usage.",
   "fix": "Include trashed Claude transcripts and archived Codex rollouts in usage aggregation, deduplicated by session identity, while excluding them from resume/session lists. Verify that removal and restoration preserve usage totals."
  },
  {
   "id": "IR19-03",
   "severity": "medium",
   "path": "runner/app.py:3458",
   "evidence": "_assistant_text treats recorded output as the last assistant message. For Codex, _parse_agent_output at lines 2383–2393 concatenates every completed agent_message without separators. A run emitting 'working' followed by 'done' consequently pins 'workingdone'. An earlier approval-request phrase can also trigger 'Waiting for you' after the final message has completed the task. This violates C2's last-message requirement.",
   "fix": "Extract and persist the actual last assistant message separately from aggregate output, and use it for pinning and waiting detection. Cover multiple Codex messages with an earlier question and a final statement."
  },
  {
   "id": "IR19-04",
   "severity": "medium",
   "path": "runner/project_runs.py:201",
   "evidence": "ring_for evicts the oldest ring after 64 runs without checking whether it is active. With long-running A and 64 later runs, A's ring disappears. api_run_events only falls back to disk for finished runs, so opening A loses its existing output. Project readers retain the evicted ring reference, while other publishers can create a replacement with sequence numbers restarted at 1, undermining snapshot/cursor consistency.",
   "fix": "Preserve active-run rings and their sequence counters, evicting completed runs first. Alternatively, provide coordinated disk-backed snapshots for active runs and ensure all publishers retain one sequence identity. Cover retention-limit eviction while an earlier run remains active."
  }
 ],
 "coverage": [
  "Verified the plan digest, all 19 manifest file hashes, and the tracked-diff digest.",
  "Inspected every manifest file, implementation changes and relevant surrounding code, added test sources, and affected existing test changes.",
  "Traced session mutations, live-session exclusion, PTY ownership, policy enforcement, terminal finalization, and closure audits.",
  "Traced project labels through creation, synchronization, backups, dispatch, and lock handoff.",
  "Traced process-engine callers, retry/fallback, interruption records, streaming, replay, history, and terminal callbacks.",
  "Inspected file browsing, project selection, Run tests wording, and related readers/writers in usage_reader.py, state_io.py, run_skill.py, reset_gen.py, and stall_detection."
 ],
 "limitations": [
  "Static inspection only: no edits, tests, delegation, browser operations, or native CLI operations.",
  "Historical test-pass and manual-validation claims were not independently verified.",
  "Native resume-picker behavior and live Linear API semantics were not exercised.",
  "SPEC.md and broader architecture documents were not inspected; fidelity was assessed against the supplied plan and inspected implementation contracts."
 ]
}
```

### Dispositions (host Claude; all 4 fixed)
- IR19-01 fixed: a failed Codex rename restores the database name and appends a corrective index entry with the old name (the index is read newest-entry-wins), so even a fragment that happens to be whole is superseded; nothing is ever cut. Test `test_failed_codex_rename_supersedes_its_index_entry`.
- IR19-02 fixed: usage counts transcripts in the session trash (Claude) and rollouts in archived_sessions (Codex token window), so removing a session never un-counts consumed usage. Test `test_trashed_transcripts_still_count_for_usage`.
- IR19-03 fixed: Codex agent messages are joined with blank lines (no more "workingdone"), and "Waiting for you" reads only the last message paragraph. Test `test_codex_messages_stay_apart_and_live_rings_survive_eviction`.
- IR19-04 fixed: ring eviction skips runs that are still active (`project_runs.is_active`, wired to `_running_jobs`). Same test.
- Proof: 573 passed.
- Budget: inspection 20 is the last of MAX_INSPECTION_ROUNDS=20.

## Inspection 20 (fresh Codex, last of MAX_INSPECTION_ROUNDS=20) — REVISE (3 medium)
- Result: /private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/43734fe6-827b-4456-8612-0540ddad69af/scratchpad/claudex/i20/claudex-642btu7e/result.json (assurance cross_provider)
```json
{
 "verdict": "REVISE",
 "summary": "Codex rename still has concrete failure-recovery defects, and the pinned assistant message remains incorrectly derived from aggregate output.",
 "findings": [
  {
   "id": "R20-01",
   "severity": "medium",
   "path": "runner/projects.py:1704",
   "evidence": "The database name is committed before _codex_store_child validates session_index.jsonl. If that index is an escaping symlink, validation raises outside the rollback block. The route returns 400, but threads.name has already changed, violating Part A's unchanged-on-failure guarantee.",
   "fix": "Validate all mutation targets before committing the database change, and include subsequent preparation failures in coordinated rollback. Add a confinement case asserting both name stores remain unchanged."
  },
  {
   "id": "R20-02",
   "severity": "medium",
   "path": "runner/projects.py:1715",
   "evidence": "The corrective index append still requires another successful write after the original append fails. With persistent ENOSPC, _append_line can leave a partial record, its newline repair can fail, and the corrective append also fails silently. Database rollback can likewise fail. The operation then reports failure while leaving corruption or inconsistent names. The new test simulates a one-time failure followed by successful recovery, so it does not establish the claimed guarantee.",
   "fix": "Use a coordinated recovery protocol that preserves the previous name without depending on additional space after ENOSPC. Retain recoverable operation state and surface failed compensation explicitly. Cover persistent write failure and concurrent index writers."
  },
  {
   "id": "R20-03",
   "severity": "medium",
   "path": "runner/app.py:3461",
   "evidence": "_assistant_text still returns the entire recorded output. Codex parsing now separates messages with blank lines but continues aggregating them, so messages 'Shall I start?' followed by 'Done.' are both returned as last_message and can both remain pinned. waiting_question additionally treats the last paragraph as the last message, losing actual message boundaries. The latest test checks aggregation and badge detection, but not the pinned-message requirement.",
   "fix": "Extract and persist the actual final assistant message separately from aggregate output. Use that field for pinning and waiting detection, preserving paragraph boundaries within the message."
  }
 ],
 "coverage": [
  "Verified the plan digest, all 20 manifest file hashes, and the tracked-diff digest.",
  "Reviewed all manifest changes, every added test file, affected existing test code, and review-log dispositions.",
  "Traced session mutations, live-session admission, PTY ownership, policy enforcement, finalization, and closure audits.",
  "Traced project labels through creation, synchronization, local backups, dispatch, and lock handoff.",
  "Inspected process-engine callers, cancellation, stalls, timeouts, streaming, replay, history, terminal callbacks, project selection, file browsing, and Run tests wording.",
  "Followed related readers and writers in state_io.py, run_skill.py, dsh_cli.py, stall_detection, usage_reader.py, reset_gen.py, and relocation admission."
 ],
 "limitations": [
  "Static inspection only: no edits, tests, delegation, browser operations, or native CLI operations.",
  "Historical test-pass and manual-validation claims were not independently verified.",
  "Native picker behavior and live Linear API semantics were not exercised.",
  "SPEC.md and broader architecture documents were not inspected; fidelity was assessed against the supplied plan and implementation contracts."
 ]
}
```

### Dispositions (host Claude) — inspection budget exhausted
- R20-01 fixed (UNREVIEWED edit): the session index path is validated before the database name is changed. Test `test_escaping_index_refuses_before_the_database_changes`.
- R20-03 fixed (UNREVIEWED edit): for Codex runs, the pinned message and "Waiting" use the last `agent_message` read from the run's stream log (paragraphs inside it kept); `waiting_question` again takes a single message. Test `test_codex_last_message_comes_from_the_stream_log`.
- R20-02 NOT fixed — accepted risk, left for the user: with a disk that stays full during a Codex rename, the corrective index entry and the database rollback can both fail, leaving an inconsistent name (the route still reports the failure). Fully atomic recovery would need a write-ahead journal or Codex's own rename API; not worth it for a local, single-user dashboard.
- Proof after these edits: 575 passed. These last edits (R20-01, R20-03) have no independent inspection.

## Final status (2026-10-16)
- Plan review: APPROVED (Codex, round 5, cross_provider).
- Build: Claude. Base 995924c. Inspections: 20 rounds (15 cross_provider Codex completed, 3 Codex provider_unavailable with Claude degraded fallbacks 4b/5b/6c/16b, 1 fallback that failed on Claude quota). Never reached a clean cross-provider inspection: each round found 2–5 new medium edge cases, trending to narrower failure-injection and race scenarios; 0 high findings since inspection 9.
- Open: R20-02 (accepted risk); unreviewed edits R20-01/R20-03; plan items 23/24/25/74 (native pickers not opened), 125 (live Linear label), 268 (clean cross-provider inspection).

## Extension (user, 2026-10-16): "再跑最多5轮，解决剩下的问题" — up to 5 more inspection rounds (21–25)
- R20-02 now fixed instead of accepted: a Codex rename writes a recovery journal (~/.agentic-os/codex-rename-journal.json, outside the Codex store) before either store changes; a failed journal write changes nothing; if the rename's rollback cannot finish, the route reports it and the journal entry is completed the next time a Codex session is resolved for rename/remove (`recover_codex_renames`). Tests `test_rename_with_a_persistently_full_disk_is_recovered_later`, `test_a_journal_write_failure_changes_nothing`.
- Proof: 577 passed. Inspection 21 covers R20-01/R20-03 (previously unreviewed) and this change.

## Inspection 21 (fresh Codex, extension 1/5) — REVISE (2 medium)
- Result: /private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/43734fe6-827b-4456-8612-0540ddad69af/scratchpad/claudex/i21/claudex-08jy7z7c/result.json (assurance cross_provider)
```json
{
 "verdict": "REVISE",
 "summary": "Material defects remain in Codex rename recovery and quota reporting after session removal.",
 "findings": [
  {
   "id": "R21-01",
   "severity": "medium",
   "path": "runner/projects.py:1763",
   "evidence": "Recovery treats every journal entry as an abandoned rename, although entries also represent operations currently executing. Session locks are per session, and _journal_lock protects only journal updates. Rename A can commit its database name, then a concurrent rename/remove of B calls session_target → recover_codex_renames, restores A's old name and clears A's journal. A then appends its requested index title and returns success. The database and index disagree despite both requests succeeding. Recovery also bypasses A's session admission lock and live-session check.",
   "fix": "Serialize rename transactions and recovery at store scope, distinguish active operations from recoverable failures, and apply session admission checks before recovery writes. Add a concurrency check covering B resolving while A is between its database update and index append."
  },
  {
   "id": "R21-02",
   "severity": "medium",
   "path": "runner/usage_reader.py:629",
   "evidence": "remove_session now relocates Codex rollouts into archived_sessions, but load_latest_codex_rate_limits still scans only sessions. Without a fresh rate-limits-live.json, removing the session containing the newest quota snapshot makes compute_windows use an older snapshot from another session. For example, displayed weekly usage can drop from 80% to 20%, or an exhaustion signal can disappear. Adding archives to _codex_window_range does not fix this separate reader; compute_windows preferentially uses server snapshot percentages.",
   "fix": "Include archived rollouts in quota-snapshot and limit-hit discovery, preferably through a shared rollout iterator. Verify that removing and restoring the session containing the newest snapshot preserves the displayed quota."
  }
 ],
 "coverage": [
  "Verified the supplied plan digest, all 20 manifest file hashes, and the tracked-diff digest.",
  "Reviewed the plan, review-log evidence, changed implementation hunks, added test sources, and affected existing test changes.",
  "Traced session resolution, rename/remove, recovery journaling, freshness checks, session claims, and PTY ownership.",
  "Traced project labels through creation, synchronization, backups, dispatch, and lock handoff.",
  "Inspected process-engine callers, streaming, interruption records, replay, history, terminal callbacks, project selection, file browsing, and Run tests wording.",
  "Followed related state readers and writers in state_io.py, run_skill.py, stall detection, tracker polling, and usage aggregation."
 ],
 "limitations": [
  "Static inspection only: no files edited, tests executed, browser/native CLI operations performed, or work delegated.",
  "Historical test-pass claims, native resume-picker behavior, and live Linear API semantics were not independently verified.",
  "SPEC.md and broader architecture documents were not inspected; fidelity was assessed against the supplied plan and inspected implementation contracts."
 ]
}
```

### Dispositions (host Claude; both fixed)
- R21-01 fixed: `CODEX_STORE_LOCK` (store-scope RLock) serializes dashboard Codex renames, archives and recovery, so any journal entry recovery sees is abandoned, never in flight; recovery also skips a session whose admission lock is held. Test `test_recovery_never_undoes_a_rename_still_in_flight`.
- R21-02 fixed: one `_codex_rollouts()` iterator (live + archived) feeds both the quota-snapshot reader and the token window. Test `test_codex_rollouts_include_archived_ones`.
- Proof: 579 passed.

## Inspection 22 (fresh Codex, extension 2/5) — REVISE (2 medium)
- Result: /private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/43734fe6-827b-4456-8612-0540ddad69af/scratchpad/claudex/i22/claudex-s002of3y/result.json (assurance cross_provider)
```json
{
 "verdict": "REVISE",
 "summary": "Two material defects remain in Codex rename recovery: pending rollback state can be overwritten, and recovery can mutate live sessions.",
 "findings": [
  {
   "id": "REC-01",
   "severity": "medium",
   "path": "runner/projects.py:1783",
   "evidence": "The HTTP route holds session_lock before calling session_target (app.py:3742). Recovery therefore skips the requested session, including during _rename_codex's second recovery call. After a failed rename leaves database name N and a journal preserving original name O, retrying that same session reads N and overwrites the journal at line 1714. If this retry encounters a SQLite timeout, line 1718 clears the journal, permanently losing recovery to O. The recovery test calls session_target without the route's lock and misses this behavior.",
   "fix": "Recover the requested session under the admission lock already owned by the caller. Refuse further mutation until its pending rollback completes, and never overwrite an unresolved journal entry. Cover recovery through the actual rename/remove routes."
  },
  {
   "id": "REC-02",
   "severity": "medium",
   "path": "runner/projects.py:1788",
   "evidence": "Recovery acquires an admission lock but never checks running jobs, session claims, open terminals, or rollout freshness before writing both name stores. These admission locks are released after launch/opening; they are not held throughout execution. Thus, after session A has an unfinished rename journal and is resumed, a rename/remove request for session B can trigger recovery that changes A while it is live. The route's later check_session_idle only checks B. This violates Part A's live-session exclusion.",
   "fix": "Before recovering each session, validate its target and apply the same live-session and freshness checks under its admission lock. Leave busy sessions journaled for a later recovery pass."
  }
 ],
 "coverage": [
  "Verified the plan SHA256, all 20 manifest file hashes, and the tracked-diff digest.",
  "Reviewed the supplied plan, review log, implementation changes, added test sources, and affected existing test code.",
  "Traced session resolution, mutations, recovery journaling, admission claims, PTY ownership, and closure audits.",
  "Traced project labels through creation, synchronization, local backups, dispatch, and lock handoff.",
  "Inspected process-engine callers, interruption records, streaming, replay, history, terminal UI, project selection, file browsing, and Run tests wording.",
  "Followed related readers and writers in state_io.py, run_skill.py, stall detection, tracker polling, reset generations, and usage aggregation."
 ],
 "limitations": [
  "Static inspection only: no files edited, tests executed, browser/native CLI operations performed, or work delegated.",
  "Historical validation claims, native resume-picker behavior, and live Linear API behavior were not independently verified.",
  "SPEC.md and broader architecture documents were not inspected; fidelity was assessed against the supplied plan and implementation contracts."
 ]
}
```

### Dispositions (host Claude; both fixed by simplifying the design)
- REC-01/REC-02 fixed: cross-session recovery is gone. A journaled rollback is settled only by the next rename or remove of that same session, inside its own request (admission lock held, idle check passed) and under the store lock, before anything new is written; if it still cannot complete, the new change is refused and the journal entry is kept (never overwritten). Other sessions' journal entries are never touched. Tests (through the real route): `test_rename_with_a_persistently_full_disk_is_recovered_later`, `test_a_pending_rollback_of_one_session_is_never_touched_by_another`, `test_codex_mutations_of_two_sessions_never_interleave`.
- Proof: 580 passed.

## Inspection 23 (fresh Codex, extension 3/5) — REVISE (3 medium)
- Result: /private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/43734fe6-827b-4456-8612-0540ddad69af/scratchpad/claudex/i23/claudex-xr_tvcdb/result.json (assurance cross_provider)
```json
{
 "verdict": "REVISE",
 "summary": "Material defects remain in older-card terminal access, quota reporting after removal, and shared Codex index recovery.",
 "findings": [
  {
   "id": "REV23-01",
   "severity": "medium",
   "path": "runner/templates/index.html:2669",
   "evidence": "The board resolves recorded sessions only from running jobs and the newest 80 runs. Once a card's last execution falls outside that window, latest_run_id becomes empty, its Terminal action disappears, and its virtual detail view hides the Terminal tab at line 2894—even though /history and the durable stream log still contain its session. This violates C's requirement for every card with a recorded session.",
   "fix": "Resolve the latest execution per visible issue independently of the global recent-run limit, or load issue history before deciding that a card has no terminal."
  },
  {
   "id": "REV23-02",
   "severity": "medium",
   "path": "runner/scripts/codex_snap_rate_limits.py:41",
   "evidence": "The snapshot writer still scans only sessions/, while removal now moves rollouts into archived_sessions/. Suppose an archived session holds an 80% snapshot and a remaining session holds a 20% snapshot from ten minutes earlier. With no current live snapshot file, the dashboard correctly discovers 80% through the updated reader. Invoking this supported snapshot script then writes the older 20% snapshot; usage_reader.py:619 accepts it immediately because it is under 30 minutes old, masking the newer archived snapshot.",
   "fix": "Include archived rollouts in the snapshot writer through the shared rollout iterator. Ensure a live-file snapshot cannot supersede a newer discovered snapshot, and verify removal preserves quota reporting through both writer and reader."
  },
  {
   "id": "REV23-03",
   "severity": "medium",
   "path": "runner/projects.py:1796",
   "evidence": "The rename journal restores names but does not repair partial shared-index records. A short append followed by ENOSPC leaves malformed JSON permanently; test_codex_index_partial_write_is_closed_and_healed explicitly expects the fragment to remain. Moreover, completing the append through multiple os.write calls allows a native Codex writer to append another session's record between fragments. That unrelated record can become part of an invalid line. CODEX_STORE_LOCK excludes dashboard threads only, and the journal contains no information to recover that lost entry.",
   "fix": "Use an index mutation mechanism coordinated with native writers that preserves complete records and unrelated appends. Retain sufficient recovery state until index integrity is restored; verify partial-write recovery and concurrent native appends instead of accepting retained corruption."
  }
 ],
 "coverage": [
  "Verified the supplied plan SHA256, all 20 manifest file hashes, and the tracked-diff digest.",
  "Reviewed the plan, review-log evidence, every manifest file's changes, added test sources, and relevant surrounding implementation.",
  "Traced session mutations, recovery journaling, live-session exclusion, PTY ownership, locking, finalization, and closure audits.",
  "Traced project labels through creation, synchronization, backups, dispatch, and lock handoff.",
  "Inspected process-engine callers, interruption records, streaming, replay, history, terminal callbacks, project selection, file browsing, and Run tests wording.",
  "Followed related readers and writers beyond the manifest, including state_io.py, run_skill.py, stall detection, relocation admission, and codex_snap_rate_limits.py."
 ],
 "limitations": [
  "Static inspection only: no edits, tests, delegation, browser operations, or native CLI operations.",
  "Historical test-pass claims and manual-validation claims were not independently verified.",
  "Native picker behavior and live Linear API semantics were not exercised.",
  "SPEC.md and broader architecture documents were not inspected; fidelity was assessed against the supplied plan and implementation contracts."
 ]
}
```

### Dispositions (host Claude)
- REV23-01 fixed: `/api/runs/latest-by-issue` returns every issue's newest execution (audits excluded), and the board falls back to it beyond the 80-run window, so a card keeps its Terminal action. Test `test_latest_run_per_issue_beyond_the_recent_window`.
- REV23-02 fixed: `scripts/codex_snap_rate_limits.py` scans archived rollouts too, so writer and reader see the same newest snapshot. Test `test_snapshot_script_reads_archived_rollouts`.
- REV23-03 partly fixed, residual stated: each index record now goes out in exactly one O_APPEND write (never continued), so no other writer — Codex itself included — can land inside it. Residual (accepted, user decision): a single short write on a full disk leaves one newline-terminated bad line for readers to skip; removing it would mean rewriting a file Codex appends to concurrently. Test `test_index_record_is_one_write`.
- Proof: 583 passed.

## Inspection 24 (fresh Codex, extension 4/5) — REVISE (2 medium)
- Result: /private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/43734fe6-827b-4456-8612-0540ddad69af/scratchpad/claudex/i24/claudex-_v14uul8/result.json (assurance cross_provider)
```json
{
 "verdict": "REVISE",
 "summary": "Two material defects remain: shared Codex index recovery can corrupt unrelated entries, and network failures strand new UI workflows.",
 "findings": [
  {
   "id": "R24-01",
   "severity": "medium",
   "path": "runner/projects.py:1796",
   "evidence": "A short os.write leaves an unterminated fragment before the separate repair-newline write at line 1817. A native Codex writer can append another session's complete entry between those writes, merging it with the fragment into invalid JSON. CODEX_STORE_LOCK excludes only dashboard threads, and the journal preserves only the renamed session's old title. Thus the remaining risk exceeds the documented single bad line: an unrelated native entry can become unreadable and cannot be recovered by the journal.",
   "fix": "Coordinate the complete append and recovery operation with native writers, retaining sufficient recovery information to preserve unrelated entries. If native coordination is unavailable, avoid direct shared-index mutation rather than claiming unchanged-on-failure behavior. Cover a native append between a short write and newline repair."
  },
  {
   "id": "R24-02",
   "severity": "medium",
   "path": "runner/templates/index.html:1265",
   "evidence": "_projectApi lets fetch rejections escape, but its new callers do not recover them. If the connection drops during a root tree request, _filesLoad never clears st.loading or records an error; subsequent renders refuse another load and offer no Retry button. During interactive completion, _cardTermNext hides the choices and clears endedRunId before awaiting this helper, then installs only a success callback. A rejected request leaves 'saving…' and removes the completion choices without confirming the transition.",
   "fix": "Convert transport failures into structured error results, clear loading state in finally, and restore completion choices with their owning run when saving fails. Verify recovery after a rejected tree fetch and a rejected completion fetch."
  }
 ],
 "coverage": [
  "Verified the supplied plan SHA256 and all 21 manifest file hashes against disk.",
  "Reviewed the plan, review-log evidence, implementation changes, every newly added test file, and affected existing test hunks.",
  "Traced session mutations, rename journaling, admission claims, PTY ownership, confidentiality policy, finalization, and closure audits.",
  "Traced project labels through creation, synchronization, backups, dispatch, and lock handoff.",
  "Inspected process-engine callers, interruption records, streaming, replay, history, terminal callbacks, project selection, file browsing, and Run tests wording.",
  "Followed related readers and writers beyond the original plan list, including state_io.py, run_skill.py, stall detection, reset generations, and quota snapshot aggregation."
 ],
 "limitations": [
  "Static inspection only: no edits, tests, delegation, browser operations, or native CLI operations.",
  "Historical validation claims, native resume-picker behavior, and live Linear API semantics were not independently verified.",
  "SPEC.md and broader architecture documents were not inspected; fidelity was assessed against the supplied plan and inspected implementation contracts."
 ]
}
```

### Dispositions (host Claude; both fixed)
- R24-01 fixed by deletion, as the inspector's fallback recommends: the dashboard no longer writes Codex's shared `session_index.jsonl` at all (Codex appends to it concurrently and offers no coordination). A Codex rename is again one `threads.name` transaction — whole or nothing — so the rename journal, its recovery, and the shared-append helper are removed (and their tests). Consequence for the user: whether `codex resume` shows a dashboard rename depends on Codex reading `threads.name`; the native picker was never opened (item 74 stays open). Codex remove still mirrors the native archive (rollout → archived_sessions, row archived with its path).
- R24-02 fixed: `_projectApi` turns a dropped connection into an error result (`status: 0`), so the file tree clears its loading state and offers Retry, and the next-state choice comes back with an error instead of hanging on "saving…".
- Proof: 574 passed (9 tests removed with the deleted mechanism).

## Inspection 25 (Codex, extension 5/5) — FAILED: provider unavailable (usage limit until 11:07)
- Result: /private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/43734fe6-827b-4456-8612-0540ddad69af/scratchpad/claudex/i25/claudex-yywt63c1/result.json

## Inspection 25b (fresh Claude, degraded fallback) — REVISE (1 medium)
- Result: /private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/43734fe6-827b-4456-8612-0540ddad69af/scratchpad/claudex/i25b/claudex-rsi59evu/result.json (assurance degraded_same_provider)
```json
{
 "verdict": "REVISE",
 "summary": "One medium defect remains. When a Linear runner-root dispatch times out or errors, the worker-owned record is written without `task_id`. Retry and quick reply look up the session by `task_id`, so the session id that REV-02 was meant to preserve is never found. The card offers \"Open interactive\", yet strict quick reply returns 409 \"no resumable session\", and an ordinary retry starts a fresh session instead of resuming. These areas held up when traced: the session rename/remove paths after the R24 simplification, lock reservation and hand-off (PATCH → dispatch, retry → project helper), the run-bound resume in open_terminal, history and attempt resolution, and project-label handling. This is a same-provider fallback review, so it is not independent of the builder.",
 "findings": [
  {
   "id": "FB5-01",
   "severity": "medium",
   "path": "runner/modules/linear/__init__.py:896",
   "evidence": "In `_dispatch_issue_held`, the success record (line 881) and the cancel/stall job record (line 839, `\"task_id\": run_id`) both carry `task_id`. The worker-owned timeout record (lines 896-897) and error record (lines 906-907) carry only `linear_issue_id, agent, reset_generation, agent_session_id=end.session`, with no `task_id` and no `model`. `api_run_retry` sets `task_id = original.get(\"task_id\") or run_id` (app.py:4082) and calls `_get_task_agent_lock(task_id)`, which keeps only records where `r.get(\"task_id\") == task_id` (app.py:2646). A record without `task_id` never matches, so `_lock_session_id` stays None. Scenario: a Linear Claude/Codex dispatch at the runner root streams, announces its session (`_publish_run_line` sets the job's agent_session_id), then hits AI_RUN_TIMEOUT_S. `/events` reports agent_session_id and `resume_eligible`, so the card shows \"Open interactive\". Quick reply (`strict: true`) returns 409 \"no resumable session for this card\" (app.py:4135). A normal Retry builds a fresh `_ai_command` instead of `_build_resume_cmd` and is not agent-locked. The REV-02 disposition (\"every worker-owned timeout/error record … carries it\") is therefore not effective on this path. The /run agent path does add `task_id=run_id` to its timeout/error records (app.py:3435/3444), and the retry path inherits it through its arguments, so only Linear dispatch is affected.",
   "fix": "Add `task_id=run_id` (and `model=pm or _agent_model(backend, cfg)` for parity) to both the timeout and the error `_write_run_log_retrying` calls in `_dispatch_issue_held`. Add a test in which a Linear runner-root dispatch times out after announcing a session, then a strict quick reply on that run returns 200 and builds the resume command."
  }
 ],
 "coverage": [
  "Read the full plan and the review-log dispositions through inspection 24, and the full tracked diff of runner/app.py, linear_client.py, modules/linear/__init__.py, local_tracker.py, modules/pty/__init__.py, project_runs.py, projects.py, reset_gen.py, usage_reader.py, codex_snap_rate_limits.py and templates/index.html",
  "Read the current app.py retry route (record lookup, unsynced guard, strict checks, session claim, card/ticket lock reservation and `_start_failed` release), `_get_task_agent_lock`, the job records of the /run entrypoint/agent paths and of retry, and api_run_history including the running-attempt merge and the dashboard root-task branch",
  "Read the current Linear `_dispatch_issue_held`: project ticket identity check and `pop_all` hand-off, the runner-root card_lock held through the run, and the success/timeout/error record fields",
  "Read the current PTY open_terminal (run-bound resume via card_run_for_session/_latest_record, project/ticket/card locks, session_lock admission, live-session refusal) and close_terminal/_finalize",
  "Read `_run_project_ticket`/`_run_project_ticket_locked` (ticket_hold nullcontext, project_lock order, durable log and meta sidecar, stderr sink) and confirmed `_records_unsafe` covers OUTPUTS_DIR, where the stream logs live",
  "Checked the board JS: virtual `linear-` cards redirect to latest_run_id, the olderLatest fallback, and the card-terminal attempt/latest logic",
  "Checked usage_reader consumers of the trash and archived rollouts, and Codex rename/archive after the R24 change (single threads.name transaction, archived_sessions confinement)"
 ],
 "limitations": [
  "DEGRADED_SAME_PROVIDER: same-provider fallback reviewer (shares the builder's provider); not an independent cross-provider inspection",
  "Static inspection only: no tests, browser, PTY, native claude/codex picker or live Linear checks. The claimed 574 passing tests were not verified",
  "The new test files were not read in full; SPEC/architecture documents were not inspected",
  "Whether `codex resume` shows threads.name (now the only name the dashboard writes) could not be verified; the plan keeps that acceptance item PARTIAL",
  "DEGRADED_SAME_PROVIDER: preferred reviewer was unavailable; claude reviewed in a fresh fallback session without cross-provider independence.",
  "DEGRADED_SAME_PROVIDER: preferred reviewer codex was unavailable; claude reviewed in a fresh fallback session without cross-provider independence."
 ]
}
```

### Disposition (host Claude; fixed)
- FB5-01 fixed: Linear dispatch timeout/error records carry `task_id` (and `model`), so retry and quick reply find the session the run announced. Test `test_timed_out_linear_dispatch_stays_resumable` (strict quick reply after a timed-out dispatch resumes `--resume <session>`).
- Proof: 575 passed.

## DeepSeek third-party inspection (user, 2026-10-16: "codex 没有usage的时候，审阅用deepseek") — APPROVED (0 findings)
- Reviewer: DeepSeek via `dsh --profile headless` 0.2.0-rc.2 with `DSH_PERMISSION_MODE=read-only` (sandboxed read-only); same scope as the Codex inspections (plan, review log, `git diff 995924c`, every new file). Artifacts: scratchpad claudex/ds1 (prompt, reply, stderr).
- Checkout fingerprint (diff + status + untracked contents) identical before and after: the reviewer wrote nothing.
- It covered the code including the FB5-01 fix and the R24-01/R24-02 edits.
- Assurance: third-party, not a claudex `cross_provider` approval (the runner drives only Claude/Codex; a third-party reviewer never replaces its approval). It lowers, not removes, the open item "Fresh cross-provider (Codex) build inspection returns no unresolved material findings".
- Its notes flagged one wording inaccuracy (not a code defect): the Codex remove confirmation said "restore by un-archiving" although the rollout also moves. Fixed in index.html (text only, after the DeepSeek pass).

## Status after the extension (2026-10-16)
- 25 inspection rounds used (20 + 5 extension). Last Codex inspection with a verdict: 24 (2 medium, fixed). Fixes after it: R24-01/R24-02, FB5-01, the confirm text — reviewed by Claude fallback 25b (FB5-01 found, fixed) and by DeepSeek (APPROVED), not by Codex.
- Open: one Codex cross-provider inspection of the final state (Codex quota returns 11:07); plan items 23/24/25/74 (native pickers), 125 (live Linear label).

## Inspection 26 (fresh Codex, on commit 56244cd) — REVISE (2 medium)
- Result: /private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/43734fe6-827b-4456-8612-0540ddad69af/scratchpad/claudex/i26/claudex-i527h8rt/result.json (assurance cross_provider)
```json
{
 "verdict": "REVISE",
 "summary": "Two concrete defects remain in stderr activity handling and durable terminal replay.",
 "findings": [
  {
   "id": "FINAL-01",
   "severity": "medium",
   "path": "runner/app.py:804",
   "evidence": "_StderrSink publishes live stderr lines without refreshing last_progress_at. Only stdout publication refreshes that timestamp. A command reporting progress on stderr while stdout remains quiet for five minutes is therefore killed by stall_detection.check_once, despite continuing to produce visible activity and having a default process deadline of 30 minutes. Project stderr also bypasses the heartbeat-updating _emit callback.",
   "fix": "Refresh the running job's heartbeat when stderr activity arrives, independently of display truncation limits. Apply the same behavior to project runs and cover stderr-only activity against the stall check."
  },
  {
   "id": "FINAL-02",
   "severity": "medium",
   "path": "runner/app.py:3494",
   "evidence": "Live stdout and stderr share the event ring's sequence, but durable storage retains stdout separately from an unsequenced stderr tail. _replay_lines renders all stdout first and appends stderr afterward. Consequently, a live sequence of 'starting', stderr 'temporary failure', then 'recovered' replays as 'starting', 'recovered', 'temporary failure'. This occurs below every truncation limit and also places failed-resume diagnostics after successful fallback output, contradicting Part C's replay-consistency requirement.",
   "fix": "Persist a combined ordered event stream, or retain ordering metadata sufficient to merge stdout and stderr during replay. Preserve the existing raw stdout contract separately and verify interleaved output and fallback replay."
  }
 ],
 "coverage": [
  "Verified the plan digest, all 21 manifest file hashes, and the tracked-diff digest.",
  "Reviewed every manifest file's changes, all added test sources, and relevant surrounding implementation.",
  "Traced session mutations, confinement, live-session checks, PTY ownership, locks, finalization, and closure audits.",
  "Traced project labels through creation, synchronization, local backups, dispatch, and lock handoff.",
  "Traced process-engine callers, retry/fallback, interruption records, streaming, replay, history, and terminal callbacks.",
  "Inspected project selection, file browsing, Run tests wording, and related state callers in state_io.py, run_skill.py, dsh_cli.py, and stall_detection."
 ],
 "limitations": [
  "Static inspection only: no edits, tests, delegation, browser operations, or native CLI operations.",
  "Historical test-pass and manual-validation claims were not independently verified.",
  "Native resume-picker behavior and live Linear API semantics remain unverified.",
  "SPEC.md and broader architecture documents were not inspected; fidelity was assessed against the supplied plan and inspected implementation contracts."
 ]
}
```

### Dispositions (host Claude; both fixed)
- FINAL-01 fixed: every stderr line (engine and project runs, before any display cap) refreshes the job's `last_progress_at`. Test `test_stderr_activity_is_progress`.
- FINAL-02 fixed: each kept stderr line records the stdout log's size when it arrived; replay merges stderr back at that position (older plain-string entries go last). Test `test_replay_keeps_stdout_and_stderr_in_their_live_order`.
- Proof: 577 passed.

## Inspection 27 (fresh Codex, on commit 5591172) — REVISE (2 medium)
- Result: /private/tmp/claude-501/-Users-yanghu-Documents-AI-Workspace-agentic-os/43734fe6-827b-4456-8612-0540ddad69af/scratchpad/claudex/i27/claudex-8dwyyqf8/result.json (assurance cross_provider)
```json
{
 "verdict": "REVISE",
 "summary": "Two material defects remain in stderr heartbeat handling and live/replay ordering.",
 "findings": [
  {
   "id": "UI27-01",
   "severity": "medium",
   "path": "runner/app.py:798",
   "evidence": "_StderrSink.feed refreshes last_progress_at only after receiving a newline and invoking _line. A scheduled command emitting periodic carriage-return progress on stderr, with quiet stdout for over 300 seconds, is therefore killed by stall_detection.check_once despite continuing activity. The project reader also waits for newline-delimited stderr before calling the sink (project_runs.py:393). The new heartbeat test covers newline-terminated output only.",
   "fix": "Refresh the heartbeat when nonempty stderr chunks arrive, independently of line completion and display limits. Drain project stderr in chunks too. Cover ongoing stderr activity without newlines across the stall threshold."
  },
  {
   "id": "UI27-02",
   "severity": "medium",
   "path": "runner/app.py:813",
   "evidence": "Sampling stdout file size does not establish the live event order. A stdout reader can flush record A at app.py:2470 and be paused before publishing it. The stderr thread then records the position after A and publishes error E first. The live ring contains E,A, but _replay_lines reconstructs A,E. The same gap exists in text, DSH and project readers. This occurs below truncation limits; the new replay test's sleeps avoid this interleaving.",
   "fix": "Serialize stdout persistence/publication and stderr position capture/publication through one per-run ordering mechanism, or persist a combined sequenced event stream while retaining raw stdout separately. Verify ordering when stderr publication occurs between a stdout flush and its live publication."
  }
 ],
 "coverage": [
  "Verified the plan SHA256, all 21 manifest file hashes, and the tracked-diff SHA256 against disk.",
  "Reviewed the supplied plan, review log, complete diff, all added test sources, and affected existing test changes.",
  "Traced session mutations, confinement, freshness checks, admission claims, PTY ownership, locks, finalization and closure audits.",
  "Traced project labels through creation, normalization, synchronization, backups, dispatch and lock handoff.",
  "Traced process-engine callers, retry/fallback, interruption records, streaming, replay, history and terminal callbacks.",
  "Inspected project selection, file browsing, Run tests wording, and related state callers in state_io.py, run_skill.py, dsh_cli.py and stall_detection."
 ],
 "limitations": [
  "Static inspection only: no edits, tests, delegation, browser operations or native CLI operations.",
  "Historical test-pass and manual-validation claims were not independently verified.",
  "Native resume-picker behavior and live Linear API semantics remain unverified.",
  "SPEC.md and broader architecture documents were not inspected; fidelity was assessed against the supplied plan and inspected implementation contracts."
 ]
}
```

### Dispositions (host Claude; both fixed)
- UI27-01 fixed: any non-empty stderr chunk refreshes the heartbeat, newline or not; project runs drain stderr in chunks (`read1`). Test `test_stderr_without_newlines_is_progress`.
- UI27-02 fixed: a per-run order lock (`project_runs.order_lock`) covers a stdout line's log write and its publication, and a stderr line's position capture and publication, on every reader (claude, text, dsh, project). Test `test_stderr_cannot_slip_between_a_stdout_write_and_its_publication`.
- Proof: 579 passed.
