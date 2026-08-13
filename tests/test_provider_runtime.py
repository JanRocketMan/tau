from pathlib import Path

import pytest

from tau_ai import OpenAICodexProvider, OpenAICompatibleProvider
from tau_coding import provider_runtime
from tau_coding.credentials import FileCredentialStore, OAuthCredential
from tau_coding.provider_config import (
    OpenAICodexProviderConfig,
    OpenAICompatibleProviderConfig,
    ProviderConfigError,
    ProviderModelMetadata,
    provider_config_from_catalog_entry,
    resolve_startup_thinking_level,
)
from tau_coding.provider_runtime import OpenAICodexCredentialResolver, create_model_provider


def test_create_model_provider_returns_openai_codex_provider(tmp_path: Path) -> None:
    store = FileCredentialStore(tmp_path / "credentials.json")

    provider = create_model_provider(
        OpenAICodexProviderConfig(stream_idle_timeout_seconds=900),
        credential_store=store,
    )

    assert isinstance(provider, OpenAICodexProvider)
    assert provider._config.stream_idle_timeout_seconds == 900


def test_create_model_provider_uses_codex_model_image_capability(tmp_path: Path) -> None:
    store = FileCredentialStore(tmp_path / "credentials.json")
    store.set_api_key("opencode", "sk-test")
    config = provider_config_from_catalog_entry("openai-codex")

    vision_provider = create_model_provider(
        config,
        credential_store=store,
        model="gpt-5.6-sol",
    )

    assert isinstance(vision_provider, OpenAICodexProvider)
    assert vision_provider._config.supports_images is True

    # Use opencode with deepseek-v4-flash (text-only model) for non-vision test
    opencode_config = provider_config_from_catalog_entry("opencode")
    text_provider = create_model_provider(
        opencode_config,
        credential_store=store,
        model="deepseek-v4-flash",
    )

    assert isinstance(text_provider, OpenAICompatibleProvider)
    assert text_provider._config.supports_images is False


def test_direct_openai_runtime_enables_responses_cache_affinity(tmp_path: Path) -> None:
    store = FileCredentialStore(tmp_path / "credentials.json")
    store.set_api_key("opencode", "sk-test")

    provider = create_model_provider(
        provider_config_from_catalog_entry("opencode"),
        credential_store=store,
        model="gpt-5.6-luna",
    )

    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider._config.compat["supportsPromptCacheKey"] is False
    assert provider._config.compat["sendSessionAffinityHeaders"] is False
    assert provider._config.compat["sessionAffinityFormat"] == "openai"


def test_huggingface_runtime_pins_backing_provider_with_model_alias(tmp_path: Path) -> None:
    store = FileCredentialStore(tmp_path / "credentials.json")
    store.set_api_key("huggingface", "hf-test")
    config = OpenAICompatibleProviderConfig(
        name="huggingface",
        credential_name="huggingface",
        models=("zai-org/GLM-5.2",),
        default_model="zai-org/GLM-5.2",
    )

    provider = create_model_provider(
        config,
        credential_store=store,
        model="zai-org/GLM-5.2",
        inference_provider="deepinfra",
    )

    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider._config.model_aliases == {"zai-org/GLM-5.2": "zai-org/GLM-5.2:deepinfra"}


def test_huggingface_runtime_rejects_policy_suffix(tmp_path: Path) -> None:
    store = FileCredentialStore(tmp_path / "credentials.json")
    store.set_api_key("huggingface", "hf-test")
    config = OpenAICompatibleProviderConfig(
        name="huggingface",
        credential_name="huggingface",
        models=("zai-org/GLM-5.2",),
        default_model="zai-org/GLM-5.2",
    )

    with pytest.raises(ProviderConfigError, match="explicit"):
        create_model_provider(
            config,
            credential_store=store,
            model="zai-org/GLM-5.2",
            inference_provider="fastest",
        )


def test_compatible_gateway_defaults_to_no_openai_cache_affinity(tmp_path: Path) -> None:
    store = FileCredentialStore(tmp_path / "credentials.json")
    store.set_api_key("opencode", "gateway-key")

    provider = create_model_provider(
        provider_config_from_catalog_entry("opencode"),
        credential_store=store,
    )

    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider._config.compat["supportsPromptCacheKey"] is False
    assert provider._config.compat["sendSessionAffinityHeaders"] is False


