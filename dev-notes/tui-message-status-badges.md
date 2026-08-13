---
title: "TUI run status bar: running timer above the prompt"
---

## What changed

Tau gained a persistent one-row status bar directly above the prompt input
box. It shows agent-run timing in a fixed position that never moves:

- `running 1m 23s` while a turn is in flight, ticking once per second
- `finished in 1m 23s` once the turn settles, with the total turn duration

The finished report appears whether the run completed normally, failed with a
provider error, or was interrupted with Ctrl+C / Esc. The finished duration
stays until the next turn starts, then the bar switches back to `running 0s`.

Two related behaviors were removed because the bar makes them redundant:

- The live TPS estimate badge (estimated tokens per second) was confusing and
  is gone entirely, along with the streamed-character counters.
- The prompt's left border no longer turns green while the agent runs. The
  border keeps its focus color during a run; the shell-mode amber and the
  failed-run red remain, because those are distinct states the bar does not
  describe.

## Why

The first iteration attached the timer to the bottom of the streaming message
block. That badge "jumped" whenever a new model response or tool call arrived,
because the footer moved from one message to the next as the transcript grew.
The status bar fixes the position: it sits above the input box, so it never
moves regardless of what streams above it.

The bar always reserves its one row (it clears its text when idle instead of
hiding). Toggling visibility would shrink the transcript viewport mid-run and
shift the scroll position; a stable row avoids all layout jumps.

The running/finished text is the single source of truth for "is the model
working", so the green prompt border and the TPS badge were removed as
redundant.

## How it maps to the architecture

- `TuiState` owns run timing: `agent_started_at` (turn start) and
  `last_run_elapsed` (finished duration). `start_agent_run()` and
  `end_agent_run()` are the only entry points; `end_agent_run()` returns the
  elapsed seconds and is idempotent.
- The adapter starts the run on `AgentStartEvent` and ends it on
  `AgentEndEvent`, `agent_settled`, and the terminal error path. The app also
  ends the run when a prompt worker raises and when the user interrupts
  (`_cancel_active_prompt`), so the bar always lands on `finished in X`.
- `RunStatusBar` is a `Static` with a content fingerprint, so the frequent
  `_refresh_chrome()` calls only repaint on real changes (once per second).
- `run_status_text(state)` derives the display string; the app refreshes the
  bar through `_refresh_chrome()` (event boundaries) and once per second via
  the existing activity tick (`_refresh_run_status_bar`).
- `_activity_prompt_border_color` no longer maps `running` to the theme
  success color; running keeps `prompt_border`, shell mode keeps the tool
  border, and failed runs keep the error color.

## Verification

```bash
uv run pytest tests/test_tui_adapter.py tests/test_tui_app.py
uv run pytest tests/ -q
uv run ruff check .
uv run mypy
```

New tests cover: bar content while running, the end-to-end streaming flow,
`finished in X` after settle, after a provider error, and after an interrupt,
plus the bar staying fixed above the prompt across tool calls and the prompt
border staying neutral while running.
