import webbrowser
from pathlib import Path

import pytest

from tau_coding.catalog_loader import builtin_catalog_resource_text


@pytest.fixture(autouse=True)
def isolate_catalog_file(
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Redirect every catalog read/write to a per-test copy of the packaged catalog.

    Tau's catalog is a writable single source of configuration. Without this
    fixture, tests that exercise save flows (setup, login, model switching)
    would rewrite the packaged ``src/tau_coding/data/catalog.toml``. The copy
    lives outside ``tmp_path`` so it never shows up in tests that enumerate
    working-directory contents (for example file-reference completion).
    """
    catalog = tmp_path_factory.mktemp("catalog") / "catalog.toml"
    catalog.write_text(builtin_catalog_resource_text(), encoding="utf-8")
    monkeypatch.setenv("TAU_CATALOG_PATH", str(catalog))


@pytest.fixture(autouse=True)
def prevent_browser_open(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail tests that accidentally launch an external browser."""

    def fail_browser_open(url: str, *_args: object, **_kwargs: object) -> bool:
        pytest.fail(f"Test attempted to open a browser URL: {url}")

    monkeypatch.setattr(webbrowser, "open", fail_browser_open)


@pytest.fixture(autouse=True)
def isolate_external_service_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep developer credentials from changing offline test behavior."""

    for variable in (
        "TAU_SEARCH_PROVIDER",
        "BRAVE_SEARCH_API_KEY",
        "BRAVE_SEARCH_API_URL",
        "BRAVE_SEARCH_TIMEOUT_SECONDS",
        "PARALLEL_SEARCH_API_KEY",
        "PARALLEL_API_KEY",
        "PARALLEL_SEARCH_API_URL",
        "PARALLEL_SEARCH_TIMEOUT_SECONDS",
        "PARALLEL_SEARCH_MODE",
    ):
        monkeypatch.delenv(variable, raising=False)


def isolate_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point home-directory lookups at the pytest temp directory."""
    monkeypatch.setenv("HOME", str(tmp_path))
    # Path.home() resolves via USERPROFILE on Windows, so HOME alone does not
    # isolate tests from the developer's real ~/.tau settings.
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
