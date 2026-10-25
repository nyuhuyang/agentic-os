"""Every test keeps the runner's lock and trash directories out of the real home directory."""

import os
import pty
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runner"))


@pytest.fixture(autouse=True)
def _real_pty_modules_need_a_pty(request):
    """The terminal suites drive real PTYs; a constrained host can run out of them."""
    if Path(str(request.node.fspath)).name not in ("test_terminals.py", "test_card_terminal.py"):
        return
    try:
        master, slave = pty.openpty()
    except OSError:
        pytest.skip("out of pty devices")
    else:
        os.close(master)
        os.close(slave)


@pytest.fixture(autouse=True)
def _private_home_dirs(tmp_path, monkeypatch):
    import projects
    monkeypatch.setattr(projects, "CARD_LOCK_DIR", tmp_path / "card-locks")
    monkeypatch.setattr(projects, "SESSION_TRASH", tmp_path / "session-trash")
    # AGE-137: never start a real ai-memory server from a test, even on a checkout where the
    # developer installed one. Tests that exercise the client build their own instance.
    monkeypatch.setenv("AGENTIC_OS_AI_MEMORY", "0")
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
