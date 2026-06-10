#!/usr/bin/env python3
"""Smoke-test the deployed CloudRun weekly API.

This is a production read-only smoke. It checks the weekly mini-program API
surface and materialized LLM endpoints without executing live LLM calls, paid
APIs, databases, vector stores, graph writes, mem0 writes, or D: scans.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


ENV_ID = "huaidjweekly-d8g1go7-d0a07863e3e"
SERVICE_NAME = "weekly-api"
DEFAULT_OUT_DIR = Path("reports/cloudrun_weekly_production_smoke_20260518")
TCB_CWD = Path(r"C:\code\githubstar\wechathtmldownload\services\weekly_activity_cloudrun")
TCB_CMD = [shutil.which("npm") or "npm", "exec", "--yes", "--package", "@cloudbase/cli@3.3.1", "--", "tcb"]
EXPECTED_MIN_READY_ITEMS = 50
EXPECTED_MIN_CURRENT_ITEMS = 1


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


def tcb_api(action: str, body: dict[str, Any], timeout_seconds: int | None) -> dict[str, Any]:
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
    run_kwargs: dict[str, Any] = {"cwd": TCB_CWD, "capture_output": True, "text": True}
    if timeout_seconds is not None:
        run_kwargs["timeout"] = timeout_seconds
    result = subprocess.run(cmd, **run_kwargs)
    payload = parse_first_json_object((result.stdout or "") + "\n" + (result.stderr or ""))
    if result.returncode != 0:
        raise RuntimeError(f"CloudBase API {action} failed with returncode={result.returncode}")
    data = payload.get("data")
    return data if isinstance(data, dict) else payload


def discover_server(env_id: str, service_name: str, timeout_seconds: int | None) -> dict[str, Any]:
    data = tcb_api("DescribeCloudRunServerDetail", {"EnvId": env_id, "ServerName": service_name}, timeout_seconds)
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


def get_paginated_current(base_url: str, timeout: int | None, *, limit: int = 100) -> dict[str, Any]:
    """Fetch the full default current feed so LLM coverage is not judged from page 1 only."""
    first_path = f"/api/v1/weekly/current?limit={limit}"
    first = get_json(base_url, first_path, timeout)
    payload = first.get("payload") if isinstance(first.get("payload"), dict) else {}
    if first.get("status_code") != 200 or not isinstance(payload.get("items"), list):
        return first

    all_items = list(payload.get("items") or [])
    page = payload.get("page") if isinstance(payload.get("page"), dict) else {}
    next_cursor = page.get("nextCursor")
    while next_cursor:
        path = f"/api/v1/weekly/current?limit={limit}&cursor={urllib.parse.quote(str(next_cursor), safe='')}"
        response = get_json(base_url, path, timeout)
        next_payload = response.get("payload") if isinstance(response.get("payload"), dict) else {}
        if response.get("status_code") != 200 or not isinstance(next_payload.get("items"), list):
            break
        all_items.extend(next_payload.get("items") or [])
        next_page = next_payload.get("page") if isinstance(next_payload.get("page"), dict) else {}
        next_cursor = next_page.get("nextCursor")

    payload = dict(payload)
    payload["items"] = all_items
    if isinstance(page, dict):
        payload["page"] = {**page, "limit": limit, "cursor": "0", "nextCursor": None, "fetched": len(all_items)}
    return {**first, "payload": payload}


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
    elif name == "current":
        page = payload.get("page") if isinstance(payload.get("page"), dict) else {}
        items = payload.get("items") if isinstance(payload.get("items"), list) else []
        summary.update(
            {
                "total": page.get("total"),
                "item_count": len(items),
                "item_ids": [str(item.get("id")) for item in items if isinstance(item, dict) and item.get("id")],
            }
        )
    elif name == "cities":
        summary.update({"city_count": payload.get("city_count") or payload.get("item_count") or list_count(payload, "cities")})
    elif name == "dates":
        summary.update({"date_count": payload.get("date_count") or payload.get("item_count") or list_count(payload, "dates")})
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


def endpoint_ok(name: str, summary: dict[str, Any]) -> bool:
    if summary.get("status_code") != 200 or not summary.get("json_object"):
        return False
    if name == "healthz":
        return summary.get("ok_field") is True and summary.get("service") == SERVICE_NAME and not summary.get("llm_has_api_key")
    if name == "manifest":
        return (
            summary.get("schema_version") == "weekly_activity_miniprogram_api.v1"
            and int(summary.get("item_count") or 0) >= EXPECTED_MIN_READY_ITEMS
        )
    if name == "current":
        return int(summary.get("total") or 0) >= EXPECTED_MIN_CURRENT_ITEMS and int(summary.get("item_count") or 0) > 0
    if name == "cities":
        return int(summary.get("city_count") or 0) > 0
    if name == "dates":
        return int(summary.get("date_count") or 0) > 0
    if name == "llm_status":
        return summary.get("schema_version") == "weekly_activity_api.llm_status.v1" and not summary.get("llm_has_api_key")
    if name == "materialized_summary":
        return (
            summary.get("schema_version") == "weekly_activity_api.materialized_summary.v1"
            and int(summary.get("item_count") or 0) >= EXPECTED_MIN_READY_ITEMS
            and summary.get("has_summary") is True
        )
    if name == "materialized_enrichments":
        return (
            summary.get("schema_version") == "weekly_activity_api.materialized_enrichment_index.v1"
            and int(summary.get("item_count") or 0) >= EXPECTED_MIN_READY_ITEMS
            and int(summary.get("enrichment_count") or 0) >= EXPECTED_MIN_READY_ITEMS
        )
    if name == "materialized_enrichment_detail":
        return (
            summary.get("schema_version") == "weekly_activity_api.materialized_enrichment.v1"
            and summary.get("has_enrichment") is True
        )
    return False


def by_name(endpoint_summaries: list[dict[str, Any]], name: str) -> dict[str, Any]:
    return next((item for item in endpoint_summaries if item.get("name") == name), {})


def build_report(server: dict[str, Any], endpoint_summaries: list[dict[str, Any]]) -> dict[str, Any]:
    endpoint_results = []
    for item in endpoint_summaries:
        ok = endpoint_ok(str(item.get("name")), item)
        endpoint_results.append({**item, "ok": ok})
    blockers = [str(item["name"]) for item in endpoint_results if not item["ok"]]

    manifest = by_name(endpoint_results, "manifest")
    current = by_name(endpoint_results, "current")
    summary = by_name(endpoint_results, "materialized_summary")
    enrichments = by_name(endpoint_results, "materialized_enrichments")
    current_ids = set(current.get("item_ids") or [])
    enrichment_ids = set(enrichments.get("enrichment_ids") or [])
    missing_current_enrichments = sorted(current_ids - enrichment_ids)
    extra_enrichments = sorted(enrichment_ids - current_ids)
    if current_ids and enrichment_ids and missing_current_enrichments:
        blockers.append("llm_current_enrichment_missing")

    warnings = []
    manifest_count = int(manifest.get("item_count") or 0)
    summary_count = int(summary.get("item_count") or 0)
    enrichment_count = int(enrichments.get("enrichment_count") or 0)
    if summary_count and manifest_count and summary_count != manifest_count:
        warnings.append("materialized_summary_item_count_differs_from_manifest")
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
        "expected_min_ready_items": EXPECTED_MIN_READY_ITEMS,
        "expected_min_current_items": EXPECTED_MIN_CURRENT_ITEMS,
        "endpoints": endpoint_results,
        "llm_coverage": {
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
    server = discover_server(args.env_id, args.service_name, timeout_seconds)
    if args.base_url:
        server["base_url"] = args.base_url.rstrip("/")
    endpoint_specs = [
        ("healthz", "/healthz"),
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
            "url_path": "/api/v1/weekly/current?limit=100",
            "status_code": None,
            "bytes_read": 0,
            "payload": {"_error": str(exc)[:240]},
        }
    responses["current"] = response
    summaries.insert(2, endpoint_summary("current", response))

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

    report = build_report(server, summaries)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.out_dir / "cloudrun_weekly_production_smoke.json", report)
    write_markdown(args.out_dir / "cloudrun_weekly_production_smoke.md", report)
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-id", default=ENV_ID)
    parser.add_argument("--service-name", default=SERVICE_NAME)
    parser.add_argument("--base-url", default="")
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument("--no-timeout", action="store_true", help="Disable CloudBase and HTTP request timeouts for this smoke.")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    report = run(parse_args(argv))
    print(json.dumps({"ok": report["ok"], "decision": report["decision"], "blockers": report["blockers"], "warnings": report["warnings"]}, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
