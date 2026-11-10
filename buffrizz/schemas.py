"""Compact tool schemas. Keep the published set under about 550 o200k tokens."""
from __future__ import annotations

STATUS_SCHEMA = {
    "name": "buffrizz_status",
    "description": (
        "Buffrizz status: official freebuff install, pane/PTY, signed-in boolean "
        "(never a token), bound Hermes session, allowlisted cwd, and job summaries. "
        "Does not start a session or send prompts."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "detail": {
                "type": "string",
                "enum": ["summary", "full"],
                "description": "summary (default) or full job list and screen excerpt.",
            }
        },
        "additionalProperties": False,
    },
}

CONNECT_SCHEMA = {
    "name": "buffrizz_connect",
    "description": (
        "Start or stop the official Freebuff TUI for this Hermes session. Login is "
        "pane-only: refuses model-supplied tokens or API keys "
        "(unsupported_operation / pair_via_pane). cwd must already be allowlisted. "
        "Does not send prompts; the user clicks Run in the pane."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["start", "stop", "status"],
                "description": "start opens the official TUI, stop ends it, status inspects it.",
            },
            "cwd": {
                "type": "string",
                "description": "Allowlisted project path. Required for start unless a session cwd is already bound.",
            },
            "continue_id": {
                "type": "string",
                "description": "Optional official --continue conversation id.",
            },
            "token": {
                "type": "string",
                "description": "Unsupported. Login is pane-only; a model-supplied token is refused.",
            },
            "api_key": {
                "type": "string",
                "description": "Unsupported. Login is pane-only; a model-supplied API key is refused.",
            },
        },
        "required": ["action"],
        "additionalProperties": False,
    },
}

JOB_SCHEMA = {
    "name": "buffrizz_job",
    "description": (
        "Queue coding tasks for the official Freebuff session. op=enqueue never "
        "auto-submits; tell the user to click Run in the pane. op=result returns git "
        "status and diff stats (default timeout_seconds=0 returns current state). "
        "op=paid_run uses the official paid Codebuff SDK only if paid_unattended is "
        "enabled and CODEBUFF_API_KEY is set; it is never a Freebuff free-mode path."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "op": {
                "type": "string",
                "enum": ["enqueue", "list", "status", "cancel", "result", "paid_run"],
                "description": "enqueue, list, status, cancel, result, or paid_run.",
            },
            "prompt": {"type": "string", "description": "Task text for enqueue or paid_run."},
            "job_id": {"type": "string", "description": "Job id for status, cancel, or result."},
            "cwd": {"type": "string", "description": "Allowlisted project; defaults to the bound session cwd."},
            "timeout_seconds": {
                "type": "integer",
                "description": "For result, wait up to this many seconds; default 0 returns current state.",
            },
        },
        "required": ["op"],
        "additionalProperties": False,
    },
}

SCHEMAS = (STATUS_SCHEMA, CONNECT_SCHEMA, JOB_SCHEMA)
TOOL_NAMES = [s["name"] for s in SCHEMAS]
