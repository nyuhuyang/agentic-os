"""AgenticOS 模块注册表 — 注册、加载、列举模块，能力检测。

所有功能模块继承 `AgenticModule`，通过 `ModuleRegistry` 注册。
模块按需加载：app.py 只导入注册表，模块在 `load_all()` 时才按名导入。

用法:
    from runner.core.module_registry import registry

    class MyModule(AgenticModule):
        name = "mymod"
        label = "My Module"
        required_env = ["MY_API_KEY"]

    registry.register(MyModule())
    registry.load_all()   # 检查各模块能力，加载可用的
    caps = registry.get_capabilities()  # 返回给前端
"""

from __future__ import annotations

import importlib
import inspect
import logging
import os
import pkgutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ── Module base class ──────────────────────────────────────────────────────


class AgenticModule(ABC):
    """所有 AgenticOS 功能模块的基类。

    Subclass 必须设置:
        name   — 唯一模块名（小写字母+数字，如 "linear"、"stt"）
        label  — 人类可读标签（如 "Linear Issues"）

    Subclass 可选的类属性:
        dependencies : list[str] — 依赖的 Python 包名（import 名）
        required_env : list[str] — 必需的环境变量名
        requires     : list[str] — 依赖的其他模块名

    子类可覆盖的方法:
        check_capabilities() — 返回 {"available": bool, "reason": str, ...}
        register_routes()     — 注册 Flask Blueprint 或路由
        register_socketio()   — 注册 SocketIO 事件
        start_background()    — 返回后台 daemon thread 列表
    """

    # ── 必填字段 ──
    name: str = ""
    label: str = ""

    # ── 可选依赖声明 ──
    dependencies: list[str] = []
    required_env: list[str] = []
    requires: list[str] = []

    # ── 运行时状态 ──
    _capability: dict[str, Any] = {"available": False, "reason": "not checked"}

    def check_capabilities(self) -> dict[str, Any]:
        """检测该模块是否可以加载。

        默认检查 required_env 和 dependencies。
        子类应重写此方法以添加自定义检测逻辑。
        """
        failing: list[str] = []

        for env_var in self.required_env:
            val = os.environ.get(env_var, "").strip()
            if not val or val.startswith("$"):
                failing.append(f"env ${env_var} not set")

        for dep in self.dependencies:
            if importlib.util.find_spec(dep) is None:
                failing.append(f"package '{dep}' not installed")

        if failing:
            return {"available": False, "reason": "; ".join(failing)}
        return {"available": True, "reason": ""}

    def register_routes(self, app) -> None:
        """注册 Flask 路由。默认无操作。"""

    def register_socketio(self, socketio) -> None:
        """注册 SocketIO 事件。默认无操作。"""

    def start_background(self, app, socketio) -> list[Any]:
        """启动后台 daemon 线程。返回 thread 列表，默认空。"""
        return []

    def __repr__(self) -> str:
        status = "✓" if self._capability.get("available") else "✗"
        return f"<AgenticModule {self.name} [{status}]>"


# ── Module registry ────────────────────────────────────────────────────────


