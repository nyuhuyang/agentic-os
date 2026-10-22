#!/usr/bin/env python3
"""Swap the machine's Claude Code login between saved accounts (AGE-125).

One-time setup, per account:
    claude auth login                         # sign in as account A (any terminal)
    .venv/bin/python3 runner/claude_account.py save a
    claude auth login                         # sign in as account B
    .venv/bin/python3 runner/claude_account.py save b

Daily swap (or use the account picker next to "Claude" on the dashboard):
    .venv/bin/python3 runner/claude_account.py use b
    .venv/bin/python3 runner/claude_account.py list

No runner restart is needed: every run spawns a fresh `claude`, which reads the keychain login.
Claude processes already running keep the old account until they exit. A snapshot left unused
for about four weeks expires; then `claude auth login` once and `save` that label again.

Credential snapshots live in the login keychain (service "agenticos-claude-account"); labels
and identities (email, ~/.claude.json oauthAccount) in ~/.agentic-os/claude-accounts.json (0600).
Tokens never reach argv, logs or output.
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

LIVE_SERVICE = "Claude Code-credentials"
SNAP_SERVICE = "agenticos-claude-account"
PROFILE_API = "https://api.anthropic.com/api/oauth/profile"
STATE_DIR = Path.home() / ".agentic-os"
INDEX = STATE_DIR / "claude-accounts.json"
LOCK = STATE_DIR / "claude-account.lock"
CLAUDE_JSON = Path.home() / ".claude.json"
OVERRIDE_ENV = ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY", "CLAUDE_CONFIG_DIR")
_LABEL = re.compile(r"[A-Za-z0-9_-]{1,32}")


class AccountError(Exception):
    pass


# ── Keychain ─────────────────────────────────────────────────────────────────

def _security(args: list[str], stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["security", *args], input=stdin, capture_output=True, text=True, timeout=15)


def _kc_read(service: str, account: str | None = None) -> str | None:
    """Secret, or None when the item does not exist. Any other failure raises: never guess."""
    args = ["find-generic-password", "-s", service] + (["-a", account] if account else []) + ["-w"]
    out = _security(args)
    if out.returncode == 44:  # errSecItemNotFound
        return None
    if out.returncode != 0:
        raise AccountError(f"keychain read failed for {service!r} (exit {out.returncode})")
    return out.stdout.rstrip("\n")


def _kc_write(service: str, account: str, secret: str) -> None:
    """Write through `security -i` stdin with hex data, so the secret never sits on argv.
    ponytail: `security -i` truncates lines past ~4 KB, so secrets cap at ~1.9 KB (a login is ~0.6 KB)."""
    if len(secret.encode()) > 1900:
        raise AccountError("credential blob too large for a stdin keychain write")
    q = lambda s: '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    line = f"add-generic-password -U -a {q(account)} -s {q(service)} -X {secret.encode().hex()}\n"
    out = _security(["-i"], stdin=line)
    if out.returncode != 0 or _kc_read(service, account) != secret:
        raise AccountError(f"keychain write failed for {service!r}")


def _live_account() -> str:
    """Account attribute of the existing live item, so -U updates it instead of adding a twin."""
    out = _security(["find-generic-password", "-s", LIVE_SERVICE])
    m = re.search(r'"acct"<blob>="([^"]*)"', out.stdout)
    return m.group(1) if m else os.environ.get("USER", "")


def _snapshot(label: str) -> dict | None:
    """Saved credential blob of LABEL, or None."""
    return _parse_blob(_kc_read(SNAP_SERVICE, label))


def _save_snapshot(label: str, blob: dict) -> None:
    _kc_write(SNAP_SERVICE, label, json.dumps(blob, separators=(",", ":")))


# ── Files ────────────────────────────────────────────────────────────────────

def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json_atomic(path: Path, data: dict, mode: int) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def _index() -> dict:
    return {k: v for k, v in _read_json(INDEX).items() if _LABEL.fullmatch(k) and isinstance(v, dict)}


def swap_generation() -> int:
    """Changes on every save/use, from any process: the dashboard drops cached usage on change."""
    try:
        return INDEX.stat().st_mtime_ns
    except OSError:
        return 0


@contextlib.contextmanager
def _locked():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOCK, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


# ── Ownership ────────────────────────────────────────────────────────────────

def _oauth(blob: dict) -> dict:
    o = blob.get("claudeAiOauth")
    return o if isinstance(o, dict) else {}


def _fetch_profile(access_token: str) -> dict | None:
    req = urllib.request.Request(PROFILE_API, headers={"Authorization": f"Bearer {access_token}"})
    try:
        with urllib.request.urlopen(req, timeout=6) as r:
            data = json.loads(r.read().decode("utf-8"))
    except (OSError, ValueError):
        return None
    uuid = ((data or {}).get("account") or {}).get("uuid") if isinstance(data, dict) else None
    return data if isinstance(uuid, str) and uuid else None


def _profile_of(blob: dict) -> dict | None:
    o = _oauth(blob)
    token, expires = o.get("accessToken"), o.get("expiresAt") or 0
    if not isinstance(token, str) or not token or expires <= time.time() * 1000 + 60_000:
        return None
    return _fetch_profile(token)


def _parse_blob(raw: str | None) -> dict | None:
    try:
        blob = json.loads(raw) if raw else None
    except ValueError:
        return None
    return blob if isinstance(blob, dict) and _oauth(blob).get("refreshToken") else None


def _live_blob() -> dict | None:
    return _parse_blob(_kc_read(LIVE_SERVICE))


def _owner(blob: dict | None, idx: dict, snaps: dict) -> str | None:
    """Label owning the live login: refresh-token match, else the profile API. Never oauthAccount."""
    if not blob:
        return None
    rt = _oauth(blob).get("refreshToken")
    for label, snap in snaps.items():
        if rt and snap and _oauth(snap).get("refreshToken") == rt:
            return label
    profile = _profile_of(blob)
    uuid = profile["account"]["uuid"] if profile else None
    return next((label for label, meta in idx.items() if uuid and meta.get("uuid") == uuid), None)


def _check_env() -> None:
    hit = [k for k in OVERRIDE_ENV if os.environ.get(k)]
    if hit:
        raise AccountError(f"{', '.join(hit)} set: Claude would not use the keychain login; unset it first")


def _check_label(label: str) -> None:
    if not isinstance(label, str) or not _LABEL.fullmatch(label):
        raise AccountError("label must be 1-32 letters, digits, '-' or '_'")


# ── Commands ─────────────────────────────────────────────────────────────────

def save(label: str) -> dict:
    _check_env()
    _check_label(label)
    with _locked():
        blob = _live_blob()
        if not blob:
            raise AccountError("not logged in: run `claude auth login` first")
        profile = _profile_of(blob)
        if not profile:
            raise AccountError("could not verify the live login with Anthropic; run any `claude` command and retry")
        acct, org = profile["account"], profile.get("organization") or {}
        uuid, email = acct["uuid"], acct.get("email") or ""
        idx = _index()
        for other, meta in idx.items():
            if other != label and meta.get("uuid") == uuid:
                raise AccountError(f"{email or uuid} is already saved as {other!r}")
        if label in idx and idx[label].get("uuid") != uuid:
            raise AccountError(f"{label!r} belongs to {idx[label].get('email')}; pick another label")
        live_meta = _read_json(CLAUDE_JSON).get("oauthAccount")
        if not (isinstance(live_meta, dict) and live_meta.get("accountUuid") == uuid):
            live_meta = {"accountUuid": uuid, "emailAddress": email, "displayName": acct.get("display_name"),
                         "organizationUuid": org.get("uuid"), "organizationName": org.get("name")}
        _save_snapshot(label, blob)
        idx[label] = {"uuid": uuid, "email": email, "oauthAccount": live_meta}
        _write_json_atomic(INDEX, idx, 0o600)
    return {"ok": True, "label": label, "email": email}


def _set_oauth_account(meta: dict) -> None:
    """Replace oauthAccount in ~/.claude.json without losing a concurrent Claude Code write:
    re-check the file is unchanged right before the replace, retry from fresh content.
    ponytail: a microsecond window remains; Claude Code has no lock to join."""
    for _ in range(5):
        before = CLAUDE_JSON.stat()
        cfg = json.loads(CLAUDE_JSON.read_text(encoding="utf-8"))
        if not isinstance(cfg, dict):
            raise ValueError(f"{CLAUDE_JSON} is not a JSON object")
        cfg["oauthAccount"] = meta
        now = CLAUDE_JSON.stat()
        if (now.st_mtime_ns, now.st_size, now.st_ino) == (before.st_mtime_ns, before.st_size, before.st_ino):
            _write_json_atomic(CLAUDE_JSON, cfg, before.st_mode & 0o777)
            return
        time.sleep(0.05)
    raise OSError(f"{CLAUDE_JSON} kept changing; left as is")


def _running_claude() -> int:
    out = subprocess.run(["pgrep", "-x", "claude"], capture_output=True, text=True, timeout=5)
    return len(out.stdout.split())


def use(label: str, force: bool = False) -> dict:
    _check_env()
    _check_label(label)
    warnings: list[str] = []
    with _locked():
        idx = _index()
        if label not in idx:
            raise AccountError(f"no saved account {label!r}; saved: {', '.join(idx) or 'none'}")
        snaps = {name: _snapshot(name) for name in idx}
        if not snaps[label] or not isinstance(idx[label].get("oauthAccount"), dict):
            raise AccountError(f"snapshot {label!r} is unreadable; log in and `save {label}` again")
        raw = _kc_read(LIVE_SERVICE)  # None only when no login exists at all: nothing to lose
        blob = _parse_blob(raw)
        owner = _owner(blob, idx, snaps)
        if raw is not None and owner is None:
            if not force:
                raise AccountError("the current login is not a saved account (or could not be verified); "
                                   "`save <label>` it first, or pass --force to discard it")
            warnings.append("current login was not saved and has been discarded")
        if owner:
            snaps[owner] = blob  # keep its rotated refresh token; its verified identity stays in the index
            _save_snapshot(owner, blob)
        _kc_write(LIVE_SERVICE, _live_account(), json.dumps(snaps[label], separators=(",", ":")))
        try:
            _set_oauth_account(idx[label]["oauthAccount"])
        except (OSError, ValueError) as exc:
            warnings.append(f"`claude auth status` may show the old email: {exc}")
        os.utime(INDEX)  # bump swap_generation(), even for a repair of the same label
    running = _running_claude()
    if running:
        warnings.append(f"{running} running claude process(es) keep the old account until they exit")
    return {"ok": True, "label": label, "email": idx[label].get("email"), "warnings": warnings}


def accounts() -> dict:
    idx = _index()
    if not idx:
        return {"accounts": [], "active": None}
    snaps = {name: _snapshot(name) for name in idx}
    return {"accounts": [{"label": k, "email": v.get("email")} for k, v in idx.items()],
            "active": _owner(_live_blob(), idx, snaps)}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("save", help="save the current login under LABEL").add_argument("label")
    u = sub.add_parser("use", help="switch the login to LABEL")
    u.add_argument("label")
    u.add_argument("--force", action="store_true", help="discard an unsaved current login")
    sub.add_parser("list", help="saved accounts; * marks the active one")
    a = p.parse_args(argv)
    try:
        if a.cmd == "save":
            r = save(a.label)
            print(f"saved {r['label']} ({r['email']})")
        elif a.cmd == "use":
            r = use(a.label, a.force)
            print(f"now using {r['label']} ({r['email']})")
            for w in r["warnings"]:
                print(f"warning: {w}", file=sys.stderr)
        else:
            r = accounts()
            for acc in r["accounts"]:
                print(f"{'*' if acc['label'] == r['active'] else ' '} {acc['label']}  {acc['email']}")
            if not r["accounts"]:
                print("no saved accounts; see --help")
    except AccountError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
