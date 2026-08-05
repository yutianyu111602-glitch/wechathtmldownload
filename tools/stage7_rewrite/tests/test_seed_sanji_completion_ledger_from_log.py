from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "seed_sanji_completion_ledger_from_log.py"
SPEC = importlib.util.spec_from_file_location("seed_sanji_completion_ledger_from_log", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def fixture_paths(tmp_path: Path, *, completed: list[str] | None = None) -> tuple[Path, Path, Path]:
    fakeids = ["a", "b", "c"]
    scope_hash = MODULE.canonical_scope_hash(fakeids)
    scope_path = tmp_path / "scope.json"
    ledger_path = tmp_path / "ledger.json"
    log_path = tmp_path / "sanji.log"
    write_json(
        scope_path,
        {
            "schema_version": MODULE.SCOPE_SCHEMA,
            "gate_pass": True,
            "eligible_fakeids": fakeids,
            "eligible_fakeids_sha256": scope_hash,
        },
    )
    cutoff = int(datetime(2026, 7, 29, 21, 0, tzinfo=timezone.utc).timestamp())
    write_json(
        ledger_path,
        {
            "schema_version": MODULE.LEDGER_SCHEMA,
            "cycle_id": "cycle",
            "account_scope_sha256": scope_hash,
            "cutoff_hours": 168,
            "cutoff_ts": cutoff,
            "accounts": [
                {
                    "ordinal": index + 1,
                    "fakeid": fakeid,
                    "status": "completed" if fakeid in (completed or []) else "pending",
                    "attempts": 1 if fakeid in (completed or []) else 0,
                }
                for index, fakeid in enumerate(fakeids)
            ],
            "last_blocker": {"code": "client_rate_limited", "message": "cooldown"},
        },
    )
    events = [
        {"ts": "2026-08-05T20:00:00+00:00", "scope": "sync", "msg": "account start", "fields": {"fakeid": "a"}},
        {"ts": "2026-08-05T20:00:01+00:00", "scope": "sync", "msg": "account done", "fields": {"fakeid": "a", "messages": 2, "articles": 1}},
        {"ts": "2026-08-05T20:00:02+00:00", "scope": "sync", "msg": "account start", "fields": {"fakeid": "b"}},
        {"ts": "2026-08-05T20:00:03+00:00", "scope": "sync", "msg": "account done", "fields": {"fakeid": "b", "messages": 1, "articles": 1}},
        {"ts": "2026-08-05T20:00:04+00:00", "scope": "sync", "msg": "account start", "fields": {"fakeid": "c"}},
        {"ts": "2026-08-05T20:00:05+00:00", "scope": "sync", "msg": "client tick failed, paused", "fields": {"fakeid": "c", "reason": "client_rate_limited", "ret": -6}},
    ]
    log_path.write_text("\n".join(json.dumps(item) for item in events) + "\n", encoding="utf-8")
    return scope_path, ledger_path, log_path


def run_seed(tmp_path: Path, *, apply: bool = False, source_cutoff_hours: float = 168) -> dict:
    scope, ledger, log = fixture_paths(tmp_path)
    return MODULE.seed_from_paths(
        scope,
        ledger,
        log,
        window_start=datetime(2026, 8, 5, 19, 59, tzinfo=timezone.utc),
        window_end=datetime(2026, 8, 5, 20, 1, tzinfo=timezone.utc),
        source_cutoff_hours=source_cutoff_hours,
        apply=apply,
    )


def test_valid_strict_prefix_is_seeded_atomically_and_blocker_is_preserved(tmp_path: Path) -> None:
    scope, ledger, log = fixture_paths(tmp_path)
    result = MODULE.seed_from_paths(
        scope,
        ledger,
        log,
        window_start=datetime(2026, 8, 5, 19, 59, tzinfo=timezone.utc),
        window_end=datetime(2026, 8, 5, 20, 1, tzinfo=timezone.utc),
        source_cutoff_hours=168,
        apply=True,
    )
    seeded = json.loads(ledger.read_text(encoding="utf-8"))

    assert result["completed_count"] == 2
    assert result["pending_count"] == 1
    assert result["status"] == "blocked_rate_limited"
    assert seeded["last_blocker"]["code"] == "client_rate_limited"
    assert [row["status"] for row in seeded["accounts"]] == ["completed", "completed", "pending"]
    assert seeded["recovery_evidence"]["coverage_gate_pass"] is True
    assert seeded["secret_values_exposed"] is False


def test_dry_run_does_not_modify_ledger(tmp_path: Path) -> None:
    scope, ledger, log = fixture_paths(tmp_path)
    before = ledger.read_bytes()
    result = MODULE.seed_from_paths(
        scope,
        ledger,
        log,
        window_start=datetime(2026, 8, 5, 19, 59, tzinfo=timezone.utc),
        window_end=datetime(2026, 8, 5, 20, 1, tzinfo=timezone.utc),
        source_cutoff_hours=168,
        apply=False,
    )
    assert result["applied"] is False
    assert ledger.read_bytes() == before


def test_internal_execution_order_may_differ_when_completed_set_is_exact_prefix(tmp_path: Path) -> None:
    scope, ledger, log = fixture_paths(tmp_path)
    events = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    reordered = events[2:4] + events[0:2] + events[4:]
    log.write_text("\n".join(json.dumps(item) for item in reordered) + "\n", encoding="utf-8")

    result = MODULE.seed_from_paths(
        scope,
        ledger,
        log,
        window_start=datetime(2026, 8, 5, 19, 59, tzinfo=timezone.utc),
        window_end=datetime(2026, 8, 5, 20, 1, tzinfo=timezone.utc),
        source_cutoff_hours=168,
        apply=False,
    )
    assert result["completed_count"] == 2


def test_nonprefix_completion_is_rejected(tmp_path: Path) -> None:
    scope, ledger, log = fixture_paths(tmp_path)
    text = log.read_text(encoding="utf-8").replace('"fakeid": "b"', '"fakeid": "not-b"')
    log.write_text(text, encoding="utf-8")

    with pytest.raises(ValueError, match="strict prefix"):
        MODULE.seed_from_paths(
            scope,
            ledger,
            log,
            window_start=datetime(2026, 8, 5, 19, 59, tzinfo=timezone.utc),
            window_end=datetime(2026, 8, 5, 20, 1, tzinfo=timezone.utc),
            source_cutoff_hours=168,
            apply=False,
        )


def test_narrower_source_window_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="narrower"):
        run_seed(tmp_path, source_cutoff_hours=1)


def test_nonpending_prefix_status_is_not_overwritten(tmp_path: Path) -> None:
    scope, ledger, log = fixture_paths(tmp_path)
    payload = json.loads(ledger.read_text(encoding="utf-8"))
    payload["accounts"][0]["status"] = "failed"
    write_json(ledger, payload)

    with pytest.raises(ValueError, match="refusing to overwrite"):
        MODULE.seed_from_paths(
            scope,
            ledger,
            log,
            window_start=datetime(2026, 8, 5, 19, 59, tzinfo=timezone.utc),
            window_end=datetime(2026, 8, 5, 20, 1, tzinfo=timezone.utc),
            source_cutoff_hours=168,
            apply=False,
        )
