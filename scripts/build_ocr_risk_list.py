"""Create a non-destructive review-risk list from an existing OCR JSON file."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.risk_rules import OcrLine, detect_risks


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ocr-json", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    payload = json.loads(args.ocr_json.read_text(encoding="utf-8"))
    lines = [
        OcrLine(page["page_number"], line["line_number"], line["text"], float(line["confidence"] or 0))
        for page in payload["pages"]
        for line in page["lines"]
    ]
    flags = detect_risks(lines)
    result = {
        "stage": "ocr_risk_candidates",
        "source_engine": payload.get("engine"),
        "source_line_count": len(lines),
        "risk_flag_count": len(flags),
        "risk_flags": [asdict(flag) for flag in flags],
    }
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"source_lines={len(lines)} risk_flags={len(flags)}")


if __name__ == "__main__":
    main()
