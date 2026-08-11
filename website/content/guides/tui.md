---
title: The interactive session
description: Get fluent in Tau's terminal UI — prompting, steering, the command palette, tool output, and pickers.
---

Running `tau` with no arguments opens the interactive terminal UI (TUI). This is
where most work happens. This guide covers the moving parts; for the exact keys
see [Keyboard shortcuts]({{< relref "../reference/keybindings.md" >}}).

## Sending a prompt

Type into the prompt box at the bottom and press **Enter** to submit. The editor
keeps its padded block size and background, while a single left border changes
color to reflect focus, shell mode, and active runs without boxing it in.
**Shift+Enter** inserts a newline for multi-line prompts. Tau streams the
assistant's reply above the prompt, showing tool calls as they run. In supported
terminal emulators, Tau also updates the tab title: named sessions show as
`τ | <name>`, and active runs add an animated running indicator so you can see
work continuing from another tab. When a run fully settles while Tau's terminal
surface is unfocused, Tau emits a desktop notification by default on supported
terminals: OSC 9 for Ghostty, iTerm2, and MinTTY, and OSC 99 for Kitty. Unknown
terminals are left untouched. Set `turn_notification` to `"bell"` to let the
terminal mark the tab or apply its configured bell behavior instead, or `"off"`
to disable notifications. BEL and operating-system desktop notifications may
produce sounds according to the user's terminal and system settings; see
[Configuration]({{< relref "../reference/configuration.md#tui-settings" >}}).

Clicking anywhere in the window returns focus to the prompt, so you can scroll
the transcript and keep typing without tabbing back.

If a provider request fails after retries, Tau shows the failure as an explicit
error block in the transcript, using the provider's own error message (for
example `server_is_overloaded` details instead of a generic failure). The block
includes a diagnostic log path and a reminder that the run ended. You can submit
another prompt without starting a new session; empty failed provider turns are
retained for diagnostics but are not replayed to the model as invalid
conversation history.

## Cancelling and steering a run

While the agent is working you don't have to wait:

- **Esc** cancels the active run. Cancellation is treated as an intentional stop,
  not an error.
- **Enter** (while running) queues your text as **steering** — extra guidance
  applied to the current run.
- **Alt+Enter** queues a **follow-up** — a prompt that waits until the current
  run would otherwise finish.
- Press **Up** on an empty prompt while running to pull the most recently queued
  follow-up back into the prompt for editing.

## The command palette and slash commands

In-session commands start with `/`. Open the **command palette** with **Ctrl+K**
to search and run them. Common ones:

- `/session` — show model, tools, skills, and context usage for the session. Text selected in this modal is copied to the clipboard automatically.
- `/model` — pick the active model
- `/tools` — search active tools by origin and open their full descriptions
- `/compact` — summarize and shrink the context
- `/resume`, `/tree` — open previous sessions or branch from history
- `/prompts` — search prompt templates and insert one for editing
- `/hotkeys` — show the keyboard shortcuts

The full list is in the [Slash commands reference]({{< relref "../reference/slash-commands.md" >}}).

## Running shell commands directly

You can run a shell command yourself without asking the model:

- `!<command>` runs it in the session's working directory **and** records the
  command and output in the conversation context.
- `!!<command>` runs it and shows the output **without** adding it to context.

As soon as the input starts with `!`, the whole input and its left border turn
the same amber/orange color as a tool while it is running, so you can tell at a
glance that submitting will execute a shell command instead of messaging the
model.

While typing a path after `!`/`!!`, press **Tab** to complete filenames from the
working directory. Dot-prefixed paths such as `.env` and `.agents/` are included.

{{% note title="Aliases" %}}
These commands (and the agent's `bash` tool) run in a non-interactive shell, so
your `~/.zshrc`/`~/.bashrc` aliases aren't loaded automatically. To use your own
aliases, set a `shellCommandPrefix` — see
[Shell settings]({{< relref "../reference/configuration.md#shell-settings" >}}).
{{% /note %}}

## Referencing files with `@`

Type `@` in the prompt to open file suggestions from the project tree, and insert
a path like `@src/app.py`. Dot-prefixed project content such as `.env` and
`.agents/` is included. Tau still skips known metadata and generated directories
such as `.git`, `.venv`, `node_modules`, `__pycache__`, `build`, and `dist`.

## Dropping files into the prompt

Drag one or more files from your file manager onto the terminal window and Tau
inserts their filesystem paths into the prompt at the cursor, separated by
spaces. Paths that contain spaces are quoted automatically, and any text you
already typed is preserved. This works anywhere over the TUI, not just above
the input box, because the terminal delivers the drop as text input.

Drops are also accepted from sources that do not give the terminal keyboard focus
first, such as the macOS Dock's Downloads stack.

## Tool output

Tool calls keep a static marker in the transcript while they run: orange means
in progress, green means success, and red means failure. The terminal tab title
also animates during a run without adding a second spinner to each tool row.

Tool results (like long `read` or `bash` output) render as compact previews so
the transcript stays readable. Toggle full tool output with **Ctrl+O**. Markdown
link hover styling underlines only the linked text, never the rest of its row. User
message blocks use the same theme background as the prompt field, with light
vertical padding so they read as blocks rather than highlighted lines.
This visually ties submitted prompts to the composer.

## Long sessions

Tau keeps long transcripts responsive by mounting only a window of messages in
the terminal at once. Your complete session remains in display state and durable
history. When older or newer messages are outside the current window, a small
boundary row appears; keep scrolling toward it to page through the rest of the
conversation.

Paging does not summarize, delete, or compact context. Use `/compact` separately
when you want to reduce what is sent to the model.

## Picking models and themes

- **`/model`** opens the model picker. Selecting a model from another provider
  switches the active provider too.
- **Ctrl+P** quickly cycles through your *scoped* (favorite) models without
  opening the picker. Manage that list with `/scoped-models` or by pressing
  `Space` on a model in the `/model` picker.
- **`/theme`** switches between `tau-dark`, `tau-light`, `high-contrast`, and
  any custom themes you have installed. Each theme uses one shared selection
  palette for prompt autocomplete and modal lists such as `/resume`. In
  `tau-dark`, the aqua selection color is also the global accent used for
  headings, prompt activity, and other emphasized UI. `tau-light` uses a deep
  teal accent for headings and list markers against its white background. See
  [Themes]({{< relref "./themes.md" >}}).

## Session status

Tau uses the full terminal width for the transcript and does not show a sidebar,
top header, or shortcut footer. Run `/session` when you need detailed model,
resource, and context information. Run `/hotkeys` when you need the shortcut
list.

The compact status block below the prompt uses two aligned rows on a large
enough terminal. The first row shows the session name on the left and
`provider:model (thinking)` on the right. The second row shows the working
directory and the short Jujutsu change ID, shown as `@ <change-id>`, on the
left, with provider-anchored active context as `used/limit` on the right. The
directory name and model are emphasized. Parent paths, Jujutsu details, and the
provider use the quieter metadata color.

When no valid provider usage exists yet, such as immediately after compaction,
the context value is `?/limit` until a fresh response reports usage. This active
count describes the system prompt, tools, and active messages that Tau expects
to send on the next request. It can decrease after compaction.

Tau omits the session name from this block when the terminal is too narrow or
too short. The remaining directory, model, thinking, and context information
stays visible. A named session also remains in the terminal tab title.

## Next

- [Sessions]({{< relref "./sessions.md" >}}) — resume, branch, rename, export.
- [Providers & models]({{< relref "./providers-and-models.md" >}}) — switch and add models.
- [Managing context]({{< relref "./context.md" >}}) — compaction and thinking modes.
