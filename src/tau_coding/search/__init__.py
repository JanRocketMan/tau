"""Provider-agnostic web search for Tau coding sessions.

The optional `search` tool sends a model query to a configurable web-search
provider. Tau ships two providers:

- `parallel` (default): the Parallel Search API, using Fast mode by default
  for a one-second latency budget.
- `brave`: the Brave Web Search API, kept for users migrating.

Selection and configuration happen at session startup through environment
variables (see `tau_coding.search.config`). The provider classes implement the
`SearchProvider` interface from `tau_coding.search.base` so new backends can be
added without touching the tool executor, rendering, or session code.
"""

from __future__ import annotations

from tau_coding.search.base import (
    DEFAULT_TIMEOUT_SECONDS,
    MAX_ERROR_BODY_CHARS,
    MAX_QUERY_CHARS,
    MAX_QUERY_WORDS,
    ParsedSearch,
    PreparedRequest,
    SearchProvider,
    common_argument_properties,
    common_query_params,
    format_results,
    normalize_result,
    run_search,
    split_freshness_range,
)
from tau_coding.search.brave import (
    BRAVE_SEARCH_ENDPOINT,
    BraveSearchConfig,
    BraveSearchProvider,
    run_brave_search,
)
from tau_coding.search.config import (
    DEFAULT_SEARCH_PROVIDER,
    SEARCH_PROVIDER_ENV,
    SEARCH_PROVIDERS,
    SearchConfig,
    current_default_provider,
    search_provider_names,
)
from tau_coding.search.parallel import (
    DEFAULT_PARALLEL_MODE,
    PARALLEL_MODES,
    PARALLEL_SEARCH_ENDPOINT,
    ParallelSearchConfig,
    ParallelSearchProvider,
)

__all__ = [
    "BRAVE_SEARCH_ENDPOINT",
    "BraveSearchConfig",
    "BraveSearchProvider",
    "DEFAULT_PARALLEL_MODE",
    "DEFAULT_SEARCH_PROVIDER",
    "DEFAULT_TIMEOUT_SECONDS",
    "MAX_ERROR_BODY_CHARS",
    "MAX_QUERY_CHARS",
    "MAX_QUERY_WORDS",
    "PARALLEL_MODES",
    "PARALLEL_SEARCH_ENDPOINT",
    "ParsedSearch",
    "ParallelSearchConfig",
    "ParallelSearchProvider",
    "PreparedRequest",
    "SEARCH_PROVIDER_ENV",
    "SEARCH_PROVIDERS",
    "SearchConfig",
    "SearchProvider",
    "common_argument_properties",
    "common_query_params",
    "current_default_provider",
    "format_results",
    "normalize_result",
    "run_brave_search",
    "run_search",
    "search_provider_names",
    "split_freshness_range",
]
