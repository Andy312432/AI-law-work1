"""The hierarchy must faithfully project annotation-level relationships."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import unittest

from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from lexiarbiter.core.io import load_lexa
from lexiarbiter.core.models import Annotation, Document
from lexiarbiter.widgets.concept_panel import ConceptSidebar


APP = QApplication.instance() or QApplication([])
FIXTURES = Path(__file__).parent / "fixtures"


def descendants(item):
    for index in range(item.childCount()):
        child = item.child(index)
        yield child
        yield from descendants(child)


def all_items(panel):
    return list(descendants(panel.tree.invisibleRootItem()))


def concept_child(parent, name):
    return next(parent.child(i) for i in range(parent.childCount())
                if parent.child(i).text(0) == name)


class ConceptTreeTests(unittest.TestCase):
    def setUp(self):
        self.doc = load_lexa(FIXTURES / "test_example.lexa")
        self.panel = ConceptSidebar()
        self.panel.refresh(self.doc)

    def tearDown(self):
        self.panel.close()

    def test_reference_shows_parent_concepts_and_all_eleven_occurrences(self):
        self.assertEqual(self.panel.tree.topLevelItemCount(), 1)
        root = self.panel.tree.topLevelItem(0)
        self.assertEqual(root.text(0), "債之發生原因")
        legal = concept_child(root, "法定之債")
        for name in ("無因管理", "不當得利", "侵權行為"):
            node = concept_child(legal, name)
            self.assertEqual(node.childCount(), 2)
        actual = {item.data(0, Qt.UserRole)["id"] for item in all_items(self.panel)
                  if item.data(0, Qt.UserRole)["kind"] == "annotation"}
        self.assertEqual(actual, {ann.id for ann in self.doc.annotations})
        self.assertFalse(self.doc.dirty)

    def test_single_click_occurrence_navigates_and_double_click_requests_edit(self):
        self.panel.resize(640, 650)
        self.panel.show()
        self.panel.tree.expandAll()
        APP.processEvents()
        item = next(item for item in all_items(self.panel)
                    if item.data(0, Qt.UserRole)["kind"] == "annotation")
        self.panel.tree.scrollToItem(item)
        navigation = QSignalSpy(self.panel.annotation_clicked)
        editing = QSignalSpy(self.panel.edit_annotation_requested)
        QTest.mouseClick(self.panel.tree.viewport(), Qt.LeftButton,
                         pos=self.panel.tree.visualItemRect(item).center())
        self.assertEqual(navigation.at(0)[0], item.data(0, Qt.UserRole)["id"])
        self.panel.tree.itemDoubleClicked.emit(item, 0)
        self.assertEqual(editing.at(0)[0], item.data(0, Qt.UserRole)["id"])

    def test_search_preserves_ancestors_and_restores_collapsed_branches(self):
        root = self.panel.tree.topLevelItem(0)
        legal = concept_child(root, "法定之債")
        legal.setExpanded(False)
        self.panel.search_edit.setText("不當得利")
        self.assertFalse(root.isHidden())
        self.assertFalse(legal.isHidden())
        self.assertFalse(concept_child(legal, "不當得利").isHidden())
        self.assertTrue(concept_child(root, "意定之債").isHidden())
        self.panel.search_edit.clear()
        self.assertFalse(legal.isExpanded())
        self.assertFalse(concept_child(root, "意定之債").isHidden())

    def test_same_concept_keeps_occurrences_under_their_actual_parents(self):
        doc = Document("甲乙", concepts={"a": "上位甲", "b": "上位乙", "c": "共用概念"},
                       annotations=[Annotation(0, 1, concept_id="c", broader_concept_id="a"),
                                    Annotation(1, 2, concept_id="c", broader_concept_id="b")])
        self.panel.refresh(doc)
        self.assertEqual(self.panel.tree.topLevelItemCount(), 2)
        for ann in doc.annotations:
            parent = concept_child(self.panel.tree.invisibleRootItem(), doc.concepts[ann.broader_concept_id])
            shared = concept_child(parent, "共用概念")
            self.assertEqual(shared.childCount(), 1)
            self.assertEqual(shared.text(1), "概念 · 1 筆")
            self.assertEqual(shared.child(0).data(0, Qt.UserRole)["id"], ann.id)

    def test_cycles_missing_references_and_unassigned_annotations_remain_accessible(self):
        doc = Document("甲乙丙丁", concepts={"a": "甲", "b": "乙"}, annotations=[
            Annotation(0, 1, concept_id="a", broader_concept_id="b"),
            Annotation(1, 2, concept_id="b", broader_concept_id="a"),
            Annotation(2, 3, concept_id="missing", broader_concept_id="missing-parent"),
            Annotation(3, 4),
        ])
        before = [a.to_dict() for a in doc.annotations]
        self.panel.refresh(doc)
        items = all_items(self.panel)
        self.assertLess(len(items), 20)
        actual = {item.data(0, Qt.UserRole)["id"] for item in items
                  if item.data(0, Qt.UserRole)["kind"] == "annotation"}
        self.assertEqual(actual, {a.id for a in doc.annotations})
        self.assertTrue(any("循環" in item.text(1) for item in items))
        self.assertEqual([a.to_dict() for a in doc.annotations], before)
        self.assertEqual(doc.concepts, {"a": "甲", "b": "乙"})

    def test_refresh_keeps_expansion_and_selection_sync_does_not_emit_navigation(self):
        self.panel.tree.collapseAll()
        self.panel.refresh(self.doc)
        self.assertFalse(self.panel.tree.topLevelItem(0).isExpanded())
        spy = QSignalSpy(self.panel.annotation_clicked)
        target = self.doc.annotations[-1]
        self.panel.select_annotation(target.id)
        self.assertEqual(self.panel.tree.currentItem().data(0, Qt.UserRole)["id"], target.id)
        self.assertEqual(spy.count(), 0)
        self.assertTrue(self.panel.tree.topLevelItem(0).isExpanded())

    def test_enlarged_view_forwards_navigation_and_refreshes_after_edits(self):
        self.panel.zoom_button.click()
        viewer = self.panel._viewer_panel
        spy = QSignalSpy(self.panel.annotation_clicked)
        viewer.select_annotation(self.doc.annotations[0].id)
        viewer.tree.itemClicked.emit(viewer.tree.currentItem(), 0)
        self.assertEqual(spy.at(0)[0], self.doc.annotations[0].id)
        self.doc.concepts[self.doc.annotations[0].concept_id] = "修改後的名稱"
        self.panel.refresh(self.doc)
        self.assertEqual(viewer.tree.topLevelItem(0).text(0), "修改後的名稱")
        self.panel._viewer_dialog.close()


if __name__ == "__main__":
    unittest.main()
