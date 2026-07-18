#!/usr/bin/env python3
"""Scan tracked text for committed HUAIDJ credential literals.

Findings report only path, line, and rule. Secret-looking values are never
echoed. Explicit test fixtures may opt out on the same line with the marker
``secret-scan: allow-test-fixture``.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
ALLOW_MARKER = "secret-scan: allow-test-fixture"
MPTEXT_ASSIGNMENT = re.compile(
    r"\$env:MPTEXT_AUTH_KEY\s*=\s*([\"'])(?P<value>.*?)\1",
    re.IGNORECASE,
)
HEX_32 = re.compile(r"(?<![0-9a-f])[0-9a-f]{32}(?![0-9a-f])", re.IGNORECASE)
AUTH_CONTEXT = re.compile(
    r"MPTEXT|AUTH[_ -]?KEY|API[_ -]?KEY|CREDENTIAL",
    re.IGNORECASE,
)
TEXT_SUFFIXES = {
    ".cjs",
    ".js",
    ".json",
    ".md",
    ".mjs",
    ".ps1",
    ".py",
    ".sh",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}


def scan_text(path: str, text: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        if ALLOW_MARKER in line:
            continue
        assignment = MPTEXT_ASSIGNMENT.search(line)
        if assignment:
            value = assignment.group("value").strip()
            if value and not (value.startswith("<") and value.endswith(">")):
                findings.append(
                    {"path": path, "line": line_number, "rule": "literal_mptext_auth_assignment"}
                )
        if AUTH_CONTEXT.search(line) and HEX_32.search(line):
            findings.append(
                {"path": path, "line": line_number, "rule": "auth_context_32_hex_literal"}
            )
    return findings


def tracked_files(repo: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        check=True,
        capture_output=True,
    )
    return [repo / raw.decode("utf-8", errors="surrogateescape") for raw in result.stdout.split(b"\0") if raw]


def scan_repo(repo: Path) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    scanned = 0
    for path in tracked_files(repo):
        if path.suffix.lower() not in TEXT_SUFFIXES or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            continue
        scanned += 1
        findings.extend(scan_text(path.relative_to(repo).as_posix(), text))
    return {
        "schema_version": "huaidj_tracked_secret_scan.v1",
        "ok": not findings,
        "scanned_file_count": scanned,
        "finding_count": len(findings),
        "findings": findings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=REPO_ROOT)
    args = parser.parse_args()
    report = scan_repo(args.repo.resolve())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
