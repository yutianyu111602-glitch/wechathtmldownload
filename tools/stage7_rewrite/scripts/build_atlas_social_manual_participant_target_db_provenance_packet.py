#!/usr/bin/env python3
"""Build a report-only target DB provenance packet for manual participants.

This packet does not open SQLite. It audits bounded upstream/SSOT artifacts for
an explicit source/raw target DB reference before the real snapshot gate can run
with --target-db.
"""
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
SCHEMA_VERSION = "stage7_atlas_social_manual_participant_target_db_provenance.v1"

DEFAULT_BLOCKED_ROWS = (
    STAGE7_ROOT
    / "reports"
    / "atlas_social_manual_participant_db_real_snapshot_gate_q6_20260526"
    / "manual_participant_db_real_snapshot_blocked_rows.jsonl"
)
DEFAULT_REAL_SUMMARY = (
    STAGE7_ROOT
    / "reports"
    / "atlas_social_manual_participant_db_real_snapshot_gate_q6_20260526"
    / "manual_participant_db_real_snapshot_gate_summary.json"
)
DEFAULT_PREWRITE_ROWS = (
    STAGE7_ROOT
    / "reports"
    / "atlas_social_manual_participant_db_prewrite_snapshot_q6_20260526"
    / "manual_participant_db_prewrite_snapshot_rows.jsonl"
)
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_social_manual_participant_target_db_provenance_q6_20260526"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T6_MANUAL_PARTICIPANT_TARGET_DB_PROVENANCE_20260526.md"

DEFAULT_CANDIDATE_SOURCES = [
    REPO_ROOT / "docs" / "current-runtime.md",
    REPO_ROOT / "LONGRUN_STATE.md",
    REPO_ROOT / "docs" / "DOCUMENTATION_INDEX.md",
    REPO_ROOT / "docs" / "threads" / "THREADS_INDEX_20260522.md",
    REPO_ROOT / "docs" / "threads" / "T5_atlas_dj_serving_graph_20260522.md",
    REPO_ROOT / "docs" / "threads" / "T6_deepseektui_ldr_sidecar_20260522.md",
    REPO_ROOT / "docs" / "threads" / "T7_docs_ssot_control_20260522.md",
    REPO_ROOT / "docs" / "CURRENT_CODE_MAP.md",
    REPO_ROOT / "AGENTS.md",
    REPO_ROOT / "reports" / "ATLAS_T6_MANUAL_PARTICIPANT_DB_REAL_SNAPSHOT_GATE_20260526.md",
    REPO_ROOT / "reports" / "ATLAS_T6_MANUAL_PARTICIPANT_DB_PREWRITE_SNAPSHOT_PACKET_20260526.md",
    REPO_ROOT / "reports" / "ATLAS_T6_MANUAL_PARTICIPANT_DB_WRITE_GATE_20260526.md",
    REPO_ROOT / "reports" / "ATLAS_T6_MANUAL_PARTICIPANT_READBACK_PREFLIGHT_20260526.md",
    DEFAULT_REAL_SUMMARY,
    DEFAULT_BLOCKED_ROWS,
    DEFAULT_PREWRITE_ROWS,
    DEFAULT_PREWRITE_ROWS.parent / "manual_participant_db_prewrite_snapshot_summary.json",
    STAGE7_ROOT
    / "reports"
    / "atlas_social_manual_participant_db_write_gate_q6_20260526"
    / "manual_participant_db_write_gate_summary.json",
    STAGE7_ROOT
    / "reports"
    / "atlas_social_manual_participant_db_write_gate_q6_20260526"
    / "manual_participant_db_write_gate_targets.jsonl",
    STAGE7_ROOT
    / "reports"
    / "atlas_social_manual_participant_readback_preflight_q6_20260526"
    / "manual_participant_readback_preflight_summary.json",
    STAGE7_ROOT
    / "reports"
    / "atlas_social_manual_participant_readback_preflight_q6_20260526"
    / "readback_schema_snapshot.json",
]

REL_DB_RE = re.compile(
    r"(?:(?:reports|tools|docs|services)[\\/][^\s`\"')\]}]+?\.(?:sqlite|sqlite3|db))",
    re.I,
)
URL_RE = re.compile(r"https?://", re.I)
SECRET_RE = re.compile(r"\b(secret|token|cookie|password|api[_-]?key|authorization)\b", re.I)
LOCAL_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"']+|/mnt/[A-Za-z][^\s\"']*|/home/[^\s\"']+|\\\\[A-Za-z0-9_.-]+[\\/][^\s\"']+",
    re.I,
)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def compact(value: Any, limit: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").casefold()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for target DB provenance: {path}")


