"""Provider configuration loaded from the single catalog file.

Tau never writes provider configuration: the catalog file is the single
source of truth, edited by hand. Runtime model/thinking changes apply to the
active session only, and `/login` stores credentials in
`~/.tau/credentials.json` without touching the catalog.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from os import environ
from typing import Any, Protocol
from urllib.parse import urlsplit

from tau_ai.env import (
    DEFAULT_OPENAI_COMPATIBLE_BASE_URL,
    DEFAULT_OPENAI_COMPATIBLE_MAX_RETRIES,
    DEFAULT_OPENAI_COMPATIBLE_MAX_RETRY_DELAY_SECONDS,
    DEFAULT_OPENAI_COMPATIBLE_STREAM_IDLE_TIMEOUT_SECONDS,
    DEFAULT_OPENAI_COMPATIBLE_TIMEOUT_SECONDS,
    OpenAICompatibleConfig,
)
from tau_ai.openai_codex import DEFAULT_OPENAI_CODEX_BASE_URL
from tau_coding.catalog_loader import default_provider_name, effective_catalog
from tau_coding.oauth_registry import get_oauth_provider
from tau_coding.paths import TauPaths
from tau_coding.provider_catalog import (
    BUILTIN_PROVIDER_CATALOG,
    ModelCatalogMetadata,
    ModelCostTier,
    ProviderApi,
    ProviderCatalogEntry,
    ProviderKind,
)
from tau_coding.thinking import (
    DEFAULT_THINKING_LEVEL,
    ThinkingLevel,
    ThinkingParameter,
    normalize_thinking_level,
    normalize_thinking_levels,
    reasoning_effort_for_level,
)

DEFAULT_PROVIDER_NAME = "openai-codex"
DEFAULT_MODEL = "gpt-5.6-luna"


class ProviderConfigError(ValueError):
    """Raised when Tau provider configuration is invalid."""


class CredentialReader(Protocol):
    """Credential lookup used while building runtime provider config."""

    def get(self, name: str) -> str | None: ...


@dataclass(frozen=True, slots=True)
class ProviderModelMetadata:
    """Runtime metadata for one configured model."""

    name: str | None = None
    api: ProviderApi | None = None
    base_url: str | None = None
    reasoning: bool | None = None
    input: tuple[str, ...] = ()
    cost: dict[str, float] = field(default_factory=dict)
    cost_tiers: tuple[ModelCostTier, ...] = ()
    context_window: int | None = None
    max_tokens: int | None = None
    thinking_default: ThinkingLevel | None = None
    thinking_levels: tuple[ThinkingLevel, ...] = ()
    headers: dict[str, str] = field(default_factory=dict)
    compat: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        """Serialize this model metadata to JSON-compatible data."""
        return {
            "name": self.name,
            "api": self.api,
            "base_url": self.base_url,
            "reasoning": self.reasoning,
            "input": list(self.input),
            "cost": dict(self.cost),
            "cost_tiers": [
                {
                    **(
                        {"max_input_tokens": tier.max_input_tokens}
                        if tier.max_input_tokens is not None
                        else {}
                    ),
                    **tier.cost,
                }
                for tier in self.cost_tiers
            ],
            "context_window": self.context_window,
            "max_tokens": self.max_tokens,
            "thinking_default": self.thinking_default,
            "thinking_levels": list(self.thinking_levels),
            "headers": dict(self.headers),
            "compat": dict(self.compat),
        }


@dataclass(frozen=True, slots=True)
class OpenAICompatibleProviderConfig:
    """Durable settings for one OpenAI-compatible provider."""

    name: str
    base_url: str = DEFAULT_OPENAI_COMPATIBLE_BASE_URL
    api: ProviderApi = "openai-completions"
    api_key_env: str = "OPENAI_API_KEY"
    credential_name: str | None = None
    models: tuple[str, ...] = (DEFAULT_MODEL,)
    default_model: str = DEFAULT_MODEL
    context_windows: dict[str, int] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    compat: dict[str, Any] = field(default_factory=dict)
    model_metadata: dict[str, ProviderModelMetadata] = field(default_factory=dict)
    timeout_seconds: float = DEFAULT_OPENAI_COMPATIBLE_TIMEOUT_SECONDS
    stream_idle_timeout_seconds: float = DEFAULT_OPENAI_COMPATIBLE_STREAM_IDLE_TIMEOUT_SECONDS
    max_retries: int = DEFAULT_OPENAI_COMPATIBLE_MAX_RETRIES
    max_retry_delay_seconds: float = DEFAULT_OPENAI_COMPATIBLE_MAX_RETRY_DELAY_SECONDS
    thinking_parameter: ThinkingParameter | None = None
    thinking_defaults: dict[str, ThinkingLevel] = field(default_factory=dict)
    inference_providers: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_provider_numbers(
            timeout_seconds=self.timeout_seconds,
            stream_idle_timeout_seconds=self.stream_idle_timeout_seconds,
            max_retries=self.max_retries,
            max_retry_delay_seconds=self.max_retry_delay_seconds,
        )
        _validate_context_windows(self.context_windows)
        _validate_model_metadata(self.models, self.model_metadata)
        _validate_json_object(self.compat, "Provider compat")
        _validate_thinking_config(
            thinking_parameter=self.thinking_parameter,
        )
        _validate_thinking_defaults(self.thinking_defaults)
        _validate_inference_providers(self.name, self.models, self.inference_providers)

    def to_json(self) -> dict[str, Any]:
        """Serialize this provider config to JSON-compatible data."""
        return {
            "name": self.name,
            "type": "openai-compatible",
            "base_url": self.base_url,
            "api": self.api,
            "api_key_env": self.api_key_env,
            "credential_name": self.credential_name,
            "models": list(self.models),
            "default_model": self.default_model,
            "context_windows": dict(self.context_windows),
            "headers": dict(self.headers),
            "compat": dict(self.compat),
            "model_metadata": {
                model: metadata.to_json() for model, metadata in self.model_metadata.items()
            },
            "timeout_seconds": self.timeout_seconds,
            "stream_idle_timeout_seconds": self.stream_idle_timeout_seconds,
            "max_retries": self.max_retries,
            "max_retry_delay_seconds": self.max_retry_delay_seconds,
            "thinking_parameter": self.thinking_parameter,
            "thinking_defaults": dict(self.thinking_defaults),
            "inference_providers": dict(self.inference_providers),
        }


@dataclass(frozen=True, slots=True)
class OpenAICodexProviderConfig:
    """Durable settings for OpenAI Codex subscription OAuth."""

    name: str = "openai-codex"
    base_url: str = DEFAULT_OPENAI_CODEX_BASE_URL
    api_key_env: str = "OPENAI_CODEX_ACCESS_TOKEN"
    credential_name: str | None = "openai-codex"
    models: tuple[str, ...] = (
        "gpt-5.5",
        "gpt-5.4",
        "gpt-5.4-mini",
        "gpt-5.3-codex",
        "gpt-5.3-codex-spark",
        "gpt-5.2",
    )
    default_model: str = "gpt-5.5"
    context_windows: dict[str, int] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    model_metadata: dict[str, ProviderModelMetadata] = field(default_factory=dict)
    timeout_seconds: float = DEFAULT_OPENAI_COMPATIBLE_TIMEOUT_SECONDS
    stream_idle_timeout_seconds: float = DEFAULT_OPENAI_COMPATIBLE_STREAM_IDLE_TIMEOUT_SECONDS
    max_retries: int = DEFAULT_OPENAI_COMPATIBLE_MAX_RETRIES
    max_retry_delay_seconds: float = DEFAULT_OPENAI_COMPATIBLE_MAX_RETRY_DELAY_SECONDS
    thinking_parameter: ThinkingParameter | None = None
    thinking_defaults: dict[str, ThinkingLevel] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_provider_numbers(
            timeout_seconds=self.timeout_seconds,
            stream_idle_timeout_seconds=self.stream_idle_timeout_seconds,
            max_retries=self.max_retries,
            max_retry_delay_seconds=self.max_retry_delay_seconds,
        )
        _validate_context_windows(self.context_windows)
        _validate_model_metadata(self.models, self.model_metadata)
        _validate_thinking_config(
            thinking_parameter=self.thinking_parameter,
        )
        _validate_thinking_defaults(self.thinking_defaults)

    def to_json(self) -> dict[str, Any]:
        """Serialize this provider config to JSON-compatible data."""
        return {
            "name": self.name,
            "type": "openai-codex",
            "base_url": self.base_url,
            "api_key_env": self.api_key_env,
            "credential_name": self.credential_name,
            "models": list(self.models),
            "default_model": self.default_model,
            "context_windows": dict(self.context_windows),
            "headers": dict(self.headers),
            "model_metadata": {
                model: metadata.to_json() for model, metadata in self.model_metadata.items()
            },
            "timeout_seconds": self.timeout_seconds,
            "stream_idle_timeout_seconds": self.stream_idle_timeout_seconds,
            "max_retries": self.max_retries,
            "max_retry_delay_seconds": self.max_retry_delay_seconds,
            "thinking_parameter": self.thinking_parameter,
            "thinking_defaults": dict(self.thinking_defaults),
        }


type ProviderConfig = OpenAICompatibleProviderConfig | OpenAICodexProviderConfig


def _catalog_timeout_seconds(entry: ProviderCatalogEntry) -> float:
    return (
        entry.timeout_seconds
        if entry.timeout_seconds is not None
        else DEFAULT_OPENAI_COMPATIBLE_TIMEOUT_SECONDS
    )


def _catalog_stream_idle_timeout_seconds(entry: ProviderCatalogEntry) -> float:
    return (
        entry.stream_idle_timeout_seconds
        if entry.stream_idle_timeout_seconds is not None
        else DEFAULT_OPENAI_COMPATIBLE_STREAM_IDLE_TIMEOUT_SECONDS
    )


def _catalog_max_retries(entry: ProviderCatalogEntry) -> int:
    if entry.max_retries is not None:
        return entry.max_retries
    return DEFAULT_OPENAI_COMPATIBLE_MAX_RETRIES


def _catalog_max_retry_delay_seconds(entry: ProviderCatalogEntry) -> float:
    return (
        entry.max_retry_delay_seconds
        if entry.max_retry_delay_seconds is not None
        else DEFAULT_OPENAI_COMPATIBLE_MAX_RETRY_DELAY_SECONDS
    )


@dataclass(frozen=True, slots=True)
class ProviderSettings:
    """Tau provider settings loaded from the single catalog file."""

    default_provider: str = DEFAULT_PROVIDER_NAME
    providers: tuple[ProviderConfig, ...] = field(
        default_factory=lambda: builtin_provider_configs()
    )

    def get_provider(self, name: str | None = None) -> ProviderConfig:
        """Return a configured provider by name."""
        target = name or self.default_provider
        for provider in self.providers:
            if provider.name == target:
                return provider
        raise ProviderConfigError(f"Unknown provider: {target}")


@dataclass(frozen=True, slots=True)
class ProviderSelection:
    """Resolved provider/model selection for a Tau run."""

    provider: ProviderConfig
    model: str


def builtin_provider_configs() -> tuple[ProviderConfig, ...]:
    """Return Tau's built-in provider configs."""
    return tuple(
        provider_config_from_catalog_entry(entry.name) for entry in BUILTIN_PROVIDER_CATALOG
    )


