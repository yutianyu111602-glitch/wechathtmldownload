from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from atlas_core_common import (  # noqa: E402
    connect_readonly,
    default_stage7_reports_root,
    json_dumps,
    sha256_file,
    table_columns,
    table_exists,
    text,
    utc_now,
    write_json,
    write_jsonl,
)

DEFAULT_CORE_DB = default_stage7_reports_root() / "atlas_core_candidate_20260604" / "atlas_core.sqlite"
DEFAULT_S119_SIDECAR = default_stage7_reports_root() / "external_link_db2_sidecar_contract_s119_20260601" / "external_link_db2_sidecar.sqlite"
DEFAULT_OUT_DIR = default_stage7_reports_root() / "atlas_core_external_link_identity_mapping_20260605"

SECRET_OR_PRIVATE_RE = re.compile(
    r"(?i)(https?://|[A-Z]:\\|\\\\wsl\.localhost\\|\.env|cookie|password|secret|token=|/mnt/[cd]/|/home/)"
)

EXTERNAL_TO_CORE_TYPES = {
    "person": {"dj"},
    "organization": {"organizer", "label", "venue"},
    "club": {"venue", "organizer"},
    "venue": {"venue"},
    "label": {"label", "organizer"},
}


def normalize_name(value: Any) -> str:
    raw = text(value, 200).casefold()
    raw = re.sub(r"\s+", " ", raw)
    return raw


def stable_mapping_id(entity_search_id: str, entity_name: str, entity_type: str) -> str:
    import hashlib

    payload = json_dumps({"entity_search_id": entity_search_id, "entity_name": entity_name, "entity_type": entity_type})
    return "atlas_core_external_link_mapping:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def load_aliases(value: Any) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []
    return [text(item, 200) for item in parsed if text(item, 200)]


def load_core_name_index(core_db: Path) -> tuple[dict[str, list[dict[str, Any]]], dict[str, str]]:
    conn = connect_readonly(core_db)
    try:
        if not table_exists(conn, "core_entity") or not table_exists(conn, "entity_legacy_id"):
            raise ValueError(f"{core_db} is not an Atlas Core candidate database")
        name_index: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in conn.execute(
            """
            SELECT entity_id, entity_type, display_name, normalized_name, aliases_json,
                   primary_city, confidence, public_state
            FROM core_entity
            ORDER BY entity_id
            """
        ):
            item = {
                "entity_id": text(row["entity_id"], 120),
                "entity_type": text(row["entity_type"], 80),
                "display_name": text(row["display_name"], 200),
                "normalized_name": text(row["normalized_name"], 200),
                "primary_city": text(row["primary_city"], 80),
                "confidence": float(row["confidence"] or 0),
                "public_state": text(row["public_state"], 80),
            }
            names = {normalize_name(item["display_name"]), normalize_name(item["normalized_name"])}
            names.update(normalize_name(alias) for alias in load_aliases(row["aliases_json"]))
            for name in sorted(value for value in names if value):
                name_index[name].append(item)

        legacy_map = {
            text(row["legacy_id"], 160): text(row["canonical_entity_id"] or row["entity_id"], 160)
            for row in conn.execute("SELECT legacy_id, canonical_entity_id, entity_id FROM entity_legacy_id")
            if text(row["legacy_id"], 160)
        }
        return name_index, legacy_map
    finally:
        conn.close()


