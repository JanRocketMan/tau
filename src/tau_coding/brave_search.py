"""Brave Search API support for Tau coding sessions.

The optional `brave_search` tool queries the Brave Web Search endpoint. It is
enabled explicitly through environment-driven process configuration:

    BRAVE_SEARCH_API_KEY          subscription key; required to enable the tool
    BRAVE_SEARCH_API_URL          endpoint override, mainly for tests
    BRAVE_SEARCH_TIMEOUT_SECONDS  request timeout in seconds (default 20)

The API key is a confidential credential. It is read from the process
environment, is never a model-visible tool argument, and never appears in tool
output, session history, or error messages. Search queries are the only data
sent to Brave; treat returned snippets as untrusted external content.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

import httpx

from tau_agent.messages import TextContent
from tau_agent.tools import AgentToolResult
from tau_agent.types import JSONValue

BRAVE_SEARCH_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
DEFAULT_TIMEOUT_SECONDS = 20.0
MAX_ERROR_BODY_CHARS = 1_000
MAX_QUERY_CHARS = 400
MAX_QUERY_WORDS = 50

_FRESHNESS_SHORTHANDS = frozenset({"pd", "pw", "pm", "py"})
_SAFESEARCH_VALUES = frozenset({"off", "moderate", "strict"})


@dataclass(frozen=True, slots=True)
class BraveSearchConfig:
    """Immutable Brave Search configuration resolved at session setup.

    `from_env()` returns ``None`` when `BRAVE_SEARCH_API_KEY` is unset or
    blank, which keeps the `brave_search` tool disabled. A malformed
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
            try:
                timeout_seconds = float(raw_timeout)
            except ValueError as exc:
                raise ValueError("BRAVE_SEARCH_TIMEOUT_SECONDS must be a number") from exc
            if timeout_seconds <= 0:
                raise ValueError("BRAVE_SEARCH_TIMEOUT_SECONDS must be positive")

        return cls(api_key=api_key, endpoint=endpoint, timeout_seconds=timeout_seconds)


def _optional_string(arguments: Mapping[str, JSONValue], name: str) -> str | None:
    """Read and normalize an optional string argument."""
    value = arguments.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"`{name}` must be a string")
    value = value.strip()
    return value or None


def _integer_argument(
    arguments: Mapping[str, JSONValue],
    name: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    """Read and validate an integer argument."""
    value = arguments.get(name, default)
    # bool is a subclass of int, but should not be accepted here.
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"`{name}` must be an integer")
    if value < minimum or value > maximum:
        raise ValueError(f"`{name}` must be between {minimum} and {maximum}, inclusive")
    return value


def _boolean_argument(arguments: Mapping[str, JSONValue], name: str, *, default: bool) -> bool:
    """Read and validate a Boolean argument."""
    value = arguments.get(name, default)
    if not isinstance(value, bool):
        raise ValueError(f"`{name}` must be a boolean")
    return value


def _validate_query(query: str) -> None:
    if not query:
        raise ValueError("`query` must not be empty")
    if len(query) > MAX_QUERY_CHARS:
        raise ValueError(f"`query` must not exceed {MAX_QUERY_CHARS} characters")
    if len(query.split()) > MAX_QUERY_WORDS:
        raise ValueError(f"`query` must not exceed {MAX_QUERY_WORDS} words")


def _validate_freshness(freshness: str | None) -> None:
    """Perform conservative local validation.

    Brave also validates custom ``YYYY-MM-DDtoYYYY-MM-DD`` ranges server-side.
    """
    if freshness is None:
        return
    if freshness in _FRESHNESS_SHORTHANDS:
        return
    if "to" in freshness:
        start, separator, end = freshness.partition("to")
        if separator and len(start) == 10 and len(end) == 10:
            return
    raise ValueError("`freshness` must be pd, pw, pm, py, or YYYY-MM-DDtoYYYY-MM-DD")


