# Review log — 2026-10-21-claude-account-swap

- Host/coordinator: Claude Code (Opus 5.5). Plan reviewer: Codex (CLI default model). Builder: Claude (host). Final inspector: fresh Codex session.
- Scope: AGE-125 swap Claude login. Authorization: runner-dispatched ticket, "commit your work on this branch" → plan + build + commit authorized; no push.
- Rounds: MAX_ROUNDS 20, MAX_FIX_ROUNDS 20, MAX_INSPECTION_ROUNDS 20. Fallback: same-provider-on-unavailable. Inspection: on.
- Budget: headless run, no live interview. Small plan (~1 module + 2 endpoints + 1 select); expect 1–3 review rounds and 1–2 inspections on a small diff. Recorded as default, no lower-effort override.
- Phase 1 note: user unavailable for interview (headless dispatch); routine reversible choices resolved by host and recorded in the plan's Findings/Options.

## Plan review round 1

Result: `/tmp/age125-art/r1/claudex-nrhegm02/result.json` (diagnostics outside checkout)

```json
{
 "status": "completed",
 "assurance": "cross_provider",
 "cli": "codex-cli 0.163.0",
 "session": "01a1611a-ec78-73d1-b8f2-61bbff4a2a70",
 "plan_sha256": "9c53ff4a489e0db83011dd8c99bf2cd924f3b8a9dbd7b708a32aff8125221cdc",
 "response": {
  "verdict": "REVISE",
  "summary": "The plan needs changes to prevent mismatched account credentials, preserve recoverability, and ensure quota cards reflect the selected account. The inspected plan matches the supplied SHA256. This was a static plan review; no tests were run.",
  "findings": [
   {
    "id": "CAS-01",
    "severity": "high",
    "path": "docs/exec-plans/active/2026-10-21-claude-account-swap.md:49",
    "evidence": "The save/use sequence has no cross-process serialization. Concurrent dashboard and CLI swaps can interleave: use B writes B's credentials, use C writes C's credentials and identity, then use B writes B's identity. The result authenticates as C while reporting B. A concurrent save can permanently snapshot that mismatched pair. Atomic replacement of the JSON file does not protect this multi-resource operation.",
    "fix": "Require one machine-wide lock shared by CLI and dashboard operations, covering live reads, outgoing snapshot updates, target installation, and identity replacement. Ensure list observes a consistent pair. Add deterministic interleaving checks."
   },
   {
    "id": "CAS-02",
    "severity": "high",
    "path": "docs/exec-plans/active/2026-10-21-claude-account-swap.md:55",
    "evidence": "The plan writes the target keychain credentials before replacing ~/.claude.json, without specifying rollback. If temporary-file creation or os.replace fails, credentials become B while oauthAccount remains A. The next use then identifies A as outgoing and overwrites A's saved snapshot with B's credentials.",
    "fix": "Validate the target and prepare the identity update before mutation. Specify rollback and interrupted-operation recovery for the two-resource transition. Refuse outgoing snapshot updates while consistency is unresolved, and verify failures at each write boundary."
   },
   {
    "id": "CAS-03",
    "severity": "high",
    "path": "docs/exec-plans/active/2026-10-21-claude-account-swap.md:85",
    "evidence": "The stated recovery contradicts the same-label no-op at line 58. In the plan's own scenario, an old A process restores A's credentials while oauthAccount still says B. Re-running use B after that process exits returns success without restoring B. Switching elsewhere can also re-save A's credentials into B's snapshot because outgoing ownership is inferred solely from oauthAccount.",
    "fix": "Provide a repair operation that bypasses the same-label shortcut and never overwrites a saved snapshot from an unverified credential/identity pair. Require authoritative ownership validation before outgoing re-save, or refuse unsafe swaps while credential-writing processes remain active. Document a recovery procedure that actually restores consistency."
   },
   {
    "id": "CAS-04",
    "severity": "medium",
    "path": "docs/exec-plans/active/2026-10-21-claude-account-swap.md:64",
    "evidence": "Resetting the cache variables without coordinating with _claude_usage_lock can be undone by an in-flight request. runner/app.py:1208 holds that lock while fetching and subsequently publishing usage. A request can fetch A, the swap can install B and clear the cache, and the old request can then publish A's response. Reload displays A's quotas for another cache interval.",
    "fix": "Specify cache invalidation under _claude_usage_lock after the swap, or use an account generation that prevents pre-swap fetches from publishing. Verify the in-flight-fetch interleaving."
   },
   {
    "id": "CAS-05",
    "severity": "medium",
    "path": "runner/app.py:1392",
    "evidence": "Clearing only the OAuth cache leaves another account-unaware quota source intact. If B's API request fails after switching, _load_claude_official_windows reads .claude/rate-limits-live.json and labels a recent snapshot live for up to 600 seconds. That snapshot can belong to A, including updates from an already-running A session. The plan's reload criterion can therefore show A's quotas under B.",
    "fix": "Make fallback snapshots account-aware and reject snapshots whose account does not match the selected login. Until provenance is available, show unavailable quota data after a swap rather than accepting an unidentified snapshot. Cover API failure immediately after switching."
   },
   {
    "id": "CAS-06",
    "severity": "medium",
    "path": "docs/exec-plans/active/2026-10-21-claude-account-swap.md:16",
    "evidence": "Fresh processes do not necessarily follow the default keychain login. _registry_exec_env copies the entire environment (runner/app.py:292), _project_exec_env applies project overrides, and PTY _shell_env does the same. With CLAUDE_CODE_OAUTH_TOKEN selecting A, installing B in the default keychain changes quota cards but leaves new runs on A—the plan itself identifies this variable as per-spawn account selection. runner/projects.py:1569 also explicitly supports CLAUDE_CONFIG_DIR.",
    "fix": "Define and enforce support for the default credential source. Detect conflicting token/config-directory overrides in inherited and project environments, and reject or clearly disable account switching for affected execution paths. Document these restrictions and verify the override cases."
   },
   {
    "id": "CAS-07",
    "severity": "low",
    "path": "docs/exec-plans/active/2026-10-21-claude-account-swap.md:45",
    "evidence": "Actionable work lacks individual '- [ ]' checkboxes: fallback documentation at line 35; save validation/storage, four ordered use steps, listing, secret transport, discovery selection/documentation, endpoint behavior, cache invalidation, and UI behavior at lines 49–70; process warnings and recovery instructions at lines 87–90. Acceptance and verification entries also bundle separate actions/assertions, including identity versus inference checks at lines 97–98, individual test cases at lines 108–113, and manual steps at lines 119–120. Progress entries similarly combine implementation, inspection/resolution, and documentation substeps at lines 124–131.",
    "fix": "Give every actionable substep, acceptance assertion, and verification check its own '- [ ]' item. Keep explanatory evidence as prose, and identify manual recovery or post-merge checks as separate follow-up checkboxes."
   }
  ],
  "coverage": [
   "Read the complete on-disk plan and verified SHA256 9c53ff4a489e0db83011dd8c99bf2cd924f3b8a9dbd7b708a32aff8125221cdc.",
   "Inspected request-token enforcement, index rendering, Claude dispatch environments, quota fetching/cache/fallback, and quota API callers in runner/app.py.",
   "Inspected dashboard request handling, Claude row rendering, and quota polling in runner/templates/index.html.",
   "Traced related execution and shared-state paths through runner/project_runs.py, runner/projects.py, runner/run_skill.py, runner/modules/pty/__init__.py, runner/modules/backends/claude.py, runner/usage_reader.py, and runner/state_io.py.",
   "Read existing request-security and Claude-usage-cache tests plus test isolation fixtures; inspected the local security manual for interactive input and password-update options.",
   "Confirmed a clean working tree and that the proposed account module and dedicated test file do not yet exist."
  ],
  "limitations": [
   "No files were edited, tests executed, application started, or work delegated.",
   "Reviewed proposed behavior against the plan's requirements and existing implementation; no account-switch implementation was available to inspect.",
   "Did not access live credentials, saved accounts, or personal Claude configuration, or perform keychain writes.",
   "Claude Code's external refresh/config-writing behavior was not independently verified. CAS-03 demonstrates a contradiction within the plan's explicitly acknowledged scenario.",
   "No statusline snapshot writer was found in the searched repository paths; the checkout's .claude directory is absent."
  ]
 }
}
```