def load_external_entities(sidecar_db: Path) -> list[dict[str, Any]]:
    conn = connect_readonly(sidecar_db)
    try:
        table = "external_link_candidates"
        if not table_exists(conn, table):
            raise ValueError(f"{sidecar_db} does not contain {table}")
        cols = set(table_columns(conn, table))
        rows: dict[tuple[str, str, str], dict[str, Any]] = {}
        select_cols = [
            "sidecar_id",
            "entity_search_id",
            "entity_name",
            "entity_type",
            "platform",
            "public_category",
            "source_ref",
            "source_ref_id",
            "url_hash",
            "source_url_hash",
            "canonical_url_key_hash",
            "fetch_status",
            "runner_decision",
        ]
        available = [col for col in select_cols if col in cols]
        for row in conn.execute(f"SELECT {', '.join(available)} FROM {table} ORDER BY 1"):
            data = {key: row[key] for key in available}
            entity_search_id = text(data.get("entity_search_id"), 160)
            entity_name = text(data.get("entity_name"), 200)
            entity_type = text(data.get("entity_type"), 80)
            key = (entity_search_id, entity_name, entity_type)
            current = rows.setdefault(
                key,
                {
                    "entity_search_id": entity_search_id,
                    "entity_name": entity_name,
                    "entity_type": entity_type,
                    "normalized_entity_name": normalize_name(entity_name),
                    "row_count": 0,
                    "sidecar_ids": set(),
                    "platforms": set(),
                    "public_categories": set(),
                    "source_refs": set(),
                    "url_hashes": set(),
                    "fetch_statuses": set(),
                    "runner_decisions": set(),
                },
            )
            current["row_count"] += 1
            for field, target in [
                ("sidecar_id", "sidecar_ids"),
                ("platform", "platforms"),
                ("public_category", "public_categories"),
                ("source_ref", "source_refs"),
                ("source_ref_id", "source_refs"),
                ("url_hash", "url_hashes"),
                ("source_url_hash", "url_hashes"),
                ("canonical_url_key_hash", "url_hashes"),
                ("fetch_status", "fetch_statuses"),
                ("runner_decision", "runner_decisions"),
            ]:
                value = text(data.get(field), 240)
                if value:
                    current[target].add(value)
        output = []
        for item in rows.values():
            output.append(
                {
                    **{key: item[key] for key in ["entity_search_id", "entity_name", "entity_type", "normalized_entity_name", "row_count"]},
                    "sidecar_sample_ids": sorted(item["sidecar_ids"])[:10],
                    "platforms": sorted(item["platforms"]),
                    "public_categories": sorted(item["public_categories"]),
                    "source_refs": sorted(item["source_refs"]),
                    "url_hash_count": len(item["url_hashes"]),
                    "fetch_statuses": sorted(item["fetch_statuses"]),
                    "runner_decisions": sorted(item["runner_decisions"]),
                }
            )
        return sorted(output, key=lambda item: (-int(item["row_count"]), item["normalized_entity_name"], item["entity_search_id"]))
    finally:
        conn.close()


