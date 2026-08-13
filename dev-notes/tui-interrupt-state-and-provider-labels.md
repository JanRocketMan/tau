# TUI interrupt state and provider labels

## What changed

Tau now reserves `Ctrl+C` as a hard TUI stop action

- During a model request, tool call, or manual compaction, it cancels the active work
- During idle input, it keeps the former fallback behavior and clears the prompt
- `Ctrl+U` is the explicit clear-prompt key
- Extensions cannot intercept `Ctrl+C`

The prompt left border now uses existing theme tokens to show the latest run state

- `success` while Tau is working
- `error` after a model run fails
- the normal prompt color after a new run starts, succeeds, or is cancelled
- the existing tool color for `!` and `!!` shell input

User catalog files can also define display-only provider labels

```toml
schema_version = 1

[provider_labels]
openai-codex = "codex"
```

The compact session status and model picker show `codex:<model>`. Provider routing, credentials, commands, and session metadata still use `openai-codex`

## Why

`Ctrl+C` is the terminal-standard stop reflex. It must stop a provider stream or active tool without forcing the user to quit Tau. The border colors make run state visible without adding new chrome or changing the current theme palette

Provider labels solve a separate display problem. A short user label must not change provider identity because that identity connects catalog metadata, credentials, runtime routing, preferences, and saved sessions

## Architecture

The cancellation token remains in `tau_agent`. Textual only decides which key calls the existing `CodingSession.cancel()` boundary

Prompt colors and provider labels remain in `tau_coding`, which owns TUI presentation and user catalog files. The reusable harness and provider streaming packages do not read display configuration

## Verification

```bash
uv run pytest tests/test_tui_config.py tests/test_tui_app.py tests/test_provider_catalog.py
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run mypy
```

For a manual check, start a slow run and press `Ctrl+C` during model output and during a `bash` tool call. Confirm that Tau stays open, work stops, and the draft prompt is preserved. Trigger a provider error and confirm that the prompt border becomes the theme error color. Add the label mapping above to `~/.tau/catalog.toml`, restart Tau, and confirm that the status block and model picker show `codex` while `tau --provider openai-codex` still works
