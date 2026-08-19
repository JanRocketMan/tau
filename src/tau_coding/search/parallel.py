"""Parallel Search API provider for Tau's provider-agnostic search tool.

The `ParallelSearchProvider` implements the `SearchProvider` interface on top
of Parallel's web search endpoint (`POST https://api.parallel.ai/v1/search`).
It is Tau's default web-search provider and ships with `fast` as the default
mode: per Parallel's documentation, Fast mode provides high quality search
within a one-second latency budget. See the API reference:

    https://docs.parallel.ai/api-reference/search/search

Configuration is read from the process environment:

    PARALLEL_SEARCH_API_KEY           API key; required to enable the provider
    PARALLEL_SEARCH_API_URL           endpoint override, mainly for tests
    PARALLEL_SEARCH_TIMEOUT_SECONDS   request timeout in seconds (default 20)
    PARALLEL_SEARCH_MODE              search mode (default "fast")

For convenience `PARALLEL_API_KEY` (the name used by Parallel's own docs and
SDKs) is accepted as a fallback when `PARALLEL_SEARCH_API_KEY` is unset.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, cast

import httpx

from tau_agent.types import JSONValue
from tau_coding.search.base import (
    DEFAULT_TIMEOUT_SECONDS,
    ParsedSearch,
    PreparedRequest,
    SearchProvider,
    _safe_error_body,
    common_argument_properties,
    common_query_params,
    split_freshness_range,
)

PARALLEL_SEARCH_ENDPOINT = "https://api.parallel.ai/v1/search"
PARALLEL_MODES = ("turbo", "fast", "basic", "advanced")
DEFAULT_PARALLEL_MODE = "fast"


@dataclass(frozen=True, slots=True)
class ParallelSearchConfig:
    """Immutable Parallel Search configuration resolved at session setup.

    `from_env()` returns ``None`` when no Parallel API key is configured, which
    keeps the provider disabled. `mode` selects the search preset and defaults
    to `fast`. A malformed `PARALLEL_SEARCH_TIMEOUT_SECONDS` or an unknown
    `PARALLEL_SEARCH_MODE` raises `ValueError` so misconfiguration fails loudly
    at startup instead of surfacing mid-session.
    """

    api_key: str
    mode: str = DEFAULT_PARALLEL_MODE
    endpoint: str = PARALLEL_SEARCH_ENDPOINT
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_chars_total: int | None = None
    max_chars_per_result: int | None = None
    extra: dict[str, JSONValue] = field(default_factory=dict)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> ParallelSearchConfig | None:
        """Build a config from the process environment, or return ``None``.

        Args:
            environ: Environment mapping to read; defaults to `os.environ`.

        Returns:
            A populated config, or ``None`` when no API key is configured.

        Raises:
            ValueError: If `PARALLEL_SEARCH_TIMEOUT_SECONDS` is malformed or
                `PARALLEL_SEARCH_MODE` is not a supported mode.
        """
        env = os.environ if environ is None else environ
        api_key = (
            env.get("PARALLEL_SEARCH_API_KEY", "") or env.get("PARALLEL_API_KEY", "")
        ).strip()
        if not api_key:
            return None

        endpoint = env.get("PARALLEL_SEARCH_API_URL", "").strip() or PARALLEL_SEARCH_ENDPOINT

        timeout_seconds = DEFAULT_TIMEOUT_SECONDS
        raw_timeout = env.get("PARALLEL_SEARCH_TIMEOUT_SECONDS", "").strip()
        if raw_timeout:
            try:
                timeout_seconds = float(raw_timeout)
            except ValueError as exc:
                raise ValueError("PARALLEL_SEARCH_TIMEOUT_SECONDS must be a number") from exc
            if timeout_seconds <= 0:
                raise ValueError("PARALLEL_SEARCH_TIMEOUT_SECONDS must be positive")

        mode = env.get("PARALLEL_SEARCH_MODE", "").strip().lower() or DEFAULT_PARALLEL_MODE
        if mode not in PARALLEL_MODES:
            names = ", ".join(PARALLEL_MODES)
            raise ValueError(f"PARALLEL_SEARCH_MODE must be one of: {names}")

        return cls(
            api_key=api_key,
            mode=mode,
            endpoint=endpoint,
            timeout_seconds=timeout_seconds,
        )


class ParallelSearchProvider(SearchProvider):
    """Parallel Search backend used by the provider-agnostic `search` tool."""

    name = "parallel"
    display_name = "Parallel Search"
    short_name = "Parallel"

    def __init__(self, config: ParallelSearchConfig) -> None:
        self._config = config
        self.timeout_seconds = config.timeout_seconds

    def describe_arguments(self) -> Mapping[str, JSONValue]:
        return common_argument_properties()

    def prepare(self, arguments: Mapping[str, JSONValue]) -> PreparedRequest:
        query, count, country, freshness = common_query_params(arguments)
        after_date, before_date = split_freshness_range(freshness)

        advanced_settings: dict[str, JSONValue] = {"max_results": count}
        if country is not None:
            advanced_settings["location"] = country.lower()
        source_policy: dict[str, JSONValue] = {}
        if after_date is not None:
            source_policy["after_date"] = after_date
        if before_date is not None:
            source_policy["before_date"] = before_date
        if source_policy:
            advanced_settings["source_policy"] = source_policy
        if self._config.max_chars_per_result is not None:
            advanced_settings["excerpt_settings"] = {
                "max_chars_per_result": self._config.max_chars_per_result
            }

        json_body: dict[str, JSONValue] = {
            "objective": query,
            "search_queries": [query],
            "mode": self._config.mode,
            "advanced_settings": advanced_settings,
        }
        if self._config.max_chars_total is not None:
            json_body["max_chars_total"] = self._config.max_chars_total
        return PreparedRequest(
            query=query,
            method="POST",
            url=self._config.endpoint,
            json_body=json_body,
            headers={
                "Content-Type": "application/json",
                "x-api-key": self._config.api_key,
                "User-Agent": "tau-parallel-search/1.0",
            },
        )

    def parse(self, request: PreparedRequest, payload: Mapping[str, Any]) -> ParsedSearch:
        results: list[dict[str, JSONValue]] = []
        raw_results = payload.get("results")
        if isinstance(raw_results, list):
            for item in raw_results:
                if not isinstance(item, dict):
                    continue
                results.append(_normalize_parallel_result(item))

        metadata: dict[str, JSONValue] = {}
        for key in ("search_id", "session_id"):
            value = payload.get(key)
            if isinstance(value, str):
                metadata[key] = value

        note: str | None = None
        warnings = payload.get("warnings")
        if isinstance(warnings, list):
            messages = [
                warning.get("message")
                for warning in warnings
                if isinstance(warning, dict)
                and isinstance(warning.get("message"), str)
                and warning["message"]
            ]
            if messages:
                note = f"{self.short_name} returned a warning: {messages[0]}"
                metadata["warnings"] = messages

        usage = payload.get("usage")
        if isinstance(usage, list):
            usage_items: list[dict[str, JSONValue]] = []
            for item in usage:
                if not isinstance(item, dict):
                    continue
                name = item.get("name")
                count = item.get("count")
                if isinstance(name, str) and isinstance(count, int) and not isinstance(count, bool):
                    usage_items.append({"name": name, "count": count})
            if usage_items:
                metadata["usage"] = cast(JSONValue, usage_items)

        return ParsedSearch(
            query=request.query,
            results=tuple(results),
            note=note,
            metadata=metadata,
        )

    def http_error_message(self, response: httpx.Response) -> str:
        if response.status_code == 401:
            message = (
                "Parallel Search rejected the API key. Check PARALLEL_SEARCH_API_KEY "
                "and the key on https://platform.parallel.ai."
            )
        elif response.status_code == 403:
            message = (
                "Parallel Search refused this request. The API key may not have "
                "access to the Search API."
            )
        elif response.status_code == 422:
            message = "Parallel Search rejected one or more search parameters."
        elif response.status_code == 429:
            message = (
                "Parallel Search rate-limited the request. Wait before trying again "
                "or check the account quota."
            )
        else:
            message = f"Parallel Search returned HTTP {response.status_code}."
        body = _safe_error_body(response, self._config.api_key)
        if body:
            message += f"\nProvider response: {body}"
        return message


def _normalize_parallel_result(raw: Mapping[str, Any]) -> dict[str, JSONValue]:
    """Map one `V1WebSearchResult` into the shared normalized shape."""
    title = raw.get("title")
    url = raw.get("url")
    excerpts = raw.get("excerpts")

    extra_snippets: list[JSONValue] = []
    if isinstance(excerpts, list):
        extra_snippets = [excerpt for excerpt in excerpts if isinstance(excerpt, str)]

    result: dict[str, JSONValue] = {
        "title": title if isinstance(title, str) else "",
        "url": url if isinstance(url, str) else "",
        "description": next((e for e in extra_snippets if isinstance(e, str) and e), ""),
        "extra_snippets": extra_snippets,
    }
    publish_date = raw.get("publish_date")
    if isinstance(publish_date, str):
        result["publish_date"] = publish_date
    return result
