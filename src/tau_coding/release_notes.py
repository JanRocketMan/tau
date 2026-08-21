"""Local release-note loading and one-time startup notices."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from packaging.version import InvalidVersion, Version

from tau_coding.paths import TauPaths

RELEASE_NOTES_STATE_FILENAME = "release-notes-state.json"
RELEASE_NOTES_PATH = Path(__file__).resolve().parent / "data" / "release-notes" / "releases.json"


@dataclass(frozen=True, slots=True)
class ReleaseNoteSection:
    """A named release-note section."""

    title: str
    items: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReleaseNotesEntry:
    """Structured release notes for one Tau version."""

    version: str
    date: str | None
    sections: tuple[ReleaseNoteSection, ...]

    @property
    def transcript_items(self) -> tuple[str, ...]:
        """Return flattened note text for compact in-app display."""
        return tuple(item for section in self.sections for item in section.items)


@dataclass(frozen=True, slots=True)
class ReleaseNotesNotice:
    """Release notes shown once after the installed Tau version changes."""

    current_version: str
    previous_version: str
    entries: tuple[ReleaseNotesEntry, ...]

    @property
    def notes(self) -> tuple[str, ...]:
        """Return all release-note items included in this notice."""
        return tuple(item for entry in self.entries for item in entry.transcript_items)

    @property
    def message(self) -> str:
        """Return a compact Markdown release-notes block for the transcript."""
        if self.entries:
            version_blocks = [self._format_entry(entry) for entry in self.entries]
            body = "\n\n".join(version_blocks)
        else:
            body = "- See the changelog for details."
        return f"Tau updated to {self.current_version}\n\n{body}"

    def _format_entry(self, entry: ReleaseNotesEntry) -> str:
        section_blocks: list[str] = []
        for section in entry.sections:
            bullets = "\n".join(f"- {item}" for item in section.items)
            section_blocks.append(f"**{section.title}**\n{bullets}")
        return "\n\n".join(section_blocks)


def startup_release_notes_notice(
    current_version: str,
    *,
    state_path: Path | None = None,
    release_notes: tuple[ReleaseNotesEntry, ...] | None = None,
) -> ReleaseNotesNotice | None:
    """Return release notes once after Tau starts with a newer installed version.

    The first run only records the current version so fresh installs do not see an
    upgrade banner. Read/write failures are quiet no-ops so startup can continue.
    """
    path = state_path or default_release_notes_state_path()
    try:
        previous_version = _read_last_seen_version(path)
    except Exception:  # noqa: BLE001 - release-note state should not block startup
        previous_version = None

    _write_release_notes_state(path, current_version)
    if previous_version is None:
        return None

    try:
        if Version(current_version) <= Version(previous_version):
            return None
    except InvalidVersion:
        return None

    if release_notes is None:
        try:
            release_notes = load_release_notes()
        except Exception:  # noqa: BLE001 - a broken bundled file must not block startup
            release_notes = ()

    entries = release_notes_between(
        previous_version,
        current_version,
        release_notes,
    )
    return ReleaseNotesNotice(
        current_version=current_version,
        previous_version=previous_version,
        entries=entries,
    )


def load_release_notes(path: Path | None = None) -> tuple[ReleaseNotesEntry, ...]:
    """Load structured release notes from the bundled JSON file."""
    data = json.loads((path or RELEASE_NOTES_PATH).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("release notes must be a JSON array")
    return tuple(_parse_release_notes_entry(item) for item in data)


def release_notes_between(
    previous_version: str,
    current_version: str,
    release_notes: tuple[ReleaseNotesEntry, ...],
) -> tuple[ReleaseNotesEntry, ...]:
    """Return release-note entries newer than previous_version up to current_version."""
    try:
        previous = Version(previous_version)
        current = Version(current_version)
    except InvalidVersion:
        return ()

    selected: list[ReleaseNotesEntry] = []
    for entry in release_notes:
        try:
            parsed = Version(entry.version)
        except InvalidVersion:
            continue
        if previous < parsed <= current:
            selected.append(entry)
    return tuple(sorted(selected, key=lambda entry: Version(entry.version)))


def default_release_notes_state_path(paths: TauPaths | None = None) -> Path:
    """Return the on-disk state path for one-time release notes."""
    return (paths or TauPaths()).logs_dir / RELEASE_NOTES_STATE_FILENAME


def _parse_release_notes_entry(data: Any) -> ReleaseNotesEntry:
    if not isinstance(data, dict):
        raise ValueError("release note entry must be an object")
    version = data.get("version")
    if not isinstance(version, str):
        raise ValueError("release note entry missing version")
    date = data.get("date")
    if date is not None and not isinstance(date, str):
        raise ValueError("release note date must be a string")
    raw_sections = data.get("sections")
    if not isinstance(raw_sections, dict):
        raise ValueError("release note sections must be an object")

    sections: list[ReleaseNoteSection] = []
    for title, raw_items in raw_sections.items():
        if not isinstance(title, str):
            raise ValueError("release note section title must be a string")
        if not isinstance(raw_items, list) or not all(isinstance(item, str) for item in raw_items):
            raise ValueError("release note section items must be strings")
        sections.append(ReleaseNoteSection(title=title, items=tuple(raw_items)))
    return ReleaseNotesEntry(version=version, date=date, sections=tuple(sections))


def _read_last_seen_version(path: Path) -> str | None:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("release-note state must be a JSON object")
    version = data.get("last_seen_version")
    if version is not None and not isinstance(version, str):
        raise ValueError("release-note last_seen_version must be a string")
    return version


def _write_release_notes_state(path: Path, current_version: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"last_seen_version": current_version}, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError:
        return
