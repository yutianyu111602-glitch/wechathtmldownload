#!/usr/bin/env python3
"""Build a read-only Atlas/Weekly route, external-link, and database inventory.

This is a control-plane audit for the longrun consolidation. It does not read
secrets, call models, deploy services, upload mini-program builds, or mutate
databases.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUT_DIR = REPO_ROOT / "tools" / "stage7_rewrite" / "reports" / "atlas_route_external_db_inventory_20260531"

SKIP_DIR_NAMES = {
    ".git",
    ".codegraph",
    ".understand-anything",
    "__pycache__",
    "node_modules",
    "vendor",
    "tmp",
    "artifacts",
    "dist",
}
SECRET_FILE_NAMES = {".env", ".env.local", "cookies.txt"}
DATA_SUFFIXES = {".sqlite", ".db", ".json", ".jsonl", ".gz", ".md"}
ROUTE_RE = re.compile(r"\b(?:app|router)\.(get|post|put|delete|patch|all)\(\s*[\"'`]([^\"'`]+)[\"'`]", re.I)
PATHNAME_EQ_RE = re.compile(r"pathname\s*===\s*[\"'`]([^\"'`]+)[\"'`]")
PATHNAME_STARTS_RE = re.compile(r"pathname\.startsWith\(\s*[\"'`]([^\"'`]+)[\"'`]\s*\)")
PATHNAME_MATCH_RE = re.compile(r"pathname\.match\(\s*/\^(.+?)\$/\s*\)")

FIELD_GROUPS: dict[str, tuple[str, ...]] = {
    "id": ("eventId", "event_id", "id", "sourceRefId", "source_ref", "activity_src"),
    "venue": ("venueName", "venue_name", "venueLabel", "organizerKey", "venue_id", "venueId"),
    "geo": ("geo_lat", "geo_lng", "latitude", "longitude", "gcj", "tencent_location", "map_location"),
    "source": ("sourceHash", "sourceRefId", "source_url_map", "source_refs", "sourceAction", "evidence"),
    "relations": ("collaborators", "sameEventCount", "residentDJs", "dj_venues", "venue_events"),
    "outlinks": ("instagram", "soundcloud", "bandcamp", "mixcloud", "mixtape", "externalUrl", "outlink"),
}

EXTERNAL_LINK_TERMS = (
    "source_url_map",
    "sourceAction",
    "source_refs",
    "externalUrl",
    "instagram",
    "ins",
    "soundcloud",
    "bandcamp",
    "mixcloud",
    "mixtape",
    "spotify",
    "netease",
)


def rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def read_text(path: Path) -> str:
    if path.name in SECRET_FILE_NAMES:
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def safe_exists(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:
        return False


def safe_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def walk_files(root: Path, *, max_files: int = 50000) -> list[Path]:
    files: list[Path] = []
    if not safe_exists(root):
        return files
    for dirpath, dirnames, filenames in os.walk(root, onerror=lambda _error: None):
        dirnames[:] = [name for name in dirnames if name not in SKIP_DIR_NAMES]
        for filename in filenames:
            if filename in SECRET_FILE_NAMES:
                continue
            path = Path(dirpath) / filename
            files.append(path)
            if len(files) >= max_files:
                return files
    return files


def cloudrun_routes(project_root: Path) -> list[dict[str, Any]]:
    src_root = project_root / "services" / "weekly_activity_cloudrun" / "src"
    rows: list[dict[str, Any]] = []
    for path in sorted(src_root.glob("*.mjs")):
        text = read_text(path)
        for match in ROUTE_RE.finditer(text):
            rows.append({"method": match.group(1).upper(), "path": match.group(2), "file": rel(path, project_root)})
        for match in PATHNAME_EQ_RE.finditer(text):
            rows.append({"method": "ANY", "path": match.group(1), "file": rel(path, project_root), "style": "pathname_eq"})
        for match in PATHNAME_STARTS_RE.finditer(text):
            rows.append({"method": "ANY", "path": f"{match.group(1)}*", "file": rel(path, project_root), "style": "pathname_prefix"})
        for match in PATHNAME_MATCH_RE.finditer(text):
            pattern = match.group(1).replace("\\/", "/")
            rows.append({"method": "ANY", "path": f"regex:^{pattern}$", "file": rel(path, project_root), "style": "pathname_regex"})
    deduped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        deduped[(row["method"], row["path"], row["file"])] = row
    return sorted(deduped.values(), key=lambda row: (row["path"], row["method"], row["file"]))


def miniapp_pages(project_root: Path) -> dict[str, Any]:
    app_json = project_root / "apps" / "weekly_activity_miniprogram" / "app.json"
    payload: dict[str, Any] = {}
    if app_json.exists():
        payload = json.loads(app_json.read_text(encoding="utf-8"))
    pages = payload.get("pages") if isinstance(payload.get("pages"), list) else []
    return {
        "app_json": rel(app_json, project_root),
        "page_count": len(pages),
        "pages": [str(page) for page in pages],
    }


def shell_pipeline_entries(project_root: Path) -> list[dict[str, Any]]:
    candidates = [
        project_root / "services" / "weekly_activity_cloudrun" / "scripts" / "bake_and_deploy.py",
        project_root / "services" / "weekly_activity_cloudrun" / "scripts" / "direct_cloudbase_deploy.py",
        project_root / "apps" / "weekly_activity_miniprogram" / "scripts" / "upload_native_windows.ps1",
        project_root / "tools" / "stage7_rewrite" / "weekly_activity_next_week_pipeline.ps1",
        Path(r"\\wsl.localhost\Ubuntu\home\pc\scripts\huaidj-weekly-openclaw-stable.sh"),
        Path(r"\\wsl.localhost\Ubuntu\home\pc\scripts\huaidj-weekly-pipeline.sh"),
    ]
    return [
        {
            "path": rel(path, project_root) if str(path).startswith(str(project_root)) else str(path),
            "exists": safe_exists(path),
            "kind": "deploy_upload" if any(token in path.name for token in ("deploy", "upload")) else "pipeline",
        }
        for path in candidates
    ]


def data_inventory(project_root: Path, *, max_rows: int = 2500) -> dict[str, Any]:
    roots = [
        project_root / "services" / "weekly_activity_cloudrun" / "data",
        project_root / "tools" / "stage7_rewrite" / "registries",
        project_root / "tools" / "stage7_rewrite" / "schemas",
        project_root / "reports",
        project_root / "tools" / "stage7_rewrite" / "reports",
    ]
    rows: list[dict[str, Any]] = []
    counts: dict[str, int] = defaultdict(int)
    truncated = False
    for root in roots:
        for path in walk_files(root, max_files=max_rows):
            suffix = "".join(path.suffixes[-2:]) if path.name.endswith(".json.gz") else path.suffix
            if suffix not in DATA_SUFFIXES and not path.name.endswith(".json.gz"):
                continue
            suffix_key = ".json.gz" if path.name.endswith(".json.gz") else path.suffix.lower()
            counts[suffix_key or "<none>"] += 1
            if len(rows) < max_rows:
                rows.append(
                    {
                        "path": rel(path, project_root),
                        "suffix": suffix_key,
                        "bytes": safe_size(path),
                    }
                )
            else:
                truncated = True
    return {"counts_by_suffix": dict(sorted(counts.items())), "sample_count": len(rows), "truncated": truncated, "samples": rows}


def scan_terms(project_root: Path, terms: tuple[str, ...], roots: list[Path]) -> list[dict[str, Any]]:
    term_re = re.compile("|".join(re.escape(term) for term in terms), re.I)
    hits: list[dict[str, Any]] = []
    for root in roots:
        for path in walk_files(root, max_files=30000):
            if path.suffix.lower() not in {".js", ".mjs", ".cjs", ".py", ".json", ".wxml", ".wxss", ".md", ".ts"}:
                continue
            text = read_text(path)
            found = sorted({match.group(0).lower() for match in term_re.finditer(text)})
            if found:
                hits.append({"path": rel(path, project_root), "terms": found[:20]})
    return sorted(hits, key=lambda row: row["path"])


def field_contract_hits(project_root: Path) -> dict[str, Any]:
    roots = [
        project_root / "apps" / "weekly_activity_miniprogram",
        project_root / "services" / "weekly_activity_cloudrun" / "src",
        project_root / "services" / "weekly_activity_cloudrun" / "tests",
        project_root / "tools" / "stage7_rewrite" / "scripts",
        project_root / "tools" / "stage7_rewrite" / "tests",
    ]
    groups: dict[str, Any] = {}
    for name, terms in FIELD_GROUPS.items():
        hits = scan_terms(project_root, terms, roots)
        groups[name] = {"term_count": len(terms), "file_count": len(hits), "files": hits[:80]}
    return groups


def external_link_inventory(project_root: Path) -> dict[str, Any]:
    roots = [
        project_root / "apps" / "weekly_activity_miniprogram",
        project_root / "services" / "weekly_activity_cloudrun",
        project_root / "tools" / "stage7_rewrite" / "scripts",
        project_root / "docs",
    ]
    hits = scan_terms(project_root, EXTERNAL_LINK_TERMS, roots)
    return {
        "terms": list(EXTERNAL_LINK_TERMS),
        "file_count": len(hits),
        "files": hits[:160],
        "copyright_boundary": {
            "preferred_behavior": "store/link metadata and jump to original platform URLs; do not cache or proxy copyrighted audio.",
            "mixtape_policy": "treat mixtape/audio links as external evidence/outlinks unless an explicit rights-safe source says otherwise.",
        },
    }


def build_report(project_root: Path, out_dir: Path) -> dict[str, Any]:
    project_root = project_root.resolve()
    routes = cloudrun_routes(project_root)
    pages = miniapp_pages(project_root)
    pipeline_entries = shell_pipeline_entries(project_root)
    db = data_inventory(project_root)
    outlinks = external_link_inventory(project_root)
    fields = field_contract_hits(project_root)
    findings: list[dict[str, str]] = []
    if not routes:
        findings.append({"severity": "high", "check": "cloudrun_routes_missing", "message": "No CloudRun routes were detected."})
    if not pages["page_count"]:
        findings.append({"severity": "high", "check": "miniapp_pages_missing", "message": "No mini-program pages were detected."})
    if fields["geo"]["file_count"] and fields["venue"]["file_count"]:
        findings.append(
            {
                "severity": "info",
                "check": "field_unification_required",
                "message": "Venue and geo aliases are spread across multiple frontend/backend/pipeline files; use this inventory before canonical field changes.",
            }
        )
    report = {
        "schema_version": "atlas_route_external_db_inventory.v1",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "project_root": str(project_root),
        "decision": "atlas_route_external_db_inventory_ready" if not any(f["severity"] == "high" for f in findings) else "atlas_route_external_db_inventory_findings",
        "findings": findings,
        "cloudrun_routes": {"count": len(routes), "routes": routes},
        "miniapp_pages": pages,
        "pipeline_entries": pipeline_entries,
        "external_links": outlinks,
        "databases_and_data_packages": db,
        "field_contract_hits": fields,
        "safety": {
            "report_only": True,
            "secret_files_read": False,
            "database_mutations": False,
            "deployment_executed": False,
            "miniapp_upload_executed": False,
            "model_calls_performed": False,
            "d_root_scan_executed": False,
        },
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "atlas_route_external_db_inventory.json", report)
    write_markdown(out_dir / "atlas_route_external_db_inventory.md", report)
    return report


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Atlas Route / External Link / DB Inventory",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Findings: `{len(report['findings'])}`",
        f"- CloudRun routes: `{report['cloudrun_routes']['count']}`",
        f"- Mini-program pages: `{report['miniapp_pages']['page_count']}`",
        f"- External-link files: `{report['external_links']['file_count']}`",
        f"- Data inventory samples: `{report['databases_and_data_packages']['sample_count']}`",
        "",
        "## Pipeline Entries",
    ]
    for row in report["pipeline_entries"]:
        lines.append(f"- `{row['path']}` exists `{row['exists']}` kind `{row['kind']}`")
    lines.extend(["", "## CloudRun Routes"])
    for row in report["cloudrun_routes"]["routes"][:80]:
        lines.append(f"- `{row['method']}` `{row['path']}` in `{row['file']}`")
    lines.extend(["", "## Mini-Program Pages"])
    for page in report["miniapp_pages"]["pages"]:
        lines.append(f"- `{page}`")
    lines.extend(["", "## Field Groups"])
    for name, group in report["field_contract_hits"].items():
        lines.append(f"- `{name}` files `{group['file_count']}` terms `{group['term_count']}`")
    lines.extend(["", "## Data Counts"])
    for suffix, count in report["databases_and_data_packages"]["counts_by_suffix"].items():
        lines.append(f"- `{suffix}`: `{count}`")
    lines.extend(["", "## Copyright Boundary"])
    boundary = report["external_links"]["copyright_boundary"]
    lines.append(f"- Preferred: {boundary['preferred_behavior']}")
    lines.append(f"- Mixtape: {boundary['mixtape_policy']}")
    if report["findings"]:
        lines.extend(["", "## Findings"])
        for finding in report["findings"]:
            lines.append(f"- `{finding['severity']}` `{finding['check']}`: {finding['message']}")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only Atlas/Weekly route, external-link, and database inventory")
    parser.add_argument("--project-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_report(args.project_root, args.out_dir)
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "findings": len(report["findings"]),
                "json": str(args.out_dir / "atlas_route_external_db_inventory.json"),
                "markdown": str(args.out_dir / "atlas_route_external_db_inventory.md"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if not any(finding["severity"] == "high" for finding in report["findings"]) else 2


if __name__ == "__main__":
    raise SystemExit(main())
