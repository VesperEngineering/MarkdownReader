from pathlib import Path

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog

from markdown_reader.app import MarkdownWindow


@pytest.fixture
def window(qtbot, monkeypatch):
    monkeypatch.setattr(MarkdownWindow, "_restore_settings", lambda self: None)
    widget = MarkdownWindow()
    qtbot.addWidget(widget)
    return widget


def test_open_renders_markdown(window, tmp_path):
    source = tmp_path / "hello.md"
    source.write_text("# Hello\n\nThis is **bold**.", encoding="utf-8")

    assert window.open_path(source)

    assert window.current_path == source.resolve()
    assert window.editor.toPlainText().startswith("# Hello")
    assert "Hello" in window.preview.toPlainText()
    assert "bold" in window.preview.toPlainText()
    assert not window.dirty


def test_window_has_application_icon(window):
    assert not window.windowIcon().isNull()


def test_markdown_drop_events_reach_the_window(window):
    assert window.acceptDrops()
    assert not window.editor.acceptDrops()
    assert not window.editor.viewport().acceptDrops()
    assert not window.preview.acceptDrops()
    assert not window.preview.viewport().acceptDrops()


def test_edit_marks_dirty_and_save_writes_utf8(window, tmp_path):
    source = tmp_path / "notes.md"
    source.write_text("Original", encoding="utf-8")
    window.open_path(source)

    window.editor.setPlainText("Changed — café")
    assert window.dirty
    assert window.save()

    assert source.read_text(encoding="utf-8") == "Changed — café"
    assert not window.dirty


def test_save_as_adds_markdown_extension(window, tmp_path, monkeypatch):
    destination = tmp_path / "new-document"
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(destination), "Markdown files (*.md)"),
    )
    window.new_document()
    window.editor.setPlainText("# New")

    saved_path = destination.with_suffix(".md")
    assert window.save_as()
    assert saved_path.read_text(encoding="utf-8") == "# New"
    assert window.settings.value("lastDirectory") == str(saved_path.parent)


def test_view_modes_and_zoom(window):
    window.set_view("preview")
    assert not window.editor.isVisible()
    assert window.preview_action.isChecked()
    window.set_view("editor")
    assert not window.preview.isVisible()
    assert window.edit_action.isChecked()
    window.set_view("split")
    assert window.split_action.isChecked()
    window.set_view("invalid")
    assert window.split_action.isChecked()

    window.zoom_in()
    assert window._preview_zoom == 1
    window.zoom_reset()
    assert window._preview_zoom == 0


def test_pdf_export_creates_nonempty_file(window, tmp_path, monkeypatch):
    source = tmp_path / "report.md"
    output = tmp_path / "report.pdf"
    source.write_text("# Report\n\nPDF body.", encoding="utf-8")
    window.open_path(source)
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(output), "PDF files (*.pdf)"),
    )

    window.export_pdf()

    assert output.exists()
    assert output.stat().st_size > 100
    assert output.read_bytes().startswith(b"%PDF")


def test_open_link_preserves_fragment_for_relative_file(window, tmp_path, monkeypatch):
    source = tmp_path / "index.md"
    source.write_text("[Details](chapter.md#details)", encoding="utf-8")
    target = tmp_path / "chapter.md"
    target.write_text("# Details", encoding="utf-8")
    opened: list[QUrl] = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url) or True)
    window.open_path(source)

    window._open_link(QUrl("chapter.md#details"))

    assert len(opened) == 1
    assert Path(opened[0].toLocalFile()) == target.resolve()
    assert opened[0].fragment() == "details"


def test_open_link_keeps_document_anchor_in_preview(window, tmp_path, monkeypatch):
    source = tmp_path / "index.md"
    source.write_text("# Details\n\n[Jump to details](#details)", encoding="utf-8")
    opened: list[QUrl] = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url) or True)
    window.open_path(source)

    window._open_link(QUrl("#details"))

    assert opened == []
