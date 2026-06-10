#!/usr/bin/env python3
"""Build a report-only packet for weekly empty-field overwrite review.

This consumes the S47 entity/field unification audit output and expands the
empty-overwrite review queue with current-release item details. It does not
merge, promote, or write production data.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_AUDIT_JSON = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "weekly_entity_field_unification_s47_20260531"
    / "weekly_entity_field_unification_audit.json"
)
DEFAULT_CURRENT_JSON = REPO_ROOT / "services" / "weekly_activity_cloudrun" / "data" / "current_release" / "current.json"
DEFAULT_OUT_DIR = (
    REPO_ROOT / "tools" / "stage7_rewrite" / "reports" / "weekly_empty_overwrite_review_s48_20260531"
)

FIELD_GROUPS = {
    "ids": ["id", "event_id", "sourceRefId", "source_ref_id", "sourceHash", "source_hash", "venue_id"],
    "venue": ["venue_id", "venue_name", "venue", "city", "city_key", "address", "address_full"],
    "geo": ["geo_lng", "geo_lat", "venue_lng", "venue_lat", "gcj02_lng", "gcj02_lat", "map_location"],
    "source": ["sourceRefId", "source_ref_id", "sourceHash", "source_hash", "source_action", "source_article"],
    "music": ["music_styles", "musicStyles", "style_tags", "genres", "external_links", "music_links", "mixtape"],
    "relations": ["collaborators", "relations", "sameEventCount", "frequentVenues", "residentDJs", "history", "sourceRefs"],
}


def rel(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def load_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    return json.loads(path.read_text(encoding="utf-8"))


def text(value: Any) -> str:
    if isinstance(value, list):
        return str(value[0] if value else "").strip()
    return str(value or "").strip()


def has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, list):
        return any(has_value(item) for item in value)
    if isinstance(value, dict):
        return any(has_value(item) for item in value.values())
    return bool(value)


def current_items(payload: Any) -> list[dict[str, Any]]:
    items = payload.get("items") if isinstance(payload, dict) else payload if isinstance(payload, list) else []
    return [item for item in items if isinstance(item, dict)]


def non_empty_fields(item: dict[str, Any], fields: list[str]) -> list[str]:
    return sorted(field for field in fields if has_value(item.get(field)))


def item_summary(item: dict[str, Any], field_groups_at_risk: list[dict[str, Any]]) -> dict[str, Any]:
    group_status = []
    blank_groups = []
    for group in field_groups_at_risk:
        group_name = text(group.get("field_group"))
        fields = FIELD_GROUPS.get(group_name, [])
        present = non_empty_fields(item, fields)
        is_blank = not present
        if is_blank:
            blank_groups.append(group_name)
        group_status.append(
            {
                "field_group": group_name,
                "present_fields": present,
                "blank_in_this_item": is_blank,
            }
        )

    return {
        "id": text(item.get("id")),
        "title": text(item.get("title") or item.get("event_title") or item.get("name")),
        "venue_id": text(item.get("venue_id") or item.get("venueId")),
        "venue_name": text(item.get("venue_name") or item.get("venue") or item.get("venueLabel")),
        "city": text(item.get("city") or item.get("city_name") or item.get("city_key")),
        "event_date": text(item.get("event_date_start") or item.get("event_date_iso_guess")),
        "address": text(item.get("address_full") or item.get("address") or item.get("venue_address")),
        "source_ref_id": text(item.get("sourceRefId") or item.get("source_ref_id")),
        "field_group_status": group_status,
        "blank_risk_groups": blank_groups,
        "would_overwrite_if_used_as_base": bool(blank_groups),
    }


def build_packet(audit_payload: dict[str, Any], current_payload: Any) -> dict[str, Any]:
    items_by_id = {text(item.get("id")): item for item in current_items(current_payload)}
    candidates = audit_payload.get("review_queue", {}).get("empty_overwrite_candidates", [])
    expanded_candidates = []
    missing_item_ids: list[str] = []

    for index, candidate in enumerate(candidates, start=1):
        field_groups_at_risk = candidate.get("field_groups_at_risk") or []
        item_ids = [text(item_id) for item_id in candidate.get("item_ids") or [] if text(item_id)]
        summaries = []
        for item_id in item_ids:
            item = items_by_id.get(item_id)
            if item is None:
                missing_item_ids.append(item_id)
                summaries.append(
                    {
                        "id": item_id,
                        "missing_from_current_release": True,
                        "would_overwrite_if_used_as_base": True,
                        "blank_risk_groups": [text(group.get("field_group")) for group in field_groups_at_risk],
                    }
                )
                continue
            summaries.append(item_summary(item, field_groups_at_risk))

        blank_item_count = sum(1 for summary in summaries if summary.get("would_overwrite_if_used_as_base"))
        expanded_candidates.append(
            {
                "review_id": f"empty_overwrite_s48_{index:03d}",
                "dedupe_scope": candidate.get("dedupe_scope") or {},
                "field_groups_at_risk": field_groups_at_risk,
                "item_count": len(summaries),
                "blank_item_count": blank_item_count,
                "safe_automerge": False,
                "required_merge_rule": "merge_non_empty_only; blank_or_missing_fields_are_noop",
                "recommended_action": (
                    "Review only. Preserve non-empty music/style/source/geo/relation fields from richer items; "
                    "do not let blank weekly/current fields overwrite DB2/DB3 history."
                ),
                "items": summaries,
            }
        )

    unique_venues = sorted(
        {
            text(candidate.get("dedupe_scope", {}).get("venue_key"))
            for candidate in expanded_candidates
            if text(candidate.get("dedupe_scope", {}).get("venue_key"))
        }
    )
    return {
        "schema_version": "weekly_empty_overwrite_review_packet.v1",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "decision": (
            "weekly_empty_overwrite_review_packet_ready"
            if expanded_candidates
            else "weekly_empty_overwrite_review_packet_empty"
        ),
        "summary": {
            "candidate_count": len(expanded_candidates),
            "unique_venue_count": len(unique_venues),
            "missing_item_ids": missing_item_ids,
            "blank_item_count": sum(candidate["blank_item_count"] for candidate in expanded_candidates),
            "high_findings": 0,
        },
        "rules": [
            "This packet is report-only and must not write DB1/DB2/DB3.",
            "Blank weekly/current fields are no-op overlays.",
            "Promotion into DB1/DB2/DB3 needs a separate review and write gate.",
            "Use sourceRefId/source_ref_id and venue/date/address scope before dedupe decisions.",
        ],
        "safety": {
            "report_only": True,
            "pipeline_executed": False,
            "provider_calls_performed": False,
            "database_mutations": False,
            "deployment_executed": False,
            "secrets_read": False,
        },
        "candidates": expanded_candidates,
    }


def write_outputs(packet: dict[str, Any], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "weekly_empty_overwrite_review_packet.json"
    jsonl_path = out_dir / "weekly_empty_overwrite_review_candidates.jsonl"
    md_path = out_dir / "weekly_empty_overwrite_review_packet.md"
    json_path.write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with jsonl_path.open("w", encoding="utf-8") as fh:
        for candidate in packet["candidates"]:
            fh.write(json.dumps(candidate, ensure_ascii=False, sort_keys=True) + "\n")
    md_path.write_text(render_markdown(packet), encoding="utf-8")


def render_markdown(packet: dict[str, Any]) -> str:
    summary = packet["summary"]
    lines = [
        "# Weekly Empty Overwrite Review Packet S48",
        "",
        f"Generated: `{packet['generated_at']}`",
        "",
        f"Decision: `{packet['decision']}`",
        "",
        "## Summary",
        "",
        f"- Candidate count: `{summary['candidate_count']}`",
        f"- Unique venues: `{summary['unique_venue_count']}`",
        f"- Blank-risk item count: `{summary['blank_item_count']}`",
        f"- Missing item ids: `{len(summary['missing_item_ids'])}`",
        f"- High findings: `{summary['high_findings']}`",
        "",
        "## Candidates",
        "",
        "| Review id | Date | City | Venue key | Items | Blank-risk items | Field groups |",
        "| --- | --- | --- | --- | ---: | ---: | --- |",
    ]
    for candidate in packet["candidates"]:
        scope = candidate["dedupe_scope"]
        groups = ", ".join(text(group.get("field_group")) for group in candidate["field_groups_at_risk"])
        lines.append(
            "| {review_id} | {date} | {city} | {venue} | {items} | {blank} | {groups} |".format(
                review_id=candidate["review_id"],
                date=text(scope.get("date")),
                city=text(scope.get("city_key")),
                venue=text(scope.get("venue_key")),
                items=candidate["item_count"],
                blank=candidate["blank_item_count"],
                groups=groups,
            )
        )
    lines.extend(
        [
            "",
            "## Required Rule",
            "",
            "- Preserve non-empty fields from richer source/current items.",
            "- Treat blank fields as no-op overlays.",
            "- Do not promote these rows into DB1/DB2/DB3 without a separate write gate.",
            "",
            "## Safety",
            "",
            f"- `report_only`: `{packet['safety']['report_only']}`",
            f"- `pipeline_executed`: `{packet['safety']['pipeline_executed']}`",
            f"- `provider_calls_performed`: `{packet['safety']['provider_calls_performed']}`",
            f"- `database_mutations`: `{packet['safety']['database_mutations']}`",
            f"- `deployment_executed`: `{packet['safety']['deployment_executed']}`",
            f"- `secrets_read`: `{packet['safety']['secrets_read']}`",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-json", type=Path, default=DEFAULT_AUDIT_JSON)
    parser.add_argument("--current-json", type=Path, default=DEFAULT_CURRENT_JSON)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    audit_payload = load_json(args.audit_json, {})
    current_payload = load_json(args.current_json, {"items": []})
    packet = build_packet(audit_payload, current_payload)
    write_outputs(packet, args.out_dir)
    print(
        json.dumps(
            {
                "decision": packet["decision"],
                "candidate_count": packet["summary"]["candidate_count"],
                "blank_item_count": packet["summary"]["blank_item_count"],
                "json": str(args.out_dir / "weekly_empty_overwrite_review_packet.json"),
                "markdown": str(args.out_dir / "weekly_empty_overwrite_review_packet.md"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
