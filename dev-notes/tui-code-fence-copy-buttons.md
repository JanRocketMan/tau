# TUI code-fence copy buttons

## What changed

Every fenced ``` code block in the transcript now shows a small copy button
(`▣`) in its top-right corner. This covers:

- code fences in assistant messages (Markdown-rendered)
- code fences in user messages
- code fences in tool results

Clicking the button copies exactly the fenced code (without the ``` markers) to
the clipboard, flashes a checkmark for ~1.2s, and restores keyboard focus to the
prompt input. Rows without complete fences keep their fast plain rendering and
get no button.

## Why it exists

Users frequently want to reuse code snippets from a session (assistant answers,
pasted user snippets, tool output) without selecting text or copying whole
messages. A per-fence button matches the mental model of "each boxed code area
has a copy control" and avoids copying surrounding prose.

## Architecture notes

All changes live in `tau_coding/tui/widgets.py` (the Textual layer) plus the
transcript helper functions; nothing was added to `tau_agent` or `tau_ai`.

- `CopyFenceButton` - a `Button` subclass with `can_focus=False` (so clicks
  never leave keyboard focus on the transcript) docked to the right edge of
  each fence box. The button background matches the box
  (`$tau-markdown-code-block-background`) in every theme. It reads the fence
  `code` from its parent at click time, so it stays in sync while markdown
  streams or tool progress updates in place.
- Button placement: a fence with a single code line gets a one-row header
  above the code hosting the button (so the box renders as two rows); a fence
  with multiple lines keeps its line count and the button sits at the end of
  the first line instead. Each box tracks a `-multi-line` class that hides its
  header row, re-synced while streaming (`_copy_context`) and on in-place tool
  progress updates (`update_code`).
- `TauMarkdownFence` - `MarkdownFence` subclass composing the header row, the
  code Label, and the button; registered in `ThemedMarkdownWidget.BLOCKS` for
  the `fence` and `code_block` token types. Code content keeps flowing through
  Textual's `set_content` / `#code-content` Label exactly like the built-in
  fence, so streamed updates and theme refreshes behave unchanged. The fence
  `code` stays fresh across streamed updates because Textual's
  `MarkdownFence._update_from_block` copies context in place.
- `FencedPlainBody` / `FencedCodeBox` / `FencedCodeContent` - user, tool, skill,
  and error rows render as plain `Static` bodies for speed. When a row contains
  at least one well-formed fence, `_transcript_plain_body_parts` splits the
  styled text into parts and `FencedPlainBody` renders each fence as a boxed
  `FencedCodeBox` with a button. Malformed or truncated fences (for example a
  preview cut mid-fence) keep the row fully literal, matching the behavior of
  the existing `_render_fenced_body` fast path.
- `refresh_invocation` (live tool progress / spinners) updates the boxed body in
  place when the sequence of text/fence parts keeps the same shape, so high-
  frequency updates do not remount widgets; adding or dropping a fence changes
  the shape and falls back to the existing remount path.
- Code-box selection still works: `FencedCodeContent.get_selection` reports the
  raw code under a drag selection.
- Click focus: Textual moves focus to the transcript when the pointer lands on
  the button, so `on_click` refocuses `#prompt` afterwards, keeping typing
  uninterrupted. The button is not tab-focusable.

## How to test

Automated checks:

```bash
uv run pytest tests/test_tui_copy_buttons.py
uv run pytest tests/test_tui_app.py -q
uv run ruff check src/tau_coding/tui tests/test_tui_copy_buttons.py
```

Manual check:

1. Run `uv run tau`.
2. Ask for code with a fenced block, paste a fenced snippet as a user message,
   and run a tool that outputs a fenced block.
3. Click each `▣` button and paste elsewhere; the button flashes ✓ and focus
   returns to the prompt.