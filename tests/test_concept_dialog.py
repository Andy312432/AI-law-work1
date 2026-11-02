"""The current-concept picker supports a single click or a new name."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from lexiarbiter.widgets.concept_panel import ConceptSelectionDialog


APP = QApplication.instance() or QApplication([])


class ConceptDialogTests(unittest.TestCase):
    def test_select_existing_concept_reuses_its_id(self):
        concepts = {"a": "法定之債", "b": "無因管理"}
        dialog = ConceptSelectionDialog(concepts, default_text="術語")
        dialog.show()
        APP.processEvents()
        item = dialog.list_widget.findItems("無因管理", Qt.MatchExactly)[0]
        QTest.mouseClick(dialog.list_widget.viewport(), Qt.LeftButton,
                         pos=dialog.list_widget.visualItemRect(item).center())
        self.assertEqual(dialog.input_edit.text(), "無因管理")
        self.assertEqual(dialog.concept_name(), "無因管理")
        self.assertNotEqual(dialog.result(), QDialog.Accepted)
        dialog.broader_combo.setCurrentText("法定之債")
        dialog.accept()
        self.assertEqual(dialog.result(), QDialog.Accepted)
        self.assertEqual(dialog.get_result(), ("b", None))
        self.assertEqual(dialog.concept_name(), "無因管理")
        self.assertEqual(dialog.broader_name(), "法定之債")
        self.assertEqual(concepts, {"a": "法定之債", "b": "無因管理"})
        dialog.close()

    def test_type_new_concept_clears_existing_selection_and_root_follows_new_name(self):
        concepts = {"a": "法定之債"}
        dialog = ConceptSelectionDialog(concepts, default_text="法定之債")
        self.assertEqual(dialog.list_widget.currentItem().text(), "法定之債")
        dialog.input_edit.setText("  新概念  ")
        self.assertEqual(dialog.list_widget.selectedItems(), [])
        dialog.accept()
        self.assertEqual(dialog.get_result(), (None, "新概念"))
        self.assertEqual(dialog.concept_name(), "新概念")
        self.assertEqual(dialog.broader_name(), "新概念")
        self.assertEqual(concepts, {"a": "法定之債"})
        dialog.close()

    def test_blank_concept_does_not_accept_dialog(self):
        dialog = ConceptSelectionDialog({"a": "法定之債"})
        dialog.input_edit.setText(" ")
        with patch("lexiarbiter.widgets.concept_panel.QMessageBox.warning"):
            dialog.accept()
        self.assertNotEqual(dialog.result(), QDialog.Accepted)
        dialog.close()

    def test_entity_type_picker_preserves_ids_and_allows_custom_types(self):
        dialog = ConceptSelectionDialog(
            {"a": "無因管理"}, default_text="無因管理",
            entity_types=[("term", "專業術語"), ("reason", "原因"), ("custom", "自訂類型")],
            entity_type_id="reason",
        )
        self.assertEqual(dialog.selected_entity_type(), "reason")
        dialog.entity_type_combo.setCurrentIndex(dialog.entity_type_combo.findData("custom"))
        dialog.accept()
        self.assertEqual(dialog.result(), QDialog.Accepted)
        self.assertEqual(dialog.selected_entity_type(), "custom")
        self.assertEqual(dialog.concept_name(), "無因管理")
        dialog.close()
