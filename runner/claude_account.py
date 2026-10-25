#!/usr/bin/env python3
"""Use one isolated Claude Code configuration directory per subscription account (AGE-125).

Why: Claude Code keeps an account's OAuth credential in the login keychain, keyed by the
configuration directory. Sharing one directory (the default) means every signed-in process shares
one refresh token, and refresh tokens are single-use — a long-lived session rotates the token and
strands any copy. This module gives each account its own directory
(~/.agentic-os/claude-accounts/<label>), so Claude owns that login's refresh lifecycle and a switch
only changes which directory new runs use. Nothing secret is copied, and no runner restart is
needed.

One-time setup, per account (needs the browser once per account):
    .venv/bin/python3 runner/claude_account.py login nyu
    .venv/bin/python3 runner/claude_account.py login rancho

Daily swap (or use the account picker next to "Claude" on the dashboard):
    .venv/bin/python3 runner/claude_account.py use rancho
    .venv/bin/python3 runner/claude_account.py list
    .venv/bin/python3 runner/claude_account.py status

Setup details:
    - `login <label> [--email ADDRESS]` creates the directory, shares sessions/skills/settings from
      ~/.claude by symlink, runs `claude auth login` inside it, verifies the result with
      `claude auth status --json`, and records the email. The first account becomes active.
    - `save <label>` records a login that was already completed in that account's directory
      (printing `status` shows the path) without opening a browser.
    - `use <label>` changes the selector only. Running Claude processes keep the account they
      started with; a terminal tab opened earlier keeps its account too. `claude` below resolves the
      selector per invocation.
    - `claude [args...]` execs the active account's Claude. To make interactive shells follow
      switches: alias claude='python3 /path/to/runner/claude_account.py claude'
    - `list` and `status` never print a token.

Accounts saved by the retired snapshot design (2026-10-21) are inert: their index shape is ignored
and their keychain items are left untouched. Re-run `login <label>` once per account. To remove an
old item by hand (it is a dead credential):
    security delete-generic-password -s agenticos-claude-account -a <label>
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

STATE_DIR = Path.home() / ".agentic-os"
ACCOUNTS_ROOT = STATE_DIR / "claude-accounts"
INDEX = STATE_DIR / "claude-accounts.json"
LOCK = STATE_DIR / "claude-account.lock"
HOME_CLAUDE = Path.home() / ".claude"
HOME_CLAUDE_JSON = Path.home() / ".claude.json"
DEFAULT_SERVICE = "Claude Code-credentials"
# Names that must stay per-account: the config file carries this account's oauthAccount, the
# credentials file is the non-keychain fallback, and backups belong to that config file.
PER_ACCOUNT = frozenset({".claude.json", ".claude.json.lock", ".credentials.json", "backups"})
# Stores every account shares. They are created in ~/.claude before the first account links them;
# otherwise Claude would create its own copy inside one account and it would not cross accounts
# (sessions, skills, plugins, agent/command definitions, hooks, output styles, todo state).
SHARED_DIRS = ("projects", "skills", "plugins", "commands", "agents", "hooks", "output-styles", "todos")
SHARED_NAMES = (*SHARED_DIRS, "settings.json", "CLAUDE.md")
# These make Claude ignore or relocate the directory's login, so a switch would silently do nothing.
OVERRIDE_ENV = (
    "CLAUDE_CODE_OAUTH_TOKEN",
    "ANTHROPIC_API_KEY",
    "CLAUDE_SECURESTORAGE_CONFIG_DIR",
    "CLAUDE_CODE_CUSTOM_OAUTH_URL",
    "CLAUDE_CODE_OAUTH_CLIENT_ID",
)
_LABEL = re.compile(r"[A-Za-z0-9_-]{1,32}")
_LOG = logging.getLogger(__name__)


class AccountError(Exception):
    pass


# ── Naming and storage ───────────────────────────────────────────────────────

def normalize_dir(value: str | Path) -> str:
    """The exact string Claude Code hashes: absolute, NFC-normalized, symlinks not resolved."""
    text = unicodedata.normalize("NFC", str(value))
    if not os.path.isabs(text):
        raise AccountError(f"configuration directory must be absolute: {text!r}")
    return text


def keychain_service(config_dir: str | Path) -> str:
    """Claude Code's keychain service for CONFIG_DIR (2.1.309 `vj()`): bare name only for the
    default directory, else a sha256 suffix of the environment value."""
    digest = hashlib.sha256(normalize_dir(config_dir).encode("utf-8")).hexdigest()[:8]
    return f"{DEFAULT_SERVICE}-{digest}"


def _security(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["security", *args], capture_output=True, text=True, timeout=15)


def _kc_read(service: str) -> str | None:
    """Secret, or None when the item does not exist. Any other failure raises: never guess."""
    try:
        out = _security(["find-generic-password", "-s", service, "-w"])
    except (OSError, subprocess.SubprocessError) as exc:  # missing/locked binary, timeout
        raise AccountError(f"could not read the keychain: {exc}") from exc
    if out.returncode == 44:  # errSecItemNotFound
        return None
    if out.returncode != 0:
        raise AccountError(f"keychain read failed for {service!r} (exit {out.returncode})")
    return out.stdout.rstrip("\n")


def _parse_blob(raw: str | None) -> dict | None:
    try:
        blob = json.loads(raw) if raw else None
    except ValueError:
        return None
    return blob if isinstance(blob, dict) else None


def _oauth(blob: dict | None) -> dict:
    oauth = (blob or {}).get("claudeAiOauth")
    return oauth if isinstance(oauth, dict) else {}


def _credential_raw(config_dir: Path) -> tuple[str | None, str]:
    """(raw credential, source) for CONFIG_DIR: keychain first, then Claude's plaintext fallback.

    A keychain *failure* (not "item missing") still tries the file: Claude itself falls back to a
    plaintext store when keychain storage is unavailable. The error is raised only when neither
    source exists, so `status` can distinguish "unreadable" from "absent"."""
    failure: AccountError | None = None
    try:
        raw = _kc_read(keychain_service(config_dir))
        if raw is not None:
            return raw, "keychain"
    except AccountError as exc:
        failure = exc
    path = config_dir / ".credentials.json"
    try:
        return path.read_text(encoding="utf-8"), "file"
    except OSError:
        if failure is not None:
            raise failure
        return None, "none"


def credentials(config_dir: str | Path) -> dict | None:
    """Parsed credential blob for CONFIG_DIR, read-only. None when there is no readable login."""
    raw, _ = _credential_raw(Path(config_dir))
    return _parse_blob(raw)


# ── Index (the selector) ─────────────────────────────────────────────────────

def _empty_index() -> dict:
    return {"active": None, "accounts": {}}


def _read_index() -> dict:
    try:
        data = json.loads(INDEX.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _empty_index()
    if not isinstance(data, dict) or not isinstance(data.get("accounts"), dict):
        return _empty_index()  # retired flat snapshot index: ignored, never rewritten as-is
    accounts = {k: v for k, v in data["accounts"].items()
                if isinstance(k, str) and _LABEL.fullmatch(k) and isinstance(v, dict)}
    active = data.get("active") if data.get("active") in accounts else None
    return {"active": active, "accounts": accounts}


def legacy_index() -> bool:
    """True when the file on disk is the retired snapshot index, so the CLI can explain it."""
    try:
        data = json.loads(INDEX.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and "accounts" not in data and bool(data)


def _write_index(index: dict) -> None:
    INDEX.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=INDEX.parent, prefix=f".{INDEX.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(index, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, INDEX)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


@contextlib.contextmanager
def _locked():
    INDEX.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCK, "a", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def swap_generation() -> int:
    """Changes on every save/use, from any process: the dashboard drops cached usage on change."""
    try:
        return INDEX.stat().st_mtime_ns
    except OSError:
        return 0


def accounts() -> dict:
    """Labels, emails and the active label. Pure index read: no keychain call, no subprocess."""
    index = _read_index()
    return {"accounts": [{"label": label, "email": meta.get("email") or ""}
                         for label, meta in index["accounts"].items()],
            "active": index["active"]}


def active_account() -> tuple[str | None, dict | None]:
    index = _read_index()
    label = index["active"]
    return (label, index["accounts"].get(label)) if label else (None, None)


# ── Account directories ──────────────────────────────────────────────────────

def _check_label(label: str) -> None:
    if not isinstance(label, str) or not _LABEL.fullmatch(label):
        raise AccountError("label must be 1-32 letters, digits, '-' or '_'")


def account_dir(label: str) -> Path:
    _check_label(label)
    return ACCOUNTS_ROOT / label


def local_only(config_dir: Path) -> list[str]:
    """Real entries that shadow a shared name (or a store that must be shared), for `status`."""
    found = []
    with contextlib.suppress(OSError):
        for name in sorted(os.listdir(config_dir)):
            if name in PER_ACCOUNT:
                continue
            entry = config_dir / name
            if entry.is_symlink():
                continue
            if name in SHARED_NAMES or (HOME_CLAUDE / name).exists():
                found.append(name)
    return found


def _ensure_canonical() -> None:
    """Create the shared stores that must be shared from the first account onwards."""
    HOME_CLAUDE.mkdir(mode=0o700, parents=True, exist_ok=True)
    for name in SHARED_DIRS:
        (HOME_CLAUDE / name).mkdir(mode=0o700, exist_ok=True)
    for name, seed in (("settings.json", "{}\n"), ("CLAUDE.md", "")):
        path = HOME_CLAUDE / name
        if not path.exists() and not path.is_symlink():  # never overwrite the user's file
            path.write_text(seed, encoding="utf-8")


def _adopt_local(config_dir: Path, name: str) -> bool:
    """Move an account-local shared store into ~/.claude and link it back (same filesystem rename).

    Only when the canonical name does not exist yet; a process holding files in the old directory
    keeps its handles, and new paths resolve through the symlink. Returns True when it moved."""
    local, shared = config_dir / name, HOME_CLAUDE / name
    if local.is_symlink() or not local.exists() or shared.exists():
        return False
    try:
        os.rename(local, shared)
        os.symlink(shared, local)
        return True
    except OSError:
        _LOG.warning("could not move %s into the shared Claude store", local)
        return False


def link_shared(config_dir: Path) -> int:
    """Symlink every shared ~/.claude entry into CONFIG_DIR. Never moves or replaces a real entry
    Claude created there, so a running session is never disturbed. Returns the number created."""
    HOME_CLAUDE.mkdir(mode=0o700, parents=True, exist_ok=True)
    for name in SHARED_NAMES:  # adopt before creating an empty canonical store
        _adopt_local(config_dir, name)
    _ensure_canonical()
    created = 0
    for source in sorted(HOME_CLAUDE.iterdir()):
        if source.name in PER_ACCOUNT:
            continue
        target = config_dir / source.name
        if target.is_symlink() or target.exists():
            continue
        try:
            os.symlink(source, target)
            created += 1
        except OSError:
            _LOG.warning("could not link %s into %s", source, config_dir)
    return created


def prepare(label: str) -> Path:
    """Create (or repair) the account directory: 0700, seeded config, shared links."""
    config_dir = account_dir(label)
    if config_dir.is_symlink():
        raise AccountError(f"{config_dir} is a symlink; use a real directory")
    ACCOUNTS_ROOT.mkdir(parents=True, exist_ok=True)
    os.chmod(ACCOUNTS_ROOT, 0o700)
    config_dir.mkdir(exist_ok=True)
    os.chmod(config_dir, 0o700)
    config = config_dir / ".claude.json"
    if not config.exists() and HOME_CLAUDE_JSON.is_file():
        config.write_bytes(HOME_CLAUDE_JSON.read_bytes())
        os.chmod(config, 0o600)
    link_shared(config_dir)
    return config_dir


# ── Claude CLI ───────────────────────────────────────────────────────────────

def claude_bin() -> str:
    return shutil.which("claude") or "claude"


def env_conflicts(env: dict | None = None) -> list[str]:
    env = os.environ if env is None else env
    return [name for name in OVERRIDE_ENV if env.get(name)]


def _check_env() -> None:
    hit = env_conflicts()
    if hit:
        raise AccountError(f"{', '.join(hit)} set: Claude would ignore the account directory; "
                           "unset it first")


def _env_for(config_dir: Path) -> dict:
    return {**os.environ, "CLAUDE_CONFIG_DIR": normalize_dir(config_dir)}


def _run(argv: list[str], env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(argv, env=env)


def auth_status(config_dir: Path, timeout: float = 60) -> dict:
    """`claude auth status --json` for CONFIG_DIR, parsed. Raises when the CLI cannot answer."""
    try:
        out = subprocess.run([claude_bin(), "auth", "status", "--json"],
                             env=_env_for(config_dir), capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        raise AccountError(f"could not run `claude auth status`: {exc}") from exc
    try:
        data = json.loads(out.stdout or "")
    except ValueError:
        raise AccountError("`claude auth status --json` returned no JSON; is the CLI installed?") from None
    if not isinstance(data, dict):
        raise AccountError("`claude auth status --json` returned an unexpected payload")
    return data


# ── Switching ────────────────────────────────────────────────────────────────

def activate_env(env: dict) -> dict:
    """Point ENV at the active account directory. Runs with no account configured are unchanged.

    A selected account whose directory is missing is still passed through: Claude then fails with
    its own authentication error instead of silently using the default or an inherited login."""
    try:
        label, _ = active_account()
    except AccountError:
        return env
    if not label:
        return env
    config_dir = account_dir(label)
    if not config_dir.is_dir():
        _LOG.warning("active Claude account %r has no directory %s", label, config_dir)
    env["CLAUDE_CONFIG_DIR"] = normalize_dir(config_dir)
    return env


def inherit_env(env: dict) -> dict:
    """Like activate_env, but an explicit CLAUDE_CONFIG_DIR from the caller wins."""
    if "CLAUDE_CONFIG_DIR" not in env:
        activate_env(env)
    return env


def access_token() -> str | None:
    """Access token for the active account, or for the default login when none is configured."""
    try:
        label, _ = active_account()
        if label:
            blob = credentials(account_dir(label))
        else:
            blob = _parse_blob(_kc_read(DEFAULT_SERVICE))
    except (AccountError, OSError, subprocess.SubprocessError):
        return None
    token = _oauth(blob).get("accessToken")
    return token if isinstance(token, str) and token else None


def _running_claude() -> int:
    out = subprocess.run(["pgrep", "-x", "claude"], capture_output=True, text=True, timeout=5)
    return len(out.stdout.split())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _record_verified(label: str, config_dir: Path, expected_email: str | None) -> dict:
    status = auth_status(config_dir)
    if not status.get("loggedIn"):
        raise AccountError(f"`claude auth status` reports {label} as not logged in; retry `login {label}`")
    reported_dir = status.get("configDirectory")
    if not isinstance(reported_dir, str) or normalize_dir(reported_dir) != normalize_dir(config_dir):
        raise AccountError(f"`claude auth status` reported config directory {reported_dir!r}, "
                           f"not {normalize_dir(config_dir)!r}")
    email = (status.get("email") or "").strip()
    if not email:
        raise AccountError("`claude auth status` returned no email; cannot record the identity")
    if expected_email and email.lower() != expected_email.strip().lower():
        raise AccountError(f"logged in as {email}, not {expected_email}; retry `login {label}`")
    subscription = status.get("subscriptionType") or ""
    with _locked():
        index = _read_index()
        for other, meta in index["accounts"].items():
            if other != label and (meta.get("email") or "").lower() == email.lower():
                raise AccountError(f"{email} is already saved as {other!r}")
        index["accounts"][label] = {"email": email, "subscription": subscription, "saved_at": _now()}
        if not index["active"]:
            index["active"] = label
        _write_index(index)
    return {"ok": True, "label": label, "email": email, "subscription": subscription,
            "dir": normalize_dir(config_dir), "active": index["active"]}


def login(label: str, email: str | None = None) -> dict:
    """Create the account directory, sign in through the browser there, record the identity."""
    _check_env()
    config_dir = prepare(label)
    argv = [claude_bin(), "auth", "login"] + (["--email", email] if email else [])
    try:
        result = _run(argv, _env_for(config_dir))
    except KeyboardInterrupt:
        raise AccountError("login interrupted") from None
    except OSError as exc:
        raise AccountError(f"could not run `claude auth login`: {exc}") from exc
    if result.returncode != 0:
        raise AccountError(f"`claude auth login` exited {result.returncode}; nothing recorded")
    return _record_verified(label, config_dir, email)


def record(label: str, email: str | None = None) -> dict:
    """Record a login already completed in LABEL's directory, without launching the browser."""
    _check_env()
    config_dir = account_dir(label)
    if not config_dir.is_dir():
        raise AccountError(f"no account directory {config_dir}; run `login {label}` first")
    return _record_verified(label, config_dir, email)


