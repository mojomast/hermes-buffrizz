"""Structured errors used by tools and the supervisor."""
from __future__ import annotations


class Problem(Exception):
    def __init__(self, code: str, message: str, fix: str = "", *, error: str | None = None):
        super().__init__(message)
        self.code = code
        self.fix = fix
        self.error = error or code

    def to_dict(self) -> dict:
        out = {"ok": False, "error": self.error, "code": self.code, "message": str(self)}
        if self.fix:
            out["fix"] = self.fix
        return out
