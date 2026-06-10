#!/usr/bin/env python3
"""Audit Stage 7 skipped articles and release-pack input risk buckets.

This script is intentionally bounded: it reads the release index.jsonl and,
optionally, one explicit Stage 7 run root. It does not walk D: roots.
"""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path
from typing import Any


def read_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                yield json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{line_no}: {exc}") from exc


def bucket_main_chars(chars: int) -> str:
    if chars <= 0:
        return "0"
    if chars < 280:
        return "1-279"
    if chars < 1000:
        return "280-999"
    return "1000+"


def audit_release_index(index_path: Path) -> dict[str, Any]:
    counters = collections.Counter()
    quality = collections.Counter()
    quality_by_risk = collections.Counter()
    account_by_risk = collections.Counter()
    warning_count = collections.Counter()
    main_buckets = collections.Counter()
    image_buckets = collections.Counter()
    samples: list[dict[str, Any]] = []

    for row in read_jsonl(index_path):
        counters["total"] += 1
        q = str(row.get("quality_grade") or "")
        quality[q] += 1
        warnings = int(row.get("warning_count") or 0)
        local_images = int(row.get("local_image_count") or 0)
        main_chars = int(row.get("main_content_chars") or 0)
        account = str(row.get("account") or "")

        warning_count[str(warnings)] += 1
        main_buckets[bucket_main_chars(main_chars)] += 1
        image_buckets[str(local_images)] += 1

        if main_chars < 280:
            counters["main_lt_280"] += 1
            quality_by_risk[(q, "main_lt_280")] += 1
        if local_images == 0:
            counters["local_images_0"] += 1
            quality_by_risk[(q, "local_images_0")] += 1
        if main_chars < 280 and local_images == 0:
            counters["likely_empty_shell"] += 1
            quality_by_risk[(q, "likely_empty_shell")] += 1
            account_by_risk[account] += 1
            if len(samples) < 20:
                samples.append({
                    "account": account,
                    "token": row.get("token"),
                    "title": row.get("title"),
                    "quality_grade": q,
                    "warning_count": warnings,
                    "local_image_count": local_images,
                    "main_content_chars": main_chars,
                    "markdown_path": row.get("markdown_path"),
                })

    return {
        "index_path": str(index_path),
        "counters": dict(counters),
        "quality": dict(quality),
        "warning_count": dict(warning_count),
        "main_content_buckets": dict(main_buckets),
        "local_image_count_top": dict(image_buckets.most_common(20)),
        "quality_by_risk": {f"{k[0]}:{k[1]}": v for k, v in quality_by_risk.items()},
        "top_accounts_likely_empty_shell": dict(account_by_risk.most_common(20)),
        "samples_likely_empty_shell": samples,
    }


def audit_stage7_run(run_root: Path) -> dict[str, Any]:
    result_files = sorted(run_root.glob("shard*/speedtest/ER_*.json"))
    status_counts = collections.Counter()
    skip_reasons = collections.Counter()
    skip_accounts = collections.Counter()
    files: list[dict[str, Any]] = []

    for path in result_files:
        data = json.loads(path.read_text(encoding="utf-8"))
        summary = data.get("summary") or {}
        files.append({
            "path": str(path),
            "manifest_total": summary.get("manifest_total"),
            "done": summary.get("done"),
            "skipped_with_reason": summary.get("skipped_with_reason"),
            "fail": summary.get("fail"),
            "verdict": summary.get("verdict"),
            "warnings": summary.get("warnings") or {},
        })
        for row in data.get("results") or []:
            status = str(row.get("status") or "")
            status_counts[status] += 1
            reason = str(row.get("skip_reason") or "")
            if reason:
                skip_reasons[reason] += 1
                skip_accounts[str(row.get("source_account") or "")] += 1

    return {
        "run_root": str(run_root),
        "result_file_count": len(result_files),
        "status_counts": dict(status_counts),
        "skip_reasons": dict(skip_reasons),
        "top_skip_accounts": dict(skip_accounts.most_common(20)),
        "files": files,
    }


def write_markdown(report: dict[str, Any], path: Path) -> None:
    release = report["release_index"]
    run = report.get("stage7_run")
    lines = [
        "# Stage 7 Skip Audit",
        "",
        f"- index: `{release['index_path']}`",
        f"- total: {release['counters'].get('total', 0)}",
        f"- likely_empty_shell: {release['counters'].get('likely_empty_shell', 0)}",
        f"- main_lt_280: {release['counters'].get('main_lt_280', 0)}",
        f"- local_images_0: {release['counters'].get('local_images_0', 0)}",
        "",
        "## Quality",
    ]
    for key, value in sorted(release["quality"].items()):
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Top Empty-Shell Accounts"])
    for key, value in release["top_accounts_likely_empty_shell"].items():
        lines.append(f"- {key}: {value}")
    if run:
        lines.extend([
            "",
            "## Stage 7 Run",
            f"- run_root: `{run['run_root']}`",
            f"- result_file_count: {run['result_file_count']}",
            f"- skip_reasons: `{json.dumps(run['skip_reasons'], ensure_ascii=False)}`",
            f"- status_counts: `{json.dumps(run['status_counts'], ensure_ascii=False)}`",
        ])
    lines.extend(["", "## Sample Likely Empty Shells"])
    for sample in release["samples_likely_empty_shell"]:
        lines.append(
            f"- {sample['account']} / {sample['token']} / {sample['quality_grade']} / "
            f"main={sample['main_content_chars']} images={sample['local_image_count']} / {sample['title']}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit release-pack and Stage 7 skip reasons")
    parser.add_argument("--index", default=r"D:\DDownload\_llm_release_v2\index.jsonl")
    parser.add_argument("--stage7-run-root", default=None)
    parser.add_argument("--out-json", default=None)
    parser.add_argument("--out-md", default=None)
    args = parser.parse_args(argv)

    report: dict[str, Any] = {
        "release_index": audit_release_index(Path(args.index)),
    }
    if args.stage7_run_root:
        report["stage7_run"] = audit_stage7_run(Path(args.stage7_run_root))

    if args.out_json:
        Path(args.out_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out_json).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.out_md:
        Path(args.out_md).parent.mkdir(parents=True, exist_ok=True)
        write_markdown(report, Path(args.out_md))

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
