#!/bin/sh
# AGE-137: install the ai-memory server used by runner/ai_memory.py, inside this checkout only.
#   sh scripts/install_ai_memory.sh [--force]
# Downloads the pinned-or-latest release for this OS/CPU into .tools/ai-memory/, verifies the
# release's SHA-256, initialises state/ai-memory/ and leaves an `enabled` marker there. No
# LaunchAgent, no harness hooks, no writes outside this checkout. `--force` re-downloads (the
# upgrade path); without it an existing binary is kept. The wiki and its index are never touched.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
DEST="$ROOT/.tools/ai-memory"
DATA="$ROOT/state/ai-memory"
VERSION=${AI_MEMORY_VERSION:-latest}
FORCE=0
[ "${1:-}" = "--force" ] && FORCE=1

say() { echo "[ai-memory] $*"; }

case "$(uname -s):$(uname -m)" in
  Darwin:arm64)  TARGET=macos-aarch64 ;;
  Darwin:x86_64) TARGET=macos-x86_64 ;;
  Linux:aarch64|Linux:arm64) TARGET=linux-aarch64 ;;
  Linux:x86_64|Linux:amd64) TARGET=linux-x86_64 ;;
  *) say "unsupported platform $(uname -s)/$(uname -m); set AI_MEMORY_TARGET to a release target"; exit 1 ;;
esac
TARGET=${AI_MEMORY_TARGET:-$TARGET}

if [ -x "$DEST/ai-memory" ] && [ "$FORCE" -eq 0 ] && [ "$VERSION" = latest ]; then
  say "binary already present: $("$DEST/ai-memory" --version 2>/dev/null || echo unknown)"
else
  TMP=$(mktemp -d "${TMPDIR:-/tmp}/ai-memory.XXXXXX")
  trap 'rm -rf "$TMP"' EXIT INT TERM
  BASE="https://github.com/akitaonrails/ai-memory/releases"
  if [ "$VERSION" = latest ]; then URL="$BASE/latest/download"; else URL="$BASE/download/v$VERSION"; fi
  ASSET="ai-memory-$TARGET.tar.gz"
  say "downloading $ASSET"
  curl -fsSL --max-time 180 "$URL/$ASSET" -o "$TMP/$ASSET"
  curl -fsSL --max-time 60 "$URL/$ASSET.sha256" -o "$TMP/$ASSET.sha256"
  EXPECTED=$(awk 'NR == 1 { print $1 }' "$TMP/$ASSET.sha256")
  if command -v shasum >/dev/null 2>&1; then
    ACTUAL=$(shasum -a 256 "$TMP/$ASSET" | awk '{ print $1 }')
  else
    ACTUAL=$(sha256sum "$TMP/$ASSET" | awk '{ print $1 }')
  fi
  [ -n "$EXPECTED" ] && [ "$EXPECTED" = "$ACTUAL" ] || { say "checksum mismatch; refusing to install"; exit 1; }
  mkdir -p "$DEST"
  tar -xzf "$TMP/$ASSET" -C "$DEST"   # over an existing tree: an upgrade, not a wipe
  say "installed $("$DEST/ai-memory" --version)"
fi

mkdir -p "$DATA"
if [ ! -f "$DATA/config.toml" ]; then
  "$DEST/ai-memory" --data-dir "$DATA" --config "$DATA/config.toml" init >/dev/null
  say "initialised $DATA"
fi
# Explicit opt-in for the runner. The binary alone does not turn capture on, so a checkout that
# happens to have .tools/ never starts a server by accident.
: > "$DATA/enabled"
PY=${AOS_PYTHON:-$ROOT/.venv/bin/python3}
[ -x "$PY" ] || PY=python3
printf '%s\n' "ready. The runner starts the server on first dispatch; check with:" \
  "  $PY runner/ai_memory.py" \
  "  $PY runner/ai_memory.py brief <project> <TICKET>" \
  "Upgrade: sh $0 --force" \
  "Disable: rm $DATA/enabled (or set AGENTIC_OS_AI_MEMORY=0)."
