#!/usr/bin/env python3
"""Run a PRD-16 public Bandcamp profile canary."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from crawl_soundcloud_profiles import run_profile_canary  # noqa: E402


DEFAULT_CANDIDATES = Path("reports/social_deep_candidates_20260515/bandcamp_urls.jsonl")
DEFAULT_OUT_DIR = Path("reports/bandcamp_canary_20260515")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--expected-min-profiles", type=int, default=5)
    parser.add_argument("--timeout-sec", type=float, default=12.0)
    parser.add_argument("--max-bytes", type=int, default=256_000)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    summary = run_profile_canary(
        candidates_path=args.candidates,
        out_dir=args.out_dir,
        platform="bandcamp",
        limit=args.limit,
        expected_min_profiles=args.expected_min_profiles,
        timeout_sec=args.timeout_sec,
        max_bytes=args.max_bytes,
    )
    print(
        json.dumps(
            {
                "decision": summary["decision"],
                "profiles_reachable": summary["profiles_reachable"],
                "summary": str(args.out_dir / "bandcamp_profile_canary_summary.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if summary["ok"] else 1


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
