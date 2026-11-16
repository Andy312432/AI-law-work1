"""Searching rendered text must preserve annotation data and coordinates."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from lexiarbiter.core.config import UserPreferences, list_annotation_modes
from lexiarbiter.core.models import Annotation, Document
from lexiarbiter.widgets.editor import AnnotationEditor
from lexiarbiter.widgets.find_bar import FindBar


APP = QApplication.instance() or QApplication([])


class FindBarTests(unittest.TestCase):
    def setUp(self):
        self.host = QWidget()
        layout = QVBoxLayout(self.host)
        self.editor = AnnotationEditor()
        self.bar = FindBar(self.editor)
        layout.addWidget(self.bar)
        layout.addWidget(self.editor)
        self.doc = Document("甲😀\r\n無因管理、無因管理、ABC abc", annotations=[
            Annotation(4, 8, {"entity": "term"}),
        ])
        self.editor.attach(self.doc, list_annotation_modes()[0], UserPreferences.load())
        self.host.show()
        APP.processEvents()

    def tearDown(self):
        self.host.close()

    def test_search_selects_unicode_matches_and_wraps_in_both_directions(self):
        self.bar.open_search()
        self.bar.search_edit.setText("無因管理")
        self.assertEqual(self.editor.storage_selection(), (4, 8))
        self.assertEqual(self.bar.result_label.text(), "1 / 2")
        QTest.keyClick(self.bar.search_edit, Qt.Key_Return)
        self.assertEqual(self.editor.storage_selection(), (9, 13))
        self.assertEqual(self.bar.result_label.text(), "2 / 2")
        QTest.keyClick(self.bar.search_edit, Qt.Key_Return)
        self.assertEqual(self.editor.storage_selection(), (4, 8))
        QTest.keyClick(self.bar.search_edit, Qt.Key_Return, Qt.ShiftModifier)
        self.assertEqual(self.editor.storage_selection(), (9, 13))
        self.assertEqual(self.bar.result_label.text(), "2 / 2")
        self.assertEqual([ann.to_dict() for ann in self.doc.annotations],
                         [Annotation(4, 8, {"entity": "term"}, id=self.doc.annotations[0].id).to_dict()])
        self.assertFalse(self.doc.dirty)

    def test_search_is_case_insensitive_and_treats_punctuation_literally(self):
        self.bar.open_search()
        self.bar.search_edit.setText("abc")
        self.assertEqual(self.editor.textCursor().selectedText(), "ABC")
        self.assertEqual(self.bar.result_label.text(), "1 / 2")
        self.bar.next_button.click()
        self.assertEqual(self.editor.textCursor().selectedText(), "abc")
        self.bar.search_edit.setText(".*")
        self.assertEqual(self.bar.result_label.text(), "找不到符合文字")
        self.assertFalse(self.editor.textCursor().hasSelection())
        self.assertFalse(self.bar.next_button.isEnabled())
        self.assertFalse(self.bar.previous_button.isEnabled())
        self.bar.search_edit.clear()
        self.assertEqual(self.bar.result_label.text(), "輸入搜尋文字")

    def test_open_uses_selected_text_and_escape_returns_focus_to_editor(self):
        cursor = self.editor.document().find("無因管理")
        self.editor.setTextCursor(cursor)
        self.bar.open_search()
        APP.processEvents()
        self.assertEqual(self.bar.search_edit.text(), "無因管理")
        self.assertTrue(self.bar.search_edit.hasFocus())
        self.assertEqual(self.bar.search_edit.selectedText(), "無因管理")
        QTest.keyClick(self.bar.search_edit, Qt.Key_Escape)
        self.assertTrue(self.bar.isHidden())
        self.assertTrue(self.editor.hasFocus())
        self.assertEqual(self.editor.storage_selection(), (4, 8))

    def test_refresh_replaces_results_when_another_document_is_loaded(self):
        self.bar.open_search()
        self.bar.search_edit.setText("無因管理")
        replacement = Document("只有一筆無因管理")
        self.editor.attach(replacement, list_annotation_modes()[0], UserPreferences.load())
        self.bar.refresh()
        self.assertEqual(self.bar.result_label.text(), "1 / 1")
        self.assertEqual(self.editor.textCursor().selectedText(), "無因管理")
        self.assertEqual(self.editor.storage_selection(), (4, 8))


if __name__ == "__main__":
    unittest.main()
