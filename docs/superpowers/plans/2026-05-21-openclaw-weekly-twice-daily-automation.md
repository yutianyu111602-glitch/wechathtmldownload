# OpenClaw Weekly Twice-Daily Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the missing production-control layer around the existing HUAIDJ weekly mini-program pipeline so OpenClaw can run twice daily, scan newly added Docker public accounts, request human QR login through Telegram/iMessage when needed, and publish only after the current source-grounded gates pass.

**Architecture:** Keep `tools\stage7_rewrite\run_openclaw_weekly_daily_publish.ps1` as the canonical release spine. Add small preflight scripts for account inventory diff, exporter auth lease, notification, and run-state recording, then call the existing wrapper only after those gates pass.

**Tech Stack:** PowerShell, Python 3, existing Stage7 scripts, local `wechat-article-exporter` on `127.0.0.1:17300`, Telegram Bot API, optional Mac/iMessage relay, CloudRun/CloudBase deploy scripts, mini-program Node tests.

---

## File Structure

- Create: `tools/stage7_rewrite/scripts/sync_weekly_accounts_from_exporter.py`
  - Reads Docker/exporter account inventory and `weekly_accounts_seed.json`; writes a reviewed registry update and `account_diff.json`.
- Create: `tools/stage7_rewrite/scripts/manage_weekly_exporter_auth_lease.py`
  - Wraps `diagnose_weekly_exporter_session.py` output into a lease state machine.
- Create: `tools/stage7_rewrite/scripts/send_weekly_login_notice.py`
  - Sends Telegram photo/message and optional iMessage relay request. It never sends auth keys.
- Create: `tools/stage7_rewrite/config/openclaw_weekly_twice_daily.tasks.json`
  - OpenClaw task definitions for morning, evening, and health check schedules.
- Modify: `tools/stage7_rewrite/run_openclaw_weekly_daily_publish.ps1`
  - Add preflight calls for account sync and auth lease before build/deploy.
- Modify: `tools/stage7_rewrite/OPENCLAW_WEEKLY_DAILY_UPDATE_RUNBOOK.md`
  - Document twice-daily schedule, account scan, QR login runbook, and no-overwrite failure behavior.
- Test: `tools/stage7_rewrite/tests/test_sync_weekly_accounts_from_exporter.py`
- Test: `tools/stage7_rewrite/tests/test_manage_weekly_exporter_auth_lease.py`
- Test: `tools/stage7_rewrite/tests/test_send_weekly_login_notice.py`

## Task 1: Account Inventory Diff

**Files:**
- Create: `tools/stage7_rewrite/scripts/sync_weekly_accounts_from_exporter.py`
- Test: `tools/stage7_rewrite/tests/test_sync_weekly_accounts_from_exporter.py`

- [ ] **Step 1: Write failing tests**

```python
# tools/stage7_rewrite/tests/test_sync_weekly_accounts_from_exporter.py
import json
import tempfile
import unittest
from pathlib import Path

from tools.stage7_rewrite.scripts.sync_weekly_accounts_from_exporter import build_account_diff


class SyncWeeklyAccountsFromExporterTests(unittest.TestCase):
    def test_adds_new_exporter_fakeid_as_review(self):
        registry = {
            "schema_version": "weekly_account_registry.v1",
            "accounts": [
                {"account_id": "known", "account_name": "Known Club", "fakeid": "known-id", "status": "active"}
            ],
        }
        exporter = [
            {"account_name": "Known Club", "fakeid": "known-id"},
            {"account_name": "New Club", "fakeid": "new-id"},
        ]
        diff = build_account_diff(registry, exporter, today="2026-05-21")
        self.assertEqual(diff["added_count"], 1)
        self.assertEqual(diff["added_accounts"][0]["status"], "review")
        self.assertEqual(diff["added_accounts"][0]["fakeid"], "new-id")

    def test_changed_fakeid_requires_review_without_overwrite(self):
        registry = {"accounts": [{"account_id": "club", "account_name": "Club", "fakeid": "old", "status": "active"}]}
        exporter = [{"account_name": "Club", "fakeid": "new"}]
        diff = build_account_diff(registry, exporter, today="2026-05-21")
        self.assertEqual(diff["changed_fakeid_count"], 1)
        self.assertEqual(diff["changed_fakeids"][0]["decision"], "fakeid_changed_review_required")

    def test_active_registry_missing_in_docker_is_warning_not_delete(self):
        registry = {"accounts": [{"account_id": "club", "account_name": "Club", "fakeid": "old", "status": "active"}]}
        diff = build_account_diff(registry, [], today="2026-05-21")
        self.assertEqual(diff["missing_active_count"], 1)
        self.assertEqual(diff["missing_active_accounts"][0]["decision"], "active_registry_missing_in_docker")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
python -m unittest C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\tests\test_sync_weekly_accounts_from_exporter.py -v
```

