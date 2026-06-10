"""Apply deterministic retrieval serving policy to a reranker canary report.

This reads local JSON artifacts only. It does not load models and does not
write Qdrant, Neo4j, production SQLite, graph, mem0, OCR/Dajiala, or D: data.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_INPUT = Path("reports/reranker_canary_qwen3_4b_20260514_v2/reranker_canary.json")
DEFAULT_OUT_DIR = Path("reports/retrieval_policy_canary_20260514")
DEFAULT_TYPE_TARGETS = "event=4,entity=4,article=2"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def normalize(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().casefold())


def hit_label(hit: dict[str, Any]) -> str:
    return str(hit.get("title") or hit.get("name") or hit.get("text") or "")[:160]


def hit_signature(hit: dict[str, Any]) -> tuple[str, str]:
    return normalize(hit.get("type")), normalize(hit_label(hit))


def parse_type_targets(value: str) -> dict[str, int]:
    targets: dict[str, int] = {}
    if not value:
        return targets
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise ValueError(f"invalid type target: {part}")
        key, raw_count = part.split("=", 1)
        count = int(raw_count)
        if count < 0:
            raise ValueError(f"negative target for {key}: {count}")
        targets[normalize(key)] = count
    return targets


def can_select(
    hit: dict[str, Any],
    selected: list[dict[str, Any]],
    signature_counts: Counter[tuple[str, str]],
    article_counts: Counter[str],
    *,
    max_per_signature: int,
    max_per_article: int,
) -> bool:
    signature = hit_signature(hit)
    if max_per_signature >= 0 and signature_counts[signature] >= max_per_signature:
        return False
    article_uid = str(hit.get("article_uid") or "")
    if article_uid and max_per_article >= 0 and article_counts[article_uid] >= max_per_article:
        return False
    return hit not in selected


def add_hit(
    hit: dict[str, Any],
    selected: list[dict[str, Any]],
    signature_counts: Counter[tuple[str, str]],
    article_counts: Counter[str],
) -> None:
    row = dict(hit)
    row["policy_rank"] = len(selected) + 1
    selected.append(row)
    signature_counts[hit_signature(hit)] += 1
    article_uid = str(hit.get("article_uid") or "")
    if article_uid:
        article_counts[article_uid] += 1


def apply_policy(
    hits: list[dict[str, Any]],
    *,
    limit: int,
    max_per_signature: int,
    max_per_article: int,
    type_targets: dict[str, int],
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    signature_counts: Counter[tuple[str, str]] = Counter()
    article_counts: Counter[str] = Counter()

    for kind, target in type_targets.items():
        for hit in hits:
            if len(selected) >= limit or sum(1 for row in selected if normalize(row.get("type")) == kind) >= target:
                break
            if normalize(hit.get("type")) != kind:
                continue
            if can_select(
                hit,
                selected,
                signature_counts,
                article_counts,
                max_per_signature=max_per_signature,
                max_per_article=max_per_article,
            ):
                add_hit(hit, selected, signature_counts, article_counts)

    for hit in hits:
        if len(selected) >= limit:
            break
        if can_select(
            hit,
            selected,
            signature_counts,
            article_counts,
            max_per_signature=max_per_signature,
            max_per_article=max_per_article,
        ):
            add_hit(hit, selected, signature_counts, article_counts)

    return selected


def first_expected_signature_policy_rank(hits: list[dict[str, Any]], expected_signature_rank: int | None) -> int | None:
    if expected_signature_rank is None:
        return None
    # The reranker canary stores only ranks, not the original expected signature.
    # Treat any previously signature-matching hit that survives policy selection as
    # a pass if its original rerank rank is at or before the known signature rank.
    for hit in hits:
        if int(hit.get("rerank_rank") or 10**9) <= expected_signature_rank:
            return int(hit["policy_rank"])
    return None


def summarize_kind_counts(hits: list[dict[str, Any]]) -> dict[str, int]:
    return dict(Counter(str(hit.get("type") or "unknown") for hit in hits))


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Retrieval Policy Canary",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- source: `{report['source_report']}`",
        f"- query_count: `{report['query_count']}`",
        f"- limit: `{report['limit']}`",
        f"- max_per_signature: `{report['max_per_signature']}`",
        f"- max_per_article: `{report['max_per_article']}`",
        f"- type_targets: `{report['type_targets']}`",
        f"- avg_unique_signature_before_top10: `{report['avg_unique_signature_before_top10']}`",
        f"- avg_unique_signature_policy_top10: `{report['avg_unique_signature_policy_top10']}`",
        f"- self_signature_policy_top5_rate: `{report['self_signature_policy_top5_rate']}`",
        "",
        "## Query Policy Results",
        "",
    ]
    for query in report["queries"]:
        lines.append(f"### {query['id']}: {query['query']}")
        lines.append(f"- source: `{query.get('source')}`")
        lines.append(f"- before_kind_counts: `{query['before_kind_counts']}`")
        lines.append(f"- policy_kind_counts: `{query['policy_kind_counts']}`")
        lines.append(f"- expected_signature_policy_rank: `{query.get('expected_signature_policy_rank')}`")
        lines.append("")
        lines.append("| policy_rank | score | original_rank | kind | label |")
        lines.append("|---:|---:|---:|---|---|")
        for hit in query["policy_hits"]:
            label = hit_label(hit).replace("|", "/")
            lines.append(
                f"| {hit['policy_rank']} | {hit.get('rerank_score')} | {hit.get('rerank_rank')} | "
                f"{hit.get('type', '')} | {label} |"
            )
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    source = read_json(args.input)
    type_targets = parse_type_targets(args.type_targets)
    query_reports: list[dict[str, Any]] = []
    unique_before_total = 0
    unique_policy_total = 0
    self_total = 0
    self_policy_top5 = 0

    for query in source.get("queries", []):
        hits = list(query.get("reranked_hits_all") or query.get("reranked_hits") or [])
        policy_hits = apply_policy(
            hits,
            limit=args.limit,
            max_per_signature=args.max_per_signature,
            max_per_article=args.max_per_article,
            type_targets=type_targets,
        )
        before_signatures = {hit_signature(hit) for hit in hits[: args.limit]}
        policy_signatures = {hit_signature(hit) for hit in policy_hits}
        expected_policy_rank = first_expected_signature_policy_rank(policy_hits, query.get("expected_signature_rank"))
        if query.get("source") == "self_alignment":
            self_total += 1
            if expected_policy_rank is not None and expected_policy_rank <= 5:
                self_policy_top5 += 1
        unique_before_total += len(before_signatures)
        unique_policy_total += len(policy_signatures)
        query_reports.append(
            {
                "id": query.get("id"),
                "query": query.get("query"),
                "source": query.get("source"),
                "expected_signature_rank": query.get("expected_signature_rank"),
                "expected_signature_policy_rank": expected_policy_rank,
                "before_kind_counts": summarize_kind_counts(hits[: args.limit]),
                "policy_kind_counts": summarize_kind_counts(policy_hits),
                "unique_signature_before_top10": len(before_signatures),
                "unique_signature_policy_top10": len(policy_signatures),
                "policy_hits": policy_hits,
            }
        )

    report = {
        "schema_version": "stage7_retrieval_policy_canary.v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "execution_host_policy": "local report-only; no model load, DB writes, graph writes, paid API calls, or D: scans",
        "source_report": str(args.input),
        "query_count": len(query_reports),
        "limit": args.limit,
        "max_per_signature": args.max_per_signature,
        "max_per_article": args.max_per_article,
        "type_targets": type_targets,
        "avg_unique_signature_before_top10": round(unique_before_total / max(len(query_reports), 1), 3),
        "avg_unique_signature_policy_top10": round(unique_policy_total / max(len(query_reports), 1), 3),
        "self_signature_policy_top5_rate": round(self_policy_top5 / max(self_total, 1), 4),
        "queries": query_reports,
    }
    write_json(args.out_dir / "retrieval_policy_report.json", report)
    write_markdown(args.out_dir / "retrieval_policy_report.md", report)
    print(json.dumps({"ok": True, "json": str(args.out_dir / "retrieval_policy_report.json"), "markdown": str(args.out_dir / "retrieval_policy_report.md")}, ensure_ascii=False, indent=2))
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--max-per-signature", type=int, default=1)
    parser.add_argument("--max-per-article", type=int, default=2)
    parser.add_argument("--type-targets", default=DEFAULT_TYPE_TARGETS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.input.exists():
        raise SystemExit(f"input not found: {args.input}")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
