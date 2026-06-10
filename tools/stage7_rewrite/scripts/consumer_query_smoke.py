"""Read-only consumer query smoke for Qdrant aliases and Neo4j staging graph.

Uses existing vectors from the local Qwen3 artifact to query the promoted
Stage7 Qdrant aliases, then verifies a small Neo4j Stage7Staging graph read.
No writes, no model loading, no paid APIs, no production publish, and no D: scan.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import numpy as np
import requests


DEFAULT_VECTOR_DIR = Path("reports/vector_full_qwen3_4b_1024_20260514")
DEFAULT_OUT_DIR = Path("reports/consumer_query_smoke_20260514")
DEFAULT_QDRANT_URL = "http://127.0.0.1:6333"
DEFAULT_NEO4J_URI = "http://127.0.0.1:7474"
DEFAULT_NEO4J_RUN_ID = "stage7_qwen3_20260514"
DEFAULT_PROMOTION_RUN_ID = "stage7_production_graph_20260515"
KINDS = ("article", "entity", "event")
ALIASES = {
    "article": "wechat_stage7_article_qwen3_embedding_4b_1024_current",
    "entity": "wechat_stage7_entity_qwen3_embedding_4b_1024_current",
    "event": "wechat_stage7_event_qwen3_embedding_4b_1024_current",
}


def require_local_url(url: str, label: str) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError(f"{label} must be local for consumer query smoke: {url}")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def text_sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()


def iter_card_rows(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        for idx, line in enumerate(handle):
            stripped = line.strip()
            if not stripped:
                continue
            row = json.loads(stripped)
            row["_vector_index"] = idx
            yield row


def select_rows(card_texts_path: Path, per_kind: int) -> dict[str, list[dict[str, Any]]]:
    selected: dict[str, list[dict[str, Any]]] = {kind: [] for kind in KINDS}
    for row in iter_card_rows(card_texts_path):
        kind = str(row.get("type") or "")
        if kind in selected and len(selected[kind]) < per_kind:
            selected[kind].append(row)
        if all(len(rows) >= per_kind for rows in selected.values()):
            break
    return selected


def qdrant_search(qdrant_url: str, alias: str, vector: list[float], limit: int) -> list[dict[str, Any]]:
    base = qdrant_url.rstrip("/")
    response = requests.post(
        f"{base}/collections/{quote(alias)}/points/search",
        json={"vector": vector, "limit": limit, "with_payload": True},
        timeout=180,
    )
    if response.status_code == 404:
        response = requests.post(
            f"{base}/collections/{quote(alias)}/points/query",
            json={"query": vector, "limit": limit, "with_payload": True},
            timeout=180,
        )
    if response.status_code >= 400:
        raise RuntimeError(f"Qdrant alias search failed {response.status_code}: {response.text[:500]}")
    result = response.json().get("result")
    if isinstance(result, dict):
        result = result.get("points")
    return result or []


def smoke_qdrant_aliases(qdrant_url: str, vector_dir: Path, per_kind: int, limit: int) -> dict[str, Any]:
    selected = select_rows(vector_dir / "card_texts.jsonl", per_kind)
    vectors = np.load(vector_dir / "vectors.npy", mmap_mode="r")
    details = []
    total = 0
    equivalent = 0
    for kind, rows in selected.items():
        alias = ALIASES[kind]
        for row in rows:
            total += 1
            vector = np.asarray(vectors[int(row["_vector_index"])], dtype="float32").tolist()
            hits = qdrant_search(qdrant_url, alias, vector, limit)
            first = hits[0] if hits else {}
            payload = first.get("payload") or {}
            expected_hash = text_sha1(str(row.get("text") or ""))
            exact_ok = payload.get("card_id") == row.get("id")
            equivalent_ok = exact_ok or (
                payload.get("card_type") == row.get("type")
                and payload.get("text_sha1") == expected_hash
            )
            equivalent += int(equivalent_ok)
            details.append(
                {
                    "kind": kind,
                    "alias": alias,
                    "expected_card_id": row.get("id"),
                    "hit_card_id": payload.get("card_id"),
                    "hit_type": payload.get("card_type"),
                    "exact_ok": exact_ok,
                    "equivalent_ok": equivalent_ok,
                    "hit_count": len(hits),
                    "score": first.get("score"),
                }
            )
    return {
        "ok": total > 0 and equivalent == total,
        "checked": total,
        "equivalent": equivalent,
        "equivalent_rate": round(equivalent / max(total, 1), 4),
        "details": details,
    }


def neo4j_commit(neo4j_uri: str, database: str, statements: list[dict[str, Any]]) -> dict[str, Any]:
    response = requests.post(
        f"{neo4j_uri.rstrip('/')}/db/{database}/tx/commit",
        json={"statements": statements},
        timeout=60,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Neo4j commit failed {response.status_code}: {response.text[:500]}")
    data = response.json()
    if data.get("errors"):
        raise RuntimeError(f"Neo4j returned errors: {json.dumps(data['errors'][:3], ensure_ascii=False)}")
    return data


def smoke_neo4j_graph(
    neo4j_uri: str,
    database: str,
    run_id: str,
    limit: int,
    *,
    use_production_labels: bool = False,
    promotion_run_id: str = DEFAULT_PROMOTION_RUN_ID,
) -> dict[str, Any]:
    if use_production_labels:
        statement = (
            "MATCH (a:Article {run_id: $run_id, promotion_run_id: $promotion_run_id})-[r:STAGE7_EDGE]->(n) "
            "WHERE (n:Entity OR n:Event) AND n.promotion_run_id = $promotion_run_id "
            "RETURN a.node_id AS article_node, a.title AS title, r.predicate AS predicate, "
            "labels(n) AS labels, n.name AS name "
            "LIMIT $limit"
        )
        parameters = {"run_id": run_id, "promotion_run_id": promotion_run_id, "limit": limit}
        label_mode = "production"
    else:
        statement = (
            "MATCH (a:Stage7Staging:Article {run_id: $run_id})-[r:STAGE7_EDGE]->(n:Stage7Staging) "
            "RETURN a.node_id AS article_node, a.title AS title, r.predicate AS predicate, "
            "labels(n) AS labels, n.name AS name "
            "LIMIT $limit"
        )
        parameters = {"run_id": run_id, "limit": limit}
        label_mode = "staging"
    data = neo4j_commit(
        neo4j_uri,
        database,
        [
            {
                "statement": statement,
                "parameters": parameters,
            }
        ],
    )
    rows = []
    for item in ((data.get("results") or [{}])[0].get("data") or []):
        row = item.get("row") or []
        rows.append(
            {
                "article_node": row[0] if len(row) > 0 else "",
                "title": row[1] if len(row) > 1 else "",
                "predicate": row[2] if len(row) > 2 else "",
                "labels": row[3] if len(row) > 3 else [],
                "name": row[4] if len(row) > 4 else "",
            }
        )
    return {"ok": len(rows) > 0, "rows": rows, "row_count": len(rows), "label_mode": label_mode}


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Stage7 Consumer Query Smoke",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- ok: `{report['ok']}`",
        f"- qdrant_ok: `{report['qdrant']['ok']}`",
        f"- neo4j_ok: `{report['neo4j']['ok']}`",
        f"- neo4j_label_mode: `{report['neo4j'].get('label_mode')}`",
        "",
        "## Qdrant Alias Queries",
        "",
    ]
    for item in report["qdrant"]["details"]:
        lines.append(
            f"- `{item['kind']}` alias `{item['alias']}` expected `{item['expected_card_id']}` "
            f"hit `{item['hit_card_id']}` equivalent=`{item['equivalent_ok']}` score=`{item['score']}`"
        )
    lines.extend(["", "## Neo4j Graph Rows", ""])
    for row in report["neo4j"]["rows"]:
        lines.append(f"- `{row['predicate']}` `{row['title']}` -> `{row['name']}` labels=`{row['labels']}`")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Read-only: no Qdrant/Neo4j writes, no production SQLite, no publish, no paid API, no D: scan.",
            "- Uses Qwen3 Stage7 aliases and the selected Neo4j label mode only.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    require_local_url(args.qdrant_url, "Qdrant URL")
    require_local_url(args.neo4j_uri, "Neo4j URI")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    qdrant = smoke_qdrant_aliases(args.qdrant_url, args.vector_dir, args.per_kind, args.qdrant_limit)
    neo4j = smoke_neo4j_graph(
        args.neo4j_uri,
        args.neo4j_database,
        args.neo4j_run_id,
        args.neo4j_limit,
        use_production_labels=args.use_production_labels,
        promotion_run_id=args.promotion_run_id,
    )
    report = {
        "schema_version": "stage7_consumer_query_smoke.v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "ok": qdrant["ok"] and neo4j["ok"],
        "vector_dir": str(args.vector_dir),
        "qdrant_url": args.qdrant_url,
        "neo4j_uri": args.neo4j_uri,
        "neo4j_database": args.neo4j_database,
        "neo4j_run_id": args.neo4j_run_id,
        "promotion_run_id": args.promotion_run_id,
        "use_production_labels": args.use_production_labels,
        "qdrant": qdrant,
        "neo4j": neo4j,
        "writes": "none",
    }
    write_json(args.out_dir / "consumer_query_smoke.json", report)
    write_markdown(args.out_dir / "consumer_query_smoke.md", report)
    print(json.dumps({"ok": report["ok"], "report": str(args.out_dir / "consumer_query_smoke.json")}, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 2


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vector-dir", type=Path, default=DEFAULT_VECTOR_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--qdrant-url", default=DEFAULT_QDRANT_URL)
    parser.add_argument("--qdrant-limit", type=int, default=10)
    parser.add_argument("--per-kind", type=int, default=1)
    parser.add_argument("--neo4j-uri", default=DEFAULT_NEO4J_URI)
    parser.add_argument("--neo4j-database", default="neo4j")
    parser.add_argument("--neo4j-run-id", default=DEFAULT_NEO4J_RUN_ID)
    parser.add_argument("--neo4j-limit", type=int, default=5)
    parser.add_argument("--use-production-labels", action="store_true")
    parser.add_argument("--promotion-run-id", default=DEFAULT_PROMOTION_RUN_ID)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
