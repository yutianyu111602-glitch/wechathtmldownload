"""Staging-only consumer adapter for Stage7 Qwen3/Qdrant/Neo4j reads.

This adapter is the narrow handoff layer between the completed Stage7 local
vector/graph artifacts and downstream consumer code. It is read-only by
default: no publishing, no production DB writes, no paid API calls, and no D:
drive scans.
"""

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import requests


DEFAULT_OUT_DIR = Path("reports/consumer_staging_adapter_20260514")
DEFAULT_QDRANT_URL = "http://127.0.0.1:6333"
DEFAULT_NEO4J_URI = "http://127.0.0.1:7474"
DEFAULT_NEO4J_DATABASE = "neo4j"
DEFAULT_NEO4J_RUN_ID = "stage7_qwen3_20260514"
DEFAULT_ALIASES = {
    "article": "wechat_stage7_article_qwen3_embedding_4b_1024_current",
    "entity": "wechat_stage7_entity_qwen3_embedding_4b_1024_current",
    "event": "wechat_stage7_event_qwen3_embedding_4b_1024_current",
}
DEFAULT_TYPE_TARGETS = {"event": 4, "entity": 4, "article": 2}


class StagingConsumerConfig:
    """Explicit consumer-facing staging defaults.

    Keep this small and boring: the point is to prevent accidental fallback to
    old Mac vector endpoints, remote services, or production graph scopes.
    """

    def __init__(
        self,
        qdrant_url: str = DEFAULT_QDRANT_URL,
        neo4j_uri: str = DEFAULT_NEO4J_URI,
        neo4j_database: str = DEFAULT_NEO4J_DATABASE,
        neo4j_run_id: str = DEFAULT_NEO4J_RUN_ID,
        aliases: dict[str, str] | None = None,
        type_targets: dict[str, int] | None = None,
        max_per_article: int = 2,
        qdrant_limit: int = 200,
    ) -> None:
        self.qdrant_url = qdrant_url
        self.neo4j_uri = neo4j_uri
        self.neo4j_database = neo4j_database
        self.neo4j_run_id = neo4j_run_id
        self.aliases = dict(aliases or DEFAULT_ALIASES)
        self.type_targets = dict(type_targets or DEFAULT_TYPE_TARGETS)
        self.max_per_article = max_per_article
        self.qdrant_limit = qdrant_limit

    def to_dict(self) -> dict[str, Any]:
        return {
            "qdrant_url": self.qdrant_url,
            "neo4j_uri": self.neo4j_uri,
            "neo4j_database": self.neo4j_database,
            "neo4j_run_id": self.neo4j_run_id,
            "aliases": self.aliases,
            "type_targets": self.type_targets,
            "max_per_article": self.max_per_article,
            "qdrant_limit": self.qdrant_limit,
        }


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    config = report["config"]
    lines = [
        "# Stage7 Consumer Staging Adapter Report",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- mode: `{report['mode']}`",
        f"- ok: `{report['ok']}`",
        f"- qdrant_url: `{config['qdrant_url']}`",
        f"- neo4j_uri: `{config['neo4j_uri']}`",
        f"- neo4j_run_id: `{config['neo4j_run_id']}`",
        "",
        "## Qdrant Aliases",
        "",
    ]
    for kind, alias in config["aliases"].items():
        lines.append(f"- `{kind}` -> `{alias}`")
    lines.extend(
        [
            "",
            "## Serving Policy",
            "",
            f"- type_targets: `{json.dumps(config['type_targets'], ensure_ascii=False)}`",
            f"- max_per_article: `{config['max_per_article']}`",
            "",
            "## Safety",
            "",
            "- Staging-only read path.",
            "- Local Qdrant/Neo4j URLs are required.",
            "- Uses Qwen3 local RTX 4090 aliases; old Mac vector endpoints are not fallback targets.",
            "- No publish, no paid API, no production SQLite, no Qdrant/Neo4j writes, no D: scan.",
        ]
    )
    if report.get("neo4j"):
        lines.extend(["", "## Neo4j Sample", ""])
        for row in report["neo4j"].get("rows", []):
            lines.append(f"- `{row.get('predicate')}` `{row.get('title')}` -> `{row.get('name')}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def require_local_url(url: str, label: str) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError(f"{label} must be local for Stage7 consumer staging adapter: {url}")


def validate_config(config: StagingConsumerConfig) -> None:
    require_local_url(config.qdrant_url, "Qdrant URL")
    require_local_url(config.neo4j_uri, "Neo4j URI")
    for kind, alias in config.aliases.items():
        if kind not in {"article", "entity", "event"}:
            raise ValueError(f"Unsupported Qdrant kind: {kind}")
        if not alias.startswith("wechat_stage7_") or "qwen3_embedding_4b_1024_current" not in alias:
            raise ValueError(f"Qdrant alias must target current local Qwen3 staging alias: {alias}")


def normalize_qdrant_hit(kind: str, hit: dict[str, Any]) -> dict[str, Any]:
    payload = hit.get("payload") or {}
    return {
        "kind": kind,
        "card_id": str(payload.get("card_id") or hit.get("id") or ""),
        "article_uid": str(payload.get("article_uid") or ""),
        "source_account": str(payload.get("source_account") or ""),
        "score": float(hit.get("score") or 0.0),
        "title": str(payload.get("title") or ""),
        "name": str(payload.get("name") or ""),
        "entity_type": str(payload.get("entity_type") or ""),
        "time": str(payload.get("time") or ""),
        "place": str(payload.get("place") or ""),
        "text": str(payload.get("text") or ""),
        "text_sha1": str(payload.get("text_sha1") or ""),
    }


def row_signature(row: dict[str, Any]) -> tuple[str, str]:
    key = str(row.get("text_sha1") or row.get("text") or row.get("card_id") or "")
    return str(row.get("kind") or ""), key


def apply_serving_policy(
    rows: list[dict[str, Any]],
    type_targets: dict[str, int] | None = None,
    max_per_article: int = 2,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    targets = dict(type_targets or DEFAULT_TYPE_TARGETS)
    effective_limit = limit if limit is not None else sum(targets.values())
    selected: list[dict[str, Any]] = []
    seen_signatures: set[tuple[str, str]] = set()
    article_counts: dict[str, int] = {}

    def sorted_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(candidates, key=lambda row: float(row.get("score") or 0.0), reverse=True)

    def take(row: dict[str, Any]) -> bool:
        if len(selected) >= effective_limit:
            return False
        signature = row_signature(row)
        article_uid = str(row.get("article_uid") or "")
        if signature in seen_signatures:
            return False
        if article_uid and article_counts.get(article_uid, 0) >= max_per_article:
            return False
        selected.append(row)
        seen_signatures.add(signature)
        if article_uid:
            article_counts[article_uid] = article_counts.get(article_uid, 0) + 1
        return True

    for kind, target in targets.items():
        taken_for_kind = 0
        for row in sorted_candidates([item for item in rows if item.get("kind") == kind]):
            if taken_for_kind >= target or len(selected) >= effective_limit:
                break
            if take(row):
                taken_for_kind += 1

    if len(selected) < effective_limit:
        for row in sorted_candidates(rows):
            if len(selected) >= effective_limit:
                break
            take(row)

    return selected


def qdrant_search_by_vector(
    config: StagingConsumerConfig,
    kind: str,
    vector: list[float],
    limit: int | None = None,
) -> list[dict[str, Any]]:
    validate_config(config)
    alias = config.aliases[kind]
    base = config.qdrant_url.rstrip("/")
    payload = {"vector": vector, "limit": limit or config.qdrant_limit, "with_payload": True}
    response = requests.post(
        f"{base}/collections/{quote(alias)}/points/search",
        json=payload,
        timeout=180,
    )
    if response.status_code == 404:
        response = requests.post(
            f"{base}/collections/{quote(alias)}/points/query",
            json={"query": vector, "limit": limit or config.qdrant_limit, "with_payload": True},
            timeout=180,
        )
    if response.status_code >= 400:
        raise RuntimeError(f"Qdrant alias search failed {response.status_code}: {response.text[:500]}")
    result = response.json().get("result")
    if isinstance(result, dict):
        result = result.get("points")
    return [normalize_qdrant_hit(kind, item) for item in (result or [])]


def merge_search_results(
    results_by_kind: dict[str, list[dict[str, Any]]],
    config: StagingConsumerConfig,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for kind in config.type_targets:
        rows.extend(results_by_kind.get(kind, []))
    return apply_serving_policy(
        rows,
        type_targets=config.type_targets,
        max_per_article=config.max_per_article,
        limit=limit,
    )


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


def build_neo4j_article_context_statement(
    limit: int = 5,
    run_id: str = DEFAULT_NEO4J_RUN_ID,
) -> dict[str, Any]:
    return {
        "statement": (
            "MATCH (a:Stage7Staging:Article {run_id: $run_id})-[r:STAGE7_EDGE]->(n:Stage7Staging) "
            "RETURN a.node_id AS article_node, a.title AS title, r.predicate AS predicate, "
            "labels(n) AS labels, n.node_id AS target_node, n.name AS name "
            "LIMIT $limit"
        ),
        "parameters": {"run_id": run_id, "limit": limit},
    }


def read_neo4j_article_context(config: StagingConsumerConfig, limit: int = 5) -> dict[str, Any]:
    validate_config(config)
    data = neo4j_commit(
        config.neo4j_uri,
        config.neo4j_database,
        [build_neo4j_article_context_statement(limit=limit, run_id=config.neo4j_run_id)],
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
                "target_node": row[4] if len(row) > 4 else "",
                "name": row[5] if len(row) > 5 else "",
            }
        )
    return {"ok": len(rows) > 0, "rows": rows, "row_count": len(rows)}


def build_config(args: argparse.Namespace) -> StagingConsumerConfig:
    return StagingConsumerConfig(
        qdrant_url=args.qdrant_url,
        neo4j_uri=args.neo4j_uri,
        neo4j_database=args.neo4j_database,
        neo4j_run_id=args.neo4j_run_id,
        max_per_article=args.max_per_article,
        qdrant_limit=args.qdrant_limit,
    )


def run(args: argparse.Namespace) -> int:
    config = build_config(args)
    validate_config(config)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    report: dict[str, Any] = {
        "schema_version": "stage7_consumer_staging_adapter.v1",
        "generated_at": now_iso(),
        "mode": args.mode,
        "ok": True,
        "config": config.to_dict(),
        "writes": "none",
    }
    if args.mode == "neo4j-smoke":
        neo4j = read_neo4j_article_context(config, limit=args.neo4j_limit)
        report["neo4j"] = neo4j
        report["ok"] = bool(neo4j["ok"])

    write_json(args.out_dir / "consumer_staging_adapter.json", report)
    write_markdown(args.out_dir / "consumer_staging_adapter.md", report)
    print(
        json.dumps(
            {
                "ok": report["ok"],
                "mode": args.mode,
                "report": str(args.out_dir / "consumer_staging_adapter.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["ok"] else 2


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("config", "neo4j-smoke"), default="config")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--qdrant-url", default=DEFAULT_QDRANT_URL)
    parser.add_argument("--qdrant-limit", type=int, default=200)
    parser.add_argument("--neo4j-uri", default=DEFAULT_NEO4J_URI)
    parser.add_argument("--neo4j-database", default=DEFAULT_NEO4J_DATABASE)
    parser.add_argument("--neo4j-run-id", default=DEFAULT_NEO4J_RUN_ID)
    parser.add_argument("--neo4j-limit", type=int, default=5)
    parser.add_argument("--max-per-article", type=int, default=2)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
