"""Analyze WeChat article URL parameters without inferring unsupported dates."""

from __future__ import annotations

import argparse
import json
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


DEFAULT_STABLE_ARTICLES = Path(
    "reports/fullmap_47k_ready_text_authok_20260513_174006/"
    "stable_extract_v1/stable_articles.jsonl"
)
DEFAULT_OUT_DIR = Path("reports/publish_time_url_analysis_20260515")
SCHEMA_VERSION = "stage7_publish_time_url_analysis.v1"
URL_KEYS = ("url", "article_url", "source_url", "original_url", "wechat_url", "mp_url")


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


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for URL timestamp analysis: {path}")


def article_url(article: dict[str, Any]) -> tuple[str, str]:
    for key in URL_KEYS:
        text = first_text(article.get(key))
        if text:
            return text, key
    source = article.get("_source")
    if isinstance(source, dict):
        for key in URL_KEYS:
            text = first_text(source.get(key))
            if text:
                return text, f"_source.{key}"
    return "", ""


def analyze_row(article: dict[str, Any]) -> dict[str, Any]:
    url, url_source = article_url(article)
    row = {
        "schema_version": SCHEMA_VERSION,
        "article_uid": first_text(article.get("article_uid")),
        "article_id": first_text(article.get("article_id")),
        "source_account": first_text(article.get("source_account")),
        "title": first_text(article.get("title")),
        "url": url,
        "url_source": url_source,
        "mid": "",
        "idx": "",
        "biz": "",
        "sn_present": False,
        "publish_time": "",
        "publish_time_source": "",
        "status": "no_url_field",
        "notes": "No URL field is present in the C-side stable row.",
        "writes": "reports_only",
    }
    if not url:
        return row
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    row["mid"] = first_text(*(params.get("mid") or []))
    row["idx"] = first_text(*(params.get("idx") or []))
    row["biz"] = first_text(*(params.get("__biz") or []))
    row["sn_present"] = bool(first_text(*(params.get("sn") or [])))
    if row["mid"]:
        row["status"] = "url_mid_observed_no_time_mapping"
        row["notes"] = "mid is observable, but no source-backed calibration maps it to publish_time."
    else:
        row["status"] = "url_no_mid"
        row["notes"] = "URL is present but has no mid parameter."
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
        "# Publish-Time URL Analysis",
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
    lines.extend(["", "## Safety", "", "- Pure C-side URL field analysis.", "- Does not infer dates from mid without source-backed calibration.", "- No D: scan, no API, no DB writes, no publish.", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def build_url_analysis(stable_articles: Path, out_dir: Path, limit: int = 0) -> dict[str, Any]:
    reject_d_path(stable_articles, "stable_articles")
    reject_d_path(out_dir, "out_dir")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "url_dates.jsonl"
    tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
    rows = 0
    publish_time_found = 0
    status_counts: Counter[str] = Counter()
    with stable_articles.open("r", encoding="utf-8") as source, tmp_path.open("w", encoding="utf-8") as out:
        for line in source:
            if limit and rows >= limit:
                break
            stripped = line.strip()
            if not stripped:
                continue
            row = analyze_row(json.loads(stripped))
            status_counts[row["status"]] += 1
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
        "url_dates_path": str(out_path),
        "writes": "reports_only",
    }
    write_json(out_dir / "url_dates_summary.json", summary)
    write_summary_md(out_dir / "url_dates_summary.md", summary)
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stable-articles", type=Path, default=DEFAULT_STABLE_ARTICLES)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--limit", type=int, default=0, help="0 means all rows")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = build_url_analysis(args.stable_articles, args.out_dir, args.limit)
    print(json.dumps({"rows": summary["rows"], "publish_time_found": summary["publish_time_found"], "status_counts": summary["status_counts"], "summary": str(args.out_dir / "url_dates_summary.json")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
