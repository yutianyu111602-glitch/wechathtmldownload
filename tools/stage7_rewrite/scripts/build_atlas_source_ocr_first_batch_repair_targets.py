#!/usr/bin/env python3
"""Build report-only repair targets from the Atlas first-batch evidence probe."""
from __future__ import annotations

import argparse
import json
import re
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE7_ROOT.parents[1]
DEFAULT_INPUT = (
    STAGE7_ROOT
    / "reports"
    / "atlas_source_ocr_first_batch_evidence_probe_t5_20260526"
    / "first_batch_evidence_probe_rows.jsonl"
)
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_source_ocr_first_batch_repair_targets_t5_20260526"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T5_SOURCE_OCR_FIRST_BATCH_REPAIR_TARGETS_20260526.md"
SCHEMA_VERSION = "stage7_atlas_source_ocr_first_batch_repair_targets.v1"

URL_RE = re.compile(r"https?://", re.I)
LOCAL_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"']+|/mnt/[A-Za-z][^\s\"']*|/home/[^\s\"']+|\\\\[A-Za-z0-9_.-]+[\\/][^\s\"']+",
    re.I,
)
SENSITIVE_KEY_RE = re.compile(r"(secret|token|cookie|password|api[_-]?key|authorization)", re.I)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").casefold()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for Atlas first-batch repair targets: {path}")


def compact(value: Any, limit: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_d_path(path, "input_jsonl")
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        for line_no, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            value = json.loads(stripped)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_no}: expected object row")
            rows.append(value)
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, newline="\n") as handle:
        handle.write(text)
        tmp = Path(handle.name)
    tmp.replace(path)


def safe_source_url_evidence(row: dict[str, Any]) -> dict[str, Any]:
    source = row.get("source_url_evidence")
    if not isinstance(source, dict):
        return {"source_url_recovery_found": False}
    return {
        "source_url_recovery_found": bool(source.get("source_url_recovery_found")),
        "source_ref_id": compact(source.get("source_ref_id"), 120),
        "source_url_sha256": compact(source.get("source_url_sha256"), 80),
        "source_url_present": bool(source.get("source_url_present")),
        "source_url_match_basis": compact(source.get("source_url_match_basis"), 160),
        "source_url_confidence": source.get("source_url_confidence") or 0,
        "post_time_present": bool(source.get("post_time_present")),
        "post_date_present": bool(source.get("post_date_present")),
    }


def candidate_names(candidates: Any, key: str = "name", limit: int = 12) -> list[str]:
    if not isinstance(candidates, list):
        return []
    names: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        name = compact(candidate.get(key), 160)
        folded = name.casefold()
        if not name or folded in seen:
            continue
        seen.add(folded)
        names.append(name)
        if len(names) >= limit:
            break
    return names


def choose_primary_lane(content_class: str, missing: list[str], row: dict[str, Any]) -> str:
    missing_set = set(missing)
    if content_class == "editorial_or_profile_candidate":
        return "manual_event_filter_or_entity_relation_review"
    if content_class == "event_like_candidate" and missing_set == {"date_verified"}:
        return "fast_date_repair_for_event_acceptance"
    if content_class == "event_like_candidate" and "ocr_markdown_verified" in missing_set:
        return "event_ocr_markdown_and_date_repair"
    if "source_context_verified" in missing_set:
        return "source_context_repair"
    if "ocr_markdown_verified" in missing_set and int(row.get("local_image_count") or 0) > 0:
        return "ocr_markdown_localization_or_generation"
    if "date_verified" in missing_set:
        return "date_evidence_localization"
    return "acceptance_precheck_rerun_candidate"


def lane_priority(content_class: str, primary_lane: str, row: dict[str, Any], missing: list[str]) -> int:
    score = 0
    if content_class == "event_like_candidate":
        score += 100
    elif content_class == "image_rich_entity_relation_candidate":
        score += 70
    elif content_class == "entity_relation_candidate":
        score += 60
    elif content_class == "editorial_or_profile_candidate":
        score += 20
    if primary_lane == "fast_date_repair_for_event_acceptance":
        score += 40
    if row.get("source_context_candidate_found"):
        score += 10
    if row.get("source_url_evidence", {}).get("source_url_recovery_found"):
        score += 8
    if row.get("ocr_markdown_candidate_found"):
        score += 8
    score += min(len(row.get("lineup_candidates") or []), 8)
    score += min(len(row.get("venue_candidates") or []), 5)
    score -= len(missing) * 3
    return score