Round 1 dispositions (host):
- CAS-01 accepted: machine-wide fcntl.flock shared by CLI and dashboard for the whole use operation; thread-interleaving test added.
- CAS-02 accepted via a different mechanism: ownership no longer depends on oauthAccount. Live owner = refresh-token match against saved snapshots, else /api/oauth/profile account.uuid (verified live); unknown → refuse. Target snapshot validated/parsed before any write. oauthAccount write failure is a warning only; it cannot corrupt a snapshot because it is never used for ownership. No rollback needed.
- CAS-03 accepted: same-label use now repairs (rewrites credentials + oauthAccount); outgoing re-save only into the authoritatively identified owner label.
- CAS-04 accepted: invalidation under _claude_usage_lock plus a generation counter; in-flight fetch publishes only if generation unchanged.
- CAS-05 accepted (bounded): rate-limits-live.json snapshot captured before last swap (index mtime) treated as unavailable. Post-swap writes by still-running old sessions accepted as residual risk, documented.
- CAS-06 accepted (bounded): use/save refuse when process env sets CLAUDE_CODE_OAUTH_TOKEN / ANTHROPIC_API_KEY / CLAUDE_CONFIG_DIR. Live launchd env checked: none set. Per-project env overrides declared unsupported (non-goal).
- CAS-07 accepted: approach moved to descriptive Design prose; every actionable step, acceptance assertion and test case is its own checkbox.

