# Changelog

## 0.1.0 — 2026-11-09

- First release: official `freebuff` CLI hosted in a session-bound Hermes
  Desktop / Webapp pane, with a three-tool agent queue.
- `buffrizz_connect` starts or stops the official PTY. Model-supplied tokens
  and API keys are refused (`pair_via_pane`). Login happens in the pane.
- `buffrizz_job op=enqueue` never auto-submits. The user clicks Run; Buffrizz
  then bracket-pastes the prompt, waits for idle, and returns git status and
  diff stats from a per-job branch in a plugin-data worktree.
- Working directories are limited to allowlisted roots (configured roots plus
  a default plugin-data workspace). Filesystem roots and symlink escapes are
  rejected.
- Optional `op=paid_run` uses the official paid `@codebuff/sdk` with
  `CODEBUFF_API_KEY` from Hermes secret scope when `paid_unattended` is
  enabled. Off by default. No Freebuff free-mode fallback.
- Tests drive a fake Freebuff TTY program and do not call Freebuff servers.
