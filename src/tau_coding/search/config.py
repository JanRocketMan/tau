"""Search provider selection and configuration for Tau coding sessions.

`SearchConfig.from_env()` resolves which provider the `search` tool uses at
session startup. The provider name comes from `TAU_SEARCH_PROVIDER` when set,
otherwise from the catalog's `default_search_provider` entry (the packaged
default is Parallel Search). When the selected provider has no API key, the
tool stays disabled. For a smooth migration, an unset `TAU_SEARCH_PROVIDER`
with only a Brave key configured falls back to the Brave provider.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from tau_coding.search.base import SearchProvider
from tau_coding.search.brave import BraveSearchConfig, BraveSearchProvider
from tau_coding.search.parallel import (
    ParallelSearchConfig,
    ParallelSearchProvider,
)

SEARCH_PROVIDER_ENV = "TAU_SEARCH_PROVIDER"
DEFAULT_SEARCH_PROVIDER = "parallel"
SEARCH_PROVIDERS = ("parallel", "brave")


@dataclass(frozen=True, slots=True)
class SearchConfig:
    """Resolved web-search configuration for one session.

    `from_env()` returns ``None`` when the selected provider is not configured,
    which disables the `search` tool. The returned object wraps the concrete
    provider so sessions and tool factories stay provider-agnostic.
    """

    provider: SearchProvider

    @property
    def provider_name(self) -> str:
        return self.provider.name

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> SearchConfig | None:
        """Build a search config from the process environment or return ``None``.

        Args:
            environ: Environment mapping to read; defaults to `os.environ`.

        Returns:
            A populated config, or ``None`` when the selected provider has no
            API key configured.

        Raises:
            ValueError: If `TAU_SEARCH_PROVIDER` names an unknown provider or a
                selected provider's environment is malformed.
        """
        env = os.environ if environ is None else environ
        explicit = env.get(SEARCH_PROVIDER_ENV, "").strip().lower()
        if explicit and explicit not in SEARCH_PROVIDERS:
            names = ", ".join(SEARCH_PROVIDERS)
            raise ValueError(f"{SEARCH_PROVIDER_ENV} must be one of: {names}")

        selected = explicit or _catalog_default_provider()
        _ensure_known(selected)

        if selected == "parallel":
            parallel_provider = _parallel_from_env(env)
            if parallel_provider is None and not explicit:
                # Migration fallback: no explicit selection and no Parallel key,
                # but a Brave key is present - keep Brave users on search.
                brave_provider = _brave_from_env(env)
                if brave_provider is not None:
                    return cls(provider=brave_provider)
            if parallel_provider is None:
                return None
            return cls(provider=parallel_provider)

        brave_provider = _brave_from_env(env)
        return cls(provider=brave_provider) if brave_provider is not None else None


def search_provider_names() -> tuple[str, ...]:
    """Return the names of all registered search providers."""
    return SEARCH_PROVIDERS


def current_default_provider() -> str:
    """Return the catalog-configured default search provider name."""
    return _catalog_default_provider()


def _ensure_known(name: str) -> None:
    if name not in SEARCH_PROVIDERS:
        names = ", ".join(SEARCH_PROVIDERS)
        raise ValueError(f"Unknown search provider: {name!r} (expected one of: {names})")


def _parallel_from_env(env: Mapping[str, str]) -> ParallelSearchProvider | None:
    config = ParallelSearchConfig.from_env(env)
    return ParallelSearchProvider(config) if config is not None else None


def _brave_from_env(env: Mapping[str, str]) -> BraveSearchProvider | None:
    config = BraveSearchConfig.from_env(env)
    return BraveSearchProvider(config) if config is not None else None


def _catalog_default_provider() -> str:
    from tau_coding.catalog_loader import default_search_provider

    name = default_search_provider().strip().lower()
    return name or DEFAULT_SEARCH_PROVIDER
