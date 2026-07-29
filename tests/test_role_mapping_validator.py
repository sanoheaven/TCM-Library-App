import importlib.util
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "validate_render_role_mapping.py"
SPEC = importlib.util.spec_from_file_location("role_mapping_validator", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def item(page, line, text, role, block_id=None):
    return {
        "pdf_page": page,
        "line_number": line,
        "text": text,
        "role": role,
        "block_id": block_id,
        "role_evidence": {"basis": "text", "note": "test"},
    }


class RoleMappingValidatorTests(unittest.TestCase):
    def test_marked_commentary_blocks_are_canonicalized_separately(self):
        expected = [
            {"pdf_page": 1, "line_number": 1, "text": "【评讲】甲"},
            {"pdf_page": 1, "line_number": 2, "text": "正文"},
            {"pdf_page": 1, "line_number": 3, "text": "【评讲】乙"},
        ]
        mappings = [
            item(1, 1, "【评讲】甲", "commentary", "reused"),
            item(1, 2, "正文", "body"),
            item(1, 3, "【评讲】乙", "commentary", "reused"),
        ]
        canonical, errors, warnings = MODULE.canonicalize(expected, mappings)
        self.assertEqual([], errors)
        self.assertEqual("commentary_1_1", canonical[0]["block_id"])
        self.assertEqual("commentary_1_3", canonical[2]["block_id"])
        self.assertTrue(any("model_block_id_reused" in warning for warning in warnings))

    def test_numbered_appendix_entries_become_formula(self):
        mappings = [
            item(1, 1, "附方", "title"),
            item(1, 2, "（1）方甲：药甲", "commentary", "wrong"),
            item(1, 3, "（2）方乙：药乙", "commentary", "wrong"),
            item(1, 4, "12", "excluded"),
            item(2, 1, "（3）方丙：药丙", "commentary", "wrong"),
            item(2, 2, "新标题", "title"),
        ]
        warnings = MODULE.normalize_formula_roles(mappings)
        self.assertEqual(["formula", "formula", "formula"], [mappings[1]["role"], mappings[2]["role"], mappings[4]["role"]])
        self.assertEqual(3, len(warnings))

    def test_cross_page_commentary_ignores_page_furniture(self):
        mappings = [
            item(1, 1, "续评", "commentary", "block_1"),
            item(1, 2, "1", "excluded"),
            item(1, 3, "页眉", "title"),
            item(2, 1, "2", "excluded"),
            item(2, 2, "页眉", "title"),
            item(2, 3, "续评", "commentary", "block_1"),
        ]
        self.assertEqual(1, MODULE.count_cross_page_commentary(mappings))

    def test_canonicalize_continues_across_page_furniture(self):
        expected = [
            {"pdf_page": 1, "line_number": 1, "text": "【评讲】甲"},
            {"pdf_page": 2, "line_number": 1, "text": "2"},
            {"pdf_page": 2, "line_number": 2, "text": "页眉"},
            {"pdf_page": 2, "line_number": 3, "text": "续评"},
        ]
        mappings = [
            item(1, 1, "【评讲】甲", "commentary", "a"),
            item(2, 1, "2", "excluded"),
            item(2, 2, "页眉", "title"),
            item(2, 3, "续评", "commentary", "a"),
        ]
        canonical, errors, warnings = MODULE.canonicalize(expected, mappings)
        self.assertEqual([], errors)
        self.assertEqual("commentary_1_1", canonical[-1]["block_id"])
        self.assertIn("cross_page_commentary_without_marker at 2/3", warnings)

    def test_total_commentary_marker_starts_a_new_block(self):
        expected = [{"pdf_page": 1, "line_number": 1, "text": "【总评讲】甲"}]
        canonical, errors, _ = MODULE.canonicalize(expected, [item(1, 1, "【总评讲】甲", "commentary", "old")])
        self.assertEqual([], errors)
        self.assertEqual("commentary_1_1", canonical[0]["block_id"])

    def test_word_candidate_is_review_only_and_cannot_claim_a_pdf_page(self):
        expected = [{"pdf_page": 1, "line_number": 1, "text": "茯苓桂枝"}]
        mapping = item(1, 1, "茯苓桂枝", "formula")
        mapping["word_candidate_text"] = "茯苓 桂枝"
        canonical, errors, warnings = MODULE.canonicalize(expected, [mapping])
        self.assertEqual([], errors)
        self.assertEqual("茯苓桂枝", canonical[0]["text"])
        self.assertIn("word_candidate_requires_page_review at 1/1", warnings)

        mapping["word_pdf_page"] = 1
        _, errors, _ = MODULE.canonicalize(expected, [mapping])
        self.assertIn("word_pdf_page_anchor_forbidden at 1/1", errors)

    def test_diagram_can_have_one_manual_rendering_with_all_source_lines_audited(self):
        mappings = [
            item(1, 1, "鉴别", "diagram"),
            item(1, 2, "虚热", "diagram"),
        ]
        for mapping in mappings:
            mapping["diagram_group"] = "d1"
        mappings[0]["derived_text"] = "鉴别：虚热。"
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "out.md"
            MODULE.render(output, mappings, 1, 1, "hash", "test")
            rendered = output.read_text(encoding="utf-8")
        self.assertEqual(1, rendered.count("图示人工转写"))
        self.assertIn("ocr_line=1", rendered)
        self.assertIn("ocr_line=2", rendered)


if __name__ == "__main__":
    unittest.main()
