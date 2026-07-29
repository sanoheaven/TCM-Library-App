"""Merge OCR disagreements and rule flags into a sorted human-review queue."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path


RISK_SCORE = {
    "low_confidence": 1,
    "layout_marker": 2,
    "short_clinical_fragment": 2,
    "delimiter_balance": 3,
    "term_near_match": 3,
    "confusable_character": 3,
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rapid-json", required=True, type=Path)
    parser.add_argument("--disagreements", required=True, type=Path)
    parser.add_argument("--risks", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    rapid = json.loads(args.rapid_json.read_text(encoding="utf-8"))
    source = {
        (page["page_number"], line["line_number"]): line
        for page in rapid["pages"]
        for line in page["lines"]
    }
    disagreements = json.loads(args.disagreements.read_text(encoding="utf-8"))["candidates"]
    flags = json.loads(args.risks.read_text(encoding="utf-8"))["risk_flags"]
    queue: dict[tuple[int, int], dict] = {}

    def item(page: int, line: int) -> dict:
        key = (page, line)
        if key not in queue:
            original = source[key]
            queue[key] = {
                "pdf_page": page,
                "rapid_line_number": line,
                "rapid_text": original["text"],
                "rapid_confidence": original["confidence"],
                "priority_score": 0,
                "reasons": [],
            }
        return queue[key]

    for candidate in disagreements:
        current = item(candidate["page_number"], candidate["rapid_line_number"])
        if candidate["kind"] == "unmatched_rapid_line":
            score, reason = 5, "unmatched_between_engines"
        else:
            score, reason = 3, "text_disagreement_between_engines"
            current["tesseract_text"] = candidate["tesseract_text"]
            current["overlap_score"] = candidate["overlap_score"]
        current["priority_score"] += score
        current["reasons"].append(reason)

    for flag in flags:
        current = item(flag["page_number"], flag["line_number"])
        current["priority_score"] += RISK_SCORE.get(flag["rule_id"], 1)
        current["reasons"].append(f"risk:{flag['rule_id']}")
        current.setdefault("risk_details", []).append(flag["detail"])

    items = sorted(queue.values(), key=lambda value: (-value["priority_score"], value["pdf_page"], value["rapid_line_number"]))
    result = {
        "stage": "ocr_review_priority_queue",
        "source": "dual_ocr_disagreements_v1 + rapidocr_risk_list_v1",
        "candidate_count": len(items),
        "priority_counts": dict(sorted(Counter(item["priority_score"] for item in items).items(), reverse=True)),
        "items": items,
    }
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"review_candidates={len(items)} priority_counts={result['priority_counts']}")


if __name__ == "__main__":
    main()
