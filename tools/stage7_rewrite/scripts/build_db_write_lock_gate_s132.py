#!/usr/bin/env python3
"""Build the S132 reusable DB write lock/readback/rollback gate.

Report-only for production data. The real command writes only fixture SQLite
files under the report directory. It proves the lock contract that later DB1,
DB2, DB3, coordinate, or external-link production write packets must use.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


REPO_ROOT = Path(__file__).resolve().parents[3]
STAGE7_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "db_write_lock_gate_s132.v1"
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "db_write_lock_gate_s132_20260601"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_DB_WRITE_LOCK_GATE_S132_20260601.md"


@dataclass(frozen=True)
class WriteGateConfig:
    busy_timeout_ms: int = 250
    max_attempts: int = 3
    retry_sleep_ms: int = 50
    transaction_mode: str = "IMMEDIATE"
    backup_before_write: bool = True
    require_postwrite_readback: bool = True
    require_single_writer_scope: bool = True


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


def connect_sqlite(path: Path, config: WriteGateConfig) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=config.busy_timeout_ms / 1000)
    conn.execute(f"PRAGMA busy_timeout = {config.busy_timeout_ms}")
    return conn


def create_fixture_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE gate_probe (id INTEGER PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL)")
        conn.execute("INSERT INTO gate_probe (id, value, updated_at) VALUES (1, 'before', ?)", (now_iso(),))
        conn.commit()
    finally:
        conn.close()


def read_fixture_value(path: Path) -> str:
    conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    try:
        row = conn.execute("SELECT value FROM gate_probe WHERE id = 1").fetchone()
        return str(row[0]) if row else ""
    finally:
        conn.close()


def backup_sqlite(path: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"{path.stem}.{stable_id({'path': str(path), 'time': now_iso()})}.backup.sqlite"
    shutil.copy2(path, backup_path)
    return backup_path


def is_lock_error(exc: BaseException) -> bool:
    return "locked" in str(exc).casefold() or "busy" in str(exc).casefold()


def run_sqlite_write_gate(
    *,
    db_path: Path,
    config: WriteGateConfig,
    backup_dir: Path,
    write_fn: Callable[[sqlite3.Connection], None],
    readback_fn: Callable[[], dict[str, Any]],
    simulate_failure_after_write: bool = False,
) -> dict[str, Any]:
    backup_path = backup_sqlite(db_path, backup_dir) if config.backup_before_write else None
    attempts: list[dict[str, Any]] = []
    last_error = ""
    for attempt in range(1, config.max_attempts + 1):
        conn: sqlite3.Connection | None = None
        try:
            conn = connect_sqlite(db_path, config)
            conn.execute(f"BEGIN {config.transaction_mode}")
            write_fn(conn)
            if simulate_failure_after_write:
                raise RuntimeError("simulated_write_failure_before_commit")
            conn.commit()
            readback = readback_fn() if config.require_postwrite_readback else {}
            return {
                "status": "committed_with_readback",
                "attempts": attempts + [{"attempt": attempt, "result": "committed"}],
                "backup_path": rel_path(backup_path) if backup_path else "",
                "readback": readback,
                "rollback_performed": False,
                "lock_abort": False,
            }
        except Exception as exc:  # noqa: BLE001 - classify for gate report
            last_error = exc.__class__.__name__ + ": " + str(exc)
            lock_error = is_lock_error(exc)
            attempts.append({"attempt": attempt, "result": "lock_error" if lock_error else "error", "error_class": exc.__class__.__name__})
            if conn is not None:
                try:
                    conn.rollback()
                except sqlite3.Error:
                    pass
            if not lock_error:
                return {
                    "status": "rolled_back_after_error",
                    "attempts": attempts,
                    "backup_path": rel_path(backup_path) if backup_path else "",
                    "readback": readback_fn(),
                    "rollback_performed": True,
                    "lock_abort": False,
                    "error": last_error,
                }
            if attempt < config.max_attempts:
                time.sleep(config.retry_sleep_ms / 1000)
        finally:
            if conn is not None:
                conn.close()
    return {
        "status": "aborted_after_bounded_lock_retries",
        "attempts": attempts,
        "backup_path": rel_path(backup_path) if backup_path else "",
        "readback": readback_fn(),
        "rollback_performed": True,
        "lock_abort": True,
        "error": last_error,
    }


def update_fixture_value(value: str) -> Callable[[sqlite3.Connection], None]:
    def write_fn(conn: sqlite3.Connection) -> None:
        conn.execute("UPDATE gate_probe SET value = ?, updated_at = ? WHERE id = 1", (value, now_iso()))

    return write_fn


def fixture_readback(path: Path, expected: str) -> Callable[[], dict[str, Any]]:
    def readback() -> dict[str, Any]:
        actual = read_fixture_value(path)
        return {"actual_value": actual, "expected_value": expected, "matches_expected": actual == expected}

    return readback


def run_fixture_scenarios(out_dir: Path, config: WriteGateConfig) -> list[dict[str, Any]]:
    fixture_dir = out_dir / "fixtures"
    backup_dir = out_dir / "backups"
    fixture_dir.mkdir(parents=True, exist_ok=True)

    scenarios: list[dict[str, Any]] = []

    success_db = fixture_dir / "success.sqlite"
    create_fixture_db(success_db)
    success_result = run_sqlite_write_gate(
        db_path=success_db,
        config=config,
        backup_dir=backup_dir,
        write_fn=update_fixture_value("after"),
        readback_fn=fixture_readback(success_db, "after"),
    )
    scenarios.append(
        {
            "scenario_id": "fixture_success_write",
            "db_path": rel_path(success_db),
            "expected_status": "committed_with_readback",
            **success_result,
        }
    )

    locked_db = fixture_dir / "locked.sqlite"
    create_fixture_db(locked_db)
    locker = connect_sqlite(locked_db, WriteGateConfig(busy_timeout_ms=5000))
    try:
        locker.execute("BEGIN IMMEDIATE")
        locked_result = run_sqlite_write_gate(
            db_path=locked_db,
            config=config,
            backup_dir=backup_dir,
            write_fn=update_fixture_value("after-lock"),
            readback_fn=fixture_readback(locked_db, "before"),
        )
    finally:
        locker.rollback()
        locker.close()
    scenarios.append(
        {
            "scenario_id": "fixture_locked_abort",
            "db_path": rel_path(locked_db),
            "expected_status": "aborted_after_bounded_lock_retries",
            **locked_result,
        }
    )

    rollback_db = fixture_dir / "rollback.sqlite"
    create_fixture_db(rollback_db)
    rollback_result = run_sqlite_write_gate(
        db_path=rollback_db,
        config=config,
        backup_dir=backup_dir,
        write_fn=update_fixture_value("after-error"),
        readback_fn=fixture_readback(rollback_db, "before"),
        simulate_failure_after_write=True,
    )
    scenarios.append(
        {
            "scenario_id": "fixture_rollback_after_failure",
            "db_path": rel_path(rollback_db),
            "expected_status": "rolled_back_after_error",
            **rollback_result,
        }
    )
    return scenarios


def gate_contract(config: WriteGateConfig) -> dict[str, Any]:
    return {
        "config": asdict(config),
        "required_controls": [
            "open the target DB through an explicit write-gate packet",
            "create or verify a backup before writes",
            "set PRAGMA busy_timeout before BEGIN",
            "use BEGIN IMMEDIATE for single-writer lock acquisition",
            "retry only for a bounded number of lock attempts",
            "abort on persistent lock instead of waiting forever",
            "rollback on non-lock errors before returning",
            "perform postwrite readback against the target selector",
            "write rollback and readback contracts to report artifacts",
            "keep production_write_allowed=false until a target-specific packet passes",
        ],
        "forbidden_shortcuts": [
            "no blind writes without backup",
            "no unbounded waiting on database locks",
            "no public promotion from a write packet without readback",
            "no DB2/DB3 projection while blocker-as-skip rows remain open for the lane",
        ],
    }


def render_scorecard(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Weekly DB Write Lock Gate S132",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Scenarios: `{summary['scenario_count']}`",
        f"- Passed scenarios: `{summary['passed_scenario_count']}`",
        f"- Lock abort scenarios: `{summary['lock_abort_count']}`",
        f"- Rollback verified scenarios: `{summary['rollback_verified_count']}`",
        f"- Backup artifacts: `{summary['backup_artifact_count']}`",
        f"- Production write allowed now: `{summary['production_write_allowed_now']}`",
        f"- Finding count: `{report['finding_count']}`",
        "",
        "## Boundary",
        "",
        "- Fixture SQLite writes only under the report directory.",
        "- No DB1/DB2/DB3 mutation, no deploy/upload/review, no external crawl, no model call, no cookie/token value read.",
        "- Later production write packets must import this gate contract or prove equivalent controls.",
    ]
    return "\n".join(lines) + "\n"


def secret_findings(payload: Any) -> list[dict[str, str]]:
    text = json.dumps(payload, ensure_ascii=False)
    findings = []
    for marker in ("sk-", "token=", "cookie=", "password=", "BEGIN PRIVATE KEY"):
        if marker.casefold() in text.casefold():
            findings.append({"pattern": "secret_like_text", "sample": marker})
    return findings[:10]


def build_gate_report(*, out_dir: Path, scorecard_path: Path, config: WriteGateConfig) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    scenarios = run_fixture_scenarios(out_dir, config)
    passed = [row for row in scenarios if row["status"] == row["expected_status"] and row.get("readback", {}).get("matches_expected")]
    backup_count = sum(1 for row in scenarios if row.get("backup_path"))
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": "db_write_lock_gate_ready_report_only",
        "outputs": {
            "report": rel_path(out_dir / "db_write_lock_gate.json"),
            "scenarios": rel_path(out_dir / "db_write_lock_gate_scenarios.jsonl"),
            "scorecard": rel_path(scorecard_path),
        },
        "summary": {
            "scenario_count": len(scenarios),
            "passed_scenario_count": len(passed),
            "lock_abort_count": sum(1 for row in scenarios if row.get("lock_abort")),
            "rollback_verified_count": sum(1 for row in scenarios if row.get("rollback_performed") and row.get("readback", {}).get("matches_expected")),
            "backup_artifact_count": backup_count,
            "production_write_allowed_now": False,
            "all_fixture_scenarios_passed": len(passed) == len(scenarios),
        },
        "gate_contract": gate_contract(config),
        "boundary": {
            "report_only_for_production": True,
            "fixture_sqlite_write": True,
            "db1_mutation": False,
            "db2_mutation": False,
            "db3_mutation": False,
            "deploy_or_upload": False,
            "network_fetch": False,
            "model_call_performed": False,
            "cookie_values_read": False,
            "token_values_read": False,
        },
        "scenarios": scenarios,
        "secret_like_findings": [],
        "finding_count": 0,
        "next_story": "S133",
    }
    findings = secret_findings(report)
    report["secret_like_findings"] = findings
    report["finding_count"] = len(findings)
    if findings or not report["summary"]["all_fixture_scenarios_passed"]:
        report["decision"] = "db_write_lock_gate_blocked_report_only"
    atomic_write_json(out_dir / "db_write_lock_gate.json", report)
    atomic_write_jsonl(out_dir / "db_write_lock_gate_scenarios.jsonl", scenarios)
    atomic_write_text(scorecard_path, render_scorecard(report))
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--busy-timeout-ms", type=int, default=250)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--retry-sleep-ms", type=int, default=50)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = WriteGateConfig(
        busy_timeout_ms=args.busy_timeout_ms,
        max_attempts=args.max_attempts,
        retry_sleep_ms=args.retry_sleep_ms,
    )
    report = build_gate_report(out_dir=args.out_dir, scorecard_path=args.scorecard, config=config)
    print(json.dumps({"decision": report["decision"], "summary": report["summary"]}, ensure_ascii=False))
    return 0 if report["finding_count"] == 0 and report["summary"]["all_fixture_scenarios_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