def use(label: str) -> dict:
    """Make LABEL the account new Claude runs use. Never writes a credential."""
    _check_label(label)
    config_dir = account_dir(label)
    warnings: list[str] = []
    with _locked():
        index = _read_index()
        if label not in index["accounts"]:
            raise AccountError(f"no saved account {label!r}; saved: {', '.join(index['accounts']) or 'none'}")
        if not config_dir.is_dir():
            raise AccountError(f"account directory {config_dir} is missing; run `login {label}`")
        link_shared(config_dir)
        index["active"] = label
        _write_index(index)
        email = index["accounts"][label].get("email")
        os.utime(INDEX)  # a re-select must still bump swap_generation()
    try:
        status = auth_status(config_dir, timeout=20)
    except AccountError as exc:
        warnings.append(f"could not verify the login: {exc}")
    else:
        if not status.get("loggedIn"):
            warnings.append(f"{label} reports not logged in; run `login {label}`")
        elif status.get("email") and status["email"] != email:
            warnings.append(f"{label} now reports {status['email']} instead of {email}")
    try:
        if credentials(config_dir) is None:
            warnings.append("no readable credential for this account: quota cards stay empty until "
                            "Claude runs once, or run `login " + label + "`")
    except AccountError as exc:
        warnings.append(f"no readable credential for this account ({exc})")
    try:
        running = _running_claude()
    except (OSError, subprocess.SubprocessError):
        running = 0
    if running:
        warnings.append(f"{running} running claude process(es) keep the account they started with")
    return {"ok": True, "label": label, "email": email, "dir": normalize_dir(config_dir),
            "warnings": warnings}


