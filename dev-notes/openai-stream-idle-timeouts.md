# OpenAI stream inactivity timeouts

## What changed

Tau now gives OpenAI-compatible and OpenAI Codex SSE responses a separate
inactivity timeout. Ordinary connection, request-write, and connection-pool
operations keep the 60-second `timeout_seconds` default. An established response
stream can remain quiet for 600 seconds by default through
`stream_idle_timeout_seconds`

The timeout is the maximum interval between response-body chunks, not a total
turn deadline. If a proxy or provider sends SSE heartbeat bytes, each chunk
resets the inactivity timer

A terminal HTTP transport failure now includes its exception type and request
phase in the diagnostic log. An empty HTTPX `ReadTimeout` no longer renders as
`Error: Error`; Tau reports the stream inactivity limit and attempt count

Cancellation now interrupts a blocked SSE read instead of waiting for another
line or for the inactivity timeout

## Why it exists

Reasoning requests can open a successful SSE response and then send no body data
for more than 60 seconds. HTTPX treats its read timeout as a network-inactivity
limit, not as a total request deadline. Tau previously applied one 60-second
value to every timeout phase, retried the quiet request twice, and then surfaced
HTTPX's empty exception string

A local credential-injection proxy made this behavior easier to observe, but the
problem was in Tau's client timeout and diagnostic policy. Proxy streaming itself
was working

## Architecture

- `tau_ai.http` owns shared timeout, transport-error, and cancellable-stream
  helpers
- `tau_ai.openai_compatible` and `tau_ai.openai_codex` apply the stream timeout
  and preserve their existing retry rule: retry only before model output starts
- `tau_coding.provider_config` persists and validates
  `stream_idle_timeout_seconds`
- `tau_coding.diagnostics` records only safe scalar transport fields
- `tau_agent` remains provider-neutral and independent of HTTPX

## Configuration

Set the value per provider in `~/.tau/providers.json`:

```json
{
  "provider_preferences": {
    "openai-codex": {
      "stream_idle_timeout_seconds": 900
    }
  }
}
```

Custom provider setup also accepts:

```bash
tau --stream-idle-timeout-seconds 900 setup
```

## How to test

```bash
uv run pytest tests/test_http.py tests/test_tau_ai.py tests/test_coding_session.py
uv run pytest tests/test_provider_config.py tests/test_provider_runtime.py tests/test_cli.py
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run mypy
```
