"""Consolidate report-only publish-time candidates by source priority."""

from __future__ import annotations

import argparse
import json
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_CONTENT = Path("reports/publish_time_content_extraction_20260515/content_dates.jsonl")
DEFAULT_HTML = Path("reports/publish_time_html_extraction_20260515/html_dates.jsonl")
DEFAULT_URL = Path("reports/publish_time_url_analysis_20260515/url_dates.jsonl")
DEFAULT_OUT_DIR = Path("reports/publish_time_consolidated_20260515")
SCHEMA_VERSION = "stage7_publish_time_consolidated.v1"
PRIORITY = {"html_publish_time_found": 0, "publish_time_candidate": 1, "url_publish_time_found": 2}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for consolidation: {path}")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_d_path(path, "input")
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                rows.append(json.loads(stripped))
    return rows


def candidate_priority(row: dict[str, Any]) -> int:
    if not row.get("publish_time"):
        return 999
    return PRIORITY.get(str(row.get("status")), 500)


def consolidate_rows(*sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_uid: dict[str, list[dict[str, Any]]] = {}
    for source_rows in sources:
        for row in source_rows:
            uid = str(row.get("article_uid") or "").strip()
            if uid:
                by_uid.setdefault(uid, []).append(row)
    output: list[dict[str, Any]] = []
    for uid, rows in sorted(by_uid.items()):
        best = sorted(rows, key=candidate_priority)[0]
        publish_time = str(best.get("publish_time") or "")
        output.append(
            {
                "schema_version": SCHEMA_VERSION,
                "article_uid": uid,
                "article_id": best.get("article_id") or "",
                "source_account": best.get("source_account") or "",
                "title": best.get("title") or "",
                "publish_time": publish_time,
                "publish_time_source": best.get("publish_time_source") or "",
                "publish_time_confidence": best.get("publish_time_confidence", 1.0 if publish_time else 0.0),
                "status": "publish_time_found" if publish_time else "publish_time_missing",
                "selected_source_status": best.get("status") or "",
                "needs_manual_review": bool(best.get("needs_manual_review", False)) if publish_time else False,
                "writes": "reports_only",
            }
        )
    return output


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_summary_md(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# Publish-Time Consolidated Index",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- rows: `{summary['rows']}`",
        f"- publish_time_found: `{summary['publish_time_found']}`",
        "",
        "## Status Counts",
        "",
    ]
    for key, value in summary["status_counts"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Safety", "", "- Report-only consolidation.", "- Does not promote content/event dates without a publish_time field.", "- No DB writes, no publish.", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def build_consolidated(content: Path, html: Path, url: Path, out_dir: Path) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = consolidate_rows(read_jsonl(content), read_jsonl(html), read_jsonl(url))
    out_path = out_dir / "publish_time_index.jsonl"
    tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
    status_counts: Counter[str] = Counter()
    publish_time_found = 0
    with tmp_path.open("w", encoding="utf-8") as out:
        for row in rows:
            status_counts[row["status"]] += 1
            if row["publish_time"]:
                publish_time_found += 1
            out.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    tmp_path.replace(out_path)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "rows": len(rows),
        "publish_time_found": publish_time_found,
        "status_counts": dict(sorted(status_counts.items())),
        "content": str(content),
        "html": str(html),
        "url": str(url),
        "index_path": str(out_path),
        "writes": "reports_only",
    }
    write_json(out_dir / "publish_time_consolidated_summary.json", summary)
    write_summary_md(out_dir / "publish_time_consolidated_summary.md", summary)
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--content-extraction", type=Path, default=DEFAULT_CONTENT)
    parser.add_argument("--html-extraction", type=Path, default=DEFAULT_HTML)
    parser.add_argument("--url-analysis", type=Path, default=DEFAULT_URL)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = build_consolidated(args.content_extraction, args.html_extraction, args.url_analysis, args.out_dir)
    print(json.dumps({"rows": summary["rows"], "publish_time_found": summary["publish_time_found"], "status_counts": summary["status_counts"], "summary": str(args.out_dir / "publish_time_consolidated_summary.json")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
