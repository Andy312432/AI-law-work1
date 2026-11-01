"""The annotation editor widget.

We keep the *original* text in `Document.text` (with raw ``\\r\\n`` line
endings, exactly as it appears in the source JSON), because that is what gets
serialised into ``.lexa`` / ``.txt`` output and what the user's MTL pipeline
preprocesses later.

For *display*, ``\\r\\n`` is normalised to ``\\n`` and literal ``<br>`` tags
are hidden. Two-way maps keep annotation offsets in the original (storage) text.
"""

from __future__ import annotations

import logging
import re
from html import escape
from typing import Optional

log = logging.getLogger(__name__)

from PySide6.QtCore import Qt, QPoint, Signal, QEvent
from PySide6.QtGui import (
    QAction, QColor, QGuiApplication, QKeySequence, QShortcut, QTextCharFormat,
    QTextCursor, QFont, QPalette,
)
from PySide6.QtWidgets import QMenu, QTextEdit, QToolTip

from ..core.config import AnnotationMode, UserPreferences, default_ui_font
from ..core.models import Annotation, Document


class _OffsetMap:
    """Map original Python string offsets to Qt display offsets (UTF-16)."""

    def __init__(self, raw: str):
        self.storage_to_display: list[int] = [0] * (len(raw) + 1)
        self.display_to_storage: list[int] = []
        # A hidden tag can sit between a selection's end and the next start.
        self._display_end_to_storage: list[int] = [0]
        display_chars: list[str] = []
        d = 0
        i = 0
        while i < len(raw):
            hidden_break = re.match(r"<br\s*/?>", raw[i:i + 16], re.IGNORECASE)
            if hidden_break:
                length = len(hidden_break.group())
                for offset in range(i, i + length):
                    self.storage_to_display[offset] = d
                i += length
                continue

            is_crlf = raw.startswith("\r\n", i)
            storage_length = 2 if is_crlf else 1
            ch = "\n" if is_crlf else raw[i]
            display_length = 2 if ord(ch) > 0xFFFF else 1
            for offset in range(i, i + storage_length):
                self.storage_to_display[offset] = d
            self.display_to_storage.extend([i] * display_length)
            self._display_end_to_storage.extend([i + storage_length] * display_length)
            display_chars.append(ch)
            d += display_length
            i += storage_length
        self.storage_to_display[len(raw)] = d
        self.display_to_storage.append(len(raw))
        self.display_text = "".join(display_chars)

    def to_display(self, storage_offset: int) -> int:
        if storage_offset <= 0:
            return 0
        if storage_offset >= len(self.storage_to_display):
            return self.storage_to_display[-1]
        return self.storage_to_display[storage_offset]

    def to_storage(self, display_offset: int, *, end: bool = False) -> int:
        offsets = self._display_end_to_storage if end else self.display_to_storage
        if display_offset <= 0:
            return offsets[0]
        if display_offset >= len(offsets):
            return offsets[-1]
        return offsets[display_offset]


def _hex_to_qcolor(value: Optional[str], alpha: int = 110) -> Optional[QColor]:
    if not value:
        return None
    c = QColor(value)
    if not c.isValid():
        return None
    c.setAlpha(alpha)
    return c


def _is_dark_palette(widget) -> bool:
    """判斷 widget 目前是否處於深色背景主題。

    優先讀 Qt 6.5+ 的 ``styleHints().colorScheme()``；舊版或回報 Unknown 時
    退回以 ``QPalette.Base`` 亮度判斷（< 128 視為深色）。
    """
    try:
        scheme = QGuiApplication.styleHints().colorScheme()
        if scheme == Qt.ColorScheme.Dark:
            return True
        if scheme == Qt.ColorScheme.Light:
            return False
    except (AttributeError, RuntimeError):
        pass
    return widget.palette().color(QPalette.Base).lightness() < 128


