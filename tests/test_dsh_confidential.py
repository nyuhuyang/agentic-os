"""AGE-139: confidential dsh argv, env, wrapper and profile-composition guards."""

import json
import os
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runner"))

import dsh_cli  # noqa: E402
import dsh_confine  # noqa: E402
import project_runs as pr  # noqa: E402

PATCH = dsh_cli.DSH_CONFIDENTIAL_PATCH


@pytest.fixture(autouse=True)
def _isolated_outputs(monkeypatch, tmp_path):
    import app
    out = Path(__file__).resolve().parents[1] / f"outputs-test-{tmp_path.name}"
    monkeypatch.setattr(app, "OUTPUTS_DIR", out)
    git = tmp_path / "git-common"
    git.mkdir()
    monkeypatch.setattr(app.project_runs, "common_dir", lambda project: str(git))
    yield
    shutil.rmtree(out, ignore_errors=True)


def _block(ident: str, name: str, extra: str = "") -> str:
    return f"- id: {ident}\n  name: '{name}'\n{extra}"


def _fixture_dump(*, patched: bool, extra: str = "", permission_extra: str = "",
                  tool_web_disabled: bool = False) -> str:
    header = "# == @deepseek-ai/dsh-base" + (f", patched by {PATCH}\n" if patched else "\n")
    disabled = "  disabled: true\n" if (patched or tool_web_disabled) else ""
    blocks = [
        _block("sandbox", "@deepseek-ai/dsh-sandbox-local",
               "  config:\n    runnerCommand: !!js [node, runner]\n"
               "    runnerFailureSignatures:\n      - 'dsh-confine:'\n" if patched else ""),
        _block("sandbox-policy", "@deepseek-ai/dsh-sandbox-policy",
               "  config:\n    mode: workspace-write\n"),
        _block("approval", "@deepseek-ai/dsh-user-approval", "  config:\n    policy: ask\n"),
        _block("permission", "@deepseek-ai/dsh-permission-presets",
               "  config:\n    defaultPreset: workspace-write\n    presets:\n"
               "      read-only:\n        approval: ask\n"
               "      workspace-write:\n        approval: ask\n" + permission_extra),
        _block("bash-sandbox", "@deepseek-ai/dsh-bash-sandbox"),
        _block("tool-bash", "@deepseek-ai/dsh-tool-bash"),
        _block("fs-sandbox", "@deepseek-ai/dsh-fs-sandbox"),
        _block("fs-observation-policy", "@deepseek-ai/dsh-fs-observation-policy"),
        _block("subprocess", "@deepseek-ai/dsh-subprocess-local"),
        _block("shell-env", "@deepseek-ai/dsh-shell-env"),
        _block("working-directory", "@deepseek-ai/dsh-working-directory"),
        _block("otel", "@deepseek-ai/dsh-otel", disabled),
        _block("session-telemetry-otel", "@deepseek-ai/dsh-session-telemetry-otel", disabled),
        _block("tool-web", "@deepseek-ai/dsh-tool-web", disabled),
        _block("tool-working-directory", "@deepseek-ai/dsh-tool-working-directory", disabled),
        _block("tool-fs", "@deepseek-ai/dsh-tool-fs", disabled),
        _block("timer", "@deepseek-ai/cordis-plugin-timer"),
    ]
    return header + "".join(blocks) + extra


def test_composition_accepts_the_pinned_profile():
    stock = _fixture_dump(patched=False)
    patched = _fixture_dump(patched=True)
    assert dsh_cli.composition_problem(stock, patched, PATCH) is None


def test_composition_rejects_a_non_vendor_layer():
    patched = _fixture_dump(patched=True).replace(
        f"# == @deepseek-ai/dsh-base, patched by {PATCH}",
        f"# == @deepseek-ai/dsh-base, patched by {PATCH}\n"
        "# == /home/user/.dsh/profiles/headless/cordis.patch.yml")
    assert "non-vendor layer" in dsh_cli.composition_problem(_fixture_dump(patched=False), patched, PATCH)


def test_composition_rejects_an_extra_enabled_id():
    patched = _fixture_dump(patched=True, extra=_block("fs-local", "@deepseek-ai/dsh-fs-local"))
    problem = dsh_cli.composition_problem(_fixture_dump(patched=False), patched, PATCH)
    assert "unexpected plugins" in problem and "fs-local" in problem


