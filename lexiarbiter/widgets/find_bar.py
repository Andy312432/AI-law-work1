"""A compact search bar for the document's rendered text."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QWidget


class FindBar(QWidget):
    def __init__(self, editor, parent=None):
        super().__init__(parent)
        self._editor = editor
        self._matches = []
        self._index = -1
        layout = QHBoxLayout(self)
        layout.addWidget(QLabel("搜尋原文"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("輸入搜尋文字…")
        self.search_edit.setClearButtonEnabled(True)
        layout.addWidget(self.search_edit, 1)
        self.result_label = QLabel("輸入搜尋文字")
        layout.addWidget(self.result_label)
        self.previous_button = QPushButton("上一筆")
        self.previous_button.setToolTip("Shift+Enter")
        self.previous_button.clicked.connect(lambda: self._move(-1))
        layout.addWidget(self.previous_button)
        self.next_button = QPushButton("下一筆")
        self.next_button.setToolTip("Enter")
        self.next_button.clicked.connect(lambda: self._move(1))
        layout.addWidget(self.next_button)
        self.close_button = QPushButton("關閉")
        self.close_button.setToolTip("Esc")
        self.close_button.clicked.connect(self.close_search)
        layout.addWidget(self.close_button)
        self.search_edit.textChanged.connect(self.refresh)
        self.search_edit.returnPressed.connect(lambda: self._move(1))
        for key, callback in (("Escape", self.close_search),
                              ("Shift+Return", lambda: self._move(-1)),
                              ("Shift+Enter", lambda: self._move(-1))):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(callback)
        self._update_result_label()
        self.hide()

    def open_search(self):
        selected = self._editor.textCursor().selectedText()
        if selected and not any(ch in selected for ch in "\n\r\u2028\u2029"):
            self.search_edit.setText(selected)
        self.show()
        self.refresh()
        self.search_edit.setFocus()
        self.search_edit.selectAll()

    def close_search(self):
        self.hide()
        self._editor.setFocus()

    def refresh(self):
        self._matches = []
        self._index = -1
        query = self.search_edit.text()
        if not self.isHidden() and query:
            document = self._editor.document()
            cursor = document.find(query)
            while not cursor.isNull():
                self._matches.append(cursor)
                cursor = document.find(query, cursor)
        if self._matches:
            position = self._editor.textCursor().selectionStart()
            self._index = next((index for index, cursor in enumerate(self._matches)
                                if cursor.selectionStart() >= position), 0)
            self._select_match()
        elif not self.isHidden():
            cursor = self._editor.textCursor()
            cursor.clearSelection()
            self._editor.setTextCursor(cursor)
        self._update_result_label()

    def _move(self, direction):
        if self._matches:
            self._index = (self._index + direction) % len(self._matches)
            self._select_match()
            self._update_result_label()

    def _select_match(self):
        self._editor.setTextCursor(self._matches[self._index])
        self._editor.ensureCursorVisible()

    def _update_result_label(self):
        self.previous_button.setEnabled(bool(self._matches))
        self.next_button.setEnabled(bool(self._matches))
        if self._matches:
            self.result_label.setText(f"{self._index + 1} / {len(self._matches)}")
            return
        self.result_label.setText("找不到符合文字" if self.search_edit.text() else "輸入搜尋文字")
