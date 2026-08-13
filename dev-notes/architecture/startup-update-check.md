# Startup update check removal

Tau no longer checks PyPI for new versions during startup and no longer provides
a `tau update` command

## What changed

- Removed the PyPI metadata request and update-check cache
- Removed the `TAU_NO_UPDATE_CHECK` compatibility switch because there is no check to disable
- Removed the installer-detection and package-manager subprocess code behind `tau update`
- Removed the update-specific TUI notice and bright-yellow transcript style
- Kept bundled release notes as local-only behavior in `tau_coding.release_notes`

## Why

Starting the coding application must not contact a package index. Users keep
control of upgrades through the package manager that installed Tau, such as
`uv tool upgrade tau-ai`, `pipx upgrade tau-ai`, or
`python -m pip install --upgrade tau-ai`

The reusable `tau_agent` package remains unchanged. This behavior belongs to the
`tau_coding` application layer

## Test

```bash
uv run pytest tests/test_release_notes.py tests/test_cli.py tests/test_tui_app.py
```
