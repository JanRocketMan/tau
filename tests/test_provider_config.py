"""Provider configuration tests for the catalog-backed settings model."""

from pathlib import Path

import pytest

from tau_coding.catalog_loader import builtin_catalog_resource_text
from tau_coding.credentials import OAuthCredential
from tau_coding.paths import TauPaths
from tau_coding.provider_catalog import ModelCostTier
from tau_coding.provider_config import (
    DEFAULT_MODEL,
    DEFAULT_PROVIDER_NAME,
    OpenAICodexProviderConfig,
    OpenAICompatibleProviderConfig,
    ProviderConfigError,
    ProviderModelMetadata,
    ProviderSettings,
    load_provider_settings,
    openai_compatible_config_from_provider,
    provider_default_thinking_level,
    provider_has_usable_credentials,
    provider_model_supports_images,
    provider_thinking_levels,
    provider_thinking_unavailable_reason,
    resolve_provider_selection,
    resolve_startup_thinking_level,
)
from tau_coding.thinking import ThinkingParameter


def _catalog_paths(tmp_path: Path, body: str | None = None) -> TauPaths:
    """Return TauPaths pointing at an isolated catalog file."""
    catalog = tmp_path / ".tau" / "catalog.toml"
    catalog.parent.mkdir(parents=True, exist_ok=True)
    catalog.write_text(
        body if body is not None else builtin_catalog_resource_text(), encoding="utf-8"
    )
    return TauPaths(home=tmp_path / ".tau", agents_home=tmp_path / ".agents", catalog_path=catalog)


def test_load_provider_settings_uses_packaged_catalog(tmp_path: Path) -> None:
    settings = load_provider_settings(TauPaths(home=tmp_path / ".tau"))

    assert settings.default_provider == "openai-codex"
    assert [provider.name for provider in settings.providers] == [
        "openai-codex",
        "opencode-go",
    ]
    assert settings.get_provider("openai-codex").default_model == "gpt-5.6-sol"


def test_builtin_codex_preserves_model_input_capabilities() -> None:
    codex = ProviderSettings().get_provider("openai-codex")

    assert provider_model_supports_images(codex, "gpt-5.6-luna")
    assert provider_model_supports_images(codex, "gpt-5.6-sol")
    assert not provider_model_supports_images(codex, "gpt-5.5")


def test_builtin_catalog_declares_model_scoped_capabilities() -> None:
    settings = ProviderSettings()
    codex = settings.get_provider("openai-codex")
    opencode_go = settings.get_provider("opencode-go")

    assert codex.context_windows["gpt-5.6-luna"] == 272_000
    assert opencode_go.context_windows["gpt-5.6-luna"] == 1_000_000
    assert provider_thinking_levels(codex, model="gpt-5.6-luna") == (
        "low",
        "medium",
        "high",
        "xhigh",
    )
    assert provider_default_thinking_level(codex, model="gpt-5.6-luna") == "xhigh"
    assert provider_thinking_unavailable_reason(codex, model="unknown") == (
        "Provider openai-codex does not declare thinking metadata for unknown"
    )
    assert provider_thinking_levels(opencode_go, model="deepseek-v4-flash") == (
        "high",
        "max",
    )
    assert provider_default_thinking_level(opencode_go, model="deepseek-v4-flash") == "max"
    assert resolve_startup_thinking_level(opencode_go, "deepseek-v4-flash") == "max"
    assert provider_thinking_levels(opencode_go, model="gpt-5.6-luna") == (
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
    )
    # Remembered preferences (packaged thinking_defaults) beat catalog metadata
    # defaults when resolving startup thinking levels.
    assert codex.thinking_defaults == {"gpt-5.6-luna": "xhigh", "gpt-5.6-sol": "xhigh"}
    assert opencode_go.thinking_defaults == {
        "deepseek-v4-flash": "max",
        "gpt-5.6-luna": "xhigh",
    }
    assert resolve_startup_thinking_level(codex, "gpt-5.6-sol") == "xhigh"


