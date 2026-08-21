"""OpenAI Responses server-side compaction protocol (prototype).

Mirrors the protocol the Codex CLI uses against the Codex subscription
backend: ``POST {backend-api}/codex/responses`` with the conversation
converted to Responses ``input`` items plus a trailing ``compaction_trigger``
item, then read the SSE stream and expect exactly one opaque ``compaction``
item. Future Codex Responses requests can replay the retained input items
plus that opaque item for higher-fidelity continuity across the compaction
boundary.

Tau keeps its portable text summary as the source of truth. This module only
produces the provider-native sidecar artifact stored in
``CompactionEntry.details``; session semantics, exports, forks, and
non-Codex providers keep using the text summary.

This is a prototype of "Path A" (core provider feature) scoped to the
``openai-codex`` subscription provider only. It deliberately does not attempt
WebSocket continuation or ``previous_response_id`` reuse, and it does not
cover direct ``api.openai.com`` Responses models.
"""

from __future__ import annotations

from collections.abc import Awaitable, Sequence
from dataclasses import dataclass
from json import loads
from typing import Any, Protocol
from uuid import uuid4

import httpx

from tau_agent.messages import AgentMessage
from tau_agent.tools import AgentTool
from tau_agent.types import JSONValue
from tau_ai.env import (
    DEFAULT_OPENAI_COMPATIBLE_STREAM_IDLE_TIMEOUT_SECONDS,
    DEFAULT_OPENAI_COMPATIBLE_TIMEOUT_SECONDS,
)
from tau_ai.http import create_async_client, streaming_timeout
from tau_ai.openai_cache import openai_prompt_cache_key
from tau_ai.openai_codex import _resolve_codex_url
from tau_ai.openai_compatible import _messages_to_responses_input

RETAINED_USER_MESSAGE_TOKEN_BUDGET = 20_000
REMOTE_COMPACTION_PROVIDER = "openai-responses-compaction"
REMOTE_COMPACTION_VERSION = 2
COMPACTION_TRIGGER_TYPE = "compaction_trigger"
COMPACTION_ITEM_TYPE = "compaction"
REMOTE_COMPACTION_V2_FEATURE = "remote_compaction_v2"
CODE_X_INSTALLATION_ID: str = str(uuid4())
"""Stable per-process Codex installation id (parity with the reference extension)."""


class RemoteCompactionError(RuntimeError):
    """Raised when the Responses compaction protocol fails."""


@dataclass(frozen=True, slots=True)
class RemoteCompactionResult:
    """One successful Responses compaction v2 result."""

    output: list[JSONValue]
    """Replacement history items: retained user messages plus the opaque compaction item."""

    usage: dict[str, JSONValue] | None
    """Normalized usage snapshot from ``response.completed``, when present."""


class RemoteCompactionCall(Protocol):
    """Callable seam used by the coding session for remote compaction.

    The session injects its own implementation in tests; production uses
    :func:`call_remote_compaction_v2`.
    """

    def __call__(
        self,
        *,
        base_url: str,
        api_key: str,
        headers: dict[str, str],
        model: str,
        input_items: list[JSONValue],
        instructions: str,
        tools: list[JSONValue],
        session_id: str | None = None,
    ) -> Awaitable[RemoteCompactionResult]: ...


def messages_to_response_items(
    messages: Sequence[AgentMessage],
    *,
    supports_images: bool = False,
) -> list[JSONValue]:
    """Convert provider-neutral messages to Responses ``input`` items."""
    return _messages_to_responses_input(list(messages), supports_images=supports_images)


def remote_compaction_endpoint(*, base_url: str, model: str) -> str:
    """Resolve the Codex Responses endpoint for a compaction request."""
    del model  # The codex transport always appends ``/codex/responses``.
    return _resolve_codex_url(base_url)


