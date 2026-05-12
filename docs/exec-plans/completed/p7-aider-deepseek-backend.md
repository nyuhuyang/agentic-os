# P7 — Aider / DeepSeek Third Backend

**Status:** Complete — all phases done 2026-05-11  
**Started:** 2026-05-11  
**Owner:** AgenticOS

## Goal

Add `aider` (backed by DeepSeek) as a third agent backend alongside `claude` and `codex`. Users can select it globally or per-issue.

## Execution Order

```
Phase 1 (backend) ✅ → Phase 3 (UI) → Phase 4 (telemetry) → Phase 2 (symphony, deferred)
```

Phase 1+3 unblock daily use. Phase 4 is polish. Phase 2 deferred until aider is used for real code tasks requiring git worktree isolation.

---

## ✅ Phase 1 — Backend Core

Completed 2026-05-11. All changes in `runner/app.py` verified (`python3 -m py_compile` passes).

- [x] `_ai_cli("aider")` → `["aider", "--model", "deepseek/deepseek-v4-flash", "--yes-always", "--no-git"]`
- [x] `_ai_command("aider", prompt)` → appends `["--message", prompt]`
- [x] `_agent_model("aider", cfg)` → `"deepseek-v4-flash"`; overridable via `cfg.agent.aider_model`
- [x] `_parse_agent_output("aider", stdout)` → raw text (existing `agent != "claude"` branch covers it)
- [x] `_ISSUE_AGENT_MARKER_RE` → regex extended to `claude|codex|aider`
- [x] `_compose_issue_description()` → accepts `"aider"`
- [x] `locked_agent` validation set → includes `"aider"`
- [x] `_issue_agent_comment_body("aider")` → label `"Aider / DeepSeek"`
- [x] `load_registry("aider")` → filters by `"aider"` agent
- [x] Both `preferred_agent` validation sets (lines 2184, 2302) → include `"aider"`
- [x] `CLAUDE.md` env var table → `DEEPSEEK_API_KEY` added

---

## Phase 2 — Symphony (Aider Worktree Runner) — DEFERRED

**Decision (2026-05-11):** Phase 1 direct dispatch (`aider --no-git --message`) is sufficient for current use. Symphony adds git worktree isolation — only needed when aider makes real code changes that require branch isolation and review before merge.

**Trigger to revisit:** aider starts doing code modification tasks (not just prompt dispatch) and branch pollution becomes a real problem.

Spec preserved below for when it becomes relevant:
- `symphony/aider_deep.py` — git worktree + aider subprocess + structured output
- `symphony/config.yaml` — model, timeout, worktree_base
- Worktrees under `symphony/worktrees/<run_id>/`, cleaned up on completion
- Output schema matches `run_log.jsonl`

---

## ✅ Phase 3 — UI: Three-Way Model Switcher

Completed 2026-05-11. All changes in `runner/templates/index.html`.