def provider_config_from_catalog_entry(name: str) -> ProviderConfig:
    """Create a durable provider config from a built-in catalog entry."""
    for entry in BUILTIN_PROVIDER_CATALOG:
        if entry.name == name:
            return provider_config_from_entry(entry)
    raise ProviderConfigError(f"Unknown built-in provider: {name}")


def provider_config_from_entry(entry: ProviderCatalogEntry) -> ProviderConfig:
    """Create a durable provider config from a catalog entry."""
    context_windows = dict(entry.context_windows or {})
    model_metadata = _provider_model_metadata_from_catalog(entry.model_metadata)
    timeout_seconds = _catalog_timeout_seconds(entry)
    stream_idle_timeout_seconds = _catalog_stream_idle_timeout_seconds(entry)
    max_retries = _catalog_max_retries(entry)
    max_retry_delay_seconds = _catalog_max_retry_delay_seconds(entry)
    thinking_defaults = dict(entry.thinking_defaults)
    if entry.kind == "openai-codex":
        return OpenAICodexProviderConfig(
            name=entry.name,
            base_url=entry.base_url,
            api_key_env=entry.api_key_env,
            credential_name=entry.credential_name,
            models=entry.models,
            default_model=entry.default_model,
            context_windows=context_windows,
            headers=dict(entry.headers),
            model_metadata=model_metadata,
            timeout_seconds=timeout_seconds,
            stream_idle_timeout_seconds=stream_idle_timeout_seconds,
            max_retries=max_retries,
            max_retry_delay_seconds=max_retry_delay_seconds,
            thinking_parameter=entry.thinking_parameter,
            thinking_defaults=thinking_defaults,
        )
    return OpenAICompatibleProviderConfig(
        name=entry.name,
        base_url=entry.base_url,
        api=entry.api or _default_api_for_kind(entry.kind),
        api_key_env=entry.api_key_env,
        credential_name=entry.credential_name,
        models=entry.models,
        default_model=entry.default_model,
        context_windows=context_windows,
        headers=dict(entry.headers),
        compat=dict(entry.compat),
        model_metadata=model_metadata,
        timeout_seconds=timeout_seconds,
        stream_idle_timeout_seconds=stream_idle_timeout_seconds,
        max_retries=max_retries,
        max_retry_delay_seconds=max_retry_delay_seconds,
        thinking_parameter=entry.thinking_parameter,
        thinking_defaults=thinking_defaults,
        inference_providers=dict(entry.inference_providers),
    )


