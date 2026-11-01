"""An interactive projection of concept relations and their text occurrences."""

from collections import defaultdict
from dataclasses import dataclass
from html import escape
import json

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMenu,
    QPushButton, QStyle, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..core.models import Annotation, Document


@dataclass
class _Hierarchy:
    names: dict[str, str]
    children: dict[str, set[str]]
    occurrences: dict[tuple[str | None, str], list[Annotation]]
    roots: set[str]
    unassigned: list[Annotation]

    @classmethod
    def from_document(cls, doc: Document):
        names = dict(doc.concepts)
        children = defaultdict(set)
        occurrences = defaultdict(list)
        incoming = set()
        roots = set()
        unassigned = []
        for ann in doc.sorted_annotations():
            cid, parent = ann.concept_id, ann.broader_concept_id
            if not cid:
                unassigned.append(ann)
                continue
            names.setdefault(cid, f"未找到概念：{cid}")
            if not parent or parent == cid:
                roots.add(cid)
                occurrences[None, cid].append(ann)
                continue
            names.setdefault(parent, f"未找到概念：{parent}")
            children[parent].add(cid)
            incoming.add(cid)
            occurrences[parent, cid].append(ann)
        roots.update(set(names) - incoming)
        return cls(names, children, occurrences, roots, unassigned)


_PATH_ROLE = Qt.UserRole + 1


def _walk(parent):
    for index in range(parent.childCount()):
        item = parent.child(index)
        yield item
        yield from _walk(item)


