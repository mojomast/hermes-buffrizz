
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from buffrizz import client, env
from buffrizz.tools import handle_connect


def test_child_env_omits_sentinel(plugin_env):
    os.environ["BUFFRIZZ_SENTINEL_SECRET"] = "sentinel-should-never-leak"
    os.environ["NODE_OPTIONS"] = "--require /tmp/evil.js"
    built = env.child_env()
    assert "BUFFRIZZ_SENTINEL_SECRET" not in built
    assert "AWS_SECRET_ACCESS_KEY" not in built or built.get("AWS_SECRET_ACCESS_KEY") != os.environ.get("AWS_SECRET_ACCESS_KEY")
    assert "NODE_OPTIONS" not in built
    assert "PATH" in built and "HOME" in built and "TERM" in built


def test_live_child_environ_has_no_sentinel(plugin_env):
    raw = handle_connect({"action": "start", "cwd": str(plugin_env["repo"])}, session_id="env-chat")
    body = json.loads(raw)
    assert body.get("ok") and body.get("running"), body
    pid = None
    for _ in range(30):
        status = client.call("GET", "/status?session=env-chat&detail=full")
        pid = status.get("pid")
        if pid:
            break
        time.sleep(0.1)
    assert pid, "freebuff child pid not reported"
    environ_path = Path(f"/proc/{pid}/environ")
    if not environ_path.is_file():
        # Also check supervisor children if pid is the session process — it should be.
        pytest_skip = False
    data = environ_path.read_bytes()
    assert b"sentinel-should-never-leak" not in data
    assert b"aws-should-never-leak" not in data
    assert b"NODE_OPTIONS" not in data
    # Supervisor session file must be mode 0600
    session = plugin_env["data"] / "supervisor.json"
    assert session.is_file()
    assert (session.stat().st_mode & 0o777) == 0o600
    token = json.loads(session.read_text())["token"]
    assert token
    # Tool output must never include the token
    status_raw = handle_connect({"action": "status"}, session_id="env-chat")
    assert token not in status_raw
