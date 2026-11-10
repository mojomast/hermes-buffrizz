"""Loopback supervisor that owns official Freebuff PTYs and the job queue."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import pty
import re
import secrets
import select
import signal
import struct
import sys
import termios
import threading
import time
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pyte

from . import PLUGIN_ID, PLUGIN_VERSION, env as envmod, gitutil, paths
from .errors import Problem
from .redact import redact_text

BIND_HOST = "127.0.0.1"
BODY_LIMIT = 256 * 1024
TRANSCRIPT_CAP = 80_000
DEFAULT_COLS = 100
DEFAULT_ROWS = 32
IDLE_MARKER = "BUFFRIZZ_IDLE>"
LOGIN_HINTS = re.compile(
    r"sign in|log in|login to|freebuff login|device code|authori[sz]e this|visit https://",
    re.I,
)
SPONSORED_HINT = re.compile(r"sponsored", re.I)
BRACKET_START = "\x1b[200~"
BRACKET_END = "\x1b[201~"


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _now() -> float:
    return time.time()


class PtySession:
    def __init__(self, session_id: str, cwd: Path, *, cols: int = DEFAULT_COLS, rows: int = DEFAULT_ROWS):
        self.session_id = session_id
        self.cwd = Path(cwd)
        self.cols = cols
        self.rows = rows
        self.master_fd: int | None = None
        self.proc: Any = None
        self.screen = pyte.Screen(cols, rows)
        self.stream = pyte.ByteStream(self.screen)
        self.transcript = bytearray()
        self.last_output_at = _now()
        self.started_at = _now()
        self.lock = threading.Lock()
        self.reader: threading.Thread | None = None
        self.binary: str | None = None
        self.continue_id: str | None = None
        self.worktree: dict | None = None
        self.bytes_written = 0
        self._stop = threading.Event()

    def start(self, binary: str, *, continue_id: str | None = None, home: Path | None = None) -> None:
        if not binary or not Path(binary).is_file():
            raise Problem(
                "freebuff_missing",
                "The official freebuff CLI was not found.",
                "Install it with `npm install -g freebuff`, then retry buffrizz_connect.",
            )
        cwd = self.cwd
        cwd.mkdir(parents=True, exist_ok=True)
        argv = [binary, "--cwd", str(cwd)]
        if continue_id:
            argv.extend(["--continue", continue_id])
        child = envmod.child_env(home=home)
        master, slave = pty.openpty()
        try:
            _set_winsize(master, self.rows, self.cols)
            self.proc = __import__("subprocess").Popen(
                argv,
                stdin=slave,
                stdout=slave,
                stderr=slave,
                cwd=str(cwd),
                env=child,
                close_fds=True,
                start_new_session=True,
            )
        except Exception:
            os.close(master)
            os.close(slave)
            raise
        os.close(slave)
        flags = fcntl.fcntl(master, fcntl.F_GETFL)
        fcntl.fcntl(master, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        self.master_fd = master
        self.binary = binary
        self.continue_id = continue_id
        self._stop.clear()
        self.reader = threading.Thread(target=self._read_loop, name=f"buffrizz-pty-{self.session_id}", daemon=True)
        self.reader.start()

    def _read_loop(self) -> None:
        fd = self.master_fd
        if fd is None:
            return
        while not self._stop.is_set():
            try:
                ready, _, _ = select.select([fd], [], [], 0.25)
            except (OSError, ValueError):
                break
            if not ready:
                continue
            try:
                chunk = os.read(fd, 8192)
            except OSError:
                break
            if not chunk:
                break
            with self.lock:
                self.stream.feed(chunk)
                self.transcript.extend(chunk)
                if len(self.transcript) > TRANSCRIPT_CAP:
                    del self.transcript[:-TRANSCRIPT_CAP]
                self.last_output_at = _now()
        self._stop.set()

    def is_alive(self) -> bool:
        if self.proc is None:
            return False
        return self.proc.poll() is None

    def write(self, data: bytes) -> None:
        if not self.is_alive() or self.master_fd is None:
            raise Problem("session_not_running", "The official Freebuff session is not running.", "Call buffrizz_connect action=start and sign in in the pane.")
        os.write(self.master_fd, data)
        self.bytes_written += len(data)

    def paste(self, text: str) -> None:
        # Strip ESC so a prompt cannot inject TUI control sequences other than the paste itself.
        clean = (text or "").replace("\x1b", "")
        payload = f"{BRACKET_START}{clean}{BRACKET_END}\r"
        self.write(payload.encode("utf-8", "replace"))

    def resize(self, cols: int, rows: int) -> None:
        cols = max(20, min(240, int(cols)))
        rows = max(8, min(80, int(rows)))
        self.cols, self.rows = cols, rows
        with self.lock:
            self.screen.resize(rows, cols)
        if self.master_fd is not None:
            _set_winsize(self.master_fd, rows, cols)

    def screen_state(self) -> dict:
        with self.lock:
            lines = [line.rstrip() for line in self.screen.display]
            cursor = {"x": int(self.screen.cursor.x), "y": int(self.screen.cursor.y)}
            text = "\n".join(lines)
            excerpt = redact_text(self.transcript.decode("utf-8", "replace"))
        signed = _signed_in_from_text(text)
        return {
            "cols": self.cols,
            "rows": self.rows,
            "lines": lines,
            "cursor": cursor,
            "signed_in": signed,
            "alive": self.is_alive(),
            "last_output_at": self.last_output_at,
            "excerpt": excerpt[-2000:],
        }

    def contains_idle_marker(self) -> bool:
        with self.lock:
            text = "\n".join(self.screen.display)
        return IDLE_MARKER in text

    def stop(self, *, timeout: float = 5.0) -> None:
        self._stop.set()
        proc = self.proc
        if proc is not None and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except OSError:
                try:
                    proc.terminate()
                except OSError:
                    pass
            try:
                proc.wait(timeout=timeout)
            except Exception:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except OSError:
                    pass
                try:
                    proc.wait(timeout=2)
                except Exception:
                    pass
        if self.master_fd is not None:
            try:
                os.close(self.master_fd)
            except OSError:
                pass
            self.master_fd = None


def _set_winsize(fd: int, rows: int, cols: int) -> None:
    try:
        packed = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, packed)
    except OSError:
        pass


def _signed_in_from_text(text: str) -> str:
    if LOGIN_HINTS.search(text or ""):
        return "false"
    if IDLE_MARKER in (text or "") or SPONSORED_HINT.search(text or ""):
        return "true"
    return "unknown"


class Supervisor:
    def __init__(self, data_dir: Path, *, freebuff_bin: str | None = None, home: Path | None = None):
        paths.set_test_overrides(data_dir=data_dir, freebuff=Path(freebuff_bin) if freebuff_bin else None, home=home)
        self.data_dir = Path(data_dir).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.freebuff_bin = freebuff_bin
        self.home = home
        self.token = secrets.token_urlsafe(32)
        self.sessions: dict[str, PtySession] = {}
        self.jobs: dict[str, dict] = {}
        self.lock = threading.RLock()
        self.httpd: ThreadingHTTPServer | None = None
        self._jobs_path = self.data_dir / "jobs.json"

    def binary(self) -> str:
        found = self.freebuff_bin or envmod.resolve_freebuff()
        if not found:
            raise Problem(
                "freebuff_missing",
                "The official freebuff CLI was not found on PATH.",
                "Install it with `npm install -g freebuff` and confirm `freebuff -v` works.",
            )
        return found

    def connect(self, session_id: str, action: str, cwd: str | None = None, continue_id: str | None = None) -> dict:
        session_id = (session_id or "").strip()
        if not session_id:
            raise Problem("missing_session", "A Hermes session id is required.", "Open a conversation and use the Buffrizz pane beside it.")
        if action == "status":
            return self._session_status(session_id)
        if action == "stop":
            return self._stop_session(session_id)
        if action != "start":
            raise Problem("invalid_action", "action must be start, stop, or status.")
        target = paths.resolve_allowlisted(cwd or "")
        with self.lock:
            existing = self.sessions.get(session_id)
            if existing and existing.is_alive():
                if Path(existing.cwd).resolve() != target:
                    raise Problem(
                        "session_busy",
                        "This conversation already has a Freebuff session in a different directory.",
                        "Stop the current session before starting another cwd, or keep using the bound project.",
                    )
                return self._session_status(session_id)
            worktree = None
            start_cwd = target
            if gitutil.is_git_repo(target):
                worktree = gitutil.ensure_session_worktree(target, session_id)
                start_cwd = Path(worktree["worktree"])
            session = PtySession(session_id, start_cwd)
            session.worktree = worktree
            session.start(self.binary(), continue_id=continue_id, home=self.home)
            self.sessions[session_id] = session
        return self._session_status(session_id)

    def _stop_session(self, session_id: str) -> dict:
        with self.lock:
            session = self.sessions.pop(session_id, None)
        if session:
            session.stop()
        return {"ok": True, "stopped": bool(session), "session_id": session_id}

    def _session_status(self, session_id: str, *, detail: str = "summary") -> dict:
        with self.lock:
            session = self.sessions.get(session_id)
            jobs = [self._public_job(j, detail=detail) for j in self.jobs.values() if j.get("session_id") == session_id]
        payload = {
            "ok": True,
            "session_id": session_id,
            "running": bool(session and session.is_alive()),
            "cwd": str(session.cwd) if session else None,
            "worktree": session.worktree if session else None,
            "signed_in": session.screen_state()["signed_in"] if session else "unknown",
            "pid": (session.proc.pid if session and session.proc is not None else None),
            "bytes_written": session.bytes_written if session else 0,
            "jobs": jobs if detail == "full" else [{"id": j["id"], "status": j["status"]} for j in jobs],
        }
        if detail == "full" and session:
            payload["screen"] = session.screen_state()
        return payload

    def enqueue(self, session_id: str, prompt: str, cwd: str | None = None) -> dict:
        prompt = (prompt or "").strip()
        if not prompt:
            raise Problem("missing_prompt", "Provide a prompt to enqueue.", "Pass the coding task as prompt.")
        if len(prompt) > 100_000:
            raise Problem("prompt_too_large", "Prompt exceeds 100 KiB.")
        with self.lock:
            session = self.sessions.get(session_id)
            if cwd:
                target = paths.resolve_allowlisted(cwd)
            elif session:
                target = Path(session.cwd)
            else:
                raise Problem(
                    "no_session",
                    "No official Freebuff session is bound to this conversation.",
                    "Call buffrizz_connect action=start with an allowlisted cwd, then enqueue.",
                )
            if session and Path(session.cwd).resolve() != target.resolve() and not _same_repo(session.cwd, target):
                # Allow the allowlisted root when the session is in its worktree.
                if not _is_under(session.cwd, target):
                    raise Problem(
                        "cwd_mismatch",
                        "The job cwd does not match the running session.",
                        "Enqueue against the bound project, or start a new session.",
                    )
            job_id = _uid("job")
            job = {
                "id": job_id,
                "session_id": session_id,
                "cwd": str(session.cwd if session else target),
                "repo": str(Path(cwd).resolve()) if cwd else (session.worktree or {}).get("worktree", str(session.cwd if session else target)),
                "prompt": prompt,
                "status": "queued",
                "created": _now(),
                "started": None,
                "finished": None,
                "branch": None,
                "base_sha": None,
                "error": None,
                "code": None,
                "result": None,
                "cancel": False,
                "submitted": False,
            }
            self.jobs[job_id] = job
            self._persist_jobs()
        return {"ok": True, "job_id": job_id, "status": "queued", "auto_submitted": False}

    def run_job(self, job_id: str, *, session_id: str | None = None) -> dict:
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                raise Problem("unknown_job", "No job with that id.")
            if session_id and job["session_id"] != session_id:
                raise Problem("job_session_mismatch", "That job belongs to a different Hermes conversation.")
            if job["status"] != "queued":
                raise Problem("job_not_queued", f"Job is {job['status']}, not queued.")
            session = self.sessions.get(job["session_id"])
            if not session or not session.is_alive():
                raise Problem(
                    "session_not_running",
                    "Start the official Freebuff TUI and sign in before clicking Run.",
                    "Open the Buffrizz pane, start the session, complete login, then click Run.",
                )
            worktree = Path(session.cwd)
            if gitutil.is_git_repo(worktree):
                info = gitutil.create_job_branch(worktree, job["id"])
                job["branch"] = info["branch"]
                job["base_sha"] = info["base_sha"]
            else:
                raise Problem(
                    "not_a_git_repo",
                    "Jobs need a git repository so results can be returned as a diff.",
                    "Use an allowlisted git project.",
                )
            job["status"] = "running"
            job["started"] = _now()
            job["submitted"] = True
            self._persist_jobs()
            prompt = job["prompt"]
            idle_seconds = paths.settings_int("idle_seconds", 12, minimum=2, maximum=120)
            timeout = paths.settings_int("job_timeout_seconds", 1800, minimum=30, maximum=7200)
        session.paste(prompt)
        pasted_at = _now()
        thread = threading.Thread(
            target=self._watch_job,
            args=(job_id, pasted_at, idle_seconds, timeout),
            name=f"buffrizz-job-{job_id}",
            daemon=True,
        )
        thread.start()
        return {"ok": True, "job_id": job_id, "status": "running"}

    def _watch_job(self, job_id: str, pasted_at: float, idle_seconds: int, timeout: int) -> None:
        deadline = pasted_at + timeout
        try:
            while True:
                with self.lock:
                    job = self.jobs.get(job_id)
                    session = self.sessions.get(job["session_id"]) if job else None
                    if not job:
                        return
                    if job.get("cancel"):
                        self._finish_job(job, "cancelled")
                        return
                if session is None or not session.is_alive():
                    self._finish_job(job, "failed", code="session_ended", error="The official Freebuff process ended before the job went idle.")
                    return
                if _now() >= deadline:
                    self._finish_job(job, "timed_out", code="timeout", error="The job reached job_timeout_seconds without going idle.")
                    return
                if session.last_output_at >= pasted_at and (_now() - session.last_output_at) >= idle_seconds:
                    self._finish_job(job, "succeeded")
                    return
                if session.contains_idle_marker() and (_now() - pasted_at) >= 0.2 and session.last_output_at >= pasted_at:
                    # Fake (and any official UI that prints the marker) can finish faster than idle_seconds.
                    if (_now() - session.last_output_at) >= min(1.0, idle_seconds):
                        self._finish_job(job, "succeeded")
                        return
                time.sleep(0.2)
        except Exception as exc:  # noqa: BLE001
            try:
                self._finish_job(job, "failed", code="watcher_error", error=str(exc)[:300])
            except Exception:
                pass

    def _finish_job(self, job: dict, status: str, *, code: str | None = None, error: str | None = None) -> None:
        with self.lock:
            if job.get("finished"):
                return
            job["status"] = status
            job["finished"] = _now()
            job["code"] = code
            job["error"] = error
            session = self.sessions.get(job["session_id"])
            excerpt = ""
            if session:
                excerpt = session.screen_state().get("excerpt") or ""
            result = None
            if job.get("base_sha") and session:
                try:
                    result = gitutil.collect_result(Path(session.cwd), job["base_sha"])
                except Problem as exc:
                    job["code"] = job["code"] or exc.code
                    job["error"] = job["error"] or str(exc)
                except Exception as exc:  # noqa: BLE001
                    job["code"] = job["code"] or "diff_failed"
                    job["error"] = job["error"] or str(exc)[:300]
            if result is not None:
                result["transcript_excerpt"] = redact_text(excerpt)
                result["branch"] = job.get("branch")
                result["worktree"] = str(session.cwd) if session else job.get("cwd")
            job["result"] = result
            self._persist_jobs()

    def cancel(self, job_id: str) -> dict:
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                raise Problem("unknown_job", "No job with that id.")
            if job["status"] in {"succeeded", "failed", "cancelled", "timed_out"}:
                return {"ok": True, "job_id": job_id, "status": job["status"]}
            job["cancel"] = True
            if job["status"] == "queued":
                job["status"] = "cancelled"
                job["finished"] = _now()
                self._persist_jobs()
        return {"ok": True, "job_id": job_id, "status": "cancelled" if job["status"] == "cancelled" else job["status"]}

    def job_view(self, job_id: str, *, detail: str = "summary") -> dict:
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                raise Problem("unknown_job", "No job with that id.")
            return {"ok": True, **self._public_job(job, detail=detail)}

    def list_jobs(self, session_id: str | None = None, *, detail: str = "summary") -> dict:
        with self.lock:
            jobs = list(self.jobs.values())
            if session_id:
                jobs = [j for j in jobs if j.get("session_id") == session_id]
            return {"ok": True, "jobs": [self._public_job(j, detail=detail) for j in jobs]}

    def _public_job(self, job: dict, *, detail: str = "summary") -> dict:
        out = {
            "id": job["id"],
            "status": job["status"],
            "session_id": job["session_id"],
            "cwd": job.get("cwd"),
            "branch": job.get("branch"),
            "created": job.get("created"),
            "started": job.get("started"),
            "finished": job.get("finished"),
            "auto_submitted": bool(job.get("submitted")),
        }
        if job.get("error"):
            out["error"] = job["error"]
            out["code"] = job.get("code")
        if detail == "full":
            out["prompt"] = job.get("prompt")
            out["result"] = job.get("result")
            out["base_sha"] = job.get("base_sha")
        elif job.get("result"):
            result = dict(job["result"])
            result.pop("status_porcelain", None)
            out["result"] = result
        return out

    def write_input(self, session_id: str, *, text: str | None = None, data: str | None = None) -> dict:
        with self.lock:
            session = self.sessions.get(session_id)
        if not session:
            raise Problem("session_not_running", "No official Freebuff session is running in this pane.")
        payload = data if data is not None else text
        if payload is None:
            raise Problem("missing_input", "Provide text or data to send to the official TUI.")
        session.write(payload.encode("utf-8", "replace") if isinstance(payload, str) else payload)
        return {"ok": True}

    def screen(self, session_id: str) -> dict:
        with self.lock:
            session = self.sessions.get(session_id)
        if not session:
            raise Problem("session_not_running", "No official Freebuff session is running in this pane.")
        return {"ok": True, **session.screen_state(), "cwd": str(session.cwd)}

    def resize(self, session_id: str, cols: int, rows: int) -> dict:
        with self.lock:
            session = self.sessions.get(session_id)
        if not session:
            raise Problem("session_not_running", "No official Freebuff session is running in this pane.")
        session.resize(cols, rows)
        return {"ok": True, "cols": session.cols, "rows": session.rows}

    def global_status(self, session_id: str | None = None, *, detail: str = "summary") -> dict:
        binary = envmod.resolve_freebuff()
        allow = [str(p) for p in paths.allowlist_roots()]
        with self.lock:
            running = {
                sid: {"cwd": str(sess.cwd), "alive": sess.is_alive(), "signed_in": sess.screen_state()["signed_in"]}
                for sid, sess in self.sessions.items()
            }
        payload = {
            "ok": True,
            "plugin": PLUGIN_ID,
            "version": PLUGIN_VERSION,
            "freebuff_installed": bool(binary),
            "freebuff_path": binary if detail == "full" else (str(Path(binary).name) if binary else None),
            "allowlist_roots": allow,
            "default_workspace": str(paths.default_workspace()),
            "paid_unattended": paths.settings_bool("paid_unattended", False),
            "sessions": running,
            "jobs": self.list_jobs(session_id, detail=detail)["jobs"],
        }
        if session_id:
            payload.update({k: v for k, v in self._session_status(session_id, detail=detail).items() if k != "ok"})
        return payload

    def _persist_jobs(self) -> None:
        public = []
        for job in self.jobs.values():
            item = {k: v for k, v in job.items() if k != "prompt"}
            item["prompt_len"] = len(job.get("prompt") or "")
            public.append(item)
        paths.dump_json(self._jobs_path, {"jobs": public})

    def shutdown(self) -> None:
        with self.lock:
            sessions = list(self.sessions.values())
            self.sessions.clear()
        for session in sessions:
            session.stop()
        httpd = self.httpd
        if httpd:
            threading.Thread(target=httpd.shutdown, daemon=True).start()


def _same_repo(a: Path, b: Path) -> bool:
    try:
        return gitutil.is_git_repo(a) and gitutil.is_git_repo(b) and gitutil.common_git_dir(a) == gitutil.common_git_dir(b)
    except Exception:
        return False


def _is_under(child: Path, root: Path) -> bool:
    try:
        return Path(child).resolve() == Path(root).resolve() or Path(child).resolve().is_relative_to(Path(root).resolve())
    except Exception:
        return False


def make_handler(supervisor: Supervisor) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

        def _unauthorized(self) -> None:
            self._send(401, {"ok": False, "error": "unauthorized", "code": "unauthorized"})

        def _authorized(self) -> bool:
            header = self.headers.get("X-Buffrizz-Token") or ""
            auth = self.headers.get("Authorization") or ""
            token = header
            if auth.lower().startswith("bearer "):
                token = token or auth[7:].strip()
            if not token or not secrets.compare_digest(token, supervisor.token):
                return False
            return True

        def _read_body(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if length > BODY_LIMIT:
                raise Problem("too_large", "Request exceeds the 256 KiB body limit.")
            raw = self.rfile.read(length) if length else b"{}"
            if not raw:
                return {}
            try:
                value = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError as exc:
                raise Problem("invalid_request", f"Invalid JSON: {exc}") from exc
            if not isinstance(value, dict):
                raise Problem("invalid_request", "Expected a JSON object.")
            return value

        def _send(self, status: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)

        def _dispatch(self, method: str) -> None:
            if not self._authorized():
                self._unauthorized()
                return
            parsed = urlparse(self.path)
            route = parsed.path
            query = {k: v[0] for k, v in parse_qs(parsed.query).items() if v}
            try:
                body = self._read_body() if method in {"POST", "PUT"} else {}
                result = _route(supervisor, method, route, query, body)
                self._send(200, result if isinstance(result, dict) else {"ok": True, "data": result})
            except Problem as exc:
                self._send(400, exc.to_dict())
            except Exception as exc:  # noqa: BLE001
                self._send(500, {"ok": False, "error": "request_failed", "code": "request_failed", "message": str(exc)[:300]})

        def do_GET(self) -> None:  # noqa: N802
            self._dispatch("GET")

        def do_POST(self) -> None:  # noqa: N802
            self._dispatch("POST")

    return Handler


def _route(sup: Supervisor, method: str, route: str, query: dict, body: dict) -> dict:
    if route == "/health" and method == "GET":
        return {"ok": True, "plugin": PLUGIN_ID, "version": PLUGIN_VERSION, "body_limit": BODY_LIMIT}
    if route == "/status" and method == "GET":
        return sup.global_status(query.get("session"), detail=query.get("detail") or "summary")
    if route == "/connect" and method == "POST":
        return sup.connect(
            str(body.get("session_id") or query.get("session") or ""),
            str(body.get("action") or "status"),
            cwd=body.get("cwd"),
            continue_id=body.get("continue_id"),
        )
    if route == "/jobs" and method == "GET":
        return sup.list_jobs(query.get("session"), detail=query.get("detail") or "summary")
    if route == "/jobs" and method == "POST":
        return sup.enqueue(str(body.get("session_id") or ""), str(body.get("prompt") or ""), cwd=body.get("cwd"))
    if route.startswith("/jobs/") and route.endswith("/run") and method == "POST":
        job_id = route.split("/")[2]
        return sup.run_job(job_id, session_id=body.get("session_id") or query.get("session"))
    if route.startswith("/jobs/") and route.endswith("/cancel") and method == "POST":
        return sup.cancel(route.split("/")[2])
    if route.startswith("/jobs/") and method == "GET":
        return sup.job_view(route.split("/")[2], detail=query.get("detail") or "full")
    if route == "/screen" and method == "GET":
        return sup.screen(str(query.get("session") or body.get("session_id") or ""))
    if route == "/input" and method == "POST":
        return sup.write_input(str(body.get("session_id") or ""), text=body.get("text"), data=body.get("data"))
    if route == "/resize" and method == "POST":
        return sup.resize(str(body.get("session_id") or ""), int(body.get("cols") or DEFAULT_COLS), int(body.get("rows") or DEFAULT_ROWS))
    if route == "/shutdown" and method == "POST":
        threading.Thread(target=sup.shutdown, daemon=True).start()
        return {"ok": True, "stopping": True}
    raise Problem("not_found", f"Unknown route {route}")


def write_session_file(data_dir: Path, port: int, pid: int, token: str) -> Path:
    path = Path(data_dir) / "supervisor.json"
    paths.dump_json(path, {"bind": BIND_HOST, "port": port, "pid": pid, "token": token}, mode=0o600)
    os.chmod(path, 0o600)
    return path


def serve(data_dir: Path, *, freebuff_bin: str | None = None, home: Path | None = None, port: int = 0) -> Supervisor:
    supervisor = Supervisor(data_dir, freebuff_bin=freebuff_bin, home=home)
    httpd = ThreadingHTTPServer((BIND_HOST, port), make_handler(supervisor))
    supervisor.httpd = httpd
    write_session_file(data_dir, httpd.server_address[1], os.getpid(), supervisor.token)
    return supervisor


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Buffrizz loopback supervisor")
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--freebuff-bin")
    parser.add_argument("--home")
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args(argv)
    data_dir = Path(args.data_dir).resolve()
    lock_path = data_dir / "supervisor.lock"
    data_dir.mkdir(parents=True, exist_ok=True)
    lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        sys.stderr.write("buffrizz supervisor already running for this data dir\n")
        return 1
    supervisor = serve(data_dir, freebuff_bin=args.freebuff_bin, home=args.home, port=args.port)
    httpd = supervisor.httpd
    assert httpd is not None

    def _stop(*_a: object) -> None:
        supervisor.shutdown()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    try:
        httpd.serve_forever(poll_interval=0.3)
    finally:
        supervisor.shutdown()
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
