"""Compute a bounded HUAIDJ weekly wake fingerprint.

The 5-minute OpenClaw/Codex wake loop should only run expensive rebuild/OCR/
geocode/deploy work when something actually changed or a failed gate/pending
queue exists. This script is report-only by default.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]

DEFAULT_INPUTS = [
    "tools/stage7_rewrite/registries/weekly_accounts_seed.json",
    "tools/stage7_rewrite/registries/weekly_venues_seed.json",
    "services/weekly_activity_cloudrun/data/current_release/manifest.json",
    "services/weekly_activity_cloudrun/data/current_release/current.json",
    "services/weekly_activity_cloudrun/data/current_release/llm/enrichment_index.json",
    "apps/weekly_activity_miniprogram/app.json",
    "apps/weekly_activity_miniprogram/utils/api.js",
    "apps/weekly_activity_miniprogram/utils/sourceAction.js",
    "services/weekly_activity_cloudrun/src/server.mjs",
]

FAILED_DECISION_TOKENS = ("blocked", "failed", "drift_detected", "not_ready")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def resolve_path(value: str, root: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def path_record(path: Path, root: Path) -> dict[str, Any]:
    try:
        rel = str(path.relative_to(root))
    except ValueError:
        rel = str(path)
    if not path.exists():
        return {"path": rel, "exists": False, "size": 0, "mtime_ns": 0, "sha256": ""}
    if not path.is_file():
        return {"path": rel, "exists": True, "kind": "non_file", "size": 0, "mtime_ns": 0, "sha256": ""}
    stat = path.stat()
    return {
        "path": rel,
        "exists": True,
        "kind": "file",
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": sha256_file(path),
    }


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def failed_gate_reason(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    if value.get("ok") is False or value.get("passes") is False:
        return "ok_false"
    blockers = value.get("blockers") or value.get("failed_checks") or value.get("errors")
    if isinstance(blockers, list) and blockers:
        return "nonempty_blockers"
    decision = str(value.get("decision") or value.get("status") or "").lower()
    if any(token in decision for token in FAILED_DECISION_TOKENS):
        return f"decision:{decision[:80]}"
    return ""


def gate_records(paths: list[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in paths:
        record = {"path": str(path), "exists": path.exists(), "failed": False, "reason": ""}
        if path.exists() and path.is_file():
            try:
                value = read_json(path)
                reason = failed_gate_reason(value)
                record.update({"failed": bool(reason), "reason": reason})
            except Exception as exc:  # noqa: BLE001 - report-only diagnostic
                record.update({"failed": True, "reason": f"unreadable_json:{type(exc).__name__}"})
        records.append(record)
    return records


def count_jsonl_rows(path: Path) -> int:
    if not path.exists() or not path.is_file():
        return 0
    count = 0
    with path.open("r", encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            if line.strip():
                count += 1
    return count


def pending_records(paths: list[Path]) -> list[dict[str, Any]]:
    return [
        {"path": str(path), "exists": path.exists(), "pending_rows": count_jsonl_rows(path)}
        for path in paths
    ]


def load_previous_state(path: Path | None) -> dict[str, Any] | None:
    if not path or not path.exists():
        return None
    try:
        value = read_json(path)
        return value if isinstance(value, dict) else None
    except Exception:
        return None


def build_report(
    *,
    root: Path,
    input_paths: list[Path],
    failed_gate_paths: list[Path],
    pending_paths: list[Path],
    state_file: Path | None,
) -> dict[str, Any]:
    file_records = [path_record(path, root) for path in input_paths]
    gates = gate_records(failed_gate_paths)
    pending = pending_records(pending_paths)
    signal = {
        "files": file_records,
        "failed_gates": gates,
        "pending_queues": pending,
    }
    fingerprint = canonical_hash(signal)
    previous = load_previous_state(state_file)
    previous_fingerprint = str((previous or {}).get("fingerprint_sha256") or "")
    failed_gate_count = sum(1 for item in gates if item.get("failed"))
    pending_row_count = sum(int(item.get("pending_rows") or 0) for item in pending)

    if failed_gate_count or pending_row_count:
        decision = "run_actionable_problem"
    elif previous_fingerprint and previous_fingerprint == fingerprint:
        decision = "skipped_no_actionable_problem"
    else:
        decision = "run_fingerprint_changed"

    return {
        "schemaVersion": "weekly_wake_fingerprint.v1",
        "generatedAt": utc_now(),
        "decision": decision,
        "fingerprint_sha256": fingerprint,
        "previous_fingerprint_sha256": previous_fingerprint,
        "changedSincePrevious": bool(previous_fingerprint and previous_fingerprint != fingerprint),
        "failedGateCount": failed_gate_count,
        "pendingRowCount": pending_row_count,
        "inputs": file_records,
        "failedGates": gates,
        "pendingQueues": pending,
        "safety": {
            "rebuildExecuted": False,
            "geocodeExecuted": False,
            "ocrExecuted": False,
            "deployExecuted": False,
            "uploadExecuted": False,
            "llmCallExecuted": False,
        },
    }


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Weekly Wake Fingerprint",
        "",
        f"- decision: `{report['decision']}`",
        f"- fingerprint: `{report['fingerprint_sha256']}`",
        f"- failed gates: `{report['failedGateCount']}`",
        f"- pending rows: `{report['pendingRowCount']}`",
        "",
        "## Inputs",
        "",
    ]
    for item in report["inputs"]:
        lines.append(f"- `{item['path']}` exists=`{item['exists']}` sha256=`{str(item.get('sha256') or '')[:16]}`")
    lines.extend([
        "",
        "## Safety",
        "",
        "- Report-only fingerprint calculation.",
        "- No rebuild, geocode, OCR, deploy, upload, or LLM call executed.",
        "",
    ])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(ROOT), help="Repository/workspace root.")
    parser.add_argument("--input", action="append", default=[], help="Extra file path to fingerprint.")
    parser.add_argument("--no-default-inputs", action="store_true", help="Only use paths passed through --input.")
    parser.add_argument("--failed-gate-json", action="append", default=[], help="JSON gate summary to force action on failure.")
    parser.add_argument("--pending-jsonl", action="append", default=[], help="Pending review JSONL queue to count.")
    parser.add_argument("--state-file", default="", help="Previous fingerprint state JSON.")
    parser.add_argument("--write-state", action="store_true", help="Write current fingerprint to --state-file.")
    parser.add_argument("--out-dir", default="", help="Output directory for report.json/report.md.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    input_values = ([] if args.no_default_inputs else list(DEFAULT_INPUTS)) + list(args.input or [])
    report = build_report(
        root=root,
        input_paths=[resolve_path(value, root) for value in input_values],
        failed_gate_paths=[resolve_path(value, root) for value in args.failed_gate_json or []],
        pending_paths=[resolve_path(value, root) for value in args.pending_jsonl or []],
        state_file=resolve_path(args.state_file, root) if args.state_file else None,
    )
    if args.out_dir:
        out_dir = resolve_path(args.out_dir, root)
        write_json(out_dir / "report.json", report)
        write_markdown(out_dir / "report.md", report)
    if args.write_state:
        if not args.state_file:
            raise SystemExit("--write-state requires --state-file")
        write_json(resolve_path(args.state_file, root), report)
    print(json.dumps({k: report[k] for k in ("decision", "fingerprint_sha256", "failedGateCount", "pendingRowCount")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
