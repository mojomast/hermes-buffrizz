
from __future__ import annotations

import json

from buffrizz import paid, paths
from buffrizz.errors import Problem
from buffrizz.tools import handle_job


def test_paid_run_disabled_by_default(plugin_env, monkeypatch):
    raw = handle_job({"op": "paid_run", "prompt": "do stuff", "cwd": str(plugin_env["repo"])}, session_id="x")
    body = json.loads(raw)
    assert isinstance(raw, str)
    assert body["ok"] is False
    assert body["code"] == "paid_disabled"


def test_paid_run_does_not_read_process_env(plugin_env, monkeypatch):
    monkeypatch.setenv("CODEBUFF_API_KEY", "cb_from_environ_should_be_ignored")
    settings = dict(plugin_env["settings"])
    settings["paid_unattended"] = True
    paths.set_test_overrides(
        data_dir=plugin_env["data"],
        freebuff=paths.test_freebuff(),
        home=plugin_env["home"],
        settings=settings,
    )

    def boom(name):
        raise RuntimeError("secret scope missing")

    # Simulate Hermes secret scope present but empty (no fallback to os.environ).
    class FakeScope:
        def get_secret(self, name, default=None):
            return default

    # get_secret import: patch paid._get_secret via a dummy module
    import types, sys
    scope = types.ModuleType("agent.secret_scope")
    def get_secret(name, default=None):
        return default
    scope.get_secret = get_secret
    sys.modules["agent"] = types.ModuleType("agent")
    sys.modules["agent.secret_scope"] = scope
    raw = handle_job({"op": "paid_run", "prompt": "do stuff", "cwd": str(plugin_env["repo"])})
    body = json.loads(raw)
    assert body["ok"] is False
    assert body["code"] == "key_missing"
    assert "cb_from_environ" not in raw
