"""Tests for runner.core.module_registry — AgenticModule base + ModuleRegistry."""

import pytest

from runner.core.module_registry import AgenticModule, ModuleRegistry, registry


class TestAgenticModule:
    """AgenticModule base class contract."""

    def test_subclass_without_name_raises(self):
        """AgenticModule with empty name should raise on registration."""
        from runner.core.module_registry import ModuleRegistry
        reg = ModuleRegistry()

        class Mod(AgenticModule):
            name = ""
            label = "Bad"

        with pytest.raises(ValueError, match="empty name"):
            reg.register(Mod())

    def test_default_capability_checks_env(self):
        """check_capabilities should detect missing env vars."""
        class TestMod(AgenticModule):
            name = "test_mod"
            label = "Test Module"
            required_env = ["_NONEXISTENT_ENV_XYZ_"]

        mod = TestMod()
        cap = mod.check_capabilities()
        assert cap["available"] is False
        assert "_NONEXISTENT_ENV_XYZ_" in cap["reason"]

    def test_check_capabilities_pass_when_env_set(self):
        """check_capabilities should pass when all required env is present."""
        import os
        os.environ["_TEST_REQUIRED_ENV_"] = "1"
        try:
            class TestMod(AgenticModule):
                name = "test_mod2"
                label = "Test Module"
                required_env = ["_TEST_REQUIRED_ENV_"]

            mod = TestMod()
            cap = mod.check_capabilities()
            assert cap["available"] is True
        finally:
            os.environ.pop("_TEST_REQUIRED_ENV_", None)


class TestModuleRegistry:
    """ModuleRegistry registration and capability checking."""

    def setup_method(self):
        """Create fresh registry for each test."""
        self.reg = ModuleRegistry()

    def test_register_and_get(self):
        class Mod(AgenticModule):
            name = "simple"
            label = "Simple"
        m = Mod()
        self.reg.register(m)
        assert self.reg.get("simple") is m

    def test_register_duplicate_name(self):
        class Mod(AgenticModule):
            name = "dup"
            label = "Dup"
        self.reg.register(Mod())
        self.reg.register(Mod())  # overwrites silently

    def test_get_nonexistent(self):
        assert self.reg.get("nonexistent") is None

    def test_load_all_returns_available(self):
        class Mod(AgenticModule):
            name = "good"
            label = "Good"
        self.reg.register(Mod())
        avail = self.reg.load_all()
        assert "good" in avail

    def test_load_all_marks_disabled(self):
        class Mod(AgenticModule):
            name = "bad"
            label = "Bad"
            required_env = ["_NONEXISTENT_ENV_XYZ_"]

        self.reg.register(Mod())
        avail = self.reg.load_all()
        assert "bad" not in avail
        assert self.reg.is_available("bad") is False

    def test_get_capabilities_structure(self):
        class ClaudeMod(AgenticModule):
            name = "claude"
            label = "Claude"
            def check_capabilities(self):
                return {"available": True, "backend": "claude"}

        class MissingMod(AgenticModule):
            name = "missing"
            label = "Missing"
            required_env = ["_NONEXISTENT_ENV_XYZ_"]

        self.reg.register(ClaudeMod())
        self.reg.register(MissingMod())
        self.reg.load_all()

        caps = self.reg.get_capabilities()
        assert "backends" in caps
        assert "claude" in caps["backends"]
        assert "missing" not in caps["backends"]  # only available backends
        assert "claude" in caps["modules"]
        assert "missing" in caps["modules"]
        assert caps["modules"]["missing"]["available"] is False

    def test_default_check_capabilities(self):
        """A module with no requirements should be available."""
        class Mod(AgenticModule):
            name = "plain"
            label = "Plain"

        self.reg.register(Mod())
        cap = self.reg.get("plain").check_capabilities()
        assert cap["available"] is True


class TestSingletonRegistry:
    """The global `registry` singleton should work as expected."""

    def test_singleton_is_registry(self):
        assert isinstance(registry, ModuleRegistry)

    def test_singleton_persists(self):
        """Modules registered via singleton are visible across imports."""
        # Registry is already used at module import time
        assert hasattr(registry, "_modules")
