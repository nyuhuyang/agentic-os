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
import signal
import subprocess
import sys
import tempfile
import threading
import time
import dataclasses
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_PROTO = Path(__file__).resolve().parent.parent
REGISTRY_PATH = Path(os.environ.get("AGENTIC_OS_PROJECTS", str(_PROTO / "projects.yaml")))
WORKTREE_ROOT = Path(os.environ.get("AGENTIC_OS_WORKTREES", "~/.agentic-os/worktrees")).expanduser()

_FIELDS = {"path", "kind", "verify", "env", "confidential", "no_push", "seed", "verify_timeout_s"}
_IDENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
DEFAULT_VERIFY_TIMEOUT_S = 600
TAIL_CHARS = 4000


class ProjectError(Exception):
    """A registry, worktree or verify problem the user has to fix."""


class TicketLocked(ProjectError):
    pass


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


# An agent can write the shared git config (e.g. core.fsmonitor -> a script in its
# worktree); git would then run that script inside the runner's own commands.
_GIT_HARDENING = ("-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null")


def sandbox_profile(writable: list[Path]) -> str:
    """macOS sandbox-exec profile: no network, writes only under `writable` and temp dirs."""
    tmp = {Path("/private/tmp"), Path(os.path.realpath(tempfile.gettempdir()))}
    roots = sorted({str(Path(os.path.realpath(p))) for p in [*writable, *tmp]})
    allow = " ".join(f'(subpath "{r}")' for r in roots)
    # allow-default keeps git, shells and test runtimes working; the denials close the routes
    # by which sandboxed code asks something outside the sandbox to act for it.
    # ponytail: deny-list, not deny-default; spike (g2) probes `open URL`, osascript and
    # launchctl submit. Move to deny-default if a new escape route shows up.
    return ("(version 1)(allow default)(deny network*)(deny file-write*)"
            "(deny lsopen)(deny appleevent-send)"
            '(deny mach-lookup (global-name "com.apple.coreservices.launchservicesd")'
            ' (global-name "com.apple.coreservices.appleevents") (global-name-regex #"^com\\.apple\\.lsd\\."))'
            f'(allow file-write* {allow} (literal "/dev/null") (literal "/dev/tty") (regex #"^/dev/fd/"))')


