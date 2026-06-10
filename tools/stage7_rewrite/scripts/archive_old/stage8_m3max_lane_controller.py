#!/usr/bin/env python3
"""Plan and benchmark Mac M3 Max vector lanes.

This controller is deliberately read-only with respect to project data stores.
It may call OpenAI-compatible embedding endpoints and write local evidence
reports, but it does not write Qdrant, Neo4j, SQLite, Mem0, or Stage7 roots.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

import requests


@dataclass(frozen=True)
class EndpointSpec:
    host: str
    port: int
    model: str
    expected_dim: int

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/v1/embeddings"


@dataclass(frozen=True)
class LanePlan:
    lane_id: str
    purpose: str
    default_route: str
    max_parallelism: str
    runs_when: str
    stop_gate: str


def parse_int_list(value: str) -> list[int]:
    items = [int(part.strip()) for part in value.split(",") if part.strip()]
    if not items:
        raise ValueError("at least one integer is required")
    if any(item < 1 for item in items):
        raise ValueError("all integers must be >= 1")
    return items


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * q))))
    return round(ordered[idx], 2)


def synthetic_texts(count: int, prefix: str) -> list[str]:
    seeds = [
        "DADA Shanghai techno event venue account artist relation",
        "ALL Club 上海 underground electronic music map entity card",
        "Lantern Beijing promoter event source evidence",
        "Oil Shenzhen bass night artist lineup source quote",
        "Elevator Shanghai label venue city relation",
        "Abyss Shanghai OCR poster account profile",
        "The Window Guangzhou electronic music venue",
        "TAG Chengdu party promoter event",
    ]
    texts: list[str] = []
    for idx in range(count):
        seed = seeds[idx % len(seeds)]
        texts.append(f"{prefix} #{idx:05d}\n卡片: {seed}\n证据: 地下电子音乐地图向量吞吐压测样本文本。")
    return texts


class BenchError(RuntimeError):
    pass


def embed_once(
    endpoint: EndpointSpec,
    texts: list[str],
    *,
    timeout_sec: float,
    post: Callable[..., Any] = requests.post,
) -> dict[str, Any]:
    started = time.perf_counter()
    response = post(endpoint.url, json={"model": endpoint.model, "input": texts}, timeout=timeout_sec)
    latency_ms = round((time.perf_counter() - started) * 1000, 2)
    if not response.ok:
        return {
            "ok": False,
            "latency_ms": latency_ms,
            "status_code": int(response.status_code),
            "error": str(getattr(response, "text", ""))[:300],
            "vectors": 0,
            "dim_mismatch": len(texts),
        }
    payload = response.json()
    data = payload.get("data") or []
    dims = [len(row.get("embedding") or []) for row in data]
    mismatches = [dim for dim in dims if dim != endpoint.expected_dim]
    return {
        "ok": not mismatches and len(data) == len(texts),
        "latency_ms": latency_ms,
        "status_code": int(response.status_code),
        "vectors": len(data),
        "dim_mismatch": len(mismatches) + max(0, len(texts) - len(data)),
        "response_model": payload.get("model") or (payload.get("_local") or {}).get("model_id"),
    }


def run_bench_level(
    endpoint: EndpointSpec,
    *,
    workers: int,
    batch_size: int,
    requests_per_worker: int,
    timeout_sec: float,
    input_prefix: str,
    post: Callable[..., Any] = requests.post,
) -> dict[str, Any]:
    total_requests = workers * requests_per_worker
    batches = [
        synthetic_texts(batch_size, f"{input_prefix} worker={idx % workers} request={idx}")
        for idx in range(total_requests)
    ]
    started = time.perf_counter()
    rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(embed_once, endpoint, batch, timeout_sec=timeout_sec, post=post)
            for batch in batches
        ]
        for future in as_completed(futures):
            try:
                rows.append(future.result())
            except Exception as exc:  # pragma: no cover - integration guard
                rows.append(
                    {
                        "ok": False,
                        "latency_ms": None,
                        "status_code": None,
                        "error": f"{type(exc).__name__}: {str(exc)[:260]}",
                        "vectors": 0,
                        "dim_mismatch": batch_size,
                    }
                )
    elapsed_sec = max(time.perf_counter() - started, 0.001)
    ok_rows = [row for row in rows if row.get("ok")]
    latencies = [float(row["latency_ms"]) for row in rows if isinstance(row.get("latency_ms"), (int, float))]
    total_vectors = sum(int(row.get("vectors") or 0) for row in rows)
    dim_mismatch = sum(int(row.get("dim_mismatch") or 0) for row in rows)
    failed_requests = len(rows) - len(ok_rows)
    return {
        "workers": workers,
        "batch_size": batch_size,
        "requests_per_worker": requests_per_worker,
        "requests": len(rows),
        "ok_requests": len(ok_rows),
        "failed_requests": failed_requests,
        "error_rate": round(failed_requests / max(len(rows), 1), 4),
        "total_vectors": total_vectors,
        "dim_mismatch": dim_mismatch,
        "elapsed_sec": round(elapsed_sec, 3),
        "vectors_per_sec": round(total_vectors / elapsed_sec, 2),
        "latency_ms_min": round(min(latencies), 2) if latencies else None,
        "latency_ms_p50": round(statistics.median(latencies), 2) if latencies else None,
        "latency_ms_p95": percentile(latencies, 0.95),
        "latency_ms_max": round(max(latencies), 2) if latencies else None,
        "sample_error": next((row.get("error") for row in rows if row.get("error")), None),
    }


def default_lane_plan(endpoint: EndpointSpec, recommended_workers: int | None) -> list[LanePlan]:
    prod_parallelism = (
        f"start 2, ramp to {recommended_workers} after green bench"
        if recommended_workers and recommended_workers > 2
        else "start 1-2; rerun bench before ramp"
    )
    return [
        LanePlan(
            lane_id="A_production_embedding",
            purpose="stable Stage7 roots -> production-staging vector releases",
            default_route=f"{endpoint.port}/{endpoint.model}/{endpoint.expected_dim}",
            max_parallelism=prod_parallelism,
            runs_when="only after stable-root gate, full dry-run, canary, rollback/resume are green",
            stop_gate="any dim mismatch, embedding failure growth, p95 latency > 5s, or active/mutating Stage7 source",
        ),
        LanePlan(
            lane_id="B_algorithm_and_model_eval",
            purpose="scenario eval, cap/profile sweep, endpoint candidate comparison",
            default_route="11437 baseline; candidates in separate collections only",
            max_parallelism="1 eval matrix while production is active; 2 when production is idle",
            runs_when="read-only sample roots or stable merged roots",
            stop_gate="candidate beats baseline only with same sample, max-jobs 0, and separate model-family output",
        ),
        LanePlan(
            lane_id="C_gpt_oss_qa",
            purpose="offline QA/classification/label suggestions for low-confidence Stage7 outputs",
            default_route="/Users/masher/.openclaw/workspace/model-runs/run-gpt-oss-20b-tq3",
            max_parallelism="1 process; never co-scheduled with high-pressure embedding ramp",
            runs_when="after stable extracts exist or on bounded low-confidence samples",
            stop_gate="stdout sanitation fails, JSON parse fails, memory pressure warning, or QA disagrees with evidence spans",
        ),
    ]


def recommend_workers(bench_rows: list[dict[str, Any]]) -> int | None:
    green: list[dict[str, Any]] = []
    for row in bench_rows:
        if row.get("error_rate") == 0 and row.get("dim_mismatch") == 0:
            p95 = row.get("latency_ms_p95")
            if isinstance(p95, (int, float)) and p95 <= 5000:
                green.append(row)
    if not green:
        return None
    max_throughput = max(float(row.get("vectors_per_sec") or 0) for row in green)
    if max_throughput <= 0:
        return None
    # Pick the knee, not the highest queue depth: the smallest worker count that
    # reaches 98% of max throughput keeps latency low while still saturating MPS.
    threshold = max_throughput * 0.98
    candidates = [row for row in green if float(row.get("vectors_per_sec") or 0) >= threshold]
    best = min(
        candidates,
        key=lambda row: (
            int(row["workers"]),
            float(row.get("latency_ms_p95") or 999999),
        ),
    )
    return int(best["workers"])


def build_report(
    endpoint: EndpointSpec,
    *,
    mode: str,
    bench_rows: list[dict[str, Any]],
    notes: list[str],
) -> dict[str, Any]:
    recommended = recommend_workers(bench_rows)
    return {
        "schema_version": "stage8_m3max_lane_controller.v1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "mode": mode,
        "writes": "none except this report directory; no Qdrant/Neo4j/SQLite/Mem0/Stage7 writes",
        "endpoint": asdict(endpoint) | {"url": endpoint.url},
        "recommended_embedding_workers": recommended,
        "lanes": [asdict(lane) for lane in default_lane_plan(endpoint, recommended)],
        "bench": bench_rows,
        "notes": notes,
    }


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    endpoint = report["endpoint"]
    lines = [
        "# M3 Max Stage8 Vector Lane Controller Report",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- mode: `{report['mode']}`",
        f"- endpoint: `{endpoint['url']}`",
        f"- model: `{endpoint['model']}`",
        f"- expected_dim: `{endpoint['expected_dim']}`",
        f"- writes: `{report['writes']}`",
        f"- recommended_embedding_workers: `{report['recommended_embedding_workers']}`",
        "",
        "## Lane Plan",
        "",
        "| lane | purpose | route | parallelism | runs_when | stop_gate |",
        "|---|---|---|---|---|---|",
    ]
    for lane in report["lanes"]:
        lines.append(
            "| {lane_id} | {purpose} | `{default_route}` | {max_parallelism} | {runs_when} | {stop_gate} |".format(
                **{key: str(value).replace("|", "/") for key, value in lane.items()}
            )
        )
    if report["bench"]:
        lines.extend(
            [
                "",
                "## Embedding Bench",
                "",
                "| workers | batch | requests | ok | failed | vectors | vectors/sec | p50 ms | p95 ms | max ms | dim mismatch |",
                "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for row in report["bench"]:
            lines.append(
                "| {workers} | {batch_size} | {requests} | {ok_requests} | {failed_requests} | {total_vectors} | {vectors_per_sec} | {latency_ms_p50} | {latency_ms_p95} | {latency_ms_max} | {dim_mismatch} |".format(
                    **row
                )
            )
    if report["notes"]:
        lines.extend(["", "## Notes", ""])
        for note in report["notes"]:
            lines.append(f"- {note}")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["plan", "bench", "plan-and-bench"], default="plan-and-bench")
    parser.add_argument("--host", default="192.168.8.234")
    parser.add_argument("--port", type=int, default=11437)
    parser.add_argument("--model", default="stella-large-zh-v2")
    parser.add_argument("--expected-dim", type=int, default=1024)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--bench-concurrency", default="1,2,4")
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--requests-per-worker", type=int, default=3)
    parser.add_argument("--timeout-sec", type=float, default=30.0)
    parser.add_argument("--input-prefix", default="M3 Max vector lane controller")
    args = parser.parse_args(argv)

    endpoint = EndpointSpec(args.host, args.port, args.model, args.expected_dim)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    bench_rows: list[dict[str, Any]] = []
    if args.mode in {"bench", "plan-and-bench"}:
        for workers in parse_int_list(args.bench_concurrency):
            bench_rows.append(
                run_bench_level(
                    endpoint,
                    workers=workers,
                    batch_size=args.batch_size,
                    requests_per_worker=args.requests_per_worker,
                    timeout_sec=args.timeout_sec,
                    input_prefix=args.input_prefix,
                )
            )

    notes = [
        "Do not consume active Stage7 roots; only stable merged roots may enter production gates.",
        "Do not mix model families in one Qdrant collection even if dimensions match.",
        "gpt-oss-20b-tq3 is QA/classification only, not an embedding route.",
    ]
    report = build_report(endpoint, mode=args.mode, bench_rows=bench_rows, notes=notes)
    json_path = out_dir / "m3max_lane_controller_report.json"
    md_path = out_dir / "M3MAX_LANE_CONTROLLER_REPORT.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(md_path, report)
    digest = hashlib.sha1(json_path.read_bytes()).hexdigest()
    print(json.dumps({"ok": True, "json": str(json_path), "markdown": str(md_path), "sha1": digest}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