class ModuleRegistry:
    """模块注册表 — 管理所有 AgenticOS 模块。

    使用单例 `registry` 访问。
    """

    def __init__(self) -> None:
        self._modules: dict[str, AgenticModule] = {}
        self._loaded: set[str] = set()
        self._background_threads: list[Any] = []

    @property
    def modules(self) -> dict[str, AgenticModule]:
        """所有已注册的模块（包括已禁用的）。"""
        return dict(self._modules)

    def register(self, module: AgenticModule) -> None:
        """注册一个模块实例。"""
        if not module.name:
            raise ValueError(f"Module {type(module).__name__} has empty name")
        self._modules[module.name] = module
        logger.debug("Module registered: %s", module.name)

    def get(self, name: str) -> AgenticModule | None:
        """按名称获取模块。"""
        return self._modules.get(name)

    def load_all(self) -> list[str]:
        """对所有已注册模块执行 `check_capabilities()`，返回可用模块名列表。

        可用模块：check_capabilities() 返回 {"available": True}。
        不可用的模块记录原因，但保留在注册表中。
        """
        available: list[str] = []
        for name, module in self._modules.items():
            try:
                result = module.check_capabilities()
                module._capability = result
                if result.get("available"):
                    available.append(name)
                else:
                    reason = result.get("reason", "unknown")
                    logger.info("Module %s disabled: %s", name, reason)
            except Exception as e:
                module._capability = {"available": False, "reason": str(e)}
                logger.warning("Module %s check failed: %s", name, e)
        self._loaded = set(available)
        return list(available)

    def is_available(self, name: str) -> bool:
        """模块是否可用（上次 load_all 结果为 True）。"""
        mod = self._modules.get(name)
        return mod is not None and mod._capability.get("available", False)

    def get_capabilities(self) -> dict[str, Any]:
        """获取所有模块的能力状态，用于 /api/capabilities。

        返回格式:
            {
                "backends": ["claude", "deepseek"],
                "linear": {"available": true, "type": "linear"},
                "stt": {"available": true, "backends": ["browser", "openai"]},
            }
        """
        backend_names: list[str] = []
        result: dict[str, Any] = {
            "modules": {},
            "available": [],
            "disabled": [],
        }
        for name, module in self._modules.items():
            cap = dict(module._capability)  # copy
            cap["label"] = module.label
            result["modules"][name] = cap
            if cap.get("available"):
                result["available"].append(name)
                if "backend" in cap:
                    backend_names.append(name)
            else:
                result["disabled"].append(name)
        result["backends"] = backend_names
        return result

    def init_background(self, app, socketio) -> None:
        """启动所有可用模块的后台线程。"""
        for name in self._loaded:
            module = self._modules[name]
            try:
                threads = module.start_background(app, socketio)
                for t in threads:
                    t.daemon = True
                    t.start()
                    self._background_threads.append(t)
                    logger.debug("Background thread started for %s", name)
            except Exception as e:
                logger.warning("Background init for %s failed: %s", name, e)

    def init_routes(self, app) -> None:
        """注册所有可用模块的 Flask 路由。"""
        for name in self._loaded:
            module = self._modules[name]
            try:
                module.register_routes(app)
                logger.debug("Routes registered for %s", name)
            except Exception as e:
                logger.warning("Route registration for %s failed: %s", name, e)

    def init_socketio(self, socketio) -> None:
        """注册所有可用模块的 SocketIO 事件。"""
        for name in self._loaded:
            module = self._modules[name]
            try:
                module.register_socketio(socketio)
                logger.debug("SocketIO handlers registered for %s", name)
            except Exception as e:
                logger.warning("SocketIO registration for %s failed: %s", name, e)

    def discover(self, paths: list[Path] | None = None) -> list[str]:
        """从指定目录自动发现模块包。

        扫描每个路径下的 __init__.py，寻找定义了 `AgenticModule` 子类
        且包含 `__all__` 或 `module_cls` 的包。

        返回自动发现的模块名列表。
        """
        discovered: list[str] = []
        for path in paths or []:
            if not path.is_dir():
                continue
            for importer, pkg_name, is_pkg in pkgutil.iter_modules([str(path)]):
                if not is_pkg:
                    continue
                try:
                    full_name = f"{path.name}.{pkg_name}"
                    mod = importlib.import_module(full_name)
                    # 查找模块中定义的 AgenticModule 子类
                    for _name, obj in inspect.getmembers(mod):
                        if (isinstance(obj, type) and issubclass(obj, AgenticModule)
                                and obj is not AgenticModule and not inspect.isabstract(obj)):
                            instance = obj()
                            if instance.name not in self._modules:
                                self.register(instance)
                                discovered.append(instance.name)
                except Exception as e:
                    logger.debug("Skipped %s: %s", pkg_name, e)
        return discovered

    def __repr__(self) -> str:
        return (f"<ModuleRegistry {len(self._modules)} registered, "
                f"{len(self._loaded)} loaded>")


# ── Singleton ──────────────────────────────────────────────────────────────

registry = ModuleRegistry()
"""全局模块注册表单例。"""
