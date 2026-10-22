---
status: in-progress
created: 2026-10-21
horizon: long-term (umbrella; each phase gets its own ticket + plan when started)
---

# Task: Scale from a handful of agents to a fleet

## Goal
Make running many agents at once safe without spending more human attention. The bottleneck at
scale is human review, not spawn count. Each extra agent needs an automated check standing in for
the human. Order: trust first (1), then attention (2), then fan-out (3), then the ceiling (4).
Origin: AGE-126 design discussion. Each phase below is a stub. Refine it into its own
`docs/exec-plans/active/<date>-<slug>.md` and Linear ticket before building.

## Progress Checklist

### Phase 1 · Automated verification gate (no merge without proof)
Today: `_merge_when_last` merges on verify badge `pass` **or `no check`** (`runner/app.py` post-run).
A project with no `verify` command auto-merges on the agent's own word.
- [ ] Decide policy for `no check` projects: block auto-merge, require a reviewer pass, or opt-in flag
- [ ] Spike: reviewer-agent pass (cross-provider, diff + ticket in, verdict JSON out) as a second gate after `verify`
- [ ] Decide which verdicts block merge vs. only badge the card
- [ ] Log each cross-provider reviewer catch that `verify` missed (run id, author/reviewer provider, finding, real or false alarm)
- [ ] After 1–2 months, review the log: keep the reviewer layer if it catches real issues, drop it to save tokens if not
- [ ] Write the Phase 1 plan + ticket

### Phase 2 · Exception inbox (board shows only what needs a human)
- [ ] Define the closed set of "needs human" states (verify failed, merge conflict, reviewer reject, agent asked a question, timeout)
- [ ] Spike: default board view = inbox; merged/successful cards collapse out of the way
- [ ] Decide whether the inbox is a filter on the existing board or a separate view
- [ ] Write the Phase 2 plan + ticket

### Phase 3 · Agent-driven ticket decomposition
- [ ] Spike: "planner" ticket whose run outputs N child tickets (title, body, `project:<key>` label) instead of code
- [ ] Decide approval point: human approves the child list before dispatch, or children dispatch directly
- [ ] Decide parent/child linkage in Linear (sub-issues vs. relation) and parent auto-close rule
- [ ] Write the Phase 3 plan + ticket

### Phase 4 · Concurrency and cost ceiling
- [ ] Measure: how many concurrent worktree runs this host sustains (CPU/RAM/disk)
- [ ] Decide limits: per-project and global concurrent runs; queued tickets wait instead of failing
- [ ] Spike: budget gate from `usage_reader.py` (pause dispatch when daily/weekly token budget is hit)
- [ ] Write the Phase 4 plan + ticket

### Handoff
- [x] `docs/context-maintenance.md` points at this umbrella plan as the long-term direction

## Acceptance Criteria
- [ ] No branch auto-merges without a passing automated check (verify or reviewer)
- [ ] With 10 runs finished, the default board view shows only the cards needing a decision
- [ ] One planner ticket can produce dispatched child tickets, ending in an approved state the human can see
- [ ] Dispatch past the concurrency or budget limit queues work and says so; it never silently drops it

## Constraints
- Build no phase before the one above it is trustworthy. Fan-out without a gate multiplies risk.
- No remote workers, multi-user, or cloud sandboxes: out of scope per AGENTS.md escalation list
- Run status closed set and `run_log.jsonl` are not changed without human confirmation
- Server stays on 127.0.0.1
- Agent count is not a goal. Measure verified merged work per unit of human attention.

## Verification
- [ ] Each phase's own plan lists its proof commands; this umbrella is done when all four phase plans are in `completed/`
