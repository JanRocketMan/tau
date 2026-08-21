"""Tests for the TOML-backed provider catalog."""

from __future__ import annotations

from pathlib import Path

import pytest

from tau_coding.catalog_loader import (
    CatalogError,
    builtin_catalog,
    builtin_catalog_resource_text,
    catalog_path,
    default_provider_name,
    effective_catalog,
    effective_provider_labels,
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
thinking_parameter = "reasoning_effort"

[providers.context_windows]
"deepseek-ai/DeepSeek-V4-Pro" = 163840

[providers.model_metadata."deepseek-ai/DeepSeek-V4-Pro"]
input = ["text"]
thinking_default = "medium"
thinking_levels = ["off", "low", "medium", "high"]
"""


def _catalog_paths(tmp_path: Path, body: str | None = None) -> TauPaths:
    """Return TauPaths pointing at an isolated catalog file."""
    catalog = tmp_path / ".tau" / "catalog.toml"
    catalog.parent.mkdir(parents=True, exist_ok=True)
    catalog.write_text(
        body if body is not None else builtin_catalog_resource_text(), encoding="utf-8"
    )
    return TauPaths(home=tmp_path / ".tau", agents_home=tmp_path / ".agents", catalog_path=catalog)


def _strip_provider_labels(text: str) -> str:
    """Remove the packaged [provider_labels] table from catalog text."""
    lines = text.splitlines()
    kept: list[str] = []
    skipping = False
    for line in lines:
        if line.strip() == "[provider_labels]":
            skipping = True
            continue
        if skipping:
            if line.startswith("["):
                skipping = False
            else:
                continue
        kept.append(line)
    return "\n".join(kept)


def test_builtin_catalog_matches_expected_providers() -> None:
    assert [entry.name for entry in BUILTIN_PROVIDER_CATALOG] == [
        "openai-codex",
        "opencode-go",
    ]


def test_builtin_catalog_oauth_and_opencode_auth_methods() -> None:
    codex = builtin_provider_entry("openai-codex")
    opencode_go = builtin_provider_entry("opencode-go")

    assert codex is not None and codex.auth_methods == ("oauth",)
    assert opencode_go is not None and opencode_go.auth_methods == ("api_key",)
    assert opencode_go.api_key_env == "OPENCODE_API_KEY"
    assert opencode_go.credential_name == "opencode"


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
    expected: dict[str, dict[str, tuple[int, int | None]]] = {
        "openai-codex": {
            "gpt-5.6-sol": (272_000, 128_000),
            "gpt-5.6-luna": (272_000, 128_000),
        },
        "opencode-go": {
            "deepseek-v4-flash": (1_000_000, 384_000),
            "gpt-5.6-luna": (1_000_000, 128_000),
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
    opencode_go = builtin_provider_entry("opencode-go")

    assert codex is not None
    assert opencode_go is not None
    assert {
        model for model, metadata in codex.model_metadata.items() if "image" in metadata.input
    } == set(codex.models)
    assert {
        model for model, metadata in opencode_go.model_metadata.items() if "image" in metadata.input
    } == {"gpt-5.6-luna"}
    assert opencode_go.model_metadata["deepseek-v4-flash"].input == ("text",)


def test_builtin_catalog_auth_and_thinking_metadata() -> None:
    codex = builtin_provider_entry("openai-codex")
    opencode_go = builtin_provider_entry("opencode-go")

    assert codex is not None
    assert opencode_go is not None
    assert codex.auth_methods == ("oauth",)
    assert opencode_go.auth_methods == ("api_key",)
    assert opencode_go.api == "openai-completions"
    assert codex.thinking_parameter == "reasoning.effort"
    assert opencode_go.thinking_parameter == "reasoning_effort"
    assert codex.model_metadata["gpt-5.6-luna"].thinking_default == "xhigh"
    assert codex.model_metadata["gpt-5.6-luna"].thinking_levels == (
        "low",
        "medium",
        "high",
        "xhigh",
    )
    assert codex.model_metadata["gpt-5.6-sol"].thinking_levels == (
        "low",
        "medium",
        "high",
        "xhigh",
    )
    assert opencode_go.model_metadata["gpt-5.6-luna"].thinking_levels == (
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
    )
    assert opencode_go.model_metadata["deepseek-v4-flash"].thinking_default == "max"
    assert opencode_go.model_metadata["deepseek-v4-flash"].thinking_levels == (
        "high",
        "max",
    )


def test_builtin_catalog_declares_default_and_preferences() -> None:
    assert default_provider_name() == "openai-codex"
    codex = builtin_provider_entry("openai-codex")
    opencode_go = builtin_provider_entry("opencode-go")

    assert codex is not None
    assert opencode_go is not None
    assert codex.default_model == "gpt-5.6-sol"
    assert codex.timeout_seconds == 60.0
    assert codex.stream_idle_timeout_seconds == 600.0
    assert codex.max_retries == 2
    assert codex.max_retry_delay_seconds == 1.0
    assert codex.thinking_defaults == {"gpt-5.6-luna": "xhigh", "gpt-5.6-sol": "xhigh"}
    assert opencode_go.thinking_defaults == {
        "deepseek-v4-flash": "max",
        "gpt-5.6-luna": "xhigh",
    }


def test_builtin_catalog_entries_are_internally_consistent() -> None:
    for entry in builtin_catalog():
        assert entry.default_model in entry.models
        assert set(entry.context_windows or {}) <= set(entry.models)
        for model, metadata in entry.model_metadata.items():
            assert model in entry.models
            assert metadata.thinking_levels
            assert metadata.thinking_default is not None
            assert metadata.thinking_default in metadata.thinking_levels
        assert set(entry.thinking_defaults) <= set(entry.models)


def test_builtin_catalog_resource_is_packaged() -> None:
    assert "[[providers]]" in builtin_catalog_resource_text()


def test_effective_catalog_without_override_is_builtin(tmp_path: Path) -> None:
    paths = TauPaths(home=tmp_path / ".tau")
    assert effective_catalog(paths) == builtin_catalog()
    assert catalog_path(paths) == catalog_path()


def test_catalog_adds_new_provider(tmp_path: Path) -> None:
    paths = _catalog_paths(tmp_path, builtin_catalog_resource_text() + VALID_PROVIDER)
    catalog = effective_catalog(paths)
    assert [entry.name for entry in catalog[:-1]] == [e.name for e in builtin_catalog()]
    entry = catalog[-1]
    assert entry.name == "nebius"
    assert entry.default_model == "deepseek-ai/DeepSeek-V4-Pro"
    assert entry.context_windows == {"deepseek-ai/DeepSeek-V4-Pro": 163_840}
    assert entry.model_metadata["deepseek-ai/DeepSeek-V4-Pro"].thinking_levels == (
        "off",
        "low",
        "medium",
        "high",
    )
    assert entry.model_metadata["deepseek-ai/DeepSeek-V4-Pro"].thinking_default == "medium"


def test_catalog_provider_labels_rename_display_without_changing_identity(tmp_path: Path) -> None:
    paths = _catalog_paths(
        tmp_path,
        _strip_provider_labels(builtin_catalog_resource_text())
        + """
[provider_labels]
openai-codex = "codex"
""",
    )

    assert effective_provider_labels(paths) == {"openai-codex": "codex"}
    assert (
        next(entry for entry in effective_catalog(paths) if entry.name == "openai-codex").name
        == "openai-codex"
    )


def test_catalog_provider_labels_reject_duplicate_labels(tmp_path: Path) -> None:
    paths = _catalog_paths(
        tmp_path,
        _strip_provider_labels(builtin_catalog_resource_text())
        + """
[provider_labels]
openai-codex = "models"
opencode-go = "models"
""",
    )

    with pytest.raises(CatalogError, match="duplicate labels: models"):
        effective_provider_labels(paths)


def test_catalog_provider_labels_reject_canonical_id_conflict(tmp_path: Path) -> None:
    paths = _catalog_paths(
        tmp_path,
        _strip_provider_labels(builtin_catalog_resource_text())
        + """
[provider_labels]
openai-codex = "opencode-go"
""",
    )

    with pytest.raises(CatalogError, match="conflicts with canonical provider IDs"):
        effective_provider_labels(paths)


def test_catalog_provider_labels_reject_unknown_provider(tmp_path: Path) -> None:
    paths = _catalog_paths(
        tmp_path,
        _strip_provider_labels(builtin_catalog_resource_text())
        + """
[provider_labels]
missing = "friendly"
""",
    )

    with pytest.raises(CatalogError, match="unknown providers: missing"):
        effective_provider_labels(paths)


def test_catalog_custom_model_extends_builtin_provider(tmp_path: Path) -> None:
    body = (
        builtin_catalog_resource_text()
        .replace(
            'models = ["gpt-5.6-luna", "deepseek-v4-flash"]',
            'models = ["custom-model", "gpt-5.6-luna", "deepseek-v4-flash"]',
        )
        .replace(
            'default_model = "deepseek-v4-flash"',
            'default_model = "custom-model"',
        )
        .replace(
            '[providers.context_windows]\n"gpt-5.6-luna" = 1000000',
            '[providers.context_windows]\n"custom-model" = 500000\n"gpt-5.6-luna" = 1000000',
        )
    )
    paths = _catalog_paths(tmp_path, body)
    entry = next(e for e in effective_catalog(paths) if e.name == "opencode-go")
    assert entry.models[0] == "custom-model"
    assert "gpt-5.6-luna" in entry.models
    assert entry.default_model == "custom-model"
    assert entry.context_windows is not None
    assert entry.context_windows["custom-model"] == 500_000
    assert entry.context_windows["gpt-5.6-luna"] == 1_000_000
    # Untouched fields keep their packaged values.
    assert entry.base_url == "https://opencode.ai/zen/go/v1"
    assert entry.thinking_parameter == "reasoning_effort"


def test_catalog_thinking_metadata_replaces_per_model(tmp_path: Path) -> None:
    body = (
        builtin_catalog_resource_text()
        .replace(
            'thinking_default = "max"\nthinking_levels = ["high", "max"]',
            'thinking_default = "low"\nthinking_levels = ["low", "high"]',
        )
        .replace(
            'thinking_defaults = { "deepseek-v4-flash" = "max", "gpt-5.6-luna" = "xhigh" }',
            'thinking_defaults = { "deepseek-v4-flash" = "low", "gpt-5.6-luna" = "xhigh" }',
        )
    )
    paths = _catalog_paths(tmp_path, body)
    entry = next(e for e in effective_catalog(paths) if e.name == "opencode-go")
    assert entry.model_metadata["deepseek-v4-flash"].thinking_levels == ("low", "high")
    assert entry.model_metadata["deepseek-v4-flash"].thinking_default == "low"
    # Untouched models keep their packaged per-model thinking metadata.
    assert entry.model_metadata["gpt-5.6-luna"].thinking_levels == (
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
    )
    assert entry.model_metadata["gpt-5.6-luna"].thinking_default == "xhigh"


def test_catalog_rejects_provider_level_thinking_fields(tmp_path: Path) -> None:
    paths = _catalog_paths(
        tmp_path,
        builtin_catalog_resource_text()
        + VALID_PROVIDER.replace(
            'thinking_parameter = "reasoning_effort"',
            'thinking_levels = ["low", "high"]\nthinking_default = "high"',
        ),
    )
    with pytest.raises(CatalogError, match="thinking_levels"):
        effective_catalog(paths)


def test_catalog_serializes_cost_tiers(tmp_path: Path) -> None:
    body = builtin_catalog_resource_text().replace(
        'thinking_default = "max"\nthinking_levels = ["high", "max"]',
        'thinking_default = "max"\nthinking_levels = ["high", "max"]\n'
        "cost_tiers = [\n"
        "  { max_input_tokens = 400000, input = 0.2, output = 1.0, cacheRead = 0.04,"
        " cacheWrite = 0 },\n"
        "  { input = 0.5, output = 2.0, cacheRead = 0.1, cacheWrite = 0 },\n"
        "]",
    )
    paths = _catalog_paths(tmp_path, body)
    entry = next(e for e in effective_catalog(paths) if e.name == "opencode-go")
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


def test_catalog_cost_tier_accepts_one_hour_cache_write_rate(tmp_path: Path) -> None:
    body = builtin_catalog_resource_text().replace(
        'thinking_default = "max"\nthinking_levels = ["high", "max"]',
        'thinking_default = "max"\nthinking_levels = ["high", "max"]\n'
        "cost_tiers = [\n"
        "  { max_input_tokens = 400000, input = 0.2, output = 1.0, cacheRead = 0.04,"
        " cacheWrite = 0.25 },\n"
        "  { input = 0.5, output = 2.0, cacheRead = 0.1, cacheWrite = 0.6, cacheWrite1h = 1.0 },\n"
        "]",
    )
    paths = _catalog_paths(tmp_path, body)
    entry = next(e for e in effective_catalog(paths) if e.name == "opencode-go")
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


def test_catalog_rejects_bounded_final_cost_tier(tmp_path: Path) -> None:
    paths = _catalog_paths(
        tmp_path,
        builtin_catalog_resource_text()
        + VALID_PROVIDER.replace(
            'thinking_levels = ["off", "low", "medium", "high"]',
            "cost_tiers = [\n"
            "  { max_input_tokens = 512000, input = 0.3, output = 1.2, cacheRead = 0.06,"
            " cacheWrite = 0 },\n"
            "]",
        ),
    )
    with pytest.raises(CatalogError, match="final tier must omit max_input_tokens"):
        effective_catalog(paths)


def test_catalog_rejects_unknown_keys(tmp_path: Path) -> None:
    paths = _catalog_paths(
        tmp_path,
        builtin_catalog_resource_text() + VALID_PROVIDER.replace("docs_url", "docs_ur1"),
    )
    with pytest.raises(CatalogError, match=r"providers\.nebius"):
        effective_catalog(paths)


def test_catalog_rejects_default_model_not_in_models(tmp_path: Path) -> None:
    paths = _catalog_paths(
        tmp_path,
        builtin_catalog_resource_text()
        + VALID_PROVIDER.replace(
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
def test_catalog_rejects_empty_and_coerced_values(
    tmp_path: Path,
    body: str,
    match: str,
) -> None:
    paths = _catalog_paths(tmp_path, builtin_catalog_resource_text() + body)
    with pytest.raises(CatalogError, match=match):
        effective_catalog(paths)


def test_catalog_rejects_bad_kind(tmp_path: Path) -> None:
    paths = _catalog_paths(
        tmp_path,
        builtin_catalog_resource_text() + VALID_PROVIDER.replace("openai-compatible", "grpc"),
    )
    with pytest.raises(CatalogError, match="kind"):
        effective_catalog(paths)


def test_catalog_rejects_malformed_toml(tmp_path: Path) -> None:
    paths = _catalog_paths(tmp_path, "[[providers]\nname =")
    with pytest.raises(CatalogError, match="invalid TOML"):
        effective_catalog(paths)


def test_catalog_new_provider_appears_in_settings(tmp_path: Path) -> None:
    paths = _catalog_paths(tmp_path, builtin_catalog_resource_text() + VALID_PROVIDER)
    settings = load_provider_settings(paths)
    provider = settings.get_provider("nebius")
    assert provider.base_url == "https://api.studio.nebius.ai/v1"
    assert provider.default_model == "deepseek-ai/DeepSeek-V4-Pro"


def test_catalog_default_provider_controls_settings(tmp_path: Path) -> None:
    paths = _catalog_paths(tmp_path)
    settings = load_provider_settings(paths)
    assert settings.default_provider == "openai-codex"
    assert [provider.name for provider in settings.providers] == [
        "openai-codex",
        "opencode-go",
    ]
    assert settings.get_provider("openai-codex").default_model == "gpt-5.6-sol"
    assert settings.get_provider("opencode-go").thinking_defaults == {
        "deepseek-v4-flash": "max",
        "gpt-5.6-luna": "xhigh",
    }


def test_catalog_rejects_unknown_default_provider(tmp_path: Path) -> None:
    body = builtin_catalog_resource_text().replace(
        'default_provider = "openai-codex"', 'default_provider = "missing"'
    )
    paths = _catalog_paths(tmp_path, body)
    with pytest.raises(CatalogError, match="default_provider 'missing' is not among providers"):
        effective_catalog(paths)


def test_catalog_rejects_thinking_defaults_for_unknown_model(tmp_path: Path) -> None:
    body = builtin_catalog_resource_text().replace(
        'thinking_defaults = { "deepseek-v4-flash" = "max", "gpt-5.6-luna" = "xhigh" }',
        'thinking_defaults = { "deepseek-v4-flash" = "max", "missing-model" = "xhigh" }',
    )
    paths = _catalog_paths(tmp_path, body)
    with pytest.raises(CatalogError, match=r"providers\.opencode-go\.thinking_defaults"):
        effective_catalog(paths)


def test_catalog_rejects_thinking_default_outside_levels(tmp_path: Path) -> None:
    body = builtin_catalog_resource_text().replace(
        'thinking_defaults = { "deepseek-v4-flash" = "max", "gpt-5.6-luna" = "xhigh" }',
        'thinking_defaults = { "deepseek-v4-flash" = "low", "gpt-5.6-luna" = "xhigh" }',
    )
    paths = _catalog_paths(tmp_path, body)
    with pytest.raises(CatalogError, match=r"thinking_defaults\.deepseek-v4-flash"):
        effective_catalog(paths)
