from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FAKE_FREEBUFF = ROOT / "tests" / "fixtures" / "freebuff"


def init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "README.md").write_text("hello\n", encoding="utf-8")
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(path.parent / "git-home"),
        "GIT_AUTHOR_NAME": "Buffrizz Test",
        "GIT_AUTHOR_EMAIL": "buffrizz-test@example.com",
        "GIT_COMMITTER_NAME": "Buffrizz Test",
        "GIT_COMMITTER_EMAIL": "buffrizz-test@example.com",
        "LANG": "C.UTF-8",
    }
    (path.parent / "git-home").mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=path, env=env, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Buffrizz Test"], cwd=path, env=env, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "buffrizz-test@example.com"], cwd=path, env=env, check=True, capture_output=True)
    subprocess.run(["git", "add", "README.md"], cwd=path, env=env, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, env=env, check=True, capture_output=True)
    return path


@pytest.fixture
def plugin_env(tmp_path, monkeypatch):
    from buffrizz import client, paths

    data = tmp_path / "plugin-data"
    home = tmp_path / "home"
    repo = init_repo(tmp_path / "project")
    data.mkdir()
    home.mkdir()
    settings = {"allowlist_roots": [str(repo)], "idle_seconds": 3, "job_timeout_seconds": 30, "paid_unattended": False}
    paths.set_test_overrides(data_dir=data, freebuff=FAKE_FREEBUFF, home=home, settings=settings)
    monkeypatch.setenv("BUFFRIZZ_SENTINEL_SECRET", "sentinel-should-never-leak")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "aws-should-never-leak")
    os.environ["BUFFRIZZ_SENTINEL_SECRET"] = "sentinel-should-never-leak"
    yield {"data": data, "home": home, "repo": repo, "settings": settings}
    try:
        session = client._load_session()
        if session:
            try:
                client._request(session, "POST", "/shutdown", {}, timeout=2)
            except Exception:
                pass
            pid = int(session.get("pid") or 0)
            if pid:
                try:
                    os.kill(pid, 15)
                except OSError:
                    pass
                time.sleep(0.2)
                try:
                    os.kill(pid, 9)
                except OSError:
                    pass
    finally:
        paths.set_test_overrides(clear=True)