def _default_api_for_kind(kind: str) -> ProviderApi:
    if kind == "openai-codex":
        return "openai-codex-responses"
    return "openai-completions"


def _provider_model_metadata_from_catalog(
    model_metadata: dict[str, ModelCatalogMetadata],
) -> dict[str, ProviderModelMetadata]:
    return {
        model: ProviderModelMetadata(
            name=metadata.name,
            api=metadata.api,
            base_url=metadata.base_url,
            reasoning=metadata.reasoning,
            input=tuple(metadata.input),
            cost=dict(metadata.cost or {}),
            cost_tiers=metadata.cost_tiers,
            context_window=metadata.context_window,
            max_tokens=metadata.max_tokens,
            thinking_default=metadata.thinking_default,
            thinking_levels=tuple(metadata.thinking_levels),
            headers=dict(metadata.headers),
            compat=dict(metadata.compat),
        )
        for model, metadata in model_metadata.items()
    }


def default_openai_provider_config() -> OpenAICompatibleProviderConfig:
    """Return Tau's default OpenAI-compatible provider entry."""
    provider = provider_config_from_catalog_entry(DEFAULT_PROVIDER_NAME)
    if not isinstance(provider, OpenAICompatibleProviderConfig):
        raise AssertionError("default OpenAI provider must be OpenAI-compatible")
    return provider


