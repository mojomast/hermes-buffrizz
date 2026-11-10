---
name: buffrizz
description: Pair a Hermes conversation with the official Freebuff CLI in a pane, queue coding tasks, and collect git diffs after the user clicks Run. Covers pairing, the queue, allowlisted roots, and the optional paid Codebuff SDK path.
license: MIT
---
# Buffrizz

Buffrizz hosts the official `freebuff` binary in a Hermes pane. You and the
user share that session. The agent queues work; the user signs in and clicks
**Run**. Skill id: `buffrizz:buffrizz`.

## Workflow

1. Check `buffrizz_status`. Confirm `freebuff_installed` and that the project
   is under `allowlist_roots`. The model cannot add a root; ask the user to
   add it in Buffrizz plugin settings if it is missing.
2. Call `buffrizz_connect` with `action=start` and the allowlisted `cwd`.
   Open the Buffrizz pane beside this conversation. If `signed_in` is `false`
   or `unknown`, tell the user to complete official login in the pane.
   **Never** pass `token` or `api_key`. Those fields return
   `unsupported_operation` / `pair_via_pane`.
3. Call `buffrizz_job` with `op=enqueue` and the coding prompt. Enqueue does
   **not** send the prompt to Freebuff (`auto_submitted` is always false).
4. Ask the user to click **Run** in the pane. Official Terms require a human
   to start each free-tier session and remain present. Ads stay visible.
5. Poll `buffrizz_job` with `op=result` and the `job_id`. Default
   `timeout_seconds=0` returns the current state; set a short timeout only if
   you must wait. The result is git status, diff stats, changed paths, and a
   short transcript excerpt. Credential-like files are redacted. Read the
   changed files with ordinary Hermes tools.

## Recovery

- `freebuff_missing`: ask the user to run `npm install -g freebuff`, then
  `freebuff doctor` in a terminal if the official CLI misbehaves.
- `cwd_not_allowlisted`: ask the user to add the project under
  `allowlist_roots`. Do not try to widen the allowlist yourself.
- `pair_via_pane`: drop any model-supplied credential and point the user at
  the pane.
- `session_not_running` or a hung login: ask the user to start or sign in in
  the pane. Do not wait forever; `timeout_seconds` defaults to 0.
- Jobs need a git repository. Buffrizz creates a session worktree and a
  `buffrizz/<job_id>` branch so the user's checkout stays untouched.

## What not to do

- Do not script Freebuff login, dismiss ads, or auto-submit a free-tier job.
- Do not read `~/.config/manicode/credentials.json`, a keychain, or Hermes
  `.env` files.
- Do not call `op=paid_run` unless the user enabled `paid_unattended` and
  wants the official **paid** Codebuff SDK (`CODEBUFF_API_KEY`). That path is
  off by default and is not Freebuff free mode.
