#!/usr/bin/env python3
"""Detect fresh Sanji/RSS activity rows and decide whether to trigger publish.

This script is intentionally cheap and secret-safe. It reads the Sanji exported
weekly-compatible queue plus the current release package, then writes a small
state/report file. It does not call any LLM and does not fetch RSS URLs.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
AUDIT_SCRIPT = ROOT / "scripts" / "audit_weekly_sanji_queue_package_gap.py"
DEFAULT_QUEUE = Path(r"E:\公众号\sanji-daily-export\latest_queue.jsonl")
DEFAULT_STATE = ROOT / "reports" / "sanji_rss_fast_watch" / "state.json"
DEFAULT_REPORT = ROOT / "reports" / "sanji_rss_fast_watch" / "latest_watch_report.json"
DEFAULT_API_DIR = ROOT.parents[1] / "services" / "weekly_activity_cloudrun" / "data" / "current_release"
DEFAULT_SOURCE_POLICY = ROOT / "registries" / "weekly_sanji_source_policy.json"
SCHEMA_VERSION = "huaidj_sanji_rss_fast_watch.v2"

# Reasons that conclusively disqualify a row — safe to commit as known immediately.
# Anything else is a "boundary" row: do NOT commit to known until publish confirms it.
_CLEAR_DISQUALIFIER_REASONS = frozenset({
    "missing_source_url",
    "missing_title",
    "non_event_notice_excluded",
    "outside_release_window",
})


def load_audit_module():
    spec = importlib.util.spec_from_file_location("audit_weekly_sanji_queue_package_gap", AUDIT_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load audit module: {AUDIT_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


AUDIT = load_audit_module()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if isinstance(value, dict):
            rows.append(value)
    return rows


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def parse_iso_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "schema_version": SCHEMA_VERSION,
            "known_source_hashes": [],
            "bootstrap_completed": False,
        }
    try:
        payload = read_json(path)
    except Exception:
        return {
            "schema_version": SCHEMA_VERSION,
            "known_source_hashes": [],
            "bootstrap_completed": False,
            "state_read_error": True,
        }
    if not isinstance(payload.get("known_source_hashes"), list):
        payload["known_source_hashes"] = []
    return payload


def row_hash(row: dict[str, Any]) -> str:
    return str(AUDIT.row_source_hash(row) or "").lower()


def _is_boundary_exclusion(reasons: list[str]) -> bool:
    """True when no clear disqualifier is present — row might be a real event."""
    for r in reasons:
        if r in _CLEAR_DISQUALIFIER_REASONS:
            return False
        if r.startswith("policy_excluded"):
            return False
    return True


def row_identity(row: dict[str, Any], source_hash: str) -> dict[str, Any]:
    return {
        "source_hash": source_hash,
        "queue_id": row.get("queue_id"),
        "account": AUDIT.row_account(row),
        "title": AUDIT.first_string(row.get("title"), row.get("source_title")),
        "source_url": AUDIT.row_url(row),
        "post_date": row.get("post_date") or row.get("publish_time_iso") or row.get("publish_time"),
    }


def package_hashes(api_dir: Path) -> set[str]:
    if not api_dir.exists():
        return set()
    try:
        return AUDIT.package_hashes(api_dir)
    except Exception:
        return set()


def save_state(
    path: Path,
    state: dict[str, Any],
    *,
    known_hashes: set[str],
    extra: dict[str, Any] | None = None,
) -> None:
    updated = dict(state)
    updated["schema_version"] = SCHEMA_VERSION
    updated["updated_at"] = now_iso()
    updated["known_source_hashes"] = sorted(known_hashes)
    if extra:
        updated.update(extra)
    write_json(path, updated)


def finalize(args: argparse.Namespace) -> dict[str, Any]:
    report_path = Path(args.finalize_report)
    report = read_json(report_path)
    state_path = Path(report["state_path"])
    state = load_state(state_path)
    known = {str(item).lower() for item in state.get("known_source_hashes", []) if item}
    publish_exit_code = int(args.publish_exit_code)

    if publish_exit_code == 0:
        hashes_to_commit = set(report.get("new_hashes_all") or [])
        decision = "finalized_publish_success"
    else:
        hashes_to_commit = set(report.get("new_non_candidate_hashes") or [])
        hashes_to_commit.update(report.get("already_published_new_hashes") or [])
        decision = "finalized_publish_failed_candidates_left_pending"

    known.update(str(item).lower() for item in hashes_to_commit if item)
    save_state(
        state_path,
        state,
        known_hashes=known,
        extra={
            "last_finalize_at": now_iso(),
            "last_publish_exit_code": publish_exit_code,
            "last_finalize_decision": decision,
            "last_watch_report": str(report_path),
        },
    )
    final_report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "mode": "finalize",
        "decision": decision,
        "publish_exit_code": publish_exit_code,
        "state_path": str(state_path),
        "committed_hash_count": len(hashes_to_commit),
        "known_hash_count": len(known),
    }
    if args.report:
        write_json(Path(args.report), final_report)
    print(json.dumps(final_report, ensure_ascii=False))
    return final_report


def detect(args: argparse.Namespace) -> dict[str, Any]:
    queue_path = Path(args.queue)
    state_path = Path(args.state)
    report_path = Path(args.report)
    api_dir = Path(args.api_dir)
    rows = read_jsonl(queue_path)
    state = load_state(state_path)
    known = {str(item).lower() for item in state.get("known_source_hashes", []) if item}
    row_hashes = {row_hash(row) for row in rows}
    row_hashes.discard("")

    generated_at = now_iso()
    today = datetime.now().date()
    window_start = datetime.strptime(args.week_start, "%Y-%m-%d").date() if args.week_start else today
    window_end = window_start + timedelta(days=max(0, args.window_days - 1))

    if not state.get("bootstrap_completed") and not args.no_bootstrap:
        save_state(
            state_path,
            state,
            known_hashes=row_hashes,
            extra={
                "bootstrap_completed": True,
                "bootstrap_at": generated_at,
                "last_decision": "bootstrap_current_queue_without_trigger",
            },
        )
        report = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": generated_at,
            "mode": "detect",
            "decision": "bootstrap_current_queue_without_trigger",
            "should_trigger": False,
            "bootstrap": True,
            "queue_path": str(queue_path),
            "state_path": str(state_path),
            "api_dir": str(api_dir),
            "queue_row_count": len(rows),
            "known_hash_count_before": len(known),
            "known_hash_count_after": len(row_hashes),
            "new_row_count": len(row_hashes),
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
        }
        write_json(report_path, report)
        print(json.dumps(report, ensure_ascii=False))
        return report

    published = package_hashes(api_dir)
    source_policy = AUDIT.load_source_policy(Path(args.source_policy) if args.source_policy else None)
    new_rows: list[dict[str, Any]] = []
    seen_new_hashes: set[str] = set()
    for row in rows:
        source_hash = row_hash(row)
        if not source_hash or source_hash in known or source_hash in seen_new_hashes:
            continue
        seen_new_hashes.add(source_hash)
        new_rows.append(row)

    excluded = Counter()
    new_candidates: list[dict[str, Any]] = []
    already_published: list[str] = []
    safe_non_candidate_hashes: set[str] = set()
    boundary_rows: list[dict[str, Any]] = []   # possible real events — do NOT commit as known
    all_new_hashes: set[str] = set()
    for row in new_rows:
        source_hash = row_hash(row)
        all_new_hashes.add(source_hash)
        classified = AUDIT.classify_row(
            row,
            week_start=window_start,
            window_end=window_end,
            source_policy=source_policy,
        )
        if not classified["include"]:
            reasons = classified.get("exclude_reasons") or []
            for reason in reasons:
                excluded[reason] += 1
            if _is_boundary_exclusion(reasons):
                boundary_rows.append({**row_identity(row, source_hash), "exclude_reasons": reasons})
            else:
                safe_non_candidate_hashes.add(source_hash)
            continue
        if source_hash in published:
            already_published.append(source_hash)
            continue
        classified.update(row_identity(row, source_hash))
        new_candidates.append(classified)

    # Write deferred boundary rows beside state for later LLM routing
    deferred_path = state_path.parent / "deferred_boundary_hashes.jsonl"
    if boundary_rows:
        with deferred_path.open("a", encoding="utf-8") as fh:
            for br in boundary_rows:
                fh.write(json.dumps({**br, "deferred_at": generated_at}, ensure_ascii=False) + "\n")

    last_trigger = parse_iso_datetime(state.get("last_trigger_at"))
    cooldown_active = False
    if last_trigger and args.min_trigger_interval_minutes > 0:
        cooldown_active = datetime.now(last_trigger.tzinfo) < last_trigger + timedelta(
            minutes=args.min_trigger_interval_minutes
        )

    would_trigger = bool(new_candidates) and not cooldown_active
    should_trigger = would_trigger and not args.detect_only
    if args.detect_only and would_trigger:
        decision = "detect_only_new_activity_candidates_pending"
    elif should_trigger:
        decision = "trigger_publish_for_new_activity_candidates"
    elif new_candidates and cooldown_active:
        decision = "cooldown_pending_new_activity_candidates"
    elif new_rows:
        decision = "new_rows_no_publishable_activity_candidate"
    else:
        decision = "no_new_rows"

    # Only commit rows we're sure about; boundary rows stay pending until publish resolves them
    commit_now = set(safe_non_candidate_hashes)
    commit_now.update(already_published)
    updated_known = set(known)
    updated_known.update(commit_now)
    extra_state = {
        "bootstrap_completed": True,
        "last_decision": decision,
        "last_detect_at": generated_at,
        "last_new_row_count": len(new_rows),
        "last_new_candidate_count": len(new_candidates),
        "last_new_boundary_count": len(boundary_rows),
        "last_watch_report": str(report_path),
    }
    if should_trigger:
        extra_state["last_trigger_at"] = generated_at
        extra_state["last_trigger_candidate_hashes"] = [row["source_hash"] for row in new_candidates]
    save_state(state_path, state, known_hashes=updated_known, extra=extra_state)

    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "mode": "detect",
        "decision": decision,
        "detect_only": args.detect_only,
        "would_trigger_publish": would_trigger,
        "should_trigger": should_trigger,
        "cooldown_active": cooldown_active,
        "queue_path": str(queue_path),
        "state_path": str(state_path),
        "api_dir": str(api_dir),
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "window_days": args.window_days,
        "min_trigger_interval_minutes": args.min_trigger_interval_minutes,
        "queue_row_count": len(rows),
        "known_hash_count_before": len(known),
        "known_hash_count_after_detect": len(updated_known),
        "new_row_count": len(new_rows),
        "new_candidate_count": len(new_candidates),
        "new_boundary_count": len(boundary_rows),
        "already_published_new_count": len(already_published),
        "excluded_new_reason_counts": dict(excluded.most_common()),
        "new_hashes_all": sorted(all_new_hashes),
        "new_non_candidate_hashes": sorted(safe_non_candidate_hashes),
        "new_boundary_hashes": [r["source_hash"] for r in boundary_rows],
        "new_boundary_rows": boundary_rows[:20],
        "already_published_new_hashes": sorted(already_published),
        "new_candidate_hashes": [row["source_hash"] for row in new_candidates],
        "new_candidate_rows": new_candidates[:50],
        "deferred_boundary_path": str(deferred_path) if boundary_rows else None,
        "rule": {
            "source": "Sanji desktop RSS snapshot latest_queue.jsonl",
            "publish_trigger": "only new current/future single-event-looking rows not already represented in current_release",
            "parent_overview": "monthly/weekly/holiday overview parents are excluded and handled by club_overviews",
            "boundary": "rows excluded only by ambiguous reasons (parent_overview, no_date, weak_signal) are deferred, never silently committed as known",
            "first_run": "bootstrap existing queue without triggering to avoid historical backfill rerun",
        },
    }
    write_json(report_path, report)
    print(json.dumps(report, ensure_ascii=False))
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["detect", "finalize"], default="detect")
    parser.add_argument("--queue", default=str(DEFAULT_QUEUE))
    parser.add_argument("--state", default=str(DEFAULT_STATE))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--api-dir", default=str(DEFAULT_API_DIR))
    parser.add_argument("--source-policy", default=str(DEFAULT_SOURCE_POLICY))
    parser.add_argument("--week-start", default="")
    parser.add_argument("--window-days", type=int, default=15)
    parser.add_argument("--min-trigger-interval-minutes", type=int, default=20)
    parser.add_argument(
        "--detect-only",
        action="store_true",
        help="Detect new RSS/Sanji candidates without marking a trigger or launching publish.",
    )
    parser.add_argument("--no-bootstrap", action="store_true")
    parser.add_argument("--finalize-report", default="")
    parser.add_argument("--publish-exit-code", type=int, default=0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.mode == "finalize":
        if not args.finalize_report:
            raise SystemExit("--finalize-report is required in finalize mode")
        finalize(args)
        return 0
    detect(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
