
from __future__ import annotations

import json
from pathlib import Path

from buffrizz import client
from buffrizz.supervisor import BIND_HOST
from buffrizz.tools import handle_status


def test_supervisor_binds_loopback_only(plugin_env):
    raw = handle_status({"detail": "summary"})
    body = json.loads(raw)
    assert body.get("ok") is True, body
    session = json.loads((plugin_env["data"] / "supervisor.json").read_text())
    assert session["bind"] == "127.0.0.1" == BIND_HOST
    assert "0.0.0.0" not in json.dumps(session)
    assert (plugin_env["data"] / "supervisor.json").stat().st_mode & 0o777 == 0o600


def test_body_limit_documented():
    from buffrizz.supervisor import BODY_LIMIT
    assert BODY_LIMIT == 256 * 1024
