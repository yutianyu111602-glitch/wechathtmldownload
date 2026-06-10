#!/usr/bin/env python3
"""Build the S224 DB2 source/provider acquisition spool sidecar.

S224 consumes the S213/S219 relation identity source-provider spool queue and
materializes a report-local SQLite/JSON sidecar for DB2 control-plane workers.
It does not mutate DB1/DB2/DB3, does not project DB2, and does not emit raw
source URLs or local archive paths.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
STAGE7_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "atlas_relation_db2_source_provider_spool_sidecar_s224.v1"
DEFAULT_INPUT = (
    STAGE7_ROOT
    / "reports"
    / "atlas_relation_identity_p1_p2_recovery_workbench_s219_after_s216_20260602"
    / "s213_db2_source_provider_spool_queue.jsonl"
)
DEFAULT_OUT_DIR = (
    STAGE7_ROOT
    / "reports"
    / "atlas_relation_db2_source_provider_spool_sidecar_s224_20260602"
)
DEFAULT_SCORECARD = (
    REPO_ROOT
    / "reports"
    / "WEEKLY_ATLAS_RELATION_DB2_SOURCE_PROVIDER_SPOOL_SIDECAR_S224_20260602.md"
)

SECRET_RE = re.compile(
    r"(?i)(sk-[A-Za-z0-9_-]{12,}|token\s*[:=]\s*[^,\s]{8,}|cookie\s*[:=]\s*[^,\s]{8,}|password\s*[:=]\s*[^,\s]{8,}|BEGIN [A-Z ]*PRIVATE KEY)"
)
RAW_URL_RE = re.compile(r"https?://", re.I)
RAW_LOCAL_PATH_RE = re.compile(r"(?i)([A-Z]:\\|\\\\wsl\.localhost\\|/mnt/[a-z]/|/home/pc/)")


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


def stable_id(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if isinstance(value, dict):
            rows.append(value)
    return rows


def as_bool(value: Any) -> bool:
    return bool(value)


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def acquire_lock(out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    lock_path = out_dir / "s224.sidecar.lock"
    fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(now_iso() + "\n")
    return lock_path


def release_lock(lock_path: Path) -> None:
    try:
        lock_path.unlink()
    except FileNotFoundError:
        pass


def priority_from_route(row: dict[str, Any]) -> tuple[str, int]:
    input_route = str(row.get("input_route") or "")
    if input_route.startswith("P1_"):
        return "P1_missing_archive_recovery", 1
    if input_route.startswith("P2_"):
        return "P2_source_provider_acquisition", 2
    if input_route.startswith("P4_"):
        return "P4_manual_risk_review", 4
    return "P9_unclassified_spool", 9


def acquisition_strategy(row: dict[str, Any]) -> str:
    source_seed = row.get("source_seed") if isinstance(row.get("source_seed"), dict) else {}
    per_dj = row.get("per_dj_resolution") if isinstance(row.get("per_dj_resolution"), dict) else {}
    missing_archive_profiles = [
        dj_id
        for dj_id, item in per_dj.items()
        if isinstance(item, dict)
        and int(item.get("source_ref_count") or 0) > 0
        and not item.get("has_exact_archive")
    ]
    if missing_archive_profiles and int(row.get("exact_archive_ref_count") or 0) > 0:
        return "recover_missing_archive_for_uncovered_profile"
    if as_list(source_seed.get("common_source_accounts")):
        return "source_account_provider_crosscheck"
    if as_list(source_seed.get("common_titles")):
        return "title_seed_provider_crosscheck"
    if as_bool(source_seed.get("has_provider_anchor")):
        return "provider_anchor_crosscheck"
    return "source_provider_seed_acquisition"


def normalize_task(row: dict[str, Any]) -> dict[str, Any]:
    priority, rank = priority_from_route(row)
    source_seed = row.get("source_seed") if isinstance(row.get("source_seed"), dict) else {}
    task_id = str(row.get("task_id") or f"s224:source:{stable_id(row)}")
    return {
        "schema_version": SCHEMA_VERSION + ".task",
        "task_id": task_id,
        "group_id": str(row.get("group_id") or ""),
        "route": str(row.get("route") or ""),
        "input_route": str(row.get("input_route") or ""),
        "priority": priority,
        "priority_rank": rank,
        "acquisition_strategy": acquisition_strategy(row),
        "queue_status": "queued_for_db2_control_plane_acquisition",
        "display_names": as_list(row.get("display_names")),
        "dj_ids": as_list(row.get("dj_ids")),
        "unicode_compact_values": as_list(row.get("unicode_compact_values")),
        "source_ref_count": int(row.get("source_ref_count") or 0),
        "source_url_resolved_ref_count": int(row.get("source_url_resolved_ref_count") or 0),
        "exact_archive_ref_count": int(row.get("exact_archive_ref_count") or 0),
        "public_fetch_ready_ref_count": int(row.get("public_fetch_ready_ref_count") or 0),
        "source_seed": {
            "common_source_accounts": as_list(source_seed.get("common_source_accounts")),
            "common_titles": as_list(source_seed.get("common_titles")),
            "common_venues": as_list(source_seed.get("common_venues")),
            "every_profile_has_date_seed": as_bool(source_seed.get("every_profile_has_date_seed")),
            "every_profile_has_title_seed": as_bool(source_seed.get("every_profile_has_title_seed")),
            "has_provider_anchor": as_bool(source_seed.get("has_provider_anchor")),
            "has_source_account_or_title_seed": as_bool(source_seed.get("has_source_account_or_title_seed")),
        },
        "per_dj_resolution": row.get("per_dj_resolution") if isinstance(row.get("per_dj_resolution"), dict) else {},
        "db2_projection_allowed_now": False,
        "db3_write_allowed_now": False,
        "accepted_for_public_release": False,
        "raw_source_url_emitted": False,
        "raw_archive_path_emitted": False,
    }


def safety_findings(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    text = "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows)
    if SECRET_RE.search(text):
        findings.append({"kind": "secret_like_value", "severity": "block"})
    if RAW_URL_RE.search(text):
        findings.append({"kind": "raw_url_emitted", "severity": "block"})
    if RAW_LOCAL_PATH_RE.search(text):
        findings.append({"kind": "raw_local_path_emitted", "severity": "block"})
    for row in rows:
        if row.get("db2_projection_allowed_now") or row.get("db3_write_allowed_now"):
            findings.append({"kind": "projection_or_db3_write_allowed", "task_id": row.get("task_id"), "severity": "block"})
        if row.get("raw_source_url_emitted") or row.get("raw_archive_path_emitted"):
            findings.append({"kind": "raw_emission_flag_true", "task_id": row.get("task_id"), "severity": "block"})
    return findings


def atomic_replace_sqlite(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(suffix=".sqlite", dir=path.parent)
    os.close(fd)
    conn = sqlite3.connect(temp_name)
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA user_version=224")
    conn.execute("CREATE TABLE __target_path(path TEXT NOT NULL)")
    conn.execute("INSERT INTO __target_path VALUES (?)", (str(path),))
    return conn


def finish_sqlite(conn: sqlite3.Connection) -> None:
    row = conn.execute("SELECT path FROM __target_path").fetchone()
    target = Path(row[0])
    temp_name = Path(conn.execute("PRAGMA database_list").fetchone()[2])
    conn.execute("DROP TABLE __target_path")
    conn.commit()
    conn.close()
    os.replace(temp_name, target)


def write_sqlite(path: Path, tasks: list[dict[str, Any]]) -> dict[str, int]:
    conn = atomic_replace_sqlite(path)
    conn.executescript(
        """
        CREATE TABLE acquisition_tasks (
          task_id TEXT PRIMARY KEY,
          group_id TEXT NOT NULL,
          route TEXT NOT NULL,
          input_route TEXT NOT NULL,
          priority TEXT NOT NULL,
          priority_rank INTEGER NOT NULL,
          acquisition_strategy TEXT NOT NULL,
          queue_status TEXT NOT NULL,
          group_size INTEGER NOT NULL,
          display_names_json TEXT NOT NULL,
          dj_ids_json TEXT NOT NULL,
          unicode_compact_values_json TEXT NOT NULL,
          source_ref_count INTEGER NOT NULL,
          source_url_resolved_ref_count INTEGER NOT NULL,
          exact_archive_ref_count INTEGER NOT NULL,
          public_fetch_ready_ref_count INTEGER NOT NULL,
          common_source_accounts_json TEXT NOT NULL,
          common_titles_json TEXT NOT NULL,
          common_venues_json TEXT NOT NULL,
          has_provider_anchor INTEGER NOT NULL,
          every_profile_has_title_seed INTEGER NOT NULL,
          every_profile_has_date_seed INTEGER NOT NULL,
          db2_projection_allowed_now INTEGER NOT NULL,
          db3_write_allowed_now INTEGER NOT NULL,
          accepted_for_public_release INTEGER NOT NULL
        );
        CREATE TABLE per_dj_resolution (
          task_id TEXT NOT NULL,
          dj_id TEXT NOT NULL,
          source_ref_count INTEGER NOT NULL,
          source_url_resolved_count INTEGER NOT NULL,
          exact_archive_count INTEGER NOT NULL,
          blocked_source_ref_count INTEGER NOT NULL,
          public_fetch_ready_count INTEGER NOT NULL,
          has_exact_archive INTEGER NOT NULL,
          has_public_fetch_ready INTEGER NOT NULL,
          exact_archive_source_ref_ids_json TEXT NOT NULL,
          public_fetch_source_ref_ids_json TEXT NOT NULL,
          PRIMARY KEY (task_id, dj_id),
          FOREIGN KEY (task_id) REFERENCES acquisition_tasks(task_id)
        );
        CREATE INDEX idx_acquisition_tasks_priority ON acquisition_tasks(priority_rank, acquisition_strategy);
        CREATE INDEX idx_acquisition_tasks_group ON acquisition_tasks(group_id);
        CREATE INDEX idx_per_dj_resolution_dj ON per_dj_resolution(dj_id);
        """
    )
    for task in tasks:
        seed = task["source_seed"]
        conn.execute(
            """
            INSERT INTO acquisition_tasks VALUES (
              ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                task["task_id"],
                task["group_id"],
                task["route"],
                task["input_route"],
                task["priority"],
                task["priority_rank"],
                task["acquisition_strategy"],
                task["queue_status"],
                len(task["dj_ids"]),
                compact_json(task["display_names"]),
                compact_json(task["dj_ids"]),
                compact_json(task["unicode_compact_values"]),
                task["source_ref_count"],
                task["source_url_resolved_ref_count"],
                task["exact_archive_ref_count"],
                task["public_fetch_ready_ref_count"],
                compact_json(seed["common_source_accounts"]),
                compact_json(seed["common_titles"]),
                compact_json(seed["common_venues"]),
                int(seed["has_provider_anchor"]),
                int(seed["every_profile_has_title_seed"]),
                int(seed["every_profile_has_date_seed"]),
                int(task["db2_projection_allowed_now"]),
                int(task["db3_write_allowed_now"]),
                int(task["accepted_for_public_release"]),
            ),
        )
        for dj_id, resolution in task["per_dj_resolution"].items():
            if not isinstance(resolution, dict):
                continue
            conn.execute(
                """
                INSERT INTO per_dj_resolution VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task["task_id"],
                    str(dj_id),
                    int(resolution.get("source_ref_count") or 0),
                    int(resolution.get("source_url_resolved_count") or 0),
                    int(resolution.get("exact_archive_count") or 0),
                    int(resolution.get("blocked_source_ref_count") or 0),
                    int(resolution.get("public_fetch_ready_count") or 0),
                    int(bool(resolution.get("has_exact_archive"))),
                    int(bool(resolution.get("has_public_fetch_ready"))),
                    compact_json(as_list(resolution.get("exact_archive_source_ref_ids"))),
                    compact_json(as_list(resolution.get("public_fetch_source_ref_ids"))),
                ),
            )
    readback = {
        "acquisition_tasks": int(conn.execute("SELECT COUNT(*) FROM acquisition_tasks").fetchone()[0]),
        "per_dj_resolution": int(conn.execute("SELECT COUNT(*) FROM per_dj_resolution").fetchone()[0]),
        "projection_allowed_rows": int(
            conn.execute(
                "SELECT COUNT(*) FROM acquisition_tasks WHERE db2_projection_allowed_now != 0 OR db3_write_allowed_now != 0 OR accepted_for_public_release != 0"
            ).fetchone()[0]
        ),
    }
    finish_sqlite(conn)
    return readback


def render_markdown(report: dict[str, Any]) -> str:
    counts = report["counts"]
    artifacts = report["artifacts"]
    lines = [
        "# Weekly Atlas Relation DB2 Source/Provider Spool Sidecar S224",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Input rows: `{counts['input_row_count']}`",
        f"- Sidecar tasks: `{counts['task_count']}`",
        f"- Per-DJ resolution rows: `{counts['per_dj_resolution_count']}`",
        f"- Priority counts: `{counts['priority_counts']}`",
        f"- Strategy counts: `{counts['acquisition_strategy_counts']}`",
        f"- SQLite: `{artifacts['sqlite']}`",
        f"- Normalized task JSONL: `{artifacts['normalized_tasks_jsonl']}`",
        "",
        "## Boundaries",
        "",
        "- Report-local sidecar only.",
        "- No DB1/DB2/DB3 mutation, no DB2 projection, no CloudRun deploy, no CloudBase sync, no mini-program upload/review/release.",
        "- No raw source URL, raw local archive path, cookie, token, or API key value is emitted.",
        "- Later DB2 writes must still go through the Docker resident DB2 weapons control plane, JSONL spool, lock, backup, single `db2-writer`, and readback.",
        "",
        "## Next Gate",
        "",
        "- Feed `s224_normalized_source_provider_tasks.jsonl` to `db2ctl` profile queues for source/provider acquisition and archive recovery.",
        "- Only article-ready or provider-crosschecked evidence can return to DB3 write gates.",
    ]
    return "\n".join(lines) + "\n"


def build_sidecar(input_path: Path, out_dir: Path, scorecard: Path) -> dict[str, Any]:
    lock_path = acquire_lock(out_dir)
    try:
        input_rows = load_jsonl(input_path)
        tasks = [normalize_task(row) for row in input_rows]
        findings = safety_findings(tasks)
        task_jsonl = out_dir / "s224_normalized_source_provider_tasks.jsonl"
        sqlite_path = out_dir / "atlas_relation_db2_source_provider_spool_sidecar_s224.sqlite"
        summary_path = out_dir / "atlas_relation_db2_source_provider_spool_sidecar_s224.json"
        markdown_path = out_dir / "atlas_relation_db2_source_provider_spool_sidecar_s224.md"
        atomic_write_jsonl(task_jsonl, tasks)
        readback = write_sqlite(sqlite_path, tasks)
        priority_counts = Counter(task["priority"] for task in tasks)
        strategy_counts = Counter(task["acquisition_strategy"] for task in tasks)
        route_counts = Counter(task["input_route"] for task in tasks)
        decision = (
            "atlas_relation_db2_source_provider_spool_sidecar_s224_ready_report_local"
            if not findings
            and readback["acquisition_tasks"] == len(tasks)
            and readback["projection_allowed_rows"] == 0
            else "atlas_relation_db2_source_provider_spool_sidecar_s224_blocked_safety_or_readback"
        )
        report = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": now_iso(),
            "decision": decision,
            "input": rel_path(input_path),
            "counts": {
                "input_row_count": len(input_rows),
                "task_count": len(tasks),
                "per_dj_resolution_count": sum(len(task["per_dj_resolution"]) for task in tasks),
                "priority_counts": dict(sorted(priority_counts.items())),
                "acquisition_strategy_counts": dict(sorted(strategy_counts.items())),
                "input_route_counts": dict(sorted(route_counts.items())),
            },
            "readback": readback,
            "safety": {
                "finding_count": len(findings),
                "findings": findings,
                "raw_source_url_emitted": False,
                "raw_archive_path_emitted": False,
                "db2_projection_allowed_now": False,
                "db3_write_allowed_now": False,
                "accepted_for_public_release": False,
            },
            "control_plane": {
                "mode": "Docker resident layered DB2 weapons plus db2ctl JSONL spool",
                "profiles": ["db2-light-workers", "db2-browser-tools", "db2-reconcile", "db2-writer"],
                "single_writer_required": True,
                "db2_writer_execute_allowed_now": False,
                "live_db2_write_allowed_now": False,
            },
            "artifacts": {
                "summary_json": rel_path(summary_path),
                "markdown": rel_path(markdown_path),
                "scorecard": rel_path(scorecard),
                "sqlite": rel_path(sqlite_path),
                "normalized_tasks_jsonl": rel_path(task_jsonl),
            },
            "production_state_difference": {
                "db1_mutated": False,
                "db2_mutated": False,
                "db2_projected": False,
                "db3_mutated": False,
                "release_uploaded_or_published": False,
            },
        }
        atomic_write_json(summary_path, report)
        atomic_write_text(markdown_path, render_markdown(report))
        atomic_write_text(scorecard, render_markdown(report))
        return report
    finally:
        release_lock(lock_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build S224 DB2 source/provider acquisition spool sidecar")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_sidecar(args.input, args.out_dir, args.scorecard)
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "counts": report["counts"],
                "readback": report["readback"],
                "safety_finding_count": report["safety"]["finding_count"],
                "out_dir": rel_path(args.out_dir),
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["decision"].endswith("_ready_report_local") else 1


if __name__ == "__main__":
    raise SystemExit(main())
