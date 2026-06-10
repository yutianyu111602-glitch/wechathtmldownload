from __future__ import annotations

import argparse
import gzip
import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from atlas_core_common import (  # noqa: E402
    add_common_args,
    default_stage7_reports_root,
    json_dumps,
    row_count,
    sha256_file,
    write_json,
)

DEFAULT_CANDIDATE_OUT_DIR = default_stage7_reports_root() / "atlas_core_candidate_20260604"
DEFAULT_READINESS_OUT_DIR = default_stage7_reports_root() / "atlas_core_migration_readiness_20260604"


def resolve_path(path: Path) -> Path:
    return path.expanduser().resolve()


def is_relative_to(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def source_paths(args: argparse.Namespace) -> dict[str, Path]:
    return {
        "db1": resolve_path(args.db1),
        "db2": resolve_path(args.db2),
        "db3": resolve_path(args.db3),
        "external_link_sidecar": resolve_path(args.external_link_sidecar),
        "s232d3b8_candidates": resolve_path(args.s232d3b8_candidates),
    }


def file_hashes(paths: dict[str, Path]) -> dict[str, str]:
    hashes = {}
    for label, path in paths.items():
        if not path.exists():
            raise FileNotFoundError(f"source file missing: {label}={path}")
        hashes[label] = sha256_file(path)
    return hashes


def validate_output_paths(args: argparse.Namespace, sources: dict[str, Path]) -> dict[str, Path]:
    reports_root = resolve_path(default_stage7_reports_root())
    out_dir = resolve_path(args.out_dir)
    readiness_out_dir = resolve_path(args.readiness_out_dir)
    if not args.allow_outside_stage7_reports:
        for label, path in {"out_dir": out_dir, "readiness_out_dir": readiness_out_dir}.items():
            if not is_relative_to(path, reports_root):
                raise ValueError(f"{label} must stay under {reports_root}: {path}")

    outputs = {
        "candidate_out_dir": out_dir,
        "readiness_out_dir": readiness_out_dir,
        "atlas_core": out_dir / "atlas_core.sqlite",
        "atlas_serving": out_dir / "atlas_serving.sqlite",
        "atlas_miniapp": out_dir / "atlas_miniapp.sqlite",
        "atlas_index": out_dir / "atlas_index.json.gz",
    }
    source_set = {path for path in sources.values()}
    for label, path in outputs.items():
        if path in source_set:
            raise ValueError(f"refusing to use source file as output: {label}={path}")
    return outputs


def parse_json_output(raw: str) -> Any:
    raw = raw.strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return {"raw_stdout": raw[-4000:]}


def run_step(label: str, command: list[str], cwd: Path) -> dict[str, Any]:
    import time
    started = time.monotonic()
    completed = subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)
    elapsed = round(time.monotonic() - started, 3)
    result = {
        "label": label,
        "command": command,
        "returncode": completed.returncode,
        "elapsed_seconds": elapsed,
        "stdout": parse_json_output(completed.stdout),
        "stderr_tail": completed.stderr[-4000:],
    }
    if completed.returncode != 0:
        raise RuntimeError(json_dumps(result))
    return result


def table_counts(db_path: Path, tables: list[str]) -> dict[str, int]:
    conn = sqlite3.connect(db_path)
    try:
        return {table: row_count(conn, table) for table in tables}
    finally:
        conn.close()


