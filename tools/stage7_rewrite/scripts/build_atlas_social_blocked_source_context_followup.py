#!/usr/bin/env python3
"""Build report-only follow-up context for blocked Q6 social identity entities.

This packet scans bounded, repo-local Atlas sidecar files for source-context
mentions of entities that were blocked by the Q6 identity acceptance gate. It
does not fetch network content and does not promote identity, graph, or product
truth.
"""
from __future__ import annotations

import argparse
import json
import re
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE7_ROOT.parents[1]
DEFAULT_BLOCKED = (
    STAGE7_ROOT
    / "reports"
    / "atlas_social_identity_acceptance_gate_q6_20260524_0224"
    / "atlas_social_identity_acceptance_blocked.jsonl"
)
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_social_blocked_source_context_followup_q6_20260525"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T6_BLOCKED_SOURCE_CONTEXT_FOLLOWUP_20260525.md"
DEFAULT_CONTEXT_FILES = [
    STAGE7_ROOT / "reports" / "atlas_dj_low_cost_repair_sidecar_20260522" / "event_participant_candidates.jsonl",
    STAGE7_ROOT / "reports" / "atlas_dj_low_cost_repair_sidecar_20260522" / "event_organizer_candidates.jsonl",
    STAGE7_ROOT / "reports" / "atlas_dj_low_cost_repair_sidecar_20260522" / "event_repair_overlay.jsonl",
]
SCHEMA_VERSION = "stage7_atlas_social_blocked_source_context_followup.v1"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").casefold()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for Q6 blocked source-context follow-up: {path}")


