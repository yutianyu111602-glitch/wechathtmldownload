"""CLI entry point for Stage 7 rewrite pipeline."""
from __future__ import annotations
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime, timezone

import yaml

from .config import load_config, Config
from .paths import ensure_output_dirs
from .logging_setup import setup_logging
from .audit_inputs import audit_inputs
from .manifest_builder import build_manifest
from .sqlite_state import SQLiteState
from .llm_worker import LlmWorker
from .report_writer import write_batch_report, write_canary_report, write_run_status_md
from .vector_plan.build_embedding_jobs import build_jobs_from_article
from .vector_plan.schemas import VectorManifest
from .vector_plan.qdrant_prepare import build_collection_defs, write_collection_plan
from .vector_plan.embed_runner import run_vector_jobs_async, default_embedding_paths, find_latest_jobs
from .atomic_io import safe_read_json
from stage9.graph_builder import process_single_article
from stage9.export_preview import export_pack


def cmd_doctor(args):
    """Health check for the pipeline environment."""
    print("=== Stage 7 Rewrite Doctor ===")
    issues = []

    # Python version
    import platform
    py_ver = platform.python_version()
    print(f"Python: {py_ver}")
    if tuple(map(int, py_ver.split(".")[:2])) < (3, 10):
        issues.append("Python < 3.10")

    # Dependencies
    try:
        import yaml
        print("PyYAML: OK")
    except ImportError:
        issues.append("PyYAML missing")
        print("PyYAML: MISSING")

    try:
        import httpx
        print("httpx: OK")
    except ImportError:
        issues.append("httpx missing")
        print("httpx: MISSING")

    # Input directory
    config = load_config()
    input_root = Path(args.input) if getattr(args, "input", None) else config.input_root
    output_root = Path(args.output) if getattr(args, "output", None) else config.output_root
    if input_root.exists():
        print(f"Input root: {input_root} (exists)")
    else:
        issues.append(f"Input root missing: {input_root}")
        print(f"Input root: {input_root} (MISSING)")

    # Output directory
    try:
        ensure_output_dirs(output_root)
        print(f"Output root: {output_root} (writable)")
    except Exception as e:
        issues.append(f"Output root not writable: {e}")
        print(f"Output root: {config.output_root} (ERROR)")

    # LLM endpoint
    from .llm_client import LlmClient
    client = LlmClient(config.llm)
    health = client.health_check()
    if health["ok"]:
        models = health.get("models", [])
        print(f"LLM endpoint: {config.llm.endpoint} (OK, models: {len(models)})")
        if models:
            print(f"  Available: {', '.join(models[:5])}")
    else:
        issues.append(f"LLM endpoint unreachable: {health.get('error')}")
        print(f"LLM endpoint: {config.llm.endpoint} (UNREACHABLE: {health.get('error')})")
    client.close()

    # Summary
    print(f"\n=== Result ===")
    if issues:
        print(f"Issues found: {len(issues)}")
        for i in issues:
            print(f"  - {i}")
        return 1
    else:
        print("All checks passed.")
        return 0


def cmd_audit(args):
    config = load_config()
    output = Path(args.output) if args.output else config.output_root
    input_root = Path(args.input) if args.input else config.input_root
    report = audit_inputs(input_root, output)
    print(f"Audit complete: {report['article_count']} articles")
    print(f"Report: {output / 'manifests' / 'input_audit_report.md'}")
    return 0


def cmd_build_manifest(args):
    config = load_config()
    output = Path(args.output) if args.output else config.output_root
    mode = args.mode or "canary"
    limit = int(args.limit) if args.limit else None
    stats = build_manifest(output, limit=limit, mode=mode)
    print(json.dumps(stats, indent=2, ensure_ascii=False))
    return 0


