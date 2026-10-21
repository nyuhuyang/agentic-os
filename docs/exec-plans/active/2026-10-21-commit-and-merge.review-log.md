# Review log: commit-and-merge

- Inspection 1 (CM-001..003): fixed. Bound-branch check, exact refs/heads sha, one status per checkout root.
- Inspection 2 (CM-004..006): fixed. Session-card agents in the main checkout are counted and gated; --commit --no-squash plus a post-check; a failed status is cached.
- Inspection 3 (CM-007..011): fixed. Inherited mergeOptions cleared, no autostash, a target mid-operation refused, the tree verified; runner-root and retiring jobs are counted.
- Inspection 4 (CM-012..014):
  - CM-012 and CM-014 are fixed.
  - CM-013 is OPEN, pending the user's decision. When the project is the runner's own checkout (agentic-os), runner-root launches can start between the manual merge's activity check and the merge. Git still refuses to overwrite files those agents have already changed. Closing it means gating /run, generic retry and unbound Linear dispatch, including its routing subprocess.
- CM-013: the user chose "做". Every runner-root job publish (/run entrypoint, /run free prompt, generic retry, unbound Linear dispatch) goes through _publish_job under the runner checkout's merge gate, and the Linear routing call runs inside _root_activity, which counts as activity. A first attempt used load_registry on every publish; that spawned git per project and hung the suite, so it was replaced by a file-only lookup cached by mtime, with a test that it never runs git. Suite: 831 passed.
- Inspection 5 (CM-015..019): all fixed. ort strategy, no-overwrite-ignore, a launch-gap marker, checkout-keyed gates and activity, and _end_job no longer retires. Suite: 836 passed.
