
from __future__ import annotations

import json
from pathlib import Path

from buffrizz.schemas import SCHEMAS, TOOL_NAMES

ROOT = Path(__file__).resolve().parents[1]
BUDGET = 550


def test_schema_token_budget():
    import tiktoken
    text = json.dumps(list(SCHEMAS), separators=(",", ":"), ensure_ascii=False)
    n = len(tiktoken.get_encoding("o200k_base").encode(text))
    budget_file = ROOT / "evals" / "schema_tokens.json"
    if budget_file.is_file():
        recorded = json.loads(budget_file.read_text()).get("o200k")
        # Allow small drift but stay under budget.
        assert recorded is None or n <= max(recorded + 40, BUDGET)
    assert n <= BUDGET, f"tool schemas are {n} o200k tokens; budget is {BUDGET}"
    assert TOOL_NAMES == ["buffrizz_status", "buffrizz_connect", "buffrizz_job"]
