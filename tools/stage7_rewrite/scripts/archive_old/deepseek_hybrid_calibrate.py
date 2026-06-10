#!/usr/bin/env python3
"""Calibration report wrapper for DeepSeek hybrid scoring.

Reads one or more Flash pilot output directories, runs the scorer, and produces
a calibration summary suitable for gate decisions. Refuses missing Flash files.
Does not scan D-drive roots or write production state.
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

from scripts.deepseek_hybrid_scorer import (  # noqa: E402
    DEFAULT_HIGH_VALUE_ACCOUNTS,
    score_flash_jsonl,
)


def find_flash_jsonl(dirs: list[Path]) -> list[Path]:
    """Find flash_rows.jsonl in each given directory."""
    found: list[Path] = []
    for d in dirs:
        candidate = d / "flash_rows.jsonl"
        if candidate.exists():
            found.append(candidate)
        else:
            # Also try flash_rows.partial.jsonl for incomplete runs
            partial = d / "flash_rows.partial.jsonl"
            if partial.exists():
                found.append(partial)
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--flash-dir", action="append", required=True, help="Flash output directory")
    parser.add_argument("--flash-jsonl", action="append", default=[], help="Direct flash JSONL path")
    parser.add_argument("--out-dir", required=True, help="Output directory for calibration report")
    parser.add_argument("--high-value-account", action="append", default=[])
    parser.add_argument("--no-default-high-value-accounts", action="store_true")
    parser.add_argument("--long-chars", type=int, default=5000)
    parser.add_argument("--zero-both-min-chars", type=int, default=512)
    parser.add_argument("--evidence-pro-threshold", type=float, default=0.9)
    parser.add_argument("--accept-evidence-threshold", type=float, default=0.98)
    parser.add_argument("--image-heavy-min-images", type=int, default=2)
    parser.add_argument("--target-pro-min", type=float, default=0.10)
    parser.add_argument("--target-pro-max", type=float, default=0.20)
    args = parser.parse_args(argv)

    paths: list[Path] = [Path(p) for p in args.flash_jsonl]
    for d in args.flash_dir:
        paths.extend(find_flash_jsonl([Path(d)]))
    paths = [p for p in paths if p.exists()]

    if not paths:
        raise SystemExit("no flash_rows.jsonl found in any --flash-dir; "
                         "run the Flash pilot first or pass --flash-jsonl directly")

    high_value_accounts = set(args.high_value_account or [])
    if not args.no_default_high_value_accounts:
        high_value_accounts.update(DEFAULT_HIGH_VALUE_ACCOUNTS)

    print(f"scoring {len(paths)} flash jsonl(s): {[str(p) for p in paths]}", file=sys.stderr)

    summary = score_flash_jsonl(
        flash_jsonl_paths=paths,
        out_dir=Path(args.out_dir),
        high_value_accounts=high_value_accounts,
        long_chars=args.long_chars,
        zero_both_min_chars=args.zero_both_min_chars,
        evidence_pro_threshold=args.evidence_pro_threshold,
        accept_evidence_threshold=args.accept_evidence_threshold,
        image_heavy_min_images=args.image_heavy_min_images,
        target_pro_min=args.target_pro_min,
        target_pro_max=args.target_pro_max,
    )

    print(json.dumps({"ok": True, **summary}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
