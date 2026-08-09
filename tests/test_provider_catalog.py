"""Tests for the TOML-backed provider catalog."""

from __future__ import annotations

from pathlib import Path

import pytest

from tau_coding.catalog_loader import (
    CatalogError,
    builtin_catalog,
    builtin_catalog_resource_text,
    effective_catalog,
    save_user_catalog_entries,
    user_catalog_path,
)
from tau_coding.paths import TauPaths
from tau_coding.provider_catalog import (
    BUILTIN_PROVIDER_CATALOG,
    builtin_provider_entry,
    model_cost_for_input_tokens,
)
from tau_coding.provider_config import load_provider_settings

VALID_PROVIDER = """
[[providers]]
name = "nebius"
display_name = "Nebius AI Studio"
kind = "openai-compatible"
base_url = "https://api.studio.nebius.ai/v1"
api_key_env = "NEBIUS_API_KEY"
credential_name = "nebius"
models = ["deepseek-ai/DeepSeek-V4-Pro", "Qwen/Qwen3-Coder-480B-A35B-Instruct"]
default_model = "deepseek-ai/DeepSeek-V4-Pro"
docs_url = "https://studio.nebius.ai/docs"
thinking_levels = ["off", "low", "medium", "high"]
thinking_models = ["deepseek-ai/DeepSeek-V4-Pro"]
thinking_default = "medium"
thinking_parameter = "reasoning_effort"

[providers.context_windows]
"deepseek-ai/DeepSeek-V4-Pro" = 163840
"""


def _write_user_catalog(tau_home: Path, body: str) -> TauPaths:
    paths = TauPaths(home=tau_home)
    tau_home.mkdir(parents=True, exist_ok=True)
    user_catalog_path(paths).write_text(f"schema_version = 1\n{body}", encoding="utf-8")
    return paths


def test_builtin_catalog_matches_expected_providers() -> None:
    assert [entry.name for entry in BUILTIN_PROVIDER_CATALOG] == [
        "openai-codex",
        "opencode-go",
        "opencode",
    ]

 def test_builtin_catalog_oauth_and_opencode_auth_methods() -> None:
     codex = builtin_provider_entry("openai-codex")
     copilot = builtin_provider_entry("github-copilot")
     opencode_go = builtin_provider_entry("opencode-go")
     opencode = builtin_provider_entry("opencode")

     assert codex is not None and codex.auth_methods == ("oauth",)
     assert copilot is not None and copilot.auth_methods == ("oauth",)
     assert opencode_go is not None and opencode_go.auth_methods == ("api_key",)
     assert opencode is not None and opencode.auth_methods == ("api_key",)
     assert opencode_go.api_key_env == "OPENCODE_API_KEY"
     assert opencode.api_key_env == "OPENCODE_API_KEY"


@pytest.mark.parametrize(
    ("provider_name", "vision_models"),
    [
        (
            "openai-codex",
            {
                "gpt-5.6-sol",
                "gpt-5.6-luna",
            },
        ),
        (
            "opencode-go",
            {
                "gpt-5.6-luna",
                "kimi-k3",
            },
        ),
        (
            "opencode",
            {
                "gpt-5.6-luna",
                "kimi-k3",
            },
        ),
    ],
)
def test_sparse_provider_catalogs_declare_model_input_modalities(
    provider_name: str, vision_models: set[str]
) -> None:
    provider = builtin_provider_entry(provider_name)

     assert provider is not None
     assert set(provider.model_metadata) == set(provider.models)
     assert {
         model for model, metadata in provider.model_metadata.items() if "image" in metadata.input
     } == vision_models


def test_builtin_catalog_entries_match_context_windows_and_output_limits() -> None:
    expected = {
        "openai-codex": {
            "gpt-5.6-sol": (1_000_000, 128_000),
            "gpt-5.6-luna": (1_000_000, 128_000),
        },
        "opencode-go": {
            "deepseek-v4-flash": (1_000_000, 384_000),
            "gpt-5.6-luna": (1_000_000, 128_000),
            "kimi-k3": (1_000_000, None),
        },
        "opencode": {
            "deepseek-v4-flash": (1_000_000, 384_000),
            "gpt-5.6-luna": (1_000_000, 128_000),
            "kimi-k3": (1_000_000, None),
        },
    }

    for provider_name, models in expected.items():
        entry = builtin_provider_entry(provider_name)
        assert entry is not None
        assert entry.context_windows == {model: values[0] for model, values in models.items()}
        for model, (context_window, max_tokens) in models.items():
            metadata = entry.model_metadata[model]
            assert metadata.context_window == context_window
            assert metadata.max_tokens == max_tokens


