"""Tests for runner.modules.backends — Claude/Codex/DeepSeek capability detection."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def clean_env():
    """Remove test artifacts from environment."""
    for key in ["_TEST_DS_KEY_"]:
        os.environ.pop(key, None)
    yield


class TestClaudeModule:
    """ClaudeModule capability detection (path-based)."""

    def test_available_when_claude_found(self):
        """Claude should be available when ~/.claude/ exists and claude CLI is on PATH."""
        from runner.modules.backends.claude import ClaudeModule
        mod = ClaudeModule()

        # Mock both the directory and the executable
        with patch("runner.modules.backends.claude.has_dir", return_value=True):
            with patch("runner.modules.backends.claude.has_executable", return_value=True):
                cap = mod.check_capabilities()
                assert cap["available"] is True
                assert cap["backend"] == "claude"
                assert len(cap["models"]) > 0

    def test_unavailable_without_claude_dir(self):
        from runner.modules.backends.claude import ClaudeModule
        mod = ClaudeModule()

        with patch("runner.modules.backends.claude.has_dir", return_value=False):
            cap = mod.check_capabilities()
            assert cap["available"] is False
            assert "directory" in cap["reason"].lower() or "claude" in cap["reason"].lower()

    def test_unavailable_without_claude_cli(self):
        from runner.modules.backends.claude import ClaudeModule
        mod = ClaudeModule()

        with patch("runner.modules.backends.claude.has_dir", return_value=True):
            with patch("runner.modules.backends.claude.has_executable", return_value=False):
                cap = mod.check_capabilities()
                assert cap["available"] is False


class TestCodexModule:
    """CodexModule capability detection."""

    def test_available_when_codex_found(self):
        from runner.modules.backends.codex import CodexModule
        mod = CodexModule()

        with patch("runner.modules.backends.codex.has_dir", return_value=True):
            with patch("runner.modules.backends.codex.has_executable", return_value=True):
                cap = mod.check_capabilities()
                assert cap["available"] is True
                assert cap["backend"] == "codex"

    def test_unavailable_without_codex_dir(self):
        from runner.modules.backends.codex import CodexModule
        mod = CodexModule()

        with patch("runner.modules.backends.codex.has_dir", return_value=False):
            cap = mod.check_capabilities()
            assert cap["available"] is False

    def test_unavailable_without_codex_cli(self):
        from runner.modules.backends.codex import CodexModule
        mod = CodexModule()

        with patch("runner.modules.backends.codex.has_dir", return_value=True):
            with patch("runner.modules.backends.codex.has_executable", return_value=False):
                cap = mod.check_capabilities()
                assert cap["available"] is False


class TestDeepSeekModule:
    """DeepSeekModule capability detection."""

    def test_available_with_key_and_httpx(self):
        from runner.modules.backends.deepseek import DeepSeekModule
        mod = DeepSeekModule()

        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-test-123"}, clear=False):
            with patch("runner.modules.backends.deepseek.has_env_key", return_value=True):
                with patch("importlib.util.find_spec") as mock_find:
                    mock_find.return_value = True
                    cap = mod.check_capabilities()
                    assert cap["available"] is True
                    assert cap["backend"] == "deepseek"
                    assert "deepseek-v4-flash" in cap["models"]

    def test_unavailable_without_key(self):
        from runner.modules.backends.deepseek import DeepSeekModule
        mod = DeepSeekModule()

        with patch("runner.modules.backends.deepseek.has_env_key", return_value=False):
            cap = mod.check_capabilities()
            assert cap["available"] is False
            assert "API_KEY" in cap["reason"]

    def test_unavailable_without_httpx(self):
        from runner.modules.backends.deepseek import DeepSeekModule
        mod = DeepSeekModule()

        with patch("runner.modules.backends.deepseek.has_env_key", return_value=True):
            import builtins
            original_import = builtins.__import__
            def _mock_import(name, *args, **kwargs):
                if name == "httpx":
                    raise ModuleNotFoundError("httpx not installed")
                return original_import(name, *args, **kwargs)
            with patch("builtins.__import__", _mock_import):
                cap = mod.check_capabilities()
                assert cap["available"] is False
                assert "httpx" in cap["reason"]
