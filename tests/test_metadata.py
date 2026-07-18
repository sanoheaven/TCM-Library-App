import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import metadata
from metadata import filename_warnings, find_exact_duplicates, find_near_duplicates, get_or_assign_document_id, infer_source_type, infer_year, validate_requested_source_type


class MetadataTests(unittest.TestCase):
    def test_infers_year_from_filename(self):
        self.assertEqual(infer_year("2024_王瑞_舌诊研究.pdf"), "2024")

    def test_uses_parent_directory_for_known_type(self):
        path = Path(r"D:\TCM-Library\05_Journal\2024_测试.pdf")
        self.assertEqual(infer_source_type(path), "JRN")

    def test_defaults_unclassified_files_to_other(self):
        path = Path(r"D:\TCM-Library\02_PDF\待分类.pdf")
        self.assertEqual(infer_source_type(path), "OTH")

    def test_rejects_unknown_explicit_source_type(self):
        path = Path(r"D:\TCM-Library\02_PDF\待分类.pdf")
        with self.assertRaises(ValueError):
                infer_source_type(path, "NOT_A_TYPE")

    def test_rejects_a_type_that_conflicts_with_the_filename_label(self):
        path = Path(r"D:\TCM-Library\02_PDF\2017_王彦晖_舌象图像分割方法_专利_v01.pdf")
        with self.assertRaisesRegex(ValueError, "Filename indicates PAT"):
            validate_requested_source_type(path, "JRN")

    def test_flags_nonstandard_version_suffix_without_blocking_intake(self):
        path = Path(r"D:\TCM-Library\02_PDF\2017_王彦晖_舌象图像分割方法_专利_vo1.pdf")
        self.assertEqual(filename_warnings(path), ["filename_version_suffix_should_be_vNN"])

    def test_finds_same_content_with_a_different_filename(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            first = root / "first.pdf"
            duplicate = root / "renamed.pdf"
            first.write_bytes(b"same PDF bytes")
            duplicate.write_bytes(b"same PDF bytes")
            self.assertEqual(find_exact_duplicates(first, [root]), [duplicate])

    def test_flags_same_work_with_a_different_version_name(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            first = root / "2020_王彦晖_舌诊研究_期刊_v01.pdf"
            revised = root / "2020_王彦晖_舌诊研究_期刊_高清扫描版_v02.pdf"
            first.write_bytes(b"first version")
            revised.write_bytes(b"revised version")
            matches = find_near_duplicates(first, [root])
            self.assertEqual(matches[0]["path"], str(revised))
            self.assertEqual(matches[0]["reason"], "same_normalized_bibliographic_key")

    def test_refuses_to_overwrite_a_legacy_metadata_record(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            temporary_db = Path(temporary_dir) / "library.json"
            target = Path(r"D:\TCM-Library\02_PDF\legacy_record_test.pdf")
            temporary_db.write_text(
                '{"' + str(target.resolve()).replace("\\", "\\\\") + '": {"status": "completed"}}',
                encoding="utf-8",
            )
            with patch.object(metadata, "DB_FILE", temporary_db):
                with self.assertRaisesRegex(ValueError, "Legacy metadata record"):
                    get_or_assign_document_id(target, "BOK")


if __name__ == "__main__":
    unittest.main()
