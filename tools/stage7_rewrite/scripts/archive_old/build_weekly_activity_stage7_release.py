"""Build a bounded Stage7 input release for weekly activity candidates.

The general overnight release is intentionally mixed across historical lanes.
Weekly recommendations need a separate, evidence-preserving release whose
articles are selected by the weekly activity queue tokens. This script only
copies the small whitelisted article files Stage7 needs; it never fetches web
pages and never writes vector, graph, or DB targets.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(r"D:\downstream_results\stage7_rewrite\longrun")
DEFAULT_WEEKLY_QUEUE = ROOT / "WEEKLY_ACTIVITY_QUEUE_20260507" / "weekly_activity_queue.jsonl"
DEFAULT_INTAKE_MANIFEST = ROOT / "LLM_INTAKE_MANIFEST_20260507" / "llm_intake_manifest.json"
DEFAULT_OUT_DIR = ROOT / "WEEKLY_ACTIVITY_STAGE7_RELEASE_20260507"

SAFE_COPY_FILES = (
    "llm_input.md",
    "meta.json",
    "sidecar.json",
    "quality_report.json",
    "assets.json",
    "poster_ocr.json",
)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def load_intake_rows(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("rows")
    if not isinstance(rows, list):
        raise ValueError(f"intake manifest has no rows list: {path}")
    return [r for r in rows if isinstance(r, dict)]


def safe_segment(value: Any) -> str:
    text = str(value or "").strip() or "_"
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:120] or "_"


def parse_date(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    match = re.search(r"\d{4}-\d{2}-\d{2}", text)
    return match.group(0) if match else text


def quality_rank(row: dict[str, Any]) -> int:
    verdict = str(row.get("verdict") or row.get("quality") or "").lower()
    if verdict == "ready":
        return 0
    if verdict == "review":
        return 1
    return 2


def build_release(
    weekly_queue: Path,
    intake_manifest: Path,
    out_dir: Path,
    limit: int,
    dry_run: bool = False,
) -> dict[str, Any]:
    weekly_rows = load_jsonl(weekly_queue)
    weekly_by_token = {str(r.get("token") or ""): r for r in weekly_rows if r.get("token")}
    intake_rows = load_intake_rows(intake_manifest)

    candidates: list[dict[str, Any]] = []
    unmatched_tokens = set(weekly_by_token)
    for row in intake_rows:
        token = str(row.get("token") or row.get("article_id") or "")
        if not token or token not in weekly_by_token:
            continue
        artifact_dir = Path(str(row.get("artifact_dir") or ""))
        llm_input = artifact_dir / "llm_input.md"
        if not artifact_dir.exists() or not llm_input.exists():
            continue
        weekly = weekly_by_token[token]
        merged = dict(row)
        merged["_weekly"] = weekly
        merged["_token"] = token
        merged["_post_date"] = parse_date(weekly.get("post_date") or row.get("post_date") or row.get("publish_time"))
        candidates.append(merged)
        unmatched_tokens.discard(token)

    candidates.sort(
        key=lambda r: (
            quality_rank(r),
            str(r.get("_post_date") or ""),
            int(r.get("llm_chars") or 0),
            str(r.get("account_key") or ""),
            str(r.get("_token") or ""),
        ),
        reverse=True,
    )
    # Put quality back in ascending order while keeping newest/highest-text first inside quality buckets.
    candidates.sort(key=quality_rank)
    selected = candidates[: max(0, limit)]

    articles_dir = out_dir / "articles"
    copied_rows: list[dict[str, Any]] = []
    file_counts: dict[str, int] = {name: 0 for name in SAFE_COPY_FILES}

    if not dry_run:
        articles_dir.mkdir(parents=True, exist_ok=True)

    for row in selected:
        token = str(row.get("_token") or "")
        account = safe_segment(row.get("account_key") or row.get("account") or row.get("source_account"))
        source_kind = safe_segment(row.get("source_kind") or "weekly_activity")
        src_dir = Path(str(row.get("artifact_dir") or ""))
        dst_dir = articles_dir / source_kind / account / safe_segment(token)
        if not dry_run:
            dst_dir.mkdir(parents=True, exist_ok=True)
        copied: list[str] = []
        for name in SAFE_COPY_FILES:
            src = src_dir / name
            if src.exists() and src.is_file():
                if not dry_run:
                    shutil.copy2(src, dst_dir / name)
                file_counts[name] += 1
                copied.append(name)
        weekly = row.get("_weekly") or {}
        copied_rows.append(
            {
                "queue_id": weekly.get("queue_id", ""),
                "account": account,
                "token": token,
                "title": weekly.get("title") or row.get("title", ""),
                "post_date": weekly.get("post_date") or row.get("post_date", ""),
                "source_url": weekly.get("source_url") or row.get("source_url", ""),
                "source_kind": row.get("source_kind", ""),
                "quality": row.get("verdict") or row.get("quality") or "",
                "llm_chars": row.get("llm_chars", 0),
                "source_artifact_dir": str(src_dir),
                "release_article_dir": str(dst_dir),
                "copied_files": copied,
            }
        )

    summary = {
        "schema_version": "weekly_activity_stage7_release.v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "dry_run": dry_run,
        "weekly_queue": str(weekly_queue),
        "intake_manifest": str(intake_manifest),
        "out_dir": str(out_dir),
        "articles_dir": str(articles_dir),
        "weekly_total": len(weekly_rows),
        "intake_rows": len(intake_rows),
        "matched_intake_rows": len(candidates),
        "selected_articles": len(selected),
        "unmatched_weekly_tokens": len(unmatched_tokens),
        "quality_counts": {},
        "file_counts": file_counts,
        "paths": {
            "manifest_json": str(out_dir / "manifest.json"),
            "index_jsonl": str(out_dir / "index.jsonl"),
            "unmatched_jsonl": str(out_dir / "unmatched_weekly_tokens.jsonl"),
        },
    }
    for row in selected:
        quality = str(row.get("verdict") or row.get("quality") or "unknown")
        summary["quality_counts"][quality] = summary["quality_counts"].get(quality, 0) + 1

    if not dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "index.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in copied_rows),
            encoding="utf-8",
        )
        (out_dir / "unmatched_weekly_tokens.jsonl").write_text(
            "".join(json.dumps({"token": t, **weekly_by_token[t]}, ensure_ascii=False) + "\n" for t in sorted(unmatched_tokens)),
            encoding="utf-8",
        )
        (out_dir / "manifest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (out_dir / "SUMMARY.md").write_text(
            "\n".join(
                [
                    "# Weekly Activity Stage7 Release",
                    "",
                    f"- generated_at: `{summary['generated_at']}`",
                    f"- weekly_total: `{summary['weekly_total']}`",
                    f"- matched_intake_rows: `{summary['matched_intake_rows']}`",
                    f"- selected_articles: `{summary['selected_articles']}`",
                    f"- unmatched_weekly_tokens: `{summary['unmatched_weekly_tokens']}`",
                    f"- articles_dir: `{articles_dir}`",
                    "",
                ]
            ),
            encoding="utf-8",
        )

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a weekly-activity-only Stage7 release from local artifacts")
    parser.add_argument("--weekly-queue", type=Path, default=DEFAULT_WEEKLY_QUEUE)
    parser.add_argument("--intake-manifest", type=Path, default=DEFAULT_INTAKE_MANIFEST)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    summary = build_release(
        weekly_queue=args.weekly_queue,
        intake_manifest=args.intake_manifest,
        out_dir=args.out_dir,
        limit=args.limit,
        dry_run=args.dry_run,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
