#!/usr/bin/env python3
"""LLM-powered identity adjudication for atlas external identity edges.

Replaces the manual workbench step with dual-pass DeepSeek cross-validation.
Reads adjudication review rows, constructs LLM prompts from evidence, runs
two independent passes (forward + adversarial), and outputs accepted edges
only when both passes agree at confidence >= threshold.

Safety: report-only by default. Requires --enable-write to produce non-empty
accepted_external_identity_edges_for_graph.jsonl.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import tempfile
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SCHEMA_VERSION = "stage7_atlas_llm_adjudication.v1"
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_CONFIDENCE_THRESHOLD = 0.8
DEFAULT_MAX_ROWS = 50
DEFAULT_TEMPERATURE = 0.0

# Buckets eligible for LLM adjudication (have profile content)
LLM_ELIGIBLE_BUCKETS = {
    "opencli_profile_content_subject_match_needs_manual_acceptance",
    "opencli_profile_content_needs_subject_match",
    "strong_url_profile_candidate_needs_content_extract",
}

# Buckets explicitly excluded (Missing content / Maigret-only / cap'd)
LLM_EXCLUDED_BUCKETS = {
    "medium_url_profile_candidate_needs_content_extract",
    "reachable_music_profile_needs_subject_match",
    "maigret_candidate_only_needs_source_backed_review",
    "context_missing_subject",
    "weak_or_unclassified_identity_evidence",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def first_text(value: Any) -> str:
    return str(value or "").strip()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            value = json.loads(stripped)
            if isinstance(value, dict):
                rows.append(value)
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def index_opencli_evidence(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Index by source_row_id for fast lookup."""
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        rid = first_text(row.get("source_row_id"))
        if rid and rid not in result:
            result[rid] = row
    return result


