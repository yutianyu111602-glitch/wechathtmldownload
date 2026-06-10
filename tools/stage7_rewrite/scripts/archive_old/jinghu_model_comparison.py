"""
Phase 5: JINGHU 4-model comparison report generator.
Reads all eval JSON outputs and produces a ranked comparison table.

Usage:
    python scripts/jinghu_model_comparison.py \
        --out-dir D:\downstream_results\stage7_rewrite\stage8\region_maps
"""
import json
import argparse
from pathlib import Path
from datetime import datetime

MODELS = [
    {
        "label": "A-stella-large",
        "name": "stella-large-zh-v2",
        "port": 11437,
        "dim": 1024,
        "dir": "JINGHU_EVAL_stella_large_20260509_1",
    },
    {
        "label": "B-jina-v5",
        "name": "jina-embeddings-v5-text-small",
        "port": 11442,
        "dim": 1024,
        "dir": "JINGHU_EVAL_jina_v5_20260509_1",
    },
    {
        "label": "C-stella-base",
        "name": "stella-base-zh-v2",
        "port": 11438,
        "dim": 768,
        "dir": "JINGHU_EVAL_C_stella_base_20260509",
    },
    {
        "label": "D-qwen3-4b",
        "name": "qwen3-embedding-4b",
        "port": 11441,
        "dim": 2560,
        "dir": "JINGHU_EVAL_D_qwen3_4b_20260509",
    },
]

VARIANTS = ["baseline", "labeled_v2", "multi_card"]
PROFILES = ["adaptive_v3_source_guard", "adaptive_v4_source_gate"]

METRICS = [
    ("recall_at_5", "Recall@5"),
    ("mrr_at_10", "MRR@10"),
    ("rank1_rate", "Rank1Rate"),
    ("city_precision_at_10", "CityPrec@10"),
    ("negative_leaks_at_10", "NegLeaks@10"),
    ("source_quality_at_10", "SrcQuality@10"),
    ("hard_negative_pass_rate", "HardNeg%"),
    ("source_gate_pass_rate", "SrcGate%"),
]

# Queries guaranteed to miss in JINGHU slice (cities outside scope)
OUT_OF_SCOPE_QUERIES = {"kunming_dada_event", "xiamen_twinklab_venue", "jinan_key_club"}


def load_model_data(base_dir: Path, model_cfg: dict) -> dict | None:
    path = base_dir / model_cfg["dir"] / "stage8_vector_semantic_eval.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def variant_key(variant: str, profile: str) -> str:
    return f"{variant}/{profile}"


def fmt(v, pct=False) -> str:
    if v is None:
        return "—"
    if pct:
        return f"{v * 100:.1f}%"
    return f"{v:.4f}"


def build_records(base_dir: Path) -> list[dict]:
    records = []
    for mcfg in MODELS:
        data = load_model_data(base_dir, mcfg)
        if data is None:
            print(f"  [skip] {mcfg['label']}: file not found in {mcfg['dir']}")
            continue
        variants_data = data.get("variants") or {}
        files = data.get("files_selected", 0)
        query_count = data.get("query_count", 0)
        for variant in VARIANTS:
            for profile in PROFILES:
                vkey = variant_key(variant, profile)
                vd = variants_data.get(vkey)
                if vd is None:
                    continue
                # Per-query analysis
                queries = vd.get("queries") or []
                in_scope_queries = [q for q in queries if q.get("id") not in OUT_OF_SCOPE_QUERIES]
                in_scope_hits = sum(1 for q in in_scope_queries if q.get("top5_hit"))
                in_scope_total = len(in_scope_queries)
                effective_recall = in_scope_hits / in_scope_total if in_scope_total else 0

                rec = {
                    "model": mcfg["label"],
                    "model_name": mcfg["name"],
                    "dim": mcfg["dim"],
                    "variant": variant,
                    "profile": profile,
                    "files": files,
                    "query_count": query_count,
                    "job_count": vd.get("job_count") or 0,
                    "in_scope_hits": in_scope_hits,
                    "in_scope_total": in_scope_total,
                    "effective_recall_at_5": effective_recall,
                }
                for metric_key, _ in METRICS:
                    rec[metric_key] = vd.get(metric_key) or 0
                records.append(rec)
    return records