class AnnotationEditor(QTextEdit):
    """Read-only-ish text view that renders annotations as background highlights.

    Selection is editable in the sense that the user can click and drag to
    select text spans, and we expose those spans for the host window to apply
    annotations to. The text content itself cannot be modified.
    """

    annotation_clicked = Signal(str)  # annotation id
    selection_changed = Signal(int, int)  # storage start, storage end
    # 滑鼠左鍵拖選結束、且選取範圍非空時 emit；參數為放開滑鼠的 global 座標，
    # 讓 host window 可以在原地附近彈出快速標註選單。
    selection_finished = Signal(QPoint)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setUndoRedoEnabled(False)
        # Allow text selection but keep cursor visible.
        self.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard
        )
        self.setMouseTracking(True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)
        self.selectionChanged.connect(self._on_selection_changed)

        self._doc: Optional[Document] = None
        self._mode: Optional[AnnotationMode] = None
        self._prefs: Optional[UserPreferences] = None
        self._omap: Optional[_OffsetMap] = None
        self._context_menu_builder = None
        # 追蹤是不是「正在拖左鍵」；右鍵 / 中鍵 / 鍵盤選取都不應觸發 popup。
        self._left_drag_active: bool = False
        self._active_annotation_id: Optional[str] = None
        self._active_concept_id: Optional[str] = None

        # 系統深 / 淺色主題切換時自動重繪。Qt 6.5+ 才有此 signal，
        # 舊版直接 fallback 到「重啟程式才生效」。
        try:
            QGuiApplication.styleHints().colorSchemeChanged.connect(
                lambda _scheme: self.refresh_highlights()
            )
        except (AttributeError, RuntimeError):
            pass

    # ------------------------------------------------------------------ setup

    def attach(self, doc: Document, mode: AnnotationMode, prefs: UserPreferences):
        self._doc = doc
        self._mode = mode
        self._prefs = prefs
        self._active_annotation_id = None
        self._active_concept_id = None

        font = QFont(prefs.ui.get("font_family", default_ui_font()),
                     prefs.ui.get("font_size", 14))
        self.setFont(font)

        # Build display text and its offset maps with the same transformations.
        self._omap = _OffsetMap(doc.text)
        self.setPlainText(self._omap.display_text)

        # Block-format with line spacing.
        self._apply_line_spacing(prefs.ui.get("line_spacing", 1.4))
        self.refresh_highlights()

    def _apply_line_spacing(self, factor: float):
        if not self._doc:
            return
        cursor = QTextCursor(self.document())
        cursor.select(QTextCursor.Document)
        block_fmt = cursor.blockFormat()
        block_fmt.setLineHeight(int(factor * 100), 1)  # ProportionalHeight
        cursor.setBlockFormat(block_fmt)

    def set_context_menu_builder(self, fn):
        """`fn(menu, ann_id_or_None, sel_start, sel_end)` populates the menu."""
        self._context_menu_builder = fn

    # ----------------------------------------------------------- selection

    def storage_selection(self) -> tuple[int, int]:
        if self._omap is None:
            return (0, 0)
        cur = self.textCursor()
        d_start = cur.selectionStart()
        d_end = cur.selectionEnd()
        start = self._omap.to_storage(d_start)
        if not cur.hasSelection():
            return (start, start)
        return (start, self._omap.to_storage(d_end, end=True))

    def has_selection(self) -> bool:
        s, e = self.storage_selection()
        return e > s

    def _on_selection_changed(self):
        self.refresh_highlights()
        s, e = self.storage_selection()
        self.selection_changed.emit(s, e)

    # --------------------------------------------------- mouse drag detection

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._left_drag_active = True
        super().mousePressEvent(ev)

    def mouseReleaseEvent(self, ev):
        super().mouseReleaseEvent(ev)
        # 只在「左鍵放開」且本輪確實是從左鍵按下開始時觸發；右鍵 / 鍵盤選取都不算。
        if ev.button() == Qt.LeftButton and self._left_drag_active:
            self._left_drag_active = False
            if self.has_selection():
                self.selection_finished.emit(ev.globalPosition().toPoint())
                return
            if self._doc is not None and self._omap is not None:
                cursor = self.cursorForPosition(ev.position().toPoint())
                annotations = self._doc.annotations_at(self._omap.to_storage(cursor.position()))
                if annotations:
                    self.annotation_clicked.emit(annotations[-1].id)

    def set_active_annotation(self, annotation_id: Optional[str]):
        self._active_annotation_id = annotation_id
        self._active_concept_id = None
        self.refresh_highlights()

    def highlight_concept(self, concept_id: str):
        self._active_concept_id = concept_id
        self.refresh_highlights()

    def _range_highlight(self, start: int, end: int, color: str):
        selection = QTextEdit.ExtraSelection()
        selection.cursor = QTextCursor(self.document())
        selection.cursor.setPosition(self._omap.to_display(start))
        selection.cursor.setPosition(self._omap.to_display(end), QTextCursor.KeepAnchor)
        selection.format.setBackground(QColor(color))
        selection.format.setForeground(QColor("#102027"))
        return selection

    # ------------------------------------------------------ highlight render

    def refresh_highlights(self):
        if self._doc is None or self._mode is None or self._omap is None:
            return
        try:
            selections = []
            for ann in self._doc.annotations:
                sel = QTextEdit.ExtraSelection()
                cursor = self.textCursor()
                d_start = self._omap.to_display(ann.start)
                d_end = self._omap.to_display(ann.end)
                cursor.setPosition(d_start)
                cursor.setPosition(d_end, QTextCursor.KeepAnchor)
                sel.cursor = cursor

                fmt = QTextCharFormat()
                self._apply_format_for_labels(fmt, ann)
                sel.format = fmt
                selections.append(sel)
            active = self._doc.find_annotation(self._active_annotation_id)
            if active and active.explanation_start is not None and active.explanation_end is not None:
                selections.append(self._range_highlight(active.explanation_start, active.explanation_end, "#90CAF9"))
                selections.append(self._range_highlight(active.start, active.end, "#FFE082"))
            for ann in self._doc.annotations:
                if self._active_concept_id and ann.concept_id == self._active_concept_id:
                    selections.append(self._range_highlight(ann.start, ann.end, "#A5D6A7"))
            selections.extend(self._matching_text_selections())
            self.setExtraSelections(selections)
        except Exception:
            # 高亮渲染失敗時清空顯示，避免整個 UI 崩潰
            log.error("refresh_highlights 發生例外，已清空高亮", exc_info=True)
            self.setExtraSelections([])

    def _matching_text_selections(self) -> list[QTextEdit.ExtraSelection]:
        """暫時反白全文相同文字，不建立或修改正式標註。"""
        cursor = self.textCursor()
        if not cursor.hasSelection():
            return []

        selected_word = cursor.selectedText().replace("\u2029", "\n")
        text = self.toPlainText()
        fmt = QTextCharFormat()
        fmt.setBackground(QColor("#FFF59D"))
        fmt.setForeground(QColor("#1B1B1B"))

        selections = []
        previous_start = 0
        display_start = 0
        # Lookahead includes overlapping matches; escape treats the text literally.
        for match in re.finditer(f"(?={re.escape(selected_word)})", text):
            # Qt cursor positions count UTF-16 units, including emoji pairs.
            display_start += len(text[previous_start:match.start()].encode("utf-16-le")) // 2
            previous_start = match.start()
            sel = QTextEdit.ExtraSelection()
            sel.cursor = QTextCursor(self.document())
            sel.cursor.setPosition(display_start)
            sel.cursor.setPosition(display_start + cursor.selectionEnd() - cursor.selectionStart(),
                                   QTextCursor.KeepAnchor)
            sel.format = fmt
            selections.append(sel)
        return selections

    def _apply_format_for_labels(self, fmt: QTextCharFormat, ann: Annotation):
        """First group with a non-null color drives the background.
        Other group labels are reflected via underline style.

        渲染參數依當下 palette（深 / 淺）自動切換：深色模式提高背景 alpha 並
        強制反白標註內文字色，底線色則固定取近黑或近白以保證對比。
        """
        if self._mode is None:
            return
        dark = _is_dark_palette(self)
        bg_alpha = 180 if dark else 130
        fallback_alpha = 90 if dark else 50
        # 底線色一律取與編輯器背景對比最強的近黑 / 近白，不再從主背景色 darker/lighter 派生
        underline_default = QColor("#ECEFF1") if dark else QColor("#1B1B1B")

        bg_color: Optional[QColor] = None
        underline_style = QTextCharFormat.NoUnderline
        underline_color: Optional[QColor] = None
        tooltip_parts: list[str] = []

        for g in self._mode.groups:
            lid = ann.labels.get(g.id)
            if not lid:
                continue
            lb = g.label(lid)
            if lb is None:
                continue
            tooltip_parts.append(f"{g.name}：{lb.name}")
            color = _hex_to_qcolor(lb.color, alpha=bg_alpha)
            if color is not None and bg_color is None:
                bg_color = color
            elif color is None:
                # 輔助群組：依該群組內 label 索引選底線樣式。
                # WaveUnderline / DashDotLine 兩者視覺差異大，在中文字下都不會被誤認為實線。
                idx = g.labels.index(lb)
                styles = [
                    QTextCharFormat.WaveUnderline,    # 第一人稱：波浪線（視覺重量大，主關注點）
                    QTextCharFormat.DashDotLine,      # 非第一人稱：dash-dot（次要層次）
                    QTextCharFormat.SingleUnderline,  # 預留第三類
                    QTextCharFormat.DotLine,          # 預留第四類
                ]
                underline_style = styles[idx % len(styles)]
                underline_color = underline_default

        if bg_color is None:
            # 無主背景色時：淡黃後備，深色模式提高 alpha 讓 span 仍可辨識。
            bg_color = _hex_to_qcolor("#FFF59D", alpha=fallback_alpha)

        fmt.setBackground(bg_color)
        # 深色模式下標註背景變得不透明度高，強制深色文字色保證閱讀對比。
        if dark and bg_color is not None:
            fmt.setForeground(QColor("#1B1B1B"))
        if underline_style != QTextCharFormat.NoUnderline:
            fmt.setUnderlineStyle(underline_style)
            if underline_color is not None:
                fmt.setUnderlineColor(underline_color)
        if tooltip_parts:
            fmt.setToolTip("　|　".join(tooltip_parts))

    # ----------------------------------------------------------- context menu

    def annotation_tooltip(self, ann: Annotation) -> str:
        term = self._doc.text[ann.start:ann.end]
        concept = self._doc.concepts.get(ann.concept_id, "尚未設定")
        broader = self._doc.concepts.get(ann.broader_concept_id, "尚未設定")
        explanation = "尚未設定"
        if ann.explanation_start is not None and ann.explanation_end is not None:
            explanation = self._doc.text[ann.explanation_start:ann.explanation_end]
        return (f"<b>術語：</b>{escape(term)}<br><b>概念：</b>{escape(concept)}"
                f"<br><b>上位概念：</b>{escape(broader)}<br><b>解釋：</b>{escape(explanation[:400])}")

    def viewportEvent(self, event):
        if event.type() == QEvent.ToolTip and self._doc is not None and self._omap is not None:
            cursor = self.cursorForPosition(event.pos())
            annotations = self._doc.annotations_at(self._omap.to_storage(cursor.position()))
            if annotations:
                QToolTip.showText(event.globalPos(), self.annotation_tooltip(annotations[-1]), self)
                return True
            QToolTip.hideText()
        return super().viewportEvent(event)

    def _on_context_menu(self, pos: QPoint):
        if self._context_menu_builder is None:
            return
        menu = QMenu(self)
        cursor = self.cursorForPosition(pos)
        if not self.textCursor().hasSelection():
            self.setTextCursor(cursor)
        d_pos = cursor.position()
        if self._omap is None:
            return
        storage_pos = self._omap.to_storage(d_pos)
        sel_start, sel_end = self.storage_selection()
        ann_id = None
        if self._doc is not None:
            anns_at = self._doc.annotations_at(storage_pos)
            if anns_at:
                ann_id = anns_at[-1].id
        self._context_menu_builder(menu, ann_id, sel_start, sel_end)
        if not menu.isEmpty():
            menu.exec(self.mapToGlobal(pos))

    def annotation_at_cursor(self) -> Optional[str]:
        if self._doc is None or self._omap is None:
            return None
        cur = self.textCursor()
        storage_pos = self._omap.to_storage(cur.position())
        anns_at = self._doc.annotations_at(storage_pos)
        return anns_at[-1].id if anns_at else None

    def jump_to_annotation(self, ann_id: str):
        if self._doc is None or self._omap is None:
            return
        ann = self._doc.find_annotation(ann_id)
        if ann is None:
            return
        cur = self.textCursor()
        cur.setPosition(self._omap.to_display(ann.start))
        cur.setPosition(self._omap.to_display(ann.end), QTextCursor.KeepAnchor)
        self.setTextCursor(cur)
        self.ensureCursorVisible()
