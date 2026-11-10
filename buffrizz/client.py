"""Talk to the loopback supervisor. Never prints the token."""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from . import env as envmod, paths
from .errors import Problem

SESSION_FILE = "supervisor.json"
_START_WAIT = 6.0


def session_file() -> Path:
    return paths.data_dir() / SESSION_FILE


def _load_session() -> dict | None:
    path = session_file()
    if not path.is_file():
        return None
    try:
        if (path.stat().st_mode & 0o777) != 0o600:
            # Tighten if a copy got wider permissions, then still use it only on loopback.
            os.chmod(path, 0o600)
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("bind") != "127.0.0.1":
        return None
    return data


def _pid_alive(pid: int) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    # Linux: treat zombies as dead.
    stat = Path(f"/proc/{pid}/stat")
    if stat.is_file():
        try:
            text = stat.read_text()
            state = text.rsplit(")", 1)[1].split()[0]
            if state == "Z":
                return False
        except (OSError, IndexError):
            pass
    return True


def _request(session: dict, method: str, route: str, payload: dict | None = None, timeout: float = 8.0) -> dict:
    port = int(session["port"])
    url = f"http://127.0.0.1:{port}{route}"
    body = None
    headers = {"X-Buffrizz-Token": str(session["token"]), "Accept": "application/json"}
    if payload is not None or method != "GET":
        raw = json.dumps(payload or {}).encode("utf-8")
        body = raw
        headers["Content-Type"] = "application/json"
        headers["Content-Length"] = str(len(raw))
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", "replace")
        try:
            data = json.loads(text) if text else {}
        except json.JSONDecodeError:
            data = {"ok": False, "error": "http_error", "code": "http_error", "message": str(exc)}
        if isinstance(data, dict):
            data.pop("token", None)
            if "ok" not in data:
                data["ok"] = False
            return data
        raise Problem("http_error", f"Supervisor HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise Problem("supervisor_unavailable", "The Buffrizz supervisor is not reachable.", "Retry the tool; the supervisor will restart if needed.") from exc
    try:
        data = json.loads(text) if text else {"ok": True}
    except json.JSONDecodeError as exc:
        raise Problem("invalid_response", "Supervisor returned invalid JSON.") from exc
    if isinstance(data, dict):
        data.pop("token", None)
        return data
    return {"ok": False, "error": "invalid_response", "code": "invalid_response"}


def health(session: dict | None = None) -> dict | None:
    session = session or _load_session()
    if not session or not _pid_alive(int(session.get("pid") or 0)):
        return None
    try:
        return _request(session, "GET", "/health", timeout=2.0)
    except Problem:
        return None


def start_supervisor() -> dict:
    existing = _load_session()
    ok = health(existing)
    if ok and existing:
        return existing
    data_dir = paths.data_dir()
    plugin_root = Path(__file__).resolve().parents[1]
    args = [sys.executable, "-m", "buffrizz.supervisor", "--data-dir", str(data_dir)]
    binary = paths.test_freebuff()
    if binary:
        args.extend(["--freebuff-bin", str(binary)])
    home = None
    # tests may set a fake HOME via paths._TEST_HOME
    from . import paths as p

    if getattr(p, "_TEST_HOME", None) is not None:
        args.extend(["--home", str(p._TEST_HOME)])
    log_path = data_dir / "supervisor.log"
    child = envmod.child_env()
    # The supervisor is our code and needs to import buffrizz.
    child["PYTHONPATH"] = os.pathsep.join([str(plugin_root), child.get("PYTHONPATH", "")]).strip(os.pathsep)
    child["PYTHONUNBUFFERED"] = "1"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "ab") as log:
        __import__("subprocess").Popen(
            args,
            cwd=str(plugin_root),
            env=child,
            stdout=log,
            stderr=log,
            start_new_session=True,
            close_fds=True,
        )
    deadline = time.time() + _START_WAIT
    while time.time() < deadline:
        time.sleep(0.1)
        session = _load_session()
        if health(session):
            return session  # type: ignore[return-value]
    raise Problem(
        "supervisor_failed",
        "The Buffrizz supervisor did not start.",
        "See the supervisor.log in the Buffrizz plugin data directory.",
    )


def ensure() -> dict:
    return start_supervisor()


def call(method: str, route: str, payload: dict | None = None, *, timeout: float = 8.0) -> dict:
    session = ensure()
    data = _request(session, method, route, payload, timeout=timeout)
    return data


def strip_secrets(payload: dict) -> dict:
    out = dict(payload)
    out.pop("token", None)
    out.pop("pairingSecret", None)
    out.pop("api_key", None)
    return out
