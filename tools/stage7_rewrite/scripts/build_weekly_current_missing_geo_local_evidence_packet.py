#!/usr/bin/env python3
"""Build a no-write local evidence packet for current missing-geo rows.

This packet joins the current source-address queue against the local
recommendation pack and weekly venue registry. It does not fetch articles,
call map providers, call models, start Docker/workers, write coordinates,
mutate registries/current releases/databases, deploy, upload, submit review,
read secrets, or scan broad disks.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
REPORTS_ROOT = REPO_ROOT / "tools" / "stage7_rewrite" / "reports"
REPORTS_MD_ROOT = REPO_ROOT / "reports"

SCHEMA_VERSION = "weekly_current_missing_geo_local_evidence_packet.v1"
DEFAULT_SOURCE_ADDRESS_PACKET = (
    REPORTS_ROOT
    / "weekly_current_missing_geo_source_address_packet_20260603"
    / "weekly_current_missing_geo_source_address_packet.json"
)
DEFAULT_CANDIDATE_JSONL = [
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "longrun"
    / "WEEKLY_ACTIVITY_EXPANDED_PACK_20260602"
    / "weekly_activity_recommendation_candidates.jsonl",
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "longrun"
    / "WEEKLY_ACTIVITY_EXPANDED_PACK_20260602"
    / "weekly_activity_recommendation_review_candidates.jsonl",
]
DEFAULT_VENUE_REGISTRY = REPO_ROOT / "tools" / "stage7_rewrite" / "registries" / "weekly_venues_seed.json"
DEFAULT_OUT_DIR = REPORTS_ROOT / "weekly_current_missing_geo_local_evidence_packet_20260603"
DEFAULT_SCORECARD = REPORTS_MD_ROOT / "WEEKLY_CURRENT_MISSING_GEO_LOCAL_EVIDENCE_PACKET_20260603.md"

PRIVATE_PATH_RE = re.compile(r"(?:[A-Za-z]:\\|/mnt/[a-z]/|/home/pc/|\\\\)", re.IGNORECASE)
SECRET_RE = re.compile(
    r"(?:bearer\s+[a-z0-9._~+/=-]+|sk-[a-z0-9]{12,}|x-auth-key\s*[:=]|"
    r"cookie_value|token_value|password\s*[:=]|authorization\s*[:=]|sessionid=|api[_-]?key\s*[:=])",
    re.IGNORECASE,
)


def now_local() -> str:
    return datetime.now(timezone.utc).astimezone().replace(microsecond=0).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        text = line.strip()
        if not text:
            continue
        value = json.loads(text)
        if isinstance(value, dict):
            value["_input_path"] = display_path(path)
            value["_input_line"] = line_number
            out.append(value)
    return out


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, payload: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in payload)
    path.write_text(text + ("\n" if text else ""), encoding="utf-8")


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return str(path)


def first(*values: Any) -> str:
    for value in values:
        if isinstance(value, list):
            nested = first(*value)
            if nested:
                return nested
            continue
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def source_rows(source_address_packet: dict[str, Any]) -> list[dict[str, Any]]:
    value = source_address_packet.get("source_address_rows")
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, dict)]


def normalize_key(value: Any) -> str:
    text = first(value).lower()
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[_\-·•|｜/\\:：()（）\[\]【】\"“”']", "", text)
    for token in ("club", "bar", "厂牌", "公社", "电音"):
        text = text.replace(token, "")
    return text


def strip_schedule_suffix(value: str) -> str:
    if ":schedule:" in value:
        return value.split(":schedule:", 1)[0]
    return value


def candidate_ids(row: dict[str, Any]) -> list[str]:
    values = [first(row.get("article_id")), first(row.get("queue_id"))]
    for value in list(values):
        if value:
            values.append(strip_schedule_suffix(value))
    unique: list[str] = []
    for value in values:
        if value and value not in unique:
            unique.append(value)
    return unique


def index_candidates(candidate_rows: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_id: dict[str, dict[str, Any]] = {}
    by_url: dict[str, dict[str, Any]] = {}
    for row in candidate_rows:
        for candidate_id in candidate_ids(row):
            by_id.setdefault(candidate_id, row)
        source_url = first(row.get("source_url"))
        if source_url:
            by_url.setdefault(source_url, row)
    return by_id, by_url


def match_candidate(row: dict[str, Any], by_id: dict[str, dict[str, Any]], by_url: dict[str, dict[str, Any]]) -> dict[str, Any]:
    ids = [first(row.get("current_item_id")), first(row.get("event_id"))]
    for value in list(ids):
        if value:
            ids.append(strip_schedule_suffix(value))
    for value in ids:
        if value in by_id:
            return by_id[value]
    source_url = first(row.get("source_url"))
    if source_url in by_url:
        return by_url[source_url]
    return {}


def registry_rows(venue_registry: dict[str, Any]) -> list[dict[str, Any]]:
    value = venue_registry.get("venues")
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, dict)]


def registry_keys(row: dict[str, Any]) -> set[str]:
    keys = {
        normalize_key(row.get("venue_id")),
        normalize_key(row.get("canonical_name")),
        normalize_key(row.get("map_poi_name")),
    }
    keys.update(normalize_key(alias) for alias in as_list(row.get("aliases")))
    return {key for key in keys if key}


def row_registry_candidates(source_row: dict[str, Any], candidate: dict[str, Any]) -> set[str]:
    values = {
        normalize_key(source_row.get("venue_name")),
        normalize_key(source_row.get("source_account_name")),
        normalize_key(first(source_row.get("current_item_id")).split(":", 1)[0]),
        normalize_key(candidate.get("account_key")),
    }
    values.update(normalize_key(value) for value in as_list(candidate.get("venue")))
    return {value for value in values if value}


def match_registry(
    source_row: dict[str, Any],
    candidate: dict[str, Any],
    venues: list[dict[str, Any]],
) -> tuple[str, dict[str, Any], list[str]]:
    city = first(source_row.get("city"), candidate.get("city"))
    candidates = row_registry_candidates(source_row, candidate)
    hits: list[dict[str, Any]] = []
    for venue in venues:
        registry_city = first(venue.get("city_name"), venue.get("city_key"))
        if registry_city != city:
            continue
        if candidates & registry_keys(venue):
            hits.append(venue)
    if len(hits) == 1:
        return "single_match", hits[0], []
    if not hits:
        return "no_match", {}, []
    return "ambiguous_match", {}, [first(hit.get("venue_id")) for hit in hits]


def bool_geo(row: dict[str, Any]) -> bool:
    return bool(first(row.get("geo_lng")) and first(row.get("geo_lat")))


def evidence_status(candidate: dict[str, Any], registry_status: str, registry: dict[str, Any]) -> str:
    candidate_address = bool(first(candidate.get("address")))
    candidate_geo = bool_geo(candidate)
    registry_address = bool(first(registry.get("address_full")))
    registry_geo = bool_geo(registry)
    registry_active = first(registry.get("status")) == "active"
    if candidate_address and candidate_geo:
        return "source_candidate_address_geo_available"
    if candidate_address:
        return "source_candidate_address_available_needs_provider_verification"
    if registry_status == "single_match" and registry_active and registry_address and registry_geo:
        return "venue_registry_address_geo_available_needs_review"
    if registry_status == "single_match" and registry_address:
        return "venue_registry_address_available_needs_provider_verification"
    if registry_status == "ambiguous_match":
        return "ambiguous_registry_match_needs_review"
    return "needs_source_address_fetch"


def build_evidence_row(
    *,
    source_row: dict[str, Any],
    candidate: dict[str, Any],
    registry_status: str,
    registry: dict[str, Any],
    ambiguous_registry_venue_ids: list[str],
    index: int,
) -> dict[str, Any]:
    status = evidence_status(candidate, registry_status, registry)
    return {
        "schema_version": SCHEMA_VERSION,
        "row_id": f"local_evidence:{index:03d}:{first(source_row.get('current_item_id'), 'missing-id')}",
        "source_address_row_id": first(source_row.get("row_id")),
        "current_item_id": first(source_row.get("current_item_id")),
        "event_id": first(source_row.get("event_id")),
        "title": first(source_row.get("title"), candidate.get("title")),
        "city": first(source_row.get("city"), candidate.get("city")),
        "venue_name": first(source_row.get("venue_name")),
        "source_account_name": first(source_row.get("source_account_name")),
        "source_url": first(source_row.get("source_url"), candidate.get("source_url")),
        "candidate_match_status": "matched" if candidate else "unmatched",
        "candidate_input_path": first(candidate.get("_input_path")),
        "candidate_input_line": candidate.get("_input_line"),
        "candidate_article_id": first(candidate.get("article_id")),
        "candidate_queue_id": first(candidate.get("queue_id")),
        "candidate_address": first(candidate.get("address")),
        "candidate_geo_lng": first(candidate.get("geo_lng")),
        "candidate_geo_lat": first(candidate.get("geo_lat")),
        "candidate_evidence_sample": [first(value) for value in as_list(candidate.get("evidence"))[:5]],
        "registry_match_status": registry_status,
        "ambiguous_registry_venue_ids": ambiguous_registry_venue_ids,
        "registry_venue_id": first(registry.get("venue_id")),
        "registry_canonical_name": first(registry.get("canonical_name")),
        "registry_city_name": first(registry.get("city_name")),
        "registry_address_full": first(registry.get("address_full")),
        "registry_geo_lng": registry.get("geo_lng"),
        "registry_geo_lat": registry.get("geo_lat"),
        "registry_geo_coord_system": first(registry.get("geo_coord_system")),
        "registry_geo_source": first(registry.get("geo_source")),
        "registry_last_verified_at": first(registry.get("last_verified_at")),
        "registry_status": first(registry.get("status")),
        "registry_source_note": first(registry.get("source_note")),
        "registry_place_fields_locked": registry.get("place_fields_locked") is True,
        "registry_geo_locked": registry.get("geo_locked") is True,
        "local_evidence_status": status,
        "local_evidence_available_now": status in {
            "source_candidate_address_geo_available",
            "source_candidate_address_available_needs_provider_verification",
            "venue_registry_address_geo_available_needs_review",
            "venue_registry_address_available_needs_provider_verification",
        },
        "needs_source_fetch": status == "needs_source_address_fetch",
        "needs_registry_review": status in {
            "venue_registry_address_geo_available_needs_review",
            "venue_registry_address_available_needs_provider_verification",
            "ambiguous_registry_match_needs_review",
        },
        "required_next_gate": (
            "review_registry_evidence_then_provider_or_coordinate_gate"
            if status == "venue_registry_address_geo_available_needs_review"
            else "fetch_current_article_or_official_source_for_address"
            if status == "needs_source_address_fetch"
            else "manual_registry_disambiguation"
            if status == "ambiguous_registry_match_needs_review"
            else "provider_verification_after_address_evidence"
        ),
        "provider_or_geocode_call_allowed_now": False,
        "coordinate_write_allowed_now": False,
        "registry_mutation_allowed_now": False,
        "docker_worker_allowed_now": False,
    }


def leak_findings(payload: Any) -> list[dict[str, Any]]:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    findings: list[dict[str, Any]] = []
    for label, pattern in (("private_path", PRIVATE_PATH_RE), ("secret_like", SECRET_RE)):
        matches = pattern.findall(text)
        if matches:
            findings.append({"type": label, "count": len(matches)})
    return findings


def build_packet(
    *,
    source_address_packet: dict[str, Any],
    candidate_rows: list[dict[str, Any]],
    venue_registry: dict[str, Any],
    source_address_packet_path: Path,
    candidate_paths: list[Path],
    venue_registry_path: Path,
) -> dict[str, Any]:
    by_candidate_id, by_candidate_url = index_candidates(candidate_rows)
    venues = registry_rows(venue_registry)
    evidence_rows: list[dict[str, Any]] = []
    for index, source_row in enumerate(source_rows(source_address_packet), start=1):
        candidate = match_candidate(source_row, by_candidate_id, by_candidate_url)
        registry_status, registry, ambiguous = match_registry(source_row, candidate, venues)
        evidence_rows.append(
            build_evidence_row(
                source_row=source_row,
                candidate=candidate,
                registry_status=registry_status,
                registry=registry,
                ambiguous_registry_venue_ids=ambiguous,
                index=index,
            )
        )

    status_counts = Counter(first(row.get("local_evidence_status")) for row in evidence_rows)
    city_counts = Counter(first(row.get("city")) or "unknown_city" for row in evidence_rows)
    local_evidence_available_count = sum(1 for row in evidence_rows if row["local_evidence_available_now"])
    remaining_source_fetch_count = sum(1 for row in evidence_rows if row["needs_source_fetch"])
    summary = {
        "source_address_task_count": len(evidence_rows),
        "candidate_input_row_count": len(candidate_rows),
        "candidate_match_count": sum(1 for row in evidence_rows if row["candidate_match_status"] == "matched"),
        "candidate_address_count": sum(1 for row in evidence_rows if row["candidate_address"]),
        "candidate_geo_count": sum(1 for row in evidence_rows if row["candidate_geo_lng"] and row["candidate_geo_lat"]),
        "registry_single_match_count": sum(1 for row in evidence_rows if row["registry_match_status"] == "single_match"),
        "registry_ambiguous_match_count": sum(1 for row in evidence_rows if row["registry_match_status"] == "ambiguous_match"),
        "registry_no_match_count": sum(1 for row in evidence_rows if row["registry_match_status"] == "no_match"),
        "registry_active_address_geo_count": sum(
            1
            for row in evidence_rows
            if row["registry_status"] == "active" and row["registry_address_full"] and row["registry_geo_lng"] and row["registry_geo_lat"]
        ),
        "local_evidence_available_count": local_evidence_available_count,
        "remaining_source_fetch_count": remaining_source_fetch_count,
        "ready_for_registry_review_count": sum(
            1 for row in evidence_rows if row["local_evidence_status"] == "venue_registry_address_geo_available_needs_review"
        ),
        "status_counts": dict(sorted(status_counts.items())),
        "unique_city_count": len(city_counts),
        "top_city_counts": dict(city_counts.most_common(10)),
    }
    decision = (
        "weekly_current_missing_geo_local_evidence_packet_all_local_evidence_available_report_only"
        if evidence_rows and remaining_source_fetch_count == 0
        else "weekly_current_missing_geo_local_evidence_packet_partial_local_evidence_report_only"
        if local_evidence_available_count
        else "weekly_current_missing_geo_local_evidence_packet_no_local_evidence_report_only"
    )
    packet = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_local(),
        "decision": decision,
        "inputs": {
            "source_address_packet": display_path(source_address_packet_path),
            "source_address_packet_decision": source_address_packet.get("decision"),
            "candidate_jsonl": [display_path(path) for path in candidate_paths],
            "venue_registry": display_path(venue_registry_path),
            "venue_registry_updated_at": venue_registry.get("updated_at"),
            "venue_registry_count": len(venues),
        },
        "summary": summary,
        "blocking_reasons": [
            reason
            for reason, enabled in (
                ("remaining_source_address_fetch_required", remaining_source_fetch_count > 0),
                ("local_registry_evidence_requires_review", summary["ready_for_registry_review_count"] > 0),
                ("provider_or_coordinate_write_gate_not_ready", True),
            )
            if enabled
        ],
        "next_action": {
            "first_gate": "review_59_registry_backed_rows_against_current_event_city_and_source_anchor",
            "second_gate": "fetch_or_extract_source_address_for_12_remaining_rows",
            "third_gate": "provider_verification_or_coordinate_acceptance_gate_after_evidence_review",
            "fourth_gate": "explicit_coordinate_write_gate_with_lock_backup_transaction_readback",
            "rerun_after_gates": "npm run weekly:deploy-upload:preflight",
        },
        "local_evidence_rows": evidence_rows,
        "leak_findings": leak_findings({"local_evidence_rows": evidence_rows}),
        "safety": {
            "report_only": True,
            "article_fetch": False,
            "provider_or_geocode_call": False,
            "coordinate_write": False,
            "registry_mutation": False,
            "release_or_current_package_mutation": False,
            "db_graph_vector_write": False,
            "docker_or_worker_started": False,
            "openclaw_pipeline_run": False,
            "model_call": False,
            "deploy_upload_review": False,
            "secret_read": False,
            "broad_disk_scan": False,
        },
    }
    return packet


def render_markdown(packet: dict[str, Any]) -> str:
    summary = packet["summary"]
    lines = [
        "# Weekly Current Missing Geo Local Evidence Packet",
        "",
        f"- decision: `{packet['decision']}`",
        f"- source_address_packet: `{packet['inputs']['source_address_packet']}`",
        f"- venue_registry: `{packet['inputs']['venue_registry']}`",
        f"- source_address_task_count: `{summary['source_address_task_count']}`",
        f"- candidate_match_count: `{summary['candidate_match_count']}`",
        f"- candidate_address_count: `{summary['candidate_address_count']}`",
        f"- registry_single_match_count: `{summary['registry_single_match_count']}`",
        f"- registry_active_address_geo_count: `{summary['registry_active_address_geo_count']}`",
        f"- local_evidence_available_count: `{summary['local_evidence_available_count']}`",
        f"- remaining_source_fetch_count: `{summary['remaining_source_fetch_count']}`",
        f"- ready_for_registry_review_count: `{summary['ready_for_registry_review_count']}`",
        f"- leak_findings: `{len(packet['leak_findings'])}`",
        "",
        "## Status Counts",
        "",
    ]
    for key, value in summary["status_counts"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(
        [
            "",
            "## Next Gates",
            "",
            f"1. `{packet['next_action']['first_gate']}`",
            f"2. `{packet['next_action']['second_gate']}`",
            f"3. `{packet['next_action']['third_gate']}`",
            f"4. `{packet['next_action']['fourth_gate']}`",
            f"5. `{packet['next_action']['rerun_after_gates']}`",
            "",
            "## Sample Rows",
            "",
        ]
    )
    for row in packet["local_evidence_rows"][:20]:
        lines.append(
            "- "
            f"`{row['current_item_id']}` "
            f"status=`{row['local_evidence_status']}` "
            f"registry=`{row['registry_venue_id'] or '<none>'}` "
            f"source_fetch=`{row['needs_source_fetch']}`"
        )
    if len(packet["local_evidence_rows"]) > 20:
        lines.append(f"- ... `{len(packet['local_evidence_rows']) - 20}` more rows")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "Report-only. No article fetch, provider/geocode call, coordinate write, registry/current-release mutation, DB/vector/graph write, Docker/worker/OpenClaw run, deploy/upload/review, model call, secret read, or broad disk scan occurred.",
            "",
        ]
    )
    return "\n".join(lines)


def write_reports(packet: dict[str, Any], out_dir: Path, scorecard_path: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "weekly_current_missing_geo_local_evidence_packet.json"
    md_path = out_dir / "weekly_current_missing_geo_local_evidence_packet.md"
    rows_path = out_dir / "weekly_current_missing_geo_local_evidence_rows.jsonl"
    source_fetch_path = out_dir / "weekly_current_missing_geo_source_fetch_required_rows.jsonl"
    registry_review_path = out_dir / "weekly_current_missing_geo_registry_review_rows.jsonl"
    write_json(json_path, packet)
    md_text = render_markdown(packet)
    md_path.write_text(md_text, encoding="utf-8")
    scorecard_path.parent.mkdir(parents=True, exist_ok=True)
    scorecard_path.write_text(md_text, encoding="utf-8")
    rows = packet["local_evidence_rows"]
    write_jsonl(rows_path, rows)
    write_jsonl(source_fetch_path, [row for row in rows if row["needs_source_fetch"]])
    write_jsonl(registry_review_path, [row for row in rows if row["needs_registry_review"]])
    return {
        "json": json_path,
        "markdown": md_path,
        "rows": rows_path,
        "source_fetch": source_fetch_path,
        "registry_review": registry_review_path,
        "scorecard": scorecard_path,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-address-packet", type=Path, default=DEFAULT_SOURCE_ADDRESS_PACKET)
    parser.add_argument("--candidate-jsonl", type=Path, action="append", default=None)
    parser.add_argument("--venue-registry", type=Path, default=DEFAULT_VENUE_REGISTRY)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--json-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    candidate_paths = args.candidate_jsonl or DEFAULT_CANDIDATE_JSONL
    candidate_rows: list[dict[str, Any]] = []
    for path in candidate_paths:
        candidate_rows.extend(read_jsonl(path))
    packet = build_packet(
        source_address_packet=read_json(args.source_address_packet),
        candidate_rows=candidate_rows,
        venue_registry=read_json(args.venue_registry),
        source_address_packet_path=args.source_address_packet,
        candidate_paths=candidate_paths,
        venue_registry_path=args.venue_registry,
    )
    paths = write_reports(packet, args.out_dir, args.scorecard)
    if args.json_only:
        print(json.dumps(packet, ensure_ascii=False, sort_keys=True))
    else:
        summary = packet["summary"]
        print(f"decision={packet['decision']}")
        print(f"source_address_task_count={summary['source_address_task_count']}")
        print(f"candidate_match_count={summary['candidate_match_count']}")
        print(f"local_evidence_available_count={summary['local_evidence_available_count']}")
        print(f"remaining_source_fetch_count={summary['remaining_source_fetch_count']}")
        print(f"json={paths['json']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
