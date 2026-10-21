---
agent:
  backend: claude
polling:
  interval_ms: 30000
tracker:
  active_states:
  - Todo
  - In Progress
  api_key: $LINEAR_API_KEY
  board_hidden_states:
  - Canceled
  - Duplicate
  kind: linear
  project_slug: baa38c65341e
  team_id: ''
  terminal_states:
  - Done
  - Canceled
  - Duplicate
---
