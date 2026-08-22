import time
from pathlib import Path

from tau_agent import (
    AgentEndEvent,
    AgentStartEvent,
    AgentToolResult,
    AssistantMessage,
    CustomMessage,
    MessageEndEvent,
    MessageStartEvent,
    MessageUpdateEvent,
    RetryEvent,
    TextContent,
    ThinkingContent,
    ToolCall,
    ToolExecutionEndEvent,
    ToolExecutionStartEvent,
    ToolExecutionUpdateEvent,
    UserMessage,
)
from tau_agent.provider_events import TextDeltaEvent, ThinkingDeltaEvent
from tau_coding.events import (
    AgentSettledEvent,
    AutoRetryStartEvent,
    CompactionEndEvent,
    CompactionStartEvent,
    QueueUpdateEvent,
    SessionAgentEndEvent,
)
from tau_coding.skills import Skill, format_skill_invocation
from tau_coding.tui import TuiEventAdapter, TuiState
from tau_coding.tui.state import format_tool_call_block, format_tool_result_block


def _update(event: TextDeltaEvent | ThinkingDeltaEvent) -> MessageUpdateEvent:
    return MessageUpdateEvent(message=event.partial, assistant_message_event=event)


def test_tui_adapter_tracks_running_state() -> None:
    state = TuiState()
    adapter = TuiEventAdapter(state)

    adapter.apply(AgentStartEvent())
    assert state.running is True

    adapter.apply(AgentEndEvent())
    assert state.running is False


def test_tui_adapter_waits_for_session_settlement_after_low_level_agent_end() -> None:
    state = TuiState()
    adapter = TuiEventAdapter(state)

    adapter.apply(AgentStartEvent())
    adapter.apply(SessionAgentEndEvent())
    assert state.running is True

    adapter.apply(AgentSettledEvent())
    assert state.running is False


def test_tui_adapter_replaces_recovered_overflow_with_terminal_retry_error() -> None:
    state = TuiState()
    adapter = TuiEventAdapter(state)
    overflow = AssistantMessage(
        stop_reason="error",
        error_message="prompt is too long: context window exceeded",
    )
    retry_error = AssistantMessage(
        stop_reason="error",
        error_message="authentication failed: API token expired",
    )

    adapter.apply(AgentStartEvent())
    adapter.apply(MessageEndEvent(message=overflow))
    adapter.apply(SessionAgentEndEvent())
    adapter.apply(CompactionStartEvent(reason="overflow"))
    adapter.apply(CompactionEndEvent(reason="overflow", will_retry=True))
    adapter.apply(AgentStartEvent())
    adapter.apply(MessageEndEvent(message=retry_error))
    adapter.apply(SessionAgentEndEvent())
    adapter.apply(AgentSettledEvent())

    error_items = [item for item in state.items if item.role == "error"]
    assert len(error_items) == 1
    assert error_items[0].text == "Error: authentication failed: API token expired"
    assert state.error == "authentication failed: API token expired"
    assert "context window exceeded" not in state.error


def test_tui_adapter_builds_assistant_item_from_nested_stream_events() -> None:
    state = TuiState()
    adapter = TuiEventAdapter(state)
    partial = AssistantMessage()

    adapter.apply(MessageStartEvent(message=partial))
    adapter.apply(_update(TextDeltaEvent(content_index=0, delta="Hel", partial=partial)))
    adapter.apply(_update(TextDeltaEvent(content_index=0, delta="lo", partial=partial)))
    assert state.assistant_buffer == "Hello"

    adapter.apply(MessageEndEvent(message=AssistantMessage(content=[TextContent(text="Hello")])))

    assert state.assistant_buffer == ""
    assert [(item.role, item.text) for item in state.items] == [("assistant", "Hello")]


