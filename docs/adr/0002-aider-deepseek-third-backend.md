# ADR 0002 — Aider + DeepSeek as Third Agent Backend

**Date:** 2026-05-11  
**Status:** Accepted

## Context

AgenticOS already supports two agent backends: `claude` (Claude Code CLI) and `codex` (OpenAI Codex CLI). Both require API subscriptions with hard token budget windows. We needed a third backend that:

- Has a different cost structure (pay-per-token, no subscription cap)
- Can run autonomously on Linear issues
- Integrates with the existing dispatch pipeline without new infrastructure

## Decision

Use **Aider** as the CLI wrapper with **DeepSeek** as the model provider.

- Backend identifier: `"aider"` throughout the codebase
- Display label: `"DeepSeek"` in the UI (Aider is the tool, DeepSeek is what users care about)
- Default model: `deepseek-v4-flash` (fast, cheap); upgradeable to `deepseek-v4-pro` via config
- Auth: `DEEPSEEK_API_KEY` env var

## Alternatives Considered

### Direct DeepSeek API (no Aider)
Call the DeepSeek API directly from `app.py` via HTTP. Rejected because:
- Would require writing a custom agent loop (tool use, file ops, retries)
- Aider already handles prompt construction, streaming, and output parsing
- Significant scope creep for what is essentially a dispatch integration

### OpenRouter as proxy
Route DeepSeek through OpenRouter for unified billing. Deferred — adds a dependency and latency for no immediate gain. Can be enabled by changing the model string to `openrouter/deepseek/...`.

### New subprocess architecture
Build a dedicated `symphony/aider_deep.py` runner with git worktree isolation. Deferred — direct dispatch (`aider --no-git --message`) is sufficient until aider is used for real code modification tasks that require branch isolation.

## Consequences

**Good:**
- No new infrastructure — plugs into existing `_ai_cli` / `_ai_command` / `_agent_model` pattern
- Pay-per-token billing avoids subscription budget contention with Claude/Codex windows
- `deepseek-v4-flash` is fast enough for routing and skill dispatch

**Trade-offs:**
- Aider as intermediary adds one layer of abstraction; output is raw text (no structured JSON like Claude CLI)
- Token usage tracked from `run_log.jsonl` only — no real-time rate limit API (unlike Codex)
- `aider` CLI must be installed in the local env; not auto-provisioned

## Known Issues (at time of writing)

- Aider + DeepSeek reasoning models loop on large files — mitigated by switching to DeepSeek TUI (see P8)
- Symphony worktree runner deferred — if aider starts making code changes, branch isolation will be needed
