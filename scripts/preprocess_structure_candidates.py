"""Build non-binding OCR structure candidates and validate chapter boundaries.

The preprocessor never changes OCR text and never assigns final roles.  With a
chapter manifest it can, however, detect boundary conditions that a role
mapping must explicitly resolve.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


COMMENTARY = re.compile(r"^【(?:总)?评讲】")
FORMULA_ITEM = re.compile(r"^[（(]\d+[）)]")
PAGE_NUMBER = re.compile(r"^\d{1,3}$")
SENTENCE_END = tuple("。！？；：”’")
SHORT_HEADING_MARKERS = ("鉴别", "分型", "转归")


def ends_sentence(text: str) -> bool:
    """Recognize terminal punctuation and closed quote/bracket formula examples."""
    value = text.strip()
    closers = "\u300d\u300f\u3011\uff09)]\u201d\u2019"
    terminals = SENTENCE_END + ("\u3002", "\uff01", "\uff1f", "\uff1b", "\uff1a", "\u2026")
    if value.endswith(tuple(closers)):
        return True
    return value.rstrip(closers).endswith(terminals)


def normalized(text: str) -> str:
    return re.sub(r"[\s·、，。；：:（）()《》【】\-—]+", "", text)


def detect(page: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    formula_mode = False
    for line in page["lines"]:
        text = line["text"].strip()
        reasons: list[str] = []
        if COMMENTARY.match(text):
            reasons.append("commentary_start")
        if "附方" in text and len(text) <= 12:
            formula_mode = True
            reasons.append("formula_heading")
        elif formula_mode and FORMULA_ITEM.match(text):
            reasons.append("formula_item")
        elif formula_mode and text and not FORMULA_ITEM.match(text):
            formula_mode = False
        if PAGE_NUMBER.match(text):
            reasons.append("page_number_candidate")
        if len(text) <= 12 and any(marker in text for marker in SHORT_HEADING_MARKERS):
            reasons.append("diagram_or_heading_candidate")
        if reasons:
            result.append({
                "pdf_page": page["page_number"],
                "line_number": line["line_number"],
                "text": line["text"],
                "candidates": reasons,
            })
    return result


def find_title_span(page: dict[str, Any], title: str) -> tuple[int, int] | None:
    wanted = normalized(title)
    lines = page["lines"]
    for start in range(len(lines)):
        combined = ""
        for end in range(start, min(start + 4, len(lines))):
            if len(lines[end]["text"].strip()) > 20:
                break
            combined += normalized(lines[end]["text"])
            if combined == wanted:
                return lines[start]["line_number"], lines[end]["line_number"]
            if not wanted.startswith(combined):
                break
    return None


CRITICAL_REVIEW_RULES = {
    "pre_child_content_requires_inheritance_review",
    "missing_manifest_title",
    "split_title_candidate",
    "title_alias_candidate",
}


def load_resolutions(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload.get("resolutions", payload) if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        raise ValueError("resolution file must contain a resolutions list")
    for item in records:
        required = {"rule_id", "pdf_page", "source_lines", "resolution", "evidence"}
        if not isinstance(item, dict) or not required <= set(item) or not item["resolution"] or not item["evidence"]:
            raise ValueError("invalid resolution record")
    return records


def resolved(
    issue: dict[str, Any],
    resolutions: list[dict[str, Any]],
    mapping: dict[tuple[int, int], dict[str, Any]],
) -> bool:
    key = (issue["rule_id"], issue["pdf_page"], issue["source_lines"])
    record = next((r for r in resolutions if (r["rule_id"], r["pdf_page"], r["source_lines"]) == key), None)
    if record is None:
        return False
    assertions = record.get("role_assertions", [])
    if issue["rule_id"] == "pre_child_content_requires_inheritance_review" and not assertions:
        return False
    for assertion in assertions:
        required = {"pdf_page", "line_start", "line_end", "role"}
        if not isinstance(assertion, dict) or not required <= set(assertion):
            return False
        for line in range(assertion["line_start"], assertion["line_end"] + 1):
            if mapping.get((assertion["pdf_page"], line), {}).get("role") != assertion["role"]:
                return False
    return True


def load_mapping(mapping_dirs: list[Path], pages: list[dict[str, Any]]) -> tuple[dict[tuple[int, int], dict[str, Any]], set[int]]:
    result: dict[tuple[int, int], dict[str, Any]] = {}
    found_pages: set[int] = set()
    for page in pages:
        path = next((directory / f"pdf-{page['page_number']:03d}.json" for directory in mapping_dirs if (directory / f"pdf-{page['page_number']:03d}.json").exists()), None)
        if path is None:
            continue
        found_pages.add(page["page_number"])
        payload = json.loads(path.read_text(encoding="utf-8"))
        for item in payload.get("mappings", []):
            result[(item["pdf_page"], item["line_number"])] = item
    return result, found_pages


def validate_boundaries(
    pages: list[dict[str, Any]],
    manifest: dict[str, Any],
    mapping: dict[tuple[int, int], dict[str, Any]] | None = None,
    resolutions: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    mapping = mapping or {}
    resolutions = resolutions or []
    page_by_number = {page["page_number"]: page for page in pages}
    issues: list[dict[str, Any]] = []
    entries = manifest.get("entries", [])
    def add(rule: str, severity: str, page: int, lines: list[int], detail: str) -> None:
        issues.append({"rule_id": rule, "severity": severity, "pdf_page": page, "source_lines": lines, "detail": detail})

    for entry in entries:
        start = entry["start_pdf"]
        page = page_by_number.get(start)
        if page is None:
            continue
        span = find_title_span(page, entry["title"])
        alias_used: dict[str, Any] | None = None
        if span is None:
            for alias in entry.get("title_aliases", []):
                if not isinstance(alias, dict) or not alias.get("text") or not alias.get("evidence"):
                    add("invalid_title_alias_manifest", "error", start, [], f"{entry['id']} alias requires text and evidence")
                    continue
                span = find_title_span(page, alias["text"])
                if span is not None:
                    alias_used = alias
                    add("title_alias_candidate", "review", start, list(range(span[0], span[1] + 1)), f"{entry['id']} alias={alias['text']} evidence={alias['evidence']}")
                    break
        if span is None:
            add("missing_manifest_title", "review", start, [], f"{entry['id']} title={entry['title']}")
            continue
        first, last = span
        if alias_used is not None:
            wrong = [line for line in range(first, last + 1) if mapping and mapping.get((start, line), {}).get("role") != "title"]
            if wrong:
                add("mapping_title_alias_not_title", "error", start, wrong, f"{entry['id']} alias title mapped as non-title")
        if first != last:
            add("split_title_candidate", "review", start, list(range(first, last + 1)), f"{entry['title']} split across OCR lines")
            wrong = [line for line in range(first, last + 1) if mapping and mapping.get((start, line), {}).get("role") != "title"]
            if wrong:
                add("mapping_split_title_not_title", "error", start, wrong, f"{entry['title']} title fragments mapped as non-title")
        parent_id = entry.get("parent_id")
        if parent_id:
            preceding = [
                line["line_number"] for line in page["lines"]
                if line["line_number"] < first and not PAGE_NUMBER.match(line["text"].strip())
            ]
            if preceding:
                add("pre_child_content_requires_inheritance_review", "review", start, preceding, f"content precedes child {entry['id']}")

    for parent in (entry for entry in entries if not entry.get("parent_id")):
        parent_headers = [parent["title"], *parent.get("header_aliases", [])]
        parent_texts = {normalized(header) for header in parent_headers}
        for page_number in range(parent["start_pdf"] + 1, parent["end_pdf"] + 1):
            page = page_by_number.get(page_number)
            if not page:
                continue
            for line in page["lines"]:
                if normalized(line["text"]) in parent_texts:
                    number = line["line_number"]
                    add("repeated_parent_header_candidate", "review", page_number, [number], parent["title"])
                    if mapping and mapping.get((page_number, number), {}).get("role") != "excluded":
                        add("mapping_repeated_parent_header_not_excluded", "error", page_number, [number], parent["title"])

    for page in pages:
        items = page["lines"]
        for index, current in enumerate(items[:-1]):
            following = items[index + 1]
            current_map = mapping.get((page["page_number"], current["line_number"]))
            next_map = mapping.get((page["page_number"], following["line_number"]))
            if (
                current_map and next_map
                and current_map.get("role") == "commentary"
                and next_map.get("role") != "commentary"
                and next_map.get("role") != "excluded"
                and current["text"].strip()
                and not ends_sentence(current["text"])
            ):
                add(
                    "mapping_commentary_continuation_break",
                    "error",
                    page["page_number"],
                    [current["line_number"], following["line_number"]],
                    "commentary line ends mid-sentence but next line changes role",
                )
    for left_page, right_page in zip(pages, pages[1:]):
        if not left_page["lines"] or not right_page["lines"]:
            continue
        current = left_page["lines"][-1]
        following = right_page["lines"][0]
        current_map = mapping.get((left_page["page_number"], current["line_number"]))
        next_map = mapping.get((right_page["page_number"], following["line_number"]))
        if (
            current_map and next_map
            and current_map.get("role") == "commentary"
            and next_map.get("role") not in {"commentary", "excluded"}
            and current["text"].strip()
            and not ends_sentence(current["text"])
        ):
            add(
                "mapping_cross_page_commentary_continuation_break",
                "error",
                left_page["page_number"],
                [current["line_number"], following["line_number"]],
                "commentary crosses page boundary but first next-page content changes role",
            )
    for issue in list(issues):
        if issue["severity"] == "review" and issue["rule_id"] in CRITICAL_REVIEW_RULES and not resolved(issue, resolutions, mapping):
            add("unresolved_critical_review", "error", issue["pdf_page"], issue["source_lines"], f"{issue['rule_id']} requires auditable resolution")
    return issues


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ocr-json", required=True, type=Path)
    parser.add_argument("--page-start", required=True, type=int)
    parser.add_argument("--page-end", required=True, type=int)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--mapping-dir", type=Path, action="append", default=[])
    parser.add_argument("--resolutions", type=Path)
    parser.add_argument("--fail-on-errors", action="store_true")
    args = parser.parse_args()

    payload = json.loads(args.ocr_json.read_text(encoding="utf-8"))
    manifest = json.loads(args.manifest.read_text(encoding="utf-8")) if args.manifest else {"entries": []}
    requested_start = args.page_start
    child = next((entry for entry in manifest.get("entries", []) if entry.get("parent_id") and entry["start_pdf"] == requested_start), None)
    context_start = requested_start - 1 if child else requested_start
    pages = [p for p in payload["pages"] if context_start <= p["page_number"] <= args.page_end]
    candidates = [entry for page in pages for entry in detect(page)]
    counts = Counter(reason for entry in candidates for reason in entry["candidates"])
    mapping, found_mapping_pages = load_mapping(args.mapping_dir, pages)
    resolutions = load_resolutions(args.resolutions)
    issues = validate_boundaries(pages, manifest, mapping, resolutions)
    if child:
        if context_start not in {p["page_number"] for p in pages}:
            issues.append({"rule_id": "missing_child_context_ocr", "severity": "error", "pdf_page": context_start, "source_lines": [], "detail": f"{child['id']} requires previous-page OCR"})
        if context_start not in found_mapping_pages:
            issues.append({"rule_id": "missing_child_context_mapping", "severity": "error", "pdf_page": context_start, "source_lines": [], "detail": f"{child['id']} requires previous-page mapping"})
    issue_counts = Counter(issue["severity"] for issue in issues)
    result = {
        "stage": "structure_preprocess_stable",
        "binding": False,
        "requested_page_start": requested_start,
        "context_page_start": context_start,
        "source_line_count": sum(len(p["lines"]) for p in pages),
        "candidate_counts": dict(sorted(counts.items())),
        "boundary_issue_counts": dict(sorted(issue_counts.items())),
        "candidates": candidates,
        "boundary_issues": issues,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"source_lines={result['source_line_count']} candidates={len(candidates)} boundary_issues={len(issues)}")
    if args.fail_on_errors and issue_counts["error"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
