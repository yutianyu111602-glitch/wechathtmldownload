#!/usr/bin/env python3
"""Build the S129 external-link mapping repair queue.

Report-only. This consumes the S128 mapping workbench and turns every blocked
row into an explicit repair or close action. It does not mutate DB1/DB2/DB3,
project to DB2, write DB3 identity rows, fetch external pages, call models, or
authorize mini-program public display.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
STAGE7_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "external_link_mapping_repair_queue_s129.v1"
DEFAULT_S128_REPORT = STAGE7_ROOT / "reports" / "external_link_entity_id_mapping_s128_20260601" / "external_link_entity_id_mapping_workbench.json"
DEFAULT_S120_ITEMS = STAGE7_ROOT / "reports" / "miniprogram_external_link_contract_s120_20260601" / "miniprogram_external_link_items.json"
DEFAULT_S125_ROWS = STAGE7_ROOT / "reports" / "db2_candidate_projection_smoke_s125_20260601" / "external_link_db2_candidate_projection_rows.json"
DEFAULT_S125A_CANDIDATES = STAGE7_ROOT / "reports" / "label_dj_bio_recognition_s125a_20260601" / "label_dj_bio_candidates.jsonl"
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "external_link_mapping_repair_queue_s129_20260601"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_EXTERNAL_LINK_MAPPING_REPAIR_QUEUE_S129_20260601.md"
DEFAULT_EVIDENCE_PATHS = [
    REPO_ROOT / "reports" / "ATLAS_T6_YYYY_IDENTITY_ACCEPTANCE_GATE_20260525.md",
    REPO_ROOT / "reports" / "ATLAS_T6_BLOCKED_SOURCE_CONTEXT_ACCEPTANCE_REVIEW_20260525.md",
    REPO_ROOT / "reports" / "ATLAS_T6_IDENTITY_ACCEPTANCE_GATE_PACKET_20260524.md",
    STAGE7_ROOT / "reports" / "atlas_social_codact_source_context_recovery_q6_20260525" / "atlas_social_codact_source_context_recovery_summary.json",
    STAGE7_ROOT / "reports" / "atlas_social_yyyy_identity_acceptance_q6_20260525" / "atlas_social_yyyy_identity_acceptance_summary.json",
]

SECRET_RE = re.compile(
    r"(?i)(sk-[A-Za-z0-9_-]{12,}|token\s*[:=]\s*[^,\s]{8,}|cookie\s*[:=]\s*[^,\s]{8,}|password\s*[:=]\s*[^,\s]{8,}|BEGIN [A-Z ]*PRIVATE KEY)"
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def rel_path(path: Path, root: Path = REPO_ROOT) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return path.as_posix()


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        temp_name = handle.name
    os.replace(temp_name, path)


def atomic_write_json(path: Path, payload: Any) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def atomic_write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    atomic_write_text(path, "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows))


def stable_id(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:24]


def compact(value: Any, limit: int = 500) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def normalize_name(value: Any) -> str:
    return re.sub(r"\s+", " ", compact(value, 160).casefold()).strip()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_rows(path: Path) -> list[dict[str, Any]]:
    payload = load_json(path)
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("items"), list):
        return [row for row in payload["items"] if isinstance(row, dict)]
    return []


def iter_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if isinstance(value, dict):
            rows.append(value)
    return rows


def load_s125a_rows(path: Path) -> list[dict[str, Any]]:
    return iter_jsonl(path)


def evidence_index(paths: list[Path]) -> dict[str, list[dict[str, str]]]:
    index: dict[str, list[dict[str, str]]] = defaultdict(list)
    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            clean = compact(line, 260)
            if not clean:
                continue
            for name in ("999999999", "CLASICK", "Cod.Act", "Cyril", "Ra", "YYYY"):
                if name.casefold() in clean.casefold():
                    index[normalize_name(name)].append({"path": rel_path(path), "snippet": clean})
    return {key: values[:5] for key, values in index.items()}


def row_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        compact(row.get("entity_search_id"), 120),
        compact(row.get("entity_name"), 160),
        compact(row.get("entity_type"), 80),
    )


def group_upstream_rows(rows: list[dict[str, Any]]) -> dict[tuple[str, str, str], list[dict[str, Any]]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row_key(row)].append(row)
    return grouped


def summarize_upstream(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "item_ids": sorted({compact(row.get("item_id"), 120) for row in rows if row.get("item_id")}),
        "platforms": sorted({compact(row.get("platform"), 80) for row in rows if row.get("platform")}),
        "public_categories": sorted({compact(row.get("public_category"), 80) for row in rows if row.get("public_category")}),
        "fetch_decisions": sorted({compact(row.get("s124_fetch_decision"), 80) for row in rows if row.get("s124_fetch_decision")}),
        "source_ref_ids": sorted({compact(row.get("source_ref_id"), 120) for row in rows if row.get("source_ref_id")}),
        "source_hashes": sorted({compact(row.get("source_hash"), 120) for row in rows if row.get("source_hash")}),
    }


def classify_task(
    row: dict[str, Any],
    *,
    ready_by_name: dict[str, list[dict[str, Any]]],
    upstream_rows: list[dict[str, Any]],
    s125a_rows: list[dict[str, Any]],
    local_evidence: list[dict[str, str]],
) -> dict[str, Any]:
    reasons = set(row.get("block_reasons") or [])
    name_key = normalize_name(row.get("entity_name"))
    entity_type = compact(row.get("entity_type"), 80)
    disposition = "repair_required"
    repair_action = "manual_source_ref_review"
    promotion_allowed = False
    resolved_without_promotion = False
    rationale: list[str] = []

    if any(reason.startswith("external_entity_type_not_person:") for reason in reasons):
        if ready_by_name.get(name_key):
            disposition = "closed_as_non_person_duplicate_of_person_candidate"
            repair_action = "close_non_person_duplicate_keep_person_candidate"
            resolved_without_promotion = True
            rationale.append("same normalized name has a report-only person mapping candidate")
        elif entity_type == "work":
            disposition = "closed_as_work_title_not_dj_profile"
            repair_action = "close_work_entity_do_not_map_to_dj_profile"
            resolved_without_promotion = True
            rationale.append("external entity is typed as work, not a DJ/person identity")
        else:
            disposition = "keep_blocked_non_person_requires_identity_evidence"
            repair_action = "collect_source_context_or_retype_before_mapping"
            rationale.append("external entity type is not person and no ready person mapping exists")

    if "missing_entity_search_id" in reasons:
        disposition = "repair_required_missing_entity_search_id"
        repair_action = "backfill_or_rederive_entity_search_id_then_rerun_mapping"
        resolved_without_promotion = False
        rationale.append("entity_search_id is blank, so mapping cannot be promoted even if name matches DB3")

    if "no_db3_or_db2_dj_profile_name_match" in reasons and not resolved_without_promotion:
        disposition = "repair_required_no_db_profile_match"
        repair_action = "collect_source_ref_or_create_separate_identity_review_candidate"
        rationale.append("no DB2/DB3 dj_profile name or alias match exists")

    if "short_latin_name_requires_source_ref_review" in reasons:
        disposition = "repair_required_short_latin_name_source_ref"
        repair_action = "prove_short_name_with_source_ref_before_mapping"
        resolved_without_promotion = False
        rationale.append("one/two-character Latin names require source-ref proof to avoid platform/abbreviation collisions")

    if "generic_platform_page" in " ".join(compact(item.get("evidence_text"), 260) for item in s125a_rows).casefold():
        rationale.append("S125A evidence indicates a generic platform page, not identity proof")

    if local_evidence:
        evidence_text = " ".join(item["snippet"] for item in local_evidence).casefold()
        has_acceptance_marker = any(
            marker in evidence_text
            for marker in (
                "identity_candidate_accepted_for_staging_review",
                "identity_acceptance_ready_report_only",
                "manual_source_context_accepted_for_identity_review",
                "accepted_for_identity_review",
                "atlas_social_yyyy_identity_acceptance_ready",
            )
        )
        has_missing_context_marker = any(
            marker in evidence_text
            for marker in (
                "manual_source_context_not_found_still_blocked",
                "blocked_needs_atlas_source_context",
                "needs_atlas_source_context",
                "do not promote cod.act",
            )
        )
        if has_acceptance_marker:
            rationale.append("older local evidence has staging-review identity acceptance; DB3 mapping still needs a separate projection/write gate")
            if not resolved_without_promotion:
                disposition = "repair_required_import_identity_gate_before_db3_mapping"
                repair_action = "carry_prior_identity_evidence_into_db3_mapping_gate"
        if has_missing_context_marker:
            rationale.append("older local evidence says source context was still missing or blocked")
            if not resolved_without_promotion and not has_acceptance_marker:
                disposition = "repair_required_prior_source_context_still_missing"
                repair_action = "continue_bounded_source_context_search_before_mapping"

    if not rationale:
        rationale.append("blocked row requires manual source-ref review before promotion")

    return {
        "task_id": stable_id({"s129": row.get("mapping_id"), "entity_name": row.get("entity_name"), "entity_type": row.get("entity_type")}),
        "mapping_id": row.get("mapping_id", ""),
        "entity_search_id": row.get("entity_search_id", ""),
        "entity_name": row.get("entity_name", ""),
        "entity_type": row.get("entity_type", ""),
        "db3_dj_id": row.get("db3_dj_id", ""),
        "db2_dj_id": row.get("db2_dj_id", ""),
        "original_block_reasons": sorted(reasons),
        "disposition": disposition,
        "repair_action": repair_action,
        "resolved_without_promotion": resolved_without_promotion,
        "promotion_allowed_now": promotion_allowed,
        "rationale": rationale,
        "upstream": summarize_upstream(upstream_rows),
        "s125a_rows": [
            {
                "entity_kind": compact(item.get("entity_kind"), 80),
                "disposition": compact(item.get("disposition"), 80),
                "role_hint": compact(item.get("role_hint"), 80),
                "confidence": item.get("confidence", 0),
                "evidence_text": compact(item.get("evidence_text"), 220),
            }
            for item in s125a_rows[:5]
        ],
        "local_evidence_refs": local_evidence[:5],
        "report_only": True,
        "db2_projection_allowed": False,
        "db3_identity_write_allowed": False,
        "miniapp_public_display_allowed": False,
    }


def build_repair_queue(
    *,
    s128_report_path: Path,
    s120_items_path: Path,
    s125_rows_path: Path,
    s125a_candidates_path: Path,
    evidence_paths: list[Path],
    out_dir: Path,
    scorecard_path: Path,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    s128 = load_json(s128_report_path)
    rows = [row for row in s128.get("rows", []) if isinstance(row, dict)]
    blocked_rows = [row for row in rows if row.get("mapping_status") != "candidate_ready_report_only"]
    ready_by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("mapping_status") == "candidate_ready_report_only":
            ready_by_name[normalize_name(row.get("entity_name"))].append(row)

    upstream = group_upstream_rows(load_rows(s120_items_path) + load_rows(s125_rows_path))
    s125a_by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in load_s125a_rows(s125a_candidates_path):
        s125a_by_name[normalize_name(row.get("entity_name"))].append(row)
    local_evidence = evidence_index(evidence_paths)

    tasks = [
        classify_task(
            row,
            ready_by_name=ready_by_name,
            upstream_rows=upstream.get(row_key(row), []),
            s125a_rows=s125a_by_name.get(normalize_name(row.get("entity_name")), []),
            local_evidence=local_evidence.get(normalize_name(row.get("entity_name")), []),
        )
        for row in blocked_rows
    ]
    by_disposition = Counter(task["disposition"] for task in tasks)
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": "external_link_mapping_repair_queue_ready_report_only",
        "inputs": {
            "s128_report": rel_path(s128_report_path),
            "s120_items": rel_path(s120_items_path),
            "s125_projection_rows": rel_path(s125_rows_path),
            "s125a_candidates": rel_path(s125a_candidates_path),
            "local_evidence_paths": [rel_path(path) for path in evidence_paths if path.exists()],
        },
        "outputs": {
            "report": rel_path(out_dir / "external_link_mapping_repair_queue.json"),
            "tasks": rel_path(out_dir / "external_link_mapping_repair_tasks.jsonl"),
            "scorecard": rel_path(scorecard_path),
        },
        "summary": {
            "blocked_input_count": len(blocked_rows),
            "repair_task_count": len(tasks),
            "closed_no_promotion_count": sum(1 for task in tasks if task["resolved_without_promotion"]),
            "repair_required_count": sum(1 for task in tasks if not task["resolved_without_promotion"]),
            "promotion_allowed_now_count": sum(1 for task in tasks if task["promotion_allowed_now"]),
            "by_disposition": dict(by_disposition),
            "all_blockers_accounted": len(tasks) == len(blocked_rows) and all(task["disposition"] for task in tasks),
        },
        "boundary": {
            "report_only": True,
            "db1_mutation": False,
            "db2_mutation": False,
            "db3_mutation": False,
            "db2_projection_allowed": False,
            "db3_identity_write_allowed": False,
            "miniapp_public_display_allowed": False,
            "miniapp_upload_or_release": False,
            "network_fetch": False,
            "model_call_performed": False,
            "cookie_values_read": False,
            "token_values_read": False,
        },
        "tasks": tasks,
        "secret_like_findings": [],
        "finding_count": 0,
        "next_story": "S130",
    }
    findings = secret_findings({"report": report, "tasks": tasks})
    report["secret_like_findings"] = findings
    report["finding_count"] = len(findings)
    if findings or not report["summary"]["all_blockers_accounted"]:
        report["decision"] = "external_link_mapping_repair_queue_blocked_report_only"
    atomic_write_json(out_dir / "external_link_mapping_repair_queue.json", report)
    atomic_write_jsonl(out_dir / "external_link_mapping_repair_tasks.jsonl", tasks)
    atomic_write_text(scorecard_path, render_scorecard(report))
    return report


def secret_findings(payload: Any) -> list[dict[str, str]]:
    text = json.dumps(payload, ensure_ascii=False)
    findings = []
    for match in SECRET_RE.finditer(text):
        findings.append({"pattern": "secret_like_text", "sample": match.group(0)[:16] + "..."})
        if len(findings) >= 10:
            break
    return findings


def render_scorecard(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Weekly External-Link Mapping Repair Queue S129",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Blocked input rows: `{summary['blocked_input_count']}`",
        f"- Repair tasks: `{summary['repair_task_count']}`",
        f"- Closed without promotion: `{summary['closed_no_promotion_count']}`",
        f"- Repair required: `{summary['repair_required_count']}`",
        f"- Promotion allowed now: `{summary['promotion_allowed_now_count']}`",
        f"- Finding count: `{report['finding_count']}`",
        "",
        "## Dispositions",
        "",
    ]
    for key, value in sorted(summary["by_disposition"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- Report-only repair queue.",
            "- No DB1/DB2/DB3 mutation, no DB2 projection, no DB3 identity write, no mini-program upload/release/public display.",
            "- Closed rows are no-promotion closures, not accepted mappings.",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--s128-report", type=Path, default=DEFAULT_S128_REPORT)
    parser.add_argument("--s120-items", type=Path, default=DEFAULT_S120_ITEMS)
    parser.add_argument("--s125-rows", type=Path, default=DEFAULT_S125_ROWS)
    parser.add_argument("--s125a-candidates", type=Path, default=DEFAULT_S125A_CANDIDATES)
    parser.add_argument("--evidence-path", action="append", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    evidence_paths = args.evidence_path if args.evidence_path is not None else DEFAULT_EVIDENCE_PATHS
    report = build_repair_queue(
        s128_report_path=args.s128_report,
        s120_items_path=args.s120_items,
        s125_rows_path=args.s125_rows,
        s125a_candidates_path=args.s125a_candidates,
        evidence_paths=evidence_paths,
        out_dir=args.out_dir,
        scorecard_path=args.scorecard,
    )
    print(json.dumps({"decision": report["decision"], "summary": report["summary"]}, ensure_ascii=False))
    return 0 if report["finding_count"] == 0 and report["summary"]["all_blockers_accounted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
