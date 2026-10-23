"""DeepSeek Harness (`dsh`) CLI helpers: binary, version gate, key, env, NDJSON events.

Pure helpers shared by app.py (dispatch), the DeepSeek backend module (capability check)
and deepseek_monitor.py (balance polling). The API key never goes into argv or logs.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tomllib
from functools import lru_cache
from pathlib import Path

DSH_MIN_VERSION = "0.2.0-rc.2"  # first release with --json and --session-id
# Decided by the 2026-10-14 spike: headless `ask` auto-denies escalation, writes stay in cwd.
DSH_PERMISSION_MODE = "workspace-write"
_DEEPSEEK_CONFIG = Path.home() / ".deepseek" / "config.toml"
_BIN_CANDIDATES = ("/opt/homebrew/bin/dsh", "/usr/local/bin/dsh")


def resolve_bin() -> str | None:
    found = shutil.which("dsh")
    if found:
        return found
    return next((p for p in _BIN_CANDIDATES if Path(p).exists()), None)


def _version_key(text: str) -> tuple | None:
    """Semver sort key; a pre-release sorts before its release (0.2.0-rc.2 < 0.2.0)."""
    m = re.search(r"(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?", text or "")
    if not m:
        return None
    pre = m.group(4)
    pre_key = (1,) if pre is None else (0, *[
        (0, int(p), "") if p.isdigit() else (1, 0, p) for p in pre.split(".")])
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)), pre_key)


@lru_cache(maxsize=8)
def _probe_version(dsh_bin: str, _mtime: float) -> str:
    return subprocess.check_output([dsh_bin, "--version"], text=True,
                                   stderr=subprocess.STDOUT, timeout=30).strip()


def check_version(dsh_bin: str) -> str:
    """Return the version, or raise RuntimeError when it is older than DSH_MIN_VERSION."""
    try:
        version = _probe_version(dsh_bin, Path(dsh_bin).stat().st_mtime)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"dsh version probe failed: {exc}") from exc
    have = _version_key(version)
    if have is None or have < _version_key(DSH_MIN_VERSION):
        raise RuntimeError(f"dsh {version or '?'} too old (need >= {DSH_MIN_VERSION}). "
                           "Upgrade: npm i -g @deepseek-ai/dsh")
    return version


def cli_prefix() -> list[str]:
    """[dsh, --profile, headless]; FileNotFoundError if missing, RuntimeError if too old."""
    dsh_bin = resolve_bin()
    if not dsh_bin:
        raise FileNotFoundError("dsh CLI not found (npm i -g @deepseek-ai/dsh)")
    check_version(dsh_bin)
    return [dsh_bin, "--profile", "headless"]


def resolve_api_key() -> str | None:
    """DEEPSEEK_API_KEY from the environment first, else ~/.deepseek/config.toml api_key."""
    key = (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    if key:
        return key
    try:
        with _DEEPSEEK_CONFIG.open("rb") as f:
            key = str(tomllib.load(f).get("api_key") or "").strip()
    except (OSError, tomllib.TOMLDecodeError):
        return None
    return key or None


def key_fp(key: str | None) -> str | None:
    return hashlib.sha256(key.encode()).hexdigest()[:12] if key else None


def dsh_env(env: dict[str, str]) -> dict[str, str]:
    """Add the API key, permission mode and read-only git hint to a child env (in place, returned)."""
    key = resolve_api_key()
    if key:
        env["DEEPSEEK_API_KEY"] = key
    env["DSH_PERMISSION_MODE"] = DSH_PERMISSION_MODE
    # AGE-138: a ticket worktree's git metadata is outside the workspace-write root. Without this,
    # `git status` refreshes the index and is denied; with it, status/log/diff never write .git.
    env["GIT_OPTIONAL_LOCKS"] = "0"
    return env


class DshRun:
    """Accumulate `dsh --json` NDJSON events into output, tokens, session and errors."""

    def __init__(self) -> None:
        self.session_id: str | None = None
        self.final: str | None = None
        self.input_tokens = 0
        self.output_tokens = 0
        self.usage_complete = True
        self.saw_step_end = False
        self.errors: list[str] = []

    def feed_line(self, line: str) -> dict | None:
        """Parse one line; malformed or non-object lines are ignored (returns None)."""
        try:
            ev = json.loads(line)
        except ValueError:
            return None
        if not isinstance(ev, dict):
            return None
        kind = ev.get("type")
        if kind == "session" and not self.session_id and isinstance(ev.get("sessionId"), str):
            self.session_id = ev["sessionId"]
        elif kind == "final":
            self.final = str(ev.get("text") or "")
        elif kind == "error":
            self.errors.append(str(ev.get("message") or "error"))
        elif kind == "status" and ev.get("phase") == "step_end":
            self.saw_step_end = True
            usage = ev.get("usage")
            if isinstance(usage, dict) and isinstance(usage.get("inputTokens"), int) \
                    and isinstance(usage.get("outputTokens"), int):
                self.input_tokens += usage["inputTokens"]
                self.output_tokens += usage["outputTokens"]
            else:
                self.usage_complete = False
        return ev

    def tokens(self) -> tuple[int | None, int | None]:
        """Summed tokens, or (None, None) when any step lacked usage: never under-report."""
        if not self.saw_step_end or not self.usage_complete:
            return None, None
        return self.input_tokens, self.output_tokens

    def outcome(self, returncode: int | None, stderr: str) -> tuple[bool, str]:
        """ok = exit 0 AND a final event. Error text keeps dsh:-prefixed lines for the retry filter."""
        ok = returncode == 0 and self.final is not None
        if ok:
            return True, ""
        lines = [f"dsh: {msg}" for msg in self.errors]
        lines += [ln for ln in (stderr or "").splitlines() if ln.startswith("dsh:")]
        if self.final is None:
            lines.append("dsh: no final event")
        lines.append(f"dsh: exit {returncode}")
        return False, "\n".join(dict.fromkeys(lines))
