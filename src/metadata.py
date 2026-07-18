"""Persistent metadata for the review pipeline."""

from __future__ import annotations

import hashlib
import json
import re
from difflib import SequenceMatcher
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


LIBRARY_ROOT = Path(r"D:\TCM-Library")
METADATA_DIR = LIBRARY_ROOT / "11_Metadata"
DB_FILE = METADATA_DIR / "library.json"

TYPE_BY_PARENT = {
    "03_Books": "BOK",
    "04_Dissertation": "DIS",
    "05_Journal": "JRN",
    "06_Conference": "CNF",
    "07_Course": "CRS",
}
TYPE_BY_FILENAME_LABEL = {
    "硕士论文": "DIS",
    "博士论文": "DIS",
    "学位论文": "DIS",
    "期刊": "JRN",
    "专利": "PAT",
    "会议": "CNF",
    "课程": "CRS",
    "讲义": "CRS",
    "图书": "BOK",
    "专著": "BOK",
    "标准": "STD",
    "指南": "STD",
    "报告": "RPT",
}
VALID_SOURCE_TYPES = frozenset({"BOK", "CHP", "DIS", "JRN", "CNF", "CRS", "PAT", "RPT", "STD", "WEB", "VID", "OTH"})
SOURCE_PDF_DIRS = ("02_PDF", "03_Books", "04_Dissertation", "05_Journal", "06_Conference", "07_Course")


def load_database() -> dict[str, Any]:
    if not DB_FILE.exists():
        return {}
    content = DB_FILE.read_text(encoding="utf-8").strip()
    return json.loads(content) if content else {}