def test_catalog_preferences_flow_into_provider_configs(tmp_path: Path) -> None:
    settings = load_provider_settings(_catalog_paths(tmp_path))
    codex = settings.get_provider("openai-codex")

    assert codex.timeout_seconds == 60.0
    assert codex.stream_idle_timeout_seconds == 600.0
    assert codex.max_retries == 2
    assert codex.max_retry_delay_seconds == 1.0


def test_legacy_provider_model_cost_tiers_round_trip() -> None:
    expected_cost_tiers = [
        {
            "max_input_tokens": 512000,
            "input": 0.3,
            "output": 1.2,
            "cacheRead": 0.06,
            "cacheWrite": 0,
        },
        {
            "input": 0.6,
            "output": 2.4,
            "cacheRead": 0.12,
            "cacheWrite": 0,
        },
    ]
    provider = OpenAICompatibleProviderConfig(
        name="local",
        base_url="http://localhost:11434/v1",
        api_key_env="LOCAL_API_KEY",
        models=("qwen",),
        default_model="qwen",
        model_metadata={
            "qwen": ProviderModelMetadata(
                cost={
                    "input": 0.3,
                    "output": 1.2,
                    "cacheRead": 0.06,
                    "cacheWrite": 0,
                },
                cost_tiers=(
                    ModelCostTier(
                        max_input_tokens=512000,
                        cost={
                            "input": 0.3,
                            "output": 1.2,
                            "cacheRead": 0.06,
                            "cacheWrite": 0,
                        },
                    ),
                    ModelCostTier(
                        cost={
                            "input": 0.6,
                            "output": 2.4,
                            "cacheRead": 0.12,
                            "cacheWrite": 0,
                        },
                    ),
                ),
            )
        },
    )

    assert provider.model_metadata["qwen"].to_json()["cost_tiers"] == expected_cost_tiers


def test_legacy_provider_cost_tier_accepts_one_hour_cache_write_rate() -> None:
    expected_cost_tiers = [
        {
            "max_input_tokens": 512000,
            "input": 0.3,
            "output": 1.2,
            "cacheRead": 0.06,
            "cacheWrite": 0.375,
            "cacheWrite1h": 0.6,
        },
        {
            "input": 0.6,
            "output": 2.4,
            "cacheRead": 0.12,
            "cacheWrite": 0.75,
            "cacheWrite1h": 1.2,
        },
    ]
    provider = OpenAICompatibleProviderConfig(
        name="local",
        base_url="http://localhost:11434/v1",
        api_key_env="LOCAL_API_KEY",
        models=("qwen",),
        default_model="qwen",
        model_metadata={
            "qwen": ProviderModelMetadata(
                cost_tiers=(
                    ModelCostTier(
                        max_input_tokens=512000,
                        cost={
                            "input": 0.3,
                            "output": 1.2,
                            "cacheRead": 0.06,
                            "cacheWrite": 0.375,
                            "cacheWrite1h": 0.6,
                        },
                    ),
                    ModelCostTier(
                        cost={
                            "input": 0.6,
                            "output": 2.4,
                            "cacheRead": 0.12,
                            "cacheWrite": 0.75,
                            "cacheWrite1h": 1.2,
                        },
                    ),
                ),
            )
        },
    )

    assert provider.model_metadata["qwen"].to_json()["cost_tiers"] == expected_cost_tiers


def test_runtime_metadata_rejects_invalid_cost_tier_values() -> None:
    with pytest.raises(ProviderConfigError, match="cost tier values must be non-negative"):
        OpenAICompatibleProviderConfig(
            name="local",
            models=("qwen",),
            default_model="qwen",
            model_metadata={
                "qwen": ProviderModelMetadata(
                    cost_tiers=(
                        ModelCostTier(
                            cost={
                                "input": -0.3,
                                "output": 1.2,
                                "cacheRead": 0.06,
                                "cacheWrite": 0,
                            }
                        ),
                    )
                )
            },
        )