def build_codex_compaction_headers(
    access_token: str,
    *,
    account_id: str,
    originator: str = "tau",
    session_id: str | None = None,
) -> dict[str, str]:
    """Build the Codex subscription headers for a remote compaction request.

    ``access_token`` is the Codex access JWT and ``account_id`` its
    ``chatgpt_account_id`` claim (resolved by the session). Mirrors the
    reference extension's header parity: identity headers plus the
    ``remote_compaction_v2`` beta feature flag that enables the v2 protocol.
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "chatgpt-account-id": account_id,
        "originator": originator,
        "User-Agent": "tau",
        "OpenAI-Beta": "responses=experimental",
        "accept": "text/event-stream",
        "content-type": "application/json",
        "x-codex-installation-id": CODE_X_INSTALLATION_ID,
        "x-codex-beta-features": REMOTE_COMPACTION_V2_FEATURE,
    }
    if session_id is not None:
        headers["x-codex-window-id"] = f"{session_id}:0"
        headers["session_id"] = session_id
    return headers


def responses_tools_payload(tools: Sequence[AgentTool]) -> list[JSONValue]:
    """Build the Responses ``tools`` payload for the active tools."""
    return [
        {
            "type": "function",
            "name": tool.name,
            "description": tool.description,
            "parameters": dict(tool.input_schema),
        }
        for tool in tools
    ]


def build_remote_compaction_payload(
    *,
    model: str,
    input_items: Sequence[JSONValue],
    instructions: str,
    tools: Sequence[JSONValue],
    session_id: str | None = None,
) -> dict[str, JSONValue]:
    """Build the compaction request body with a trailing ``compaction_trigger``.

    The payload mirrors the shape of surrounding normal Responses requests
    (instructions, tools, reasoning via ``include``) rather than endpoint
    defaults, matching the reference Pi extension.
    """
    payload: dict[str, JSONValue] = {
        "model": model,
        "input": [*input_items, {"type": COMPACTION_TRIGGER_TYPE}],
        "instructions": instructions,
        "tools": list(tools),
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "stream": True,
        "store": False,
        "include": ["reasoning.encrypted_content"],
    }
    cache_key = openai_prompt_cache_key(session_id)
    if cache_key is not None:
        payload["prompt_cache_key"] = cache_key
    return payload


def _parse_sse_blocks(text: str) -> list[dict[str, Any]]:
    """Parse ``data:`` lines out of a Responses SSE text body."""
    events: list[dict[str, Any]] = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        data_lines = [line[5:].lstrip() for line in block.split("\n") if line.startswith("data:")]
        data = "\n".join(data_lines).strip()
        if not data or data == "[DONE]":
            continue
        try:
            parsed = loads(data)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            events.append(parsed)
    return events


def _int(value: object) -> int:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def normalize_usage_snapshot(value: object) -> dict[str, JSONValue] | None:
    """Normalize a Responses usage block into a portable snapshot."""
    if not isinstance(value, dict):
        return None
    details = value.get("input_tokens_details")
    cached = _int(details.get("cached_tokens") if isinstance(details, dict) else None)
    cache_write = _int(
        (details.get("cache_creation_tokens") or details.get("cache_write_tokens"))
        if isinstance(details, dict)
        else None
    )
    input_tokens = _int(value.get("input_tokens"))
    output_tokens = _int(value.get("output_tokens"))
    total_tokens = _int(value.get("total_tokens")) or (input_tokens + output_tokens)
    return {
        "input": max(0, input_tokens - cached - cache_write),
        "output": output_tokens,
        "cache_read": cached,
        "cache_write": cache_write,
        "total_tokens": total_tokens,
    }


def _remote_error_message(event: dict[str, Any], *, fallback: str) -> str:
    """Extract a safe scalar error message from a Responses event."""
    sources: list[dict[str, Any]] = [event]
    nested_error = event.get("error")
    if isinstance(nested_error, dict):
        sources.append(nested_error)
    response = event.get("response")
    if isinstance(response, dict):
        response_error = response.get("error")
        if isinstance(response_error, dict):
            sources.append(response_error)

    for key in ("message", "detail", "code"):
        for source in sources:
            value = source.get(key)
            if isinstance(value, str) and value:
                return value
    for source in sources[1:]:
        value = source.get("type")
        if isinstance(value, str) and value:
            return value
    return fallback


def _http_error_message(response: httpx.Response) -> str:
    """Return safe HTTP failure details without copying a response body to logs."""
    try:
        payload = response.json()
    except ValueError:
        return response.reason_phrase
    if not isinstance(payload, dict):
        return response.reason_phrase
    return _remote_error_message(payload, fallback=response.reason_phrase)


def parse_compaction_sse(text: str) -> tuple[JSONValue, dict[str, JSONValue] | None]:
    """Parse a compaction SSE body and return the opaque item plus usage.

    Raises :class:`RemoteCompactionError` on error events, a failed response,
    a stream that never completes, or when the stream does not yield exactly
    one ``compaction`` item.
    """
    completed = False
    usage: dict[str, JSONValue] | None = None
    compaction_items: list[JSONValue] = []

    for event in _parse_sse_blocks(text):
        event_type = event.get("type")
        if event_type == "error":
            message = _remote_error_message(event, fallback="unknown error")
            raise RemoteCompactionError(f"OpenAI remote compaction failed: {message}")
        if event_type == "response.failed":
            message = _remote_error_message(event, fallback="response failed")
            raise RemoteCompactionError(f"OpenAI remote compaction failed: {message}")
        if event_type == "response.output_item.done":
            item = event.get("item")
            if isinstance(item, dict) and item.get("type") == COMPACTION_ITEM_TYPE:
                compaction_items.append(item)
        if event_type == "response.completed":
            completed = True
            response = event.get("response")
            if isinstance(response, dict):
                usage = normalize_usage_snapshot(response.get("usage"))

    if not completed:
        raise RemoteCompactionError(
            "OpenAI remote compaction stream ended before response.completed."
        )
    if len(compaction_items) != 1:
        raise RemoteCompactionError(
            "OpenAI remote compaction expected exactly one compaction item, "
            f"got {len(compaction_items)}."
        )
    return compaction_items[0], usage


def _is_real_user_message(item: JSONValue) -> bool:
    """Return whether an input item is a user message with real content.

    Empty or whitespace-only text parts do not count, so a message that only
    contains an empty ``input_text`` part is dropped like an empty string form.
    """
    if not isinstance(item, dict):
        return False
    if item.get("type") == "message" and item.get("role") == "user":
        content = item.get("content")
        if isinstance(content, str):
            return bool(content.strip())
        if isinstance(content, list):
            return any(
                not isinstance(part, dict)
                or part.get("type") != "input_text"
                or bool(part.get("text"))
                for part in content
            )
    return False


def _message_text_tokens(item: JSONValue) -> int:
    if not isinstance(item, dict):
        return 0
    content = item.get("content")
    if isinstance(content, str):
        return max(1, (len(content) + 3) // 4)
    if isinstance(content, list):
        chars = 0
        for part in content:
            if not isinstance(part, dict):
                continue
            text = part.get("text")
            if isinstance(text, str):
                chars += len(text)
        return max(1, (chars + 3) // 4)
    return 1


def _truncate_message_to_budget(item: JSONValue, max_tokens: int) -> JSONValue | None:
    """Truncate one user message to a remaining token budget, if possible."""
    if not isinstance(item, dict):
        return item
    content = item.get("content")
    if isinstance(content, str):
        remaining = max(0, max_tokens * 4)
        text = content[:remaining]
        return {**item, "content": text} if text else None
    if isinstance(content, list):
        remaining_chars = max(0, max_tokens * 4)
        kept: list[JSONValue] = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "input_image":
                kept.append(part)
                continue
            if remaining_chars == 0 or not isinstance(part, dict):
                continue
            part_text = part.get("text")
            if isinstance(part_text, str):
                truncated = part_text[:remaining_chars]
                remaining_chars -= len(truncated)
                if truncated:
                    kept.append({**part, "text": truncated})
        return {**item, "content": kept} if kept else None
    return item


def build_replacement_history(
    input_items: Sequence[JSONValue],
    compaction_item: JSONValue,
    *,
    retain_token_budget: int = RETAINED_USER_MESSAGE_TOKEN_BUDGET,
) -> list[JSONValue]:
    """Build the replayable replacement history for future Responses requests.

    Keeps the most recent real user messages within the token budget, oldest
    first, then the opaque compaction item. Empty or whitespace-only user
    messages are dropped, matching the reference implementation.
    """
    retained_messages = [item for item in input_items if _is_real_user_message(item)]
    kept: list[JSONValue] = []
    remaining = retain_token_budget
    for item in reversed(retained_messages):
        if remaining <= 0:
            break
        tokens = _message_text_tokens(item)
        if tokens <= remaining:
            kept.append(item)
            remaining -= tokens
            continue
        truncated = _truncate_message_to_budget(item, remaining)
        if truncated is not None:
            kept.append(truncated)
        remaining = 0
    return [*reversed(kept), compaction_item]


async def call_remote_compaction_v2(
    *,
    base_url: str,
    api_key: str,
    headers: dict[str, str] | None = None,
    model: str,
    input_items: list[JSONValue],
    instructions: str,
    tools: list[JSONValue],
    session_id: str | None = None,
    timeout_seconds: float = DEFAULT_OPENAI_COMPATIBLE_TIMEOUT_SECONDS,
    stream_idle_timeout_seconds: float = DEFAULT_OPENAI_COMPATIBLE_STREAM_IDLE_TIMEOUT_SECONDS,
    transport: httpx.AsyncBaseTransport | None = None,
) -> RemoteCompactionResult:
    """POST one Responses compaction v2 request and return the replacement history.

    ``transport`` is a test seam for deterministic offline HTTP round trips.
    Errors raise :class:`RemoteCompactionError`; callers fall back to the
    portable text summary.
    """
    endpoint = remote_compaction_endpoint(base_url=base_url, model=model)
    payload = build_remote_compaction_payload(
        model=model,
        input_items=input_items,
        instructions=instructions,
        tools=tools,
        session_id=session_id,
    )
    # HTTP field names are case-insensitive, but a plain dict is not. Normalize
    # first so caller-provided ``content-type`` and these defaults cannot become
    # duplicate wire headers. The Codex backend rejects duplicate content types.
    request_headers = {name.lower(): value for name, value in (headers or {}).items()}
    request_headers["authorization"] = f"Bearer {api_key}"
    request_headers.setdefault("content-type", "application/json")
    request_headers.setdefault("accept", "text/event-stream")
    client_kwargs: dict[str, Any] = {
        "timeout": streaming_timeout(
            timeout_seconds=timeout_seconds,
            stream_idle_timeout_seconds=stream_idle_timeout_seconds,
        ),
    }
    if transport is not None:
        client_kwargs["transport"] = transport
    async with create_async_client(**client_kwargs) as client:
        response = await client.post(endpoint, json=payload, headers=request_headers)
        if response.status_code >= 400:
            raise RemoteCompactionError(
                f"OpenAI remote compaction failed ({response.status_code}): "
                f"{_http_error_message(response)}"
            )
        text = response.text
    compaction_item, usage = parse_compaction_sse(text)
    output = build_replacement_history(input_items, compaction_item)
    return RemoteCompactionResult(output=output, usage=usage)