def load_provider_settings(paths: TauPaths | None = None) -> ProviderSettings:
    """Load provider settings from the single catalog file."""
    resolved_paths = paths or TauPaths()
    providers = _effective_provider_configs(resolved_paths)
    default_provider = default_provider_name(resolved_paths)
    if default_provider is None or default_provider not in {
        provider.name for provider in providers
    }:
        default_provider = providers[0].name if providers else DEFAULT_PROVIDER_NAME
    return ProviderSettings(default_provider=default_provider, providers=providers)


def _effective_provider_configs(paths: TauPaths | None = None) -> tuple[ProviderConfig, ...]:
    """Return provider configs from the single catalog file."""
    return tuple(provider_config_from_entry(entry) for entry in effective_catalog(paths))


def resolve_provider_selection(
    settings: ProviderSettings,
    *,
    provider_name: str | None = None,
    model: str | None = None,
) -> ProviderSelection:
    """Resolve the provider and model for a run."""
    provider = settings.get_provider(provider_name)
    selected_model = model or provider.default_model
    if not selected_model:
        raise ProviderConfigError(f"Provider {provider.name} does not define a default model")
    validate_provider_model(provider, selected_model)
    return ProviderSelection(provider=provider, model=selected_model)


def validate_provider_model(provider: ProviderConfig, model: str) -> None:
    """Raise when ``model`` is not declared by ``provider``."""
    if model in provider.models:
        return
    available = ", ".join(sorted(provider.models)) or "none"
    raise ProviderConfigError(
        f"Model is not configured for provider {provider.name}: {model}. "
        f"Available models: {available}"
    )


def provider_thinking_levels(
    provider: ProviderConfig,
    *,
    model: str | None = None,
) -> tuple[ThinkingLevel, ...]:
    """Return thinking levels supported by a provider/model pair."""
    selected_model = model or provider.default_model
    metadata = _metadata_for_model(provider, selected_model)
    if metadata is None or metadata.reasoning is False:
        return ()
    return tuple(metadata.thinking_levels)


def provider_thinking_unavailable_reason(
    provider: ProviderConfig,
    *,
    model: str | None = None,
) -> str | None:
    """Explain why a provider/model pair has no configurable thinking modes."""
    selected_model = model or provider.default_model
    metadata = _metadata_for_model(provider, selected_model)
    if metadata is None:
        return f"Provider {provider.name} does not declare thinking metadata for {selected_model}"
    if metadata.reasoning is False:
        return f"{provider.name}:{selected_model} is not a reasoning model"
    if not metadata.thinking_levels:
        return f"{provider.name}:{selected_model} does not declare thinking_levels"
    return None


def _metadata_for_model(provider: ProviderConfig, model: str) -> ProviderModelMetadata | None:
    return getattr(provider, "model_metadata", {}).get(model)


def _provider_api(provider: ProviderConfig, model: str | None = None) -> ProviderApi | str:
    selected_model = model or provider.default_model
    metadata = _metadata_for_model(provider, selected_model)
    if metadata is not None and metadata.api is not None:
        return metadata.api
    if isinstance(provider, OpenAICodexProviderConfig):
        return "openai-codex-responses"
    return getattr(provider, "api", "openai-completions")


