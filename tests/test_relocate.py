"""scripts/relocate_checkout.sh with launchctl/curl/pgrep/plutil shimmed: success, refusals,
rollback after a failed start, after an interrupt, and after a broken worktree."""

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "relocate_checkout.sh"

SHIMS = {
    # bootstrap marks the runner "up" from the checkout named in the plist, unless that checkout
    # is SHIM_FAIL_AT; SHIM_KILL_AT sends the script a TERM on the first bootstrap there.
    "launchctl": '''echo "launchctl $*" >> "$SHIM_LOG"
case "$1" in
  bootout) rm -f "$SHIM_UP" ;;
  bootstrap)
    at=$(grep -o '<string>[^<]*runner/app.py' "$3" | sed 's/<string>//; s|/runner/app.py||')
    if [ -n "${SHIM_KILL_AT:-}" ] && [ "$at" = "$SHIM_KILL_AT" ] && [ ! -e "$SHIM_LOG.killed" ]; then
      touch "$SHIM_LOG.killed"; kill -TERM $PPID; exit 0
    fi
    [ "$at" = "${SHIM_FAIL_AT:-}" ] || echo "$at" > "$SHIM_UP" ;;
esac''',
    "curl": '''case "$*" in
  *api/runs*) echo "${SHIM_JOBS:-[]}" ;;
  *%{http_code}*) [ -s "$SHIM_UP" ] && echo 200 || echo 000 ;;
  *) [ -s "$SHIM_UP" ] && echo '<meta name="agentic-os-token" content="tok">' ;;
esac''',
    "pgrep": '''pat=$2
case "$pat" in
  */runner/app.py) [ -s "$SHIM_UP" ] && [ "$pat" = "$(cat "$SHIM_UP")/runner/app.py" ] || exit 1
                   [ "$1" = -fl ] && echo "1 python $pat"; exit 0 ;;
  *) [ -n "${SHIM_OTHER_AT:-}" ] && [ "$pat" = "$SHIM_OTHER_AT/" ] && { echo "99 python $pat/runner/run_skill.py"; exit 0; }
     exit 1 ;;
esac''',
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
    g = lambda *a: subprocess.run(["git", "-C", str(old), *a], check=True, capture_output=True)
    subprocess.run(["git", "init", "-q", str(old)], check=True)
    g("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "i")
    g("worktree", "add", "-q", str(old / ".claude" / "worktrees" / "w1"))
    g("config", "--local", "core.hooksPath", f"{old}/.git/hooks")
    plist = tmp_path / "agent.plist"
    plist.write_text(f"<string>{old}/.venv/bin/python3</string>\n<string>{old}/runner/app.py</string>\n")
    up = tmp_path / "up"
    up.write_text(str(old))
    e = {**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}", "AOS_PLIST": str(plist), "AOS_WAIT": "3",
         "SHIM_LOG": str(tmp_path / "calls"), "SHIM_UP": str(up)}
    return old, new, plist, up, e


def run(old, new, e):
    return subprocess.run(["sh", str(SCRIPT), str(old), str(new)], env=e, capture_output=True, text=True)


def hooks(repo):
    return subprocess.run(["git", "-C", str(repo), "config", "--local", "--get", "core.hooksPath"],
                          capture_output=True, text=True).stdout.strip()


def assert_back_on_old(old, new, plist, up, before, r):
    assert r.returncode == 1 and "rolled back; runner up on" in r.stdout, r.stdout + r.stderr
    assert old.exists() and not new.exists() and plist.read_text() == before
    assert up.read_text().strip() == str(old)  # the restored runner is the old checkout's
    assert str(new) not in (old / ".venv" / "bin" / "pip").read_text()
    assert hooks(old) == f"{old}/.git/hooks"
    assert subprocess.run(["git", "-C", str(old / ".claude" / "worktrees" / "w1"), "status"],
                          capture_output=True).returncode == 0


def test_moves_repoints_and_restarts(env):
    old, new, plist, up, e = env
    r = run(old, new, e)
    assert r.returncode == 0, r.stdout + r.stderr
    assert not old.exists() and (new / "runner" / "app.py").exists()
    assert str(old) not in plist.read_text() and str(new) in plist.read_text()
    assert str(old) not in (new / ".venv" / "bin" / "pip").read_text()
    assert hooks(new) == f"{new}/.git/hooks" and up.read_text().strip() == str(new)
    assert subprocess.run(["git", "-C", str(new / ".claude" / "worktrees" / "w1"), "status"],
                          capture_output=True).returncode == 0
    assert "DONE" in r.stdout


def test_refusals_change_nothing(env, tmp_path):
    old, new, plist, up, e = env
    before = plist.read_text()
    assert "jobs are running" in run(old, new, {**e, "SHIM_JOBS": '[{"run_id":"x"}]'}).stdout
    assert "processes still use" in run(old, new, {**e, "SHIM_OTHER_AT": str(old)}).stdout
    new.mkdir()
    assert "already exists" in run(old, new, e).stdout
    new.rmdir()
    assert "not an AgenticOS checkout" in run(tmp_path, new, e).stdout
    assert old.exists() and plist.read_text() == before and up.read_text().strip() == str(old)


def test_rolls_back_when_only_the_new_checkout_fails_to_start(env):
    old, new, plist, up, e = env
    before = plist.read_text()
    assert_back_on_old(old, new, plist, up, before, run(old, new, {**e, "SHIM_FAIL_AT": str(new)}))


def test_rolls_back_when_interrupted_after_the_move(env):
    old, new, plist, up, e = env
    before = plist.read_text()
    r = run(old, new, {**e, "SHIM_KILL_AT": str(new)})
    assert "interrupted" in r.stdout
    assert_back_on_old(old, new, plist, up, before, r)


def test_rolls_back_when_a_worktree_cannot_be_repaired(env):
    old, new, plist, up, e = env
    (old / ".claude" / "worktrees" / "w1" / ".git").unlink()  # unrepairable
    before = plist.read_text()
    r = run(old, new, e)
    assert r.returncode == 1 and "rolled back" in r.stdout and old.exists() and not new.exists()
    assert plist.read_text() == before and up.read_text().strip() == str(old)
