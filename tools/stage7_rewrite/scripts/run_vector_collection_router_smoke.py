#!/usr/bin/env python3
"""Read-only smoke for full vector collections in Qdrant.

This verifies vector collections by scrolling sample stored vectors and
searching each collection with its own vector. By default it keeps the legacy
Qwen3/Snowflake/English-sidecar route. When --role-report role=path is used,
it switches to the current role-isolated route such as multilingual_baseline,
ocr_baseline, english_sidecar, and snowflake_canary.

No model load, embedding call, Qdrant write, alias change, graph/DB write,
paid API call, publish, or D: scan.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import requests


SCHEMA_VERSION = "stage7_vector_collection_router_smoke.v1"
DEFAULT_OUT_DIR = Path("reports/vector_collection_router_smoke_20260518")
DEFAULT_QDRANT_URL = "http://127.0.0.1:6333"
DEFAULT_SNOWFLAKE_REPORT = Path("reports/vector_role_full_wave_20260518/snowflake_canary/qdrant_vector_role_full_wave_report.json")
DEFAULT_ENGLISH_REPORT = Path("reports/vector_role_full_wave_20260518/english_sidecar/qdrant_vector_role_full_wave_report.json")
QWEN_ALIASES = {
    "article": "wechat_stage7_article_qwen3_embedding_4b_1024_current",
    "entity": "wechat_stage7_entity_qwen3_embedding_4b_1024_current",
    "event": "wechat_stage7_event_qwen3_embedding_4b_1024_current",
}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def require_local_url(url: str, label: str) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError(f"{label} must be local: {url}")


def reject_d_root(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw in {"d:", "d:/", "/mnt/d", "/mnt/d/"} or raw.startswith("d:/ddownload") or raw.startswith("d:/aidata"):
        raise ValueError(f"{label} refuses broad D root: {path}")


def read_json(path: Path) -> dict[str, Any]:
    reject_d_root(path, "json")
    value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def norm_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/")


def classify_query_language(text: str) -> str:
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    if cjk and latin:
        return "mixed"
    if cjk:
        return "zh"
    if latin:
        return "en"
    return "unknown"


def route_channels(lang: str) -> list[str]:
    if lang == "zh":
        return ["qwen3_current", "snowflake_full_staging"]
    if lang == "en":
        return ["english_sidecar_full_staging", "qwen3_current"]
    if lang == "mixed":
        return ["qwen3_current", "snowflake_full_staging", "english_sidecar_full_staging"]
    return ["qwen3_current"]


def role_route_channels(lang: str) -> list[str]:
    if lang == "zh":
        return ["multilingual_baseline", "snowflake_canary", "ocr_baseline"]
    if lang == "en":
        return ["english_sidecar", "multilingual_baseline"]
    if lang == "mixed":
        return ["multilingual_baseline", "snowflake_canary", "english_sidecar", "ocr_baseline"]
    return ["multilingual_baseline"]


def collections_from_full_wave_report(path: Path) -> dict[str, str]:
    report = read_json(path)
    collections = ((report.get("state") or {}).get("collections") or (report.get("plan") or {}).get("collections") or {})
    if not isinstance(collections, dict) or not collections:
        raise ValueError(f"{path} does not contain full-wave collections")
    return {str(kind): str(name) for kind, name in collections.items()}


def collection_groups(snowflake_report: Path, english_report: Path) -> dict[str, dict[str, str]]:
    return {
        "qwen3_current": QWEN_ALIASES,
        "snowflake_full_staging": collections_from_full_wave_report(snowflake_report),
        "english_sidecar_full_staging": collections_from_full_wave_report(english_report),
    }


def collection_groups_with_qwen(
    snowflake_report: Path,
    english_report: Path,
    qwen_report: Path | None = None,
) -> dict[str, dict[str, str]]:
    groups = collection_groups(snowflake_report, english_report)
    if qwen_report is not None:
        groups["qwen3_current"] = collections_from_full_wave_report(qwen_report)
    return groups


def parse_role_report_arg(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise ValueError(f"--role-report must be role=path, got: {value}")
    role, path = value.split("=", 1)
    role = role.strip()
    if not role:
        raise ValueError(f"--role-report role is empty: {value}")
    return role, Path(path.strip())


def collection_groups_from_role_reports(values: list[str]) -> dict[str, dict[str, str]]:
    groups: dict[str, dict[str, str]] = {}
    for value in values:
        role, report_path = parse_role_report_arg(value)
        if role in groups:
            raise ValueError(f"duplicate --role-report role: {role}")
        groups[role] = collections_from_full_wave_report(report_path)
    if not groups:
        raise ValueError("at least one --role-report is required")
    return groups


def qdrant_scroll_vectors(qdrant_url: str, collection: str, limit: int, timeout_sec: int = 60) -> list[dict[str, Any]]:
    response = requests.post(
        f"{qdrant_url.rstrip('/')}/collections/{quote(collection)}/points/scroll",
        json={"limit": limit, "with_payload": True, "with_vector": True},
        params={"timeout": timeout_sec},
        timeout=timeout_sec,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Qdrant scroll failed {collection} {response.status_code}: {response.text[:500]}")
    points = (response.json().get("result") or {}).get("points") or []
    return [point for point in points if point.get("vector") is not None]


def qdrant_search(qdrant_url: str, collection: str, vector: Any, limit: int, timeout_sec: int = 60) -> list[dict[str, Any]]:
    response = requests.post(
        f"{qdrant_url.rstrip('/')}/collections/{quote(collection)}/points/search",
        json={"vector": vector, "limit": limit, "with_payload": True},
        params={"timeout": timeout_sec},
        timeout=timeout_sec,
    )
    if response.status_code == 404:
        response = requests.post(
            f"{qdrant_url.rstrip('/')}/collections/{quote(collection)}/points/query",
            json={"query": vector, "limit": limit, "with_payload": True},
            params={"timeout": timeout_sec},
            timeout=timeout_sec,
        )
    if response.status_code >= 400:
        raise RuntimeError(f"Qdrant search failed {collection} {response.status_code}: {response.text[:500]}")
    result = response.json().get("result")
    if isinstance(result, dict):
        result = result.get("points")
    return result or []


def payload_parent(payload: dict[str, Any], point_id: Any) -> str:
    return str(
        payload.get("parent_id")
        or payload.get("article_uid")
        or payload.get("card_id")
        or payload.get("object_id")
        or payload.get("job_id")
        or point_id
        or ""
    )


def normalize_hit(channel: str, kind: str, collection: str, rank: int, hit: dict[str, Any]) -> dict[str, Any]:
    payload = hit.get("payload") or {}
    return {
        "channel": channel,
        "kind": kind,
        "collection": collection,
        "rank": rank,
        "score": hit.get("score"),
        "point_id": str(hit.get("id") or ""),
        "parent_id": payload_parent(payload, hit.get("id")),
        "job_id": payload.get("job_id"),
        "card_id": payload.get("card_id"),
        "text_sha1": payload.get("text_sha1"),
        "field_path": payload.get("field_path"),
        "model": payload.get("model"),
        "label": payload.get("title") or payload.get("name") or payload.get("text") or "",
    }


def self_probe_match(expected_point_id: str, hits: list[dict[str, Any]], identity_score: float = 0.999) -> tuple[bool, str]:
    if any(str(hit.get("point_id") or "") == expected_point_id for hit in hits):
        return True, "exact_point_in_top_k"
    if hits:
        try:
            top_score = float(hits[0].get("score") or 0.0)
        except (TypeError, ValueError):
            top_score = 0.0
        if top_score >= identity_score:
            return True, "identity_duplicate_top1"
    return False, "miss"


def probe_collection(
    qdrant_url: str,
    channel: str,
    kind: str,
    collection: str,
    sample_size: int,
    top_k: int,
    timeout_sec: int = 60,
) -> dict[str, Any]:
    samples = qdrant_scroll_vectors(qdrant_url, collection, sample_size, timeout_sec=timeout_sec)
    probes = []
    matched = 0
    for point in samples:
        point_id = str(point.get("id"))
        vector = point.get("vector")
        hits = [
            normalize_hit(channel, kind, collection, rank, hit)
            for rank, hit in enumerate(qdrant_search(qdrant_url, collection, vector, top_k, timeout_sec=timeout_sec), start=1)
        ]
        ok, match_reason = self_probe_match(point_id, hits)
        matched += int(ok)
        probes.append(
            {
                "expected_point_id": point_id,
                "expected_parent_id": payload_parent(point.get("payload") or {}, point_id),
                "matched": ok,
                "match_reason": match_reason,
                "hits": hits,
            }
        )
    return {
        "channel": channel,
        "kind": kind,
        "collection": collection,
        "checked": len(probes),
        "matched": matched,
        "match_rate": round(matched / max(len(probes), 1), 4),
        "probes": probes,
    }


def rrf_fuse(channel_hits: dict[str, list[dict[str, Any]]], *, rrf_k: int = 60, limit: int = 10) -> list[dict[str, Any]]:
    fused: dict[str, dict[str, Any]] = {}
    for channel, hits in channel_hits.items():
        for hit in hits:
            parent = str(hit.get("parent_id") or f"{channel}:{hit.get('rank')}")
            row = fused.setdefault(parent, {"parent_id": parent, "rrf_score": 0.0, "channels": [], "best_hits": []})
            row["rrf_score"] += 1.0 / (rrf_k + int(hit.get("rank") or 0))
            if channel not in row["channels"]:
                row["channels"].append(channel)
            row["best_hits"].append(hit)
    rows = sorted(fused.values(), key=lambda item: item["rrf_score"], reverse=True)
    for index, row in enumerate(rows[:limit], start=1):
        row["fused_rank"] = index
        row["rrf_score"] = round(float(row["rrf_score"]), 6)
        row["best_hits"] = sorted(row["best_hits"], key=lambda hit: int(hit.get("rank") or 999))[:3]
    return rows[:limit]


def build_router_cases(
    channel_probes: dict[str, list[dict[str, Any]]],
    top_k: int,
    *,
    route_mode: str = "legacy",
) -> list[dict[str, Any]]:
    specs = [
        {"id": "zh_full_route", "query": "上海 电子音乐 俱乐部 活动 阵容"},
        {"id": "en_full_route", "query": "DJ SoundCloud Bandcamp profile"},
        {"id": "mixed_full_route", "query": "深圳 OIL CLUB 周末 lineup"},
        {"id": "poster_ocr_route", "query": "海报 OCR 阵容 poster lineup"},
    ]
    cases = []
    for spec in specs:
        lang = classify_query_language(spec["query"])
        channels = role_route_channels(lang) if route_mode == "role_isolated" else route_channels(lang)
        channels = [channel for channel in channels if channel in channel_probes]
        hits_by_channel: dict[str, list[dict[str, Any]]] = {}
        for channel in channels:
            hits = []
            for probe in channel_probes.get(channel, []):
                for item in (probe.get("probes") or [])[:top_k]:
                    hits.extend(item.get("hits") or [])
            hits_by_channel[channel] = hits[:top_k]
        cases.append({**spec, "lang": lang, "routed_channels": channels, "fused": rrf_fuse(hits_by_channel, limit=top_k)})
    return cases


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Vector Collection Router Smoke",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- ok: `{report['ok']}`",
        f"- decision: `{report['decision']}`",
        f"- sample_size_per_collection: `{report['sample_size_per_collection']}`",
        f"- top_k: `{report['top_k']}`",
        "",
        "## Channel Probes",
        "",
    ]
    for channel, probes in report["channel_probes"].items():
        for probe in probes:
            lines.append(
                f"- `{channel}` `{probe['kind']}` `{probe['matched']}/{probe['checked']}` "
                f"match_rate `{probe['match_rate']}` collection `{probe['collection']}`"
            )
    lines.extend(["", "## Router Cases", ""])
    for case in report["router_cases"]:
        lines.append(f"- `{case['id']}` lang `{case['lang']}` channels `{case['routed_channels']}` fused `{len(case['fused'])}`")
    lines.extend(["", "## Safety", ""])
    for key, value in sorted(report["safety"].items()):
        lines.append(f"- `{key}`: `{value}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    require_local_url(args.qdrant_url, "qdrant_url")
    if args.role_report:
        groups = collection_groups_from_role_reports(args.role_report)
        route_mode = "role_isolated"
    else:
        groups = collection_groups_with_qwen(args.snowflake_report, args.english_report, args.qwen_report)
        route_mode = "legacy"
    channel_probes: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for channel, collections in groups.items():
        for kind, collection in collections.items():
            channel_probes[channel].append(
                probe_collection(
                    args.qdrant_url,
                    channel,
                    kind,
                    collection,
                    args.sample_size_per_collection,
                    args.top_k,
                    timeout_sec=args.qdrant_timeout_sec,
                )
            )
    router_cases = build_router_cases(channel_probes, args.top_k, route_mode=route_mode)
    all_probes = [probe for probes in channel_probes.values() for probe in probes]
    ok = all(probe["checked"] > 0 and probe["match_rate"] == 1.0 for probe in all_probes) and all(
        case["fused"] for case in router_cases
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": ok,
        "decision": "vector_collection_router_smoke_ready" if ok else "vector_collection_router_smoke_needs_review",
        "qdrant_url": args.qdrant_url,
        "snowflake_report": norm_path(args.snowflake_report),
        "english_report": norm_path(args.english_report),
        "qwen_report": norm_path(args.qwen_report) if args.qwen_report else "",
        "role_reports": list(args.role_report or []),
        "route_mode": route_mode,
        "sample_size_per_collection": args.sample_size_per_collection,
        "top_k": args.top_k,
        "qdrant_timeout_sec": args.qdrant_timeout_sec,
        "collection_groups": groups,
        "channel_probes": dict(channel_probes),
        "router_cases": router_cases,
        "safety": {
            "model_loaded": False,
            "embedding_call_executed": False,
            "qdrant_write_executed": False,
            "qdrant_alias_change_executed": False,
            "neo4j_write_executed": False,
            "sqlite_write_executed": False,
            "mem0_write_executed": False,
            "paid_api_used": False,
            "production_publish_executed": False,
            "d_scan_executed": False,
        },
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    report_path = args.out_dir / "vector_collection_router_smoke.json"
    md_path = args.out_dir / "vector_collection_router_smoke.md"
    write_json(report_path, report)
    write_markdown(md_path, report)
    print(
        json.dumps(
            {"ok": report["ok"], "decision": report["decision"], "report": str(report_path)},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if ok else 2


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qdrant-url", default=DEFAULT_QDRANT_URL)
    parser.add_argument("--snowflake-report", type=Path, default=DEFAULT_SNOWFLAKE_REPORT)
    parser.add_argument("--english-report", type=Path, default=DEFAULT_ENGLISH_REPORT)
    parser.add_argument("--qwen-report", type=Path, default=None, help="Optional qdrant_full_staging_report.json for a pre-alias Qwen3 staging collection set.")
    parser.add_argument(
        "--role-report",
        action="append",
        default=[],
        help="Current role-isolated full-wave report as role=path. May be repeated.",
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--sample-size-per-collection", type=int, default=3)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--qdrant-timeout-sec", type=int, default=60)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
