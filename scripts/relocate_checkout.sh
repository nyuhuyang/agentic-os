#!/bin/sh
# Move this AgenticOS checkout to a new folder and repoint everything that hard-codes its path:
# the launchd agent, the venv's script shebangs, the nested git worktrees and core.hooksPath.
#   sh scripts/relocate_checkout.sh OLD NEW
# Run it from a process that can read both folders (macOS privacy rules may block some
# shells). It stops the runner, moves, repairs, restarts, and rolls everything back if the
# runner does not come back on the new path or the script is interrupted. Files outside this
# checkout that mention the old path (~/.claude, ~/.codex) are only reported, never edited.
# Exit: 0 moved, 1 refused or rolled back (old path running again), 2 needs a human.
set -u
OLD=${1:?usage: relocate_checkout.sh OLD NEW}
NEW=${2:?usage: relocate_checkout.sh OLD NEW}
LABEL=com.agenticos.runner
PLIST=${AOS_PLIST:-"$HOME/Library/LaunchAgents/$LABEL.plist"}  # override for tests only
DOMAIN="gui/$(id -u)"
URL=http://127.0.0.1:8510
WAIT=${AOS_WAIT:-40}  # seconds to wait for the runner to answer (tests shorten it)
PHASE=check

say() { echo "[relocate] $*"; }
die() { say "ABORT: $*"; exit 1; }
manual() { say "NEEDS A HUMAN: $*"; exit 2; }
http() { curl -s --connect-timeout 2 -m 5 "$@"; }

[ -f "$OLD/runner/app.py" ] || die "$OLD is not an AgenticOS checkout"
[ -e "$NEW" ] && die "$NEW already exists"
[ -d "$(dirname "$NEW")" ] || die "parent of $NEW does not exist"
[ -f "$PLIST" ] || die "no launchd agent at $PLIST"
case "$NEW/" in "$OLD"/*) die "$NEW is inside $OLD" ;; esac

token=$(http "$URL/" | sed -n 's/.*name="agentic-os-token" content="\([^"]*\)".*/\1/p')
[ -n "$token" ] || die "runner not reachable; start it first so running jobs can be checked"
jobs=$(http -H "X-AgenticOS-Token: $token" "$URL/api/runs?state=running")
[ "$jobs" = "[]" ] || die "jobs are running (or the check failed): $jobs"
others() { pgrep -fl "$1/" | grep -v -e "$1/runner/app.py" -e relocate_checkout.sh; }  # CLI runs, scripts, ...
busy=$(others "$OLD") && die "processes still use $OLD: $busy"

BACKUP=$(mktemp -t agenticos-plist) || die "cannot create a plist backup"
cp "$PLIST" "$BACKUP" && cmp -s "$PLIST" "$BACKUP" || die "plist backup did not verify"
say "plist backup: $BACKUP"

runner_from() { pgrep -f "$1/runner/app.py" >/dev/null; }
wait_down() {
  i=0
  while runner_from "$1"; do i=$((i + 1)); [ $i -gt 30 ] && return 1; sleep 0.5; done
}
wait_up() {  # HTTP 200 from a runner of checkout $1, within ~$WAIT s overall
  i=0
  until [ "$(http -o /dev/null -w '%{http_code}' "$URL/")" = 200 ] && runner_from "$1"; do
    i=$((i + 1)); [ $i -gt "$WAIT" ] && return 1; sleep 1
  done
}
restart_old() {
  cp "$BACKUP" "$PLIST" && launchctl bootstrap "$DOMAIN" "$PLIST" && wait_up "$OLD" \
    && say "runner restarted on $OLD" || manual "runner did not restart on $OLD; plist backup at $BACKUP"
}
repoint() {  # rewrite $1 -> $2 for the checkout now at $2
  grep -rlI --null "$1" "$2/.venv/bin" | xargs -0 sed -i '' "s|$1|$2|g" || return 1
  sed -i '' "s|$1|$2|g" "$2/.venv/pyvenv.cfg" || return 1
  hooks=$(git -C "$2" config --local --get core.hooksPath)
  case "$hooks" in "$1"/*) git -C "$2" config --local core.hooksPath "$2${hooks#"$1"}" || return 1 ;; esac
  for wt in "$2"/.claude/worktrees/*; do
    [ -d "$wt" ] || continue
    git -C "$2" worktree repair "$wt" >/dev/null 2>&1 || return 1
  done
  sed -i '' "s|$1|$2|g" "$PLIST" && plutil -lint "$PLIST" >/dev/null
}
verified() {  # nothing operational in checkout $2 still names $1, and every worktree works
  [ -z "$(grep -rlI "$1" "$2/.venv" 2>/dev/null)" ] || { say "old path left in .venv"; return 1; }
  ! grep -q "$1" "$PLIST" || { say "old path left in the plist"; return 1; }
  ! git -C "$2" config --list --local | grep -q "$1" || { say "old path left in git config"; return 1; }
  git -C "$2" worktree list --porcelain | sed -n 's/^worktree //p' | while read -r wt; do
    case "$wt/" in "$1"/*) say "worktree still at $wt"; exit 1 ;; esac
    git -C "$wt" status --porcelain >/dev/null 2>&1 || { say "worktree broken: $wt"; exit 1; }
  done
}
rollback() {
  PHASE=rollback
  trap '' HUP INT TERM
  say "rolling back: $*"
  launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null
  wait_down "$NEW" || manual "a runner from $NEW is still alive; checkout left at $NEW"
  busy=$(others "$NEW") && manual "processes still use $NEW ($busy); checkout left there"
  mv "$NEW" "$OLD" || manual "could not move $NEW back to $OLD"
  repoint "$NEW" "$OLD" || say "WARNING: repointing back reported an error"
  verified "$NEW" "$OLD" || say "WARNING: the old checkout still names $NEW somewhere"
  restart_old
  say "rolled back; runner up on $OLD"
  exit 1
}
on_signal() {
  case "$PHASE" in
    stopped) say "interrupted before the move"; restart_old; exit 1 ;;
    moved) rollback "interrupted" ;;
    *) exit 1 ;;
  esac
}
trap on_signal HUP INT TERM

PHASE=stopped
launchctl bootout "$DOMAIN/$LABEL" || { PHASE=check; die "could not stop $LABEL"; }
wait_down "$OLD" || { restart_old; die "runner did not stop"; }
busy=$(others "$OLD") && { restart_old; die "processes still use $OLD: $busy"; }
mv "$OLD" "$NEW" || { restart_old; die "mv failed; nothing changed"; }
PHASE=moved
say "moved to $NEW"
repoint "$OLD" "$NEW" || rollback "repoint failed"
verified "$OLD" "$NEW" || rollback "verification failed"
launchctl bootstrap "$DOMAIN" "$PLIST" || rollback "bootstrap failed"
wait_up "$NEW" || rollback "no runner from $NEW answered on $URL"
PHASE=done
trap - HUP INT TERM
git -C "$NEW" worktree list
say "runner up from $NEW"
say "still mention the old path (edit them yourself):"
grep -ln "$OLD" "$HOME/.claude/settings.json" "$HOME/.codex/config.toml" 2>/dev/null | sed 's/^/  /'
rm -f "$BACKUP"
say "DONE"