- [x] CSS: `.agent-badge.aider`, `.job-btn.retry-aider`, `.todo-run-btn.aider` (green #7ec8a0)
- [x] CSS: `.agent-btn:not(:first-child)` border fix for 3-button toggle
- [x] HTML: global toolbar toggle — ⬡ Aider button added
- [x] HTML: issue detail modal agent picker — ⬡ Aider button added
- [x] HTML: dispatch + retry button groups — Aider buttons added
- [x] HTML: todo card — ▶ Aider run button added
- [x] JS: `setAgent()` — aider active toggle
- [x] JS: `setDetailIssueAgent()` — ternary normalization, aider button toggle
- [x] JS: `_updateDetailRetryLock()` — aider retry button show/hide
- [x] JS: `paLabel` — `'AIDER'` label for badge

---

## ✅ Phase 4 — Telemetry

File: `runner/usage_reader.py`

### Step 1 — Add aider to DEFAULT_LIMITS

Find the `DEFAULT_LIMITS` dict (contains `"claude"` and `"codex"` keys). Add:

```python
"aider":  {"window_5h": 10_000_000, "window_7d": 50_000_000, "daily_runs_max": 20},
```

### Step 2 — Add aider branch in `compute_windows()`

`compute_windows()` has an `if agent == "codex":` block that returns early. Add a new `if agent == "aider":` block **before** the codex block. It must return the same dict shape.

Logic:
- Read `run_log_path` (already passed in, defaults to `outputs/run_log.jsonl`)
- Parse each JSONL line; keep records where `record.get("agent") == "aider"`
- For each record, parse `record.get("started_at")` as ISO datetime
- Sum `(record.get("input_tokens") or 0) + (record.get("output_tokens") or 0)` for records within `cur_5h` range and `cur_7d` range
- Count runs (sessions) in each range

Return:

```python
return {
    "agent": "aider",
    "limits_estimated": True,
    "quota_source": "run_log",
    "window_5h": {
        "tokens": sum_5h,
        "limit": lim_5h,
        "pct": _pct(sum_5h, lim_5h),
        "remaining_pct": _rem(sum_5h, lim_5h),
        "sessions": runs_5h,
        "reset": midnight_label,
        "resets_at_unix": None,
        "window_minutes": 300,
        "display_line": f"{_fmt_tok(sum_5h)} / {_fmt_tok(lim_5h)} · {runs_5h} runs",
    },
    "window_7d": {
        "tokens": sum_7d,
        "limit": lim_7d,
        "pct": _pct(sum_7d, lim_7d),
        "remaining_pct": _rem(sum_7d, lim_7d),
        "sessions": runs_7d,
        "reset": weekly_reset_label,
        "resets_at_unix": None,
        "window_minutes": 10080,
        "display_line": f"{_fmt_tok(sum_7d)} / {_fmt_tok(lim_7d)} · {runs_7d} runs",
    },
    "aux": {
        "title": "DeepSeek Usage",
        "value_line": f"{_fmt_tok(sum_7d)} tokens this week",
        "sub_line": f"{runs_7d} runs",
        "reset": weekly_reset_label,
        "pct": _pct(sum_7d, lim_7d),
    },
}
```

Note: `_fmt_tok`, `_pct`, `_rem`, `midnight_label`, `weekly_reset_label`, `lim_5h`, `lim_7d` are all already defined in `compute_windows()` before the codex block — reuse them.

### Step 3 — Verify

```python
import sys; sys.path.insert(0, 'runner')
from usage_reader import compute_windows
w = compute_windows('aider')
assert w['agent'] == 'aider'
assert 'tokens' in w['window_5h']
assert 'tokens' in w['window_7d']
print('PASS:', w['window_5h']['display_line'], '|', w['window_7d']['display_line'])
```

- [x] Step 1 done — `"aider"` added to `DEFAULT_LIMITS`
- [x] Step 2 done — `compute_windows("aider")` reads `run_log.jsonl`, filters by agent, returns correct shape
- [x] Step 3 passes — verified: `PASS 5h: 0 / 10.0M · 0 runs | 7d: 0 / 50.0M · 0 runs`

---

## Key Constraints

- DeepSeek key never hardcoded — env only (`DEEPSEEK_API_KEY`)
- `aider --no-git` always in direct dispatch; symphony worktree is deferred
- Run status closed set unchanged: `running`, `success`, `failed`, `error`, `timeout`, `sent`, `archived`
- No new dependencies in `runner/` — aider CLI must already be installed in env

## Files Touched

| File | Change |
|------|--------|
| `runner/app.py` | `_ai_cli`, `_ai_command`, `_agent_model`, `_parse_agent_output`, regex, validation sets, comment body |
| `runner/templates/index.html` | 3-way toggle, issue modal, card tag |
| `symphony/` | deferred — not touched in P7 |
| `CLAUDE.md` | env var table |
| `AGENTS.md` | repo map |
| `docs/adr/0002-*.md` | new |