def index_http_fast(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        seed_id = first_text(row.get("seed_id"))
        if seed_id and seed_id not in result:
            result[seed_id] = row
    return result


# ---------------------------------------------------------------------------
# LLM Client (DeepSeek API)
# ---------------------------------------------------------------------------

def call_deepseek(
    *,
    system_prompt: str,
    user_prompt: str,
    model: str,
    api_key: str,
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int = 512,
    timeout_sec: int = 60,
) -> dict[str, Any]:
    """Call DeepSeek Chat API and return parsed JSON response."""
    import urllib.request
    import urllib.error

    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.deepseek.com/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )

    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return {
            "error": f"HTTP {exc.code}",
            "body": exc.read().decode("utf-8", errors="replace")[:500],
            "latency_ms": (time.monotonic() - start) * 1000,
        }
    except Exception as exc:
        return {
            "error": str(exc)[:200],
            "latency_ms": (time.monotonic() - start) * 1000,
        }

    latency_ms = (time.monotonic() - start) * 1000

    choice = (body.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    raw_content = first_text(message.get("content"))

    # Parse JSON from response
    try:
        parsed = json.loads(raw_content)
    except json.JSONDecodeError:
        parsed = {"raw": raw_content, "parse_error": True}

    return {
        "parsed": parsed if isinstance(parsed, dict) else {"raw": raw_content},
        "finish_reason": choice.get("finish_reason"),
        "model": body.get("model", model),
        "usage": body.get("usage", {}),
        "latency_ms": latency_ms,
    }


# ---------------------------------------------------------------------------
# Prompt Construction
# ---------------------------------------------------------------------------

FORWARD_SYSTEM = """你是中国地下电子音乐知识图谱的身份裁决专家。
你的任务：判断一个外部社交资料（Instagram/SoundCloud/Bandcamp等）是否与文章中提到的实体是同一个人/组织。

裁决标准（严格按序判断）：
1. display_name 与 subject_name 完全一致或仅大小写/空格差异 → accepted, confidence≥0.9
2. display_name 包含 subject_name 或反之（如 "Smoke Machine" vs "SMOKE MACHINE"）→ accepted, confidence≥0.85
3. handle 含 subject_name 且 platform 是音乐平台 → accepted, confidence≥0.8
4. 名字高度相关但有关键差异（如 "Jogja Noise Club" vs "Jogja Noise Bombing"）→ needs_more_source
5. 名字不匹配或证据不足以判断 → rejected

电子音乐场景常见变体：Herrensauna→𝕳𝖊𝖗𝖗𝖊𝖓𝖘𝖆𝖚𝖓𝖆 (特殊字体), 中文名/拼音, 缩写。

输出必须是严格 JSON（不要有其他文字）：
{"decision":"accepted|rejected|needs_more_source","confidence":0.0,"name_match_type":"exact|fuzzy|partial|none","evidence_strength":"strong|moderate|weak","reasoning":"≤150字中文"}"""

ADVERSARIAL_SYSTEM = """你是中国地下电子音乐知识图谱的严格审查员。
你的任务是严格审查身份匹配，找出任何可能不一致或同名不同实体的风险。

请质疑以下匹配（从怀疑角度出发）：
1. 名字是否有拼写、语言、字体的实际差异（非仅大小写）？
2. display_name 和 handle 是否可能是不同实体（如品牌 vs 个人、官方号 vs 粉丝号）？
3. bio 内容是否与电子音乐实体类型（DJ/厂牌/场地/活动）一致？
4. 是否存在同名不同实体的合理怀疑？

若找不到任何实质疑点 → accepted。有任何合理怀疑 → rejected。

输出必须是严格 JSON（不要有其他文字）：
{"decision":"accepted|rejected|needs_more_source","confidence":0.0,"name_match_type":"exact|fuzzy|partial|none","evidence_strength":"strong|moderate|weak","concerns":["疑点1","疑点2"],"reasoning":"≤150字中文"}"""


def build_context_from_adjudication_row(adj_row: dict[str, Any]) -> dict[str, Any]:
    ctx = adj_row.get("context") or {}
    return {
        "subject_name": first_text(ctx.get("subject_name")),
        "source_title": first_text(ctx.get("source_title")),
        "subject_type": first_text(ctx.get("subject_type")),
        "source_article_uid": first_text(ctx.get("source_article_uid")),
        "source_account": first_text(ctx.get("source_account")),
    }


def build_forward_prompt(adj_row: dict[str, Any], evidence: dict[str, Any] | None) -> str:
    ctx = build_context_from_adjudication_row(adj_row)
    if evidence:
        display = first_text(evidence.get("profile_display_name"))
        handle = first_text(evidence.get("profile_handle"))
        bio = first_text(evidence.get("bio_excerpt"))
        platform = first_text(evidence.get("platform"))
        url = first_text(evidence.get("evidence_url") or evidence.get("final_url"))
    else:
        display = first_text(adj_row.get("site_name") or adj_row.get("username"))
        handle = first_text(adj_row.get("username"))
        bio = ""
        platform = first_text(adj_row.get("platform"))
        url = first_text(adj_row.get("url") or adj_row.get("final_url"))

    return "\n".join([
        "请判断以下外部资料是否属于同一实体：",
        "",
        f"文章提及的实体名: {ctx['subject_name']}",
        f"实体类型: {ctx['subject_type'] or '未知'}",
        f"文章来源: {ctx['source_title'][:120]}",
        "",
        "外部资料:",
        f"- 平台: {platform}",
        f"- URL: {url}",
        f"- 显示名: {display}",
        f"- 用户名: {handle}",
        f"- 简介: {bio[:200]}",
    ])


def build_adversarial_prompt(adj_row: dict[str, Any], evidence: dict[str, Any] | None) -> str:
    # Same input, different system prompt
    return build_forward_prompt(adj_row, evidence)


# ---------------------------------------------------------------------------
# Core Adjudication
# ---------------------------------------------------------------------------

def adjudicate_one(
    *,
    adj_row: dict[str, Any],
    evidence: dict[str, Any] | None,
    model: str,
    api_key: str,
    confidence_threshold: float,
    call_log: list[dict[str, Any]],
) -> dict[str, Any]:
    """Run dual-pass LLM adjudication on a single row."""

    bucket = first_text(adj_row.get("adjudication_bucket"))

    # Fast-path: ineligible buckets
    if bucket not in LLM_ELIGIBLE_BUCKETS:
        return {
            "row_index": adj_row.get("row_index"),
            "subject_name": (adj_row.get("context") or {}).get("subject_name", ""),
            "bucket": bucket,
            "llm_eligible": False,
            "llm_decision": "skipped",
            "llm_confidence": 0.0,
            "accepted_for_graph": False,
            "skip_reason": f"bucket '{bucket}' not in LLM_ELIGIBLE_BUCKETS",
        }

    fwd_prompt = build_forward_prompt(adj_row, evidence)
    adv_prompt = build_adversarial_prompt(adj_row, evidence)

    # Pass 1 — Forward
    fwd_result = call_deepseek(
        system_prompt=FORWARD_SYSTEM,
        user_prompt=fwd_prompt,
        model=model,
        api_key=api_key,
    )

    # Pass 2 — Adversarial
    adv_result = call_deepseek(
        system_prompt=ADVERSARIAL_SYSTEM,
        user_prompt=adv_prompt,
        model=model,
        api_key=api_key,
    )

    fwd_parsed = fwd_result.get("parsed", {})
    adv_parsed = adv_result.get("parsed", {})

    fwd_decision = first_text(fwd_parsed.get("decision", "")).lower()
    adv_decision = first_text(adv_parsed.get("decision", "")).lower()
    fwd_confidence = float(fwd_parsed.get("confidence") or 0)
    adv_confidence = float(adv_parsed.get("confidence") or 0)

    # Cross-validation gate
    both_accepted = fwd_decision == "accepted" and adv_decision == "accepted"
    confidence_ok = fwd_confidence >= confidence_threshold and adv_confidence >= confidence_threshold

    accepted = both_accepted and confidence_ok

    row_result = {
        "row_index": adj_row.get("row_index"),
        "subject_name": (adj_row.get("context") or {}).get("subject_name", ""),
        "source_family": first_text(adj_row.get("source_family")),
        "bucket": bucket,
        "platform": first_text(adj_row.get("platform")),
        "url": first_text(adj_row.get("url") or adj_row.get("final_url")),
        "llm_eligible": True,
        "pass1_decision": fwd_decision,
        "pass1_confidence": fwd_confidence,
        "pass1_reasoning": first_text(fwd_parsed.get("reasoning")),
        "pass1_name_match": first_text(fwd_parsed.get("name_match_type")),
        "pass2_decision": adv_decision,
        "pass2_confidence": adv_confidence,
        "pass2_reasoning": first_text(adv_parsed.get("reasoning")),
        "pass2_concerns": adv_parsed.get("concerns") if isinstance(adv_parsed.get("concerns"), list) else [],
        "llm_decision": "accepted" if accepted else ("rejected" if not both_accepted else "needs_more_source"),
        "llm_confidence": min(fwd_confidence, adv_confidence),
        "accepted_for_graph": accepted,
        "cross_validation_passed": both_accepted,
        "confidence_threshold_met": confidence_ok,
    }

    # Log both calls
    call_log.append({
        "row_index": adj_row.get("row_index"),
        "subject_name": row_result["subject_name"],
        "pass": "forward",
        "prompt": fwd_prompt,
        "system": FORWARD_SYSTEM[:200],
        "result": fwd_result,
        "timestamp": now_iso(),
    })
    call_log.append({
        "row_index": adj_row.get("row_index"),
        "subject_name": row_result["subject_name"],
        "pass": "adversarial",
        "prompt": adv_prompt,
        "system": ADVERSARIAL_SYSTEM[:200],
        "result": adv_result,
        "timestamp": now_iso(),
    })

    return row_result


def build_edge(row_result: dict[str, Any], adj_row: dict[str, Any]) -> dict[str, Any]:
    """Build accepted_external_identity_edges_for_graph entry."""
    ctx = adj_row.get("context") or {}
    return {
        "schema_version": "stage7_external_identity_edge.v1.llm",
        "subject_name": first_text(ctx.get("subject_name")),
        "subject_type": first_text(ctx.get("subject_type")),
        "source_article_uid": first_text(ctx.get("source_article_uid")),
        "source_title": first_text(ctx.get("source_title")),
        "platform": row_result["platform"],
        "url": row_result["url"],
        "predicate": "HAS_PROFILE",
        "evidence_tool": row_result.get("source_family", "llm_adjudication"),
        "llm_decision": row_result["llm_decision"],
        "llm_confidence": row_result["llm_confidence"],
        "adjudicated_at": now_iso(),
        "adjudicator": "llm_deepseek_dual_pass",
        "model": f"deepseek-chat (dual-pass cross-validation, threshold={DEFAULT_CONFIDENCE_THRESHOLD})",
    }


# ---------------------------------------------------------------------------
# Spot-check
# ---------------------------------------------------------------------------

def spot_check_rows(results: list[dict[str, Any]], count: int, seed: int = 42) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    eligible = [r for r in results if r.get("llm_eligible")]
    if len(eligible) <= count:
        return eligible
    return rng.sample(eligible, count)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adjudication-dir", type=Path, required=True,
                        help="Path to rule-engine adjudication output directory")
    parser.add_argument("--opencli-evidence", type=Path, default=None,
                        help="Path to opencli_social_profile_evidence.jsonl")
    parser.add_argument("--http-fast-dir", type=Path, default=None,
                        help="Path to HTTP fast results directory")
    parser.add_argument("--seed-queue", type=Path, default=None,
                        help="Path to external_evidence_seed_queue.jsonl")
    parser.add_argument("--out-dir", type=Path, required=True,
                        help="Output directory for LLM adjudication results")
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL)
    parser.add_argument("--api-key", type=str, default="",
                        help="DeepSeek API key, or 'env:VAR_NAME' to read from env")
    parser.add_argument("--confidence-threshold", type=float, default=DEFAULT_CONFIDENCE_THRESHOLD)
    parser.add_argument("--max-rows", type=int, default=DEFAULT_MAX_ROWS)
    parser.add_argument("--spot-check", type=int, default=0,
                        help="Randomly select N rows for spot-check summary")
    parser.add_argument("--enable-write", action="store_true",
                        help="Actually write accepted edges (default: report-only)")
    parser.add_argument("--report-only-exit-zero", action="store_true",
                        help="Exit 0 even if accepted_for_graph=0")
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    # Resolve API key
    api_key = args.api_key
    if api_key.startswith("env:"):
        api_key = os.environ.get(api_key[4:].strip(), "")
    if not api_key:
        print(json.dumps({"ok": False, "error": "No API key provided. Use --api-key or env:VAR_NAME"}, ensure_ascii=False))
        return 3

    # Read inputs
    review_path = args.adjudication_dir / "external_identity_adjudication_review.jsonl"
    adj_rows = read_jsonl(review_path)
    if not adj_rows:
        print(json.dumps({"ok": False, "error": f"No review rows found at {review_path}"}, ensure_ascii=False))
        return 2

    evidence_index: dict[str, dict[str, Any]] = {}
    if args.opencli_evidence and args.opencli_evidence.exists():
        evidence_index = index_opencli_evidence(read_jsonl(args.opencli_evidence))

    # Limit rows
    rows_to_adjudicate = adj_rows[:args.max_rows]
    call_log: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []

    for i, adj_row in enumerate(rows_to_adjudicate):
        source_family = first_text(adj_row.get("source_family"))
        # Try to match evidence by source_row_id (OpenCLI) or seed_id (HTTP fast)
        evidence: dict[str, Any] | None = None
        if source_family == "opencli_profile_metadata":
            # The adjudication row may not have source_row_id directly; try from context
            # OpenCLI evidence is indexed by source_row_id; we match by URL or subject
            adj_url = first_text(adj_row.get("url") or adj_row.get("final_url"))
            adj_subject = first_text((adj_row.get("context") or {}).get("subject_name"))
            for _rid, ev in evidence_index.items():
                ev_url = first_text(ev.get("evidence_url") or ev.get("final_url"))
                ev_subject = first_text(ev.get("subject_name"))
                if ev_url and adj_url and ev_url.strip("/") == adj_url.strip("/"):
                    evidence = ev
                    break
                if ev_subject and adj_subject and ev_subject == adj_subject:
                    evidence = ev
                    break

        result = adjudicate_one(
            adj_row=adj_row,
            evidence=evidence,
            model=args.model,
            api_key=api_key,
            confidence_threshold=args.confidence_threshold,
            call_log=call_log,
        )
        results.append(result)

        # Progress
        accepted_count = sum(1 for r in results if r.get("accepted_for_graph"))
        print(f"[{i+1}/{len(rows_to_adjudicate)}] {result['subject_name'][:30]:30s} "
              f"bucket={result.get('bucket',''):50s} "
              f"llm={result.get('llm_decision'):15s} "
              f"accepted={result.get('accepted_for_graph')}")

    # Build accepted edges
    accepted_results = [r for r in results if r.get("accepted_for_graph")]
    accepted_edges = []
    for r in accepted_results:
        adj_row = rows_to_adjudicate[r["row_index"] - 1] if r["row_index"] else {}
        accepted_edges.append(build_edge(r, adj_row))

    # Spot-check
    spot_checks: list[dict[str, Any]] = []
    if args.spot_check > 0:
        spot_checks = spot_check_rows(results, args.spot_check)

    # Write outputs
    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    write_jsonl(out_dir / "llm_adjudication_review.jsonl", results)
    write_jsonl(out_dir / "llm_call_log.jsonl", call_log)

    if args.enable_write and accepted_edges:
        write_jsonl(out_dir / "accepted_external_identity_edges_for_graph.jsonl", accepted_edges)
    else:
        # Empty file (report-only)
        write_jsonl(out_dir / "accepted_external_identity_edges_for_graph.jsonl", [])

    # Summary
    decision_counts = Counter(r["llm_decision"] for r in results)
    bucket_counts = Counter(r["bucket"] for r in results)
    total_tokens = sum(
        (c.get("result", {}).get("usage", {}).get("total_tokens") or 0)
        for c in call_log
    )

    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": True,
        "decision": f"llm_adjudication_complete_accepted_{len(accepted_edges)}",
        "model": args.model,
        "confidence_threshold": args.confidence_threshold,
        "dual_pass_cross_validation": True,
        "input_rows": len(adj_rows),
        "adjudicated_rows": len(results),
        "eligible_rows": sum(1 for r in results if r.get("llm_eligible")),
        "accepted_for_graph": len(accepted_edges),
        "rejected": decision_counts.get("rejected", 0),
        "needs_more_source": decision_counts.get("needs_more_source", 0),
        "skipped": decision_counts.get("skipped", 0),
        "cross_validation_passed": sum(1 for r in results if r.get("cross_validation_passed")),
        "total_llm_calls": len(call_log),
        "total_tokens": total_tokens,
        "bucket_counts": dict(bucket_counts),
        "spot_check_rows": len(spot_checks),
        "write_enabled": args.enable_write and len(accepted_edges) > 0,
        "accepted_edge_path": str(out_dir / "accepted_external_identity_edges_for_graph.jsonl"),
        "review_path": str(out_dir / "llm_adjudication_review.jsonl"),
        "call_log_path": str(out_dir / "llm_call_log.jsonl"),
        "safety": {
            "model_call_executed": True,
            "network_call_executed": True,  # DeepSeek API
            "graph_write_executed": False,
            "qdrant_write_executed": False,
            "sqlite_write_executed": False,
            "mem0_write_executed": False,
            "paid_api_used": True,
            "cookie_or_token_exported": False,
            "d_scan_executed": False,
            "report_only": not args.enable_write,
        },
    }

    write_json(out_dir / "llm_adjudication_summary.json", summary)
    write_markdown(out_dir / "llm_adjudication_summary.md", summary, accepted_results)

    print(json.dumps({
        "ok": summary["ok"],
        "decision": summary["decision"],
        "adjudicated_rows": summary["adjudicated_rows"],
        "eligible_rows": summary["eligible_rows"],
        "accepted_for_graph": summary["accepted_for_graph"],
        "total_tokens": summary["total_tokens"],
        "summary": str(out_dir / "llm_adjudication_summary.json"),
    }, ensure_ascii=False, indent=2))

    return 0


