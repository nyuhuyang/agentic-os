# P20 — Dashboard Fixes & Token Panel Redesign

## Status: Active

> **Code changes: NONE made yet.** All items below are pending. Check box when done.

---

## Task Checklist

### Track 1 — Fix Empty Kanban Board
- [x] **1-A** `dashboard-server.ts`: add `listLinearIssues?` + `updateLinearIssueState?` + `createLinearIssue?` + `transcribeAudio?` + `getIssueHistory?` to `DashboardServerHost`
- [x] **1-B** `dashboard-server.ts`: add `LinearIssuePayload` + `RunAttemptEntry` types
- [x] **1-C** `dashboard-server.ts`: add `GET /api/v1/linear/issues` route
- [x] **1-D** `dashboard-server.ts`: add `PATCH /api/v1/linear/issues/:id` route (accepts `state_name`, `title`, `description`)
- [x] **1-E** `runtime-host.ts`: implement `listLinearIssues()` using `tracker.fetchIssuesByStates(ALL_STATES)`
- [x] **1-F** `runtime-host.ts`: implement `updateLinearIssueState()` via GraphQL mutation
- [x] **1-G** `useLinearIssues.ts`: URL changed → `/api/v1/linear/issues`
- [ ] **1-H** `useLinearIssues.ts`: allow `created_at` / `updated_at` to be `string | null` — *not verified*
- [x] **1-I** `KanbanBoard.tsx`: PATCH URL fixed → `/api/v1/linear/issues/:id`
- [ ] **1-J** `symphony-ts`: run `pnpm build` — **must do before testing**

### Track 2 — Token Panel (3-Model Usage Grid)
- [x] **2-A** `types/api.ts`: `WindowEntry`, `WindowsAgentData`, `WindowsAllResponse`, `DeepSeekUsage` fixed — `DeepSeekUsage.balance.is_available` + `balance.balance_cny` (actual API shape: nested under `balance`, not flat)
- [x] **2-B** `client.ts`: `fetchWindowsAll()`, `fetchDeepSeekUsage()`, `fetchUsageAll()`, `postDeepSeekRefresh()`, `createLinearIssue()` added
- [x] **2-C** `useIssues.ts`: `useWindowsAll()`, `useDeepSeekUsage()`, `useUsageAll()` added
- [x] **2-D** New file `UsageGrid.tsx`: table (Claude/Codex/DeepSeek) × (5h/weekly/monthly); uses `useWindowsAll` + `useDeepSeekUsage`; CSS classes added to App.css
- [x] **2-E** `TokenPanel.tsx`: uses `<UsageGrid />` confirmed
- [x] **2-F** Tokens button: in `App.tsx` — `tokensOpen` toggle + "Tokens" button rendered
- [x] **2-G** `App.tsx`: `tokensOpen` state, `TokenPanel` rendered as overlay when open

### Track 3 — Create Issue from Board
- [x] **3-A** `dashboard-server.ts`: `createLinearIssue?` + `CreateIssueInput` added
- [x] **3-B** `dashboard-server.ts`: `POST /api/v1/linear/issues` route added
- [x] **3-C** `runtime-host.ts`: `createLinearIssue()` implemented (line 416)
- [x] **3-D** `client.ts`: `createLinearIssue()` added
- [x] **3-E** `CreateIssueForm.tsx`: exists, has title/description/submit/cancel
- [x] **3-F** `KanbanBoard.tsx`: `+` button on Todo column, `CreateIssueForm` shown inline
- [x] **3-G** `App.css`: `.create-issue-form` + `.kanban-column-add-btn` confirmed present

