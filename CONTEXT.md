# Domain Context — AgenticOS Job Board

## Glossary

### Run
A single execution of a skill, identified by a unique `run_id` (UUID). Always linked to a Linear Issue via `linear_issue_id`. Recorded in `run_log.jsonl`. Status reflects local execution state (see Run Status).

### Linear Issue
The primary work unit. Polled from Linear GraphQL. Rendered as the primary card type on the job board. Source of truth for WHAT work exists and WHAT state it is in.

### Run Status (local)
The closed set of values recorded in `run_log.jsonl`. Reflects local execution state, not Linear state. Values:

| Status | Board Column |
|--------|-------------|
| `sent` | Backlog |
| `todo` | Todo |
| `running` | In Progress |
| `failed`, `error`, `timeout`, `stalled` | Human Review |
| `rework` | Hidden: Rework |
| `merging` | Hidden: Merging |
| `success` | Hidden: Done |
| `cancelled` | Hidden: Canceled |
| `duplicate` | Hidden: Duplicated |

### Linear State → Board Column Mapping

| Linear State | Board Column | Run Status |
|-------------|-------------|------------|
| Backlog | Backlog | `sent` |
| Todo | Todo | `todo` |
| In Progress (no active run) | Todo | `todo` + "dispatch pending" badge |
| In Progress (active run) | In Progress | `running` |
| Done | Hidden: Done | `success` |
| Canceled | Hidden: Canceled | `cancelled` |
| Duplicate | Hidden: Duplicated | `duplicate` |

`Rework` and `Merging` are board-only states with no Linear equivalent.

### Human Review (board-only)
A board column holding runs with status `failed`, `error`, `timeout`, or `stalled`. Not reflected back to Linear — the Linear issue stays `In Progress` until a human resolves it on the board. Resolution (retry or cancel) then pushes a new state to Linear.

### Skill Selection
When a Linear issue enters `In Progress`, a single Claude routing call reads the issue title + description alongside the skill registry and returns the best-matching skill name. The result is stored as `selected_skill` on the run record. Human override is possible before dispatch confirms.

### Dispatch (semi-auto)
`In Progress` Linear issues auto-dispatch on the next poll cycle. `Todo` issues sit on the board until manually dragged to In Progress. "Semi-auto" means: human controls WHEN, AI controls WHICH skill.

### Attempt
Integer field on run records. `0` = first attempt. Each retry increments and writes a new record with `attempt+1` and `parent_run_id` pointing to the original `run_id`.

### Stall
A run in `running` state with no `run_progress` SocketIO event for `STALL_TIMEOUT_S` (default 300s). Auto-transitions to `stalled` status (not `failed` — distinct triage path). Mapped to Human Review column.

### Active States
Linear states configured in `WORKFLOW.md` under `tracker.active_states` (e.g. `Todo`, `In Progress`). Issues in these states are eligible for polling and dispatch.

### Terminal States
Linear states configured under `tracker.terminal_states` (e.g. `Done`, `Canceled`, `Duplicate`). Issues in these states are shown in hidden board columns and are not re-dispatched.

### WORKFLOW.md
Single config file at agentic-os root. YAML front matter. Controls tracker connection, polling interval, and agent backend. Same format as Symphony.

```yaml
tracker:
  kind: linear
  api_key: $LINEAR_API_KEY
  project_slug: "<slug>"
  active_states:
    - Todo
    - In Progress
  terminal_states:
    - Done
    - Canceled
    - Duplicate
polling:
  interval_ms: 5000
agent:
  backend: claude  # or codex
```

### run_log.jsonl
Append-only local audit log. New fields added for Linear integration: `linear_issue_id`, `attempt`, `parent_run_id`, `selected_skill`. Board only renders records that have a `linear_issue_id`. Legacy records (no `linear_issue_id`) remain in file but are hidden from the board.

### Legacy Run
A run record in `run_log.jsonl` without a `linear_issue_id`. Produced before the Linear-as-source-of-truth pivot. Hidden from the board; retained for audit only.
