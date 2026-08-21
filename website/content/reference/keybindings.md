---
title: Keyboard shortcuts
description: Default keys for the Tau TUI, and how to remap them.
---

These are the default keys in the interactive [TUI]({{< relref "../guides/tui.md" >}}). Run
`/hotkeys` in-session to see them. The keybindings are built-in defaults and
cannot be remapped (see [Configuration]({{< relref "./configuration.md#tui-settings" >}})).

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
Keys use Textual's syntax (`ctrl+k`, `ctrl+f`, `down`, `f2`, …). The defaults
are built in; there is no TUI settings file.
{{% /note %}}
