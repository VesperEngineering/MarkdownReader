from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QSettings, QTimer, Qt, QUrl
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent, QDesktopServices, QFont, QIcon, QKeySequence, QTextDocument
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QToolBar,
    QVBoxLayout,
    QWidget,
    QTextBrowser,
)

APP_NAME = "Markdown Reader"
ICON_PATH = Path(__file__).resolve().parent / "assets" / "icon.png"
MARKDOWN_FILTER = "Markdown files (*.md *.markdown *.mdown *.mkd);;All files (*.*)"
MARKDOWN_EXTENSIONS = {".md", ".markdown", ".mdown", ".mkd"}
WELCOME = """# Markdown Reader

Drop a Markdown file anywhere in this window, or use **File → Open** (`Ctrl+O`).

You can read, edit, save, export to PDF, search, and zoom.
"""

PREVIEW_CSS = """
body { font-family: 'Segoe UI', sans-serif; font-size: 11pt; line-height: 1.5;
       color: #24292f; margin: 28px; }
h1, h2 { border-bottom: 1px solid #d0d7de; padding-bottom: 0.3em; }
h1, h2, h3, h4 { color: #1f2328; }
pre, code { font-family: Consolas, monospace; background: #f6f8fa; }
pre { padding: 12px; border: 1px solid #d8dee4; }
blockquote { color: #57606a; border-left: 4px solid #d0d7de; padding-left: 12px; }
table { border-collapse: collapse; }
th, td { border: 1px solid #d0d7de; padding: 6px 12px; }
a { color: #0969da; }
"""


