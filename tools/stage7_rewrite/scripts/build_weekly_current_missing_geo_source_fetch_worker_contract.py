#!/usr/bin/env python3
"""Build a no-execution Docker worker contract for missing-geo source fetch.

This consumes the source-fetch slice from the current missing-geo evidence
acceptance packet. It emits deterministic worker tasks and account batches for
the layered OpenClaw/Docker runtime, but it does not start Docker, fetch network
content, call models/providers, write coordinates, mutate packages/databases, or
read secrets.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
REPORTS_ROOT = REPO_ROOT / "tools" / "stage7_rewrite" / "reports"
REPORTS_MD_ROOT = REPO_ROOT / "reports"

SCHEMA_VERSION = "weekly_current_missing_geo_source_fetch_worker_contract.v1"
DEFAULT_SOURCE_FETCH_ROWS = (
    REPORTS_ROOT
    / "weekly_current_missing_geo_evidence_acceptance_packet_20260603"
    / "weekly_current_missing_geo_source_fetch_acceptance_rows.jsonl"
)
DEFAULT_OUT_DIR = REPORTS_ROOT / "weekly_current_missing_geo_source_fetch_worker_contract_20260603"
DEFAULT_SCORECARD = REPORTS_MD_ROOT / "WEEKLY_CURRENT_MISSING_GEO_SOURCE_FETCH_WORKER_CONTRACT_20260603.md"

QUEUE_NAME = "weekly_current_missing_geo_source_fetch_20260603"
DOCKER_PROFILE = "openclaw-source-queue-cache"
DOCKER_SERVICE = "openclaw-source-queue-cache"
WORKER_LAYER = "L2_SOURCE_EVIDENCE_FETCH"
OPENCLAW_QUEUE_NAME = "openclaw.source_queue_cache"
COMPOSE_PATH = "tools/stage7_rewrite/docker/openclaw-weekly/docker-compose.openclaw-weekly.yml"

PRIVATE_PATH_RE = re.compile(r"(?:[A-Za-z]:\\|/mnt/[a-z]/|/home/pc/|\\\\)", re.IGNORECASE)
SECRET_RE = re.compile(
    r"(?:bearer\s+[a-z0-9._~+/=-]+|sk-[a-z0-9]{12,}|x-auth-key\s*[:=]|"
    r"cookie_value|token_value|password\s*[:=]|authorization\s*[:=]|sessionid=|api[_-]?key\s*[:=])",
    re.IGNORECASE,
)


def now_local() -> str:
    return datetime.now(timezone.utc).astimezone().replace(microsecond=0).isoformat()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        text = line.strip()
        if not text:
            continue
        value = json.loads(text)
        if isinstance(value, dict):
            value["_input_path"] = display_path(path)
            value["_input_line"] = line_number
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


def stable_hash(*values: Any, length: int = 16) -> str:
    text = "|".join(first(value) for value in values)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]


def required_input_checks(row: dict[str, Any]) -> dict[str, bool]:
    return {
        "acceptance_lane_is_source_fetch": first(row.get("acceptance_lane")) == "source_fetch",
        "current_item_id_present": bool(first(row.get("current_item_id"))),
        "event_id_present": bool(first(row.get("event_id"))),
        "title_present": bool(first(row.get("title"))),
        "city_present": bool(first(row.get("city"))),
        "venue_name_present": bool(first(row.get("venue_name"))),
        "source_url_present": first(row.get("source_url")).startswith("https://mp.weixin.qq.com/"),
        "source_account_name_present": bool(first(row.get("source_account_name"))),
        "local_evidence_status_expected": first(row.get("local_evidence_status")) == "needs_source_address_fetch",
        "no_address_yet": not bool(first(row.get("address"))),
        "existing_contract_disallows_source_fetch_now": row.get("source_fetch_allowed_now") is False,
        "existing_contract_disallows_docker_now": row.get("docker_worker_allowed_now") is False,
        "existing_contract_disallows_coordinate_write_now": row.get("coordinate_write_allowed_now") is False,
    }


def missing_checks(checks: dict[str, bool]) -> list[str]:
    return [key for key, value in checks.items() if not value]


def build_worker_task(row: dict[str, Any], index: int) -> dict[str, Any]:
    checks = required_input_checks(row)
    missing = missing_checks(checks)
    current_item_id = first(row.get("current_item_id"))
    source_url = first(row.get("source_url"))
    task_hash = stable_hash(current_item_id, source_url)
    return {
        "schema_version": SCHEMA_VERSION,
        "task_id": f"source_fetch_worker:{index:03d}:{task_hash}",
        "source_acceptance_row_id": first(row.get("row_id")),
        "local_evidence_row_id": first(row.get("local_evidence_row_id")),
        "current_item_id": current_item_id,
        "event_id": first(row.get("event_id")),
        "title": first(row.get("title")),
        "city": first(row.get("city")),
        "venue_name": first(row.get("venue_name")),
        "source_url": source_url,
        "source_account_name": first(row.get("source_account_name")),
        "worker_layer": WORKER_LAYER,
        "docker_profile": DOCKER_PROFILE,
        "docker_service": DOCKER_SERVICE,
        "docker_compose_path": COMPOSE_PATH,
        "queue_name": QUEUE_NAME,
        "openclaw_queue_name": OPENCLAW_QUEUE_NAME,
        "lease_key": f"source_fetch:{current_item_id or task_hash}",
        "idempotency_key": f"source_fetch:{task_hash}",
        "required_input_checks": checks,
        "missing_required_input_checks": missing,
        "worker_task_status": "ready_for_controller_release" if not missing else "blocked_missing_required_input",
        "required_worker_outputs": [
            "source_fetch_result_id",
            "source_url",
            "source_account_name",
            "source_url_sha256",
            "fetched_at",
            "source_published_at_if_available",
            "address_or_poi_evidence",
            "source_text_excerpt_ref",
            "evidence_confidence",
            "needs_provider_verification",
            "no_coordinate_write",
        ],
        "forbidden_worker_outputs": [
            "raw_secret",
            "cookie",
            "token",
            "credential",
            "coordinate_write",
            "current_package_mutation",
            "registry_mutation",
            "cloudbase_upload",
            "formal_review_release",
        ],
        "next_gate_after_worker": "source_fetch_result_acceptance_packet_before_provider_or_coordinate_write",
        "docker_worker_allowed_now": False,
        "network_fetch_allowed_now": False,
        "deepseek_or_model_call_allowed_now": False,
        "provider_or_geocode_call_allowed_now": False,
        "coordinate_write_allowed_now": False,
        "registry_mutation_allowed_now": False,
        "current_package_mutation_allowed_now": False,
        "db_graph_vector_write_allowed_now": False,
        "deploy_upload_review_allowed_now": False,
    }


def build_account_batches(worker_tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for task in worker_tasks:
        grouped[first(task.get("source_account_name"), "unknown_source_account")].append(task)

    batches: list[dict[str, Any]] = []
    for index, (account_name, tasks) in enumerate(sorted(grouped.items()), start=1):
        city_counts = Counter(first(task.get("city")) or "unknown_city" for task in tasks)
        batches.append(
            {
                "schema_version": SCHEMA_VERSION,
                "batch_id": f"source_fetch_account_batch:{index:03d}:{stable_hash(account_name, length=12)}",
                "source_account_name": account_name,
                "worker_layer": WORKER_LAYER,
                "docker_profile": DOCKER_PROFILE,
                "docker_service": DOCKER_SERVICE,
                "queue_name": QUEUE_NAME,
                "task_count": len(tasks),
                "city_counts": dict(city_counts.most_common(20)),
                "sample_current_item_ids": [task["current_item_id"] for task in tasks[:8]],
                "sample_source_urls": [task["source_url"] for task in tasks[:5]],
                "ready_for_controller_release_count": sum(
                    1 for task in tasks if task["worker_task_status"] == "ready_for_controller_release"
                ),
                "blocked_missing_required_input_count": sum(
                    1 for task in tasks if task["worker_task_status"] == "blocked_missing_required_input"
                ),
                "docker_worker_allowed_now": False,
                "network_fetch_allowed_now": False,
                "coordinate_write_allowed_now": False,
            }
        )
    return batches


def release_blockers() -> list[dict[str, Any]]:
    return [
        {
            "blocker_id": "explicit_controller_source_fetch_release_missing",
            "required_to_clear": "controller signs a source-fetch runtime release artifact for this queue",
        },
        {
            "blocker_id": "docker_runtime_release_artifact_missing",
            "required_to_clear": "OpenClaw/Docker profile release artifact names the exact profile, queue, and input packet",
        },
        {
            "blocker_id": "network_fetch_release_missing",
            "required_to_clear": "runtime policy explicitly allows bounded public source fetch for these 12 URLs",
        },
        {
            "blocker_id": "source_fetch_result_acceptance_packet_missing",
            "required_to_clear": "worker results are returned to an acceptance packet before provider or coordinate gates",
        },
        {
            "blocker_id": "coordinate_write_gate_not_released",
            "required_to_clear": "manual/provider acceptance and explicit coordinate write gate with backup/readback",
        },
    ]


def leak_findings(payload: Any) -> list[dict[str, Any]]:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    findings: list[dict[str, Any]] = []
    for label, pattern in (("private_path", PRIVATE_PATH_RE), ("secret_like", SECRET_RE)):
        matches = pattern.findall(text)
        if matches:
            findings.append({"type": label, "count": len(matches)})
    return findings


def build_packet(*, source_fetch_rows: list[dict[str, Any]], source_fetch_rows_path: Path) -> dict[str, Any]:
    worker_tasks = [build_worker_task(row, index) for index, row in enumerate(source_fetch_rows, start=1)]
    account_batches = build_account_batches(worker_tasks)
    status_counts = Counter(first(task.get("worker_task_status")) for task in worker_tasks)
    city_counts = Counter(first(task.get("city")) or "unknown_city" for task in worker_tasks)
    source_account_counts = Counter(first(task.get("source_account_name")) or "unknown_source_account" for task in worker_tasks)
    missing_required_input_count = status_counts.get("blocked_missing_required_input", 0)
    packet = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_local(),
        "decision": "weekly_current_missing_geo_source_fetch_worker_contract_ready_report_only_waiting_controller_release"
        if worker_tasks and not missing_required_input_count
        else "weekly_current_missing_geo_source_fetch_worker_contract_partial_report_only"
        if worker_tasks
        else "weekly_current_missing_geo_source_fetch_worker_contract_empty_report_only",
        "inputs": {
            "source_fetch_rows": display_path(source_fetch_rows_path),
        },
        "summary": {
            "source_fetch_input_count": len(source_fetch_rows),
            "worker_task_count": len(worker_tasks),
            "ready_for_controller_release_count": status_counts.get("ready_for_controller_release", 0),
            "missing_required_input_count": missing_required_input_count,
            "account_batch_count": len(account_batches),
            "docker_worker_release_ready": False,
            "docker_worker_allowed_now": False,
            "network_fetch_allowed_now": False,
            "deepseek_or_model_call_allowed_now": False,
            "provider_or_geocode_call_allowed_now": False,
            "coordinate_write_allowed_count": 0,
            "status_counts": dict(sorted(status_counts.items())),
            "top_city_counts": dict(city_counts.most_common(20)),
            "source_account_counts": dict(source_account_counts.most_common(30)),
        },
        "runtime_contract": {
            "runtime_type": "layered_docker_worker_contract_no_execution",
            "skill_role": "thin_control_plane_only",
            "worker_layer": WORKER_LAYER,
            "docker_profile": DOCKER_PROFILE,
            "docker_service": DOCKER_SERVICE,
            "docker_compose_path": COMPOSE_PATH,
            "queue_name": QUEUE_NAME,
            "openclaw_queue_name": OPENCLAW_QUEUE_NAME,
            "execution_allowed_now": False,
            "network_allowed_now": False,
            "model_allowed_now": False,
            "provider_allowed_now": False,
            "db_write_allowed_now": False,
            "required_controller_release": "explicit_controller_source_fetch_runtime_release",
        },
        "release_blockers": release_blockers(),
        "next_action": {
            "first_gate": "controller_reviews_this_source_fetch_worker_contract",
            "second_gate": "if_approved_emit_source_fetch_runtime_release_artifact_with_exact_queue_and_profile",
            "third_gate": "run_l2_source_evidence_worker_in_docker_with_queue_lease_and_checkpoint",
            "fourth_gate": "build_source_fetch_result_acceptance_packet_no_coordinate_write",
            "fifth_gate": "only_then_consider_provider_or_coordinate_acceptance_gate",
        },
        "worker_tasks": worker_tasks,
        "account_batches": account_batches,
        "leak_findings": leak_findings({"worker_tasks": worker_tasks, "account_batches": account_batches}),
        "safety": {
            "report_only": True,
            "docker_worker_started": False,
            "network_fetch": False,
            "deepseek_or_model_call": False,
            "provider_or_geocode_call": False,
            "coordinate_write": False,
            "registry_mutation": False,
            "current_package_mutation": False,
            "db_graph_vector_write": False,
            "cloudbase_sync": False,
            "deploy_upload_review_release": False,
            "secret_read": False,
            "broad_disk_scan": False,
        },
    }
    return packet


def render_markdown(packet: dict[str, Any]) -> str:
    summary = packet["summary"]
    runtime = packet["runtime_contract"]
    lines = [
        "# Weekly Current Missing Geo Source Fetch Worker Contract",
        "",
        f"- decision: `{packet['decision']}`",
        f"- source_fetch_rows: `{packet['inputs']['source_fetch_rows']}`",
        f"- worker_layer: `{runtime['worker_layer']}`",
        f"- docker_profile: `{runtime['docker_profile']}`",
        f"- queue_name: `{runtime['queue_name']}`",
        f"- source_fetch_input_count: `{summary['source_fetch_input_count']}`",
        f"- worker_task_count: `{summary['worker_task_count']}`",
        f"- account_batch_count: `{summary['account_batch_count']}`",
        f"- ready_for_controller_release_count: `{summary['ready_for_controller_release_count']}`",
        f"- missing_required_input_count: `{summary['missing_required_input_count']}`",
        f"- docker_worker_allowed_now: `{summary['docker_worker_allowed_now']}`",
        f"- network_fetch_allowed_now: `{summary['network_fetch_allowed_now']}`",
        f"- deepseek_or_model_call_allowed_now: `{summary['deepseek_or_model_call_allowed_now']}`",
        f"- coordinate_write_allowed_count: `{summary['coordinate_write_allowed_count']}`",
        f"- leak_findings: `{len(packet['leak_findings'])}`",
        "",
        "## Source Accounts",
        "",
    ]
    for key, value in summary["source_account_counts"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(
        [
            "",
            "## Release Blockers",
            "",
        ]
    )
    for blocker in packet["release_blockers"]:
        lines.append(f"- `{blocker['blocker_id']}`: {blocker['required_to_clear']}")
    lines.extend(
        [
            "",
            "## Next Gates",
            "",
            f"1. `{packet['next_action']['first_gate']}`",
            f"2. `{packet['next_action']['second_gate']}`",
            f"3. `{packet['next_action']['third_gate']}`",
            f"4. `{packet['next_action']['fourth_gate']}`",
            f"5. `{packet['next_action']['fifth_gate']}`",
            "",
            "## Sample Tasks",
            "",
        ]
    )
    for task in packet["worker_tasks"][:20]:
        lines.append(
            "- "
            f"`{task['current_item_id']}` "
            f"account=`{task['source_account_name']}` "
            f"city=`{task['city']}` "
            f"status=`{task['worker_task_status']}`"
        )
    if len(packet["worker_tasks"]) > 20:
        lines.append(f"- ... `{len(packet['worker_tasks']) - 20}` more rows")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "Report-only Docker worker contract. No Docker/worker start, network fetch, DeepSeek/model call, provider/geocode call, coordinate write, registry/current-release/DB mutation, CloudBase sync, deploy/upload/review/release, secret read, or broad disk scan occurred.",
            "",
        ]
    )
    return "\n".join(lines)


def write_reports(packet: dict[str, Any], out_dir: Path, scorecard_path: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "weekly_current_missing_geo_source_fetch_worker_contract.json"
    md_path = out_dir / "weekly_current_missing_geo_source_fetch_worker_contract.md"
    tasks_path = out_dir / "weekly_current_missing_geo_source_fetch_worker_tasks.jsonl"
    batches_path = out_dir / "weekly_current_missing_geo_source_fetch_worker_account_batches.jsonl"
    blockers_path = out_dir / "weekly_current_missing_geo_source_fetch_worker_release_blockers.jsonl"
    write_json(json_path, packet)
    md_text = render_markdown(packet)
    md_path.write_text(md_text, encoding="utf-8")
    scorecard_path.parent.mkdir(parents=True, exist_ok=True)
    scorecard_path.write_text(md_text, encoding="utf-8")
    write_jsonl(tasks_path, packet["worker_tasks"])
    write_jsonl(batches_path, packet["account_batches"])
    write_jsonl(blockers_path, packet["release_blockers"])
    return {
        "json": json_path,
        "markdown": md_path,
        "tasks": tasks_path,
        "account_batches": batches_path,
        "release_blockers": blockers_path,
        "scorecard": scorecard_path,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-fetch-rows", type=Path, default=DEFAULT_SOURCE_FETCH_ROWS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--json-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    packet = build_packet(
        source_fetch_rows=read_jsonl(args.source_fetch_rows),
        source_fetch_rows_path=args.source_fetch_rows,
    )
    paths = write_reports(packet, args.out_dir, args.scorecard)
    if args.json_only:
        print(json.dumps(packet, ensure_ascii=False, sort_keys=True))
    else:
        summary = packet["summary"]
        print(f"decision={packet['decision']}")
        print(f"worker_task_count={summary['worker_task_count']}")
        print(f"ready_for_controller_release_count={summary['ready_for_controller_release_count']}")
        print(f"missing_required_input_count={summary['missing_required_input_count']}")
        print(f"account_batch_count={summary['account_batch_count']}")
        print(f"docker_worker_allowed_now={summary['docker_worker_allowed_now']}")
        print(f"network_fetch_allowed_now={summary['network_fetch_allowed_now']}")
        print(f"coordinate_write_allowed_count={summary['coordinate_write_allowed_count']}")
        print(f"json={paths['json']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