### Track 4 — Embedded Terminal Tab
- [x] **4-A** `symphony-ts/package.json`: `ws` added ✅; `node-pty` **NOT added** — terminal uses `child_process.spawn` instead (basic pipe, not full PTY; interactive apps like vim won't work)
- [x] **4-B** `terminal-server.ts`: exists — uses `child_process.spawn` + `ws`, streams at `/api/v1/terminal`
- [x] **4-C** `dashboard-server.ts`: imports and calls `attachTerminalWebSocket`
- [ ] **4-D** `runtime-host.ts`: pass `workdir` when starting dashboard — *not verified*
- [x] **4-E** `vite.config.ts`: `/api` proxy updated with `ws: true`
- [x] **4-F** `ui/package.json`: `xterm` + `xterm-addon-fit` added
- [x] **4-G** `TerminalPanel.tsx`: exists — xterm.js + WebSocket + CLEAR button
- [x] **4-H** `App.tsx`: `"terminal"` tab added, `<TerminalPanel />` rendered when active

### Track 5 — Kanban Card Redesign + Cancelled Archive
- [x] **5-A** `KanbanBoard.tsx`: now 4 columns only (backlog, todo, running, done); rework/merging removed
- [x] **5-B** `AgentKanbanCard.tsx`: has `timeAgo`, `formatTok`, dispatch buttons — *model chip (MODEL · X) not confirmed, needs visual check*
- [x] **5-C** `AgentKanbanCard.tsx`: `onDispatch?(agent)` prop wired to dispatch buttons
- [x] **5-D** `ui/src/utils/format.ts` exists; `AgentKanbanCard` has inline `formatTok` + `timeAgo`
- [x] **5-E** `TrashPanel.tsx`: now accepts `LinearIssue[]`
- [x] **5-F** `App.tsx`: `trashOpen` state, `TrashPanel` at App level as overlay
- [ ] **5-G** `Header.tsx`: still has old simple header — **no trash icon, no total count, no token button** in `Header.tsx` component itself (currently all wired in `App.tsx` directly)

### Track 6 — Issue Detail Panel Redesign
- [x] **6-A** `DetailPanel.tsx`: state badge + identifier in header
- [x] **6-C** `DetailPanel.tsx`: `linearIssue` prop + "◆ LINEAR ISSUE" section with link
- [x] **6-D** `dashboard-server.ts` PATCH accepts `title` + `description`; `runtime-host.ts` impl done
- [x] **6-H** `DetailPanel.tsx`: "PREVIOUS ATTEMPTS (N)" section exists (but returns [] — see 6-Q)
- [x] **6-J** `DetailPanel.tsx`: prompt/output tabs exist
- [x] **6-K** `DetailPanel.tsx`: COMMENT/FEEDBACK section with STT mic button
- [x] **6-O** `DetailPanel.tsx`: "✓ Approve → Done" + 3 agent buttons in bottom action bar

### Track 7 — Issue Detail: Run History from Flask (NEW)

**Root cause**: `symphony-ts /api/v1/issues/:id/history` returns `[]` — no historical data. Real history is in Flask app.py's JSONL run log.

**Backend already done (Claude)**:
- [x] **7-A** `runner/app.py`: `/api/runs` now accepts `?linear_issue_id=<uuid>` filter (3-line change)
- [x] **7-B** `vite.config.ts`: `/api/runs` proxied → port 8510

**Frontend — DeepSeek to implement**:

- [ ] **7-C** `types/api.ts`: add `RunRecord` interface:
  ```ts
  export interface RunRecord {
    run_id: string
    linear_issue_id: string | null
    status: string      // 'done' | 'review' | 'failed' | 'archived' | 'running'
    agent: string | null
    model: string | null
    attempt: number
    started_at: string | null
    duration_s: number | null
    duration: string | null
    when: string | null
    prompt: string | null
    output: string | null
    error: string | null
  }
  ```

- [ ] **7-D** `api/client.ts`: add:
  ```ts
  export async function fetchRunsByIssue(linearIssueId: string): Promise<RunRecord[]> {
    const res = await fetch(`/api/runs?linear_issue_id=${encodeURIComponent(linearIssueId)}&limit=20`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return res.json()
  }
  ```

- [ ] **7-E** `hooks/useIssues.ts`: add:
  ```ts
  export function useIssueRuns(linearIssueId: string | null | undefined) {
    return useQuery<RunRecord[]>({
      queryKey: ['runs', 'issue', linearIssueId],
      queryFn: () => fetchRunsByIssue(linearIssueId!),
      enabled: !!linearIssueId,
      refetchInterval: 15_000,
      staleTime: 10_000,
    })
  }
  ```

- [ ] **7-F** `DetailPanel.tsx`: replace `prevAttempts` (from symphony-ts `/history`) with `useIssueRuns(linearIssue?.id)`. Render collapsible list matching Flask UI:
  - Each row: `[STATUS BADGE] Attempt N · <date> · <duration> · <agent>/<model>`
  - Click → expand to show PROMPT and OUTPUT sections (truncated to ~300 chars, "show more" button)
  - Status badge colors: `done`=green, `review`=purple, `failed`=red, `running`=yellow
  - Sort newest first

  **CSS classes to add** (match Flask style):
  ```css
  .attempt-item { border: 1px solid hsl(var(--border)); border-radius: 4px; margin-bottom: 5px; overflow: hidden; }
  .attempt-header { padding: 7px 12px; cursor: pointer; display: flex; align-items: center; gap: 8px; font-size: 11px; color: hsl(var(--muted-foreground)); background: hsl(var(--background)); }
  .attempt-header:hover { color: hsl(var(--foreground)); background: hsl(0,0%,11%); }
  .attempt-toggle { margin-left: auto; font-size: 9px; }
  .attempt-body { padding: 4px 12px 10px; background: hsl(var(--card)); }
  .attempt-sub-label { font-size: 9px; color: hsl(var(--muted-foreground)); letter-spacing: 1.5px; text-transform: uppercase; margin: 8px 0 3px; }
  .attempt-content { font-size: 11px; color: hsl(var(--foreground)); background: hsl(var(--background)); border-radius: 3px; padding: 7px 10px; white-space: pre-wrap; word-break: break-word; max-height: 180px; overflow-y: auto; line-height: 1.45; }
  .attempt-badge { font-size: 9px; font-weight: 700; letter-spacing: 0.5px; padding: 1px 5px; border-radius: 3px; text-transform: uppercase; }
  .attempt-badge.done { background: #1a3a1a; color: #3fb950; }
  .attempt-badge.review { background: #2a1a3a; color: #a371f7; }
  .attempt-badge.failed { background: #3a1a1a; color: #f85149; }
  .attempt-badge.running { background: #3a2a1a; color: #d29922; }
  ```

  Placement: put the collapsible history **above** the Prompt/Output/Log/Feedback tabs, replacing the current `prevAttempts` section that uses symphony-ts data.

---

## Overview

Six tracks — all pending:
1. **Track 1** — Fix empty board (root cause: missing `/api/v1/linear/issues` route in symphony-ts)
2. **Track 2** — Token panel: 3-model usage grid (Claude/Codex/DeepSeek, 5h/weekly/monthly)
3. **Track 3** — Create issue directly from Todo column
4. **Track 4** — Embedded terminal tab (xterm.js + node-pty)
5. **Track 5** — Card redesign + cancelled archive panel
6. **Track 6** — Issue detail panel full redesign

---

## Track 1: Kanban Board — Fix Empty Columns

### Root Cause

The frontend hook `ui/src/hooks/useLinearIssues.ts` fetches `/api/linear/issues`.  
The actual backend is `symphony-ts` (started via `start.sh` → `node symphony-ts/dist/src/cli/main.js`).  
`symphony-ts/src/observability/dashboard-server.ts` has **no** `/api/linear/issues` route → 404 → empty board.

The same problem affects the PATCH call in `KanbanBoard.tsx` (drag-to-done state update) which calls `/api/linear/issues/:id` — also missing.

### Fix: 4 files to change

---

#### File 1: `prototypes/symphony-ts/src/observability/dashboard-server.ts`

**A. Extend `DashboardServerHost` interface** (around line 114):

```ts
export interface DashboardServerHost {
  getRuntimeSnapshot(): RuntimeSnapshot | Promise<RuntimeSnapshot>;
  getIssueDetails(issueIdentifier: string): Promise<IssueDetailResponse | null>;
  requestRefresh?(): Promise<RefreshResponse>;
  cancelIssue?(issueIdentifier: string): Promise<CancelResponse>;
  dispatchIssue?(issueIdentifier: string): Promise<{ ok: boolean }>;
  getTokenUsage?(period: "5h" | "weekly"): Promise<TokenUsageResponse>;
  subscribeToSnapshots?(listener: () => void): () => void;

  // NEW — add these:
  listLinearIssues?(teamId?: string): Promise<LinearIssuePayload[]>;
  updateLinearIssueState?(issueId: string, stateName: string): Promise<{ ok: boolean }>;
}
```

**B. Add `LinearIssuePayload` type** (after existing interfaces, before the function):

```ts
export interface LinearIssuePayload {
  id: string;
  identifier: string;
  title: string;
  description: string | null;
  priority: number | null;
  state: string;
  url: string | null;
  labels: string[];
  assignee: string;
  team_id: string;
  team_key: string;
  team_name: string;
  created_at: string | null;
  updated_at: string | null;
}
```

**C. Add two new routes** inside the request handler (after the existing `/api/v1/tokens/...` block, before the generic `/api/v1/` catch-all around line 354):

```ts
// GET /api/v1/linear/issues[?team_id=...]
if (url.pathname === "/api/v1/linear/issues" && request.method === "GET") {
  if (!options.host.listLinearIssues) {
    writeJsonError(response, 501, "not_implemented", { message: "listLinearIssues not available." });
    return;
  }
  const teamId = url.searchParams.get("team_id") ?? undefined;
  try {
    const issues = await options.host.listLinearIssues(teamId);
    writeJson(response, 200, issues);
  } catch (err) {
    writeJsonError(response, 500, "internal_error", { message: toErrorMessage(err) });
  }
  return;
}

// PATCH /api/v1/linear/issues/:id  { state_name: string }
const linearPatchMatch = url.pathname.match(/^\/api\/v1\/linear\/issues\/([^/]+)$/);
if (linearPatchMatch && request.method === "PATCH") {
  const issueId = decodeURIComponent(linearPatchMatch[1]);
  if (!options.host.updateLinearIssueState) {
    writeJsonError(response, 501, "not_implemented", { message: "updateLinearIssueState not available." });
    return;
  }
  let body: unknown;
  try {
    body = await readJsonBody(request);
  } catch {
    writeJsonError(response, 400, "bad_request", { message: "Invalid JSON body." });
    return;
  }
  const stateName = (body as Record<string, unknown>)?.state_name;
  if (typeof stateName !== "string") {
    writeJsonError(response, 400, "bad_request", { message: "state_name required." });
    return;
  }
  try {
    const result = await options.host.updateLinearIssueState(issueId, stateName);
    writeJson(response, 200, result);
  } catch (err) {
    writeJsonError(response, 500, "internal_error", { message: toErrorMessage(err) });
  }
  return;
}
```

> Note: `readJsonBody` and `writeJson`/`writeJsonError` helpers already exist in this file. Reuse them.

---

#### File 2: `prototypes/symphony-ts/src/orchestrator/runtime-host.ts`

**A. Implement `listLinearIssues`** in `OrchestratorRuntimeHost` class:

```ts
async listLinearIssues(_teamId?: string): Promise<import("../observability/dashboard-server.js").LinearIssuePayload[]> {
  const ALL_STATES = [
    "Backlog", "Todo", "In Progress", "In Review",
    "Rework", "Merging", "Done", "Canceled", "Cancelled", "Duplicate",
  ];
  const issues = await this.tracker.fetchIssuesByStates(ALL_STATES);
  return issues.map((issue) => ({
    id: issue.id,
    identifier: issue.identifier,
    title: issue.title,
    description: issue.description ?? null,
    priority: issue.priority ?? null,
    state: issue.state,
    url: issue.url ?? null,
    labels: issue.labels,
    assignee: "",         // not in Issue model; placeholder
    team_id: "",
    team_key: "",
    team_name: "",
    created_at: issue.createdAt ?? null,
    updated_at: issue.updatedAt ?? null,
  }));
}
```

**B. Implement `updateLinearIssueState`**:

The `IssueTracker` interface doesn't have a state-update method. Two options:
- **Option A (simpler)**: Cast `this.tracker` to `LinearTrackerClient` and call `executeRawGraphql` with a mutation
- **Option B (cleaner)**: Add `updateIssueState?(issueId: string, stateName: string): Promise<void>` to `IssueTracker` interface in `src/tracker/tracker.ts` and implement in `LinearTrackerClient`

**Recommended: Option A for speed.** Add this mutation inline in runtime-host:

```ts
async updateLinearIssueState(issueId: string, stateName: string): Promise<{ ok: boolean }> {
  // LinearTrackerClient has executeRawGraphql — cast if needed
  const tracker = this.tracker as import("../tracker/linear-client.js").LinearTrackerClient;
  if (!tracker.executeRawGraphql) {
    return { ok: false };
  }

  // Step 1: find the state ID for stateName in this team
  // Linear requires state ID, not state name, for IssueUpdate mutation.
  // Query workflow states filtered by name:
  const statesQuery = `
    query($name: String!) {
      workflowStates(filter: { name: { eq: $name } }) {
        nodes { id name }
      }
    }
  `;
  const statesData = await tracker.executeRawGraphql(statesQuery, { name: stateName }) as any;
  const stateId = statesData?.workflowStates?.nodes?.[0]?.id;
  if (!stateId) return { ok: false };

  // Step 2: update issue
  const mutation = `
    mutation($issueId: String!, $stateId: String!) {
      issueUpdate(id: $issueId, input: { stateId: $stateId }) {
        success
      }
    }
  `;
  const result = await tracker.executeRawGraphql(mutation, { issueId, stateId }) as any;
  return { ok: result?.issueUpdate?.success === true };
}
```

> Check `LinearTrackerClient.executeRawGraphql` signature — it takes `(query, variables)` and requires the private `apiKey`. It's currently private. If access is blocked, add a public `updateIssueState(issueId, stateName)` method to `LinearTrackerClient` instead and call it directly.

---

#### File 3: `prototypes/agentic-os/ui/src/hooks/useLinearIssues.ts`

Change fetch URL from `/api/linear/issues` to `/api/v1/linear/issues`:

```ts
// Before:
const res = await fetch(`/api/linear/issues${params}`)

// After:
const res = await fetch(`/api/v1/linear/issues${params}`)
```

Also update the `LinearIssue` type — `created_at` and `updated_at` should allow `null`:
```ts
created_at: string | null
updated_at: string | null
```

---

#### File 4: `prototypes/agentic-os/ui/src/components/KanbanBoard.tsx`

Change PATCH URL from `/api/linear/issues/:id` to `/api/v1/linear/issues/:id`:

Around line where `fetch('/api/linear/issues/...')` is called in `handleDragEnd`:
```ts
// Before:
fetch(`/api/linear/issues/${encodeURIComponent(id)}`, {

// After:
fetch(`/api/v1/linear/issues/${encodeURIComponent(id)}`, {
```

---

#### Build step (after code changes)

Symphony-ts must be rebuilt before `start.sh` picks up changes:
```bash
cd /Users/yanghu/Documents/AI_Workspace/prototypes/symphony-ts
pnpm build   # or: npx tsc
```

---

## Track 2: Token Panel Redesign

### Goal

Replace the current `TokenPanel.tsx` (Codex-only table) with a 3-row usage grid matching the reference screenshot layout.

### Reference Layout

```
          5-HOUR            WEEKLY            TODAY / MONTHLY
Claude    86% ████░         91% █████░        0 tokens · 22h54m
Codex     99% █████░        43% ███░          16,549 tok · 4d16h
DeepSeek  ¥0.00/¥5.00       ¥20.11/¥50.00    ¥20.11/¥200.00
```

Each cell shows:
- Large % remaining (color: green ≥60%, yellow 30-59%, red <30%)
- Horizontal progress bar (filled = used, empty = remaining)
- Detail line: `tokens / limit · N sessions` (Claude/Codex) or `¥spent / ¥limit` (DeepSeek)
- Time remaining badge top-right

### Data Sources

**Claude & Codex** → `GET /api/windows/all`
Response shape (per agent):
```json
{
  "claude": {
    "window_5h": { "tokens": 1315911, "limit": 9350000, "sessions": 22, "remaining_pct": 86, "tokens_fmt": "1.3M", "limit_fmt": "9.4M" },
    "window_7d": { "tokens": 14745446, "limit": 159000000, "sessions": 192, "remaining_pct": 91 },
    "aux": { "time_remaining_5h": "3h48m", "time_remaining_7d": "4d16h" }
  },
  "codex": { ... }
}
```

**DeepSeek** → `GET /api/usage` (field: `result.deepseek`)
Response shape:
```json
{
  "deepseek": {
    "available": true,
    "balance_cny": 179.89,
    "total_cost_cny": 20.11,
    "window_5h_cost_cny": 0.00,
    "window_7d_cost_cny": 20.11,
    "window_30d_cost_cny": 20.11
  }
}
```
DeepSeek budgets (from config/defaults): 5h=¥5, weekly=¥50, monthly=¥200.

> DeepSeek data is cached in `~/.deepseek/usage.json`. Refresh via `POST /api/deepseek/refresh`. Frontend should call refresh on mount + every 5 min, show "last updated Xm ago" timestamp.

### Files to Change

#### New file: `ui/src/components/UsageGrid.tsx`

New component that renders the 3×3 grid. Props:
```ts
interface UsageGridProps {
  windowsData: WindowsAllResponse | null   // from /api/windows/all
  usageData: UsageResponse | null          // from /api/usage
  onDeepSeekRefresh: () => void
  lastDeepSeekRefresh: Date | null
}
```

Each cell is a `UsageCell` sub-component:
```ts
interface UsageCellProps {
  label: string           // "5-HOUR" | "WEEKLY" | "MONTHLY" | "TODAY TOKENS"
  pct: number             // 0-100 remaining %
  detailLine: string      // e.g. "1.3M / 9.4M · 22 sessions" or "¥0.00 / ¥5.00"
  timeRemaining?: string  // e.g. "3h48m"
  isCost?: boolean        // DeepSeek row: show ¥ styling instead of %
}
```

Color logic for % badge:
- ≥60%: `#3fb950` (green)
- 30-59%: `#d29922` (yellow)
- <30%: `#f85149` (red)

#### New file: `ui/src/api/client.ts` additions

Add two fetch functions:
```ts
export async function fetchWindowsAll(): Promise<WindowsAllResponse> {
  const res = await fetch('/api/windows/all')
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

export async function fetchUsageAll(): Promise<UsageResponse> {
  const res = await fetch('/api/usage')
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

export async function postDeepSeekRefresh(): Promise<void> {
  await fetch('/api/deepseek/refresh', { method: 'POST' })
}
```

#### New file: `ui/src/types/api.ts` additions

Add response types:
```ts
export interface WindowEntry {
  tokens: number
  limit: number
  sessions: number
  remaining_pct: number
  tokens_fmt: string
  limit_fmt: string
  display_line: string
}

export interface WindowsAgentData {
  agent: string
  window_5h: WindowEntry
  window_7d: WindowEntry
  aux: { time_remaining_5h?: string; time_remaining_7d?: string }
}

export interface WindowsAllResponse {
  claude: WindowsAgentData
  codex: WindowsAgentData
  deepseek: WindowsAgentData
}

export interface DeepSeekUsage {
  available: boolean
  balance_cny: number
  total_cost_cny: number
  window_5h_cost_cny: number
  window_7d_cost_cny: number
  window_30d_cost_cny: number
}

export interface UsageResponse {
  claude: unknown
  codex: unknown
  deepseek: DeepSeekUsage
}
```

#### Modified: `ui/src/hooks/useIssues.ts`

Add hooks:
```ts
export function useWindowsAll() {
  return useQuery<WindowsAllResponse>({
    queryKey: ['windows', 'all'],
    queryFn: fetchWindowsAll,
    refetchInterval: 60_000,
    staleTime: 30_000,
  })
}

export function useUsageAll() {
  return useQuery<UsageResponse>({
    queryKey: ['usage', 'all'],
    queryFn: fetchUsageAll,
    refetchInterval: 300_000,
    staleTime: 60_000,
  })
}
```

#### Modified: `ui/src/components/TokenPanel.tsx`

Replace current implementation with `UsageGrid`:
```tsx
import { UsageGrid } from './UsageGrid.tsx'
import { useWindowsAll, useUsageAll } from '../hooks/useIssues.ts'

export function TokenPanel() {
  const { data: windowsData } = useWindowsAll()
  const { data: usageData } = useUsageAll()
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null)

  const handleRefresh = async () => {
    await postDeepSeekRefresh()
    setLastRefresh(new Date())
  }

  return (
    <div className="token-panel">
      <div className="token-panel-header">
        <h3>Usage</h3>
      </div>
      <UsageGrid
        windowsData={windowsData ?? null}
        usageData={usageData ?? null}
        onDeepSeekRefresh={handleRefresh}
        lastDeepSeekRefresh={lastRefresh}
      />
    </div>
  )
}
```

#### Modified: `ui/src/components/Header.tsx`

Add clickable token button that toggles `TokenPanel`:
```tsx
interface HeaderProps {
  connected: boolean
  onTokensClick: () => void
  tokensOpen: boolean
}
```

The token button shows a colored dot indicating worst health across all 3 models (green/yellow/red). Requires passing minimal health state down from `App.tsx` or computing it inside header via a lightweight hook.

Simplest approach: pass `tokenHealth: 'good' | 'warn' | 'critical'` as prop from `App.tsx` which computes it from `useWindowsAll`.

#### Modified: `ui/src/App.tsx`

- Add `tokensOpen` state
- Wire `onTokensClick` to `Header`
- Render `<TokenPanel>` conditionally when `tokensOpen` (as overlay panel or slide-in)

---

## Track 3: Create Issue from Board (+ Button on Todo Column)

### Goal

Add a `+` button to the **Todo** column header so issues can be created directly in the dashboard without opening Linear. AgenticOS is the primary coding interface — it must allow creating, not just receiving, work.

### UX Flow

1. User clicks `+` on Todo column header
2. Inline form appears at top of Todo column (or modal overlay)
3. Fields: **Title** (required), **Description** (optional)
4. Submit → creates issue in Linear via API → issue appears in Todo column
5. On success: close form, invalidate `linear-issues` query to refresh board

### Backend: New Route

**File: `prototypes/symphony-ts/src/observability/dashboard-server.ts`**

Add to `DashboardServerHost` interface:
```ts
createLinearIssue?(input: CreateIssueInput): Promise<{ ok: boolean; issueId?: string; identifier?: string }>;
```

Add type:
```ts
export interface CreateIssueInput {
  title: string;
  description?: string;
  teamId?: string;   // optional; host can use default team from config
}
```

Add route:
```ts
// POST /api/v1/linear/issues
if (url.pathname === "/api/v1/linear/issues" && request.method === "POST") {
  if (!options.host.createLinearIssue) {
    writeJsonError(response, 501, "not_implemented", { message: "createLinearIssue not available." });
    return;
  }
  let body: unknown;
  try { body = await readJsonBody(request); } catch {
    writeJsonError(response, 400, "bad_request", { message: "Invalid JSON." });
    return;
  }
  const input = body as CreateIssueInput;
  if (!input?.title) {
    writeJsonError(response, 400, "bad_request", { message: "title required." });
    return;
  }
  try {
    const result = await options.host.createLinearIssue(input);
    writeJson(response, 201, result);
  } catch (err) {
    writeJsonError(response, 500, "internal_error", { message: toErrorMessage(err) });
  }
  return;
}
```

> Place this block **before** the existing `GET /api/v1/linear/issues` block so the method check distinguishes them.

**File: `prototypes/symphony-ts/src/orchestrator/runtime-host.ts`**

Implement `createLinearIssue` in `OrchestratorRuntimeHost`:

```ts
async createLinearIssue(input: CreateIssueInput): Promise<{ ok: boolean; issueId?: string; identifier?: string }> {
  const tracker = this.tracker as import("../tracker/linear-client.js").LinearTrackerClient;
  if (!tracker.executeRawGraphql) return { ok: false };

  // Get team ID: prefer input.teamId, fall back to config
  const teamId = input.teamId ?? (this.config as any)?.tracker?.team_id ?? "";
  if (!teamId) return { ok: false };

  // Get "Todo" state ID for this team
  const stateQuery = `
    query($teamId: String!, $name: String!) {
      workflowStates(filter: { team: { id: { eq: $teamId } }, name: { eq: $name } }) {
        nodes { id name }
      }
    }
  `;
  const stateData = await tracker.executeRawGraphql(stateQuery, { teamId, name: "Todo" }) as any;
  const stateId = stateData?.workflowStates?.nodes?.[0]?.id;
  if (!stateId) return { ok: false };

  const mutation = `
    mutation($teamId: String!, $title: String!, $description: String, $stateId: String!) {
      issueCreate(input: { teamId: $teamId, title: $title, description: $description, stateId: $stateId }) {
        success
        issue { id identifier }
      }
    }
  `;
  const result = await tracker.executeRawGraphql(mutation, {
    teamId,
    title: input.title,
    description: input.description ?? null,
    stateId,
  }) as any;
  const created = result?.issueCreate;
  return {
    ok: created?.success === true,
    issueId: created?.issue?.id,
    identifier: created?.issue?.identifier,
  };
}
```

> If `executeRawGraphql` is private, add a public `createIssue(teamId, title, description, stateId)` method to `LinearTrackerClient` in `src/tracker/linear-client.ts` and call that instead.

### Frontend

**New file: `ui/src/components/CreateIssueForm.tsx`**

Inline form rendered at top of Todo column when `open=true`:

```tsx
interface CreateIssueFormProps {
  onSubmit: (title: string, description: string) => Promise<void>
  onCancel: () => void
}

export function CreateIssueForm({ onSubmit, onCancel }: CreateIssueFormProps) {
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!title.trim()) return
    setSubmitting(true)
    await onSubmit(title.trim(), description.trim())
    setSubmitting(false)
  }

  return (
    <form className="create-issue-form" onSubmit={handleSubmit}>
      <input
        autoFocus
        placeholder="Issue title"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        className="create-issue-title"
      />
      <textarea
        placeholder="Description (optional)"
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        className="create-issue-description"
        rows={2}
      />
      <div className="create-issue-actions">
        <button type="submit" disabled={!title.trim() || submitting}>
          {submitting ? 'Creating…' : 'Create'}
        </button>
        <button type="button" onClick={onCancel}>Cancel</button>
      </div>
    </form>
  )
}
```

**New function in `ui/src/api/client.ts`**:

```ts
export async function createLinearIssue(title: string, description?: string): Promise<{ ok: boolean; identifier?: string }> {
  const res = await fetch('/api/v1/linear/issues', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title, description }),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}
```

**Modified: `ui/src/components/Column.tsx` or `KanbanBoard.tsx`**

In `KanbanBoard.tsx`, add state:
```ts
const [creatingInTodo, setCreatingInTodo] = useState(false)
```

In the Todo column header render, add `+` button:
```tsx
// Inside kanban-column-header for col.key === 'todo':
{col.key === 'todo' && (
  <button
    className="kanban-column-add-btn"
    onClick={() => setCreatingInTodo(true)}
    title="Create issue"
  >
    +
  </button>
)}
```

Inside the Todo column body, at top (before the draggable items):
```tsx
{col.key === 'todo' && creatingInTodo && (
  <CreateIssueForm
    onSubmit={async (title, description) => {
      await createLinearIssue(title, description)
      setCreatingInTodo(false)
      queryClient.invalidateQueries({ queryKey: LINEAR_ISSUES_KEY })
    }}
    onCancel={() => setCreatingInTodo(false)}
  />
)}
```

> `queryClient` can be obtained via `useQueryClient()` hook in `KanbanBoard.tsx`. `LINEAR_ISSUES_KEY` is currently defined in `useLinearIssues.ts` — export it or re-fetch via the hook's `refetch`.

**CSS to add in `App.css`**:
```css
.create-issue-form { ... }   /* card-like styling matching AgentKanbanCard */
.kanban-column-add-btn { ... }   /* small + icon, top-right of header */
```

---

## DeepSeek Timing Note

DeepSeek cost data is **not real-time** — it reflects the last refresh of `~/.deepseek/usage.json`.  
Balance (`balance_cny`) comes from DeepSeek API when refreshed.  
Cost windows (`window_5h_cost_cny` etc.) are estimated from checkpoint files.  
Show "last updated: Xm ago" and a manual refresh button. Auto-refresh on panel open.  
This is acceptable — defer real-time streaming to a later task.

---

## Track 4: Embedded Terminal Tab

### Goal

Add a **Terminal** tab to the dashboard header nav (alongside Board / Tokens / History). Renders a full xterm.js terminal backed by a server-side PTY. Use case: deep multi-turn agent conversations and manual commands without leaving the dashboard.

Reference: screenshot shows bash shell with `.venv` activated, CLEAR button top-right.

### Why xterm.js + server PTY (not just a log viewer)

The terminal must be interactive — full stdin/stdout, arrow keys, Ctrl-C, etc. This requires:
- **Server side**: `node-pty` spawns a real PTY process (bash). Output streamed to browser via WebSocket.
- **Client side**: `xterm.js` renders ANSI output and sends keystrokes back via WebSocket.

### Backend Changes

**File: `prototypes/symphony-ts/src/observability/dashboard-server.ts`**

The existing server uses Node's `http.createServer`. Extend it to handle WebSocket upgrades for the terminal endpoint.

Add dependency in `prototypes/symphony-ts/package.json`:
```json
"node-pty": "^1.0.0",
"ws": "^8.0.0"
```

Add a helper in `dashboard-server.ts` (or new file `terminal-server.ts`):

```ts
import { WebSocketServer } from "ws";
import * as pty from "node-pty";
import type { IncomingMessage, Server } from "http";

export function attachTerminalWebSocket(server: Server, workdir: string): void {
  const wss = new WebSocketServer({ noServer: true });

  server.on("upgrade", (req: IncomingMessage, socket, head) => {
    const url = new URL(req.url ?? "", "http://localhost");
    if (url.pathname !== "/api/v1/terminal") {
      socket.destroy();
      return;
    }
    wss.handleUpgrade(req, socket, head, (ws) => {
      wss.emit("connection", ws, req);
    });
  });

  wss.on("connection", (ws) => {
    const shell = process.platform === "win32" ? "cmd.exe" : "bash";

    const ptyProcess = pty.spawn(shell, [], {
      name: "xterm-color",
      cols: 120,
      rows: 40,
      cwd: workdir,
      env: {
        ...process.env,
        // Activate .venv if it exists
        PATH: `${workdir}/../.venv/bin:${process.env.PATH}`,
        VIRTUAL_ENV: `${workdir}/../.venv`,
      },
    });

    ptyProcess.onData((data) => {
      if (ws.readyState === ws.OPEN) {
        ws.send(JSON.stringify({ type: "output", data }));
      }
    });

    ws.on("message", (msg: Buffer | string) => {
      try {
        const parsed = JSON.parse(msg.toString());
        if (parsed.type === "input") {
          ptyProcess.write(parsed.data);
        } else if (parsed.type === "resize") {
          ptyProcess.resize(parsed.cols, parsed.rows);
        }
      } catch {
        // ignore malformed messages
      }
    });

    ws.on("close", () => {
      ptyProcess.kill();
    });

    ptyProcess.onExit(() => {
      ws.close();
    });
  });
}
```

**Where to call it:** In `dashboard-server.ts` `startServer()` function, after `server.listen(...)`:
```ts
attachTerminalWebSocket(server, options.workdir ?? process.cwd());
```

Add `workdir` to `DashboardServerOptions`:
```ts
export interface DashboardServerOptions {
  host: DashboardServerHost;
  port?: number;
  workdir?: string;   // NEW — cwd for terminal PTY
  staticDir?: string;
}
```

Pass `workdir` from `runtime-host.ts` `startDashboard()` call — use the workspace root path.

---

### Frontend Changes

**Add dependency** in `ui/package.json`:
```json
"xterm": "^5.3.0",
"xterm-addon-fit": "^0.8.0"
```

**New file: `ui/src/components/TerminalPanel.tsx`**

```tsx
import { useEffect, useRef } from "react";
import { Terminal } from "xterm";
import { FitAddon } from "xterm-addon-fit";
import "xterm/css/xterm.css";

export function TerminalPanel() {
  const containerRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<Terminal | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    const term = new Terminal({
      theme: { background: "#0d1117", foreground: "#c9d1d9" },
      fontFamily: '"JetBrains Mono", "Fira Code", monospace',
      fontSize: 13,
      cursorBlink: true,
    });
    const fitAddon = new FitAddon();
    term.loadAddon(fitAddon);
    term.open(containerRef.current!);
    fitAddon.fit();
    termRef.current = term;

    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${protocol}//${location.host}/api/v1/terminal`);
    wsRef.current = ws;

    ws.onopen = () => {
      ws.send(JSON.stringify({ type: "resize", cols: term.cols, rows: term.rows }));
    };

    ws.onmessage = (e) => {
      const msg = JSON.parse(e.data);
      if (msg.type === "output") term.write(msg.data);
    };

    term.onData((data) => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "input", data }));
      }
    });

    const observer = new ResizeObserver(() => {
      fitAddon.fit();
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "resize", cols: term.cols, rows: term.rows }));
      }
    });
    observer.observe(containerRef.current!);

    return () => {
      observer.disconnect();
      ws.close();
      term.dispose();
    };
  }, []);

  const handleClear = () => {
    termRef.current?.clear();
  };

  return (
    <div className="terminal-panel">
      <div className="terminal-panel-header">
        <span className="terminal-title">◆ TERMINAL</span>
        <button className="terminal-clear-btn" onClick={handleClear}>CLEAR</button>
      </div>
      <div ref={containerRef} className="terminal-container" />
    </div>
  );
}
```

**Modified: `ui/src/App.tsx`**

Add `"terminal"` to the tab type union and render `<TerminalPanel />` when active:

```tsx
type Tab = "board" | "tokens" | "history" | "terminal";  // add terminal

