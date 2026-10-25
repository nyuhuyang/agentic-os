"""scripts/relocate_checkout.sh with launchctl/curl/pgrep/plutil shimmed: success, refusals,
rollback after a failed start, after an interrupt, and after a broken worktree."""

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "relocate_checkout.sh"

# An outer DSH Seatbelt hides another process's argv from the shell script's pgrep.
outer_sandbox = pytest.mark.skipif(bool(os.environ.get("AGENTICOS_DSH_SANDBOX")),
                                   reason="process arguments are hidden by the outer sandbox")

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
  *api/maintenance*) echo "curl maintenance $*" >> "$SHIM_LOG"
    case "$*" in *'"on": false'*) m=false ;; *) m=true ;; esac
    [ -n "${SHIM_GATE_TIMEOUT:-}" ] && [ "$m" = true ] && exit 28  # closed server-side, answer lost
    echo "{\\"inflight\\":${SHIM_INFLIGHT:-0},\\"maintenance\\":$m}" ;;
  *api/runs*) echo "${SHIM_JOBS:-[]}" ;;
  *%{http_code}*) [ -s "$SHIM_UP" ] && echo 200 || echo 000 ;;
  *) [ -s "$SHIM_UP" ] && echo '<meta name="agentic-os-token" content="tok">' ;;
esac''',
    # runner patterns are matched as the regexes they are, against the "up" runner and an
    # optional look-alike runner (BUILD-002); everything else uses the real process table
    "pgrep": '''pat=$2
case "$pat" in
  */runner/app*py) for c in "$(cat "$SHIM_UP" 2>/dev/null)" "${SHIM_LOOKALIKE:-}"; do
                     [ -n "$c" ] && printf '%s/runner/app.py' "$c" | grep -qE "$pat" && exit 0
                   done
                   exit 1 ;;
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
    # python3: the real one; after the first directory rename it can TERM the script
    "python3": '''/usr/bin/python3 "$@" || exit $?
case "$*" in *os.rename*)
  if [ -n "${SHIM_KILL_AFTER_MV:-}" ] && [ ! -e "$SHIM_LOG.mvkill" ]; then touch "$SHIM_LOG.mvkill"; kill -TERM $PPID; fi ;;
esac''',
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
    (old / "scripts").mkdir()
    (old / "scripts" / "maintenance_lock.py").write_text((SCRIPT.parent / "maintenance_lock.py").read_text())
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
         "AOS_PYTHON": str(bin_ / "python3"),
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


@outer_sandbox
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
        assert r.returncode == 1 and "holds the maintenance lock" in r.stdout
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


def test_run_skill_never_recreates_a_checkout_moved_mid_acquire(tmp_path, monkeypatch):
    """The checkout is renamed after run_skill saw it but before it creates the lock folder."""
    import pathlib
    import sys
    sys.path.insert(0, str(SCRIPT.parents[1] / "runner"))
    import run_skill
    old = tmp_path / "old"
    (old / "runner").mkdir(parents=True)
    (old / "runner" / "run_skill.py").write_text("")
    monkeypatch.setattr(run_skill, "_SELF", old / "runner" / "run_skill.py")
    monkeypatch.setattr(run_skill, "OUTPUTS_DIR", old / "outputs")
    monkeypatch.setattr(run_skill, "LOCKS_DIR", old / "outputs" / "locks")
    real_mkdir = pathlib.Path.mkdir
    moved = []

    def mkdir(self, *a, **k):
        if not moved:
            moved.append(1)
            old.rename(tmp_path / "new")  # the relocation lands right here
        return real_mkdir(self, *a, **k)
    monkeypatch.setattr(pathlib.Path, "mkdir", mkdir)
    assert run_skill._maintenance_shared() is None
    assert not old.exists() and (tmp_path / "new" / "runner").is_dir()


@pytest.mark.parametrize("bad", ["agentic-os&x", "agentic-os|x", "agentic os"])
def test_paths_with_pattern_characters_are_refused_up_front(env, bad):
    old, new, plist, up, e = env
    before = plist.read_text()
    r = run(old, new.parent / bad, e)
    assert r.returncode == 1 and "paths may only use" in r.stdout
    assert old.exists() and plist.read_text() == before


def test_a_dotted_path_is_replaced_literally(env):
    old, new, plist, up, e = env
    other = str(old).replace("agentic-os", "agenticXos")  # what an unescaped "." would also match
    pip = old / ".venv" / "bin" / "pip"
    pip.write_text(pip.read_text() + f"# keep {other}\n")
    dotted = new.parent / "agentic.os"
    r = run(old, dotted, e)
    assert r.returncode == 0, r.stdout + r.stderr
    assert f"keep {other}" in (dotted / ".venv" / "bin" / "pip").read_text()


def test_another_filesystem_is_refused(env, monkeypatch):
    old, new, plist, up, e = env
    r = run(old, Path("/dev/fd/agentic-os"), e)  # devfs: never the checkout's filesystem
    assert r.returncode == 1 and ("another filesystem" in r.stdout or "parent of" in r.stdout)
    assert old.exists()


def test_runs_in_flight_refuse_the_move_and_reopen_admission(env):
    old, new, plist, up, e = env
    r = run(old, new, {**e, "SHIM_INFLIGHT": "1"})
    assert r.returncode == 1 and "runs are in flight" in r.stdout
    calls = Path(e["SHIM_LOG"]).read_text()
    assert '{"on": true}' in calls and '{"on": false}' in calls and "bootout" not in calls
    assert old.exists()


