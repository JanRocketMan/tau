"""Tests for the packaged hotkey catalog (``data/hotkeys.toml``)."""

from __future__ import annotations

import pytest

from tau_coding.hotkeys import (
    HotkeyCatalogError,
    hotkey_catalog,
    hotkeys_path,
    parse_hotkey_catalog_text,
)

# Every prompt hotkey and its packaged default key. The TUI key handling and
# the documented shortcuts must match this table exactly.
EXPECTED_PROMPT_KEYS = {
    "submit": "enter",
    "insert_newline": "shift+enter",
    "interrupt": "ctrl+c",
    "cancel": "escape",
    "queue_follow_up": "alt+enter",
    "command_palette": "ctrl+k",
    "session_picker": "ctrl+r",
    "tree_picker": "ctrl+g",
    "open_context": "ctrl+l",
    "accept_completion": "tab",
    "completion_next": "down",
    "completion_previous": "up",
    "thinking_cycle": "ctrl+f",
    "model_cycle": "ctrl+p",
    "toggle_thinking": "ctrl+t",
    "toggle_tool_results": "ctrl+o",
    "clear_prompt": "ctrl+u",
    "quit": "ctrl+d",
}

#: Keymaps referenced by the TUI code.
REQUIRED_KEYMAPS = {
    "prompt",
    "app",
    "prompt_normal",
    "prompt_completion",
    "prompt_running",
    "extension_select",
    "extension_confirm",
    "extension_input",
    "tools_reference_search_input",
    "tools_reference",
    "session_picker_search_input",
    "prompt_template_picker",
    "session_picker",
    "skill_picker_search_input",
    "skill_picker",
    "tree_picker",
    "branch_summary_instructions",
    "command_output_scroll",
    "command_output",
    "login_provider_search_input",
    "login_provider_picker",
    "login_method_picker",
    "theme_picker",
    "model_picker_search_input",
    "model_picker",
    "custom_provider_login",
    "login_screen",
    "oauth_login",
    "project_trust",
}


def test_builtin_catalog_parses_and_has_expected_keymaps() -> None:
    catalog = hotkey_catalog()

    assert set(catalog.keymap_names) == REQUIRED_KEYMAPS


def test_every_hotkey_has_key_action_and_description() -> None:
    catalog = hotkey_catalog()

    for keymap_name in REQUIRED_KEYMAPS:
        for hotkey in catalog.keymap(keymap_name).hotkeys:
            assert hotkey.name
            assert hotkey.key
            assert hotkey.action
            assert hotkey.description


def test_prompt_keymap_defaults_match_documented_shortcuts() -> None:
    catalog = hotkey_catalog()

    assert set(catalog.keys("prompt")) == set(EXPECTED_PROMPT_KEYS)
    for name, key in EXPECTED_PROMPT_KEYS.items():
        assert catalog.key("prompt", name) == key


def test_reference_keymaps_resolve_prompt_keys_and_actions() -> None:
    catalog = hotkey_catalog()

    for keymap_name in ("app", "prompt_normal", "prompt_completion", "prompt_running"):
        for hotkey in catalog.keymap(keymap_name).hotkeys:
            definition = catalog.hotkey("prompt", hotkey.name)
            assert hotkey.key == definition.key
            assert hotkey.action == definition.action


def test_app_keymap_matches_app_scope_bindings() -> None:
    catalog = hotkey_catalog()

    bindings = catalog.bindings("app")
    assert [(binding.key, binding.action) for binding in bindings] == [
        ("escape", "cancel"),
        ("ctrl+k", "open_command_palette"),
        ("ctrl+r", "open_session_picker"),
        ("ctrl+g", "open_tree_picker"),
        ("ctrl+l", "open_context"),
        ("ctrl+f", "cycle_thinking"),
        ("ctrl+p", "cycle_model"),
        ("tab", "accept_completion"),
        ("alt+enter", "submit_follow_up"),
        ("down", "completion_next"),
        ("up", "completion_previous"),
        ("ctrl+o", "toggle_tool_results"),
        ("ctrl+t", "toggle_thinking"),
        ("ctrl+c", "interrupt"),
        ("ctrl+u", "clear_prompt"),
        ("ctrl+d", "quit"),
    ]
    assert all(binding.show for binding in bindings)
    assert [binding.priority for binding in bindings] == [
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        True,
        True,
        True,
        True,
        False,
        False,
        False,
        False,
        False,
    ]