Expected: FAIL with `ModuleNotFoundError` or missing `build_account_diff`.

- [ ] **Step 3: Implement minimal script**

```python
# tools/stage7_rewrite/scripts/sync_weekly_accounts_from_exporter.py
from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path
from typing import Any


def normalize_name(value: str) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


def account_id_from_name(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", normalize_name(name)).strip("_")
    return slug or "account_review"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_account_diff(registry: dict[str, Any], exporter_accounts: list[dict[str, Any]], today: str) -> dict[str, Any]:
    registry_accounts = registry.get("accounts") if isinstance(registry.get("accounts"), list) else []
    by_fakeid = {str(a.get("fakeid", "")): a for a in registry_accounts if a.get("fakeid")}
    by_name = {normalize_name(a.get("account_name", "")): a for a in registry_accounts if a.get("account_name")}
    exporter_fakeids = {str(a.get("fakeid", "")) for a in exporter_accounts if a.get("fakeid")}

    added: list[dict[str, Any]] = []
    changed: list[dict[str, Any]] = []
    for source in exporter_accounts:
        fakeid = str(source.get("fakeid", "")).strip()
        name = str(source.get("account_name", "")).strip()
        if not fakeid or not name:
            continue
        if fakeid in by_fakeid:
            continue
        existing = by_name.get(normalize_name(name))
        if existing:
            changed.append({
                "account_name": name,
                "old_fakeid_hash_source": "registry",
                "new_fakeid": fakeid,
                "decision": "fakeid_changed_review_required",
            })
            continue
        added.append({
            "account_id": account_id_from_name(name),
            "account_name": name,
            "fakeid": fakeid,
            "aliases": [],
            "city_key": "",
            "type": "unknown",
            "status": "review",
            "sync_priority": 5,
            "last_seen_at": today,
            "source": "wechat-article-exporter",
        })

    missing = []
    for account in registry_accounts:
        if account.get("status") == "active" and account.get("fakeid") and account.get("fakeid") not in exporter_fakeids:
            missing.append({
                "account_id": account.get("account_id", ""),
                "account_name": account.get("account_name", ""),
                "decision": "active_registry_missing_in_docker",
            })

    return {
        "schema_version": "weekly_account_diff.v1",
        "generated_at": today,
        "added_count": len(added),
        "changed_fakeid_count": len(changed),
        "missing_active_count": len(missing),
        "added_accounts": added,
        "changed_fakeids": changed,
        "missing_active_accounts": missing,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Diff Docker/exporter public-account inventory against weekly registry.")
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--exporter-accounts", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--write-registry", action="store_true")
    args = parser.parse_args()

    registry = load_json(args.registry)
    exporter_accounts = load_json(args.exporter_accounts)
    if isinstance(exporter_accounts, dict):
        exporter_accounts = exporter_accounts.get("accounts", [])
    diff = build_account_diff(registry, exporter_accounts, today=date.today().isoformat())
    write_json(args.out, diff)
    if args.write_registry and diff["added_accounts"]:
        registry.setdefault("accounts", []).extend(diff["added_accounts"])
        registry["updated_at"] = date.today().isoformat()
        write_json(args.registry, registry)
    print(json.dumps(diff, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```powershell
python -m unittest C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\tests\test_sync_weekly_accounts_from_exporter.py -v
```

Expected: PASS, 3 tests.

- [ ] **Step 5: Commit task**

```powershell
git -C C:\code\githubstar\wechathtmldownload add tools/stage7_rewrite/scripts/sync_weekly_accounts_from_exporter.py tools/stage7_rewrite/tests/test_sync_weekly_accounts_from_exporter.py
git -C C:\code\githubstar\wechathtmldownload commit -m "feat: add weekly account inventory diff"
```

## Task 2: Exporter Auth Lease

**Files:**
- Create: `tools/stage7_rewrite/scripts/manage_weekly_exporter_auth_lease.py`
- Test: `tools/stage7_rewrite/tests/test_manage_weekly_exporter_auth_lease.py`

- [ ] **Step 1: Write failing tests**

```python
# tools/stage7_rewrite/tests/test_manage_weekly_exporter_auth_lease.py
import unittest

