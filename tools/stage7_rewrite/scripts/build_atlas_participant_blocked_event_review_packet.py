#!/usr/bin/env python3
"""Build a review packet for blocked Atlas participant-delta events.

This is a report-only helper for the DJ-first serving graph line. It reads the
bounded blocked-event queue emitted by the information-gap closure step and
adds deterministic review guidance. It does not mutate source/serving SQLite,
call models, use network, or promote rows.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


DEFAULT_BLOCKED_EVENTS = Path("reports/atlas_serving_information_gap_closure_20260523/participant_delta_blocked_events.jsonl")
DEFAULT_OUT_DIR = Path("reports/atlas_participant_blocked_event_review_packet_20260523")
SCHEMA_VERSION = "atlas_participant_blocked_event_review_packet.v1"

MUSIC_TERMS = {
    "dj",
    "techno",
    "house",
    "bass",
    "hiphop",
    "hip hop",
    "jazz",
    "groove",
    "psy",
    "pulse",
    "rave",
    "club",
    "klub",
    "vinyl",
    "festival",
    "fest",
    "live",
    "party",
    "deep west",
    "蹦迪",
    "派对",
    "派對",
    "电子",
    "电音",
    "音乐",
    "音樂",
    "爵士",
    "律动",
    "舞池",
    "锐舞",
    "摇滚",
    "黑胶",
    "黑膠",
}
HARD_REJECT_BUCKETS = {"hard_admin_noise", "hard_non_music_noise"}
HOLD_BUCKETS = {"schedule_without_venue_review", "market_tasting_admin_review"}
PRODUCT_REVIEW_BUCKETS = {"product_noise_filter_review", "possible_music_event_manual_review"}
RAW_LEAK_TOKENS = ("http://", "https://", "mp.weixin.qq.com", "openid=", "fakeid=", "unionid=", "D:/", "D:\\", "C:/", "C:\\", "/mnt/d/", "/mnt/c/", "\\\\wsl")


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def text(value: Any) -> str:
    return str(value or "").strip()


def norm(value: Any) -> str:
    return text(value).casefold()


def int_value(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def float_value(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def has_music_signal(*values: Any) -> bool:
    haystack = " ".join(norm(value) for value in values if text(value))
    return any(term.casefold() in haystack for term in MUSIC_TERMS)


def leak_hits(payload: Any) -> int:
    raw = json.dumps(payload, ensure_ascii=False)
    return sum(1 for token in RAW_LEAK_TOKENS if token in raw)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.strip():
                continue
            value = json.loads(line)
            if isinstance(value, dict):
                rows.append(value)
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text_value = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text_value)
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


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(value)
        tmp = Path(handle.name)
    tmp.replace(path)


def classify(row: dict[str, Any]) -> dict[str, Any]:
    bucket = text(row.get("review_bucket"))
    participants = int_value(row.get("participant_delta_count"))
    confidence = float_value(row.get("confidence"))
    title = text(row.get("event_title"))
    venue = text(row.get("venue_name"))
    time_text = text(row.get("time_text"))
    music_signal = has_music_signal(title, venue)
    has_time = bool(text(row.get("starts_at")) or time_text)
    has_venue = bool(venue)

    score = 0
    score += min(participants, 6) * 2
    score += 4 if confidence >= 0.95 else 2 if confidence >= 0.9 else 0
    score += 4 if music_signal else 0
    score += 2 if has_time else 0
    score += 2 if has_venue else 0

    if bucket in HARD_REJECT_BUCKETS:
        action = "reject_hard_noise"
        reason = "hard admin or non-music bucket"
    elif bucket in HOLD_BUCKETS and not music_signal:
        action = "hold_review_only"
        reason = "market/tasting/schedule bucket lacks strong public music signal"
    elif bucket in PRODUCT_REVIEW_BUCKETS and music_signal and participants >= 2 and confidence >= 0.9:
        action = "manual_review_candidate"
        reason = "music signal plus participant/time/venue evidence requires source review before any public merge"
    elif music_signal and participants >= 3 and confidence >= 0.9:
        action = "manual_review_candidate"
        reason = "music signal survives product-noise bucket but still needs source review"
    else:
        action = "hold_review_only"
        reason = "insufficient public-safe evidence for automatic promotion"

    return {
        "schema_version": f"{SCHEMA_VERSION}.decision_row",
        "event_id": text(row.get("event_id")),
        "event_title": title,
        "venue_name": venue,
        "city": text(row.get("city")),
        "time_text": time_text,
        "source_ref_id": text(row.get("source_ref_id")),
        "participant_delta_count": participants,
        "confidence": confidence,
        "review_bucket": bucket,
        "noise_terms": row.get("noise_terms") or [],
        "music_signal": music_signal,
        "has_time": has_time,
        "has_venue": has_venue,
        "review_score": score,
        "review_action": action,
        "review_reason": reason,
        "public_promotion_recommendation": "source_review_required_no_auto_merge" if action == "manual_review_candidate" else "do_not_promote_without_new_evidence",
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Atlas Participant Blocked Event Review Packet",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- decision: `{report['decision']}`",
        f"- input_rows: `{report['input_rows']}`",
        f"- raw_leak_hits: `{report['raw_leak_hits']}`",
        "",
        "## Review Actions",
        "",
    ]
    for key, value in sorted(report["review_action_counts"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Review Buckets", ""])
    for key, value in sorted(report["review_bucket_counts"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Top Manual Review Candidates", ""])
    for row in report["top_manual_review_candidates"]:
        lines.append(
            "- `{event_id}` score `{score}` participants `{participants}` confidence `{confidence}`: {title} @ {venue}".format(
                event_id=row["event_id"],
                score=row["review_score"],
                participants=row["participant_delta_count"],
                confidence=row["confidence"],
                title=row["event_title"],
                venue=row["venue_name"] or "unknown venue",
            )
        )
    lines.extend(["", "## Safety", ""])
    for key, value in sorted(report["boundary"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.append("")
    return "\n".join(lines)


def build_packet(blocked_events_path: Path, out_dir: Path) -> dict[str, Any]:
    rows = read_jsonl(blocked_events_path)
    decisions = [classify(row) for row in rows]
    decisions.sort(key=lambda row: (row["review_action"] != "manual_review_candidate", -row["review_score"], row["event_id"]))
    raw_leak_hits = leak_hits(decisions)
    action_counts = Counter(row["review_action"] for row in decisions)
    bucket_counts = Counter(row["review_bucket"] for row in decisions)
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": "blocked_event_review_packet_ready_report_only",
        "blocked_events_path": str(blocked_events_path),
        "input_rows": len(rows),
        "raw_leak_hits": raw_leak_hits,
        "review_action_counts": dict(action_counts),
        "review_bucket_counts": dict(bucket_counts),
        "top_manual_review_candidates": [row for row in decisions if row["review_action"] == "manual_review_candidate"][:12],
        "outputs": {
            "summary_json": str(out_dir / "blocked_event_review_packet.json"),
            "summary_md": str(out_dir / "blocked_event_review_packet.md"),
            "decisions_jsonl": str(out_dir / "blocked_event_review_decisions.jsonl"),
        },
        "boundary": {
            "llm_call_executed": False,
            "network_call_executed": False,
            "source_sqlite_write_executed": False,
            "serving_sqlite_write_executed": False,
            "production_pointer_update_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "cloudrun_deploy_executed": False,
        },
    }
    write_json(out_dir / "blocked_event_review_packet.json", report)
    write_jsonl(out_dir / "blocked_event_review_decisions.jsonl", decisions)
    write_text(out_dir / "blocked_event_review_packet.md", render_markdown(report))
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blocked-events", type=Path, default=DEFAULT_BLOCKED_EVENTS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_packet(args.blocked_events, args.out_dir)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
