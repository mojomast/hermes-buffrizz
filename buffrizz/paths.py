"""Profile-scoped data, allowlisted working directories, and test overrides."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable

from . import PLUGIN_ID
from .errors import Problem

# Filesystem roots and near-roots that may never be an allowlist entry.
_BLOCKED_ROOTS = {
    Path("/"),
    Path("/home"),
    Path("/Users"),
    Path("/private"),
    Path("/opt"),
    Path("/usr"),
    Path("/var"),
    Path("/tmp"),
    Path("/etc"),
    Path("/root"),
    Path("/System"),
    Path("/Library"),
    Path("/Applications"),
}

_TEST_DATA_DIR: Path | None = None
_TEST_FREEBUFF: Path | None = None
_TEST_HOME: Path | None = None
_TEST_SETTINGS: dict[str, Any] | None = None


def set_test_overrides(
    *,
    data_dir: Path | None = None,
    freebuff: Path | None = None,
    home: Path | None = None,
    settings: dict[str, Any] | None = None,
    clear: bool = False,
) -> None:
    """Test-only process-local overrides. Never read from tool arguments or env."""
    global _TEST_DATA_DIR, _TEST_FREEBUFF, _TEST_HOME, _TEST_SETTINGS
    if clear:
        _TEST_DATA_DIR = _TEST_FREEBUFF = _TEST_HOME = _TEST_SETTINGS = None
        return
    if data_dir is not None:
        _TEST_DATA_DIR = Path(data_dir)
    if freebuff is not None:
        _TEST_FREEBUFF = Path(freebuff)
    if home is not None:
        _TEST_HOME = Path(home)
    if settings is not None:
        _TEST_SETTINGS = dict(settings)
        try:
            persist_settings(_TEST_SETTINGS)
        except OSError:
            pass


def data_dir() -> Path:
    if _TEST_DATA_DIR is not None:
        root = _TEST_DATA_DIR
    else:
        from plugins.plugin_storage import plugin_data_dir

        root = plugin_data_dir(PLUGIN_ID)
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def user_home() -> Path:
    if _TEST_HOME is not None:
        return Path(_TEST_HOME).resolve()
    return Path.home().resolve()


def test_freebuff() -> Path | None:
    return _TEST_FREEBUFF


def default_workspace() -> Path:
    path = data_dir() / "workspaces"
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def worktree_root() -> Path:
    path = data_dir() / "worktrees"
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def tmp_dir() -> Path:
    path = data_dir() / "tmp"
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def settings_file() -> Path:
    return data_dir() / "settings.json"


def _read_settings_file() -> dict[str, Any]:
    path = settings_file()
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(raw) if isinstance(raw, dict) else {}


def persist_settings(settings: dict[str, Any]) -> None:
    dump_json(settings_file(), settings, mode=0o600)


def load_hermes_settings() -> dict[str, Any]:
    """Merge optional settings.json with Hermes plugin settings (Hermes wins on conflicts)."""
    file_settings = _read_settings_file()
    if _TEST_SETTINGS is not None:
        return {**file_settings, **_TEST_SETTINGS}
    hermes: dict[str, Any] = {}
    try:
        from hermes_cli.config import load_config_readonly

        cfg = load_config_readonly() or {}
        plugins = cfg.get("plugins") if isinstance(cfg, dict) else None
        entries = plugins.get("entries") if isinstance(plugins, dict) else None
        entry = entries.get(PLUGIN_ID) if isinstance(entries, dict) else None
        settings = entry.get("settings") if isinstance(entry, dict) else None
        if isinstance(settings, dict):
            hermes = dict(settings)
    except Exception:
        hermes = {}
    merged = {**file_settings, **hermes}
    roots = _as_path_list(file_settings.get("allowlist_roots")) + _as_path_list(hermes.get("allowlist_roots"))
    if roots:
        merged["allowlist_roots"] = list(dict.fromkeys(roots))
    return merged


def _as_path_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parts = value.replace(";", "\n").replace(",", "\n").splitlines()
        return [p.strip() for p in parts if p.strip()]
    if isinstance(value, (list, tuple)):
        out: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
        return out
    return []


def configured_allowlist_roots() -> list[Path]:
    settings = load_hermes_settings()
    roots: list[Path] = []
    for raw in _as_path_list(settings.get("allowlist_roots")):
        try:
            roots.append(_resolve_configured_root(raw))
        except Problem:
            continue
    return roots


def allowlist_roots() -> list[Path]:
    roots = [default_workspace()]
    seen = {roots[0]}
    for root in configured_allowlist_roots():
        if root not in seen:
            roots.append(root)
            seen.add(root)
    return roots


def _resolve_configured_root(raw: str) -> Path:
    if not isinstance(raw, str) or not raw.strip() or "\x00" in raw or "://" in raw:
        raise Problem("invalid_root", "Allowlist roots must be local absolute paths.")
    path = Path(raw.strip()).expanduser()
    if not path.is_absolute() and _TEST_DATA_DIR is None:
        # Relative user-configured roots are resolved against the user home, never cwd.
        path = user_home() / path
    try:
        resolved = path.resolve()
    except OSError as exc:
        raise Problem("invalid_root", f"Could not resolve allowlist root: {exc}") from exc
    if _is_blocked_root(resolved):
        raise Problem(
            "root_not_allowed",
            "Filesystem roots cannot be allowlisted.",
            "Add a specific project directory in Buffrizz settings, not / or /home.",
        )
    return resolved


def _is_blocked_root(path: Path) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return True
    if resolved in _BLOCKED_ROOTS:
        return True
    # A path with no name is the filesystem root.
    if resolved.anchor == str(resolved) or str(resolved) == "/":
        return True
    return False


def resolve_allowlisted(cwd: str | Path, roots: Iterable[Path] | None = None) -> Path:
    """Resolve a working directory and require it to sit under an allowlisted root."""
    if not isinstance(cwd, (str, Path)) or not str(cwd).strip() or "\x00" in str(cwd):
        raise Problem(
            "invalid_cwd",
            "Provide an allowlisted project path.",
            "Pick a directory from buffrizz_status allowlist_roots.",
        )
    text = str(cwd).strip()
    if "://" in text:
        raise Problem("invalid_cwd", "Working directories must be local paths, not URLs.")
    path = Path(text).expanduser()
    try:
        resolved = path.resolve()
    except OSError as exc:
        raise Problem("invalid_cwd", f"Could not resolve working directory: {exc}") from exc
    if _is_blocked_root(resolved):
        raise Problem(
            "cwd_not_allowlisted",
            "That path is a filesystem root and cannot be used.",
            "Use a project directory from the allowlist.",
        )
    allowed = [Path(r).resolve() for r in (roots if roots is not None else allowlist_roots())]
    for root in allowed:
        try:
            if resolved == root or resolved.is_relative_to(root):
                return resolved
        except (OSError, ValueError):
            continue
    raise Problem(
        "cwd_not_allowlisted",
        "That working directory is not under an allowlisted root.",
        "Add the project in Buffrizz plugin settings (allowlist_roots). The model cannot add a root.",
    )


def settings_int(name: str, default: int, *, minimum: int = 1, maximum: int = 86400) -> int:
    value = load_hermes_settings().get(name, default)
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def settings_bool(name: str, default: bool = False) -> bool:
    value = load_hermes_settings().get(name, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value) if value is not None else default


def dump_json(path: Path, payload: dict, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    text = json.dumps(payload, indent=2, sort_keys=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(tmp, flags, mode)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        os.chmod(path, mode)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
