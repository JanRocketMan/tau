---
title: Managing context
description: Keep long sessions working with automatic and manual compaction, and control model effort with thinking modes.
---

A model can only read so much text at once — its **context window**. Long coding
sessions fill it up. Tau handles this with **compaction** (summarizing older
history) and lets you tune how hard the model works with **thinking modes**.

## Seeing context usage

The compact status below the TUI prompt shows provider-anchored active context as
`used/limit`. When no valid provider usage exists yet, it shows `?/limit` instead
of presenting the fallback estimate as provider-confirmed usage. Run `/session`
to see the detailed provider basis or fallback estimate:

```text
Estimated context tokens: <count>
Context window: <count>
Context window source: configured catalog | provider live catalog
Context token breakdown: system=<count>, messages=<count>, tools=<count>
Thinking mode: <mode>
```

After a successful model response, Tau uses the provider-reported token usage as
the authoritative size of the context processed by that response, then estimates
only messages added afterward. Before the first response, immediately after
compaction, or when no valid usage is available, Tau falls back to a deterministic
estimate (roughly `characters / 4` plus small per-message and per-tool overhead).
The fallback covers the system prompt, project context (`AGENTS.md`), skill
metadata, active message history, and tool schemas.

`/session` reports `Context token basis: provider=<count>, estimated
trailing=<count>` when provider usage anchors the active count. Otherwise it shows
the fallback system/message/tool breakdown. Provider usage from errored or aborted
responses is not trusted.

This active count is not a cumulative billing total. It describes only what Tau
expects to send next, so it can decrease after compaction even though the
provider has processed more tokens over the life of the session.

Run `/context` or press **Ctrl+L** while the agent is idle to inspect a temporary
Markdown snapshot of that active context in your default editor. Below the total,
the `Usage:` line
estimates tokens for System content and tool schemas, User instruction files
outside the repository, Project instruction files inside it, user Input, Tools
output, and assistant Out. `Out` includes assistant text, thinking, and tool
calls. Every count uses K units and rounds to the nearest whole K. Values below
200 tokens display as `0K`; values from 200 through 999 tokens display as `1K`.
The file then shows the system prompt, tool schemas, and active messages after
compaction or branch selection.
Editing the file does not change the session

## Automatic compaction

By default, Tau compacts automatically when the estimate gets close to the
model's context window. It checks three moments:

- before a new prompt (to catch context added out-of-band),
- after a successful turn (to compact before your next turn), and
- after a context-overflow error (force compaction regardless of the local estimate,
  then retry once).

When it compacts, Tau asks the model to summarize older messages, keeps a recent
suffix of the conversation, and continues. The original session file is never
edited — only the *active context* sent to the provider changes.

The default threshold follows the model's context window minus a reserve. Providers
that advertise an explicit runtime threshold can override that default. In particular,
Codex subscription sessions discover account/rollout-specific limits from Codex's
authenticated model catalog because those limits can differ from the public OpenAI API.
You can override the resulting threshold for a run:

```bash
tau --auto-compact-threshold 100000
```

Automatic compaction is best-effort: if summarization fails, Tau logs it and keeps
the original context. During successful overflow recovery, the TUI shows compaction
and retry progress instead of presenting the intermediate provider rejection as a
terminal error. The error becomes visible only if recovery cannot complete.

## Manual compaction

Compact on demand any time:

```text
/compact
/compact focus on the database migration work
```

Optional text after `/compact` is added as extra focus for the summary. Manual
compaction summarizes the whole active context into one summary and fails visibly
if the request fails.

In the TUI, a manual compaction looks like a normal working turn: the terminal
tab title animates while it runs, and a turn-finished notification fires when it
completes while the app is unfocused.
Press `Esc` to cancel a running compaction.

## Thinking modes

Some models can spend extra effort reasoning before answering. Tau exposes a
thinking level you can cycle:

```text
off → minimal → low → medium → high → xhigh → max
```

- **Shift+Tab** cycles the thinking level (configurable in `~/.tau/tui.json`
  via the `thinking_cycle` keybinding).
- **Ctrl+T** toggles whether reasoning tokens are shown (hidden by default).
  Reasoning blocks are saved with the assistant response, so their original
  positions and visibility toggle are restored when you resume a session.

Thinking is model-aware: Tau enables it only when the active model declares a
`thinking_levels` list in its catalog metadata. When it's unavailable, `/session`
shows the reason (for example, the model metadata is missing, or the model is not
a reasoning model). Custom providers declare the two model-scoped thinking
fields, `thinking_default` and `thinking_levels`, in their catalog metadata —
see [Configuration]({{< relref "../reference/configuration.md#providers" >}}).

At startup Tau picks a valid level for the selected model automatically: a
remembered per-model choice wins, then the model's catalog default, then the
global default, then the first level the model supports. OpenCode Go starts
`deepseek-v4-flash` at `max` and `gpt-5.6-luna` at `xhigh`. Cycling with the
thinking key cycles through only that model's declared levels, and does nothing
when the model exposes a single level.
