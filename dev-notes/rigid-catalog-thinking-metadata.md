# Rigid catalog thinking metadata

## What changed

`thinking_level_map` is gone. The provider catalog now declares thinking
support with one rigid shape:

- A `[[providers]]` entry sets only `thinking_parameter` — the request field
  Tau uses to change effort (`reasoning_effort`, `reasoning.effort`, or
  `anthropic.thinking`). Provider-level `thinking_levels`, `thinking_models`,
  and `thinking_default` are rejected.
- Every `[providers.model_metadata.<model>]` entry declares exactly two thinking
  fields: `thinking_levels` (the Tau levels the model accepts) and
  `thinking_default` (a member of that list used at startup).

The value Tau sends to the provider is the Tau level name itself
(`reasoning_effort_for_level`, which maps `off` to `none` and passes every
other level through). There is no per-model wire-value remapping anymore: a
model lists only levels whose names the provider accepts.

The `/effort` slash command was removed. The thinking-cycle keybinding (default
`Shift+Tab`, remappable via `thinking_cycle` in `~/.tau/tui.json`) is the way
to change the level in a session. Cycling steps through the active model's
`thinking_levels` and is a silent no-op when the model exposes zero or one
levels.

## Why it exists

The old `thinking_level_map` mixed two jobs: marking a level unsupported per
model (`null` values, written in the catalog as `unsupported_thinking_levels`)
and remapping a Tau level to a provider-specific value (`xhigh` to `max`). The
two-job map made the catalog harder to read and to validate, and the implicit
"everything except `xhigh` is supported unless listed" fallback was surprising.

The rigid shape keeps capability data in one place — model metadata — and makes
the wire value trivially predictable: the level name is the value. When a
provider rejects a level name, the fix is to remove that level from the model's
`thinking_levels` list.

## Mapping to Pi's design

Pi keeps model capability metadata separate from session controls. Tau now
follows the same boundary more strictly: `tau_coding` resolves the available
levels and defaults purely from `ProviderModelMetadata.thinking_levels` /
`thinking_default`, the session layer remembers per-model preferences in
`thinking_defaults`, and the TUI consumes the resolved level without knowing
how the catalog stores it.

## How to verify

```bash
uv run pytest tests/test_provider_catalog.py tests/test_provider_config.py tests/test_provider_runtime.py tests/test_coding_session.py tests/test_commands.py tests/test_tui_app.py
uv run ruff check src tests
uv run ruff format --check src tests
```

In a running TUI:

- `/model` to a model with different `thinking_levels` and press the thinking
  key: the level cycles through the new model's list only.
- Pick a model with a single level and press the key: nothing changes and no
  error appears.
- `/effort` is no longer a registered command.