def test_resolve_provider_selection_uses_configured_defaults() -> None:
    settings = ProviderSettings(
        default_provider="local",
        providers=(
            OpenAICompatibleProviderConfig(
                name="local",
                base_url="http://localhost:11434/v1",
                api_key_env="LOCAL_API_KEY",
                models=("qwen",),
                default_model="qwen",
            ),
        ),
    )

    selection = resolve_provider_selection(settings)

    assert selection.provider.name == "local"
    assert selection.model == "qwen"


def test_resolve_provider_selection_rejects_unknown_provider() -> None:
    with pytest.raises(ProviderConfigError, match="Unknown provider"):
        resolve_provider_selection(ProviderSettings(), provider_name="missing")


def _kimi_code_like_provider() -> OpenAICompatibleProviderConfig:
    # Mirrors a catalog entry: k3 supports low, high, and max, with max as its
    # catalog default; kimi-for-coding supports only medium.
    return OpenAICompatibleProviderConfig(
        name="kimi-code",
        models=("k3", "kimi-for-coding"),
        default_model="k3",
        thinking_parameter="reasoning_effort",
        model_metadata={
            "k3": ProviderModelMetadata(
                reasoning=True,
                thinking_default="max",
                thinking_levels=("low", "high", "max"),
            ),
            "kimi-for-coding": ProviderModelMetadata(
                reasoning=True,
                thinking_default="medium",
                thinking_levels=("medium",),
            ),
        },
    )


def test_resolve_startup_thinking_level_uses_k3_max_default() -> None:
    provider = _kimi_code_like_provider()

    # The current global startup preference is xhigh, which K3 does not expose;
    # its catalog default max wins.
    assert resolve_startup_thinking_level(provider, "k3") == "max"


def test_resolve_startup_thinking_level_prefers_remembered_model_default() -> None:
    provider = _kimi_code_like_provider()
    remembered = OpenAICompatibleProviderConfig(
        name=provider.name,
        models=provider.models,
        default_model=provider.default_model,
        thinking_parameter=provider.thinking_parameter,
        thinking_defaults={"k3": "high"},
        model_metadata=provider.model_metadata,
    )

    assert resolve_startup_thinking_level(remembered, "k3") == "high"


def test_resolve_startup_thinking_level_keeps_supported_default() -> None:
    provider = _kimi_code_like_provider()

    # kimi-for-coding supports global medium and exposes it as its catalog default.
    assert provider_thinking_levels(provider, model="kimi-for-coding") == ("medium",)
    assert resolve_startup_thinking_level(provider, "kimi-for-coding") == "medium"


def test_resolve_startup_thinking_level_returns_none_without_levels() -> None:
    provider = OpenAICompatibleProviderConfig(
        name="local",
        models=("qwen",),
        default_model="qwen",
    )

    assert resolve_startup_thinking_level(provider, "qwen") is None


def test_resolve_provider_selection_rejects_model_not_declared_for_provider() -> None:
    settings = ProviderSettings(
        default_provider="local",
        providers=(
            OpenAICompatibleProviderConfig(
                name="local",
                base_url="http://localhost:11434/v1",
                api_key_env="LOCAL_API_KEY",
                models=("qwen",),
                default_model="qwen",
            ),
        ),
    )

    with pytest.raises(
        ProviderConfigError,
        match="Model is not configured for provider local: llama",
    ):
        resolve_provider_selection(settings, model="llama")


def test_runtime_config_uses_selected_model_image_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CUSTOM_API_KEY", "secret")
    provider = OpenAICompatibleProviderConfig(
        name="custom",
        api_key_env="CUSTOM_API_KEY",
        models=("text", "vision"),
        default_model="text",
        model_metadata={
            "text": ProviderModelMetadata(input=("text",)),
            "vision": ProviderModelMetadata(input=("text", "image")),
        },
    )

    assert not openai_compatible_config_from_provider(provider, model="text").supports_images
    assert openai_compatible_config_from_provider(provider, model="vision").supports_images


