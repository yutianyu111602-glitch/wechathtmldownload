from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "run_huaidj_sanji_daily_twice.ps1"
WINDOWS_POWERSHELL = shutil.which("powershell")
POWERSHELL = WINDOWS_POWERSHELL or shutil.which("pwsh")


def _lease_function_source() -> str:
    source = RUNNER.read_text(encoding="utf-8")
    start = source.index("function Acquire-Lock {")
    end = source.index("function Get-JsonProperty {", start)
    return source[start:end]


def _write_harness(tmp_path: Path) -> Path:
    harness = tmp_path / "lease-harness.ps1"
    harness.write_text(
        """
param(
    [Parameter(Mandatory = $true)][string]$Mode,
    [Parameter(Mandatory = $true)][string]$LeasePath,
    [switch]$AgeMetadata,
    [switch]$WaitAfterRelease
)
$ErrorActionPreference = "Stop"
$LockPath = $LeasePath
$LockDir = Split-Path -Parent $LockPath
$LockTimeoutMinutes = 1

"""
        + _lease_function_source()
        + r"""

function Set-AgedMetadata {
    param($Lock)
    $metadata = $Lock.metadata
    $metadata.started_at = (Get-Date).ToUniversalTime().AddDays(-30).ToString("o")
    $metadata.stale_metadata_after_minutes = 1
    $json = $metadata | ConvertTo-Json -Compress
    $bytes = (New-Object System.Text.UTF8Encoding($false)).GetBytes($json)
    $Lock.stream.SetLength([Math]::Max(1, $bytes.Length))
    $Lock.stream.Position = 0
    $Lock.stream.Write($bytes, 0, $bytes.Length)
    $Lock.stream.Flush($true)
}

if ($Mode -eq "try") {
    try {
        $lease = Acquire-Lock
        [Console]::Out.WriteLine("ACQUIRED:{0}" -f $lease.lease_token)
        [Console]::Out.Flush()
        Release-Lock -Lock $lease
        exit 0
    } catch {
        [Console]::Out.WriteLine("BLOCKED:{0}" -f $_.Exception.Message)
        [Console]::Out.Flush()
        exit 23
    }
}

if ($Mode -eq "release-failure") {
    $WarningPreference = "Stop"
    $fake = [PSCustomObject]@{
        unlocked = $false
        disposed = $false
    }
    $fake | Add-Member -MemberType ScriptMethod -Name SetLength -Value { throw "simulated metadata write failure" }
    $fake | Add-Member -MemberType ScriptMethod -Name Unlock -Value { param($offset, $length); $this.unlocked = $true }
    $fake | Add-Member -MemberType ScriptMethod -Name Dispose -Value { $this.disposed = $true }
    $lease = @{ stream = $fake; lease_token = "failing-release" }
    Release-Lock -Lock $lease
    [Console]::Out.WriteLine((
        "RESULT:unlocked={0};disposed={1};stream_null={2}" -f @(
            $fake.unlocked,
            $fake.disposed,
            ($null -eq $lease.stream)
        )
    ))
    [Console]::Out.Flush()
    exit 0
}

if ($Mode -ne "hold") {
    throw "Unsupported harness mode: $Mode"
}

$lease = Acquire-Lock
if ($AgeMetadata) {
    Set-AgedMetadata -Lock $lease
}
[Console]::Out.WriteLine("ACQUIRED:{0}" -f $lease.lease_token)
if ($AgeMetadata) {
    [Console]::Out.WriteLine("AGED:{0}" -f $lease.metadata.started_at)
}
[Console]::Out.Flush()
[Console]::In.ReadLine() | Out-Null
Release-Lock -Lock $lease
[Console]::Out.WriteLine("RELEASED")
[Console]::Out.Flush()
if ($WaitAfterRelease) {
    [Console]::In.ReadLine() | Out-Null
}
""",
        encoding="utf-8",
    )
    return harness


def _command(harness: Path, mode: str, lease_path: Path, *extra: str) -> list[str]:
    assert POWERSHELL is not None
    return [
        POWERSHELL,
        "-NoLogo",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(harness),
        "-Mode",
        mode,
        "-LeasePath",
        str(lease_path),
        *extra,
    ]


