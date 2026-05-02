#!/usr/bin/env python3
"""Job runner for schedulable skills.

Wraps execution of a skill's entrypoint script with structured logging,
state tracking, and optional retry.

Usage:
    .venv/bin/python3 .codex/runner/run_skill.py <skill> [-- <args...>]
    .venv/bin/python3 .codex/runner/run_skill.py yt-pipeline -- --query "RAG" --goal "survey"
    .venv/bin/python3 .codex/runner/run_skill.py llm-wiki-lint
    .venv/bin/python3 .codex/runner/run_skill.py --list
    .venv/bin/python3 .codex/runner/run_skill.py --status

Logs:
    outputs/run_log.jsonl    append-only run record per execution
    outputs/job_state.json   last known state per skill (overwritten each run)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import IO

try:
    import fcntl
    _HAVE_FCNTL = True
except ImportError:
    _HAVE_FCNTL = False  # Windows fallback: locking skipped

ROOT = Path.cwd()
# Registry lives at workspace root (AI_Workspace/.codex/), not inside knowledge_base.
WORKSPACE_ROOT = ROOT.parent.parent
REGISTRY_JSON = WORKSPACE_ROOT / ".codex" / "registry.json"
OUTPUTS_DIR = ROOT / "outputs"
RUN_LOG = OUTPUTS_DIR / "run_log.jsonl"
JOB_STATE = OUTPUTS_DIR / "job_state.json"
LOCKS_DIR = OUTPUTS_DIR / "locks"

VENV_PYTHON = ROOT / ".venv" / "bin" / "python3"


def _python() -> str:
    return str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_registry() -> dict:
    if not REGISTRY_JSON.exists():
        raise SystemExit(
            f"Registry not found at {REGISTRY_JSON}.\n"
            "Run: .venv/bin/python3 .codex/skills/skill-registry/scripts/build_registry.py"
        )
    payload = json.loads(REGISTRY_JSON.read_text(encoding="utf-8"))
    return payload.get("skills", {})


def _acquire_lock(skill: str) -> "IO | None":
    """Acquire exclusive per-skill lock. Returns open file handle if acquired, None if busy.

    Uses fcntl.flock (POSIX) so the lock is automatically released on process exit.
    Lock file lives in outputs/locks/<skill>.lock and contains the holder's PID.
    """
    if not _HAVE_FCNTL:
        return None  # no locking on non-POSIX; caller treats None as "acquired"
    LOCKS_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = LOCKS_DIR / f"{skill}.lock"
    fh: IO = lock_path.open("w", encoding="utf-8")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fh.write(str(os.getpid()))
        fh.flush()
        return fh
    except OSError:
        fh.close()
        return None


def _append_log(record: dict) -> None:
    OUTPUTS_DIR.mkdir(exist_ok=True)
    with RUN_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _update_state(skill: str, record: dict) -> None:
    OUTPUTS_DIR.mkdir(exist_ok=True)
    state: dict = {}
    if JOB_STATE.exists():
        try:
            state = json.loads(JOB_STATE.read_text(encoding="utf-8"))
        except Exception:
            state = {}
    state[skill] = {
        "last_run": record["started_at"],
        "status": record["status"],
        "exit_code": record.get("exit_code"),
        "duration_s": record.get("duration_s"),
        "error": record.get("error"),
    }
    # Atomic write: temp file then rename prevents partial-write corruption under concurrency.
    tmp = JOB_STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, JOB_STATE)


def run_once(skill: str, entrypoint: str, skill_args: list[str]) -> dict:
    script = ROOT / entrypoint
    if not script.exists():
        return {
            "skill": skill,
            "entrypoint": entrypoint,
            "args": skill_args,
            "pid": os.getpid(),
            "started_at": _now_iso(),
            "finished_at": _now_iso(),
            "status": "error",
            "exit_code": None,
            "duration_s": 0.0,
            "error": f"Script not found: {script}",
        }

    cmd = [_python(), str(script)] + skill_args
    started = time.monotonic()
    started_at = _now_iso()

    try:
        result = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=False,  # let stdout/stderr pass through to terminal
            text=True,
        )
        exit_code = result.returncode
        status = "success" if exit_code == 0 else "failed"
        error = None
    except Exception as exc:
        exit_code = None
        status = "error"
        error = str(exc)

    duration = round(time.monotonic() - started, 3)
    return {
        "skill": skill,
        "entrypoint": entrypoint,
        "args": skill_args,
        "pid": os.getpid(),
        "started_at": started_at,
        "finished_at": _now_iso(),
        "status": status,
        "exit_code": exit_code,
        "duration_s": duration,
        "error": error,
    }


def cmd_run(skill: str, skill_args: list[str], retry: int, dry_run: bool, yes: bool, headless: bool) -> int:
    registry = _load_registry()

    if skill not in registry:
        print(f"Unknown skill: {skill}", file=sys.stderr)
        print(f"Known skills: {', '.join(sorted(registry))}", file=sys.stderr)
        return 1

    entry = registry[skill]
    sec = entry.get("security", {})

    # Headless safety gate: block confirmation_required and destructive skills from
    # unattended execution (cron, launchd, remote workers).
    if headless:
        if sec.get("confirmation_required") or sec.get("risk_level") == "destructive":
            print(
                f"[runner] BLOCKED: `{skill}` requires human confirmation "
                f"(risk={sec.get('risk_level', '?')}) and cannot run headless.",
                file=sys.stderr,
            )
            return 1

    # Interactive security gate
    if sec.get("confirmation_required") and not yes and not dry_run:
        risk = sec.get("risk_level", "unknown")
        reason = sec.get("reason", "")
        print(f"[security] {skill} requires confirmation.")
        print(f"  risk:   {risk}")
        print(f"  reason: {reason}")
        answer = input("  Proceed? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("Aborted.")
            return 1

    if not entry.get("schedule_eligible"):
        print(
            f"Skill `{skill}` is not marked schedule_eligible.\n"
            "Only eligible skills with executable scripts can be run by the runner.",
            file=sys.stderr,
        )
        return 1

    entrypoint = entry.get("entrypoint")
    if not entrypoint:
        print(f"Skill `{skill}` has no entrypoint script defined.", file=sys.stderr)
        return 1

    if dry_run:
        print(f"[dry-run] would run: {_python()} {entrypoint} {' '.join(skill_args)}")
        return 0

    # Per-skill exclusive lock: prevents two runners from launching the same skill concurrently.
    lock_fh = _acquire_lock(skill)
    if _HAVE_FCNTL and lock_fh is None:
        print(f"[runner] BLOCKED: `{skill}` is already running (lock held). Aborting.", file=sys.stderr)
        return 1

    try:
        print(f"[runner] {skill} → {entrypoint}")
        if skill_args:
            print(f"[runner] args: {skill_args}")
        print(f"[runner] started at {_now_iso()}")
        print()

        attempts = 0
        record: dict = {}
        while attempts <= retry:
            if attempts > 0:
                print(f"\n[runner] retry {attempts}/{retry}...")
            record = run_once(skill, entrypoint, skill_args)
            attempts += 1
            if record["status"] == "success":
                break

        _append_log(record)
        _update_state(skill, record)

        print()
        status_line = f"[runner] {record['status'].upper()} in {record['duration_s']}s"
        if record.get("error"):
            status_line += f" — {record['error']}"
        print(status_line)

        return 0 if record["status"] == "success" else 1
    finally:
        if lock_fh is not None:
            lock_fh.close()  # releases fcntl lock automatically


def cmd_list(registry: dict) -> int:
    schedulable = {n: e for n, e in registry.items() if e.get("schedule_eligible")}
    if not schedulable:
        print("No schedulable skills registered.")
        return 0
    print(f"{'Skill':<25} {'Mode':<12} {'Entrypoint'}")
    print("-" * 70)
    for name, entry in sorted(schedulable.items()):
        ep = entry.get("entrypoint") or "—"
        print(f"{name:<25} {entry.get('execution_mode', ''):<12} {ep}")
    return 0


def cmd_status() -> int:
    if not JOB_STATE.exists():
        print("No job state found. No skills have been run yet.")
        return 0

    state = json.loads(JOB_STATE.read_text(encoding="utf-8"))
    if not state:
        print("Job state is empty.")
        return 0

    print(f"{'Skill':<25} {'Status':<10} {'Last run':<26} {'Duration'}")
    print("-" * 80)
    for name, info in sorted(state.items()):
        duration = f"{info.get('duration_s', '?')}s" if info.get("duration_s") is not None else "?"
        print(f"{name:<25} {info.get('status', '?'):<10} {info.get('last_run', '?'):<26} {duration}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Job runner for schedulable skills.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Example: .venv/bin/python3 .codex/runner/run_skill.py yt-pipeline -- --query 'AI agents' --goal 'survey'",
    )
    parser.add_argument("skill", nargs="?", help="Skill name to run.")
    parser.add_argument("skill_args", nargs=argparse.REMAINDER, help="Arguments forwarded to the skill script (after --).")
    parser.add_argument("--retry", type=int, default=0, metavar="N", help="Retry on failure up to N times (default 0).")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be run without executing.")
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt for high-risk skills.")
    parser.add_argument("--headless", action="store_true", help="Headless mode: abort if skill requires human confirmation or has destructive risk level. Use for cron/launchd/remote execution.")
    parser.add_argument("--list", action="store_true", help="List all schedulable skills and exit.")
    parser.add_argument("--status", action="store_true", help="Show last run status for all skills and exit.")

    args = parser.parse_args()

    if args.list:
        return cmd_list(_load_registry())

    if args.status:
        return cmd_status()

    if not args.skill:
        parser.print_help()
        return 1

    # Strip leading '--' separator if present
    skill_args = args.skill_args
    if skill_args and skill_args[0] == "--":
        skill_args = skill_args[1:]

    return cmd_run(args.skill, skill_args, args.retry, args.dry_run, args.yes, args.headless)


if __name__ == "__main__":
    raise SystemExit(main())
