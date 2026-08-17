"""Provider contract owned by Tau's portable agent layer."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from tau_agent.messages import AgentMessage
from tau_agent.provider_events import AssistantMessageEvent
from tau_agent.tools import AgentTool
from tau_agent.types import JSONValue


class CancellationToken(Protocol):
    def is_cancelled(self) -> bool:
        """Return whether the current stream should stop."""
        ...


class ModelProvider(Protocol):
    """Provider-neutral Pi-compatible model stream interface."""

    def stream_response(
        self,
        *,
        model: str,
        system: str,
        messages: list[AgentMessage],
        tools: list[AgentTool],
        signal: CancellationToken | None = None,
        session_id: str | None = None,
        remote_input_items: list[JSONValue] | None = None,
    ) -> AsyncIterator[AssistantMessageEvent]:
        """Stream one model response as assistant message events.

        Providers may use ``session_id`` for request routing or prompt-cache
        affinity. ``remote_input_items`` carries provider-native input items
        persisted by a previous compaction (only the Responses transports
        consume it); unsupported providers ignore it. Defaults to ``None``.
        """
        ...
