"""Shared helpers for OpenAI Responses API streams."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

type ReasoningSummaryPartKey = tuple[str | int | None, int]


class ReasoningSummaryBoundaryTracker:
    """Separate consecutive reasoning-summary parts for Markdown rendering."""

    def __init__(self) -> None:
        self._part_key: ReasoningSummaryPartKey | None = None

    def separate(self, event: Mapping[str, Any], delta: str) -> str:
        """Prefix the first delta of a new summary part with a blank line."""
        part_key = _reasoning_summary_part_key(event)
        if part_key is None:
            return delta
        separator = "\n\n" if self._part_key is not None and part_key != self._part_key else ""
        self._part_key = part_key
        return f"{separator}{delta}"


def _reasoning_summary_part_key(event: Mapping[str, Any]) -> ReasoningSummaryPartKey | None:
    summary_index = event.get("summary_index")
    if not isinstance(summary_index, int) or isinstance(summary_index, bool):
        return None

    item_id = event.get("item_id")
    if isinstance(item_id, str) and item_id:
        return item_id, summary_index

    output_index = event.get("output_index")
    if isinstance(output_index, int) and not isinstance(output_index, bool):
        return output_index, summary_index

    return None, summary_index