def test_builtin_catalog_declares_current_model_modalities() -> None:
    codex = builtin_provider_entry("openai-codex")
    opencode = builtin_provider_entry("opencode")

    assert codex is not None
    assert opencode is not None
    assert {
        model for model, metadata in codex.model_metadata.items() if "image" in metadata.input
    } == set(codex.models)
    assert {
        model for model, metadata in opencode.model_metadata.items() if "image" in metadata.input
    } == {"gpt-5.6-luna", "kimi-k3"}
    assert opencode.model_metadata["deepseek-v4-flash"].input == ("text",)


def test_builtin_catalog_auth_and_thinking_metadata() -> None:
    codex = builtin_provider_entry("openai-codex")
    opencode = builtin_provider_entry("opencode")

    assert codex is not None
    assert opencode is not None
    assert codex.auth_methods == ("oauth",)
    assert opencode.auth_methods == ("api_key",)
    assert opencode.api == "openai-completions"
    assert codex.thinking_levels == ("low", "medium", "high", "xhigh")
    assert codex.thinking_default == "xhigh"
    assert codex.thinking_parameter == "reasoning.effort"
    assert opencode.thinking_levels == ("low", "medium", "high", "xhigh")
    assert opencode.thinking_default == "xhigh"
    assert opencode.thinking_parameter == "reasoning_effort"
    assert codex.model_metadata["gpt-5.6-sol"].thinking_level_map == {"xhigh": "xhigh"}
    assert codex.model_metadata["gpt-5.6-luna"].thinking_level_map == {"xhigh": "xhigh"}


def test_builtin_catalog_entries_are_internally_consistent() -> None:
    for entry in builtin_catalog():
        assert entry.default_model in entry.models
        assert set(entry.thinking_models) <= set(entry.models)
        assert set(entry.context_windows or {}) <= set(entry.models)
        if entry.thinking_default is not None:
            assert entry.thinking_levels is not None
            assert entry.thinking_default in entry.thinking_levels


def test_builtin_catalog_resource_is_packaged() -> None:
    assert "[[providers]]" in builtin_catalog_resource_text()


def test_effective_catalog_without_user_file_is_builtin(tmp_path: Path) -> None:
    paths = TauPaths(home=tmp_path / ".tau")
    assert effective_catalog(paths) == builtin_catalog()


def test_user_catalog_adds_new_provider(tmp_path: Path) -> None:
    paths = _write_user_catalog(tmp_path / ".tau", VALID_PROVIDER)
    catalog = effective_catalog(paths)
    assert [entry.name for entry in catalog[:-1]] == [e.name for e in builtin_catalog()]
    entry = catalog[-1]
    assert entry.name == "nebius"
    assert entry.default_model == "deepseek-ai/DeepSeek-V4-Pro"
    assert entry.context_windows == {"deepseek-ai/DeepSeek-V4-Pro": 163_840}
    assert entry.thinking_levels == ("off", "low", "medium", "high")


def test_user_catalog_overlays_builtin_provider(tmp_path: Path) -> None:
    paths = _write_user_catalog(
        tmp_path / ".tau",
        """
[[providers]]
name = "opencode"
models = ["custom-model"]
default_model = "custom-model"

[providers.context_windows]
"custom-model" = 500000
""",
    )
    entry = next(e for e in effective_catalog(paths) if e.name == "opencode")
    assert entry.models[0] == "custom-model"
    assert "gpt-5.6-luna" in entry.models
    assert entry.default_model == "custom-model"
    assert entry.context_windows is not None
    assert entry.context_windows["custom-model"] == 500_000
    assert entry.context_windows["gpt-5.6-luna"] == 1_000_000
    # Untouched fields come from the builtin entry.
    assert entry.base_url == "https://opencode.ai/zen/v1"
    assert entry.thinking_parameter == "reasoning_effort"


