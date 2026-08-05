from __future__ import annotations

import hashlib
import sys
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from build_sanji_client_account_scope import build_scope


def test_scope_excludes_inactive_accounts_and_reports_missing_active() -> None:
    registry = [
        {"fakeid": "active-present", "account_name": "Active", "status": "active"},
        {"fakeid": "active-missing", "account_name": "Missing", "status": "active"},
        {
            "fakeid": "closed",
            "account_name": "Closed",
            "status": "inactive",
            "inactive_reason": "closed",
        },
    ]

    scope = build_scope(registry, {"active-present": "Active", "closed": "Closed"})

    assert scope["eligible_fakeids"] == ["active-present"]
    assert scope["excluded_inactive"][0]["fakeid"] == "closed"
    assert scope["counts"]["active_missing_from_sanji"] == 1
    assert scope["gate_pass"] is False


def test_scope_passes_only_when_registry_and_sanji_match() -> None:
    registry = [{"fakeid": "active", "account_name": "Active", "status": "active"}]

    scope = build_scope(registry, {"active": "Active"})

    assert scope["gate_pass"] is True
    assert scope["counts"]["eligible_active_present"] == 1
    assert scope["eligible_fakeids_sha256"] == hashlib.sha256(b"active\n").hexdigest()
    assert scope["secret_values_exposed"] is False
