#!/usr/bin/env python3
"""Audit where an Atlas incremental refresh loses source information.

The audit is read-only. It compares the source artifact manifest, DeepSeek
Flash rows, and stable materialization outputs for a single incremental run.
It is meant to keep the Atlas database route from treating the old generic
Stage7 LLM path as a lossless extractor.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import median
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                value = json.loads(stripped)
                if isinstance(value, dict):
                    rows.append(value)
    return rows


def pct(part: int, total: int) -> float:
    return round(part * 100.0 / total, 3) if total else 0.0


def dist(values: list[int]) -> dict[str, Any]:
    if not values:
        return {"count": 0}
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "min": ordered[0],
        "p50": median(ordered),
        "p90": ordered[int((len(ordered) - 1) * 0.9)],
        "max": ordered[-1],
        "zero": sum(1 for value in ordered if value == 0),
    }


def audit(run_dir: Path) -> dict[str, Any]:
    host_dir = run_dir / "host_html_artifacts"
    deepseek_dir = run_dir / "deepseek_stage7_1021"
    stable_dir = run_dir / "stable_extract"
    host_summary = read_json(host_dir / "host_html_artifact_summary.json")
    manifest_rows = read_jsonl(host_dir / "stage7_manifest.jsonl")
    flash_rows = read_jsonl(deepseek_dir / "flash_rows.jsonl")
    stable_rows = read_jsonl(stable_dir / "stable_articles.jsonl")

    body_chars = [int(row.get("body_text_chars") or 0) for row in manifest_rows]
    html_chars = [int(row.get("html_chars") or 0) for row in manifest_rows]
    ocr_chars = [int(row.get("ocr_text_chars") or 0) for row in manifest_rows]
    input_chars = [int(row.get("input_chars") or 0) for row in manifest_rows]
    short_body_large_html = sum(
        1 for row in manifest_rows if int(row.get("html_chars") or 0) > 50000 and int(row.get("body_text_chars") or 0) < 800
    )
    ocr_missing = sum(1 for row in manifest_rows if int(row.get("local_image_count") or 0) > 0 and int(row.get("ocr_text_chars") or 0) == 0)

    raw_lens: list[int] = []
    flash_zero_events = 0
    flash_zero_both = 0
    flash_parse_fail = 0
    flash_schema_fail = 0
    for row in flash_rows:
        row_entities = 0
        row_events = 0
        for chunk in row.get("chunks") or []:
            raw = str(chunk.get("raw_content") or "")
            raw_lens.append(len(raw))
            if not chunk.get("parse_ok"):
                flash_parse_fail += 1
            if not chunk.get("schema_ok"):
                flash_schema_fail += 1
            row_entities += int(chunk.get("entities_count") or 0)
            row_events += int(chunk.get("events_count") or 0)
        if row_events == 0:
            flash_zero_events += 1
        if row_events == 0 and row_entities == 0:
            flash_zero_both += 1

    stable_zero_events = 0
    stable_zero_both = 0
    stable_ocr_evidence_rows = 0
    stable_events = 0
    stable_entities = 0
    for row in stable_rows:
        entity_count = len(row.get("entities") or [])
        event_count = len(row.get("events") or [])
        stable_entities += entity_count
        stable_events += event_count
        if event_count == 0:
            stable_zero_events += 1
        if event_count == 0 and entity_count == 0:
            stable_zero_both += 1
        if row.get("ocr_evidence"):
            stable_ocr_evidence_rows += 1

    raw_at_cap = sum(1 for length in raw_lens if length >= 8000)
    schema_gap_fields = [
        "event_date_text",
        "event_time_text",
        "lineup_artists",
        "music_styles",
        "price",
        "ticketing_text",
        "description_original_lines",
        "source_action",
    ]
    stable_article_keys = set()
    for row in stable_rows[:20]:
        stable_article_keys.update(row.keys())
    missing_weekly_fields = [field for field in schema_gap_fields if field not in stable_article_keys]

    diagnosis: list[dict[str, str]] = []
    if short_body_large_html:
        diagnosis.append(
            {
                "stage": "pre_llm_body_extraction",
                "severity": "high",
                "reason": f"{short_body_large_html}/{len(manifest_rows)} rows have huge HTML but short extracted body text.",
            }
        )
    if ocr_missing or (host_summary.get("tesseract_lang") == "eng"):
        diagnosis.append(
            {
                "stage": "pre_llm_ocr",
                "severity": "medium",
                "reason": f"OCR missing on {ocr_missing} image rows and current tesseract_lang={host_summary.get('tesseract_lang')!r}.",
            }
        )
    if raw_at_cap:
        diagnosis.append(
            {
                "stage": "llm_raw_capture",
                "severity": "medium",
                "reason": f"{raw_at_cap}/{len(raw_lens)} captured LLM chunks hit the 8000 char raw_content cap.",
            }
        )
    if stable_zero_events:
        diagnosis.append(
            {
                "stage": "generic_stage7_schema",
                "severity": "high",
                "reason": f"{stable_zero_events}/{len(stable_rows)} stable rows have zero events; old Stage7 graph schema is not a weekly activity field schema.",
            }
        )
    if missing_weekly_fields:
        diagnosis.append(
            {
                "stage": "schema_materialization",
                "severity": "high",
                "reason": "Stable Atlas article rows do not preserve weekly rich fields: " + ", ".join(missing_weekly_fields),
            }
        )
    if not stable_ocr_evidence_rows and stable_rows:
        diagnosis.append(
            {
                "stage": "ocr_evidence_materialization",
                "severity": "medium",
                "reason": "Stable rows contain no article-level ocr_evidence even though OCR text was provided upstream.",
            }
        )

    return {
        "schema_version": "atlas_incremental_loss_chain_audit.v1",
        "run_dir": str(run_dir),
        "host": {
            "input_rows": host_summary.get("input_rows"),
            "manifest_rows": len(manifest_rows),
            "failed_rows": host_summary.get("failed_rows"),
            "body_text_chars": dist(body_chars),
            "html_chars": dist(html_chars),
            "ocr_text_chars": dist(ocr_chars),
            "input_chars": dist(input_chars),
            "short_body_large_html_rows": short_body_large_html,
            "short_body_large_html_pct": pct(short_body_large_html, len(manifest_rows)),
            "ocr_missing_image_rows": ocr_missing,
            "tesseract_lang": host_summary.get("tesseract_lang"),
        },
        "llm_runner": {
            "rows": len(flash_rows),
            "chunks": len(raw_lens),
            "parse_fail_chunks": flash_parse_fail,
            "schema_fail_chunks": flash_schema_fail,
            "raw_content_len": dist(raw_lens),
            "raw_content_8000_cap_chunks": raw_at_cap,
            "zero_event_rows": flash_zero_events,
            "zero_both_rows": flash_zero_both,
        },
        "stable_materialization": {
            "rows": len(stable_rows),
            "entities": stable_entities,
            "events": stable_events,
            "zero_event_rows": stable_zero_events,
            "zero_event_pct": pct(stable_zero_events, len(stable_rows)),
            "zero_both_rows": stable_zero_both,
            "ocr_evidence_rows": stable_ocr_evidence_rows,
            "missing_weekly_rich_fields": missing_weekly_fields,
        },
        "diagnosis": diagnosis,
        "decision": "not_lossless_old_stage7_path" if diagnosis else "no_major_loss_detected",
    }


def write_md(path: Path, result: dict[str, Any]) -> None:
    lines = [
        "# Atlas Incremental Loss Chain Audit",
        "",
        f"- decision: `{result['decision']}`",
        f"- run_dir: `{result['run_dir']}`",
        "",
        "## Diagnosis",
        "",
    ]
    for item in result["diagnosis"]:
        lines.append(f"- `{item['severity']}` `{item['stage']}`: {item['reason']}")
    if not result["diagnosis"]:
        lines.append("- No major loss stage detected.")
    lines.extend(
        [
            "",
            "## Counts",
            "",
            f"- host manifest rows: `{result['host']['manifest_rows']}`",
            f"- short body / large HTML rows: `{result['host']['short_body_large_html_rows']}` (`{result['host']['short_body_large_html_pct']}%`)",
            f"- OCR missing image rows: `{result['host']['ocr_missing_image_rows']}`",
            f"- LLM chunks: `{result['llm_runner']['chunks']}`",
            f"- raw_content cap chunks: `{result['llm_runner']['raw_content_8000_cap_chunks']}`",
            f"- stable rows: `{result['stable_materialization']['rows']}`",
            f"- stable zero-event rows: `{result['stable_materialization']['zero_event_rows']}` (`{result['stable_materialization']['zero_event_pct']}%`)",
            f"- stable OCR evidence rows: `{result['stable_materialization']['ocr_evidence_rows']}`",
            "",
            "## Required Pipeline Change",
            "",
            "- Do not use the old generic Stage7 graph extractor as the sole Atlas daily route.",
            "- Preserve source evidence before LLM: queue digest, page metadata, body text, poster OCR, and source lines.",
            "- Materialize an activity-aware Atlas sidecar/schema for dates, times, venue, address, lineup, ticketing, and description lines before reducing to graph entities/events.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--out-json")
    parser.add_argument("--out-md")
    args = parser.parse_args()
    result = audit(Path(args.run_dir))
    if args.out_json:
        Path(args.out_json).write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.out_md:
        write_md(Path(args.out_md), result)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
