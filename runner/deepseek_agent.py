"""DeepSeek Agent -- direct API integration with tool-calling loop.

Replaces the old `deepseek --prompt --yolo` subprocess + _execute_deepseek_commands
hack with a proper tool-enabled agent that calls DeepSeek's chat completions API
directly, provides real tool definitions, and executes tool calls in a loop.
"""

import os
import json
import subprocess
import time
import logging
import re
from pathlib import Path
from typing import Any, Callable

import httpx

logger = logging.getLogger(__name__)

DEEPSEEK_API_BASE = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-flash"
MAX_TOOL_ITERATIONS = 20
TOOL_TIMEOUT = 60


def _api_key() -> str:
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not key:
        cfg = Path.home() / ".deepseek" / "config.toml"
        if cfg.exists():
            for line in cfg.read_text().splitlines():
                line = line.strip()
                if line.startswith("api_key"):
                    key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    return key


TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "exec_shell",
            "description": "Execute a shell command on the local machine and return stdout/stderr/exit_code.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to execute"}
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file at the given path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file (absolute or relative to workspace root)"}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file. Creates parent directories if needed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file"},
                    "content": {"type": "string", "description": "File content to write"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Replace a specific text block in a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file"},
                    "old_string": {"type": "string", "description": "Text to find and replace (must be unique)"},
                    "new_string": {"type": "string", "description": "Replacement text"},
                },
                "required": ["path", "old_string", "new_string"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List files and directories in a given path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path"}
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grep_files",
            "description": "Search for a regex pattern in workspace files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regular expression to search for"},
                    "include": {"type": "string", "description": "Optional: glob pattern (e.g. *.py)"},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_status",
            "description": "Show the working tree status.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_diff",
            "description": "Show git diff for unstaged changes.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
]


