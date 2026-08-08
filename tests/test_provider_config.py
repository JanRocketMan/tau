import json
from pathlib import Path

import pytest

import tau_coding.provider_config as provider_config
from tau_coding.credentials import FileCredentialStore, OAuthCredential
from tau_coding.paths import TauPaths
from tau_coding.provider_catalog import ModelCostTier
from tau_coding.provider_config import (
    DEFAULT_MODEL,
    OpenAICodexProviderConfig,
    OpenAICompatibleProviderConfig,
    ProviderConfigError,
    ProviderModelMetadata,
    ProviderSettings,
    ScopedModelConfig,
    load_provider_settings,
    openai_compatible_config_from_provider,
    provider_default_thinking_level,
    provider_has_usable_credentials,
    provider_model_supports_images,
    provider_settings_from_json,
    provider_thinking_levels,
    provider_thinking_unavailable_reason,
    resolve_provider_selection,
    resolve_startup_thinking_level,
    save_provider_settings,
    set_default_provider_model,
    set_provider_thinking_level,
    upsert_openai_compatible_provider,
)
from tau_coding.thinking import ThinkingLevel


def test_stale_preferences_cannot_restore_removed_codex_alias(tmp_path: Path) -> None:
    tau_home = tmp_path / ".tau"
    tau_home.mkdir()
    (tau_home / "providers.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "default_provider": "openai-codex",
                "provider_preferences": {
                    "openai-codex": {
                        "default_model": "gpt-5.6",
                        "thinking_defaults": {"gpt-5.6": "low"},
                    }
                },
                "scoped_models": [],
            }
        )
    )

    settings = load_provider_settings(TauPaths(home=tau_home))
    codex = settings.get_provider("openai-codex")

    assert codex.default_model == "gpt-5.6-luna"
    assert "gpt-5.6" not in codex.models
    assert "gpt-5.6" not in codex.thinking_defaults


def test_load_provider_settings_missing_file_uses_current_catalog(tmp_path: Path) -> None:
    settings = load_provider_settings(TauPaths(home=tmp_path / ".tau"))

    assert settings.default_provider == "openai-codex"
    assert [provider.name for provider in settings.providers] == [
        "openai-codex",
        "opencode-go",
        "opencode",
    ]
    assert settings.get_provider("openai-codex").default_model == DEFAULT_MODEL


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
    assert opencode_go.context_windows["kimi-k3"] == 1_000_000
    assert provider_thinking_levels(codex, model="gpt-5.6-luna") == (
        "low",
        "medium",
        "high",
        "xhigh",
    )
    assert provider_default_thinking_level(codex, model="gpt-5.6-luna") == "xhigh"
    assert provider_thinking_unavailable_reason(codex, model="unknown") == (
        "openai-codex:unknown is not declared in thinking_models"
    )
    assert provider_thinking_levels(opencode_go, model="kimi-k3") == (
        "low",
        "medium",
        "high",
        "xhigh",
    )


def test_load_provider_settings_accepts_provider_preferences_with_user_catalog(
    tmp_path: Path,
) -> None:
    tau_home = tmp_path / ".tau"
    tau_home.mkdir()
    (tau_home / "catalog.toml").write_text(
        """
schema_version = 1

[[providers]]
name = "local"
display_name = "local"
kind = "openai-compatible"
base_url = "http://localhost:11434/v1"
api_key_env = "LOCAL_API_KEY"
models = ["qwen", "llama"]
default_model = "qwen"
docs_url = "http://localhost:11434/v1"
""".strip(),
        encoding="utf-8",
    )
    (tau_home / "providers.json").write_text(
        json.dumps(
            {
                "default_provider": "local",
                "provider_preferences": {
                    "local": {
                        "default_model": "qwen",
                        "headers": {"X-Test": "yes"},
                        "timeout_seconds": 12.0,
                        "max_retries": 1,
                        "max_retry_delay_seconds": 0.5,
                        "thinking_defaults": {},
                    }
                },
                "scoped_models": [{"provider": "local", "model": "qwen"}],
            }
        ),
        encoding="utf-8",
    )

    settings = load_provider_settings(TauPaths(home=tau_home))

    provider = settings.get_provider("local")
    assert settings.default_provider == "local"
    assert provider.base_url == "http://localhost:11434/v1"
    assert provider.default_model == "qwen"
    assert provider.headers == {"X-Test": "yes"}
    assert provider.timeout_seconds == 12.0
    assert settings.scoped_models == (ScopedModelConfig(provider="local", model="qwen"),)