def test_user_catalog_thinking_fields_replace_as_group(tmp_path: Path) -> None:
    paths = _write_user_catalog(
        tmp_path / ".tau",
        """
[[providers]]
name = "opencode"
thinking_levels = ["low", "high"]
thinking_default = "high"
""",
    )
    entry = next(e for e in effective_catalog(paths) if e.name == "opencode")
    assert entry.thinking_levels == ("low", "high")
    assert entry.thinking_default == "high"
    assert entry.thinking_models == ()
    assert entry.thinking_parameter is None


def test_user_catalog_overlays_and_serializes_cost_tiers(tmp_path: Path) -> None:
    paths = _write_user_catalog(
        tmp_path / ".tau",
        """
[[providers]]
name = "opencode"

[providers.model_metadata."deepseek-v4-flash"]
cost_tiers = [
  { max_input_tokens = 400000, input = 0.2, output = 1.0, cacheRead = 0.04, cacheWrite = 0 },
  { input = 0.5, output = 2.0, cacheRead = 0.1, cacheWrite = 0 },
]
""",
    )
    entry = next(e for e in effective_catalog(paths) if e.name == "opencode")
    metadata = entry.model_metadata["deepseek-v4-flash"]
    assert model_cost_for_input_tokens(metadata, 400_000) == {
        "input": 0.2,
        "output": 1.0,
        "cacheRead": 0.04,
        "cacheWrite": 0,
    }
    long_context_cost = {
        "input": 0.5,
        "output": 2.0,
        "cacheRead": 0.1,
        "cacheWrite": 0,
    }
    assert model_cost_for_input_tokens(metadata, 400_001) == long_context_cost

    save_user_catalog_entries([entry], paths)
    reloaded = next(e for e in effective_catalog(paths) if e.name == "opencode")
    assert (
        model_cost_for_input_tokens(reloaded.model_metadata["deepseek-v4-flash"], 400_001)
        == long_context_cost
    )


def test_user_catalog_cost_tier_accepts_one_hour_cache_write_rate(tmp_path: Path) -> None:
    paths = _write_user_catalog(
        tmp_path / ".tau",
        """
[[providers]]
name = "opencode"

[providers.model_metadata."deepseek-v4-flash"]
cost_tiers = [
  { max_input_tokens = 400000, input = 0.2, output = 1.0, cacheRead = 0.04, cacheWrite = 0.25 },
  { input = 0.5, output = 2.0, cacheRead = 0.1, cacheWrite = 0.6, cacheWrite1h = 1.0 },
]
""",
    )
    entry = next(e for e in effective_catalog(paths) if e.name == "opencode")
    metadata = entry.model_metadata["deepseek-v4-flash"]
    assert model_cost_for_input_tokens(metadata, 400_001) == {
        "input": 0.5,
        "output": 2.0,
        "cacheRead": 0.1,
        "cacheWrite": 0.6,
        "cacheWrite1h": 1.0,
    }
    # Tiers without the key omit it, so billing can fall back to cacheWrite.
    assert model_cost_for_input_tokens(metadata, 400_000) == {
        "input": 0.2,
        "output": 1.0,
        "cacheRead": 0.04,
        "cacheWrite": 0.25,
    }


def test_user_catalog_rejects_bounded_final_cost_tier(tmp_path: Path) -> None:
    paths = _write_user_catalog(
        tmp_path / ".tau",
        """
[[providers]]
name = "opencode"

[providers.model_metadata."deepseek-v4-flash"]
cost_tiers = [
  { max_input_tokens = 512000, input = 0.3, output = 1.2, cacheRead = 0.06, cacheWrite = 0 },
]
""",
    )
    with pytest.raises(CatalogError, match="final tier must omit max_input_tokens"):
        effective_catalog(paths)


def test_user_catalog_rejects_unknown_keys(tmp_path: Path) -> None:
    paths = _write_user_catalog(tmp_path / ".tau", VALID_PROVIDER.replace("docs_url", "docs_ur1"))
    with pytest.raises(CatalogError, match=r"providers\.nebius"):
        effective_catalog(paths)