def test_create_model_provider_rejects_model_not_declared_for_provider(
    tmp_path: Path,
) -> None:
    store = FileCredentialStore(tmp_path / "credentials.json")
    provider_config = OpenAICompatibleProviderConfig(
        name="local",
        models=("qwen",),
        default_model="qwen",
    )

    with pytest.raises(
        ProviderConfigError,
        match="Model is not configured for provider local: llama",
    ):
        create_model_provider(provider_config, credential_store=store, model="llama")


def test_create_model_provider_maps_codex_reasoning_effort_like_pi(tmp_path: Path) -> None:
    store = FileCredentialStore(tmp_path / "credentials.json")
    provider_config = OpenAICodexProviderConfig(
        thinking_parameter="reasoning.effort",
        model_metadata={
            "gpt-5.5": ProviderModelMetadata(
                reasoning=True,
                thinking_default="xhigh",
                thinking_levels=("off", "minimal", "low", "medium", "high", "xhigh"),
            ),
        },
    )

    off_provider = create_model_provider(
        provider_config,
        credential_store=store,
        model="gpt-5.5",
        thinking_level="off",
    )
    minimal_provider = create_model_provider(
        provider_config,
        credential_store=store,
        model="gpt-5.5",
        thinking_level="minimal",
    )
    xhigh_provider = create_model_provider(
        provider_config,
        credential_store=store,
        model="gpt-5.5",
        thinking_level="xhigh",
    )

    assert isinstance(off_provider, OpenAICodexProvider)
    assert isinstance(minimal_provider, OpenAICodexProvider)
    assert isinstance(xhigh_provider, OpenAICodexProvider)
    assert off_provider._config.reasoning_effort is None
    assert minimal_provider._config.reasoning_effort == "low"
    assert xhigh_provider._config.reasoning_effort == "xhigh"


def test_create_model_provider_coerces_unsupported_startup_thinking_level(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Regression: startup used to pass the global default ("medium") straight
    # to create_model_provider, which crashed for models like kimi-code:k3
    # that only support xhigh. Now k3 supports low, high, and max.
    monkeypatch.setenv("TAU_TEST_KIMI_CODE_API_KEY", "test-key")
    store = FileCredentialStore(tmp_path / "credentials.json")
    provider_config = OpenAICompatibleProviderConfig(
        name="kimi-code",
        api_key_env="TAU_TEST_KIMI_CODE_API_KEY",
        models=("k3",),
        default_model="k3",
        thinking_parameter="reasoning_effort",
        model_metadata={
            "k3": ProviderModelMetadata(
                reasoning=True,
                thinking_default="max",
                thinking_levels=("low", "high", "max"),
            ),
        },
    )

    with pytest.raises(
        ProviderConfigError,
        match="Thinking mode medium is not available for kimi-code:k3",
    ):
        create_model_provider(
            provider_config,
            credential_store=store,
            model="k3",
            thinking_level="medium",
        )

    provider = create_model_provider(
        provider_config,
        credential_store=store,
        model="k3",
        thinking_level=resolve_startup_thinking_level(provider_config, "k3"),
    )

    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider._config.reasoning_effort == "max"


@pytest.mark.anyio
async def test_openai_codex_credential_resolver_refreshes_expired_credentials(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    store = FileCredentialStore(tmp_path / "credentials.json")
    store.set_oauth(
        "openai-codex",
        OAuthCredential(
            access="old-access",
            refresh="old-refresh",
            expires=1,
            account_id="old-account",
        ),
    )

    async def fake_refresh(refresh_token: str) -> OAuthCredential:
        assert refresh_token == "old-refresh"
        return OAuthCredential(
            access="new-access",
            refresh="new-refresh",
            expires=9999999999999,
            account_id="new-account",
        )

    monkeypatch.setattr(provider_runtime, "refresh_openai_codex_token", fake_refresh)

    resolver = OpenAICodexCredentialResolver(
        OpenAICodexProviderConfig(),
        credential_store=store,
    )

    credentials = await resolver()

    assert credentials.access_token == "new-access"
    assert credentials.account_id == "new-account"
    assert store.get_oauth("openai-codex") == OAuthCredential(
        access="new-access",
        refresh="new-refresh",
        expires=9999999999999,
        account_id="new-account",
    )
