"""Exercise the real window/controller, including save and reload."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from lexiarbiter.app import MainWindow
from lexiarbiter.core.config import DEFAULT_PREFERENCES, UserPreferences
from lexiarbiter.core.io import load_lexa


APP = QApplication.instance() or QApplication([])
FIXTURES = Path(__file__).parent / "fixtures"


class WindowTests(unittest.TestCase):
    def setUp(self):
        prefs = copy.deepcopy(DEFAULT_PREFERENCES)
        prefs["active_annotation_mode"] = "term_definition"
        prefs["behavior"]["auto_popup_on_selection"] = False
        prefs["behavior"]["auto_annotate_matches"] = False
        self.folder = tempfile.TemporaryDirectory()
        preferences = UserPreferences(prefs, Path(self.folder.name) / "preferences.json")
        with patch("lexiarbiter.app.UserPreferences.load", return_value=preferences):
            self.window = MainWindow()
        self.window.load_file(str(FIXTURES / "test_example.docx"))

    def tearDown(self):
        self.window.doc.dirty = False
        self.window.close()
        self.folder.cleanup()

    def select_span(self, start, end):
        editor = self.window.editor
        cursor = QTextCursor(editor.document())
        cursor.setPosition(editor._omap.to_display(start))
        cursor.setPosition(editor._omap.to_display(end), QTextCursor.KeepAnchor)
        editor.setTextCursor(cursor)

    def test_eleven_worksheet_actions_through_window_save_and_reload(self):
        reference = load_lexa(FIXTURES / "test_example.lexa")
        for expected in reference.annotations:
            self.select_span(expected.start, expected.end)
            with patch("lexiarbiter.app.ConceptSelectionDialog") as dialog:
                dialog.return_value.exec.return_value = True
                dialog.return_value.concept_name.return_value = reference.concepts[expected.concept_id]
                dialog.return_value.broader_name.return_value = reference.concepts[expected.broader_concept_id]
                self.window.apply_label("entity", "term")
            self.select_span(expected.explanation_start, expected.explanation_end)
            self.window.action_set_explanation()
        self.assertEqual(len(self.window.doc.annotations), 11)
        path = Path(self.folder.name) / "worksheet.lexa"
        with patch("lexiarbiter.app.QFileDialog.getSaveFileName", return_value=(str(path), "")):
            self.assertTrue(self.window.action_save_as())
        self.window.load_file(str(path))
        for found, expected in zip(self.window.doc.sorted_annotations(), reference.sorted_annotations()):
            self.assertEqual((found.start, found.end, found.explanation_start, found.explanation_end),
                             (expected.start, expected.end, expected.explanation_start, expected.explanation_end))
            self.assertEqual(self.window.doc.concepts[found.concept_id], reference.concepts[expected.concept_id])
            self.assertEqual(self.window.doc.concepts[found.broader_concept_id], reference.concepts[expected.broader_concept_id])

    def test_cancel_concept_dialog_keeps_document_untouched(self):
        self.select_span(43, 49)
        with patch("lexiarbiter.app.ConceptSelectionDialog") as dialog:
            dialog.return_value.exec.return_value = False
            self.window.apply_label("entity", "term")
        self.assertEqual(self.window.doc.annotations, [])
        self.assertEqual(self.window.doc.concepts, {})

    def test_default_automatic_action_records_all_occurrences(self):
        self.window.act_auto_match.setChecked(True)
        self.select_span(55, 59)
        with patch("lexiarbiter.app.ConceptSelectionDialog") as dialog:
            dialog.return_value.exec.return_value = True
            dialog.return_value.concept_name.return_value = "意定之債"
            dialog.return_value.broader_name.return_value = "債之發生原因"
            self.window.apply_label("entity", "term")
        self.assertEqual(len(self.window.doc.annotations), self.window.doc.text.count("意定之債"))
        self.assertIn("自動新增", self.window.status.currentMessage())
        ann = self.window.doc.annotations[0]
        self.window.concept_panel.concept_clicked.emit(ann.concept_id)
        self.assertEqual(self.window.active_annotation_id, self.window.doc.sorted_annotations()[1].id)

    def test_real_dialog_keyboard_shortcut_and_explanation_button(self):
        self.window.show()
        APP.processEvents()
        self.select_span(43, 49)

        def complete_dialog():
            dialog = APP.activeModalWidget()
            dialog.input_edit.setText("債之發生原因")
            QTest.mouseClick(dialog.btn_ok, Qt.LeftButton)

        QTimer.singleShot(0, complete_dialog)
        self.window.editor.setFocus()
        QTest.keyClick(self.window.editor, Qt.Key_1)
        self.assertEqual(len(self.window.doc.annotations), 1)
        self.select_span(50, 204)
        QTest.mouseClick(self.window.annotation_details.set_explanation_button, Qt.LeftButton)
        self.assertEqual(self.window.doc.annotations[0].explanation_end, 204)
        self.assertIn("債之發生原因", self.window.annotation_details.summary.toPlainText())

    def test_tree_edit_changes_parent_refreshes_branch_and_survives_save(self):
        self.window.load_file(str(FIXTURES / "test_example.lexa"))
        ann = self.window.doc.annotations[1]
        self.window.show()
        APP.processEvents()

        def complete_dialog():
            dialog = APP.activeModalWidget()
            dialog.broader_combo.setCurrentText("法定之債")
            QTest.mouseClick(dialog.btn_ok, Qt.LeftButton)

        self.window.concept_panel.zoom_button.click()
        panel = self.window.concept_panel._viewer_panel
        panel.select_annotation(ann.id)
        APP.processEvents()
        point = panel.tree.visualItemRect(panel.tree.currentItem()).center()
        QTest.mouseClick(panel.tree.viewport(), Qt.LeftButton, pos=point)
        APP.processEvents()
        point = panel.tree.visualItemRect(panel.tree.currentItem()).center()
        QTimer.singleShot(0, complete_dialog)
        QTest.mouseDClick(panel.tree.viewport(), Qt.LeftButton, pos=point)
        self.assertEqual(self.window.doc.concepts[ann.broader_concept_id], "法定之債")
        item = self.window.concept_panel.tree.currentItem()
        self.assertEqual(item.parent().parent().text(0), "法定之債")
        path = Path(self.folder.name) / "changed-parent.lexa"
        with patch("lexiarbiter.app.QFileDialog.getSaveFileName", return_value=(str(path), "")):
            self.assertTrue(self.window.action_save_as())
        self.window.load_file(str(path))
        reloaded = self.window.doc.find_annotation(ann.id)
        self.assertEqual(self.window.doc.concepts[reloaded.broader_concept_id], "法定之債")

    def test_tree_can_navigate_an_annotation_with_a_missing_concept_reference(self):
        self.window.load_file(str(FIXTURES / "test_example.lexa"))
        ann = self.window.doc.annotations[0]
        del self.window.doc.concepts[ann.concept_id]
        self.window.concept_panel.refresh(self.window.doc)
        self.window.concept_panel.concept_clicked.emit(ann.concept_id)
        self.assertEqual(self.window.active_annotation_id, ann.id)
        self.assertIn("未找到概念", self.window.status.currentMessage())


if __name__ == "__main__":
    unittest.main()
