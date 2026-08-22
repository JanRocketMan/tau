---
title: Keyboard shortcuts
description: Every TUI hotkey, defined in the packaged hotkeys.toml catalog.
---

All keyboard shortcuts in the interactive [TUI]({{< relref "../guides/tui.md" >}})
are defined in one file: `src/tau_coding/data/hotkeys.toml`. That catalog is
the single source of truth for key handling; every entry names the key, the
action it triggers, and a short description, grouped by the screen or widget
that uses it. There is no in-session shortcut list, so open the file directly
when you need a reminder.

The user-visible bindings can be remapped through
[Configuration]({{< relref "./configuration.md#tui-settings" >}}); the catalog
carries the defaults.

## Prompting

| Key | Action |
| --- | --- |
| `Enter` | Submit the prompt (or apply a highlighted completion) |
| `Shift+Enter` | Insert a newline |
| `Ctrl+C` | Stop the active model run, tool, or compaction |
| `Esc` | Cancel the active run |
| `Enter` (while running) | Queue text as steering for the current run |
| `Alt+Enter` | Queue a follow-up that waits until the run would stop |
| `Up` (empty prompt, running) | Edit the most recently queued follow-up |

## Navigation & pickers

| Key | Action |
| --- | --- |
| `Ctrl+K` | Open the command palette |
| `Ctrl+R` | Open the session picker |
| `Ctrl+L` | Open the active model context in the default editor |
| `Tab` | Accept the highlighted completion |
| `Down` / `Up` | Move through completions |

## Models & thinking

| Key | Action |
| --- | --- |
| `Ctrl+P` | Cycle through all available models (default provider first) |
| `Ctrl+F` | Cycle the thinking mode |
| `Ctrl+T` | Toggle display of thinking/reasoning tokens |

## Output & session

| Key | Action |
| --- | --- |
| `Ctrl+O` | Toggle full tool output (vs. compact preview) |
| `Ctrl+U` | Clear the prompt input |
| `Ctrl+D` | Quit |

{{% note title="Keys" %}}
Keys use Textual's syntax (`ctrl+k`, `ctrl+f`, `down`, `f2`, ...). The table
above summarizes the prompt-scope defaults; `src/tau_coding/data/hotkeys.toml`
also covers pickers, modals, and footer modes, each with a short description.
{{% /note %}}