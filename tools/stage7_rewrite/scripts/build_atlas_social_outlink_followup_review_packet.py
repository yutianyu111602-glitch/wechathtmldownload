#!/usr/bin/env python3
"""Build a report-only review packet from Atlas social outlink follow-up rows.

The input queue is produced by expand_atlas_social_profile_outlinks.py. This
gate compresses high-volume SoundCloud/Bandcamp/etc. candidate links into
human/T5-reviewable buckets without fetching pages or promoting graph truth.
"""
from __future__ import annotations

import argparse
import json
import re
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib import parse


STAGE7_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FOLLOWUP_QUEUE = (
    STAGE7_ROOT
    / "reports"
    / "atlas_social_profile_outlinks_q6_20260523_1815_http"
    / "atlas_social_outlink_followup_queue.jsonl"
)
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_social_outlink_followup_review_q6_20260523"
SCHEMA_VERSION = "stage7_atlas_social_outlink_followup_review.v1"

PROFILE_KINDS = {"audio_profile", "video_channel_or_profile", "social_crosslink"}
DIRECT_EVIDENCE_PLATFORMS = {"bandcamp", "soundcloud", "mixcloud", "residentadvisor", "beatport"}
LOW_SIGNAL_URL_PARTS = {"/recommended", "/likes", "/reposts"}
LOW_SIGNAL_ANCHOR_PREFIXES = ("more tracks like", "playlists containing")


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").casefold()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for social outlink review: {path}")


