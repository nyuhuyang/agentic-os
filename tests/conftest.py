"""Every test keeps the runner's lock and trash directories out of the real home directory."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runner"))


@pytest.fixture(autouse=True)
def _private_home_dirs(tmp_path, monkeypatch):
    import projects
    monkeypatch.setattr(projects, "CARD_LOCK_DIR", tmp_path / "card-locks")
    monkeypatch.setattr(projects, "SESSION_TRASH", tmp_path / "session-trash")
    # Session-name syncs can write native names: never the real ~/.claude or ~/.codex stores.
    monkeypatch.setattr(projects, "CLAUDE_PROJECTS", tmp_path / "claude-store")
    monkeypatch.setattr(projects, "CODEX_DB", tmp_path / "codex-store" / "state_5.sqlite")
    # LocalTracker derives its first identifier from the real ticket worktrees; keep that out of
    # a developer machine's ~/.agentic-os so LOC-2 is not LOC-36 (AGE-125 suite run).
    monkeypatch.setattr(projects, "WORKTREE_ROOT", tmp_path / "worktrees")
    # Account swaps (AGE-125) never read or touch the real index or lock.
    import claude_account
    monkeypatch.setattr(claude_account, "STATE_DIR", tmp_path / "agentic-os")
    monkeypatch.setattr(claude_account, "INDEX", tmp_path / "agentic-os" / "claude-accounts.json")
    monkeypatch.setattr(claude_account, "LOCK", tmp_path / "agentic-os" / "claude-account.lock")
