"""Acceptance cases from the supplied annotation worksheet and edge cases."""

import json
from dataclasses import fields
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from lexiarbiter.core.annotations import TextSpan, record_term, set_explanation
from lexiarbiter.core.config import load_annotation_mode
from lexiarbiter.core.io import export_txt, load_docx, load_lexa, save_lexa
from lexiarbiter.core.models import Annotation, Document


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"
MODE = load_annotation_mode(ROOT / "configs/annotation_modes/term_definition.json")


class AnnotationTests(unittest.TestCase):
    def test_docx_and_eleven_annotations_match_reference_by_concept_name(self):
        doc = load_docx(FIXTURES / "test_example.docx")
        reference = load_lexa(FIXTURES / "test_example.lexa")
        self.assertEqual(doc.text, reference.text)
        self.assertEqual(len(doc.text), 1209)
        for expected in reference.annotations:
            result = record_term(
                doc, TextSpan(expected.start, expected.end),
                reference.concepts[expected.concept_id],
                reference.concepts[expected.broader_concept_id], auto_match=False,
            )
            set_explanation(doc, result.annotation.id,
                            TextSpan(expected.explanation_start, expected.explanation_end))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "result.lexa"
            save_lexa(doc, path, MODE)
            actual = load_lexa(path)
        self.assertEqual(len(actual.annotations), 11)
        self.assertEqual(len(actual.concepts), 6)
        for expected, found in zip(reference.sorted_annotations(), actual.sorted_annotations()):
            for key in ("start", "end", "explanation_start", "explanation_end", "labels", "note"):
                self.assertEqual(getattr(found, key), getattr(expected, key), key)
            for key in ("concept_id", "broader_concept_id"):
                self.assertEqual(actual.concepts[getattr(found, key)],
                                 reference.concepts[getattr(expected, key)])

    def test_automatic_occurrences_have_own_explanation_and_shared_concepts(self):
        doc = Document("債之關係，債之關係。債之關係")
        result = record_term(doc, TextSpan(0, 4), "債", "法律關係")
        self.assertEqual(result.auto_created, 2)
        self.assertEqual(len(doc.annotations), 3)
        for ann in doc.annotations:
            self.assertEqual((ann.explanation_start, ann.explanation_end), (ann.start, ann.end))
            self.assertEqual(doc.concepts[ann.concept_id], "債")
            self.assertEqual(doc.concepts[ann.broader_concept_id], "法律關係")
        set_explanation(doc, result.annotation.id, TextSpan(5, 9))
        self.assertEqual(doc.annotations[1].explanation_start, 5)
        record_term(doc, TextSpan(0, 4), "債", "法律關係")
        self.assertEqual(len(doc.annotations), 3)
        self.assertEqual(result.annotation.explanation_start, 5)

    def test_long_and_short_terms_skip_conflicts_without_overwriting(self):
        doc = Document("損害賠償責任，損害賠償，損害賠償責任")
        record_term(doc, TextSpan(0, 6), "損害賠償責任", auto_match=False)
        result = record_term(doc, TextSpan(7, 11), "損害賠償")
        self.assertEqual(result.auto_created, 1)
        self.assertEqual(result.skipped, 1)
        self.assertEqual([(a.start, a.end) for a in doc.sorted_annotations()], [(0, 6), (7, 11), (12, 16)])
        with self.assertRaises(ValueError):
            record_term(doc, TextSpan(12, 18), "損害賠償責任")
        record_term(doc, TextSpan(12, 18), "損害賠償責任", replace_conflicts=True)
        self.assertEqual(doc.sorted_annotations()[-1].end, 18)

    def test_overlapping_literal_matches_choose_first_available_range(self):
        doc = Document("aaaaa")
        record_term(doc, TextSpan(1, 3), "aa")
        self.assertEqual([(a.start, a.end) for a in doc.sorted_annotations()], [(1, 3), (3, 5)])

    def test_overlap_filter_uses_half_open_ranges_and_group(self):
        a = Annotation(2, 6, {"entity": "term"})
        doc = Document("0123456789", [a, Annotation(3, 5, {"other": "x"})])
        self.assertEqual(doc.annotations_in_range_for_group(4, 8, "entity"), [a])
        self.assertEqual(doc.annotations_in_range_for_group(6, 8, "entity"), [])
        self.assertEqual(doc.annotations_in_range_for_group(4, 4, "entity"), [])

    def test_invalid_input_does_not_create_orphan_concepts(self):
        doc = Document("文字", [Annotation(0, 2, {"entity": "term"})])
        for span, name in [(TextSpan(0, 3), "新概念"), (TextSpan(0, 1), " ")]:
            with self.assertRaises(ValueError):
                record_term(doc, span, name)
        self.assertEqual(doc.concepts, {})
        self.assertFalse(doc.dirty)

    def test_formal_save_rejects_missing_required_fields_but_backup_keeps_draft(self):
        doc = Document("術語", [Annotation(0, 2, {"entity": "term"})])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "result.lexa"
            with self.assertRaises(ValueError):
                save_lexa(doc, path, MODE)
            self.assertFalse(path.exists())
            save_lexa(doc, path, MODE, update_doc_state=False)
            self.assertEqual(len(load_lexa(path).annotations), 1)

    def test_export_does_not_leak_concept_to_unrelated_spans(self):
        doc = Document("空白甲乙丙", [Annotation(2, 3, {"entity": "term"}, concept_id="c"),
                                  Annotation(4, 5, {"entity": "term"})], concepts={"c": "概念甲"})
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "result.txt"
            export_txt(doc, path, MODE)
            text = path.read_text(encoding="utf-8")
        self.assertIn("<P>Term=概念甲|甲</P>", text)
        self.assertIn("<P>Term|丙</P>", text)

    def test_original_model_fields_are_unchanged(self):
        expected = json.loads((FIXTURES / "test_example.lexa").read_text(encoding="utf-8"))
        self.assertEqual({f.name for f in fields(Annotation)}, set(expected["annotations"][0]))
        self.assertEqual({f.name for f in fields(Document)},
                         {"text", "annotations", "schema_id", "source_filename", "source_meta",
                          "concepts", "file_path", "dirty"})

    def test_failed_atomic_save_keeps_original_and_dirty_state(self):
        doc = Document("術語")
        record_term(doc, TextSpan(0, 2), "術語")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "result.lexa"
            path.write_text("original", encoding="utf-8")
            with patch("lexiarbiter.core.io.os.replace", side_effect=OSError("disk unavailable")):
                with self.assertRaises(OSError):
                    save_lexa(doc, path, MODE)
            self.assertEqual(path.read_text(encoding="utf-8"), "original")
            self.assertEqual(list(Path(folder).iterdir()), [path])
            self.assertTrue(doc.dirty)

    def test_automatic_matching_does_not_copy_unrelated_group(self):
        doc = Document("甲甲", [Annotation(0, 1, {"other": "x"})])
        record_term(doc, TextSpan(0, 1), "甲")
        self.assertEqual(doc.annotations[-1].labels, {"entity": "term"})


if __name__ == "__main__":
    unittest.main()
