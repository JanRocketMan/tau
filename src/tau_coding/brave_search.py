"""Legacy Brave Search API module, kept for backward compatibility.

Tau's web search is now provider-agnostic and defaults to the Parallel Search
API. The provider-neutral core, the `SearchConfig` selection layer, and the
Brave provider live in `tau_coding.search`. This module re-exports the Brave
pieces that older call sites (`BraveSearchConfig`, `run_brave_search`,
`BRAVE_SEARCH_ENDPOINT`) import directly so existing code keeps working during
the transition.

New code should import from `tau_coding.search`; do not grow this module.
"""

from __future__ import annotations

from tau_coding.search.brave import (
    BRAVE_SEARCH_ENDPOINT,
    BraveSearchConfig,
    BraveSearchProvider,
    run_brave_search,
)

__all__ = [
    "BRAVE_SEARCH_ENDPOINT",
    "BraveSearchConfig",
    "BraveSearchProvider",
    "run_brave_search",
]
