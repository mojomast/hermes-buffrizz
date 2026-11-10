#!/usr/bin/env python3
"""Offline stand-in for the official freebuff TUI. Used only in tests. No network."""
from __future__ import annotations

import os
import select
import sys
import time
from pathlib import Path

IDLE = "BUFFRIZZ_IDLE> "


def _cwd_from_args(argv: list[str]) -> str | None:
    args = list(argv)
    i = 0
    while i < len(args):
        if args[i] == "--cwd" and i + 1 < len(args):
            return args[i + 1]
        i += 1
    return None


def _write(text: str) -> None:
    sys.stdout.write(text)
    sys.stdout.flush()


def _read_available(timeout: float = 0.2) -> str:
    ready, _, _ = select.select([sys.stdin], [], [], timeout)
    if not ready:
        return ""
    return os.read(sys.stdin.fileno(), 4096).decode("utf-8", "replace")


def _extract_prompt(buf: str) -> tuple[str, str | None]:
    """Return leftover buffer and a completed prompt, if any."""
    start = "\x1b[200~"
    end = "\x1b[201~"
    if start in buf and end in buf:
        before, rest = buf.split(start, 1)
        if end in rest:
            body, after = rest.split(end, 1)
            after = after.lstrip("\r\n")
            return before + after, body
    if "\r" in buf or "\n" in buf:
        line, sep, rest = buf.replace("\r\n", "\n").replace("\r", "\n").partition("\n")
        if sep:
            return rest, line
    return buf, None


def _do_work(prompt: str, cwd: Path) -> None:
    _write(f"\nWorking on: {prompt.strip()[:120]}\n")
    if os.environ.get("BUFFRIZZ_FAKE_HANG") == "1":
        while True:
            time.sleep(60)
    if os.environ.get("BUFFRIZZ_FAKE_CRASH") == "1":
        _write("fake crash\n")
        sys.exit(1)
    target = cwd / "buffrizz_job_output.txt"
    with target.open("a", encoding="utf-8") as fh:
        fh.write(prompt.strip() + "\n")
    # Also drop a credential-like file so tests can assert redaction.
    secret = cwd / "credentials.json"
    if os.environ.get("BUFFRIZZ_FAKE_WRITE_SECRET") == "1":
        secret.write_text('{"token":"tok_should_be_redacted_value"}', encoding="utf-8")
    _write("Done.\nSponsored: fake ad stays visible\n")
    _write(IDLE)


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    if "-v" in argv or "--version" in argv:
        _write("freebuff-fake 0.0.0\n")
        return 0
    if "-h" in argv or "--help" in argv:
        _write("usage: freebuff [--cwd DIR] [login|doctor]\n")
        return 0
    if argv and argv[0] == "doctor":
        _write("fake doctor: ok\n")
        return 0
    if argv and argv[0] == "login":
        _write("Please sign in to Freebuff.\nVisit https://freebuff.com/login\n")
        while _read_available(1.0) is not None:
            chunk = _read_available(30.0)
            if chunk == "" and not select.select([sys.stdin], [], [], 0)[0]:
                # timeout with empty; keep waiting until EOF
                if sys.stdin.closed:
                    return 0
        return 0
    cwd = Path(_cwd_from_args(argv) or os.getcwd()).resolve()
    try:
        os.chdir(cwd)
    except OSError:
        pass
    if os.environ.get("BUFFRIZZ_FAKE_LOGIN") == "1":
        _write("Please sign in to Freebuff.\nVisit https://freebuff.com/login\nRun: freebuff login\n")
        buf = ""
        while True:
            buf += _read_available(1.0)
            if buf == "" and sys.stdin.closed:
                return 0
            # Stay on the login screen. Never auto-complete sign-in.
            if not buf and not select.select([sys.stdin], [], [], 0.5)[0]:
                continue
            # Discard input so tests can type without escaping the login gate.
            buf = ""
    _write("\x1b[2J\x1b[H")
    _write("Freebuff fake TUI\nSponsored: test advertisement\n")
    _write(IDLE)
    buf = ""
    while True:
        buf += _read_available(0.25)
        if not buf:
            # Detect EOF
            if not select.select([sys.stdin], [], [], 0)[0]:
                continue
            more = _read_available(0)
            if more == "":
                return 0
            buf += more
        buf, prompt = _extract_prompt(buf)
        if prompt is not None and prompt.strip():
            _do_work(prompt, cwd)
        elif prompt is not None:
            _write(IDLE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
