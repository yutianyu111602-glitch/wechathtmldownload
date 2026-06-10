#!/usr/bin/env python3
"""Smoke-test vector router mechanics across Qwen3 control and role canaries.

This is a read-only smoke. It verifies local Qdrant channel access, language
route decisions, RRF fusion, and parent collapse using existing vectors as
self-probes. It does not load embedding models, write stores, promote aliases,
call paid APIs, publish, or scan D:.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import numpy as np
import requests


DEFAULT_VECTOR_DIR = Path("reports/vector_full_qwen3_4b_1024_20260514")
DEFAULT_SNOWFLAKE_EMBEDDINGS = Path("reports/vector_role_embedding_canary_20260518/snowflake_canary/embeddings.jsonl")
DEFAULT_ENGLISH_EMBEDDINGS = Path("reports/vector_role_embedding_canary_20260518/english_sidecar/embeddings.jsonl")
DEFAULT_OUT_DIR = Path("reports/vector_router_smoke_20260518")
DEFAULT_QDRANT_URL = "http://127.0.0.1:6333"
SCHEMA_VERSION = "stage7_vector_router_smoke.v1"

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
        raise ValueError(f"{label} must be local for vector router smoke: {url}")


def reject_d_root(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw in {"d:", "d:/", "/mnt/d", "/mnt/d/"} or raw.startswith("d:/ddownload") or raw.startswith("d:/aidata"):
        raise ValueError(f"{label} refuses broad D root: {path}")


def read_jsonl(path: Path, limit: int = 0) -> list[dict[str, Any]]:
    reject_d_root(path, "jsonl")
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            rows.append(json.loads(stripped))
            if limit and len(rows) >= limit:
                break
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def text_sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()


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
        return ["qwen3_current", "snowflake_canary"]
    if lang == "en":
        return ["english_sidecar", "qwen3_current"]
    if lang == "mixed":
        return ["qwen3_current", "snowflake_canary", "english_sidecar"]
    return ["qwen3_current"]


def qdrant_search(qdrant_url: str, collection: str, vector: list[float], limit: int) -> list[dict[str, Any]]:
    response = requests.post(
        f"{qdrant_url.rstrip('/')}/collections/{quote(collection)}/points/search",
        json={"vector": vector, "limit": limit, "with_payload": True},
        timeout=60,
    )
    if response.status_code == 404:
        response = requests.post(
            f"{qdrant_url.rstrip('/')}/collections/{quote(collection)}/points/query",
            json={"query": vector, "limit": limit, "with_payload": True},
            timeout=60,
        )
    if response.status_code >= 400:
        raise RuntimeError(f"Qdrant search failed {response.status_code}: {response.text[:500]}")
    result = response.json().get("result")
    if isinstance(result, dict):
        result = result.get("points")
    return result or []


def iter_qwen_rows(vector_dir: Path, limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with (vector_dir / "card_texts.jsonl").open("r", encoding="utf-8") as handle:
        for idx, line in enumerate(handle):
            if not line.strip():
                continue
            row = json.loads(line)
            if str(row.get("type") or "") not in QWEN_ALIASES:
                continue
            row["_vector_index"] = idx
            rows.append(row)
            if len(rows) >= limit:
                break
    return rows


def normalize_hit(channel: str, collection: str, rank: int, hit: dict[str, Any]) -> dict[str, Any]:
    payload = hit.get("payload") or {}
    parent_id = (
        payload.get("parent_id")
        or payload.get("article_uid")
        or payload.get("card_id")
        or payload.get("object_id")
        or payload.get("job_id")
        or hit.get("id")
    )
    return {
        "channel": channel,
        "collection": collection,
        "rank": rank,
        "score": hit.get("score"),
        "parent_id": str(parent_id or ""),
        "job_id": payload.get("job_id"),
        "card_id": payload.get("card_id"),
        "text_sha1": payload.get("text_sha1"),
        "field_path": payload.get("field_path"),
        "model": payload.get("model"),
        "label": payload.get("title") or payload.get("name") or payload.get("text") or "",
    }


def rrf_fuse(channel_hits: dict[str, list[dict[str, Any]]], *, rrf_k: int = 60, limit: int = 10) -> list[dict[str, Any]]:
    fused: dict[str, dict[str, Any]] = {}
    for channel, hits in channel_hits.items():
        for hit in hits:
            parent = hit.get("parent_id") or f"{channel}:{hit.get('rank')}"
            item = fused.setdefault(
                parent,
                {
                    "parent_id": parent,
                    "rrf_score": 0.0,
                    "channels": [],
                    "best_hits": [],
                },
            )
            item["rrf_score"] += 1.0 / (rrf_k + int(hit.get("rank") or 0))
            if channel not in item["channels"]:
                item["channels"].append(channel)
            item["best_hits"].append(hit)
    rows = sorted(fused.values(), key=lambda item: item["rrf_score"], reverse=True)
    for index, row in enumerate(rows[:limit], start=1):
        row["fused_rank"] = index
        row["rrf_score"] = round(float(row["rrf_score"]), 6)
        row["best_hits"] = sorted(row["best_hits"], key=lambda hit: int(hit.get("rank") or 999))[:3]
    return rows[:limit]


def qwen_self_probe(qdrant_url: str, vector_dir: Path, probe_count: int, top_k: int) -> dict[str, Any]:
    rows = iter_qwen_rows(vector_dir, probe_count)
    vectors = np.load(vector_dir / "vectors.npy", mmap_mode="r")
    probes = []
    matched = 0
    for row in rows:
        kind = str(row.get("type") or "")
        collection = QWEN_ALIASES[kind]
        vector = np.asarray(vectors[int(row["_vector_index"])], dtype="float32").tolist()
        hits = [normalize_hit("qwen3_current", collection, rank, hit) for rank, hit in enumerate(qdrant_search(qdrant_url, collection, vector, top_k), start=1)]
        first = hits[0] if hits else {}
        expected_sha1 = text_sha1(str(row.get("text") or ""))
        ok = first.get("card_id") == row.get("id") or first.get("text_sha1") == expected_sha1
        matched += int(ok)
        probes.append({"expected_id": row.get("id"), "collection": collection, "matched": ok, "hits": hits})
    return {
        "channel": "qwen3_current",
        "checked": len(probes),
        "matched": matched,
        "match_rate": round(matched / max(len(probes), 1), 4),
        "probes": probes,
    }


def role_self_probe(qdrant_url: str, embeddings_path: Path, channel: str, probe_count: int, top_k: int) -> dict[str, Any]:
    rows = read_jsonl(embeddings_path, limit=probe_count)
    probes = []
    matched = 0
    for row in rows:
        collection = str(row.get("collection") or "")
        hits = [normalize_hit(channel, collection, rank, hit) for rank, hit in enumerate(qdrant_search(qdrant_url, collection, row["vector"], top_k), start=1)]
        first = hits[0] if hits else {}
        ok = first.get("job_id") == row.get("job_id") or first.get("text_sha1") == row.get("text_sha1")
        matched += int(ok)
        probes.append({"expected_id": row.get("job_id"), "collection": collection, "matched": ok, "hits": hits})
    return {
        "channel": channel,
        "checked": len(probes),
        "matched": matched,
        "match_rate": round(matched / max(len(probes), 1), 4),
        "probes": probes,
    }


def build_router_cases(probes_by_channel: dict[str, dict[str, Any]], top_k: int) -> list[dict[str, Any]]:
    case_specs = [
        {"id": "zh_route", "query": "上海 电子音乐 俱乐部 活动 阵容"},
        {"id": "en_route", "query": "DJ SoundCloud Bandcamp profile"},
        {"id": "mixed_route", "query": "深圳 OIL CLUB 周末 lineup"},
    ]
    cases = []
    for spec in case_specs:
        lang = classify_query_language(spec["query"])
        channels = route_channels(lang)
        channel_hits: dict[str, list[dict[str, Any]]] = {}
        for channel in channels:
            probe = probes_by_channel.get(channel) or {}
            hits = []
            for item in (probe.get("probes") or [])[:top_k]:
                hits.extend(item.get("hits") or [])
            channel_hits[channel] = hits[:top_k]
        cases.append(
            {
                **spec,
                "lang": lang,
                "routed_channels": channels,
                "fused": rrf_fuse(channel_hits, limit=top_k),
            }
        )
    return cases


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Vector Router Smoke",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- ok: `{report['ok']}`",
        f"- probe_count: `{report['probe_count']}`",
        "",
        "## Channel Self-Probes",
        "",
    ]
    for channel, probe in report["channel_probes"].items():
        lines.append(f"- `{channel}`: `{probe['matched']}/{probe['checked']}` match_rate `{probe['match_rate']}`")
    lines.extend(["", "## Router Cases", ""])
    for case in report["router_cases"]:
        lines.append(f"- `{case['id']}` lang `{case['lang']}` channels `{case['routed_channels']}` fused `{len(case['fused'])}`")
    lines.extend(["", "## Safety", ""])
    for key, value in sorted(report["safety"].items()):
        lines.append(f"- `{key}`: `{value}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    require_local_url(args.qdrant_url, "Qdrant URL")
    probes = {
        "qwen3_current": qwen_self_probe(args.qdrant_url, args.vector_dir, args.probe_count, args.top_k),
        "snowflake_canary": role_self_probe(args.qdrant_url, args.snowflake_embeddings, "snowflake_canary", args.probe_count, args.top_k),
        "english_sidecar": role_self_probe(args.qdrant_url, args.english_embeddings, "english_sidecar", args.probe_count, args.top_k),
    }
    cases = build_router_cases(probes, args.top_k)
    ok = all(probe["checked"] > 0 and probe["match_rate"] == 1.0 for probe in probes.values()) and all(
        case["fused"] for case in cases
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": ok,
        "decision": "vector_router_smoke_ready" if ok else "vector_router_smoke_needs_review",
        "qdrant_url": args.qdrant_url,
        "vector_dir": str(args.vector_dir),
        "snowflake_embeddings": str(args.snowflake_embeddings),
        "english_embeddings": str(args.english_embeddings),
        "probe_count": args.probe_count,
        "top_k": args.top_k,
        "channel_probes": probes,
        "router_cases": cases,
        "scope_note": "Self-probe verifies channel access/router mechanics only; hard-query semantic ranking still requires query embedding evaluation.",
        "safety": {
            "model_loaded": False,
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
    write_json(args.out_dir / "vector_router_smoke.json", report)
    write_markdown(args.out_dir / "vector_router_smoke.md", report)
    print(
        json.dumps(
            {"ok": report["ok"], "decision": report["decision"], "report": str(args.out_dir / "vector_router_smoke.json")},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if ok else 2


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vector-dir", type=Path, default=DEFAULT_VECTOR_DIR)
    parser.add_argument("--snowflake-embeddings", type=Path, default=DEFAULT_SNOWFLAKE_EMBEDDINGS)
    parser.add_argument("--english-embeddings", type=Path, default=DEFAULT_ENGLISH_EMBEDDINGS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--qdrant-url", default=DEFAULT_QDRANT_URL)
    parser.add_argument("--probe-count", type=int, default=5)
    parser.add_argument("--top-k", type=int, default=5)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