def test_provider_settings_ignore_unknown_fields(tmp_path: Path) -> None:
    settings = provider_settings_from_json(
        {
            "default_provider": "opencode-go",
            "future_top_level_option": True,
            "provider_preferences": {
                "opencode-go": {
                    "default_model": "gpt-5.6-luna",
                    "future_provider_option": {"enabled": True},
                }
            },
        },
        paths=TauPaths(home=tmp_path / ".tau"),
    )

    assert settings.default_provider == "opencode-go"
    assert settings.get_provider("opencode-go").default_model == "gpt-5.6-luna"


def test_load_provider_settings_ignores_preference_without_catalog_entry(
    tmp_path: Path,
) -> None:
    tau_home = tmp_path / ".tau"
    tau_home.mkdir()
    (tau_home / "providers.json").write_text(
        json.dumps(
            {
                "default_provider": "opencode-go",
                "provider_preferences": {
                    "opencode-go": {"default_model": "gpt-5.6-luna"},
                    "llama-cpp": {"default_model": "local"},
                },
            }
        ),
        encoding="utf-8",
    )

    settings = load_provider_settings(TauPaths(home=tau_home))

    assert settings.get_provider("opencode-go").default_model == "gpt-5.6-luna"
    assert "llama-cpp" not in {provider.name for provider in settings.providers}


def test_save_provider_settings_writes_backup_when_replacing(tmp_path: Path) -> None:
    paths = TauPaths(home=tmp_path / ".tau")
    initial = ProviderSettings(
        providers=(
            OpenAICompatibleProviderConfig(
                name="local",
                models=("gpt-5",),
                default_model="gpt-5",
            ),
        ),
    )
    updated = ProviderSettings(
        providers=(
            OpenAICompatibleProviderConfig(
                name="local",
                models=("gpt-5-mini",),
                default_model="gpt-5-mini",
            ),
        ),
    )

    path = save_provider_settings(initial, paths)
    save_provider_settings(updated, paths)

    backup = path.with_suffix(path.suffix + ".bak")
    assert backup.exists()
    assert load_provider_settings(paths).get_provider("local").default_model == "gpt-5-mini"
    assert (
        json.loads(backup.read_text())["provider_preferences"]["local"]["default_model"] == "gpt-5"
    )


def test_save_and_load_provider_settings_round_trip(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Isolate provider_config from the host environment so built-in provider
    # discovery (credential filtering) is deterministic and the loaded settings
    # contain only the user-saved providers.
    monkeypatch.setattr(provider_config, "environ", {})

    paths = TauPaths(home=tmp_path / ".tau")
    settings = ProviderSettings(
        default_provider="local",
        providers=(
            OpenAICompatibleProviderConfig(
                name="local",
                base_url="http://localhost:11434/v1",
                api_key_env="LOCAL_API_KEY",
                models=("qwen", "llama"),
                default_model="qwen",
                context_windows={"qwen": 64_000},
                headers={"X-Test": "enabled"},
                timeout_seconds=120,
                max_retries=2,
                max_retry_delay_seconds=0.5,
            ),
        ),
        scoped_models=(ScopedModelConfig(provider="local", model="llama"),),
    )

    path = save_provider_settings(settings, paths)
    loaded = load_provider_settings(paths)

    assert path == tmp_path / ".tau" / "providers.json"
    assert json.loads(path.read_text())["schema_version"] == 2
    assert loaded == settings


def test_legacy_provider_model_cost_tiers_round_trip() -> None:
    raw = {
        "default_provider": "local",
        "providers": [
            {
                "type": "openai-compatible",
                "name": "local",
                "base_url": "http://localhost:11434/v1",
                "api_key_env": "LOCAL_API_KEY",
                "models": ["qwen"],
                "default_model": "qwen",
                "model_metadata": {
                    "qwen": {
                        "cost": {
                            "input": 0.3,
                            "output": 1.2,
                            "cacheRead": 0.06,
                            "cacheWrite": 0,
                        },
                        "cost_tiers": [
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
                        ],
                    }
                },
            }
        ],
        "scoped_models": [],
    }

    settings = provider_settings_from_json(raw)
    provider = settings.get_provider("local")
    assert isinstance(provider, OpenAICompatibleProviderConfig)
    assert (
        provider.model_metadata["qwen"].to_json()["cost_tiers"]
        == raw["providers"][0]["model_metadata"]["qwen"]["cost_tiers"]
    )


def test_legacy_provider_cost_tier_accepts_one_hour_cache_write_rate() -> None:
    raw = {
        "default_provider": "local",
        "providers": [
            {
                "type": "openai-compatible",
                "name": "local",
                "base_url": "http://localhost:11434/v1",
                "api_key_env": "LOCAL_API_KEY",
                "models": ["qwen"],
                "default_model": "qwen",
                "model_metadata": {
                    "qwen": {
                        "cost_tiers": [
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
                            },
                        ],
                    }
                },
            }
        ],
        "scoped_models": [],
    }

    settings = provider_settings_from_json(raw)
    provider = settings.get_provider("local")
    assert isinstance(provider, OpenAICompatibleProviderConfig)
    tiers = provider.model_metadata["qwen"].cost_tiers
    assert tiers[0].cost["cacheWrite1h"] == 0.6
    # Tiers without the key omit it, so billing can fall back to cacheWrite.
    assert "cacheWrite1h" not in tiers[1].cost
    assert (
        provider.model_metadata["qwen"].to_json()["cost_tiers"]
        == raw["providers"][0]["model_metadata"]["qwen"]["cost_tiers"]
    )


