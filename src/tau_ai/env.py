"""Provider configuration dataclasses and defaults."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Literal

from tau_agent.types import JSONValue

DEFAULT_OPENAI_COMPATIBLE_BASE_URL = "https://api.openai.com/v1"
DEFAULT_OPENAI_COMPATIBLE_TIMEOUT_SECONDS = 60.0
DEFAULT_OPENAI_COMPATIBLE_MAX_RETRIES = 2
DEFAULT_OPENAI_COMPATIBLE_MAX_RETRY_DELAY_SECONDS = 1.0

# Prompt-cache retention preferences. "short" uses the provider default TTL
# (5 minutes on Anthropic), "long" requests the 1 hour TTL, and "none" disables
# cache breakpoints entirely for backends that reject them.
type CacheRetention = Literal["none", "short", "long"]

CACHE_RETENTION_NONE: CacheRetention = "none"
CACHE_RETENTION_SHORT: CacheRetention = "short"
CACHE_RETENTION_LONG: CacheRetention = "long"


@dataclass(frozen=True, slots=True)
class RuntimeProviderAuth:
    """Request auth resolved immediately before a provider call."""

    api_key: str
    base_url: str | None = None
    headers: Mapping[str, str] | None = None


type RuntimeProviderAuthResolver = Callable[[], Awaitable[RuntimeProviderAuth]]
type RuntimeResponseHeadersObserver = Callable[[Mapping[str, str]], None]


@dataclass(frozen=True, slots=True)
class OpenAICompatibleConfig:
    """Configuration for an OpenAI-compatible chat completions endpoint."""

    api_key: str
    base_url: str = DEFAULT_OPENAI_COMPATIBLE_BASE_URL
    headers: Mapping[str, str] | None = None
    timeout_seconds: float = DEFAULT_OPENAI_COMPATIBLE_TIMEOUT_SECONDS
    max_retries: int = DEFAULT_OPENAI_COMPATIBLE_MAX_RETRIES
    max_retry_delay_seconds: float = DEFAULT_OPENAI_COMPATIBLE_MAX_RETRY_DELAY_SECONDS
    api: str = "openai-completions"
    max_tokens: int | None = None
    supports_images: bool = False
    reasoning_effort: str | None = None
    reasoning_effort_parameter: str = "reasoning_effort"
    thinking_format: str = "openai"
    compat: Mapping[str, JSONValue] = field(default_factory=dict)
    model_aliases: Mapping[str, str] = field(default_factory=dict)
    include_reasoning_effort_none: bool = False
    provider_name: str = "OpenAI-compatible provider"
    response_provider_header: str | None = None
    omit_authorization_header: bool = False
    credential_resolver: RuntimeProviderAuthResolver | None = None
    response_headers_observer: RuntimeResponseHeadersObserver | None = None
