#!/usr/bin/env python3
"""Audit whether Rust Club has enough evidence for an address/coordinate write.

Report-only. This script does not call map providers, read secrets, write
coordinates, mutate DB/graph/vector data, deploy, upload, or scan broad disks.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DETAIL = (
    REPO_ROOT
    / "services"
    / "weekly_activity_cloudrun"
    / "data"
    / "current_release"
    / "by-id"
    / "rust_clubu3a74c857fda5f80128.json"
)
DEFAULT_ENRICHMENT = (
    REPO_ROOT
    / "services"
    / "weekly_activity_cloudrun"
    / "data"
    / "current_release"
    / "llm"
    / "enrichments"
    / "rust_clubu3a74c857fda5f80128.json"
)
DEFAULT_SOURCE_MAP = (
    REPO_ROOT
    / "services"
    / "weekly_activity_cloudrun"
    / "data"
    / "current_release"
    / "source_actions"
    / "source_url_map.json"
)
DEFAULT_AMAP_RESULTS = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "weekly_geocode_missing_geo_amap_s20_20260531"
    / "provider_results.jsonl"
)
DEFAULT_TENCENT_RESULTS = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "weekly_geocode_missing_geo_tencent_s20_20260531"
    / "provider_results.jsonl"
)
DEFAULT_OUT_DIR = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "weekly_rust_club_geo_evidence_audit_s37_20260531"
)
PUBLIC_SEARCH_QUERIES = [
    "Rust Club 锈蚀俱乐部 大庆 地址",
    "Rust Club 锈蚀俱乐部 大庆 湖边",
    '"2026.5.30" "Rust Club" "初夏夜之梦"',
    '"锈蚀俱乐部" "大庆"',
]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(read_text(path))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in read_text(path).splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def first(*values: Any) -> str:
    for value in values:
        if isinstance(value, list):
            nested = first(*value)
            if nested:
                return nested
        elif value is not None:
            text = str(value).strip()
            if text:
                return text
    return ""


def nested(payload: dict[str, Any], *keys: str) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def source_entry(source_map: dict[str, Any], source_hash: str) -> dict[str, Any]:
    sources = source_map.get("sources")
    if isinstance(sources, dict):
        entry = sources.get(source_hash)
        return entry if isinstance(entry, dict) else {}
    return {}


def compact_provider_row(row: dict[str, Any]) -> dict[str, Any]:
    decision = row.get("decision") if isinstance(row.get("decision"), dict) else {}
    return {
        "provider": row.get("provider", ""),
        "accepted": bool(decision.get("accepted") or row.get("accepted")),
        "decision": decision.get("decision") or row.get("decision") or "",
        "reason": decision.get("reason") or row.get("reason") or "",
        "strong_place_matches": int(decision.get("strong_place_matches") or row.get("strong_place_matches") or 0),
        "status": row.get("status") or decision.get("status") or "",
        "infocode": row.get("infocode") or decision.get("infocode") or "",
    }


def provider_summary(paths: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        for row in read_jsonl(path):
            compact = compact_provider_row(row)
            compact["path"] = str(path)
            rows.append(compact)
    return rows


def build_audit(
    *,
    detail_path: Path,
    enrichment_path: Path,
    source_map_path: Path,
    amap_results: Path,
    tencent_results: Path,
    public_search_note: str,
) -> dict[str, Any]:
    detail = read_json(detail_path)
    item = detail.get("item") if isinstance(detail.get("item"), dict) else detail
    enrichment = read_json(enrichment_path) if enrichment_path.exists() else {}
    source_map = read_json(source_map_path)

    source_hash = first(
        nested(item, "source_article", "url_hash"),
        item.get("sourceHash"),
        item.get("source_hash"),
        "74c857fda5f80128",
    )
    source = source_entry(source_map, source_hash)
    enriched = nested(enrichment, "enriched", "enrichment") or {}

    address_candidates = [
        first(item.get("address")),
        first(item.get("address_full")),
        first(enriched.get("address_candidate") if isinstance(enriched, dict) else ""),
    ]
    address_candidates = [value for value in address_candidates if value]

    geo_candidates = {
        "geo_lng": item.get("geo_lng"),
        "geo_lat": item.get("geo_lat"),
        "venue_lng": item.get("venue_lng"),
        "venue_lat": item.get("venue_lat"),
    }
    provider_rows = provider_summary([amap_results, tencent_results])
    accepted_provider_rows = [row for row in provider_rows if row["accepted"]]
    strong_provider_rows = [row for row in provider_rows if row["strong_place_matches"] > 0]
    tencent_auth_errors = [
        row
        for row in provider_rows
        if "tencent" in row["provider"].lower() and ("签名验证失败" in row["reason"] or str(row["status"]) == "111")
    ]

    city_confirmed = first(item.get("city"), item.get("city_name")) == "大庆"
    source_account_confirmed = "Rust Club" in first(source.get("account_name"), item.get("source_account_name"), item.get("account"))
    street_address_present = bool(address_candidates)
    provider_accepts = bool(accepted_provider_rows)
    provider_has_strong_match = bool(strong_provider_rows)
    public_search_has_street_address = public_search_note == "public_search_found_verified_street_level_address"
    safe_to_write = street_address_present and provider_accepts and provider_has_strong_match

    blockers: list[dict[str, str]] = []
    if not street_address_present:
        blockers.append({"code": "missing_street_level_address", "detail": "detail/enrichment/source evidence has no address"})
    if not provider_accepts:
        blockers.append({"code": "no_provider_accepted_coordinate", "detail": "Amap/Tencent rows contain no accepted provider result"})
    if not provider_has_strong_match:
        blockers.append({"code": "no_strong_poi_match", "detail": "provider rows contain no strong POI match"})
    if tencent_auth_errors and not provider_accepts:
        blockers.append({"code": "tencent_auth_or_control_plane_blocked", "detail": "Tencent rows still show signature/auth status"})
    if not public_search_has_street_address:
        blockers.append({"code": "public_search_no_verified_street_address", "detail": public_search_note})

    decision = "rust_club_geo_evidence_ready_to_write" if safe_to_write else "rust_club_geo_evidence_still_blocked"
    return {
        "schema_version": "rust_club_geo_evidence_audit.v1",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "decision": decision,
        "safe_to_write_address_or_coordinate": safe_to_write,
        "candidate": {
            "event_id": first(item.get("id"), source.get("event_id")),
            "venue_id": first(item.get("venue_id")),
            "venue_name": first(item.get("venue_name")),
            "city": first(item.get("city"), item.get("city_name")),
            "title": first(item.get("title"), item.get("title_display")),
            "source_hash": source_hash,
            "source_url": first(source.get("url"), nested(item, "source_article", "url")),
            "source_account": first(source.get("account_name"), nested(item, "source_article", "account_name")),
        },
        "signals": {
            "city_confirmed": city_confirmed,
            "source_account_confirmed": source_account_confirmed,
            "street_address_present": street_address_present,
            "provider_accepts": provider_accepts,
            "provider_has_strong_match": provider_has_strong_match,
            "public_search_has_street_address": public_search_has_street_address,
        },
        "address_candidates": address_candidates,
        "geo_candidates": geo_candidates,
        "provider_rows": provider_rows,
        "public_search": {
            "queries": PUBLIC_SEARCH_QUERIES,
            "note": public_search_note,
        },
        "blockers": blockers,
        "boundary": {
            "report_only": True,
            "map_provider_called": False,
            "secret_read": False,
            "coordinate_write": False,
            "db_graph_vector_write": False,
            "deploy_upload_review": False,
            "broad_disk_scan": False,
        },
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Rust Club Geo Evidence Audit",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Safe to write address/coordinate: `{str(report['safe_to_write_address_or_coordinate']).lower()}`",
        f"- Candidate: `{report['candidate']['venue_name']}` / `{report['candidate']['city']}`",
        f"- Source URL: `{report['candidate']['source_url']}`",
        "",
        "## Signals",
        "",
    ]
    for key, value in report["signals"].items():
        lines.append(f"- `{key}`: `{str(value).lower()}`")

    lines.extend(["", "## Provider Rows", ""])
    if report["provider_rows"]:
        for row in report["provider_rows"]:
            lines.append(
                "- `{provider}` decision `{decision}`, accepted `{accepted}`, strong matches `{strong}`; reason `{reason}`".format(
                    provider=row["provider"],
                    decision=row["decision"],
                    accepted=str(row["accepted"]).lower(),
                    strong=row["strong_place_matches"],
                    reason=row["reason"],
                )
            )
    else:
        lines.append("- No provider rows were available.")

    lines.extend(["", "## Blockers", ""])
    if report["blockers"]:
        for blocker in report["blockers"]:
            lines.append(f"- `{blocker['code']}`: {blocker['detail']}")
    else:
        lines.append("- No blockers.")

    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "Report-only audit. It did not call map providers, read secrets, write coordinates, mutate DB/graph/vector data, deploy, upload, submit review, or scan broad disks.",
            "",
        ]
    )
    return "\n".join(lines)


def write_reports(report: dict[str, Any], out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "rust_club_geo_evidence_audit.json"
    md_path = out_dir / "rust_club_geo_evidence_audit.md"
    write_json(json_path, report)
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": md_path}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--detail", type=Path, default=DEFAULT_DETAIL)
    parser.add_argument("--enrichment", type=Path, default=DEFAULT_ENRICHMENT)
    parser.add_argument("--source-map", type=Path, default=DEFAULT_SOURCE_MAP)
    parser.add_argument("--amap-results", type=Path, default=DEFAULT_AMAP_RESULTS)
    parser.add_argument("--tencent-results", type=Path, default=DEFAULT_TENCENT_RESULTS)
    parser.add_argument(
        "--public-search-note",
        default="bounded_public_search_found_no_verified_street_level_address",
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_audit(
        detail_path=args.detail,
        enrichment_path=args.enrichment,
        source_map_path=args.source_map,
        amap_results=args.amap_results,
        tencent_results=args.tencent_results,
        public_search_note=args.public_search_note,
    )
    paths = write_reports(report, args.out_dir)
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "safe_to_write_address_or_coordinate": report["safe_to_write_address_or_coordinate"],
                "blocker_count": len(report["blockers"]),
                "json": str(paths["json"]),
                "markdown": str(paths["markdown"]),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
