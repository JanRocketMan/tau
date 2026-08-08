"""Provider-neutral streaming events emitted by model adapters."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from tau_agent.messages import AssistantMessage
from tau_agent.tools import ToolCall
from tau_agent.types import JSONValue


class BaseProviderEvent(BaseModel):
    """Base class for all provider events. Forbids extra fields."""

    model_config = ConfigDict(extra="forbid")


class ProviderResponseStartEvent(BaseProviderEvent):
    """The provider has started a model response."""

    type: Literal["response_start"] = "response_start"
    model: str
    response_provider: str | None = None


class ProviderRetryEvent(BaseProviderEvent):
    """The provider adapter is retrying a transient request failure."""

    type: Literal["retry"] = "retry"
    attempt: int
    max_attempts: int
    delay_seconds: float
    message: str
    data: dict[str, JSONValue] | None = None


class ProviderTextDeltaEvent(BaseProviderEvent):
    """A streamed text fragment from the provider."""

    type: Literal["text_delta"] = "text_delta"
    delta: str


class ProviderThinkingDeltaEvent(BaseProviderEvent):
    """A streamed thinking/reasoning fragment from the provider."""

    type: Literal["thinking_delta"] = "thinking_delta"
    delta: str


class ProviderToolCallEvent(BaseProviderEvent):
    """A complete tool call requested by the model."""

    type: Literal["tool_call"] = "tool_call"
    tool_call: ToolCall


class ProviderResponseEndEvent(BaseProviderEvent):
    """The provider has completed a model response."""

    type: Literal["response_end"] = "response_end"
    message: AssistantMessage
    finish_reason: str | None = None


class ProviderErrorEvent(BaseProviderEvent):
    """A provider-level error that can be surfaced by the agent layer."""

    type: Literal["error"] = "error"
    message: str
    data: dict[str, JSONValue] | None = None
    response_provider: str | None = None


type ProviderEvent = (
    ProviderResponseStartEvent
    | ProviderRetryEvent
    | ProviderTextDeltaEvent
    | ProviderThinkingDeltaEvent
    | ProviderToolCallEvent
    | ProviderResponseEndEvent
    | ProviderErrorEvent
)
