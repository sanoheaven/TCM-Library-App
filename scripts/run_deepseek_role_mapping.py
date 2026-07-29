"""Request a constrained, page-anchored OCR role mapping from DeepSeek.

The script deliberately does not render Markdown or calculate audit conclusions.
Those operations belong to a separate deterministic validator and renderer.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ROLES = ["body", "commentary", "title", "diagram", "formula", "excluded"]

SYSTEM_PROMPT = """You are a constrained OCR structural annotator. Return only one JSON object.
Do not generate Markdown. Do not summarize. Do not claim validation, coverage, pairing, or visual confirmation.

For every supplied frozen OCR line, return exactly one object in `mappings`, in the same order:
{
  "pdf_page": integer,
  "line_number": integer,
  "text": "exact byte-for-byte copied source text",
  "role": one of body, commentary, title, diagram, formula, excluded,
  "role_evidence": {"basis": "text|coordinates|context|needs_human_review", "note": "brief"},
  "block_id": "stable commentary id" or null
}

Use `block_id` only for commentary. Continue the same block_id across pages when the supplied text and layout indicate the commentary continues. You cannot see page images: never use visual_confirmed or claim visual evidence. Use needs_human_review for uncertain boundaries or diagrams. Preserve every source text exactly; do not normalize punctuation, whitespace, or characters."""


def load_env_key(env_file: Path, key_name: str) -> str | None:
    if not env_file.exists():
        return None
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() == key_name:
            return value.strip().strip('"').strip("'")
    return None


def extract_json(text: str) -> dict[str, Any]:
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    payload = fenced.group(1) if fenced else text.strip()
    result = json.loads(payload)
    if not isinstance(result, dict) or not isinstance(result.get("mappings"), list):
        raise ValueError("DeepSeek response must be a JSON object with a mappings array")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ocr", required=True, type=Path)
    parser.add_argument("--page-start", required=True, type=int)
    parser.add_argument("--page-end", required=True, type=int)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--prior-mapping", type=Path)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--api-key-env", default="DEEPSEEK_API_KEY")
    parser.add_argument("--model", default="deepseek-chat")
    parser.add_argument("--base-url", default="https://api.deepseek.com/chat/completions")
    parser.add_argument("--max-tokens", type=int, default=16384)
    args = parser.parse_args()
    if args.page_start > args.page_end:
        raise ValueError("--page-start must not exceed --page-end")

    api_key = os.environ.get(args.api_key_env) or load_env_key(args.env_file, args.api_key_env)
    if not api_key:
        raise RuntimeError(f"Missing {args.api_key_env}; set it in the environment or {args.env_file}")

    ocr = json.loads(args.ocr.read_text(encoding="utf-8"))
    pages = [p for p in ocr["pages"] if args.page_start <= p["page_number"] <= args.page_end]
    if len(pages) != args.page_end - args.page_start + 1:
        raise ValueError("Requested OCR page range is incomplete")

    prior_context: dict[str, Any] | None = None
    if args.prior_mapping:
        prior = json.loads(args.prior_mapping.read_text(encoding="utf-8"))
        prior_mappings = prior.get("mappings", [])
        if not prior_mappings:
            raise ValueError("--prior-mapping has no mappings")
        tail = prior_mappings[-3:]
        prior_context = {
            "previous_page": tail[-1]["pdf_page"],
            "last_three_mappings": tail,
            "open_commentary_block_id": (
                tail[-1].get("block_id") if tail[-1].get("role") == "commentary" else None
            ),
            "instruction": (
                "If the new page continues the preceding commentary, reuse open_commentary_block_id exactly. "
                "If it does not continue, do not reuse it. This context is not visual confirmation."
            ),
        }

    source_lines = [
        {
            "pdf_page": page["page_number"],
            "line_number": line["line_number"],
            "text": line["text"],
            "box": line["box"],
        }
        for page in pages
        for line in page["lines"]
    ]
    user_payload = {
        "task": "Map each frozen OCR source line to one structural role.",
        "allowed_roles": ROLES,
        "source_lines": source_lines,
    }
    if prior_context:
        user_payload["previous_page_context"] = prior_context
    request_body = json.dumps(
        {
            "model": args.model,
            "temperature": 0,
            "max_tokens": args.max_tokens,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        args.base_url,
        data=request_body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            api_result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"DeepSeek request failed with HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"DeepSeek connection failed: {exc.reason}") from exc

    content = api_result["choices"][0]["message"]["content"]
    try:
        mapping = extract_json(content)
    except (ValueError, json.JSONDecodeError) as exc:
        raw_path = args.output.with_suffix(args.output.suffix + ".raw-response.txt")
        raw_path.write_text(content, encoding="utf-8")
        raise RuntimeError(f"DeepSeek returned invalid JSON; raw response saved to {raw_path}") from exc
    output = {
        "schema": "ocr_role_mapping_v1",
        "model": args.model,
        "api_model": api_result.get("model"),
        "api_finish_reason": api_result["choices"][0].get("finish_reason"),
        "source": {
            "ocr": str(args.ocr),
            "page_start": args.page_start,
            "page_end": args.page_end,
            "source_line_count": len(source_lines),
        },
        "mappings": mapping["mappings"],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"saved_mapping={args.output}")
    print(f"frozen_source_lines={len(source_lines)}")


if __name__ == "__main__":
    main()
