#!/usr/bin/env python3
"""Extract OCR entities from recovered sidecar poster_ocr.json files.

This is a report-only bridge for PRD-13. It reads bounded local C: recovered
process status directories and converts only structured `recovered` fields into
OCR entity rows. It does not parse free-form OCR plain_text into entities.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_OCR_ROOT = Path("reports/ocr_root_cause_20260515")
DEFAULT_OUT_DIR = Path("reports/ocr_sidecar_entity_extraction_20260515")
SCHEMA_VERSION = "stage7_ocr_sidecar_entity_extraction.v1"
MAX_STRUCTURED_ENTITY_CHARS = 160


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
    tmp.replace(path)


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def is_under(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def normalize_name(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).strip(" -:|")


def is_valid_structured_entity_name(value: Any) -> bool:
    text = normalize_name(value)
    if not text:
        return False
    if len(text) > MAX_STRUCTURED_ENTITY_CHARS:
        return False
    if text[0] in "{[":
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, (dict, list)):
            return False
        lowered = text.lower()
        if '"backend"' in lowered or '"recovered"' in lowered or '"plain_text"' in lowered:
            return False
    lowered = text.lower()
    if '"backend"' in lowered and '"recovered"' in lowered:
        return False
    return True


def value_list(value: Any, *, field_name: str, skipped: Counter[str]) -> list[str]:
    values = value if isinstance(value, list) else [value]
    normalized: list[str] = []
    for item in values:
        text = normalize_name(item)
        if not text:
            continue
        if not is_valid_structured_entity_name(text):
            skipped[f"invalid_structured_entity_value:{field_name}"] += 1
            continue
        normalized.append(text)
    return normalized


def single_value(value: Any, *, field_name: str, skipped: Counter[str]) -> str:
    values = value_list(value, field_name=field_name, skipped=skipped)
    return values[0] if values else ""


def stable_id(*values: str) -> str:
    raw = "|".join(str(value or "").casefold() for value in values)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def article_uid_from_relative(relative_dir: str) -> tuple[str, str]:
    parts = [part for part in re.split(r"[\\/]+", relative_dir) if part]
    if len(parts) >= 2:
        return parts[0], f"{parts[0]}/{parts[1]}"
    if parts:
        return parts[0], parts[0]
    return "", ""


def entity_row(
    *,
    entity_type: str,
    entity_name: str,
    source_account: str,
    source_article_uid: str,
    poster_ocr_path: Path,
    evidence_field: str,
    confidence: float,
) -> dict[str, Any]:
    entity_name = normalize_name(entity_name)
    return {
        "schema_version": SCHEMA_VERSION + ".row",
        "ocr_entity_id": f"ocr:{entity_type}:{stable_id(entity_type, entity_name, source_article_uid, str(poster_ocr_path))}",
        "entity_type": entity_type,
        "entity_name": entity_name,
        "source": "ocr_poster",
        "source_origin": "sidecar_recovered_process",
        "confidence": confidence,
        "source_article_uid": source_article_uid,
        "source_account": source_account,
        "source_poster_ocr_path": str(poster_ocr_path),
        "evidence_field": evidence_field,
        "evidence_text": entity_name,
        "merged_with_existing": False,
        "staging_only": True,
    }


def rows_from_recovered(
    *,
    poster_ocr_path: Path,
    relative_dir: str,
    recovered: dict[str, Any],
    skipped: Counter[str],
) -> list[dict[str, Any]]:
    source_account, source_article_uid = article_uid_from_relative(relative_dir)
    rows: list[dict[str, Any]] = []
    venue = single_value(
        recovered.get("venue_name_candidate"),
        field_name="recovered.venue_name_candidate",
        skipped=skipped,
    )
    if venue:
        rows.append(
            entity_row(
                entity_type="venue",
                entity_name=venue,
                source_account=source_account,
                source_article_uid=source_article_uid,
                poster_ocr_path=poster_ocr_path,
                evidence_field="recovered.venue_name_candidate",
                confidence=0.7,
            )
        )
    for date_text in value_list(
        recovered.get("date_texts"),
        field_name="recovered.date_texts",
        skipped=skipped,
    ):
        rows.append(
            entity_row(
                entity_type="event_date",
                entity_name=date_text,
                source_account=source_account,
                source_article_uid=source_article_uid,
                poster_ocr_path=poster_ocr_path,
                evidence_field="recovered.date_texts",
                confidence=0.65,
            )
        )
    for lineup in value_list(
        recovered.get("lineup_lines"),
        field_name="recovered.lineup_lines",
        skipped=skipped,
    ):
        rows.append(
            entity_row(
                entity_type="artist",
                entity_name=lineup,
                source_account=source_account,
                source_article_uid=source_article_uid,
                poster_ocr_path=poster_ocr_path,
                evidence_field="recovered.lineup_lines",
                confidence=0.62,
            )
        )
    return rows


def extract_sidecar_entities(ocr_root: Path, out_dir: Path, min_entities: int, max_items: int = 0) -> dict[str, Any]:
    root_resolved = ocr_root.resolve()
    status_files = sorted(ocr_root.glob("empty_no_local_image_dajiala_process_*/ocr-status.json"))
    entities: list[dict[str, Any]] = []
    skipped: Counter[str] = Counter()
    poster_ocr_seen = 0
    plain_text_nonempty = 0
    inspected_items = 0
    for status_path in status_files:
        status = read_json(status_path)
        for item in status.get("items") or []:
            if max_items and inspected_items >= max_items:
                continue
            artifact_dir = Path(str(item.get("artifactDir") or ""))
            poster_ocr_path = artifact_dir / "poster_ocr.json"
            if not poster_ocr_path.exists() or not is_under(poster_ocr_path, root_resolved):
                skipped["poster_ocr_missing_or_outside_root"] += 1
                continue
            inspected_items += 1
            poster_ocr_seen += 1
            try:
                poster = read_json(poster_ocr_path)
            except Exception:
                skipped["poster_ocr_unreadable"] += 1
                continue
            if str(poster.get("plain_text") or "").strip():
                plain_text_nonempty += 1
            recovered = poster.get("recovered")
            if not isinstance(recovered, dict):
                skipped["missing_recovered_object"] += 1
                continue
            rows = rows_from_recovered(
                poster_ocr_path=poster_ocr_path,
                relative_dir=str(item.get("relativeDir") or ""),
                recovered=recovered,
                skipped=skipped,
            )
            if not rows:
                skipped["empty_recovered_structured_fields"] += 1
                continue
            entities.extend(rows)

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in entities:
        key = row["ocr_entity_id"]
        if key in seen:
            skipped["duplicate_ocr_entity_id"] += 1
            continue
        seen.add(key)
        deduped.append(row)

    type_counts = Counter(row["entity_type"] for row in deduped)
    gate_met = len(deduped) >= min_entities
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": gate_met,
        "decision": "ocr_sidecar_entity_extraction_ready" if gate_met else "ocr_sidecar_entity_extraction_below_gate",
        "ocr_root": str(ocr_root),
        "status_file_count": len(status_files),
        "poster_ocr_seen": poster_ocr_seen,
        "plain_text_nonempty": plain_text_nonempty,
        "entity_count": len(deduped),
        "min_entities": min_entities,
        "gate_met": gate_met,
        "entity_type_counts": dict(type_counts),
        "skipped": dict(skipped),
        "entity_path": str(out_dir / "ocr_entities.jsonl"),
        "safety": [
            "reports_only",
            "bounded_c_reports_sidecar_status_dirs",
            "structured_recovered_fields_only",
            "no_plain_text_entity_parsing",
            "no_ocr_execution",
            "no_graph_vector_db_write",
            "no_paid_api",
            "no_d_scan",
        ],
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(out_dir / "ocr_entities.jsonl", deduped)
    write_json(out_dir / "ocr_sidecar_entity_extraction_summary.json", summary)
    write_markdown(out_dir / "ocr_sidecar_entity_extraction_summary.md", summary)
    return summary


def write_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# PRD-13 Sidecar OCR Entity Extraction",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{summary['decision']}`",
        f"- entity_count: `{summary['entity_count']}`",
        f"- min_entities: `{summary['min_entities']}`",
        f"- gate_met: `{summary['gate_met']}`",
        f"- poster_ocr_seen: `{summary['poster_ocr_seen']}`",
        f"- plain_text_nonempty: `{summary['plain_text_nonempty']}`",
        f"- entity_path: `{summary['entity_path']}`",
        "",
        "## Entity Types",
        "",
    ]
    for key, value in sorted(summary["entity_type_counts"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Skipped", ""])
    for key, value in sorted(summary["skipped"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Report-only.",
            "- Uses structured `recovered` fields only; OCR `plain_text` is not parsed into entities.",
            "- No OCR execution, graph/vector/DB write, paid API, publish, or D: scan.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    summary = extract_sidecar_entities(args.ocr_root, args.out_dir, args.min_entities, max_items=args.max_items)
    print(
        json.dumps(
            {
                "ok": summary["ok"],
                "decision": summary["decision"],
                "entity_count": summary["entity_count"],
                "report": str(args.out_dir / "ocr_sidecar_entity_extraction_summary.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if summary["ok"] or args.report_only_exit_zero else 2


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ocr-root", type=Path, default=DEFAULT_OCR_ROOT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--min-entities", type=int, default=10)
    parser.add_argument("--max-items", type=int, default=0)
    parser.add_argument("--report-only-exit-zero", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
