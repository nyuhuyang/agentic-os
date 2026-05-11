# agentic-os — Agent Contract

See [`AGENTS.md`](AGENTS.md) for architecture, workflow, and escalation rules.

## Env vars

| Var | Default | Purpose |
| --- | --- | --- |
| `REGISTRY_JSON` | `.codex/registry.json` | Skill registry path |
| `WORKSPACE_CLAUDE_DIR` | `.claude/` | Dir containing `rate-limits-live.json` |

## Usage data sources

| Source | Path |
| --- | --- |
| Claude JSONL | `~/.claude/projects/**/*.jsonl` |
| Codex SQLite | `~/.codex/state_5.sqlite` (`threads` table) |
| Claude live rate limits | `$WORKSPACE_CLAUDE_DIR/rate-limits-live.json` — silently skipped if missing |
| Codex live rate limits | `~/.codex/sessions/**/*.jsonl` (`token_count` events) |
| Budget overrides | `~/.claude/budget.json` (`window_5h`, `window_7d`, `daily_runs_max`) |