def test_composition_rejects_a_missing_id():
    patched = _fixture_dump(patched=True).replace(_block("fs-sandbox", "@deepseek-ai/dsh-fs-sandbox"), "")
    problem = dsh_cli.composition_problem(_fixture_dump(patched=False), patched, PATCH)
    assert "missing expected plugins" in problem and "fs-sandbox" in problem


def test_composition_rejects_danger_full_access():
    patched = _fixture_dump(patched=True, permission_extra="      danger-full-access:\n        approval: never\n")
    assert "danger-full-access" in dsh_cli.composition_problem(_fixture_dump(patched=False), patched, PATCH)


def test_composition_rejects_a_tool_that_is_not_disabled():
    patched = _fixture_dump(patched=True).replace(
        _block("tool-web", "@deepseek-ai/dsh-tool-web", "  disabled: true\n"),
        _block("tool-web", "@deepseek-ai/dsh-tool-web"))
    problem = dsh_cli.composition_problem(_fixture_dump(patched=False), patched, PATCH)
    assert "tool-web is not disabled" in problem or "unexpected plugins" in problem


def test_stock_profile_requires_the_shipped_bundles(tmp_path):
    profile = tmp_path / "profiles" / "headless"
    profile.mkdir(parents=True)
    manifest = {"dsh": {"profile": {"bundles": ["@deepseek-ai/dsh-base", "@deepseek-ai/dsh-headless"]}}}
    (profile / "package.json").write_text(json.dumps(manifest))
    assert dsh_cli.stock_profile_problem(str(tmp_path)) is None
    manifest["dsh"]["profile"]["bundles"].append("@deepseek-ai/dsh-experimental-terminal-bundle")
    (profile / "package.json").write_text(json.dumps(manifest))
    assert "must select exactly" in dsh_cli.stock_profile_problem(str(tmp_path))


# ── wrapper ─────────────────────────────────────────────────────────────────

def _worktree(tmp_path):
    root = tmp_path / "worktree"
    root.mkdir()
    return str(root)


def test_wrapper_builds_the_seatbelt_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(dsh_confine, "_temp_root", lambda: "/private/tmp")
    root = _worktree(tmp_path)
    git = tmp_path / "git-common"
    argv = dsh_confine.build_argv(
        [root, str(git), "--ro-bind", "/", "/", "--tmpfs", "/tmp", "--bind", root, root, "--",
         "bash", "-c", "echo hi"])
    assert argv[0] == "/usr/bin/sandbox-exec" and argv[1] == "-p"
    profile = argv[2]
    assert "(deny network*)" in profile
    assert 'global-name "com.apple.dnssd.service"' in profile
    assert f'(subpath "{os.path.realpath(root)}")' in profile
    assert '(subpath "/private/tmp")' in profile
    assert f'(subpath "{os.path.realpath(git)}")' in profile
    assert argv[-3:] == ["bash", "-c", "echo hi"]


def test_wrapper_turns_a_profile_error_into_a_confine_error(tmp_path, monkeypatch):
    monkeypatch.setattr(dsh_confine, "_temp_root", lambda: "/private/tmp")
    monkeypatch.setattr(dsh_confine.projects, "sandbox_prefix",
                        lambda roots, temp=None, temp_root=None, protected=None: (_ for _ in ()).throw(RuntimeError("bad path")))
    with pytest.raises(dsh_confine.ConfineError, match="sandbox profile"):
        dsh_confine.build_argv([_worktree(tmp_path), "--", "true"])


def test_wrapper_read_only_does_not_grant_the_worktree(tmp_path, monkeypatch):
    monkeypatch.setattr(dsh_confine, "_temp_root", lambda: "/private/tmp")
    root = _worktree(tmp_path)
    argv = dsh_confine.build_argv([root, "--ro-bind", "/", "/", "--dev", "/dev", "--", "cat", "x"])
    assert f'(subpath "{os.path.realpath(root)}")' not in argv[2]
    assert '(literal "/dev/null")' in argv[2]


