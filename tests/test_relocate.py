"""scripts/relocate_checkout.sh with launchctl/curl/pgrep/plutil shimmed: success, refusals, rollback."""

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "relocate_checkout.sh"

SHIMS = {
    # launchctl: record calls; bootstrap marks the runner "up" from the path in the plist
    "launchctl": '''echo "launchctl $*" >> "$SHIM_LOG"
case "$1" in
  bootout) rm -f "$SHIM_UP" ;;
  bootstrap) [ -n "${SHIM_FAIL_UP:-}" ] || grep -o '<string>[^<]*runner/app.py' "$3" | sed 's/<string>//; s|/runner/app.py||' > "$SHIM_UP" ;;
esac''',
    "curl": '''case "$*" in
  *api/runs*) echo "${SHIM_JOBS:-[]}" ;;
  *%{http_code}*) [ -s "$SHIM_UP" ] && echo 200 || echo 000 ;;
  *) [ -s "$SHIM_UP" ] && echo '<meta name="agentic-os-token" content="tok">' ;;
esac''',
    "pgrep": '''[ -s "$SHIM_UP" ] && [ "$2" = "$(cat "$SHIM_UP")/runner/app.py" ]''',
    "plutil": "exit 0",
}


@pytest.fixture
def env(tmp_path):
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    for name, body in SHIMS.items():
        (bin_ / name).write_text("#!/bin/sh\n" + body + "\n")
        (bin_ / name).chmod(0o755)
    old, new = tmp_path / "proto" / "agentic-os", tmp_path / "agentic-os"
    (old / "runner").mkdir(parents=True)
    (old / "runner" / "app.py").write_text("")
    (old / ".venv" / "bin").mkdir(parents=True)
    (old / ".venv" / "bin" / "pip").write_text(f"#!{old}/.venv/bin/python3\n")
    (old / ".venv" / "pyvenv.cfg").write_text(f"command = python3 -m venv {old}/.venv\n")
    subprocess.run(["git", "init", "-q", str(old)], check=True)
    subprocess.run(["git", "-C", str(old), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "i"], check=True)
    subprocess.run(["git", "-C", str(old), "worktree", "add", "-q", str(old / ".claude" / "worktrees" / "w1")], check=True)
    plist = tmp_path / "agent.plist"
    plist.write_text(f"<string>{old}/.venv/bin/python3</string>\n<string>{old}/runner/app.py</string>\n")
    up = tmp_path / "up"
    up.write_text(str(old))
    e = {**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}", "AOS_PLIST": str(plist),
         "SHIM_LOG": str(tmp_path / "calls"), "SHIM_UP": str(up)}
    return old, new, plist, e


def run(old, new, e):
    return subprocess.run(["sh", str(SCRIPT), str(old), str(new)], env=e, capture_output=True, text=True)


def test_moves_repoints_and_restarts(env):
    old, new, plist, e = env
    r = run(old, new, e)
    assert r.returncode == 0, r.stdout + r.stderr
    assert not old.exists() and (new / "runner" / "app.py").exists()
    assert str(old) not in plist.read_text() and str(new) in plist.read_text()
    assert str(old) not in (new / ".venv" / "bin" / "pip").read_text()
    wt = subprocess.run(["git", "-C", str(new / ".claude" / "worktrees" / "w1"), "status", "--short"],
                        capture_output=True, text=True)
    assert wt.returncode == 0  # the nested worktree still resolves its repo
    assert "runner up from" in r.stdout


def test_refuses_running_jobs_existing_target_and_non_checkout(env, tmp_path):
    old, new, plist, e = env
    before = plist.read_text()
    assert "jobs are running" in run(old, new, {**e, "SHIM_JOBS": '[{"run_id":"x"}]'}).stdout
    new.mkdir()
    assert "already exists" in run(old, new, e).stdout
    new.rmdir()
    assert "not an AgenticOS checkout" in run(tmp_path, new, e).stdout
    assert old.exists() and plist.read_text() == before


def test_rolls_back_when_the_runner_does_not_come_up(env):
    old, new, plist, e = env
    before = plist.read_text()
    r = run(old, new, {**e, "SHIM_FAIL_UP": "1"})
    assert r.returncode == 1 and "rolling back" in r.stdout
    assert old.exists() and not new.exists() and plist.read_text() == before
    assert str(new) not in (old / ".venv" / "bin" / "pip").read_text()
