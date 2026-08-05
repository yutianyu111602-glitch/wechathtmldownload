#!/usr/bin/env python3
"""Recover verified Sanji client completions into a durable sync-cycle ledger.

This is intentionally a narrow recovery tool.  It accepts only a contiguous
prefix of the frozen active-account scope, requires a matching terminal rate
limit on the next account, and proves that the earlier sync window was at least
as broad as the ledger window before writing anything.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


LEDGER_SCHEMA = "sanji_client_sync_cycle.v1"
SCOPE_SCHEMA = "sanji_client_account_scope.v1"


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def parse_timestamp(value: str) -> datetime:
    text = str(value).strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp must include an offset: {value}")
    return parsed


def canonical_scope_hash(fakeids: list[str]) -> str:
    return hashlib.sha256(("\n".join(fakeids) + "\n").encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_sync_events(log_path: Path, window_start: datetime, window_end: datetime) -> list[dict[str, Any]]:
    if window_end <= window_start:
        raise ValueError("log window end must be after start")
    events: list[dict[str, Any]] = []
    with log_path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        for line_number, line in enumerate(handle, start=1):
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict) or event.get("scope") != "sync" or not event.get("ts"):
                continue
            observed_at = parse_timestamp(str(event["ts"]))
            if window_start <= observed_at <= window_end:
                event["_line"] = line_number
                event["_observed_at"] = observed_at
                events.append(event)
    return events


def terminal_rate_limit_fakeid(events: list[dict[str, Any]]) -> tuple[str, datetime]:
    matches: list[tuple[str, datetime]] = []
    for event in events:
        fields = event.get("fields") if isinstance(event.get("fields"), dict) else {}
        reason = str(fields.get("reason") or "")
        message = str(event.get("msg") or "")
        fakeid = str(fields.get("fakeid") or "")
        is_terminal = message == "client tick failed, paused" and (
            reason == "client_rate_limited" or int(fields.get("ret") or 0) == -6
        )
        if is_terminal and fakeid:
            matches.append((fakeid, event["_observed_at"]))
    if len(matches) != 1:
        raise ValueError(f"expected exactly one terminal client rate-limit event, found {len(matches)}")
    return matches[0]


def analyze_recovery(
    scope: dict[str, Any],
    ledger: dict[str, Any],
    events: list[dict[str, Any]],
    *,
    source_cutoff_hours: float,
) -> dict[str, Any]:
    if scope.get("schema_version") != SCOPE_SCHEMA:
        raise ValueError("sanji account scope schema mismatch")
    if ledger.get("schema_version") != LEDGER_SCHEMA:
        raise ValueError("sanji completion ledger schema mismatch")
    if not bool(scope.get("gate_pass")):
        raise ValueError("sanji account scope gate did not pass")
    if source_cutoff_hours <= 0:
        raise ValueError("source cutoff hours must be positive")

    fakeids = [str(value) for value in scope.get("eligible_fakeids") or [] if str(value)]
    if not fakeids:
        raise ValueError("eligible account scope is empty")
    scope_hash = canonical_scope_hash(fakeids)
    if scope.get("eligible_fakeids_sha256") != scope_hash:
        raise ValueError("account scope hash does not match eligible account order")
    if ledger.get("account_scope_sha256") != scope_hash:
        raise ValueError("ledger account scope hash mismatch")

    rows = ledger.get("accounts")
    if not isinstance(rows, list) or [str(row.get("fakeid") or "") for row in rows] != fakeids:
        raise ValueError("ledger account order does not match the frozen scope")

    starts: dict[str, dict[str, Any]] = {}
    completions: dict[str, dict[str, Any]] = {}
    for event in events:
        fields = event.get("fields") if isinstance(event.get("fields"), dict) else {}
        fakeid = str(fields.get("fakeid") or "")
        message = str(event.get("msg") or "")
        if not fakeid:
            continue
        if message == "account start":
            if fakeid in starts:
                raise ValueError(f"duplicate account start in recovery window: {fakeid}")
            starts[fakeid] = event
        elif message == "account done":
            if fakeid in completions:
                raise ValueError(f"duplicate account completion in recovery window: {fakeid}")
            completions[fakeid] = event

    if not completions:
        raise ValueError("no completed Sanji accounts found in recovery window")
    if len(starts) != len(completions) + 1:
        raise ValueError("expected one more account start than completion at the terminal rate limit")
    for fakeid, done in completions.items():
        start = starts.get(fakeid)
        if start is None:
            raise ValueError(f"completion has no preceding start: {fakeid}")
        if start["_observed_at"] > done["_observed_at"]:
            raise ValueError(f"completion precedes start: {fakeid}")

    completed_count = len(completions)
    expected_prefix = fakeids[:completed_count]
    if set(completions) != set(expected_prefix):
        raise ValueError("completed accounts are not the strict prefix of the frozen active scope")
    if completed_count >= len(fakeids):
        raise ValueError("recovery window is already complete; no terminal account remains")

    blocker_fakeid, blocker_at = terminal_rate_limit_fakeid(events)
    expected_blocker = fakeids[completed_count]
    if blocker_fakeid != expected_blocker:
        raise ValueError("terminal rate-limit account is not the next account in the frozen scope")
    if blocker_fakeid not in starts:
        raise ValueError("terminal rate-limit account has no start event")
    if starts[blocker_fakeid]["_observed_at"] > blocker_at:
        raise ValueError("terminal rate limit precedes the blocker account start")

    first_start = min(event["_observed_at"] for event in starts.values())
    conservative_cutoff = first_start - timedelta(hours=source_cutoff_hours)
    ledger_cutoff = datetime.fromtimestamp(int(ledger.get("cutoff_ts") or 0), tz=timezone.utc)
    if conservative_cutoff.astimezone(timezone.utc) > ledger_cutoff:
        raise ValueError("earlier sync window is narrower than the completion ledger window")

    return {
        "fakeids": fakeids,
        "scope_hash": scope_hash,
        "starts": starts,
        "completions": completions,
        "completed_count": completed_count,
        "blocker_fakeid": blocker_fakeid,
        "blocker_at": blocker_at,
        "conservative_source_cutoff": conservative_cutoff,
        "ledger_cutoff": ledger_cutoff,
    }


def ledger_summary(ledger: dict[str, Any]) -> dict[str, Any]:
    rows = ledger["accounts"]
    completed = sum(row.get("status") == "completed" for row in rows)
    rate_limited = sum(row.get("status") == "rate_limited" for row in rows)
    failed = sum(row.get("status") == "failed" for row in rows)
    return {
        "requested_count": len(rows),
        "completed_count": completed,
        "pending_count": len(rows) - completed - rate_limited - failed,
        "rate_limited_count": rate_limited,
        "failed_count": failed,
        "cycle_complete": bool(rows) and completed == len(rows),
    }


def build_seeded_ledger(
    ledger: dict[str, Any],
    analysis: dict[str, Any],
    *,
    log_path: Path,
    log_sha256: str,
    window_start: datetime,
    window_end: datetime,
    source_cutoff_hours: float,
) -> dict[str, Any]:
    seeded = copy.deepcopy(ledger)
    for index in range(analysis["completed_count"]):
        row = seeded["accounts"][index]
        if row.get("status") not in {"pending", "completed"}:
            raise ValueError(f"refusing to overwrite non-pending ledger status at ordinal {index + 1}")
        start = analysis["starts"][row["fakeid"]]
        done = analysis["completions"][row["fakeid"]]
        fields = done.get("fields") if isinstance(done.get("fields"), dict) else {}
        row.update(
            {
                "status": "completed",
                "attempts": max(1, int(row.get("attempts") or 0)),
                "phase": "finished",
                "started": "recovered_from_verified_sanji_log",
                "resume_attempts": 0,
                "started_at": start["_observed_at"].isoformat(),
                "finished_at": done["_observed_at"].isoformat(),
                "last_error": None,
                "recovered_from_evidence": True,
                "messages": int(fields.get("messages") or 0),
                "articles": int(fields.get("articles") or 0),
            }
        )

    seeded["recovery_evidence"] = {
        "schema_version": "sanji_client_log_recovery.v1",
        "method": "strict_active_scope_prefix",
        "source_log_path": str(log_path),
        "source_log_sha256": log_sha256,
        "source_window_start": window_start.isoformat(),
        "source_window_end": window_end.isoformat(),
        "source_cutoff_hours": source_cutoff_hours,
        "conservative_source_cutoff_upper_bound_ts": int(
            analysis["conservative_source_cutoff"].timestamp()
        ),
        "ledger_cutoff_ts": int(seeded["cutoff_ts"]),
        "coverage_gate_pass": True,
        "completed_prefix_count": analysis["completed_count"],
        "completed_ordinal_first": 1,
        "completed_ordinal_last": analysis["completed_count"],
        "next_blocked_ordinal": analysis["completed_count"] + 1,
        "next_blocker_code": "client_rate_limited",
        "next_blocker_observed_at": analysis["blocker_at"].isoformat(),
        "secret_values_exposed": False,
    }
    seeded["summary"] = ledger_summary(seeded)
    global_rate_limit = (seeded.get("last_blocker") or {}).get("code") == "client_rate_limited"
    if seeded["summary"]["cycle_complete"]:
        seeded["status"] = "complete"
    elif seeded["summary"]["rate_limited_count"] or global_rate_limit:
        seeded["status"] = "blocked_rate_limited"
    elif seeded["summary"]["failed_count"]:
        seeded["status"] = "blocked_failed"
    else:
        seeded["status"] = "in_progress"
    seeded["updated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    seeded["secret_values_exposed"] = False
    return seeded


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix=f"{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def seed_from_paths(
    scope_path: Path,
    ledger_path: Path,
    log_path: Path,
    *,
    window_start: datetime,
    window_end: datetime,
    source_cutoff_hours: float,
    apply: bool,
) -> dict[str, Any]:
    scope = read_json(scope_path)
    ledger = read_json(ledger_path)
    events = load_sync_events(log_path, window_start, window_end)
    analysis = analyze_recovery(scope, ledger, events, source_cutoff_hours=source_cutoff_hours)
    log_digest = file_sha256(log_path)
    seeded = build_seeded_ledger(
        ledger,
        analysis,
        log_path=log_path.resolve(),
        log_sha256=log_digest,
        window_start=window_start,
        window_end=window_end,
        source_cutoff_hours=source_cutoff_hours,
    )
    if apply:
        write_json_atomic(ledger_path, seeded)
    return {
        "ok": True,
        "applied": apply,
        "ledger_path": str(ledger_path.resolve()),
        "cycle_id": seeded.get("cycle_id"),
        "account_scope_sha256": seeded.get("account_scope_sha256"),
        "completed_count": seeded["summary"]["completed_count"],
        "pending_count": seeded["summary"]["pending_count"],
        "next_blocked_ordinal": analysis["completed_count"] + 1,
        "next_blocker_code": "client_rate_limited",
        "coverage_gate_pass": True,
        "status": seeded["status"],
        "source_log_sha256": log_digest,
        "secret_values_exposed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope-json", type=Path, required=True)
    parser.add_argument("--ledger-json", type=Path, required=True)
    parser.add_argument("--sanji-log", type=Path, required=True)
    parser.add_argument("--window-start", required=True, help="ISO 8601 timestamp with offset")
    parser.add_argument("--window-end", required=True, help="ISO 8601 timestamp with offset")
    parser.add_argument("--source-cutoff-hours", type=float, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    report = seed_from_paths(
        args.scope_json,
        args.ledger_json,
        args.sanji_log,
        window_start=parse_timestamp(args.window_start),
        window_end=parse_timestamp(args.window_end),
        source_cutoff_hours=args.source_cutoff_hours,
        apply=args.apply,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
