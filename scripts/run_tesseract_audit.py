"""Generate auditable Tesseract OCR candidates from a fixed page-image set."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
from typing import Any

from build_ocr_disagreements import tesseract_lines


def page_number(path: Path) -> int:
    match = re.search(r"(\d{3,4})$", path.stem)
    if not match:
        raise ValueError(f"Cannot determine page number from {path.name}")
    return int(match.group(1))


def file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--images", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--tsv-dir", required=True, type=Path)
    parser.add_argument("--tesseract", default=r"C:\Program Files\Tesseract-OCR\tesseract.exe", type=Path)
    parser.add_argument("--language", default="chi_sim")
    parser.add_argument("--psm", default="6")
    args = parser.parse_args()

    images = sorted(args.images.glob("*.png"))
    if not images:
        raise FileNotFoundError(f"No PNG images in {args.images}")
    args.tsv_dir.mkdir(parents=True, exist_ok=True)
    pages: list[dict[str, Any]] = []
    for index, image in enumerate(images, 1):
        number = page_number(image)
        result = subprocess.run(
            [str(args.tesseract), str(image), "stdout", "-l", args.language, "--psm", str(args.psm), "tsv"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if result.returncode:
            raise RuntimeError(f"Tesseract failed on {image.name}: {result.stderr.decode('utf-8', errors='replace')}")
        tsv = args.tsv_dir / f"page-{number:03d}.tsv"
        tsv.write_bytes(result.stdout)
        lines = tesseract_lines(tsv)
        pages.append(
            {
                "page_number": number,
                "image_filename": image.name,
                "image_sha256": file_sha256(image),
                "lines": [
                    {
                        "line_number": line_index,
                        "text": line["text"],
                        "confidence": line["mean_word_confidence"],
                        "box": [
                            [line["box"][0], line["box"][1]], [line["box"][2], line["box"][1]],
                            [line["box"][2], line["box"][3]], [line["box"][0], line["box"][3]],
                        ],
                    }
                    for line_index, line in enumerate(lines, 1)
                ],
            }
        )
        if index == 1 or index % 10 == 0 or index == len(images):
            print(f"ocr_progress={index}/{len(images)} pdf_page={number} lines={len(lines)}", flush=True)

    payload = {
        "stage": "ocr_candidate",
        "engine": "tesseract",
        "language": args.language,
        "psm": int(args.psm),
        "includes_risk_flags": False,
        "pages": pages,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"pages={len(pages)} lines={sum(len(page['lines']) for page in pages)}", flush=True)


if __name__ == "__main__":
    main()
