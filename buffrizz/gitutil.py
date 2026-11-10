"""Git snapshots, worktrees, and result stats in an allowlisted project."""
from __future__ import annotations

import subprocess
from pathlib import Path

from . import env as envmod
from . import paths
from .errors import Problem
from .redact import filter_changed_files

_GIT_TIMEOUT = 60


def run_git(args: list[str], cwd: Path, *, check: bool = False) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        env=envmod.git_env(),
        capture_output=True,
        text=True,
        timeout=_GIT_TIMEOUT,
        check=False,
    )
    if check and proc.returncode != 0:
        raise Problem(
            "git_failed",
            (proc.stderr or proc.stdout or "git command failed").strip()[:500],
            "Confirm the project is a git repository and retry.",
        )
    return proc


def is_git_repo(cwd: Path) -> bool:
    proc = run_git(["rev-parse", "--is-inside-work-tree"], cwd)
    return proc.returncode == 0 and proc.stdout.strip() == "true"


def head_sha(cwd: Path) -> str:
    proc = run_git(["rev-parse", "HEAD"], cwd, check=True)
    return proc.stdout.strip()


def common_git_dir(cwd: Path) -> Path:
    proc = run_git(["rev-parse", "--git-common-dir"], cwd, check=True)
    raw = Path(proc.stdout.strip())
    return raw if raw.is_absolute() else (cwd / raw).resolve()


def ensure_session_worktree(repo: Path, session_id: str) -> dict:
    """Create or reuse a session worktree under plugin data, starting from HEAD."""
    if not is_git_repo(repo):
        raise Problem(
            "not_a_git_repo",
            "Jobs need a git repository so Buffrizz can isolate a branch and return a diff.",
            "Initialize git in the allowlisted project, or pick a different root.",
        )
    slug = "".join(ch for ch in session_id if ch.isalnum())[-16:] or "session"
    branch = f"buffrizz/session-{slug}"
    dest = (paths.worktree_root() / slug).resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        if is_git_repo(dest) and common_git_dir(dest) == common_git_dir(repo):
            return {"worktree": str(dest), "branch": branch, "base_sha": head_sha(dest), "reused": True}
        raise Problem(
            "worktree_conflict",
            f"A path already exists at the session worktree: {dest}",
            "Remove the leftover worktree under the Buffrizz plugin data directory and retry.",
        )
    base = head_sha(repo)
    proc = run_git(["worktree", "add", "-B", branch, str(dest), "HEAD"], repo)
    if proc.returncode != 0:
        raise Problem(
            "worktree_failed",
            (proc.stderr or proc.stdout or "git worktree add failed").strip()[:500],
            "Check that the repository is healthy and that plugin data is writable.",
        )
    return {"worktree": str(dest), "branch": branch, "base_sha": base, "reused": False}


def create_job_branch(worktree: Path, job_id: str) -> dict:
    branch = f"buffrizz/{job_id}"
    base = head_sha(worktree)
    proc = run_git(["checkout", "-B", branch], worktree)
    if proc.returncode != 0:
        raise Problem(
            "branch_failed",
            (proc.stderr or proc.stdout or "could not create job branch").strip()[:500],
            "Inspect the session worktree and retry.",
        )
    return {"branch": branch, "base_sha": base}


def snapshot(cwd: Path) -> dict:
    sha = head_sha(cwd) if is_git_repo(cwd) else ""
    status = run_git(["status", "--porcelain"], cwd)
    return {
        "sha": sha,
        "dirty": bool(status.stdout.strip()) if status.returncode == 0 else True,
    }


def collect_result(cwd: Path, base_sha: str) -> dict:
    if not is_git_repo(cwd):
        raise Problem("not_a_git_repo", "The working directory is not a git repository.")
    status_proc = run_git(["status", "--porcelain"], cwd)
    diff_proc = run_git(["diff", "--stat", base_sha or "HEAD"], cwd)
    names_proc = run_git(["diff", "--name-only", base_sha or "HEAD"], cwd)
    untracked_proc = run_git(["ls-files", "--others", "--exclude-standard"], cwd)
    paths_changed = []
    if names_proc.returncode == 0:
        paths_changed.extend([line for line in names_proc.stdout.splitlines() if line.strip()])
    if untracked_proc.returncode == 0:
        for line in untracked_proc.stdout.splitlines():
            if line.strip() and line not in paths_changed:
                paths_changed.append(line)
    kept, redacted = filter_changed_files(paths_changed)
    log_proc = run_git(["log", "--oneline", f"{base_sha}..HEAD"], cwd) if base_sha else None
    commits = log_proc.stdout.strip().splitlines() if log_proc and log_proc.returncode == 0 else []
    porcelain = status_proc.stdout.strip() if status_proc.returncode == 0 else ""
    stats = (diff_proc.stdout or "").strip()
    untracked_count = sum(1 for line in porcelain.splitlines() if line.startswith("??"))
    if untracked_count:
        extra = f"{untracked_count} untracked file" + ("s" if untracked_count != 1 else "")
        stats = (stats + "\n" + extra).strip() if stats else extra
    return {
        "base_sha": base_sha,
        "head_sha": head_sha(cwd),
        "status_porcelain": porcelain,
        "diff_stats": stats,
        "changed_files": kept,
        "redacted_files": redacted,
        "commits": commits,
        "dirty": bool(porcelain) or bool(kept) or bool(redacted),
    }