@pytest.mark.parametrize("argv", [
    [],
    ["relative/root", "--", "true"],
    ["/definitely/missing/worktree", "--", "true"],
])
def test_wrapper_rejects_a_bad_root(argv):
    with pytest.raises(dsh_confine.ConfineError):
        dsh_confine.build_argv(argv)


def test_wrapper_rejects_a_missing_separator_and_command(tmp_path):
    root = _worktree(tmp_path)
    with pytest.raises(dsh_confine.ConfineError, match="separator"):
        dsh_confine.build_argv([root, "--ro-bind", "/", "/"])
    with pytest.raises(dsh_confine.ConfineError, match="missing command"):
        dsh_confine.build_argv([root, "--"])
    with pytest.raises(dsh_confine.ConfineError, match="option-like"):
        dsh_confine.build_argv([root, "--", "-f", "x"])


def test_wrapper_rejects_an_untrusted_temp_root(tmp_path, monkeypatch):
    monkeypatch.setattr(dsh_confine, "_temp_root", lambda: "/home/someone")
    with pytest.raises(dsh_confine.ConfineError, match="temporary"):
        dsh_confine.build_argv([_worktree(tmp_path), "--", "true"])


def test_wrapper_main_fails_closed_when_sandbox_exec_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(dsh_confine, "_temp_root", lambda: "/tmp")
    monkeypatch.setattr(dsh_confine.projects, "sandbox_prefix",
                        lambda roots, temp=None, temp_root=None, protected=None: ["/definitely/missing/sandbox-exec"])
    assert dsh_confine.main([_worktree(tmp_path), "--", "true"]) == 126


def test_wrapper_gives_the_shell_its_own_temp_root(tmp_path, monkeypatch):
    captured = {}

    def fake_execve(path, argv, env):
        captured.update(path=path, argv=argv, env=env)
        raise SystemExit(0)

    monkeypatch.setattr(dsh_confine, "_temp_root", lambda: "/tmp")
    monkeypatch.setattr(dsh_confine.projects, "sandbox_prefix",
                        lambda roots, temp=None, temp_root=None, protected=None: ["/usr/bin/sandbox-exec", "-p", "x"])
    monkeypatch.setattr(dsh_confine.os, "execve", fake_execve)
    root = _worktree(tmp_path)
    with pytest.raises(SystemExit):
        dsh_confine.main([root, "-", "--bind", root, root, "--", "true"])
    assert captured["env"]["TMPDIR"] == captured["env"]["TMP"] == captured["env"]["TEMP"] == "/tmp"
    assert captured["argv"][-1] == "true"


# ── env / argv ──────────────────────────────────────────────────────────────

def test_confidential_dsh_refuses_when_records_are_unsafe(monkeypatch, tmp_path):
    import app
    monkeypatch.setattr(app, "_registry_exec_env", lambda agent, reg: {"PATH": "/usr/bin"})
    monkeypatch.setattr(app, "_load_registry", lambda agent: {})
    monkeypatch.setattr(app, "_records_unsafe", lambda: "records are outside the checkout")
    project = SimpleNamespace(env={}, confidential=True)
    with pytest.raises(pr.ProjectRunError, match="records are outside"):
        app._project_exec_env("dsh", project, str(tmp_path), "run-unsafe")


def test_confidential_dsh_pins_temp_over_a_repository_dotenv(monkeypatch, tmp_path):
    import app
    (tmp_path / ".env").write_text("TMPDIR=/Users/someone\nTMP=/Users/someone\n")
    monkeypatch.setattr(app, "_registry_exec_env", lambda agent, reg: {"PATH": "/usr/bin"})
    monkeypatch.setattr(app, "_load_registry", lambda agent: {})
    monkeypatch.setattr(app, "_records_unsafe", lambda: None)
    monkeypatch.setattr(app.dsh_cli, "verify_confidential_launch", lambda env, wt: None)
    env = app._project_exec_env("dsh", SimpleNamespace(env={}, confidential=True),
                                str(tmp_path), "run-dotenv")
    assert env["TMPDIR"] != "/Users/someone" and env["TMPDIR"].endswith("run-dotenv")