def display_path(path: Path, repo_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(repo_root.resolve())).replace("\\", "/")
    except ValueError:
        return path.name


def normalize_ref(value: str, repo_root: Path) -> str | None:
    raw = compact(value, 1000).strip("`\"'.,;)")
    if not raw:
        return None
    lowered = raw.replace("\\", "/").casefold()
    if lowered.startswith("d:/") or lowered.startswith("/mnt/d/"):
        return "redacted_d_drive_path"
    path = Path(raw)
    if path.is_absolute():
        try:
            return str(path.resolve().relative_to(repo_root.resolve())).replace("\\", "/")
        except ValueError:
            return "redacted_absolute_path_" + sha256_text(raw)[:16]
    normalized = re.sub(r"/+", "/", raw.replace("\\", "/"))
    if not re.match(r"^(reports|tools|docs|services)/", normalized, re.I):
        return None
    return normalized


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


def read_json(path: Path, label: str) -> dict[str, Any]:
    reject_d_path(path, label)
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    return value if isinstance(value, dict) else {}


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


def scan_payload(payload: Any) -> dict[str, int]:
    text = canonical_json(payload)
    return {
        "public_url_hits": len(URL_RE.findall(text)),
        "sensitive_key_hits": len(SECRET_RE.findall(text)),
        "local_path_hits": len(LOCAL_PATH_RE.findall(text)),
    }