def compact(value: Any, limit: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def normalize(value: Any) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", compact(value).casefold())


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_d_path(path, "jsonl")
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        for line in handle:
            if line.strip():
                value = json.loads(line)
                if isinstance(value, dict):
                    rows.append(value)
    return rows


def iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    reject_d_path(path, "context_file")
    if not path.exists():
        return
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        for line in handle:
            if line.strip():
                value = json.loads(line)
                if isinstance(value, dict):
                    yield value


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


def parse_json_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [compact(item, 200) for item in value if compact(item, 200)]
    text = compact(value, 5000)
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return []
    if isinstance(parsed, list):
        return [compact(item, 200) for item in parsed if compact(item, 200)]
    return []


def candidate_terms(row: dict[str, Any]) -> list[dict[str, str]]:
    terms: list[dict[str, str]] = []
    for field in ["candidate_names_json", "candidate_organizers_json", "participants", "inferred_participants_json", "inferred_organizers_json"]:
        for item in parse_json_list(row.get(field)):
            terms.append({"field": field, "value": item})
    for field in ["event_name", "source_title", "entity_name", "name"]:
        value = compact(row.get(field), 300)
        if value:
            terms.append({"field": field, "value": value})
    return terms


def match_terms(target_name: str, terms: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    target_norm = normalize(target_name)
    exact: list[dict[str, str]] = []
    alias_like: list[dict[str, str]] = []
    if not target_norm:
        return exact, alias_like
    for term in terms:
        term_norm = normalize(term["value"])
        if not term_norm:
            continue
        if term_norm == target_norm:
            exact.append(term)
        elif len(target_norm) >= 4 and target_norm in term_norm:
            alias_like.append(term)
    return exact, alias_like


def build_candidate(
    *,
    generated_at: str,
    blocked: dict[str, Any],
    context_file: Path,
    row: dict[str, Any],
    exact_terms: list[dict[str, str]],
    alias_like_terms: list[dict[str, str]],
) -> dict[str, Any]:
    match_kind = "exact_name_local_source_context_candidate" if exact_terms else "alias_like_local_source_context_review"
    return {
        "schema_version": SCHEMA_VERSION + ".candidate",
        "generated_at": generated_at,
        "entity_search_id": compact(blocked.get("entity_search_id")),
        "name": compact(blocked.get("name")),
        "type": compact(blocked.get("type")),
        "match_kind": match_kind,
        "matched_terms": exact_terms or alias_like_terms,
        "context_file": str(context_file),
        "event_key": compact(row.get("event_key")),
        "event_id": compact(row.get("event_id")),
        "event_name": compact(row.get("event_name")),
        "source_account": compact(row.get("source_account")),
        "source_article_uid": compact(row.get("source_article_uid")),
        "source_title": compact(row.get("source_title")),
        "tier": compact(row.get("tier") or row.get("repair_tier")),
        "basis": compact(row.get("basis")),
        "confidence": row.get("confidence"),
        "accepted_for_graph": False,
        "identity_proof": False,
        "avatar_display_allowed": False,
        "public_serving_field_allowed": False,
        "graph_write_allowed": False,
        "next_gate": "T5/T7 manual source-context review before any identity acceptance or graph/write use.",
    }


def dedupe_candidates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str, str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for row in rows:
        key = (
            row["entity_search_id"],
            row["match_kind"],
            row["source_article_uid"],
            row["event_key"],
            json.dumps(row["matched_terms"], ensure_ascii=False, sort_keys=True),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def build_followup(
    *,
    blocked_path: Path,
    context_files: list[Path],
    out_dir: Path,
    report_path: Path,
    max_candidates_per_entity: int,
) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    blocked_rows = read_jsonl(blocked_path)
    generated_at = now_iso()
    candidate_rows: list[dict[str, Any]] = []
    scanned_rows = 0
    for context_file in context_files:
        for row in iter_jsonl(context_file):
            scanned_rows += 1
            terms = candidate_terms(row)
            for blocked in blocked_rows:
                exact_terms, alias_like_terms = match_terms(compact(blocked.get("name")), terms)
                if exact_terms or alias_like_terms:
                    candidate_rows.append(
                        build_candidate(
                            generated_at=generated_at,
                            blocked=blocked,
                            context_file=context_file,
                            row=row,
                            exact_terms=exact_terms,
                            alias_like_terms=alias_like_terms,
                        )
                    )
    candidate_rows = dedupe_candidates(candidate_rows)

    selected: list[dict[str, Any]] = []
    per_entity_count: Counter[str] = Counter()
    for row in sorted(
        candidate_rows,
        key=lambda item: (
            item["entity_search_id"],
            0 if item["match_kind"].startswith("exact_name") else 1,
            item["source_article_uid"],
            item["event_key"],
        ),
    ):
        entity_id = row["entity_search_id"]
        if per_entity_count[entity_id] >= max_candidates_per_entity:
            continue
        per_entity_count[entity_id] += 1
        selected.append(row)

    selected_by_entity: dict[str, list[dict[str, Any]]] = {}
    for row in selected:
        selected_by_entity.setdefault(row["entity_search_id"], []).append(row)

    entity_rows: list[dict[str, Any]] = []
    for rank, blocked in enumerate(blocked_rows, start=1):
        entity_id = compact(blocked.get("entity_search_id"))
        rows = selected_by_entity.get(entity_id, [])
        exact_count = sum(1 for row in rows if row["match_kind"].startswith("exact_name"))
        alias_count = sum(1 for row in rows if row["match_kind"].startswith("alias_like"))
        if exact_count:
            status = "exact_local_source_context_candidate_review_needed"
        elif alias_count:
            status = "alias_like_local_source_context_review_needed"
        else:
            status = "no_local_source_context_found"
        entity_rows.append(
            {
                "schema_version": SCHEMA_VERSION + ".entity",
                "generated_at": generated_at,
                "review_rank": rank,
                "entity_search_id": entity_id,
                "name": compact(blocked.get("name")),
                "type": compact(blocked.get("type")),
                "previous_acceptance_gate_status": compact(blocked.get("acceptance_gate_status")),
                "followup_status": status,
                "selected_context_candidate_count": len(rows),
                "exact_candidate_count": exact_count,
                "alias_like_candidate_count": alias_count,
                "candidate_sources": sorted({row["source_article_uid"] for row in rows if row["source_article_uid"]}),
                "candidate_events": sorted({row["event_name"] for row in rows if row["event_name"]})[:10],
                "accepted_for_graph": False,
                "identity_proof": False,
                "avatar_display_allowed": False,
                "public_serving_field_allowed": False,
                "graph_write_allowed": False,
                "next_gate": "Manual T5/T7 review of source-context candidates; still no product/public/graph promotion.",
            }
        )

    followup_path = out_dir / "atlas_social_blocked_source_context_followup.jsonl"
    candidates_path = out_dir / "atlas_social_blocked_source_context_candidates.jsonl"
    blocked_remaining_path = out_dir / "atlas_social_blocked_source_context_remaining_blocked.jsonl"
    summary_path = out_dir / "atlas_social_blocked_source_context_followup_summary.json"
    write_jsonl(followup_path, entity_rows)
    write_jsonl(candidates_path, selected)
    write_jsonl(blocked_remaining_path, [row for row in entity_rows if row["followup_status"] == "no_local_source_context_found"])

    status_counts = Counter(row["followup_status"] for row in entity_rows)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "ok": True,
        "decision": "atlas_social_blocked_source_context_followup_ready_report_only",
        "blocked_path": str(blocked_path),
        "context_files": [str(path) for path in context_files],
        "out_dir": str(out_dir),
        "report_path": str(report_path),
        "followup_path": str(followup_path),
        "candidates_path": str(candidates_path),
        "blocked_remaining_path": str(blocked_remaining_path),
        "blocked_entity_rows": len(blocked_rows),
        "context_rows_scanned": scanned_rows,
        "selected_candidate_rows": len(selected),
        "entities_with_exact_context_candidates": sum(1 for row in entity_rows if row["exact_candidate_count"] > 0),
        "entities_remaining_without_context": sum(1 for row in entity_rows if row["followup_status"] == "no_local_source_context_found"),
        "status_counts": dict(sorted(status_counts.items())),
        "accepted_for_graph": 0,
        "identity_proof_promoted": 0,
        "avatar_display_allowed": 0,
        "public_serving_field_allowed": 0,
        "graph_write_allowed": 0,
        "safety": {
            "report_only": True,
            "network_call_executed": False,
            "model_call_executed": False,
            "paid_api_used": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "sqlite_write_executed": False,
            "mem0_or_agentmemory_write_executed": False,
            "cloudrun_or_vps_deploy_executed": False,
            "mini_program_upload_or_review_executed": False,
            "secret_value_read_or_printed": False,
            "d_scan_executed": False,
        },
        "next_gate": "T5/T7 manual source-context review for exact candidates; no product truth or graph/write use without a separate acceptance gate.",
    }
    write_json(summary_path, summary)
    write_markdown(report_path, summary, entity_rows)
    return summary


def write_markdown(report_path: Path, summary: dict[str, Any], entity_rows: list[dict[str, Any]]) -> None:
    lines = [
        "# Atlas T6 Blocked Source-Context Follow-up",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{summary['decision']}`",
        f"- blocked_entity_rows: `{summary['blocked_entity_rows']}`",
        f"- selected_candidate_rows: `{summary['selected_candidate_rows']}`",
        f"- entities_with_exact_context_candidates: `{summary['entities_with_exact_context_candidates']}`",
        f"- entities_remaining_without_context: `{summary['entities_remaining_without_context']}`",
        "",
        "## Evidence",
        "",
        f"- Follow-up rows: `{summary['followup_path']}`",
        f"- Candidate rows: `{summary['candidates_path']}`",
        f"- Remaining blocked rows: `{summary['blocked_remaining_path']}`",
        f"- Context files scanned: `{summary['context_rows_scanned']}` rows across `{len(summary['context_files'])}` local files.",
        "",
        "## Entity Results",
        "",
    ]
    for row in entity_rows:
        lines.append(
            f"- `{row['name']}` `{row['entity_search_id']}`: `{row['followup_status']}`, "
            f"exact `{row['exact_candidate_count']}`, alias-like `{row['alias_like_candidate_count']}`, "
            f"selected candidates `{row['selected_context_candidate_count']}`."
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- This packet is report-only local source-context follow-up.",
            "- Exact local source context is not identity proof, avatar permission, public serving permission, or graph/write permission.",
            "- No network/model/paid API call, Neo4j/Qdrant/SQLite write, public pointer update, CloudRun/VPS deploy, mini-program upload/review, memory write, credential read, destructive Git, 9router use, or D: root scan occurred.",
            "",
            "## STOP_REASON / WAIT_REASON",
            "",
            "- `STOP_REASON`: none for report-only local follow-up.",
            "- `WAIT_REASON`: remaining entities still need manual T5/T7 source-context review and a separate acceptance gate before any product/public/graph promotion.",
            "",
            "## Next Resume Cursor",
            "",
            "Route exact context candidates into a bounded T5/T7 manual source-context acceptance review, or continue public target identity only if it can be verified without secrets.",
            "",
        ]
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blocked", type=Path, default=DEFAULT_BLOCKED)
    parser.add_argument("--context-file", type=Path, action="append", dest="context_files")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--max-candidates-per-entity", type=int, default=8)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    context_files = args.context_files or DEFAULT_CONTEXT_FILES
    summary = build_followup(
        blocked_path=args.blocked,
        context_files=context_files,
        out_dir=args.out_dir,
        report_path=args.report,
        max_candidates_per_entity=args.max_candidates_per_entity,
    )
    print(
        json.dumps(
            {
                "decision": summary["decision"],
                "blocked_entity_rows": summary["blocked_entity_rows"],
                "selected_candidate_rows": summary["selected_candidate_rows"],
                "entities_with_exact_context_candidates": summary["entities_with_exact_context_candidates"],
                "entities_remaining_without_context": summary["entities_remaining_without_context"],
                "summary": str(Path(summary["out_dir"]) / "atlas_social_blocked_source_context_followup_summary.json"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
