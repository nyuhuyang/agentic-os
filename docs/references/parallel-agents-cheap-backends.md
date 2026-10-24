# Parallel agents without Claude Projects' cost — Chinese models vs self-build

Research note for AGE-120, 2026-10-24. Follows `claude-code-projects.md`. The question: a $20 Claude Pro plan cannot fund many parallel Claude Code threads, so can DeepSeek or another Chinese model run a Projects-style setup (one coordinator plus many parallel agents)?

## Short answer

Yes. The cheapest route is to reuse what the runner already has, not to buy another product. AgenticOS already covers most of Projects:

| Projects piece | AgenticOS today |
| --- | --- |
| Thread = own branch + repo copy | Each Linear ticket runs in its own worktree on `agent/<id>`. Dispatch starts one background thread per ticket, and no global concurrency cap was found in `runner/modules/linear/__init__.py` |
| Worker model | `dsh` agent = DeepSeek Harness (already wired, `runner/dsh_cli.py`) |
| Assembly / merge | Verify harness + local auto-merge (AGE-111) |
| Shared memory | `docs/context-maintenance.md` + exec plans (in git, which is better than cloud memory) |
| Coordinator (goal → threads) | **Missing.** Today you split a goal into tickets by hand |
| Mobile steering, cloud runs | Missing, and out of scope (127.0.0.1 only) |

## Chinese options

Prices are from 2026-10 sources. Only DeepSeek's prices were checked on the official page; verify the others before paying.

| Option | What it gives | Price | Parallel fit |
| --- | --- | --- | --- |
| **DeepSeek API** (official) | `deepseek-flash` (V4.1, 1M ctx) and `deepseek-v4-pro` (1M ctx). Anthropic-compatible endpoint, so Claude Code itself can run on it | Per 1M tokens, off-peak: Flash $0.15 in / $0.003 cache-hit / $0.60 out. Pro $0.66 / $0.022 / $1.98. Peak is 2x | **Best.** Pay per token, no 5-hour window. Concurrency limit is 2500 (Flash) and 500 (Pro) |
| Kimi (Moonshot) | Agent Swarm with up to 300 sub-agents (K2.6) inside the Kimi app. Kimi Code CLI | About $19/mo membership; swarm tier conflicting ($19 vs $39+). API about $0.60 / $2.50 | Swarm is a cloud chat feature, not tied to your repo or worktrees. Good for research fan-out, not for code tickets |
| Zhipu GLM Coding Plan | GLM-5.x with an Anthropic-compatible endpoint | $18 / $72 / $160 per month (one source says the plan is no longer on sale) | Flat plan with 5-hour and weekly credit windows. Parallel threads hit the same wall as Claude Pro |
| MiniMax Token / M Plan | M3.1 Flash, Anthropic-compatible | From about $10/mo, or $0.15 / $0.60 pay-as-you-go | Like GLM, the windowed plans cap parallel use |
| Alibaba Qwen Token Plan | Qwen Code CLI (the free tier ended 2026-04-15) | ¥39 / ¥139 / ¥499 per month | Documented 1–2 / 3–4 / 6–8 concurrent agents per tier |

None of these offer the Claude Projects product itself, i.e. a coordinator plus parallel cloud threads on your GitHub repo. Kimi Swarm is the closest, but it works on chat and documents, not on a repo checkout.

**Why pay-per-token wins for parallel work:** flat "coding plans" ration usage per 5-hour window. That is the same limit that makes Claude Pro too small. DeepSeek bills per token with heavy cache discounts, so 10 threads cost 10× one thread, with no lockout.

### Cost estimate per thread (rough)

The basis is a real AGE-110 Codex run: 7.36M input tokens at a 96.8% cache-hit rate. Output is assumed at about 0.1M.

- Flash, off-peak: 0.24M miss × 0.15 + 7.12M hit × 0.003 + 0.1M × 0.60 ≈ **$0.12**
- Pro, off-peak: 0.24 × 0.66 + 7.12 × 0.022 + 0.1 × 1.98 ≈ **$0.51**
- 10 heavy threads a day for 30 days ≈ $36/mo on Flash, $150/mo on Pro. Typical tickets are much smaller (the runner's median `claude` run is $0.07).

**Peak hours** are 01:00–04:00 and 06:00–10:00 UTC, Mon–Fri, which is 09–12 and 14–18 Beijing time, or 21:00–00:00 and 02:00–06:00 US Eastern (EDT). US daytime is entirely off-peak.

## Self-build ladder (stop at the first rung that holds)

- [ ] **Rung 0, no code:** split a goal into N Linear tickets with agent `dsh` (plus a `project:<key>` label if needed). The runner runs them in parallel worktrees and auto-merges them. Try this on one real goal and record the cost in the dashboard's DeepSeek balance-delta row.
- [ ] **Rung 1, env-only agent:** run the Claude Code CLI against DeepSeek (`ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic`, `ANTHROPIC_MODEL=deepseek-v4-pro`, `CLAUDE_CODE_SUBAGENT_MODEL=deepseek-flash`, per DeepSeek's official guide). Claude Code's own subagents and worktree-isolated agents then act as an in-ticket coordinator. First try it by hand in a terminal tab. Wire it in as a runner agent only if it beats `dsh`.
- [ ] **Rung 2, coordinator, only if Rung 0 splitting gets tedious:** add a "decompose" action where one `deepseek-v4-pro` call turns a goal into N sub-issue drafts. The user approves them, and the runner creates them as Linear sub-issues. About 100 lines. Write an exec plan first.

Not worth building: cloud execution, mobile steering, or a hybrid proxy that keeps Claude as the main agent and routes subagents to DeepSeek (unofficial proxies or patches). Keep the Claude Pro plan for coordinator and review turns, which are high-value and low-token.

## Constraints

- **Confidential projects never go to DeepSeek or any other third-party model API.** The runner already rejects `dsh` for them. Any Rung 1/2 agent must inherit that rule.
- DeepSeek's tool-use quality on long agentic tasks is below Claude's. Keep the verify harness as the gate, and keep a Claude or Codex review on merges that matter.

## Sources

- DeepSeek pricing (official): https://api-docs.deepseek.com/quick_start/pricing
- DeepSeek × Claude Code (official): https://api-docs.deepseek.com/quick_start/agent_integrations/claude_code/
- Kimi Agent Swarm: https://www.kimi.com/en/help/agent/agent-swarm
- Kimi pricing/review: https://www.mayhemcode.com/2026/08/kimi-agent-swarm-review-features.html
- GLM Coding Plan: https://vibecoding.app/blog/zhipu-ai-glm-coding-plan-review , https://rankllms.com/coding-plans/
- MiniMax: https://github.com/Alorse/cc-compatible-models , https://www.digitalapplied.com/blog/run-minimax-m3-1-flash-inside-claude-code-setup
- Qwen: https://www.alibabacloud.com/help/en/model-studio/coding-plan , https://codingplan.org/en/plans/qwen , https://inventivehq.com/blog/qwen-code-still-free-2026-shutdown
- Subagent routing: https://musaab.io/posts/2026/deepseek-subagents-claude-code/