@pytest.mark.parametrize(
    ("cost_tiers", "match"),
    [
        (
            [
                {
                    "max_input_tokens": 512000,
                    "input": 0.3,
                    "output": 1.2,
                    "cacheRead": 0.06,
                    "cacheWrite": 0,
                }
            ],
            "final cost tier must omit max_input_tokens",
        ),
        (
            [
                {
                    "max_input_tokens": 512000,
                    "input": 0.3,
                    "output": 1.2,
                    "cacheRead": 0.06,
                    "cacheWrite": 0,
                },
                {
                    "max_input_tokens": 400000,
                    "input": 0.4,
                    "output": 1.6,
                    "cacheRead": 0.08,
                    "cacheWrite": 0,
                },
                {
                    "input": 0.6,
                    "output": 2.4,
                    "cacheRead": 0.12,
                    "cacheWrite": 0,
                },
            ],
            "limits must be strictly increasing",
        ),
        (
            [
                {
                    "unexpected": 1,
                    "input": 0.3,
                    "output": 1.2,
                    "cacheRead": 0.06,
                    "cacheWrite": 0,
                }
            ],
            "unknown fields",
        ),
        (
            [
                {
                    "input": -0.3,
                    "output": 1.2,
                    "cacheRead": 0.06,
                    "cacheWrite": 0,
                }
            ],
            "0 or greater",
        ),
    ],
)
def test_legacy_provider_rejects_invalid_cost_tiers(
    cost_tiers: list[dict[str, object]],
    match: str,
) -> None:
    raw = {
        "default_provider": "local",
        "providers": [
            {
                "type": "openai-compatible",
                "name": "local",
                "base_url": "http://localhost:11434/v1",
                "api_key_env": "LOCAL_API_KEY",
                "models": ["qwen"],
                "default_model": "qwen",
                "model_metadata": {"qwen": {"cost_tiers": cost_tiers}},
            }
        ],
    }

    with pytest.raises(ProviderConfigError, match=match):
        provider_settings_from_json(raw)


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


def test_provider_settings_parses_scoped_models() -> None:
    settings = provider_settings_from_json(
        {
            "default_provider": "local",
            "providers": [
                {
                    "type": "openai-compatible",
                    "name": "local",
                    "base_url": "http://localhost:11434/v1",
                    "api_key_env": "LOCAL_API_KEY",
                    "models": ["qwen", "llama"],
                    "default_model": "qwen",
                    "context_windows": {"qwen": 64000},
                }
            ],
            "scoped_models": [
                {"provider": "local", "model": "qwen"},
                {"provider": "local", "model": "qwen"},
                {"provider": "local", "model": "llama"},
            ],
        }
    )

    assert settings.get_provider("local").context_windows == {"qwen": 64000}
    assert settings.scoped_models == (
        ScopedModelConfig(provider="local", model="qwen"),
        ScopedModelConfig(provider="local", model="llama"),
    )


