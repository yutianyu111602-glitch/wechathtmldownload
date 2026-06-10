#!/usr/bin/env python3
"""Audit the Weekly/Atlas user-command recall ledger.

Report-only. This does not deploy, upload, submit review, call providers or
LLMs, read secrets, write coordinates, mutate databases, or scan broad disks.
It only checks the command ledger structure and referenced evidence paths.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_LEDGER = REPO_ROOT / "reports" / "WEEKLY_USER_COMMAND_RECALL_EXECUTION_LEDGER_20260531.md"
DEFAULT_OUT_DIR = REPO_ROOT / "tools" / "stage7_rewrite" / "reports" / "weekly_user_command_ledger_audit_s32_20260531"

REQUIRED_CLUSTERS = {
    "Full takeover / understand everything",
    "CloudRun / mini-program production path",
    "DB1 + DB2 + DB3 unification",
    "DJ / venue relation surface",
    "DJ Interview",
    "Week/month mobile preview",
    "Mixtape / listen feature",
    "Address / coordinate repair",
    "OpenClaw skill / self-optimization",
    "Incremental build speed",
    "CodeGraph / understand-anything / codeflow",
    "Runtime maintenance / memory",
    "Anti-commercial product constitution",
}

REQUIRED_LEDGER_TOKENS = {
    "s28_original_link": "WEEKLY_MINIPROGRAM_EXTERNAL_LINK_ACTION_S28_20260531.md",
    "s29_event_handler": "WEEKLY_MINIPROGRAM_EVENT_HANDLER_COVERAGE_S29_20260531.md",
    "s30_full_preflight": "WEEKLY_DEPLOY_UPLOAD_PREFLIGHT_FULL_MINIAPP_S30_20260531.md",
}

REQUIRED_BLOCKER_TOKENS = {
    "rust_club": "Rust Club",
    "tencent_111": "Tencent status `111`",
    "devtools_protocol": "DevTools rendered mini-program behavior tests remain blocked",
}

PATH_PREFIXES = (
    "apps/",
    "apps\\",
    "docs/",
    "docs\\",
    "reports/",
    "reports\\",
    "services/",
    "services\\",
    "tools/",
    "tools\\",
    "package.json",
    "README.md",
    "\\\\wsl.localhost\\",
)

PATH_SUFFIXES = (
    ".cjs",
    ".html",
    ".js",
    ".json",
    ".md",
    ".mjs",
    ".ps1",
    ".py",
    ".sqlite",
    ".wxml",
    ".wxss",
)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def normalize_markdown_path(value: str, repo_root: Path) -> Path | None:
    raw = value.strip()
    if not raw:
        return None
    normalized = raw.replace("/", "\\")
    if raw.startswith("\\\\wsl.localhost\\"):
        return Path(raw)
    if raw.startswith("\\\\"):
        return Path(raw)
    if not raw.startswith(PATH_PREFIXES) and not raw.endswith(PATH_SUFFIXES):
        return None
    if ":" in raw[:4]:
        return Path(raw)
    return repo_root / normalized


def parse_clusters(text: str) -> list[dict[str, Any]]:
    clusters: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.startswith("| "):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 4:
            continue
        if cells[0] in {"Cluster", "---"}:
            continue
        evidence_refs = re.findall(r"`([^`]+)`", cells[3])
        clusters.append(
            {
                "cluster": cells[0],
                "intent": cells[1],
                "status": cells[2],
                "evidence": cells[3],
                "evidence_refs": evidence_refs,
            }
        )
    return clusters


def extract_section(text: str, heading: str) -> str:
    marker = f"## {heading}"
    start = text.find(marker)
    if start < 0:
        return ""
    next_start = text.find("\n## ", start + len(marker))
    if next_start < 0:
        return text[start:]
    return text[start:next_start]


def check_evidence_paths(clusters: list[dict[str, Any]], repo_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    checked: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    for row in clusters:
        for ref in row["evidence_refs"]:
            path = normalize_markdown_path(ref, repo_root)
            if path is None:
                continue
            exists = path.exists()
            checked.append(
                {
                    "cluster": row["cluster"],
                    "ref": ref,
                    "path": str(path),
                    "exists": exists,
                }
            )
            if not exists:
                findings.append(
                    {
                        "code": "missing_evidence_path",
                        "cluster": row["cluster"],
                        "ref": ref,
                        "path": str(path),
                    }
                )
    return checked, findings


def audit_ledger(ledger_path: Path, repo_root: Path) -> dict[str, Any]:
    text = read_text(ledger_path)
    clusters = parse_clusters(text)
    cluster_names = {row["cluster"] for row in clusters}
    findings: list[dict[str, Any]] = []

    for name in sorted(REQUIRED_CLUSTERS - cluster_names):
        findings.append({"code": "missing_required_cluster", "cluster": name})

    checked_paths, path_findings = check_evidence_paths(clusters, repo_root)
    findings.extend(path_findings)

    for code, token in REQUIRED_LEDGER_TOKENS.items():
        if token not in text:
            findings.append({"code": "missing_required_ledger_token", "token_code": code, "token": token})

    blockers = extract_section(text, "Current Blockers")
    for code, token in REQUIRED_BLOCKER_TOKENS.items():
        if token not in blockers:
            findings.append({"code": "missing_required_blocker", "token_code": code, "token": token})

    next_safe = extract_section(text, "Next Safe Actions")
    if "weekly:deploy-upload:preflight" not in next_safe:
        findings.append({"code": "missing_preflight_next_safe_action"})
    if "DevTools" not in next_safe:
        findings.append({"code": "missing_devtools_next_safe_action"})

    address_row = next((row for row in clusters if row["cluster"] == "Address / coordinate repair"), None)
    if address_row and "blocked" not in address_row["status"].lower():
        findings.append(
            {
                "code": "address_coordinate_not_marked_blocked",
                "status": address_row["status"],
            }
        )

    boundary = extract_section(text, "Boundary")
    for token in ("did not deploy", "write coordinates", "print secrets"):
        if token not in boundary:
            findings.append({"code": "missing_boundary_token", "token": token})

    decision = "weekly_user_command_ledger_audit_passed" if not findings else "weekly_user_command_ledger_audit_failed"
    return {
        "schema_version": "weekly_user_command_ledger_audit.v1",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "decision": decision,
        "ledger_path": str(ledger_path),
        "cluster_count": len(clusters),
        "required_cluster_count": len(REQUIRED_CLUSTERS),
        "checked_evidence_path_count": len(checked_paths),
        "missing_evidence_path_count": sum(1 for finding in findings if finding["code"] == "missing_evidence_path"),
        "finding_count": len(findings),
        "clusters": clusters,
        "checked_evidence_paths": checked_paths,
        "findings": findings,
        "boundary": {
            "report_only": True,
            "deploy_executed": False,
            "upload_executed": False,
            "review_submitted": False,
            "db_graph_vector_write": False,
            "coordinate_write": False,
            "provider_or_llm_call": False,
            "secret_read": False,
            "broad_disk_scan": False,
        },
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Weekly User Command Ledger Audit",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Ledger: `{report['ledger_path']}`",
        f"- Cluster count: `{report['cluster_count']}`",
        f"- Required clusters: `{report['required_cluster_count']}`",
        f"- Checked evidence paths: `{report['checked_evidence_path_count']}`",
        f"- Finding count: `{report['finding_count']}`",
        "",
        "## Cluster Status",
        "",
    ]
    for row in report["clusters"]:
        lines.append(f"- `{row['cluster']}`: {row['status']}")

    lines.extend(["", "## Findings", ""])
    if not report["findings"]:
        lines.append("No ledger structure, blocker, S28/S29/S30 token, or evidence-path findings.")
    else:
        for finding in report["findings"]:
            lines.append(f"- `{finding['code']}`: `{json.dumps(finding, ensure_ascii=False, sort_keys=True)}`")

    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "This audit is report-only. It does not deploy CloudRun, upload or submit a mini-program, mutate DB/graph/vector data, write coordinates, call map providers or LLMs, fetch/cache/proxy media, read secrets, or scan broad disks.",
            "",
        ]
    )
    return "\n".join(lines)


def write_reports(report: dict[str, Any], out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "weekly_user_command_ledger_audit.json"
    md_path = out_dir / "weekly_user_command_ledger_audit.md"
    write_json(json_path, report)
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": md_path}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--json-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    report = audit_ledger(args.ledger, args.repo_root)
    paths = write_reports(report, args.out_dir)
    if args.json_only:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        print(
            json.dumps(
                {
                    "decision": report["decision"],
                    "cluster_count": report["cluster_count"],
                    "finding_count": report["finding_count"],
                    "json": str(paths["json"]),
                    "markdown": str(paths["markdown"]),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0 if report["decision"] == "weekly_user_command_ledger_audit_passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
