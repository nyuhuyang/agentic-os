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
import sys
import tomllib
from functools import lru_cache
from pathlib import Path

DSH_MIN_VERSION = "0.2.0-rc.2"  # first release with --json and --session-id
# AGE-139: 0.2.1-rc.2 is the first installed headless profile with the working-directory
# tool/service the confidential overlay must disable; older dsh runs are refused for
# confidential projects only.
DSH_CONFIDENTIAL_MIN_VERSION = "0.2.1-rc.2"
# Decided by the 2026-10-14 spike: headless `ask` auto-denies escalation, writes stay in cwd.
DSH_PERMISSION_MODE = "workspace-write"
DSH_CONFINE_RUNNER_ENV = "AGENTICOS_DSH_CONFINE_RUNNER"
_RUNNER_DIR = Path(__file__).resolve().parent
DSH_CONFINE_RUNNER = _RUNNER_DIR / "dsh_confine.py"
DSH_CONFIDENTIAL_PATCH = _RUNNER_DIR / "scripts" / "dsh-confidential.yml"
DSH_CONFIDENTIAL_BUNDLES = ("@deepseek-ai/dsh-base", "@deepseek-ai/dsh-headless")
_DISABLED_TOOLS = frozenset({"tool-web", "tool-working-directory", "tool-fs"})
_DISABLED_EXTRA = frozenset({"otel", "session-telemetry-otel"})
_TEMP_PREFIXES = ("/tmp", "/private/tmp", "/var/folders", "/private/var/folders")
# The enforcing providers the overlay pins. Any layer that renames or replaces one of these
# would move the confinement boundary, so the composition check insists on the vendor names.
_CONFINE_PROVIDERS = {
    "sandbox": "@deepseek-ai/dsh-sandbox-local",
    "sandbox-policy": "@deepseek-ai/dsh-sandbox-policy",
    "bash-sandbox": "@deepseek-ai/dsh-bash-sandbox",
    "tool-bash": "@deepseek-ai/dsh-tool-bash",
    "fs-sandbox": "@deepseek-ai/dsh-fs-sandbox",
    "fs-observation-policy": "@deepseek-ai/dsh-fs-observation-policy",
    "subprocess": "@deepseek-ai/dsh-subprocess-local",
    "shell-env": "@deepseek-ai/dsh-shell-env",
    "working-directory": "@deepseek-ai/dsh-working-directory",
    "permission": "@deepseek-ai/dsh-permission-presets",
    "approval": "@deepseek-ai/dsh-user-approval",
}
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


def _node_launcher(dsh_bin: str) -> list[str] | None:
    """[absolute node, absolute bin.js] for a `#!/usr/bin/env node` install, else None.

    AGE-139: a project PATH override can otherwise put a worktree-local `node` first and run
    repository code before dsh (and any sandbox) starts. Resolve both paths in the runner's
    environment, not the project's.
    """
    node = shutil.which("node")
    script = Path(dsh_bin).resolve()
    if node and script.is_file() and script.suffix == ".js":
        return [os.path.realpath(node), str(script)]
    return None


def cli_prefix() -> list[str]:
    """[dsh, --profile, headless]; FileNotFoundError if missing, RuntimeError if too old.

    Non-confidential dsh keeps its existing `#!/usr/bin/env node` launch; the absolute
    Node launcher is confined to `confidential_cli_prefix()` (AGE-139).
    """
    dsh_bin = resolve_bin()
    if not dsh_bin:
        raise FileNotFoundError("dsh CLI not found (npm i -g @deepseek-ai/dsh)")
    check_version(dsh_bin)
    return [dsh_bin, "--profile", "headless"]


def confidential_cli_prefix() -> list[str]:
    """The absolute-node dsh prefix plus the confidential sandbox patch.

    Refuses an install without a resolvable absolute node/bin.js pair: a shebang lookup
    through a project PATH is exactly the pre-sandbox execution this path must exclude.
    """
    dsh_bin = resolve_bin()
    if not dsh_bin:
        raise FileNotFoundError("dsh CLI not found (npm i -g @deepseek-ai/dsh)")
    version = check_version(dsh_bin)
    if _version_key(version) < _version_key(DSH_CONFIDENTIAL_MIN_VERSION):
        raise RuntimeError(f"confidential dsh needs >= {DSH_CONFIDENTIAL_MIN_VERSION} "
                           f"(found {version}); upgrade: npm i -g @deepseek-ai/dsh")
    launcher = _node_launcher(dsh_bin)
    if launcher is None:
        raise RuntimeError("confidential dsh needs an absolute node interpreter and bin.js")
    return [*launcher, "--profile", "headless", "--patch", str(DSH_CONFIDENTIAL_PATCH)]


