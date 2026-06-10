#!/usr/bin/env python3
"""DB2 external-link Docker skill control-plane.

This script is a thin skill/control layer for DB2 external-link scraping lanes.
It discovers available OpenClaw Docker weapons, builds a bounded fetch plan from
queue artifacts, and emits a Docker run command contract.

Default mode is report-only: no Docker start, no network fetch, no DB write.
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DOCKER_ROOT = REPO_ROOT / "tools" / "stage7_rewrite" / "docker" / "openclaw-db2-external-link"
CONTRACT_COMPOSE = DOCKER_ROOT / "docker-compose.openclaw-db2-external-link.yml"
RUNTIME_COMPOSE = DOCKER_ROOT / "docker-compose.openclaw-db2-external-link.runtime.yml"
DEFAULT_QUEUE_DB2_SIDECAR = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "external_link_db2_sidecar_contract_s119_20260601"
    / "external_link_db2_sidecar_candidates.jsonl"
)
DEFAULT_OUT_DIR = REPO_ROOT / "tools" / "stage7_rewrite" / "reports" / "db2_external_link_docker_skill_20260604"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "DB2_EXTERNAL_LINK_DOCKER_SKILL_20260604.md"
DEFAULT_RUNTIME_SERVICE = "openclaw-db2-outlink-public-fetch"
DEFAULT_RUNTIME_PROFILE = "openclaw-db2-outlink-public-fetch"
DEFAULT_RUNTIME_QUEUE = "openclaw.db2_outlink_public_fetch"

SCHEMA_VERSION = "db2_external_link_docker_skill.v1"


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def rel_path(path: Path, root: Path = REPO_ROOT) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def parse_services(compose_text: str) -> dict[str, dict[str, str]]:
    services: dict[str, dict[str, str]] = {}
    section_match = re.search(r"^services:\s*$", compose_text, flags=re.MULTILINE)
    if not section_match:
        return services

    services_text = compose_text[section_match.end() :]
    service_blocks = list(re.finditer(r"^  ([a-z0-9-]+):\s*$", services_text, flags=re.MULTILINE))
    for i, m in enumerate(service_blocks):
        name = m.group(1)
        start = m.start()
        end = service_blocks[i + 1].start() if i + 1 < len(service_blocks) else len(services_text)
        block = services_text[start:end]
        profile_match = re.search(r'profiles:\s*\["([^"]+)"\]', block)
        layer_match = re.search(r'OPENCLAW_LAYER:\s*"([^"]+)"', block)
        queue_match = re.search(r'OPENCLAW_QUEUE_NAME:\s*"([^"]+)"', block)
        services[name] = {
            "profile": profile_match.group(1) if profile_match else "",
            "layer": layer_match.group(1) if layer_match else "",
            "queue_name": queue_match.group(1) if queue_match else "",
        }
    return services


def load_queue_rows(path: Path, limit: int, start_offset: int = 0) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    seen = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        if not isinstance(obj, dict):
            continue
        if seen < start_offset:
            seen += 1
            continue
        rows.append(obj)
        seen += 1
        if limit > 0 and len(rows) >= limit:
            break
    return rows


def build_plan_rows(rows: list[dict[str, Any]], start_offset: int = 0) -> list[dict[str, Any]]:
    plan: list[dict[str, Any]] = []
    for idx, row in enumerate(rows, start=1):
        plan.append(
            {
                "order": start_offset + idx,
                "task_id": str(row.get("sidecar_id") or row.get("task_id") or ""),
                "entity_search_id": str(row.get("entity_search_id") or ""),
                "entity_name": str(row.get("entity_name") or ""),
                "entity_type": str(row.get("entity_type") or ""),
                "platform": str(row.get("platform") or ""),
                "source_url": str(row.get("url") or row.get("profile_url") or ""),
                "public_category": str(row.get("public_category") or ""),
                "confidence_score": int(row.get("confidence_score", 0)),
                "confidence_band": str(row.get("confidence_band") or ""),
                "docker_profile": str(row.get("docker_profile") or DEFAULT_RUNTIME_PROFILE),
                "docker_service": str(row.get("docker_service") or DEFAULT_RUNTIME_SERVICE),
                "queue_name": str(row.get("queue_name") or DEFAULT_RUNTIME_QUEUE),
                "network_fetch_allowed_now": bool(row.get("network_fetch_allowed_now", False)),
                "db_graph_vector_write_allowed_now": bool(row.get("db_graph_vector_write_allowed_now", False)),
                "deploy_upload_review_allowed_now": bool(row.get("deploy_upload_review_allowed_now", False)),
            }
        )
    return plan


def build_docker_command(contract_compose: Path, runtime_compose: Path, profile: str, service: str) -> list[str]:
    return [
        "docker",
        "compose",
        "-f",
        str(contract_compose),
        "-f",
        str(runtime_compose),
        "--profile",
        profile,
        "run",
        "--rm",
        service,
    ]


def runtime_report_path(repo_root: Path, runtime_service: str) -> Path:
    return (
        repo_root
        / "tools"
        / "stage7_rewrite"
        / "reports"
        / "openclaw_db2_external_link_profiles_contract"
        / f"{runtime_service}_public_fetch_report.json"
    )


def attach_runtime_report(report: dict[str, Any], repo_root: Path) -> None:
    runtime_service = str(report["weapons_inventory"]["runtime_service"])
    path = runtime_report_path(repo_root, runtime_service)
    runtime_report = read_json(path)
    report["execution_contract"]["runtime_report_path"] = rel_path(path, repo_root)
    if not runtime_report:
        report["execution_contract"]["runtime_report_found"] = False
        return
    report["execution_contract"]["runtime_report_found"] = True
    report["execution_contract"]["network_fetch_executed"] = bool(runtime_report.get("network_fetch_executed"))
    report["execution_contract"]["db_write_executed"] = bool(runtime_report.get("db_write_executed"))
    report["execution_contract"]["secret_read_executed"] = bool(runtime_report.get("secret_read_executed"))
    report["execution_contract"]["runtime_summary"] = {
        "decision": runtime_report.get("decision", ""),
        "input_count": runtime_report.get("input_count", 0),
        "attempted_fetch_count": runtime_report.get("attempted_fetch_count", 0),
        "fetched_count": runtime_report.get("fetched_count", 0),
        "blocked_count": runtime_report.get("blocked_count", 0),
        "raw_url_private_path_secret_leak_count": runtime_report.get("raw_url_private_path_secret_leak_count", 0),
        "cookie_or_token_read_executed": runtime_report.get("cookie_or_token_read_executed", False),
        "identity_promotion_executed": runtime_report.get("identity_promotion_executed", False),
        "db2_projection_executed": runtime_report.get("db2_projection_executed", False),
    }


def build_report(
    repo_root: Path,
    contract_compose: Path,
    runtime_compose: Path,
    queue_path: Path,
    max_tasks: int,
    start_offset: int,
    allow_docker_run: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    contract_text = read_text(contract_compose)
    runtime_text = read_text(runtime_compose)
    services_contract = parse_services(contract_text)
    services_runtime = parse_services(runtime_text)

    queue_rows = load_queue_rows(queue_path, max_tasks, max(start_offset, 0))
    plan_rows = build_plan_rows(queue_rows, max(start_offset, 0))

    runtime_service = DEFAULT_RUNTIME_SERVICE
    runtime_profile = DEFAULT_RUNTIME_PROFILE
    command = build_docker_command(contract_compose, runtime_compose, runtime_profile, runtime_service)

    decision = (
        "db2_external_link_docker_skill_runtime_execution_allowed_by_explicit_flag"
        if allow_docker_run
        else "db2_external_link_docker_skill_ready_report_only_no_execution"
    )

    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": decision,
        "mode": "control_plane_skill_docker_arsenal",
        "inputs": {
            "contract_compose": rel_path(contract_compose, repo_root),
            "runtime_compose": rel_path(runtime_compose, repo_root),
            "queue_path": rel_path(queue_path, repo_root),
        },
        "weapons_inventory": {
            "contract_services": services_contract,
            "runtime_services": services_runtime,
            "runtime_service": runtime_service,
            "runtime_profile": runtime_profile,
        },
        "plan_summary": {
            "task_count": len(plan_rows),
            "max_tasks": max_tasks,
            "start_offset": max(start_offset, 0),
            "all_tasks_report_only": all(not bool(r.get("network_fetch_allowed_now")) for r in plan_rows),
        },
        "execution_contract": {
            "docker_command": command,
            "docker_command_shell": shlex.join(command),
            "allow_docker_run": allow_docker_run,
            "docker_build_context": "tools/stage7_rewrite/docker/openclaw-db2-external-link",
            "repo_root_sent_as_build_context": False,
            "repo_root_mounted_in_container": False,
            "reports_mount": "tools/stage7_rewrite/reports:/openclaw-reports",
            "docker_started": False,
            "network_fetch_executed": False,
            "db_write_executed": False,
            "coordinate_write_executed": False,
            "deploy_upload_review_executed": False,
            "secret_read_executed": False,
        },
        "next_required_gate": "explicit_controller_release_and_runtime_report_before_any_non_report_only_claim",
    }
    return report, plan_rows, command


def write_scorecard(path: Path, report: dict[str, Any]) -> None:
    s = report["plan_summary"]
    e = report["execution_contract"]
    lines = [
        "# DB2 External Link Docker Skill",
        "",
        f"Generated: {report.get('generated_at', '')}",
        "",
        f"- decision: {report['decision']}",
        f"- task_count: {s['task_count']}",
        f"- start_offset: {s.get('start_offset', 0)}",
        f"- runtime_service: {report['weapons_inventory']['runtime_service']}",
        f"- runtime_profile: {report['weapons_inventory']['runtime_profile']}",
        f"- allow_docker_run: {str(e['allow_docker_run']).lower()}",
        f"- docker_build_context: {e['docker_build_context']}",
        f"- repo_root_sent_as_build_context: {str(e['repo_root_sent_as_build_context']).lower()}",
        f"- repo_root_mounted_in_container: {str(e['repo_root_mounted_in_container']).lower()}",
        f"- runtime_report_found: {str(e.get('runtime_report_found', False)).lower()}",
        "",
        "## Boundary",
        "",
        "Skill is control-plane first. Default is report-only: no Docker start, no network fetch, no DB/coordinate write, no deploy/upload/review/release.",
        "",
        "## Docker Command",
        "",
        e["docker_command_shell"],
        "",
    ]
    if e.get("runtime_summary"):
        summary = e["runtime_summary"]
        lines.extend(
            [
                "## Runtime Summary",
                "",
                f"- decision: {summary.get('decision', '')}",
                f"- input_count: {summary.get('input_count', 0)}",
                f"- fetched_count: {summary.get('fetched_count', 0)}",
                f"- blocked_count: {summary.get('blocked_count', 0)}",
                f"- raw_url_private_path_secret_leak_count: {summary.get('raw_url_private_path_secret_leak_count', 0)}",
                f"- db2_projection_executed: {str(summary.get('db2_projection_executed', False)).lower()}",
                f"- identity_promotion_executed: {str(summary.get('identity_promotion_executed', False)).lower()}",
                f"- cookie_or_token_read_executed: {str(summary.get('cookie_or_token_read_executed', False)).lower()}",
                "",
            ]
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="DB2 external-link Docker skill control-plane")
    p.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    p.add_argument("--contract-compose", type=Path, default=CONTRACT_COMPOSE)
    p.add_argument("--runtime-compose", type=Path, default=RUNTIME_COMPOSE)
    p.add_argument("--queue", type=Path, default=DEFAULT_QUEUE_DB2_SIDECAR)
    p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    p.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    p.add_argument("--max-tasks", type=int, default=50)
    p.add_argument("--start-offset", type=int, default=0)
    p.add_argument("--allow-docker-run", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    contract_compose = args.contract_compose if args.contract_compose.is_absolute() else repo_root / args.contract_compose
    runtime_compose = args.runtime_compose if args.runtime_compose.is_absolute() else repo_root / args.runtime_compose
    queue_path = args.queue if args.queue.is_absolute() else repo_root / args.queue

    report, plan_rows, command = build_report(
        repo_root=repo_root,
        contract_compose=contract_compose,
        runtime_compose=runtime_compose,
        queue_path=queue_path,
        max_tasks=args.max_tasks,
        start_offset=args.start_offset,
        allow_docker_run=args.allow_docker_run,
    )

    out_dir = args.out_dir if args.out_dir.is_absolute() else repo_root / args.out_dir
    write_json(out_dir / "db2_external_link_docker_skill.json", report)
    write_jsonl(out_dir / "db2_external_link_docker_skill_plan.jsonl", plan_rows)
    write_scorecard(args.scorecard if args.scorecard.is_absolute() else repo_root / args.scorecard, report)

    if args.allow_docker_run:
        try:
            subprocess.run(command, check=True)
            report["execution_contract"]["docker_started"] = True
            attach_runtime_report(report, repo_root)
            write_json(out_dir / "db2_external_link_docker_skill.json", report)
            write_scorecard(args.scorecard if args.scorecard.is_absolute() else repo_root / args.scorecard, report)
        except FileNotFoundError:
            report["decision"] = "db2_external_link_docker_skill_runtime_requested_but_docker_not_found"
            write_json(out_dir / "db2_external_link_docker_skill.json", report)
            print(json.dumps({"decision": report["decision"], "docker_command": command}, ensure_ascii=False))
            return 2
        except subprocess.CalledProcessError as exc:
            report["decision"] = "db2_external_link_docker_skill_runtime_requested_but_failed"
            report["execution_contract"]["runtime_exit_code"] = exc.returncode
            write_json(out_dir / "db2_external_link_docker_skill.json", report)
            print(json.dumps({"decision": report["decision"], "exit_code": exc.returncode}, ensure_ascii=False))
            return exc.returncode

    print(
        json.dumps(
            {
                "schema_version": report["schema_version"],
                "decision": report["decision"],
                "task_count": report["plan_summary"]["task_count"],
                "output_json": str(out_dir / "db2_external_link_docker_skill.json"),
                "scorecard": str(args.scorecard if args.scorecard.is_absolute() else repo_root / args.scorecard),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
