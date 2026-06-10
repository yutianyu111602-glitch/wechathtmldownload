#!/usr/bin/env python3
"""Refresh PRD-12 poster OCR text gate from official index and sidecar evidence.

This is a report-only gate refresh. It reads the official OCR file index and
bounded recovered-process sidecar poster_ocr.json files, then explains whether
poster text vectorization has a valid input contract.

No OCR execution, embedding calls, Qdrant writes, alias changes, paid API calls,
publish, or D: scan.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_POINTER = Path("reports/ocr_file_index_latest.json")
DEFAULT_OCR_ROOT = Path("reports/ocr_root_cause_20260515")
DEFAULT_OUT_DIR = Path("reports/poster_ocr_text_gate_refresh_20260515")
SCHEMA_VERSION = "stage7_prd12_poster_ocr_text_gate_refresh.v1"
TEXT_READY_STATUSES = {"complete"}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def reject_broad_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw in {"d:", "d:/", "/mnt/d", "/mnt/d/"}:
        raise ValueError(f"{label} refuses broad D root: {path}")
    if raw.startswith("d:/ddownload") or raw.startswith("d:/aidata"):
        raise ValueError(f"{label} refuses banned D subtree: {path}")


def read_json(path: Path) -> dict[str, Any]:
    reject_broad_d_path(path, "json")
    value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_broad_d_path(path, "jsonl")
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            value = json.loads(stripped)
            if isinstance(value, dict):
                rows.append(value)
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
    tmp.replace(path)


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# PRD-12 Poster OCR Text Gate Refresh",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- decision: `{report['decision']}`",
        f"- text_vectorization_input_gate_met: `{report['text_vectorization_input_gate_met']}`",
        f"- embedding_or_qdrant_write_allowed: `{report['embedding_or_qdrant_write_allowed']}`",
        f"- candidate_manifest_path: `{report['candidate_manifest_path']}`",
        "",
        "## Official Index",
        "",
    ]
    official = report["official_index"]
    for key in ("record_count", "text_ready_rows", "min_text_posters", "text_gate_met"):
        lines.append(f"- {key}: `{official.get(key)}`")
    lines.extend(["", "## Sidecar Evidence", ""])
    sidecar = report["sidecar"]
    for key in ("status_file_count", "poster_ocr_seen", "plain_text_nonempty", "min_text_posters", "text_gate_met"):
        lines.append(f"- {key}: `{sidecar.get(key)}`")
    lines.extend(["", "## Blockers", ""])
    if report["blockers"]:
        for blocker in report["blockers"]:
            lines.append(f"- {blocker}")
    else:
        lines.append("- none")
    lines.extend(["", "## Allowed Next Actions", ""])
    for item in report["allowed_next_actions"]:
        lines.append(f"- {item}")
    lines.extend(["", "## Forbidden Next Actions", ""])
    for item in report["forbidden_next_actions"]:
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Report-only.",
            "- Candidate manifest stores metadata, text length, and SHA-256 only; it does not copy OCR text.",
            "- No OCR execution, embedding call, Qdrant write, alias change, paid API, publish, or D: scan.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def is_under(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def article_uid_from_relative(relative_dir: str) -> tuple[str, str]:
    parts = [part for part in relative_dir.replace("/", "\\").split("\\") if part]
    if len(parts) >= 2:
        return parts[0], f"{parts[0]}/{parts[1]}"
    if parts:
        return parts[0], parts[0]
    return "", ""


def load_official_index(pointer_path: Path, min_text_posters: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    pointer = read_json(pointer_path)
    index_path = Path(str(pointer["index_path"]))
    rows = read_jsonl(index_path)
    status_counts = Counter(str(row.get("ocr_status") or "unknown").strip() or "unknown" for row in rows)
    text_ready = [row for row in rows if str(row.get("ocr_status") or "").strip() in TEXT_READY_STATUSES]
    candidates: list[dict[str, Any]] = []
    for row in text_ready:
        text = str(row.get("ocr_text") or row.get("poster_ocr_text") or "").strip()
        candidates.append(
            {
                "origin": "official_ocr_index",
                "source_article_uid": row.get("source_article_uid") or row.get("article_uid") or "",
                "source_account": row.get("source_account") or row.get("account") or "",
                "ocr_status": row.get("ocr_status"),
                "text_length": len(text),
                "text_sha256": text_hash(text) if text else "",
                "poster_ocr_path": row.get("poster_ocr_path") or "",
                "raw_row_ref": row.get("raw_path") or row.get("path") or "",
            }
        )
    return (
        {
            "pointer_path": str(pointer_path),
            "index_path": str(index_path),
            "record_count": len(rows),
            "text_ready_rows": len(text_ready),
            "min_text_posters": min_text_posters,
            "text_gate_met": len(text_ready) >= min_text_posters,
            "ocr_status_counts": dict(status_counts),
        },
        candidates,
    )


def audit_sidecar_text(ocr_root: Path, min_text_posters: int, max_items: int = 0) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    root_resolved = ocr_root.resolve()
    status_files = sorted(ocr_root.glob("empty_no_local_image_dajiala_process_*/ocr-status.json"))
    candidates: list[dict[str, Any]] = []
    backend_counts: Counter[str] = Counter()
    skipped: Counter[str] = Counter()
    poster_ocr_seen = 0
    inspected_items = 0
    for status_path in status_files:
        status = read_json(status_path)
        for item in status.get("items") or []:
            if max_items and inspected_items >= max_items:
                continue
            artifact_dir = Path(str(item.get("artifactDir") or ""))
            poster_ocr_path = artifact_dir / "poster_ocr.json"
            if not poster_ocr_path.exists() or not is_under(poster_ocr_path, root_resolved):
                skipped["poster_ocr_missing_or_outside_root"] += 1
                continue
            inspected_items += 1
            poster_ocr_seen += 1
            try:
                poster = read_json(poster_ocr_path)
            except Exception:
                skipped["poster_ocr_unreadable"] += 1
                continue
            backend = str(poster.get("backend") or "unknown").strip() or "unknown"
            backend_counts[backend] += 1
            plain_text = str(poster.get("plain_text") or "").strip()
            if not plain_text:
                skipped["plain_text_empty"] += 1
                continue
            source_account, source_article_uid = article_uid_from_relative(str(item.get("relativeDir") or ""))
            candidates.append(
                {
                    "origin": "sidecar_poster_ocr",
                    "source_article_uid": source_article_uid,
                    "source_account": source_account,
                    "relative_dir": item.get("relativeDir"),
                    "poster_ocr_path": str(poster_ocr_path),
                    "backend": backend,
                    "text_length": len(plain_text),
                    "text_sha256": text_hash(plain_text),
                    "text_copied": False,
                    "contract_status": "outside_official_ocr_index",
                }
            )
    return (
        {
            "ocr_root": str(ocr_root),
            "status_file_count": len(status_files),
            "poster_ocr_seen": poster_ocr_seen,
            "plain_text_nonempty": len(candidates),
            "min_text_posters": min_text_posters,
            "text_gate_met": len(candidates) >= min_text_posters,
            "backend_counts": dict(backend_counts),
            "skipped": dict(skipped),
        },
        candidates,
    )


def build_report(
    official: dict[str, Any],
    official_candidates: list[dict[str, Any]],
    sidecar: dict[str, Any],
    sidecar_candidates: list[dict[str, Any]],
    candidate_manifest_path: Path,
) -> dict[str, Any]:
    official_gate = bool(official.get("text_gate_met"))
    sidecar_gate = bool(sidecar.get("text_gate_met"))
    blockers: list[str] = []
    if not official_gate:
        blockers.append(
            f"official OCR index poster text rows {official.get('text_ready_rows')} < required {official.get('min_text_posters')}"
        )
    if sidecar_gate and not official_gate:
        blockers.append("sidecar poster OCR text meets count gate but is outside the official OCR index/vectorization contract")
    if not sidecar_gate and not official_gate:
        blockers.append("sidecar poster OCR text rows also below required count")
    blockers.append("embedding and Qdrant writes remain forbidden in this report-only refresh")

    if official_gate:
        decision = "poster_ocr_text_gate_ready_official_index"
    elif sidecar_gate:
        decision = "poster_ocr_text_gate_sidecar_ready_official_contract_blocked"
    else:
        decision = "poster_ocr_text_gate_blocked_missing_real_text"

    allowed = (
        ["build_poster_text_vector_canary_only_after_separate_embedding_write_gate"]
        if official_gate
        else ["review_sidecar_text_manifest_and_define_official_index_bridge_contract"]
        if sidecar_gate
        else ["recover_real_poster_ocr_text_before_vectorization"]
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": True,
        "report_only": True,
        "decision": decision,
        "text_vectorization_input_gate_met": official_gate,
        "embedding_or_qdrant_write_allowed": False,
        "official_index": official,
        "sidecar": sidecar,
        "candidate_counts": {
            "official_index": len(official_candidates),
            "sidecar": len(sidecar_candidates),
            "total": len(official_candidates) + len(sidecar_candidates),
        },
        "candidate_manifest_path": str(candidate_manifest_path),
        "blockers": blockers,
        "allowed_next_actions": allowed,
        "forbidden_next_actions": [
            "do_not_run_embedding_without_official_text_contract_or_explicit_write_gate",
            "do_not_create_qdrant_poster_collection",
            "do_not_promote_qdrant_alias",
            "do_not_copy_raw_ocr_text_into_gate_manifest",
            "do_not_use_article_text_or_test_fixtures_as_poster_ocr",
        ],
        "safety": [
            "reports_only",
            "official_index_read_only",
            "bounded_c_reports_sidecar_read_only",
            "candidate_manifest_hashes_no_text_copy",
            "ocr_execution_false",
            "embedding_calls_false",
            "qdrant_write_false",
            "alias_change_false",
            "no_paid_api",
            "no_d_scan",
            "no_publish",
        ],
        "writes": "reports_only",
    }


def run(args: argparse.Namespace) -> int:
    official, official_candidates = load_official_index(args.pointer, args.min_text_posters)
    sidecar, sidecar_candidates = audit_sidecar_text(args.ocr_root, args.min_text_posters, max_items=args.max_sidecar_items)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    candidate_manifest = args.out_dir / "poster_ocr_text_candidates.jsonl"
    write_jsonl(candidate_manifest, official_candidates + sidecar_candidates)
    report = build_report(official, official_candidates, sidecar, sidecar_candidates, candidate_manifest)
    write_json(args.out_dir / "poster_ocr_text_gate_refresh.json", report)
    write_markdown(args.out_dir / "poster_ocr_text_gate_refresh.md", report)
    print(
        json.dumps(
            {
                "ok": report["ok"],
                "decision": report["decision"],
                "text_vectorization_input_gate_met": report["text_vectorization_input_gate_met"],
                "candidate_counts": report["candidate_counts"],
                "report": str(args.out_dir / "poster_ocr_text_gate_refresh.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["ok"] or args.report_only_exit_zero else 2


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pointer", type=Path, default=DEFAULT_POINTER)
    parser.add_argument("--ocr-root", type=Path, default=DEFAULT_OCR_ROOT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--min-text-posters", type=int, default=20)
    parser.add_argument("--max-sidecar-items", type=int, default=0)
    parser.add_argument("--report-only-exit-zero", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
