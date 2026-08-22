import asyncio
from collections.abc import AsyncIterator, Mapping

import pytest

from pi_event_helpers import (
    assistant_done,
    assistant_error,
    assistant_start,
    text_delta,
    thinking_delta,
    tool_call_end,
)
from tau_agent import (
    AgentEvent,
    AgentMessage,
    AgentTool,
    AgentToolResult,
    AssistantMessage,
    CustomMessage,
    MessageEndEvent,
    MessageUpdateEvent,
    RetryEvent,
    SimpleCancellationToken,
    TextContent,
    ThinkingContent,
    ToolCall,
    ToolCancellationToken,
    ToolExecutionEndEvent,
    ToolExecutionUpdateEvent,
    ToolExecutor,
    ToolResultMessage,
    ToolUpdateCallback,
    UserMessage,
    message_text,
)
from tau_agent.loop import run_agent_loop
from tau_agent.messages import AssistantMessageDiagnostic
from tau_agent.provider_events import (
    AssistantErrorEvent,
    AssistantRetryEvent,
    TextDeltaEvent,
    ThinkingDeltaEvent,
)
from tau_agent.types import JSONValue
from tau_ai import FakeProvider


async def _collect(stream: AsyncIterator[AgentEvent]) -> list[AgentEvent]:
    return [event async for event in stream]


def _tool(
    name: str,
    execute_fn: ToolExecutor,
) -> AgentTool:
    return AgentTool(
        name=name,
        label=name.title(),
        description=f"Run {name}.",
        parameters={"type": "object"},
        execute_fn=execute_fn,
    )


@pytest.mark.anyio
async def test_agent_loop_streams_canonical_nested_events() -> None:
    messages: list[AgentMessage] = [UserMessage(content="Say hello")]
    assistant = AssistantMessage(content=[TextContent(text="Hello")], model="fake")
    provider = FakeProvider(
        [[assistant_start(), text_delta("Hel"), text_delta("lo"), assistant_done(assistant)]]
    )

    events = await _collect(
        run_agent_loop(
            provider=provider,
            model="fake",
            system="You are Tau.",
            messages=messages,
            tools=[],
        )
    )

    assert [event.type for event in events] == [
        "agent_start",
        "turn_start",
        "message_start",
        "message_update",
        "message_update",
        "message_end",
        "turn_end",
        "agent_end",
    ]
    updates = [
        event.assistant_message_event
        for event in events
        if isinstance(event, MessageUpdateEvent)
        and isinstance(event.assistant_message_event, TextDeltaEvent)
    ]
    assert [event.delta for event in updates] == ["Hel", "lo"]
    assert messages == [messages[0], assistant]


@pytest.mark.anyio
async def test_agent_loop_forwards_provider_retry_progress() -> None:
    assistant = AssistantMessage(content=[TextContent(text="Done")], model="fake")
    provider = FakeProvider(
        [
            [
                AssistantRetryEvent(
                    attempt=2,
                    max_attempts=4,
                    delay_ms=250,
                    error_message="Retrying provider request 2/4 after HTTP 503 in 0.25s.",
                ),
                assistant_start(),
                assistant_done(assistant),
            ]
        ]
    )

    events = await _collect(
        run_agent_loop(
            provider=provider,
            model="fake",
            system="You are Tau.",
            messages=[UserMessage(content="work")],
            tools=[],
        )
    )

    retry = next(event for event in events if isinstance(event, RetryEvent))
    assert retry.scope == "provider"
    assert retry.attempt == 2
    assert retry.max_attempts == 4
    assert retry.delay_ms == 250


@pytest.mark.anyio
async def test_agent_loop_nests_thinking_events_without_losing_final_message() -> None:
    messages: list[AgentMessage] = [UserMessage(content="Think briefly")]
    assistant = AssistantMessage(content=[TextContent(text="Done")], model="fake")
    provider = FakeProvider(
        [
            [
                assistant_start(),
                thinking_delta("hidden "),
                thinking_delta("reasoning"),
                text_delta("Done"),
                assistant_done(assistant),
            ]
        ]
    )

    events = await _collect(
        run_agent_loop(
            provider=provider,
            model="fake",
            system="You are Tau.",
            messages=messages,
            tools=[],
        )
    )

    nested = [
        event.assistant_message_event
        for event in events
        if isinstance(event, MessageUpdateEvent)
        and isinstance(event.assistant_message_event, ThinkingDeltaEvent)
    ]
    assert [event.delta for event in nested] == ["hidden ", "reasoning"]
    assert messages[-1] == assistant
    # The final provider message is the canonical persistence boundary.
    assert isinstance(messages[-1], AssistantMessage)


