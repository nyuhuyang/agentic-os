# ADR-0001: Linear Issues as Primary Board Entity

**Status:** Accepted  
**Date:** 2026-05-07

## Context

The original board displayed skill run records from `run_log.jsonl` as primary cards. Symphony's orchestrator uses Linear issues as the primary work unit and dispatches agents against them. Agentic-os needs to choose between these two models.

## Decision

Linear issues are the source of truth for what work exists and what state it is in. The job board renders Linear issues as primary cards. `run_log.jsonl` becomes a local execution audit log, not the board's data source. Board only renders run records that carry a `linear_issue_id`.

## Rationale

- Symphony already proved this model works; porting it avoids reinventing issue tracking UI.
- Linear provides triage, prioritization, labels, and history for free — rebuilding these in `run_log.jsonl` would be large scope.
- Run records are ephemeral execution artifacts; issues are durable work items. Conflating them added complexity without benefit.

## Consequences

- Legacy run records (no `linear_issue_id`) are hidden from the board. Retained in file for audit.
- `WORKFLOW.md` at the agentic-os root is required to configure Linear connection.
- Human Review column is board-only: failed runs are not pushed back to Linear (issue stays `In Progress` in Linear until human resolves it on the board).
- Skill selection becomes AI-driven: a routing Claude call selects the skill per issue rather than explicit user click.
- Board cannot function without a Linear connection configured. Offline mode is out of scope.