## Plan review round 2

Result: `/tmp/age125-art/r2/claudex-wo_eiah8/result.json` (diagnostics outside checkout)

```json
{
 "status": "completed",
 "assurance": "cross_provider",
 "cli": "codex-cli 0.163.0",
 "session": "01a1611a-ec78-73d1-b8f2-61bbff4a2a70",
 "plan_sha256": "0e68485443baf23e1785d5b44eda81e13eea120f76febaefdfc405545ff5d9ec",
 "response": {
  "verdict": "REVISE",
  "summary": "The revision addresses the original credential-ownership and dashboard cache-race scenarios. Remaining defects concern save serialization, snapshot identity consistency, and cache invalidation after CLI swaps. Actionable substeps also remain bundled. The plan hash matches the supplied SHA256.",
  "findings": [
   {
    "id": "CAS-08",
    "severity": "medium",
    "path": "docs/exec-plans/active/2026-10-21-claude-account-swap.md:65",
    "evidence": "The revised lock explicitly covers use, but save also writes snapshots and the shared label index. Two concurrent saves can read the same index, add different labels, and overwrite each other's updates, leaving a saved keychain item undiscoverable. Save can also observe credentials and oauthAccount on opposite sides of a concurrent use. The verification covers only use versus use.",
    "fix": "Require save to hold the same machine-wide lock throughout its live reads, profile lookup, snapshot write, and atomic index update. Add save/save and save/use interleaving checks. Outgoing saves called within use should use an internal helper without reacquiring the lock."
   },
   {
    "id": "CAS-09",
    "severity": "medium",
    "path": "docs/exec-plans/active/2026-10-21-claude-account-swap.md:64",
    "evidence": "Authoritative ownership protects credentials, but the saved oauthAccount can still belong to another account. For example, use B succeeds with the explicitly permitted oauthAccount-write warning, leaving A's metadata. A subsequent save b obtains B's uuid from the profile endpoint but snapshots A's oauthAccount. Later use b restores A's identity metadata, violating the target-email acceptance criterion. An external config writer can produce the same mismatch.",
    "fix": "Require saved oauthAccount identity to match the verified credential owner. Reject inconsistent metadata or reconstruct it from verified account data. When re-saving outgoing credentials, preserve previously validated identity metadata rather than copying unrelated live metadata. Add a save-after-identity-write-failure check."
   },
   {
    "id": "CAS-10",
    "severity": "medium",
    "path": "docs/exec-plans/active/2026-10-21-claude-account-swap.md:83",
    "evidence": "Usage-cache invalidation and generation changes occur only after a dashboard POST. A CLI use changes the keychain and index mtime without notifying the running dashboard. runner/app.py:1208 can continue returning A's cached API response after switching to B; if subsequent fetches fail, the existing retention policy keeps A's response for up to 15 minutes. The new index-mtime check applies only to fallback snapshots, so it does not reject this cached API response.",
    "fix": "Have the usage-cache reader observe a cross-process swap generation before returning cached data and before publishing a fetch. A changed generation must clear cached usage and retry state for CLI swaps as well as dashboard swaps. Add a check that simulates an external CLI swap while A's usage is cached."
   },
   {
    "id": "CAS-07",
    "severity": "low",
    "path": "docs/exec-plans/active/2026-10-21-claude-account-swap.md:155",
    "evidence": "Individual actionable substeps still lack their own checkboxes. Examples include lock/refusal/re-save/write/warning implementation at line 155; select, POST, and reload at line 162; both account logins and both saves at line 172; and both swaps, auth-status confirmation, and dashboard-run confirmation at line 173. Verification also bundles separate checks at lines 138, 143, and 148. Renaming the approach section does not resolve these remaining bundled checklist items.",
    "fix": "Split each independently actionable implementation substep, verification assertion, and user follow-up action into its own '- [ ]' checkbox."
   }
  ],
  "coverage": [
   "Read the complete revised plan and verified SHA256 0e68485443baf23e1785d5b44eda81e13eea120f76febaefdfc405545ff5d9ec.",
   "Compared all seven prior findings with the revised design and host dispositions; did not reopen the accepted post-swap snapshot risk or unsupported project credential overrides.",
   "Re-inspected OAuth usage fetching, cache retention, fallback snapshots, inherited/project environments, dashboard token injection, and quota polling.",
   "Traced related state and execution paths through runner/state_io.py, runner/projects.py, runner/project_runs.py, runner/modules/pty/__init__.py, and runner/usage_reader.py.",
   "Read relevant existing usage-cache test assertions and reviewed request-security and test-isolation context from the preceding inspection.",
   "Confirmed that only the plan is modified and the proposed account module and dedicated tests are not yet present."
  ],
  "limitations": [
   "No files were edited, tests executed, application started, or work delegated.",
   "This is a plan review; no account-switch implementation was available to inspect.",
   "Live credentials, personal configuration, launchd environment, and the profile endpoint were not accessed. The reported live checks remain supplied evidence.",
   "Claude Code's external credential/config writers were not independently inspected; failure scenarios involving them follow behavior explicitly acknowledged by the revised plan."
  ]
 }
}
```