def _model_base_url(provider: ProviderConfig, model: str | None = None) -> str:
    selected_model = model or provider.default_model
    metadata = _metadata_for_model(provider, selected_model)
    return metadata.base_url if metadata is not None and metadata.base_url else provider.base_url


def _model_headers(provider: ProviderConfig, model: str | None = None) -> dict[str, str]:
    selected_model = model or provider.default_model
    metadata = _metadata_for_model(provider, selected_model)
    return {**provider.headers, **(metadata.headers if metadata is not None else {})}


def _model_compat(provider: ProviderConfig, model: str | None = None) -> dict[str, Any]:
    selected_model = model or provider.default_model
    metadata = _metadata_for_model(provider, selected_model)
    return {
        **_detected_compat(provider, selected_model),
        **getattr(provider, "compat", {}),
        **(metadata.compat if metadata is not None else {}),
    }


def _detected_compat(provider: ProviderConfig, model: str) -> dict[str, Any]:
    base_url = _model_base_url(provider, model)
    is_together = provider.name == "together" or "api.together.ai" in base_url
    is_zai = provider.name == "zai" or "api.z.ai" in base_url
    is_moonshot = provider.name in {"moonshotai", "moonshotai-cn"} or "moonshot." in base_url
    is_grok = provider.name == "xai" or "api.x.ai" in base_url
    is_deepseek = provider.name == "deepseek" or "deepseek.com" in base_url
    is_cerebras = provider.name == "cerebras" or "cerebras.ai" in base_url
    is_openrouter = provider.name == "openrouter" or "openrouter.ai" in base_url
    is_openai_api = (
        urlsplit(base_url).hostname == urlsplit(DEFAULT_OPENAI_COMPATIBLE_BASE_URL).hostname
    )
    is_openai_responses = _provider_api(provider, model) == "openai-responses"
    is_nonstandard = is_cerebras or is_grok or is_together or is_deepseek or is_zai or is_moonshot
    use_max_tokens = is_moonshot or is_together
    is_anthropic_api = urlsplit(base_url).hostname == "api.anthropic.com"
    return {
        "supportsStore": not is_nonstandard,
        "supportsReasoningEffort": not (is_grok or is_zai or is_moonshot or is_together),
        "supportsUsageInStreaming": True,
        "maxTokensField": "max_tokens" if use_max_tokens else "max_completion_tokens",
        "thinkingFormat": (
            "deepseek"
            if is_deepseek
            else "zai"
            if is_zai
            else "together"
            if is_together
            else "openrouter"
            if is_openrouter
            else "openai"
        ),
        "supportsStrictMode": not (is_moonshot or is_together),
        "supportsLongCacheRetention": not is_together,
        # OpenAI's prompt-cache fields and affinity headers are not universally
        # accepted by compatible gateways. Default them on only for the official
        # endpoint; provider/model compat can opt another route in explicitly.
        "supportsPromptCacheKey": is_openai_api,
        "sendSessionAffinityHeaders": is_openai_api and is_openai_responses,
        "sessionAffinityFormat": "openrouter" if is_openrouter else "openai",
        # Only first-party Anthropic is known to accept cache_control. Several
        # catalog providers speak the Anthropic protocol through a gateway, and one
        # proxies to non-Anthropic models, so they default to no breakpoints. This
        # is a detected default, overridable per provider or per model.
        "supportsCacheControl": is_anthropic_api,
        "supportsCacheControlOnTools": True,
    }


def _model_max_tokens(provider: ProviderConfig, model: str | None = None) -> int | None:
    selected_model = model or provider.default_model
    metadata = _metadata_for_model(provider, selected_model)
    return metadata.max_tokens if metadata is not None else None


def provider_model_supports_images(provider: ProviderConfig, model: str | None = None) -> bool:
    selected_model = model or provider.default_model
    metadata = _metadata_for_model(provider, selected_model)
    return metadata is not None and "image" in metadata.input


def provider_default_thinking_level(
    provider: ProviderConfig,
    *,
    model: str | None = None,
) -> ThinkingLevel | None:
    """Return the preferred thinking level for a provider/model pair."""
    selected_model = model or provider.default_model
    levels = provider_thinking_levels(provider, model=selected_model)
    if not levels:
        return None
    metadata = _metadata_for_model(provider, selected_model)
    if metadata is not None and metadata.thinking_default in levels:
        return metadata.thinking_default
    if DEFAULT_THINKING_LEVEL in levels:
        return DEFAULT_THINKING_LEVEL
    return levels[0]


