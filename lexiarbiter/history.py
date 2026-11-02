"""Document edit history; original text and file paths stay outside undo state."""

from copy import deepcopy
from dataclasses import dataclass
from typing import Callable

from PySide6.QtGui import QUndoCommand

from .core.models import Annotation, Document


@dataclass
class EditSnapshot:
    annotations: list[Annotation]
    concepts: dict[str, str]
    active_annotation_id: str | None

    @classmethod
    def capture(cls, doc: Document, active_annotation_id: str | None):
        return cls(deepcopy(doc.annotations), dict(doc.concepts), active_annotation_id)

    def restore(self, doc: Document) -> None:
        doc.annotations = deepcopy(self.annotations)
        doc.concepts = dict(self.concepts)

    def same_content(self, other: "EditSnapshot") -> bool:
        return self.annotations == other.annotations and self.concepts == other.concepts


class EditCommand(QUndoCommand):
    def __init__(self, title: str, before: EditSnapshot, after: EditSnapshot,
                 apply: Callable[[EditSnapshot], None]):
        super().__init__(title)
        self._before = before
        self._after = after
        self._apply = apply

    def undo(self):
        self._apply(self._before)

    def redo(self):
        self._apply(self._after)
