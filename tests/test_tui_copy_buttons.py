"""Tests for the code-fence and user-prompt copy buttons in the Tau TUI.

Fenced ``` blocks inside assistant (Markdown) messages, user messages, and
tool results render as boxed code areas with a small copy button in the
top-right corner. Submitted user prompts additionally carry their own copy
button on the first line. This module covers button presence, the copied
text, live updates (streaming fences and in-place tool progress), and the
plain fast path staying untouched for rows without fences.
"""

from typing import cast

import pytest
from textual.widgets import Label, Static

from tau_agent import (
    AgentEvent,
    AgentMessage,
    AgentToolResult,
    AssistantMessage,
    TextContent,
    ToolExecutionEndEvent,
    ToolExecutionStartEvent,
    UserMessage,
)
from tau_coding import CodingSession
from tau_coding.tui.app import PromptInput, TauTuiApp
from tau_coding.tui.config import TAU_DARK_THEME
from tau_coding.tui.widgets import (
    CopyFenceButton,
    CopyPromptButton,
    FencedCodeBox,
    FencedPlainBody,
    TauMarkdownFence,
    TranscriptMessageWidget,
    TranscriptView,
)
from test_tui_app import FakeSession


def _tui_app(messages: tuple[AgentMessage, ...]) -> TauTuiApp:
    return TauTuiApp(cast(CodingSession, FakeSession(messages=messages)))


def _user_message(text: str) -> UserMessage:
    return UserMessage(role="user", content=[TextContent(type="text", text=text)])


def _assistant_message(text: str) -> AssistantMessage:
    return AssistantMessage(role="assistant", content=[TextContent(type="text", text=text)])


def _message_buttons(app: TauTuiApp) -> list[CopyFenceButton]:
    return list(app.query(CopyFenceButton))


def _prompt_buttons(app: TauTuiApp) -> list[CopyPromptButton]:
    return list(app.query(CopyPromptButton))


@pytest.mark.anyio
async def test_assistant_fences_get_buttons_and_copy_their_code() -> None:
    app = _tui_app(
        (
            _assistant_message(
                "Here:\n\n"
                "```python\n"
                "def add(a, b):\n"
                "    return a + b\n"
                "```\n\n"
                "And the test:\n\n"
                "```bash\n"
                "pytest -q\n"
                "```"
            ),
        )
    )

    async with app.run_test(size=(110, 30)) as pilot:
        await pilot.pause()
        buttons = _message_buttons(app)
        assert len(buttons) == 2
        fences = [button.parent for button in buttons]
        assert all(isinstance(fence, TauMarkdownFence) for fence in fences)
        # One button per fence, docked to the right edge of its box.
        for button, fence in zip(buttons, fences, strict=True):
            assert button.styles.dock == "right"
            assert button.parent is fence
        # The button docks to the right edge of its box: single-line code gets
        # a header row above it, multi-line code keeps its line count and the
        # button sits at the end of the first line instead.
        for button in buttons:
            fence = button.parent
            assert isinstance(fence, TauMarkdownFence)
            multi_line = len(fence.code.splitlines()) > 1
            assert fence.has_class("-multi-line") == multi_line
            header = fence.query_one(".fence-header", Static)
            assert header.display != multi_line
            code = fence.query_one("#code-content", Label)
            code_row = code.region.y
            expected_button_row = header.region.y if not multi_line else code_row
            assert button.region.y == expected_button_row
            assert not multi_line or code_row == button.region.y

        # The first fence's code is the python block, the second the bash line.
        await pilot.click(buttons[0])
        assert app.clipboard == "def add(a, b):\n    return a + b"
        await pilot.click(buttons[1])
        assert app.clipboard == "pytest -q"

        # Copy feedback flips the label briefly and reverts.
        assert buttons[1].label.plain == "✓"
        await pilot.pause(1.5)
        assert buttons[1].label.plain == "▣"


@pytest.mark.anyio
async def test_user_message_fence_gets_button_and_copies_code() -> None:
    app = _tui_app((_user_message("Run this:\n\n```python\nx = 1\nprint(x)\n```"),))

    async with app.run_test(size=(110, 30)) as pilot:
        await pilot.pause()
        buttons = _message_buttons(app)
        assert len(buttons) == 1
        box = buttons[0].parent
        assert isinstance(box, FencedCodeBox)
        assert isinstance(box.parent, FencedPlainBody)
        # Two code lines: the button sits at the end of the first line and the
        # box keeps its natural line count (no header row).
        assert box.has_class("-multi-line")
        header = box.query_one(".fenced-code-header", Static)
        code = box.query_one(".fenced-code-content", Static)
        assert not header.display
        assert buttons[0].region.y == code.region.y

        await pilot.click(buttons[0])
        assert app.clipboard == "x = 1\nprint(x)"


