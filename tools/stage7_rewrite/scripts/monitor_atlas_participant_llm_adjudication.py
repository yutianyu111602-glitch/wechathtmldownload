#!/usr/bin/env python3
"""Monitor and gate Atlas participant LLM adjudication sidecars.

The monitor is intentionally sidecar-only: it reads queue/result SQLite files,
computes quality and cost signals, and optionally stops low-yield runner
processes. It never writes source Atlas SQLite or public serving databases.
"""

from __future__ import annotations

import argparse
import collections
import json
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent.parent

DEFAULT_QUEUE_DB = (
    REPO_ROOT
    / "reports"
    / "atlas_participant_llm_adjudication_queue_v2_20260522"
    / "participant_llm_queue.sqlite"
)
DEFAULT_REVIEW_DB = (
    REPO_ROOT
    / "reports"
    / "atlas_participant_llm_adjudication_full_review_candidates_v2_20260522"
    / "participant_llm_decisions.sqlite"
)
DEFAULT_REEXTRACT_DB = (
    REPO_ROOT
    / "reports"
    / "atlas_participant_llm_adjudication_full_reextract_v2_20260522"
    / "participant_llm_decisions.sqlite"
)
DEFAULT_OUT_DIR = REPO_ROOT / "reports" / "atlas_participant_llm_monitor_20260522"

KNOWN_NON_PARTICIPANT_KEYS = {
    "all",
    "oil",
    "dada",
    "tag",
    "shcr",
    "byyb",
    "baihui",
    "cdcr",
    "club",
    "radio",
    "fm",
    "bar",
    "场地",
    "俱乐部",
    "电台",
    "酒吧",
}

