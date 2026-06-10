#!/usr/bin/env python3
"""Report-only Stage7 local E2E integration checks.

Modes:
* qdrant-neo4j-joint: use existing local Qwen3 vectors to query Qdrant aliases,
  then read Neo4j Stage7Staging for the same term.
* release-pack-consumer: validate the staging pointer and simulate downstream
  article/entity/event card consumption without requiring publish_time.
* cloudrun-smoke: optional local HTTP smoke against a local CloudRun dev server.
* full: run all of the above. CloudRun is optional unless --require-cloudrun is set.

No writes to production stores, no DB mutations, no paid API, no D: scan.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode, urlparse

import requests


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import consumer_release_pointer_smoke  # noqa: E402


DEFAULT_VECTOR_DIR = Path("reports/vector_full_qwen3_4b_1024_20260514")
DEFAULT_POINTER = Path("reports/consumer_release_pack_full_unknown_time_20260514/release_pointer.staging.json")
DEFAULT_OUT_DIR = Path("reports/e2e_integration_20260515")
DEFAULT_QDRANT_URL = "http://127.0.0.1:6333"
DEFAULT_NEO4J_URI = "http://127.0.0.1:7474"
DEFAULT_CLOUDRUN_URL = "http://127.0.0.1:8787"
DEFAULT_NEO4J_RUN_ID = "stage7_qwen3_20260514"
KINDS = ("article", "entity", "event")
ALIASES = {
    "article": "wechat_stage7_article_qwen3_embedding_4b_1024_current",
    "entity": "wechat_stage7_entity_qwen3_embedding_4b_1024_current",
    "event": "wechat_stage7_event_qwen3_embedding_4b_1024_current",
}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def require_local_url(url: str, label: str) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError(f"{label} must be local for Stage7 E2E smoke: {url}")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for Stage7 E2E smoke: {path}")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_pointer_file(raw_path: str, pointer_path: Path) -> Path:
    return consumer_release_pointer_smoke.resolve_from_pointer(raw_path, pointer_path)


def sample_jsonl(path: Path, limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            row = json.loads(stripped)
            if isinstance(row, dict):
                rows.append(row)
            if len(rows) >= limit:
                break
    return rows


def row_matches_query(row: dict[str, Any], query: str) -> bool:
    needle = query.lower()
    haystack = " ".join(str(row.get(field) or "") for field in ("text", "source_account", "title", "name", "place"))
    return needle in haystack.lower()


def find_query_rows(card_texts_path: Path, query: str, per_kind: int = 1) -> dict[str, list[dict[str, Any]]]:
    selected: dict[str, list[dict[str, Any]]] = {kind: [] for kind in KINDS}
    with card_texts_path.open("r", encoding="utf-8") as handle:
        for index, line in enumerate(handle):
            if all(len(rows) >= per_kind for rows in selected.values()):
                break
            stripped = line.strip()
            if not stripped:
                continue
            row = json.loads(stripped)
            if not isinstance(row, dict):
                continue
            kind = str(row.get("type") or "")
            if kind not in selected or len(selected[kind]) >= per_kind:
                continue
            if row_matches_query(row, query):
                row["_vector_index"] = index
                selected[kind].append(row)
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
        raise RuntimeError(f"Qdrant search failed for {alias} {response.status_code}: {response.text[:500]}")
    result = response.json().get("result")
    if isinstance(result, dict):
        result = result.get("points")
    return result or []


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


def run_qdrant_neo4j(args: argparse.Namespace) -> dict[str, Any]:
    require_local_url(args.qdrant_url, "Qdrant URL")
    require_local_url(args.neo4j_uri, "Neo4j URI")
    reject_d_path(args.vector_dir, "vector_dir")

    import numpy as np

    selected = find_query_rows(args.vector_dir / "card_texts.jsonl", args.query, per_kind=1)
    vectors = np.load(args.vector_dir / "vectors.npy", mmap_mode="r")
    qdrant_details: list[dict[str, Any]] = []
    qdrant_hit_total = 0
    for kind, rows in selected.items():
        for row in rows:
            vector = np.asarray(vectors[int(row["_vector_index"])], dtype="float32").tolist()
            hits = qdrant_search(args.qdrant_url, ALIASES[kind], vector, args.qdrant_limit)
            qdrant_hit_total += len(hits)
            first_payload = (hits[0].get("payload") if hits else {}) or {}
            qdrant_details.append(
                {
                    "kind": kind,
                    "alias": ALIASES[kind],
                    "query_card_id": row.get("id"),
                    "query_text": row.get("text"),
                    "hit_count": len(hits),
                    "first_hit_card_id": first_payload.get("card_id"),
                    "first_hit_type": first_payload.get("card_type"),
                    "first_hit_article_uid": first_payload.get("article_uid") or first_payload.get("source_article_uid"),
                }
            )

    term = args.query.lower()
    statement = (
        "MATCH (n:Stage7Staging {run_id: $run_id}) "
        "WHERE toLower(coalesce(n.name, '')) CONTAINS $term "
        "OR toLower(coalesce(n.title, '')) CONTAINS $term "
        "OR toLower(coalesce(n.node_id, '')) CONTAINS $term "
        "OPTIONAL MATCH (n)-[r:STAGE7_EDGE]-(m:Stage7Staging {run_id: $run_id}) "
        "RETURN labels(n) AS labels, n.node_id AS node_id, n.name AS name, n.title AS title, "
        "r.predicate AS predicate, labels(m) AS neighbor_labels, m.name AS neighbor_name, m.title AS neighbor_title "
        "LIMIT $limit"
    )
    data = neo4j_commit(
        args.neo4j_uri,
        args.neo4j_database,
        [{"statement": statement, "parameters": {"run_id": args.neo4j_run_id, "term": term, "limit": args.neo4j_limit}}],
    )
    neo4j_rows = []
    for item in ((data.get("results") or [{}])[0].get("data") or []):
        row = item.get("row") or []
        neo4j_rows.append(
            {
                "labels": row[0] if len(row) > 0 else [],
                "node_id": row[1] if len(row) > 1 else "",
                "name": row[2] if len(row) > 2 else "",
                "title": row[3] if len(row) > 3 else "",
                "predicate": row[4] if len(row) > 4 else "",
                "neighbor_labels": row[5] if len(row) > 5 else [],
                "neighbor_name": row[6] if len(row) > 6 else "",
                "neighbor_title": row[7] if len(row) > 7 else "",
            }
        )

    article_search = next((item for item in qdrant_details if item["kind"] == "article"), {})
    qdrant_ok = bool(article_search) and int(article_search.get("hit_count") or 0) >= args.min_qdrant_hits
    neo4j_ok = len(neo4j_rows) > 0
    return {
        "ok": qdrant_ok and neo4j_ok,
        "decision": "qdrant_neo4j_joint_ready" if qdrant_ok and neo4j_ok else "qdrant_neo4j_joint_blocked",
        "query": args.query,
        "qdrant": {
            "ok": qdrant_ok,
            "hit_total": qdrant_hit_total,
            "min_article_hits": args.min_qdrant_hits,
            "selected_counts": {kind: len(rows) for kind, rows in selected.items()},
            "details": qdrant_details,
        },
        "neo4j": {
            "ok": neo4j_ok,
            "run_id": args.neo4j_run_id,
            "row_count": len(neo4j_rows),
            "rows": neo4j_rows[: args.neo4j_limit],
        },
    }


def simulate_release_pack_consumer(pointer_path: Path, sample_count: int, full_count: bool) -> dict[str, Any]:
    reject_d_path(pointer_path, "pointer")
    pointer_report = consumer_release_pointer_smoke.validate_pointer(pointer_path, sample_count, full_count)
    pointer = read_json(pointer_path)
    files = pointer.get("files") or {}
    articles_path = resolve_pointer_file(str((files.get("articles") or {}).get("path") or ""), pointer_path)
    entities_path = resolve_pointer_file(str((files.get("entities") or {}).get("path") or ""), pointer_path)
    events_path = resolve_pointer_file(str((files.get("events") or {}).get("path") or ""), pointer_path)
    for label, path in {"articles": articles_path, "entities": entities_path, "events": events_path}.items():
        reject_d_path(path, label)

    articles = sample_jsonl(articles_path, sample_count)
    entities = sample_jsonl(entities_path, sample_count)
    events = sample_jsonl(events_path, sample_count)

    article_cards = [
        {
            "id": row.get("article_id") or row.get("article_uid"),
            "title": row.get("title") or "",
            "source_account": row.get("source_account") or "",
            "publish_time": row.get("publish_time") or "",
            "publish_time_status": row.get("publish_time_status") or "",
        }
        for row in articles
    ]
    entity_cards = [
        {
            "id": row.get("eid") or row.get("name"),
            "name": row.get("name") or "",
            "type": row.get("type") or "",
            "source_article_uid": row.get("source_article_uid") or "",
        }
        for row in entities
    ]
    event_cards = [
        {
            "id": row.get("evid") or row.get("name"),
            "title": row.get("name") or "",
            "date": row.get("time_iso") or "",
            "date_text": row.get("time_text") or "",
            "venue": row.get("place") or "",
            "participants": row.get("participants") if isinstance(row.get("participants"), list) else [],
            "source_article_uid": row.get("source_article_uid") or "",
        }
        for row in events
    ]

    unknown_time_safe = all(card["publish_time_status"] in {"known", "unknown"} for card in article_cards)
    no_required_post_date = all("post_date" not in card for card in [*article_cards, *event_cards, *entity_cards])
    event_list_ok = bool(event_cards) and all(card["title"] for card in event_cards)
    ok = bool(pointer_report.get("ok")) and bool(article_cards) and bool(entity_cards) and event_list_ok and unknown_time_safe and no_required_post_date
    return {
        "ok": ok,
        "decision": "release_pack_consumer_sim_ready" if ok else "release_pack_consumer_sim_blocked",
        "pointer_ok": bool(pointer_report.get("ok")),
        "pointer_decision": pointer_report.get("decision"),
        "sample_count": sample_count,
        "full_count": full_count,
        "article_cards": len(article_cards),
        "entity_cards": len(entity_cards),
        "event_cards": len(event_cards),
        "unknown_time_safe": unknown_time_safe,
        "no_required_post_date": no_required_post_date,
        "event_list_ok": event_list_ok,
        "warnings": pointer_report.get("warnings") or [],
        "errors": pointer_report.get("errors") or [],
        "preview": {
            "articles": article_cards[:3],
            "entities": entity_cards[:3],
            "events": event_cards[:3],
        },
    }


def run_release_pack_consumer(args: argparse.Namespace) -> dict[str, Any]:
    return simulate_release_pack_consumer(args.pointer, args.sample_count, not args.skip_full_count)


def run_cloudrun_smoke(args: argparse.Namespace) -> dict[str, Any]:
    require_local_url(args.cloudrun_url, "CloudRun URL")
    endpoints = [
        ("/healthz", {}),
        ("/api/v1/weekly/manifest", {}),
        ("/api/v1/weekly/current", {"limit": "10"}),
        ("/api/v1/weekly/cities", {}),
        ("/api/v1/weekly/dates", {}),
    ]
    results = []
    for path, params in endpoints:
        url = args.cloudrun_url.rstrip("/") + path
        if params:
            url += "?" + urlencode(params)
        try:
            response = requests.get(url, timeout=12)
        except requests.RequestException as exc:
            return {
                "ok": False,
                "decision": "cloudrun_smoke_skipped_local_service_unavailable",
                "required": bool(args.require_cloudrun),
                "error": str(exc),
                "results": results,
            }
        content_type = response.headers.get("content-type", "")
        results.append(
            {
                "url": url,
                "status_code": response.status_code,
                "json_like": "json" in content_type.lower() or response.text.strip().startswith(("{", "[")),
                "body_preview": response.text[:200],
            }
        )
    ok = all(200 <= item["status_code"] < 500 and item["json_like"] for item in results)
    return {
        "ok": ok,
        "decision": "cloudrun_local_smoke_ready" if ok else "cloudrun_local_smoke_blocked",
        "required": bool(args.require_cloudrun),
        "results": results,
    }


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    if args.mode in {"qdrant-neo4j-joint", "full"}:
        checks["qdrant_neo4j_joint"] = run_qdrant_neo4j(args)
    if args.mode in {"release-pack-consumer", "full"}:
        checks["release_pack_consumer"] = run_release_pack_consumer(args)
    if args.mode in {"cloudrun-smoke", "full"}:
        checks["cloudrun_smoke"] = run_cloudrun_smoke(args)

    required_checks = ["qdrant_neo4j_joint", "release_pack_consumer"] if args.mode == "full" else list(checks)
    if args.mode == "full" and args.require_cloudrun:
        required_checks.append("cloudrun_smoke")
    ok = all(bool(checks[name].get("ok")) for name in required_checks if name in checks)
    blockers = [f"{name}: {checks[name].get('decision')}" for name in required_checks if name in checks and not checks[name].get("ok")]
    if args.mode == "full" and "cloudrun_smoke" in checks and not args.require_cloudrun and not checks["cloudrun_smoke"].get("ok"):
        decision = "e2e_local_core_ready_cloudrun_skipped" if ok else "e2e_local_core_blocked"
    else:
        decision = "e2e_integration_ready" if ok else "e2e_integration_blocked"
    return {
        "schema_version": "stage7_e2e_integration_report.v1",
        "generated_at": now_iso(),
        "mode": args.mode,
        "ok": ok,
        "decision": decision,
        "required_checks": required_checks,
        "blockers": blockers,
        "checks": checks,
        "writes": "reports_only",
        "safety": [
            "no production publish",
            "no production SQLite write",
            "no Qdrant or Neo4j write",
            "no paid API call",
            "no D: scan",
        ],
    }


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Stage7 E2E Integration Report",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- mode: `{report['mode']}`",
        f"- ok: `{report['ok']}`",
        f"- decision: `{report['decision']}`",
        f"- required_checks: `{json.dumps(report['required_checks'], ensure_ascii=False)}`",
        "",
        "## Checks",
        "",
    ]
    for name, item in report["checks"].items():
        lines.extend([f"### {name}", "", f"- ok: `{item.get('ok')}`", f"- decision: `{item.get('decision')}`"])
        if name == "qdrant_neo4j_joint":
            lines.append(f"- qdrant_hit_total: `{item['qdrant']['hit_total']}`")
            lines.append(f"- neo4j_row_count: `{item['neo4j']['row_count']}`")
        if name == "release_pack_consumer":
            lines.append(f"- article_cards: `{item.get('article_cards')}`")
            lines.append(f"- entity_cards: `{item.get('entity_cards')}`")
            lines.append(f"- event_cards: `{item.get('event_cards')}`")
            lines.append(f"- unknown_time_safe: `{item.get('unknown_time_safe')}`")
        if name == "cloudrun_smoke":
            lines.append(f"- required: `{item.get('required')}`")
            if item.get("error"):
                lines.append(f"- error: `{item.get('error')}`")
        lines.append("")

    lines.extend(["## Blockers", ""])
    if report["blockers"]:
        for blocker in report["blockers"]:
            lines.append(f"- `{blocker}`")
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Reports only.",
            "- No production publish.",
            "- No production SQLite write.",
            "- No Qdrant or Neo4j write.",
            "- No paid API call.",
            "- No D: scan.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    report = build_report(args)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.out_dir / "e2e_integration_report.json", report)
    write_markdown(args.out_dir / "e2e_integration_report.md", report)
    print(
        json.dumps(
            {
                "ok": report["ok"],
                "decision": report["decision"],
                "blockers": len(report["blockers"]),
                "report": str(args.out_dir / "e2e_integration_report.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["ok"] or args.report_only_exit_zero else 2


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("qdrant-neo4j-joint", "release-pack-consumer", "cloudrun-smoke", "full"), default="full")
    parser.add_argument("--vector-dir", type=Path, default=DEFAULT_VECTOR_DIR)
    parser.add_argument("--pointer", type=Path, default=DEFAULT_POINTER)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--query", default="Dada")
    parser.add_argument("--qdrant-url", default=DEFAULT_QDRANT_URL)
    parser.add_argument("--qdrant-limit", type=int, default=10)
    parser.add_argument("--min-qdrant-hits", type=int, default=5)
    parser.add_argument("--neo4j-uri", default=DEFAULT_NEO4J_URI)
    parser.add_argument("--neo4j-database", default="neo4j")
    parser.add_argument("--neo4j-run-id", default=DEFAULT_NEO4J_RUN_ID)
    parser.add_argument("--neo4j-limit", type=int, default=10)
    parser.add_argument("--cloudrun-url", default=DEFAULT_CLOUDRUN_URL)
    parser.add_argument("--require-cloudrun", action="store_true")
    parser.add_argument("--sample-count", type=int, default=20)
    parser.add_argument("--skip-full-count", action="store_true", default=True)
    parser.add_argument("--full-count", dest="skip_full_count", action="store_false")
    parser.add_argument("--report-only-exit-zero", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
