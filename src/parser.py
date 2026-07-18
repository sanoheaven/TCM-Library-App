"""PDF page-level extraction for review, not for authoritative interpretation."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pdfplumber


PIPELINE_VERSION = "2.0"
CITATION_RE = re.compile(r"[\[［]([0-9０-９]+(?:\s*[-,，－]\s*[0-9０-９]+)*)[\]］]")
TABLE_LABEL_RE = re.compile(r"(?:表|Table)\s*([0-9０-９]+)", re.IGNORECASE)
MIN_MEANINGFUL_TEXT_CHARS = 30


def extract_citation_markers(text: str) -> list[str]:
    """Return original bracketed numeric citation markers without resolving them."""

    return [match.group(0) for match in CITATION_RE.finditer(text)]


def extract_table_labels(text: str) -> list[str]:
    """Find table labels even when raster tables cannot be reconstructed."""

    return [match.group(0) for match in TABLE_LABEL_RE.finditer(text)]


def _table_candidates(page: pdfplumber.page.Page) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    try:
        tables = page.find_tables()
    except Exception as exc:  # A table-detection failure must remain visible.
        return [{"warning": f"table_detection_failed: {exc}"}]

    for number, table in enumerate(tables, start=1):
        rows = table.extract() or []
        candidates.append(
            {
                "number": number,
                "bbox": [round(value, 2) for value in table.bbox],
                "rows": rows,
                "row_count": len(rows),
                "column_count": max((len(row or []) for row in rows), default=0),
                "review_required": True,
            }
        )
    return candidates


def _image_summary(page: pdfplumber.page.Page) -> dict[str, Any]:
    """Separate page-sized scan backgrounds from likely visual figures."""

    page_area = page.width * page.height
    full_page_rasters = 0
    figure_candidates = 0
    image_candidates: list[dict[str, Any]] = []
    for ordinal, image in enumerate(page.images or [], start=1):
        image_area = float(image.get("width", 0)) * float(image.get("height", 0))
        bbox = [
            round(float(image.get("x0", 0)), 2),
            round(float(image.get("top", 0)), 2),
            round(float(image.get("x1", 0)), 2),
            round(float(image.get("bottom", 0)), 2),
        ]
        if page_area and image_area / page_area >= 0.75:
            full_page_rasters += 1
            image_kind = "full_page_raster"
        else:
            figure_candidates += 1
            image_kind = "embedded_figure_candidate"
        image_candidates.append({"ordinal": ordinal, "bbox": bbox, "kind": image_kind})
    return {
        "image_object_count": len(page.images or []),
        "full_page_raster_count": full_page_rasters,
        "figure_candidate_count": figure_candidates,
        "image_candidates": image_candidates,
    }


def _page_warnings(text: str, tables: list[dict[str, Any]], image_summary: dict[str, int]) -> list[str]:
    warnings: list[str] = []
    table_labels = extract_table_labels(text)
    if not text.strip():
        warnings.append("no_extractable_text_possible_scan_or_layout_issue")
    elif len(text.strip()) < MIN_MEANINGFUL_TEXT_CHARS:
        warnings.append("low_text_density_possible_blank_or_scan")
    if image_summary["full_page_raster_count"]:
        warnings.append("full_page_raster_layout_requires_visual_review")
    if tables:
        warnings.append("table_candidates_require_human_review")
    elif table_labels:
        warnings.append("table_labels_detected_but_no_structured_table_extracted")
    if image_summary["figure_candidate_count"]:
        warnings.append("image_or_figure_candidates_require_human_review")
    for table in tables:
        if "warning" in table:
            warnings.append(table["warning"])
    return warnings


def extract_document(pdf_path: Path) -> dict[str, Any]:
    """Extract each page independently and retain all quality warnings."""

    pages: list[dict[str, Any]] = []
    document_warnings: list[str] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            tables = _table_candidates(page)
            image_summary = _image_summary(page)
            warnings = _page_warnings(text, tables, image_summary)

            pages.append(
                {
                    "page_number": page_number,
                    "text": text,
                    "character_count": len(text),
                    "citation_markers": extract_citation_markers(text),
                    "table_labels": extract_table_labels(text),
                    "tables": tables,
                    **image_summary,
                    "warnings": warnings,
                }
            )

    if not pages:
        document_warnings.append("pdf_has_no_pages")
    if any("no_extractable_text_possible_scan_or_layout_issue" in page["warnings"] for page in pages):
        document_warnings.append("one_or_more_pages_need_ocr_or_manual_review")

    return {
        "pipeline_version": PIPELINE_VERSION,
        "source_pdf": str(pdf_path),
        "page_count": len(pages),
        "pages": pages,
        "warnings": document_warnings,
    }