def status() -> dict:
    """Diagnostics for the active account, without printing any secret."""
    label, meta = active_account()
    out: dict = {"active": label, "email": (meta or {}).get("email"), "dir": None,
                 "accounts": accounts()["accounts"], "conflicts": env_conflicts(),
                 "legacy_index": legacy_index(), "credential": "none", "error": None,
                 "loggedIn": None, "reported_email": None,
                 "subscription": None, "local_only": [], "linked": 0}
    if not label:
        return out
    config_dir = account_dir(label)
    out["dir"] = normalize_dir(config_dir)
    if not config_dir.is_dir():
        out["error"] = "the account directory is missing; run `login " + label + "`"
        return out
    try:
        raw, out["credential"] = _credential_raw(config_dir)
        out["credential"] = out["credential"] if _parse_blob(raw) else "none"
    except AccountError as exc:
        out["credential"] = "unreadable"
        out["error"] = str(exc)
    out["local_only"] = local_only(config_dir)
    out["linked"] = len([n for n in os.listdir(config_dir)
                         if (config_dir / n).is_symlink() and n not in PER_ACCOUNT])
    try:
        live = auth_status(config_dir, timeout=20)
    except AccountError as exc:
        out["error"] = out["error"] or str(exc)
        return out
    out["loggedIn"] = live.get("loggedIn")
    out["reported_email"] = live.get("email")
    out["subscription"] = live.get("subscriptionType")
    out["configDirectory"] = live.get("configDirectory")
    return out