def test_confidential_dsh_env_pins_temp_and_runner(monkeypatch, tmp_path):
    import app
    monkeypatch.setattr(app, "_registry_exec_env", lambda agent, reg: {
        "PATH": "/usr/bin", "TMPDIR": "/Users/someone", "TMP": "/Users/someone", "TEMP": "/Users/someone"})
    monkeypatch.setattr(app, "_load_registry", lambda agent: {})
    seen = {}
    monkeypatch.setattr(app.dsh_cli, "verify_confidential_launch",
                        lambda env, wt: seen.update(env=env, wt=wt))
    monkeypatch.setattr(app, "_records_unsafe", lambda: None)
    project = SimpleNamespace(env={"TMPDIR": "/Users/someone", "DSH_HOME": ""}, confidential=True)
    env = app._project_exec_env("dsh", project, str(tmp_path), "run-1")
    assert env["AGENTICOS_DSH_CONFINE_GIT"] == str(tmp_path / "git-common")
    spill = str(Path(os.path.realpath(app.OUTPUTS_DIR / "dsh-spill")) / "run-1")
    assert env["TMPDIR"] == env["TMP"] == env["TEMP"] == spill
    assert not spill.startswith(os.path.realpath(tmp_path))
    assert env["DSH_PERMISSION_MODE"] == "workspace-write"
    assert env["DSH_TELEMETRY_DISABLED"] == "1"
    assert seen["wt"] == os.path.realpath(tmp_path)
    runner = json.loads(env[dsh_cli.DSH_CONFINE_RUNNER_ENV])
    assert runner[0] == sys.executable and runner[1] == "-I" and runner[2].endswith("dsh_confine.py")
    assert env["DSH_HOME"] == str(Path.home() / ".dsh")
    assert env["DSH_AGENTS_HOME"] == str(Path.home() / ".agents")


def test_confidential_dsh_refuses_dsh_home_inside_the_worktree(monkeypatch, tmp_path):
    import app
    monkeypatch.setattr(app, "_registry_exec_env", lambda agent, reg: {"PATH": "/usr/bin"})
    monkeypatch.setattr(app, "_load_registry", lambda agent: {})
    project = SimpleNamespace(env={"DSH_HOME": str(tmp_path / "home")}, confidential=True)
    with pytest.raises(pr.ProjectRunError, match="DSH_HOME"):
        app._project_exec_env("dsh", project, str(tmp_path))


def test_session_ticket_reads_the_worktree_root(monkeypatch, tmp_path):
    import app
    monkeypatch.setattr(app._projects, "WORKTREE_ROOT", tmp_path)
    cwd = tmp_path / "demo" / "T-1"
    cwd.mkdir(parents=True)
    assert app._session_ticket(SimpleNamespace(key="demo"), str(cwd)) == "T-1"


def test_non_confidential_dsh_prefix_is_unchanged(monkeypatch):
    monkeypatch.setattr(dsh_cli, "resolve_bin", lambda: "/bin/dsh")
    monkeypatch.setattr(dsh_cli, "check_version", lambda dsh_bin: "0.2.1-rc.2")
    assert dsh_cli.cli_prefix() == ["/bin/dsh", "--profile", "headless"]


def test_confidential_dsh_refuses_a_tilde_user_home(monkeypatch, tmp_path):
    import app
    monkeypatch.setattr(app, "_registry_exec_env", lambda agent, reg: {"PATH": "/usr/bin"})
    monkeypatch.setattr(app, "_load_registry", lambda agent: {})
    project = SimpleNamespace(env={"DSH_HOME": "~bob/dsh"}, confidential=True)
    with pytest.raises(pr.ProjectRunError, match="absolute path"):
        app._project_exec_env("dsh", project, str(tmp_path), "run-tilde")


def test_confidential_dsh_refuses_a_temp_dsh_home(monkeypatch, tmp_path):
    import app
    monkeypatch.setattr(app, "_registry_exec_env", lambda agent, reg: {"PATH": "/usr/bin"})
    monkeypatch.setattr(app, "_load_registry", lambda agent: {})
    monkeypatch.setattr(app, "_records_unsafe", lambda: None)
    worktree = tmp_path / "wt"
    worktree.mkdir()
    project = SimpleNamespace(env={"DSH_HOME": str(tmp_path / "dsh")}, confidential=True)
    with pytest.raises(pr.ProjectRunError, match="temp"):
        app._project_exec_env("dsh", project, str(worktree), "run-temp")


