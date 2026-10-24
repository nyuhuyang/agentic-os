---
status: draft
created: 2026-10-24
ticket: none yet (split out of AGE-126; needs its own Linear issue)
---

# Task: Decide the confidentiality label for the analysis projects

## Why this is a separate plan

AGE-126 is about running more agents without spending more human attention. Whether a
data-analysis project should be labelled `confidential` is a data-egress policy decision with its
own risk, its own owner approval, and no dependency on fleet mechanics. It only ended up inside
AGE-126 because `dsh` used to be refused for confidential projects; AGE-139 removed that coupling,
so the two questions can be decided independently.

## The question

Several data-analysis projects carry the `confidential` label. The owner says the patient data is
simulated and the real data lives on a server, so the label may be protecting nothing. Should
these projects stay confidential, and if not, exactly what changes?

## Facts (2026-10-24)

- AGE-139 (on main) lets `dsh` run confidential projects through `runner/dsh_confine.py`. The old
  refusal in `runner/project_runs.py` is gone. What staying confidential costs now is usability,
  not eligibility: stock dsh profile only, `tool-web` / `tool-fs` / `tool-working-directory`
  disabled, no session resume, macOS only, dsh `>= 0.2.1-rc.2`.
- Confidentiality is sticky: `_ticket_confidential` merges the registry flag, the worktree sidecar
  (`~/.agentic-os/worktrees/<key>/.meta/<ident>.json`), the durable binding
  (`state/issue_bindings.json`) and run history; any `True` wins. Editing `projects.yaml` only
  changes new tickets.
- The flag controls six surfaces, not just the sandbox: dsh/Claude/Codex confinement, Linear egress
  (confidential tasks are local-only, AGE-127), the tracker-comment template, run-record text,
  `ai_memory` (skipped when confidential, AGE-137), and the verify/git Seatbelt.
- Codewhale is a possible alternative harness whose macOS/Linux sandbox has a network dimension
  (`sandbox_network_access`; Seatbelt on macOS, bubblewrap on Linux). It is a backend project, not
  a way to relabel.

## Options

A. **Keep confidential, use dsh through AGE-139.**
   - Gain: no Linear or memory egress; tools confined; no code change.
   - Cost: no native file tools, no resume, stock profile only, macOS only.

B. **Flip these projects to non-confidential** (registry plus sidecar plus durable binding).
   - Gain: dsh native sandbox, full tool set, resume; one special case fewer.
   - Cost: titles and comments reach Linear, summaries reach `ai_memory`, shell network is open;
     old tickets need a state edit that the owner must approve.

C. **Add a middle tier** (for example `sensitive`: external model allowed, tools confined, Linear
   denied, resume allowed).
   - Not a flag flip; needs a schema and policy change. Only if A and B both fail.

D. **Switch the backend to codewhale.**
   - Closes the sandbox gap natively, but it is a backend integration project, not a labelling fix.

## Decision criteria

- Does any repository actually contain records: `tests/fixtures`, `*.csv`, `*.ipynb` outputs,
  logs, screenshots?
- Is the code itself under an NDA even when the data is not?
- May project and ticket titles appear in Linear?

## Open questions

- Which projects are labelled confidential today? (`projects.yaml` is gitignored.)
- Which of them already have runs whose sidecar or binding would stay sticky?
- Is "confidential" here about patient data, about client code, or about a contract?

## Acceptance criteria

- [ ] Every analysis project's label matches what the repository holds and where the data lives.
- [ ] No stale sidecar or binding keeps a ticket confidential against the decision.
- [ ] If flipped, a new ticket in each project launches `dsh` without a refusal.
- [ ] AGE-126 no longer decides anything about confidentiality.

## Verification

- [ ] `runner/projects.py list` shows the intended flags.
- [ ] One new ticket per flipped project runs on `dsh` and finishes.
- [ ] No code change is expected. If option C is chosen, it becomes its own build plan.

## Risks and trade-offs

- Flipping widens egress. If a repository later receives real data, the flag has to come back;
  stickiness helps in that direction but not in reverse.
- Cleaning sidecars and bindings edits `state/`, which is normally hands-off.
- Codewhale is young (v0.10.x); a backend swap imports its own churn and a new protocol parser.
