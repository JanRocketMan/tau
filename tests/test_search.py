"""Deterministic tests for the provider-agnostic search core and Parallel API.

All HTTP traffic runs through `httpx.MockTransport`; no test performs network
access or consumes Parallel quota. Coverage spans provider selection
(`SearchConfig.from_env`), the Parallel provider request/response mapping, the
shared executor, and the `search_providers` catalog entries.
"""

from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from tau_agent.tools import AgentTool
from tau_coding import create_coding_tools, create_search_tool
from tau_coding.catalog_loader import (
    CatalogError,
    builtin_catalog_resource_text,
    builtin_search_catalog,
    default_search_provider,
    effective_search_catalog,
)
from tau_coding.paths import TauPaths
from tau_coding.search import (
    PARALLEL_SEARCH_ENDPOINT,
    BraveSearchProvider,
    ParallelSearchConfig,
    ParallelSearchProvider,
    SearchConfig,
    run_search,
    search_provider_names,
)
from tau_coding.search.base import PreparedRequest

TEST_API_KEY = "test-secret"

Handler = Callable[[httpx.Request], httpx.Response]

_PARALLEL_ENV = {
    "PARALLEL_SEARCH_API_KEY": TEST_API_KEY,
    "PARALLEL_SEARCH_TIMEOUT_SECONDS": "5",
    "PARALLEL_SEARCH_MODE": "fast",
}


def _parallel_config() -> ParallelSearchConfig:
    return ParallelSearchConfig(api_key=TEST_API_KEY, timeout_seconds=5.0)


def _parallel_env() -> dict[str, str]:
    return dict(_PARALLEL_ENV)


