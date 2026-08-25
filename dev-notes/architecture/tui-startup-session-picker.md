# Session picker on launch

## What changed

Running `tau` with no arguments now opens the session picker (`SessionPickerScreen` in `src/tau_coding/tui/app.py`) immediately instead of dropping straight into a fresh session. The picker also changed layout and content:

- The search field moved below the session list, so the list is the primary element.
- A new first row, **Start a new session**, is selected by default. Pressing Enter starts fresh; arrow keys move to past sessions and Enter resumes one.
- While a search query is active, the new-session row is hidden so the first match is selected by default; this preserves the old type-to-filter, Enter-to-resume flow.
- With zero past sessions, the picker still opens and shows only the new-session row.

`tau --session <id>`, `tau "<prompt>"`, and print mode are unchanged and skip the picker.

## Why it exists

The launch flow previously forced a choice before showing history: users who wanted to resume had to know `--session`, `Ctrl+R`, or `/resume` existed. Now the default path is one decision point - Enter starts a new session, arrows pick a past one.

## How it maps to the codebase

- `run_tui_app` passes `open_session_picker_on_start=True` to `TauTuiApp` only when no explicit `session_id` and no `initial_prompt` were given. The flag defaults to `False` so direct `TauTuiApp` construction (tests, extensions) keeps the old behavior.
- `TauTuiApp.on_mount` opens the picker after startup work finishes, before the first prompt.
- The picker dismisses with a `SessionPickerResult` dataclass (`start_new_session` or `session_id`) instead of a bare session id, so the callback can distinguish "new session" from cancel (`None`).
- On "new session", the callback keeps the current session when it has no messages (the launch session is already fresh and unindexed, avoiding a second record) and calls `session.new_session()` otherwise, matching `/new`.

## How to test

```bash
uv run pytest tests/test_tui_app.py -k "picker or start_picker or run_tui_app"
uv run ruff check .
```

Manual check: `tau` in a project with past sessions shows the picker with **Start a new session** highlighted, Enter lands on a fresh session, down + Enter resumes, and typing filters the list with the search field below it.