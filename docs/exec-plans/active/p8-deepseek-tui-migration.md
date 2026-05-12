# P8 — Migrate from Aider to DeepSeek TUI

**Status:** Complete  
**Started:** 2026-05-11
**Owner:** AgenticOS

## Goal

Replace `aider` as the DeepSeek execution tool with DeepSeek TUI (`deepseek` CLI). Aider causes infinite reasoning loops with DeepSeek V4. DeepSeek TUI is purpose-built for DeepSeek V4, uses `apply-patch` (no SEARCH/REPLACE guessing), and has YOLO mode equivalent to Claude Code's `bypassPermissions`.

## Why Now

- Aider + DeepSeek V4 reliably loops on files > ~300 lines
- Root cause: aider uses SEARCH/REPLACE format which triggers DeepSeek reasoning spiral
- DeepSeek TUI uses structured `apply-patch` tool — no format guessing, no loops
- V4 Pro/Flash natively supported (no litellm abstraction layer)

## Gate Decision — Symphony CLI Choice

**Symphony (`symphony/aider_deep.py`) is blocked on this plan.**

Symphony will call either `aider` or `deepseek` CLI as its subprocess. This decision must not be made until Step 2 passes:

- If Step 2 passes → Symphony uses `deepseek --yolo --prompt` (apply-patch, no loops)
- If Step 2 fails → Symphony uses `aider --model deepseek/deepseek-chat --message` (known behavior, known risk)

Do not write or spec symphony internals until this gate resolves.

## Execution Order

```
Step 1 (install + smoke test) → Step 2 (validate on real task) → [GATE: symphony CLI decision] → Step 3 (update workflow docs) → Step 4 (remove aider config)
```

---

## Step 1 — Install and Smoke Test

- [x] Install DeepSeek TUI: follow https://github.com/Hmbown/DeepSeek-TUI install instructions
- [x] Verify `deepseek --version` works
- [x] Smoke test: `deepseek --model deepseek-v4-flash --yolo --prompt "print hello world to stdout"`
- [x] Confirm `DEEPSEEK_API_KEY` env var works (already set from P7)

**AC:** `deepseek` command available, responds without looping.

---

## Step 2 — Validate on Real Task

Pick one small bounded task from P7 Phase 4 or backlog. Run:

```bash
deepseek --model deepseek-v4-pro --yolo \
  "Read docs/exec-plans/active/<plan>.md and implement <one specific step>. Only modify <one file>."
```

- [x] Task completes without loop
- [x] File edit applied correctly
- [x] `python3 -m py_compile <file>` passes after edit

**AC:** One real code task completes end-to-end. Compare cost vs aider run.

---

## Step 3 — Update Workflow Docs

- [x] `AGENTS.md` — replace aider references with `deepseek` CLI (no aider references found; already clean)
- [x] `CLAUDE.md` env var table — note `DEEPSEEK_API_KEY` used by both `deepseek` CLI and `runner/app.py`
- [x] `docs/PLANS.md` — note DeepSeek TUI as standard tool for DeepSeek tasks
- [x] Update any prompts in exec plans that say `aider --message` → `deepseek --yolo --prompt` (no matches found outside this plan)

---

## Step 4 — Remove Aider Config

- [x] Delete `.aider.conf.yml` (no longer needed)
- [x] Confirm `aider` still installed as fallback (keep but don't use as primary)

---

## Key Constraints

- Do NOT remove `aider` from env — keep as fallback
- YOLO mode = auto-approved; only use for tasks scoped to this repo
- `deepseek-v4-pro` for complex tasks; `deepseek-v4-flash` for mechanical edits
- Step 2 must pass before committing to full migration

## Reference

- Tool: https://github.com/Hmbown/DeepSeek-TUI
- Models: `deepseek-v4-pro` (full), `deepseek-v4-flash` (fast/cheap)
- Modes: Plan (read-only), Agent (approval gates), YOLO (auto-approved)