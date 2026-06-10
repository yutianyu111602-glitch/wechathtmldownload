"""Compare Stage8/Stage9 write strategies using existing Stage7 data.

This script is intentionally canary-only by default:

- Reads existing ``llm_extract`` files.
- Builds vector jobs from the current Stage8 card generator.
- Calls the configured embedding endpoint for a bounded sample.
- Writes Qdrant test collections with a ``wechat_test_`` prefix.
- Writes an isolated PC SQLite ledger under the run output directory.
- Builds a Neo4j preview pack and reports whether Neo4j is reachable.

It does not write production Qdrant collections, production Neo4j, or the
existing Stage7 ``pipeline.sqlite`` unless the caller changes the output paths.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import socket
import sqlite3
import sys
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
import requests

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stage7.atomic_io import safe_read_json
from stage7.vector_plan.build_embedding_jobs import build_jobs_from_article
from stage7.vector_plan.embed_runner import run_vector_jobs_async
from stage9.graph_builder import process_single_article


DEFAULT_OUTPUT_ROOT = Path(r"D:\downstream_results\stage7_rewrite")
DEFAULT_LONGRUN_ROOT = DEFAULT_OUTPUT_ROOT / "longrun"
DEFAULT_QDRANT_URL = "http://127.0.0.1:6333"
DEFAULT_NEO4J_HOST = "127.0.0.1"
DEFAULT_NEO4J_BOLT_PORT = 7687
DEFAULT_NEO4J_HTTP_PORT = 7474
DEFAULT_NEO4J_TX_URL = "http://127.0.0.1:7474/db/neo4j/tx/commit"
DEFAULT_NEO4J_BATCH_SIZE = 500


@dataclass
class StrategyResult:
    name: str
    status: str
    details: dict[str, Any]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_id() -> str:
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


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_vector_route(config_path: Path) -> tuple[str, str, int, dict[str, Any]]:
    with config_path.open("r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    ep_key = config.get("default_chinese_endpoint", "local_mac_vector_endpoint_11437")
    ep_def = (config.get("endpoints") or {}).get(ep_key) or {}
    endpoint = ep_def.get("pc_call_url") or ep_def.get("url") or "http://192.168.8.234:11437"
    dim = int(ep_def.get("dim", 1024))
    route_metadata = {
        "endpoint_id": ep_def.get("endpoint_id") or ep_key,
        "endpoint_port": int(str(endpoint).rstrip("/").rsplit(":", 1)[-1]),
        "canonical_url": ep_def.get("canonical_url", ""),
        "pc_call_url": endpoint,
        "route_role": ep_def.get("route_role", "wechat_93k_default"),
        "dim_expected": dim,
    }
    return ep_def.get("model", "stella-large-zh-v2"), endpoint, dim, route_metadata


def collect_extract_files(output_root: Path, sample_articles: int | None) -> list[Path]:
    extract_root = output_root / "llm_extract"
    files = sorted(extract_root.rglob("extract.article.v1.json"))
    if sample_articles is not None:
        files = files[:sample_articles]
    return files


def build_jobs(
    output_root: Path,
    config_path: Path,
    out_dir: Path,
    sample_articles: int | None,
    max_jobs: int | None,
    card_template: str,
) -> tuple[Path, list[Path], list[dict[str, Any]], dict[str, Any]]:
    model, endpoint, dim, route_metadata = load_vector_route(config_path)
    files = collect_extract_files(output_root, sample_articles)
    all_jobs = []
    by_kind: Counter[str] = Counter()
    parsed_files = 0
    for extract_file in files:
        article_data = safe_read_json(extract_file, {})
        if not article_data:
            continue
        parsed_files += 1
        rel_path = str(extract_file.relative_to(output_root))
        jobs = build_jobs_from_article(
            article_data,
            rel_path,
            model,
            endpoint,
            dim,
            route_metadata,
            card_template=card_template,
        )
        for job in jobs:
            all_jobs.append(job.to_dict())
            by_kind[job.object_kind] += 1
            if max_jobs is not None and len(all_jobs) >= max_jobs:
                break
        if max_jobs is not None and len(all_jobs) >= max_jobs:
            break

    jobs_path = out_dir / "vector_jobs.strategy_test.jsonl"
    write_jsonl(jobs_path, all_jobs)
    stats = {
        "files_selected": len(files),
        "files_parsed": parsed_files,
        "job_count": len(all_jobs),
        "by_kind": dict(by_kind),
        "model": model,
        "endpoint": endpoint,
        "dim": dim,
        "card_template": card_template,
        "jobs_path": str(jobs_path),
    }
    write_json(out_dir / "vector_jobs.strategy_test.summary.json", stats)
    return jobs_path, files, all_jobs, stats


def point_id_for(row: dict[str, Any]) -> str:
    seed = "|".join([
        str(row.get("job_id") or ""),
        str(row.get("object_kind") or ""),
        str(row.get("object_id") or ""),
        str(row.get("text_sha1") or ""),
    ])
    return str(uuid.uuid5(uuid.NAMESPACE_URL, seed))


def qdrant_payload(row: dict[str, Any]) -> dict[str, Any]:
    metadata = row.get("metadata") or {}
    return {
        "point_id": point_id_for(row),
        "job_id": row.get("job_id"),
        "object_kind": row.get("object_kind"),
        "object_id": row.get("object_id"),
        "article_id": row.get("article_id"),
        "source_path": row.get("source_path"),
        "collection_original": row.get("collection"),
        "model": row.get("model"),
        "dim": row.get("dim"),
        "endpoint": row.get("endpoint"),
        "text_sha1": row.get("text_sha1"),
        "account": metadata.get("account"),
        "article_title": metadata.get("article_title"),
        "confidence": metadata.get("confidence"),
        "endpoint_id": metadata.get("endpoint_id"),
        "endpoint_port": metadata.get("endpoint_port"),
        "route_role": metadata.get("route_role"),
        "created_at": row.get("created_at") or now_iso(),
    }


def qdrant_payload_is_equivalent(row: dict[str, Any], payload: dict[str, Any] | None) -> bool:
    if not payload:
        return False
    return (
        str(payload.get("text_sha1") or "") == str(row.get("text_sha1") or "")
        and str(payload.get("object_kind") or "") == str(row.get("object_kind") or "")
    )


def safe_collection_model(model: str) -> str:
    return model.replace("/", "_").replace(".", "_").replace("-", "_")


def run_qdrant_tests(
    embeddings: list[dict[str, Any]],
    qdrant_url: str,
    out_dir: Path,
    run_suffix: str,
    query_count: int,
    keep_collections: bool,
) -> list[StrategyResult]:
    try:
        from qdrant_client import QdrantClient, models
    except Exception as exc:
        return [StrategyResult("qdrant_import", "BLOCKED", {"reason": f"qdrant_client import failed: {exc}"})]

    if not embeddings:
        return [StrategyResult("qdrant_import", "FAIL", {"reason": "no embeddings"})]

    dim_counts = Counter(len(row.get("vector") or []) for row in embeddings)
    if len(dim_counts) != 1:
        return [StrategyResult("qdrant_import", "FAIL", {"reason": "mixed vector dimensions", "dim_counts": dict(dim_counts)})]

    dim = next(iter(dim_counts))
    model = str(embeddings[0].get("model") or "stella-large-zh-v2")
    model_label = safe_collection_model(model)
    client = QdrantClient(url=qdrant_url, timeout=30)

    results: list[StrategyResult] = []
    collection_map: dict[str, str] = {}
    split_collections = {
        kind: f"wechat_test_split_{kind}_{model_label}_{dim}_{run_suffix}"
        for kind in sorted({str(row.get("object_kind") or "unknown") for row in embeddings})
    }
    unified_collection = f"wechat_test_unified_{model_label}_{dim}_{run_suffix}"

    def recreate_collection(name: str) -> None:
        if client.collection_exists(name):
            client.delete_collection(name)
        client.create_collection(
            collection_name=name,
            vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE),
        )

    for name in [*split_collections.values(), unified_collection]:
        recreate_collection(name)

    def upsert_rows(name: str, rows: list[dict[str, Any]]) -> None:
        points = [
            models.PointStruct(
                id=point_id_for(row),
                vector=row["vector"],
                payload=qdrant_payload(row),
            )
            for row in rows
        ]
        for start in range(0, len(points), 64):
            client.upsert(collection_name=name, points=points[start:start + 64], wait=True)

    for kind, name in split_collections.items():
        rows = [row for row in embeddings if str(row.get("object_kind") or "unknown") == kind]
        upsert_rows(name, rows)
        collection_map[kind] = name

    upsert_rows(unified_collection, embeddings)

    def self_hit_rate(name_for_row) -> dict[str, Any]:
        tested = 0
        hit = 0
        equivalent_hit = 0
        misses = []
        duplicate_equivalent_misses = []
        for row in embeddings[:query_count]:
            collection_name = name_for_row(row)
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
            elif points and qdrant_payload_is_equivalent(row, getattr(points[0], "payload", {}) or {}):
                equivalent_hit += 1
                duplicate_equivalent_misses.append({
                    "expected": expected_id,
                    "top": top_id,
                    "collection": collection_name,
                    "job_id": row.get("job_id"),
                    "top_job_id": (getattr(points[0], "payload", {}) or {}).get("job_id"),
                    "text_sha1": row.get("text_sha1"),
                })
            else:
                misses.append({
                    "expected": expected_id,
                    "top": top_id,
                    "collection": collection_name,
                    "job_id": row.get("job_id"),
                })
        return {
            "tested": tested,
            "hit": hit,
            "self_hit_rate": round(hit / tested, 4) if tested else 0.0,
            "equivalent_hit": equivalent_hit,
            "equivalent_hit_rate": round(equivalent_hit / tested, 4) if tested else 0.0,
            "misses": misses[:5],
            "duplicate_equivalent_misses": duplicate_equivalent_misses[:5],
        }

    split_eval = self_hit_rate(lambda row: collection_map[str(row.get("object_kind") or "unknown")])
    unified_eval = self_hit_rate(lambda row: unified_collection)

    details = {
        "qdrant_url": qdrant_url,
        "dim": dim,
        "model": model,
        "row_count": len(embeddings),
        "split_collections": split_collections,
        "unified_collection": unified_collection,
        "split_eval": split_eval,
        "unified_eval": unified_eval,
        "kept_collections": keep_collections,
    }
    write_json(out_dir / "qdrant_strategy_details.json", details)

    def qdrant_eval_status(evaluation: dict[str, Any]) -> str:
        if evaluation["self_hit_rate"] == 1.0:
            return "PASS"
        if evaluation.get("equivalent_hit_rate") == 1.0:
            return "WARN_DUPLICATE_EQUIV"
        return "WARN"

    results.append(StrategyResult(
        "qdrant_split_by_kind",
        qdrant_eval_status(split_eval),
        {
            "collections": split_collections,
            **split_eval,
        },
    ))
    results.append(StrategyResult(
        "qdrant_unified_payload_filter",
        qdrant_eval_status(unified_eval),
        {
            "collection": unified_collection,
            **unified_eval,
        },
    ))

    if not keep_collections:
        for name in [*split_collections.values(), unified_collection]:
            if client.collection_exists(name):
                client.delete_collection(name)
        results.append(StrategyResult(
            "qdrant_test_cleanup",
            "PASS",
            {"deleted_collections": [*split_collections.values(), unified_collection]},
        ))

    return results


def run_qdrant_tests_guarded(
    embeddings: list[dict[str, Any]],
    qdrant_url: str,
    out_dir: Path,
    run_suffix: str,
    query_count: int,
    keep_collections: bool,
) -> list[StrategyResult]:
    try:
        return run_qdrant_tests(
            embeddings,
            qdrant_url,
            out_dir,
            run_suffix,
            query_count,
            keep_collections,
        )
    except Exception as exc:
        return [StrategyResult(
            "qdrant_tests",
            "BLOCKED",
            {
                "qdrant_url": qdrant_url,
                "row_count": len(embeddings),
                "kept_collections": keep_collections,
                "reason": f"Qdrant canary could not complete: {type(exc).__name__}: {exc}",
            },
        )]


def run_pc_db_test(db_path: Path, embeddings: list[dict[str, Any]], graph_rows: dict[str, list[dict[str, Any]]]) -> StrategyResult:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
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
                payload_json TEXT,
                updated_at TEXT NOT NULL
            )
        """)
        for _ in range(2):
            for row in embeddings:
                payload = qdrant_payload(row)
                conn.execute("""
                    INSERT INTO vector_objects (
                        object_kind, object_id, text_sha1, article_id, collection_name,
                        model, dim, endpoint, canonical_text, metadata_json, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(object_kind, object_id, text_sha1) DO UPDATE SET
                        article_id=excluded.article_id,
                        collection_name=excluded.collection_name,
                        model=excluded.model,
                        dim=excluded.dim,
                        endpoint=excluded.endpoint,
                        canonical_text=excluded.canonical_text,
                        metadata_json=excluded.metadata_json,
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
                    now_iso(),
                ))
                conn.execute("""
                    INSERT INTO vector_write_ledger (
                        target, point_id, object_kind, object_id, collection_name,
                        text_sha1, status, payload_json, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(target, point_id) DO UPDATE SET
                        status=excluded.status,
                        payload_json=excluded.payload_json,
                        updated_at=excluded.updated_at
                """, (
                    "qdrant_test",
                    payload["point_id"],
                    row.get("object_kind"),
                    row.get("object_id"),
                    row.get("collection"),
                    row.get("text_sha1"),
                    "written",
                    json.dumps(payload, ensure_ascii=False),
                    now_iso(),
                ))
            for node in graph_rows.get("nodes", []):
                conn.execute("""
                    INSERT INTO graph_nodes (
                        node_id, node_kind, name, type, article_uid, payload_json, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(node_id) DO UPDATE SET
                        node_kind=excluded.node_kind,
                        name=excluded.name,
                        type=excluded.type,
                        article_uid=excluded.article_uid,
                        payload_json=excluded.payload_json,
                        updated_at=excluded.updated_at
                """, (
                    node.get("node_id"),
                    node.get("node_kind"),
                    node.get("name"),
                    node.get("type"),
                    node.get("article_uid"),
                    json.dumps(node, ensure_ascii=False),
                    now_iso(),
                ))
            for edge in graph_rows.get("edges", []):
                conn.execute("""
                    INSERT INTO graph_edges (
                        edge_id, subject_id, predicate, object_id, article_id, payload_json, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(edge_id) DO UPDATE SET
                        subject_id=excluded.subject_id,
                        predicate=excluded.predicate,
                        object_id=excluded.object_id,
                        article_id=excluded.article_id,
                        payload_json=excluded.payload_json,
                        updated_at=excluded.updated_at
                """, (
                    edge.get("edge_id"),
                    edge.get("subject_id"),
                    edge.get("predicate"),
                    edge.get("object_id"),
                    edge.get("article_id"),
                    json.dumps(edge, ensure_ascii=False),
                    now_iso(),
                ))
            conn.commit()
        counts = {
            "vector_objects": conn.execute("SELECT COUNT(*) FROM vector_objects").fetchone()[0],
            "vector_write_ledger": conn.execute("SELECT COUNT(*) FROM vector_write_ledger").fetchone()[0],
            "graph_nodes": conn.execute("SELECT COUNT(*) FROM graph_nodes").fetchone()[0],
            "graph_edges": conn.execute("SELECT COUNT(*) FROM graph_edges").fetchone()[0],
        }
    return StrategyResult("pc_sqlite_ledger_idempotent", "PASS", {"db_path": str(db_path), **counts})


def complete_graph_endpoint_nodes(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add stub nodes for edge endpoints missing from Stage9 entity/event nodes.

    Stage9 preview edges commonly originate from article nodes. Older preview
    exports did not materialize those article nodes, which makes graph database
    canary writes unable to match the source side of the edge. The stubs are
    deliberately minimal and labelled by ``node_kind`` for later replacement by
    richer article records.
    """
    by_id = {str(node.get("node_id")): node for node in nodes if node.get("node_id")}
    for edge in edges:
        for field in ("subject_id", "object_id"):
            node_id = str(edge.get(field) or "")
            if not node_id or node_id in by_id:
                continue
            node_kind = "article" if node_id.startswith("art:") else "unknown"
            by_id[node_id] = {
                "node_id": node_id,
                "node_kind": node_kind,
                "name": node_id,
                "type": node_kind,
                "article_uid": edge.get("article_id", ""),
                "quality_flags": ["stub_endpoint_node"],
            }
    return list(by_id.values())


def build_graph_preview(extract_files: list[Path], out_dir: Path) -> dict[str, list[dict[str, Any]]]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    for path in extract_files:
        result = process_single_article(path)
        if not result:
            continue
        nodes.extend(result.get("entity_nodes") or [])
        events.extend(result.get("event_nodes") or [])
        edges.extend(result.get("edges") or [])
    completed_nodes = complete_graph_endpoint_nodes(nodes + events, edges)
    graph_dir = out_dir / "graph_preview"
    write_jsonl(graph_dir / "nodes.entities.jsonl", nodes)
    write_jsonl(graph_dir / "nodes.events.jsonl", events)
    write_jsonl(graph_dir / "nodes.completed.jsonl", completed_nodes)
    write_jsonl(graph_dir / "edges.jsonl", edges)
    cypher = [
        "// Neo4j canary preview generated by run_stage8_write_strategy_tests.py",
        "CREATE CONSTRAINT wechat_test_node_id IF NOT EXISTS FOR (n:WechatNode) REQUIRE n.node_id IS UNIQUE;",
        "UNWIND $nodes AS row",
        "MERGE (n:WechatNode {node_id: row.node_id})",
        "SET n += row;",
        "UNWIND $edges AS row",
        "MATCH (a:WechatNode {node_id: row.subject_id})",
        "MATCH (b:WechatNode {node_id: row.object_id})",
        "MERGE (a)-[r:WECHAT_REL {edge_id: row.edge_id}]->(b)",
        "SET r += row;",
    ]
    (graph_dir / "neo4j_canary_preview.cypher").write_text("\n".join(cypher) + "\n", encoding="utf-8")
    return {"nodes": completed_nodes, "edges": edges}


def test_port(host: str, port: int, timeout_sec: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_sec):
            return True
    except OSError:
        return False


def neo4j_commit(tx_url: str, statements: list[dict[str, Any]]) -> dict[str, Any]:
    response = requests.post(tx_url, json={"statements": statements}, timeout=60)
    response.raise_for_status()
    payload = response.json()
    if payload.get("errors"):
        raise RuntimeError(json.dumps(payload["errors"], ensure_ascii=False))
    return payload


def batched_rows(rows: list[dict[str, Any]], batch_size: int) -> list[list[dict[str, Any]]]:
    size = max(1, int(batch_size or DEFAULT_NEO4J_BATCH_SIZE))
    return [rows[start:start + size] for start in range(0, len(rows), size)]


def neo4j_count_from_payload(payload: dict[str, Any]) -> int:
    try:
        return int(payload["results"][0]["data"][0]["row"][0])
    except (KeyError, IndexError, TypeError, ValueError):
        return 0


def cleanup_neo4j_run(tx_url: str, run_suffix: str, batch_size: int) -> dict[str, int]:
    size = max(1, int(batch_size or DEFAULT_NEO4J_BATCH_SIZE))
    deleted_edges = 0
    deleted_nodes = 0
    cleanup_batches = 0
    edge_statement = (
        "MATCH ()-[r:WECHAT_TEST_REL {run_id: $run_id}]->() "
        f"WITH r LIMIT {size} DELETE r RETURN count(r) AS deleted"
    )
    node_statement = (
        "MATCH (n:WechatTestNode {run_id: $run_id}) "
        f"WITH n LIMIT {size} DELETE n RETURN count(n) AS deleted"
    )
    while True:
        payload = neo4j_commit(tx_url, [{
            "statement": edge_statement,
            "parameters": {"run_id": run_suffix},
        }])
        count = neo4j_count_from_payload(payload)
        if count == 0:
            break
        deleted_edges += count
        cleanup_batches += 1
    while True:
        payload = neo4j_commit(tx_url, [{
            "statement": node_statement,
            "parameters": {"run_id": run_suffix},
        }])
        count = neo4j_count_from_payload(payload)
        if count == 0:
            break
        deleted_nodes += count
        cleanup_batches += 1
    return {
        "deleted_edges": deleted_edges,
        "deleted_nodes": deleted_nodes,
        "cleanup_batches": cleanup_batches,
    }


def run_neo4j_canary_write(
    tx_url: str,
    graph_rows: dict[str, list[dict[str, Any]]],
    run_suffix: str,
    *,
    cleanup: bool,
    batch_size: int = DEFAULT_NEO4J_BATCH_SIZE,
) -> dict[str, Any]:
    nodes = [dict(row, run_id=run_suffix) for row in graph_rows.get("nodes", [])]
    edges = [dict(row, run_id=run_suffix) for row in graph_rows.get("edges", [])]
    node_batches = batched_rows(nodes, batch_size)
    edge_batches = batched_rows(edges, batch_size)
    neo4j_commit(tx_url, [{
        "statement": (
            "CREATE CONSTRAINT wechat_test_node_id IF NOT EXISTS "
            "FOR (n:WechatTestNode) REQUIRE n.node_id IS UNIQUE"
        )
    }])
    for batch in node_batches:
        neo4j_commit(tx_url, [{
            "statement": (
                "UNWIND $nodes AS row "
                "MERGE (n:WechatTestNode {node_id: row.node_id}) "
                "SET n += row"
            ),
            "parameters": {"nodes": batch},
        }])
    for batch in edge_batches:
        neo4j_commit(tx_url, [{
            "statement": (
                "UNWIND $edges AS row "
                "MATCH (a:WechatTestNode {node_id: row.subject_id}) "
                "MATCH (b:WechatTestNode {node_id: row.object_id}) "
                "MERGE (a)-[r:WECHAT_TEST_REL {edge_id: row.edge_id}]->(b) "
                "SET r += row"
            ),
            "parameters": {"edges": batch},
        }])
    count_payload = neo4j_commit(tx_url, [{
        "statement": (
            "MATCH (n:WechatTestNode {run_id: $run_id}) "
            "WITH count(n) AS nodes "
            "MATCH ()-[r:WECHAT_TEST_REL {run_id: $run_id}]->() "
            "RETURN nodes, count(r) AS edges"
        ),
        "parameters": {"run_id": run_suffix},
    }])
    row = count_payload["results"][0]["data"][0]["row"]
    result = {
        "written_nodes": row[0],
        "written_edges": row[1],
        "cleaned_up": False,
        "batch_size": max(1, int(batch_size or DEFAULT_NEO4J_BATCH_SIZE)),
        "node_batches": len(node_batches),
        "edge_batches": len(edge_batches),
    }
    if cleanup:
        result.update(cleanup_neo4j_run(tx_url, run_suffix, batch_size))
        result["cleaned_up"] = True
    return result


def run_neo4j_probe(
    host: str,
    bolt_port: int,
    http_port: int,
    graph_rows: dict[str, list[dict[str, Any]]],
    out_dir: Path,
    *,
    enable_write: bool,
    tx_url: str,
    run_suffix: str,
    cleanup: bool,
    batch_size: int = DEFAULT_NEO4J_BATCH_SIZE,
) -> StrategyResult:
    bolt = test_port(host, bolt_port)
    http = test_port(host, http_port)
    details = {
        "host": host,
        "bolt_port": bolt_port,
        "bolt_listening": bolt,
        "http_port": http_port,
        "http_listening": http,
        "tx_url": tx_url,
        "node_count": len(graph_rows.get("nodes", [])),
        "edge_count": len(graph_rows.get("edges", [])),
        "preview_path": str(out_dir / "graph_preview" / "neo4j_canary_preview.cypher"),
    }
    if not graph_rows.get("nodes") and not graph_rows.get("edges"):
        details["reason"] = "No graph rows were produced for this sample; no Neo4j write attempted."
        return StrategyResult("neo4j_canary_write", "SKIPPED_NO_GRAPH", details)
    if not (bolt or http):
        details["reason"] = "Neo4j is not listening locally; no write attempted."
        return StrategyResult("neo4j_reachability_and_preview", "BLOCKED", details)
    if not enable_write:
        details["reason"] = "Neo4j is reachable, but --enable-neo4j-write was not set."
        return StrategyResult("neo4j_reachability_and_preview", "PASS_PREVIEW", details)
    try:
        write_result = run_neo4j_canary_write(
            tx_url,
            graph_rows,
            run_suffix,
            cleanup=cleanup,
            batch_size=batch_size,
        )
        details.update(write_result)
        status = "PASS" if write_result["written_nodes"] > 0 else "WARN"
        details["reason"] = "Neo4j canary write completed."
        return StrategyResult("neo4j_canary_write", status, details)
    except Exception as exc:
        details["reason"] = f"Neo4j canary write failed: {type(exc).__name__}: {exc}"
        return StrategyResult("neo4j_canary_write", "FAIL", details)


def write_report(out_dir: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# Stage8/Stage9 Write Strategy Test",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- output_root: `{summary['output_root']}`",
        f"- out_dir: `{summary['out_dir']}`",
        f"- jobs: `{summary['job_stats']['job_count']}`",
        (
            f"- embeddings: `{summary['embedding_stats']['succeeded']}` succeeded / "
            f"`{summary['embedding_stats']['failed']}` failed / "
            f"`{summary['embedding_stats'].get('skipped_existing', 0)}` skipped_existing"
        ),
        "",
        "## Strategy Results",
        "",
        "| Strategy | Status | Key detail |",
        "| --- | --- | --- |",
    ]
    for row in summary["strategy_results"]:
        detail = row.get("details", {})
        key = (
            (
                f"exact {detail.get('self_hit_rate')}; equivalent {detail.get('equivalent_hit_rate')}"
                if detail.get("equivalent_hit_rate") is not None
                and detail.get("equivalent_hit_rate") != detail.get("self_hit_rate")
                else detail.get("self_hit_rate")
            )
            or detail.get("vector_objects")
            or detail.get("reason")
            or detail.get("row_count")
            or ""
        )
        lines.append(f"| `{row['name']}` | `{row['status']}` | `{key}` |")
    lines.extend([
        "",
        "## Recommendation",
        "",
        "- Use PC SQLite ledger as the write source-of-truth before any external upsert.",
        "- Prefer split Qdrant collections for production filtering and dimension safety.",
        "- Keep a unified Qdrant collection only if cross-kind exploration quality beats split multi-query in later relevance tests.",
        "- Keep Neo4j writes in `WechatTestNode` / `WECHAT_TEST_REL` canary labels with cleanup until a production graph gate is added.",
        "",
    ])
    (out_dir / "SUMMARY.md").write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run bounded Stage8/Stage9 write strategy tests.")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--out-dir", default="")
    parser.add_argument("--vector-config", default="")
    parser.add_argument("--sample-articles", type=int, default=30)
    parser.add_argument("--max-jobs", type=int, default=80)
    parser.add_argument("--card-template", default="multi_card", choices=["baseline", "labeled_v2", "multi_card", "research_v1"])
    parser.add_argument("--embedding-concurrency", type=int, default=4)
    parser.add_argument("--embedding-timeout-sec", type=int, default=120)
    parser.add_argument("--qdrant-url", default=DEFAULT_QDRANT_URL)
    parser.add_argument("--query-count", type=int, default=10)
    parser.add_argument("--skip-qdrant", action="store_true")
    parser.add_argument("--keep-qdrant-test-collections", action="store_true")
    parser.add_argument("--neo4j-host", default=DEFAULT_NEO4J_HOST)
    parser.add_argument("--neo4j-bolt-port", type=int, default=DEFAULT_NEO4J_BOLT_PORT)
    parser.add_argument("--neo4j-http-port", type=int, default=DEFAULT_NEO4J_HTTP_PORT)
    parser.add_argument("--neo4j-tx-url", default=DEFAULT_NEO4J_TX_URL)
    parser.add_argument("--enable-neo4j-write", action="store_true")
    parser.add_argument("--cleanup-neo4j-test", action="store_true")
    parser.add_argument("--neo4j-batch-size", type=int, default=DEFAULT_NEO4J_BATCH_SIZE)
    args = parser.parse_args(argv)

    output_root = Path(args.output_root)
    suffix = run_id()
    out_dir = Path(args.out_dir) if args.out_dir else DEFAULT_LONGRUN_ROOT / f"STAGE8_WRITE_STRATEGY_TEST_{suffix}"
    out_dir.mkdir(parents=True, exist_ok=True)
    config_path = Path(args.vector_config) if args.vector_config else Path(__file__).resolve().parent.parent / "config" / "vector_endpoints.yaml"

    jobs_path, extract_files, jobs, job_stats = build_jobs(
        output_root,
        config_path,
        out_dir,
        args.sample_articles,
        args.max_jobs,
        args.card_template,
    )

    embeddings_path = out_dir / "vector_embeddings.strategy_test.jsonl"
    failures_path = out_dir / "vector_failures.strategy_test.jsonl"
    embedding_stats = asyncio.run(run_vector_jobs_async(
        jobs_path,
        embeddings_path,
        failures_path,
        concurrency=max(1, args.embedding_concurrency),
        limit=args.max_jobs,
        resume=True,
        timeout_sec=args.embedding_timeout_sec,
    )).to_dict()

    embeddings = read_jsonl(embeddings_path)
    graph_rows = build_graph_preview(extract_files, out_dir)

    strategy_results: list[StrategyResult] = []
    pc_db_path = out_dir / "pc_stage8_write_test.sqlite"
    strategy_results.append(run_pc_db_test(pc_db_path, embeddings, graph_rows))

    if args.skip_qdrant:
        strategy_results.append(StrategyResult("qdrant_tests", "SKIPPED", {"reason": "--skip-qdrant"}))
    else:
        strategy_results.extend(run_qdrant_tests_guarded(
            embeddings,
            args.qdrant_url,
            out_dir,
            suffix,
            max(1, args.query_count),
            args.keep_qdrant_test_collections,
        ))

    strategy_results.append(run_neo4j_probe(
        args.neo4j_host,
        args.neo4j_bolt_port,
        args.neo4j_http_port,
        graph_rows,
        out_dir,
        enable_write=bool(args.enable_neo4j_write),
        tx_url=args.neo4j_tx_url,
        run_suffix=suffix,
        cleanup=bool(args.cleanup_neo4j_test),
        batch_size=args.neo4j_batch_size,
    ))

    summary = {
        "schema_version": "stage8_write_strategy_test.v1",
        "generated_at": now_iso(),
        "output_root": str(output_root),
        "out_dir": str(out_dir),
        "job_stats": job_stats,
        "embedding_stats": embedding_stats,
        "graph_counts": {
            "nodes": len(graph_rows.get("nodes", [])),
            "edges": len(graph_rows.get("edges", [])),
        },
        "strategy_results": [
            {"name": item.name, "status": item.status, "details": item.details}
            for item in strategy_results
        ],
        "paths": {
            "jobs": str(jobs_path),
            "embeddings": str(embeddings_path),
            "failures": str(failures_path),
            "pc_db": str(pc_db_path),
            "summary_md": str(out_dir / "SUMMARY.md"),
        },
    }
    write_json(out_dir / "summary.json", summary)
    write_report(out_dir, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    hard_fail = any(item.status == "FAIL" for item in strategy_results)
    if embedding_stats.get("failed", 0):
        hard_fail = True
    return 1 if hard_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
