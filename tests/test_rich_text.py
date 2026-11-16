"""Native rich rendering must preserve selectable annotation coordinates."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from lexiarbiter.core.annotations import TextSpan, record_term, set_explanation
from lexiarbiter.core.config import UserPreferences, list_annotation_modes
from lexiarbiter.core.io import load_any, load_docx, load_lexa, save_lexa
from lexiarbiter.core.models import Annotation, Document
from lexiarbiter.core.rich_text import RICH_TEXT_KEY
from lexiarbiter.widgets.editor import AnnotationEditor
from lexiarbiter.widgets.file_panel import FilePanel


APP = QApplication.instance() or QApplication([])


def write_docx(path):
    """A small real DOCX: heading, bold run, list, table, and line break."""
    with ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", '''
            <Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
              <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
              <Default Extension="xml" ContentType="application/xml"/>
              <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
            </Types>''')
        archive.writestr("_rels/.rels", '''
            <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
              <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
            </Relationships>''')
        archive.writestr("word/document.xml", '''
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body>
                <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>債之關係</w:t></w:r></w:p>
                <w:p><w:r><w:rPr><w:b/></w:rPr><w:t>無因管理</w:t></w:r><w:r><w:br/><w:t>解釋😀</w:t></w:r></w:p>
                <w:tbl><w:tr><w:tc><w:p><w:r><w:t>術語</w:t></w:r></w:p></w:tc>
                  <w:tc><w:p><w:r><w:t>無因管理</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
              </w:body>
            </w:document>''')
        archive.writestr("word/_rels/document.xml.rels", '''
            <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
              <Relationship Id="styles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
            </Relationships>''')
        archive.writestr("word/styles.xml", '''
            <w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/></w:style>
            </w:styles>''')


class RichTextTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.mode = next(mode for mode in list_annotation_modes() if mode.id == "term_definition")
        self.editor = AnnotationEditor()
        self.addCleanup(self.editor.close)

    def open_source(self, suffix, source):
        path = self.root / ("example" + suffix)
        path.write_text(source, encoding="utf-8-sig")
        doc = load_any(path)
        self.editor.attach(doc, self.mode, UserPreferences.load())
        self.assertEqual(self.editor.toPlainText(), doc.text)
        return doc

    def select_word(self, doc, word, start=0):
        offset = doc.text.index(word, start)
        cursor = self.editor.document().find(word, self.editor._omap.to_display(start))
        self.assertFalse(cursor.isNull())
        self.editor.setTextCursor(cursor)
        self.assertEqual(self.editor.storage_selection(), (offset, offset + len(word)))
        return offset

    def test_markdown_bold_heading_and_inline_html_use_native_formats(self):
        doc = self.open_source(".md", "# 標題\n\n**無因管理**<br />解釋😀\n\n- 無因管理")
        self.assertNotIn("**", doc.text)
        self.assertNotIn("<br", doc.text)
        self.assertIn("無因管理\n解釋😀", doc.text)
        start = self.select_word(doc, "無因管理")
        self.assertGreaterEqual(self.editor.textCursor().charFormat().fontWeight(), QFont.Bold)
        self.assertIsNotNone(self.editor.document().lastBlock().textList())
        result = record_term(doc, TextSpan(start, start + 4), "無因管理")
        explanation = self.select_word(doc, "解釋😀")
        set_explanation(doc, result.annotation.id, TextSpan(explanation, explanation + 3))
        self.assertEqual(len(doc.annotations), 2)
        self.assert_roundtrip(doc)

    def test_html_entities_table_emoji_and_br_offsets_roundtrip(self):
        doc = self.open_source(".html", "<h1>標題</h1><p>甲😀<br>乙&nbsp;丙</p>"
                               "<table><tr><td><b>無因管理</b></td><td>解釋😀</td></tr></table>"
                               "<p>無因管理</p>")
        self.assertIn("甲😀\n乙 丙", doc.text)
        start = self.select_word(doc, "無因管理")
        self.assertIsNotNone(self.editor.textCursor().currentTable())
        result = record_term(doc, TextSpan(start, start + 4), "無因管理")
        explanation = self.select_word(doc, "解釋😀")
        set_explanation(doc, result.annotation.id, TextSpan(explanation, explanation + 3))
        self.editor.set_active_annotation(result.annotation.id)
        self.assertTrue(any(s.cursor.selectedText() == "解釋😀" for s in self.editor.extraSelections()))
        self.editor.jump_to_annotation(result.annotation.id)
        self.assertEqual(self.editor.textCursor().selectedText(), "無因管理")
        self.assert_roundtrip(doc)

    def assert_roundtrip(self, doc):
        path = self.root / "saved.lexa"
        save_lexa(doc, path, self.mode)
        restored = load_lexa(path)
        self.assertEqual(restored.text, doc.text)
        self.assertEqual(restored.annotations, doc.annotations)
        self.assertEqual(restored.source_meta, doc.source_meta)
        self.editor.attach(restored, self.mode, UserPreferences.load())
        self.assertEqual(self.editor.toPlainText(), doc.text)
        self.select_word(restored, "無因管理")
        self.assertGreaterEqual(self.editor.textCursor().charFormat().fontWeight(), QFont.Bold)

    def test_docx_mammoth_keeps_heading_bold_table_and_break(self):
        path = self.root / "example.docx"
        write_docx(path)
        doc = load_docx(path)
        self.editor.attach(doc, self.mode, UserPreferences.load())
        self.assertIn("無因管理\n解釋😀", doc.text)
        self.assertNotIn("我是表格", doc.text)
        self.assertEqual(self.editor.document().firstBlock().blockFormat().headingLevel(), 1)
        start = self.select_word(doc, "無因管理")
        self.assertGreaterEqual(self.editor.textCursor().charFormat().fontWeight(), QFont.Bold)
        self.select_word(doc, "無因管理", start + 4)
        self.assertIsNotNone(self.editor.textCursor().currentTable())
        record_term(doc, TextSpan(start, start + 4), "無因管理")
        self.assert_roundtrip(doc)

    def test_judicial_html_br_is_a_native_line_break(self):
        path = self.root / "judgment.json"
        path.write_text(json.dumps({"JFULL": "<p>甲<br />乙</p>", "JID": "sample"}), encoding="utf-8")
        doc = load_any(path)
        self.editor.attach(doc, self.mode, UserPreferences.load())
        self.assertEqual(doc.text, "甲\n乙")
        self.assertEqual(self.editor.toPlainText(), "甲\n乙")
        self.assertEqual(doc.source_meta["JID"], "sample")

    def test_legacy_lexa_is_not_reparsed_or_reindexed(self):
        doc = Document("甲<br />**乙**", [Annotation(9, 10, {"entity": "term"})])
        self.editor.attach(doc, self.mode, UserPreferences.load())
        self.assertEqual(self.editor.toPlainText(), doc.text)
        self.assertEqual(self.select_word(doc, "乙"), 9)

    def test_plain_judicial_text_preserves_original_line_endings_and_literals(self):
        path = self.root / "plain.json"
        text = "甲\r\n**乙**，甲 < 乙"
        path.write_text(json.dumps({"JFULL": text}), encoding="utf-8")
        doc = load_any(path)
        self.assertEqual(doc.text, text)
        self.assertNotIn(RICH_TEXT_KEY, doc.source_meta)

    def test_render_source_mismatch_falls_back_to_stored_text_without_moving_annotations(self):
        doc = self.open_source(".html", "<b>無因管理</b>")
        record_term(doc, TextSpan(0, 4), "無因管理")
        doc.source_meta[RICH_TEXT_KEY]["source"] = "<p>已被外部改動的內容</p>"
        with self.assertLogs("lexiarbiter.core.rich_text", level="WARNING"):
            self.editor.attach(doc, self.mode, UserPreferences.load())
        self.assertEqual(self.editor.toPlainText(), "無因管理")
        selections = self.editor.extraSelections()
        self.assertEqual(selections[0].cursor.selectedText(), "無因管理")

    def test_format_aliases_are_importable_and_listed_in_source_folder(self):
        for suffix, source, expected in [(".markdown", "**甲**", "甲"),
                                         (".htm", "<b>乙</b>", "乙")]:
            with self.subTest(suffix=suffix):
                self.assertEqual(self.open_source(suffix, source).text, expected)
        panel = FilePanel()
        self.addCleanup(panel.close)
        panel.set_directory(self.root, self.root / "example.htm")
        self.assertEqual(panel._lists["raw"].count(), 2)
        self.assertEqual(panel.tabs.currentIndex(), 0)


if __name__ == "__main__":
    unittest.main()
