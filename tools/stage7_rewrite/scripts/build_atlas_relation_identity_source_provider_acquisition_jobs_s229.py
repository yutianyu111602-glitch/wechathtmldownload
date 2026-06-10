from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
REPORTS_ROOT = ROOT / "tools" / "stage7_rewrite" / "reports"
DEFAULT_WORKBENCH = (
    REPORTS_ROOT
    / "atlas_relation_identity_s228_pending_candidate_workbench_20260602"
    / "s228_pending_candidate_workbench.jsonl"
)
DEFAULT_TASKS = (
    REPORTS_ROOT
    / "atlas_relation_db2_source_provider_spool_sidecar_s224_from_s219_20260602"
    / "s224_normalized_source_provider_tasks.jsonl"
)
DEFAULT_EVENTS = (
    REPORTS_ROOT
    / "atlas_relation_identity_db2_source_provider_spool_s225_from_s219_20260602"
    / "s222_db2_writer_identity_candidate_events.jsonl"
)
DEFAULT_OUT_DIR = REPORTS_ROOT / "atlas_relation_identity_source_provider_acquisition_jobs_s229_20260602"

SCHEMA_VERSION = "atlas_relation_identity_source_provider_acquisition_jobs_s229.v1"
ROW_SCHEMA_VERSION = f"{SCHEMA_VERSION}.job"

RAW_URL_RE = re.compile(r"https?://", re.IGNORECASE)
RAW_PATH_RE = re.compile(r"(?:[A-Za-z]:\\|/mnt/[a-z]/|/home/pc/|\\\\)", re.IGNORECASE)
SECRET_RE = re.compile(r"(?:secret|token|cookie|sk=|key=)", re.IGNORECASE)

LANE_ACTIONS = {
    "P1_recover_missing_profile_archive_or_provider": "identity_missing_archive_or_provider_recovery",
    "P2_provider_anchor_crosscheck": "identity_provider_anchor_crosscheck",
    "P2_resolved_source_url_public_or_archive_replay": "identity_resolved_source_replay",
    "P2_source_title_crosscheck": "identity_source_title_crosscheck",
    "P3_external_manual_acquisition": "identity_external_manual_acquisition",
}

ACTION_PROFILES = {
    "identity_missing_archive_or_provider_recovery": {
        "worker_profile": "safe",
        "requires_network": False,
        "preferred_input": "exact_archive_or_resolved_source_ref_ids",
    },
    "identity_provider_anchor_crosscheck": {
        "worker_profile": "safe",
        "requires_network": False,
        "preferred_input": "source_account_or_provider_anchor",
    },
    "identity_resolved_source_replay": {
        "worker_profile": "safe",
        "requires_network": False,
        "preferred_input": "resolved_source_ref_ids",
    },
    "identity_source_title_crosscheck": {
        "worker_profile": "safe",
        "requires_network": False,
        "preferred_input": "source_title_seed",
    },
    "identity_external_manual_acquisition": {
        "worker_profile": "experimental",
        "requires_network": True,
        "preferred_input": "external_source_provider_search",
    },
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if text:
                rows.append(json.loads(text))
    return rows


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def stable_id(*parts: Any) -> str:
    text = "\x1f".join(str(part or "") for part in parts)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:20]


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def safe_strings(value: Any) -> list[str]:
    return [str(item) for item in as_list(value) if str(item)]


def detail_by_task(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row.get("task_id") or ""): row for row in rows if row.get("task_id")}


