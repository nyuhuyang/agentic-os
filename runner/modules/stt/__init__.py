"""Speech-to-Text 语音转文字模块。

支持多个后端:
- browser  — 浏览器 Web Speech API（免费，不需要 API key）
- openai   — OpenAI Whisper API（需要 OPENAI_API_KEY）
- local    — 本地 whisper-cpp 模型（未来，需要 whisper-cpp 可执行文件）

模块名: "stt"
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
import os
import time
import threading
import uuid
from typing import Any

from runner.core.module_registry import AgenticModule, registry
from runner.core.features import has_env_key, has_executable, has_package

logger = logging.getLogger(__name__)

_OPENAI_STT_MODELS = {
    "whisper-1": "whisper-1",
    "gpt-4o-mini-transcribe": "gpt-4o-mini-transcribe",
    "gpt-4o-transcribe": "gpt-4o-transcribe",
}
_DEFAULT_OPENAI_STT_MODEL = os.environ.get("OPENAI_STT_MODEL", "gpt-4o-mini-transcribe")
_REALTIME_TRANSPORT_MODEL = os.environ.get("OPENAI_REALTIME_TRANSPORT_MODEL", "gpt-realtime-mini")
_OPENAI_LANGUAGE_CODES = {
    "zh-cn": "zh",
    "zh-tw": "zh",
    "en-us": "en",
    "en-gb": "en",
    "ja-jp": "ja",
    "ko-kr": "ko",
}


@dataclass
class _RealtimeStreamState:
    sid: str
    stream_id: str
    model: str
    socketio: Any
    conn: Any | None = None
    ready: threading.Event = field(default_factory=threading.Event)
    closed: threading.Event = field(default_factory=threading.Event)
    last_error: str = ""
    audio_chunks_since_commit: int = 0
    last_commit_ts: float = 0.0


_realtime_streams: dict[str, _RealtimeStreamState] = {}
_realtime_stream_lock = threading.Lock()


def _normalize_openai_model(model: str | None) -> str:
    value = (model or _DEFAULT_OPENAI_STT_MODEL).strip()
    return _OPENAI_STT_MODELS.get(value, _DEFAULT_OPENAI_STT_MODEL)


def _normalize_openai_language(language: str | None) -> str | None:
    value = (language or "").strip().lower()
    if not value or value == "auto":
        return None
    return _OPENAI_LANGUAGE_CODES.get(value, value.split("-", 1)[0])


def _emit_stream_event(state: _RealtimeStreamState, event: str, payload: dict[str, Any]) -> None:
    payload = dict(payload)
    payload["stream_id"] = state.stream_id
    state.socketio.emit(event, payload, to=state.sid)


def _close_stream_state(state: _RealtimeStreamState) -> None:
    state.closed.set()
    try:
        if state.conn is not None:
            state.conn.close()
    except Exception:
        pass


def _transcription_session_payload(model: str) -> dict[str, Any]:
    session: dict[str, Any] = {
        "input_audio_format": "pcm16",
        "input_audio_transcription": {"model": model},
        "turn_detection": None,
        "modalities": ["text"],
    }
    return session


def _commit_stream_audio(state: _RealtimeStreamState) -> None:
    if state.conn is None or state.closed.is_set():
        return
    try:
        state.conn.input_audio_buffer.commit()
        state.audio_chunks_since_commit = 0
        state.last_commit_ts = time.time()
    except Exception as e:
        state.last_error = str(e)
        _emit_stream_event(state, "stt_openai_error", {"error": str(e)})


def _openai_realtime_worker(state: _RealtimeStreamState, api_key: str) -> None:
    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        conn = client.beta.realtime.connect(model=_REALTIME_TRANSPORT_MODEL).enter()
        state.conn = conn

        # Send session update to configure transcription
        conn.session.update(session=_transcription_session_payload(state.model))
        state.last_commit_ts = time.time()

        # Listen for events (openai v2 API uses iterator, not .on() handlers)
        for event in conn:
            if state.closed.is_set():
                break

            event_data = {}
            if hasattr(event, "to_dict"):
                event_data = event.to_dict()

            event_type = getattr(event, "type", None) or event_data.get("type", "")

            if event_type == "session.updated":
                if not state.ready.is_set():
                    _emit_stream_event(state, "stt_openai_ready", {
                        "status": "ready",
                        "transport_model": _REALTIME_TRANSPORT_MODEL,
                        "model": state.model,
                    })
                    state.ready.set()

            elif event_type == "conversation.item.input_audio_transcription.delta":
                if state.closed.is_set():
                    continue
                _emit_stream_event(state, "stt_openai_delta", {
                    "delta": event_data.get("delta", "") or "",
                    "item_id": event_data.get("item_id", ""),
                    "content_index": event_data.get("content_index"),
                })

            elif event_type == "conversation.item.input_audio_transcription.completed":
                if state.closed.is_set():
                    continue
                _emit_stream_event(state, "stt_openai_final", {
                    "transcript": event_data.get("transcript", "") or "",
                    "item_id": event_data.get("item_id", ""),
                    "content_index": event_data.get("content_index"),
                })

            elif event_type == "conversation.item.input_audio_transcription.failed":
                if state.closed.is_set():
                    continue
                error_info = event_data.get("error", {}) or {}
                message = error_info.get("message", "") or error_info.get("error", "") or "Transcription failed"
                state.last_error = message
                _emit_stream_event(state, "stt_openai_error", {"error": message})

            elif event_type == "error":
                if state.closed.is_set():
                    continue
                error_info = event_data.get("error", {}) or {}
                message = str(error_info.get("message", "") or error_info.get("error", "") or str(event_data))
                state.last_error = message
                _emit_stream_event(state, "stt_openai_error", {"error": message})

    except Exception as e:
        state.last_error = str(e)
        if not state.ready.is_set():
            state.ready.set()
        if not state.closed.is_set():
            _emit_stream_event(state, "stt_openai_error", {"error": str(e)})
    finally:
        _emit_stream_event(state, "stt_openai_closed", {"status": "closed"})
        state.closed.set()
        with _realtime_stream_lock:
            if _realtime_streams.get(state.sid) is state:
                _realtime_streams.pop(state.sid, None)
        try:
            if state.conn is not None:
                state.conn.close()
        except Exception:
            pass


class STTModule(AgenticModule):
    """Speech-to-Text module with multiple backend support."""

    name = "stt"
    label = "Speech-to-Text"
    dependencies: list[str] = []
    required_env: list[str] = []

    def check_capabilities(self) -> dict:
        """Detect which STT backends are available."""
        available_backends = []

        # Browser STT — always available (client-side Web Speech API)
        available_backends.append("browser")

        # OpenAI transcription — requires OPENAI_API_KEY + openai package
        if has_env_key("OPENAI_API_KEY") and has_package("openai"):
            available_backends.append("openai")

        # WhisperCPP — requires whisper-cpp executable (future)
        if has_executable("whisper-cpp"):
            available_backends.append("local")

        return {
            "available": True,
            "reason": "",
            "backends": available_backends,
        }

    def register_routes(self, app) -> None:
        """Register POST /api/stt for OpenAI transcription backends."""

        @app.route("/api/stt", methods=["POST"])
        def _api_stt():
            """Transcribe audio via OpenAI Audio API using auto language detection."""
            api_key = os.environ.get("OPENAI_API_KEY")
            if not api_key:
                return app.response_class(
                    response=json.dumps({"error": "OPENAI_API_KEY not set in environment"}),
                    status=400,
                    mimetype="application/json",
                )

            from flask import request

            if "audio" not in request.files:
                return app.response_class(
                    response=json.dumps({"error": "No audio file provided"}),
                    status=400,
                    mimetype="application/json",
                )

            audio_file = request.files["audio"]
            model = (request.form.get("model") or _DEFAULT_OPENAI_STT_MODEL).strip()
            model = _OPENAI_STT_MODELS.get(model, _DEFAULT_OPENAI_STT_MODEL)
            language = _normalize_openai_language(request.form.get("language"))

            try:
                from openai import OpenAI
                client = OpenAI(api_key=api_key)
                payload = {
                    "model": model,
                    "file": (
                        audio_file.filename or "recording.webm",
                        audio_file.read(),
                        audio_file.content_type or "audio/webm",
                    ),
                    "response_format": "text",
                }
                if language:
                    payload["language"] = language
                transcript = client.audio.transcriptions.create(**payload)
                return app.response_class(
                    response=json.dumps({"text": transcript}),
                    status=200,
                    mimetype="application/json",
                )
            except Exception as e:
                return app.response_class(
                    response=json.dumps({"error": str(e)}),
                    status=500,
                    mimetype="application/json",
                )

    def register_socketio(self, socketio) -> None:
        """Register realtime OpenAI STT streaming handlers."""

        @socketio.on("stt_openai_start")
        def _stt_openai_start(data):
            from flask import request

            api_key = os.environ.get("OPENAI_API_KEY")
            if not api_key:
                return {"error": "OPENAI_API_KEY not set in environment"}

            payload = data or {}
            model = _normalize_openai_model(payload.get("model"))
            stream_id = (payload.get("stream_id") or uuid.uuid4().hex).strip()

            with _realtime_stream_lock:
                prev = _realtime_streams.get(request.sid)
                if prev is not None:
                    _close_stream_state(prev)
                state = _RealtimeStreamState(
                    sid=request.sid,
                    stream_id=stream_id,
                    model=model,
                    socketio=socketio,
                )
                _realtime_streams[request.sid] = state

            worker = threading.Thread(target=_openai_realtime_worker, args=(state, api_key), daemon=True)
            worker.start()

            if not state.ready.wait(timeout=5.0):
                with _realtime_stream_lock:
                    if _realtime_streams.get(request.sid) is state:
                        _realtime_streams.pop(request.sid, None)
                return {"error": "Timed out starting realtime transcription"}

            if state.last_error:
                return {"error": state.last_error}

            return {
                "ok": True,
                "stream_id": stream_id,
                "model": model,
                "transport_model": _REALTIME_TRANSPORT_MODEL,
            }

        @socketio.on("stt_openai_audio")
        def _stt_openai_audio(data):
            from flask import request

            payload = data or {}
            stream_id = (payload.get("stream_id") or "").strip()
            audio_b64 = (payload.get("audio") or "").strip()
            if not stream_id or not audio_b64:
                return

            state = _realtime_streams.get(request.sid)
            if state is None or state.stream_id != stream_id or state.closed.is_set():
                return
            if state.conn is None:
                return

            try:
                state.conn.input_audio_buffer.append(audio=audio_b64)
                state.audio_chunks_since_commit += 1
                now = time.time()
                if state.audio_chunks_since_commit >= 3 or (
                    state.audio_chunks_since_commit > 0 and (now - state.last_commit_ts) >= 0.5
                ):
                    _commit_stream_audio(state)
            except Exception as e:
                state.last_error = str(e)
                _emit_stream_event(state, "stt_openai_error", {"error": str(e)})

        @socketio.on("stt_openai_stop")
        def _stt_openai_stop(data):
            from flask import request
            import time

            payload = data or {}
            stream_id = (payload.get("stream_id") or "").strip()
            state = _realtime_streams.get(request.sid)
            if state is None or state.stream_id != stream_id:
                return {"ok": True}

            if state.conn is not None and not state.closed.is_set():
                try:
                    _commit_stream_audio(state)
                except Exception:
                    pass
                def _delayed_close():
                    time.sleep(0.75)
                    _close_stream_state(state)

                threading.Thread(target=_delayed_close, daemon=True).start()
            return {"ok": True}

        @socketio.on("disconnect")
        def _stt_openai_disconnect():
            from flask import request

            with _realtime_stream_lock:
                state = _realtime_streams.pop(request.sid, None)
            if state is not None:
                _close_stream_state(state)


# ── Module registration ────────────────────────────────────────────────────

module = STTModule()
registry.register(module)
