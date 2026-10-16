"""Per-issue reset generation and per-issue tracker lock (plan Decision 11, DSH-30).

A reset (a ticket dragged back to Todo, or a run marked todo/rework) bumps the issue's
generation. Every launch records the generation it started under. Session resume and the
agent lock only trust records of the current generation, and a completion from an older
generation never moves the ticket. All state-changing tracker operations for one issue
take its lock and check the generation inside it, so an update already in flight cannot
land after a reset.
"""

from __future__ import annotations

import threading
from pathlib import Path

from state_io import json_transaction, read_json

GEN_PATH = Path(__file__).resolve().parent.parent / "state" / "reset_generations.json"

_locks: dict[str, threading.RLock] = {}
_locks_guard = threading.Lock()


def issue_lock(key: str) -> threading.RLock:
    """In-process lock for one issue (all tracker writers live in the dashboard process)."""
    with _locks_guard:
        return _locks.setdefault(key, threading.RLock())


def current(key: str | None) -> int:
    if not key:
        return 0
    value = read_json(GEN_PATH).get(key, 0)
    return value if isinstance(value, int) else 0


def snapshot() -> dict:
    """All generations at once (the poller compares before/after a fetch)."""
    return dict(read_json(GEN_PATH))


def bump(key: str) -> int:
    with json_transaction(GEN_PATH, indent=2) as gens:
        gens[key] = (gens.get(key) if isinstance(gens.get(key), int) else 0) + 1
        return gens[key]


def restore(key: str, previous: int, bumped: int) -> None:
    """Undo a bump whose transition was refused, unless something bumped again since."""
    with json_transaction(GEN_PATH, indent=2) as gens:
        if gens.get(key) == bumped:
            gens[key] = previous


def is_current(key: str | None, gen: int | None) -> bool:
    """True when `gen` (None = not generation-tracked) is still the issue's generation."""
    return gen is None or not key or current(key) == gen
