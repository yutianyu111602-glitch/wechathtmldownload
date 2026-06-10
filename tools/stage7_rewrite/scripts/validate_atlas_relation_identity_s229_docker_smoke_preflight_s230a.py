from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
REPORTS_ROOT = ROOT / "tools" / "stage7_rewrite" / "reports"
DEFAULT_S229_DIR = REPORTS_ROOT / "atlas_relation_identity_source_provider_acquisition_jobs_s229_20260602"
DEFAULT_OUT_DIR = REPORTS_ROOT / "atlas_relation_identity_s229_docker_smoke_preflight_s230a_20260602"

RAW_URL_RE = re.compile(r"https?://", re.IGNORECASE)
RAW_PATH_RE = re.compile(r"(?:[A-Za-z]:\\|/mnt/[a-z]/|/home/pc/|\\\\)", re.IGNORECASE)
SECRET_RE = re.compile(r"(?:secret|token|cookie|password|authorization)", re.IGNORECASE)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


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


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def scan_jobs(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for index, job in enumerate(jobs):
        text = json.dumps(job, ensure_ascii=False, sort_keys=True)
        for kind, pattern in (("raw_url", RAW_URL_RE), ("raw_path", RAW_PATH_RE), ("secret_like", SECRET_RE)):
            if pattern.search(text):
                findings.append({"kind": kind, "index": index, "job_id": job.get("job_id"), "severity": "block"})
        for field in ("evidence_ready_for_db3", "db3_write_allowed_now", "db2_projection_allowed_now", "writer_event_allowed_now"):
            if bool(job.get(field)):
                findings.append({"kind": f"job_flag_enabled:{field}", "index": index, "job_id": job.get("job_id"), "severity": "block"})
    return findings


def validate(report: dict[str, Any], manifest: dict[str, Any], jobs: list[dict[str, Any]]) -> dict[str, Any]:
    failed_checks: list[dict[str, Any]] = []
    counts = report.get("counts") or {}
    artifacts = report.get("artifacts") or {}
    expected_jobs = int(counts.get("selected_job_count") or 0)
    job_count = len(jobs)

    if report.get("decision") != "atlas_relation_identity_source_provider_acquisition_jobs_s229_ready_report_only":
        failed_checks.append({"check": "s229_decision_ready", "value": report.get("decision")})
    if job_count != expected_jobs:
        failed_checks.append({"check": "job_count_matches_report", "expected": expected_jobs, "actual": job_count})
    if int(counts.get("writer_event_allowed_count") or 0) != 0:
        failed_checks.append({"check": "writer_event_allowed_count_zero", "value": counts.get("writer_event_allowed_count")})
    if int(counts.get("evidence_ready_for_db3_count") or 0) != 0:
        failed_checks.append({"check": "evidence_ready_for_db3_count_zero", "value": counts.get("evidence_ready_for_db3_count")})
    if not bool(report.get("safety", {}).get("report_only")):
        failed_checks.append({"check": "report_only_true"})
    if not bool(manifest.get("report_only")):
        failed_checks.append({"check": "manifest_report_only_true"})
    if int(manifest.get("writer_event_allowed_count") or 0) != 0:
        failed_checks.append({"check": "manifest_writer_event_allowed_zero", "value": manifest.get("writer_event_allowed_count")})
    if int(manifest.get("job_count") or 0) != job_count:
        failed_checks.append({"check": "manifest_job_count_matches", "expected": job_count, "actual": manifest.get("job_count")})

    for key in ("jobs_jsonl", "docker_worker_manifest", "report_json"):
        path_text = artifacts.get(key)
        if not path_text or not (ROOT / path_text).exists():
            failed_checks.append({"check": "artifact_exists", "artifact": key, "path": path_text})

    safety_findings = scan_jobs(jobs)
    failed_checks.extend(safety_findings)
    profile_counts = Counter(str(job.get("worker_profile") or "unknown") for job in jobs)
    action_counts = Counter(str(job.get("acquisition_action") or "unknown") for job in jobs)

    return {
        "schema_version": "atlas_relation_identity_s229_docker_smoke_preflight_s230a.v1",
        "current_story_id": "S230A",
        "generated_at": utc_now(),
        "decision": (
            "atlas_relation_identity_s229_docker_smoke_preflight_s230a_ready_for_docker_smoke_after_db2_hold"
            if not failed_checks
            else "atlas_relation_identity_s229_docker_smoke_preflight_s230a_blocked"
        ),
        "counts": {
            "job_count": job_count,
            "safe_profile_job_count": int(profile_counts.get("safe", 0)),
            "experimental_profile_job_count": int(profile_counts.get("experimental", 0)),
            "action_counts": dict(action_counts),
            "failed_check_count": len(failed_checks),
        },
        "failed_checks": failed_checks,
        "safety": {
            "report_only": True,
            "docker_started": False,
            "network_fetch": False,
            "model_calls": False,
            "db1_mutation": False,
            "db2_mutation": False,
            "db2_projection": False,
            "db3_mutation": False,
            "deploy_upload_review_release": False,
            "raw_url_or_path_emitted": False,
            "secret_values_printed": False,
        },
        "execution_cursor": {
            "next_story_id": "S230",
            "next_action": "Wait for the active DB2 avatar production cycle to exit, rerun DB2 health/writer/schedule, then execute a bounded read-only Docker smoke over the S229 manifest.",
            "do_not_run_while_active_db2_cycle": [
                "docker compose run db2-light-workers for S229/S230",
                "db2ctl production worker-batch --execute",
                "db2ctl writer once --execute",
                "DB2_WORKER_EXECUTE=1",
                "DB2_WRITER_EXECUTE=1",
            ],
        },
    }


def render_markdown(report: dict[str, Any], report_path: Path) -> str:
    counts = report["counts"]
    lines = [
        "# Atlas Relation Identity S229 Docker Smoke Preflight S230A",
        "",
        f"Decision: `{report['decision']}`",
        "",
        f"- job_count: `{counts['job_count']}`",
        f"- safe_profile_job_count: `{counts['safe_profile_job_count']}`",
        f"- experimental_profile_job_count: `{counts['experimental_profile_job_count']}`",
        f"- failed_check_count: `{counts['failed_check_count']}`",
        "",
        "## Boundary",
        "",
        "S230A is local/report-only. It does not start Docker, fetch network resources, call models, mutate DB1/DB2/DB3, project DB2, deploy, upload, review, or release.",
        "",
        "## Next",
        "",
        report["execution_cursor"]["next_action"],
        "",
        "## Artifact",
        "",
        f"- `{rel(report_path)}`",
    ]
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate S229 artifacts before Docker smoke")
    parser.add_argument("--s229-dir", type=Path, default=DEFAULT_S229_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    s229_dir = args.s229_dir
    report = read_json(s229_dir / "atlas_relation_identity_source_provider_acquisition_jobs_s229.json")
    manifest = read_json(s229_dir / "s229_docker_worker_manifest.json")
    jobs = read_jsonl(s229_dir / "s229_acquisition_jobs.jsonl")
    result = validate(report, manifest, jobs)

    out_dir = args.out_dir
    report_path = out_dir / "atlas_relation_identity_s229_docker_smoke_preflight_s230a.json"
    markdown_path = out_dir / "atlas_relation_identity_s229_docker_smoke_preflight_s230a.md"
    result["artifacts"] = {
        "report_json": rel(report_path),
        "markdown": rel(markdown_path),
    }
    write_json(report_path, result)
    markdown_path.write_text(render_markdown(result, report_path), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not result["failed_checks"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
