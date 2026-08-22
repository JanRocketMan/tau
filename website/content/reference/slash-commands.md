---
title: Slash commands
description: Every in-session slash command in the Tau TUI.
---

Type these inside the interactive [TUI]({{< relref "../guides/tui.md" >}}). Open the searchable
command palette with **Ctrl+K**.

| Command | Description |
| --- | --- |
| `/quit` | Exit the session |
| `/new` | Start a new session |
| `/session` | Show session info and stats (model, cwd, tools, skills, context) |
| `/system` | Show the active system prompt without adding it to context or session history |
| `/context` | Open a temporary snapshot of the active model context in the default editor |
| `/compact [instructions]` | Summarize and compact the active context |
| `/export [--format html\|jsonl] [dest]` | Export the current session |
| `/resume [session-id]` | Resume a previous session, or open the picker |
| `/tree` | Branch from an earlier point in the session tree |
| `/name <new name>` | Rename the current session and, in supported terminals, the terminal tab title |
| `/model` | Open the model picker |
| `/tools` | Browse active tools and open their full descriptions |
| `/theme [name]` | Show or set the TUI theme |
| `/login [provider]` | Connect a built-in provider with OAuth or an API key; Anthropic uses `anthropic-subscription` or `anthropic-api` |
| `/logout [provider]` | Remove saved credentials for a provider |
| `/reload` | Reload local skills, prompts, extensions, and project context |
| `/prompts` | Search loaded prompt templates and insert an invocation for editing |
| `/skills` | Open a searchable picker of loaded skills and insert a selection into the prompt |
| `/skill:<name> [request]` | Expand a loaded skill into your prompt |

{{% note title="Live HTML exports include the system prompt" %}}
`/export` includes the current system prompt in a collapsed section when it
creates HTML. Review it before sharing because it may expose project
instructions or other local context. JSONL exports do not include the prompt.
Offline `tau export` from stored JSONL cannot recover it and omits the section.
{{% /note %}}

{{% note title="`/skill:` is special" %}}
`/skill:<name>` is a *prompt-expansion* path, not a normal command — Tau expands
the named skill into your prompt and runs it as a turn. Its optional request may
start on the same line or on following lines. See
[Skills & prompt templates]({{< relref "../guides/skills-and-prompts.md" >}}).
{{% /note %}}

`/context` and its **Ctrl+L** shortcut use `$VISUAL`, then `$EDITOR`, with `vi`
as the Unix fallback and Notepad as the Windows fallback. The temporary Markdown
file starts with the
best available total token count and an estimated `Usage:` breakdown for System,
User, Project, Input, Tools, and Out. `System` combines the base system estimate
with active tool schemas. `User` counts active instruction-file contents outside
the current repository. `Project` counts those inside the repository. Generated
instruction wrappers remain part of `System`. `Input` counts active provider
input messages other than tool results. `Tools` counts tool-result messages.
`Out` counts assistant text, thinking, and tool calls. All counts use K units and
round to the nearest whole K. Values below 200 tokens display as `0K`; values
from 200 through 999 tokens display as `1K`. The rest of the file shows the
system prompt, tool definitions, and active compacted messages. It is
a snapshot: edits are discarded and do not enter session history or change later
model requests. Wait for the editor to close to return to Tau. For a graphical
editor, configure its wait option when needed, for example
`EDITOR="code --wait"`

The snapshot includes stored assistant thinking blocks when present. Tau replays
those blocks as reasoning content for some Chat Completions providers. Responses
API providers can instead replay signed or encrypted reasoning metadata, so the
exact wire representation remains provider-specific. A provider-anchored
`Total` can differ from the estimated category sum because providers do not
report token use by source

Only registered commands are consumed locally. Other slash-prefixed input, including
absolute paths such as `/tmp` or `/Users/me/file.png`, is sent to the model as a normal
prompt.

Related:

- **Thinking effort** can be changed with the keyboard shortcut — see
  [Keyboard shortcuts]({{< relref "./keybindings.md" >}}) and [Managing context]({{< relref "../guides/context.md#thinking-modes" >}}).
- **Prompt templates** use slash invocations (for example, `/wt …`). Use `/prompts` to search loaded templates and insert an invocation without submitting it.
