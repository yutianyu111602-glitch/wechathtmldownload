#!/usr/bin/env python3
"""Build report-only T5/T7 identity review criteria from Q6 metadata rows."""
from __future__ import annotations

import argparse
import json
import re
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE7_ROOT.parents[1]
DEFAULT_RESULTS = (
    STAGE7_ROOT
    / "reports"
    / "atlas_social_outlink_bounded_fetch_q6_20260523_2327"
    / "atlas_social_outlink_bounded_fetch_results.jsonl"
)
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_social_identity_review_criteria_q6_20260524"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T6_IDENTITY_REVIEW_CRITERIA_PACKET_20260524.md"
SCHEMA_VERSION = "stage7_atlas_social_identity_review_criteria.v1"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").casefold()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for Q6 identity review criteria: {path}")


def compact(value: Any, limit: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def normalize(value: Any) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", compact(value, 1000).casefold())


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_d_path(path, "jsonl")
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        for line in handle:
            if line.strip():
                item = json.loads(line)
                if isinstance(item, dict):
                    rows.append(item)
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


def row_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        compact(row.get("entity_search_id")),
        compact(row.get("target_kind")),
        compact(row.get("target_url"), 3000).casefold(),
    )


def public_metadata_haystack(row: dict[str, Any]) -> str:
    return " ".join(
        [
            compact(row.get("page_title"), 500),
            compact(row.get("og_title"), 500),
            compact(row.get("meta_description"), 500),
            compact(row.get("canonical_url"), 3000),
            compact(row.get("final_url"), 3000),
        ]
    )


def classify_review(row: dict[str, Any]) -> tuple[str, str, list[str]]:
    name_norm = normalize(row.get("name"))
    metadata_norm = normalize(public_metadata_haystack(row))
    target_kind = compact(row.get("target_kind"))
    reachable = bool(row.get("reachable"))
    status = int(row.get("status_code") or 0)
    signals = row.get("metadata_signals") if isinstance(row.get("metadata_signals"), list) else []

    if not reachable or not (200 <= status < 400):
        return "defer_unreachable_or_blocked", "needs_more_source_context", [f"http_{status or 0}"]

    reasons: list[str] = []
    if name_norm and name_norm in metadata_norm:
        reasons.append("candidate_name_seen_in_public_metadata")
    if "public_metadata_present" in signals or "public_title_metadata_present" in signals:
        reasons.append("public_metadata_present")
    if "auth_or_js_marker" in signals:
        reasons.append("js_shell_metadata_only")

    if target_kind == "profile_page" and "candidate_name_seen_in_public_metadata" in reasons:
        return "manual_review_profile_identity_candidate", "profile_identity_candidate", reasons
    if target_kind == "music_artifact" and "candidate_name_seen_in_public_metadata" in reasons:
        return "manual_review_music_artifact_context", "supporting_music_artifact_context", reasons
    if reasons:
        return "manual_review_weak_metadata_candidate", "weak_metadata_candidate", reasons
    return "defer_needs_stronger_source_context", "needs_more_source_context", ["no_candidate_name_in_public_metadata"]


def candidate_row(row: dict[str, Any], generated_at: str, rank: int) -> dict[str, Any]:
    review_action, evidence_role, reasons = classify_review(row)
    return {
        "schema_version": SCHEMA_VERSION + ".row",
        "generated_at": generated_at,
        "review_rank": rank,
        "entity_search_id": compact(row.get("entity_search_id")),
        "name": compact(row.get("name")),
        "type": compact(row.get("type")),
        "target_kind": compact(row.get("target_kind")),
        "target_url": compact(row.get("target_url"), 3000),
        "final_url": compact(row.get("final_url"), 3000),
        "status_code": int(row.get("status_code") or 0),
        "page_title": compact(row.get("page_title"), 500),
        "og_title": compact(row.get("og_title"), 500),
        "meta_description": compact(row.get("meta_description"), 500),
        "review_action": review_action,
        "evidence_role": evidence_role,
        "review_reasons": reasons,
        "manual_review_required": True,
        "accepted_for_graph": False,
        "identity_proof": False,
        "graph_write_allowed": False,
        "next_gate": "T5/T7 manual identity review; require independent source context before any product truth or graph use.",
    }


