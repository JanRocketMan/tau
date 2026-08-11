# Model context editor command

`/context` adds a local inspection path for the next model request. The command
registry returns `CommandResult.context_editor_requested`, and the Textual
frontend owns the external-editor operation. The configurable `open_context`
keybinding uses `ctrl+l` by default and calls the same frontend action. This keeps
editor and terminal suspension policy out of `tau_agent`

The snapshot uses the same active session messages as the harness, including
compaction and branch replay. `provider_context_messages()` supplies the shared
filter that removes empty failed or aborted assistant messages from provider
requests and from this view. `tau_coding.model_context` renders the system
prompt, active tool schemas, and messages as Markdown with a compact total token
count at the top. The next line estimates System, User, Project, Input, Tools,
and Out separately. System combines the base system estimate with active tool
schemas. Input contains non-assistant provider input, Tools contains tool-result
messages, and Out contains assistant text, thinking, and tool calls. Every
displayed count rounds to the nearest whole K. Values below 200 tokens display
as `0K`; values from 200 through 999 tokens display as `1K`

User and Project counts come from active instruction-file contents. Tau finds the
repository root from `.git` or `.jj`, with the nearest project marker as a
fallback. Files at or below that root count as Project; files elsewhere count
as User. Their generated XML wrappers remain in System so source contents are
not double-counted

Textual suspends terminal application mode while `$VISUAL`, `$EDITOR`, `vi`, or
Notepad runs. Tau writes the snapshot to a temporary directory and removes it
after the editor exits. Changes to the file are not read back, persisted, or
sent to the model. Commands are rejected during active turns so a blocking
terminal editor cannot pause an in-flight provider stream

Thinking content needs provider-specific care. Tau's Chat Completions adapter
can replay stored reasoning text, while Responses adapters replay signed or
encrypted reasoning items. The readable provider-neutral snapshot includes
stored thinking text, but it does not claim to be a byte-for-byte provider
payload

Validate with:

```bash
uv run pytest tests/test_model_context.py tests/test_commands.py tests/test_tui_app.py
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run mypy
```
