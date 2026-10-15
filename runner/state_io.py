"""Cross-process locked read-modify-write for the runner's shared JSON state (plan 4b).

The dashboard, run_skill.py and the tracker writers all rewrite the same files. Each
whole load -> change -> save holds an fcntl lock on a sibling `<file>.lock`, and each
save goes through a unique temp file plus os.replace, so a concurrent writer can never
lose another writer's update or leave a half-written file.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable


@contextlib.contextmanager
def file_lock(path: Path):
    """Exclusive lock for `path`'s read-modify-write. Blocks; also excludes other threads."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path.with_name(path.name + ".lock"), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)  # closing the descriptor releases the lock


def write_json_atomic(path: Path, data: Any, **dump_kw) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, **dump_kw)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


def read_json(path: Path, default: Callable[[], Any] = dict) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return default()


@contextlib.contextmanager
def json_transaction(path: Path, default: Callable[[], Any] = dict, **dump_kw):
    """`with json_transaction(p) as data: data[...] = ...` -> saved atomically on success."""
    with file_lock(path):
        data = read_json(path, default)
        yield data
        write_json_atomic(path, data, **dump_kw)