def collapse_matches(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for match in matches:
        current = by_id.setdefault(match["entity_id"], dict(match))
        current["confidence"] = max(float(current.get("confidence") or 0), float(match.get("confidence") or 0))
    return sorted(by_id.values(), key=lambda item: (-float(item.get("confidence") or 0), item["entity_type"], item["entity_id"]))


def compatibility_status(external_type: str, match: dict[str, Any]) -> tuple[bool, str]:
    raw = normalize_name(external_type)
    if raw in {"event", "work"}:
        return False, f"external_entity_type_not_identity_subject:{raw}"
    allowed = EXTERNAL_TO_CORE_TYPES.get(raw)
    if not allowed:
        return False, f"external_entity_type_requires_manual_policy:{raw or 'missing'}"
    core_type = text(match.get("entity_type"), 80)
    if core_type not in allowed:
        return False, f"core_entity_type_not_compatible:{raw}->{core_type}"
    return True, "compatible_type"


def classify_entity(entity: dict[str, Any], name_index: dict[str, list[dict[str, Any]]], legacy_map: dict[str, str]) -> dict[str, Any]:
    entity_search_id = entity["entity_search_id"]
    matches = collapse_matches(name_index.get(entity["normalized_entity_name"], []))
    direct = legacy_map.get(entity_search_id, "")
    reasons: list[str] = []
    evidence: list[str] = []
    status = "blocked"
    confidence_band = "none"
    confidence_score = 0
    target = ""
    match_method = []

    if not entity_search_id:
        reasons.append("missing_entity_search_id")
    if not entity["normalized_entity_name"]:
        reasons.append("missing_entity_name")
    if direct:
        status = "already_mapped_in_entity_legacy_id"
        confidence_band = "high"
        confidence_score = 100
        target = direct
        match_method.append("entity_legacy_id_direct")
        evidence.append("entity_legacy_id_direct_match")
    elif len(matches) == 1:
        compatible, reason = compatibility_status(entity["entity_type"], matches[0])
        if compatible and entity_search_id:
            evidence.append(reason)
            status = "candidate_ready_report_only"
            confidence_band = "medium"
            confidence_score = 80
            target = matches[0]["entity_id"]
            match_method.append("normalized_name_or_alias_exact_singleton")
        else:
            reasons.append(reason)
            status = "blocked_before_mapping"
    elif len(matches) > 1:
        status = "blocked_ambiguous"
        reasons.append("ambiguous_multiple_core_entity_matches")
    else:
        status = "blocked_no_core_match"
        reasons.append("no_core_entity_name_or_alias_match")

    if entity["entity_type"] in {"event", "work"} and status == "candidate_ready_report_only":
        status = "blocked_before_mapping"

    patch_preview = {}
    if status == "candidate_ready_report_only":
        patch_preview = {
            "entity_id": target,
            "canonical_entity_id": target,
            "legacy_layer": "S119_external_link_sidecar",
            "legacy_table": "external_link_candidates",
            "legacy_id": entity_search_id,
            "legacy_name": entity["entity_name"],
            "source_report": "atlas_core_external_link_identity_mapping_20260605",
            "is_primary": 0,
            "valid_from": "",
            "valid_to": "",
            "write_allowed_now": False,
        }

    return {
        "mapping_id": stable_mapping_id(entity_search_id, entity["entity_name"], entity["entity_type"]),
        **entity,
        "target_entity_id": target,
        "candidate_match_count": len(matches),
        "candidate_matches": matches[:20],
        "match_methods": match_method,
        "mapping_evidence": evidence,
        "mapping_status": status,
        "confidence_band": confidence_band,
        "confidence_score": confidence_score,
        "block_reasons": reasons,
        "entity_legacy_id_patch_preview": patch_preview,
        "report_only": True,
        "core_write_allowed_now": False,
        "db3_write_allowed_now": False,
        "accepted_for_graph_allowed_now": False,
    }


def leak_findings(payload: Any) -> list[dict[str, str]]:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    findings = []
    for match in SECRET_OR_PRIVATE_RE.finditer(raw):
        findings.append({"kind": "raw_url_or_secret_or_private_path", "sample": match.group(0)[:40]})
        if len(findings) >= 20:
            break
    return findings


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Atlas Core External-Link Identity Mapping Workbench",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- decision: `{report['decision']}`",
        f"- external_group_count: `{summary['external_group_count']}`",
        f"- candidate_ready_count: `{summary['candidate_ready_count']}`",
        f"- already_mapped_count: `{summary['already_mapped_count']}`",
        f"- blocked_count: `{summary['blocked_count']}`",
        f"- source_hashes_unchanged: `{report['source_hashes_unchanged']}`",
        f"- leak_finding_count: `{report['leak_finding_count']}`",
        "",
        "## Status Counts",
        "",
    ]
    for key, value in sorted(summary["by_mapping_status"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- Report-only workbench.",
            "- No Atlas Core, DB2, DB3, miniapp, graph, or production write.",
            "- Candidate rows are patch previews only; `write_allowed_now` stays false.",
            "- Raw URLs are not emitted.",
            "",
            "## Next",
            "",
            "1. Review `atlas_core_external_link_identity_mapping_candidates.jsonl`.",
            "2. Review `atlas_core_external_link_identity_mapping_blockers.jsonl`.",
            "3. Only after controller approval, feed candidate patch previews into the next report-local core build.",
        ]
    )
    return "\n".join(lines) + "\n"


