#!/usr/bin/env python3
"""Build a report-only review pack for weekly Atlas fuzzy/no-match rows."""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


def norm(value: str) -> str:
    return re.sub(r"[\s·・|｜@＠:：,，.。()（）\[\]【】\-_/\\]+", "", str(value or "").lower())


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"expected object JSON: {path}")
    return data


def load_current_titles(path: Path | None) -> dict[str, dict[str, str]]:
    if not path:
        return {}
    data = load_json(path)
    out: dict[str, dict[str, str]] = {}
    for item in data.get("items") or []:
        event_id = str(item.get("id") or item.get("event_id") or "")
        if not event_id:
            continue
        venue_value = item.get("venue_name") or ""
        if not venue_value:
            raw_venue = item.get("venue")
            venue_value = raw_venue[0] if isinstance(raw_venue, list) and raw_venue else raw_venue or ""
        out[event_id] = {
            "title": str(item.get("title") or item.get("display_title") or ""),
            "venue": str(venue_value),
            "city_key": str(item.get("city_key") or ""),
        }
    return out


def classify_row(row: dict[str, Any]) -> str:
    method = row.get("match_method")
    if method == "fuzzy_multiple":
        candidates = row.get("candidates") or []
        names = {norm(candidate.get("canonical_name") or "") for candidate in candidates if isinstance(candidate, dict)}
        if len(names) == 1 and names:
            return "upstream_dedupe_candidate"
        return "manual_disambiguation_required"
    if method == "no_match":
        return "atlas_alias_gap"
    if method == "alias_exact":
        return "verified_exact"
    return "other"


def build_review_rows(snapshot: dict[str, Any], current_titles: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in snapshot.get("lineup_resolved") or []:
        if row.get("match_method") not in {"fuzzy_multiple", "no_match"}:
            continue
        event_id = str(row.get("event_id") or "")
        meta = current_titles.get(event_id, {})
        candidates = []
        for candidate in row.get("candidates") or []:
            if not isinstance(candidate, dict):
                continue
            candidates.append({
                "artist_id": candidate.get("artist_id"),
                "canonical_name": candidate.get("canonical_name"),
                "score": candidate.get("score"),
            })
        rows.append({
            "schema_version": "weekly_atlas_disambiguation_review_row.v1",
            "event_id": event_id,
            "title": meta.get("title", ""),
            "venue": meta.get("venue", ""),
            "city_key": meta.get("city_key", ""),
            "raw": row.get("raw"),
            "match_method": row.get("match_method"),
            "match_score": row.get("match_score"),
            "review_bucket": classify_row(row),
            "recommended_action": "review_identity_or_keep_hint" if row.get("match_method") == "fuzzy_multiple" else "add_alias_only_with_source_evidence",
            "candidates": candidates,
            "front_end_safe_default": "show_with_hint" if row.get("match_method") == "fuzzy_multiple" else "hide",
            "production_write_allowed": False,
        })
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_outputs(out_dir: Path, snapshot: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    review_path = out_dir / "weekly_atlas_disambiguation_review.jsonl"
    write_jsonl(review_path, rows)
    buckets = Counter(row["review_bucket"] for row in rows)
    methods = Counter(row["match_method"] for row in rows)
    summary = {
        "schema_version": "weekly_atlas_disambiguation_review_summary.v1",
        "decision": "review_pack_ready_report_only",
        "ok": True,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "publish_package": snapshot.get("publish_package") or "",
        "review_rows": len(rows),
        "method_counts": dict(methods),
        "bucket_counts": dict(buckets),
        "production_write_executed": False,
        "qdrant_write_executed": False,
        "neo4j_write_executed": False,
        "out_jsonl": str(review_path),
    }
    (out_dir / "weekly_atlas_disambiguation_review_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    md = [
        "# Weekly Atlas Disambiguation Review",
        "",
        f"- decision: `{summary['decision']}`",
        f"- review_rows: `{len(rows)}`",
        f"- method_counts: `{dict(methods)}`",
        f"- bucket_counts: `{dict(buckets)}`",
        "- production writes: `false`",
        "",
        "This pack is for review only. Fuzzy multi-candidate rows must stay hint-only until a source-backed identity decision exists.",
        "",
    ]
    (out_dir / "weekly_atlas_disambiguation_review_summary.md").write_text("\n".join(md), encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--current", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    snapshot = load_json(args.snapshot)
    rows = build_review_rows(snapshot, load_current_titles(args.current))
    summary = write_outputs(args.out_dir, snapshot, rows)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
