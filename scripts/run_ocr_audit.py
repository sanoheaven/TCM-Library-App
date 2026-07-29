"""Generate auditable OCR candidates, optionally followed by risk detection.

The default mode deliberately does not import or run risk rules. This lets an
independent source-image correction baseline be completed before risk flags
are revealed.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any


def file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def page_number(path: Path) -> int:
    match = re.search(r"(\d{3,4})$", path.stem)
    if not match:
        raise ValueError(f"Cannot determine page number from {path.name}")
    return int(match.group(1))


def run(args: argparse.Namespace) -> dict[str, Any]:
    from rapidocr_onnxruntime import RapidOCR

    image_paths = sorted(Path(args.images).glob(args.glob))
    if not image_paths:
        raise FileNotFoundError("No source images matched")

    engine = RapidOCR()
    pages: list[dict[str, Any]] = []
    for index, image_path in enumerate(image_paths, start=1):
        result, _elapsed = engine(str(image_path))
        lines = [
            {
                "line_number": index,
                "text": text,
                "confidence": float(confidence),
                "box": box,
            }
            for index, (box, text, confidence) in enumerate(result or [], start=1)
        ]
        pages.append(
            {
                "page_number": page_number(image_path),
                "image_filename": image_path.name,
                "image_sha256": file_sha256(image_path),
                "lines": lines,
            }
        )
        if index == 1 or index % 10 == 0 or index == len(image_paths):
            print(f"ocr_progress={index}/{len(image_paths)} pdf_page={page_number(image_path)} lines={len(lines)}", flush=True)

    payload: dict[str, Any] = {
        "stage": "ocr_candidate",
        "engine": "rapidocr_onnxruntime",
        "includes_risk_flags": False,
        "pages": pages,
    }
    if args.with_risks:
        from src.risk_rules import OcrLine, detect_risks

        lines = [
            OcrLine(page["page_number"], line["line_number"], line["text"], line["confidence"])
            for page in pages
            for line in page["lines"]
        ]
        payload["includes_risk_flags"] = True
        payload["risk_flags"] = [asdict(flag) for flag in detect_risks(lines)]

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--images", required=True)
    parser.add_argument("--glob", default="*.png")
    parser.add_argument("--output", required=True)
    parser.add_argument("--with-risks", action="store_true")
    args = parser.parse_args()
    payload = run(args)
    print(f"pages={len(payload['pages'])} lines={sum(len(page['lines']) for page in payload['pages'])}")


if __name__ == "__main__":
    main()
