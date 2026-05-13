# P9 — Research: Shell Execution for DeepSeek via MCP

**Status:** Completed — superseded by direct API integration  
**Priority:** Low  
**Superseded by:** `runner/deepseek_agent.py` (direct API tool-calling agent)

## Goal

Investigate whether DeepSeek TUI's MCP (Model Context Protocol) or sandbox configuration can grant shell execution capability to the non-interactive `exec` mode, eliminating the need for dashboard-side post-processing.

## Background

DeepSeek TUI v0.8.29's non-interactive `exec` mode (`deepseek exec`) does not include real tool definitions (`exec_shell`, `code_execution`, `read_file`, etc.) in its system prompt. It only simulates tool outputs. This limits dispatched deepseek agents to text generation only.

The original workaround (P8, Option 2) added dashboard-side post-processing: parse ` ```bash ` blocks from deepseek output, execute them locally via Python `subprocess`, and inject real results.

**Since the writing of this plan, `runner/deepseek_agent.py` was implemented**, which solves the problem at the architecture level — no MCP, sandbox, or post-processing needed.

## Research Findings (verified 2026-05-12)

### Q1: MCP Server Registration

`deepseek mcp` has full subcommand support:
- `list`, `add`, `remove`, `enable`, `disable`, `connect`, `tools`, `validate`, `init`, `add-self`
- **`deepseek mcp add-self`** registers a config entry in `~/.deepseek/mcp.json` that launches `deepseek serve --mcp` via stdio transport, exposing all internal tools
- **`deepseek serve --mcp`** starts an MCP server over stdio
- **`deepseek serve --http`** starts an HTTP/SSE runtime API server (port 7878, localhost) with auth, CORS, and worker pool support
- Feature flags confirm: `mcp` = experimental & enabled, `shell_tool` = stable & enabled

**Blocker:** macOS SIP/permissions prevent `deepseek mcp add-self` from writing to `~/.deepseek/` (Operation not permitted). No `mcp.json` exists. Could be worked around by manually placing the file.

**Verdict:** Technically feasible but unnecessary — the direct API approach is simpler.

### Q2: Sandbox Mode

- `deepseek sandbox check <command>` evaluates approval policy decisions and works correctly
- Current config: `approval_policy = auto`, project is `trusted`
- `--sandbox-mode` is a global CLI option but its possible values are not enumerated in help output
- The sandbox system is for TUI interactive mode's approval policy — it does not add tool definitions to `deepseek exec`'s system prompt

**Verdict:** Sandbox configuration does not solve the core problem (missing tool definitions in exec mode).

### Q3: app-server / HTTP Dispatch

- `deepseek app-server` runs on port 8787 with `--host`, `--port`, `--stdio` options
- `deepseek serve --http` is the more capable HTTP/SSE runtime API (port 7878) with workers, CORS, auth
- Both could serve as tool-enabled backends for external HTTP clients

**Verdict:** Feasible but architecturally inferior to the direct API approach — adds a separate server process with IPC overhead.

## How It Was Actually Solved

The project already has a complete solution in `runner/deepseek_agent.py`:

```
app.py → _ds_dispatch() → DeepSeekModule.dispatch() → deepseek_agent.run_deepseek_agent()
```

**`deepseek_agent.py`** bypasses `deepseek exec` entirely:
1. Calls DeepSeek chat completions API directly (`api.deepseek.com/beta`)
2. Provides **6 real tool definitions** in the API call: `exec_shell`, `read_file`, `write_file`, `edit_file`, `list_dir`, `grep_files`
3. Executes tool calls in a loop (max 20 iterations)
4. Supports streaming callbacks for SocketIO push
5. Reports usage (tokens in/out, duration, iteration count)

**`runner/modules/backends/deepseek.py`** (DeepSeekModule) wraps it:
- `dispatch()` → agent with tools
- `execute_commands()` → fallback post-processing (parses ```bash blocks)
- `load_usage()` → monitor integration

**`runner/app.py`** integration:
- When `agent == "deepseek"`, calls `_ds_dispatch()` instead of CLI subprocess
- Full SocketIO streaming, retry support, token tracking

## Evaluation

| Path | Feasible | Implemented | Recommendation |
|------|----------|-------------|---------------|
| **Direct API** (`deepseek_agent.py`) | ✓ | ✓ | **Current production solution** |
| **MCP server** (`deepseek serve --mcp`) | ✓ | ✗ | Alternative — extra process |
| **Sandbox config** (`--sandbox-mode`) | Partial | ✗ | Doesn't add tool definitions |
| **HTTP server** (`deepseek serve --http`) | ✓ | ✗ | Alternative — IPC overhead |

The direct API approach wins on simplicity, reliability, and observability. No MCP/sandbox/app-server work needed.

## Acceptance Criteria — All Met

- [x] DeepSeek dispatch via Job Board executes shell commands directly (no post-processing)
- [x] File reads (`read_file`) work in dispatch mode
- [x] Output is deterministic with real timestamps and exit codes
- [x] Tool iterations are tracked and reported
- [x] DeepSeek post-processing (`execute_commands()`) remains as a fallback for any residual non-tool output

## Superseding Context

This plan is **completed and superseded**. The post-processing workaround (P8, Option 2) is no longer the primary path for DeepSeek — it remains as a fallback only.

The MCP infrastructure (`deepseek serve --mcp`, `deepseek serve --http`) remains available if future requirements demand external tool access (e.g., an ACP server for editor integration).