def compact(value: Any, limit: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def normalize(value: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", compact(value, 240).casefold())


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_d_path(path, "jsonl")
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
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
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
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


def host_of(url: str) -> str:
    host = parse.urlsplit(compact(url, 3000)).netloc.casefold()
    return host[4:] if host.startswith("www.") else host


def path_of(url: str) -> str:
    return parse.urlsplit(compact(url, 3000)).path.casefold()


def has_subject_match(row: dict[str, Any]) -> bool:
    reasons = row.get("priority_reasons")
    if isinstance(reasons, list) and "subject_match" in reasons:
        return True
    name = compact(row.get("name"))
    if not name:
        return False
    haystack = " ".join(
        [
            compact(row.get("anchor_text")),
            compact(row.get("outlink_url")),
            compact(row.get("profile_url")),
        ]
    )
    normalized_name = normalize(name)
    return len(normalized_name) >= 3 and normalized_name in normalize(haystack)


def is_low_signal(row: dict[str, Any]) -> bool:
    url_path = path_of(compact(row.get("outlink_url")))
    anchor = compact(row.get("anchor_text")).casefold()
    if any(part in url_path for part in LOW_SIGNAL_URL_PARTS):
        return True
    return any(anchor.startswith(prefix) for prefix in LOW_SIGNAL_ANCHOR_PREFIXES)


def review_decision(row: dict[str, Any]) -> tuple[str, list[str], int]:
    platform = compact(row.get("outlink_platform")).casefold()
    kind = compact(row.get("outlink_kind")).casefold()
    score = int(row.get("priority_score") or 0)
    subject_match = has_subject_match(row)
    low_signal = is_low_signal(row)
    reasons: list[str] = []

    if low_signal:
        reasons.append("low_signal_recommendation_or_playlist_container")
        return "deprioritize_low_signal_music_container", reasons, max(score - 35, 0)
    if platform not in DIRECT_EVIDENCE_PLATFORMS and kind not in PROFILE_KINDS:
        reasons.append("platform_is_not_primary_music_identity_evidence")
        return "manual_review_secondary_platform_candidate", reasons, max(score - 10, 0)
    if kind in PROFILE_KINDS and subject_match:
        reasons.extend(["profile_like_link", "subject_match"])
        return "manual_review_direct_profile_candidate", reasons, score + 10
    if kind in {"audio_track_candidate", "audio_collection_or_mixtape", "event_candidate"} and subject_match:
        reasons.extend(["music_artifact_link", "subject_match"])
        return "manual_review_music_artifact_candidate", reasons, score
    if subject_match:
        reasons.append("subject_match")
        return "manual_review_subject_matched_candidate", reasons, score
    reasons.append("no_subject_match_signal")
    return "needs_stronger_subject_context_before_fetch", reasons, max(score - 20, 0)


def review_row(row: dict[str, Any], rank: int) -> dict[str, Any]:
    decision, decision_reasons, review_score = review_decision(row)
    return {
        "schema_version": SCHEMA_VERSION + ".row",
        "reviewed_at": now_iso(),
        "review_rank": rank,
        "review_decision": decision,
        "review_score": review_score,
        "decision_reasons": decision_reasons,
        "entity_search_id": compact(row.get("entity_search_id")),
        "queue_index": row.get("queue_index"),
        "name": compact(row.get("name")),
        "type": compact(row.get("type")),
        "outlink_id": compact(row.get("outlink_id")),
        "outlink_platform": compact(row.get("outlink_platform")),
        "outlink_kind": compact(row.get("outlink_kind")),
        "outlink_host": host_of(compact(row.get("outlink_url"))),
        "outlink_url": compact(row.get("outlink_url"), 3000),
        "anchor_text": compact(row.get("anchor_text"), 500),
        "profile_platform": compact(row.get("profile_platform")),
        "profile_url": compact(row.get("profile_url"), 3000),
        "source_layer": compact(row.get("source_layer")),
        "source_priority_score": row.get("priority_score"),
        "source_priority_reasons": row.get("priority_reasons") if isinstance(row.get("priority_reasons"), list) else [],
        "next_action": "manual_review_or_bounded_content_fetch",
        "review_required": True,
        "accepted_for_graph": False,
        "identity_proof": False,
        "graph_write_allowed": False,
    }


def build_review_packet(*, followup_queue_path: Path, out_dir: Path, top_limit: int = 80) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    input_rows = read_jsonl(followup_queue_path)
    sorted_input = sorted(
        input_rows,
        key=lambda row: (
            int(row.get("priority_score") or 0),
            compact(row.get("outlink_platform")),
            compact(row.get("outlink_kind")),
            compact(row.get("name")),
        ),
        reverse=True,
    )
    reviewed_rows = [review_row(row, index + 1) for index, row in enumerate(sorted_input)]
    reviewed_rows.sort(
        key=lambda row: (
            int(row.get("review_score") or 0),
            compact(row.get("outlink_platform")),
            compact(row.get("outlink_kind")),
            compact(row.get("name")),
        ),
        reverse=True,
    )
    for index, row in enumerate(reviewed_rows, start=1):
        row["review_rank"] = index
    top_rows = reviewed_rows[: max(top_limit, 0)]

    decision_counts = Counter(row["review_decision"] for row in reviewed_rows)
    platform_counts = Counter(row["outlink_platform"] for row in reviewed_rows)
    kind_counts = Counter(row["outlink_kind"] for row in reviewed_rows)
    entity_counts = Counter(row["name"] for row in reviewed_rows)
    per_entity: dict[str, dict[str, Any]] = defaultdict(lambda: {"rows": 0, "platforms": Counter(), "top_score": 0})
    for row in reviewed_rows:
        item = per_entity[row["name"]]
        item["rows"] += 1
        item["platforms"][row["outlink_platform"]] += 1
        item["top_score"] = max(item["top_score"], row["review_score"])

    review_path = out_dir / "atlas_social_outlink_followup_review_rows.jsonl"
    top_path = out_dir / "atlas_social_outlink_followup_top_review_queue.jsonl"
    accepted_path = out_dir / "accepted_social_identity_edges_for_graph.jsonl"
    entity_rollup_path = out_dir / "atlas_social_outlink_followup_entity_rollup.jsonl"

    entity_rollup_rows = [
        {
            "schema_version": SCHEMA_VERSION + ".entity_rollup",
            "name": name,
            "rows": data["rows"],
            "platform_counts": dict(data["platforms"]),
            "top_review_score": data["top_score"],
            "accepted_for_graph": False,
            "identity_proof": False,
            "graph_write_allowed": False,
        }
        for name, data in sorted(per_entity.items(), key=lambda item: (item[1]["top_score"], item[1]["rows"]), reverse=True)
    ]

    write_jsonl(review_path, reviewed_rows)
    write_jsonl(top_path, top_rows)
    write_jsonl(accepted_path, [])
    write_jsonl(entity_rollup_path, entity_rollup_rows)

    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": True,
        "decision": "atlas_social_outlink_followup_review_ready_no_graph_acceptance",
        "followup_queue_path": str(followup_queue_path),
        "review_rows_path": str(review_path),
        "top_review_queue_path": str(top_path),
        "entity_rollup_path": str(entity_rollup_path),
        "accepted_edges_path": str(accepted_path),
        "input_rows": len(input_rows),
        "reviewed_rows": len(reviewed_rows),
        "top_review_rows": len(top_rows),
        "entity_count": len(per_entity),
        "accepted_for_graph": 0,
        "identity_proof_promoted": 0,
        "graph_write_allowed": 0,
        "decision_counts": dict(decision_counts),
        "platform_counts": dict(platform_counts),
        "kind_counts": dict(kind_counts),
        "safety": {
            "report_only": True,
            "network_call_executed": False,
            "model_call_executed": False,
            "paid_api_used": False,
            "graph_write_executed": False,
            "qdrant_write_executed": False,
            "neo4j_write_executed": False,
            "sqlite_write_executed": False,
            "mem0_write_executed": False,
            "d_scan_executed": False,
        },
    }
    write_json(out_dir / "atlas_social_outlink_followup_review_summary.json", summary)
    write_markdown(out_dir / "atlas_social_outlink_followup_review_summary.md", summary)
    return summary


def write_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# Atlas Social Outlink Follow-Up Review Packet",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{summary['decision']}`",
        f"- input_rows: `{summary['input_rows']}`",
        f"- reviewed_rows: `{summary['reviewed_rows']}`",
        f"- top_review_rows: `{summary['top_review_rows']}`",
        f"- entity_count: `{summary['entity_count']}`",
        f"- accepted_for_graph: `{summary['accepted_for_graph']}`",
        f"- identity_proof_promoted: `{summary['identity_proof_promoted']}`",
        f"- graph_write_allowed: `{summary['graph_write_allowed']}`",
        f"- review_rows_path: `{summary['review_rows_path']}`",
        f"- top_review_queue_path: `{summary['top_review_queue_path']}`",
        f"- entity_rollup_path: `{summary['entity_rollup_path']}`",
        f"- accepted_edges_path: `{summary['accepted_edges_path']}`",
        "",
        "## Decision Counts",
        "",
    ]
    for key, value in sorted(summary["decision_counts"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Platform Counts", ""])
    for key, value in sorted(summary["platform_counts"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Report-only review packet.",
            "- No network/model/paid API call was executed by this gate.",
            "- No graph, Qdrant, Neo4j, SQLite production, mem0, or agentmemory write was executed.",
            "- Accepted graph edge output is intentionally empty.",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--followup-queue", type=Path, default=DEFAULT_FOLLOWUP_QUEUE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--top-limit", type=int, default=80)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_review_packet(
        followup_queue_path=args.followup_queue,
        out_dir=args.out_dir,
        top_limit=args.top_limit,
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
