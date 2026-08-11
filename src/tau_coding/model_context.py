"""Human-readable snapshots of the active model context."""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from tau_agent.loop import provider_context_messages
from tau_agent.messages import (
    AgentMessage,
    AssistantMessage,
    ImageContent,
    TextContent,
    ThinkingContent,
    ToolResultMessage,
    UserMessage,
    message_to_user,
)
from tau_agent.tools import AgentTool
from tau_coding.context import find_repository_root
from tau_coding.context_window import (
    estimate_message_tokens,
    estimate_text_tokens,
    estimate_tool_tokens,
)
from tau_coding.system_prompt import ProjectContextFile


@dataclass(frozen=True, slots=True)
class ModelContextTokenBreakdown:
    """Estimated token use by source in one active model context."""

    system: int
    user: int
    project: int
    input: int
    tools: int
    out: int


def format_model_context(
    *,
    system: str,
    messages: Sequence[AgentMessage],
    tools: Sequence[AgentTool],
    total_tokens: int,
    cwd: Path | None = None,
    context_files: Sequence[ProjectContextFile] = (),
) -> str:
    """Return a readable snapshot of the context for the next model request."""
    context_messages = provider_context_messages(messages)
    breakdown = estimate_model_context_breakdown(
        system=system,
        messages=context_messages,
        tools=tools,
        cwd=cwd,
        context_files=context_files,
    )
    tool_names = ", ".join(tool.name for tool in tools) or "none"
    lines = [
        f"Total: {format_context_token_count(total_tokens)} tokens",
        _format_usage(breakdown),
        "Contents:",
        "- System prompt",
        f"- Tool definitions ({len(tools)}): {tool_names}",
        f"- Messages: {len(context_messages)}",
        "",
        "# System prompt",
        "",
        system,
        "",
        "# Tool definitions",
        "",
    ]

    if tools:
        for tool in tools:
            lines.extend(_format_tool(tool))
    else:
        lines.append("(none)")

    lines.extend(("", "# Messages", ""))
    if context_messages:
        for index, message in enumerate(context_messages, start=1):
            lines.extend(_format_message(index, message))
    else:
        lines.append("(none)")

    return "\n".join(lines).rstrip() + "\n"


def estimate_model_context_breakdown(
    *,
    system: str,
    messages: Sequence[AgentMessage],
    tools: Sequence[AgentTool],
    cwd: Path | None,
    context_files: Sequence[ProjectContextFile],
) -> ModelContextTokenBreakdown:
    """Estimate context tokens by system source and provider-message role."""
    user_tokens = 0
    project_tokens = 0
    project_root = find_repository_root(cwd) if cwd is not None else None
    for context_file in context_files:
        tokens = estimate_text_tokens(context_file.content)
        if project_root is not None and _path_is_within(context_file.path, project_root):
            project_tokens += tokens
        else:
            user_tokens += tokens

    system_tokens = max(
        0,
        estimate_text_tokens(system) - user_tokens - project_tokens,
    ) + sum(estimate_tool_tokens(tool) for tool in tools)
    input_tokens = 0
    tool_output_tokens = 0
    assistant_output_tokens = 0
    for message in messages:
        tokens = estimate_message_tokens(message)
        if isinstance(message, AssistantMessage):
            assistant_output_tokens += tokens
        elif isinstance(message, ToolResultMessage):
            tool_output_tokens += tokens
        else:
            input_tokens += tokens

    return ModelContextTokenBreakdown(
        system=system_tokens,
        user=user_tokens,
        project=project_tokens,
        input=input_tokens,
        tools=tool_output_tokens,
        out=assistant_output_tokens,
    )


def _format_usage(breakdown: ModelContextTokenBreakdown) -> str:
    return (
        f"Usage: System {format_context_token_count(breakdown.system)} "
        f"User {format_context_token_count(breakdown.user)} "
        f"Project {format_context_token_count(breakdown.project)} "
        f"Input {format_context_token_count(breakdown.input)} "
        f"Tools {format_context_token_count(breakdown.tools)} "
        f"Out {format_context_token_count(breakdown.out)}"
    )


def _path_is_within(path: str, root: Path) -> bool:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        candidate.resolve().relative_to(root)
    except ValueError:
        return False
    return True


def format_context_token_count(tokens: int) -> str:
    """Format tokens to the nearest whole K, using 0K below 200 tokens."""
    normalized = max(0, tokens)
    if normalized < 200:
        return "0K"
    thousands = max(1, (normalized + 500) // 1_000)
    return f"{thousands}K"


def _format_tool(tool: AgentTool) -> list[str]:
    schema = json.dumps(tool.input_schema, indent=2, ensure_ascii=False)
    return [
        f"## Tool: {tool.name}",
        "",
        tool.description,
        "",
        "Input schema:",
        "",
        "```json",
        schema,
        "```",
        "",
    ]


def _format_message(index: int, message: AgentMessage) -> list[str]:
    if isinstance(message, UserMessage):
        return _format_user_message(index, message)
    if isinstance(message, AssistantMessage):
        return _format_assistant_message(index, message)
    if isinstance(message, ToolResultMessage):
        return _format_tool_result_message(index, message)

    projected = message_to_user(message)
    lines = [f"## Message {index}: User ({message.role})", ""]
    lines.extend(_format_content(projected.content))
    lines.append("")
    return lines


def _format_user_message(index: int, message: UserMessage) -> list[str]:
    lines = [f"## Message {index}: User", ""]
    lines.extend(_format_content(message.content))
    lines.append("")
    return lines


def _format_assistant_message(index: int, message: AssistantMessage) -> list[str]:
    lines = [f"## Message {index}: Assistant", ""]
    if not message.content:
        lines.append("(no content)")
    for block in message.content:
        if isinstance(block, TextContent):
            lines.extend(("<text>", block.text, "</text>"))
        elif isinstance(block, ThinkingContent):
            lines.extend(("<thinking>", block.thinking, "</thinking>"))
        else:
            lines.extend(
                (
                    f'<tool-call id="{block.id}" name="{block.name}">',
                    json.dumps(block.arguments, indent=2, ensure_ascii=False),
                    "</tool-call>",
                )
            )
    lines.append("")
    return lines


def _format_tool_result_message(index: int, message: ToolResultMessage) -> list[str]:
    status = "error" if message.is_error else "ok"
    lines = [
        f"## Message {index}: Tool result ({message.tool_name}, {status})",
        "",
        f'<tool-result call-id="{message.tool_call_id}">',
    ]
    lines.extend(_format_content(message.content))
    lines.extend(("</tool-result>", ""))
    return lines


def _format_content(content: str | Sequence[TextContent | ImageContent]) -> list[str]:
    if isinstance(content, str):
        return [content]

    lines: list[str] = []
    for block in content:
        if isinstance(block, TextContent):
            lines.append(block.text)
        else:
            lines.extend(
                (
                    f'<image mime-type="{block.mime_type}" encoding="base64">',
                    block.data,
                    "</image>",
                )
            )
    return lines or ["(no content)"]
