#!/usr/bin/env python3
"""Offline compatibility gate for Stage7 consumer packs with unknown publish time.

This script checks whether a staging release pointer can be consumed by the
current weekly mini-program / CloudRun code when article publish_time is
unknown. It is report-only: no publish, no production SQLite write, no paid API,
no Qdrant/Neo4j mutation, and no D: scan.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
STAGE7_ROOT = SCRIPT_DIR.parent
REPO_ROOT = SCRIPT_DIR.parents[2]
DEFAULT_POINTER = STAGE7_ROOT / "reports/consumer_release_pack_full_unknown_time_20260514/release_pointer.staging.json"
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports/consumer_unknown_time_compat_20260514"
POINTER_SCHEMA = "stage7_consumer_release_pointer.v1"
PACK_SCHEMA = "stage7_consumer_release_pack.v1"
TOKEN_RE = re.compile(r"\b(post_date|publish_time)\b")

SCAN_PATHS = [
    Path("apps/weekly_activity_miniprogram/utils"),
    Path("apps/weekly_activity_miniprogram/pages"),
    Path("services/weekly_activity_cloudrun/src"),
]
ALLOWED_DEPENDENCIES = {
    ("apps/weekly_activity_miniprogram/pages/index/index.js", "post_date"): "nullable_new_tab_sort",
    ("services/weekly_activity_cloudrun/src/llmEnrichment.mjs", "post_date"): "optional_llm_metadata",
}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for unknown-time compat gate: {path}")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def as_repo_rel(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def resolve_pointer_file(raw_path: str, pointer_path: Path) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    candidates = [
        STAGE7_ROOT / path,
        pointer_path.parent / path,
        pointer_path.parent / path.name,
        Path.cwd() / path,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def iter_scan_files(repo_root: Path) -> list[Path]:
    files: list[Path] = []
    for rel in SCAN_PATHS:
        base = repo_root / rel
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix not in {".js", ".mjs", ".wxml"}:
                continue
            if any(part in {"node_modules", "data", "release"} for part in path.parts):
                continue
            files.append(path)
    return sorted(files)


def classify_dependency(rel_path: str, token: str, line: str) -> tuple[str, str]:
    allowed = ALLOWED_DEPENDENCIES.get((rel_path, token))
    if allowed == "nullable_new_tab_sort":
        if 'String(b.post_date || "")' in line and 'String(a.post_date || "")' in line:
            return allowed, "ok"
        return allowed, "review_required"
    if allowed:
        return allowed, "ok"
    return "unexpected_dependency", "review_required"


def scan_code_dependencies(repo_root: Path) -> dict[str, Any]:
    hits: list[dict[str, Any]] = []
    errors: list[str] = []
    for path in iter_scan_files(repo_root):
        rel = as_repo_rel(path, repo_root)
        for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
            for match in TOKEN_RE.finditer(line):
                token = match.group(1)
                classification, status = classify_dependency(rel, token, line.strip())
                row = {
                    "path": rel,
                    "line": line_no,
                    "token": token,
                    "classification": classification,
                    "status": status,
                    "text": line.strip(),
                }
                hits.append(row)
                if status != "ok":
                    errors.append(f"{rel}:{line_no} {token} requires review")
    return {
        "ok": not errors,
        "hits": hits,
        "errors": errors,
    }


def compact_item_body(format_js: Path) -> str:
    text = format_js.read_text(encoding="utf-8", errors="replace")
    start = text.find("function compactItem")
    end = text.find("module.exports", start)
    if start == -1:
        return ""
    if end == -1:
        return text[start:]
    return text[start:end]


def check_consumer_contracts(repo_root: Path) -> dict[str, Any]:
    format_js = repo_root / "apps/weekly_activity_miniprogram/utils/format.js"
    mini_api_js = repo_root / "apps/weekly_activity_miniprogram/utils/api.js"
    datastore_mjs = repo_root / "services/weekly_activity_cloudrun/src/dataStore.mjs"
    contracts: dict[str, Any] = {
        "miniapp_compact_item": {"ok": False, "path": as_repo_rel(format_js, repo_root), "checks": {}},
        "miniapp_static_filter": {"ok": False, "path": as_repo_rel(mini_api_js, repo_root), "checks": {}},
        "cloudrun_filter": {"ok": False, "path": as_repo_rel(datastore_mjs, repo_root), "checks": {}},
    }
    errors: list[str] = []

    if format_js.exists():
        body = compact_item_body(format_js)
        checks = {
            "exists": True,
            "uses_event_date_for_display": "event_date_start || item.event_date_iso_guess" in body,
            "does_not_use_post_date": "post_date" not in body and "publish_time" not in body,
        }
        contracts["miniapp_compact_item"]["checks"] = checks
        contracts["miniapp_compact_item"]["ok"] = all(checks.values())
    else:
        contracts["miniapp_compact_item"]["checks"] = {"exists": False}
    if not contracts["miniapp_compact_item"]["ok"]:
        errors.append("miniapp compactItem publish-time independence check failed")

    if mini_api_js.exists():
        text = mini_api_js.read_text(encoding="utf-8", errors="replace")
        checks = {
            "exists": True,
            "date_filter_uses_event_date": "itemMatchesDate(item, filters.date)" in text
            and "function itemDateKeys" in text
            and "event_date_iso_guess" in text,
            "static_current_response_present": "currentResponseFromStatic" in text,
        }
        contracts["miniapp_static_filter"]["checks"] = checks
        contracts["miniapp_static_filter"]["ok"] = all(checks.values())
    else:
        contracts["miniapp_static_filter"]["checks"] = {"exists": False}
    if not contracts["miniapp_static_filter"]["ok"]:
        errors.append("miniapp static fallback date-filter check failed")

    if datastore_mjs.exists():
        text = datastore_mjs.read_text(encoding="utf-8", errors="replace")
        checks = {
            "exists": True,
            "current_filter_uses_event_date": "itemMatchesDate(item, date)" in text
            and "function itemDateKeys" in text
            and "event_date_iso_guess" in text,
            "dates_fallback_unknown": 'itemDates.length ? itemDates : ["unknown"]' in text,
        }
        contracts["cloudrun_filter"]["checks"] = checks
        contracts["cloudrun_filter"]["ok"] = all(checks.values())
    else:
        contracts["cloudrun_filter"]["checks"] = {"exists": False}
    if not contracts["cloudrun_filter"]["ok"]:
        errors.append("CloudRun event-date fallback contract check failed")

    return {"ok": not errors, "contracts": contracts, "errors": errors}


def sample_jsonl(path: Path, sample_count: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if len(rows) >= sample_count:
                break
            stripped = line.strip()
            if not stripped:
                continue
            row = json.loads(stripped)
            if isinstance(row, dict):
                rows.append(row)
    return rows


def check_pack(pointer_path: Path, sample_count: int) -> dict[str, Any]:
    reject_d_path(pointer_path, "pointer")
    pointer = read_json(pointer_path)
    errors: list[str] = []
    warnings: list[str] = []
    if pointer.get("schema_version") != POINTER_SCHEMA:
        errors.append(f"bad pointer schema_version: {pointer.get('schema_version')!r}")
    if pointer.get("channel") != "staging":
        errors.append(f"pointer channel must be staging, got {pointer.get('channel')!r}")
    if not pointer.get("release_ready"):
        errors.append("pointer release_ready is false")
    policy = pointer.get("publish_time_policy") or {}
    allow_unknown = bool(policy.get("allow_unknown_publish_time"))
    if not allow_unknown:
        errors.append("pointer must explicitly allow unknown publish_time for this staging lane")

    files = pointer.get("files") or {}
    articles_path = resolve_pointer_file(str((files.get("articles") or {}).get("path") or ""), pointer_path)
    events_path = resolve_pointer_file(str((files.get("events") or {}).get("path") or ""), pointer_path)
    manifest_path = resolve_pointer_file(str((files.get("manifest") or {}).get("path") or ""), pointer_path)
    for label, path in {"articles": articles_path, "events": events_path, "manifest": manifest_path}.items():
        reject_d_path(path, label)
        if not path.exists():
            errors.append(f"missing {label} file: {path}")

    article_rows = sample_jsonl(articles_path, sample_count) if articles_path.exists() else []
    event_rows = sample_jsonl(events_path, sample_count) if events_path.exists() else []
    article_status_counts: dict[str, int] = {}
    for idx, row in enumerate(article_rows, start=1):
        if row.get("schema_version") != PACK_SCHEMA:
            errors.append(f"article sample {idx} bad schema")
        status = str(row.get("publish_time_status") or "")
        article_status_counts[status] = article_status_counts.get(status, 0) + 1
        if status == "unknown" and row.get("publish_time"):
            errors.append(f"article sample {idx} has publish_time despite unknown status")
        if status not in {"known", "unknown"}:
            errors.append(f"article sample {idx} bad publish_time_status {status!r}")

    event_time_populated = 0
    for idx, row in enumerate(event_rows, start=1):
        if row.get("schema_version") != PACK_SCHEMA:
            errors.append(f"event sample {idx} bad schema")
        if row.get("time_iso") or row.get("time_text"):
            event_time_populated += 1
    if event_rows and not event_time_populated:
        warnings.append("sampled event rows do not expose time_iso/time_text; consumer date grouping may be sparse")

    counts = pointer.get("counts") or {}
    missing = int(counts.get("missing_publish_time_articles") or 0)
    articles = int(counts.get("articles") or 0)
    if articles and missing == articles:
        warnings.append("all release-pack articles have unknown publish_time; production publish remains blocked")
    manifest = read_json(manifest_path) if manifest_path.exists() else {}
    if manifest and manifest.get("schema_version") != PACK_SCHEMA:
        errors.append(f"bad manifest schema_version: {manifest.get('schema_version')!r}")

    return {
        "ok": not errors,
        "pointer_path": str(pointer_path),
        "channel": pointer.get("channel"),
        "release_ready": bool(pointer.get("release_ready")),
        "counts": counts,
        "publish_time_policy": policy,
        "article_sample_count": len(article_rows),
        "event_sample_count": len(event_rows),
        "article_status_counts": article_status_counts,
        "event_time_populated": event_time_populated,
        "warnings": warnings,
        "errors": errors,
    }


def validate_compat(pointer_path: Path, repo_root: Path, sample_count: int) -> dict[str, Any]:
    reject_d_path(repo_root, "repo_root")
    pack = check_pack(pointer_path, sample_count)
    dependencies = scan_code_dependencies(repo_root)
    contracts = check_consumer_contracts(repo_root)
    errors = [*pack["errors"], *dependencies["errors"], *contracts["errors"]]
    warnings = [*pack["warnings"]]
    report = {
        "schema_version": "stage7_consumer_unknown_time_compat.v1",
        "generated_at": now_iso(),
        "ok": not errors,
        "decision": "consumer_unknown_time_staging_compatible" if not errors else "consumer_unknown_time_staging_blocked",
        "repo_root": str(repo_root),
        "pack": pack,
        "code_dependencies": dependencies,
        "consumer_contracts": contracts,
        "warnings": warnings,
        "errors": errors,
        "writes": "reports_only",
        "safety": [
            "no production publish",
            "no production SQLite write",
            "no paid API call",
            "no Qdrant/Neo4j write",
            "no D: scan",
        ],
    }
    return report


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    pack = report["pack"]
    deps = report["code_dependencies"]
    contracts = report["consumer_contracts"]
    lines = [
        "# Stage7 Consumer Unknown-Time Compatibility",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- ok: `{report['ok']}`",
        f"- decision: `{report['decision']}`",
        f"- pointer: `{pack['pointer_path']}`",
        f"- article_sample_count: `{pack['article_sample_count']}`",
        f"- event_sample_count: `{pack['event_sample_count']}`",
        f"- article_status_counts: `{json.dumps(pack['article_status_counts'], ensure_ascii=False, sort_keys=True)}`",
        f"- event_time_populated: `{pack['event_time_populated']}`",
        "",
        "## Code Dependencies",
        "",
        f"- ok: `{deps['ok']}`",
        f"- hits: `{len(deps['hits'])}`",
        "",
    ]
    for hit in deps["hits"]:
        lines.append(
            f"- `{hit['path']}:{hit['line']}` token=`{hit['token']}` "
            f"classification=`{hit['classification']}` status=`{hit['status']}`"
        )
    lines.extend(["", "## Consumer Contracts", ""])
    for name, item in contracts["contracts"].items():
        lines.append(f"- `{name}` ok=`{item['ok']}` checks=`{json.dumps(item['checks'], ensure_ascii=False, sort_keys=True)}`")
    lines.extend(["", "## Warnings", ""])
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
    report = validate_compat(args.pointer, args.repo_root, args.sample_count)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.out_dir / "consumer_unknown_time_compat.json", report)
    write_markdown(args.out_dir / "consumer_unknown_time_compat.md", report)
    print(
        json.dumps(
            {
                "ok": report["ok"],
                "decision": report["decision"],
                "warnings": len(report["warnings"]),
                "errors": len(report["errors"]),
                "report": str(args.out_dir / "consumer_unknown_time_compat.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["ok"] else 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pointer", type=Path, default=DEFAULT_POINTER)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--sample-count", type=int, default=50)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
