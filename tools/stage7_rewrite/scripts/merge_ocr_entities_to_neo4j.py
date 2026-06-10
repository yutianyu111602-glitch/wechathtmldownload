#!/usr/bin/env python3
"""Build a PRD-13 Neo4j dry-run merge plan for OCR entities.

Default mode is dry-run and performs no mutation. Apply mode is intentionally
guarded by a confirmation token and remains staging-only.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib import parse, request


DEFAULT_OCR_ENTITIES = Path("reports/ocr_entity_extraction_20260515/ocr_entities.jsonl")
DEFAULT_OUT_DIR = Path("reports/ocr_entity_merge_20260515")
DEFAULT_NEO4J_URI = "http://127.0.0.1:7474"
DEFAULT_REVIEW_PACKET = Path("reports/ocr_entity_merge_review_packet_20260517/ocr_entity_merge_review_packet.json")
CONFIRM_TOKEN = "ENABLE_NEO4J_OCR_ENTITY_STAGING_WRITE"
SCHEMA_VERSION = "stage7_ocr_entity_neo4j_merge.v1"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def reject_broad_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").rstrip("/").lower()
    if raw in {"d:", "d:/", "/mnt/d", "/mnt/d/"} or raw.startswith("d:/ddownload") or raw.startswith("d:/aidata"):
        raise ValueError(f"{label} refuses broad D root: {path}")


def require_local_neo4j(uri: str) -> None:
    parsed = parse.urlparse(uri)
    if parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError(f"Neo4j URI must be local for OCR entity staging: {uri}")


def first_text(value: Any) -> str:
    return str(value or "").strip()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_broad_d_path(path, "ocr_entities")
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                row = json.loads(stripped)
                if isinstance(row, dict):
                    rows.append(row)
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def read_json(path: Path) -> dict[str, Any]:
    reject_broad_d_path(path, "json")
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    return value if isinstance(value, dict) else {}


def valid_entity(row: dict[str, Any]) -> bool:
    return (
        first_text(row.get("source")) == "ocr_poster"
        and bool(first_text(row.get("ocr_entity_id")))
        and bool(first_text(row.get("entity_type")))
        and bool(first_text(row.get("entity_name")))
        and bool(row.get("staging_only"))
    )


def merge_key(row: dict[str, Any]) -> str:
    return f"ocr_poster:{first_text(row.get('entity_type')).casefold()}:{first_text(row.get('entity_name')).casefold()}"


def merge_plan_row(row: dict[str, Any], run_id: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION + ".plan_row",
        "run_id": run_id,
        "ocr_entity_id": first_text(row.get("ocr_entity_id")),
        "merge_key": merge_key(row),
        "entity_type": first_text(row.get("entity_type")),
        "entity_name": first_text(row.get("entity_name")),
        "source_article_uid": first_text(row.get("source_article_uid")),
        "source_account": first_text(row.get("source_account")),
        "source_poster_ocr_path": first_text(row.get("source_poster_ocr_path")),
        "confidence": float(row.get("confidence") or 0.0),
        "staging_labels": ["Stage7Staging", "OcrPosterEntity"],
        "mutation_status": "dry_run_only",
    }


def neo4j_commit(uri: str, database: str, statements: list[dict[str, Any]]) -> dict[str, Any]:
    payload = json.dumps({"statements": statements}, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        f"{uri.rstrip('/')}/db/{database}/tx/commit",
        data=payload,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def staging_write_statement(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "statement": (
            "UNWIND $rows AS row "
            "MERGE (n:Stage7Staging:OcrPosterEntity {merge_key: row.merge_key}) "
            "SET n.run_id = row.run_id, n.ocr_entity_id = row.ocr_entity_id, "
            "    n.entity_type = row.entity_type, n.entity_name = row.entity_name, "
            "    n.source_article_uid = row.source_article_uid, n.source_account = row.source_account, "
            "    n.source_poster_ocr_path = row.source_poster_ocr_path, n.confidence = row.confidence, "
            "    n.staging_only = true, n.mutation_status = 'staging_applied', n.updated_at = datetime()"
        ),
        "parameters": {"rows": rows},
    }


def rollback_statements(run_id: str) -> list[dict[str, Any]]:
    return [
        {
            "statement": "MATCH (n:Stage7Staging:OcrPosterEntity {run_id:$run_id}) DETACH DELETE n",
            "parameters": {"run_id": run_id},
        }
    ]


def verification_statements(run_id: str) -> list[dict[str, Any]]:
    return [
        {
            "statement": "MATCH (n:Stage7Staging:OcrPosterEntity {run_id:$run_id}) RETURN count(n)",
            "parameters": {"run_id": run_id},
        },
        {
            "statement": "MATCH (n:OcrPosterEntity {run_id:$run_id}) RETURN count(n)",
            "parameters": {"run_id": run_id},
        },
        {
            "statement": (
                "MATCH (n:Stage7Staging:OcrPosterEntity {run_id:$run_id}) "
                "WHERE coalesce(n.staging_only, false) <> true RETURN count(n)"
            ),
            "parameters": {"run_id": run_id},
        },
        {
            "statement": (
                "MATCH (n:Stage7Staging:OcrPosterEntity {run_id:$run_id}) "
                "RETURN n.merge_key, n.entity_type, n.entity_name ORDER BY n.merge_key LIMIT 10"
            ),
            "parameters": {"run_id": run_id},
        },
    ]


def query_count(result: dict[str, Any], index: int) -> int:
    return int(result["results"][index]["data"][0]["row"][0])


def verify_staging(neo4j_uri: str, database: str, run_id: str, expected: int) -> dict[str, Any]:
    result = neo4j_commit(neo4j_uri, database, verification_statements(run_id))
    errors = result.get("errors") or []
    counts = {
        "staging_ocr_poster_entities": 0 if errors else query_count(result, 0),
        "all_ocr_poster_entities_with_run_id": 0 if errors else query_count(result, 1),
        "non_staging_only_nodes": 0 if errors else query_count(result, 2),
    }
    samples = [] if errors else [item["row"] for item in result["results"][3]["data"]]
    return {
        "ok": not errors and counts["staging_ocr_poster_entities"] == expected and counts["non_staging_only_nodes"] == 0,
        "expected_nodes": expected,
        "counts": counts,
        "samples": samples,
        "neo4j_result_errors": errors,
    }


def review_packet_accepts_apply(review_path: Path, run_id: str, plan_rows: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    review = read_json(review_path)
    blockers: list[str] = []
    if review.get("decision") != "ocr_entity_merge_review_accepted_for_staging" or not review.get("ok"):
        blockers.append("review packet is not accepted for staging")
    if str(review.get("run_id") or "") != run_id:
        blockers.append("review packet run_id does not match apply run_id")
    if int(review.get("accepted_plan_rows") or 0) != len(plan_rows):
        blockers.append("review packet accepted_plan_rows does not match apply rows")
    blockers.extend(str(item) for item in (review.get("blockers") or []))
    return not blockers, list(dict.fromkeys(blockers))


def build_merge(args: argparse.Namespace) -> dict[str, Any]:
    require_local_neo4j(args.neo4j_uri)
    reject_broad_d_path(args.out_dir, "out_dir")
    if args.mode == "apply" and args.confirm_token != CONFIRM_TOKEN:
        raise SystemExit(f"--confirm-token {CONFIRM_TOKEN} required for OCR entity staging apply")

    source_rows = read_jsonl(args.ocr_entities)
    skipped: Counter[str] = Counter()
    plan_rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in source_rows:
        if not valid_entity(row):
            skipped["invalid_entity_row"] += 1
            continue
        plan = merge_plan_row(row, args.neo4j_run_id)
        if plan["merge_key"] in seen:
            skipped["duplicate_merge_key"] += 1
            continue
        seen.add(plan["merge_key"])
        plan_rows.append(plan)

    type_counts = Counter(row["entity_type"] for row in plan_rows)
    mutation_executed = False
    nodes_written = 0
    verification: dict[str, Any] | None = None
    neo4j_result = None
    review_blockers: list[str] = []
    if args.mode == "rollback":
        neo4j_result = neo4j_commit(args.neo4j_uri, args.database, rollback_statements(args.neo4j_run_id))
        mutation_executed = True
        verification = verify_staging(args.neo4j_uri, args.database, args.neo4j_run_id, 0)
    elif args.mode == "apply" and plan_rows:
        review_packet = getattr(args, "review_packet", DEFAULT_REVIEW_PACKET)
        accepted, review_blockers = review_packet_accepts_apply(review_packet, args.neo4j_run_id, plan_rows)
        if not accepted:
            raise SystemExit(f"review packet is not accepted for apply: {review_blockers}")
        neo4j_result = neo4j_commit(args.neo4j_uri, args.database, [staging_write_statement(plan_rows)])
        errors = (neo4j_result or {}).get("errors") or []
        if errors:
            raise SystemExit(json.dumps(errors[:3], ensure_ascii=False))
        mutation_executed = True
        nodes_written = len(plan_rows)
        verification = verify_staging(args.neo4j_uri, args.database, args.neo4j_run_id, len(plan_rows))

    if args.mode == "apply" and mutation_executed:
        decision = "ocr_entity_merge_staging_written"
    elif args.mode == "rollback":
        decision = "ocr_entity_merge_staging_rollback_executed"
    else:
        decision = "ocr_entity_merge_dry_run_ready" if plan_rows else "ocr_entity_merge_empty"
    args.out_dir.mkdir(parents=True, exist_ok=True)
    plan_path = args.out_dir / "ocr_entity_merge_plan.jsonl"
    write_jsonl(plan_path, plan_rows)
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": decision,
        "mode": args.mode,
        "run_id": args.neo4j_run_id,
        "ocr_entities": str(args.ocr_entities),
        "plan_path": str(plan_path),
        "neo4j_uri": args.neo4j_uri,
        "database": args.database,
        "entities_seen": len(source_rows),
        "would_merge_entities": len(plan_rows),
        "nodes_written": nodes_written,
        "mutation_executed": mutation_executed,
        "review_packet": str(getattr(args, "review_packet", DEFAULT_REVIEW_PACKET)),
        "review_blockers": review_blockers,
        "verification": verification,
        "neo4j_result_errors": (neo4j_result or {}).get("errors") if neo4j_result else None,
        "entity_type_counts": dict(type_counts),
        "skipped": dict(skipped),
        "rollback_command": (
            f"python scripts\\merge_ocr_entities_to_neo4j.py --mode rollback "
            f"--neo4j-run-id {args.neo4j_run_id} --confirm-token {CONFIRM_TOKEN}"
        ),
        "safety": [
            "dry_run_default",
            "staging_only",
            "confirm_token_required_for_mutation",
            "no_production_labels",
            "no_publish",
            "no_d_scan",
            "no_paid_api",
        ],
    }
    write_json(args.out_dir / "ocr_entity_merge_report.json", report)
    write_markdown(args.out_dir / "ocr_entity_merge_report.md", report)
    print(json.dumps({"ok": True, "decision": decision, "would_merge_entities": len(plan_rows), "nodes_written": nodes_written, "report": str(args.out_dir / "ocr_entity_merge_report.json")}, ensure_ascii=False, indent=2))
    return report


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# PRD-13 OCR Entity Neo4j Merge Dry-run",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- decision: `{report['decision']}`",
        f"- mode: `{report['mode']}`",
        f"- run_id: `{report['run_id']}`",
        f"- entities_seen: `{report['entities_seen']}`",
        f"- would_merge_entities: `{report['would_merge_entities']}`",
        f"- nodes_written: `{report.get('nodes_written')}`",
        f"- mutation_executed: `{report['mutation_executed']}`",
        f"- plan_path: `{report['plan_path']}`",
        "",
        "## Entity Types",
        "",
    ]
    for key, value in sorted(report["entity_type_counts"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Skipped", ""])
    for key, value in sorted(report["skipped"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Dry-run default.",
            "- Staging labels only; no production labels or publish.",
            "- No mutation in dry-run mode.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ocr-entities", type=Path, default=DEFAULT_OCR_ENTITIES)
    parser.add_argument("--neo4j-run-id", default="stage7_qwen3_20260514")
    parser.add_argument("--mode", choices=["dry-run", "apply", "rollback"], default="dry-run")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--neo4j-uri", default=DEFAULT_NEO4J_URI)
    parser.add_argument("--database", default="neo4j")
    parser.add_argument("--review-packet", type=Path, default=DEFAULT_REVIEW_PACKET)
    parser.add_argument("--confirm-token", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    build_merge(parse_args(argv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
