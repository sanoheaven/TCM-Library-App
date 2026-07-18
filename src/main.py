"""Safe entry point for small-batch PDF review packages."""

from __future__ import annotations

import argparse
from pathlib import Path

from metadata import (
    VALID_SOURCE_TYPES,
    find_exact_duplicates,
    find_near_duplicates,
    get_or_assign_document_id,
    infer_source_type,
    reclassify_document,
    update_record,
    filename_warnings,
    validate_requested_source_type,
)
from parser import extract_document
from writer import write_review_package


DEFAULT_INPUT_DIR = Path(r"D:\TCM-Library\02_PDF")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create review packages for a small PDF sample.")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--pdf", type=Path, help="Process one explicit PDF path.")
    parser.add_argument(
        "--source-type",
        required=True,
        choices=sorted(VALID_SOURCE_TYPES),
        help="Required source type, for example JRN or DIS.",
    )
    parser.add_argument("--limit", type=int, default=1, help="Maximum PDFs to process (default: 1).")
    parser.add_argument("--dry-run", action="store_true", help="List selected PDFs without writing outputs.")
    parser.add_argument("--batch", action="store_true", help="Explicitly allow processing the selected input-directory sample.")
    parser.add_argument(
        "--confirm-near-duplicate",
        metavar="REASON",
        help="Required human decision note to process a similar-but-not-identical PDF.",
    )
    parser.add_argument("--reclassify", action="store_true", help="Correct an existing review package's source type and ID.")
    return parser.parse_args()


def select_pdfs(args: argparse.Namespace) -> list[Path]:
    if args.pdf:
        return [args.pdf]
    return sorted(args.input_dir.glob("*.pdf"))[: args.limit]


def process_pdf(pdf_path: Path, source_type: str | None, duplicate_review: dict[str, str] | None = None) -> Path:
    if not pdf_path.exists() or pdf_path.suffix.lower() != ".pdf":
        raise FileNotFoundError(f"Not a readable PDF: {pdf_path}")

    kind = infer_source_type(pdf_path, source_type)
    validate_requested_source_type(pdf_path, kind)
    document_id = get_or_assign_document_id(pdf_path, kind)
    extraction = extract_document(pdf_path)
    extraction["warnings"].extend(filename_warnings(pdf_path))
    output_dir = write_review_package(pdf_path, document_id, kind, extraction)
    update_record(pdf_path, document_id, kind, output_dir, extraction, duplicate_review)
    return output_dir


def main() -> None:
    args = parse_args()
    if args.reclassify:
        if not args.pdf:
            raise SystemExit("--reclassify requires --pdf and --source-type")
        old_id, new_id, output_dir = reclassify_document(args.pdf, args.source_type)
        print(f"Reclassified {old_id} -> {new_id}: {output_dir}")
        return

    pdfs = select_pdfs(args)
    if not pdfs:
        print(f"No PDFs found in: {args.input_dir}")
        return

    if not args.pdf and not args.dry_run and not args.batch:
        raise SystemExit("Refusing directory conversion without --batch. Use --dry-run first, then pass --pdf for each approved file or --batch explicitly.")

    print(f"Selected {len(pdfs)} PDF(s); duplicate checks run before every conversion.")
    for pdf_path in pdfs:
        validate_requested_source_type(pdf_path, args.source_type)
        duplicates = find_exact_duplicates(pdf_path)
        near_duplicates = find_near_duplicates(pdf_path)
        if duplicates:
            print(f"- DUPLICATE: {pdf_path}")
            for duplicate in duplicates:
                print(f"  existing: {duplicate}")
        elif near_duplicates:
            print(f"- NEEDS_DUPLICATE_REVIEW: {pdf_path}")
            for candidate in near_duplicates:
                print(f"  candidate ({candidate['reason']}, similarity={candidate['similarity']}): {candidate['path']}")
        else:
            print(f"- unique: {pdf_path}")
    if args.dry_run:
        return

    for pdf_path in pdfs:
        duplicates = find_exact_duplicates(pdf_path)
        if duplicates:
            print(f"Skipped duplicate: {pdf_path}")
            continue
        near_duplicates = find_near_duplicates(pdf_path)
        if near_duplicates and not args.confirm_near_duplicate:
            print(f"Skipped pending duplicate review: {pdf_path}")
            continue
        duplicate_review = None
        if near_duplicates:
            duplicate_review = {
                "status": "human_confirmed_distinct_or_additional_version",
                "decision_note": args.confirm_near_duplicate,
                "candidates": near_duplicates,
            }
        output_dir = process_pdf(pdf_path, args.source_type, duplicate_review)
        print(f"Review package written to: {output_dir}")


if __name__ == "__main__":
    main()
