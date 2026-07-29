import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "preprocess_structure_candidates.py"
SPEC = importlib.util.spec_from_file_location("structure_preprocessor", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def line(number, text):
    return {"line_number": number, "text": text}


class StructurePreprocessorTests(unittest.TestCase):
    def test_detects_non_binding_structural_candidates(self):
        page = {"page_number": 1, "lines": [
            line(1, "【评讲】说明"),
            line(2, "附方"),
            line(3, "（1）方名"),
            line(4, "12"),
        ]}
        found = {entry["line_number"]: entry["candidates"] for entry in MODULE.detect(page)}
        self.assertIn("commentary_start", found[1])
        self.assertIn("formula_heading", found[2])
        self.assertIn("formula_item", found[3])
        self.assertIn("page_number_candidate", found[4])

    def test_split_title_and_bad_mapping_are_reported(self):
        pages = [{"page_number": 55, "lines": [line(1, "失"), line(2, "音"), line(3, "概说")]}]
        manifest = {"entries": [{"id": "loss", "title": "失音", "start_pdf": 55, "end_pdf": 57}]}
        mapping = {(55, 1): {"role": "body"}, (55, 2): {"role": "body"}}
        issues = MODULE.validate_boundaries(pages, manifest, mapping)
        rules = {issue["rule_id"] for issue in issues}
        self.assertIn("split_title_candidate", rules)
        self.assertIn("mapping_split_title_not_title", rules)

    def test_parent_header_must_be_excluded(self):
        pages = [
            {"page_number": 48, "lines": [line(1, "肺痿肺痈")]},
            {"page_number": 51, "lines": [line(1, "肺痿肺痈")]},
        ]
        manifest = {"entries": [{"id": "parent", "title": "肺痿肺痈", "start_pdf": 48, "end_pdf": 54}]}
        issues = MODULE.validate_boundaries(pages, manifest, {(51, 1): {"role": "body"}})
        self.assertIn("mapping_repeated_parent_header_not_excluded", {issue["rule_id"] for issue in issues})

    def test_parent_header_alias_must_be_excluded(self):
        pages = [
            {"page_number": 48, "lines": [line(1, "\u80ba\u75bf\u80ba\u75c8")]},
            {"page_number": 54, "lines": [line(2, "\u80ba\u75bf\u80ba\u75db")]},
        ]
        manifest = {"entries": [{"id": "parent", "title": "\u80ba\u75bf\u80ba\u75c8", "header_aliases": ["\u80ba\u75bf\u80ba\u75db"], "start_pdf": 48, "end_pdf": 54}]}
        issues = MODULE.validate_boundaries(pages, manifest, {(54, 2): {"role": "body"}})
        self.assertIn("mapping_repeated_parent_header_not_excluded", {issue["rule_id"] for issue in issues})

    def test_mid_sentence_commentary_role_break_is_error(self):
        pages = [{"page_number": 54, "lines": [line(7, "【评讲】此句尚未结束，"), line(8, "继续内容。")]}]
        mapping = {(54, 7): {"role": "commentary"}, (54, 8): {"role": "body"}}
        issues = MODULE.validate_boundaries(pages, {"entries": []}, mapping)
        self.assertIn("mapping_commentary_continuation_break", {issue["rule_id"] for issue in issues})

    def test_child_start_reports_preceding_content(self):
        pages = [{"page_number": 51, "lines": [line(1, "前一子项续文。"), line(2, "肺痈"), line(3, "病因")]}]
        manifest = {"entries": [
            {"id": "parent", "title": "肺痿肺痈", "start_pdf": 48, "end_pdf": 54},
            {"id": "child", "title": "肺痈", "parent_id": "parent", "start_pdf": 51, "end_pdf": 54},
        ]}
        issues = MODULE.validate_boundaries(pages, manifest)
        self.assertIn("pre_child_content_requires_inheritance_review", {issue["rule_id"] for issue in issues})

    def test_critical_review_requires_exact_auditable_resolution(self):
        pages = [{"page_number": 51, "lines": [line(1, "\u7ee7\u6587"), line(2, "\u80ba\u75c8")]}]
        manifest = {"entries": [{"id": "parent", "title": "\u80ba\u75bf", "start_pdf": 48, "end_pdf": 54}, {"id": "child", "title": "\u80ba\u75c8", "parent_id": "parent", "start_pdf": 51, "end_pdf": 54}]}
        issues = MODULE.validate_boundaries(pages, manifest)
        self.assertIn("unresolved_critical_review", {issue["rule_id"] for issue in issues})
        resolution = {"rule_id": "pre_child_content_requires_inheritance_review", "pdf_page": 51, "source_lines": [1], "resolution": "inherited", "evidence": "page image", "role_assertions": [{"pdf_page": 51, "line_start": 1, "line_end": 1, "role": "commentary"}]}
        mapping = {(51, 1): {"role": "commentary"}}
        resolved_issues = MODULE.validate_boundaries(pages, manifest, mapping, [resolution])
        self.assertNotIn("unresolved_critical_review", {issue["rule_id"] for issue in resolved_issues})

        bad_mapping = {(51, 1): {"role": "body"}}
        bad_issues = MODULE.validate_boundaries(pages, manifest, bad_mapping, [resolution])
        self.assertIn("unresolved_critical_review", {issue["rule_id"] for issue in bad_issues})

    def test_title_alias_is_start_page_scoped_and_requires_resolution(self):
        pages = [{"page_number": 74, "lines": [line(1, "\u52b3")]}]
        manifest = {"entries": [{"id": "labor", "title": "\u52b3\u7635", "title_aliases": [{"text": "\u52b3", "evidence": "page image"}], "start_pdf": 74, "end_pdf": 79}]}
        mapping = {(74, 1): {"role": "title"}}
        issues = MODULE.validate_boundaries(pages, manifest, mapping)
        self.assertIn("unresolved_critical_review", {issue["rule_id"] for issue in issues})
        resolution = {"rule_id": "title_alias_candidate", "pdf_page": 74, "source_lines": [1], "resolution": "accepted", "evidence": "page image"}
        issues = MODULE.validate_boundaries(pages, manifest, mapping, [resolution])
        self.assertNotIn("unresolved_critical_review", {issue["rule_id"] for issue in issues})

        wrong_role = MODULE.validate_boundaries(pages, manifest, {(74, 1): {"role": "body"}}, [resolution])
        self.assertIn("mapping_title_alias_not_title", {issue["rule_id"] for issue in wrong_role})

    def test_cross_page_commentary_break_is_error(self):
        pages = [
            {"page_number": 50, "lines": [line(37, "\u3010\u8bc4\u8bb2\u3011\u672a\u7ed3\u675f\uff0c")]},
            {"page_number": 51, "lines": [line(1, "\u7ee7\u6587")]},
        ]
        mapping = {(50, 37): {"role": "commentary"}, (51, 1): {"role": "body"}}
        issues = MODULE.validate_boundaries(pages, {"entries": []}, mapping)
        self.assertIn("mapping_cross_page_commentary_continuation_break", {issue["rule_id"] for issue in issues})

    def test_terminal_punctuation_before_closing_parenthesis_is_not_a_break(self):
        pages = [{"page_number": 1, "lines": [line(1, "\u8bc4\u8bb2\u5b8c\u3002\uff09"), line(2, "\u6b63\u6587")]}]
        mapping = {(1, 1): {"role": "commentary"}, (1, 2): {"role": "body"}}
        issues = MODULE.validate_boundaries(pages, {"entries": []}, mapping)
        self.assertNotIn("mapping_commentary_continuation_break", {issue["rule_id"] for issue in issues})

    def test_closed_parenthetical_example_is_not_extended_as_commentary(self):
        pages = [{"page_number": 1, "lines": [line(1, "\u65b9\u4f8b\uff08\u7532\u4e59\uff09"), line(2, "\u4e0b\u4e00\u8282")]}]
        mapping = {(1, 1): {"role": "commentary"}, (1, 2): {"role": "body"}}
        issues = MODULE.validate_boundaries(pages, {"entries": []}, mapping)
        self.assertNotIn("mapping_commentary_continuation_break", {issue["rule_id"] for issue in issues})


if __name__ == "__main__":
    unittest.main()