def _exec_tool(name: str, args: dict[str, Any], cwd: str | None = None) -> str:
    try:
        if name == "exec_shell":
            cmd = args.get("command", "")
            if not cmd:
                return json.dumps({"error": "No command provided"})
            result = subprocess.run(
                cmd, shell=True, cwd=cwd or os.getcwd(),
                capture_output=True, text=True, timeout=TOOL_TIMEOUT,
            )
            parts = []
            if result.stdout.strip():
                parts.append(result.stdout.strip())
            if result.stderr.strip():
                parts.append(f"stderr: {result.stderr.strip()}")
            parts.append(f"exit code: {result.returncode}")
            return "\n".join(parts)

        elif name == "read_file":
            p = Path(args.get("path", ""))
            if not p.is_absolute():
                p = (Path(cwd or os.getcwd()) / p).resolve()
            if not p.exists():
                return json.dumps({"error": f"File not found: {p}"})
            return p.read_text(encoding="utf-8", errors="replace")

        elif name == "write_file":
            p = Path(args.get("path", ""))
            if not p.is_absolute():
                p = (Path(cwd or os.getcwd()) / p).resolve()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(args.get("content", ""), encoding="utf-8")
            return json.dumps({"ok": True, "path": str(p)})

        elif name == "edit_file":
            p = Path(args.get("path", ""))
            if not p.is_absolute():
                p = (Path(cwd or os.getcwd()) / p).resolve()
            if not p.exists():
                return json.dumps({"error": f"File not found: {p}"})
            content = p.read_text(encoding="utf-8")
            old = args.get("old_string", "")
            new = args.get("new_string", "")
            if old not in content:
                return json.dumps({"error": "old_string not found"})
            count = content.count(old)
            if count > 1:
                return json.dumps({"error": f"old_string found {count} times"})
            content = content.replace(old, new)
            p.write_text(content, encoding="utf-8")
            return json.dumps({"ok": True, "path": str(p)})

        elif name == "list_dir":
            p = Path(args.get("path", cwd or os.getcwd()))
            if not p.is_absolute():
                p = (Path(cwd or os.getcwd()) / p).resolve()
            if not p.is_dir():
                return json.dumps({"error": f"Not a directory: {p}"})
            return "\n".join(sorted(e.name for e in p.iterdir()))

        elif name == "grep_files":
            pattern = args.get("pattern", "")
            include = args.get("include", "*")
            root = Path(cwd or os.getcwd())
            matches = []
            for f in root.rglob(include):
                if f.is_file() and not any(p.startswith(".") for p in f.parts):
                    try:
                        text = f.read_text(encoding="utf-8", errors="replace")
                        for i, line in enumerate(text.splitlines(), 1):
                            if re.search(pattern, line):
                                rel = f.relative_to(root)
                                matches.append(f"{rel}:{i}: {line.strip()[:200]}")
                    except Exception:
                        pass
            return "\n".join(matches[:200]) or "No matches found"

        elif name == "git_status":
            result = subprocess.run(
                ["git", "status", "--short"], cwd=cwd or os.getcwd(),
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                return f"Error: {result.stderr.strip()}"
            return result.stdout.strip() or "Working tree clean"

        elif name == "git_diff":
            result = subprocess.run(
                ["git", "diff"], cwd=cwd or os.getcwd(),
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                return f"Error: {result.stderr.strip()}"
            return result.stdout.strip() or "No unstaged changes"

        return json.dumps({"error": f"Unknown tool: {name}"})
    except subprocess.TimeoutExpired:
        return json.dumps({"error": f"Tool {name} timed out after {TOOL_TIMEOUT}s"})
    except Exception as e:
        return json.dumps({"error": f"Tool {name} failed: {e}"})


class DeepSeekAgent:
    """Agent that calls DeepSeek API with tools and executes tool calls in a loop."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        workspace: str | None = None,
        api_key: str | None = None,
    ):
        self.model = model
        self.workspace = workspace or os.getcwd()
        self.api_key = api_key or _api_key()
        self._messages: list[dict[str, Any]] = []

    def run(
        self,
        prompt: str,
        system_prompt: str | None = None,
        stream_callback: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        self._messages = []
        if system_prompt:
            self._messages.append({"role": "system", "content": system_prompt})
        self._messages.append({"role": "user", "content": prompt})

        start_time = time.monotonic()
        total_input_tokens = 0
        total_output_tokens = 0
        iterations = 0

        while iterations < MAX_TOOL_ITERATIONS:
            iterations += 1
            data = {
                "model": self.model,
                "messages": self._messages,
                "tools": TOOL_DEFINITIONS,
                "max_tokens": 16000,
            }
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            try:
                resp = httpx.post(
                    f"{DEEPSEEK_API_BASE}/chat/completions",
                    headers=headers, json=data, timeout=120,
                )
                if resp.status_code != 200:
                    err = f"API error {resp.status_code}: {resp.text[:500]}"
                    if stream_callback:
                        stream_callback(f"\n[{err}]\n")
                    return {"ok": False, "error": err,
                            "duration_s": round(time.monotonic() - start_time, 2)}

                result = resp.json()
                choice = result["choices"][0]
                msg = choice["message"]
                usage = result.get("usage", {})
                total_input_tokens += usage.get("prompt_tokens", 0)
                total_output_tokens += usage.get("completion_tokens", 0)

                self._messages.append(msg)
                tool_calls = msg.get("tool_calls") or []

                if not tool_calls:
                    text = msg.get("content") or ""
                    if stream_callback:
                        stream_callback(text)
                    return {
                        "ok": True, "output": text,
                        "duration_s": round(time.monotonic() - start_time, 2),
                        "input_tokens": total_input_tokens,
                        "output_tokens": total_output_tokens,
                        "iterations": iterations,
                        "model": result.get("model", self.model),
                    }

                for tc in tool_calls:
                    func_name = tc["function"]["name"]
                    try:
                        func_args = json.loads(tc["function"]["arguments"])
                    except json.JSONDecodeError:
                        func_args = {}
                    if stream_callback:
                        stream_callback(f"\n[{func_name}]")
                    tool_result = _exec_tool(func_name, func_args, cwd=self.workspace)
                    if stream_callback and len(tool_result) < 2000:
                        stream_callback(f"\n{tool_result[:1000]}\n")
                    self._messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": tool_result[:10000],
                    })

            except httpx.TimeoutException:
                err = "API request timed out after 120s"
                if stream_callback:
                    stream_callback(f"\n[{err}]\n")
                return {"ok": False, "error": err,
                        "duration_s": round(time.monotonic() - start_time, 2)}
            except Exception as e:
                err = f"Agent error: {e}"
                if stream_callback:
                    stream_callback(f"\n[{err}]\n")
                return {"ok": False, "error": err,
                        "duration_s": round(time.monotonic() - start_time, 2)}

        return {"ok": False,
                "error": f"Exceeded max tool iterations ({MAX_TOOL_ITERATIONS})",
                "duration_s": round(time.monotonic() - start_time, 2)}


def run_deepseek_agent(
    prompt: str,
    model: str = DEFAULT_MODEL,
    system_prompt: str | None = None,
    workspace: str | None = None,
    stream_callback: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    agent = DeepSeekAgent(model=model, workspace=workspace)
    return agent.run(prompt, system_prompt=system_prompt, stream_callback=stream_callback)


if __name__ == "__main__":
    import sys
    prompt = " ".join(sys.argv[1:]) or "Run 'date' and tell me the current time."
    result = run_deepseek_agent(prompt)
    print(json.dumps(result))