def build_entity_rollups(candidates: list[dict[str, Any]], generated_at: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in candidates:
        grouped[row["entity_search_id"]].append(row)
    rollups: list[dict[str, Any]] = []
    for entity_id, rows in grouped.items():
        action_counts = Counter(row["review_action"] for row in rows)
        role_counts = Counter(row["evidence_role"] for row in rows)
        first = rows[0]
        rollups.append(
            {
                "schema_version": SCHEMA_VERSION + ".entity",
                "generated_at": generated_at,
                "entity_search_id": entity_id,
                "name": first["name"],
                "type": first["type"],
                "candidate_rows": len(rows),
                "unique_target_urls": len({row["target_url"] for row in rows}),
                "profile_identity_candidate_rows": action_counts.get("manual_review_profile_identity_candidate", 0),
                "supporting_music_artifact_rows": action_counts.get("manual_review_music_artifact_context", 0),
                "review_action_counts": dict(sorted(action_counts.items())),
                "evidence_role_counts": dict(sorted(role_counts.items())),
                "manual_review_required": True,
                "accepted_for_graph": False,
                "identity_proof": False,
                "graph_write_allowed": False,
            }
        )
    rollups.sort(key=lambda row: (-row["profile_identity_candidate_rows"], -row["supporting_music_artifact_rows"], row["name"]))
    return rollups


def build_identity_review_criteria(*, results_path: Path, out_dir: Path, report_path: Path) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    rows = read_jsonl(results_path)
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        key = row_key(row)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)

    generated_at = now_iso()
    candidates = [candidate_row(row, generated_at, index) for index, row in enumerate(deduped, start=1)]
    rollups = build_entity_rollups(candidates, generated_at)

    candidates_path = out_dir / "atlas_social_identity_review_candidates.jsonl"
    rollups_path = out_dir / "atlas_social_identity_review_entity_rollups.jsonl"
    summary_path = out_dir / "atlas_social_identity_review_criteria_summary.json"
    write_jsonl(candidates_path, candidates)
    write_jsonl(rollups_path, rollups)

    action_counts = Counter(row["review_action"] for row in candidates)
    role_counts = Counter(row["evidence_role"] for row in candidates)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "ok": True,
        "decision": "atlas_social_identity_review_criteria_ready_report_only",
        "results_path": str(results_path),
        "out_dir": str(out_dir),
        "report_path": str(report_path),
        "candidates_path": str(candidates_path),
        "entity_rollups_path": str(rollups_path),
        "input_rows": len(rows),
        "deduped_candidate_rows": len(candidates),
        "unique_entities": len(rollups),
        "unique_target_urls": len({row["target_url"] for row in candidates}),
        "review_action_counts": dict(sorted(action_counts.items())),
        "evidence_role_counts": dict(sorted(role_counts.items())),
        "target_kind_counts": dict(sorted(Counter(row["target_kind"] for row in candidates).items())),
        "accepted_for_graph": 0,
        "identity_proof_promoted": 0,
        "graph_write_allowed": 0,
        "next_gate": "T5/T7 manual identity review; require independent source context before product truth, avatar display, public serving fields, graph/vector/DB writes, or memory writes.",
        "safety": {
            "report_only": True,
            "network_call_executed": False,
            "model_call_executed": False,
            "paid_api_used": False,
            "page_body_persisted": False,
            "graph_write_executed": False,
            "qdrant_write_executed": False,
            "neo4j_write_executed": False,
            "sqlite_write_executed": False,
            "mem0_write_executed": False,
            "secret_value_read_or_printed": False,
            "d_scan_executed": False,
        },
    }
    write_json(summary_path, summary)
    write_markdown(out_dir / "atlas_social_identity_review_criteria_summary.md", summary, rollups)
    write_markdown(report_path, summary, rollups, top_level=True)
    return summary


def write_markdown(path: Path, summary: dict[str, Any], rollups: list[dict[str, Any]], top_level: bool = False) -> None:
    title = "Atlas T6 Identity Review Criteria Packet" if top_level else "Atlas Social Identity Review Criteria"
    lines = [
        f"# {title}",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{summary['decision']}`",
        f"- input_rows: `{summary['input_rows']}`",
        f"- deduped_candidate_rows: `{summary['deduped_candidate_rows']}`",
        f"- unique_entities: `{summary['unique_entities']}`",
        f"- unique_target_urls: `{summary['unique_target_urls']}`",
        f"- accepted_for_graph: `{summary['accepted_for_graph']}`",
        f"- identity_proof_promoted: `{summary['identity_proof_promoted']}`",
        f"- graph_write_allowed: `{summary['graph_write_allowed']}`",
        f"- candidates_path: `{summary['candidates_path']}`",
        f"- entity_rollups_path: `{summary['entity_rollups_path']}`",
        "",
        "## Review Actions",
        "",
    ]
    for key, value in summary["review_action_counts"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Evidence Roles", ""])
    for key, value in summary["evidence_role_counts"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Entity Rollups", ""])
    for row in rollups:
        lines.append(
            "- `{name}` `{entity}`: profile candidates `{profile}`, supporting artifacts `{artifacts}`, rows `{rows}`".format(
                name=row["name"],
                entity=row["entity_search_id"],
                profile=row["profile_identity_candidate_rows"],
                artifacts=row["supporting_music_artifact_rows"],
                rows=row["candidate_rows"],
            )
        )
    lines.extend(
        [
            "",
            "## Manual Criteria",
            "",
            "- A SoundCloud profile metadata match is only a manual identity candidate, not identity proof.",
            "- Music-artifact rows are supporting context only; they cannot create a graph edge or avatar/public field by themselves.",
            "- Promotion requires independent source context reviewed by T5/T7 and a later explicit graph/write gate.",
            "",
            "## Safety",
            "",
            "- Report-only criteria build; no network/model/paid API call was executed in this step.",
            "- No page body, secret value, graph/vector/database write, memory write, deployment, upload, review submission, or D: root scan occurred.",
            f"- Next gate: {summary['next_gate']}",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_identity_review_criteria(results_path=args.results, out_dir=args.out_dir, report_path=args.report_path)
    print(
        json.dumps(
            {
                "decision": summary["decision"],
                "deduped_candidate_rows": summary["deduped_candidate_rows"],
                "unique_entities": summary["unique_entities"],
                "summary": str(args.out_dir / "atlas_social_identity_review_criteria_summary.json"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
