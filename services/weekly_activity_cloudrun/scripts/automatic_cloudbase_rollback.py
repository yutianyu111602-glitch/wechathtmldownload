#!/usr/bin/env python3
"""Fail-closed automatic rollback for one transaction-bound CloudRun publish.

The caller must already hold the service-scoped publish lease.  This helper
will only roll back when the live 100%-traffic version is the exact candidate
captured by the named deploy report.  A third-party, unknown, or split-traffic
identity is never mutated.  Success also requires the restored service to
match the unchanged authoritative local release across health, generation,
the complete paginated item-ID set, and club-overviews.

Provider exception text, lease tokens, credentials, and response payloads are
never persisted or printed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = Path(__file__).resolve().parents[3]
TOOLS_SCRIPT_DIR = REPO_ROOT / "tools" / "stage7_rewrite" / "scripts"
for import_dir in (SCRIPT_DIR, TOOLS_SCRIPT_DIR):
    if str(import_dir) not in sys.path:
        sys.path.insert(0, str(import_dir))

from bake_and_deploy import validate_held_service_publish_lease  # noqa: E402
from direct_cloudbase_deploy import (  # noqa: E402
    ENV_ID,
    SERVICE_NAME,
    describe_cloudrun_server_identity,
    poll_task,
    safe_remote_identifier,
    tcb_api,
)
from verify_weekly_club_overviews_remote import (  # noqa: E402
    assert_matching_snapshots,
    build_snapshot as build_club_overviews_snapshot,
)


REPORT_SCHEMA_VERSION = "cloudrun_automatic_rollback.v1"
TRANSACTION_SCHEMA_VERSION = "weekly_cloudrun_publish_transaction.v1"
DEPLOY_SCHEMA_VERSION = "cloudrun_direct_api_deploy.v2"
ALLOWED_TRANSACTION_STATUSES = {
    "prepared",
    "promotion_blocked",
    "promotion_failed_restored",
}
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
HTTPS_BASE_RE = re.compile(
    r"^https://[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?(?::\d{1,5})?$"
)


class SafeRollbackError(RuntimeError):
    """A fixed, secret-safe failure code suitable for persistent evidence."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def write_json_durable(path: Path, payload: dict[str, Any]) -> None:
    """Atomically journal a report and flush its bytes before remote mutation."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def read_object(path: Path, failure_code: str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SafeRollbackError(failure_code) from exc
    if not isinstance(value, dict):
        raise SafeRollbackError(failure_code)
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def directory_snapshot(path: Path) -> dict[str, Any]:
    """Match bake_and_deploy.directory_snapshot without importing mutable globals."""

    path = Path(path)
    files: list[dict[str, Any]] = []
    if path.exists():
        for item in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
            files.append(
                {
                    "path": item.relative_to(path).as_posix(),
                    "size": item.stat().st_size,
                    "sha256": sha256_file(item),
                }
            )
    encoded = json.dumps(files, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return {
        "exists": path.exists(),
        "fingerprint": hashlib.sha256(encoded).hexdigest(),
        "file_count": len(files),
        "total_bytes": sum(int(item["size"]) for item in files),
        "files": files,
    }


def item_id_snapshot(release_dir: Path) -> dict[str, Any]:
    current = read_object(Path(release_dir) / "current.json", "authoritative_current_invalid")
    items = current.get("items")
    if not isinstance(items, list) or not items:
        raise SafeRollbackError("authoritative_current_items_missing")
    ids = [
        str(item.get("id") or "").strip()
        for item in items
        if isinstance(item, dict)
    ]
    if len(ids) != len(items) or any(not item_id for item_id in ids):
        raise SafeRollbackError("authoritative_current_item_ids_incomplete")
    unique_ids = sorted(set(ids))
    if len(unique_ids) != len(ids):
        raise SafeRollbackError("authoritative_current_item_ids_duplicated")
    digest = hashlib.sha256("\n".join(unique_ids).encode("utf-8")).hexdigest()
    return {
        "item_count": len(items),
        "unique_item_id_count": len(unique_ids),
        "item_id_digest": digest,
        "item_ids": unique_ids,
        "digest_algorithm": "sha256(sorted_unique_item_ids_utf8_lf)",
    }


def safe_lease_evidence(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value.get(key)
        for key in (
            "schema_version",
            "lease_token_sha256",
            "transaction_id",
            "env_id",
            "service_name",
            "owner_pid",
        )
        if key in value
    }


def int_100(value: Any) -> bool:
    try:
        return int(value) == 100
    except (TypeError, ValueError):
        return False


def validated_version(identity: dict[str, Any], code_prefix: str) -> str:
    version = safe_remote_identifier(identity.get("active_version"))
    if not version:
        raise SafeRollbackError(f"{code_prefix}_version_missing")
    if not int_100(identity.get("active_flow_ratio")):
        raise SafeRollbackError(f"{code_prefix}_traffic_not_100")
    return version


def validate_base_url(value: Any, code: str) -> str:
    base_url = str(value or "").rstrip("/")
    if not HTTPS_BASE_RE.fullmatch(base_url):
        raise SafeRollbackError(code)
    return base_url


def validate_lease(args: argparse.Namespace, expected_hash: str) -> dict[str, Any]:
    try:
        evidence = validate_held_service_publish_lease(
            lease_path=args.publish_lease_path,
            lease_token=args.publish_lease_token,
            transaction_id=args.transaction_id,
            env_id=args.env_id,
            service_name=args.service_name,
            data_root=args.data_root,
        )
    except Exception as exc:  # noqa: BLE001 - never persist lease/provider exception text
        raise SafeRollbackError("service_publish_lease_not_held") from exc
    lease_hash = str(evidence.get("lease_token_sha256") or "").lower()
    if not HEX64_RE.fullmatch(lease_hash) or lease_hash != expected_hash:
        raise SafeRollbackError("service_publish_lease_binding_mismatch")
    return evidence


def bind_evidence(args: argparse.Namespace) -> dict[str, Any]:
    if not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", str(args.transaction_id or "")
    ):
        raise SafeRollbackError("transaction_id_invalid")
    if not safe_remote_identifier(args.env_id) or not safe_remote_identifier(
        args.service_name
    ):
        raise SafeRollbackError("rollback_target_identifier_invalid")
    deploy = read_object(args.deploy_report, "deploy_report_missing_or_invalid")
    transaction = read_object(
        args.transaction_report, "publish_transaction_report_missing_or_invalid"
    )
    if deploy.get("schema_version") != DEPLOY_SCHEMA_VERSION:
        raise SafeRollbackError("deploy_report_schema_mismatch")
    if transaction.get("schema_version") != TRANSACTION_SCHEMA_VERSION:
        raise SafeRollbackError("publish_transaction_schema_mismatch")
    if transaction.get("status") not in ALLOWED_TRANSACTION_STATUSES:
        raise SafeRollbackError("publish_transaction_status_not_rollback_safe")

    binding = deploy.get("evidence_binding")
    if not isinstance(binding, dict):
        raise SafeRollbackError("deploy_evidence_binding_missing")
    exact_bindings = {
        "transaction_id": args.transaction_id,
        "env_id": args.env_id,
        "service_name": args.service_name,
    }
    for field, expected in exact_bindings.items():
        if str(binding.get(field) or "") != str(expected):
            raise SafeRollbackError(f"deploy_{field}_binding_mismatch")
    if str(transaction.get("transaction_id") or "") != str(args.transaction_id):
        raise SafeRollbackError("publish_transaction_id_binding_mismatch")
    if str(deploy.get("env_id") or "") != str(args.env_id):
        raise SafeRollbackError("deploy_env_id_mismatch")
    if str(deploy.get("service_name") or "") != str(args.service_name):
        raise SafeRollbackError("deploy_service_name_mismatch")

    context_fingerprint = str(binding.get("deploy_context_fingerprint") or "").lower()
    transaction_context = transaction.get("deploy_context")
    transaction_fingerprint = str(
        transaction_context.get("fingerprint")
        if isinstance(transaction_context, dict)
        else ""
    ).lower()
    if (
        not HEX64_RE.fullmatch(context_fingerprint)
        or context_fingerprint != transaction_fingerprint
    ):
        raise SafeRollbackError("deploy_context_transaction_binding_mismatch")
    expected_generation = str(binding.get("expected_generation_id") or "")
    if expected_generation != str(transaction.get("candidate_generation_id") or ""):
        raise SafeRollbackError("candidate_generation_transaction_binding_mismatch")
    lease_hash = str(binding.get("publish_lease_token_sha256") or "").lower()
    if not HEX64_RE.fullmatch(lease_hash):
        raise SafeRollbackError("deploy_publish_lease_binding_invalid")

    mutation = deploy.get("remote_mutation")
    if not isinstance(mutation, dict) or mutation.get("update_attempted") is not True:
        raise SafeRollbackError("deploy_remote_mutation_not_journaled")
    if not bool((deploy.get("safety") or {}).get("cloud_deploy_executed")):
        raise SafeRollbackError("deploy_remote_mutation_not_executed")

    previous_identity = deploy.get("previous_server_identity")
    candidate_identity = deploy.get("post_update_server_identity")
    deployment_identity = deploy.get("deployment_identity")
    if not isinstance(previous_identity, dict) or not isinstance(candidate_identity, dict):
        raise SafeRollbackError("deploy_version_identity_missing")
    if not isinstance(deployment_identity, dict):
        raise SafeRollbackError("deploy_candidate_identity_missing")
    previous_version = validated_version(previous_identity, "previous_active")
    candidate_version = validated_version(candidate_identity, "candidate_active")
    observed = safe_remote_identifier(deployment_identity.get("observed_active_version"))
    reported = safe_remote_identifier(deployment_identity.get("reported_version"))
    if not observed or observed != candidate_version:
        raise SafeRollbackError("candidate_observed_version_binding_mismatch")
    if reported and reported != candidate_version:
        raise SafeRollbackError("candidate_reported_version_binding_mismatch")
    if previous_version == candidate_version:
        raise SafeRollbackError("previous_and_candidate_versions_are_equal")
    previous_base_url = validate_base_url(
        previous_identity.get("base_url"), "previous_base_url_invalid"
    )
    candidate_base_url = validate_base_url(
        candidate_identity.get("base_url"), "candidate_base_url_invalid"
    )
    if previous_base_url != candidate_base_url:
        raise SafeRollbackError("deploy_base_url_identity_mismatch")

    baseline = transaction.get("baseline")
    baseline_current = baseline.get("current_release") if isinstance(baseline, dict) else None
    if not isinstance(baseline_current, dict):
        raise SafeRollbackError("publish_transaction_baseline_missing")
    live_snapshot = directory_snapshot(args.authoritative_release_dir)
    if not live_snapshot.get("exists") or live_snapshot.get("fingerprint") != baseline_current.get(
        "fingerprint"
    ):
        raise SafeRollbackError("authoritative_current_release_changed_since_prepare")
    if int(live_snapshot.get("file_count") or -1) != int(
        baseline_current.get("file_count") or -2
    ):
        raise SafeRollbackError("authoritative_current_release_file_count_changed")

    return {
        "deploy": deploy,
        "transaction": transaction,
        "lease_hash": lease_hash,
        "previous_version": previous_version,
        "candidate_version": candidate_version,
        "base_url": previous_base_url,
        "authoritative_snapshot": live_snapshot,
        "context_fingerprint": context_fingerprint,
        "candidate_generation_id": expected_generation,
    }


def get_json(
    base_url: str,
    path: str,
    *,
    proxy_url: str,
    timeout_seconds: float,
) -> tuple[int, dict[str, Any]]:
    handlers: list[Any] = []
    if proxy_url:
        handlers.append(
            urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
        )
    opener = urllib.request.build_opener(*handlers)
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        headers={
            "Accept": "application/json",
            "User-Agent": "huaidj-cloudrun-rollback-verifier/1",
        },
    )
    try:
        with opener.open(request, timeout=timeout_seconds) as response:
            status = int(getattr(response, "status", response.getcode()))
            raw = response.read(8_000_000)
    except (OSError, urllib.error.URLError) as exc:
        raise SafeRollbackError("rollback_verification_http_request_failed") from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SafeRollbackError("rollback_verification_http_json_invalid") from exc
    if not isinstance(payload, dict):
        raise SafeRollbackError("rollback_verification_http_json_not_object")
    return status, payload


def require_ok_json(
    base_url: str,
    path: str,
    *,
    proxy_url: str,
    timeout_seconds: float,
    failure_code: str,
) -> dict[str, Any]:
    status, payload = get_json(
        base_url,
        path,
        proxy_url=proxy_url,
        timeout_seconds=timeout_seconds,
    )
    if status != 200:
        raise SafeRollbackError(failure_code)
    return payload


def fetch_all_remote_ids(
    *,
    base_url: str,
    proxy_url: str,
    request_timeout_seconds: float,
    max_pages: int,
) -> dict[str, Any]:
    if max_pages <= 0:
        raise SafeRollbackError("rollback_pagination_max_pages_invalid")
    ids: list[str] = []
    seen_cursors: set[str] = set()
    cursor: str | None = None
    expected_total: int | None = None
    for page_number in range(1, max_pages + 1):
        cursor_key = "<first>" if cursor is None else cursor
        if cursor_key in seen_cursors:
            raise SafeRollbackError("rollback_pagination_cursor_repeated")
        seen_cursors.add(cursor_key)
        params: list[tuple[str, str]] = [("scope", "package"), ("limit", "100")]
        if cursor is not None:
            params.append(("cursor", cursor))
        path = "/api/v1/weekly/current?" + urllib.parse.urlencode(params)
        payload = require_ok_json(
            base_url,
            path,
            proxy_url=proxy_url,
            timeout_seconds=request_timeout_seconds,
            failure_code="rollback_pagination_http_failed",
        )
        items = payload.get("items")
        page = payload.get("page")
        filters = payload.get("filters")
        if not isinstance(items, list) or not isinstance(page, dict):
            raise SafeRollbackError("rollback_pagination_payload_invalid")
        if not isinstance(filters, dict) or str(filters.get("scope") or "") != "package":
            raise SafeRollbackError("rollback_pagination_scope_not_package")
        try:
            page_total = int(page.get("total"))
        except (TypeError, ValueError) as exc:
            raise SafeRollbackError("rollback_pagination_total_invalid") from exc
        if expected_total is None:
            expected_total = page_total
        elif page_total != expected_total:
            raise SafeRollbackError("rollback_pagination_total_changed")
        for item in items:
            if not isinstance(item, dict) or not str(item.get("id") or "").strip():
                raise SafeRollbackError("rollback_pagination_item_id_invalid")
            ids.append(str(item["id"]).strip())
        raw_next = page.get("nextCursor")
        if raw_next is None or str(raw_next) == "":
            unique_ids = sorted(set(ids))
            digest = hashlib.sha256("\n".join(unique_ids).encode("utf-8")).hexdigest()
            return {
                "pages_fetched": page_number,
                "reported_total": expected_total,
                "item_count": len(ids),
                "unique_item_id_count": len(unique_ids),
                "duplicate_item_id_count": len(ids) - len(unique_ids),
                "item_id_digest": digest,
                "item_ids": unique_ids,
                "digest_algorithm": "sha256(sorted_unique_item_ids_utf8_lf)",
            }
        next_cursor = str(raw_next)
        if next_cursor == cursor or next_cursor in seen_cursors:
            raise SafeRollbackError("rollback_pagination_cursor_did_not_advance")
        cursor = next_cursor
    raise SafeRollbackError("rollback_pagination_max_pages_exceeded")


def verify_authoritative_release(
    *,
    base_url: str,
    service_name: str,
    authoritative_release_dir: Path,
    proxy_url: str,
    request_timeout_seconds: float,
    max_pages: int,
) -> dict[str, Any]:
    """Verify the restored service exactly matches the old local authority."""

    release_dir = Path(authoritative_release_dir)
    manifest = read_object(
        release_dir / "manifest.json", "authoritative_manifest_missing_or_invalid"
    )
    generation_id = str(
        manifest.get("generation_id") or manifest.get("generationId") or ""
    )
    if not generation_id:
        raise SafeRollbackError("authoritative_manifest_generation_missing")
    local_ids = item_id_snapshot(release_dir)
    try:
        manifest_count = int(manifest.get("item_count"))
    except (TypeError, ValueError) as exc:
        raise SafeRollbackError("authoritative_manifest_item_count_invalid") from exc
    if manifest_count != local_ids["item_count"]:
        raise SafeRollbackError("authoritative_manifest_current_count_mismatch")

    health = require_ok_json(
        base_url,
        "/healthz",
        proxy_url=proxy_url,
        timeout_seconds=request_timeout_seconds,
        failure_code="rollback_health_http_failed",
    )
    if health.get("ok") is not True or str(health.get("service") or "") != service_name:
        raise SafeRollbackError("rollback_health_contract_failed")
    ready = require_ok_json(
        base_url,
        "/readyz",
        proxy_url=proxy_url,
        timeout_seconds=request_timeout_seconds,
        failure_code="rollback_ready_http_failed",
    )
    ready_generation = str(ready.get("generationId") or ready.get("generation_id") or "")
    if (
        ready.get("ok") is not True
        or str(ready.get("service") or "") != service_name
        or ready_generation != generation_id
        or int(ready.get("packageItemCount") or -1) != local_ids["item_count"]
        or int(ready.get("derivedDetailCount") or -1) != local_ids["item_count"]
        or str(ready.get("itemIdDigest") or "") != local_ids["item_id_digest"]
    ):
        raise SafeRollbackError("rollback_ready_generation_or_digest_mismatch")
    remote_manifest = require_ok_json(
        base_url,
        "/api/v1/weekly/manifest",
        proxy_url=proxy_url,
        timeout_seconds=request_timeout_seconds,
        failure_code="rollback_manifest_http_failed",
    )
    remote_manifest_generation = str(
        remote_manifest.get("generation_id") or remote_manifest.get("generationId") or ""
    )
    if (
        remote_manifest.get("schema_version") != "weekly_activity_miniprogram_api.v1"
        or int(remote_manifest.get("item_count") or -1) != local_ids["item_count"]
        or remote_manifest_generation != generation_id
    ):
        raise SafeRollbackError("rollback_manifest_mismatch")

    remote_ids = fetch_all_remote_ids(
        base_url=base_url,
        proxy_url=proxy_url,
        request_timeout_seconds=request_timeout_seconds,
        max_pages=max_pages,
    )
    if (
        remote_ids["reported_total"] != local_ids["item_count"]
        or remote_ids["item_count"] != local_ids["item_count"]
        or remote_ids["unique_item_id_count"] != local_ids["unique_item_id_count"]
        or remote_ids["duplicate_item_id_count"] != 0
        or remote_ids["item_id_digest"] != local_ids["item_id_digest"]
        or remote_ids["item_ids"] != local_ids["item_ids"]
    ):
        raise SafeRollbackError("remote_item_ids_do_not_match_authoritative_release")

    candidate_clubs = read_object(
        release_dir / "club_overviews.json",
        "authoritative_club_overviews_missing_or_invalid",
    )
    candidate_club_snapshot = build_club_overviews_snapshot(
        candidate_clubs, source="authoritative_local"
    )
    remote_clubs = require_ok_json(
        base_url,
        "/api/v1/weekly/club-overviews",
        proxy_url=proxy_url,
        timeout_seconds=request_timeout_seconds,
        failure_code="rollback_club_overviews_http_failed",
    )
    remote_club_snapshot = build_club_overviews_snapshot(
        remote_clubs, source="restored_remote"
    )
    try:
        assert_matching_snapshots(candidate_club_snapshot, remote_club_snapshot)
    except ValueError as exc:
        raise SafeRollbackError("rollback_club_overviews_mismatch") from exc

    return {
        "ok": True,
        "base_url": base_url,
        "generation_id": generation_id,
        "item_count": local_ids["item_count"],
        "item_id_digest": local_ids["item_id_digest"],
        "health": {"ok": True, "service": service_name},
        "ready": {
            "ok": True,
            "generation_id": ready_generation,
            "package_item_count": local_ids["item_count"],
            "item_id_digest": local_ids["item_id_digest"],
        },
        "manifest": {
            "schema_version": remote_manifest.get("schema_version"),
            "generation_id": remote_manifest_generation,
            "item_count": local_ids["item_count"],
        },
        "pagination": {
            key: value for key, value in remote_ids.items() if key != "item_ids"
        },
        "club_overviews": {
            "verified": True,
            "club_count": candidate_club_snapshot.get("club_count"),
            "overview_count": candidate_club_snapshot.get("overview_count"),
            "kind_counts": candidate_club_snapshot.get("kind_counts"),
            "summary_sha256": candidate_club_snapshot.get("summary_sha256"),
        },
    }


def verify_with_retry(args: argparse.Namespace, base_url: str) -> dict[str, Any]:
    deadline = time.monotonic() + max(float(args.verification_timeout_seconds), 0.0)
    last_error: SafeRollbackError | None = None
    attempts = 0
    while True:
        attempts += 1
        try:
            evidence = verify_authoritative_release(
                base_url=base_url,
                service_name=args.service_name,
                authoritative_release_dir=args.authoritative_release_dir,
                proxy_url=args.proxy_url,
                request_timeout_seconds=args.request_timeout_seconds,
                max_pages=args.max_pages,
            )
            evidence["attempt_count"] = attempts
            return evidence
        except SafeRollbackError as exc:
            last_error = exc
        if time.monotonic() >= deadline:
            assert last_error is not None
            raise last_error
        time.sleep(max(float(args.verification_poll_interval_seconds), 0.01))


def wait_for_restored_identity(
    args: argparse.Namespace,
    *,
    base_url: str,
    candidate_version: str,
    previous_version: str,
) -> dict[str, Any]:
    """Allow CloudBase routing identity to converge after a successful task."""

    deadline = time.monotonic() + max(float(args.verification_timeout_seconds), 0.0)
    attempts = 0
    while True:
        attempts += 1
        try:
            identity = describe_cloudrun_server_identity(args.env_id, args.service_name)
        except Exception:  # noqa: BLE001 - provider text must not escape
            identity = {}
        observed_base = str(identity.get("base_url") or "").rstrip("/")
        observed_version = safe_remote_identifier(identity.get("active_version"))
        ratio_is_100 = int_100(identity.get("active_flow_ratio"))
        if observed_base and observed_base != base_url:
            raise SafeRollbackError("rollback_readback_base_url_changed")
        if observed_version and observed_version not in {candidate_version, previous_version}:
            raise SafeRollbackError("rollback_readback_third_party_version_detected")
        if observed_base == base_url and observed_version == previous_version and ratio_is_100:
            return {
                "base_url": observed_base,
                "active_version": observed_version,
                "active_flow_ratio": 100,
                "attempt_count": attempts,
            }
        if time.monotonic() >= deadline:
            raise SafeRollbackError("rollback_identity_not_restored")
        time.sleep(max(float(args.verification_poll_interval_seconds), 0.01))


def _run_bound(args: argparse.Namespace, report: dict[str, Any]) -> dict[str, Any]:
    bound = bind_evidence(args)
    lease = validate_lease(args, bound["lease_hash"])
    report.update(
        {
            "stage": "evidence_bound",
            "evidence_binding": {
                "transaction_id": args.transaction_id,
                "env_id": args.env_id,
                "service_name": args.service_name,
                "deploy_context_fingerprint": bound["context_fingerprint"],
                "candidate_generation_id": bound["candidate_generation_id"],
                "publish_lease_token_sha256": bound["lease_hash"],
                "previous_active_version": bound["previous_version"],
                "candidate_active_version": bound["candidate_version"],
            },
            "service_publish_lease": safe_lease_evidence(lease),
            "authoritative_current_release": {
                "path": str(Path(args.authoritative_release_dir).resolve()),
                "fingerprint": bound["authoritative_snapshot"]["fingerprint"],
                "file_count": bound["authoritative_snapshot"]["file_count"],
            },
        }
    )
    write_json_durable(args.report, report)

    try:
        live_before = describe_cloudrun_server_identity(args.env_id, args.service_name)
    except Exception as exc:  # noqa: BLE001 - provider text may contain request details
        raise SafeRollbackError("live_server_identity_capture_failed") from exc
    live_version = validated_version(live_before, "live_active")
    live_base_url = validate_base_url(live_before.get("base_url"), "live_base_url_invalid")
    if live_base_url != bound["base_url"]:
        raise SafeRollbackError("live_base_url_not_bound_to_deploy")
    if live_version not in {bound["previous_version"], bound["candidate_version"]}:
        raise SafeRollbackError("live_active_version_not_owned_by_transaction")
    report["live_identity_before"] = {
        "base_url": live_base_url,
        "active_version": live_version,
        "active_flow_ratio": 100,
    }

    if live_version == bound["previous_version"]:
        report["idempotent_previous_version_already_active"] = True
        report["stage"] = "previous_version_already_active"
        write_json_durable(args.report, report)
    else:
        report["idempotent_previous_version_already_active"] = False
        report["stage"] = "rollback_intent_journaled"
        report["rollback_intent"] = {
            "action": "SubmitServerRollback",
            "current_version": bound["candidate_version"],
            "rollback_version": bound["previous_version"],
            "journaled_at": now_iso(),
        }
        write_json_durable(args.report, report)

        lease_before_call = validate_lease(args, bound["lease_hash"])
        report["service_publish_lease_revalidated_before_rollback"] = safe_lease_evidence(
            lease_before_call
        )
        # Conservatively journal the API attempt before calling the provider.
        # If the response is lost, the report remains rollback-required.
        report["automatic_rollback_executed"] = True
        report["rollback_api_call_attempted_at"] = now_iso()
        write_json_durable(args.report, report)
        try:
            response = tcb_api(
                "SubmitServerRollback",
                {
                    "EnvId": args.env_id,
                    "ServerName": args.service_name,
                    "CurrentVersionName": bound["candidate_version"],
                    "RollbackVersionName": bound["previous_version"],
                    "OperatorRemark": (
                        f"huaidj automatic rollback tx={args.transaction_id}"
                    )[:200],
                },
                service="tcbr",
                api_version="2022-02-17",
            )
        except Exception as exc:  # noqa: BLE001 - never persist provider exception text
            raise SafeRollbackError("submit_server_rollback_api_failed") from exc
        task_id_raw = safe_remote_identifier(response.get("TaskId"))
        request_id = safe_remote_identifier(response.get("RequestId"))
        try:
            task_id = int(task_id_raw)
            if task_id <= 0:
                raise ValueError
        except (TypeError, ValueError) as exc:
            raise SafeRollbackError("rollback_response_task_id_invalid") from exc
        report["rollback_response"] = {
            "task_id": task_id,
            "request_id": request_id,
            "response_received": True,
        }
        report["stage"] = "rollback_response_received"
        write_json_durable(args.report, report)
        try:
            operation = poll_task(
                args.env_id,
                args.service_name,
                task_id,
                args.max_wait_seconds,
            )
        except Exception as exc:  # noqa: BLE001 - never persist provider exception text
            raise SafeRollbackError("rollback_task_poll_failed") from exc
        report["rollback_operation"] = {
            "ok": operation.get("ok") is True,
            "status": safe_remote_identifier(operation.get("status")),
            "version_name": safe_remote_identifier(operation.get("version_name")),
        }
        report["stage"] = "rollback_task_polled"
        write_json_durable(args.report, report)
        if operation.get("ok") is not True:
            raise SafeRollbackError("rollback_task_failed")
        polled_version = safe_remote_identifier(operation.get("version_name"))
        if polled_version and polled_version != bound["previous_version"]:
            raise SafeRollbackError("rollback_task_version_mismatch")

    lease_after_task = validate_lease(args, bound["lease_hash"])
    report["service_publish_lease_revalidated_before_readback"] = safe_lease_evidence(
        lease_after_task
    )
    live_after = wait_for_restored_identity(
        args,
        base_url=bound["base_url"],
        candidate_version=bound["candidate_version"],
        previous_version=bound["previous_version"],
    )
    restored_base_url = str(live_after["base_url"])
    report["live_identity_after"] = live_after
    report["stage"] = "rollback_identity_restored"
    write_json_durable(args.report, report)

    verification = verify_with_retry(args, restored_base_url)
    report["restored_authoritative_verification"] = verification
    final_lease = validate_lease(args, bound["lease_hash"])
    report["service_publish_lease_revalidated_after_verification"] = safe_lease_evidence(
        final_lease
    )
    report.update(
        {
            "ok": True,
            "decision": "cloudrun_automatic_rollback_verified",
            "automatic_rollback_verified": True,
            "stage": "rollback_and_authoritative_release_verified",
            "verified_at": now_iso(),
        }
    )
    write_json_durable(args.report, report)
    return report


def run(args: argparse.Namespace) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": False,
        "decision": "cloudrun_automatic_rollback_not_started",
        "stage": "initializing",
        "transaction_id": args.transaction_id,
        "env_id": args.env_id,
        "service_name": args.service_name,
        "deploy_report": str(Path(args.deploy_report).resolve()),
        "transaction_report": str(Path(args.transaction_report).resolve()),
        "automatic_rollback_executed": False,
        "automatic_rollback_verified": False,
        "idempotent_previous_version_already_active": False,
        "safety": {
            "unknown_or_third_party_version_mutated": False,
            "lease_token_persisted": False,
            "provider_exception_text_persisted": False,
            "local_authoritative_release_mutated": False,
        },
    }
    write_json_durable(args.report, report)
    try:
        return _run_bound(args, report)
    except Exception as exc:  # noqa: BLE001 - collapse all text to a fixed safe code
        code = exc.code if isinstance(exc, SafeRollbackError) else "automatic_rollback_unexpected_failure"
        report.update(
            {
                "ok": False,
                "decision": "cloudrun_automatic_rollback_blocked",
                "automatic_rollback_verified": False,
                "stage": "rollback_blocked",
                "failed_at": now_iso(),
                "failure": {"code": code},
            }
        )
        write_json_durable(args.report, report)
        return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transaction-id", required=True)
    parser.add_argument("--env-id", default=ENV_ID)
    parser.add_argument("--service-name", default=SERVICE_NAME)
    parser.add_argument("--deploy-report", type=Path, required=True)
    parser.add_argument("--transaction-report", type=Path, required=True)
    parser.add_argument("--authoritative-release-dir", type=Path, required=True)
    parser.add_argument("--publish-lease-path", type=Path, required=True)
    parser.add_argument("--publish-lease-token", required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--proxy-url", default="")
    parser.add_argument("--max-wait-seconds", type=int, default=900)
    parser.add_argument("--verification-timeout-seconds", type=float, default=180.0)
    parser.add_argument("--verification-poll-interval-seconds", type=float, default=5.0)
    parser.add_argument("--request-timeout-seconds", type=float, default=30.0)
    parser.add_argument("--max-pages", type=int, default=1000)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = run(args)
    print(
        json.dumps(
            {
                "ok": report.get("ok"),
                "decision": report.get("decision"),
                "automatic_rollback_executed": report.get(
                    "automatic_rollback_executed"
                ),
                "automatic_rollback_verified": report.get(
                    "automatic_rollback_verified"
                ),
                "failure_code": (report.get("failure") or {}).get("code"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
