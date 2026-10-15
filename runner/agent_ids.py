"""Canonical agent ids. Old ids are aliased on read and never rewritten in stored data."""

from __future__ import annotations

AGENTS = ("claude", "codex", "dsh")
# deepseek = retired direct-API agent, deepseek-tui = retired Rust CLI, aider = older alias.
_ALIASES = {"deepseek": "dsh", "deepseek-tui": "dsh", "aider": "dsh"}


def canonical_agent(agent: str | None) -> str | None:
    """Return the canonical id for a known agent (legacy ids → dsh), else None."""
    value = (agent or "").strip().lower()
    value = _ALIASES.get(value, value)
    return value if value in AGENTS else None


def agent_ids_for(agent: str) -> set[str]:
    """All raw ids (canonical plus legacy aliases) that resolve to agent."""
    return {agent} | {old for old, new in _ALIASES.items() if new == agent}
