from __future__ import annotations

import hashlib
import sys
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from migrate_sanji_completion_ledger_scope import migrate_ledger


def scope_hash(fakeids: list[str]) -> str:
    return hashlib.sha256(("\n".join(fakeids) + "\n").encode()).hexdigest()


def test_migration_filters_closed_accounts_and_preserves_verified_statuses(tmp_path: Path) -> None:
    previous = {
        "schema_version": "sanji_client_sync_cycle.v1",
        "cycle_id": "old",
        "account_scope_sha256": scope_hash(["done", "closed", "pending"]),
        "accounts": [
            {"ordinal": 1, "fakeid": "done", "status": "completed"},
            {"ordinal": 2, "fakeid": "closed", "status": "completed"},
            {"ordinal": 3, "fakeid": "pending", "status": "pending"},
        ],
        "last_blocker": {"code": "client_rate_limited"},
    }
    scope = {
        "schema_version": "sanji_client_account_scope.v1",
        "gate_pass": True,
        "eligible_fakeids": ["done", "pending"],
        "eligible_fakeids_sha256": scope_hash(["done", "pending"]),
    }

    migrated = migrate_ledger(
        previous,
        scope,
        new_cycle_id="new",
        previous_ledger_path=tmp_path / "old.json",
        previous_ledger_sha256="a" * 64,
        reason="closed after 180 days without updates",
    )

    assert migrated["cycle_id"] == "new"
    assert [row["fakeid"] for row in migrated["accounts"]] == ["done", "pending"]
    assert [row["ordinal"] for row in migrated["accounts"]] == [1, 2]
    assert migrated["summary"]["completed_count"] == 1
    assert migrated["summary"]["pending_count"] == 1
    assert migrated["scope_migration_evidence"]["removed_count"] == 1
    assert migrated["status"] == "blocked_rate_limited"
    assert migrated["secret_values_exposed"] is False


def test_migration_rejects_scope_that_adds_an_account(tmp_path: Path) -> None:
    previous = {
        "schema_version": "sanji_client_sync_cycle.v1",
        "account_scope_sha256": scope_hash(["old"]),
        "accounts": [{"ordinal": 1, "fakeid": "old", "status": "completed"}],
    }
    scope = {
        "schema_version": "sanji_client_account_scope.v1",
        "gate_pass": True,
        "eligible_fakeids": ["new"],
        "eligible_fakeids_sha256": scope_hash(["new"]),
    }

    try:
        migrate_ledger(
            previous,
            scope,
            new_cycle_id="new-cycle",
            previous_ledger_path=tmp_path / "old.json",
            previous_ledger_sha256="b" * 64,
            reason="closed accounts removed",
        )
    except ValueError as error:
        assert "subset" in str(error)
    else:
        raise AssertionError("expected ValueError")