@pytest.mark.anyio
async def test_user_prompt_gets_copy_button_and_copies_full_text() -> None:
    prompt = "first line\nsecond line\nthird line"
    app = _tui_app((_user_message(prompt),))

    async with app.run_test(size=(110, 30)) as pilot:
        await pilot.pause()
        buttons = _prompt_buttons(app)
        assert len(buttons) == 1
        message = app.query_one(TranscriptMessageWidget)
        assert buttons[0].parent is message
        # The button docks to the right edge of the first prompt line and
        # blends with the prompt row background, unlike fence buttons.
        assert buttons[0].styles.dock == "right"
        assert buttons[0].styles.background == message.styles.background
        assert buttons[0].region.y == message.query_one(".transcript-plain-body").region.y

        await pilot.click(buttons[0])
        assert app.clipboard == prompt
        assert buttons[0].label.plain == "✓"
        await pilot.pause(1.5)
        assert buttons[0].label.plain == "▣"


@pytest.mark.anyio
async def test_fenced_user_prompt_copies_prompt_while_fence_button_copies_code() -> None:
    prompt = "Run this:\n\n```python\nx = 1\nprint(x)\n```\n\nthanks"
    app = _tui_app((_user_message(prompt),))

    async with app.run_test(size=(110, 30)) as pilot:
        await pilot.pause()
        prompt_button = _prompt_buttons(app)[0]
        fence_button = _message_buttons(app)[0]
        assert isinstance(prompt_button.parent, TranscriptMessageWidget)
        assert isinstance(fence_button.parent, FencedCodeBox)
        # Each button blends with the box it sits in: the prompt button with
        # the prompt row, the fence button with the code block.
        assert prompt_button.styles.background == prompt_button.parent.styles.background
        assert fence_button.styles.background == fence_button.parent.styles.background
        # The prompt button sits above the fence, on the prompt's first line.
        assert prompt_button.region.y < fence_button.region.y

        # The prompt button copies the raw prompt, fences included, while the
        # fence button keeps copying just the fenced code.
        await pilot.click(prompt_button)
        assert app.clipboard == prompt
        await pilot.click(fence_button)
        assert app.clipboard == "x = 1\nprint(x)"


@pytest.mark.anyio
async def test_malformed_user_fence_still_gets_prompt_copy_button() -> None:
    prompt = "broken fence\n```python\nx = 1"
    app = _tui_app((_user_message(prompt),))

    async with app.run_test(size=(110, 30)) as pilot:
        await pilot.pause()
        assert not _message_buttons(app)

        await pilot.click(_prompt_buttons(app)[0])
        assert app.clipboard == prompt


@pytest.mark.anyio
async def test_prompt_copy_button_is_not_focusable_and_keeps_prompt_focus() -> None:
    app = _tui_app((_user_message("plain prompt"),))

    async with app.run_test(size=(110, 30)) as pilot:
        await pilot.pause()
        button = _prompt_buttons(app)[0]
        assert button.can_focus is False

        prompt = app.query_one(PromptInput)
        assert app.focused is prompt
        await pilot.click(button)
        assert app.focused is prompt


@pytest.mark.anyio
async def test_only_user_rows_get_prompt_copy_button() -> None:
    app = _tui_app((_user_message("prompt"), _assistant_message("answer")))

    async with app.run_test(size=(110, 30)) as pilot:
        await pilot.pause()
        buttons = _prompt_buttons(app)
        assert len(buttons) == 1
        parent = buttons[0].parent
        assert isinstance(parent, TranscriptMessageWidget)
        assert parent.item.role == "user"


@pytest.mark.anyio
async def test_tool_result_fence_gets_button_and_copies_code() -> None:
    app = _tui_app((_user_message("run it"),))

    async def stream(event: AgentEvent) -> None:
        app.adapter.apply(event)
        await app._apply_streaming_transcript_event(event)

    async with app.run_test(size=(110, 30)) as pilot:
        await pilot.pause()
        app.state.show_tool_results = True
        await stream(
            ToolExecutionStartEvent(tool_call_id="call-1", tool_name="bash", args={"cmd": "pytest"})
        )
        await stream(
            ToolExecutionEndEvent(
                tool_call_id="call-1",
                tool_name="bash",
                result=AgentToolResult(
                    content=[TextContent(text="✓ 1 passed\n\n```text\ncollected 1 item\n```")]
                ),
                is_error=False,
            )
        )
        await pilot.pause()

        buttons = _message_buttons(app)
        assert len(buttons) == 1
        assert isinstance(buttons[0].parent, FencedCodeBox)

        await pilot.click(buttons[0])
        assert app.clipboard == "collected 1 item"