// In header nav:
<button onClick={() => setTab("terminal")}>Terminal</button>

// In content render:
{tab === "terminal" && <TerminalPanel />}
```

**CSS (`App.css`)**:
```css
.terminal-panel {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 60px);   /* full height minus header */
  background: #0d1117;
}
.terminal-panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 16px;
  border-bottom: 1px solid #21262d;
}
.terminal-title { color: #f85149; font-size: 12px; font-weight: bold; }
.terminal-clear-btn { /* small ghost button */ }
.terminal-container { flex: 1; padding: 8px; }
```

---

### Important Notes for Implementation

- `node-pty` requires native compilation (`node-gyp`). Run `pnpm install` after adding it — may need Xcode CLI tools on Mac.
- The vite proxy in `vite.config.ts` does NOT proxy WebSocket by default. Add:
  ```ts
  proxy: {
    '/api': {
      target: 'http://localhost:4321',
      ws: true,           // ← enable WebSocket proxy
      changeOrigin: true,
    },
    ...
  }
  ```
  Replace the current string shorthand `'/api': 'http://localhost:4321'` with this object form.
- Terminal spawns one PTY per WebSocket connection. If user opens multiple browser tabs, each gets its own shell — acceptable.
- `.venv` path: constructed as `workdir/../.venv`. Verify this resolves to the correct venv path for agentic-os (`/Users/yanghu/Documents/AI_Workspace/prototypes/agentic-os/.venv`). Pass absolute path from runtime-host.

---

## Track 5: Kanban Card Design + Cancelled Archive Panel

### Reference Design (from screenshots)

**Active board**: 5 columns — Backlog · Todo (+ button) · In Progress · In Review · Done  
**Cancelled**: hidden from board, accessible via trash icon with count badge in header

---

### 5A: Column Structure

Current code has 6 columns (backlog, todo, running, review, rework, merging). Target is 5:

| Column | Key | Maps from Linear state |
|---|---|---|
| Backlog | `backlog` | Backlog |
| Todo | `todo` | Todo |
| In Progress | `running` | In Progress |
| In Review | `review` | In Review |
| Done | `done` | Done |

Remove `rework` and `merging` columns from `COLUMN_DEFS` in `KanbanBoard.tsx` and `useLinearIssues.ts`.  
Issues with state "Rework" or "Merging" → map to `running` (In Progress).

Update `STATE_TO_COLUMN` in `useLinearIssues.ts`:
```ts
'rework': 'running',
'merging': 'running',
```

---

### 5B: Issue Card Redesign (`AgentKanbanCard.tsx`)

Each card shows (top to bottom):
```
AGE-89                    [MODEL · DEEPSEEK-V4-FLASH] [DEEPSEEK]
─────────────────────────────────────────────────────
现在几点
现在几点

Updated 6h ago                                      2.2K tok
─────────────────────────────────────────────────────
[◊ Claude]  [◊ Codex]  [◊ DeepSeek]
```

**Zones:**

**Top row:**
- Left: issue identifier (e.g., `AGE-89`)
- Right: model tag chip `MODEL · <model-name>` (gray, small) + agent badge `[CLAUDE]`/`[CODEX]`/`[DEEPSEEK]` (colored)
  - Agent badge color: Claude = orange, Codex = blue, DeepSeek = teal
  - Source: `entry.last_event` or a `agent` field on the entry

**Middle:**
- Title (large, white)
- Description / last message (small, muted, 1 line truncated)

**Bottom meta row:**
- Left: `Updated Xh ago` (relative timestamp from `entry.last_event_at`)
- Right: token count formatted (e.g., `2.2K tok` from `entry.tokens.total_tokens`)
  - Show nothing if 0

**Agent dispatch buttons (bottom):**
- Three buttons always shown: `◊ Claude`, `◊ Codex`, `◊ DeepSeek`
- Clicking dispatches `POST /api/v1/issues/:identifier/dispatch` with `{ agent: "claude" | "codex" | "deepseek" }`
- `◊` icon is a small lightning/diamond symbol
- Button style: ghost, small, rounded chip
- Currently active agent button: slightly brighter/highlighted border

**Props change for `AgentKanbanCard`:**
```ts
interface AgentKanbanCardProps {
  entry: RunningEntry        // existing
  onClick?: () => void       // existing
  isDragging?: boolean       // existing
  onDispatch?: (agent: string) => void   // NEW
}
```

**Dispatch logic** (in `KanbanBoard.tsx` where cards are rendered):
```ts
onDispatch={async (agent) => {
  await fetch(`/api/v1/issues/${encodeURIComponent(identifier)}/dispatch`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ agent }),
  })
  queryClient.invalidateQueries({ queryKey: STATE_KEY })
}}
```

**Token formatting helper** (add to card or shared utils):
```ts
function fmtTok(n: number): string {
  if (n === 0) return ''
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M tok`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K tok`
  return `${n} tok`
}
```

**Relative time helper:**
```ts
function relativeTime(iso: string | null): string {
  if (!iso) return '—'
  const diff = Date.now() - new Date(iso).getTime()
  const m = Math.floor(diff / 60_000)
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  return `${Math.floor(h / 24)}d ago`
}
```

---

### 5C: Cancelled Archive Panel (`TrashPanel.tsx`)

**Header trash icon (in `Header.tsx`):**
```tsx
<button className="trash-btn" onClick={onTrashClick}>
  🗑 {cancelledCount}
