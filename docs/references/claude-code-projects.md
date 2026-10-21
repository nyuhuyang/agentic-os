# Claude Code Projects (beta) — fit with AgenticOS

Research note for AGE-120, 2026-10-21. No code changes: the user has no access yet, and there is no API to integrate against.

## What it is

There are two products with the same name:

- **Legacy Projects** (claude.ai chat): a workspace with its own chats, uploaded knowledge files (RAG on paid plans, up to about 10x context) and custom instructions. Sharing is Team/Enterprise only.
- **New Projects (beta, since 2026-09-17)**: one goal-driven conversation in claude.ai/code, the desktop Code tab and the mobile apps. It is not in the terminal CLI or the IDE extensions.
  - A **coordinator** scopes the goal, proposes threads, delegates work, reviews the results and assembles them.
  - Each **thread** is a full Claude Code cloud session on its own branch and its own repo copy. Overlapping edits surface as PR merge conflicts. Threads may use subagents, loops and workflows.
  - All threads share one **project memory** (details and decisions). A **library** holds the files you add and the artifacts Claude produces.
  - Configurable per project: the cloud environment, connectors, plugins, instructions, and model plus effort (set separately for the coordinator and the workers). You can also set check-in, thread-start and update frequency.
  - Code edits need push rights on a github.com repo with the Claude GitHub App installed. Non-code projects (docs, research) need no repo.
  - **Local execution**: connect a folder via Remote Control and choose "Work locally". This needs CLI ≥ 2.1.280 (local: 2.1.305 ✓). Local threads pause while the Mac sleeps; cloud threads keep running.
  - **Usage** comes from the regular Pro/Max quota. Parallel threads burn it faster. Each project has its own usage view.
  - Legacy projects are being migrated: instructions, files, history and scheduled tasks carry over, with an email beforehand if the project was used in the last 30 days.
- **Access**: on 2026-10-09 access was granted to everyone on the waitlist *at that time*. Later sign-ups wait for staged notices. Team/Enterprise come later. To check, look for "Projects" in the claude.ai/code sidebar.

## Overlap with AgenticOS

| AgenticOS today | Projects equivalent | Who keeps it |
| --- | --- | --- |
| Linear ticket → runner dispatch | Coordinator splits a goal into threads | Runner: single scoped tickets. Projects: open-ended multi-part goals |
| Per-ticket worktree on `agent/<id>` | Thread on its own branch/repo copy | Both. Same isolation model |
| Verify harness + local auto-merge (AGE-111) | Thread opens PR; merge on GitHub | Runner. Projects work arrives as PRs, so `git pull` main after merging |
| Cross-provider agents (codex, dsh) + claudex-loop review | Claude only | Runner. Projects cannot do cross-provider review |
| Sandboxed confidential projects, template-only comments | Cloud threads upload code to Anthropic cloud | Runner only. **Never put confidential projects in cloud threads** |
| 127.0.0.1-only dashboard | Mobile steering, runs while the laptop is closed | Projects. This covers the "remote" need without exposing the runner (remote scope stays out of scope here) |
| `docs/context-maintenance.md`, exec plans | Project memory | Repo is truth. Project memory is not in git, so decisions must still land in repo docs |
| `usage_reader.py` (local Claude JSONL) | Per-project usage view | Gap: cloud threads write no local JSONL, so token stats undercount. The quota card (`remaining_pct`) still reflects the true usage |

## Recommended integration (when access arrives)

Use Projects as a second front door for work that does not fit one ticket. Keep the runner as the execution backbone for tickets. Build nothing until the pilot shows a real gap.

- [ ] Confirm access: "Projects" is visible in the claude.ai/code sidebar.
- [ ] Authorise the claude.ai Linear connector (currently unauthorised), so the coordinator can read and update tickets.
- [ ] Pilot 1, non-code: one research goal (this kind of note) with no repo. Compare its output and usage against a runner `claude` run.
- [ ] Pilot 2, code: create a project on `nyuhuyang/agentic-os` (public, GitHub App installed) with instructions "Follow AGENTS.md and CLAUDE.md; record decisions in docs/context-maintenance.md". Give it one multi-ticket goal, e.g. the multi-project dispatch dogfood.
- [ ] Pilot 2 check: thread PRs pass `.venv/bin/python3 -m py_compile runner/*.py` and pytest before merge.
- [ ] Pilot 3, local: run "Work locally" via Remote Control on a non-confidential repo. Check whether local threads write `~/.claude/projects` JSONL (if they do, `usage_reader.py` sees them for free).
- [ ] Record the pilot results here, then decide: keep both front doors, or move multi-part goals off Linear.

## Not doing now

- No runner code. There is no public API or webhook to start or read a Project, so the dashboard cannot dispatch to it. Revisit if one appears. `RemoteTrigger`/scheduled cloud agents are a separate, existing feature.
- No confidential repos in Projects. Even in local mode, the coordinator and memory live in Anthropic's cloud. This stays off until a written decision says otherwise.

## Sources

- https://support.claude.com/en/articles/9517075-what-are-projects
- https://claude.com/resources/articles/projects-redesigned
- https://smartscope.blog/en/blog/claude-code-projects-pro-max-waitlist-expansion-start-2026/
- https://www.developersdigest.tech/blog/claude-code-projects-coordinator-threads-pro-max-2026
- https://www.theregister.com/ai-and-ml/2026/09/18/claude-code-revamps-projects-so-you-can-work-and-pay-in-parallel/5297532
