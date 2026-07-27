"""Build a page-anchored correction draft from auditable OCR inputs.

Only corrections explicitly present in the frozen gold baseline are applied.
The output is a review draft, never a source of truth or a final transcription.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ocr", required=True)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--title", default="不寐（附：多寐、健忘）校勘版 v0")
    parser.add_argument("--scope", default="不寐（附：多寐、健忘），书内页82-90 / PDF98-106")
    parser.add_argument("--page-start", type=int)
    parser.add_argument("--page-end", type=int)
    args = parser.parse_args()
    if (args.page_start is None) != (args.page_end is None):
        raise ValueError("--page-start and --page-end must be provided together")
    if args.page_start is not None and args.page_start > args.page_end:
        raise ValueError("--page-start must be less than or equal to --page-end")

    ocr = json.loads(Path(args.ocr).read_text(encoding="utf-8"))
    baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    corrections = {
        (item["page"], item["line"]): item
        for item in baseline["known_correction_records"]
    }

    output: list[str] = [
        "---",
        "type: corrected_transcription_draft",
        "status: correction_draft_pending_second_visual_pass",
        'source: "2014_邓必隆_中医内科学评讲_姚荷生著；邓必隆整理_人民卫生出版社_v1.pdf"',
        f'scope: "{args.scope}"',
        f'ocr_candidate_sha256: "{baseline["ocr_candidate_sha256"]}"',
        "---",
        "",
        f"# {args.title}",
        "",
        "> 状态：仅将已确认校勘项合入 OCR 初稿；尚未完成全量二校，不能作为核定稿、规则提取或临床内容依据。",
        "> 每行均保留 PDF 页和 OCR 行锚点；附录列出本版应用的校勘记录。",
        "",
    ]

    applied: list[dict] = []
    for page in ocr["pages"]:
        if args.page_start is not None and not args.page_start <= page["page_number"] <= args.page_end:
            continue
        output.extend([f"## PDF {page['page_number']}（书内页 {page['page_number'] - 16}）", ""])
        for line in page["lines"]:
            key = (page["page_number"], line["line_number"])
            item = corrections.get(key)
            text = line["text"]
            suffix = ""
            if item:
                if item["ocr"] not in text:
                    raise ValueError(f"Baseline text does not match OCR at {key}: {item['id']}")
                text = text.replace(item["ocr"], item["source"], 1)
                suffix = f" <!-- {item['id']} -->"
                applied.append(item)
            output.append(f"<a id=\"pdf-{page['page_number']}-line-{line['line_number']}\"></a>{text}{suffix}")
        output.append("")

    output.extend(["## 已应用校勘记录", "", "| ID | PDF页/行 | 类型 | OCR候选 → 校勘后 |", "|---|---|---|---|"])
    for item in applied:
        output.append(
            f"| {item['id']} | {item['page']} / {item['line']} | {item['kind']} | {item['ocr']} → {item['source']} |"
        )

    Path(args.output).write_text("\n".join(output) + "\n", encoding="utf-8")
    print(f"applied_corrections={len(applied)}")


if __name__ == "__main__":
    main()