</button>
```
`cancelledCount` = count of cancelled issues (from `useLinearColumns` — issues in `cancelled` bucket).

Pass `onTrashClick` and `cancelledCount` from `App.tsx` down to `Header`.

**Panel design (in `TrashPanel.tsx`):**
```
CANCELLED (77)  ✕
┌──────────────────────────────────────┐
│ AGE-11           AGE-16   AGE-15 ... │
│ 削减合并...       down load...        │
│ [CANCELLED]      [CANCELLED]          │
└──────────────────────────────────────┘
```

- Appears as an overlay/drawer below the header (not replacing the board)
- Grid layout: 6 columns, compact cards
- Each card: identifier, title (truncated), `CANCELLED` badge, no action buttons
- Header: `CANCELLED (N)` + `✕` close button

**Current `TrashPanel.tsx` receives `entries: RunningEntry[]` but is always empty** because `cancelledEntries` in `KanbanBoard.tsx` is hardcoded `[]`.

Fix: pass cancelled Linear issues from `useLinearColumns` instead. In `App.tsx`:
```ts
const cancelledIssues = linearIssues?.filter(li => classifyState(li.state) === 'cancelled') ?? []
```
Pass to `KanbanBoard` or directly to `TrashPanel`.

`TrashPanel` needs to accept `LinearIssue[]` (not just `RunningEntry[]`). Update its props type.

**`TrashPanel` render as overlay:**
- Currently rendered inside `KanbanBoard` — move it to `App.tsx` level so it overlays the full board
- Toggle visibility via `trashOpen` state in `App.tsx`

---

### 5D: Header Counter

Add to `Header.tsx`:
- `totalCount` prop: total active issues (all non-cancelled columns)
- `cancelledCount` prop: cancelled count
- `onTrashClick` prop: toggle trash panel

Header right section:
```tsx
<span className="total-count">{totalCount} total tasks</span>
<button className="trash-btn" onClick={onTrashClick}>
  <TrashIcon /> {cancelledCount}