def resolve_startup_thinking_level(
    provider: ProviderConfig,
    model: str,
    *,
    preferred: ThinkingLevel = DEFAULT_THINKING_LEVEL,
) -> ThinkingLevel | None:
    """Pick a valid startup thinking level for a provider/model pair.

    Startup (TUI and print mode) must never crash just because the remembered
    default model does not support the global default level. The level uses a
    model-aware fallback policy:
    the remembered per-model preference wins, then the model catalog default,
    then the global ``preferred`` level, then the first available level.

    Returns ``None`` when the model has no configurable thinking levels.
    """
    levels = provider_thinking_levels(provider, model=model)
    if not levels:
        return None
    remembered = provider.thinking_defaults.get(model)
    if remembered in levels:
        return remembered
    metadata = _metadata_for_model(provider, model)
    if metadata is not None and metadata.thinking_default in levels:
        return metadata.thinking_default
    if preferred in levels:
        return preferred
    return provider_default_thinking_level(provider, model=model) or levels[0]


def openai_compatible_config_from_provider(
    provider: OpenAICompatibleProviderConfig,
    *,
    credential_reader: CredentialReader | None = None,
    model: str | None = None,
    thinking_level: ThinkingLevel | None = None,
) -> OpenAICompatibleConfig:
    """Build OpenAI-compatible runtime config from durable settings."""
    api_key = _api_key_from_provider(provider, credential_reader=credential_reader)
    selected_model = model or provider.default_model
    base_url = _model_base_url(provider, selected_model)
    if provider.name == DEFAULT_PROVIDER_NAME and provider.api_key_env == "OPENAI_API_KEY":
        base_url = environ.get("OPENAI_BASE_URL", base_url)
    reasoning_effort = _reasoning_effort_from_provider(
        provider,
        model=selected_model,
        thinking_level=thinking_level,
    )
    compat = _model_compat(provider, selected_model)
    return OpenAICompatibleConfig(
        api_key=api_key,
        provider_name=provider.name,
        api=str(_provider_api(provider, selected_model)),
        base_url=base_url.rstrip("/"),
        headers=_model_headers(provider, selected_model),
        timeout_seconds=provider.timeout_seconds,
        stream_idle_timeout_seconds=provider.stream_idle_timeout_seconds,
        max_retries=provider.max_retries,
        max_retry_delay_seconds=provider.max_retry_delay_seconds,
        supports_images=provider_model_supports_images(provider, selected_model),
        reasoning_effort=reasoning_effort,
        reasoning_effort_parameter=provider.thinking_parameter or "reasoning_effort",
        thinking_format=_thinking_format(provider, selected_model),
        compat=compat,
        response_provider_header=(
            "x-inference-provider" if provider.name == "huggingface" else None
        ),
        include_reasoning_effort_none=_include_reasoning_effort_none(
            provider,
            model=selected_model,
            thinking_level=thinking_level,
        ),
    )


def provider_kind(provider: ProviderConfig) -> ProviderKind:
    """Return the durable provider kind."""
    if isinstance(provider, OpenAICodexProviderConfig):
        return "openai-codex"
    return "openai-compatible"


def provider_has_usable_credentials(
    provider: ProviderConfig,
    *,
    credential_reader: CredentialReader | None = None,
) -> bool:
    """Return whether Tau can attempt calls for this provider without prompting setup."""
    if provider.credential_name and credential_reader is not None:
        get_oauth = getattr(credential_reader, "get_oauth", None)
        if (
            get_oauth_provider(provider.name) is not None
            and get_oauth is not None
            and get_oauth(provider.credential_name) is not None
        ):
            return True
        if credential_reader.get(provider.credential_name):
            return True
    return bool(environ.get(provider.api_key_env))


def _reasoning_effort_from_provider(
    provider: OpenAICompatibleProviderConfig,
    *,
    model: str | None,
    thinking_level: ThinkingLevel | None,
) -> str | None:
    if thinking_level is None or provider.thinking_parameter not in {
        "reasoning_effort",
        "reasoning.effort",
    }:
        return None

    levels = provider_thinking_levels(provider, model=model)
    if not levels:
        return None

    selected_model = model or provider.default_model
    normalized = normalize_thinking_level(thinking_level)
    if normalized not in levels:
        available = ", ".join(levels)
        raise ProviderConfigError(
            f"Thinking mode {normalized} is not available for "
            f"{provider.name}:{selected_model}. Available modes: {available}"
        )
    if provider.name == "huggingface" and normalized == "minimal":
        # Hugging Face's router currently accepts low/medium/high/xhigh/max/none
        # for reasoning_effort, but rejects Pi/Tau's "minimal" label.
        return "low"
    return reasoning_effort_for_level(normalized)


