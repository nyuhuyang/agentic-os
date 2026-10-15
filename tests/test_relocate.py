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
    [ -n "${SHIM_RECREATE:-}" ] && [ "$at" = "${SHIM_FAIL_AT:-}" ] && mkdir -p "$SHIM_RECREATE"
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
  *) exec "$REAL_PGREP" "$@" ;;  # the real process table for everything but the runner (REL-010)
esac''',
    "plutil": "exit 0",
    # fault injection around the real tools (REAL_* filled in by the fixture)
    "git": '''if [ -n "${SHIM_GIT_FAIL_ONCE:-}" ] && [ ! -e "$SHIM_LOG.gitfail" ] && echo "$*" | grep -q "${SHIM_GIT_FAIL_ON:-worktree list}"; then
  touch "$SHIM_LOG.gitfail"; exit 128
fi
exec "$REAL_GIT" "$@"''',
    "sed": '''if [ -n "${SHIM_SED_FAIL:-}" ] && echo "$*" | grep -qF "$SHIM_SED_FAIL"; then exit 1; fi
exec "$REAL_SED" "$@"''',
    "mv": '''"$REAL_MV" "$@" || exit $?
if [ -n "${SHIM_KILL_AFTER_MV:-}" ] && [ ! -e "$SHIM_LOG.mvkill" ]; then touch "$SHIM_LOG.mvkill"; kill -TERM $PPID; fi''',
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
    import shutil
    real = {f"REAL_{t.upper()}": shutil.which(t) for t in ("git", "sed", "mv", "pgrep")}
    e = {**os.environ, **real, "PATH": f"{bin_}:{os.environ['PATH']}", "AOS_PLIST": str(plist), "AOS_WAIT": "3",
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
    r = run(old, new, e)  # real pgrep: its own lock helper must not count as busy
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
    other = subprocess.Popen(["/usr/bin/python3", "-c", "import time; time.sleep(30)", f"{old}/runner/run_skill.py"])
    try:
        assert "processes still use" in run(old, new, e).stdout
    finally:
        other.kill()
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


def test_an_already_broken_worktree_is_refused_up_front(env):
    old, new, plist, up, e = env
    (old / ".claude" / "worktrees" / "w1" / ".git").unlink()
    before = plist.read_text()
    r = run(old, new, e)
    assert r.returncode == 1 and "worktree already broken" in r.stdout
    assert old.exists() and not new.exists() and plist.read_text() == before
    assert "bootout" not in (Path(e["SHIM_LOG"]).read_text() if Path(e["SHIM_LOG"]).exists() else "")


def test_rolls_back_when_a_worktree_repair_fails(env):
    old, new, plist, up, e = env
    before = plist.read_text()
    r = run(old, new, {**e, "SHIM_GIT_FAIL_ONCE": "1", "SHIM_GIT_FAIL_ON": "worktree repair"})
    assert "repoint failed" in r.stdout
    assert_back_on_old(old, new, plist, up, before, r)


def test_a_running_skill_blocks_the_move(env):
    old, new, plist, up, e = env
    lock = old / "outputs" / "locks" / "maintenance.lock"
    holder = subprocess.Popen(["/usr/bin/python3", "-c", (
        "import fcntl, os, sys, time; os.makedirs(os.path.dirname(sys.argv[1]), exist_ok=True); "
        "f = open(sys.argv[1], 'a'); fcntl.flock(f, fcntl.LOCK_SH); print('x', flush=True); time.sleep(30)"),
        "outputs/locks/maintenance.lock"],
        stdout=subprocess.PIPE, cwd=str(old))  # like `.venv/bin/python3 runner/run_skill.py`: no OLD in argv
    holder.stdout.readline()
    try:
        r = run(old, new, e)
        assert r.returncode == 1 and "a skill run holds the maintenance lock" in r.stdout
        assert old.exists() and up.read_text().strip() == str(old)
    finally:
        holder.kill()


def test_run_skill_refuses_while_maintenance_holds_the_lock(tmp_path, monkeypatch):
    import fcntl
    import sys
    sys.path.insert(0, str(SCRIPT.parents[1] / "runner"))
    import run_skill
    monkeypatch.setattr(run_skill, "LOCKS_DIR", tmp_path)
    with open(tmp_path / "maintenance.lock", "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        assert run_skill._maintenance_shared() is None
    fh = run_skill._maintenance_shared()
    assert fh is not None
    fh.close()


def test_incomplete_reverse_repair_needs_a_human(env):
    old, new, plist, up, e = env
    r = run(old, new, {**e, "SHIM_FAIL_AT": str(new), "SHIM_SED_FAIL": f"s|{new}|{old}|g"})
    assert r.returncode == 2 and "recovery is incomplete" in r.stdout, r.stdout + r.stderr
    assert old.exists() and up.read_text().strip() == str(old)  # the runner was still restarted


def test_failed_inspection_is_not_success(env):
    old, new, plist, up, e = env
    before = plist.read_text()
    r = run(old, new, {**e, "SHIM_GIT_FAIL_ONCE": "1"})
    assert "cannot list worktrees" in r.stdout
    assert_back_on_old(old, new, plist, up, before, r)


def test_interrupt_right_after_the_rename_rolls_back(env):
    old, new, plist, up, e = env
    before = plist.read_text()
    r = run(old, new, {**e, "SHIM_KILL_AFTER_MV": "1"})
    assert "interrupted during the move" in r.stdout
    assert_back_on_old(old, new, plist, up, before, r)


def test_rollback_stops_when_old_was_recreated(env):
    old, new, plist, up, e = env
    r = run(old, new, {**e, "SHIM_FAIL_AT": str(new), "SHIM_RECREATE": str(old)})
    assert r.returncode == 2 and "was recreated meanwhile" in r.stdout
    assert (new / "runner" / "app.py").exists() and not (old / "agentic-os").exists()  # never nested


def test_run_skill_takes_the_lock_before_prompting_and_never_recreates_a_moved_checkout(tmp_path, monkeypatch):
    import builtins
    import fcntl
    import sys
    sys.path.insert(0, str(SCRIPT.parents[1] / "runner"))
    import run_skill
    monkeypatch.setattr(run_skill, "OUTPUTS_DIR", tmp_path / "outputs")
    monkeypatch.setattr(run_skill, "LOCKS_DIR", tmp_path / "outputs" / "locks")
    monkeypatch.setattr(run_skill, "_load_registry", lambda: {"s": {"entrypoint": "x.py", "security": {"confirmation_required": True}}})
    held = []

    def prompt(_):
        with open(tmp_path / "outputs" / "locks" / "maintenance.lock", "a") as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                held.append(False)
            except BlockingIOError:
                held.append(True)
        return "n"
    monkeypatch.setattr(builtins, "input", prompt)
    run_skill.cmd_run("s", [], 0, False, False, False)
    assert held == [True]  # a prompting CLI already blocks a move
    gone = tmp_path / "moved-away"
    monkeypatch.setattr(run_skill, "_SELF", gone / "runner" / "run_skill.py")
    monkeypatch.setattr(run_skill, "OUTPUTS_DIR", gone / "outputs")
    monkeypatch.setattr(run_skill, "LOCKS_DIR", gone / "outputs" / "locks")
    assert run_skill._maintenance_shared() is None and not gone.exists()
