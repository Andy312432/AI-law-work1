"""Native Qt rich content, stored separately from annotation text coordinates."""

from html.parser import HTMLParser
import logging

from PySide6.QtGui import QTextDocument

from .models import Document


log = logging.getLogger(__name__)
RICH_TEXT_KEY = "_lexiarbiter_rich_text"


class _HtmlDetector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.found = False

    def handle_starttag(self, tag, attrs):
        if tag in {
            "html", "body", "p", "div", "span", "br", "hr", "img", "a",
            "b", "strong", "i", "em", "u", "s", "sub", "sup", "pre", "code",
            "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "ul", "ol", "li",
            "table", "thead", "tbody", "tfoot", "tr", "th", "td", "dl", "dt", "dd",
        }:
            self.found = True


def is_html(source: str) -> bool:
    detector = _HtmlDetector()
    detector.feed(source)
    return detector.found


def set_rich_text(target: QTextDocument, source: str, text_format: str) -> None:
    if text_format == "markdown":
        target.setMarkdown(source)
        return
    if text_format == "html":
        target.setHtml(source)
        return
    raise ValueError(f"不支援的文字格式：{text_format}")


def import_rich_text(doc: Document, source: str, text_format: str) -> Document:
    """For new imports only: annotate native visible text, retain formatted source."""
    if doc.annotations:
        raise ValueError("已有標註的文件不可重新轉換文字座標")
    rendered = QTextDocument()
    set_rich_text(rendered, source, text_format)
    doc.text = rendered.toPlainText()
    doc.source_meta[RICH_TEXT_KEY] = {"format": text_format, "source": source}
    return doc


def display_document(target: QTextDocument, doc: Document) -> None:
    content = doc.source_meta.get(RICH_TEXT_KEY)
    if isinstance(content, dict) and content.get("format") in {"markdown", "html"}:
        source = content.get("source")
        if isinstance(source, str):
            set_rich_text(target, source, content["format"])
            if target.toPlainText() == doc.text:
                return
            # A changed source or Qt parser must never move saved annotations.
            log.warning("格式內容與標註原文不同，改用原文顯示：%s", doc.source_filename)
    target.setPlainText(doc.text)
