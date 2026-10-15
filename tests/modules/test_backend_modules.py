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
    """DeepSeekModule: monitoring-only; available when dsh + Node >= 22 + key; dispatches as dsh."""

    def _patch(self, monkeypatch, *, bin="/x/dsh", node=25, key="sk-test-123", version="0.2.0-rc.2"):
        from runner.modules.backends import deepseek as mod
        monkeypatch.setattr(mod.dsh_cli, "resolve_bin", lambda: bin)
        monkeypatch.setattr(mod.dsh_cli, "resolve_api_key", lambda: key)
        monkeypatch.setattr(mod, "_node_major", lambda: node)
        def _check(b):
            if version is None:
                raise RuntimeError("dsh 0.1.0 too old")
            return version
        monkeypatch.setattr(mod.dsh_cli, "check_version", _check)
        return mod.DeepSeekModule()

    def test_available_advertises_dsh(self, monkeypatch):
        cap = self._patch(monkeypatch).check_capabilities()
        assert cap["available"] is True and cap["backend"] == "dsh"

    def test_unavailable_without_binary(self, monkeypatch):
        cap = self._patch(monkeypatch, bin=None).check_capabilities()
        assert cap["available"] is False and "dsh" in cap["reason"]

    def test_unavailable_with_old_node(self, monkeypatch):
        cap = self._patch(monkeypatch, node=20).check_capabilities()
        assert cap["available"] is False and "Node" in cap["reason"]

    def test_unavailable_with_old_dsh(self, monkeypatch):
        cap = self._patch(monkeypatch, version=None).check_capabilities()
        assert cap["available"] is False and "too old" in cap["reason"]

    def test_unavailable_without_key(self, monkeypatch):
        cap = self._patch(monkeypatch, key=None).check_capabilities()
        assert cap["available"] is False and "API_KEY" in cap["reason"]
