"""Speech-to-Text 语音转文字模块。

支持多个后端:
- browser  — 浏览器 Web Speech API（免费，不需要 API key）
- openai   — OpenAI Whisper API（需要 OPENAI_API_KEY）
- local    — 本地 whisper-cpp 模型（未来，需要 whisper-cpp 可执行文件）

模块名: "stt"
"""

from __future__ import annotations

import json
import logging
import os

from runner.core.module_registry import AgenticModule, registry
from runner.core.features import has_env_key, has_executable, has_package

logger = logging.getLogger(__name__)


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

        # OpenAI Whisper — requires OPENAI_API_KEY + openai package
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
        """Register POST /api/stt for OpenAI backend."""

        @app.route("/api/stt", methods=["POST"])
        def _api_stt():
            """Transcribe audio via OpenAI Audio API (whisper-1)."""
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

            try:
                from openai import OpenAI
                client = OpenAI(api_key=api_key)
                transcript = client.audio.transcriptions.create(
                    model="whisper-1",
                    file=(
                        audio_file.filename or "recording.webm",
                        audio_file.read(),
                        audio_file.content_type or "audio/webm",
                    ),
                    response_format="text",
                )
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


# ── Module registration ────────────────────────────────────────────────────

module = STTModule()
registry.register(module)
