"""Provider-neutral web-search core for Tau coding sessions.

The optional `search` tool sends a model query to the configured web-search
provider (Parallel Search by default, Brave as an alternative). Each provider
implements the `SearchProvider` interface: it validates tool arguments, builds
its own HTTP request, and normalizes the provider response into the shared
result shape used for rendering and session `details`. `run_search` executes
that flow and maps operational failures (timeouts, transport errors, HTTP
errors, malformed responses) to bounded, model-recoverable error messages.

The API key is a confidential credential. It is read from the process
environment, is never a model-visible tool argument, and never appears in tool
output, session history, or error messages. Search queries are the only data
sent to the configured provider; treat returned snippets as untrusted external
content.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, cast

import httpx

from tau_agent.messages import TextContent
from tau_agent.tools import AgentToolResult
from tau_agent.types import JSONValue

DEFAULT_TIMEOUT_SECONDS = 20.0
MAX_QUERY_CHARS = 400
MAX_QUERY_WORDS = 50
MAX_ERROR_BODY_CHARS = 1_000

_FRESHNESS_SHORTHANDS = frozenset({"pd", "pw", "pm", "py"})


@dataclass(frozen=True, slots=True)
class PreparedRequest:
    """A validated, provider-specific HTTP request ready to send.

    Providers set exactly one of `query_params` (GET) or `json_body` (POST);
    `headers` may carry the provider credential.
    """

    query: str
    method: str
    url: str
    query_params: dict[str, str | int | bool] | None = None
    json_body: Mapping[str, JSONValue] | None = None
    headers: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ParsedSearch:
    """A provider-normalized search outcome.

    `results` is a tuple of normalized result dicts with the shared keys
    `title`, `url`, `description`, and `extra_snippets`, plus optional
    provider keys such as `age` or `publish_date`. `note` is an optional,
    already-rendered line appended under the header (for example a corrected
    query or a provider warning). `metadata` holds provider fields copied into
    the tool `details` such as a search id, session id, or usage counters.
    """

    query: str
    results: tuple[dict[str, JSONValue], ...]
    note: str | None = None
    metadata: Mapping[str, JSONValue] = field(default_factory=dict)


class SearchProvider(ABC):
    """Backend-agnostic web-search provider used by the `search` tool."""

    name: str = ""
    display_name: str = ""
    short_name: str = ""
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    @abstractmethod
    def describe_arguments(self) -> Mapping[str, JSONValue]:
        """Return JSON-schema properties for the model-visible tool input."""

    @abstractmethod
    def prepare(self, arguments: Mapping[str, JSONValue]) -> PreparedRequest:
        """Validate `arguments` and build the HTTP request.

        Raises:
            ValueError: If any argument fails local validation. No network
                request is made in that case.
        """

    @abstractmethod
    def parse(self, request: PreparedRequest, payload: Mapping[str, Any]) -> ParsedSearch:
        """Normalize a 200 JSON payload into results and an optional note."""

    @abstractmethod
    def http_error_message(self, response: httpx.Response) -> str:
        """Return an actionable message for a non-200 response."""

    def timeout_message(self) -> str:
        """Return the message used when the request times out."""
        return f"{self.display_name} timed out before returning results."

    def transport_error_message(self, exc: httpx.RequestError) -> str:
        """Return the message used when the transport layer fails."""
        return f"{self.display_name} request failed: {type(exc).__name__}"


def common_argument_properties() -> Mapping[str, JSONValue]:
    """Return the shared model-visible tool arguments across providers."""
    return {
        "query": {
            "type": "string",
            "minLength": 1,
            "maxLength": MAX_QUERY_CHARS,
            "description": "Web search query. Keep it focused and below 50 words.",
        },
        "count": {
            "type": "integer",
            "minimum": 1,
            "maximum": 20,
            "default": 10,
            "description": "Number of web results to request.",
        },
        "country": {
            "type": "string",
            "minLength": 2,
            "maxLength": 2,
            "description": ("Optional two-letter result country code, for example US, GB, or DE."),
        },
        "freshness": {
            "type": "string",
            "description": ("Optional date filter: pd, pw, pm, py, or YYYY-MM-DDtoYYYY-MM-DD."),
        },
    }


def common_query_params(
    arguments: Mapping[str, JSONValue],
) -> tuple[str, int, str | None, str | None]:
    """Validate and return the shared (query, count, country, freshness) tuple.

    Raises:
        ValueError: If any shared argument fails validation.
    """
    query = _optional_string(arguments, "query") or ""
    _validate_query(query)

    count = _integer_argument(arguments, "count", default=10, minimum=1, maximum=20)

    country = _optional_string(arguments, "country")
    if country is not None:
        if len(country) != 2 or not country.isalpha():
            raise ValueError("`country` must be a two-letter code")
        country = country.upper()

    freshness = _optional_string(arguments, "freshness")
    _validate_freshness(freshness)
    return query, count, country, freshness


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


def _validate_query(query: str) -> None:
    if not query:
        raise ValueError("`query` must not be empty")
    if len(query) > MAX_QUERY_CHARS:
        raise ValueError(f"`query` must not exceed {MAX_QUERY_CHARS} characters")
    if len(query.split()) > MAX_QUERY_WORDS:
        raise ValueError(f"`query` must not exceed {MAX_QUERY_WORDS} words")


def _validate_freshness(freshness: str | None) -> None:
    """Perform conservative local validation of a date filter.

    Shorthands map to Brave; providers that cannot express a shorthand (Parallel)
    ignore it. Custom ``YYYY-MM-DDtoYYYY-MM-DD`` ranges are validated locally and
    forwarded to providers that support them.
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


