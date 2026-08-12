"""HTTP client helpers shared by Tau network integrations."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager, suppress
from typing import Any

import httpx

from tau_ai.provider import CancellationToken

_PROXY_ENV_VARS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)


def normalize_proxy_url(proxy_url: str) -> str:
    """Return an httpx-compatible proxy URL.

    Some environments use ``socks://`` as a generic SOCKS proxy scheme. httpx
    accepts explicit SOCKS versions (for example ``socks5://`` and
    ``socks5h://``), but rejects the generic scheme before it can make a
    request. Treat the generic form as SOCKS5 so Tau can honor these proxy
    environment variables.
    """

    if proxy_url.lower().startswith("socks://"):
        return f"socks5://{proxy_url[len('socks://') :]}"
    return proxy_url


@contextmanager
def normalized_proxy_environment() -> Iterator[None]:
    """Temporarily normalize proxy environment variables for httpx construction."""

    original: dict[str, str | None] = {}
    changed = False
    for name in _PROXY_ENV_VARS:
        value = os.environ.get(name)
        if value is None:
            continue
        normalized = normalize_proxy_url(value)
        if normalized == value:
            continue
        original[name] = value
        os.environ[name] = normalized
        changed = True

    try:
        yield
    finally:
        if changed:
            for name, value in original.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value


def create_async_client(**kwargs: Any) -> httpx.AsyncClient:
    """Create an ``httpx.AsyncClient`` with Tau's proxy normalization applied."""

    with normalized_proxy_environment():
        return httpx.AsyncClient(**kwargs)


def streaming_timeout(
    *,
    timeout_seconds: float,
    stream_idle_timeout_seconds: float,
) -> httpx.Timeout:
    """Build an HTTP timeout with a longer inactivity limit for response streams."""

    return httpx.Timeout(timeout_seconds, read=stream_idle_timeout_seconds)


def transport_error_data(
    exc: httpx.HTTPError,
    *,
    attempts: int,
    response_started: bool,
    stream_idle_timeout_seconds: float,
) -> dict[str, Any]:
    """Return safe structured details for one terminal HTTP transport error."""

    phase = "response_stream" if response_started else "request"
    details: dict[str, Any] = {
        "attempts": attempts,
        "error_type": type(exc).__name__,
        "phase": phase,
    }
    if str(exc):
        details["error"] = str(exc)
    if isinstance(exc, httpx.ReadTimeout) and response_started:
        details["stream_idle_timeout_seconds"] = stream_idle_timeout_seconds
    return details


def transport_error_message(
    exc: httpx.HTTPError,
    *,
    provider_name: str,
    attempts: int,
    response_started: bool,
    stream_idle_timeout_seconds: float,
) -> str:
    """Return an actionable message even when HTTPX supplies an empty exception string."""

    error_type = type(exc).__name__
    attempts_text = "attempt" if attempts == 1 else "attempts"
    if isinstance(exc, httpx.ReadTimeout) and response_started:
        return (
            f"{provider_name} stream received no data for "
            f"{stream_idle_timeout_seconds:g} seconds ({error_type}) after "
            f"{attempts} {attempts_text}."
        )
    detail = str(exc).strip()
    if detail:
        return detail
    return f"{provider_name} request failed with {error_type} after {attempts} {attempts_text}."


async def aiter_with_cancellation[T](
    source: AsyncIterator[T],
    *,
    signal: CancellationToken | None,
    poll_interval_seconds: float = 0.05,
) -> AsyncIterator[T]:
    """Yield an async stream while allowing a polling cancellation token to stop a quiet read."""

    if signal is None:
        async for item in source:
            yield item
        return

    iterator = source.__aiter__()
    cancel_task = asyncio.create_task(
        _wait_for_cancellation(signal, poll_interval_seconds=poll_interval_seconds)
    )
    read_task: asyncio.Task[T] | None = None
    try:
        while True:
            read_task = asyncio.create_task(_next_item(iterator))
            done, _pending = await asyncio.wait(
                {read_task, cancel_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if cancel_task in done:
                read_task.cancel()
                with suppress(asyncio.CancelledError, StopAsyncIteration):
                    await read_task
                read_task = None
                return
            try:
                item = read_task.result()
            except StopAsyncIteration:
                read_task = None
                return
            read_task = None
            yield item
    finally:
        if read_task is not None and not read_task.done():
            read_task.cancel()
            with suppress(asyncio.CancelledError, StopAsyncIteration):
                await read_task
        cancel_task.cancel()
        with suppress(asyncio.CancelledError):
            await cancel_task
        close = getattr(iterator, "aclose", None)
        if close is not None:
            with suppress(RuntimeError):
                await close()


async def _next_item[T](iterator: AsyncIterator[T]) -> T:
    """Read one async-iterator item through a coroutine accepted by create_task."""

    return await iterator.__anext__()


async def _wait_for_cancellation(
    signal: CancellationToken,
    *,
    poll_interval_seconds: float,
) -> None:
    """Wait until a synchronous cancellation token changes state."""

    while not signal.is_cancelled():
        await asyncio.sleep(poll_interval_seconds)


def get_json(url: str, *, timeout: float, follow_redirects: bool = False) -> dict[str, object]:
    """Fetch a JSON object with Tau's proxy normalization applied."""

    with normalized_proxy_environment():
        response = httpx.get(url, timeout=timeout, follow_redirects=follow_redirects)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("HTTP response must be a JSON object")
    return data
