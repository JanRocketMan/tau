"""Deterministic Pi-compatible model provider for tests."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable

from tau_agent.messages import AgentMessage
from tau_agent.tools import AgentTool
from tau_agent.types import JSONValue
from tau_ai.events import AssistantMessageEvent
from tau_ai.provider import CancellationToken


class FakeProvider:
    """A provider that replays predefined assistant event streams."""

    def __init__(self, streams: Iterable[Iterable[AssistantMessageEvent]]) -> None:
        self._streams = [list(stream) for stream in streams]
        self.calls: list[tuple[str, str, list[AgentMessage], list[AgentTool]]] = []
        self.session_ids: list[str | None] = []
        self.remote_input_items: list[list[JSONValue]] = []

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
        self.calls.append((model, system, list(messages), list(tools)))
        self.session_ids.append(session_id)
        self.remote_input_items.append(list(remote_input_items or []))
        stream = self._streams.pop(0) if self._streams else []

        async def iterator() -> AsyncIterator[AssistantMessageEvent]:
            for event in stream:
                if signal is not None and signal.is_cancelled():
                    return
                yield event

        return iterator()
