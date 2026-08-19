# TUI terminal tab titles

Issue: #260

## What changed

The Textual TUI now updates the terminal emulator's window/tab title with the
active Tau session name and run state:

- idle unnamed session: `τ`
- idle named session: `τ | <session name>`
- running session: an animated Braille spinner prefix plus the idle title
- successful settled run: `✓` plus the idle title
- failed settled run: `✗` plus the idle title
- settled run whose final assistant message has thinking but no visible text or
  tool call: `✗` plus the idle title
- interrupted run: the neutral idle title

A new run replaces the settled marker with the running spinner. On TUI shutdown
Tau writes a neutral `τ` title so the terminal is not left with a stale state.

## Why it lives in `tau_coding`

Terminal title updates are a frontend concern. The implementation uses state the
TUI already owns:

- `TuiState.running`, populated from agent lifecycle events by the adapter
- `TuiState.error`, which records a terminal model failure
- `TuiState.last_run_elapsed` and `last_run_interrupted`, which distinguish a
  successful settlement from initial idle and an intentional stop
- `TuiState.last_response_was_thinking_only`, which detects a likely truncated
  final response without treating an intermediate thinking-plus-tool-call turn
  as a failure
- `CodingSession.session_title`, which is updated by `/name` and automatic
  session naming

No terminal or Textual dependencies were added to `tau_agent` or `tau_ai`.

## Mechanism

`src/tau_coding/tui/terminal_title.py` emits OSC 0 sequences:

```text
ESC ] 0 ; <title> BEL
```

OSC 0 is broadly supported by common terminal emulators and sets the terminal
window/tab title. tmux records this value as the pane title, so status formats can
use the `✓` and `✗` prefixes without giving Tau access to the tmux control socket.
The `TerminalTitleController` writes only when the computed title changes, so idle
refreshes do not spam stdout. While running, the existing activity timer drives
both the in-app prompt animation and the tab-title spinner. The prompt worker
refreshes the title once more after it releases its working state, which publishes
the final success or error marker.

The incomplete-response check is intentionally narrow. At each completed
assistant message, the TUI records whether the canonical message contains
non-empty thinking, no non-empty text, and no tool call. Only the latest assistant
message matters when the run settles. A tool-calling turn can therefore contain
thinking without producing a false red marker, while a run that ends directly
from a thinking-only message is marked for attention. This is a presentation
heuristic and does not rewrite the durable message or classify the run as a
provider error.

## Capability detection and safety

Title writing is enabled only when stdout is a TTY, `TERM` is not `dumb`, and CI
is not detected. Users can opt out with `TAU_TERMINAL_TITLE=0`; CI/no-TTY cases
can opt in explicitly with `TAU_TERMINAL_TITLE=1` only where supported by the
helper's rules. Title writes are best-effort: if the terminal stream raises while
Tau is writing an OSC sequence, Tau disables further title writes for that TUI
process instead of interrupting the session.

Session names are sanitized before they enter an OSC payload: C0/C1 control
characters, including BEL and ESC, are stripped and the title is capped to 120
characters.

## Testing and manual verification

Automated tests cover title construction, sanitization, capability detection,
deduplicated writes, and TUI running/name/idle transitions.

Manual verification:

1. Open `tau` in a real terminal tab.
2. Confirm an unnamed idle TUI shows `τ` in the tab title.
3. Run `/name build notes` and confirm the tab changes to `τ | build notes`.
4. Submit a prompt that runs long enough to observe the animated spinner prefix.
5. Let the run finish and confirm the title starts with `✓`.
6. Trigger a terminal provider error and confirm the title starts with `✗`.
7. Settle a response with thinking but no visible answer or tool call and confirm
   the title starts with `✗`.
8. Cancel a run and confirm the title returns to its neutral form.
9. Quit the TUI and confirm the tab is reset to `τ`.
10. Repeat once with `TAU_TERMINAL_TITLE=0 tau` and confirm Tau does not manage
   the tab title.
