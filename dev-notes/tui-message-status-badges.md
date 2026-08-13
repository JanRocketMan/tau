---
title: "TUI message status badges: running timer and live TPS"
---

## What changed

While an agent turn is in flight, the currently streaming assistant (and
thinking) message shows a one-row status footer:

- bottom-left: `running 1m 23s`, ticking once per second
- bottom-right: `010 TPS`, the estimated streaming speed, always three
  zero-padded digits (capped at 999)

Once the turn settles, the final assistant message reports
`finished in 1m 23s` with the total turn duration, and the TPS badge
disappears. Intermediate messages of the turn (for example the text before a
tool call) keep their `running` badge while the agent works and lose it at
settle, so history reads as plain messages again.

## Why

Users launching an agent want to see at a glance how long it has been working
and how fast the model is generating, without reading the transcript. The
footer is attached to the message itself, so it scrolls with the message and
survives window paging and redraws.

TPS is estimated as `chars / 4` per second because provider token usage only
arrives after a response completes. The estimate is intentionally a live
indicator, not a billing figure.

## How it maps to the architecture

- `TuiState` owns turn timing: `agent_started_at` is set on `AgentStartEvent`
  and `end_agent_run()` tags the final assistant item with `run_elapsed` at
  settle. `ChatItem` gained `run_started_at` and `run_elapsed`.
- The adapter attaches `run_started_at` to items it creates while a turn is
  active (`add_assistant_message`, `add_thinking_delta`, `_flush`), so restored
  history never shows a badge.
- `MessageStatusFooter` is a docked bottom row mounted by both
  `TranscriptMessageWidget` and `StreamingTranscriptMessageWidget`. Docking
  keeps it at the bottom of the message even while Textual Markdown appends
  new blocks; `Markdown.update()` only removes `MarkdownBlock` children, so the
  footer survives full re-parses.
- The streaming widget counts fragments (`_streamed_chars`,
  `_stream_started_at`) and derives TPS; `finalize()` drops the TPS badge while
  keeping the timer.
- The existing activity tick (`_tick_activity`, throttled to 1 s) refreshes
  mounted footers, and `finish_agent_run()` refreshes all mounted
  assistant/thinking footers at settle so `finished in X` replaces `running X`.

## Verification

```bash
uv run pytest tests/test_tui_adapter.py tests/test_tui_app.py
uv run pytest tests/ -q
uv run ruff check .
uv run mypy
```

New tests cover: adapter run timing, settle tagging, TPS formatting
(zero-padded, capped, no-data), streaming badge content, TPS hiding on
finalize, and the end-to-end finished badge after `AgentSettledEvent`.
