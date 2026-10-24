"""Tests for runner.modules.stt — two-pass /api/stt with fake OpenAI clients."""

import asyncio
import io
import time
import types

import pytest
from flask import Flask

import runner.modules.stt as stt


class FakeClient:
    """Async OpenAI stand-in. `behaviour` maps stage -> coroutine fn(kwargs)."""

    calls: list = []
    cancelled: list = []

    def __init__(self, behaviour):
        self.behaviour = behaviour
        self.audio = types.SimpleNamespace(transcriptions=types.SimpleNamespace(create=self._stage("transcribe")))
        self.responses = types.SimpleNamespace(create=self._stage("polish"))

    def _stage(self, name):
        async def create(**kwargs):
            FakeClient.calls.append((name, kwargs))
            try:
                return await self.behaviour[name](kwargs)
            except asyncio.CancelledError:
                FakeClient.cancelled.append(name)
                raise
        return create

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _ok(text, attr="text"):
    async def fn(_kwargs):
        return types.SimpleNamespace(**{attr: text})
    return fn


def _sleep(seconds):
    async def fn(_kwargs):
        await asyncio.sleep(seconds)
    return fn


@pytest.fixture
def client(monkeypatch, tmp_path):
    FakeClient.calls, FakeClient.cancelled = [], []
    behaviour = {"transcribe": _ok("我想用 OpenAI"), "polish": _ok("我想用 OpenAI。", "output_text")}
    monkeypatch.setattr(stt, "_make_client", lambda key: FakeClient(behaviour))
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("STT_GLOSSARY_EXTRA", raising=False)
    app = Flask(__name__)
    stt.STTModule().register_routes(app)
    c = app.test_client()
    c.behaviour = behaviour
    return c


def _post(c, browser_text="我想用 open 4o", language="zh-CN"):
    return c.post("/api/stt", data={
        "audio": (io.BytesIO(b"fake-audio"), "rec.webm", "audio/webm"),
        "browser_text": browser_text, "language": language,
    }, content_type="multipart/form-data")


def test_happy_path_returns_polished_and_raw(client):
    r = _post(client)
    assert r.status_code == 200
    body = r.get_json()
    assert (body["text"], body["raw"], body["polished"]) == ("我想用 OpenAI。", "我想用 OpenAI", True)
    assert FakeClient.calls[1][1]["reasoning"] == {"effort": "none"}


def test_transcription_request_shape(client):
    _post(client, browser_text="x" * 5000)
    name, kw = FakeClient.calls[0]
    assert name == "transcribe"
    assert kw["model"] == stt.STT_MODEL and kw["response_format"] == "json"
    assert "language" not in kw
    assert kw["extra_body"]["languages"] == ["zh"]
    assert "OpenAI" in kw["extra_body"]["keywords"]
    assert kw["prompt"] == "x" * stt.PROMPT_MAX_CHARS


def test_polish_timeout_returns_raw_quickly_and_cancels(client, monkeypatch):
    monkeypatch.setattr(stt, "POLISH_TIMEOUT_S", 0.3)
    client.behaviour["polish"] = _sleep(20)
    t = time.monotonic()
    body = _post(client).get_json()
    assert time.monotonic() - t < 1.3
    assert body["text"] == body["raw"] == "我想用 OpenAI" and body["polished"] is False
    assert FakeClient.cancelled == ["polish"]


def test_polish_error_returns_raw(client):
    async def boom(_kwargs):
        raise RuntimeError("model down")
    client.behaviour["polish"] = boom
    body = _post(client).get_json()
    assert body["polished"] is False and body["text"] == "我想用 OpenAI"


def test_transcription_timeout_is_504_and_cancelled(client, monkeypatch):
    monkeypatch.setattr(stt, "TRANSCRIBE_TIMEOUT_S", 0.3)
    client.behaviour["transcribe"] = _sleep(60)
    t = time.monotonic()
    r = _post(client)
    assert r.status_code == 504 and time.monotonic() - t < 1.3
    assert FakeClient.cancelled == ["transcribe"]


def test_transcription_error_is_502(client):
    async def boom(_kwargs):
        raise RuntimeError("bad audio")
    client.behaviour["transcribe"] = boom
    r = _post(client)
    assert r.status_code == 502 and "bad audio" in r.get_json()["error"]