def test_tui_adapter_keeps_interleaved_thinking_fragments_in_one_row() -> None:
    """Interleaved gateway deltas must not split one reasoning stream across
    multiple provisional thinking rows; the final message then replaces them
    with the canonical coalesced blocks."""
    state = TuiState()
    adapter = TuiEventAdapter(state)
    partial = AssistantMessage()

    adapter.apply(MessageStartEvent(message=partial))
    adapter.apply(
        _update(ThinkingDeltaEvent(content_index=0, delta="Let me expl", partial=partial))
    )
    adapter.apply(
        _update(TextDeltaEvent(content_index=1, delta="Let me confirm the st", partial=partial))
    )
    adapter.apply(
        _update(ThinkingDeltaEvent(content_index=2, delta="ore the reference.", partial=partial))
    )
    adapter.apply(
        _update(
            TextDeltaEvent(
                content_index=3, delta="ate and then study the reference.", partial=partial
            )
        )
    )

    assert state.assistant_buffer == "Let me confirm the state and then study the reference."
    assert [(item.role, item.text) for item in state.items] == [
        ("thinking", "Let me explore the reference.")
    ]

    adapter.apply(
        MessageEndEvent(
            message=AssistantMessage(
                content=[
                    ThinkingContent(
                        thinking="Let me explore the reference.",
                        thinking_signature="reasoning_content",
                    ),
                    TextContent(text="Let me confirm the state and then study the reference."),
                ]
            )
        )
    )
    assert [(item.role, item.text) for item in state.items] == [
        ("thinking", "Let me explore the reference."),
        ("assistant", "Let me confirm the state and then study the reference."),
    ]


def test_tui_adapter_builds_user_and_compact_skill_items() -> None:
    skill = Skill(
        name="review",
        path=Path("/workspace/.tau/skills/review.md"),
        content="# Review\nFull instructions.",
        description="Review code",
    )
    state = TuiState()
    adapter = TuiEventAdapter(state)

    adapter.apply(MessageEndEvent(message=UserMessage(content="Hello Tau")))
    adapter.apply(
        MessageEndEvent(message=UserMessage(content=format_skill_invocation(skill, "check auth")))
    )

    assert [(item.role, item.text) for item in state.items] == [
        ("user", "Hello Tau"),
        ("skill", "Using skill: review"),
        ("user", "check auth"),
    ]


def test_tui_adapter_groups_nested_thinking_deltas() -> None:
    state = TuiState()
    adapter = TuiEventAdapter(state)
    partial = AssistantMessage()

    adapter.apply(_update(ThinkingDeltaEvent(content_index=0, delta="hidden ", partial=partial)))
    adapter.apply(_update(ThinkingDeltaEvent(content_index=0, delta="reasoning", partial=partial)))

    assert [(item.role, item.text) for item in state.items] == [("thinking", "hidden reasoning")]
    assert state.show_thinking is True


def test_tui_state_restores_persisted_assistant_blocks_in_order() -> None:
    state = TuiState()
    state.load_messages(
        [
            AssistantMessage(
                content=[
                    ThinkingContent(thinking="plan"),
                    TextContent(text="before"),
                    ToolCall(id="call-1", name="read", arguments={"path": "README.md"}),
                    ThinkingContent(thinking="continue"),
                    TextContent(text="done"),
                ]
            )
        ]
    )

    assert [item.role for item in state.items] == [
        "thinking",
        "assistant",
        "tool",
        "thinking",
        "assistant",
    ]


def test_tui_adapter_records_tool_progress_and_result() -> None:
    state = TuiState()
    adapter = TuiEventAdapter(state)

    adapter.apply(
        ToolExecutionStartEvent(tool_call_id="call-1", tool_name="read", args={"path": "notes.md"})
    )
    adapter.apply(
        ToolExecutionUpdateEvent(
            tool_call_id="call-1",
            tool_name="read",
            args={"path": "notes.md"},
            partial_result=AgentToolResult(content=[TextContent(text="reading")]),
        )
    )
    adapter.apply(
        ToolExecutionEndEvent(
            tool_call_id="call-1",
            tool_name="read",
            result=AgentToolResult(content=[TextContent(text="done")]),
            is_error=False,
        )
    )

    assert [
        (item.role, item.text, item.tool_result_text, item.update_text) for item in state.items
    ] == [("tool", "→ read notes.md", "✓ read\ndone", None)]


