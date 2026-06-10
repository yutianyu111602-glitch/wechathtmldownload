#!/usr/bin/env python3
"""Calibration report wrapper for the DeepSeek hybrid scorer.

Reads Flash pilot JSONL artifacts, runs the deterministic scorer,
and writes a human-readable calibration report. Refuses missing
Flash files and does not scan D-drive roots.

Usage:
  python scripts/deepseek_hybrid_calibration_report.py \
    --flash-jsonl reports/deepseek_flash_pilot_20260509_500/flash_rows.jsonl \
    --out-dir reports/deepseek_hybrid_score_calibration_20260509
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
STAGE7_ROOT = SCRIPT_DIR.parent
if str(STAGE7_ROOT) not in sys.path:
    sys.path.insert(0, str(STAGE7_ROOT))

from scripts.deepseek_hybrid_scorer import score_flash_jsonl  # noqa: E402


FORBIDDEN_ROOTS = {"D:\\", "D:/", "D:", "D:\\DDownload", "D:/DDownload", "D:\\aidata", "D:/aidata"}


def _is_safe_path(value: str) -> bool:
    path = str(Path(value).resolve())
    for forbidden in FORBIDDEN_ROOTS:
        if path == forbidden or path.startswith(forbidden.rstrip("/\\") + "\\") or path.startswith(forbidden.rstrip("/\\") + "/"):
            return False
    return True


def build_report(summary: dict) -> str:
    lines = [
        "# DeepSeek Hybrid Calibration Report",
        "",
        f"- generated_at: {summary['generated_at']}",
        f"- processed_rows: {summary['processed_rows']}",
        f"- pro_upgrade_ratio: {summary['pro_upgrade_ratio']}",
        f"- target_band_status: {summary['target_band_status']}",
        f"- target_pro_min: {summary['target_pro_min']}",
        f"- target_pro_max: {summary['target_pro_max']}",
        "",
        "## Decision Counts",
        "",
    ]
    for decision, count in summary["decision_counts"].items():
        lines.append(f"- {decision}: {count}")

    lines.extend([
        "",
        "## Aggregate Gates",
        "",
    ])
    ag = summary["aggregate_metrics"]
    for key in ("api_ok_rate", "parse_ok_rate", "schema_ok_rate", "evidence_hit_rate", "zero_both_rate"):
        lines.append(f"- {key}: {ag[key]}")
    lines.append(f"- long_article_count: {ag.get('long_article_count', 0)}")
    lines.append(f"- high_value_low_output_count: {ag.get('high_value_low_output_count', 0)}")

    lines.extend([
        "",
        "## Thresholds",
        "",
    ])
    for key, value in summary["thresholds"].items():
        lines.append(f"- {key}: {value}")

    lines.extend([
        "",
        "## Source Files",
        "",
    ])
    for src in summary["source_files"]:
        lines.append(f"- `{src}`")

    lines.extend([
        "",
        "## Pro Reasons Breakdown",
        "",
        "Count reasons from pro_candidates.jsonl:",
        "",
        "```powershell",
        "Get-Content pro_candidates.jsonl | ConvertFrom-Json | ForEach-Object { $_.routing.reasons } | Group-Object | Sort-Object Count -Descending | Format-Table Name,Count",
        "```",
        "",
        "## Output Files",
        "",
    ])
    for name, opath in summary["outputs"].items():
        lines.append(f"- {name}: `{opath}`")

    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--flash-jsonl", action="append", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--long-chars", type=int, default=5000)
    parser.add_argument("--zero-both-min-chars", type=int, default=512)
    parser.add_argument("--evidence-pro-threshold", type=float, default=0.9)
    parser.add_argument("--accept-evidence-threshold", type=float, default=0.98)
    parser.add_argument("--image-heavy-min-images", type=int, default=2)
    parser.add_argument("--target-pro-min", type=float, default=0.10)
    parser.add_argument("--target-pro-max", type=float, default=0.20)
    args = parser.parse_args(argv)

    paths = [Path(value) for value in args.flash_jsonl]
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        raise SystemExit(f"missing flash jsonl file(s): {missing}")

    for value in args.flash_jsonl:
        if not _is_safe_path(value):
            raise SystemExit(f"forbidden path (D-drive root scan not allowed): {value}")

    out_dir = Path(args.out_dir)
    if not _is_safe_path(str(out_dir)):
        raise SystemExit(f"forbidden output path: {out_dir}")

    print(f"Running hybrid scorer on {len(paths)} Flash file(s)...", flush=True)

    summary = score_flash_jsonl(
        flash_jsonl_paths=paths,
        out_dir=out_dir,
        high_value_accounts=set(),  # use defaults
        long_chars=args.long_chars,
        zero_both_min_chars=args.zero_both_min_chars,
        evidence_pro_threshold=args.evidence_pro_threshold,
        accept_evidence_threshold=args.accept_evidence_threshold,
        image_heavy_min_images=args.image_heavy_min_images,
        target_pro_min=args.target_pro_min,
        target_pro_max=args.target_pro_max,
    )

    report_path = out_dir / "calibration_report.md"
    report_path.write_text(build_report(summary), encoding="utf-8")
    print(f"Report written: {report_path}", flush=True)

    # Print one-line summary
    print(
        f"rows={summary['processed_rows']} "
        f"accept={summary['decision_counts'].get('accept_flash', 0)} "
        f"pro={summary['decision_counts'].get('pro_reextract', 0)} "
        f"mac={summary['decision_counts'].get('mac_gpt_triage', 0)} "
        f"pro_ratio={summary['pro_upgrade_ratio']} "
        f"band={summary['target_band_status']}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
