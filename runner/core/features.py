"""Feature detection utilities for module capabilities.

Provides helpers to check environment variables, installed packages, and
available executables — used by each module's `check_capabilities()` to
decide whether it can load.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
from pathlib import Path


def has_env(name: str) -> bool:
    """Check if an environment variable is set and non-empty."""
    val = os.environ.get(name, "")
    return bool(val and val.strip())


def has_env_key(env_var: str) -> bool:
    """Check if an env var looks like an API key (non-empty, not a placeholder).

    Treats values starting with '$' as unresolved variable references.
    """
    val = os.environ.get(env_var, "").strip()
    if not val:
        return False
    if val.startswith("$"):
        return bool(val[1:]) and has_env(val[1:])
    # Skip common placeholder patterns
    placeholders = ("your-", "sk-your", "placeholder", "xxx")
    return not val.lower().startswith(placeholders)


def has_package(name: str) -> bool:
    """Check if a Python package is importable."""
    try:
        return importlib.util.find_spec(name) is not None
    except ModuleNotFoundError:
        return False


def has_executable(name: str) -> bool:
    """Check if an executable is on PATH."""
    return shutil.which(name) is not None


def has_dir(path: str | Path) -> bool:
    """Check if a directory exists."""
    return Path(path).expanduser().resolve().is_dir()


def has_file(path: str | Path) -> bool:
    """Check if a file exists."""
    return Path(path).expanduser().resolve().is_file()


def check_all(checks: dict[str, callable]) -> tuple[bool, list[str]]:
    """Run a dict of named checks, return (all_ok, reasons).

    Example:
        ok, reasons = check_all({
            "DEEPSEEK_API_KEY env": lambda: has_env("DEEPSEEK_API_KEY"),
            "openai package": lambda: has_package("openai"),
        })
    """
    reasons: list[str] = []
    for name, fn in checks.items():
        try:
            if not fn():
                reasons.append(f"missing: {name}")
        except Exception as e:
            reasons.append(f"error checking {name}: {e}")
    return (len(reasons) == 0, reasons)