def test_tui_adapter_renders_skill_file_reads_with_skill_style() -> None:
    skill = Skill(
        name="review",
        path=Path("/workspace/.tau/skills/review.md"),
        content="# Review",
        description="Review code",
    )
    state = TuiState(skills=(skill,))
    adapter = TuiEventAdapter(state)

    adapter.apply(
        ToolExecutionStartEvent(
            tool_call_id="call-1",
            tool_name="read",
            args={"path": "/workspace/.tau/skills/review.md"},
        )
    )
    adapter.apply(
        ToolExecutionEndEvent(
            tool_call_id="call-1",
            tool_name="read",
            result=AgentToolResult(content=[TextContent(text="# Review\nFull instructions.")]),
            is_error=False,
        )
    )

    assert [(item.role, item.text, item.tool_result_text) for item in state.items] == [
        ("skill", "Loading skill: review", "✓ read\n# Review\nFull instructions.")
    ]


def test_tui_adapter_records_retry_and_queue_status() -> None:
    state = TuiState()
    adapter = TuiEventAdapter(state)

    adapter.apply(
        AutoRetryStartEvent(
            attempt=2,
            max_attempts=3,
            delay_ms=0,
            error_message="Retrying provider request 2/3 after HTTP 503.",
        )
    )
    adapter.apply(QueueUpdateEvent(steering=("adjust",), follow_up=("after",)))
    adapter.apply(MessageStartEvent(message=AssistantMessage()))
    adapter.apply(
        RetryEvent(
            scope="provider",
            attempt=2,
            max_attempts=3,
            delay_ms=250,
            error_message="Retrying provider request 2/3 after HTTP 503 in 0.25s.",
        )
    )
    adapter.apply(MessageEndEvent(message=AssistantMessage(content=[TextContent(text="Done")])))

    assert [(item.role, item.text) for item in state.items] == [
        ("status", "… Retrying provider request 2/3 after HTTP 503."),
        ("status", "… Retrying provider request 2/3 after HTTP 503 in 0.25s."),
        ("assistant", "Done"),
    ]
    assert state.queued_steering == ("adjust",)
    assert state.queued_follow_up == ("after",)


def test_tui_adapter_keeps_retried_incomplete_error_provisional() -> None:
    state = TuiState()
    adapter = TuiEventAdapter(state)
    interrupted = AssistantMessage(
        content=[ThinkingContent(thinking="unfinished")],
        stop_reason="error",
        error_message="provider interrupted generation",
    )

    adapter.apply(AgentStartEvent())
    adapter.apply(MessageStartEvent(message=AssistantMessage()))
    adapter.apply(
        RetryEvent(
            scope="response",
            attempt=1,
            max_attempts=1,
            delay_ms=0,
            error_message="Provider interrupted generation; retrying once.",
        )
    )
    adapter.apply(MessageEndEvent(message=interrupted))

    assert state.running is True
    assert state.error is None
    assert [(item.role, item.text) for item in state.items] == [
        ("thinking", "unfinished"),
        ("status", "… Provider interrupted generation; retrying once."),
    ]

    adapter.apply(MessageStartEvent(message=AssistantMessage()))
    adapter.apply(MessageEndEvent(message=AssistantMessage(content=[TextContent(text="Done")])))
    adapter.apply(SessionAgentEndEvent())
    adapter.apply(AgentSettledEvent())

    assert state.running is False
    assert state.error is None
    assert state.last_response_was_thinking_only is False


def test_tui_adapter_hides_internal_auto_retry_message() -> None:
    state = TuiState()
    adapter = TuiEventAdapter(state)
    hidden = CustomMessage(
        custom_type="auto-retry",
        content="Continue the task.",
        display=False,
    )

    adapter.apply(MessageEndEvent(message=hidden))
    state.load_messages([hidden])

    assert state.items == []

    interrupted = AssistantMessage(
        content=[ThinkingContent(thinking="unfinished")],
        stop_reason="error",
        error_message="provider interrupted generation",
    )
    state.load_messages(
        [
            interrupted,
            hidden,
            AssistantMessage(content=[TextContent(text="Done")]),
        ]
    )

    assert state.error is None
    assert [(item.role, item.text) for item in state.items] == [
        ("thinking", "unfinished"),
        ("assistant", "Done"),
    ]


