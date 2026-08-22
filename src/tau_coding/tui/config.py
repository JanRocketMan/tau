"""In-memory Textual TUI configuration for Tau.

Tau's TUI has no user-level configuration file: all settings use built-in
in-memory defaults below, and runtime changes (for example the theme picker)
apply to the current session only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, cast

from tau_coding.hotkeys import hotkey_catalog
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
    """Configurable keys for Tau's built-in Textual frontend.

    Unset fields resolve to their packaged ``data/hotkeys.toml`` defaults;
    the catalog is the single source of truth for every hotkey. The user
    settings file may override individual keys at runtime.
    """

    cancel: str | None = None
    command_palette: str | None = None
    session_picker: str | None = None
    open_context: str | None = None
    queue_follow_up: str | None = None
    accept_completion: str | None = None
    completion_next: str | None = None
    completion_previous: str | None = None
    thinking_cycle: str | None = None
    model_cycle: str | None = None
    toggle_thinking: str | None = None
    toggle_tool_results: str | None = None
    clear_prompt: str | None = None
    quit: str | None = None
    copy_message: str | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        """Resolve unset keys from the catalog and apply legacy aliases."""
        defaults = _default_keybindings()
        clear_prompt_override = self.clear_prompt
        if self.copy_message is not None and clear_prompt_override is None:
            # ``copy_message`` was the old name for clearing the prompt.
            clear_prompt_override = self.copy_message
        if self.copy_message == "ctrl+c":
            # An untouched legacy Ctrl+C value yields to the hard interrupt
            # binding; custom values continue to work as the clear key.
            clear_prompt_override = "ctrl+u"
        if clear_prompt_override == "ctrl+c":
            raise TuiConfigError("TUI keybinding 'ctrl+c' is reserved for interrupt")
        for action in _CONFIGURABLE_ACTIONS:
            if getattr(self, action) is None:
                object.__setattr__(self, action, defaults[action])
        object.__setattr__(self, "clear_prompt", clear_prompt_override or self.clear_prompt)
        object.__setattr__(self, "copy_message", self.clear_prompt)

    def to_json(self) -> dict[str, str]:
        """Serialize these keybindings to JSON-compatible data."""
        return {action: cast(str, getattr(self, action)) for action in _CONFIGURABLE_ACTIONS}


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


#: The actions a user may remap through TUI settings; names match the prompt
#: keymap entries in ``data/hotkeys.toml``.
_CONFIGURABLE_ACTIONS: tuple[str, ...] = (
    "cancel",
    "command_palette",
    "session_picker",
    "open_context",
    "queue_follow_up",
    "accept_completion",
    "completion_next",
    "completion_previous",
    "thinking_cycle",
    "model_cycle",
    "toggle_thinking",
    "toggle_tool_results",
    "clear_prompt",
    "quit",
)


def _default_keybindings() -> dict[str, str]:
    """Return the packaged default key for every configurable action."""
    catalog = hotkey_catalog()
    return {action: catalog.key("prompt", action) for action in _CONFIGURABLE_ACTIONS}


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
