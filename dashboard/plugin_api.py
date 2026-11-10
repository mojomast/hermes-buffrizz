"""Hermes authenticates and profile-scopes this router before dispatching it."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from fastapi import APIRouter, Request

_root = Path(__file__).resolve().parents[1]
_name = "_buffrizz_backend_" + __import__("hashlib").sha256(str(_root).encode()).hexdigest()[:12]
if _root.as_posix() not in sys.path:
    sys.path.insert(0, str(_root))
if _name not in sys.modules:
    spec = importlib.util.spec_from_file_location(
        _name,
        _root / "buffrizz" / "__init__.py",
        submodule_search_locations=[str(_root / "buffrizz")],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[_name] = module
    spec.loader.exec_module(module)

client = __import__(_name + ".client", fromlist=["call", "ensure"])
errors = __import__(_name + ".errors", fromlist=["Problem"])
Problem = errors.Problem
router = APIRouter()
BODY_LIMIT = 256 * 1024


async def body(request: Request, limit: int = BODY_LIMIT) -> dict:
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise Problem("too_large", "Request exceeds the 256 KiB body limit.")
        chunks.append(chunk)
    value = json.loads(b"".join(chunks) or b"{}")
    if not isinstance(value, dict):
        raise Problem("invalid_request", "Expected a JSON object.")
    return value


def envelope(fn, *args, **kwargs):
    try:
        data = fn(*args, **kwargs)
        if isinstance(data, dict):
            data.setdefault("ok", True)
            data.pop("token", None)
            return data
        return {"ok": True, "data": data}
    except Problem as exc:
        return exc.to_dict()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "code": "request_failed", "error": "request_failed", "message": str(exc)[:300]}


def _call(method: str, route: str, payload: dict | None = None, timeout: float = 8.0) -> dict:
    client.ensure()
    return client.call(method, route, payload, timeout=timeout)


@router.get("/state")
def state(session: str = "", detail: str = "summary"):
    def read():
        q = f"/status?detail={detail or 'summary'}"
        if session:
            q += f"&session={__import__('urllib.parse').quote(session)}"
        return _call("GET", q)
    return envelope(read)


@router.get("/screen")
def screen(session: str):
    return envelope(_call, "GET", f"/screen?session={__import__('urllib.parse').quote(session)}")


@router.post("/connect")
async def connect(request: Request):
    try:
        data = await body(request)
        return envelope(_call, "POST", "/connect", data)
    except Problem as exc:
        return exc.to_dict()


@router.post("/input")
async def input_route(request: Request):
    try:
        data = await body(request, 16384)
        return envelope(_call, "POST", "/input", data)
    except Problem as exc:
        return exc.to_dict()


@router.post("/resize")
async def resize(request: Request):
    try:
        data = await body(request, 4096)
        return envelope(_call, "POST", "/resize", data)
    except Problem as exc:
        return exc.to_dict()


@router.post("/jobs/{job_id}/run")
async def run_job(job_id: str, request: Request):
    try:
        data = await body(request)
        data = dict(data)
        return envelope(_call, "POST", f"/jobs/{job_id}/run", data)
    except Problem as exc:
        return exc.to_dict()


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    return envelope(_call, "POST", f"/jobs/{job_id}/cancel", {})


@router.post("/jobs")
async def enqueue(request: Request):
    try:
        data = await body(request)
        return envelope(_call, "POST", "/jobs", data)
    except Problem as exc:
        return exc.to_dict()


@router.get("/jobs")
def jobs(session: str = ""):
    q = "/jobs?detail=summary"
    if session:
        q += f"&session={__import__('urllib.parse').quote(session)}"
    return envelope(_call, "GET", q)