def cmd_run_llm(args):
    config_path = Path(args.config) if getattr(args, "config", None) else None
    config = load_config(config_path)
    output = Path(args.output) if args.output else config.output_root
    mode = args.mode or "canary"
    limit = int(args.limit) if args.limit else None
    resume = getattr(args, "resume", False)
    allow_empty_recovery = getattr(args, "allow_empty_recovery", False)
    run_id = getattr(args, "run_id", None) or f"{mode}_{__import__('datetime').datetime.now().strftime('%Y%m%d_%H%M%S')}"

    ensure_output_dirs(output)
    logger = setup_logging(output / "logs", f"stage7_{run_id}")
    state = SQLiteState(output / "state" / "pipeline.sqlite")

    print(f"Run ID: {run_id}")

    # Resume: reset stale running to pending
    if resume:
        reset_count = state.reset_stale_running(mode)
        if reset_count > 0:
            print(f"Resume: reset {reset_count} stale running articles to pending")

    # Production guard
    if mode == "production":
        if not getattr(args, "confirm_production", False):
            print("ERROR: production mode requires --confirm-production")
            return 1
        pilot_report = output / "reports" / "BATCH_500_REPORT.md"
        if not pilot_report.exists():
            print("WARNING: Pilot 500 report not found. Proceed with caution.")

    # Load manifest
    manifest_path = output / "manifests" / f"processing_manifest.{mode}.jsonl"
    if not manifest_path.exists():
        print(f"Manifest not found: {manifest_path}")
        return 1

    records = []
    with open(manifest_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            # Resume: skip already processed articles (same mode only)
            if resume:
                db_status = state.get_status(r["article_uid"])
                db_mode = state.get_mode(r["article_uid"])
                if db_status in ("done", "done_with_warnings", "failed_final", "skipped") and db_mode == mode:
                    continue
            if r.get("status") == "pending":
                records.append(r)

    if limit:
        records = records[:limit]

    print(f"Mode: {mode}, articles to process: {len(records)}, resume={resume}, allow_empty_recovery={allow_empty_recovery}")

    worker = LlmWorker(config, state, logger, allow_empty_recovery=allow_empty_recovery)
    results = []

    try:
        for i, record in enumerate(records):
            print(f"[{i+1}/{len(records)}] {record['source_account']} / {record['article_id']}")
            result = worker.process_article(record, mode=mode)
            results.append(result)

            # Update checkpoint every 5 articles
            if (i + 1) % 5 == 0:
                stats = state.get_stats(mode)
                processed_total = (
                    stats.get("done", 0)
                    + stats.get("done_with_warnings", 0)
                    + stats.get("failed_retryable", 0)
                    + stats.get("failed_final", 0)
                    + stats.get("skipped", 0)
                )
                stats["phase"] = mode
                stats["percent"] = (processed_total / max(stats["total"], 1)) * 100
                write_run_status_md(output, {
                    **stats,
                })
    finally:
        worker.close()

    # Write report
    if mode == "canary":
        report_path = write_canary_report(output, results)
        print(f"\nCanary report: {report_path}")

    stats = state.get_stats(mode)
    if mode != "canary":
        report_path = write_batch_report(output, mode, results, stats)
        print(f"\nBatch report: {report_path}")
    stats = state.get_stats(mode)
    stats["phase"] = mode
    write_run_status_md(output, stats)
    done_total = stats.get("done", 0) + stats.get("done_with_warnings", 0)
    print(f"\nDone: {done_total}, Failed: {stats['failed_retryable'] + stats['failed_final']}, Pending: {stats['pending']}")
    return 0


def cmd_report(args):
    config = load_config()
    output = Path(args.output) if args.output else config.output_root
    state = SQLiteState(output / "state" / "pipeline.sqlite")
    for mode in ["canary", "batch50", "batch100", "batch500", "full"]:
        try:
            stats = state.get_stats(mode)
            print(f"Mode {mode}: {json.dumps(stats, indent=2, ensure_ascii=False)}")
        except Exception:
            pass
    return 0


def cmd_build_vector_jobs(args):
    """Build vector embedding jobs from Stage 7 extract output."""
    output = Path(args.output) if args.output else load_config().output_root
    sample = int(args.sample) if args.sample else None

    config_path = Path(args.vector_config) if getattr(args, "vector_config", None) else (
        Path(__file__).parent.parent / "config" / "vector_endpoints.yaml"
    )
    if not config_path.exists():
        print(f"ERROR: vector config not found: {config_path}")
        return 1
    with open(config_path, "r", encoding="utf-8") as f:
        vec_config = yaml.safe_load(f) or {}

    ep_key = vec_config.get("default_chinese_endpoint", "local_mac_vector_endpoint_11437")
    ep_def = vec_config.get("endpoints", {}).get(ep_key, {})
    model = ep_def.get("model", "stella-large-zh-v2")
    endpoint_url = ep_def.get("pc_call_url") or ep_def.get("url", "http://192.168.8.234:11437")
    dim = ep_def.get("dim", 1024)
    route_metadata = {
        "endpoint_id": ep_def.get("endpoint_id") or ep_key,
        "endpoint_port": int(str(endpoint_url).rstrip("/").rsplit(":", 1)[-1]),
        "canonical_url": ep_def.get("canonical_url", ""),
        "pc_call_url": ep_def.get("pc_call_url", endpoint_url),
        "route_role": ep_def.get("route_role", "wechat_93k_default"),
        "dim_expected": int(dim),
    }

    extract_dir = output / "llm_extract"
    if not extract_dir.exists():
        print(f"ERROR: llm_extract dir not found: {extract_dir}")
        return 1

    all_jobs = []
    by_unit_type: dict[str, int] = {}
    files_scanned = 0

    for account_dir in sorted(extract_dir.iterdir()):
        if not account_dir.is_dir():
            continue
        for article_dir in sorted(account_dir.iterdir()):
            if not article_dir.is_dir():
                continue
            ef = article_dir / "extract.article.v1.json"
            if not ef.exists():
                continue
            article_data = safe_read_json(ef, {})
            if not article_data:
                continue
            files_scanned += 1
            rel_path = str(ef.relative_to(output))
            jobs = build_jobs_from_article(
                article_data,
                rel_path,
                model,
                endpoint_url,
                dim,
                route_metadata,
                card_template=args.card_template,
            )
            for job in jobs:
                all_jobs.append(job)
                by_unit_type[job.object_kind] = by_unit_type.get(job.object_kind, 0) + 1
            if sample and files_scanned >= sample:
                break
        if sample and files_scanned >= sample:
            break

    jobs_dir = output / "stage8" / "jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)
    if args.card_template == "baseline":
        suffix = f".sample{sample}" if sample else ""
    else:
        suffix = f".{args.card_template}.sample{sample}" if sample else f".{args.card_template}"
    jobs_path = jobs_dir / f"vector_jobs{suffix}.jsonl"

    with open(jobs_path, "w", encoding="utf-8") as f:
        for job in all_jobs:
            f.write(json.dumps(job.to_dict(), ensure_ascii=False, default=str) + "\n")

    manifest = VectorManifest(
        source_stage7_root=str(output),
        job_count=len(all_jobs),
        by_unit_type=by_unit_type,
        embedding_models=[model],
    )
    manifest_path = jobs_dir / f"vector_manifest{suffix}.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest.to_dict(), f, ensure_ascii=False, indent=2, default=str)

    collection_defs = build_collection_defs(model=model, dim=dim)
    plan_path = write_collection_plan(jobs_dir, collection_defs)

    stats = {
        "job_count": len(all_jobs),
        "files_scanned": files_scanned,
        "by_unit_type": by_unit_type,
        "jobs_path": str(jobs_path),
        "manifest_path": str(manifest_path),
        "collection_plan_path": str(plan_path),
        "model": model,
        "endpoint": endpoint_url,
        "dim": dim,
        "card_template": args.card_template,
    }
    print(json.dumps(stats, indent=2, ensure_ascii=False, default=str))
    return 0


def cmd_run_vectors(args):
    """Run vector embedding jobs and write embeddings JSONL."""
    import asyncio

    output = Path(args.output) if args.output else load_config().output_root
    jobs_path = Path(args.jobs) if args.jobs else find_latest_jobs(output)
    embeddings_path, failures_path = default_embedding_paths(output, jobs_path)
    if args.embeddings:
        embeddings_path = Path(args.embeddings)
    if args.failures:
        failures_path = Path(args.failures)

    stats = asyncio.run(
        run_vector_jobs_async(
            jobs_path,
            embeddings_path,
            failures_path,
            concurrency=max(1, int(args.concurrency or 4)),
            limit=int(args.limit) if args.limit else None,
            resume=bool(args.resume),
            timeout_sec=int(args.timeout_sec or 120),
            batch_size=max(1, int(args.batch_size or 1)),
        )
    )
    print(json.dumps(stats.to_dict(), indent=2, ensure_ascii=False))
    return 0 if stats.failed == 0 else 1


def cmd_build_graph_pack(args):
    output = Path(args.output) if args.output else load_config().output_root
    sample = int(args.sample) if args.sample else None

    extract_root = output / "llm_extract"
    if not extract_root.exists():
        print(f"Extract root not found: {extract_root}")
        return 1

    json_files = sorted(extract_root.rglob("extract.article.v1.json"))
    if sample:
        json_files = json_files[:sample]

    if not json_files:
        print("No extract.article.v1.json files found.")
        return 1

    print(f"Found {len(json_files)} article extracts")

    all_entities = []
    all_events = []
    all_edges = []
    all_relations = []
    article_count = 0

    for i, fpath in enumerate(json_files):
        result = process_single_article(fpath)
        if result is None:
            continue
        article_count += 1
        all_entities.extend(result["entity_nodes"])
        all_events.extend(result["event_nodes"])
        all_edges.extend(result["edges"])

        try:
            with open(fpath, "r", encoding="utf-8") as f:
                raw = json.load(f)
            for rel in raw.get("relations", []):
                rel["_article_uid"] = result["article_uid"]
                all_relations.append(rel)
        except Exception:
            pass

        if (i + 1) % 20 == 0:
            print(f"  [{i+1}/{len(json_files)}] entities={len(all_entities)} events={len(all_events)} edges={len(all_edges)}")

    print(f"Processed {article_count} articles: {len(all_entities)} entities, {len(all_events)} events, {len(all_edges)} edges")

    gc_dir = export_pack(output, all_entities, all_events, all_edges, all_relations, article_count, sample_limit=sample)
    print(f"Graph candidate pack written to: {gc_dir}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Stage 7 Rewrite Pipeline")
    parser.add_argument("--output", default=None, help="Output root directory")
    sub = parser.add_subparsers(dest="command")

    # doctor
    p_doctor = sub.add_parser("doctor", help="Environment health check")
    p_doctor.add_argument("--input", default=None, help="Input root override")
    p_doctor.add_argument("--output", default=None, help="Output root override")

    # audit
    p_audit = sub.add_parser("audit", help="Audit input directory")
    p_audit.add_argument("--input", default=None, help="Input root")
    p_audit.add_argument("--output", default=None, help="Output root")

    # build-manifest
    p_manifest = sub.add_parser("build-manifest", help="Build processing manifest")
    p_manifest.add_argument("--input", default=None, help="Input root")
    p_manifest.add_argument("--output", default=None, help="Output root")
    p_manifest.add_argument("--mode", default="canary", help="Mode: canary/batch50/batch500/full")
    p_manifest.add_argument("--limit", default=None, help="Limit articles")

    # run-llm
    p_run = sub.add_parser("run-llm", help="Run LLM extraction")
    p_run.add_argument("--mode", default="canary", help="Mode")
    p_run.add_argument("--limit", default=None, help="Limit articles")
    p_run.add_argument("--output", default=None, help="Output root")
    p_run.add_argument("--confirm-production", action="store_true", help="Confirm production run")
    p_run.add_argument("--resume", action="store_true", help="Resume interrupted run")
    p_run.add_argument("--allow-empty-recovery", action="store_true", help="Allow empty result recovery (default: false)")
    p_run.add_argument("--run-id", default=None, help="Run identifier for logging and state isolation")
    p_run.add_argument("--config", default=None, help="Custom config YAML path")

    # report
    sub.add_parser("report", help="Show run reports")

    # build-vector-jobs
    p_vec = sub.add_parser("build-vector-jobs", help="Build vector embedding jobs from Stage 7 output")
    p_vec.add_argument("--output", default=None, help="Stage 7 output root")
    p_vec.add_argument("--sample", default=None, help="Limit to N articles")
    p_vec.add_argument("--vector-config", default=None, help="Path to vector_endpoints.yaml")
    p_vec.add_argument("--card-template", default="baseline", choices=["baseline", "labeled_v2", "multi_card", "research_v1"], help="Canonical text/card template")

    # run-vectors
    p_run_vec = sub.add_parser("run-vectors", help="Run vector embedding jobs")
    p_run_vec.add_argument("--output", default=None, help="Stage 7 output root")
    p_run_vec.add_argument("--jobs", default=None, help="vector_jobs JSONL path")
    p_run_vec.add_argument("--embeddings", default=None, help="Output embeddings JSONL")
    p_run_vec.add_argument("--failures", default=None, help="Output failures JSONL")
    p_run_vec.add_argument("--limit", default=None, help="Limit jobs")
    p_run_vec.add_argument("--concurrency", default=4, help="Concurrent embedding requests")
    p_run_vec.add_argument("--batch-size", default=1, help="Texts per embedding request")
    p_run_vec.add_argument("--resume", action="store_true", help="Skip existing text_sha1 embeddings")
    p_run_vec.add_argument("--timeout-sec", default=120, help="HTTP timeout seconds")

    # build-graph-pack
    p_graph = sub.add_parser("build-graph-pack", help="Build graph candidate pack from Stage 7 output")
    p_graph.add_argument("--output", default=None, help="Stage 7 output root")
    p_graph.add_argument("--sample", default=None, help="Limit to N articles")

    args = parser.parse_args(argv)

    if args.command == "doctor":
        return cmd_doctor(args)
    elif args.command == "audit":
        return cmd_audit(args)
    elif args.command == "build-manifest":
        return cmd_build_manifest(args)
    elif args.command == "run-llm":
        return cmd_run_llm(args)
    elif args.command == "report":
        return cmd_report(args)
    elif args.command == "build-vector-jobs":
        return cmd_build_vector_jobs(args)
    elif args.command == "run-vectors":
        return cmd_run_vectors(args)
    elif args.command == "build-graph-pack":
        return cmd_build_graph_pack(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
