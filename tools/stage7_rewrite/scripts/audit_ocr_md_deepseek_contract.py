#!/usr/bin/env python3
"""Audit whether existing poster OCR text reaches DeepSeek text input.

This is a report-only contract audit for already downloaded / already paid
Stage7 process artifacts. It reads bounded C: report directories, checks
poster_ocr.json against llm_input.md, and writes only summary evidence.

No OCR execution, LLM/API call, Dajiala call, embedding call, vector/graph/DB
write, alias change, publish, cookie/token read, or D: scan.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "stage7_ocr_md_deepseek_contract_audit.v1"
DEFAULT_OUT_DIR = Path("reports/ocr_md_deepseek_contract_audit_20260518")
DEFAULT_PROCESS_ROOTS = [
    Path("reports/dajiala_paid_next100_process_20260516"),
    Path("reports/dajiala_paid_next100_wave02_process_20260516"),
    Path("reports/dajiala_paid_next100_wave03_process_20260516"),
    Path("reports/dajiala_paid_next100_wave04_process_20260516"),
    Path("reports/dajiala_paid_wave05_process_20260517"),
    Path("reports/dajiala_paid_wave06_process_20260517"),
]
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def reject_broad_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw in {"d:", "d:/", "/mnt/d", "/mnt/d/"}:
        raise ValueError(f"{label} refuses broad D root: {path}")
    if raw.startswith("d:/ddownload") or raw.startswith("d:/aidata"):
        raise ValueError(f"{label} refuses banned D subtree: {path}")


def read_json(path: Path) -> dict[str, Any]:
    reject_broad_d_path(path, "json")
    try:
        value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


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


def norm_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/")


def compact(value: Any, limit: int = 240) -> str:
    return " ".join(str(value or "").split())[:limit]


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_for_match(text: str) -> str:
    return "".join(re.findall(r"[\w\u4e00-\u9fff]+", text.lower(), flags=re.UNICODE))


def extract_markdown_section(markdown: str, heading: str = "## Poster OCR") -> str:
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


def article_root_from_meta(meta_path: Path) -> tuple[Path, Path]:
    raw_dir = meta_path.parent
    if raw_dir.name == "raw":
        return raw_dir.parent, raw_dir
    return raw_dir, raw_dir


def account_article_id(process_root: Path, article_dir: Path) -> tuple[str, str] | None:
    try:
        rel = article_dir.relative_to(process_root)
    except ValueError:
        return None
    parts = rel.parts
    if len(parts) < 2:
        return None
    return parts[0], parts[1]


def count_images(raw_dir: Path) -> dict[str, int]:
    image_dir = raw_dir / "images"
    local_image_count = 0
    gif_or_webp_count = 0
    if image_dir.exists() and image_dir.is_dir():
        for path in image_dir.iterdir():
            suffix = path.suffix.lower()
            if path.is_file() and suffix in IMAGE_SUFFIXES:
                local_image_count += 1
                if suffix in {".gif", ".webp"}:
                    gif_or_webp_count += 1
    frames_dir = raw_dir / ".poster_ocr_frames"
    frame_count = 0
    if frames_dir.exists() and frames_dir.is_dir():
        frame_count = sum(1 for path in frames_dir.iterdir() if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES)
    return {
        "local_image_count": local_image_count,
        "gif_or_webp_image_count": gif_or_webp_count,
        "poster_ocr_frame_count": frame_count,
    }


def iter_recovered_values(value: Any) -> list[str]:
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            out.extend(iter_recovered_values(item))
        return out
    if isinstance(value, dict):
        out = []
        for item in value.values():
            out.extend(iter_recovered_values(item))
        return out
    return []


def poster_text_parts(poster: dict[str, Any]) -> dict[str, Any]:
    plain_text = str(poster.get("plain_text") or "").strip()
    blocks = poster.get("blocks") or []
    block_texts = [str(block.get("text") or "").strip() for block in blocks if isinstance(block, dict)]
    block_texts = [text for text in block_texts if text]
    recovered_texts = iter_recovered_values(poster.get("recovered"))
    all_texts = [plain_text, *block_texts, *recovered_texts]
    combined = "\n".join(text for text in all_texts if text.strip())
    return {
        "plain_text_len": len(plain_text),
        "blocks_text_len": len("\n".join(block_texts)),
        "recovered_text_len": len("\n".join(recovered_texts)),
        "block_count": len(block_texts),
        "combined_text": combined,
    }


def text_matches_section(combined_text: str, section_text: str) -> bool:
    if not combined_text.strip() or not section_text.strip():
        return False
    section_norm = normalize_for_match(section_text)
    candidates = []
    for line in combined_text.splitlines():
        line_norm = normalize_for_match(line)
        if len(line_norm) >= 4:
            candidates.append(line_norm[:80])
    combined_norm = normalize_for_match(combined_text)
    if len(combined_norm) >= 4:
        candidates.append(combined_norm[:80])
    return any(candidate and candidate in section_norm for candidate in candidates)


def build_artifact_row(process_root: Path, meta_path: Path) -> dict[str, Any] | None:
    article_dir, raw_dir = article_root_from_meta(meta_path)
    account_art = account_article_id(process_root, article_dir)
    if not account_art:
        return None
    account, article_id = account_art
    meta = read_json(meta_path)
    poster_path = raw_dir / "poster_ocr.json"
    llm_input_path = raw_dir / "llm_input.md"
    poster = read_json(poster_path) if poster_path.exists() else {}
    parts = poster_text_parts(poster)
    combined_text = str(parts.pop("combined_text"))
    ocr_text_ready = bool(combined_text.strip())
    llm_input_exists = llm_input_path.exists()
    llm_text = llm_input_path.read_text(encoding="utf-8", errors="replace") if llm_input_exists else ""
    section_text = extract_markdown_section(llm_text) if llm_text else ""
    llm_has_section = bool(section_text or "## Poster OCR" in llm_text)
    llm_section_nonempty = bool(section_text.strip())
    ocr_text_in_llm_section = text_matches_section(combined_text, section_text)
    short_ocr_text_for_match = len(combined_text) < 32

    issue_types: list[str] = []
    if ocr_text_ready and not llm_input_exists:
        issue_types.append("missing_llm_input")
    if ocr_text_ready and llm_input_exists and not llm_has_section:
        issue_types.append("ocr_text_ready_but_missing_md_section")
    if ocr_text_ready and llm_has_section and not llm_section_nonempty:
        issue_types.append("ocr_text_ready_but_empty_md_section")
    if ocr_text_ready and llm_section_nonempty and not ocr_text_in_llm_section and not short_ocr_text_for_match:
        issue_types.append("ocr_text_ready_but_not_matched_in_md_section")

    row = {
        "article_uid": f"{account}/{article_id}",
        "article_id": article_id,
        "source_account": str(meta.get("account_name") or meta.get("account") or account),
        "title": compact(meta.get("title"), 300),
        "process_root": norm_path(process_root),
        "artifact_dir": norm_path(raw_dir),
        "meta_path": norm_path(meta_path),
        "poster_ocr_path": norm_path(poster_path) if poster_path.exists() else "",
        "llm_input_path": norm_path(llm_input_path) if llm_input_exists else "",
        "poster_ocr_exists": poster_path.exists(),
        "poster_ocr_backend": str(poster.get("backend") or ""),
        "poster_ocr_image_heavy": bool(poster.get("imageHeavy")),
        "ocr_text_ready": ocr_text_ready,
        "ocr_text_chars": len(combined_text),
        "ocr_text_sha256": sha256_text(combined_text) if combined_text else "",
        "llm_input_exists": llm_input_exists,
        "llm_input_chars": len(llm_text),
        "llm_has_poster_ocr_section": llm_has_section,
        "llm_poster_ocr_section_chars": len(section_text),
        "ocr_text_in_llm_section": ocr_text_in_llm_section,
        "short_ocr_text_for_match": short_ocr_text_for_match,
        "issue_types": issue_types,
        "text_copied": False,
    }
    row.update(parts)
    row.update(count_images(raw_dir))
    return row


def decision_from_counts(counts: dict[str, int]) -> str:
    if counts["scanned_artifacts"] == 0:
        return "ocr_md_deepseek_contract_insufficient_local_evidence"
    if counts["ocr_text_ready"] == 0:
        return "ocr_md_deepseek_contract_insufficient_ocr_text_evidence"
    if (
        counts["ocr_text_ready_but_missing_md_section"] > 0
        or counts["ocr_text_ready_but_empty_md_section"] > 0
        or counts["missing_llm_input"] > 0
    ):
        return "ocr_md_deepseek_contract_rebuild_required_existing_artifacts"
    if counts["ocr_text_ready_but_not_matched_in_md_section"] > 0:
        return "ocr_md_deepseek_contract_review_required_existing_artifacts"
    return "ocr_md_deepseek_contract_ready_existing_paid_artifacts"


def build_audit(process_roots: list[Path], out_dir: Path, max_artifacts: int = 0) -> dict[str, Any]:
    roots = [root.resolve() for root in process_roots if root.exists()]
    for root in roots:
        reject_broad_d_path(root, "process_root")

    rows: list[dict[str, Any]] = []
    skipped_meta = 0
    for root in roots:
        for meta_path in sorted(root.rglob("meta.json")):
            if max_artifacts and len(rows) >= max_artifacts:
                break
            row = build_artifact_row(root, meta_path)
            if row is None:
                skipped_meta += 1
                continue
            rows.append(row)

    issue_counts: Counter[str] = Counter()
    for row in rows:
        issue_counts.update(row.get("issue_types") or [])
    backend_counts = Counter(str(row.get("poster_ocr_backend") or "<missing>") for row in rows)
    root_counts = Counter(str(row.get("process_root") or "") for row in rows)
    counts = {
        "scanned_artifacts": len(rows),
        "skipped_meta": skipped_meta,
        "with_poster_ocr_file": sum(1 for row in rows if row.get("poster_ocr_exists")),
        "ocr_text_ready": sum(1 for row in rows if row.get("ocr_text_ready")),
        "llm_input_exists": sum(1 for row in rows if row.get("llm_input_exists")),
        "llm_has_poster_ocr_section": sum(1 for row in rows if row.get("llm_has_poster_ocr_section")),
        "llm_has_nonempty_poster_ocr_section": sum(1 for row in rows if int(row.get("llm_poster_ocr_section_chars") or 0) > 0),
        "ocr_text_in_llm_section": sum(1 for row in rows if row.get("ocr_text_in_llm_section")),
        "missing_llm_input": sum(1 for row in rows if "missing_llm_input" in (row.get("issue_types") or [])),
        "ocr_text_ready_but_missing_md_section": sum(
            1 for row in rows if "ocr_text_ready_but_missing_md_section" in (row.get("issue_types") or [])
        ),
        "ocr_text_ready_but_empty_md_section": sum(
            1 for row in rows if "ocr_text_ready_but_empty_md_section" in (row.get("issue_types") or [])
        ),
        "ocr_text_ready_but_not_matched_in_md_section": sum(
            1 for row in rows if "ocr_text_ready_but_not_matched_in_md_section" in (row.get("issue_types") or [])
        ),
        "short_ocr_text_match_unchecked": sum(
            1
            for row in rows
            if row.get("ocr_text_ready")
            and row.get("short_ocr_text_for_match")
            and int(row.get("llm_poster_ocr_section_chars") or 0) > 0
            and not row.get("ocr_text_in_llm_section")
        ),
        "gif_or_webp_image_rows": sum(1 for row in rows if int(row.get("gif_or_webp_image_count") or 0) > 0),
        "poster_ocr_frame_rows": sum(1 for row in rows if int(row.get("poster_ocr_frame_count") or 0) > 0),
    }
    decision = decision_from_counts(counts)
    review_rows = [
        {
            "article_uid": row["article_uid"],
            "artifact_dir": row["artifact_dir"],
            "poster_ocr_path": row["poster_ocr_path"],
            "llm_input_path": row["llm_input_path"],
            "issue_types": row["issue_types"],
            "ocr_text_chars": row["ocr_text_chars"],
            "ocr_text_sha256": row["ocr_text_sha256"],
            "llm_poster_ocr_section_chars": row["llm_poster_ocr_section_chars"],
            "poster_ocr_backend": row["poster_ocr_backend"],
            "text_copied": False,
            "recommended_action": "rebuild_llm_input_from_existing_poster_ocr" if row["issue_types"] else "none",
        }
        for row in rows
        if row.get("issue_types")
    ]

    out_dir.mkdir(parents=True, exist_ok=True)
    detail_path = out_dir / "ocr_md_deepseek_contract_rows.jsonl"
    review_path = out_dir / "review_queue.jsonl"
    report_path = out_dir / "ocr_md_deepseek_contract_audit.json"
    md_path = out_dir / "ocr_md_deepseek_contract_audit.md"
    write_jsonl(detail_path, rows)
    write_jsonl(review_path, review_rows)
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": True,
        "report_only": True,
        "decision": decision,
        "process_roots": [norm_path(root) for root in roots],
        "missing_process_roots": [norm_path(root) for root in process_roots if not root.exists()],
        "counts": counts,
        "issue_counts": dict(sorted(issue_counts.items())),
        "poster_ocr_backend_counts": dict(sorted(backend_counts.items())),
        "process_root_counts": dict(sorted(root_counts.items())),
        "outputs": {
            "report": norm_path(report_path),
            "markdown": norm_path(md_path),
            "rows": norm_path(detail_path),
            "review_queue": norm_path(review_path),
        },
        "allowed_next_actions": [
            "If rebuild_required, regenerate only llm_input.md/manifest from existing poster_ocr.json and local artifacts.",
            "If ready, continue downstream text-lane checks without paid Dajiala/API rerun.",
            "Keep GIF/WebP handling as local static-frame conversion before OCR.",
        ],
        "forbidden_next_actions": [
            "Do not start a new paid Dajiala wave for this audit result.",
            "Do not rerun DeepSeek extraction until missing/empty OCR markdown rows are rebuilt from existing artifacts.",
            "Do not copy raw OCR text into reports; use lengths and SHA-256 only.",
        ],
        "safety": {
            "ocr_execution": False,
            "paid_api_used": False,
            "llm_api_call": False,
            "qdrant_write": False,
            "neo4j_write": False,
            "mem0_write": False,
            "production_write": False,
            "d_scan": False,
            "text_copied_to_reports": False,
        },
        "writes": "reports_only",
    }
    write_json(report_path, report)
    write_markdown(md_path, report)
    return report


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    counts = report["counts"]
    lines = [
        "# OCR to Markdown to DeepSeek Contract Audit",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- decision: `{report['decision']}`",
        f"- report_only: `{report['report_only']}`",
        f"- scanned_artifacts: `{counts['scanned_artifacts']}`",
        f"- ocr_text_ready: `{counts['ocr_text_ready']}`",
        f"- llm_has_poster_ocr_section: `{counts['llm_has_poster_ocr_section']}`",
        f"- llm_has_nonempty_poster_ocr_section: `{counts['llm_has_nonempty_poster_ocr_section']}`",
        f"- ocr_text_in_llm_section: `{counts['ocr_text_in_llm_section']}`",
        f"- missing_llm_input: `{counts['missing_llm_input']}`",
        f"- missing_md_section: `{counts['ocr_text_ready_but_missing_md_section']}`",
        f"- empty_md_section: `{counts['ocr_text_ready_but_empty_md_section']}`",
        f"- unmatched_md_section: `{counts['ocr_text_ready_but_not_matched_in_md_section']}`",
        f"- short_ocr_text_match_unchecked: `{counts['short_ocr_text_match_unchecked']}`",
        f"- gif_or_webp_image_rows: `{counts['gif_or_webp_image_rows']}`",
        f"- poster_ocr_frame_rows: `{counts['poster_ocr_frame_rows']}`",
        "",
        "## Outputs",
        "",
    ]
    for key, value in report["outputs"].items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Allowed Next Actions", ""])
    for item in report["allowed_next_actions"]:
        lines.append(f"- {item}")
    lines.extend(["", "## Forbidden Next Actions", ""])
    for item in report["forbidden_next_actions"]:
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Existing local/paid artifacts only.",
            "- No OCR execution, paid API call, DeepSeek call, vector/graph/DB write, publish, or D: scan.",
            "- Detail and review files store metadata, lengths, issue types, and SHA-256; they do not copy OCR text.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--process-root", action="append", type=Path, default=[])
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--max-artifacts", type=int, default=0)
    parser.add_argument("--report-only-exit-zero", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    roots = args.process_root or DEFAULT_PROCESS_ROOTS
    report = build_audit(roots, args.out_dir, max_artifacts=args.max_artifacts)
    print(
        json.dumps(
            {
                "ok": report["ok"],
                "decision": report["decision"],
                "counts": report["counts"],
                "report": report["outputs"]["report"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if report["ok"] or args.report_only_exit_zero else 2


if __name__ == "__main__":
    raise SystemExit(main())