def _tool_for(handler: Handler, requests: list[httpx.Request]) -> AgentTool:
    """Build a Parallel `search` tool backed by a recording mock transport."""

    def record(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    config = SearchConfig(provider=ParallelSearchProvider(_parallel_config()))
    return create_search_tool(config, transport=httpx.MockTransport(record))


def _payload(
    results: list[dict[str, object]],
    *,
    warnings: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "search_id": "search_abc123",
        "session_id": "session_xyz",
        "results": results,
    }
    if warnings is not None:
        payload["warnings"] = warnings
    return payload


def _ok(request: httpx.Request, results: list[dict[str, object]]) -> httpx.Response:
    return httpx.Response(200, request=request, json=_payload(results))


def _mock_default_provider(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    monkeypatch.setattr("tau_coding.search.config._catalog_default_provider", lambda: name)


def test_search_provider_names() -> None:
    assert search_provider_names() == ("parallel", "brave")


# ---------------------------------------------------------------------------
# Provider selection (SearchConfig.from_env)
# ---------------------------------------------------------------------------


def test_from_env_returns_none_without_any_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_default_provider(monkeypatch, "parallel")
    assert SearchConfig.from_env({}) is None


def test_from_env_selects_parallel_default(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_default_provider(monkeypatch, "parallel")
    config = SearchConfig.from_env(_parallel_env())

    assert config is not None
    assert config.provider_name == "parallel"
    assert config.provider.display_name == "Parallel Search"


def test_from_env_explicit_brave_selection() -> None:
    config = SearchConfig.from_env(
        {
            "TAU_SEARCH_PROVIDER": "brave",
            "BRAVE_SEARCH_API_KEY": "key-123",
        }
    )

    assert config is not None
    assert config.provider_name == "brave"
    assert isinstance(config.provider, BraveSearchProvider)


def test_from_env_brave_selection_requires_key() -> None:
    assert SearchConfig.from_env({"TAU_SEARCH_PROVIDER": "brave"}) is None


def test_from_env_explicit_parallel_does_not_fall_back_to_brave() -> None:
    config = SearchConfig.from_env(
        {
            "TAU_SEARCH_PROVIDER": "parallel",
            "BRAVE_SEARCH_API_KEY": "key-123",
        }
    )

    assert config is None


def test_from_env_migration_fallback_uses_brave_when_parallel_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_default_provider(monkeypatch, "parallel")
    config = SearchConfig.from_env({"BRAVE_SEARCH_API_KEY": "key-123"})

    assert config is not None
    assert config.provider_name == "brave"


def test_from_env_rejects_unknown_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_default_provider(monkeypatch, "parallel")
    with pytest.raises(ValueError, match="TAU_SEARCH_PROVIDER"):
        SearchConfig.from_env({"TAU_SEARCH_PROVIDER": "exafunk"})


def test_from_env_reads_parallel_options() -> None:
    config = SearchConfig.from_env(_parallel_env())

    assert config is not None
    assert config.provider.timeout_seconds == 5.0
    assert config.provider._config.mode == "fast"


def test_from_env_accepts_parallel_api_key_fallback() -> None:
    config = SearchConfig.from_env({"PARALLEL_API_KEY": "fallback-key"})

    assert config is not None
    assert config.provider_name == "parallel"


def test_from_env_rejects_invalid_parallel_timeout() -> None:
    env = {**_parallel_env(), "PARALLEL_SEARCH_TIMEOUT_SECONDS": "soon"}
    with pytest.raises(ValueError, match="must be a number"):
        SearchConfig.from_env(env)


def test_from_env_rejects_unknown_parallel_mode() -> None:
    env = {**_parallel_env(), "PARALLEL_SEARCH_MODE": "ludicrous"}
    with pytest.raises(ValueError, match="PARALLEL_SEARCH_MODE"):
        SearchConfig.from_env(env)


def test_parallel_config_defaults_to_fast_mode() -> None:
    config = ParallelSearchConfig(api_key=TEST_API_KEY)
    assert config.mode == "fast"
    assert config.endpoint == PARALLEL_SEARCH_ENDPOINT


# ---------------------------------------------------------------------------
# Parallel provider request building
# ---------------------------------------------------------------------------


def test_parallel_describe_arguments_has_neutral_schema() -> None:
    properties = ParallelSearchProvider(_parallel_config()).describe_arguments()

    assert set(properties) == {"query", "count", "country", "freshness"}
    assert properties["query"]["minLength"] == 1
    assert properties["count"]["default"] == 10
    assert properties["count"]["maximum"] == 20


def test_parallel_prepare_builds_fast_post_request() -> None:
    provider = ParallelSearchProvider(_parallel_config())
    request = provider.prepare({"query": "tau coding agent", "count": 5})

    assert isinstance(request, PreparedRequest)
    assert request.method == "POST"
    assert request.url == PARALLEL_SEARCH_ENDPOINT
    assert request.headers["x-api-key"] == TEST_API_KEY
    assert request.headers["Content-Type"] == "application/json"

    body = request.json_body
    assert body is not None
    assert body["objective"] == "tau coding agent"
    assert body["search_queries"] == ["tau coding agent"]
    assert body["mode"] == "fast"
    advanced = body["advanced_settings"]
    assert isinstance(advanced, dict)
    assert advanced["max_results"] == 5


def test_parallel_prepare_maps_country_and_freshness() -> None:
    provider = ParallelSearchProvider(_parallel_config())
    request = provider.prepare(
        {
            "query": "python releases",
            "country": "DE",
            "freshness": "2025-01-01to2025-01-31",
        }
    )

    body = request.json_body
    assert body is not None
    advanced = body["advanced_settings"]
    assert isinstance(advanced, dict)
    assert advanced["location"] == "de"
    source_policy = advanced["source_policy"]
    assert isinstance(source_policy, dict)
    assert source_policy["after_date"] == "2025-01-01"
    assert source_policy["before_date"] == "2025-01-31"


def test_parallel_prepare_ignores_freshness_shorthand() -> None:
    provider = ParallelSearchProvider(_parallel_config())
    request = provider.prepare({"query": "python releases", "freshness": "pw"})

    body = request.json_body
    assert body is not None
    advanced = body["advanced_settings"]
    assert isinstance(advanced, dict)
    assert "source_policy" not in advanced


def test_parallel_prepare_rejects_invalid_arguments() -> None:
    provider = ParallelSearchProvider(_parallel_config())
    for arguments, match in [
        ({"query": ""}, "query"),
        ({"query": "x", "count": 0}, "count"),
        ({"query": "x", "count": 21}, "count"),
        ({"query": "x", "country": "usa"}, "two-letter"),
        ({"query": "x", "freshness": "last-week"}, "freshness"),
    ]:
        with pytest.raises(ValueError, match=match):
            provider.prepare(arguments)


# ---------------------------------------------------------------------------
# Parallel provider parsing
# ---------------------------------------------------------------------------


def test_parallel_parse_normalizes_results() -> None:
    provider = ParallelSearchProvider(_parallel_config())
    request = provider.prepare({"query": "tau"})
    parsed = provider.parse(
        request,
        {
            "search_id": "search_1",
            "session_id": "session_2",
            "results": [
                {
                    "url": "https://example.test/tau",
                    "title": "Tau",
                    "publish_date": "2026-01-15",
                    "excerpts": ["First excerpt.", "Second excerpt."],
                },
                {"url": "https://example.test/x", "excerpts": []},
            ],
        },
    )

    first = parsed.results[0]
    assert first["title"] == "Tau"
    assert first["url"] == "https://example.test/tau"
    assert first["description"] == "First excerpt."
    assert first["extra_snippets"] == ["First excerpt.", "Second excerpt."]
    assert first["publish_date"] == "2026-01-15"
    assert parsed.metadata["search_id"] == "search_1"
    assert parsed.metadata["session_id"] == "session_2"


def test_parallel_parse_reports_warnings() -> None:
    provider = ParallelSearchProvider(_parallel_config())
    request = provider.prepare({"query": "tau"})
    parsed = provider.parse(
        request,
        _payload(
            [],
            warnings=[{"type": "warning", "message": "Some inputs were ignored"}],
        ),
    )

    assert parsed.note == "Parallel returned a warning: Some inputs were ignored"
    assert parsed.metadata["warnings"] == ["Some inputs were ignored"]


# ---------------------------------------------------------------------------
# Full tool flow through the shared executor
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_parallel_success_formats_results_and_detail() -> None:
    requests: list[httpx.Request] = []
    tool = _tool_for(
        lambda request: _ok(
            request,
            [
                {
                    "url": "https://example.test/tau",
                    "title": "Tau",
                    "publish_date": "2026-01-15",
                    "excerpts": ["A coding-agent project."],
                }
            ],
        ),
        requests,
    )

    result = await tool.execute("call-1", {"query": "tau coding agent", "count": 5})

    assert len(requests) == 1
    request = requests[0]
    assert request.headers["x-api-key"] == TEST_API_KEY

    assert "Parallel Search results for: tau coding agent" in result.text
    assert "1. Tau" in result.text
    assert "URL: https://example.test/tau" in result.text
    assert "Published: 2026-01-15" in result.text
    assert "Snippet: A coding-agent project." in result.text

    details = result.details
    assert isinstance(details, dict)
    assert details["provider"] == "parallel"
    assert details["query"] == "tau coding agent"
    assert details["count"] == 1
    assert TEST_API_KEY not in str(details)
    results = details["results"]
    assert isinstance(results, list)
    assert results[0]["url"] == "https://example.test/tau"


@pytest.mark.anyio
async def test_parallel_empty_results_message() -> None:
    requests: list[httpx.Request] = []
    tool = _tool_for(lambda request: _ok(request, []), requests)

    result = await tool.execute("call-1", {"query": "nothing here"})

    assert result.text == "No Parallel Search web results found for: nothing here"
    assert result.details["count"] == 0


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
async def test_parallel_http_errors(status_code: int, expected: str) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, request=request, json={"error": "boom"})

    tool = _tool_for(handler, requests)
    result = await tool.execute("call-1", {"query": "tau"})

    assert expected in result.text
    assert result.details["status_code"] == status_code


@pytest.mark.anyio
async def test_parallel_timeout_returns_bounded_error() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    tool = _tool_for(handler, requests)
    result = await tool.execute("call-1", {"query": "tau"})

    assert result.text == "Parallel Search timed out before returning results."
    assert result.details["error"] == "timeout"


@pytest.mark.anyio
async def test_parallel_invalid_json_returns_error() -> None:
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

    assert result.text == "Parallel Search returned an invalid JSON response."
    assert result.details["error"] == "invalid_json"


@pytest.mark.anyio
async def test_parallel_api_key_redacted_in_errors() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, request=request, json={"detail": f"bad {TEST_API_KEY}"})

    tool = _tool_for(handler, requests)
    result = await tool.execute("call-1", {"query": "tau"})

    assert TEST_API_KEY not in result.text
    assert "[redacted]" in result.text


@pytest.mark.anyio
async def test_run_search_is_provider_agnostic() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _ok(request, [])

    provider = ParallelSearchProvider(_parallel_config())
    result = await run_search(provider, {"query": "tau"}, transport=httpx.MockTransport(handler))

    assert len(requests) == 1
    assert requests[0].url == PARALLEL_SEARCH_ENDPOINT
    assert "No Parallel Search web results" in result.text


def test_create_search_tool_uses_provider_agnostic_name() -> None:
    config = SearchConfig(provider=ParallelSearchProvider(_parallel_config()))
    tool = create_search_tool(config)

    assert tool.name == "search"
    assert tool.label == "Parallel Search"
    assert tool.parameters["required"] == ["query"]


def test_create_coding_tools_appends_search_named_search(tmp_path: Path) -> None:
    config = SearchConfig(provider=ParallelSearchProvider(_parallel_config()))
    tools = create_coding_tools(cwd=tmp_path, search=config)

    assert [tool.name for tool in tools] == ["read", "write", "edit", "bash", "search"]


# ---------------------------------------------------------------------------
# Search provider catalog
# ---------------------------------------------------------------------------


def test_builtin_search_catalog_has_parallel_and_brave() -> None:
    entries = {entry.name: entry for entry in builtin_search_catalog()}

    assert set(entries) == {"parallel", "brave"}
    parallel = entries["parallel"]
    assert parallel.display_name == "Parallel Search"
    assert parallel.api_key_env == "PARALLEL_SEARCH_API_KEY"
    assert parallel.endpoint == PARALLEL_SEARCH_ENDPOINT
    assert parallel.default_mode == "fast"
    assert parallel.modes == ("turbo", "fast", "basic", "advanced")

    brave = entries["brave"]
    assert brave.api_key_env == "BRAVE_SEARCH_API_KEY"
    assert brave.modes == ()


def test_default_search_provider_from_builtin_catalog() -> None:
    assert default_search_provider() == "parallel"


def test_effective_search_catalog_reads_single_catalog_file(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.toml"
    catalog.parent.mkdir(parents=True, exist_ok=True)
    catalog.write_text(
        builtin_catalog_resource_text().replace(
            'default_search_provider = "parallel"', 'default_search_provider = "brave"'
        ),
        encoding="utf-8",
    )
    paths = TauPaths(home=tmp_path / ".tau", catalog_path=catalog)

    entries = {entry.name: entry for entry in effective_search_catalog(paths)}

    assert default_search_provider(paths) == "brave"
    assert entries["brave"].display_name == "Brave Search"
    assert "parallel" in entries  # packaged entries remain


def test_catalog_rejects_unknown_default_search_provider(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.toml"
    catalog.parent.mkdir(parents=True, exist_ok=True)
    catalog.write_text(
        builtin_catalog_resource_text().replace(
            'default_search_provider = "parallel"', 'default_search_provider = "missing"'
        ),
        encoding="utf-8",
    )
    paths = TauPaths(home=tmp_path / ".tau", catalog_path=catalog)

    with pytest.raises(CatalogError, match="default_search_provider"):
        effective_search_catalog(paths)


def test_brave_search_config_compat_import() -> None:
    from tau_coding.brave_search import BraveSearchConfig as ShimConfig

    config = ShimConfig(api_key="k")
    assert config.endpoint == "https://api.search.brave.com/res/v1/web/search"
