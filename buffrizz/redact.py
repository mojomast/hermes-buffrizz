"""Redact credential-like paths and token-shaped text from job results."""
from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

_NAME_PATTERNS = (
    re.compile(r"^\.env$", re.I),
    re.compile(r"^\.env\..+$", re.I),
    re.compile(r"^credentials\.json$", re.I),
    re.compile(r"^auth\.json$", re.I),
    re.compile(r"^.*secret.*$", re.I),
    re.compile(r"^id_rsa$", re.I),
    re.compile(r"^id_dsa$", re.I),
    re.compile(r"^id_ecdsa$", re.I),
    re.compile(r"^id_ed25519$", re.I),
    re.compile(r"^.*\.pem$", re.I),
    re.compile(r"^.*\.p12$", re.I),
    re.compile(r"^.*\.pfx$", re.I),
    re.compile(r"^.*\.key$", re.I),
    re.compile(r"^.*\.kdbx$", re.I),
    re.compile(r"^.*\.keystore$", re.I),
)

_TOKEN_RE = re.compile(
    r"(?i)(bearer\s+)[a-z0-9._\-]+"
    r"|(?:tok|sk|cb)_[a-z0-9._\-]{8,}"
    r"|(api[_-]?key|token|secret|password)\s*[=:]\s*\S+"
)


def is_sensitive_path(path: str) -> bool:
    name = PurePosixPath(str(path).replace("\\", "/")).name
    return any(pat.match(name) for pat in _NAME_PATTERNS)


def redact_text(text: str, *, limit: int = 4000) -> str:
    if not text:
        return ""
    clipped = text if len(text) <= limit else text[-limit:]
    return _TOKEN_RE.sub("[redacted]", clipped)


def filter_changed_files(paths: list[str]) -> tuple[list[str], list[str]]:
    kept: list[str] = []
    redacted: list[str] = []
    for path in paths:
        if is_sensitive_path(path):
            redacted.append(path)
        else:
            kept.append(path)
    return kept, redacted
