
from __future__ import annotations

import json
from buffrizz.tools import handle_connect


def test_connect_refuses_model_token():
    raw = handle_connect({"action": "start", "token": "tok_from_chat", "cwd": "/tmp/nope"})
    body = json.loads(raw)
    assert isinstance(raw, str)
    assert body["ok"] is False
    assert body["error"] == "unsupported_operation"
    assert body["code"] == "pair_via_pane"


def test_connect_refuses_api_key():
    raw = handle_connect({"action": "start", "api_key": "cb_from_chat"})
    body = json.loads(raw)
    assert body["error"] == "unsupported_operation"
    assert body["code"] == "pair_via_pane"
    assert body.get("token") is None
    assert "cb_from_chat" not in raw


def test_connect_without_secret_does_not_use_supplied_creds(monkeypatch):
    called = {}
    def fake_call(method, route, payload=None, timeout=8.0):
        called["payload"] = payload
        return {"ok": True, "running": False}
    monkeypatch.setattr("buffrizz.tools.client.ensure", lambda: {"bind": "127.0.0.1"})
    monkeypatch.setattr("buffrizz.tools.client.call", fake_call)
    raw = handle_connect({"action": "status"}, session_id="sess1")
    body = json.loads(raw)
    assert body["ok"] is True
    assert "token" not in (called.get("payload") or {})
    assert "api_key" not in (called.get("payload") or {})
