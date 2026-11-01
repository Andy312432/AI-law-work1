"""Term/explanation operations using the template's unchanged data format."""

from dataclasses import dataclass
import uuid

from .models import Annotation, Document


@dataclass(frozen=True)
class TextSpan:
    start: int
    end: int

    def validate(self, text: str) -> None:
        if not (isinstance(self.start, int) and isinstance(self.end, int)
                and 0 <= self.start < self.end <= len(text)):
            raise ValueError("請選取有效的文字範圍。")
        if not text[self.start:self.end].strip():
            raise ValueError("範圍不能只有空白或換行。")


@dataclass(frozen=True)
class AnnotationResult:
    annotation: Annotation
    auto_created: int = 0
    skipped: int = 0


def _concept_id(doc: Document, name: str) -> str:
    for cid, existing in doc.concepts.items():
        if existing == name:
            return cid
    cid = "C_" + uuid.uuid4().hex[:8]
    doc.concepts[cid] = name
    return cid


def record_term(doc: Document, span: TextSpan, concept_name: str,
                broader_name: str | None = None, *, group_id: str = "entity",
                label_id: str = "term", auto_match: bool = True,
                replace_conflicts: bool = False) -> AnnotationResult:
    """Record a complete term, then add available literal matches.

    Existing annotations always win during automatic matching. New occurrences
    inherit concepts, but use their own term span as the explanation. A local
    explanation cannot be inferred from an occurrence elsewhere in the text.
    """
    span.validate(doc.text)
    name = concept_name.strip()
    broader = broader_name.strip() if broader_name else name
    if not name or not broader:
        raise ValueError("概念與上位概念不能留空。")
    exact = next((a for a in doc.annotations if (a.start, a.end) == (span.start, span.end)), None)
    conflicts = [a for a in doc.annotations_in_range_for_group(span.start, span.end, group_id)
                 if a is not exact]
    if conflicts and not replace_conflicts:
        raise ValueError("術語範圍與既有同群組標註重疊。")
    for ann in conflicts:
        ann.labels.pop(group_id)
        if not ann.labels:
            doc.remove_annotation(ann.id)
    cid = _concept_id(doc, name)
    parent_id = _concept_id(doc, broader)
    ann = exact or Annotation(span.start, span.end)
    ann.labels[group_id] = label_id
    ann.concept_id = cid
    ann.broader_concept_id = parent_id
    if ann.explanation_start is None or ann.explanation_end is None:
        ann.explanation_start, ann.explanation_end = span.start, span.end
    if exact is None:
        doc.add_annotation(ann)
    doc.dirty = True
    if not auto_match:
        return AnnotationResult(ann)
    created, skipped = _add_matches(doc, ann, group_id)
    return AnnotationResult(ann, created, skipped)


def _add_matches(doc: Document, source: Annotation, group_id: str) -> tuple[int, int]:
    term = doc.text[source.start:source.end]
    position = doc.text.find(term)
    created = skipped = 0
    while position >= 0:
        end = position + len(term)
        overlaps = doc.annotations_in_range_for_group(position, end, group_id)
        if not overlaps:
            doc.add_annotation(Annotation(
                position, end, {group_id: source.labels[group_id]}, concept_id=source.concept_id,
                broader_concept_id=source.broader_concept_id,
                explanation_start=position, explanation_end=end,
            ))
            created += 1
        elif not any(a.start == position and a.end == end for a in overlaps):
            skipped += 1
        position = doc.text.find(term, position + 1)
    return created, skipped


def set_explanation(doc: Document, annotation_id: str, span: TextSpan) -> None:
    span.validate(doc.text)
    ann = doc.find_annotation(annotation_id)
    if ann is None:
        raise ValueError("請先點選要設定解釋的術語。")
    ann.explanation_start, ann.explanation_end = span.start, span.end
    doc.dirty = True


def validate_term_annotations(doc: Document) -> None:
    """Reject incomplete formal saves, while allowing incomplete crash backups."""
    problems = []
    for ann in doc.annotations:
        try:
            TextSpan(ann.start, ann.end).validate(doc.text)
            TextSpan(ann.explanation_start, ann.explanation_end).validate(doc.text)
            if not ann.labels:
                raise ValueError("缺少標籤")
            if not doc.concepts.get(ann.concept_id, "").strip():
                raise ValueError("缺少對應概念")
            if not doc.concepts.get(ann.broader_concept_id, "").strip():
                raise ValueError("缺少上位概念")
        except ValueError as error:
            problems.append(f"{ann.start}-{ann.end}：{error}")
    if problems:
        raise ValueError("以下標註尚未完整，請點選術語補齊概念與解釋後再儲存：\n" + "\n".join(problems[:12]))