class ConceptSidebar(QWidget):
    """Show broader concept -> concept -> individual annotation, without mutation."""

    concept_clicked = Signal(str)
    annotation_clicked = Signal(str)
    edit_annotation_requested = Signal(str)

    def __init__(self, parent=None, *, allow_zoom=True):
        super().__init__(parent)
        self._doc = None
        self._annotation_items = defaultdict(list)
        self._search_expansion = None
        self._viewer_dialog = None
        self._viewer_panel = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self.summary = QLabel("概念關係樹")
        self.summary.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.summary)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜尋概念或術語…")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._filter)
        layout.addWidget(self.search_edit)

        row = QHBoxLayout()
        self.expand_button = QPushButton("全部展開")
        self.collapse_button = QPushButton("全部收合")
        row.addWidget(self.expand_button)
        row.addWidget(self.collapse_button)
        self.zoom_button = QPushButton("放大檢視")
        self.zoom_button.setVisible(allow_zoom)
        self.zoom_button.clicked.connect(self._open_viewer)
        row.addWidget(self.zoom_button)
        row.addStretch()
        layout.addLayout(row)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["上位概念 → 概念 → 術語位置", "類型／筆數"])
        self.tree.setColumnWidth(0, 285)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Interactive)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.setUniformRowHeights(True)
        self.tree.setIndentation(20)
        self.tree.setAnimated(True)
        self.tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tree.setExpandsOnDoubleClick(True)
        self.tree.itemClicked.connect(self._activate_item)
        self.tree.itemDoubleClicked.connect(self._edit_item)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        layout.addWidget(self.tree, 1)
        self.expand_button.clicked.connect(self.tree.expandAll)
        self.collapse_button.clicked.connect(self.tree.collapseAll)
        self._enter_shortcut = QShortcut(QKeySequence("Return"), self.tree)
        self._enter_shortcut.activated.connect(lambda: self._activate_item(self.tree.currentItem()))
        self._edit_shortcut = QShortcut(QKeySequence("F2"), self.tree)
        self._edit_shortcut.activated.connect(lambda: self._edit_item(self.tree.currentItem()))

        self.hint = QLabel("點概念：查看相關術語　點術語：跳回原文\n雙擊術語或按 F2：修改這一筆的概念／上位概念")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        self.empty_label = QLabel("尚無概念。選取原文並標註術語後，關係會出現在這裡。")
        self.empty_label.setWordWrap(True)
        layout.addWidget(self.empty_label)
        self.refresh(None)

    def _expanded_paths(self):
        return {item.data(0, _PATH_ROLE) for item in _walk(self.tree.invisibleRootItem())
                if item.isExpanded()}

    def _restore_expansion(self, paths):
        for item in _walk(self.tree.invisibleRootItem()):
            item.setExpanded(item.data(0, _PATH_ROLE) in paths)

    def refresh(self, doc: Document | None):
        same_document = doc is not None and doc is self._doc
        expanded = self._search_expansion if self._search_expansion is not None else self._expanded_paths()
        current = self.tree.currentItem()
        selected = current.data(0, Qt.UserRole) if current else None
        self._doc = doc
        self._annotation_items.clear()
        self.tree.clear()
        self._search_expansion = None
        if not same_document:
            self.search_edit.blockSignals(True)
            self.search_edit.clear()
            self.search_edit.blockSignals(False)
        graph = _Hierarchy.from_document(doc) if doc else _Hierarchy({}, {}, {}, set(), [])
        seen = set()
        for cid in sorted(graph.roots, key=lambda key: graph.names[key].casefold()):
            self._append_concept(graph, cid, None, (), self.tree.invisibleRootItem(), seen)
        # A component consisting only of a cycle has no natural root.
        for cid in sorted(graph.names, key=lambda key: graph.names[key].casefold()):
            if cid not in seen:
                self._append_concept(graph, cid, None, (), self.tree.invisibleRootItem(), seen)
        if graph.unassigned:
            group = QTreeWidgetItem(self.tree, ["尚未設定概念", f"{len(graph.unassigned)} 筆"])
            group.setData(0, Qt.UserRole, {"kind": "group", "id": "unassigned"})
            group.setData(0, _PATH_ROLE, "unassigned")
            for ann in graph.unassigned:
                self._append_annotation(group, ann, ("unassigned",))
        if same_document:
            self._restore_expansion(expanded)
        else:
            self.tree.expandToDepth(1)
        if self.search_edit.text():
            self._filter(self.search_edit.text())
        if same_document and selected and selected["kind"] == "annotation":
            self.select_annotation(selected["id"])
        count = len(doc.annotations) if doc else 0
        self.summary.setText(f"概念關係樹　{len(graph.names)} 個概念 · {count} 筆標註")
        self.empty_label.setVisible(not graph.names and not graph.unassigned)
        if self._viewer_panel is not None:
            self._viewer_panel.refresh(doc)

    def _append_concept(self, graph, cid, parent_id, path, parent_item, seen):
        cycle = cid in path
        node_path = (*path, cid)
        count = len(graph.occurrences.get((parent_id, cid), ()))
        kind = "循環連結" if cycle else f"概念 · {count} 筆"
        item = QTreeWidgetItem(parent_item, [graph.names[cid], kind])
        item.setIcon(0, self.style().standardIcon(QStyle.SP_DirIcon))
        item.setData(0, Qt.UserRole, {"kind": "concept", "id": cid, "parent_id": parent_id})
        item.setData(0, _PATH_ROLE, json.dumps(node_path))
        description = f"概念：{graph.names[cid]}\n點選可查看相關術語。"
        if cycle:
            description += "\n此處回到已出現的概念，停止展開以顯示循環關係。"
        item.setToolTip(0, description)
        seen.add(cid)
        if not cycle:
            for child in sorted(graph.children.get(cid, ()), key=lambda key: graph.names[key].casefold()):
                self._append_concept(graph, child, cid, node_path, item, seen)
        for ann in graph.occurrences.get((parent_id, cid), ()):
            self._append_annotation(item, ann, node_path)

    def _append_annotation(self, parent, ann, path):
        term = self._doc.text[ann.start:ann.end].replace("\n", " ").replace("\r", " ")
        preview = term[:32] + ("…" if len(term) > 32 else "")
        item = QTreeWidgetItem(parent, [f"「{preview}」 [{ann.start}, {ann.end})", "術語實體"])
        item.setIcon(0, self.style().standardIcon(QStyle.SP_FileIcon))
        item.setData(0, Qt.UserRole, {"kind": "annotation", "id": ann.id})
        item.setData(0, _PATH_ROLE, json.dumps((*path, "annotation", ann.id)))
        explanation = "尚未設定"
        if ann.explanation_start is not None and ann.explanation_end is not None:
            explanation = self._doc.text[ann.explanation_start:ann.explanation_end]
        item.setToolTip(0, f"<b>術語：</b>{escape(term)}<br>"
                          f"<b>概念：</b>{escape(self._doc.concepts.get(ann.concept_id, '尚未設定'))}<br>"
                          f"<b>上位概念：</b>{escape(self._doc.concepts.get(ann.broader_concept_id, '尚未設定'))}<br>"
                          f"<b>解釋：</b>{escape(explanation[:500])}<br>雙擊可修改這一筆。")
        self._annotation_items[ann.id].append(item)

    def _filter(self, query):
        query = query.strip().casefold()
        if query and self._search_expansion is None:
            self._search_expansion = self._expanded_paths()
        for index in range(self.tree.topLevelItemCount()):
            self._filter_item(self.tree.topLevelItem(index), query)
        if not query and self._search_expansion is not None:
            self._restore_expansion(self._search_expansion)
            self._search_expansion = None

    def _filter_item(self, item, query, ancestor_matches=False):
        matches = ancestor_matches or not query or query in item.text(0).casefold()
        children_match = False
        for index in range(item.childCount()):
            children_match = self._filter_item(item.child(index), query, matches) or children_match
        visible = matches or children_match
        item.setHidden(not visible)
        if query and visible and item.childCount():
            item.setExpanded(True)
        return visible

    def select_annotation(self, annotation_id):
        candidates = self._annotation_items.get(annotation_id, ())
        if not candidates:
            self.tree.clearSelection()
            return
        current = self.tree.currentItem()
        item = current if current in candidates else candidates[0]
        if item.isHidden():
            self.search_edit.clear()
        ancestor = item.parent()
        while ancestor:
            ancestor.setExpanded(True)
            ancestor = ancestor.parent()
        self.tree.setCurrentItem(item)
        self.tree.scrollToItem(item)
        if self._viewer_panel is not None:
            self._viewer_panel.select_annotation(annotation_id)

    def _open_viewer(self):
        if self._viewer_dialog is None:
            self._viewer_dialog = QDialog(self.window())
            self._viewer_dialog.setWindowTitle("概念關係樹：上位概念、概念與術語實體")
            self._viewer_dialog.resize(760, 720)
            self._viewer_dialog.setSizeGripEnabled(True)
            layout = QVBoxLayout(self._viewer_dialog)
            self._viewer_panel = ConceptSidebar(self._viewer_dialog, allow_zoom=False)
            self._viewer_panel.concept_clicked.connect(self.concept_clicked)
            self._viewer_panel.annotation_clicked.connect(self.annotation_clicked)
            self._viewer_panel.edit_annotation_requested.connect(self.edit_annotation_requested)
            layout.addWidget(self._viewer_panel)
        self._viewer_panel.refresh(self._doc)
        self._viewer_dialog.show()
        self._viewer_dialog.raise_()
        self._viewer_dialog.activateWindow()

    def _activate_item(self, item, _column=0):
        if item is None:
            return
        entry = item.data(0, Qt.UserRole)
        if entry["kind"] == "concept":
            self.concept_clicked.emit(entry["id"])
        if entry["kind"] == "annotation":
            self.annotation_clicked.emit(entry["id"])

    def _edit_item(self, item, _column=0):
        if item is None:
            return
        entry = item.data(0, Qt.UserRole)
        if entry["kind"] == "annotation":
            self.edit_annotation_requested.emit(entry["id"])

    def _context_menu(self, position):
        item = self.tree.itemAt(position)
        if item is None:
            return
        menu = QMenu(self)
        entry = item.data(0, Qt.UserRole)
        if entry["kind"] == "annotation":
            menu.addAction("跳回原文", lambda: self._activate_item(item))
            menu.addAction("修改這一筆的概念／上位概念…", lambda: self._edit_item(item))
            menu.addSeparator()
        menu.addAction("展開這一層", lambda: item.setExpanded(True))
        menu.addAction("收合這一層", lambda: item.setExpanded(False))
        menu.exec(self.tree.viewport().mapToGlobal(position))
