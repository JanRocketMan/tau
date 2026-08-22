---
title: "Hotkey catalog: data/hotkeys.toml as single source of truth"
---

This phase moves every keyboard shortcut in the Tau TUI into one packaged data
file, `src/tau_coding/data/hotkeys.toml`, and removes the in-session `/hotkeys`
command.

## What was added

- `src/tau_coding/data/hotkeys.toml` - the catalog. Each `[[keymaps]]` block
  names a scope (the prompt, app bindings, prompt footer modes, pickers, and
  modals); each `[[keymaps.bindings]]` entry carries a stable `name`, the
  `key`, the Textual `action`, and a short `description`. Optional flags:
  `show`, `priority`, `bound` (false means the widget handles the key itself),
  and `key_display` (footer hints, with `{name}` placeholders).
- `src/tau_coding/hotkeys.py` - a typed loader mirroring `catalog_loader.py`.
  `HotkeyCatalog` resolves keymaps, builds Textual `Binding` lists
  (`bindings(keymap, overrides=...)`), applies user remaps to keys and footer
  hints, and validates the file (schema version, required fields, unique names,
  unique keys per keymap, resolvable references).

## What changed

- Every `BINDINGS` class variable in `tui/app.py` and `tui/project_trust.py`
  now reads from the catalog instead of listing `Binding(...)` literals.
- `_app_bindings`, `_prompt_bindings`, and `_hidden_prompt_bindings` build from
  the `app` and `prompt_*` keymaps; hotkey names match `TuiKeybindings` field
  names so user remaps keep working.
- `TuiKeybindings` defaults now come from the catalog: unset fields resolve in
  `__post_init__`, so the packaged file stays the only place keys are defined.
- `on_key` handlers compare against catalog keys (`_widget_keys` / `_prompt_keys`).
- The `/hotkeys` slash command and its test were removed; the docs point users
  at the catalog file directly.
- Repo-root symlinks `catalog.toml` and `hotkeys.toml` point at the packaged
  data files for convenient editing.

## Why it exists

- One place to see, document, and change every hotkey, with a description per
  entry instead of an in-session copy that could drift.
- The loader validates the file at import, so a malformed catalog fails loudly
  instead of silently changing key behavior.

## How it maps to the codebase

- `tau_coding/hotkeys.py` mirrors `tau_coding/catalog_loader.py`: packaged
  resource, parse + validate, cached singleton accessor.
- `tau_coding/tui/config.py` keeps its user-facing settings/JSON layer; only
  the default values moved into the catalog.
- Reference-style keymaps (`app`, `prompt_normal`, `prompt_completion`,
  `prompt_running`) point at `prompt` definitions, so keys and actions are
  never duplicated.

## How to test or use it

- `uv run pytest tests/test_hotkeys.py tests/test_tui_app.py` - catalog
  parsing, keymaps, and TUI binding behavior.
- Edit `hotkeys.toml` (or the `./hotkeys.toml` symlink) to change a key; the
  change applies on the next TUI start.
- TUI setting remaps (via `tui_settings_from_json`) still override the
  catalog defaults at runtime.