"""Minimal child environments. Never inherit the agent process environment."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from . import paths

# Non-secret session plumbing the official CLI may need (keyring, git ssh).
# Names only — values are copied from the current process when present.
_SESSION_KEYS = (
    "USER",
    "LOGNAME",
    "TZ",
    "XDG_RUNTIME_DIR",
    "XDG_SESSION_TYPE",
    "DBUS_SESSION_BUS_ADDRESS",
    "SSH_AUTH_SOCK",
)

_STD_PATHS = (
    "/opt/homebrew/bin",
    "/usr/local/bin",
    "/usr/bin",
    "/bin",
)


def _which(name: str) -> str | None:
    """Locate a binary. Search process PATH plus standard dirs; do not copy PATH."""
    found = shutil.which(name)
    if found:
        return found
    extra = os.pathsep.join(_STD_PATHS)
    home_local = paths.user_home() / ".local" / "bin"
    search = os.pathsep.join([str(home_local), extra])
    return shutil.which(name, path=search)


def resolve_freebuff() -> str | None:
    override = paths.test_freebuff()
    if override is not None:
        candidate = Path(override)
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate.resolve())
        return None
    return _which("freebuff")


def resolve_node() -> str | None:
    return _which("node")


def child_path(*extra_bins: str | None) -> str:
    dirs: list[str] = []
    for bin_path in extra_bins:
        if bin_path:
            parent = str(Path(bin_path).resolve().parent)
            if parent not in dirs:
                dirs.append(parent)
    home_local = str(paths.user_home() / ".local" / "bin")
    for item in (*_STD_PATHS, home_local):
        if item not in dirs and Path(item).is_dir():
            dirs.append(item)
    # Always include POSIX basics even if missing (recovery).
    for item in ("/usr/bin", "/bin"):
        if item not in dirs:
            dirs.append(item)
    return os.pathsep.join(dirs)


def child_env(*, home: Path | None = None, extra: dict[str, str] | None = None) -> dict[str, str]:
    """Exact-name allowlist. Does not copy os.environ or NODE_OPTIONS."""
    env: dict[str, str] = {}
    home_path = Path(home) if home is not None else paths.user_home()
    env["HOME"] = str(home_path)
    env["PATH"] = child_path(resolve_freebuff(), resolve_node())
    env["TERM"] = "xterm-256color"
    env["LANG"] = "C.UTF-8"
    env["LC_ALL"] = "C.UTF-8"
    env["TMPDIR"] = str(paths.tmp_dir())
    env["NO_TELEMETRY"] = "1"
    for key in _SESSION_KEYS:
        value = os.environ.get(key)
        if isinstance(value, str) and value and "\x00" not in value:
            env[key] = value
    if extra:
        for key, value in extra.items():
            if not isinstance(key, str) or not key or not isinstance(value, str):
                continue
            env[key] = value
    return env


def git_env() -> dict[str, str]:
    return child_env()
