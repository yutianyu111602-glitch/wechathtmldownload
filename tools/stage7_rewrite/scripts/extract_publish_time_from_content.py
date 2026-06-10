"""Extract publish-time candidates from C-side article text fields.

This is report-only. It never treats event dates in titles as true publish time.
Only full dates with publish-specific context become publish-time candidates;
all other dates are kept as content date candidates for review.
"""

from __future__ import annotations

import argparse
import json
import re
import tempfile
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any


DEFAULT_STABLE_ARTICLES = Path(
    "reports/fullmap_47k_ready_text_authok_20260513_174006/"
    "stable_extract_v1/stable_articles.jsonl"
)
DEFAULT_OUT_DIR = Path("reports/publish_time_content_extraction_20260515")
SCHEMA_VERSION = "stage7_publish_time_content_extraction.v1"
FULL_DATE_RE = re.compile(
    r"(?P<year>20\d{2})\s*(?:[-/.年])\s*(?P<month>1[0-2]|0?[1-9])\s*(?:[-/.月])\s*(?P<day>3[01]|[12]\d|0?[1-9])\s*日?"
)
COMPACT_DATE_RE = re.compile(r"(?<!\d)(?P<year>20\d{2})(?P<month>0[1-9]|1[0-2])(?P<day>0[1-9]|[12]\d|3[01])(?!\d)")
MONTH_DAY_RE = re.compile(r"(?<!\d)(?P<month>1[0-2]|0?[1-9])\s*(?:[-/.月])\s*(?P<day>3[01]|[12]\d|0?[1-9])\s*日?(?!\d)")
PUBLISH_CONTEXT = (
    "本文发表于",
    "本文发布于",
    "文章发表于",
    "文章发布于",
    "原文发表于",
    "原文发布于",
    "发布时间",
    "发布日期",
    "发文时间",
    "推文时间",
    "推送时间",
)
EVENT_CONTEXT = ("活动时间", "演出时间", "派对时间", "活动", "演出", "派对", "门票", "阵容", "lineup", "周五", "周六", "周日")


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
        raise ValueError(f"{label} must not point to D: for content publish-time extraction: {path}")


def valid_date(year: int, month: int, day: int) -> str:
    try:
        parsed = date(year, month, day)
    except ValueError:
        return ""
    if not (date(2015, 1, 1) <= parsed <= date(2026, 12, 31)):
        return ""
    return parsed.isoformat()


def context_window(text: str, start: int, end: int, size: int = 18) -> str:
    return text[max(0, start - size) : min(len(text), end + size)]


def context_score(context: str, source_field: str) -> tuple[str, float, bool]:
    has_publish = any(token in context for token in PUBLISH_CONTEXT)
    has_event = any(token.lower() in context.lower() for token in EVENT_CONTEXT)
    if has_publish and not has_event:
        return "publish_time_candidate", 0.75, False
    if has_publish:
        return "publish_time_candidate_needs_review", 0.55, True
    if source_field == "title" or has_event:
        return "content_date_only", 0.25, True
    return "content_date_candidate", 0.35, True


def iter_text_fields(article: dict[str, Any]) -> list[tuple[str, str]]:
    fields: list[tuple[str, str]] = []
    for key in ("title", "plain_text", "raw_text", "raw_content", "content", "summary", "vector_text"):
        text = first_text(article.get(key))
        if text:
            fields.append((key, text))
    for entity in article.get("entities") or []:
        if isinstance(entity, dict):
            for evidence in entity.get("evidence") or []:
                quote = first_text(evidence.get("quote") if isinstance(evidence, dict) else "")
                if quote:
                    fields.append(("entity_evidence", quote))
    for event in article.get("events") or []:
        if isinstance(event, dict):
            for key in ("time_text", "date_text", "name", "description"):
                text = first_text(event.get(key))
                if text:
                    fields.append((f"event_{key}", text))
            for evidence in event.get("evidence") or []:
                quote = first_text(evidence.get("quote") if isinstance(evidence, dict) else "")
                if quote:
                    fields.append(("event_evidence", quote))
    return fields