def event_by_task(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows:
        task_id = str(row.get("source_profile_id") or row.get("handle") or "")
        if task_id:
            indexed[task_id] = row
    return indexed


def missing_archive_dj_ids(task: dict[str, Any]) -> list[str]:
    per_dj = task.get("per_dj_resolution") or {}
    ids: list[str] = []
    for dj_id, resolution in per_dj.items():
        if isinstance(resolution, dict) and not bool(resolution.get("has_exact_archive")):
            ids.append(str(dj_id))
    return sorted(ids)


def collect_source_ref_ids(task: dict[str, Any], field: str) -> list[str]:
    per_dj = task.get("per_dj_resolution") or {}
    ids: set[str] = set()
    for resolution in per_dj.values():
        if not isinstance(resolution, dict):
            continue
        for ref_id in resolution.get(field) or []:
            text = str(ref_id)
            if text:
                ids.add(text)
    return sorted(ids)


def job_action_for_lane(lane: str) -> str:
    return LANE_ACTIONS.get(lane, "identity_external_manual_acquisition")


def build_job(workbench: dict[str, Any], task: dict[str, Any] | None, event: dict[str, Any] | None) -> dict[str, Any]:
    task = task or {}
    event = event or {}
    task_id = str(workbench.get("task_id") or task.get("task_id") or event.get("source_profile_id") or "")
    lane = str(workbench.get("s228_lane") or "")
    action = job_action_for_lane(lane)
    profile = ACTION_PROFILES[action]
    source_seed = task.get("source_seed") or workbench.get("source_seed") or {}
    exact_refs = collect_source_ref_ids(task, "exact_archive_source_ref_ids")
    public_fetch_refs = collect_source_ref_ids(task, "public_fetch_source_ref_ids")
    missing_djs = missing_archive_dj_ids(task)
    group_id = str(workbench.get("group_id") or task.get("group_id") or event.get("eid") or "")
    job_id = "s229:" + stable_id(task_id, group_id, lane, event.get("sidecar_id"))

    return {
        "schema_version": ROW_SCHEMA_VERSION,
        "job_id": job_id,
        "task_id": task_id,
        "candidate_sidecar_id": event.get("sidecar_id"),
        "subject_id": event.get("subject_id"),
        "group_id": group_id,
        "normalized_name": event.get("normalized_name") or "".join(safe_strings(workbench.get("unicode_compact_values"))[:1]),
        "display_names": workbench.get("display_names") or task.get("display_names") or [],
        "dj_ids": workbench.get("dj_ids") or task.get("dj_ids") or [],
        "unicode_compact_values": workbench.get("unicode_compact_values") or task.get("unicode_compact_values") or [],
        "review_status": event.get("review_status") or workbench.get("review_status"),
        "s228_lane": lane,
        "acquisition_action": action,
        "worker_profile": profile["worker_profile"],
        "requires_network": bool(profile["requires_network"]),
        "preferred_input": profile["preferred_input"],
        "priority": workbench.get("priority") or task.get("priority"),
        "priority_rank": int(task.get("priority_rank") or 99),
        "source_ref_count": int(task.get("source_ref_count") or workbench.get("source_ref_count") or 0),
        "source_url_resolved_ref_count": int(task.get("source_url_resolved_ref_count") or workbench.get("source_url_resolved_ref_count") or 0),
        "exact_archive_ref_count": int(task.get("exact_archive_ref_count") or workbench.get("exact_archive_ref_count") or 0),
        "public_fetch_ready_ref_count": int(task.get("public_fetch_ready_ref_count") or workbench.get("public_fetch_ready_ref_count") or 0),
        "missing_archive_dj_ids": missing_djs,
        "exact_archive_source_ref_ids": exact_refs[:20],
        "public_fetch_source_ref_ids": public_fetch_refs[:20],
        "source_seed": {
            "common_source_accounts": safe_strings(source_seed.get("common_source_accounts")),
            "common_titles": safe_strings(source_seed.get("common_titles")),
            "common_venues": safe_strings(source_seed.get("common_venues")),
            "has_provider_anchor": bool(source_seed.get("has_provider_anchor")),
            "has_source_account_or_title_seed": bool(source_seed.get("has_source_account_or_title_seed")),
        },
        "evidence_ready_for_db3": False,
        "db3_write_allowed_now": False,
        "db2_projection_allowed_now": False,
        "writer_event_allowed_now": False,
        "output_contract": "report_local_job_only_until_article_ready_or_provider_crosschecked_evidence",
    }


def scan_safety(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        text = json.dumps(row, ensure_ascii=False, sort_keys=True)
        for kind, pattern in (("raw_url", RAW_URL_RE), ("raw_path", RAW_PATH_RE), ("secret_like", SECRET_RE)):
            if pattern.search(text):
                findings.append({"index": index, "job_id": row.get("job_id"), "kind": kind, "severity": "block"})
    return findings


def build_jobs(
    workbench_rows: list[dict[str, Any]],
    task_rows: list[dict[str, Any]],
    event_rows: list[dict[str, Any]],
    *,
    lane: str | None = None,
    max_jobs: int | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    tasks = detail_by_task(task_rows)
    events = event_by_task(event_rows)
    selected = [row for row in workbench_rows if not lane or row.get("s228_lane") == lane]
    selected.sort(key=lambda row: (str(row.get("s228_lane") or ""), int(row.get("source_ref_count") or 0) * -1, str(row.get("task_id") or "")))
    if max_jobs is not None:
        selected = selected[:max_jobs]

    jobs: list[dict[str, Any]] = []
    missing_task_count = 0
    missing_event_count = 0
    for row in selected:
        task_id = str(row.get("task_id") or "")
        task = tasks.get(task_id)
        event = events.get(task_id)
        if task is None:
            missing_task_count += 1
        if event is None:
            missing_event_count += 1
        jobs.append(build_job(row, task, event))

    safety_findings = scan_safety(jobs)
    lane_counts = Counter(str(job.get("s228_lane") or "unknown") for job in jobs)
    action_counts = Counter(str(job.get("acquisition_action") or "unknown") for job in jobs)
    profile_counts = Counter(str(job.get("worker_profile") or "unknown") for job in jobs)
    network_count = sum(1 for job in jobs if job.get("requires_network"))

    report = {
        "schema_version": SCHEMA_VERSION,
        "current_story_id": "S229",
        "generated_at": utc_now(),
        "decision": (
            "atlas_relation_identity_source_provider_acquisition_jobs_s229_ready_report_only"
            if not safety_findings and missing_task_count == 0 and missing_event_count == 0
            else "atlas_relation_identity_source_provider_acquisition_jobs_s229_needs_review"
        ),
        "counts": {
            "input_workbench_count": len(workbench_rows),
            "input_task_detail_count": len(task_rows),
            "input_event_count": len(event_rows),
            "selected_job_count": len(jobs),
            "missing_task_detail_count": missing_task_count,
            "missing_event_count": missing_event_count,
            "requires_network_job_count": network_count,
            "evidence_ready_for_db3_count": 0,
            "writer_event_allowed_count": 0,
            "safety_finding_count": len(safety_findings),
            "lane_counts": dict(lane_counts),
            "acquisition_action_counts": dict(action_counts),
            "worker_profile_counts": dict(profile_counts),
        },
        "safety": {
            "report_only": True,
            "network_fetch": False,
            "model_calls": False,
            "db1_mutation": False,
            "db2_mutation": False,
            "db2_projection": False,
            "db3_mutation": False,
            "cloudrun_deploy": False,
            "cloudbase_sync": False,
            "mini_program_upload": False,
            "wechat_review_submit": False,
            "public_release": False,
            "raw_source_url_emitted": False,
            "raw_archive_path_emitted": False,
            "secret_values_printed": False,
            "safety_findings": safety_findings,
        },
        "execution_cursor": {
            "next_story_id": "S230",
            "next_action": "Run a bounded Docker read-only smoke of the S229 acquisition jobs, then implement real provider/archive evidence collectors per lane before any writer event or DB3 write gate.",
            "do_not_run": [
                "Do not mark identity candidates accepted without article-ready or provider-crosschecked evidence.",
                "Do not write DB2 projection while atlas_relation_field_integrity is red.",
                "Do not deploy/upload/review/release while deploy preflight has required failures.",
            ],
        },
    }

    by_action: dict[str, list[dict[str, Any]]] = {}
    for job in jobs:
        by_action.setdefault(str(job["acquisition_action"]), []).append(job)
    return report, jobs, by_action


def render_markdown(report: dict[str, Any], report_path: Path) -> str:
    counts = report["counts"]
    lines = [
        "# Atlas Relation Identity Source Provider Acquisition Jobs S229",
        "",
        f"Generated: {report['generated_at']}",
        "",
        f"Decision: `{report['decision']}`",
        "",
        "## Counts",
        "",
        f"- selected_job_count: `{counts['selected_job_count']}`",
        f"- missing_task_detail_count: `{counts['missing_task_detail_count']}`",
        f"- missing_event_count: `{counts['missing_event_count']}`",
        f"- requires_network_job_count: `{counts['requires_network_job_count']}`",
        f"- evidence_ready_for_db3_count: `{counts['evidence_ready_for_db3_count']}`",
        f"- writer_event_allowed_count: `{counts['writer_event_allowed_count']}`",
        "",
        "## Actions",
        "",
    ]
    for action, value in sorted(counts["acquisition_action_counts"].items()):
        lines.append(f"- `{action}`: `{value}`")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "S229 is a report-local Docker worker job adapter. It does not fetch network resources, call models, mutate DB1/DB2/DB3, project DB2, deploy, upload, review, release, or emit raw source URLs/archive paths.",
            "",
            "## Next",
            "",
            report["execution_cursor"]["next_action"],
            "",
            "## Artifact",
            "",
            f"- `{rel(report_path)}`",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build S229 DB2 identity source/provider acquisition jobs")
    parser.add_argument("--workbench", type=Path, default=DEFAULT_WORKBENCH)
    parser.add_argument("--tasks", type=Path, default=DEFAULT_TASKS)
    parser.add_argument("--events", type=Path, default=DEFAULT_EVENTS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--lane", choices=sorted(LANE_ACTIONS), help="Optional bounded lane filter")
    parser.add_argument("--max-jobs", type=int, help="Optional bounded job count")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.max_jobs is not None and args.max_jobs <= 0:
        raise SystemExit("--max-jobs must be positive")

    workbench_rows = read_jsonl(args.workbench)
    task_rows = read_jsonl(args.tasks)
    event_rows = read_jsonl(args.events)
    report, jobs, by_action = build_jobs(
        workbench_rows,
        task_rows,
        event_rows,
        lane=args.lane,
        max_jobs=args.max_jobs,
    )

    out_dir = args.out_dir
    report_path = out_dir / "atlas_relation_identity_source_provider_acquisition_jobs_s229.json"
    jobs_path = out_dir / "s229_acquisition_jobs.jsonl"
    manifest_path = out_dir / "s229_docker_worker_manifest.json"
    markdown_path = out_dir / "atlas_relation_identity_source_provider_acquisition_jobs_s229.md"
    action_dir = out_dir / "jobs_by_action"

    artifacts = {
        "report_json": rel(report_path),
        "jobs_jsonl": rel(jobs_path),
        "docker_worker_manifest": rel(manifest_path),
        "markdown": rel(markdown_path),
        "jobs_by_action_dir": rel(action_dir),
    }
    report["artifacts"] = artifacts

    manifest = {
        "schema_version": f"{SCHEMA_VERSION}.docker_worker_manifest",
        "generated_at": report["generated_at"],
        "default_command": "python tools/stage7_rewrite/scripts/build_atlas_relation_identity_source_provider_acquisition_jobs_s229.py",
        "docker_profiles": sorted(set(job["worker_profile"] for job in jobs)),
        "job_count": len(jobs),
        "report_only": True,
        "writer_event_allowed_count": 0,
        "inputs": {
            "workbench": rel(args.workbench),
            "tasks": rel(args.tasks),
            "events": rel(args.events),
        },
        "outputs": artifacts,
    }

    write_json(report_path, report)
    write_jsonl(jobs_path, jobs)
    for action, rows in by_action.items():
        write_jsonl(action_dir / f"{action}.jsonl", rows)
    write_json(manifest_path, manifest)
    markdown_path.write_text(render_markdown(report, report_path), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