def test_upsert_openai_compatible_provider_replaces_and_sets_default() -> None:
    settings = ProviderSettings(
        scoped_models=(ScopedModelConfig(provider="openai", model="gpt-5.5"),)
    )
    provider = OpenAICompatibleProviderConfig(
        name="local",
        base_url="http://localhost:11434/v1",
        api_key_env="LOCAL_API_KEY",
        models=("qwen",),
        default_model="qwen",
    )

    updated = upsert_openai_compatible_provider(settings, provider, set_default=True)
    replaced = upsert_openai_compatible_provider(
        updated,
        OpenAICompatibleProviderConfig(
            name="local",
            base_url="http://localhost:11434/v1",
            api_key_env="LOCAL_API_KEY",
            models=("llama",),
            default_model="llama",
        ),
        set_default=True,
    )

    assert updated.default_provider == "local"
    assert [item.name for item in updated.providers] == sorted(
        [provider.name for provider in settings.providers] + ["local"]
    )
    assert replaced.get_provider("local").default_model == "llama"
    assert replaced.scoped_models == settings.scoped_models


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
    # Mirrors the catalog kimi-code entry: k3 supports low, high, and xhigh
    # mapped to "low", "high", "max" respectively.
    return OpenAICompatibleProviderConfig(
        name="kimi-code",
        models=("k3", "kimi-for-coding"),
        default_model="k3",
        thinking_levels=("low", "medium", "high", "xhigh"),
        thinking_default="xhigh",
        thinking_parameter="reasoning_effort",
        model_metadata={
            "k3": ProviderModelMetadata(
                reasoning=True,
                thinking_level_map={
                    "off": None,
                    "minimal": None,
                    "low": "low",
                    "medium": None,
                    "high": "high",
                    "xhigh": "max",
                },
            ),
            "kimi-for-coding": ProviderModelMetadata(
                reasoning=True,
                thinking_level_map={
                    "off": None,
                    "minimal": None,
                    "low": None,
                    "high": None,
                    "xhigh": None,
                },
            ),
        },
    )


def test_resolve_startup_thinking_level_uses_k3_max_default() -> None:
    provider = _kimi_code_like_provider()

    # The current global startup preference is high, which K3 supports.
    assert resolve_startup_thinking_level(provider, "k3") == "high"


def test_resolve_startup_thinking_level_prefers_remembered_model_default() -> None:
    provider = _kimi_code_like_provider()
    remembered = OpenAICompatibleProviderConfig(
        name=provider.name,
        models=provider.models,
        default_model=provider.default_model,
        thinking_levels=provider.thinking_levels,
        thinking_default=provider.thinking_default,
        thinking_parameter=provider.thinking_parameter,
        thinking_defaults={"k3": "xhigh"},
        model_metadata=provider.model_metadata,
    )

    assert resolve_startup_thinking_level(remembered, "k3") == "xhigh"


def test_resolve_startup_thinking_level_keeps_supported_default() -> None:
    provider = _kimi_code_like_provider()

    # kimi-for-coding supports global medium but not K3's xhigh default.
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


def test_set_default_provider_model_rejects_model_not_declared_for_provider() -> None:
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
        set_default_provider_model(settings, provider_name="local", model="llama")


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
    monkeypatch.setenv("LOCAL_API_KEY", "test-key")
    provider = OpenAICompatibleProviderConfig(
        name="local",
        base_url="http://localhost:11434/v1/",
        api_key_env="LOCAL_API_KEY",
        models=("qwen",),
        default_model="qwen",
    )

    config = openai_compatible_config_from_provider(provider)

    assert config.api_key == "test-key"
    assert config.provider_name == "local"
    assert config.base_url == "http://localhost:11434/v1"
    assert config.headers == {}
    assert config.timeout_seconds == 60.0
    assert config.max_retries == 2
    assert config.max_retry_delay_seconds == 1.0
    assert config.response_provider_header is None


def test_huggingface_runtime_config_captures_inference_provider_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HF_TEST_TOKEN", "test-key")
    provider = OpenAICompatibleProviderConfig(
        name="huggingface",
        base_url="https://router.huggingface.co/v1",
        api_key_env="HF_TEST_TOKEN",
        models=("test-model",),
        default_model="test-model",
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
        timeout_seconds=180,
        max_retries=3,
        max_retry_delay_seconds=0.25,
    )

    config = openai_compatible_config_from_provider(provider)

    assert config.timeout_seconds == 180
    assert config.max_retries == 3
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
        headers={"X-HF-Bill-To": "my-org"},
    )

    config = openai_compatible_config_from_provider(provider)

    assert config.headers == {"X-HF-Bill-To": "my-org"}


