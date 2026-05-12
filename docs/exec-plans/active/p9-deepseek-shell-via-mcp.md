# P9 — Research: Shell Execution for DeepSeek via MCP

**Status:** Planned  
**Priority:** Low (blocked by option-2 workaround)  

## Goal

Investigate whether DeepSeek TUI's MCP (Model Context Protocol) or sandbox configuration can grant shell execution capability to the non-interactive `exec` mode, eliminating the need for dashboard-side post-processing.

## Background

DeepSeek TUI v0.8.29's non-interactive `exec` mode (`deepseek exec`) does not include real tool definitions (`exec_shell`, `code_execution`, `read_file`, etc.) in its system prompt. It only simulates tool outputs. This limits dispatched deepseek agents to text generation only.

The current workaround (P8, Option 2) adds dashboard-side post-processing: parse ` ```bash ` blocks from deepseek output, execute them locally via Python `subprocess`, and inject real results.

## Research Questions

1. **Does `deepseek mcp` support registering a custom MCP server that provides shell execution?**
   - Check MCP stdio protocol: `deepseek mcp-server --help`
   - Can we run an MCP server alongside `deepseek exec`?
   - What tools does the MCP server need to expose?

2. **Does `--sandbox-mode danger-full-access` or any sandbox config unlock real tools in `exec` mode?**
   - Currently tested: `--sandbox-mode danger-full-access` does NOT help
   - Are there other sandbox modes or config values?
   - Is `external-sandbox` usable?

3. **Does `deepseek app-server` mode support tool-enabled dispatch over HTTP?**
   - Port 8787, runs as a server
   - Could accept prompts and return responses with real tool execution

## Acceptance Criteria

- A deepseek dispatch via the Job Board executes shell commands directly (no post-processing)
- File reads (`read_file`) also work in exec mode
- Output is deterministic and verifiable (e.g., real timestamps)

## Evaluation

If this research finds a viable approach, implement it and replace the post-processing workaround (P8, Option 2). If not, the post-processing approach remains the permanent solution.

## Prior Art

- DeepSeek TUI v0.8.29 interactive mode has full tool access
- `deepseek exec` mode has no real tools (verified by testing)
- MCP standard: https://modelcontextprotocol.io/
