#!/usr/bin/env python3
"""Apply the S136B local source-pack acceptance write gate for strong venue rows.

This script consumes the S136 acquisition queue and optionally refreshes only
registry `last_verified_at` and `source_note` for rows with strong local
source-pack evidence. It does not write DB1/DB2/DB3/SQLite, call providers,
crawl external pages, deploy, upload, or read cookies/tokens.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
STAGE7_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "stale_registry_source_pack_acceptance_s136b.v1"
DEFAULT_TASKS = (
    STAGE7_ROOT
    / "reports"
    / "stale_registry_source_acquisition_queue_s136_20260601"
    / "stale_registry_source_acquisition_tasks_s136.jsonl"
)
DEFAULT_S132_REPORT = STAGE7_ROOT / "reports" / "db_write_lock_gate_s132_20260601" / "db_write_lock_gate.json"
DEFAULT_REGISTRY = STAGE7_ROOT / "registries" / "weekly_venues_seed.json"
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "stale_registry_source_pack_acceptance_s136b_20260601"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_STALE_REGISTRY_SOURCE_PACK_ACCEPTANCE_S136B_20260601.md"
DEFAULT_FRESH_AFTER = "2026-05-22"


def now_cst() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")


def today_cst() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")


def rel_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except (OSError, ValueError):
        return str(path)


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        temp_name = handle.name
    os.replace(temp_name, path)


def write_json(path: Path, payload: Any) -> None:
    write_text_atomic(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    write_text_atomic(path, "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows))


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def first(*values: Any) -> str:
    for value in values:
        if isinstance(value, list):
            nested = first(*value)
            if nested:
                return nested
            continue
        text = str(value or "").strip()
        if text:
            return text
    return ""


def parse_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    for candidate in (text[:10], text):
        try:
            return date.fromisoformat(candidate)
        except ValueError:
            continue
    return None


def s132_contract_ready(s132: dict[str, Any]) -> bool:
    summary = s132.get("summary", {})
    required_controls = set((s132.get("gate_contract") or {}).get("required_controls", []))
    return bool(
        s132.get("decision") == "db_write_lock_gate_ready_report_only"
        and summary.get("all_fixture_scenarios_passed") is True
        and any("backup" in item for item in required_controls)
        and any("readback" in item for item in required_controls)
        and any("rollback" in item for item in required_controls)
    )


class FileLock:
    def __init__(self, path: Path, *, attempts: int = 3, sleep_ms: int = 50) -> None:
        self.path = path
        self.attempts = attempts
        self.sleep_ms = sleep_ms
        self.fd: int | None = None

    def __enter__(self) -> "FileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(1, self.attempts + 1):
            try:
                self.fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self.fd, f"pid={os.getpid()} acquired_at={now_cst()}\n".encode("utf-8"))
                return self
            except FileExistsError:
                if attempt == self.attempts:
                    raise TimeoutError(f"lock busy after {self.attempts} attempts: {self.path}")
                time.sleep(self.sleep_ms / 1000.0)
        raise TimeoutError(f"lock busy: {self.path}")

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


def ready_tasks(tasks: list[dict[str, Any]], registry: dict[str, Any], *, fresh_after: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    fresh_after_date = parse_date(fresh_after)
    if fresh_after_date is None:
        raise ValueError(f"invalid fresh_after: {fresh_after}")
    registry_by_id = {first(row.get("venue_id")): row for row in registry.get("venues", [])}
    ready: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for task in tasks:
        if task.get("status") != "ready_for_s136_source_acceptance_gate":
            continue
        venue_id = first(task.get("venue_id"))
        registry_row = registry_by_id.get(venue_id)
        verified_at = parse_date(first((registry_row or {}).get("last_verified_at"), (registry_row or {}).get("geo_verified_at")))
        if verified_at is not None and verified_at >= fresh_after_date:
            skipped.append({"venue_id": venue_id, "reason": "already_fresh_in_registry", "last_verified_at": verified_at.isoformat()})
            continue
        strong_hits = [
            hit
            for hit in ((task.get("local_source_pack") or {}).get("hits") or [])
            if hit.get("status") == "strong_source_pack_candidate"
        ]
        if not strong_hits:
            skipped.append({"venue_id": venue_id, "reason": "missing_strong_source_pack_hit"})
            continue
        if registry_row is None:
            skipped.append({"venue_id": venue_id, "reason": "missing_registry_row"})
            continue
        ready.append({**task, "strong_hits": strong_hits})
    return ready, skipped


def source_note(task: dict[str, Any], *, previous_last_verified_at: str) -> str:
    hits = task.get("strong_hits") or []
    article_ids = [first(hit.get("article_id"), hit.get("queue_id")) for hit in hits]
    article_ids = [value for value in article_ids if value]
    note_ids = ", ".join(article_ids[:3])
    if len(article_ids) > 3:
        note_ids += f", +{len(article_ids) - 3} more"
    return (
        f"{today_cst()} S136B local source-pack acceptance: {len(article_ids)} strong source row(s) "
        f"confirmed same registry address and taxi-grade coordinate; article_ids={note_ids}; "
        f"previous_last_verified_at={previous_last_verified_at or 'empty'}."
    )


def apply_registry_write(*, registry_path: Path, ready_rows: list[dict[str, Any]], out_dir: Path) -> dict[str, Any]:
    if not ready_rows:
        return {"applied": False, "reason": "no_ready_source_pack_rows", "write_count": 0}
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = out_dir / f"backup_before_stale_registry_source_pack_acceptance_s136b_{stamp}.json"
    lock_path = registry_path.with_name(registry_path.name + ".s136b.lock")
    shutil.copy2(registry_path, backup_path)
    ready_by_id = {row["venue_id"]: row for row in ready_rows}
    changed_ids: list[str] = []
    with FileLock(lock_path):
        registry = read_json(registry_path)
        for venue in registry.get("venues", []):
            venue_id = first(venue.get("venue_id"))
            task = ready_by_id.get(venue_id)
            if not task:
                continue
            previous_note = first(venue.get("source_note"))
            previous_last = first(venue.get("last_verified_at"), venue.get("geo_verified_at"))
            note = source_note(task, previous_last_verified_at=previous_last)
            venue["last_verified_at"] = today_cst()
            venue["source_note"] = f"{previous_note} | {note}" if previous_note else note
            changed_ids.append(venue_id)
        write_json(registry_path, registry)

    readback = read_json(registry_path)
    readback_by_id = {first(row.get("venue_id")): row for row in readback.get("venues", [])}
    failed_ids = [
        venue_id
        for venue_id in changed_ids
        if first(readback_by_id.get(venue_id, {}).get("last_verified_at")) != today_cst()
        or "S136B local source-pack acceptance" not in first(readback_by_id.get(venue_id, {}).get("source_note"))
    ]
    return {
        "applied": True,
        "write_count": len(changed_ids),
        "backup_path": rel_path(backup_path),
        "lock_path": rel_path(lock_path),
        "readback_ok": not failed_ids and len(changed_ids) == len(ready_rows),
        "changed_venue_ids": changed_ids,
        "failed_readback_venue_ids": failed_ids,
    }


def output_row(task: dict[str, Any], *, status: str) -> dict[str, Any]:
    return {
        "venue_id": task["venue_id"],
        "canonical_name": task.get("canonical_name", ""),
        "city": task.get("city", ""),
        "status": status,
        "strong_hit_count": len(task.get("strong_hits") or []),
        "strong_hits": task.get("strong_hits", [])[:5],
        "write_fields": ["last_verified_at", "source_note"],
        "preserve_fields": ["registry.address", "registry.geo_lng", "registry.geo_lat", "registry.geo_source"],
        "rollback_selector": task.get("rollback_selector", {"venue_id": task["venue_id"], "path": "$.venues[*]"}),
    }


def render_scorecard(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Weekly Stale Registry Source-Pack Acceptance S136B",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Ready source-pack rows: `{summary['ready_source_pack_rows']}`",
        f"- Registry write requested: `{summary['registry_write_requested']}`",
        f"- Registry write applied: `{report['registry_write'].get('applied', False)}`",
        f"- Registry write count: `{report['registry_write'].get('write_count', 0)}`",
        f"- Readback OK: `{report['registry_write'].get('readback_ok', False)}`",
        f"- Skipped ready tasks: `{summary['skipped_ready_tasks']}`",
        f"- Finding count: `{report['finding_count']}`",
        "",
        "## Boundary",
        "",
        "- Only `last_verified_at` and `source_note` may be written for strong local source-pack rows. Address/coordinate/source fields are preserved.",
        "- No DB1/DB2/DB3/SQLite mutation, no release JSON write, no deploy/upload/review, no external crawl, no provider call, no model call, no cookie/token value read.",
        "",
        "## Next",
        "",
        "- Rerun S133 and coordinate freshness after any applied write, then continue S136 acquisition for rows still stale.",
    ]
    return "\n".join(lines) + "\n"


def build_report(
    *,
    tasks_path: Path,
    s132_report_path: Path,
    registry_path: Path,
    out_dir: Path,
    scorecard_path: Path,
    apply_write: bool,
    fresh_after: str,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    tasks = read_jsonl(tasks_path)
    s132 = read_json(s132_report_path)
    registry = read_json(registry_path)
    ready, skipped = ready_tasks(tasks, registry, fresh_after=fresh_after)
    findings: list[dict[str, Any]] = []
    if ready and not s132_contract_ready(s132):
        findings.append({"finding": "s132_lock_contract_not_ready_for_source_pack_acceptance"})

    registry_write = {"applied": False, "write_count": 0}
    if apply_write and ready and not findings:
        registry_write = apply_registry_write(registry_path=registry_path, ready_rows=ready, out_dir=out_dir)
        if not registry_write.get("readback_ok"):
            findings.append({"finding": "registry_write_readback_failed", "details": registry_write})
    elif apply_write and findings:
        registry_write = {"applied": False, "write_count": 0, "reason": "findings_blocked_write"}

    if registry_write.get("applied"):
        decision = "stale_registry_source_pack_acceptance_registry_write_applied"
    elif ready:
        decision = "stale_registry_source_pack_acceptance_ready_report_only"
    else:
        decision = "stale_registry_source_pack_acceptance_no_ready_rows"

    rows = [output_row(task, status="accepted_for_registry_write" if registry_write.get("applied") else "ready_report_only") for task in ready]
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_cst(),
        "decision": decision,
        "inputs": {
            "tasks": rel_path(tasks_path),
            "s132_report": rel_path(s132_report_path),
            "registry": rel_path(registry_path),
        },
        "outputs": {
            "report": rel_path(out_dir / "stale_registry_source_pack_acceptance_s136b.json"),
            "rows": rel_path(out_dir / "stale_registry_source_pack_acceptance_rows_s136b.jsonl"),
            "scorecard": rel_path(scorecard_path),
        },
        "summary": {
            "ready_source_pack_rows": len(ready),
            "skipped_ready_tasks": len(skipped),
            "registry_write_requested": apply_write,
            "s132_lock_contract_ready": s132_contract_ready(s132),
        },
        "skipped_tasks": skipped,
        "registry_write": registry_write,
        "ready_venue_ids": [row["venue_id"] for row in ready],
        "boundary": {
            "report_only": not registry_write.get("applied"),
            "registry_mutation": bool(registry_write.get("applied")),
            "db1_mutation": False,
            "db2_mutation": False,
            "db3_mutation": False,
            "sqlite_mutation": False,
            "release_json_mutation": False,
            "deploy_upload_review": False,
            "provider_or_geocode_call": False,
            "external_crawl": False,
            "model_call": False,
            "cookie_values_read": False,
            "token_values_read": False,
            "broad_disk_scan": False,
        },
        "next_safe_action": "rerun S133 and coordinate freshness, then continue S136 acquisition for remaining stale rows",
        "findings": findings,
        "finding_count": len(findings),
    }
    write_json(out_dir / "stale_registry_source_pack_acceptance_s136b.json", report)
    write_jsonl(out_dir / "stale_registry_source_pack_acceptance_rows_s136b.jsonl", rows)
    write_text_atomic(scorecard_path, render_scorecard(report))
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", type=Path, default=DEFAULT_TASKS)
    parser.add_argument("--s132-report", type=Path, default=DEFAULT_S132_REPORT)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--fresh-after", default=DEFAULT_FRESH_AFTER)
    parser.add_argument("--apply-registry-write", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_report(
        tasks_path=args.tasks,
        s132_report_path=args.s132_report,
        registry_path=args.registry,
        out_dir=args.out_dir,
        scorecard_path=args.scorecard,
        apply_write=args.apply_registry_write,
        fresh_after=args.fresh_after,
    )
    print(json.dumps({"decision": report["decision"], "summary": report["summary"], "registry_write": report["registry_write"]}, ensure_ascii=False, sort_keys=True))
    return 0 if report["finding_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
