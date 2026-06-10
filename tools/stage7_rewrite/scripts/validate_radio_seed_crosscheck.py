#!/usr/bin/env python3
"""Cross-check imported radio seed URLs against live crawl rows and audio URLs.

This is the P1 bridge between legacy dj-dataset evidence and current public
source validation. It reads the seed JSONL and bounded Camofox crawl outputs,
then checks that seeded pages were fetched and expected audio URLs still respond.
It is report-only: no graph/vector/DB writes, no paid API, no D: scan.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import requests


DEFAULT_SEED = Path("reports/p1_dj_dataset_import_20260514/radio_canary_seed_urls.jsonl")
DEFAULT_OUT_DIR = Path("reports/p1_radio_social_seeded_canary_20260514")


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for P1 crosscheck: {path}")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_d_path(path, "jsonl")
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                row = json.loads(stripped)
                if isinstance(row, dict):
                    rows.append(row)
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def compact(text: str) -> str:
    return " ".join(str(text or "").casefold().split())


def title_matches(seed: dict[str, Any], crawl: dict[str, Any] | None) -> bool:
    if not crawl:
        return False
    expected = compact(seed.get("expected_title") or seed.get("expected_artist_name") or "")
    if not expected:
        return True
    haystack = compact(f"{crawl.get('title', '')} {crawl.get('body_excerpt', '')}")
    if expected in haystack:
        return True
    # Allow show names that differ only by title/artist split.
    artist = compact(seed.get("expected_artist_name") or "")
    return bool(artist and artist in haystack)


def audio_url_ok(url: str, timeout: int) -> dict[str, Any]:
    try:
        response = requests.head(url, allow_redirects=True, timeout=timeout)
        if response.status_code in {405, 403}:
            response = requests.get(url, headers={"Range": "bytes=0-0"}, stream=True, timeout=timeout)
        return {
            "url": url,
            "ok": 200 <= response.status_code < 400,
            "status_code": response.status_code,
            "content_type": response.headers.get("content-type", ""),
        }
    except Exception as exc:
        return {"url": url, "ok": False, "status_code": None, "error": str(exc)}


def crosscheck(seed_file: Path, crawl_files: list[Path], out_dir: Path, timeout: int) -> dict[str, Any]:
    reject_d_path(seed_file, "seed_file")
    reject_d_path(out_dir, "out_dir")
    seeds = read_jsonl(seed_file)
    crawled_rows: dict[str, dict[str, Any]] = {}
    for crawl_file in crawl_files:
        for row in read_jsonl(crawl_file):
            crawled_rows[str(row.get("page_url") or "")] = row

    rows: list[dict[str, Any]] = []
    counts = {
        "seeds": len(seeds),
        "crawled_matches": 0,
        "title_matches": 0,
        "audio_checked": 0,
        "audio_ok": 0,
        "audio_failed": 0,
    }
    for seed in seeds:
        page_url = str(seed.get("page_url") or "")
        crawl = crawled_rows.get(page_url)
        has_crawl = crawl is not None
        title_ok = title_matches(seed, crawl)
        audio_checks = []
        for url in seed.get("expected_audio_links") or []:
            if not url:
                continue
            check = audio_url_ok(str(url), timeout)
            audio_checks.append(check)
            counts["audio_checked"] += 1
            if check["ok"]:
                counts["audio_ok"] += 1
            else:
                counts["audio_failed"] += 1
        if has_crawl:
            counts["crawled_matches"] += 1
        if title_ok:
            counts["title_matches"] += 1
        rows.append(
            {
                "source_family": seed.get("source_family"),
                "page_url": page_url,
                "has_crawl": has_crawl,
                "title_match": title_ok,
                "expected_title": seed.get("expected_title") or "",
                "crawl_title": crawl.get("title") if crawl else "",
                "audio_checks": audio_checks,
                "audio_ok_count": sum(1 for item in audio_checks if item["ok"]),
            }
        )

    blockers = []
    if counts["crawled_matches"] == 0:
        blockers.append("no seeded pages were crawled")
    if counts["audio_checked"] and counts["audio_ok"] == 0:
        blockers.append("no expected audio URL responded")
    if counts["audio_failed"] and counts["audio_ok"] < max(1, counts["audio_checked"] // 2):
        blockers.append("too many expected audio URLs failed")
    warnings = []
    if counts["crawled_matches"] < counts["seeds"]:
        warnings.append("not every seed was crawled; expected for bounded max-pages canaries")
    if counts["title_matches"] < counts["crawled_matches"]:
        warnings.append("some crawled pages did not match expected title/artist text")

    report = {
        "schema_version": "stage7_p1_radio_seed_crosscheck.v1",
        "generated_at": now_iso(),
        "ok": not blockers,
        "decision": "p1_seed_crosscheck_green" if not blockers else "p1_seed_crosscheck_blocked",
        "seed_file": str(seed_file),
        "crawl_files": [str(path) for path in crawl_files],
        "counts": counts,
        "rows": rows,
        "warnings": warnings,
        "blockers": blockers,
        "writes": "reports_only",
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "radio_seed_crosscheck.json", report)
    write_markdown(out_dir / "radio_seed_crosscheck.md", report)
    return report


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    counts = report["counts"]
    lines = [
        "# P1 Radio Seed Crosscheck",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- ok: `{report['ok']}`",
        f"- decision: `{report['decision']}`",
        f"- seeds: `{counts['seeds']}`",
        f"- crawled_matches: `{counts['crawled_matches']}`",
        f"- title_matches: `{counts['title_matches']}`",
        f"- audio_checked: `{counts['audio_checked']}`",
        f"- audio_ok: `{counts['audio_ok']}`",
        f"- audio_failed: `{counts['audio_failed']}`",
        "",
        "## Rows",
        "",
    ]
    for row in report["rows"]:
        lines.append(
            f"- `{row['source_family']}` `{row['page_url']}` crawl=`{row['has_crawl']}` "
            f"title=`{row['title_match']}` audio_ok=`{row['audio_ok_count']}`"
        )
    lines.extend(["", "## Warnings", ""])
    if report["warnings"]:
        for warning in report["warnings"]:
            lines.append(f"- `{warning}`")
    else:
        lines.append("- none")
    lines.extend(["", "## Blockers", ""])
    if report["blockers"]:
        for blocker in report["blockers"]:
            lines.append(f"- `{blocker}`")
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Reports only.",
            "- No graph/vector/DB write.",
            "- No paid API.",
            "- No D: scan.",
            "- No publish.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    report = crosscheck(args.seed_file, args.crawl_jsonl, args.out_dir, args.timeout)
    print(
        json.dumps(
            {
                "ok": report["ok"],
                "decision": report["decision"],
                "counts": report["counts"],
                "report": str(args.out_dir / "radio_seed_crosscheck.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["ok"] else 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-file", type=Path, default=DEFAULT_SEED)
    parser.add_argument("--crawl-jsonl", type=Path, action="append", required=True)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--timeout", type=int, default=15)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
