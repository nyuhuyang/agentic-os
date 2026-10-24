# ai-memory — cross-agent memory for project tickets (AGE-137)

Assessed 2026-10-23 against ai-memory **3.2.2** ([repo](https://github.com/akitaonrails/ai-memory),
[site](https://aimemory.sh)). Verdict: **worth adopting, but at the runner's dispatch boundary, not
as a per-user harness install.** The native install (global lifecycle hooks + a LaunchAgent + MCP in
every harness) conflicts with how this runner launches agents; the memory service itself fits the
ticket handoff from Claude to Codex or DSH well.

## What it is

A single Rust binary that runs a local HTTP/MCP server over a git-backed markdown wiki. Lifecycle
hooks feed it observations; a zero-LLM consolidator turns sessions into pages; retrieval fuses FTS5,
entities and links (vectors optional). The wiki is the source of truth; the SQLite index is
rebuildable. Handoffs are typed and claim-once; hook capture and search work without any API key.
Supported harnesses include Claude Code, Codex and DeepSeek Harness (DSH) — for DSH, hooks go
through the `@deepseek-ai/dsh-hooks-claude-code` bridge and both the MCP entry and the hook patch
must be merged by hand into `$DSH_HOME/profiles/<profile>/cordis.patch.yml` (no `--apply`).

## Fit with our multi-agent switching

Where it helps:

- **A new card/worktree starts with no memory of the last one.** Within one card, AGE-114 already
  hands every earlier turn and transcript to the next agent or provider. Nothing carries a decision
  or a failed approach from a previous ticket, though, and the next provider re-derives it.
- **Review is a handoff.** Codex inspecting Claude's build (claudex-loop) currently gets the plan and
  the diff. A short, per-ticket memory page tells it what was tried, what the verify said and what
  the previous agent claimed, without re-reading the whole run log.
- **The schema matches our runs.** A run ends with status, verify, shortstat and a closing summary —
  exactly the fields worth remembering, and the server needs no LLM call to store or find them.

Where it does not replace anything:

- **In-card handoff stays AGE-114.** Resumed sessions get the reply only; a switch/new session gets
  the run chain and transcripts. ai-memory adds cross-card knowledge, not a better in-card replay.
- **It is not a substitute for the repo.** The brief is historical evidence; the prompt says so.
  Agents still verify against the current tree.

Why not the documented install:

- `ai-memory setup` writes into home directories (`~/.local/…`, `~/.claude/settings.json`,
  `~/.codex/config.toml`, a launchd agent). The runner's worktree contract forbids that here, and a
  per-user daemon would serve interactive sessions that the runner does not launch.
- Confidential projects run behind a sandbox whose network allowlist is Codex/OpenAI only; harness
  hooks added globally would also load in those runs and fail (or leak prompts) there.
- DSH has no apply-able hook file, so a native install would need a hand-merged Cordis patch.

## What this branch installs

```
runner/ai_memory.py                 HTTP/MCP client + lazy server lifecycle
runner/project_runs.with_memory_brief()
                                    appends the brief after the task
runner/app.py                       brief before a fresh run; record after it
scripts/install_ai_memory.sh        release download (SHA-256) into .tools/, init under state/
```

Flow for one project-bound run:

1. A fresh (not resumed) non-confidential run asks the server for `tickets/<ident>.md` in the
   `(<project key>, <ticket id>)` scope and prepends up to 6 newer sections (≤ 3.5 KB) to the prompt.
2. The agent runs as before; memory is never a dependency.
3. After the run the runner appends a section: run id, timestamp, agent, status, task, verify,
   shortstat, runner commit and the closing summary (secrets redacted, ≤ 1.2 KB). The page keeps the
   newest 40 sections and 12 KB.
4. Pages are written with ai-memory's conditional write (`expected_page_id`), retried once on a
   concurrent append. A repeated run id is a no-op while it is one of the last 100 ids in the page
   header (the section list itself keeps the newest 40).

Confidential projects are skipped in both directions. Unknown confidentiality is skipped in the
record path too.

## Install and operate

```sh
sh scripts/install_ai_memory.sh            # .tools/ai-memory/ + state/ai-memory/ + enabled marker
sh scripts/install_ai_memory.sh --force    # re-download (upgrade); wiki/index untouched

.venv/bin/python3 runner/ai_memory.py                          # status
.venv/bin/python3 runner/ai_memory.py brief agentic-os AGE-137 # the block a run would get
```

- Data: `state/ai-memory/` (gitignored; wiki markdown under `wiki/`, ~90 MB with the local
  embedding model, downloaded on first start). Server log: `state/ai-memory/logs/runner-server.log`.
- Server: loopback on a per-checkout port (base 49375, plus a small hash of the data directory), so two
  checkouts never reuse each other's service. Bearer token from `state/ai-memory/auth-tokens/default`;
  started lazily by the runner (or the first `brief`) and reused by later runner processes. Stopping the
  runner leaves it running; it is restarted on demand.
- Lifecycle: resident by design. There is no idle timeout, so after the first use it keeps its model
  and index in memory until the machine reboots or you stop it. To stop it by hand, use the port from
  `python3 runner/ai_memory.py` (for example `kill "$(lsof -ti tcp:49434)"`); the next project run or
  `brief` starts it again. Runner restarts do not stop it.
- Disable: `rm state/ai-memory/enabled` (or `AGENTIC_OS_AI_MEMORY=0`). Re-enable: touch the marker,
  or `AGENTIC_OS_AI_MEMORY=1`.
- External server: set `AI_MEMORY_SERVER_URL` and `AI_MEMORY_AUTH_TOKEN`; no local binary needed.
- Port: `AGENTIC_OS_AI_MEMORY_PORT` overrides the per-checkout default; a stock ai-memory on 49374 is
  left alone.
- The install is per checkout. After the branch merges, run the installer once in the main checkout;
  the merged runner finds it there.

## Failure modes

- Binary missing, marker absent, server down or a call timing out (4 s): the run proceeds without a
  brief and without a record. A failed start backs off for 60 s instead of retrying on every run.
- The server is never started for a confidential project, and no brief or summary text leaves the
  runner for one.
- Stored text is untrusted historical evidence: the prompt labels it, and the server itself keeps
  pages as plain markdown the operator can edit or audit.

## Limits / follow-ups

- No MCP registration or lifecycle hooks: agents cannot query memory mid-run, and interactive
  dashboard sessions (the other launch path in `app.py`) are not captured. Add that only if the
  cross-card brief proves useful in practice.
- One page per ticket, not per project. A project-level decisions page (`decisions/…`) is the natural
  next step once the ticket scope is dogfooded.
- Zero-LLM path only; no consolidation prompt, no dream pass, no vectors beyond the local model.
- The local embedding model (~90 MB) is fetched on the first start. In an offline environment,
  expect FTS-only behaviour while that fetch fails.
