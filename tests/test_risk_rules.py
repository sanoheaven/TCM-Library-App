import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from risk_rules import OcrLine, detect_risks


class KnownOcrErrorRecallTests(unittest.TestCase):
    """Gold cases contain OCR candidates only; the detector never edits text."""

    def test_感冒_known_error_set_has_full_recall(self):
        cases = [
            OcrLine(21, 1, "并未深人经络", 0.9916),
            OcrLine(22, 2, "肢节凌痛", 0.9808),
            OcrLine(22, 3, "鼻妞", 0.9818),
            OcrLine(23, 4, ">热与燥，辨气分证", 0.9619),
            OcrLine(23, 5, "大便或唐", 0.9661),
            OcrLine(24, 6, "银翘散（4等", 0.9157),
            OcrLine(24, 7, "若对于喉红痛、鼻等症可不行", 0.9970),
            OcrLine(24, 8, "黄连香饮：黄连一香厚朴扁豆", 0.9286),
            OcrLine(24, 9, "用黄连香饮（5之类", 0.9745),
            OcrLine(24, 10, "羌活胜湿汤：羌活独活川芎蔓荆子甘草防风薬本", 0.9621),
        ]
        flags = detect_risks(cases)
        covered = {(flag.page_number, flag.line_number) for flag in flags}
        expected = {(case.page_number, case.line_number) for case in cases}
        self.assertEqual(covered, expected)

    def test_normal_line_is_not_flagged(self):
        flags = detect_risks([OcrLine(22, 20, "感冒的一般症状，是鼻塞声重、多嚏、时流清涕。", 0.9999)])
        self.assertEqual(flags, [])

    def test_formula_name_with_one_missing_rare_character_is_flagged(self):
        flags = detect_risks([OcrLine(106, 4, "半夏米汤：半夏北米", 0.9999)])
        self.assertIn("term_near_match", {flag.rule_id for flag in flags})


if __name__ == "__main__":
    unittest.main()