@pytest.mark.anyio
async def test_agent_loop_retries_thinking_only_response_once() -> None:
    first = AssistantMessage(
        content=[ThinkingContent(thinking="unfinished plan")],
        model="fake",
    )
    final = AssistantMessage(content=[TextContent(text="Done")], model="fake")
    provider = FakeProvider(
        [
            [assistant_start(), assistant_done(first)],
            [assistant_start(), text_delta("Done"), assistant_done(final)],
        ]
    )
    messages: list[AgentMessage] = [UserMessage(content="work")]

    events = await _collect(
        run_agent_loop(
            provider=provider,
            model="fake",
            system="You are Tau.",
            messages=messages,
            tools=[],
        )
    )

    retries = [event for event in events if isinstance(event, RetryEvent)]
    assert [(event.scope, event.attempt, event.max_attempts) for event in retries] == [
        ("response", 1, 1)
    ]
    assert len(provider.calls) == 2
    assert messages[1] is first
    recovery = messages[2]
    assert isinstance(recovery, CustomMessage)
    assert recovery.custom_type == "auto-retry"
    assert recovery.display is False
    assert messages[3] is final
    assert provider.calls[1][2] == messages[:3]


@pytest.mark.anyio
async def test_agent_loop_stops_after_second_consecutive_thinking_only_response() -> None:
    first = AssistantMessage(content=[ThinkingContent(thinking="first")], model="fake")
    second = AssistantMessage(content=[ThinkingContent(thinking="second")], model="fake")
    provider = FakeProvider(
        [
            [assistant_start(), assistant_done(first)],
            [assistant_start(), assistant_done(second)],
        ]
    )
    messages: list[AgentMessage] = [UserMessage(content="work")]

    events = await _collect(
        run_agent_loop(
            provider=provider,
            model="fake",
            system="You are Tau.",
            messages=messages,
            tools=[],
        )
    )

    assert len(provider.calls) == 2
    assert [event.type for event in events].count("retry") == 1
    assert messages[-1] is second


@pytest.mark.anyio
async def test_agent_loop_retries_partial_retryable_provider_interruption() -> None:
    interrupted = AssistantMessage(
        content=[ThinkingContent(thinking="unfinished")],
        model="fake",
        stop_reason="error",
        error_message="Provider inference was interrupted",
        diagnostics=[
            AssistantMessageDiagnostic(
                type="provider_error",
                details={"retryable_incomplete_response": True},
            )
        ],
    )
    final = AssistantMessage(content=[TextContent(text="Done")], model="fake")
    provider = FakeProvider(
        [
            [assistant_start(), AssistantErrorEvent(reason="error", error=interrupted)],
            [assistant_start(), assistant_done(final)],
        ]
    )
    messages: list[AgentMessage] = [UserMessage(content="work")]

    events = await _collect(
        run_agent_loop(
            provider=provider,
            model="fake",
            system="You are Tau.",
            messages=messages,
            tools=[],
        )
    )

    retry = next(event for event in events if isinstance(event, RetryEvent))
    assert retry.scope == "response"
    assert retry.error_message == "Provider inference was interrupted; retrying once."
    assert len(provider.calls) == 2
    assert messages[-1] is final


