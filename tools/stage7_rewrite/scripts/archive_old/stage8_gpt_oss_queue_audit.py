#!/usr/bin/env python3
"""Audit GPT-OSS QA queues without touching Stage7 or vector writers.

The GPT-OSS lane is advisory. This tool reads a completed
``stage8_gpt_oss_qa.py`` report, classifies useful/suspicious queue rows, and
writes review artifacts for later Qwen salvage budgeting.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


ACTION_VALUES = {"qwen_salvage", "deterministic_cleanup", "hold_low_signal"}
SALVAGE_FAILURES = {"quote_not_exact", "model_underextracted", "input_fragmented"}
LOW_SIGNAL_FAILURES = {"image_only", "metadata_only", "low_value"}
MARKER_PATTERNS = {
    "music": re.compile(r"(?i)(dj|live|舞|派对|演出|现场|厂牌|电子|techno|house|ambient|experimental|noise)"),
    "lineup": re.compile(r"(?i)(line[\s-]?up|阵容|名单|artist|guest)"),
    "venue": re.compile(r"(?i)(venue|club|bar|地址|场地|space|room|floor)"),
    "ticket": re.compile(r"(?i)(rmb|tickets?|购票|门票|预售|presale|door price)"),
    "time": re.compile(
        r"(?i)(\b\d{1,2}[:：]\d{2}\b|\b\d{1,2}\s*(pm|am)\b|"
        r"\b\d{1,2}\s*(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\b|"
        r"\b20\d{2}[./-]\d{1,2}[./-]\d{1,2}\b|明晚|周[一二三四五六日天]|星期)"
    ),
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def parsed(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("parsed")
    return value if isinstance(value, dict) else {}


def compact_row(row: dict[str, Any], reason: str) -> dict[str, Any]:
    p = parsed(row)
    return {
        "sample_id": row.get("sample_id"),
        "article_id": row.get("article_id"),
        "account": row.get("account"),
        "title": row.get("title"),
        "category": row.get("category"),
        "priority": row.get("priority"),
        "entity_count": row.get("entity_count"),
        "event_count": row.get("event_count"),
        "evidence_drop_count": row.get("evidence_drop_count"),
        "recommended_action": p.get("recommended_action"),
        "failure_cause": p.get("failure_cause"),
        "has_extractable_music_value": p.get("has_extractable_music_value"),
        "scene_tags": p.get("scene_tags"),
        "reason_short": p.get("reason_short"),
        "audit_reason": reason,
        "extract_path": row.get("extract_path"),
    }


def marker_features(row: dict[str, Any]) -> set[str]:
    haystack = " ".join(str(row.get(key) or "") for key in ("title", "excerpt"))
    return {name for name, pattern in MARKER_PATTERNS.items() if pattern.search(haystack)}


def has_action_label_scene_tags(row: dict[str, Any]) -> bool:
    tags = parsed(row).get("scene_tags")
    if not isinstance(tags, list):
        return False
    return bool({str(tag) for tag in tags} & ACTION_VALUES)


def classify_salvage(row: dict[str, Any]) -> tuple[str, str] | None:
    p = parsed(row)
    if p.get("recommended_action") != "qwen_salvage":
        return None
    failure = str(p.get("failure_cause") or "")
    category = str(row.get("category") or "")
    has_value = p.get("has_extractable_music_value") is True

    if p.get("has_extractable_music_value") is False:
        return "deterministic_or_hold", "salvage_without_music_value"
    if failure == "low_value":
        return "deterministic_or_hold", "salvage_low_value"
    if category == "title_pseudoquote":
        return "review", "title_pseudoquote_may_be_cleanup"
    if has_value and failure in SALVAGE_FAILURES:
        return "strong", "valuable_extractable_salvage_failure"
    return "review", "salvage_needs_human_review"


def is_hold_false_negative(row: dict[str, Any]) -> tuple[bool, str]:
    p = parsed(row)
    if p.get("recommended_action") != "hold_low_signal":
        return False, ""
    if p.get("has_extractable_music_value") is True:
        return True, "hold_but_model_says_extractable"
    try:
        has_objects = int(row.get("entity_count") or 0) + int(row.get("event_count") or 0) > 0
    except (TypeError, ValueError):
        has_objects = False
    features = marker_features(row)
    if has_objects and len(features) >= 2:
        return True, "hold_with_objects_and_multiple_markers"
    failure = str(p.get("failure_cause") or "")
    if str(row.get("category") or "") == "zero_entity_event" and (
        len(features) >= 4 or (len(features) >= 3 and failure not in LOW_SIGNAL_FAILURES)
    ):
        return True, "zero_object_hold_with_strong_music_markers"
    return False, ""


def audit(report: dict[str, Any]) -> dict[str, Any]:
    rows = report.get("sample_outputs") or []
    action_counts: Counter[str] = Counter()
    failure_counts: Counter[str] = Counter()
    category_action_counts: Counter[str] = Counter()
    parse_failures = []
    action_tag_anomalies = []
    salvage_strong = []
    salvage_review = []
    deterministic_or_hold = []
    hold_false_negative = []

    for row in rows:
        p = parsed(row)
        if not row.get("parse_ok"):
            parse_failures.append(compact_row(row, "parse_failure"))
            continue
        action = str(p.get("recommended_action") or "missing")
        failure = str(p.get("failure_cause") or "missing")
        category = str(row.get("category") or "missing")
        action_counts[action] += 1
        failure_counts[failure] += 1
        category_action_counts[f"{category}|{action}"] += 1

        salvage = classify_salvage(row)
        if salvage:
            bucket, reason = salvage
            item = compact_row(row, reason)
            if bucket == "strong":
                salvage_strong.append(item)
            elif bucket == "review":
                salvage_review.append(item)
            else:
                deterministic_or_hold.append(item)

        is_false_negative, reason = is_hold_false_negative(row)
        if is_false_negative:
            hold_false_negative.append(compact_row(row, reason))

        if has_action_label_scene_tags(row):
            action_tag_anomalies.append(compact_row(row, "scene_tags_contains_action_labels"))

    total_rows = len(rows)
    parsed_rows = total_rows - len(parse_failures)
    suspicious_salvage = len(salvage_review) + len(deterministic_or_hold)
    qwen_total = action_counts.get("qwen_salvage", 0)
    suspicious_ratio = suspicious_salvage / qwen_total if qwen_total else 0.0

    return {
        "schema_version": "gpt_oss_queue_audit.v1",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_report": report.get("manifest_jsonl") or report.get("extract_roots"),
        "samples_selected": report.get("samples_selected"),
        "parse_rate": report.get("parse_rate"),
        "analysis_leak_after_sanitize_count": report.get("analysis_leak_after_sanitize_count"),
        "total_rows": total_rows,
        "parsed_rows": parsed_rows,
        "action_counts": dict(action_counts),
        "failure_counts": dict(failure_counts),
        "category_action_counts": dict(category_action_counts),
        "salvage_strong_count": len(salvage_strong),
        "salvage_review_count": len(salvage_review),
        "deterministic_or_hold_count": len(deterministic_or_hold),
        "hold_false_negative_review_count": len(hold_false_negative),
        "parse_failure_count": len(parse_failures),
        "action_tag_anomaly_count": len(action_tag_anomalies),
        "suspicious_salvage_ratio": round(suspicious_ratio, 4),
        "expansion_note": expansion_note(report, suspicious_ratio, len(hold_false_negative), len(action_tag_anomalies)),
        "queues": {
            "qwen_salvage_strong": salvage_strong,
            "qwen_salvage_review": salvage_review,
            "deterministic_or_hold_review": deterministic_or_hold,
            "hold_false_negative_review": hold_false_negative,
            "parse_failures": parse_failures,
            "action_tag_anomalies": action_tag_anomalies,
        },
    }


def expansion_note(
    report: dict[str, Any],
    suspicious_salvage_ratio: float,
    false_negative_count: int,
    action_tag_anomaly_count: int,
) -> str:
    parse_rate = float(report.get("parse_rate") or 0.0)
    leaks = int(report.get("analysis_leak_after_sanitize_count") or 0)
    if parse_rate < 0.95 or leaks:
        return "do_not_expand_parse_gate_failed"
    if suspicious_salvage_ratio > 0.5:
        return "expand_with_salvage_review_split"
    if false_negative_count > 0:
        return "expand_but_review_hold_false_negatives"
    if action_tag_anomaly_count > 0:
        return "expand_but_ignore_scene_tags_for_actions"
    return "expand_allowed"


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def write_markdown(path: Path, result: dict[str, Any]) -> None:
    lines = [
        "# GPT-OSS Queue Audit Report",
        "",
        f"Generated: {result['generated_at']}",
        "",
        "## Summary",
        "",
        f"- samples_selected: `{result.get('samples_selected')}`",
        f"- parse_rate: `{result.get('parse_rate')}`",
        f"- analysis_leak_after_sanitize_count: `{result.get('analysis_leak_after_sanitize_count')}`",
        f"- expansion_note: `{result['expansion_note']}`",
        "",
        "## Counts",
        "",
        f"- qwen_salvage_strong: `{result['salvage_strong_count']}`",
        f"- qwen_salvage_review: `{result['salvage_review_count']}`",
        f"- deterministic_or_hold_review: `{result['deterministic_or_hold_count']}`",
        f"- hold_false_negative_review: `{result['hold_false_negative_review_count']}`",
        f"- parse_failures: `{result['parse_failure_count']}`",
        f"- action_tag_anomalies: `{result['action_tag_anomaly_count']}`",
        f"- suspicious_salvage_ratio: `{result['suspicious_salvage_ratio']}`",
        "",
        "## Action Counts",
        "",
    ]
    for key, count in sorted(result["action_counts"].items()):
        lines.append(f"- `{key}`: {count}")
    lines.extend(["", "## Failure Counts", ""])
    for key, count in sorted(result["failure_counts"].items()):
        lines.append(f"- `{key}`: {count}")
    lines.extend(["", "## Notes", ""])
    lines.append("- `scene_tags` can contain action labels in GPT-OSS output; downstream logic must not treat them as canonical music tags.")
    lines.append("- `hold_false_negative_review` rows are review candidates only, not automatic salvage approvals.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> dict[str, Any]:
    report = read_json(Path(args.report_json))
    result = audit(report)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    full_json = {key: value for key, value in result.items() if key != "queues"}
    (out_dir / "gpt_oss_queue_audit.json").write_text(
        json.dumps(full_json, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    for name, rows in result["queues"].items():
        write_jsonl(out_dir / f"{name}.jsonl", rows)
    write_markdown(out_dir / "GPT_OSS_QUEUE_AUDIT_REPORT.md", result)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-json", required=True)
    parser.add_argument("--out-dir", required=True)
    return parser.parse_args()


def main() -> None:
    result = run(parse_args())
    print(json.dumps({key: value for key, value in result.items() if key != "queues"}, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
