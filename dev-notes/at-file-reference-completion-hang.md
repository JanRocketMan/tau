# `@` file-reference completion hang on large workspaces

## What changed

`src/tau_coding/tui/autocomplete.py` now bounds and amortizes the filesystem
walk behind `@` file-reference completions. The walk:

- stops after `FILE_REFERENCE_WALK_BUDGET` (2500) examined entries
- is lazy, so the 50-item suggestion cap in `_file_reference_completions` stops
  it early instead of forcing a full traversal
- never descends into symlinked directories
- is cached per cwd for `FILE_REFERENCE_CACHE_TTL_SECONDS` (3.0s)

The cache stores precomputed `_FileReferenceEntry` values (relative path,
lowercased relative path, directory flag), so the per-keystroke filter loop only
does in-memory string comparisons.

## Why it exists

The prompt's `on_text_area_changed` handler in `app.py` rebuilds the completion
state synchronously on the Textual UI thread for every keystroke. On `@`, that
called `_iter_file_reference_paths`, which walked the entire workspace tree and
only then filtered the results against the typed prefix.

Measured on a synthetic 24k-file repo: each keystroke blocked the UI for ~0.7s.
On real big repos (hundreds of thousands of files) that is multi-second freezes,
which reads as a hang. A second defect: the walk followed directory symlinks
with no cycle guard, so a single `link -> .` loop expanded into ~120 duplicate
garbage entries (bounded only by the kernel's 40-symlink cap on Linux) and
re-walked monorepo-style symlink farms once per link.

## How it maps to Pi's design

Completion is a UI-layer concern; the fix stays entirely inside the
`tau_coding.tui` autocomplete helper. `build_completion_state` keeps its pure
signature, the app keeps its per-keystroke call, and the agent harness is
untouched.

## How to test

```bash
uv run pytest tests/test_tui_autocomplete.py
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

Regression tests cover budget bounding, symlink-cycle safety, symlinked dirs
being listed without being descended into, and per-cwd cache reuse.

## Trade-offs

- A prefix that matches nothing still scans up to 2500 entries, but only on the
  first `@` keystroke in a cwd; the cache absorbs the rest of the keystrokes.
- Newly created files take up to 3.0s to appear in `@` completions.
- Very deep, alphabetically-late matches can be missed when the walk budget
  expires before reaching them. This is graceful degradation; the alternative
  was blocking the UI.
- A single directory with a huge number of entries (hundreds of thousands)
  still pays one `sorted()` per cache miss; the budget bounds the per-entry
  scan. Offloading the walk to a Textual worker remains a possible follow-up if
  that edge case shows up in practice.