class MarkdownWindow(QMainWindow):
    def __init__(self, initial_path: str | None = None) -> None:
        super().__init__()
        self.setWindowIcon(QIcon(str(ICON_PATH)))
        self.settings = QSettings("HermesTools", APP_NAME)
        self.current_path: Path | None = None
        self.dirty = False
        self.last_find = ""
        self._preview_zoom = 0
        self._editor_zoom = 0
        self._updating_editor = False

        self.setAcceptDrops(True)
        self.resize(1100, 760)
        self.setMinimumSize(700, 480)
        self._build_ui()
        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self._restore_settings()
        self._show_welcome()

        if initial_path:
            QTimer.singleShot(0, lambda: self.open_path(Path(initial_path)))

    def _build_ui(self) -> None:
        root = QWidget(self)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.editor = QPlainTextEdit()
        # QPlainTextEdit accepts text drops by default, which prevents file drops
        # over the editor from reaching MarkdownWindow.dropEvent.
        self.editor.setAcceptDrops(False)
        self.editor.setPlaceholderText("Open or drop a Markdown file, then edit its source here…")
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.editor.setFont(QFont("Consolas", 11))
        self.editor.textChanged.connect(self._on_text_changed)

        self.preview = QTextBrowser()
        # QTextBrowser also accepts drops by default; let the main window handle
        # them so dropping works across both panes.
        self.preview.setAcceptDrops(False)
        self.preview.setOpenLinks(False)
        self.preview.anchorClicked.connect(self._open_link)
        self.preview.document().setDefaultStyleSheet(PREVIEW_CSS)

        self.splitter.addWidget(self.editor)
        self.splitter.addWidget(self.preview)
        self.splitter.setSizes([470, 630])
        layout.addWidget(self.splitter, 1)

        self.find_bar = QWidget()
        find_layout = QHBoxLayout(self.find_bar)
        find_layout.setContentsMargins(8, 5, 8, 5)
        find_layout.addWidget(QLabel("Find:"))
        self.find_input = QLineEdit()
        self.find_input.setClearButtonEnabled(True)
        self.find_input.returnPressed.connect(self.find_next)
        find_layout.addWidget(self.find_input, 1)
        previous = QPushButton("Previous")
        previous.clicked.connect(self.find_previous)
        find_layout.addWidget(previous)
        next_button = QPushButton("Next")
        next_button.clicked.connect(self.find_next)
        find_layout.addWidget(next_button)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.hide_find)
        find_layout.addWidget(close_button)
        self.find_bar.hide()
        layout.addWidget(self.find_bar)

        self.setCentralWidget(root)
        self.statusBar().showMessage("Drop a Markdown file here to open it")

    def _action(self, text: str, slot, shortcut: str | QKeySequence | None = None) -> QAction:
        action = QAction(text, self)
        action.triggered.connect(slot)
        if shortcut:
            action.setShortcut(shortcut)
        return action

    def _build_actions(self) -> None:
        self.new_action = self._action("&New", self.new_document, QKeySequence.StandardKey.New)
        self.open_action = self._action("&Open…", self.open_dialog, QKeySequence.StandardKey.Open)
        self.close_action = self._action("&Close File", self.close_document, "Ctrl+W")
        self.save_action = self._action("&Save", self.save, QKeySequence.StandardKey.Save)
        self.save_as_action = self._action("Save &As…", self.save_as, QKeySequence.StandardKey.SaveAs)
        self.pdf_action = self._action("Export as &PDF…", self.export_pdf, QKeySequence.StandardKey.Print)
        self.exit_action = self._action("E&xit", self.close, QKeySequence.StandardKey.Quit)

        self.undo_action = self._action("&Undo", self.editor.undo, QKeySequence.StandardKey.Undo)
        self.redo_action = self._action("&Redo", self.editor.redo, QKeySequence.StandardKey.Redo)
        self.cut_action = self._action("Cu&t", self.editor.cut, QKeySequence.StandardKey.Cut)
        self.copy_action = self._action("&Copy", self.copy, QKeySequence.StandardKey.Copy)
        self.paste_action = self._action("&Paste", self.editor.paste, QKeySequence.StandardKey.Paste)
        self.select_all_action = self._action("Select &All", self.select_all, QKeySequence.StandardKey.SelectAll)
        self.find_action = self._action("&Find…", self.show_find, QKeySequence.StandardKey.Find)
        self.find_next_action = self._action("Find &Next", self.find_next, QKeySequence.StandardKey.FindNext)

        self.zoom_in_action = self._action("Zoom &In", self.zoom_in, QKeySequence.StandardKey.ZoomIn)
        self.zoom_out_action = self._action("Zoom &Out", self.zoom_out, QKeySequence.StandardKey.ZoomOut)
        self.zoom_reset_action = self._action("&Reset Zoom", self.zoom_reset, "Ctrl+0")

        self.view_group = QActionGroup(self)
        self.view_group.setExclusive(True)
        self.split_action = self._view_action("&Split View", "split", "Ctrl+1", True)
        self.preview_action = self._view_action("&Preview Only", "preview", "Ctrl+2")
        self.edit_action = self._view_action("&Editor Only", "editor", "Ctrl+3")

        self.about_action = self._action("&About", self.about)

    def _view_action(self, text: str, mode: str, shortcut: str, checked: bool = False) -> QAction:
        action = QAction(text, self)
        action.setCheckable(True)
        action.setChecked(checked)
        action.setShortcut(shortcut)
        action.triggered.connect(lambda _checked=False, value=mode: self.set_view(value))
        self.view_group.addAction(action)
        return action

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        file_menu.addActions([self.new_action, self.open_action])
        self.recent_menu = QMenu("Open &Recent", self)
        file_menu.addMenu(self.recent_menu)
        file_menu.addSeparator()
        file_menu.addActions([self.close_action, self.save_action, self.save_as_action])
        file_menu.addSeparator()
        file_menu.addAction(self.pdf_action)
        file_menu.addSeparator()
        file_menu.addAction(self.exit_action)

        edit_menu = self.menuBar().addMenu("&Edit")
        edit_menu.addActions([self.undo_action, self.redo_action])
        edit_menu.addSeparator()
        edit_menu.addActions([self.cut_action, self.copy_action, self.paste_action, self.select_all_action])
        edit_menu.addSeparator()
        edit_menu.addActions([self.find_action, self.find_next_action])

        view_menu = self.menuBar().addMenu("&View")
        view_menu.addActions([self.split_action, self.preview_action, self.edit_action])
        view_menu.addSeparator()
        view_menu.addActions([self.zoom_in_action, self.zoom_out_action, self.zoom_reset_action])

        help_menu = self.menuBar().addMenu("&Help")
        help_menu.addAction(self.about_action)
        self._refresh_recent_menu()

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Main toolbar", self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        toolbar.addActions([self.open_action, self.save_action, self.pdf_action])
        toolbar.addSeparator()
        toolbar.addActions([self.split_action, self.preview_action, self.edit_action])
        toolbar.addSeparator()
        toolbar.addActions([self.zoom_out_action, self.zoom_in_action, self.zoom_reset_action])

    def _restore_settings(self) -> None:
        geometry = self.settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        state = self.settings.value("windowState")
        if state:
            self.restoreState(state)

    def _show_welcome(self) -> None:
        self._updating_editor = True
        self.editor.clear()
        self._updating_editor = False
        self.preview.document().setMarkdown(WELCOME, QTextDocument.MarkdownDialectGitHub)
        self.preview.document().setDefaultStyleSheet(PREVIEW_CSS)
        self.current_path = None
        self.dirty = False
        self._update_title()

    def _render(self, text: str) -> None:
        document = self.preview.document()
        if self.current_path:
            document.setBaseUrl(QUrl.fromLocalFile(str(self.current_path.parent) + "/"))
        else:
            document.setBaseUrl(QUrl())
        document.setMarkdown(text, QTextDocument.MarkdownDialectGitHub)
        document.setDefaultStyleSheet(PREVIEW_CSS)

    def _on_text_changed(self) -> None:
        if self._updating_editor:
            return
        self.dirty = True
        self._render(self.editor.toPlainText())
        self._update_title()

    def _update_title(self) -> None:
        name = self.current_path.name if self.current_path else "Untitled"
        marker = " *" if self.dirty else ""
        self.setWindowTitle(f"{name}{marker} — {APP_NAME}")

    def new_document(self) -> None:
        if not self._confirm_discard():
            return
        self.current_path = None
        self._updating_editor = True
        self.editor.clear()
        self._updating_editor = False
        self.dirty = False
        self._render("")
        self._update_title()
        self.editor.setFocus()
        self.statusBar().showMessage("New document", 3000)

    def open_dialog(self) -> None:
        start = self.settings.value("lastDirectory", str(Path.home()))
        filename, _ = QFileDialog.getOpenFileName(self, "Open Markdown", start, MARKDOWN_FILTER)
        if filename:
            self.open_path(Path(filename))

    def open_path(self, path: Path) -> bool:
        path = path.expanduser().resolve()
        if not path.is_file():
            QMessageBox.warning(self, APP_NAME, f"File not found:\n{path}")
            return False
        if not self._confirm_discard():
            return False
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            QMessageBox.critical(self, APP_NAME, f"Could not open the file:\n{exc}")
            return False

        self.current_path = path
        self._updating_editor = True
        self.editor.setPlainText(text)
        self._updating_editor = False
        self.dirty = False
        self._render(text)
        self.editor.document().setModified(False)
        self.settings.setValue("lastDirectory", str(path.parent))
        self._add_recent(path)
        self._update_title()
        self.statusBar().showMessage(f"Opened {path}", 5000)
        return True

    def close_document(self) -> None:
        if self._confirm_discard():
            self._show_welcome()
            self.statusBar().showMessage("File closed", 3000)

    def save(self) -> bool:
        if self.current_path is None:
            return self.save_as()
        return self._write_to(self.current_path)

    def save_as(self) -> bool:
        suggested = str(self.current_path or (Path.home() / "document.md"))
        filename, _ = QFileDialog.getSaveFileName(self, "Save Markdown As", suggested, MARKDOWN_FILTER)
        if not filename:
            return False
        path = Path(filename)
        if not path.suffix:
            path = path.with_suffix(".md")
        return self._write_to(path)

    def _write_to(self, path: Path) -> bool:
        try:
            path.write_text(self.editor.toPlainText(), encoding="utf-8")
        except OSError as exc:
            QMessageBox.critical(self, APP_NAME, f"Could not save the file:\n{exc}")
            return False
        self.current_path = path.resolve()
        self.dirty = False
        self.editor.document().setModified(False)
        self._render(self.editor.toPlainText())
        self.settings.setValue("lastDirectory", str(self.current_path.parent))
        self._add_recent(self.current_path)
        self._update_title()
        self.statusBar().showMessage(f"Saved {self.current_path}", 5000)
        return True

    def export_pdf(self) -> None:
        suggested = (self.current_path.with_suffix(".pdf") if self.current_path else Path.home() / "document.pdf")
        filename, _ = QFileDialog.getSaveFileName(self, "Export PDF", str(suggested), "PDF files (*.pdf)")
        if not filename:
            return
        path = Path(filename)
        if path.suffix.lower() != ".pdf":
            path = path.with_suffix(".pdf")
        try:
            printer = QPrinter(QPrinter.PrinterMode.HighResolution)
            printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
            printer.setOutputFileName(str(path))
            printer.setDocName(self.current_path.name if self.current_path else "Markdown document")
            self.preview.document().print_(printer)
        except Exception as exc:
            QMessageBox.critical(self, APP_NAME, f"Could not export the PDF:\n{exc}")
            return
        self.statusBar().showMessage(f"Exported PDF to {path}", 7000)

    def _confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        result = QMessageBox.question(
            self,
            "Unsaved changes",
            "Save changes before continuing?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if result == QMessageBox.StandardButton.Cancel:
            return False
        if result == QMessageBox.StandardButton.Save:
            return self.save()
        return True

    def set_view(self, mode: str) -> None:
        if mode not in {"split", "preview", "editor"}:
            return
        self.editor.setVisible(mode in {"split", "editor"})
        self.preview.setVisible(mode in {"split", "preview"})
        self.split_action.setChecked(mode == "split")
        self.preview_action.setChecked(mode == "preview")
        self.edit_action.setChecked(mode == "editor")
        if mode == "split":
            self.splitter.setSizes([470, 630])
        self.statusBar().showMessage(f"{mode.title()} view", 2000)

    def zoom_in(self) -> None:
        self.preview.zoomIn(1)
        self.editor.zoomIn(1)
        self._preview_zoom += 1
        self._editor_zoom += 1
        self._show_zoom()

    def zoom_out(self) -> None:
        self.preview.zoomOut(1)
        self.editor.zoomOut(1)
        self._preview_zoom -= 1
        self._editor_zoom -= 1
        self._show_zoom()

    def zoom_reset(self) -> None:
        if self._preview_zoom > 0:
            self.preview.zoomOut(self._preview_zoom)
        elif self._preview_zoom < 0:
            self.preview.zoomIn(-self._preview_zoom)
        if self._editor_zoom > 0:
            self.editor.zoomOut(self._editor_zoom)
        elif self._editor_zoom < 0:
            self.editor.zoomIn(-self._editor_zoom)
        self._preview_zoom = self._editor_zoom = 0
        self._show_zoom()

    def _show_zoom(self) -> None:
        self.statusBar().showMessage(f"Zoom: {100 + self._preview_zoom * 10}%", 2000)

    def show_find(self) -> None:
        selected = self.editor.textCursor().selectedText()
        if selected:
            self.find_input.setText(selected)
        elif self.last_find:
            self.find_input.setText(self.last_find)
        self.find_bar.show()
        self.find_input.setFocus()
        self.find_input.selectAll()

    def hide_find(self) -> None:
        self.find_bar.hide()
        self.editor.setFocus()

    def find_next(self) -> None:
        self._find(backward=False)

    def find_previous(self) -> None:
        self._find(backward=True)

    def _find(self, backward: bool) -> None:
        term = self.find_input.text() or self.last_find
        if not term:
            self.show_find()
            return
        self.last_find = term
        flags = QTextDocument.FindFlag.FindBackward if backward else QTextDocument.FindFlag(0)
        if not self.editor.find(term, flags):
            cursor = self.editor.textCursor()
            cursor.movePosition(cursor.MoveOperation.End if backward else cursor.MoveOperation.Start)
            self.editor.setTextCursor(cursor)
            if not self.editor.find(term, flags):
                self.statusBar().showMessage(f'No matches for "{term}"', 3000)

    def copy(self) -> None:
        focused = QApplication.focusWidget()
        if focused is self.preview:
            self.preview.copy()
        else:
            self.editor.copy()

    def select_all(self) -> None:
        focused = QApplication.focusWidget()
        if focused is self.preview:
            self.preview.selectAll()
        else:
            self.editor.selectAll()

    def _open_link(self, url: QUrl) -> None:
        if url.isRelative() and self.current_path:
            if not url.path() and url.hasFragment():
                self.preview.scrollToAnchor(url.fragment())
                return
            target = QUrl.fromLocalFile(str((self.current_path.parent / url.path()).resolve()))
            target.setQuery(url.query())
            target.setFragment(url.fragment())
            url = target
        QDesktopServices.openUrl(url)

    def _recent_paths(self) -> list[str]:
        value = self.settings.value("recentFiles", [])
        if isinstance(value, str):
            return [value]
        return list(value or [])

    def _add_recent(self, path: Path) -> None:
        value = str(path)
        paths = [item for item in self._recent_paths() if item != value and Path(item).exists()]
        paths.insert(0, value)
        self.settings.setValue("recentFiles", paths[:10])
        self._refresh_recent_menu()

    def _refresh_recent_menu(self) -> None:
        self.recent_menu.clear()
        paths = [item for item in self._recent_paths() if Path(item).exists()]
        if not paths:
            empty = self.recent_menu.addAction("No recent files")
            empty.setEnabled(False)
            return
        for item in paths:
            action = self.recent_menu.addAction(Path(item).name)
            action.setToolTip(item)
            action.triggered.connect(lambda _checked=False, p=item: self.open_path(Path(p)))
        self.recent_menu.addSeparator()
        self.recent_menu.addAction("Clear Recent Files", self._clear_recent)

    def _clear_recent(self) -> None:
        self.settings.remove("recentFiles")
        self._refresh_recent_menu()

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        urls = event.mimeData().urls()
        if any(Path(url.toLocalFile()).suffix.lower() in MARKDOWN_EXTENSIONS for url in urls):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.suffix.lower() in MARKDOWN_EXTENSIONS:
                self.open_path(path)
                event.acceptProposedAction()
                return

    def about(self) -> None:
        QMessageBox.about(
            self,
            f"About {APP_NAME}",
            "<b>Markdown Reader 0.1.2</b><br><br>"
            "A small native Markdown reader and editor with live preview, "
            "drag-and-drop, PDF export, search, and zoom.",
        )

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if not self._confirm_discard():
            event.ignore()
            return
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("windowState", self.saveState())
        event.accept()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("HermesTools")
    app.setWindowIcon(QIcon(str(ICON_PATH)))
    app.setStyle("Fusion")
    initial_path = sys.argv[1] if len(sys.argv) > 1 else None
    window = MarkdownWindow(initial_path)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
