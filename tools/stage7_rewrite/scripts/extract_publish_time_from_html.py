"""Extract true publish-time fields from directly referenced raw HTML files.

This is a bounded known-path reader: it follows each stable row's meta_path to
raw/artifact_manifest.json, then reads that manifest's inputPath. It never walks
D: or discovers files recursively.
"""

from __future__ import annotations

import argparse
import json
import re
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_STABLE_ARTICLES = Path(
    "reports/fullmap_47k_ready_text_authok_20260513_174006/"
    "stable_extract_v1/stable_articles.jsonl"
)
DEFAULT_OUT_DIR = Path("reports/publish_time_html_extraction_20260515")
SCHEMA_VERSION = "stage7_publish_time_html_extraction.v1"
META_RE = re.compile(
    r"<meta[^>]+(?:property|name)=[\"'](?P<name>og:article:published_time|article:published_time|wechat:published_time|publish_time|pubdate|datePublished)[\"'][^>]+content=[\"'](?P<value>[^\"']+)[\"'][^>]*>",
    re.IGNORECASE,
)
META_RE_REVERSED = re.compile(
    r"<meta[^>]+content=[\"'](?P<value>[^\"']+)[\"'][^>]+(?:property|name)=[\"'](?P<name>og:article:published_time|article:published_time|wechat:published_time|publish_time|pubdate|datePublished)[\"'][^>]*>",
    re.IGNORECASE,
)
JSON_FIELD_RE = re.compile(r"[\"'](?P<name>publish_time|publishTime|published_at|create_time|ct)[\"']\s*:\s*[\"']?(?P<value>[^\"',}\s;]+)", re.IGNORECASE)
VAR_FIELD_RE = re.compile(r"\bvar\s+(?P<name>publish_time|publishTime|createTime|ct)\s*=\s*[\"']?(?P<value>[^\"';\s]+)", re.IGNORECASE)


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def first_text(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def resolve_known_path(raw_path: str | Path) -> Path:
    text = str(raw_path)
    if text.startswith("/mnt/d/"):
        return Path("D:/" + text[len("/mnt/d/") :])
    if text.startswith("/mnt/c/"):
        return Path("C:/" + text[len("/mnt/c/") :])
    return Path(text)


def reject_unbounded_d_root(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower().rstrip("/")
    if raw in {"d:", "d:/", "/mnt/d", "/mnt/d/"}:
        raise ValueError(f"{label} must not be an unbounded D: root")


def read_json_if_exists(path: Path) -> dict[str, Any]:
    reject_unbounded_d_root(path, "json")
    if not path.exists() or not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}


def artifact_manifest_path(meta_path: Path) -> Path:
    return meta_path.parent / "artifact_manifest.json"


def normalize_time(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    if re.fullmatch(r"\d{10}", text):
        return datetime.fromtimestamp(int(text), tz=timezone.utc).date().isoformat()
    if re.fullmatch(r"\d{13}", text):
        return datetime.fromtimestamp(int(text) / 1000, tz=timezone.utc).date().isoformat()
    match = re.search(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})", text)
    if match:
        year, month, day = map(int, match.groups())
        try:
            return datetime(year, month, day).date().isoformat()
        except ValueError:
            return ""
    return text if re.match(r"20\d{2}-\d{2}-\d{2}", text) else ""


def find_html_publish_time(html: str) -> tuple[str, str, str]:
    for regex in (META_RE, META_RE_REVERSED, JSON_FIELD_RE, VAR_FIELD_RE):
        for match in regex.finditer(html):
            normalized = normalize_time(match.group("value"))
            if normalized:
                return normalized, f"html.{match.group('name')}", match.group(0)[:200]
    return "", "", ""


def extract_row(article: dict[str, Any], *, max_bytes: int = 2_000_000) -> dict[str, Any]:
    article_uid = first_text(article.get("article_uid"))
    meta_raw = first_text(article.get("meta_path"))
    row = {
        "schema_version": SCHEMA_VERSION,
        "article_uid": article_uid,
        "article_id": first_text(article.get("article_id")),
        "source_account": first_text(article.get("source_account")),
        "title": first_text(article.get("title")),
        "meta_path": meta_raw,
        "raw_html_path": "",
        "publish_time": "",
        "publish_time_source": "",
        "original_text_matched": "",
        "status": "missing_artifact_manifest",
        "bytes_read": 0,
        "files_checked": [],
        "files_missing": [],
        "writes": "reports_only",
    }
    if not meta_raw:
        row["status"] = "missing_meta_path"
        return row
    meta_path = resolve_known_path(meta_raw)
    artifact_path = artifact_manifest_path(meta_path)
    artifact = read_json_if_exists(artifact_path)
    if not artifact:
        row["files_missing"].append(str(artifact_path))
        return row
    row["files_checked"].append(str(artifact_path))
    raw_path_text = first_text(artifact.get("inputPath"), artifact.get("input_path"))
    if not raw_path_text:
        row["status"] = "missing_raw_html_path"
        return row
    raw_path = resolve_known_path(raw_path_text)
    row["raw_html_path"] = str(raw_path)
    reject_unbounded_d_root(raw_path, "raw_html")
    if not raw_path.exists() or not raw_path.is_file():
        row["status"] = "missing_raw_html"
        row["files_missing"].append(str(raw_path))
        return row
    size = raw_path.stat().st_size
    if size > max_bytes:
        row["status"] = "raw_html_too_large"
        row["bytes_read"] = size
        return row
    html = raw_path.read_text(encoding="utf-8", errors="replace")
    row["files_checked"].append(str(raw_path))
    row["bytes_read"] = len(html.encode("utf-8", errors="replace"))
    publish_time, source, matched = find_html_publish_time(html)
    if publish_time:
        row["publish_time"] = publish_time
        row["publish_time_source"] = source
        row["original_text_matched"] = matched
        row["status"] = "html_publish_time_found"
    else:
        row["status"] = "html_no_publish_time"
    return row


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
        "# Publish-Time HTML Extraction",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- rows: `{summary['rows']}`",
        f"- limit: `{summary['limit']}`",
        f"- publish_time_found: `{summary['publish_time_found']}`",
        "",
        "## Status Counts",
        "",
    ]
    for key, value in summary["status_counts"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Safety", "", "- Reads only raw HTML paths from artifact_manifest.json.", "- No D: directory scan, no API, no DB writes, no publish.", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def build_html_index(stable_articles: Path, out_dir: Path, *, limit: int = 2000, max_bytes: int = 2_000_000) -> dict[str, Any]:
    reject_unbounded_d_root(stable_articles, "stable_articles")
    reject_unbounded_d_root(out_dir, "out_dir")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "html_dates.jsonl"
    tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
    rows = 0
    status_counts: Counter[str] = Counter()
    publish_time_found = 0
    checked_files = 0
    missing_files = 0
    with stable_articles.open("r", encoding="utf-8") as source, tmp_path.open("w", encoding="utf-8") as out:
        for line in source:
            if limit and rows >= limit:
                break
            stripped = line.strip()
            if not stripped:
                continue
            row = extract_row(json.loads(stripped), max_bytes=max_bytes)
            status_counts[row["status"]] += 1
            checked_files += len(row["files_checked"])
            missing_files += len(row["files_missing"])
            if row["publish_time"]:
                publish_time_found += 1
            out.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            rows += 1
    tmp_path.replace(out_path)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "stable_articles": str(stable_articles),
        "out_dir": str(out_dir),
        "limit": limit,
        "rows": rows,
        "publish_time_found": publish_time_found,
        "status_counts": dict(sorted(status_counts.items())),
        "checked_files": checked_files,
        "missing_files": missing_files,
        "html_dates_path": str(out_path),
        "writes": "reports_only",
    }
    write_json(out_dir / "html_dates_summary.json", summary)
    write_summary_md(out_dir / "html_dates_summary.md", summary)
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stable-articles", type=Path, default=DEFAULT_STABLE_ARTICLES)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--limit", type=int, default=2000, help="0 means all rows")
    parser.add_argument("--max-bytes", type=int, default=2_000_000)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = build_html_index(args.stable_articles, args.out_dir, limit=args.limit, max_bytes=args.max_bytes)
    print(
        json.dumps(
            {
                "rows": summary["rows"],
                "publish_time_found": summary["publish_time_found"],
                "status_counts": summary["status_counts"],
                "summary": str(args.out_dir / "html_dates_summary.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
