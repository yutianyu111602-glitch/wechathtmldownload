from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from audit_weekly_account_inactivity import build_audit


def test_audit_marks_only_stale_active_accounts_as_closed_candidates() -> None:
    registry = [
        {"account_id": "fresh", "account_name": "Fresh", "fakeid": "fresh", "status": "active"},
        {"account_id": "stale", "account_name": "Stale", "fakeid": "stale", "status": "active"},
        {"account_id": "empty", "account_name": "Empty", "fakeid": "empty", "status": "active"},
        {"account_id": "old", "account_name": "Old", "fakeid": "old", "status": "inactive"},
    ]
    audit = build_audit(
        registry,
        {"fresh": 1_767_225_600, "stale": 1_719_792_000, "old": 1_600_000_000},
        as_of=datetime(2026, 1, 1, tzinfo=timezone.utc),
        threshold_days=180,
    )

    assert audit["active_count"] == 3
    assert audit["candidate_count"] == 2
    assert [row["account_name"] for row in audit["candidates"]] == ["Empty", "Stale"]
    assert all("fakeid" not in row for row in audit["candidates"])
    assert audit["policy"] == "long_term_no_updates_means_closed"
    assert audit["automatic_registry_write"] is False
    assert audit["secret_values_exposed"] is False


def test_audit_rejects_non_positive_threshold() -> None:
    try:
        build_audit([], {}, as_of=datetime.now(timezone.utc), threshold_days=0)
    except ValueError as error:
        assert "positive" in str(error)
    else:
        raise AssertionError("expected ValueError")
