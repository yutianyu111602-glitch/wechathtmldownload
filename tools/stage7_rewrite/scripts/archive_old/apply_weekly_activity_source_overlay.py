#!/usr/bin/env python3
"""Apply source-grounded corrections to a weekly activity pack.

This script is the stable boundary between new local/public sources and the
mini-program publisher. It does not fetch pages or call models. It only accepts
facts that already have a supporting source quote.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


PACK_CANDIDATES = "weekly_activity_recommendation_candidates.jsonl"
PACK_REVIEW = "weekly_activity_recommendation_review_candidates.jsonl"
PACK_SUMMARY = "summary.json"
SUPPORTED_SCHEMA = "weekly_activity_source_overlay.v1"
OUTPUT_SCHEMA = "weekly_activity_source_overlay_application.v1"
GROUNDING_FIELDS = ("event_time_text", "running_hours_text", "address", "city", "venue")
LIST_FIELDS = {"city", "venue"}
MODEL_SOURCE_RE = re.compile(r"gpt|llm|model|guess|infer", re.I)
TIME_RE = re.compile(
    r"(?i)(?:\b[0-2]?\d[:：][0-5]\d\b|"
    r"(?:凌晨|早上|上午|中午|下午|晚上|晚间)\s*[0-2]?\d(?:点|[:：][0-5]\d)?|"
    r"\b(?:doors?|open|start)\s*[：:]?\s*[0-2]?\d[:：][0-5]\d\b|\blate\b)"
)
ADDRESS_SIGNAL_RE = re.compile(
    r"省|市|区|县|路|街|道|巷|弄|号|栋|幢|层|室|广场|文创园|创意园|园区|中心|B\d|L\d|M\d",
    re.I,
)


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                rows.append(value)
    return rows


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def first_string(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def list_strings(value: Any) -> list[str]:
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    if isinstance(value, list):
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return []


def normalize(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).lower()
    return re.sub(r"\s+", "", text)


def token_from_url(value: str) -> str:
    match = re.search(r"/s/([^?#]+)", value)
    return match.group(1) if match else ""


def row_keys(row: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for field in ("id", "event_id", "article_id", "queue_id"):
        value = first_string(row.get(field))
        if value:
            keys.add(f"{field}:{value}")
            keys.add(f"any:{value}")
    source_url = first_string(row.get("source_url"), row.get("url"), row.get("article_url"))
    if source_url:
        keys.add(f"url:{source_url}")
        token = token_from_url(source_url)
        if token:
            keys.add(f"url_token:{token}")
            keys.add(f"any:{token}")
    return keys


def quote_supports_time(value: str, quote: str) -> bool:
    if not value or not quote:
        return False
    if normalize(value) in normalize(quote):
        return True
    value_tokens = [normalize(match.group(0)) for match in TIME_RE.finditer(value)]
    quote_tokens = {normalize(match.group(0)) for match in TIME_RE.finditer(quote)}
    return bool(value_tokens) and all(token in quote_tokens for token in value_tokens)


def quote_supports_text(value: str, quote: str) -> bool:
    if not value or not quote:
        return False
    return normalize(value) in normalize(quote)


def looks_like_address(value: str) -> bool:
    return bool(value and ADDRESS_SIGNAL_RE.search(value))


def validate_overlay(row: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    reasons: list[str] = []
    source_kind = first_string(row.get("source_kind"))
    source_quote = first_string(row.get("source_quote"), row.get("evidence_quote"), row.get("quote"))
    if source_kind and MODEL_SOURCE_RE.search(source_kind):
        reasons.append("model_or_inference_source_not_allowed")
    if not source_kind:
        reasons.append("missing_source_kind")
    if not source_quote:
        reasons.append("missing_source_quote")
    if not row_keys(row):
        reasons.append("missing_match_key")

    fields: dict[str, Any] = {}
    time_value = first_string(row.get("event_time_text"), row.get("running_hours_text"))
    if time_value:
        if not TIME_RE.search(time_value):
            reasons.append("event_time_text_has_no_time_token")
        elif not quote_supports_time(time_value, source_quote):
            reasons.append("event_time_text_not_supported_by_quote")
        else:
            fields["event_time_text"] = time_value

    running_hours = first_string(row.get("running_hours_text"))
    if running_hours and running_hours != time_value:
        if quote_supports_time(running_hours, source_quote):
            fields["running_hours_text"] = running_hours
        else:
            reasons.append("running_hours_text_not_supported_by_quote")

    address = first_string(row.get("address"), row.get("address_full"))
    if address:
        if not looks_like_address(address):
            reasons.append("address_shape_rejected")
        elif not quote_supports_text(address, source_quote):
            reasons.append("address_not_supported_by_quote")
        else:
            fields["address"] = address

    for field in ("city", "venue"):
        values = list_strings(row.get(field))
        supported = [value for value in values if quote_supports_text(value, source_quote)]
        if values and not supported:
            reasons.append(f"{field}_not_supported_by_quote")
        elif supported:
            fields[field] = supported

    return fields, reasons


def overlay_metadata(row: dict[str, Any], fields: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SUPPORTED_SCHEMA,
        "source_kind": first_string(row.get("source_kind")),
        "source_url": first_string(row.get("source_url"), row.get("evidence_url")),
        "source_path": first_string(row.get("source_path")),
        "source_quote": first_string(row.get("source_quote"), row.get("evidence_quote"), row.get("quote")),
        "confidence": row.get("confidence", ""),
        "applied_fields": sorted(fields.keys()),
    }


def merge_unique(existing: Any, additions: list[str]) -> list[str]:
    out = list_strings(existing)
    seen = {normalize(value) for value in out}
    for value in additions:
        if value and normalize(value) not in seen:
            out.append(value)
            seen.add(normalize(value))
    return out


def apply_overlay_to_row(
    row: dict[str, Any],
    overlay: dict[str, Any],
    fields: dict[str, Any],
    *,
    replace_existing: bool,
) -> tuple[dict[str, Any], list[str]]:
    next_row = dict(row)
    changed: list[str] = []
    for field, value in fields.items():
        current = next_row.get(field)
        current_empty = not list_strings(current) if field in LIST_FIELDS else not first_string(current)
        if not current_empty and not replace_existing:
            continue
        next_row[field] = value if field in LIST_FIELDS else first_string(value)
        changed.append(field)
    if changed:
        meta = overlay_metadata(overlay, {field: fields[field] for field in changed})
        overlays = next_row.get("source_overlays") if isinstance(next_row.get("source_overlays"), list) else []
        next_row["source_overlays"] = [*overlays, meta]
        quote = first_string(meta.get("source_quote"))
        evidence = [f"Source overlay ({meta['source_kind']}): {quote}"] if quote else []
        next_row["evidence"] = merge_unique(next_row.get("evidence"), evidence)
        if "event_time_text" in changed and not first_string(next_row.get("running_hours_text")):
            next_row["running_hours_text"] = first_string(next_row.get("event_time_text"))
    return next_row, changed


def index_overlays(rows: list[dict[str, Any]]) -> tuple[dict[str, tuple[dict[str, Any], dict[str, Any]]], dict[str, Any]]:
    index: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    invalid: list[dict[str, Any]] = []
    valid_count = 0
    for row_number, row in enumerate(rows, start=1):
        fields, reasons = validate_overlay(row)
        if reasons or not fields:
            invalid.append(
                {
                    "row_number": row_number,
                    "reasons": reasons or ["no_supported_fields"],
                    "keys": sorted(row_keys(row)),
                    "title": first_string(row.get("title")),
                }
            )
            continue
        valid_count += 1
        for key in row_keys(row):
            index[key] = (row, fields)
    return index, {"valid_overlay_rows": valid_count, "invalid_overlay_rows": len(invalid), "invalid": invalid[:50]}


def apply_to_pack(
    *,
    pack_dir: Path,
    overlay_jsonl: Path,
    out_dir: Path,
    replace_existing: bool = False,
) -> dict[str, Any]:
    overlays = read_jsonl(overlay_jsonl)
    overlay_index, overlay_summary = index_overlays(overlays)
    out_dir.mkdir(parents=True, exist_ok=True)

    file_summaries: dict[str, Any] = {}
    changed_fields: Counter[str] = Counter()
    matched_rows = 0
    updated_rows = 0

    for filename in (PACK_CANDIDATES, PACK_REVIEW):
        rows = read_jsonl(pack_dir / filename)
        output_rows: list[dict[str, Any]] = []
        file_updated = 0
        for row in rows:
            match: tuple[dict[str, Any], dict[str, Any]] | None = None
            for key in row_keys(row):
                if key in overlay_index:
                    match = overlay_index[key]
                    break
            if not match:
                output_rows.append(row)
                continue
            matched_rows += 1
            overlay, fields = match
            next_row, changed = apply_overlay_to_row(row, overlay, fields, replace_existing=replace_existing)
            if changed:
                updated_rows += 1
                file_updated += 1
                changed_fields.update(changed)
            output_rows.append(next_row)
        write_jsonl(out_dir / filename, output_rows)
        file_summaries[filename] = {"rows": len(rows), "updated_rows": file_updated}

    source_summary = read_json(pack_dir / PACK_SUMMARY)
    source_summary["source_overlay"] = {
        "schema_version": OUTPUT_SCHEMA,
        "overlay_jsonl": str(overlay_jsonl),
        "overlay_rows": len(overlays),
        "valid_overlay_rows": overlay_summary["valid_overlay_rows"],
        "invalid_overlay_rows": overlay_summary["invalid_overlay_rows"],
        "matched_rows": matched_rows,
        "updated_rows": updated_rows,
        "changed_fields": dict(sorted(changed_fields.items())),
        "replace_existing": replace_existing,
    }
    write_json(out_dir / PACK_SUMMARY, source_summary)

    for extra in ("source_summary.json", "SUMMARY.md"):
        src = pack_dir / extra
        if src.exists() and not (out_dir / extra).exists():
            shutil.copy2(src, out_dir / extra)

    summary = {
        "schema_version": OUTPUT_SCHEMA,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "pack_dir": str(pack_dir),
        "overlay_jsonl": str(overlay_jsonl),
        "out_dir": str(out_dir),
        "files": file_summaries,
        "overlay_rows": len(overlays),
        "valid_overlay_rows": overlay_summary["valid_overlay_rows"],
        "invalid_overlay_rows": overlay_summary["invalid_overlay_rows"],
        "matched_rows": matched_rows,
        "updated_rows": updated_rows,
        "changed_fields": dict(sorted(changed_fields.items())),
        "invalid_overlays": overlay_summary["invalid"],
    }
    write_json(out_dir / "source_overlay_summary.json", summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply source-grounded overlay facts to a weekly activity pack")
    parser.add_argument("--pack-dir", required=True)
    parser.add_argument("--overlay-jsonl", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--replace-existing", action="store_true")
    parser.add_argument("--strict", action="store_true", help="Return non-zero if any overlay row is invalid")
    args = parser.parse_args(argv)

    summary = apply_to_pack(
        pack_dir=Path(args.pack_dir),
        overlay_jsonl=Path(args.overlay_jsonl),
        out_dir=Path(args.out_dir),
        replace_existing=args.replace_existing,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.strict and summary["invalid_overlay_rows"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