</button>
```

Wire in `App.tsx` by counting from `linearIssues`.

---

## Track 6: Issue Detail Panel Redesign

### Reference Design (from screenshot)

```
┌─ [IN REVIEW]  AGE-84 · TEST-DISPATCH-469B9A              [× Close] ─┐
│  Started: 5/14 6:34PM · Duration: 32.46s · Model: claude-sonnet-4-6  │
│  ID: 985eda73-...                                                      │
├── ◆ LINEAR ISSUE ─────────────────────────────────────────────────────┤
│  TITLE   [修改语音输入图标错误的位置                                  ]│
│  DESC    [/path/to/screenshot...                              ][scroll]│
│          [Attach file]                                                  │
│  STATE   [In Review ▼]    [Save to Linear]  ↗ AGE-84                  │
├── PREVIOUS ATTEMPTS (1) ──────────────────────────────────────────────┤
│  ▼ [IN REVIEW]  Attempt 1  5/14 6:14PM · 6.31s                       │
├── PROMPT / COMMAND ───────────────────────────────────────────────────┤
│  Original task: AGE-84: TEST-dispatch-469b9a                           │
│  Say hello                                                              │
│  Previous attempt output: Hello.                                        │
│  [Human feedback]: ...                                                  │
│  Please continue or revise based on the feedback above.                │
├── OUTPUT ─────────────────────────────────────────────────────────────┤
│  `mic-status-desc` moved below flex row...                             │
├── COMMENT / FEEDBACK  [OpenAI 4o mini ▼] [📎]────────────────────────┤
│  [Add feedback or instructions for the next run…                      ]│
│  [Attach file]                                                          │
├───────────────────────────────────────────────────────────────────────┤
│  [✓ Approve → Done]         [◊ Claude]  [◊ Codex]  [◊ DeepSeek]      │
└───────────────────────────────────────────────────────────────────────┘
```

---

### What Current Code Has vs. What's Needed

| Section | Current | Needed |
|---|---|---|
| Header | identifier + close | state badge + identifier + title + close |
| Meta | state, session, turn, tokens | started, duration, model, UUID |
| Linear Issue | ✗ | editable title + description + state dropdown + Save |
| Previous Attempts | ✗ | collapsible list from history API |
| Prompt/Command | ✗ | full prompt text from run history |
| Output | ✗ | agent output from run history |
| Comment/Feedback | `CommentFeed` (basic) | model selector + attach + re-dispatch integration |
| Bottom actions | single Dispatch OR Cancel | Approve→Done + 3 agent buttons |

---

### 6A: Header + Meta Row

**Header bar:**
```tsx
<div className="detail-header">
  <span className={`detail-state-badge ${stateClass}`}>{entry.state.toUpperCase()}</span>
  <h2>{entry.issue_identifier} · {issueTitle}</h2>
  <button className="close-btn" onClick={onClose}>× Close</button>
