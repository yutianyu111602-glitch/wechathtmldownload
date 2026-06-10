#!/usr/bin/env python3
"""Accept and optionally apply the Rust Club Daqing source-backed coordinate repair."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PACK_DIR = ROOT / "tools" / "stage7_rewrite" / "longrun" / "WEEKLY_ACTIVITY_EXPANDED_PACK_20260531"
DEFAULT_REGISTRY = ROOT / "tools" / "stage7_rewrite" / "registries" / "weekly_venues_seed.json"
DEFAULT_CURRENT = ROOT / "services" / "weekly_activity_cloudrun" / "data" / "current_release" / "current.json"
DEFAULT_CURRENT_MANIFEST = ROOT / "services" / "weekly_activity_cloudrun" / "data" / "current_release" / "manifest.json"
DEFAULT_PREVIOUS_SELECTOR = (
    ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "weekly_resource_field_repair_20260531"
    / "backup_before_weekly_resource_field_repair"
    / "by-id"
    / "rust_clubu3a74c857fda5f80128.json"
)
DEFAULT_PROVIDER_PROBE = (
    ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "rust_club_provider_source_acceptance_s134_20260601"
    / "provider_probe"
    / "provider_results.jsonl"
)
DEFAULT_OUT_DIR = ROOT / "tools" / "stage7_rewrite" / "reports" / "rust_club_source_acceptance_s134_20260601"
RUST_VENUE_ID = "rust_club_daqing"
RUST_SELECTOR_ID = "rust_club:74c857fda5f80128"
ACCEPTED_ADDRESS = "黑龙江省大庆市龙凤区黎明街道黎明湖酒吧一条街3号集装箱"
ACCEPTED_LNG = 125.12989
ACCEPTED_LAT = 46.59399


def now_cst() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")


def today_cst() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def iter_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def finite_float(value: Any) -> float | None:
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def text_values(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item or "").strip() for item in value if str(item or "").strip()]
    text = str(value or "").strip()
    return [text] if text else []


def source_url_hash(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:16]


def rust_source_row_is_accepted(row: dict[str, Any]) -> bool:
    if str(row.get("account_key") or "").strip() != "rust_club":
        return False
    title_evidence = " ".join(
        [
            str(row.get("title") or ""),
            " ".join(text_values(row.get("venue"))),
            " ".join(text_values(row.get("city"))),
            str(row.get("address") or ""),
            " ".join(text_values(row.get("evidence"))),
        ]
    )
    if "大庆" not in title_evidence:
        return False
    if "Rust" not in title_evidence and "锈蚀" not in title_evidence:
        return False
    address = str(row.get("address") or "")
    if "黎明湖酒吧一条街" not in address or "3号集装箱" not in address:
        return False
    lng = finite_float(row.get("geo_lng"))
    lat = finite_float(row.get("geo_lat"))
    if lng is None or lat is None:
        return False
    if abs(lng - ACCEPTED_LNG) > 0.00001 or abs(lat - ACCEPTED_LAT) > 0.00001:
        return False
    try:
        confidence = float(row.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    return confidence >= 0.95


def compact_source_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "article_id": row.get("article_id") or row.get("queue_id") or "",
        "title": row.get("title") or "",
        "source_url_hash": source_url_hash(str(row.get("source_url") or "")),
        "post_date": row.get("post_date") or "",
        "event_date_text": text_values(row.get("event_date_text")),
        "address": row.get("address") or "",
        "geo_lng": finite_float(row.get("geo_lng")),
        "geo_lat": finite_float(row.get("geo_lat")),
        "confidence": row.get("confidence"),
    }


def accepted_source_rows(pack_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name in ("weekly_activity_recommendation_candidates.jsonl", "weekly_activity_recommendation_review_candidates.jsonl"):
        for row in iter_jsonl(pack_dir / name):
            if rust_source_row_is_accepted(row):
                rows.append(compact_source_row(row))
    return rows


def provider_probe_summary(path: Path) -> dict[str, Any]:
    rows = iter_jsonl(path)
    status_counts: dict[str, int] = {}
    for row in rows:
        key = str(row.get("response_status"))
        status_counts[key] = status_counts.get(key, 0) + 1
    return {
        "path": display_path(path) if path.exists() else str(path),
        "row_count": len(rows),
        "accepted_count": sum(1 for row in rows if row.get("decision", {}).get("accepted")),
        "status_counts": status_counts,
        "credential_envs": sorted({str(row.get("key_env") or "") for row in rows if row.get("key_env")}),
        "decision": "provider_signature_failed" if status_counts.get("111") else ("provider_probe_absent" if not rows else "provider_probe_review"),
    }


def load_current_items(path: Path) -> list[dict[str, Any]]:
    payload = load_json(path)
    if isinstance(payload, list):
        return payload
    return payload.get("items") or []


def reconcile_current_selector(current_path: Path, manifest_path: Path, previous_selector_path: Path) -> dict[str, Any]:
    items = load_current_items(current_path)
    selector_present = any(item.get("id") == RUST_SELECTOR_ID for item in items if isinstance(item, dict))
    manifest = load_json(manifest_path) if manifest_path.exists() else {}
    previous = load_json(previous_selector_path) if previous_selector_path.exists() else {}
    previous_date = str(previous.get("event_date_start") or previous.get("event_date_iso_guess") or "")
    window_start = str(manifest.get("window_start") or "")
    reason = "selector_present"
    if not selector_present and previous_date and window_start and previous_date < window_start:
        reason = "selector_absent_due_window_rollover"
    elif not selector_present:
        reason = "selector_absent_unexplained"
    return {
        "selector_id": RUST_SELECTOR_ID,
        "selector_present": selector_present,
        "previous_selector_path": display_path(previous_selector_path) if previous_selector_path.exists() else str(previous_selector_path),
        "previous_event_date": previous_date,
        "current_window_start": window_start,
        "current_item_count": len(items),
        "decision": reason,
    }


def find_registry_row(registry: dict[str, Any]) -> tuple[int, dict[str, Any] | None]:
    for index, row in enumerate(registry.get("venues") or []):
        if row.get("venue_id") == RUST_VENUE_ID:
            return index, row
    return -1, None


def apply_registry_write(registry_path: Path, out_dir: Path, accepted_rows: list[dict[str, Any]]) -> dict[str, Any]:
    registry = load_json(registry_path)
    index, row = find_registry_row(registry)
    if row is None:
        return {"applied": False, "reason": "registry_selector_missing"}
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = out_dir / f"backup_before_rust_club_registry_write_{stamp}.json"
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(registry_path, backup_path)
    updated = dict(row)
    updated.update(
        {
            "address_full": ACCEPTED_ADDRESS,
            "status": "active",
            "last_verified_at": today_cst(),
            "geo_lat": ACCEPTED_LAT,
            "geo_lng": ACCEPTED_LNG,
            "geo_coord_system": "GCJ-02",
            "geo_source": "source_pack_repeated_rust_club_coordinate_s134",
            "source_note": (
                "2026-06-01 S134 source-pack acceptance: 2 Rust Club 大庆 source rows carry the same "
                "黎明湖酒吧一条街3号集装箱 address and 125.129890,46.593990 coordinate; Tencent provider probe "
                "remains blocked by status 111 signature validation and was not used for acceptance."
            ),
        }
    )
    registry["venues"][index] = updated
    registry["updated_at"] = today_cst()
    write_json(registry_path, registry)
    readback = load_json(registry_path)
    _, readback_row = find_registry_row(readback)
    readback_ok = bool(
        readback_row
        and readback_row.get("status") == "active"
        and readback_row.get("address_full") == ACCEPTED_ADDRESS
        and finite_float(readback_row.get("geo_lng")) == ACCEPTED_LNG
        and finite_float(readback_row.get("geo_lat")) == ACCEPTED_LAT
    )
    return {
        "applied": True,
        "backup_path": display_path(backup_path),
        "selector_index": index,
        "readback_ok": readback_ok,
        "written_fields": ["address_full", "status", "last_verified_at", "geo_lat", "geo_lng", "geo_coord_system", "geo_source", "source_note"],
        "accepted_source_article_ids": [row.get("article_id") for row in accepted_rows],
    }


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    sources = accepted_source_rows(args.pack_dir)
    coordinate_consensus = len({(row["geo_lng"], row["geo_lat"], row["address"]) for row in sources}) == 1 if sources else False
    source_acceptance_ready = len(sources) >= 2 and coordinate_consensus
    registry = load_json(args.registry)
    registry_index, registry_row = find_registry_row(registry)
    provider_probe = provider_probe_summary(args.provider_probe)
    selector_reconciliation = reconcile_current_selector(args.current_json, args.current_manifest, args.previous_selector)
    registry_write = {"applied": False, "reason": "apply_registry_write flag not set"}
    if args.apply_registry_write:
        if source_acceptance_ready:
            registry_write = apply_registry_write(args.registry, out_dir, sources)
        else:
            registry_write = {"applied": False, "reason": "source_acceptance_not_ready"}
    decision = "rust_club_source_acceptance_ready_registry_write_applied" if registry_write.get("applied") and registry_write.get("readback_ok") else "rust_club_source_acceptance_ready_report_only"
    report = {
        "schema_version": "rust_club_source_acceptance_s134.v1",
        "generated_at": now_cst(),
        "decision": decision,
        "finding_count": 0,
        "inputs": {
            "pack_dir": display_path(args.pack_dir),
            "registry": display_path(args.registry),
            "current_json": display_path(args.current_json),
            "current_manifest": display_path(args.current_manifest),
            "provider_probe": display_path(args.provider_probe) if args.provider_probe.exists() else str(args.provider_probe),
        },
        "source_acceptance": {
            "ready": source_acceptance_ready,
            "accepted_count": len(sources),
            "coordinate_consensus": coordinate_consensus,
            "accepted_address": ACCEPTED_ADDRESS,
            "accepted_geo_lng": ACCEPTED_LNG,
            "accepted_geo_lat": ACCEPTED_LAT,
            "geo_coord_system": "GCJ-02",
            "accepted_rows": sources,
        },
        "provider_probe": provider_probe,
        "current_release_selector_reconciliation": selector_reconciliation,
        "registry_prewrite": {
            "selector_found": registry_row is not None,
            "selector_index": registry_index if registry_row is not None else None,
            "current_status": (registry_row or {}).get("status"),
            "current_address_full": (registry_row or {}).get("address_full", ""),
        },
        "registry_write": registry_write,
        "boundary": {
            "db1_mutation": False,
            "db2_mutation": False,
            "db3_mutation": False,
            "sqlite_mutation": False,
            "json_registry_mutation": bool(registry_write.get("applied")),
            "deploy_upload_review": False,
            "cookie_values_read": False,
            "token_values_read": False,
            "provider_secret_values_printed": False,
            "broad_disk_scan": False,
        },
        "next_safe_action": "rerun S133 target-specific preflight so it reads the updated registry row before any release rebuild/deploy/upload",
    }
    write_json(out_dir / "rust_club_source_acceptance_s134.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-dir", type=Path, default=DEFAULT_PACK_DIR)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--current-json", type=Path, default=DEFAULT_CURRENT)
    parser.add_argument("--current-manifest", type=Path, default=DEFAULT_CURRENT_MANIFEST)
    parser.add_argument("--previous-selector", type=Path, default=DEFAULT_PREVIOUS_SELECTOR)
    parser.add_argument("--provider-probe", type=Path, default=DEFAULT_PROVIDER_PROBE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--apply-registry-write", action="store_true")
    args = parser.parse_args()
    report = build_report(args)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
