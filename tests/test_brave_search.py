"""Deterministic tests for the Brave Search tool.

All HTTP traffic runs through `httpx.MockTransport`; no test performs network
access or consumes Brave quota.
"""

from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from tau_agent.tools import AgentTool
from tau_agent.types import JSONValue
from tau_coding import BraveSearchConfig, create_brave_search_tool, create_coding_tools
from tau_coding.brave_search import BRAVE_SEARCH_ENDPOINT, run_brave_search

TEST_API_KEY = "test-secret"

Handler = Callable[[httpx.Request], httpx.Response]


def _config() -> BraveSearchConfig:
    return BraveSearchConfig(api_key=TEST_API_KEY, timeout_seconds=5.0)


def _tool_for(handler: Handler, requests: list[httpx.Request]) -> AgentTool:
    """Build a `brave_search` tool backed by a recording mock transport."""

    def record(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    return create_brave_search_tool(_config(), transport=httpx.MockTransport(record))


def _payload(results: list[dict[str, object]], *, altered: str | None = None) -> dict[str, object]:
    query: dict[str, object] = {"original": "tau coding agent"}
    if altered is not None:
        query["altered"] = altered
    return {"type": "search", "query": query, "web": {"results": results}}


def _ok(request: httpx.Request, results: list[dict[str, object]]) -> httpx.Response:
    return httpx.Response(200, request=request, json=_payload(results))


def test_from_env_returns_none_without_api_key() -> None:
    assert BraveSearchConfig.from_env({}) is None
    assert BraveSearchConfig.from_env({"BRAVE_SEARCH_API_KEY": "   "}) is None


def test_from_env_reads_key_endpoint_and_timeout() -> None:
    config = BraveSearchConfig.from_env(
        {
            "BRAVE_SEARCH_API_KEY": "  key-123  ",
            "BRAVE_SEARCH_API_URL": "http://localhost:8080/search",
            "BRAVE_SEARCH_TIMEOUT_SECONDS": "7.5",
        }
    )

    assert config is not None
    assert config.api_key == "key-123"
    assert config.endpoint == "http://localhost:8080/search"
    assert config.timeout_seconds == 7.5


def test_from_env_uses_defaults() -> None:
    config = BraveSearchConfig.from_env({"BRAVE_SEARCH_API_KEY": "key-123"})

    assert config is not None
    assert config.endpoint == BRAVE_SEARCH_ENDPOINT
    assert config.timeout_seconds == 20.0


def test_from_env_rejects_invalid_timeout() -> None:
    with pytest.raises(ValueError, match="must be a number"):
        BraveSearchConfig.from_env(
            {"BRAVE_SEARCH_API_KEY": "key-123", "BRAVE_SEARCH_TIMEOUT_SECONDS": "soon"}
        )
    with pytest.raises(ValueError, match="must be positive"):
        BraveSearchConfig.from_env(
            {"BRAVE_SEARCH_API_KEY": "key-123", "BRAVE_SEARCH_TIMEOUT_SECONDS": "0"}
        )


def test_create_coding_tools_omits_brave_search_by_default(tmp_path: Path) -> None:
    tools = create_coding_tools(cwd=tmp_path)

    assert [tool.name for tool in tools] == ["read", "write", "edit", "bash"]


def test_create_coding_tools_appends_brave_search_when_configured(tmp_path: Path) -> None:
    tools = create_coding_tools(cwd=tmp_path, brave_search=_config())

    assert [tool.name for tool in tools] == ["read", "write", "edit", "bash", "brave_search"]


def test_tool_schema_has_no_credential_arguments() -> None:
    tool = create_brave_search_tool(_config())

    assert tool.name == "brave_search"
    assert tool.parameters["required"] == ["query"]
    properties = tool.parameters["properties"]
    assert isinstance(properties, dict)
    for name in properties:
        assert "key" not in name.lower()
        assert "token" not in name.lower()


@pytest.mark.anyio
async def test_success_sends_auth_header_and_formats_results() -> None:
    requests: list[httpx.Request] = []
    tool = _tool_for(
        lambda request: _ok(
            request,
            [
                {
                    "title": "Tau",
                    "url": "https://example.test/tau",
                    "description": "A coding-agent project.",
                    "age": "2 days ago",
                    "extra_snippets": ["A minimal terminal coding agent."],
                }
            ],
        ),
        requests,
    )

    result = await tool.execute("call-1", {"query": "tau coding agent", "count": 5})

    assert len(requests) == 1
    request = requests[0]
    assert request.headers["X-Subscription-Token"] == TEST_API_KEY
    assert request.headers["Accept"] == "application/json"
    assert request.url.params["q"] == "tau coding agent"
    assert request.url.params["count"] == "5"
    assert request.url.params["result_filter"] == "web"
    assert request.url.params["text_decorations"] == "false"

    assert "Brave Search results for: tau coding agent" in result.text
    assert "1. Tau" in result.text
    assert "URL: https://example.test/tau" in result.text
    assert "Snippet: A coding-agent project." in result.text
    assert "Additional snippet: A minimal terminal coding agent." in result.text

    details = result.details
    assert isinstance(details, dict)
    assert details["provider"] == "brave"
    assert details["query"] == "tau coding agent"
    assert details["count"] == 1
    results = details["results"]
    assert isinstance(results, list)
    first_result = results[0]
    assert isinstance(first_result, dict)
    assert first_result["url"] == "https://example.test/tau"
    assert TEST_API_KEY not in str(details)


@pytest.mark.anyio
async def test_empty_result_set_returns_clear_message() -> None:
    requests: list[httpx.Request] = []
    tool = _tool_for(lambda request: _ok(request, []), requests)

    result = await tool.execute("call-1", {"query": "nothing matches this"})

    assert result.text == "No Brave Search web results found for: nothing matches this"
    details = result.details
    assert isinstance(details, dict)
    assert details["count"] == 0


@pytest.mark.anyio
async def test_corrected_query_is_reported() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            json=_payload(
                [{"title": "Tau", "url": "https://example.test/tau", "description": "d"}],
                altered="tau agent",
            ),
        )

    tool = _tool_for(handler, requests)
    result = await tool.execute("call-1", {"query": "tau agnet"})

    assert "Brave used the corrected query: tau agent" in result.text
    details = result.details
    assert isinstance(details, dict)
    assert details["altered_query"] == "tau agent"


