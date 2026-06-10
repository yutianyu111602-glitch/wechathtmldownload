#!/usr/bin/env python3
"""Extract PRD-13 OCR venue/date/lineup entities from poster_ocr.json files.

This script reads the latest OCR file index and only opens the exact
poster_ocr_path values from rows that already have completed OCR text. It does
not recursively scan D:, run OCR, or write graph/vector/DB state.
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


DEFAULT_POINTER = Path("reports/ocr_file_index_latest.json")
DEFAULT_OUT_DIR = Path("reports/ocr_entity_extraction_20260515")
SCHEMA_VERSION = "stage7_ocr_entity_extraction.v1"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def reject_broad_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").rstrip("/").lower()
    if raw in {"d:", "d:/", "/mnt/d", "/mnt/d/"} or raw.startswith("d:/ddownload") or raw.startswith("d:/aidata"):
        raise ValueError(f"{label} refuses broad D root: {path}")


def first_text(value: Any) -> str:
    return str(value or "").strip()


def read_json(path: Path) -> Any:
    reject_broad_d_path(path, "json")
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_broad_d_path(path, "jsonl")
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                row = json.loads(stripped)
                if isinstance(row, dict):
                    rows.append(row)
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
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


def normalize_name(value: str) -> str:
    return re.sub(r"\s+", " ", first_text(value)).strip(" -:|")


def stable_id(*values: str) -> str:
    raw = "|".join(first_text(value).casefold() for value in values)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def value_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [normalize_name(str(item)) for item in value if normalize_name(str(item))]
    text = normalize_name(first_text(value))
    return [text] if text else []


def recovered_payload(poster_ocr: dict[str, Any]) -> dict[str, Any]:
    recovered = poster_ocr.get("recovered")
    return recovered if isinstance(recovered, dict) else {}


def entity_row(
    *,
    entity_type: str,
    entity_name: str,
    source_article_uid: str,
    source_account: str,
    poster_ocr_path: str,
    evidence_field: str,
    evidence_text: str,
    confidence: float,
) -> dict[str, Any]:
    entity_name = normalize_name(entity_name)
    return {
        "schema_version": SCHEMA_VERSION + ".row",
        "ocr_entity_id": f"ocr:{entity_type}:{stable_id(entity_type, entity_name, source_article_uid)}",
        "entity_type": entity_type,
        "entity_name": entity_name,
        "source": "ocr_poster",
        "confidence": confidence,
        "source_article_uid": source_article_uid,
        "source_account": source_account,
        "source_poster_ocr_path": poster_ocr_path,
        "evidence_field": evidence_field,
        "evidence_text": evidence_text,
        "merged_with_existing": False,
        "staging_only": True,
    }


def rows_from_poster(row: dict[str, Any], poster_ocr: dict[str, Any]) -> list[dict[str, Any]]:
    recovered = recovered_payload(poster_ocr)
    source_article_uid = first_text(row.get("article_uid"))
    source_account = first_text(row.get("source_account"))
    poster_ocr_path = first_text(row.get("poster_ocr_path"))
    out: list[dict[str, Any]] = []

    venue = normalize_name(first_text(recovered.get("venue_name_candidate")))
    if venue:
        out.append(
            entity_row(
                entity_type="venue",
                entity_name=venue,
                source_article_uid=source_article_uid,
                source_account=source_account,
                poster_ocr_path=poster_ocr_path,
                evidence_field="recovered.venue_name_candidate",
                evidence_text=venue,
                confidence=0.7,
            )
        )

    for date_text in value_list(recovered.get("date_texts")):
        out.append(
            entity_row(
                entity_type="event_date",
                entity_name=date_text,
                source_article_uid=source_article_uid,
                source_account=source_account,
                poster_ocr_path=poster_ocr_path,
                evidence_field="recovered.date_texts",
                evidence_text=date_text,
                confidence=0.65,
            )
        )

    for lineup in value_list(recovered.get("lineup_lines")):
        out.append(
            entity_row(
                entity_type="artist",
                entity_name=lineup,
                source_article_uid=source_article_uid,
                source_account=source_account,
                poster_ocr_path=poster_ocr_path,
                evidence_field="recovered.lineup_lines",
                evidence_text=lineup,
                confidence=0.62,
            )
        )
    return out


def build_extraction(pointer_path: Path, out_dir: Path, min_entities: int) -> dict[str, Any]:
    reject_broad_d_path(out_dir, "out_dir")
    pointer = read_json(pointer_path)
    index_path = Path(pointer["index_path"])
    index_rows = read_jsonl(index_path)
    entities: list[dict[str, Any]] = []
    skipped: Counter[str] = Counter()
    scanned_ocr_files = 0

    for row in index_rows:
        if first_text(row.get("ocr_status")) != "complete":
            skipped[f"ocr_status:{first_text(row.get('ocr_status')) or 'unknown'}"] += 1
            continue
        poster_path = Path(first_text(row.get("poster_ocr_path")))
        if not poster_path.exists():
            skipped["poster_ocr_missing_on_disk"] += 1
            continue
        try:
            poster_ocr = read_json(poster_path)
        except Exception:
            skipped["poster_ocr_unreadable"] += 1
            continue
        if not isinstance(poster_ocr, dict):
            skipped["poster_ocr_not_object"] += 1
            continue
        scanned_ocr_files += 1
        rows = rows_from_poster(row, poster_ocr)
        if not rows:
            skipped["poster_ocr_no_recovered_entities"] += 1
            continue
        entities.extend(rows)

    # Deduplicate by deterministic OCR entity id.
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entity in entities:
        if entity["ocr_entity_id"] in seen:
            skipped["duplicate_ocr_entity"] += 1
            continue
        seen.add(entity["ocr_entity_id"])
        deduped.append(entity)

    type_counts = Counter(entity["entity_type"] for entity in deduped)
    gate_met = len(deduped) >= min_entities
    decision = "ocr_entity_extraction_ready" if gate_met else "ocr_entity_extraction_blocked_insufficient_ocr_entities"

    out_dir.mkdir(parents=True, exist_ok=True)
    entity_path = out_dir / "ocr_entities.jsonl"
    write_jsonl(entity_path, deduped)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": decision,
        "ok": gate_met,
        "pointer_path": str(pointer_path),
        "index_path": str(index_path),
        "entity_path": str(entity_path),
        "index_rows": len(index_rows),
        "scanned_ocr_files": scanned_ocr_files,
        "entity_count": len(deduped),
        "min_entities": min_entities,
        "gate_met": gate_met,
        "entity_type_counts": dict(type_counts),
        "skipped": dict(skipped),
        "safety": [
            "reports_only",
            "exact_poster_ocr_paths_only",
            "no_recursive_d_scan",
            "no_ocr_execution",
            "no_graph_vector_db_write",
            "no_paid_api",
            "no_publish",
        ],
    }
    write_json(out_dir / "ocr_entity_extraction_summary.json", summary)
    write_markdown(out_dir / "ocr_entity_extraction_summary.md", summary)
    return summary


def write_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# PRD-13 OCR Entity Extraction",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{summary['decision']}`",
        f"- index_rows: `{summary['index_rows']}`",
        f"- scanned_ocr_files: `{summary['scanned_ocr_files']}`",
        f"- entity_count: `{summary['entity_count']}`",
        f"- min_entities: `{summary['min_entities']}`",
        f"- gate_met: `{summary['gate_met']}`",
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
            "- Reports only.",
            "- Reads exact `poster_ocr_path` values from the OCR index only.",
            "- No recursive D: scan, OCR execution, graph/vector/DB write, paid API, or publish.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ocr-index", "--pointer", dest="pointer", type=Path, default=DEFAULT_POINTER)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--min-entities", type=int, default=10)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    summary = build_extraction(args.pointer, args.out_dir, args.min_entities)
    print(
        json.dumps(
            {
                "decision": summary["decision"],
                "entity_count": summary["entity_count"],
                "summary": str(args.out_dir / "ocr_entity_extraction_summary.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
