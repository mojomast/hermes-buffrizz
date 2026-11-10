"""Optional paid Codebuff SDK path. Off by default. Never a Freebuff free-mode client."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from . import env as envmod, gitutil, paths
from .errors import Problem
from .redact import redact_text

RUNNER = Path(__file__).resolve().parent / "paid_runner.mjs"


def _get_secret(name: str) -> str | None:
    try:
        from agent.secret_scope import get_secret
    except ImportError as exc:
        raise Problem(
            "secret_scope_unavailable",
            "Hermes secret scope is not available, so the paid key cannot be read.",
            "Run this op inside Hermes with CODEBUFF_API_KEY declared in plugin env.",
        ) from exc
    try:
        value = get_secret(name)
    except Exception as exc:  # noqa: BLE001
        raise Problem(
            "secret_scope_unavailable",
            "Could not read CODEBUFF_API_KEY from Hermes secret scope.",
            "Set CODEBUFF_API_KEY in the Hermes plugin env; Buffrizz will not fall back to the process environment.",
        ) from exc
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if not isinstance(value, str):
        return None
    return value.strip()


def paid_available() -> dict:
    enabled = paths.settings_bool("paid_unattended", False)
    node = envmod.resolve_node()
    return {
        "enabled": enabled,
        "node": bool(node),
        "runner": RUNNER.is_file(),
        "key_configured": None,  # never probed in a way that could leak; tools report only when op is used
    }


def run_paid(prompt: str, cwd: Path, *, max_steps: int = 20) -> dict:
    if not paths.settings_bool("paid_unattended", False):
        raise Problem(
            "paid_disabled",
            "Paid unattended runs are off by default.",
            "Enable paid_unattended in Buffrizz plugin settings and set CODEBUFF_API_KEY in Hermes env. This uses the official paid Codebuff SDK, not Freebuff free mode.",
        )
    prompt = (prompt or "").strip()
    if not prompt:
        raise Problem("missing_prompt", "Provide a prompt for paid_run.")
    cwd = paths.resolve_allowlisted(cwd)
    if not gitutil.is_git_repo(cwd):
        raise Problem("not_a_git_repo", "paid_run needs a git repository.", "Use an allowlisted git project.")
    key = _get_secret("CODEBUFF_API_KEY")
    if not key:
        raise Problem(
            "key_missing",
            "CODEBUFF_API_KEY is not configured in Hermes secret scope.",
            "Paste a Codebuff API key (https://www.codebuff.com/api-keys) into the Hermes plugin env. Buffrizz will not read vendor credential files or the process environment.",
        )
    node = envmod.resolve_node()
    if not node:
        raise Problem("node_missing", "Node.js is required for the official Codebuff SDK.", "Install Node 22+ and retry.")
    if not RUNNER.is_file():
        raise Problem("runner_missing", "The paid runner script is missing from the plugin install.")
    work = gitutil.ensure_session_worktree(cwd, "paid")
    worktree = Path(work["worktree"])
    info = gitutil.create_job_branch(worktree, "paid_" + str(int(__import__("time").time())))
    key_file = paths.tmp_dir() / f"cb-{os.getpid()}-{info['branch'].replace('/', '_')}.key"
    prompt_file = paths.tmp_dir() / f"cb-prompt-{os.getpid()}.txt"
    try:
        fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(key)
        os.chmod(key_file, 0o600)
        prompt_file.write_text(prompt, encoding="utf-8")
        child = envmod.child_env()
        # Do not put CODEBUFF_API_KEY in the environment; the runner reads the 0600 key file.
        proc = subprocess.run(
            [
                node,
                str(RUNNER),
                "--key-file",
                str(key_file),
                "--cwd",
                str(worktree),
                "--prompt-file",
                str(prompt_file),
                "--max-steps",
                str(max(1, min(int(max_steps), 40))),
            ],
            cwd=str(worktree),
            env=child,
            capture_output=True,
            text=True,
            timeout=paths.settings_int("job_timeout_seconds", 1800, minimum=30, maximum=7200),
            check=False,
        )
    finally:
        try:
            if key_file.exists():
                key_file.unlink()
        except OSError:
            pass
        try:
            prompt_file.unlink(missing_ok=True)
        except OSError:
            pass
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "paid runner failed").strip()
        if "Cannot find package '@codebuff/sdk'" in err or "Cannot find module" in err:
            raise Problem(
                "sdk_missing",
                "The official @codebuff/sdk package is not installed.",
                "Install it with `npm install -g @codebuff/sdk` (paid Codebuff, not Freebuff), then retry.",
            )
        raise Problem("paid_run_failed", redact_text(err)[:500], "Check the Codebuff account and retry.")
    result = gitutil.collect_result(worktree, info["base_sha"])
    result["branch"] = info["branch"]
    result["worktree"] = str(worktree)
    result["transcript_excerpt"] = redact_text((proc.stdout or "")[-2000:])
    result["paid"] = True
    return {"ok": True, "status": "succeeded", "result": result, "via": "codebuff_sdk"}
