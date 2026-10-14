# Review log: 2026-10-14-dsh-backend-swap

- 2026-10-14: Claude (host) wrote the plan at the user's request: "replace DS TUI with DeepSeek Harness and retire deepseek". The user asked for no review yet.
- Evidence gathered locally:
  - `dsh --version` = 0.1.0-rc.7;
  - `dsh --profile headless --help` and `--dump-config` (sandbox and approval presets);
  - `~/.dsh/profiles` contains only `headless`;
  - the launchd plist PATH;
  - `git grep` for deepseek references in `runner/`.
- Status: **NOT YET REVIEWED.**
