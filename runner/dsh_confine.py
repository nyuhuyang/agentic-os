#!/usr/bin/env python3
"""dsh sandbox runner for confidential and workspace projects (AGE-139, AGE-146).

dsh's own macOS sandbox confines file writes only; its shell network stays open. The runner
points dsh's `sandbox.runnerCommand` at this script. dsh appends its bwrap-style profile
arguments, then `--`, then the real command. This script ignores the bwrap dialect, builds the
runner's Seatbelt profile from the worktree root dsh passed as the first launcher argument, and
execs the command under it.

Two modes: `confidential` keeps the AGE-139 profile (network/app-service denials, `/tmp` as the
shell temp) and is the default when the token is absent; `workspace` mirrors dsh's native
write-only profile and adds the repository's git common dir so a non-confidential agent can
`git add`/`git commit` in its linked worktree (AGE-146).

The root travels in argv, not the environment: dsh strips `DSH_*` from children and its
PTC/workflow runtime drops almost all ambient variables, so argv is the one channel every
consumer preserves.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_TRUSTED_TEMP_PREFIXES = ("/tmp", "/private/tmp", "/var/folders", "/private/var/folders")
_RUNNER = Path(__file__).resolve().parent
if str(_RUNNER) not in sys.path:
    sys.path.insert(0, str(_RUNNER))

try:
    import projects  # noqa: E402
    _IMPORT_ERROR: Exception | None = None
except Exception as _exc:  # pragma: no cover - a broken install must fail closed
    projects = None  # type: ignore[assignment]
    _IMPORT_ERROR = _exc


class ConfineError(Exception):
    """A confinement request that cannot be honored; the command must not run."""


_SHELL_TEMP = "/tmp"
_MODES = ("confidential", "workspace")


def _temp_root() -> str:
    """The shell's temp root. dsh's spill writers use the parent TMPDIR (a runner-owned
    directory); the sandboxed shell must not be able to write that, so it gets `/tmp`."""
    return _SHELL_TEMP


def _trusted_temp(path: str) -> bool:
    real = os.path.realpath(path)
    return any(real == prefix or real.startswith(prefix + os.sep) for prefix in _TRUSTED_TEMP_PREFIXES)


def _workspace_write(profile_args: list[str], root: str) -> bool:
    """True when dsh's bwrap dialect grants this workspace write access."""
    for index, arg in enumerate(profile_args):
        if arg == "--bind" and index + 2 < len(profile_args) \
                and profile_args[index + 1] == root and profile_args[index + 2] == root:
            return True
    return False


def _mode_of(argv: list[str]) -> str:
    """The optional mode token after the git dir; absent means confidential (AGE-139 callers)."""
    return argv[2] if len(argv) > 2 and argv[2] in _MODES else "confidential"


def build_argv(argv: list[str], env: dict[str, str] | None = None) -> list[str]:
    """(sandbox-exec profile, command) for one dsh command. Raises ConfineError on refusal.

    `argv` is dsh's launcher tail: `root, git-common-dir-or-"-", [confidential|workspace],
    bwrap-profile... , "--", command...`. The git common dir is writable when dsh grants
    workspace-write, so the agent can `git add`/`git commit` in its worktree; the runner still
    commits leftovers. `env` is accepted for callers/tests; paths are deliberately not read
    from it.
    """
    if sys.platform != "darwin":
        raise ConfineError("the dsh sandbox is macOS-only")
    if not argv:
        raise ConfineError("missing worktree root")
    root = argv[0]
    if not isinstance(root, str) or not os.path.isabs(root):
        raise ConfineError("the worktree root must be an absolute path")
    if not os.path.isdir(root):
        raise ConfineError("the worktree root does not exist")
    git_dir = None
    start = 1
    if len(argv) > 1:
        candidate = argv[1]
        if candidate == "-":
            start = 2
        elif candidate != "--" and not candidate.startswith("-"):
            if os.path.isabs(candidate) and os.path.isdir(candidate):
                git_dir = candidate
                start = 2
            else:
                raise ConfineError("the git common dir must be an absolute existing path or -")
    mode = "confidential"
    if len(argv) > start and argv[start] in _MODES:
        mode = argv[start]
        start += 1
    try:
        sep = argv.index("--", start)
    except ValueError:
        raise ConfineError("missing command separator") from None
    command = argv[sep + 1:]
    if not command:
        raise ConfineError("missing command")
    if command[0].startswith("-"):
        raise ConfineError("refusing an option-like command")
    if not _trusted_temp(_temp_root()):
        raise ConfineError("untrusted temporary root")
    if projects is None:
        raise ConfineError(f"cannot import the runner modules: {_IMPORT_ERROR}")
    profile_args = argv[start:sep]
    writable = [Path(root)] if _workspace_write(profile_args, root) else []
    if writable and git_dir:
        writable.append(Path(git_dir))
    if mode == "workspace":
        # dsh's native workspace-write grants the root, /tmp and os.tmpdir(); read-only grants
        # none of them. Keep the ambient TMPDIR, unlike the confidential spill separation.
        temp = bool(writable)
        try:
            prefix = projects.sandbox_prefix(writable, temp=temp, temp_root=None, write_only=True)
        except Exception as exc:
            raise ConfineError(f"cannot build the sandbox profile: {exc}") from exc
    else:
        temp = "--tmpfs" in profile_args
        try:
            prefix = projects.sandbox_prefix(writable, temp=temp,
                                             temp_root=_temp_root() if temp else None)
        except Exception as exc:
            raise ConfineError(f"cannot build the sandbox profile: {exc}") from exc
    return [*prefix, *command]


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        exec_argv = build_argv(argv)
    except ConfineError as exc:
        print(f"dsh-confine: {exc}", file=sys.stderr)
        return 126
    except Exception as exc:  # fail closed even on an unexpected wrapper error
        print(f"dsh-confine: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 126
    mode = _mode_of(argv)
    child_env = dict(os.environ)
    # A process already under this Seatbelt must not nest sandbox-exec (macOS refuses it); the
    # marker lets projects.py skip the inner profile while the parent keeps the same boundary.
    child_env[projects.DSH_SANDBOX_ENV] = mode
    if mode == "confidential":  # the shell gets its own temp; dsh keeps the spill dir
        child_env["TMPDIR"] = child_env["TMP"] = child_env["TEMP"] = _temp_root()
    try:
        os.execve(exec_argv[0], exec_argv, child_env)
    except OSError as exc:
        print(f"dsh-confine: cannot start the sandbox: {exc}", file=sys.stderr)
        return 126


if __name__ == "__main__":
    sys.exit(main())
