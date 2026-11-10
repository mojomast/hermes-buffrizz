
from __future__ import annotations

import json
import time

from buffrizz import client
from buffrizz.tools import handle_connect, handle_job, handle_status


def _start(plugin_env, session="chat-1"):
    raw = handle_connect({"action": "start", "cwd": str(plugin_env["repo"])}, session_id=session)
    body = json.loads(raw)
    assert body.get("ok") is True, body
    assert body.get("running") is True, body
    # Wait until the fake TUI is idle / signed in
    for _ in range(40):
        status = json.loads(handle_connect({"action": "status"}, session_id=session))
        if status.get("signed_in") == "true":
            return status
        time.sleep(0.1)
    return json.loads(handle_connect({"action": "status"}, session_id=session))


def test_enqueue_does_not_write_to_pty(plugin_env):
    status = _start(plugin_env)
    written = status.get("bytes_written") or 0
    raw = handle_job({"op": "enqueue", "prompt": "add a hello file"}, session_id="chat-1")
    body = json.loads(raw)
    assert isinstance(raw, str)
    assert body["ok"] is True
    assert body["status"] == "queued"
    assert body.get("auto_submitted") is False
    later = json.loads(handle_connect({"action": "status"}, session_id="chat-1"))
    assert later.get("bytes_written") == written


def test_run_produces_diff_end_to_end(plugin_env):
    _start(plugin_env)
    enq = json.loads(handle_job({"op": "enqueue", "prompt": "write a greeting into the repo"}, session_id="chat-1"))
    job_id = enq["job_id"]
    # Human click: the pane calls /jobs/{id}/run
    ran = client.call("POST", f"/jobs/{job_id}/run", {"session_id": "chat-1"})
    assert ran.get("ok") is True, ran
    result = None
    for _ in range(50):
        raw = handle_job({"op": "result", "job_id": job_id, "timeout_seconds": 0}, session_id="chat-1")
        body = json.loads(raw)
        if body.get("status") in {"succeeded", "failed", "cancelled", "timed_out"}:
            result = body
            break
        time.sleep(0.2)
    assert result is not None, "job did not finish"
    assert result["status"] == "succeeded", result
    files = (result.get("result") or {}).get("changed_files") or []
    assert "buffrizz_job_output.txt" in files
    assert result.get("result", {}).get("diff_stats")


def test_result_redacts_credential_files(plugin_env, monkeypatch):
    monkeypatch.setenv("BUFFRIZZ_FAKE_WRITE_SECRET", "1")
    # The fake freebuff child does not inherit this unless we put it in child env.
    # Instead, write the secret file in the worktree after enqueue by setting the
    # env on the supervisor child via a repo-side marker the fake already checks
    # in os.environ. Re-start with the env in the fake binary wrapper? Easier:
    # write credentials.json ourselves after success path by calling the fake
    # with the env. We'll put a wrapper note: update settings and start a new
    # session after writing a sidecar script. Simpler approach: after a normal
    # job, drop credentials.json into the worktree and collect again through a
    # second job that triggers the fake write.
    from buffrizz import paths
    settings = dict(plugin_env["settings"])
    paths.set_test_overrides(settings=settings, data_dir=plugin_env["data"], freebuff=paths.test_freebuff(), home=plugin_env["home"])
    # Patch child env for this process? The supervisor is already using fake
    # freebuff; set the env file the fake can read from the worktree instead.
    # Update fake to also look at a marker file. For this test, write the
    # credential file into the worktree before result collection by running a
    # job and then adding the file + asserting collect_result redacts it.
    from buffrizz import gitutil
    from buffrizz.redact import is_sensitive_path
    assert is_sensitive_path("credentials.json")
    _start(plugin_env, session="chat-2")
    status = json.loads(handle_connect({"action": "status"}, session_id="chat-2"))
    worktree = status["cwd"]
    from pathlib import Path
    Path(worktree, "credentials.json").write_text('{"token":"tok_secret"}')
    Path(worktree, "notes.txt").write_text("ok")
    collected = gitutil.collect_result(Path(worktree), gitutil.head_sha(Path(worktree)))
    # Untracked files relative to HEAD (no new commit): notes and credentials
    assert "notes.txt" in collected["changed_files"]
    assert "credentials.json" in collected["redacted_files"]
    assert "credentials.json" not in collected["changed_files"]
    assert "tok_secret" not in json.dumps(collected)


def test_connect_does_not_block_without_login(plugin_env):
    # Start is asynchronous and must not wait for a human to sign in or type.
    t0 = time.time()
    raw = handle_connect({"action": "start", "cwd": str(plugin_env["repo"])}, session_id="chat-login")
    elapsed = time.time() - t0
    body = json.loads(raw)
    assert elapsed < 3, elapsed
    assert body.get("ok") is True
    assert body.get("running") is True


def test_handlers_always_return_json_strings(plugin_env):
    for raw in (
        handle_status({"detail": "summary"}, session_id="chat-1"),
        handle_connect({"action": "status"}, session_id="chat-1"),
        handle_job({"op": "list"}, session_id="chat-1"),
        handle_job({"op": "result"}, session_id="chat-1"),
        handle_job({"op": "nope"}, session_id="chat-1"),
    ):
        assert isinstance(raw, str)
        json.loads(raw)