def iter_json_strings(value: Any, path: str = "$") -> Iterable[tuple[str, str]]:
    if isinstance(value, dict):
        for key, item in value.items():
            yield from iter_json_strings(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from iter_json_strings(item, f"{path}[{index}]")
    elif isinstance(value, str):
        yield path, value


def source_tier(source_path: Path, direct_sources: set[str], repo_root: Path) -> str:
    rel = display_path(source_path, repo_root)
    if rel in direct_sources:
        return "direct_upstream_gate"
    if rel.startswith("docs/") or rel == "AGENTS.md" or rel == "LONGRUN_STATE.md":
        return "current_ssot_text"
    return "supporting_artifact"


def classify_candidate(path_ref: str, field_path: str, context: str, tier: str) -> tuple[str, bool]:
    text = f"{path_ref} {field_path} {context}".casefold()
    path_lower = path_ref.casefold()
    if "atlas_serving" in path_lower or path_lower.endswith("atlas_serving.sqlite"):
        return "serving_read_model_rejected_not_source_raw_target", False
    if "participant_graph_delta.sqlite" in path_lower:
        return "derived_delta_rejected_not_source_raw_target", False
    direct_target = (
        ("target_db" in field_path.casefold() and tier != "current_ssot_text")
        or (tier == "direct_upstream_gate" and "target db" in context.casefold())
    )
    if direct_target:
        return "explicit_source_raw_target_db_candidate", True
    if path_lower.endswith("atlas.sqlite") or "atlas_local_sqlite_db" in path_lower:
        return "source_db_reference_not_explicit_q6_target", False
    return "sqlite_reference_review_only", False


def extract_candidates_from_json(path: Path, value: Any, direct_sources: set[str], repo_root: Path) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    tier = source_tier(path, direct_sources, repo_root)
    for field_path, text in iter_json_strings(value):
        refs = set(REL_DB_RE.findall(text))
        normalized_value = normalize_ref(text, repo_root)
        if normalized_value and normalized_value.endswith((".sqlite", ".sqlite3", ".db")):
            refs.add(normalized_value)
        for ref in sorted(refs):
            normalized = normalize_ref(ref, repo_root)
            if not normalized:
                continue
            classification, direct_ready = classify_candidate(normalized, field_path, text, tier)
            candidates.append(
                {
                    "schema_version": SCHEMA_VERSION + ".candidate_ref",
                    "path_ref": normalized,
                    "path_sha256": sha256_text(normalized),
                    "source_file": display_path(path, repo_root),
                    "source_tier": tier,
                    "field_path": compact(field_path, 260),
                    "classification": classification,
                    "direct_explicit_target_db_candidate": direct_ready,
                }
            )
    return candidates


def extract_candidates_from_text(path: Path, text: str, direct_sources: set[str], repo_root: Path) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    tier = source_tier(path, direct_sources, repo_root)
    for line_no, line in enumerate(text.splitlines(), start=1):
        for ref in sorted(set(REL_DB_RE.findall(line))):
            normalized = normalize_ref(ref, repo_root)
            if not normalized:
                continue
            classification, direct_ready = classify_candidate(normalized, f"line:{line_no}", line, tier)
            candidates.append(
                {
                    "schema_version": SCHEMA_VERSION + ".candidate_ref",
                    "path_ref": normalized,
                    "path_sha256": sha256_text(normalized),
                    "source_file": display_path(path, repo_root),
                    "source_tier": tier,
                    "field_path": f"line:{line_no}",
                    "classification": classification,
                    "direct_explicit_target_db_candidate": direct_ready,
                }
            )
    return candidates


def load_candidate_refs(paths: list[Path], direct_sources: set[str], repo_root: Path) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    seen = set()
    for path in paths:
        reject_d_path(path, "candidate_source")
        if not path.exists() or path.is_dir():
            continue
        suffix = path.suffix.casefold()
        if suffix in {".json"}:
            value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
            rows = extract_candidates_from_json(path, value, direct_sources, repo_root)
        elif suffix in {".jsonl"}:
            rows = []
            for item in read_jsonl(path, "candidate_source_jsonl"):
                rows.extend(extract_candidates_from_json(path, item, direct_sources, repo_root))
        else:
            rows = extract_candidates_from_text(path, path.read_text(encoding="utf-8", errors="replace"), direct_sources, repo_root)
        for row in rows:
            key = (row["path_ref"], row["source_file"], row["field_path"], row["classification"])
            if key in seen:
                continue
            seen.add(key)
            refs.append(row)
    return refs


def dedupe_candidate_refs(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for ref in refs:
        key = (ref["path_ref"], ref["classification"])
        current = grouped.setdefault(
            key,
            {
                "schema_version": SCHEMA_VERSION + ".candidate_ref_rollup",
                "path_ref": ref["path_ref"],
                "path_sha256": ref["path_sha256"],
                "classification": ref["classification"],
                "direct_explicit_target_db_candidate": ref["direct_explicit_target_db_candidate"],
                "source_files": [],
                "source_tiers": [],
                "field_paths": [],
                "existing_repo_path": False,
            },
        )
        current["direct_explicit_target_db_candidate"] = (
            current["direct_explicit_target_db_candidate"] or ref["direct_explicit_target_db_candidate"]
        )
        for key_name, value in [
            ("source_files", ref["source_file"]),
            ("source_tiers", ref["source_tier"]),
            ("field_paths", ref["field_path"]),
        ]:
            if value not in current[key_name]:
                current[key_name].append(value)
    return sorted(grouped.values(), key=lambda row: (row["classification"], row["path_ref"]))


def existing_paths(refs: list[dict[str, Any]], repo_root: Path) -> None:
    for ref in refs:
        if ref["path_ref"].startswith("redacted_"):
            ref["existing_repo_path"] = False
            continue
        path = repo_root / ref["path_ref"]
        ref["existing_repo_path"] = path.exists()


def build_packet(
    blocked_rows_path: Path,
    real_summary_path: Path,
    prewrite_rows_path: Path,
    candidate_sources: list[Path],
    out_dir: Path,
    report_path: Path,
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    generated_at = now_iso()
    blocked_rows = read_jsonl(blocked_rows_path, "blocked_rows")
    prewrite_rows = read_jsonl(prewrite_rows_path, "prewrite_rows")
    real_summary = read_json(real_summary_path, "real_summary")
    direct_sources = {
        display_path(real_summary_path, repo_root),
        display_path(blocked_rows_path, repo_root),
        display_path(prewrite_rows_path, repo_root),
        display_path(DEFAULT_PREWRITE_ROWS.parent / "manual_participant_db_prewrite_snapshot_summary.json", repo_root),
        "tools/stage7_rewrite/reports/atlas_social_manual_participant_db_write_gate_q6_20260526/manual_participant_db_write_gate_summary.json",
        "tools/stage7_rewrite/reports/atlas_social_manual_participant_db_write_gate_q6_20260526/manual_participant_db_write_gate_targets.jsonl",
        "tools/stage7_rewrite/reports/atlas_social_manual_participant_readback_preflight_q6_20260526/manual_participant_readback_preflight_summary.json",
        "tools/stage7_rewrite/reports/atlas_social_manual_participant_readback_preflight_q6_20260526/readback_schema_snapshot.json",
    }
    candidate_refs = dedupe_candidate_refs(load_candidate_refs(candidate_sources, direct_sources, repo_root))
    existing_paths(candidate_refs, repo_root)

    direct_ready_refs = [
        ref for ref in candidate_refs if ref["direct_explicit_target_db_candidate"] and ref["existing_repo_path"]
    ]
    serving_rejected = [
        ref for ref in candidate_refs if ref["classification"] == "serving_read_model_rejected_not_source_raw_target"
    ]
    source_refs_unlinked = [
        ref for ref in candidate_refs if ref["classification"] == "source_db_reference_not_explicit_q6_target"
    ]

    blockers = []
    if not direct_ready_refs:
        blockers.append("no_existing_explicit_source_raw_target_db_in_direct_upstream")
    if serving_rejected:
        blockers.append("serving_read_model_candidates_rejected")
    if source_refs_unlinked:
        blockers.append("source_db_references_not_bound_to_q6_manual_participant_gate")

    provenance_blocked_rows = []
    for row in blocked_rows:
        provenance_blocked_rows.append(
            {
                "schema_version": SCHEMA_VERSION + ".blocked_row",
                "generated_at": generated_at,
                "selector_hash": compact(row.get("selector_hash"), 100),
                "contract_row_sha256": compact(row.get("contract_row_sha256"), 100),
                "blockers": blockers or ["target_db_provenance_requires_real_snapshot_gate"],
                "write_execution_allowed_now": False,
            }
        )

    ready_rows = []
    for ref in direct_ready_refs:
        for row in prewrite_rows:
            ready_rows.append(
                {
                    "schema_version": SCHEMA_VERSION + ".ready_row",
                    "generated_at": generated_at,
                    "selector_hash": compact(row.get("selector_hash"), 100),
                    "contract_row_sha256": compact(row.get("contract_row_sha256"), 100),
                    "target_db_path_ref": ref["path_ref"],
                    "target_db_path_sha256": ref["path_sha256"],
                    "next_command": "run real snapshot gate with explicit --target-db",
                    "write_execution_allowed_now": False,
                }
            )

    leak_counts = scan_payload(candidate_refs + provenance_blocked_rows + ready_rows)
    class_counts = Counter(ref["classification"] for ref in candidate_refs)
    failed_checks = sorted(
        set(
            (["target_db_provenance_blocked"] if not direct_ready_refs else [])
            + [key for key, value in leak_counts.items() if value]
        )
    )
    decision = (
        "atlas_social_manual_participant_target_db_provenance_ready_report_only"
        if direct_ready_refs and not failed_checks
        else "atlas_social_manual_participant_target_db_provenance_blocked_report_only"
    )
    counts = {
        "input_real_snapshot_blocked_rows": len(blocked_rows),
        "input_prewrite_rows": len(prewrite_rows),
        "candidate_ref_rows": len(candidate_refs),
        "unique_candidate_paths": len({ref["path_ref"] for ref in candidate_refs}),
        "direct_existing_explicit_target_db_paths": len({ref["path_ref"] for ref in direct_ready_refs}),
        "serving_read_model_rejected_paths": len({ref["path_ref"] for ref in serving_rejected}),
        "source_db_reference_unlinked_paths": len({ref["path_ref"] for ref in source_refs_unlinked}),
        "target_db_ready_for_real_snapshot_rows": len(ready_rows),
        "target_db_provenance_blocked_rows": len(provenance_blocked_rows),
        "write_execution_allowed_rows": 0,
    }
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "decision": decision,
        "failed_checks": failed_checks,
        "counts": counts,
        "classification_counts": dict(sorted(class_counts.items())),
        "leak_counts": leak_counts,
        "inputs": {
            "blocked_rows": display_path(blocked_rows_path, repo_root),
            "real_snapshot_summary": display_path(real_summary_path, repo_root),
            "prewrite_rows": display_path(prewrite_rows_path, repo_root),
            "candidate_source_count": len(candidate_sources),
            "upstream_decision": compact(real_summary.get("decision"), 160),
        },
        "outputs": {
            "candidate_refs": display_path(out_dir / "target_db_candidate_refs.jsonl", repo_root),
            "blocked_rows": display_path(out_dir / "target_db_provenance_blocked_rows.jsonl", repo_root),
            "ready_rows": display_path(out_dir / "target_db_ready_for_real_snapshot_rows.jsonl", repo_root),
            "summary_json": display_path(out_dir / "target_db_provenance_summary.json", repo_root),
            "summary_md": display_path(out_dir / "target_db_provenance_summary.md", repo_root),
            "report": display_path(report_path, repo_root),
        },
        "next_cursor": display_path(out_dir / "target_db_provenance_blocked_rows.jsonl", repo_root),
        "next_gate": (
            "Only rerun the real snapshot gate if a direct upstream artifact names an existing explicit source/raw target DB."
        ),
        "boundary": {
            "report_only": True,
            "target_db_opened_read_only": False,
            "source_raw_db_write_executed": False,
            "serving_sqlite_write_or_rebuild_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "production_sqlite_write_executed": False,
            "public_pointer_update_executed": False,
            "deploy_executed": False,
            "mini_program_upload_or_review_executed": False,
            "memory_write_executed": False,
            "network_call_executed": False,
            "model_call_executed": False,
            "credential_read_executed": False,
            "d_root_scan_executed": False,
        },
        "write_guards": {
            "write_execution_allowed_now": False,
            "source_sqlite_write_allowed": False,
            "serving_rebuild_allowed": False,
            "graph_write_allowed": False,
            "public_serving_field_allowed": False,
            "memory_write_allowed": False,
        },
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(out_dir / "target_db_candidate_refs.jsonl", candidate_refs)
    write_jsonl(out_dir / "target_db_provenance_blocked_rows.jsonl", provenance_blocked_rows)
    write_jsonl(out_dir / "target_db_ready_for_real_snapshot_rows.jsonl", ready_rows)
    write_json(out_dir / "target_db_provenance_summary.json", summary)
    summary_md = "\n".join(
        [
            "# Atlas T6 Manual Participant Target DB Provenance - 2026-05-26",
            "",
            f"- Decision: `{decision}`",
            f"- Failed checks: `{failed_checks}`",
            f"- Input real-snapshot blocked rows: `{counts['input_real_snapshot_blocked_rows']}`",
            f"- Candidate refs / unique paths: `{counts['candidate_ref_rows']}` / `{counts['unique_candidate_paths']}`",
            f"- Direct existing explicit target DB paths: `{counts['direct_existing_explicit_target_db_paths']}`",
            f"- Serving read-model rejected paths: `{counts['serving_read_model_rejected_paths']}`",
            f"- Source DB references not bound to Q6 gate: `{counts['source_db_reference_unlinked_paths']}`",
            f"- Ready rows / blocked rows: `{counts['target_db_ready_for_real_snapshot_rows']}` / `{counts['target_db_provenance_blocked_rows']}`",
            f"- Leak hits: `{leak_counts['public_url_hits']}/{leak_counts['sensitive_key_hits']}/{leak_counts['local_path_hits']}`",
            f"- Next cursor: `{summary['next_cursor']}`",
            "",
        ]
    )
    write_text(out_dir / "target_db_provenance_summary.md", summary_md)
    report = "\n".join(
        [
            "# Atlas T6 Manual Participant Target DB Provenance - 2026-05-26",
            "",
            "## Decision",
            "",
            f"`{decision}`",
            "",
            "## Findings",
            "",
            "- The 07:45 real snapshot gate is still blocked because no direct upstream artifact names an existing explicit source/raw target DB.",
            "- Serving read-model SQLite references are rejected for this gate.",
            "- Source DB references from other lanes remain evidence only until a Q6 manual participant gate explicitly binds them.",
            "",
            "## Counts",
            "",
            f"- Candidate refs / unique paths: `{counts['candidate_ref_rows']}` / `{counts['unique_candidate_paths']}`.",
            f"- Direct existing explicit target DB paths: `{counts['direct_existing_explicit_target_db_paths']}`.",
            f"- Ready rows / blocked rows: `{counts['target_db_ready_for_real_snapshot_rows']}` / `{counts['target_db_provenance_blocked_rows']}`.",
            f"- Leak hits: `{leak_counts['public_url_hits']}/{leak_counts['sensitive_key_hits']}/{leak_counts['local_path_hits']}`.",
            "",
            "## Boundary",
            "",
            "Report-only. No SQLite database was opened, no source/raw DB write occurred, and serving/graph/vector/public/deploy/upload/memory state stayed closed.",
            "",
            "## Next Cursor",
            "",
            f"`{summary['next_cursor']}`",
            "",
        ]
    )
    write_text(report_path, report)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blocked-rows", type=Path, default=DEFAULT_BLOCKED_ROWS)
    parser.add_argument("--real-summary", type=Path, default=DEFAULT_REAL_SUMMARY)
    parser.add_argument("--prewrite-rows", type=Path, default=DEFAULT_PREWRITE_ROWS)
    parser.add_argument("--candidate-source", type=Path, action="append", default=None)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    candidate_sources = args.candidate_source or DEFAULT_CANDIDATE_SOURCES
    summary = build_packet(
        args.blocked_rows,
        args.real_summary,
        args.prewrite_rows,
        candidate_sources,
        args.out_dir,
        args.report,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not summary["failed_checks"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
