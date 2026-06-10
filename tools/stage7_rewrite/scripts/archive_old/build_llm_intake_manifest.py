#!/usr/bin/env python3
"""Build a bounded manifest of recovered artifacts that should feed LLM stages.

The script is read-only for source artifacts. It does not copy article files,
does not scan D: roots, and does not start OCR/LLM/vector work. It only reads
known recovered queues plus their bounded artifact roots, validates article
dirs, and writes a compact intake manifest.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


LONGRUN_ROOT = Path(r"D:\downstream_results\stage7_rewrite\longrun")
MAIN_ARTIFACT_ROOT = Path(r"D:\DDownload\_llm_artifacts")
MAIN_ARCHIVE_ROOT = Path(r"D:\DDownload\_archive_mptext")
DEFAULT_OUT_DIR = LONGRUN_ROOT / "LLM_INTAKE_MANIFEST_20260507"
FULL_EMPTY_RECOVERY_ROOT = LONGRUN_ROOT / "FULL_EMPTY_LINK_RECOVERY_20260507"


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    return value if isinstance(value, dict) else None


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                value = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                rows.append(value)
    return rows


def first_string(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    count = 0
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if line.strip():
                count += 1
    return count


def known_sources() -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = [
        {
            "name": "latest_free_recovered",
            "queue_path": LONGRUN_ROOT / "LATEST_FREE_CHUNKS_20260506_2225" / "combined-recovered-queue.jsonl",
            "artifact_root": LONGRUN_ROOT / "LATEST_ARTIFACTS_FULL_20260506_2225",
            "archive_root": LONGRUN_ROOT / "LATEST_ARCHIVE_FULL_20260506_2225",
            "kind": "latest_free",
        },
        {
            "name": "latest_free_review",
            "queue_path": LONGRUN_ROOT / "LATEST_FREE_CHUNKS_20260506_2225" / "combined-review-items.jsonl",
            "artifact_root": LONGRUN_ROOT / "LATEST_ARTIFACTS_FULL_20260506_2225",
            "archive_root": LONGRUN_ROOT / "LATEST_ARCHIVE_FULL_20260506_2225",
            "kind": "latest_free_review",
        },
        {
            "name": "latest_dajiala_blocked_canary_recovered",
            "queue_path": LONGRUN_ROOT
            / "LATEST_DAJIALA_BLOCKED_CANARY_20260506_NIGHT"
            / "audit"
            / "recovered_queue.jsonl",
            "artifact_root": LONGRUN_ROOT / "LATEST_DAJIALA_BLOCKED_CANARY_20260506_NIGHT" / "artifacts",
            "archive_root": LONGRUN_ROOT / "LATEST_DAJIALA_BLOCKED_CANARY_20260506_NIGHT" / "archive",
            "kind": "latest_dajiala_canary",
        },
        {
            "name": "latest_dajiala_blocked_canary_review",
            "queue_path": LONGRUN_ROOT
            / "LATEST_DAJIALA_BLOCKED_CANARY_20260506_NIGHT"
            / "audit"
            / "review_items.jsonl",
            "artifact_root": LONGRUN_ROOT / "LATEST_DAJIALA_BLOCKED_CANARY_20260506_NIGHT" / "artifacts",
            "archive_root": LONGRUN_ROOT / "LATEST_DAJIALA_BLOCKED_CANARY_20260506_NIGHT" / "archive",
            "kind": "latest_dajiala_canary_review",
        },
        {
            "name": "oil_reexported_recovered",
            "queue_path": LONGRUN_ROOT / "RECOVERED_OIL_QUEUE_20260506_2020" / "recovered_oil_queue.jsonl",
            "artifact_root": MAIN_ARTIFACT_ROOT,
            "archive_root": MAIN_ARCHIVE_ROOT,
            "kind": "main_reexported",
        },
        {
            "name": "free_signed_reexported_recovered",
            "queue_path": LONGRUN_ROOT
            / "FREE_SIGNED_RECOVERED_QUEUE_20260506_2055"
            / "recovered_signed_queue.jsonl",
            "artifact_root": MAIN_ARTIFACT_ROOT,
            "archive_root": MAIN_ARCHIVE_ROOT,
            "kind": "main_reexported",
        },
    ]

    combined_summary = read_json(LONGRUN_ROOT / "RECOVERED_SHORT2LONG_20260506_2152" / "summary.json")
    for audit_dir_text in (combined_summary or {}).get("source_audits", []):
        audit_dir = Path(audit_dir_text)
        audit_summary = read_json(audit_dir / "summary.json") or {}
        artifact_root = first_string(audit_summary.get("artifact_root"))
        archive_root = first_string(audit_summary.get("archive_root"))
        recovered_queue = first_string(audit_summary.get("recovered_queue_jsonl"))
        if recovered_queue and artifact_root:
            sources.append(
                {
                    "name": f"short2long_{audit_dir.name}",
                    "queue_path": Path(recovered_queue),
                    "artifact_root": Path(artifact_root),
                    "archive_root": Path(archive_root) if archive_root else Path(""),
                    "kind": "short2long_recovered",
                }
            )
        review_queue = first_string(audit_summary.get("review_items_jsonl"))
        if review_queue and artifact_root:
            sources.append(
                {
                    "name": f"short2long_review_{audit_dir.name}",
                    "queue_path": Path(review_queue),
                    "artifact_root": Path(artifact_root),
                    "archive_root": Path(archive_root) if archive_root else Path(""),
                    "kind": "short2long_review",
                }
            )

    for delta_root in sorted(LONGRUN_ROOT.glob("WEEKLY_ACTIVITY_DELTA_*")):
        if not delta_root.is_dir():
            continue
        audit_summary = read_json(delta_root / "audit" / "summary.json") or {}
        artifact_root = first_string(audit_summary.get("artifact_root"))
        archive_root = first_string(audit_summary.get("archive_root"))
        recovered_queue = first_string(audit_summary.get("recovered_queue_jsonl"))
        if recovered_queue and artifact_root:
            sources.append(
                {
                    "name": f"weekly_activity_delta_{delta_root.name.lower()}_recovered",
                    "queue_path": Path(recovered_queue),
                    "artifact_root": Path(artifact_root),
                    "archive_root": Path(archive_root) if archive_root else Path(""),
                    "kind": "weekly_activity_delta",
                }
            )
        review_queue = first_string(audit_summary.get("review_items_jsonl"))
        if review_queue and artifact_root:
            sources.append(
                {
                    "name": f"weekly_activity_delta_{delta_root.name.lower()}_review",
                    "queue_path": Path(review_queue),
                    "artifact_root": Path(artifact_root),
                    "archive_root": Path(archive_root) if archive_root else Path(""),
                    "kind": "weekly_activity_delta_review",
                }
            )

    if FULL_EMPTY_RECOVERY_ROOT.exists():
        for process_dir in sorted(FULL_EMPTY_RECOVERY_ROOT.glob("PROCESS_WAVE_*")):
            if not process_dir.is_dir():
                continue
            suffix = process_dir.name.removeprefix("PROCESS_")
            artifact_root = FULL_EMPTY_RECOVERY_ROOT / f"ARTIFACTS_{suffix}"
            archive_root = FULL_EMPTY_RECOVERY_ROOT / f"ARCHIVE_{suffix}"
            sources.append(
                {
                    "name": f"full_empty_{suffix.lower()}_recovered",
                    "queue_path": process_dir / "combined-recovered-queue.jsonl",
                    "artifact_root": artifact_root,
                    "archive_root": archive_root,
                    "kind": "full_empty_recovered",
                }
            )
            sources.append(
                {
                    "name": f"full_empty_{suffix.lower()}_review",
                    "queue_path": process_dir / "combined-review-items.jsonl",
                    "artifact_root": artifact_root,
                    "archive_root": archive_root,
                    "kind": "full_empty_review",
                }
            )
    return sources


def validate_record(source: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    account = first_string(record.get("account_key"), record.get("account"), record.get("account_nickname"))
    token = first_string(record.get("token"))
    artifact_root = Path(source["artifact_root"])
    archive_root = Path(source.get("archive_root") or "")
    artifact_dir = artifact_root / account / token
    archive_dir = archive_root / account / token if str(archive_root) else Path("")

    llm_path = artifact_dir / "llm_input.md"
    sidecar_path = artifact_dir / "sidecar.json"
    quality_path = artifact_dir / "quality_report.json"
    meta_path = artifact_dir / "meta.json"
    poster_ocr_path = artifact_dir / "poster_ocr.json"
    archive_meta_path = archive_dir / "archive_meta.json" if str(archive_dir) else Path("")

    llm_text = ""
    if llm_path.exists():
        try:
            llm_text = llm_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            llm_text = ""
    sidecar = read_json(sidecar_path)
    quality = read_json(quality_path)
    meta = read_json(meta_path)
    archive_meta = read_json(archive_meta_path) if str(archive_meta_path) else None

    main_content = first_string((sidecar or {}).get("main_content"))
    llm_chars = len(llm_text.strip())
    main_chars = len(main_content.strip()) if main_content else 0
    raw_html_bytes = 0
    if archive_meta and isinstance(archive_meta.get("raw_html_bytes"), (int, float)):
        raw_html_bytes = int(archive_meta["raw_html_bytes"])
    title = first_string((meta or {}).get("title"), ((sidecar or {}).get("meta") or {}).get("title"), record.get("title"))
    source_url = first_string((meta or {}).get("source_url"), ((sidecar or {}).get("archive") or {}).get("source_url"), record.get("source_url"))

    reasons: list[str] = []
    if not account or not token:
        reasons.append("missing_account_or_token")
    if not artifact_dir.exists():
        reasons.append("artifact_dir_missing")
    if not llm_path.exists() or llm_chars < 280:
        reasons.append("llm_input_too_short")
    if not sidecar:
        reasons.append("sidecar_missing")
    if main_chars < 80:
        reasons.append("main_content_too_short")
    if not title or title == "微信公众平台":
        reasons.append("bad_or_missing_title")
    if not source_url:
        reasons.append("missing_source_url")
    warnings = (quality or {}).get("warnings") if isinstance(quality, dict) else []
    if isinstance(warnings, list) and warnings:
        reasons.append("quality_warnings")

    if not reasons:
        verdict = "ready"
    elif artifact_dir.exists() and llm_path.exists() and llm_chars >= 80:
        verdict = "review"
    else:
        verdict = "blocked"

    rel = ""
    try:
        rel = str(artifact_dir.relative_to(artifact_root))
    except ValueError:
        rel = f"{account}\\{token}"

    return {
        "source_name": source["name"],
        "source_kind": source["kind"],
        "account_key": account,
        "token": token,
        "title": title,
        "source_url": source_url,
        "original_short_url": first_string(record.get("original_short_url")),
        "artifact_root": str(artifact_root),
        "archive_root": str(archive_root) if str(archive_root) else "",
        "artifact_dir": str(artifact_dir),
        "relative_artifact_dir": rel,
        "llm_input_path": str(llm_path),
        "llm_chars": llm_chars,
        "main_content_chars": main_chars,
        "raw_html_bytes": raw_html_bytes,
        "poster_ocr_exists": poster_ocr_path.exists(),
        "sidecar_exists": bool(sidecar),
        "quality_report_exists": quality_path.exists(),
        "verdict": verdict,
        "reasons": reasons,
    }


def build_manifest() -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    source_summaries = []
    seen: set[str] = set()
    duplicate_count = 0
    for source in known_sources():
        queue_path = Path(source["queue_path"])
        records = read_jsonl(queue_path)
        source_ready = source_review = source_blocked = 0
        for record in records:
            row = validate_record(source, record)
            dedupe_key = row["source_url"] or f"{row['account_key']}\0{row['token']}"
            if dedupe_key in seen:
                duplicate_count += 1
                continue
            seen.add(dedupe_key)
            rows.append(row)
            if row["verdict"] == "ready":
                source_ready += 1
            elif row["verdict"] == "review":
                source_review += 1
            else:
                source_blocked += 1
        source_summaries.append(
            {
                "name": source["name"],
                "kind": source["kind"],
                "queue_path": str(queue_path),
                "artifact_root": str(source["artifact_root"]),
                "archive_root": str(source.get("archive_root") or ""),
                "queue_records": len(records),
                "ready": source_ready,
                "review": source_review,
                "blocked": source_blocked,
            }
        )

    counts = Counter(row["verdict"] for row in rows)
    reason_counts = Counter(reason for row in rows for reason in row["reasons"])
    kind_counts = Counter(row["source_kind"] for row in rows)
    return {
        "schema_version": "wechat_93k_llm_intake_manifest.v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "rows": rows,
        "summary": {
            "total": len(rows),
            "ready": counts.get("ready", 0),
            "review": counts.get("review", 0),
            "blocked": counts.get("blocked", 0),
            "duplicate_skipped": duplicate_count,
            "source_kind_counts": dict(kind_counts),
            "reason_counts": dict(reason_counts),
            "sources": source_summaries,
        },
    }


def write_outputs(out_dir: Path, manifest: dict[str, Any]) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = manifest["rows"]
    summary = manifest["summary"]
    json_path = out_dir / "llm_intake_manifest.json"
    jsonl_path = out_dir / "llm_intake_manifest.jsonl"
    ready_path = out_dir / "llm_ready_artifact_dirs.txt"
    review_path = out_dir / "llm_review_artifact_dirs.txt"
    blocked_path = out_dir / "llm_blocked_items.jsonl"
    md_path = out_dir / "SUMMARY.md"

    json_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    jsonl_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    ready_rows = [row for row in rows if row["verdict"] == "ready"]
    review_rows = [row for row in rows if row["verdict"] == "review"]
    blocked_rows = [row for row in rows if row["verdict"] == "blocked"]
    ready_path.write_text("".join(row["artifact_dir"] + "\n" for row in ready_rows), encoding="utf-8")
    review_path.write_text("".join(row["artifact_dir"] + "\n" for row in review_rows), encoding="utf-8")
    blocked_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in blocked_rows),
        encoding="utf-8",
    )
    lines = [
        "# LLM Intake Manifest",
        "",
        f"- generated_at: `{manifest['generated_at']}`",
        f"- total: `{summary['total']}`",
        f"- ready: `{summary['ready']}`",
        f"- review: `{summary['review']}`",
        f"- blocked: `{summary['blocked']}`",
        f"- duplicate_skipped: `{summary['duplicate_skipped']}`",
        "",
        "## Source Kinds",
        "",
    ]
    for key, value in summary["source_kind_counts"].items():
        lines.append(f"- `{key}`: {value}")
    lines.extend(["", "## Reason Counts", ""])
    for key, value in summary["reason_counts"].items():
        lines.append(f"- `{key}`: {value}")
    lines.extend(["", "## Sources", ""])
    for source in summary["sources"]:
        lines.append(
            f"- `{source['name']}` records={source['queue_records']} ready={source['ready']} review={source['review']} blocked={source['blocked']}"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "json": str(json_path),
        "jsonl": str(jsonl_path),
        "ready_dirs": str(ready_path),
        "review_dirs": str(review_path),
        "blocked_jsonl": str(blocked_path),
        "md": str(md_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build LLM intake manifest from recovered queues")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    manifest = build_manifest()
    paths = write_outputs(Path(args.out_dir), manifest)
    result = {"summary": manifest["summary"], "paths": paths}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.strict and manifest["summary"]["ready"] == 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
