#!/usr/bin/env python3
"""Project registry, per-ticket worktrees and the verify harness.

CLI:
    .venv/bin/python3 runner/projects.py list
    .venv/bin/python3 runner/projects.py worktree <key> <issue-id>
    .venv/bin/python3 runner/projects.py verify <key> --worktree DIR [--base SHA]
    .venv/bin/python3 runner/projects.py cleanup <key> <issue-id>

The registry (projects.yaml, gitignored) names private projects, so nothing
here prints or logs more than keys and paths the user already wrote there.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import re
import shlex
import shutil
import stat as stat_module
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import dataclasses
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_PROTO = Path(__file__).resolve().parent.parent
REGISTRY_PATH = Path(os.environ.get("AGENTIC_OS_PROJECTS", str(_PROTO / "projects.yaml")))
WORKTREE_ROOT = Path(os.environ.get("AGENTIC_OS_WORKTREES", "~/.agentic-os/worktrees")).expanduser()

_FIELDS = {"path", "kind", "verify", "env", "confidential", "no_push", "seed", "verify_timeout_s", "note",
           "auto_merge"}
_IDENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
DEFAULT_VERIFY_TIMEOUT_S = 600
TAIL_CHARS = 4000


class ProjectError(Exception):
    """A registry, worktree or verify problem the user has to fix."""


class TicketLocked(ProjectError):
    pass


class ProjectBusy(ProjectError):
    """The project lifecycle lock is held (a run, baseline, CLI command or terminal)."""


class RegistryConflict(ProjectError):
    """projects.yaml changed since the caller read it."""


class WorktreesRemain(ProjectError):
    def __init__(self, msg: str, worktrees: list[str]):
        super().__init__(msg)
        self.worktrees = worktrees


@dataclass(frozen=True)
class Project:
    key: str
    path: Path
    verify: str
    kind: str = ""
    env: dict = field(default_factory=dict)
    confidential: bool = False
    no_push: bool = False
    seed: tuple = ()
    verify_timeout_s: int = DEFAULT_VERIFY_TIMEOUT_S
    note: str = ""
    auto_merge: bool = True


# An agent can write the shared git config (e.g. core.fsmonitor -> a script in its
# worktree); git would then run that script inside the runner's own commands.
_GIT_HARDENING = ("-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null")


def _sb_str(path: str) -> str:
    """A path as a sandbox-profile string literal: quotes and backslashes escaped (SC-015)."""
    if any(ord(c) < 32 or c == "\x7f" for c in path):
        raise ProjectError(f"path {path!r} has control characters; the sandbox cannot name it")
    return '"' + path.replace("\\", "\\\\").replace('"', '\\"') + '"'


def sandbox_profile(writable: list[Path], temp: bool = True) -> str:
    """macOS sandbox-exec profile: no network, writes only under `writable` and (temp) temp dirs."""
    tmp = {Path("/private/tmp"), Path(os.path.realpath(tempfile.gettempdir()))} if temp else set()
    roots = sorted({str(Path(os.path.realpath(p))) for p in [*writable, *tmp]})
    allow = " ".join(f'(subpath {_sb_str(r)})' for r in roots) or '(literal "/dev/null")'
    # allow-default keeps git, shells and test runtimes working; the denials close the routes
    # by which sandboxed code asks something outside the sandbox to act for it.
    # ponytail: deny-list, not deny-default; spike (g2) probes `open URL`, osascript and
    # launchctl submit. Move to deny-default if a new escape route shows up.
    return ("(version 1)(allow default)(deny network*)(deny file-write*)"
            "(deny lsopen)(deny appleevent-send)"
            '(deny mach-lookup (global-name "com.apple.coreservices.launchservicesd")'
            ' (global-name "com.apple.coreservices.appleevents") (global-name-regex #"^com\\.apple\\.lsd\\."))'
            f'(allow file-write* {allow} (literal "/dev/null") (literal "/dev/tty") (regex #"^/dev/fd/"))')


def sandbox_prefix(writable: list[Path], temp: bool = True) -> list[str]:
    return ["/usr/bin/sandbox-exec", "-p", sandbox_profile(writable, temp)]


def readonly_status(cwd: Path) -> list[str]:
    """`uncommitted` under a write-nothing sandbox: no writable roots, not even temp. A clean
    filter that status runs can neither touch the checkout nor its git dir (SC-011)."""
    argv = [*sandbox_prefix([], temp=False), "git", *_GIT_HARDENING, "-C", str(cwd), "--no-optional-locks",
            "status", "--porcelain", "-z", "--untracked-files=all"]
    try:
        code, out, err = _run_bounded(argv, GIT_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise ProjectError(f"git status timed out in {cwd}") from None
    if code != 0:
        raise ProjectError(f"git status failed in {cwd}: {err.decode(errors='replace').strip()}")
    return _porcelain_paths(out)


GIT_TIMEOUT_S = 120
COMMIT_TIMEOUT_S = 60


def _kill_group(proc: subprocess.Popen) -> None:
    """SIGTERM the whole process group, SIGKILL after 5 s, then reap."""
    # macOS answers EPERM (not ESRCH) for a group whose members are all zombies.
    for sig, wait in ((signal.SIGTERM, 5), (signal.SIGKILL, 5)):
        try:
            os.killpg(proc.pid, sig)
        except (ProcessLookupError, PermissionError):
            break
        try:
            proc.wait(timeout=wait)
            break
        except subprocess.TimeoutExpired:
            continue
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(proc.pid, signal.SIGKILL)  # stragglers left by a leader that already exited
    proc.wait()


# Every process group the runner starts for a project (git, agent, verify) is registered
# here, so shutdown can stop them all; after stop_all() nothing new starts (I5-12, I6-08).
STOPPING = threading.Event()
_LIVE: set = set()
_LIVE_LOCK = threading.Lock()


def spawn(argv: list[str], **kw) -> subprocess.Popen:
    """Popen in a new session, registered for shutdown. Refused once stop_all() ran."""
    with _LIVE_LOCK:
        if STOPPING.is_set():
            raise ProjectError("runner is shutting down")
        proc = subprocess.Popen(argv, start_new_session=True, **kw)
        _LIVE.add(proc)
    return proc


def reap(proc: subprocess.Popen) -> None:
    """Kill and reap the group, then forget it."""
    try:
        _kill_group(proc)
    finally:
        with _LIVE_LOCK:
            _LIVE.discard(proc)


def stop_all() -> None:
    """Shutdown: refuse new processes, then kill and reap every live project process group."""
    with _LIVE_LOCK:
        STOPPING.set()
        live = list(_LIVE)
    for proc in live:
        with contextlib.suppress(Exception):
            reap(proc)


def _run_bounded(argv: list[str], timeout: float, cwd: Path | None = None, env: dict | None = None,
                 merge_stderr: bool = False, stdin: bytes | None = None) -> tuple[int, bytes, bytes]:
    """Run argv in its own process group. On timeout, error or Ctrl-C the group is killed and
    reaped before this returns or raises (subprocess.TimeoutExpired on timeout)."""
    proc = spawn(argv, cwd=cwd, env=env, stdout=subprocess.PIPE,
                 stderr=subprocess.STDOUT if merge_stderr else subprocess.PIPE,
                 stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL)
    try:
        out, err = proc.communicate(input=stdin, timeout=timeout)
    finally:
        reap(proc)  # every outcome: also stragglers a successful command left running
    return proc.returncode, out or b"", err or b""


def _git_argv(cwd: Path, args: tuple, confine: list[Path] | None, hardening: tuple = _GIT_HARDENING) -> list[str]:
    if args and args[0] == "diff":  # repo-configured diff drivers/textconv never run
        args = ("diff", "--no-ext-diff", "--no-textconv", *[a for a in args[1:] if a not in ("--no-ext-diff", "--no-textconv")])
    argv = ["git", *hardening, "-C", str(cwd), *args]
    return [*sandbox_prefix(confine), *argv] if confine is not None else argv


def _git(cwd: Path, *args: str, check: bool = True, confine: list[Path] | None = None,
         timeout: float = GIT_TIMEOUT_S, env: dict | None = None,
         stdin: bytes | None = None) -> subprocess.CompletedProcess:
    """Every runner-owned git command goes through here: hardened, bounded, own process group,
    and confined when `confine` is set."""
    argv = _git_argv(cwd, args, confine)
    try:
        code, out, err = _run_bounded(argv, timeout, env=env, stdin=stdin)
    except subprocess.TimeoutExpired:
        raise ProjectError(f"git {args[0]} timed out after {timeout:.0f} s in {cwd}") from None
    proc = subprocess.CompletedProcess(argv, code, out.decode("utf-8", "replace"), err.decode("utf-8", "replace"))
    if check and code != 0:
        raise ProjectError(f"git {' '.join(args)} failed in {cwd}: {proc.stderr.strip()}")
    return proc


def confine_for(project: "Project", *paths: Path) -> list[Path] | None:
    """Writable roots for confined commands on a confidential project; None otherwise (Decision 9)."""
    if not project.confidential:
        return None
    common = _git(project.path, "rev-parse", "--git-common-dir").stdout.strip()
    return [(project.path / common).resolve(), *paths]


# ── Registry ─────────────────────────────────────────────────────────────────

def _seed_path(root: Path, raw: object, key: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ProjectError(f"{key}: seed entries must be non-empty strings")
    rel = Path(raw)
    if rel.is_absolute() or ".." in rel.parts:
        raise ProjectError(f"{key}: seed {raw!r} must be relative to the project root, without '..'")
    src = root / rel
    if not src.exists():  # also false for a dangling link
        raise ProjectError(f"{key}: seed {raw!r} is missing or a dangling link")
    if not src.resolve().is_relative_to(root.resolve()):
        raise ProjectError(f"{key}: seed {raw!r} resolves outside the project root")
    return rel.as_posix()


def _parse_project(key: str, entry: object) -> Project:
    if not isinstance(entry, dict):
        raise ProjectError(f"{key}: entry must be a mapping")
    unknown = set(entry) - _FIELDS
    if unknown:
        raise ProjectError(f"{key}: unknown field(s) {sorted(unknown)}; allowed: {sorted(_FIELDS)}")
    raw_path = entry.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ProjectError(f"{key}: 'path' is required")
    root = Path(raw_path).expanduser()
    if not root.is_absolute():
        raise ProjectError(f"{key}: 'path' must be absolute or ~-relative")
    if not root.is_dir() or _git(root, "rev-parse", "--git-dir", check=False).returncode != 0:
        raise ProjectError(f"{key}: {root} is not a git repository")
    verify = entry.get("verify")  # optional: without it the agent runs the project's own tests
    if verify is not None and (not isinstance(verify, str) or not verify.strip()):
        raise ProjectError(f"{key}: 'verify' must be a non-empty string when given")
    env = entry.get("env") or {}
    if not isinstance(env, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in env.items()):
        raise ProjectError(f"{key}: 'env' must map strings to strings")
    env = {k: os.path.expanduser(v) if k == "PATH" else v for k, v in env.items()}
    seeds = entry.get("seed") or []
    if not isinstance(seeds, list):
        raise ProjectError(f"{key}: 'seed' must be a list")
    note = entry.get("note") or ""
    if not isinstance(note, str):
        raise ProjectError(f"{key}: 'note' must be a string")
    timeout = entry.get("verify_timeout_s", DEFAULT_VERIFY_TIMEOUT_S)
    if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout <= 0:
        raise ProjectError(f"{key}: 'verify_timeout_s' must be a positive integer")
    return Project(
        key=key, path=root, verify=(verify or "").strip(), kind=str(entry.get("kind") or ""),
        env=env, confidential=bool(entry.get("confidential", False)),
        no_push=bool(entry.get("no_push", False)), auto_merge=bool(entry.get("auto_merge", True)),
        seed=tuple(_seed_path(root, s, key) for s in seeds), verify_timeout_s=timeout, note=note,
    )


def declares_confidential(path: Path | None = None) -> bool:
    """True when any registry entry declares `confidential`, valid entry or not (I6-04).
    An unreadable registry counts as declaring it (fail closed)."""
    path = Path(path or REGISTRY_PATH)
    if not path.exists():
        return False
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return True
    entries = data.get("projects") if isinstance(data, dict) else None
    if not isinstance(entries, dict):
        return True
    return any(not isinstance(e, dict) or e.get("confidential") not in (None, False) for e in entries.values())


def load_registry(path: Path | None = None, errors: dict | None = None,
                  data: bytes | None = None) -> dict[str, Project]:
    """Parse the registry. With `errors` given, a bad entry is recorded there and skipped
    (the dashboard keeps showing the other projects); without it, the first error raises.
    `data` parses bytes already read (one snapshot for entries and hash, REGUI-008)."""
    path = Path(path or REGISTRY_PATH)
    if data is None and not path.exists():
        return {}
    try:
        data = yaml.safe_load(data if data is not None else path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ProjectError(f"{path}: cannot read registry: {exc}") from None
    projects = data.get("projects") if isinstance(data, dict) else None
    if not isinstance(projects, dict):
        raise ProjectError(f"{path}: top level must have a 'projects' mapping")
    for key in projects:
        if not isinstance(key, str) or not _IDENT.match(key):
            raise ProjectError(f"{path}: project key {key!r} must match {_IDENT.pattern}")
    if errors is None:
        return {key: _parse_project(key, entry) for key, entry in projects.items()}
    loaded = {}
    for key, entry in projects.items():
        try:
            loaded[key] = _parse_project(key, entry)
        except Exception as exc:  # ProjectError, or e.g. RuntimeError from '~nouser', ValueError from NUL
            errors[key] = str(exc)
    return loaded


def _check_key(key: object) -> str:
    if not isinstance(key, str) or not _IDENT.match(key):
        raise ProjectError(f"project key {key!r} must match {_IDENT.pattern}")
    return key


@contextlib.contextmanager
def project_lock(key: str, exclusive: bool = False, blocking: bool = True):
    """Lifecycle lock of one project (REGUI-004). Shared (blocking) for everything that uses
    the project: a launch, CLI worktree/verify/cleanup, a baseline, a project tab. Exclusive
    (non-blocking) for remove and for edits of path/confidential/seed. Lock order everywhere:
    project -> registry -> ticket locks; a holder never re-acquires or downgrades it."""
    lock_dir = WORKTREE_ROOT / ".project-locks"  # outside every key dir; keys never start with "."
    lock_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(lock_dir / f"{_check_key(key)}.lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(fd, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError:
            raise ProjectBusy(f"project {key} is busy (a run, baseline, CLI command or open terminal is using it)") from None
        yield
    finally:
        os.close(fd)


def _registry_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest() if data else ""


def _read_registry_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return b""


def registry_snapshot(path: Path | None = None) -> tuple[bytes, str]:
    """One read of projects.yaml: its bytes and their hash ("" when missing)."""
    data = _read_registry_bytes(Path(path or REGISTRY_PATH))
    return data, _registry_hash(data)


def raw_entries(data: bytes) -> dict:
    """The entries as written (for the edit form); {} when the file is empty or malformed."""
    try:
        doc = yaml.safe_load(data) if data else None
    except yaml.YAMLError:
        return {}
    projects = doc.get("projects") if isinstance(doc, dict) else None
    return {k: v for k, v in projects.items() if isinstance(k, str)} if isinstance(projects, dict) else {}


def _locked_doc(path: Path, expected_hash: str) -> dict:
    data = _read_registry_bytes(path)
    if _registry_hash(data) != expected_hash:
        raise RegistryConflict("projects.yaml changed since it was loaded; reload and try again")
    try:
        doc = (yaml.safe_load(data) if data else None) or {"projects": {}}
    except yaml.YAMLError as exc:
        raise ProjectError(f"{path}: cannot parse registry: {exc}") from None
    if not isinstance(doc, dict) or not isinstance(doc.setdefault("projects", {}), dict):
        raise ProjectError(f"{path}: top level must have a 'projects' mapping")
    return doc


def _write_registry(path: Path, doc: dict, expected_hash: str) -> None:
    """Re-check the hash immediately before replacing (REGUI-008), then write atomically.
    ponytail: an editor saving in the instant between this check and os.replace still loses;
    editors do not take the registry lock."""
    if _registry_hash(_read_registry_bytes(path)) != expected_hash:
        raise RegistryConflict("projects.yaml changed while saving; reload and try again")
    text = yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, default_flow_style=False)
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(tmp, path.stat().st_mode & 0o777 if path.exists() else 0o600)
        os.replace(tmp, path)
    except OSError as exc:
        raise ProjectError(f"cannot write {path}: {exc}") from None
    finally:
        if tmp:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(tmp)


def _clean_entry(entry: object) -> dict:
    """Form values -> a registry entry: empty optional fields are dropped, booleans kept."""
    if not isinstance(entry, dict):
        raise ProjectError("entry must be a mapping")
    return {k: v for k, v in entry.items() if v is not None and v != "" and v != [] and v != {}}


def _worktree_dirs(key: str) -> list[str]:
    """Names under WORKTREE_ROOT/<key> that may be worktrees (dirs or links; .meta and lock files skipped)."""
    root = WORKTREE_ROOT / key
    if not root.is_dir():
        return []
    return sorted(e.name for e in root.iterdir() if e.name != ".meta" and (e.is_dir() or e.is_symlink()))


def _lifecycle_changed(old: dict, new: dict) -> bool:
    """path, confidential and seed changes need the exclusive project lock."""
    return (old.get("path") != new.get("path") or bool(old.get("confidential")) != bool(new.get("confidential"))
            or (old.get("seed") or []) != (new.get("seed") or []))


def save_project(key: str, entry: dict, expected_hash: str, *, create: bool = False,
                 path: Path | None = None) -> dict:
    """Create or edit one registry entry from the dashboard, validated like dispatch.
    The key is immutable: worktrees, sidecars and bindings are keyed by it. On create, a
    missing or empty folder that is not its own repo root is made one after the key/hash/
    duplicate checks (REGUI-B005); a non-empty one is refused. If the save then fails the
    folder is kept, never deleted (B006), and the error carries `initialized`."""
    path = Path(path or REGISTRY_PATH)
    _check_key(key)
    entry = _clean_entry(entry)
    old = raw_entries(_read_registry_bytes(path)).get(key)
    lifecycle = create or _lifecycle_changed(old if isinstance(old, dict) else {}, entry)
    with contextlib.ExitStack() as stack:
        if lifecycle:
            stack.enter_context(project_lock(key, exclusive=True, blocking=False))
        from state_io import file_lock
        stack.enter_context(file_lock(path))
        doc = _locked_doc(path, expected_hash)
        projects = doc["projects"]
        old = projects.get(key) if isinstance(projects.get(key), dict) else {}
        if not lifecycle and _lifecycle_changed(old, entry):
            raise RegistryConflict("projects.yaml changed while saving; reload and try again")
        if create and key in projects:
            raise ProjectError(f"project {key!r} already exists")
        if not create and key not in projects:
            raise ProjectError(f"unknown project {key!r}")
        created = init_repo(str(entry.get("path") or "")) if create and _needs_init(entry.get("path")) else None
        try:
            project = _validate_for_save(key, entry, old, create)
            projects[key] = entry
            _write_registry(path, doc, expected_hash)
        except Exception as exc:
            if not created:
                raise
            if not isinstance(exc, ProjectError):  # e.g. an OSError: still a structured answer (B007)
                exc = ProjectError(f"save failed: {exc}")
            exc.args = (f"{exc} — the new repo {created} was created and kept; save again to register it",)
            exc.initialized = str(created)
            raise exc from None
    return {"key": key, "confidential": project.confidential}


def _validate_for_save(key: str, entry: dict, old: dict, create: bool) -> Project:
    """Caller holds the registry lock and, for create/lifecycle changes, the exclusive project lock."""
    project = _parse_project(key, entry)
    if project.path.resolve().is_relative_to(WORKTREE_ROOT.resolve()):
        raise ProjectError(f"{key}: path must not be inside {WORKTREE_ROOT}")
    new_repo = create or entry.get("path") != old.get("path")
    if new_repo and not _is_repo_root(project.path):  # a folder inside another repo is not a project (SAP-001)
        raise ProjectError(f"{key}: {project.path} is not the root of its git repository")
    trees = _worktree_dirs(key)
    if trees and not create and new_repo:  # sidecars record the old path literally (REGUI-007, B002)
        raise ProjectError(f"{key}: the path cannot change while worktrees exist ({', '.join(trees)}); "
                           "remove the project with clean-up, or clean them up first")
    if trees and create:  # re-adding: every leftover must bind to exactly this path
        bad = []
        for ident in trees:
            try:
                load_binding(project, _check_ident(ident))
            except ProjectError:
                bad.append(ident)
        if bad:
            raise ProjectError(f"{key}: leftover worktrees under {WORKTREE_ROOT / key} belong to another "
                               f"path or are damaged: {bad}; clean them up first")
    if new_repo or entry.get("seed") != old.get("seed"):
        # The exact dispatch checks (verify targets, seed copy, collision, committed-ignore
        # rule) in a throwaway worktree, under the caller's exclusive lock (REGUI-002/009).
        ident = f"REGCHECK-{int(time.time() * 1000)}"
        with ticket_lock(key, ident):
            if create_worktree(project, ident)["reused"]:
                raise ProjectError(f"{key}/{ident} already existed; left untouched")
            remove_worktree(project, ident)
        drop_ticket_lock(key, ident)
    return project


def _cleanup_descriptor(key: str, raw: object) -> Project:
    """The project to clean worktrees with. A broken entry keeps only its path, is always
    confidential (every git call confined, REGUI-012), and must still be a git repo."""
    with contextlib.suppress(Exception):
        return _parse_project(key, raw)
    raw_path = raw.get("path") if isinstance(raw, dict) else None
    root = Path(raw_path).expanduser() if isinstance(raw_path, str) and raw_path.strip() else None
    if root is None or not root.is_absolute() or not root.is_dir() or \
            _git(root, "rev-parse", "--git-dir", check=False).returncode != 0:
        raise ProjectError(f"{key}: path is missing or not a git repository, so worktree ownership "
                           f"cannot be verified; nothing removed")
    return Project(key=key, path=root, verify="", confidential=True)


def remove_project(key: str, expected_hash: str, *, cleanup: bool = False,
                   path: Path | None = None) -> dict:
    """Remove one registry entry (a broken one too). Project files are never touched; with
    `cleanup`, work-free worktrees are removed first, all or nothing (REGUI-005)."""
    path = Path(path or REGISTRY_PATH)
    _check_key(key)
    from state_io import file_lock
    removed: list[str] = []
    with project_lock(key, exclusive=True, blocking=False), file_lock(path):
        doc = _locked_doc(path, expected_hash)
        if key not in doc["projects"]:
            raise ProjectError(f"unknown project {key!r}")
        trees = _worktree_dirs(key)
        if trees and not cleanup:
            raise WorktreesRemain(f"{key}: worktrees remain: {', '.join(trees)}", trees)
        if trees:
            removed = _cleanup_worktrees(_cleanup_descriptor(key, doc["projects"][key]), trees)
        del doc["projects"][key]
        try:
            _write_registry(path, doc, expected_hash)
        except RegistryConflict as exc:
            raise RegistryConflict(f"{exc} (already removed worktrees: {removed or 'none'})") from None
        # Nothing else can hold this key's ticket locks while its exclusive project lock is held
        # (every ticket-lock holder takes the shared project lock first), so lock-only leftovers go.
        key_dir, meta = WORKTREE_ROOT / key, WORKTREE_ROOT / key / ".meta"
        if key_dir.is_dir() and not _worktree_dirs(key) and \
                all(e.is_file() and e.suffix == ".lock" for e in (meta.iterdir() if meta.is_dir() else [])) and \
                all(e.name == ".meta" for e in key_dir.iterdir()):
            shutil.rmtree(key_dir)
    return {"removed": key, "worktrees_removed": removed}


def drop_ticket_lock(key: str, ident: str) -> None:
    """Delete the lock file of a one-off ticket id (REGCHECK-/BASELINE-) after its lock is released."""
    (WORKTREE_ROOT / key / ".meta" / f"{_check_ident(ident)}.lock").unlink(missing_ok=True)


def _cleanup_worktrees(project: Project, trees: list[str]) -> list[str]:
    """Preflight every worktree under all their ticket locks, then delete; nothing is deleted
    unless every one is an owned, clean worktree with no commits beyond its base."""
    failures: list[str] = []
    with contextlib.ExitStack() as stack:
        checked: list[tuple[Project, str]] = []
        for ident in trees:  # sorted: one acquisition order
            try:
                _check_ident(ident)
                stack.enter_context(ticket_lock(project.key, ident))
                wt = worktree_path(project, ident)
                if wt.is_symlink() or not _is_worktree_of(project, wt):
                    raise ProjectError("not a worktree of this project")
                meta = load_binding(project, ident)
                eff = effective(project, meta)  # sidecar-confidential stays confined (REGUI-012)
                dirty = uncommitted(eff, wt)
                if dirty:
                    raise ProjectError(f"uncommitted changes: {', '.join(dirty[:5])}")
                ahead = _git(project.path, "rev-list", "--count", f"{meta['base_sha']}..refs/heads/agent/{ident}",
                             confine=confine_for(eff)).stdout.strip()
                if ahead != "0":
                    raise ProjectError(f"{ahead} commit(s) beyond its base")
                checked.append((eff, ident))
            except ProjectError as exc:
                failures.append(f"{ident}: {exc}")
        if failures:
            raise ProjectError("nothing removed; worktrees hold work or cannot be verified — " + "; ".join(failures))
        done: list[str] = []
        for eff, ident in checked:
            try:
                remove_worktree(eff, ident)
            except ProjectError as exc:
                left = [i for _, i in checked if i not in done]
                raise ProjectError(f"cleanup failed at {ident}: {exc}; removed {done or 'none'}, "
                                   f"still present {left}; registry entry kept") from None
            done.append(ident)
        return done


def _is_repo_root(root: Path) -> bool:
    proc = _git(root, "rev-parse", "--show-toplevel", check=False) if root.is_dir() else None
    return bool(proc and proc.returncode == 0 and Path(proc.stdout.strip()).resolve() == root.resolve())


def _needs_init(raw_path: object) -> bool:
    """True for a missing folder or an empty one that is not its own repo root; a non-empty
    non-root folder is refused (its files would otherwise be committed blind)."""
    if not isinstance(raw_path, str) or not raw_path.strip():
        return False  # _parse_project reports the missing path
    root = Path(raw_path).expanduser()
    if not root.is_absolute() or not os.path.lexists(root):
        return root.is_absolute()
    if not root.is_dir() or _is_repo_root(root):
        return False
    if any(root.iterdir()):
        raise ProjectError(f"{root} is not a git repository root and is not empty; run git init and commit first")
    return True


def init_repo(raw_path: str) -> Path:
    """Make a missing or empty folder a repo: git init + empty initial commit. On failure it
    removes only what it created (the folder it made, else just .git)."""
    root = Path(raw_path or "").expanduser()
    if not root.is_absolute():
        raise ProjectError("path must be absolute or ~-relative")
    existed = os.path.lexists(root)
    if existed and (not root.is_dir() or root.is_symlink() or any(root.iterdir())):
        raise ProjectError(f"{root} is not an empty folder")
    if not existed and not root.parent.is_dir():
        raise ProjectError(f"parent folder {root.parent} does not exist")
    if (root if existed else root.parent).resolve().is_relative_to(WORKTREE_ROOT.resolve()):
        raise ProjectError(f"path must not be inside {WORKTREE_ROOT}")
    if not existed:
        root.mkdir()
    try:
        _git(root, "init", "-q")
        _git(root, "commit", "-q", "--allow-empty", "-m", "Initial commit")
    except BaseException:
        shutil.rmtree(root / ".git" if existed else root, ignore_errors=True)
        raise
    return root


def derive_key(folder_name: str, taken) -> str:
    """The project key for a folder: its name made valid for _IDENT, `project` when nothing
    usable is left (SAP-004), then -2, -3, ... on a clash."""
    base = re.sub(r"[^A-Za-z0-9._-]", "-", folder_name or "")
    base = re.sub(r"^[^A-Za-z0-9]+", "", base) or "project"
    key, n = base, 1
    while key in taken:
        n += 1
        key = f"{base}-{n}"
    return key


def set_confidential(key: str, value: bool, expected_hash: str, path: Path | None = None) -> dict:
    """Change only `confidential` on the stored entry; every other field stays as written
    (no _clean_entry, SAP-007). A lifecycle change: needs the exclusive project lock."""
    path = Path(path or REGISTRY_PATH)
    _check_key(key)
    if not isinstance(value, bool):
        raise ProjectError("confidential must be true or false")
    from state_io import file_lock
    with project_lock(key, exclusive=True, blocking=False), file_lock(path):
        doc = _locked_doc(path, expected_hash)
        entry = doc["projects"].get(key)
        if not isinstance(entry, dict):
            raise ProjectError(f"unknown project {key!r}")
        # A copy: a YAML alias may share this mapping with another project (SAP-B001).
        entry = doc["projects"][key] = {**entry, "confidential": value}
        project = _parse_project(key, entry)
        _write_registry(path, doc, expected_hash)
    return {"key": key, "confidential": project.confidential}


_SCAN_ROOTS = ("Documents", "code", "Projects", "Developer", "src", "repos", "work", "")
_SCAN_SKIP_NAMES = {"Library", "Desktop", "Downloads", "node_modules", ".venv", "Applications", "Pictures",
                    "Movies", "Music"}


def locate_folder(name: str, entries: list, budget_s: float = 3.0, limit: int = 20) -> dict:
    """Where a dropped folder lives: the browser gives only its name and entry names. No git
    calls; one deadline and one result cap over every phase (SAP-B002), and one eligibility
    rule for history candidates, scan roots and scan children (SAP-B003)."""
    if not isinstance(name, str) or not name or "/" in name or name in (".", "..") or "\0" in name:
        raise ProjectError("folder name must be a single path component")
    want = {e for e in (entries or [])[:50] if isinstance(e, str)}
    deadline = time.monotonic() + budget_s
    late = lambda: time.monotonic() > deadline
    home = Path.home()
    skip_real = {str(p.resolve()) for p in (WORKTREE_ROOT, *(Path(t) for t in _TEMP_ROOTS)) if p.exists()}
    skip_real |= {str((home / n).resolve()) for n in ("Library", "Desktop", "Downloads")}
    found: dict[str, float] = {}
    state = {"complete": True}

    def eligible(p: Path) -> bool:
        """No hidden or skipped component, no symlink anywhere on the path, not under a skipped root."""
        if any(part.startswith(".") or part in _SCAN_SKIP_NAMES for part in p.parts[1:]):
            return False
        cur = Path(p.parts[0])
        for part in p.parts[1:]:
            cur = cur / part
            if cur.is_symlink():
                return False
        try:
            real = str(p.resolve())
        except OSError:
            return False
        return not any(real == s_ or real.startswith(s_ + "/") for s_ in skip_real)

    def consider(d: Path) -> None:
        """Entries are read one at a time until every wanted name is seen (or, for an empty
        drop, until any entry appears), checking the deadline as it goes (SAP-B002)."""
        if not eligible(d):
            return
        missing = set(want)
        try:
            with os.scandir(d) as it:
                for e in it:
                    if late():
                        state["complete"] = False
                        return
                    if not want:
                        return  # an empty drop matches only an empty folder
                    missing.discard(e.name)
                    if not missing:
                        break
            if missing:
                return
            found[str(d.resolve())] = d.stat().st_mtime
        except OSError:
            return

    def stop() -> bool:
        if late() or len(found) >= limit:
            state["complete"] = False
            return True
        return False

    # (a) session-history cwds and their ancestors: string ops only, under the same deadline
    cwds: set[str] = set()
    with contextlib.suppress(OSError):
        for proj in CLAUDE_PROJECTS.iterdir() if CLAUDE_PROJECTS.is_dir() else []:
            if stop():
                break
            for f in proj.glob("*.jsonl") if proj.is_dir() else []:
                if stop():
                    break
                with contextlib.suppress(Exception):
                    from usage_reader import _cached_by_stat
                    cwd = _cached_by_stat("session_cwd", f, f.stat(), _first_cwd)
                    if cwd:
                        cwds.add(cwd)
    if CODEX_DB.exists() and not stop():
        import sqlite3
        try:
            db = sqlite3.connect(f"file:{CODEX_DB}?mode=ro", uri=True, timeout=max(0.01, deadline - time.monotonic()))
            db.set_progress_handler(lambda: 1 if late() else 0, 1000)  # aborts a long query at the deadline
            try:
                cwds |= {c for (c,) in db.execute("SELECT DISTINCT cwd FROM threads") if isinstance(c, str)}
            finally:
                db.close()
        except sqlite3.Error:
            state["complete"] = state["complete"] and not late()
    for cwd in cwds:
        if stop():
            break
        parts = Path(cwd).parts
        if name in parts:
            consider(Path(*parts[:len(parts) - parts[::-1].index(name)]))
    # (b) breadth-first scan, at most 4 levels under each root, checked entry by entry
    queue = [(home / r if r else home, 0) for r in _SCAN_ROOTS]
    queue = [(d, n) for d, n in queue if d.is_dir() and eligible(d)]
    seen: set[str] = set()
    while queue and not stop():
        d, depth = queue.pop(0)
        real = str(d.resolve())
        if real in seen:
            continue
        seen.add(real)
        try:
            it = os.scandir(d)
        except OSError:
            continue
        with it:
            for c in it:
                if stop():
                    break
                try:
                    if not c.is_dir(follow_symlinks=False) or c.name.startswith(".") or c.name in _SCAN_SKIP_NAMES:
                        continue
                except OSError:
                    continue
                child = Path(c.path)
                if c.name == name:
                    consider(child)
                if depth < 3 and not (d == home and c.name in _SCAN_ROOTS) and eligible(child):
                    queue.append((child, depth + 1))
    if late():  # work that overran inside the last step still counts as cut short
        state["complete"] = False
    home_s = str(home)
    ordered = sorted(found, key=lambda p: found[p], reverse=True)[:limit]
    return {"matches": ["~" + p[len(home_s):] if p.startswith(home_s + "/") else p for p in ordered],
            "complete": state["complete"]}

def registered_key(key: str | None, registry: dict[str, Project] | None = None) -> str | None:
    """A label's project key mapped onto the registry, ignoring case ("project:Agentic-OS" is
    agentic-os); None when no registered project matches (FB3-01/03)."""
    if not key:
        return None
    registry = load_registry(errors={}) if registry is None else registry
    if key in registry:
        return key
    return next((k for k in registry if k.lower() == key.lower()), None)


def get_project(key: str, registry: dict[str, Project] | None = None) -> Project:
    registry = load_registry() if registry is None else registry
    if key not in registry:
        known = ", ".join(sorted(registry)) or "none"
        raise ProjectError(f"unknown project {key!r} (registered: {known})")
    return registry[key]


def untracked_verify_targets(project: Project) -> list[str]:
    """Paths named in the verify command that exist in the checkout but not at HEAD.

    ponytail: a token counts as a target only if it is an existing path inside the repo;
    commands like `pytest -q` name no file, so they always pass this check.
    """
    root = project.path.resolve()
    missing = []
    lexer = shlex.shlex(project.verify, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    for token in lexer:
        if "{root}" in token or "{base}" in token or token.startswith("-"):
            continue
        cand = (root / token)
        if not cand.exists() or not cand.resolve().is_relative_to(root):
            continue
        rel = cand.resolve().relative_to(root).as_posix()
        if _git(root, "cat-file", "-e", f"HEAD:{rel}", check=False).returncode != 0:
            missing.append(rel)
    return missing


# ── Ticket lock ──────────────────────────────────────────────────────────────

def _check_ident(ident: str) -> str:
    if not _IDENT.match(ident or ""):
        raise ProjectError(f"issue id {ident!r} must match {_IDENT.pattern}")
    return ident


@contextlib.contextmanager
def ticket_lock(key: str, ident: str):
    """Non-blocking per-ticket lock, shared by the dashboard and every CLI subcommand."""
    lock_dir = WORKTREE_ROOT / _check_key(key) / ".meta"  # sidecars never share the ticket-dir namespace; no path in the key (FB3-01)
    lock_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(lock_dir / f"{_check_ident(ident)}.lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise TicketLocked(f"{key}/{ident} is busy (another launch, verify, cleanup or terminal holds it)")
        yield
    finally:
        os.close(fd)


CARD_LOCK_DIR = Path(os.environ.get("AGENTIC_OS_CARD_LOCKS", "~/.agentic-os/card-locks")).expanduser()


@contextlib.contextmanager
def card_lock(card_key: str):
    """Non-blocking lock of a runner-root card (no project): held by its interactive terminal
    while open and by a retry/quick reply until its attempt ends (C2). Same rule as ticket_lock."""
    CARD_LOCK_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(CARD_LOCK_DIR / f"{_check_ident(card_key)}.lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise TicketLocked(f"card {card_key} is busy (an interactive terminal or a running attempt holds it)")
        yield
    finally:
        os.close(fd)


def card_busy(project_key: str | None, ident: str | None, card_key: str | None) -> bool:
    """Probe without keeping it: is this card's lock (ticket lock for a project card, card lock
    otherwise) held right now?"""
    try:
        if project_key and ident:
            with ticket_lock(project_key, ident):
                return False
        if card_key:
            with card_lock(card_key):
                return False
    except TicketLocked:
        return True
    except ProjectError:
        return False
    return False


# ── Worktrees ────────────────────────────────────────────────────────────────

def worktree_path(project: Project, ident: str) -> Path:
    return WORKTREE_ROOT / project.key / _check_ident(ident)


def _symlink_ancestor(wt: Path, rel: str) -> str | None:
    cur = wt
    for part in Path(rel).parts[:-1]:
        cur = cur / part
        if cur.is_symlink():
            return cur.relative_to(wt).as_posix()
    return None


def _ignored_by_committed_rule(wt: Path, rel: str, confine: list[Path] | None = None) -> bool:
    """True only when a tracked, unmodified .gitignore inside the worktree ignores `rel`.

    .git/info/exclude and core.excludesFile are uncommitted, so they do not count.
    """
    proc = _git(wt, "check-ignore", "-v", "-z", "--stdin", check=False, confine=confine,
                stdin=rel.encode("utf-8", "surrogateescape") + b"\0")
    fields = proc.stdout.split("\0")
    if proc.returncode != 0 or len(fields) < 4:
        return False
    source, _line, pattern = fields[0], fields[1], fields[2]
    if pattern.startswith("!"):
        return False  # with -v, a negation rule also "matches": the path is explicitly NOT ignored
    if Path(source).is_absolute() or not source.endswith(".gitignore"):
        return False
    tracked = _git(wt, "ls-files", "--error-unmatch", "--", source, check=False, confine=confine).returncode == 0
    clean = _git(wt, "diff", "--quiet", "--no-ext-diff", "HEAD", "--", source, check=False,
                 confine=confine).returncode == 0
    return tracked and clean


def _check_seed_destinations(wt: Path, project: Project) -> None:
    for rel in project.seed:
        link = _symlink_ancestor(wt, rel)
        if link:
            raise ProjectError(f"seed {rel!r}: worktree ancestor {link!r} is a symlink")


def _check_seed_source(project: Project, rel: str) -> None:
    """Every link followed while copying the seed must stay inside the project root."""
    root = project.path.resolve()
    src = project.path / rel
    if not src.exists() or not src.resolve().is_relative_to(root):
        raise ProjectError(f"seed {rel!r} is missing, dangling or resolves outside the project root")
    if not src.is_dir():
        return

    def walk(directory: Path, ancestors: frozenset) -> None:
        for entry in directory.iterdir():
            if entry.is_symlink():
                target = entry.resolve()
                if not target.exists():
                    raise ProjectError(f"seed {rel!r}: dangling link {entry}")
                if not target.is_relative_to(root):
                    raise ProjectError(f"seed {rel!r}: link {entry} points outside the project root")
            if entry.is_dir():  # follows links, as copytree(symlinks=False) will
                real = entry.resolve()
                if real in ancestors:
                    raise ProjectError(f"seed {rel!r}: symlink cycle at {entry}")
                walk(entry, ancestors | {real})

    walk(src, frozenset({src.resolve()}))


def _copy_seeds(wt: Path, project: Project) -> None:
    for rel in project.seed:
        src, dest = project.path / rel, wt / rel
        _check_seed_source(project, rel)
        if os.path.lexists(dest):
            raise ProjectError(f"seed {rel!r} collides with a path that already exists in the worktree")
        _check_seed_destinations(wt, project)
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            if src.is_dir():
                shutil.copytree(src, dest, symlinks=False)  # links become independent copies
            else:
                shutil.copy2(src, dest)  # follows a file link
        except (shutil.Error, OSError) as exc:
            raise ProjectError(f"seed {rel!r} could not be copied (dangling link?): {exc}") from exc
        if not _ignored_by_committed_rule(wt, rel, confine_for(project, wt)):
            raise ProjectError(f"seed {rel!r} is not ignored by the worktree's committed .gitignore rules")


def _is_worktree_of(project: Project, wt: Path) -> bool:
    """True only when `wt` is itself the top level of a worktree of this project's repo
    (a subdirectory of one does not count)."""
    if not wt.is_dir():
        return False
    mine = _git(project.path, "rev-parse", "--git-common-dir", check=False).stdout.strip()
    theirs = _git(wt, "rev-parse", "--git-common-dir", check=False).stdout.strip()
    top = _git(wt, "rev-parse", "--show-toplevel", check=False).stdout.strip()
    if not mine or not theirs or not top:
        return False
    return (project.path / mine).resolve() == (wt / theirs).resolve() and Path(top).resolve() == wt.resolve()


def _binding_path(project: Project, ident: str) -> Path:
    return WORKTREE_ROOT / project.key / ".meta" / f"{_check_ident(ident)}.json"


def load_binding(project: Project, ident: str) -> dict:
    """The worktree's persisted binding, validated against the live worktree (reuse and verify)."""
    wt, branch = worktree_path(project, ident), f"agent/{ident}"
    try:
        meta = json.loads(_binding_path(project, ident).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ProjectError(f"{project.key}/{ident}: worktree binding metadata is missing; run cleanup") from None
    if not isinstance(meta, dict) or meta.get("project_path") != str(project.path) or meta.get("branch") != branch:
        raise ProjectError(f"{project.key}/{ident}: worktree belongs to a different project or branch; run cleanup")
    actual = _git(wt, "symbolic-ref", "--short", "HEAD", check=False).stdout.strip()
    if actual != branch:
        raise ProjectError(f"{project.key}/{ident}: worktree is on {actual or 'a detached HEAD'}, not {branch}")
    base = meta.get("base_sha")
    if not isinstance(base, str) or _git(wt, "cat-file", "-e", f"{base}^{{commit}}", check=False).returncode != 0:
        raise ProjectError(f"{project.key}/{ident}: recorded base commit is missing; run cleanup")
    return meta


def mark_confidential(project: Project, ident: str) -> None:
    """Record in the worktree's sidecar that this ticket is confidential. Sticky: every entry
    point that runs its code (dashboard or `projects.py verify`) then confines it (I7-02).
    Caller holds ticket_lock."""
    path = _binding_path(project, ident)
    meta = json.loads(path.read_text(encoding="utf-8"))
    if meta.get("confidential") is not True:
        meta["confidential"] = True
        tmp = path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(meta, f)
        os.replace(tmp, path)


def sidecar_confidential(key: str, ident: str) -> bool | None:
    """The worktree sidecar's confidentiality, read without the ticket lock or git, so it is
    known before any fallible step (I9-01). None when it exists but cannot be read."""
    try:
        path = WORKTREE_ROOT / key / ".meta" / f"{_check_ident(ident)}.json"
    except ProjectError:
        return None
    if not path.exists():
        return False
    try:
        return bool(json.loads(path.read_text(encoding="utf-8")).get("confidential"))
    except (OSError, ValueError, AttributeError):
        return None


def effective(project: Project, meta: dict) -> Project:
    """The project policy for one ticket: confidential if the registry or its sidecar says so."""
    if meta.get("confidential") and not project.confidential:
        return dataclasses.replace(project, confidential=True)
    return project


def ticket_from_worktree(project: Project, worktree: Path) -> str:
    """The ticket id of an owned worktree: exactly <WORKTREE_ROOT>/<key>/<id>, nothing deeper."""
    wt = Path(worktree).expanduser().resolve()
    owned_root = (WORKTREE_ROOT / project.key).resolve()
    if wt.parent != owned_root or not _is_worktree_of(project, wt):
        raise ProjectError(f"{wt} is not a worktree AgenticOS created for {project.key}")
    return _check_ident(wt.name)


def create_worktree(project: Project, ident: str) -> dict:
    """Create (or reuse, for rework) the ticket's worktree. Caller holds ticket_lock."""
    wt = worktree_path(project, ident)
    branch = f"agent/{ident}"
    if wt.exists():
        if not _is_worktree_of(project, wt):
            raise ProjectError(f"{wt} exists but is not a worktree of {project.key}")
        meta = load_binding(project, ident)
        _check_seed_destinations(wt, project)
        for rel in project.seed:  # a reused worktree must still hold every seed, still ignored
            if not os.path.lexists(wt / rel) or not _ignored_by_committed_rule(wt, rel, confine_for(project, wt)):
                raise ProjectError(f"{project.key}/{ident}: seed {rel!r} is missing or no longer ignored; run cleanup")
        return {"worktree": str(wt), "branch": branch, "base_sha": meta["base_sha"], "reused": True}
    missing = untracked_verify_targets(project)
    if missing:
        raise ProjectError(f"{project.key}: verify target(s) not committed at HEAD: {missing}; commit them first")
    if _git(project.path, "rev-parse", "--verify", "--quiet", branch, check=False).returncode == 0:
        raise ProjectError(f"branch {branch} already exists without its worktree; run cleanup first")
    base = _git(project.path, "rev-parse", "HEAD").stdout.strip()
    wt.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    _git(project.path, "worktree", "add", "-b", branch, str(wt), base, confine=confine_for(project, wt))
    try:
        os.chmod(wt, 0o700)
        _copy_seeds(wt, project)
        # The binding is the "ready" marker: written only once every seed is copied and checked.
        meta = _binding_path(project, ident)
        meta.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(meta, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump({"project_path": str(project.path), "branch": branch, "base_sha": base,
                       "created_at": time.time(), "confidential": project.confidential}, f)
    except BaseException as exc:
        with contextlib.suppress(Exception):
            remove_worktree(project, ident)
        if isinstance(exc, OSError):
            raise ProjectError(f"{project.key}/{ident}: worktree setup failed: {exc}") from exc
        raise
    return {"worktree": str(wt), "branch": branch, "base_sha": base, "reused": False}


def remove_worktree(project: Project, ident: str) -> None:
    """Remove the worktree and its branch. Caller holds ticket_lock."""
    wt = worktree_path(project, ident)
    if os.path.lexists(wt):
        if not _is_worktree_of(project, wt):
            raise ProjectError(f"{wt} is not a worktree of {project.key}; refusing to delete it")
        # On failure this raises and the directory (and any uncommitted work) stays put.
        _git(project.path, "worktree", "remove", "--force", str(wt), confine=confine_for(project, wt))
    _git(project.path, "worktree", "prune", check=False)
    branch = f"agent/{ident}"
    if _git(project.path, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", check=False).returncode == 0:
        _git(project.path, "branch", "-D", branch)
    _binding_path(project, ident).unlink(missing_ok=True)


def runner_commit(project: Project, wt: Path, message: str) -> str | None:
    """Commit the agent's uncommitted changes on its branch (sandboxed Codex cannot write .git).

    Caller holds ticket_lock and has reaped the agent. Unsigned, hooks off, 60 s cap.
    Returns the new commit sha, or None when there was nothing to commit.
    """
    load_binding(project, ticket_from_worktree(project, wt))  # still the bound branch (I5-10)
    confine = confine_for(project, wt)
    # Staging can run repo-configured clean filters, so it is bounded like the commit.
    _git(wt, "add", "-A", confine=confine, timeout=COMMIT_TIMEOUT_S)
    if _git(wt, "diff", "--cached", "--quiet", "--no-ext-diff", check=False, confine=confine).returncode == 0:
        return None
    _git(wt, "commit", "--no-verify", "--no-gpg-sign", "-q", "-m", message, confine=confine, timeout=COMMIT_TIMEOUT_S,
         env=_identity_env(wt))
    return _git(wt, "rev-parse", "HEAD").stdout.strip()


def _identity_env(cwd: Path) -> dict | None:
    """A fallback committer when the repo has none configured."""
    if _git(cwd, "config", "user.email", check=False).stdout.strip():
        return None
    return {**os.environ, "GIT_AUTHOR_NAME": "AgenticOS", "GIT_AUTHOR_EMAIL": "agentic-os@localhost",
            "GIT_COMMITTER_NAME": "AgenticOS", "GIT_COMMITTER_EMAIL": "agentic-os@localhost"}


_MERGE_LOCK = threading.Lock()  # ponytail: one per process; runs of different projects rarely finish at once


def branch_head(project: Project, ident: str) -> str:
    """The commit agent/<ident> points at now: what a queued merge must merge (SC-007)."""
    return _git(project.path, "rev-parse", "--verify", f"refs/heads/agent/{_check_ident(ident)}^{{commit}}",
                confine=confine_for(project, project.path)).stdout.strip()


def commit_state(project: Project, cwd: str | Path) -> dict | None:
    """What the session row's Commit button reflects, read-only: {state, files, ahead}.
    dirty = uncommitted changes; unmerged = a clean worktree whose agent/<id> has commits the
    main checkout's HEAD lacks; clean = nothing to commit and nothing left to merge. None when
    the folder is not this project's checkout or worktree (the button stays neutral)."""
    top = _git(Path(cwd), "rev-parse", "--show-toplevel", check=False)
    if top.returncode:
        return None
    repo = Path(top.stdout.strip()).resolve()
    ident = None
    if repo != project.path.resolve():
        try:
            ident = ticket_from_worktree(project, repo)
        except ProjectError:
            return None
    files = len(readonly_status(repo))  # write-nothing sandbox: status can run clean filters (SC-011)
    if files:
        return {"state": "dirty", "files": files, "ahead": 0}
    ahead = 0
    if ident:
        r = _git(project.path, "rev-list", "--count", f"HEAD..refs/heads/agent/{ident}", check=False)
        ahead = int(r.stdout.strip() or 0) if r.returncode == 0 else 0
    return {"state": "unmerged" if ahead else "clean", "files": 0, "ahead": ahead}


def check_queued_merge(project: Project, ident: str, sha: str) -> None:
    """A queued (ticket, verified sha) is still that ticket's work: its binding exists and its
    branch still contains the sha. Cleanup or a replaced branch refuses the merge (SC-009).
    Caller holds the ticket's lock."""
    load_binding(project, ident)  # raises when the worktree/binding was cleaned up
    if _git(project.path, "merge-base", "--is-ancestor", sha, f"refs/heads/agent/{_check_ident(ident)}",
            check=False, confine=confine_for(project, project.path)).returncode:
        raise ProjectError(f"agent/{ident} no longer contains the verified commit; merge it by hand")


def merge_into_checkout(project: Project, ident: str, rev: str | None = None) -> str:
    """Merge agent/<ident> into the branch the main checkout has checked out (AGE-111).

    Only a conflict-free merge is made: merge-tree checks first, so no merge is ever left
    half done and no `merge --abort` can touch the user's own uncommitted edits. Git itself
    refuses when the merge would overwrite a local change. Returns the checkout's new HEAD."""
    branch = f"agent/{_check_ident(ident)}"
    if rev is not None and not re.fullmatch(r"[0-9a-f]{40}([0-9a-f]{24})?", rev):
        raise ProjectError(f"not a commit id: {rev!r}")
    target = rev or branch  # rev: the commit that passed verification, not whatever the branch holds now
    root = project.path
    confine = confine_for(project, root)
    with _MERGE_LOCK:
        if _git(root, "symbolic-ref", "-q", "HEAD", check=False, confine=confine).returncode:
            raise ProjectError(f"{root} is on a detached HEAD; merge {branch} by hand")
        if _git(root, "merge-tree", "--write-tree", "HEAD", target, check=False, confine=confine).returncode:
            raise ProjectError(f"{branch} conflicts with {root}; merge it by hand")
        _git(root, "merge", "--no-edit", "--no-verify", "--no-gpg-sign", "-q", "-m", f"Merge branch '{branch}'",
             target, confine=confine, timeout=COMMIT_TIMEOUT_S, env=_identity_env(root))
        return _git(root, "rev-parse", "HEAD", confine=confine).stdout.strip()


def commit_checkout(project: Project, cwd: str | Path, message: object = "", dry_run: bool = False) -> dict:
    """The user's manual Commit on a session row: stage every change in the session's checkout
    (the project's folder or one of its AgenticOS worktrees) and commit it locally. Never pushes.
    A dry run only reports {repo, branch, files}. Hooks off and unsigned, like runner_commit."""
    top = _git(Path(cwd), "rev-parse", "--show-toplevel", check=False)
    if top.returncode:
        raise ProjectError(f"{cwd} is not inside a git checkout")
    repo = Path(top.stdout.strip()).resolve()
    ident = None
    if repo != project.path.resolve():
        ident = ticket_from_worktree(project, repo)  # refuses anything else (a nested or foreign repo)
    msg = message.strip() if isinstance(message, str) else ""
    if not dry_run and not msg:
        raise ProjectError("a commit message is required")
    # Always sandboxed, whatever the policy says: staging can run repo-configured clean filters,
    # and a policy read before the ticket lock could be stale by the time git runs (SC-006).
    common = _git(project.path, "rev-parse", "--git-common-dir").stdout.strip()
    confine = [(project.path / common).resolve(), repo]
    with contextlib.ExitStack() as stack:
        if ident:
            stack.enter_context(ticket_lock(project.key, ident))  # a run, verify or terminal owns it now
        elif not _MERGE_LOCK.acquire(blocking=False):
            raise TicketLocked(f"a merge into {repo} is in progress; try again in a moment")
        else:
            stack.callback(_MERGE_LOCK.release)
        if _git(repo, "symbolic-ref", "-q", "HEAD", check=False, confine=confine).returncode:
            raise ProjectError(f"{repo} is on a detached HEAD; commit there by hand")
        busy = _git_operation(repo, confine)
        if busy:  # git add -A would mark conflicts resolved and commit their markers (SC-003)
            raise ProjectError(f"{repo} has {busy} in progress; finish or abort it by hand first")
        branch = _git(repo, "symbolic-ref", "--short", "HEAD", confine=confine).stdout.strip()
        files = readonly_status(repo)  # preview and count: nothing writable (SC-011)
        out = {"repo": str(repo), "branch": branch, "files": files}
        if dry_run or not files:
            return {**out, "committed": None}
        _git(repo, "add", "-A", confine=confine, timeout=COMMIT_TIMEOUT_S)
        if _git(repo, "diff", "--cached", "--quiet", "--no-ext-diff", check=False, confine=confine).returncode == 0:
            return {**out, "committed": None}
        _git(repo, "commit", "--no-verify", "--no-gpg-sign", "-q", "-m", msg, confine=confine,
             timeout=COMMIT_TIMEOUT_S, env=_identity_env(repo))
        return {**out, "committed": _git(repo, "rev-parse", "HEAD", confine=confine).stdout.strip()}


def _git_operation(repo: Path, confine: list[Path] | None) -> str | None:
    """An unfinished merge / cherry-pick / revert / rebase, or unmerged index entries, else None."""
    for ref, what in (("MERGE_HEAD", "a merge"), ("CHERRY_PICK_HEAD", "a cherry-pick"), ("REVERT_HEAD", "a revert")):
        if _git(repo, "rev-parse", "-q", "--verify", ref, check=False, confine=confine).returncode == 0:
            return what
    for d in ("rebase-merge", "rebase-apply"):
        p = _git(repo, "rev-parse", "--git-path", d, confine=confine).stdout.strip()
        if (repo / p if not os.path.isabs(p) else Path(p)).exists():
            return "a rebase"
    if _git(repo, "--no-optional-locks", "ls-files", "-u", confine=confine).stdout.strip():
        return "unresolved conflicts"
    return None


def committed_seeds(project: Project, wt: Path, base: str) -> list[str]:
    """Seed paths touched by commits base..HEAD in the worktree (=> badge `seed committed`)."""
    confine = confine_for(project, wt)
    names = []
    for commit in _git(wt, "rev-list", f"{base}..HEAD", confine=confine).stdout.split():
        # -m: a merge is diffed against each parent, so a file introduced only by the
        # merge result is seen. -z output is pure NUL-separated names (exact bytes).
        raw = _git_bytes(wt, "diff-tree", "-r", "-m", "--root", "-z", "--name-only", "--no-commit-id", commit,
                         confine=confine)
        names += [n.decode("utf-8", "surrogateescape") for n in raw.split(b"\0") if n]
    hits = set()
    for name in names:
        for rel in project.seed:
            if name == rel or name.startswith(rel.rstrip("/") + "/"):
                hits.add(rel)
    return sorted(hits)


# ── Main-checkout fingerprint ────────────────────────────────────────────────

def _git_bytes(cwd: Path, *args: str, confine: list[Path] | None = None,
               hardening: tuple = _GIT_HARDENING) -> bytes:
    try:
        code, out, err = _run_bounded(_git_argv(cwd, args, confine, hardening), GIT_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise ProjectError(f"git {args[0]} timed out in {cwd}") from None
    if code != 0:
        raise ProjectError(f"git {' '.join(args)} failed in {cwd}: {err.decode(errors='replace').strip()}")
    return out


def _stat_entry(path: Path, rel: str) -> list:
    st = path.lstat()
    return [rel, st.st_size, st.st_mode, st.st_mtime_ns]


# Claude Code makes this empty settings-staging dir in the main checkout's .claude/ even
# for a worktree run (seen with 2.1.300). Its contents and the settings files still count.
CLAUDE_STAGING = ".claude/.cc-writes"


def fingerprint(project: Project, exclude: set[str] = frozenset()) -> str:
    """Hash of everything an agent might change in the main checkout (Decision 1).

    HEAD, staged and unstaged diffs, every untracked/ignored file's (path, size, mode,
    mtime_ns), the effective git config and the effective hooks dir. `exclude` holds
    runner bookkeeping paths (relative); an entry ending in "/" excludes that whole directory.
    ponytail: ignored dirs are walked in full; a huge node_modules makes this slow, cache by
    dir mtime if it ever matters.
    """
    prefixes = tuple(e for e in exclude if e.endswith("/"))
    skip = lambda rel: rel in exclude or (rel + "/") in exclude or rel.startswith(prefixes)
    root = project.path
    confine = confine_for(project)
    g = lambda *a: _git_bytes(root, *a, confine=confine)
    h = hashlib.sha256()
    h.update(g("rev-parse", "HEAD"))
    h.update(_git_bytes(root, "symbolic-ref", "-q", "HEAD", confine=confine) if
             _git(root, "symbolic-ref", "-q", "HEAD", check=False, confine=confine).returncode == 0 else b"detached")
    # Shared refs every worktree can change (stash, other branches, tags); the ticket's own
    # agent/* branches and remote-tracking refs are expected to move.
    refs = g("for-each-ref", "--format=%(refname) %(objectname)")
    h.update(b"\n".join(l for l in refs.splitlines()
                        if not l.startswith((b"refs/heads/agent/", b"refs/remotes/"))))
    h.update(hashlib.sha256(g("ls-files", "-v", "-z")).digest())  # skip-worktree / assume-unchanged flags
    h.update(hashlib.sha256(g("diff", "--cached", "--binary", "--no-ext-diff", "--no-textconv")).digest())
    h.update(hashlib.sha256(g("diff", "--binary", "--no-ext-diff", "--no-textconv")).digest())
    files = []
    for entry in g("status", "--porcelain", "-z", "-uall", "--ignored=matching").split(b"\0"):
        if len(entry) < 4 or entry[:2] not in (b"??", b"!!"):
            continue
        rel = entry[3:].decode("utf-8", "surrogateescape").rstrip("/")
        if skip(rel):
            continue
        path = root / rel
        if path.is_dir() and not path.is_symlink():
            for dirpath, dirnames, filenames in os.walk(path):
                for name in sorted(dirnames + filenames):
                    sub = Path(dirpath) / name
                    r = sub.relative_to(root).as_posix()
                    if r == CLAUDE_STAGING and sub.is_dir() and not sub.is_symlink():
                        continue  # its own metadata only; anything inside still counts
                    if not skip(r):
                        files.append(_stat_entry(sub, r))
        elif os.path.lexists(path):
            files.append(_stat_entry(path, rel))
    h.update(json.dumps(sorted(files)).encode())
    h.update(g("config", "--list", "--show-origin", "--includes"))
    # The hardening's own core.hooksPath=/dev/null would hide the real hooks dir;
    # rev-parse runs no hooks, so only fsmonitor is switched off for this lookup.
    hooks = Path(_git_bytes(root, "rev-parse", "--git-path", "hooks", confine=confine,
                            hardening=("-c", "core.fsmonitor=false")).decode().strip())
    hooks = hooks if hooks.is_absolute() else root / hooks
    if hooks.is_dir():
        h.update(json.dumps(sorted(_stat_entry(f, f.name) for f in hooks.iterdir())).encode())
    return h.hexdigest()


# ── Verify ───────────────────────────────────────────────────────────────────

def verify_env(project: Project) -> dict:
    env = os.environ.copy()
    for k, v in project.env.items():
        env[k] = f"{v}{os.pathsep}{env.get('PATH', '')}" if k == "PATH" else v
    return env


def verify_writable_roots(wt: Path) -> list[Path]:
    """Verify needs no shared git writes: only the worktree and its own per-worktree git dir
    (index refresh). Hooks, config and refs in the common dir stay read-only (I4-05)."""
    return [wt, Path(_git(wt, "rev-parse", "--absolute-git-dir").stdout.strip())]


def uncommitted(project: Project, wt: Path, confine: list[Path] | None = None) -> list[str]:
    """Tracked or non-ignored untracked changes left in the worktree (seeds are ignored).
    Read-only: --no-optional-locks keeps status from refreshing the index (SC-004). `confine`
    overrides the policy's confinement (status can run clean filters, SC-008)."""
    out = _git_bytes(wt, "--no-optional-locks", "status", "--porcelain", "-z", "--untracked-files=all",
                     confine=confine if confine is not None else confine_for(project, wt))
    return _porcelain_paths(out)


def _porcelain_paths(out: bytes) -> list[str]:
    """Paths of `status --porcelain -z`: a rename/copy record is followed by its source path,
    a bare token that is consumed, not counted (SC-005)."""
    tokens, paths, i = out.split(b"\0"), [], 0
    while i < len(tokens):
        e = tokens[i]
        i += 1
        if len(e) > 3:
            paths.append(e[3:].decode("utf-8", "surrogateescape"))
            if e[0:1] in (b"R", b"C") or e[1:2] in (b"R", b"C"):
                i += 1  # the source path
    return paths


def run_verify(project: Project, worktree: Path, base: str | None = None, prefix: list[str] | None = None,
               on_start=None) -> dict:
    """Run the project's verify command in an owned worktree. Caller holds ticket_lock.

    Confidential projects run under the sandbox-exec profile (Decision 9) unless `prefix` is given.
    """
    if not project.verify:
        raise ProjectError(f"{project.key}: no verify command configured")
    wt = Path(worktree).expanduser().resolve()
    ident = ticket_from_worktree(project, wt)
    meta = load_binding(project, ident)  # exact owned worktree + valid binding
    project = effective(project, meta)
    if project.confidential and not meta.get("confidential"):
        mark_confidential(project, ident)  # a CLI-only promotion sticks too (I8-01)
    base = base or meta["base_sha"]
    cmd = project.verify.replace("{root}", shlex.quote(str(project.path)))
    if "{base}" in cmd:
        if not base:
            raise ProjectError(f"{project.key}: verify uses {{base}} but no --base was given")
        cmd = cmd.replace("{base}", shlex.quote(base))
    if prefix is None and project.confidential:
        prefix = sandbox_prefix(verify_writable_roots(wt))
    prefix = prefix or []
    argv = [*prefix, "/bin/sh", "-c", cmd]
    t0 = time.monotonic()
    proc = spawn(argv, cwd=wt, env=verify_env(project), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if on_start:
        on_start(proc)  # the caller can cancel this verify by killing its group
    # The exit status comes from wait(), not from stdout EOF: a background child that keeps
    # the pipe open must not turn a passing verify into a timeout (or hang a daemon read).
    chunks: list[bytes] = []
    reader = threading.Thread(target=lambda: chunks.extend(iter(lambda: proc.stdout.read(65536), b"")),
                              daemon=True)
    reader.start()
    status = "pass"
    try:
        proc.wait(timeout=project.verify_timeout_s)
    except subprocess.TimeoutExpired:
        status = "timeout"
    finally:
        reap(proc)  # timeout, Ctrl-C, cancel, or background children a finished verify left behind
    reader.join(timeout=5)  # ponytail: a setsid daemon holding the pipe is abandoned, not awaited
    out = b"".join(chunks)
    code = proc.returncode
    if status != "timeout" and code != 0:
        status = "fail"
    return {
        "status": status,
        "exit": 124 if status == "timeout" else code,
        "duration_s": round(time.monotonic() - t0, 1),
        "tail": out.decode("utf-8", "replace")[-TAIL_CHARS:],  # local only, never leaves the machine
    }


# ── Run-record location guard (Decision 4a) ─────────────────────────────────

def check_record_locations(paths: list[Path], checkout: Path, registry: dict[str, Project]) -> None:
    """With any confidential project registered, run records (which hold confidential prompts
    and outputs) must live inside this checkout and be ignored by its committed .gitignore.
    Raises ProjectError otherwise; the runner refuses to start (every writer is covered)."""
    if any(p.confidential for p in registry.values()):
        problem = record_location_problem(paths, checkout)
        if problem:
            raise ProjectError(problem)


def record_location_problem(paths: list[Path], checkout: Path) -> str | None:
    """Why these run-record paths may not hold confidential content, or None when they may.
    Also checked on every confidential launch (a registry edited after startup, I5-04)."""
    root = Path(checkout).resolve()
    for path in paths:
        resolved = Path(os.path.realpath(path))
        if not resolved.is_relative_to(root):
            return (f"run records at {path} are outside {root}; with confidential projects "
                    "registered they must stay in this checkout's gitignored state/ or outputs/")
        rel = resolved.relative_to(root).as_posix()
        if not _ignored_by_committed_rule(root, rel):
            return f"run records at {path} are not ignored by {root}'s committed .gitignore"
    return None


# ── Session readers (Phase 1: read-only) ─────────────────────────────────────
# ~/.claude and ~/.codex are read-only to AgenticOS, with two user-authorized exceptions
# (2026-10-15), both in "Session rename / remove" below: renaming a session (a custom-title
# record appended to a Claude transcript; threads.name for Codex) and removing one (the
# Claude transcript moves to ~/.agentic-os/session-trash; Codex threads are archived).

CLAUDE_PROJECTS = Path(os.environ.get("CLAUDE_CONFIG_DIR", "~/.claude")).expanduser() / "projects"
CODEX_DB = Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser() / "state_5.sqlite"
MAX_SESSIONS = 50


def _slug(path: Path | str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


def _under(cwd: str, roots: list[str]) -> bool:
    return any(cwd == r or cwd.startswith(r.rstrip("/") + "/") for r in roots)


def _under_resolved(cwd: str, roots: list[str]) -> bool:
    """_under on resolved paths: no `..` or escaping symlink passes (IR9-03)."""
    return _under(os.path.realpath(cwd), [os.path.realpath(r) for r in roots])


def _session_roots(project: Project) -> list[str]:
    return [str(project.path), str(WORKTREE_ROOT / project.key)]


def _user_text(msg: object) -> str:
    if not isinstance(msg, dict):
        return msg if isinstance(msg, str) else ""
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


_USER_LINE = re.compile(r'"type"\s*:\s*"user"')
_ASSISTANT_LINE = re.compile(r'"type"\s*:\s*"assistant"')


def _claude_summary(path: Path) -> dict | None:
    """One pass over a session JSONL. ponytail: only lines that can matter are json-parsed."""
    info = {"cwd": None, "entrypoint": None, "branch": None, "first": None,
            "custom": None, "ai": None, "messages": 0}
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                is_user = bool(_USER_LINE.search(line))
                if is_user or _ASSISTANT_LINE.search(line):
                    info["messages"] += 1
                if not (is_user or "-title" in line):
                    continue
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(e, dict):
                    continue  # valid JSON of the wrong shape: skip the record, keep the file
                t = e.get("type")
                s_ = lambda k: e.get(k) if isinstance(e.get(k), str) else None
                if t == "custom-title":
                    info["custom"] = s_("customTitle") or s_("title") or info["custom"]
                elif t == "ai-title":
                    info["ai"] = s_("aiTitle") or info["ai"]
                elif t == "user":
                    info["cwd"] = info["cwd"] or s_("cwd")
                    info["entrypoint"] = info["entrypoint"] or s_("entrypoint")
                    info["branch"] = s_("gitBranch") or info["branch"]
                    if info["first"] is None and not e.get("isMeta") and not e.get("toolUseResult"):
                        text = _user_text(e.get("message")).strip()
                        if text and not text.startswith("<"):
                            info["first"] = text[:200]
    except (OSError, TypeError, AttributeError):
        return None  # ponytail: an unexpected shape drops one session, never the whole view
    return info


def _headless_ok(agent: str, sid: str, board_ids) -> bool:
    """A headless session (claude -p / sdk, codex exec) is shown only when the runner launched
    it: its (agent, id) is in `board_ids`, built by app.py from its run records (STB §9)."""
    return bool(board_ids) and (agent, sid) in board_ids


def _with_label(row: dict, labels) -> dict:
    label = (labels or {}).get((row["agent"], row["id"]))
    if isinstance(label, dict):  # {"label": identifier, "title": the card's title}
        if label.get("title"):
            row["card_title"] = label["title"]  # a headless run's first message is the runner's preamble
        label = label.get("label")
    if label:
        row["label"] = label  # the card identifier, shown before the title (§9)
    return row


def claude_sessions(project: Project, board_ids=None, labels=None) -> list[dict]:
    from usage_reader import _cached_by_stat  # same per-file (mtime, size) cache as the usage cards
    roots = _session_roots(project)
    prefixes = [_slug(r) for r in roots]
    out = []
    if not CLAUDE_PROJECTS.is_dir():
        return out
    for d in CLAUDE_PROJECTS.iterdir():
        if not d.is_dir() or not any(d.name.startswith(p) for p in prefixes):
            continue
        for f in d.glob("*.jsonl"):
            try:
                st = f.stat()
            except OSError:
                continue
            try:
                info = _cached_by_stat("project_session", f, st, _claude_summary)
                if not info or not info["cwd"] or not _under(info["cwd"], roots):
                    continue
            except Exception:
                continue  # one odd session file never hides the rest
            if (info["entrypoint"] or "").startswith("sdk-") and not _headless_ok("claude", f.stem, board_ids):
                continue  # headless -p / SDK runs are shown only when the board launched them
            out.append(_with_label({
                "agent": "claude", "id": f.stem, "cwd": info["cwd"],
                "title": _claude_title(info),
                "updated": st.st_mtime, "branch": info["branch"], "messages": info["messages"],
                "resume": f"cd {shlex.quote(info['cwd'])} && claude --resume {shlex.quote(f.stem)}",
            }, labels))
    return out


def _claude_title(info: dict) -> str:
    return info["custom"] or info["ai"] or info["first"] or "untitled"


def _codex_title(name, title, first) -> str:
    return name or title or (first or "")[:200] or "untitled"


def claude_memory_names(project: Project) -> list[str]:
    mem = CLAUDE_PROJECTS / _slug(project.path) / "memory"
    return sorted(p.name for p in mem.glob("*.md")) if mem.is_dir() else []


def codex_sessions(project: Project, board_ids=None, labels=None) -> list[dict]:
    import sqlite3
    if not CODEX_DB.exists():
        return []
    roots = _session_roots(project)
    try:
        db = sqlite3.connect(f"file:{CODEX_DB}?mode=ro", uri=True)
        try:
            rows = db.execute(
                "SELECT id, cwd, name, title, first_user_message, updated_at, tokens_used, git_branch, source "
                "FROM threads WHERE archived = 0 AND source IN ('cli', 'vscode', 'exec')").fetchall()
        finally:
            db.close()
    except sqlite3.Error:
        return []  # format drift: degrade to no Codex rows, never crash the view
    out = []
    for tid, cwd, name, title, first, updated, tokens, branch, source in rows:
        if not isinstance(tid, str) or not isinstance(cwd, str) or not _under(cwd, roots):
            continue
        if source == "exec" and not _headless_ok("codex", tid, board_ids):
            continue  # `codex exec` threads are shown only when the board launched them (§9)
        name, title, first, branch = (v if isinstance(v, str) else None for v in (name, title, first, branch))
        try:
            updated = float(updated or 0)
        except (TypeError, ValueError):
            updated = 0.0
        out.append(_with_label({
            "agent": "codex", "id": tid, "cwd": cwd,
            "title": _codex_title(name, title, first),
            "updated": updated, "branch": branch, "tokens": tokens,
            "resume": f"cd {shlex.quote(cwd)} && codex resume {shlex.quote(tid)}",
        }, labels))
    return out


def _first_cwd(path: Path) -> str | None:
    """The cwd of a Claude session: the first line that carries one. Bounded: only the first
    256 KB are read (ponytail: a session whose cwd appears later is simply not suggested)."""
    with open(path, encoding="utf-8", errors="replace") as f:
        head = f.read(262144)
        for line in head.split("\n")[:200]:  # physical lines only: U+2028 is valid inside JSON (SAP-B006)
            if '"cwd"' not in line:
                continue
            try:
                cwd = json.loads(line).get("cwd")
            except (ValueError, AttributeError):
                continue
            if isinstance(cwd, str) and cwd:
                return cwd
    return None


# Throwaway temp repos (spikes, test fixtures) are never suggested as projects.
_TEMP_ROOTS = ("/tmp", "/private/tmp", "/var/folders", "/private/var/folders")
_TOPLEVEL: dict[str, str | None] = {}  # ponytail: per-process memo; restart the runner to forget


def _repo_root(cwd: str) -> str | None:
    if cwd not in _TOPLEVEL:
        top = None
        if os.path.isdir(cwd):
            proc = _git(Path(cwd), "rev-parse", "--show-toplevel", check=False, timeout=10)
            top = proc.stdout.strip() or None if proc.returncode == 0 else None
        _TOPLEVEL[cwd] = top
    return _TOPLEVEL[cwd]


def session_dirs(registered: list[Path], limit: int = 50) -> list[dict]:
    """Git repo roots seen in Claude/Codex session history that are not registered yet.
    Read-only; any reader failure just yields fewer rows."""
    from usage_reader import _cached_by_stat
    seen: dict[str, dict] = {}  # cwd -> {last_used, sessions, agents}

    def note(cwd: str, ts: float, agent: str, n: int = 1) -> None:
        row = seen.setdefault(cwd, {"last_used": 0.0, "sessions": 0, "agents": set()})
        row["last_used"] = max(row["last_used"], ts)
        row["sessions"] += n
        row["agents"].add(agent)

    with contextlib.suppress(OSError):
        for d in CLAUDE_PROJECTS.iterdir() if CLAUDE_PROJECTS.is_dir() else []:
            for f in d.glob("*.jsonl") if d.is_dir() else []:
                with contextlib.suppress(Exception):
                    st = f.stat()
                    cwd = _cached_by_stat("session_cwd", f, st, _first_cwd)
                    if cwd:
                        note(cwd, st.st_mtime, "claude")
    if CODEX_DB.exists():
        import sqlite3
        with contextlib.suppress(sqlite3.Error):
            db = sqlite3.connect(f"file:{CODEX_DB}?mode=ro", uri=True)
            try:
                for cwd, updated, n in db.execute(
                        "SELECT cwd, MAX(updated_at), COUNT(*) FROM threads WHERE archived = 0 GROUP BY cwd"):
                    if isinstance(cwd, str) and cwd:
                        with contextlib.suppress(TypeError, ValueError):
                            note(cwd, float(updated or 0), "codex", int(n or 0))
            finally:
                db.close()
    skip = [str(WORKTREE_ROOT.resolve()), *_TEMP_ROOTS]
    taken = {str(Path(p).resolve()) for p in registered}
    roots: dict[str, dict] = {}
    for cwd, row in seen.items():
        with contextlib.suppress(Exception):
            top = _repo_root(cwd)
            if not top:
                continue
            real = str(Path(top).resolve())
            if real in taken or _under(real, skip):
                continue
            agg = roots.setdefault(real, {"last_used": 0.0, "sessions": 0, "agents": set()})
            agg["last_used"] = max(agg["last_used"], row["last_used"])
            agg["sessions"] += row["sessions"]
            agg["agents"] |= row["agents"]
    home = str(Path.home())
    out = [{"path": "~" + p[len(home):] if p.startswith(home + "/") else p, "name": Path(p).name,
            "last_used": r["last_used"], "sessions": r["sessions"], "agents": sorted(r["agents"])}
           for p, r in roots.items()]
    out.sort(key=lambda r: r["last_used"], reverse=True)
    return out[:limit]


def project_sessions(project: Project, board_ids=None, labels=None) -> list[dict]:
    """`board_ids`: (agent, id) pairs the runner launched; `labels`: (agent, id) -> card
    identifier. Both are built by app.py, which this module never imports (§9)."""
    rows = claude_sessions(project, board_ids, labels) + codex_sessions(project, board_ids, labels)
    rows.sort(key=lambda r: r["updated"], reverse=True)
    return rows[:MAX_SESSIONS]


# ── Session rename / remove (the only writes to ~/.claude and ~/.codex) ──────

SESSION_TRASH = Path(os.environ.get("AGENTIC_OS_SESSION_TRASH", "~/.agentic-os/session-trash")).expanduser()
SESSION_FRESH_S = 120
_SESSION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,127}$")
_SESSION_LOCKS: dict[tuple[str, str], threading.Lock] = {}
_SESSION_LOCKS_GUARD = threading.Lock()


class SessionNotFound(ProjectError):
    """No such session in this project."""


class SessionBusy(ProjectError):
    """The session is live (a tab, a running job, or written in the last 2 minutes)."""


@contextlib.contextmanager
def session_lock(agent: str, sid: str):
    """Per-session admission lock: rename/remove hold it across check + write, and resume-tab
    opening and retry/quick-reply launch take it for their own admission. Non-blocking."""
    with _SESSION_LOCKS_GUARD:
        lock = _SESSION_LOCKS.setdefault((agent, sid), threading.Lock())
    if not lock.acquire(blocking=False):
        raise SessionBusy(f"session {sid} is busy (being renamed, removed or opened)")
    try:
        yield
    finally:
        lock.release()


def session_target(project: Project, agent: str, sid: str, board_ids=None) -> dict:
    """Resolve one session of this project: {agent, id, cwd, path, title} (path: transcript/rollout).
    Refuses unknown ids, ids with path characters, cwd outside the project, files outside the stores.
    A headless session resolves only when its (agent, id) is in `board_ids` (§9)."""
    if agent not in ("claude", "codex"):
        raise ProjectError(f"unknown agent {agent!r}")
    if not isinstance(sid, str) or not _SESSION_ID.match(sid):
        raise ProjectError(f"session id {sid!r} is not valid")
    roots = _session_roots(project)
    if agent == "claude":
        store = CLAUDE_PROJECTS.resolve() if CLAUDE_PROJECTS.is_dir() else None
        prefixes = [_slug(r) for r in roots]
        for d in (CLAUDE_PROJECTS.iterdir() if store else []):
            f = d / f"{sid}.jsonl"
            if not d.is_dir() or not any(d.name.startswith(p) for p in prefixes) or not f.is_file() or f.is_symlink():
                continue
            if not f.resolve().is_relative_to(store):
                continue
            info = _claude_summary(f)
            if (info and info["cwd"] and _under_resolved(info["cwd"], roots)
                    and (not (info["entrypoint"] or "").startswith("sdk-") or _headless_ok(agent, sid, board_ids))):
                return {"agent": agent, "id": sid, "cwd": info["cwd"], "path": f, "title": _claude_title(info)}
        raise SessionNotFound(f"no Claude session {sid} in project {project.key}")
    import sqlite3
    db_path = _codex_db_checked()
    try:
        db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
        try:
            sources = ("cli", "vscode", "exec") if _headless_ok(agent, sid, board_ids) else ("cli", "vscode")
            row = db.execute("SELECT cwd, rollout_path, name, title, first_user_message FROM threads "
                             f"WHERE id = ? AND archived = 0 AND source IN ({','.join('?' * len(sources))})",
                             (sid, *sources)).fetchone()
        finally:
            db.close()
    except sqlite3.Error as exc:
        raise ProjectError(f"Codex session store unreadable: {exc}") from None
    if not row or not isinstance(row[0], str) or not _under_resolved(row[0], roots):
        raise SessionNotFound(f"no Codex session {sid} in project {project.key}")
    rollout = Path(row[1]) if isinstance(row[1], str) and row[1] else None
    store = Path(os.path.realpath(CODEX_DB.parent))
    if rollout is None or not Path(os.path.realpath(rollout)).is_relative_to(store):
        # its idleness cannot be checked inside the Codex store: refuse rather than guess (IR9-03)
        raise ProjectError(f"Codex session {sid} has no rollout inside {store}; not touched")
    texts = [v if isinstance(v, str) else None for v in row[2:5]]
    return {"agent": agent, "id": sid, "cwd": row[0], "path": rollout, "title": _codex_title(*texts)}


def find_session(agent: str, sid: str) -> dict | None:
    """A session the runner itself launched or bound (its id comes from run records, never from
    a client): {agent, id, cwd, path, title, native_title}, or None. Store-confined like
    session_target, but with no project-root check. native_title is the name the agent's picker
    shows (Claude's newest custom-title, Codex threads.name), None when unset (DP-30)."""
    if agent not in ("claude", "codex") or not isinstance(sid, str) or not _SESSION_ID.match(sid):
        return None
    if agent == "claude":
        if not CLAUDE_PROJECTS.is_dir():
            return None
        store = CLAUDE_PROJECTS.resolve()
        for d in CLAUDE_PROJECTS.iterdir():
            f = d / f"{sid}.jsonl"
            if not d.is_dir() or not f.is_file() or f.is_symlink() or not f.resolve().is_relative_to(store):
                continue
            info = _claude_summary(f)
            if info and info["cwd"]:
                return {"agent": agent, "id": sid, "cwd": info["cwd"], "path": f,
                        "title": _claude_title(info), "native_title": info["custom"]}
        return None
    import sqlite3
    try:
        db = sqlite3.connect(f"file:{_codex_db_checked()}?mode=ro", uri=True, timeout=5)
        try:
            row = db.execute("SELECT cwd, rollout_path, name, title, first_user_message FROM threads "
                             "WHERE id = ? AND archived = 0", (sid,)).fetchone()
        finally:
            db.close()
    except (sqlite3.Error, ProjectError):
        return None
    if not row or not isinstance(row[0], str) or not isinstance(row[1], str) or not row[1]:
        return None
    store = Path(os.path.realpath(CODEX_DB.parent))
    rollout = Path(os.path.realpath(row[1]))
    if not rollout.is_relative_to(store) or not rollout.is_file() or not os.access(rollout, os.R_OK):
        return None  # a thread row whose rollout is gone is not resumable (R6)
    texts = [v if isinstance(v, str) else None for v in row[2:5]]
    return {"agent": agent, "id": sid, "cwd": row[0], "path": Path(row[1]),
            "title": _codex_title(*texts), "native_title": texts[0] or None}


def session_file(agent: str, sid: str) -> Path | None:
    """The transcript/rollout of a runner-known session, path only: find_session's store
    confinement without reading the file (a poll target; CTX-003)."""
    if agent == "codex":
        found = find_session(agent, sid)  # DB row + a stat, no file scan
        return found["path"] if found else None
    if agent != "claude" or not isinstance(sid, str) or not _SESSION_ID.match(sid) or not CLAUDE_PROJECTS.is_dir():
        return None
    store = CLAUDE_PROJECTS.resolve()
    found = [f for d in CLAUDE_PROJECTS.iterdir() for f in [d / f"{sid}.jsonl"]
             if d.is_dir() and f.is_file() and not f.is_symlink() and f.resolve().is_relative_to(store)]
    # the same id can sit under an old and a new checkout's folder: the one written last is live (CTX-008)
    return max(found, key=lambda f: (f.stat().st_mtime_ns, str(f)), default=None)


def session_name_text(title: object) -> str:
    """A card title as a session name: control characters as spaces, whitespace collapsed,
    at most 200 characters; '' when nothing is left (§Definitions)."""
    if not isinstance(title, str):
        return ""
    text = "".join(" " if unicodedata.category(c) == "Cc" else c for c in title)
    return " ".join(text.split())[:200].strip()


def check_session_idle(target: dict, live_ids: set[tuple[str, str]], now: float | None = None) -> None:
    """Refuse a live session: held by a terminal or running job (`live_ids` of (agent, id)), or
    its transcript/rollout written in the last SESSION_FRESH_S seconds."""
    if (target["agent"], target["id"]) in live_ids:
        raise SessionBusy(f"session {target['id']} is open in a terminal or a running job")
    path = target.get("path")
    with contextlib.suppress(OSError):
        if path is not None and (now or time.time()) - path.stat().st_mtime < SESSION_FRESH_S:
            raise SessionBusy(f"session {target['id']} was written in the last 2 minutes; try again when it is idle")


def _clean_title(title: object) -> str:
    if not isinstance(title, str):
        raise ProjectError("title must be text")
    title = title.strip()
    if not 1 <= len(title) <= 200 or any(unicodedata.category(c) == "Cc" for c in title):
        raise ProjectError("title must be 1-200 characters with no control characters")
    return title


def rename_session(target: dict, title: object) -> str:
    """Claude: append one custom-title record (what /rename writes); a short or failed write is
    truncated back so no partial record survives. Codex: threads.name in one transaction."""
    title = _clean_title(title)
    if target["agent"] == "claude":
        path = target["path"]
        line = (json.dumps({"type": "custom-title", "customTitle": title, "sessionId": target["id"]},
                           ensure_ascii=False, separators=(",", ":")) + "\n").encode()
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW)
        try:
            st = os.fstat(fd)
            size = st.st_size
            try:
                written = os.write(fd, line)
                if written != len(line):
                    raise OSError(f"short write ({written} of {len(line)} bytes)")
            except BaseException:
                os.ftruncate(fd, size)  # safe: a live session is refused, nothing else appends
                raise
            # Keep the times: our own write must not make the session look live (2-minute rule)
            # or jump to the top of claude --resume (FB-03).
            os.utime(fd, ns=(st.st_atime_ns, st.st_mtime_ns))
        finally:
            os.close(fd)
        return title
    # Codex: threads.name in one database transaction — committed whole or not at all. The shared
    # session_index.jsonl is never written: Codex appends to it concurrently and there is no way to
    # coordinate with it, so a failure could corrupt other sessions' entries (R24-01).
    with CODEX_STORE_LOCK:
        _codex_update("UPDATE threads SET name = ? WHERE id = ? AND archived = 0", (title, target["id"]))
    return title


CODEX_STORE_LOCK = threading.Lock()  # serializes the dashboard's Codex renames and archives


def _codex_store_child(name: str) -> Path:
    """A path directly inside the resolved Codex store; refused if it is (or leads through) a
    symlink out of it (CR-02)."""
    store = Path(os.path.realpath(CODEX_DB.parent))
    path = store / name
    if path.is_symlink() or Path(os.path.realpath(path)).parent != store:
        raise ProjectError(f"{path} leads outside the Codex store; not touched")
    return path


def _codex_db_checked() -> Path:
    """The Codex database, resolved, only if it stays inside the Codex store: a symlink to a
    database elsewhere is refused before anything is read or written (UI10-04)."""
    store = Path(os.path.realpath(CODEX_DB.parent))
    real = Path(os.path.realpath(CODEX_DB))
    if real.parent != store:
        raise ProjectError(f"{CODEX_DB} leads outside the Codex store ({real}); not touched")
    return real


def _codex_update(sql: str, args: tuple, require_row: bool = True) -> None:
    import sqlite3
    try:
        db = sqlite3.connect(str(_codex_db_checked()), timeout=5)
        try:
            with db:  # one transaction: committed whole or rolled back
                if db.execute(sql, args).rowcount != 1 and require_row:
                    raise SessionNotFound("Codex session changed meanwhile (archived or gone)")
        finally:
            db.close()
    except sqlite3.Error as exc:
        raise ProjectError(f"Codex session store write failed: {exc}") from None


def remove_session(target: dict) -> dict:
    """Never a hard delete. Codex: archive the thread. Claude: move the transcript, then its
    same-named sidecar folder, into SESSION_TRASH/<slug>/; a failed second move puts the
    transcript back. A trash on another filesystem is refused before anything moves."""
    if target["agent"] == "codex":
        with CODEX_STORE_LOCK:
            return _archive_codex(target)
    return _trash_claude(target)


def _archive_codex(target: dict) -> dict:
    # What Codex's own archive does: the rollout moves into archived_sessions/ and the row is
    # archived with its new path (FB4-02). The move is undone if the database update fails.
    rollout = target["path"]
    archived_dir = _codex_store_child("archived_sessions")  # never a symlink out of the store (CR-02)
    dest = archived_dir / rollout.name
    if dest.exists() or dest.is_symlink():
        raise ProjectError(f"{dest} already exists; not touched")
    archived_dir.mkdir(exist_ok=True)
    os.rename(rollout, dest)
    try:
        _codex_update("UPDATE threads SET archived = 1, archived_at = ?, rollout_path = ? WHERE id = ? AND archived = 0",
                      (int(time.time()), str(dest), target["id"]))
    except BaseException:
        os.rename(dest, rollout)
        raise
    return {"archived": True, "rollout": str(dest)}


def _trash_claude(target: dict) -> dict:
    src = target["path"]
    sidecar = src.with_suffix("")
    dest_dir = SESSION_TRASH / src.parent.name
    dest, dest_side = dest_dir / src.name, dest_dir / sidecar.name
    if dest.exists() or dest_side.exists():
        raise ProjectError(f"{dest_dir} already holds a session named {target['id']}; move it away first")
    dest_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.stat(dest_dir).st_dev != os.stat(src).st_dev:
        raise ProjectError(f"{SESSION_TRASH} is on another filesystem than {src.parent}; refusing to copy")
    os.rename(src, dest)
    if sidecar.is_dir() and not sidecar.is_symlink():
        try:
            os.rename(sidecar, dest_side)
        except OSError:
            os.rename(dest, src)  # put the transcript back: the session stays exactly as it was
            raise
    return {"trash": str(dest)}


# ── File browser (read-only) ─────────────────────────────────────────────────
# Listing follows git, never a raw walk. Nothing here writes: GIT_OPTIONAL_LOCKS=0 keeps
# `git status` from refreshing the index of a worktree an agent is using.

BROWSE_CAP = 2000
PREVIEW_LIMIT = 200_000


def browse_worktrees(project: Project) -> list[str]:
    """'main' plus the agent worktree ids of this project (plain dirs only)."""
    root = WORKTREE_ROOT / project.key
    return ["main", *[n for n in _worktree_dirs(project.key) if not (root / n).is_symlink() and _IDENT.match(n)]]


def _browse_root(project: Project, wt: str | None) -> tuple[Path, list[Path] | None]:
    if wt in (None, "", "main"):
        return project.path.resolve(), ([] if project.confidential else None)
    root = worktree_path(project, wt)
    if root.is_symlink() or not _is_worktree_of(project, root):
        raise ProjectError(f"{wt} is not a worktree of {project.key}")
    confidential = project.confidential or sidecar_confidential(project.key, wt) is not False
    return root.resolve(), ([] if confidential else None)


def _browse_path(root: Path, rel: str | None) -> tuple[str, Path]:
    """(clean rel, resolved path) inside root; refuses absolute, `..`, `.git` and escaping links."""
    rel = rel or ""
    if "\0" in rel or rel.startswith(("~", "/")):
        raise ProjectError(f"path {rel!r} is not relative to the checkout")
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts) or (parts and parts[0] == ".git"):
        raise ProjectError(f"path {rel!r} is outside the checkout")
    real = (root / "/".join(parts)).resolve()
    if real != root and not real.is_relative_to(root):
        raise ProjectError(f"path {rel!r} leads outside the checkout")
    return "/".join(parts), real


def _browse_env() -> dict:
    return {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}


def _browse_git(root: Path, confine: list[Path] | None, *args: str) -> subprocess.CompletedProcess:
    return _git(root, *args, check=False, confine=confine, timeout=30, env=_browse_env())


class _Entry:
    """A directory entry's type and size, captured while its directory descriptor is open: a
    DirEntry from scandir(fd) needs that descriptor for any later stat (REV32-01)."""
    __slots__ = ("name", "_dir", "_link", "_size")

    def __init__(self, e: os.DirEntry):
        self.name = e.name
        try:
            self._link = e.is_symlink()
            self._dir = e.is_dir(follow_symlinks=False)
        except OSError:
            self._link, self._dir = False, False
        try:
            self._size = e.stat(follow_symlinks=False).st_size
        except OSError:
            self._size = None

    def is_dir(self, follow_symlinks: bool = True) -> bool:
        return self._dir

    def is_symlink(self) -> bool:
        return self._link

    def size(self) -> int | None:
        return self._size


def list_dir(project: Project, wt: str | None, rel: str | None) -> dict:
    """One level of the checkout: {entries: [{name, kind, size, status, ignored}], more}."""
    root, confine = _browse_root(project, wt)
    rel, target = _browse_path(root, rel)
    if target != root and (target.is_symlink() or not target.is_dir()):
        raise ProjectError(f"{rel!r} is not a folder")
    prefix = rel + "/" if rel else ""
    if rel and _check_ignored(root, confine, [rel + "/"]):
        raise ProjectError(f"{rel!r} is ignored by git; its contents are not listed")
    ls = _browse_git(root, confine, "ls-files", "--cached", "--others", "--exclude-standard",
                     "--directory", "--no-empty-directory", "-z", "--", prefix or ".")
    if ls.returncode != 0:
        raise ProjectError(f"git ls-files failed in {root}: {ls.stderr.strip()}")
    names: dict[str, bool] = {}  # child name -> is a folder
    collapsed = False  # git folded this whole folder into one untracked entry (UI8-02)
    for path in filter(None, ls.stdout.split("\0")):
        if not path.startswith(prefix):
            continue
        if prefix and path == prefix:
            collapsed = True
            continue
        head, sep, _rest = path[len(prefix):].partition("/")
        if head and head != ".git":
            names[head] = names.get(head, False) or bool(sep)
    status: dict[str, str] = {}
    st = _browse_git(root, confine, "status", "--porcelain", "-z", "--untracked-files=all", "--", prefix or ".")
    tokens = st.stdout.split("\0") if st.returncode == 0 else []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        i += 1
        if len(tok) < 4:
            continue
        xy, path = tok[:2], tok[3:]
        if xy[0] in "RC":
            i += 1  # the rename source follows
        if path.startswith(prefix):
            head = path[len(prefix):].split("/", 1)[0]
            status.setdefault(head, "?" if xy == "??" else (xy.strip() or "M")[0])
    try:
        dfd = _open_confined(root, target, directory=True)  # list what was actually opened (REV31-01)
        try:
            with os.scandir(dfd) as it:  # metadata read while the descriptor is open (REV32-01)
                on_disk = {e.name: _Entry(e) for e in it}
        finally:
            os.close(dfd)
    except OSError as exc:
        raise ProjectError(f"cannot read {rel or '.'}: {exc}") from None
    if collapsed:  # every child of a wholly untracked folder is untracked unless git ignores it
        kids = {n: prefix + n + ("/" if e.is_dir(follow_symlinks=False) else "") for n, e in on_disk.items() if n != ".git"}
        ignored_kids = _check_ignored(root, confine, list(kids.values()))
        for n, rel_n in kids.items():
            if rel_n not in ignored_kids:
                names[n] = on_disk[n].is_dir(follow_symlinks=False)
                status.setdefault(n, "?")
    extra = [n for n in on_disk if n not in names and n != ".git"]
    ignored = _check_ignored(root, confine, [prefix + n + ("/" if on_disk[n].is_dir(follow_symlinks=False) else "")
                                             for n in extra])
    entries = []
    for name in [*names, *extra]:
        e = on_disk.get(name)
        is_ign = name not in names
        if is_ign and (prefix + name + ("/" if e and e.is_dir(follow_symlinks=False) else "")) not in ignored:
            continue  # neither listed by git nor ignored: an empty folder
        if e is None:
            kind, size = "file", None  # tracked but deleted on disk
        elif e.is_symlink():
            kind, size = "link", None  # listed, never followed
        elif e.is_dir():
            kind, size = "dir", None
        else:
            kind, size = "file", e.size()
        entries.append({"name": name, "kind": kind, "size": size, "status": status.get(name, ""), "ignored": is_ign})
    entries.sort(key=lambda x: (x["kind"] != "dir", x["name"].lower()))
    return {"path": rel, "entries": entries[:BROWSE_CAP], "more": max(0, len(entries) - BROWSE_CAP)}


def _check_ignored(root: Path, confine: list[Path] | None, rels: list[str]) -> set[str]:
    """The subset of `rels` git ignores (a trailing / marks a folder)."""
    if not rels:
        return set()
    proc = _git(root, "check-ignore", "-z", "--stdin", check=False, confine=confine, timeout=30,
                env=_browse_env(), stdin="\0".join(rels).encode() + b"\0")
    return set(filter(None, proc.stdout.split("\0"))) if proc.returncode in (0, 1) else set()


def _open_confined(root: Path, real: Path, directory: bool = False) -> int:
    """Open `real` and prove the *opened* object is inside `root`: its path is read back from the
    descriptor (macOS F_GETPATH), so a file or ancestor swapped for an escaping symlink between
    the check and the open is refused (REV31-01). The final component is never followed."""
    import fcntl
    flags = os.O_RDONLY | os.O_NOFOLLOW | (os.O_DIRECTORY if directory else 0)
    try:
        fd = os.open(real, flags)
    except OSError as exc:
        raise ProjectError(f"cannot open {real.name}: {exc.strerror}") from None
    try:
        opened = Path(os.fsdecode(fcntl.fcntl(fd, fcntl.F_GETPATH, bytes(1024)).rstrip(b"\0")))
        opened = Path(os.path.realpath(opened))
        if opened != root and not opened.is_relative_to(root):
            raise ProjectError("path leads outside the checkout")
        if not directory and not stat_module.S_ISREG(os.fstat(fd).st_mode):
            raise ProjectError(f"{real.name} is not a regular file")
    except BaseException:
        os.close(fd)
        raise
    return fd


def read_file(project: Project, wt: str | None, rel: str | None, limit: int = PREVIEW_LIMIT) -> dict:
    """Read-only preview: text for a text file up to `limit` bytes; size and type otherwise."""
    import mimetypes
    root, _confine = _browse_root(project, wt)
    rel, real = _browse_path(root, rel)
    if not real.is_file():
        raise ProjectError(f"{rel!r} is not a file")
    fd = _open_confined(root, real)  # checked again on what was actually opened (REV31-01)
    with os.fdopen(fd, "rb") as f:
        size = os.fstat(f.fileno()).st_size
        kind = mimetypes.guess_type(real.name)[0]
        out = {"path": rel, "size": size, "type": kind, "text": None, "binary": False, "too_large": size > limit}
        if out["too_large"]:
            return out
        data = f.read(limit + 1)
    if b"\0" in data[:8192]:
        out["binary"] = True
        return out
    try:
        out["text"] = data.decode("utf-8")
    except UnicodeDecodeError:
        out["binary"] = True
    return out


def reveal_path(project: Project, wt: str | None, rel: str | None) -> Path:
    """The resolved path `open -R` should show; same checks as the browser."""
    root, _confine = _browse_root(project, wt)
    return _browse_path(root, rel)[1]


# ── CLI ──────────────────────────────────────────────────────────────────────

def _cmd_list(args) -> dict:
    out = {}
    for key, p in load_registry().items():
        trees = []
        root = WORKTREE_ROOT / key
        if root.is_dir():
            for wt in sorted(x for x in root.iterdir() if x.is_dir()):
                trees.append({"id": wt.name, "age_days": round((time.time() - wt.stat().st_mtime) / 86400, 1)})
        out[key] = {"path": str(p.path), "kind": p.kind, "confidential": p.confidential,
                    "no_push": p.no_push, "worktrees": trees}
    return out


def _cmd_worktree(args) -> dict:
    with project_lock(args.key):
        project = get_project(args.key)
        with ticket_lock(project.key, args.id):
            return create_worktree(project, args.id)


def _cmd_verify(args) -> dict:
    with project_lock(args.key):
        project = get_project(args.key)
        ident = ticket_from_worktree(project, Path(args.worktree))
        with ticket_lock(project.key, ident):
            return run_verify(project, Path(args.worktree), base=args.base)


def _cmd_cleanup(args) -> dict:
    with project_lock(args.key):
        project = get_project(args.key)
        with ticket_lock(project.key, args.id):
            remove_worktree(project, args.id)
    return {"removed": str(worktree_path(project, args.id))}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AgenticOS project registry and verify harness.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list").set_defaults(fn=_cmd_list)
    p = sub.add_parser("worktree"); p.add_argument("key"); p.add_argument("id"); p.set_defaults(fn=_cmd_worktree)
    p = sub.add_parser("verify"); p.add_argument("key"); p.add_argument("--worktree", required=True)
    p.add_argument("--base"); p.set_defaults(fn=_cmd_verify)
    p = sub.add_parser("cleanup"); p.add_argument("key"); p.add_argument("id"); p.set_defaults(fn=_cmd_cleanup)
    args = parser.parse_args(argv)
    try:
        result = args.fn(args)
    except ProjectError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    if args.cmd == "verify":
        return 0 if result["status"] == "pass" else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
