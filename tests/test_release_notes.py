from pathlib import Path

import pytest

from tau_coding.release_notes import (
    ReleaseNoteSection,
    ReleaseNotesEntry,
    load_release_notes,
    release_notes_between,
    startup_release_notes_notice,
)


def test_load_release_notes_reads_shared_json(tmp_path: Path) -> None:
    notes_path = tmp_path / "releases.json"
    notes_path.write_text(
        """
        [
          {
            "version": "0.1.2",
            "date": "2026-07-03",
            "sections": {"New": ["Feature"], "Fixed": ["Fix"]}
          }
        ]
        """,
        encoding="utf-8",
    )

    notes = load_release_notes(notes_path)

    assert notes == (
        ReleaseNotesEntry(
            version="0.1.2",
            date="2026-07-03",
            sections=(
                ReleaseNoteSection(title="New", items=("Feature",)),
                ReleaseNoteSection(title="Fixed", items=("Fix",)),
            ),
        ),
    )


def test_startup_release_notes_notice_records_first_seen_version(tmp_path: Path) -> None:
    state_path = tmp_path / "release-notes-state.json"

    notice = startup_release_notes_notice(
        "0.1.2",
        state_path=state_path,
        release_notes=(
            ReleaseNotesEntry(
                version="0.1.2",
                date=None,
                sections=(ReleaseNoteSection(title="New", items=("New TUI release notes",)),),
            ),
        ),
    )

    assert notice is None
    assert '"last_seen_version": "0.1.2"' in state_path.read_text(encoding="utf-8")


def test_startup_release_notes_notice_reports_upgrade_once(tmp_path: Path) -> None:
    state_path = tmp_path / "release-notes-state.json"
    state_path.write_text('{"last_seen_version":"0.1.1"}\n', encoding="utf-8")
    release_notes = (
        ReleaseNotesEntry(
            version="0.1.2",
            date=None,
            sections=(ReleaseNoteSection(title="New", items=("New feature", "Bug fix")),),
        ),
    )

    notice = startup_release_notes_notice(
        "0.1.2",
        state_path=state_path,
        release_notes=release_notes,
    )

    assert notice is not None
    assert notice.previous_version == "0.1.1"
    assert notice.current_version == "0.1.2"
    assert notice.notes == ("New feature", "Bug fix")
    assert notice.message == "Tau updated to 0.1.2\n\n**New**\n- New feature\n- Bug fix"

    second_notice = startup_release_notes_notice(
        "0.1.2",
        state_path=state_path,
        release_notes=release_notes,
    )
    assert second_notice is None


def test_startup_release_notes_notice_survives_missing_release_notes_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import tau_coding.release_notes as release_notes_module

    monkeypatch.setattr(
        release_notes_module,
        "RELEASE_NOTES_PATH",
        tmp_path / "missing" / "releases.json",
    )
    state_path = tmp_path / "release-notes-state.json"
    state_path.write_text('{"last_seen_version":"0.1.1"}\n', encoding="utf-8")

    notice = startup_release_notes_notice("0.1.2", state_path=state_path)

    assert notice is not None
    assert notice.entries == ()


def test_startup_release_notes_notice_survives_malformed_release_notes_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import tau_coding.release_notes as release_notes_module

    broken_path = tmp_path / "releases.json"
    broken_path.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(release_notes_module, "RELEASE_NOTES_PATH", broken_path)
    state_path = tmp_path / "release-notes-state.json"
    state_path.write_text('{"last_seen_version":"0.1.1"}\n', encoding="utf-8")

    notice = startup_release_notes_notice("0.1.2", state_path=state_path)

    assert notice is not None
    assert notice.entries == ()


def test_startup_release_notes_notice_combines_skipped_versions(tmp_path: Path) -> None:
    state_path = tmp_path / "release-notes-state.json"
    state_path.write_text('{"last_seen_version":"0.1.0"}\n', encoding="utf-8")
    release_notes = (
        ReleaseNotesEntry(
            version="0.1.2",
            date=None,
            sections=(ReleaseNoteSection(title="New", items=("Second change",)),),
        ),
        ReleaseNotesEntry(
            version="0.1.1",
            date=None,
            sections=(ReleaseNoteSection(title="Fixed", items=("First change",)),),
        ),
        ReleaseNotesEntry(
            version="0.1.3",
            date=None,
            sections=(ReleaseNoteSection(title="New", items=("Future change",)),),
        ),
    )

    notice = startup_release_notes_notice(
        "0.1.2",
        state_path=state_path,
        release_notes=release_notes,
    )

    assert notice is not None
    assert notice.notes == ("First change", "Second change")


def test_release_notes_between_ignores_future_versions() -> None:
    entries = (
        ReleaseNotesEntry(version="0.1.1", date=None, sections=()),
        ReleaseNotesEntry(version="0.1.2", date=None, sections=()),
        ReleaseNotesEntry(version="0.1.3", date=None, sections=()),
    )

    assert release_notes_between("0.1.1", "0.1.2", entries) == (entries[1],)


def test_load_release_notes_resolves_default_path() -> None:
    entries = load_release_notes()

    assert entries
    assert all(entry.version for entry in entries)
