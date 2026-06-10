#!/usr/bin/env python3
"""Probe current and candidate Mac vector embedding endpoints.

This is a read-only endpoint health and dimension probe. It sends one small
OpenAI-compatible ``/v1/embeddings`` request per route and writes a JSON/MD
report. It does not write Qdrant, Neo4j, SQLite, Mem0, or production data.
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import requests


@dataclass(frozen=True)
class ProbeRoute:
    port: int
    model: str
    expected_dim: int
    role: str


DEFAULT_ROUTES = (
    ProbeRoute(11437, "stella-large-zh-v2", 1024, "current_default"),
    ProbeRoute(11435, "bge-m3", 1024, "fallback"),
    ProbeRoute(11436, "stella_en", 1536, "english_only"),
    ProbeRoute(11438, "stella-base-zh", 768, "zh_prefilter"),
    ProbeRoute(11439, "stella-mrl-large-zh-v3.5-1792d", 1024, "candidate_stella_v35"),
    ProbeRoute(11440, "Qwen/Qwen3-Embedding-0.6B", 1024, "candidate_qwen3_0_6b"),
    ProbeRoute(11441, "Qwen/Qwen3-Embedding-4B", 2560, "candidate_qwen3_4b"),
    ProbeRoute(11442, "jinaai/jina-embeddings-v5-text-small", 1024, "candidate_jina_v5_small"),
)


def parse_route_spec(spec: str) -> ProbeRoute:
    parts = [part.strip() for part in spec.split("|")]
    if len(parts) != 4:
        raise ValueError("route spec must be port|model|expected_dim|role")
    return ProbeRoute(port=int(parts[0]), model=parts[1], expected_dim=int(parts[2]), role=parts[3])


def probe_route(
    host: str,
    route: ProbeRoute,
    *,
    timeout_sec: float,
    input_text: str,
    post: Callable[..., Any] = requests.post,
) -> dict[str, Any]:
    url = f"http://{host}:{route.port}/v1/embeddings"
    started = time.perf_counter()
    row: dict[str, Any] = {
        "port": route.port,
        "model": route.model,
        "expected_dim": route.expected_dim,
        "role": route.role,
        "url": url,
    }
    try:
        response = post(url, json={"model": route.model, "input": [input_text]}, timeout=timeout_sec)
        row["status_code"] = int(response.status_code)
        row["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
        if response.ok:
            payload = response.json()
            embedding = (payload.get("data") or [{}])[0].get("embedding")
            row["dim"] = len(embedding) if isinstance(embedding, list) else None
            row["dim_ok"] = row["dim"] == route.expected_dim
            row["response_model"] = payload.get("model") or (payload.get("_local") or {}).get("model_id")
            row["device"] = (payload.get("_local") or {}).get("device")
        else:
            row["error_preview"] = str(response.text)[:300].replace("\n", " ")
    except Exception as exc:  # pragma: no cover - exercised in integration probes
        row["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
        row["error"] = f"{type(exc).__name__}: {str(exc)[:260]}"
    return row


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    rows = report["rows"]
    lines = [
        "# Stage8 Vector Model Endpoint Probe",
        "",
        f"- checked_at: `{report['checked_at']}`",
        f"- host: `{report['host']}`",
        f"- writes: `none; embedding endpoint probe only`",
        "",
        "| port | role | model | expected | status | dim | dim_ok | latency_ms | note |",
        "|---:|---|---|---:|---:|---:|---|---:|---|",
    ]
    for row in rows:
        note = row.get("error") or row.get("error_preview") or row.get("response_model") or ""
        lines.append(
            "| {port} | {role} | `{model}` | {expected_dim} | {status} | {dim} | {dim_ok} | {latency} | {note} |".format(
                port=row.get("port", ""),
                role=row.get("role", ""),
                model=row.get("model", ""),
                expected_dim=row.get("expected_dim", ""),
                status=row.get("status_code", ""),
                dim=row.get("dim", ""),
                dim_ok=row.get("dim_ok", ""),
                latency=row.get("latency_ms", ""),
                note=str(note).replace("|", "/"),
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    routes = list(DEFAULT_ROUTES)
    for spec in args.extra_route:
        routes.append(parse_route_spec(spec))
    rows = [
        probe_route(args.host, route, timeout_sec=args.timeout_sec, input_text=args.input_text)
        for route in routes
    ]
    return {
        "schema_version": "stage8_vector_model_endpoint_probe.v1",
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "host": args.host,
        "input_text_sha1": __import__("hashlib").sha1(args.input_text.encode("utf-8")).hexdigest(),
        "rows": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="192.168.8.234")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--timeout-sec", type=float, default=8.0)
    parser.add_argument("--input-text", default="地下电子音乐地图向量模型候选探针：DADA Shanghai, ALL Club, techno event")
    parser.add_argument(
        "--extra-route",
        action="append",
        default=[],
        help="Additional route as port|model|expected_dim|role",
    )
    args = parser.parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = build_report(args)
    json_path = out_dir / "model_endpoint_probe.json"
    md_path = out_dir / "model_endpoint_probe.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(md_path, report)
    print(json.dumps({"ok": True, "json": str(json_path), "markdown": str(md_path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
