# Provider-agnostic web search (Parallel default)

Tau's optional search tool moved from a Brave-only `brave_search` tool to a
provider-agnostic `search` tool that defaults to the Parallel Search API in
Fast mode. Brave remains available as a migration alternative, and the old
`brave_search` factory/names still work.

## What was added

- `src/tau_coding/search/` is the new provider-agnostic core:
  - `search/base.py` defines the `SearchProvider` interface (argument schema,
    `prepare`, `parse`, error messages), the shared `PreparedRequest` /
    `ParsedSearch` shapes, common argument validation, the neutral text
    renderer, the key-redacting error-body helper, and the `run_search`
    executor that maps operational failures to bounded error results.
  - `search/parallel.py` ships the new default provider. `ParallelSearchConfig`
    reads `PARALLEL_SEARCH_API_KEY` (with `PARALLEL_API_KEY` fallback),
    `PARALLEL_SEARCH_API_URL`, `PARALLEL_SEARCH_TIMEOUT_SECONDS`, and
    `PARALLEL_SEARCH_MODE` (default `fast`). The provider sends
    `POST /v1/search` with `objective`, `search_queries`, `mode`, and
    `advanced_settings` (`max_results`, `location`, `source_policy` date
    range), and normalizes `V1WebSearchResult` items (title, URL, first excerpt
    as snippet, remaining excerpts, publish date).
  - `search/brave.py` contains the Brave provider, moved from the old module.
  - `search/config.py` implements `SearchConfig.from_env()`: `TAU_SEARCH_PROVIDER`
    selects `parallel` or `brave`; the catalog's `default_search_provider`
    decides when the env var is unset. When selection is unset and only a
    Brave key is configured, it falls back to Brave so existing users keep
    searching during the transition.
- `src/tau_coding/brave_search.py` is now a thin backward-compatible shim that
  re-exports `BraveSearchConfig`, `BraveSearchProvider`, `run_brave_search`, and
  `BRAVE_SEARCH_ENDPOINT`. New code should import from `tau_coding.search`.
- `src/tau_coding/tools.py` gained `create_search_tool(config: SearchConfig)`
  and changed `create_coding_tools` to take `search=`; `create_brave_search_tool`
  stays as a legacy Brave-pinned helper with the historical `brave_search` name.
- `CodingSessionConfig.brave_search` became `CodingSessionConfig.search`; both
  entry edges (`cli.py`, `tui/app.py`) resolve it once via
  `SearchConfig.from_env()`.
- `catalog.toml` now carries a `default_search_provider` root key and
  `[[search_providers]]` tables (name, display name, API key env var, endpoint,
  docs URL, supported modes, default mode, timeout env var). `catalog_loader.py`
  parses them into `SearchCatalogEntry` and exposes `builtin_search_catalog()`,
  `effective_search_catalog()`, and `default_search_provider()`; the user-level
  catalog overlay merges and overrides them like the LLM provider catalog.

## Why it exists

Web search is opt-in because it creates a new outbound data path: the model's
query text is sent to the configured provider. The tool stays disabled unless
the selected provider's API key is present. Making the tool provider-agnostic
keeps the harness and the tool factory independent of any single service, so
adding a backend is one new provider class plus a catalog entry.

Design choices worth knowing:

- The tool's model-visible schema is the neutral intersection (`query`,
  `count`, `country`, `freshness`). Provider-specific knobs (Parallel mode,
  Brave safesearch/spellcheck toggles) live in configuration, not in the tool
  arguments, so prompts and schemas stay stable across backends.
- The key is process configuration, never a model-visible tool argument, and is
  defensively redacted from error bodies before they reach the model or session
  history.
- Invalid arguments raise `ValueError` before any network access; operational
  failures (timeout, transport error, HTTP 401/403/422/429/5xx, malformed JSON)
  return bounded error results so the model can recover. There are no automatic
  retries, so a 429 cannot turn into a quota-burning loop.
- The default mode is `fast`: per Parallel's docs, Fast mode gives high quality
  search within a one-second latency budget.
- `SearchConfig.from_env()` consults the catalog for the default provider, so
  editing `default_search_provider` (built-in or user `~/.tau/catalog.toml`)
  changes the out-of-the-box backend without code changes.

## How to test or use it

```bash
export PARALLEL_SEARCH_API_KEY="..."      # required for the default provider
export TAU_SEARCH_PROVIDER=parallel        # optional; catalog default wins
tau                                       # or: tau --print "..."
```

To keep using Brave during migration:

```bash
export TAU_SEARCH_PROVIDER=brave
export BRAVE_SEARCH_API_KEY="..."
```

Automated coverage lives in `tests/test_search.py` (Parallel provider, config
resolution, catalog entries, provider-agnostic executor) and
`tests/test_brave_search.py` (Brave provider through the legacy helpers). All
HTTP traffic runs through `httpx.MockTransport` (no network, no quota).
