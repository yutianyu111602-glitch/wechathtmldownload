#!/usr/bin/env python3
"""Audit weekly entity/field unification without running the pipeline.

This is a read-only guard for the user's current priority:
- DB1/DB2/DB3 field contracts stay authoritative.
- Non-same-name same-entity venue candidates are visible for review.
- Empty fields must not overwrite richer source/geo/music/relation fields.
- Frontend and backend dedupe contracts remain aligned.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CURRENT = REPO_ROOT / "services" / "weekly_activity_cloudrun" / "data" / "current_release" / "current.json"
DEFAULT_VENUE_REGISTRY = REPO_ROOT / "tools" / "stage7_rewrite" / "registries" / "weekly_venues_seed.json"
DEFAULT_FRONTEND_FORMAT = REPO_ROOT / "apps" / "weekly_activity_miniprogram" / "utils" / "format.js"
DEFAULT_BACKEND_STORE = REPO_ROOT / "services" / "weekly_activity_cloudrun" / "src" / "dataStore.mjs"
DEFAULT_FRONTEND_TEST = REPO_ROOT / "apps" / "weekly_activity_miniprogram" / "tests" / "format-quality.test.cjs"
DEFAULT_BACKEND_TEST = REPO_ROOT / "services" / "weekly_activity_cloudrun" / "tests" / "weeklyApi.test.mjs"
DEFAULT_DB_FIELD_CONTRACT = (
    REPO_ROOT / "tools" / "stage7_rewrite" / "reports" / "atlas_db_field_contract_20260531" / "atlas_db_field_contract.json"
)
DEFAULT_RELATION_FIELD_CONTRACT = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "weekly_deploy_upload_preflight_s35_final_20260531"
    / "atlas_relation_field_integrity"
    / "atlas_relation_field_integrity.json"
)
DEFAULT_OUT_DIR = REPO_ROOT / "tools" / "stage7_rewrite" / "reports" / "weekly_entity_field_unification_s47_20260531"

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


def normalize(value: Any) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", text(value).lower()).strip()


def city_of(row: dict[str, Any]) -> str:
    return normalize(row.get("city_key") or row.get("city") or row.get("city_name"))


def address_of(row: dict[str, Any]) -> str:
    return normalize(row.get("address_full") or row.get("address") or row.get("venue_address"))


def venue_name_of(row: dict[str, Any]) -> str:
    return text(row.get("venue_name") or row.get("venueLabel") or row.get("venue") or row.get("canonical_name"))


def venue_id_of(row: dict[str, Any]) -> str:
    return text(row.get("venue_id") or row.get("venueId"))


def current_items(payload: Any) -> list[dict[str, Any]]:
    items = payload.get("items") if isinstance(payload, dict) else payload if isinstance(payload, list) else []
    return [item for item in items if isinstance(item, dict)]


def registry_rows(payload: Any) -> list[dict[str, Any]]:
    rows = payload.get("venues") if isinstance(payload, dict) else payload if isinstance(payload, list) else []
    return [row for row in rows if isinstance(row, dict)]


def name_set_for_registry(row: dict[str, Any]) -> set[str]:
    names = {normalize(row.get("canonical_name")), normalize(row.get("venue_name"))}
    for alias in row.get("aliases") or []:
        names.add(normalize(alias))
    return {name for name in names if name}


def group_same_address(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        city = city_of(row)
        address = address_of(row)
        if city and address:
            groups[(city, address)].append(row)
    findings = []
    for (city, address), group in sorted(groups.items()):
        ids = sorted({venue_id_of(row) for row in group if venue_id_of(row)})
        names = sorted({venue_name_of(row) for row in group if venue_name_of(row)})
        if len(ids) > 1 or len({normalize(name) for name in names}) > 1:
            findings.append(
                {
                    "city_key": city,
                    "address_key": address,
                    "venue_ids": ids,
                    "venue_names": names[:12],
                    "row_count": len(group),
                }
            )
    return findings


def find_registry_alias_mismatches(items: list[dict[str, Any]], registry: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {venue_id_of(row): row for row in registry if venue_id_of(row)}
    mismatches = []
    for item in items:
        venue_id = venue_id_of(item)
        if not venue_id or venue_id not in by_id:
            continue
        name = normalize(venue_name_of(item))
        if not name:
            continue
        row = by_id[venue_id]
        aliases = name_set_for_registry(row)
        if name not in aliases:
            mismatches.append(
                {
                    "id": text(item.get("id")),
                    "venue_id": venue_id,
                    "venue_name": venue_name_of(item),
                    "registry_canonical": text(row.get("canonical_name")),
                    "same_address": bool(address_of(item) and address_of(item) == address_of(row)),
                }
            )
    return mismatches


def non_empty_fields(item: dict[str, Any], fields: list[str]) -> set[str]:
    return {field for field in fields if has_value(item.get(field))}


def find_empty_overwrite_candidates(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        date = text(item.get("event_date_start") or item.get("event_date_iso_guess"))
        city = city_of(item)
        venue_key = venue_id_of(item) or normalize(venue_name_of(item))
        address = address_of(item)
        if date and city and (venue_key or address):
            groups[(date, city, venue_key, address)].append(item)
    candidates = []
    for key, group in groups.items():
        if len(group) < 2:
            continue
        group_findings = []
        for group_name, fields in FIELD_GROUPS.items():
            coverage = [non_empty_fields(item, fields) for item in group]
            union = set().union(*coverage)
            if not union:
                continue
            if any(not values for values in coverage):
                group_findings.append({"field_group": group_name, "present_fields": sorted(union)})
        if group_findings:
            candidates.append(
                {
                    "dedupe_scope": {"date": key[0], "city_key": key[1], "venue_key": key[2], "address_key": key[3]},
                    "item_ids": [text(item.get("id")) for item in group[:10]],
                    "field_groups_at_risk": group_findings,
                }
            )
    return candidates[:80]


def static_token_report(path: Path, tokens: list[str]) -> dict[str, Any]:
    if not path.exists():
        return {"path": rel(path), "exists": False, "tokens": {token: False for token in tokens}}
    content = path.read_text(encoding="utf-8", errors="ignore")
    return {"path": rel(path), "exists": True, "tokens": {token: token in content for token in tokens}}


def existing_contract_decision(path: Path) -> dict[str, Any]:
    payload = load_json(path, {})
    return {
        "path": rel(path),
        "exists": path.exists(),
        "decision": text(payload.get("decision")) if isinstance(payload, dict) else "",
        "finding_count": len(payload.get("findings") or []) if isinstance(payload, dict) else 0,
    }


def summarize(
    current_payload: Any,
    registry_payload: Any,
    *,
    frontend_format: Path = DEFAULT_FRONTEND_FORMAT,
    backend_store: Path = DEFAULT_BACKEND_STORE,
    frontend_test: Path = DEFAULT_FRONTEND_TEST,
    backend_test: Path = DEFAULT_BACKEND_TEST,
    db_field_contract: Path = DEFAULT_DB_FIELD_CONTRACT,
    relation_field_contract: Path = DEFAULT_RELATION_FIELD_CONTRACT,
) -> dict[str, Any]:
    items = current_items(current_payload)
    venues = registry_rows(registry_payload)
    active_venues = [row for row in venues if text(row.get("status")).lower() != "deprecated"]
    registry_same_address = group_same_address(active_venues)
    current_same_address = group_same_address(items)
    alias_mismatches = find_registry_alias_mismatches(items, active_venues)
    empty_overwrite_candidates = find_empty_overwrite_candidates(items)

    static_contract = {
        "frontend_format": static_token_report(
            frontend_format,
            ["mergeNonEmpty", "dedupeItems", "areLikelyDuplicateItems", "sameAddress", "sourceRefId", "source_ref_id"],
        ),
        "backend_store": static_token_report(
            backend_store,
            ["mergeNonEmpty", "dedupeItems", "areLikelyDuplicateItems", "sameAddress", "sourceRefId", "source_ref_id"],
        ),
        "frontend_test": static_token_report(frontend_test, ["keeps non-empty fields", "mergeNonEmpty ignores empty overlay"]),
        "backend_test": static_token_report(backend_test, ["dedupe preserves non-empty fields"]),
    }
    findings: list[dict[str, Any]] = []
    for name, entry in static_contract.items():
        missing = [token for token, present in entry["tokens"].items() if not present]
        if missing:
            findings.append({"severity": "high", "check": f"{name}_missing_static_contract_tokens", "missing": missing})

    db_contracts = {
        "db_field_contract": existing_contract_decision(db_field_contract),
        "relation_field_contract": existing_contract_decision(relation_field_contract),
    }
    for name, entry in db_contracts.items():
        if not entry["exists"] or not entry["decision"]:
            findings.append({"severity": "warning", "check": f"{name}_not_found_or_unreadable", "path": entry["path"]})
        elif "findings" in entry["decision"] and entry["finding_count"]:
            findings.append({"severity": "high", "check": f"{name}_has_findings", "decision": entry["decision"]})

    review_queue = {
        "registry_same_address_multi_id": registry_same_address,
        "current_same_address_multi_name_or_id": current_same_address,
        "current_registry_alias_mismatches": alias_mismatches[:80],
        "empty_overwrite_candidates": empty_overwrite_candidates,
    }
    review_count = sum(len(value) for value in review_queue.values())
    if not any(f["severity"] == "high" for f in findings) and review_count:
        decision = "weekly_entity_field_unification_passed_with_review_queue"
    elif any(f["severity"] == "high" for f in findings):
        decision = "weekly_entity_field_unification_findings"
    else:
        decision = "weekly_entity_field_unification_passed"

    return {
        "schema_version": "weekly_entity_field_unification_audit.v1",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "decision": decision,
        "summary": {
            "current_item_count": len(items),
            "registry_active_count": len(active_venues),
            "review_queue_count": review_count,
            "high_finding_count": sum(1 for finding in findings if finding["severity"] == "high"),
        },
        "findings": findings,
        "review_queue": review_queue,
        "db_contracts": db_contracts,
        "static_contract": static_contract,
        "rules": [
            "DB1 supplies raw/source evidence; DB2 supplies relation/read-model truth; DB3 supplies the mobile projection.",
            "Non-same-name same-address venue candidates must be review-visible before merge or alias promotion.",
            "Empty weekly/current fields must never overwrite non-empty source, geo, music, or relation fields.",
            "Frontend and backend dedupe must both use non-empty coalescing and sourceRefId-aware aliases.",
        ],
        "safety": {
            "report_only": True,
            "pipeline_executed": False,
            "provider_calls_performed": False,
            "database_mutations": False,
            "deployment_executed": False,
            "secrets_read": False,
        },
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    summary = report["summary"]
    lines = [
        "# Weekly Entity Field Unification Audit S47",
        "",
        f"Generated: `{report['generated_at']}`",
        "",
        f"Decision: `{report['decision']}`",
        "",
        "## Summary",
        "",
        f"- Current items: `{summary['current_item_count']}`",
        f"- Registry active rows: `{summary['registry_active_count']}`",
        f"- Review queue rows: `{summary['review_queue_count']}`",
        f"- High findings: `{summary['high_finding_count']}`",
        "",
        "## Review Queue",
        "",
    ]
    for key, rows in report["review_queue"].items():
        lines.append(f"- `{key}`: `{len(rows)}`")
    lines.extend(["", "## Existing DB Contracts", ""])
    for key, entry in report["db_contracts"].items():
        lines.append(f"- `{key}`: exists `{entry['exists']}`, decision `{entry['decision']}`, findings `{entry['finding_count']}`")
    lines.extend(["", "## Static Contract", ""])
    for key, entry in report["static_contract"].items():
        present = [token for token, ok in entry["tokens"].items() if ok]
        missing = [token for token, ok in entry["tokens"].items() if not ok]
        lines.append(f"- `{key}`: present `{len(present)}`, missing `{len(missing)}`")
        if missing:
            lines.append(f"  - missing: `{', '.join(missing)}`")
    lines.extend(["", "## Findings", ""])
    if report["findings"]:
        for finding in report["findings"]:
            lines.append(f"- `{finding['severity']}` `{finding['check']}`")
    else:
        lines.append("- none")
    lines.extend(["", "## Rules", ""])
    lines.extend(f"- {rule}" for rule in report["rules"])
    lines.extend(["", "## Safety", ""])
    for key, value in report["safety"].items():
        lines.append(f"- `{key}`: `{value}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current-json", type=Path, default=DEFAULT_CURRENT)
    parser.add_argument("--venue-registry", type=Path, default=DEFAULT_VENUE_REGISTRY)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args(argv)

    report = summarize(
        load_json(args.current_json, {}),
        load_json(args.venue_registry, {}),
        frontend_format=DEFAULT_FRONTEND_FORMAT,
        backend_store=DEFAULT_BACKEND_STORE,
        frontend_test=DEFAULT_FRONTEND_TEST,
        backend_test=DEFAULT_BACKEND_TEST,
        db_field_contract=DEFAULT_DB_FIELD_CONTRACT,
        relation_field_contract=DEFAULT_RELATION_FIELD_CONTRACT,
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.out_dir / "weekly_entity_field_unification_audit.json", report)
    write_markdown(args.out_dir / "weekly_entity_field_unification_audit.md", report)
    print(json.dumps({"decision": report["decision"], **report["summary"]}, ensure_ascii=False, sort_keys=True))
    return 1 if report["summary"]["high_finding_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
