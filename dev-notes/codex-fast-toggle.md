# Codex Fast toggle

`/fast` or Ctrl+F toggles Fast routing for the current loaded Codex subscription session
and does nothing for other providers. The Codex catalog entry sets `fast = true`
to start sessions with Fast routing. Session toggle changes are not saved

The coding session owns the toggle and rebuilds the runtime provider when it
changes. The AI adapter sends `service_tier: "priority"` and
`x-codex-routing-hint: model=<model>;tier=priority`. The portable agent harness
has no Codex-specific changes, which preserves Pi's layer boundaries

The Ctrl+F binding lives in the packaged hotkey catalog as `toggle_fast`.
It runs the same silent command and refreshes status
without changing the prompt draft or opening a modal

Reasoning effort stays unchanged. The TUI adds `-fast` to the effort label while
Fast is active. The selection survives effort and model changes, but starting or
resuming a session restores the catalog default. Switching to another provider hides and disables
it; switching back restores the selection

Support checks are deliberately omitted. The user handles provider errors for
unsupported accounts or models. Fast mode can use subscription credits faster

Run the focused checks with:

```bash
uv run pytest tests/test_commands.py tests/test_coding_session.py tests/test_tau_ai.py tests/test_tui_app.py -k fast
```
