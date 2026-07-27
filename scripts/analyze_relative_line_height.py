"""Report OCR line-box heights for a small, visually labelled layout sample."""

from __future__ import annotations

import argparse
import json
from statistics import median
from pathlib import Path


def height(line: dict) -> float:
    ys = [point[1] for point in line["box"]]
    return max(ys) - min(ys)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ocr", required=True)
    parser.add_argument("--page", action="append", type=int, required=True)
    args = parser.parse_args()

    source = json.loads(Path(args.ocr).read_text(encoding="utf-8"))
    for number in args.page:
        page = next(item for item in source["pages"] if item["page_number"] == number)
        print(f"PAGE {number}")
        for line in page["lines"]:
            print(f"{line['line_number']:02}\t{height(line):.2f}\t{line['text']}")
        values = [height(line) for line in page["lines"] if len(line["text"].strip()) >= 4]
        print(f"MEDIAN\t{median(values):.2f}")


if __name__ == "__main__":
    main()
