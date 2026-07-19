#!/usr/bin/env python3
"""Smoke-test the deployed CloudRun weekly API.

This is a production read-only smoke. It checks the weekly mini-program API
surface and materialized LLM endpoints without executing live LLM calls, paid
APIs, databases, vector stores, graph writes, mem0 writes, or D: scans.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


ENV_ID = "huaidjweekly-d8g1go7-d0a07863e3e"
SERVICE_NAME = "weekly-api"
DEFAULT_OUT_DIR = Path(
    os.environ.get("HUAIDJ_REPORT_ROOT", r"F:\DevData\HuaidjRuntime\state\reports")
) / "cloudrun_weekly_production_smoke"
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_TCB_CWD = REPO_ROOT / "services" / "weekly_activity_cloudrun"
TCB_CMD = [shutil.which("npm") or "npm", "exec", "--yes", "--package", "@cloudbase/cli@3.3.1", "--", "tcb"]
EXPECTED_MIN_READY_ITEMS = 50
EXPECTED_MIN_CURRENT_ITEMS = 1
MAX_CURRENT_PAGES = 1000


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def parse_first_json_object(text: str) -> dict[str, Any]:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        return {}
    value = json.loads(text[start : end + 1])
    return value if isinstance(value, dict) else {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def resolve_tcb_cwd(explicit: Path | None) -> Path:
    cwd = (explicit or DEFAULT_TCB_CWD).expanduser().resolve()
    if not cwd.is_dir():
        raise ValueError(f"CloudBase CLI working directory does not exist: {cwd}")
    if not (cwd / "package.json").is_file():
        raise ValueError(f"CloudBase CLI working directory is not a CloudRun project (package.json missing): {cwd}")
    return cwd


def tcb_api(
    action: str,
    body: dict[str, Any],
    timeout_seconds: int | None,
    *,
    tcb_cwd: Path | None = None,
) -> dict[str, Any]:
    cmd = [
        *TCB_CMD,
        "api",
        "tcbr",
        action,
        "--api-version",
        "2022-02-17",
        "--body",
        json.dumps(body, ensure_ascii=False, separators=(",", ":")),
        "--json",
    ]
    run_kwargs: dict[str, Any] = {"cwd": resolve_tcb_cwd(tcb_cwd), "capture_output": True, "text": True}
    if timeout_seconds is not None:
        run_kwargs["timeout"] = timeout_seconds
    result = subprocess.run(cmd, **run_kwargs)
    payload = parse_first_json_object((result.stdout or "") + "\n" + (result.stderr or ""))
    if result.returncode != 0:
        raise RuntimeError(f"CloudBase API {action} failed with returncode={result.returncode}")
    data = payload.get("data")
    return data if isinstance(data, dict) else payload


def discover_server(
    env_id: str,
    service_name: str,
    timeout_seconds: int | None,
    *,
    tcb_cwd: Path | None = None,
) -> dict[str, Any]:
    data = tcb_api(
        "DescribeCloudRunServerDetail",
        {"EnvId": env_id, "ServerName": service_name},
        timeout_seconds,
        tcb_cwd=tcb_cwd,
    )
    base = data.get("BaseInfo") if isinstance(data.get("BaseInfo"), dict) else {}
    versions = data.get("OnlineVersionInfos") if isinstance(data.get("OnlineVersionInfos"), list) else []
    active = next((item for item in versions if str(item.get("FlowRatio")) == "100"), versions[0] if versions else {})
    return {
        "base_url": str(base.get("DefaultDomainName") or "").rstrip("/"),
        "status": base.get("Status"),
        "update_time": base.get("UpdateTime"),
        "access_types": base.get("AccessTypes") or [],
        "active_version": active.get("VersionName", ""),
        "active_flow_ratio": active.get("FlowRatio", ""),
        "request_id": data.get("RequestId", ""),
    }


def decode_json(raw: bytes) -> dict[str, Any]:
    text = raw.decode("utf-8", errors="replace")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {"_decode_error": text[:240]}
    return payload if isinstance(payload, dict) else {"value": payload}


def get_json(base_url: str, path: str, timeout: int | None) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}{path}"
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "stage7-weekly-smoke/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(4_000_000)
            return {
                "url_path": path,
                "status_code": response.status,
                "content_type": response.headers.get("content-type", ""),
                "bytes_read": len(raw),
                "payload": decode_json(raw),
            }
    except urllib.error.HTTPError as exc:
        raw = exc.read(256_000)
        return {
            "url_path": path,
            "status_code": exc.code,
            "content_type": exc.headers.get("content-type", ""),
            "bytes_read": len(raw),
            "payload": decode_json(raw),
        }


def current_path(*, limit: int, lookback_days: int | None = None, cursor: str | None = None, scope: str | None = None) -> str:
    params: list[tuple[str, str]] = [("limit", str(limit))]
    if scope:
        params.append(("scope", scope))
    if lookback_days is not None:
        params.append(("lookbackDays", str(lookback_days)))
    if cursor is not None:
        params.append(("cursor", str(cursor)))
    return f"/api/v1/weekly/current?{urllib.parse.urlencode(params)}"


def get_paginated_current(
    base_url: str,
    timeout: int | None,
    *,
    limit: int = 100,
    lookback_days: int | None = None,
    scope: str | None = None,
    max_pages: int = MAX_CURRENT_PAGES,
) -> dict[str, Any]:
    """Fetch a full current feed so LLM coverage is not judged from page 1 only."""
    if max_pages <= 0:
        raise ValueError("max_pages must be positive")
    first: dict[str, Any] | None = None
    first_payload: dict[str, Any] | None = None
    first_page: dict[str, Any] | None = None
    all_items: list[Any] = []
    seen_cursors: set[str] = set()
    cursor: str | None = None

    for page_number in range(1, max_pages + 1):
        cursor_key = "<first>" if cursor is None else cursor
        if cursor_key in seen_cursors:
            raise RuntimeError(f"pagination cursor repeated: {cursor_key}")
        seen_cursors.add(cursor_key)
        path = current_path(
            limit=limit,
            lookback_days=lookback_days,
            cursor=cursor,
            scope=scope,
        )
        response = get_json(base_url, path, timeout)
        payload = response.get("payload") if isinstance(response.get("payload"), dict) else {}
        if response.get("status_code") != 200 or not isinstance(payload.get("items"), list):
            raise RuntimeError(
                f"pagination page request failed: page={page_number} status={response.get('status_code')}"
            )
        page = payload.get("page") if isinstance(payload.get("page"), dict) else None
        if page is None:
            raise RuntimeError(f"pagination page metadata missing: page={page_number}")
        if first is None:
            first = response
            first_payload = dict(payload)
            first_page = dict(page)
        all_items.extend(payload.get("items") or [])
        raw_next = page.get("nextCursor")
        if raw_next is None or str(raw_next) == "":
            assert first is not None and first_payload is not None and first_page is not None
            first_payload["items"] = all_items
            first_payload["page"] = {
                **first_page,
                "limit": limit,
                "cursor": "0",
                "nextCursor": None,
                "fetched": len(all_items),
                "pagesFetched": page_number,
            }
            return {**first, "payload": first_payload}
        next_cursor = str(raw_next)
        if cursor is not None and next_cursor == cursor:
            raise RuntimeError(f"pagination cursor did not advance: {cursor}")
        if next_cursor in seen_cursors:
            raise RuntimeError(f"pagination cursor repeated: {next_cursor}")
        cursor = next_cursor

    raise RuntimeError(f"pagination exceeded maximum page count: {max_pages}")


def list_count(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    return len(value) if isinstance(value, list) else 0


def endpoint_summary(name: str, response: dict[str, Any]) -> dict[str, Any]:
    payload = response["payload"]
    status_code = response.get("status_code")
    summary: dict[str, Any] = {
        "name": name,
        "url_path": response["url_path"],
        "status_code": status_code,
        "json_object": isinstance(payload, dict) and "_decode_error" not in payload,
        "bytes_read": response.get("bytes_read"),
    }
    if isinstance(payload, dict) and payload.get("_error"):
        summary["error"] = payload.get("_error")
    if name == "healthz":
        llm = payload.get("llm") if isinstance(payload.get("llm"), dict) else {}
        summary.update({"ok_field": payload.get("ok"), "service": payload.get("service"), "llm_has_api_key": "apiKey" in llm})
    elif name == "readyz":
        summary.update(
            {
                "ok_field": payload.get("ok"),
                "service": payload.get("service"),
                "generation_id": payload.get("generationId"),
                "package_item_count": payload.get("packageItemCount"),
                "derived_detail_count": payload.get("derivedDetailCount"),
                "item_id_digest": payload.get("itemIdDigest"),
            }
        )
    elif name == "manifest":
        summary.update(
            {
                "schema_version": payload.get("schema_version"),
                "generated_at": payload.get("generated_at"),
                "item_count": payload.get("item_count"),
                "city_route_count": payload.get("city_route_count"),
                "date_route_count": payload.get("date_route_count"),
            }
        )
    elif name in {"current", "full_current"}:
        page = payload.get("page") if isinstance(payload.get("page"), dict) else {}
        items = payload.get("items") if isinstance(payload.get("items"), list) else []
        summary.update(
            {
                "total": page.get("total"),
                "item_count": len(items),
                "item_ids": [str(item.get("id")) for item in items if isinstance(item, dict) and item.get("id")],
                "city_counts": dict(sorted(Counter(
                    str(item.get("city_key") or ((item.get("city_keys") or [""])[0] if isinstance(item.get("city_keys"), list) and item.get("city_keys") else ""))
                    for item in items if isinstance(item, dict) and (item.get("city_key") or item.get("city_keys"))
                ).items())),
            }
        )
    elif name == "cities":
        city_rows = payload.get("cities") if isinstance(payload.get("cities"), list) else []
        summary.update({
            "scope": payload.get("scope"),
            "city_count": payload.get("city_count") or list_count(payload, "cities"),
            "item_count": payload.get("item_count"),
            "city_counts": {
                str(row.get("city_key") or row.get("key")): int(row.get("item_count") or row.get("count") or 0)
                for row in city_rows if isinstance(row, dict) and (row.get("city_key") or row.get("key"))
            },
        })
    elif name == "dates":
        summary.update({
            "scope": payload.get("scope"),
            "date_count": payload.get("date_count") or list_count(payload, "dates"),
            "item_count": payload.get("item_count"),
        })
    elif name == "llm_status":
        llm = payload.get("llm") if isinstance(payload.get("llm"), dict) else {}
        summary.update(
            {
                "schema_version": payload.get("schemaVersion"),
                "provider": llm.get("provider"),
                "model": llm.get("model"),
                "thinking": llm.get("thinking"),
                "llm_has_api_key": "apiKey" in llm,
            }
        )
    elif name == "materialized_summary":
        summary.update(
            {
                "schema_version": payload.get("schemaVersion"),
                "generated_at": payload.get("generatedAt"),
                "provider": payload.get("provider"),
                "model": payload.get("model"),
                "item_count": payload.get("itemCount"),
                "has_summary": isinstance(payload.get("summary"), dict),
            }
        )
    elif name == "materialized_enrichments":
        enrichments = payload.get("enrichments") if isinstance(payload.get("enrichments"), list) else []
        summary.update(
            {
                "schema_version": payload.get("schemaVersion"),
                "generated_at": payload.get("generatedAt"),
                "provider": payload.get("provider"),
                "model": payload.get("model"),
                "item_count": payload.get("itemCount"),
                "enrichment_count": len(enrichments),
                "enrichment_ids": [str(item.get("id")) for item in enrichments if isinstance(item, dict) and item.get("id")],
            }
        )
    elif name == "materialized_enrichment_detail":
        enriched = payload.get("enriched") if isinstance(payload.get("enriched"), dict) else {}
        summary.update(
            {
                "schema_version": payload.get("schemaVersion"),
                "id": payload.get("id"),
                "has_enrichment": isinstance(payload.get("enrichment"), dict)
                or isinstance(enriched.get("enrichment"), dict),
            }
        )
    if isinstance(status_code, int) and status_code >= 400:
        error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
        summary["error_code"] = error.get("code")
    return summary


def endpoint_ok(
    name: str,
    summary: dict[str, Any],
    *,
    expected_min_ready_items: int = EXPECTED_MIN_READY_ITEMS,
    expected_min_current_items: int = EXPECTED_MIN_CURRENT_ITEMS,
) -> bool:
    if summary.get("status_code") != 200 or not summary.get("json_object"):
        return False
    if name == "healthz":
        return summary.get("ok_field") is True and summary.get("service") == SERVICE_NAME and not summary.get("llm_has_api_key")
    if name == "readyz":
        package_count = int(summary.get("package_item_count") or 0)
        return (
            summary.get("ok_field") is True
            and summary.get("service") == SERVICE_NAME
            and bool(summary.get("generation_id"))
            and package_count >= expected_min_ready_items
            and int(summary.get("derived_detail_count") or 0) == package_count
            and len(str(summary.get("item_id_digest") or "")) == 64
        )
    if name == "manifest":
        return (
            summary.get("schema_version") == "weekly_activity_miniprogram_api.v1"
            and int(summary.get("item_count") or 0) >= expected_min_ready_items
        )
    if name in {"current", "full_current"}:
        return int(summary.get("total") or 0) >= expected_min_current_items and int(summary.get("item_count") or 0) > 0
    if name == "cities":
        return int(summary.get("city_count") or 0) > 0
    if name == "dates":
        return int(summary.get("date_count") or 0) > 0
    if name == "llm_status":
        return summary.get("schema_version") == "weekly_activity_api.llm_status.v1" and not summary.get("llm_has_api_key")
    if name == "materialized_summary":
        return (
            summary.get("schema_version") == "weekly_activity_api.materialized_summary.v1"
            and int(summary.get("item_count") or 0) >= expected_min_ready_items
            and summary.get("has_summary") is True
        )
    if name == "materialized_enrichments":
        return (
            summary.get("schema_version") == "weekly_activity_api.materialized_enrichment_index.v1"
            and int(summary.get("item_count") or 0) >= expected_min_ready_items
            and int(summary.get("enrichment_count") or 0) >= expected_min_ready_items
        )
    if name == "materialized_enrichment_detail":
        return (
            summary.get("schema_version") == "weekly_activity_api.materialized_enrichment.v1"
            and summary.get("has_enrichment") is True
        )
    return False


def by_name(endpoint_summaries: list[dict[str, Any]], name: str) -> dict[str, Any]:
    return next((item for item in endpoint_summaries if item.get("name") == name), {})


def bind_report_to_deploy(
    report: dict[str, Any],
    deploy_report_path: Path,
    *,
    expected_env_id: str,
    expected_service_name: str,
) -> dict[str, Any]:
    """Fail closed unless this smoke proves the exact named deploy candidate."""
    blockers = list(report.get("blockers") or [])
    try:
        deploy = json.loads(Path(deploy_report_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        deploy = {}
        blockers.append("deploy_evidence_missing_or_invalid")
    binding = deploy.get("evidence_binding") if isinstance(deploy.get("evidence_binding"), dict) else {}
    identity = deploy.get("deployment_identity") if isinstance(deploy.get("deployment_identity"), dict) else {}
    ready = by_name(report.get("endpoints") or [], "readyz")
    active_version = str((report.get("server") or {}).get("active_version") or "")
    smoke_base_url = str((report.get("server") or {}).get("base_url") or "").rstrip("/")
    deploy_base_url = str(
        (deploy.get("post_update_server_identity") or {}).get("base_url") or ""
    ).rstrip("/")
    remote_generation_id = str(ready.get("generation_id") or "")
    expected_generation_id = str(binding.get("expected_generation_id") or "")
    fingerprint = str(binding.get("deploy_context_fingerprint") or "")
    zip_sha = str(binding.get("deploy_zip_sha256") or "")
    lease_hash = str(binding.get("publish_lease_token_sha256") or "")
    reported_version = str(identity.get("reported_version") or "")
    observed_active_version = str(identity.get("observed_active_version") or "")
    checks = {
        "deploy_report_schema": deploy.get("schema_version") == "cloudrun_direct_api_deploy.v2",
        "deploy_report_ok": deploy.get("ok") is True,
        "deploy_executed": bool((deploy.get("safety") or {}).get("cloud_deploy_executed")),
        "transaction_id_present": bool(binding.get("transaction_id")),
        "target_env_matches": binding.get("env_id") == expected_env_id,
        "target_service_matches": binding.get("service_name") == expected_service_name,
        "context_fingerprint_valid": len(fingerprint) == 64
        and set(fingerprint.lower()) <= set("0123456789abcdef"),
        "deploy_zip_sha_valid": len(zip_sha) == 64
        and set(zip_sha.lower()) <= set("0123456789abcdef"),
        "publish_lease_binding_valid": len(lease_hash) == 64
        and set(lease_hash.lower()) <= set("0123456789abcdef"),
        "deploy_expected_generation_matches": bool(expected_generation_id)
        and remote_generation_id == expected_generation_id,
        "active_version_bound_to_deploy": bool(active_version)
        and bool(reported_version)
        and bool(observed_active_version)
        and active_version == reported_version
        and observed_active_version == reported_version,
        "base_url_bound_to_deploy": bool(smoke_base_url)
        and bool(deploy_base_url)
        and smoke_base_url == deploy_base_url,
    }
    blocker_names = {
        "deploy_report_schema": "deploy_report_schema_mismatch",
        "deploy_report_ok": "deploy_report_not_successful",
        "deploy_executed": "deploy_execution_not_proven",
        "transaction_id_present": "deploy_transaction_id_missing",
        "target_env_matches": "deploy_target_env_mismatch",
        "target_service_matches": "deploy_target_service_mismatch",
        "context_fingerprint_valid": "deploy_context_fingerprint_invalid",
        "deploy_zip_sha_valid": "deploy_zip_sha_invalid",
        "publish_lease_binding_valid": "publish_lease_binding_invalid",
        "deploy_expected_generation_matches": "deploy_expected_generation_mismatch",
        "active_version_bound_to_deploy": "active_version_not_bound_to_deploy",
        "base_url_bound_to_deploy": "base_url_not_bound_to_deploy",
    }
    blockers.extend(blocker_names[name] for name, passed in checks.items() if not passed)
    blockers = list(dict.fromkeys(blockers))
    report["schema_version"] = "stage7_cloudrun_weekly_production_smoke.v2"
    report["deploy_evidence_path"] = str(Path(deploy_report_path).resolve())
    report["deploy_evidence_checks"] = checks
    report["evidence_binding"] = {
        **binding,
        "active_version": active_version,
        "base_url": smoke_base_url,
        "remote_generation_id": remote_generation_id,
    }
    report["blockers"] = blockers
    report["ok"] = not blockers
    report["decision"] = (
        "cloudrun_weekly_production_smoke_ready"
        if report["ok"]
        else "cloudrun_weekly_production_smoke_blocked"
    )
    return report


def build_report(
    server: dict[str, Any],
    endpoint_summaries: list[dict[str, Any]],
    *,
    expected_min_ready_items: int = EXPECTED_MIN_READY_ITEMS,
    expected_min_current_items: int = EXPECTED_MIN_CURRENT_ITEMS,
) -> dict[str, Any]:
    endpoint_results = []
    for item in endpoint_summaries:
        ok = endpoint_ok(
            str(item.get("name")),
            item,
            expected_min_ready_items=expected_min_ready_items,
            expected_min_current_items=expected_min_current_items,
        )
        endpoint_results.append({**item, "ok": ok})
    blockers = [str(item["name"]) for item in endpoint_results if not item["ok"]]

    manifest = by_name(endpoint_results, "manifest")
    current = by_name(endpoint_results, "current")
    full_current = by_name(endpoint_results, "full_current")
    cities = by_name(endpoint_results, "cities")
    dates = by_name(endpoint_results, "dates")
    summary = by_name(endpoint_results, "materialized_summary")
    enrichments = by_name(endpoint_results, "materialized_enrichments")
    llm_reference = full_current if full_current else current
    current_ids = set(llm_reference.get("item_ids") or [])
    enrichment_ids = set(enrichments.get("enrichment_ids") or [])
    missing_current_enrichments = sorted(current_ids - enrichment_ids)
    extra_enrichments = sorted(enrichment_ids - current_ids)
    if current_ids and enrichment_ids and missing_current_enrichments:
        blockers.append("llm_current_enrichment_missing")

    warnings = []
    manifest_count = int(manifest.get("item_count") or 0)
    summary_count = int(summary.get("item_count") or 0)
    enrichment_count = int(enrichments.get("enrichment_count") or 0)
    full_current_count = int(full_current.get("item_count") or 0)
    if summary_count and manifest_count and summary_count != manifest_count:
        warnings.append("materialized_summary_item_count_differs_from_manifest")
    if full_current and full_current_count and manifest_count and full_current_count != manifest_count:
        blockers.append("full_current_count_differs_from_manifest")
    current_total = int(current.get("total") or 0)
    if current_total and int(cities.get("item_count") or -1) != current_total:
        blockers.append("current_city_facet_total_differs")
    if current_total and int(dates.get("item_count") or -1) != current_total:
        blockers.append("current_date_facet_total_differs")
    if current.get("city_counts") != cities.get("city_counts"):
        blockers.append("current_city_facet_counts_differ")
    if extra_enrichments:
        warnings.append("materialized_enrichment_index_is_superset_of_current_release")
    if enrichment_count and summary_count and enrichment_count != summary_count:
        warnings.append("materialized_enrichment_count_differs_from_summary")
    if not server.get("base_url"):
        blockers.append("missing_default_domain_name")
    if server.get("status") != "normal":
        blockers.append("cloudrun_server_not_normal")
    if str(server.get("active_flow_ratio")) != "100":
        blockers.append("active_version_not_100_flow")
    blockers = list(dict.fromkeys(blockers))
    warnings = list(dict.fromkeys(warnings))
    ok = not blockers
    return {
        "schema_version": "stage7_cloudrun_weekly_production_smoke.v1",
        "generated_at": now_iso(),
        "ok": ok,
        "decision": "cloudrun_weekly_production_smoke_ready" if ok else "cloudrun_weekly_production_smoke_blocked",
        "server": server,
        "expected_min_ready_items": expected_min_ready_items,
        "expected_min_current_items": expected_min_current_items,
        "endpoints": endpoint_results,
        "llm_coverage": {
            "reference_endpoint": llm_reference.get("name") or "",
            "current_item_ids_checked": len(current_ids),
            "enrichment_ids_seen": len(enrichment_ids),
            "missing_current_enrichment_count": len(missing_current_enrichments),
            "missing_current_enrichment_sample": missing_current_enrichments[:10],
            "extra_enrichment_count": len(extra_enrichments),
            "extra_enrichment_sample": extra_enrichments[:10],
        },
        "warnings": warnings,
        "blockers": blockers,
        "safety": {
            "secret_value_read_or_printed": False,
            "paid_api_used": False,
            "llm_call_executed": False,
            "production_sqlite_write_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "mem0_write_executed": False,
            "d_scan_executed": False,
        },
        "writes": "production_http_smoke_report_only",
    }


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# CloudRun Weekly Production Smoke",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- decision: `{report['decision']}`",
        f"- ok: `{report['ok']}`",
        f"- active_version: `{report['server'].get('active_version')}`",
        f"- active_flow_ratio: `{report['server'].get('active_flow_ratio')}`",
        "",
        "## Endpoints",
        "",
    ]
    for item in report["endpoints"]:
        lines.append(f"- `{item['name']}` `{item['url_path']}` ok=`{item['ok']}`")
    lines.extend(["", "## LLM Coverage", ""])
    coverage = report["llm_coverage"]
    lines.extend(
        [
            f"- reference_endpoint: `{coverage['reference_endpoint']}`",
            f"- current_item_ids_checked: `{coverage['current_item_ids_checked']}`",
            f"- enrichment_ids_seen: `{coverage['enrichment_ids_seen']}`",
            f"- missing_current_enrichment_count: `{coverage['missing_current_enrichment_count']}`",
            f"- extra_enrichment_count: `{coverage['extra_enrichment_count']}`",
        ]
    )
    lines.extend(["", "## Warnings", ""])
    lines.extend([f"- `{item}`" for item in report["warnings"]] or ["- none"])
    lines.extend(["", "## Blockers", ""])
    lines.extend([f"- `{item}`" for item in report["blockers"]] or ["- none"])
    lines.extend(["", "## Safety", "", "- Read-only HTTP/API smoke. No live LLM, paid API, DB/vector/graph/mem0 write, or D: scan."])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> dict[str, Any]:
    timeout_seconds = None if args.no_timeout else args.timeout_seconds
    tcb_cwd = resolve_tcb_cwd(getattr(args, "tcb_cwd", None))
    server = discover_server(args.env_id, args.service_name, timeout_seconds, tcb_cwd=tcb_cwd)
    if args.base_url:
        server["base_url"] = args.base_url.rstrip("/")
    endpoint_specs = [
        ("healthz", "/healthz"),
        ("readyz", "/readyz"),
        ("manifest", "/api/v1/weekly/manifest"),
        ("cities", "/api/v1/weekly/cities"),
        ("dates", "/api/v1/weekly/dates"),
        ("llm_status", "/api/v1/weekly/llm/status"),
        ("materialized_summary", "/api/v1/weekly/llm/materialized-summary"),
        ("materialized_enrichments", "/api/v1/weekly/llm/materialized-enrichments"),
    ]
    responses: dict[str, dict[str, Any]] = {}
    summaries = []
    for name, path in endpoint_specs:
        try:
            response = get_json(server["base_url"], path, timeout_seconds)
        except Exception as exc:  # noqa: BLE001
            response = {"url_path": path, "status_code": None, "bytes_read": 0, "payload": {"_error": str(exc)[:240]}}
        responses[name] = response
        summaries.append(endpoint_summary(name, response))

    try:
        response = get_paginated_current(server["base_url"], timeout_seconds)
    except Exception as exc:  # noqa: BLE001
        response = {
            "url_path": current_path(limit=100),
            "status_code": None,
            "bytes_read": 0,
            "payload": {"_error": str(exc)[:240]},
        }
    responses["current"] = response
    summaries.insert(2, endpoint_summary("current", response))

    try:
        response = get_paginated_current(server["base_url"], timeout_seconds, scope="package")
    except Exception as exc:  # noqa: BLE001
        response = {
            "url_path": current_path(limit=100, scope="package"),
            "status_code": None,
            "bytes_read": 0,
            "payload": {"_error": str(exc)[:240]},
        }
    responses["full_current"] = response
    summaries.insert(3, endpoint_summary("full_current", response))

    current_items = responses.get("current", {}).get("payload", {}).get("items") or []
    first_id = ""
    if isinstance(current_items, list):
        first_id = next((str(item.get("id")) for item in current_items if isinstance(item, dict) and item.get("id")), "")
    if first_id:
        path = f"/api/v1/weekly/llm/materialized-enrichments/{urllib.parse.quote(first_id, safe='')}"
        try:
            response = get_json(server["base_url"], path, timeout_seconds)
        except Exception as exc:  # noqa: BLE001
            response = {"url_path": path, "status_code": None, "bytes_read": 0, "payload": {"_error": str(exc)[:240]}}
        summaries.append(endpoint_summary("materialized_enrichment_detail", response))
    else:
        summaries.append(
            {
                "name": "materialized_enrichment_detail",
                "url_path": "",
                "status_code": None,
                "json_object": False,
                "error": "no_current_item_id_for_detail_probe",
            }
        )

    report = build_report(
        server,
        summaries,
        expected_min_ready_items=args.expected_min_ready_items,
        expected_min_current_items=args.expected_min_current_items,
    )
    report = bind_report_to_deploy(
        report,
        args.deploy_report,
        expected_env_id=args.env_id,
        expected_service_name=args.service_name,
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.out_dir / "cloudrun_weekly_production_smoke.json", report)
    write_markdown(args.out_dir / "cloudrun_weekly_production_smoke.md", report)
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-id", default=ENV_ID)
    parser.add_argument("--service-name", default=SERVICE_NAME)
    parser.add_argument("--base-url", default="")
    parser.add_argument(
        "--deploy-report",
        type=Path,
        required=True,
        help="The exact named direct-deploy report this remote smoke must bind to.",
    )
    parser.add_argument(
        "--tcb-cwd",
        type=Path,
        default=None,
        help="CloudRun project directory for CloudBase CLI; defaults to this checkout's services/weekly_activity_cloudrun.",
    )
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument("--no-timeout", action="store_true", help="Disable CloudBase and HTTP request timeouts for this smoke.")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--expected-min-ready-items", type=int, default=EXPECTED_MIN_READY_ITEMS)
    parser.add_argument("--expected-min-current-items", type=int, default=EXPECTED_MIN_CURRENT_ITEMS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    global ENV_ID, SERVICE_NAME  # noqa: PLW0603
    args = parse_args(argv)
    ENV_ID = args.env_id
    SERVICE_NAME = args.service_name
    report = run(args)
    print(json.dumps({"ok": report["ok"], "decision": report["decision"], "blockers": report["blockers"], "warnings": report["warnings"]}, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
