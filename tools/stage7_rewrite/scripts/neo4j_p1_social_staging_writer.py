"""Dry-run, verify, or write reviewed P1 social edges into Neo4j staging.

Default mode is dry-run and performs no mutation. Mutating modes require the
explicit confirmation token and local Neo4j URI. This writer is for staging-only
social/profile edges accepted by review_p1_social_graph_candidates.py.
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


DEFAULT_ACCEPTED_EDGES = Path("reports/p1_social_candidate_review_20260515/accepted_social_edges.jsonl")
DEFAULT_OUT_DIR = Path("reports/neo4j_p1_social_staging_20260515")
DEFAULT_NEO4J_URI = "http://127.0.0.1:7474"
DEFAULT_RUN_ID = "stage7_p1_social_20260515"
CONFIRM_TOKEN = "ENABLE_NEO4J_P1_SOCIAL_STAGING_WRITE"
SCHEMA_VERSION = "stage7_neo4j_p1_social_staging_writer.v1"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for P1 social Neo4j staging: {path}")


def require_local_neo4j(uri: str) -> None:
    parsed = parse.urlparse(uri)
    if parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError(f"Neo4j URI must be local for P1 social staging: {uri}")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_d_path(path, "accepted_edges")
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
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


def first_text(value: Any) -> str:
    return str(value or "").strip()


def social_subject_id(edge: dict[str, Any]) -> str:
    return f"p1_social_subject:{first_text(edge.get('source_family')).casefold()}:{first_text(edge.get('subject_name')).casefold()}"


def social_source_id(edge: dict[str, Any]) -> str:
    return f"p1_social_source:{first_text(edge.get('object_url')).casefold()}"


def valid_edge(edge: dict[str, Any]) -> bool:
    return (
        first_text(edge.get("review_status")) == "accepted_for_staging"
        and bool(edge.get("staging_only"))
        and first_text(edge.get("edge_type")) == "HAS_PROFILE"
        and bool(first_text(edge.get("subject_name")))
        and bool(first_text(edge.get("object_url")))
    )


def edge_payload(edge: dict[str, Any], run_id: str) -> dict[str, Any]:
    return {
        "edge_id": first_text(edge.get("edge_id")),
        "run_id": run_id,
        "subject_id": social_subject_id(edge),
        "subject_name": first_text(edge.get("subject_name")),
        "source_family": first_text(edge.get("source_family")),
        "object_id": social_source_id(edge),
        "object_url": first_text(edge.get("object_url")),
        "object_platform": first_text(edge.get("object_platform")),
        "evidence_url": first_text(edge.get("evidence_url")),
        "confidence": float(edge.get("confidence") or 0.0),
        "rollback_key": first_text(edge.get("rollback_key")),
        "source_edge_id": first_text(edge.get("source_edge_id")),
        "source_candidate_id": first_text(edge.get("source_candidate_id")),
    }


def write_statement(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "statement": (
            "UNWIND $rows AS row "
            "MERGE (s:Stage7Staging:SocialSubject {social_subject_id: row.subject_id}) "
            "SET s.name = row.subject_name, s.source_family = row.source_family, "
            "    s.p1_social_run_id = row.run_id, s.updated_at = datetime() "
            "MERGE (o:Stage7Staging:SocialSource {social_source_id: row.object_id}) "
            "SET o.url = row.object_url, o.platform = row.object_platform, "
            "    o.p1_social_run_id = row.run_id, o.updated_at = datetime() "
            "MERGE (s)-[r:HAS_PROFILE {edge_id: row.edge_id}]->(o) "
            "SET r.run_id = row.run_id, r.p1_social_run_id = row.run_id, "
            "    r.evidence_url = row.evidence_url, r.confidence = row.confidence, "
            "    r.rollback_key = row.rollback_key, r.source_edge_id = row.source_edge_id, "
            "    r.source_candidate_id = row.source_candidate_id, r.staging_only = true, "
            "    r.updated_at = datetime()"
        ),
        "parameters": {"rows": rows},
    }


def rollback_statements(run_id: str) -> list[dict[str, Any]]:
    return [
        {
            "statement": "MATCH ()-[r]->() WHERE r.p1_social_run_id = $run_id DELETE r",
            "parameters": {"run_id": run_id},
        },
        {
            "statement": "MATCH (n:Stage7Staging) WHERE n.p1_social_run_id = $run_id AND NOT (n)--() DELETE n",
            "parameters": {"run_id": run_id},
        },
    ]


def verification_statements(run_id: str, base_run_id: str) -> list[dict[str, Any]]:
    return [
        {
            "statement": (
                "MATCH (n:Stage7Staging:SocialSubject) "
                "WHERE n.p1_social_run_id = $run_id RETURN count(n) AS count"
            ),
            "parameters": {"run_id": run_id},
        },
        {
            "statement": (
                "MATCH (n:Stage7Staging:SocialSource) "
                "WHERE n.p1_social_run_id = $run_id RETURN count(n) AS count"
            ),
            "parameters": {"run_id": run_id},
        },
        {
            "statement": (
                "MATCH (:Stage7Staging:SocialSubject)-[r:HAS_PROFILE]->(:Stage7Staging:SocialSource) "
                "WHERE r.p1_social_run_id = $run_id RETURN count(r) AS count"
            ),
            "parameters": {"run_id": run_id},
        },
        {
            "statement": (
                "MATCH ()-[r:HAS_PROFILE]->() WHERE r.p1_social_run_id = $run_id "
                "AND r.staging_only = true RETURN count(r) AS count"
            ),
            "parameters": {"run_id": run_id},
        },
        {
            "statement": (
                "MATCH ()-[r:HAS_PROFILE]->() WHERE r.p1_social_run_id = $run_id "
                "AND coalesce(r.staging_only, false) <> true RETURN count(r) AS count"
            ),
            "parameters": {"run_id": run_id},
        },
        {
            "statement": (
                "MATCH (n:Stage7Staging:Article) WHERE n.run_id = $base_run_id "
                "RETURN count(n) AS count"
            ),
            "parameters": {"base_run_id": base_run_id},
        },
        {
            "statement": (
                "MATCH (s:Stage7Staging:SocialSubject)-[r:HAS_PROFILE]->(o:Stage7Staging:SocialSource) "
                "WHERE r.p1_social_run_id = $run_id "
                "RETURN s.name AS subject_name, o.url AS object_url, r.edge_id AS edge_id, "
                "r.staging_only AS staging_only ORDER BY subject_name, object_url"
            ),
            "parameters": {"run_id": run_id},
        },
    ]


def neo4j_commit(uri: str, database: str, statements: list[dict[str, Any]]) -> dict[str, Any]:
    payload = json.dumps({"statements": statements}, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        f"{uri.rstrip('/')}/db/{database}/tx/commit",
        data=payload,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Neo4j P1 Social Staging Writer",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- mode: `{report['mode']}`",
        f"- run_id: `{report['run_id']}`",
        f"- accepted_edges: `{report['accepted_edges']}`",
        f"- edges_seen: `{report['edges_seen']}`",
        f"- would_write_edges: `{report['would_write_edges']}`",
        f"- edges_written: `{report['edges_written']}`",
        f"- mutation_executed: `{report['mutation_executed']}`",
        "",
        "## Edge Counts",
        "",
    ]
    for key, value in sorted((report.get("edge_counts") or {}).items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(
        [
            "",
            "## Rollback",
            "",
            f"`{report['rollback_command']}`",
            "",
            "## Safety",
            "",
            "- Default mode is dry-run.",
            "- Canary/apply/rollback require explicit confirm token.",
            "- Staging-only labels/properties; no production labels or publish.",
            "- No D: scan, paid API, Qdrant alias change, production SQLite, or mem0 write.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def run(args: argparse.Namespace) -> dict[str, Any]:
    require_local_neo4j(args.neo4j_uri)
    reject_d_path(args.out_dir, "out_dir")
    if args.mode in {"canary", "apply", "rollback"} and args.confirm_token != CONFIRM_TOKEN:
        raise SystemExit(f"--confirm-token {CONFIRM_TOKEN} required for Neo4j P1 social staging mutations")
    args.out_dir.mkdir(parents=True, exist_ok=True)

    rows = [edge_payload(edge, args.run_id) for edge in read_jsonl(args.accepted_edges) if valid_edge(edge)]
    if args.limit:
        rows = rows[: args.limit]
    edge_counts = Counter("HAS_PROFILE" for _ in rows)
    mutation_executed = False
    edges_written = 0
    neo4j_result = None

    if args.mode == "rollback":
        neo4j_result = neo4j_commit(args.neo4j_uri, args.database, rollback_statements(args.run_id))
        mutation_executed = True
    elif args.mode in {"canary", "apply"} and rows:
        neo4j_result = neo4j_commit(args.neo4j_uri, args.database, [write_statement(rows)])
        mutation_executed = True
        edges_written = len(rows)

    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "mode": args.mode,
        "run_id": args.run_id,
        "accepted_edges": str(args.accepted_edges),
        "out_dir": str(args.out_dir),
        "neo4j_uri": args.neo4j_uri,
        "database": args.database,
        "edges_seen": len(rows),
        "would_write_edges": len(rows),
        "edges_written": edges_written,
        "edge_counts": dict(edge_counts),
        "mutation_executed": mutation_executed,
        "neo4j_result_errors": (neo4j_result or {}).get("errors") if neo4j_result else None,
        "rollback_command": (
            f"python scripts\\neo4j_p1_social_staging_writer.py --mode rollback "
            f"--run-id {args.run_id} --confirm-token {CONFIRM_TOKEN}"
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
    write_json(args.out_dir / "neo4j_p1_social_staging_report.json", report)
    write_markdown(args.out_dir / "neo4j_p1_social_staging_report.md", report)
    print(json.dumps({"ok": True, "mode": args.mode, "edges_seen": len(rows), "report": str(args.out_dir / "neo4j_p1_social_staging_report.json")}, ensure_ascii=False, indent=2))
    return report


def query_count(result: dict[str, Any], index: int) -> int:
    return int(result["results"][index]["data"][0]["row"][0])


def run_verify(args: argparse.Namespace) -> dict[str, Any]:
    require_local_neo4j(args.neo4j_uri)
    reject_d_path(args.out_dir, "out_dir")
    args.out_dir.mkdir(parents=True, exist_ok=True)

    expected_rows = [edge_payload(edge, args.run_id) for edge in read_jsonl(args.accepted_edges) if valid_edge(edge)]
    if args.limit:
        expected_rows = expected_rows[: args.limit]
    neo4j_result = neo4j_commit(
        args.neo4j_uri,
        args.database,
        verification_statements(args.run_id, args.base_run_id),
    )
    errors = neo4j_result.get("errors") or []
    counts = {
        "social_subject_nodes": 0 if errors else query_count(neo4j_result, 0),
        "social_source_nodes": 0 if errors else query_count(neo4j_result, 1),
        "has_profile_edges": 0 if errors else query_count(neo4j_result, 2),
        "staging_only_edges": 0 if errors else query_count(neo4j_result, 3),
        "non_staging_only_edges": 0 if errors else query_count(neo4j_result, 4),
        "base_run_articles": 0 if errors else query_count(neo4j_result, 5),
    }
    rows = [] if errors else [item["row"] for item in neo4j_result["results"][6]["data"]]
    expected_edge_count = len(expected_rows)
    ok = (
        not errors
        and counts["has_profile_edges"] == expected_edge_count
        and counts["staging_only_edges"] == expected_edge_count
        and counts["non_staging_only_edges"] == 0
        and counts["social_subject_nodes"] == expected_edge_count
        and counts["social_source_nodes"] == expected_edge_count
    )
    report = {
        "schema_version": f"{SCHEMA_VERSION}.verify",
        "generated_at": now_iso(),
        "mode": "verify",
        "ok": ok,
        "run_id": args.run_id,
        "base_run_id": args.base_run_id,
        "accepted_edges": str(args.accepted_edges),
        "expected_edge_count": expected_edge_count,
        "counts": counts,
        "edges": rows,
        "neo4j_result_errors": errors,
        "mutation_executed": False,
        "rollback_command": (
            f"python scripts\\neo4j_p1_social_staging_writer.py --mode rollback "
            f"--run-id {args.run_id} --confirm-token {CONFIRM_TOKEN}"
        ),
        "safety": [
            "verify_is_read_only",
            "staging_only",
            "no_production_labels",
            "no_publish",
            "no_d_scan",
            "no_paid_api",
        ],
    }
    write_json(args.out_dir / "canary_verification.json", report)
    lines = [
        "# Neo4j P1 Social Staging Verification",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- ok: `{report['ok']}`",
        f"- run_id: `{args.run_id}`",
        f"- expected_edge_count: `{expected_edge_count}`",
        f"- has_profile_edges: `{counts['has_profile_edges']}`",
        f"- staging_only_edges: `{counts['staging_only_edges']}`",
        f"- non_staging_only_edges: `{counts['non_staging_only_edges']}`",
        f"- social_subject_nodes: `{counts['social_subject_nodes']}`",
        f"- social_source_nodes: `{counts['social_source_nodes']}`",
        f"- base_run_articles: `{counts['base_run_articles']}`",
        f"- mutation_executed: `False`",
        "",
        "## Edges",
        "",
    ]
    for subject_name, object_url, edge_id, staging_only in rows:
        lines.append(f"- `{subject_name}` -> `{object_url}` (`{edge_id}`, staging_only=`{staging_only}`)")
    lines.extend(["", "## Rollback", "", f"`{report['rollback_command']}`", ""])
    (args.out_dir / "canary_verification.md").write_text("\n".join(lines), encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": ok,
                "mode": "verify",
                "expected_edge_count": expected_edge_count,
                "has_profile_edges": counts["has_profile_edges"],
                "report": str(args.out_dir / "canary_verification.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["dry-run", "verify", "canary", "apply", "rollback"], default="dry-run")
    parser.add_argument("--accepted-edges", type=Path, default=DEFAULT_ACCEPTED_EDGES)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--neo4j-uri", default=DEFAULT_NEO4J_URI)
    parser.add_argument("--database", default="neo4j")
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--base-run-id", default="stage7_qwen3_20260514")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--confirm-token", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.mode == "verify":
        run_verify(args)
    else:
        run(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
