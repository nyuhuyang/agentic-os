"""Speech-to-Text 语音转文字模块。

支持多个后端:
- browser  — 浏览器 Web Speech API（免费，不需要 API key）
- openai   — OpenAI Whisper API（需要 OPENAI_API_KEY）
- local    — 本地 whisper-cpp 模型（需要 whisper-cpp 可执行文件）

模块名: "stt"
"""