def test_prompt_mode_keymaps_carry_footer_labels() -> None:
    catalog = hotkey_catalog()

    assert [(b.key, b.description) for b in catalog.bindings("prompt_normal")] == [
        ("enter", "Submit"),
        ("shift+enter", "Newline"),
        ("ctrl+k", "Commands"),
        ("ctrl+r", "Sessions"),
        ("ctrl+g", "Tree"),
        ("ctrl+l", "Context"),
        ("ctrl+f", "Thinking"),
        ("ctrl+p", "Model"),
        ("ctrl+c", "Stop"),
        ("ctrl+u", "Clear"),
        ("ctrl+d", "Quit"),
    ]
    assert [(b.key, b.description) for b in catalog.bindings("prompt_running")] == [
        ("enter", "Steer"),
        ("alt+enter", "Follow-up"),
        ("ctrl+c", "Stop"),
        ("escape", "Cancel"),
        ("ctrl+t", "Thinking"),
        ("ctrl+o", "Tools"),
    ]
    completion = catalog.bindings("prompt_completion")
    assert [(b.key, b.description, b.key_display) for b in completion] == [
        ("tab", "Complete", "Tab/Enter"),
        ("down", "Choose", "Up/Down"),
        ("escape", "Close", None),
    ]


def test_bindings_apply_configured_key_overrides() -> None:
    catalog = hotkey_catalog()
    overrides = {"open_context": "f7", "accept_completion": "f2"}

    app_bindings = catalog.bindings("app", overrides=overrides)
    assert [b.key for b in app_bindings if b.action == "open_context"] == ["f7"]
    assert [b.key for b in app_bindings if b.action == "accept_completion"] == ["f2"]

    completion = catalog.bindings("prompt_completion", overrides=overrides)
    assert [b.key_display for b in completion if b.action == "accept_completion"] == ["F2/Enter"]


def test_unbound_hotkeys_are_documented_but_not_bound() -> None:
    catalog = hotkey_catalog()

    skill_keys = catalog.keys("skill_picker_search_input")
    assert skill_keys["show_description"] == "f1"
    assert skill_keys["show_in_transcript"] == "ctrl+enter"
    assert [b.key for b in catalog.bindings("skill_picker_search_input")] == [
        "escape",
        "up",
        "down",
    ]

    branch_keys = catalog.keys("branch_summary_instructions")
    assert branch_keys["submit"] == "ctrl+enter"
    assert [b.key for b in catalog.bindings("branch_summary_instructions")] == ["escape"]


def test_widget_keymap_bindings_match_previous_class_bindings() -> None:
    catalog = hotkey_catalog()

    assert [(b.key, b.action, b.show, b.priority) for b in catalog.bindings("session_picker")] == [
        ("escape", "cancel", True, False),
        ("up", "cursor_up", False, False),
        ("down", "cursor_down", False, False),
        ("enter", "select_cursor", False, False),
    ]
    assert [(b.key, b.action, b.priority) for b in catalog.bindings("tree_picker")] == [
        ("escape", "cancel", False),
        ("up", "cursor_up", False),
        ("down", "cursor_down", False),
        ("enter", "select_cursor", False),
        ("s", "select_with_summary", False),
        ("c", "select_with_custom_summary", False),
        ("ctrl+t", "toggle_tool_calls", False),
    ]
    login_methods = catalog.bindings("login_method_picker")
    assert [(b.key, b.action, b.show) for b in login_methods] == [
        ("escape", "cancel", True),
        ("ctrl+d", "cancel", True),
        ("up", "cursor_up", False),
        ("down", "cursor_down", False),
        ("enter", "select_cursor", False),
    ]
    assert all(b.priority for b in login_methods)


def test_duplicate_keys_within_one_keymap_are_rejected() -> None:
    with pytest.raises(HotkeyCatalogError, match="binds key 'up' to both"):
        parse_hotkey_catalog_text(
            """
            schema_version = 1

            [[keymaps]]
            name = "prompt"
            description = "x"

            [[keymaps.bindings]]
            name = "a"
            key = "up"
            action = "a"
            description = "a"

            [[keymaps.bindings]]
            name = "b"
            key = "up"
            action = "b"
            description = "b"
            """,
            source="test",
        )


def test_unresolvable_reference_is_rejected() -> None:
    with pytest.raises(HotkeyCatalogError, match="unknown prompt hotkey 'missing'"):
        parse_hotkey_catalog_text(
            """
            schema_version = 1

            [[keymaps]]
            name = "prompt"
            description = "x"

            [[keymaps.bindings]]
            name = "a"
            key = "up"
            action = "a"
            description = "a"

            [[keymaps]]
            name = "other"
            description = "x"

            [[keymaps.bindings]]
            hotkey = "missing"
            description = "label"
            """,
            source="test",
        )


def test_unknown_bindings_field_types_are_rejected() -> None:
    with pytest.raises(HotkeyCatalogError, match="show must be a boolean"):
        parse_hotkey_catalog_text(
            """
            schema_version = 1

            [[keymaps]]
            name = "prompt"
            description = "x"

            [[keymaps.bindings]]
            name = "a"
            key = "up"
            action = "a"
            description = "a"
            show = "yes"
            """,
            source="test",
        )


def test_hotkeys_path_points_at_packaged_data_file() -> None:
    assert hotkeys_path().name == "hotkeys.toml"
    assert hotkeys_path().read_text(encoding="utf-8").startswith("# Tau hotkey catalog")


def test_hotkey_catalog_is_singleton_per_process() -> None:
    assert hotkey_catalog() is hotkey_catalog()
