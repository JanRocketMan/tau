"""Translate Tau's transitional provider parser output into Pi stream events."""

from __future__ import annotations

from collections.abc import AsyncIterator

from tau_agent.messages import (
    AssistantContent,
    AssistantMessage,
    AssistantMessageDiagnostic,
    TextContent,
    ThinkingContent,
    Usage,
)
from tau_ai._provider_events import (
    ProviderErrorEvent,
    ProviderEvent,
    ProviderResponseEndEvent,
    ProviderResponseStartEvent,
    ProviderRetryEvent,
    ProviderTextDeltaEvent,
    ProviderThinkingDeltaEvent,
    ProviderToolCallEvent,
)
from tau_ai.events import (
    AssistantDoneEvent,
    AssistantErrorEvent,
    AssistantMessageEvent,
    AssistantRetryEvent,
    AssistantStartEvent,
    DoneReason,
    TextDeltaEvent,
    TextEndEvent,
    TextStartEvent,
    ThinkingDeltaEvent,
    ThinkingEndEvent,
    ThinkingStartEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
)


def _snapshot(message: AssistantMessage) -> AssistantMessage:
    return message.model_copy(deep=True)


async def _end_active_block(
    partial: AssistantMessage,
    index: int | None,
) -> AsyncIterator[AssistantMessageEvent]:
    """End the active text/thinking block before the provider changes channels."""
    if index is None:
        return
    block = partial.content[index]
    if isinstance(block, TextContent):
        yield TextEndEvent(
            content_index=index,
            content=block.text,
            partial=_snapshot(partial),
        )
    elif isinstance(block, ThinkingContent):
        yield ThinkingEndEvent(
            content_index=index,
            content=block.thinking,
            partial=_snapshot(partial),
        )


def _copy_replay_metadata(target: AssistantMessage, source: AssistantMessage) -> None:
    """Copy provider metadata onto streamed blocks without changing their order."""
    source_thinking = [block for block in source.content if isinstance(block, ThinkingContent)]
    target_thinking = [block for block in target.content if isinstance(block, ThinkingContent)]
    for target_block, source_block in zip(target_thinking, source_thinking, strict=False):
        target_block.thinking_signature = source_block.thinking_signature
        target_block.redacted = source_block.redacted

    source_text = [block for block in source.content if isinstance(block, TextContent)]
    target_text = [block for block in target.content if isinstance(block, TextContent)]
    for target_text_block, source_text_block in zip(target_text, source_text, strict=False):
        target_text_block.text_signature = source_text_block.text_signature


def _coalesce_same_kind_blocks(blocks: list[AssistantContent]) -> list[AssistantContent]:
    """Merge same-kind text/thinking fragments into one contiguous block.

    Chat-completions gateways can interleave fragments of one continuous
    reasoning or answer stream across chunks (thinking, text, thinking, text).
    Each kind switch would otherwise become its own content block even though
    the fragments belong to a single thinking or answer stream. Fragments are
    therefore grouped by kind inside each text/thinking region, emitted in
    first-occurrence order, so thinking and answer each stay contiguous.
    Tool calls are structural barriers: fragments on either side of a tool
    call come from genuinely different phases and stay separate. Boundaries
    attested by the provider itself (for example OpenAI reasoning summary
    parts) arrive as whitespace or text inside the deltas and survive the
    merge unchanged.
    """
    merged: list[AssistantContent] = []
    pending_thinking: list[str] = []
    pending_text: list[str] = []
    first_kind: str | None = None

    def flush() -> None:
        nonlocal first_kind
        if first_kind == "thinking":
            if pending_thinking:
                merged.append(ThinkingContent(thinking="".join(pending_thinking)))
            if pending_text:
                merged.append(TextContent(text="".join(pending_text)))
        elif first_kind == "text":
            if pending_text:
                merged.append(TextContent(text="".join(pending_text)))
            if pending_thinking:
                merged.append(ThinkingContent(thinking="".join(pending_thinking)))
        pending_thinking.clear()
        pending_text.clear()
        first_kind = None

    for block in blocks:
        if isinstance(block, ThinkingContent):
            pending_thinking.append(block.thinking)
            first_kind = first_kind or "thinking"
        elif isinstance(block, TextContent):
            pending_text.append(block.text)
            first_kind = first_kind or "text"
        else:
            flush()
            merged.append(block.model_copy(deep=True))
    flush()
    return merged


def _finish_reason(value: str | None, *, has_tools: bool) -> DoneReason | None:
    if value in {"tool_calls", "tool_use", "toolUse"}:
        return "toolUse"
    if value in {"length", "max_tokens", "MAX_TOKENS", "incomplete"}:
        return "length"
    if value in {"stop", "completed", "done"}:
        return "toolUse" if has_tools else "stop"
    return None


def _finish_reason_error(value: str | None) -> str:
    if value is None:
        return "Provider stream ended without a finish reason"
    return f"Provider returned unsupported finish reason: {value}"


