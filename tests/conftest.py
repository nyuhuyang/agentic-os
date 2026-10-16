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
