"""Claude account swap: per-account config dirs, selector, env integration (AGE-125)."""

import json
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

import claude_account as ca

FUTURE = (time.time() + 3600) * 1000


def creds(refresh="rt", access="at"):
    return {"claudeAiOauth": {"accessToken": access, "refreshToken": refresh, "expiresAt": FUTURE}}


class FakeSecurity:
    """Stands in for /usr/bin/security. AGE-125 reads credentials and never writes them."""

    def __init__(self):
        self.items: dict[str, str] = {}
        self.argvs: list[list[str]] = []

    def __call__(self, args):
        self.argvs.append(list(args))
        assert args[0] == "find-generic-password", args
        service = args[args.index("-s") + 1]
        if service not in self.items:
            return subprocess.CompletedProcess(args, 44, "", "not found")
        return subprocess.CompletedProcess(args, 0, self.items[service] + "\n", "")


class FakeClaude:
    """Stands in for `claude auth login` / `claude auth status --json`."""

    def __init__(self, security: FakeSecurity):
        self.security = security
        self.status: dict[str, dict] = {}
        self.calls: list[tuple[list[str], dict]] = []
        self.login_email = "user@example.com"
        self.exit_code = 0
        self.logged_in = True
        self.reported_dir = None
        self.result_email = None  # what the browser really signed in as, independent of --email

    def run(self, argv, env):
        self.calls.append((list(argv), dict(env)))
        config_dir = env["CLAUDE_CONFIG_DIR"]
        email = (self.result_email
                 or (argv[argv.index("--email") + 1] if "--email" in argv else self.login_email))
        self.status[config_dir] = {
            "loggedIn": self.logged_in, "email": email, "subscriptionType": "pro",
            "configDirectory": self.reported_dir or config_dir,
            "projectsDirectory": config_dir + "/projects"}
        if self.logged_in:
            self.security.items[ca.keychain_service(config_dir)] = json.dumps(creds())
        return subprocess.CompletedProcess(argv, self.exit_code, "", "")

    def auth_status(self, config_dir, timeout=60):
        key = str(config_dir)
        if key not in self.status:
            raise ca.AccountError(f"no status for {key}")
        return dict(self.status[key])


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(ca, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(ca, "ACCOUNTS_ROOT", tmp_path / "state" / "claude-accounts")
    monkeypatch.setattr(ca, "INDEX", tmp_path / "state" / "claude-accounts.json")
    monkeypatch.setattr(ca, "LOCK", tmp_path / "state" / "claude-account.lock")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(ca, "HOME_CLAUDE", home / ".claude")
    monkeypatch.setattr(ca, "HOME_CLAUDE_JSON", home / ".claude.json")
    (home / ".claude").mkdir()
    (home / ".claude" / "skills").mkdir()
    (home / ".claude" / "settings.json").write_text("{}")
    (home / ".claude" / "history.jsonl").write_text("")
    (home / ".claude" / ".credentials.json").write_text("{}")
    (home / ".claude" / "backups").mkdir()
    (home / ".claude.json").write_text(json.dumps({"hasCompletedOnboarding": True}))
    for name in (*ca.OVERRIDE_ENV, "CLAUDE_CONFIG_DIR"):
        monkeypatch.delenv(name, raising=False)
    security = FakeSecurity()
    claude = FakeClaude(security)
    monkeypatch.setattr(ca, "_security", security)
    monkeypatch.setattr(ca, "_run", claude.run)
    monkeypatch.setattr(ca, "auth_status", claude.auth_status)
    monkeypatch.setattr(ca, "_running_claude", lambda: 0)
    return SimpleNamespace(tmp=tmp_path, home=home, security=security, claude=claude,
                           cfg=lambda label: ca.account_dir(label))


def login(env, label, email=None):
    env.claude.login_email = email or f"{label}@example.com"
    return ca.login(label, email)


# ── Naming and keychain service ─────────────────────────────────────────────

def test_keychain_service_hashes_the_exact_directory():
    import hashlib
    directory = "/tmp/age125-accounts/nyu"
    assert ca.keychain_service(directory) == (
        "Claude Code-credentials-" + hashlib.sha256(directory.encode()).hexdigest()[:8])


def test_keychain_service_does_not_resolve_symlinks(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    assert ca.keychain_service(link) != ca.keychain_service(real)


def test_keychain_service_normalizes_nfc():
    import unicodedata
    decomposed = "/tmp/" + unicodedata.normalize("NFD", "café")
    composed = unicodedata.normalize("NFC", decomposed)
    assert ca.keychain_service(decomposed) == ca.keychain_service(composed)


def test_normalize_dir_rejects_a_relative_path():
    with pytest.raises(ca.AccountError, match="absolute"):
        ca.normalize_dir("relative/dir")


# ── Account directories ─────────────────────────────────────────────────────

def test_prepare_creates_private_dir_links_shared_entries_and_seeds_config(env):
    account = ca.prepare("a")
    assert oct(account.stat().st_mode & 0o777) == "0o700"
    assert (account / "projects").is_symlink()
    assert (account / "skills").is_symlink()
    assert (account / "settings.json").is_symlink()
    assert (account / "history.jsonl").is_symlink()
    for excluded in (".credentials.json", "backups", ".claude.json"):
        assert not (account / excluded).is_symlink()
    assert json.loads((account / ".claude.json").read_text()) == {"hasCompletedOnboarding": True}
    assert oct((account / ".claude.json").stat().st_mode & 0o777) == "0o600"


def test_prepare_is_idempotent_and_keeps_the_seeded_config(env):
    account = ca.prepare("a")
    links = len([p for p in account.iterdir() if p.is_symlink()])
    (account / ".claude.json").write_text('{"edited": true}')
    ca.prepare("a")
    assert json.loads((account / ".claude.json").read_text()) == {"edited": True}
    assert len([p for p in account.iterdir() if p.is_symlink()]) == links


def test_prepare_never_replaces_a_real_entry(env):
    account = ca.prepare("a")
    (account / "skills").unlink()
    (account / "skills").mkdir()
    (account / "skills" / "mine.md").write_text("x")
    ca.prepare("a")
    assert not (account / "skills").is_symlink()
    assert (account / "skills" / "mine.md").exists()
    assert "skills" in ca.local_only(account)


def test_prepare_bootstraps_projects_so_two_accounts_share_sessions(env):
    assert not (ca.HOME_CLAUDE / "projects").exists()
    first = ca.prepare("a")
    second = ca.prepare("b")
    assert (ca.HOME_CLAUDE / "projects").is_dir()
    assert (first / "projects").is_symlink() and (second / "projects").is_symlink()
    assert (first / "projects").resolve() == (second / "projects").resolve()
    (first / "projects" / "s1.jsonl").write_text("{}\n")
    assert (second / "projects" / "s1.jsonl").exists()


def test_prepare_adopts_an_account_local_projects_directory(env):
    account = ca.prepare("a")
    (account / "projects").unlink()
    (account / "projects").mkdir()
    (account / "projects" / "session.jsonl").write_text("{}\n")
    (ca.HOME_CLAUDE / "projects").rmdir()  # canonical store missing again
    ca.prepare("a")
    assert (account / "projects").is_symlink()
    assert (ca.HOME_CLAUDE / "projects" / "session.jsonl").exists()


def test_prepare_creates_every_shared_store_on_a_clean_machine(env):
    import shutil
    shutil.rmtree(ca.HOME_CLAUDE)
    first = ca.prepare("a")
    for name in ca.SHARED_DIRS:
        assert (ca.HOME_CLAUDE / name).is_dir()
        assert (first / name).is_symlink()
    for name in ("settings.json", "CLAUDE.md"):
        assert (ca.HOME_CLAUDE / name).is_file()
        assert (first / name).is_symlink()
    # what account A installs into a shared store is visible to account B
    (first / "skills" / "new-skill.md").write_text("x")
    (first / "settings.json").write_text('{"model": "opus"}')
    second = ca.prepare("b")
    assert (second / "skills" / "new-skill.md").exists()
    assert json.loads((second / "settings.json").read_text()) == {"model": "opus"}


def test_prepare_adopts_a_local_skills_store_when_the_canonical_one_is_absent(env):
    account = ca.prepare("a")
    (account / "skills").unlink()
    (account / "skills").mkdir()
    (account / "skills" / "mine.md").write_text("x")
    (ca.HOME_CLAUDE / "skills").rmdir()
    ca.prepare("a")
    assert (account / "skills").is_symlink()
    assert (ca.HOME_CLAUDE / "skills" / "mine.md").exists()


def test_prepare_adopts_a_local_settings_file_when_the_canonical_one_is_absent(env):
    account = ca.prepare("a")
    (account / "settings.json").unlink()
    (account / "settings.json").write_text('{"model": "opus"}')
    (ca.HOME_CLAUDE / "settings.json").unlink()
    ca.prepare("a")
    assert (account / "settings.json").is_symlink()
    assert json.loads((ca.HOME_CLAUDE / "settings.json").read_text()) == {"model": "opus"}


def test_prepare_adopts_projects_when_home_claude_itself_is_absent(env):
    account = ca.prepare("a")
    (account / "projects").unlink()
    (account / "projects").mkdir()
    (account / "projects" / "s.jsonl").write_text("{}\n")
    import shutil
    shutil.rmtree(ca.HOME_CLAUDE)
    ca.prepare("a")
    assert (account / "projects").is_symlink()
    assert (ca.HOME_CLAUDE / "projects" / "s.jsonl").exists()


def test_prepare_reports_a_local_projects_directory_when_the_store_exists(env):
    account = ca.prepare("a")
    (account / "projects").unlink()
    (account / "projects").mkdir()
    ca.prepare("a")
    assert not (account / "projects").is_symlink()
    assert "projects" in ca.local_only(account)


def test_prepare_refuses_a_symlinked_account_directory(env):
    ca.ACCOUNTS_ROOT.mkdir(parents=True)
    (env.tmp / "elsewhere").mkdir()
    (ca.ACCOUNTS_ROOT / "a").symlink_to(env.tmp / "elsewhere")
    with pytest.raises(ca.AccountError, match="symlink"):
        ca.prepare("a")


# ── login / save ────────────────────────────────────────────────────────────

def test_login_records_identity_and_activates_the_first_account(env):
    result = login(env, "nyu", "a@example.com")
    assert result == {"ok": True, "label": "nyu", "email": "a@example.com", "subscription": "pro",
                      "dir": ca.normalize_dir(ca.account_dir("nyu")), "active": "nyu"}
    index = json.loads(ca.INDEX.read_text())
    assert index["active"] == "nyu"
    assert index["accounts"]["nyu"]["email"] == "a@example.com"
    assert oct(ca.INDEX.stat().st_mode & 0o777) == "0o600"


def test_login_passes_the_exact_config_dir_and_email_flag(env):
    login(env, "nyu", "a@example.com")
    argv, child_env = env.claude.calls[-1]
    assert argv[1:3] == ["auth", "login"]
    assert argv[argv.index("--email") + 1] == "a@example.com"
    assert child_env["CLAUDE_CONFIG_DIR"] == ca.normalize_dir(ca.account_dir("nyu"))


def test_a_second_login_does_not_switch_the_active_account(env):
    login(env, "nyu")
    login(env, "rancho")
    assert ca.accounts()["active"] == "nyu"


def test_login_refuses_a_non_zero_exit_and_records_nothing(env):
    env.claude.exit_code = 2
    with pytest.raises(ca.AccountError, match="exited 2"):
        login(env, "nyu")
    assert not ca.INDEX.exists()


def test_login_refuses_when_status_says_logged_out(env):
    env.claude.logged_in = False
    with pytest.raises(ca.AccountError, match="not logged in"):
        login(env, "nyu")
    assert not ca.INDEX.exists()


def test_login_refuses_a_different_reported_config_directory(env):
    login(env, "nyu")
    env.claude.reported_dir = "/somewhere/else"
    with pytest.raises(ca.AccountError, match="config directory"):
        login(env, "rancho")
    assert ca.accounts()["active"] == "nyu" and "rancho" not in ca.INDEX.read_text()


def test_login_refuses_an_email_mismatch(env):
    env.claude.result_email = "wrong@example.com"
    with pytest.raises(ca.AccountError, match="logged in as"):
        ca.login("nyu", "expected@example.com")
    assert not ca.INDEX.exists()


def test_login_refuses_an_email_already_saved_under_another_label(env):
    login(env, "nyu", "same@example.com")
    with pytest.raises(ca.AccountError, match="already saved as 'nyu'"):
        login(env, "rancho", "same@example.com")
    assert ca.accounts()["active"] == "nyu"


@pytest.mark.parametrize("label", ["../x", "a@b", "", "x" * 33])
def test_login_refuses_an_invalid_label(env, label):
    with pytest.raises(ca.AccountError, match="label"):
        ca.login(label)


@pytest.mark.parametrize("variable", ca.OVERRIDE_ENV)
def test_login_refuses_override_variables(env, monkeypatch, variable):
    monkeypatch.setenv(variable, "x")
    with pytest.raises(ca.AccountError, match=variable):
        ca.login("nyu")
    assert env.claude.calls == []


def test_save_records_an_existing_login_without_launching(env):
    account = ca.prepare("nyu")
    env.claude.login_email = "a@example.com"
    env.claude.run(["claude", "auth", "login"], ca._env_for(account))
    env.claude.calls.clear()
    result = ca.record("nyu")
    assert result["email"] == "a@example.com"
    assert env.claude.calls == []  # no browser launch
    assert ca.accounts()["active"] == "nyu"


def test_save_requires_an_account_directory(env):
    with pytest.raises(ca.AccountError, match="no account directory"):
        ca.record("nyu")


# ── use ─────────────────────────────────────────────────────────────────────

def test_use_switches_and_bumps_the_generation(env):
    login(env, "nyu")
    login(env, "rancho")
    before = ca.swap_generation()
    time.sleep(0.01)
    result = ca.use("rancho")
    assert result["label"] == "rancho" and result["warnings"] == []
    assert ca.accounts()["active"] == "rancho"
    assert ca.swap_generation() != before


def test_use_links_shared_names_that_appeared_later(env):
    login(env, "nyu")
    login(env, "rancho")
    (ca.HOME_CLAUDE / "downloads").mkdir()
    ca.use("rancho")
    assert (ca.account_dir("rancho") / "downloads").is_symlink()


@pytest.mark.parametrize("label", ["nope", "../x"])
def test_use_refuses_an_unknown_or_invalid_label(env, label):
    login(env, "nyu")
    with pytest.raises(ca.AccountError):
        ca.use(label)


def test_use_refuses_a_missing_account_directory(env):
    login(env, "nyu")
    import shutil
    shutil.rmtree(ca.account_dir("nyu"))
    with pytest.raises(ca.AccountError, match="missing"):
        ca.use("nyu")


def test_use_warns_when_the_target_reports_logged_out(env):
    login(env, "nyu")
    login(env, "rancho")
    env.claude.status[str(ca.account_dir("rancho"))]["loggedIn"] = False
    result = ca.use("rancho")
    assert result["ok"] and any("not logged in" in w for w in result["warnings"])


def test_use_warns_when_the_target_cannot_be_verified(env):
    login(env, "nyu")
    login(env, "rancho")
    env.claude.status.pop(str(ca.account_dir("rancho")))
    result = ca.use("rancho")
    assert any("could not verify" in w for w in result["warnings"])


def test_use_warns_when_the_credential_is_unreadable(env):
    login(env, "nyu")
    login(env, "rancho")
    env.security.items.pop(ca.keychain_service(ca.account_dir("rancho")))
    result = ca.use("rancho")
    assert any("no readable credential" in w for w in result["warnings"])


def test_use_warns_about_running_claude_processes(env, monkeypatch):
    login(env, "nyu")
    monkeypatch.setattr(ca, "_running_claude", lambda: 2)
    assert any("2 running claude" in w for w in ca.use("nyu")["warnings"])


def test_use_never_writes_a_credential(env):
    login(env, "nyu")
    login(env, "rancho")
    ca.use("rancho")
    assert env.security.argvs and all(argv[0] == "find-generic-password"
                                      for argv in env.security.argvs)


def test_use_waits_for_the_cross_process_index_lock(env):
    login(env, "nyu")
    code = ("import fcntl,sys,time\n"
            "f=open(sys.argv[1],'a')\n"
            "fcntl.flock(f,fcntl.LOCK_EX)\n"
            "print('held',flush=True)\n"
            "time.sleep(1.5)\n")
    holder = subprocess.Popen([sys.executable, "-c", code, str(ca.LOCK)],
                              stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "held"
        started = time.monotonic()
        ca.use("nyu")
        assert time.monotonic() - started > 0.8
    finally:
        holder.wait(timeout=10)


# ── Index and env ───────────────────────────────────────────────────────────

def test_accounts_is_a_pure_index_read(env, monkeypatch):
    login(env, "nyu")

    def forbidden(*args, **kwargs):
        raise AssertionError("accounts() must not leave the index")
    monkeypatch.setattr(ca, "_kc_read", forbidden)
    monkeypatch.setattr(ca, "_running_claude", forbidden)
    assert ca.accounts() == {"accounts": [{"label": "nyu", "email": "nyu@example.com"}],
                             "active": "nyu"}


def test_legacy_index_is_ignored_everywhere(env, capsys):
    ca.INDEX.parent.mkdir(parents=True)
    ca.INDEX.write_text(json.dumps({"nyu": {"uuid": "u-1", "email": "old@example.com"}}))
    assert ca.accounts() == {"accounts": [], "active": None}
    assert ca.legacy_index() is True
    assert ca.activate_env({"OTHER": "kept"}) == {"OTHER": "kept"}
    assert ca.main(["list"]) == 0
    assert "retired snapshot index" in capsys.readouterr().err


def test_activate_env_overrides_an_existing_value(env):
    login(env, "nyu")
    assert ca.activate_env({"CLAUDE_CONFIG_DIR": "/somewhere/else"})["CLAUDE_CONFIG_DIR"] == \
        ca.normalize_dir(ca.account_dir("nyu"))


def test_activate_env_leaves_runs_unchanged_without_an_account(env):
    assert ca.activate_env({"A": "1"}) == {"A": "1"}


def test_activate_env_ignores_an_unreadable_index(env):
    ca.INDEX.parent.mkdir(parents=True)
    ca.INDEX.write_text("{not json")
    assert ca.activate_env({"A": "1"}) == {"A": "1"}


def test_activate_env_keeps_a_selected_account_whose_directory_is_missing(env):
    login(env, "nyu")
    import shutil
    shutil.rmtree(ca.account_dir("nyu"))
    # Never fall back to the default login when an account is selected: Claude must fail loudly.
    assert ca.activate_env({"A": "1"})["CLAUDE_CONFIG_DIR"] == \
        ca.normalize_dir(ca.account_dir("nyu"))


def test_inherit_env_preserves_an_explicit_value(env):
    login(env, "nyu")
    assert ca.inherit_env({"CLAUDE_CONFIG_DIR": "/explicit"})["CLAUDE_CONFIG_DIR"] == "/explicit"
    assert ca.inherit_env({})["CLAUDE_CONFIG_DIR"] == ca.normalize_dir(ca.account_dir("nyu"))


# ── Credentials for the quota cards ─────────────────────────────────────────

def test_access_token_reads_the_active_account_item(env):
    login(env, "nyu")
    login(env, "rancho")
    ca.use("rancho")
    assert ca.access_token() == "at"


def test_access_token_falls_back_to_the_plaintext_file(env):
    login(env, "nyu")
    env.security.items.pop(ca.keychain_service(ca.account_dir("nyu")))
    (ca.account_dir("nyu") / ".credentials.json").write_text(
        json.dumps(creds(access="file-token")))
    assert ca.access_token() == "file-token"


def test_access_token_uses_the_default_login_only_when_nothing_is_configured(env):
    env.security.items[ca.DEFAULT_SERVICE] = json.dumps(creds(access="default-token"))
    assert ca.access_token() == "default-token"


def test_access_token_never_falls_back_to_the_default_item_for_an_active_account(env):
    login(env, "nyu")
    env.security.items.pop(ca.keychain_service(ca.account_dir("nyu")))
    env.security.items[ca.DEFAULT_SERVICE] = json.dumps(creds(access="someone-else"))
    assert ca.access_token() is None


def test_access_token_still_reads_the_file_when_the_keychain_fails(env, monkeypatch):
    login(env, "nyu")
    (ca.account_dir("nyu") / ".credentials.json").write_text(
        json.dumps(creds(access="file-token")))
    monkeypatch.setattr(ca, "_kc_read", lambda service: (_ for _ in ()).throw(ca.AccountError("boom")))
    assert ca.access_token() == "file-token"


def test_access_token_uses_the_file_after_a_keychain_timeout(env, monkeypatch):
    login(env, "nyu")
    (ca.account_dir("nyu") / ".credentials.json").write_text(json.dumps(creds(access="file-token")))

    def timeout(args):
        raise subprocess.TimeoutExpired("security", 15)
    monkeypatch.setattr(ca, "_security", timeout)
    assert ca.access_token() == "file-token"


def test_use_warns_instead_of_failing_on_a_keychain_timeout(env, monkeypatch):
    login(env, "nyu")
    login(env, "rancho")

    def timeout(args):
        raise subprocess.TimeoutExpired("security", 15)
    monkeypatch.setattr(ca, "_security", timeout)
    result = ca.use("rancho")
    assert result["ok"]
    assert any("no readable credential" in w for w in result["warnings"])


def test_status_reports_an_unreadable_credential_on_a_keychain_timeout(env, monkeypatch):
    login(env, "nyu")

    def timeout(args):
        raise subprocess.TimeoutExpired("security", 15)
    monkeypatch.setattr(ca, "_security", timeout)
    data = ca.status()
    assert data["credential"] == "unreadable" and "security" in data["error"]


def test_access_token_is_none_when_both_sources_fail(env, monkeypatch):
    login(env, "nyu")
    monkeypatch.setattr(ca, "_kc_read", lambda service: (_ for _ in ()).throw(ca.AccountError("boom")))
    assert ca.access_token() is None


# ── CLI ─────────────────────────────────────────────────────────────────────

def test_cli_lists_accounts_and_marks_the_active_one(env, capsys):
    login(env, "nyu")
    login(env, "rancho")
    assert ca.main(["list"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("* nyu") and out[1].startswith("  rancho")


def test_cli_use_prints_the_new_account(env, capsys):
    login(env, "nyu")
    login(env, "rancho")
    env.claude.status[str(ca.account_dir("rancho"))]["loggedIn"] = False
    assert ca.main(["use", "rancho"]) == 0
    assert "now using rancho" in capsys.readouterr().out


def test_cli_status_never_prints_a_token(env, capsys):
    login(env, "nyu")
    env.security.items[ca.keychain_service(ca.account_dir("nyu"))] = json.dumps(
        creds(access="sk-ant-secret-token"))
    assert ca.main(["status"]) == 0
    captured = capsys.readouterr()
    assert "sk-ant-secret-token" not in captured.out + captured.err
    assert "active: nyu" in captured.out and "credential: keychain" in captured.out


def test_cli_claude_execs_with_the_active_env(env, monkeypatch):
    login(env, "nyu")
    seen = {}

    def fake_exec(binary, argv, child_env):
        seen.update(binary=binary, argv=argv, env=child_env)
    monkeypatch.setattr(ca.os, "execvpe", fake_exec)
    assert ca.main(["claude", "--resume", "s1"]) == 0
    assert seen["argv"][1:] == ["--resume", "s1"]
    assert seen["env"]["CLAUDE_CONFIG_DIR"] == ca.normalize_dir(ca.account_dir("nyu"))


def test_cli_reports_an_account_error_without_a_traceback(env, capsys):
    assert ca.main(["use", "nope"]) == 1
    assert "no saved account" in capsys.readouterr().err


# ── Runner integration ──────────────────────────────────────────────────────

@pytest.fixture
def app_mod(env, monkeypatch, tmp_path):
    import app
    monkeypatch.setattr(app, "REGISTRY_CACHE_DIR", tmp_path / "registry")
    return app


def test_registry_exec_env_sets_the_account_for_claude_only(app_mod, env):
    login(env, "nyu")
    assert app_mod._registry_exec_env("claude", {})["CLAUDE_CONFIG_DIR"] == \
        ca.normalize_dir(ca.account_dir("nyu"))
    assert "CLAUDE_CONFIG_DIR" not in app_mod._registry_exec_env("codex", {})
    assert "CLAUDE_CONFIG_DIR" not in app_mod._registry_exec_env("dsh", {})


def test_run_agent_process_applies_the_account_after_project_env(app_mod, env, tmp_path, monkeypatch):
    login(env, "nyu")
    monkeypatch.setattr(app_mod, "RUN_PROGRESS_DIR", tmp_path / "progress")
    script = tmp_path / "dump.py"
    script.write_text(
        "import json, os\n"
        "print(json.dumps({'type': 'result', 'session_id': 's1', "
        "'result': os.environ.get('CLAUDE_CONFIG_DIR', '')}), flush=True)\n")
    app_mod._running_jobs["acct"] = {"run_id": "acct"}
    try:
        output, *_rest = app_mod.run_agent_process(
            "acct", [sys.executable, str(script)], stream="claude", timeout=20,
            env={"CLAUDE_CONFIG_DIR": "/from-projects-yaml"})
    finally:
        app_mod._running_jobs.pop("acct", None)
    assert output == ca.normalize_dir(ca.account_dir("nyu"))


def test_project_run_agent_applies_the_account_after_project_env(env, tmp_path):
    import project_runs
    login(env, "nyu")
    script = tmp_path / "dump.py"
    script.write_text(
        "import os, pathlib\n"
        "pathlib.Path('seen.txt').write_text(os.environ.get('CLAUDE_CONFIG_DIR', ''))\n")
    _lines, _err, code, _timed = project_runs.run_agent(
        [sys.executable, str(script)], str(tmp_path),
        {"CLAUDE_CONFIG_DIR": "/from-projects-yaml"}, "acctrun", "claude", 30,
        lambda *args, **kwargs: None)
    assert code == 0 and (tmp_path / "seen.txt").read_text() == \
        ca.normalize_dir(ca.account_dir("nyu"))


def test_terminal_tabs_get_the_active_account(env):
    import runner.modules.pty as tpty
    login(env, "nyu")
    assert tpty._shell_env()["CLAUDE_CONFIG_DIR"] == ca.normalize_dir(ca.account_dir("nyu"))


def test_terminal_tabs_win_over_a_project_config_dir(env):
    import runner.modules.pty as tpty
    login(env, "nyu")
    project = SimpleNamespace(env={"CLAUDE_CONFIG_DIR": "/from-projects-yaml"})
    assert tpty._shell_env(project)["CLAUDE_CONFIG_DIR"] == \
        ca.normalize_dir(ca.account_dir("nyu"))


def test_run_skill_passes_the_account_to_the_skill_script(env, tmp_path, monkeypatch):
    import run_skill
    login(env, "nyu")
    root = tmp_path / "skillroot"
    root.mkdir()
    (root / "ok.py").write_text(
        "import os, pathlib\n"
        "pathlib.Path('seen.txt').write_text(os.environ.get('CLAUDE_CONFIG_DIR', ''))\n")
    monkeypatch.setattr(run_skill, "ROOT", root)
    monkeypatch.setattr(run_skill, "_append_log", lambda record: None)
    monkeypatch.setattr(run_skill, "_update_state", lambda record: None)
    assert run_skill.run_once("s", "ok.py", [])["status"] == "success"
    assert (root / "seen.txt").read_text() == ca.normalize_dir(ca.account_dir("nyu"))


def test_quota_fetch_uses_the_account_access_token(app_mod, env, monkeypatch):
    login(env, "nyu")
    seen = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b'{"five_hour": {"utilization": 40}}'

    def urlopen(request, timeout=None):
        seen["auth"] = request.get_header("Authorization")
        return Response()

    monkeypatch.setattr(app_mod.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(app_mod, "_claude_cli_user_agent", lambda: "ua")
    assert app_mod._fetch_claude_oauth_usage() == {"five_hour": {"utilization": 40}}
    assert seen["auth"] == "Bearer at"


def test_stream_claude_error_result_is_a_failed_run(app_mod, env, tmp_path, monkeypatch):
    monkeypatch.setattr(app_mod, "RUN_PROGRESS_DIR", tmp_path / "progress")
    script = tmp_path / "fake.py"
    script.write_text(
        "import json\n"
        "print(json.dumps({'type': 'system', 'subtype': 'init', 'session_id': 's1'}), flush=True)\n"
        "print(json.dumps({'type': 'result', 'is_error': True, 'result': 'Not logged in', "
        "'session_id': 's1'}), flush=True)\n")
    proc = subprocess.Popen([sys.executable, str(script)], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    out, _it, _ot, _pm, sid, _err, ok = app_mod._stream_claude_run(proc, "authfail", timeout=20)
    assert out == "Not logged in" and sid == "s1" and ok is False


def test_parse_project_output_reports_the_result_text_as_the_error(app_mod):
    events = [json.dumps({"type": "result", "is_error": True, "result": "Not logged in",
                          "session_id": "s1"})]
    parsed = app_mod._parse_project_output("claude", events, "", 0)
    assert parsed[5] is False and parsed[6] == "Not logged in"


# ── Dashboard wiring ────────────────────────────────────────────────────────

def test_endpoints_need_the_request_token(app_mod, env):
    login(env, "nyu")
    client = app_mod.app.test_client()
    assert client.get("/api/claude-accounts").status_code == 403
    assert client.post("/api/claude-accounts/use", json={"label": "nyu"}).status_code == 403


def test_endpoints_list_and_use(app_mod, env):
    login(env, "nyu")
    login(env, "rancho")
    client = app_mod.app.test_client()
    headers = {"X-AgenticOS-Token": app_mod.REQUEST_TOKEN}
    listed = client.get("/api/claude-accounts", headers=headers)
    assert listed.json == {"accounts": [{"label": "nyu", "email": "nyu@example.com"},
                                        {"label": "rancho", "email": "rancho@example.com"}],
                           "active": "nyu"}
    switched = client.post("/api/claude-accounts/use", json={"label": "rancho"}, headers=headers)
    assert switched.json["ok"] and ca.accounts()["active"] == "rancho"
    missing = client.post("/api/claude-accounts/use", json={"label": "nope"}, headers=headers)
    assert missing.status_code == 400 and "no saved account" in missing.json["error"]


def test_dashboard_select_needs_two_accounts(app_mod, env):
    login(env, "nyu")
    html = app_mod.app.test_client().get("/").text
    assert 'class="claude-account-select"' not in html
    login(env, "rancho")
    html = app_mod.app.test_client().get("/").text
    assert 'class="claude-account-select"' in html
    assert '<option value="nyu" title="nyu@example.com" selected>' in html


def test_external_swap_clears_cached_usage(app_mod, env, monkeypatch):
    login(env, "nyu")
    login(env, "rancho")
    clock = [1000.0]
    monkeypatch.setattr(app_mod.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(app_mod, "_claude_usage_cache", (0.0, None))
    monkeypatch.setattr(app_mod, "_claude_usage_retry_at", 0.0)
    monkeypatch.setattr(app_mod, "_claude_usage_gen", ca.swap_generation())
    calls = []
    monkeypatch.setattr(app_mod, "_fetch_claude_oauth_usage",
                        lambda: calls.append(1) or {"five_hour": {"utilization": 40}})
    assert app_mod._load_claude_oauth_usage()[0] == {"five_hour": {"utilization": 40}}
    clock[0] += 0.01
    time.sleep(0.01)
    ca.use("rancho")
    app_mod._load_claude_oauth_usage()
    assert len(calls) == 2


def test_pre_swap_rate_limit_snapshot_is_not_live(app_mod, env, tmp_path, monkeypatch):
    login(env, "nyu")
    snapshot = tmp_path / "rate-limits-live.json"
    monkeypatch.setattr(app_mod, "CLAUDE_RATE_LIMITS_LIVE", snapshot)
    snapshot.write_text(json.dumps({"captured_at": "2000-01-01T00:00:00Z",
                                    "rate_limits": {"five_hour": {}}}))
    assert app_mod._claude_live_snapshot() == {}
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 5))
    snapshot.write_text(json.dumps({"captured_at": now, "rate_limits": {"five_hour": {}}}))
    assert app_mod._claude_live_snapshot()["captured_at"] == now


def test_swap_during_a_fetch_is_not_published(app_mod, env, monkeypatch):
    login(env, "nyu")
    login(env, "rancho")
    monkeypatch.setattr(app_mod, "_claude_usage_cache", (0.0, None))
    monkeypatch.setattr(app_mod, "_claude_usage_retry_at", 0.0)
    monkeypatch.setattr(app_mod, "_claude_usage_gen", ca.swap_generation())

    def fetch():
        ca.use("rancho")
        return {"five_hour": {"utilization": 40}}

    monkeypatch.setattr(app_mod, "_fetch_claude_oauth_usage", fetch)
    assert app_mod._load_claude_oauth_usage() == ({}, 0.0)