def _thinking_format(provider: ProviderConfig, model: str) -> str:
    compat = _model_compat(provider, model)
    value = compat.get("thinkingFormat")
    if isinstance(value, str) and value:
        return value
    base_url = _model_base_url(provider, model)
    if provider.name == "deepseek" or "deepseek.com" in base_url:
        return "deepseek"
    if provider.name == "zai" or "api.z.ai" in base_url:
        return "zai"
    if provider.name == "together" or "api.together.ai" in base_url:
        return "together"
    if provider.name == "openrouter" or "openrouter.ai" in base_url:
        return "openrouter"
    return "openai"


def _include_reasoning_effort_none(
    provider: ProviderConfig,
    *,
    model: str,
    thinking_level: ThinkingLevel | None,
) -> bool:
    if thinking_level is None:
        return False
    try:
        normalized = normalize_thinking_level(thinking_level)
    except ValueError:
        return False
    if normalized != "off":
        return False
    return "off" in provider_thinking_levels(provider, model=model)


def _api_key_from_provider(
    provider: ProviderConfig,
    *,
    credential_reader: CredentialReader | None,
) -> str:
    if provider.credential_name and credential_reader is not None:
        credential = credential_reader.get(provider.credential_name)
        if credential:
            return credential
        get_oauth = getattr(credential_reader, "get_oauth", None)
        if get_oauth_provider(provider.name) is not None and get_oauth is not None:
            oauth_credential = get_oauth(provider.credential_name)
            if oauth_credential is not None:
                access = getattr(oauth_credential, "access", None)
                if isinstance(access, str) and access:
                    return access

    api_key = environ.get(provider.api_key_env)
    if api_key:
        return api_key
    credential_hint = f" or run /login {provider.name}" if provider.credential_name else ""
    raise RuntimeError(f"Missing provider API key. Set {provider.api_key_env}{credential_hint}.")


def _validate_provider_numbers(
    *,
    timeout_seconds: float,
    stream_idle_timeout_seconds: float,
    max_retries: int,
    max_retry_delay_seconds: float,
) -> None:
    if isinstance(timeout_seconds, bool) or timeout_seconds <= 0:
        raise ProviderConfigError("Provider timeout_seconds must be greater than 0")
    if isinstance(stream_idle_timeout_seconds, bool) or stream_idle_timeout_seconds <= 0:
        raise ProviderConfigError("Provider stream_idle_timeout_seconds must be greater than 0")
    if not isinstance(max_retries, int) or isinstance(max_retries, bool) or max_retries < 0:
        raise ProviderConfigError("Provider max_retries must be 0 or greater")
    if (
        not isinstance(max_retry_delay_seconds, int | float)
        or isinstance(max_retry_delay_seconds, bool)
        or max_retry_delay_seconds < 0
    ):
        raise ProviderConfigError("Provider max_retry_delay_seconds must be 0 or greater")


def _validate_context_windows(context_windows: dict[str, int]) -> None:
    for model, context_window in context_windows.items():
        if not isinstance(model, str) or not model.strip():
            raise ProviderConfigError("Provider context_windows keys must be non-empty strings")
        if (
            not isinstance(context_window, int)
            or isinstance(context_window, bool)
            or context_window <= 0
        ):
            raise ProviderConfigError("Provider context_windows values must be positive integers")


def _validate_model_metadata(
    models: tuple[str, ...],
    model_metadata: dict[str, ProviderModelMetadata],
) -> None:
    model_names = set(models)
    for model, metadata in model_metadata.items():
        if model not in model_names:
            raise ProviderConfigError(f"Provider model_metadata key is not in models: {model}")
        if metadata.context_window is not None and metadata.context_window <= 0:
            raise ProviderConfigError("Provider model_metadata context_window must be positive")
        if metadata.max_tokens is not None and metadata.max_tokens <= 0:
            raise ProviderConfigError("Provider model_metadata max_tokens must be positive")
        if any(item not in {"text", "image"} for item in metadata.input):
            raise ProviderConfigError("Provider model_metadata input must contain text or image")
        if any(value < 0 for value in metadata.cost.values()):
            raise ProviderConfigError("Provider model_metadata cost values must be non-negative")
        if metadata.thinking_default is not None:
            normalize_thinking_level(metadata.thinking_default)
        if metadata.thinking_levels:
            try:
                normalized = normalize_thinking_levels(metadata.thinking_levels)
            except ValueError as exc:
                raise ProviderConfigError(str(exc)) from exc
            if normalized != metadata.thinking_levels:
                raise ProviderConfigError(
                    "Provider model_metadata thinking_levels must be normalized"
                )
            if metadata.thinking_default is None:
                raise ProviderConfigError(
                    f"Provider model_metadata {model} thinking_default is required "
                    "when thinking_levels is set"
                )
            if metadata.thinking_default not in metadata.thinking_levels:
                raise ProviderConfigError(
                    f"Provider model_metadata {model} thinking_default must be in thinking_levels"
                )
        _validate_runtime_cost_tiers(metadata.cost_tiers)
        _validate_json_object(metadata.compat, "Provider model_metadata compat")
        _validate_string_dict(metadata.headers, "Provider model_metadata headers")


