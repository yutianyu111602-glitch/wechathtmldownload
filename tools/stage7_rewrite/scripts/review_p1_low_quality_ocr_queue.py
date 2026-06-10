#!/usr/bin/env python3
"""Review P1 low-quality OCR rows before any Flash/graph spend.

The queue has non-empty OCR text but failed the OCR quality gate. This script
does deterministic triage only: it reads the exact queue rows and existing row
metrics, then writes review buckets. It does not call LLMs, run OCR, scan D:
roots, or write graph/vector/product stores.
"""
from __future__ import annotations

import argparse
import json
import re
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


SCRIPT_PATH = Path(__file__).resolve()
STAGE7_ROOT = SCRIPT_PATH.parents[1]
REPORTS = STAGE7_ROOT / "reports"
DEFAULT_INPUT = (
    REPORTS
    / "v6_p1_existing_ocr_locator_after_stage10_global_ocr_20260519"
    / "v6_p1_existing_ocr_low_quality_text_review_needed.jsonl"
)
DEFAULT_OUT_DIR = REPORTS / "p1_low_quality_ocr_review_20260519"
SCHEMA_VERSION = "stage7_p1_low_quality_ocr_review.v1"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_no, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            row = json.loads(stripped)
            if isinstance(row, dict):
                row["_review_source_line"] = line_no
                yield row


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
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


def meaningful_chars(text: str) -> int:
    return len(re.findall(r"[0-9A-Za-z\u4e00-\u9fff]", text or ""))


def read_poster_text(path_text: str) -> tuple[str, str]:
    path = Path(path_text)
    if not path.exists():
        return "", "poster_ocr_missing"
    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return "", "poster_ocr_unreadable"
    parts: list[str] = []
    plain = payload.get("plain_text")
    if isinstance(plain, str) and plain.strip():
        parts.append(plain.strip())
    for block in payload.get("blocks") or []:
        if isinstance(block, dict) and str(block.get("text") or "").strip():
            parts.append(str(block["text"]).strip())
    text = "\n".join(parts).strip()
    return text, str(payload.get("backend") or "")


def classify(row: dict[str, Any]) -> dict[str, Any]:
    text, backend = read_poster_text(str(row.get("poster_ocr_path") or ""))
    ocr_chars = int(row.get("poster_ocr_text_chars") or len(text))
    chars = max(ocr_chars, meaningful_chars(text))
    flash_events = int(row.get("flash_events") or 0)
    flash_entities = int(row.get("flash_entities") or 0)
    if chars < 8:
        decision = "reject_low_signal_ocr_text"
        bucket = "rejected_low_signal"
        next_action = "Do not send to Flash/graph; no usable OCR evidence survived review."
    elif chars >= 12 and flash_events > 0:
        decision = "source_review_candidate_event_context"
        bucket = "source_review_candidate"
        next_action = "Review source context or higher-quality image evidence before any Flash rerun."
    elif chars >= 12:
        decision = "source_review_candidate_entity_context"
        bucket = "source_review_candidate"
        next_action = "Review source context; existing OCR is still not accepted as direct Markdown evidence."
    else:
        decision = "manual_review_low_signal"
        bucket = "manual_review_low_signal"
        next_action = "Manual/source-context review only; do not auto-run Flash."
    return {
        "schema_version": f"{SCHEMA_VERSION}.row",
        "article_uid": row.get("article_uid"),
        "article_id": row.get("article_id"),
        "source_account": row.get("source_account"),
        "title": row.get("title"),
        "poster_ocr_path": row.get("poster_ocr_path"),
        "llm_input_path": row.get("llm_input_path"),
        "poster_ocr_text_chars": ocr_chars,
        "meaningful_chars": chars,
        "poster_ocr_backend": backend or row.get("poster_ocr_backend"),
        "flash_entities": flash_entities,
        "flash_events": flash_events,
        "flash_output_count": int(row.get("flash_output_count") or 0),
        "recommended_ocr_mode": row.get("recommended_ocr_mode"),
        "bucket": bucket,
        "decision": decision,
        "automatic_flash_allowed": False,
        "accepted_for_graph": False,
        "next_action": next_action,
        "review_source_line": row.get("_review_source_line"),
        "evidence": {
            "has_local_image_evidence": bool(row.get("has_local_image_evidence")),
            "poster_ocr_quality_accepted": bool(row.get("poster_ocr_quality_accepted")),
            "merge_ocr_markdown_flash_ready": bool(row.get("merge_ocr_markdown_flash_ready")),
        },
    }


