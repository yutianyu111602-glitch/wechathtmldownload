#!/usr/bin/env python3
"""Build the OCR -> Markdown -> DeepSeek Flash reprocess lane plan.

Report-only planner. It reads existing Stage7 reports and writes bounded
manifest artifacts. It does not run OCR, Dajiala, DeepSeek, vector, graph,
SQLite, publish, or broad D: scans.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "stage7_ocr_markitdown_flash_reprocess_plan.v1"
DEFAULT_OUT_DIR = ROOT / "reports" / "ocr_markitdown_flash_reprocess_plan_20260518"
DEFAULT_OCR_INDEX_SUMMARY = (
    ROOT / "reports" / "dajiala_paid_latest_verified_combined_ocr_index_20260518" / "ocr_file_index_summary.json"
)
DEFAULT_V6_P1 = (
    ROOT / "reports" / "v6_image_bucket_loss_audit_20260518" / "v6_image_bucket_p1_likely_visual_missing.jsonl"
)
DEFAULT_EXTERNAL_QUEUE = (
    ROOT
    / "reports"
    / "stage7_external_data_roots_validation_20260518"
    / "external_data_roots_validation_queue.jsonl"
)
DEFAULT_MARKITDOWN_PYTHON = Path.home() / ".venvs" / "stage7-markitdown" / "Scripts" / "python.exe"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def compact(value: Any, limit: int = 240) -> str:
    return " ".join(str(value or "").split())[:limit]


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def iter_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        tmp = Path(handle.name)
    tmp.replace(path)


def resolve_stage7_path(value: Any) -> Path:
    raw = str(value or "").strip()
    if not raw:
        return Path()
    normalized = raw.replace("\\", "/")
    if normalized.startswith("/mnt/") and len(normalized) > 7:
        drive = normalized[5]
        if drive.isalpha() and normalized[6] == "/":
            return Path(f"{drive.upper()}:/" + normalized[7:])
    path = Path(raw)
    if path.is_absolute():
        return path
    if normalized.startswith("tools/stage7_rewrite/"):
        return ROOT.parent.parent / normalized
    return ROOT / path


def markdown_section(markdown: str, heading: str = "## Poster OCR") -> str:
    lines = markdown.splitlines()
    collecting = False
    body: list[str] = []
    for line in lines:
        if collecting and line.startswith("## "):
            break
        if collecting:
            body.append(line)
            continue
        if line.strip() == heading:
            collecting = True
    return "\n".join(body).strip()


def poster_text_chars(poster_path: Path) -> int:
    poster = read_json(poster_path)
    if not poster:
        return 0
    parts: list[str] = []
    plain = poster.get("plain_text")
    if isinstance(plain, str):
        parts.append(plain)
    blocks = poster.get("blocks")
    if isinstance(blocks, list):
        for block in blocks:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
    recovered = poster.get("recovered")
    if isinstance(recovered, dict):
        for value in recovered.values():
            if isinstance(value, str):
                parts.append(value)
            elif isinstance(value, list):
                parts.extend(str(item) for item in value if str(item).strip())
    return len("\n".join(part for part in parts if str(part).strip()))


def read_meta_title(meta_path: Path) -> str:
    meta = read_json(meta_path)
    for key in ("title", "article_title", "name"):
        value = meta.get(key)
        if isinstance(value, str) and value.strip():
            return compact(value, 200)
    return ""


def markitdown_status() -> dict[str, Any]:
    isolated_python = Path(os.environ.get("STAGE7_MARKITDOWN_PYTHON") or DEFAULT_MARKITDOWN_PYTHON)
    return {
        "python_module_available": importlib.util.find_spec("markitdown") is not None,
        "cli_available": shutil.which("markitdown") is not None,
        "isolated_python_path": str(isolated_python).replace("\\", "/"),
        "isolated_python_available": isolated_python.exists(),
    }


def bucket_for(chars: int, local_images: int) -> str:
    if chars <= 80:
        size = "tiny"
    elif chars <= 512:
        size = "short"
    elif chars <= 1800:
        size = "medium"
    elif chars <= 5000:
        size = "long"
    else:
        size = "xlong"
    return f"ready:{size}:{'image' if local_images else 'text'}"


def build_verified_ocr_rows(index_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], Counter[str], Counter[str]]:
    rows: list[dict[str, Any]] = []
    skipped: Counter[str] = Counter()
    accounts: Counter[str] = Counter()
    for row in index_rows:
        if row.get("ocr_status") != "complete":
            skipped["ocr_not_complete"] += 1
            continue
        llm_input_path = resolve_stage7_path(row.get("llm_input_path"))
        meta_path = resolve_stage7_path(row.get("meta_path"))
        poster_path = resolve_stage7_path(row.get("poster_ocr_path"))
        if not llm_input_path.exists():
            skipped["missing_llm_input"] += 1
            continue
        if not meta_path.exists():
            skipped["missing_meta"] += 1
            continue
        if not poster_path.exists():
            skipped["missing_poster_ocr"] += 1
            continue

        llm_text = llm_input_path.read_text(encoding="utf-8", errors="replace")
        section = markdown_section(llm_text)
        section_chars = len(section)
        ocr_chars = poster_text_chars(poster_path)
        if "## Poster OCR" not in llm_text:
            skipped["missing_poster_ocr_section"] += 1
        if section_chars <= 0:
            skipped["empty_poster_ocr_section"] += 1

        local_images = int(row.get("local_image_count") or row.get("processed_asset_image_count") or 0)
        account = str(row.get("source_account") or "")
        accounts[account] += 1
        input_chars = len(llm_text)
        rows.append(
            {
                "status": "pending",
                "article_uid": str(row.get("article_uid") or ""),
                "source_account": account,
                "article_id": str(row.get("article_id") or ""),
                "title": read_meta_title(meta_path),
                "input_chars": input_chars,
                "quality_grade": "ready",
                "local_image_count": local_images,
                "bucket": bucket_for(input_chars, local_images),
                "llm_input_path": str(llm_input_path).replace("\\", "/"),
                "meta_path": str(meta_path).replace("\\", "/"),
                "poster_ocr_path": str(poster_path).replace("\\", "/"),
                "poster_ocr_text_chars": ocr_chars,
                "llm_poster_ocr_section_chars": section_chars,
                "has_ocr_before_markdown_contract": section_chars > 0 and ocr_chars > 0,
                "reprocess_lane": "verified_paid_ocr_markdown_flash",
                "allow_no_info_after_flash": True,
                "no_info_rule": "allowed_only_after_ocr_markdown_evidence_reaches_llm_input",
            }
        )
    return rows, skipped, accounts


def select_balanced_canary(rows: list[dict[str, Any]], limit: int, max_per_account: int) -> list[dict[str, Any]]:
    preferred = [
        row
        for row in rows
        if row.get("has_ocr_before_markdown_contract")
        and int(row.get("local_image_count") or 0) > 0
        and int(row.get("poster_ocr_text_chars") or 0) > 0
    ]
    preferred.sort(
        key=lambda row: (
            str(row.get("source_account") or ""),
            -int(row.get("local_image_count") or 0),
            int(row.get("input_chars") or 0),
            str(row.get("article_id") or ""),
        )
    )
    selected: list[dict[str, Any]] = []
    account_counts: Counter[str] = Counter()
    for row in preferred:
        account = str(row.get("source_account") or "")
        if account_counts[account] >= max_per_account:
            continue
        selected.append(row)
        account_counts[account] += 1
        if len(selected) >= limit:
            break
    return selected


def build_v6_targets(p1_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    for row in p1_rows:
        targets.append(
            {
                "article_uid": str(row.get("article_uid") or ""),
                "article_id": str(row.get("article_id") or ""),
                "source_account": str(row.get("source_account") or ""),
                "title": compact(row.get("title"), 200),
                "priority": str(row.get("priority") or "P1_likely_visual_info_missing"),
                "local_image_count": int(row.get("local_image_count") or 0),
                "legacy_llm_input_path": str(row.get("llm_input_path") or ""),
                "legacy_flash_input_chars": int(row.get("input_chars") or 0),
                "legacy_flash_output_count": int(row.get("output_count") or 0),
                "risk_flags": row.get("risk_flags") or [],
                "required_next_action": "locate_local_images_or_recapture_then_ocr_then_markdown_then_flash",
                "direct_flash_without_ocr": "forbidden",
                "direct_ingest": "forbidden",
            }
        )
    return targets


def build_external_rows(external_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in external_rows:
        required_gates = list(row.get("required_gates") or [])
        if "ocr_before_markdown_deepseek_contract" not in required_gates:
            required_gates.append("ocr_before_markdown_deepseek_contract")
        out.append(
            {
                "root_id": row.get("root_id"),
                "root_path": row.get("root_path"),
                "candidate_kind": row.get("candidate_kind"),
                "exists": bool(row.get("exists")),
                "trust_status": "unverified_candidate_do_not_ingest_directly",
                "eligible_for_flash_now": False,
                "planned_lane": "validate_source_identity_dedupe_then_ocr_markdown_flash",
                "forbidden_next_action": "direct_ingest_or_direct_flash_without_ocr_markdown_contract",
                "required_gates": required_gates,
                "top_extensions": row.get("top_extensions") or {},
                "total_files_scanned": int(row.get("total_files_scanned") or 0),
                "truncated_by_file_cap": bool(row.get("truncated_by_file_cap")),
            }
        )
    return out


def write_markdown(path: Path, summary: dict[str, Any]) -> None:
    counts = summary["counts"]
    safety = summary["safety"]
    markitdown = summary["markitdown"]
    lines = [
        "# OCR -> Markdown -> DeepSeek Flash Reprocess Plan",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{summary['decision']}`",
        f"- verified_paid_ocr_rows: `{counts['verified_paid_ocr_rows']}`",
        f"- canary_manifest_rows: `{counts['canary_manifest_rows']}`",
        f"- v6_p1_targets: `{counts['v6_p1_targets']}`",
        f"- external_candidate_roots: `{counts['external_candidate_roots']}`",
        f"- markitdown_python_module_available: `{markitdown['python_module_available']}`",
        f"- markitdown_cli_available: `{markitdown['cli_available']}`",
        f"- markitdown_isolated_python_available: `{markitdown['isolated_python_available']}`",
        f"- markitdown_isolated_python_path: `{markitdown['isolated_python_path']}`",
        "",
        "## Policy",
        "",
        "- No-info output is allowed only after image/GIF evidence has gone through OCR, the OCR text is merged into Markdown, and DeepSeek Flash sees that Markdown evidence.",
        "- Existing text-only Flash rows with images remain baseline, not proof that poster facts were absent.",
        "- External/user-supplied roots are validation-only candidates until source identity, dedupe, hash, and OCR-before-Markdown gates pass.",
        "- GIF/WebP candidates require static-frame extraction before OCR.",
        "- Chinese/mixed poster text should use the Chinese OCR lane; English-only text may use the English OCR fallback.",
        "",
        "## Safety",
        "",
    ]
    for key, value in safety.items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(
        [
            "",
            "## Outputs",
            "",
        ]
    )
    for key, value in summary["outputs"].items():
        lines.append(f"- {key}: `{value}`")
    write_text(path, "\n".join(lines) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--ocr-index-summary", type=Path, default=DEFAULT_OCR_INDEX_SUMMARY)
    parser.add_argument("--v6-p1-jsonl", type=Path, default=DEFAULT_V6_P1)
    parser.add_argument("--external-queue-jsonl", type=Path, default=DEFAULT_EXTERNAL_QUEUE)
    parser.add_argument("--canary-limit", type=int, default=12)
    parser.add_argument("--canary-max-per-account", type=int, default=2)
    args = parser.parse_args(argv)

    out_dir = args.out_dir if args.out_dir.is_absolute() else ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    ocr_summary = read_json(args.ocr_index_summary)
    index_path = resolve_stage7_path(ocr_summary.get("index_path"))
    index_rows = iter_jsonl(index_path)
    verified_rows, skipped, accounts = build_verified_ocr_rows(index_rows)
    canary = select_balanced_canary(
        verified_rows,
        limit=max(0, args.canary_limit),
        max_per_account=max(1, args.canary_max_per_account),
    )
    v6_targets = build_v6_targets(iter_jsonl(args.v6_p1_jsonl))
    external = build_external_rows(iter_jsonl(args.external_queue_jsonl))

    verified_path = out_dir / "verified_paid_ocr_flash_reprocess_manifest.jsonl"
    canary_path = out_dir / "canary_manifest.jsonl"
    v6_path = out_dir / "v6_p1_ocr_markdown_flash_targets.jsonl"
    external_path = out_dir / "external_candidate_roots_ocr_markdown_flash_validation.jsonl"
    summary_path = out_dir / "ocr_markitdown_flash_reprocess_plan.json"
    markdown_path = out_dir / "ocr_markitdown_flash_reprocess_plan.md"

    write_jsonl(verified_path, verified_rows)
    write_jsonl(canary_path, canary)
    write_jsonl(v6_path, v6_targets)
    write_jsonl(external_path, external)

    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": "ocr_markdown_flash_reprocess_lane_ready_report_only",
        "policy": {
            "allow_no_info": "allowed_only_after_ocr_markdown_flash_evidence_path",
            "required_order": [
                "validate_source_identity_and_dedupe",
                "extract_static_frames_for_gif_or_webp",
                "ocr_images_with_language_appropriate_model",
                "merge_ocr_into_markdown_llm_input",
                "deepseek_flash_reprocess",
                "only_then_accept_no_info_or_empty_result",
            ],
            "direct_flash_on_pre_ocr_markdown": "forbidden",
            "direct_external_root_ingest": "forbidden",
        },
        "counts": {
            "ocr_index_input_rows": len(index_rows),
            "verified_paid_ocr_rows": len(verified_rows),
            "verified_paid_ocr_skipped": dict(sorted(skipped.items())),
            "canary_manifest_rows": len(canary),
            "v6_p1_targets": len(v6_targets),
            "external_candidate_roots": len(external),
        },
        "top_verified_ocr_accounts": dict(accounts.most_common(25)),
        "markitdown": markitdown_status(),
        "safety": {
            "report_only": True,
            "d_drive_scan": False,
            "ocr_execution": False,
            "deepseek_api_call": False,
            "dajiala_paid_api": False,
            "qdrant_write": False,
            "neo4j_write": False,
            "sqlite_write": False,
            "publish": False,
            "secret_read": False,
        },
        "outputs": {
            "verified_paid_ocr_manifest": str(verified_path.relative_to(ROOT)).replace("\\", "/"),
            "canary_manifest": str(canary_path.relative_to(ROOT)).replace("\\", "/"),
            "v6_p1_targets": str(v6_path.relative_to(ROOT)).replace("\\", "/"),
            "external_candidate_roots": str(external_path.relative_to(ROOT)).replace("\\", "/"),
            "summary_json": str(summary_path.relative_to(ROOT)).replace("\\", "/"),
            "summary_md": str(markdown_path.relative_to(ROOT)).replace("\\", "/"),
        },
        "next_gate": {
            "canary": "run stage7_deepseek_flash_pilot select-only then small direct DeepSeek Flash run",
            "v6_p1": "locate/recapture local images before any Flash rerun",
            "external_roots": "build bounded validation manifests; do not trust root content directly",
        },
    }
    write_json(summary_path, summary)
    write_markdown(markdown_path, summary)
    print(json.dumps({"ok": True, **summary["counts"], "out_dir": str(out_dir)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