Round 2 dispositions (host):
- CAS-08 accepted: save holds the same machine-wide lock; use calls an internal unlocked re-save helper; save/save and save/use blocking tests added.
- CAS-09 accepted: save stores live oauthAccount only if accountUuid == profile uuid, else a minimal one rebuilt from the profile response; outgoing re-save inside use replaces only credentials and keeps verified identity fields; tests added.
- CAS-10 accepted: swap generation = index file st_mtime_ns (touched by every CLI or dashboard use); _load_claude_oauth_usage clears cache/retry on generation change and refuses to publish a fetch whose generation changed. The in-process counter was dropped in favour of this single cross-process mechanism.
- CAS-07 accepted: implementation, verification and user follow-up items split into single-deliverable checkboxes.

## Plan review round 3

Result: `/tmp/age125-art/r3/claudex-by8t87z9/result.json` (diagnostics outside checkout)

```json
{
 "status": "completed",
 "assurance": "cross_provider",
 "cli": "codex-cli 0.163.0",
 "session": "01a1611a-ec78-73d1-b8f2-61bbff4a2a70",
 "plan_sha256": "7ebec7c5c0dfb4c6360600242f7c70dd1bb8799c7eb18c37ba774a289ecc2d5f",
 "response": {
  "verdict": "REVISE",
  "summary": "CAS-08, CAS-09, and CAS-10 are addressed in the revised design. One additional account-label edge case remains, along with bundled actionable checklist items. The on-disk plan matches the supplied SHA256.",
  "findings": [
   {
    "id": "CAS-11",
    "severity": "medium",
    "path": "docs/exec-plans/active/2026-10-21-claude-account-swap.md:62",
    "evidence": "Multiple labels may reference the same account UUID; only label syntax is constrained. Save account A as both a and alias, then let its refresh token rotate. Switching to B resolves one matching A label and updates only that snapshot. The other alias retains the older credentials. Using that alias subsequently restores the rotated-out token instead of A's preserved current credentials, potentially requiring another login despite a valid snapshot existing. This can occur before the documented four-week expiry risk.",
    "fix": "Enforce one label per verified account UUID, or define aliases over a single canonical credential snapshot. Add a check covering duplicate labels followed by token rotation and switching through either label."
   },
   {
    "id": "CAS-07",
    "severity": "low",
    "path": "docs/exec-plans/active/2026-10-21-claude-account-swap.md:199",
    "evidence": "Some independent actions still share one checkbox: dashboard switching and endpoint authorization at line 130; CLI implementation and setup documentation at line 190; both endpoints at line 192; POST, reload, and error alert at line 199; and running use versus confirming auth status at line 213. These remain bundled despite the requested individual-checkbox requirement.",
    "fix": "Give each independent implementation action, acceptance assertion, and follow-up check its own '- [ ]' item, including separate GET/POST endpoint tasks and separate success/error UI behavior checks."
   }
  ],
  "coverage": [
   "Read the complete revised plan and verified SHA256 7ebec7c5c0dfb4c6360600242f7c70dd1bb8799c7eb18c37ba774a289ecc2d5f.",
   "Checked prior findings against the revised locking, verified identity storage, outgoing credential preservation, and cross-process cache-generation design.",
   "Re-inspected request-token enforcement, index rendering, OAuth usage fetching, cache retention, fallback snapshots, and dashboard quota polling.",
   "Traced related execution and shared-state paths through runner/project_runs.py, runner/modules/pty/__init__.py, runner/usage_reader.py, and runner/state_io.py, including inherited and project-specific environments.",
   "Read existing usage-cache failure/retention assertions. Confirmed that only the plan is modified and the proposed account module and dedicated tests are absent.",
   "Accepted the explicitly bounded residual risks and unsupported project credential overrides without reopening them."
  ],
  "limitations": [
   "No files were edited, tests executed, application started, or work delegated.",
   "This reviews the implementation plan; no account-switch implementation was available.",
   "Live credentials, launchd configuration, profile responses, and Claude Code's external writers were not independently inspected.",
   "The duplicate-label failure follows the token-rotation behavior assumed by the plan; actual token-revocation timing was not verified."
  ]
 }
}
```