def test_confidential_dsh_refuses_a_relative_home(monkeypatch, tmp_path):
    import app
    monkeypatch.setattr(app, "_registry_exec_env", lambda agent, reg: {"PATH": "/usr/bin"})
    monkeypatch.setattr(app, "_load_registry", lambda agent: {})
    project = SimpleNamespace(env={"DSH_HOME": "relative/dsh"}, confidential=True)
    with pytest.raises(pr.ProjectRunError, match="DSH_HOME"):
        app._project_exec_env("dsh", project, str(tmp_path))


def test_confidential_dsh_refuses_home_inside_the_worktree(monkeypatch, tmp_path):
    import app
    monkeypatch.setattr(app, "_registry_exec_env", lambda agent, reg: {"PATH": "/usr/bin"})
    monkeypatch.setattr(app, "_load_registry", lambda agent: {})
    project = SimpleNamespace(env={"HOME": str(tmp_path)}, confidential=True)
    with pytest.raises(pr.ProjectRunError, match="HOME"):
        app._project_exec_env("dsh", project, str(tmp_path))


def test_confidential_dsh_strips_bootstrap_env(monkeypatch, tmp_path):
    import app
    monkeypatch.setattr(app, "_registry_exec_env", lambda agent, reg: {
        "PATH": "/usr/bin", "DSH_SNAPSHOT": "replay", "DSH_TOOLS_MODE": "native"})
    monkeypatch.setattr(app, "_load_registry", lambda agent: {})
    monkeypatch.setattr(app.dsh_cli, "verify_confidential_launch", lambda env, wt: None)
    monkeypatch.setattr(app, "_records_unsafe", lambda: None)
    project = SimpleNamespace(env={"NODE_OPTIONS": "--require ./preload.cjs",
                                   "PYTHONPATH": str(tmp_path), "DYLD_LIBRARY_PATH": str(tmp_path),
                                   "DSH_TOOLS_MODE": "native"},
                              confidential=True)
    env = app._project_exec_env("dsh", project, str(tmp_path / "wt"))
    assert "NODE_OPTIONS" not in env and "PYTHONPATH" not in env
    assert "DYLD_LIBRARY_PATH" not in env and "DSH_TOOLS_MODE" not in env
    assert "DSH_SNAPSHOT" not in env


def test_spill_cleanup_never_trusts_a_child_env(monkeypatch, tmp_path):
    import app
    victim = tmp_path / "victim"
    victim.mkdir()
    app._cleanup_dsh_spill({"AGENTICOS_DSH_SPILL_DIR": str(victim)})
    assert victim.exists()
    monkeypatch.setattr(app, "_registry_exec_env", lambda agent, reg: {"PATH": "/usr/bin"})
    monkeypatch.setattr(app, "_load_registry", lambda agent: {})
    env = app._project_exec_env("claude", SimpleNamespace(env={"AGENTICOS_DSH_SPILL_DIR": str(victim)},
                                                          confidential=False), str(tmp_path))
    assert "AGENTICOS_DSH_SPILL_DIR" not in env


def test_confidential_dsh_refuses_a_missing_confidential_prefix(monkeypatch):
    monkeypatch.setattr(pr, "common_dir", lambda project: "/tmp/common")
    project = SimpleNamespace(key="demo", confidential=True)
    with pytest.raises(pr.ProjectRunError, match="absolute-node prefix"):
        pr.agent_cli("dsh", project, "claude", lambda: ["dsh"])


def test_confidential_resume_is_refused(monkeypatch):
    import app
    with pytest.raises(pr.ProjectRunError, match="does not resume"):
        app._project_cmd("dsh", SimpleNamespace(confidential=True), "go on", "session-1")


def test_agent_cli_uses_the_confidential_prefix(monkeypatch):
    monkeypatch.setattr(pr, "common_dir", lambda project: "/tmp/common")
    project = SimpleNamespace(key="demo", confidential=True)
    called = []

    def prefix():
        called.append(True)
        return ["node", "/dsh/bin.js", "--profile", "headless", "--patch", str(PATCH)]

    assert pr.agent_cli("dsh", project, "claude", lambda: ["dsh"], prefix) == prefix()
    assert called


