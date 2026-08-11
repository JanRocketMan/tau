import subprocess
from pathlib import Path

import pytest

from tau_agent import (
    AssistantMessage,
    TextContent,
    ThinkingContent,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from tau_coding.context_window import (
    estimate_message_tokens,
    estimate_text_tokens,
    estimate_tool_tokens,
)
from tau_coding.model_context import (
    estimate_model_context_breakdown,
    format_context_token_count,
    format_model_context,
)
from tau_coding.system_prompt import ProjectContextFile
from tau_coding.tools import create_coding_tools
from tau_coding.tui import external_editor
from tau_coding.tui.external_editor import ExternalEditorError, open_text_in_editor


def test_format_model_context_includes_request_contents_and_compact_total(tmp_path: Path) -> None:
    tool = create_coding_tools(cwd=tmp_path)[0]
    messages = [
        UserMessage(content="Inspect this file"),
        AssistantMessage(
            content=[
                ThinkingContent(
                    thinking="I should read it", thinking_signature="reasoning_content"
                ),
                TextContent(text="I will inspect it"),
                ToolCall(id="call-1", name="read", arguments={"path": "README.md"}),
            ]
        ),
        ToolResultMessage(
            tool_call_id="call-1",
            tool_name="read",
            content=[TextContent(text="Project readme")],
        ),
    ]

    rendered = format_model_context(
        system="You are Tau.",
        messages=messages,
        tools=[tool],
        total_tokens=35_000,
    )

    assert rendered.startswith("Total: 35K tokens\nUsage: System ")
    assert rendered.splitlines()[1] == (
        "Usage: System 0K User 0K Project 0K Input 0K Tools 0K Out 0K"
    )
    assert rendered.splitlines()[2:5] == [
        "Contents:",
        "- System prompt",
        "- Tool definitions (1): read",
    ]
    assert rendered.index("# System prompt") < rendered.index("# Tool definitions")
    assert rendered.index("# Tool definitions") < rendered.index("# Messages")
    assert "I should read it" in rendered
    assert '<tool-call id="call-1" name="read">' in rendered
    assert '"path": "README.md"' in rendered
    assert "## Message 3: Tool result (read, ok)" in rendered
    assert "Project readme" in rendered


def test_model_context_breakdown_splits_user_and_project_instruction_files(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repo"
    cwd = repository / "packages" / "app"
    outside = tmp_path / "home" / ".tau" / "AGENTS.md"
    inside = repository / "AGENTS.md"
    cwd.mkdir(parents=True)
    (repository / ".git").mkdir()
    (cwd / "pyproject.toml").write_text("[project]", encoding="utf-8")
    user_content = "u" * 4_000
    project_content = "p" * 2_000
    system = f"Base{user_content}{project_content}"

    breakdown = estimate_model_context_breakdown(
        system=system,
        messages=[],
        tools=[],
        cwd=cwd,
        context_files=[
            ProjectContextFile(path=str(outside), content=user_content),
            ProjectContextFile(path=str(inside), content=project_content),
        ],
    )

    assert breakdown.user == 1_000
    assert breakdown.project == 500
    assert breakdown.system == estimate_text_tokens(system) - 1_500
    assert breakdown.input == 0
    assert breakdown.tools == 0
    assert breakdown.out == 0

    rendered = format_model_context(
        system=system,
        messages=[],
        tools=[],
        total_tokens=1_501,
        cwd=cwd,
        context_files=[
            ProjectContextFile(path=str(outside), content=user_content),
            ProjectContextFile(path=str(inside), content=project_content),
        ],
    )
    assert rendered.splitlines()[1] == (
        "Usage: System 0K User 1K Project 1K Input 0K Tools 0K Out 0K"
    )


def test_model_context_breakdown_splits_input_tool_and_assistant_messages(
    tmp_path: Path,
) -> None:
    tool = create_coding_tools(cwd=tmp_path)[0]
    user_message = UserMessage(content="u" * 4_000)
    tool_result = ToolResultMessage(
        tool_call_id="call-1",
        tool_name="read",
        content=[TextContent(text="t" * 8_000)],
    )
    assistant_message = AssistantMessage(
        content=[
            ThinkingContent(thinking="h" * 2_000),
            TextContent(text="o" * 12_000),
            ToolCall(id="call-2", name="write", arguments={"content": "a" * 2_000}),
        ]
    )

    breakdown = estimate_model_context_breakdown(
        system="System",
        messages=[user_message, tool_result, assistant_message],
        tools=[tool],
        cwd=tmp_path,
        context_files=[],
    )

    assert breakdown.system == estimate_text_tokens("System") + estimate_tool_tokens(tool)
    assert breakdown.input == estimate_message_tokens(user_message)
    assert breakdown.tools == estimate_message_tokens(tool_result)
    assert breakdown.out == estimate_message_tokens(assistant_message)


def test_format_model_context_excludes_empty_failed_assistant_messages() -> None:
    rendered = format_model_context(
        system="System",
        messages=[
            UserMessage(content="Hello"),
            AssistantMessage(content=[], stop_reason="error", error_message="failed"),
        ],
        tools=[],
        total_tokens=999,
    )

    assert "Total: 1K tokens" in rendered
    assert "- Messages: 1" in rendered
    assert "## Message 1: User" in rendered
    assert "## Message 2" not in rendered


@pytest.mark.parametrize(
    ("tokens", "expected"),
    [
        (0, "0K"),
        (52, "0K"),
        (199, "0K"),
        (200, "1K"),
        (881, "1K"),
        (1_000, "1K"),
        (1_499, "1K"),
        (1_500, "2K"),
        (9_900, "10K"),
        (9_978, "10K"),
        (11_357, "11K"),
        (197_000, "197K"),
        (1_000_000, "1000K"),
    ],
)
def test_format_context_token_count_uses_nearest_whole_k(tokens: int, expected: str) -> None:
    assert format_context_token_count(tokens) == expected


def test_resolve_editor_command_prefers_visual_then_editor() -> None:
    assert external_editor.resolve_editor_command({"VISUAL": "code --wait", "EDITOR": "vim"}) == (
        "code",
        "--wait",
    )
    assert external_editor.resolve_editor_command({"EDITOR": "vim -f"}) == ("vim", "-f")


def test_open_text_in_editor_uses_temporary_markdown_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured_path: Path | None = None
    captured_text: str | None = None

    def fake_run(command: list[str], *, cwd: Path, check: bool) -> subprocess.CompletedProcess[str]:
        nonlocal captured_path, captured_text
        assert command[:2] == ["code", "--wait"]
        assert cwd == tmp_path
        assert check is False
        captured_path = Path(command[-1])
        captured_text = captured_path.read_text(encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(external_editor.subprocess, "run", fake_run)

    open_text_in_editor(
        "Total: 1K tokens\n",
        cwd=tmp_path,
        environ={"EDITOR": "code --wait"},
    )

    assert captured_text == "Total: 1K tokens\n"
    assert captured_path is not None
    assert not captured_path.exists()


def test_open_text_in_editor_reports_nonzero_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(command: list[str], *, cwd: Path, check: bool) -> subprocess.CompletedProcess[str]:
        del cwd, check
        return subprocess.CompletedProcess(command, 2)

    monkeypatch.setattr(external_editor.subprocess, "run", fake_run)

    with pytest.raises(ExternalEditorError, match="exited with status 2"):
        open_text_in_editor("context", cwd=tmp_path, environ={"EDITOR": "false"})