def date_candidates_from_text(source_field: str, text: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, int, int]] = set()
    for regex, precision in ((FULL_DATE_RE, "day"), (COMPACT_DATE_RE, "day")):
        for match in regex.finditer(text):
            iso = valid_date(int(match.group("year")), int(match.group("month")), int(match.group("day")))
            if not iso:
                continue
            key = (iso, match.start(), match.end())
            if key in seen:
                continue
            seen.add(key)
            context = context_window(text, match.start(), match.end())
            status, confidence, needs_review = context_score(context, source_field)
            candidates.append(
                {
                    "candidate_date": iso,
                    "date_precision": precision,
                    "source_field": source_field,
                    "original_text_matched": match.group(0),
                    "context": context,
                    "status": status,
                    "confidence": confidence,
                    "needs_manual_review": needs_review,
                }
            )
    for match in MONTH_DAY_RE.finditer(text):
        context = context_window(text, match.start(), match.end())
        status, confidence, needs_review = context_score(context, source_field)
        candidates.append(
            {
                "candidate_date": "",
                "date_precision": "month_day",
                "source_field": source_field,
                "original_text_matched": match.group(0),
                "context": context,
                "status": "content_date_only" if status.startswith("publish_time") else status,
                "confidence": min(confidence, 0.3),
                "needs_manual_review": True,
            }
        )
    return candidates


def extract_row(article: dict[str, Any]) -> dict[str, Any]:
    all_candidates: list[dict[str, Any]] = []
    for source_field, text in iter_text_fields(article):
        all_candidates.extend(date_candidates_from_text(source_field, text[:3000]))
    all_candidates.sort(
        key=lambda item: (
            0 if str(item["status"]).startswith("publish_time_candidate") else 1,
            -float(item["confidence"]),
            0 if item["source_field"] != "title" else 1,
        )
    )
    best = all_candidates[0] if all_candidates else {}
    status = first_text(best.get("status")) or "no_date_found"
    publish_time = ""
    publish_time_source = ""
    if status == "publish_time_candidate" and first_text(best.get("candidate_date")):
        publish_time = best["candidate_date"]
        publish_time_source = f"content.{best['source_field']}"
    return {
        "schema_version": SCHEMA_VERSION,
        "article_uid": first_text(article.get("article_uid")),
        "article_id": first_text(article.get("article_id")),
        "source_account": first_text(article.get("source_account")),
        "title": first_text(article.get("title")),
        "status": status,
        "publish_time": publish_time,
        "publish_time_source": publish_time_source,
        "publish_time_confidence": float(best.get("confidence") or 0.0),
        "candidate_date": first_text(best.get("candidate_date")),
        "date_precision": first_text(best.get("date_precision")),
        "candidate_source": first_text(best.get("source_field")),
        "original_text_matched": first_text(best.get("original_text_matched")),
        "context": first_text(best.get("context")),
        "needs_manual_review": bool(best.get("needs_manual_review", True)),
        "candidate_count": len(all_candidates),
        "writes": "reports_only",
    }


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
        "# Publish-Time Content Extraction",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- rows: `{summary['rows']}`",
        f"- source: `{summary['stable_articles']}`",
        f"- limit: `{summary['limit']}`",
        "",
        "## Status Counts",
        "",
    ]
    for key, value in summary["status_counts"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- C-side report-only extraction.",
            "- Title/event dates are not promoted to publish_time.",
            "- No D: scan, no API, no DB writes, no publish.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def build_content_index(stable_articles: Path, out_dir: Path, limit: int = 10000) -> dict[str, Any]:
    reject_d_path(stable_articles, "stable_articles")
    reject_d_path(out_dir, "out_dir")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "content_dates.jsonl"
    tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
    status_counts: Counter[str] = Counter()
    rows = 0
    publish_candidates = 0
    with stable_articles.open("r", encoding="utf-8") as source, tmp_path.open("w", encoding="utf-8") as out:
        for line in source:
            if limit and rows >= limit:
                break
            stripped = line.strip()
            if not stripped:
                continue
            row = extract_row(json.loads(stripped))
            status_counts[row["status"]] += 1
            if row["publish_time"]:
                publish_candidates += 1
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
        "publish_time_candidates": publish_candidates,
        "status_counts": dict(sorted(status_counts.items())),
        "content_dates_path": str(out_path),
        "writes": "reports_only",
    }
    write_json(out_dir / "content_dates_summary.json", summary)
    write_summary_md(out_dir / "content_dates_summary.md", summary)
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stable-articles", type=Path, default=DEFAULT_STABLE_ARTICLES)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--limit", type=int, default=10000, help="0 means all rows")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = build_content_index(args.stable_articles, args.out_dir, args.limit)
    print(
        json.dumps(
            {
                "rows": summary["rows"],
                "publish_time_candidates": summary["publish_time_candidates"],
                "status_counts": summary["status_counts"],
                "summary": str(args.out_dir / "content_dates_summary.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
