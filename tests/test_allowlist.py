
from __future__ import annotations

import os
from pathlib import Path

import pytest

from buffrizz import paths
from buffrizz.errors import Problem


def test_rejects_filesystem_root(tmp_path):
    paths.set_test_overrides(data_dir=tmp_path / "d", settings={"allowlist_roots": ["/"]})
    try:
        roots = paths.allowlist_roots()
        assert Path("/") not in roots
        with pytest.raises(Problem) as exc:
            paths.resolve_allowlisted("/")
        assert exc.value.code == "cwd_not_allowlisted" or exc.value.code == "root_not_allowed"
    finally:
        paths.set_test_overrides(clear=True)


def test_rejects_path_outside_allowlist(tmp_path):
    allowed = tmp_path / "ok"
    allowed.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    paths.set_test_overrides(data_dir=tmp_path / "d", settings={"allowlist_roots": [str(allowed)]})
    try:
        resolved = paths.resolve_allowlisted(str(allowed / "sub"))
        assert resolved == (allowed / "sub").resolve() or allowed in resolved.parents or resolved == allowed.resolve()
        (allowed / "sub").mkdir()
        assert paths.resolve_allowlisted(str(allowed / "sub")) == (allowed / "sub").resolve()
        with pytest.raises(Problem) as exc:
            paths.resolve_allowlisted(str(other))
        assert exc.value.code == "cwd_not_allowlisted"
    finally:
        paths.set_test_overrides(clear=True)


def test_symlink_escape_rejected(tmp_path):
    allowed = tmp_path / "ok"
    allowed.mkdir()
    secret = tmp_path / "secret"
    secret.mkdir()
    (secret / "file").write_text("nope")
    link = allowed / "escape"
    link.symlink_to(secret)
    paths.set_test_overrides(data_dir=tmp_path / "d", settings={"allowlist_roots": [str(allowed)]})
    try:
        with pytest.raises(Problem) as exc:
            paths.resolve_allowlisted(str(link))
        assert exc.value.code == "cwd_not_allowlisted"
    finally:
        paths.set_test_overrides(clear=True)


def test_model_cannot_add_root_via_argument(tmp_path):
    allowed = tmp_path / "ok"
    allowed.mkdir()
    extra = tmp_path / "extra"
    extra.mkdir()
    paths.set_test_overrides(data_dir=tmp_path / "d", settings={"allowlist_roots": [str(allowed)]})
    try:
        with pytest.raises(Problem):
            paths.resolve_allowlisted(str(extra))
        # default workspace is allowed
        ws = paths.default_workspace()
        assert paths.resolve_allowlisted(str(ws)) == ws
    finally:
        paths.set_test_overrides(clear=True)
