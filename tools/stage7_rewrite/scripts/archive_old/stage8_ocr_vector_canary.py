"""Run a small read-only OCR-populated Stage8 vector canary.

This uses the same in-memory evaluator as stage8_vector_semantic_eval.py. It
does not write Qdrant, Neo4j, PC DB, or embedding cache data.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCRIPT_DIR))

import stage8_vector_semantic_eval as semantic_eval


FORBIDDEN_D_ROOTS = {"d:", "d:\\", "d:\\ddownload", "d:\\aidata"}
ARTIFACT_EVENT_SIGNALS = (
    "活动",
    "派对",
    "演出",
    "阵容",
    "音乐",
    "club",
    "dj",
    "event",
    "lineup",
    "party",
    "show",
)
BAD_ARTIFACT_TITLES = {"微信公众平台"}
BAD_ARTIFACT_BODY_MARKERS = (
    "根据作者隐私设置",
    "看作者其他内容",
    "轻点两下取消赞",
    "轻点两下取消在看",
    "Body root not found",
)


def validate_artifact_root(artifact_root: Path) -> Path:
    resolved = artifact_root.resolve()
    normalized = str(resolved).rstrip("\\/").lower()
    if normalized in FORBIDDEN_D_ROOTS:
        raise ValueError(f"refusing unbounded artifact root: {resolved}")
    if not resolved.exists():
        raise FileNotFoundError(f"artifact root does not exist: {resolved}")
    if not resolved.is_dir():
        raise NotADirectoryError(f"artifact root is not a directory: {resolved}")
    return resolved


def prepare_materialized_output_root(path: Path) -> Path:
    resolved = path.resolve()
    if resolved.exists() and any(resolved.iterdir()):
        raise FileExistsError(f"materialized output root is not empty: {resolved}")
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def has_ocr_evidence(poster_ocr: Any) -> bool:
    return bool(semantic_eval.iter_ocr_evidence({"poster_ocr": poster_ocr}))


def artifact_text_fields(artifact_dir: Path, poster_ocr: Any) -> tuple[str, str, str]:
    meta = semantic_eval.safe_read_json(artifact_dir / "meta.json", {})
    sidecar = semantic_eval.safe_read_json(artifact_dir / "sidecar.json", {})
    rule_extract = semantic_eval.safe_read_json(artifact_dir / "rule_extract.json", {})
    sidecar_meta = sidecar.get("meta", {}) if isinstance(sidecar, dict) else {}
    title = str(meta.get("title") or sidecar_meta.get("title") or artifact_dir.name)
    main_content = (
        sidecar.get("main_content")
        if isinstance(sidecar, dict)
        else ""
    ) or rule_extract.get("body_text", "")
    ocr_text = " ".join(
        str(item.get("ocr_text", ""))
        for item in semantic_eval.iter_ocr_evidence({"poster_ocr": poster_ocr})
    )
    return title, str(main_content or ""), str(ocr_text or "")


def has_broad_vector_content(artifact_dir: Path, poster_ocr: Any) -> bool:
    title, main_content, ocr_text = artifact_text_fields(artifact_dir, poster_ocr)
    title_norm = " ".join(title.split())
    body_norm = " ".join((main_content or ocr_text).split())
    if title_norm in BAD_ARTIFACT_TITLES:
        sidecar = semantic_eval.safe_read_json(artifact_dir / "sidecar.json", {})
        rule_extract = semantic_eval.safe_read_json(artifact_dir / "rule_extract.json", {})
        warnings_text = " ".join(
            str(value)
            for value in [
                *(sidecar.get("warnings", []) if isinstance(sidecar, dict) else []),
                *(rule_extract.get("warnings", []) if isinstance(rule_extract, dict) else []),
            ]
        )
        archive = sidecar.get("archive", {}) if isinstance(sidecar, dict) else {}
        if (
            len(body_norm) < 200
            or any(marker in body_norm for marker in BAD_ARTIFACT_BODY_MARKERS)
            or any(marker in warnings_text for marker in BAD_ARTIFACT_BODY_MARKERS)
            or archive.get("status") == "partial"
        ):
            return False
    return bool(title_norm.strip() or body_norm.strip())


def collect_real_ocr_artifact_dirs(
    artifact_root: Path,
    sample: int,
    scan_limit: int,
    require_ocr: bool = True,
) -> tuple[list[Path], int]:
    root = validate_artifact_root(artifact_root)
    selected: list[Path] = []
    scanned = 0
    for poster_path in root.rglob("poster_ocr.json"):
        scanned += 1
        if scanned > scan_limit:
            break
        poster_ocr = semantic_eval.safe_read_json(poster_path, {})
        if require_ocr and not has_ocr_evidence(poster_ocr):
            continue
        if not require_ocr and not ((poster_path.parent / "sidecar.json").exists() or (poster_path.parent / "meta.json").exists()):
            continue
        if not require_ocr and not has_broad_vector_content(poster_path.parent, poster_ocr):
            continue
        selected.append(poster_path.parent)
        if len(selected) >= sample:
            break
    return selected, scanned


def safe_segment(value: str, fallback: str) -> str:
    text = (value or fallback).strip() or fallback
    for ch in '<>:"/\\|?*':
        text = text.replace(ch, "_")
    return text[:80] or fallback


def text_preview(value: Any, limit: int = 1200) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def artifact_event_like(*values: str) -> bool:
    text = " ".join(values).lower()
    return any(signal.lower() in text for signal in ARTIFACT_EVENT_SIGNALS)


def derive_artifact_cards(
    article_id: str,
    account: str,
    title: str,
    publish_time: str,
    main_content: str,
    ocr_text: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    evidence = text_preview(main_content or ocr_text or title, limit=180)
    entities = [
        {
            "entity_id": f"{article_id}:account",
            "name": account,
            "type": "organization",
            "aliases": [],
            "description": text_preview(title, limit=160),
            "evidence": [{"quote": evidence}] if evidence else [],
        }
    ]
    events: list[dict[str, Any]] = []
    if artifact_event_like(title, main_content, ocr_text):
        events.append(
            {
                "event_id": f"{article_id}:derived_event",
                "name": title,
                "type": "derived_artifact_event",
                "time": publish_time,
                "place": account,
                "participants": [],
                "description": text_preview(main_content or ocr_text, limit=400),
                "evidence": [{"quote": evidence}] if evidence else [],
            }
        )
    return entities, events


def build_article_from_artifact_dir(
    artifact_dir: Path,
    artifact_root: Path,
    derive_cards: bool = False,
) -> dict[str, Any]:
    meta = semantic_eval.safe_read_json(artifact_dir / "meta.json", {})
    sidecar = semantic_eval.safe_read_json(artifact_dir / "sidecar.json", {})
    poster_ocr = semantic_eval.safe_read_json(artifact_dir / "poster_ocr.json", {})
    sidecar_meta = sidecar.get("meta", {}) if isinstance(sidecar, dict) else {}
    account = (
        meta.get("account_name")
        or sidecar_meta.get("account_name")
        or artifact_dir.parent.name
    )
    title, main_content, ocr_text = artifact_text_fields(artifact_dir, poster_ocr)
    rel = artifact_dir.relative_to(artifact_root)
    article_id = artifact_dir.name
    publish_time = meta.get("publish_time_iso") or meta.get("publish_time_text") or ""
    entities: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    if derive_cards:
        entities, events = derive_artifact_cards(
            article_id,
            str(account),
            str(title),
            str(publish_time),
            str(main_content),
            str(ocr_text),
        )
    return {
        "schema_version": "article_extract.v1",
        "article_id": article_id,
        "article_uid": article_id,
        "title": title,
        "source_account": account,
        "publish_time": publish_time,
        "url": meta.get("source_url", ""),
        "summary": text_preview(main_content or ocr_text),
        "topics": [],
        "entities": entities,
        "events": events,
        "relations": [],
        "claims": [],
        "poster_ocr": poster_ocr,
        "source_artifact_dir": str(artifact_dir),
        "source_artifact_rel": str(rel),
    }


def materialize_artifact_extracts(
    artifact_dirs: list[Path],
    artifact_root: Path,
    output_root: Path,
    derive_cards: bool = False,
) -> list[Path]:
    extract_files: list[Path] = []
    for artifact_dir in artifact_dirs:
        article = build_article_from_artifact_dir(artifact_dir, artifact_root, derive_cards=derive_cards)
        account_dir = safe_segment(str(article.get("source_account", "")), "unknown_account")
        article_dir = safe_segment(str(article.get("article_uid", "")), "unknown_article")
        extract_path = output_root / "llm_extract" / f"real_ocr__{account_dir}" / article_dir / "extract.article.v1.json"
        extract_path.parent.mkdir(parents=True, exist_ok=True)
        extract_path.write_text(json.dumps(article, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        extract_files.append(extract_path)
    return extract_files


def select_extract_files(output_root: Path, sample: int, extract_scope: str, require_ocr: bool) -> list[Path]:
    selected: list[Path] = []
    seen: set[Path] = set()
    all_files = semantic_eval.iter_extract_files(output_root, sample=1000000, extract_scope=extract_scope)
    if require_ocr:
        for path in all_files:
            article = semantic_eval.safe_read_json(path, {})
            if article and semantic_eval.iter_ocr_evidence(article):
                selected.append(path)
                seen.add(path)
                if len(selected) >= sample:
                    return selected
    for path in semantic_eval.iter_extract_files(output_root, sample=sample * 4, extract_scope=extract_scope):
        if path in seen:
            continue
        selected.append(path)
        seen.add(path)
        if len(selected) >= sample:
            break
    return selected


def summarize_result(result: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "query_count",
        "candidate_policy",
        "candidate_cap",
        "avg_candidates_before_cap",
        "avg_candidates_scored",
        "recall_at_5",
        "rank1",
        "rank1_rate",
        "mrr_at_10",
        "city_precision_at_10",
        "object_kind_precision_at_10",
        "negative_leaks_at_10",
        "source_quality_at_10",
        "bad_source_leaks_at_10",
        "review_lane_top3_rate",
        "low_source_top3_rate",
        "avg_unique_accounts_at_10",
        "avg_unique_cities_at_10",
        "event_card_share_at_10",
        "hard_negative_query_count",
        "hard_negative_pass_rate",
        "source_gate_query_count",
        "source_gate_pass_rate",
    ]
    summary = {key: result.get(key) for key in keys}
    if summary.get("rank1") is None:
        summary["rank1"] = result.get("rank1_rate")
    summary["by_intent"] = {
        name: {
            "query_count": value.get("query_count"),
            "recall_at_5": value.get("recall_at_5"),
            "rank1": value.get("rank1") if value.get("rank1") is not None else value.get("rank1_rate"),
            "rank1_rate": value.get("rank1_rate"),
            "mrr_at_10": value.get("mrr_at_10"),
            "object_kind_precision_at_10": value.get("object_kind_precision_at_10"),
        }
        for name, value in sorted(result.get("by_intent", {}).items())
    }
    summary["ocr_query_top3"] = [
        {
            "id": query.get("id"),
            "first_hit_rank": query.get("first_hit_rank"),
            "top3": query.get("top3", []),
        }
        for query in result.get("queries", [])
        if query.get("intent") == "ocr_evidence_lookup"
    ]
    return summary


def run_canary(args: argparse.Namespace) -> dict[str, Any]:
    root = ROOT
    temp_dir: TemporaryDirectory[str] | None = None
    artifact_root: Path | None = None
    artifact_dirs: list[Path] = []
    artifact_scan_count: int | None = None
    try:
        if args.artifact_root:
            artifact_root = validate_artifact_root(Path(args.artifact_root))
            artifact_dirs, artifact_scan_count = collect_real_ocr_artifact_dirs(
                artifact_root,
                args.sample,
                args.artifact_scan_limit,
                require_ocr=args.artifact_require_ocr,
            )
            if args.materialized_output_root:
                output_root = prepare_materialized_output_root(Path(args.materialized_output_root))
            else:
                temp_dir = TemporaryDirectory(prefix="stage8_ocr_vector_canary_")
                output_root = Path(temp_dir.name)
            extract_files = materialize_artifact_extracts(
                artifact_dirs,
                artifact_root,
                output_root,
                derive_cards=args.artifact_derived_cards,
            )
        else:
            output_root = Path(args.output_root)
            if not output_root.is_absolute():
                output_root = root / output_root
            extract_files = select_extract_files(
                output_root,
                args.sample,
                args.extract_scope,
                args.require_ocr,
            )
        if not extract_files:
            raise ValueError("no extract files selected for OCR vector canary")
        report: dict[str, Any] = {
            "schema_version": "stage8_ocr_vector_canary.v1",
            "input_mode": "artifact_root" if artifact_root else "output_root",
            "output_root": str(output_root),
            "endpoint_url": args.endpoint_url,
            "endpoint_model": getattr(args, "endpoint_model", None),
            "endpoint_dim": getattr(args, "endpoint_dim", None),
            "files_selected": len(extract_files),
            "extract_files": [str(path.relative_to(output_root)) for path in extract_files],
            "materialize_only": bool(args.materialize_only),
            "query_count": 0,
            "query_intents": {},
            "variants": {},
        }
        if artifact_root:
            report["artifact_root"] = str(artifact_root)
            report["artifact_scan_count"] = artifact_scan_count
            report["artifact_derived_cards"] = bool(args.artifact_derived_cards)
            report["artifact_require_ocr"] = bool(args.artifact_require_ocr)
            report["artifact_dirs"] = [str(path.relative_to(artifact_root)) for path in artifact_dirs]
        if args.materialize_only:
            return report
        eval_queries = semantic_eval.build_eval_queries(
            output_root,
            extract_files,
            query_mode=args.query_mode,
            auto_query_limit=args.auto_query_limit,
            auto_query_per_article=args.auto_query_per_article,
            hard_negative_limit=args.hard_negative_limit,
            hard_negative_per_article=args.hard_negative_per_article,
        )
        report["query_count"] = len(eval_queries)
        report["query_intents"] = dict(Counter(str(query.get("intent", "unknown")) for query in eval_queries))
        variants = [part.strip() for part in args.variants.split(",") if part.strip()]
        for variant in variants:
            jobs = semantic_eval.build_variant_jobs_from_files(
                root,
                output_root,
                variant,
                extract_files,
                max_jobs=args.max_jobs,
                endpoint_override=args.endpoint_url,
                model_override=getattr(args, "endpoint_model", None),
                dim_override=getattr(args, "endpoint_dim", None),
            )
            result = semantic_eval.evaluate_variant(
                jobs,
                queries=eval_queries,
                score_profile=args.score_profile,
                cache=None,
                candidate_policy=args.candidate_policy,
                candidate_cap=args.candidate_cap,
            )
            variant_summary = summarize_result(result)
            variant_summary["job_count"] = len(jobs)
            variant_summary["object_kinds"] = sorted({job.object_kind for job in jobs})
            report["variants"][variant] = variant_summary
        return report
    finally:
        if temp_dir:
            temp_dir.cleanup()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-root",
        default="tests/fixtures/ocr_vector_canary",
        help="Stage8-style output root containing llm_extract/**/extract.article.v1.json",
    )
    parser.add_argument(
        "--artifact-root",
        default="",
        help="Optional bounded Stage7 artifact root; real poster_ocr.json files are materialized into a temporary eval root",
    )
    parser.add_argument("--artifact-scan-limit", type=int, default=2000)
    parser.add_argument("--artifact-require-ocr", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--artifact-derived-cards", action="store_true")
    parser.add_argument(
        "--materialized-output-root",
        default="",
        help="Optional empty output root to keep materialized Stage8-style extracts for downstream write tests",
    )
    parser.add_argument("--materialize-only", action="store_true")
    parser.add_argument("--endpoint-url", default="http://192.168.8.234:11437")
    parser.add_argument("--endpoint-model", default=None, help="Override embedding request model for candidate-model eval lanes")
    parser.add_argument("--endpoint-dim", type=int, default=None, help="Override expected embedding dimension for candidate-model eval lanes")
    parser.add_argument("--sample", type=int, default=3)
    parser.add_argument("--extract-scope", choices=["primary", "all"], default="primary")
    parser.add_argument("--require-ocr", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--variants", default="multi_card,research_v1")
    parser.add_argument("--score-profile", default="adaptive_v3_source_guard")
    parser.add_argument("--query-mode", default="auto")
    parser.add_argument("--auto-query-limit", type=int, default=24)
    parser.add_argument("--auto-query-per-article", type=int, default=8)
    parser.add_argument("--hard-negative-limit", type=int, default=0)
    parser.add_argument("--hard-negative-per-article", type=int, default=0)
    parser.add_argument("--candidate-policy", default="prefilter_v1")
    parser.add_argument("--candidate-cap", type=int, default=50)
    parser.add_argument("--max-jobs", type=int, default=0)
    args = parser.parse_args(argv)
    print(json.dumps(run_canary(args), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
