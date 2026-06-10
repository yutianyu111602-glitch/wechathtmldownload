#!/usr/bin/env python3
"""Build a source-safe weekly Golden annotation pack."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"expected object JSON: {path}")
    return data


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def build_pack(current: dict[str, Any], audit: dict[str, Any], snapshot: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    item_by_id = {item.get("id") or item.get("event_id"): item for item in current.get("items") or []}
    snapshot_by_event: dict[str, list[dict[str, Any]]] = {}
    for row in snapshot.get("lineup_resolved") or []:
        snapshot_by_event.setdefault(str(row.get("event_id") or ""), []).append(row)

    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def add(event_id: str, stratum: str, reason: str) -> None:
        if not event_id or (event_id, stratum) in seen or len(rows) >= limit:
            return
        seen.add((event_id, stratum))
        item = item_by_id.get(event_id, {})
        atlas_rows = snapshot_by_event.get(event_id, [])
        venue_value = item.get("venue_name") or ""
        if not venue_value:
            raw_venue = item.get("venue")
            venue_value = raw_venue[0] if isinstance(raw_venue, list) and raw_venue else raw_venue or ""
        rows.append({
            "schema_version": "weekly_golden_annotation_candidate.v1",
            "event_id": event_id,
            "stratum": stratum,
            "reason": reason,
            "annotation_status": "pending",
            "title": item.get("title") or item.get("display_title") or "",
            "city_key": item.get("city_key") or "",
            "venue": venue_value,
            "event_date_start": item.get("event_date_start") or item.get("event_date_iso_guess") or "",
            "pipeline_lineup": item.get("lineup_artists") or item.get("lineup") or [],
            "gold_lineup": [],
            "gold_decision": "",
            "atlas_methods": dict(Counter(row.get("match_method") for row in atlas_rows)),
            "atlas_rows": [
                {
                    "raw": row.get("raw"),
                    "match_method": row.get("match_method"),
                    "display_tier": row.get("display_tier"),
                    "canonical_name": row.get("canonical_name"),
                }
                for row in atlas_rows[:8]
            ],
        })

    for issue in (audit.get("issues") or {}).get("missing_lineup") or []:
        add(str(issue.get("id") or ""), "missing_lineup", "strict audit reports missing lineup")
    for row in snapshot.get("lineup_resolved") or []:
        if row.get("match_method") == "fuzzy_multiple":
            add(str(row.get("event_id") or ""), "atlas_fuzzy_multiple", "Atlas has multiple candidates; verify identity or keep hint-only")
        elif row.get("match_method") == "no_match":
            add(str(row.get("event_id") or ""), "atlas_no_match", "Atlas alias gap; add only if source evidence supports identity")
        elif row.get("match_method") == "alias_exact":
            add(str(row.get("event_id") or ""), "atlas_alias_exact_sample", "sample exact binding for precision check")
    return rows


def write_outputs(out_dir: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    pack_path = out_dir / "weekly_golden_annotation_candidates.jsonl"
    write_jsonl(pack_path, rows)
    strata = Counter(row["stratum"] for row in rows)
    summary = {
        "schema_version": "weekly_golden_annotation_pack_summary.v1",
        "decision": "golden_annotation_pack_ready",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "candidate_count": len(rows),
        "stratum_counts": dict(strata),
        "annotation_status": {"pending": len(rows), "verified": 0},
        "out_jsonl": str(pack_path),
    }
    (out_dir / "weekly_golden_annotation_pack_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    md = [
        "# Weekly Golden Annotation Pack",
        "",
        f"- decision: `{summary['decision']}`",
        f"- candidate_count: `{len(rows)}`",
        f"- stratum_counts: `{dict(strata)}`",
        "",
        "Annotate `gold_lineup` and `gold_decision` before using this pack as verified evaluation truth.",
        "",
    ]
    (out_dir / "weekly_golden_annotation_pack_summary.md").write_text("\n".join(md), encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=120)
    args = parser.parse_args()

    rows = build_pack(load_json(args.current), load_json(args.audit), load_json(args.snapshot), args.limit)
    print(json.dumps(write_outputs(args.out_dir, rows), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
