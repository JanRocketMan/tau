---
title: "Incomplete response recovery"
---

Tau now distinguishes a complete model turn from a stream that only looks complete at the HTTP layer

## Why this exists

An OpenAI-compatible gateway can return HTTP 200, stream reasoning, and then stop before it sends visible text or a tool call. Tau previously normalized any unknown or missing `finish_reason` to `stop`, so the agent loop treated an interrupted response as successful and ended the run

This was most visible with OpenCode Go, but it is not specific to one model. A Responses model can also report a completed response that contains reasoning but no answer or tool call

## Provider finish validation

The OpenAI-compatible adapter now validates terminal provider values instead of guessing

- Chat Completions accepts known stop, length, and tool-call reasons
- Responses accepts `completed` and `incomplete`
- `insufficient_system_resource` becomes a retryable provider interruption
- `content_filter` becomes an explicit terminal error
- A missing or unknown reason becomes an explicit error

The raw value is stored in assistant diagnostics as `provider_finish` for successful responses or `provider_error` for failures. Session JSONL therefore keeps the evidence needed to diagnose the next provider incident

If a retryable finish reason arrives before any model output, `tau_ai` uses the configured provider retry budget and backoff. If reasoning has already streamed, the adapter does not replay the same request because that would duplicate streamed output. It marks a reasoning-only interruption for the bounded agent recovery instead

## Bounded agent recovery

The portable agent loop checks the completed assistant message. It retries when either condition is true

- the model returned reasoning, but no visible text or tool call
- the provider marked a partial reasoning-only interruption as safe to continue

The loop adds one hidden `CustomMessage` that asks the model to continue the pending task. This matches the manual `continue` workaround without showing a fake user message in the TUI. The message remains in durable history so replay is deterministic

Only one consecutive incomplete response is retried. If that retry is also incomplete, Tau stops and shows the result. A valid tool call resets the bound, so a later independent interruption after tool progress can receive its own single recovery attempt

## Retry events

Provider backoff and incomplete-response recovery both emit `RetryEvent`

- `scope="provider"` reports HTTP, transport, or provider-stream backoff
- `scope="response"` reports the one bounded continuation

The TUI and transcript renderer show both as status output. Final text and JSON renderers do not treat an intermediate recovered provider error as the final run result

## DeepSeek V4 compatibility

The OpenCode Go `deepseek-v4-flash` model now declares the same required compatibility behavior as the model contract

- send DeepSeek's `thinking` object
- use `max_tokens` when a maximum is sent
- omit unsupported `store`
- replay actual `reasoning_content`, or an empty string when an assistant turn had no reasoning delta

The replay fallback prevents tool-result requests from failing when DeepSeek requires the assistant field even though the prior response omitted it

## How to test

```bash
uv run pytest tests/test_tau_ai.py -q
uv run pytest tests/test_agent_loop.py -q
uv run pytest tests/test_coding_session.py -q
uv run pytest tests/test_tui_adapter.py tests/test_rendering.py -q
uv run pytest tests/test_provider_catalog.py tests/test_provider_runtime.py -q
```