def test_tui_adapter_tracks_thinking_only_final_assistant_response() -> None:
    state = TuiState()
    adapter = TuiEventAdapter(state)

    adapter.apply(AgentStartEvent())
    adapter.apply(
        MessageEndEvent(
            message=AssistantMessage(content=[ThinkingContent(thinking="unfinished plan")])
        )
    )

    assert state.last_response_was_thinking_only is True

    adapter.apply(
        MessageEndEvent(
            message=AssistantMessage(
                content=[
                    ThinkingContent(thinking="use a tool"),
                    ToolCall(id="call-1", name="read", arguments={"path": "README.md"}),
                ]
            )
        )
    )
    assert state.last_response_was_thinking_only is False

    adapter.apply(
        MessageEndEvent(
            message=AssistantMessage(
                content=[
                    ThinkingContent(thinking="final plan"),
                    TextContent(text="Completed response"),
                ]
            )
        )
    )
    assert state.last_response_was_thinking_only is False


def test_tui_adapter_records_assistant_error_and_aborted_message() -> None:
    state = TuiState(running=True, assistant_buffer="partial")
    adapter = TuiEventAdapter(state)

    adapter.apply(
        MessageEndEvent(
            message=AssistantMessage(stop_reason="error", error_message="provider failed")
        )
    )

    assert state.error == "provider failed"
    assert [(item.role, item.text) for item in state.items] == [("error", "Error: provider failed")]
    assert state.assistant_buffer == ""


def test_tui_state_restores_partial_assistant_response_and_error() -> None:
    state = TuiState()

    state.load_messages(
        [
            AssistantMessage(
                content=[TextContent(text="partial response")],
                stop_reason="error",
                error_message="provider failed",
            )
        ]
    )

    assert [(item.role, item.text) for item in state.items] == [
        ("assistant", "partial response"),
        ("error", "Error: provider failed"),
    ]
    assert state.error == "provider failed"


def test_tool_formatters_keep_human_readable_output() -> None:
    from tau_agent import ToolCall

    assert (
        format_tool_call_block(
            ToolCall(
                id="call-1",
                name="read",
                arguments={"path": "tests/test_tui_app.py", "offset": 1, "limit": 80},
            )
        )
        == "→ read tests/test_tui_app.py:1-80"
    )
    content = "\n".join(f"line {index}" for index in range(1, 12))
    block = format_tool_result_block(name="read", ok=True, content=content)
    assert "line 8" in block
    assert "line 9" not in block
    assert "3 more lines" in block


def test_tui_adapter_uses_canonical_result_details_for_patch() -> None:
    state = TuiState()
    adapter = TuiEventAdapter(state)

    adapter.apply(
        ToolExecutionEndEvent(
            tool_call_id="call-1",
            tool_name="edit",
            result=AgentToolResult(
                content=[TextContent(text="Successfully replaced 1 block.")],
                details={"patch": "--- a.py\n+++ a.py\n@@\n-old\n+new"},
            ),
            is_error=False,
        )
    )

    assert "Patch:\n--- a.py\n+++ a.py" in (state.items[0].tool_result_text or "")


def test_tui_adapter_records_agent_run_timing_and_finished_badge() -> None:
    state = TuiState()
    adapter = TuiEventAdapter(state)

    adapter.apply(AgentStartEvent())
    assert state.agent_started_at is not None

    adapter.apply(MessageEndEvent(message=_assistant_message("hello")))
    adapter.apply(AgentSettledEvent())

    assert state.agent_started_at is None
    assert state.running is False
    assert state.last_run_elapsed is not None
    assert state.last_run_elapsed >= 0


def test_tui_state_last_run_elapsed_clears_on_new_run() -> None:
    state = TuiState()
    state.start_agent_run()
    state.agent_started_at = time.monotonic() - 65
    assert state.end_agent_run() is not None
    assert 65 <= state.last_run_elapsed < 67

    state.start_agent_run()
    assert state.last_run_elapsed is None
    assert state.agent_started_at is not None


def test_tui_state_end_agent_run_is_idempotent() -> None:
    state = TuiState()
    assert state.end_agent_run() is None
    state.start_agent_run()
    assert state.end_agent_run() is not None
    assert state.end_agent_run() is None


def _assistant_message(content: str) -> AssistantMessage:
    return AssistantMessage(content=[TextContent(text=content)])
