"""Per-file (mtime, size) cache in usage_reader: recompute only when a file changes."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runner"))
import usage_reader as u


def test_cached_by_stat_recomputes_only_on_change(tmp_path):
    f = tmp_path / "s.jsonl"
    f.write_text("a\n")
    calls = []

    def compute(p):
        calls.append(1)
        return p.read_text()

    assert u._cached_by_stat("test", f, f.stat(), compute) == "a\n"
    assert u._cached_by_stat("test", f, f.stat(), compute) == "a\n"
    assert len(calls) == 1

    f.write_text("ab\n")
    st = f.stat()
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
    assert u._cached_by_stat("test", f, f.stat(), compute) == "ab\n"
    assert len(calls) == 2
