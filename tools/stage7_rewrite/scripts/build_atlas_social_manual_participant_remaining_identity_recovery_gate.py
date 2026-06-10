#!/usr/bin/env python3
"""Build a report-only recovery gate for remaining Q6 blocked identity lanes."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE7_ROOT.parents[1]
DEFAULT_BLOCKED_DIR = (
    STAGE7_ROOT
    / "reports"
    / "atlas_social_manual_participant_blocked_identity_review_q6_20260526"
)
DEFAULT_OUT_DIR = (
    STAGE7_ROOT
    / "reports"
    / "atlas_social_manual_participant_remaining_identity_recovery_q6_20260526"
)
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T6_MANUAL_PARTICIPANT_REMAINING_IDENTITY_RECOVERY_GATE_20260526.md"
SCHEMA_VERSION = "stage7_atlas_social_manual_participant_remaining_identity_recovery_gate.v1"

URL_RE = re.compile(r"https?://", re.I)
SECRET_RE = re.compile(r"\b(secret|token|cookie|password|api[_-]?key|authorization|bearer)\b", re.I)
LOCAL_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"']+|/mnt/[A-Za-z][^\s\"']*|/home/[^\s\"']+|\\\\[A-Za-z0-9_.-]+[\\/][^\s\"']+",
    re.I,
)

INPUT_FILES = {
    "event_date_or_source_year_recovery": "event_date_or_source_year_recovery_work_orders.jsonl",
    "same_date_cluster_tiebreak": "same_date_cluster_tiebreak_work_orders.jsonl",
    "venue_alias_lineage": "venue_alias_lineage_work_orders.jsonl",
    "multi_venue_split": "multi_venue_split_work_orders.jsonl",
    "low_title_similarity": "low_title_similarity_work_orders.jsonl",
}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def compact(value: Any, limit: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def normalize(value: Any) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", compact(value, 1000).casefold())


def venue_family(value: Any) -> str:
    text = normalize(value)
    if not text:
        return ""
    if "oil" in text or "车公庙泰然" in text or "l111a" in text or "l111a" in text.replace("一", "1"):
        return "oil"
    if "clubme" in text:
        return "clubme"
    if "coolwave" in text or "酷浪" in text:
        return "coolwaveclub"
    if "thebox" in text or "年轻力中心" in text:
        return "the_box"
    if "dada" in text and ("kunming" in text or "昆明" in text):
        return "dada_kunming"
    if "dada" in text and ("beijing" in text or "北京" in text):
        return "dada_beijing"
    return text


def number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def stable_id(prefix: str, parts: Iterable[Any]) -> str:
    raw = "|".join(compact(part, 800) for part in parts)
    return f"{prefix}:{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}"


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").casefold()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for remaining identity recovery gate: {path}")


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return path.name


def sanitize_report_text(value: Any, limit: int = 1000) -> str:
    text = compact(value, limit).replace("\\", "/")
    text = URL_RE.sub("[url-redacted]", text)
    text = LOCAL_PATH_RE.sub("[local-path-redacted]", text)
    text = re.sub(r"token", "marker", text, flags=re.I)
    text = SECRET_RE.sub("[sensitive-label-redacted]", text)
    return text


def read_jsonl(path: Path, label: str) -> list[dict[str, Any]]:
    reject_d_path(path, label)
    if not path.exists():
        return []
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


def list_strings(value: Any, limit: int = 200) -> list[str]:
    if not isinstance(value, list):
        return []
    return [compact(item, limit) for item in value if compact(item, limit)]


def clusters(row: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in row.get("semantic_event_clusters_for_review") or [] if isinstance(item, dict)]


def cluster_event_ids(cluster: dict[str, Any]) -> list[str]:
    return list_strings(cluster.get("event_ids"), 160)


def cluster_source_refs(cluster: dict[str, Any]) -> list[str]:
    return list_strings(cluster.get("source_ref_ids"), 160)


def cluster_brief(cluster: dict[str, Any]) -> dict[str, Any]:
    event_ids = cluster_event_ids(cluster)
    return {
        "cluster_id": compact(cluster.get("cluster_id"), 160),
        "starts_at": compact(cluster.get("starts_at"), 80),
        "canonical_venue": compact(cluster.get("canonical_venue"), 180),
        "venue_family": venue_family(cluster.get("canonical_venue") or cluster.get("venue_name_sample")),
        "venue_name_sample": compact(cluster.get("venue_name_sample"), 220),
        "city_sample": compact(cluster.get("city_sample"), 120),
        "event_title_sample": compact(cluster.get("event_title_sample"), 280),
        "event_ids": event_ids[:32],
        "event_id_count": int(number(cluster.get("event_id_count")) or len(event_ids)),
        "candidate_rows": int(number(cluster.get("candidate_rows"))),
        "max_event_match_score": round(number(cluster.get("max_event_match_score")), 4),
        "max_participant_count": int(number(cluster.get("max_participant_count"))),
        "source_ref_ids": cluster_source_refs(cluster)[:12],
    }


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


def selected_ids(selected_clusters: list[dict[str, Any]]) -> list[str]:
    ids: set[str] = set()
    for cluster in selected_clusters:
        ids.update(cluster_event_ids(cluster))
    return sorted(ids)


def selected_refs(selected_clusters: list[dict[str, Any]], source_ref_id: str) -> list[str]:
    refs: set[str] = {source_ref_id} if source_ref_id else set()
    for cluster in selected_clusters:
        refs.update(cluster_source_refs(cluster))
    refs.discard("")
    return sorted(refs)


def selector_hash(row: dict[str, Any], selected_clusters: list[dict[str, Any]], lane: str) -> str:
    return stable_id(
        "remainingidentityselector",
        [
            lane,
            row.get("review_work_order_id"),
            row.get("article_uid"),
            [cluster.get("cluster_id") for cluster in selected_clusters],
            selected_ids(selected_clusters),
        ],
    )


def make_readback_candidate(
    row: dict[str, Any],
    selected_clusters: list[dict[str, Any]],
    *,
    resolution_lane: str,
    resolution_status: str,
    resolution_reason: str,
    source_hash: str | None = None,
) -> dict[str, Any]:
    event_ids = selected_ids(selected_clusters)
    source_ref_id = compact(row.get("source_ref_id"), 160)
    source_refs = selected_refs(selected_clusters, source_ref_id)
    selector = selector_hash(row, selected_clusters, resolution_lane)
    representative = event_ids[0] if event_ids else ""
    source_hash_value = compact(source_hash if source_hash is not None else row.get("source_hash"), 200)
    return {
        "schema_version": f"{SCHEMA_VERSION}.readback_candidate",
        "recovery_id": stable_id("remainingidentity", [row.get("review_work_order_id"), resolution_lane, event_ids]),
        "resolution_id": compact(row.get("upstream_resolution_id"), 160),
        "resolution_status": resolution_status,
        "resolution_lane": resolution_lane,
        "resolution_reason": resolution_reason,
        "manual_review_required": False,
        "source_account": compact(row.get("source_account"), 160),
        "article_uid": compact(row.get("article_uid"), 240),
        "work_item_id": compact(row.get("upstream_work_item_id"), 160),
        "review_work_order_id": compact(row.get("review_work_order_id"), 160),
        "source_ref_id": source_ref_id,
        "source_ref_ids": source_refs,
        "source_hash": source_hash_value,
        "selector_hash": selector,
        "selected_event_ids_review_only": event_ids,
        "selected_event_id_count": len(event_ids),
        "representative_event_id_review_only": representative,
        "selected_semantic_event_clusters": [cluster_brief(cluster) for cluster in selected_clusters],
        "deterministic_selector": {
            "selector_hash": selector,
            "event_ids": event_ids,
            "source_ref_ids": source_refs,
            "source_hash": source_hash_value,
            "representative_event_id_review_only": representative,
            "selected_cluster_ids": [compact(cluster.get("cluster_id"), 160) for cluster in selected_clusters],
        },
        "candidate_date_values": list_strings(row.get("candidate_date_values"), 80),
        "derived_title_date_candidates": list_strings(row.get("derived_title_date_candidates"), 80),
        "post_date": compact(row.get("post_date"), 80),
        "title": sanitize_report_text(row.get("title"), 280),
        "name": sanitize_report_text(row.get("name"), 180),
        "source_hash_unbound_to_selected_cluster": not source_hash_value,
        "llm_audit_judgment": "deterministic_report_only_candidate; feed through DB-backed readback before any source/raw DB or serving/graph/public write",
        "later_write_contract": {
            "write_allowed_now": False,
            "db_backed_readback_required": True,
            "source_raw_target_db_provenance_required": True,
            "prewrite_snapshot_required": True,
            "rollback_required": True,
            "postwrite_readback_required": True,
        },
        **closed_flags(),
    }


def block_row(row: dict[str, Any], lane: str, reasons: list[str], extra: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "schema_version": f"{SCHEMA_VERSION}.blocked_row",
        "recovery_id": stable_id("remainingidentityblocked", [row.get("review_work_order_id"), lane, reasons]),
        "source_account": compact(row.get("source_account"), 160),
        "article_uid": compact(row.get("article_uid"), 240),
        "review_work_order_id": compact(row.get("review_work_order_id"), 160),
        "upstream_resolution_id": compact(row.get("upstream_resolution_id"), 160),
        "recovery_lane": lane,
        "blocked_reasons": sorted(set(reasons)),
        "candidate_date_values": list_strings(row.get("candidate_date_values"), 80),
        "derived_title_date_candidates": list_strings(row.get("derived_title_date_candidates"), 80),
        "matching_date_cluster_count": int(number(row.get("matching_date_cluster_count"))),
        "source_ocr_recovery_required": row.get("source_ocr_recovery_required") is True,
        "db_readback_required_before_write": row.get("db_readback_required_before_write") is True,
        "title": sanitize_report_text(row.get("title"), 280),
        "name": sanitize_report_text(row.get("name"), 180),
        "safe_next_action": compact(row.get("safe_next_action"), 260),
        "semantic_event_clusters_for_review": [cluster_brief(cluster) for cluster in clusters(row)],
        "later_write_contract": {
            "write_allowed_now": False,
            "manual_or_source_recovery_required_first": True,
            "db_backed_readback_required_after_recovery": True,
        },
        **(extra or {}),
        **closed_flags(),
    }


def source_hash_for_selected(row: dict[str, Any], selected_clusters: list[dict[str, Any]]) -> str:
    row_ref = compact(row.get("source_ref_id"), 160)
    row_hash = compact(row.get("source_hash"), 200)
    if row_ref and row_hash and any(row_ref in cluster_source_refs(cluster) for cluster in selected_clusters):
        return row_hash
    return ""


def resolve_same_date(row: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    derived_dates = set(list_strings(row.get("derived_title_date_candidates"), 80))
    post_year = compact(row.get("post_date"), 20)[:4]
    matching = [cluster for cluster in clusters(row) if compact(cluster.get("starts_at"), 80) in derived_dates]
    if post_year and any(compact(cluster.get("starts_at"), 80).startswith(post_year) for cluster in matching):
        matching = [cluster for cluster in matching if compact(cluster.get("starts_at"), 80).startswith(post_year)]
    if not matching:
        return None, block_row(row, "same_date_cluster_tiebreak", ["no_cluster_matches_derived_title_date"])

    source_ref_id = compact(row.get("source_ref_id"), 160)
    ranked = sorted(
        matching,
        key=lambda cluster: (
            number(cluster.get("max_event_match_score")),
            1 if source_ref_id and source_ref_id in cluster_source_refs(cluster) else 0,
            number(cluster.get("candidate_rows")),
            number(cluster.get("event_id_count")),
        ),
        reverse=True,
    )
    top = ranked[0]
    second_score = number(ranked[1].get("max_event_match_score")) if len(ranked) > 1 else -1.0
    top_score = number(top.get("max_event_match_score"))
    top_source_match = bool(source_ref_id and source_ref_id in cluster_source_refs(top))
    if top_score < 0.95:
        return None, block_row(row, "same_date_cluster_tiebreak", ["top_title_score_below_deterministic_threshold"])
    if len(ranked) > 1 and top_score == second_score and not top_source_match:
        return None, block_row(row, "same_date_cluster_tiebreak", ["top_cluster_tie_without_source_ref_precedence"])

    candidate = make_readback_candidate(
        row,
        [top],
        resolution_lane="date_resolved_consolidation_candidate",
        resolution_status="date_resolved_consolidation_candidate_report_only",
        resolution_reason="same_date_cluster_tiebreak_deterministic_selector_report_only",
        source_hash=source_hash_for_selected(row, [top]),
    )
    candidate["same_date_tiebreak_evidence"] = {
        "candidate_matching_clusters": [cluster_brief(cluster) for cluster in matching],
        "selected_cluster_source_ref_match": top_source_match,
        "top_score": top_score,
        "second_score": second_score,
    }
    return candidate, None


def resolve_venue_alias(row: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    derived_dates = set(list_strings(row.get("derived_title_date_candidates"), 80))
    all_clusters = clusters(row)
    matching = [cluster for cluster in all_clusters if not derived_dates or compact(cluster.get("starts_at"), 80) in derived_dates]
    if derived_dates and not matching:
        return None, block_row(row, "venue_alias_lineage", ["derived_title_date_not_matching_candidate_cluster"])

    selected = matching or all_clusters
    dates = {compact(cluster.get("starts_at"), 80) for cluster in selected if compact(cluster.get("starts_at"), 80)}
    families = {venue_family(cluster.get("canonical_venue") or cluster.get("venue_name_sample")) for cluster in selected}
    families.discard("")
    min_score = min([number(cluster.get("max_event_match_score")) for cluster in selected] or [0])
    if len(dates) != 1:
        return None, block_row(row, "venue_alias_lineage", ["selected_clusters_not_single_date"])
    if len(families) != 1:
        return None, block_row(
            row,
            "venue_alias_lineage",
            ["venue_alias_family_not_deterministic"],
            {"candidate_venue_families": sorted(families)},
        )
    if min_score < 0.95:
        return None, block_row(row, "venue_alias_lineage", ["venue_alias_title_score_below_threshold"])

    candidate = make_readback_candidate(
        row,
        selected,
        resolution_lane="venue_alias_resolved_consolidation_candidate",
        resolution_status="venue_alias_resolved_consolidation_candidate_report_only",
        resolution_reason="venue_alias_lineage_deterministic_selector_report_only",
        source_hash=source_hash_for_selected(row, selected),
    )
    candidate["venue_alias_lineage_evidence"] = {
        "venue_family": next(iter(families)),
        "selected_cluster_count": len(selected),
        "selected_cluster_briefs": [cluster_brief(cluster) for cluster in selected],
        "min_title_score": min_score,
    }
    return candidate, None


def process_row(row: dict[str, Any], lane: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if lane == "same_date_cluster_tiebreak":
        return resolve_same_date(row)
    if lane == "venue_alias_lineage":
        return resolve_venue_alias(row)
    if lane == "event_date_or_source_year_recovery":
        reasons = ["source_ocr_or_manual_event_date_recovery_required"]
        if row.get("source_ocr_recovery_required") is True:
            reasons.append("source_ocr_recovery_required")
        if int(number(row.get("matching_date_cluster_count"))) == 0:
            reasons.append("no_candidate_cluster_matches_derived_title_date")
        return None, block_row(row, lane, reasons)
    if lane == "multi_venue_split":
        return None, block_row(row, lane, ["manual_multi_venue_or_room_split_required"])
    if lane == "low_title_similarity":
        return None, block_row(row, lane, ["manual_title_identity_review_required"])
    return None, block_row(row, lane, ["unrecognized_recovery_lane"])


def scan_payload(payload: Any) -> dict[str, int]:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "public_url_hits": len(URL_RE.findall(text)),
        "sensitive_key_hits": len(SECRET_RE.findall(text)),
        "local_path_hits": len(LOCAL_PATH_RE.findall(text)),
    }


def build_batches(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[compact(row.get("source_account"), 160)].append(row)
    batches: list[dict[str, Any]] = []
    for source_account, items in sorted(grouped.items()):
        lanes = Counter(compact(row.get("recovery_lane") or row.get("resolution_lane"), 160) for row in items)
        batches.append(
            {
                "schema_version": f"{SCHEMA_VERSION}.source_account_batch",
                "source_account": source_account,
                "row_count": len(items),
                "lane_counts": dict(sorted(lanes.items())),
                "write_allowed_now": False,
            }
        )
    return batches


def render_summary_md(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    return "\n".join(
        [
            "# Atlas Q6 Remaining Identity Recovery Gate Summary",
            "",
            f"- Decision: `{summary['decision']}`",
            f"- Input / candidates / blocked: `{counts['input_work_order_rows']}/{counts['readback_candidate_rows']}/{counts['blocked_rows']}`",
            f"- Same-date candidates: `{counts['same_date_tiebreak_candidate_rows']}`",
            f"- Venue-alias candidates: `{counts['venue_alias_lineage_candidate_rows']}`",
            f"- Source-year / multi-venue / low-title blocked: `{counts['event_date_or_source_year_blocked_rows']}/{counts['multi_venue_split_blocked_rows']}/{counts['low_title_similarity_blocked_rows']}`",
            f"- Venue-alias date-mismatch blocked: `{counts['venue_alias_date_mismatch_blocked_rows']}`",
            f"- Unique selected event ids in candidates: `{counts['unique_selected_event_ids_in_candidates']}`",
            f"- Leak hits public/sensitive/local: `{summary['leak_counts']['public_url_hits']}/{summary['leak_counts']['sensitive_key_hits']}/{summary['leak_counts']['local_path_hits']}`",
            f"- Next resume pointer: `{summary['next_resume_pointer']}`",
            "",
        ]
    )


def render_report(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    outputs = summary["outputs"]
    return "\n".join(
        [
            "# Atlas T6 Manual Participant Remaining Identity Recovery Gate - 2026-05-26",
            "",
            "## Decision",
            "",
            f"- Decision: `{summary['decision']}`",
            f"- Failed checks: `{summary['failed_checks']}`",
            "- Boundary: report-only recovery gate. It reads existing JSONL work orders only and does not open SQLite, fetch network, call models, execute OCR, accept graph facts, write source/raw Atlas DB, rebuild/write serving SQLite, write Neo4j/Qdrant/production SQLite, update public pointers, deploy, upload/review mini-program, or write memory.",
            "",
            "## Counts",
            "",
            f"- Input work orders: `{counts['input_work_order_rows']}`",
            f"- Readback candidate rows: `{counts['readback_candidate_rows']}`",
            f"- Blocked rows: `{counts['blocked_rows']}`",
            f"- Same-date tiebreak / venue-alias candidates: `{counts['same_date_tiebreak_candidate_rows']}/{counts['venue_alias_lineage_candidate_rows']}`",
            f"- Source-year / venue-date-mismatch / multi-venue / low-title blockers: `{counts['event_date_or_source_year_blocked_rows']}/{counts['venue_alias_date_mismatch_blocked_rows']}/{counts['multi_venue_split_blocked_rows']}/{counts['low_title_similarity_blocked_rows']}`",
            f"- Source-account batches: `{counts['source_account_batches']}`",
            f"- Unique selected event ids in candidates: `{counts['unique_selected_event_ids_in_candidates']}`",
            "- Accepted/source-sqlite/serving/graph/public/memory rows: `0/0/0/0/0/0`",
            f"- Public URL / sensitive key / local path leak hits: `{summary['leak_counts']['public_url_hits']}/{summary['leak_counts']['sensitive_key_hits']}/{summary['leak_counts']['local_path_hits']}`",
            "",
            "## Evidence",
            "",
            f"- Summary JSON: `{outputs['summary_json']}`",
            f"- All rows: `{outputs['all_rows']}`",
            f"- Readback candidates: `{outputs['readback_candidates']}`",
            f"- Same-date candidates: `{outputs['same_date_tiebreak_candidates']}`",
            f"- Venue-alias candidates: `{outputs['venue_alias_lineage_candidates']}`",
            f"- Blocked rows: `{outputs['blocked_rows']}`",
            f"- Source-account batches: `{outputs['source_account_batches']}`",
            "",
            "## Next Resume Pointer",
            "",
            f"`{summary['next_resume_pointer']}`",
            "",
            f"Split resume pointers: `{summary['next_resume_pointer_split']}`",
            "",
        ]
    )


def build_packet(blocked_dir: Path, out_dir: Path, report_path: Path) -> dict[str, Any]:
    reject_d_path(blocked_dir, "blocked_dir")
    reject_d_path(out_dir, "out_dir")
    reject_d_path(report_path, "report_path")
    generated_at = now_iso()
    input_rows_by_lane = {
        lane: read_jsonl(blocked_dir / filename, f"{lane}_jsonl")
        for lane, filename in INPUT_FILES.items()
    }

    candidates: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    all_rows: list[dict[str, Any]] = []
    for lane, rows in input_rows_by_lane.items():
        for row in rows:
            candidate, blocked_row = process_row(row, lane)
            if candidate is not None:
                candidate["generated_at"] = generated_at
                candidates.append(candidate)
                all_rows.append(candidate)
            if blocked_row is not None:
                blocked_row["generated_at"] = generated_at
                blocked.append(blocked_row)
                all_rows.append(blocked_row)

    same_date = [row for row in candidates if row["resolution_lane"] == "date_resolved_consolidation_candidate"]
    venue_alias = [row for row in candidates if row["resolution_lane"] == "venue_alias_resolved_consolidation_candidate"]
    event_date_blocked = [row for row in blocked if row["recovery_lane"] == "event_date_or_source_year_recovery"]
    multi_venue_blocked = [row for row in blocked if row["recovery_lane"] == "multi_venue_split"]
    low_title_blocked = [row for row in blocked if row["recovery_lane"] == "low_title_similarity"]
    venue_date_blocked = [
        row
        for row in blocked
        if row["recovery_lane"] == "venue_alias_lineage"
        and "derived_title_date_not_matching_candidate_cluster" in row["blocked_reasons"]
    ]
    selected_event_ids = sorted({event_id for row in candidates for event_id in row["selected_event_ids_review_only"]})
    batches = build_batches(all_rows)

    outputs = {
        "summary_json": display_path(out_dir / "remaining_identity_recovery_summary.json"),
        "summary_md": display_path(out_dir / "remaining_identity_recovery_summary.md"),
        "all_rows": display_path(out_dir / "remaining_identity_recovery_all_rows.jsonl"),
        "readback_candidates": display_path(out_dir / "remaining_identity_recovery_readback_candidates_report_only.jsonl"),
        "same_date_tiebreak_candidates": display_path(out_dir / "deterministic_same_date_tiebreak_candidates.jsonl"),
        "venue_alias_lineage_candidates": display_path(out_dir / "venue_alias_lineage_candidates_report_only.jsonl"),
        "blocked_rows": display_path(out_dir / "remaining_identity_recovery_blocked_rows.jsonl"),
        "event_date_or_source_year_blocked_rows": display_path(out_dir / "event_date_or_source_year_blocked_rows.jsonl"),
        "multi_venue_split_blocked_rows": display_path(out_dir / "multi_venue_split_blocked_rows.jsonl"),
        "low_title_similarity_blocked_rows": display_path(out_dir / "low_title_similarity_blocked_rows.jsonl"),
        "venue_alias_date_mismatch_blocked_rows": display_path(out_dir / "venue_alias_date_mismatch_blocked_rows.jsonl"),
        "source_account_batches": display_path(out_dir / "source_account_remaining_identity_batches.jsonl"),
    }
    leak_counts = scan_payload(all_rows + batches)
    failed_checks = [key for key, value in leak_counts.items() if value]
    if not candidates:
        failed_checks.append("no_recovery_candidates")

    counts = {
        "input_work_order_rows": sum(len(rows) for rows in input_rows_by_lane.values()),
        "readback_candidate_rows": len(candidates),
        "blocked_rows": len(blocked),
        "same_date_tiebreak_candidate_rows": len(same_date),
        "venue_alias_lineage_candidate_rows": len(venue_alias),
        "event_date_or_source_year_blocked_rows": len(event_date_blocked),
        "multi_venue_split_blocked_rows": len(multi_venue_blocked),
        "low_title_similarity_blocked_rows": len(low_title_blocked),
        "venue_alias_date_mismatch_blocked_rows": len(venue_date_blocked),
        "source_account_batches": len(batches),
        "unique_selected_event_ids_in_candidates": len(selected_event_ids),
        "accepted_for_graph_rows": 0,
        "source_sqlite_write_allowed_rows": 0,
        "serving_rebuild_allowed_rows": 0,
        "graph_write_allowed_rows": 0,
        "public_serving_field_allowed_rows": 0,
        "memory_write_allowed_rows": 0,
    }
    summary = {
        "schema_version": f"{SCHEMA_VERSION}.summary",
        "generated_at": generated_at,
        "decision": (
            "atlas_social_manual_participant_remaining_identity_recovery_candidates_ready_report_only"
            if not failed_checks
            else "atlas_social_manual_participant_remaining_identity_recovery_blocked_report_only"
        ),
        "failed_checks": sorted(failed_checks),
        "inputs": {
            lane: display_path(blocked_dir / filename)
            for lane, filename in INPUT_FILES.items()
        },
        "outputs": outputs,
        "counts": counts,
        "leak_counts": leak_counts,
        "source_account_counts": dict(sorted(Counter(row.get("source_account") for row in all_rows).items())),
        "blocked_reason_counts": dict(sorted(Counter(reason for row in blocked for reason in row["blocked_reasons"]).items())),
        "next_resume_pointer": outputs["readback_candidates"] if candidates else outputs["blocked_rows"],
        "next_resume_pointer_split": {
            "readback_candidates_first": outputs["readback_candidates"],
            "same_date_tiebreak_candidates": outputs["same_date_tiebreak_candidates"],
            "venue_alias_lineage_candidates": outputs["venue_alias_lineage_candidates"],
            "blocked_recovery_rows": outputs["blocked_rows"],
        },
        "write_guards": {
            "write_execution_allowed_now": False,
            "source_sqlite_write_allowed": False,
            "serving_rebuild_allowed": False,
            "graph_write_allowed": False,
            "public_serving_field_allowed": False,
            "memory_write_allowed": False,
        },
        "safety": {
            "report_only": True,
            "source_sqlite_opened": False,
            "serving_sqlite_opened": False,
            "source_sqlite_write_executed": False,
            "serving_sqlite_rebuild_executed": False,
            "network_call_executed": False,
            "model_call_executed": False,
            "ocr_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "memory_write_executed": False,
        },
    }

    write_json(out_dir / "remaining_identity_recovery_summary.json", summary)
    write_text(out_dir / "remaining_identity_recovery_summary.md", render_summary_md(summary))
    write_jsonl(out_dir / "remaining_identity_recovery_all_rows.jsonl", all_rows)
    write_jsonl(out_dir / "remaining_identity_recovery_readback_candidates_report_only.jsonl", candidates)
    write_jsonl(out_dir / "deterministic_same_date_tiebreak_candidates.jsonl", same_date)
    write_jsonl(out_dir / "venue_alias_lineage_candidates_report_only.jsonl", venue_alias)
    write_jsonl(out_dir / "remaining_identity_recovery_blocked_rows.jsonl", blocked)
    write_jsonl(out_dir / "event_date_or_source_year_blocked_rows.jsonl", event_date_blocked)
    write_jsonl(out_dir / "multi_venue_split_blocked_rows.jsonl", multi_venue_blocked)
    write_jsonl(out_dir / "low_title_similarity_blocked_rows.jsonl", low_title_blocked)
    write_jsonl(out_dir / "venue_alias_date_mismatch_blocked_rows.jsonl", venue_date_blocked)
    write_jsonl(out_dir / "source_account_remaining_identity_batches.jsonl", batches)
    write_text(report_path, render_report(summary))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blocked-dir", type=Path, default=DEFAULT_BLOCKED_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_packet(args.blocked_dir, args.out_dir, args.report)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
