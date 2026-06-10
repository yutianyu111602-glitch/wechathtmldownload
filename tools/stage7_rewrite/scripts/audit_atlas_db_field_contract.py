#!/usr/bin/env python3
"""Audit Atlas/Weekly database and canonical field contracts.

Read-only. Opens SQLite databases in read-only mode where possible, inspects
the packaged mini-program GZ index and weekly current release JSON, and writes
a contract report for DB1/DB2/DB3 plus field aliases.
"""
from __future__ import annotations

import argparse
import gzip
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUT_DIR = REPO_ROOT / "tools" / "stage7_rewrite" / "reports" / "atlas_db_field_contract_20260531"

DEFAULT_DB_LAYERS = {
    "DB1_source_raw_atlas": REPO_ROOT
    / "reports"
    / "atlas_incremental_wechat_refresh_20260522_1438"
    / "atlas_local_sqlite_db_139123_activity_candidate_current_20260525_1435"
    / "atlas.sqlite",
    "DB2_serving_read_model": REPO_ROOT
    / "reports"
    / "atlas_serving_time_overlay_span_split_search_date_refresh_candidate_20260527_2018"
    / "atlas_serving.sqlite",
    "DB2_serving_final_family": REPO_ROOT / "reports" / "atlas_serving_final_20260528" / "atlas_serving.sqlite",
    "DB3_miniapp_sqlite": REPO_ROOT / "services" / "weekly_activity_cloudrun" / "data" / "atlas_miniapp.sqlite",
    "UNTRUSTED_inaccessible_serving_copy": REPO_ROOT / "services" / "weekly_activity_cloudrun" / "data" / "atlas_serving.sqlite",
}
DEFAULT_ATLAS_INDEX = REPO_ROOT / "services" / "weekly_activity_cloudrun" / "data" / "atlas_index.json.gz"
DEFAULT_WEEKLY_CURRENT = REPO_ROOT / "services" / "weekly_activity_cloudrun" / "data" / "current_release" / "current.json"

CANONICAL_FIELD_CONTRACT = {
    "ids": {
        "canonical": ["id", "event_id", "dj_id", "venue_id", "source_ref_id"],
        "aliases": ["eventId", "article_id", "queue_id", "sourceRefId", "source_hash", "sourceHash", "eid", "i", "sr"],
        "rule": "Do not use sourceHash as a substitute for sourceRefId when Atlas evidence lookup is required.",
    },
    "venue": {
        "canonical": ["venue_id", "venue_name", "city"],
        "aliases": ["venueName", "venueLabel", "organizerKey", "venue", "v", "vi", "ci"],
        "rule": "City-scoped venue keys must win before plain IDs or names.",
    },
    "geo": {
        "canonical": ["geo_lng", "geo_lat", "geo_coord_system", "geo_source"],
        "aliases": ["venue_lng", "venue_lat", "longitude", "latitude", "gcj02_lng", "gcj02_lat", "map_location", "tencent_location"],
        "rule": "Trusted provider/fixed venue DB coordinates must not be overwritten by empty or fallback coordinates.",
    },
    "source": {
        "canonical": ["source_ref_id", "source_hash", "source_title", "source_account_name", "source_published_at"],
        "aliases": ["sourceRefId", "sourceHash", "source_ref", "activity_src", "atlas_src", "src", "sr"],
        "rule": "Public surfaces expose evidence metadata; raw source URLs remain server-side unless an explicit jump endpoint returns them.",
    },
    "relations": {
        "canonical": ["same_event_count", "event_count", "relation_score", "venue_event_count"],
        "aliases": ["sameEventCount", "relationshipScore", "relationScore", "residentDJs", "dj_venues", "venue_events", "collabs"],
        "rule": "Artist and venue pages must preserve relation arrays even when weekly current items are empty.",
    },
    "external_music_links": {
        "canonical": ["external_links", "music_links", "platform", "url_hash", "source_ref_id", "rights_status"],
        "aliases": ["instagram", "soundcloud", "bandcamp", "mixcloud", "mixtape", "outlink", "externalUrl", "profileUrl"],
        "rule": "Music/mixtape links are original-platform outlinks; do not cache, proxy, or expose downloadable audio.",
    },
}


def rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def sqlite_connect_readonly(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)


