#!/usr/bin/env python3
"""Build the S125 report-local DB2 external-link projection smoke.

This creates a local candidate SQLite and fixtures only. It does not mutate DB1,
DB2, DB3, mini-program packages, or production pointers.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
STAGE7_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "db2_candidate_projection_smoke_s125.v1"
DEFAULT_S120_ITEMS = STAGE7_ROOT / "reports" / "miniprogram_external_link_contract_s120_20260601" / "miniprogram_external_link_items.json"
DEFAULT_S121_AUDIT = STAGE7_ROOT / "reports" / "three_db_merge_performance_s121_20260601" / "three_db_merge_performance_audit.json"
DEFAULT_S124_RESULTS = STAGE7_ROOT / "reports" / "external_link_no_cookie_canary_s124_20260601" / "external_link_no_cookie_canary_results.jsonl"
DEFAULT_S125A_CANDIDATES = STAGE7_ROOT / "reports" / "label_dj_bio_recognition_s125a_20260601" / "label_dj_bio_candidates.jsonl"
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "db2_candidate_projection_smoke_s125_20260601"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_DB2_CANDIDATE_PROJECTION_SMOKE_S125_20260601.md"

SECRET_RE = re.compile(
    r"(?i)(sk-[A-Za-z0-9_-]{12,}|token\s*[:=]\s*[^,\s]{8,}|cookie\s*[:=]\s*[^,\s]{8,}|password\s*[:=]\s*[^,\s]{8,}|BEGIN [A-Z ]*PRIVATE KEY)"
)
DIRECT_MEDIA_RE = re.compile(r"\.(mp3|m4a|aac|flac|wav|ogg|mp4|mov|mkv|avi|zip|rar|7z|tar|gz)(\?|#|$)", re.I)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def rel_path(path: Path, root: Path = REPO_ROOT) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return path.as_posix()


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        temp_name = handle.name
    os.replace(temp_name, path)


def atomic_write_json(path: Path, payload: Any) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def atomic_replace_sqlite(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(suffix=".sqlite", dir=path.parent)
    os.close(fd)
    conn = sqlite3.connect(temp_name)
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA user_version=125")
    conn.execute("CREATE TABLE __target_path(path TEXT NOT NULL)")
    conn.execute("INSERT INTO __target_path VALUES (?)", (str(path),))
    return conn


def finish_sqlite(conn: sqlite3.Connection) -> None:
    row = conn.execute("SELECT path FROM __target_path").fetchone()
    target = Path(row[0])
    temp_name = Path(conn.execute("PRAGMA database_list").fetchone()[2])
    conn.execute("DROP TABLE __target_path")
    conn.commit()
    conn.close()
    os.replace(temp_name, target)


def stable_id(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:24]


def compact(value: Any, limit: int = 4000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def iter_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if isinstance(value, dict):
            rows.append(value)
    return rows


def read_json(path: Path) -> Any:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def load_s120_items(path: Path) -> list[dict[str, Any]]:
    payload = read_json(path)
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("items"), list):
        return [row for row in payload["items"] if isinstance(row, dict)]
    return []


def s121_mapping_blocker_present(path: Path) -> bool:
    payload = read_json(path)
    if not isinstance(payload, dict):
        return True
    text = json.dumps(payload, ensure_ascii=False)
    return "s120_external_link_entity_ids_not_db3_dj_ids" in text or "mapping table/gate is needed" in text


def build_s125a_index(path: Path) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for row in iter_jsonl(path):
        name = compact(row.get("entity_name"), 120).casefold()
        if not name:
            continue
        current = index.get(name, {"entity_kinds": set(), "dispositions": set(), "bio_count": 0, "label_org_like_count": 0})
        current["entity_kinds"].add(compact(row.get("entity_kind"), 80))
        current["dispositions"].add(compact(row.get("disposition"), 80))
        current["bio_count"] += 1 if row.get("role_hint") == "bio_claim" else 0
        current["label_org_like_count"] += 1 if row.get("entity_kind") in {"label_org", "collective_crew", "promoter_org"} else 0
        index[name] = current
    return {
        name: {
            "entity_kinds": sorted(value["entity_kinds"]),
            "dispositions": sorted(value["dispositions"]),
            "bio_count": value["bio_count"],
            "label_org_like_count": value["label_org_like_count"],
        }
        for name, value in index.items()
    }


def projection_status(item: dict[str, Any], fetch: dict[str, Any] | None, gate: dict[str, Any] | None, mapping_blocker: bool) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if not compact(item.get("entity_search_id"), 120):
        reasons.append("missing_entity_search_id")
    if DIRECT_MEDIA_RE.search(compact(item.get("url"), 1000)):
        reasons.append("direct_media_url")
    if not fetch:
        reasons.append("pending_s124_fetch")
    elif fetch.get("decision") != "fetch_ok_public_candidate":
        reasons.extend([f"s124:{reason}" for reason in fetch.get("blocked_reasons") or ["needs_review"]])
    if gate and gate.get("label_org_like_count", 0) and "reject_not_dj" in gate.get("dispositions", []):
        reasons.append("s125a_label_or_org_conflict")
    if mapping_blocker:
        reasons.append("s121_entity_id_mapping_gate")
    if reasons:
        return "blocked_before_promotion", reasons
    return "report_local_projected", []


def make_projection_rows(s120_items: list[dict[str, Any]], s124_results: list[dict[str, Any]], s125a_index: dict[str, dict[str, Any]], mapping_blocker: bool) -> list[dict[str, Any]]:
    fetch_by_item = {compact(row.get("item_id"), 120): row for row in s124_results}
    rows: list[dict[str, Any]] = []
    for item in s120_items:
        item_id = compact(item.get("item_id"), 120)
        fetch = fetch_by_item.get(item_id)
        gate = s125a_index.get(compact(item.get("entity_name"), 120).casefold())
        status, block_reasons = projection_status(item, fetch, gate, mapping_blocker)
        rows.append(
            {
                "projection_id": stable_id({"item_id": item_id, "url": item.get("url")}),
                "item_id": item_id,
                "sidecar_id": compact(item.get("sidecar_id"), 120),
                "entity_search_id": compact(item.get("entity_search_id"), 120),
                "entity_name": compact(item.get("entity_name"), 160),
                "entity_type": compact(item.get("entity_type"), 80),
                "platform": compact(item.get("platform"), 80),
                "public_category": compact(item.get("public_category"), 80),
                "display_label": compact(item.get("display_label"), 80),
                "display_group": compact(item.get("display_group"), 80),
                "display_priority": int(item.get("display_priority") or 999),
                "url": compact(item.get("url"), 1200),
                "source_ref": compact(item.get("source_ref"), 160),
                "confidence_score": int(item.get("confidence_score") or 0),
                "confidence_band": compact(item.get("confidence_band"), 80),
                "copyright_safety": compact(item.get("copyright_safety"), 160),
                "s124_fetch_decision": compact(fetch.get("decision") if fetch else "", 120),
                "s124_status": int(fetch.get("status") or 0) if fetch else 0,
                "s125a_gate_json": json.dumps(gate or {}, ensure_ascii=False, sort_keys=True),
                "projection_status": status,
                "block_reasons_json": json.dumps(block_reasons, ensure_ascii=False),
                "report_local_candidate_written": True,
                "db2_projection_allowed": False,
                "db3_identity_write_allowed": False,
                "miniapp_public_display_allowed": False,
            }
        )
    return rows


def write_candidate_sqlite(path: Path, rows: list[dict[str, Any]]) -> None:
    conn = atomic_replace_sqlite(path)
    columns = [
        ("projection_id", "TEXT PRIMARY KEY"),
        ("item_id", "TEXT"),
        ("sidecar_id", "TEXT"),
        ("entity_search_id", "TEXT"),
        ("entity_name", "TEXT"),
        ("entity_type", "TEXT"),
        ("platform", "TEXT"),
        ("public_category", "TEXT"),
        ("display_label", "TEXT"),
        ("display_group", "TEXT"),
        ("display_priority", "INTEGER"),
        ("url", "TEXT"),
        ("source_ref", "TEXT"),
        ("confidence_score", "INTEGER"),
        ("confidence_band", "TEXT"),
        ("copyright_safety", "TEXT"),
        ("s124_fetch_decision", "TEXT"),
        ("s124_status", "INTEGER"),
        ("s125a_gate_json", "TEXT"),
        ("projection_status", "TEXT"),
        ("block_reasons_json", "TEXT"),
        ("report_local_candidate_written", "INTEGER"),
        ("db2_projection_allowed", "INTEGER"),
        ("db3_identity_write_allowed", "INTEGER"),
        ("miniapp_public_display_allowed", "INTEGER"),
    ]
    conn.execute(
        "CREATE TABLE external_link_candidate_projection ("
        + ", ".join(f"{name} {kind}" for name, kind in columns)
        + ")"
    )
    placeholders = ",".join("?" for _ in columns)
    conn.executemany(
        f"INSERT INTO external_link_candidate_projection VALUES ({placeholders})",
        [tuple(row[name] for name, _ in columns) for row in rows],
    )
    conn.execute("CREATE INDEX idx_s125_entity_name ON external_link_candidate_projection(entity_name)")
    conn.execute("CREATE INDEX idx_s125_platform ON external_link_candidate_projection(platform)")
    conn.execute("CREATE INDEX idx_s125_status ON external_link_candidate_projection(projection_status)")
    finish_sqlite(conn)


def smoke_candidate_sqlite(path: Path) -> dict[str, Any]:
    conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    try:
        total = conn.execute("SELECT COUNT(*) FROM external_link_candidate_projection").fetchone()[0]
        by_status = dict(conn.execute("SELECT projection_status, COUNT(*) FROM external_link_candidate_projection GROUP BY projection_status").fetchall())
        search_rows = conn.execute(
            "SELECT entity_name, platform, url FROM external_link_candidate_projection WHERE entity_name LIKE ? ORDER BY display_priority LIMIT 5",
            ("%999999999%",),
        ).fetchall()
        profile_rows = conn.execute(
            "SELECT entity_name, COUNT(*), SUM(CASE WHEN s124_fetch_decision='fetch_ok_public_candidate' THEN 1 ELSE 0 END) "
            "FROM external_link_candidate_projection GROUP BY entity_name ORDER BY COUNT(*) DESC LIMIT 5"
        ).fetchall()
    finally:
        conn.close()
    return {
        "sqlite_opened_read_only": True,
        "total_rows": total,
        "by_projection_status": by_status,
        "search_smoke": {"query": "999999999", "row_count": len(search_rows), "passed": len(search_rows) >= 1},
        "profile_smoke": {"row_count": len(profile_rows), "passed": total > 0, "sample": profile_rows},
    }


def miniapp_fixture(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["s124_fetch_decision"] != "fetch_ok_public_candidate":
            continue
        grouped[row["entity_name"]].append(
            {
                "item_id": row["item_id"],
                "entity_name": row["entity_name"],
                "platform": row["platform"],
                "display_label": row["display_label"],
                "display_group": row["display_group"],
                "url": row["url"],
                "jump_out_original_url": True,
                "media_cached": False,
                "media_downloaded": False,
                "media_proxied": False,
                "miniapp_public_display_allowed": False,
                "projection_status": row["projection_status"],
                "block_reasons": json.loads(row["block_reasons_json"]),
            }
        )
    return {
        "schema_version": f"{SCHEMA_VERSION}.miniapp_fixture",
        "generated_at": now_iso(),
        "public_display_allowed": False,
        "groups": grouped,
    }


def secret_findings(report: dict[str, Any], rows: list[dict[str, Any]], fixture: dict[str, Any]) -> list[dict[str, str]]:
    text = json.dumps({"report": report, "rows": rows, "fixture": fixture}, ensure_ascii=False)
    findings = []
    for match in SECRET_RE.finditer(text):
        findings.append({"pattern": "secret_like_text", "sample": match.group(0)[:16] + "..."})
        if len(findings) >= 10:
            break
    return findings


def scorecard(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Weekly DB2 Candidate Projection Smoke S125",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Input rows: `{summary['input_count']}`",
        f"- Report-local rows: `{summary['report_local_row_count']}`",
        f"- Fetch OK rows: `{summary['fetch_ok_count']}`",
        f"- Blocked before promotion: `{summary['blocked_before_promotion_count']}`",
        f"- Finding count: `{report['finding_count']}`",
        "",
        "## Projection Status",
        "",
    ]
    for key, value in sorted(summary["by_projection_status"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(
        [
            "",
            "## Smoke",
            "",
            f"- Search smoke passed: `{report['smoke']['search_smoke']['passed']}`",
            f"- Profile smoke passed: `{report['smoke']['profile_smoke']['passed']}`",
            "",
            "## Boundaries",
            "",
            "- Report-local SQLite and fixtures only.",
            "- No production DB mutation, no DB2/DB3 projection, no mini-program upload/release, no public display.",
            "- S121 entity-id mapping and S125A label/person/bio gates remain carried as blockers before promotion.",
        ]
    )
    return "\n".join(lines) + "\n"


def build_projection(
    s120_items_path: Path,
    s121_audit_path: Path,
    s124_results_path: Path,
    s125a_candidates_path: Path,
    out_dir: Path,
    scorecard_path: Path,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = make_projection_rows(
        load_s120_items(s120_items_path),
        iter_jsonl(s124_results_path),
        build_s125a_index(s125a_candidates_path),
        s121_mapping_blocker_present(s121_audit_path),
    )
    sqlite_path = out_dir / "external_link_db2_candidate_projection.sqlite"
    write_candidate_sqlite(sqlite_path, rows)
    smoke = smoke_candidate_sqlite(sqlite_path)
    fixture = miniapp_fixture(rows)
    by_status = Counter(row["projection_status"] for row in rows)
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": "db2_candidate_projection_smoke_ready_report_local",
        "inputs": {
            "s120_items": rel_path(s120_items_path),
            "s121_audit": rel_path(s121_audit_path),
            "s124_results": rel_path(s124_results_path),
            "s125a_candidates": rel_path(s125a_candidates_path),
        },
        "outputs": {
            "report": rel_path(out_dir / "db2_candidate_projection_smoke.json"),
            "sqlite": rel_path(sqlite_path),
            "miniapp_fixture": rel_path(out_dir / "miniapp_external_link_fixture.json"),
            "scorecard": rel_path(scorecard_path),
        },
        "summary": {
            "input_count": len(rows),
            "report_local_row_count": len(rows),
            "fetch_ok_count": sum(1 for row in rows if row["s124_fetch_decision"] == "fetch_ok_public_candidate"),
            "blocked_before_promotion_count": sum(1 for row in rows if row["projection_status"] == "blocked_before_promotion"),
            "by_projection_status": dict(by_status),
            "s121_entity_mapping_gate_carried": True,
            "s125a_label_bio_gate_carried": True,
        },
        "smoke": smoke,
        "boundaries": {
            "report_local_sqlite_written": True,
            "production_database_mutation": False,
            "db1_mutation": False,
            "db2_projection_allowed": False,
            "db3_identity_write_allowed": False,
            "miniapp_public_display_allowed": False,
            "miniapp_upload_or_release": False,
            "network_fetch": False,
            "cookie_values_read": False,
            "token_values_read": False,
            "model_call_performed": False,
        },
        "secret_like_findings": [],
        "finding_count": 0,
        "next_story": "S126",
    }
    findings = secret_findings(report, rows, fixture)
    report["secret_like_findings"] = findings
    report["finding_count"] = len(findings)
    if findings or not smoke["search_smoke"]["passed"] or not smoke["profile_smoke"]["passed"]:
        report["decision"] = "db2_candidate_projection_smoke_blocked_report_local"
    atomic_write_json(out_dir / "db2_candidate_projection_smoke.json", report)
    atomic_write_json(out_dir / "miniapp_external_link_fixture.json", fixture)
    atomic_write_json(out_dir / "external_link_db2_candidate_projection_rows.json", rows)
    atomic_write_text(scorecard_path, scorecard(report))
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--s120-items", type=Path, default=DEFAULT_S120_ITEMS)
    parser.add_argument("--s121-audit", type=Path, default=DEFAULT_S121_AUDIT)
    parser.add_argument("--s124-results", type=Path, default=DEFAULT_S124_RESULTS)
    parser.add_argument("--s125a-candidates", type=Path, default=DEFAULT_S125A_CANDIDATES)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_projection(
        args.s120_items,
        args.s121_audit,
        args.s124_results,
        args.s125a_candidates,
        args.out_dir,
        args.scorecard,
    )
    print(json.dumps({"decision": report["decision"], "finding_count": report["finding_count"], "summary": report["summary"]}, ensure_ascii=False))
    return 0 if report["decision"] == "db2_candidate_projection_smoke_ready_report_local" else 1


if __name__ == "__main__":
    raise SystemExit(main())
