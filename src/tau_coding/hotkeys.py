"""Typed access to Tau's packaged hotkey catalog.

The packaged ``src/tau_coding/data/hotkeys.toml`` is Tau's single source of
truth for every keyboard shortcut in the TUI. Each entry names the key, the
action it triggers, and a short description; every scope (the prompt, app
bindings, prompt footer modes, pickers, and modals) is one ``keymap``. The TUI
builds its Textual ``Binding`` lists from this catalog, and
``TuiKeybindings`` derives its defaults from it. Edit the file directly to
change or document hotkeys.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import Any

from textual.binding import Binding, BindingType

HOTKEYS_SCHEMA_VERSION = 1

#: The keymap whose entries define keys and actions for every other keymap.
PROMPT_KEYMAP = "prompt"


class HotkeyCatalogError(ValueError):
    """Raised when a Tau hotkey catalog file is invalid."""


@dataclass(frozen=True, slots=True)
class Hotkey:
    """One keyboard shortcut within a keymap.

    Attributes:
        name: Stable identifier used by code and by other keymaps.
        key: Key in Textual syntax, for example ``"ctrl+k"``.
        action: Textual action run when the key is pressed.
        description: Short description of what the hotkey does.
        show: Whether the binding may appear in a Textual footer.
        priority: Whether the binding wins over focused-widget key handling.
        bound: Whether the key is registered as a Textual binding. ``False``
            means the owning widget handles the key itself in ``on_key``.
        key_display: Optional footer display text; ``{name}`` placeholders
            expand to that hotkey's effective key.
    """

    name: str
    key: str
    action: str
    description: str
    show: bool = True
    priority: bool = False
    bound: bool = True
    key_display: str | None = None


@dataclass(frozen=True, slots=True)
class HotkeyKeymap:
    """A named set of hotkeys for one screen, widget, or prompt mode."""

    name: str
    description: str
    hotkeys: tuple[Hotkey, ...]


class HotkeyCatalog:
    """Parsed hotkey catalog with named keymaps and hotkey lookups."""

    def __init__(self, keymaps: tuple[HotkeyKeymap, ...]) -> None:
        self._keymaps = {keymap.name: keymap for keymap in keymaps}
        self._hotkeys = {
            keymap.name: {hotkey.name: hotkey for hotkey in keymap.hotkeys} for keymap in keymaps
        }

    def keymap(self, name: str) -> HotkeyKeymap:
        """Return one keymap by name."""
        try:
            return self._keymaps[name]
        except KeyError as error:
            raise HotkeyCatalogError(f"unknown hotkey keymap {name!r}") from error

    @property
    def keymap_names(self) -> tuple[str, ...]:
        """Return the keymap names in catalog order."""
        return tuple(self._keymaps)

    def hotkey(self, keymap: str, name: str) -> Hotkey:
        """Return one hotkey by keymap and name."""
        try:
            return self._hotkeys[keymap][name]
        except KeyError as error:
            raise HotkeyCatalogError(f"keymap {keymap!r} has no hotkey {name!r}") from error

    def key(self, keymap: str, name: str) -> str:
        """Return the key for one hotkey."""
        return self.hotkey(keymap, name).key

    def action(self, keymap: str, name: str) -> str:
        """Return the action for one hotkey."""
        return self.hotkey(keymap, name).action

    def keys(self, keymap: str) -> dict[str, str]:
        """Return a hotkey name-to-key map for one keymap."""
        return {hotkey.name: hotkey.key for hotkey in self.keymap(keymap).hotkeys}

    def effective_keys(
        self,
        keymap: str = PROMPT_KEYMAP,
        *,
        overrides: Mapping[str, str] | None = None,
    ) -> dict[str, str]:
        """Return a hotkey name-to-key map with optional per-name overrides.

        Overrides come from user-configured ``TuiKeybindings``; names that
        appear only in the packaged catalog keep their default keys.
        """
        keys = self.keys(keymap)
        if overrides:
            keys.update(overrides)
        return keys

    def bindings(
        self,
        keymap: str,
        *,
        overrides: Mapping[str, str] | None = None,
    ) -> list[BindingType]:
        """Build the Textual binding list for one keymap.

        ``overrides`` remap configured prompt hotkeys; ``key_display``
        placeholders expand with the effective keys, so footer hints follow
        user remaps too. Unbound entries (``bound = false``) are excluded;
        their owning widgets read the keys via :meth:`keys`.
        """
        effective = self.effective_keys(overrides=overrides)
        display_keys = {name: display_key(key) for name, key in effective.items()}
        bindings: list[BindingType] = []
        for hotkey in self.keymap(keymap).hotkeys:
            if not hotkey.bound:
                continue
            key = overrides.get(hotkey.name, hotkey.key) if overrides else hotkey.key
            key_display = (
                self._expand_key_display(hotkey.key_display, display_keys)
                if hotkey.key_display is not None
                else None
            )
            bindings.append(
                Binding(
                    key,
                    hotkey.action,
                    hotkey.description,
                    show=hotkey.show,
                    priority=hotkey.priority,
                    key_display=key_display,
                )
            )
        return bindings

    def _expand_key_display(self, key_display: str, keys: Mapping[str, str]) -> str:
        try:
            return key_display.format(**keys)
        except KeyError as error:
            raise HotkeyCatalogError(
                f"key_display {key_display!r} references unknown hotkey {error.args[0]!r}"
            ) from error


def display_key(key: str) -> str:
    """Render a key for user-facing hints, for example ``"ctrl+k"`` -> ``"Ctrl+K"``."""
    return "+".join(part.capitalize() for part in key.split("+"))


def builtin_hotkeys_resource_text() -> str:
    """Return the packaged builtin hotkey catalog TOML text."""
    return files("tau_coding").joinpath("data/hotkeys.toml").read_text(encoding="utf-8")


def hotkeys_path() -> Path:
    """Return the packaged ``data/hotkeys.toml`` file path."""
    return Path(files("tau_coding").joinpath("data/hotkeys.toml").__fspath__())


def parse_hotkey_catalog_text(text: str, *, source: str) -> HotkeyCatalog:
    """Parse and validate hotkey catalog TOML text."""
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise HotkeyCatalogError(f"{source}: invalid TOML: {error}") from error
    return _catalog_from_raw(raw, source=source)


@lru_cache(maxsize=1)
def hotkey_catalog() -> HotkeyCatalog:
    """Return the packaged hotkey catalog, parsed once per process."""
    return parse_hotkey_catalog_text(
        builtin_hotkeys_resource_text(),
        source=str(hotkeys_path()),
    )


def _catalog_from_raw(raw: dict[str, Any], *, source: str) -> HotkeyCatalog:
    _validate_schema_version(raw, source=source)
    raw_keymaps = raw.get("keymaps")
    if not isinstance(raw_keymaps, list):
        raise HotkeyCatalogError(f"{source}: keymaps must be a list")
    parsed = [
        _parse_keymap(entry, source=source, index=index) for index, entry in enumerate(raw_keymaps)
    ]
    prompt = next((keymap for keymap in parsed if keymap.name == PROMPT_KEYMAP), None)
    if prompt is None:
        raise HotkeyCatalogError(f"{source}: keymap {PROMPT_KEYMAP!r} is required")
    prompt_hotkeys = {hotkey.name: hotkey for hotkey in prompt.hotkeys}
    keymaps: list[HotkeyKeymap] = []
    for keymap in parsed:
        if keymap.name == PROMPT_KEYMAP:
            keymaps.append(prompt)
            continue
        # Reference entries were parsed with an empty key; definitions keep
        # their own key. Resolve references against the prompt keymap.
        resolved = tuple(
            _resolve_reference(keymap, hotkey, prompt_hotkeys, source=source)
            if not hotkey.key
            else hotkey
            for hotkey in keymap.hotkeys
        )
        keymaps.append(HotkeyKeymap(keymap.name, keymap.description, resolved))
    catalog = HotkeyCatalog(tuple(keymaps))
    prompt_keys = {name: hotkey.key for name, hotkey in prompt_hotkeys.items()}
    for keymap in keymaps:
        _validate_unique_keys(keymap, source=source)
        for hotkey in keymap.hotkeys:
            if hotkey.key_display is not None:
                catalog._expand_key_display(hotkey.key_display, prompt_keys)
    return catalog


def _validate_schema_version(raw: dict[str, Any], *, source: str) -> None:
    version = raw.get("schema_version")
    if not isinstance(version, int):
        raise HotkeyCatalogError(f"{source}: schema_version must be an integer")
    if version != HOTKEYS_SCHEMA_VERSION:
        raise HotkeyCatalogError(
            f"{source}: unsupported schema_version {version}; expected {HOTKEYS_SCHEMA_VERSION}"
        )


def _parse_keymap(raw: Any, *, source: str, index: int) -> HotkeyKeymap:
    prefix = f"{source}: keymaps[{index}]"
    if not isinstance(raw, dict):
        raise HotkeyCatalogError(f"{prefix} must be a table")
    name = _required_string(raw, "name", prefix=prefix)
    description = _required_string(raw, "description", prefix=prefix)
    raw_bindings = raw.get("bindings")
    if not isinstance(raw_bindings, list):
        raise HotkeyCatalogError(f"{prefix}: bindings must be a list")
    hotkeys = tuple(
        _parse_hotkey(binding, source=source, keymap=name, index=entry_index)
        for entry_index, binding in enumerate(raw_bindings)
    )
    _validate_unique_names(hotkeys, prefix=prefix)
    return HotkeyKeymap(name=name, description=description, hotkeys=hotkeys)


def _parse_hotkey(raw: Any, *, source: str, keymap: str, index: int) -> Hotkey:
    prefix = f"{source}: keymaps.{keymap}.bindings[{index}]"
    if not isinstance(raw, dict):
        raise HotkeyCatalogError(f"{prefix} must be a table")
    reference = raw.get("hotkey")
    if reference is not None:
        if keymap == PROMPT_KEYMAP:
            raise HotkeyCatalogError(
                f"{prefix}: keymap {PROMPT_KEYMAP!r} defines hotkeys and cannot reference them"
            )
        if not isinstance(reference, str) or not reference.strip():
            raise HotkeyCatalogError(f"{prefix}: hotkey must be a non-empty string")
        return Hotkey(
            name=reference.strip(),
            key="",
            action="",
            description=_required_string(raw, "description", prefix=prefix),
            show=_optional_bool(raw, "show", prefix=prefix, default=True),
            priority=_optional_bool(raw, "priority", prefix=prefix, default=False),
            bound=_optional_bool(raw, "bound", prefix=prefix, default=True),
            key_display=_optional_string(raw, "key_display", prefix=prefix),
        )
    return Hotkey(
        name=_required_string(raw, "name", prefix=prefix),
        key=_required_string(raw, "key", prefix=prefix),
        action=_required_string(raw, "action", prefix=prefix),
        description=_required_string(raw, "description", prefix=prefix),
        show=_optional_bool(raw, "show", prefix=prefix, default=True),
        priority=_optional_bool(raw, "priority", prefix=prefix, default=False),
        bound=_optional_bool(raw, "bound", prefix=prefix, default=True),
        key_display=_optional_string(raw, "key_display", prefix=prefix),
    )


def _resolve_reference(
    keymap: HotkeyKeymap,
    hotkey: Hotkey,
    prompt_hotkeys: Mapping[str, Hotkey],
    *,
    source: str,
) -> Hotkey:
    definition = prompt_hotkeys.get(hotkey.name)
    if definition is None:
        raise HotkeyCatalogError(
            f"{source}: keymaps.{keymap.name} references unknown prompt hotkey {hotkey.name!r}"
        )
    return Hotkey(
        name=definition.name,
        key=definition.key,
        action=definition.action,
        description=hotkey.description,
        show=hotkey.show,
        priority=hotkey.priority,
        bound=hotkey.bound,
        key_display=hotkey.key_display,
    )


def _validate_unique_names(hotkeys: tuple[Hotkey, ...], *, prefix: str) -> None:
    seen: set[str] = set()
    for hotkey in hotkeys:
        if hotkey.name in seen:
            raise HotkeyCatalogError(f"{prefix}: duplicate hotkey name {hotkey.name!r}")
        seen.add(hotkey.name)


def _validate_unique_keys(keymap: HotkeyKeymap, *, source: str) -> None:
    seen: dict[str, str] = {}
    for hotkey in keymap.hotkeys:
        if not hotkey.bound:
            continue
        previous = seen.get(hotkey.key)
        if previous is not None:
            raise HotkeyCatalogError(
                f"{source}: keymaps.{keymap.name} binds key {hotkey.key!r} to "
                f"both {previous!r} and {hotkey.name!r}"
            )
        seen[hotkey.key] = hotkey.name


def _required_string(raw: dict[str, Any], field: str, *, prefix: str) -> str:
    value = _optional_string(raw, field, prefix=prefix)
    if value is None:
        raise HotkeyCatalogError(f"{prefix}: {field} is required")
    return value


def _optional_string(raw: dict[str, Any], field: str, *, prefix: str) -> str | None:
    value = raw.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise HotkeyCatalogError(f"{prefix}: {field} must be a non-empty string")
    return value.strip()


def _optional_bool(raw: dict[str, Any], field: str, *, prefix: str, default: bool) -> bool:
    value = raw.get(field)
    if value is None:
        return default
    if not isinstance(value, bool):
        raise HotkeyCatalogError(f"{prefix}: {field} must be a boolean")
    return value