def test_openai_compatible_config_from_provider_sets_reasoning_effort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCAL_API_KEY", "test-key")
    provider = OpenAICompatibleProviderConfig(
        name="local",
        base_url="http://localhost:11434/v1/",
        api_key_env="LOCAL_API_KEY",
        models=("reasoner", "plain"),
        default_model="reasoner",
        thinking_levels=("off", "low", "high"),
        thinking_models=("reasoner",),
        thinking_default="low",
        thinking_parameter="reasoning_effort",
    )

    reasoner = openai_compatible_config_from_provider(
        provider,
        model="reasoner",
        thinking_level="off",
    )
    plain = openai_compatible_config_from_provider(
        provider,
        model="plain",
        thinking_level="high",
    )

    assert reasoner.reasoning_effort == "none"
    assert plain.reasoning_effort is None


@pytest.mark.parametrize(
    ("level", "expected_effort"),
    [("low", "low"), ("high", "high"), ("xhigh", "xhigh")],
)
def test_kimi_k3_maps_thinking_levels_to_reasoning_effort(
    monkeypatch: pytest.MonkeyPatch,
    level: ThinkingLevel,
    expected_effort: str,
) -> None:
    monkeypatch.setenv("OPENCODE_API_KEY", "test-key")
    settings = load_provider_settings(TauPaths(home=Path("/missing")))
    provider = settings.get_provider("opencode-go")

    config = openai_compatible_config_from_provider(
        provider,
        model="kimi-k3",
        thinking_level=level,
    )

    assert provider_thinking_levels(provider, model="kimi-k3") == (
        "low",
        "medium",
        "high",
        "xhigh",
    )
    assert config.reasoning_effort == expected_effort


def test_openai_compatible_config_from_provider_rejects_unsupported_thinking_level(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCAL_API_KEY", "test-key")
    provider = OpenAICompatibleProviderConfig(
        name="local",
        base_url="http://localhost:11434/v1/",
        api_key_env="LOCAL_API_KEY",
        models=("reasoner",),
        default_model="reasoner",
        thinking_levels=("low", "high"),
        thinking_parameter="reasoning_effort",
    )

    with pytest.raises(ProviderConfigError, match="not available"):
        openai_compatible_config_from_provider(
            provider,
            model="reasoner",
            thinking_level="medium",
        )


def test_openai_compatible_config_from_provider_uses_stored_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "env-key")
    provider = OpenAICompatibleProviderConfig(
        name="openrouter",
        base_url="https://openrouter.ai/api/v1",
        api_key_env="OPENROUTER_API_KEY",
        credential_name="openrouter",
        models=("openai/gpt-4.1-mini",),
        default_model="openai/gpt-4.1-mini",
    )

    class FakeCredentials:
        def get(self, name: str) -> str | None:
            return "stored-key" if name == "openrouter" else None

    config = openai_compatible_config_from_provider(
        provider,
        credential_reader=FakeCredentials(),
    )

    assert config.api_key == "stored-key"


def test_openai_compatible_config_from_provider_falls_back_to_env_when_stored_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "env-key")
    provider = OpenAICompatibleProviderConfig(
        name="openrouter",
        base_url="https://openrouter.ai/api/v1",
        api_key_env="OPENROUTER_API_KEY",
        credential_name="openrouter",
        models=("openai/gpt-4.1-mini",),
        default_model="openai/gpt-4.1-mini",
    )

    class FakeCredentials:
        def get(self, name: str) -> str | None:
            return None

    config = openai_compatible_config_from_provider(provider, credential_reader=FakeCredentials())

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
    parameter: str,
    expected: str,
) -> None:
    monkeypatch.setenv("LOCAL_API_KEY", "test-key")
    provider = OpenAICompatibleProviderConfig(
        name="local",
        base_url="http://localhost:11434/v1/",
        api_key_env="LOCAL_API_KEY",
        models=("reasoner",),
        default_model="reasoner",
        thinking_levels=("low", "high"),
        thinking_parameter=parameter,  # type: ignore[arg-type]
    )

    config = openai_compatible_config_from_provider(
        provider,
        model="reasoner",
        thinking_level="high",
    )

    assert config.reasoning_effort == "high"
    assert config.reasoning_effort_parameter == expected


