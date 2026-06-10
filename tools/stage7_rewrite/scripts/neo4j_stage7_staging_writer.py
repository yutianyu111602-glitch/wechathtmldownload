"""Build and optionally write Stage7 stable graph candidates to Neo4j staging.

Default mode is dry-run. Any Neo4j mutation requires an explicit confirmation
token. The writer is staging-only: every node carries `Stage7Staging` and a
run_id, and relationships use a single `STAGE7_EDGE` type with a predicate
property so rollback is deterministic.

This script does not scan D:, call paid APIs, write production SQLite, touch
Qdrant aliases, or publish consumer data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests


DEFAULT_STABLE_JSONL = Path(
    "reports/fullmap_47k_ready_text_authok_20260513_174006/"
    "stable_extract_v1/stable_articles.jsonl"
)
DEFAULT_OUT_DIR = Path("reports/neo4j_stage7_staging_20260514")
DEFAULT_NEO4J_URI = "http://127.0.0.1:7474"
DEFAULT_RUN_ID = "stage7_qwen3_20260514"
CONFIRM_TOKEN = "ENABLE_NEO4J_STAGE7_STAGING_WRITE"
NODE_KINDS = ("article", "entity", "event")


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def sha1_text(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()


def short_hash(text: str, length: int = 16) -> str:
    return sha1_text(text)[:length]


def norm_text(value: Any) -> str:
    return str(value or "").strip()


def json_prop(value: Any) -> str:
    return json.dumps(value if value is not None else [], ensure_ascii=False, sort_keys=True)


def require_local_neo4j(uri: str) -> None:
    parsed = urlparse(uri)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError(f"Neo4j URI must be local for this staging writer: {uri}")


def article_node_id(article_uid: str) -> str:
    return f"art:{short_hash(article_uid)}"


def entity_node_id(article_uid: str, entity: dict[str, Any], ordinal: int) -> str:
    local_id = norm_text(entity.get("entity_id"))
    name = norm_text(entity.get("name"))
    key = local_id or f"{ordinal}:{name.lower()}"
    return f"ent:{short_hash(article_uid)}:{short_hash(key)}"


def event_node_id(article_uid: str, event: dict[str, Any], ordinal: int) -> str:
    local_id = norm_text(event.get("event_id"))
    name = norm_text(event.get("name"))
    time_text = norm_text(event.get("time") or event.get("time_text"))
    key = local_id or f"{ordinal}:{name.lower()}:{time_text}"
    return f"evt:{short_hash(article_uid)}:{short_hash(key)}"


def edge_id(run_id: str, subject_id: str, predicate: str, object_id: str, article_uid: str, ordinal: int) -> str:
    return f"edge:{short_hash(f'{run_id}|{article_uid}|{ordinal}|{subject_id}|{predicate}|{object_id}', 24)}"


def evidence_count(items: Any) -> int:
    return len(items) if isinstance(items, list) else 0


def evidence_text(items: Any, limit: int = 3) -> str:
    if not isinstance(items, list):
        return ""
    quotes = [norm_text(item.get("quote")) for item in items if isinstance(item, dict) and norm_text(item.get("quote"))]
    return " | ".join(quotes[:limit])


def confidence(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def build_graph_rows(article: dict[str, Any], run_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    article_uid = norm_text(article.get("article_uid"))
    if not article_uid:
        return [], []

    article_id = article_node_id(article_uid)
    nodes: list[dict[str, Any]] = [
        {
            "node_id": article_id,
            "node_kind": "article",
            "run_id": run_id,
            "article_uid": article_uid,
            "article_id": norm_text(article.get("article_id")),
            "source_account": norm_text(article.get("source_account")),
            "title": norm_text(article.get("title")),
            "name": norm_text(article.get("title")) or article_uid,
            "quality_grade": norm_text(article.get("quality_grade")),
            "input_chars": int(article.get("input_chars") or 0),
            "raw_json": "",
        }
    ]
    edges: list[dict[str, Any]] = []
    name_to_node: dict[str, str] = {}
    seq = 0

    entities = article.get("entities") or []
    if not isinstance(entities, list):
        entities = []
    for idx, ent in enumerate(entities, start=1):
        if not isinstance(ent, dict):
            continue
        name = norm_text(ent.get("name"))
        if not name:
            continue
        node_id = entity_node_id(article_uid, ent, idx)
        name_to_node.setdefault(name, node_id)
        nodes.append(
            {
                "node_id": node_id,
                "node_kind": "entity",
                "run_id": run_id,
                "article_uid": article_uid,
                "source_account": norm_text(article.get("source_account")),
                "name": name,
                "entity_type": norm_text(ent.get("type") or "unknown"),
                "bio": norm_text(ent.get("bio") or ent.get("description")),
                "aliases_json": json_prop(ent.get("aliases") or []),
                "source_kind": norm_text(ent.get("source_kind") or ent.get("source")),
                "confidence": confidence(ent.get("confidence")),
                "evidence_count": evidence_count(ent.get("evidence")),
                "raw_json": json_prop(ent),
            }
        )
        seq += 1
        edges.append(
            {
                "edge_id": edge_id(run_id, article_id, "ARTICLE_MENTIONS_ENTITY", node_id, article_uid, seq),
                "run_id": run_id,
                "subject_id": article_id,
                "object_id": node_id,
                "predicate": "ARTICLE_MENTIONS_ENTITY",
                "article_uid": article_uid,
                "source_account": norm_text(article.get("source_account")),
                "confidence": confidence(ent.get("confidence")),
                "evidence_count": evidence_count(ent.get("evidence")),
                "evidence_text": evidence_text(ent.get("evidence")),
                "raw_json": "",
            }
        )

    events = article.get("events") or []
    if not isinstance(events, list):
        events = []
    for idx, event in enumerate(events, start=1):
        if not isinstance(event, dict):
            continue
        name = norm_text(event.get("name"))
        if not name:
            continue
        node_id = event_node_id(article_uid, event, idx)
        name_to_node.setdefault(name, node_id)
        nodes.append(
            {
                "node_id": node_id,
                "node_kind": "event",
                "run_id": run_id,
                "article_uid": article_uid,
                "source_account": norm_text(article.get("source_account")),
                "name": name,
                "time_text": norm_text(event.get("time") or event.get("time_text")),
                "place_text": norm_text(event.get("place") or event.get("place_text")),
                "participants_json": json_prop(event.get("participants") or []),
                "confidence": confidence(event.get("confidence")),
                "evidence_count": evidence_count(event.get("evidence")),
                "raw_json": json_prop(event),
            }
        )
        seq += 1
        edges.append(
            {
                "edge_id": edge_id(run_id, article_id, "ARTICLE_REPORTS_EVENT", node_id, article_uid, seq),
                "run_id": run_id,
                "subject_id": article_id,
                "object_id": node_id,
                "predicate": "ARTICLE_REPORTS_EVENT",
                "article_uid": article_uid,
                "source_account": norm_text(article.get("source_account")),
                "confidence": confidence(event.get("confidence")),
                "evidence_count": evidence_count(event.get("evidence")),
                "evidence_text": evidence_text(event.get("evidence")),
                "raw_json": "",
            }
        )

    relations = article.get("relations") or []
    if not isinstance(relations, list):
        relations = []
    for rel in relations:
        if not isinstance(rel, dict):
            continue
        subject_name = norm_text(rel.get("subject") or rel.get("subject_name"))
        object_name = norm_text(rel.get("object") or rel.get("object_name"))
        subject_id = name_to_node.get(subject_name)
        object_id = name_to_node.get(object_name)
        if not subject_id or not object_id:
            continue
        predicate = norm_text(rel.get("predicate") or "RELATED_TO").upper().replace(" ", "_")
        seq += 1
        edges.append(
            {
                "edge_id": edge_id(run_id, subject_id, predicate, object_id, article_uid, seq),
                "run_id": run_id,
                "subject_id": subject_id,
                "object_id": object_id,
                "predicate": predicate,
                "article_uid": article_uid,
                "source_account": norm_text(article.get("source_account")),
                "confidence": confidence(rel.get("confidence")),
                "evidence_count": evidence_count(rel.get("evidence")),
                "evidence_text": evidence_text(rel.get("evidence")),
                "raw_json": json_prop(rel),
            }
        )

    return nodes, edges


def auth_tuple() -> tuple[str, str] | None:
    user = os.environ.get("NEO4J_USER")
    password = os.environ.get("NEO4J_PASSWORD")
    if user and password:
        return user, password
    return None


def neo4j_commit(uri: str, database: str, statements: list[dict[str, Any]]) -> dict[str, Any]:
    endpoint = f"{uri.rstrip('/')}/db/{database}/tx/commit"
    response = requests.post(endpoint, json={"statements": statements}, auth=auth_tuple(), timeout=120)
    if response.status_code >= 400:
        raise RuntimeError(f"Neo4j commit failed {response.status_code}: {response.text[:500]}")
    data = response.json()
    errors = data.get("errors") or []
    if errors:
        raise RuntimeError(f"Neo4j returned errors: {json.dumps(errors[:3], ensure_ascii=False)}")
    return data


def constraint_statements() -> list[dict[str, Any]]:
    return [
        {
            "statement": (
                "CREATE CONSTRAINT stage7_staging_node_id IF NOT EXISTS "
                "FOR (n:Stage7Staging) REQUIRE n.node_id IS UNIQUE"
            )
        }
    ]


def node_statement(kind: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    labels = {
        "article": "Stage7Staging:Article",
        "entity": "Stage7Staging:Entity",
        "event": "Stage7Staging:Event",
    }[kind]
    return {
        "statement": (
            f"UNWIND $rows AS row "
            f"MERGE (n:{labels} {{node_id: row.node_id}}) "
            f"SET n += row, n.updated_at = datetime()"
        ),
        "parameters": {"rows": rows},
    }


def edge_statement(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "statement": (
            "UNWIND $rows AS row "
            "MATCH (s:Stage7Staging {node_id: row.subject_id}) "
            "MATCH (o:Stage7Staging {node_id: row.object_id}) "
            "MERGE (s)-[r:STAGE7_EDGE {edge_id: row.edge_id}]->(o) "
            "SET r += row, r.updated_at = datetime()"
        ),
        "parameters": {"rows": rows},
    }


def rollback_statement(run_id: str) -> dict[str, Any]:
    return {
        "statement": (
            "MATCH (n:Stage7Staging {run_id: $run_id}) "
            "DETACH DELETE n"
        ),
        "parameters": {"run_id": run_id},
    }


def count_statement(run_id: str) -> dict[str, Any]:
    return {
        "statement": (
            "MATCH (n:Stage7Staging {run_id: $run_id}) "
            "WITH count(n) AS nodes "
            "MATCH ()-[r:STAGE7_EDGE {run_id: $run_id}]->() "
            "RETURN nodes, count(r) AS edges"
        ),
        "parameters": {"run_id": run_id},
    }


def load_state(path: Path, resume: bool) -> dict[str, Any]:
    if resume and path.exists():
        return read_json(path)
    return {
        "schema_version": "stage7_neo4j_staging_state.v1",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "next_line": 0,
        "articles_seen": 0,
        "nodes_written": 0,
        "edges_written": 0,
        "complete": False,
    }


def flush_batch(
    *,
    mode: str,
    uri: str,
    database: str,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> tuple[int, int]:
    if not nodes and not edges:
        return 0, 0
    if mode == "dry-run":
        return len(nodes), len(edges)
    by_kind: dict[str, list[dict[str, Any]]] = {kind: [] for kind in NODE_KINDS}
    for node in nodes:
        kind = node.get("node_kind")
        if kind in by_kind:
            by_kind[kind].append(node)
    statements = []
    for kind in NODE_KINDS:
        if by_kind[kind]:
            statements.append(node_statement(kind, by_kind[kind]))
    if edges:
        statements.append(edge_statement(edges))
    neo4j_commit(uri, database, statements)
    return len(nodes), len(edges)


def run(args: argparse.Namespace) -> int:
    require_local_neo4j(args.neo4j_uri)
    if args.mode in {"canary", "apply", "rollback"} and args.confirm_token != CONFIRM_TOKEN:
        raise SystemExit(f"--confirm-token {CONFIRM_TOKEN} required for Neo4j mutations")
    if not args.stable_jsonl.exists() and args.mode != "rollback":
        raise SystemExit(f"stable jsonl not found: {args.stable_jsonl}")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    report_path = args.out_dir / "neo4j_stage7_staging_report.json"
    state_path = args.out_dir / "neo4j_stage7_staging_state.json"

    if args.mode == "rollback":
        neo4j_commit(args.neo4j_uri, args.database, [rollback_statement(args.run_id)])
        report = {
            "schema_version": "stage7_neo4j_staging_report.v1",
            "generated_at": now_iso(),
            "mode": args.mode,
            "run_id": args.run_id,
            "rolled_back": True,
            "rollback_statement": rollback_statement(args.run_id)["statement"],
            "secrets_printed": False,
        }
        write_json(report_path, report)
        write_markdown(args.out_dir / "neo4j_stage7_staging_report.md", report)
        print(json.dumps({"ok": True, "rolled_back": True, "report": str(report_path)}, ensure_ascii=False, indent=2))
        return 0

    if args.mode in {"canary", "apply"}:
        neo4j_commit(args.neo4j_uri, args.database, constraint_statements())

    state = load_state(state_path, args.resume)
    start_line = int(state.get("next_line") or 0)
    limit = int(args.limit or 0)
    max_articles = limit if args.mode == "dry-run" else (limit or (args.canary_limit if args.mode == "canary" else 0))
    node_counter: Counter[str] = Counter()
    edge_counter: Counter[str] = Counter()
    batch_nodes: list[dict[str, Any]] = []
    batch_edges: list[dict[str, Any]] = []
    articles_processed = 0
    lines_seen = 0
    last_processed_line = start_line - 1
    started = time.time()

    with args.stable_jsonl.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle):
            if line_no < start_line:
                continue
            stripped = line.strip()
            if not stripped:
                state["next_line"] = line_no + 1
                continue
            article = json.loads(stripped)
            last_processed_line = line_no
            nodes, edges = build_graph_rows(article, args.run_id)
            lines_seen += 1
            articles_processed += 1
            for node in nodes:
                node_counter[str(node.get("node_kind"))] += 1
            for edge in edges:
                edge_counter[str(edge.get("predicate"))] += 1
            batch_nodes.extend(nodes)
            batch_edges.extend(edges)
            if len(batch_nodes) >= args.batch_nodes or len(batch_edges) >= args.batch_edges:
                written_nodes, written_edges = flush_batch(
                    mode=args.mode,
                    uri=args.neo4j_uri,
                    database=args.database,
                    nodes=batch_nodes,
                    edges=batch_edges,
                )
                state["nodes_written"] = int(state.get("nodes_written") or 0) + written_nodes
                state["edges_written"] = int(state.get("edges_written") or 0) + written_edges
                state["articles_seen"] = int(state.get("articles_seen") or 0) + articles_processed
                state["next_line"] = line_no + 1
                state["updated_at"] = now_iso()
                write_json(state_path, state)
                batch_nodes = []
                batch_edges = []
                articles_processed = 0
            if max_articles and lines_seen >= max_articles:
                state["next_line"] = line_no + 1
                break

    written_nodes, written_edges = flush_batch(
        mode=args.mode,
        uri=args.neo4j_uri,
        database=args.database,
        nodes=batch_nodes,
        edges=batch_edges,
    )
    state["nodes_written"] = int(state.get("nodes_written") or 0) + written_nodes
    state["edges_written"] = int(state.get("edges_written") or 0) + written_edges
    state["articles_seen"] = int(state.get("articles_seen") or 0) + articles_processed
    if last_processed_line >= start_line:
        state["next_line"] = last_processed_line + 1
    state["updated_at"] = now_iso()
    state["complete"] = not max_articles
    write_json(state_path, state)

    live_counts = None
    if args.mode in {"canary", "apply"}:
        result = neo4j_commit(args.neo4j_uri, args.database, [count_statement(args.run_id)])
        rows = (((result.get("results") or [{}])[0].get("data") or [{}])[0].get("row") or [])
        if len(rows) >= 2:
            live_counts = {"nodes": rows[0], "edges": rows[1]}

    report = {
        "schema_version": "stage7_neo4j_staging_report.v1",
        "generated_at": now_iso(),
        "mode": args.mode,
        "run_id": args.run_id,
        "stable_jsonl": str(args.stable_jsonl),
        "out_dir": str(args.out_dir),
        "neo4j_uri": args.neo4j_uri,
        "database": args.database,
        "limit": limit,
        "canary_limit": args.canary_limit,
        "duration_sec": round(time.time() - started, 3),
        "line_start": start_line,
        "lines_seen_this_run": lines_seen,
        "node_counter_this_run": dict(node_counter),
        "edge_counter_this_run": dict(edge_counter),
        "state": state,
        "live_counts": live_counts,
        "rollback_command": (
            f"python scripts\\neo4j_stage7_staging_writer.py --mode rollback "
            f"--run-id {args.run_id} --confirm-token {CONFIRM_TOKEN}"
        ),
        "secrets_printed": False,
        "notes": [
            "Staging-only labels/properties; no production labels or consumer publish.",
            "Relationships use STAGE7_EDGE with predicate property for safe rollback.",
            "Dry-run reads the C: stable JSONL only and does not contact Neo4j for writes.",
            "nodes_written is submitted node rows; live_counts.nodes is unique Neo4j nodes after MERGE.",
        ],
    }
    write_json(report_path, report)
    write_markdown(args.out_dir / "neo4j_stage7_staging_report.md", report)
    print(json.dumps({"ok": True, "mode": args.mode, "report": str(report_path), "live_counts": live_counts}, ensure_ascii=False, indent=2))
    return 0


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    state = report.get("state") or {}
    node_counts = report.get("node_counter_this_run") or {}
    edge_counts = report.get("edge_counter_this_run") or {}
    lines = [
        "# Neo4j Stage7 Staging Writer Report",
        "",
        f"- generated_at: `{report.get('generated_at')}`",
        f"- mode: `{report.get('mode')}`",
        f"- run_id: `{report.get('run_id')}`",
        f"- stable_jsonl: `{report.get('stable_jsonl')}`",
        f"- live_counts: `{json.dumps(report.get('live_counts'), ensure_ascii=False)}`",
        "",
        "## Progress",
        "",
        f"- lines_seen_this_run: `{report.get('lines_seen_this_run')}`",
        f"- state_next_line: `{state.get('next_line')}`",
        f"- state_nodes_written: `{state.get('nodes_written')}`",
        f"- state_edges_written: `{state.get('edges_written')}`",
        f"- complete: `{state.get('complete')}`",
        "",
        "## Node Counts This Run",
        "",
    ]
    for key in sorted(node_counts):
        lines.append(f"- `{key}`: {node_counts[key]}")
    lines.extend(["", "## Edge Counts This Run", ""])
    for key, value in sorted(edge_counts.items(), key=lambda item: (-int(item[1]), str(item[0]))):
        lines.append(f"- `{key}`: {value}")
    lines.extend(
        [
            "",
            "## Rollback",
            "",
            f"`{report.get('rollback_command')}`",
            "",
            "## Safety",
            "",
            "- No D: scan, no paid API, no production SQLite, no Qdrant alias change, no consumer publish.",
            "- All staging nodes have `Stage7Staging` and `run_id`; rollback is by `run_id`.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["dry-run", "canary", "apply", "rollback"], default="dry-run")
    parser.add_argument("--stable-jsonl", type=Path, default=DEFAULT_STABLE_JSONL)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--neo4j-uri", default=DEFAULT_NEO4J_URI)
    parser.add_argument("--database", default="neo4j")
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--limit", type=int, default=1000, help="0 means all. Dry-run default is bounded.")
    parser.add_argument("--canary-limit", type=int, default=1000)
    parser.add_argument("--batch-nodes", type=int, default=5000)
    parser.add_argument("--batch-edges", type=int, default=5000)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--confirm-token", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
