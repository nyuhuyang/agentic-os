#!/bin/sh
# Move this AgenticOS checkout to a new folder and repoint everything that hard-codes its path:
# the launchd agent, the venv's script shebangs and the nested git worktrees.
#   sh scripts/relocate_checkout.sh OLD NEW
# Run it from a process that can read both folders (macOS privacy rules may block some
# shells). It stops the runner, moves, repairs, restarts, and rolls everything back if the
# runner does not come back on the new path. Files outside this checkout that mention the
# old path (~/.claude, ~/.codex) are only reported, never edited.
set -u
OLD=${1:?usage: relocate_checkout.sh OLD NEW}
NEW=${2:?usage: relocate_checkout.sh OLD NEW}
LABEL=com.agenticos.runner
PLIST=${AOS_PLIST:-"$HOME/Library/LaunchAgents/$LABEL.plist"}  # override for tests only
DOMAIN="gui/$(id -u)"
URL=http://127.0.0.1:8510

say() { echo "[relocate] $*"; }
die() { say "ABORT: $*"; exit 1; }

[ -f "$OLD/runner/app.py" ] || die "$OLD is not an AgenticOS checkout"
[ -e "$NEW" ] && die "$NEW already exists"
[ -d "$(dirname "$NEW")" ] || die "parent of $NEW does not exist"
[ -f "$PLIST" ] || die "no launchd agent at $PLIST"
case "$NEW/" in "$OLD"/*) die "$NEW is inside $OLD" ;; esac

token=$(curl -s "$URL/" | sed -n 's/.*name="agentic-os-token" content="\([^"]*\)".*/\1/p')
[ -n "$token" ] || die "runner not reachable; start it first so running jobs can be checked"
jobs=$(curl -s -H "X-AgenticOS-Token: $token" "$URL/api/runs?state=running")
[ "$jobs" = "[]" ] || die "jobs are running: $jobs"

wait_down() {
  i=0
  while pgrep -f "$1/runner/app.py" >/dev/null; do
    i=$((i + 1)); [ $i -gt 30 ] && return 1; sleep 0.5
  done
}
wait_up() {
  i=0
  until [ "$(curl -s -o /dev/null -w '%{http_code}' "$URL/")" = 200 ]; do
    i=$((i + 1)); [ $i -gt 60 ] && return 1; sleep 0.5
  done
}
repoint() {  # $1 -> $2 inside the checkout at $2
  grep -rlI --null "$1" "$2/.venv/bin" | xargs -0 sed -i '' "s|$1|$2|g"
  sed -i '' "s|$1|$2|g" "$2/.venv/pyvenv.cfg"
  for wt in "$2"/.claude/worktrees/*; do [ -d "$wt" ] && git -C "$2" worktree repair "$wt"; done
  sed -i '' "s|$1|$2|g" "$PLIST"
  plutil -lint "$PLIST" >/dev/null || return 1
}
rollback() {
  say "rolling back: $*"
  launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null; wait_down "$NEW"
  mv "$NEW" "$OLD" && repoint "$NEW" "$OLD"
  cp "$BACKUP" "$PLIST"
  launchctl bootstrap "$DOMAIN" "$PLIST"
  wait_up && say "rolled back; runner up on $OLD" || say "rolled back, but the runner did not start: check $PLIST"
  exit 1
}

BACKUP=$(mktemp -t agenticos-plist)
cp "$PLIST" "$BACKUP"
say "plist backup: $BACKUP"

launchctl bootout "$DOMAIN/$LABEL" || die "could not stop $LABEL"
wait_down "$OLD" || { launchctl bootstrap "$DOMAIN" "$PLIST"; die "runner did not stop"; }
mv "$OLD" "$NEW" || { launchctl bootstrap "$DOMAIN" "$PLIST"; die "mv failed; nothing changed"; }
say "moved to $NEW"
repoint "$OLD" "$NEW" || rollback "repoint failed"
left=$(grep -rlI "$OLD" "$NEW/.venv" "$PLIST" 2>/dev/null)
[ -z "$left" ] || rollback "old path still in: $left"
launchctl bootstrap "$DOMAIN" "$PLIST" || rollback "bootstrap failed"
wait_up || rollback "runner did not answer on $URL"
pgrep -f "$NEW/runner/app.py" >/dev/null || rollback "the answering runner is not the new checkout"
git -C "$NEW" worktree list
say "runner up from $NEW"
say "still mention the old path (edit them yourself):"
grep -ln "$OLD" "$HOME/.claude/settings.json" "$HOME/.codex/config.toml" 2>/dev/null | sed 's/^/  /'
say "DONE"
