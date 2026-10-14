"""Speech-to-Text 语音转文字模块。

支持多个后端:
- browser — 浏览器 Web Speech API（免费，实时预览，不需要 API key）
- openai  — POST /api/stt 两步整理：gpt-transcribe 重新转写录音，再由小文本模型润色
            （需要 OPENAI_API_KEY；见 docs/exec-plans/active/2026-10-14-stt-two-pass.md）
- local   — 本地 whisper-cpp 模型（未来，需要 whisper-cpp 可执行文件）

模块名: "stt"
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

from runner.core.module_registry import AgenticModule, registry
from runner.core.features import has_env_key, has_executable, has_package

logger = logging.getLogger(__name__)

STT_MODEL = os.environ.get("OPENAI_STT_MODEL", "gpt-transcribe")
POLISH_MODEL = os.environ.get("OPENAI_STT_POLISH_MODEL", "gpt-6-luna")
# Total per-stage deadlines (HTTPX timeouts are per phase/read, so they are not enough).
TRANSCRIBE_TIMEOUT_S = 30.0
POLISH_TIMEOUT_S = 8.0
# Self-imposed caps: the guide documents no max for keyword length/count or gpt-transcribe prompt length.
PROMPT_MAX_CHARS = 1000
KEYWORD_MAX_LEN = 64
KEYWORD_MAX_COUNT = 100
GLOSSARY_PATH = Path(__file__).with_name("glossary.txt")

_LANGUAGE_CODES = {"zh-cn": "zh", "zh-tw": "zh", "en-us": "en", "en-gb": "en", "ja-jp": "ja", "ko-kr": "ko"}

POLISH_INSTRUCTIONS = (
    "You clean up a speech-to-text transcript that a user dictated as instructions or notes.\n"
    "- Fix recognition errors. Use the glossary and the browser transcript (a second, less accurate witness) as evidence.\n"
    "- Remove filler words such as 那个, 就是, 嗯, um.\n"
    "- Fix punctuation.\n"
    "- Keep the meaning, the Chinese/English mix, and every instruction intact.\n"
    "- Do not summarize, translate, answer, or add content.\n"
    "Return only the cleaned text."
)


def _make_client(api_key: str):
    from openai import AsyncOpenAI

    return AsyncOpenAI(api_key=api_key, max_retries=0)


def _normalize_language(language: str | None) -> str | None:
    value = (language or "").strip().lower()
    if not value or value == "auto":
        return None
    return _LANGUAGE_CODES.get(value, value.split("-", 1)[0])


def load_glossary(extra_path: str | None = None) -> list[str]:
    """Generic glossary + optional private extras (STT_GLOSSARY_EXTRA). Bad entries/files only warn."""
    extra = extra_path if extra_path is not None else os.environ.get("STT_GLOSSARY_EXTRA", "")
    paths = [GLOSSARY_PATH] + ([Path(extra).expanduser()] if extra else [])
    keywords: list[str] = []
    seen: set[str] = set()
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            logger.warning("STT glossary %s unreadable: %s", path, e)
            continue
        for line in text.splitlines():
            kw = line.strip()
            if not kw or kw.startswith("#"):
                continue
            # The API rejects the whole request on '<', '>', CR or LF (splitlines already removed CR/LF).
            if "<" in kw or ">" in kw or len(kw) > KEYWORD_MAX_LEN:
                logger.warning("STT glossary entry dropped: %r", kw)
                continue
            if kw.casefold() not in seen:
                seen.add(kw.casefold())
                keywords.append(kw)
    return keywords[:KEYWORD_MAX_COUNT]


def run_with_deadline(make_coro, timeout: float):
    """Run one coroutine with a real total deadline; cancellation aborts the in-flight request.

    Deliberately not asyncio.run(): its teardown joins the default executor, which can block on an
    uncancellable getaddrinfo thread. loop.close() shuts the executor down with wait=False.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(asyncio.wait_for(make_coro(), timeout))
    finally:
        loop.close()


async def transcribe(api_key: str, audio: tuple, prompt: str, keywords: list[str], language: str | None) -> str:
    extra: dict = {}
    if keywords:
        extra["keywords"] = keywords
    if language:
        extra["languages"] = [language]  # replaces singular `language`; never send both
    kwargs: dict = {"model": STT_MODEL, "file": audio, "response_format": "json"}
    if prompt:
        kwargs["prompt"] = prompt
    if extra:
        kwargs["extra_body"] = extra
    async with _make_client(api_key) as client:
        result = await client.audio.transcriptions.create(**kwargs)
    return (result.text or "").strip()


async def polish(api_key: str, raw: str, browser_text: str, keywords: list[str]) -> str:
    parts = []
    if keywords:
        parts.append("Glossary: " + ", ".join(keywords))
    if browser_text:
        parts.append("Browser transcript (second witness, may be wrong):\n" + browser_text)
    parts.append("Transcript to clean:\n" + raw)
    async with _make_client(api_key) as client:
        result = await client.responses.create(
            model=POLISH_MODEL,
            reasoning={"effort": "none"},
            instructions=POLISH_INSTRUCTIONS,
            input="\n\n".join(parts),
        )
    return (result.output_text or "").strip()


class STTModule(AgenticModule):
    """Speech-to-Text module with multiple backend support."""

    name = "stt"
    label = "Speech-to-Text"
    dependencies: list[str] = []
    required_env: list[str] = []

    def check_capabilities(self) -> dict:
        """Detect which STT backends are available."""
        available_backends = ["browser"]  # client-side Web Speech API
        # Two-pass refinement — requires OPENAI_API_KEY + openai package
        if has_env_key("OPENAI_API_KEY") and has_package("openai"):
            available_backends.append("openai")
        if has_executable("whisper-cpp"):
            available_backends.append("local")
        return {"available": True, "reason": "", "backends": available_backends}

    def register_routes(self, app) -> None:
        """Register POST /api/stt: transcribe the recording, then polish it."""

        def _json(payload: dict, status: int = 200):
            return app.response_class(response=json.dumps(payload), status=status, mimetype="application/json")

        @app.route("/api/stt", methods=["POST"])
        def _api_stt():
            from flask import request

            api_key = os.environ.get("OPENAI_API_KEY")
            if not api_key:
                return _json({"error": "OPENAI_API_KEY not set in environment"}, 400)
            if "audio" not in request.files:
                return _json({"error": "No audio file provided"}, 400)

            upload = request.files["audio"]
            audio = (upload.filename or "recording.webm", upload.read(), upload.content_type or "audio/webm")
            browser_text = (request.form.get("browser_text") or "").strip()[:PROMPT_MAX_CHARS]
            language = _normalize_language(request.form.get("language"))
            keywords = load_glossary()

            try:
                raw = run_with_deadline(
                    lambda: transcribe(api_key, audio, browser_text, keywords, language), TRANSCRIBE_TIMEOUT_S)
            except TimeoutError:
                return _json({"error": "transcription timed out"}, 504)
            except Exception as e:
                return _json({"error": str(e)}, 502)

            text, polished = raw, False
            if raw:
                try:
                    cleaned = run_with_deadline(lambda: polish(api_key, raw, browser_text, keywords), POLISH_TIMEOUT_S)
                    if cleaned:
                        text, polished = cleaned, True
                except Exception as e:  # timeout or API error ⇒ fall back to the raw transcript
                    logger.warning("STT polish skipped: %s", e or type(e).__name__)
            return _json({"text": text, "raw": raw, "polished": polished,
                          "model": STT_MODEL, "polish_model": POLISH_MODEL if polished else None})


# ── Module registration ────────────────────────────────────────────────────

module = STTModule()
registry.register(module)