def _entry_blocks(text: str) -> dict[str, str]:
    """`id -> composed block` from a `dsh --dump-config` entry list."""
    out: dict[str, str] = {}
    for block in re.split(r"^(?=- id: )", text, flags=re.M):
        match = re.match(r"- id: (\S+)\n", block)
        if match:
            out[match.group(1)] = block
    return out


def _enabled_ids(text: str) -> set[str]:
    return {ident for ident, block in _entry_blocks(text).items()
            if not re.search(r"^  disabled: true$", block, re.M)}


def _has_name(block: str, package: str) -> bool:
    return re.search(rf"^  name: ['\"]?{re.escape(package)}['\"]?$", block, re.M) is not None


def _inside(path: Path, root: Path) -> bool:
    try:
        return path == root or path.is_relative_to(root)
    except ValueError:
        return False


def _under(path: Path, *roots: str) -> bool:
    text = str(path)
    return any(text == root or text.startswith(root + os.sep) for root in roots)


def _unsafe_install(path: Path, root: Path) -> bool:
    """A trusted launcher under the worktree or a sandbox-writable temp root is replaceable."""
    return _inside(path, root) or _under(path, *_TEMP_PREFIXES)


def _unsafe_raw(path: Path, root: Path) -> bool:
    """Like `_unsafe_install`, but for the unresolved spelling (a venv shim)."""
    return _inside(path, root) or _under(str(path), *_TEMP_PREFIXES)


