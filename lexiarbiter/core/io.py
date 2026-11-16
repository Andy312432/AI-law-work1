"""File I/O for LexiArbiter.

Supported file types:

* `.json`  - Raw judicial open-data file. We read the `JFULL` field for the
             full judgment text plus a few metadata fields.
* `.lexa`  - LexiArbiter's own work-in-progress format. JSON content but with
             a distinct extension so it is easy to tell apart from raw data.
             Holds the full original text + structured annotation list, so
             another annotator can pick up where you left off.
* `.txt`   - Final model-ready export, matching the wrapper format used by
             the user's MTL pipeline (e.g. ``<P>大前提,非第一人稱|...</P>``).
* `.docx`  - Mammoth converts Word content to semantic HTML for Qt rendering.
* `.md` / `.markdown`, `.html` / `.htm` - Native Qt rich content imports.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import mammoth
from pathlib import Path
from typing import Optional

from .config import AnnotationMode, ExportConfig
from .models import Annotation, Document
from .annotations import validate_term_annotations
from .rich_text import import_rich_text, is_html

log = logging.getLogger(__name__)


LEXA_VERSION = 1


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_judicial_json(path: Path | str) -> Document:
    """Load a raw judicial open-data .json file (JFULL inside).

    Some judicial open-data files have a top-level dict; some have a list with
    one record. Try both.
    """
    path = Path(path)
    log.info("載入 judicial JSON：%s", path)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        if not data:
            raise ValueError("JSON 內容為空陣列")
        data = data[0]
    if not isinstance(data, dict):
        raise ValueError("無法辨識 JSON 結構")

    text = data.get("JFULL") or data.get("jfull") or ""
    if not text:
        raise ValueError("JSON 中找不到 JFULL 欄位")

    meta = {k: v for k, v in data.items() if k not in ("JFULL", "jfull")}
    doc = Document(
        text=text,
        annotations=[],
        schema_id="",
        source_filename=path.name,
        source_meta=meta,
        file_path=str(path),
        dirty=False,
    )
    if is_html(text):
        return import_rich_text(doc, text, "html")
    return doc


def load_lexa(path: Path | str) -> Document:
    """Load a LexiArbiter work-in-progress file."""
    path = Path(path)
    log.info("載入 lexa：%s", path)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if data.get("format") != "lexa":
        raise ValueError("檔案不是 LexiArbiter 的 .lexa 格式")

    text = data.get("text", "")
    anns = [Annotation.from_dict(a) for a in data.get("annotations", [])]

    src = data.get("source", {}) or {}
    return Document(
        text=text,
        annotations=anns,
        schema_id=data.get("schema", ""),
        source_filename=src.get("filename", path.name),
        source_meta=src.get("meta", {}),
        concepts=data.get("concepts", {}),  # 新增：讀取概念池
        file_path=str(path),
        dirty=False,
    )


def load_docx(path: Path | str) -> Document:
    """Convert DOCX semantics to HTML with Mammoth, then use native Qt text."""
    path = Path(path)
    log.info("載入 DOCX（Mammoth）：%s", path)
    with path.open("rb") as source:
        result = mammoth.convert_to_html(source, ignore_empty_paragraphs=False)
    for message in result.messages:
        log.warning("Mammoth %s：%s", message.type, message.message)
    doc = Document("", source_filename=path.name, file_path=str(path), dirty=True)
    return import_rich_text(doc, result.value, "html")


def load_formatted_text(path: Path | str) -> Document:
    path = Path(path)
    text_format = "markdown" if path.suffix.lower() in {".md", ".markdown"} else "html"
    source = path.read_text(encoding="utf-8-sig")
    doc = Document("", source_filename=path.name, file_path=str(path), dirty=True)
    return import_rich_text(doc, source, text_format)


def load_any(path: Path | str) -> Document:
    """Dispatch on extension.

    .txt 不在此處理：它需要 AnnotationMode 才能把 tag 字串 resolve 成
    (group_id, label_id)，由 MainWindow.load_file 直接呼叫 parse_legacy_txt。
    """
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".lexa":
        return load_lexa(path)
    if suffix == ".json":
        return load_judicial_json(path)
    if suffix == ".docx":
        return load_docx(path)
    if suffix in {".md", ".markdown", ".html", ".htm"}:
        return load_formatted_text(path)
    raise ValueError(f"不支援的檔案類型：{suffix}")


# ---------------------------------------------------------------------------
# Save .lexa
# ---------------------------------------------------------------------------

def save_lexa(doc: Document, path: Path | str, schema: AnnotationMode,
              update_doc_state: bool = True) -> None:
    """寫入 .lexa。

    update_doc_state=False 時不更動 doc.file_path / dirty / schema_id，
    供 autosave、emergency 之類的「旁路存檔」使用——這些寫法不應該讓
    使用者看到的「未儲存」狀態消失。
    """
    path = Path(path)
    if update_doc_state and schema.id == "term_definition":
        validate_term_annotations(doc)
    log.info("儲存 lexa：%s（標註數：%d）", path, len(doc.annotations))
    payload = {
        "format": "lexa",
        "version": LEXA_VERSION,
        "schema": schema.id,
        "source": {
            "filename": doc.source_filename,
            "meta": doc.source_meta,
        },
        "concepts": doc.concepts,
        "text": doc.text,
        "annotations": [a.to_dict() for a in doc.sorted_annotations()],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=path.name + ".", suffix=".tmp", delete=False) as f:
            temporary = Path(f.name)
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    if update_doc_state:
        doc.file_path = str(path)
        doc.schema_id = schema.id
        doc.dirty = False


# ---------------------------------------------------------------------------
# Export model-ready .txt
# ---------------------------------------------------------------------------

def _format_p_line(text: str, labels: dict[str, str], concept_name: Optional[str],
                   schema: AnnotationMode, exp: ExportConfig) -> str:
    parts: list[str] = []
    for gid in exp.tag_order:
        lid = labels.get(gid)
        if not lid:
            continue
        lb = schema.label(gid, lid)
        if lb is not None:
            # 若有綁定概念，附加至 Tag 後方 (例如 Term=過擬合)
            if concept_name:
                parts.append(f"{lb.tag}={concept_name}")
            else:
                parts.append(lb.tag)
    tag_blob = exp.tag_separator.join(parts)
    # In the user's example, \r\n inside the original text is preserved as the
    # raw text (the model's preprocessing strips it later).
    return f"{exp.wrapper_open}{tag_blob}{exp.field_separator}{text}{exp.wrapper_close}"


def export_txt(doc: Document, path: Path | str, schema: AnnotationMode) -> dict:
    """Write a model-ready .txt file. Returns a dict with summary info.

    Summary keys: ``written`` (int), ``unannotated_chars`` (int),
    ``partial_count`` (int), ``warnings`` (list[str]).

    演算法以「字元 segment」為單位：先把所有 annotation 的 start/end
    切成不重疊區段，再對每個區段合併所有覆蓋該區段的 annotation labels。
    這讓「同範圍多群組」（無論在 .lexa 是用一條多群組 annotation 或多條
    同 span 各帶一群組來表達）匯出結果一致，達到冪等性。
    """
    path = Path(path)
    log.info("匯出 txt：%s", path)
    exp = schema.export

    text = doc.text
    n = len(text)

    # 1) 收集 boundary points。
    points: set[int] = {0, n}
    for a in doc.annotations:
        if 0 <= a.start <= n:
            points.add(a.start)
        if 0 <= a.end <= n:
            points.add(a.end)
    sorted_points = sorted(points)

    warnings: list[str] = []

    # 2) 對每個 segment 合併所有覆蓋它的 annotation labels。
    raw_segments: list[tuple[int, int, dict[str, str], Optional[str]]] = []
    for i in range(len(sorted_points) - 1):
        s, e = sorted_points[i], sorted_points[i + 1]
        if s >= e:
            continue
        seg_labels: dict[str, str] = {}
        seg_concept_id = None
        for a in doc.annotations:
            if a.start <= s and e <= a.end:
                if a.concept_id and seg_concept_id is None:
                    seg_concept_id = a.concept_id
                for gid, lid in a.labels.items():
                    if gid in seg_labels and seg_labels[gid] != lid:
                        # 同群組衝突理論上不會發生（apply_label 已禁止），
                        # 但讀入舊 .lexa 仍可能遇到；採「先到先得」並記警告。
                        seg_preview = text[s:min(s + 15, e)].replace("\r", " ").replace("\n", " ")
                        warnings.append(
                            f"段落 {s}-{e}「{seg_preview}…」同群組 {gid} 出現多個 label "
                            f"（{seg_labels[gid]} vs {lid}），採用先標註的版本。"
                        )
                    else:
                        seg_labels[gid] = lid
        raw_segments.append((s, e, seg_labels, seg_concept_id))

    # 3) 合併相鄰且 labels 完全相同的 segments，避免 boundary 切碎輸出。
    merged: list[tuple[int, int, dict[str, str]]] = []
    for s, e, lbls, cid in raw_segments:
        if merged and merged[-1][1] == s and merged[-1][2] == lbls and merged[-1][3] == cid:
            merged[-1] = (merged[-1][0], e, lbls, cid)
            #ps, _pe, plbls = merged[-1]
            #merged[-1] = (ps, e, plbls)
        else:
            merged.append((s, e, lbls, cid))

    # 4) 逐段輸出。
    lines: list[str] = []
    partial_count = 0
    unannotated_chars = 0
    written = 0

    for s, e, lbls, cid in merged:
        seg_text = text[s:e]
        if not seg_text:
            continue
        if lbls:
            missing = [
                schema.group(gid).name
                for gid in exp.tag_order
                if gid not in lbls and schema.group(gid) is not None
            ]
            if missing:
                partial_count += 1
                if exp.require_all_groups:
                    warnings.append(
                        f"段落「{seg_text[:15]}…」缺少必填群組：{', '.join(missing)}"
                    )
            concept_name = doc.concepts.get(cid) if cid else None
            lines.append(_format_p_line(seg_text, lbls, concept_name, schema, exp))
            written += 1
        else:
            if exp.include_unannotated and seg_text.strip():
                lines.append(seg_text)
                written += 1
            else:
                unannotated_chars += len(seg_text)

    # 換行策略：依 doc.text 主導換行決定。JSON 來源是 CRLF → 輸出 CRLF；
    # 純 LF 來源 → 輸出 LF。這讓「載入 .txt → 重新匯出」能達到 byte-identical
    # 的 round-trip（反向驗證匯出流程的核心需求）。
    crlf = text.count("\r\n")
    lf_only = text.count("\n") - crlf
    if crlf == 0 and lf_only == 0:
        nl = "\r\n"  # 全無換行 → fallback CRLF，與 user pipeline（範例檔）一致
    else:
        nl = "\r\n" if crlf >= lf_only else "\n"

    path.parent.mkdir(parents=True, exist_ok=True)
    # newline="" 避免 Python 在 Windows 上又把 \n 偷偷轉成 \r\n，
    # 破壞我們手動決定好的換行策略。
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(nl.join(lines))

    return {
        "written": written,
        "unannotated_chars": unannotated_chars,
        "partial_count": partial_count,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Optional: parse a legacy .txt back into a Document (best-effort).
# ---------------------------------------------------------------------------

_P_RE = re.compile(r"<P>(?P<tags>[^|<>]*)\|(?P<text>.*?)</P>", re.DOTALL)


def parse_legacy_txt(
    path: Path | str, schema: AnnotationMode
) -> tuple[Document, dict]:
    """Best-effort import of a model-ready .txt back into a Document.

    Each ``<P>tag1,tag2|text</P>`` segment becomes an Annotation. Tags that the
    schema does not recognise are dropped (recorded on ``ann.note``).

    Returns ``(Document, summary)``。summary 用於：
    1. 反向驗證匯出 bug：列出未知 tag、群組衝突、夾雜文字等異常。
    2. UI 在載入後彈窗讓 user 確認是否繼續、彙整顯示偵測結果。

    summary 鍵：
    - ``paragraphs``: 解析到的 <P>...</P> 段數
    - ``unknown_tags``: dict[str, int]，未知 tag 字串 → 出現次數
    - ``empty_tag_paragraphs``: int，<P>|...</P>（無任何 tag）
    - ``duplicate_tags_paragraphs``: int，<P>大前提,大前提|...</P>
    - ``group_collisions_paragraphs``: int，<P>大前提,小前提|...</P>
    - ``non_export_group_tags``: dict[str, int]，label 存在但其 group 不在
      ``schema.export.tag_order``（re-export 會被丟掉，需要警告）
    - ``stray_text_chars``: int，<P>...</P> 區塊外的非空白字元數
    - ``dominant_newline``: ``"\\r\\n"`` 或 ``"\\n"``
    """
    path = Path(path)
    # 以 bytes 讀檔偵測主導換行：要算「裸 \n」必須在 decode 前做，
    # 否則 Python 的 universal newlines 會把 \r\n 偷偷攤平。
    raw_bytes = path.read_bytes()
    crlf = raw_bytes.count(b"\r\n")
    bare_lf = raw_bytes.count(b"\n") - crlf
    nl = "\r\n" if crlf >= bare_lf else "\n"
    raw = raw_bytes.decode("utf-8")

    text_parts: list[str] = []
    annotations: list[Annotation] = []

    summary: dict = {
        "paragraphs": 0,
        "unknown_tags": {},
        "empty_tag_paragraphs": 0,
        "duplicate_tags_paragraphs": 0,
        "group_collisions_paragraphs": 0,
        "non_export_group_tags": {},
        "stray_text_chars": 0,
        "dominant_newline": nl,
    }

    export_groups = set(schema.export.tag_order)

    # 計算「<P>...</P> 區塊外的非空白字元數」用 cursor 追蹤。
    cursor = 0

    for m in _P_RE.finditer(raw):
        # 區塊間夾雜文字（含最前面）
        gap = raw[cursor:m.start()]
        summary["stray_text_chars"] += sum(1 for ch in gap if not ch.isspace())

        tags_raw = [t.strip() for t in m.group("tags").split(",") if t.strip()]
        seg = m.group("text")

        if not tags_raw:
            summary["empty_tag_paragraphs"] += 1
        if len(tags_raw) != len(set(tags_raw)):
            summary["duplicate_tags_paragraphs"] += 1

        labels: dict[str, str] = {}
        note_lines: list[str] = []
        unknown: list[str] = []
        collisions: list[str] = []  # 同群組衝突敘述
        for t in tags_raw:
            lb = schema.find_label_by_tag(t)
            if lb is None:
                unknown.append(t)
                summary["unknown_tags"][t] = summary["unknown_tags"].get(t, 0) + 1
                continue
            if lb.group_id not in export_groups:
                # label 存在但 group 不在 export.tag_order：re-export 會丟掉，
                # 視為「未知（不會被匯出的群組）」一起警告。
                key = f"(非匯出群組: {lb.group_id})"
                summary["non_export_group_tags"][t] = (
                    summary["non_export_group_tags"].get(t, 0) + 1
                )
                note_lines.append(f"非匯出群組標籤：{t}（group={lb.group_id}）")
            if lb.group_id in labels and labels[lb.group_id] != lb.id:
                collisions.append(
                    f"{lb.group_id}={labels[lb.group_id]} vs {lb.id}"
                )
            labels[lb.group_id] = lb.id

        if collisions:
            summary["group_collisions_paragraphs"] += 1
            note_lines.append(
                f"同群組衝突：{'; '.join(collisions)}（採後標註的版本）"
            )

        if unknown:
            note_lines.append(f"未知標籤：{','.join(unknown)}")

        # 串接：區塊間用主導換行（與檔案內保持一致）。
        # 區塊內 seg 保持原樣（已是主導換行 + 文字內容）。
        if text_parts:
            text_parts.append(nl)
        text_parts.append(seg)
        end = sum(len(p) for p in text_parts)
        start = end - len(seg)

        ann = Annotation(start=start, end=end, labels=labels)
        if note_lines:
            ann.note = "；".join(note_lines)
        annotations.append(ann)
        summary["paragraphs"] += 1
        cursor = m.end()

    # 最後一個 </P> 之後的夾雜文字
    tail = raw[cursor:]
    summary["stray_text_chars"] += sum(1 for ch in tail if not ch.isspace())

    if not annotations:
        raise ValueError("此 .txt 不含任何 <P>...</P> 段落，無法作為標註匯入。")

    text = "".join(text_parts)
    doc = Document(
        text=text,
        annotations=annotations,
        schema_id=schema.id,
        source_filename=path.name,
        file_path=str(path),
        dirty=False,
    )
    return doc, summary