def _start_holder(
    harness: Path,
    lease_path: Path,
    *extra: str,
) -> tuple[subprocess.Popen[str], str, str | None]:
    holder = subprocess.Popen(
        _command(harness, "hold", lease_path, *extra),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert holder.stdout is not None
    acquired = holder.stdout.readline().strip()
    assert acquired.startswith("ACQUIRED:"), (
        acquired,
        holder.stderr.read() if holder.stderr else "",
    )
    aged_started_at = None
    if "-AgeMetadata" in extra:
        aged = holder.stdout.readline().strip()
        assert aged.startswith("AGED:"), aged
        aged_started_at = aged.removeprefix("AGED:")
    return holder, acquired.removeprefix("ACQUIRED:"), aged_started_at


def _release(holder: subprocess.Popen[str], *, keep_process: bool = False) -> None:
    assert holder.stdin is not None
    assert holder.stdout is not None
    holder.stdin.write("release\n")
    holder.stdin.flush()
    assert holder.stdout.readline().strip() == "RELEASED"
    if not keep_process:
        holder.wait(timeout=10)
        assert holder.returncode == 0, holder.stderr.read() if holder.stderr else ""


def _stop(holder: subprocess.Popen[str]) -> None:
    if holder.poll() is None:
        holder.kill()
    holder.wait(timeout=10)


pytestmark = pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")


def test_first_owner_blocks_second_owner(tmp_path: Path) -> None:
    harness = _write_harness(tmp_path)
    lease_path = tmp_path / "leases" / "daily.lock"
    holder, _token, _aged = _start_holder(harness, lease_path)
    try:
        contender = subprocess.run(
            _command(harness, "try", lease_path),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        assert contender.returncode == 23
        assert "BLOCKED:Another Sanji daily publish run holds the operating-system lease" in contender.stdout
    finally:
        _release(holder)


def test_release_metadata_failure_still_cleans_up_without_throwing(tmp_path: Path) -> None:
    harness = _write_harness(tmp_path)
    result = subprocess.run(
        _command(harness, "release-failure", tmp_path / "leases" / "daily.lock"),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "RESULT:unlocked=True;disposed=True;stream_null=True" in result.stdout


@pytest.mark.skipif(WINDOWS_POWERSHELL is None, reason="Windows PowerShell 5 is required")
def test_runner_parses_in_windows_powershell_5(tmp_path: Path) -> None:
    assert WINDOWS_POWERSHELL is not None
    parse_probe = tmp_path / "parse-probe.ps1"
    parse_probe.write_text(
        """
param([string]$ScriptPath)
$tokens = $null
$errors = $null
[System.Management.Automation.Language.Parser]::ParseFile(
    $ScriptPath,
    [ref]$tokens,
    [ref]$errors
) | Out-Null
if ($errors.Count -gt 0) {
    $errors | ForEach-Object { [Console]::Error.WriteLine($_.Message) }
    exit 1
}
[Console]::Out.WriteLine($PSVersionTable.PSVersion.ToString())
""",
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            WINDOWS_POWERSHELL,
            "-NoLogo",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(parse_probe),
            "-ScriptPath",
            str(RUNNER),
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().startswith("5.1.")


@pytest.mark.parametrize("owner_exit", ["release", "crash"])
def test_owner_exit_or_release_allows_reacquire(tmp_path: Path, owner_exit: str) -> None:
    harness = _write_harness(tmp_path)
    lease_path = tmp_path / "leases" / "daily.lock"
    holder, _token, _aged = _start_holder(harness, lease_path)
    if owner_exit == "release":
        _release(holder)
    else:
        _stop(holder)

    successor = subprocess.run(
        _command(harness, "try", lease_path),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert successor.returncode == 0, successor.stderr
    assert successor.stdout.startswith("ACQUIRED:")


def test_aged_metadata_cannot_steal_active_os_lease(tmp_path: Path) -> None:
    harness = _write_harness(tmp_path)
    lease_path = tmp_path / "leases" / "daily.lock"
    holder, owner_token, aged_started_at = _start_holder(harness, lease_path, "-AgeMetadata")
    try:
        assert aged_started_at is not None
        aged_at = datetime.fromisoformat(aged_started_at.replace("Z", "+00:00"))
        assert aged_at < datetime.now(timezone.utc) - timedelta(days=29)

        contender = subprocess.run(
            _command(harness, "try", lease_path),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        assert contender.returncode == 23
        assert contender.stdout.startswith("BLOCKED:")
    finally:
        _release(holder)
    released = json.loads(lease_path.read_text(encoding="utf-8"))
    assert released["lease_token"] == owner_token
    assert released["active"] is False


def test_releasing_owner_never_deletes_successor_lease(tmp_path: Path) -> None:
    harness = _write_harness(tmp_path)
    lease_path = tmp_path / "leases" / "daily.lock"
    first, _first_token, _aged = _start_holder(harness, lease_path, "-WaitAfterRelease")
    _release(first, keep_process=True)

    successor, successor_token, _successor_aged = _start_holder(harness, lease_path)
    try:
        assert first.stdin is not None
        first.stdin.write("exit\n")
        first.stdin.flush()
        first.wait(timeout=10)
        assert first.returncode == 0, first.stderr.read() if first.stderr else ""

        assert lease_path.exists()
        contender = subprocess.run(
            _command(harness, "try", lease_path),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        assert contender.returncode == 23
    finally:
        _release(successor)
    metadata = json.loads(lease_path.read_text(encoding="utf-8"))
    assert metadata["active"] is False
    assert metadata["lease_token"] == successor_token
