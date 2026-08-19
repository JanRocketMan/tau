import webbrowser
from pathlib import Path

import pytest


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
