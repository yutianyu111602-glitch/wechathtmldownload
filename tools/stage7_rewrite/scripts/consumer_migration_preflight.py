"""Read-only consumer migration preflight for Stage7 Qwen3/Qdrant/Neo4j assets.

The preflight verifies that downstream consumers can explicitly target the new
Qwen3 Stage7 Qdrant aliases and the Neo4j Stage7Staging graph. It writes only
reports under C: and does not publish, upload, mutate DBs, call paid APIs, or
scan D:.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import requests


DEFAULT_OUT_DIR = Path("reports/consumer_migration_preflight_20260514")
DEFAULT_QDRANT_URL = "http://127.0.0.1:6333"
DEFAULT_NEO4J_URI = "http://127.0.0.1:7474"
DEFAULT_NEO4J_RUN_ID = "stage7_qwen3_20260514"
STABLE_SUMMARY = Path(
    "reports/fullmap_47k_ready_text_authok_20260513_174006/"
    "stable_extract_v1/stable_materialize_summary.json"
)
STABLE_REPAIR_GATE = Path(
    "reports/fullmap_47k_ready_text_authok_20260513_174006/"
    "stable_extract_v1/stable_repair_gate_summary.json"
)
CONSUMER_FILES = {
    "master_plan": Path("MASTER_PLAN_20260513.md"),
    "consumer_schema": Path("FINAL_CONSUMER_SCHEMA_20260510.md"),
    "weekly_pipeline": Path("weekly_activity_next_week_pipeline.ps1"),
    "weekly_app": Path("../../apps/weekly_activity_miniprogram"),
}
EXPECTED_QDRANT = {
    "article": {
        "alias": "wechat_stage7_article_qwen3_embedding_4b_1024_current",
        "collection": "wechat_stage7_article_qwen3_embedding_4b_1024_20260514_full_staging",
        "count": 45568,
    },
    "entity": {
        "alias": "wechat_stage7_entity_qwen3_embedding_4b_1024_current",
        "collection": "wechat_stage7_entity_qwen3_embedding_4b_1024_20260514_full_staging",
        "count": 516421,
    },
    "event": {
        "alias": "wechat_stage7_event_qwen3_embedding_4b_1024_current",
        "collection": "wechat_stage7_event_qwen3_embedding_4b_1024_20260514_full_staging",
        "count": 219296,
    },
}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def require_local_url(url: str, label: str) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError(f"{label} must be local for consumer migration preflight: {url}")


def qdrant_request(qdrant_url: str, path: str) -> dict[str, Any]:
    response = requests.get(f"{qdrant_url.rstrip('/')}{path}", timeout=30)
    if response.status_code >= 400:
        raise RuntimeError(f"Qdrant GET {path} failed {response.status_code}: {response.text[:500]}")
    return response.json()


def qdrant_aliases(qdrant_url: str) -> dict[str, str]:
    data = qdrant_request(qdrant_url, "/aliases")
    rows = ((data.get("result") or {}).get("aliases") or [])
    return {row["alias_name"]: row["collection_name"] for row in rows}


def qdrant_collection_info(qdrant_url: str, collection: str) -> dict[str, Any]:
    data = qdrant_request(qdrant_url, f"/collections/{quote(collection)}")
    return data.get("result") or {}


def check_qdrant(qdrant_url: str) -> dict[str, Any]:
    aliases = qdrant_aliases(qdrant_url)
    rows: dict[str, dict[str, Any]] = {}
    ok = True
    for kind, expected in EXPECTED_QDRANT.items():
        alias = expected["alias"]
        target = aliases.get(alias)
        info = qdrant_collection_info(qdrant_url, expected["collection"])
        optimizer_status = info.get("optimizer_status")
        points_count = int(info.get("points_count") or 0)
        item_ok = (
            target == expected["collection"]
            and info.get("status") == "green"
            and (optimizer_status == "ok" or optimizer_status is None)
            and points_count == expected["count"]
        )
        ok = ok and item_ok
        rows[kind] = {
            "ok": item_ok,
            "alias": alias,
            "alias_target": target,
            "expected_target": expected["collection"],
            "status": info.get("status"),
            "optimizer_status": optimizer_status,
            "points_count": points_count,
            "expected_count": expected["count"],
            "indexed_vectors_count": info.get("indexed_vectors_count"),
        }
    return {"ok": ok, "aliases": rows}


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


def check_neo4j(neo4j_uri: str, database: str, run_id: str) -> dict[str, Any]:
    statements = [
        {
            "statement": (
                "MATCH (n:Stage7Staging {run_id: $run_id}) "
                "RETURN labels(n) AS labels, count(n) AS count ORDER BY count DESC"
            ),
            "parameters": {"run_id": run_id},
        },
        {
            "statement": (
                "MATCH ()-[r:STAGE7_EDGE {run_id: $run_id}]->() "
                "RETURN r.predicate AS predicate, count(r) AS count ORDER BY count DESC"
            ),
            "parameters": {"run_id": run_id},
        },
    ]
    data = neo4j_commit(neo4j_uri, database, statements)
    results = data.get("results") or []
    label_counts: dict[str, int] = {}
    edge_counts: dict[str, int] = {}
    if results:
        for row in results[0].get("data") or []:
            labels, count = row.get("row") or [[], 0]
            label = next((item for item in labels if item != "Stage7Staging"), "Unknown")
            label_counts[label] = int(count)
    if len(results) > 1:
        for row in results[1].get("data") or []:
            predicate, count = row.get("row") or ["", 0]
            edge_counts[str(predicate)] = int(count)
    expected_labels = {"Article": 45568, "Entity": 313691, "Event": 57058}
    expected_edges = {"ARTICLE_MENTIONS_ENTITY": 516421, "ARTICLE_REPORTS_EVENT": 219296}
    ok = label_counts == expected_labels and edge_counts == expected_edges
    return {
        "ok": ok,
        "run_id": run_id,
        "labels": label_counts,
        "expected_labels": expected_labels,
        "edges": edge_counts,
        "expected_edges": expected_edges,
        "node_total": sum(label_counts.values()),
        "edge_total": sum(edge_counts.values()),
    }


def check_files(root: Path) -> dict[str, Any]:
    rows = {}
    ok = True
    for key, rel in CONSUMER_FILES.items():
        path = (root / rel).resolve()
        exists = path.exists()
        ok = ok and exists
        rows[key] = {"exists": exists, "path": str(path)}
    return {"ok": ok, "files": rows}


def stable_summary() -> dict[str, Any]:
    summary = read_json(STABLE_SUMMARY) if STABLE_SUMMARY.exists() else {}
    repair = read_json(STABLE_REPAIR_GATE) if STABLE_REPAIR_GATE.exists() else {}
    return {
        "summary_path": str(STABLE_SUMMARY),
        "repair_gate_path": str(STABLE_REPAIR_GATE),
        "summary": summary,
        "repair_gate": repair,
    }


def build_decision(report: dict[str, Any]) -> dict[str, Any]:
    blockers = []
    if not report["consumer_files"]["ok"]:
        blockers.append("consumer entry files missing")
    if not report["qdrant"]["ok"]:
        blockers.append("qdrant alias/count/health check failed")
    if not report["neo4j"]["ok"]:
        blockers.append("neo4j staging count check failed")
    if blockers:
        status = "blocked"
    else:
        status = "ready_for_consumer_staging_plan"
    return {
        "status": status,
        "blockers": blockers,
        "allowed_next": [
            "write consumer migration adapter plan against Qwen3 Stage7 aliases",
            "build read-only API/query smoke for weekly/search consumers",
            "stage a release pack only after schema validation and rollback pointer are written",
        ],
        "still_forbidden": [
            "legacy stella alias replacement",
            "production SQLite write",
            "CloudBase/CloudRun/mini-program publish",
            "mem0 write",
            "OCR/Dajiala paid or D: recursive work",
        ],
    }


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    qdrant = report["qdrant"]
    neo4j = report["neo4j"]
    decision = report["decision"]
    lines = [
        "# Stage7 Consumer Migration Preflight",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- status: `{decision['status']}`",
        f"- qdrant_url: `{report['qdrant_url']}`",
        f"- neo4j_uri: `{report['neo4j_uri']}`",
        f"- neo4j_run_id: `{report['neo4j_run_id']}`",
        "",
        "## Qdrant Aliases",
        "",
        "| Kind | OK | Alias | Target | Points | Indexed |",
        "|---|---:|---|---|---:|---:|",
    ]
    for kind, item in qdrant["aliases"].items():
        lines.append(
            f"| `{kind}` | `{item['ok']}` | `{item['alias']}` | "
            f"`{item['alias_target']}` | {item['points_count']} | {item.get('indexed_vectors_count')} |"
        )
    lines.extend(
        [
            "",
            "## Neo4j Stage7Staging",
            "",
            f"- ok: `{neo4j['ok']}`",
            f"- node_total: `{neo4j['node_total']}`",
            f"- edge_total: `{neo4j['edge_total']}`",
            f"- labels: `{json.dumps(neo4j['labels'], ensure_ascii=False, sort_keys=True)}`",
            f"- edges: `{json.dumps(neo4j['edges'], ensure_ascii=False, sort_keys=True)}`",
            "",
            "## Consumer Entries",
            "",
        ]
    )
    for key, item in report["consumer_files"]["files"].items():
        lines.append(f"- `{key}`: `{item['path']}` exists=`{item['exists']}`")
    lines.extend(["", "## Decision", ""])
    if decision["blockers"]:
        lines.append("Blockers:")
        for blocker in decision["blockers"]:
            lines.append(f"- {blocker}")
    else:
        lines.append("- No preflight blocker found for a consumer staging migration plan.")
    lines.extend(["", "Allowed next:"])
    for item in decision["allowed_next"]:
        lines.append(f"- {item}")
    lines.extend(["", "Still forbidden:"])
    for item in decision["still_forbidden"]:
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- This preflight is read-only.",
            "- It does not publish, upload, write production SQLite, mutate Qdrant/Neo4j, call paid APIs, or scan D:.",
            "- Consumers must explicitly choose `wechat_stage7_*_qwen3_embedding_4b_1024_current`; legacy stella aliases stay separate.",
            "- Consumer graph reads must target `Stage7Staging` with `run_id=stage7_qwen3_20260514` until a separate production graph promotion plan exists.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    root = Path.cwd()
    require_local_url(args.qdrant_url, "Qdrant URL")
    require_local_url(args.neo4j_uri, "Neo4j URI")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "schema_version": "stage7_consumer_migration_preflight.v1",
        "generated_at": now_iso(),
        "root": str(root),
        "qdrant_url": args.qdrant_url,
        "neo4j_uri": args.neo4j_uri,
        "neo4j_database": args.neo4j_database,
        "neo4j_run_id": args.neo4j_run_id,
        "consumer_files": check_files(root),
        "stable": stable_summary(),
        "qdrant": check_qdrant(args.qdrant_url),
        "neo4j": check_neo4j(args.neo4j_uri, args.neo4j_database, args.neo4j_run_id),
        "writes": "report files only",
    }
    report["decision"] = build_decision(report)
    write_json(args.out_dir / "consumer_migration_preflight.json", report)
    write_markdown(args.out_dir / "consumer_migration_preflight.md", report)
    print(
        json.dumps(
            {
                "ok": report["decision"]["status"] == "ready_for_consumer_staging_plan",
                "status": report["decision"]["status"],
                "report": str(args.out_dir / "consumer_migration_preflight.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["decision"]["status"] == "ready_for_consumer_staging_plan" else 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--qdrant-url", default=DEFAULT_QDRANT_URL)
    parser.add_argument("--neo4j-uri", default=DEFAULT_NEO4J_URI)
    parser.add_argument("--neo4j-database", default="neo4j")
    parser.add_argument("--neo4j-run-id", default=DEFAULT_NEO4J_RUN_ID)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
