import pytest

from tau_coding.tui.config import (
    CODEYELLOW_THEME,
    TuiConfigError,
    TuiKeybindings,
    TuiSettings,
    get_tui_theme,
    tui_settings_from_json,
)


def test_tui_settings_defaults_are_builtin() -> None:
    assert TuiSettings().keybindings.open_context == "ctrl+l"
    assert TuiSettings().keybindings.quit == "ctrl+d"
    assert TuiSettings().keybindings.thinking_cycle == "ctrl+f"
    assert TuiSettings().theme == "codeyellow"


def test_tui_settings_ignores_removed_message_selection_keybindings() -> None:
    settings = tui_settings_from_json(
        {
            "keybindings": {
                "message_previous": "alt+up",
                "message_next": "alt+down",
            }
        }
    )

    assert settings == TuiSettings()


def test_tui_settings_ignore_unknown_fields() -> None:
    settings = tui_settings_from_json(
        {
            "theme": "tau-light",
            "future_setting": {"enabled": True},
        }
    )

    assert settings.theme == "tau-light"


def test_tui_keybindings_ignore_unknown_actions() -> None:
    settings = tui_settings_from_json(
        {
            "keybindings": {
                "quit": "f12",
                "future_action": "ctrl+g",
            }
        }
    )

    assert settings.keybindings.quit == "f12"


def test_tui_keybindings_reject_duplicate_keys() -> None:
    with pytest.raises(TuiConfigError, match="assigned to both"):
        tui_settings_from_json(
            {
                "keybindings": {
                    "cancel": "escape",
                    "command_palette": "escape",
                }
            }
        )


def test_tui_settings_accept_unknown_theme_and_fall_back_when_resolving() -> None:
    settings = tui_settings_from_json({"theme": "solarized"})

    assert settings.theme == "solarized"
    assert settings.resolved_theme == CODEYELLOW_THEME


def test_tui_settings_reject_non_string_theme() -> None:
    with pytest.raises(TuiConfigError, match="theme"):
        tui_settings_from_json({"theme": 7})
    with pytest.raises(TuiConfigError, match="theme"):
        tui_settings_from_json({"theme": "  "})


def test_tui_settings_accept_light_theme() -> None:
    settings = tui_settings_from_json({"theme": "tau-light"})

    assert settings.theme == "tau-light"
    assert settings.resolved_theme.screen_background == "#ffffff"
    assert settings.resolved_theme.syntax_theme == "ansi_light"


def test_tui_settings_load_auto_copy_selection() -> None:
    settings = tui_settings_from_json({"auto_copy_selection": True})

    assert settings.auto_copy_selection is True
    assert settings.to_json()["auto_copy_selection"] is True


def test_tui_settings_reject_invalid_auto_copy_selection() -> None:
    with pytest.raises(TuiConfigError, match="auto_copy_selection"):
        tui_settings_from_json({"auto_copy_selection": "yes"})


def test_tui_keybindings_migrate_default_legacy_ctrl_c_to_ctrl_u() -> None:
    settings = tui_settings_from_json({"keybindings": {"copy_message": "ctrl+c"}})

    assert settings.keybindings.clear_prompt == "ctrl+u"


def test_tui_keybindings_preserve_custom_legacy_clear_prompt_key() -> None:
    settings = tui_settings_from_json({"keybindings": {"copy_message": "ctrl+b"}})

    assert settings.keybindings.clear_prompt == "ctrl+b"


def test_tui_keybindings_reserve_ctrl_c_for_interrupt() -> None:
    with pytest.raises(TuiConfigError, match="reserved for interrupt"):
        tui_settings_from_json({"keybindings": {"clear_prompt": "ctrl+c"}})
    with pytest.raises(TuiConfigError, match="reserved for interrupt"):
        TuiKeybindings(clear_prompt="ctrl+c")


def test_tui_keybindings_constructor_migrates_legacy_default() -> None:
    assert TuiKeybindings(copy_message="ctrl+c").clear_prompt == "ctrl+u"


def test_tui_keybindings_serialize_to_json() -> None:
    settings = TuiSettings(
        keybindings=TuiKeybindings(
            command_palette="ctrl+j",
            session_picker="ctrl+y",
            open_context="f7",
            queue_follow_up="f5",
            accept_completion="f2",
            thinking_cycle="f3",
            model_cycle="f6",
            toggle_thinking="f4",
            clear_prompt="ctrl+b",
        ),
        theme="high-contrast",
    )

    assert settings.to_json()["keybindings"]["command_palette"] == "ctrl+j"
    assert settings.to_json()["keybindings"]["session_picker"] == "ctrl+y"
    assert settings.to_json()["keybindings"]["open_context"] == "f7"
    assert settings.to_json()["keybindings"]["queue_follow_up"] == "f5"
    assert settings.to_json()["keybindings"]["toggle_tool_results"] == "ctrl+o"
    assert settings.to_json()["keybindings"]["toggle_thinking"] == "f4"
    assert settings.to_json()["keybindings"]["accept_completion"] == "f2"
    assert settings.to_json()["keybindings"]["thinking_cycle"] == "f3"
    assert settings.to_json()["keybindings"]["model_cycle"] == "f6"
    assert settings.to_json()["keybindings"]["clear_prompt"] == "ctrl+b"
    assert settings.to_json()["theme"] == "high-contrast"
    assert settings.to_json()["auto_copy_selection"] is False


def test_get_tui_theme_returns_builtin_theme() -> None:
    assert get_tui_theme("high-contrast").prompt_border == "#00ff66"
    assert get_tui_theme("tau-light").prompt_border == "#2563eb"
    assert get_tui_theme("tau-dark").screen_background == "#000000"


def test_tui_turn_notification_defaults_to_desktop() -> None:
    assert TuiSettings().turn_notification == "desktop"
    assert tui_settings_from_json({}).turn_notification == "desktop"


def test_tui_turn_notification_roundtrips() -> None:
    for value in ("off", "bell", "desktop"):
        settings = tui_settings_from_json({"turn_notification": value})
        assert settings.turn_notification == value
        assert settings.to_json()["turn_notification"] == value


def test_tui_turn_notification_rejects_invalid_value() -> None:
    with pytest.raises(TuiConfigError, match="turn_notification"):
        tui_settings_from_json({"turn_notification": "sound"})

    with pytest.raises(TuiConfigError, match="turn_notification"):
        tui_settings_from_json({"turn_notification": True})


def test_tui_settings_ignore_removed_sidebar_position() -> None:
    settings = tui_settings_from_json({"sidebar_position": "left"})

    assert settings == TuiSettings()
    assert "sidebar_position" not in settings.to_json()
