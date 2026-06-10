#!/usr/bin/env python3
"""Evaluate DeepSeek extraction on bounded local WeChat article exports.

This is a report-only harness for D:\\DDownload-style exports. It only reads
explicitly provided article/account directories, traverses to a bounded depth,
skips secret-looking paths, and reuses the weekly prompt/model scoring matrix.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import evaluate_weekly_deepseek_prompt_matrix as matrix  # noqa: E402


DEFAULT_OUT = Path("tools/stage7_rewrite/reports/ddownload_deepseek_prompt_matrix_20260518")
SECRET_NAME_RE = re.compile(r"secret|token|cookie|credential|private|key|recovery|password", re.I)
AGGREGATE_TITLE_RE = re.compile(r"一览|预览|安排|本周|月.*活动|月.*信号|schedule|calendar", re.I)
IMAGE_RE = re.compile(r"<img\b|data-src=|cdn_url|mmbiz\.qpic\.cn", re.I)
TAG_RE = re.compile(r"<[^>]+>")
FOLDER_DATE_RE = re.compile(r"(?<!\d)(20\d{2})-(\d{2})-(\d{2})")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8", errors="ignore"))


def safe_path(path: Path) -> bool:
    return not SECRET_NAME_RE.search(str(path))


def bounded_download_files(root: Path, *, max_depth: int, limit: int) -> list[Path]:
    if not root.exists() or not root.is_dir() or not safe_path(root):
        return []
    found: list[Path] = []

    def walk(path: Path, depth: int) -> None:
        if len(found) >= limit or depth > max_depth:
            return
        try:
            entries = list(os.scandir(path))
        except OSError:
            return
        for entry in entries:
            if len(found) >= limit:
                return
            child = Path(entry.path)
            if not safe_path(child):
                continue
            if entry.is_file() and child.name == "download.json":
                found.append(child)
            elif entry.is_dir() and depth < max_depth:
                walk(child, depth + 1)

    walk(root, 0)
    found.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
    return found[:limit]


def strip_html(value: str) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"(?is)<script.*?</script>|<style.*?</style>", " ", text)
    text = TAG_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if value not in (None, "", [], {}):
            return str(value).strip()
    return ""


def parse_date_hint(*values: Any) -> date | None:
    for value in values:
        text = str(value or "")
        match = FOLDER_DATE_RE.search(text)
        if match:
            try:
                return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
            except ValueError:
                pass
        match = re.search(r"(?<!\d)(20\d{2})[./年-](\d{1,2})[./月-](\d{1,2})", text)
        if match:
            try:
                return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
            except ValueError:
                pass
    return None


def infer_expected_event_dates(title: str, source_text: str, post_date: date | None, *, aggregate: bool) -> list[str]:
    year_hint = post_date.isoformat() if post_date else None
    title_dates = matrix.extract_explicit_dates(title, year_hint=year_hint)
    if title_dates:
        return title_dates
    if post_date:
        if re.search(r"今晚|今天|今日", title):
            return [post_date.isoformat()]
        if re.search(r"明晚|明天|明日", title):
            return [(post_date + timedelta(days=1)).isoformat()]
    if aggregate:
        return matrix.extract_explicit_dates(source_text, year_hint=year_hint)[:20]
    return []


def is_out_of_window(dates: list[str], *, window_start: str, window_days: int) -> bool:
    if not dates:
        return False
    start = date.fromisoformat(window_start)
    end = start + timedelta(days=window_days - 1)
    valid_dates: list[date] = []
    for value in dates:
        try:
            valid_dates.append(date.fromisoformat(value))
        except ValueError:
            continue
    return bool(valid_dates) and not any(start <= value <= end for value in valid_dates)


def article_from_download(path: Path) -> dict[str, Any] | None:
    if not safe_path(path):
        return None
    try:
        data = read_json(path)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    meta_path = path.with_name("metadata.json")
    meta = read_json(meta_path) if meta_path.exists() and safe_path(meta_path) else {}
    raw_path = path.with_name("raw.html")
    raw_html = raw_path.read_text(encoding="utf-8", errors="ignore") if raw_path.exists() and safe_path(raw_path) else ""
    html_text = first_text(data.get("content_noencode"), data.get("content"), raw_html)
    plain_text = strip_html(html_text)
    title = first_text(data.get("title"), meta.get("title"), path.parent.name)
    link = first_text(data.get("link"), data.get("url"), meta.get("link"))
    account = first_text(data.get("nickname"), meta.get("nickname"), meta.get("author_name"), data.get("author"), data.get("user_name"), path.parent.parent.name)
    create_time = first_text(data.get("create_time"), meta.get("create_time"))
    digest = first_text(data.get("desc"), data.get("digest"), meta.get("digest"))
    image_count = len(IMAGE_RE.findall(html_text)) + int(bool(first_text(data.get("cdn_url"), meta.get("cover"))))
    source_text = "\n".join(part for part in [title, digest, plain_text] if part)[:12000]
    if not title and not source_text:
        return None
    post_date = parse_date_hint(create_time, meta.get("create_time"), data.get("create_time"), path.parent.name)
    all_dates = matrix.extract_explicit_dates(source_text, year_hint=post_date.isoformat() if post_date else create_time)
    is_aggregate = bool(AGGREGATE_TITLE_RE.search(title))
    dates = infer_expected_event_dates(title, source_text, post_date, aggregate=is_aggregate)
    category = "aggregate_child" if is_aggregate else "complete_control"
    if image_count >= 8 and len(plain_text) < 1200:
        category = "image_heavy"
    return {
        "path": str(path),
        "account": account,
        "title": title,
        "link": link,
        "create_time": create_time,
        "post_date": post_date.isoformat() if post_date else "",
        "digest": digest,
        "plain_text_chars": len(plain_text),
        "image_count": image_count,
        "explicit_dates": dates[:20],
        "all_source_dates": all_dates[:30],
        "category": category,
        "source_text": source_text,
    }


def sample_from_article(article: dict[str, Any], *, window_start: str, window_days: int) -> dict[str, Any]:
    source_id = matrix.normalize_key(article.get("path"))[-80:] or matrix.normalize_key(article.get("title"))
    candidate = {
        "title": article.get("title"),
        "source_url": article.get("link"),
        "post_date": article.get("post_date") or article.get("create_time"),
        "event_date_text": article.get("explicit_dates"),
        "evidence": [article.get("title"), article.get("digest"), article.get("source_text")[:2000]],
    }
    aggregate = {}
    if article.get("category") == "aggregate_child":
        aggregate = {
            "event_count": max(2, min(8, len(article.get("explicit_dates") or []))),
            "parent_title": article.get("title"),
            "local_article_path": article.get("path"),
            "source_date_count": len(article.get("all_source_dates") or []),
        }
    sample = matrix.build_sample(
        category=article["category"],
        source_id=source_id,
        candidate=candidate,
        aggregate=aggregate,
        window_start=window_start,
        window_days=window_days,
    )
    sample["sample_id"] = f"ddownload:{article['category']}:{source_id}"
    expected_dates = list(article.get("explicit_dates") or [])
    sample["expected"]["dates"] = expected_dates
    sample["expected"]["out_of_window"] = is_out_of_window(
        expected_dates,
        window_start=window_start,
        window_days=window_days,
    )
    sample["expected"]["local_date_policy"] = (
        "title_or_post_relative_or_aggregate_dates_only"
        if expected_dates
        else "no_supported_activity_date"
    )
    sample["local_article"] = {
        key: article.get(key)
        for key in ("path", "account", "title", "link", "plain_text_chars", "image_count", "explicit_dates", "all_source_dates")
    }
    sample["source_text"] = article.get("source_text", "")
    return sample


def recompute_total(score: dict[str, Any], *, out_of_window: bool) -> float:
    total = (
        float(score.get("date_score") or 0) * 0.28
        + float(score.get("window_score") or 0) * 0.18
        + float(score.get("lineup_score") or 0) * 0.2
        + float(score.get("evidence_score") or 0) * 0.14
        + float(score.get("venue_score") or 0) * 0.12
        + float(score.get("aggregate_score") or 0) * 0.08
    )
    if out_of_window and float(score.get("window_score") or 0) == 0.0:
        total = min(total, 0.55)
    return round(total, 4)


def score_local_article_response(sample: dict[str, Any], parsed: Any, prompt_text: str = "") -> dict[str, Any]:
    score = matrix.score_response(sample, parsed, prompt_text)
    expected_dates = set(score.get("expected_dates") or [])
    returned_dates = set(score.get("returned_dates") or [])
    unexpected_dates = sorted(returned_dates - expected_dates)
    if expected_dates and unexpected_dates:
        score["unexpected_dates"] = unexpected_dates
        score["date_score"] = min(float(score.get("date_score") or 0), 0.7)
        score["total_score"] = recompute_total(
            score,
            out_of_window=bool((sample.get("expected") or {}).get("out_of_window")),
        )
    return score


def collect_articles(args: argparse.Namespace) -> list[dict[str, Any]]:
    articles: list[dict[str, Any]] = []
    seen: set[str] = set()
    for root in args.article_dir:
        files = bounded_download_files(root, max_depth=args.max_depth, limit=args.max_files_per_dir)
        for path in files:
            key = str(path.resolve()).lower()
            if key in seen:
                continue
            seen.add(key)
            article = article_from_download(path)
            if article:
                articles.append(article)
    for path in args.download_json:
        if not safe_path(path):
            continue
        article = article_from_download(path)
        if article and str(path.resolve()).lower() not in seen:
            articles.append(article)
    articles.sort(key=lambda row: (row.get("category") != "aggregate_child", row.get("path") or ""))
    return articles[: args.sample_limit] if args.sample_limit else articles


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--article-dir", type=Path, action="append", default=[], help="Explicit local account/article directory to sample.")
    parser.add_argument("--download-json", type=Path, action="append", default=[], help="Explicit download.json path to include.")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--window-start", default=matrix.DEFAULT_WINDOW_START)
    parser.add_argument("--window-days", type=int, default=matrix.DEFAULT_WINDOW_DAYS)
    parser.add_argument("--max-depth", type=int, default=2)
    parser.add_argument("--max-files-per-dir", type=int, default=8)
    parser.add_argument("--sample-limit", type=int, default=0)
    parser.add_argument("--endpoint", default=os.environ.get("DEEPSEEK_BASE_URL") or matrix.DEFAULT_ENDPOINT)
    parser.add_argument("--api-key", default=os.environ.get("DEEPSEEK_API_KEY"))
    parser.add_argument("--prompts", nargs="*", default=["yellowpage_gate_v3"], choices=list(matrix.PROMPT_VARIANTS))
    parser.add_argument("--max-concurrency", type=int, default=2)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--max-tokens", type=int, default=2200)
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument("--select-only", action="store_true")
    return parser.parse_args(argv)


def write_markdown(path: Path, articles: list[dict[str, Any]], samples: list[dict[str, Any]], summary: dict[str, Any], rows: list[dict[str, Any]], args: argparse.Namespace) -> None:
    lines = [
        "# DDownload DeepSeek Article Matrix",
        "",
        f"- generated_at: {datetime.now().isoformat(timespec='seconds')}",
        f"- article_dirs: {', '.join(str(p) for p in args.article_dir)}",
        f"- articles: {len(articles)}",
        f"- samples: {len(samples)}",
        f"- calls: {len(rows)}",
        f"- window: {args.window_start} + {args.window_days} days",
        "",
        "## Input Mix",
        "",
    ]
    by_category: dict[str, int] = {}
    for article in articles:
        by_category[article["category"]] = by_category.get(article["category"], 0) + 1
    for key, count in sorted(by_category.items()):
        lines.append(f"- {key}: `{count}`")
    lines.extend(["", "## Ranking", ""])
    lines.append("| rank | prompt | model combo | calls | json ok | avg score | date | lineup | evidence | latency | tokens |")
    lines.append("| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for idx, group in enumerate(summary.get("groups", []), start=1):
        lines.append(
            "| {rank} | {prompt} | {combo} | {count} | {json_ok}/{count} | {score:.4f} | {date:.2f} | {lineup:.2f} | {evidence:.2f} | {latency:.2f}s | {tokens} |".format(
                rank=idx,
                prompt=group["prompt_variant"],
                combo=group["matrix_name"],
                count=group["count"],
                json_ok=group["json_ok_count"],
                score=group["avg_score"],
                date=group["date_acc"],
                lineup=group["lineup_acc"],
                evidence=group["evidence_acc"],
                latency=group["avg_latency_sec"],
                tokens=group["total_tokens"],
            )
        )
    lines.extend(["", "## Sample Articles", ""])
    for sample in samples[:30]:
        local = sample.get("local_article") or {}
        lines.append(f"- `{sample['category']}` {local.get('account')} / {local.get('title')} / images={local.get('image_count')} / chars={local.get('plain_text_chars')}")
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- Secret-looking filenames are skipped by this harness.",
            "- This report is evaluation-only; it does not mutate release data or DDownload files.",
            "- Scores are heuristic for local raw articles because there is no full human ground truth.",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if not args.article_dir and not args.download_json:
        raise SystemExit("provide --article-dir or --download-json")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    articles = collect_articles(args)
    samples = [sample_from_article(article, window_start=args.window_start, window_days=args.window_days) for article in articles]
    (args.out_dir / "articles.json").write_text(json.dumps(articles, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.out_dir / "samples.json").write_text(json.dumps(samples, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.select_only:
        print(json.dumps({"articles": len(articles), "samples": len(samples), "out_dir": str(args.out_dir)}, ensure_ascii=False))
        return 0
    if not args.api_key:
        raise SystemExit("DEEPSEEK_API_KEY is not set")
    tasks = [
        matrix.make_call_task(
            sample,
            prompt_variant=prompt,
            matrix_name=matrix_name,
            model=model,
            thinking=thinking,
        )
        for sample in samples
        for prompt in args.prompts
        for matrix_name, model, thinking in matrix.MODEL_MATRIX
    ]
    raw_rows: list[dict[str, Any]] = []
    sample_by_id = {sample["sample_id"]: sample for sample in samples}
    from concurrent.futures import ThreadPoolExecutor, as_completed

    with ThreadPoolExecutor(max_workers=max(1, args.max_concurrency)) as executor:
        futures = [executor.submit(matrix.run_task, task, args) for task in tasks]
        for future in as_completed(futures):
            row = future.result()
            sample = sample_by_id[row["sample_id"]]
            row["score"] = (
                score_local_article_response(sample, row.get("parsed"), matrix.build_user_prompt(sample, row["prompt_variant"]))
                if row.get("json_ok")
                else {
                    "total_score": 0,
                    "date_score": 0,
                    "lineup_score": 0,
                    "evidence_score": 0,
                    "venue_score": 0,
                    "aggregate_score": 0,
                }
            )
            raw_rows.append(row)
            print(json.dumps({"done": len(raw_rows), "total": len(tasks), "sample": row["sample_id"], "combo": row["matrix_name"], "json": row.get("json_ok"), "score": row["score"].get("total_score")}, ensure_ascii=False))
    raw_rows.sort(key=lambda row: (row["prompt_variant"], row["matrix_name"], row["sample_id"]))
    matrix.write_jsonl(args.out_dir / "raw_results.jsonl", raw_rows)
    summary = matrix.summarize_results(raw_rows)
    (args.out_dir / "matrix_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(args.out_dir / "matrix_summary.md", articles, samples, summary, raw_rows, args)
    print(json.dumps({"out_dir": str(args.out_dir), "articles": len(articles), "calls": len(raw_rows), "best": summary["groups"][0] if summary.get("groups") else None}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
