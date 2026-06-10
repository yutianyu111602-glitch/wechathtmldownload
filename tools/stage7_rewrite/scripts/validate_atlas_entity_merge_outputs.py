#!/usr/bin/env python3
"""Validate Atlas entity-merge DeepSeek outputs and known merge boundaries."""

from __future__ import annotations

import argparse
import json
import re
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "atlas_entity_merge_output_validation.v1"
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_QUEUE = REPO_ROOT / "reports" / "atlas_entity_merge_deepseek_queue_ocr_full_current" / "entity_merge_llm_queue.jsonl"
DEFAULT_DECISIONS = REPO_ROOT / "reports" / "atlas_entity_merge_deepseek_results_ocr_full_current" / "entity_merge_llm_decisions.jsonl"
DEFAULT_PLAN_DIR = REPO_ROOT / "reports" / "atlas_entity_merge_plan_ocr_full_current"
DEFAULT_OUT_DIR = REPO_ROOT / "reports" / "atlas_entity_merge_validation_current"


KNOWN_CASES = [
    {
        "case": "loopy",
        "must_include": ["Loopy", "loopy Club", "杭州 Loopy", "LOOPY俱乐部"],
        "must_exclude": ["akkoii [loopy]"],
    },
    {
        "case": "oil",
        "must_include": ["OIL", "OIL油", "OIL Club"],
        "must_exclude": ["Boiler Room"],
    },
    {
        "case": "all",
        "must_include": ["ALL", "All俱乐部", "All Club Shanghai"],
        "must_exclude": ["ZhaoDai", "RealLive And Books"],
    },
]

FORBIDDEN_GROUP_KEYS = {
    "raw_json",
    "source_url",
    "source_urls",
    "cookie",
    "cookies",
    "token",
    "api_key",
    "authorization",
    "password",
    "secret",
}
FORBIDDEN_VALUE_PATTERNS = [
    re.compile(r"[A-Za-z]:\\"),
    re.compile(r"/mnt/[a-z]/", re.IGNORECASE),
    re.compile(r"file://", re.IGNORECASE),
    re.compile(r"\.sqlite\b", re.IGNORECASE),
    re.compile(r"sk-[A-Za-z0-9]{12,}"),
]


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def text(value: Any) -> str:
    return str(value or "").strip()


def name_key(value: Any) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text(value).casefold())


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_no, line in enumerate(handle, 1):
            stripped = line.strip()
            if not stripped:
                continue
            row = json.loads(stripped)
            if not isinstance(row, dict):
                raise ValueError(f"invalid JSONL object at {path}:{line_no}")
            rows.append(row)
    return rows


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def group_names(group: dict[str, Any]) -> list[str]:
    names = [text(group.get("canonical_name"))]
    names.extend(text(member.get("display_name")) for member in group.get("members") or [])
    out: list[str] = []
    seen: set[str] = set()
    for name in names:
        key = name_key(name)
        if name and key not in seen:
            seen.add(key)
            out.append(name)
    return out


def find_group_for_case(groups: list[dict[str, Any]], must_include: list[str]) -> dict[str, Any] | None:
    required = {name_key(item) for item in must_include}
    best: dict[str, Any] | None = None
    best_hits = -1
    for group in groups:
        keys = {name_key(name) for name in group_names(group)}
        hits = len(required & keys)
        if hits > best_hits:
            best = group
            best_hits = hits
        if required <= keys:
            return group
    return best


