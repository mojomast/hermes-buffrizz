# Deploying Buffrizz on a Hermes 0.23.0 host

These steps install a tested checkout of this plugin next to other plugins,
without changing their enablement. They are written for a host that already
runs Hermes `v0.23.0` from `~/.hermes/hermes-agent`, symlinks plugins into
`~/.hermes/plugins`, and serves the Hermes web app (commonly port 9120).
Adjust user, host, and unit names to match the machine.

Do not open a NousResearch catalog PR from this file. Catalog submission is a
separate, explicitly authorized step.

## 1. Backup

Record the current plugin enablement and take a copy of any existing checkout
before changing files:

```bash
stamp=$(date +%Y%m%d-%H%M%S)
mkdir -p ~/.hermes/backups
# If a previous checkout exists, copy it into ~/.hermes/backups/buffrizz-$stamp
# (rsync or recursive copy) and record its HEAD as the rollback SHA.
```

Also copy the active Hermes profile config into that backup directory under a
timestamped name so you can restore *only* the Buffrizz enablement and
settings if something goes wrong. Do not replace the live profile config with
a stale full-file backup that would clobber other plugins.

## 2. Official Freebuff CLI

Install the official CLI with its documented method. Do not fetch a mirror
binary or bundle one into the plugin:

```bash
npm install -g freebuff
freebuff -v
# optional: freebuff doctor
```

Login stays in the official TUI. Do not script `freebuff login` and do not
read `~/.config/manicode/credentials.json`.

## 3. Checkout, symlink, enable

```bash
git clone https://github.com/mojomast/hermes-buffrizz.git ~/hermes-buffrizz
cd ~/hermes-buffrizz
git checkout <tested-sha>   # or a release tag such as v0.1.0

mkdir -p ~/.hermes/plugins
ln -sfn ~/hermes-buffrizz ~/.hermes/plugins/buffrizz

# Enable only this plugin. Leave other plugins' enabled flags unchanged.
# Using the CLI, if available:
hermes plugins enable buffrizz
# or edit plugins.entries.buffrizz.enabled: true in the active profile config.
```

Add at least one project under `plugins.entries.buffrizz.settings.allowlist_roots`
if you want work outside the default plugin-data workspace.

Install plugin Python deps the same way the host already does for other
plugins (`hermes plugins install` / enable will typically admit
`pyproject.toml` dependencies: `fastapi` and `pyte`).

## 4. Gateway restart

Hermes does not hot-remount plugin HTTP routes. Restart the gateway **once**
after the symlink and enablement change, then confirm it and the other
enabled plugins come back healthy:

```bash
# Example — use the unit or process this host already uses:
#   systemctl --user restart hermes-gateway
#   or the host's existing restart script.
# After restart:
hermes plugins list
hermes plugins doctor buffrizz
# Confirm the web app responds (example port):
curl -fsS http://127.0.0.1:9120/ >/dev/null
```

Record the command you used. If the gateway or another plugin fails to come
back, roll back immediately (section 6).

## 5. Smoke test

- The plugin loads and doctor / `plugins list` shows the three tools.
- The pane route serves (open the Buffrizz pane in Desktop or the web app).
- A queued job against the *fake* Freebuff TTY (tests in this repo) produces
  a diff end to end: `python -m pytest tests/test_jobs.py -q`.
- The real `freebuff` binary launches in the pane PTY at least up to its
  login screen. A human signs in; do not automate that step.

## 6. Rollback

```bash
# Restore the previous checkout (or remove the symlink if this was a first install):
#   cd ~/hermes-buffrizz && git checkout <rollback-sha>
#   or: rm ~/.hermes/plugins/buffrizz
# Restore only the buffrizz enablement/settings you changed, not a stale
# full config.yaml that would clobber other plugins.
# Restart the gateway once more and re-check hermes plugins list / doctor.
```

Keep the backup directory (`~/.hermes/backups/buffrizz-<timestamp>`) until
you are satisfied the new pin is healthy.