def test_provider_settings_from_json_loads_headers() -> None:
    settings = provider_settings_from_json(
        {
            "default_provider": "huggingface",
            "providers": [
                {
                    "type": "openai-compatible",
                    "name": "huggingface",
                    "base_url": "https://router.huggingface.co/v1",
                    "api_key_env": "HF_TOKEN",
                    "credential_name": "huggingface",
                    "models": ["Qwen/Qwen3-Coder"],
                    "default_model": "Qwen/Qwen3-Coder",
                    "headers": {"X-HF-Bill-To": "my-org"},
                }
            ],
        }
    )

    provider = settings.get_provider("huggingface")

    assert isinstance(provider, OpenAICompatibleProviderConfig)
    assert provider.headers == {"X-HF-Bill-To": "my-org"}


def test_provider_settings_from_json_loads_custom_thinking_capabilities() -> None:
    settings = provider_settings_from_json(
        {
            "default_provider": "local",
            "providers": [
                {
                    "type": "openai-compatible",
                    "name": "local",
                    "base_url": "http://localhost:11434/v1",
                    "api_key_env": "LOCAL_API_KEY",
                    "models": ["reasoner", "plain"],
                    "default_model": "reasoner",
                    "thinking_levels": ["off", "low", "high"],
                    "thinking_models": ["reasoner"],
                    "thinking_default": "low",
                    "thinking_parameter": "reasoning_effort",
                    "thinking_defaults": {"reasoner": "high"},
                }
            ],
        }
    )

    provider = settings.get_provider("local")

    assert isinstance(provider, OpenAICompatibleProviderConfig)
    assert provider_thinking_levels(provider, model="reasoner") == ("off", "low", "high")
    assert provider_thinking_levels(provider, model="plain") == ()
    assert provider_default_thinking_level(provider, model="reasoner") == "low"
    assert provider.thinking_defaults == {"reasoner": "high"}
    assert provider.to_json()["thinking_parameter"] == "reasoning_effort"


def test_set_provider_thinking_level_updates_preference() -> None:
    provider = OpenAICompatibleProviderConfig(
        name="local",
        models=("reasoner",),
        default_model="reasoner",
        thinking_levels=("low", "high"),
        thinking_models=("reasoner",),
        thinking_default="low",
        thinking_parameter="reasoning_effort",
    )
    settings = ProviderSettings(default_provider="local", providers=(provider,))

    updated = set_provider_thinking_level(
        settings,
        provider_name="local",
        model="reasoner",
        thinking_level="high",
    )

    assert updated.get_provider("local").thinking_defaults == {"reasoner": "high"}
    assert updated.to_json()["provider_preferences"]["local"]["thinking_defaults"] == {
        "reasoner": "high"
    }


def test_provider_settings_from_json_loads_openai_codex_provider() -> None:
    settings = provider_settings_from_json(
        {
            "default_provider": "openai-codex",
            "providers": [
                {
                    "type": "openai-codex",
                    "name": "openai-codex",
                    "base_url": "https://chatgpt.com/backend-api",
                    "api_key_env": "OPENAI_CODEX_ACCESS_TOKEN",
                    "credential_name": "openai-codex",
                    "models": ["gpt-5.5", "gpt-5.4"],
                    "default_model": "gpt-5.5",
                    "headers": {"X-Test": "enabled"},
                }
            ],
        }
    )

    provider = settings.get_provider("openai-codex")

    assert isinstance(provider, OpenAICodexProviderConfig)
    assert provider.default_model == "gpt-5.5"
    assert provider.headers == {"X-Test": "enabled"}


