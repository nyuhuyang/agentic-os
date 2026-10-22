"""Claude account swap: keychain snapshots, ownership, locking, dashboard wiring (AGE-125)."""

import json
import os
import shlex
import subprocess
import threading
import time

import pytest

import claude_account as ca

FUTURE = (time.time() + 3600) * 1000
UUID_A, UUID_B = "uuid-a", "uuid-b"


def creds(rt, at="at", expires=FUTURE):
    return {"claudeAiOauth": {"accessToken": at, "refreshToken": rt, "expiresAt": expires}}


class FakeKeychain:
    """Stands in for /usr/bin/security; records every argv and stdin."""

    def __init__(self):
        self.items: dict[tuple[str, str], str] = {}
        self.argvs: list[list[str]] = []
        self.stdins: list[str] = []

    def __call__(self, args, stdin=None):
        self.argvs.append(list(args))
        if args == ["-i"]:
            self.stdins.append(stdin)
            a = shlex.split(stdin)
            assert a[0] == "add-generic-password" and "-U" in a
            acct, svc, hexd = a[a.index("-a") + 1], a[a.index("-s") + 1], a[a.index("-X") + 1]
            self.items[(svc, acct)] = bytes.fromhex(hexd).decode()
            return subprocess.CompletedProcess(args, 0, "", "")
        assert args[0] == "find-generic-password"
        svc = args[args.index("-s") + 1]
        acct = args[args.index("-a") + 1] if "-a" in args else None
        hit = [(k, v) for k, v in self.items.items() if k[0] == svc and (acct is None or k[1] == acct)]
        if not hit:
            return subprocess.CompletedProcess(args, 44, "", "not found")
        (svc, acct), secret = hit[0]
        out = secret + "\n" if "-w" in args else f'    "acct"<blob>="{acct}"\n'
        return subprocess.CompletedProcess(args, 0, out, "")

    def live(self):
        return json.loads(self.items[(ca.LIVE_SERVICE, "me")])

    def set_live(self, blob):
        self.items[(ca.LIVE_SERVICE, "me")] = json.dumps(blob)

    def snap(self, label):
        return json.loads(self.items[(ca.SNAP_SERVICE, label)])


@pytest.fixture
def kc(tmp_path, monkeypatch):
    k = FakeKeychain()
    monkeypatch.setattr(ca, "_security", k)
    monkeypatch.setattr(ca, "STATE_DIR", tmp_path / "aos")
    monkeypatch.setattr(ca, "INDEX", tmp_path / "aos" / "claude-accounts.json")
    monkeypatch.setattr(ca, "LOCK", tmp_path / "aos" / "claude-account.lock")
    monkeypatch.setattr(ca, "CLAUDE_JSON", tmp_path / ".claude.json")
    monkeypatch.setattr(ca, "_running_claude", lambda: 0)
    for v in ca.OVERRIDE_ENV:
        monkeypatch.delenv(v, raising=False)
    k.profiles = {}  # access token -> uuid

    def profile(token):
        uuid = k.profiles.get(token)
        return {"account": {"uuid": uuid, "email": f"{uuid}@x", "display_name": uuid},
                "organization": {"uuid": "org-" + uuid, "name": "Org"}} if uuid else None
    monkeypatch.setattr(ca, "_fetch_profile", profile)
    return k


def login(kc, uuid, rt, at):
    """Simulate `claude auth login`: live keychain blob + oauthAccount."""
    kc.set_live(creds(rt, at))
    kc.profiles[at] = uuid
    cfg = ca._read_json(ca.CLAUDE_JSON)
    cfg.update({"other": 1, "oauthAccount": {"accountUuid": uuid, "emailAddress": f"{uuid}@x", "extra": 7}})
    ca.CLAUDE_JSON.write_text(json.dumps(cfg))
    os.chmod(ca.CLAUDE_JSON, 0o600)


@pytest.fixture
def two(kc):
    login(kc, UUID_A, "rt-a", "at-a")
    ca.save("a")
    login(kc, UUID_B, "rt-b", "at-b")
    ca.save("b")
    return kc


def test_save_stores_verified_snapshot_and_index(two):
    assert two.snap("a") == creds("rt-a", "at-a")
    idx = json.loads(ca.INDEX.read_text())
    assert {k: (v["uuid"], v["email"]) for k, v in idx.items()} == {"a": (UUID_A, "uuid-a@x"),
                                                                     "b": (UUID_B, "uuid-b@x")}
    assert idx["a"]["oauthAccount"]["extra"] == 7  # live identity kept when its uuid matches
    assert oct(ca.INDEX.stat().st_mode & 0o777) == "0o600"


def test_save_rejects_invalid_label(kc):
    with pytest.raises(ca.AccountError):
        ca.save("../x")