def _validate_runtime_cost_tiers(tiers: tuple[ModelCostTier, ...]) -> None:
    if tiers and tiers[-1].max_input_tokens is not None:
        raise ProviderConfigError(
            "Provider model_metadata final cost tier must omit max_input_tokens"
        )
    previous_limit = 0
    for tier in tiers:
        if any(value < 0 for value in tier.cost.values()):
            raise ProviderConfigError(
                "Provider model_metadata cost tier values must be non-negative"
            )
        if tier.max_input_tokens is None:
            continue
        if tier.max_input_tokens <= previous_limit:
            raise ProviderConfigError(
                "Provider model_metadata cost tier limits must be strictly increasing"
            )
        previous_limit = tier.max_input_tokens


def _validate_string_dict(value: dict[str, str], field_name: str) -> None:
    for key, item in value.items():
        if not isinstance(key, str) or not key.strip():
            raise ProviderConfigError(f"{field_name} keys must be non-empty strings")
        if not isinstance(item, str) or not item.strip():
            raise ProviderConfigError(f"{field_name} values must be non-empty strings")


def _validate_json_object(value: dict[str, Any], field_name: str) -> None:
    for key, item in value.items():
        if not isinstance(key, str) or not key.strip():
            raise ProviderConfigError(f"{field_name} keys must be non-empty strings")
        _validate_json_value(item, f"{field_name}.{key}")


def _validate_json_value(value: object, field_name: str) -> None:
    if value is None or isinstance(value, str | int | float | bool):
        return
    if isinstance(value, list):
        for item in value:
            _validate_json_value(item, field_name)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ProviderConfigError(f"{field_name} object keys must be strings")
            _validate_json_value(item, f"{field_name}.{key}")
        return
    raise ProviderConfigError(f"{field_name} must be JSON-compatible")


def _reject_codex_legacy_compat(compat: dict[str, Any]) -> None:
    if compat:
        raise ProviderConfigError("OpenAI Codex legacy provider compat is not supported")


_HF_INFERENCE_PROVIDER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def validate_huggingface_inference_provider(value: str) -> str:
    """Return a normalized explicit Hugging Face provider suffix."""
    normalized = value.strip()
    if not _HF_INFERENCE_PROVIDER_PATTERN.fullmatch(normalized):
        raise ProviderConfigError(
            "Hugging Face inference provider must contain only letters, numbers, '.', '_', or '-'"
        )
    if normalized in {"fastest", "cheapest", "preferred"}:
        raise ProviderConfigError(
            f"Hugging Face inference provider must be explicit, not routing policy: {normalized}"
        )
    return normalized


def _validate_inference_providers(
    provider_name: str,
    models: tuple[str, ...],
    inference_providers: dict[str, str],
) -> None:
    if inference_providers and provider_name != "huggingface":
        raise ProviderConfigError(
            "inference_providers preferences are only supported for the huggingface provider"
        )
    for model, route in inference_providers.items():
        if model not in models:
            raise ProviderConfigError(
                f"Inference-provider preference references unknown model: {model}"
            )
        validate_huggingface_inference_provider(route)


def _validate_thinking_defaults(thinking_defaults: dict[str, ThinkingLevel]) -> None:
    for model, thinking_level in thinking_defaults.items():
        if not isinstance(model, str) or not model.strip():
            raise ProviderConfigError("Provider thinking_defaults keys must be non-empty strings")
        try:
            normalize_thinking_level(thinking_level)
        except ValueError as exc:
            raise ProviderConfigError(str(exc)) from exc


def _validate_thinking_config(
    *,
    thinking_parameter: ThinkingParameter | None,
) -> None:
    if thinking_parameter not in {
        None,
        "reasoning_effort",
        "reasoning.effort",
        "anthropic.thinking",
    }:
        raise ProviderConfigError(
            "Provider thinking_parameter must be reasoning_effort, reasoning.effort, "
            "or anthropic.thinking"
        )