PRICES_USD_PER_1M = {
    "cache_hit_input": 0.0028,
    "cache_miss_input": 0.14,
    "output": 0.28,
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_json(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except json.JSONDecodeError:
        return default


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def connect_readonly(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def queue_lane_counts(path: Path) -> dict[str, int]:
    if not path.exists():
        return {}
    with connect_readonly(path) as conn:
        return {
            str(row["llm_lane"]): int(row["n"])
            for row in conn.execute(
                "SELECT llm_lane, COUNT(*) AS n FROM participant_llm_queue GROUP BY llm_lane"
            )
        }


def participant_names(value: Any) -> list[str]:
    parsed = parse_json(value, [])
    names: list[str] = []
    if isinstance(parsed, list):
        for item in parsed:
            if isinstance(item, dict):
                name = item.get("name") or item.get("participant_name")
                if name:
                    names.append(str(name))
            elif isinstance(item, str):
                names.append(item)
    return [name.strip() for name in names if name and name.strip()]


def usage_cost_usd(value: Any) -> float:
    usage = parse_json(value, {})
    if not isinstance(usage, dict):
        return 0.0
    prompt_tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
    cache_hit = int(usage.get("prompt_cache_hit_tokens") or usage.get("cached_tokens") or 0)
    cache_miss_value = usage.get("prompt_cache_miss_tokens")
    cache_miss = int(cache_miss_value) if cache_miss_value is not None else max(0, prompt_tokens - cache_hit)
    output_tokens = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
    return (
        cache_hit * PRICES_USD_PER_1M["cache_hit_input"]
        + cache_miss * PRICES_USD_PER_1M["cache_miss_input"]
        + output_tokens * PRICES_USD_PER_1M["output"]
    ) / 1_000_000


def inspect_result_db(path: Path, target_by_lane: dict[str, int]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "rows": 0,
        "cost_usd": 0.0,
        "errors": 0,
        "decisions": {},
        "public_graph_ready": 0,
        "suspect_accept_names": 0,
        "lane_stats": {},
    }
    if not path.exists():
        return result

    lane_decisions: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    lane_ready: collections.Counter[str] = collections.Counter()
    lane_cost: collections.Counter[str] = collections.Counter()
    lane_suspect: collections.Counter[str] = collections.Counter()
    decisions: collections.Counter[str] = collections.Counter()

    with connect_readonly(path) as conn:
        rows = conn.execute(
            """
            SELECT llm_lane, decision, public_graph_ready, accepted_participants_json,
                   error, usage_json
            FROM participant_llm_decision
            """
        ).fetchall()

    result["rows"] = len(rows)
    for row in rows:
        lane = str(row["llm_lane"] or "")
        decision = str(row["decision"] or "")
        decisions[decision] += 1
        lane_decisions[lane][decision] += 1
        if int(row["public_graph_ready"] or 0):
            result["public_graph_ready"] += 1
            lane_ready[lane] += 1
        if row["error"]:
            result["errors"] += 1
        cost = usage_cost_usd(row["usage_json"])
        result["cost_usd"] += cost
        lane_cost[lane] += cost
        if decision == "accept":
            for name in participant_names(row["accepted_participants_json"]):
                key = name.lower()
                if key in KNOWN_NON_PARTICIPANT_KEYS or len(name) <= 1:
                    result["suspect_accept_names"] += 1
                    lane_suspect[lane] += 1

    result["cost_usd"] = round(float(result["cost_usd"]), 6)
    result["decisions"] = dict(decisions)
    for lane, counter in lane_decisions.items():
        rows_for_lane = sum(counter.values())
        target = int(target_by_lane.get(lane, 0))
        accepted = int(counter.get("accept", 0))
        ready = int(lane_ready.get(lane, 0))
        cost_usd = float(lane_cost.get(lane, 0.0))
        result["lane_stats"][lane] = {
            "rows": rows_for_lane,
            "target_rows": target,
            "progress": round(rows_for_lane / target, 6) if target else None,
            "accept": accepted,
            "reject": int(counter.get("reject", 0)),
            "needs_more_context": int(counter.get("needs_more_context", 0)),
            "accept_rate": round(accepted / rows_for_lane, 6) if rows_for_lane else 0,
            "public_graph_ready": ready,
            "public_ready_rate": round(ready / rows_for_lane, 6) if rows_for_lane else 0,
            "suspect_accept_names": int(lane_suspect.get(lane, 0)),
            "cost_usd": round(cost_usd, 6),
            "cost_per_public_ready_usd": round(cost_usd / ready, 6) if ready else None,
        }
    return result


def low_yield_lanes(summary: dict[str, Any], min_rows: int, min_ready_rate: float) -> list[str]:
    lanes: list[str] = []
    for result in summary["results"].values():
        for lane, stats in result.get("lane_stats", {}).items():
            rows = int(stats.get("rows") or 0)
            ready_rate = float(stats.get("public_ready_rate") or 0)
            if rows >= min_rows and ready_rate < min_ready_rate:
                lanes.append(lane)
    return sorted(set(lanes))


def stop_runner_processes(lanes: list[str]) -> list[dict[str, Any]]:
    stopped: list[dict[str, Any]] = []
    if not lanes:
        return stopped
    pattern = "|".join(lanes)
    command = (
        "$procs = Get-CimInstance Win32_Process -Filter \"name = 'python.exe'\" | "
        f"Where-Object {{ $_.CommandLine -match 'run_atlas_participant_llm_adjudication' -and $_.CommandLine -match '{pattern}' }}; "
        "foreach($p in $procs){ "
        "Write-Output (\"STOP \" + $p.ProcessId + \" \" + $p.CommandLine); "
        "Stop-Process -Id $p.ProcessId -Force "
        "}"
    )
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        check=False,
        capture_output=True,
        text=True,
    )
    for line in proc.stdout.splitlines():
        if line.startswith("STOP "):
            parts = line.split(" ", 2)
            stopped.append({"pid": int(parts[1]), "command": parts[2] if len(parts) > 2 else ""})
    return stopped


def write_report(out_dir: Path, summary: dict[str, Any]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "monitor_summary.json").write_text(json_dumps(summary), encoding="utf-8")
    lines = [
        "# Atlas Participant LLM Monitor",
        "",
        f"Generated: `{summary['generated_at']}`",
        f"Queue DB: `{summary['queue_db']}`",
        f"Low-yield lanes: `{', '.join(summary['policy']['low_yield_lanes']) or 'none'}`",
        f"Stopped processes: `{len(summary['policy']['stopped_processes'])}`",
        "",
        "## Results",
    ]
    for name, result in summary["results"].items():
        lines.extend(
            [
                "",
                f"### {name}",
                "",
                f"- Rows: `{result['rows']}`",
                f"- Cost USD: `{result['cost_usd']}`",
                f"- Public ready: `{result['public_graph_ready']}`",
                f"- Errors: `{result['errors']}`",
                f"- Suspect accepted names: `{result['suspect_accept_names']}`",
            ]
        )
        for lane, stats in result["lane_stats"].items():
            lines.append(
                "- "
                f"`{lane}` rows `{stats['rows']}/{stats['target_rows']}` "
                f"accept_rate `{stats['accept_rate']}` public_ready_rate `{stats['public_ready_rate']}` "
                f"cost_per_ready `{stats['cost_per_public_ready_usd']}`"
            )
    (out_dir / "monitor_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue-db", default=str(DEFAULT_QUEUE_DB))
    parser.add_argument("--review-db", default=str(DEFAULT_REVIEW_DB))
    parser.add_argument("--reextract-db", default=str(DEFAULT_REEXTRACT_DB))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--min-rows", type=int, default=500)
    parser.add_argument("--min-public-ready-rate", type=float, default=0.05)
    parser.add_argument("--stop-low-yield", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    queue_db = Path(args.queue_db)
    targets = queue_lane_counts(queue_db)
    summary: dict[str, Any] = {
        "generated_at": now_iso(),
        "queue_db": str(queue_db),
        "queue_lane_targets": targets,
        "safety": {
            "source_sqlite_write_executed": False,
            "production_write_executed": False,
            "deploy_or_upload_executed": False,
            "graph_vector_write_executed": False,
        },
        "results": {
            "review": inspect_result_db(Path(args.review_db), targets),
            "reextract": inspect_result_db(Path(args.reextract_db), targets),
        },
        "policy": {
            "min_rows": args.min_rows,
            "min_public_ready_rate": args.min_public_ready_rate,
            "low_yield_lanes": [],
            "stop_low_yield_requested": bool(args.stop_low_yield),
            "stopped_processes": [],
        },
    }
    lanes = low_yield_lanes(summary, args.min_rows, args.min_public_ready_rate)
    summary["policy"]["low_yield_lanes"] = lanes
    if args.stop_low_yield:
        summary["policy"]["stopped_processes"] = stop_runner_processes(lanes)
    write_report(Path(args.out_dir), summary)
    print(json_dumps(summary))


if __name__ == "__main__":
    main()
