from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import db2_outlink_recovery_preflight_s126 as preflight


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Container-safe read-only DB2 probe")
    parser.add_argument("--live-db", type=Path, default=Path("/db2-data/atlas_swarm_data.sqlite"))
    parser.add_argument("--active-workers", type=int, default=0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = preflight.collect_preflight(args.live_db, active_workers=args.active_workers)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["integrity"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