def save_database(database: dict[str, Any]) -> None:
    METADATA_DIR.mkdir(parents=True, exist_ok=True)
    DB_FILE.write_text(json.dumps(database, ensure_ascii=False, indent=2), encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_exact_duplicates(
    pdf_path: Path,
    search_roots: Iterable[Path] | None = None,
) -> list[Path]:
    """Find same-content PDFs by size then SHA-256; filenames are not trusted."""

    resolved = pdf_path.resolve()
    target_size = pdf_path.stat().st_size
    target_hash = sha256_file(pdf_path)
    roots = list(search_roots) if search_roots is not None else [LIBRARY_ROOT / name for name in SOURCE_PDF_DIRS]
    duplicates: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for candidate in root.rglob("*.pdf"):
            if candidate.resolve() == resolved or candidate.stat().st_size != target_size:
                continue
            if sha256_file(candidate) == target_hash:
                duplicates.append(candidate)
    return duplicates


def _bibliographic_key(pdf_path: Path) -> tuple[str, str, str]:
    """Build a conservative comparison key from the agreed intake filename."""

    parts = [part.strip() for part in pdf_path.stem.split("_") if part.strip()]
    year = parts[0] if parts and re.fullmatch(r"(?:19|20)\d{2}", parts[0]) else ""
    author = parts[1] if len(parts) > 1 else ""
    title_parts = parts[2:]
    if title_parts and title_parts[-1].lower().startswith("v"):
        title_parts.pop()
    title_parts = [
        part
        for part in title_parts
        if part not in {"期刊", "硕士论文", "博士论文", "专利", "会议", "课程", "标准", "报告"}
    ]
    title = "".join(title_parts)
    title = re.sub(r"(?:高清扫描版|扫描版|高清版|OCR版|OCR|副本|下载版|最终版|修订版|\[[^\]]*\]|【[^】]*】)", "", title, flags=re.IGNORECASE)
    title = re.sub(r"[^\w\u4e00-\u9fff]", "", title).lower()
    return year, author, title


def find_near_duplicates(
    pdf_path: Path,
    search_roots: Iterable[Path] | None = None,
) -> list[dict[str, str]]:
    """Return conservative same-work candidates; never treat them as exact duplicates."""

    resolved = pdf_path.resolve()
    year, author, title = _bibliographic_key(pdf_path)
    if not year or not author or len(title) < 4:
        return []

    roots = list(search_roots) if search_roots is not None else [LIBRARY_ROOT / name for name in SOURCE_PDF_DIRS]
    matches: list[dict[str, str]] = []
    for root in roots:
        if not root.exists():
            continue
        for candidate in root.rglob("*.pdf"):
            if candidate.resolve() == resolved:
                continue
            candidate_year, candidate_author, candidate_title = _bibliographic_key(candidate)
            if (candidate_year, candidate_author) != (year, author) or not candidate_title:
                continue
            similarity = SequenceMatcher(None, title, candidate_title).ratio()
            if title == candidate_title or similarity >= 0.93:
                matches.append(
                    {
                        "path": str(candidate),
                        "reason": "same_normalized_bibliographic_key" if title == candidate_title else "high_title_similarity",
                        "similarity": f"{similarity:.3f}",
                    }
                )
    return matches


def infer_source_type(pdf_path: Path, requested_type: str | None = None) -> str:
    if requested_type:
        source_type = requested_type.upper()
        if source_type not in VALID_SOURCE_TYPES:
            raise ValueError(f"Unsupported source type: {source_type}")
        return source_type
    return TYPE_BY_PARENT.get(pdf_path.parent.name, "OTH")


def infer_filename_source_type(pdf_path: Path) -> str | None:
    """Use an explicit filename carrier label as a safety check, never as a silent override."""

    for label, source_type in TYPE_BY_FILENAME_LABEL.items():
        if label in pdf_path.stem:
            return source_type
    return None


def validate_requested_source_type(pdf_path: Path, requested_type: str) -> None:
    filename_type = infer_filename_source_type(pdf_path)
    if filename_type and filename_type != requested_type.upper():
        raise ValueError(
            f"Filename indicates {filename_type}, but requested source type is {requested_type.upper()}: {pdf_path.name}"
        )


def filename_warnings(pdf_path: Path) -> list[str]:
    warnings: list[str] = []
    if not re.search(r"_v\d{2}\.pdf$", pdf_path.name, flags=re.IGNORECASE):
        warnings.append("filename_version_suffix_should_be_vNN")
    return warnings


def infer_year(filename: str) -> str:
    match = re.search(r"(?:19|20)\d{2}", filename)
    return match.group(0) if match else "UNK"


def get_or_assign_document_id(pdf_path: Path, source_type: str | None = None) -> str:
    database = load_database()
    key = str(pdf_path.resolve())
    existing_record = database.get(key, {})
    if existing_record and not existing_record.get("document_id"):
        raise ValueError(
            "Legacy metadata record found for this PDF. Review or migrate it before running the v2 pipeline: "
            f"{pdf_path}"
        )
    existing = existing_record.get("document_id")
    if existing:
        return existing

    year = infer_year(pdf_path.name)
    kind = infer_source_type(pdf_path, source_type)
    prefix = f"TCM-{year}-{kind}-"
    used = [
        value.get("document_id", "")
        for value in database.values()
        if value.get("document_id", "").startswith(prefix)
    ]
    sequence = max((int(value.rsplit("-", 1)[-1]) for value in used), default=0) + 1
    return f"{prefix}{sequence:04d}"


def reclassify_document(pdf_path: Path, source_type: str) -> tuple[str, str, Path]:
    """Correct an intake classification before any knowledge use; preserve the review package."""

    database = load_database()
    key = str(pdf_path.resolve())
    record = database.get(key)
    if not record:
        raise KeyError(f"No registered document found for: {pdf_path}")

    old_id = record["document_id"]
    new_type = infer_source_type(pdf_path, source_type)
    if record["source_type"] == new_type:
        return old_id, old_id, Path(record["markdown_dir"])

    year = infer_year(pdf_path.name)
    prefix = f"TCM-{year}-{new_type}-"
    used = [
        value.get("document_id", "")
        for value in database.values()
        if value.get("document_id", "").startswith(prefix)
    ]
    sequence = max((int(value.rsplit("-", 1)[-1]) for value in used), default=0) + 1
    new_id = f"{prefix}{sequence:04d}"

    old_output = Path(record["markdown_dir"])
    new_output = old_output.parent / new_id
    old_manifest = METADATA_DIR / f"{old_id}.manifest.json"
    new_manifest = METADATA_DIR / f"{new_id}.manifest.json"
    if new_output.exists() or new_manifest.exists():
        raise FileExistsError(f"Refusing to overwrite existing document ID: {new_id}")

    old_output.rename(new_output)
    manifest = json.loads(old_manifest.read_text(encoding="utf-8"))
    manifest["document_id"] = new_id
    manifest["source_type"] = new_type
    new_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    old_manifest.unlink()

    document_path = new_output / "document.md"
    document_content = document_path.read_text(encoding="utf-8")
    document_content = document_content.replace(
        f'document_id: "{old_id}"', f'document_id: "{new_id}"', 1
    ).replace(
        f'source_type: "{record["source_type"]}"', f'source_type: "{new_type}"', 1
    ).replace(f"<!-- source: {old_id} |", f"<!-- source: {new_id} |")
    document_path.write_text(document_content, encoding="utf-8")

    report_path = new_output / "conversion-report.md"
    report_path.write_text(
        report_path.read_text(encoding="utf-8").replace(old_id, new_id), encoding="utf-8"
    )

    record["document_id"] = new_id
    record["source_type"] = new_type
    record["markdown_dir"] = str(new_output)
    database[key] = record
    save_database(database)
    return old_id, new_id, new_output


def update_record(
    pdf_path: Path,
    document_id: str,
    source_type: str,
    output_dir: Path,
    extraction: dict[str, Any],
    duplicate_review: dict[str, Any] | None = None,
) -> None:
    database = load_database()
    key = str(pdf_path.resolve())
    page_warnings = [warning for page in extraction["pages"] for warning in page["warnings"]]
    status = "needs_review" if extraction["warnings"] or page_warnings else "extracted"
    database[key] = {
        "record_format": "review_pipeline_v2",
        "document_id": document_id,
        "filename": pdf_path.name,
        "pdf_path": str(pdf_path),
        "source_type": source_type,
        "sha256": sha256_file(pdf_path),
        "markdown_dir": str(output_dir),
        "status": status,
        "pipeline_version": extraction["pipeline_version"],
        "page_count": extraction["page_count"],
        "warnings": extraction["warnings"] + page_warnings,
        "processed_at": datetime.now(timezone.utc).isoformat(),
    }
    if duplicate_review:
        database[key]["duplicate_review"] = duplicate_review
    save_database(database)
