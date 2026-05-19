---
agent:
  backend: deepseek
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
  team_id: 76114694-9541-434c-8600-762735c3bd88
  terminal_states:
  - Done
  - Canceled
  - Duplicate
---