def render_markdown(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    lines = [
        "# P1 Low-Quality OCR Review",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{summary['decision']}`",
        f"- input_rows: `{counts['input_rows']}`",
        f"- source_review_candidate_rows: `{counts['source_review_candidate_rows']}`",
        f"- manual_review_low_signal_rows: `{counts['manual_review_low_signal_rows']}`",
        f"- rejected_low_signal_rows: `{counts['rejected_low_signal_rows']}`",
        f"- accepted_for_markdown_flash_rows: `{counts['accepted_for_markdown_flash_rows']}`",
        "",
        "## Interpretation",
        "",
        "No row is automatically accepted for Markdown/Flash. This preserves previous paid and LLM work by routing weak OCR text to source-context review instead of model reruns.",
        "",
        "## Safety",
        "",
    ]
    for key, value in sorted(summary["safety"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.append("")
    return "\n".join(lines)


def build(input_path: Path, out_dir: Path) -> dict[str, Any]:
    rows = [classify(row) for row in iter_jsonl(input_path)]
    buckets = Counter(row["bucket"] for row in rows)
    accepted = [row for row in rows if row["automatic_flash_allowed"]]
    source_review = [row for row in rows if row["bucket"] == "source_review_candidate"]
    manual = [row for row in rows if row["bucket"] == "manual_review_low_signal"]
    rejected = [row for row in rows if row["bucket"] == "rejected_low_signal"]
    out_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "review_rows": out_dir / "review_rows.jsonl",
        "source_review_candidates": out_dir / "source_review_candidates.jsonl",
        "manual_review_low_signal": out_dir / "manual_review_low_signal.jsonl",
        "rejected_low_signal": out_dir / "rejected_low_signal.jsonl",
        "accepted_for_markdown_flash": out_dir / "accepted_for_markdown_flash.jsonl",
        "summary_json": out_dir / "low_quality_ocr_review_summary.json",
        "summary_md": out_dir / "low_quality_ocr_review_summary.md",
    }
    write_jsonl(outputs["review_rows"], rows)
    write_jsonl(outputs["source_review_candidates"], source_review)
    write_jsonl(outputs["manual_review_low_signal"], manual)
    write_jsonl(outputs["rejected_low_signal"], rejected)
    write_jsonl(outputs["accepted_for_markdown_flash"], accepted)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": True,
        "decision": "p1_low_quality_ocr_review_complete_no_auto_flash",
        "input_path": str(input_path),
        "out_dir": str(out_dir),
        "counts": {
            "input_rows": len(rows),
            "source_review_candidate_rows": len(source_review),
            "manual_review_low_signal_rows": len(manual),
            "rejected_low_signal_rows": len(rejected),
            "accepted_for_markdown_flash_rows": len(accepted),
            "bucket_counts": dict(sorted(buckets.items())),
        },
        "outputs": {key: str(value) for key, value in outputs.items()},
        "safety": {
            "d_root_scan_executed": False,
            "bounded_queue_only": True,
            "ocr_execution": False,
            "llm_called": False,
            "paid_api_used": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "mem0_write_executed": False,
            "product_surface_write_executed": False,
            "used_9router": False,
        },
    }
    write_json(outputs["summary_json"], summary)
    write_text(outputs["summary_md"], render_markdown(summary))
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = build(args.input, args.out_dir)
    print(
        json.dumps(
            {
                "ok": summary["ok"],
                "decision": summary["decision"],
                "counts": summary["counts"],
                "out_dir": summary["out_dir"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
