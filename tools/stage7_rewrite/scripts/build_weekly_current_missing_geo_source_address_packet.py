#!/usr/bin/env python3
"""Build a no-write source-address queue for current weekly missing-geo rows.

This packet maps current missing-geo source-address tasks to the current release
package and its source_url_map. It produces source anchors for a future layered
Docker worker. It does not fetch articles, call map providers, call models,
start workers, write coordinates, mutate databases/releases/registries, deploy,
upload, submit review, read secrets, or scan broad disks.
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

SCHEMA_VERSION = "weekly_current_missing_geo_source_address_packet.v1"
DEFAULT_CURRENT_RELEASE = REPO_ROOT / "services" / "weekly_activity_cloudrun" / "data" / "current_release" / "current.json"
DEFAULT_SOURCE_URL_MAP = (
    REPO_ROOT
    / "services"
    / "weekly_activity_cloudrun"
    / "data"
    / "current_release"
    / "source_actions"
    / "source_url_map.json"
)
DEFAULT_CURRENT_MISSING_GEO_TASKS = (
    REPORTS_ROOT
    / "weekly_current_missing_geo_repair_packet_20260603"
    / "weekly_current_missing_geo_repair_tasks.jsonl"
)
DEFAULT_OUT_DIR = REPORTS_ROOT / "weekly_current_missing_geo_source_address_packet_20260603"
DEFAULT_SCORECARD = REPORTS_MD_ROOT / "WEEKLY_CURRENT_MISSING_GEO_SOURCE_ADDRESS_PACKET_20260603.md"

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
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        value = json.loads(text)
        if isinstance(value, dict):
            rows.append(value)
    return rows


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


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


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


def rows(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = payload.get(key)
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, dict)]


def item_id_candidates(item: dict[str, Any]) -> list[str]:
    candidates = [
        first(item.get("id")),
        first(item.get("event_id")),
        first(item.get("article_id")),
        first(item.get("queue_id")),
    ]
    source = as_dict(item.get("source_article"))
    source_action = as_dict(item.get("source_action"))
    for url_hash in (first(source.get("url_hash")), first(source_action.get("url_hash"))):
        if url_hash:
            candidates.append(url_hash)
            account = first(item.get("account"), item.get("account_key"), item.get("source_account_name"))
            if account:
                candidates.append(f"{account}:{url_hash}")
    unique: list[str] = []
    for candidate in candidates:
        if candidate and candidate not in unique:
            unique.append(candidate)
    return unique


def index_current_items(current_release: dict[str, Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for item in rows(current_release, "items"):
        for candidate in item_id_candidates(item):
            index.setdefault(candidate, item)
    return index


def source_map_sources(source_url_map: dict[str, Any]) -> dict[str, dict[str, Any]]:
    sources = source_url_map.get("sources")
    if not isinstance(sources, dict):
        return {}
    return {str(key): value for key, value in sources.items() if isinstance(value, dict)}


def suffix_hash(value: str) -> str:
    text = value.strip()
    if ":" in text:
        return text.rsplit(":", 1)[-1].strip()
    return text


def extract_url_hash(item: dict[str, Any], task_item: dict[str, Any]) -> str:
    source = as_dict(item.get("source_article"))
    source_action = as_dict(item.get("source_action"))
    return first(
        source.get("url_hash"),
        source_action.get("url_hash"),
        suffix_hash(first(item.get("id"))),
        suffix_hash(first(item.get("event_id"))),
        suffix_hash(first(task_item.get("id"))),
    )


def current_task_item(task: dict[str, Any]) -> dict[str, Any]:
    return as_dict(task.get("current_item"))


def match_current_item(task: dict[str, Any], current_index: dict[str, dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    task_item = current_task_item(task)
    for candidate in item_id_candidates(task_item):
        if candidate in current_index:
            return candidate, current_index[candidate]
    task_id = first(task_item.get("id"), task.get("event_id"), task.get("task_id"))
    if task_id in current_index:
        return task_id, current_index[task_id]
    hash_id = suffix_hash(task_id)
    if hash_id in current_index:
        return hash_id, current_index[hash_id]
    return "", {}


def build_source_row(
    *,
    task: dict[str, Any],
    current_index: dict[str, dict[str, Any]],
    sources: dict[str, dict[str, Any]],
    index: int,
) -> dict[str, Any]:
    task_item = current_task_item(task)
    matched_key, current_item = match_current_item(task, current_index)
    url_hash = extract_url_hash(current_item, task_item)
    source = sources.get(url_hash, {})
    source_url = first(source.get("url"))
    source_article = as_dict(current_item.get("source_article"))
    source_action = as_dict(current_item.get("source_action"))
    source_account_name = first(
        current_item.get("source_account_name"),
        source_article.get("account_name"),
        source.get("account_name"),
        current_item.get("account"),
        current_item.get("account_key"),
    )
    source_published_at = first(
        current_item.get("source_published_at"),
        source_article.get("published_at"),
        source.get("published_at"),
        current_item.get("post_date"),
    )
    address = first(task_item.get("address"), current_item.get("address"), current_item.get("address_full"))
    source_anchor_present = bool(source_url or source_account_name or url_hash)
    return {
        "schema_version": SCHEMA_VERSION,
        "row_id": f"source_address:{index:03d}:{first(task_item.get('id'), task.get('task_id'), 'missing-id')}",
        "source_task_id": first(task.get("task_id")),
        "source_task_status": first(task.get("status")),
        "current_item_match_status": "matched" if current_item else "unmatched",
        "current_item_match_key": matched_key,
        "current_item_id": first(task_item.get("id"), current_item.get("id")),
        "event_id": first(current_item.get("event_id"), task_item.get("id")),
        "title": first(current_item.get("title_display"), current_item.get("title"), task_item.get("title")),
        "city": first(current_item.get("city_name"), current_item.get("city"), current_item.get("city_key"), task_item.get("city")),
        "venue_name": first(current_item.get("venue_name"), current_item.get("venue"), task_item.get("venue_name")),
        "venue_group_id": first(task.get("venue_group_id")),
        "url_hash": url_hash,
        "source_url": source_url,
        "source_type": first(source.get("type"), source_action.get("type")),
        "source_account_name": source_account_name,
        "source_published_at": source_published_at,
        "source_action_available": source_action.get("available") is True,
        "source_anchor_present": source_anchor_present,
        "address_present_in_current": bool(address),
        "cover_url_present": bool(first(current_item.get("cover_url"), current_item.get("cover_image_url"))),
        "poster_file_id_present": bool(first(current_item.get("poster_file_id"))),
        "poster_source": first(current_item.get("poster_source")),
        "required_evidence": [
            "recover_address_from_current_article_or_verified_official_venue_source",
            "preserve_source_url_hash_and_source_ref",
            "address_evidence_must_match_current_city_and_venue_anchor",
            "do_not_geocode_without_address_or_poi_evidence",
            "explicit_coordinate_write_gate_required_after_address_evidence",
        ],
        "provider_or_geocode_call_allowed_now": False,
        "coordinate_write_allowed_now": False,
        "docker_worker_allowed_now": False,
        "db_registry_mutation_allowed_now": False,
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
    current_release: dict[str, Any],
    source_url_map: dict[str, Any],
    current_missing_geo_tasks: list[dict[str, Any]],
    current_release_path: Path,
    source_url_map_path: Path,
    current_missing_geo_tasks_path: Path,
) -> dict[str, Any]:
    current_index = index_current_items(current_release)
    sources = source_map_sources(source_url_map)
    source_tasks = [
        task
        for task in current_missing_geo_tasks
        if first(task.get("task_type")) == "current_item_source_address_acquisition"
    ]
    skipped_task_count = len(current_missing_geo_tasks) - len(source_tasks)
    source_rows = [
        build_source_row(task=task, current_index=current_index, sources=sources, index=index)
        for index, task in enumerate(source_tasks, start=1)
    ]
    city_counts = Counter(first(row.get("city")) or "unknown_city" for row in source_rows)
    source_url_count = sum(1 for row in source_rows if row["source_url"])
    source_anchor_count = sum(1 for row in source_rows if row["source_anchor_present"])
    current_item_match_count = sum(1 for row in source_rows if row["current_item_match_status"] == "matched")
    unmatched_task_count = len(source_rows) - current_item_match_count
    missing_source_url_count = len(source_rows) - source_url_count
    source_url_map_match_count = sum(1 for row in source_rows if row["url_hash"] in sources)
    blocking_reasons = [
        reason
        for reason, enabled in (
            ("source_address_evidence_not_acquired", bool(source_rows)),
            ("current_item_source_anchor_unmatched", unmatched_task_count > 0),
            ("source_url_anchor_missing", missing_source_url_count > 0),
            ("coordinate_write_gate_not_ready", True),
        )
        if enabled
    ]
    if not source_rows:
        decision = "weekly_current_missing_geo_source_address_packet_no_source_tasks_report_only"
    elif unmatched_task_count or missing_source_url_count:
        decision = "weekly_current_missing_geo_source_address_packet_incomplete_anchors_report_only"
    else:
        decision = "weekly_current_missing_geo_source_address_packet_ready_report_only_no_execution"
    packet = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_local(),
        "decision": decision,
        "inputs": {
            "current_release": display_path(current_release_path),
            "current_release_generated_at": current_release.get("generated_at"),
            "current_release_item_count": current_release.get("item_count", len(rows(current_release, "items"))),
            "source_url_map": display_path(source_url_map_path),
            "source_url_map_generated_at": source_url_map.get("generated_at"),
            "source_url_map_source_count": source_url_map.get("source_count", len(sources)),
            "current_missing_geo_tasks": display_path(current_missing_geo_tasks_path),
            "current_missing_geo_task_count": len(current_missing_geo_tasks),
        },
        "summary": {
            "source_address_task_count": len(source_rows),
            "skipped_non_source_task_count": skipped_task_count,
            "current_item_match_count": current_item_match_count,
            "unmatched_task_count": unmatched_task_count,
            "source_url_map_match_count": source_url_map_match_count,
            "source_url_count": source_url_count,
            "missing_source_url_count": missing_source_url_count,
            "source_anchor_count": source_anchor_count,
            "address_present_in_current_count": sum(1 for row in source_rows if row["address_present_in_current"]),
            "cover_url_present_count": sum(1 for row in source_rows if row["cover_url_present"]),
            "poster_file_id_present_count": sum(1 for row in source_rows if row["poster_file_id_present"]),
            "source_action_available_count": sum(1 for row in source_rows if row["source_action_available"]),
            "unique_city_count": len(city_counts),
            "top_city_counts": dict(city_counts.most_common(10)),
        },
        "blocking_reasons": blocking_reasons,
        "next_action": {
            "first_gate": "source_address_evidence_worker_design_or_fixture",
            "second_gate": "layered_docker_source_evidence_worker_release",
            "third_gate": "source_address_evidence_review_acceptance",
            "fourth_gate": "provider_verification_after_address_evidence",
            "fifth_gate": "explicit_coordinate_write_gate_with_lock_backup_transaction_readback",
            "rerun_after_gates": "npm run weekly:deploy-upload:preflight",
        },
        "source_address_rows": source_rows,
        "leak_findings": leak_findings({"source_address_rows": source_rows}),
        "safety": {
            "report_only": True,
            "article_fetch": False,
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
    return packet


def render_markdown(packet: dict[str, Any]) -> str:
    summary = packet["summary"]
    rows_out = packet["source_address_rows"]
    lines = [
        "# Weekly Current Missing Geo Source Address Packet",
        "",
        f"- decision: `{packet['decision']}`",
        f"- current_release: `{packet['inputs']['current_release']}`",
        f"- source_url_map: `{packet['inputs']['source_url_map']}`",
        f"- current_missing_geo_tasks: `{packet['inputs']['current_missing_geo_tasks']}`",
        f"- source_address_task_count: `{summary['source_address_task_count']}`",
        f"- skipped_non_source_task_count: `{summary['skipped_non_source_task_count']}`",
        f"- current_item_match_count: `{summary['current_item_match_count']}`",
        f"- unmatched_task_count: `{summary['unmatched_task_count']}`",
        f"- source_url_count: `{summary['source_url_count']}`",
        f"- missing_source_url_count: `{summary['missing_source_url_count']}`",
        f"- source_anchor_count: `{summary['source_anchor_count']}`",
        f"- cover_url_present_count: `{summary['cover_url_present_count']}`",
        f"- poster_file_id_present_count: `{summary['poster_file_id_present_count']}`",
        f"- leak_findings: `{len(packet['leak_findings'])}`",
        "",
        "## Next Gates",
        "",
        f"1. `{packet['next_action']['first_gate']}`",
        f"2. `{packet['next_action']['second_gate']}`",
        f"3. `{packet['next_action']['third_gate']}`",
        f"4. `{packet['next_action']['fourth_gate']}`",
        f"5. `{packet['next_action']['fifth_gate']}`",
        f"6. `{packet['next_action']['rerun_after_gates']}`",
        "",
        "## Sample Rows",
        "",
    ]
    for row in rows_out[:20]:
        lines.append(
            "- "
            f"`{row['current_item_id']}` "
            f"city=`{row['city']}` "
            f"venue=`{row['venue_name']}` "
            f"source_account=`{row['source_account_name']}` "
            f"published_at=`{row['source_published_at']}` "
            f"source_url_present=`{bool(row['source_url'])}`"
        )
    if len(rows_out) > 20:
        lines.append(f"- ... `{len(rows_out) - 20}` more rows")
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
    json_path = out_dir / "weekly_current_missing_geo_source_address_packet.json"
    md_path = out_dir / "weekly_current_missing_geo_source_address_packet.md"
    tasks_path = out_dir / "weekly_current_missing_geo_source_address_tasks.jsonl"
    write_json(json_path, packet)
    md_text = render_markdown(packet)
    md_path.write_text(md_text, encoding="utf-8")
    scorecard_path.parent.mkdir(parents=True, exist_ok=True)
    scorecard_path.write_text(md_text, encoding="utf-8")
    write_jsonl(tasks_path, packet["source_address_rows"])
    return {"json": json_path, "markdown": md_path, "tasks": tasks_path, "scorecard": scorecard_path}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current-release", type=Path, default=DEFAULT_CURRENT_RELEASE)
    parser.add_argument("--source-url-map", type=Path, default=DEFAULT_SOURCE_URL_MAP)
    parser.add_argument("--current-missing-geo-tasks", type=Path, default=DEFAULT_CURRENT_MISSING_GEO_TASKS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--json-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    packet = build_packet(
        current_release=read_json(args.current_release),
        source_url_map=read_json(args.source_url_map),
        current_missing_geo_tasks=read_jsonl(args.current_missing_geo_tasks),
        current_release_path=args.current_release,
        source_url_map_path=args.source_url_map,
        current_missing_geo_tasks_path=args.current_missing_geo_tasks,
    )
    paths = write_reports(packet, args.out_dir, args.scorecard)
    if args.json_only:
        print(json.dumps(packet, ensure_ascii=False, sort_keys=True))
    else:
        summary = packet["summary"]
        print(f"decision={packet['decision']}")
        print(f"source_address_task_count={summary['source_address_task_count']}")
        print(f"current_item_match_count={summary['current_item_match_count']}")
        print(f"source_url_count={summary['source_url_count']}")
        print(f"missing_source_url_count={summary['missing_source_url_count']}")
        print(f"json={paths['json']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
