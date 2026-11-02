"""Undo must restore the entire edit, including references and saved state."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from lexiarbiter.app import MainWindow
from lexiarbiter.core.annotations import concept_deletion_impact, remove_concept
from lexiarbiter.core.config import DEFAULT_PREFERENCES, UserPreferences
from lexiarbiter.core.models import Annotation, Document


APP = QApplication.instance() or QApplication([])
FIXTURES = Path(__file__).parent / "fixtures"


def contents(doc):
    return (dict(doc.concepts), [ann.to_dict() for ann in doc.annotations])


class ConceptDeletionTests(unittest.TestCase):
    def test_delete_parent_preserves_children_and_repairs_broader_references(self):
        doc = Document("甲乙丙", concepts={"a": "甲", "b": "乙", "c": "丙"}, annotations=[
            Annotation(0, 1, concept_id="a", broader_concept_id="a"),
            Annotation(1, 2, concept_id="b", broader_concept_id="a"),
            Annotation(2, 3, concept_id="c", broader_concept_id="b"),
        ])
        impact = concept_deletion_impact(doc, "a")
        self.assertEqual((impact.removed_annotations, impact.reparented_annotations), (1, 1))
        remove_concept(doc, "a")
        self.assertEqual(doc.concepts, {"b": "乙", "c": "丙"})
        self.assertEqual([(a.concept_id, a.broader_concept_id) for a in doc.annotations], [("b", "b"), ("c", "b")])
        self.assertTrue(doc.dirty)

    def test_unused_concept_can_be_deleted_and_missing_id_changes_nothing(self):
        doc = Document("", concepts={"unused": "未使用概念"})
        remove_concept(doc, "unused")
        self.assertEqual(doc.concepts, {})
        before = contents(doc)
        with self.assertRaises(ValueError):
            remove_concept(doc, "missing")
        self.assertEqual(contents(doc), before)


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        prefs = copy.deepcopy(DEFAULT_PREFERENCES)
        prefs["active_annotation_mode"] = "term_definition"
        prefs["behavior"].update(auto_popup_on_selection=False, auto_annotate_matches=False)
        preferences = UserPreferences(prefs, Path(self.folder.name) / "prefs.json")
        with patch("lexiarbiter.app.UserPreferences.load", return_value=preferences):
            self.window = MainWindow()
        self.window.load_file(str(FIXTURES / "test_example.lexa"))

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

    def delete(self, concept_id):
        with patch("lexiarbiter.app.QMessageBox.question", return_value=QMessageBox.Yes):
            self.window.action_delete_concept(concept_id)

    def test_delete_concept_and_all_related_changes_are_one_undoable_edit(self):
        before = contents(self.window.doc)
        root = self.window.doc.annotations[0].concept_id
        self.delete(root)
        after = contents(self.window.doc)
        self.assertNotIn(root, self.window.doc.concepts)
        self.assertFalse(any(a.concept_id == root or a.broader_concept_id == root for a in self.window.doc.annotations))
        self.assertEqual(self.window.undo_stack.count(), 1)
        self.assertTrue(self.window.doc.dirty)
        self.window.undo_stack.undo()
        self.assertEqual(contents(self.window.doc), before)
        self.assertFalse(self.window.doc.dirty)
        self.window.undo_stack.redo()
        self.assertEqual(contents(self.window.doc), after)

    def test_cancel_deletion_does_not_change_data_or_history(self):
        before = contents(self.window.doc)
        with patch("lexiarbiter.app.QMessageBox.question", return_value=QMessageBox.Cancel):
            self.window.action_delete_concept(self.window.doc.annotations[0].concept_id)
        self.assertEqual(contents(self.window.doc), before)
        self.assertFalse(self.window.undo_stack.canUndo())
        self.assertFalse(self.window.doc.dirty)

    def test_ctrl_z_and_ctrl_y_work_in_the_editor(self):
        before = contents(self.window.doc)
        root = self.window.doc.annotations[0].concept_id
        self.delete(root)
        self.window.show()
        self.window.activateWindow()
        self.window.editor.setFocus()
        APP.processEvents()
        QTest.keyClick(self.window.editor, Qt.Key_Z, Qt.ControlModifier)
        self.assertEqual(contents(self.window.doc), before)
        QTest.keyClick(self.window.editor, Qt.Key_Y, Qt.ControlModifier)
        self.assertNotIn(root, self.window.doc.concepts)

    def test_delete_menu_and_ctrl_z_work_in_enlarged_tree(self):
        before = contents(self.window.doc)
        self.window.show()
        self.window.concept_panel.zoom_button.click()
        panel = self.window.concept_panel._viewer_panel
        root = panel.tree.topLevelItem(0)
        menu = panel._menu_for_item(root)
        deletion = next(action for action in menu.actions() if action.data() == "delete_concept")
        with patch("lexiarbiter.app.QMessageBox.question", return_value=QMessageBox.Yes):
            deletion.trigger()
        self.assertNotEqual(contents(self.window.doc), before)
        panel.tree.setFocus()
        self.window.concept_panel._viewer_dialog.activateWindow()
        APP.processEvents()
        QTest.keyClick(panel.tree, Qt.Key_Z, Qt.ControlModifier)
        self.assertEqual(contents(self.window.doc), before)
        self.assertEqual(panel.tree.topLevelItem(0).text(0), "債之發生原因")

    def test_automatic_annotations_and_new_concepts_undo_and_redo_as_a_batch(self):
        self.window.load_file(str(FIXTURES / "test_example.docx"))
        self.window.act_auto_match.setChecked(True)
        before = contents(self.window.doc)
        self.select_span(55, 59)
        with patch("lexiarbiter.app.ConceptSelectionDialog") as dialog:
            dialog.return_value.exec.return_value = True
            dialog.return_value.selected_entity_type.return_value = "term"
            dialog.return_value.concept_name.return_value = "意定之債"
            dialog.return_value.broader_name.return_value = "債之發生原因"
            self.window.apply_label("entity", "term")
        after = contents(self.window.doc)
        self.assertGreater(len(self.window.doc.annotations), 1)
        self.assertEqual(self.window.undo_stack.count(), 1)
        self.window.undo_stack.undo()
        self.assertEqual(contents(self.window.doc), before)
        self.assertTrue(self.window.doc.dirty)  # Imported Word has never been saved.
        self.assertEqual(self.window.editor.extraSelections(), [])
        self.window.undo_stack.redo()
        self.assertEqual(contents(self.window.doc), after)

    def test_explanation_changes_and_use_self_can_both_be_undone(self):
        ann = self.window.doc.annotations[0]
        original = (ann.explanation_start, ann.explanation_end)
        self.window._select_annotation(ann.id)
        self.select_span(55, 59)
        self.window.action_set_explanation()
        self.window.action_use_term_explanation()
        self.window.undo_stack.undo()
        current = self.window.doc.find_annotation(ann.id)
        self.assertEqual((current.explanation_start, current.explanation_end), (55, 59))
        self.window.undo_stack.undo()
        current = self.window.doc.find_annotation(ann.id)
        self.assertEqual((current.explanation_start, current.explanation_end), original)
        self.assertFalse(self.window.doc.dirty)

    def test_edit_concept_and_parent_undo_removes_new_concept(self):
        before = contents(self.window.doc)
        ann = self.window.doc.annotations[0]
        self.window._select_annotation(ann.id)
        with patch("lexiarbiter.app.ConceptSelectionDialog") as dialog:
            dialog.return_value.exec.return_value = True
            dialog.return_value.selected_entity_type.return_value = "term"
            dialog.return_value.concept_name.return_value = "新概念"
            dialog.return_value.broader_name.return_value = "新上位概念"
            self.window.action_edit_concepts()
        self.assertIn("新概念", self.window.doc.concepts.values())
        self.window.undo_stack.undo()
        self.assertEqual(contents(self.window.doc), before)

    def test_annotation_deletion_and_group_clearing_can_be_undone(self):
        for operation in (self.window.action_remove_annotation_at_cursor,
                          lambda: self.window.clear_group_in_selection("entity")):
            with self.subTest(operation=operation):
                self.window.load_file(str(FIXTURES / "test_example.lexa"))
                before = contents(self.window.doc)
                self.select_span(43, 49)
                operation()
                self.assertEqual(len(self.window.doc.annotations), 10)
                self.window.undo_stack.undo()
                self.assertEqual(contents(self.window.doc), before)

    def test_save_marks_clean_and_undo_keeps_current_save_path(self):
        self.delete(self.window.doc.annotations[0].concept_id)
        path = Path(self.folder.name) / "deleted.lexa"
        with patch("lexiarbiter.app.QFileDialog.getSaveFileName", return_value=(str(path), "")):
            self.assertTrue(self.window.action_save_as())
        self.assertFalse(self.window.doc.dirty)
        self.window.undo_stack.undo()
        self.assertTrue(self.window.doc.dirty)
        self.assertEqual(self.window.doc.file_path, str(path))
        self.window.undo_stack.redo()
        self.assertFalse(self.window.doc.dirty)

    def test_loading_another_file_clears_history_and_new_edit_discards_redo(self):
        self.delete(self.window.doc.annotations[0].concept_id)
        self.window.undo_stack.undo()
        self.delete(self.window.doc.annotations[-1].concept_id)
        self.assertFalse(self.window.undo_stack.canRedo())
        self.window.load_file(str(FIXTURES / "test_example.docx"))
        self.assertFalse(self.window.undo_stack.canUndo())
        self.assertFalse(self.window.undo_stack.canRedo())
        self.assertTrue(self.window.doc.dirty)

    def test_reapplying_unchanged_concept_selects_target_without_creating_history(self):
        first, second = self.window.doc.annotations[:2]
        self.window._select_annotation(second.id)
        self.select_span(first.start, first.end)
        with patch("lexiarbiter.app.ConceptSelectionDialog") as dialog:
            dialog.return_value.exec.return_value = True
            dialog.return_value.selected_entity_type.return_value = "term"
            dialog.return_value.concept_name.return_value = self.window.doc.concepts[first.concept_id]
            dialog.return_value.broader_name.return_value = self.window.doc.concepts[first.broader_concept_id]
            self.window.apply_label("entity", "term")
        self.assertEqual(self.window.annotation_details.annotations.currentData(), first.id)
        self.assertFalse(self.window.undo_stack.canUndo())
        self.assertFalse(self.window.doc.dirty)

    def test_search_text_undo_does_not_undo_document_edits(self):
        self.delete(self.window.doc.annotations[0].concept_id)
        after = contents(self.window.doc)
        self.window.show()
        self.window.concept_panel.zoom_button.click()
        panel = self.window.concept_panel._viewer_panel
        panel.search_edit.setFocus()
        APP.processEvents()
        QTest.keyClicks(panel.search_edit, "abc")
        QTest.keyClick(panel.search_edit, Qt.Key_Z, Qt.ControlModifier)
        self.assertNotEqual(panel.search_edit.text(), "abc")
        self.assertEqual(contents(self.window.doc), after)
        self.assertEqual(self.window.undo_stack.index(), 1)


if __name__ == "__main__":
    unittest.main()