</div>
```

**Meta row (single line below header):**
```tsx
<div className="detail-meta-row-top">
  <span>Started: <strong>{formatDate(entry.started_at)}</strong></span>
  <span>·</span>
  <span>Duration: <strong>{duration}</strong></span>
  <span>·</span>
  <span>Model: <strong>{model}</strong></span>
  <span>·</span>
  <span>ID: <code>{entry.session_id}</code></span>
</div>
```

`issueTitle` and `model` come from the issue detail API response (already fetched via `getIssueDetails`). Need to confirm these fields are in `IssueDetailResponse`.

---

### 6B: Linear Issue Section (Editable)

New section below meta. Data: title + description from Linear (passed via `useLinearIssues` or fetched from detail API).

```tsx
<section className="detail-section">
  <div className="detail-section-label">◆ LINEAR ISSUE</div>

  <label>TITLE</label>
  <input value={editTitle} onChange={e => setEditTitle(e.target.value)} />

  <label>DESCRIPTION</label>
  <textarea value={editDesc} onChange={e => setEditDesc(e.target.value)} rows={5} />
  <button>📎 Attach file</button>

  <label>STATE</label>
  <select value={editState} onChange={e => setEditState(e.target.value)}>
    {['Backlog','Todo','In Progress','In Review','Done'].map(s =>
      <option key={s}>{s}</option>
    )}
  </select>

  <button onClick={handleSaveToLinear} disabled={saving}>
    {saving ? 'Saving…' : 'Save to Linear'}
  </button>
  <a href={issueUrl} target="_blank" rel="noreferrer">↗ {entry.issue_identifier}</a>
