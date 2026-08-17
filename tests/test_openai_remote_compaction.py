"""Unit tests for the OpenAI Responses server-side compaction protocol."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from tau_agent.messages import (
    AssistantMessage,
    TextContent,
    ThinkingContent,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from tau_agent.tools import AgentTool, AgentToolResult
from tau_ai.openai_remote_compaction import (
    COMPACTION_ITEM_TYPE,
    COMPACTION_TRIGGER_TYPE,
    RemoteCompactionError,
    build_codex_compaction_headers,
    build_remote_compaction_payload,
    build_replacement_history,
    call_remote_compaction_v2,
    messages_to_response_items,
    normalize_usage_snapshot,
    parse_compaction_sse,
    remote_compaction_endpoint,
    responses_tools_payload,
)


def _sse(*payloads: str) -> str:
    """Join JSON payloads as SSE ``data:`` lines."""
    return "\n\n".join(f"data: {payload}" for payload in payloads)


def _compaction_event(item: dict[str, Any] | None = None, item_id: str = "item_1") -> str:
    item = item or {
        "type": COMPACTION_ITEM_TYPE,
        "id": item_id,
        "encrypted_content": "opaque-blob",
    }
    return json.dumps(
        {
            "type": "response.output_item.done",
            "item": item,
        }
    )


def _completed_event(usage: dict[str, Any] | None = None) -> str:
    return json.dumps(
        {
            "type": "response.completed",
            "response": {
                "usage": usage
                or {
                    "input_tokens": 100,
                    "output_tokens": 5,
                    "total_tokens": 105,
                    "input_tokens_details": {"cached_tokens": 40},
                }
            },
        }
    )


def test_remote_compaction_endpoint_resolution() -> None:
    assert (
        remote_compaction_endpoint(base_url="https://chatgpt.com/backend-api", model="gpt-5.4")
        == "https://chatgpt.com/backend-api/codex/responses"
    )
    assert (
        remote_compaction_endpoint(base_url="https://chatgpt.com/backend-api/", model="gpt-5.4")
        == "https://chatgpt.com/backend-api/codex/responses"
    )
    assert (
        remote_compaction_endpoint(base_url="https://example.com/codex", model="gpt-5.4")
        == "https://example.com/codex/responses"
    )


def test_build_codex_compaction_headers_shape() -> None:
    headers = build_codex_compaction_headers(
        "jwt-access-token",
        account_id="acct_123",
        session_id="session-9",
    )
    assert headers["Authorization"] == "Bearer jwt-access-token"
    assert headers["chatgpt-account-id"] == "acct_123"
    assert headers["originator"] == "tau"
    assert headers["OpenAI-Beta"] == "responses=experimental"
    assert headers["x-codex-beta-features"] == "remote_compaction_v2"
    assert headers["x-codex-installation-id"]
    assert headers["x-codex-window-id"] == "session-9:0"
    assert headers["session_id"] == "session-9"


def test_build_remote_compaction_payload_appends_compaction_trigger() -> None:
    payload = build_remote_compaction_payload(
        model="gpt-5.6-sol",
        input_items=[
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "hi"}],
            }
        ],
        instructions="You are Tau.",
        tools=[{"type": "function", "name": "read", "parameters": {}}],
    )
    assert payload["model"] == "gpt-5.6-sol"
    assert payload["store"] is False
    assert payload["include"] == ["reasoning.encrypted_content"]
    assert payload["parallel_tool_calls"] is True
    assert payload["input"][-1] == {"type": COMPACTION_TRIGGER_TYPE}
    assert payload["input"][0]["type"] == "message"
    assert payload["tools"][0]["name"] == "read"


def test_messages_to_response_items_converts_roles() -> None:
    messages = [
        UserMessage(content="hello"),
        AssistantMessage(
            content=[
                ThinkingContent(
                    thinking="reasoning text",
                    thinking_signature=json.dumps(
                        {
                            "type": "reasoning",
                            "summary": [{"type": "summary_text", "text": "brief"}],
                        }
                    ),
                ),
                TextContent(text="answer"),
                ToolCall(id="call_1", name="read", arguments={"path": "a.py"}),
            ]
        ),
        ToolResultMessage(tool_call_id="call_1", tool_name="read", content="contents"),
    ]
    items = messages_to_response_items(messages)
    assert items[0] == {"role": "user", "content": "hello"}
    assert items[1]["type"] == "reasoning"
    assert items[2] == {"role": "assistant", "content": "answer"}
    assert items[3] == {
        "type": "function_call",
        "call_id": "call_1",
        "name": "read",
        "arguments": '{"path": "a.py"}',
    }
    assert items[4] == {"type": "function_call_output", "call_id": "call_1", "output": "contents"}


def test_responses_tools_payload_builds_function_tools() -> None:
    tool = AgentTool(
        name="read",
        label="read",
        description="Read a file",
        parameters={"type": "object", "properties": {"path": {"type": "string"}}},
        execute_fn=lambda _params: AgentToolResult(content=[TextContent(text="ok")]),
    )
    payload = responses_tools_payload([tool])
    assert payload == [
        {
            "type": "function",
            "name": "read",
            "description": "Read a file",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
        }
    ]


def test_parse_compaction_sse_returns_item_and_usage() -> None:
    text = _sse(
        json.dumps({"type": "response.created", "response": {"id": "r_1"}}),
        _compaction_event(),
        _completed_event(),
        "[DONE]",
    )
    item, usage = parse_compaction_sse(text)
    assert item["type"] == COMPACTION_ITEM_TYPE
    assert item["encrypted_content"] == "opaque-blob"
    assert usage == {
        "input": 60,
        "output": 5,
        "cache_read": 40,
        "cache_write": 0,
        "total_tokens": 105,
    }


def test_parse_compaction_sse_rejects_error_event() -> None:
    text = _sse(json.dumps({"type": "error", "message": "boom"}))
    with pytest.raises(RemoteCompactionError, match="boom"):
        parse_compaction_sse(text)


def test_parse_compaction_sse_rejects_failed_response() -> None:
    text = _sse(
        json.dumps(
            {
                "type": "response.failed",
                "response": {"error": {"message": "rate limited"}},
            }
        )
    )
    with pytest.raises(RemoteCompactionError, match="rate limited"):
        parse_compaction_sse(text)


def test_parse_compaction_sse_requires_completion() -> None:
    text = _sse(_compaction_event())
    with pytest.raises(RemoteCompactionError, match="response.completed"):
        parse_compaction_sse(text)


def test_parse_compaction_sse_requires_exactly_one_compaction_item() -> None:
    text = _sse(_compaction_event(), _compaction_event(item_id="item_2"), _completed_event())
    with pytest.raises(RemoteCompactionError, match="exactly one"):
        parse_compaction_sse(text)


def test_normalize_usage_snapshot_handles_missing_details() -> None:
    assert normalize_usage_snapshot({"input_tokens": 10, "output_tokens": 2}) == {
        "input": 10,
        "output": 2,
        "cache_read": 0,
        "cache_write": 0,
        "total_tokens": 12,
    }
    assert normalize_usage_snapshot(None) is None


def _user_item(text: str) -> dict[str, Any]:
    return {"type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]}


def test_build_replacement_history_keeps_recent_user_messages() -> None:
    input_items = [
        _user_item("old question"),
        {"type": "function_call", "call_id": "c1", "name": "read", "arguments": "{}"},
        {"type": "function_call_output", "call_id": "c1", "output": "x"},
        _user_item(""),
        _user_item("recent question"),
    ]
    compaction = {"type": COMPACTION_ITEM_TYPE, "encrypted_content": "blob"}
    history = build_replacement_history(input_items, compaction)
    # Empty user messages are dropped; non-user items are dropped; real user
    # messages are kept oldest-first within the (large) default budget, with
    # the opaque compaction item last.
    assert history == [
        _user_item("old question"),
        _user_item("recent question"),
        compaction,
    ]


def test_build_replacement_history_truncates_to_token_budget() -> None:
    input_items = [_user_item("a" * 200), _user_item("b" * 10)]
    compaction = {"type": COMPACTION_ITEM_TYPE, "encrypted_content": "blob"}
    history = build_replacement_history(input_items, compaction, retain_token_budget=10)
    # Budget 10 tokens = 40 chars: the newest message fits (3 tokens), the
    # older one is truncated to the remaining 7 tokens = 28 chars.
    assert len(history) == 3
    assert history[0] == {
        "type": "message",
        "role": "user",
        "content": [{"type": "input_text", "text": "a" * 28}],
    }
    assert history[1] == _user_item("b" * 10)
    assert history[2] == compaction


def test_call_remote_compaction_v2_round_trip_with_mock_transport() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            text=_sse(
                _compaction_event(),
                _completed_event(),
            ),
        )

    async def run() -> None:
        result = await call_remote_compaction_v2(
            base_url="https://chatgpt.com/backend-api",
            api_key="jwt-access-token",
            headers={
                "chatgpt-account-id": "acct_123",
                "originator": "tau",
                "OpenAI-Beta": "responses=experimental",
                "x-codex-beta-features": "remote_compaction_v2",
            },
            model="gpt-5.4",
            input_items=[_user_item("keep me")],
            instructions="You are Tau.",
            tools=[],
            transport=httpx.MockTransport(handler),
        )
        assert captured["url"] == "https://chatgpt.com/backend-api/codex/responses"
        assert captured["headers"]["authorization"] == "Bearer jwt-access-token"
        assert captured["headers"]["x-codex-beta-features"] == "remote_compaction_v2"
        assert captured["headers"]["chatgpt-account-id"] == "acct_123"
        body = captured["body"]
        assert body["input"][-1] == {"type": COMPACTION_TRIGGER_TYPE}
        assert result.usage is not None
        assert result.usage["total_tokens"] == 105
        # Replacement history keeps the retained user message plus the item.
        assert result.output[0] == _user_item("keep me")
        assert result.output[-1]["type"] == COMPACTION_ITEM_TYPE

    import anyio

    anyio.run(run)


def test_call_remote_compaction_v2_raises_on_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="unauthorized")

    async def run() -> None:
        with pytest.raises(RemoteCompactionError, match="401"):
            await call_remote_compaction_v2(
                base_url="https://chatgpt.com/backend-api",
                api_key="jwt-access-token",
                headers={},
                model="gpt-5.4",
                input_items=[],
                instructions="You are Tau.",
                tools=[],
                transport=httpx.MockTransport(handler),
            )

    import anyio

    anyio.run(run)