"""Registered Buffrizz tools. Every handler returns json.dumps(...)."""
from __future__ import annotations

import inspect
import json
from typing import Any, Callable

from . import PLUGIN_ID, PLUGIN_VERSION, client, paid, paths
from .errors import Problem
from .schemas import CONNECT_SCHEMA, JOB_SCHEMA, SCHEMAS, STATUS_SCHEMA

_PAIR_FIX = (
    "Sign in inside the official Freebuff TUI in the Buffrizz pane. "
    "buffrizz_connect refuses a model-supplied token or API key so chat content cannot pair a stranger."
)


def _ok(payload: dict) -> str:
    if "ok" not in payload:
        payload = {"ok": True, **payload}
    return json.dumps(client.strip_secrets(payload), ensure_ascii=False)


def _err(exc: Problem | dict | Exception) -> str:
    if isinstance(exc, Problem):
        return json.dumps(exc.to_dict(), ensure_ascii=False)
    if isinstance(exc, dict):
        body = dict(exc)
        body.setdefault("ok", False)
        return json.dumps(body, ensure_ascii=False)
    return json.dumps(
        {"ok": False, "error": "request_failed", "code": "request_failed", "message": str(exc)[:300]},
        ensure_ascii=False,
    )


def _session_id(args: dict | None, kwargs: dict) -> str:
    host = str(kwargs.get("session_id") or "").strip()
    if host:
        return host
    return str((args or {}).get("session_id") or "").strip()


def _ensure() -> None:
    client.ensure()


def handle_status(args: dict | None = None, session_id: str | None = None, **kwargs: Any) -> str:
    try:
        a = args or {}
        detail = str(a.get("detail") or "summary")
        if detail not in {"summary", "full"}:
            detail = "summary"
        sid = _session_id(a, {**kwargs, "session_id": session_id or kwargs.get("session_id")})
        _ensure()
        route = f"/status?detail={detail}"
        if sid:
            route += f"&session={__import__('urllib.parse').quote(sid)}"
        data = client.call("GET", route)
        if not data.get("ok", True) and data.get("error"):
            return _ok({**data, "ok": False})
        data.setdefault("plugin", PLUGIN_ID)
        data.setdefault("version", PLUGIN_VERSION)
        data["ok"] = True
        return _ok(data)
    except Problem as exc:
        return _err(exc)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


def handle_connect(args: dict | None = None, session_id: str | None = None, **kwargs: Any) -> str:
    try:
        a = args or {}
        token = str(a.get("token") or "").strip()
        api_key = str(a.get("api_key") or "").strip()
        if token or api_key:
            return _err(Problem(
                "pair_via_pane",
                "Login is pane-only. buffrizz_connect refuses a model-supplied token or API key so chat or page content cannot sign in as someone else.",
                _PAIR_FIX,
                error="unsupported_operation",
            ))
        action = str(a.get("action") or "status")
        sid = _session_id(a, {**kwargs, "session_id": session_id or kwargs.get("session_id")})
        if action == "start" and not sid:
            return _err(Problem(
                "missing_session",
                "Open a Hermes conversation so Buffrizz can bind the official TUI to that chat.",
                "Start the session from the Buffrizz pane beside the conversation, or call this tool from that chat.",
            ))
        _ensure()
        data = client.call("POST", "/connect", {
            "action": action,
            "session_id": sid,
            "cwd": a.get("cwd"),
            "continue_id": a.get("continue_id") or None,
        })
        if data.get("ok") is False:
            return _ok(data)
        data["ok"] = True
        data["pair_via_pane"] = True
        return _ok(data)
    except Problem as exc:
        return _err(exc)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


def handle_job(args: dict | None = None, session_id: str | None = None, **kwargs: Any) -> str:
    try:
        a = args or {}
        op = str(a.get("op") or "")
        sid = _session_id(a, {**kwargs, "session_id": session_id or kwargs.get("session_id")})
        if op == "paid_run":
            return _ok(paid.run_paid(str(a.get("prompt") or ""), a.get("cwd") or paths.default_workspace()))
        _ensure()
        if op == "enqueue":
            if not sid:
                return _err(Problem(
                    "missing_session",
                    "Enqueue a job from the Hermes conversation bound to the Buffrizz pane.",
                    "Open the pane beside this chat, start the official TUI, then enqueue.",
                ))
            data = client.call("POST", "/jobs", {
                "session_id": sid,
                "prompt": a.get("prompt") or "",
                "cwd": a.get("cwd"),
            })
            if data.get("ok"):
                data["auto_submitted"] = False
                data["fix"] = "Ask the user to click Run in the Buffrizz pane. Do not try to auto-submit the free-tier session."
            return _ok(data)
        if op == "list":
            q = f"/jobs?detail=summary"
            if sid:
                q += f"&session={__import__('urllib.parse').quote(sid)}"
            return _ok(client.call("GET", q))
        if op == "status":
            job_id = str(a.get("job_id") or "")
            if not job_id:
                return _err(Problem("missing_job_id", "Pass job_id for status.", "Use op=list to see job ids."))
            return _ok(client.call("GET", f"/jobs/{job_id}?detail=full"))
        if op == "cancel":
            job_id = str(a.get("job_id") or "")
            if not job_id:
                return _err(Problem("missing_job_id", "Pass job_id for cancel."))
            return _ok(client.call("POST", f"/jobs/{job_id}/cancel", {}))
        if op == "result":
            job_id = str(a.get("job_id") or "")
            if not job_id:
                return _err(Problem("missing_job_id", "Pass job_id for result."))
            timeout = int(a.get("timeout_seconds") or 0)
            timeout = max(0, min(timeout, 600))
            if timeout <= 0:
                return _ok(client.call("GET", f"/jobs/{job_id}?detail=full"))
            import time
            deadline = time.time() + timeout
            data = client.call("GET", f"/jobs/{job_id}?detail=full")
            while time.time() < deadline and data.get("status") in {"queued", "running"}:
                time.sleep(0.4)
                data = client.call("GET", f"/jobs/{job_id}?detail=full")
            data["ok"] = data.get("ok", True)
            return _ok(data)
        return _err(Problem("invalid_op", f"Unknown op {op!r}.", "Use enqueue, list, status, cancel, result, or paid_run."))
    except Problem as exc:
        return _err(exc)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


def bind_tool_result(tool_name=None, args=None, result=None, session_id=None, **kwargs):
    """Bind a successful connect/enqueue to the host-supplied Hermes session id."""
    if tool_name not in {"buffrizz_status", "buffrizz_connect", "buffrizz_job"} or not session_id:
        return
    # Observation only; pairing and queue already used the host session id when present.
    return


def register_tools(ctx) -> None:
    handlers = {
        "buffrizz_status": handle_status,
        "buffrizz_connect": handle_connect,
        "buffrizz_job": handle_job,
    }
    for schema in SCHEMAS:
        handler = handlers[schema["name"]]
        options = dict(
            name=schema["name"],
            toolset=PLUGIN_ID,
            schema=schema,
            handler=handler,
            description=schema["description"],
            emoji="🦬",
        )
        try:
            params = inspect.signature(ctx.register_tool).parameters
        except (TypeError, ValueError):
            params = {}
        if params and not any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
            options = {k: v for k, v in options.items() if k in params}
        ctx.register_tool(**options)
