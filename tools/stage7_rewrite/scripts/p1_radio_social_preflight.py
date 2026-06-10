#!/usr/bin/env python3
"""P1 radio/social preflight.

This script is intentionally report-only. It inventories known C: artifacts from
the old dj-dataset project, checks local Camofox/Maigret services, and writes the
cross-validation gates required before any new radio/social crawl.
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_DJ_ROOT = Path(r"C:\Users\pc\code\dj-dataset")
DEFAULT_OUT_DIR = Path("reports/p1_radio_social_preflight_20260514")

KNOWN_JSON_ARTIFACTS = [
    "raw/baihui_hosts.json",
    "raw/baihui_shows.json",
    "raw/byyb_djs.json",
    "raw/byyb_performances.json",
    "raw/cdcrlive_bilibili_djs.json",
    "raw/byyb_shows_full.jsonl",
    "raw/baihui_shows_full.jsonl",
    "artifacts/stage2v2/hidden_kb_bundle_writeback_report.json",
    "artifacts/stage2v2/cross_match/match_stats.json",
]

KNOWN_DB_TABLES = {
    "output/dj_dataset.db": [
        "entities",
        "source_records",
        "entity_links",
        "social_links",
        "social_links_verified",
        "social_links_review_queue",
    ],
    "output/ig_profile_capture.db": ["profiles", "external_links", "mentions", "follow_actions"],
    "output/linktree_capture.db": ["linktree_sources", "linktree_children"],
}

STAGE7_RADIO_ARTIFACTS = [
    "reports/radio_byyb_test.jsonl",
    "reports/sc_radio_tracks_20260511_124547.jsonl",
]

PLATFORMS = ["instagram", "soundcloud", "bandcamp", "linktree", "bilibili", "youtube", "residentadvisor"]


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def safe_count_json_records(path: Path) -> dict[str, Any]:
    result = {"path": str(path), "exists": path.exists(), "records": 0, "kind": "", "error": ""}
    if not path.exists():
        return result
    try:
        if path.suffix == ".jsonl":
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                result["records"] = sum(1 for line in handle if line.strip())
            result["kind"] = "jsonl"
            return result

        payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        result["kind"] = type(payload).__name__
        if isinstance(payload, list):
            result["records"] = len(payload)
        elif isinstance(payload, dict):
            result["records"] = len(payload)
            for key in ("items", "records", "rows", "data", "results"):
                value = payload.get(key)
                if isinstance(value, list):
                    result["records"] = len(value)
                    result["kind"] = f"dict.{key}"
                    break
    except Exception as exc:  # pragma: no cover - defensive report path
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def table_count(db_path: Path, table: str) -> dict[str, Any]:
    result = {"table": table, "rows": None, "error": ""}
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
            result["rows"] = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def inspect_databases(root: Path) -> list[dict[str, Any]]:
    reports = []
    for rel, tables in KNOWN_DB_TABLES.items():
        db_path = root / rel
        entry = {"path": str(db_path), "exists": db_path.exists(), "tables": []}
        if db_path.exists():
            entry["size_bytes"] = db_path.stat().st_size
            entry["tables"] = [table_count(db_path, table) for table in tables]
        reports.append(entry)
    return reports


def inspect_stage7_radio_artifacts(stage7_root: Path) -> list[dict[str, Any]]:
    reports = []
    for rel in STAGE7_RADIO_ARTIFACTS:
        path = stage7_root / rel
        entry = safe_count_json_records(path)
        entry["quality_flags"] = []
        if path.exists() and path.suffix == ".jsonl":
            page_types = Counter()
            music_links = Counter()
            missing_body = 0
            broken_titles = 0
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    page_types[str(row.get("page_type", ""))] += 1
                    for url in row.get("music_links", []) or []:
                        music_links[url] += 1
                    if not (row.get("body_excerpt") or row.get("body_text")):
                        missing_body += 1
                    title = str(row.get("title", ""))
                    if "Collapse" in title or title.startswith("- button"):
                        broken_titles += 1
            entry["page_types"] = dict(page_types)
            entry["unique_music_links"] = len(music_links)
            entry["top_music_links"] = music_links.most_common(5)
            entry["missing_body_rows"] = missing_body
            entry["broken_title_rows"] = broken_titles
            if entry["records"] and entry["unique_music_links"] <= 3:
                entry["quality_flags"].append("thin_station_level_links")
            if missing_body:
                entry["quality_flags"].append("body_text_not_persisted")
            if broken_titles:
                entry["quality_flags"].append("broken_title_extraction")
        reports.append(entry)
    return reports


def check_http(name: str, url: str, timeout: float = 5.0) -> dict[str, Any]:
    result = {"name": name, "url": url, "ok": False, "status": None, "bytes": 0, "body_preview": "", "error": ""}
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            body = response.read(4096)
            result.update(
                {
                    "ok": 200 <= int(response.status) < 500,
                    "status": int(response.status),
                    "bytes": len(body),
                    "body_preview": body.decode("utf-8", errors="replace")[:500],
                }
            )
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        result["error"] = str(exc)
    return result


def platform_counts_from_csv(path: Path, max_rows: int = 200_000) -> dict[str, Any]:
    result = {"path": str(path), "exists": path.exists(), "rows_sampled": 0, "platform_counts": {}, "error": ""}
    if not path.exists():
        return result
    counts: Counter[str] = Counter()
    try:
        with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
            reader = csv.DictReader(handle)
            for idx, row in enumerate(reader):
                if idx >= max_rows:
                    break
                result["rows_sampled"] += 1
                joined = " ".join(str(value or "").casefold() for value in row.values())
                for platform in PLATFORMS:
                    if platform in joined or ("linktr.ee" in joined and platform == "linktree"):
                        counts[platform] += 1
        result["platform_counts"] = dict(counts)
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def build_preflight(
    dj_root: Path,
    stage7_root: Path,
    camofox_url: str,
    maigret_url: str,
) -> dict[str, Any]:
    json_artifacts = [safe_count_json_records(dj_root / rel) for rel in KNOWN_JSON_ARTIFACTS]
    db_reports = inspect_databases(dj_root)
    export_reports = [
        platform_counts_from_csv(dj_root / "产物" / "dj_data_full_848_20260317_2255.csv"),
        platform_counts_from_csv(dj_root / "产物" / "dj_data_full_export.csv"),
    ]
    stage7_radio = inspect_stage7_radio_artifacts(stage7_root)
    services = [
        check_http("camofox", f"{camofox_url.rstrip('/')}/health"),
        check_http("maigret", maigret_url.rstrip("/")),
    ]

    has_raw_radio = any(item["exists"] and item["records"] for item in json_artifacts[:7])
    has_social_db = any(
        db["exists"] and any(t.get("rows") for t in db.get("tables", []))
        for db in db_reports
        if db["path"].endswith(("ig_profile_capture.db", "linktree_capture.db", "dj_dataset.db"))
    )
    services_ok = {service["name"]: service["ok"] for service in services}

    return {
        "generated_at": now_iso(),
        "dj_root": str(dj_root),
        "stage7_root": str(stage7_root),
        "raw_radio_assets_present": bool(has_raw_radio),
        "social_assets_present": bool(has_social_db),
        "services_ok": services_ok,
        "decision": {
            "p1_import_old_assets": "ready" if has_raw_radio and has_social_db else "blocked_missing_assets",
            "p1_new_crawl": "ready_for_bounded_canary" if services_ok.get("camofox") else "blocked_camofox_down",
            "p1_maigret": "ready_for_latin_username_canary" if services_ok.get("maigret") else "blocked_maigret_down",
            "old_data_truth_status": "evidence_only_requires_cross_validation",
        },
        "json_artifacts": json_artifacts,
        "databases": db_reports,
        "exports": export_reports,
        "stage7_radio_artifacts": stage7_radio,
        "services": services,
        "cross_validation_gates": [
            "old dj-dataset rows must be imported with source/provenance/confidence, not promoted as truth",
            "byyb/baihui/cdcr canary must include title, snapshot_length, date_raw, performers, body_excerpt, music_links",
            "Maigret hits are existence signals only; identity requires Camofox/source validation",
            "Instagram login/cookie deep scraping is not enabled by default",
            "SoundCloud/Bandcamp/Linktree evidence must keep URL role: identity/content/evidence/rejected",
        ],
    }


def write_outputs(report: dict[str, Any], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "p1_radio_social_preflight.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    lines = [
        "# P1 Radio/Social Preflight",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- dj_root: `{report['dj_root']}`",
        f"- raw_radio_assets_present: `{report['raw_radio_assets_present']}`",
        f"- social_assets_present: `{report['social_assets_present']}`",
        f"- decision.p1_import_old_assets: `{report['decision']['p1_import_old_assets']}`",
        f"- decision.p1_new_crawl: `{report['decision']['p1_new_crawl']}`",
        f"- decision.p1_maigret: `{report['decision']['p1_maigret']}`",
        "",
        "## Services",
        "",
    ]
    for service in report["services"]:
        lines.append(
            f"- {service['name']}: ok=`{service['ok']}`, status=`{service['status']}`, url=`{service['url']}`"
        )
    lines.extend(["", "## Known JSON/JSONL Artifacts", ""])
    for artifact in report["json_artifacts"]:
        if artifact["exists"]:
            lines.append(f"- `{artifact['path']}`: records=`{artifact['records']}`, kind=`{artifact['kind']}`")
    lines.extend(["", "## Databases", ""])
    for db in report["databases"]:
        if not db["exists"]:
            lines.append(f"- `{db['path']}`: missing")
            continue
        table_bits = ", ".join(f"{t['table']}={t['rows']}" for t in db["tables"] if t.get("rows") is not None)
        lines.append(f"- `{db['path']}`: {table_bits}")
    lines.extend(["", "## Stage7 Existing Radio Artifact Quality", ""])
    for artifact in report["stage7_radio_artifacts"]:
        lines.append(
            f"- `{artifact['path']}`: exists=`{artifact['exists']}`, rows=`{artifact['records']}`, "
            f"unique_music_links=`{artifact.get('unique_music_links', 0)}`, flags=`{artifact.get('quality_flags', [])}`"
        )
    lines.extend(["", "## Cross-Validation Gates", ""])
    for gate in report["cross_validation_gates"]:
        lines.append(f"- {gate}")
    (out_dir / "p1_radio_social_preflight.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dj-root", default=str(DEFAULT_DJ_ROOT))
    parser.add_argument("--stage7-root", default=".")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--camofox-url", default="http://127.0.0.1:9377")
    parser.add_argument("--maigret-url", default="http://127.0.0.1:5050")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_preflight(
        Path(args.dj_root),
        Path(args.stage7_root),
        args.camofox_url,
        args.maigret_url,
    )
    write_outputs(report, Path(args.out_dir))
    print(json.dumps(report["decision"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
