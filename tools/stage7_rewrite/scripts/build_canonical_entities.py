#!/usr/bin/env python3
"""Build a report-only canonical entity resolution canary for PRD-14.

The canary reads local Stage7 consumer release-pack entities, builds exact
same-name canonical groups, emits fuzzy/alias review candidates, and writes
reports only. It does not write Neo4j, Qdrant, mem0, SQLite, or production
state.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable


DEFAULT_ENTITIES_JSONL = Path("reports/consumer_release_pack_full_unknown_time_20260514/entities.jsonl")
DEFAULT_OUT_DIR = Path("reports/canonical_entities_20260515")
COMMON_TOKENS = {
    "bar",
    "club",
    "live",
    "music",
    "records",
    "record",
    "official",
    "the",
}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
    tmp.replace(path)


def iter_jsonl(path: Path, limit: int = 0) -> Iterable[tuple[int, dict[str, Any]]]:
    with path.open("r", encoding="utf-8") as handle:
        for idx, line in enumerate(handle, start=1):
            if limit and idx > limit:
                break
            line = line.strip()
            if not line:
                continue
            value = json.loads(line)
            if isinstance(value, dict):
                yield idx, value


def normalize_display(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return " ".join(text.strip().split())


def exact_key(value: Any) -> str:
    return normalize_display(value).casefold()


def compact_key(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    chars = []
    for char in text:
        category = unicodedata.category(char)
        if category.startswith(("L", "N")):
            chars.append(char)
    return "".join(chars)


def has_cjk(value: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in value)


def useful_compact_key(value: str) -> bool:
    if not value:
        return False
    if value in COMMON_TOKENS:
        return False
    if has_cjk(value):
        return len(value) >= 2
    return len(value) >= 4


def entity_type(row: dict[str, Any]) -> str:
    return exact_key(row.get("type") or "unknown") or "unknown"


def confidence(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def mention_id(row: dict[str, Any], idx: int) -> str:
    source_article_uid = normalize_display(row.get("source_article_uid"))
    eid = normalize_display(row.get("eid"))
    if source_article_uid and eid:
        return f"{source_article_uid}#{eid}"
    if source_article_uid:
        return f"{source_article_uid}#row{idx}"
    return f"row{idx}"


def canonical_id(kind: str, name_key: str) -> str:
    digest = hashlib.sha1(f"{kind}:{name_key}".encode("utf-8")).hexdigest()[:14]
    return f"canon:{kind}:{digest}"


def add_group(groups: dict[tuple[str, str], dict[str, Any]], row: dict[str, Any], idx: int) -> None:
    name = normalize_display(row.get("name"))
    if not name:
        return
    kind = entity_type(row)
    key = (kind, exact_key(name))
    group = groups.setdefault(
        key,
        {
            "entity_type": kind,
            "name_key": key[1],
            "compact_name": compact_key(name),
            "display_names": Counter(),
            "aliases": Counter(),
            "source_articles": set(),
            "cities": Counter(),
            "mention_count": 0,
            "confidence_sum": 0.0,
            "merged_from_sample": [],
        },
    )
    group["mention_count"] += 1
    group["confidence_sum"] += confidence(row.get("confidence"))
    group["display_names"][name] += 1
    source_article_uid = normalize_display(row.get("source_article_uid"))
    if source_article_uid:
        group["source_articles"].add(source_article_uid)
    city = normalize_display(row.get("city"))
    if city:
        group["cities"][city] += 1
    aliases = row.get("aliases")
    if isinstance(aliases, list):
        for alias in aliases:
            alias_text = normalize_display(alias)
            if alias_text:
                group["aliases"][alias_text] += 1
    mid = mention_id(row, idx)
    if len(group["merged_from_sample"]) < 20:
        group["merged_from_sample"].append(mid)


def preferred_name(group: dict[str, Any]) -> str:
    names: Counter[str] = group["display_names"]
    return sorted(names.items(), key=lambda item: (-item[1], -len(item[0]), item[0]))[0][0]


def canonical_row(group: dict[str, Any]) -> dict[str, Any]:
    name = preferred_name(group)
    aliases = []
    seen = {exact_key(name)}
    for source in (group["display_names"], group["aliases"]):
        for alias, _count in source.most_common():
            key = exact_key(alias)
            if key and key not in seen:
                seen.add(key)
                aliases.append(alias)
            if len(aliases) >= 12:
                break
        if len(aliases) >= 12:
            break
    source_articles = sorted(group["source_articles"])
    return {
        "schema_version": "stage7_canonical_entity.v1",
        "canonical_id": canonical_id(group["entity_type"], group["name_key"]),
        "canonical_name": name,
        "entity_type": group["entity_type"],
        "aliases": aliases,
        "mention_count": group["mention_count"],
        "source_article_count": len(source_articles),
        "source_articles_sample": source_articles[:20],
        "merged_from_count": group["mention_count"],
        "merged_from_sample": group["merged_from_sample"],
        "avg_confidence": round(group["confidence_sum"] / max(group["mention_count"], 1), 4),
        "resolution_level": "exact_name_case_whitespace_normalized",
        "write_status": "report_only_not_written_to_neo4j",
    }


def candidate_key(left_id: str, right_id: str, match_type: str) -> tuple[str, str, str]:
    a, b = sorted((left_id, right_id))
    return (a, b, match_type)


def fuzzy_candidates(
    groups: list[dict[str, Any]],
    max_groups: int,
    max_candidates: int,
    min_mentions: int,
) -> list[dict[str, Any]]:
    eligible = [
        group
        for group in groups
        if group["mention_count"] >= min_mentions and useful_compact_key(group["compact_name"])
    ]
    eligible.sort(key=lambda group: (-group["mention_count"], preferred_name(group)))
    eligible = eligible[:max_groups]
    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for group in eligible:
        by_type[group["entity_type"]].append(group)

    compact_to_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for group in eligible:
        compact_to_groups[(group["entity_type"], group["compact_name"])].append(group)

    candidates: dict[tuple[str, str, str], dict[str, Any]] = {}

    def add_candidate(left: dict[str, Any], right: dict[str, Any], match_type: str, score: float, reason: str) -> None:
        left_row = canonical_row(left)
        right_row = canonical_row(right)
        if left_row["canonical_id"] == right_row["canonical_id"]:
            return
        key = candidate_key(left_row["canonical_id"], right_row["canonical_id"], match_type)
        current = candidates.get(key)
        row = {
            "schema_version": "stage7_canonical_entity_candidate.v1",
            "left_canonical_id": left_row["canonical_id"],
            "right_canonical_id": right_row["canonical_id"],
            "left_name": left_row["canonical_name"],
            "right_name": right_row["canonical_name"],
            "entity_type": left_row["entity_type"],
            "match_type": match_type,
            "score": round(score, 4),
            "reason": reason,
            "left_mention_count": left_row["mention_count"],
            "right_mention_count": right_row["mention_count"],
            "left_aliases_sample": left_row["aliases"][:8],
            "right_aliases_sample": right_row["aliases"][:8],
            "requires_review": True,
            "write_status": "report_only_not_written_to_neo4j",
        }
        if current is None or row["score"] > current["score"]:
            candidates[key] = row

    for group in eligible:
        alias_values = list(group["aliases"].keys()) + list(group["display_names"].keys())
        for alias in alias_values:
            alias_key = compact_key(alias)
            if not useful_compact_key(alias_key) or alias_key == group["compact_name"]:
                continue
            for other in compact_to_groups.get((group["entity_type"], alias_key), []):
                add_candidate(group, other, "alias_exact", 0.95, f"alias compact key `{alias_key}` matches another canonical name")

    for kind, typed_groups in by_type.items():
        del kind
        count = len(typed_groups)
        for left_idx in range(count):
            left = typed_groups[left_idx]
            left_key = left["compact_name"]
            for right in typed_groups[left_idx + 1 :]:
                right_key = right["compact_name"]
                if left_key == right_key:
                    continue
                short, long = (left_key, right_key) if len(left_key) <= len(right_key) else (right_key, left_key)
                if not useful_compact_key(short) or short not in long:
                    continue
                ratio = SequenceMatcher(None, left_key, right_key).ratio()
                containment = len(short) / max(len(long), 1)
                score = max(ratio, containment)
                if score >= 0.55 or (has_cjk(short) and len(short) >= 2):
                    add_candidate(left, right, "substring_or_near_alias", score, f"`{short}` is contained in `{long}`")
                if len(candidates) >= max_candidates * 3:
                    break
            if len(candidates) >= max_candidates * 3:
                break

    rows = sorted(
        candidates.values(),
        key=lambda row: (-row["score"], -row["left_mention_count"] - row["right_mention_count"], row["left_name"], row["right_name"]),
    )
    return rows[:max_candidates]


def build_canonical_index(
    entity_rows: Iterable[tuple[int, dict[str, Any]]],
    min_exact_mentions: int,
    max_fuzzy_groups: int,
    max_fuzzy_candidates: int,
    min_fuzzy_mentions: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    rows_seen = 0
    missing_name_rows = 0
    type_counts: Counter[str] = Counter()
    for idx, row in entity_rows:
        rows_seen += 1
        name = normalize_display(row.get("name"))
        if not name:
            missing_name_rows += 1
            continue
        type_counts[entity_type(row)] += 1
        add_group(groups, row, idx)

    merge_groups = [group for group in groups.values() if group["mention_count"] >= min_exact_mentions]
    merge_groups.sort(key=lambda group: (-group["mention_count"], preferred_name(group)))
    canonical_rows = [canonical_row(group) for group in merge_groups]
    candidates = fuzzy_candidates(list(groups.values()), max_fuzzy_groups, max_fuzzy_candidates, min_fuzzy_mentions)
    summary = {
        "schema_version": "stage7_canonical_entities_summary.v1",
        "generated_at": now_iso(),
        "entity_rows_seen": rows_seen,
        "missing_name_rows": missing_name_rows,
        "unique_exact_name_groups": len(groups),
        "canonical_exact_groups": len(canonical_rows),
        "fuzzy_review_candidates": len(candidates),
        "type_counts": dict(type_counts.most_common()),
        "top_canonical_groups": [
            {
                "canonical_id": row["canonical_id"],
                "canonical_name": row["canonical_name"],
                "entity_type": row["entity_type"],
                "mention_count": row["mention_count"],
                "source_article_count": row["source_article_count"],
            }
            for row in canonical_rows[:20]
        ],
        "top_review_candidates": candidates[:20],
        "safety": {
            "report_only": True,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "mem0_write_executed": False,
            "production_write_executed": False,
            "paid_api_used": False,
        },
    }
    return canonical_rows, candidates, summary


def decide(summary: dict[str, Any], min_exact_groups: int, require_fuzzy_candidates: bool) -> None:
    exact_ok = int(summary["canonical_exact_groups"]) >= min_exact_groups
    fuzzy_ok = int(summary["fuzzy_review_candidates"]) > 0 or not require_fuzzy_candidates
    summary["gate"] = {
        "min_exact_groups": min_exact_groups,
        "require_fuzzy_candidates": require_fuzzy_candidates,
        "exact_gate_met": exact_ok,
        "fuzzy_review_gate_met": fuzzy_ok,
    }
    summary["ok"] = exact_ok and fuzzy_ok
    summary["decision"] = "canonical_entity_report_ready" if summary["ok"] else "canonical_entity_report_needs_more_evidence"
    blockers = []
    if not exact_ok:
        blockers.append("exact canonical groups below gate")
    if not fuzzy_ok:
        blockers.append("no fuzzy/alias review candidates")
    summary["blockers"] = blockers
    summary["writes"] = "reports_only"


def write_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# Stage7 Canonical Entities Report",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- ok: `{summary['ok']}`",
        f"- decision: `{summary['decision']}`",
        f"- entity_rows_seen: `{summary['entity_rows_seen']}`",
        f"- unique_exact_name_groups: `{summary['unique_exact_name_groups']}`",
        f"- canonical_exact_groups: `{summary['canonical_exact_groups']}`",
        f"- fuzzy_review_candidates: `{summary['fuzzy_review_candidates']}`",
        "",
        "## Gate",
        "",
    ]
    for key, value in summary["gate"].items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Top Canonical Groups", "", "| Name | Type | Mentions | Articles |", "|---|---|---:|---:|"])
    for row in summary["top_canonical_groups"]:
        lines.append(
            f"| `{row['canonical_name']}` | `{row['entity_type']}` | {row['mention_count']} | {row['source_article_count']} |"
        )
    lines.extend(["", "## Top Review Candidates", "", "| Left | Right | Type | Match | Score |", "|---|---|---|---|---:|"])
    for row in summary["top_review_candidates"]:
        lines.append(
            f"| `{row['left_name']}` | `{row['right_name']}` | `{row['entity_type']}` | `{row['match_type']}` | {row['score']} |"
        )
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Report-only.",
            "- No Neo4j, Qdrant, mem0, SQLite, cloud, paid API, or production writes.",
            "- Fuzzy rows are review candidates, not automatic merges.",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    canonical_rows, candidates, summary = build_canonical_index(
        iter_jsonl(args.entities_jsonl, args.limit),
        min_exact_mentions=args.min_exact_mentions,
        max_fuzzy_groups=args.max_fuzzy_groups,
        max_fuzzy_candidates=args.max_fuzzy_candidates,
        min_fuzzy_mentions=args.min_fuzzy_mentions,
    )
    decide(summary, min_exact_groups=args.min_exact_groups, require_fuzzy_candidates=not args.no_require_fuzzy)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(args.out_dir / "canonical_index.jsonl", canonical_rows)
    write_jsonl(args.out_dir / "canonical_review_candidates.jsonl", candidates)
    write_json(args.out_dir / "canonical_entities_summary.json", summary)
    write_markdown(args.out_dir / "canonical_entities_summary.md", summary)
    print(
        json.dumps(
            {
                "ok": summary["ok"],
                "decision": summary["decision"],
                "canonical_exact_groups": summary["canonical_exact_groups"],
                "fuzzy_review_candidates": summary["fuzzy_review_candidates"],
                "summary": str(args.out_dir / "canonical_entities_summary.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if summary["ok"] or args.report_only_exit_zero else 2


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entities-jsonl", type=Path, default=DEFAULT_ENTITIES_JSONL)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--min-exact-mentions", type=int, default=2)
    parser.add_argument("--min-exact-groups", type=int, default=100)
    parser.add_argument("--max-fuzzy-groups", type=int, default=3000)
    parser.add_argument("--max-fuzzy-candidates", type=int, default=1000)
    parser.add_argument("--min-fuzzy-mentions", type=int, default=2)
    parser.add_argument("--no-require-fuzzy", action="store_true")
    parser.add_argument("--report-only-exit-zero", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