def write_markdown(path: Path, summary: dict[str, Any], accepted_results: list[dict[str, Any]]) -> None:
    lines = [
        "# Atlas LLM Identity Adjudication",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- model: `{summary['model']}`",
        f"- confidence_threshold: `{summary['confidence_threshold']}`",
        f"- dual_pass_cross_validation: `{summary['dual_pass_cross_validation']}`",
        f"- input_rows: `{summary['input_rows']}`",
        f"- eligible_rows: `{summary['eligible_rows']}`",
        f"- **accepted_for_graph**: `{summary['accepted_for_graph']}`",
        f"- rejected: `{summary['rejected']}`",
        f"- needs_more_source: `{summary['needs_more_source']}`",
        f"- skipped: `{summary['skipped']}`",
        f"- total_llm_calls: `{summary['total_llm_calls']}`",
        f"- total_tokens: `{summary['total_tokens']}`",
        f"- write_enabled: `{summary['write_enabled']}`",
        "",
    ]

    if accepted_results:
        lines.extend([
            "## Accepted Edges",
            "",
            "| # | Subject | Platform | LLM Confidence |",
            "|---:|---------|----------|---------------:|",
        ])
        for i, r in enumerate(accepted_results, 1):
            lines.append(f"| {i} | {r.get('subject_name', '')} | {r.get('platform', '')} | {r.get('llm_confidence', 0):.2f} |")

    lines.extend([
        "",
        "## Safety",
        "",
        "- Dual-pass cross-validation: forward + adversarial prompts",
        "- Maigret-only rows excluded from LLM adjudication",
        "- No graph/vector/DB/mem0 writes",
        "- Report-only unless --enable-write passed",
    ])

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