def test_recovers_after_consecutive_timeouts(client, monkeypatch):
    monkeypatch.setattr(stt, "TRANSCRIBE_TIMEOUT_S", 0.2)
    client.behaviour["transcribe"] = _sleep(30)
    assert _post(client).status_code == 504
    assert _post(client).status_code == 504
    client.behaviour["transcribe"] = _ok("ok")
    assert _post(client).get_json()["raw"] == "ok"


def test_blocking_executor_work_does_not_hold_response(client, monkeypatch):
    """Stands in for an uncancellable getaddrinfo thread: loop.close() must not join it."""
    monkeypatch.setattr(stt, "POLISH_TIMEOUT_S", 0.3)

    async def blocking(_kwargs):
        await asyncio.get_running_loop().run_in_executor(None, time.sleep, 2)
    client.behaviour["polish"] = blocking
    t = time.monotonic()
    body = _post(client).get_json()
    assert time.monotonic() - t < 1.3 and body["polished"] is False


def test_missing_key_is_400(client, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY")
    assert _post(client).status_code == 400


def test_glossary_validation_and_bad_extras(tmp_path, monkeypatch, caplog):
    extra = tmp_path / "extra.txt"
    extra.write_text("ProjectX\n<bad>\n" + "y" * 100 + "\nopenai\n", encoding="utf-8")
    kws = stt.load_glossary(str(extra))
    assert "ProjectX" in kws and "<bad>" not in kws and "y" * 100 not in kws
    assert sum(k.casefold() == "openai" for k in kws) == 1  # deduped against generic list
    assert "OpenAI" in stt.load_glossary(str(tmp_path / "missing.txt"))  # missing extras: warning only
    bad = tmp_path / "bad.bin"
    bad.write_bytes(b"\xff\xfe\x00bad")
    assert "OpenAI" in stt.load_glossary(str(bad))  # undecodable extras: warning only


def test_id_alias_persisted_and_served(tmp_path, monkeypatch):
    import runner.modules.linear as lin
    monkeypatch.setattr(lin, "ID_ALIASES_PATH", tmp_path / "out" / "id_aliases.json")
    lin.record_id_alias("local-1", "uuid-1")
    lin.record_id_alias("local-2", "uuid-2")
    assert lin.load_id_aliases() == {"local-1": "uuid-1", "local-2": "uuid-2"}
    app = Flask(__name__)
    lin.LinearModule()._register_linear_routes(app)
    assert app.test_client().get("/api/linear/id-aliases").get_json() == {"local-1": "uuid-1", "local-2": "uuid-2"}


def test_live_text_is_polished_without_transcription(client):
    body = client.post("/api/stt", data={"text": "我想用 OpenAI", "language": "zh-CN"}).get_json()
    assert [name for name, _ in FakeClient.calls] == ["polish"]
    assert (body["text"], body["raw"], body["polished"], body["model"]) == (
        "我想用 OpenAI。", "我想用 OpenAI", True, stt.LIVE_MODEL)


def test_live_token_mints_transcription_session(client, monkeypatch):
    seen = {}

    def fake_mint(api_key, session):
        seen.update(key=api_key, session=session)
        return "ek_test"
    monkeypatch.setattr(stt, "mint_live_secret", fake_mint)
    body = client.post("/api/stt/live-token", json={"language": "zh-CN"}).get_json()
    assert body["value"] == "ek_test" and seen["key"] == "test-key"
    inp = seen["session"]["audio"]["input"]
    assert seen["session"]["type"] == "transcription" and inp["turn_detection"] is None
    assert inp["transcription"]["model"] == stt.LIVE_MODEL and inp["transcription"]["languages"] == ["zh"]
    assert "OpenAI" in inp["transcription"]["keywords"]


def test_live_token_error_is_502(client, monkeypatch):
    def boom(*_a):
        raise OSError("offline")
    monkeypatch.setattr(stt, "mint_live_secret", boom)
    r = client.post("/api/stt/live-token", json={})
    assert r.status_code == 502 and "offline" in r.get_json()["error"]
