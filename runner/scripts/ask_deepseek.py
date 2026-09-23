#!/usr/bin/env python3
"""Delegate a text-only task to DeepSeek — callable by Claude Code or Codex.

Two modes:
  --agentic   Use `deepseek exec --auto` (file tools, shell, multi-step coding)
  (default)   Direct API call — supports multi-turn conversation history

Session persistence:
  Sessions are stored in a file (default: /tmp/.deepseek_session).
  --agentic: uses deepseek's --resume <session_id>
  default:   replays full conversation history on each call
  --new:     clear session and start fresh

Usage:
    python3 ask_deepseek.py --prompt "Review this strategy..."
    python3 ask_deepseek.py --prompt "Follow-up question..."   # continues same session
    python3 ask_deepseek.py --new --prompt "Start fresh"
    python3 ask_deepseek.py --prompt-file prompt.md --out result.md
    python3 ask_deepseek.py --attach main.py --prompt "Review this file"
    python3 ask_deepseek.py --agentic --prompt-file task.md
    echo "Summarize this CSV" | python3 ask_deepseek.py
    python3 ask_deepseek.py --prompt "..." --json

Exit codes:
    0  success
    1  bad arguments / missing prompt
    2  missing/invalid API key
    3  network/API error
    4  response parse error
    5  deepseek binary not found (--agentic mode)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_SYSTEM = (
    "You are a rigorous analytical assistant. "
    "Respond with precise, well-structured analysis. "
    "Never fabricate data. If uncertain, say so."
)

# Session state files
SESSION_DIR = Path("/tmp")
AGENTIC_SESSION_FILE = SESSION_DIR / ".deepseek_agentic_session"
API_HISTORY_FILE = SESSION_DIR / ".deepseek_api_history.json"


# ── API key ─────────────────────────────────────────────────────────────────

def _api_key() -> str:
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if key:
        return key
    cfg = Path.home() / ".deepseek" / "config.toml"
    if cfg.exists():
        for line in cfg.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line.startswith("api_key"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


# ── Session management ───────────────────────────────────────────────────────

def _load_agentic_session() -> str | None:
    if AGENTIC_SESSION_FILE.exists():
        sid = AGENTIC_SESSION_FILE.read_text().strip()
        return sid if sid else None
    return None


def _save_agentic_session(session_id: str) -> None:
    AGENTIC_SESSION_FILE.write_text(session_id)


def _clear_session() -> None:
    for f in (AGENTIC_SESSION_FILE, API_HISTORY_FILE):
        if f.exists():
            f.unlink()
    print("[deepseek] Session cleared.", file=sys.stderr)


def _load_api_history() -> list[dict]:
    if API_HISTORY_FILE.exists():
        try:
            return json.loads(API_HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _save_api_history(history: list[dict]) -> None:
    API_HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


# ── Direct API (default mode) ────────────────────────────────────────────────

def _call_api(
    prompt: str,
    system: str,
    model: str,
    timeout: int = 120,
    new_session: bool = False,
) -> dict:
    key = _api_key()
    if not key:
        print("ERROR: DEEPSEEK_API_KEY not set and not found in ~/.deepseek/config.toml", file=sys.stderr)
        sys.exit(2)

    # Load or reset conversation history
    if new_session:
        history: list[dict] = []
    else:
        history = _load_api_history()

    # First turn: inject system message if history is empty
    messages: list[dict] = []
    if not history:
        messages.append({"role": "system", "content": system})

    messages.extend(history)
    messages.append({"role": "user", "content": prompt})

    payload = json.dumps({
        "model": model,
        "messages": messages,
        "stream": False,
    }).encode("utf-8")

    req = urllib.request.Request(
        DEEPSEEK_API_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"ERROR: DeepSeek API {e.code}: {body[:300]}", file=sys.stderr)
        sys.exit(3)
    except urllib.error.URLError as e:
        print(f"ERROR: Network error: {e.reason}", file=sys.stderr)
        sys.exit(3)
    except TimeoutError:
        print(f"ERROR: Request timed out after {timeout}s", file=sys.stderr)
        sys.exit(3)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        print(f"ERROR: Could not parse API response: {raw[:200]}", file=sys.stderr)
        sys.exit(4)

    choices = data.get("choices", [])
    if not choices:
        print(f"ERROR: Empty choices in response: {raw[:300]}", file=sys.stderr)
        sys.exit(4)

    content = choices[0].get("message", {}).get("content", "")
    usage = data.get("usage", {})

    # Persist conversation: only store user/assistant turns (not system)
    history.append({"role": "user", "content": prompt})
    history.append({"role": "assistant", "content": content})
    _save_api_history(history)

    turn = len(history) // 2
    print(f"[deepseek] turn {turn} | history saved → {API_HISTORY_FILE}", file=sys.stderr)

    return {
        "content": content,
        "model": data.get("model", model),
        "input_tokens": usage.get("prompt_tokens"),
        "output_tokens": usage.get("completion_tokens"),
        "turn": turn,
    }


# ── Agentic mode (deepseek exec --auto) ─────────────────────────────────────

def _find_deepseek_bin() -> str | None:
    import shutil
    ds = shutil.which("deepseek")
    if ds:
        return ds
    for p in ("/opt/homebrew/bin/deepseek", "/usr/local/bin/deepseek"):
        if Path(p).exists():
            return p
    return None


def _run_agentic(prompt: str, timeout: int = 1800, new_session: bool = False) -> dict:
    ds_bin = _find_deepseek_bin()
    if not ds_bin:
        print("ERROR: deepseek binary not found in PATH", file=sys.stderr)
        sys.exit(5)

    cmd = [ds_bin, "exec", "--auto", "--output-format", "stream-json"]

    # Resume session if available
    if not new_session:
        existing_session = _load_agentic_session()
        if existing_session:
            cmd += ["--resume", existing_session]
            print(f"[deepseek] resuming session {existing_session[:8]}...", file=sys.stderr)
        else:
            print("[deepseek] starting new agentic session", file=sys.stderr)
    else:
        print("[deepseek] --new: starting fresh agentic session", file=sys.stderr)

    cmd.append(prompt)

    t0 = time.monotonic()
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError:
        print("ERROR: deepseek binary not found", file=sys.stderr)
        sys.exit(5)

    content_parts: list[str] = []
    meta: dict = {}
    session_id_holder: list[str | None] = [None]
    deadline = t0 + timeout

    assert proc.stdout is not None
    for raw in proc.stdout:
        if time.monotonic() > deadline:
            proc.kill()
            print(f"ERROR: deepseek exec timed out after {timeout}s", file=sys.stderr)
            sys.exit(3)
        line = raw.decode("utf-8", errors="replace").rstrip("\n")
        if not line:
            continue
        try:
            ev = json.loads(line)
            ev_type = ev.get("type", "")
            if ev_type == "content":
                content_parts.append(ev.get("content", ""))
            elif ev_type == "metadata":
                meta.update(ev.get("meta", {}))
            elif ev_type == "session_capture":
                session_id_holder[0] = ev.get("content")
        except Exception:
            pass

    proc.wait()
    stderr_s = (proc.stderr.read() or b"").decode("utf-8", errors="replace").strip()
    if proc.returncode != 0 and not content_parts:
        print(f"ERROR: deepseek exec failed (rc={proc.returncode}): {stderr_s[:300]}", file=sys.stderr)
        sys.exit(3)

    # Save session ID for next call
    session_id = session_id_holder[0] or meta.get("session_id")
    if session_id:
        _save_agentic_session(session_id)
        print(f"[deepseek] session saved: {session_id[:8]}...", file=sys.stderr)

    return {
        "content": "".join(content_parts),
        "model": meta.get("model", "deepseek"),
        "input_tokens": meta.get("input_tokens"),
        "output_tokens": meta.get("output_tokens"),
        "session_id": session_id,
        "duration_s": round(time.monotonic() - t0, 1),
    }


# ── Prompt assembly ──────────────────────────────────────────────────────────

def _build_prompt(args: argparse.Namespace) -> str:
    parts: list[str] = []

    if args.prompt:
        parts.append(args.prompt)
    elif args.prompt_file:
        pf = Path(args.prompt_file)
        if not pf.exists():
            print(f"ERROR: --prompt-file not found: {pf}", file=sys.stderr)
            sys.exit(1)
        parts.append(pf.read_text(encoding="utf-8"))
    else:
        if sys.stdin.isatty():
            print("ERROR: provide --prompt, --prompt-file, or pipe text via stdin", file=sys.stderr)
            sys.exit(1)
        parts.append(sys.stdin.read())

    for path_str in args.attach or []:
        ap = Path(path_str)
        if not ap.exists():
            print(f"WARN: --attach file not found: {ap}", file=sys.stderr)
            continue
        content = ap.read_text(encoding="utf-8", errors="replace")
        parts.append(f"\n--- Attached: {ap.name} ---\n{content}\n---")

    return "\n\n".join(parts).strip()


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Delegate text-only tasks to DeepSeek from Claude Code or Codex"
    )
    parser.add_argument("--prompt", "-p", help="Prompt text")
    parser.add_argument("--prompt-file", "-f", help="Path to a file containing the prompt")
    parser.add_argument("--system", help="System message text")
    parser.add_argument("--system-file", help="Path to a file containing the system message")
    parser.add_argument("--attach", "-a", action="append", metavar="FILE",
                        help="Attach file contents inline (repeat for multiple)")
    parser.add_argument("--model", "-m", default=DEFAULT_MODEL,
                        help=f"DeepSeek model (default: {DEFAULT_MODEL})")
    parser.add_argument("--out", "-o", help="Write response to this file")
    parser.add_argument("--json", dest="output_json", action="store_true",
                        help="Output machine-readable JSON instead of plain text")
    parser.add_argument("--agentic", action="store_true",
                        help="Use deepseek exec --auto (file tools, multi-step coding)")
    parser.add_argument("--new", action="store_true",
                        help="Clear session and start fresh (ignore existing session)")
    parser.add_argument("--session-status", action="store_true",
                        help="Print current session info and exit")
    parser.add_argument("--timeout", type=int, default=120,
                        help="Timeout seconds (default 120; agentic default 1800)")
    args = parser.parse_args()

    # Session status query
    if args.session_status:
        sid = _load_agentic_session()
        hist = _load_api_history()
        print(f"Agentic session: {sid or 'none'}")
        print(f"API history:     {len(hist) // 2} turns ({API_HISTORY_FILE})")
        return

    # Clear session if --new
    if args.new:
        _clear_session()

    # Need a prompt for everything else
    prompt = _build_prompt(args)
    if not prompt:
        print("ERROR: empty prompt", file=sys.stderr)
        sys.exit(1)

    system = DEFAULT_SYSTEM
    if args.system:
        system = args.system
    elif args.system_file:
        sf = Path(args.system_file)
        if not sf.exists():
            print(f"ERROR: --system-file not found: {sf}", file=sys.stderr)
            sys.exit(1)
        system = sf.read_text(encoding="utf-8")

    if args.agentic:
        timeout = args.timeout if args.timeout != 120 else 1800
        result = _run_agentic(prompt, timeout=timeout, new_session=args.new)
    else:
        result = _call_api(prompt, system, args.model, timeout=args.timeout, new_session=args.new)

    content = result.get("content", "")

    if args.out:
        Path(args.out).write_text(content, encoding="utf-8")
        if not args.output_json:
            print(f"[deepseek] wrote {len(content)} chars → {args.out}", file=sys.stderr)

    if args.output_json:
        print(json.dumps({
            "content": content,
            "model": result.get("model"),
            "input_tokens": result.get("input_tokens"),
            "output_tokens": result.get("output_tokens"),
            "session_id": result.get("session_id"),
            "turn": result.get("turn"),
            "duration_s": result.get("duration_s"),
            "out": args.out,
        }))
    else:
        if not args.out:
            print(content)


if __name__ == "__main__":
    main()