def sqlite_table_counts(path: Path, tables: list[str] | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {"path": str(path), "exists": False, "readable": False, "tables": {}, "error": ""}
    try:
        row["exists"] = path.exists()
    except OSError as exc:
        row["error"] = str(exc)
        return row
    if not row["exists"]:
        return row
    try:
        conn = sqlite_connect_readonly(path)
    except Exception as exc:  # noqa: BLE001
        row["error"] = str(exc)
        return row
    try:
        found = [name for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        selected = tables or found
        for table in selected:
            if table not in found:
                continue
            try:
                count = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                cols = [info[1] for info in conn.execute(f'PRAGMA table_info("{table}")').fetchall()]
                row["tables"][table] = {"count": int(count), "columns": cols}
            except sqlite3.Error as exc:
                row["tables"][table] = {"error": str(exc)}
        row["readable"] = True
    finally:
        conn.close()
    return row


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def audit_weekly_current(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "exists": False, "item_count": 0, "coverage": {}, "missing_geo_items": []}
    payload = read_json(path)
    items = payload.get("items") if isinstance(payload, dict) else payload if isinstance(payload, list) else []
    if not isinstance(items, list):
        items = []

    def present(item: dict[str, Any], *keys: str) -> bool:
        for key in keys:
            value = item.get(key)
            if value not in (None, "", [], {}):
                return True
        return False

    coverage = {
        "id": sum(1 for item in items if isinstance(item, dict) and present(item, "id", "event_id")),
        "venue_id_or_name": sum(1 for item in items if isinstance(item, dict) and present(item, "venue_id", "venue_name", "venue")),
        "address": sum(1 for item in items if isinstance(item, dict) and present(item, "address", "address_full", "venue_address")),
        "geo": sum(1 for item in items if isinstance(item, dict) and present(item, "geo_lng", "geo_lat", "venue_lng", "venue_lat")),
        "source_ref_or_hash": sum(1 for item in items if isinstance(item, dict) and present(item, "sourceRefId", "source_ref_id", "sourceHash", "source_hash")),
        "external_music_links": sum(1 for item in items if isinstance(item, dict) and present(item, "external_links", "music_links", "mixtape")),
    }
    missing_geo = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if not present(item, "geo_lng", "geo_lat", "venue_lng", "venue_lat"):
            missing_geo.append(
                {
                    "id": item.get("id") or item.get("event_id") or "",
                    "venue_id": item.get("venue_id") or "",
                    "venue_name": item.get("venue_name") or item.get("venueLabel") or item.get("venue") or "",
                    "city": item.get("city") or item.get("city_name") or "",
                }
            )
    return {
        "path": str(path),
        "exists": True,
        "item_count": len(items),
        "coverage": coverage,
        "missing_geo_items": missing_geo[:50],
    }


def audit_atlas_index(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "exists": False, "keys": [], "counts": {}}
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        return {"path": str(path), "exists": True, "keys": [], "counts": {}}
    keys = sorted(payload.keys())
    counts = {}
    for key in keys:
        value = payload.get(key)
        if isinstance(value, (list, dict)):
            counts[key] = len(value)
    return {"path": str(path), "exists": True, "keys": keys, "counts": counts}


def build_report(
    db_layers: dict[str, Path],
    atlas_index_path: Path,
    weekly_current_path: Path,
    out_dir: Path,
) -> dict[str, Any]:
    db_tables = {
        "DB1_source_raw_atlas": ["articles", "events", "entities", "atlas_activity_events", "atlas_activity_evidence_refs"],
        "DB2_serving_read_model": [
            "performance_event",
            "dj_profile",
            "dj_event",
            "dj_relation_rollup",
            "dj_venue_rollup",
            "evidence_ref",
            "search_document",
        ],
        "DB2_serving_final_family": ["performance_event", "dj_profile", "dj_event", "dj_relation_rollup", "dj_venue_rollup"],
        "DB3_miniapp_sqlite": ["subject", "dj_profile", "dj_event", "dj_collaborator", "dj_venue", "source_ref"],
        "UNTRUSTED_inaccessible_serving_copy": ["performance_event"],
    }
    db_rows = {name: sqlite_table_counts(path, db_tables.get(name)) for name, path in db_layers.items()}
    weekly = audit_weekly_current(weekly_current_path)
    atlas_index = audit_atlas_index(atlas_index_path)
    findings: list[dict[str, str]] = []
    for name in ("DB1_source_raw_atlas", "DB2_serving_read_model", "DB3_miniapp_sqlite"):
        row = db_rows.get(name, {})
        if not row.get("readable"):
            findings.append({"severity": "high", "check": f"{name}_not_readable", "message": row.get("error") or "database not readable"})
    untrusted = db_rows.get("UNTRUSTED_inaccessible_serving_copy", {})
    if untrusted.get("exists") and not untrusted.get("readable"):
        findings.append(
            {
                "severity": "info",
                "check": "untrusted_serving_copy_unreadable",
                "message": "services/weekly_activity_cloudrun/data/atlas_serving.sqlite exists but is not readable; do not use it as current truth.",
            }
        )
    item_count = weekly.get("item_count", 0)
    if item_count:
        geo_count = weekly.get("coverage", {}).get("geo", 0)
        if geo_count < item_count:
            findings.append(
                {
                    "severity": "warning",
                    "check": "weekly_current_geo_gap",
                    "message": f"weekly current geo coverage is {geo_count}/{item_count}; unresolved rows must stay blocked until provider/source verified.",
                }
            )
        music_count = weekly.get("coverage", {}).get("external_music_links", 0)
        if music_count == 0:
            findings.append(
                {
                    "severity": "info",
                    "check": "weekly_music_links_absent",
                    "message": "weekly current package has no stable external/music link field yet; add as rights-safe outlink metadata.",
                }
            )
    decision = "atlas_db_field_contract_ready" if not any(f["severity"] == "high" for f in findings) else "atlas_db_field_contract_findings"
    report = {
        "schema_version": "atlas_db_field_contract.v1",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "decision": decision,
        "findings": findings,
        "canonical_field_contract": CANONICAL_FIELD_CONTRACT,
        "db_layers": {name: {**row, "path": rel(Path(row["path"]), REPO_ROOT)} for name, row in db_rows.items()},
        "weekly_current": {**weekly, "path": rel(Path(weekly["path"]), REPO_ROOT)},
        "atlas_index": {**atlas_index, "path": rel(Path(atlas_index["path"]), REPO_ROOT)},
        "safety": {
            "report_only": True,
            "database_mutations": False,
            "secret_files_read": False,
            "model_calls_performed": False,
            "deployment_executed": False,
        },
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "atlas_db_field_contract.json", report)
    write_markdown(out_dir / "atlas_db_field_contract.md", report)
    return report


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Atlas DB / Field Contract",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Findings: `{len(report['findings'])}`",
        "",
        "## DB Layers",
    ]
    for name, row in report["db_layers"].items():
        lines.append(f"- `{name}` `{row['path']}` readable `{row['readable']}`")
        for table, table_info in row.get("tables", {}).items():
            count = table_info.get("count", "error")
            lines.append(f"  - `{table}` rows `{count}`")
    lines.extend(["", "## Weekly Current Coverage"])
    weekly = report["weekly_current"]
    lines.append(f"- Items: `{weekly.get('item_count', 0)}`")
    for key, value in weekly.get("coverage", {}).items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Atlas Miniapp GZ"])
    for key, value in report["atlas_index"].get("counts", {}).items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Canonical Fields"])
    for name, contract in report["canonical_field_contract"].items():
        lines.append(f"- `{name}` canonical `{', '.join(contract['canonical'])}`")
        lines.append(f"  - aliases `{', '.join(contract['aliases'])}`")
        lines.append(f"  - rule: {contract['rule']}")
    if report["findings"]:
        lines.extend(["", "## Findings"])
        for finding in report["findings"]:
            lines.append(f"- `{finding['severity']}` `{finding['check']}`: {finding['message']}")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit Atlas DB and canonical field contracts")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--atlas-index", type=Path, default=DEFAULT_ATLAS_INDEX)
    parser.add_argument("--weekly-current", type=Path, default=DEFAULT_WEEKLY_CURRENT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_report(DEFAULT_DB_LAYERS, args.atlas_index, args.weekly_current, args.out_dir)
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "findings": len(report["findings"]),
                "json": str(args.out_dir / "atlas_db_field_contract.json"),
                "markdown": str(args.out_dir / "atlas_db_field_contract.md"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if not any(finding["severity"] == "high" for finding in report["findings"]) else 2


if __name__ == "__main__":
    raise SystemExit(main())