def build_search_params(arguments: Mapping[str, JSONValue]) -> dict[str, str | int | bool]:
    """Validate tool arguments and build Brave query parameters.

    Raises:
        ValueError: If any argument fails local validation. No network request
            is made in that case.
    """
    query = _optional_string(arguments, "query") or ""
    _validate_query(query)

    count = _integer_argument(arguments, "count", default=10, minimum=1, maximum=20)
    offset = _integer_argument(arguments, "offset", default=0, minimum=0, maximum=9)

    country = _optional_string(arguments, "country")
    search_lang = _optional_string(arguments, "search_lang")
    ui_lang = _optional_string(arguments, "ui_lang")
    freshness = _optional_string(arguments, "freshness")
    _validate_freshness(freshness)

    safesearch = _optional_string(arguments, "safesearch") or "moderate"
    if safesearch not in _SAFESEARCH_VALUES:
        raise ValueError("`safesearch` must be off, moderate, or strict")

    params: dict[str, str | int | bool] = {
        "q": query,
        "count": count,
        "offset": offset,
        "safesearch": safesearch,
        "spellcheck": _boolean_argument(arguments, "spellcheck", default=True),
        "extra_snippets": _boolean_argument(arguments, "extra_snippets", default=True),
        # Restrict the response to the result family this tool understands.
        "result_filter": "web",
        # Avoid Brave's snippet decoration markers in model-visible output.
        "text_decorations": False,
    }
    if country is not None:
        params["country"] = country.upper()
    if search_lang is not None:
        params["search_lang"] = search_lang
    if ui_lang is not None:
        params["ui_lang"] = ui_lang
    if freshness is not None:
        params["freshness"] = freshness
    return params


async def request_brave_search(
    config: BraveSearchConfig,
    params: Mapping[str, str | int | bool],
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> httpx.Response:
    """Send one Brave Web Search request.

    `transport` is injectable so tests can use `httpx.MockTransport` instead of
    performing network access.
    """
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": config.api_key,
        "User-Agent": "tau-brave-search/1.0",
    }
    async with httpx.AsyncClient(
        transport=transport,
        timeout=config.timeout_seconds,
        follow_redirects=False,
    ) as client:
        return await client.get(config.endpoint, params=params, headers=headers)


def _safe_error_body(response: httpx.Response, api_key: str) -> str:
    """Extract a bounded error message without exposing request headers.

    The API key is redacted defensively: even if a provider (or a misbehaving
    endpoint override) echoes the key in its response body, it must never reach
    model-visible output or session history.
    """
    try:
        body: Any = response.json()
        rendered = json.dumps(body, ensure_ascii=False)
    except (ValueError, TypeError):
        rendered = response.text
    rendered = rendered.strip().replace(api_key, "[redacted]")
    if len(rendered) > MAX_ERROR_BODY_CHARS:
        rendered = rendered[:MAX_ERROR_BODY_CHARS] + "..."
    return rendered


def _http_error_message(response: httpx.Response, api_key: str) -> str:
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
    body = _safe_error_body(response, api_key)
    if body:
        message += f"\nProvider response: {body}"
    return message


def normalize_result(raw: Mapping[str, Any]) -> dict[str, JSONValue]:
    """Retain fields useful to the model and discard bulky provider metadata."""
    title = raw.get("title")
    url = raw.get("url")
    description = raw.get("description")
    age = raw.get("age")
    language = raw.get("language")
    subtype = raw.get("subtype")

    extra = raw.get("extra_snippets")
    extra_snippets: list[JSONValue] = []
    if isinstance(extra, list):
        extra_snippets = [item for item in extra if isinstance(item, str)]

    result: dict[str, JSONValue] = {
        "title": title if isinstance(title, str) else "",
        "url": url if isinstance(url, str) else "",
        "description": description if isinstance(description, str) else "",
        "extra_snippets": extra_snippets,
    }
    if isinstance(age, str):
        result["age"] = age
    if isinstance(language, str):
        result["language"] = language
    if isinstance(subtype, str):
        result["subtype"] = subtype
    return result


