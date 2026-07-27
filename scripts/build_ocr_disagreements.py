"""Create review candidates from RapidOCR line boxes and Tesseract TSV boxes.

This is a non-destructive alignment aid.  A disagreement means only that two
engines produced different candidate text at a spatially related location; it
does not establish which candidate is correct.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import re
from statistics import mean


def page_number(name: str) -> int:
    match = re.search(r"(\d{3,4})", name)
    if not match:
        raise ValueError(f"Page number missing from {name}")
    return int(match.group(1))


def normalize(text: str) -> str:
    return re.sub(r"[\s\W_]", "", text)


def rect_from_polygon(polygon: list[list[float]]) -> tuple[float, float, float, float]:
    xs = [point[0] for point in polygon]
    ys = [point[1] for point in polygon]
    return min(xs), min(ys), max(xs), max(ys)


def overlap_score(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    left, top = max(a[0], b[0]), max(a[1], b[1])
    right, bottom = min(a[2], b[2]), min(a[3], b[3])
    if right <= left or bottom <= top:
        return 0.0
    intersection = (right - left) * (bottom - top)
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return intersection / max(area_a + area_b - intersection, 1)


def tesseract_lines(tsv_path: Path) -> list[dict]:
    groups: dict[tuple[str, str, str, str], list[dict]] = {}
    with tsv_path.open(encoding="utf-8", newline="") as stream:
        # Tesseract may emit a literal double quote as recognized text.  Its
        # TSV is not CSV-escaped in that case, so treating quotes as CSV quote
        # delimiters can swallow all subsequent physical rows into one field.
        for row in csv.DictReader(stream, delimiter="\t", quoting=csv.QUOTE_NONE):
            if row["level"] != "5" or not row["text"].strip():
                continue
            key = (row["block_num"], row["par_num"], row["line_num"], row["page_num"])
            groups.setdefault(key, []).append(row)

    output: list[dict] = []
    for words in groups.values():
        left = min(float(word["left"]) for word in words)
        top = min(float(word["top"]) for word in words)
        right = max(float(word["left"]) + float(word["width"]) for word in words)
        bottom = max(float(word["top"]) + float(word["height"]) for word in words)
        confidences = [float(word["conf"]) for word in words if float(word["conf"]) >= 0]
        output.append(
            {
                "text": "".join(word["text"] for word in words),
                "box": [left, top, right, bottom],
                "mean_word_confidence": mean(confidences) / 100 if confidences else None,
                "min_word_confidence": min(confidences) / 100 if confidences else None,
            }
        )
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rapid-json", required=True)
    parser.add_argument("--tesseract-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    rapid = json.loads(Path(args.rapid_json).read_text(encoding="utf-8"))
    tess_dir = Path(args.tesseract_dir)
    disagreements: list[dict] = []
    summary: dict[str, int] = {"rapid_lines": 0, "matched_lines": 0, "disagreements": 0, "unmatched_rapid_lines": 0}

    for page in rapid["pages"]:
        number = page["page_number"]
        tsv = tess_dir / f"page-{number:03d}.tsv"
        if not tsv.exists():
            raise FileNotFoundError(tsv)
        tess_lines = tesseract_lines(tsv)
        used: set[int] = set()
        for line in page["lines"]:
            summary["rapid_lines"] += 1
            rapid_box = rect_from_polygon(line["box"])
            candidates = [(index, overlap_score(rapid_box, tuple(item["box"]))) for index, item in enumerate(tess_lines) if index not in used]
            index, score = max(candidates, key=lambda item: item[1], default=(-1, 0.0))
            if score < 0.15:
                summary["unmatched_rapid_lines"] += 1
                disagreements.append(
                    {"kind": "unmatched_rapid_line", "page_number": number, "rapid_line_number": line["line_number"], "rapid_text": line["text"], "rapid_confidence": line["confidence"], "overlap_score": score}
                )
                continue
            used.add(index)
            summary["matched_lines"] += 1
            tess = tess_lines[index]
            if normalize(line["text"]) != normalize(tess["text"]):
                summary["disagreements"] += 1
                disagreements.append(
                    {
                        "kind": "text_disagreement",
                        "page_number": number,
                        "rapid_line_number": line["line_number"],
                        "rapid_text": line["text"],
                        "rapid_confidence": line["confidence"],
                        "tesseract_text": tess["text"],
                        "tesseract_mean_word_confidence": tess["mean_word_confidence"],
                        "tesseract_min_word_confidence": tess["min_word_confidence"],
                        "overlap_score": score,
                    }
                )

    payload = {"stage": "dual_ocr_disagreement_candidates", "summary": summary, "candidates": disagreements}
    output = Path(args.output)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
