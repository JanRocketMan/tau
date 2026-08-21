"""Load Tau's provider catalog from the packaged TOML file.

The packaged ``src/tau_coding/data/catalog.toml`` is Tau's single source of
provider configuration. It carries the default provider, provider display
labels, full provider definitions, per-provider runtime preferences, and the
web-search providers used by the optional ``search`` tool. Tau only reads the
catalog; edit the file directly to change providers or preferences.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from importlib.resources import files
from os import environ
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StringConstraints,
    ValidationError,
)

from tau_agent.types import JSONValue
from tau_coding.paths import TauPaths
from tau_coding.provider_catalog import (
    DEFAULT_SEARCH_PROVIDER,
    AuthMethod,
    ModelCatalogMetadata,
    ModelCostTier,
    ModelInput,
    ProviderApi,
    ProviderCatalogEntry,
    ProviderKind,
    SearchCatalogEntry,
)
from tau_coding.thinking import ThinkingLevel, ThinkingParameter

CATALOG_SCHEMA_VERSION = 1

_NonEmptyString = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1),
]
_NonEmptyStringTuple = Annotated[tuple[_NonEmptyString, ...], Field(min_length=1)]
_PositiveInt = Annotated[StrictInt, Field(gt=0)]
_NonNegativeInt = Annotated[StrictInt, Field(ge=0)]
_PositiveFloat = Annotated[float, Field(gt=0)]
_NonNegativeFloat = Annotated[float, Field(ge=0)]


class CatalogError(ValueError):
    """Raised when a Tau catalog file is invalid."""


class _CatalogCostTier(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_input_tokens: _PositiveInt | None = None
    input: _NonNegativeFloat
    output: _NonNegativeFloat
    cacheRead: _NonNegativeFloat
    cacheWrite: _NonNegativeFloat
    # Optional 1-hour TTL cache-write rate (Anthropic bills those above the
    # 5-minute cacheWrite rate). Omitted from the cost dict when unset so
    # consumers can fall back to cacheWrite.
    cacheWrite1h: _NonNegativeFloat | None = None


class _CatalogModelMetadata(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: _NonEmptyString | None = None
    api: ProviderApi | None = None
    base_url: _NonEmptyString | None = None
    reasoning: StrictBool | None = None
    input: tuple[ModelInput, ...] = ()
    cost: dict[_NonEmptyString, _NonNegativeFloat] | None = None
    cost_tiers: tuple[_CatalogCostTier, ...] = ()
    context_window: _PositiveInt | None = None
    max_tokens: _PositiveInt | None = None
    thinking_default: ThinkingLevel | None = None
    thinking_levels: tuple[ThinkingLevel, ...] = ()
    headers: dict[_NonEmptyString, _NonEmptyString] = {}
    compat: dict[_NonEmptyString, Any] = {}


class _CatalogProvider(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: _NonEmptyString
    display_name: _NonEmptyString
    kind: ProviderKind
    base_url: _NonEmptyString
    api_key_env: _NonEmptyString
    credential_name: _NonEmptyString | None = None
    models: _NonEmptyStringTuple
    default_model: _NonEmptyString
    docs_url: _NonEmptyString
    api: ProviderApi | None = None
    context_windows: dict[_NonEmptyString, _PositiveInt] | None = None
    headers: dict[_NonEmptyString, _NonEmptyString] = {}
    compat: dict[_NonEmptyString, Any] = {}
    model_metadata: dict[_NonEmptyString, _CatalogModelMetadata] = {}
    thinking_parameter: ThinkingParameter | None = None
    removed_models: tuple[_NonEmptyString, ...] = ()
    auth_methods: tuple[AuthMethod, ...] = ("api_key",)
    timeout_seconds: _PositiveFloat | None = None
    stream_idle_timeout_seconds: _PositiveFloat | None = None
    max_retries: _NonNegativeInt | None = None
    max_retry_delay_seconds: _NonNegativeFloat | None = None
    thinking_defaults: dict[_NonEmptyString, ThinkingLevel] = {}
    inference_providers: dict[_NonEmptyString, _NonEmptyString] = {}


class _CatalogSearchProvider(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: _NonEmptyString
    display_name: _NonEmptyString
    api_key_env: _NonEmptyString
    endpoint: _NonEmptyString
    docs_url: _NonEmptyString
    modes: tuple[_NonEmptyString, ...] = ()
    default_mode: _NonEmptyString | None = None
    timeout_env: _NonEmptyString | None = None


class _CatalogFile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1]
    default_provider: _NonEmptyString | None = None
    provider_labels: dict[_NonEmptyString, _NonEmptyString] = {}
    providers: tuple[_CatalogProvider, ...] = ()
    default_search_provider: _NonEmptyString | None = None
    search_providers: tuple[_CatalogSearchProvider, ...] = ()


def builtin_catalog_resource_text() -> str:
    """Return the packaged builtin catalog TOML text."""
    return files("tau_coding").joinpath("data/catalog.toml").read_text(encoding="utf-8")


def catalog_path(paths: TauPaths | None = None) -> Path:
    """Return the single catalog file path.

    Tau keeps one catalog file: the packaged ``data/catalog.toml``. Callers
    that need an isolated catalog (tests, sandboxes) can point
    ``TauPaths.catalog_path`` at another file, or set the
    ``TAU_CATALOG_PATH`` environment variable to redirect every read and
    write (useful when the package directory is not writable).
    """
    resolved = paths or TauPaths()
    if resolved.catalog_path is not None:
        return resolved.catalog_path
    override = environ.get("TAU_CATALOG_PATH")
    if override:
        return Path(override)
    return Path(files("tau_coding").joinpath("data/catalog.toml").__fspath__())


def builtin_catalog() -> tuple[ProviderCatalogEntry, ...]:
    """Return the packaged catalog entries."""
    path = catalog_path()
    raw = _raw_catalog(path)
    filtered = _apply_model_tombstones(raw, base=raw)
    return _entries_from_raw(filtered, source=str(path))


def builtin_search_catalog() -> tuple[SearchCatalogEntry, ...]:
    """Return the packaged search-provider catalog."""
    path = catalog_path()
    return _search_entries_from_raw(_raw_catalog(path), source=str(path))


def effective_catalog(paths: TauPaths | None = None) -> tuple[ProviderCatalogEntry, ...]:
    """Return catalog entries from the single catalog file."""
    path = catalog_path(paths)
    raw = _raw_catalog(path)
    filtered = _apply_model_tombstones(raw, base=raw)
    return _entries_from_raw(filtered, source=str(path))


def effective_search_catalog(
    paths: TauPaths | None = None,
) -> tuple[SearchCatalogEntry, ...]:
    """Return search-provider catalog entries from the single catalog file."""
    path = catalog_path(paths)
    return _search_entries_from_raw(_raw_catalog(path), source=str(path))


def default_search_provider(paths: TauPaths | None = None) -> str:
    """Return the configured default web-search provider name.

    Reads the ``default_search_provider`` root key from the catalog file and
    falls back to `DEFAULT_SEARCH_PROVIDER` when it is absent.
    """
    path = catalog_path(paths)
    name = _raw_catalog(path).get("default_search_provider")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return DEFAULT_SEARCH_PROVIDER


def default_provider_name(paths: TauPaths | None = None) -> str | None:
    """Return the configured default provider name from the catalog file."""
    path = catalog_path(paths)
    name = _raw_catalog(path).get("default_provider")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return None


def effective_provider_labels(paths: TauPaths | None = None) -> dict[str, str]:
    """Return configured provider display labels keyed by canonical provider ID."""
    path = catalog_path(paths)
    raw = _raw_catalog(path)
    provider_labels = raw.get("provider_labels", {})
    if not isinstance(provider_labels, dict):
        raise CatalogError(f"{path}: provider_labels must be a table")
    labels: dict[str, str] = {}
    for provider_name, label in provider_labels.items():
        if not isinstance(provider_name, str) or not provider_name.strip():
            raise CatalogError(f"{path}: provider_labels keys must be non-empty strings")
        if not isinstance(label, str) or not label.strip():
            raise CatalogError(
                f"{path}: provider_labels.{provider_name} must be a non-empty string"
            )
        labels[provider_name.strip()] = label.strip()
    provider_names = {entry.name for entry in effective_catalog(paths)}
    _validate_provider_labels(labels, provider_names=provider_names, source=str(path))
    return labels


def _raw_catalog(path: Path) -> dict[str, Any]:
    """Return parsed catalog TOML data for one catalog file path."""
    if not path.exists():
        return {"schema_version": CATALOG_SCHEMA_VERSION, "providers": []}
    return _parse_catalog_text(path.read_text(encoding="utf-8"), source=str(path))


def _parse_catalog_text(text: str, *, source: str) -> dict[str, Any]:
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise CatalogError(f"{source}: invalid TOML: {error}") from error


def _validate_catalog_root(raw: dict[str, Any], *, source: str) -> None:
    allowed = {
        "schema_version",
        "default_provider",
        "provider_labels",
        "providers",
        "default_search_provider",
        "search_providers",
    }
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise CatalogError(f"{source}: unknown catalog keys: {', '.join(unknown)}")
    if "schema_version" not in raw:
        raise CatalogError(f"{source}: schema_version is required")
    if raw["schema_version"] != CATALOG_SCHEMA_VERSION:
        raise CatalogError(f"{source}: unsupported schema_version: {raw['schema_version']!r}")
    default_provider = raw.get("default_provider")
    if default_provider is not None and (
        not isinstance(default_provider, str) or not default_provider.strip()
    ):
        raise CatalogError(f"{source}: default_provider must be a non-empty string")
    _raw_providers(raw)


def _apply_model_tombstones(
    raw: dict[str, Any],
    *,
    base: dict[str, Any],
) -> dict[str, Any]:
    """Remove provider-scoped models withdrawn by the catalog."""
    base_by_name = {_raw_provider_name(provider): provider for provider in _raw_providers(base)}
    providers: list[dict[str, Any]] = []
    for provider in _raw_providers(raw):
        removed = {model for model in provider.get("removed_models", []) if isinstance(model, str)}
        if not removed:
            providers.append(provider)
            continue
        filtered = {**provider}
        for field in ("models",):
            values = filtered.get(field)
            if isinstance(values, list):
                filtered[field] = [model for model in values if model not in removed]
        for field in (
            "context_windows",
            "model_metadata",
            "thinking_defaults",
            "inference_providers",
        ):
            values = filtered.get(field)
            if isinstance(values, dict):
                filtered[field] = {
                    model: value for model, value in values.items() if model not in removed
                }
        if filtered.get("default_model") in removed:
            name = _raw_provider_name(provider)
            base_default = base_by_name.get(name, {}).get("default_model")
            remaining = filtered.get("models", [])
            filtered["default_model"] = (
                base_default
                if isinstance(base_default, str) and base_default not in removed
                else remaining[0]
                if isinstance(remaining, list) and remaining
                else ""
            )
        providers.append(filtered)
    return {**raw, "providers": providers}


def _raw_providers(raw: dict[str, Any]) -> list[dict[str, Any]]:
    providers = raw.get("providers", [])
    if not isinstance(providers, list) or not all(isinstance(item, dict) for item in providers):
        raise CatalogError("catalog providers must be an array of tables ([[providers]])")
    return providers


def _raw_search_providers(raw: dict[str, Any]) -> list[dict[str, Any]]:
    entries = raw.get("search_providers", [])
    if not entries:
        return []
    if not isinstance(entries, list) or not all(isinstance(item, dict) for item in entries):
        raise CatalogError(
            "catalog search_providers must be an array of tables ([[search_providers]])"
        )
    return entries


def _raw_provider_name(provider: dict[str, Any]) -> str:
    name = provider.get("name")
    if not isinstance(name, str) or not name.strip():
        raise CatalogError("catalog provider entries must have a non-empty string name")
    return name.strip()


def _entries_from_raw(raw: dict[str, Any], *, source: str) -> tuple[ProviderCatalogEntry, ...]:
    try:
        catalog = _CatalogFile.model_validate(raw)
    except ValidationError as error:
        raise CatalogError(f"{source}: {_format_validation_error(raw, error)}") from error
    entries = tuple(_entry_from_provider(provider, source=source) for provider in catalog.providers)
    names = [entry.name for entry in entries]
    if len(set(names)) != len(names):
        duplicates = sorted({name for name in names if names.count(name) > 1})
        raise CatalogError(f"{source}: duplicate provider names: {', '.join(duplicates)}")
    _validate_provider_labels(
        catalog.provider_labels,
        provider_names=set(names),
        source=source,
    )
    if catalog.default_provider is not None and catalog.default_provider not in names:
        raise CatalogError(
            f"{source}: default_provider {catalog.default_provider!r} is not among providers"
        )
    return entries


def _search_entries_from_raw(raw: dict[str, Any], *, source: str) -> tuple[SearchCatalogEntry, ...]:
    """Build validated search provider entries from raw catalog data."""
    try:
        catalog = _CatalogFile.model_validate(raw)
    except ValidationError as error:
        raise CatalogError(f"{source}: {_format_validation_error(raw, error)}") from error

    entries = tuple(
        _search_entry_from_provider(provider, source=source)
        for provider in catalog.search_providers
    )
    names = [entry.name for entry in entries]
    if len(set(names)) != len(names):
        duplicates = sorted({name for name in names if names.count(name) > 1})
        raise CatalogError(f"{source}: duplicate search provider names: {', '.join(duplicates)}")
    _validate_search_default(catalog.default_search_provider, names, source=source)
    return entries


def _validate_search_default(default: str | None, search_names: list[str], *, source: str) -> None:
    """Reject a default search provider that has no matching catalog entry."""
    if default is None:
        return
    if not search_names:
        raise CatalogError(f"{source}: default_search_provider {default!r} has no search_providers")
    if default not in search_names:
        joined = ", ".join(search_names)
        raise CatalogError(
            f"{source}: default_search_provider {default!r} is not among search_providers: {joined}"
        )


def _search_entry_from_provider(
    provider: _CatalogSearchProvider, *, source: str
) -> SearchCatalogEntry:
    prefix = f"{source}: search_providers.{provider.name}"
    if provider.default_mode is not None and provider.default_mode not in provider.modes:
        raise CatalogError(f"{prefix}.default_mode: {provider.default_mode!r} is not in modes")
    if provider.default_mode is None and provider.modes:
        raise CatalogError(f"{prefix}.default_mode: is required when modes is declared")
    return SearchCatalogEntry(
        name=provider.name,
        display_name=provider.display_name,
        api_key_env=provider.api_key_env,
        endpoint=provider.endpoint,
        docs_url=provider.docs_url,
        modes=provider.modes,
        default_mode=provider.default_mode,
        timeout_env=provider.timeout_env,
    )


def _validate_provider_labels(
    labels: Mapping[str, str],
    *,
    provider_names: set[str],
    source: str,
) -> None:
    """Reject ambiguous display labels while keeping provider IDs unchanged."""
    unknown = sorted(set(labels) - provider_names)
    if unknown:
        raise CatalogError(
            f"{source}: provider_labels contains unknown providers: {', '.join(unknown)}"
        )
    label_counts: dict[str, int] = {}
    for label in labels.values():
        label_counts[label] = label_counts.get(label, 0) + 1
    duplicates = sorted(label for label, count in label_counts.items() if count > 1)
    if duplicates:
        raise CatalogError(
            f"{source}: provider_labels contains duplicate labels: {', '.join(duplicates)}"
        )
    conflicts = sorted(
        provider_name
        for provider_name, label in labels.items()
        if label in provider_names and label != provider_name
    )
    if conflicts:
        raise CatalogError(
            f"{source}: provider_labels conflicts with canonical provider IDs: "
            f"{', '.join(conflicts)}"
        )


def _entry_from_provider(provider: _CatalogProvider, *, source: str) -> ProviderCatalogEntry:
    prefix = f"{source}: providers.{provider.name}"
    if provider.default_model not in provider.models:
        raise CatalogError(f"{prefix}.default_model: {provider.default_model!r} is not in models")
    for model in provider.context_windows or {}:
        if model not in provider.models:
            raise CatalogError(f"{prefix}.context_windows: {model!r} is not in models")
    for model in provider.model_metadata:
        if model not in provider.models:
            raise CatalogError(f"{prefix}.model_metadata: {model!r} is not in models")
    for model in provider.thinking_defaults:
        if model not in provider.models:
            raise CatalogError(f"{prefix}.thinking_defaults: {model!r} is not in models")
        metadata = provider.model_metadata.get(model)
        if (
            metadata is not None
            and metadata.thinking_levels
            and provider.thinking_defaults[model] not in metadata.thinking_levels
        ):
            raise CatalogError(
                f"{prefix}.thinking_defaults.{model}: "
                f"{provider.thinking_defaults[model]!r} is not in thinking_levels"
            )
    for model in provider.inference_providers:
        if model not in provider.models:
            raise CatalogError(f"{prefix}.inference_providers: {model!r} is not in models")

    for model, catalog_metadata in provider.model_metadata.items():
        _validate_cost_tiers(
            catalog_metadata.cost_tiers,
            field_name=f"{prefix}.model_metadata.{model}",
        )
        if not catalog_metadata.thinking_levels:
            raise CatalogError(
                f"{prefix}.model_metadata.{model}.thinking_levels: "
                "must declare at least one thinking level"
            )
        if catalog_metadata.reasoning is False:
            raise CatalogError(
                f"{prefix}.model_metadata.{model}.reasoning: "
                "cannot be false when thinking_levels is set"
            )
        if catalog_metadata.thinking_default is None:
            raise CatalogError(
                f"{prefix}.model_metadata.{model}.thinking_default: "
                "is required when thinking_levels is set"
            )
        if catalog_metadata.thinking_default not in catalog_metadata.thinking_levels:
            raise CatalogError(
                f"{prefix}.model_metadata.{model}.thinking_default: "
                f"{catalog_metadata.thinking_default!r} is not in thinking_levels"
            )

    model_metadata = {
        model: _model_metadata_from_provider(metadata)
        for model, metadata in provider.model_metadata.items()
    }
    context_windows = dict(provider.context_windows or {})
    for model, metadata in model_metadata.items():
        if metadata.context_window is not None and model not in context_windows:
            context_windows[model] = metadata.context_window

    return ProviderCatalogEntry(
        name=provider.name,
        display_name=provider.display_name,
        kind=provider.kind,
        base_url=provider.base_url,
        api_key_env=provider.api_key_env,
        credential_name=provider.credential_name,
        models=provider.models,
        default_model=provider.default_model,
        docs_url=provider.docs_url,
        api=provider.api,
        context_windows=context_windows or None,
        headers=dict(provider.headers),
        compat=_json_object(provider.compat, f"{prefix}.compat"),
        model_metadata=model_metadata,
        thinking_parameter=provider.thinking_parameter,
        removed_models=provider.removed_models,
        auth_methods=provider.auth_methods,
        timeout_seconds=provider.timeout_seconds,
        stream_idle_timeout_seconds=provider.stream_idle_timeout_seconds,
        max_retries=provider.max_retries,
        max_retry_delay_seconds=provider.max_retry_delay_seconds,
        thinking_defaults=dict(provider.thinking_defaults),
        inference_providers=dict(provider.inference_providers),
    )


def _validate_cost_tiers(
    tiers: tuple[_CatalogCostTier, ...],
    *,
    field_name: str,
) -> None:
    if not tiers:
        return
    if tiers[-1].max_input_tokens is not None:
        raise CatalogError(f"{field_name}.cost_tiers: final tier must omit max_input_tokens")
    previous_limit = 0
    for index, tier in enumerate(tiers[:-1]):
        limit = tier.max_input_tokens
        if limit is None or limit <= previous_limit:
            raise CatalogError(
                f"{field_name}.cost_tiers.{index}.max_input_tokens: "
                "limits must be strictly increasing"
            )
        previous_limit = limit


def _model_metadata_from_provider(metadata: _CatalogModelMetadata) -> ModelCatalogMetadata:
    return ModelCatalogMetadata(
        name=metadata.name,
        api=metadata.api,
        base_url=metadata.base_url,
        reasoning=metadata.reasoning,
        input=metadata.input,
        cost=dict(metadata.cost) if metadata.cost else None,
        cost_tiers=tuple(
            ModelCostTier(
                max_input_tokens=tier.max_input_tokens,
                cost=_cost_tier_rates(tier),
            )
            for tier in metadata.cost_tiers
        ),
        context_window=metadata.context_window,
        max_tokens=metadata.max_tokens,
        thinking_default=metadata.thinking_default,
        thinking_levels=tuple(metadata.thinking_levels),
        headers=dict(metadata.headers),
        compat=_json_object(metadata.compat, "model_metadata.compat"),
    )


def _cost_tier_rates(tier: _CatalogCostTier) -> dict[str, float]:
    rates = {
        "input": tier.input,
        "output": tier.output,
        "cacheRead": tier.cacheRead,
        "cacheWrite": tier.cacheWrite,
    }
    if tier.cacheWrite1h is not None:
        rates["cacheWrite1h"] = tier.cacheWrite1h
    return rates


def _json_object(value: Mapping[str, Any], field_name: str) -> dict[str, JSONValue]:
    return {key: _json_value(item, f"{field_name}.{key}") for key, item in value.items()}


def _json_value(value: Any, field_name: str) -> JSONValue:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, list):
        return [_json_value(item, field_name) for item in value]
    if isinstance(value, dict):
        output: dict[str, JSONValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise CatalogError(f"{field_name}: object keys must be strings")
            output[key] = _json_value(item, f"{field_name}.{key}")
        return output
    raise CatalogError(f"{field_name}: unsupported value {value!r}")


def _format_validation_error(raw: dict[str, Any], error: ValidationError) -> str:
    messages = []
    for issue in error.errors():
        location = ".".join(_dotted_location(raw, issue["loc"]))
        messages.append(f"{location}: {issue['msg']}")
    return "; ".join(messages)


def _dotted_location(raw: dict[str, Any], location: tuple[int | str, ...]) -> list[str]:
    parts: list[str] = []
    for part in location:
        if parts and parts[-1] == "providers" and isinstance(part, int):
            providers = raw.get("providers")
            name = None
            if isinstance(providers, list) and part < len(providers):
                item = providers[part]
                if isinstance(item, dict):
                    name = item.get("name")
            parts.append(str(name) if isinstance(name, str) else str(part))
        else:
            parts.append(str(part))
    return parts