def action_flags(row: dict[str, Any], missing: list[str], primary_lane: str) -> list[str]:
    flags: list[str] = []
    if "date_verified" in missing:
        flags.append("localize_date_from_article_header_text_or_ocr")
    if "ocr_markdown_verified" in missing:
        flags.append("locate_or_generate_ocr_markdown_for_local_images")
    if "source_context_verified" in missing:
        flags.append("recover_article_context_from_local_source_db_or_archive")
    if "venue_verified" in missing:
        flags.append("verify_venue_against_source_context")
    if "lineup_verified" in missing:
        flags.append("verify_lineup_against_source_context")
    if primary_lane == "manual_event_filter_or_entity_relation_review":
        flags.append("keep_out_of_performance_event_acceptance_until_reviewed")
    return flags


def target_row(row: dict[str, Any], generated_at: str, source_rank: int) -> dict[str, Any]:
    missing = [compact(item, 120) for item in row.get("missing_after_probe") or [] if compact(item, 120)]
    content_class = compact(row.get("content_classification"), 120)
    primary_lane = choose_primary_lane(content_class, missing, row)
    date_values = candidate_names(row.get("date_candidates"), key="value", limit=8)
    venue_names = candidate_names(row.get("venue_candidates"), limit=8)
    lineup_names = candidate_names(row.get("lineup_candidates"), limit=16)
    source_url = safe_source_url_evidence(row)
    priority = lane_priority(content_class, primary_lane, row, missing)
    return {
        "schema_version": SCHEMA_VERSION + ".target_row",
        "generated_at": generated_at,
        "source_rank": source_rank,
        "repair_rank": 0,
        "repair_priority": priority,
        "primary_repair_lane": primary_lane,
        "work_item_id": compact(row.get("work_item_id"), 120),
        "article_uid": compact(row.get("article_uid"), 200),
        "source_account": compact(row.get("source_account"), 200),
        "title": compact(row.get("title"), 500),
        "content_classification": content_class,
        "candidate_status": compact(row.get("candidate_status"), 180),
        "blocking_fields": missing,
        "repair_actions": action_flags(row, missing, primary_lane),
        "candidate_field_counts": {
            "date_candidates": len(row.get("date_candidates") or []),
            "venue_candidates": len(row.get("venue_candidates") or []),
            "lineup_candidates": len(row.get("lineup_candidates") or []),
            "source_entity_rows_found": int(row.get("source_entity_rows_found") or 0),
            "source_event_rows_found": int(row.get("source_event_rows_found") or 0),
            "local_image_count": int(row.get("local_image_count") or 0),
        },
        "candidate_preview": {
            "date_values": date_values,
            "venue_names": venue_names,
            "lineup_names": lineup_names,
            "source_entity_kinds": [compact(item, 80) for item in row.get("source_entity_kinds") or [] if compact(item, 80)],
        },
        "source_url_evidence": source_url,
        "ready_for_acceptance_gate": False,
        "accepted_for_graph": False,
        "serving_rebuild_allowed": False,
        "graph_write_allowed": False,
        "public_serving_field_allowed": False,
        "write_status": "report_only",
    }


def scan_payload_for_leaks(value: Any, key_path: tuple[str, ...] = ()) -> dict[str, int]:
    hits = {"public_url_hits": 0, "secret_word_hits": 0, "local_path_hits": 0}
    if isinstance(value, dict):
        for key, child in value.items():
            child_hits = scan_payload_for_leaks(child, key_path + (str(key),))
            for name, count in child_hits.items():
                hits[name] += count
        return hits
    if isinstance(value, list):
        for child in value:
            child_hits = scan_payload_for_leaks(child, key_path)
            for name, count in child_hits.items():
                hits[name] += count
        return hits
    text = compact(value, 4000)
    if not text:
        return hits
    joined_key = ".".join(key_path)
    hits["public_url_hits"] += len(URL_RE.findall(text))
    hits["local_path_hits"] += len(LOCAL_PATH_RE.findall(text))
    if SENSITIVE_KEY_RE.search(joined_key):
        hits["secret_word_hits"] += 1
    return hits


