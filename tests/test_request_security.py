"""Browser request checks: Socket.IO origin + token, Host allow-list, request token, framing."""

import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runner"))

EVIL = "https://evil.example"
GOOD = "http://127.0.0.1:8510"


@pytest.fixture(scope="module")
def app_mod():
    import app
    import runner.modules.pty as pty_mod
    # Register only the PTY module (socket events + upload routes); no pollers.
    # Flask refuses late route registration once another test module has sent a
    # request through this app, so lift that flag for the registration only.
    if "api_board_upload" not in app.app.view_functions:
        got, app.app._got_first_request = app.app._got_first_request, False
        pty_mod.module.register_routes(app.app)
        app.app._got_first_request = got
        pty_mod.module.register_socketio(app.socketio)
    return app


@pytest.fixture
def no_launch(app_mod, monkeypatch):
    """Any agent launch fails the test."""
    def boom(*a, **k):
        raise AssertionError("an agent process was launched")
    monkeypatch.setattr(app_mod.subprocess, "Popen", boom)
    import runner.modules.pty as pty_mod
    monkeypatch.setattr(pty_mod.pty, "fork", boom)
    return app_mod


def _tok(app_mod):
    return {"X-AgenticOS-Token": app_mod.REQUEST_TOKEN}


# ── Socket.IO ────────────────────────────────────────────────────────────────

def test_socketio_handshake_foreign_origin_refused(no_launch):
    c = no_launch.app.test_client()
    r = c.get("/socket.io/?EIO=4&transport=polling", headers={"Origin": EVIL})
    assert r.status_code == 400


def test_socketio_handshake_own_origin_accepted(app_mod):
    c = app_mod.app.test_client()
    r = c.get("/socket.io/?EIO=4&transport=polling", headers={"Origin": GOOD})
    assert r.status_code == 200 and b'"sid"' in r.data


def test_socketio_connect_with_token_can_open_a_terminal(app_mod, monkeypatch):
    import runner.modules.pty as pty_mod
    opened = []
    monkeypatch.setattr(pty_mod, "open_terminal", lambda data, sio: opened.append(data) or {"term_id": "x"})
    client = app_mod.socketio.test_client(app_mod.app, auth={"token": app_mod.REQUEST_TOKEN})
    assert client.is_connected()
    assert client.emit("term_open", {"kind": "shell"}, callback=True) == {"term_id": "x"} and opened
    client.disconnect()


def test_socketio_connect_without_token_refused(no_launch):
    client = no_launch.socketio.test_client(no_launch.app)
    assert not client.is_connected()


def test_socketio_connect_wrong_token_refused(no_launch):
    client = no_launch.socketio.test_client(no_launch.app, auth={"token": "nope"})
    assert not client.is_connected()


def test_configure_request_security_uses_host_and_port(app_mod):
    try:
        app_mod._configure_request_security("devbox", 9000)
        assert app_mod.app.config["TRUSTED_HOSTS"] == ["127.0.0.1", "localhost", "devbox"]
        assert app_mod.socketio.server.eio.cors_allowed_origins == [
            "http://127.0.0.1:9000", "http://localhost:9000", "http://devbox:9000"]
        assert "*" not in app_mod.socketio.server.eio.cors_allowed_origins
    finally:
        app_mod._configure_request_security("127.0.0.1", 8510)


# ── HTTP ─────────────────────────────────────────────────────────────────────

def test_foreign_host_on_run_gets_400(no_launch):
    r = no_launch.app.test_client().post(
        "/run", json={"prompt": "x"}, headers={"Host": "evil.example:8510", **_tok(no_launch)})
    assert r.status_code == 400


def test_stream_route_is_gone(no_launch):
    before = dict(no_launch._running_jobs)
    r = no_launch.app.test_client().get("/stream?prompt=x", headers=_tok(no_launch))
    assert r.status_code == 404
    assert no_launch._running_jobs == before


def test_run_without_token_403(no_launch):
    r = no_launch.app.test_client().post("/run", json={"prompt": "x"})
    assert r.status_code == 403


def test_run_wrong_token_403(no_launch):
    r = no_launch.app.test_client().post("/run", json={"prompt": "x"}, headers={"X-AgenticOS-Token": "nope"})
    assert r.status_code == 403


def test_run_with_token_passes_guard(no_launch):
    # Empty prompt: the route answers without launching anything, proving the guard let it through.
    r = no_launch.app.test_client().post("/run", json={"prompt": ""}, headers=_tok(no_launch))
    assert r.status_code == 200 and r.get_json() == {"ok": False, "error": "No prompt provided."}


def test_upload_without_token_writes_nothing(app_mod, monkeypatch, tmp_path):
    import runner.modules.pty as pty_mod
    monkeypatch.setattr(pty_mod, "UPLOADS_DIR", tmp_path / "up")
    monkeypatch.setattr(pty_mod, "BOARD_UPLOADS_DIR", tmp_path / "board")
    c = app_mod.app.test_client()
    for path, d in (("/upload", "up"), ("/api/board/upload", "board")):
        r = c.post(path, data={"file": (io.BytesIO(b"x"), "a.txt")}, content_type="multipart/form-data")
        assert r.status_code == 403
        assert not (tmp_path / d).exists()


def test_index_sets_frame_ancestors(app_mod, monkeypatch):
    # The knowledge-base log is TCC-protected from test shells; it is irrelevant here.
    monkeypatch.setattr(app_mod, "load_vault_pulse", lambda *a, **k: [])
    r = app_mod.app.test_client().get("/")
    assert r.status_code == 200
    assert r.headers["Content-Security-Policy"] == "frame-ancestors 'none'"
    assert app_mod.REQUEST_TOKEN.encode() in r.data


def test_attachment_served_without_token_sandboxed(app_mod, monkeypatch, tmp_path):
    import runner.modules.pty as pty_mod
    monkeypatch.setattr(pty_mod, "BOARD_UPLOADS_DIR", tmp_path)
    (tmp_path / "evil.js").write_text("window.SENTINEL = 1;")
    r = app_mod.app.test_client().get("/api/board/uploads/evil.js")
    assert r.status_code == 200
    assert r.headers["Content-Security-Policy"].startswith("sandbox")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["Cross-Origin-Resource-Policy"] == "same-origin"
