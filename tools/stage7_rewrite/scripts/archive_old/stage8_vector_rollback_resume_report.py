"""Build a rollback/resume report from a Stage8 vector gate run.

This script is read-only with respect to vector stores and databases. It reads a
production-gate dry-run/canary directory and writes a compact evidence report
describing what can be resumed, what can be rolled back, and what still blocks
production mode.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stage7.atomic_io import safe_read_json


PASSLIKE_STATUSES = {"PASS", "PASS_PREVIEW", "SKIPPED_NO_GRAPH", "SKIPPED"}
PRODUCTION_CONFIRM_TOKEN = "ENABLE_PRODUCTION_VECTOR_WRITE_93K"


def read_jsonl_count(path: Path) -> int:
    if not path.exists():
        return 0
    count = 0
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                count += 1
    return count


def load_plan(gate_dir: Path) -> dict[str, Any]:
    plan = safe_read_json(gate_dir / "production_gate_plan.json", {})
    return plan if isinstance(plan, dict) else {}


def load_canary_summary(gate_dir: Path, plan: dict[str, Any]) -> dict[str, Any]:
    embedded = plan.get("canary_summary")
    if isinstance(embedded, dict):
        return embedded
    summary = safe_read_json(gate_dir / "gate_canary_summary.json", {})
    return summary if isinstance(summary, dict) else {}


def strategy_statuses(canary_summary: dict[str, Any]) -> list[dict[str, str]]:
    rows = []
    for item in canary_summary.get("strategy_results") or []:
        if isinstance(item, dict):
            rows.append({
                "name": str(item.get("name") or ""),
                "status": str(item.get("status") or ""),
            })
    return rows


def is_strategy_result_passlike(item: dict[str, Any]) -> bool:
    status = str(item.get("status") or "")
    if status in PASSLIKE_STATUSES:
        return True
    if status != "WARN_DUPLICATE_EQUIV":
        return False
    details = item.get("details") or {}
    return (
        float(details.get("equivalent_hit_rate") or 0.0) >= 1.0
        and int(details.get("equivalent_hit") or 0) == int(details.get("tested") or -1)
        and not (details.get("misses") or [])
    )


def is_canary_green(canary_summary: dict[str, Any]) -> bool:
    if not canary_summary:
        return False
    embedding_stats = canary_summary.get("embedding_stats") or {}
    if int(embedding_stats.get("failed") or 0) > 0:
        return False
    results = [item for item in canary_summary.get("strategy_results") or [] if isinstance(item, dict)]
    return bool(results) and all(is_strategy_result_passlike(item) for item in results)


def qdrant_cleanup_status(canary_summary: dict[str, Any]) -> dict[str, Any]:
    for item in canary_summary.get("strategy_results") or []:
        if not isinstance(item, dict):
            continue
        if item.get("name") == "qdrant_test_cleanup":
            details = item.get("details") or {}
            return {
                "status": item.get("status"),
                "deleted_collections": details.get("deleted_collections") or [],
            }
    return {"status": "", "deleted_collections": []}


def neo4j_write_status(canary_summary: dict[str, Any]) -> dict[str, Any]:
    for item in canary_summary.get("strategy_results") or []:
        if not isinstance(item, dict):
            continue
        if item.get("name") == "neo4j_canary_write":
            details = item.get("details") or {}
            return {
                "status": item.get("status"),
                "written_nodes": details.get("written_nodes"),
                "written_edges": details.get("written_edges"),
                "cleaned_up": details.get("cleaned_up"),
                "batch_size": details.get("batch_size"),
                "node_batches": details.get("node_batches"),
                "edge_batches": details.get("edge_batches"),
                "cleanup_batches": details.get("cleanup_batches"),
            }
    return {"status": "", "cleaned_up": False}


def build_report(gate_dir: Path) -> dict[str, Any]:
    gate_dir = gate_dir.resolve()
    plan = load_plan(gate_dir)
    canary_summary = load_canary_summary(gate_dir, plan)
    jobs_path = Path(str(plan.get("jobs_path") or gate_dir / "vector_jobs.gate_plan.jsonl"))
    embeddings_path = gate_dir / "vector_embeddings.gate_canary.jsonl"
    failures_path = gate_dir / "vector_failures.gate_canary.jsonl"
    embedding_stats = canary_summary.get("embedding_stats") or {}
    strategy_rows = strategy_statuses(canary_summary)
    canary_green = is_canary_green(canary_summary)
    jobs_jsonl_count = read_jsonl_count(jobs_path)
    embeddings_jsonl_count = read_jsonl_count(embeddings_path)
    failures_jsonl_count = read_jsonl_count(failures_path)
    writer_path = SCRIPT_DIR / "stage8_vector_production_writer.py"
    writer_available = writer_path.exists()
    expected_jobs = int(plan.get("job_count") or 0)
    production_blockers: list[str] = []
    if not writer_available:
        production_blockers.append("dedicated production writer is not implemented")
    if not canary_green:
        production_blockers.append("gate canary is not green")
    if int(plan.get("quarantined_articles") or 0) != 0:
        production_blockers.append("Tier D quarantine is nonzero")
    if expected_jobs <= 0:
        production_blockers.append("gate has no vector jobs")
    if jobs_jsonl_count != expected_jobs:
        production_blockers.append(f"jobs JSONL count mismatch: {jobs_jsonl_count} != {expected_jobs}")
    if embeddings_jsonl_count != expected_jobs:
        production_blockers.append(f"embedding count mismatch: {embeddings_jsonl_count} != {expected_jobs}")
    if failures_jsonl_count != 0:
        production_blockers.append(f"embedding failures are present: {failures_jsonl_count}")
    if "192.168.8.234" not in str(plan.get("endpoint") or ""):
        production_blockers.append("endpoint is not the approved Mac LAN endpoint")
    production_ready = not production_blockers
    if production_ready:
        production_blockers.append(f"manual production writer apply requires {PRODUCTION_CONFIRM_TOKEN}")
    return {
        "schema_version": "stage8_vector_rollback_resume_report.v1",
        "gate_dir": str(gate_dir),
        "mode": plan.get("mode", ""),
        "card_template": plan.get("card_template", ""),
        "candidate_cap": plan.get("candidate_cap"),
        "score_profile": plan.get("score_profile", ""),
        "model": plan.get("model", ""),
        "dim": plan.get("dim"),
        "endpoint": plan.get("endpoint", ""),
        "files_parsed": plan.get("files_parsed"),
        "eligible_articles": plan.get("eligible_articles"),
        "quarantined_articles": plan.get("quarantined_articles"),
        "tier_counts": plan.get("tier_counts") or {},
        "job_count": plan.get("job_count"),
        "jobs_jsonl_count": jobs_jsonl_count,
        "embeddings_jsonl_count": embeddings_jsonl_count,
        "failures_jsonl_count": failures_jsonl_count,
        "embedding_stats": embedding_stats,
        "strategy_statuses": strategy_rows,
        "canary_green": canary_green,
        "qdrant_cleanup": qdrant_cleanup_status(canary_summary),
        "neo4j": neo4j_write_status(canary_summary),
        "resume_policy": plan.get("pc_ledger_policy") or {},
        "qdrant_policy": plan.get("qdrant_policy") or {},
        "neo4j_policy": plan.get("neo4j_policy") or {},
        "production_ready": production_ready,
        "production_writer_available": writer_available,
        "production_writer_path": str(writer_path),
        "production_blockers": production_blockers,
        "rollback_order": [
            "stop production writer and freeze new ledger claims",
            "use PC ledger resume key object_kind + object_id + text_sha1 to identify completed and pending vector objects",
            "delete or alias-swap only collections created for the failed production run",
            "delete Neo4j relationships/nodes by production run_id or test run_id before retrying graph writes",
            "resume from ledger rows not marked committed for each target",
        ],
    }


def write_markdown(report: dict[str, Any], out_md: Path) -> None:
    qdrant = report["qdrant_cleanup"]
    neo4j = report["neo4j"]
    lines = [
        "# Stage8 Vector Rollback / Resume Report",
        "",
        f"- gate_dir: `{report['gate_dir']}`",
        f"- mode: `{report['mode']}`",
        f"- strategy: `{report['card_template']} cap{report['candidate_cap']} {report['score_profile']}`",
        f"- endpoint: `{report['endpoint']}` / `{report['model']}` / dim `{report['dim']}`",
        f"- parsed/eligible/quarantine: `{report['files_parsed']}` / `{report['eligible_articles']}` / `{report['quarantined_articles']}`",
        f"- tier_counts: `{json.dumps(report['tier_counts'], ensure_ascii=False, sort_keys=True)}`",
        f"- jobs: plan `{report['job_count']}`, jsonl `{report['jobs_jsonl_count']}`",
        f"- embeddings/failures: `{report['embeddings_jsonl_count']}` / `{report['failures_jsonl_count']}`",
        f"- canary_green: `{report['canary_green']}`",
        f"- production_ready: `{report['production_ready']}`",
        f"- production_writer_available: `{report.get('production_writer_available')}`",
        f"- production_writer_path: `{report.get('production_writer_path')}`",
        "",
        "## Strategy Statuses",
        "",
    ]
    for row in report["strategy_statuses"]:
        lines.append(f"- `{row['name']}`: `{row['status']}`")
    lines.extend([
        "",
        "## Cleanup Evidence",
        "",
        f"- Qdrant cleanup: `{qdrant.get('status')}` collections `{len(qdrant.get('deleted_collections') or [])}`",
        (
            f"- Neo4j: `{neo4j.get('status')}` nodes `{neo4j.get('written_nodes')}` "
            f"edges `{neo4j.get('written_edges')}` cleaned_up `{neo4j.get('cleaned_up')}` "
            f"batch_size `{neo4j.get('batch_size')}`"
        ),
        "",
        "## Resume Policy",
        "",
        f"- ledger_first: `{report['resume_policy'].get('ledger_first')}`",
        f"- resume_key: `{report['resume_policy'].get('resume_key')}`",
        "",
        "## Rollback Order",
        "",
    ])
    for step in report["rollback_order"]:
        lines.append(f"- {step}")
    lines.extend([
        "",
        "## Production Blockers",
        "",
    ])
    for blocker in report["production_blockers"]:
        lines.append(f"- {blocker}")
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gate-dir", required=True)
    parser.add_argument("--out-json", default="")
    parser.add_argument("--out-md", default="")
    args = parser.parse_args(argv)
    gate_dir = Path(args.gate_dir)
    report = build_report(gate_dir)
    out_json = Path(args.out_json) if args.out_json else gate_dir / "rollback_resume_report.json"
    out_md = Path(args.out_md) if args.out_md else gate_dir / "ROLLBACK_RESUME_REPORT.md"
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    write_markdown(report, out_md)
    print(json.dumps({"ok": True, "json": str(out_json), "markdown": str(out_md)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
