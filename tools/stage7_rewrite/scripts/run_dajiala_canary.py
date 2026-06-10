#!/usr/bin/env python3
"""Run a cost-capped Dajiala canary without writing production stores.

The script reads a prepared JSONL queue, optionally calls Dajiala
``article_detail`` for a bounded number of rows, and writes a redacted report.
API keys are read only from environment variables and are never written to
stdout, JSONL, or markdown output.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


DEFAULT_QUEUE = Path("reports/dajiala_budget_waves_20260514/dajiala_canary_50.jsonl")
DEFAULT_OUT_DIR = Path("reports/dajiala_paid_canary_20260515")
DEFAULT_BASE_URL = "https://www.dajiala.com"
SCHEMA_VERSION = "stage7_dajiala_paid_canary.v1"
UNIT_COST = 0.03

ResponseFunc = Callable[[str, str, str, int], dict[str, Any]]


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def read_jsonl(path: Path, limit: int = 0, skip: int = 0) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen = 0
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.strip():
                continue
            if seen < skip:
                seen += 1
                continue
            rows.append(json.loads(line))
            seen += 1
            if limit and len(rows) >= limit:
                break
    return rows


def get_api_key(env: dict[str, str] | None = None) -> str:
    source = env if env is not None else os.environ
    return (source.get("DAJIALA_API_KEY") or source.get("JZL_API_KEY") or "").strip()


def sanitize(value: Any, secret: str) -> str:
    text = str(value or "")
    if secret:
        text = text.replace(secret, "[REDACTED]")
    return text


def data_records(response: dict[str, Any]) -> list[dict[str, Any]]:
    data = response.get("data")
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        nested = data.get("data")
        if isinstance(nested, list):
            return [item for item in nested if isinstance(item, dict)]
        if isinstance(nested, dict):
            return [nested, data]
        return [data]
    return []


def first_value(response: dict[str, Any], names: list[str]) -> str:
    for name in names:
        value = response.get(name)
        if value is not None and str(value).strip():
            return str(value).strip()
        for record in data_records(response):
            nested = record.get(name)
            if nested is not None and str(nested).strip():
                return str(nested).strip()
    return ""


def response_code(response: dict[str, Any]) -> str:
    value = response.get("code")
    if value is not None and str(value).strip():
        return str(value).strip()
    for record in data_records(response):
        nested = record.get("code")
        if nested is not None and str(nested).strip():
            return str(nested).strip()
    return ""


def response_message(response: dict[str, Any]) -> str:
    return first_value(response, ["msg", "message"])


def parse_money(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float("".join(ch for ch in value if ch.isdigit() or ch in ".-"))
        except ValueError:
            return None
    return None


def is_success_response(response: dict[str, Any]) -> bool:
    return response_code(response) == "0"


def article_url(row: dict[str, Any]) -> str:
    return str(row.get("url") or row.get("source_url") or row.get("short_url") or "").strip()


def article_key(row: dict[str, Any]) -> str:
    return str(row.get("article_uid") or row.get("article_id") or row.get("url") or row.get("source_url") or "").strip()


def request_article_detail(url: str, key: str, base_url: str, timeout: int) -> dict[str, Any]:
    endpoint = base_url.rstrip("/") + "/fbmain/monitor/v3/article_detail"
    query = urllib.parse.urlencode({"key": key, "url": url})
    request = urllib.request.Request(
        endpoint + "?" + query,
        headers={"accept": "application/json, text/plain, */*", "user-agent": "stage7-dajiala-canary/1.0"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8", errors="replace")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"code": "non_json", "msg": raw[:300]}
    return parsed if isinstance(parsed, dict) else {"code": "bad_json", "msg": "response was not a JSON object"}


def compact_result(
    row: dict[str, Any],
    response: dict[str, Any] | None,
    *,
    status: str,
    reason: str,
    cost: float,
    elapsed_ms: int,
    secret: str,
) -> dict[str, Any]:
    response = response or {}
    content = first_value(response, ["content"])
    content_text = first_value(response, ["content_text"])
    return {
        "schema_version": "stage7_dajiala_paid_canary.result.v1",
        "article_key": article_key(row),
        "source_account": str(row.get("source_account") or row.get("account") or row.get("biz") or ""),
        "url": article_url(row),
        "status": status,
        "reason": sanitize(reason, secret),
        "code": sanitize(response_code(response), secret),
        "message": sanitize(response_message(response), secret)[:300],
        "cost": round(cost, 4),
        "elapsed_ms": elapsed_ms,
        "has_title": bool(first_value(response, ["title"])),
        "has_content": bool(content or content_text),
        "content_length": len(content),
        "content_text_length": len(content_text),
        "has_cover": bool(first_value(response, ["cover", "cover_url"])),
        "reported_cost_money": first_value(response, ["cost_money", "cost"]),
        "reported_remain_money": first_value(response, ["remain_money", "remain"]),
    }


def decision_for(report: dict[str, Any]) -> str:
    if report["blocking_reasons"]:
        return "dajiala_canary_blocked"
    if report["dry_run"]:
        return "dajiala_canary_dry_run_ready"
    if report["total_requests"] == 0:
        return "dajiala_canary_no_requests"
    if report["success_count"] > 0:
        return "dajiala_canary_executed"
    return "dajiala_canary_failed"


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Dajiala Paid Canary Report",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- decision: `{report['decision']}`",
        f"- mode: `{report['mode']}`",
        f"- dry_run: `{report['dry_run']}`",
        f"- queue_path: `{report['queue_path']}`",
        f"- total_requests: `{report['total_requests']}`",
        f"- success_count: `{report['success_count']}`",
        f"- failed_count: `{report['failed_count']}`",
        f"- total_cost: `{report['total_cost']}`",
        f"- max_cost: `{report['max_cost']}`",
        "",
        "## Blocking Reasons",
        "",
    ]
    if report["blocking_reasons"]:
        lines.extend(f"- {reason}" for reason in report["blocking_reasons"])
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- API key is read from environment only and is never logged.",
            "- No DB, graph, vector, mem0, article store, or production file is written.",
            "- Failed calls are not retried.",
            "- Cost is hard-capped before each request.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_canary(
    args: argparse.Namespace,
    *,
    env: dict[str, str] | None = None,
    request_func: ResponseFunc = request_article_detail,
) -> dict[str, Any]:
    out_dir: Path = args.out_dir
    blocking: list[str] = []
    results: list[dict[str, Any]] = []
    queue_rows: list[dict[str, Any]] = []
    secret = get_api_key(env)

    if not args.queue.exists():
        blocking.append("canary queue missing")
    else:
        queue_rows = read_jsonl(args.queue, args.limit, args.skip)
        if not queue_rows:
            blocking.append("canary queue empty")

    if not args.dry_run and not secret:
        blocking.append("DAJIALA_API_KEY/JZL_API_KEY missing")

    mode = args.mode
    if mode == "auth-smoke" and args.limit != 1:
        queue_rows = queue_rows[:1]

    total_cost = 0.0
    success_count = 0
    failed_count = 0
    skipped_count = 0
    total_requests = 0

    if not blocking:
        for row in queue_rows:
            url = article_url(row)
            if not url.startswith("http"):
                skipped_count += 1
                results.append(
                    compact_result(row, None, status="skipped", reason="missing_http_url", cost=0, elapsed_ms=0, secret=secret)
                )
                continue
            if args.dry_run:
                skipped_count += 1
                results.append(
                    compact_result(row, None, status="dry_run", reason="would_request", cost=0, elapsed_ms=0, secret=secret)
                )
                continue
            if round(total_cost + args.unit_cost, 10) > args.max_cost:
                skipped_count += 1
                results.append(
                    compact_result(row, None, status="skipped", reason="max_cost_reached", cost=0, elapsed_ms=0, secret=secret)
                )
                break
            started = time.monotonic()
            response: dict[str, Any] | None = None
            reason = ""
            try:
                response = request_func(url, secret, args.base_url, args.timeout)
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                reason = sanitize(error, secret)
                response = {"code": "request_error", "msg": reason}
            elapsed_ms = int((time.monotonic() - started) * 1000)
            reported_cost = parse_money(first_value(response, ["cost_money", "cost"]))
            charged_cost = round(reported_cost if reported_cost is not None else args.unit_cost, 4)
            total_requests += 1
            total_cost = round(total_cost + charged_cost, 4)
            if response and is_success_response(response):
                success_count += 1
                results.append(
                    compact_result(row, response, status="success", reason="ok", cost=charged_cost, elapsed_ms=elapsed_ms, secret=secret)
                )
            else:
                failed_count += 1
                failure_reason = reason or f"code={response_code(response or {}) or 'unknown'}"
                results.append(
                    compact_result(row, response, status="failed", reason=failure_reason, cost=charged_cost, elapsed_ms=elapsed_ms, secret=secret)
                )

    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "mode": mode,
        "dry_run": bool(args.dry_run),
        "queue_path": str(args.queue),
        "out_dir": str(out_dir),
        "base_url": args.base_url,
        "limit": args.limit,
        "skip": args.skip,
        "queue_rows_loaded": len(queue_rows),
        "total_requests": total_requests,
        "success_count": success_count,
        "failed_count": failed_count,
        "skipped_count": skipped_count,
        "total_cost": round(total_cost, 4),
        "max_cost": args.max_cost,
        "unit_cost": args.unit_cost,
        "success_rate": round(success_count / total_requests, 4) if total_requests else 0,
        "blocking_reasons": blocking,
        "safety": [
            "env_key_only",
            "key_redacted",
            "no_retries",
            "hard_cost_cap",
            "no_db_graph_vector_mem0_writes",
            "reports_only",
        ],
    }
    report["decision"] = decision_for(report)

    write_json(out_dir / "dajiala_canary_report.json", report)
    write_jsonl(out_dir / "dajiala_canary_results.jsonl", results)
    write_markdown(out_dir / "dajiala_canary_report.md", report)
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--mode", choices=["auth-smoke", "canary"], default="canary")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--skip", type=int, default=0)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--max-cost", type=float, default=0.10)
    parser.add_argument("--unit-cost", type=float, default=UNIT_COST)
    parser.add_argument("--base-url", default=os.environ.get("DAJIALA_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = run_canary(args)
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "total_requests": report["total_requests"],
                "success_count": report["success_count"],
                "failed_count": report["failed_count"],
                "total_cost": report["total_cost"],
                "blocking_reasons": report["blocking_reasons"],
                "summary": str(args.out_dir / "dajiala_canary_report.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
