# OpenAI GPT-6 catalog refresh

The Codex catalog now uses the exact ID `gpt-6.1-sol` for GPT-6.1 Sol and
removes `gpt-6-sol` from the provider. Its existing 272,000-token context value
stays as a conservative Codex fallback; Tau uses the live Codex model catalog
when it can.

GPT-6.1 Sol costs $2 per million input tokens and $10 per million output
tokens, the same standard rates as GPT-6 Sol. Cached input is $0.10 instead of
$0.20, and cache writes cost $2.50 for both. GPT-6 Luna costs $0.10 input,
$0.50 output, $0.01 cached input, and $0.125 cache writes per million tokens.
Both models support reasoning effort through `max`, which the catalog exposes
as Tau's `max` thinking level.

OpenAI references:

- [GPT-6.1 Sol model](https://developers.openai.com/api/docs/models/gpt-6.1-sol)
- [GPT-6 Luna model](https://developers.openai.com/api/docs/models/gpt-6-luna)
- [API pricing](https://developers.openai.com/api/docs/pricing)

## Verify

```bash
uv run pytest tests/test_provider_catalog.py tests/test_provider_config.py tests/test_provider_runtime.py
```
