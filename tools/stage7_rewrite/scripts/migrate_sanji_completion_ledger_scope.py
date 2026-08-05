#!/usr/bin/env python3
"""Migrate a Sanji completion ledger to a verified subset account scope."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from seed_sanji_completion_ledger_from_log import (
    LEDGER_SCHEMA,
    canonical_scope_hash,
    file_sha256,
    ledger_summary,
    read_json,
    write_json_atomic,
)


SCOPE_SCHEMA = "sanji_client_account_scope.v1"
MIGRATION_SCHEMA = "sanji_client_scope_migration.v1"


def removed_scope_hash(fakeids: list[str]) -> str:
    return hashlib.sha256(("\n".join(sorted(fakeids)) + "\n").encode("utf-8")).hexdigest()


def migrate_ledger(
    previous: dict[str, Any],
    scope: dict[str, Any],
    *,
    new_cycle_id: str,
    previous_ledger_path: Path,
    previous_ledger_sha256: str,
    reason: str,
) -> dict[str, Any]:
    if previous.get("schema_version") != LEDGER_SCHEMA:
        raise ValueError("previous completion ledger schema mismatch")
    if scope.get("schema_version") != SCOPE_SCHEMA or not scope.get("gate_pass"):
        raise ValueError("new account scope schema/gate mismatch")
    if not new_cycle_id.strip():
        raise ValueError("new cycle id is required")
    if not reason.strip():
        raise ValueError("scope migration reason is required")

    new_fakeids = [str(value) for value in scope.get("eligible_fakeids") or [] if str(value)]
    new_scope_hash = canonical_scope_hash(new_fakeids)
    if scope.get("eligible_fakeids_sha256") != new_scope_hash:
        raise ValueError("new account scope hash mismatch")

    previous_rows = previous.get("accounts")
    if not isinstance(previous_rows, list) or not previous_rows:
        raise ValueError("previous completion ledger has no account rows")
    previous_fakeids = [str(row.get("fakeid") or "") for row in previous_rows]
    if len(previous_fakeids) != len(set(previous_fakeids)) or any(not value for value in previous_fakeids):
        raise ValueError("previous completion ledger account identities are invalid")
    previous_scope_hash = canonical_scope_hash(previous_fakeids)
    if previous.get("account_scope_sha256") != previous_scope_hash:
        raise ValueError("previous completion ledger account scope hash mismatch")
    if not set(new_fakeids).issubset(previous_fakeids):
        raise ValueError("new account scope is not a subset of the previous ledger")

    previous_by_fakeid = {str(row["fakeid"]): row for row in previous_rows}
    retained_rows = [copy.deepcopy(previous_by_fakeid[fakeid]) for fakeid in new_fakeids]
    for ordinal, row in enumerate(retained_rows, start=1):
        row["ordinal"] = ordinal

    new_fakeid_set = set(new_fakeids)
    removed_fakeids = [fakeid for fakeid in previous_fakeids if fakeid not in new_fakeid_set]
    migrated = copy.deepcopy(previous)
    migrated["cycle_id"] = new_cycle_id
    migrated["account_scope_sha256"] = new_scope_hash
    migrated["accounts"] = retained_rows
    migrated["summary"] = ledger_summary(migrated)
    migrated["status"] = (
        "complete"
        if migrated["summary"]["cycle_complete"]
        else "blocked_rate_limited"
        if migrated["summary"]["rate_limited_count"]
        or (migrated.get("last_blocker") or {}).get("code") == "client_rate_limited"
        else "blocked_failed"
        if migrated["summary"]["failed_count"]
        else "in_progress"
    )
    migrated["scope_migration_evidence"] = {
        "schema_version": MIGRATION_SCHEMA,
        "method": "filter_inactive_accounts_preserve_verified_rows",
        "reason": reason,
        "previous_cycle_id": str(previous.get("cycle_id") or ""),
        "previous_ledger_path": str(previous_ledger_path.resolve()),
        "previous_ledger_sha256": previous_ledger_sha256,
        "previous_scope_sha256": str(previous.get("account_scope_sha256") or ""),
        "new_scope_sha256": new_scope_hash,
        "previous_requested_count": len(previous_rows),
        "new_requested_count": len(retained_rows),
        "removed_count": len(removed_fakeids),
        "removed_fakeids_sha256": removed_scope_hash(removed_fakeids),
        "completed_preserved_count": migrated["summary"]["completed_count"],
        "pending_preserved_count": migrated["summary"]["pending_count"],
        "migrated_at": datetime.now(timezone.utc).isoformat(),
        "secret_values_exposed": False,
    }
    migrated["updated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    migrated["secret_values_exposed"] = False
    return migrated


def migrate_from_paths(
    previous_ledger_path: Path,
    scope_path: Path,
    output_path: Path,
    *,
    new_cycle_id: str,
    reason: str,
    apply: bool,
) -> dict[str, Any]:
    previous_digest = file_sha256(previous_ledger_path)
    migrated = migrate_ledger(
        read_json(previous_ledger_path),
        read_json(scope_path),
        new_cycle_id=new_cycle_id,
        previous_ledger_path=previous_ledger_path,
        previous_ledger_sha256=previous_digest,
        reason=reason,
    )
    if apply:
        if output_path.resolve() == previous_ledger_path.resolve():
            raise ValueError("refusing to overwrite the previous ledger")
        write_json_atomic(output_path, migrated)
    return {
        "ok": True,
        "applied": apply,
        "output_path": str(output_path.resolve()),
        "cycle_id": migrated["cycle_id"],
        "account_scope_sha256": migrated["account_scope_sha256"],
        "completed_count": migrated["summary"]["completed_count"],
        "pending_count": migrated["summary"]["pending_count"],
        "removed_count": migrated["scope_migration_evidence"]["removed_count"],
        "status": migrated["status"],
        "secret_values_exposed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous-ledger", type=Path, required=True)
    parser.add_argument("--scope-json", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cycle-id", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    report = migrate_from_paths(
        args.previous_ledger,
        args.scope_json,
        args.out,
        new_cycle_id=args.cycle_id,
        reason=args.reason,
        apply=args.apply,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
