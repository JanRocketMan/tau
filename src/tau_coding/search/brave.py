"""Brave Web Search provider for Tau's provider-agnostic search tool.

The `BraveSearchProvider` implements the `SearchProvider` interface on top of
the Brave Web Search API. It is the migrated-to alternative to the default
Parallel provider and is selected with ``TAU_SEARCH_PROVIDER=brave`` or used
through the backward-compatible `BraveSearchConfig` / `run_brave_search`
helpers.

Configuration is read from the process environment:

    BRAVE_SEARCH_API_KEY          subscription key; required to enable the tool
    BRAVE_SEARCH_API_URL          endpoint override, mainly for tests
    BRAVE_SEARCH_TIMEOUT_SECONDS  request timeout in seconds (default 20)
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from tau_agent.tools import AgentToolResult
from tau_agent.types import JSONValue
from tau_coding.search.base import (
    DEFAULT_TIMEOUT_SECONDS,
    ParsedSearch,
    PreparedRequest,
    SearchProvider,
    _safe_error_body,
    common_argument_properties,
    common_query_params,
    normalize_result,
    run_search,
)

BRAVE_SEARCH_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
_SAFESEARCH_VALUES = frozenset({"off", "moderate", "strict"})


@dataclass(frozen=True, slots=True)
class BraveSearchConfig:
    """Immutable Brave Search configuration resolved at session setup.

    `from_env()` returns ``None`` when `BRAVE_SEARCH_API_KEY` is unset or
    blank, which keeps the provider disabled. A malformed
    `BRAVE_SEARCH_TIMEOUT_SECONDS` raises `ValueError` so misconfiguration
    fails loudly at startup instead of surfacing mid-session.
    """

    api_key: str
    endpoint: str = BRAVE_SEARCH_ENDPOINT
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> BraveSearchConfig | None:
        """Build a config from the process environment, or return ``None``.

        Args:
            environ: Environment mapping to read; defaults to `os.environ`.

        Returns:
            A populated config, or ``None`` when no API key is configured.

        Raises:
            ValueError: If `BRAVE_SEARCH_TIMEOUT_SECONDS` is set but is not a
                positive number.
        """
        env = os.environ if environ is None else environ
        api_key = env.get("BRAVE_SEARCH_API_KEY", "").strip()
        if not api_key:
            return None

        endpoint = env.get("BRAVE_SEARCH_API_URL", "").strip() or BRAVE_SEARCH_ENDPOINT
        timeout_seconds = DEFAULT_TIMEOUT_SECONDS
        raw_timeout = env.get("BRAVE_SEARCH_TIMEOUT_SECONDS", "").strip()
        if raw_timeout:
            timeout_seconds = _parse_timeout(raw_timeout, "BRAVE_SEARCH_TIMEOUT_SECONDS")

        return cls(api_key=api_key, endpoint=endpoint, timeout_seconds=timeout_seconds)


def _parse_timeout(raw: str, env_name: str) -> float:
    try:
        timeout_seconds = float(raw)
    except ValueError as exc:
        raise ValueError(f"{env_name} must be a number") from exc
    if timeout_seconds <= 0:
        raise ValueError(f"{env_name} must be positive")
    return timeout_seconds


class BraveSearchProvider(SearchProvider):
    """Brave Web Search backend used by the provider-agnostic `search` tool."""

    name = "brave"
    display_name = "Brave Search"
    short_name = "Brave"

    def __init__(self, config: BraveSearchConfig) -> None:
        self._config = config
        self.timeout_seconds = config.timeout_seconds

    def describe_arguments(self) -> Mapping[str, JSONValue]:
        return common_argument_properties()

    def prepare(self, arguments: Mapping[str, JSONValue]) -> PreparedRequest:
        query, count, country, freshness = common_query_params(arguments)

        params: dict[str, str | int | bool] = {
            "q": query,
            "count": count,
            "safesearch": "moderate",
            "spellcheck": True,
            "extra_snippets": True,
            # Restrict the response to the result family this tool understands.
            "result_filter": "web",
            # Avoid Brave's snippet decoration markers in model-visible output.
            "text_decorations": False,
        }
        if country is not None:
            params["country"] = country
        if freshness is not None:
            params["freshness"] = freshness

        return PreparedRequest(
            query=query,
            method="GET",
            url=self._config.endpoint,
            query_params=params,
            headers={
                "X-Subscription-Token": self._config.api_key,
                "User-Agent": "tau-brave-search/1.0",
            },
        )

    def parse(self, request: PreparedRequest, payload: Mapping[str, Any]) -> ParsedSearch:
        web = payload.get("web")
        raw_results: list[Any] = []
        if isinstance(web, dict):
            candidate_results = web.get("results")
            if isinstance(candidate_results, list):
                raw_results = candidate_results
        results = [normalize_result(item) for item in raw_results if isinstance(item, dict)]

        note: str | None = None
        metadata: dict[str, JSONValue] = {}
        query_metadata = payload.get("query")
        if isinstance(query_metadata, dict):
            candidate = query_metadata.get("altered")
            if isinstance(candidate, str) and candidate and candidate != request.query:
                note = f"{self.short_name} used the corrected query: {candidate}"
                metadata["altered_query"] = candidate

        return ParsedSearch(
            query=request.query,
            results=tuple(results),
            note=note,
            metadata=metadata,
        )

    def http_error_message(self, response: httpx.Response) -> str:
        if response.status_code == 401:
            message = (
                "Brave Search rejected the API key. Check BRAVE_SEARCH_API_KEY "
                "and the key's subscription."
            )
        elif response.status_code == 403:
            message = (
                "Brave Search refused this request. The API key may not have "
                "access to the Web Search product."
            )
        elif response.status_code == 422:
            message = "Brave Search rejected one or more search parameters."
        elif response.status_code == 429:
            message = (
                "Brave Search rate-limited the request. Wait before trying again "
                "or check the subscription quota."
            )
        else:
            message = f"Brave Search returned HTTP {response.status_code}."
        body = _safe_error_body(response, self._config.api_key)
        if body:
            message += f"\nProvider response: {body}"
        return message


async def run_brave_search(
    arguments: Mapping[str, JSONValue],
    *,
    config: BraveSearchConfig,
    transport: httpx.AsyncBaseTransport | None = None,
) -> AgentToolResult:
    """Execute one Brave Web Search tool call (backward-compatible helper).

    New code should use `run_search` with a `SearchProvider` for provider
    neutrality. This helper preserves the pre-migration call signature.
    """
    return await run_search(BraveSearchProvider(config), arguments, transport=transport)
