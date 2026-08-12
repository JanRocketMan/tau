import asyncio
import os
from collections.abc import AsyncIterator

import httpx
import pytest

from tau_agent import SimpleCancellationToken
from tau_ai.http import (
    aiter_with_cancellation,
    create_async_client,
    normalize_proxy_url,
    normalized_proxy_environment,
    streaming_timeout,
    transport_error_data,
    transport_error_message,
)


def test_normalize_proxy_url_converts_generic_socks_scheme() -> None:
    assert normalize_proxy_url("socks://127.0.0.1:1080") == "socks5://127.0.0.1:1080"
    assert normalize_proxy_url("SOCKS://user:pass@proxy.local:1080") == (
        "socks5://user:pass@proxy.local:1080"
    )


def test_normalize_proxy_url_leaves_explicit_schemes_unchanged() -> None:
    assert normalize_proxy_url("socks5://127.0.0.1:1080") == "socks5://127.0.0.1:1080"
    assert normalize_proxy_url("socks5h://127.0.0.1:1080") == "socks5h://127.0.0.1:1080"
    assert normalize_proxy_url("http://127.0.0.1:8080") == "http://127.0.0.1:8080"


def test_normalized_proxy_environment_restores_original_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALL_PROXY", "socks://127.0.0.1:1080")

    with normalized_proxy_environment():
        assert os.environ["ALL_PROXY"] == "socks5://127.0.0.1:1080"

    assert os.environ["ALL_PROXY"] == "socks://127.0.0.1:1080"


@pytest.mark.anyio
async def test_create_async_client_accepts_generic_socks_proxy_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALL_PROXY", "socks://127.0.0.1:1080")

    client = create_async_client(timeout=1)
    try:
        assert isinstance(client, httpx.AsyncClient)
    finally:
        await client.aclose()

    assert os.environ["ALL_PROXY"] == "socks://127.0.0.1:1080"


def test_streaming_timeout_uses_separate_read_inactivity_limit() -> None:
    timeout = streaming_timeout(timeout_seconds=60, stream_idle_timeout_seconds=600)

    assert timeout.connect == 60
    assert timeout.write == 60
    assert timeout.pool == 60
    assert timeout.read == 600


def test_transport_read_timeout_has_actionable_message_and_details() -> None:
    request = httpx.Request("POST", "https://example.test/v1/responses")
    error = httpx.ReadTimeout("", request=request)

    assert transport_error_message(
        error,
        provider_name="openai-codex",
        attempts=3,
        response_started=True,
        stream_idle_timeout_seconds=600,
    ) == ("openai-codex stream received no data for 600 seconds (ReadTimeout) after 3 attempts.")
    assert transport_error_data(
        error,
        attempts=3,
        response_started=True,
        stream_idle_timeout_seconds=600,
    ) == {
        "attempts": 3,
        "error_type": "ReadTimeout",
        "phase": "response_stream",
        "stream_idle_timeout_seconds": 600,
    }


@pytest.mark.anyio
async def test_aiter_with_cancellation_interrupts_quiet_stream() -> None:
    signal = SimpleCancellationToken()
    read_started = asyncio.Event()
    read_closed = asyncio.Event()

    async def quiet_stream() -> AsyncIterator[str]:
        try:
            read_started.set()
            await asyncio.Event().wait()
            yield "unreachable"
        finally:
            read_closed.set()

    async def cancel() -> None:
        await read_started.wait()
        signal.cancel()

    cancel_task = asyncio.create_task(cancel())
    items = [
        item
        async for item in aiter_with_cancellation(
            quiet_stream(),
            signal=signal,
            poll_interval_seconds=0,
        )
    ]
    await cancel_task

    assert items == []
    assert read_closed.is_set()
