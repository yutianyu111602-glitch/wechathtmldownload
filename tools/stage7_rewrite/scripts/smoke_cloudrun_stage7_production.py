#!/usr/bin/env python3
"""Smoke-test the deployed CloudRun Stage7 atlas API.

This is a production read-only smoke. It discovers the current CloudRun public
domain through CloudBase server detail unless --base-url is provided, then checks
the Stage7 atlas endpoints that are expected to serve the full release pack.
It does not call LLM providers, paid OCR APIs, databases, Qdrant, Neo4j, or mem0.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


ENV_ID = "huaidjweekly-d8g1go7-d0a07863e3e"
SERVICE_NAME = "weekly-api"
DEFAULT_OUT_DIR = Path("reports/cloudrun_stage7_production_smoke_20260518")
TCB_CWD = Path(r"C:\code\githubstar\wechathtmldownload\services\weekly_activity_cloudrun")
TCB_CMD = [shutil.which("npm") or "npm", "exec", "--yes", "--package", "@cloudbase/cli@3.3.1", "--", "tcb"]
EXPECTED_COUNTS = {"articles": 138102, "entities": 1510787, "events": 608678}


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


def tcb_api(action: str, body: dict[str, Any]) -> dict[str, Any]:
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
    result = subprocess.run(cmd, cwd=TCB_CWD, capture_output=True, text=True, timeout=240)
    payload = parse_first_json_object((result.stdout or "") + "\n" + (result.stderr or ""))
    if result.returncode != 0:
        raise RuntimeError(f"CloudBase API {action} failed with returncode={result.returncode}")
    data = payload.get("data")
    return data if isinstance(data, dict) else payload


def discover_server(env_id: str, service_name: str) -> dict[str, Any]:
    data = tcb_api("DescribeCloudRunServerDetail", {"EnvId": env_id, "ServerName": service_name})
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


def get_json(base_url: str, path: str, timeout: int) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}{path}"
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "stage7-production-smoke/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read(2_000_000)
        text = raw.decode("utf-8", errors="replace")
        payload = json.loads(text)
        if not isinstance(payload, dict):
            payload = {"value": payload}
        return {
            "url_path": path,
            "status_code": response.status,
            "content_type": response.headers.get("content-type", ""),
            "bytes_read": len(raw),
            "payload": payload,
        }


def get_html(base_url: str, path: str, timeout: int) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}{path}"
    request = urllib.request.Request(url, headers={"Accept": "text/html", "User-Agent": "stage7-production-smoke/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read(2_000_000)
        text = raw.decode("utf-8", errors="replace")
        return {
            "url_path": path,
            "status_code": response.status,
            "content_type": response.headers.get("content-type", ""),
            "bytes_read": len(raw),
            "text": text,
        }


def endpoint_summary(name: str, response: dict[str, Any]) -> dict[str, Any]:
    payload = response["payload"]
    summary: dict[str, Any] = {
        "name": name,
        "url_path": response["url_path"],
        "status_code": response["status_code"],
        "json_object": isinstance(payload, dict),
    }
    if name == "healthz":
        summary.update({"ok_field": payload.get("ok"), "service": payload.get("service")})
    elif name == "manifest":
        counts = payload.get("counts") if isinstance(payload.get("counts"), dict) else {}
        summary.update(
            {
                "release_ready": payload.get("releaseReady"),
                "decision": payload.get("decision"),
                "counts": {key: counts.get(key) for key in EXPECTED_COUNTS},
            }
        )
    elif name == "search":
        retrieval = payload.get("retrieval") if isinstance(payload.get("retrieval"), dict) else {}
        summary.update(
            {
                "result_count": payload.get("resultCount"),
                "retrieval_mode": retrieval.get("mode"),
                "live_vector_search_enabled": retrieval.get("liveVectorSearchEnabled"),
            }
        )
    elif name == "recommendations":
        safety = payload.get("safety") if isinstance(payload.get("safety"), dict) else {}
        summary.update(
            {
                "recommendation_count": payload.get("recommendationCount"),
                "decision": payload.get("decision"),
                "model_call_executed": safety.get("modelCallExecuted"),
                "mem0_write_executed": safety.get("mem0WriteExecuted"),
            }
        )
    elif name == "graph_rag":
        summary.update({"answer_count": payload.get("answerCount"), "llm_call_executed": payload.get("llmCallExecuted")})
    elif name == "vector_router":
        summary.update(
            {
                "ok_field": payload.get("ok"),
                "decision": payload.get("decision"),
                "sample_size_per_collection": payload.get("sampleSizePerCollection"),
            }
        )
    elif name == "overview":
        counts = payload.get("counts") if isinstance(payload.get("counts"), dict) else {}
        surfaces = payload.get("browsingSurfaces") if isinstance(payload.get("browsingSurfaces"), list) else []
        service = payload.get("serviceIntegration") if isinstance(payload.get("serviceIntegration"), dict) else {}
        safety = payload.get("safety") if isinstance(payload.get("safety"), dict) else {}
        summary.update(
            {
                "counts": {key: counts.get(key) for key in EXPECTED_COUNTS},
                "surface_count": len(surfaces),
                "live_vector_search_enabled": service.get("liveVectorSearchEnabled"),
                "llm_call_executed": safety.get("llmCallExecuted"),
                "qdrant_write_executed": safety.get("qdrantWriteExecuted"),
            }
        )
    elif name == "identity_review":
        summary_payload = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
        page = payload.get("page") if isinstance(payload.get("page"), dict) else {}
        safety = payload.get("safety") if isinstance(payload.get("safety"), dict) else {}
        summary.update(
            {
                "decision": payload.get("decision"),
                "item_count": summary_payload.get("itemCount"),
                "accepted_for_graph": summary_payload.get("acceptedForGraph"),
                "returned": page.get("returned"),
                "graph_write_executed": safety.get("graphWriteExecuted"),
                "network_call_executed": safety.get("networkCallExecuted"),
                "model_call_executed": safety.get("modelCallExecuted"),
            }
        )
    elif name == "entity_list":
        items = payload.get("items") if isinstance(payload.get("items"), list) else []
        first = items[0] if items and isinstance(items[0], dict) else {}
        summary.update({"returned": len(items), "first_entity_id": first.get("eid", "")})
    elif name == "entity_detail":
        related = payload.get("related") if isinstance(payload.get("related"), dict) else {}
        safety = payload.get("safety") if isinstance(payload.get("safety"), dict) else {}
        source_article = related.get("sourceArticle") if isinstance(related.get("sourceArticle"), dict) else None
        events = related.get("events") if isinstance(related.get("events"), list) else []
        summary.update(
            {
                "schema_version": payload.get("schemaVersion"),
                "kind": payload.get("kind"),
                "primary_id": payload.get("primaryId"),
                "matched_by": payload.get("matchedBy"),
                "has_source_article": source_article is not None,
                "related_event_count": len(events),
                "llm_call_executed": safety.get("llmCallExecuted"),
                "qdrant_write_executed": safety.get("qdrantWriteExecuted"),
                "neo4j_write_executed": safety.get("neo4jWriteExecuted"),
                "mem0_write_executed": safety.get("mem0WriteExecuted"),
            }
        )
    return summary


def html_endpoint_summary(name: str, response: dict[str, Any]) -> dict[str, Any]:
    text = response.get("text") or ""
    if name == "identity_page":
        title = "图鉴身份审阅"
    elif name == "detail_page":
        title = "图鉴详情"
    else:
        title = "中国地下电子音乐图鉴"
    return {
        "name": name,
        "url_path": response["url_path"],
        "status_code": response["status_code"],
        "content_type": response.get("content_type", ""),
        "bytes_read": response.get("bytes_read", 0),
        "html_document": "<!doctype html>" in text.lower(),
        "contains_title": title in text,
        "contains_overview_api": "/api/v1/stage7/overview" in text,
        "contains_identity_api": "/api/v1/stage7/identity-review" in text,
        "contains_detail_api": "/api/v1/stage7/" in text,
    }


def endpoint_ok(name: str, summary: dict[str, Any]) -> bool:
    if name == "atlas_page":
        return (
            summary.get("status_code") == 200
            and "text/html" in str(summary.get("content_type") or "")
            and summary.get("html_document") is True
            and summary.get("contains_title") is True
            and summary.get("contains_overview_api") is True
        )
    if name == "identity_page":
        return (
            summary.get("status_code") == 200
            and "text/html" in str(summary.get("content_type") or "")
            and summary.get("html_document") is True
            and summary.get("contains_title") is True
            and summary.get("contains_identity_api") is True
        )
    if name == "detail_page":
        return (
            summary.get("status_code") == 200
            and "text/html" in str(summary.get("content_type") or "")
            and summary.get("html_document") is True
            and summary.get("contains_title") is True
            and summary.get("contains_detail_api") is True
        )
    if summary.get("status_code") != 200 or not summary.get("json_object"):
        return False
    if name == "healthz":
        return summary.get("ok_field") is True and summary.get("service") == SERVICE_NAME
    if name == "manifest":
        counts = summary.get("counts") or {}
        return bool(summary.get("release_ready")) and all(int(counts.get(key) or 0) >= expected for key, expected in EXPECTED_COUNTS.items())
    if name == "search":
        return int(summary.get("result_count") or 0) > 0 and summary.get("retrieval_mode") == "materialized_text_scan"
    if name == "recommendations":
        return int(summary.get("recommendation_count") or 0) > 0 and summary.get("model_call_executed") is False
    if name == "graph_rag":
        return int(summary.get("answer_count") or 0) > 0 and summary.get("llm_call_executed") is False
    if name == "vector_router":
        return summary.get("ok_field") is True and summary.get("decision") == "vector_collection_router_smoke_ready"
    if name == "overview":
        counts = summary.get("counts") or {}
        return (
            all(int(counts.get(key) or 0) >= expected for key, expected in EXPECTED_COUNTS.items())
            and int(summary.get("surface_count") or 0) >= 4
            and summary.get("live_vector_search_enabled") is False
            and summary.get("llm_call_executed") is False
            and summary.get("qdrant_write_executed") is False
        )
    if name == "identity_review":
        return (
            summary.get("decision") == "identity_review_workbench_ready_read_only"
            and int(summary.get("item_count") or 0) > 0
            and int(summary.get("returned") or 0) > 0
            and int(summary.get("accepted_for_graph") or 0) == 0
            and summary.get("graph_write_executed") is False
            and summary.get("network_call_executed") is False
            and summary.get("model_call_executed") is False
        )
    if name == "entity_list":
        return int(summary.get("returned") or 0) > 0 and bool(summary.get("first_entity_id"))
    if name == "entity_detail":
        return (
            summary.get("schema_version") == "stage7_atlas_api.detail_response.v1"
            and summary.get("kind") == "entities"
            and bool(summary.get("primary_id"))
            and summary.get("llm_call_executed") is False
            and summary.get("qdrant_write_executed") is False
            and summary.get("neo4j_write_executed") is False
            and summary.get("mem0_write_executed") is False
        )
    return False


def build_report(server: dict[str, Any], endpoint_summaries: list[dict[str, Any]]) -> dict[str, Any]:
    endpoint_results = []
    for item in endpoint_summaries:
        ok = endpoint_ok(str(item.get("name")), item)
        endpoint_results.append({**item, "ok": ok})
    blockers = [str(item["name"]) for item in endpoint_results if not item["ok"]]
    if not server.get("base_url"):
        blockers.append("missing_default_domain_name")
    if server.get("status") != "normal":
        blockers.append("cloudrun_server_not_normal")
    if str(server.get("active_flow_ratio")) != "100":
        blockers.append("active_version_not_100_flow")
    ok = not blockers
    return {
        "schema_version": "stage7_cloudrun_production_smoke.v1",
        "generated_at": now_iso(),
        "ok": ok,
        "decision": "cloudrun_stage7_production_smoke_ready" if ok else "cloudrun_stage7_production_smoke_blocked",
        "server": server,
        "expected_counts": EXPECTED_COUNTS,
        "endpoints": endpoint_results,
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
        "# CloudRun Stage7 Production Smoke",
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
    lines.extend(["", "## Blockers", ""])
    lines.extend([f"- `{item}`" for item in report["blockers"]] or ["- none"])
    lines.extend(["", "## Safety", "", "- Read-only HTTP/API smoke. No LLM, paid API, DB/vector/graph/mem0 write, or D: scan."])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.base_url:
        server = {
            "base_url": args.base_url.rstrip("/"),
            "status": "normal",
            "update_time": "",
            "access_types": ["manual_base_url"],
            "active_version": "manual_base_url",
            "active_flow_ratio": "100",
            "request_id": "",
        }
    else:
        server = discover_server(args.env_id, args.service_name)
    summaries = []
    detail_entity_id = ""
    entity_list_path = "/api/v1/stage7/entities?limit=1"
    try:
        entity_list_response = get_json(server["base_url"], entity_list_path, args.timeout_seconds)
        entity_list_payload = entity_list_response.get("payload") if isinstance(entity_list_response.get("payload"), dict) else {}
        entity_items = entity_list_payload.get("items") if isinstance(entity_list_payload.get("items"), list) else []
        if entity_items and isinstance(entity_items[0], dict):
            detail_entity_id = str(entity_items[0].get("eid") or "")
        summaries.append(endpoint_summary("entity_list", entity_list_response))
    except Exception as exc:  # noqa: BLE001
        summaries.append({"name": "entity_list", "url_path": entity_list_path, "status_code": None, "json_object": False, "error": str(exc)[:240]})
    endpoints = [
        ("healthz", "json", "/healthz"),
        ("manifest", "json", "/api/v1/stage7/manifest"),
        ("search", "json", f"/api/v1/stage7/search?{urllib.parse.urlencode({'q': args.query, 'limit': 3})}"),
        ("overview", "json", "/api/v1/stage7/overview?sampleLimit=40"),
        ("identity_review", "json", "/api/v1/stage7/identity-review?limit=20"),
        ("recommendations", "json", "/api/v1/stage7/recommendations?limit=1"),
        ("graph_rag", "json", "/api/v1/stage7/graph-rag/answers?limit=1"),
        ("vector_router", "json", "/api/v1/stage7/vector-router/status"),
        ("atlas_page", "html", "/atlas"),
        ("identity_page", "html", "/atlas/identity"),
    ]
    if detail_entity_id:
        encoded_entity_id = urllib.parse.quote(detail_entity_id, safe="")
        endpoints.extend(
            [
                ("entity_detail", "json", f"/api/v1/stage7/entities/{encoded_entity_id}?relatedLimit=8"),
                ("detail_page", "html", f"/atlas/entities/{encoded_entity_id}"),
            ]
        )
    else:
        summaries.append(
            {
                "name": "entity_detail",
                "url_path": "/api/v1/stage7/entities/<first>",
                "status_code": None,
                "json_object": False,
                "error": "entity_list_returned_no_eid",
            }
        )
        summaries.append(
            {
                "name": "detail_page",
                "url_path": "/atlas/entities/<first>",
                "status_code": None,
                "content_type": "",
                "html_document": False,
                "contains_title": False,
                "contains_detail_api": False,
                "error": "entity_list_returned_no_eid",
            }
        )
    for name, mode, path in endpoints:
        try:
            if mode == "html":
                summaries.append(html_endpoint_summary(name, get_html(server["base_url"], path, args.timeout_seconds)))
            else:
                summaries.append(endpoint_summary(name, get_json(server["base_url"], path, args.timeout_seconds)))
        except Exception as exc:  # noqa: BLE001
            summaries.append({"name": name, "url_path": path, "status_code": None, "json_object": False, "error": str(exc)[:240]})
    report = build_report(server, summaries)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.out_dir / "cloudrun_stage7_production_smoke.json", report)
    write_markdown(args.out_dir / "cloudrun_stage7_production_smoke.md", report)
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-id", default=ENV_ID)
    parser.add_argument("--service-name", default=SERVICE_NAME)
    parser.add_argument("--base-url", default="")
    parser.add_argument("--query", default="dada")
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    report = run(parse_args(argv))
    print(json.dumps({"ok": report["ok"], "decision": report["decision"], "blockers": report["blockers"]}, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