def iter_tree(value: Any, path: str = "$") -> Iterable[tuple[str, Any]]:
    yield path, value
    if isinstance(value, dict):
        for key, item in value.items():
            yield from iter_tree(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from iter_tree(item, f"{path}[{index}]")


def validate_group_integrity(groups: list[dict[str, Any]]) -> dict[str, Any]:
    subject_owner: dict[str, str] = {}
    duplicate_subjects: list[dict[str, str]] = []
    member_count_mismatch: list[dict[str, Any]] = []
    non_report_only_groups: list[str] = []
    forbidden_hits: list[dict[str, str]] = []
    for group in groups:
        group_id = text(group.get("group_id")) or text(group.get("canonical_subject_id"))
        members = group.get("members") if isinstance(group.get("members"), list) else []
        declared_count = int(group.get("member_count") or 0)
        if declared_count != len(members):
            member_count_mismatch.append({"group_id": group_id, "member_count": declared_count, "actual_member_count": len(members)})
        if group.get("report_only") is not True:
            non_report_only_groups.append(group_id)
        for member in members:
            subject_id = text(member.get("subject_id")) if isinstance(member, dict) else ""
            if not subject_id:
                continue
            previous = subject_owner.get(subject_id)
            if previous and previous != group_id:
                duplicate_subjects.append({"subject_id": subject_id, "first_group_id": previous, "second_group_id": group_id})
            subject_owner.setdefault(subject_id, group_id)
        for path, value in iter_tree(group):
            leaf = path.rsplit(".", 1)[-1].split("[", 1)[0].casefold()
            if leaf in FORBIDDEN_GROUP_KEYS:
                forbidden_hits.append({"group_id": group_id, "path": path, "reason": "forbidden_key"})
                continue
            if isinstance(value, str):
                for pattern in FORBIDDEN_VALUE_PATTERNS:
                    if pattern.search(value):
                        forbidden_hits.append({"group_id": group_id, "path": path, "reason": f"forbidden_value:{pattern.pattern}"})
                        break
    return {
        "duplicate_subjects": duplicate_subjects[:50],
        "duplicate_subject_count": len(duplicate_subjects),
        "member_count_mismatch": member_count_mismatch[:50],
        "member_count_mismatch_count": len(member_count_mismatch),
        "non_report_only_groups": non_report_only_groups[:50],
        "non_report_only_group_count": len(non_report_only_groups),
        "forbidden_hits": forbidden_hits[:50],
        "forbidden_hit_count": len(forbidden_hits),
    }


def validate_known_cases(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for case in KNOWN_CASES:
        group = find_group_for_case(groups, case["must_include"])
        names = group_names(group or {})
        keys = {name_key(name) for name in names}
        missing = [item for item in case["must_include"] if name_key(item) not in keys]
        forbidden_present = [item for item in case["must_exclude"] if name_key(item) in keys]
        checks.append(
            {
                "case": case["case"],
                "ok": not missing and not forbidden_present,
                "canonical_subject_id": text((group or {}).get("canonical_subject_id")),
                "canonical_name": text((group or {}).get("canonical_name")),
                "member_count": int((group or {}).get("member_count") or len((group or {}).get("members") or [])),
                "missing": missing,
                "forbidden_present": forbidden_present,
                "sample_names": names[:16],
            }
        )
    return checks


def write_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# Atlas Entity Merge Output Validation",
        "",
        f"- decision: `{summary['decision']}`",
        f"- queue_rows: `{summary['coverage']['queue_rows']}`",
        f"- latest_execute_decisions: `{summary['coverage']['latest_execute_decisions']}`",
        f"- missing_decisions: `{summary['coverage']['missing_decisions']}`",
        f"- unknown_decisions_ignored: `{summary['coverage']['unknown_decisions_ignored']}`",
        f"- plan_error_rows: `{summary['plan']['error_rows']}`",
        f"- merge_groups: `{summary['plan']['merge_groups']}`",
        f"- merged_subjects: `{summary['plan']['merged_subjects']}`",
        "",
        "## Known Cases",
        "",
    ]
    for check in summary["known_cases"]:
        marker = "PASS" if check["ok"] else "FAIL"
        lines.append(
            f"- `{marker}` `{check['case']}` -> `{check['canonical_name']}` / `{check['canonical_subject_id']}`; "
            f"members `{check['member_count']}`; missing `{check['missing']}`; forbidden `{check['forbidden_present']}`"
        )
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- validation is read-only",
            "- no DeepSeek call, SQLite write, Neo4j write, Qdrant write, mem0 write, or production pointer update",
            "",
        ]
    )
    write_text(path, "\n".join(lines))


