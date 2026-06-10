#!/usr/bin/env python3
"""Build a no-write inventory for the S117 external-link/DB2 restart lane.

The inventory is intentionally local and report-only. It classifies existing
scripts, tests, sidecar/candidate DB artifacts, lock/cache hints, and local
weapon-catalog entries without reading cookie values, browser profiles, .env
files, or production databases.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[3]
REPORTS_ROOT = REPO_ROOT / "tools" / "stage7_rewrite" / "reports"
DEFAULT_OUT_DIR = REPORTS_ROOT / "external_link_db2_inventory_s117_20260601"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_EXTERNAL_LINK_DB2_INVENTORY_S117_20260601.md"
DEFAULT_WEAPON_CATALOG = Path("//wsl.localhost/Ubuntu/home/pc/reports/WEAPON_CATALOG_20260601.md")
DEFAULT_ARSENAL_SKILL = Path("C:/Users/pc/.codex/skills/external-link-db2-arsenal/SKILL.md")
CURRENT_STORY_ID = "S117"

IGNORED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    "vendor",
    ".understand-anything",
    ".codegraph",
    "tmp",
    "dist",
    "build",
    "coverage",
}

SCAN_ROOTS = [
    "tools/stage7_rewrite/scripts",
    "tools/stage7_rewrite/tests",
    "tools/stage7_rewrite/weekly_atlas_bridge",
    "apps/weekly_activity_miniprogram",
    "services/weekly_activity_cloudrun/src",
    "services/weekly_activity_cloudrun/scripts",
    "services/weekly_activity_cloudrun/tests",
    "docs/threads",
    "docs/longrun/atlas-route-external-db-20260531",
    "reports",
]

INCLUDED_SUFFIXES = {
    ".py",
    ".js",
    ".cjs",
    ".mjs",
    ".ts",
    ".json",
    ".jsonl",
    ".md",
    ".sqlite",
    ".db",
    ".ps1",
    ".sh",
}

CATEGORY_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("external_link", re.compile(r"outlink|external|social|instagram|mixtape|music|radio|video|soundcloud|bandcamp|bilibili|weibo|maigret|profile", re.I)),
    ("source_acquisition", re.compile(r"source|source_ref|evidence|article|wechat|acquisition|provenance", re.I)),
    ("db2_serving_sidecar", re.compile(r"db2|serving|sqlite|sidecar|candidate|projection|qdrant|neo4j|read_model", re.I)),
    ("mini_program_surface", re.compile(r"mini.?program|miniprogram|sourceAction|sourceArticles|externalLink|pages[/\\](artist|venue|detail|source|saved)", re.I)),
    ("docker_exporter_auth", re.compile(r"docker|exporter|login|qr|auth|session|cookie", re.I)),
    ("poster_lineup_ocr", re.compile(r"poster|lineup|ocr|mimo|vision|multimodal|image", re.I)),
    ("devtools_release_gate", re.compile(r"devtools|deploy|upload|preflight|review", re.I)),
]

SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("openai_or_generic_sk", re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}")),
    ("assignment_token", re.compile(r"(?i)\b(token|cookie|secret|password)\s*[:=]\s*['\"]?[^'\"\s]{12,}")),
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def rel_path(path: Path, root: Path = REPO_ROOT) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return path.as_posix()


def is_ignored_path(path: Path) -> bool:
    parts = set(path.parts)
    return bool(parts.intersection(IGNORED_DIRS))


def iter_project_files(root: Path, relative_roots: Iterable[str] = SCAN_ROOTS) -> Iterable[Path]:
    for rel_root in relative_roots:
        start = root / rel_root
        if not start.exists():
            continue
        for current, dirs, files in os.walk(start):
            current_path = Path(current)
            dirs[:] = [name for name in dirs if name not in IGNORED_DIRS and not name.startswith(".git")]
            if is_ignored_path(current_path.relative_to(root)):
                continue
            for name in files:
                path = current_path / name
                if path.suffix.lower() not in INCLUDED_SUFFIXES:
                    continue
                yield path


def classify_path(path_text: str) -> list[str]:
    categories = [name for name, pattern in CATEGORY_PATTERNS if pattern.search(path_text)]
    return categories or ["uncategorized"]


def file_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".sqlite", ".db"}:
        return "sqlite_artifact"
    if "tests" in path.parts or path.name.startswith("test_") or path.name.endswith(".test.cjs") or path.name.endswith(".test.mjs"):
        return "test"
    if suffix in {".py", ".js", ".cjs", ".mjs", ".ts", ".ps1", ".sh"}:
        return "script"
    if suffix in {".json", ".jsonl"}:
        return "data_or_report"
    if suffix == ".md":
        return "document"
    return "other"


def inspect_files(root: Path) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    db_artifacts: list[dict[str, Any]] = []
    lock_cache_candidates: list[dict[str, Any]] = []
    counters: dict[str, Counter[str]] = {
        "category": Counter(),
        "kind": Counter(),
        "suffix": Counter(),
    }

    for path in sorted(iter_project_files(root), key=lambda p: rel_path(p, root)):
        rel = rel_path(path, root)
        categories = classify_path(rel)
        kind = file_kind(path)
        suffix = path.suffix.lower()
        for category in categories:
            counters["category"][category] += 1
        counters["kind"][kind] += 1
        counters["suffix"][suffix] += 1
        try:
            size = path.stat().st_size
        except OSError:
            size = None
        record = {
            "path": rel,
            "kind": kind,
            "categories": categories,
            "size_bytes": size,
        }
        if set(categories) - {"uncategorized"}:
            items.append(record)
        if kind == "sqlite_artifact":
            db_artifacts.append(record)
        lowered = rel.lower()
        if any(token in lowered for token in ("lock", "cache", "pid", "status", "queue", "fingerprint")):
            if set(categories) - {"uncategorized"} or "reports/" in lowered or "tools/stage7_rewrite" in lowered:
                lock_cache_candidates.append(record)

    return {
        "items": items[:500],
        "truncated_items": max(0, len(items) - 500),
        "db_artifacts": db_artifacts[:160],
        "truncated_db_artifacts": max(0, len(db_artifacts) - 160),
        "lock_cache_candidates": lock_cache_candidates[:160],
        "truncated_lock_cache_candidates": max(0, len(lock_cache_candidates) - 160),
        "counts": {name: dict(counter.most_common()) for name, counter in counters.items()},
    }


def inspect_package_scripts(root: Path) -> list[dict[str, str]]:
    package_path = root / "package.json"
    if not package_path.exists():
        return []
    payload = json.loads(read_text(package_path))
    scripts = payload.get("scripts") if isinstance(payload, dict) else {}
    if not isinstance(scripts, dict):
        return []
    rows = []
    for name, command in sorted(scripts.items()):
        haystack = f"{name} {command}"
        categories = classify_path(haystack)
        if categories == ["uncategorized"]:
            continue
        rows.append({
            "name": str(name),
            "command": str(command),
            "categories": ",".join(categories),
        })
    return rows


def inspect_weapon_catalog(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "path": path.as_posix()}
    text = read_text(path)
    lines = text.splitlines()
    headings = [line.strip() for line in lines if line.startswith("#")][:80]
    hits = []
    pattern = re.compile(r"cookie|chrome|puppeteer|playwright|scrapling|lightpanda|camofox|maigret|deepseek|hunyuan|mimo|ocr|docker|openclaw|外链|缓存|锁", re.I)
    for line in lines:
        if pattern.search(line):
            hits.append(line.strip())
        if len(hits) >= 80:
            break
    return {
        "exists": True,
        "path": path.as_posix(),
        "line_count": len(lines),
        "headings": headings,
        "hits": hits,
    }


def inspect_arsenal_skill(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "path": path.as_posix()}
    text = read_text(path)
    tool_rows = []
    for line in text.splitlines():
        if line.startswith("|") and "`C:\\code\\githubstar" in line:
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if len(cells) >= 3 and cells[0] != "---":
                tool_rows.append({
                    "need": cells[0],
                    "prefer": cells[1],
                    "local_path": cells[2],
                })
    cookie_extension = "nmckokihipjgplolmcmjakknndddifde" if "nmckokihipjgplolmcmjakknndddifde" in text else ""
    return {
        "exists": True,
        "path": path.as_posix(),
        "tool_rows": tool_rows,
        "cookie_extension_id": cookie_extension,
        "cookie_policy": "manual_user_export_metadata_only" if cookie_extension else "not_found",
    }


def secret_scan_inventory(inventory: dict[str, Any]) -> list[dict[str, str]]:
    text = json.dumps(inventory, ensure_ascii=False)
    findings = []
    for name, pattern in SECRET_PATTERNS:
        for match in pattern.finditer(text):
            findings.append({
                "pattern": name,
                "sample": match.group(0)[:24] + "...",
            })
            if len(findings) >= 10:
                return findings
    return findings


def derive_risks(file_inventory: dict[str, Any], weapon_catalog: dict[str, Any], arsenal_skill: dict[str, Any]) -> list[dict[str, str]]:
    risks = [
        {
            "risk_id": "cookie_credentials_boundary",
            "severity": "high",
            "risk": "Cookie export can unlock authenticated crawls but is credential material.",
            "mitigation": "Accept only explicit user-supplied export files; verify metadata only; never print or commit values.",
        },
        {
            "risk_id": "file_lock_queue_drift",
            "severity": "high",
            "risk": "Long-running crawlers and exporters can collide on queues, status files, and staged artifacts.",
            "mitigation": "Add lock leases, stale-lock recovery, atomic writes, and content-fingerprint caches before real crawl waves.",
        },
        {
            "risk_id": "db_projection_blur",
            "severity": "high",
            "risk": "DB1 source truth, DB2 serving model, and DB3 miniapp projection can be mistaken for one mutable database.",
            "mitigation": "Use sidecars and report-local candidates first; require row-count, leak, search, graph, and field-preservation gates.",
        },
        {
            "risk_id": "rendered_verification_blocked",
            "severity": "medium",
            "risk": "Mini-program UI work cannot be release-claimed while DevTools rendered coverage remains blocked.",
            "mitigation": "Keep UI tests as static/unit/API proof until DevTools environment is clean and rendered coverage passes.",
        },
    ]
    if not weapon_catalog.get("exists"):
        risks.append({
            "risk_id": "weapon_catalog_missing",
            "severity": "medium",
            "risk": "WSL weapon catalog was not readable from this host.",
            "mitigation": "Use Codex local arsenal skill and module index until the WSL path is restored.",
        })
    if not arsenal_skill.get("exists"):
        risks.append({
            "risk_id": "arsenal_skill_missing",
            "severity": "medium",
            "risk": "Codex external-link DB2 arsenal skill is missing.",
            "mitigation": "Recreate or reinstall the local routing skill before selecting platform tools.",
        })
    if file_inventory.get("truncated_items"):
        risks.append({
            "risk_id": "inventory_truncated",
            "severity": "low",
            "risk": "Inventory matched more files than the report embeds.",
            "mitigation": "Use category counts and rerun with narrower follow-up queries for implementation stories.",
        })
    return risks


def build_inventory(root: Path, weapon_catalog_path: Path, arsenal_skill_path: Path) -> dict[str, Any]:
    file_inventory = inspect_files(root)
    package_scripts = inspect_package_scripts(root)
    weapon_catalog = inspect_weapon_catalog(weapon_catalog_path)
    arsenal_skill = inspect_arsenal_skill(arsenal_skill_path)
    inventory: dict[str, Any] = {
        "schema_version": "external_link_db2_inventory.v1",
        "current_story_id": CURRENT_STORY_ID,
        "generated_at": utc_now_iso(),
        "decision": "external_link_db2_inventory_ready_report_only",
        "repo_root": root.as_posix(),
        "boundaries": {
            "report_only": True,
            "external_crawl_started": False,
            "cookie_values_read": False,
            "browser_profile_read": False,
            "env_files_read": False,
            "database_mutation": False,
            "deploy_upload_review": False,
            "d_drive_scan": False,
        },
        "package_scripts": package_scripts,
        "file_inventory": file_inventory,
        "weapon_catalog": weapon_catalog,
        "arsenal_skill": arsenal_skill,
        "recommended_first_canaries": [
            {
                "canary_id": "no_cookie_public_source_action_fixture",
                "purpose": "Exercise source-action URL safety and original-link routing with local fixtures.",
                "network": "none",
            },
            {
                "canary_id": "no_cookie_public_profile_page_fetch",
                "purpose": "Fetch one public artist/venue page with Scrapling or Lightpanda only after S118 lock/cache exists.",
                "network": "public_http_get_later",
            },
            {
                "canary_id": "db2_outlink_sidecar_fixture_projection",
                "purpose": "Project a fixture high-confidence Instagram/mixtape/radio/video link into a report-local sidecar.",
                "network": "none",
            },
        ],
        "next_story": "S118" if package_scripts or file_inventory["items"] else "S117_followup_inventory_scope_fix",
    }
    inventory["risk_register"] = derive_risks(file_inventory, weapon_catalog, arsenal_skill)
    inventory["secret_like_findings"] = secret_scan_inventory(inventory)
    inventory["finding_count"] = len(inventory["secret_like_findings"])
    if inventory["finding_count"]:
        inventory["decision"] = "external_link_db2_inventory_blocked_secret_like_text"
    return inventory


def markdown_table(rows: list[dict[str, Any]], columns: list[str], limit: int = 40) -> list[str]:
    out = ["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    for row in rows[:limit]:
        out.append("| " + " | ".join(str(row.get(column, "")).replace("|", "\\|") for column in columns) + " |")
    if len(rows) > limit:
        omitted = [f"{len(rows) - limit} more rows omitted"] + ["" for _ in columns[1:]]
        out.append("| " + " | ".join(omitted) + " |")
    return out


def render_markdown(report: dict[str, Any]) -> str:
    counts = report["file_inventory"]["counts"]
    lines = [
        "# Weekly External-Link DB2 Inventory S117",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Story: `{report['current_story_id']}`",
        f"- Generated: `{report['generated_at']}`",
        f"- Report-only: `{report['boundaries']['report_only']}`",
        f"- Cookie values read: `{report['boundaries']['cookie_values_read']}`",
        f"- External crawl started: `{report['boundaries']['external_crawl_started']}`",
        f"- DB mutation: `{report['boundaries']['database_mutation']}`",
        f"- Secret-like findings: `{report['finding_count']}`",
        "",
        "## Counts",
        "",
        "### Categories",
        "",
    ]
    for key, value in counts.get("category", {}).items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "### Kinds", ""])
    for key, value in counts.get("kind", {}).items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend([
        "",
        "## Package Scripts",
        "",
        *markdown_table(report["package_scripts"], ["name", "categories", "command"], 35),
        "",
        "## DB Artifacts",
        "",
        *markdown_table(report["file_inventory"]["db_artifacts"], ["path", "categories", "size_bytes"], 35),
        "",
        "## Lock / Cache / Queue Candidates",
        "",
        *markdown_table(report["file_inventory"]["lock_cache_candidates"], ["path", "categories", "kind"], 35),
        "",
        "## Weapon Catalog",
        "",
        f"- Exists: `{report['weapon_catalog'].get('exists')}`",
        f"- Path: `{report['weapon_catalog'].get('path')}`",
        f"- Line count: `{report['weapon_catalog'].get('line_count', '')}`",
        "",
        "## Arsenal Skill",
        "",
        f"- Exists: `{report['arsenal_skill'].get('exists')}`",
        f"- Path: `{report['arsenal_skill'].get('path')}`",
        f"- Cookie policy: `{report['arsenal_skill'].get('cookie_policy', '')}`",
        f"- Cookie extension id known: `{bool(report['arsenal_skill'].get('cookie_extension_id'))}`",
        "",
        "## Risk Register",
        "",
        *markdown_table(report["risk_register"], ["risk_id", "severity", "risk", "mitigation"], 20),
        "",
        "## Recommended First Canaries",
        "",
        *markdown_table(report["recommended_first_canaries"], ["canary_id", "network", "purpose"], 10),
        "",
        "## Next",
        "",
        f"- Next story: `{report['next_story']}`",
        "- S118 should add a fixture-first lock/cache harness before any real external crawl wave.",
        "",
    ])
    return "\n".join(lines)


def write_reports(report: dict[str, Any], out_dir: Path, scorecard: Path) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    scorecard.parent.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "external_link_db2_inventory.json"
    markdown_path = out_dir / "external_link_db2_inventory.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown = render_markdown(report)
    markdown_path.write_text(markdown, encoding="utf-8")
    scorecard.write_text(markdown, encoding="utf-8")
    return {
        "json": rel_path(json_path),
        "markdown": rel_path(markdown_path),
        "scorecard": rel_path(scorecard),
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--weapon-catalog", type=Path, default=DEFAULT_WEAPON_CATALOG)
    parser.add_argument("--arsenal-skill", type=Path, default=DEFAULT_ARSENAL_SKILL)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    report = build_inventory(args.repo_root, args.weapon_catalog, args.arsenal_skill)
    paths = write_reports(report, args.out_dir, args.scorecard)
    print(json.dumps({
        "decision": report["decision"],
        "finding_count": report["finding_count"],
        "package_script_count": len(report["package_scripts"]),
        "inventory_item_count": len(report["file_inventory"]["items"]),
        "db_artifact_count": len(report["file_inventory"]["db_artifacts"]),
        "paths": paths,
    }, ensure_ascii=False, indent=2))
    return 1 if report["finding_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