def build_mapping(core_db: Path, external_link_sidecar: Path, out_dir: Path) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    sources = {"core_db": core_db.resolve(), "external_link_sidecar": external_link_sidecar.resolve()}
    before = {label: sha256_file(path) for label, path in sources.items()}
    name_index, legacy_map = load_core_name_index(core_db)
    external_entities = load_external_entities(external_link_sidecar)
    rows = [classify_entity(entity, name_index, legacy_map) for entity in external_entities]
    candidates = [row for row in rows if row["mapping_status"] == "candidate_ready_report_only"]
    blockers = [row for row in rows if row["mapping_status"].startswith("blocked")]
    patch_preview = [row["entity_legacy_id_patch_preview"] for row in candidates if row["entity_legacy_id_patch_preview"]]
    after = {label: sha256_file(path) for label, path in sources.items()}
    source_hashes_unchanged = before == after
    by_status = Counter(row["mapping_status"] for row in rows)
    payload_for_scan = {"rows": rows, "patch_preview": patch_preview}
    findings = leak_findings(payload_for_scan)
    blockers_for_decision = []
    if not source_hashes_unchanged:
        blockers_for_decision.append("source_hash_changed")
    if findings:
        blockers_for_decision.append("leak_findings_present")
    report = {
        "schema_version": "atlas_core_external_link_identity_mapping.v1",
        "generated_at": utc_now(),
        "decision": "atlas_core_external_link_identity_mapping_ready_report_only" if not blockers_for_decision else "atlas_core_external_link_identity_mapping_blocked_report_only",
        "blockers": blockers_for_decision,
        "inputs": {label: str(path) for label, path in sources.items()},
        "outputs": {
            "report": str(out_dir / "atlas_core_external_link_identity_mapping_report.json"),
            "rows": str(out_dir / "atlas_core_external_link_identity_mapping_rows.jsonl"),
            "candidates": str(out_dir / "atlas_core_external_link_identity_mapping_candidates.jsonl"),
            "blockers": str(out_dir / "atlas_core_external_link_identity_mapping_blockers.jsonl"),
            "entity_legacy_id_patch_preview": str(out_dir / "entity_legacy_id_patch_preview.jsonl"),
            "summary_md": str(out_dir / "atlas_core_external_link_identity_mapping_summary.md"),
        },
        "source_hashes_before": before,
        "source_hashes_after": after,
        "source_hashes_unchanged": source_hashes_unchanged,
        "summary": {
            "external_group_count": len(rows),
            "candidate_ready_count": len(candidates),
            "already_mapped_count": sum(1 for row in rows if row["mapping_status"] == "already_mapped_in_entity_legacy_id"),
            "blocked_count": len(blockers),
            "patch_preview_count": len(patch_preview),
            "by_mapping_status": dict(by_status),
        },
        "safety": {
            "report_only": True,
            "core_write_executed": False,
            "db2_write_executed": False,
            "db3_write_executed": False,
            "production_write_executed": False,
            "raw_url_emitted": False,
            "source_hash_guard_enforced": True,
        },
        "leak_findings": findings,
        "leak_finding_count": len(findings),
    }
    write_json(out_dir / "atlas_core_external_link_identity_mapping_report.json", report)
    write_jsonl(out_dir / "atlas_core_external_link_identity_mapping_rows.jsonl", rows)
    write_jsonl(out_dir / "atlas_core_external_link_identity_mapping_candidates.jsonl", candidates)
    write_jsonl(out_dir / "atlas_core_external_link_identity_mapping_blockers.jsonl", blockers)
    write_jsonl(out_dir / "entity_legacy_id_patch_preview.jsonl", patch_preview)
    (out_dir / "atlas_core_external_link_identity_mapping_summary.md").write_text(render_markdown(report), encoding="utf-8")
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build report-only S119 external-link identity mapping candidates for Atlas Core.")
    parser.add_argument("--core-db", type=Path, default=DEFAULT_CORE_DB)
    parser.add_argument("--external-link-sidecar", type=Path, default=DEFAULT_S119_SIDECAR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> dict[str, Any]:
    args = parse_args(argv)
    return build_mapping(args.core_db, args.external_link_sidecar, args.out_dir)


if __name__ == "__main__":
    print(json_dumps(main()))
