"""Cross-provider transcript compilation tests."""

from __future__ import annotations

import re

from tau_ai.tool_call_ids import portable_tool_call_id


def test_portable_tool_call_id_preserves_safe_ids_and_hashes_native_ids() -> None:
    assert portable_tool_call_id("call_safe-1") == "call_safe-1"

    first = portable_tool_call_id("call_1|fc_1")
    second = portable_tool_call_id("call_1|fc_2")

    assert re.fullmatch(r"[A-Za-z0-9_-]+", first)
    assert first == portable_tool_call_id("call_1|fc_1")
    assert first != second
    assert len(first) <= 64