def validate_outputs(args: argparse.Namespace) -> dict[str, Any]:
    queue_path = Path(args.queue)
    decisions_path = Path(args.decisions)
    plan_dir = Path(args.plan_dir)
    out_dir = Path(args.out_dir)
    groups_path = plan_dir / "entity_merge_groups_report_only.jsonl"
    review_path = plan_dir / "entity_merge_review_queue.jsonl"
    split_path = plan_dir / "entity_merge_split_decisions.jsonl"
    errors_path = plan_dir / "entity_merge_error_decisions.jsonl"

    queue_rows = read_jsonl(queue_path)
    decision_rows = read_jsonl(decisions_path)
    for extra_path in getattr(args, "extra_decisions", []) or []:
        path = Path(extra_path)
        if path.exists():
            decision_rows.extend(read_jsonl(path))
    groups = read_jsonl(groups_path)
    review_rows = read_jsonl(review_path) if review_path.exists() else []
    split_rows = read_jsonl(split_path) if split_path.exists() else []
    error_rows = read_jsonl(errors_path) if errors_path.exists() else []

    queue_ids = {text(row.get("cluster_id")) for row in queue_rows if text(row.get("cluster_id"))}
    latest_execute_by_cluster: dict[str, dict[str, Any]] = {}
    unknown_decisions = 0
    for row in decision_rows:
        cluster_id = text(row.get("cluster_id"))
        if cluster_id not in queue_ids:
            unknown_decisions += 1
            continue
        if bool(row.get("execute")):
            latest_execute_by_cluster[cluster_id] = row

    missing = sorted(queue_ids - latest_execute_by_cluster.keys())
    decision_counts = Counter(text(row.get("decision")) or "unknown" for row in latest_execute_by_cluster.values())
    known_cases = validate_known_cases(groups)
    group_integrity = validate_group_integrity(groups)
    hard_blockers: list[str] = []
    if missing:
        hard_blockers.append("missing_current_queue_decisions")
    if error_rows:
        hard_blockers.append("plan_error_rows_present")
    if any(not row["ok"] for row in known_cases):
        hard_blockers.append("known_case_boundary_failure")
    if group_integrity["duplicate_subject_count"]:
        hard_blockers.append("duplicate_subject_across_merge_groups")
    if group_integrity["member_count_mismatch_count"]:
        hard_blockers.append("merge_group_member_count_mismatch")
    if group_integrity["non_report_only_group_count"]:
        hard_blockers.append("merge_group_not_report_only")
    if group_integrity["forbidden_hit_count"]:
        hard_blockers.append("merge_group_forbidden_field_or_value")

    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": "atlas_entity_merge_outputs_validated" if not hard_blockers else "atlas_entity_merge_outputs_blocked",
        "queue_path": str(queue_path),
        "decisions_path": str(decisions_path),
        "extra_decisions_paths": [str(Path(path)) for path in getattr(args, "extra_decisions", []) or []],
        "plan_dir": str(plan_dir),
        "out_dir": str(out_dir),
        "coverage": {
            "queue_rows": len(queue_rows),
            "decision_rows_raw": len(decision_rows),
            "latest_execute_decisions": len(latest_execute_by_cluster),
            "missing_decisions": len(missing),
            "missing_decision_sample": missing[:20],
            "unknown_decisions_ignored": unknown_decisions,
            "decision_counts": dict(decision_counts),
        },
        "plan": {
            "merge_groups": len(groups),
            "merged_subjects": len({text(member.get("subject_id")) for group in groups for member in group.get("members") or [] if text(member.get("subject_id"))}),
            "review_rows": len(review_rows),
            "split_rows": len(split_rows),
            "error_rows": len(error_rows),
            "ocr_confusable_queue_rows": sum(1 for row in queue_rows if "ocr_confusable_key" in (row.get("risk_flags") or [])),
            "ocr_confusable_groups": sum(1 for row in groups if "ocr_confusable_key" in (row.get("risk_flags") or [])),
        },
        "known_cases": known_cases,
        "group_integrity": group_integrity,
        "hard_blockers": hard_blockers,
        "safety": {
            "read_only_validation": True,
            "llm_call_executed": False,
            "sqlite_write_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "mem0_write_executed": False,
            "production_pointer_updated": False,
            "raw_secret_read": False,
        },
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "entity_merge_validation_summary.json", summary)
    write_markdown(out_dir / "entity_merge_validation_report.md", summary)
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", default=str(DEFAULT_QUEUE))
    parser.add_argument("--decisions", default=str(DEFAULT_DECISIONS))
    parser.add_argument("--extra-decisions", action="append", default=[])
    parser.add_argument("--plan-dir", default=str(DEFAULT_PLAN_DIR))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    summary = validate_outputs(parse_args(argv))
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not summary["hard_blockers"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
