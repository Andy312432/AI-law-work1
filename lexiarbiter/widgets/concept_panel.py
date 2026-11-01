"""Concept management UI components."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QLineEdit, QPushButton,
    QLabel, QWidget, QMessageBox, QComboBox, QPlainTextEdit
)

from .concept_tree import ConceptSidebar

class ConceptSelectionDialog(QDialog):
    """彈出視窗：讓使用者從現有概念挑選，或輸入新概念。"""
    def __init__(self, concepts: dict[str, str], default_text: str = "", parent=None,
                 broader_name: str = ""):
        super().__init__(parent)
        self.setWindowTitle("設定概念與上位概念")
        self.resize(420, 510)
        
        layout = QVBoxLayout(self)
        
        layout.addWidget(QLabel("1. 從現有概念選擇："))
        self.list_widget = QListWidget()
        # 依最近加入(或字母)排序顯示
        self._concept_map = {}
        for cid, name in concepts.items():
            self.list_widget.addItem(name)
            self._concept_map[name] = cid
        layout.addWidget(self.list_widget)
        # 將清單依照筆畫/字母順序排序
        self.list_widget.sortItems(Qt.AscendingOrder)

        layout.addWidget(QLabel("2. 或直接輸入新概念："))
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("輸入新術語概念...")
        # 自動將反白的文字填入輸入框
        self.input_edit.setText(default_text) 
        # 選取框內所有文字，方便使用者如果不滿意可以直接打字覆蓋
        self.input_edit.selectAll()
        layout.addWidget(self.input_edit)

        layout.addWidget(QLabel("3. 上位概念（可選既有概念或輸入新名稱）："))
        self.broader_combo = QComboBox()
        self.broader_combo.setEditable(True)
        self.broader_combo.addItem("（同本概念，最上層）", None)
        for name in sorted(set(concepts.values())):
            self.broader_combo.addItem(name, name)
        if broader_name and broader_name != default_text:
            self.broader_combo.setCurrentText(broader_name)
        layout.addWidget(self.broader_combo)
        note = QLabel("新標註的解釋預設為術語本身，既有解釋會保留。可選取解釋文字，按「設為此術語的解釋」。")
        note.setWordWrap(True)
        layout.addWidget(note)

        # 按鈕區
        btn_layout = QHBoxLayout()
        self.btn_ok = QPushButton("確定 (Enter)")
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

        # 點擊清單時自動填入輸入框
        self.list_widget.itemClicked.connect(lambda item: self.input_edit.setText(item.text()))
        self.list_widget.itemDoubleClicked.connect(lambda _item: self.accept())
        self.btn_ok.setDefault(True)
        self.input_edit.setFocus()

    def accept(self):
        if not self.input_edit.text().strip() or not self.broader_combo.currentText().strip():
            QMessageBox.warning(self, "欄位未完成", "概念與上位概念不能留空。最上層請選「同本概念」。")
            return
        super().accept()

    def concept_name(self) -> str:
        return self.input_edit.text().strip()

    def broader_name(self) -> str:
        text = self.broader_combo.currentText().strip()
        if text == self.broader_combo.itemText(0):
            return self.concept_name()
        return text

    def get_result(self) -> tuple[str | None, str | None]:
        """回傳 (已存在的 ID, 新增的名稱)。若輸入框為空則回傳 (None, None)。"""
        text = self.input_edit.text().strip()
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
        self.annotations.setPlaceholderText("點選文中的術語，或從這裡選擇")
        self.annotations.activated.connect(self._on_activated)
        layout.addWidget(self.annotations)
        self.summary = QPlainTextEdit()
        self.summary.setReadOnly(True)
        self.summary.setMaximumHeight(155)
        layout.addWidget(self.summary)
        self.set_explanation_button = QPushButton("設為此術語的解釋（Ctrl+L）")
        self.set_explanation_button.clicked.connect(self.explanation_requested)
        layout.addWidget(self.set_explanation_button)
        row = QHBoxLayout()
        self.use_self_button = QPushButton("解釋用術語本身")
        self.use_self_button.clicked.connect(self.self_explanation_requested)
        self.edit_concepts_button = QPushButton("修改概念／上位概念")
        self.edit_concepts_button.clicked.connect(self.concepts_requested)
        row.addWidget(self.use_self_button)
        row.addWidget(self.edit_concepts_button)
        layout.addLayout(row)
        hint = QLabel("黃色：術語　藍色：目前術語的解釋\n先點術語，再選取解釋文字並按上方按鈕。")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.refresh(None)

    def refresh(self, doc, annotation_id=None):
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
            self.summary.setPlainText("選取術語文字，按「專業術語」建立標註。\n點選既有術語可查看、修改這一筆。")
            return
        explanation = "尚未設定"
        if ann.explanation_start is not None and ann.explanation_end is not None:
            explanation = doc.text[ann.explanation_start:ann.explanation_end]
        self.summary.setPlainText(
            f"術語：{doc.text[ann.start:ann.end]}\n"
            f"概念：{doc.concepts.get(ann.concept_id, '尚未設定')}\n"
            f"上位概念：{doc.concepts.get(ann.broader_concept_id, '尚未設定')}\n"
            f"解釋 [{ann.explanation_start}, {ann.explanation_end})：{explanation}"
        )

    def _on_activated(self, index):
        annotation_id = self.annotations.itemData(index)
        if annotation_id:
            self.annotation_requested.emit(annotation_id)