def test_rollback_ignores_a_look_alike_runner(env, tmp_path):
    old, new, plist, up, e = env
    dotted = new.parent / "agentic.os"
    look = str(dotted).replace("agentic.os", "agenticXos")  # what an unescaped pattern would match
    before = plist.read_text()
    r = run(old, dotted, {**e, "SHIM_FAIL_AT": str(dotted), "SHIM_LOOKALIKE": look})
    assert r.returncode == 1 and "rolled back; runner up on" in r.stdout, r.stdout
    assert old.exists() and plist.read_text() == before


def test_dotted_old_is_replaced_literally(env, tmp_path):
    old, new, plist, up, e = env
    dotted_old = old.parent / "agentic.os"
    old.rename(dotted_old)
    subprocess.run(["git", "-C", str(dotted_old), "worktree", "repair", str(dotted_old / ".claude" / "worktrees" / "w1")], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(dotted_old), "config", "--local", "core.hooksPath", f"{dotted_old}/.git/hooks"], check=True)
    pip = dotted_old / ".venv" / "bin" / "pip"
    look = str(dotted_old).replace("agentic.os", "agenticXos")
    pip.write_text(f"#!{dotted_old}/.venv/bin/python3\n# keep {look}\n")
    (dotted_old / ".venv" / "pyvenv.cfg").write_text(f"command = python3 -m venv {dotted_old}/.venv\n")
    plist.write_text(plist.read_text().replace(str(old), str(dotted_old)))
    up.write_text(str(dotted_old))
    r = run(dotted_old, new, e)
    assert r.returncode == 0, r.stdout + r.stderr
    text = (new / ".venv" / "bin" / "pip").read_text()
    assert f"#!{new}/.venv/bin/python3" in text and f"keep {look}" in text


def test_a_symlinked_parent_on_another_filesystem_is_refused(env, tmp_path):
    old, new, plist, up, e = env
    (tmp_path / "ext").symlink_to("/dev")  # looks local, resolves to devfs
    r = run(old, tmp_path / "ext" / "agentic-os", e)
    assert r.returncode == 1 and "another filesystem" in r.stdout and old.exists()


def test_a_lost_gate_answer_still_reopens_admission(env):
    old, new, plist, up, e = env
    r = run(old, new, {**e, "SHIM_GATE_TIMEOUT": "1"})
    assert r.returncode == 1 and "no answer" in r.stdout and "WARNING" not in r.stdout
    calls = Path(e["SHIM_LOG"]).read_text()
    assert calls.index('{"on": true}') < calls.index('{"on": false}') and "bootout" not in calls


def test_a_second_relocation_is_refused_without_touching_the_gate(env):
    old, new, plist, up, e = env
    lock = old / "outputs" / "locks" / "maintenance.lock"
    holder = subprocess.Popen(["/usr/bin/python3", "-c", (
        "import fcntl, os, sys, time; os.makedirs(os.path.dirname(sys.argv[1]), exist_ok=True); "
        "f = open(sys.argv[1], 'a'); fcntl.flock(f, fcntl.LOCK_EX); print('x', flush=True); time.sleep(30)"),
        "outputs/locks/maintenance.lock"], stdout=subprocess.PIPE, cwd=str(old))  # attempt A
    holder.stdout.readline()
    try:
        r = run(old, new, e)  # attempt B
        assert r.returncode == 1 and "another relocation holds the maintenance lock" in r.stdout
        log = Path(e["SHIM_LOG"])
        assert not log.exists() or "maintenance" not in log.read_text()  # B never touched A's gate
    finally:
        holder.kill()


def test_an_early_signal_reopens_admission(env, tmp_path):
    old, new, plist, up, e = env
    # TERM as soon as the gate closes (from the curl shim), i.e. before the runner is stopped
    shim = Path(e["PATH"].split(":")[0]) / "curl"
    shim.write_text(shim.read_text().replace(
        'echo "{\\"inflight\\"', '[ "$m" = true ] && [ -z "${SHIM_SENT:-}" ] && kill -TERM $PPID; echo "{\\"inflight\\"'))
    r = run(old, new, e)
    calls = Path(e["SHIM_LOG"]).read_text()
    assert r.returncode == 1 and '{"on": false}' in calls and "bootout" not in calls and old.exists()


def test_lock_helper_never_recreates_a_checkout_moved_before_it_starts(tmp_path):
    """Attempt B checked OLD, then attempt A renamed it before B's helper ran."""
    old = tmp_path / "old"
    (old / "outputs").mkdir(parents=True)
    inode = old.stat().st_ino
    old.rename(tmp_path / "new")
    out = subprocess.run(["/usr/bin/python3", str(SCRIPT.parent / "maintenance_lock.py"), str(old), str(inode),
                          str(os.getpid())], capture_output=True, text=True)
    assert out.stdout.strip() == "busy" and not old.exists()
    old.mkdir()  # a different folder now at the old path
    out = subprocess.run(["/usr/bin/python3", str(SCRIPT.parent / "maintenance_lock.py"), str(old), str(inode),
                          str(os.getpid())], capture_output=True, text=True)
    assert out.stdout.strip() == "busy" and not (old / "outputs").exists()


def test_a_destination_created_before_the_rename_is_never_nested_into(env, monkeypatch):
    old, new, plist, up, e = env
    # the destination appears (non-empty) right as the runner stops, i.e. after the preflight
    shim = Path(e["PATH"].split(":")[0]) / "launchctl"
    shim.write_text(shim.read_text().replace('  bootout) rm -f "$SHIM_UP" ;;',
                                             f'  bootout) rm -f "$SHIM_UP"; mkdir -p "{new}/squatter" ;;'))
    before = plist.read_text()
    r = run(old, new, e)
    assert r.returncode == 1 and "rename failed" in r.stdout
    assert (old / "runner" / "app.py").exists() and not (new / "agentic-os").exists()  # never nested
    assert plist.read_text() == before and up.read_text().strip() == str(old)


