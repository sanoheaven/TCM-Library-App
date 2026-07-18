import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from parser import _image_summary, extract_citation_markers, extract_table_labels
from writer import build_tongue_asset_candidates, content_boundary_status


class CitationMarkerTests(unittest.TestCase):
    def test_keeps_original_numeric_markers(self):
        text = "研究见[1]、[2-4]、［３］，但[作者，2024]不是数字引文。"
        self.assertEqual(extract_citation_markers(text), ["[1]", "[2-4]", "［３］"])


class TableLabelTests(unittest.TestCase):
    def test_finds_table_labels_without_claiming_structured_extraction(self):
        text = "表3 病因分布，另见 Table 7 和表８。"
        self.assertEqual(extract_table_labels(text), ["表3", "Table 7", "表８"])


class ImageSummaryTests(unittest.TestCase):
    def test_separates_a_full_page_scan_from_a_figure(self):
        class Page:
            width = 100
            height = 100
            images = [
                {"width": 100, "height": 100},
                {"width": 20, "height": 30},
            ]

        self.assertEqual(
            _image_summary(Page()),
            {
                "image_object_count": 2,
                "full_page_raster_count": 1,
                "figure_candidate_count": 1,
                "image_candidates": [
                    {"ordinal": 1, "bbox": [0.0, 0.0, 0.0, 0.0], "kind": "full_page_raster"},
                    {"ordinal": 2, "bbox": [0.0, 0.0, 0.0, 0.0], "kind": "embedded_figure_candidate"},
                ],
            },
        )


class ContentBoundaryTests(unittest.TestCase):
    def test_journal_pdfs_require_article_boundary_review(self):
        self.assertEqual(content_boundary_status("JRN"), "unverified")

    def test_dissertations_are_treated_as_one_document_until_review_says_otherwise(self):
        self.assertEqual(content_boundary_status("DIS"), "whole_document_assumed")


class TongueAssetCandidateTests(unittest.TestCase):
    def test_creates_candidate_only_links_without_claiming_a_tongue_diagnosis(self):
        registry = build_tongue_asset_candidates(
            "TCM-2026-BOK-0001",
            Path(r"D:\TCM-Library\02_PDF\tongue_book.pdf"),
            [
                {
                    "page_number": 12,
                    "figure_candidate_count": 2,
                    "full_page_raster_count": 0,
                    "image_candidates": [
                        {"ordinal": 1, "bbox": [1, 2, 3, 4], "kind": "embedded_figure_candidate"},
                        {"ordinal": 2, "bbox": [5, 6, 7, 8], "kind": "embedded_figure_candidate"},
                    ],
                }
            ],
        )
        self.assertEqual(registry["status"], "candidate_only")
        self.assertEqual(len(registry["candidate_images"]), 2)
        self.assertIsNone(registry["candidate_images"][0]["source_description_quote"])

    def test_marks_full_page_scans_for_visual_triage_without_calling_them_tongue_images(self):
        registry = build_tongue_asset_candidates(
            "TCM-2026-BOK-0001",
            Path(r"D:\TCM-Library\02_PDF\tongue_book.pdf"),
            [{"page_number": 8, "figure_candidate_count": 0, "full_page_raster_count": 1}],
        )
        candidate = registry["candidate_images"][0]
        self.assertEqual(candidate["candidate_status"], "needs_visual_triage")
        self.assertEqual(candidate["candidate_kind"], "full_page_scan_visual_triage")


if __name__ == "__main__":
    unittest.main()
