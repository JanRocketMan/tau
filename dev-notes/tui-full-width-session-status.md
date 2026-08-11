---
title: "TUI full-width session status"
---

## What changed

Tau no longer mounts a session sidebar. The transcript and prompt now use the
full terminal width at every screen size.

The two-line status block below the prompt now shows:

- the session name and active provider, model, and thinking level on the first row
- the working directory, short Jujutsu change ID, and active context usage on
  the second row

The status block omits the session name when the terminal is narrower than 80
columns or shorter than 20 rows. It then uses the previous compact layout, with
the directory on the left and model details on the right. The terminal tab title
continues to identify a named session.

## Why

The sidebar reduced the width available for the transcript and duplicated much
of the information that users can get from `/session`. Moving the session name into the
existing status block keeps the active session visible without reserving a large
part of the screen.

The responsive title rule keeps the model, working directory, and context data
readable on small terminals. These values are more useful for the next prompt,
so Tau removes the session name first.

## Compatibility

`sidebar_position` is no longer part of `TuiSettings` and Tau no longer writes it
to `~/.tau/tui.json`. The settings parser treats an old `sidebar_position` value
as an unknown field. Existing configuration files therefore continue to load.

The sidebar widgets and Rich renderers were removed from `tau_coding.tui`. The
session statistics and `/session` command remain independent of Textual.

## Verification

Run:

```bash
uv run pytest tests/test_tui_config.py tests/test_tui_app.py
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

For manual verification, start `tau` in a named session at 80 columns or wider.
Confirm that no sidebar appears and that the status block shows the name, model,
directory, Jujutsu details, and context usage. Resize below 80 columns or 20 rows
and confirm that only the session name disappears. Resize back and confirm that
the name returns.
