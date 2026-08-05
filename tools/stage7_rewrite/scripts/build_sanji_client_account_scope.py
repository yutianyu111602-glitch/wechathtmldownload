#!/usr/bin/env python3
"""Build the explicit active-only Sanji WeChat-client account scope."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "sanji_client_account_scope.v1"


def load_registry(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    accounts = payload.get("accounts") or payload.get("items")
    if not isinstance(accounts, list) or not accounts:
        raise RuntimeError(f"registry has no accounts: {path}")
    return [item for item in accounts if isinstance(item, dict)]


def load_sanji_accounts(sanji_root: Path) -> dict[str, str]:
    db_path = sanji_root / "sanji.db"
    if not db_path.is_file():
        raise RuntimeError(f"Sanji database is missing: {db_path}")
    connection = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    try:
        return {
            str(fakeid): str(nickname or "")
            for fakeid, nickname in connection.execute(
                "SELECT fakeid, nickname FROM wechat_account ORDER BY fakeid"
            )
        }
    finally:
        connection.close()


def _scope_hash(fakeids: list[str]) -> str:
    return hashlib.sha256(("\n".join(fakeids) + "\n").encode("utf-8")).hexdigest()


def build_scope(
    registry_accounts: list[dict[str, Any]], sanji_accounts: dict[str, str]
) -> dict[str, Any]:
    active = [item for item in registry_accounts if item.get("status") == "active" and item.get("fakeid")]
    inactive = [item for item in registry_accounts if item.get("status") == "inactive" and item.get("fakeid")]
    active_present = [item for item in active if str(item["fakeid"]) in sanji_accounts]
    active_missing = [item for item in active if str(item["fakeid"]) not in sanji_accounts]
    inactive_present = [item for item in inactive if str(item["fakeid"]) in sanji_accounts]
    registry_fakeids = {str(item.get("fakeid") or "") for item in registry_accounts}
    unregistered = [
        {"fakeid": fakeid, "account_name": nickname}
        for fakeid, nickname in sorted(sanji_accounts.items())
        if fakeid not in registry_fakeids
    ]
    eligible_fakeids = [str(item["fakeid"]) for item in active_present]

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "policy": "registry_active_only",
        "gate_pass": not active_missing and not unregistered,
        "counts": {
            "registry_total": len(registry_accounts),
            "registry_active": len(active),
            "registry_inactive": len(inactive),
            "sanji_total": len(sanji_accounts),
            "eligible_active_present": len(active_present),
            "excluded_inactive_present": len(inactive_present),
            "active_missing_from_sanji": len(active_missing),
            "sanji_unregistered": len(unregistered),
        },
        "eligible_fakeids": eligible_fakeids,
        "eligible_fakeids_sha256": _scope_hash(eligible_fakeids),
        "excluded_inactive": [
            {
                "fakeid": str(item["fakeid"]),
                "account_name": str(item.get("account_name") or ""),
                "reason": str(item.get("inactive_reason") or "registry_status_inactive"),
                "verified_at": str(item.get("inactive_verified_at") or ""),
            }
            for item in inactive_present
        ],
        "active_missing_from_sanji": [
            {"fakeid": str(item["fakeid"]), "account_name": str(item.get("account_name") or "")}
            for item in active_missing
        ],
        "sanji_unregistered": unregistered,
        "secret_values_exposed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--sanji-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    scope = build_scope(load_registry(args.registry), load_sanji_accounts(args.sanji_root))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(scope, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "out": str(args.out), "counts": scope["counts"], "gate_pass": scope["gate_pass"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
