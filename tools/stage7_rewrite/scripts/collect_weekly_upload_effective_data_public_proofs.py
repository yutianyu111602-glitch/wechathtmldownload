#!/usr/bin/env python3
"""Collect bounded public proofs for weekly upload/effective-data state."""
from __future__ import annotations

import argparse
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
REPORTS_ROOT = REPO_ROOT / "tools" / "stage7_rewrite" / "reports"
REPORTS_MD_ROOT = REPO_ROOT / "reports"

SCHEMA_VERSION = "weekly_upload_effective_data_public_proofs.v1"
DECISION_PASS = "weekly_upload_effective_data_public_proofs_collected_partial_public_remote_effective"
DECISION_BLOCKED = "weekly_upload_effective_data_public_proofs_blocked_or_incomplete"

DEFAULT_EXECUTION_GATE = (
    REPORTS_ROOT
    / "weekly_upload_effective_data_proof_execution_gate_20260603"
    / "weekly_upload_effective_data_proof_execution_gate.json"
)
DEFAULT_CURRENT_URL = "https://weekly-api-255880-4-1371956557.sh.run.tcloudbase.com/api/v1/weekly/current?limit=100"
DEFAULT_OUT_DIR = REPORTS_ROOT / "weekly_upload_effective_data_proof_execution_20260603_public"
DEFAULT_SCORECARD = REPORTS_MD_ROOT / "WEEKLY_UPLOAD_EFFECTIVE_DATA_PUBLIC_PROOFS_20260603.md"

EXPECTED_ITEM_COUNT = 78
STALE_DATE = "2026-05-29"
REQUIRED_DATES = ["2026-06-02", "2026-06-03"]
COVER_KEYS = ["coverUrl", "cover_url", "coverImageUrl", "cover_image_url", "posterUrl", "poster_url"]


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def item_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("items", "events"):
        rows = payload.get(key)
        if isinstance(rows, list):
            return [item for item in rows if isinstance(item, dict)]
    data = payload.get("data")
    if isinstance(data, dict):
        return item_rows(data)
    return []


def item_date(item: dict[str, Any]) -> str:
    for key in ("date", "event_date", "eventDate", "event_date_start", "event_date_iso_guess"):
        value = str(item.get(key, "") or "").strip()
        if value:
            return value
    return ""


def item_cover_url(item: dict[str, Any]) -> str:
    for key in COVER_KEYS:
        value = str(item.get(key, "") or "").strip()
        if value:
            return value
    return ""


def fetch_json(url: str, timeout_sec: int) -> tuple[dict[str, Any], dict[str, Any]]:
    request = urllib.request.Request(url, headers={"User-Agent": "weekly-proof-collector/1.0"})
    with urllib.request.urlopen(request, timeout=timeout_sec) as response:
        body = response.read()
        return json.loads(body.decode("utf-8")), {
            "url": url,
            "status": int(response.status),
            "content_type": response.headers.get("Content-Type", ""),
            "bytes": len(body),
        }


def fetch_binary(url: str, timeout_sec: int) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "weekly-proof-collector/1.0"})
    with urllib.request.urlopen(request, timeout=timeout_sec) as response:
        body = response.read(2_000_000)
        return {
            "url": url.split("?", 1)[0] + ("?[redacted_query]" if "?" in url else ""),
            "status": int(response.status),
            "content_type": response.headers.get("Content-Type", ""),
            "bytes_read": len(body),
        }


def analyze_current_payload(payload: dict[str, Any], transport: dict[str, Any]) -> dict[str, Any]:
    rows = item_rows(payload)
    dates = sorted({date for date in (item_date(item) for item in rows) if date})
    cover_count = sum(1 for item in rows if item_cover_url(item))
    total = payload.get("total") or payload.get("count") or len(rows)
    gates = {
        "http_status_200": transport.get("status") == 200,
        "item_count_at_least_78": len(rows) >= EXPECTED_ITEM_COUNT or int(total or 0) >= EXPECTED_ITEM_COUNT,
        "stale_20260529_absent": STALE_DATE not in dates,
        "required_dates_present": all(date in dates for date in REQUIRED_DATES),
        "poster_fields_present": cover_count > 0,
    }
    return {
        "proof_id": "remote_effective:cloudrun_current_endpoint",
        "status": "proven" if all(gates.values()) else "blocked",
        "transport": transport,
        "total": int(total or 0),
        "item_count": len(rows),
        "dates": dates[:16],
        "contains_2026_05_29": STALE_DATE in dates,
        "required_dates_present": [date for date in REQUIRED_DATES if date in dates],
        "poster_cover_field_count": cover_count,
        "source": payload.get("source") or payload.get("dataSource") or "",
        "generatedAt": payload.get("generatedAt") or payload.get("generated_at") or "",
        "gates": gates,
        "sample_poster_url": next((item_cover_url(item) for item in rows if item_cover_url(item)), ""),
    }


def analyze_poster_fetch(poster_fetch: dict[str, Any]) -> dict[str, Any]:
    content_type = str(poster_fetch.get("content_type", "")).lower()
    gates = {
        "http_status_200": poster_fetch.get("status") == 200,
        "image_content_type": content_type.startswith("image/"),
        "nonzero_body": int(poster_fetch.get("bytes_read", 0) or 0) > 0,
    }
    return {
        "proof_id": "remote_effective:poster_image_fetch",
        "status": "proven" if all(gates.values()) else "blocked",
        "transport": poster_fetch,
        "gates": gates,
    }


