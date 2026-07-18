#!/usr/bin/env python3
"""Reconcile the deployed club-overviews endpoint with the staged candidate.

The CloudRun data store intentionally normalizes this payload before serving it.
This verifier applies the same public normalization to the candidate, then
requires the remote schema, counts, kind summary, and canonical payload digest
to match exactly.  It is read-only apart from its evidence report.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "club_overviews.v1"
REPORT_SCHEMA_VERSION = "cloudrun_club_overviews_reconciliation.v1"
ENDPOINT_PATH = "/api/v1/weekly/club-overviews"
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def string_or_none(value: Any) -> str | None:
    text = str(value if value is not None else "").strip()
    return text or None


def iso_date(value: Any) -> str | None:
    text = str(value or "").strip()
    return text if ISO_DATE_RE.fullmatch(text) else None


def normalize_club_overviews(raw: dict[str, Any] | None) -> dict[str, Any]:
    by_club: dict[str, list[dict[str, Any]]] = {}
    kind_counts: dict[str, int] = {}
    overview_count = 0
    raw_by_club = raw.get("by_club") if isinstance(raw, dict) else {}
    if not isinstance(raw_by_club, dict):
        raw_by_club = {}

    for raw_club, raw_items in raw_by_club.items():
        club = str(raw_club or "").strip()
        if not club or not isinstance(raw_items, list):
            continue
        items: list[dict[str, Any]] = []
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                continue
            item = {
                "record_type": string_or_none(raw_item.get("record_type")) or "club_overview_parent",
                "parent_aggregate": raw_item.get("parent_aggregate") is not False,
                "include_in_activity_feed": raw_item.get("include_in_activity_feed") is True,
                "club": string_or_none(raw_item.get("club")) or club,
                "title": string_or_none(raw_item.get("title")) or "",
                "publish_date": iso_date(raw_item.get("publish_date")),
                "original_url": string_or_none(raw_item.get("original_url")) or "",
                "cover_url": string_or_none(raw_item.get("cover_url")) or "",
                "window_kind": string_or_none(raw_item.get("window_kind")) or "other",
                "window_label": string_or_none(raw_item.get("window_label")) or "",
                "window_start": iso_date(raw_item.get("window_start")),
                "window_end": iso_date(raw_item.get("window_end")),
            }
            if item["original_url"] and item["cover_url"]:
                items.append(item)
        if not items:
            continue
        by_club[club] = items
        overview_count += len(items)
        for item in items:
            kind = str(item["window_kind"])
            kind_counts[kind] = kind_counts.get(kind, 0) + 1

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": string_or_none(raw.get("generated_at")) if isinstance(raw, dict) else None,
        "as_of_date": iso_date(raw.get("as_of_date")) if isinstance(raw, dict) else None,
        "source": string_or_none(raw.get("source")) if isinstance(raw, dict) else None,
        "club_count": len(by_club),
        "overview_count": overview_count,
        "kind_counts": kind_counts,
        "by_club": by_club,
    }


def canonical_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_snapshot(payload: Any, *, source: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError(f"{source} club-overviews payload must be a JSON object")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"{source} club-overviews schema mismatch: expected={SCHEMA_VERSION} "
            f"actual={payload.get('schema_version')!r}"
        )
    if not isinstance(payload.get("by_club"), dict):
        raise ValueError(f"{source} club-overviews by_club must be a JSON object")
    for club, items in payload["by_club"].items():
        if not isinstance(club, str) or not club.strip():
            raise ValueError(f"{source} club-overviews contains an empty/non-string club key")
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise ValueError(f"{source} club-overviews by_club[{club!r}] must be an array of objects")

    normalized = normalize_club_overviews(payload)
    for field in ("club_count", "overview_count", "kind_counts"):
        if field not in payload:
            raise ValueError(f"{source} club-overviews is missing required summary field {field}")
        if payload[field] != normalized[field]:
            raise ValueError(
                f"{source} club-overviews {field} mismatch: declared={payload[field]!r} "
                f"normalized={normalized[field]!r}"
            )
    return {
        "source": source,
        "schema_version": SCHEMA_VERSION,
        "club_count": normalized["club_count"],
        "overview_count": normalized["overview_count"],
        "kind_counts": normalized["kind_counts"],
        "summary_sha256": canonical_sha256(normalized),
        "digest_algorithm": "sha256(canonical_backend_normalized_club_overviews_json)",
    }


def assert_matching_snapshots(candidate: dict[str, Any], remote: dict[str, Any]) -> None:
    for field in ("schema_version", "club_count", "overview_count", "kind_counts"):
        if candidate.get(field) != remote.get(field):
            raise ValueError(
                f"Remote club-overviews {field} differs from candidate: "
                f"candidate={candidate.get(field)!r} remote={remote.get(field)!r}"
            )
    if candidate.get("summary_sha256") != remote.get("summary_sha256"):
        raise ValueError(
            "Remote club-overviews summary digest differs from candidate: "
            f"candidate={candidate.get('summary_sha256')} remote={remote.get('summary_sha256')}"
        )


def load_candidate(candidate_api_dir: Path) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    path = candidate_api_dir / "club_overviews.json"
    if not path.is_file():
        raise ValueError(f"Candidate club_overviews.json not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Candidate club_overviews.json is unreadable: {path}: {exc}") from exc
    snapshot = build_snapshot(payload, source="candidate")
    snapshot["file_sha256"] = sha256_file(path)
    return path, payload, snapshot


def fetch_remote_payload(url: str, *, proxy_url: str, request_timeout_seconds: float) -> tuple[int, str, Any]:
    handlers: list[Any] = []
    if proxy_url:
        handlers.append(urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url}))
    opener = urllib.request.build_opener(*handlers)
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "huaidj-release-guardian/1"})
    with opener.open(request, timeout=request_timeout_seconds) as response:
        status = int(getattr(response, "status", response.getcode()))
        content_type = str(response.headers.get("Content-Type") or "")
        raw = response.read()
    if status != 200:
        raise ValueError(f"Remote club-overviews returned HTTP {status}")
    if "application/json" not in content_type.lower():
        raise ValueError(f"Remote club-overviews content-type is not JSON: {content_type!r}")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Remote club-overviews returned invalid UTF-8 JSON: {exc}") from exc
    return status, content_type, payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def reconcile(
    *,
    base_url: str,
    candidate_api_dir: Path,
    proxy_url: str,
    report_path: Path,
    timeout_seconds: float,
    poll_interval_seconds: float,
    request_timeout_seconds: float,
) -> dict[str, Any]:
    candidate_path, _candidate_payload, candidate_snapshot = load_candidate(candidate_api_dir)
    endpoint = base_url.rstrip("/") + ENDPOINT_PATH
    deadline = time.monotonic() + max(timeout_seconds, 0.0)
    attempt_count = 0
    last_error = ""
    last_remote_snapshot: dict[str, Any] | None = None
    last_http_status: int | None = None
    last_content_type = ""

    while True:
        attempt_count += 1
        try:
            status, content_type, remote_payload = fetch_remote_payload(
                endpoint,
                proxy_url=proxy_url,
                request_timeout_seconds=request_timeout_seconds,
            )
            remote_snapshot = build_snapshot(remote_payload, source="remote")
            last_remote_snapshot = remote_snapshot
            last_http_status = status
            last_content_type = content_type
            assert_matching_snapshots(candidate_snapshot, remote_snapshot)
            report = {
                "schema_version": REPORT_SCHEMA_VERSION,
                "generated_at": now_iso(),
                "ok": True,
                "decision": "cloudrun_club_overviews_reconciled",
                "endpoint": endpoint,
                "candidate_path": str(candidate_path),
                "attempt_count": attempt_count,
                "http_status": status,
                "content_type": content_type,
                "candidate": candidate_snapshot,
                "remote": remote_snapshot,
            }
            write_json(report_path, report)
            return report
        except (OSError, ValueError, urllib.error.URLError) as exc:
            last_error = str(exc)
        if time.monotonic() >= deadline:
            report = {
                "schema_version": REPORT_SCHEMA_VERSION,
                "generated_at": now_iso(),
                "ok": False,
                "decision": "cloudrun_club_overviews_reconciliation_blocked",
                "endpoint": endpoint,
                "candidate_path": str(candidate_path),
                "attempt_count": attempt_count,
                "http_status": last_http_status,
                "content_type": last_content_type,
                "candidate": candidate_snapshot,
                "remote": last_remote_snapshot,
                "failure_reason": last_error,
            }
            write_json(report_path, report)
            raise ValueError(last_error)
        time.sleep(max(poll_interval_seconds, 0.1))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--candidate-api-dir", type=Path, required=True)
    parser.add_argument("--proxy-url", default="")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--poll-interval-seconds", type=float, default=5.0)
    parser.add_argument("--request-timeout-seconds", type=float, default=30.0)
    args = parser.parse_args(argv)
    try:
        report = reconcile(
            base_url=args.base_url,
            candidate_api_dir=args.candidate_api_dir.expanduser().resolve(),
            proxy_url=args.proxy_url.strip(),
            report_path=args.report.expanduser().resolve(),
            timeout_seconds=args.timeout_seconds,
            poll_interval_seconds=args.poll_interval_seconds,
            request_timeout_seconds=args.request_timeout_seconds,
        )
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
