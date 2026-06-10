"""Write a local Hermes heartbeat snapshot for Stage7.

Default execution writes one heartbeat and exits. Continuous mode is explicit:
pass --interval and --iterations greater than 1.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path
from typing import Any

from hermes_monitor_common import (
    append_jsonl,
    latest_markdown_heading,
    now_iso,
    read_json_if_exists,
    reject_d_path,
    write_json,
    write_text,
)


DEFAULT_OUT_DIR = Path("reports/hermes_heartbeat_20260515")
SCHEMA_VERSION = "stage7_hermes_heartbeat.v1"


def http_probe(url: str, timeout_sec: float = 2.0) -> dict[str, Any]:
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json,text/plain,*/*"})
        with urllib.request.urlopen(req, timeout=timeout_sec) as response:
            return {"ok": True, "status": response.status}
    except Exception as exc:  # pragma: no cover - exact network errors vary
        return {"ok": False, "error": type(exc).__name__}


def collect_heartbeat(root: Path, *, check_services: bool = False) -> dict[str, Any]:
    reject_d_path(root, "root")
    publish_gate = read_json_if_exists(root / "reports/consumer_publish_gate_review_20260515/consumer_publish_gate_review.json")
    social_verify = read_json_if_exists(root / "reports/neo4j_p1_social_staging_20260515/canary_verification.json")
    ocr_audit = read_json_if_exists(root / "reports/ocr_root_cause_20260515/non_dajiala_recoverability_audit_v30_20260515/summary.json")

    services: dict[str, Any] = {}
    if check_services:
        services = {
            "qdrant": http_probe("http://127.0.0.1:6333/"),
            "neo4j": http_probe("http://127.0.0.1:7474/"),
            "camofox": http_probe("http://127.0.0.1:9377/health"),
        }

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "root": str(root),
        "longrun_last_round": latest_markdown_heading(root / "LONGRUN_STATE.md"),
        "publish_gate": {
            "decision": publish_gate.get("decision"),
            "dry_run_ready": publish_gate.get("dry_run_ready"),
            "publish_allowed": publish_gate.get("publish_allowed"),
            "blocking_count": len(publish_gate.get("blocking_reasons") or []),
        },
        "p1_social": {
            "verify_ok": social_verify.get("ok"),
            "has_profile_edges": (social_verify.get("counts") or {}).get("has_profile_edges"),
            "non_staging_only_edges": (social_verify.get("counts") or {}).get("non_staging_only_edges"),
        },
        "ocr_recovery": {
            "missing_empty_no_local_image": ocr_audit.get("missing_count"),
            "writes": ocr_audit.get("writes"),
        },
        "services": services,
        "writes": "reports_only",
    }


def write_heartbeat(out_dir: Path, heartbeat: dict[str, Any]) -> None:
    reject_d_path(out_dir, "out_dir")
    write_json(out_dir / "heartbeat_latest.json", heartbeat)
    append_jsonl(out_dir / "heartbeat.jsonl", heartbeat)
    lines = [
        "# Hermes Heartbeat",
        "",
        f"- generated_at: `{heartbeat['generated_at']}`",
        f"- longrun_last_round: `{heartbeat.get('longrun_last_round')}`",
        f"- publish_gate: `{(heartbeat.get('publish_gate') or {}).get('decision')}`",
        f"- p1_social_verify_ok: `{(heartbeat.get('p1_social') or {}).get('verify_ok')}`",
        f"- ocr_missing_empty_no_local_image: `{(heartbeat.get('ocr_recovery') or {}).get('missing_empty_no_local_image')}`",
        f"- writes: `{heartbeat['writes']}`",
        "",
    ]
    write_text(out_dir / "heartbeat_latest.md", "\n".join(lines))


def run_once(root: Path, out_dir: Path, *, check_services: bool = False) -> dict[str, Any]:
    heartbeat = collect_heartbeat(root, check_services=check_services)
    write_heartbeat(out_dir, heartbeat)
    return heartbeat


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--interval", type=int, default=0)
    parser.add_argument("--iterations", type=int, default=1)
    parser.add_argument("--check-services", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    last: dict[str, Any] = {}
    for index in range(max(args.iterations, 1)):
        last = run_once(args.root, args.out_dir, check_services=args.check_services)
        if args.interval > 0 and index + 1 < args.iterations:
            time.sleep(args.interval)
    print(json.dumps({"ok": True, "heartbeat": str(args.out_dir / "heartbeat_latest.json")}, ensure_ascii=False, indent=2))
    return 0 if last else 1


if __name__ == "__main__":
    raise SystemExit(main())