def readback(outputs: dict[str, Path]) -> dict[str, Any]:
    serving_db = outputs["atlas_serving"]
    miniapp_db = outputs["atlas_miniapp"]
    core_db = outputs["atlas_core"]
    index_path = outputs["atlas_index"]

    serving_expected = {
        "canonical_subject",
        "dj_profile",
        "performance_event",
        "dj_event",
        "dj_relation_rollup",
        "dj_venue_rollup",
        "evidence_ref",
        "activity_event_detail",
        "activity_evidence_ref",
        "search_document",
        "search_document_fts",
        "search_document_fts_unicode61",
        "graph_window_cache",
    }
    miniapp_expected = {
        "subject",
        "dj_profile",
        "dj_event",
        "dj_collaborator",
        "dj_venue",
        "source_ref",
        "dj_identity_redirect",
        "dj_identity_profile_disposition",
    }
    index_expected = {"subjects", "profiles", "events", "collabs", "dj_venues", "venue_events", "venue_by_name", "source_refs"}

    serving = sqlite3.connect(serving_db)
    try:
        serving_tables = {row[0] for row in serving.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
        fts_counts = {
            query: int(serving.execute("SELECT COUNT(*) FROM search_document_fts WHERE search_document_fts MATCH ?", (query,)).fetchone()[0] or 0)
            for query in ["DJ", "OIL", "深圳", "上海"]
        }
        unicode61_fts_counts = {
            query: int(serving.execute("SELECT COUNT(*) FROM search_document_fts_unicode61 WHERE search_document_fts_unicode61 MATCH ?", (query,)).fetchone()[0] or 0)
            for query in ["DJ", "OIL", "深圳", "上海"]
        }
        tokenizer_row = serving.execute("SELECT value FROM build_metadata WHERE key='search_document_fts_tokenizer'").fetchone()
        unicode61_tokenizer_row = serving.execute("SELECT value FROM build_metadata WHERE key='search_document_fts_unicode61_tokenizer'").fetchone()
        serving_readback = {
            "missing_tables": sorted(serving_expected - serving_tables),
            "counts": table_counts(serving_db, ["canonical_subject", "dj_profile", "performance_event", "dj_event", "dj_relation_rollup", "dj_venue_rollup", "evidence_ref", "activity_event_detail", "activity_evidence_ref", "search_document", "graph_window_cache"]),
            "fts_counts": fts_counts,
            "fts_tokenizer": tokenizer_row[0] if tokenizer_row else "",
            "unicode61_fts_counts": unicode61_fts_counts,
            "unicode61_fts_tokenizer": unicode61_tokenizer_row[0] if unicode61_tokenizer_row else "",
        }
    finally:
        serving.close()

    miniapp = sqlite3.connect(miniapp_db)
    try:
        miniapp_tables = {row[0] for row in miniapp.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        miniapp_readback = {
            "missing_tables": sorted(miniapp_expected - miniapp_tables),
            "counts": table_counts(miniapp_db, ["subject", "dj_profile", "dj_event", "dj_collaborator", "dj_venue", "source_ref", "dj_identity_redirect", "dj_identity_profile_disposition"]),
        }
    finally:
        miniapp.close()

    core = sqlite3.connect(core_db)
    try:
        external_columns = [row[1] for row in core.execute("PRAGMA table_info(external_link_evidence)")]
        core_readback = {
            "counts": table_counts(core_db, ["core_entity", "core_event", "entity_event_edge", "entity_relation_edge", "external_link_evidence", "identity_resolution_case", "compat_activity_event_detail", "compat_activity_evidence_ref", "compat_graph_window_cache", "compat_canonical_subject", "compat_dj_profile", "compat_search_document", "compat_dj_org_rollup"]),
            "external_link_raw_url_columns": [name for name in external_columns if "url" in name.lower() and name not in {"canonical_url_key_hash", "url_hash"}],
            "core_source_ref_raw_url_redacted_nonempty": int(core.execute("SELECT COUNT(*) FROM core_source_ref WHERE COALESCE(raw_url_redacted, '') <> ''").fetchone()[0] or 0),
        }
    finally:
        core.close()

    with gzip.open(index_path, "rb") as fh:
        index_payload = json.loads(fh.read().decode("utf-8"))
    index_readback = {
        "v": index_payload.get("v"),
        "missing_keys": sorted(index_expected - set(index_payload)),
        "counts": {key: len(index_payload.get(key, {})) for key in ["subjects", "profiles", "events", "collabs", "dj_venues", "source_refs"]},
    }

    return {
        "core": core_readback,
        "serving": serving_readback,
        "miniapp": miniapp_readback,
        "index": index_readback,
    }


def run_safe(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[3]
    sources = source_paths(args)
    outputs = validate_output_paths(args, sources)
    before = file_hashes(sources)
    steps: list[dict[str, Any]] = []
    source_hashes_unchanged = False
    error = ""
    try:
        common_args = [
            "--db1",
            str(sources["db1"]),
            "--db2",
            str(sources["db2"]),
            "--db3",
            str(sources["db3"]),
            "--external-link-sidecar",
            str(sources["external_link_sidecar"]),
            "--s232d3b8-candidates",
            str(sources["s232d3b8_candidates"]),
        ]
        steps.append(
            run_step(
                "readiness_audit",
                [sys.executable, str(SCRIPT_DIR / "audit_atlas_core_migration_readiness.py"), *common_args, "--out-dir", str(outputs["readiness_out_dir"])],
                repo_root,
            )
        )
        steps.append(
            run_step(
                "build_core_candidate",
                [
                    sys.executable,
                    str(SCRIPT_DIR / "build_atlas_core_candidate.py"),
                    *common_args,
                    "--out-dir",
                    str(outputs["candidate_out_dir"]),
                    "--dataset-id",
                    args.dataset_id,
                ],
                repo_root,
            )
        )
        steps.append(
            run_step(
                "export_serving_sqlite",
                [
                    sys.executable,
                    str(SCRIPT_DIR / "export_atlas_core_to_serving_sqlite.py"),
                    "--core-db",
                    str(outputs["atlas_core"]),
                    "--out",
                    str(outputs["atlas_serving"]),
                ],
                repo_root,
            )
        )
        steps.append(
            run_step(
                "export_miniapp_sqlite",
                [
                    sys.executable,
                    str(SCRIPT_DIR / "export_atlas_core_to_miniapp_sqlite.py"),
                    "--core-db",
                    str(outputs["atlas_core"]),
                    "--out",
                    str(outputs["atlas_miniapp"]),
                ],
                repo_root,
            )
        )
        steps.append(
            run_step(
                "export_miniapp_index",
                [
                    sys.executable,
                    str(SCRIPT_DIR / "export_atlas_core_to_miniapp_index.py"),
                    "--miniapp-db",
                    str(outputs["atlas_miniapp"]),
                    "--out",
                    str(outputs["atlas_index"]),
                ],
                repo_root,
            )
        )
    except Exception as exc:
        error = str(exc)
    finally:
        after = file_hashes(sources)
        source_hashes_unchanged = before == after

    rb = readback(outputs) if not error and source_hashes_unchanged else {}
    blockers = []
    if error:
        blockers.append("execution_step_failed")
    if not source_hashes_unchanged:
        blockers.append("source_hash_changed")
    if rb:
        if rb["serving"]["missing_tables"] or rb["miniapp"]["missing_tables"] or rb["index"]["missing_keys"]:
            blockers.append("legacy_shape_missing")
        legacy_required = ["OIL"]
        unicode_required = ["DJ", "深圳", "上海"]
        if any(rb["serving"]["fts_counts"].get(query, 0) <= 0 for query in legacy_required):
            blockers.append("fts_smoke_failed")
        if any(rb["serving"]["unicode61_fts_counts"].get(query, 0) <= 0 for query in unicode_required):
            blockers.append("fts_smoke_failed")
        if rb["serving"]["counts"].get("activity_event_detail", 0) <= 0 or rb["serving"]["counts"].get("activity_evidence_ref", 0) <= 0:
            blockers.append("activity_detail_evidence_empty")
        if rb["core"]["external_link_raw_url_columns"] or rb["core"]["core_source_ref_raw_url_redacted_nonempty"]:
            blockers.append("raw_url_safety_failed")

    report = {
        "schema_version": "atlas_core_safe_execution.v1",
        "decision": "atlas_core_safe_execution_passed" if not blockers else "atlas_core_safe_execution_blocked",
        "blockers": blockers,
        "error": error,
        "source_hashes_before": before,
        "source_hashes_after": after,
        "source_hashes_unchanged": source_hashes_unchanged,
        "sources": {label: str(path) for label, path in sources.items()},
        "outputs": {label: str(path) for label, path in outputs.items()},
        "steps": steps,
        "timing": {
            "steps": {s["label"]: s.get("elapsed_seconds", 0) for s in steps},
            "total_elapsed_seconds": round(sum(s.get("elapsed_seconds", 0) for s in steps), 3),
        },
        "readback": rb,
        "safety": {
            "source_db_write_executed": False,
            "production_db_write_executed": False,
            "report_local_output_only": True,
            "source_hash_guard_enforced": True,
        },
    }
    outputs["candidate_out_dir"].mkdir(parents=True, exist_ok=True)
    write_json(outputs["candidate_out_dir"] / "atlas_core_safe_execution_report.json", report)
    if blockers:
        raise RuntimeError(json_dumps(report))
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Atlas Core candidate pipeline with source-hash safety guards.")
    add_common_args(parser)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_CANDIDATE_OUT_DIR)
    parser.add_argument("--readiness-out-dir", type=Path, default=DEFAULT_READINESS_OUT_DIR)
    parser.add_argument("--dataset-id", default="atlas_core_candidate_20260604")
    parser.add_argument("--allow-outside-stage7-reports", action="store_true", help="Testing only: allow writing outside tools/stage7_rewrite/reports.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> dict[str, Any]:
    return run_safe(parse_args(argv))


if __name__ == "__main__":
    print(json_dumps(main()))