def sandbox_prefix(writable: list[Path]) -> list[str]:
    return ["/usr/bin/sandbox-exec", "-p", sandbox_profile(writable)]


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
    verify = entry.get("verify")
    if not isinstance(verify, str) or not verify.strip():
        raise ProjectError(f"{key}: 'verify' is required")
    env = entry.get("env") or {}
    if not isinstance(env, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in env.items()):
        raise ProjectError(f"{key}: 'env' must map strings to strings")
    env = {k: os.path.expanduser(v) if k == "PATH" else v for k, v in env.items()}
    seeds = entry.get("seed") or []
    if not isinstance(seeds, list):
        raise ProjectError(f"{key}: 'seed' must be a list")
    timeout = entry.get("verify_timeout_s", DEFAULT_VERIFY_TIMEOUT_S)
    if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout <= 0:
        raise ProjectError(f"{key}: 'verify_timeout_s' must be a positive integer")
    return Project(
        key=key, path=root, verify=verify.strip(), kind=str(entry.get("kind") or ""),
        env=env, confidential=bool(entry.get("confidential", False)),
        no_push=bool(entry.get("no_push", False)),
        seed=tuple(_seed_path(root, s, key) for s in seeds), verify_timeout_s=timeout,
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


def load_registry(path: Path | None = None, errors: dict | None = None) -> dict[str, Project]:
    """Parse the registry. With `errors` given, a bad entry is recorded there and skipped
    (the dashboard keeps showing the other projects); without it, the first error raises."""
    path = Path(path or REGISTRY_PATH)
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
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
    lock_dir = WORKTREE_ROOT / key / ".meta"  # sidecars never share the ticket-dir namespace
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
    env = None
    if not _git(wt, "config", "user.email", check=False).stdout.strip():
        env = {**os.environ, "GIT_AUTHOR_NAME": "AgenticOS", "GIT_AUTHOR_EMAIL": "agentic-os@localhost",
               "GIT_COMMITTER_NAME": "AgenticOS", "GIT_COMMITTER_EMAIL": "agentic-os@localhost"}
    _git(wt, "commit", "--no-verify", "--no-gpg-sign", "-q", "-m", message, confine=confine, timeout=COMMIT_TIMEOUT_S, env=env)
    return _git(wt, "rev-parse", "HEAD").stdout.strip()


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


def uncommitted(project: Project, wt: Path) -> list[str]:
    """Tracked or non-ignored untracked changes left in the worktree (seeds are ignored)."""
    out = _git_bytes(wt, "status", "--porcelain", "-z", "--untracked-files=all", confine=confine_for(project, wt))
    return [e[3:].decode("utf-8", "surrogateescape") for e in out.split(b"\0") if len(e) > 3]


def run_verify(project: Project, worktree: Path, base: str | None = None, prefix: list[str] | None = None,
               on_start=None) -> dict:
    """Run the project's verify command in an owned worktree. Caller holds ticket_lock.

    Confidential projects run under the sandbox-exec profile (Decision 9) unless `prefix` is given.
    """
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
# ~/.claude and ~/.codex are read-only to AgenticOS: nothing here writes or copies them.

CLAUDE_PROJECTS = Path(os.environ.get("CLAUDE_CONFIG_DIR", "~/.claude")).expanduser() / "projects"
CODEX_DB = Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser() / "state_5.sqlite"
MAX_SESSIONS = 50


def _slug(path: Path | str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


def _under(cwd: str, roots: list[str]) -> bool:
    return any(cwd == r or cwd.startswith(r.rstrip("/") + "/") for r in roots)


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


def claude_sessions(project: Project) -> list[dict]:
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
            if (info["entrypoint"] or "").startswith("sdk-"):
                continue  # headless -p / SDK runs are not resumable picker sessions
            out.append({
                "agent": "claude", "id": f.stem, "cwd": info["cwd"],
                "title": info["custom"] or info["ai"] or info["first"] or "untitled",
                "updated": st.st_mtime, "branch": info["branch"], "messages": info["messages"],
                "resume": f"cd {shlex.quote(info['cwd'])} && claude --resume {shlex.quote(f.stem)}",
            })
    return out


def claude_memory_names(project: Project) -> list[str]:
    mem = CLAUDE_PROJECTS / _slug(project.path) / "memory"
    return sorted(p.name for p in mem.glob("*.md")) if mem.is_dir() else []


def codex_sessions(project: Project) -> list[dict]:
    import sqlite3
    if not CODEX_DB.exists():
        return []
    roots = _session_roots(project)
    try:
        db = sqlite3.connect(f"file:{CODEX_DB}?mode=ro", uri=True)
        try:
            rows = db.execute(
                "SELECT id, cwd, name, title, first_user_message, updated_at, tokens_used, git_branch "
                "FROM threads WHERE archived = 0 AND source IN ('cli', 'vscode')").fetchall()
        finally:
            db.close()
    except sqlite3.Error:
        return []  # format drift: degrade to no Codex rows, never crash the view
    out = []
    for tid, cwd, name, title, first, updated, tokens, branch in rows:
        if not isinstance(tid, str) or not isinstance(cwd, str) or not _under(cwd, roots):
            continue
        name, title, first, branch = (v if isinstance(v, str) else None for v in (name, title, first, branch))
        try:
            updated = float(updated or 0)
        except (TypeError, ValueError):
            updated = 0.0
        out.append({
            "agent": "codex", "id": tid, "cwd": cwd,
            "title": name or title or (first or "")[:200] or "untitled",
            "updated": updated, "branch": branch, "tokens": tokens,
            "resume": f"cd {shlex.quote(cwd)} && codex resume {shlex.quote(tid)}",
        })
    return out


def project_sessions(project: Project) -> list[dict]:
    rows = claude_sessions(project) + codex_sessions(project)
    rows.sort(key=lambda r: r["updated"], reverse=True)
    return rows[:MAX_SESSIONS]


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
    project = get_project(args.key)
    with ticket_lock(project.key, args.id):
        return create_worktree(project, args.id)


def _cmd_verify(args) -> dict:
    project = get_project(args.key)
    ident = ticket_from_worktree(project, Path(args.worktree))
    with ticket_lock(project.key, ident):
        return run_verify(project, Path(args.worktree), base=args.base)


def _cmd_cleanup(args) -> dict:
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