def test_save_refuses_uuid_saved_under_other_label(two):
    with pytest.raises(ca.AccountError, match="already saved as 'b'"):
        ca.save("alias")


def test_save_rebuilds_mismatched_identity_from_profile(kc):
    login(kc, UUID_A, "rt-a", "at-a")
    kc.set_live(creds("rt-b", "at-b"))  # keychain is B, oauthAccount still says A
    kc.profiles["at-b"] = UUID_B
    ca.save("b")
    meta = ca._index()["b"]["oauthAccount"]
    assert meta["accountUuid"] == UUID_B and meta["emailAddress"] == "uuid-b@x" and "extra" not in meta


def test_save_refuses_unverifiable_login(kc):
    kc.set_live(creds("rt", "at-unknown"))
    with pytest.raises(ca.AccountError, match="verify"):
        ca.save("a")


def test_use_resaves_outgoing_by_refresh_token_and_switches(two):
    two.set_live(creds("rt-b", "at-b2"))  # B's access token refreshed, refresh token unchanged
    r = ca.use("a")
    assert r["ok"] and r["label"] == "a"
    assert two.snap("b") == creds("rt-b", "at-b2")
    assert two.live() == creds("rt-a", "at-a")
    cfg = json.loads(ca.CLAUDE_JSON.read_text())
    assert cfg["oauthAccount"]["accountUuid"] == UUID_A and cfg["other"] == 1
    assert oct(ca.CLAUDE_JSON.stat().st_mode & 0o777) == "0o600"


def test_use_finds_rotated_owner_via_profile_and_keeps_identity(two):
    two.set_live(creds("rt-b-rotated", "at-b3"))
    two.profiles["at-b3"] = UUID_B
    ca.use("a")
    assert two.snap("b")["claudeAiOauth"]["refreshToken"] == "rt-b-rotated"
    meta = ca._index()["b"]
    assert meta["oauthAccount"]["accountUuid"] == UUID_B and meta["uuid"] == UUID_B


def test_use_refuses_unknown_owner_without_writes(two):
    two.set_live(creds("rt-c", "at-c"))
    before = dict(two.items), ca.CLAUDE_JSON.read_text(), ca.INDEX.stat().st_mtime_ns
    with pytest.raises(ca.AccountError, match="not a saved account"):
        ca.use("a")
    assert (dict(two.items), ca.CLAUDE_JSON.read_text(), ca.INDEX.stat().st_mtime_ns) == before


def test_use_force_discards_unknown_login(two):
    two.set_live(creds("rt-c", "at-c"))
    snaps = two.snap("a"), two.snap("b")
    r = ca.use("a", force=True)
    assert two.live() == creds("rt-a", "at-a") and (two.snap("a"), two.snap("b")) == snaps
    assert any("discarded" in w for w in r["warnings"])


def test_use_same_label_repairs(two):
    cfg = json.loads(ca.CLAUDE_JSON.read_text())
    cfg["oauthAccount"] = {"accountUuid": UUID_A}  # identity drifted; keychain is still B
    ca.CLAUDE_JSON.write_text(json.dumps(cfg))
    ca.use("b")
    assert json.loads(ca.CLAUDE_JSON.read_text())["oauthAccount"]["accountUuid"] == UUID_B
    assert two.live() == creds("rt-b", "at-b")


def test_use_unknown_target_refused_before_writes(two):
    writes = len(two.stdins)
    with pytest.raises(ca.AccountError, match="no saved account"):
        ca.use("zz")
    assert len(two.stdins) == writes


def test_oauthaccount_write_failure_is_warning(two, monkeypatch):
    real = ca._write_json_atomic

    def fail(path, data, mode):
        if path == ca.CLAUDE_JSON:
            raise OSError("disk full")
        return real(path, data, mode)
    monkeypatch.setattr(ca, "_write_json_atomic", fail)
    r = ca.use("a")
    assert r["ok"] and two.live() == creds("rt-a", "at-a")
    assert any("disk full" in w for w in r["warnings"])
    assert ca.main(["use", "b"]) == 0


@pytest.mark.parametrize("var", ca.OVERRIDE_ENV)
def test_env_override_refused(two, monkeypatch, var):
    monkeypatch.setenv(var, "x")
    with pytest.raises(ca.AccountError, match=var):
        ca.use("a")
    with pytest.raises(ca.AccountError, match=var):
        ca.save("a")


def test_no_secret_on_argv_or_output(two, capsys):
    ca.main(["use", "a"])
    ca.main(["list"])
    out = capsys.readouterr()
    secrets = ("rt-a", "rt-b", "at-a", "at-b")
    assert not any(s in arg for argv in two.argvs for arg in argv for s in secrets)
    assert not any(s in out.out + out.err for s in secrets)
    assert "* a" in out.out