def test_openai_compatible_config_from_provider_uses_configured_env_var(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CUSTOM_API_KEY", "secret")
    provider = OpenAICompatibleProviderConfig(
        name="custom",
        base_url="http://localhost:11434/v1/",
        api_key_env="CUSTOM_API_KEY",
        models=("qwen",),
        default_model="qwen",
    )

    config = openai_compatible_config_from_provider(provider)

    assert config.api_key == "secret"
    assert config.base_url == "http://localhost:11434/v1"


def test_huggingface_runtime_config_captures_inference_provider_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HF_API_KEY", "secret")
    provider = OpenAICompatibleProviderConfig(
        name="huggingface",
        base_url="https://router.huggingface.co/v1",
        api_key_env="HF_API_KEY",
        models=("qwen",),
        default_model="qwen",
        inference_providers={"qwen": "nvidia"},
    )

    config = openai_compatible_config_from_provider(provider)

    assert config.response_provider_header == "x-inference-provider"


def test_openai_compatible_config_from_provider_uses_configured_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCAL_API_KEY", "test-key")
    provider = OpenAICompatibleProviderConfig(
        name="local",
        base_url="http://localhost:11434/v1/",
        api_key_env="LOCAL_API_KEY",
        models=("qwen",),
        default_model="qwen",
        timeout_seconds=120,
        stream_idle_timeout_seconds=900,
        max_retries=1,
        max_retry_delay_seconds=0.25,
    )

    config = openai_compatible_config_from_provider(provider)

    assert config.timeout_seconds == 120
    assert config.stream_idle_timeout_seconds == 900
    assert config.max_retries == 1
    assert config.max_retry_delay_seconds == 0.25


def test_openai_compatible_config_from_provider_uses_configured_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCAL_API_KEY", "test-key")
    provider = OpenAICompatibleProviderConfig(
        name="local",
        base_url="http://localhost:11434/v1/",
        api_key_env="LOCAL_API_KEY",
        models=("qwen",),
        default_model="qwen",
        headers={"X-Custom": "value"},
        model_metadata={
            "qwen": ProviderModelMetadata(headers={"X-Model": "qwen"}),
        },
    )

    config = openai_compatible_config_from_provider(provider, model="qwen")

    assert config.headers["X-Custom"] == "value"
    assert config.headers["X-Model"] == "qwen"


def test_openai_compatible_config_from_provider_sets_reasoning_effort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCAL_API_KEY", "test-key")
    provider = OpenAICompatibleProviderConfig(
        name="local",
        base_url="http://localhost:11434/v1/",
        api_key_env="LOCAL_API_KEY",
        models=("reasoner",),
        default_model="reasoner",
        thinking_parameter="reasoning_effort",
        model_metadata={
            "reasoner": ProviderModelMetadata(
                reasoning=True,
                thinking_default="low",
                thinking_levels=("low", "high"),
            ),
        },
    )

    config = openai_compatible_config_from_provider(
        provider,
        model="reasoner",
        thinking_level="high",
    )

    assert config.reasoning_effort == "high"
    assert config.reasoning_effort_parameter == "reasoning_effort"


def test_deepseek_v4_flash_maps_thinking_levels_to_reasoning_effort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCAL_API_KEY", "test-key")
    provider = OpenAICompatibleProviderConfig(
        name="local",
        base_url="http://localhost:11434/v1/",
        api_key_env="LOCAL_API_KEY",
        models=("reasoner",),
        default_model="reasoner",
        thinking_parameter="reasoning_effort",
        model_metadata={
            "reasoner": ProviderModelMetadata(
                reasoning=True,
                thinking_default="high",
                thinking_levels=("low", "high"),
            ),
        },
    )

    config = openai_compatible_config_from_provider(
        provider,
        model="reasoner",
        thinking_level="high",
    )

    assert config.reasoning_effort_parameter == "reasoning_effort"
    assert config.reasoning_effort == "high"


def test_deepseek_v4_flash_rejects_unlisted_thinking_levels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCAL_API_KEY", "test-key")
    provider = OpenAICompatibleProviderConfig(
        name="local",
        base_url="http://localhost:11434/v1/",
        api_key_env="LOCAL_API_KEY",
        models=("reasoner",),
        default_model="reasoner",
        thinking_parameter="reasoning_effort",
        model_metadata={
            "reasoner": ProviderModelMetadata(
                reasoning=True,
                thinking_default="low",
                thinking_levels=("low", "high"),
            ),
        },
    )

    with pytest.raises(ProviderConfigError, match="not available"):
        openai_compatible_config_from_provider(
            provider,
            model="reasoner",
            thinking_level="medium",
        )


def test_openai_compatible_config_from_provider_rejects_unsupported_thinking_level(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCAL_API_KEY", "test-key")
    provider = OpenAICompatibleProviderConfig(
        name="local",
        base_url="http://localhost:11434/v1/",
        api_key_env="LOCAL_API_KEY",
        models=("qwen",),
        default_model="qwen",
        thinking_parameter="reasoning_effort",
        model_metadata={
            "qwen": ProviderModelMetadata(
                reasoning=True,
                thinking_default="low",
                thinking_levels=("low", "high"),
            ),
        },
    )

    with pytest.raises(ProviderConfigError, match="not available"):
        openai_compatible_config_from_provider(
            provider,
            model="qwen",
            thinking_level="max",
        )


def test_openai_compatible_config_from_provider_uses_stored_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CUSTOM_API_KEY", raising=False)

    class Credentials:
        def get(self, name: str) -> str | None:
            return "stored-key" if name == "custom" else None

    provider = OpenAICompatibleProviderConfig(
        name="custom",
        api_key_env="CUSTOM_API_KEY",
        credential_name="custom",
        models=("qwen",),
        default_model="qwen",
    )
    config = openai_compatible_config_from_provider(
        provider,
        credential_reader=Credentials(),
    )

    assert config.api_key == "stored-key"


def test_openai_compatible_config_from_provider_falls_back_to_env_when_stored_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CUSTOM_API_KEY", "env-key")

    class EmptyCredentials:
        def get(self, name: str) -> str | None:
            return None

    provider = OpenAICompatibleProviderConfig(
        name="custom",
        api_key_env="CUSTOM_API_KEY",
        credential_name="custom",
        models=("qwen",),
        default_model="qwen",
    )
    config = openai_compatible_config_from_provider(
        provider,
        credential_reader=EmptyCredentials(),
    )

    assert config.api_key == "env-key"


def test_provider_has_usable_credentials_checks_stored_key_and_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    provider = OpenAICompatibleProviderConfig(
        name="openrouter",
        api_key_env="OPENROUTER_API_KEY",
        credential_name="openrouter",
    )

    class EmptyCredentials:
        def get(self, name: str) -> str | None:
            return None

    class StoredCredentials:
        def get(self, name: str) -> str | None:
            return "stored-key" if name == "openrouter" else None

    assert not provider_has_usable_credentials(provider, credential_reader=EmptyCredentials())
    assert provider_has_usable_credentials(provider, credential_reader=StoredCredentials())

    monkeypatch.setenv("OPENROUTER_API_KEY", "env-key")

    assert provider_has_usable_credentials(provider, credential_reader=EmptyCredentials())


@pytest.mark.parametrize(
    ("parameter", "expected"),
    [
        ("reasoning_effort", "reasoning_effort"),
        ("reasoning.effort", "reasoning.effort"),
    ],
)
def test_openai_compatible_config_from_provider_sets_reasoning_parameter(
    monkeypatch: pytest.MonkeyPatch,
    parameter: ThinkingParameter,
    expected: str,
) -> None:
    monkeypatch.setenv("LOCAL_API_KEY", "test-key")
    provider = OpenAICompatibleProviderConfig(
        name="local",
        base_url="http://localhost:11434/v1/",
        api_key_env="LOCAL_API_KEY",
        models=("reasoner",),
        default_model="reasoner",
        thinking_parameter=parameter,
        model_metadata={
            "reasoner": ProviderModelMetadata(
                reasoning=True,
                thinking_default="high",
                thinking_levels=("low", "high"),
            ),
        },
    )

    config = openai_compatible_config_from_provider(
        provider,
        model="reasoner",
        thinking_level="high",
    )

    assert config.reasoning_effort == "high"
    assert config.reasoning_effort_parameter == expected


def test_openai_compatible_provider_config_rejects_invalid_timeout() -> None:
    with pytest.raises(ProviderConfigError, match="greater than 0"):
        OpenAICompatibleProviderConfig(name="local", timeout_seconds=0)
    with pytest.raises(ProviderConfigError, match="stream_idle_timeout_seconds"):
        OpenAICompatibleProviderConfig(name="local", stream_idle_timeout_seconds=0)


def test_openai_compatible_provider_config_rejects_invalid_retries() -> None:
    with pytest.raises(ProviderConfigError, match="0 or greater"):
        OpenAICompatibleProviderConfig(name="local", max_retries=-1)
    with pytest.raises(ProviderConfigError, match="0 or greater"):
        OpenAICompatibleProviderConfig(name="local", max_retry_delay_seconds=-1)


def test_openai_compatible_provider_config_rejects_unknown_inference_providers() -> None:
    with pytest.raises(ProviderConfigError, match="unknown model"):
        OpenAICompatibleProviderConfig(
            name="huggingface",
            models=("qwen",),
            default_model="qwen",
            inference_providers={"missing": "nvidia"},
        )


def test_openai_compatible_provider_config_rejects_inference_providers_for_non_hf() -> None:
    with pytest.raises(ProviderConfigError, match="huggingface provider"):
        OpenAICompatibleProviderConfig(
            name="local",
            models=("qwen",),
            default_model="qwen",
            inference_providers={"qwen": "nvidia"},
        )


def test_openai_codex_provider_config_round_trips_preferences() -> None:
    provider = OpenAICodexProviderConfig(
        name="openai-codex",
        default_model="gpt-5.6-sol",
        thinking_defaults={"gpt-5.6-luna": "xhigh", "gpt-5.6-sol": "xhigh"},
    )

    assert provider.thinking_defaults["gpt-5.6-sol"] == "xhigh"
    assert provider.to_json()["default_model"] == "gpt-5.6-sol"


def test_catalog_default_provider_fallback_when_absent(tmp_path: Path) -> None:
    body = builtin_catalog_resource_text().replace('default_provider = "opencode-go"', "")
    paths = _catalog_paths(tmp_path, body)
    # Without a default_provider key the loader falls back to the first provider.
    settings = load_provider_settings(paths)
    assert settings.default_provider == "openai-codex"


def test_load_provider_settings_rejects_broken_catalog(tmp_path: Path) -> None:
    paths = _catalog_paths(tmp_path, "schema_version = 1\n[[providers]]\nname =")
    with pytest.raises(Exception, match="invalid TOML"):
        load_provider_settings(paths)


def test_default_provider_name_constant() -> None:
    assert DEFAULT_PROVIDER_NAME == "openai-codex"
    assert DEFAULT_MODEL == "gpt-5.6-luna"


def test_oauth_credential_reads_through_credential_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_CODEX_ACCESS_TOKEN", raising=False)

    class OAuthCredentials:
        def get(self, name: str) -> str | None:
            return None

        def get_oauth(self, name: str) -> OAuthCredential | None:
            if name != "openai-codex":
                return None
            return OAuthCredential(access="oauth-token", refresh="refresh-token", expires=0)

    provider = OpenAICompatibleProviderConfig(
        name="openai-codex",
        api_key_env="CUSTOM_API_KEY",
        credential_name="openai-codex",
        models=("qwen",),
        default_model="qwen",
    )
    config = openai_compatible_config_from_provider(
        provider,
        credential_reader=OAuthCredentials(),
    )

    assert config.api_key == "oauth-token"
