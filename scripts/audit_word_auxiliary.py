"""Compare an auxiliary ScanKing Word transcript with frozen OCR evidence.

The report is deliberately non-destructive: it never writes Word text back into
OCR lines or infers PDF page anchors from the Word document's reflowed pages.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from docx import Document


PUNCTUATION = re.compile(r"[\s\u3000\W_]+", re.UNICODE)
FORMULA = re.compile(r"^[（(]\s*(\d+)\s*[）)]")


def normalize(text: str) -> str:
    return PUNCTUATION.sub("", text)


def source_lines(ocr: dict[str, Any], start: int, end: int) -> list[dict[str, Any]]:
    return [
        {"pdf_page": page["page_number"], "line_number": line["line_number"], "text": line["text"]}
        for page in ocr["pages"]
        if start <= page["page_number"] <= end
        for line in page["lines"]
    ]


def normalized_source_index(lines: list[dict[str, Any]]) -> tuple[str, list[tuple[int, int]]]:
    characters: list[str] = []
    locations: list[tuple[int, int]] = []
    for line in lines:
        for char in normalize(line["text"]):
            characters.append(char)
            locations.append((line["pdf_page"], line["line_number"]))
    return "".join(characters), locations


def locations_for_span(locations: list[tuple[int, int]], start: int, end: int) -> list[tuple[int, int]]:
    return list(dict.fromkeys(locations[start:end]))


def formula_rows(paragraphs: list[str]) -> dict[int, str]:
    result: dict[int, str] = {}
    for paragraph in paragraphs:
        match = FORMULA.match(paragraph)
        if match:
            result[int(match.group(1))] = paragraph
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ocr", required=True, type=Path)
    parser.add_argument("--word", required=True, type=Path)
    parser.add_argument("--page-start", required=True, type=int)
    parser.add_argument("--page-end", required=True, type=int)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()

    ocr = json.loads(args.ocr.read_text(encoding="utf-8"))
    lines = source_lines(ocr, args.page_start, args.page_end)
    paragraphs = [paragraph.text.strip() for paragraph in Document(args.word).paragraphs if paragraph.text.strip()]
    normalized_ocr, locations = normalized_source_index(lines)

    formula_ocr: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for line in lines:
        match = FORMULA.match(line["text"])
        if match:
            formula_ocr[int(match.group(1))].append(line)
    word_formulas = formula_rows(paragraphs)

    commentary_candidates: list[dict[str, Any]] = []
    previous_marked_commentary = False
    search_cursor = 0
    for paragraph_index, paragraph in enumerate(paragraphs, 1):
        marked = paragraph.startswith("【评讲】")
        continuation = previous_marked_commentary and not marked
        candidate = marked or continuation
        previous_marked_commentary = marked
        if not candidate:
            continue
        needle = normalize(paragraph)
        exact_start = normalized_ocr.find(needle, search_cursor)
        if exact_start < 0:
            exact_start = normalized_ocr.find(needle)
        if exact_start >= 0:
            commentary_candidates.append({
                "word_paragraph": paragraph_index,
                "classification": "explicit_marker" if marked else "possible_unmarked_continuation_requires_page_review",
                "match": "exact",
                "ocr_locations": locations_for_span(locations, exact_start, exact_start + len(needle)),
                "word_text": paragraph,
            })
            search_cursor = exact_start + len(needle)
            continue
        match = SequenceMatcher(None, needle, normalized_ocr, autojunk=False).find_longest_match()
        if match.size >= 8:
            commentary_candidates.append({
                "word_paragraph": paragraph_index,
                "classification": "explicit_marker" if marked else "possible_unmarked_continuation_requires_page_review",
                "match": "partial_requires_page_review",
                "shared_characters": match.size,
                "ocr_locations": locations_for_span(locations, match.b, match.b + match.size),
                "word_text": paragraph,
            })

    report = [
        "# 《痰饮》扫描全能王 Word 辅助核对报告", "",
        "> 本报告只登记候选差异；Word 不是 PDF 页级证据，不能改写冻结 OCR 源行。所有候选仍须回到原 PDF 页图逐页确认。", "",
        f"- 冻结 OCR 源行：{len(lines)}（PDF {args.page_start}–{args.page_end}）",
        f"- Word 非空段落：{len(paragraphs)}（Word 重排页码不参与 PDF 锚定）",
        f"- Word 附方编号：{len(word_formulas)}；OCR 附方编号：{len(formula_ocr)}", "",
        "## 评讲候选（Word 标记/紧邻续段对照）", "",
    ]
    for item in commentary_candidates:
        anchors = ", ".join(f"PDF {page} 行 {line}" for page, line in item["ocr_locations"])
        detail = f"；共享字符 {item['shared_characters']}" if "shared_characters" in item else ""
        report.extend([
            f"- Word 段 {item['word_paragraph']}：`{item['classification']}` / `{item['match']}` → {anchors}{detail}",
            f"  - Word 候选：{item['word_text']}",
        ])
    report.extend(["", "## 附方候选（Word 保留空格，仅供逐页核图）", ""])
    for number in sorted(word_formulas):
        ocr_rows = formula_ocr.get(number, [])
        anchors = ", ".join(f"PDF {row['pdf_page']} 行 {row['line_number']}" for row in ocr_rows) or "未在 OCR 编号行中定位"
        ocr_text = " / ".join(row["text"] for row in ocr_rows) or "—"
        ratio = SequenceMatcher(None, normalize(ocr_text), normalize(word_formulas[number]), autojunk=False).ratio()
        report.extend([
            f"### （{number}）→ {anchors}",
            f"- OCR 冻结文本：{ocr_text}",
            f"- Word 候选：{word_formulas[number]}",
            f"- 归一化相似度：{ratio:.3f}；必须核对原页后才能采用。", "",
        ])
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text("\n".join(report) + "\n", encoding="utf-8")
    print(f"report={args.report}")
    print(f"source_lines={len(lines)} word_paragraphs={len(paragraphs)} commentary_candidates={len(commentary_candidates)} formulas={len(word_formulas)}")


if __name__ == "__main__":
    main()