Round 3 dispositions (host):
- CAS-11 accepted: one label per verified uuid; save refuses a uuid already saved under a different label; same label + same uuid overwrites. Test added.
- CAS-07 accepted: split acceptance (dashboard switch vs GET guard vs POST guard), CLI vs docstring, GET vs POST endpoints, UI POST/reload/alert, and use vs auth-status confirmation into separate checkboxes.

## Plan review round 4

Result: `/tmp/age125-art/r4/claudex-kecnyh59/result.json` (diagnostics outside checkout)

```json
{
 "status": "completed",
 "assurance": "cross_provider",
 "cli": "codex-cli 0.163.0",
 "session": "01a1611a-ec78-73d1-b8f2-61bbff4a2a70",
 "plan_sha256": "bd910e1d07d869cb00f19bd566296b52da25e4f839c910b110d968d8bb674969",
 "response": {
  "verdict": "APPROVED",
  "summary": "No material unresolved defects found in the revised plan. CAS-11 is addressed by the one-label-per-UUID rule; prior substantive fixes remain covered. Minor checklist granularity remains. The plan matches the supplied SHA256.",
  "findings": [
   {
    "id": "CAS-07",
    "severity": "low",
    "path": "docs/exec-plans/active/2026-10-21-claude-account-swap.md:226",
    "evidence": "Two user follow-up entries still bundle separate actions and verification checks: line 226 combines starting a dashboard run with confirming account A; line 227 combines switching to B with confirming quota-card changes.",
    "fix": "Split each entry into an action checkbox and a separate confirmation checkbox."
   }
  ],
  "coverage": [
   "Read the complete current plan and verified SHA256 bd910e1d07d869cb00f19bd566296b52da25e4f839c910b110d968d8bb674969.",
   "Checked the revisions against all prior findings, including duplicate-account labels, shared locking, identity consistency, and cross-process cache invalidation.",
   "Re-inspected existing usage-cache retention and quota fallback behavior in runner/app.py.",
   "Across this review sequence, traced request guards, dashboard callers, dispatch environments, PTY environments, snapshot readers, and shared-state helpers beyond the plan's implementation file list.",
   "Confirmed that only the plan is modified and the proposed account module and dedicated tests remain absent."
  ],
  "limitations": [
   "Static plan approval only; implementation correctness remains subject to inspection after coding.",
   "No files were edited, tests executed, application started, or work delegated.",
   "Live credentials, profile responses, launchd configuration, and external Claude Code writers were not independently inspected. Explicitly accepted residual risks remain."
  ]
 }
}
```

Round 4 disposition: CAS-07 (low, user follow-up granularity) left as-is to keep the approval bound to the reviewed hash; follow-up items are user steps outside this session.
