"""Textual TUI frontend for Tau coding sessions."""

from __future__ import annotations

from tau_coding.tui.adapter import TuiEventAdapter
from tau_coding.tui.app import TauTuiApp, run_tui_app
from tau_coding.tui.autocomplete import CompletionOption
from tau_coding.tui.config import (
    BUILTIN_TUI_THEME_NAMES,
    HIGH_CONTRAST_THEME,
    TAU_DARK_THEME,
    TAU_LIGHT_THEME,
    TuiConfigError,
    TuiKeybindings,
    TuiRoleStyle,
    TuiSettings,
    TuiTheme,
    TuiThemeName,
    TurnNotificationMode,
    get_tui_theme,
    tui_settings_from_json,
)
from tau_coding.tui.state import ChatItem, TuiState
from tau_coding.tui.widgets import (
    CompactSessionInfo,
    StreamingTranscriptMessageWidget,
    TranscriptMessageWidget,
    TranscriptView,
    render_chat_item,
    render_compact_session_info,
    transcript_item_selection_text,
)

__all__ = [
    "BUILTIN_TUI_THEME_NAMES",
    "ChatItem",
    "CompletionOption",
    "CompactSessionInfo",
    "TauTuiApp",
    "TAU_DARK_THEME",
    "TAU_LIGHT_THEME",
    "StreamingTranscriptMessageWidget",
    "TranscriptMessageWidget",
    "TranscriptView",
    "TuiEventAdapter",
    "TuiConfigError",
    "HIGH_CONTRAST_THEME",
    "TuiKeybindings",
    "TuiRoleStyle",
    "TuiSettings",
    "TuiTheme",
    "TuiThemeName",
    "TurnNotificationMode",
    "TuiState",
    "get_tui_theme",
    "render_chat_item",
    "render_compact_session_info",
    "run_tui_app",
    "transcript_item_selection_text",
    "tui_settings_from_json",
]
