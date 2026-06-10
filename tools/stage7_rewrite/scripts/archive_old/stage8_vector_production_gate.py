"""Production-shaped Stage8 vector gate.

The gate is intentionally conservative:

- dry-run plans Tier A/B/C/D routing and vector jobs without embedding or DB writes.
- canary mode may run Mac embeddings plus isolated SQLite/Qdrant/Neo4j test writes.
- production mode is blocked until a separate production writer is implemented.

All embedding endpoints must be Mac endpoints. PC-local vector inference is not
allowed in this lane.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCRIPT_DIR))

import run_stage8_write_strategy_tests as write_tests
import stage8_vector_semantic_eval as semantic_eval
from stage7.atomic_io import safe_read_json
from stage7.vector_plan.build_embedding_jobs import build_jobs_from_article
from stage7.vector_plan.embed_runner import run_vector_jobs_async


BAD_PLATFORM_TITLES = {"微信公众平台"}
BAD_PLATFORM_MARKERS = (
    "根据作者隐私设置",
    "看作者其他内容",
    "轻点两下取消赞",
    "轻点两下取消在看",
    "Body root not found",
)
PRODUCTION_CONFIRM_TOKEN = "ENABLE_PRODUCTION_VECTOR_WRITE_93K"


@dataclass
class TierDecision:
    extract_path: str
    article_id: str
    account: str
    title: str
    tier: str
    action: str
    card_template: str
    candidate_cap: int
    score_profile: str
    reasons: list[str]


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def iter_extract_files(output_root: Path, sample_articles: int) -> list[Path]:
    files = sorted((output_root / "llm_extract").rglob("extract.article.v1.json"))
    if sample_articles > 0:
        files = files[:sample_articles]
    return files


def compact_text(value: Any, limit: int = 2000) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def article_body_text(article: dict[str, Any]) -> str:
    values = [
        article.get("summary"),
        article.get("main_content"),
        article.get("body_text"),
        article.get("title"),
    ]
    return compact_text(" ".join(str(value or "") for value in values))


def is_platform_privacy_article(article: dict[str, Any]) -> bool:
    title = compact_text(article.get("title"))
    body = article_body_text(article)
    if title not in BAD_PLATFORM_TITLES:
        return False
    if len(body) < 240:
        return True
    return any(marker in body for marker in BAD_PLATFORM_MARKERS)


def has_structured_cards(article: dict[str, Any]) -> bool:
    return any(article.get(key) for key in ("entities", "events", "relations", "claims"))


def has_ocr_cards(article: dict[str, Any]) -> bool:
    return bool(list(semantic_eval.iter_ocr_evidence(article)))


def classify_article(
    article: dict[str, Any],
    path: Path,
    *,
    card_template: str,
    candidate_cap: int,
    score_profile: str,
) -> TierDecision:
    article_id = str(article.get("article_uid") or article.get("article_id") or path.parent.name)
    account = str(article.get("source_account") or article.get("account") or path.parent.parent.name)
    title = str(article.get("title") or "")
    reasons: list[str] = []
    if is_platform_privacy_article(article):
        reasons.append("platform_privacy_or_partial_capture")
        return TierDecision(
            extract_path=str(path),
            article_id=article_id,
            account=account,
            title=title,
            tier="D",
            action="quarantine_no_broad_vector_write",
            card_template="none",
            candidate_cap=0,
            score_profile="none",
            reasons=reasons,
        )
    if has_ocr_cards(article):
        tier = "C"
        reasons.append("ocr_evidence_present")
    elif has_structured_cards(article):
        tier = "A"
        reasons.append("structured_stage7_extract")
    elif article_body_text(article):
        tier = "B"
        reasons.append("text_present_without_rich_structure")
    else:
        tier = "D"
        reasons.append("empty_article_text")
    action = "quarantine_no_broad_vector_write" if tier == "D" else "eligible_vector_canary_or_write"
    return TierDecision(
        extract_path=str(path),
        article_id=article_id,
        account=account,
        title=title,
        tier=tier,
        action=action,
        card_template=card_template if tier != "D" else "none",
        candidate_cap=candidate_cap if tier != "D" else 0,
        score_profile=score_profile if tier != "D" else "none",
        reasons=reasons,
    )


def enforce_mac_endpoint(endpoint: str, route_metadata: dict[str, Any], allow_local_endpoint: bool) -> None:
    endpoint_id = str(route_metadata.get("endpoint_id") or "")
    endpoint_lower = endpoint.lower()
    if not endpoint_id.startswith("local_mac_vector_endpoint_"):
        raise ValueError(f"embedding endpoint is not a Mac endpoint id: {endpoint_id}")
    if ("127.0.0.1" in endpoint_lower or "localhost" in endpoint_lower) and not allow_local_endpoint:
        raise ValueError(f"PC execution refuses local vector endpoint: {endpoint}")
    if "192.168.8.234" not in endpoint_lower and not allow_local_endpoint:
        raise ValueError(f"PC execution expected Mac LAN endpoint, got: {endpoint}")


def materialize_selected_root(output_root: Path, selected: list[tuple[Path, dict[str, Any], TierDecision]], out_dir: Path) -> Path:
    selected_root = out_dir / "selected_extracts_root"
    for src_path, article, decision in selected:
        account = write_tests.safe_collection_model(decision.account or "unknown_account")
        article_id = write_tests.safe_collection_model(decision.article_id or src_path.parent.name)
        dst = selected_root / "llm_extract" / f"tier_{decision.tier}__{account}" / article_id / "extract.article.v1.json"
        dst.parent.mkdir(parents=True, exist_ok=True)
        if "schema_version" not in article:
            article = dict(article, schema_version="article_extract.v1")
        dst.write_text(json.dumps(article, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return selected_root


def build_plan(args: argparse.Namespace) -> dict[str, Any]:
    output_root = Path(args.output_root).resolve()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    config_path = Path(args.vector_config).resolve() if args.vector_config else ROOT / "config" / "vector_endpoints.yaml"
    model, endpoint, dim, route_metadata = write_tests.load_vector_route(config_path)
    enforce_mac_endpoint(endpoint, route_metadata, args.allow_local_endpoint)

    extract_files = iter_extract_files(output_root, args.sample_articles)
    selected: list[tuple[Path, dict[str, Any], TierDecision]] = []
    quarantined: list[TierDecision] = []
    decisions: list[TierDecision] = []
    jobs: list[dict[str, Any]] = []
    by_tier: Counter[str] = Counter()
    by_job_kind: Counter[str] = Counter()
    parsed = 0

    for extract_file in extract_files:
        article = safe_read_json(extract_file, {})
        if not article:
            continue
        parsed += 1
        decision = classify_article(
            article,
            extract_file,
            card_template=args.card_template,
            candidate_cap=args.candidate_cap,
            score_profile=args.score_profile,
        )
        decisions.append(decision)
        by_tier[decision.tier] += 1
        if decision.tier == "D":
            quarantined.append(decision)
            continue
        rel_path = str(extract_file.relative_to(output_root))
        article_jobs = build_jobs_from_article(
            article,
            rel_path,
            model,
            endpoint,
            dim,
            route_metadata,
            card_template=args.card_template,
        )
        selected.append((extract_file, article, decision))
        for job in article_jobs:
            jobs.append(job.to_dict())
            by_job_kind[job.object_kind] += 1
            if args.max_jobs > 0 and len(jobs) >= args.max_jobs:
                break
        if args.max_jobs > 0 and len(jobs) >= args.max_jobs:
            break

    selected_root = materialize_selected_root(output_root, selected, out_dir)
    jobs_path = out_dir / "vector_jobs.gate_plan.jsonl"
    write_jsonl(jobs_path, jobs)
    write_jsonl(out_dir / "selected_extracts.jsonl", [asdict(item[2]) for item in selected])
    write_jsonl(out_dir / "quarantine_tier_d.jsonl", [asdict(item) for item in quarantined])

    production_allowed = False
    production_blockers = []
    if args.mode != "production":
        production_blockers.append(f"mode is {args.mode}; production writes are not attempted")
    if args.mode == "production":
        production_blockers.append("production writer is not implemented in this gate script")
        if args.confirm_production_write != PRODUCTION_CONFIRM_TOKEN:
            production_blockers.append("missing production confirmation token")
    if quarantined:
        production_blockers.append("Tier D rows were quarantined; review quarantine before production")
    if not selected:
        production_blockers.append("no eligible vector rows selected")

    plan = {
        "schema_version": "stage8_vector_production_gate.v1",
        "mode": args.mode,
        "output_root": str(output_root),
        "out_dir": str(out_dir),
        "selected_root": str(selected_root),
        "files_seen": len(extract_files),
        "files_parsed": parsed,
        "eligible_articles": len(selected),
        "quarantined_articles": len(quarantined),
        "tier_counts": dict(by_tier),
        "job_count": len(jobs),
        "job_kind_counts": dict(by_job_kind),
        "jobs_path": str(jobs_path),
        "endpoint": endpoint,
        "model": model,
        "dim": dim,
        "route_metadata": route_metadata,
        "card_template": args.card_template,
        "candidate_cap": args.candidate_cap,
        "score_profile": args.score_profile,
        "qdrant_policy": {
            "collection_prefix": args.qdrant_collection_prefix,
            "split_by_kind": True,
            "collection_name_must_include_model_and_dim": True,
            "production_collections_written": False,
        },
        "pc_ledger_policy": {
            "ledger_first": True,
            "resume_key": "object_kind + object_id + text_sha1",
            "production_ledger_written": False,
        },
        "neo4j_policy": {
            "test_label": "WechatTestNode",
            "production_label": "WechatNode",
            "production_graph_written": False,
        },
        "production_allowed": production_allowed,
        "production_blockers": production_blockers,
        "canary_summary": None,
    }
    return plan


def run_canary(plan: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    out_dir = Path(plan["out_dir"])
    selected_root = Path(plan["selected_root"])
    jobs_path, extract_files, _jobs, job_stats = write_tests.build_jobs(
        selected_root,
        Path(args.vector_config).resolve() if args.vector_config else ROOT / "config" / "vector_endpoints.yaml",
        out_dir,
        None,
        args.max_jobs if args.max_jobs > 0 else None,
        args.card_template,
    )
    embeddings_path = out_dir / "vector_embeddings.gate_canary.jsonl"
    failures_path = out_dir / "vector_failures.gate_canary.jsonl"
    embedding_stats = asyncio.run(run_vector_jobs_async(
        jobs_path,
        embeddings_path,
        failures_path,
        concurrency=max(1, args.embedding_concurrency),
        limit=args.max_jobs if args.max_jobs > 0 else None,
        resume=True,
        timeout_sec=args.embedding_timeout_sec,
        batch_size=max(1, args.embedding_batch_size),
    )).to_dict()
    embeddings = write_tests.read_jsonl(embeddings_path)
    graph_rows = write_tests.build_graph_preview(extract_files, out_dir)
    suffix = write_tests.run_id()
    strategy_results = [
        write_tests.run_pc_db_test(out_dir / "pc_stage8_gate_canary.sqlite", embeddings, graph_rows)
    ]
    strategy_results.extend(write_tests.run_qdrant_tests_guarded(
        embeddings,
        args.qdrant_url,
        out_dir,
        suffix,
        max(1, args.query_count),
        args.keep_qdrant_test_collections,
    ))
    strategy_results.append(write_tests.run_neo4j_probe(
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
        "schema_version": "stage8_vector_gate_canary.v1",
        "job_stats": job_stats,
        "embedding_stats": embedding_stats,
        "graph_counts": {"nodes": len(graph_rows.get("nodes", [])), "edges": len(graph_rows.get("edges", []))},
        "strategy_results": [
            {"name": item.name, "status": item.status, "details": item.details}
            for item in strategy_results
        ],
    }
    write_json(out_dir / "gate_canary_summary.json", summary)
    return summary


def write_markdown(plan: dict[str, Any], out_dir: Path) -> None:
    lines = [
        "# Stage8 Vector Production Gate",
        "",
        f"- mode: `{plan['mode']}`",
        f"- output_root: `{plan['output_root']}`",
        f"- eligible_articles: `{plan['eligible_articles']}`",
        f"- quarantined_articles: `{plan['quarantined_articles']}`",
        f"- job_count: `{plan['job_count']}`",
        f"- endpoint: `{plan['endpoint']}`",
        f"- model/dim: `{plan['model']}` / `{plan['dim']}`",
        f"- production_allowed: `{plan['production_allowed']}`",
        "",
        "## Tier Counts",
        "",
    ]
    for tier, count in sorted(plan["tier_counts"].items()):
        lines.append(f"- Tier {tier}: `{count}`")
    lines.extend([
        "",
        "## Job Kinds",
        "",
    ])
    for kind, count in sorted(plan["job_kind_counts"].items()):
        lines.append(f"- `{kind}`: `{count}`")
    lines.extend([
        "",
        "## Production Blockers",
        "",
    ])
    for blocker in plan["production_blockers"] or ["none"]:
        lines.append(f"- {blocker}")
    if plan.get("canary_summary"):
        lines.extend([
            "",
            "## Canary",
            "",
            f"- embeddings: `{plan['canary_summary']['embedding_stats'].get('succeeded')}` succeeded / `{plan['canary_summary']['embedding_stats'].get('failed')}` failed",
            f"- embedding_batch_size: `{plan['canary_summary']['embedding_stats'].get('batch_size')}`",
        ])
        for row in plan["canary_summary"]["strategy_results"]:
            lines.append(f"- `{row['name']}`: `{row['status']}`")
    (out_dir / "PRODUCTION_GATE_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["dry-run", "canary", "production"], default="dry-run")
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--vector-config", default="")
    parser.add_argument("--sample-articles", type=int, default=100)
    parser.add_argument("--max-jobs", type=int, default=0)
    parser.add_argument("--card-template", choices=["multi_card", "research_v1"], default="research_v1")
    parser.add_argument("--candidate-cap", type=int, default=20)
    parser.add_argument("--score-profile", default="adaptive_v3_source_guard")
    parser.add_argument("--qdrant-collection-prefix", default="wechat_prod")
    parser.add_argument("--allow-local-endpoint", action="store_true")
    parser.add_argument("--confirm-production-write", default="")
    parser.add_argument("--embedding-concurrency", type=int, default=4)
    parser.add_argument("--embedding-batch-size", type=int, default=1)
    parser.add_argument("--embedding-timeout-sec", type=int, default=180)
    parser.add_argument("--qdrant-url", default=write_tests.DEFAULT_QDRANT_URL)
    parser.add_argument("--query-count", type=int, default=40)
    parser.add_argument("--keep-qdrant-test-collections", action="store_true")
    parser.add_argument("--neo4j-host", default=write_tests.DEFAULT_NEO4J_HOST)
    parser.add_argument("--neo4j-bolt-port", type=int, default=write_tests.DEFAULT_NEO4J_BOLT_PORT)
    parser.add_argument("--neo4j-http-port", type=int, default=write_tests.DEFAULT_NEO4J_HTTP_PORT)
    parser.add_argument("--neo4j-tx-url", default=write_tests.DEFAULT_NEO4J_TX_URL)
    parser.add_argument("--enable-neo4j-write", action="store_true")
    parser.add_argument("--cleanup-neo4j-test", action="store_true")
    parser.add_argument("--neo4j-batch-size", type=int, default=write_tests.DEFAULT_NEO4J_BATCH_SIZE)
    args = parser.parse_args(argv)

    if args.mode == "production":
        raise ValueError("production writes are blocked: implement a dedicated production writer after green gate canary")

    plan = build_plan(args)
    if args.mode == "canary":
        plan["canary_summary"] = run_canary(plan, args)
    out_dir = Path(plan["out_dir"])
    write_json(out_dir / "production_gate_plan.json", plan)
    write_markdown(plan, out_dir)
    print(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True))
    if plan["canary_summary"] and plan["canary_summary"]["embedding_stats"].get("failed", 0):
        return 1
    if any(row["status"] == "FAIL" for row in (plan.get("canary_summary") or {}).get("strategy_results", [])):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
