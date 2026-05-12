"""Agent 后端模块 — 可插拔的 AI 代码代理。

支持的后端:
- claude    (需要 ~/.claude/ 目录 + claude CLI)
- deepseek  (需要 DEEPSEEK_API_KEY 环境变量)
- codex     (需要 ~/.codex/ 存在 + codex CLI)

每个后端是一个独立的 `AgenticModule` 子类。
"""
