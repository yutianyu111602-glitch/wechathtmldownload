#!/usr/bin/env python3
"""Build weekly_entity_snapshot.json (read-only atlas bridge)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.stage7_rewrite.weekly_atlas_bridge.snapshot import build_snapshot_from_paths  # noqa: E402


DEFAULT_REGISTRY = REPO_ROOT / "tools/stage7_rewrite/registries/weekly_artists_seed.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--alias-export", type=Path, default=None)
    parser.add_argument("--publish-package", default="")
    parser.add_argument("--enable-vector-review", action="store_true")
    parser.add_argument("--qdrant-url", default="http://127.0.0.1:6333")
    args = parser.parse_args()

    qdrant_url = args.qdrant_url if args.enable_vector_review else None
    snapshot = build_snapshot_from_paths(
        args.current,
        args.registry,
        alias_export_path=args.alias_export,
        qdrant_url=qdrant_url,
        publish_package=args.publish_package,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(snapshot.get("stats") or {}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