from tools.stage7_rewrite.scripts.manage_weekly_exporter_auth_lease import classify_lease


class ManageWeeklyExporterAuthLeaseTests(unittest.TestCase):
    def test_green_when_real_fetch_ok_and_fresh(self):
        lease = classify_lease({"session_ok": True, "decision": "exporter_session_ok"}, previous_hours=80)
        self.assertEqual(lease["status"], "green")

    def test_yellow_when_real_fetch_ok_but_expiring(self):
        lease = classify_lease({"session_ok": True, "decision": "exporter_session_ok"}, previous_hours=18)
        self.assertEqual(lease["status"], "yellow")

    def test_auth_required_on_invalid_session(self):
        lease = classify_lease({"session_ok": False, "decision": "exporter_session_invalid"}, previous_hours=80)
        self.assertEqual(lease["status"], "auth_required")
        self.assertTrue(lease["should_stop_before_build"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

```powershell
python -m unittest C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\tests\test_manage_weekly_exporter_auth_lease.py -v
```

Expected: FAIL with missing module or missing `classify_lease`.

- [ ] **Step 3: Implement minimal script**

```python
# tools/stage7_rewrite/scripts/manage_weekly_exporter_auth_lease.py
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


def classify_lease(session_report: dict[str, Any], previous_hours: float | None) -> dict[str, Any]:
    ok = bool(session_report.get("session_ok"))
    decision = str(session_report.get("decision", ""))
    if not ok:
        return {
            "status": "auth_required",
            "should_notify": True,
            "should_stop_before_build": True,
            "reason": decision or "session_not_ok",
        }
    remaining = float(previous_hours if previous_hours is not None else 96)
    if remaining < 36:
        return {
            "status": "yellow",
            "should_notify": True,
            "should_stop_before_build": False,
            "reason": "auth_expiring_within_36h",
        }
    return {
        "status": "green",
        "should_notify": False,
        "should_stop_before_build": False,
        "reason": "session_ok",
    }


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_session_diagnostic(command: list[str]) -> dict[str, Any]:
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    text = completed.stdout.strip()
    if not text:
        return {"session_ok": False, "decision": "diagnostic_no_output", "stderr": completed.stderr[:200]}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"session_ok": False, "decision": "diagnostic_bad_json", "stdout": text[:200]}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build weekly exporter auth lease from real article-fetch diagnostic.")
    parser.add_argument("--lease", type=Path, required=True)
    parser.add_argument("--diagnostic-command", nargs="+", required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    previous = read_json(args.lease)
    previous_hours = previous.get("remaining_hours_estimate")
    report = run_session_diagnostic(args.diagnostic_command)
    classified = classify_lease(report, previous_hours=previous_hours)
    now = datetime.now()
    lease = {
        "schema_version": "weekly_exporter_auth_lease.v1",
        "generated_at": now.isoformat(timespec="seconds"),
        "last_real_fetch_decision": report.get("decision", ""),
        "last_real_fetch_ok": bool(report.get("session_ok")),
        "expires_at_estimate": (now + timedelta(hours=96)).isoformat(timespec="seconds") if report.get("session_ok") else previous.get("expires_at_estimate", ""),
        "remaining_hours_estimate": 96 if report.get("session_ok") else previous_hours,
        **classified,
    }
    write_json(args.out or args.lease, lease)
    print(json.dumps(lease, ensure_ascii=False, indent=2))
    return 2 if lease["should_stop_before_build"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

```powershell
python -m unittest C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\tests\test_manage_weekly_exporter_auth_lease.py -v
```

Expected: PASS, 3 tests.

- [ ] **Step 5: Commit task**

```powershell
git -C C:\code\githubstar\wechathtmldownload add tools/stage7_rewrite/scripts/manage_weekly_exporter_auth_lease.py tools/stage7_rewrite/tests/test_manage_weekly_exporter_auth_lease.py
git -C C:\code\githubstar\wechathtmldownload commit -m "feat: add weekly exporter auth lease gate"
```

## Task 3: Login Notice Sender

**Files:**
- Create: `tools/stage7_rewrite/scripts/send_weekly_login_notice.py`
- Test: `tools/stage7_rewrite/tests/test_send_weekly_login_notice.py`

- [ ] **Step 1: Write failing tests**

```python
# tools/stage7_rewrite/tests/test_send_weekly_login_notice.py
import unittest

from tools.stage7_rewrite.scripts.send_weekly_login_notice import build_notice_payload


class SendWeeklyLoginNoticeTests(unittest.TestCase):
    def test_notice_never_contains_auth_key(self):
        payload = build_notice_payload(run_id="r1", status="auth_required", login_url="http://127.0.0.1:17300", reason="invalid")
        text = payload["text"].lower()
        self.assertIn("r1", text)
        self.assertIn("http://127.0.0.1:17300", text)
        self.assertNotIn("auth_key", text)
        self.assertNotIn("cookie", text)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

```powershell
python -m unittest C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\tests\test_send_weekly_login_notice.py -v
```

Expected: FAIL with missing module or missing `build_notice_payload`.

- [ ] **Step 3: Implement minimal sender**

```python
# tools/stage7_rewrite/scripts/send_weekly_login_notice.py
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any
from urllib import request, parse


def build_notice_payload(run_id: str, status: str, login_url: str, reason: str) -> dict[str, str]:
    return {
        "text": (
            f"HUAIDJ weekly exporter login needed\n"
            f"run_id: {run_id}\n"
            f"status: {status}\n"
            f"reason: {reason}\n"
            f"open: {login_url}\n"
            f"Scan the WeChat login QR, then OpenClaw will verify with a real article fetch."
        )
    }


def send_telegram(bot_token: str, chat_id: str, text: str, photo: Path | None) -> dict[str, Any]:
    if photo and photo.exists():
        url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
        boundary = "----weekly-login-boundary"
        body = (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n{chat_id}\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"caption\"\r\n\r\n{text}\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"login.png\"\r\n"
            f"Content-Type: image/png\r\n\r\n"
        ).encode("utf-8") + photo.read_bytes() + f"\r\n--{boundary}--\r\n".encode("utf-8")
        req = request.Request(url, data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    else:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        data = parse.urlencode({"chat_id": chat_id, "text": text}).encode("utf-8")
        req = request.Request(url, data=data)
    with request.urlopen(req, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Send weekly exporter login notice without secrets.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--status", required=True)
    parser.add_argument("--reason", default="")
    parser.add_argument("--login-url", default="http://127.0.0.1:17300")
    parser.add_argument("--qr-image", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    payload = build_notice_payload(args.run_id, args.status, args.login_url, args.reason)
    result = {"telegram": "skipped_missing_env", "imessage": "skipped_bridge_unavailable"}
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if token and chat_id:
        result["telegram"] = send_telegram(token, chat_id, payload["text"], args.qr_image)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({"payload": payload, "result": result}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"payload": payload, "result": result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

```powershell
python -m unittest C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\tests\test_send_weekly_login_notice.py -v
```

Expected: PASS, 1 test.

- [ ] **Step 5: Commit task**

```powershell
git -C C:\code\githubstar\wechathtmldownload add tools/stage7_rewrite/scripts/send_weekly_login_notice.py tools/stage7_rewrite/tests/test_send_weekly_login_notice.py
git -C C:\code\githubstar\wechathtmldownload commit -m "feat: add weekly login notice sender"
```

## Task 4: Wire Preflight Into Wrapper

**Files:**
- Modify: `tools/stage7_rewrite/run_openclaw_weekly_daily_publish.ps1`
- Test: existing wrapper smoke through `-DryRun -SkipBuild`

- [ ] **Step 1: Add parameters**

Add parameters near the existing parameter list:

```powershell
[switch]$SkipAccountSync,
[switch]$SkipAuthLeaseCheck,
[string]$ExporterAccountsPath = "",
[string]$RunStateRoot = ""
```

- [ ] **Step 2: Define run-state paths**

After `$RunReportDir` is defined, add:

```powershell
if ([string]::IsNullOrWhiteSpace($RunStateRoot)) {
    $RunStateRoot = Join-Path $Reports "openclaw_weekly_run_state"
}
$RunStateDir = Join-Path $RunStateRoot $RunId
$AccountDiffPath = Join-Path $RunStateDir "account_diff.json"
$AuthLeasePath = Join-Path $RunStateDir "auth_lease.json"
$LoginNoticePath = Join-Path $RunStateDir "login_notice.json"
New-Item -ItemType Directory -Force -Path $RunStateDir | Out-Null
```

- [ ] **Step 3: Add account sync preflight**

Before the current build step, add:

```powershell
if (-not $SkipAccountSync) {
    Invoke-RunStep "Scan Docker/exporter account inventory" {
        if ([string]::IsNullOrWhiteSpace($ExporterAccountsPath) -or -not (Test-Path -LiteralPath $ExporterAccountsPath)) {
            Write-Host "  Exporter account inventory path not provided; recording skipped account sync." -ForegroundColor Yellow
            @{ schema_version = "weekly_account_diff.v1"; decision = "skipped_missing_exporter_accounts_path" } |
                ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $AccountDiffPath -Encoding UTF8
        } else {
            python (Join-Path $Scripts "sync_weekly_accounts_from_exporter.py") `
                --registry (Join-Path $Stage7 "registries\weekly_accounts_seed.json") `
                --exporter-accounts $ExporterAccountsPath `
                --out $AccountDiffPath `
                --write-registry
        }
    }
}
```

- [ ] **Step 4: Add auth lease gate**

Before the current build step and after account sync, add:

```powershell
if (-not $SkipAuthLeaseCheck) {
    Invoke-RunStep "Check Docker exporter auth lease" {
        $diagnosticScript = Join-Path $Scripts "diagnose_weekly_exporter_session.py"
        python (Join-Path $Scripts "manage_weekly_exporter_auth_lease.py") `
            --lease $AuthLeasePath `
            --out $AuthLeasePath `
            --diagnostic-command python $diagnosticScript --registry (Join-Path $Stage7 "registries\weekly_accounts_seed.json") --endpoint "http://127.0.0.1:17300" --auth-env "MPTEXT_AUTH_KEY"
        $lease = Get-Content -Raw -LiteralPath $AuthLeasePath | ConvertFrom-Json
        if ($lease.should_notify) {
            python (Join-Path $Scripts "send_weekly_login_notice.py") `
                --run-id $RunId `
                --status $lease.status `
                --reason $lease.reason `
                --out $LoginNoticePath
        }
        if ($lease.should_stop_before_build) {
            throw "Exporter auth required; login notice sent and build stopped before touching release package."
        }
    }
}
```

- [ ] **Step 5: Run dry wrapper smoke**

```powershell
powershell -ExecutionPolicy Bypass -File C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\run_openclaw_weekly_daily_publish.ps1 -DryRun -SkipBuild -SkipAccountSync -SkipAuthLeaseCheck
```

Expected: exits 0 and prints the wrapper configuration without build/deploy/upload.

- [ ] **Step 6: Commit task**

```powershell
git -C C:\code\githubstar\wechathtmldownload add tools/stage7_rewrite/run_openclaw_weekly_daily_publish.ps1
git -C C:\code\githubstar\wechathtmldownload commit -m "feat: gate weekly publish with account and auth preflight"
```

## Task 5: OpenClaw Schedule Config

**Files:**
- Create: `tools/stage7_rewrite/config/openclaw_weekly_twice_daily.tasks.json`

- [ ] **Step 1: Create schedule config**

```json
{
  "schema_version": "openclaw_tasks.v1",
  "timezone": "Asia/Shanghai",
  "tasks": [
    {
      "id": "huaidj-weekly-morning",
      "name": "HUAIDJ Weekly Morning Source-Gated Publish",
      "schedule": "10 7 * * *",
      "workspace": "C:\\code\\githubstar\\wechathtmldownload",
      "command": "powershell -ExecutionPolicy Bypass -File C:\\code\\githubstar\\wechathtmldownload\\tools\\stage7_rewrite\\run_openclaw_weekly_daily_publish.ps1 -DeployBackend -UploadFrontend -Desc \"OpenClaw morning source-gated\"",
      "single_instance_key": "huaidj-weekly-publish",
      "notify_on": ["failed", "auth_required", "published"]
    },
    {
      "id": "huaidj-weekly-evening",
      "name": "HUAIDJ Weekly Evening Source-Gated Publish",
      "schedule": "10 19 * * *",
      "workspace": "C:\\code\\githubstar\\wechathtmldownload",
      "command": "powershell -ExecutionPolicy Bypass -File C:\\code\\githubstar\\wechathtmldownload\\tools\\stage7_rewrite\\run_openclaw_weekly_daily_publish.ps1 -DeployBackend -UploadFrontend -Desc \"OpenClaw evening source-gated\"",
      "single_instance_key": "huaidj-weekly-publish",
      "notify_on": ["failed", "auth_required", "published"]
    },
    {
      "id": "huaidj-weekly-auth-health",
      "name": "HUAIDJ Weekly Exporter Auth Health",
      "schedule": "0 */6 * * *",
      "workspace": "C:\\code\\githubstar\\wechathtmldownload",
      "command": "python C:\\code\\githubstar\\wechathtmldownload\\tools\\stage7_rewrite\\scripts\\diagnose_weekly_exporter_session.py --registry C:\\code\\githubstar\\wechathtmldownload\\tools\\stage7_rewrite\\registries\\weekly_accounts_seed.json --endpoint http://127.0.0.1:17300 --auth-env MPTEXT_AUTH_KEY",
      "single_instance_key": "huaidj-weekly-auth-health",
      "notify_on": ["failed", "auth_required"]
    }
  ]
}
```

- [ ] **Step 2: Validate JSON**

```powershell
python -m json.tool C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\config\openclaw_weekly_twice_daily.tasks.json > $env:TEMP\openclaw_weekly_twice_daily.tasks.pretty.json
```

Expected: exits 0.

- [ ] **Step 3: Commit task**

```powershell
git -C C:\code\githubstar\wechathtmldownload add tools/stage7_rewrite/config/openclaw_weekly_twice_daily.tasks.json
git -C C:\code\githubstar\wechathtmldownload commit -m "docs: add OpenClaw twice daily schedule config"
```

## Task 6: Runbook Update And Verification

**Files:**
- Modify: `tools/stage7_rewrite/OPENCLAW_WEEKLY_DAILY_UPDATE_RUNBOOK.md`
- Modify if needed: `apps/weekly_activity_miniprogram/OPENCLAW_AUTOMATION.md`

- [ ] **Step 1: Update runbook**

Document:

- Morning/evening schedule.
- Account inventory scan every run.
- Auth lease states: `green`, `yellow`, `auth_required`, `waiting_for_scan`, `recovered`.
- Telegram primary notification.
- iMessage via configured Mac relay only.
- Stop-before-build behavior when auth is invalid.
- No automatic WeChat review submission.

- [ ] **Step 2: Verify docs contain no placeholder markers**

```powershell
$patterns = @('TB' + 'D', 'TO' + 'DO', '<' + 'key>', '<' + 'secret>', 'paste' + '-current-key')
Select-String -Path C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\OPENCLAW_WEEKLY_DAILY_UPDATE_RUNBOOK.md -Pattern $patterns
```

Expected: no matches in the new sections.

- [ ] **Step 3: Run focused tests**

```powershell
python -m unittest `
  C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\tests\test_sync_weekly_accounts_from_exporter.py `
  C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\tests\test_manage_weekly_exporter_auth_lease.py `
  C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\tests\test_send_weekly_login_notice.py `
  C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\tests\test_diagnose_weekly_exporter_session.py `
  C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\tests\test_validate_weekly_daily_queue_refresh.py -v
```

Expected: all tests pass.

- [ ] **Step 4: Run mini-program fallback tests**

```powershell
Push-Location C:\code\githubstar\wechathtmldownload\apps\weekly_activity_miniprogram
node --test tests/api-static-fallback.test.cjs
Pop-Location
```

Expected: PASS; confirms frontend can survive Cloud container failure through public/static fallback.

- [ ] **Step 5: Commit task**

```powershell
git -C C:\code\githubstar\wechathtmldownload add tools/stage7_rewrite/OPENCLAW_WEEKLY_DAILY_UPDATE_RUNBOOK.md apps/weekly_activity_miniprogram/OPENCLAW_AUTOMATION.md
git -C C:\code\githubstar\wechathtmldownload commit -m "docs: document weekly twice daily operations runbook"
```

## Final Release Gate

- [ ] Account diff script passes tests.
- [ ] Auth lease script passes tests.
- [ ] Login notice sender passes tests and does not include auth keys/cookies in payload.
- [ ] Wrapper dry smoke passes with preflight skipped.
- [ ] Wrapper preflight stops before build when auth is invalid.
- [ ] OpenClaw schedule JSON validates.
- [ ] Existing daily queue validation tests pass.
- [ ] Existing mini-program public/static fallback tests pass.
- [ ] No CloudRun deploy is run until the user explicitly selects implementation execution.
- [ ] No mini-program upload is run until the backend remote smoke passes in implementation.
- [ ] No WeChat review submission is automated.

## Execution Choice

Plan complete. Recommended execution mode is subagent-driven development: one worker for account diff, one for auth lease/notification, one for wrapper wiring, then one final verification worker.
