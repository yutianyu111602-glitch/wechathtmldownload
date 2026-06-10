from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path


def now_cst_stamp() -> str:
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d_%H%M")


def decide_nightwatch(preflight: dict) -> str:
    if preflight.get("integrity") != "ok":
        return "stop_due_integrity"
    stop_gates = set(preflight.get("stop_gates", []))
    if "searxng_delta" in stop_gates:
        return "stop_due_searxng_delta"
    if "active_workers_with_stale_running" in stop_gates:
        return "hold_for_human"
    return "continue_profile_a"


def build_payload(preflight: dict, lineage_summary: dict | None = None, run_id: str | None = None) -> dict:
    payload = {
        "run_id": run_id or f"db2_outlink_nightwatch_{now_cst_stamp()}",
        "source_db_role": "live_swarm_external_link_db2",
        "integrity": preflight.get("integrity"),
        "tables": preflight.get("table_counts", {}),
        "progress": preflight.get("progress", {}),
        "searxng_tagged_count": preflight.get("searxng_tagged_count", 0),
        "searxng_delta": preflight.get("searxng_delta", 0),
        "active_worker_count": preflight.get("active_worker_count", 0),
        "stale_running_count": preflight.get("stale_running_count", 0),
        "stop_gates": preflight.get("stop_gates", []),
        "lineage_reconcile": lineage_summary or {},
    }
    payload["decision"] = decide_nightwatch(preflight)
    return payload


def write_nightwatch_outputs(payload: dict, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "db2_outlink_nightwatch_summary.json"
    md_path = output_dir / "db2_outlink_nightwatch_summary.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "# DB2 Outlink Nightwatch",
        "",
        f"- run_id: `{payload.get('run_id')}`",
        f"- source_db_role: `{payload.get('source_db_role')}`",
        f"- integrity: `{payload.get('integrity')}`",
        f"- decision: `{payload.get('decision')}`",
        f"- active_worker_count: `{payload.get('active_worker_count')}`",
        f"- stale_running_count: `{payload.get('stale_running_count')}`",
        f"- searxng_tagged_count: `{payload.get('searxng_tagged_count')}`",
        f"- stop_gates: `{payload.get('stop_gates')}`",
        "",
        "## Lineage Reconcile",
        "",
        f"- projection_allowed: `{payload.get('lineage_reconcile', {}).get('projection_allowed', 0)}`",
        f"- rows: `{payload.get('lineage_reconcile', {}).get('rows', 0)}`",
    ]
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write DB2 outlink nightwatch output from preflight JSON")
    parser.add_argument("--preflight-json", type=Path, required=True)
    parser.add_argument("--lineage-json", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("/db2-reports"))
    parser.add_argument("--run-id")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    preflight = json.loads(args.preflight_json.read_text(encoding="utf-8"))
    lineage_summary = None
    if args.lineage_json and args.lineage_json.exists():
        lineage_summary = json.loads(args.lineage_json.read_text(encoding="utf-8"))
    payload = build_payload(preflight, lineage_summary, args.run_id)
    json_path, md_path = write_nightwatch_outputs(payload, args.output_dir)
    print(json.dumps({"json": str(json_path), "markdown": str(md_path), "decision": payload["decision"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
