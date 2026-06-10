#!/usr/bin/env python3
"""Build a report-only PRD-14 fuzzy canonical review gate packet.

The packet reviews the existing fuzzy/alias candidate file as a future-write
gate. It does not accept merges or write Neo4j. Instead it makes the current
promotion-safe decision explicit: exact canonical groups may remain report
evidence, while fuzzy merge/write is deferred until a separate review/write gate.
"""
from __future__ import annotations

import argparse
import json
import re
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_SUMMARY = Path("reports/canonical_entities_20260515/canonical_entities_summary.json")
DEFAULT_CANDIDATES = Path("reports/canonical_entities_20260515/canonical_review_candidates.jsonl")
DEFAULT_OUT_DIR = Path("reports/canonical_fuzzy_review_gate_packet_20260517")
SCHEMA_VERSION = "stage7_canonical_fuzzy_review_gate_packet.v1"


PLACE_PARENT_TERMS = {
    "中国",
    "china",
    "北京",
    "beijing",
    "北京市",
    "上海",
    "shanghai",
    "深圳",
    "shenzhen",
    "广州",
    "guangzhou",
    "成都",
    "chengdu",
    "昆明",
    "kunming",
    "广东",
    "guangdong",
    "朝阳区",
    "chaoyangdistrict",
    "东城区",
    "dongchengdistrict",
}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for canonical fuzzy review gate: {path}")


def read_json(path: Path) -> dict[str, Any]:
    reject_d_path(path, "json")
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    return value if isinstance(value, dict) else {}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_d_path(path, "jsonl")
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


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def compact(value: Any) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value or "").casefold())


def classify_candidate(row: dict[str, Any]) -> str:
    entity_type = str(row.get("entity_type") or "unknown").casefold()
    left = compact(row.get("left_name"))
    right = compact(row.get("right_name"))
    match_type = str(row.get("match_type") or "")
    if entity_type == "place" and (left in PLACE_PARENT_TERMS or right in PLACE_PARENT_TERMS):
        return "deferred_hierarchical_place_or_parent_alias"
    if entity_type == "place" and (left in right or right in left):
        return "deferred_place_address_or_subregion"
    if match_type == "alias_exact":
        return "deferred_alias_exact_requires_owner_review"
    return "deferred_fuzzy_requires_owner_review"


def build_packet(*, summary_path: Path, candidates_path: Path, out_dir: Path) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    summary = read_json(summary_path)
    candidates = read_jsonl(candidates_path)
    review_rows = []
    for row in candidates:
        decision = classify_candidate(row)
        enriched = dict(row)
        enriched.update(
            {
                "schema_version": SCHEMA_VERSION + ".row",
                "review_decision": decision,
                "merge_accepted": False,
                "write_allowed": False,
                "requires_owner_review_before_write": True,
            }
        )
        review_rows.append(enriched)

    decision_counts = Counter(row["review_decision"] for row in review_rows)
    out_dir.mkdir(parents=True, exist_ok=True)
    review_path = out_dir / "canonical_fuzzy_review_rows.jsonl"
    write_jsonl(review_path, review_rows)
    packet = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": True,
        "decision": "canonical_fuzzy_review_gate_ready_report_only",
        "summary_path": str(summary_path),
        "candidates_path": str(candidates_path),
        "review_path": str(review_path),
        "canonical_exact_groups": summary.get("canonical_exact_groups"),
        "fuzzy_review_candidates": len(candidates),
        "reviewed_candidates": len(review_rows),
        "unreviewed_candidates": 0,
        "accepted_merges": 0,
        "deferred_merges": len(review_rows),
        "future_fuzzy_merge_write_deferred": True,
        "decision_counts": dict(decision_counts),
        "promotion_blocker_cleared_by_deferral": bool(review_rows),
        "blockers": [
            "fuzzy canonical merge/write remains deferred",
            "Neo4j canonical writes remain forbidden",
            "production graph labels remain forbidden",
        ],
        "allowed_next_actions": [
            "use exact canonical groups as report-only evidence",
            "keep fuzzy merge candidates deferred until owner review and a separate Neo4j write gate",
            "allow graph promotion readiness to stop treating fuzzy candidates as an unreviewed hidden write dependency",
        ],
        "safety": {
            "reports_only": True,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "mem0_write_executed": False,
            "production_write_executed": False,
            "paid_api_used": False,
            "d_scan_executed": False,
            "publish_executed": False,
        },
        "writes": "reports_only",
    }
    write_json(out_dir / "canonical_fuzzy_review_gate_packet.json", packet)
    write_markdown(out_dir / "canonical_fuzzy_review_gate_packet.md", packet)
    return packet


def write_markdown(path: Path, packet: dict[str, Any]) -> None:
    lines = [
        "# Canonical Fuzzy Review Gate Packet",
        "",
        f"- generated_at: `{packet['generated_at']}`",
        f"- decision: `{packet['decision']}`",
        f"- canonical_exact_groups: `{packet['canonical_exact_groups']}`",
        f"- fuzzy_review_candidates: `{packet['fuzzy_review_candidates']}`",
        f"- reviewed_candidates: `{packet['reviewed_candidates']}`",
        f"- accepted_merges: `{packet['accepted_merges']}`",
        f"- deferred_merges: `{packet['deferred_merges']}`",
        f"- future_fuzzy_merge_write_deferred: `{packet['future_fuzzy_merge_write_deferred']}`",
        "",
        "## Decision Counts",
        "",
    ]
    for key, value in sorted(packet["decision_counts"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Safety", ""])
    for key, value in sorted(packet["safety"].items()):
        lines.append(f"- `{key}`: `{value}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    packet = build_packet(summary_path=args.summary, candidates_path=args.candidates, out_dir=args.out_dir)
    print(
        json.dumps(
            {
                "ok": packet["ok"],
                "decision": packet["decision"],
                "fuzzy_review_candidates": packet["fuzzy_review_candidates"],
                "accepted_merges": packet["accepted_merges"],
                "deferred_merges": packet["deferred_merges"],
                "summary": str(args.out_dir / "canonical_fuzzy_review_gate_packet.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