def test_swap_bumps_generation(two):
    g = ca.swap_generation()
    time.sleep(0.01)
    ca.use("a")
    assert ca.swap_generation() != g


@pytest.mark.parametrize("op", [lambda: ca.use("a"), lambda: ca.save("b")])
def test_ops_block_while_lock_held(two, op):
    done = threading.Event()
    with ca._locked():
        t = threading.Thread(target=lambda: (op(), done.set()))
        t.start()
        assert not done.wait(0.3)
    t.join(5)
    assert done.is_set()


# ── Dashboard wiring ─────────────────────────────────────────────────────────

@pytest.fixture
def app_mod(two):
    import app
    return app


def test_endpoints_need_request_token(app_mod):
    c = app_mod.app.test_client()
    assert c.get("/api/claude-accounts").status_code == 403
    assert c.post("/api/claude-accounts/use", json={"label": "a"}).status_code == 403


def test_endpoints_list_and_use(app_mod, two):
    c = app_mod.app.test_client()
    h = {"X-AgenticOS-Token": app_mod.REQUEST_TOKEN}
    r = c.get("/api/claude-accounts", headers=h)
    assert r.json == {"accounts": [{"label": "a", "email": "uuid-a@x"}, {"label": "b", "email": "uuid-b@x"}],
                      "active": "b"}
    assert "rt-" not in r.text and "at-" not in r.text
    r = c.post("/api/claude-accounts/use", json={"label": "a"}, headers=h)
    assert r.json["ok"] and two.live() == creds("rt-a", "at-a")
    r = c.post("/api/claude-accounts/use", json={"label": "nope"}, headers=h)
    assert r.status_code == 400 and "no saved account" in r.json["error"]


USAGE = {"five_hour": {"utilization": 40}, "seven_day": {"utilization": 60}}


@pytest.fixture
def usage_clock(app_mod, monkeypatch):
    t = [1000.0]
    monkeypatch.setattr(app_mod.time, "monotonic", lambda: t[0])
    monkeypatch.setattr(app_mod, "_claude_usage_cache", (0.0, None))
    monkeypatch.setattr(app_mod, "_claude_usage_retry_at", 0.0)
    monkeypatch.setattr(app_mod, "_claude_usage_gen", ca.swap_generation())
    return t


def test_external_swap_clears_cached_usage(app_mod, usage_clock, monkeypatch):
    calls = []
    monkeypatch.setattr(app_mod, "_fetch_claude_oauth_usage", lambda: calls.append(1) or USAGE)
    assert app_mod._load_claude_oauth_usage()[0] == USAGE
    time.sleep(0.01)
    ca.use("a")  # e.g. from the CLI: only the index mtime tells the dashboard
    app_mod._load_claude_oauth_usage()
    assert len(calls) == 2  # cache dropped although its TTL had not expired


def test_swap_during_fetch_is_not_published(app_mod, usage_clock, monkeypatch):
    def fetch():
        time.sleep(0.01)
        ca.use("a")
        return USAGE
    monkeypatch.setattr(app_mod, "_fetch_claude_oauth_usage", fetch)
    assert app_mod._load_claude_oauth_usage() == ({}, 0.0)
    assert app_mod._claude_usage_cache[1] is None


def test_pre_swap_rate_limit_snapshot_ignored(app_mod, two, tmp_path, monkeypatch):
    snap = tmp_path / "rate-limits-live.json"
    monkeypatch.setattr(app_mod, "CLAUDE_RATE_LIMITS_LIVE", snap)
    snap.write_text(json.dumps({"captured_at": "2000-01-01T00:00:00Z", "rate_limits": {"five_hour": {}}}))
    assert app_mod._claude_live_snapshot() == {}
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 5))
    snap.write_text(json.dumps({"captured_at": now, "rate_limits": {"five_hour": {}}}))
    assert app_mod._claude_live_snapshot()["captured_at"] == now


def test_oversized_secret_refused_without_write(kc):
    with pytest.raises(ca.AccountError, match="too large"):
        ca._kc_write(ca.SNAP_SERVICE, "a", "x" * 2000)
    assert kc.stdins == []


@pytest.mark.parametrize("n, shown", [(1, False), (2, True)])
def test_dashboard_select_needs_two_accounts(app_mod, monkeypatch, n, shown):
    accs = [{"label": "a", "email": "a@x"}, {"label": "b", "email": "b@x"}][:n]
    monkeypatch.setattr(ca, "accounts", lambda: {"accounts": accs, "active": "a"})
    html = app_mod.app.test_client().get("/").text
    assert ('class="claude-account-select"' in html) is shown
    if shown:
        assert '<option value="a" title="a@x" selected>' in html and '<option value="b" title="b@x" >' in html
