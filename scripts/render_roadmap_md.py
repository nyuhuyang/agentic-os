#!/usr/bin/env python3
"""Generate docs/exec-plans/ROADMAP.md from state/roadmap.json.

Usage:
    python3 scripts/render_roadmap_md.py
    python3 scripts/render_roadmap_md.py --roadmap

This script reads the structured JSON source of truth and produces a
human-readable markdown summary. The markdown file is NOT authoritative;
all state changes must be made in state/roadmap.json.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROTO = _HERE.parent  # agentic-os root

STATE_DIR = _PROTO / "state"
ROADMAP_JSON = STATE_DIR / "roadmap.json"
EVENTS_JSONL = STATE_DIR / "events.jsonl"
OUTPUT_MD = _PROTO / "docs" / "exec-plans" / "ROADMAP.md"
OUTPUT_ACTIVE_TASKS = _PROTO / "docs" / "generated" / "ACTIVE_TASKS.md"
OUTPUT_COMPLETED = _PROTO / "docs" / "generated" / "COMPLETED.md"
OUTPUT_ACTIVE_TASKS = _PROTO / "docs" / "generated" / "ACTIVE_TASKS.md"
OUTPUT_COMPLETED = _PROTO / "docs" / "generated" / "COMPLETED.md"


def _load_roadmap() -> dict:
    if not ROADMAP_JSON.exists():
        print(f"Error: {ROADMAP_JSON} not found.", file=sys.stderr)
        sys.exit(1)
    try:
        return json.loads(ROADMAP_JSON.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"Error parsing {ROADMAP_JSON}: {e}", file=sys.stderr)
        sys.exit(1)


def _append_event(event: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with EVENTS_JSONL.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def _fmt_date(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return iso[:10]


def _render_section(items: list[dict], heading: str, args) -> list[str]:
    if not items:
        if args.no_empty:
            return []
        return [f"## {heading}", "", "_None._", ""]

    lines = [f"## {heading}", ""]
    for item in items:
        status_tag = item.get("status", "")
        title = item.get("title", "Untitled")
        notes = item.get("notes", "")
        updated = _fmt_date(item.get("updated_at"))
        item_id = item.get("id", "")

        if args.no_items:
            continue
        if args.no_id:
            item_id = ""
        if args.no_title:
            title = ""
        if args.no_status:
            status_tag = ""
        if args.no_notes:
            notes = ""
        if args.no_updated:
            updated = ""

        line_parts = []
        if item_id:
            line_parts.append(f"### {item_id.upper()}")
        if title:
            if line_parts:
                line_parts.append(" — " + title)
            else:
                line_parts.append(f"### {title}")
        if line_parts:
            lines.append("".join(line_parts))
        else:
            lines.append("### ")

        if status_tag:
            lines.append(f"**Status:** {status_tag}")
        if updated:
            lines.append(f"**Updated:** {updated}")
        if notes:
            lines.append("")
            lines.append(notes)
        lines.append("")
    return lines


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Generate ROADMAP.md from state/roadmap.json")
    parser.add_argument("--roadmap", action="store_true", help="Generate docs/exec-plans/ROADMAP.md (default behavior)")
    parser.add_argument("--dry-run", action="store_true", help="Print generated markdown to stdout instead of writing to file")
    parser.add_argument("--watch", action="store_true", help="Watch for changes to state/roadmap.json and regenerate")
    parser.add_argument("--output", type=str, default=None, help="Custom output path")
    parser.add_argument("--no-events", action="store_true", help="Skip appending to events.jsonl")
    parser.add_argument("--no-header", action="store_true", help="Skip the generated header line")
    parser.add_argument("--no-footer", action="store_true", help="Skip the footer line")
    parser.add_argument("--no-timestamp", action="store_true", help="Skip timestamp in header")
    parser.add_argument("--no-version", action="store_true", help="Skip version in header")
    parser.add_argument("--no-updated", action="store_true", help="Skip updated date in header")
    parser.add_argument("--no-separator", action="store_true", help="Skip separator line")
    parser.add_argument("--no-sections", action="store_true", help="Skip all sections (just header and footer)")
    parser.add_argument("--no-completed", action="store_true", help="Skip Completed section")
    parser.add_argument("--no-active", action="store_true", help="Skip Active section")
    parser.add_argument("--no-backlog", action="store_true", help="Skip Backlog section")
    parser.add_argument("--no-deferred", action="store_true", help="Skip Deferred section")
    parser.add_argument("--no-empty", action="store_true", help="Skip empty sections")
    parser.add_argument("--no-notes", action="store_true", help="Skip notes in items")
    parser.add_argument("--no-status", action="store_true", help="Skip status tags")
    parser.add_argument("--no-id", action="store_true", help="Skip item IDs")
    parser.add_argument("--no-title", action="store_true", help="Skip item titles")
    parser.add_argument("--no-items", action="store_true", help="Skip all items (just section headings)")
    parser.add_argument("--no-headings", action="store_true", help="Skip section headings")
    parser.add_argument("--no-meta", action="store_true", help="Skip all metadata (header, footer, separator)")
    parser.add_argument("--no-content", action="store_true", help="Skip all content (just metadata)")
    parser.add_argument("--no-output", action="store_true", help="Skip writing to file (just print to stdout)")
    parser.add_argument("--no-append", action="store_true", help="Skip appending to events.jsonl")
    parser.add_argument("--no-print", action="store_true", help="Skip printing to stdout")
    parser.add_argument("--no-active-tasks", action="store_true", help="Skip generating ACTIVE_TASKS.md")
    parser.add_argument("--no-completed-file", action="store_true", help="Skip generating COMPLETED.md")
    args = parser.parse_args()

    if args.watch:
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler
        except ImportError:
            print("watchdog not installed; falling back to polling every 2 seconds", file=sys.stderr)
            _polling_watch(args)
            return 0

        class RoadmapHandler(FileSystemEventHandler):
            def on_modified(self, event):
                if event.src_path == str(ROADMAP_JSON):
                    print(f"Detected change in {ROADMAP_JSON}, regenerating...")
                    _generate(args)

        observer = Observer()
        observer.schedule(RoadmapHandler(), str(STATE_DIR), recursive=False)
        observer.start()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            observer.stop()
        observer.join()
        return 0

    _generate(args)
    return 0


def _polling_watch(args) -> None:
    last_mtime = ROADMAP_JSON.stat().st_mtime if ROADMAP_JSON.exists() else 0
    try:
        while True:
            time.sleep(2)
            if ROADMAP_JSON.exists():
                mtime = ROADMAP_JSON.stat().st_mtime
                if mtime != last_mtime:
                    last_mtime = mtime
                    print(f"Detected change in {ROADMAP_JSON}, regenerating...")
                    _generate(args)
    except KeyboardInterrupt:
        pass


def _generate(args) -> None:
    roadmap = _load_roadmap()
    version = roadmap.get("version", 1)
    updated_at = roadmap.get("updated_at", "")
    updated_date = _fmt_date(updated_at)

    lines = []

    if not args.no_header:
        header_parts = ["# Roadmap", ""]
        if not args.no_timestamp or not args.no_version or not args.no_updated:
            meta_parts = []
            if not args.no_version:
                meta_parts.append(f"Version {version}")
            if not args.no_updated:
                meta_parts.append(f"Last updated {updated_date}")
            if meta_parts:
                header_parts.append(f"> **Generated from `state/roadmap.json`** · {' · '.join(meta_parts)}")
                header_parts.append("")
        header_parts.append("This file is automatically generated. Do not edit it directly.")
        header_parts.append("To make changes, edit `state/roadmap.json` and run:")
        header_parts.append("")
        header_parts.append("    python3 scripts/render_roadmap_md.py")
        header_parts.append("")
        if not args.no_separator:
            header_parts.append("---")
            header_parts.append("")
        lines.extend(header_parts)

    if not args.no_sections:
        sections = []
        if not args.no_completed:
            sections.append(("completed", "Completed"))
        if not args.no_active:
            sections.append(("active", "Active"))
        if not args.no_backlog:
            sections.append(("backlog", "Backlog"))
        if not args.no_deferred:
            sections.append(("deferred", "Deferred"))

        for key, heading in sections:
            items = roadmap.get(key, [])
            if args.no_empty and not items:
                continue
            if args.no_headings:
                # still render items but without heading
                for item in items:
                    lines.extend(_render_section([item], heading, args))
            else:
                lines.extend(_render_section(items, heading, args))

    if not args.no_footer:
        lines.append("")
        lines.append("---")
        lines.append("")

    # Remove trailing blank line
    while lines and lines[-1] == "":
        lines.pop()
    lines.append("")

    output_path = Path(args.output) if args.output else OUTPUT_MD

    if args.dry_run or args.no_output:
        print("\n".join(lines))
    else:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("\n".join(lines), encoding="utf-8")
        if not args.no_print:
            print(f"Generated {output_path}")

    if not args.no_events and not args.no_append:
        _append_event({
            "type": "roadmap_rendered",
            "version": version,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        })

    # Generate ACTIVE_TASKS.md
    if not args.no_active_tasks:
        active_items = roadmap.get("active", [])
        active_lines = ["# Active Tasks", ""]
        if not active_items:
            active_lines.append("_No active tasks._")
        else:
            for item in active_items:
                title = item.get("title", "Untitled")
                status = item.get("status", "")
                notes = item.get("notes", "")
                active_lines.append(f"## {title}")
                if status:
                    active_lines.append(f"**Status:** {status}")
                if notes:
                    active_lines.append("")
                    active_lines.append(notes)
                active_lines.append("")
        while active_lines and active_lines[-1] == "":
            active_lines.pop()
        active_lines.append("")
        OUTPUT_ACTIVE_TASKS.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_ACTIVE_TASKS.write_text("\n".join(active_lines), encoding="utf-8")
        if not args.no_print:
            print(f"Generated {OUTPUT_ACTIVE_TASKS}")

    # Generate COMPLETED.md
    if not args.no_completed_file:
        completed_items = roadmap.get("completed", [])
        completed_lines = ["# Completed Tasks", ""]
        if not completed_items:
            completed_lines.append("_No completed tasks._")
        else:
            for item in completed_items:
                title = item.get("title", "Untitled")
                status = item.get("status", "")
                notes = item.get("notes", "")
                completed_lines.append(f"## {title}")
                if status:
                    completed_lines.append(f"**Status:** {status}")
                if notes:
                    completed_lines.append("")
                    completed_lines.append(notes)
                completed_lines.append("")
        while completed_lines and completed_lines[-1] == "":
            completed_lines.pop()
        completed_lines.append("")
        OUTPUT_COMPLETED.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_COMPLETED.write_text("\n".join(completed_lines), encoding="utf-8")
        if not args.no_print:
            print(f"Generated {OUTPUT_COMPLETED}")



if __name__ == "__main__":
    raise SystemExit(main())