</section>
```

`handleSaveToLinear` calls `PATCH /api/v1/linear/issues/:id` (defined in Track 1) with `{ state_name: editState }` and separately title/description if the PATCH endpoint supports them. Add `title` and `description` to `updateLinearIssueState` or create a separate `updateLinearIssue` mutation.

**Linear GraphQL mutation for title + description update** (add to `runtime-host.ts`):
```graphql
mutation($issueId: String!, $title: String!, $description: String) {
  issueUpdate(id: $issueId, input: { title: $title, description: $description }) {
    success
  }
}
```

Update `PATCH /api/v1/linear/issues/:id` body to accept `{ state_name?, title?, description? }` and apply each field if present.

**Where does initial title/description come from?**
- If issue is in `useLinearIssues` cache → use that data (pass `LinearIssue` to `DetailPanel` as optional prop alongside `RunningEntry`)
- If not cached (e.g., issue only exists in engine state) → title from `entry.last_message` fallback

Update `DetailPanel` props:
```ts
interface DetailPanelProps {
  entry: RunningEntry | null
  linearIssue?: LinearIssue | null    // NEW — for editable fields
  onClose: () => void
  onIssueUpdate?: () => void
}
```

In `App.tsx` / `KanbanBoard.tsx`, when opening detail panel, look up matching `LinearIssue` from `linearIssues` array by `entry.issue_id` and pass it.

---

### 6C: Previous Attempts Section

Collapsible list. Data comes from a new API endpoint.

**New backend route needed in `dashboard-server.ts`:**
```
GET /api/v1/issues/:identifier/history
```

Add to `DashboardServerHost`:
```ts
getIssueHistory?(identifier: string): Promise<RunAttempt[]>;
```

Where `RunAttempt` (define in dashboard-server.ts):
```ts
export interface RunAttempt {
  attemptNumber: number;
  startedAt: string;
  duration: number | null;     // seconds
  state: string;
  prompt: string | null;       // full constructed prompt
  output: string | null;       // agent output
}
```

Implement in `OrchestratorRuntimeHost` — scan `this.workspaceManager` or the run log for past attempts by identifier. This depends on what symphony-ts persists. If run history isn't stored in symphony-ts, fallback: return empty array (section hidden when empty).

**Frontend:**
```tsx
const { data: history } = useQuery({
  queryKey: ['issue-history', entry.issue_identifier],
  queryFn: () => fetch(`/api/v1/issues/${encodeURIComponent(entry.issue_identifier)}/history`).then(r => r.json()),
  enabled: !!entry,
})
```

Render as collapsible accordion:
```tsx
<section className="detail-section">
  <div className="detail-section-label">
    PREVIOUS ATTEMPTS ({history?.length ?? 0})
  </div>
  {history?.map((attempt) => (
    <details key={attempt.attemptNumber} className="attempt-row">
      <summary>
        <span className={`attempt-state-badge`}>{attempt.state.toUpperCase()}</span>
        Attempt {attempt.attemptNumber}
        {' '}{formatDate(attempt.startedAt)} · {attempt.duration}s
      </summary>
      {/* Expands to show prompt + output for that attempt */}
      <pre className="attempt-prompt">{attempt.prompt}</pre>
      <pre className="attempt-output">{attempt.output}</pre>
    </details>
  ))}