def test_confidential_dsh_prompt_asks_for_a_commit():
    project = SimpleNamespace(key="demo", auto_merge=False, no_push=True, verify="true", confidential=True)
    confidential = pr.project_prompt("task", project, {"branch": "agent/T-1"}, "dsh")
    assert "Commit your work on this branch" in confidential
    assert "Leave your changes uncommitted" not in confidential
    plain = pr.project_prompt("task", SimpleNamespace(**{**project.__dict__, "confidential": False}),
                              {"branch": "agent/T-1"}, "dsh")
    assert "Commit your work on this branch" in plain


# ── installed dsh ───────────────────────────────────────────────────────────

def _installed_profile():
    profile = Path.home() / ".dsh" / "profiles" / "headless"
    if dsh_cli.resolve_bin() is None or not profile.is_dir():
        pytest.skip("dsh or its headless profile is not installed")
    return profile


def test_confidential_prefix_uses_absolute_node():
    _installed_profile()
    prefix = dsh_cli.confidential_cli_prefix()
    assert os.path.isabs(prefix[0]) and os.path.isabs(prefix[1]) and prefix[1].endswith("bin.js")
    assert prefix[2:4] == ["--profile", "headless"] and prefix[4] == "--patch"


def test_verify_rejects_an_install_under_a_sandbox_temp_root(monkeypatch, tmp_path):
    monkeypatch.setattr(dsh_cli, "confidential_cli_prefix",
                        lambda: ["/opt/homebrew/bin/node", "/opt/homebrew/lib/dsh/bin.js",
                                 "--profile", "headless", "--patch", str(PATCH)])
    monkeypatch.setattr(dsh_cli, "_unsafe_install", lambda path, root: str(path).startswith("/private/tmp/"))
    env = {dsh_cli.DSH_CONFINE_RUNNER_ENV: json.dumps([sys.executable, "-I", "/private/tmp/agenticos/dsh_confine.py"]),
           "DSH_HOME": str(Path.home() / ".dsh")}
    with pytest.raises(RuntimeError, match="confidential runner"):
        dsh_cli.verify_confidential_launch(env, str(tmp_path / "wt"))


def test_verify_rejects_a_relative_interpreter(monkeypatch, tmp_path):
    monkeypatch.setattr(dsh_cli, "confidential_cli_prefix",
                        lambda: ["/opt/homebrew/bin/node", "/opt/homebrew/lib/dsh/bin.js",
                                 "--profile", "headless", "--patch", str(PATCH)])
    env = {dsh_cli.DSH_CONFINE_RUNNER_ENV: json.dumps(["python", "-I", str(dsh_cli.DSH_CONFINE_RUNNER)]),
           "DSH_HOME": str(Path.home() / ".dsh")}
    with pytest.raises(RuntimeError, match="absolute"):
        dsh_cli.verify_confidential_launch(env, str(tmp_path / "wt"))


def test_verify_rejects_a_foreign_runner_script(monkeypatch, tmp_path):
    monkeypatch.setattr(dsh_cli, "confidential_cli_prefix",
                        lambda: ["/opt/homebrew/bin/node", "/opt/homebrew/lib/dsh/bin.js",
                                 "--profile", "headless", "--patch", str(PATCH)])
    env = {dsh_cli.DSH_CONFINE_RUNNER_ENV: json.dumps([sys.executable, "-I", "/tmp/other.py"]),
           "DSH_HOME": str(Path.home() / ".dsh")}
    with pytest.raises(RuntimeError, match="own wrapper"):
        dsh_cli.verify_confidential_launch(env, str(tmp_path / "wt"))


def test_installed_dsh_composes_the_confidential_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(dsh_cli, "_TEMP_PREFIXES", ())  # the test DSH_HOME lives under pytest's temp
    profile = _installed_profile()
    home = tmp_path / "dsh-home"
    shutil.copytree(profile, home / "profiles" / "headless")
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    env = {"DSH_HOME": str(home), "PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", ""),
           dsh_cli.DSH_CONFINE_RUNNER_ENV: json.dumps([sys.executable, "-I", str(dsh_cli.DSH_CONFINE_RUNNER)])}
    dsh_cli.verify_confidential_launch(env, str(worktree))