def exec_claude(args: list[str]) -> None:
    """Replace this process with the active account's Claude (for terminal aliases)."""
    env = activate_env(os.environ.copy())
    binary = claude_bin()
    try:
        os.execvpe(binary, [binary, *args], env)
    except OSError as exc:
        raise AccountError(f"could not run {binary!r}: {exc}") from exc


# ── CLI ──────────────────────────────────────────────────────────────────────

def _print_status(data: dict) -> None:
    if data.get("legacy_index"):
        print("note: the retired snapshot index is ignored; run `login <label>` for each account")
    if not data.get("active"):
        print("active: none (Claude uses the default login; run `login <label>`)")
        if data.get("conflicts"):
            print(f"override variables set: {', '.join(data['conflicts'])}")
        return
    print(f"active: {data['active']}  {data.get('dir')}")
    print(f"login:  loggedIn={data.get('loggedIn')}  email={data.get('reported_email')}  "
          f"subscription={data.get('subscription')}")
    print(f"credential: {data.get('credential')}   shared links: {data.get('linked')}")
    if data.get("local_only"):
        print(f"local-only entries (not shared): {', '.join(data['local_only'])}")
    if data.get("conflicts"):
        print(f"override variables set: {', '.join(data['conflicts'])}")
    if data.get("error"):
        print(f"warning: {data['error']}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["claude"]:  # everything after `claude` belongs to Claude, not argparse
        try:
            exec_claude(args[1:])
        except AccountError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        return 0
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_login = sub.add_parser("login", help="create the account directory and sign in there")
    p_login.add_argument("label")
    p_login.add_argument("--email", help="expected account email (prefills and verifies the login)")
    p_save = sub.add_parser("save", help="record a login already made in that account directory")
    p_save.add_argument("label")
    p_save.add_argument("--email", help="expected account email")
    sub.add_parser("use", help="switch new Claude runs to LABEL").add_argument("label")
    sub.add_parser("list", help="saved accounts; * marks the active one")
    sub.add_parser("status", help="diagnose the active account without printing secrets")
    parsed = parser.parse_args(args)
    try:
        if parsed.cmd in ("login", "save"):
            runner = login if parsed.cmd == "login" else record
            result = runner(parsed.label, parsed.email)
            verb = "now using" if result["active"] == result["label"] else "saved"
            print(f"{verb} {result['label']} ({result['email']})")
        elif parsed.cmd == "use":
            result = use(parsed.label)
            print(f"now using {result['label']} ({result['email']})")
            for warning in result["warnings"]:
                print(f"warning: {warning}", file=sys.stderr)
        elif parsed.cmd == "list":
            data = accounts()
            for account in data["accounts"]:
                mark = "*" if account["label"] == data["active"] else " "
                print(f"{mark} {account['label']}  {account['email']}")
            if not data["accounts"]:
                print("no saved accounts; see --help")
            if legacy_index():
                print("note: the retired snapshot index is ignored; run `login <label>` again",
                      file=sys.stderr)
        else:
            _print_status(status())
    except AccountError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