@pytest.mark.anyio
async def test_optional_arguments_are_forwarded() -> None:
    requests: list[httpx.Request] = []
    tool = _tool_for(lambda request: _ok(request, []), requests)

    await tool.execute(
        "call-1",
        {
            "query": "python releases",
            "country": "de",
            "search_lang": "de",
            "ui_lang": "de-DE",
            "safesearch": "strict",
            "freshness": "2025-01-01to2025-01-31",
            "spellcheck": False,
            "extra_snippets": False,
            "offset": 2,
        },
    )

    params = requests[0].url.params
    assert params["country"] == "DE"
    assert params["search_lang"] == "de"
    assert params["ui_lang"] == "de-DE"
    assert params["safesearch"] == "strict"
    assert params["freshness"] == "2025-01-01to2025-01-31"
    assert params["spellcheck"] == "false"
    assert params["extra_snippets"] == "false"
    assert params["offset"] == "2"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("arguments", "match"),
    [
        ({"query": "x", "count": 0}, "count"),
        ({"query": "x", "count": 21}, "count"),
        ({"query": "x", "count": True}, "count"),
        ({"query": "x", "count": "5"}, "count"),
        ({"query": "x", "offset": 10}, "offset"),
        ({"query": ""}, "query"),
        ({"query": "   "}, "query"),
        ({"query": "x" * 401}, "400 characters"),
        ({"query": " ".join(["word"] * 51)}, "50 words"),
        ({"query": "x", "safesearch": "everything"}, "safesearch"),
        ({"query": "x", "freshness": "last-week"}, "freshness"),
    ],
)
async def test_invalid_arguments_raise_before_network_access(
    arguments: dict[str, JSONValue], match: str
) -> None:
    requests: list[httpx.Request] = []
    tool = _tool_for(lambda request: _ok(request, []), requests)

    with pytest.raises(ValueError, match=match):
        await tool.execute("call-1", arguments)

    assert requests == []


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("status_code", "expected"),
    [
        (401, "rejected the API key"),
        (403, "refused this request"),
        (422, "rejected one or more search parameters"),
        (429, "rate-limited"),
        (500, "HTTP 500"),
    ],
)
async def test_http_errors_return_actionable_messages(status_code: int, expected: str) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, request=request, json={"error": "boom"})

    tool = _tool_for(handler, requests)
    result = await tool.execute("call-1", {"query": "tau"})

    assert expected in result.text
    details = result.details
    assert isinstance(details, dict)
    assert details["error"] == "http_error"
    assert details["status_code"] == status_code


@pytest.mark.anyio
async def test_timeout_returns_bounded_error() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    tool = _tool_for(handler, requests)
    result = await tool.execute("call-1", {"query": "tau"})

    assert result.text == "Brave Search timed out before returning results."
    details = result.details
    assert isinstance(details, dict)
    assert details["error"] == "timeout"


@pytest.mark.anyio
async def test_transport_error_returns_bounded_error() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    tool = _tool_for(handler, requests)
    result = await tool.execute("call-1", {"query": "tau"})

    assert result.text == "Brave Search request failed: ConnectError"
    details = result.details
    assert isinstance(details, dict)
    assert details["error"] == "request_error"


@pytest.mark.anyio
async def test_non_json_response_returns_invalid_json_error() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            content=b"<html>oops</html>",
            headers={"content-type": "text/html"},
        )

    tool = _tool_for(handler, requests)
    result = await tool.execute("call-1", {"query": "tau"})

    assert result.text == "Brave Search returned an invalid JSON response."
    details = result.details
    assert isinstance(details, dict)
    assert details["error"] == "invalid_json"


@pytest.mark.anyio
async def test_unexpected_response_shape_returns_error() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, request=request, json=["not", "an", "object"])

    tool = _tool_for(handler, requests)
    result = await tool.execute("call-1", {"query": "tau"})

    assert result.text == "Brave Search returned an unexpected response shape."
    details = result.details
    assert isinstance(details, dict)
    assert details["error"] == "invalid_response"


@pytest.mark.anyio
async def test_api_key_never_appears_in_output() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        # Even if an endpoint echoes the key in its error body, the tool must
        # redact it before the text reaches the model or session history.
        return httpx.Response(422, request=request, json={"detail": f"bad key {TEST_API_KEY}"})

    tool = _tool_for(handler, requests)
    result = await tool.execute("call-1", {"query": "tau"})

    assert TEST_API_KEY not in result.text
    assert "[redacted]" in result.text
    assert TEST_API_KEY not in str(result.details)


@pytest.mark.anyio
async def test_run_brave_search_delegates_through_executor_helper() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _ok(request, [])

    result = await run_brave_search(
        {"query": "tau"}, config=_config(), transport=httpx.MockTransport(handler)
    )

    assert len(requests) == 1
    assert "No Brave Search web results" in result.text