</section>
```

---

### 6D: Prompt / Command + Output Sections

Show current run's prompt and output. Data from `getIssueDetails` response.

Extend `IssueDetailResponse` in `dashboard-server.ts` to include:
```ts
export interface IssueDetailRunningState {
  // existing fields...
  prompt: string | null;    // constructed prompt sent to agent
  output: string | null;    // last output from agent
}
```

Populate in `toRunningIssueDetail()` in `runtime-host.ts` from orchestrator state.

**Frontend:**
```tsx
const { data: detail } = useQuery({
  queryKey: ['issue-detail', entry.issue_identifier],
  queryFn: () => fetch(`/api/v1/${encodeURIComponent(entry.issue_identifier)}`).then(r => r.json()),
  enabled: !!entry,
  refetchInterval: entry?.session_id ? 5_000 : false,  // poll if running
})

// Then in render:
{detail?.prompt && (
  <section className="detail-section">
    <div className="detail-section-label">PROMPT / COMMAND</div>
    <pre className="detail-prompt">{detail.prompt}</pre>
  </section>
)}

{detail?.output && (
  <section className="detail-section">
    <div className="detail-section-label">OUTPUT</div>
    <pre className="detail-output">{detail.output}</pre>
  </section>
)}
```

---

### 6E: Comment / Feedback Section

Replaces current `CommentFeed` tab. Fixed section with **STT model selector**, **voice input**, and **file attachment via path**.

#### Layout
```
COMMENT / FEEDBACK         [Browser STT ▼]  [🎤]
┌─────────────────────────────────────────────┐
│ Add feedback or instructions for next run…  │
└─────────────────────────────────────────────┘
[📎 Attach file]
```

#### STT Model Selector (the dropdown top-right)

**NOT the agent model** — this selects the **speech-to-text engine**:
- `Browser STT` — Web Speech API (`window.SpeechRecognition`), no API key needed, online-only
- `OpenAI 4o mini` — Whisper via OpenAI API, records audio → POST to backend → returns transcript

```tsx
<select value={sttModel} onChange={e => setSttModel(e.target.value)}>
  <option value="browser">Browser STT</option>
  <option value="openai">OpenAI 4o mini</option>
</select>
<button onClick={handleMicToggle} className={recording ? 'mic-active' : ''}>🎤</button>
```

**Browser STT implementation:**
```ts
const recognition = new (window.SpeechRecognition || window.webkitSpeechRecognition)()
recognition.lang = 'zh-CN'   // or auto-detect
recognition.interimResults = false
recognition.onresult = (e) => {
  const transcript = e.results[0][0].transcript
  setFeedback(prev => prev + (prev ? ' ' : '') + transcript)
}
recognition.start()
```

**OpenAI Whisper STT implementation:**
1. Record audio via `MediaRecorder` API into a blob
2. POST blob to new backend route `POST /api/v1/stt` with `{ model: "whisper-1" }`
3. Backend calls OpenAI Whisper API, returns `{ transcript: string }`
4. Insert transcript into textarea

New backend route in `dashboard-server.ts`:
```
POST /api/v1/stt
Body: FormData with audio file
Response: { transcript: string }
```

Add to `DashboardServerHost`:
```ts
transcribeAudio?(audioBlob: Buffer, mimeType: string): Promise<{ transcript: string }>;
```

Implement in `runtime-host.ts` using OpenAI SDK (already a dependency via Codex):
```ts
async transcribeAudio(audioBlob: Buffer, mimeType: string) {
  const openai = new OpenAI({ apiKey: process.env.OPENAI_API_KEY })
  const file = new File([audioBlob], 'audio.webm', { type: mimeType })
  const result = await openai.audio.transcriptions.create({ model: 'whisper-1', file })
  return { transcript: result.text }
}
```

#### Attach File → Insert Absolute Path

"Attach file" does **not upload**. It opens a file picker and inserts the selected file's absolute path into the textarea.

```tsx
const fileInputRef = useRef<HTMLInputElement>(null)

const handleAttachFile = () => {
  fileInputRef.current?.click()
}

const handleFileSelected = (e: React.ChangeEvent<HTMLInputElement>) => {
  const file = e.target.files?.[0]
  if (!file) return
  // In Electron/Tauri: file.path gives absolute path.
  // In browser: file.name only. Use a workaround: show file name and instruct user
  // to paste full path, OR use webkitdirectory trick.
  // Simplest for now: insert the file name as a note — user can correct the path.
  const pathStr = (file as any).path ?? file.name  // Electron exposes .path
  setFeedback(prev => prev + (prev ? '\n' : '') + pathStr)
  e.target.value = ''  // reset so same file can be re-attached
}

// Render:
<input ref={fileInputRef} type="file" style={{ display: 'none' }} onChange={handleFileSelected} />
<button onClick={handleAttachFile}>📎 Attach file</button>
```

> Note: In a standard browser, `file.path` is undefined (security restriction). Only Electron/Tauri exposes it. In a browser context, fall back to `file.name` and show a note that the full path must be provided manually. The agent reads files via absolute path, so this is a known limitation unless the app is packaged as a desktop app.

#### Dispatch with Feedback

Feedback is submitted when user clicks one of the bottom agent buttons:

```ts
const handleDispatchWithFeedback = async (agent: string) => {
  if (feedback.trim()) {
    await commentOnIssue(entry.issue_identifier, feedback.trim())
  }
  await dispatchIssue(entry.issue_identifier, agent)
  setFeedback('')
  onIssueUpdate?.()
}
```

`commentOnIssue` already exists in `client.ts`. `dispatchIssue` accepts agent string.

---

### 6F: Bottom Action Bar (Fixed)

Fixed to bottom of panel regardless of scroll position.

```tsx
<div className="detail-action-bar">
  <button
    className="action-btn action-btn-approve"
    onClick={handleApprove}
  >
    ✓ Approve → Done
  </button>
  <div className="action-btn-group">
    <button className="action-btn action-btn-claude" onClick={() => handleDispatchWithFeedback('claude')}>
      ◊ Claude
    </button>
    <button className="action-btn action-btn-codex" onClick={() => handleDispatchWithFeedback('codex')}>
      ◊ Codex
    </button>
    <button className="action-btn action-btn-deepseek" onClick={() => handleDispatchWithFeedback('deepseek')}>
      ◊ DeepSeek
    </button>
  </div>
</div>
```

`handleApprove` → PATCH linear issue state to "Done" + optionally mark in engine.

Remove the existing "Cancel" / "Dispatch" buttons from mid-panel actions — superseded by bottom bar.

---

### CSS Notes

- Panel is a right-side drawer or full-screen overlay (current code: right panel)
- `detail-action-bar`: `position: sticky; bottom: 0; background: #0d1117; border-top: 1px solid #21262d`
- `detail-prompt`, `detail-output`: `font-family: monospace; white-space: pre-wrap; font-size: 12px; background: #010409; padding: 12px; border-radius: 4px; max-height: 300px; overflow-y: auto`
- Agent button colors: Claude = `#f0883e`, Codex = `#58a6ff`, DeepSeek = `#39d353`

---

## Not In Scope (deferred)

- Filter by project / team on kanban board
- DeepSeek real-time streaming cost
- Token panel vertical bar display (mentioned in discussion, lower priority)
- Skill Board panel (architecture still being defined — see discussion notes)
