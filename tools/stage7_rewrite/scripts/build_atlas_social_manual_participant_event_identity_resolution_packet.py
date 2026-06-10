#!/usr/bin/env python3
"""Build a report-only resolution packet for blocked Q6 manual event identity rows."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE7_ROOT.parents[1]
DEFAULT_INPUT = (
    STAGE7_ROOT
    / "reports"
    / "atlas_social_manual_participant_blocker_recovery_q6_20260526"
    / "manual_event_identity_review_work_orders.jsonl"
)
DEFAULT_OUT_DIR = (
    STAGE7_ROOT
    / "reports"
    / "atlas_social_manual_participant_event_identity_resolution_q6_20260526"
)
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T6_MANUAL_PARTICIPANT_EVENT_IDENTITY_RESOLUTION_PACKET_20260526.md"
SCHEMA_VERSION = "stage7_atlas_social_manual_participant_event_identity_resolution.v1"

URL_RE = re.compile(r"https?://", re.I)
SECRET_RE = re.compile(r"\b(secret|token|cookie|password|api[_-]?key|authorization|bearer)\b", re.I)
LOCAL_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"']+|/mnt/[A-Za-z][^\s\"']*|/home/[^\s\"']+|\\\\[A-Za-z0-9_.-]+[\\/][^\s\"']+",
    re.I,
)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def compact(value: Any, limit: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").casefold()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for event identity resolution: {path}")


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return path.name


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


def stable_id(prefix: str, parts: Iterable[Any]) -> str:
    raw = "|".join(compact(part, 800) for part in parts)
    return f"{prefix}:{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}"


def normalize_text(value: Any) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", compact(value, 1000).casefold())


def canonical_venue(value: Any) -> str:
    normalized = normalize_text(value)
    if "thebox" in normalized and "dada" in normalized:
        return "multi_venue_the_box_dada"
    if "dada" in normalized and ("beijing" in normalized or "北京" in normalized):
        return "dada_beijing"
    if "dada" in normalized and ("kunming" in normalized or "昆明" in normalized):
        return "dada_kunming"
    if "oil" in normalized:
        return "oil"
    if "thebox" in normalized and "dada" not in normalized:
        return "the_box"
    return normalized


def parse_date(value: Any) -> date | None:
    text = compact(value, 32)
    match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", text)
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def title_date_candidates(title: Any, post_date: Any) -> list[str]:
    source_date = parse_date(post_date)
    if not source_date:
        return []
    values: set[str] = set()
    text = compact(title, 1000)
    for match in re.finditer(r"(\d{1,2})月\s*(\d{1,2})日", text):
        month, day = int(match.group(1)), int(match.group(2))
        add_year_adjusted_title_date(values, source_date, month, day)
    for match in re.finditer(r"(?<!\d)(\d{1,2})/(\d{1,2})(?!\d)", text):
        month, day = int(match.group(1)), int(match.group(2))
        add_year_adjusted_title_date(values, source_date, month, day)
    if "今晚" in text:
        values.add(source_date.isoformat())
    return sorted(values)


def add_year_adjusted_title_date(values: set[str], source_date: date, month: int, day: int) -> None:
    candidates: list[date] = []
    for year in (source_date.year - 1, source_date.year, source_date.year + 1):
        try:
            candidates.append(date(year, month, day))
        except ValueError:
            continue
    if not candidates:
        return
    # Prefer an event date in the same announcement year, but allow year rollover
    # when the month/day is near the source date and the same-year value is implausible.
    same_year = [item for item in candidates if item.year == source_date.year]
    selected = same_year[0] if same_year else min(candidates, key=lambda item: abs((item - source_date).days))
    if (selected - source_date).days < -180:
        selected = date(source_date.year + 1, month, day)
    values.add(selected.isoformat())


def cluster_signature(cluster: dict[str, Any]) -> dict[str, Any]:
    event_ids = [compact(item, 120) for item in cluster.get("event_ids", []) if compact(item, 120)]
    return {
        "cluster_id": compact(cluster.get("cluster_id"), 120),
        "starts_at": compact(cluster.get("starts_at"), 40),
        "city_sample": compact(cluster.get("city_sample"), 80),
        "venue_name_sample": compact(cluster.get("venue_name_sample"), 160),
        "canonical_venue": canonical_venue(cluster.get("venue_name_sample")),
        "event_title_sample": compact(cluster.get("event_title_sample"), 260),
        "event_ids": event_ids,
        "event_id_count": int(number(cluster.get("event_id_count")) or len(event_ids)),
        "candidate_rows": int(number(cluster.get("candidate_rows"))),
        "max_event_match_score": round(number(cluster.get("max_event_match_score")), 4),
        "max_participant_count": int(number(cluster.get("max_participant_count"))),
        "source_ref_ids": [compact(item, 120) for item in cluster.get("source_ref_ids", []) if compact(item, 120)][:8],
    }


def representative_event_id(clusters: list[dict[str, Any]]) -> str:
    candidates: list[tuple[int, int, float, str]] = []
    for cluster in clusters:
        for event_id in cluster.get("event_ids", []):
            candidates.append(
                (
                    int(number(cluster.get("max_participant_count"))),
                    int(number(cluster.get("candidate_rows"))),
                    number(cluster.get("max_event_match_score")),
                    compact(event_id, 120),
                )
            )
    if not candidates:
        return ""
    candidates.sort(key=lambda item: (-item[0], -item[1], -item[2], item[3]))
    return candidates[0][3]


def closed_flags() -> dict[str, bool | str]:
    return {
        "accepted_for_graph": False,
        "source_sqlite_write_allowed": False,
        "serving_rebuild_allowed": False,
        "graph_write_allowed": False,
        "public_serving_field_allowed": False,
        "memory_write_allowed": False,
        "write_status": "report_only",
    }


def selector_hash(payload: dict[str, Any]) -> str:
    material = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def selected_payload(row: dict[str, Any], selected_clusters: list[dict[str, Any]], resolution_lane: str) -> dict[str, Any]:
    event_ids = sorted({event_id for cluster in selected_clusters for event_id in cluster.get("event_ids", [])})
    cluster_ids = sorted({compact(cluster.get("cluster_id"), 120) for cluster in selected_clusters if compact(cluster.get("cluster_id"), 120)})
    source_ref_ids = sorted(
        {
            compact(row.get("source_ref_id"), 120),
            *[
                compact(item, 120)
                for cluster in selected_clusters
                for item in cluster.get("source_ref_ids", [])
                if compact(item, 120)
            ],
        }
        - {""}
    )
    payload = {
        "resolution_lane": resolution_lane,
        "source_account": compact(row.get("source_account"), 220),
        "article_uid": compact(row.get("article_uid"), 260),
        "source_ref_id": compact(row.get("source_ref_id"), 120),
        "source_hash": compact(row.get("source_hash"), 120),
        "post_date": compact(row.get("post_date"), 40),
        "event_ids": event_ids,
        "cluster_ids": cluster_ids,
        "source_ref_ids": source_ref_ids,
        "representative_event_id_review_only": representative_event_id(selected_clusters),
    }
    payload["selector_hash"] = selector_hash(payload)
    return payload


def resolve_row(row: dict[str, Any], generated_at: str) -> dict[str, Any]:
    clusters = [
        cluster_signature(cluster)
        for cluster in row.get("semantic_event_clusters", [])
        if isinstance(cluster, dict)
    ]
    blocker_status = compact(row.get("blocker_status"), 120)
    derived_dates = title_date_candidates(row.get("title"), row.get("post_date"))
    selected_clusters: list[dict[str, Any]] = []
    resolution_lane = "still_blocked_manual_event_identity"
    resolution_status = "manual_event_identity_still_blocked_report_only"
    resolution_reason = "manual_source_or_ocr_review_required"

    if blocker_status == "blocked_conflicting_event_dates":
        matches = [cluster for cluster in clusters if cluster.get("starts_at") in derived_dates]
        if len(matches) == 1:
            selected_clusters = matches
            resolution_lane = "date_resolved_consolidation_candidate"
            resolution_status = "date_resolved_consolidation_candidate_report_only"
            resolution_reason = "single_candidate_cluster_matches_title_date_in_source_post_year"
        elif len(matches) > 1:
            resolution_reason = "multiple_candidate_clusters_match_title_date"
        else:
            resolution_reason = "no_candidate_cluster_matches_title_date"
    elif blocker_status == "blocked_conflicting_city_or_venue":
        canonical_venues = {cluster.get("canonical_venue") for cluster in clusters if cluster.get("canonical_venue")}
        starts_at_values = {cluster.get("starts_at") for cluster in clusters if cluster.get("starts_at")}
        multi_venue = any(str(venue).startswith("multi_venue") for venue in canonical_venues)
        if len(canonical_venues) == 1 and len(starts_at_values) <= 1 and not multi_venue:
            selected_clusters = clusters
            resolution_lane = "venue_alias_resolved_consolidation_candidate"
            resolution_status = "venue_alias_resolved_consolidation_candidate_report_only"
            resolution_reason = "all_candidate_venues_canonicalize_to_one_alias"
        elif multi_venue:
            resolution_reason = "candidate_contains_multi_venue_context"
        else:
            resolution_reason = "candidate_venues_do_not_canonicalize_to_one_alias"
    elif blocker_status == "blocked_low_title_similarity":
        resolution_reason = "title_similarity_still_requires_manual_review"

    selector = selected_payload(row, selected_clusters, resolution_lane) if selected_clusters else {}
    event_ids = selector.get("event_ids", []) if selector else []
    return {
        "schema_version": SCHEMA_VERSION + ".row",
        "generated_at": generated_at,
        "resolution_id": stable_id(
            "eventidentity",
            [row.get("recovery_work_order_id"), row.get("article_uid"), blocker_status, resolution_status],
        ),
        "upstream_recovery_work_order_id": compact(row.get("recovery_work_order_id"), 120),
        "source_account": compact(row.get("source_account"), 220),
        "article_uid": compact(row.get("article_uid"), 260),
        "work_item_id": compact(row.get("work_item_id"), 120),
        "rank": int(number(row.get("rank"))),
        "title": compact(row.get("title"), 520),
        "name": compact(row.get("name"), 320),
        "post_date": compact(row.get("post_date"), 40),
        "source_ref_id": compact(row.get("source_ref_id"), 120),
        "source_hash": compact(row.get("source_hash"), 120),
        "blocker_status": blocker_status,
        "blocking_reason": compact(row.get("blocking_reason"), 520),
        "resolution_lane": resolution_lane,
        "resolution_status": resolution_status,
        "resolution_reason": resolution_reason,
        "derived_title_date_candidates": derived_dates,
        "semantic_event_cluster_count": len(clusters),
        "candidate_rows": int(number(row.get("candidate_rows"))),
        "participant_sample_rows": int(number(row.get("participant_sample_rows"))),
        "selected_event_ids_review_only": event_ids,
        "selected_event_id_count": len(event_ids),
        "representative_event_id_review_only": selector.get("representative_event_id_review_only", "") if selector else "",
        "selected_semantic_event_clusters": selected_clusters[:8],
        "all_semantic_event_clusters": clusters[:8],
        "deterministic_selector": selector,
        "selector_hash": selector.get("selector_hash", "") if selector else "",
        "manual_review_required": resolution_status == "manual_event_identity_still_blocked_report_only",
        "next_gate": (
            "Feed candidate rows into a DB-backed consolidation/readback packet before any source, serving, graph, public, or memory mutation."
            if selected_clusters
            else "Recover stronger source/OCR/manual evidence before consolidation."
        ),
        **closed_flags(),
    }


def dedupe_candidates(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[compact(row.get("selector_hash"), 80)].append(row)
    deduped: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    for selector, group in sorted(groups.items()):
        if not selector:
            continue
        group_sorted = sorted(group, key=lambda item: (int(item.get("rank") or 0), item.get("resolution_id", "")))
        winner = dict(group_sorted[0])
        winner["duplicate_selector_input_rows"] = len(group_sorted)
        winner["duplicate_selector_collapsed"] = len(group_sorted) > 1
        deduped.append(winner)
        if len(group_sorted) > 1:
            duplicates.append(
                {
                    "schema_version": SCHEMA_VERSION + ".duplicate_selector",
                    "selector_hash": selector,
                    "duplicate_selector_input_rows": len(group_sorted),
                    "kept_resolution_id": winner["resolution_id"],
                    "collapsed_resolution_ids": [item["resolution_id"] for item in group_sorted[1:]],
                    "source_account": winner.get("source_account", ""),
                    "article_uid": winner.get("article_uid", ""),
                    "resolution_lane": winner.get("resolution_lane", ""),
                    **closed_flags(),
                }
            )
    return deduped, duplicates


def scan_payload(rows: list[dict[str, Any]]) -> dict[str, int]:
    text = "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows)
    return {
        "public_url_hits": len(URL_RE.findall(text)),
        "sensitive_key_hits": len(SECRET_RE.findall(text)),
        "local_path_hits": len(LOCAL_PATH_RE.findall(text)),
    }


def build_event_identity_resolution_packet(input_path: Path, out_dir: Path, report_path: Path) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    generated_at = now_iso()
    input_rows = read_jsonl(input_path)
    rows = [resolve_row(row, generated_at) for row in input_rows]
    candidates = [row for row in rows if row["resolution_status"] != "manual_event_identity_still_blocked_report_only"]
    date_candidates = [row for row in candidates if row["resolution_lane"] == "date_resolved_consolidation_candidate"]
    venue_candidates = [row for row in candidates if row["resolution_lane"] == "venue_alias_resolved_consolidation_candidate"]
    still_blocked = [row for row in rows if row["resolution_status"] == "manual_event_identity_still_blocked_report_only"]
    deduped_candidates, duplicate_rows = dedupe_candidates(candidates)

    batches: list[dict[str, Any]] = []
    by_account: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_account[row["source_account"]].append(row)
    for account, account_rows in sorted(by_account.items()):
        status_counts = Counter(row["resolution_status"] for row in account_rows)
        lane_counts = Counter(row["resolution_lane"] for row in account_rows)
        batches.append(
            {
                "schema_version": SCHEMA_VERSION + ".source_account_batch",
                "generated_at": generated_at,
                "source_account": account,
                "input_rows": len(account_rows),
                "resolution_candidate_rows": sum(
                    1 for row in account_rows if row["resolution_status"] != "manual_event_identity_still_blocked_report_only"
                ),
                "still_blocked_rows": sum(
                    1 for row in account_rows if row["resolution_status"] == "manual_event_identity_still_blocked_report_only"
                ),
                "resolution_status_counts": dict(sorted(status_counts.items())),
                "resolution_lane_counts": dict(sorted(lane_counts.items())),
                **closed_flags(),
            }
        )

    safety_rows = rows + duplicate_rows + batches
    leak_scan = scan_payload(safety_rows)
    failed_checks = [key for key, value in leak_scan.items() if value]
    decision = (
        "atlas_social_manual_participant_event_identity_resolution_failed_safety_scan"
        if failed_checks
        else "atlas_social_manual_participant_event_identity_resolution_candidates_ready_report_only"
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "resolution_rows_jsonl": out_dir / "manual_event_identity_resolution_rows.jsonl",
        "resolution_candidates_jsonl": out_dir / "manual_event_identity_resolution_candidates.jsonl",
        "resolution_candidates_deduped_jsonl": out_dir / "manual_event_identity_resolution_candidates_deduped.jsonl",
        "date_candidates_jsonl": out_dir / "date_resolved_consolidation_candidates.jsonl",
        "venue_alias_candidates_jsonl": out_dir / "venue_alias_resolved_consolidation_candidates.jsonl",
        "still_blocked_jsonl": out_dir / "still_blocked_manual_event_identity_rows.jsonl",
        "duplicate_selectors_jsonl": out_dir / "duplicate_selector_collapsed_rows.jsonl",
        "source_account_batches_jsonl": out_dir / "source_account_event_identity_batches.jsonl",
        "summary_json": out_dir / "manual_event_identity_resolution_summary.json",
        "summary_md": out_dir / "manual_event_identity_resolution_summary.md",
    }

    write_jsonl(paths["resolution_rows_jsonl"], rows)
    write_jsonl(paths["resolution_candidates_jsonl"], candidates)
    write_jsonl(paths["resolution_candidates_deduped_jsonl"], deduped_candidates)
    write_jsonl(paths["date_candidates_jsonl"], date_candidates)
    write_jsonl(paths["venue_alias_candidates_jsonl"], venue_candidates)
    write_jsonl(paths["still_blocked_jsonl"], still_blocked)
    write_jsonl(paths["duplicate_selectors_jsonl"], duplicate_rows)
    write_jsonl(paths["source_account_batches_jsonl"], batches)

    status_counts = Counter(row["resolution_status"] for row in rows)
    lane_counts = Counter(row["resolution_lane"] for row in rows)
    blocker_counts = Counter(row["blocker_status"] for row in rows)
    reason_counts = Counter(row["resolution_reason"] for row in rows)
    summary = {
        "schema_version": SCHEMA_VERSION + ".summary",
        "generated_at": generated_at,
        "decision": decision,
        "failed_checks": failed_checks,
        "inputs": {"manual_event_identity_work_orders": display_path(input_path)},
        "outputs": {name: display_path(path) for name, path in paths.items()},
        "counts": {
            "input_manual_event_identity_rows": len(input_rows),
            "resolution_rows": len(rows),
            "resolution_candidate_rows": len(candidates),
            "resolution_candidate_deduped_rows": len(deduped_candidates),
            "date_resolved_candidate_rows": len(date_candidates),
            "venue_alias_resolved_candidate_rows": len(venue_candidates),
            "still_blocked_rows": len(still_blocked),
            "duplicate_selector_groups": len(duplicate_rows),
            "source_account_batches": len(batches),
            "accepted_for_graph_rows": 0,
            "source_sqlite_write_allowed_rows": 0,
            "serving_rebuild_allowed_rows": 0,
            "graph_write_allowed_rows": 0,
            "public_serving_field_allowed_rows": 0,
            "memory_write_allowed_rows": 0,
        },
        "resolution_status_counts": dict(sorted(status_counts.items())),
        "resolution_lane_counts": dict(sorted(lane_counts.items())),
        "blocker_status_counts": dict(sorted(blocker_counts.items())),
        "resolution_reason_counts": dict(sorted(reason_counts.items())),
        "source_account_counts": {row["source_account"]: row["input_rows"] for row in batches},
        "leak_scan": leak_scan,
        "safety": {
            "report_only": True,
            "source_sqlite_opened": False,
            "source_sqlite_write_executed": False,
            "serving_sqlite_rebuild_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "production_write_executed": False,
            "network_call_executed": False,
            "model_call_executed": False,
            "memory_write_executed": False,
            "credential_read": False,
            "d_root_scan": False,
            "raw_source_url_emitted": False,
            "raw_local_path_emitted": False,
        },
        "next_resume_cursor": display_path(paths["resolution_candidates_deduped_jsonl"])
        if deduped_candidates
        else display_path(paths["still_blocked_jsonl"]),
        "stop_reason": "report_only_resolution_candidates_need_db_backed_consolidation_gate",
        "wait_reason": (
            "Event identity candidates are deterministic review outputs only; source/raw writes, serving rebuild, graph/vector production, public, and memory gates remain closed."
        ),
    }
    write_json(paths["summary_json"], summary)
    summary_md = render_summary(summary)
    write_text(paths["summary_md"], summary_md)
    write_text(report_path, render_report(summary))
    return summary


def render_summary(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    return "\n".join(
        [
            "# Manual Participant Event Identity Resolution Summary",
            "",
            f"- Decision: `{summary['decision']}`",
            f"- Failed checks: `{json.dumps(summary['failed_checks'], ensure_ascii=False)}`",
            f"- Input rows: `{counts['input_manual_event_identity_rows']}`",
            f"- Candidate rows: `{counts['resolution_candidate_rows']}`; deduped `{counts['resolution_candidate_deduped_rows']}`",
            f"- Date resolved: `{counts['date_resolved_candidate_rows']}`; venue alias resolved: `{counts['venue_alias_resolved_candidate_rows']}`",
            f"- Still blocked: `{counts['still_blocked_rows']}`",
            f"- Leak hits: `{summary['leak_scan']['public_url_hits']}/{summary['leak_scan']['sensitive_key_hits']}/{summary['leak_scan']['local_path_hits']}`",
            f"- Next cursor: `{summary['next_resume_cursor']}`",
            "",
        ]
    )


def render_report(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    outputs = summary["outputs"]
    return "\n".join(
        [
            "# Atlas T6 Manual Participant Event Identity Resolution Packet - 2026-05-26",
            "",
            "Status: `CURRENT_AUTHORITY`",
            "Mode: `report_only`",
            "",
            "## Decision",
            "",
            f"- Decision: `{summary['decision']}`",
            f"- Failed checks: `{json.dumps(summary['failed_checks'], ensure_ascii=False)}`",
            f"- Manual event identity input rows: `{counts['input_manual_event_identity_rows']}`",
            f"- Resolution candidate rows: `{counts['resolution_candidate_rows']}`",
            f"- Deduped candidate rows: `{counts['resolution_candidate_deduped_rows']}`",
            f"- Date-resolved candidate rows: `{counts['date_resolved_candidate_rows']}`",
            f"- Venue-alias-resolved candidate rows: `{counts['venue_alias_resolved_candidate_rows']}`",
            f"- Still blocked rows: `{counts['still_blocked_rows']}`",
            f"- Duplicate selector groups: `{counts['duplicate_selector_groups']}`",
            f"- Source account batches: `{counts['source_account_batches']}`",
            f"- Accepted/write/promotion rows: `{counts['accepted_for_graph_rows']}/{counts['source_sqlite_write_allowed_rows']}/{counts['serving_rebuild_allowed_rows']}/{counts['graph_write_allowed_rows']}/{counts['public_serving_field_allowed_rows']}/{counts['memory_write_allowed_rows']}`",
            f"- Public URL / sensitive-key / local path leak hits: `{summary['leak_scan']['public_url_hits']}` / `{summary['leak_scan']['sensitive_key_hits']}` / `{summary['leak_scan']['local_path_hits']}`",
            "",
            "## Outputs",
            "",
            f"- Summary JSON: `{outputs['summary_json']}`",
            f"- Resolution rows: `{outputs['resolution_rows_jsonl']}`",
            f"- Candidate rows: `{outputs['resolution_candidates_jsonl']}`",
            f"- Deduped candidate rows: `{outputs['resolution_candidates_deduped_jsonl']}`",
            f"- Date-resolved candidates: `{outputs['date_candidates_jsonl']}`",
            f"- Venue-alias candidates: `{outputs['venue_alias_candidates_jsonl']}`",
            f"- Still blocked rows: `{outputs['still_blocked_jsonl']}`",
            f"- Duplicate selector evidence: `{outputs['duplicate_selectors_jsonl']}`",
            f"- Source-account batches: `{outputs['source_account_batches_jsonl']}`",
            "",
            "## Boundary",
            "",
            "- Report-only review over existing redacted JSONL artifacts.",
            "- No SQLite open, OCR execution, model call, network fetch, source/raw Atlas DB write, serving SQLite write or rebuild, public pointer, CloudRun/VPS deploy, Neo4j/Qdrant/SQLite production write, mini-program upload/review, memory write, credential read, 9router use, destructive Git, or D root scan occurred.",
            "- Candidate rows are not graph facts. They require a separate DB-backed consolidation/readback gate with rollback and postwrite evidence before any mutation.",
            "",
            "## Next Cursor",
            "",
            f"Use `{summary['next_resume_cursor']}` for a bounded consolidation/readback gate. Keep `{outputs['still_blocked_jsonl']}` closed for source/OCR/manual review.",
            "",
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_event_identity_resolution_packet(args.input, args.out_dir, args.report)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not summary["failed_checks"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