def leak_scan(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    total = {"public_url_hits": 0, "secret_word_hits": 0, "local_path_hits": 0}
    for row in rows:
        hits = scan_payload_for_leaks(row)
        for name, count in hits.items():
            total[name] += count
    return total


def rollup_by_source(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["source_account"]].append(row)
    rollups: list[dict[str, Any]] = []
    for source, source_rows in grouped.items():
        lane_counts = Counter(row["primary_repair_lane"] for row in source_rows)
        rollups.append(
            {
                "schema_version": SCHEMA_VERSION + ".source_rollup",
                "source_account": source,
                "rows": len(source_rows),
                "lane_counts": dict(sorted(lane_counts.items())),
                "event_like_rows": sum(1 for row in source_rows if row["content_classification"] == "event_like_candidate"),
                "date_blocked_rows": sum(1 for row in source_rows if "date_verified" in row["blocking_fields"]),
                "ocr_blocked_rows": sum(1 for row in source_rows if "ocr_markdown_verified" in row["blocking_fields"]),
                "first_repair_rank": min(row["repair_rank"] for row in source_rows),
                "write_status": "report_only",
            }
        )
    return sorted(rollups, key=lambda row: (-row["rows"], row["first_repair_rank"], row["source_account"]))


def build_report(summary: dict[str, Any], sample_rows: list[dict[str, Any]]) -> str:
    counts = summary["counts"]
    lines = [
        "# Atlas T5 Source/OCR First-Batch Repair Targets",
        "",
        f"- Generated at: `{summary['generated_at']}`",
        f"- Decision: `{summary['decision']}`",
        f"- Failed checks: `{summary['failed_checks']}`",
        f"- Input probe rows: `{counts['input_probe_rows']}`",
        f"- Repair target rows: `{counts['repair_target_rows']}`",
        f"- Event-like repair targets: `{counts['event_like_repair_targets']}`",
        f"- Fast date lane rows: `{counts['fast_date_lane_rows']}`",
        f"- Date repair rows: `{counts['date_repair_rows']}`",
        f"- OCR/Markdown repair rows: `{counts['ocr_markdown_repair_rows']}`",
        f"- Entity/review rows: `{counts['entity_or_review_rows']}`",
        f"- Public URL / secret / local path leak hits: `{summary['leak_scan']['public_url_hits']}` / `{summary['leak_scan']['secret_word_hits']}` / `{summary['leak_scan']['local_path_hits']}`",
        "",
        "## Lane Counts",
        "",
        "| lane | rows |",
        "| --- | ---: |",
    ]
    for lane, count in sorted(summary["lane_counts"].items()):
        lines.append(f"| `{lane}` | `{count}` |")
    lines.extend(["", "## First Execution Slice", "", "| rank | source | title | lane | blockers |", "| ---: | --- | --- | --- | --- |"])
    for row in sample_rows[:10]:
        lines.append(
            f"| `{row['repair_rank']}` | `{row['source_account']}` | {row['title']} | `{row['primary_repair_lane']}` | `{row['blocking_fields']}` |"
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- Report-only target queue from already-generated probe evidence.",
            "- No OCR execution, LLM/model call, source/raw Atlas DB write, serving SQLite write/rebuild, public pointer, CloudRun/VPS deploy, Neo4j/Qdrant/SQLite production write, mini-program upload/review, memory write, credential read, 9router use, destructive Git, or D: root scan occurred.",
            "- Source URLs are not emitted raw; rows only keep source URL presence, match basis, source ref, and SHA256.",
            "",
            "## Next Gate",
            "",
            "Start with `fast_date_repair_for_event_acceptance`, then `event_ocr_markdown_and_date_repair`. After each local repair slice, rerun the source/OCR acceptance precheck before accepting graph facts or rebuilding serving outputs.",
            "",
        ]
    )
    return "\n".join(lines)