def format_results(
    query: str,
    results: list[dict[str, JSONValue]],
    *,
    altered_query: str | None,
) -> str:
    """Render normalized results as model-visible text."""
    if not results:
        return f"No Brave Search web results found for: {query}"

    lines = [f"Brave Search results for: {query}"]
    if altered_query and altered_query != query:
        lines.append(f"Brave used the corrected query: {altered_query}")
    lines.append("")

    for index, result in enumerate(results, start=1):
        title = result.get("title") or "(untitled result)"
        url = result.get("url") or "(URL unavailable)"
        description = result.get("description")
        age = result.get("age")
        extra_snippets = result.get("extra_snippets")

        lines.append(f"{index}. {title}")
        lines.append(f"   URL: {url}")
        if age:
            lines.append(f"   Age: {age}")
        if description:
            lines.append(f"   Snippet: {description}")
        if isinstance(extra_snippets, list):
            for snippet in extra_snippets:
                if isinstance(snippet, str) and snippet:
                    lines.append(f"   Additional snippet: {snippet}")
        lines.append("")

    lines.append(
        "Use the listed URLs when citing or referring to these sources. "
        "Search snippets can be incomplete; do not claim that they prove "
        "details not present in the returned text."
    )
    return "\n".join(lines).rstrip()


async def run_brave_search(
    arguments: Mapping[str, JSONValue],
    *,
    config: BraveSearchConfig,
    transport: httpx.AsyncBaseTransport | None = None,
) -> AgentToolResult:
    """Execute one Brave Web Search tool call.

    Invalid arguments raise `ValueError` before any network access; the agent
    loop surfaces the message to the model. Operational failures (timeouts,
    transport errors, HTTP errors, malformed responses) return an error result
    so the model can recover, and never include the API key.
    """
    params = build_search_params(arguments)
    query = str(params["q"])
    offset = int(params["offset"])

    try:
        response = await request_brave_search(config, params, transport=transport)
    except httpx.TimeoutException:
        return AgentToolResult(
            content=[TextContent(text="Brave Search timed out before returning results.")],
            details={"error": "timeout"},
        )
    except httpx.RequestError as exc:
        return AgentToolResult(
            content=[TextContent(text=f"Brave Search request failed: {type(exc).__name__}")],
            details={"error": "request_error", "exception": type(exc).__name__},
        )

    if response.status_code != 200:
        return AgentToolResult(
            content=[TextContent(text=_http_error_message(response, config.api_key))],
            details={"error": "http_error", "status_code": response.status_code},
        )

    try:
        payload: Any = response.json()
    except ValueError:
        return AgentToolResult(
            content=[TextContent(text="Brave Search returned an invalid JSON response.")],
            details={"error": "invalid_json"},
        )
    if not isinstance(payload, dict):
        return AgentToolResult(
            content=[TextContent(text="Brave Search returned an unexpected response shape.")],
            details={"error": "invalid_response"},
        )

    web = payload.get("web")
    raw_results: list[Any] = []
    if isinstance(web, dict):
        candidate_results = web.get("results")
        if isinstance(candidate_results, list):
            raw_results = candidate_results
    results = [normalize_result(item) for item in raw_results if isinstance(item, dict)]

    altered_query: str | None = None
    query_metadata = payload.get("query")
    if isinstance(query_metadata, dict):
        candidate = query_metadata.get("altered")
        if isinstance(candidate, str):
            altered_query = candidate

    details: dict[str, JSONValue] = {
        "provider": "brave",
        "query": query,
        "count": len(results),
        "offset": offset,
        # cast: `list` is invariant, so the narrower element type needs a cast.
        "results": cast(list[JSONValue], results),
    }
    if altered_query is not None:
        details["altered_query"] = altered_query

    return AgentToolResult(
        content=[TextContent(text=format_results(query, results, altered_query=altered_query))],
        details=details,
    )
