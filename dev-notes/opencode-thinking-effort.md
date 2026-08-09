# OpenCode thinking defaults and `/effort`

## What changed

The OpenCode Go (`opencode-go`) and OpenCode Zen (`opencode`) catalog entries now
carry model-specific thinking defaults:

- `kimi-k3` starts at Tau's `max` level and sends `reasoning_effort: "max"`.
- `deepseek-v4-flash` starts at Tau's `high` level and sends
  `reasoning_effort: "high"`.

The defaults live in each model's catalog metadata instead of on the provider,
so the same provider can select the correct level for each model. The existing
wire mapping remains available for provider values such as OpenCode's `max`
value.

The interactive TUI also registers `/effort [level]`. With no argument it shows
the current level and the levels available for the active model. With a level,
it validates and persists the choice for future turns in the current session.
The existing Shift+Tab shortcut continues to cycle through the same
model-aware levels.

## Why it exists

Pi separates model capability metadata from the session control that selects an
effort level. Tau follows that boundary in `tau_coding`: the catalog describes
model defaults and wire mappings, `CodingSession` resolves and persists the
active level, and the TUI applies slash-command results without putting Textual
into the provider layer.

## How to verify

```bash
uv run pytest tests/test_provider_catalog.py tests/test_provider_config.py tests/test_commands.py tests/test_tui_autocomplete.py tests/test_thinking.py
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy
```

In a running TUI, try `/effort`, `/effort high`, or `/effort max` after selecting
an OpenCode model. `/session` reports the active effort level.