@pytest.mark.anyio
async def test_agent_loop_executes_tool_and_emits_tool_result_message_lifecycle() -> None:
    async def execute(
        tool_call_id: str,
        arguments: Mapping[str, JSONValue],
        signal: ToolCancellationToken | None = None,
        on_update: ToolUpdateCallback | None = None,
    ) -> AgentToolResult:
        del tool_call_id, signal, on_update
        return AgentToolResult(
            content=[TextContent(text=f"contents of {arguments['path']}")],
            details={"path": arguments["path"]},
        )

    tool_call = ToolCall(id="call-1", name="read", arguments={"path": "README.md"})
    first = AssistantMessage(content=[TextContent(text="Reading."), tool_call], model="fake")
    final = AssistantMessage(content=[TextContent(text="Done.")], model="fake")
    provider = FakeProvider(
        [
            [assistant_start(), tool_call_end(tool_call), assistant_done(first, "toolUse")],
            [assistant_start(), text_delta("Done."), assistant_done(final)],
        ]
    )
    messages: list[AgentMessage] = [UserMessage(content="Read README.md")]

    events = await _collect(
        run_agent_loop(
            provider=provider,
            model="fake",
            system="You are Tau.",
            messages=messages,
            tools=[_tool("read", execute)],
        )
    )

    result = next(message for message in messages if isinstance(message, ToolResultMessage))
    assert result.role == "toolResult"
    assert result.tool_name == "read"
    assert result.text == "contents of README.md"
    assert result.details == {"path": "README.md"}
    result_lifecycle = [
        event.type
        for event in events
        if isinstance(event, (MessageEndEvent,)) and event.message is result
    ]
    assert result_lifecycle == ["message_end"]
    assert [event.type for event in events].count("message_start") == 3
    assert provider.calls[1][2] == messages[:3]


@pytest.mark.anyio
async def test_agent_loop_passes_call_id_signal_and_progress_to_tool() -> None:
    observed: list[tuple[str, ToolCancellationToken | None]] = []

    async def execute(
        tool_call_id: str,
        arguments: Mapping[str, JSONValue],
        signal: ToolCancellationToken | None = None,
        on_update: ToolUpdateCallback | None = None,
    ) -> AgentToolResult:
        del arguments
        observed.append((tool_call_id, signal))
        assert on_update is not None
        on_update(AgentToolResult(content=[TextContent(text="working")]))
        await asyncio.sleep(0)
        return AgentToolResult(content=[TextContent(text="done")])

    call = ToolCall(id="call-1", name="work", arguments={})
    first = AssistantMessage(content=[call], model="fake")
    final = AssistantMessage(content=[TextContent(text="finished")], model="fake")
    provider = FakeProvider(
        [
            [assistant_start(), tool_call_end(call), assistant_done(first, "toolUse")],
            [assistant_start(), assistant_done(final)],
        ]
    )
    signal = SimpleCancellationToken()

    events = await _collect(
        run_agent_loop(
            provider=provider,
            model="fake",
            system="You are Tau.",
            messages=[UserMessage(content="work")],
            tools=[_tool("work", execute)],
            signal=signal,
        )
    )

    assert observed == [("call-1", signal)]
    updates = [event for event in events if isinstance(event, ToolExecutionUpdateEvent)]
    assert [event.partial_result.text for event in updates] == ["working"]


@pytest.mark.anyio
async def test_agent_loop_records_unknown_tool_as_canonical_error_result() -> None:
    call = ToolCall(id="call-1", name="missing", arguments={})
    assistant = AssistantMessage(content=[call], model="fake")
    messages: list[AgentMessage] = [UserMessage(content="Use it")]
    provider = FakeProvider(
        [[assistant_start(), tool_call_end(call), assistant_done(assistant, "toolUse")]]
    )

    events = await _collect(
        run_agent_loop(
            provider=provider,
            model="fake",
            system="You are Tau.",
            messages=messages,
            tools=[],
            max_turns=1,
        )
    )

    end = next(event for event in events if isinstance(event, ToolExecutionEndEvent))
    assert end.is_error is True
    assert end.result.text == "Tool missing not found"
    result = next(message for message in messages if isinstance(message, ToolResultMessage))
    assert result.is_error is True
    assert result.text == "Tool missing not found"


