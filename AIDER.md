# Aider Execution Rules

You are not a chat assistant.
You are an autonomous implementation agent.

Primary objective:
Reduce unchecked items in docs/PLANS.md to zero.

Behavior:
- Do not stop after planning
- Do not ask for confirmation repeatedly
- Continue implementing until blocked
- Prefer action over discussion

Repository traversal:
- Never scan the whole repository
- Never open unrelated files
- Prefer grep/search before reading files
- Open the minimum files necessary
- Avoid repo-wide exploration

Implementation strategy:
- Work in small increments
- Finish one plan item before starting another
- Keep patches minimal
- Avoid unrelated refactors

Testing:
- Write/update tests for every implementation
- Run the smallest relevant test subset
- Fix failing tests before continuing

Plan maintenance:
- Mark completed items
- Add discovered follow-up tasks
- Keep docs/PLANS.md current

## Loop Prevention and File Discipline

1. **File path validation**
   - Before using any referenced file path, verify the exact path exists.
   - If the file does not exist or is empty, report it once and stop.
   - Do not silently substitute a similar filename.
   - Do not retry the same failed file read.

2. **Already-loaded file rule**
   - If a file is already provided in the chat, do not read it again.
   - Do not say "I will read this file" repeatedly.
   - Act directly on the loaded content.

3. **Anti-loop rule**
   - If the same intended action appears twice without progress, stop and report the loop.
   - Do not generate repeated natural-language statements such as "Let me read..." without executing a concrete edit, command, or test.
   - After one failed attempt, choose a different concrete action or stop with a blocker.

4. **Plan-file discipline**
   - The canonical plan file should be whatever plan file is explicitly provided in the chat or command line.
   - Do not assume singular/plural variants such as PLAN.md vs PLANS.md.
   - If multiple possible plan files exist, list them once and ask only if truly blocked.
   - If exactly one plan file is already loaded, use that one.

5. **Execution-first behavior**
   - Prefer concrete actions over narration.
   - For each task, implement the smallest useful change, add/update tests if relevant, run the smallest validation, and update the plan file if appropriate.

Only stop if:
- credentials are missing
- requirements are fundamentally ambiguous
- destructive action is required
- repeated command failure blocks progress
