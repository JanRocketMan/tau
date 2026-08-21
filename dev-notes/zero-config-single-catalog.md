# Zero-config: single read-only catalog, shared Claude skills directory

## What was added

Tau no longer needs any user-level configuration files. Provider configuration
and the TUI keybindings are built-in defaults; user skills come from
`~/.claude/skills` (shared with Claude Code). The packaged catalog is **read-only
for Tau**: nothing inside a session, the TUI, or a CLI command can modify it
The catalog file is edited by hand only.

Removed files, functions, and concepts:

- `~/.tau/catalog.toml` - the user-level catalog overlay is gone. The packaged
  `src/tau_coding/data/catalog.toml` is the single catalog: provider
  definitions, `provider_labels`, the `default_provider` root key (now
  `openai-codex`, with `gpt-5.6-sol` as its default model), and per-provider
  preferences (`default_model`, `headers`, `timeout_seconds`,
  `stream_idle_timeout_seconds`, `max_retries`, `max_retry_delay_seconds`,
  `thinking_defaults`, `inference_providers`).
- `~/.tau/providers.json` - gone, along with `save_provider_settings` and all
  other persistence entry points (`save_default_provider_model`,
  `save_provider_thinking_level`, `upsert_saved_provider`,
  `save_catalog_entries`, `save_catalog_preferences`). `load_provider_settings`
  builds settings from the catalog only. In-session model/thinking switches
  apply to the current session and are never written anywhere.
- `scoped_models` - removed. Ctrl+P cycles every model across all providers
  with usable credentials: default provider first with its default model, then
  its remaining models, then each other provider's default model and models.
  The `/scoped-models` command, the picker's scoped tab, and
  `ScopedModelConfig` are gone.
- `~/.tau/tui.json` - gone. `thinking_cycle` now defaults to `ctrl+f`, and the
  theme applies for the current session only. `TuiSettings`/`TuiKeybindings`
  remain as in-memory defaults; `tui_settings_from_json` stays as a pure
  parser.
- `~/.tau/skills/` - user skills now load from `~/.claude/skills` (via
  `TauResourcePaths.claude_home`, defaulting to `Path.home() / ".claude"`).
- `~/.tau/cache/` - the release-notes state file moved to
  `~/.tau/logs/release-notes-state.json`.

After this refactor `~/.tau` contains only: `logs/`, `sessions/`,
`credentials.json`, `trust.json`, and `trust.json.lock` (plus any optional
user resources the user creates, such as `prompts/`, `themes/`, `SYSTEM.md`).

## Why

Zero-config startup: a fresh clone/install of Tau works immediately with the
packaged catalog, no `~/.tau` scaffolding required. The catalog is the single
source of truth that nothing can override at runtime: `/login` stores
credentials (which should not be committed to git) in `~/.tau/credentials.json`
and nothing else, and the only way to change provider defaults is to edit
`src/tau_coding/data/catalog.toml` by hand (or `tau setup`, which prints the
TOML block to paste instead of writing it).

## How it maps to the design

- `catalog_loader.py` still owns TOML parsing/validation but now resolves one
  catalog path: `TauPaths.catalog_path` when set, else `$TAU_CATALOG_PATH`,
  else the packaged `tau_coding/data/catalog.toml`. The overlay merge code and
  the catalog writers (`save_catalog_entries`, `save_catalog_preferences`)
  were deleted; the file is read-only for Tau.
- `provider_config.py` keeps the `ProviderSettings` model and all runtime
  config builders, minus every persistence entry point (providers.json layer,
  upserts, in-memory preference mutation helpers).
- `session.py` gained `cycle_model`/`model_cycle_choices`; the TUI calls them
  from the Ctrl+P binding. Model and thinking switches never write to disk.
- `/login` (including `/login custom`) stores the credential in
  `~/.tau/credentials.json` and nothing else; `tau setup` prints the TOML
  block to add to the catalog instead of writing it.

## Automation

- Tests point at an isolated catalog through `TauPaths(catalog_path=...)` or
  the `TAU_CATALOG_PATH` env var. An autouse conftest fixture
  (`isolate_catalog_file`) seeds a per-test catalog copy outside `tmp_path` so
  no test can rewrite the packaged file.
- `TAU_CATALOG_PATH` is also the escape hatch for read-only installations: set
  it to a writable catalog file.

## How to test

- `uv run pytest` (excluding
  `tests/test_package_metadata.py::test_wheel_includes_release_notes_package_data`,
  which requires registry access for `uv build`).
- Manual: delete `~/.tau` config files (`catalog.toml`, `providers.json`,
  `providers.json.bak`, `tui.json`, `skills/`, `cache/`) and run `tau`;
  providers load from the packaged catalog and skills appear from
  `~/.claude/skills`. Press Ctrl+P to cycle all models and Ctrl+F to cycle
  thinking. Edit `src/tau_coding/data/catalog.toml` to change the default
  provider (`openai-codex`, default model `gpt-5.6-sol`) or any provider
  preference; session switches never persist.