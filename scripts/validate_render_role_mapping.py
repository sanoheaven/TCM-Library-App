"""Validate, canonicalize, and render constrained OCR role mappings.

This program never changes source text. It computes structural statistics itself,
and it assigns canonical commentary block IDs only from the validated role order.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


ROLES = {"body", "commentary", "title", "diagram", "formula", "excluded"}
EVIDENCE = {"text", "coordinates", "context", "needs_human_review"}


def is_commentary_marker(text: str) -> bool:
    """Recognize explicit commentary labels, including variants such as 【总评讲】."""
    return bool(re.match(r"^【[^】]*评讲】", text))


def frozen_lines(ocr: dict[str, Any], start: int, end: int) -> list[dict[str, Any]]:
    return [
        {"pdf_page": page["page_number"], "line_number": line["line_number"], "text": line["text"]}
        for page in ocr["pages"]
        if start <= page["page_number"] <= end
        for line in page["lines"]
    ]


def canonicalize(expected: list[dict[str, Any]], mappings: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if len(expected) != len(mappings):
        errors.append(f"mapping_count={len(mappings)} expected={len(expected)}")
        return [], errors, warnings

    canonical: list[dict[str, Any]] = []
    active_block: str | None = None
    previous_role: str | None = None
    previous_page: int | None = None
    last_content_role: str | None = None
    last_content_block: str | None = None
    last_content_page: int | None = None
    seen_keys: set[tuple[int, int]] = set()
    original_blocks: dict[str, list[tuple[int, int]]] = {}
    for source, raw in zip(expected, mappings, strict=True):
        item = dict(raw)
        key = (item.get("pdf_page"), item.get("line_number"))
        if key in seen_keys:
            errors.append(f"duplicate_source={key}")
        seen_keys.add(key)
        if {k: item.get(k) for k in ("pdf_page", "line_number", "text")} != source:
            errors.append(f"source_mismatch expected={source['pdf_page']}/{source['line_number']}")
        role = item.get("role")
        if role not in ROLES:
            errors.append(f"unknown_role={role!r} at {source['pdf_page']}/{source['line_number']}")
        evidence = item.get("role_evidence") or {}
        if evidence.get("basis") not in EVIDENCE or "visual_confirmed" in str(evidence).lower():
            errors.append(f"invalid_evidence at {source['pdf_page']}/{source['line_number']}")
        if "word_pdf_page" in item:
            errors.append(f"word_pdf_page_anchor_forbidden at {source['pdf_page']}/{source['line_number']}")
        word_candidate = item.get("word_candidate_text")
        if word_candidate is not None:
            if not isinstance(word_candidate, str) or not word_candidate:
                errors.append(f"invalid_word_candidate_text at {source['pdf_page']}/{source['line_number']}")
            elif word_candidate != source["text"]:
                warnings.append(f"word_candidate_requires_page_review at {source['pdf_page']}/{source['line_number']}")

        if role == "commentary":
            original = item.get("block_id")
            if not original:
                errors.append(f"missing_commentary_block_id at {source['pdf_page']}/{source['line_number']}")
            else:
                original_blocks.setdefault(str(original), []).append(key)
            if is_commentary_marker(source["text"]):
                active_block = f"commentary_{source['pdf_page']}_{source['line_number']}"
            elif previous_role != "commentary" or active_block is None:
                if last_content_role == "commentary" and last_content_page != source["pdf_page"]:
                    active_block = last_content_block
                    warnings.append(f"cross_page_commentary_without_marker at {source['pdf_page']}/{source['line_number']}")
                else:
                    active_block = f"commentary_unmarked_{source['pdf_page']}_{source['line_number']}"
                    warnings.append(f"commentary_without_marked_start at {source['pdf_page']}/{source['line_number']}")
            item["block_id"] = active_block
        else:
            if item.get("block_id") is not None:
                errors.append(f"non_commentary_block_id at {source['pdf_page']}/{source['line_number']}")
            active_block = None
            item["block_id"] = None
        previous_role = role
        previous_page = source["pdf_page"]
        if role not in {"excluded", "title"}:
            last_content_role = role
            last_content_block = item.get("block_id")
            last_content_page = source["pdf_page"]
        canonical.append(item)

    for block, locations in original_blocks.items():
        starts = sum(1 for location in locations if is_commentary_marker(next(x for x in canonical if (x["pdf_page"], x["line_number"]) == location)["text"]))
        if starts > 1:
            warnings.append(f"model_block_id_reused={block} marked_starts={starts}; canonicalized")
    return canonical, errors, warnings


def normalize_formula_roles(mappings: list[dict[str, Any]]) -> list[str]:
    """Apply the auditable, generic '附方 + numbered entries' structural rule."""
    warnings: list[str] = []
    in_formula = False
    for item in mappings:
        text = item.get("text", "")
        if item.get("role") == "title" and "附方" in text:
            in_formula = True
            continue
        if in_formula and item.get("role") == "excluded":
            continue
        if in_formula and item.get("role") == "title":
            in_formula = False
            continue
        if in_formula and text.lstrip().startswith(("(", "（")):
            if item.get("role") != "formula":
                warnings.append(f"formula_role_normalized at {item.get('pdf_page')}/{item.get('line_number')}")
                item["role"] = "formula"
                item["block_id"] = None
                item["role_evidence"] = {"basis": "context", "note": "附方标题后的编号条目；待人工核验"}
            continue
        if in_formula:
            in_formula = False
    return warnings


def count_cross_page_commentary(mappings: list[dict[str, Any]]) -> int:
    by_page: dict[int, list[dict[str, Any]]] = {}
    for item in mappings:
        by_page.setdefault(item["pdf_page"], []).append(item)
    count = 0
    pages = sorted(by_page)
    for left_page, right_page in zip(pages, pages[1:]):
        left = next((item for item in reversed(by_page[left_page]) if item["role"] not in {"excluded", "title"}), None)
        right = next((item for item in by_page[right_page] if item["role"] not in {"excluded", "title"}), None)
        if left and right and left["role"] == right["role"] == "commentary" and left["block_id"] == right["block_id"]:
            count += 1
    return count


def render(markdown: Path, mappings: list[dict[str, Any]], start: int, end: int, ocr_hash: str, chapter_name: str) -> None:
    lines = [
        "---", "type: structured_transcription", "status: structure_final_pending_creator_review",
        f'scope: "{chapter_name} / PDF {start}-{end}"', f'ocr_candidate_sha256: "{ocr_hash}"', "---", "",
        f"# {chapter_name}：结构化重做稿", "", "> 机器候选：逐行角色映射经程序硬校验后渲染；尚未人工逐页核图，不得进入 Ingest。", "",
    ]
    by_page: dict[int, list[dict[str, Any]]] = {}
    for item in mappings:
        by_page.setdefault(item["pdf_page"], []).append(item)
    prior_pages = [number for number in by_page if number < start]
    previous_page_last_block: str | None = None
    if prior_pages:
        prior_items = by_page[max(prior_pages)]
        if prior_items and prior_items[-1]["role"] == "commentary":
            previous_page_last_block = prior_items[-1].get("block_id")

    def rendered_source(item: dict[str, Any], anchor: str) -> str:
        """Show auxiliary Word text only when it is unmistakably labelled and audited."""
        text = item["text"]
        if item.get("suppress_display"):
            return (
                f'<!-- OCR_SOURCE:display_suppressed | pdf_page={item["pdf_page"]} '
                f'| ocr_line={item["line_number"]} | text={json.dumps(text, ensure_ascii=False)} -->'
            )
        word_candidate = item.get("word_candidate_text")
        if isinstance(word_candidate, str) and word_candidate and word_candidate != text:
            return (
                f"{anchor}**[扫描全能王 Word 候选，待原页核验]** {word_candidate}\n"
                f'<!-- OCR_SOURCE:word_candidate_diff | pdf_page={item["pdf_page"]} '
                f'| ocr_line={item["line_number"]} | text={json.dumps(text, ensure_ascii=False)} -->'
            )
        return anchor + text

    for page in range(start, end + 1):
        page_items = by_page[page]
        lines.extend([f"## PDF {page}（书内页 {page - 16}）", ""])
        open_block: str | None = None
        for index, item in enumerate(page_items):
            role, text = item["role"], item["text"]
            next_item = page_items[index + 1] if index + 1 < len(page_items) else None
            anchor = f'<a id="pdf-{page}-line-{item["line_number"]}"></a>'
            display = rendered_source(item, anchor)
            if role == "commentary":
                if open_block != item["block_id"]:
                    continuation = " | continued_from=previous_page" if item["block_id"] == previous_page_last_block else ""
                    lines.append(f"<!-- BEGIN:评讲 | pdf_page={page} | block_id={item['block_id']} | boundary=needs_human_review{continuation} -->")
                    open_block = item["block_id"]
                lines.append(display)
                if not next_item or next_item["role"] != "commentary" or next_item["block_id"] != open_block:
                    lines.append(f"<!-- END:评讲 | pdf_page={page} | block_id={open_block} | boundary=needs_human_review -->")
                    open_block = None
            elif role == "excluded":
                lines.append(f'<!-- EXCLUDED:source_line | pdf_page={page} | ocr_line={item["line_number"]} | text={json.dumps(text, ensure_ascii=False)} -->')
            elif role == "title":
                lines.extend([f"### {anchor}{text}", ""])
            elif role == "diagram":
                group = item.get("diagram_group")
                previous = page_items[index - 1] if index else None
                group_start = not group or previous is None or previous.get("role") != "diagram" or previous.get("diagram_group") != group
                if group_start and item.get("derived_text"):
                    lines.extend([
                        f"<!-- DIAGRAM:manual_transcription | pdf_page={page} | group={group} | source=OCR_lines -->",
                        f"[图示人工转写（待原页核验）] {item['derived_text']}",
                    ])
                lines.extend([
                    f'<!-- DIAGRAM_SOURCE:source_line | pdf_page={page} | ocr_line={item["line_number"]} | text={json.dumps(text, ensure_ascii=False)} -->',
                    "",
                ])
            elif role == "formula":
                lines.extend([f"**附方（待人工核验）** {display}", ""])
            else:
                lines.append(display)
        previous_page_last_block = page_items[-1].get("block_id") if page_items[-1]["role"] == "commentary" else None
        lines.append("")
    markdown.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ocr", required=True, type=Path)
    parser.add_argument("--mapping-dir", required=True, type=Path)
    parser.add_argument("--page-start", required=True, type=int)
    parser.add_argument("--context-start", type=int)
    parser.add_argument("--page-end", required=True, type=int)
    parser.add_argument("--canonical-output", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--markdown-output", required=True, type=Path)
    parser.add_argument("--chapter-name", default="痰饮")
    args = parser.parse_args()
    ocr_bytes = args.ocr.read_bytes()
    ocr = json.loads(ocr_bytes.decode("utf-8"))
    context_start = args.context_start if args.context_start is not None else args.page_start
    if context_start > args.page_start:
        raise ValueError("context-start must be less than or equal to page-start")
    expected = frozen_lines(ocr, context_start, args.page_end)
    raw_mappings: list[dict[str, Any]] = []
    api_models: Counter[str] = Counter()
    for page in range(context_start, args.page_end + 1):
        path = args.mapping_dir / f"pdf-{page:03d}.json"
        if not path.exists():
            raise FileNotFoundError(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        api_models[str(data.get("api_model"))] += 1
        raw_mappings.extend(data.get("mappings", []))
    formula_warnings = normalize_formula_roles(raw_mappings)
    canonical, errors, warnings = canonicalize(expected, raw_mappings)
    warnings = formula_warnings + warnings
    counts = Counter(item["role"] for item in canonical)
    crossing = count_cross_page_commentary(canonical)
    report_lines = [
        f"source_line_count={len(expected)}", f"mapping_count={len(raw_mappings)}", f"role_counts={dict(sorted(counts.items()))}",
        f"cross_page_commentary_blocks={crossing}", f"api_models={dict(api_models)}", f"errors={len(errors)}", f"warnings={len(warnings)}",
        *["ERROR " + item for item in errors], *["WARNING " + item for item in warnings],
    ]
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    if errors:
        raise RuntimeError("Hard validation failed; see report")
    args.canonical_output.write_text(json.dumps({"schema": "ocr_role_mapping_v1_canonical", "mappings": canonical}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    render(args.markdown_output, canonical, args.page_start, args.page_end, hashlib.sha256(ocr_bytes).hexdigest().upper(), args.chapter_name)
    print("hard_validation=passed")
    print("; ".join(report_lines[:6]))


if __name__ == "__main__":
    main()