def split_freshness_range(freshness: str | None) -> tuple[str | None, str | None]:
    """Return (start_date, end_date) from a validated date-range filter.

    Shorthands and ``None`` yield ``(None, None)`` because they cannot be
    expressed as an explicit range.
    """
    if freshness is None or "to" not in freshness:
        return None, None
    start, _, end = freshness.partition("to")
    start_date = start.strip() or None
    end_date = end.strip() or None
    return start_date, end_date


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
    display_name: str,
    note: str | None,
) -> str:
    """Render normalized results as model-visible text."""
    if not results:
        return f"No {display_name} web results found for: {query}"

    lines = [f"{display_name} results for: {query}"]
    if note:
        lines.append(note)
    lines.append("")

    for index, result in enumerate(results, start=1):
        title = result.get("title") or "(untitled result)"
        url = result.get("url") or "(URL unavailable)"
        description = result.get("description")
        age = result.get("age")
        publish_date = result.get("publish_date")
        extra_snippets = result.get("extra_snippets")

        lines.append(f"{index}. {title}")
        lines.append(f"   URL: {url}")
        if age:
            lines.append(f"   Age: {age}")
        if publish_date:
            lines.append(f"   Published: {publish_date}")
        if description:
            lines.append(f"   Snippet: {description}")
        if isinstance(extra_snippets, list):
            for snippet in extra_snippets:
                if isinstance(snippet, str) and snippet and snippet != description:
                    lines.append(f"   Additional snippet: {snippet}")
        lines.append("")

    lines.append(
        "Use the listed URLs when citing or referring to these sources. "
        "Search snippets can be incomplete; do not claim that they prove "
        "details not present in the returned text."
    )
    return "\n".join(lines).rstrip()


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


async def _send(
    provider: SearchProvider,
    request: PreparedRequest,
    *,
    transport: httpx.AsyncBaseTransport | None,
) -> httpx.Response:
    """Send one provider request with an injectable transport."""
    headers = {"Accept": "application/json", **dict(request.headers)}
    async with httpx.AsyncClient(
        transport=transport,
        timeout=provider.timeout_seconds,
        follow_redirects=False,
    ) as client:
        return await client.request(
            request.method,
            request.url,
            params=request.query_params,
            json=request.json_body,
            headers=headers,
        )


async def run_search(
    provider: SearchProvider,
    arguments: Mapping[str, JSONValue],
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> AgentToolResult:
    """Execute one provider-agnostic web-search tool call.

    Invalid arguments raise `ValueError` before any network access; the agent
    loop surfaces the message to the model. Operational failures (timeouts,
    transport errors, HTTP errors, malformed responses) return an error result
    so the model can recover, and never include the API key.
    """
    request = provider.prepare(arguments)

    try:
        response = await _send(provider, request, transport=transport)
    except httpx.TimeoutException:
        return AgentToolResult(
            content=[TextContent(text=provider.timeout_message())],
            details={"error": "timeout"},
        )
    except httpx.RequestError as exc:
        return AgentToolResult(
            content=[TextContent(text=provider.transport_error_message(exc))],
            details={"error": "request_error", "exception": type(exc).__name__},
        )

    if response.status_code != 200:
        return AgentToolResult(
            content=[TextContent(text=provider.http_error_message(response))],
            details={"error": "http_error", "status_code": response.status_code},
        )

    try:
        payload: Any = response.json()
    except ValueError:
        return AgentToolResult(
            content=[
                TextContent(text=f"{provider.display_name} returned an invalid JSON response.")
            ],
            details={"error": "invalid_json"},
        )
    if not isinstance(payload, dict):
        return AgentToolResult(
            content=[
                TextContent(text=f"{provider.display_name} returned an unexpected response shape.")
            ],
            details={"error": "invalid_response"},
        )

    parsed = provider.parse(request, payload)
    text = format_results(
        parsed.query,
        list(parsed.results),
        display_name=provider.display_name,
        note=parsed.note,
    )
    details: dict[str, JSONValue] = {
        "provider": provider.name,
        "query": parsed.query,
        "count": len(parsed.results),
        # cast: `list` is invariant, so the narrower element type needs a cast.
        "results": cast(list[JSONValue], list(parsed.results)),
    }
    details.update(dict(parsed.metadata))
    return AgentToolResult(content=[TextContent(text=text)], details=details)
