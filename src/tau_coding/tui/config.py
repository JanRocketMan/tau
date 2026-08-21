"""In-memory Textual TUI configuration for Tau.

Tau's TUI has no user-level configuration file: all settings use built-in
in-memory defaults below, and runtime changes (for example the theme picker)
apply to the current session only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, cast

from tau_coding.tui.themes import (
    BUILTIN_TUI_THEME_NAMES,
    CODEYELLOW_THEME,
    HIGH_CONTRAST_THEME,
    TAU_DARK_THEME,
    TAU_LIGHT_THEME,
    TuiRoleStyle,
    TuiTheme,
    TuiThemeName,
    get_tui_theme,
)

type TurnNotificationMode = Literal["off", "bell", "desktop"]


__all__ = [
    "BUILTIN_TUI_THEME_NAMES",
    "CODEYELLOW_THEME",
    "HIGH_CONTRAST_THEME",
    "TAU_DARK_THEME",
    "TAU_LIGHT_THEME",
    "TuiConfigError",
    "TuiKeybindings",
    "TuiRoleStyle",
    "TuiSettings",
    "TuiTheme",
    "TuiThemeName",
    "TurnNotificationMode",
    "get_tui_theme",
    "tui_settings_from_json",
]


class TuiConfigError(ValueError):
    """Raised when Tau TUI configuration is invalid."""


@dataclass(frozen=True, slots=True)
class TuiKeybindings:
    """Configurable keys for Tau's built-in Textual frontend."""

    cancel: str = "escape"
    command_palette: str = "ctrl+k"
    session_picker: str = "ctrl+r"
    open_context: str = "ctrl+l"
    queue_follow_up: str = "alt+enter"
    accept_completion: str = "tab"
    completion_next: str = "down"
    completion_previous: str = "up"
    thinking_cycle: str = "ctrl+f"
    model_cycle: str = "ctrl+p"
    toggle_thinking: str = "ctrl+t"
    toggle_tool_results: str = "ctrl+o"
    clear_prompt: str = "ctrl+u"
    quit: str = "ctrl+d"
    copy_message: str | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        """Accept the former ``copy_message`` constructor name as a compatibility alias."""
        clear_prompt = self.copy_message or self.clear_prompt
        if self.copy_message == "ctrl+c":
            clear_prompt = "ctrl+u"
        if clear_prompt == "ctrl+c":
            raise TuiConfigError("TUI keybinding 'ctrl+c' is reserved for interrupt")
        object.__setattr__(self, "clear_prompt", clear_prompt)
        object.__setattr__(self, "copy_message", clear_prompt)

    def to_json(self) -> dict[str, str]:
        """Serialize these keybindings to JSON-compatible data."""
        return {
            "cancel": self.cancel,
            "command_palette": self.command_palette,
            "session_picker": self.session_picker,
            "open_context": self.open_context,
            "queue_follow_up": self.queue_follow_up,
            "accept_completion": self.accept_completion,
            "completion_next": self.completion_next,
            "completion_previous": self.completion_previous,
            "thinking_cycle": self.thinking_cycle,
            "model_cycle": self.model_cycle,
            "toggle_thinking": self.toggle_thinking,
            "toggle_tool_results": self.toggle_tool_results,
            "clear_prompt": self.clear_prompt,
            "quit": self.quit,
        }


@dataclass(frozen=True, slots=True)
class TuiSettings:
    """Tau TUI settings loaded from Tau home."""

    keybindings: TuiKeybindings = field(default_factory=TuiKeybindings)
    theme: TuiThemeName = "codeyellow"
    auto_copy_selection: bool = False
    turn_notification: TurnNotificationMode = "desktop"

    def to_json(self) -> dict[str, Any]:
        """Serialize these settings to JSON-compatible data."""
        return {
            "auto_copy_selection": self.auto_copy_selection,
            "keybindings": self.keybindings.to_json(),
            "theme": self.theme,
            "turn_notification": self.turn_notification,
        }

    @property
    def resolved_theme(self) -> TuiTheme:
        """Return the selected theme, falling back to codeyellow when unknown."""
        try:
            return get_tui_theme(self.theme)
        except KeyError:
            return CODEYELLOW_THEME


def tui_settings_from_json(data: dict[str, Any]) -> TuiSettings:
    """Parse TUI settings from JSON-compatible data."""
    # Ignore settings added by newer Tau versions so sharing this user-level
    # file across upgrades, downgrades, and multiple installations cannot block
    # TUI startup. Recognized settings remain strictly validated below.
    keybindings_data = data.get("keybindings", {})
    if not isinstance(keybindings_data, dict):
        raise TuiConfigError("TUI keybindings must be a JSON object")
    raw_notification = data.get("turn_notification", "desktop")
    if not isinstance(raw_notification, str) or raw_notification not in {
        "off",
        "bell",
        "desktop",
    }:
        raise TuiConfigError("turn_notification must be 'off', 'bell', or 'desktop'")
    return TuiSettings(
        keybindings=_keybindings_from_json(keybindings_data),
        theme=_theme_name(data.get("theme", "codeyellow")),
        auto_copy_selection=_bool_setting(
            data.get("auto_copy_selection", False),
            "auto_copy_selection",
        ),
        turn_notification=cast(TurnNotificationMode, raw_notification),
    )


def _bool_setting(value: object, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    raise TuiConfigError(f"TUI setting must be a boolean: {field_name}")


def _keybindings_from_json(data: dict[str, Any]) -> TuiKeybindings:
    defaults = TuiKeybindings()
    # Future versions may add actions to this nested object. Read only actions
    # this version understands, just as the top-level settings parser does.
    values = {
        field_name: _key_string(data.get(field_name, default_value), field_name)
        for field_name, default_value in defaults.to_json().items()
    }
    # ``copy_message`` was the old name for clearing the prompt. An untouched
    # old Ctrl+C value now yields to the hard interrupt binding; custom values
    # continue to work as the clear-prompt key.
    if "clear_prompt" not in data and "copy_message" in data:
        legacy_clear_prompt = _key_string(data["copy_message"], "copy_message")
        if legacy_clear_prompt != "ctrl+c":
            values["clear_prompt"] = legacy_clear_prompt
    _reject_duplicate_keys(values)
    if values["clear_prompt"] == "ctrl+c":
        raise TuiConfigError("TUI keybinding 'ctrl+c' is reserved for interrupt")
    return TuiKeybindings(**values)


def _key_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TuiConfigError(f"TUI keybinding must be a non-empty string: {field_name}")
    return value.strip()


def _theme_name(value: object) -> TuiThemeName:
    if not isinstance(value, str) or not value.strip():
        raise TuiConfigError("TUI theme must be a non-empty string")
    return value.strip()


def _reject_duplicate_keys(values: dict[str, str]) -> None:
    key_to_action: dict[str, str] = {}
    for action, key in values.items():
        previous_action = key_to_action.get(key)
        if previous_action is not None:
            raise TuiConfigError(
                f"TUI keybinding {key!r} is assigned to both {previous_action!r} and {action!r}"
            )
        key_to_action[key] = action
