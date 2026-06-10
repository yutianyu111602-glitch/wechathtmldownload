#!/usr/bin/env python3
"""Build a no-write repair packet for current weekly items missing geo.

This packet is a control-plane artifact. It turns the deploy-upload
``current_missing_geo`` rows into explicit per-current-item tasks and venue
groups. It does not call map providers, start workers, write coordinates,
mutate registry/current-release data, deploy, upload, submit review, read
secrets, or call models.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
REPORTS_ROOT = REPO_ROOT / "tools" / "stage7_rewrite" / "reports"
REPORTS_MD_ROOT = REPO_ROOT / "reports"

SCHEMA_VERSION = "weekly_current_missing_geo_repair_packet.v1"
DEFAULT_COORDINATE_FRESHNESS = (
    REPORTS_ROOT
    / "weekly_deploy_upload_preflight_20260531"
    / "coordinate_freshness_latest_claim"
    / "weekly_coordinate_freshness_queue.json"
)
DEFAULT_OUT_DIR = REPORTS_ROOT / "weekly_current_missing_geo_repair_packet_20260603"
DEFAULT_SCORECARD = REPORTS_MD_ROOT / "WEEKLY_CURRENT_MISSING_GEO_REPAIR_PACKET_20260603.md"

RAW_URL_RE = re.compile(r"https?://", re.IGNORECASE)
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


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, payload: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in payload)
    path.write_text(text + ("\n" if text else ""), encoding="utf-8")


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
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


def int_value(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def rows(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = payload.get(key)
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, dict)]


def normalized_group_key(row: dict[str, Any]) -> str:
    city = first(row.get("city"), row.get("city_key")) or "unknown_city"
    venue = first(row.get("venue_name"), row.get("venue"), row.get("venue_id")) or "unknown_venue"
    return f"{city}|{venue}".lower()


def task_type_for(row: dict[str, Any]) -> str:
    if first(row.get("address"), row.get("address_full")):
        return "current_item_address_provider_verification"
    return "current_item_source_address_acquisition"


def task_status_for(task_type: str) -> str:
    if task_type == "current_item_address_provider_verification":
        return "blocked_pending_provider_verification_release"
    return "blocked_pending_source_address_evidence"


def requirements_for(task_type: str) -> list[str]:
    common = [
        "current_event_identity_preserved",
        "venue_identity_or_registry_mapping_reviewed",
        "no_empty_coordinate_overwrite",
        "no_secret_value_written_to_reports",
        "explicit_coordinate_write_gate_required",
    ]
    if task_type == "current_item_address_provider_verification":
        return [
            "address_source_bound_to_current_event_or_verified_official_source",
            "forward_geocode_same_city",
            "reverse_geocode_same_place_or_same_street_address",
            "provider_result_retains_source_ref",
            *common,
        ]
    return [
        "recover_address_from_current_source_or_official_venue_source",
        "do_not_geocode_without_address_or_poi_evidence",
        "source_evidence_contains_city_and_venue_anchor",
        *common,
    ]


def compact_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": first(row.get("id"), row.get("event_id")),
        "venue_id": first(row.get("venue_id")),
        "venue_name": first(row.get("venue_name"), row.get("venue")),
        "city": first(row.get("city"), row.get("city_key")),
        "address": first(row.get("address"), row.get("address_full")),
        "title": first(row.get("title")),
        "geo_lng": row.get("geo_lng"),
        "geo_lat": row.get("geo_lat"),
        "geo_source": first(row.get("geo_source"), row.get("geo_provider")),
        "geo_verified_at": first(row.get("geo_verified_at")),
    }


def build_task(row: dict[str, Any], index: int, venue_group_id: str, group_size: int) -> dict[str, Any]:
    item = compact_row(row)
    task_type = task_type_for(item)
    return {
        "schema_version": SCHEMA_VERSION,
        "task_id": f"current_missing_geo:{index:03d}:{item['id'] or 'missing-id'}",
        "task_type": task_type,
        "status": task_status_for(task_type),
        "current_item": item,
        "venue_group_id": venue_group_id,
        "venue_group_size": group_size,
        "has_address": bool(item["address"]),
        "has_venue_id": bool(item["venue_id"]),
        "coordinate_write_allowed_now": False,
        "provider_or_geocode_call_allowed_now": False,
        "db_registry_mutation_allowed_now": False,
        "docker_worker_allowed_now": False,
        "requirements_before_any_coordinate_write": requirements_for(task_type),
        "next_worker_contract": {
            "mode": "report_only_until_explicit_controller_release",
            "preferred_runtime": "layered_docker_worker",
            "skill_role": "thin_control_plane_only",
        },
    }


def build_venue_groups(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for task in tasks:
        grouped[str(task["venue_group_id"])].append(task)

    groups: list[dict[str, Any]] = []
    for group_id, group_tasks in sorted(grouped.items()):
        first_item = group_tasks[0]["current_item"]
        task_types = Counter(str(task["task_type"]) for task in group_tasks)
        groups.append(
            {
                "venue_group_id": group_id,
                "city": first_item["city"],
                "venue_name": first_item["venue_name"],
                "venue_id_values": sorted(
                    {task["current_item"]["venue_id"] for task in group_tasks if task["current_item"]["venue_id"]}
                ),
                "current_item_count": len(group_tasks),
                "with_address_count": sum(1 for task in group_tasks if task["has_address"]),
                "without_address_count": sum(1 for task in group_tasks if not task["has_address"]),
                "task_type_counts": dict(sorted(task_types.items())),
                "sample_current_item_ids": [task["current_item"]["id"] for task in group_tasks[:8]],
                "group_status": (
                    "blocked_pending_source_address_evidence"
                    if any(task["task_type"] == "current_item_source_address_acquisition" for task in group_tasks)
                    else "blocked_pending_provider_verification_release"
                ),
            }
        )
    return groups


def leak_findings(payload: Any) -> list[dict[str, Any]]:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    findings: list[dict[str, Any]] = []
    for label, pattern in (
        ("raw_url", RAW_URL_RE),
        ("private_path", PRIVATE_PATH_RE),
        ("secret_like", SECRET_RE),
    ):
        matches = pattern.findall(text)
        if matches:
            findings.append({"type": label, "count": len(matches)})
    return findings


def build_packet(*, coordinate_freshness: dict[str, Any], coordinate_freshness_path: Path) -> dict[str, Any]:
    freshness_summary = (
        coordinate_freshness.get("summary", {})
        if isinstance(coordinate_freshness.get("summary"), dict)
        else {}
    )
    missing_rows = rows(coordinate_freshness, "current_missing_geo")
    group_sizes = Counter(normalized_group_key(row) for row in missing_rows)
    tasks = [
        build_task(row, index, normalized_group_key(row), group_sizes[normalized_group_key(row)])
        for index, row in enumerate(missing_rows, start=1)
    ]
    groups = build_venue_groups(tasks)
    task_types = Counter(str(task["task_type"]) for task in tasks)
    city_counts = Counter(str(task["current_item"]["city"]) for task in tasks)
    has_address_count = sum(1 for task in tasks if task["has_address"])
    has_venue_id_count = sum(1 for task in tasks if task["has_venue_id"])
    task_leak_findings = leak_findings({"tasks": tasks, "venue_groups": groups})
    safe_to_claim = coordinate_freshness.get("safe_to_claim_all_latest") is True
    write_gate_ready = safe_to_claim and not tasks
    decision = (
        "weekly_current_missing_geo_repair_packet_no_current_missing_geo_report_only"
        if not tasks and safe_to_claim
        else "weekly_current_missing_geo_repair_packet_blocked_report_only"
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_local(),
        "decision": decision,
        "coordinate_freshness_input": display_path(coordinate_freshness_path),
        "coordinate_freshness_decision": coordinate_freshness.get("decision"),
        "safe_to_claim_all_latest": safe_to_claim,
        "write_gate_ready": write_gate_ready,
        "coordinate_write_allowed": False,
        "provider_or_geocode_call_performed": False,
        "docker_or_worker_started": False,
        "summary": {
            "current_items": int_value(freshness_summary.get("current_items"), len(missing_rows)),
            "current_items_missing_geo": int_value(freshness_summary.get("current_items_missing_geo"), len(missing_rows)),
            "task_count": len(tasks),
            "venue_group_count": len(groups),
            "with_address_count": has_address_count,
            "without_address_count": len(tasks) - has_address_count,
            "with_venue_id_count": has_venue_id_count,
            "without_venue_id_count": len(tasks) - has_venue_id_count,
            "unique_city_count": len(city_counts),
            "task_type_counts": dict(sorted(task_types.items())),
            "top_city_counts": dict(city_counts.most_common(10)),
        },
        "blocking_reasons": [
            reason
            for reason, enabled in (
                ("coordinate_latest_claim_not_proven", not safe_to_claim),
                ("current_missing_geo_present", bool(tasks)),
                ("current_missing_geo_repair_tasks_pending", bool(tasks)),
                ("coordinate_write_gate_not_ready", not write_gate_ready),
            )
            if enabled
        ],
        "next_action": {
            "first_gate": "source_address_evidence_for_rows_without_address",
            "second_gate": "provider_verification_for_rows_with_address_or_recovered_address",
            "third_gate": "explicit_coordinate_write_gate_with_lock_backup_transaction_readback",
            "rerun_after_gates": "npm run weekly:deploy-upload:preflight",
        },
        "venue_groups": groups,
        "tasks": tasks,
        "leak_findings": task_leak_findings,
        "safety": {
            "report_only": True,
            "provider_or_geocode_call": False,
            "coordinate_write": False,
            "registry_or_release_mutation": False,
            "db_graph_vector_write": False,
            "docker_or_worker_started": False,
            "openclaw_pipeline_run": False,
            "model_call": False,
            "deploy_upload_review": False,
            "secret_read": False,
            "broad_disk_scan": False,
        },
    }


def render_markdown(packet: dict[str, Any]) -> str:
    summary = packet["summary"]
    task_type_counts = ", ".join(f"{key}={value}" for key, value in summary["task_type_counts"].items())
    lines = [
        "# Weekly Current Missing Geo Repair Packet",
        "",
        f"- decision: `{packet['decision']}`",
        f"- coordinate_freshness_input: `{packet['coordinate_freshness_input']}`",
        f"- coordinate_freshness_decision: `{packet['coordinate_freshness_decision']}`",
        f"- safe_to_claim_all_latest: `{packet['safe_to_claim_all_latest']}`",
        f"- current_items: `{summary['current_items']}`",
        f"- current_items_missing_geo: `{summary['current_items_missing_geo']}`",
        f"- task_count: `{summary['task_count']}`",
        f"- venue_group_count: `{summary['venue_group_count']}`",
        f"- with_address_count: `{summary['with_address_count']}`",
        f"- without_address_count: `{summary['without_address_count']}`",
        f"- with_venue_id_count: `{summary['with_venue_id_count']}`",
        f"- task_type_counts: `{task_type_counts or '<none>'}`",
        f"- coordinate_write_allowed: `{packet['coordinate_write_allowed']}`",
        f"- provider_or_geocode_call_performed: `{packet['provider_or_geocode_call_performed']}`",
        f"- docker_or_worker_started: `{packet['docker_or_worker_started']}`",
        f"- leak_findings: `{len(packet['leak_findings'])}`",
        "",
        "## Next Gates",
        "",
        f"1. `{packet['next_action']['first_gate']}`",
        f"2. `{packet['next_action']['second_gate']}`",
        f"3. `{packet['next_action']['third_gate']}`",
        f"4. `{packet['next_action']['rerun_after_gates']}`",
        "",
        "## Venue Groups",
        "",
    ]
    for group in packet["venue_groups"][:20]:
        lines.append(
            "- "
            f"`{group['venue_group_id']}` "
            f"items=`{group['current_item_count']}` "
            f"with_address=`{group['with_address_count']}` "
            f"without_address=`{group['without_address_count']}` "
            f"status=`{group['group_status']}`"
        )
    if len(packet["venue_groups"]) > 20:
        lines.append(f"- ... `{len(packet['venue_groups']) - 20}` more groups")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "Report-only. No provider/geocode call, coordinate write, registry/current-release mutation, DB/vector/graph write, Docker/worker/OpenClaw run, deploy/upload/review, model call, secret read, or broad disk scan occurred.",
            "",
        ]
    )
    return "\n".join(lines)


def write_reports(packet: dict[str, Any], out_dir: Path, scorecard_path: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "weekly_current_missing_geo_repair_packet.json"
    md_path = out_dir / "weekly_current_missing_geo_repair_packet.md"
    tasks_path = out_dir / "weekly_current_missing_geo_repair_tasks.jsonl"
    groups_path = out_dir / "weekly_current_missing_geo_venue_groups.jsonl"
    write_json(json_path, packet)
    md_text = render_markdown(packet)
    md_path.write_text(md_text, encoding="utf-8")
    scorecard_path.parent.mkdir(parents=True, exist_ok=True)
    scorecard_path.write_text(md_text, encoding="utf-8")
    write_jsonl(tasks_path, packet["tasks"])
    write_jsonl(groups_path, packet["venue_groups"])
    return {"json": json_path, "markdown": md_path, "tasks": tasks_path, "venue_groups": groups_path, "scorecard": scorecard_path}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coordinate-freshness", type=Path, default=DEFAULT_COORDINATE_FRESHNESS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--json-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    packet = build_packet(coordinate_freshness=read_json(args.coordinate_freshness), coordinate_freshness_path=args.coordinate_freshness)
    paths = write_reports(packet, args.out_dir, args.scorecard)
    if args.json_only:
        print(json.dumps(packet, ensure_ascii=False, sort_keys=True))
    else:
        summary = packet["summary"]
        print(f"decision={packet['decision']}")
        print(f"task_count={summary['task_count']}")
        print(f"venue_group_count={summary['venue_group_count']}")
        print(f"with_address_count={summary['with_address_count']}")
        print(f"without_address_count={summary['without_address_count']}")
        print(f"json={paths['json']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