async def canonicalize_provider_stream(
    source: AsyncIterator[ProviderEvent],
    *,
    api: str,
    provider: str,
    model: str,
) -> AsyncIterator[AssistantMessageEvent]:
    """Canonicalize one old internal parser stream.

    Provider parsers remain isolated behind this private bridge while they are
    migrated incrementally. The public provider protocol exposes only Pi events.
    """
    partial = AssistantMessage(api=api, provider=provider, model=model)
    active_index: int | None = None
    active_kind: str | None = None
    started = False
    terminal = False

    async for event in source:
        if isinstance(event, ProviderRetryEvent):
            yield AssistantRetryEvent(
                attempt=event.attempt,
                max_attempts=event.max_attempts,
                delay_ms=max(0, round(event.delay_seconds * 1000)),
                error_message=event.message,
            )
            continue
        if isinstance(event, ProviderResponseStartEvent):
            if event.response_provider is not None:
                partial.response_provider = event.response_provider
            if not started:
                started = True
                yield AssistantStartEvent(partial=_snapshot(partial))
            continue
        if not started:
            started = True
            yield AssistantStartEvent(partial=_snapshot(partial))

        if isinstance(event, ProviderTextDeltaEvent):
            if active_kind != "text":
                async for end_event in _end_active_block(partial, active_index):
                    yield end_event
                active_index = len(partial.content)
                active_kind = "text"
                partial.content.append(TextContent(text=""))
                yield TextStartEvent(content_index=active_index, partial=_snapshot(partial))
            assert active_index is not None
            block = partial.content[active_index]
            assert isinstance(block, TextContent)
            block.text += event.delta
            yield TextDeltaEvent(
                content_index=active_index,
                delta=event.delta,
                partial=_snapshot(partial),
            )
        elif isinstance(event, ProviderThinkingDeltaEvent):
            if active_kind != "thinking":
                async for end_event in _end_active_block(partial, active_index):
                    yield end_event
                active_index = len(partial.content)
                active_kind = "thinking"
                partial.content.append(ThinkingContent(thinking=""))
                yield ThinkingStartEvent(
                    content_index=active_index,
                    partial=_snapshot(partial),
                )
            assert active_index is not None
            block = partial.content[active_index]
            assert isinstance(block, ThinkingContent)
            block.thinking += event.delta
            yield ThinkingDeltaEvent(
                content_index=active_index,
                delta=event.delta,
                partial=_snapshot(partial),
            )
        elif isinstance(event, ProviderToolCallEvent):
            async for end_event in _end_active_block(partial, active_index):
                yield end_event
            active_index = None
            active_kind = None
            index = len(partial.content)
            partial.content.append(event.tool_call.model_copy(deep=True))
            yield ToolCallStartEvent(content_index=index, partial=_snapshot(partial))
            yield ToolCallEndEvent(
                content_index=index,
                tool_call=event.tool_call,
                partial=_snapshot(partial),
            )
        elif isinstance(event, ProviderResponseEndEvent):
            async for end_event in _end_active_block(partial, active_index):
                yield end_event
            active_index = None
            active_kind = None

            # Keep the streamed kind order while grouping same-kind
            # fragments into contiguous thinking and answer blocks.
            # The parser's final message remains authoritative for response
            # metadata/usage only.
            final = event.message.model_copy(deep=True)
            final.api = api
            final.provider = provider
            final.model = model
            final.response_provider = event.message.response_provider or partial.response_provider
            final.content = _coalesce_same_kind_blocks(partial.content)
            if not final.content and event.message.content:
                final.content = _coalesce_same_kind_blocks(event.message.content)
            _copy_replay_metadata(final, event.message)
            reason = _finish_reason(
                event.finish_reason,
                has_tools=bool(final.tool_calls),
            )
            if reason is None:
                final.stop_reason = "error"
                final.error_message = _finish_reason_error(event.finish_reason)
                final.diagnostics = [
                    *(final.diagnostics or []),
                    AssistantMessageDiagnostic(
                        type="provider_error",
                        details={"finish_reason": event.finish_reason},
                    ),
                ]
                yield AssistantErrorEvent(reason="error", error=final)
                terminal = True
                continue
            final.stop_reason = reason
            final.diagnostics = [
                *(final.diagnostics or []),
                AssistantMessageDiagnostic(
                    type="provider_finish",
                    details={"finish_reason": event.finish_reason},
                ),
            ]
            yield AssistantDoneEvent(reason=reason, message=final)
            terminal = True
        elif isinstance(event, ProviderErrorEvent):
            async for end_event in _end_active_block(partial, active_index):
                yield end_event
            active_index = None
            active_kind = None
            error = partial.model_copy(deep=True)
            error.response_provider = event.response_provider or partial.response_provider
            error.stop_reason = "error"
            error.error_message = event.message
            error.diagnostics = [
                AssistantMessageDiagnostic(type="provider_error", details=event.data)
            ]
            yield AssistantErrorEvent(reason="error", error=error)
            terminal = True

    if not started:
        yield AssistantStartEvent(partial=_snapshot(partial))
    if not terminal:
        error = partial.model_copy(deep=True)
        error.stop_reason = "error"
        error.error_message = "Provider stream ended without a terminal event"
        error.usage = Usage()
        yield AssistantErrorEvent(reason="error", error=error)
