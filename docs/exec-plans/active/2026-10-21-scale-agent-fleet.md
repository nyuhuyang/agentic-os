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

## Cost reality (decides who writes and who reviews)

Three agents run side by side: `claude`, `codex`, `dsh`. The first two sit on $20/month
subscriptions sized for one human working interactively; continuous fleet work exhausts their
rolling and weekly windows. `dsh` is per-token and has no fixed monthly ceiling, and is roughly an
order of magnitude cheaper per unit of work than list-price Claude/Codex API. So the split is not
"best model per task" but **cheap elastic writer + scarce premium reviewer**:

- `dsh` carries bulk implementation. Its marginal cost is low enough that retries and best-of-N
  are affordable, which buys reliability more cheaply than a stronger model would.
- `claude` / `codex` are a prepaid monthly allowance of *judgment*. Spend it on cross-provider
  review, ambiguous design calls, and work `dsh` must not touch (confidential projects are already
  refused for `dsh` in `runner/project_runs.py`). Never let implementation drain it.
- Reviewer capacity is therefore the scarce resource. Deterministic `verify` runs first and should
  absorb everything it can; cross-provider review is sampled and risk-weighted, not applied to
  every diff. Every check `verify` cannot do spends reviewer quota.
- Open risk: if `dsh` becomes the only writer, execution is a monoculture. The writer slot must stay
  a config-level swap behind the existing agent abstraction, and a small share of work should keep
  running on the other two so the fallback stays exercised.

## Progress Checklist

### Phase 1 · Automated verification gate (no merge without proof)
Today: `_merge_when_last` merges on verify badge `pass` **or `no check`** (`runner/app.py` post-run).
A project with no `verify` command auto-merges on the agent's own word.
- [ ] Decide policy for `no check` projects: block auto-merge, require a reviewer pass, or opt-in flag
- [ ] Spike: reviewer-agent pass (cross-provider, diff + ticket in, verdict JSON out) as a second gate after `verify`
- [ ] Decide review sampling, since reviewer quota is scarce: always review large or sensitive diffs and unfamiliar task types, sample the rest, leave low-risk diffs on `verify` alone
- [ ] Decide which verdicts block merge vs. only badge the card
- [ ] Log each cross-provider reviewer catch that `verify` missed (run id, author/reviewer provider, finding, real or false alarm)
- [ ] After 1–2 months, review the log: keep the reviewer layer if it catches real issues, drop it to save tokens if not. This is also the test of whether `dsh` can be the default writer at all
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

### Phase 4 · Concurrency, cost, and quota ceiling
- [ ] Measure: how many concurrent worktree runs this host sustains (CPU/RAM/disk)
- [ ] Decide limits: per-project and global concurrent runs; queued tickets wait instead of failing
- [ ] Spike: budget gate from `usage_reader.py` (pause dispatch when daily/weekly token budget is hit)
- [ ] Spike: quota-aware routing — task class picks the agent (bulk implementation → `dsh`; review/design → `claude`/`codex`), with a per-agent ledger (rolling/weekly windows for the subscriptions, $ spend for `dsh`) that reserves subscription quota for review
- [ ] Write the Phase 4 plan + ticket

### Handoff
- [x] `docs/context-maintenance.md` points at this umbrella plan as the long-term direction

## Acceptance Criteria
- [ ] No branch auto-merges without a passing automated check (verify or reviewer)
- [ ] With 10 runs finished, the default board view shows only the cards needing a decision
- [ ] One planner ticket can produce dispatched child tickets, ending in an approved state the human can see
- [ ] Dispatch past the concurrency or budget limit queues work and says so; it never silently drops it
- [ ] Cost per merged change is recorded and does not rise faster than merged output

## Constraints
- Build no phase before the one above it is trustworthy. Fan-out without a gate multiplies risk.
- No remote workers, multi-user, or cloud sandboxes: out of scope per AGENTS.md escalation list
- Run status closed set and `run_log.jsonl` are not changed without human confirmation
- Server stays on 127.0.0.1
- Agent count is not a goal. Measure verified merged work per unit of human attention and per dollar.
- Subscription quota is reserved for review; bulk implementation defaults to the metered agent.

## Verification
- [ ] Each phase's own plan lists its proof commands; this umbrella is done when all four phase plans are in `completed/`
