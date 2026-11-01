import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from lexiarbiter.core.config import UserPreferences, list_annotation_modes
from lexiarbiter.core.models import Annotation, Document
from lexiarbiter.widgets.editor import AnnotationEditor, _OffsetMap
from lexiarbiter.widgets.concept_panel import ConceptSidebar


APP = QApplication.instance() or QApplication([])


class EditorTests(unittest.TestCase):
    def test_raw_offsets_handle_crlf_hidden_breaks_and_emoji(self):
        mapping = _OffsetMap("甲\r\n😀<br />乙<br>丙")
        self.assertEqual(mapping.display_text, "甲\n😀乙丙")
        self.assertEqual(mapping.to_storage(mapping.to_display(10)), 10)
        self.assertEqual(mapping.to_storage(mapping.to_display(4), end=True), 4)
        self.assertEqual(mapping.to_storage(mapping.to_display(12), end=True), 11)

    def test_click_annotation_emits_id_and_highlights_its_explanation(self):
        ann = Annotation(0, 2, {"entity": "term"}, concept_id="c", broader_concept_id="c",
                         explanation_start=3, explanation_end=5)
        doc = Document("術語，解釋", [ann], concepts={"c": "術語"})
        editor = AnnotationEditor()
        editor.attach(doc, list_annotation_modes()[0], UserPreferences.load())
        editor.show()
        APP.processEvents()
        spy = QSignalSpy(editor.annotation_clicked)
        cursor = QTextCursor(editor.document())
        cursor.setPosition(1)
        QTest.mouseClick(editor.viewport(), Qt.LeftButton, pos=editor.cursorRect(cursor).center())
        self.assertEqual(spy.count(), 1)
        self.assertEqual(spy.at(0)[0], ann.id)
        editor.set_active_annotation(ann.id)
        spans = [(s.cursor.selectionStart(), s.cursor.selectionEnd()) for s in editor.extraSelections()]
        self.assertIn((3, 5), spans)
        self.assertIn("術語", editor.annotation_tooltip(ann))
        editor.close()

    def test_sidebar_emits_concept_id(self):
        panel = ConceptSidebar()
        panel.refresh(Document("", concepts={"c": "概念"}))
        spy = QSignalSpy(panel.concept_clicked)
        item = panel.tree.topLevelItem(0)
        panel.tree.itemClicked.emit(item, 0)
        self.assertEqual(spy.count(), 1)
        self.assertEqual(spy.at(0)[0], "c")
        panel.close()


if __name__ == "__main__":
    unittest.main()
