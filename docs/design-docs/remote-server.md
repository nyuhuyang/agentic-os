# Running AgenticOS on a remote server (AGE-131)

Question: drive work on a company server (data that lives there) from the same dashboard,
with the least code change. Today that server is reached through VS Code Remote-SSH.

## Step 0: the bare CLIs on the server, no runner yet

Prove the agents work there before porting anything. Everything installs under `$HOME`, no sudo.

```bash
curl -sI https://api.anthropic.com https://api.openai.com | grep HTTP   # egress; else set HTTPS_PROXY
curl -fsSL https://claude.ai/install.sh | bash      # claude -> ~/.local/bin
npm i -g --prefix ~/.local @openai/codex            # needs Node >= 18
claude          # login prints a URL: open it on the Mac, paste the code back
codex login --device-auth   # headless; or tunnel the callback: ssh -L 1455:localhost:1455 <server>
```

- [ ] `curl` shows HTTP responses from both APIs (directly or through the company proxy).
- [ ] `claude -p "say hi"` answers inside a server repo.
- [ ] `codex exec "say hi"` answers inside a server repo.

## Recommendation: a second runner on the server, reached through an SSH tunnel

Do not make the Mac runner dispatch over SSH: worktrees, verify, session readers and the
PTY all assume a local filesystem, so that is a rewrite. Run a separate runner on the
server instead and open it in the Mac browser:

```bash
# on the server
git clone <agentic-os> ~/agentic-os && cd ~/agentic-os
python3 -m venv .venv && .venv/bin/pip install flask flask-socketio requests pyyaml   # no requirements file; Python >= 3.11 (tomllib)
cp projects.example.yaml projects.yaml   # register only the server's repos
.venv/bin/python3 runner/app.py --port 8511   # stays on 127.0.0.1
```

```bash
# on the Mac (or let VS Code Remote-SSH's Ports panel forward 8511)
ssh -N -L 8511:127.0.0.1:8511 <server>
open http://localhost:8511
```

- [ ] Use the same port on both ends. The Socket.IO Origin allow-list is
      `http://{127.0.0.1,localhost}:<--port>` (`runner/app.py` `_allowed_origins`), so a
      tunnel `8600 → 8511` loads the page but the terminal/live updates are refused.
      8510 stays free for the Mac runner.
- [ ] Never pass `--host 0.0.0.0`: the tunnel is the auth boundary (escalation rule).
- [ ] Keep it alive with `tmux`/`systemd --user`; launchd and `launchctl kickstart` are Mac-only.
- [ ] Log in `claude` / `codex` on the server once; usage cards read `~/.claude` and
      `~/.codex` there, so they show the server's spend, not the Mac's.

## What breaks on a Linux server

| Piece | Why | Minimal fix |
| --- | --- | --- |
| Confidential projects | `projects.sandbox_prefix` runs `/usr/bin/sandbox-exec` (macOS) | Linux equivalent via `bwrap` (`--unshare-net`, ro-bind `/`, rw-bind the worktree); or mark the project non-confidential if the server itself is the boundary |
| Claude account switching | `claude_account.py` uses the macOS Keychain (`security`) | Leave unused on the server |
| `dsh` binary lookup | `dsh_cli._BIN_CANDIDATES` are Homebrew paths | Not needed unless DeepSeek runs there |

Company data is the confidential case, so the `bwrap` port is the one real code change.
Decide first whether it is needed: if the server is already the trust boundary, run the
server runner without `LINEAR_API_KEY` (whole runner on the local tracker,
`state/tasks.json`) and register the project non-confidential.

## Tracker: do not let two runners poll the same Linear queue

A `project:<key>` label the Mac registry does not know makes the Mac runner record an
"unknown project" error on that card (`modules/linear` FB3-01). Pick one:

- [ ] Server runner without `LINEAR_API_KEY`: everything on its local tracker, nothing reaches Linear; best fit for company data.
- [ ] Or a separate Linear team/project polled only by the server runner.

## Check before starting

- [ ] Company policy allows Claude/Codex API calls with this data from that server.
- [ ] Server has Python ≥ 3.11, git, and outbound HTTPS to the model APIs.
