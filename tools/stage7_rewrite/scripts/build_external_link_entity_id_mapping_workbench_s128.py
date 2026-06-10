#!/usr/bin/env python3
"""Build the S128 external-link entity-id mapping workbench.

Report-only. This script reads S120/S125 candidates plus DB2/DB3 profiles and
emits a bridge candidate from external-link entity ids to DB3 DJ ids. It does
not mutate DB1/DB2/DB3, call models, fetch network pages, launch DevTools, or
authorize mini-program public display.
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
SCHEMA_VERSION = "external_link_entity_id_mapping_s128.v1"
DEFAULT_S120_ITEMS = STAGE7_ROOT / "reports" / "miniprogram_external_link_contract_s120_20260601" / "miniprogram_external_link_items.json"
DEFAULT_S125_ROWS = STAGE7_ROOT / "reports" / "db2_candidate_projection_smoke_s125_20260601" / "external_link_db2_candidate_projection_rows.json"
DEFAULT_S125A_CANDIDATES = STAGE7_ROOT / "reports" / "label_dj_bio_recognition_s125a_20260601" / "label_dj_bio_candidates.jsonl"
DEFAULT_DB2 = REPO_ROOT / "reports" / "atlas_serving_time_overlay_span_split_search_date_refresh_candidate_20260527_2018" / "atlas_serving.sqlite"
DEFAULT_DB3 = REPO_ROOT / "services" / "weekly_activity_cloudrun" / "data" / "atlas_miniapp.sqlite"
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "external_link_entity_id_mapping_s128_20260601"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_EXTERNAL_LINK_ENTITY_ID_MAPPING_S128_20260601.md"

SECRET_RE = re.compile(
    r"(?i)(sk-[A-Za-z0-9_-]{12,}|token\s*[:=]\s*[^,\s]{8,}|cookie\s*[:=]\s*[^,\s]{8,}|password\s*[:=]\s*[^,\s]{8,}|BEGIN [A-Z ]*PRIVATE KEY)"
)


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
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def atomic_write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    atomic_write_text(path, "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows))


def stable_id(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:24]


def compact(value: Any, limit: int = 4000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def normalize_name(value: Any) -> str:
    text = compact(value, 160).casefold()
    text = re.sub(r"\s+", " ", text)
    return text


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


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


def load_rows(path: Path) -> list[dict[str, Any]]:
    payload = load_json(path)
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("items"), list):
        return [row for row in payload["items"] if isinstance(row, dict)]
    return []


def load_s125a_index(path: Path) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for row in iter_jsonl(path):
        name = normalize_name(row.get("entity_name"))
        if not name:
            continue
        current = index.setdefault(name, {"entity_kinds": set(), "dispositions": set(), "bio_count": 0, "label_org_like_count": 0})
        current["entity_kinds"].add(compact(row.get("entity_kind"), 80))
        current["dispositions"].add(compact(row.get("disposition"), 80))
        if row.get("role_hint") == "bio_claim":
            current["bio_count"] += 1
        if row.get("entity_kind") in {"label_org", "collective_crew", "promoter_org"}:
            current["label_org_like_count"] += 1
    return {
        key: {
            "entity_kinds": sorted(value["entity_kinds"]),
            "dispositions": sorted(value["dispositions"]),
            "bio_count": value["bio_count"],
            "label_org_like_count": value["label_org_like_count"],
        }
        for key, value in index.items()
    }


def parse_aliases(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        raw = value
    else:
        try:
            parsed = json.loads(str(value))
            raw = parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            raw = []
    return [compact(item, 120) for item in raw if compact(item, 120)]


def load_profiles(db_path: Path, *, layer: str) -> list[dict[str, Any]]:
    conn = sqlite3.connect(f"file:{db_path.resolve().as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        table_exists = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='dj_profile'").fetchone()
        if not table_exists:
            return []
        rows = []
        for row in conn.execute(
            "SELECT dj_id, display_name, normalized_name, aliases_json, city_primary, event_count FROM dj_profile"
        ):
            aliases = parse_aliases(row["aliases_json"])
            rows.append(
                {
                    "layer": layer,
                    "dj_id": compact(row["dj_id"], 120),
                    "display_name": compact(row["display_name"], 160),
                    "normalized_name": compact(row["normalized_name"], 160),
                    "aliases": aliases,
                    "city_primary": compact(row["city_primary"], 80),
                    "event_count": int(row["event_count"] or 0),
                }
            )
        return rows
    finally:
        conn.close()


def build_profile_index(profiles: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for profile in profiles:
        names = {normalize_name(profile["display_name"]), normalize_name(profile["normalized_name"])}
        names.update(normalize_name(alias) for alias in profile.get("aliases", []))
        for name in sorted(item for item in names if item):
            index[name].append(profile)
    return index


def unique_external_entities(s120_items: list[dict[str, Any]], s125_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in s120_items + s125_rows:
        key = (
            compact(row.get("entity_search_id"), 120),
            compact(row.get("entity_name"), 160),
            compact(row.get("entity_type"), 80),
        )
        current = grouped.setdefault(
            key,
            {
                "entity_search_id": key[0],
                "entity_name": key[1],
                "entity_type": key[2],
                "item_ids": set(),
                "platforms": set(),
                "public_categories": set(),
                "fetch_ok_count": 0,
                "candidate_row_count": 0,
            },
        )
        if row.get("item_id"):
            current["item_ids"].add(compact(row.get("item_id"), 120))
        if row.get("platform"):
            current["platforms"].add(compact(row.get("platform"), 80))
        if row.get("public_category"):
            current["public_categories"].add(compact(row.get("public_category"), 80))
        if row.get("s124_fetch_decision") == "fetch_ok_public_candidate":
            current["fetch_ok_count"] += 1
        current["candidate_row_count"] += 1
    out = []
    for value in grouped.values():
        out.append(
            {
                **{key: value[key] for key in ("entity_search_id", "entity_name", "entity_type")},
                "item_ids": sorted(value["item_ids"]),
                "platforms": sorted(value["platforms"]),
                "public_categories": sorted(value["public_categories"]),
                "fetch_ok_count": value["fetch_ok_count"],
                "candidate_row_count": value["candidate_row_count"],
            }
        )
    return sorted(out, key=lambda row: (row["entity_name"].casefold(), row["entity_search_id"], row["entity_type"]))


def collapse_matches(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for match in matches:
        current = by_id.setdefault(
            match["dj_id"],
            {
                "dj_id": match["dj_id"],
                "display_name": match["display_name"],
                "normalized_name": match["normalized_name"],
                "city_primary": match.get("city_primary", ""),
                "event_count": match.get("event_count", 0),
                "layers": set(),
            },
        )
        current["layers"].add(match["layer"])
        current["event_count"] = max(int(current.get("event_count") or 0), int(match.get("event_count") or 0))
    return [
        {
            **{key: value[key] for key in ("dj_id", "display_name", "normalized_name", "city_primary", "event_count")},
            "layers": sorted(value["layers"]),
        }
        for value in by_id.values()
    ]


def candidate_status(entity: dict[str, Any], matches: list[dict[str, Any]], s125a_gate: dict[str, Any] | None) -> tuple[str, str, int, list[str]]:
    reasons: list[str] = []
    normalized_entity_name = normalize_name(entity["entity_name"])
    dispositions = set(s125a_gate.get("dispositions", [])) if s125a_gate else set()
    entity_kinds = set(s125a_gate.get("entity_kinds", [])) if s125a_gate else set()
    if not entity["entity_search_id"]:
        reasons.append("missing_entity_search_id")
    if entity["entity_type"] and entity["entity_type"] != "person":
        reasons.append(f"external_entity_type_not_person:{entity['entity_type']}")
    if s125a_gate and s125a_gate.get("label_org_like_count", 0):
        reasons.append("s125a_label_or_org_like_gate")
    if re.fullmatch(r"[a-z0-9]{1,2}", normalized_entity_name) and not (
        "accept_candidate" in dispositions and "dj_person" in entity_kinds
    ):
        reasons.append("short_latin_name_requires_source_ref_review")
    if len(matches) == 0:
        reasons.append("no_db3_or_db2_dj_profile_name_match")
    elif len(matches) > 1:
        reasons.append("ambiguous_multiple_dj_profile_matches")
    elif "DB3_miniapp" not in matches[0].get("layers", []):
        reasons.append("db2_only_match_missing_db3_profile")

    if reasons:
        return "blocked_before_mapping_promotion", "blocked", 0, reasons
    return "candidate_ready_report_only", "high", 90, ["normalized_name_or_alias_singleton_match"]


def make_mapping_rows(
    entities: list[dict[str, Any]],
    profile_index: dict[str, list[dict[str, Any]]],
    s125a_index: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for entity in entities:
        lookup = normalize_name(entity["entity_name"])
        matches = collapse_matches(profile_index.get(lookup, []))
        gate = s125a_index.get(lookup)
        status, confidence_band, confidence_score, reasons = candidate_status(entity, matches, gate)
        top = matches[0] if len(matches) == 1 else {}
        rows.append(
            {
                "mapping_id": stable_id(
                    {
                        "entity_search_id": entity["entity_search_id"],
                        "entity_name": entity["entity_name"],
                        "entity_type": entity["entity_type"],
                    }
                ),
                "entity_search_id": entity["entity_search_id"],
                "entity_name": entity["entity_name"],
                "entity_type": entity["entity_type"],
                "normalized_entity_name": lookup,
                "s120_s125_item_count": len(entity["item_ids"]),
                "candidate_row_count": entity["candidate_row_count"],
                "fetch_ok_count": entity["fetch_ok_count"],
                "platforms": entity["platforms"],
                "public_categories": entity["public_categories"],
                "db3_dj_id": top.get("dj_id", "") if "DB3_miniapp" in top.get("layers", []) else "",
                "db2_dj_id": top.get("dj_id", "") if "DB2_serving" in top.get("layers", []) else "",
                "target_display_name": top.get("display_name", ""),
                "target_normalized_name": top.get("normalized_name", ""),
                "target_city_primary": top.get("city_primary", ""),
                "target_event_count": top.get("event_count", 0),
                "candidate_match_count": len(matches),
                "candidate_matches": matches,
                "match_methods": ["normalized_name_or_alias_exact"] if matches else [],
                "s125a_gate": gate or {},
                "mapping_status": status,
                "confidence_band": confidence_band,
                "confidence_score": confidence_score,
                "block_reasons": reasons,
                "report_only": True,
                "db2_projection_allowed": False,
                "db3_identity_write_allowed": False,
                "miniapp_public_display_allowed": False,
            }
        )
    return rows


def secret_findings(payload: Any) -> list[dict[str, str]]:
    text = json.dumps(payload, ensure_ascii=False)
    findings = []
    for match in SECRET_RE.finditer(text):
        findings.append({"pattern": "secret_like_text", "sample": match.group(0)[:16] + "..."})
        if len(findings) >= 10:
            break
    return findings


def render_scorecard(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Weekly External-Link Entity-ID Mapping S128",
        "",
        f"- Decision: `{report['decision']}`",
        f"- External entities: `{summary['external_entity_count']}`",
        f"- Candidate ready: `{summary['candidate_ready_count']}`",
        f"- Blocked: `{summary['blocked_count']}`",
        f"- Direct id matches: `{summary['direct_entity_id_match_count']}`",
        f"- Finding count: `{report['finding_count']}`",
        "",
        "## Status",
        "",
    ]
    for key, value in sorted(summary["by_mapping_status"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- Report-only mapping workbench.",
            "- No DB1/DB2/DB3 mutation, no DB2 projection, no DB3 identity write, no mini-program upload/release/public display.",
            "- Candidate rows must still pass source/ref, label/bio, and rendered mini-program gates before promotion.",
        ]
    )
    return "\n".join(lines) + "\n"


def build_workbench(
    *,
    s120_items_path: Path,
    s125_rows_path: Path,
    s125a_candidates_path: Path,
    db2_path: Path,
    db3_path: Path,
    out_dir: Path,
    scorecard_path: Path,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    s120_items = load_rows(s120_items_path)
    s125_rows = load_rows(s125_rows_path)
    entities = unique_external_entities(s120_items, s125_rows)
    profiles = load_profiles(db3_path, layer="DB3_miniapp") + load_profiles(db2_path, layer="DB2_serving")
    profile_index = build_profile_index(profiles)
    rows = make_mapping_rows(entities, profile_index, load_s125a_index(s125a_candidates_path))
    by_status = Counter(row["mapping_status"] for row in rows)
    direct_matches = sum(1 for row in rows if row["entity_search_id"] and row["entity_search_id"] == row.get("db3_dj_id"))
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": "external_link_entity_id_mapping_ready_report_only",
        "inputs": {
            "s120_items": rel_path(s120_items_path),
            "s125_projection_rows": rel_path(s125_rows_path),
            "s125a_candidates": rel_path(s125a_candidates_path),
            "db2_serving": rel_path(db2_path),
            "db3_miniapp": rel_path(db3_path),
        },
        "outputs": {
            "report": rel_path(out_dir / "external_link_entity_id_mapping_workbench.json"),
            "rows": rel_path(out_dir / "external_link_entity_id_mapping_rows.jsonl"),
            "scorecard": rel_path(scorecard_path),
        },
        "summary": {
            "external_entity_count": len(rows),
            "candidate_ready_count": sum(1 for row in rows if row["mapping_status"] == "candidate_ready_report_only"),
            "blocked_count": sum(1 for row in rows if row["mapping_status"] != "candidate_ready_report_only"),
            "direct_entity_id_match_count": direct_matches,
            "by_mapping_status": dict(by_status),
            "db3_profile_count_loaded": sum(1 for row in profiles if row["layer"] == "DB3_miniapp"),
            "db2_profile_count_loaded": sum(1 for row in profiles if row["layer"] == "DB2_serving"),
        },
        "boundary": {
            "report_only": True,
            "db1_mutation": False,
            "db2_mutation": False,
            "db3_mutation": False,
            "db2_projection_allowed": False,
            "db3_identity_write_allowed": False,
            "miniapp_public_display_allowed": False,
            "miniapp_upload_or_release": False,
            "network_fetch": False,
            "model_call_performed": False,
            "cookie_values_read": False,
            "token_values_read": False,
        },
        "rows": rows,
        "secret_like_findings": [],
        "finding_count": 0,
        "next_story": "S129",
    }
    findings = secret_findings({"report": report, "rows": rows})
    report["secret_like_findings"] = findings
    report["finding_count"] = len(findings)
    if findings:
        report["decision"] = "external_link_entity_id_mapping_blocked_report_only"
    atomic_write_json(out_dir / "external_link_entity_id_mapping_workbench.json", report)
    atomic_write_jsonl(out_dir / "external_link_entity_id_mapping_rows.jsonl", rows)
    atomic_write_text(scorecard_path, render_scorecard(report))
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--s120-items", type=Path, default=DEFAULT_S120_ITEMS)
    parser.add_argument("--s125-rows", type=Path, default=DEFAULT_S125_ROWS)
    parser.add_argument("--s125a-candidates", type=Path, default=DEFAULT_S125A_CANDIDATES)
    parser.add_argument("--db2", type=Path, default=DEFAULT_DB2)
    parser.add_argument("--db3", type=Path, default=DEFAULT_DB3)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_workbench(
        s120_items_path=args.s120_items,
        s125_rows_path=args.s125_rows,
        s125a_candidates_path=args.s125a_candidates,
        db2_path=args.db2,
        db3_path=args.db3,
        out_dir=args.out_dir,
        scorecard_path=args.scorecard,
    )
    print(json.dumps({"decision": report["decision"], "summary": report["summary"]}, ensure_ascii=False))
    return 0 if report["finding_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
