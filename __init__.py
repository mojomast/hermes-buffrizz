"""Buffrizz: official Freebuff CLI in a Hermes pane, plus a job queue."""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))


def register(ctx) -> None:
    skills = _HERE / "skills"
    if skills.is_dir() and hasattr(ctx, "register_skill"):
        for child in sorted(p for p in skills.iterdir() if p.is_dir()):
            skill_md = child / "SKILL.md"
            if skill_md.is_file():
                ctx.register_skill(child.name, skill_md)
    from buffrizz.tools import bind_tool_result, register_tools

    if hasattr(ctx, "register_hook"):
        ctx.register_hook("post_tool_call", bind_tool_result)
    register_tools(ctx)
