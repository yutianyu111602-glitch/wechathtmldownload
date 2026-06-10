#!/usr/bin/env python3
"""Phase 5: Final quality report + cost accounting.

Aggregates all pipeline outputs into a single comprehensive report.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────
CROSS_DB_DIR = Path(
    r"C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports"
    r"\cross_db_identity_resolution_20260608"
)
INVENTORY_PATH = (
    Path(r"C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports")
    / "cross_db_entity_inventory_20260608"
    / "cross_db_eid_inventory.json"
)
DECISIONS_PATH = CROSS_DB_DIR / "cross_db_identity_decisions.jsonl"
MERGE_MAP_PATH = CROSS_DB_DIR / "cross_db_merge_map.json"
YUANBAO_PATH = CROSS_DB_DIR / "yuanbao_entity_search_results.json"
REPORT_PATH = CROSS_DB_DIR / "cross_db_final_report.json"


def main():
    print("=" * 60)
    print("Phase 5: Final Quality Report + Cost Accounting")
    print("=" * 60)

    report = {"generated_at": __import__("datetime").datetime.now().isoformat()}

    # ── Inventory stats ─────────────────────────────────────
    if INVENTORY_PATH.exists():
        inv = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
        stats = inv.get("stats", {})
        report["inventory"] = {
            "db3_entities": stats.get("db3_entity_count", 0),
            "db2_eid_groups": stats.get("db2_eid_count", 0),
            "exact_single_match": stats.get("exact_single", 0),
            "exact_multi_match": stats.get("exact_multi", 0),
            "fuzzy_match": stats.get("fuzzy_matches", 0),
            "no_match": stats.get("no_matches", 0),
        }

    # ── LLM decisions ───────────────────────────────────────
    if DECISIONS_PATH.exists():
        decisions = []
        with open(DECISIONS_PATH, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    decisions.append(json.loads(line))

        counts = Counter(d.get("decision") for d in decisions)
        total_tokens = sum(
            d.get("usage", {}).get("total_tokens", 0) for d in decisions
        )
        prompt_tokens = sum(
            d.get("usage", {}).get("prompt_tokens", 0) for d in decisions
        )
        completion_tokens = sum(
            d.get("usage", {}).get("completion_tokens", 0) for d in decisions
        )
        total_latency = sum(d.get("latency_ms", 0) for d in decisions)

        # Cost: $0.14/M input, $0.28/M output (DeepSeek Flash)
        input_cost = prompt_tokens * 0.14 / 1_000_000
        output_cost = completion_tokens * 0.28 / 1_000_000
        total_cost = input_cost + output_cost

        conf_high = sum(1 for d in decisions if d.get("confidence", 0) >= 0.9)
        conf_med = sum(
            1
            for d in decisions
            if 0.7 <= d.get("confidence", 0) < 0.9 and d.get("decision") == "match"
        )
        conf_low = sum(
            1
            for d in decisions
            if d.get("confidence", 0) < 0.7 and d.get("decision") == "match"
        )

        report["llm_resolution"] = {
            "model": "deepseek-v4-flash",
            "total_candidates": len(decisions),
            "decisions": dict(counts),
            "match_rate": f"{counts.get('match',0)/len(decisions)*100:.1f}%",
            "confidence_high": conf_high,
            "confidence_medium": conf_med,
            "confidence_low": conf_low,
            "total_tokens": total_tokens,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "avg_latency_ms": round(total_latency / max(len(decisions), 1)),
            "cost": {
                "input_cost_usd": round(input_cost, 4),
                "output_cost_usd": round(output_cost, 4),
                "total_cost_usd": round(total_cost, 2),
            },
        }

    # ── Merge map ───────────────────────────────────────────
    if MERGE_MAP_PATH.exists():
        mm = json.loads(MERGE_MAP_PATH.read_text(encoding="utf-8"))
        mm_stats = mm.get("stats", {})
        report["merge_map"] = {
            "db2_to_db3_mappings": mm_stats.get("db2_eids_mapped", 0),
            "existing_remaps": mm_stats.get("existing_remaps", 0),
            "total_unified_remaps": mm_stats.get("db2_eids_mapped", 0)
            + mm_stats.get("existing_remaps", 0),
            "confidence_breakdown": mm_stats.get("confidence_breakdown", {}),
        }

    # ── Yuanbao ─────────────────────────────────────────────
    if YUANBAO_PATH.exists():
        yb = json.loads(YUANBAO_PATH.read_text(encoding="utf-8"))
        report["yuanbao"] = {
            "total_unmatched": yb.get("total_unmatched", 0),
            "searched": yb.get("searched", 0),
            "results_count": len(yb.get("results", [])),
        }

    # ── Grand total ─────────────────────────────────────────
    report["grand_summary"] = {
        "total_db3_entities": report.get("inventory", {}).get("db3_entities", 0),
        "total_db2_entities": report.get("inventory", {}).get("db2_eid_groups", 0),
        "exact_matches_auto": report.get("inventory", {}).get("exact_single_match", 0),
        "llm_matches": counts.get("match", 0),
        "total_linked": report.get("inventory", {}).get("exact_single_match", 0)
        + counts.get("match", 0),
        "still_unmatched": report.get("inventory", {}).get("no_match", 0)
        - counts.get("match", 0),
        "total_pipeline_cost_usd": round(
            report.get("llm_resolution", {}).get("cost", {}).get("total_cost_usd", 0),
            2,
        ),
        "approach": "query-time merge_map (零 SQL UPDATE, 完全可逆)",
    }

    # ── Save ────────────────────────────────────────────────
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # ── Print summary ───────────────────────────────────────
    gs = report["grand_summary"]
    lr = report.get("llm_resolution", {})
    mm = report.get("merge_map", {})
    cost = lr.get("cost", {})

    print(f"\n{'='*60}")
    print(f"🏆 三库归一最终报告")
    print(f"{'='*60}")
    print(f"")
    print(f"📊 实体规模:")
    print(f"   DB3 服务库:    {gs['total_db3_entities']:,} 实体")
    print(f"   DB2 证据库:    {gs['total_db2_entities']:,} eid 组")
    print(f"")
    print(f"🔗 匹配成果:")
    print(f"   精确自动匹配:  {gs['exact_matches_auto']:,}")
    print(f"   LLM 裁决匹配:  {gs['llm_matches']:,}")
    print(f"   ─────────────────────")
    print(f"   总计已链接:    {gs['total_linked']:,}")
    print(f"   尚未匹配:      {gs['still_unmatched']:,}")
    print(f"   链接率:        {gs['total_linked']/gs['total_db2_entities']*100:.1f}%")
    print(f"")
    print(f"🤖 LLM 裁决质量:")
    print(f"   模型:          {lr.get('model', '?')}")
    print(f"   高置信度(≥0.9): {lr.get('confidence_high', 0):,}")
    print(f"   中置信度:      {lr.get('confidence_medium', 0):,}")
    print(f"   平均延迟:      {lr.get('avg_latency_ms', 0):.0f}ms")
    print(f"   错误率:        {lr.get('decisions',{}).get('error',0)/max(lr.get('total_candidates',1),1)*100:.1f}%")
    print(f"")
    print(f"💰 花费核算:")
    print(f"   模型:          DeepSeek v4-flash ($0.14/M in, $0.28/M out)")
    print(f"   输入 tokens:   {lr.get('prompt_tokens', 0):,}")
    print(f"   输出 tokens:   {lr.get('completion_tokens', 0):,}")
    print(f"   总花费:        ${cost.get('total_cost_usd', 0):.2f}")
    print(f"")
    print(f"🗺️  合并映射:")
    print(f"   DB2→DB3:       {mm.get('db2_to_db3_mappings', 0):,}")
    print(f"   已有 remap:    {mm.get('existing_remaps', 0):,}")
    print(f"   统一映射总数:  {mm.get('total_unified_remaps', 0):,}")
    print(f"")
    print(f"🛡️  设计原则:")
    print(f"   ✅ query-time merge_map（零 SQL UPDATE, 完全可逆）")
    print(f"   ✅ v4-flash 够用 ($0.14/M vs v4-pro $1.10/M)")
    print(f"   ✅ concurrency 6 (稳定优先)")
    print(f"   ✅ 不写 2.1GB 服务库")

    print(f"\n📄 完整报告: {REPORT_PATH}")


if __name__ == "__main__":
    main()