def test_load_provider_settings_does_not_restore_stale_codex_builtin_models(
    tmp_path: Path,
) -> None:
    tau_home = tmp_path / ".tau"
    tau_home.mkdir()
    (tau_home / "providers.json").write_text(
        json.dumps(
            {
                "default_provider": "openai-codex",
                "providers": [
                    {
                        "type": "openai-codex",
                        "name": "openai-codex",
                        "base_url": "https://chatgpt.com/backend-api",
                        "api_key_env": "OPENAI_CODEX_ACCESS_TOKEN",
                        "credential_name": "openai-codex",
                        "models": ["gpt-5", "gpt-5.5"],
                        "default_model": "gpt-5",
                        "thinking_levels": ["off", "minimal", "low", "medium", "high", "xhigh"],
                        "thinking_models": ["gpt-5.5"],
                        "thinking_default": "medium",
                        "thinking_parameter": "reasoning.effort",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    settings = load_provider_settings(TauPaths(home=tau_home))
    provider = settings.get_provider("openai-codex")

    assert provider.models == ("gpt-5.6-luna", "gpt-5.6-sol")
    assert provider.default_model == "gpt-5.6-luna"
    assert provider_thinking_levels(provider, model="gpt-5.6-luna") == (
        "low",
        "medium",
        "high",
        "xhigh",
    )
    migrated = json.loads((tau_home / "providers.json").read_text())
    assert migrated["schema_version"] == 2
    assert "providers" not in migrated
    assert (tau_home / "providers.json.bak").exists()
    assert not (tau_home / "catalog.toml").exists()


def test_load_provider_settings_merges_builtin_model_catalog(tmp_path: Path) -> None:
    tau_home = tmp_path / ".tau"
    tau_home.mkdir()
    (tau_home / "providers.json").write_text(
        json.dumps(
            {
                "default_provider": "opencode-go",
                "providers": [
                    {
                        "type": "openai-compatible",
                        "name": "opencode-go",
                        "base_url": "https://opencode.ai/zen/go/v1",
                        "api_key_env": "OPENCODE_API_KEY",
                        "credential_name": "opencode",
                        "models": ["gpt-5.6-luna", "custom/coder"],
                        "default_model": "gpt-5.6-luna",
                        "headers": {"X-Test": "my-org"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    settings = load_provider_settings(TauPaths(home=tau_home))

    provider = settings.get_provider("opencode-go")
    assert provider.default_model == "gpt-5.6-luna"
    assert provider.headers == {"X-Test": "my-org"}
    assert provider.context_windows["gpt-5.6-luna"] == 1_000_000
    assert "deepseek-v4-flash" in provider.models
    assert "custom/coder" not in provider.models


def test_load_provider_settings_restores_builtin_providers_with_stored_credentials(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(provider_config, "environ", {})
    tau_home = tmp_path / ".tau"
    tau_home.mkdir()
    (tau_home / "providers.json").write_text(
        json.dumps(
            {
                "default_provider": "local",
                "providers": [
                    {
                        "type": "openai-compatible",
                        "name": "local",
                        "base_url": "http://localhost:11434/v1",
                        "api_key_env": "LOCAL_API_KEY",
                        "credential_name": None,
                        "models": ["qwen"],
                        "default_model": "qwen",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    store = FileCredentialStore(tau_home / "credentials.json")
    store.set("opencode", "stored-opencode-key")
    store.set_oauth(
        "openai-codex",
        OAuthCredential(
            access="access-token",
            refresh="refresh-token",
            expires=123456,
            account_id="account-1",
        ),
    )

    settings = load_provider_settings(TauPaths(home=tau_home))

    assert {provider.name for provider in settings.providers} == {
        "local",
        "openai-codex",
        "opencode-go",
        "opencode",
    }
    assert settings.default_provider == "local"
    assert settings.get_provider("opencode-go").credential_name == "opencode"
    assert settings.get_provider("openai-codex").credential_name == "openai-codex"


def test_load_provider_settings_restores_builtin_credential_name(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(provider_config, "environ", {})
    tau_home = tmp_path / ".tau"
    tau_home.mkdir()
    (tau_home / "providers.json").write_text(
        json.dumps(
            {
                "default_provider": "opencode-go",
                "providers": [
                    {
                        "type": "openai-compatible",
                        "name": "opencode-go",
                        "base_url": "https://opencode.ai/zen/go/v1",
                        "api_key_env": "OPENCODE_API_KEY",
                        "credential_name": None,
                        "models": ["gpt-5.6-luna"],
                        "default_model": "gpt-5.6-luna",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    class FakeCredentials:
        def get(self, name: str) -> str | None:
            return "stored-key" if name == "opencode" else None

    settings = load_provider_settings(TauPaths(home=tau_home))
    provider = settings.get_provider("opencode-go")

    assert isinstance(provider, OpenAICompatibleProviderConfig)
    assert provider.credential_name == "opencode"
    assert provider.context_windows["gpt-5.6-luna"] == 1_000_000
    config = openai_compatible_config_from_provider(
        provider,
        credential_reader=FakeCredentials(),
    )
    assert config.api_key == "stored-key"


def test_load_provider_settings_migrates_custom_provider_to_catalog(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(provider_config, "environ", {})
    tau_home = tmp_path / ".tau"
    tau_home.mkdir()
    original = {
        "default_provider": "local",
        "providers": [
            {
                "type": "openai-compatible",
                "name": "local",
                "base_url": "http://localhost:11434/v1",
                "api_key_env": "LOCAL_API_KEY",
                "credential_name": None,
                "models": ["qwen"],
                "default_model": "qwen",
                "context_windows": {"qwen": 64000},
                "headers": {"X-Test": "yes"},
            }
        ],
    }
    (tau_home / "providers.json").write_text(json.dumps(original), encoding="utf-8")

    settings = load_provider_settings(TauPaths(home=tau_home))

    provider = settings.get_provider("local")
    assert provider.context_windows == {"qwen": 64_000}
    assert provider.headers == {"X-Test": "yes"}
    assert json.loads((tau_home / "providers.json.bak").read_text()) == original
    migrated = json.loads((tau_home / "providers.json").read_text())
    assert migrated["schema_version"] == 2
    assert migrated["provider_preferences"]["local"]["default_model"] == "qwen"
    catalog = (tau_home / "catalog.toml").read_text()
    assert 'name = "local"' in catalog
    assert 'models = ["qwen"]' in catalog


def test_legacy_migration_aborts_before_changes_when_backup_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(provider_config, "environ", {})
    tau_home = tmp_path / ".tau"
    tau_home.mkdir()
    original = {
        "default_provider": "local",
        "providers": [
            {
                "type": "openai-compatible",
                "name": "local",
                "base_url": "http://localhost:11434/v1",
                "api_key_env": "LOCAL_API_KEY",
                "models": ["qwen"],
                "default_model": "qwen",
            }
        ],
    }
    settings_path = tau_home / "providers.json"
    settings_path.write_text(json.dumps(original), encoding="utf-8")

    def fail_backup(*_args: object, **_kwargs: object) -> None:
        raise PermissionError("backup denied")

    monkeypatch.setattr(provider_config, "copy2", fail_backup)

    with pytest.raises(PermissionError, match="backup denied"):
        load_provider_settings(TauPaths(home=tau_home))

    assert json.loads(settings_path.read_text()) == original
    assert not (tau_home / "providers.json.bak").exists()
    assert not (tau_home / "catalog.toml").exists()


def test_provider_settings_from_json_rejects_unknown_schema_version() -> None:
    with pytest.raises(ProviderConfigError, match="schema_version"):
        provider_settings_from_json(
            {
                "schema_version": 99,
                "default_provider": "openai",
                "provider_preferences": {},
            }
        )


def test_provider_settings_from_json_rejects_invalid_headers() -> None:
    with pytest.raises(ProviderConfigError, match="string object"):
        provider_settings_from_json(
            {
                "default_provider": "local",
                "providers": [
                    {
                        "type": "openai-compatible",
                        "name": "local",
                        "base_url": "http://localhost:11434/v1",
                        "api_key_env": "LOCAL_API_KEY",
                        "models": ["qwen"],
                        "default_model": "qwen",
                        "headers": {"X-Test": 123},
                    }
                ],
            }
        )


def test_provider_settings_from_json_rejects_invalid_timeout() -> None:
    with pytest.raises(ProviderConfigError, match="greater than 0"):
        provider_settings_from_json(
            {
                "default_provider": "local",
                "providers": [
                    {
                        "type": "openai-compatible",
                        "name": "local",
                        "base_url": "http://localhost:11434/v1",
                        "api_key_env": "LOCAL_API_KEY",
                        "models": ["qwen"],
                        "default_model": "qwen",
                        "timeout_seconds": 0,
                    }
                ],
            }
        )


def test_openai_compatible_provider_config_rejects_invalid_timeout() -> None:
    with pytest.raises(ProviderConfigError, match="greater than 0"):
        OpenAICompatibleProviderConfig(name="local", timeout_seconds=0)


def test_provider_settings_from_json_rejects_invalid_retries() -> None:
    with pytest.raises(ProviderConfigError, match="0 or greater"):
        provider_settings_from_json(
            {
                "default_provider": "local",
                "providers": [
                    {
                        "type": "openai-compatible",
                        "name": "local",
                        "base_url": "http://localhost:11434/v1",
                        "api_key_env": "LOCAL_API_KEY",
                        "models": ["qwen"],
                        "default_model": "qwen",
                        "max_retries": -1,
                    }
                ],
            }
        )


def test_openai_compatible_provider_config_rejects_invalid_retries() -> None:
    with pytest.raises(ProviderConfigError, match="0 or greater"):
        OpenAICompatibleProviderConfig(name="local", max_retries=-1)
    with pytest.raises(ProviderConfigError, match="0 or greater"):
        OpenAICompatibleProviderConfig(name="local", max_retry_delay_seconds=-1)