def stock_profile_problem(dsh_home: str) -> str | None:
    """Why this profile is not the shipped headless profile, or None when it is.

    `--dump-default-config` includes the profile's selected bundles, so a user-added vendor
    bundle would appear in both the baseline and the patched dump and pass the id comparison.
    Require the shipped selections and an empty profile dependency set first.
    """
    profile = Path(dsh_home).expanduser() / "profiles" / "headless"
    try:
        manifest = json.loads((profile / "package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return f"cannot read {profile / 'package.json'}: {exc}"
    if not isinstance(manifest, dict):
        return f"{profile / 'package.json'} is not an object"
    dsh = manifest.get("dsh")
    bundles = dsh.get("profile", {}).get("bundles") if isinstance(dsh, dict) else None
    if bundles != list(DSH_CONFIDENTIAL_BUNDLES):
        return (f"the headless profile must select exactly {list(DSH_CONFIDENTIAL_BUNDLES)}; "
                f"found {bundles!r}")
    if manifest.get("dependencies"):
        return "the headless profile must not declare dependencies (a local package could shadow a vendor bundle)"
    if (profile / "node_modules").exists():
        return "the headless profile must not have a profile-local node_modules"
    return None


def composition_problem(stock_text: str, patched_text: str, patch_path: Path) -> str | None:
    """Why the composed confidential profile is unsafe, or None when every check passes.

    Pure over the two dump texts so the security rules can be tested without booting dsh.
    """
    patch = str(patch_path)
    for header in re.findall(r"^# == (.+)$", patched_text, re.M):
        origin, _, patched = header.partition(", patched by ")
        sources = [origin.strip()]
        if patched:
            sources += [source.strip() for source in patched.split(",")]
        for source in sources:
            if source.startswith("@deepseek-ai/") or source == patch:
                continue
            return f"dsh profile has a non-vendor layer ({source})"
    if f"patched by {patch}" not in patched_text:
        return "dsh did not apply the confidential sandbox patch"
    blocks = _entry_blocks(patched_text)
    actual = _enabled_ids(patched_text)
    expected = _enabled_ids(stock_text) - _DISABLED_TOOLS - _DISABLED_EXTRA
    extra = sorted(actual - expected)
    if extra:
        return f"dsh enables unexpected plugins: {', '.join(extra)}"
    missing = sorted(expected - actual)
    if missing:
        return f"dsh is missing expected plugins: {', '.join(missing)}"
    sandbox = blocks.get("sandbox", "")
    if "runnerCommand:" not in sandbox or "dsh-confine:" not in sandbox:
        return "the sandbox provider is not using the confidential runner"
    for ident in _DISABLED_TOOLS | _DISABLED_EXTRA:
        if not re.search(r"^  disabled: true$", blocks.get(ident, ""), re.M):
            return f"{ident} is not disabled"
    if "mode: workspace-write" not in blocks.get("sandbox-policy", ""):
        return "sandbox-policy is not workspace-write"
    permission = blocks.get("permission", "")
    if "defaultPreset: workspace-write" not in permission:
        return "the default permission preset is not workspace-write"
    if "danger-full-access" in permission:
        return "the permission table exposes danger-full-access"
    if "read-only:" not in permission or "workspace-write:" not in permission:
        return "the permission table is incomplete"
    if "policy: ask" not in blocks.get("approval", ""):
        return "the approval policy is not ask"
    for ident, package in _CONFINE_PROVIDERS.items():
        block = blocks.get(ident, "")
        if not block:
            return f"missing {ident}"
        if not _has_name(block, package):
            return f"{ident} is not the vendor {package}"
    return None


def _dump(launcher: list[str], args: list[str], env: dict[str, str], cwd: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run([*launcher, *args], env=env, cwd=cwd, stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"confidential dsh: cannot compose its profile: {exc}") from exc


def verify_confidential_launch(env: dict[str, str], worktree: str) -> None:
    """Fail closed before a confidential dsh launch unless the composed sandbox is the pinned one."""
    prefix = confidential_cli_prefix()
    dsh_home = Path(env.get("DSH_HOME") or (Path.home() / ".dsh")).expanduser()
    root = Path(os.path.realpath(worktree))
    for path in (prefix[0], prefix[1], str(DSH_CONFINE_RUNNER), str(DSH_CONFIDENTIAL_PATCH),
                 str(dsh_home), str(dsh_home / "profiles" / "headless")):
        if _unsafe_install(Path(os.path.realpath(path)), root):
            raise RuntimeError(
                f"confidential dsh launcher {path} is inside the worktree or a writable temp root")
    raw_runner = env.get(DSH_CONFINE_RUNNER_ENV)
    try:
        runner_argv = json.loads(raw_runner or "")
    except ValueError:
        raise RuntimeError(f"{DSH_CONFINE_RUNNER_ENV} must be a JSON argv array") from None
    if (not isinstance(runner_argv, list) or len(runner_argv) != 3
            or not all(isinstance(item, str) for item in runner_argv)
            or runner_argv[1] != "-I"):
        raise RuntimeError(f"{DSH_CONFINE_RUNNER_ENV} must be a JSON [python, -I, script] array")
    if not os.path.isabs(runner_argv[0]):
        raise RuntimeError("the confidential runner interpreter must be absolute")
    if Path(runner_argv[2]).resolve() != DSH_CONFINE_RUNNER.resolve():
        raise RuntimeError("the confidential runner script is not the runner's own wrapper")
    for path in (Path(runner_argv[0]), Path(sys.prefix)):
        if _unsafe_raw(path, root):
            raise RuntimeError("the confidential interpreter prefix is inside the worktree or a writable temp root")
    for path in (runner_argv[0], runner_argv[2]):
        if _unsafe_install(Path(os.path.realpath(path)), root):
            raise RuntimeError("the confidential runner is inside the worktree or a writable temp root")
    if not Path(runner_argv[2]).is_file():
        raise RuntimeError("the confidential runner script is missing")
    problem = stock_profile_problem(str(dsh_home))
    if problem:
        raise RuntimeError(f"confidential dsh: {problem}")
    # Probe the exact final launch environment, not a separately reconstructed one: an
    # ambient DSH_* switch must be absent from both or the check proves the wrong profile.
    check_env = dict(env)
    check_env.update({"DSH_HOME": str(dsh_home), "DSH_PERMISSION_MODE": DSH_PERMISSION_MODE,
                      DSH_CONFINE_RUNNER_ENV: raw_runner})
    launcher = [prefix[0], prefix[1]]
    stock = _dump(launcher, ["--profile", "headless", "--dump-default-config"], check_env, worktree)
    if stock.returncode:
        raise RuntimeError(f"confidential dsh: --dump-default-config failed (exit {stock.returncode})")
    patched = _dump(launcher, ["--profile", "headless", "--patch", str(DSH_CONFIDENTIAL_PATCH),
                               "--dump-config"], check_env, worktree)
    if patched.returncode:
        raise RuntimeError(f"confidential dsh: --dump-config failed (exit {patched.returncode})")
    if "patch: entry" in (stock.stderr + patched.stderr):
        raise RuntimeError("confidential dsh: the sandbox patch was not applied (unknown plugin id)")
    problem = composition_problem(stock.stdout, patched.stdout, DSH_CONFIDENTIAL_PATCH)
    if problem:
        raise RuntimeError(f"confidential dsh: {problem}")


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
    """Add the API key and permission mode to a child env (in place, returned)."""
    key = resolve_api_key()
    if key:
        env["DEEPSEEK_API_KEY"] = key
    env["DSH_PERMISSION_MODE"] = DSH_PERMISSION_MODE
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
