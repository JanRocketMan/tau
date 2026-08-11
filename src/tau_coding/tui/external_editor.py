"""External-editor support for the Textual frontend."""

import os
import shlex
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path


class ExternalEditorError(RuntimeError):
    """Raised when Tau cannot open or complete an external editor process."""


def resolve_editor_command(environ: Mapping[str, str] | None = None) -> tuple[str, ...]:
    """Resolve the user's editor command from VISUAL, EDITOR, or a platform default."""
    environment = os.environ if environ is None else environ
    configured = environment.get("VISUAL", "").strip() or environment.get("EDITOR", "").strip()
    if not configured:
        return ("notepad",) if sys.platform == "win32" else ("vi",)

    try:
        command = tuple(shlex.split(configured))
    except ValueError as exc:
        raise ExternalEditorError(f"Invalid editor command: {exc}") from exc
    if not command:
        raise ExternalEditorError("The configured editor command is empty")
    return command


def open_text_in_editor(
    text: str,
    *,
    cwd: Path,
    environ: Mapping[str, str] | None = None,
    filename: str = "tau-context.md",
) -> None:
    """Open text in a temporary file and wait for the configured editor to close."""
    command = resolve_editor_command(environ)
    try:
        with tempfile.TemporaryDirectory(prefix="tau-context-") as directory:
            path = Path(directory) / filename
            path.write_text(text, encoding="utf-8")
            completed = subprocess.run([*command, str(path)], cwd=cwd, check=False)
    except OSError as exc:
        raise ExternalEditorError(f"Could not open editor {command[0]}: {exc}") from exc

    if completed.returncode != 0:
        raise ExternalEditorError(f"Editor {command[0]} exited with status {completed.returncode}")
