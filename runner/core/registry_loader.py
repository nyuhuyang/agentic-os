"""注册表加载工具 — 读取技能注册表 JSON/MD。"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_PROJECT_ROOT: Path | None = None
_VENV_PYTHON: Path | None = None
_MASTER_REGISTRY_JSON: Path | None = None
_CLAUDE_REGISTRY_JSON: Path | None = None
_CLAUDE_REGISTRY_MD: Path | None = None


def set_paths(proto_root: Path, venv_python: Path,
              master_registry_json: Path, claude_registry_json: Path,
              claude_registry_md: Path) -> None:
    """Set paths from app.py during initialization."""
    global _PROJECT_ROOT, _VENV_PYTHON, _MASTER_REGISTRY_JSON, _CLAUDE_REGISTRY_JSON, _CLAUDE_REGISTRY_MD
    _PROJECT_ROOT = proto_root
    _VENV_PYTHON = venv_python
    _MASTER_REGISTRY_JSON = master_registry_json
    _CLAUDE_REGISTRY_JSON = claude_registry_json
    _CLAUDE_REGISTRY_MD = claude_registry_md


def _ensure_paths():
    global _PROJECT_ROOT, _VENV_PYTHON, _MASTER_REGISTRY_JSON, _CLAUDE_REGISTRY_JSON, _CLAUDE_REGISTRY_MD
    if _PROJECT_ROOT is not None:
        return
    import sys as _sys
    _app = _sys.modules.get("app")
    if _app is None:
        _app = _sys.modules.get("__main__")
    if _app is None:
        return
    _PROJECT_ROOT = getattr(_app, "_PROTO", None)
    _VENV_PYTHON = getattr(_app, "VENV_PYTHON", None)
    _MASTER_REGISTRY_JSON = getattr(_app, "MASTER_REGISTRY_JSON", None)
    _CLAUDE_REGISTRY_JSON = getattr(_app, "CLAUDE_REGISTRY_JSON", None)
    _CLAUDE_REGISTRY_MD = getattr(_app, "CLAUDE_REGISTRY_MD", None)


def python_path() -> str:
    _ensure_paths()
    return str(_VENV_PYTHON) if _VENV_PYTHON and _VENV_PYTHON.exists() else sys.executable


def read_registry_json(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        skills = payload.get("skills", {})
        return skills if isinstance(skills, dict) else {}
    except Exception:
        return {}


def registry_md_text(registry: dict[str, dict]) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Skill Registry",
        "",
        f"Generated: {now} · {len(registry)} skills",
        "",
        "| Skill | Stack | Risk | Confirm? | Exec mode | Schedulable | Entrypoint |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for name, entry in sorted(registry.items()):
        sec = entry.get("security", {})
        schedulable = "yes" if entry.get("schedule_eligible") else "—"
        ep = f"`{entry['entrypoint']}`" if entry.get("entrypoint") else "—"
        confirm = "**yes**" if sec.get("confirmation_required") else "—"
        lines.append(
            f"| `{name}` | {entry.get('stack', 'uncategorized')} | "
            f"{sec.get('risk_level', '?')} | {confirm} | "
            f"{entry.get('execution_mode', 'local_only')} | {schedulable} | {ep} |"
        )
    lines += ["", "## Stack summary", "", "| Stack | Skills |", "| --- | --- |"]
    stacks: dict[str, list[str]] = {}
    for name, entry in registry.items():
        stacks.setdefault(entry.get("stack", "uncategorized"), []).append(name)
    for stack, skills in sorted(stacks.items()):
        lines.append(f"| {stack} | {', '.join(f'`{s}`' for s in sorted(skills))} |")
    lines += ["", "## Schedulable skills", ""]
    schedulable = {n: e for n, e in registry.items() if e.get("schedule_eligible")}
    if schedulable:
        for name, entry in sorted(schedulable.items()):
            ep = entry.get("entrypoint") or "no script (AI-only)"
            lines.append(f"- **`{name}`** ({entry.get('execution_mode', 'local_only')}) — {ep}")
    else:
        lines.append("No schedulable skills registered yet.")
    return "\n".join(lines) + "\n"


def filter_registry_for_agent(agent: str | None) -> dict[str, dict]:
    _ensure_paths()
    agent = (agent or "").strip().lower()
    registry = read_registry_json(_MASTER_REGISTRY_JSON)
    if not agent:
        return registry
    return {name: entry for name, entry in registry.items() if agent in (entry.get("agents") or [])}


def ensure_claude_registry() -> dict[str, dict]:
    _ensure_paths()
    registry = filter_registry_for_agent("claude")
    _CLAUDE_REGISTRY_JSON.parent.mkdir(parents=True, exist_ok=True)
    _CLAUDE_REGISTRY_JSON.write_text(
        json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(),
                     "skill_count": len(registry), "skills": registry},
                    indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    _CLAUDE_REGISTRY_MD.write_text(registry_md_text(registry), encoding="utf-8")
    return registry


def load_registry(agent: str | None = None) -> dict[str, dict]:
    _ensure_paths()
    agent = (agent or "").strip().lower()
    if agent == "claude":
        return ensure_claude_registry()
    if agent == "codex":
        return filter_registry_for_agent("codex")
    if agent == "deepseek":
        return filter_registry_for_agent("deepseek")
    return read_registry_json(_MASTER_REGISTRY_JSON)
