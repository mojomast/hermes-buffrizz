
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class FakeCtx:
    def __init__(self):
        self.tools = {}
        self.skills = {}
        self.hooks = {}

    def register_tool(self, name, toolset, schema, handler, description="", emoji="", **kwargs):
        self.tools[name] = {"toolset": toolset, "schema": schema, "handler": handler, "description": description}

    def register_skill(self, name, path):
        self.skills[name] = Path(path)

    def register_hook(self, name, fn):
        self.hooks[name] = fn


def load_register():
    spec = importlib.util.spec_from_file_location("buffrizz_plugin_root", ROOT / "__init__.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_register_tools_skill_and_hook():
    import sys
    sys.path.insert(0, str(ROOT))
    from buffrizz.schemas import TOOL_NAMES
    from ruamel.yaml import YAML
    yaml = YAML(typ="safe")
    yaml.allow_duplicate_keys = False
    manifest = yaml.load((ROOT / "plugin.yaml").read_text())
    ctx = FakeCtx()
    load_register().register(ctx)
    assert list(ctx.tools) == list(manifest["provides_tools"]) == TOOL_NAMES
    assert "buffrizz" in ctx.skills
    assert (ctx.skills["buffrizz"]).is_file()
    hook = ctx.hooks["post_tool_call"]
    hook(tool_name="buffrizz_status", unexpected_future_field=True)
    # Handlers always exist and are callable; live JSON envelopes are covered in test_jobs.
    assert all(callable(rec["handler"]) for rec in ctx.tools.values())
