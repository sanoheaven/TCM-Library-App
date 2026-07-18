"""Write reviewable Markdown and sidecar evidence files."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


LIBRARY_ROOT = Path(r"D:\TCM-Library")


def content_boundary_status(source_type: str) -> str:
    """Journal downloads can include the next article on their final page."""

    return "unverified" if source_type == "JRN" else "whole_document_assumed"


def _write_table_csv(table: dict[str, Any], table_path: Path) -> None:
    with table_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        for row in table.get("rows", []):
            writer.writerow(row or [])


def _render_table_crop(pdf_path: Path, bbox: list[float], destination: Path) -> str | None:
    """Keep a visual table candidate whenever the local renderer supports it."""

    try:
        import pdfplumber

        page_number = int(destination.stem[1:4])
        with pdfplumber.open(pdf_path) as pdf:
            page = pdf.pages[page_number - 1]
            page.crop(tuple(bbox)).to_image(resolution=150).save(destination, format="PNG")
        return None
    except Exception as exc:
        return f"table_crop_not_generated: {exc}"


def build_tongue_asset_candidates(
    document_id: str, pdf_path: Path, pages: list[dict[str, Any]]
) -> dict[str, Any]:
    """Create candidate-only evidence links; never auto-classify a figure as a tongue image."""

    candidates: list[dict[str, Any]] = []
    for page in pages:
        page_number = page["page_number"]
        for image in page.get("image_candidates", []):
            if image["kind"] != "embedded_figure_candidate":
                continue
            ordinal = image["ordinal"]
            candidates.append(
                {
                    "asset_id": f"{document_id}-TONGUE-P{page_number:03d}-I{ordinal:02d}",
                    "candidate_status": "needs_human_pairing",
                    "source_pdf": str(pdf_path),
                    "source_page": page_number,
                    "source_locator": f"<!-- source: {document_id} | page: {page_number:03d} -->",
                    "image_evidence": "embedded_figure_candidate",
                    "source_bbox": image["bbox"],
                    "image_crop_file": None,
                    "source_description_quote": None,
                    "description_page": None,
                    "description_locator": None,
                    "diagnostic_context_quote": None,
                    "expert_review": None,
                    "rights_status": "not_reviewed",
                    "quality_status": "not_reviewed",
                    "notes": "Confirm image and exact source description before any Ingest or model use.",
                }
            )
        if page["full_page_raster_count"]:
            candidates.append(
                {
                    "asset_id": f"{document_id}-SCAN-P{page_number:03d}",
                    "candidate_status": "needs_visual_triage",
                    "candidate_kind": "full_page_scan_visual_triage",
                    "source_pdf": str(pdf_path),
                    "source_page": page_number,
                    "source_locator": f"<!-- source: {document_id} | page: {page_number:03d} -->",
                    "image_evidence": "full_page_raster",
                    "preview_file": f"scan-index/p{page_number:03d}.png",
                    "source_bbox": None,
                    "image_crop_file": None,
                    "source_description_quote": None,
                    "description_page": None,
                    "description_locator": None,
                    "diagnostic_context_quote": None,
                    "expert_review": None,
                    "rights_status": "not_reviewed",
                    "quality_status": "not_reviewed",
                    "notes": "This is a scanned page, not an automatic tongue-image claim. Visually confirm a tongue image and its exact original description before any Ingest or model use.",
                }
            )
    return {
        "asset_registry_version": "0.1",
        "document_id": document_id,
        "source_pdf": str(pdf_path),
        "status": "candidate_only",
        "human_pairing_required": True,
        "candidate_images": candidates,
        "full_page_raster_pages_requiring_visual_review": [
            page["page_number"] for page in pages if page["full_page_raster_count"]
        ],
    }


def _write_scan_page_index(
    pdf_path: Path, pages: list[dict[str, Any]], output_dir: Path
) -> list[str]:
    """Write low-resolution review previews for full-page scans; source PDF remains authoritative."""

    scan_pages = [page["page_number"] for page in pages if page["full_page_raster_count"]]
    if not scan_pages:
        return []
    warnings: list[str] = []
    destination = output_dir / "scan-index"
    destination.mkdir(exist_ok=True)
    try:
        import pdfplumber

        with pdfplumber.open(pdf_path) as pdf:
            for page_number in scan_pages:
                try:
                    pdf.pages[page_number - 1].to_image(resolution=72).save(
                        destination / f"p{page_number:03d}.png", format="PNG"
                    )
                except Exception as exc:
                    warnings.append(f"scan_preview_not_generated_p{page_number:03d}: {exc}")
    except Exception as exc:
        warnings.append(f"scan_preview_index_not_generated: {exc}")
    return warnings


def write_review_package(
    pdf_path: Path,
    document_id: str,
    source_type: str,
    extraction: dict[str, Any],
) -> Path:
    category = pdf_path.parent.name if pdf_path.parent.name.startswith("0") else source_type
    output_dir = LIBRARY_ROOT / "09_Markdown" / category / document_id
    tables_dir = output_dir / "tables"
    figures_dir = output_dir / "figures"
    metadata_dir = LIBRARY_ROOT / "11_Metadata"
    output_dir.mkdir(parents=True, exist_ok=True)
    tables_dir.mkdir(exist_ok=True)
    figures_dir.mkdir(exist_ok=True)
    metadata_dir.mkdir(parents=True, exist_ok=True)
    boundary_status = content_boundary_status(source_type)

    all_warnings = list(extraction["warnings"])
    markdown: list[str] = [
        "---",
        f'document_id: "{document_id}"',
        f'source_type: "{source_type}"',
        f'source_pdf: "{pdf_path}"',
        f"page_count: {extraction['page_count']}",
        f'content_boundary_status: "{boundary_status}"',
        'status: "needs_review"',
        f'pipeline_version: "{extraction["pipeline_version"]}"',
        "---",
        "",
        f"# {pdf_path.stem}",
        "",
        "> [!warning] 转换产物，非正式知识来源",
        "> 表格、图像、OCR 与引文映射必须按转换报告人工复核后，才可作为 Ingest 证据。",
        "",
    ]
    if boundary_status == "unverified":
        markdown.extend(
            [
                "> [!warning] 期刊文章边界未核验",
                "> PDF 末页可能已包含下一篇文章。确认目标文章的起止页之前，不得对整份 PDF 做 AI 语义提取或 Ingest。",
                "",
            ]
        )

    for page in extraction["pages"]:
        page_number = page["page_number"]
        markdown.extend(
            [
                f"<!-- source: {document_id} | page: {page_number:03d} -->",
                "",
                f"## 第 {page_number} 页",
                "",
                page["text"] or "[OCR待核：本页未提取到可用文本]",
                "",
            ]
        )
        for table in page["tables"]:
            if "warning" in table:
                all_warnings.append(table["warning"])
                continue
            table_name = f"p{page_number:03d}_t{table['number']:02d}"
            csv_path = tables_dir / f"{table_name}.csv"
            image_path = figures_dir / f"{table_name}.png"
            _write_table_csv(table, csv_path)
            crop_warning = _render_table_crop(pdf_path, table["bbox"], image_path)
            if crop_warning:
                all_warnings.append(crop_warning)
            markdown.extend(
                [
                    "> [!warning] 表格候选，必须人工复核",
                    f"> 单元格候选：`tables/{csv_path.name}`；原页裁剪：`figures/{image_path.name}`。",
                    "> 不得在未复核前将该表格转写为知识结论。",
                    "",
                ]
            )
        if page["figure_candidate_count"]:
            markdown.extend(
                [
                    "> [!warning] 本页含图像/图版候选",
                    "> 舌象图、图注与示意图须保留原页定位并人工复核；本次未自动解释图像。",
                    "",
                ]
            )
        if page["full_page_raster_count"]:
            markdown.extend(
                [
                    "> [!warning] 整页扫描/光栅底图",
                    "> 本页的纯文本不保留可靠版面结构；表格、图注和引文须以原 PDF 视觉复核为准。",
                    "",
                ]
            )
        if page["table_labels"] and not page["tables"]:
            labels = "、".join(page["table_labels"])
            markdown.extend(
                [
                    "> [!warning] 未结构化表格候选",
                    f"> 已识别表题：{labels}；未提取到可靠单元格，禁止将本页文字当作完整表格数据。",
                    "",
                ]
            )

    document_path = output_dir / "document.md"
    document_path.write_text("\n".join(markdown), encoding="utf-8")

    tongue_assets = build_tongue_asset_candidates(document_id, pdf_path, extraction["pages"])
    all_warnings.extend(_write_scan_page_index(pdf_path, extraction["pages"], output_dir))
    tongue_assets_path = output_dir / "tongue-asset-candidates.json"
    tongue_assets_path.write_text(json.dumps(tongue_assets, ensure_ascii=False, indent=2), encoding="utf-8")

    report_lines = [
        f"# {document_id} 转换报告",
        "",
        f"- 原始文件：`{pdf_path}`",
        f"- 页数：{extraction['page_count']}",
        f"- 页级文本锚点：{len(extraction['pages'])}",
        f"- 表格候选：{sum(len(page['tables']) for page in extraction['pages'])}",
        f"- 未结构化表题：{sum(len(page['table_labels']) for page in extraction['pages'])}",
        f"- 图版候选页：{sum(1 for page in extraction['pages'] if page['figure_candidate_count'])}",
        f"- 整页扫描底图页：{sum(1 for page in extraction['pages'] if page['full_page_raster_count'])}",
        f"- 引文标记：{sum(len(page['citation_markers']) for page in extraction['pages'])}",
        f"- 文章边界状态：{boundary_status}",
        f"- 舌诊图文配对/扫描页筛选候选：{len(tongue_assets['candidate_images'])}（仅候选，须人工确认）",
        "",
        "## 警告",
    ]
    report_lines.extend(f"- {warning}" for warning in sorted(set(all_warnings)) or ["- 无自动警告；仍需人工审阅高风险内容。"])
    report_lines.extend(["", "## 人工复核", "", "- [ ] 目标文章起止页已确认（期刊 PDF 必填）", "- [ ] 页码与原始 PDF 对齐", "- [ ] 高风险表格已核对", "- [ ] 舌象图/图注已核对", "- [ ] 引文与文末参考文献已映射", "- [ ] 可进入 Ingest 的范围已确认"])
    (output_dir / "conversion-report.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    manifest = {
        "document_id": document_id,
        "source_type": source_type,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "review_status": "needs_review",
        "content_boundary_status": boundary_status,
        "extraction": extraction,
        "warnings": sorted(set(all_warnings)),
        "tongue_asset_candidates": {
            "path": str(tongue_assets_path),
            "count": len(tongue_assets["candidate_images"]),
            "status": "candidate_only",
        },
    }
    (metadata_dir / f"{document_id}.manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return output_dir