def test_user_catalog_rejects_default_model_not_in_models(tmp_path: Path) -> None:
    paths = _write_user_catalog(
        tmp_path / ".tau",
        VALID_PROVIDER.replace(
            'default_model = "deepseek-ai/DeepSeek-V4-Pro"', 'default_model = "missing"'
        ),
    )
    with pytest.raises(CatalogError, match=r"providers\.nebius\.default_model"):
        effective_catalog(paths)


@pytest.mark.parametrize(
    ("body", "match"),
    [
        (
            VALID_PROVIDER.replace('display_name = "Nebius AI Studio"', 'display_name = ""'),
            r"providers\.nebius\.display_name",
        ),
        (
            VALID_PROVIDER.replace(
                'models = ["deepseek-ai/DeepSeek-V4-Pro", "Qwen/Qwen3-Coder-480B-A35B-Instruct"]',
                'models = [""]',
            ),
            r"providers\.nebius\.models",
        ),
        (
            VALID_PROVIDER.replace('"deepseek-ai/DeepSeek-V4-Pro" = 163840', '"" = 163840'),
            r"providers\.nebius\.context_windows",
        ),
        (
            VALID_PROVIDER.replace(
                '"deepseek-ai/DeepSeek-V4-Pro" = 163840',
                '"deepseek-ai/DeepSeek-V4-Pro" = 0',
            ),
            r"providers\.nebius\.context_windows",
        ),
        (
            VALID_PROVIDER.replace(
                '"deepseek-ai/DeepSeek-V4-Pro" = 163840',
                '"deepseek-ai/DeepSeek-V4-Pro" = -1',
            ),
            r"providers\.nebius\.context_windows",
        ),
        (
            VALID_PROVIDER.replace(
                '"deepseek-ai/DeepSeek-V4-Pro" = 163840',
                '"deepseek-ai/DeepSeek-V4-Pro" = true',
            ),
            r"providers\.nebius\.context_windows",
        ),
        (
            VALID_PROVIDER.replace(
                '"deepseek-ai/DeepSeek-V4-Pro" = 163840',
                '"deepseek-ai/DeepSeek-V4-Pro" = "163840"',
            ),
            r"providers\.nebius\.context_windows",
        ),
    ],
)
def test_user_catalog_rejects_empty_and_coerced_values(
    tmp_path: Path,
    body: str,
    match: str,
) -> None:
    paths = _write_user_catalog(tmp_path / ".tau", body)
    with pytest.raises(CatalogError, match=match):
        effective_catalog(paths)


def test_user_catalog_rejects_bad_kind(tmp_path: Path) -> None:
    paths = _write_user_catalog(
        tmp_path / ".tau", VALID_PROVIDER.replace("openai-compatible", "grpc")
    )
    with pytest.raises(CatalogError, match="kind"):
        effective_catalog(paths)


def test_user_catalog_rejects_malformed_toml(tmp_path: Path) -> None:
    paths = _write_user_catalog(tmp_path / ".tau", "[[providers]\nname =")
    with pytest.raises(CatalogError, match="invalid TOML"):
        effective_catalog(paths)


def test_user_catalog_provider_appears_in_settings(tmp_path: Path) -> None:
    paths = _write_user_catalog(tmp_path / ".tau", VALID_PROVIDER)
    settings = load_provider_settings(paths)
    provider = settings.get_provider("nebius")
    assert provider.base_url == "https://api.studio.nebius.ai/v1"
    assert provider.default_model == "deepseek-ai/DeepSeek-V4-Pro"


def test_user_catalog_provider_appears_with_existing_settings_file(tmp_path: Path) -> None:
    paths = _write_user_catalog(tmp_path / ".tau", VALID_PROVIDER)
    (tmp_path / ".tau" / "providers.json").write_text(
        '{"default_provider": "openai", "providers": [{"type": "openai-compatible", '
        '"name": "openai", "base_url": "https://api.openai.com/v1", '
        '"api_key_env": "OPENAI_API_KEY", "models": ["gpt-5.5"], '
        '"default_model": "gpt-5.5"}], "scoped_models": []}',
        encoding="utf-8",
    )
    settings = load_provider_settings(paths)
    assert settings.get_provider("nebius").models[0] == "deepseek-ai/DeepSeek-V4-Pro"
