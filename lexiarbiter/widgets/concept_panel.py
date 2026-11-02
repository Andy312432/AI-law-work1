"""Concept management UI components."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QGroupBox, QLineEdit, QListWidget,
    QLabel, QWidget, QMessageBox, QComboBox, QPlainTextEdit
)

from .concept_tree import ConceptSidebar

class ConceptSelectionDialog(QDialog):
    """彈出視窗：讓使用者從現有概念挑選，或輸入新概念。"""
    def __init__(self, concepts: dict[str, str], default_text: str = "", parent=None,
                 broader_name: str = "", entity_types: list[tuple[str, str]] | None = None,
                 entity_type_id: str | None = None):
        super().__init__(parent)
        self.setWindowTitle("設定標註")
        self.resize(460, 500)
        
        layout = QVBoxLayout(self)
        self.entity_type_combo = None
        if entity_types:
            type_row = QHBoxLayout()
            type_row.addWidget(QLabel("實體類型"))
            self.entity_type_combo = QComboBox()
            for type_id, name in entity_types:
                self.entity_type_combo.addItem(name, type_id)
            if entity_type_id is not None:
                index = self.entity_type_combo.findData(entity_type_id)
                if index < 0:
                    self.entity_type_combo.addItem(f"未定義類型：{entity_type_id}", entity_type_id)
                    index = self.entity_type_combo.count() - 1
                self.entity_type_combo.setCurrentIndex(index)
            type_row.addWidget(self.entity_type_combo, 1)
            layout.addLayout(type_row)
        
        self._concept_map = {name: cid for cid, name in concepts.items()}
        current_group = QGroupBox("目前概念")
        current_layout = QVBoxLayout(current_group)
        current_description = QLabel("這段文字代表的概念，例如「無因管理」。")
        current_description.setWordWrap(True)
        current_layout.addWidget(current_description)
        self.input_edit = QLineEdit(default_text)
        self.input_edit.setPlaceholderText("選擇既有概念，或輸入新名稱")
        self.input_edit.selectAll()
        current_layout.addWidget(self.input_edit)
        self.list_widget = QListWidget()
        self.list_widget.addItems(sorted(self._concept_map))
        current_layout.addWidget(self.list_widget)
        self.list_widget.currentItemChanged.connect(self._select_existing_concept)
        self.list_widget.itemClicked.connect(self._select_existing_concept)
        self.input_edit.textChanged.connect(self._sync_existing_selection)
        self._sync_existing_selection(default_text)
        layout.addWidget(current_group, 1)

        broader_group = QGroupBox("上位概念")
        broader_layout = QVBoxLayout(broader_group)
        broader_description = QLabel("目前概念所屬的較大類別，例如「法定之債」。")
        broader_description.setWordWrap(True)
        broader_layout.addWidget(broader_description)
        self.broader_combo = QComboBox()
        self.broader_combo.setEditable(True)
        self.broader_combo.addItem("（同本概念，最上層）", None)
        for name in sorted(set(concepts.values())):
            self.broader_combo.addItem(name, name)
        if broader_name and broader_name != default_text:
            self.broader_combo.setCurrentText(broader_name)
        broader_layout.addWidget(self.broader_combo)
        layout.addWidget(broader_group)

        # 按鈕區
        btn_layout = QHBoxLayout()
        self.btn_ok = QPushButton("確定")
        self.btn_ok.setStyleSheet("background-color: #2196F3; color: white; font-weight: bold; padding: 6px; border-radius: 4px;")
        self.btn_ok.clicked.connect(self.accept)
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setStyleSheet("background-color: #546E7A; color: white; padding: 6px; border-radius: 4px;")
        self.btn_cancel.clicked.connect(self.reject)

        # 將按鈕推到對話框的右下角
        btn_layout.addStretch()
        
        # 將 OK 放在前面 (左邊)，Cancel 放在後面 (右邊)
        btn_layout.addWidget(self.btn_ok)
        btn_layout.addWidget(self.btn_cancel)
        layout.addLayout(btn_layout)

        self.btn_ok.setDefault(True)
        self.input_edit.setFocus()

    def _select_existing_concept(self, item, _previous=None):
        if item is not None:
            self.input_edit.setText(item.text())

    def _sync_existing_selection(self, text):
        matches = self.list_widget.findItems(text.strip(), Qt.MatchExactly)
        blocked = self.list_widget.blockSignals(True)
        self.list_widget.setCurrentItem(matches[0] if matches else None)
        if not matches:
            self.list_widget.clearSelection()
        self.list_widget.blockSignals(blocked)

    def accept(self):
        if not self.concept_name() or not self.broader_combo.currentText().strip():
            QMessageBox.warning(self, "欄位未完成", "概念與上位概念不能留空。")
            return
        super().accept()

    def concept_name(self) -> str:
        return self.input_edit.text().strip()

    def selected_entity_type(self) -> str | None:
        return self.entity_type_combo.currentData() if self.entity_type_combo is not None else None

    def broader_name(self) -> str:
        text = self.broader_combo.currentText().strip()
        if text == self.broader_combo.itemText(0):
            return self.concept_name()
        return text

    def get_result(self) -> tuple[str | None, str | None]:
        """回傳 (已存在的 ID, 新增的名稱)。若輸入框為空則回傳 (None, None)。"""
        text = self.concept_name()
        if not text:
            return None, None
        if text in self._concept_map:
            return self._concept_map[text], None
        return None, text


class AnnotationDetails(QWidget):
    """Persistent target while the user selects an explanation elsewhere."""

    explanation_requested = Signal()
    self_explanation_requested = Signal()
    concepts_requested = Signal()
    annotation_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        title = QLabel("術語與解釋")
        title.setStyleSheet("font-weight: bold;")
        layout.addWidget(title)
        self.annotations = QComboBox()
        self.annotations.setPlaceholderText("選擇術語")
        self.annotations.activated.connect(self._on_activated)
        layout.addWidget(self.annotations)
        self.summary = QPlainTextEdit()
        self.summary.setReadOnly(True)
        self.summary.setMaximumHeight(155)
        layout.addWidget(self.summary)
        self.set_explanation_button = QPushButton("設定解釋")
        self.set_explanation_button.clicked.connect(self.explanation_requested)
        layout.addWidget(self.set_explanation_button)
        row = QHBoxLayout()
        self.use_self_button = QPushButton("改為用術語本身解釋")
        self.use_self_button.clicked.connect(self.self_explanation_requested)
        self.edit_concepts_button = QPushButton("修改標註")
        self.edit_concepts_button.clicked.connect(self.concepts_requested)
        row.addWidget(self.use_self_button)
        row.addWidget(self.edit_concepts_button)
        layout.addLayout(row)
        self.refresh(None)

    def refresh(self, doc, annotation_id=None, mode=None):
        self.annotations.blockSignals(True)
        self.annotations.clear()
        if doc:
            for ann in doc.sorted_annotations():
                term = doc.text[ann.start:ann.end].replace("\n", " ")
                self.annotations.addItem(f"{ann.start}-{ann.end}　{term[:40]}", ann.id)
        index = self.annotations.findData(annotation_id)
        self.annotations.setCurrentIndex(index)
        self.annotations.blockSignals(False)
        ann = doc.find_annotation(annotation_id) if doc else None
        for button in (self.set_explanation_button, self.use_self_button, self.edit_concepts_button):
            button.setEnabled(ann is not None)
        if ann is None:
            self.summary.setPlainText("尚未選取術語")
            return
        explanation = "尚未設定"
        if ann.explanation_start is not None and ann.explanation_end is not None:
            explanation = doc.text[ann.explanation_start:ann.explanation_end]
        type_names = []
        for group_id, label_id in ann.labels.items():
            label = mode.label(group_id, label_id) if mode else None
            type_names.append(label.name if label else label_id)
        self.summary.setPlainText(
            f"術語：{doc.text[ann.start:ann.end]}\n"
            f"實體類型：{'、'.join(type_names) or '尚未設定'}\n"
            f"概念：{doc.concepts.get(ann.concept_id, '尚未設定')}\n"
            f"上位概念：{doc.concepts.get(ann.broader_concept_id, '尚未設定')}\n"
            f"解釋 [{ann.explanation_start}, {ann.explanation_end})：{explanation}"
        )

    def _on_activated(self, index):
        annotation_id = self.annotations.itemData(index)
        if annotation_id:
            self.annotation_requested.emit(annotation_id)
