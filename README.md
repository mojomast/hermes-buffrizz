# Buffrizz

A Hermes Agent plugin that hosts the official [Freebuff](https://freebuff.com/cli)
CLI in a Desktop / Webapp pane so you and the agent can share one session.
The agent queues coding tasks; you sign in and click **Run**. When the official
TUI goes idle, Buffrizz hands back git status and diff stats.

This is not a headless Freebuff client, a wrapper around free inference, or a
third-party Codebuff API. It spawns the official `freebuff` binary in a real
PTY, leaves ads and notices visible, and will not script login or auto-submit
a free-tier job.

- Plugin id: `buffrizz`
- Requires Hermes `>=0.23.0`
- Platforms: Linux and macOS
- License: MIT

## Tools

Three composable tools, measured with tiktoken `o200k_base` (see
`evals/measure_schemas.py`; budget 550 tokens):

| Tool | Role |
| --- | --- |
| `buffrizz_status` | Official CLI install, pane/PTY, signed-in boolean (never a token), bound session, allowlisted roots, job summaries. `detail` is `summary` or `full`. |
| `buffrizz_connect` | `action`: `start`, `stop`, `status`. Opens the official TUI for this Hermes conversation. Refuses model-supplied `token` or `api_key` (`unsupported_operation` / `pair_via_pane`). `cwd` must already be allowlisted. |
| `buffrizz_job` | `op`: `enqueue`, `list`, `status`, `cancel`, `result`, `paid_run`. Enqueue never auto-submits. `result` waits only if `timeout_seconds` is set; default `0` returns the current state. |

Skill id: `buffrizz:buffrizz`.

## How pairing and the queue work

1. Add project roots in Buffrizz plugin settings (`allowlist_roots`). The
   model cannot add a root. A default workspace under profile-scoped plugin
   data is always available. Filesystem roots (`/`, `/home`, …) are rejected.
2. The agent calls `buffrizz_connect` with `action=start` and an allowlisted
   `cwd`. Buffrizz opens a session-bound pane and starts the official CLI
   (`freebuff --cwd …`, optional official `--continue`). If the project is a
   git repo, work happens in a plugin-data worktree so your checkout stays
   put. Each job gets a `buffrizz/<job_id>` branch.
3. You sign in in the official TUI if needed. Buffrizz never reads
   `~/.config/manicode/credentials.json`, a keychain, Hermes `auth.json`, or
   `.env` files. `signed_in` is inferred from pane output (`true`, `false`,
   or `unknown`).
4. The agent enqueues a prompt. The pane shows the job. Nothing is typed
   into Freebuff until you click **Run**.
5. **Run** uses bracketed paste to feed the official TUI. A watcher waits for
   idle, error, cancel, or `job_timeout_seconds` (default 30 minutes). It
   does not hide ads or dismiss notices.
6. `buffrizz_job op=result` returns a JSON envelope: status, a short
   transcript excerpt, diff stats, and changed paths. Credential-like file
   contents are redacted. The agent can then read the files with ordinary
   Hermes tools.

Official Freebuff Terms require a human to start each session and remain
present. “Headless for the user” here means you do not have to type the
prompt, not that a hidden unattended free-tier client is running.

## Optional paid unattended path

`buffrizz_job op=paid_run` is **off by default**. Enable `paid_unattended` in
plugin settings and set `CODEBUFF_API_KEY` in Hermes plugin env (read only
through `agent.secret_scope.get_secret`). That path uses the official
[`@codebuff/sdk`](https://www.codebuff.com/docs/advanced/sdk) with a paid
key. It is never a Freebuff free-mode fallback, and it will not read a
device token from the official CLI. Install Node and `@codebuff/sdk` if you
want it.

## Install

```bash
# Official CLI (user machine; not bundled)
npm install -g freebuff

# Plugin, from this repo
hermes plugins install /path/to/hermes-buffrizz
# or, once catalogued: hermes plugins install buffrizz
```

Open the Buffrizz pane, add allowlisted roots, start the official TUI, and
sign in yourself. Hermes 0.23.0 or newer is required so the Desktop pane can
use `ctx.rest`.

`hermes plugins validate . --install-deps` is the same gate as catalog CI.
Tests use a fake Freebuff TTY program and never call Freebuff servers.

```bash
python -m pip install '.[dev]'
python -m pytest tests -q
python evals/measure_schemas.py
```

See [DEPLOY.md](DEPLOY.md) for installing onto a Hermes 0.23.0 host
(backup, symlink, gateway restart, rollback).

## Disclosure (catalog rule 13)

- Downloads or invokes the official Freebuff CLI only (`npm install -g
  freebuff` is a documented user step). The plugin does not bundle the
  native binary. The official client may use the network, show ads, and
  apply AI-training labels described in Freebuff’s own terms and privacy
  policy.
- Starts a loopback (`127.0.0.1`) supervisor with a random token stored at
  mode `0600` under profile-scoped plugin data, a long-running official
  PTY, and a job-idle watcher.
- Runs `git` in an allowlisted project and may create a worktree under
  plugin data plus a `buffrizz/…` branch per job.
- Stores job records in profile-scoped plugin data (`plugin_data_dir`), not
  in the install checkout. No telemetry.
- Does not read Hermes or Freebuff credential stores or keychains. First
  login is pane-only. The user must click Run for each free-tier job.
- Child processes get a minimal environment (PATH, HOME, TERM, LANG, TMPDIR,
  plus a short allowlist of session plumbing such as `DBUS_SESSION_BUS_ADDRESS`).
  Agent secrets and `NODE_OPTIONS` are not inherited.
- `--trust-agents` is never passed.

## Config

Under `plugins.entries.buffrizz.settings`:

| Key | Default | Meaning |
| --- | --- | --- |
| `allowlist_roots` | `[]` | Extra project roots. The default plugin-data workspace is always allowed. |
| `idle_seconds` | `12` | PTY silence after activity before a running job is treated as idle. |
| `job_timeout_seconds` | `1800` | Maximum seconds a free-tier job may run after Run. |
| `paid_unattended` | `false` | Allow `op=paid_run` via the official paid Codebuff SDK. |

The HTTP supervisor body limit is 256 KiB for the whole JSON payload.

## License

MIT. Copyright (c) 2026 mojomast.