@pytest.mark.anyio
async def test_fenceless_user_message_keeps_fast_plain_static_body() -> None:
    app = _tui_app((_user_message("just plain text, no fences"),))

    async with app.run_test(size=(110, 30)) as pilot:
        await pilot.pause()
        assert not _message_buttons(app)
        message = app.query_one(TranscriptMessageWidget)
        assert isinstance(message.query_one(".transcript-plain-body"), Static)
        assert not app.query(FencedPlainBody)


@pytest.mark.anyio
async def test_malformed_fence_stays_literal_without_buttons() -> None:
    app = _tui_app((_user_message("broken fence\n```python\nx = 1\n"),))

    async with app.run_test(size=(110, 30)) as pilot:
        await pilot.pause()
        assert not _message_buttons(app)
        message = app.query_one(TranscriptMessageWidget)
        body = message.query_one(".transcript-plain-body", Static)
        assert "```python" in str(body.render())


@pytest.mark.anyio
async def test_copy_button_is_not_focusable_and_keeps_prompt_focus() -> None:
    app = _tui_app((_user_message("```python\nx = 1\n```"),))

    async with app.run_test(size=(110, 30)) as pilot:
        await pilot.pause()
        button = _message_buttons(app)[0]
        assert button.can_focus is False

        prompt = app.query_one(PromptInput)
        assert app.focused is prompt
        await pilot.click(button)
        assert app.focused is prompt


@pytest.mark.anyio
async def test_streaming_fence_gets_button_and_code_stays_fresh() -> None:
    app = _tui_app(())

    async with app.run_test(size=(110, 30)) as pilot:
        await pilot.pause()
        transcript = app.query_one("#transcript", TranscriptView)
        await transcript.append_assistant_delta("Here:\n\n```python\n", theme=TAU_DARK_THEME)
        await pilot.pause()
        await transcript.append_assistant_delta("x = 1\n```", theme=TAU_DARK_THEME)
        await pilot.pause()

        buttons = _message_buttons(app)
        assert len(buttons) == 1
        assert isinstance(buttons[0].parent, TauMarkdownFence)

        await pilot.click(buttons[0])
        assert app.clipboard == "x = 1"


@pytest.mark.anyio
async def test_tool_progress_updates_fenced_body_in_place() -> None:
    app = _tui_app((_user_message("run it"),))

    async def stream(event: AgentEvent) -> None:
        app.adapter.apply(event)
        await app._apply_streaming_transcript_event(event)

    async with app.run_test(size=(110, 30)) as pilot:
        await pilot.pause()
        app.state.show_tool_results = True
        await stream(
            ToolExecutionStartEvent(tool_call_id="call-1", tool_name="bash", args={"cmd": "pytest"})
        )
        await stream(
            ToolExecutionEndEvent(
                tool_call_id="call-1",
                tool_name="bash",
                result=AgentToolResult(
                    content=[TextContent(text="```text\ncollected 1 item\n```")]
                ),
                is_error=False,
            )
        )
        await pilot.pause()

        message = next(
            widget for widget in app.query(TranscriptMessageWidget) if widget.item.role == "tool"
        )
        body = message.query_one(".transcript-plain-body", FencedPlainBody)

        # Live progress for the same row updates the boxed body in place.
        message.item.tool_result_text = "✓ bash\n```text\ncollected 1 item, 100% passed\n```"
        assert message.refresh_invocation(show_tool_results=True)
        assert message.query_one(".transcript-plain-body") is body

        button = _message_buttons(app)[0]
        await pilot.click(button)
        assert app.clipboard == "collected 1 item, 100% passed"


@pytest.mark.anyio
async def test_fence_shape_change_falls_back_to_remount() -> None:
    app = _tui_app((_user_message("run it"),))

    async def stream(event: AgentEvent) -> None:
        app.adapter.apply(event)
        await app._apply_streaming_transcript_event(event)

    async with app.run_test(size=(110, 30)) as pilot:
        await pilot.pause()
        app.state.show_tool_results = True
        await stream(
            ToolExecutionStartEvent(tool_call_id="call-1", tool_name="bash", args={"cmd": "pytest"})
        )
        await stream(
            ToolExecutionEndEvent(
                tool_call_id="call-1",
                tool_name="bash",
                result=AgentToolResult(
                    content=[TextContent(text="```text\ncollected 1 item\n```")]
                ),
                is_error=False,
            )
        )
        await pilot.pause()

        message = next(
            widget for widget in app.query(TranscriptMessageWidget) if widget.item.role == "tool"
        )
        message.query_one(".transcript-plain-body", FencedPlainBody)

        # Dropping the fence changes the body shape: refresh must report False
        # so the row is remounted instead of updating in place.
        message.item.tool_result_text = "no fences anymore"
        assert not message.refresh_invocation(show_tool_results=True)
