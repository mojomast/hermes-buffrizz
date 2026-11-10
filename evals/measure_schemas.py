#!/usr/bin/env python3
"""Measure published tool-schema tokens (o200k_base and cl100k_base)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from buffrizz.schemas import SCHEMAS, TOOL_NAMES  # noqa: E402

BUDGET = 550


def main() -> int:
    import tiktoken

    text = json.dumps(list(SCHEMAS), separators=(",", ":"), ensure_ascii=False)
    o200k = len(tiktoken.get_encoding("o200k_base").encode(text))
    cl100k = len(tiktoken.get_encoding("cl100k_base").encode(text))
    payload = {
        "tools": TOOL_NAMES,
        "o200k": o200k,
        "cl100k": cl100k,
        "budget_o200k": BUDGET,
        "ok": o200k <= BUDGET,
    }
    out = Path(__file__).with_name("schema_tokens.json")
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    if o200k > BUDGET:
        print(f"schema token budget exceeded: {o200k} > {BUDGET}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