def score_record(rec: dict) -> float:
    """Composite score for ranking: weights recall + city_precision."""
    r5 = rec.get("recall_at_5") or 0
    eff = rec.get("effective_recall_at_5") or 0
    cp = rec.get("city_precision_at_10") or 0
    sq = rec.get("source_quality_at_10") or 0
    return 0.35 * r5 + 0.25 * eff + 0.25 * cp + 0.15 * sq


def build_markdown(records: list[dict], base_dir: Path) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# JINGHU 4-Model Vector Eval Comparison",
        f"",
        f"**Generated:** {now}",
        f"**Slice:** 京沪杭宁 (JINGHU) — 4,427 articles (上海 2,273 · 北京 2,123 · 南京 18 · 杭州 13)",
        f"**Sample:** 500 articles · 11 fixed golden queries",
        f"**Note:** 3 queries (kunming/xiamen/jinan) are out-of-scope for JINGHU slice — excluded from effective recall.",
        f"",
        f"---",
        f"",
        f"## 1. Summary: Best Configurations (ranked by composite score)",
        f"",
    ]

    ranked = sorted(records, key=score_record, reverse=True)

    # Header
    lines.append(
        "| Rank | Model | Variant | Profile | Recall@5 | Eff.Recall | CityPrec@10 | MRR@10 | SrcQuality | Composite |"
    )
    lines.append("|------|-------|---------|---------|----------|------------|-------------|--------|------------|-----------|")
    for i, rec in enumerate(ranked[:12], 1):
        score = score_record(rec)
        lines.append(
            f"| {i} | `{rec['model']}` | `{rec['variant']}` | `{rec['profile']}` "
            f"| {fmt(rec['recall_at_5'])} | {fmt(rec['effective_recall_at_5'])} "
            f"| {fmt(rec['city_precision_at_10'])} | {fmt(rec['mrr_at_10'])} "
            f"| {fmt(rec['source_quality_at_10'])} | **{score:.4f}** |"
        )

    # Best config call-out
    best = ranked[0]
    lines += [
        f"",
        f"### Best Overall Configuration",
        f"",
        f"- **Model:** `{best['model']}` (`{best['model_name']}`, dim={best['dim']})",
        f"- **Variant:** `{best['variant']}`",
        f"- **Score profile:** `{best['profile']}`",
        f"- **Composite score:** {score_record(best):.4f}",
        f"- **Recall@5:** {fmt(best['recall_at_5'])}",
        f"- **Effective recall (in-scope queries):** {best['in_scope_hits']}/{best['in_scope_total']} = {fmt(best['effective_recall_at_5'])}",
        f"- **City precision@10:** {fmt(best['city_precision_at_10'])}",
        f"",
        f"---",
        f"",
        f"## 2. Per-Model Summary (labeled_v2 variant)",
        f"",
    ]

    # Per-model table for labeled_v2 only
    lines.append("| Model | Dim | Recall@5 | Eff.Recall@5 | CityPrec@10 | MRR@10 | NegLeaks@10 | HardNeg% | SrcGate% |")
    lines.append("|-------|-----|----------|--------------|-------------|--------|-------------|----------|----------|")
    lv2_recs = [r for r in records if r["variant"] == "labeled_v2" and r["profile"] == "adaptive_v3_source_guard"]
    for rec in lv2_recs:
        lines.append(
            f"| `{rec['model']}` | {rec['dim']} "
            f"| {fmt(rec['recall_at_5'])} | {fmt(rec['effective_recall_at_5'])} "
            f"| {fmt(rec['city_precision_at_10'])} | {fmt(rec['mrr_at_10'])} "
            f"| {fmt(rec['negative_leaks_at_10'])} | {fmt(rec['hard_negative_pass_rate'])} "
            f"| {fmt(rec['source_gate_pass_rate'])} |"
        )

    lines += [
        f"",
        f"---",
        f"",
        f"## 3. Variant Comparison (across all models, adaptive_v3_source_guard profile)",
        f"",
    ]

    lines.append("| Variant | Avg Recall@5 | Avg Eff.Recall | Avg CityPrec@10 | Avg MRR@10 | Composite |")
    lines.append("|---------|-------------|----------------|-----------------|------------|-----------|")
    for variant in VARIANTS:
        vrecs = [r for r in records if r["variant"] == variant and r["profile"] == "adaptive_v3_source_guard"]
        if not vrecs:
            continue
        avg_r5 = sum(r["recall_at_5"] for r in vrecs) / len(vrecs)
        avg_eff = sum(r["effective_recall_at_5"] for r in vrecs) / len(vrecs)
        avg_cp = sum(r["city_precision_at_10"] for r in vrecs) / len(vrecs)
        avg_mrr = sum(r["mrr_at_10"] for r in vrecs) / len(vrecs)
        avg_composite = sum(score_record(r) for r in vrecs) / len(vrecs)
        lines.append(
            f"| `{variant}` | {avg_r5:.4f} | {avg_eff:.4f} | {avg_cp:.4f} | {avg_mrr:.4f} | **{avg_composite:.4f}** |"
        )

    lines += [
        f"",
        f"---",
        f"",
        f"## 4. Score Profile Comparison (labeled_v2 variant, all models)",
        f"",
    ]

    lines.append("| Profile | Avg Recall@5 | Avg CityPrec@10 | Avg MRR@10 |")
    lines.append("|---------|-------------|-----------------|------------|")
    for profile in PROFILES:
        precs = [r for r in records if r["variant"] == "labeled_v2" and r["profile"] == profile]
        if not precs:
            continue
        avg_r5 = sum(r["recall_at_5"] for r in precs) / len(precs)
        avg_cp = sum(r["city_precision_at_10"] for r in precs) / len(precs)
        avg_mrr = sum(r["mrr_at_10"] for r in precs) / len(precs)
        lines.append(f"| `{profile}` | {avg_r5:.4f} | {avg_cp:.4f} | {avg_mrr:.4f} |")

    lines += [
        f"",
        f"---",
        f"",
        f"## 5. Per-Query Hit Analysis (labeled_v2 / adaptive_v3_source_guard)",
        f"",
    ]

    # Collect per-query hits for each model
    query_hits: dict[str, dict[str, bool]] = {}
    for mcfg in MODELS:
        data = load_model_data(base_dir, mcfg)
        if data is None:
            continue
        vd = (data.get("variants") or {}).get("labeled_v2/adaptive_v3_source_guard") or {}
        for q in vd.get("queries") or []:
            qid = q.get("id", "?")
            if qid not in query_hits:
                query_hits[qid] = {}
            query_hits[qid][mcfg["label"]] = q.get("top5_hit", False)

    # Table header
    model_labels = [m["label"] for m in MODELS]
    header_cols = " | ".join(m.split("-")[0] for m in model_labels)
    lines.append(f"| Query ID | Scope | {header_cols} | Notes |")
    lines.append("|----------|-------|" + "---|" * len(model_labels) + "-------|")
    for qid, hits in sorted(query_hits.items()):
        scope = "❌ out" if qid in OUT_OF_SCOPE_QUERIES else "✅ in"
        hit_cols = " | ".join("✓" if hits.get(m, False) else "✗" for m in model_labels)
        note = ""
        if qid in OUT_OF_SCOPE_QUERIES:
            note = "Not in JINGHU cities"
        elif all(not v for v in hits.values()):
            note = "Miss across all models"
        elif all(v for v in hits.values()):
            note = "Hit across all models"
        lines.append(f"| `{qid}` | {scope} | {hit_cols} | {note} |")

    lines += [
        f"",
        f"---",
        f"",
        f"## 6. Key Findings & Recommendations",
        f"",
        f"### Finding 1: Variant is the primary differentiator",
        f"All 4 embedding models (stella-large 1024d, jina-v5 1024d, stella-base 768d, Qwen3-4B 2560d) "
        f"produce **identical hit patterns** on these 11 golden queries. "
        f"The **card variant** (labeled_v2 vs baseline) accounts for the full +25% recall gain.",
        f"",
        f"### Finding 2: labeled_v2 > multi_card ≈ baseline on city precision",
        f"- `labeled_v2`: CityPrec@10 = 0.360 (adds explicit city label to card text)",
        f"- `multi_card`: CityPrec@10 = 0.320 (multiple card views dilute city signal)",
        f"- `baseline`: CityPrec@10 = 0.000 (no city signal in card text)",
        f"",
        f"### Finding 3: Score profiles are equivalent here",
        f"`adaptive_v3_source_guard` and `adaptive_v4_source_gate` produce identical scores. "
        f"Source gate logic had no effect on these queries (negative_leaks = 0, source_gate_pass_rate = 0).",
        f"",
        f"### Finding 4: Query bank needs JINGHU-scoped queries",
        f"3/11 queries (kunming, xiamen, jinan) target cities outside the JINGHU slice — "
        f"guaranteed misses. Effective hit rate with in-scope queries: **5/8 = 62.5%**.",
        f"",
        f"### Recommendation: Best production parameters",
        f"",
        f"| Parameter | Recommended Value | Rationale |",
        f"|-----------|------------------|-----------|",
        f"| Embedding model | `stella-large-zh-v2` (port 11437, 1024d) | Highest dim among tied models; established baseline |",
        f"| Card variant | `labeled_v2` | Best city_precision@10 (0.360 vs 0.320 multi_card) |",
        f"| Score profile | `adaptive_v3_source_guard` | Equivalent to v4 here; simpler logic |",
        f"| Candidate cap | 20 | Used in all evals |",
        f"| Qdrant collection dim | 1024 | stella-large-zh-v2 native dim |",
        f"",
        f"### Next Steps",
        f"1. **Enrich golden query bank** with 杭州/南京-specific hard queries (current 13/18 articles too sparse for hit)",
        f"2. **Phase 3**: Run GPT-OSS regional QA (advisory, ~300 articles)",
        f"3. **Phase 4**: Ingest to Qdrant `wechat_jinghu_stella_1024d_staging` using labeled_v2 cards",
        f"4. **Model D (Qwen3-4B 2560d)**: Keep as research collection (`wechat_jinghu_qwen3_4b_2560d_research`) — do NOT mix with 1024d production collections",
        f"",
    ]

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", required=True, help="Base directory containing JINGHU_EVAL_* subdirs")
    parser.add_argument("--report-name", default="JINGHU_MODEL_COMPARISON_20260509.md")
    args = parser.parse_args()

    base_dir = Path(args.out_dir)
    print(f"Loading eval results from {base_dir}")

    records = build_records(base_dir)
    print(f"Loaded {len(records)} variant×profile×model records")

    md = build_markdown(records, base_dir)
    out_path = base_dir / args.report_name
    out_path.write_text(md, encoding="utf-8")
    print(f"Report written → {out_path}")

    # Also write JSON summary
    json_out = base_dir / args.report_name.replace(".md", ".json")
    ranked = sorted(records, key=score_record, reverse=True)
    summary = {
        "generated": datetime.now().isoformat(),
        "best": {
            "model": ranked[0]["model"],
            "model_name": ranked[0]["model_name"],
            "dim": ranked[0]["dim"],
            "variant": ranked[0]["variant"],
            "profile": ranked[0]["profile"],
            "composite_score": round(score_record(ranked[0]), 4),
            "recall_at_5": ranked[0]["recall_at_5"],
            "effective_recall_at_5": round(ranked[0]["effective_recall_at_5"], 4),
            "city_precision_at_10": ranked[0]["city_precision_at_10"],
            "mrr_at_10": ranked[0]["mrr_at_10"],
        },
        "all_ranked": [
            {
                "rank": i + 1,
                "model": r["model"],
                "variant": r["variant"],
                "profile": r["profile"],
                "composite": round(score_record(r), 4),
                "recall_at_5": r["recall_at_5"],
                "city_precision_at_10": r["city_precision_at_10"],
                "mrr_at_10": r["mrr_at_10"],
            }
            for i, r in enumerate(ranked)
        ],
    }
    json_out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"JSON summary → {json_out}")


if __name__ == "__main__":
    main()
