"""Stage8 vector production writer.

This is the controlled writer behind the production gate. It is deliberately
separate from ``stage8_vector_production_gate.py``:

- ``preflight`` validates a green gate and writes no stores.
- ``apply`` requires the manual confirmation token and writes resumable
  production targets: PC SQLite ledger, Qdrant staging collections, and Neo4j
  production labels/relationships.

The writer consumes an already green gate directory. It does not start Stage7
extraction and does not use PC-local embedding models.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_stage8_write_strategy_tests as write_tests
import stage8_vector_production_writer_design as writer_design
from stage7.atomic_io import safe_read_json


PRODUCTION_CONFIRM_TOKEN = "ENABLE_PRODUCTION_VECTOR_WRITE_93K"
DEFAULT_PRODUCTION_DB = Path(r"D:\downstream_results\stage7_rewrite\stage8\production\pc_vector_production.sqlite")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{line_no}: {exc}") from exc
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def load_plan(gate_dir: Path) -> dict[str, Any]:
    plan = safe_read_json(gate_dir / "production_gate_plan.json", {})
    return plan if isinstance(plan, dict) else {}


def load_rollback(gate_dir: Path) -> dict[str, Any]:
    rollback = safe_read_json(gate_dir / "rollback_resume_report.json", {})
    return rollback if isinstance(rollback, dict) else {}


def count_jsonl(path: Path) -> int:
    return len(read_jsonl(path))


def embeddings_path(gate_dir: Path) -> Path:
    return gate_dir / "vector_embeddings.gate_canary.jsonl"


def failures_path(gate_dir: Path) -> Path:
    return gate_dir / "vector_failures.gate_canary.jsonl"


def jobs_path(gate_dir: Path, plan: dict[str, Any]) -> Path:
    return Path(str(plan.get("jobs_path") or gate_dir / "vector_jobs.gate_plan.jsonl"))


def build_release_id(plan: dict[str, Any], requested: str | None) -> str:
    if requested:
        return requested
    model = writer_design.safe_name(plan.get("model") or "model")
    dim = plan.get("dim") or "dim"
    count = plan.get("eligible_articles") or plan.get("job_count") or "unknown"
    return f"stage8_vector_{model}_{dim}_{count}_{now_stamp()}"


def qdrant_staging_collections(plan: dict[str, Any], release_id: str) -> dict[str, str]:
    collections = writer_design.collection_names(plan, release_id)
    return dict(collections.get("split_by_kind") or {})


def build_preflight(gate_dir: Path, release_id: str | None = None, confirm_token: str = "") -> dict[str, Any]:
    gate_dir = gate_dir.resolve()
    plan = load_plan(gate_dir)
    rollback = load_rollback(gate_dir)
    release = build_release_id(plan, release_id)
    jobs_count = count_jsonl(jobs_path(gate_dir, plan))
    embedding_count = count_jsonl(embeddings_path(gate_dir))
    failure_count = count_jsonl(failures_path(gate_dir))
    blockers: list[str] = []

    if not plan:
        blockers.append("missing production gate plan")
    if not rollback:
        blockers.append("missing rollback/resume report")
    if not rollback.get("canary_green"):
        blockers.append("gate canary is not green")
    if int(plan.get("quarantined_articles") or 0) != 0:
        blockers.append("gate has quarantined Tier D articles")
    endpoint = str(plan.get("endpoint") or "")
    if "192.168.8.234" not in endpoint:
        blockers.append(f"endpoint is not the approved Mac LAN route: {endpoint}")
    expected_jobs = int(plan.get("job_count") or rollback.get("jobs_jsonl_count") or 0)
    if expected_jobs <= 0:
        blockers.append("gate has no vector jobs")
    if jobs_count != expected_jobs:
        blockers.append(f"jobs JSONL count mismatch: {jobs_count} != {expected_jobs}")
    if embedding_count != expected_jobs:
        blockers.append(f"embedding count mismatch: {embedding_count} != {expected_jobs}")
    if failure_count != 0:
        blockers.append(f"embedding failures are present: {failure_count}")
    if confirm_token != PRODUCTION_CONFIRM_TOKEN:
        blockers.append("missing production confirmation token")

    collections = qdrant_staging_collections(plan, release)
    for name in collections.values():
        if not name.startswith("wechat_prod_"):
            blockers.append(f"qdrant staging collection is not production-prefixed: {name}")
        if name.startswith("wechat_test_"):
            blockers.append(f"qdrant staging collection uses test prefix: {name}")

    return {
        "schema_version": "stage8_vector_production_writer_preflight.v1",
        "gate_dir": str(gate_dir),
        "release_id": release,
        "apply_allowed": not blockers,
        "blockers": blockers,
        "job_count": expected_jobs,
        "jobs_jsonl_count": jobs_count,
        "embedding_count": embedding_count,
        "failure_count": failure_count,
        "endpoint": endpoint,
        "model": plan.get("model"),
        "dim": plan.get("dim"),
        "qdrant_staging_collections": collections,
        "pc_resume_key": "object_kind + object_id + text_sha1",
        "neo4j_run_id": release,
    }


def point_id_for(row: dict[str, Any]) -> str:
    seed = "|".join([
        str(row.get("job_id") or ""),
        str(row.get("object_kind") or ""),
        str(row.get("object_id") or ""),
        str(row.get("text_sha1") or ""),
    ])
    return str(uuid.uuid5(uuid.NAMESPACE_URL, seed))


def qdrant_payload(row: dict[str, Any], release_id: str) -> dict[str, Any]:
    payload = write_tests.qdrant_payload(row)
    payload.update({
        "release_id": release_id,
        "production_stage": "staging",
        "production_writer": "stage8_vector_production_writer.py",
    })
    return payload


def load_graph_rows(gate_dir: Path) -> dict[str, list[dict[str, Any]]]:
    graph_dir = gate_dir / "graph_preview"
    return {
        "nodes": read_jsonl(graph_dir / "nodes.completed.jsonl"),
        "edges": read_jsonl(graph_dir / "edges.jsonl"),
    }


def write_pc_production_ledger(
    db_path: Path,
    embeddings: list[dict[str, Any]],
    graph_rows: dict[str, list[dict[str, Any]]],
    *,
    release_id: str,
) -> dict[str, Any]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS production_runs (
                release_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS vector_objects (
                object_kind TEXT NOT NULL,
                object_id TEXT NOT NULL,
                text_sha1 TEXT NOT NULL,
                article_id TEXT,
                collection_name TEXT,
                model TEXT,
                dim INTEGER,
                endpoint TEXT,
                canonical_text TEXT,
                metadata_json TEXT,
                release_id TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (object_kind, object_id, text_sha1)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS vector_write_ledger (
                target TEXT NOT NULL,
                point_id TEXT NOT NULL,
                object_kind TEXT,
                object_id TEXT,
                collection_name TEXT,
                text_sha1 TEXT,
                status TEXT NOT NULL,
                release_id TEXT,
                payload_json TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (target, point_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS graph_nodes (
                node_id TEXT PRIMARY KEY,
                node_kind TEXT,
                name TEXT,
                type TEXT,
                article_uid TEXT,
                release_id TEXT,
                payload_json TEXT,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS graph_edges (
                edge_id TEXT PRIMARY KEY,
                subject_id TEXT,
                predicate TEXT,
                object_id TEXT,
                article_id TEXT,
                release_id TEXT,
                payload_json TEXT,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute(
            "INSERT INTO production_runs (release_id, status, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(release_id) DO UPDATE SET status=excluded.status, updated_at=excluded.updated_at",
            (release_id, "staging_claimed", now_iso()),
        )
        for row in embeddings:
            payload = qdrant_payload(row, release_id)
            conn.execute("""
                INSERT INTO vector_objects (
                    object_kind, object_id, text_sha1, article_id, collection_name,
                    model, dim, endpoint, canonical_text, metadata_json, release_id, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(object_kind, object_id, text_sha1) DO UPDATE SET
                    article_id=excluded.article_id,
                    collection_name=excluded.collection_name,
                    model=excluded.model,
                    dim=excluded.dim,
                    endpoint=excluded.endpoint,
                    canonical_text=excluded.canonical_text,
                    metadata_json=excluded.metadata_json,
                    release_id=excluded.release_id,
                    updated_at=excluded.updated_at
            """, (
                row.get("object_kind"),
                row.get("object_id"),
                row.get("text_sha1"),
                row.get("article_id"),
                row.get("collection"),
                row.get("model"),
                row.get("dim"),
                row.get("endpoint"),
                row.get("canonical_text", ""),
                json.dumps(row.get("metadata") or {}, ensure_ascii=False),
                release_id,
                now_iso(),
            ))
            conn.execute("""
                INSERT INTO vector_write_ledger (
                    target, point_id, object_kind, object_id, collection_name,
                    text_sha1, status, release_id, payload_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(target, point_id) DO UPDATE SET
                    status=excluded.status,
                    release_id=excluded.release_id,
                    payload_json=excluded.payload_json,
                    updated_at=excluded.updated_at
            """, (
                "pc_ledger",
                payload["point_id"],
                row.get("object_kind"),
                row.get("object_id"),
                row.get("collection"),
                row.get("text_sha1"),
                "claimed",
                release_id,
                json.dumps(payload, ensure_ascii=False),
                now_iso(),
            ))
        for node in graph_rows.get("nodes", []):
            conn.execute("""
                INSERT INTO graph_nodes (
                    node_id, node_kind, name, type, article_uid, release_id, payload_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(node_id) DO UPDATE SET
                    node_kind=excluded.node_kind,
                    name=excluded.name,
                    type=excluded.type,
                    article_uid=excluded.article_uid,
                    release_id=excluded.release_id,
                    payload_json=excluded.payload_json,
                    updated_at=excluded.updated_at
            """, (
                node.get("node_id"),
                node.get("node_kind"),
                node.get("name"),
                node.get("type"),
                node.get("article_uid"),
                release_id,
                json.dumps(node, ensure_ascii=False),
                now_iso(),
            ))
        for edge in graph_rows.get("edges", []):
            conn.execute("""
                INSERT INTO graph_edges (
                    edge_id, subject_id, predicate, object_id, article_id, release_id, payload_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(edge_id) DO UPDATE SET
                    subject_id=excluded.subject_id,
                    predicate=excluded.predicate,
                    object_id=excluded.object_id,
                    article_id=excluded.article_id,
                    release_id=excluded.release_id,
                    payload_json=excluded.payload_json,
                    updated_at=excluded.updated_at
            """, (
                edge.get("edge_id"),
                edge.get("subject_id"),
                edge.get("predicate"),
                edge.get("object_id"),
                edge.get("article_id"),
                release_id,
                json.dumps(edge, ensure_ascii=False),
                now_iso(),
            ))
        conn.commit()
        counts = {
            "production_runs": conn.execute("SELECT COUNT(*) FROM production_runs").fetchone()[0],
            "vector_objects": conn.execute("SELECT COUNT(*) FROM vector_objects").fetchone()[0],
            "vector_write_ledger": conn.execute("SELECT COUNT(*) FROM vector_write_ledger").fetchone()[0],
            "graph_nodes": conn.execute("SELECT COUNT(*) FROM graph_nodes").fetchone()[0],
            "graph_edges": conn.execute("SELECT COUNT(*) FROM graph_edges").fetchone()[0],
        }
    finally:
        conn.close()
    return {"db_path": str(db_path), **counts}


def upsert_qdrant_staging(
    embeddings: list[dict[str, Any]],
    collections: dict[str, str],
    *,
    qdrant_url: str,
    out_dir: Path,
    release_id: str,
    query_count: int,
    min_equivalent_hit_rate: float = 1.0,
) -> dict[str, Any]:
    from qdrant_client import QdrantClient, models

    if not embeddings:
        raise ValueError("no embeddings to write")
    dim_counts = Counter(len(row.get("vector") or []) for row in embeddings)
    if len(dim_counts) != 1:
        raise ValueError(f"mixed vector dimensions: {dict(dim_counts)}")
    dim = next(iter(dim_counts))
    client = QdrantClient(url=qdrant_url, timeout=60)

    for collection_name in collections.values():
        if client.collection_exists(collection_name):
            continue
        client.create_collection(
            collection_name=collection_name,
            vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE),
        )

    by_kind: dict[str, list[dict[str, Any]]] = {}
    for row in embeddings:
        by_kind.setdefault(str(row.get("object_kind") or "unknown"), []).append(row)

    for kind, rows in by_kind.items():
        collection_name = collections[kind]
        points = [
            models.PointStruct(
                id=point_id_for(row),
                vector=row["vector"],
                payload=qdrant_payload(row, release_id),
            )
            for row in rows
        ]
        for start in range(0, len(points), 64):
            client.upsert(collection_name=collection_name, points=points[start:start + 64], wait=True)

    tested = 0
    hit = 0
    equivalent_hit = 0
    misses = []
    for row in embeddings[: max(1, query_count)]:
        collection_name = collections[str(row.get("object_kind") or "unknown")]
        expected_id = point_id_for(row)
        response = client.query_points(
            collection_name=collection_name,
            query=row["vector"],
            limit=3,
            with_payload=True,
        )
        points = list(getattr(response, "points", []) or [])
        top_id = str(points[0].id) if points else ""
        tested += 1
        if top_id == expected_id:
            hit += 1
            equivalent_hit += 1
        elif points and write_tests.qdrant_payload_is_equivalent(row, getattr(points[0], "payload", {}) or {}):
            equivalent_hit += 1
        else:
            misses.append({
                "expected": expected_id,
                "top": top_id,
                "collection": collection_name,
                "job_id": row.get("job_id"),
            })
    result = {
        "qdrant_url": qdrant_url,
        "collections": collections,
        "row_count": len(embeddings),
        "dim": dim,
        "tested": tested,
        "hit": hit,
        "self_hit_rate": round(hit / tested, 4) if tested else 0.0,
        "equivalent_hit": equivalent_hit,
        "equivalent_hit_rate": round(equivalent_hit / tested, 4) if tested else 0.0,
        "misses": misses[:10],
    }
    write_json(out_dir / "qdrant_production_staging_details.json", result)
    if result["equivalent_hit_rate"] < min_equivalent_hit_rate:
        raise RuntimeError(f"Qdrant staging verification failed (rate={result['equivalent_hit_rate']:.4f} < threshold={min_equivalent_hit_rate}): {result}")
    return result


def write_neo4j_production(
    graph_rows: dict[str, list[dict[str, Any]]],
    *,
    tx_url: str,
    release_id: str,
    batch_size: int,
) -> dict[str, Any]:
    nodes = [dict(row, release_id=release_id, run_id=release_id) for row in graph_rows.get("nodes", [])]
    edges = [dict(row, release_id=release_id, run_id=release_id) for row in graph_rows.get("edges", [])]
    if not nodes and not edges:
        return {"status": "SKIPPED_NO_GRAPH", "written_nodes": 0, "written_edges": 0}
    size = max(1, int(batch_size or write_tests.DEFAULT_NEO4J_BATCH_SIZE))
    node_batches = write_tests.batched_rows(nodes, size)
    edge_batches = write_tests.batched_rows(edges, size)
    write_tests.neo4j_commit(tx_url, [{
        "statement": "CREATE CONSTRAINT wechat_node_id IF NOT EXISTS FOR (n:WechatNode) REQUIRE n.node_id IS UNIQUE"
    }])
    for batch in node_batches:
        write_tests.neo4j_commit(tx_url, [{
            "statement": (
                "UNWIND $nodes AS row "
                "MERGE (n:WechatNode {node_id: row.node_id}) "
                "SET n += row"
            ),
            "parameters": {"nodes": batch},
        }])
    for batch in edge_batches:
        write_tests.neo4j_commit(tx_url, [{
            "statement": (
                "UNWIND $edges AS row "
                "MATCH (a:WechatNode {node_id: row.subject_id}) "
                "MATCH (b:WechatNode {node_id: row.object_id}) "
                "MERGE (a)-[r:WECHAT_REL {edge_id: row.edge_id}]->(b) "
                "SET r += row"
            ),
            "parameters": {"edges": batch},
        }])
    payload = write_tests.neo4j_commit(tx_url, [{
        "statement": (
            "MATCH (n:WechatNode {release_id: $release_id}) "
            "WITH count(n) AS nodes "
            "MATCH ()-[r:WECHAT_REL {release_id: $release_id}]->() "
            "RETURN nodes, count(r) AS edges"
        ),
        "parameters": {"release_id": release_id},
    }])
    row = payload["results"][0]["data"][0]["row"]
    return {
        "status": "PASS",
        "written_nodes": row[0],
        "written_edges": row[1],
        "batch_size": size,
        "node_batches": len(node_batches),
        "edge_batches": len(edge_batches),
        "tx_url": tx_url,
    }


def run_apply(args: argparse.Namespace, preflight: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    gate_dir = Path(args.gate_dir).resolve()
    release_id = preflight["release_id"]
    embeddings = read_jsonl(embeddings_path(gate_dir))
    graph_rows = load_graph_rows(gate_dir)
    result: dict[str, Any] = {
        "schema_version": "stage8_vector_production_writer_apply.v1",
        "release_id": release_id,
        "gate_dir": str(gate_dir),
        "out_dir": str(out_dir),
        "pc_ledger": None,
        "qdrant_staging": None,
        "neo4j": None,
        "status": "RUNNING",
    }
    result["pc_ledger"] = write_pc_production_ledger(
        Path(args.pc_db),
        embeddings,
        graph_rows,
        release_id=release_id,
    )
    write_json(out_dir / "production_writer_apply_partial.json", result)
    if not args.skip_qdrant:
        result["qdrant_staging"] = upsert_qdrant_staging(
            embeddings,
            preflight["qdrant_staging_collections"],
            qdrant_url=args.qdrant_url,
            out_dir=out_dir,
            release_id=release_id,
            query_count=args.qdrant_query_count,
            min_equivalent_hit_rate=args.qdrant_min_equivalent_hit_rate,
        )
        write_json(out_dir / "production_writer_apply_partial.json", result)
    if not args.skip_neo4j:
        result["neo4j"] = write_neo4j_production(
            graph_rows,
            tx_url=args.neo4j_tx_url,
            release_id=release_id,
            batch_size=args.neo4j_batch_size,
        )
    result["status"] = "PASS"
    write_json(out_dir / "production_writer_apply.json", result)
    return result


def write_report(preflight: dict[str, Any], apply_result: dict[str, Any] | None, out_dir: Path) -> None:
    lines = [
        "# Stage8 Vector Production Writer",
        "",
        f"- release_id: `{preflight['release_id']}`",
        f"- gate_dir: `{preflight['gate_dir']}`",
        f"- apply_allowed: `{preflight['apply_allowed']}`",
        f"- endpoint: `{preflight['endpoint']}`",
        f"- jobs/embeddings/failures: `{preflight['job_count']}` / `{preflight['embedding_count']}` / `{preflight['failure_count']}`",
        "",
        "## Blockers",
        "",
    ]
    for blocker in preflight["blockers"] or ["none"]:
        lines.append(f"- {blocker}")
    lines.extend(["", "## Qdrant Staging Collections", ""])
    for kind, name in sorted(preflight["qdrant_staging_collections"].items()):
        lines.append(f"- `{kind}`: `{name}`")
    if apply_result:
        lines.extend(["", "## Apply Result", ""])
        lines.append(f"- status: `{apply_result['status']}`")
        lines.append(f"- pc_ledger: `{json.dumps(apply_result.get('pc_ledger'), ensure_ascii=False, sort_keys=True)}`")
        lines.append(f"- qdrant_staging: `{json.dumps(apply_result.get('qdrant_staging'), ensure_ascii=False, sort_keys=True)}`")
        lines.append(f"- neo4j: `{json.dumps(apply_result.get('neo4j'), ensure_ascii=False, sort_keys=True)}`")
    (out_dir / "PRODUCTION_WRITER_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["preflight", "apply"], default="preflight")
    parser.add_argument("--gate-dir", required=True)
    parser.add_argument("--out-dir", default="")
    parser.add_argument("--release-id", default="")
    parser.add_argument("--confirm-production-write", default="")
    parser.add_argument("--pc-db", default=str(DEFAULT_PRODUCTION_DB))
    parser.add_argument("--qdrant-url", default=write_tests.DEFAULT_QDRANT_URL)
    parser.add_argument("--qdrant-query-count", type=int, default=160)
    parser.add_argument("--qdrant-min-equivalent-hit-rate", type=float, default=1.0)
    parser.add_argument("--skip-qdrant", action="store_true")
    parser.add_argument("--neo4j-tx-url", default=write_tests.DEFAULT_NEO4J_TX_URL)
    parser.add_argument("--neo4j-batch-size", type=int, default=write_tests.DEFAULT_NEO4J_BATCH_SIZE)
    parser.add_argument("--skip-neo4j", action="store_true")
    args = parser.parse_args(argv)

    gate_dir = Path(args.gate_dir).resolve()
    preflight = build_preflight(
        gate_dir,
        release_id=args.release_id or None,
        confirm_token=args.confirm_production_write,
    )
    out_dir = Path(args.out_dir) if args.out_dir else gate_dir / "production_writer_runs" / preflight["release_id"]
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "production_writer_preflight.json", preflight)
    apply_result = None
    if args.mode == "apply":
        if not preflight["apply_allowed"]:
            write_report(preflight, None, out_dir)
            print(json.dumps(preflight, ensure_ascii=False, indent=2, sort_keys=True))
            return 2
        apply_result = run_apply(args, preflight, out_dir)
    write_report(preflight, apply_result, out_dir)
    print(json.dumps({"preflight": preflight, "apply": apply_result}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
