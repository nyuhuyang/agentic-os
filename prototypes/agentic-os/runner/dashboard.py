#!/usr/bin/env python3
"""Agentic OS — command center dashboard.

Displays skill registry state, recent run history, and quick-run commands.

Usage:
    .venv/bin/python3 .codex/runner/dashboard.py
    .venv/bin/python3 .codex/runner/dashboard.py --watch          # refresh every 10s
    .venv/bin/python3 .codex/runner/dashboard.py --watch 30       # refresh every 30s
    .venv/bin/python3 .codex/runner/dashboard.py --runs 20        # show last 20 runs
    .venv/bin/python3 .codex/runner/dashboard.py --skill <name>   # detail view for one skill
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    from rich.columns import Columns
    from rich.console import Console
    from rich.live import Live
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    from rich import box
except ImportError as exc:
    raise SystemExit("rich is required. Run with .venv/bin/python3") from exc

ROOT = Path.cwd()
WORKSPACE_ROOT = ROOT.parent.parent
REGISTRY_JSON = WORKSPACE_ROOT / ".codex" / "registry.json"
OUTPUTS_DIR = ROOT / "outputs"
RUN_LOG = OUTPUTS_DIR / "run_log.jsonl"
JOB_STATE = OUTPUTS_DIR / "job_state.json"

RUNNER_CMD = ".venv/bin/python3 .codex/runner/run_skill.py"

STATUS_STYLE = {
    "success": "green",
    "failed": "red",
    "error": "red bold",
    "running": "yellow",
}


def _load_registry() -> dict:
    if not REGISTRY_JSON.exists():
        return {}
    return json.loads(REGISTRY_JSON.read_text(encoding="utf-8")).get("skills", {})


def _load_state() -> dict:
    if not JOB_STATE.exists():
        return {}
    try:
        return json.loads(JOB_STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_runs(limit: int) -> list[dict]:
    if not RUN_LOG.exists():
        return []
    lines = RUN_LOG.read_text(encoding="utf-8").strip().splitlines()
    records = []
    for line in reversed(lines):
        try:
            records.append(json.loads(line))
        except Exception:
            continue
        if len(records) >= limit:
            break
    return records


def _fmt_dt(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso)
        now = datetime.now(timezone.utc)
        diff = now - dt
        secs = int(diff.total_seconds())
        if secs < 60:
            return f"{secs}s ago"
        if secs < 3600:
            return f"{secs // 60}m ago"
        if secs < 86400:
            return f"{secs // 3600}h ago"
        return f"{secs // 86400}d ago"
    except Exception:
        return iso[:16] if len(iso) >= 16 else iso


def _fmt_dur(dur: float | None) -> str:
    if dur is None:
        return "—"
    if dur < 1:
        return f"{int(dur * 1000)}ms"
    return f"{dur:.1f}s"


def build_skills_table(registry: dict, state: dict) -> Table:
    table = Table(
        title="Skills",
        box=box.SIMPLE_HEAD,
        show_footer=False,
        expand=True,
    )
    table.add_column("Skill", style="cyan", no_wrap=True, min_width=22)
    table.add_column("Stack", style="dim", min_width=9)
    table.add_column("Mode", style="dim", min_width=10)
    table.add_column("Sched", justify="center", width=5)
    table.add_column("Last status", justify="center", min_width=10)
    table.add_column("Last run", justify="right", min_width=9)
    table.add_column("Dur", justify="right", min_width=6)

    for name, entry in sorted(registry.items()):
        s = state.get(name, {})
        status = s.get("status", "—")
        style = STATUS_STYLE.get(status, "dim")
        status_cell = Text(status, style=style) if status != "—" else Text("—", style="dim")

        sched = "✓" if entry.get("schedule_eligible") else "—"
        sched_style = "green" if entry.get("schedule_eligible") else "dim"

        table.add_row(
            name,
            entry.get("stack", "?"),
            entry.get("execution_mode", "?"),
            Text(sched, style=sched_style),
            status_cell,
            _fmt_dt(s.get("last_run")),
            _fmt_dur(s.get("duration_s")),
        )

    return table


def build_runs_table(runs: list[dict]) -> Table:
    table = Table(
        title=f"Recent runs (last {len(runs)})",
        box=box.SIMPLE_HEAD,
        expand=True,
    )
    table.add_column("Skill", style="cyan", no_wrap=True)
    table.add_column("Status", justify="center")
    table.add_column("Exit", justify="center", style="dim")
    table.add_column("Duration", justify="right")
    table.add_column("When", justify="right")
    table.add_column("Args", style="dim", overflow="fold")

    for run in runs:
        status = run.get("status", "?")
        style = STATUS_STYLE.get(status, "dim")
        args = " ".join(run.get("args", [])) or "—"
        table.add_row(
            run.get("skill", "?"),
            Text(status, style=style),
            str(run.get("exit_code", "?")),
            _fmt_dur(run.get("duration_s")),
            _fmt_dt(run.get("started_at")),
            args,
        )

    return table


def build_commands_panel(registry: dict) -> Panel:
    schedulable = {n: e for n, e in registry.items() if e.get("schedule_eligible") and e.get("entrypoint")}
    if not schedulable:
        return Panel("No schedulable skills with entrypoints.", title="Quick run")

    lines: list[Text] = []
    for name, entry in sorted(schedulable.items()):
        line = Text()
        line.append(f"  {name:<22}", style="cyan bold")
        line.append("run_skill.py ", style="dim")
        line.append(name, style="white")
        lines.append(line)

    content = Text("\n").join(lines)
    return Panel(content, title="Quick run  (prefix: .venv/bin/python3 .codex/runner/)", border_style="dim")


def build_header(registry: dict, state: dict) -> Panel:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    total = len(registry)
    schedulable = sum(1 for e in registry.values() if e.get("schedule_eligible"))
    ran = len(state)
    errors = sum(1 for s in state.values() if s.get("status") in ("failed", "error"))

    parts = [
        Text.assemble(("AI Workspace", "bold white"), "  ·  ", (now, "dim")),
        Text.assemble(
            (str(total), "cyan"), " skills  ",
            (str(schedulable), "green"), " schedulable  ",
            (str(ran), "white"), " ever run  ",
            (str(errors), "red" if errors else "dim"), " errors",
        ),
    ]
    content = Text("\n").join(parts)
    return Panel(content, border_style="blue")


def render(runs_limit: int) -> None:
    console = Console()
    registry = _load_registry()
    state = _load_state()
    runs = _load_runs(runs_limit)

    console.print(build_header(registry, state))
    console.print()
    console.print(build_skills_table(registry, state))
    console.print()

    if runs:
        console.print(build_runs_table(runs))
        console.print()

    console.print(build_commands_panel(registry))


def render_skill_detail(name: str) -> None:
    console = Console()
    registry = _load_registry()
    state = _load_state()

    if name not in registry:
        console.print(f"[red]Unknown skill: {name}[/red]")
        console.print(f"Known: {', '.join(sorted(registry))}")
        return

    entry = registry[name]
    info = state.get(name, {})

    table = Table(box=box.SIMPLE, show_header=False, expand=False)
    table.add_column("Field", style="dim", width=18)
    table.add_column("Value")

    table.add_row("name", Text(name, style="cyan bold"))
    table.add_row("stack", entry.get("stack", "?"))
    table.add_row("exec mode", entry.get("execution_mode", "?"))
    table.add_row("schedulable", "yes" if entry.get("schedule_eligible") else "no")
    table.add_row("entrypoint", entry.get("entrypoint") or "— (AI-only)")
    table.add_row("purpose", entry.get("purpose", "?")[:80])
    table.add_row("", "")
    table.add_row("last status", Text(info.get("status", "never run"), style=STATUS_STYLE.get(info.get("status", ""), "dim")))
    table.add_row("last run", _fmt_dt(info.get("last_run")))
    table.add_row("duration", _fmt_dur(info.get("duration_s")))
    if info.get("error"):
        table.add_row("error", Text(info["error"], style="red"))

    deps = entry.get("dependencies", {})
    if deps.get("external_services"):
        table.add_row("", "")
        table.add_row("external", ", ".join(deps["external_services"]))

    triggers = entry.get("trigger_phrases", [])
    if triggers:
        table.add_row("triggers", " · ".join(triggers[:3]))

    console.print(Panel(table, title=f"Skill: {name}", border_style="blue"))

    # show recent runs for this skill
    all_runs = _load_runs(100)
    skill_runs = [r for r in all_runs if r.get("skill") == name][:5]
    if skill_runs:
        console.print(build_runs_table(skill_runs))


def main() -> int:
    parser = argparse.ArgumentParser(description="Agentic OS command center.")
    parser.add_argument("--watch", nargs="?", const=10, type=int, metavar="SECONDS",
                        help="Refresh every N seconds (default 10).")
    parser.add_argument("--runs", type=int, default=10, metavar="N",
                        help="Number of recent runs to show (default 10).")
    parser.add_argument("--skill", metavar="NAME",
                        help="Show detail view for one skill.")
    args = parser.parse_args()

    if args.skill:
        render_skill_detail(args.skill)
        return 0

    if args.watch is not None:
        console = Console()
        with Live(console=console, refresh_per_second=1, screen=True) as live:
            while True:
                registry = _load_registry()
                state = _load_state()
                runs = _load_runs(args.runs)

                from rich.console import Group
                live.update(Group(
                    build_header(registry, state),
                    build_skills_table(registry, state),
                    build_runs_table(runs) if runs else Text(""),
                    build_commands_panel(registry),
                ))
                time.sleep(args.watch)
    else:
        render(args.runs)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