def build_report(
    *,
    execution_gate: dict[str, Any],
    current_payload: dict[str, Any],
    current_transport: dict[str, Any],
    poster_fetch: dict[str, Any],
) -> dict[str, Any]:
    current_proof = analyze_current_payload(current_payload, current_transport)
    poster_proof = analyze_poster_fetch(poster_fetch)
    proofs = [current_proof, poster_proof]
    proven_count = sum(1 for proof in proofs if proof["status"] == "proven")
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": DECISION_PASS if proven_count == len(proofs) else DECISION_BLOCKED,
        "source_execution_gate_decision": execution_gate.get("decision", ""),
        "source_execution_gate_release_id": execution_gate.get("release_id", ""),
        "proofs": proofs,
        "summary": {
            "public_proof_count": len(proofs),
            "public_proof_proven_count": proven_count,
            "public_proof_blocked_count": len(proofs) - proven_count,
            "cloudrun_current_endpoint_proven": current_proof["status"] == "proven",
            "poster_image_fetch_proven": poster_proof["status"] == "proven",
            "remaining_non_public_or_metadata_proofs": [
                "remote_effective:miniprogram_render_after_storage_clear",
                "remote_effective:cloudbase_database_current",
                "remote_effective:miniprogram_uploaded_version",
            ],
            "miniprogram_upload_allowed_now": False,
            "review_release_allowed_now": False,
            "release_ready": False,
        },
        "boundary": {
            "public_http_get_executed": True,
            "poster_image_fetch_executed": True,
            "devtools_executed": False,
            "cloudbase_sync_executed": False,
            "cloudrun_deployed": False,
            "database_mutations": False,
            "coordinate_writes": False,
            "package_rebuild_executed": False,
            "miniprogram_upload_executed": False,
            "review_submitted": False,
            "public_release_executed": False,
            "credential_or_secret_read": False,
            "browser_cookie_or_profile_read": False,
            "docker_or_worker_started": False,
            "provider_or_model_call": False,
        },
    }


def build_blocked_report(*, execution_gate: dict[str, Any], phase: str, error: Exception) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": DECISION_BLOCKED,
        "source_execution_gate_decision": execution_gate.get("decision", ""),
        "source_execution_gate_release_id": execution_gate.get("release_id", ""),
        "proofs": [
            {
                "proof_id": "remote_effective:cloudrun_current_endpoint",
                "status": "blocked",
                "blocked_phase": phase,
                "error_type": type(error).__name__,
                "error": str(error)[:500],
            },
            {
                "proof_id": "remote_effective:poster_image_fetch",
                "status": "blocked",
                "blocked_phase": "not_attempted_after_upstream_blocker",
                "error_type": "",
                "error": "",
            },
        ],
        "summary": {
            "public_proof_count": 2,
            "public_proof_proven_count": 0,
            "public_proof_blocked_count": 2,
            "cloudrun_current_endpoint_proven": False,
            "poster_image_fetch_proven": False,
            "remaining_non_public_or_metadata_proofs": [
                "remote_effective:miniprogram_render_after_storage_clear",
                "remote_effective:cloudbase_database_current",
                "remote_effective:miniprogram_uploaded_version",
            ],
            "miniprogram_upload_allowed_now": False,
            "review_release_allowed_now": False,
            "release_ready": False,
        },
        "boundary": {
            "public_http_get_executed": False,
            "public_http_get_attempted": phase == "current_endpoint_fetch",
            "poster_image_fetch_executed": False,
            "devtools_executed": False,
            "cloudbase_sync_executed": False,
            "cloudrun_deployed": False,
            "database_mutations": False,
            "coordinate_writes": False,
            "package_rebuild_executed": False,
            "miniprogram_upload_executed": False,
            "review_submitted": False,
            "public_release_executed": False,
            "credential_or_secret_read": False,
            "browser_cookie_or_profile_read": False,
            "docker_or_worker_started": False,
            "provider_or_model_call": False,
        },
    }


def write_scorecard(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    summary = report["summary"]
    lines = [
        "# Weekly Upload/Effective-Data Public Proofs",
        "",
        f"Generated: {report['generated_at']}",
        "",
        f"- decision: `{report['decision']}`",
        f"- public proof proven count: `{summary['public_proof_proven_count']}`",
        f"- public proof blocked count: `{summary['public_proof_blocked_count']}`",
        f"- CloudRun current endpoint proven: `{summary['cloudrun_current_endpoint_proven']}`",
        f"- poster image fetch proven: `{summary['poster_image_fetch_proven']}`",
        f"- mini-program upload allowed now: `{summary['miniprogram_upload_allowed_now']}`",
        f"- review/release allowed now: `{summary['review_release_allowed_now']}`",
        f"- release ready: `{summary['release_ready']}`",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect weekly public upload/effective-data proofs.")
    parser.add_argument("--execution-gate", type=Path, default=DEFAULT_EXECUTION_GATE)
    parser.add_argument("--current-url", default=DEFAULT_CURRENT_URL)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--timeout-sec", type=int, default=20)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    execution_gate = read_json(args.execution_gate)
    try:
        current_payload, current_transport = fetch_json(args.current_url, args.timeout_sec)
        current_proof = analyze_current_payload(current_payload, current_transport)
        if not current_proof["sample_poster_url"]:
            raise RuntimeError("current endpoint did not expose a poster URL to fetch")
        poster_fetch = fetch_binary(current_proof["sample_poster_url"], args.timeout_sec)
        report = build_report(
            execution_gate=execution_gate,
            current_payload=current_payload,
            current_transport=current_transport,
            poster_fetch=poster_fetch,
        )
    except Exception as error:
        report = build_blocked_report(execution_gate=execution_gate, phase="current_endpoint_fetch", error=error)
    output_json = args.out_dir / "weekly_upload_effective_data_public_proofs.json"
    write_json(output_json, report)
    write_scorecard(args.scorecard, report)
    print(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "decision": report["decision"],
                "summary": report["summary"],
                "output_json": str(output_json),
                "scorecard": str(args.scorecard),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
