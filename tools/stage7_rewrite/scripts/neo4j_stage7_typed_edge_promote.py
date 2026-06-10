#!/usr/bin/env python3
"""Promote Stage7 generic Neo4j staging edges into typed staging edges.

This is staging-only. It reads `STAGE7_EDGE(predicate=...)` relationships within
one `Stage7Staging` run and MERGEs typed relationships with a separate
`typed_run_id`. It never touches production labels or deletes generic edges.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests


DEFAULT_NEO4J_URI = "http://127.0.0.1:7474"
DEFAULT_RUN_ID = "stage7_qwen3_20260514"
DEFAULT_TYPED_RUN_ID = "stage7_qwen3_typed_20260514"
DEFAULT_OUT_DIR = Path("reports/neo4j_stage7_typed_edges_20260514")
CONFIRM_TOKEN = "ENABLE_NEO4J_TYPED_EDGE_WRITE"

PREDICATE_TO_TYPE = {
    "ARTICLE_MENTIONS_ENTITY": "MENTIONS",
    "ARTICLE_REPORTS_EVENT": "REPORTS",
    "PERFORMS_AT": "PERFORMS_AT",
    "B2B_WITH": "B2B_WITH",
    "HELD_AT": "HELD_AT",
    "LOCATED_IN": "LOCATED_IN",
    "ORGANIZED_BY": "ORGANIZED_BY",
    "PART_OF": "PART_OF",
}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def require_local_neo4j(uri: str) -> None:
    parsed = urlparse(uri)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError(f"Neo4j URI must be local for typed-edge staging promotion: {uri}")


def neo4j_commit(neo4j_uri: str, database: str, statements: list[dict[str, Any]]) -> dict[str, Any]:
    response = requests.post(
        f"{neo4j_uri.rstrip('/')}/db/{database}/tx/commit",
        json={"statements": statements},
        timeout=120,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Neo4j commit failed {response.status_code}: {response.text[:500]}")
    data = response.json()
    if data.get("errors"):
        raise RuntimeError(f"Neo4j returned errors: {json.dumps(data['errors'][:3], ensure_ascii=False)}")
    return data


def predicate_counts(neo4j_uri: str, database: str, run_id: str) -> list[dict[str, Any]]:
    data = neo4j_commit(
        neo4j_uri,
        database,
        [
            {
                "statement": (
                    "MATCH (:Stage7Staging {run_id:$run_id})-[r:STAGE7_EDGE {run_id:$run_id}]->(:Stage7Staging {run_id:$run_id}) "
                    "RETURN r.predicate AS predicate, count(r) AS count ORDER BY count DESC"
                ),
                "parameters": {"run_id": run_id},
            }
        ],
    )
    rows = []
    for item in ((data.get("results") or [{}])[0].get("data") or []):
        row = item.get("row") or []
        rows.append({"predicate": row[0], "count": int(row[1])})
    return rows


def typed_counts(neo4j_uri: str, database: str, typed_run_id: str) -> list[dict[str, Any]]:
    statements = []
    for rel_type in sorted(set(PREDICATE_TO_TYPE.values())):
        statements.append(
            {
                "statement": f"MATCH ()-[r:{rel_type} {{typed_run_id:$typed_run_id}}]->() RETURN '{rel_type}' AS type, count(r) AS count",
                "parameters": {"typed_run_id": typed_run_id},
            }
        )
    data = neo4j_commit(neo4j_uri, database, statements)
    rows = []
    for result in data.get("results") or []:
        for item in result.get("data") or []:
            row = item.get("row") or []
            rows.append({"type": row[0], "count": int(row[1])})
    return rows


def promotion_query(rel_type: str) -> str:
    if rel_type not in set(PREDICATE_TO_TYPE.values()):
        raise ValueError(f"Unsupported relationship type: {rel_type}")
    return (
        "MATCH (s:Stage7Staging {run_id:$run_id})-[r:STAGE7_EDGE {run_id:$run_id}]->(o:Stage7Staging {run_id:$run_id}) "
        "WHERE r.predicate = $predicate AND r.typed_edge_run_id IS NULL "
        "WITH s, r, o LIMIT $batch_size "
        f"MERGE (s)-[t:{rel_type} {{edge_id: r.edge_id}}]->(o) "
        "SET t.run_id = r.run_id, "
        "    t.typed_run_id = $typed_run_id, "
        "    t.source_edge_id = r.edge_id, "
        "    t.predicate = r.predicate, "
        "    t.article_uid = r.article_uid, "
        "    t.source_account = r.source_account, "
        "    t.confidence = r.confidence, "
        "    t.evidence_count = r.evidence_count, "
        "    t.evidence_text = r.evidence_text, "
        "    t.promoted_at = $promoted_at, "
        "    r.typed_edge_run_id = $typed_run_id "
        "RETURN count(t) AS promoted"
    )


def promote_one_batch(
    neo4j_uri: str,
    database: str,
    run_id: str,
    typed_run_id: str,
    predicate: str,
    batch_size: int,
) -> int:
    rel_type = PREDICATE_TO_TYPE[predicate]
    data = neo4j_commit(
        neo4j_uri,
        database,
        [
            {
                "statement": promotion_query(rel_type),
                "parameters": {
                    "run_id": run_id,
                    "typed_run_id": typed_run_id,
                    "predicate": predicate,
                    "batch_size": batch_size,
                    "promoted_at": now_iso(),
                },
            }
        ],
    )
    rows = ((data.get("results") or [{}])[0].get("data") or [])
    return int((rows[0].get("row") or [0])[0]) if rows else 0


def promote(
    neo4j_uri: str,
    database: str,
    run_id: str,
    typed_run_id: str,
    limit: int,
    batch_size: int,
) -> dict[str, Any]:
    promoted_by_predicate: dict[str, int] = {}
    remaining_limit = limit if limit > 0 else None
    for predicate in PREDICATE_TO_TYPE:
        total = 0
        while True:
            if remaining_limit is not None and remaining_limit <= 0:
                break
            this_batch = min(batch_size, remaining_limit) if remaining_limit is not None else batch_size
            count = promote_one_batch(neo4j_uri, database, run_id, typed_run_id, predicate, this_batch)
            if count <= 0:
                break
            total += count
            if remaining_limit is not None:
                remaining_limit -= count
            if count < this_batch:
                break
        if total:
            promoted_by_predicate[predicate] = total
        if remaining_limit is not None and remaining_limit <= 0:
            break
    return {"promoted_by_predicate": promoted_by_predicate, "promoted_total": sum(promoted_by_predicate.values())}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Neo4j Stage7 Typed Edge Promotion",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- mode: `{report['mode']}`",
        f"- run_id: `{report['run_id']}`",
        f"- typed_run_id: `{report['typed_run_id']}`",
        f"- ok: `{report['ok']}`",
        f"- promoted_total: `{report.get('promotion', {}).get('promoted_total', 0)}`",
        "",
        "## Generic Predicate Counts",
        "",
    ]
    for row in report["before_generic_counts"]:
        lines.append(f"- `{row['predicate']}`: {row['count']}")
    lines.extend(["", "## Typed Counts", ""])
    for row in report["after_typed_counts"]:
        if row["count"]:
            lines.append(f"- `{row['type']}`: {row['count']}")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Staging-only: requires `Stage7Staging` nodes and exact `run_id`.",
            "- Generic `STAGE7_EDGE` relationships are retained for rollback.",
            "- No production labels, consumer publish, D: scan, paid API, or Qdrant mutation.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> dict[str, Any]:
    require_local_neo4j(args.neo4j_uri)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    before = predicate_counts(args.neo4j_uri, args.neo4j_database, args.run_id)
    promotion_result = {"promoted_by_predicate": {}, "promoted_total": 0}
    if args.mode in {"canary", "promote"}:
        if args.confirm_token != CONFIRM_TOKEN:
            raise ValueError(f"{args.mode} requires --confirm-token {CONFIRM_TOKEN}")
        limit = args.limit if args.mode == "canary" else 0
        promotion_result = promote(
            args.neo4j_uri,
            args.neo4j_database,
            args.run_id,
            args.typed_run_id,
            limit=limit,
            batch_size=args.batch_size,
        )
    after = typed_counts(args.neo4j_uri, args.neo4j_database, args.typed_run_id)
    report = {
        "schema_version": "stage7_neo4j_typed_edge_promotion.v1",
        "generated_at": now_iso(),
        "mode": args.mode,
        "ok": True,
        "neo4j_uri": args.neo4j_uri,
        "neo4j_database": args.neo4j_database,
        "run_id": args.run_id,
        "typed_run_id": args.typed_run_id,
        "limit": args.limit,
        "batch_size": args.batch_size,
        "predicate_to_type": PREDICATE_TO_TYPE,
        "before_generic_counts": before,
        "promotion": promotion_result,
        "after_typed_counts": after,
    }
    write_json(args.out_dir / "neo4j_stage7_typed_edge_promotion.json", report)
    write_markdown(args.out_dir / "neo4j_stage7_typed_edge_promotion.md", report)
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["dry-run", "canary", "promote", "status"], default="dry-run")
    parser.add_argument("--neo4j-uri", default=DEFAULT_NEO4J_URI)
    parser.add_argument("--neo4j-database", default="neo4j")
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--typed-run-id", default=DEFAULT_TYPED_RUN_ID)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--confirm-token", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = run(args)
    print(
        json.dumps(
            {
                "ok": report["ok"],
                "mode": report["mode"],
                "promoted_total": report["promotion"]["promoted_total"],
                "report": str(args.out_dir / "neo4j_stage7_typed_edge_promotion.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