def build_repair_targets(input_path: Path, out_dir: Path, report_path: Path) -> dict[str, Any]:
    generated_at = now_iso()
    probe_rows = read_jsonl(input_path)
    targets = [target_row(row, generated_at, idx) for idx, row in enumerate(probe_rows, start=1)]
    targets.sort(key=lambda row: (-row["repair_priority"], row["source_rank"], row["source_account"], row["title"]))
    for idx, row in enumerate(targets, start=1):
        row["repair_rank"] = idx

    event_like = [row for row in targets if row["content_classification"] == "event_like_candidate"]
    fast_date = [row for row in targets if row["primary_repair_lane"] == "fast_date_repair_for_event_acceptance"]
    date_targets = [row for row in targets if "date_verified" in row["blocking_fields"]]
    ocr_targets = [row for row in targets if "ocr_markdown_verified" in row["blocking_fields"]]
    entity_review = [row for row in targets if row["content_classification"] != "event_like_candidate"]
    source_rollups = rollup_by_source(targets)
    leak_hits = leak_scan(targets)
    failed_checks: list[str] = []
    if any(leak_hits.values()):
        failed_checks.append("repair_target_output_contains_public_url_secret_or_local_path")
    if not targets:
        failed_checks.append("no_repair_targets")

    lane_counts = Counter(row["primary_repair_lane"] for row in targets)
    counts = {
        "input_probe_rows": len(probe_rows),
        "repair_target_rows": len(targets),
        "event_like_repair_targets": len(event_like),
        "fast_date_lane_rows": len(fast_date),
        "date_repair_rows": len(date_targets),
        "ocr_markdown_repair_rows": len(ocr_targets),
        "entity_or_review_rows": len(entity_review),
        "source_account_rollup_rows": len(source_rollups),
    }
    summary = {
        "schema_version": SCHEMA_VERSION + ".summary",
        "generated_at": generated_at,
        "decision": "atlas_source_ocr_first_batch_repair_targets_ready_report_only"
        if not failed_checks
        else "atlas_source_ocr_first_batch_repair_targets_failed_safety_scan",
        "failed_checks": failed_checks,
        "inputs": {"probe_rows": display_path(input_path)},
        "outputs": {
            "repair_target_rows": display_path(out_dir / "repair_target_rows.jsonl"),
            "event_like_repair_targets": display_path(out_dir / "event_like_repair_targets.jsonl"),
            "fast_date_repair_targets": display_path(out_dir / "fast_date_repair_targets.jsonl"),
            "date_repair_targets": display_path(out_dir / "date_repair_targets.jsonl"),
            "ocr_markdown_repair_targets": display_path(out_dir / "ocr_markdown_repair_targets.jsonl"),
            "entity_relation_review_targets": display_path(out_dir / "entity_relation_review_targets.jsonl"),
            "source_account_repair_rollup": display_path(out_dir / "source_account_repair_rollup.jsonl"),
        },
        "counts": counts,
        "lane_counts": dict(sorted(lane_counts.items())),
        "source_account_counts": dict(sorted(Counter(row["source_account"] for row in targets).items())),
        "leak_scan": leak_hits,
        "execution_cursor": {
            "first_lane": fast_date[0]["primary_repair_lane"] if fast_date else (targets[0]["primary_repair_lane"] if targets else "none"),
            "first_lane_rows": len(fast_date) if fast_date else (1 if targets else 0),
            "next_command_intent": "Repair/localize the first target lane, rerun source/OCR acceptance precheck, then keep graph/serving writes closed until gates pass.",
        },
        "safety": {
            "report_only": True,
            "raw_source_url_emitted": False,
            "ocr_execution_executed": False,
            "llm_call_executed": False,
            "network_call_executed": False,
            "production_write_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "serving_sqlite_rebuild_executed": False,
            "source_sqlite_write_executed": False,
            "memory_write_executed": False,
            "credential_read": False,
            "d_root_scan": False,
        },
        "stop_reason": "none" if not failed_checks else "repair_target_failed_checks",
        "wait_reason": "none",
    }

    write_jsonl(out_dir / "repair_target_rows.jsonl", targets)
    write_jsonl(out_dir / "event_like_repair_targets.jsonl", event_like)
    write_jsonl(out_dir / "fast_date_repair_targets.jsonl", fast_date)
    write_jsonl(out_dir / "date_repair_targets.jsonl", date_targets)
    write_jsonl(out_dir / "ocr_markdown_repair_targets.jsonl", ocr_targets)
    write_jsonl(out_dir / "entity_relation_review_targets.jsonl", entity_review)
    write_jsonl(out_dir / "source_account_repair_rollup.jsonl", source_rollups)
    write_json(out_dir / "source_ocr_first_batch_repair_targets_summary.json", summary)
    write_text(report_path, build_report(summary, targets))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_repair_targets(args.input, args.out_dir, args.report)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not summary["failed_checks"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