@pytest.mark.anyio
async def test_agent_loop_converts_provider_error_to_assistant_error_message() -> None:
    messages: list[AgentMessage] = [UserMessage(content="hello")]
    provider = FakeProvider([[assistant_error("provider failed")]])

    events = await _collect(
        run_agent_loop(
            provider=provider,
            model="fake",
            system="You are Tau.",
            messages=messages,
            tools=[],
        )
    )

    assert [event.type for event in events] == [
        "agent_start",
        "turn_start",
        "message_start",
        "message_end",
        "turn_end",
        "agent_end",
    ]
    error = messages[-1]
    assert isinstance(error, AssistantMessage)
    assert error.stop_reason == "error"
    assert error.error_message == "provider failed"


@pytest.mark.anyio
async def test_agent_loop_excludes_empty_failed_assistant_from_next_provider_call() -> None:
    messages: list[AgentMessage] = []
    recovered = AssistantMessage(content=[TextContent(text="recovered")], model="fake")
    provider = FakeProvider(
        [
            [assistant_error("provider failed")],
            [assistant_start(), assistant_done(recovered)],
        ]
    )

    await _collect(
        run_agent_loop(
            provider=provider,
            model="fake",
            system="You are Tau.",
            messages=messages,
            tools=[],
            prompts=[UserMessage(content="hello")],
        )
    )
    failed = messages[-1]
    assert isinstance(failed, AssistantMessage)
    assert failed.stop_reason == "error"

    await _collect(
        run_agent_loop(
            provider=provider,
            model="fake",
            system="You are Tau.",
            messages=messages,
            tools=[],
            prompts=[UserMessage(content="continue")],
        )
    )

    assert failed in messages
    replayed = provider.calls[1][2]
    assert [message_text(message) for message in replayed] == ["hello", "continue"]
    assert failed not in replayed
    assert messages[-1] is recovered


@pytest.mark.anyio
async def test_agent_loop_injects_steering_and_follow_up_messages() -> None:
    call = ToolCall(id="call-1", name="work", arguments={})

    async def execute(
        tool_call_id: str,
        arguments: Mapping[str, JSONValue],
        signal: ToolCancellationToken | None = None,
        on_update: ToolUpdateCallback | None = None,
    ) -> AgentToolResult:
        del tool_call_id, arguments, signal, on_update
        return AgentToolResult(content=[TextContent(text="ok")])

    first = AssistantMessage(content=[call], model="fake")
    second = AssistantMessage(content=[TextContent(text="second")], model="fake")
    third = AssistantMessage(content=[TextContent(text="third")], model="fake")
    provider = FakeProvider(
        [
            [assistant_start(), tool_call_end(call), assistant_done(first, "toolUse")],
            [assistant_start(), assistant_done(second)],
            [assistant_start(), assistant_done(third)],
        ]
    )
    steering = [UserMessage(content="steer")]
    follow_up = [UserMessage(content="follow up")]

    def pop(queue: list[UserMessage]) -> tuple[UserMessage, ...]:
        return (queue.pop(0),) if queue else ()

    messages: list[AgentMessage] = [UserMessage(content="start")]
    await _collect(
        run_agent_loop(
            provider=provider,
            model="fake",
            system="You are Tau.",
            messages=messages,
            tools=[_tool("work", execute)],
            get_steering_messages=lambda: pop(steering),
            get_follow_up_messages=lambda: pop(follow_up),
        )
    )

    assert [message.text for message in messages if isinstance(message, UserMessage)] == [
        "start",
        "steer",
        "follow up",
    ]
    assert len(provider.calls) == 3


@pytest.mark.anyio
async def test_agent_loop_stops_with_assistant_error_after_max_turns() -> None:
    call = ToolCall(id="call-1", name="missing", arguments={})
    assistant = AssistantMessage(content=[call], model="fake")
    provider = FakeProvider(
        [[assistant_start(), tool_call_end(call), assistant_done(assistant, "toolUse")]]
    )
    messages: list[AgentMessage] = [UserMessage(content="loop")]

    await _collect(
        run_agent_loop(
            provider=provider,
            model="fake",
            system="You are Tau.",
            messages=messages,
            tools=[],
            max_turns=1,
        )
    )

    error = messages[-1]
    assert isinstance(error, AssistantMessage)
    assert error.stop_reason == "error"
    assert error.error_message == "Agent stopped after max_turns=1"
    assert len(provider.calls) == 1
