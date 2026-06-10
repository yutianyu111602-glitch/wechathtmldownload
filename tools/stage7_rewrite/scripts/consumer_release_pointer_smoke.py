#!/usr/bin/env python3
"""Validate a Stage7 consumer release pointer before downstream use.

This is an offline staging gate. It reads the pointer and local release-pack
files, verifies file integrity and minimum consumer row shape, and writes a
report. It does not publish, write production SQLite, call paid APIs, touch
Qdrant/Neo4j, or scan D:.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_POINTER = Path(
    "reports/consumer_release_pack_full_unknown_time_20260514/release_pointer.staging.json"
)
DEFAULT_OUT_DIR = Path("reports/consumer_release_pointer_smoke_20260514")
POINTER_SCHEMA = "stage7_consumer_release_pointer.v1"
PACK_SCHEMA = "stage7_consumer_release_pack.v1"
REQUIRED_BY_KIND = {
    "articles": [
        "schema_version",
        "card_type",
        "article_uid",
        "source_account",
        "title",
        "publish_time_status",
        "entity_count",
        "event_count",
        "extract_version",
        "vector_text",
    ],
    "entities": [
        "schema_version",
        "card_type",
        "eid",
        "name",
        "type",
        "confidence",
        "source_article_uid",
        "source_kind",
        "vector_text",
    ],
    "events": [
        "schema_version",
        "card_type",
        "evid",
        "name",
        "confidence",
        "source_article_uid",
        "source_kind",
        "vector_text",
    ],
}
EXPECTED_CARD_TYPE = {"articles": "article", "entities": "entity", "events": "event"}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for consumer pointer smoke: {path}")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def sha256_and_line_count(path: Path) -> tuple[str, int]:
    h = hashlib.sha256()
    lines = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
            lines += chunk.count(b"\n")
    return h.hexdigest(), lines


def resolve_from_pointer(raw_path: str, pointer_path: Path) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    candidates = [
        Path.cwd() / path,
        pointer_path.parent / path,
        pointer_path.parent / path.name,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def is_present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str) and not value.strip():
        return False
    return True


def validate_sample_row(kind: str, row: dict[str, Any], allow_unknown_publish_time: bool) -> list[str]:
    errors = []
    for field in REQUIRED_BY_KIND[kind]:
        if not is_present(row.get(field)):
            errors.append(f"missing {field}")
    if row.get("schema_version") != PACK_SCHEMA:
        errors.append(f"bad schema_version {row.get('schema_version')!r}")
    expected_type = EXPECTED_CARD_TYPE[kind]
    if row.get("card_type") != expected_type:
        errors.append(f"bad card_type {row.get('card_type')!r}, expected {expected_type!r}")
    if kind == "articles":
        status = str(row.get("publish_time_status") or "")
        publish_time = str(row.get("publish_time") or "")
        if status == "unknown" and publish_time:
            errors.append("unknown publish_time_status with non-empty publish_time")
        if status == "unknown" and not allow_unknown_publish_time:
            errors.append("unknown publish_time_status but pointer policy forbids it")
        if status not in {"known", "unknown"}:
            errors.append(f"bad publish_time_status {status!r}")
    else:
        try:
            confidence = float(row.get("confidence"))
        except (TypeError, ValueError):
            errors.append("confidence is not numeric")
        else:
            if confidence < 0.5:
                errors.append(f"confidence below staging threshold: {confidence}")
    return errors


def sample_jsonl(path: Path, sample_count: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = []
    parse_errors = []
    with path.open("r", encoding="utf-8") as handle:
        for idx, line in enumerate(handle, start=1):
            if len(rows) >= sample_count:
                break
            stripped = line.strip()
            if not stripped:
                continue
            try:
                row = json.loads(stripped)
            except json.JSONDecodeError as exc:
                parse_errors.append({"line": idx, "error": str(exc)})
                continue
            if isinstance(row, dict):
                rows.append(row)
            else:
                parse_errors.append({"line": idx, "error": "row is not a JSON object"})
    return rows, parse_errors


def validate_pointer(pointer_path: Path, sample_per_file: int, full_count: bool) -> dict[str, Any]:
    reject_d_path(pointer_path, "pointer")
    pointer = read_json(pointer_path)
    allow_unknown = bool((pointer.get("publish_time_policy") or {}).get("allow_unknown_publish_time"))
    report: dict[str, Any] = {
        "schema_version": "stage7_consumer_release_pointer_smoke.v1",
        "generated_at": now_iso(),
        "pointer_path": str(pointer_path),
        "pointer_schema_ok": pointer.get("schema_version") == POINTER_SCHEMA,
        "channel": pointer.get("channel"),
        "release_ready": bool(pointer.get("release_ready")),
        "decision": pointer.get("decision"),
        "publish_time_policy": pointer.get("publish_time_policy") or {},
        "full_count": full_count,
        "sample_per_file": sample_per_file,
        "files": {},
        "errors": [],
        "warnings": [],
        "writes": "reports_only",
    }
    if not report["pointer_schema_ok"]:
        report["errors"].append(f"bad pointer schema_version: {pointer.get('schema_version')!r}")
    if pointer.get("channel") != "staging":
        report["errors"].append(f"pointer channel must be staging, got {pointer.get('channel')!r}")
    if not pointer.get("release_ready"):
        report["errors"].append("pointer release_ready is false")
    if "publish" in str(pointer.get("writes") or "").lower() and "no publish" not in str(pointer.get("writes") or "").lower():
        report["warnings"].append("pointer writes field mentions publish; review before downstream use")

    pointer_counts = pointer.get("counts") or {}
    pointer_files = pointer.get("files") or {}
    for kind in ("manifest", "articles", "entities", "events"):
        info = pointer_files.get(kind) or {}
        path_raw = str(info.get("path") or "")
        if not path_raw:
            report["errors"].append(f"pointer missing file path for {kind}")
            continue
        path = resolve_from_pointer(path_raw, pointer_path)
        reject_d_path(path, kind)
        file_report: dict[str, Any] = {
            "path": str(path),
            "exists": path.exists(),
            "expected_bytes": info.get("bytes"),
            "actual_bytes": None,
            "bytes_ok": False,
            "expected_sha256": info.get("sha256"),
            "actual_sha256": None,
            "sha256_ok": False,
        }
        if not path.exists():
            report["errors"].append(f"missing file for {kind}: {path}")
            report["files"][kind] = file_report
            continue
        file_report["actual_bytes"] = path.stat().st_size
        file_report["bytes_ok"] = file_report["actual_bytes"] == info.get("bytes")
        if not file_report["bytes_ok"]:
            report["errors"].append(f"{kind} bytes mismatch")
        actual_sha, line_count = sha256_and_line_count(path)
        file_report["actual_sha256"] = actual_sha
        file_report["sha256_ok"] = actual_sha == info.get("sha256")
        if not file_report["sha256_ok"]:
            report["errors"].append(f"{kind} sha256 mismatch")
        if kind != "manifest":
            expected_count = pointer_counts.get(kind)
            file_report["line_count"] = line_count if full_count else None
            file_report["expected_count"] = expected_count
            file_report["count_ok"] = (line_count == expected_count) if full_count else None
            if full_count and line_count != expected_count:
                report["errors"].append(f"{kind} line count mismatch: {line_count} != {expected_count}")
            rows, parse_errors = sample_jsonl(path, sample_per_file)
            file_report["sample_count"] = len(rows)
            file_report["sample_parse_errors"] = parse_errors
            file_report["sample_errors"] = []
            for idx, row in enumerate(rows, start=1):
                for error in validate_sample_row(kind, row, allow_unknown):
                    file_report["sample_errors"].append({"sample": idx, "error": error})
            if parse_errors:
                report["errors"].append(f"{kind} sample parse errors")
            if file_report["sample_errors"]:
                report["errors"].append(f"{kind} sample schema errors")
        report["files"][kind] = file_report

    manifest_info = report["files"].get("manifest") or {}
    manifest_path = Path(str(manifest_info.get("path") or ""))
    if manifest_path.exists():
        manifest = read_json(manifest_path)
        if manifest.get("schema_version") != PACK_SCHEMA:
            report["errors"].append(f"bad manifest schema_version: {manifest.get('schema_version')!r}")
        for count_key in ("articles", "entities", "events", "missing_publish_time_articles"):
            if manifest.get(count_key) != pointer_counts.get(count_key):
                report["errors"].append(f"manifest/pointer count mismatch for {count_key}")
        if bool(manifest.get("allow_unknown_publish_time")) != allow_unknown:
            report["errors"].append("manifest/pointer allow_unknown_publish_time mismatch")

    missing = int(pointer_counts.get("missing_publish_time_articles") or 0)
    articles = int(pointer_counts.get("articles") or 0)
    if missing and not allow_unknown:
        report["errors"].append("missing publish_time rows require allow_unknown_publish_time")
    if missing == articles and allow_unknown:
        report["warnings"].append("all articles have unknown publish_time; staging only, production publish remains blocked")

    report["ok"] = not report["errors"]
    report["decision"] = "consumer_staging_pointer_verified" if report["ok"] else "consumer_staging_pointer_blocked"
    return report


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Stage7 Consumer Release Pointer Smoke",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- ok: `{report['ok']}`",
        f"- decision: `{report['decision']}`",
        f"- pointer: `{report['pointer_path']}`",
        f"- channel: `{report['channel']}`",
        f"- release_ready: `{report['release_ready']}`",
        f"- full_count: `{report['full_count']}`",
        "",
        "## Files",
        "",
    ]
    for kind, item in report["files"].items():
        lines.extend(
            [
                f"### {kind}",
                "",
                f"- exists: `{item.get('exists')}`",
                f"- bytes_ok: `{item.get('bytes_ok')}`",
                f"- sha256_ok: `{item.get('sha256_ok')}`",
            ]
        )
        if kind != "manifest":
            lines.extend(
                [
                    f"- expected_count: `{item.get('expected_count')}`",
                    f"- line_count: `{item.get('line_count')}`",
                    f"- count_ok: `{item.get('count_ok')}`",
                    f"- sample_count: `{item.get('sample_count')}`",
                    f"- sample_errors: `{len(item.get('sample_errors') or [])}`",
                    "",
                ]
            )
        else:
            lines.append("")
    lines.extend(["## Warnings", ""])
    if report["warnings"]:
        for warning in report["warnings"]:
            lines.append(f"- `{warning}`")
    else:
        lines.append("- none")
    lines.extend(["", "## Errors", ""])
    if report["errors"]:
        for error in report["errors"]:
            lines.append(f"- `{error}`")
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Reports only.",
            "- No production publish.",
            "- No production SQLite write.",
            "- No paid API call.",
            "- No Qdrant/Neo4j write.",
            "- No D: scan.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    report = validate_pointer(args.pointer, args.sample_per_file, not args.skip_full_count)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.out_dir / "consumer_release_pointer_smoke.json", report)
    write_markdown(args.out_dir / "consumer_release_pointer_smoke.md", report)
    print(
        json.dumps(
            {
                "ok": report["ok"],
                "decision": report["decision"],
                "warnings": len(report["warnings"]),
                "errors": len(report["errors"]),
                "report": str(args.out_dir / "consumer_release_pointer_smoke.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["ok"] else 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pointer", type=Path, default=DEFAULT_POINTER)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--sample-per-file", type=int, default=20)
    parser.add_argument("--skip-full-count", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
