#!/usr/bin/env python3
"""Promote the verified Stage7 Neo4j staging graph to production-read markers.

The current Stage7 graph already keeps type labels such as :Article, :Entity,
and :Event on staging nodes. Promotion therefore uses `promotion_run_id` as the
blue-green marker and never removes type labels during rollback.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests


DEFAULT_NEO4J_URI = "http://127.0.0.1:7474"
DEFAULT_DATABASE = "neo4j"
DEFAULT_STAGING_RUN_ID = "stage7_qwen3_20260514"
DEFAULT_PROMOTION_RUN_ID = "stage7_production_graph_20260515"
DEFAULT_READINESS = Path("reports/graph_promotion_readiness_refresh_20260516/graph_promotion_readiness.json")
DEFAULT_OUT_DIR = Path("reports/graph_production_promotion_20260517")
CONFIRM_TOKEN = "ENABLE_GRAPH_PRODUCTION_PROMOTION"
SCHEMA_VERSION = "stage7_graph_production_promotion.v1"
KINDS = ("article", "entity", "event")
LABELS = {"article": "Article", "entity": "Entity", "event": "Event"}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw in {"d:", "d:/", "/mnt/d", "/mnt/d/"} or raw.startswith("d:/ddownload") or raw.startswith("d:/aidata"):
        raise ValueError(f"{label} refuses broad D root: {path}")


def require_local_neo4j(uri: str) -> None:
    parsed = urlparse(uri)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError(f"Neo4j URI must be local for graph promotion: {uri}")


def read_json(path: Path) -> dict[str, Any]:
    reject_d_path(path, "json")
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    return value if isinstance(value, dict) else {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def neo4j_commit(uri: str, database: str, statements: list[dict[str, Any]]) -> dict[str, Any]:
    require_local_neo4j(uri)
    response = requests.post(
        f"{uri.rstrip('/')}/db/{database}/tx/commit",
        json={"statements": statements},
        timeout=120,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Neo4j request failed {response.status_code}: {response.text[:500]}")
    payload = response.json()
    if payload.get("errors"):
        raise RuntimeError(json.dumps(payload["errors"][:3], ensure_ascii=False))
    return payload


def scalar_values(payload: dict[str, Any]) -> list[int]:
    values: list[int] = []
    for result in payload.get("results") or []:
        data = result.get("data") or []
        row = (data[0].get("row") if data else [0]) or [0]
        values.append(int(row[0] or 0))
    return values


def count_statements(staging_run_id: str, promotion_run_id: str) -> list[dict[str, Any]]:
    statements: list[dict[str, Any]] = []
    for kind, label in LABELS.items():
        statements.append(
            {
                "statement": f"MATCH (n:Stage7Staging:{label} {{run_id:$staging_run_id}}) RETURN count(n)",
                "parameters": {"staging_run_id": staging_run_id},
            }
        )
        statements.append(
            {
                "statement": f"MATCH (n:{label} {{run_id:$staging_run_id}}) RETURN count(n)",
                "parameters": {"staging_run_id": staging_run_id},
            }
        )
        statements.append(
            {
                "statement": f"MATCH (n:{label} {{run_id:$staging_run_id, promotion_run_id:$promotion_run_id}}) RETURN count(n)",
                "parameters": {"staging_run_id": staging_run_id, "promotion_run_id": promotion_run_id},
            }
        )
    return statements


def read_counts(uri: str, database: str, staging_run_id: str, promotion_run_id: str) -> dict[str, dict[str, int]]:
    values = scalar_values(neo4j_commit(uri, database, count_statements(staging_run_id, promotion_run_id)))
    counts: dict[str, dict[str, int]] = {}
    index = 0
    for kind in KINDS:
        counts[kind] = {
            "staging": values[index],
            "typed_label_with_run_id": values[index + 1],
            "promoted": values[index + 2],
        }
        index += 3
    return counts


def promote_statements(staging_run_id: str, promotion_run_id: str) -> list[dict[str, Any]]:
    statements: list[dict[str, Any]] = []
    for label in LABELS.values():
        statements.append(
            {
                "statement": (
                    f"MATCH (n:Stage7Staging:{label} {{run_id:$staging_run_id}}) "
                    f"SET n:{label}, n.promotion_run_id = $promotion_run_id, n.promoted_at = datetime() "
                    "RETURN count(n)"
                ),
                "parameters": {"staging_run_id": staging_run_id, "promotion_run_id": promotion_run_id},
            }
        )
    return statements


def rollback_statements(staging_run_id: str, promotion_run_id: str) -> list[dict[str, Any]]:
    statements: list[dict[str, Any]] = []
    for label in LABELS.values():
        statements.append(
            {
                "statement": (
                    f"MATCH (n:Stage7Staging:{label} {{run_id:$staging_run_id, promotion_run_id:$promotion_run_id}}) "
                    "REMOVE n.promotion_run_id, n.promoted_at RETURN count(n)"
                ),
                "parameters": {"staging_run_id": staging_run_id, "promotion_run_id": promotion_run_id},
            }
        )
    return statements


def mutation_counts(payload: dict[str, Any]) -> dict[str, int]:
    values = scalar_values(payload)
    return {kind: values[index] if index < len(values) else 0 for index, kind in enumerate(KINDS)}


def batched_mutation_statement(kind: str, mode: str) -> dict[str, Any]:
    label = LABELS[kind]
    if mode == "promote":
        statement = (
            f"MATCH (n:Stage7Staging:{label} {{run_id:$staging_run_id}}) "
            "WHERE coalesce(n.promotion_run_id, '') <> $promotion_run_id "
            "WITH n LIMIT $batch_size "
            f"SET n:{label}, n.promotion_run_id = $promotion_run_id, n.promoted_at = datetime() "
            "RETURN count(n)"
        )
    elif mode == "rollback":
        statement = (
            f"MATCH (n:Stage7Staging:{label} {{run_id:$staging_run_id, promotion_run_id:$promotion_run_id}}) "
            "WITH n LIMIT $batch_size "
            "REMOVE n.promotion_run_id, n.promoted_at RETURN count(n)"
        )
    else:
        raise ValueError(f"unsupported batched mutation mode: {mode}")
    return {"statement": statement, "parameters": {}}


def execute_batched_mutation(
    uri: str,
    database: str,
    *,
    mode: str,
    staging_run_id: str,
    promotion_run_id: str,
    batch_size: int,
    min_batch_size: int = 250,
) -> dict[str, Any]:
    totals = {kind: 0 for kind in KINDS}
    batches = {kind: 0 for kind in KINDS}
    batch_sizes = {kind: max(1, int(batch_size)) for kind in KINDS}
    errors: list[str] = []

    for kind in KINDS:
        current_batch = max(1, int(batch_size))
        while True:
            statement = batched_mutation_statement(kind, mode)
            statement["parameters"] = {
                "staging_run_id": staging_run_id,
                "promotion_run_id": promotion_run_id,
                "batch_size": current_batch,
            }
            try:
                payload = neo4j_commit(uri, database, [statement])
            except RuntimeError as exc:
                text = str(exc)
                if "MemoryPoolOutOfMemoryError" in text and current_batch > min_batch_size:
                    current_batch = max(min_batch_size, current_batch // 2)
                    errors.append(f"{kind}: reduced batch_size to {current_batch} after Neo4j OOM")
                    continue
                raise
            changed = scalar_values(payload)[0]
            if changed <= 0:
                batch_sizes[kind] = current_batch
                break
            totals[kind] += changed
            batches[kind] += 1
            if changed < current_batch:
                batch_sizes[kind] = current_batch
                break
    return {"changed_counts": totals, "batches": batches, "batch_sizes": batch_sizes, "warnings": errors}


def validate_counts(counts: dict[str, dict[str, int]], *, expect_promoted: bool) -> dict[str, Any]:
    blockers: list[str] = []
    for kind, row in counts.items():
        if row["staging"] <= 0:
            blockers.append(f"{kind} staging count is zero")
        if row["typed_label_with_run_id"] < row["staging"]:
            blockers.append(f"{kind} type-label count is below staging count")
        if expect_promoted and row["promoted"] != row["staging"]:
            blockers.append(f"{kind} promoted count does not match staging count")
        if not expect_promoted and row["promoted"] != 0:
            blockers.append(f"{kind} promoted count is not zero")
    return {"ok": not blockers, "blockers": blockers}


def readiness_allows(readiness: dict[str, Any]) -> tuple[bool, list[str]]:
    if not readiness:
        return False, ["graph promotion readiness report is missing"]
    blockers = list(readiness.get("blockers") or [])
    if readiness.get("decision") != "graph_promotion_ready" or not readiness.get("promotion_allowed"):
        blockers.append("graph promotion readiness is not green")
    return not blockers, list(dict.fromkeys(str(item) for item in blockers))


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    reject_d_path(args.out_dir, "out_dir")
    require_local_neo4j(args.neo4j_uri)
    readiness = read_json(args.readiness)
    ready, readiness_blockers = readiness_allows(readiness)
    before_counts = read_counts(args.neo4j_uri, args.database, args.staging_run_id, args.promotion_run_id)
    mutation_executed = False
    mutation_result: dict[str, Any] | None = None
    mutated_counts: dict[str, int] = {}

    if args.mode in {"promote", "rollback"} and args.confirm_token != CONFIRM_TOKEN:
        raise SystemExit(f"--confirm-token {CONFIRM_TOKEN} required for graph production promotion mutations")
    if args.mode == "promote":
        if not ready:
            raise SystemExit(f"graph promotion readiness blocked: {readiness_blockers}")
        mutation_result = execute_batched_mutation(
            args.neo4j_uri,
            args.database,
            mode="promote",
            staging_run_id=args.staging_run_id,
            promotion_run_id=args.promotion_run_id,
            batch_size=args.batch_size,
        )
        mutation_executed = True
        mutated_counts = dict(mutation_result["changed_counts"])
    elif args.mode == "rollback":
        mutation_result = execute_batched_mutation(
            args.neo4j_uri,
            args.database,
            mode="rollback",
            staging_run_id=args.staging_run_id,
            promotion_run_id=args.promotion_run_id,
            batch_size=args.batch_size,
        )
        mutation_executed = True
        mutated_counts = dict(mutation_result["changed_counts"])

    after_counts = read_counts(args.neo4j_uri, args.database, args.staging_run_id, args.promotion_run_id)
    expect_promoted = args.mode in {"promote", "verify"}
    verification = validate_counts(after_counts, expect_promoted=expect_promoted)

    if args.mode == "dry-run":
        decision = "graph_production_promotion_dry_run_ready" if ready and verification["ok"] else "graph_production_promotion_dry_run_blocked"
    elif args.mode == "promote":
        decision = "graph_production_promotion_written" if verification["ok"] else "graph_production_promotion_write_failed_verification"
    elif args.mode == "rollback":
        decision = "graph_production_promotion_rollback_executed" if verification["ok"] else "graph_production_promotion_rollback_failed_verification"
    else:
        decision = "graph_production_promotion_verified" if verification["ok"] else "graph_production_promotion_verify_failed"

    blockers = [*readiness_blockers, *verification["blockers"]]
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": (decision.endswith("_ready") or decision.endswith("_written") or decision.endswith("_executed") or decision.endswith("_verified"))
        and not blockers,
        "decision": decision,
        "mode": args.mode,
        "staging_run_id": args.staging_run_id,
        "promotion_run_id": args.promotion_run_id,
        "readiness_path": str(args.readiness),
        "readiness_decision": readiness.get("decision"),
        "readiness_promotion_allowed": readiness.get("promotion_allowed"),
        "before_counts": before_counts,
        "after_counts": after_counts,
        "mutation_executed": mutation_executed,
        "mutated_counts": mutated_counts,
        "mutation_batches": (mutation_result or {}).get("batches") if isinstance(mutation_result, dict) else None,
        "mutation_batch_sizes": (mutation_result or {}).get("batch_sizes") if isinstance(mutation_result, dict) else None,
        "mutation_warnings": (mutation_result or {}).get("warnings") if isinstance(mutation_result, dict) else [],
        "verification": verification,
        "blockers": list(dict.fromkeys(blockers)),
        "rollback_command": (
            f"python scripts\\promote_graph_to_production.py --mode rollback "
            f"--staging-run-id {args.staging_run_id} --promotion-run-id {args.promotion_run_id} "
            f"--confirm-token {CONFIRM_TOKEN} --out-dir {args.out_dir}"
        ),
        "safety": {
            "local_neo4j_only": True,
            "dry_run_default": True,
            "confirm_token_required_for_mutation": True,
            "type_labels_removed_on_rollback": False,
            "qdrant_write_executed": False,
            "mem0_write_executed": False,
            "paid_api_used": False,
            "d_scan_executed": False,
            "publish_executed": False,
        },
        "writes": "local_neo4j_production_markers" if mutation_executed else "reports_only",
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.out_dir / "promotion_report.json", report)
    write_markdown(args.out_dir / "promotion_report.md", report)
    write_json(args.out_dir / f"promotion_report_{args.mode}.json", report)
    write_markdown(args.out_dir / f"promotion_report_{args.mode}.md", report)
    return report


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Graph Production Promotion",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- decision: `{report['decision']}`",
        f"- mode: `{report['mode']}`",
        f"- staging_run_id: `{report['staging_run_id']}`",
        f"- promotion_run_id: `{report['promotion_run_id']}`",
        f"- mutation_executed: `{report['mutation_executed']}`",
        "",
        "## Counts",
        "",
    ]
    for kind in KINDS:
        row = report["after_counts"][kind]
        lines.append(
            f"- `{kind}` staging `{row['staging']}` typed_label `{row['typed_label_with_run_id']}` promoted `{row['promoted']}`"
        )
    lines.extend(["", "## Blockers", ""])
    if report["blockers"]:
        lines.extend(f"- {item}" for item in report["blockers"])
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Local Neo4j only.",
            "- Rollback removes promotion markers only; it does not remove Article/Entity/Event labels.",
            "- No Qdrant, mem0, paid API, D: scan, publish, or deploy.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["dry-run", "promote", "verify", "rollback"], default="dry-run")
    parser.add_argument("--neo4j-uri", default=DEFAULT_NEO4J_URI)
    parser.add_argument("--database", default=DEFAULT_DATABASE)
    parser.add_argument("--staging-run-id", default=DEFAULT_STAGING_RUN_ID)
    parser.add_argument("--promotion-run-id", default=DEFAULT_PROMOTION_RUN_ID)
    parser.add_argument("--readiness", type=Path, default=DEFAULT_READINESS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--confirm-token", default="")
    parser.add_argument("--batch-size", type=int, default=5000)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_report(args)
    print(
        json.dumps(
            {
                "ok": report["ok"],
                "decision": report["decision"],
                "mode": report["mode"],
                "mutated_counts": report["mutated_counts"],
                "blockers": report["blockers"],
                "report": str(args.out_dir / "promotion_report.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
